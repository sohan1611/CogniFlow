"""Durable student model — the long-term half of the persistence split.

Invariant: mastery is written through IMMEDIATELY on every update. A crash, a killed
process, or a closed laptop mid-session must never lose what a student demonstrated.

Two stores, two lifetimes, deliberately separate:
  * LangGraph checkpoints (SqliteSaver)  -> session state, keyed by thread_id, ephemeral
  * THIS store                           -> mastery per student, keyed by student_id,
                                            survives every session

A session can be abandoned harmlessly. Learning cannot.

Two backends behind the one class, chosen by configuration and nothing else:
  * PostgreSQL, when DATABASE_URL is set -> the hosted engine. Render's free tier has an
    ephemeral disk: a redeploy, a restart, or the spin-down after ~15 idle minutes wipes
    it, and a SQLite file there took every student's progress with it.
  * SQLite otherwise                     -> local development, the demo, the tests.

An explicit db_path always means SQLite, so a test or the demo that names a file can
never be redirected into a real database by an environment variable.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config.settings import get_settings
from app.models.enums import StudentOutcome
from app.models.schemas import SkillNode, SkillUpdate

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = Path("data/cogniflow.db")

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
    resolved_misconceptions TEXT NOT NULL DEFAULT '[]',
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

# The same three tables for PostgreSQL. Two differences, both load-bearing:
#   * DOUBLE PRECISION, not REAL. Postgres REAL is a 4-byte float, so a mastery of 0.35
#     would read back as 0.3499999940395355 -- a student's score silently changed by the
#     act of storing it. SQLite's REAL is already 8 bytes.
#   * An identity column instead of AUTOINCREMENT, which Postgres does not have.
# Timestamps stay TEXT in UTC ISO-8601, so both backends hand the API identical values.
POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS students (
        student_id   TEXT PRIMARY KEY,
        domain       TEXT NOT NULL DEFAULT 'python_fundamentals',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS skill_mastery (
        student_id     TEXT NOT NULL,
        skill          TEXT NOT NULL,
        mastery        DOUBLE PRECISION NOT NULL,
        confidence     DOUBLE PRECISION NOT NULL,
        attempts       INTEGER NOT NULL DEFAULT 0,
        prerequisites  TEXT NOT NULL DEFAULT '[]',
        misconceptions TEXT NOT NULL DEFAULT '[]',
        resolved_misconceptions TEXT NOT NULL DEFAULT '[]',
        updated_at     TEXT NOT NULL,
        PRIMARY KEY (student_id, skill)
    )""",
    """CREATE TABLE IF NOT EXISTS attempt_log (
        id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        student_id      TEXT NOT NULL,
        session_id      TEXT NOT NULL,
        skill           TEXT NOT NULL,
        outcome         TEXT NOT NULL,
        mastery_before  DOUBLE PRECISION NOT NULL,
        mastery_after   DOUBLE PRECISION NOT NULL,
        created_at      TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_attempt_student ON attempt_log(student_id, skill)",
)

POOL_APPLICATION_NAME = "cogniflow-engine"
_POOLS: dict[str, Any] = {}
_POOLS_LOCK = threading.Lock()


def student_id_from_name(name: str) -> str:
    """Convert a display name into a stable storage key.

    Raw names are not used as primary keys because case, leading/trailing spaces, and
    punctuation variations would create accidental duplicate students for the same
    person.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def configured_backend() -> str:
    """Which backend a default StudentStore() uses on this host: "postgres" or "sqlite"."""
    return "postgres" if get_settings().database_url else "sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _postgres_pool(url: str) -> Any:
    """One connection pool per database URL, shared by every StudentStore in the process.

    The API builds a StudentStore per request. Opening a fresh TLS connection to a hosted
    Postgres for each of those would put a handshake in front of every mastery write. The
    pool also re-checks a connection before lending it out: Neon suspends an idle compute
    and drops its connections, and a dead one must be replaced, not handed to a write.
    """
    with _POOLS_LOCK:
        pool = _POOLS.get(url)
        if pool is not None:
            return pool
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            url,
            min_size=1,
            max_size=4,
            # Named, so the engine's connections are identifiable in pg_stat_activity.
            kwargs={"row_factory": dict_row, "application_name": POOL_APPLICATION_NAME},
            check=ConnectionPool.check_connection,
            name="cogniflow-students",
            open=True,
        )
        try:
            with pool.connection() as conn:
                for statement in POSTGRES_SCHEMA:
                    conn.execute(statement)
        except Exception:
            pool.close()
            raise
        _POOLS[url] = pool
        return pool


