"""Document parsing for RAG.

Invariant: every parsed document has a skill metadata value so retrieval can
pre-filter by skill before semantic ranking.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.models.errors import (
    CogniFlowError, InvalidEvidenceError, SkillGraphError, LimitExceededError,
)

logger = logging.getLogger(__name__)


class DocumentMeta(BaseModel):
    subject: str = ""
    unit: str = ""
    topic: str = ""
    skill: str
    difficulty: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    source: str = ""
    license: str = ""
    source_file: str


class ParsedDocument(BaseModel):
    meta: DocumentMeta
    body: str


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_str(item) for item in value]
    return [_as_str(value)]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter_text = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            loaded = yaml.safe_load(frontmatter_text) or {}
            if not isinstance(loaded, dict):
                raise CogniFlowError("Markdown frontmatter must be a mapping")
            return loaded, body

    raise CogniFlowError("Markdown frontmatter is missing a closing delimiter")


def _meta_from_mapping(metadata: dict[str, Any], source_file: str) -> DocumentMeta:
    skill = _as_str(metadata.get("skill")).strip()
    if not skill:
        raise CogniFlowError(f"Knowledge document {source_file} is missing skill metadata")

    return DocumentMeta(
        subject=_as_str(metadata.get("subject")),
        unit=_as_str(metadata.get("unit")),
        topic=_as_str(metadata.get("topic")),
        skill=skill,
        difficulty=_as_str(metadata.get("difficulty")),
        prerequisites=_as_str_list(metadata.get("prerequisites")),
        source=_as_str(metadata.get("source")),
        license=_as_str(metadata.get("license")),
        source_file=source_file,
    )


def parse_markdown(path: Path) -> ParsedDocument:
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)
    return ParsedDocument(meta=_meta_from_mapping(metadata, path.name), body=body)


def parse_pdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    skill = re.sub(r"^\d+_", "", path.stem).strip()
    if not skill:
        raise CogniFlowError(f"Knowledge PDF {path.name} cannot derive a skill")

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        pages.append(f"\n\n[page {page_number}]\n\n{page.extract_text() or ''}")

    meta = DocumentMeta(skill=skill, source_file=path.name)
    return ParsedDocument(meta=meta, body="".join(pages).strip())


def load_corpus(directory: Path) -> list[ParsedDocument]:
    if not directory.exists():
        logger.warning("Knowledge corpus directory does not exist: %s", directory)
        return []

    documents: list[ParsedDocument] = []
    paths = sorted([*directory.rglob("*.md"), *directory.rglob("*.pdf")])
    for path in paths:
        try:
            if path.suffix.lower() == ".md":
                documents.append(parse_markdown(path))
            elif path.suffix.lower() == ".pdf":
                documents.append(parse_pdf(path))
        except Exception as exc:
            logger.warning("Skipping unreadable knowledge file %s: %s", path, exc)
    return documents

