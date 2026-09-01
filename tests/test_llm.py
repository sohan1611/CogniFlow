"""Phase 4 tests: provider abstraction, structured outputs, recovery, replay cache.

Covers plan requirements 10 (LLM failure) and 11 (malformed structured output).

Every test here runs OFFLINE against a programmable stub. That is deliberate: recovery
logic that can only be exercised by paying a provider is not really verified, and it
could not be run in CI or on a plane the night before a demo.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.llm.cache import ReplayCache, make_key
from app.llm.errors import LLMErrorKind, classify_exception, fault_for
from app.llm.provider import ProviderSpec, Role, available_chain, default_chain
from app.llm.stub import ScriptedFailure, StubCaller
from app.llm.structured import LLMClient
from app.models.enums import SystemFault


class Answer(BaseModel):
    """Small schema used throughout these tests."""

    verdict: str
    score: float = Field(ge=0.0, le=1.0)


GOOD = Answer(verdict="correct", score=0.9)
MESSAGES = [{"role": "user", "content": "grade this"}]


def _client(*callers, cache=None, **kw) -> LLMClient:
    """LLMClient with sleep stubbed out so retry tests stay instant."""
    return LLMClient(Role.GRADE, callers, cache=cache, sleep=lambda _s: None, **kw)


# ---------------------------------------------------------------- happy path
def test_successful_call_returns_validated_value() -> None:
    stub = StubCaller(name="a", default=GOOD)
    out = _client(stub).call_structured(Answer, MESSAGES)
    assert out.ok and isinstance(out.value, Answer)
    assert out.value.verdict == "correct"
    assert out.provider_used == "a"
    assert out.fault is None
    assert out.attempts == 1


def test_dict_response_is_validated_not_trusted() -> None:
    stub = StubCaller(name="a", default={"verdict": "ok", "score": 0.5})
    out = _client(stub).call_structured(Answer, MESSAGES)
    assert isinstance(out.value, Answer)


# ------------------------------------------------------ TEST 11: malformed
def test_11_malformed_output_is_repaired_and_succeeds() -> None:
    """A schema violation triggers exactly one repair turn, then succeeds."""
    stub = StubCaller(name="a")
    stub.queue({"verdict": "ok", "score": 4.2})  # score > 1.0 -> ValidationError
    stub.queue(GOOD)

    out = _client(stub).call_structured(Answer, MESSAGES)

    assert out.ok
    assert out.repaired is True
    assert out.attempts == 2
    # the repair turn must actually carry the validation detail back to the model
    _, repaired_messages = stub.calls[1]
    assert len(repaired_messages) == len(MESSAGES) + 1
    assert "did not satisfy" in repaired_messages[-1]["content"]
    assert "score" in repaired_messages[-1]["content"]


def test_11_repair_is_attempted_only_once_then_fails_over() -> None:
    """Two schema violations from one provider must not loop; move to the next."""
    bad = StubCaller(name="bad", default={"verdict": "x", "score": 9.9})
    good = StubCaller(name="good", default=GOOD)

    out = _client(bad, good).call_structured(Answer, MESSAGES)

    assert out.ok
    assert out.provider_used == "good"
    assert bad.call_count == 2, "should try once, repair once, then give up"
    assert out.providers_tried == ["bad", "good"]


def test_11_malformed_everywhere_reports_malformed_fault() -> None:
    bad = StubCaller(name="bad", default={"verdict": "x", "score": 9.9})
    out = _client(bad).call_structured(Answer, MESSAGES)
    assert not out.ok
    assert out.fault is SystemFault.MALFORMED_MODEL_OUTPUT


# --------------------------------------------------- TEST 10: LLM failure
class _RateLimit(Exception):
    """Stands in for a provider rate-limit type (classified by class name)."""


_RateLimit.__name__ = "RateLimitError"


def test_10_transient_failure_is_retried_then_succeeds() -> None:
    stub = StubCaller(name="a")
    stub.queue(_RateLimit("slow down"))
    stub.queue(_RateLimit("slow down"))
    stub.queue(GOOD)

    out = _client(stub).call_structured(Answer, MESSAGES)

    assert out.ok
    assert out.attempts == 3
    assert stub.call_count == 3


def test_10_all_providers_failing_yields_llm_failure_and_never_raises() -> None:
    a = StubCaller(name="a", default=_RateLimit("down"))
    b = StubCaller(name="b", default=_RateLimit("also down"))

    out = _client(a, b).call_structured(Answer, MESSAGES)

    assert out.ok is False
    assert out.value is None
    assert out.fault is SystemFault.LLM_FAILURE
    assert out.providers_tried == ["a", "b"]
    assert out.error_message


def test_10_failover_reaches_a_healthy_provider() -> None:
    dead = StubCaller(name="dead", default=_RateLimit("nope"))
    alive = StubCaller(name="alive", default=GOOD)

    out = _client(dead, alive).call_structured(Answer, MESSAGES)

    assert out.ok and out.provider_used == "alive"


class _AuthError(Exception):
    pass


_AuthError.__name__ = "AuthenticationError"


def test_permanent_error_is_not_retried() -> None:
    """A bad key will not fix itself; retrying it just burns the demo clock."""
    dead = StubCaller(name="dead", default=_AuthError("bad key"))
    alive = StubCaller(name="alive", default=GOOD)

    out = _client(dead, alive).call_structured(Answer, MESSAGES)

    assert out.ok
    assert dead.call_count == 1, "permanent errors must fail over immediately"


@pytest.mark.parametrize(
    "exc,expected",
    [
        (_RateLimit("x"), LLMErrorKind.RETRYABLE),
        (_AuthError("x"), LLMErrorKind.PERMANENT),
        (TimeoutError("x"), LLMErrorKind.RETRYABLE),
        (ValueError("totally unknown"), LLMErrorKind.RETRYABLE),
    ],
)
def test_exception_classification(exc: Exception, expected: LLMErrorKind) -> None:
    assert classify_exception(exc) is expected


def test_status_code_classification() -> None:
    class Weird(Exception):
        status_code = 503

    class Bad(Exception):
        status_code = 400

    assert classify_exception(Weird()) is LLMErrorKind.RETRYABLE
    assert classify_exception(Bad()) is LLMErrorKind.PERMANENT


def test_fault_mapping() -> None:
    assert fault_for(LLMErrorKind.MALFORMED) is SystemFault.MALFORMED_MODEL_OUTPUT
    assert fault_for(LLMErrorKind.RETRYABLE) is SystemFault.LLM_FAILURE
    assert fault_for(LLMErrorKind.PERMANENT) is SystemFault.LLM_FAILURE


def test_never_raises_for_arbitrary_exception_types() -> None:
    """The contract is absolute: no exception escapes call_structured."""
    for exc in (RuntimeError("x"), KeyError("k"), ScriptedFailure("s"), OSError("io")):
        out = _client(StubCaller(name="a", default=exc)).call_structured(Answer, MESSAGES)
        assert out.ok is False
        assert out.fault is not None


def test_no_providers_configured() -> None:
    out = _client().call_structured(Answer, MESSAGES)
    assert not out.ok
    assert out.fault is SystemFault.LLM_FAILURE
    assert "no providers" in (out.error_message or "")


# ------------------------------------------------------------- fallback
def test_deterministic_fallback_keeps_the_session_alive() -> None:
    dead = StubCaller(name="dead", default=_RateLimit("down"))
    spare = Answer(verdict="ungraded", score=0.0)

    out = _client(dead).call_structured(Answer, MESSAGES, fallback=spare)

    assert out.ok, "fallback should provide a usable value"
    assert out.used_fallback is True
    assert out.value == spare
    assert out.fault is SystemFault.LLM_FAILURE, "fault must still be recorded"


# ---------------------------------------------------------------- caching
def test_cache_round_trip_avoids_a_second_provider_call(tmp_path) -> None:
    cache = ReplayCache(tmp_path / "c")
    stub = StubCaller(name="a:m", default=GOOD)

    first = _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    assert first.from_cache is False
    assert stub.call_count == 1

    second = _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    assert second.from_cache is True
    assert second.value == GOOD
    assert stub.call_count == 1, "cache hit must not call the provider again"


def test_cache_key_changes_with_every_input() -> None:
    base = dict(
        provider="p", model="m", role="grade", schema_name="Answer",
        messages=[{"role": "user", "content": "a"}],
    )
    k = make_key(**base)
    assert k != make_key(**{**base, "provider": "q"})
    assert k != make_key(**{**base, "model": "n"})
    assert k != make_key(**{**base, "role": "generate"})
    assert k != make_key(**{**base, "schema_name": "Other"})
    assert k != make_key(**{**base, "messages": [{"role": "user", "content": "b"}]})
    assert k == make_key(**base), "key must be stable for identical input"


def test_cache_disabled_never_reads_or_writes(tmp_path) -> None:
    cache = ReplayCache(tmp_path / "c", enabled=False)
    stub = StubCaller(name="a", default=GOOD)
    _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    assert stub.call_count == 2
    assert cache.count() == 0


def test_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path) -> None:
    cache = ReplayCache(tmp_path / "c")
    key = "deadbeef"
    cache.directory.mkdir(parents=True, exist_ok=True)
    (cache.directory / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None


def test_cache_entry_that_no_longer_matches_schema_is_a_miss(tmp_path) -> None:
    """Schema evolution must not resurrect an incompatible cached answer."""
    cache = ReplayCache(tmp_path / "c")
    stub = StubCaller(name="a:m", default=GOOD)
    client = _client(stub, cache=cache)
    client.call_structured(Answer, MESSAGES)

    # corrupt the stored value so it violates the schema
    entry = next(cache.directory.glob("*.json"))
    payload = json.loads(entry.read_text(encoding="utf-8"))
    payload["value"]["score"] = 99.0
    entry.write_text(json.dumps(payload), encoding="utf-8")

    out = _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    assert out.from_cache is False, "invalid cached payload must not be served"
    assert out.ok


def test_cache_clear_and_count(tmp_path) -> None:
    cache = ReplayCache(tmp_path / "c")
    stub = StubCaller(name="a:m", default=GOOD)
    _client(stub, cache=cache).call_structured(Answer, MESSAGES)
    assert cache.count() == 1
    assert cache.clear() == 1
    assert cache.count() == 0


# ---------------------------------------------------------------- provider
def test_default_chain_leads_with_genuinely_free_tiers() -> None:
    """Cost is a correctness property here, not a preference.

    An Anthropic API key is metered pay-per-token and is billed SEPARATELY from a
    Claude Pro/Max subscription -- a subscription grants no API access. Leading the
    chain with it would quietly turn a zero-cost project into a paid one, so the free
    tiers go first and Anthropic is opt-in.
    """
    chain = default_chain(Role.GENERATE)
    assert [s.provider for s in chain] == ["groq", "google", "anthropic"]
    assert chain[0].provider != "anthropic", "the paid provider must not lead"
    assert all(s.api_key_env for s in chain)


def test_thinking_enabled_only_for_reasoning_roles() -> None:
    """Thinking is an Anthropic-specific setting, so check the Anthropic rung."""
    def anthropic_spec(role):
        return next(s for s in default_chain(role) if s.provider == "anthropic")

    assert anthropic_spec(Role.ANALYZE).thinking is True
    assert anthropic_spec(Role.ADAPT).thinking is True
    assert anthropic_spec(Role.GENERATE).thinking is False


def test_provider_order_is_configurable() -> None:
    """Teams holding API credits can promote the paid provider deliberately."""
    from app.llm.provider import _spec

    order = ["anthropic", "groq"]
    chain = [_spec(p, Role.GENERATE) for p in order]
    assert [s.provider for s in chain] == order


def test_availability_follows_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert available_chain(Role.GRADE) == []

    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert [s.provider for s in available_chain(Role.GRADE)] == ["groq"]


def test_offline_spec_is_always_available() -> None:
    assert ProviderSpec(provider="offline", model="none").available() is True


def test_building_a_caller_never_needs_credentials_at_import_time() -> None:
    """Constructing the caller must be lazy; only .call() should need a key."""
    from app.llm.provider import build_caller

    caller = build_caller(ProviderSpec(provider="anthropic", model="claude-opus-5"))
    assert caller.name == "anthropic:claude-opus-5"
