"""Rule-based adaptation policy for CogniFlow.

Invariant: adaptation decisions are pure functions of typed state and fixed limits.
"""

from dataclasses import dataclass

from app.mastery.skill_graph import SkillGraph
from app.models.enums import (
    AdaptationAction,
    CORRECTNESS,
    Difficulty,
    StudentOutcome,
    TeachingMode,
)
from app.models.schemas import AdaptationDecision


MASTERY_THRESHOLD = 0.6
CONFIDENCE_THRESHOLD = 0.5
ESCALATE_THRESHOLD = 0.8
MAX_LOOPS = 25
MAX_ATTEMPTS_PER_SKILL = 4
MAX_PREREQ_DEPTH = 3


@dataclass
class PolicyContext:
    """State required for deterministic adaptation."""

    target_skill: str
    graph: SkillGraph
    last_outcome: StudentOutcome | None
    consecutive_failures: int
    topic_attempts: int
    loop_count: int
    prereq_depth: int
    prereq_return_stack: list[str]
    current_difficulty: Difficulty = Difficulty.MEDIUM
    misconception_hint: str | None = None
    """A skill implicated by the student's actual mistake, if one was diagnosed.

    This is stronger evidence than the mastery heuristic alone. "Your recursive call is
    computed but not returned" points at `functions` because of what the student DID,
    whereas mastery*confidence only says which prerequisite looks weakest on paper. When
    the two disagree, direct evidence of the error wins -- but only if the hint names a
    genuine, unmastered prerequisite, so it can never redirect somewhere arbitrary.
    """


