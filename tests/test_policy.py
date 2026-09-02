"""Tests for deterministic adaptation policy.

Invariant: policy branches depend only on typed context and fixed thresholds.
"""

import pytest

from app.mastery.policy import MAX_ATTEMPTS_PER_SKILL, MAX_LOOPS, PolicyContext, decide
from app.mastery.skill_graph import SkillGraph
from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
from app.models.schemas import SkillNode


def node(
    skill: str,
    mastery: float,
    confidence: float = 0.7,
    prerequisites: list[str] | None = None,
    attempts: int = 4,
) -> SkillNode:
    """Default attempts=4 so fixtures carry the evidence a real session would have.

    Prerequisite redirects now require evidence; a node with zero observations is a
    prior, and the policy deliberately refuses to act on one.
    """
    return SkillNode(
        skill=skill,
        mastery=mastery,
        confidence=confidence,
        attempts=attempts,
        prerequisites=prerequisites or [],
    )


def graph_for(
    target_mastery: float = 0.5,
    target_confidence: float = 0.7,
    variables_mastery: float = 0.8,
    conditionals_mastery: float = 0.8,
) -> SkillGraph:
    return SkillGraph(
        {
            "variables": node("variables", variables_mastery),
            "conditionals": node("conditionals", conditionals_mastery, prerequisites=["variables"]),
            "loops": node(
                "loops",
                target_mastery,
                confidence=target_confidence,
                prerequisites=["variables", "conditionals"],
            ),
        }
    )


def ctx(
    graph: SkillGraph,
    last_outcome: StudentOutcome | None,
    consecutive_failures: int = 0,
    topic_attempts: int = 0,
    loop_count: int = 0,
    target_skill: str = "loops",
    prereq_depth: int = 0,
    prereq_return_stack: list[str] | None = None,
    current_difficulty: Difficulty = Difficulty.MEDIUM,
    misconception_hint: str | None = None,
) -> PolicyContext:
    return PolicyContext(
        target_skill=target_skill,
        graph=graph,
        last_outcome=last_outcome,
        consecutive_failures=consecutive_failures,
        topic_attempts=topic_attempts,
        loop_count=loop_count,
        prereq_depth=prereq_depth,
        prereq_return_stack=prereq_return_stack or [],
        current_difficulty=current_difficulty,
        misconception_hint=misconception_hint,
    )


def test_high_performance_advances() -> None:
    decision = decide(ctx(graph_for(target_mastery=0.7), StudentOutcome.CORRECT))
    assert decision.action == AdaptationAction.ADVANCE


def test_first_failure_retries_variation() -> None:
    decision = decide(
        ctx(
            graph_for(target_mastery=0.5),
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=1,
        )
    )
    assert decision.action == AdaptationAction.RETRY_VARIATION
    assert decision.target_skill == "loops"


def test_repeated_failure_with_weak_prerequisite_revisits_prereq() -> None:
    decision = decide(
        ctx(
            graph_for(target_mastery=0.5, conditionals_mastery=0.3),
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
        )
    )
    assert decision.action == AdaptationAction.REVISIT_PREREQUISITE
    assert decision.target_skill == "conditionals"
    assert decision.difficulty == Difficulty.EASY


def test_repeated_failure_with_no_weak_prerequisite_steps_down() -> None:
    decision = decide(
        ctx(
            graph_for(target_mastery=0.5),
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
        )
    )
    assert decision.action == AdaptationAction.STEP_DOWN_DIFFICULTY
    assert decision.difficulty == Difficulty.EASY


