"""Tests for progressive, non-answer hint ladders."""

from __future__ import annotations

import re

import pytest

from app.mastery.misconceptions import PATTERNS, detect, hints_for
from app.models.enums import StudentOutcome


PATTERN_BY_KEY = {pattern.key: pattern for pattern in PATTERNS}


def test_hint_matching_never_changes_diagnosis() -> None:
    """Hints are guesses about a draft; diagnosis reroutes a student.

    These were briefly the same code path, and a print-vs-return mistake started
    implicating `conditionals` instead of `functions`.
    """
    code = 'def greet(name):\n    print("hi " + name)\n\nx = greet("a")\nprint(x)'
    found = detect(
        code=code,
        stdout="",
        stderr="",
        outcome=StudentOutcome.WRONG_ANSWER,
    )

    assert found is not None and found.key == "print_instead_of_return"
    assert found.prerequisite_hint == "functions"


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda pattern: pattern.key)
def test_every_pattern_has_exactly_two_hints(pattern) -> None:
    assert len(pattern.hints) == 2
    assert all(hint.strip() for hint in pattern.hints)


def test_hints_do_not_contain_copy_paste_fixes() -> None:
    return_instruction = re.compile(r"\badd\s+(a\s+)?return\b", re.IGNORECASE)
    guarded_patterns = (
        PATTERN_BY_KEY["missing_base_case"],
        PATTERN_BY_KEY["unreturned_recursive_call"],
    )

    for pattern in guarded_patterns:
        for hint in pattern.hints:
            assert not return_instruction.search(hint)
            assert "return the" not in hint.lower()

    for pattern in PATTERNS:
        for hint in pattern.hints:
            assert "```" not in hint
            assert "=" not in hint


def test_hints_for_recursion_returns_two_non_empty_strings() -> None:
    hints = hints_for("recursion")

    assert len(hints) == 2
    assert all(hint.strip() for hint in hints)


def test_hints_for_uses_student_code_before_generic_skill_ladder() -> None:
    generic = hints_for("recursion")
    specific = hints_for(
        "recursion",
        code="def total(n):\n    return n + total(n - 1)",
    )

    assert specific == PATTERN_BY_KEY["missing_base_case"].hints
    assert specific != generic


def test_hints_for_unknown_skill_still_returns_helpful_text() -> None:
    hints = hints_for("a-skill-that-does-not-exist")

    assert hints
    assert all(hint.strip() for hint in hints)


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda pattern: pattern.key)
def test_hints_are_not_the_student_note(pattern) -> None:
    assert pattern.student_note
    assert pattern.student_note not in pattern.hints
    assert all(hint != pattern.student_note for hint in pattern.hints)
