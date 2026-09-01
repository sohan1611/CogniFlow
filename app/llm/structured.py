"""Structured LLM calls with repair, retry, failover, and replay caching.

Invariant: `call_structured` NEVER raises and NEVER returns unvalidated data. It returns
an LLMOutcome that either carries a schema-valid model instance or a SystemFault
explaining why it could not.

That contract is what lets the orchestration layer treat a provider outage as a routing
decision rather than a crash -- and, critically, it keeps every LLM failure on the
SystemFault side of the taxonomy, where it can never touch a student's mastery score.

Recovery order, most specific first:
  1. replay cache hit                -> return immediately
  2. schema violation (MALFORMED)    -> ONE repair attempt feeding the validation error
                                        back to the model, then move on
  3. transient error (RETRYABLE)     -> retry the same provider with backoff
  4. permanent error (PERMANENT)     -> abandon this provider immediately, fail over
  5. chain exhausted                 -> deterministic fallback if the caller supplied
                                        one, else LLM_FAILURE
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from pydantic import BaseModel, ValidationError

from app.llm.cache import ReplayCache, make_key
from app.llm.errors import LLMErrorKind, classify_exception, fault_for
from app.llm.provider import Role, StructuredCaller
from app.models.enums import SystemFault

logger = logging.getLogger(__name__)

MAX_RETRIES_PER_PROVIDER = 2
BACKOFF_BASE_SECONDS = 0.5


@dataclass
class LLMOutcome:
    """The result of a structured call. Success and failure are both first-class."""

    value: BaseModel | None = None
    fault: SystemFault | None = None
    provider_used: str | None = None
    attempts: int = 0
    repaired: bool = False
    from_cache: bool = False
    used_fallback: bool = False
    error_message: str | None = None
    providers_tried: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when a schema-valid value is available, however it was obtained."""
        return self.value is not None


def _repair_message(exc: ValidationError, schema: type[BaseModel]) -> dict[str, str]:
    """Build the corrective turn sent after a schema violation.

    We hand back the actual validation errors rather than a vague 'try again'. A model
    told exactly which field failed and why fixes it far more reliably.
    """
    detail = "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
        for err in exc.errors()[:8]
    )
    return {
        "role": "user",
        "content": (
            f"Your previous response did not satisfy the {schema.__name__} schema. "
            f"Validation errors: {detail}. "
            "Respond again with exactly the required fields and value types."
        ),
    }


class LLMClient:
    """Calls models for one role, with the full recovery chain."""

    def __init__(
        self,
        role: Role,
        callers: Sequence[StructuredCaller],
        *,
        cache: ReplayCache | None = None,
        max_retries: int = MAX_RETRIES_PER_PROVIDER,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.role = role
        self.callers = list(callers)
        self.cache = cache
        self.max_retries = max_retries
        self._sleep = sleep

    # -- cache -------------------------------------------------------------
    def _cache_key(
        self, caller: StructuredCaller, schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> str:
        provider, _, model = caller.name.partition(":")
        return make_key(
            provider=provider,
            model=model or caller.name,
            role=str(self.role),
            schema_name=schema.__name__,
            messages=messages,
        )

    def _cache_get(
        self, caller: StructuredCaller, schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> BaseModel | None:
        if self.cache is None:
            return None
        payload = self.cache.get(self._cache_key(caller, schema, messages))
        if payload is None:
            return None
        try:
            return schema.model_validate(payload.get("value", {}))
        except ValidationError:
            # A cached payload that no longer fits the schema (because the schema
            # changed) is a miss, not a failure.
            logger.info("cached payload no longer matches %s; ignoring", schema.__name__)
            return None

    # -- main entry point --------------------------------------------------
    def call_structured(
        self,
        schema: type[BaseModel],
        messages: list[dict[str, str]],
        *,
        fallback: BaseModel | None = None,
    ) -> LLMOutcome:
        """Run the full recovery chain. Never raises.

        `fallback` is a deterministic value used when every provider fails -- it keeps a
        tutoring session moving instead of ending it. The outcome records both the
        fault and used_fallback so the event log never pretends the model succeeded.
        """
        outcome = LLMOutcome()
        last_kind: LLMErrorKind | None = None

        if not self.callers:
            outcome.fault = SystemFault.LLM_FAILURE
            outcome.error_message = "no providers configured"
            return self._finish(outcome, schema, fallback)

        for caller in self.callers:
            outcome.providers_tried.append(caller.name)

            cached = self._cache_get(caller, schema, messages)
            if cached is not None:
                outcome.value = cached
                outcome.provider_used = caller.name
                outcome.from_cache = True
                return outcome

            turns = list(messages)
            repaired_here = False

            for attempt in range(self.max_retries + 1):
                outcome.attempts += 1
                try:
                    value = caller.call(schema, turns)
                except ValidationError as exc:
                    last_kind = LLMErrorKind.MALFORMED
                    outcome.error_message = f"schema violation: {exc.error_count()} error(s)"
                    if repaired_here:
                        logger.warning(
                            "%s produced invalid %s twice; failing over",
                            caller.name,
                            schema.__name__,
                        )
                        break
                    logger.info("repairing malformed %s from %s", schema.__name__, caller.name)
                    turns = [*turns, _repair_message(exc, schema)]
                    repaired_here = True
                    outcome.repaired = True
                    continue
                except Exception as exc:  # noqa: BLE001 - classified, never swallowed
                    last_kind = classify_exception(exc)
                    outcome.error_message = f"{type(exc).__name__}: {exc}"
                    if last_kind is LLMErrorKind.PERMANENT:
                        logger.warning(
                            "%s permanent failure (%s); failing over", caller.name, exc
                        )
                        break
                    if attempt < self.max_retries:
                        delay = BACKOFF_BASE_SECONDS * (2**attempt)
                        logger.info(
                            "%s transient failure (%s); retry %d in %.1fs",
                            caller.name,
                            exc,
                            attempt + 1,
                            delay,
                        )
                        self._sleep(delay)
                        continue
                    logger.warning("%s exhausted retries; failing over", caller.name)
                    break
                else:
                    outcome.value = value
                    outcome.provider_used = caller.name
                    if self.cache is not None:
                        self.cache.put(
                            self._cache_key(caller, schema, messages),
                            {"schema": schema.__name__, "value": value.model_dump(mode="json")},
                        )
                    return outcome

        outcome.fault = fault_for(last_kind) if last_kind else SystemFault.LLM_FAILURE
        return self._finish(outcome, schema, fallback)

    @staticmethod
    def _finish(
        outcome: LLMOutcome, schema: type[BaseModel], fallback: BaseModel | None
    ) -> LLMOutcome:
        """Apply the deterministic fallback, if one was offered."""
        if fallback is not None and isinstance(fallback, schema):
            outcome.value = fallback
            outcome.used_fallback = True
            logger.warning(
                "all providers failed for %s; using deterministic fallback", schema.__name__
            )
        return outcome
