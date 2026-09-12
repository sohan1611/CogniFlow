"""The student store must behave identically on SQLite and on PostgreSQL.

The hosted engine keeps student progress in Postgres because its disk is wiped on every
restart. Everything else -- the demo, local development, the rest of this suite -- runs
on SQLite. So the backend a student's progress actually lives in is the one the rest of
the suite never touches, and "it works locally" says nothing about it.

These tests close that gap. Selection is tested without any database. The Postgres half
runs the same calls against both backends and demands identical results, and needs a
DISPOSABLE Postgres:

    COGNIFLOW_TEST_DATABASE_URL=postgresql://user@127.0.0.1:5432/cogniflow_test

Without it those tests skip rather than pass. Never point it at a real database: the
connection test terminates the engine's own pooled connections.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.enums import StudentOutcome
from app.models.schemas import SkillNode, SkillUpdate
from app.services import student_store
from app.services.student_store import StudentStore

PG_URL = os.environ.get("COGNIFLOW_TEST_DATABASE_URL", "")


def _settings(url: str | None):
    return lambda: SimpleNamespace(database_url=url)


# -- selection: no database needed -------------------------------------------

def test_an_explicit_path_is_sqlite_even_when_a_database_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo and every test name a file. None of them may land in a real database."""
    monkeypatch.setattr(student_store, "get_settings", _settings("postgresql://h.invalid/db"))
    monkeypatch.setattr(
        student_store, "_postgres_pool", lambda url: pytest.fail("connected to Postgres")
    )
    assert StudentStore(tmp_path / "s.db").backend == "sqlite"
    assert StudentStore(":memory:").backend == "sqlite"


def test_no_database_url_means_the_default_sqlite_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(student_store, "get_settings", _settings(None))
    assert StudentStore().backend == "sqlite"
    assert (tmp_path / "data" / "cogniflow.db").exists()
    assert student_store.configured_backend() == "sqlite"


def test_a_configured_database_url_selects_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """This is the path the API takes: StudentStore() with no arguments."""
    monkeypatch.setattr(student_store, "get_settings", _settings("postgresql://h.invalid/db"))
    seen: list[str] = []
    monkeypatch.setattr(student_store, "_postgres_pool", lambda url: seen.append(url) or object())
    store = StudentStore()
    assert store.backend == "postgres"
    assert seen == ["postgresql://h.invalid/db"]
    assert student_store.configured_backend() == "postgres"


def test_a_path_and_a_url_together_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        StudentStore(tmp_path / "s.db", database_url="postgresql://h.invalid/db")


def test_placeholders_are_translated_only_for_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(student_store, "_postgres_pool", lambda url: object())
    query = "SELECT 1 FROM t WHERE a = ? AND b = ?"
    assert StudentStore(tmp_path / "s.db")._sql(query) == query
    assert (
        StudentStore(database_url="postgresql://h.invalid/db")._sql(query)
        == "SELECT 1 FROM t WHERE a = %s AND b = %s"
    )


# -- behaviour: the same calls on both backends --------------------------------

def _attempt(skill: str, outcome: StudentOutcome, before: float, after: float) -> SkillUpdate:
    return SkillUpdate(
        skill=skill,
        mastery_before=before,
        mastery_after=after,
        confidence_before=0.2,
        confidence_after=0.3,
        outcome=outcome,
        attempts_after=2,
    )


def _exercise(store: StudentStore, sid: str) -> dict:
    """Every public method, in the order the API uses them. Returns what a caller sees."""
    created = store.ensure_student(sid)
    created_again = store.ensure_student(sid)
    needs_diagnostic_before = store.needs_diagnostic(sid)
    store.mark_diagnosed(sid)
    needs_diagnostic_after = store.needs_diagnostic(sid)
    store.seed(
        sid,
        {
            "variables": SkillNode(
                skill="variables", mastery=0.35, confidence=0.2, attempts=1,
                misconceptions=["off_by_one"],
            ),
            "functions": SkillNode(
                skill="functions", mastery=0.55, confidence=0.4, prerequisites=["variables"],
            ),
        },
    )
    store.save_skill(
        sid,
        SkillNode(
            skill="variables", mastery=0.6123456789, confidence=0.51, attempts=2,
            resolved_misconceptions=["off_by_one"],
        ),
    )
    store.log_attempt(sid, "session-1", _attempt("variables", StudentOutcome.WRONG_ANSWER, 0.35, 0.31))
    store.log_attempt(sid, "session-1", _attempt("variables", StudentOutcome.CORRECT, 0.31, 0.6123456789))
    store.log_attempt(sid, "session-1", _attempt("functions", StudentOutcome.CORRECT, 0.55, 0.66))
    rows = store.attempts_for(sid)
    return {
        "created": created,
        "created_again": created_again,
        "needs_diagnostic_before": needs_diagnostic_before,
        "needs_diagnostic_after": needs_diagnostic_after,
        "exists": store.exists(sid),
        "stranger_exists": store.exists(sid + "-nobody"),
        "skills": {name: node.model_dump() for name, node in store.load_skills(sid).items()},
        "columns": sorted(rows[0]),
        "attempts": [
            {k: v for k, v in row.items() if k not in ("id", "created_at", "student_id")}
            for row in rows
        ],
        "ids_ascend": [row["id"] for row in rows] == sorted(row["id"] for row in rows),
        "variables_attempts": len(store.attempts_for(sid, "variables")),
        "distinct": store.distinct_skills(sid),
        "counts": store.outcome_counts(sid, "variables"),
    }


