"""Project exception hierarchy for deterministic domain failures.

Invariant: domain errors carry no secrets and do not perform recovery side effects.
"""


class CogniFlowError(Exception):
    """Base class for CogniFlow domain errors."""


class InvalidEvidenceError(CogniFlowError):
    """Raised when non-student evidence reaches mastery update."""


class SkillGraphError(CogniFlowError):
    """Raised for cyclic skill graphs or unknown skill references."""


class LimitExceededError(CogniFlowError):
    """Raised when deterministic session limits are exceeded."""
