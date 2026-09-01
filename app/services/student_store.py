"""Durable student model — the long-term half of the persistence split.

Invariant: mastery is written through IMMEDIATELY on every update. A crash, a killed
process, or a closed laptop mid-session must never lose what a student demonstrated.

Two stores, two lifetimes, deliberately separate:
  * LangGraph checkpoints (SqliteSaver)  -> session state, keyed by thread_id, ephemeral
  * THIS store                           -> mastery per student, keyed by student_id,
                                            survives every session

A session can be abandoned harmlessly. Learning cannot.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.models.enums import StudentOutcome
from app.models.schemas import SkillNode, SkillUpdate

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id   TEXT PRIMARY KEY,
    domain       TEXT NOT NULL DEFAULT 'python_fundamentals',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_mastery (
    student_id     TEXT NOT NULL,
    skill          TEXT NOT NULL,
    mastery        REAL NOT NULL,
    confidence     REAL NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    prerequisites  TEXT NOT NULL DEFAULT '[]',
    misconceptions TEXT NOT NULL DEFAULT '[]',
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (student_id, skill)
);

CREATE TABLE IF NOT EXISTS attempt_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    skill           TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    mastery_before  REAL NOT NULL,
    mastery_after   REAL NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempt_student ON attempt_log(student_id, skill);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StudentStore:
    """SQLite-backed durable student model."""

    def __init__(self, db_path: Path | str = "data/cogniflow.db") -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn: sqlite3.Connection | None = None
        if str(self.db_path) == ":memory:":
            # An in-memory DB dies with its connection, so hold one open for tests.
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._memory_conn is not None:
            self._memory_conn.row_factory = sqlite3.Row
            yield self._memory_conn
            self._memory_conn.commit()
            return
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- students ----------------------------------------------------------
    def ensure_student(self, student_id: str, domain: str = "python_fundamentals") -> bool:
        """Create the student if absent. Returns True when newly created."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
            ).fetchone()
            if row:
                return False
            conn.execute(
                "INSERT INTO students (student_id, domain, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (student_id, domain, _now(), _now()),
            )
        return True

    def exists(self, student_id: str) -> bool:
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()
                is not None
            )

    # -- mastery -----------------------------------------------------------
    def load_skills(self, student_id: str) -> dict[str, SkillNode]:
        """Every skill record we hold for this student."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_mastery WHERE student_id = ? ORDER BY skill",
                (student_id,),
            ).fetchall()
        return {
            row["skill"]: SkillNode(
                skill=row["skill"],
                mastery=row["mastery"],
                confidence=row["confidence"],
                attempts=row["attempts"],
                prerequisites=json.loads(row["prerequisites"]),
                misconceptions=json.loads(row["misconceptions"]),
            )
            for row in rows
        }

    def save_skill(self, student_id: str, node: SkillNode) -> None:
        """Write through a single skill. Called on EVERY mastery update."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_mastery"
                " (student_id, skill, mastery, confidence, attempts, prerequisites,"
                "  misconceptions, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(student_id, skill) DO UPDATE SET"
                "  mastery=excluded.mastery, confidence=excluded.confidence,"
                "  attempts=excluded.attempts, prerequisites=excluded.prerequisites,"
                "  misconceptions=excluded.misconceptions, updated_at=excluded.updated_at",
                (
                    student_id,
                    node.skill,
                    node.mastery,
                    node.confidence,
                    node.attempts,
                    json.dumps(node.prerequisites),
                    json.dumps(node.misconceptions),
                    _now(),
                ),
            )
            conn.execute(
                "UPDATE students SET updated_at = ? WHERE student_id = ?",
                (_now(), student_id),
            )

    def save_skills(self, student_id: str, nodes: dict[str, SkillNode]) -> None:
        for node in nodes.values():
            self.save_skill(student_id, node)

    def seed(self, student_id: str, nodes: dict[str, SkillNode]) -> None:
        """Initialise a student with a starting skill graph (used by the demo)."""
        self.ensure_student(student_id)
        self.save_skills(student_id, nodes)

    # -- audit trail -------------------------------------------------------
    def log_attempt(
        self, student_id: str, session_id: str, update: SkillUpdate
    ) -> None:
        """Record one mastery movement. Only ever called with student evidence."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attempt_log"
                " (student_id, session_id, skill, outcome, mastery_before,"
                "  mastery_after, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    student_id,
                    session_id,
                    update.skill,
                    str(update.outcome),
                    update.mastery_before,
                    update.mastery_after,
                    _now(),
                ),
            )

    def attempts_for(self, student_id: str, skill: str | None = None) -> list[dict]:
        query = "SELECT * FROM attempt_log WHERE student_id = ?"
        params: list[object] = [student_id]
        if skill:
            query += " AND skill = ?"
            params.append(skill)
        query += " ORDER BY id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def outcome_counts(self, student_id: str, skill: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.attempts_for(student_id, skill):
            counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
        return counts

    def close(self) -> None:
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
