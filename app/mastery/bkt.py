"""Bayesian Knowledge Tracing for CogniFlow mastery.

Invariant: only StudentOutcome evidence can change a mastery score.
"""

from dataclasses import dataclass
import math

from app.models.enums import CORRECTNESS, StudentOutcome, is_student_evidence
from app.models.errors import InvalidEvidenceError
from app.models.schemas import SkillNode, SkillUpdate


@dataclass(frozen=True)
class BKTParams:
    """Classic Corbett and Anderson BKT parameters."""

    p_init: float = 0.25
    p_transit: float = 0.15
    p_slip: float = 0.10
    p_guess: float = 0.20

    def __post_init__(self) -> None:
        """Validate that BKT probabilities are identifiable."""

        for name in ("p_init", "p_transit", "p_slip", "p_guess"):
            value = getattr(self, name)
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must be strictly inside (0, 1)")
        if self.p_slip + self.p_guess >= 1.0:
            raise ValueError("p_slip + p_guess must be less than 1.0")


def posterior(p_known: float, correct: bool, prm: BKTParams) -> float:
    """Return P(known | observed response) before the learning transition."""

    if correct:
        num = p_known * (1 - prm.p_slip)
        den = num + (1 - p_known) * prm.p_guess
    else:
        num = p_known * prm.p_slip
        den = num + (1 - p_known) * (1 - prm.p_guess)
    if den <= 0:
        return p_known
    return num / den


def transition(p_post: float, prm: BKTParams) -> float:
    """Apply the BKT learning transition after an observation."""

    return p_post + (1 - p_post) * prm.p_transit


def update(p_known: float, outcome: StudentOutcome, prm: BKTParams) -> float:
    """THE ONLY entry point that changes mastery."""

    if not is_student_evidence(outcome):
        raise InvalidEvidenceError("system faults cannot update mastery")
    correct = CORRECTNESS[outcome]
    return transition(posterior(p_known, correct, prm), prm)


def confidence_from_attempts(attempts: int, k: float = 4.0) -> float:
    """Effective-sample-size confidence. 0 attempts -> 0.0, monotonically -> 1.0."""

    return 1.0 - math.exp(-attempts / k)


def update_skill(
    node: SkillNode,
    outcome: StudentOutcome,
    prm: BKTParams,
) -> tuple[SkillNode, SkillUpdate]:
    """Return an immutable SkillNode update plus its audit record."""

    mastery_after = update(node.mastery, outcome, prm)
    attempts_after = node.attempts + 1
    confidence_after = confidence_from_attempts(attempts_after)
    updated = SkillNode(
        skill=node.skill,
        mastery=mastery_after,
        confidence=confidence_after,
        attempts=attempts_after,
        prerequisites=list(node.prerequisites),
        misconceptions=list(node.misconceptions),
        # Carried explicitly. This constructor rebuilds the node from scratch, so a
        # field omitted here is not preserved -- it is silently reset to empty on the
        # next attempt, and the record of what a student overcame would disappear the
        # moment they answered another question.
        resolved_misconceptions=list(node.resolved_misconceptions),
    )
    audit = SkillUpdate(
        skill=node.skill,
        mastery_before=node.mastery,
        mastery_after=mastery_after,
        confidence_before=node.confidence,
        confidence_after=confidence_after,
        outcome=outcome,
        attempts_after=attempts_after,
    )
    return updated, audit


def resolve_misconceptions(
    node: SkillNode,
    mastery_threshold: float,
    confidence_threshold: float,
) -> tuple[SkillNode, list[str]]:
    """Retire the misconceptions a student has demonstrably grown out of.

    Returns the updated node and the list that was just resolved, so the caller can say
    so out loud rather than quietly changing the record.

    The bar is mastery AND confidence, the same pair that gates every other "they know
    this now" decision in the system. Mastery alone would clear a misconception on a
    single lucky answer, and the BKT model exists precisely because one correct answer
    is not proof -- it would be incoherent to model slip and guess everywhere else and
    then ignore both here.

    Resolved entries are moved, never deleted. A student who once thought a recursive
    call returns itself and no longer does has achieved the thing this whole system is
    for, and that is worth keeping.

    Thresholds are parameters rather than imports: this module is the arithmetic layer
    and does not decide policy, it applies it.
    """
    if not node.misconceptions:
        return node, []
    if node.mastery < mastery_threshold or node.confidence < confidence_threshold:
        return node, []

    newly_resolved = list(node.misconceptions)
    already = list(node.resolved_misconceptions)
    combined = already + [m for m in newly_resolved if m not in already]
    updated = node.model_copy(
        update={"misconceptions": [], "resolved_misconceptions": combined}
    )
    return updated, newly_resolved
