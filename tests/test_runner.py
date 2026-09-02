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


def test_empty_expectations_do_not_shadow_a_usable_one() -> None:
    """Regression: a live model emitted test_cases with EMPTY expectations.

    The model produced a perfectly good top-level `expected_output` AND a `test_cases`
    list whose entries carried stdin but no expectation. Those unusable cases were being
    honoured, so every submission was compared against "" and failed -- which made the
    headline demo fail 2 runs in 5 against a real provider.

    Unusable cases must be skipped, never allowed to decide pass/fail.
    """
    from app.tools.sandbox.runner import run_test_cases
    from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

    sandbox = SubprocessSandbox()
    shadowing = [
        {"name": "a", "stdin": "", "expected_output": ""},
        {"name": "b", "stdin": "", "expected_output": "   "},
        {"name": "c", "stdin": ""},
    ]
    suite = run_test_cases(sandbox, "print(15)", shadowing)
    assert suite.total_count == 0, "cases with no expectation must not be scored"


def test_a_correct_submission_passes_when_only_expected_output_is_usable() -> None:
    """The end-to-end shape of the same bug, through the grading node."""
    from app.graph.deps import GraphDeps
    from app.graph.nodes import make_execute_and_grade
    from app.services.events import EventLog
    from app.services.student_store import StudentStore

    deps = GraphDeps.offline(StudentStore(":memory:"), EventLog())
    node = make_execute_and_grade(deps)

    state = {
        "target_skill": "functions",
        "student_code": "print(15)",
        "current_problem": {
            "expected_output": "15",
            # the shape a real model produced: stdin present, expectation absent
            "test_cases": [{"name": "t1", "stdin": ""}, {"name": "t2", "stdin": ""}],
        },
    }
    patch = node(state)  # type: ignore[arg-type]
    assert patch["grader_result"]["passed"] is True, (
        "unusable test cases shadowed the usable expected_output"
    )
