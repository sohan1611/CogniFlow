"""How much a single submission is worth as evidence about one skill.

Classic BKT treats every observation as one bit: right or wrong. That is the correct
model for a multiple-choice item, where the only thing you learn is whether the box was
ticked. It is the wrong model here, because we execute the student's program against test
cases and therefore know considerably more than one bit about what happened:

  - a program that never parsed tells us almost nothing about loops,
  - a program that ran and passed 3 of 4 cases tells us the student nearly has it,
  - a program that ran and passed none tells us they do not,

and those three were previously indistinguishable. This module turns an execution result
into a weighted observation, and keeps the counters that say how much the evidence for a
skill AGREES with itself rather than merely how much of it there is.

Nothing here is probabilistic, model-driven or time-dependent: same inputs, same numbers,
every time (CLAUDE.md RULE 4).
"""

from dataclasses import dataclass
import math

from app.models.enums import CORRECTNESS, StudentOutcome, is_student_evidence
from app.models.errors import InvalidEvidenceError

# Recency discount for the agreement counters. A student who failed three times and then
# succeeded three times is not inconsistent -- they are learning -- so old disagreement
# has to fade or the tutor can never notice that it worked.
#
# 0.60 rather than a gentler 0.80, and the number was measured rather than picked. The
# policy caps a skill at MAX_ATTEMPTS_PER_SKILL = 4 attempts per session, so a student who
# fails twice and then succeeds twice has spent their budget; at 0.80 their confidence
# reaches only 0.265 and the mastery gate (0.5) refuses them, meaning anyone who started
# badly could never be marked as having got there no matter what they did next. At 0.60
# the same recovery reads 0.511 while a clean run is unchanged at 0.811 and alternating
# right/wrong still collapses to 0.231 -- responsive to recovery without becoming
# credulous about noise.
LAMBDA = 0.60

# Evidence needed before confidence is meaningful. 3.0 is chosen so that three consistent
# observations cross 0.5, which is the gate app/mastery/policy.py already relies on.
CONFIDENCE_K = 3.0

# A failed observation never counts as literally nothing; repeated inability to produce a
# running program is itself weak evidence.
W_MIN = 0.05

# How much of a failure is attributable to the skill under test.
KAPPA: dict[StudentOutcome, float] = {
    # It ran and was measured. The fraction it failed is exactly how much of the task the
    # student did not do.
    StudentOutcome.WRONG_ANSWER: 1.00,
    # It ran and crashed: a real defect, but a crash can come from a detail that has
    # nothing to do with the concept being taught.
    StudentOutcome.STUDENT_RUNTIME_ERROR: 0.60,
    # Non-termination is decisive for loops and weak everywhere else.
    StudentOutcome.STUDENT_TIMEOUT: 0.50,
    # The program never ran, so nothing about the concept was observed at all.
    StudentOutcome.STUDENT_SYNTAX_ERROR: 0.15,
}


@dataclass(frozen=True)
class Observation:
    """One piece of student evidence about one skill.

    Constructing this is the ONLY way to submit evidence to the mastery update, and a
    SystemFault cannot be packaged into one. That is CLAUDE.md RULE 3 enforced a step
    earlier than before: an infrastructure failure can no longer even be expressed as
    evidence, let alone reach the arithmetic.
    """

    outcome: StudentOutcome
    score: float = 0.0
    """Fraction of test cases passed, 0.0 to 1.0. Defaults to 0.0 -- the honest default
    for a missing measurement, and the one that reproduces the old all-or-nothing
    behaviour rather than silently awarding credit we did not observe."""

    distinct_expectations: int = 1
    """How many DIFFERENT expected outputs the graded suite contained. See guess_for."""

    def __post_init__(self) -> None:
        if not is_student_evidence(self.outcome):
            raise InvalidEvidenceError(
                f"only StudentOutcome is evidence; refusing {self.outcome!r}"
            )
        score = self.score
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise InvalidEvidenceError(f"score must be a real number, got {score!r}")
        if math.isnan(score) or not 0.0 <= score <= 1.0:
            raise InvalidEvidenceError(f"score must lie in [0, 1], got {score!r}")
        if not isinstance(self.distinct_expectations, int) or isinstance(
            self.distinct_expectations, bool
        ):
            raise InvalidEvidenceError(
                f"distinct_expectations must be an int, got {self.distinct_expectations!r}"
            )
        if self.distinct_expectations < 0:
            raise InvalidEvidenceError("distinct_expectations cannot be negative")


