"""The arithmetic of evidence-weighted mastery, pinned to exact numbers.

Every figure asserted here is also published -- in the rescue plan, in the README and in
the demo script. That is the point of the file: if the implementation and the documented
behaviour ever disagree, this fails rather than the claim quietly becoming false.
"""

import math

import pytest

from app.mastery.bkt import (
    MASTERY_CEILING,
    BKTParams,
    analytic_floor,
    update,
    update_skill,
)
from app.mastery.evidence import (
    KAPPA,
    W_MIN,
    Observation,
    accumulate,
    confidence_from_evidence,
    evidence_weight,
    guess_for,
)
from app.models.enums import StudentOutcome, SystemFault
from app.models.errors import InvalidEvidenceError
from app.models.schemas import SkillNode

PRM = BKTParams()
OLD = BKTParams(p_init=0.25, p_transit=0.15, p_slip=0.10, p_guess=0.20)


def fail(score: float = 0.0, n: int = 1, outcome=StudentOutcome.WRONG_ANSWER) -> Observation:
    return Observation(outcome=outcome, score=score, distinct_expectations=n)


def ok(n: int = 1) -> Observation:
    return Observation(outcome=StudentOutcome.CORRECT, distinct_expectations=n)


# --------------------------------------------------------------------------- the floor


def test_analytic_floor_reproduces_the_measured_production_wall():
    """The old parameters must still yield 6/35 -- the value we actually observed."""

    assert analytic_floor(OLD, p_guess=0.20) == pytest.approx(6 / 35, abs=1e-12)
    assert analytic_floor(OLD, p_guess=0.20) == pytest.approx(0.17142857, abs=1e-8)


def test_analytic_floor_for_shipped_parameters():
    assert analytic_floor(PRM) == pytest.approx(0.096, abs=1e-12)
    assert analytic_floor(PRM, p_guess=0.05) == pytest.approx(0.095, abs=1e-12)
    assert analytic_floor(PRM, p_guess=0.20) == pytest.approx(0.098461538, abs=1e-8)


def test_floor_is_where_repeated_failure_actually_converges():
    """The closed form is only worth publishing if the iteration agrees with it."""

    p = 0.30
    for _ in range(200):
        p = update(p, fail(n=2), PRM)
    assert p == pytest.approx(analytic_floor(PRM, p_guess=0.10), abs=1e-9)


def test_failing_students_can_now_be_shown_below_ten_percent():
    """The whole point of the change: 0.17 was unreachable-from-below before."""

    p = 0.30
    for _ in range(4):
        p = update(p, fail(n=2), PRM)
    assert p < 0.10


def test_published_failure_trajectory():
    p = 0.30
    seen = []
    for _ in range(4):
        p = update(p, fail(n=2), PRM)
        seen.append(round(p, 4))
    assert seen == [0.1413, 0.1046, 0.0976, 0.0963]


# ------------------------------------------------------------------- correct answers


def test_published_success_trajectory_on_a_strong_suite():
    p = 0.30
    seen = []
    for _ in range(3):
        p = update(p, ok(n=2), PRM)
        seen.append(round(p, 4))
    assert seen == [0.8018, 0.9740, 0.99]


def test_published_success_trajectory_on_the_weak_diagnostic():
    """A single literal expectation is a weak instrument and must move mastery less."""

    p = 0.30
    seen = []
    for _ in range(4):
        p = update(p, ok(n=1), PRM)
        seen.append(round(p, 4))
    assert seen == [0.6739, 0.9060, 0.9781, 0.99]


def test_a_stronger_suite_moves_further_on_success():
    weak = update(0.30, ok(n=1), PRM)
    mid = update(0.30, ok(n=2), PRM)
    strong = update(0.30, ok(n=3), PRM)
    assert weak < mid < strong


# ------------------------------------------------------------------- evidence quality


