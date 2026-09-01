"""Pydantic schemas for deterministic CogniFlow state.

Invariant: persisted mastery and confidence values are always bounded in [0, 1].
"""

from pydantic import BaseModel, Field

from app.models.enums import (
    AdaptationAction,
    AssessmentType,
    Difficulty,
    StudentOutcome,
    TeachingMode,
)


class SkillNode(BaseModel):
    """State for one skill in the prerequisite graph."""

    skill: str
    mastery: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    attempts: int = Field(ge=0, default=0)
    prerequisites: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)


class DiagnosticResult(BaseModel):
    """Output of an offline diagnostic pass."""

    weak_skills: list[str]
    target_skill: str | None
    missing_prerequisites: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


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

    def fingerprint(self) -> str:
        """Stable hash of the task's substance, used to avoid re-issuing near-identical
        problems. Deliberately excludes title and sources, which can differ while the
        underlying exercise is the same."""
        import hashlib

        basis = f"{self.skill}|{self.difficulty}|{self.assessment_type}|{self.prompt.strip().lower()}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


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
