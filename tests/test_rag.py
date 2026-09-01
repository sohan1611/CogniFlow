"""Tests for RAG retrieval invariants."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from app.models.enums import (
    Difficulty, TeachingMode, AssessmentType, AdaptationAction,
    SessionStatus, StudentOutcome, SystemFault, CORRECTNESS, is_student_evidence,
)
from app.models.errors import (
    CogniFlowError, InvalidEvidenceError, SkillGraphError, LimitExceededError,
)
from app.models.schemas import RetrievedChunk
from app.rag.chunker import MIN_CHUNK_CHARS, chunk_document
from app.rag.documents import parse_markdown
from app.rag.ingest import ingest_corpus
from app.rag.retriever import Retriever
from app.rag.store import VectorStore


def _write_markdown(
    directory: Path,
    name: str,
    *,
    skill: str | None,
    topic: str = "",
    unit: int | str = 1,
    body: str,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    skill_line = f"skill: {skill}\n" if skill is not None else ""
    path = directory / name
    path.write_text(
        (
            "---\n"
            "subject: python_fundamentals\n"
            f"unit: {unit}\n"
            f"topic: {topic}\n"
            f"{skill_line}"
            "difficulty: MEDIUM\n"
            "prerequisites: [intro]\n"
            "source: test corpus\n"
            "license: test\n"
            "---\n\n"
            f"{body}"
        ),
        encoding="utf-8",
    )
    return path


def _recursion_body() -> str:
    return (
        "# Recursion\n\n"
        "A recursive function calls itself on a smaller version of the same problem. "
        "A base case stops infinite recursion by returning without another recursive call. "
        "Progress toward the base case is what makes recursion terminate safely.\n\n"
        "When tracing recursion, write down each pending call and confirm that every call "
        "moves closer to the base case that stops infinite recursion."
    )


def _loops_body() -> str:
    return (
        "# Loops\n\n"
        "A loop repeats a block while a condition remains true. For loops iterate over "
        "items in a sequence, while while loops continue until their condition changes. "
        "Counters and accumulators are common loop patterns."
    )


def _build_corpus(directory: Path) -> Path:
    _write_markdown(directory, "01_recursion.md", skill="recursion", topic="recursion", body=_recursion_body())
    _write_markdown(directory, "02_loops.md", skill="loops", topic="loops", body=_loops_body())
    return directory


def test_parse_markdown_extracts_frontmatter_and_body_unit_as_str(tmp_path: Path) -> None:
    path = _write_markdown(
        tmp_path,
        "functions.md",
        skill="functions",
        topic="functions",
        unit=3,
        body="# Functions\n\nFunctions group reusable behavior.",
    )

    document = parse_markdown(path)

    assert document.meta.skill == "functions"
    assert document.meta.unit == "3"
    assert document.meta.source_file == "functions.md"
    assert "# Functions" in document.body


def test_parse_markdown_raises_when_skill_missing(tmp_path: Path) -> None:
    path = _write_markdown(
        tmp_path,
        "missing_skill.md",
        skill=None,
        body="# Missing\n\nThis document cannot be filtered.",
    )

    with pytest.raises(CogniFlowError):
        parse_markdown(path)


def test_chunk_document_is_heading_aware(tmp_path: Path) -> None:
    path = _write_markdown(
        tmp_path,
        "headings.md",
        skill="headings",
        body=(
            "# First\n\n"
            "First section material about definitions and examples.\n\n"
            "# Second\n\n"
            "Second section material about practice and transfer."
        ),
    )
    document = parse_markdown(path)

    chunks = chunk_document(document)

    assert len(chunks) == 2
    assert chunks[0].section == "First"
    assert "# Second" not in chunks[0].text
    assert chunks[1].section == "Second"
    assert "# First" not in chunks[1].text


def test_chunk_ids_are_stable_across_runs(tmp_path: Path) -> None:
    path = _write_markdown(tmp_path, "stable.md", skill="stable", body=_recursion_body())
    document = parse_markdown(path)

    first = chunk_document(document)
    second = chunk_document(document)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_short_trailing_fragments_merge_instead_of_becoming_stubs(tmp_path: Path) -> None:
    paragraphs = "\n\n".join(
        [
            "Large paragraph " + ("recursion progress and base case. " * 35),
            "Second paragraph " + ("recursive calls shrink toward a base case. " * 35),
            "short tail",
        ]
    )
    path = _write_markdown(tmp_path, "merge_tail.md", skill="recursion", body=f"# Tail\n\n{paragraphs}")
    document = parse_markdown(path)

    chunks = chunk_document(document)

    assert len(chunks) >= 1
    assert len(chunks[-1].text) >= MIN_CHUNK_CHARS
    assert "short tail" in chunks[-1].text


def test_ingest_then_count_positive(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")

    summary = ingest_corpus(corpus, store)

    assert summary["documents"] == 2
    assert summary["chunks"] > 0
    assert store.count() > 0


def test_reingest_is_idempotent(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")

    ingest_corpus(corpus, store)
    first_count = store.count()
    ingest_corpus(corpus, store)
    second_count = store.count()

    assert first_count > 0
    assert second_count == first_count


def test_query_with_skill_filter_returns_only_matching_skill_chunks(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")
    ingest_corpus(corpus, store)

    chunks = store.query("how do counters update in loops", skill="loops", k=4)

    assert chunks
    assert {chunk.skill for chunk in chunks} == {"loops"}


def test_semantic_relevance_returns_recursion_first(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")
    ingest_corpus(corpus, store)

    chunks = store.query("what stops infinite recursion", k=2)

    assert chunks
    assert chunks[0].skill == "recursion"


def test_citations_return_source_file_section_strings_that_resolve_to_chunks(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")
    ingest_corpus(corpus, store)
    evidence = Retriever(store).retrieve("what stops infinite recursion", skill="recursion")

    citations = evidence.citations()
    chunk_refs = {f"{chunk.source_file}#{chunk.section}" for chunk in evidence.chunks}

    assert citations
    assert citations == list(dict.fromkeys(citations))
    assert set(citations).issubset(chunk_refs)


def test_fallback_when_skill_filter_has_no_documents(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path / "corpus")
    store = VectorStore(path=tmp_path / "chroma")
    ingest_corpus(corpus, store)

    evidence = Retriever(store).retrieve("what stops infinite recursion", skill="arrays")

    assert evidence.used_fallback is True
    assert evidence.degraded is False
    assert evidence.chunks


def test_degraded_path_when_store_query_raises() -> None:
    class RaisingStore:
        def query(self, text: str, skill: str | None = None, k: int = 4) -> list[RetrievedChunk]:
            raise RuntimeError("store unavailable")

    retriever = Retriever(cast(Any, RaisingStore()))

    evidence = retriever.retrieve("anything", skill="recursion")

    assert evidence.degraded is True
    assert evidence.fault == SystemFault.RETRIEVAL_FAILURE
    assert evidence.chunks == []


def test_empty_collection_query_returns_empty_list(tmp_path: Path) -> None:
    store = VectorStore(path=tmp_path / "chroma")

    assert store.query("anything", k=4) == []
