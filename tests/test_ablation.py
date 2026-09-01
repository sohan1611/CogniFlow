"""Phase 7 tests: the simulator, the ablation harness, and BKT fitting.

The ablation is only worth reporting if the harness is FAIR. Most of these tests exist
to catch the ways a comparison can quietly cheat -- unequal budgets, leaked ground
truth, a pre-test that secretly teaches, or a cohort with no controls. Two such bugs
were found this way during development, and both had reversed the result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.mastery.bkt import BKTParams
from app.mastery.skill_graph import SkillGraph
from eval.ablation import MAX_STEPS, Arm, run_ablation, run_session, summarize
from eval.bkt_fit import auc, evaluate, fit, generate_trajectories, predict_next
from eval.simulator import PREREQ_HELD, SimConfig, SimulatedStudent, make_cohort

SKILLS = Path("app/config/skills.yaml")


@pytest.fixture(scope="module")
def base_nodes():
    return SkillGraph.from_yaml(SKILLS).nodes


@pytest.fixture(scope="module")
def start_nodes(base_nodes):
    return {
        k: v.model_copy(update={"mastery": 0.35, "confidence": 0.2, "attempts": 0})
        for k, v in base_nodes.items()
    }


# ------------------------------------------------------------- simulator
def test_missing_prerequisite_suppresses_performance(base_nodes) -> None:
    """Gating must actually bite, or the whole experiment is vacuous."""
    graph = SkillGraph(base_nodes)
    strong = {s: 0.9 for s in base_nodes}
    gapped = {**strong, "functions": 0.2}

    a = SimulatedStudent(true_skill=dict(strong), graph=graph)
    b = SimulatedStudent(true_skill=dict(gapped), graph=graph)

    assert b.effective_ability("recursion") < a.effective_ability("recursion") * 0.5


def test_practising_a_blocked_skill_barely_teaches(base_nodes) -> None:
    """The claim that makes prerequisite-finding valuable rather than decorative."""
    graph = SkillGraph(base_nodes)
    blocked = SimulatedStudent(
        true_skill={**{s: 0.9 for s in base_nodes}, "functions": 0.2, "recursion": 0.2},
        graph=graph,
    )
    clear = SimulatedStudent(
        true_skill={**{s: 0.9 for s in base_nodes}, "recursion": 0.2}, graph=graph
    )
    for _ in range(5):
        blocked.attempt("recursion")
        clear.attempt("recursion")

    assert clear.true_skill["recursion"] > blocked.true_skill["recursion"] + 0.3


def test_assess_measures_without_teaching(base_nodes) -> None:
    """A pre-test that teaches would fix the planted gap for every arm for free."""
    graph = SkillGraph(base_nodes)
    student = SimulatedStudent(
        true_skill={s: 0.4 for s in base_nodes}, graph=graph
    )
    before = dict(student.true_skill)
    for _ in range(10):
        student.assess("recursion")
    assert student.true_skill == before, "assess() changed the student"

    student.attempt("recursion")
    assert student.true_skill["recursion"] != before["recursion"], "attempt() must teach"


def test_cohort_contains_both_gapped_students_and_controls(base_nodes) -> None:
    cohort = make_cohort(base_nodes, n=40)
    gapped = [g for _, g in cohort if g]
    controls = [g for _, g in cohort if not g]
    assert len(gapped) == len(controls) == 20

    for student, gap in cohort:
        if gap:
            assert student.true_skill["functions"] < PREREQ_HELD
        else:
            assert student.true_skill["functions"] >= PREREQ_HELD


def test_cohort_is_reproducible(base_nodes) -> None:
    a = make_cohort(base_nodes, n=10, seed=7)
    b = make_cohort(base_nodes, n=10, seed=7)
    assert [s.true_skill for s, _ in a] == [s.true_skill for s, _ in b]


# ------------------------------------------------------- harness fairness
def test_every_arm_receives_an_identical_step_budget(base_nodes, start_nodes) -> None:
    """The bug that reversed the first result: arm A ran 40 steps, arm B ran 4."""
    budgets: dict[Arm, set[int]] = {}
    for arm in Arm:
        results = [
            run_session(arm, student, start_nodes, gap)
            for student, gap in make_cohort(base_nodes, n=8)
        ]
        budgets[arm] = {r.steps for r in results}
    assert all(b == {MAX_STEPS} for b in budgets.values()), budgets


def test_policies_never_observe_the_hidden_skill_vector(base_nodes, start_nodes) -> None:
    """The tutor's belief must be driven by observations, not by ground truth."""
    cohort = make_cohort(base_nodes, n=4)
    for student, gap in cohort:
        truth = dict(student.true_skill)
        result = run_session(Arm.RULES, student, start_nodes, gap)
        # A tutor peeking at ground truth would have near-zero estimate error.
        assert result.estimate_error > 0.0
        assert set(truth) == set(student.true_skill)


