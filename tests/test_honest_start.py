"""Regression tests for honest student initialization and attempt reporting."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import SESSIONS, SKILLS_CONFIG, app
from app.mastery.skill_graph import SkillGraph
from app.models.enums import StudentOutcome
from app.models.schemas import SkillUpdate
from app.services.demo_runner import seed_student
from app.services.student_store import StudentStore


@pytest.fixture
def client_and_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Path]:
    """An API client and the SQLite file behind its request-local stores."""
    import app.api.main as api

    db_path = tmp_path / "honest-start.db"
    monkeypatch.setattr(api, "StudentStore", lambda *a, **k: StudentStore(db_path))
    SESSIONS.clear()
    return TestClient(app), db_path


def _attempt(skill: str = "variables") -> SkillUpdate:
    return SkillUpdate(
        skill=skill,
        mastery_before=0.5,
        mastery_after=0.6,
        confidence_before=0.3,
        confidence_after=0.4,
        outcome=StudentOutcome.CORRECT,
        attempts_after=1,
    )


def test_new_student_starts_at_curriculum_priors(
    client_and_db: tuple[TestClient, Path],
) -> None:
    client, db_path = client_and_db

    started = client.post("/session", json={"name": "Nila"}).json()
    stored = StudentStore(db_path).load_skills(started["student_id"])
    expected = SkillGraph.from_yaml(SKILLS_CONFIG).nodes

    assert stored == expected
    assert all(node.attempts == 0 for node in stored.values())

    plan = client.get("/student/nila/plan").json()
    assert plan["counts"]["done"] == 0
    assert plan["counts"]["provisional"] == 0
    assert plan["total_attempts"] == 0


def test_reentering_before_finishing_still_needs_diagnostic(
    client_and_db: tuple[TestClient, Path],
) -> None:
    client, _db_path = client_and_db

    client.post("/session", json={"name": "Nila"})
    reentered = client.post("/session", json={"name": "Nila"}).json()

    assert reentered["returning"] is True
    assert reentered["needs_diagnostic"] is True


def test_finished_diagnostic_is_persisted_across_store_instances(
    client_and_db: tuple[TestClient, Path],
) -> None:
    client, db_path = client_and_db
    client.post("/session", json={"name": "Nila"})

    question = client.get("/session/nila/diagnostic").json()
    assert question["skill"] == "variables"
    answer = client.post(
        "/session/nila/diagnostic",
        json={"skill": "variables", "code": "print('wrong')"},
    )
    assert answer.status_code == 200
    assert client.get("/session/nila/diagnostic").json()["complete"] is True

    fresh_store = StudentStore(db_path)
    assert fresh_store.needs_diagnostic("nila") is False

    reentered = client.post("/session", json={"name": "Nila"}).json()
    assert reentered["returning"] is True
    assert reentered["needs_diagnostic"] is False


def test_real_attempts_exempt_pre_marker_student_from_diagnostic(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = StudentStore(db_path)
    store.ensure_student("history")
    store.log_attempt("history", "old-session", _attempt())

    with sqlite3.connect(db_path) as conn:
        diagnosed_at = conn.execute(
            "SELECT diagnosed_at FROM students WHERE student_id = ?", ("history",)
        ).fetchone()[0]

    assert diagnosed_at is None
    assert store.needs_diagnostic("history") is False


def test_old_demo_seed_without_real_attempts_needs_diagnostic(tmp_path: Path) -> None:
    store = StudentStore(tmp_path / "seeded.db")
    nodes = seed_student(store, "seeded")

    assert sum(node.attempts for node in nodes.values()) == 24
    assert store.attempts_for("seeded") == []
    assert store.needs_diagnostic("seeded") is True


def test_plan_total_attempts_counts_log_rows_not_skill_attempts(
    client_and_db: tuple[TestClient, Path],
) -> None:
    client, db_path = client_and_db
    client.post("/session", json={"name": "Nila"})
    store = StudentStore(db_path)

    inflated = {
        skill: node.model_copy(update={"attempts": 5})
        for skill, node in store.load_skills("nila").items()
    }
    store.save_skills("nila", inflated)
    store.log_attempt("nila", "session-1", _attempt())
    store.log_attempt("nila", "session-1", _attempt("functions"))

    plan = client.get("/student/nila/plan").json()

    assert sum(skill["attempts"] for skill in plan["skills"]) == 40
    assert plan["total_attempts"] == 2


def test_old_sqlite_students_table_gains_diagnosed_marker(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE students (
                student_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL DEFAULT 'python_fundamentals',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO students (student_id, created_at, updated_at)
            VALUES ('legacy', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            """
        )

    migrated = StudentStore(db_path)
    assert migrated.needs_diagnostic("legacy") is True
    migrated.mark_diagnosed("legacy")
    migrated.close()

    assert StudentStore(db_path).needs_diagnostic("legacy") is False