def test_sqlite_round_trips_every_method(tmp_path: Path) -> None:
    seen = _exercise(StudentStore(tmp_path / "s.db"), "ada")
    assert seen["created"] is True and seen["created_again"] is False
    assert seen["needs_diagnostic_before"] is True
    assert seen["needs_diagnostic_after"] is False
    assert seen["exists"] is True and seen["stranger_exists"] is False
    assert seen["skills"]["variables"]["mastery"] == 0.6123456789
    assert seen["skills"]["variables"]["resolved_misconceptions"] == ["off_by_one"]
    assert seen["skills"]["functions"]["prerequisites"] == ["variables"]
    assert [a["outcome"] for a in seen["attempts"]] == ["WRONG_ANSWER", "CORRECT", "CORRECT"]
    assert seen["ids_ascend"] and seen["variables_attempts"] == 2
    assert seen["distinct"] == ["functions", "variables"]
    assert seen["counts"] == {"WRONG_ANSWER": 1, "CORRECT": 1}


@pytest.fixture
def pg_url() -> str:
    if not PG_URL:
        pytest.skip("set COGNIFLOW_TEST_DATABASE_URL to a disposable Postgres to run this")
    return PG_URL


@pytest.fixture
def sid(pg_url: str):
    """A student id no other run can collide with, removed afterwards."""
    student = f"test-{uuid.uuid4().hex[:12]}"
    yield student
    with StudentStore(database_url=pg_url)._connect() as conn:
        for table in ("attempt_log", "skill_mastery", "students"):
            conn.execute(f"DELETE FROM {table} WHERE student_id = %s", (student,))


def test_postgres_matches_sqlite_on_every_method(pg_url: str, sid: str, tmp_path: Path) -> None:
    assert _exercise(StudentStore(database_url=pg_url), sid) == _exercise(
        StudentStore(tmp_path / "s.db"), sid
    )


def test_postgres_stores_mastery_without_float_drift(pg_url: str, sid: str) -> None:
    """Postgres REAL is 4 bytes: 0.35 would read back as 0.3499999940395355."""
    store = StudentStore(database_url=pg_url)
    store.seed(sid, {"recursion": SkillNode(skill="recursion", mastery=0.35, confidence=0.3)})
    assert store.load_skills(sid)["recursion"].mastery == 0.35


def test_progress_survives_a_process_restart(
    pg_url: str, sid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this backend exists to fix, reproduced as closely as a test can.

    A fresh pool means fresh connections and a fresh schema check -- what a new process
    after a redeploy gets. What the first one wrote must still be there.
    """
    StudentStore(database_url=pg_url).seed(
        sid, {"loops": SkillNode(skill="loops", mastery=0.8, confidence=0.6, attempts=3)}
    )
    old_pools = dict(student_store._POOLS)
    monkeypatch.setattr(student_store, "_POOLS", {})
    try:
        reborn = StudentStore(database_url=pg_url)
        assert reborn.exists(sid)
        assert reborn.load_skills(sid)["loops"].attempts == 3
    finally:
        for pool in student_store._POOLS.values():
            pool.close()
        monkeypatch.setattr(student_store, "_POOLS", old_pools)


def test_a_dropped_connection_is_replaced_not_used(pg_url: str, sid: str) -> None:
    """Neon suspends an idle compute and its connections die with it.

    The next mastery write after a quiet spell must get a live connection, not an error.
    """
    import psycopg

    store = StudentStore(database_url=pg_url)
    store.ensure_student(sid)
    with psycopg.connect(pg_url, autocommit=True) as admin:
        killed = admin.execute(
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity"
            " WHERE application_name = %s AND datname = current_database()",
            (student_store.POOL_APPLICATION_NAME,),
        ).fetchone()[0]
    assert killed >= 1, "no pooled connection was found to terminate"
    assert store.exists(sid)