def test_no_prerequisite_arm_structurally_cannot_redirect(base_nodes, start_nodes) -> None:
    results = [
        run_session(Arm.NO_PREREQ, s, start_nodes, g)
        for s, g in make_cohort(base_nodes, n=20)
    ]
    assert all(r.redirected_to == [] for r in results)
    assert summarize(Arm.NO_PREREQ, results).gap_detection_rate == 0.0


# --------------------------------------------------------- the headline
def test_prerequisite_awareness_beats_drilling(base_nodes) -> None:
    """The claim the project rests on, measured rather than asserted.

    Deliberately asserts a DIRECTION, not a magic number -- a test pinned to an exact
    figure would break on any harmless tuning and teach the team to ignore it.
    """
    summaries = run_ablation(n=60)
    a = summaries[Arm.NO_PREREQ]
    b = summaries[Arm.RULES]

    assert b.gap_detection_rate > 0.4, "should find most planted gaps"
    assert a.gap_detection_rate == 0.0, "control arm cannot find gaps by construction"
    assert b.median_steps is not None and a.median_steps is not None
    assert b.median_steps < a.median_steps, "should reach mastery in fewer attempts"
    assert b.mean_estimate_error < a.mean_estimate_error, "should model students better"


def test_false_redirect_rate_is_reported_not_hidden() -> None:
    """Diagnosis has a cost, and the harness must surface it."""
    summaries = run_ablation(n=40)
    b = summaries[Arm.RULES]
    assert 0.0 <= b.false_redirect_rate <= 1.0
    assert b.false_redirect_rate > 0.0, (
        "a redirect policy with a literally zero false-positive rate would be "
        "suspicious; if this ever passes, check the controls are real"
    )


def test_ablation_is_deterministic() -> None:
    first = run_ablation(n=30)
    second = run_ablation(n=30)
    for arm in Arm:
        assert first[arm].median_steps == second[arm].median_steps
        assert first[arm].gap_detection_rate == second[arm].gap_detection_rate


# --------------------------------------------------------------- BKT fit
def test_auc_matches_known_values() -> None:
    assert auc([0.1, 0.4, 0.35, 0.8], [False, False, True, True]) == pytest.approx(0.75)
    assert auc([1, 2, 3], [False, False, True]) == pytest.approx(1.0)
    assert auc([1, 1, 1], [True, False, True]) == pytest.approx(0.5)
    assert auc([1.0], [True]) == 0.5  # degenerate: single class


def test_predict_next_rises_with_a_record_of_success() -> None:
    prm = BKTParams()
    assert predict_next([True] * 5, prm) > predict_next([False] * 5, prm)


def test_fitting_improves_the_quantity_it_optimises() -> None:
    """The fitter maximises likelihood, so judge it on held-out likelihood."""
    from eval.bkt_fit import mean_log_likelihood

    sequences = generate_trajectories("recursion", n=120, length=10)
    train, test = sequences[:84], sequences[84:]
    terrible = BKTParams(p_init=0.9, p_transit=0.02, p_slip=0.45, p_guess=0.45)
    fitted = fit(train)
    assert mean_log_likelihood(test, fitted) > mean_log_likelihood(test, terrible)


def test_auc_is_rank_invariant_and_so_hides_calibration_errors() -> None:
    """Documents a real finding, not a quirk.

    Badly calibrated parameters can match or beat well-fitted ones on AUC, because AUC
    only asks whether students are ORDERED correctly. This is why fitting does not
    improve AUC much here -- and it is the honest reason the project keeps literature
    defaults: the system consumes mastery as a threshold comparison, which depends on
    ranking rather than on calibrated probabilities.
    """
    from eval.bkt_fit import mean_log_likelihood

    sequences = generate_trajectories("recursion", n=120, length=10)
    train, test = sequences[:84], sequences[84:]
    terrible = BKTParams(p_init=0.9, p_transit=0.02, p_slip=0.45, p_guess=0.45)
    fitted = fit(train)

    # far better calibrated ...
    assert mean_log_likelihood(test, fitted) > mean_log_likelihood(test, terrible) + 0.05
    # ... yet AUC barely distinguishes them
    assert abs(evaluate(test, fitted) - evaluate(test, terrible)) < 0.05


def test_training_data_is_not_generated_by_a_bkt_process() -> None:
    """Guards the anti-circularity claim in the docstring.

    The simulator gates on prerequisites; BKT has no such concept. If trajectories ever
    stopped depending on prerequisite state, the fitting study would become circular.
    """
    strong = generate_trajectories("recursion", n=60, length=10, seed=1)
    assert any(any(seq) for seq in strong)
    # a third of the cohort carries a prerequisite gap, so success rates must vary widely
    rates = sorted(sum(s) / len(s) for s in strong)
    assert rates[-1] - rates[0] > 0.4, "no regime variation -> gating is not in the data"
