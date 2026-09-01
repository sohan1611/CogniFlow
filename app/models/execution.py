"""Execution result models for sandboxed student code.

Invariant: process startup is reported explicitly so infrastructure faults remain
disjoint from student evidence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ExecutionStatus(StrEnum):
    """Terminal status for one sandbox execution."""

    OK = "ok"
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    SYNTAX_ERROR = "syntax_error"
    RUNTIME_ERROR = "runtime_error"
    SANDBOX_ERROR = "sandbox_error"


class SandboxCapability(BaseModel):
    """Honest description of what isolation we actually have on this host."""

    backend: str
    process_isolation: bool
    network_isolation: bool
    memory_limit_mb: int | None
    cpu_limit_seconds: int | None
    notes: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Structured result for a single student-code execution."""

    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    runtime_ms: int = 0
    timed_out: bool = False
    started: bool
    error_message: str | None = None


class TestCaseResult(BaseModel):
    """Outcome for one expected-output test case."""

    name: str
    passed: bool
    expected: str
    actual: str
    execution: ExecutionResult


class TestSuiteResult(BaseModel):
    """Aggregate result for a deterministic test-suite run."""

    results: list[TestCaseResult]
    passed_count: int
    total_count: int
    all_passed: bool
    first_failure: TestCaseResult | None
