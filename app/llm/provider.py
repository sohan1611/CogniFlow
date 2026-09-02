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

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env into the process environment BEFORE the module-level os.environ reads
# below. Without this, a key sitting in .env is invisible to ProviderSpec.available()
# and every provider silently reports "no credentials" -- which looks exactly like a
# missing key and wastes a long time to diagnose.
load_dotenv()

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
# Model ids are env-overridable because provider catalogues drift.
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = os.environ.get("COGNIFLOW_ANTHROPIC_MODEL", "claude-sonnet-5")
"""Default Anthropic model. Sonnet rather than Opus by deliberate default.

Anthropic credit is finite and metered. Problem generation and misconception analysis
are well within Sonnet's range, and the ADAPT role's output is constrained by the
deterministic guard regardless of which model proposes it -- so paying Opus rates for a
decision the guard may overrule is poor value. Override per role below, or globally
with COGNIFLOW_ANTHROPIC_MODEL.
"""

ROLE_MODELS: dict[str, str] = {
    role: os.environ[key]
    for role, key in (
        ("generate", "COGNIFLOW_MODEL_GENERATE"),
        ("grade", "COGNIFLOW_MODEL_GRADE"),
        ("analyze", "COGNIFLOW_MODEL_ANALYZE"),
        ("adapt", "COGNIFLOW_MODEL_ADAPT"),
    )
    if key in os.environ
}
"""Per-role Anthropic model overrides.

Spend is not uniform across roles. Generation is the one a judge actually reads;
adaptation is guarded and cheap to get slightly wrong. Setting
COGNIFLOW_MODEL_ADAPT=claude-haiku-4-5 while leaving generation on Sonnet is a
sensible way to stretch a fixed credit.
"""
GROQ_MODEL = os.environ.get("COGNIFLOW_GROQ_MODEL", "openai/gpt-oss-120b")
# gemini-2.0-flash was retired by Google and now returns 404, so the previous default
# would have failed over silently on any fresh clone. Verified by calling this one
# through with_structured_output, which is the path that actually has to work --
# gemini-2.5-flash is listed by the models endpoint but 404s the same way.
GEMINI_MODEL = os.environ.get("COGNIFLOW_GEMINI_MODEL", "gemini-3.8-flash")


PROVIDER_ORDER = [
    p.strip()
    for p in os.environ.get("COGNIFLOW_PROVIDER_ORDER", "groq,google,anthropic").split(",")
    if p.strip()
]
"""Chain order, free tiers FIRST by default.

Groq and Google both offer genuinely free API tiers that are ample for this project.
Anthropic's API is metered pay-per-token and is billed SEPARATELY from a Claude
Pro/Max subscription -- a subscription grants no API access. Leading with Anthropic
would therefore have quietly turned a zero-cost project into a paid one.

Set COGNIFLOW_PROVIDER_ORDER=anthropic,groq,google to promote Anthropic if you do hold
API credits and want its stronger structured-output behaviour.
"""


def _spec(provider: str, role: Role) -> ProviderSpec:
    thinking = role in (Role.ANALYZE, Role.ADAPT)
    if provider == "anthropic":
        return ProviderSpec(
            provider="anthropic",
            model=ROLE_MODELS.get(str(role), ANTHROPIC_MODEL),
            max_tokens=8000,
            thinking=thinking,
            api_key_env="ANTHROPIC_API_KEY",
        )
    if provider == "groq":
        return ProviderSpec(
            provider="groq", model=GROQ_MODEL, max_tokens=4000, api_key_env="GROQ_API_KEY"
        )
    if provider == "google":
        return ProviderSpec(
            provider="google",
            model=GEMINI_MODEL,
            max_tokens=4000,
            api_key_env="GOOGLE_API_KEY",
        )
    raise ValueError(f"unknown provider {provider!r}")


def default_chain(role: Role) -> list[ProviderSpec]:
    """Ordered providers to try for a role. Free tiers lead by default."""
    return [_spec(p, role) for p in PROVIDER_ORDER]


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
