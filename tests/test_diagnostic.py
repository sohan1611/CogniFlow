"""The adaptive diagnostic.

What makes it a diagnostic rather than a quiz is what it DOESN'T ask.
"""

from __future__ import annotations

import pytest

from app.mastery.policy import MASTERY_THRESHOLD
from app.mastery.skill_graph import SkillGraph, weakest_startable
from app.models.enums import StudentOutcome
from app.services.diagnostic import (
    QUESTIONS,
    UNKNOWN_MASTERY,
    DiagnosticSession,
)

SKILLS = "app/config/skills.yaml"


@pytest.fixture
def graph() -> SkillGraph:
    return SkillGraph.from_yaml(SKILLS)


def _run(graph: SkillGraph, answer) -> tuple[DiagnosticSession, list[str]]:
    session = DiagnosticSession(graph=graph)
    asked: list[str] = []
    while (question := session.next_question()) is not None:
        asked.append(question.skill)
        session.record(question.skill, answer(question.skill))
    return session, asked


def test_every_skill_in_the_graph_has_a_question(graph: SkillGraph) -> None:
    """A skill with no probe is a skill the diagnostic silently guesses at."""
    covered = {q.skill for q in QUESTIONS}
    assert covered == set(graph.nodes), f"no diagnostic question for {set(graph.nodes) - covered}"


def test_foundations_are_asked_before_what_depends_on_them(graph: SkillGraph) -> None:
    """An answer about recursion means nothing until we know about functions."""
    _, asked = _run(graph, lambda _s: StudentOutcome.CORRECT)
    for skill in asked:
        for prereq in graph.prerequisites(skill):
            assert asked.index(prereq) < asked.index(skill), (
                f"{skill} was asked before its prerequisite {prereq}"
            )


def test_a_failed_skill_prunes_everything_downstream(graph: SkillGraph) -> None:
    """Someone who cannot write a function will fail recursion too.

    Asking them to prove it twice tells us nothing and costs them the will to continue.
    """
    session, asked = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "functions" else StudentOutcome.CORRECT,
    )
    assert "functions" in asked
    for downstream in ("recursion", "function_call_tracing", "recursion_tree"):
        assert downstream not in asked, f"{downstream} was asked despite functions failing"
        assert session.skipped[downstream] == "functions"
    # Unrelated branches are still explored.
    assert "loops" in asked and "nested_loops" in asked


def test_failing_the_root_skill_ends_the_diagnostic_immediately(graph: SkillGraph) -> None:
    """Everything depends on variables, so there is nothing left worth asking."""
    session, asked = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "variables" else StudentOutcome.CORRECT,
    )
    assert asked == ["variables"]
    assert len(session.skipped) == len(graph.nodes) - 1


def test_mastery_comes_from_evidence_not_a_constant(graph: SkillGraph) -> None:
    """The point of the whole exercise: a profile that was measured, not assumed."""
    strong, _ = _run(graph, lambda _s: StudentOutcome.CORRECT)
    weak, _ = _run(graph, lambda _s: StudentOutcome.WRONG_ANSWER)

    strong_nodes, _ = strong.finish(MASTERY_THRESHOLD)
    weak_nodes, _ = weak.finish(MASTERY_THRESHOLD)

    assert strong_nodes["variables"].mastery > UNKNOWN_MASTERY
    assert weak_nodes["variables"].mastery < UNKNOWN_MASTERY
    assert strong_nodes["variables"].mastery != weak_nodes["variables"].mastery


def test_a_skipped_skill_is_unmeasured_and_records_why(graph: SkillGraph) -> None:
    """A pruned question stays unknown; prerequisite evidence is not its measurement."""
    session, _ = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "functions" else StudentOutcome.CORRECT,
    )
    nodes, result = session.finish(MASTERY_THRESHOLD)

    skipped = nodes["recursion"]
    assert skipped.mastery == UNKNOWN_MASTERY
    assert skipped.confidence == 0.0
    assert skipped.attempts == 0
    assert skipped.evidence_weight == 0.0
    assert skipped.agree_correct == 0.0
    assert skipped.agree_wrong == 0.0
    assert skipped.measured is False
    assert result.skipped_because["recursion"] == "functions"
    assert result.weak_skills[0] == "functions"
    measured_flags = [nodes[skill].measured for skill in result.weak_skills]
    assert measured_flags == sorted(measured_flags, reverse=True)


def test_removing_the_skipped_cap_does_not_change_routing(graph: SkillGraph) -> None:
    """Prerequisite gating already keeps skipped descendants out of the startable set."""
    session, _ = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "functions" else StudentOutcome.CORRECT,
    )
    nodes, result = session.finish(MASTERY_THRESHOLD)

    # Reconstruct the deleted behaviour to prove the routing verdict did not depend on it.
    legacy_nodes = dict(nodes)
    for skill, blocker in result.skipped_because.items():
        legacy_nodes[skill] = nodes[skill].model_copy(
            update={
                "mastery": min(
                    nodes[blocker].mastery,
                    MASTERY_THRESHOLD - 0.05,
                )
            }
        )
    legacy_graph = SkillGraph(legacy_nodes)
    legacy_weak = sorted(
        (s for s, n in legacy_nodes.items() if n.mastery < MASTERY_THRESHOLD),
        key=lambda s: (
            legacy_nodes[s].mastery,
            bool(legacy_graph.unmastered_prerequisites(s, MASTERY_THRESHOLD)),
            s,
        ),
    )

    assert weakest_startable(nodes, MASTERY_THRESHOLD) == "functions"
    assert weakest_startable(legacy_nodes, MASTERY_THRESHOLD) == "functions"
    assert result.target_skill == legacy_weak[0] == "functions"


def test_result_names_the_weakest_skill_and_its_gaps(graph: SkillGraph) -> None:
    session, _ = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "functions" else StudentOutcome.CORRECT,
    )
    _, result = session.finish(MASTERY_THRESHOLD)
    assert result.target_skill == "functions"
    assert result.evidence, "a diagnosis with no evidence is an assertion"
    assert any("functions=" in item for item in result.evidence)


def test_diagnosis_confidence_reflects_how_much_was_asked(graph: SkillGraph) -> None:
    """Four answers is a sketch; eight is a picture. Confidence must say which."""
    full, _ = _run(graph, lambda _s: StudentOutcome.CORRECT)
    partial, _ = _run(
        graph,
        lambda s: StudentOutcome.WRONG_ANSWER if s == "variables" else StudentOutcome.CORRECT,
    )
    _, full_result = full.finish(MASTERY_THRESHOLD)
    _, partial_result = partial.finish(MASTERY_THRESHOLD)
    assert full_result.confidence > partial_result.confidence


def test_questions_are_gradeable_by_execution(graph: SkillGraph) -> None:
    """Every probe must have something the sandbox can actually check."""
    for question in QUESTIONS:
        problem = question.as_problem()
        assert problem["expected_output"], f"{question.skill} has no expected output"
        assert problem["test_cases"], f"{question.skill} has no test case"
        assert question.prompt.strip(), f"{question.skill} has no prompt"
