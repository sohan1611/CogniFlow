"""Graph assembly: nodes, conditional edges, loop bounds, checkpointing.

Invariant: `update_mastery` is reachable ONLY along the valid-evidence edge. The
evidence router is the single place that decides whether something a student did, or
something our infrastructure did, is about to move a mastery score -- so it is the
edge that enforces the project's central safety property.

Termination is bounded three independent ways (loop count, per-skill attempts,
prerequisite depth), because an adaptive loop with no ceiling is an infinite loop
waiting for a live demo.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import nodes as N
from app.graph.deps import GraphDeps
from app.graph.state import AgentState
from app.mastery import policy
from app.models.enums import AdaptationAction, SessionStatus, is_student_evidence


# ---------------------------------------------------------------- routers
def route_evidence(state: AgentState) -> Literal["update_mastery", "recover"]:
    """THE safety edge.

    Student evidence updates the model. Infrastructure faults never do. Because this
    is a routing decision rather than an `if` buried inside the mastery updater, the
    property is visible in the graph topology itself.
    """
    raw = state.get("error_type") or ""
    try:
        from app.models.enums import StudentOutcome

        return "update_mastery" if is_student_evidence(StudentOutcome(raw)) else "recover"
    except ValueError:
        return "recover"


def route_next(state: AgentState) -> Literal["continue", "finalize"]:
    """Loop or stop. Three independent ceilings, any of which ends the session."""
    if state.get("session_status") not in (str(SessionStatus.ACTIVE), None):
        return "finalize"
    if state.get("next_action") == AdaptationAction.COMPLETE:
        return "finalize"
    if state.get("loop_count", 0) >= policy.MAX_LOOPS:
        return "finalize"
    if state.get("error_count", 0) > 5:
        return "finalize"
    return "continue"


def route_context(state: AgentState) -> Literal["retrieve", "generate_problem"]:
    """Skip retrieval when we already hold material for this skill."""
    sources = state.get("retrieved_sources") or []
    skill = state.get("target_skill")
    if sources and all(s.get("skill") == skill for s in sources):
        return "generate_problem"
    return "retrieve"


# ---------------------------------------------------------------- builder
def build_graph(deps: GraphDeps, checkpointer=None):
    """Compile the CogniFlow graph.

    A checkpointer is REQUIRED for interrupt/resume; MemorySaver is used when none is
    supplied so tests and one-shot runs still work.
    """
    g = StateGraph(AgentState)

    g.add_node("load_student", N.make_load_student(deps))
    g.add_node("diagnose", N.make_diagnose(deps))
    g.add_node("plan_action", N.make_plan_action(deps))
    g.add_node("retrieve", N.make_retrieve(deps))
    g.add_node("generate_problem", N.make_generate_problem(deps))
    g.add_node("await_student", N.make_await_student(deps))
    g.add_node("execute_and_grade", N.make_execute_and_grade(deps))
    g.add_node("update_mastery", N.make_update_mastery(deps))
    g.add_node("adapt", N.make_adapt(deps))
    g.add_node("recover", N.make_recover(deps))
    g.add_node("finalize", N.make_finalize(deps))

    g.add_edge(START, "load_student")
    g.add_edge("load_student", "diagnose")
    g.add_edge("diagnose", "plan_action")

    g.add_conditional_edges(
        "plan_action",
        route_context,
        {"retrieve": "retrieve", "generate_problem": "generate_problem"},
    )
    g.add_edge("retrieve", "generate_problem")
    g.add_edge("generate_problem", "await_student")
    g.add_edge("await_student", "execute_and_grade")

    g.add_conditional_edges(
        "execute_and_grade",
        route_evidence,
        {"update_mastery": "update_mastery", "recover": "recover"},
    )
    g.add_edge("update_mastery", "adapt")

    g.add_conditional_edges(
        "adapt", route_next, {"continue": "plan_action", "finalize": "finalize"}
    )
    g.add_conditional_edges(
        "recover", route_next, {"continue": "plan_action", "finalize": "finalize"}
    )
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())


def sqlite_checkpointer(path: Path | str):
    """A durable checkpointer plus the connection that owns it.

    Returns (saver, connection). The caller must close the connection -- holding it
    open is what lets a SEPARATE PROCESS resume the same thread later, which is the
    whole point of the exercise.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(conn), conn
