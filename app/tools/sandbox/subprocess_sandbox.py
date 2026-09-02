"""Cross-platform subprocess sandbox for student code.

Invariant: a spawned child is student evidence only when its execution status says
so; failures to create the process are reported as sandbox errors with started=False.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from app.models.execution import ExecutionResult, ExecutionStatus, SandboxCapability
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S, MAX_OUTPUT_CHARS


class SubprocessSandbox:
    """Run student code in a separate Python process."""

    def __init__(
        self,
        memory_limit_mb: int = 256,
        cpu_limit_seconds: int = 5,
        process_limit: int = 64,
        restrict: bool | None = None,
    ) -> None:
        """`restrict` refuses filesystem, network, process and introspection access
        BEFORE running the code.

        ON by default. A Python-fundamentals exercise never needs any of those, and
        defaulting to permissive would mean a publicly deployed CogniFlow is an open
        proxy with a text box. Set COGNIFLOW_RESTRICT_CODE=0 for local development
        against code you already trust.
        """
        self._memory_limit_mb = memory_limit_mb
        self._cpu_limit_seconds = cpu_limit_seconds
        self._process_limit = process_limit
        if restrict is None:
            restrict = os.environ.get("COGNIFLOW_RESTRICT_CODE", "1").strip() not in {
                "0", "false", "False", "no",
            }
        self.restrict = restrict

    def capability(self) -> SandboxCapability:
        """Report subprocess isolation capabilities for the current platform."""

        notes = ["network isolation unavailable on subprocess backend"]
        if os.name == "posix":
            return SandboxCapability(
                backend="subprocess",
                process_isolation=True,
                network_isolation=False,
                memory_limit_mb=self._memory_limit_mb,
                cpu_limit_seconds=self._cpu_limit_seconds,
                notes=notes,
            )

        notes.extend(
            [
                "memory limit unavailable on Windows subprocess backend",
                "cpu limit unavailable on Windows subprocess backend; wall timeout is enforced",
            ]
        )
        return SandboxCapability(
            backend="subprocess",
            process_isolation=True,
            network_isolation=False,
            memory_limit_mb=None,
            cpu_limit_seconds=None,
            notes=notes,
        )

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        """Execute code in a per-run temp directory using the current interpreter."""
        if self.restrict:
            from app.tools.sandbox.restrictions import check

            restriction = check(code)
            if restriction is not None:
                # Refused BEFORE execution, so nothing the code might do at runtime can
                # matter. started=False because no process was ever created.
                return ExecutionResult(
                    status=ExecutionStatus.BLOCKED,
                    started=False,
                    stderr=restriction.message(),
                    error_message=f"{restriction.rule}: {restriction.detail}",
                )


        started_at = time.perf_counter()
        temp_dir: str | None = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="cogniflow-subprocess-")
            code_path = Path(temp_dir) / "student_code.py"
            code_path.write_text(code, encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-I", "-B", str(code_path)],
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=temp_dir,
                env=_minimal_child_env(temp_dir),
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
                preexec_fn=self._posix_preexec_fn(),
            )
            runtime_ms = _runtime_ms(started_at)
            stdout, stderr = _truncate_streams(completed.stdout, completed.stderr)
            return ExecutionResult(
                status=_status_from_completed(completed.returncode, stderr),
                stdout=stdout,
                stderr=stderr,
                exit_code=completed.returncode,
                runtime_ms=runtime_ms,
                timed_out=False,
                started=True,
            )
        except subprocess.TimeoutExpired as exc:
            runtime_ms = _runtime_ms(started_at)
            stdout, stderr = _truncate_streams(
                _decode_output(exc.output),
                _decode_output(exc.stderr),
            )
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                stdout=stdout,
                stderr=stderr,
                exit_code=None,
                runtime_ms=runtime_ms,
                timed_out=True,
                started=True,
            )
        except OSError as exc:
            return _sandbox_error(started_at, exc)
        except subprocess.SubprocessError as exc:
            return _sandbox_error(started_at, exc)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _posix_preexec_fn(self) -> Callable[[], None] | None:
        if os.name != "posix":
            return None

        memory_bytes = self._memory_limit_mb * 1024 * 1024
        cpu_seconds = max(1, math.ceil(self._cpu_limit_seconds))
        process_limit = self._process_limit

        def apply_limits() -> None:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (process_limit, process_limit))

        return apply_limits


def _minimal_child_env(temp_dir: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if os.name == "nt":
        for key in (
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SYSTEMDRIVE",
            "SYSTEMROOT",
            "SystemDrive",
            "SystemRoot",
            "WINDIR",
        ):
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["TEMP"] = temp_dir
        env["TMP"] = temp_dir
    else:
        for key in ("LANG", "LC_ALL", "PATH"):
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["HOME"] = temp_dir
        env["TMPDIR"] = temp_dir

    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _runtime_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _decode_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _truncate_streams(stdout: str | None, stderr: str | None) -> tuple[str, str]:
    safe_stdout = stdout or ""
    safe_stderr = stderr or ""
    notes: list[str] = []

    if len(safe_stdout) > MAX_OUTPUT_CHARS:
        safe_stdout = safe_stdout[:MAX_OUTPUT_CHARS]
        notes.append(f"stdout truncated to {MAX_OUTPUT_CHARS} chars")

    if len(safe_stderr) > MAX_OUTPUT_CHARS:
        safe_stderr = safe_stderr[:MAX_OUTPUT_CHARS]
        notes.append(f"stderr truncated to {MAX_OUTPUT_CHARS} chars")

    if notes:
        note_text = "\n" + "\n".join(f"[cogniflow sandbox] {note}" for note in notes)
        keep_chars = max(0, MAX_OUTPUT_CHARS - len(note_text))
        safe_stderr = safe_stderr[:keep_chars] + note_text

    return safe_stdout, safe_stderr


def _status_from_completed(exit_code: int, stderr: str) -> ExecutionStatus:
    if exit_code == 0:
        return ExecutionStatus.OK
    if _looks_like_syntax_error(stderr):
        return ExecutionStatus.SYNTAX_ERROR
    if "Traceback (most recent call last):" in stderr:
        return ExecutionStatus.RUNTIME_ERROR
    return ExecutionStatus.NONZERO_EXIT


def _looks_like_syntax_error(stderr: str) -> bool:
    markers = ("SyntaxError:", "IndentationError:", "TabError:")
    return any(marker in stderr for marker in markers)


def _sandbox_error(started_at: float, exc: BaseException) -> ExecutionResult:
    message = str(exc) or exc.__class__.__name__
    return ExecutionResult(
        status=ExecutionStatus.SANDBOX_ERROR,
        stderr=message,
        exit_code=None,
        runtime_ms=_runtime_ms(started_at),
        timed_out=False,
        started=False,
        error_message=message,
    )
