"""CogniFlow settings and sandbox factory.

Invariant: configuration defaults contain no secrets, and sandbox selection never
pretends Docker hardening exists when Docker is unavailable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.tools.sandbox.base import Sandbox
from app.tools.sandbox.docker_sandbox import DockerSandbox
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Runtime settings sourced from COGNIFLOW_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="COGNIFLOW_",
        env_file=(".env.example", ".env"),
        extra="ignore",
    )

    db_path: Path = Path("data/cogniflow.db")
    # A PostgreSQL URL for the student store. Unprefixed DATABASE_URL is the name every
    # host and provider uses; set it and student progress lives there instead of in the
    # SQLite file at db_path, which a host with an ephemeral disk throws away.
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "COGNIFLOW_DATABASE_URL"),
    )
    # A public Neon Auth endpoint. Setting it makes account JWTs mandatory for every
    # student route; leaving it unset preserves local name-based identity.
    neon_auth_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "NEON_AUTH_BASE_URL", "COGNIFLOW_NEON_AUTH_BASE_URL"
        ),
    )
    checkpoint_path: Path = Path("data/checkpoints")
    chroma_path: Path = Path("data/chroma")
    sandbox: Literal["subprocess", "docker"] = "subprocess"
    replay_cache: bool = True
    primary_provider: str = "offline"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def get_sandbox() -> Sandbox:
    """Create the configured sandbox, falling back honestly when Docker is absent."""

    settings = get_settings()
    if settings.sandbox == "docker":
        docker_sandbox = DockerSandbox()
        if docker_sandbox.is_available():
            return docker_sandbox
        logger.warning("COGNIFLOW_SANDBOX=docker requested but Docker is unavailable; using subprocess")
    return SubprocessSandbox()
