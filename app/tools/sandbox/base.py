"""Shared sandbox protocol and limits.

Invariant: sandbox implementations must never hide whether student code actually
started, because that field separates student evidence from infrastructure faults.
"""

from __future__ import annotations

from typing import Protocol

from app.models.execution import ExecutionResult, SandboxCapability


DEFAULT_TIMEOUT_S: float = 5.0
MAX_OUTPUT_CHARS: int = 10_000


class Sandbox(Protocol):
    """Execution backend protocol for untrusted student code."""

    def capability(self) -> SandboxCapability:
        """Describe the actual isolation guarantees available on this host."""

        ...

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        """Execute code once and return a structured result."""

        ...
