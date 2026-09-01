"""Phase 5 tests: orchestration, checkpointing, interrupt/resume.

Covers plan requirements 15 (checkpoint persistence) and 16 (interrupt/resume).

Test 16 deliberately resumes in a SEPARATE OS PROCESS. Resuming in-process only proves
the object stayed in memory; resuming from a cold process proves the graph genuinely
suspended to disk and rehydrated, which is the claim we make to judges.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from langgraph.types import Command

from app.graph.builder import build_graph, route_context, route_evidence, route_next, sqlite_checkpointer
from app.graph.deps import GraphDeps
from app.graph.state import AgentState, initial_state
from app.mastery import policy
from app.mastery.skill_graph import SkillGraph
from app.models.enums import SessionStatus, StudentOutcome, SystemFault
from app.services.events import EventLog, EventType
from app.services.student_store import StudentStore
from app.tools.sandbox.faults import FaultInjectingSandbox, FaultInjector
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

SKILLS = Path("app/config/skills.yaml")
CORRECT = {"code": "print(12)"}


def _store(tmp_path: Path, **overrides: float) -> StudentStore:
    store = StudentStore(tmp_path / "students.db")
    nodes = SkillGraph.from_yaml(SKILLS).nodes
    for skill, mastery in overrides.items():
        nodes[skill] = nodes[skill].model_copy(
            update={"mastery": mastery, "confidence": 0.6, "attempts": 3}
        )
    store.seed("s1", nodes)
    return store


def _app(store: StudentStore, events: EventLog, checkpointer=None, sandbox=None):
    deps = GraphDeps.offline(store, events)
    if sandbox is not None:
        deps.sandbox = sandbox
    return build_graph(deps, checkpointer=checkpointer)


# ------------------------------------------------------------------ routers
def test_route_evidence_sends_student_outcomes_to_mastery() -> None:
    for outcome in StudentOutcome:
        state: AgentState = {"error_type": str(outcome)}  # type: ignore[assignment]
        assert route_evidence(state) == "update_mastery", outcome


def test_route_evidence_sends_every_system_fault_to_recover() -> None:
    """The safety edge, checked exhaustively rather than on a happy path."""
    for fault in SystemFault:
        state: AgentState = {"error_type": str(fault)}  # type: ignore[assignment]
        assert route_evidence(state) == "recover", fault


def test_route_evidence_treats_junk_as_a_fault() -> None:
    for junk in ("", "banana", "None"):
        assert route_evidence({"error_type": junk}) == "recover"  # type: ignore[arg-type]


def test_route_next_respects_every_ceiling() -> None:
    active = {"session_status": str(SessionStatus.ACTIVE)}
    assert route_next({**active, "loop_count": 1}) == "continue"  # type: ignore[arg-type]
    assert route_next({**active, "loop_count": policy.MAX_LOOPS}) == "finalize"  # type: ignore[arg-type]
    assert route_next({**active, "error_count": 6}) == "finalize"  # type: ignore[arg-type]
    assert route_next({**active, "next_action": "COMPLETE"}) == "finalize"  # type: ignore[arg-type]
    assert route_next({"session_status": str(SessionStatus.HALTED_ERROR)}) == "finalize"  # type: ignore[arg-type]


def test_route_context_skips_retrieval_when_material_already_matches() -> None:
    same = {"target_skill": "functions", "retrieved_sources": [{"skill": "functions"}]}
    other = {"target_skill": "recursion", "retrieved_sources": [{"skill": "functions"}]}
    assert route_context(same) == "generate_problem"  # type: ignore[arg-type]
    assert route_context(other) == "retrieve"  # type: ignore[arg-type]
    assert route_context({"target_skill": "x", "retrieved_sources": []}) == "retrieve"  # type: ignore[arg-type]


# ------------------------------------------------------- interrupt / resume
def test_graph_pauses_at_the_student_interaction_point(tmp_path: Path) -> None:
    events = EventLog()
    app = _app(_store(tmp_path), events)
    cfg = {"configurable": {"thread_id": "t-pause"}}

    out = app.invoke(initial_state("s1", "t-pause", target_skill="recursion"), cfg)

    assert "__interrupt__" in out
    assert app.get_state(cfg).next == ("await_student",)
    assert events.of_type(EventType.AWAITING_STUDENT)


def test_resume_delivers_the_submission_and_continues(tmp_path: Path) -> None:
    events = EventLog()
    app = _app(_store(tmp_path), events)
    cfg = {"configurable": {"thread_id": "t-resume"}}

    app.invoke(initial_state("s1", "t-resume", target_skill="recursion"), cfg)
    out = app.invoke(Command(resume=CORRECT), cfg)

    assert out["attempt_count"] == 1
    assert out["student_code"] == CORRECT["code"]
    assert events.of_type(EventType.MASTERY), "a submission must move the model"


# --------------------------------------------- TEST 15: checkpoint persists
def test_15_checkpoint_is_written_to_sqlite_and_survives_reopen(tmp_path: Path) -> None:
    ckpt = tmp_path / "ckpt.db"
    cfg = {"configurable": {"thread_id": "t-persist"}}

    saver, conn = sqlite_checkpointer(ckpt)
    app = _app(_store(tmp_path), EventLog(), checkpointer=saver)
    app.invoke(initial_state("s1", "t-persist", target_skill="recursion"), cfg)
    conn.close()

    assert ckpt.exists() and ckpt.stat().st_size > 0

    # Reopen from scratch -- a genuinely new saver over the same file.
    saver2, conn2 = sqlite_checkpointer(ckpt)
    app2 = _app(_store(tmp_path), EventLog(), checkpointer=saver2)
    snapshot = app2.get_state(cfg)
    conn2.close()

    assert snapshot.next == ("await_student",), "pending node lost across reopen"
    assert snapshot.values["target_skill"] == "recursion"
    assert snapshot.values["current_problem"] is not None


def test_15_separate_threads_do_not_share_state(tmp_path: Path) -> None:
    saver, conn = sqlite_checkpointer(tmp_path / "c.db")
    app = _app(_store(tmp_path), EventLog(), checkpointer=saver)
    try:
        a = {"configurable": {"thread_id": "A"}}
        b = {"configurable": {"thread_id": "B"}}
        app.invoke(initial_state("s1", "A", target_skill="recursion"), a)
        app.invoke(initial_state("s1", "B", target_skill="loops"), b)
        assert app.get_state(a).values["target_skill"] == "recursion"
        assert app.get_state(b).values["target_skill"] == "loops"
    finally:
        conn.close()


# ------------------------------ TEST 16: resume in a SEPARATE OS PROCESS
RESUME_SCRIPT = '''
import json, sys
from pathlib import Path
sys.path.insert(0, {root!r})
from langgraph.types import Command
from app.graph.builder import build_graph, sqlite_checkpointer
from app.graph.deps import GraphDeps
from app.services.events import EventLog
from app.services.student_store import StudentStore

saver, conn = sqlite_checkpointer({ckpt!r})
store = StudentStore({db!r})
app = build_graph(GraphDeps.offline(store, EventLog()), checkpointer=saver)
cfg = {{"configurable": {{"thread_id": {thread!r}}}}}

before = app.get_state(cfg)
out = app.invoke(Command(resume={{"code": "print(12)"}}), cfg)
conn.close()
print(json.dumps({{
    "pending_before": list(before.next),
    "attempt_count": out.get("attempt_count"),
    "student_code": out.get("student_code"),
    "target_skill": out.get("target_skill"),
    "mastery": out.get("mastery_scores", {{}}).get("recursion"),
}}))
'''


def test_16_interrupt_and_resume_across_two_processes(tmp_path: Path) -> None:
    """The claim we make to judges: it genuinely suspends, and a COLD process resumes it."""
    ckpt = tmp_path / "ckpt.db"
    db = tmp_path / "students.db"
    root = str(Path.cwd())

    # --- process 1: start and suspend ---------------------------------
    store = StudentStore(db)
    store.seed("s1", SkillGraph.from_yaml(SKILLS).nodes)
    saver, conn = sqlite_checkpointer(ckpt)
    app = build_graph(GraphDeps.offline(store, EventLog()), checkpointer=saver)
    cfg = {"configurable": {"thread_id": "cross"}}
    first = app.invoke(initial_state("s1", "cross", target_skill="recursion"), cfg)
    assert "__interrupt__" in first
    mastery_before = first["mastery_scores"]["recursion"]
    conn.close()
    del app, saver, store  # nothing from process 1 may be reused

    # --- process 2: a genuinely separate interpreter -------------------
    script = RESUME_SCRIPT.format(
        root=root, ckpt=str(ckpt), db=str(db), thread="cross"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0, f"resume process failed:\n{proc.stderr[-2000:]}"

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["pending_before"] == ["await_student"], "cold process saw no pause"
    assert payload["attempt_count"] == 1
    assert payload["student_code"] == "print(12)"
    assert payload["target_skill"] == "recursion"
    assert payload["mastery"] != mastery_before, "the resumed run did not update mastery"


# --------------------------------- infra faults must not touch mastery
def test_injected_sandbox_failure_leaves_mastery_untouched_through_the_graph(
    tmp_path: Path,
) -> None:
    """Plan requirement 14, exercised through real graph routing rather than a unit call."""
    store = _store(tmp_path, recursion=0.35)
    events = EventLog()
    injector = FaultInjector()
    injector.queue(SystemFault.SANDBOX_FAILURE)
    sandbox = FaultInjectingSandbox(SubprocessSandbox(), injector)

    app = _app(store, events, sandbox=sandbox)
    cfg = {"configurable": {"thread_id": "t-fault"}}
    start = app.invoke(initial_state("s1", "t-fault", target_skill="recursion"), cfg)
    before = start["mastery_scores"]["recursion"]

    out = app.invoke(Command(resume=CORRECT), cfg)

    assert out["mastery_scores"]["recursion"] == before, "an infra fault moved mastery"
    assert events.of_type(EventType.RECOVERY), "recovery node was not reached"
    assert not events.of_type(EventType.MASTERY), "mastery node must not have run"
    assert store.attempts_for("s1", "recursion") == [], "no attempt should be logged"


# ------------------------------------------------------- serializability
def test_state_after_a_full_turn_is_json_serializable(tmp_path: Path) -> None:
    """If this fails, cross-process resume will fail later and more mysteriously."""
    app = _app(_store(tmp_path), EventLog())
    cfg = {"configurable": {"thread_id": "t-json"}}
    app.invoke(initial_state("s1", "t-json", target_skill="recursion"), cfg)
    out = app.invoke(Command(resume=CORRECT), cfg)

    payload = {k: v for k, v in out.items() if k not in ("messages", "__interrupt__")}
    encoded = json.dumps(payload, default=str)
    assert json.loads(encoded)["target_skill"]


def test_durable_store_is_written_through_on_every_update(tmp_path: Path) -> None:
    """A crash mid-session must not lose demonstrated learning."""
    store = _store(tmp_path, recursion=0.35)
    app = _app(store, EventLog())
    cfg = {"configurable": {"thread_id": "t-wt"}}
    app.invoke(initial_state("s1", "t-wt", target_skill="recursion"), cfg)
    app.invoke(Command(resume=CORRECT), cfg)

    reopened = StudentStore(tmp_path / "students.db")
    assert reopened.load_skills("s1")["recursion"].mastery != 0.35
    assert len(reopened.attempts_for("s1", "recursion")) == 1
