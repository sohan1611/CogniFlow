"""The mastery reset is explicit, scoped, and restores a coherent fresh state."""

from __future__ import annotations

from app.mastery.bkt import BKTParams
from app.models.enums import StudentOutcome
from app.models.schemas import SkillNode, SkillUpdate
from app.services.student_store import StudentStore
from scripts.reset_mastery import main


def _measured(skill: str) -> SkillNode:
    return SkillNode(
        skill=skill,
        mastery=0.72,
        confidence=0.61,
        attempts=3,
        evidence_weight=2.5,
        agree_correct=2.0,
        agree_wrong=0.5,
    )


def _add_history(store: StudentStore, student_id: str) -> None:
    store.seed(student_id, {"variables": _measured("variables")})
    store.mark_diagnosed(student_id)
    store.log_attempt(
        student_id,
        "session-1",
        SkillUpdate(
            skill="variables",
            mastery_before=0.3,
            mastery_after=0.72,
            confidence_before=0.0,
            confidence_after=0.61,
            outcome=StudentOutcome.CORRECT,
            attempts_after=3,
        ),
    )


def test_reset_refuses_without_yes_and_changes_nothing(capsys) -> None:
    store = StudentStore(":memory:")
    _add_history(store, "ada")

    assert main(["--student", "ada"], store=store) == 2
    assert store.load_skills("ada")["variables"].measured is True
    assert len(store.attempts_for("ada")) == 1
    assert store.needs_diagnostic("ada") is False
    assert "Refusing" in capsys.readouterr().out


def test_reset_one_student_clears_all_three_parts_of_the_state() -> None:
    store = StudentStore(":memory:")
    _add_history(store, "ada")
    _add_history(store, "grace")

    assert main(["--student", "ada", "--yes"], store=store) == 0

    reset = store.load_skills("ada")["variables"]
    assert reset.mastery == BKTParams().p_init
    assert reset.confidence == 0.0
    assert reset.attempts == 0
    assert (
        reset.evidence_weight,
        reset.agree_correct,
        reset.agree_wrong,
    ) == (0.0, 0.0, 0.0)
    assert store.attempts_for("ada") == []
    assert store.needs_diagnostic("ada") is True

    assert store.load_skills("grace")["variables"].measured is True
    assert len(store.attempts_for("grace")) == 1


def test_reset_all_selects_every_student() -> None:
    store = StudentStore(":memory:")
    _add_history(store, "ada")
    _add_history(store, "grace")

    assert main(["--all", "--yes"], store=store) == 0
    assert store.student_ids() == ["ada", "grace"]
    assert all(
        not store.load_skills(student_id)["variables"].measured
        for student_id in store.student_ids()
    )
    assert all(store.needs_diagnostic(student_id) for student_id in store.student_ids())
