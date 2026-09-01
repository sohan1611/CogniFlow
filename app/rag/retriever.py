"""Agent-facing retrieval facade.

Invariant: retrieval failures degrade to SystemFault.RETRIEVAL_FAILURE and never
propagate to tutoring-session callers.
"""

from __future__ import annotations

import logging

from app.models.enums import (
    Difficulty, TeachingMode, AssessmentType, AdaptationAction,
    SessionStatus, StudentOutcome, SystemFault, CORRECTNESS, is_student_evidence,
)
from app.models.schemas import RetrievedEvidence
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_K = 4


class Retriever:
    def __init__(self, store: VectorStore | None = None) -> None:
        self.store = store if store is not None else VectorStore()

    def retrieve(self, query: str, skill: str | None = None, k: int = DEFAULT_K) -> RetrievedEvidence:
        """Return grounded evidence or a degraded result without raising."""

        try:
            if skill is not None:
                filtered_chunks = self.store.query(query, skill=skill, k=k)
                if filtered_chunks:
                    return RetrievedEvidence(query=query, skill_filter=skill, chunks=filtered_chunks)
                fallback_chunks = self.store.query(query, skill=None, k=k)
                return RetrievedEvidence(
                    query=query,
                    skill_filter=skill,
                    chunks=fallback_chunks,
                    used_fallback=True,
                )

            chunks = self.store.query(query, skill=None, k=k)
            return RetrievedEvidence(query=query, skill_filter=None, chunks=chunks)
        except Exception:
            logger.warning("Retrieval failed for skill %s", skill, exc_info=True)
            return RetrievedEvidence(
                query=query,
                skill_filter=skill,
                chunks=[],
                degraded=True,
                fault=SystemFault.RETRIEVAL_FAILURE,
            )
