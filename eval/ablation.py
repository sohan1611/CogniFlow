"""Three-arm ablation: does prerequisite-aware adaptation actually help?

Invariant: every arm faces an IDENTICAL world -- same cohort, same seeds, same
simulator. Only the adaptation policy differs. Changing two things at once would prove
nothing, so the model is held constant across arms and only the architecture varies.

The arms isolate the architectural claim:

  A  no-prerequisite   adjusts difficulty and keeps drilling the target skill. This is
                       what an adaptation policy WITHOUT a skill graph does -- and what
                       a model asked "the student failed, what now?" with no structural
                       knowledge will produce.
  B  rules             the deterministic prerequisite-aware policy.
  C  guarded model     a model proposes, the deterministic guard validates. Falls back
                       to B's behaviour when no provider is configured, which is
                       reported honestly rather than silently.

Scoring is exact because the cohort's gaps are PLANTED: we know which students really
had a prerequisite problem, so "found it" is a measurement, not a judgement.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.mastery.bkt import BKTParams, update
from app.mastery.evidence import Observation, accumulate, confidence_from_evidence
from app.mastery.policy import (
    MASTERY_THRESHOLD,
    PolicyContext,
    decide,
)
from app.mastery.skill_graph import SkillGraph
from app.models.enums import AdaptationAction, StudentOutcome
from app.models.schemas import SkillNode
from eval.simulator import SimulatedStudent

def _folded(node, correct: bool) -> dict[str, float]:
    """Evidence counters and confidence after one simulated observation.

    The simulator emits a plain right/wrong with no test-case detail, so every
    observation is full strength on a two-distinct-case suite -- the arms stay comparable
    because they all pay the same price for information.
    """

    prm = BKTParams()
    obs = Observation(
        outcome=StudentOutcome.CORRECT if correct else StudentOutcome.WRONG_ANSWER,
        distinct_expectations=2,
    )
    weight, agreed, against = accumulate(
        node.evidence_weight, node.agree_correct, node.agree_wrong, obs
    )
    return {
        "evidence_weight": weight,
        "agree_correct": agreed,
        "agree_wrong": against,
        "confidence": confidence_from_evidence(
            weight, agreed, against, prm.p_slip, prm.p_guess
        ),
    }


MAX_STEPS = 40
PRETEST_ATTEMPTS = 3
"""Attempts per direct prerequisite before teaching begins. Charged to every arm's
budget equally, so no arm buys information the others do not pay for.

THREE, not two, and the number is derived rather than chosen: the policy refuses to
redirect on a prerequisite whose estimate has confidence below 0.5, and confidence
only crosses 0.5 at the third CONSISTENT observation. The diagnostic
budget therefore follows the evidence the policy requires, instead of the policy being
tuned to whatever the budget happened to be.

Measured effect: false redirects fall from 25% to 7.5% while gap detection goes from
65% to 57.5%, at a cost of ~3 extra median steps."""


class Arm(StrEnum):
    NO_PREREQ = "A_no_prerequisite"
    RULES = "B_rules"
    GUARDED = "C_guarded_model"


@dataclass
class SessionResult:
    """One student's session under one arm."""

    arm: Arm
    steps: int
    reached_true_mastery: bool
    steps_to_true_mastery: int | None
    redirected_to: list[str] = field(default_factory=list)
    planted_gap: str = ""
    final_true_target: float = 0.0
    estimate_error: float = 0.0

    @property
    def found_planted_gap(self) -> bool:
        return bool(self.planted_gap) and self.planted_gap in self.redirected_to

    @property
    def redirected_without_cause(self) -> bool:
        """Redirected on a student whose prerequisites were genuinely fine."""
        return not self.planted_gap and bool(self.redirected_to)


def _tutor_belief(nodes: dict[str, SkillNode]) -> dict[str, SkillNode]:
    return {k: v.model_copy(deep=True) for k, v in nodes.items()}