def test_published_weighted_failure_ladder_is_strictly_decreasing():
    """Failing 1 of 4 must cost less than failing 4 of 4. This is the defect that made a
    typo and a wholly wrong program numerically identical."""

    weights = [0.15, 0.25, 0.50, 0.60, 0.75, 1.00]
    got = [round(update(0.30, fail(score=1 - w, n=4), PRM), 4) for w in weights]
    # score = 1 - w only because KAPPA[WRONG_ANSWER] is 1.00; see the outcome test below.
    assert got == [0.2543, 0.2284, 0.1797, 0.1661, 0.1511, 0.1383]
    assert got == sorted(got, reverse=True)


def test_error_kinds_are_no_longer_interchangeable():
    """A program that never parsed says less about loops than one that ran and was wrong."""

    syntax = update(0.30, fail(outcome=StudentOutcome.STUDENT_SYNTAX_ERROR, n=4), PRM)
    timeout = update(0.30, fail(outcome=StudentOutcome.STUDENT_TIMEOUT, n=4), PRM)
    runtime = update(0.30, fail(outcome=StudentOutcome.STUDENT_RUNTIME_ERROR, n=4), PRM)
    wrong = update(0.30, fail(outcome=StudentOutcome.WRONG_ANSWER, n=4), PRM)
    assert syntax > timeout > runtime > wrong


def test_a_failure_never_rewards_a_student():
    """Weighting the likelihood but not the transition would move 0.300 UP to 0.307,
    rewarding a student whose program never ran.

    Stated against the floor rather than against the current value, because the floor
    attracts from below too: a student already beneath it drifts up toward it, since at
    that point the model cannot tell them apart from it. What must never happen is a
    failure leaving mastery above where it started AND above the floor.
    """

    obs = fail(outcome=StudentOutcome.STUDENT_SYNTAX_ERROR)
    weight = evidence_weight(obs)
    floor = analytic_floor(PRM, p_guess=guess_for(1), weight=weight)
    for p in (0.02, 0.05, 0.30, 0.5, 0.9):
        after = update(p, obs, PRM)
        assert after <= max(p, floor) + 1e-12
    # and at any realistic mastery it strictly costs the student
    for p in (0.30, 0.5, 0.9):
        assert update(p, obs, PRM) < p


def test_the_weighted_floor_is_where_weak_failures_converge():
    obs = fail(outcome=StudentOutcome.STUDENT_SYNTAX_ERROR)
    p = 0.30
    for _ in range(300):
        p = update(p, obs, PRM)
    expected = analytic_floor(PRM, p_guess=guess_for(1), weight=evidence_weight(obs))
    assert p == pytest.approx(expected, abs=1e-9)

    # The weak floor sits BELOW the full-strength one, which looks backwards until you
    # read the transition: weak evidence scales down the learning opportunity as well as
    # the likelihood, so less mastery is re-injected per step. Three hundred submissions
    # that never parsed is ~45 full observations' worth of "still cannot run this", and
    # the model is entitled to settle lower than for a student whose code at least ran.
    # What matters per observation is the opposite, and is asserted by the ladder test:
    # one syntax error costs far less than one wrong answer.
    assert expected < analytic_floor(PRM, p_guess=guess_for(1))
    assert update(0.30, obs, PRM) > update(0.30, fail(n=1), PRM)


def test_partial_credit_never_flips_the_sign():
    """3-of-4 is negative evidence of reduced size, not positive evidence."""

    for score in (0.0, 0.25, 0.5, 0.75, 0.99):
        assert update(0.30, fail(score=score, n=4), PRM) < 0.30


def test_a_near_zero_weight_is_close_to_the_identity():
    obs = fail(score=1.0, n=4)  # weight collapses to W_MIN
    assert evidence_weight(obs) == pytest.approx(W_MIN)
    assert update(0.30, obs, PRM) == pytest.approx(0.30, abs=0.02)


def test_incorrect_never_beats_correct_at_any_weight():
    for score in (0.0, 0.3, 0.6, 0.9, 1.0):
        for n in (1, 2, 4):
            assert update(0.30, fail(score=score, n=n), PRM) < update(0.30, ok(n=n), PRM)


