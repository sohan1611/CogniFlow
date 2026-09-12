"""Pydantic schemas for deterministic CogniFlow state.

Invariant: persisted mastery and confidence values are always bounded in [0, 1].
"""

from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.enums import (
    AdaptationAction,
    AssessmentType,
    Difficulty,
    StudentOutcome,
    TeachingMode,
)

# BKTParams.p_init is the source of truth for this prior.  schemas.py cannot import
# app.mastery.bkt without creating a cycle, so a regression test keeps the two equal.
DEFAULT_MASTERY_PRIOR = 0.30


class SkillNode(BaseModel):
    """State for one skill in the prerequisite graph."""

    skill: str
    mastery: float = Field(ge=0.0, le=1.0, default=DEFAULT_MASTERY_PRIOR)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    attempts: int = Field(ge=0, default=0)
    prerequisites: list[str] = Field(default_factory=list)

    evidence_weight: float = Field(ge=0.0, default=0.0)
    """Total weight of student evidence seen for this skill.

    Not the same as `attempts`: five syntax errors are five attempts but only 0.75 of an
    observation, because a program that never ran said almost nothing about the concept.
    This is also what distinguishes a skill we have MEASURED from one we merely hold a
    prior for -- see `measured`."""

    agree_correct: float = Field(ge=0.0, default=0.0)
    agree_wrong: float = Field(ge=0.0, default=0.0)
    """Recency-discounted evidence for and against, feeding confidence. Kept as running
    sums so confidence is O(1) to update and reconstructible from the attempt log."""

    @property
    def measured(self) -> bool:
        """Whether anything has actually been observed about this skill.

        A skill at its prior is not a skill at 30%: it is a skill we have never tested.
        Showing the prior as a number is how three untested skills came to display 0.24
        indistinguishably from a skill the student had genuinely failed once.
        """

        return self.evidence_weight > 0.0

    misconceptions: list[str] = Field(default_factory=list)
    """Misunderstandings the student is believed to hold RIGHT NOW."""

    resolved_misconceptions: list[str] = Field(default_factory=list)
    """Misunderstandings they used to hold and have since demonstrably overcome.

    Kept rather than deleted. "You used to think a recursive call returns itself, and
    you no longer do" is the single most encouraging thing a tutor can say, and it is
    also the evidence that remediation worked -- deleting it would throw away the only
    record that the detour was worth taking.
    """


class DiagnosticResult(BaseModel):
    """Output of an offline diagnostic pass."""

    weak_skills: list[str]
    target_skill: str | None
    missing_prerequisites: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    skipped_because: dict[str, str] = Field(default_factory=dict)


class PlanningDecision(BaseModel):
    """Deterministic plan for the next assessment or teaching step."""

    target_skill: str
    difficulty: Difficulty
    assessment_type: AssessmentType
    teaching_mode: TeachingMode
    needs_retrieval: bool = True
    reason: str = ""


class AdaptationDecision(BaseModel):
    """Adaptation action proposed as plain input or emitted by the guard."""

    action: AdaptationAction
    target_skill: str | None = None
    teaching_mode: TeachingMode | None = None
    difficulty: Difficulty | None = None
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class GuardVerdict(BaseModel):
    """Result of validating a proposed adaptation decision."""

    final: AdaptationDecision
    overridden: bool
    violated_rules: list[str] = Field(default_factory=list)
    proposed_action: AdaptationAction | None = None


class SkillUpdate(BaseModel):
    """Audit record for a single mastery update from student evidence."""

    skill: str
    mastery_before: float
    mastery_after: float
    confidence_before: float
    confidence_after: float
    outcome: StudentOutcome
    attempts_after: int

    weight: float = 1.0
    """How much of a full observation this submission was worth for this skill."""

    share: float = 1.0
    """This skill's slice of the observation. Below 1.0 when a failure was split with a
    prerequisite; the shares of one submission always sum to exactly 1.0."""

    attributed_from: str | None = None
    """Set on the prerequisite row when the debit arrived from another skill's exercise,
    so the audit trail can say why `variables` moved during a loops problem."""

from app.models.enums import (
    Difficulty, TeachingMode, AssessmentType, AdaptationAction,
    SessionStatus, StudentOutcome, SystemFault, CORRECTNESS, is_student_evidence,
)
from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    skill: str
    topic: str = ""
    unit: str = ""
    subject: str = ""
    difficulty: str = ""
    source_file: str
    section: str = ""
    score: float = Field(ge=0.0)


class RetrievedEvidence(BaseModel):
    """Grounded retrieval result with citations for downstream agents."""

    query: str
    skill_filter: str | None
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    used_fallback: bool = False
    degraded: bool = False
    fault: SystemFault | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0

    def citations(self) -> list[str]:
        seen: set[str] = set()
        citations: list[str] = []
        for chunk in self.chunks:
            citation = f"{chunk.source_file}#{chunk.section}"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)
        return citations


class GeneratedProblem(BaseModel):
    """A task authored for one student at one moment.

    Invariant: `grounding_sources` records which curriculum material informed this
    problem, so a generated task can always be traced back to the page that taught it.
    """

    title: str
    prompt: str
    skill: str
    difficulty: Difficulty
    assessment_type: AssessmentType
    starter_code: str = ""
    test_cases: list[dict[str, str]] = Field(default_factory=list)
    expected_output: str = ""
    grounding_sources: list[str] = Field(default_factory=list)

    # What this task actually demands, carried alongside it. A problem labelled HARD can
    # now be checked against the concepts and cognitive level its rung promised, instead
    # of the label being the only evidence for the claim.
    concepts: list[str] = Field(default_factory=list)
    cognitive_level: str = ""
    complexity: str = ""
    problem_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    generation_seed: str = ""

    def fingerprint(self) -> str:
        """Identity of this exact task at this exact level.

        Includes difficulty, so the same wording at EASY and at HARD are two different
        fingerprints -- which is correct for "have I served this exact problem", and
        exactly wrong for "is this a rerun of something they have already seen". Use
        `content_key` for the second question.
        """
        import hashlib

        basis = f"{self.skill}|{self.difficulty}|{self.assessment_type}|{self.prompt.strip().lower()}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def content_key(self) -> str:
        """Identity of the QUESTION, ignoring what level it was served at.

        This is the one that catches the bug that prompted all of this: the same sentence
        handed to a student at EASY, then MEDIUM, then HARD, differing only in the word in
        the title. Under `fingerprint` those are three distinct problems. Under this they
        are one, which is what a student would tell you.
        """
        import hashlib
        import re

        normalised = re.sub(r"\s+", " ", self.prompt.strip().lower())
        return hashlib.sha256(f"{self.skill}|{normalised}".encode("utf-8")).hexdigest()[:16]


class GradeResult(BaseModel):
    """Outcome of evaluating one submission."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    feedback: str = ""
    failing_case: str | None = None


class MisconceptionAnalysis(BaseModel):
    """What the student appears to misunderstand, and why we think so."""

    misconception: str
    evidence: list[str] = Field(default_factory=list)
    likely_prerequisite_gap: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