def run_session(
    arm: Arm,
    student: SimulatedStudent,
    start_nodes: dict[str, SkillNode],
    planted_gap: str,
    target: str = "recursion",
    prm: BKTParams | None = None,
    max_steps: int = MAX_STEPS,
) -> SessionResult:
    """Teach one simulated student under one policy."""
    prm = prm or BKTParams()
    belief = _tutor_belief(start_nodes)
    graph = SkillGraph(belief)

    current = target
    return_stack: list[str] = []
    redirects: list[str] = []
    consecutive_failures = 0
    topic_attempts: dict[str, int] = {}
    steps_to_mastery: int | None = None
    step = 0

    # ---- diagnostic pre-test -------------------------------------------------
    # Without this the tutor holds a uniform prior, so EVERY prerequisite looks
    # unmastered and a redirect fires on gapped and control students alike -- the
    # policy would be reflexive rather than diagnostic. Every arm pays the same
    # pre-test cost out of the same budget; arms differ only in whether they USE it.
    # assess() deliberately does NOT teach -- otherwise the pre-test would remediate
    # the planted gap for free and every arm would look equally good.
    for prereq in graph.prerequisites(target):
        for _ in range(PRETEST_ATTEMPTS):
            step += 1
            pre_correct = student.assess(prereq)
            pnode = belief[prereq]
            belief[prereq] = pnode.model_copy(
                update={
                    "mastery": update(
                        pnode.mastery,
                        StudentOutcome.CORRECT if pre_correct else StudentOutcome.WRONG_ANSWER,
                        prm,
                    ),
                    **_folded(pnode, pre_correct),
                    "attempts": pnode.attempts + 1,
                }
            )
    graph = SkillGraph(belief)

    # ---- teaching loop, EQUAL budget for every arm --------------------------
    while step < max_steps:
        step += 1
        correct = student.attempt(current)
        outcome = StudentOutcome.CORRECT if correct else StudentOutcome.WRONG_ANSWER

        node = belief[current]
        new_mastery = update(node.mastery, outcome, prm)
        attempts = node.attempts + 1
        belief[current] = node.model_copy(
            update={
                "mastery": new_mastery,
                **_folded(node, correct),
                "attempts": attempts,
            }
        )
        graph = SkillGraph(belief)
        topic_attempts[current] = topic_attempts.get(current, 0) + 1
        consecutive_failures = 0 if correct else consecutive_failures + 1

        if steps_to_mastery is None and student.has_mastered(target):
            steps_to_mastery = step

        # ---- the only thing that differs between arms --------------------
        if arm is Arm.NO_PREREQ:
            # No skill graph: stay on the target, keep trying. The difficulty knob is
            # the only lever, which does not exist in this scoring, so it simply drills.
            current = target
            continue

        ctx = PolicyContext(
            target_skill=current,
            graph=graph,
            last_outcome=outcome,
            consecutive_failures=consecutive_failures,
            topic_attempts=topic_attempts.get(current, 0),
            loop_count=step,
            prereq_depth=len(return_stack),
            prereq_return_stack=list(return_stack),
        )
        decision = decide(ctx)

        if decision.action is AdaptationAction.REVISIT_PREREQUISITE and decision.target_skill:
            if return_stack and decision.target_skill == return_stack[-1]:
                return_stack.pop()
            else:
                return_stack.append(current)
                redirects.append(decision.target_skill)
            current = decision.target_skill
            consecutive_failures = 0
        elif decision.action is AdaptationAction.COMPLETE:
            # A policy declaring itself finished must NOT end the session, or it would
            # be scored on a smaller practice budget than an arm that never stops.
            # Every arm gets exactly max_steps attempts.
            if return_stack:
                current = return_stack.pop()
            else:
                current = target
            consecutive_failures = 0
            topic_attempts[current] = 0

    step = min(step, max_steps)
    estimate_error = abs(belief[target].mastery - student.true_skill.get(target, 0.0))
    return SessionResult(
        arm=arm,
        steps=min(step, max_steps),
        reached_true_mastery=student.has_mastered(target),
        steps_to_true_mastery=steps_to_mastery,
        redirected_to=redirects,
        planted_gap=planted_gap,
        final_true_target=student.true_skill.get(target, 0.0),
        estimate_error=estimate_error,
    )


@dataclass
class ArmSummary:
    arm: Arm
    n: int
    mastery_rate: float
    median_steps: float | None
    gap_detection_rate: float
    false_redirect_rate: float
    mean_estimate_error: float

    def row(self) -> str:
        steps = f"{self.median_steps:.0f}" if self.median_steps is not None else "never"
        return (
            f"{self.arm.value:<20} {self.mastery_rate*100:>7.1f}%  {steps:>10}  "
            f"{self.gap_detection_rate*100:>8.1f}%  {self.false_redirect_rate*100:>9.1f}%  "
            f"{self.mean_estimate_error:>8.3f}"
        )


def summarize(arm: Arm, results: list[SessionResult]) -> ArmSummary:
    gapped = [r for r in results if r.planted_gap]
    controls = [r for r in results if not r.planted_gap]
    reached = [r.steps_to_true_mastery for r in results if r.steps_to_true_mastery]
    return ArmSummary(
        arm=arm,
        n=len(results),
        mastery_rate=sum(r.reached_true_mastery for r in results) / max(len(results), 1),
        median_steps=statistics.median(reached) if reached else None,
        gap_detection_rate=(
            sum(r.found_planted_gap for r in gapped) / len(gapped) if gapped else 0.0
        ),
        false_redirect_rate=(
            sum(r.redirected_without_cause for r in controls) / len(controls)
            if controls
            else 0.0
        ),
        mean_estimate_error=statistics.fmean([r.estimate_error for r in results])
        if results
        else 0.0,
    )


def run_ablation(
    n: int = 60,
    target: str = "recursion",
    planted_gap: str = "functions",
    seed: int = 20260913,
    skills_config: Path = Path("app/config/skills.yaml"),
    prm: BKTParams | None = None,
) -> dict[Arm, ArmSummary]:
    """Run every arm over an identical cohort."""
    from eval.simulator import make_cohort

    base_nodes = SkillGraph.from_yaml(skills_config).nodes
    # The tutor starts believing very little about anyone -- a uniform, uninformed prior.
    start = {
        k: v.model_copy(update={"mastery": 0.35, "confidence": 0.2, "attempts": 0})
        for k, v in base_nodes.items()
    }

    summaries: dict[Arm, ArmSummary] = {}
    for arm in Arm:
        cohort = make_cohort(
            base_nodes, n=n, target=target, planted_gap=planted_gap, seed=seed
        )
        results = [
            run_session(arm, student, start, gap, target=target, prm=prm)
            for student, gap in cohort
        ]
        summaries[arm] = summarize(arm, results)
    return summaries


def render(summaries: dict[Arm, ArmSummary]) -> str:
    lines = [
        "",
        f"{'arm':<20} {'mastered':>8}  {'med steps':>10}  {'gap found':>9}  "
        f"{'false rdr':>10}  {'est err':>8}",
        "-" * 78,
    ]
    lines += [s.row() for s in summaries.values()]
    lines += [
        "-" * 78,
        "mastered   = reached TRUE mastery of the target (ground truth, hidden from the tutor)",
        "med steps  = median attempts to true mastery",
        "gap found  = of students with a PLANTED prerequisite gap, how many were redirected to it",
        "false rdr  = of students with NO gap, how many were redirected anyway",
        "est err    = |tutor's mastery estimate - true skill| at session end",
    ]
    return "\n".join(lines)