class StudentStore:
    """Durable student model on PostgreSQL (hosted) or SQLite (local)."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        database_url: str | None = None,
    ) -> None:
        if db_path is not None and database_url is not None:
            raise ValueError("pass a db_path or a database_url, not both")
        self._memory_conn: sqlite3.Connection | None = None
        self._pool: Any = None
        self.db_path: Path | None = None

        url = database_url
        if db_path is None and url is None:
            url = get_settings().database_url
        if url:
            self.backend = "postgres"
            self._pool = _postgres_pool(url)
            return

        self.backend = "sqlite"
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_SQLITE_PATH
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # An in-memory DB dies with its connection, so hold one open for tests.
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns that arrived after a student's database was first written.

        `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so a
        returning student whose row predates a new column would otherwise crash the load
        that was supposed to welcome them back. Additive and idempotent: it only ever
        adds a missing column with a default, so it cannot lose data and can run on
        every open. SQLite only -- every Postgres database was created with the column.
        """
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(skill_mastery)")}
        if "resolved_misconceptions" not in columns:
            conn.execute(
                "ALTER TABLE skill_mastery"
                " ADD COLUMN resolved_misconceptions TEXT NOT NULL DEFAULT '[]'"
            )

    def _sql(self, query: str) -> str:
        """SQLite binds `?`, psycopg binds `%s`. Every query here is written once, for both."""
        return query.replace("?", "%s") if self.backend == "postgres" else query

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        """A connection that commits on success and rolls back on an exception."""
        if self._pool is not None:
            with self._pool.connection() as conn:
                yield conn
            return
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
        """Create the student if absent. Returns True when newly created.

        One conditional insert rather than a read then a write: two first requests for
        the same new student cannot both see "absent" and then collide on the key.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                self._sql(
                    "INSERT INTO students (student_id, domain, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (student_id) DO NOTHING"
                ),
                (student_id, domain, _now(), _now()),
            )
            return cursor.rowcount == 1

    def exists(self, student_id: str) -> bool:
        with self._connect() as conn:
            return (
                conn.execute(
                    self._sql("SELECT 1 FROM students WHERE student_id = ?"),
                    (student_id,),
                ).fetchone()
                is not None
            )

    # -- mastery -----------------------------------------------------------
    def load_skills(self, student_id: str) -> dict[str, SkillNode]:
        """Every skill record we hold for this student."""
        with self._connect() as conn:
            rows = conn.execute(
                self._sql("SELECT * FROM skill_mastery WHERE student_id = ? ORDER BY skill"),
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
                resolved_misconceptions=json.loads(row["resolved_misconceptions"]),
            )
            for row in rows
        }

    def _write_skill(self, conn: Any, student_id: str, node: SkillNode) -> None:
        conn.execute(
            self._sql(
                "INSERT INTO skill_mastery"
                " (student_id, skill, mastery, confidence, attempts, prerequisites,"
                "  misconceptions, resolved_misconceptions, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (student_id, skill) DO UPDATE SET"
                "  mastery=excluded.mastery, confidence=excluded.confidence,"
                "  attempts=excluded.attempts, prerequisites=excluded.prerequisites,"
                "  misconceptions=excluded.misconceptions,"
                "  resolved_misconceptions=excluded.resolved_misconceptions,"
                "  updated_at=excluded.updated_at"
            ),
            (
                student_id,
                node.skill,
                node.mastery,
                node.confidence,
                node.attempts,
                json.dumps(node.prerequisites),
                json.dumps(node.misconceptions),
                json.dumps(node.resolved_misconceptions),
                _now(),
            ),
        )
        conn.execute(
            self._sql("UPDATE students SET updated_at = ? WHERE student_id = ?"),
            (_now(), student_id),
        )

    def save_skill(self, student_id: str, node: SkillNode) -> None:
        """Write through a single skill. Called on EVERY mastery update."""
        with self._connect() as conn:
            self._write_skill(conn, student_id, node)

    def save_skills(self, student_id: str, nodes: dict[str, SkillNode]) -> None:
        """Write several skills in one transaction: all of them land, or none do."""
        with self._connect() as conn:
            for node in nodes.values():
                self._write_skill(conn, student_id, node)

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
                self._sql(
                    "INSERT INTO attempt_log"
                    " (student_id, session_id, skill, outcome, mastery_before,"
                    "  mastery_after, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                ),
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
            return [dict(r) for r in conn.execute(self._sql(query), params).fetchall()]

    def distinct_skills(self, student_id: str) -> list[str]:
        """Skills this student has actually attempted, alphabetically."""
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    "SELECT DISTINCT skill FROM attempt_log"
                    " WHERE student_id = ? ORDER BY skill"
                ),
                (student_id,),
            ).fetchall()
        return [row["skill"] for row in rows]

    def outcome_counts(self, student_id: str, skill: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.attempts_for(student_id, skill):
            counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
        return counts

    def close(self) -> None:
        """Release a held in-memory database. A Postgres pool is process-wide and stays."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
