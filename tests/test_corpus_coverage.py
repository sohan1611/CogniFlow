"""Every skill in the graph must have its own curriculum material.

Invariant: skill-filtered retrieval must never fall back for a skill the agent can
actually target.

WHY THIS TEST EXISTS
Retrieval degrades silently. When no document carries a skill's tag, the retriever
widens to an unfiltered search and returns *something* — so nothing looks broken, and
the agent teaches a `conditionals` remediation out of the recursion chapter. Before this
test, six of eight skills were in that state and no failure was visible anywhere.

This is the RAG equivalent of the safety invariant: a silent wrong answer is worse than
a loud missing one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.mastery.misconceptions import PATTERNS
from app.mastery.skill_graph import SkillGraph
from app.rag.documents import load_corpus
from app.rag.retriever import Retriever

SKILLS_CONFIG = Path("app/config/skills.yaml")
CORPUS = Path("data/knowledge")


@pytest.fixture(scope="module")
def skills() -> list[str]:
    return sorted(SkillGraph.from_yaml(SKILLS_CONFIG).nodes)


@pytest.fixture(scope="module")
def corpus_skills() -> set[str]:
    return {doc.meta.skill for doc in load_corpus(CORPUS)}


# ------------------------------------------------------------- corpus shape
def test_every_skill_has_a_document(skills, corpus_skills) -> None:
    missing = sorted(set(skills) - corpus_skills)
    assert not missing, (
        f"{len(missing)} skill(s) have no curriculum material: {missing}. "
        "Retrieval will silently serve another skill's chapter."
    )


def test_no_document_claims_a_skill_outside_the_graph(skills, corpus_skills) -> None:
    """A document tagged with an unknown skill can never be retrieved."""
    orphans = sorted(corpus_skills - set(skills))
    assert not orphans, f"documents tagged with unknown skills: {orphans}"


def test_documents_declare_prerequisites_consistent_with_the_graph() -> None:
    """Frontmatter must not contradict skills.yaml -- one of them would be a lie."""
    graph = SkillGraph.from_yaml(SKILLS_CONFIG)
    for doc in load_corpus(CORPUS):
        declared = set(doc.meta.prerequisites)
        actual = set(graph.prerequisites(doc.meta.skill))
        assert declared <= actual, (
            f"{doc.meta.source_file} declares prerequisites {sorted(declared - actual)} "
            f"that the skill graph does not have for {doc.meta.skill!r}"
        )


def test_every_document_is_substantial_enough_to_chunk() -> None:
    """A one-paragraph stub satisfies coverage on paper and teaches nobody."""
    for doc in load_corpus(CORPUS):
        headings = [ln for ln in doc.body.splitlines() if ln.startswith("## ")]
        assert len(headings) >= 4, (
            f"{doc.meta.source_file} has only {len(headings)} sections; "
            "heading-aware chunking needs more to produce useful chunks"
        )
        assert len(doc.body) > 2500, f"{doc.meta.source_file} is too short to teach from"


def test_every_document_addresses_misconceptions() -> None:
    for doc in load_corpus(CORPUS):
        assert "misconception" in doc.body.lower(), (
            f"{doc.meta.source_file} has no misconceptions section; the diagnoser "
            "retrieves this material precisely when a student holds one"
        )


# ------------------------------------------- alignment with the diagnoser
def test_material_exists_for_every_skill_a_misconception_can_implicate(corpus_skills) -> None:
    """The diagnoser may redirect to any implicated skill; each needs material.

    Otherwise the system correctly identifies the cause and then teaches it out of the
    wrong chapter, which is arguably worse than not diagnosing at all.
    """
    implicated = {p.prerequisite_hint for p in PATTERNS if p.prerequisite_hint}
    missing = sorted(implicated - corpus_skills)
    assert not missing, f"misconceptions implicate skills with no material: {missing}"


# ------------------------------------------------------- live retrieval
@pytest.fixture(scope="module")
def retriever() -> Retriever:
    return Retriever()


def test_skill_filtered_retrieval_never_falls_back(skills, retriever) -> None:
    """The behaviour that was silently wrong before the corpus was expanded."""
    fell_back = []
    for skill in skills:
        evidence = retriever.retrieve(f"{skill} explanation and worked example", skill=skill)
        if evidence.used_fallback or not evidence.chunks:
            fell_back.append(skill)
    assert not fell_back, (
        f"skill-filtered retrieval fell back for {fell_back} -- these would be taught "
        "from another skill's material"
    )


def test_retrieved_material_actually_belongs_to_the_requested_skill(skills, retriever) -> None:
    for skill in skills:
        evidence = retriever.retrieve(f"{skill} worked example", skill=skill)
        wrong = {c.skill for c in evidence.chunks} - {skill}
        assert not wrong, f"retrieval for {skill!r} leaked material from {sorted(wrong)}"


def test_citations_resolve_for_every_skill(skills, retriever) -> None:
    """A generated problem claims grounding; the citation must point somewhere real."""
    for skill in skills:
        evidence = retriever.retrieve(f"{skill} explanation", skill=skill)
        citations = evidence.citations()
        assert citations, f"no citations available for {skill!r}"
        for citation in citations:
            assert "#" in citation, f"malformed citation {citation!r}"
            source = citation.split("#", 1)[0]
            assert (CORPUS / source).exists(), f"citation points at a missing file: {source}"
