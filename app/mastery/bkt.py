"""Bayesian Knowledge Tracing for CogniFlow mastery.

Invariant: only StudentOutcome evidence can change a mastery score.
"""

from dataclasses import dataclass
import math

from app.mastery.evidence import (
    Observation,
    accumulate,
    confidence_from_evidence,
    evidence_weight,
    guess_for,
)
from app.models.enums import CORRECTNESS, StudentOutcome, is_student_evidence
from app.models.errors import InvalidEvidenceError
from app.models.schemas import SkillNode, SkillUpdate

# A mastery of exactly 1.0 is an absorbing fixed point of this model: the odds are
# infinite, so no future evidence of any kind can move it. An estimate that cannot be
# revised is not a belief, it is a decoration, so the estimate is capped just below.
MASTERY_CEILING = 0.99


@dataclass(frozen=True)
class BKTParams:
    """Classic Corbett and Anderson BKT parameters, retuned for free-response code.

    The literature defaults describe multiple-choice-shaped assessment. Nothing in
    CogniFlow is multiple choice: we run the student's program. Three of the four moved
    for that reason -- the instrument, not new data -- and `p_guess` is no longer really
    a constant at all (see evidence.guess_for).
    """

    p_init: float = 0.30
    """The honest prior that an arriving learner already holds a given intro-Python skill.
    This is now the system's ONLY prior; app/config/skills.yaml used to carry a second,
    disagreeing one (0.5) which silently won."""

    p_transit: float = 0.08
    """P(not knowing -> knowing) per opportunity. This parameter IS the floor (see
    analytic_floor): at the old 0.15 no student could ever be recorded below 0.171, which
    we measured in production and could not defend. 0.08 describes one problem plus its
    feedback inside a single sitting, rather than the full instructional cycle the 0.15
    figure was drawn from."""

    p_slip: float = 0.15
    """P(answering wrong while knowing). Higher than the classic 0.10, not lower: someone
    who understands loops still ships off-by-ones, typos and misread specs, and writing a
    whole program offers far more ways to fail while knowing than ticking a box does."""

    p_guess: float = 0.10
    """Base P(answering right without knowing). The old 0.20 is the 1-in-5 multiple-choice
    figure and was simply the wrong quantity. Used directly only for the confidence poles;
    each observation derives its own from the suite that graded it."""

    def __post_init__(self) -> None:
        """Validate that BKT probabilities are identifiable."""

        for name in ("p_init", "p_transit", "p_slip", "p_guess"):
            value = getattr(self, name)
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must be strictly inside (0, 1)")
        if self.p_slip + self.p_guess >= 1.0:
            raise ValueError("p_slip + p_guess must be less than 1.0")


def analytic_floor(prm: BKTParams, p_guess: float | None = None,
                   weight: float = 1.0) -> float:
    """The mastery a student converges to under repeated full-strength failure.

    Derivation, because the number matters more than anyone's intuition about it. A wrong
    answer multiplies the odds of knowing by r = S / (1 - G), and the learning transition
    maps p -> p(1 - T) + T. Composing them, the fixed points solve

        (1 - r)u^2 - (1 - r + T)u + T = 0     ->     u = 1  and  u = T / (1 - r)

    and the lower root is attracting. Substituting r gives the expression below.

    The point of having it in closed form: with the OLD parameters it returns exactly
    6/35 = 0.17142857..., which is the wall we measured in production -- no student could
    be recorded below 0.17 no matter how badly it went, because the transition re-injected
    0.15 of the remaining probability mass after every single failure. The floor was a
    property of the dynamics, never a clamp, which is why nobody found it by reading for
    a max(). With the shipped parameters it returns 0.096.

    `weight` gives the floor for a weaker observation, which is lower: repeatedly failing
    to produce a running program converges to 0.051 rather than 0.096.

    Note the floor attracts from BOTH sides. A student already below it drifts up towards
    it rather than down, because with that little evidence the model genuinely cannot
    distinguish them from the floor. That is a property of BKT with a non-zero learn rate,
    not a bug, and it is why the "a failure must never raise mastery" property is stated
    against max(current, floor) rather than against the current value alone.
    """

    guess = prm.p_guess if p_guess is None else p_guess
    if weight >= 1.0:
        return prm.p_transit * (1 - guess) / (1 - guess - prm.p_slip)
    ratio = (prm.p_slip / (1 - guess)) ** weight
    return weight * prm.p_transit / (1 - ratio)


