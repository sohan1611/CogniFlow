"""Programmable offline caller.

Invariant: this module never touches a network. It exists so the entire LLM layer --
retry, repair, failover, caching, fault classification -- is provable without an API
key and without spend.

An adaptation policy whose failure handling can only be verified by paying a provider
is not really verified, so the stub is a first-class part of the design rather than a
test fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


class ScriptedFailure(Exception):
    """Raised by the stub on demand, to drive the recovery paths."""


@dataclass
class StubCaller:
    """A caller whose responses are scripted in advance.

    Each queued item is either:
      * a BaseModel        -> returned as-is
      * a dict             -> validated against the requested schema (so a dict that
                              does NOT satisfy the schema exercises the repair path)
      * an Exception       -> raised
      * a callable         -> invoked with (schema, messages) and its result used
    Once the queue empties, `default` is used; if there is no default, the last item
    repeats. That keeps tests short without making behaviour surprising.
    """

    name: str = "stub"
    responses: list[Any] = field(default_factory=list)
    default: Any = None
    calls: list[tuple[type[BaseModel], list[dict[str, str]]]] = field(
        default_factory=list
    )

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def queue(self, item: Any) -> "StubCaller":
        """Add a scripted response. Chainable."""
        self.responses.append(item)
        return self

    def call(
        self, schema: type[BaseModel], messages: list[dict[str, str]]
    ) -> BaseModel:
        self.calls.append((schema, messages))

        if self.responses:
            item = self.responses.pop(0)
        elif self.default is not None:
            item = self.default
        else:
            raise ScriptedFailure("stub exhausted: no scripted response remaining")

        if isinstance(item, Callable) and not isinstance(item, type):  # type: ignore[arg-type]
            item = item(schema, messages)

        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseModel):
            return item
        if isinstance(item, dict):
            # Deliberately allowed to raise ValidationError -- that is how a test
            # simulates a model returning well-formed JSON that violates the schema.
            return schema.model_validate(item)

        raise ScriptedFailure(f"stub cannot handle scripted item of type {type(item)!r}")


def always(value: Any) -> StubCaller:
    """A stub that returns the same thing forever."""
    return StubCaller(default=value)


def raises(exc: BaseException) -> StubCaller:
    """A stub that always fails with the given exception."""
    return StubCaller(default=exc)


__all__ = ["StubCaller", "ScriptedFailure", "always", "raises", "ValidationError"]
