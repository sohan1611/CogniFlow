"""Heading-aware chunking for RAG.

Invariant: chunk IDs are stable across runs and chunks do not cross markdown
heading sections before paragraph-level splitting is applied.
"""

from __future__ import annotations

import re
from pydantic import BaseModel

from app.rag.documents import ParsedDocument

CHUNK_TARGET_CHARS = 2400
CHUNK_OVERLAP_CHARS = 320
MIN_CHUNK_CHARS = 200

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


class Chunk(BaseModel):
    chunk_id: str
    text: str
    section: str
    index: int


def _heading_text(line: str) -> str:
    match = _HEADING_RE.match(line.strip())
    if match is None:
        return ""
    return match.group(1).strip().strip("#").strip()


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_section = ""
    current_lines: list[str] = []

    for line in body.splitlines():
        heading = _heading_text(line)
        if heading:
            if current_lines:
                sections.append((current_section, current_lines))
            current_section = heading
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_section, current_lines))

    return [(section, "\n".join(lines).strip()) for section, lines in sections if "\n".join(lines).strip()]


def _paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]


def _split_long_text(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_TARGET_CHARS, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return [chunk for chunk in chunks if chunk]


def _overlap_paragraphs(paragraphs: list[str]) -> list[str]:
    overlap: list[str] = []
    total = 0
    for paragraph in reversed(paragraphs):
        paragraph_len = len(paragraph) + (2 if overlap else 0)
        if overlap and total + paragraph_len > CHUNK_OVERLAP_CHARS:
            break
        overlap.insert(0, paragraph)
        total += paragraph_len
        if total >= CHUNK_OVERLAP_CHARS:
            break
    return overlap


def _split_oversized_section(text: str) -> list[str]:
    if len(text) <= CHUNK_TARGET_CHARS:
        return [text]

    chunks: list[str] = []
    current: list[str] = []

    for paragraph in _paragraphs(text):
        if len(paragraph) > CHUNK_TARGET_CHARS:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
            chunks.extend(_split_long_text(paragraph))
            continue

        candidate = "\n\n".join([*current, paragraph]).strip()
        if current and len(candidate) > CHUNK_TARGET_CHARS:
            flushed = current
            chunks.append("\n\n".join(flushed).strip())
            current = _overlap_paragraphs(flushed)
            candidate = "\n\n".join([*current, paragraph]).strip()
            if len(candidate) > CHUNK_TARGET_CHARS:
                current = [paragraph]
            else:
                current.append(paragraph)
        else:
            current.append(paragraph)

    if current:
        chunks.append("\n\n".join(current).strip())

    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        trailing = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n\n{trailing}".strip()

    return [chunk for chunk in chunks if chunk]


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    raw_chunks: list[tuple[str, str]] = []
    for section, section_text in _split_sections(doc.body):
        for text in _split_oversized_section(section_text):
            raw_chunks.append((section, text))

    chunks: list[Chunk] = []
    for index, (section, text) in enumerate(raw_chunks):
        chunks.append(
            Chunk(
                chunk_id=f"{doc.meta.source_file}::{index}",
                text=text,
                section=section,
                index=index,
            )
        )
    return chunks

