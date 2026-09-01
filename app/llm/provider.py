"""LLM provider abstraction with an explicit failover chain.

Invariant: call sites name a ROLE, never a model. Which provider and model serve a role
is configuration, so quality and cost are tuned in one place and a provider outage is a
config-level concern rather than a code change.

Failover is not decoration. It is the "Robustness" characteristic the hackathon brief
asks for, and it is demonstrable live: kill the primary mid-run and the graph continues.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Role(StrEnum):
    """Why we are calling a model. The only thing a call site should have to know."""

    GENERATE = "generate"
    """Author a novel problem grounded in retrieved curriculum."""
    GRADE = "grade"
    """Score a free-text answer against a rubric."""
    ANALYZE = "analyze"
    """Name the specific misconception behind a wrong submission."""
    ADAPT = "adapt"
    """Propose the next adaptation action (the guard then validates it)."""


@dataclass(frozen=True)
class ProviderSpec:
    """One rung of a failover chain."""

    provider: str
    model: str
    max_tokens: int = 8000
    thinking: bool = False
    api_key_env: str = ""

    def available(self) -> bool:
        """True when this provider could actually be reached."""
        if self.provider == "offline":
            return True
        return bool(self.api_key_env and os.environ.get(self.api_key_env))


@runtime_checkable
class StructuredCaller(Protocol):
    """Turns messages plus a schema into a validated model instance.

    Deliberately NOT LangChain's Runnable: keeping our own narrow interface is what
    lets the entire LLM layer be tested offline with a programmable stub.

    Implementations raise on failure. Classification and recovery belong to
    app/llm/structured.py, not here.
    """

    name: str

    def call(
        self, schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> BaseModel: ...


# ---------------------------------------------------------------------------
# Default chains. Claude leads because it is already paid for (zero marginal cost)
# and is the strongest at structured output; the free tiers exist to absorb bulk
# evaluation runs and to keep the demo alive if the primary rate-limits.
# Model ids for the free tiers are env-overridable because provider catalogues drift.
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = os.environ.get("COGNIFLOW_ANTHROPIC_MODEL", "claude-opus-5")
GROQ_MODEL = os.environ.get("COGNIFLOW_GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.environ.get("COGNIFLOW_GEMINI_MODEL", "gemini-2.0-flash")


def default_chain(role: Role) -> list[ProviderSpec]:
    """Ordered providers to try for a role."""
    thinking = role in (Role.ANALYZE, Role.ADAPT)
    return [
        ProviderSpec(
            provider="anthropic",
            model=ANTHROPIC_MODEL,
            max_tokens=8000,
            thinking=thinking,
            api_key_env="ANTHROPIC_API_KEY",
        ),
        ProviderSpec(
            provider="groq",
            model=GROQ_MODEL,
            max_tokens=4000,
            api_key_env="GROQ_API_KEY",
        ),
        ProviderSpec(
            provider="google",
            model=GEMINI_MODEL,
            max_tokens=4000,
            api_key_env="GOOGLE_API_KEY",
        ),
    ]


@dataclass
class LangChainCaller:
    """Adapts a LangChain chat model to the StructuredCaller protocol."""

    spec: ProviderSpec
    _model: object | None = field(default=None, repr=False)

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"{self.spec.provider}:{self.spec.model}"

    def _build(self) -> object:
        """Construct the chat model lazily, so importing this module never needs keys."""
        if self._model is not None:
            return self._model

        provider = self.spec.provider
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs: dict[str, object] = {
                "model": self.spec.model,
                "max_tokens": self.spec.max_tokens,
            }
            # NOTE: temperature is deliberately NOT set. Current Claude models reject
            # sampling parameters with a 400, and LangChain omits the field when it is
            # None -- so the correct action is to leave it alone, not to set a value.
            if self.spec.thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            self._model = ChatAnthropic(**kwargs)  # type: ignore[arg-type]

        elif provider == "groq":
            from langchain_groq import ChatGroq

            self._model = ChatGroq(
                model=self.spec.model, max_tokens=self.spec.max_tokens
            )

        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._model = ChatGoogleGenerativeAI(
                model=self.spec.model, max_output_tokens=self.spec.max_tokens
            )
        else:
            raise ValueError(f"unknown provider {provider!r}")

        return self._model

    def call(
        self, schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> BaseModel:
        """Invoke the model with a schema. Raises on any failure, by design."""
        model = self._build()
        structured = model.with_structured_output(schema)  # type: ignore[attr-defined]
        lc_messages = [(m["role"], m["content"]) for m in messages]
        result = structured.invoke(lc_messages)
        if not isinstance(result, schema):
            # Belt and braces: never hand back something unvalidated.
            return schema.model_validate(result)
        return result


def build_caller(spec: ProviderSpec) -> StructuredCaller:
    """Create a caller for a provider spec."""
    if spec.provider == "offline":
        from app.llm.stub import StubCaller

        return StubCaller(name="offline")
    return LangChainCaller(spec=spec)


def available_chain(role: Role) -> list[ProviderSpec]:
    """The chain filtered to providers that actually have credentials present."""
    return [spec for spec in default_chain(role) if spec.available()]
