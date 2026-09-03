"""Deterministic misconception patterns.

Invariant: this module never calls a model. It recognises the misconceptions that have
an unambiguous signature in the interpreter's own output, so the LLM is only consulted
for the cases that genuinely need judgement.

Why bother when we have a model: a `RecursionError` means a missing or unreachable base
case. That is not a matter of opinion, it is what the exception means. Asking a model to
infer it would add latency, cost, and the possibility of a different answer each time,
to a question whose answer is already known. The model earns its place on the cases
these rules cannot name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import StudentOutcome


@dataclass(frozen=True)
class Pattern:
    """One recognisable misconception."""

    key: str
    label: str
    prerequisite_hint: str | None
    """The skill this misconception really implicates, which is often NOT the skill
    being practised -- a `NoneType` arithmetic error during recursion is a `return`
    misunderstanding, i.e. a functions problem wearing a recursion costume."""

    student_note: str = ""
    """The same diagnosis, addressed to the student instead of to a reviewer.

    `label` is written for the event stream: third person, diagnostic, and it names the
    fault outright. That is the wrong register for the person who just failed. This ends
    in a question the student can answer from what they already know, because handing
    someone the fix teaches them that they needed handing the fix.

    Deterministic on purpose. The rule already knows exactly which misunderstanding
    fired, so asking a model to re-describe it would add latency and a failure mode to
    a sentence we can simply write correctly once.
    """

    stderr_patterns: tuple[str, ...] = ()
    stdout_patterns: tuple[str, ...] = ()
    code_patterns: tuple[str, ...] = ()
    outcomes: tuple[StudentOutcome, ...] = ()


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        key="missing_base_case",
        label="recursive function has no reachable base case, so it never terminates",
        prerequisite_hint="conditionals",
        student_note=(
            "Your recursive call looks right, but nothing ever stops it — the function calls "
            "itself all the way down. What is the smallest input where it should return "
            "immediately, without calling itself again?"
        ),
        stderr_patterns=(r"RecursionError", r"maximum recursion depth"),
    ),
    Pattern(
        key="unreturned_recursive_call",
        label="recursive call is computed but not returned, so the function yields None",
        prerequisite_hint="functions",
        student_note=(
            "You are computing the recursive call but not returning it, so the function hands "
            "back None and the arithmetic fails. Look at the line that calls itself: what happens "
            "to the value it produces?"
        ),
        stderr_patterns=(
            r"unsupported operand type\(s\).*NoneType",
            r"TypeError.*NoneType.*int",
            r"'NoneType' object is not",
        ),
    ),
    Pattern(
        key="print_instead_of_return",
        label="uses print where a return value is required, so the caller receives None",
        prerequisite_hint="functions",
        student_note=(
            "Your function prints the answer instead of returning it, so the caller receives "
            "None. Printing shows a value to a human; returning gives it back to the code. Which "
            "one does the caller need here?"
        ),
        code_patterns=(r"def\s+\w+\([^)]*\):(?:(?!return).)*?print\(",),
        outcomes=(StudentOutcome.WRONG_ANSWER,),
    ),
    Pattern(
        key="infinite_loop",
        label="loop condition never becomes false, so execution does not terminate",
        prerequisite_hint="loops",
        student_note=(
            "Your loop never finishes, so the program was stopped for you. Look at the variable "
            "in the loop condition: is anything inside the loop actually changing it?"
        ),
        outcomes=(StudentOutcome.STUDENT_TIMEOUT,),
    ),
    Pattern(
        key="off_by_one_recursion",
        label="recursive step does not reduce the problem, so the base case is unreachable",
        prerequisite_hint="recursion",
        student_note=(
            "Each recursive call is being given the same problem rather than a smaller one, so "
            "the base case is never reached. Compare the argument you pass to the one you "
            "received: is it getting closer to the stopping point?"
        ),
        code_patterns=(r"def\s+(\w+)\([^)]*\):(?:(?!\1\s*\(\s*\w+\s*[-+]).)*?\1\s*\(\s*\w+\s*\)",),
    ),
    Pattern(
        key="name_error",
        label="uses a name that was never defined, or defined only inside another scope",
        prerequisite_hint="variables",
        student_note=(
            "You are using a name Python has not seen yet at that point — either it was never "
            "defined, or it was defined inside another function and is not visible here. Where is "
            "that name first assigned?"
        ),
        stderr_patterns=(r"NameError",),
    ),
    Pattern(
        key="indentation",
        label="block structure is wrong, so statements sit outside the body they belong to",
        prerequisite_hint=None,
        student_note=(
            "The indentation puts some statements outside the block you meant them to be in, so "
            "they run at the wrong time. Which lines are meant to belong to the body above them?"
        ),
        stderr_patterns=(r"IndentationError", r"TabError"),
    ),
)


def detect(
    *,
    code: str | None,
    stdout: str,
    stderr: str,
    outcome: StudentOutcome,
) -> Pattern | None:
    """Return the first pattern whose signature matches, or None.

    Order matters: stderr evidence is the most reliable, so those patterns are checked
    before anything inferred from the source text.
    """
    haystack_err = stderr or ""
    haystack_out = stdout or ""
    body = code or ""

    for pattern in PATTERNS:
        if pattern.stderr_patterns and any(
            re.search(p, haystack_err, re.IGNORECASE | re.DOTALL)
            for p in pattern.stderr_patterns
        ):
            return pattern

    for pattern in PATTERNS:
        if pattern.outcomes and outcome in pattern.outcomes:
            if not pattern.code_patterns:
                return pattern
            if any(re.search(p, body, re.DOTALL) for p in pattern.code_patterns):
                return pattern

    for pattern in PATTERNS:
        if pattern.stdout_patterns and any(
            re.search(p, haystack_out, re.IGNORECASE) for p in pattern.stdout_patterns
        ):
            return pattern

    return None
