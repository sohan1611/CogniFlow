"""Classification of LLM failures.

Invariant: every LLM failure is classified as retryable, permanent, or malformed
BEFORE any recovery decision is made. Recovery strategy is a function of the class,
never of a string match against an error message.

None of these failures may ever reach the mastery model: they are all SystemFault
territory (see app/models/enums.py). A provider outage is our problem, not the
student's.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import SystemFault


class LLMErrorKind(StrEnum):
    """How a failed LLM call should be recovered from."""

    RETRYABLE = "retryable"
    """Transient: rate limit, timeout, connection reset, 5xx, overloaded.
    Retry the same provider with backoff, then fail over."""

    PERMANENT = "permanent"
    """Will not succeed on retry: auth failure, bad request, unknown model.
    Skip straight to the next provider; retrying wastes the demo clock."""

    MALFORMED = "malformed"
    """The call succeeded but the payload did not validate against the schema.
    Repair once by feeding the validation error back, then fall back."""


# Exception type names treated as transient. Matched by class name so this module
# stays importable without every provider SDK installed -- the Groq and Gemini
# packages are optional at runtime.
_RETRYABLE_NAMES: frozenset[str] = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "DeadlineExceededError",
        "InternalServerError",
        "OverloadedError",
        "RateLimitError",
        "RetryableError",
        "ServiceUnavailableError",
        "ConflictError",
        "ConnectionError",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
        # LangChain's normalized hierarchy (langchain_core.exceptions). Provider
        # wrappers subclass these, so matching here covers every provider at once
        # rather than chasing each SDK's own spelling.
        "ModelRateLimitError",
        "ModelAPIError",
        "ModelConnectionError",
        "ModelTimeoutError",
    }
)

_PERMANENT_NAMES: frozenset[str] = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "BadRequestError",
        "UnprocessableEntityError",
        "RequestTooLargeError",
        "APIResponseValidationError",
        # Same normalized hierarchy. ModelNotFoundError is the one that bit us: a
        # retired model name carries no status_code, so it fell through to the
        # RETRYABLE default and burned three backoff retries per call before failing
        # over -- on every call, for the whole session. A dead model does not come
        # back within a demo, and the retry budget exists for blips, not epitaphs.
        "ModelNotFoundError",
        "ModelAuthenticationError",
        "ModelPermissionDeniedError",
        "ModelInvalidRequestError",
        "ContextOverflowError",
    }
)


def classify_exception(exc: BaseException) -> LLMErrorKind:
    """Map a provider exception onto a recovery class.

    Walks the exception's MRO so provider subclasses of a known base are caught.
    Unknown exceptions are treated as RETRYABLE: on a live demo a spurious retry is
    cheap, while giving up on a recoverable blip is not.
    """
    for klass in type(exc).__mro__:
        name = klass.__name__
        if name in _PERMANENT_NAMES:
            return LLMErrorKind.PERMANENT
        if name in _RETRYABLE_NAMES:
            return LLMErrorKind.RETRYABLE

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 429 or status >= 500:
            return LLMErrorKind.RETRYABLE
        if 400 <= status < 500:
            return LLMErrorKind.PERMANENT

    return LLMErrorKind.RETRYABLE


def fault_for(kind: LLMErrorKind) -> SystemFault:
    """Map a recovery class onto the SystemFault recorded in the event log."""
    if kind is LLMErrorKind.MALFORMED:
        return SystemFault.MALFORMED_MODEL_OUTPUT
    return SystemFault.LLM_FAILURE