def test_guess_ladder():
    assert guess_for(0) == 0.20
    assert guess_for(1) == 0.20
    assert guess_for(2) == 0.10
    assert guess_for(3) == 0.05
    assert guess_for(9) == 0.05


def test_correct_answers_are_always_full_strength():
    assert evidence_weight(ok()) == 1.0
    assert evidence_weight(Observation(outcome=StudentOutcome.CORRECT, score=0.0)) == 1.0


def test_kappa_covers_every_incorrect_outcome():
    """A new StudentOutcome must not silently fall through to a KeyError in production."""

    incorrect = {o for o in StudentOutcome if o is not StudentOutcome.CORRECT}
    assert incorrect == set(KAPPA)


# ----------------------------------------------------------------------- the ceiling


def test_mastery_never_exceeds_the_ceiling():
    import random

    rng = random.Random(20260912)
    p = 0.30
    for _ in range(500):
        if rng.random() < 0.7:
            p = update(p, ok(n=rng.choice([1, 2, 4])), PRM)
        else:
            p = update(p, fail(score=rng.random(), n=rng.choice([1, 2, 4])), PRM)
        assert 0.0 < p <= MASTERY_CEILING


def test_the_ceiling_keeps_the_model_falsifiable():
    """At exactly 1.0 the odds are infinite and no evidence could ever move it again."""

    p = MASTERY_CEILING
    for _ in range(5):
        p = update(p, fail(n=2), PRM)
    assert p < 0.20


def test_a_stored_one_point_zero_does_not_explode():
    """Old rows contain 1.0; it must not divide by zero."""

    assert update(1.0, fail(n=2), PRM) < 1.0


# -------------------------------------------------------------------- RULE 3 (safety)


@pytest.mark.parametrize("fault", list(SystemFault))
def test_a_fault_cannot_even_be_packaged_as_evidence(fault):
    with pytest.raises(InvalidEvidenceError):
        Observation(outcome=fault)


@pytest.mark.parametrize("junk", [None, 0, 1, "CORRECT", "", {}, [], 3.5, True])
def test_junk_is_not_evidence(junk):
    with pytest.raises(InvalidEvidenceError):
        Observation(outcome=junk)


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), "1.0", None])
def test_score_must_be_a_real_fraction(score):
    with pytest.raises(InvalidEvidenceError):
        Observation(outcome=StudentOutcome.CORRECT, score=score)


def test_negative_distinct_expectations_is_refused():
    with pytest.raises(InvalidEvidenceError):
        Observation(outcome=StudentOutcome.CORRECT, distinct_expectations=-1)


@pytest.mark.parametrize("fault", list(SystemFault))
def test_update_still_refuses_faults(fault):
    with pytest.raises(InvalidEvidenceError):
        update(0.30, fault, PRM)


# ------------------------------------------------------------------------ confidence


def run_confidence(pattern: str) -> float:
    """pattern is a string of 'c' (correct) and 'w' (wrong), oldest first."""

    weight_total = correct_mass = wrong_mass = 0.0
    for mark in pattern:
        obs = ok(n=2) if mark == "c" else fail(n=2)
        weight_total, correct_mass, wrong_mass = accumulate(
            weight_total, correct_mass, wrong_mass, obs
        )
    return confidence_from_evidence(
        weight_total, correct_mass, wrong_mass, PRM.p_slip, PRM.p_guess
    )


def test_published_confidence_table():
    assert round(run_confidence(""), 3) == 0.000
    assert round(run_confidence("ccc"), 3) == 0.632
    assert round(run_confidence("ccccc"), 3) == 0.811
    assert round(run_confidence("www"), 3) == 0.632
    assert round(run_confidence("cwcwcw"), 3) == 0.231


def test_consistent_evidence_beats_mixed_evidence():
    """The headline defect: the old formula scored these two identically."""

    assert run_confidence("ccccc") > 0.8
    assert run_confidence("cwcwcw") < 0.30
    # and the gap is what matters: mixed evidence must stay the wrong side of the 0.5
    # gate that the mastery decision uses.
    assert run_confidence("cwcwcw") < 0.5 <= run_confidence("ccc")