def decide(ctx: PolicyContext) -> AdaptationDecision:
    """Choose the next deterministic adaptation action."""

    mastery = ctx.graph.mastery(ctx.target_skill)
    confidence = ctx.graph.nodes[ctx.target_skill].confidence
    evidence = _evidence(ctx, mastery, confidence)
    success = ctx.last_outcome is not None and CORRECTNESS[ctx.last_outcome]
    failure = ctx.last_outcome is not None and not CORRECTNESS[ctx.last_outcome]

    tripped_limits = _tripped_limits(ctx)
    if tripped_limits:
        # Report WHY we stopped honestly. A session that ends at mastery 0.88 because
        # the per-skill attempt cap was reached is a success, not a limit failure, and
        # saying "limit tripped" there reads as a bug to anyone watching.
        mastered = mastery >= MASTERY_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD
        reason = (
            f"target skill mastered (mastery={mastery:.2f}); session limit also reached: "
            f"{', '.join(tripped_limits)}"
            if mastered
            else f"limit tripped: {', '.join(tripped_limits)}"
        )
        return AdaptationDecision(
            action=AdaptationAction.COMPLETE,
            target_skill=ctx.target_skill,
            reason=reason,
            evidence=evidence + [f"limits={','.join(tripped_limits)}", f"mastered={mastered}"],
            confidence=confidence,
        )

    # Returning to the ORIGINAL objective outranks perfecting the detour. Without this
    # ordering the agent masters the prerequisite and then keeps escalating inside it,
    # never going back to the skill the student actually came for -- which defeats the
    # whole point of a prerequisite redirect.
    if (
        success
        and ctx.prereq_return_stack
        and mastery >= MASTERY_THRESHOLD
        and confidence >= CONFIDENCE_THRESHOLD
    ):
        return AdaptationDecision(
            action=AdaptationAction.REVISIT_PREREQUISITE,
            target_skill=ctx.prereq_return_stack[-1],
            reason="prerequisite mastered, returning to original target",
            evidence=evidence + [f"return_stack_size={len(ctx.prereq_return_stack)}"],
            confidence=confidence,
        )

    if success and mastery >= ESCALATE_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD:
        return AdaptationDecision(
            action=AdaptationAction.ESCALATE_DIFFICULTY,
            target_skill=ctx.target_skill,
            difficulty=_escalated_difficulty(ctx.current_difficulty),
            reason="current skill mastered at escalation threshold",
            evidence=evidence + [f"mastery>={ESCALATE_THRESHOLD}", f"confidence>={CONFIDENCE_THRESHOLD}"],
            confidence=confidence,
        )

    if success and mastery >= MASTERY_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD:
        return AdaptationDecision(
            action=AdaptationAction.ADVANCE,
            target_skill=ctx.target_skill,
            reason="current skill mastered with sufficient confidence",
            evidence=evidence + [
                f"mastery>={MASTERY_THRESHOLD}",
                f"confidence>={CONFIDENCE_THRESHOLD}",
            ],
            confidence=confidence,
        )

    if failure and ctx.consecutive_failures == 1:
        return AdaptationDecision(
            action=AdaptationAction.RETRY_VARIATION,
            target_skill=ctx.target_skill,
            difficulty=ctx.current_difficulty,
            reason="first failure on current skill, retrying a variation",
            evidence=evidence + ["consecutive_failures=1"],
            confidence=confidence,
        )

    if failure and ctx.consecutive_failures >= 2:
        unmastered = ctx.graph.unmastered_prerequisites(ctx.target_skill, MASTERY_THRESHOLD)
        weakest = ctx.graph.weakest_prerequisite(ctx.target_skill, MASTERY_THRESHOLD)

        # Direct evidence of the mistake outranks the mastery heuristic, but only when
        # it names a real unmastered prerequisite of the skill in question.
        hinted = ctx.misconception_hint
        if hinted and hinted in unmastered:
            weakest = hinted

        if weakest is not None and ctx.prereq_depth < MAX_PREREQ_DEPTH:
            return AdaptationDecision(
                action=AdaptationAction.REVISIT_PREREQUISITE,
                target_skill=weakest,
                teaching_mode=TeachingMode.CODE_TRACE,
                difficulty=Difficulty.EASY,
                reason=(
                f"diagnosed misconception implicates '{weakest}'"
                if ctx.misconception_hint == weakest
                else "repeated failures indicate an unmastered prerequisite"
            ),
                evidence=evidence + [
                    f"consecutive_failures={ctx.consecutive_failures}",
                    f"weakest_prerequisite={weakest}",
                ],
                confidence=confidence,
            )
        if ctx.current_difficulty == Difficulty.EASY:
            return AdaptationDecision(
                action=AdaptationAction.EXPLAIN_DIFFERENTLY,
                target_skill=ctx.target_skill,
                teaching_mode=TeachingMode.WORKED_EXAMPLE,
                difficulty=Difficulty.EASY,
                reason="repeated failures remain at easiest difficulty",
                evidence=evidence + [f"consecutive_failures={ctx.consecutive_failures}"],
                confidence=confidence,
            )
        return AdaptationDecision(
            action=AdaptationAction.STEP_DOWN_DIFFICULTY,
            target_skill=ctx.target_skill,
            difficulty=_stepped_down_difficulty(ctx.current_difficulty),
            reason="repeated failures with no weak prerequisite, stepping down difficulty",
            evidence=evidence + [f"consecutive_failures={ctx.consecutive_failures}"],
            confidence=confidence,
        )

    return AdaptationDecision(
        action=AdaptationAction.REASSESS,
        target_skill=ctx.target_skill,
        reason="insufficient evidence for mastery or remediation decision",
        evidence=evidence + ["fallback=reassess"],
        confidence=confidence,
    )


def _tripped_limits(ctx: PolicyContext) -> list[str]:
    limits: list[str] = []
    if ctx.loop_count >= MAX_LOOPS:
        limits.append("loop_count")
    if ctx.topic_attempts >= MAX_ATTEMPTS_PER_SKILL:
        limits.append("topic_attempts")
    return limits


def _evidence(ctx: PolicyContext, mastery: float, confidence: float) -> list[str]:
    outcome = ctx.last_outcome.value if ctx.last_outcome is not None else "none"
    return [
        f"target_skill={ctx.target_skill}",
        f"last_outcome={outcome}",
        f"mastery={mastery:.6f}",
        f"confidence={confidence:.6f}",
    ]


def _escalated_difficulty(current: Difficulty) -> Difficulty:
    if current == Difficulty.EASY:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def _stepped_down_difficulty(current: Difficulty) -> Difficulty:
    if current == Difficulty.HARD:
        return Difficulty.MEDIUM
    return Difficulty.EASY
