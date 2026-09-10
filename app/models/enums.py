"""Domain enums for CogniFlow.

Invariant: student outcomes and system faults are disjoint runtime types.
"""

from enum import StrEnum


class Difficulty(StrEnum):
    """Supported assessment and instruction difficulty levels."""

    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class Language(StrEnum):
    """Programming languages CogniFlow can offer when execution is safe."""

    PYTHON = "PYTHON"
    JAVASCRIPT = "JAVASCRIPT"
    JAVA = "JAVA"
    CPP = "CPP"
    C = "C"


class TeachingMode(StrEnum):
    """Deterministic teaching modes available to the policy layer."""

    TEXTUAL = "TEXTUAL"
    WORKED_EXAMPLE = "WORKED_EXAMPLE"
    CODE_TRACE = "CODE_TRACE"
    ANALOGY = "ANALOGY"
    SOCRATIC_HINTS = "SOCRATIC_HINTS"
    VISUAL_DESCRIPTION = "VISUAL_DESCRIPTION"


class AssessmentType(StrEnum):
    """Assessment shapes that can be selected without model calls.

    Every member is graded by EXECUTION: the student submits a program, it runs in the
    sandbox, and the output is compared. That is what makes grading deterministic and
    free.

    MCQ and SHORT_ANSWER were declared here and never implemented, because both need a
    rubric grader for free text that this system does not have -- and adding one would
    put a model in the grading path, which is exactly where we have refused to put one.
    They are removed rather than left in the enum: a listed capability that no code path
    can reach is a claim, and this project does not make claims it cannot demonstrate.
    """

    CODING = "CODING"
    CODE_TRACE = "CODE_TRACE"
    DEBUGGING = "DEBUGGING"


class AdaptationAction(StrEnum):
    """Actions proposed by later models or emitted by deterministic policy."""

    ADVANCE = "ADVANCE"
    RETRY_VARIATION = "RETRY_VARIATION"
    EXPLAIN_DIFFERENTLY = "EXPLAIN_DIFFERENTLY"
    STEP_DOWN_DIFFICULTY = "STEP_DOWN_DIFFICULTY"
    REVISIT_PREREQUISITE = "REVISIT_PREREQUISITE"
    ESCALATE_DIFFICULTY = "ESCALATE_DIFFICULTY"
    REASSESS = "REASSESS"
    COMPLETE = "COMPLETE"


class SessionStatus(StrEnum):
    """Session lifecycle states controlled by deterministic limits."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    HALTED_LIMIT = "HALTED_LIMIT"
    HALTED_ERROR = "HALTED_ERROR"


class StudentOutcome(StrEnum):
    """Evidence about student performance that may update mastery."""

    CORRECT = "CORRECT"
    WRONG_ANSWER = "WRONG_ANSWER"
    STUDENT_SYNTAX_ERROR = "STUDENT_SYNTAX_ERROR"
    STUDENT_RUNTIME_ERROR = "STUDENT_RUNTIME_ERROR"
    STUDENT_TIMEOUT = "STUDENT_TIMEOUT"


class SystemFault(StrEnum):
    """Infrastructure failures that must never update mastery."""

    SANDBOX_FAILURE = "SANDBOX_FAILURE"
    LLM_FAILURE = "LLM_FAILURE"
    MALFORMED_MODEL_OUTPUT = "MALFORMED_MODEL_OUTPUT"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    EXECUTION_REFUSED = "EXECUTION_REFUSED"
    """Static restrictions refused to run the submission.

    On the SystemFault side deliberately. A student who writes a correct function and
    also imports `os` has demonstrated no misconception, and their mastery must not move
    because of a restriction nobody told them about."""


CORRECTNESS: dict[StudentOutcome, bool] = {
    StudentOutcome.CORRECT: True,
    StudentOutcome.WRONG_ANSWER: False,
    StudentOutcome.STUDENT_SYNTAX_ERROR: False,
    StudentOutcome.STUDENT_RUNTIME_ERROR: False,
    StudentOutcome.STUDENT_TIMEOUT: False,
}


def is_student_evidence(x: object) -> bool:
    """Return True only for evidence emitted as a StudentOutcome member."""

    return isinstance(x, StudentOutcome)
