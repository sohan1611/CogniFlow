"""Classifier tests for the disjoint evidence taxonomy."""

from __future__ import annotations

from app.models.enums import StudentOutcome, SystemFault, is_student_evidence
from app.models.execution import ExecutionResult, ExecutionStatus
from app.tools.sandbox.classifier import classify, classify_with_expectation


def _result(status: ExecutionStatus, started: bool) -> ExecutionResult:
    return ExecutionResult(
        status=status,
        started=started,
        timed_out=status == ExecutionStatus.TIMEOUT,
    )


def test_every_status_and_started_combination_maps_to_documented_side() -> None:
    for status in ExecutionStatus:
        for started in (False, True):
            outcome = classify(_result(status, started))
            if status == ExecutionStatus.BLOCKED:
                # Refused by static restriction before anything ran. A SystemFault, and
                # specifically NOT a student error: a learner who writes a correct
                # function and also imports `os` has demonstrated no misconception, and
                # their mastery must not move for a rule nobody told them about.
                assert outcome == SystemFault.EXECUTION_REFUSED
            elif status == ExecutionStatus.SANDBOX_ERROR or not started:
                assert isinstance(outcome, SystemFault)
            elif status == ExecutionStatus.TIMEOUT:
                assert outcome == StudentOutcome.STUDENT_TIMEOUT
            elif status == ExecutionStatus.SYNTAX_ERROR:
                assert outcome == StudentOutcome.STUDENT_SYNTAX_ERROR
            elif status == ExecutionStatus.RUNTIME_ERROR:
                assert outcome == StudentOutcome.STUDENT_RUNTIME_ERROR
            elif status == ExecutionStatus.NONZERO_EXIT:
                assert outcome == StudentOutcome.STUDENT_RUNTIME_ERROR
            else:
                assert outcome == StudentOutcome.WRONG_ANSWER


def test_not_started_always_yields_system_fault() -> None:
    for status in ExecutionStatus:
        outcome = classify(_result(status, started=False))

        assert isinstance(outcome, SystemFault)


def test_started_timeout_is_always_student_timeout() -> None:
    result = _result(ExecutionStatus.TIMEOUT, started=True)

    assert classify(result) == StudentOutcome.STUDENT_TIMEOUT


def test_classify_with_expectation_resolves_ok_results() -> None:
    result = _result(ExecutionStatus.OK, started=True)

    assert classify_with_expectation(result, passed=True) == StudentOutcome.CORRECT
    assert classify_with_expectation(result, passed=False) == StudentOutcome.WRONG_ANSWER


def test_every_classifier_result_is_exactly_one_taxonomy_side() -> None:
    for status in ExecutionStatus:
        for started in (False, True):
            outcome = classify(_result(status, started))
            student_side = is_student_evidence(outcome)
            system_side = isinstance(outcome, SystemFault)

            assert student_side != system_side


def test_a_refusal_is_never_student_evidence() -> None:
    """The safety property applied to the new status.

    Restrictions protect a public deployment. They must not cost a student mastery,
    because a refusal says nothing about what the student understands.
    """
    for started in (False, True):
        outcome = classify(_result(ExecutionStatus.BLOCKED, started))
        assert outcome == SystemFault.EXECUTION_REFUSED
        assert not is_student_evidence(outcome)


def test_every_execution_status_is_classified_on_exactly_one_side() -> None:
    """Adding a status without deciding which side it falls on is a design error."""
    for status in ExecutionStatus:
        for started in (False, True):
            outcome = classify(_result(status, started))
            student = is_student_evidence(outcome)
            fault = isinstance(outcome, SystemFault)
            assert student != fault, f"{status}/{started} is both or neither"
