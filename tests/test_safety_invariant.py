"""Adversarial tests for THE safety invariant (plan requirement 14).

Infrastructure failures must be structurally incapable of changing a mastery score.

These tests are deliberately written by the reviewer rather than the implementer, and
they attack the invariant from angles a happy-path test suite would not: raw strings
that collide with enum values, cross-enum value collisions, non-enum junk, and a fuzz
walk that mixes real student evidence with injected faults.

If any test here fails, the failure is in the design, not in the test.
"""

from __future__ import annotations

import random

import pytest

from app.mastery.bkt import BKTParams, update, update_skill
from app.models.enums import (
    CORRECTNESS,
    StudentOutcome,
    SystemFault,
    is_student_evidence,
)
from app.models.errors import InvalidEvidenceError
from app.models.schemas import SkillNode

PRM = BKTParams()


def _node(mastery: float = 0.5) -> SkillNode:
    return SkillNode(skill="recursion", mastery=mastery, confidence=0.4, attempts=2)


# --------------------------------------------------------------------------
# 1. The two enums must not overlap in VALUE, not merely in identity.
#    StrEnum members compare equal to bare strings, so a value collision would
#    make the disjointness claim false in practice even with isinstance guards.
# --------------------------------------------------------------------------
def test_enum_values_are_disjoint() -> None:
    student = {m.value for m in StudentOutcome}
    fault = {m.value for m in SystemFault}
    assert student.isdisjoint(fault), f"value collision: {student & fault}"


def test_no_fault_is_student_evidence() -> None:
    for fault in SystemFault:
        assert is_student_evidence(fault) is False


def test_every_student_outcome_is_evidence_and_has_correctness() -> None:
    for outcome in StudentOutcome:
        assert is_student_evidence(outcome) is True
        assert outcome in CORRECTNESS, f"{outcome} missing from CORRECTNESS"
    assert CORRECTNESS[StudentOutcome.CORRECT] is True
    assert sum(CORRECTNESS.values()) == 1, "exactly one outcome may count as correct"


# --------------------------------------------------------------------------
# 2. Every SystemFault must be rejected by BOTH mastery entry points.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fault", list(SystemFault))
def test_update_rejects_every_system_fault(fault: SystemFault) -> None:
    with pytest.raises(InvalidEvidenceError):
        update(0.5, fault, PRM)  # type: ignore[arg-type]


@pytest.mark.parametrize("fault", list(SystemFault))
def test_update_skill_rejects_every_system_fault(fault: SystemFault) -> None:
    node = _node()
    with pytest.raises(InvalidEvidenceError):
        update_skill(node, fault, PRM)  # type: ignore[arg-type]
    # the node must be untouched -- no partial mutation before the raise
    assert node.mastery == 0.5
    assert node.attempts == 2


# --------------------------------------------------------------------------
# 3. Junk must not sneak through. A bare string equal to a StudentOutcome value
#    is the most likely real-world leak (JSON round-trip, LLM output, DB read).
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "junk",
    [
        "CORRECT",  # string that EQUALS a StudentOutcome value
        "WRONG_ANSWER",
        "SANDBOX_FAILURE",
        "",
        None,
        0,
        1,
        True,
        3.14,
        ["CORRECT"],
        {"outcome": "CORRECT"},
        object(),
    ],
)
def test_update_rejects_non_enum_input(junk: object) -> None:
    with pytest.raises(InvalidEvidenceError):
        update(0.5, junk, PRM)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 4. Fuzz: interleave genuine evidence with injected faults. Mastery may move
#    ONLY on the student-evidence steps, and must stay a valid probability.
# --------------------------------------------------------------------------
def test_faults_never_move_mastery_during_a_mixed_session() -> None:
    rng = random.Random(20260913)
    mastery = 0.35
    student_steps = 0

    for _ in range(500):
        if rng.random() < 0.5:
            fault = rng.choice(list(SystemFault))
            before = mastery
            with pytest.raises(InvalidEvidenceError):
                update(mastery, fault, PRM)  # type: ignore[arg-type]
            assert mastery == before, "a fault changed mastery"
        else:
            outcome = rng.choice(list(StudentOutcome))
            mastery = update(mastery, outcome, PRM)
            student_steps += 1

        assert 0.0 <= mastery <= 1.0, f"mastery escaped [0,1]: {mastery}"

    assert student_steps > 0, "fuzz never exercised the student path"


# --------------------------------------------------------------------------
# 5. The demo's headline claim: an injected sandbox failure mid-session leaves
#    the student's mastery bit-for-bit identical.
# --------------------------------------------------------------------------
def test_demo_scenario_sandbox_failure_leaves_mastery_bit_identical() -> None:
    node = _node(mastery=0.35)

    after_real_attempt, _ = update_skill(node, StudentOutcome.STUDENT_RUNTIME_ERROR, PRM)
    checkpoint = after_real_attempt.mastery

    for fault in SystemFault:
        with pytest.raises(InvalidEvidenceError):
            update_skill(after_real_attempt, fault, PRM)  # type: ignore[arg-type]

    assert after_real_attempt.mastery == checkpoint
    assert after_real_attempt.attempts == 3


# --------------------------------------------------------------------------
# 6. Direction check: a wrong answer must not be able to RAISE mastery above
#    what the identical correct answer would have produced.
# --------------------------------------------------------------------------
def test_incorrect_never_beats_correct() -> None:
    for start in (0.05, 0.2, 0.35, 0.5, 0.75, 0.95):
        good = update(start, StudentOutcome.CORRECT, PRM)
        for bad in (o for o in StudentOutcome if o is not StudentOutcome.CORRECT):
            assert update(start, bad, PRM) < good, f"{bad} beat CORRECT at {start}"
