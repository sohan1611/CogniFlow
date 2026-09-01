"""Deterministic sandbox fault injection.

Invariant: injected infrastructure faults return sandbox errors and never execute
student code.
"""

from __future__ import annotations

from app.models.enums import SystemFault
from app.models.execution import ExecutionResult, ExecutionStatus, SandboxCapability
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S, Sandbox


class FaultInjector:
    """Deterministic, explicit fault injection for demos and tests."""

    def __init__(self) -> None:
        self._queue: list[SystemFault] = []

    def queue(self, fault: SystemFault) -> None:
        self._queue.append(fault)

    def pop(self) -> SystemFault | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def clear(self) -> None:
        self._queue.clear()

    @property
    def pending(self) -> int:
        return len(self._queue)


class FaultInjectingSandbox:
    """Wrap a sandbox and return queued faults instead of running code."""

    def __init__(self, inner: Sandbox, injector: FaultInjector) -> None:
        self._inner = inner
        self._injector = injector

    def capability(self) -> SandboxCapability:
        return self._inner.capability()

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        fault = self._injector.pop()
        if fault is None:
            return self._inner.run(code, stdin=stdin, timeout_s=timeout_s)

        message = _fault_message(fault)
        return ExecutionResult(
            status=ExecutionStatus.SANDBOX_ERROR,
            stdout="",
            stderr=message,
            exit_code=None,
            runtime_ms=0,
            timed_out=False,
            started=False,
            error_message=message,
        )


def _fault_message(fault: SystemFault) -> str:
    value = getattr(fault, "value", None)
    if isinstance(value, str):
        return value
    return str(fault)
