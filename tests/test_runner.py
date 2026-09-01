"""Runner tests for suite aggregation and fault-abort behavior."""

from __future__ import annotations

from app.models.enums import SystemFault, is_student_evidence
from app.models.execution import ExecutionResult, ExecutionStatus, SandboxCapability
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S
from app.tools.sandbox.classifier import classify
from app.tools.sandbox.faults import FaultInjectingSandbox, FaultInjector
from app.tools.sandbox.runner import run_test_cases


class QueueSandbox:
    """Deterministic sandbox test double."""

    def __init__(self, results: list[ExecutionResult]) -> None:
        self._results = list(results)

    def capability(self) -> SandboxCapability:
        return SandboxCapability(
            backend="queue",
            process_isolation=True,
            network_isolation=False,
            memory_limit_mb=None,
            cpu_limit_seconds=None,
        )

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        if not self._results:
            raise AssertionError("no queued execution result")
        return self._results.pop(0)


class QueueFaultAfterFirstRunSandbox:
    """Queues an infrastructure fault after the first delegated run."""

    def __init__(self, injector: FaultInjector) -> None:
        self._injector = injector
        self._calls = 0

    def capability(self) -> SandboxCapability:
        return SandboxCapability(
            backend="fault-after-first",
            process_isolation=True,
            network_isolation=False,
            memory_limit_mb=None,
            cpu_limit_seconds=None,
        )

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        self._calls += 1
        if self._calls == 1:
            self._injector.queue(SystemFault.SANDBOX_FAILURE)
        return _ok("first\n")


def _ok(stdout: str) -> ExecutionResult:
    return ExecutionResult(
        status=ExecutionStatus.OK,
        stdout=stdout,
        exit_code=0,
        started=True,
    )


def test_all_cases_pass() -> None:
    sandbox = QueueSandbox([_ok("2\n"), _ok("4\n")])
    suite = run_test_cases(
        sandbox,
        "unused",
        [
            {"name": "double one", "stdin": "1\n", "expected_output": "2"},
            {"name": "double two", "stdin": "2\n", "expected_output": "4"},
        ],
    )

    assert suite.all_passed is True
    assert suite.passed_count == 2
    assert suite.total_count == 2
    assert suite.first_failure is None


def test_one_case_fails_and_first_failure_is_identified() -> None:
    sandbox = QueueSandbox([_ok("2\n"), _ok("wrong\n"), _ok("6\n")])
    suite = run_test_cases(
        sandbox,
        "unused",
        [
            {"name": "case one", "stdin": "1\n", "expected_output": "2"},
            {"name": "case two", "stdin": "2\n", "expected_output": "4"},
            {"name": "case three", "stdin": "3\n", "expected_output": "6"},
        ],
    )

    assert suite.all_passed is False
    assert suite.passed_count == 2
    assert suite.total_count == 3
    assert suite.first_failure is not None
    assert suite.first_failure.name == "case two"


def test_injected_fault_mid_suite_aborts_without_student_failure() -> None:
    injector = FaultInjector()
    sandbox = FaultInjectingSandbox(QueueFaultAfterFirstRunSandbox(injector), injector)
    suite = run_test_cases(
        sandbox,
        "unused",
        [
            {"name": "case one", "stdin": "", "expected_output": "first"},
            {"name": "case two", "stdin": "", "expected_output": "second"},
            {"name": "case three", "stdin": "", "expected_output": "third"},
        ],
    )

    assert suite.all_passed is False
    assert suite.passed_count == 1
    assert suite.total_count == 2
    assert suite.first_failure is not None
    assert suite.first_failure.name == "case two"

    outcome = classify(suite.first_failure.execution)
    assert outcome == SystemFault.SANDBOX_FAILURE
    assert is_student_evidence(outcome) is False