def posterior(p_known: float, correct: bool, prm: BKTParams, weight: float = 1.0,
              p_guess: float | None = None) -> float:
    """Return P(known | observed response) before the learning transition.

    `weight` tempers the likelihood: the odds are multiplied by L**weight, so weight 1 is
    classic BKT and weight 0 leaves the belief exactly where it was. Raising a likelihood
    to a fractional power is the standard way to say "this datum counts as a fraction of
    an observation" -- it stays a Bayesian odds update, and it cannot change the direction
    of the update, only its size.
    """

    guess = prm.p_guess if p_guess is None else p_guess
    p = min(max(p_known, 1e-9), MASTERY_CEILING)
    # Clamped before taking odds: a stored 1.0 (which old rows can contain) would divide
    # by zero, and a stored 0.0 would make the skill permanently unlearnable.
    ratio = (1 - prm.p_slip) / guess if correct else prm.p_slip / (1 - guess)
    odds = (p / (1 - p)) * (ratio ** weight)
    return odds / (1 + odds)


def transition(p_post: float, prm: BKTParams, weight: float = 1.0) -> float:
    """Apply the BKT learning transition, scaled by how strong the observation was.

    Scaling T by the same weight as the likelihood is load-bearing rather than tidy. At
    full strength a syntax error would move mastery UP -- 0.300 becomes 0.307 -- because
    the transition adds learning regardless of what happened. That would reward a student
    whose program never ran. A weak observation is also a weak learning opportunity: the
    student who never got their code to execute never got the feedback that teaches.
    """

    return p_post * (1 - weight * prm.p_transit) + weight * prm.p_transit


def update(
    p_known: float,
    evidence: StudentOutcome | Observation,
    prm: BKTParams,
    *,
    share: float = 1.0,
) -> float:
    """THE ONLY entry point that changes mastery.

    Accepts a bare StudentOutcome (promoted to a full-strength observation, which is
    exactly the old behaviour) or an Observation carrying partial credit and the strength
    of the suite that graded it. `share` scales the observation when a failure is split
    with a prerequisite (see app/mastery/attribution.py).
    """

    obs = evidence if isinstance(evidence, Observation) else Observation(outcome=evidence)
    # Observation.__post_init__ raises InvalidEvidenceError for every SystemFault and for
    # anything that is not a StudentOutcome at all, so the RULE 3 guard now sits one step
    # earlier: a fault cannot be packaged as evidence, never mind submitted as it.
    if not is_student_evidence(obs.outcome):  # pragma: no cover - defence in depth
        raise InvalidEvidenceError("system faults cannot update mastery")

    weight = evidence_weight(obs) * share
    guess = guess_for(obs.distinct_expectations)
    correct = CORRECTNESS[obs.outcome]
    moved = transition(posterior(p_known, correct, prm, weight, guess), prm, weight)
    return min(moved, MASTERY_CEILING)


def update_skill(
    node: SkillNode,
    evidence: StudentOutcome | Observation,
    prm: BKTParams,
    *,
    share: float = 1.0,
    attributed_from: str | None = None,
) -> tuple[SkillNode, SkillUpdate]:
    """Return an immutable SkillNode update plus its audit record.

    `share` is this skill's slice of one observation when a failure is split with a
    prerequisite; `attributed_from` records which exercise the evidence came from, so a
    student can be told why `variables` moved during a loops problem.
    """

    obs = evidence if isinstance(evidence, Observation) else Observation(outcome=evidence)
    mastery_after = update(node.mastery, obs, prm, share=share)
    attempts_after = node.attempts + 1
    weight_used = evidence_weight(obs) * share
    weight_total, agree_correct, agree_wrong = accumulate(
        node.evidence_weight, node.agree_correct, node.agree_wrong, obs, share=share
    )
    confidence_after = confidence_from_evidence(
        weight_total, agree_correct, agree_wrong, prm.p_slip, prm.p_guess
    )
    updated = SkillNode(
        skill=node.skill,
        mastery=mastery_after,
        confidence=confidence_after,
        attempts=attempts_after,
        evidence_weight=weight_total,
        agree_correct=agree_correct,
        agree_wrong=agree_wrong,
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
        outcome=obs.outcome,
        attempts_after=attempts_after,
        weight=weight_used,
        share=share,
        attributed_from=attributed_from,
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
