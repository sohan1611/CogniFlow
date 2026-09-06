"""Chroma vector store wrapper for RAG.

Invariant: chromadb is imported only in this module and all persisted metadata
is string-only so Chroma accepts every chunk deterministically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from app.config.settings import Settings, get_settings
from app.models.schemas import RetrievedChunk
from app.rag.chunker import Chunk
from app.rag.documents import ParsedDocument


class VectorStore:
    """Thin wrapper over local persistent Chroma using its built-in ONNX embedder."""

    COLLECTION = "cogniflow_curriculum"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else get_settings().chroma_path
        self._client = chromadb.PersistentClient(path=str(self.path))
        self._embedding_function = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            self.COLLECTION,
            embedding_function=self._embedding_function,
        )

    def add_chunks(self, doc: ParsedDocument, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0

        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "skill": str(doc.meta.skill or ""),
                "topic": str(doc.meta.topic or ""),
                "unit": str(doc.meta.unit or ""),
                "subject": str(doc.meta.subject or ""),
                "difficulty": str(doc.meta.difficulty or ""),
                "source_file": str(doc.meta.source_file or ""),
                "section": str(chunk.section or ""),
            }
            for chunk in chunks
        ]
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    def query(self, text: str, skill: str | None = None, k: int = 4) -> list[RetrievedChunk]:
        if k <= 0 or self.count() == 0:
            return []

        query_args: dict[str, Any] = {
            "query_texts": [text],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        if skill is not None:
            query_args["where"] = {"skill": skill}

        result = self._collection.query(**query_args)
        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]

        if not ids or not ids[0]:
            return []

        chunks: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids[0], documents[0], metadatas[0], distances[0]):
            metadata = metadata or {}
            chunks.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    text=str(document or ""),
                    skill=str(metadata.get("skill") or ""),
                    topic=str(metadata.get("topic") or ""),
                    unit=str(metadata.get("unit") or ""),
                    subject=str(metadata.get("subject") or ""),
                    difficulty=str(metadata.get("difficulty") or ""),
                    source_file=str(metadata.get("source_file") or ""),
                    section=str(metadata.get("section") or ""),
                    score=float(distance or 0.0),
                )
            )
        return chunks

    def count(self) -> int:
        return int(self._collection.count())

    def chunk_ids(self) -> set[str]:
        """Every chunk id currently stored.

        Exists so a test can tell a stale index from a current one. The index is
        committed -- it has to be, or a free-tier host re-embeds the whole curriculum on
        every cold start -- and a committed derived artefact drifts silently unless
        something checks.
        """
        return set(self._collection.get(include=[])["ids"])

    def reset(self) -> None:
        self._client.delete_collection(self.COLLECTION)
        self._collection = self._client.get_or_create_collection(
            self.COLLECTION,
            embedding_function=self._embedding_function,
        )
