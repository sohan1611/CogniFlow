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
from app.models.schemas import AdaptationDecision, SkillNode


MASTERY_THRESHOLD = 0.6
CONFIDENCE_THRESHOLD = 0.5
ESCALATE_THRESHOLD = 0.8
MAX_LOOPS = 25
MAX_ATTEMPTS_PER_SKILL = 4
MAX_PREREQ_DEPTH = 3


def is_mastered(mastery: float, confidence: float) -> bool:
    """Has this student actually mastered the skill?

    This is the system's ONE definition, and everything that claims a skill is finished
    must call it. Both halves are load-bearing. Mastery says the estimate is high;
    confidence says there is enough evidence behind the estimate to believe it. After a
    single correct answer BKT returns mastery 0.85 at confidence 0.22 -- a number that
    looks like knowledge and is actually a prior that has been nudged once.

    The API's learning plan used to test mastery alone, and so told a student who had
    answered one question per topic that five of eight were "Completed", while `decide`
    below -- looking at the identical numbers through both halves -- would refuse to
    ADVANCE any of them. One word, two meanings, and the student was shown the wrong one.

    Not to be confused with `SkillGraph.is_mastered`, which tests mastery against a bare
    threshold and answers a different question: whether a PREREQUISITE is good enough to
    let the student move on past it. That one governs routing, deliberately ignores
    confidence, and must not be changed to match this -- locking a topic because the
    tutor is unsure about something upstream would strand students behind their own
    lack of evidence.
    """
    return mastery >= MASTERY_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD

# Evidence gates for prerequisite redirects:
# PREREQ_EVIDENCE_CONFIDENCE prevents the tutor from treating a prior-like
# mastery estimate as diagnosis-level evidence after only a small number of
# observations.
PREREQ_EVIDENCE_CONFIDENCE = 0.5
# PREREQ_MIN_ATTEMPTS lets repeated direct observations substitute for the
# confidence scalar when the node has enough concrete attempts behind it.
PREREQ_MIN_ATTEMPTS = 3
# PREREQ_REDIRECT_THRESHOLD is the bar for ACTING on a suspected gap, stricter than the
# practised skill; otherwise the failures are not evidence that the prerequisite
# explains the struggle.
PREREQ_REDIRECT_THRESHOLD = 0.45
"""Secondary bar. Currently NON-BINDING at the chosen evidence budget: with three
observations every threshold from 0.30 to 0.50 produces identical results, because the
populations have already separated. Retained as a floor if the evidence budget is ever
reduced, and documented as inert rather than credited with an improvement it did not
produce."""


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
    teaching_mode: TeachingMode = TeachingMode.TEXTUAL
    """How the current skill is being taught right now.

    EXPLAIN_DIFFERENTLY needs this to mean anything: without knowing what was already
    tried, "explain differently" can only pick the same mode again and call it a change.
    """

    misconception_hint: str | None = None
    """A skill implicated by the student's actual mistake, if one was diagnosed.

    This is stronger evidence than the mastery heuristic alone. "Your recursive call is
    computed but not returned" points at `functions` because of what the student DID,
    whereas mastery*confidence only says which prerequisite looks weakest on paper. When
    the two disagree, direct evidence of the error wins -- but only if the hint names a
    genuine, unmastered prerequisite, so it can never redirect somewhere arbitrary.
    """


