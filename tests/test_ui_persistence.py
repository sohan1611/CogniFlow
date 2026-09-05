"""Persistence and identity helpers for the Streamlit UI."""

from __future__ import annotations

from pathlib import Path

from app.models.enums import StudentOutcome
from app.models.schemas import SkillUpdate
from app.services.demo_runner import seed_student
from app.services.student_store import StudentStore, student_id_from_name


def test_student_id_from_name_normalizes_display_names() -> None:
    assert student_id_from_name("Aarav") == "aarav"
    assert student_id_from_name(" Aarav  Kumar ") == "aarav-kumar"
    assert student_id_from_name("A@#$b") == "a-b"
    assert not student_id_from_name("")


def test_student_store_round_trips_seeded_masteries(tmp_path: Path) -> None:
    db_path = tmp_path / "students.db"
    store = StudentStore(db_path)
    nodes = seed_student(store, "aarav")
    nodes["functions"] = nodes["functions"].model_copy(
        update={"mastery": 0.73, "confidence": 0.66, "attempts": 4}
    )
    store.save_skills("aarav", nodes)
    expected = {
        skill: (node.mastery, node.confidence, node.attempts)
        for skill, node in nodes.items()
    }
    store.close()

    reloaded = StudentStore(db_path)
    actual = {
        skill: (node.mastery, node.confidence, node.attempts)
        for skill, node in reloaded.load_skills("aarav").items()
    }
    reloaded.close()

    assert actual == expected


def test_ensure_student_reports_only_first_creation(tmp_path: Path) -> None:
    store = StudentStore(tmp_path / "students.db")

    assert store.ensure_student("aarav") is True
    assert store.ensure_student("aarav") is False

    store.close()


def test_distinct_skills_returns_attempted_skills_once_sorted(tmp_path: Path) -> None:
    store = StudentStore(tmp_path / "students.db")
    store.ensure_student("aarav")

    for skill in ("loops", "functions", "loops"):
        store.log_attempt(
            "aarav",
            "session-1",
            SkillUpdate(
                skill=skill,
                mastery_before=0.40,
                mastery_after=0.50,
                confidence_before=0.40,
                confidence_after=0.50,
                outcome=StudentOutcome.CORRECT,
                attempts_after=1,
            ),
        )

    assert store.distinct_skills("aarav") == ["functions", "loops"]

    store.close()
