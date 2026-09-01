"""Deterministic guard for proposed adaptation decisions.

Invariant: guard output never violates the hard adaptation rules it enforces.
"""

from app.mastery.policy import (
    CONFIDENCE_THRESHOLD,
    ESCALATE_THRESHOLD,
    MASTERY_THRESHOLD,
    MAX_ATTEMPTS_PER_SKILL,
    MAX_LOOPS,
    MAX_PREREQ_DEPTH,
    PolicyContext,
    decide,
)
from app.models.enums import AdaptationAction
from app.models.schemas import AdaptationDecision, GuardVerdict


def validate(proposed: AdaptationDecision, ctx: PolicyContext) -> GuardVerdict:
    """Validate a proposed decision and override it with deterministic policy if needed."""

    violations = _violated_rules(proposed, ctx)
    if not violations:
        return GuardVerdict(
            final=proposed,
            overridden=False,
            proposed_action=proposed.action,
        )

    final = decide(ctx)
    if _violated_rules(final, ctx):
        final = _safe_complete(ctx)
    return GuardVerdict(
        final=final,
        overridden=True,
        violated_rules=violations,
        proposed_action=proposed.action,
    )


def _violated_rules(decision: AdaptationDecision, ctx: PolicyContext) -> list[str]:
    violations: list[str] = []
    mastery = ctx.graph.mastery(ctx.target_skill)
    confidence = ctx.graph.nodes[ctx.target_skill].confidence

    if (
        decision.action == AdaptationAction.ADVANCE
        and (mastery < MASTERY_THRESHOLD or confidence < CONFIDENCE_THRESHOLD)
    ):
        violations.append("advance_requires_mastery")

    # A pending return stack is an unmet obligation: the agent detoured away from a
    # skill the student came for, and must go back before moving on. The deterministic
    # policy respects this by branch ordering, but a MODEL proposing freely does not --
    # a live provider proposed ADVANCE here and silently abandoned the original
    # objective, which is precisely the failure this guard exists to prevent.
    if (
        decision.action
        in (AdaptationAction.ADVANCE, AdaptationAction.ESCALATE_DIFFICULTY)
        and ctx.prereq_return_stack
    ):
        violations.append("must_return_to_original_objective")

    if decision.action == AdaptationAction.ESCALATE_DIFFICULTY and (
        mastery < ESCALATE_THRESHOLD or confidence < CONFIDENCE_THRESHOLD
    ):
        # Mastery alone is not enough. One lucky answer can push a BKT posterior past
        # 0.8 while confidence is still ~0.2, and escalating there is the classic
        # overconfident-tutor failure: the student gets a harder problem on the
        # strength of a single data point.
        violations.append("escalate_requires_mastery")

    # Redirecting on a SINGLE failure is only justified when the student's actual
    # mistake implicates that prerequisite. One bad answer is noise; one bad answer plus
    # a diagnosed cause is evidence. Without this, a model will happily abandon a skill
    # after one wobble -- which is the mirror image of never redirecting at all.
    if (
        decision.action == AdaptationAction.REVISIT_PREREQUISITE
        and ctx.consecutive_failures < 2
        and not ctx.prereq_return_stack
        and ctx.misconception_hint != decision.target_skill
    ):
        violations.append("premature_redirect_without_evidence")

    if decision.action == AdaptationAction.REVISIT_PREREQUISITE:
        unmastered = ctx.graph.unmastered_prerequisites(ctx.target_skill, MASTERY_THRESHOLD)
        if not ctx.prereq_return_stack and decision.target_skill not in unmastered:
            violations.append("prereq_must_exist")
        if ctx.prereq_depth >= MAX_PREREQ_DEPTH:
            violations.append("prereq_depth_exceeded")

    if _limits_breached(ctx) and decision.action != AdaptationAction.COMPLETE:
        violations.append("loop_limit")

    if decision.target_skill is not None and decision.target_skill not in ctx.graph.nodes:
        violations.append("unknown_skill")

    if (
        decision.action == AdaptationAction.STEP_DOWN_DIFFICULTY
        and ctx.consecutive_failures >= 2
        and ctx.graph.weakest_prerequisite(ctx.target_skill, MASTERY_THRESHOLD) is not None
    ):
        violations.append("repeated_failure_needs_investigation")

    return violations


def _limits_breached(ctx: PolicyContext) -> bool:
    return ctx.loop_count >= MAX_LOOPS or ctx.topic_attempts >= MAX_ATTEMPTS_PER_SKILL


def _safe_complete(ctx: PolicyContext) -> AdaptationDecision:
    target_skill = ctx.target_skill if ctx.target_skill in ctx.graph.nodes else None
    evidence = [
        f"target_skill={ctx.target_skill}",
        "guard_override=complete",
    ]
    return AdaptationDecision(
        action=AdaptationAction.COMPLETE,
        target_skill=target_skill,
        reason="guard fallback selected complete to preserve hard invariants",
        evidence=evidence,
        confidence=ctx.graph.nodes[ctx.target_skill].confidence if target_skill is not None else 0.5,
    )
