"""Evidence gates on prerequisite redirects.

A detour costs the student time and confidence, so the bar to ACT on a suspected gap is
deliberately higher than the bar to NOTICE weakness. These tests pin that distinction.

The measured effect on the 80-student ablation: false redirects fall from 25% to 7.5%
while gap detection goes from 65% to 57.5%. See docs/ABLATION.md.
"""

from __future__ import annotations

import pytest

from app.mastery.bkt import confidence_from_attempts
from app.mastery.guard import validate
from app.mastery.policy import (
    PREREQ_EVIDENCE_CONFIDENCE,
    PREREQ_MIN_ATTEMPTS,
    PREREQ_REDIRECT_THRESHOLD,
    PolicyContext,
    decide,
)
from app.mastery.skill_graph import SkillGraph
from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
from app.models.schemas import AdaptationDecision, SkillNode


def _graph(*, prereq_mastery: float, prereq_attempts: int) -> SkillGraph:
    """A recursion/functions graph with a controllable evidence level on `functions`."""
    return SkillGraph(
        {
            "variables": SkillNode(skill="variables", mastery=0.9, confidence=0.9, attempts=5),
            "conditionals": SkillNode(
                skill="conditionals", mastery=0.9, confidence=0.9, attempts=5,
                prerequisites=["variables"],
            ),
            "functions": SkillNode(
                skill="functions",
                mastery=prereq_mastery,
                confidence=confidence_from_attempts(prereq_attempts),
                attempts=prereq_attempts,
                prerequisites=["variables"],
            ),
            "recursion": SkillNode(
                skill="recursion", mastery=0.2, confidence=0.7, attempts=4,
                prerequisites=["functions", "conditionals"],
            ),
        }
    )


def _ctx(graph: SkillGraph, *, hint: str | None = None, failures: int = 2) -> PolicyContext:
    return PolicyContext(
        target_skill="recursion",
        graph=graph,
        last_outcome=StudentOutcome.WRONG_ANSWER,
        consecutive_failures=failures,
        topic_attempts=2,
        loop_count=3,
        prereq_depth=0,
        prereq_return_stack=[],
        current_difficulty=Difficulty.MEDIUM,
        misconception_hint=hint,
    )


# ------------------------------------------------------------ the gates
def test_thin_evidence_does_not_trigger_a_redirect() -> None:
    """One observation is a prior with a rumour attached, not grounds for a detour."""
    graph = _graph(prereq_mastery=0.2, prereq_attempts=1)
    decision = decide(_ctx(graph))
    assert decision.action is not AdaptationAction.REVISIT_PREREQUISITE
    assert decision.action in (
        AdaptationAction.STEP_DOWN_DIFFICULTY,
        AdaptationAction.EXPLAIN_DIFFERENTLY,
    )


def test_the_same_prerequisite_with_enough_evidence_does_trigger_one() -> None:
    """Identical mastery, more observations -- only the evidence changed."""
    graph = _graph(prereq_mastery=0.2, prereq_attempts=PREREQ_MIN_ATTEMPTS)
    decision = decide(_ctx(graph))
    assert decision.action is AdaptationAction.REVISIT_PREREQUISITE
    assert decision.target_skill == "functions"


def test_a_prerequisite_that_is_only_marginally_weak_does_not_trigger_one() -> None:
    """Below the mastery threshold but above the ACTION threshold.

    This is the band where control students who got unlucky used to land, and it is
    where the old 25% false-redirect rate came from.
    """
    marginal = (PREREQ_REDIRECT_THRESHOLD + 0.6) / 2  # between action bar and mastery bar
    graph = _graph(prereq_mastery=marginal, prereq_attempts=5)
    decision = decide(_ctx(graph))
    assert decision.action is not AdaptationAction.REVISIT_PREREQUISITE


def test_the_confidence_bar_is_what_demands_a_third_observation() -> None:
    """The evidence budget is derived, not chosen.

    confidence_from_attempts crosses PREREQ_EVIDENCE_CONFIDENCE at three observations,
    which is why the diagnostic pre-test asks three questions rather than two.
    """
    assert confidence_from_attempts(2) < PREREQ_EVIDENCE_CONFIDENCE
    assert confidence_from_attempts(3) >= PREREQ_EVIDENCE_CONFIDENCE


# ------------------------------------------------------- the hint bypass
def test_a_diagnosed_misconception_bypasses_the_evidence_gates() -> None:
    """Direct evidence of the mistake outranks any statistical bar.

    If their code shows an unreturned recursive call, we do not need three more data
    points to believe `functions` is the problem.
    """
    graph = _graph(prereq_mastery=0.55, prereq_attempts=1)  # thin AND only marginally weak
    blocked = decide(_ctx(graph))
    assert blocked.action is not AdaptationAction.REVISIT_PREREQUISITE

    hinted = decide(_ctx(graph, hint="functions"))
    assert hinted.action is AdaptationAction.REVISIT_PREREQUISITE
    assert hinted.target_skill == "functions"


@pytest.mark.parametrize("bad_hint", ["nested_loops", "variables", "not_a_skill", ""])
def test_the_bypass_cannot_be_abused(bad_hint: str) -> None:
    """A hint may only promote a genuine, unmastered prerequisite.

    `nested_loops` is not a prerequisite of recursion; `variables` is mastered;
    `not_a_skill` does not exist. None may cause a redirect.
    """
    graph = _graph(prereq_mastery=0.55, prereq_attempts=1)
    decision = decide(_ctx(graph, hint=bad_hint or None))
    assert decision.action is not AdaptationAction.REVISIT_PREREQUISITE


# --------------------------------------------------------------- guard
def test_guard_rejects_a_model_redirect_that_fails_the_gates() -> None:
    """The model may propose a detour the rules would not take. The guard stops it."""
    graph = _graph(prereq_mastery=0.55, prereq_attempts=1)
    proposal = AdaptationDecision(
        action=AdaptationAction.REVISIT_PREREQUISITE, target_skill="functions"
    )
    verdict = validate(proposal, _ctx(graph))

    assert verdict.overridden is True
    assert "redirect_without_sufficient_evidence" in verdict.violated_rules
    assert verdict.final.action is not AdaptationAction.REVISIT_PREREQUISITE


def test_guard_allows_the_same_redirect_once_a_misconception_backs_it() -> None:
    graph = _graph(prereq_mastery=0.55, prereq_attempts=1)
    proposal = AdaptationDecision(
        action=AdaptationAction.REVISIT_PREREQUISITE, target_skill="functions"
    )
    verdict = validate(proposal, _ctx(graph, hint="functions"))

    assert "redirect_without_sufficient_evidence" not in verdict.violated_rules
    assert verdict.final.action is AdaptationAction.REVISIT_PREREQUISITE


def test_guard_allows_a_well_evidenced_redirect() -> None:
    graph = _graph(prereq_mastery=0.2, prereq_attempts=PREREQ_MIN_ATTEMPTS)
    proposal = AdaptationDecision(
        action=AdaptationAction.REVISIT_PREREQUISITE, target_skill="functions"
    )
    verdict = validate(proposal, _ctx(graph))
    assert verdict.overridden is False
