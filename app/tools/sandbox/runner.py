"""Deterministic test-case runner for sandboxed student code.

Invariant: a SystemFault aborts the suite immediately so partial infrastructure
failure cannot be converted into student evidence.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import SystemFault
from app.models.execution import ExecutionStatus, TestCaseResult, TestSuiteResult
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S, Sandbox
from app.tools.sandbox.classifier import classify_with_expectation


def run_test_cases(
    sandbox: Sandbox,
    student_code: str,
    test_cases: list[dict[str, Any]],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> TestSuiteResult:
    """Run each test case once and compare stripped stdout to expected output."""

    results: list[TestCaseResult] = []
    first_failure: TestCaseResult | None = None

    for raw_case in test_cases:
        name = str(raw_case["name"])
        stdin = str(raw_case.get("stdin", ""))
        expected = str(raw_case["expected_output"]).strip()
        execution = sandbox.run(student_code, stdin=stdin, timeout_s=timeout_s)
        actual = execution.stdout.strip()
        passed = execution.status == ExecutionStatus.OK and actual == expected
        case_result = TestCaseResult(
            name=name,
            passed=passed,
            expected=expected,
            actual=actual,
            execution=execution,
        )
        results.append(case_result)

        classification = classify_with_expectation(execution, passed=passed)
        if isinstance(classification, SystemFault):
            return _suite_result(results, first_failure=case_result)
        if not passed and first_failure is None:
            first_failure = case_result

    return _suite_result(results, first_failure=first_failure)


def _suite_result(
    results: list[TestCaseResult],
    first_failure: TestCaseResult | None,
) -> TestSuiteResult:
    passed_count = sum(1 for result in results if result.passed)
    total_count = len(results)
    return TestSuiteResult(
        results=results,
        passed_count=passed_count,
        total_count=total_count,
        all_passed=total_count > 0 and passed_count == total_count and first_failure is None,
        first_failure=first_failure,
    )
