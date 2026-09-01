"""Docker sandbox tests that do not require Docker to be installed."""

from __future__ import annotations

import pytest

from app.models.execution import ExecutionStatus
from app.tools.sandbox.docker_sandbox import DockerSandbox


DOCKER_AVAILABLE = DockerSandbox.is_available()


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is unavailable")
def test_docker_capability_reports_hardening_when_available() -> None:
    capability = DockerSandbox().capability()

    assert capability.backend == "docker"
    assert capability.network_isolation is True
    assert capability.memory_limit_mb == 256


def test_unavailable_docker_returns_sandbox_error_started_false(monkeypatch) -> None:
    monkeypatch.setattr(DockerSandbox, "is_available", staticmethod(lambda: False))

    result = DockerSandbox().run("print('not run')\n", timeout_s=0.5)

    assert result.status == ExecutionStatus.SANDBOX_ERROR
    assert result.started is False
    assert result.error_message is not None
