"""Tests for BKT mastery arithmetic.

Invariant: infrastructure faults are structurally rejected from mastery updates.
"""

import random

import pytest

from app.mastery.bkt import MASTERY_CEILING, BKTParams, posterior, update
from app.mastery.evidence import Observation, accumulate, confidence_from_evidence
from app.models.enums import StudentOutcome, SystemFault
from app.models.errors import InvalidEvidenceError
from app.models.schemas import DEFAULT_MASTERY_PRIOR, SkillNode


def test_schema_default_prior_matches_bkt_source_of_truth() -> None:
    """The schema duplicates p_init only to avoid the schemas <-> mastery import cycle."""
    assert DEFAULT_MASTERY_PRIOR == BKTParams().p_init
    assert SkillNode(skill="variables").mastery == BKTParams().p_init
    assert SkillNode(skill="variables").confidence == 0.0


def test_correct_never_decreases_mastery() -> None:
    """1.0 is excluded because mastery is now capped at MASTERY_CEILING.

    An estimate of exactly 1.0 has infinite odds, so no future evidence of any kind could
    ever revise it -- that is not a belief, it is a decoration. A stored 1.0 from an older
    row is pulled down to the ceiling on its next observation, which is the intended
    behaviour rather than a decrease in belief.
    """
    prm = BKTParams()
    for start in [0.0, 0.1, 0.25, 0.5, 0.75, 0.95]:
        assert update(start, StudentOutcome.CORRECT, prm) >= start
    assert update(1.0, StudentOutcome.CORRECT, prm) == MASTERY_CEILING


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


def test_confidence_grows_with_consistent_evidence_and_is_bounded() -> None:
    """Replaces the old attempt-counting test.

    confidence_from_attempts saw only a count, so five correct and five incorrect both
    returned 0.7135 and confidence could never fall. It is now a function of how much the
    evidence AGREES, so this asserts growth along a CONSISTENT run specifically.
    """
    prm = BKTParams()
    weight = agreed = against = 0.0
    values = [confidence_from_evidence(weight, agreed, against, prm.p_slip, prm.p_guess)]
    for _ in range(19):
        weight, agreed, against = accumulate(
            weight, agreed, against,
            Observation(outcome=StudentOutcome.CORRECT, distinct_expectations=2),
        )
        values.append(
            confidence_from_evidence(weight, agreed, against, prm.p_slip, prm.p_guess)
        )
    assert values[0] == 0.0
    assert all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    assert all(0.0 <= value <= 1.0 for value in values)


def test_bkt_params_reject_degenerate_slip_guess_sum() -> None:
    with pytest.raises(ValueError):
        BKTParams(p_slip=0.5, p_guess=0.5)


# -------------------------------------------------------- misconception resolution
def _node(**kw) -> SkillNode:
    base = dict(skill="recursion", mastery=0.9, confidence=0.9,
                misconceptions=["thinks a recursive call returns itself"])
    base.update(kw)
    return SkillNode(**base)


def test_misconceptions_resolve_only_with_mastery_AND_confidence() -> None:
    """One lucky answer must not clear a misunderstanding.

    The whole reason this system uses BKT is that a single correct answer is not proof.
    Clearing a misconception on mastery alone would model slip and guess everywhere
    except the one place a student is told they have fixed something.
    """
    from app.mastery.bkt import resolve_misconceptions

    # mastered and confident -> resolved
    node, resolved = resolve_misconceptions(_node(), 0.6, 0.5)
    assert resolved and node.misconceptions == []
    assert node.resolved_misconceptions == ["thinks a recursive call returns itself"]

    # mastered but not yet confident -> untouched
    node, resolved = resolve_misconceptions(_node(confidence=0.2), 0.6, 0.5)
    assert resolved == [] and len(node.misconceptions) == 1

    # confident but not mastered -> untouched
    node, resolved = resolve_misconceptions(_node(mastery=0.3), 0.6, 0.5)
    assert resolved == [] and len(node.misconceptions) == 1


def test_resolved_misconceptions_are_moved_not_deleted() -> None:
    """The record that remediation worked is the point, not a side effect."""
    from app.mastery.bkt import resolve_misconceptions

    node, _ = resolve_misconceptions(_node(), 0.6, 0.5)
    assert node.misconceptions == []
    assert len(node.resolved_misconceptions) == 1


def test_resolution_does_not_duplicate_an_already_resolved_entry() -> None:
    """A student can re-learn the same lesson without it being recorded twice."""
    from app.mastery.bkt import resolve_misconceptions

    already = _node(resolved_misconceptions=["thinks a recursive call returns itself"])
    node, resolved = resolve_misconceptions(already, 0.6, 0.5)
    assert node.resolved_misconceptions == ["thinks a recursive call returns itself"]
    assert resolved == ["thinks a recursive call returns itself"]


def test_update_skill_preserves_resolved_history() -> None:
    """Regression: update_skill rebuilds the node, so an omitted field is wiped.

    Without this, every subsequent attempt would silently erase the record of what the
    student had already overcome.
    """
    from app.mastery.bkt import update_skill

    node = SkillNode(skill="recursion", mastery=0.5, confidence=0.5,
                     resolved_misconceptions=["an old mistake"])
    updated, _ = update_skill(node, StudentOutcome.CORRECT, BKTParams())
    assert updated.resolved_misconceptions == ["an old mistake"]
