"""Corpus ingestion for RAG.

Invariant: stable chunk IDs plus Chroma upsert make repeated ingestion
idempotent for the same corpus.
"""

from __future__ import annotations

from pathlib import Path

from app.rag.chunker import chunk_document
from app.rag.documents import load_corpus
from app.rag.store import VectorStore


def ingest_corpus(directory: Path | None = None, store: VectorStore | None = None) -> dict[str, int]:
    corpus_dir = directory if directory is not None else Path("data/knowledge")
    vector_store = store if store is not None else VectorStore()

    documents = load_corpus(corpus_dir)
    chunk_total = 0
    skills: set[str] = set()
    for document in documents:
        chunks = chunk_document(document)
        added = vector_store.add_chunks(document, chunks)
        chunk_total += added
        if added:
            skills.add(document.meta.skill)

    return {"documents": len(documents), "chunks": chunk_total, "skills": len(skills)}

