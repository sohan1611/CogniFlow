"""Tests for BKT mastery arithmetic.

Invariant: infrastructure faults are structurally rejected from mastery updates.
"""

import random

import pytest

from app.mastery.bkt import BKTParams, confidence_from_attempts, posterior, update
from app.models.enums import StudentOutcome, SystemFault
from app.models.errors import InvalidEvidenceError


def test_correct_never_decreases_mastery() -> None:
    prm = BKTParams()
    for start in [0.0, 0.1, 0.25, 0.5, 0.75, 0.95, 1.0]:
        assert update(start, StudentOutcome.CORRECT, prm) >= start


def test_posterior_strictly_decreases_on_incorrect() -> None:
    prm = BKTParams()
    for start in [0.1, 0.25, 0.5, 0.75, 0.95]:
        assert posterior(start, correct=False, prm=prm) < start


def test_correct_update_exceeds_wrong_update_from_same_start() -> None:
    prm = BKTParams()
    start = 0.45
    assert update(start, StudentOutcome.CORRECT, prm) > update(
        start,
        StudentOutcome.WRONG_ANSWER,
        prm,
    )


def test_mastery_stays_bounded_across_random_sequences() -> None:
    prm = BKTParams()
    rng = random.Random(42)
    outcomes = list(StudentOutcome)
    for _ in range(100):
        mastery = rng.random()
        for _ in range(100):
            mastery = update(mastery, rng.choice(outcomes), prm)
            assert 0.0 <= mastery <= 1.0


@pytest.mark.parametrize("fault", list(SystemFault))
def test_system_faults_raise_invalid_evidence(fault: SystemFault) -> None:
    with pytest.raises(InvalidEvidenceError):
        update(0.5, fault, BKTParams())  # type: ignore[arg-type]


def test_confidence_from_attempts_is_increasing_and_bounded() -> None:
    values = [confidence_from_attempts(attempts) for attempts in range(20)]
    assert values[0] == 0.0
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1))
    assert all(0.0 <= value < 1.0 for value in values)


def test_bkt_params_reject_degenerate_slip_guess_sum() -> None:
    with pytest.raises(ValueError):
        BKTParams(p_slip=0.5, p_guess=0.5)