def prerequisite_has_redirect_evidence(
    ctx: PolicyContext,
    prerequisite: str,
) -> bool:
    """Return whether a prerequisite redirect has enough statistical evidence.

    Invariant: weak prerequisite estimates are not sufficient on their own.
    PREREQ_EVIDENCE_CONFIDENCE and PREREQ_MIN_ATTEMPTS keep the tutor from
    acting on a prior-like estimate, while PREREQ_MARGIN requires the
    prerequisite to be meaningfully weaker than the practised skill before it can
    explain repeated failures.
    """
    node: SkillNode | None = ctx.graph.nodes.get(prerequisite)
    if node is None:
        return False

    has_estimate_evidence = (
        node.confidence >= PREREQ_EVIDENCE_CONFIDENCE
        or node.attempts >= PREREQ_MIN_ATTEMPTS
    )
    # A STRICTER bar to ACT than to NOTICE.
    #
    # MASTERY_THRESHOLD (0.6) answers "is this skill mastered?".
    # PREREQ_REDIRECT_THRESHOLD (0.45) answers a different and more expensive question:
    # "is this prerequisite broken badly enough to justify abandoning the skill the
    # student actually came for?" A detour costs the student time and confidence, so
    # the bar to trigger one is deliberately higher than the bar to record a weakness.
    #
    # Empirically this is where the populations separate: after a two-question pre-test
    # a student whose prerequisite is genuinely fine lands at 0.60-0.94, while one with
    # a real gap lands at 0.18-0.38. The false redirects were control students who got
    # unlucky and drifted into the 0.45-0.60 band.
    #
    # NOTE for anyone tempted to use a relative margin instead: by the time a redirect
    # is under consideration the student has failed the TARGET twice, so the target's
    # estimate has already fallen below the prerequisite's. "Prerequisite must be weaker
    # than the target" is therefore backwards and can essentially never fire.
    is_clearly_broken = node.mastery < PREREQ_REDIRECT_THRESHOLD
    return has_estimate_evidence and is_clearly_broken


def misconception_implicates_prerequisite(
    ctx: PolicyContext,
    prerequisite: str,
) -> bool:
    """Return whether a misconception hint directly implicates this prerequisite.

    Invariant: the hint can bypass statistical evidence only when it names a real
    unmastered prerequisite of the current target.
    """
    if ctx.misconception_hint != prerequisite:
        return False

    unmastered = ctx.graph.unmastered_prerequisites(
        ctx.target_skill,
        MASTERY_THRESHOLD,
    )
    return prerequisite in unmastered


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
        mastered = is_mastered(mastery, confidence)
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
        and is_mastered(mastery, confidence)
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

    if success and is_mastered(mastery, confidence):
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
            # Direct misconception evidence bypasses the statistical evidence
            # gates; the observed mistake is stronger than estimate confidence.
            weakest = hinted
        elif weakest is not None and not prerequisite_has_redirect_evidence(ctx, weakest):
            weakest = None

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
            mode = _next_explanation_mode(ctx.teaching_mode)
            return AdaptationDecision(
                action=AdaptationAction.EXPLAIN_DIFFERENTLY,
                target_skill=ctx.target_skill,
                teaching_mode=mode,
                difficulty=Difficulty.EASY,
                reason=(
                    f"repeated failures at the easiest difficulty; explaining via "
                    f"{mode.value} instead of {ctx.teaching_mode.value}"
                ),
                evidence=evidence + [
                    f"consecutive_failures={ctx.consecutive_failures}",
                    f"previous_mode={ctx.teaching_mode.value}",
                ],
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


# The order an explanation is retried in, weakest change first. Each is a different way
# of showing the SAME idea, not a different idea: a worked example before an analogy
# before a picture, because a student who has just failed twice needs the concrete
# before the figurative.
EXPLANATION_MODES: tuple[TeachingMode, ...] = (
    TeachingMode.WORKED_EXAMPLE,
    TeachingMode.CODE_TRACE,
    TeachingMode.ANALOGY,
    TeachingMode.VISUAL_DESCRIPTION,
    TeachingMode.SOCRATIC_HINTS,
)


def _next_explanation_mode(current: TeachingMode) -> TeachingMode:
    """The next way to explain something, given what has already been tried.

    Deterministic and cyclic. Repeating the approach that just failed is the specific
    thing EXPLAIN_DIFFERENTLY exists to avoid, so the mode always moves; a mode outside
    the rotation (TEXTUAL, the default) enters it at the start.
    """
    if current not in EXPLANATION_MODES:
        return EXPLANATION_MODES[0]
    index = EXPLANATION_MODES.index(current)
    return EXPLANATION_MODES[(index + 1) % len(EXPLANATION_MODES)]


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
