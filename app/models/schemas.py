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
