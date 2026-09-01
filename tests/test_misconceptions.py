"""Tests for deterministic misconception detection.

These patterns exist so the model is consulted only where judgement is genuinely
required. A `RecursionError` means a missing base case -- that is what the exception
means, not an opinion -- so recognising it in code is cheaper, faster, and identical on
every run.

The most important property tested here is the one that makes the redirect causal:
a misconception must implicate the skill actually at fault, which is frequently NOT the
skill being practised.
"""

from __future__ import annotations

import pytest

from app.mastery.misconceptions import PATTERNS, detect
from app.models.enums import StudentOutcome


def test_recursion_error_is_a_missing_base_case() -> None:
    found = detect(
        code="def f(n):\n    return n * f(n-1)",
        stdout="",
        stderr="RecursionError: maximum recursion depth exceeded",
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR,
    )
    assert found is not None
    assert found.key == "missing_base_case"
    assert "base case" in found.label


def test_none_arithmetic_implicates_functions_not_recursion() -> None:
    """The finding the whole architecture rests on.

    A student failing recursion because their recursive call returns None does not have
    a recursion problem. They have a `return` problem, which is a FUNCTIONS problem
    wearing a recursion costume. The misconception must say so, because that is what
    turns the redirect from a heuristic into a diagnosis.
    """
    found = detect(
        code="def total(n):\n    if n == 0:\n        return 0\n    total(n-1) + n",
        stdout="",
        stderr="TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'",
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR,
    )
    assert found is not None
    assert found.key == "unreturned_recursive_call"
    assert found.prerequisite_hint == "functions", (
        "must implicate functions, not the skill being practised"
    )


def test_timeout_is_an_infinite_loop() -> None:
    found = detect(
        code="while True: pass", stdout="", stderr="",
        outcome=StudentOutcome.STUDENT_TIMEOUT,
    )
    assert found is not None
    assert found.key == "infinite_loop"
    assert found.prerequisite_hint == "loops"


def test_print_instead_of_return_is_detected_from_source() -> None:
    found = detect(
        code="def double(x):\n    print(x * 2)\n\nprint(double(4))",
        stdout="8\nNone",
        stderr="",
        outcome=StudentOutcome.WRONG_ANSWER,
    )
    assert found is not None
    assert found.prerequisite_hint == "functions"


def test_name_error_implicates_variables() -> None:
    found = detect(
        code="print(undefined_thing)", stdout="",
        stderr="NameError: name 'undefined_thing' is not defined",
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR,
    )
    assert found is not None and found.prerequisite_hint == "variables"


def test_stderr_evidence_outranks_source_inference() -> None:
    """An actual traceback is stronger evidence than a guess from the source text."""
    found = detect(
        code="def f(x):\n    print(x)",           # would match print_instead_of_return
        stdout="",
        stderr="RecursionError: maximum recursion depth exceeded",
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR,
    )
    assert found is not None and found.key == "missing_base_case"


def test_correct_submissions_and_clean_failures_yield_nothing() -> None:
    """Detection must not invent a misconception where there is no signal."""
    assert detect(code="print(42)", stdout="42", stderr="", outcome=StudentOutcome.CORRECT) is None
    assert (
        detect(code="print(1)", stdout="1", stderr="", outcome=StudentOutcome.WRONG_ANSWER)
        is None
    ), "a plain wrong answer with no signature must not be over-diagnosed"


def test_detection_never_raises_on_junk_input() -> None:
    """Student code and interpreter output are both untrusted."""
    for code in (None, "", "\x00\x01", "def f(:" * 50, "λ" * 100):
        for outcome in StudentOutcome:
            detect(code=code, stdout="", stderr="", outcome=outcome)


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.key)
def test_every_pattern_is_well_formed(pattern) -> None:
    """Each pattern must be actionable: a label, and some way to match."""
    assert pattern.label and len(pattern.label) > 15, "labels must explain, not name"
    assert (
        pattern.stderr_patterns or pattern.stdout_patterns or pattern.code_patterns
        or pattern.outcomes
    ), f"{pattern.key} can never match anything"


def test_prerequisite_hints_name_real_skills() -> None:
    """A hint pointing at a skill outside the graph could never drive a redirect."""
    from pathlib import Path

    from app.mastery.skill_graph import SkillGraph

    known = set(SkillGraph.from_yaml(Path("app/config/skills.yaml")).nodes)
    for pattern in PATTERNS:
        if pattern.prerequisite_hint:
            assert pattern.prerequisite_hint in known, (
                f"{pattern.key} implicates unknown skill {pattern.prerequisite_hint!r}"
            )


def test_hint_only_redirects_to_a_genuine_unmastered_prerequisite() -> None:
    """The hint is evidence, not an override.

    It may only promote a skill that is genuinely an unmastered prerequisite. Otherwise
    a bad diagnosis could send a student somewhere arbitrary.
    """
    from app.mastery.policy import PolicyContext, decide
    from app.mastery.skill_graph import SkillGraph
    from app.models.enums import AdaptationAction, StudentOutcome as SO
    from app.models.schemas import SkillNode

    nodes = {
        "variables": SkillNode(skill="variables", mastery=0.9, confidence=0.9),
        "conditionals": SkillNode(skill="conditionals", mastery=0.3, confidence=0.8,
                                  prerequisites=["variables"]),
        "functions": SkillNode(skill="functions", mastery=0.5, confidence=0.8,
                               prerequisites=["variables"]),
        "recursion": SkillNode(skill="recursion", mastery=0.2, confidence=0.7,
                               prerequisites=["functions", "conditionals"]),
    }
    graph = SkillGraph(nodes)

    def run(hint):
        return decide(PolicyContext(
            target_skill="recursion", graph=graph, last_outcome=SO.WRONG_ANSWER,
            consecutive_failures=2, topic_attempts=2, loop_count=3,
            prereq_depth=0, prereq_return_stack=[], misconception_hint=hint,
        ))

    # conditionals is weaker on mastery*confidence (0.24 vs 0.40), so it wins by default
    assert run(None).target_skill == "conditionals"
    # a hint naming a real unmastered prerequisite promotes it
    assert run("functions").target_skill == "functions"
    # a hint naming something that is NOT a prerequisite is ignored
    assert run("nested_loops").target_skill == "conditionals"
    # a hint naming a MASTERED prerequisite is ignored
    assert run("variables").target_skill == "conditionals"
    assert run(None).action is AdaptationAction.REVISIT_PREREQUISITE
