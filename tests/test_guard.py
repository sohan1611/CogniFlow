"""Tests for deterministic adaptation guard.

Invariant: final guard verdicts satisfy every hard guard rule.
"""

import pytest

from app.mastery.guard import validate
from app.mastery.policy import (
    CONFIDENCE_THRESHOLD,
    ESCALATE_THRESHOLD,
    MASTERY_THRESHOLD,
    MAX_ATTEMPTS_PER_SKILL,
    MAX_LOOPS,
    MAX_PREREQ_DEPTH,
    PolicyContext,
)
from app.mastery.skill_graph import SkillGraph
from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
from app.models.schemas import AdaptationDecision, SkillNode


def node(
    skill: str,
    mastery: float,
    confidence: float = 0.7,
    prerequisites: list[str] | None = None,
) -> SkillNode:
    return SkillNode(
        skill=skill,
        mastery=mastery,
        confidence=confidence,
        prerequisites=prerequisites or [],
    )


def graph_for(target_mastery: float, target_confidence: float, prereq_mastery: float = 0.8) -> SkillGraph:
    return SkillGraph(
        {
            "variables": node("variables", prereq_mastery),
            "loops": node(
                "loops",
                target_mastery,
                confidence=target_confidence,
                prerequisites=["variables"],
            ),
        }
    )


def ctx(
    graph: SkillGraph,
    last_outcome: StudentOutcome | None = None,
    consecutive_failures: int = 0,
    topic_attempts: int = 0,
    loop_count: int = 0,
    prereq_depth: int = 0,
    prereq_return_stack: list[str] | None = None,
    current_difficulty: Difficulty = Difficulty.MEDIUM,
) -> PolicyContext:
    return PolicyContext(
        target_skill="loops",
        graph=graph,
        last_outcome=last_outcome,
        consecutive_failures=consecutive_failures,
        topic_attempts=topic_attempts,
        loop_count=loop_count,
        prereq_depth=prereq_depth,
        prereq_return_stack=prereq_return_stack or [],
        current_difficulty=current_difficulty,
    )


def decision(action: AdaptationAction, target_skill: str | None = "loops") -> AdaptationDecision:
    return AdaptationDecision(
        action=action,
        target_skill=target_skill,
        reason="test proposal",
        evidence=["test"],
    )


def test_advance_at_low_mastery_is_overridden() -> None:
    context = ctx(graph_for(target_mastery=0.2, target_confidence=0.8))
    verdict = validate(decision(AdaptationAction.ADVANCE), context)
    assert verdict.overridden is True
    assert "advance_requires_mastery" in verdict.violated_rules
    assert verdict.proposed_action == AdaptationAction.ADVANCE


def test_revisit_without_unmastered_prerequisite_is_overridden() -> None:
    context = ctx(graph_for(target_mastery=0.5, target_confidence=0.8, prereq_mastery=0.9))
    verdict = validate(decision(AdaptationAction.REVISIT_PREREQUISITE, target_skill="variables"), context)
    assert verdict.overridden is True
    assert "prereq_must_exist" in verdict.violated_rules


def test_valid_proposal_passes_through_unchanged() -> None:
    context = ctx(
        graph_for(target_mastery=0.5, target_confidence=0.8),
        last_outcome=StudentOutcome.WRONG_ANSWER,
        consecutive_failures=1,
    )
    proposed = decision(AdaptationAction.RETRY_VARIATION)
    verdict = validate(proposed, context)
    assert verdict.overridden is False
    assert verdict.final == proposed


def test_final_verdict_satisfies_invariants_for_all_actions() -> None:
    contexts = [
        ctx(graph_for(0.2, 0.8)),
        ctx(graph_for(0.7, 0.7), StudentOutcome.CORRECT),
        ctx(
            graph_for(0.5, 0.7, prereq_mastery=0.2),
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
        ),
        ctx(
            graph_for(0.5, 0.7),
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
            loop_count=MAX_LOOPS,
        ),
        ctx(
            graph_for(0.7, 0.7),
            StudentOutcome.CORRECT,
            prereq_depth=MAX_PREREQ_DEPTH,
            prereq_return_stack=["loops"],
        ),
    ]
    targets = {
        AdaptationAction.REVISIT_PREREQUISITE: "variables",
        AdaptationAction.COMPLETE: None,
    }
    for context in contexts:
        for action in AdaptationAction:
            proposed = decision(action, target_skill=targets.get(action, "loops"))
            verdict = validate(proposed, context)
            assert_satisfies_invariants(verdict.final, context)