def test_prerequisite_selection_picks_functions_in_demo_scenario() -> None:
    """Plan requirement 4, updated when evidence gates were introduced.

    In the demo, `functions` sits at 0.55 -- weak, but not BADLY broken. That is above
    PREREQ_REDIRECT_THRESHOLD, so mastery alone is deliberately not enough to justify
    abandoning recursion. What justifies it is the diagnosed misconception: the
    student's code showed an unreturned recursive call, which implicates `functions`
    directly. That is exactly how the real demo drives this redirect.

    Both directions are asserted, so the behaviour is pinned rather than assumed.
    """
    graph = SkillGraph(
        {
            "variables": node("variables", 0.9),
            "conditionals": node("conditionals", 0.9, prerequisites=["variables"]),
            "loops": node("loops", 0.8, prerequisites=["variables", "conditionals"]),
            "functions": node("functions", 0.55, prerequisites=["variables"]),
            "recursion": node("recursion", 0.35, prerequisites=["functions", "conditionals"]),
        }
    )

    with_evidence = decide(
        ctx(
            graph,
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
            target_skill="recursion",
            misconception_hint="functions",
        )
    )
    assert with_evidence.action == AdaptationAction.REVISIT_PREREQUISITE
    assert with_evidence.target_skill == "functions"

    # Without the diagnosis, a merely-weak prerequisite does not justify the detour.
    without = decide(
        ctx(
            graph,
            StudentOutcome.WRONG_ANSWER,
            consecutive_failures=2,
            target_skill="recursion",
        )
    )
    assert without.action is not AdaptationAction.REVISIT_PREREQUISITE

@pytest.mark.parametrize(
    ("loop_count", "topic_attempts"),
    [(MAX_LOOPS, 0), (0, MAX_ATTEMPTS_PER_SKILL)],
)
def test_loop_and_attempt_limits_complete(loop_count: int, topic_attempts: int) -> None:
    decision = decide(
        ctx(
            graph_for(target_mastery=0.7),
            StudentOutcome.CORRECT,
            loop_count=loop_count,
            topic_attempts=topic_attempts,
        )
    )
    assert decision.action == AdaptationAction.COMPLETE


def test_returning_from_prerequisite_targets_popped_skill() -> None:
    graph = SkillGraph(
        {
            "variables": node("variables", 0.9),
            "functions": node("functions", 0.7, prerequisites=["variables"]),
            "recursion": node("recursion", 0.4, prerequisites=["functions"]),
        }
    )
    decision = decide(
        ctx(
            graph,
            StudentOutcome.CORRECT,
            target_skill="functions",
            prereq_return_stack=["recursion"],
        )
    )
    assert decision.action == AdaptationAction.REVISIT_PREREQUISITE
    assert decision.target_skill == "recursion"
    assert decision.reason == "prerequisite mastered, returning to original target"


def test_a_prerequisite_with_no_evidence_does_not_trigger_a_redirect() -> None:
    """Companion to the above: the SAME scenario without observations must NOT redirect.

    Added when evidence gates were introduced. The pair pins the change in both
    directions -- with evidence the demo redirect still fires, without it the tutor
    declines to act on a prior.
    """
    from app.mastery.policy import PolicyContext, decide
    from app.mastery.skill_graph import SkillGraph
    from app.models.enums import AdaptationAction, Difficulty, StudentOutcome
    from app.models.schemas import SkillNode

    nodes = {
        "variables": SkillNode(skill="variables", mastery=0.90, confidence=0.85, attempts=3),
        "conditionals": SkillNode(skill="conditionals", mastery=0.85, confidence=0.80,
                                  attempts=3, prerequisites=["variables"]),
        "functions": SkillNode(skill="functions", mastery=0.55, confidence=0.0,
                               attempts=0, prerequisites=["variables"]),
        "recursion": SkillNode(skill="recursion", mastery=0.35, confidence=0.50, attempts=3,
                               prerequisites=["functions", "conditionals"]),
    }
    decision = decide(PolicyContext(
        target_skill="recursion", graph=SkillGraph(nodes),
        last_outcome=StudentOutcome.WRONG_ANSWER, consecutive_failures=2,
        topic_attempts=2, loop_count=3, prereq_depth=0, prereq_return_stack=[],
        current_difficulty=Difficulty.MEDIUM,
    ))
    assert decision.action is not AdaptationAction.REVISIT_PREREQUISITE

