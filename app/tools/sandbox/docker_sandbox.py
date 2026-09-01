"""Optional Docker sandbox backend for stronger isolation.

Invariant: if the containerized Python process does not start, the result is a
sandbox failure rather than student evidence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.models.execution import ExecutionResult, ExecutionStatus, SandboxCapability
from app.tools.sandbox.base import DEFAULT_TIMEOUT_S
from app.tools.sandbox.subprocess_sandbox import (
    _decode_output,
    _runtime_ms,
    _status_from_completed,
    _truncate_streams,
)


_STARTED_SENTINEL = "__COGNIFLOW_STUDENT_PROCESS_STARTED__"


class DockerSandbox:
    """Run student code in Docker when the local Docker CLI is available."""

    def __init__(self, image: str = "python:3.12-slim") -> None:
        self._image = image

    @staticmethod
    def is_available() -> bool:
        """Return whether the Docker CLI and daemon respond."""

        if shutil.which("docker") is None:
            return False
        try:
            completed = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def capability(self) -> SandboxCapability:
        """Report Docker isolation capabilities."""

        return SandboxCapability(
            backend="docker",
            process_isolation=True,
            network_isolation=True,
            memory_limit_mb=256,
            cpu_limit_seconds=1,
            notes=["docker backend uses --network=none, --memory=256m, --cpus=1"],
        )

    def run(
        self,
        code: str,
        stdin: str = "",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ExecutionResult:
        """Execute code in a read-only, network-disabled Docker container."""

        started_at = time.perf_counter()
        if not self.is_available():
            return _docker_sandbox_error(
                started_at,
                "Docker is unavailable; falling back is handled by settings factory",
                timed_out=False,
            )

        temp_dir: str | None = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="cogniflow-docker-")
            code_path = Path(temp_dir) / "student_code.py"
            code_path.write_text(code, encoding="utf-8")
            completed = subprocess.run(
                self._docker_args(temp_dir),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_minimal_docker_cli_env(),
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
            runtime_ms = _runtime_ms(started_at)
            stderr_without_sentinel, started = _remove_started_sentinel(completed.stderr)
            stdout, stderr = _truncate_streams(completed.stdout, stderr_without_sentinel)
            if not started:
                message = stderr.strip() or "Docker container did not start student Python process"
                return ExecutionResult(
                    status=ExecutionStatus.SANDBOX_ERROR,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=completed.returncode,
                    runtime_ms=runtime_ms,
                    timed_out=False,
                    started=False,
                    error_message=message,
                )

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
            raw_stderr = _decode_output(exc.stderr)
            stderr_without_sentinel, started = _remove_started_sentinel(raw_stderr)
            stdout, stderr = _truncate_streams(_decode_output(exc.output), stderr_without_sentinel)
            if started:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=None,
                    runtime_ms=runtime_ms,
                    timed_out=True,
                    started=True,
                )
            return ExecutionResult(
                status=ExecutionStatus.SANDBOX_ERROR,
                stdout=stdout,
                stderr=stderr,
                exit_code=None,
                runtime_ms=runtime_ms,
                timed_out=True,
                started=False,
                error_message="Docker timed out before student Python process started",
            )
        except OSError as exc:
            return _docker_sandbox_error(started_at, str(exc) or exc.__class__.__name__, timed_out=False)
        except subprocess.SubprocessError as exc:
            return _docker_sandbox_error(started_at, str(exc) or exc.__class__.__name__, timed_out=False)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _docker_args(self, temp_dir: str) -> list[str]:
        wrapper = (
            "import runpy, sys; "
            f"print('{_STARTED_SENTINEL}', file=sys.stderr, flush=True); "
            "runpy.run_path('/sandbox/student_code.py', run_name='__main__')"
        )
        return [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=16m",
            "-i",
            "-v",
            f"{temp_dir}:/sandbox:ro",
            "-w",
            "/sandbox",
            self._image,
            "python",
            "-I",
            "-B",
            "-c",
            wrapper,
        ]


def _minimal_docker_cli_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in (
        "COMSPEC",
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "HOME",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SystemRoot",
        "USERPROFILE",
        "WINDIR",
    ):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


def _remove_started_sentinel(stderr: str | None) -> tuple[str, bool]:
    if not stderr:
        return "", False

    lines = stderr.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() == _STARTED_SENTINEL:
            del lines[index]
            return "".join(lines), True
    return stderr, False


def _docker_sandbox_error(started_at: float, message: str, timed_out: bool) -> ExecutionResult:
    return ExecutionResult(
        status=ExecutionStatus.SANDBOX_ERROR,
        stderr=message,
        exit_code=None,
        runtime_ms=_runtime_ms(started_at),
        timed_out=timed_out,
        started=False,
        error_message=message,
    )