def test_confident_that_a_student_does_NOT_know_something():
    """Three consistent failures is strong evidence, not weak evidence."""

    assert run_confidence("www") == pytest.approx(run_confidence("ccc"), abs=1e-9)


def test_confidence_can_decrease():
    """The property the attempt-counting formula could not express at all."""

    steady = run_confidence("ccccc")
    then_erratic = run_confidence("cccccwcwcw")
    assert then_erratic < steady


def test_three_consistent_observations_cross_the_evidence_gate():
    """policy.py gates redirects on confidence >= 0.5; CONFIDENCE_K = 3.0 preserves it."""

    assert run_confidence("cc") < 0.5
    assert run_confidence("ccc") >= 0.5


def test_learning_is_not_punished_as_inconsistency():
    """Three failures then three successes is a student improving, not noise."""

    assert run_confidence("wwwccc") > run_confidence("cwcwcw")


def test_a_recovered_student_can_still_reach_the_mastery_gate():
    """The case that set LAMBDA.

    policy.py caps a skill at four attempts per session. A student who fails twice and
    then succeeds twice has spent that budget, so if their confidence cannot reach 0.5
    they can never be marked as having got there -- however well they finish. This is the
    test that would have caught a recency discount set too slow.
    """

    assert run_confidence("wwcc") >= 0.5


def test_syntax_errors_accumulate_confidence_slowly():
    weight_total = correct_mass = wrong_mass = 0.0
    for _ in range(5):
        weight_total, correct_mass, wrong_mass = accumulate(
            weight_total,
            correct_mass,
            wrong_mass,
            fail(outcome=StudentOutcome.STUDENT_SYNTAX_ERROR, n=2),
        )
    five_syntax = confidence_from_evidence(
        weight_total, correct_mass, wrong_mass, PRM.p_slip, PRM.p_guess
    )
    assert five_syntax < run_confidence("ww")


def test_confidence_is_zero_without_evidence():
    assert confidence_from_evidence(0.0, 0.0, 0.0, PRM.p_slip, PRM.p_guess) == 0.0


def test_confidence_is_bounded():
    import random

    rng = random.Random(7)
    weight_total = correct_mass = wrong_mass = 0.0
    for _ in range(300):
        obs = ok(n=2) if rng.random() < 0.5 else fail(score=rng.random(), n=2)
        weight_total, correct_mass, wrong_mass = accumulate(
            weight_total, correct_mass, wrong_mass, obs
        )
        c = confidence_from_evidence(
            weight_total, correct_mass, wrong_mass, PRM.p_slip, PRM.p_guess
        )
        # Saturates at 1.0 rather than approaching it: after ~40 consistent observations
        # the evidence term rounds to 1 in floating point. Unlike mastery this needs no
        # ceiling -- confidence is never inverted into odds, so 1.0 costs us nothing but
        # "we have plenty of evidence".
        assert 0.0 <= c <= 1.0


def test_mastery_one_point_zero_with_confidence_zero_point_seven_one_is_impossible():
    """The exact pair a student reported. Mastery can no longer reach 1.00 at all."""

    node = SkillNode(skill="functions", mastery=0.30, confidence=0.0)
    for _ in range(6):
        node, _ = update_skill(node, ok(n=2), PRM)
    assert node.mastery <= MASTERY_CEILING
    assert node.confidence > 0.8  # was 0.7135 for any six attempts whatsoever


# ------------------------------------------------------------------------- unmeasured


def test_a_fresh_skill_is_unmeasured():
    node = SkillNode(skill="loops", mastery=PRM.p_init, confidence=0.0)
    assert node.measured is False
    assert node.evidence_weight == 0.0


def test_one_observation_makes_a_skill_measured():
    node = SkillNode(skill="loops", mastery=PRM.p_init, confidence=0.0)
    node, _ = update_skill(node, fail(n=2), PRM)
    assert node.measured is True