def assert_satisfies_invariants(final: AdaptationDecision, context: PolicyContext) -> None:
    mastery = context.graph.mastery(context.target_skill)
    confidence = context.graph.nodes[context.target_skill].confidence
    if final.action == AdaptationAction.ADVANCE:
        assert mastery >= MASTERY_THRESHOLD
        assert confidence >= CONFIDENCE_THRESHOLD
    if final.action == AdaptationAction.ESCALATE_DIFFICULTY:
        assert mastery >= ESCALATE_THRESHOLD
    if final.action == AdaptationAction.REVISIT_PREREQUISITE:
        unmastered = context.graph.unmastered_prerequisites(context.target_skill, MASTERY_THRESHOLD)
        assert context.prereq_return_stack or final.target_skill in unmastered
        assert context.prereq_depth < MAX_PREREQ_DEPTH
    if context.loop_count >= MAX_LOOPS or context.topic_attempts >= MAX_ATTEMPTS_PER_SKILL:
        assert final.action == AdaptationAction.COMPLETE
    if final.target_skill is not None:
        assert final.target_skill in context.graph.nodes
    if (
        final.action == AdaptationAction.STEP_DOWN_DIFFICULTY
        and context.consecutive_failures >= 2
    ):
        assert context.graph.weakest_prerequisite(context.target_skill, MASTERY_THRESHOLD) is None


def test_advance_is_blocked_while_a_prerequisite_return_is_owed() -> None:
    """Regression: a live model proposed ADVANCE mid-detour and abandoned the target.

    The deterministic policy never does this because of branch ordering, so the gap was
    invisible until a real provider proposed freely. That is the whole point of having
    a guard rather than trusting the model.
    """
    from app.mastery.guard import validate
    from app.mastery.policy import PolicyContext
    from app.mastery.skill_graph import SkillGraph
    from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
    from app.models.schemas import AdaptationDecision, SkillNode

    nodes = {
        "variables": SkillNode(skill="variables", mastery=0.9, confidence=0.9),
        "functions": SkillNode(
            skill="functions", mastery=0.8, confidence=0.8, attempts=5,
            prerequisites=["variables"],
        ),
        "recursion": SkillNode(
            skill="recursion", mastery=0.3, confidence=0.6,
            prerequisites=["functions"],
        ),
    }
    ctx = PolicyContext(
        target_skill="functions",
        graph=SkillGraph(nodes),
        last_outcome=StudentOutcome.CORRECT,
        consecutive_failures=0,
        topic_attempts=2,
        loop_count=4,
        prereq_depth=1,
        prereq_return_stack=["recursion"],
        current_difficulty=Difficulty.MEDIUM,
    )

    for action in (AdaptationAction.ADVANCE, AdaptationAction.ESCALATE_DIFFICULTY):
        verdict = validate(AdaptationDecision(action=action, target_skill="functions"), ctx)
        assert verdict.overridden, f"{action} should be blocked mid-detour"
        assert "must_return_to_original_objective" in verdict.violated_rules
        assert verdict.final.action is AdaptationAction.REVISIT_PREREQUISITE
        assert verdict.final.target_skill == "recursion"


def test_advance_is_allowed_once_nothing_is_owed() -> None:
    """The rule must not fire when there is no outstanding detour."""
    from app.mastery.guard import validate
    from app.mastery.policy import PolicyContext
    from app.mastery.skill_graph import SkillGraph
    from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
    from app.models.schemas import AdaptationDecision, SkillNode

    nodes = {
        "variables": SkillNode(skill="variables", mastery=0.9, confidence=0.9),
        "functions": SkillNode(
            skill="functions", mastery=0.8, confidence=0.8, attempts=5,
            prerequisites=["variables"],
        ),
    }
    ctx = PolicyContext(
        target_skill="functions",
        graph=SkillGraph(nodes),
        last_outcome=StudentOutcome.CORRECT,
        consecutive_failures=0,
        topic_attempts=2,
        loop_count=4,
        prereq_depth=0,
        prereq_return_stack=[],
        current_difficulty=Difficulty.MEDIUM,
    )
    verdict = validate(AdaptationDecision(action=AdaptationAction.ADVANCE, target_skill="functions"), ctx)
    assert verdict.overridden is False
