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


# ------------------------------------------------ wording must match the actual code
NON_RECURSIVE = "def add(a, b):\n    print(a + b)\n\ntotal = add(2, 3)\nprint(total + 1)"
RECURSIVE = "def total(n):\n    n + total(n - 1)\n\nprint(total(5) + 1)"
NONETYPE_ERROR = "TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'"


def test_non_recursive_code_is_not_told_its_recursive_call_is_wrong() -> None:
    """A NoneType arithmetic error means a function returned None. It does not mean the
    function was recursive, and a student who wrote no recursion being told their
    "recursive call" is wrong stops trusting the tutor -- correctly.
    """
    from app.mastery.misconceptions import detect, student_note_for
    from app.models.enums import StudentOutcome

    found = detect(code=NON_RECURSIVE, stdout="", stderr=NONETYPE_ERROR,
                   outcome=StudentOutcome.STUDENT_RUNTIME_ERROR)
    assert found is not None
    # The diagnosis is right either way -- only the wording adapts.
    assert found.prerequisite_hint == "functions"
    assert "recursi" not in student_note_for(found, NON_RECURSIVE).lower()


def test_recursive_code_still_gets_the_recursion_wording() -> None:
    from app.mastery.misconceptions import detect, student_note_for
    from app.models.enums import StudentOutcome

    found = detect(code=RECURSIVE, stdout="", stderr=NONETYPE_ERROR,
                   outcome=StudentOutcome.STUDENT_RUNTIME_ERROR)
    assert "recursi" in student_note_for(found, RECURSIVE).lower()


def test_a_call_after_the_function_is_not_recursion() -> None:
    """Regression: the old regex bounded a function body by indentation and failed.

    `total = add(2, 3)` sits at module level AFTER the def, and was read as the function
    calling itself -- so a draft with no recursion was offered recursion hints.
    """
    from app.mastery.misconceptions import analyse_draft

    assert analyse_draft(NON_RECURSIVE).recursive is False
    assert analyse_draft(RECURSIVE).recursive is True


def test_hints_follow_the_draft_not_the_pattern_name() -> None:
    from app.mastery.misconceptions import hints_for

    plain = hints_for("functions", NON_RECURSIVE)[0].lower()
    assert "calling itself" not in plain, "recursion hints offered for non-recursive code"


def test_unparseable_drafts_are_handled_not_crashed() -> None:
    """Hints are offered on unfinished work, so half-written code is the normal case."""
    from app.mastery.misconceptions import analyse_draft, hints_for

    facts = analyse_draft("def broken(:\n    this is not python")
    assert facts.parses is False and facts.recursive is False
    assert hints_for("functions", "def broken(:")  # still returns a usable ladder


def test_the_same_skill_at_different_levels_gets_different_hints() -> None:
    """Reported by a student: every recursion problem gave the same two hints.

    It did. With an empty editor there was no draft to read, so hint selection fell
    straight to a fixed pair per skill -- and an EASY base-case exercise and a HARD
    divide-and-conquer one were handed identical advice. The rung knows what its level
    demands, so a blank editor can still get a hint aimed at THIS problem.
    """
    from app.mastery.misconceptions import hints_for

    first = {
        level: hints_for("recursion", None, level)[0]
        for level in ("EASY", "MEDIUM", "HARD")
    }
    assert len(set(first.values())) == 3, f"levels still share a hint: {first}"


def test_what_they_wrote_still_beats_what_they_were_asked() -> None:
    """A recognisable mistake in the draft is the most useful thing available, and
    adding a difficulty signal must not demote it."""
    from app.mastery.misconceptions import hints_for

    printed = "def double(n):\n    print(n * 2)\n\ndouble(6)"
    from_draft = hints_for("functions", printed, "HARD")
    from_level = hints_for("functions", None, "HARD")
    assert from_draft != from_level
    assert "asking for" not in from_draft[0], "the draft hint was replaced by the rung one"


def test_an_unknown_difficulty_falls_back_rather_than_raising() -> None:
    """`difficulty` arrives as a string off graph state and may be absent or junk."""
    from app.mastery.misconceptions import hints_for

    baseline = hints_for("loops")
    assert hints_for("loops", None, None) == baseline
    assert hints_for("loops", None, "NONSENSE") == baseline