def guess_for(distinct_expectations: int) -> float:
    """P(passing without knowing), derived from how falsifiable the test suite is.

    Everything in CogniFlow is graded by running the student's program against expected
    output, so the chance of passing by luck is not a constant of the subject -- it is a
    property of the instrument we happened to use. A suite with one literal expectation
    can be passed by printing that literal; three different correct outputs for three
    different inputs is not luck.

    This prices our own diagnostic honestly: every diagnostic question carries a single
    expected_output, and four of the eight expect "10", so `print(10)` passes half of it.
    A diagnostic pass is therefore deliberately worth less than an exercise pass.
    """

    if distinct_expectations <= 1:
        return 0.20
    if distinct_expectations == 2:
        return 0.10
    return 0.05


def evidence_weight(obs: Observation) -> float:
    """How much of one full observation this submission is worth."""

    if CORRECTNESS[obs.outcome]:
        return 1.0
    return max(KAPPA[obs.outcome] * (1.0 - obs.score), W_MIN)


def accumulate(
    evidence_weight_total: float,
    agree_correct: float,
    agree_wrong: float,
    obs: Observation,
    *,
    share: float = 1.0,
) -> tuple[float, float, float]:
    """Fold one observation into a skill's evidence counters."""

    weight = evidence_weight(obs) * share
    hit = 1.0 if CORRECTNESS[obs.outcome] else 0.0
    return (
        evidence_weight_total + weight,
        LAMBDA * agree_correct + weight * hit,
        LAMBDA * agree_wrong + weight * (1.0 - hit),
    )


def coverage(evidence_weight_total: float) -> float:
    """How much evidence has been seen, ignoring whether it agrees with itself.

    This is the honest measure for "how thorough was the diagnostic" -- a question about
    how much we asked, not about how well the student did. It is deliberately NOT what a
    skill's confidence uses: four answers is a sketch and eight is a picture, but eight
    answers that contradict each other are still not a picture of anything.
    """

    if evidence_weight_total <= 0.0:
        return 0.0
    return 1.0 - math.exp(-evidence_weight_total / CONFIDENCE_K)


def confidence_from_evidence(
    evidence_weight_total: float,
    agree_correct: float,
    agree_wrong: float,
    p_slip: float,
    p_guess: float,
) -> float:
    """How much the evidence for this skill agrees with itself.

    Two independent questions, deliberately kept apart and multiplied:

        (1 - e^(-N/k))   how much have I seen
        agreement        how much does it look like one story rather than noise

    The agreement term is anchored on the model's own two states, not on 50%: a student
    who knows the skill succeeds at rate (1 - slip), one who does not at rate (guess).
    Confidence is high when the record looks like it came from EITHER of those, and low
    when it looks like neither -- alternating right and wrong is the genuinely
    uninformative case, and it is the one the old attempt-counting formula scored highest.

    This replaces `1 - exp(-attempts / 4)`, which saw only a count: five correct and five
    incorrect both returned 0.7135, and it could never go down.
    """

    if evidence_weight_total <= 0.0:
        return 0.0
    total = agree_correct + agree_wrong
    if total <= 0.0:
        return 0.0
    rho = agree_correct / total
    midpoint = (1.0 - p_slip + p_guess) / 2.0
    half_range = (1.0 - p_slip - p_guess) / 2.0
    # Guaranteed positive by BKTParams.__post_init__ (p_slip + p_guess < 1).
    agreement = min(1.0, abs(rho - midpoint) / half_range)
    return coverage(evidence_weight_total) * agreement
