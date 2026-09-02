"""Deterministic execution-result taxonomy.

Invariant: every result maps to exactly one side of the disjoint taxonomy:
StudentOutcome for mastery evidence or SystemFault for infrastructure failure.
"""

from __future__ import annotations

from app.models.enums import StudentOutcome, SystemFault
from app.models.execution import ExecutionResult, ExecutionStatus


def classify(result: ExecutionResult) -> StudentOutcome | SystemFault:
    """Map an ExecutionResult onto exactly one disjoint taxonomy branch."""

    # A refusal is checked FIRST and before `started`, because blocked code never runs
    # and therefore never starts -- without this it would be misreported as a sandbox
    # failure, which is a different and misleading claim.
    if result.status == ExecutionStatus.BLOCKED:
        return SystemFault.EXECUTION_REFUSED
    if result.status == ExecutionStatus.SANDBOX_ERROR:
        return SystemFault.SANDBOX_FAILURE
    if not result.started:
        return SystemFault.SANDBOX_FAILURE
    if result.status == ExecutionStatus.TIMEOUT:
        return StudentOutcome.STUDENT_TIMEOUT
    if result.status == ExecutionStatus.SYNTAX_ERROR:
        return StudentOutcome.STUDENT_SYNTAX_ERROR
    if result.status == ExecutionStatus.RUNTIME_ERROR:
        return StudentOutcome.STUDENT_RUNTIME_ERROR
    if result.status == ExecutionStatus.NONZERO_EXIT:
        return StudentOutcome.STUDENT_RUNTIME_ERROR
    return StudentOutcome.WRONG_ANSWER


def classify_with_expectation(
    result: ExecutionResult,
    passed: bool,
) -> StudentOutcome | SystemFault:
    """Resolve OK executions into CORRECT or WRONG_ANSWER using test comparison."""

    if result.status != ExecutionStatus.OK:
        return classify(result)
    if not result.started:
        return SystemFault.SANDBOX_FAILURE
    if passed:
        return StudentOutcome.CORRECT
    return StudentOutcome.WRONG_ANSWER
