"""The LangGraph state object.

Invariant: every field is JSON-serializable. LangGraph checkpoints this to SQLite and
rehydrates it in a DIFFERENT process, so a live object (a NetworkX graph, a sandbox
handle, a model client) placed here would not survive the round trip. The skill graph
therefore travels as a plain dict and is rebuilt inside the nodes that need it.

Session state vs long-term state:
  * THIS object is session state, keyed by thread_id, and it dies with the session.
  * Durable mastery lives in SQLite via app/services/student_store.py, keyed by
    student_id, and is written through on every update so a crash mid-session cannot
    lose learning.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from app.models.enums import (
    AdaptationAction,
    AssessmentType,
    Difficulty,
    Language,
    SessionStatus,
    TeachingMode,
)


class AgentState(TypedDict, total=False):
    """State threaded through the CogniFlow graph."""

    # -- identity ----------------------------------------------------------
    student_id: str
    session_id: str  # equals the LangGraph thread_id

    # -- conversation ------------------------------------------------------
    messages: Annotated[list, add_messages]

    # -- curriculum position ----------------------------------------------
    domain: str
    current_skill: str | None
    target_skill: str | None
    prerequisite_skill: str | None
    prereq_return_stack: list[str]
    """Skills we detoured away from. Popping this is how the agent returns to the
    ORIGINAL objective after remediating a prerequisite -- without it, 'return to
    recursion' would be guesswork."""

    # -- pedagogy ----------------------------------------------------------
    language: str
    difficulty_level: str
    teaching_mode: str
    assessment_type: str

    # -- student model (mirror of the durable store) -----------------------
    skill_graph: dict[str, dict[str, Any]]
    mastery_scores: dict[str, float]
    confidence_scores: dict[str, float]

    # -- current task ------------------------------------------------------
    current_problem: dict[str, Any] | None
    current_problem_id: str | None
    retrieved_context: list[str]
    retrieved_sources: list[dict[str, Any]]

    # -- submission --------------------------------------------------------
    student_answer: str | None
    student_code: str | None
    execution_result: dict[str, Any] | None
    grader_result: dict[str, Any] | None

    # -- history -----------------------------------------------------------
    attempt_count: int
    consecutive_failures: int
    topic_attempt_count: dict[str, int]
    detected_misconceptions: list[dict[str, Any]]
    diagnostic_history: list[dict[str, Any]]
    assessment_history: list[dict[str, Any]]
    recent_problem_hashes: list[str]
    """Guards the 'do not generate effectively identical problems' requirement
    mechanically, rather than by asking a prompt nicely."""

    recent_prompts: list[str]
    """The literal wording of recent problems, fed back to the generator as a
    do-not-repeat list. A model cannot avoid what it has not been shown."""

    recent_content_keys: list[str]
    """The same guard, asked the question a STUDENT would ask.

    A fingerprint includes difficulty, so one sentence served at EASY and again at HARD
    is two fingerprints and passes the check -- which is precisely the bug that made this
    field necessary. A content key ignores the level, so a repeat is caught however it is
    labelled."""

    # -- decisions ---------------------------------------------------------
    last_action: str | None
    next_action: str | None
    decision_reason: str | None
    decision_evidence: list[str]
    decision_confidence: float | None
    guard_override: bool
    """True when the deterministic guard rejected the model's proposal. This is the
    ablation headline: how often the rules had to overrule the LLM."""

    # -- control -----------------------------------------------------------
    retry_count: int
    error_count: int
    last_error: str | None
    error_type: str | None

    evidence_score: float
    """Fraction of test cases the submission passed. Feeds the mastery update: failing
    1 of 4 is not the same evidence as failing 4 of 4, and used to be treated as if it
    were."""

    distinct_expectations: int
    """How many DIFFERENT expected outputs the graded suite held. Sets how much a pass is
    worth: a suite with one literal expectation can be passed by printing that literal."""

    attribution_hint: str | None
    """Prerequisite implicated by a DETERMINISTIC misconception rule, and nothing else.

    Kept separate from `detected_misconceptions[].implicates`, which may come from the
    LLM. That value routes the next problem; this one moves a mastery score, and CLAUDE.md
    RULE 4 forbids a model deciding what a student's record says about them."""
    session_status: str
    loop_count: int
    prereq_depth: int
    recommended_next_skill: str | None
    """What to study next, set by `finalize` when the target was actually mastered.

    Absent rather than empty when nothing was unlocked: a session that halted on a limit,
    or one whose target still has unmastered dependents, has nothing honest to recommend.
    """


def initial_state(
    student_id: str,
    session_id: str,
    *,
    domain: str = "python_fundamentals",
    target_skill: str | None = None,
    language: str | Language = Language.PYTHON,
) -> AgentState:
    """A fully-populated starting state.

    Every key is present from the start so nodes never have to guess whether a field
    exists -- a partially-initialised TypedDict is how KeyErrors reach a live demo.
    """
    return AgentState(
        student_id=student_id,
        session_id=session_id,
        messages=[],
        domain=domain,
        language=str(language),
        current_skill=None,
        target_skill=target_skill,
        prerequisite_skill=None,
        prereq_return_stack=[],
        difficulty_level=str(Difficulty.MEDIUM),
        teaching_mode=str(TeachingMode.TEXTUAL),
        assessment_type=str(AssessmentType.CODING),
        skill_graph={},
        mastery_scores={},
        confidence_scores={},
        current_problem=None,
        current_problem_id=None,
        retrieved_context=[],
        retrieved_sources=[],
        student_answer=None,
        student_code=None,
        execution_result=None,
        grader_result=None,
        attempt_count=0,
        consecutive_failures=0,
        topic_attempt_count={},
        detected_misconceptions=[],
        diagnostic_history=[],
        assessment_history=[],
        recent_problem_hashes=[],
        recent_prompts=[],
        recent_content_keys=[],
        last_action=None,
        next_action=None,
        decision_reason=None,
        decision_evidence=[],
        decision_confidence=None,
        guard_override=False,
        retry_count=0,
        error_count=0,
        last_error=None,
        error_type=None,
        evidence_score=0.0,
        distinct_expectations=1,
        attribution_hint=None,
        session_status=str(SessionStatus.ACTIVE),
        loop_count=0,
        prereq_depth=0,
    )
