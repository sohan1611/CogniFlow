"""Deterministic test-case runner for sandboxed student code.

Invariant: a SystemFault aborts the suite immediately so partial infrastructure
failure cannot be converted into student evidence.

Test cases arrive from a LANGUAGE MODEL and are therefore untrusted input. A model may
omit a field, name it differently, or emit a non-dict entry entirely. None of that may
crash the graph -- a malformed case is skipped or defaulted, never raised, because a
generation quirk must not end a student's session.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.models.enums import Language, SystemFault
from app.models.execution import ExecutionResult, ExecutionStatus, TestCaseResult, TestSuiteResult
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S, Sandbox
from app.tools.sandbox.classifier import classify_with_expectation
from app.tools.sandbox.languages import LanguageSpec, spec_for


def run_test_cases(
    sandbox: Sandbox,
    student_code: str,
    test_cases: list[dict[str, Any]],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    language: Language | LanguageSpec | str | None = None,
) -> TestSuiteResult:
    """Run each test case once and compare stripped stdout to expected output."""

    results: list[TestCaseResult] = []
    first_failure: TestCaseResult | None = None

    for index, raw_case in enumerate(test_cases, 1):
        if not isinstance(raw_case, dict):
            continue
        name = str(raw_case.get("name") or f"case_{index}")
        stdin = str(raw_case.get("stdin") or raw_case.get("input") or "")
        expected_raw = (
            raw_case.get("expected_output")
            if raw_case.get("expected_output") is not None
            else raw_case.get("expected", raw_case.get("output"))
        )
        if expected_raw is None or not str(expected_raw).strip():
            # A case with nothing to compare against is not a test. Models routinely
            # emit test_cases with EMPTY expectations alongside a perfectly good
            # top-level expected_output; treating those as real makes every submission
            # fail against "". Skipping is correct -- inventing an expectation would
            # fabricate student evidence.
            continue
        expected = str(expected_raw).strip()
        execution = run_submission(
            sandbox,
            student_code,
            stdin=stdin,
            timeout_s=timeout_s,
            language=language,
        )
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


def run_submission(
    sandbox: Sandbox,
    student_code: str,
    stdin: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    language: Language | LanguageSpec | str | None = None,
) -> ExecutionResult:
    """Run one submission, passing a language only to sandboxes that accept it."""

    if language is None:
        return sandbox.run(student_code, stdin=stdin, timeout_s=timeout_s)

    if _accepts_language(sandbox.run):
        return sandbox.run(  # type: ignore[call-arg]
            student_code,
            stdin=stdin,
            timeout_s=timeout_s,
            language=language,
        )

    if _is_python(language):
        return sandbox.run(student_code, stdin=stdin, timeout_s=timeout_s)

    spec = spec_for(language)
    message = f"{spec.label} execution requires a language-aware sandbox"
    return ExecutionResult(
        status=ExecutionStatus.SANDBOX_ERROR,
        stderr=message,
        started=False,
        error_message=message,
    )


def _is_python(language: Language | LanguageSpec | str) -> bool:
    try:
        return spec_for(language).language == Language.PYTHON
    except ValueError:
        return False


def _accepts_language(run: Any) -> bool:
    try:
        parameters = inspect.signature(run).parameters
    except (TypeError, ValueError):
        return True
    return "language" in parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()
    )


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
