"""Sandbox backend tests for the student-vs-infrastructure invariant."""

from __future__ import annotations

import os

from app.models.enums import StudentOutcome, SystemFault
from app.models.execution import ExecutionStatus
from app.tools.sandbox.base import MAX_OUTPUT_CHARS
from app.tools.sandbox.classifier import classify, classify_with_expectation
from app.tools.sandbox.faults import FaultInjectingSandbox, FaultInjector
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox


def test_syntax_error_classifies_as_student_syntax_error() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run("def broken(:\n    pass\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.SYNTAX_ERROR
    assert result.started is True
    assert classify(result) == StudentOutcome.STUDENT_SYNTAX_ERROR


def test_runtime_error_classifies_as_student_runtime_error() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run("print(1 / 0)\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.RUNTIME_ERROR
    assert result.started is True
    assert classify(result) == StudentOutcome.STUDENT_RUNTIME_ERROR


def test_wrong_answer_uses_expectation_to_classify() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run("print('4')\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.OK
    assert classify_with_expectation(result, passed=False) == StudentOutcome.WRONG_ANSWER


def test_timeout_after_start_is_student_timeout() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run("while True:\n    pass\n", timeout_s=0.5)

    assert result.status == ExecutionStatus.TIMEOUT
    assert result.started is True
    assert result.timed_out is True
    assert classify(result) == StudentOutcome.STUDENT_TIMEOUT


def test_fault_injection_returns_sandbox_failure_without_starting() -> None:
    injector = FaultInjector()
    injector.queue(SystemFault.SANDBOX_FAILURE)
    sandbox = FaultInjectingSandbox(SubprocessSandbox(), injector)

    result = sandbox.run("print('would not run')\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.SANDBOX_ERROR
    assert result.started is False
    assert classify(result) == SystemFault.SANDBOX_FAILURE
    assert injector.pending == 0


def test_correct_code_classifies_as_correct_with_expectation() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run("print(input().strip().upper())\n", stdin="ok\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.OK
    assert result.stdout.strip() == "OK"
    assert classify_with_expectation(result, passed=True) == StudentOutcome.CORRECT


def test_stdout_is_truncated_and_noted_in_stderr() -> None:
    sandbox = SubprocessSandbox()
    result = sandbox.run(f"print('x' * {MAX_OUTPUT_CHARS + 1000})\n", timeout_s=1.0)

    assert result.status == ExecutionStatus.OK
    assert len(result.stdout) <= MAX_OUTPUT_CHARS
    assert "truncated" in result.stderr.lower()


def test_child_environment_does_not_inherit_parent_secrets(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-parent-secret")
    sandbox = SubprocessSandbox()
    result = sandbox.run(
        "import os\nprint(os.environ.get('ANTHROPIC_API_KEY'))\n",
        timeout_s=1.0,
    )

    assert result.status == ExecutionStatus.OK
    assert result.stdout.strip() == "None"


def test_subprocess_capability_is_honest_and_never_raises() -> None:
    capability = SubprocessSandbox().capability()

    assert capability.backend == "subprocess"
    assert capability.process_isolation is True
    assert capability.network_isolation is False
    if os.name == "nt":
        assert capability.memory_limit_mb is None
        assert capability.cpu_limit_seconds is None
        assert any("Windows subprocess backend" in note for note in capability.notes)
    else:
        assert capability.memory_limit_mb is not None
        assert capability.cpu_limit_seconds is not None
