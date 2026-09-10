"""HTTP API over the tutoring graph.

    uvicorn app.api.main:app --reload

A second renderer, not a second implementation. `ui.py` opens by saying it renders state
and never decides anything; this file makes the same promise, and the two are proof of
it -- the graph does not know or care which one is talking to it. Everything here is
serialisation and session lookup.

Why this exists: Streamlit cannot be the product surface. It is a single Python process
holding session state in memory, which is right for a demo and wrong for a student on a
phone. Splitting the engine behind HTTP lets a real frontend live somewhere else,
without the engine learning anything about it.

Sessions are held in memory here, deliberately. Durable STUDENT state is already in
SQLite via StudentStore; what lives in this dict is the in-flight graph handle, which is
exactly the thing that should not outlive a restart. Swapping the dict for Redis is a
change to this file alone.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.graph.builder import build_graph
from app.graph.deps import GraphDeps
from app.graph.state import initial_state
from app.llm.provider import Role, available_chain
from app.mastery.misconceptions import hints_for
from app.mastery.difficulty import rung_for
from app.mastery.policy import MASTERY_THRESHOLD, is_mastered
from app.mastery.skill_graph import SkillGraph, weakest_startable
from app.models.enums import Difficulty, Language, StudentOutcome
from app.rag.retriever import Retriever
from app.services.demo_runner import seed_student
from app.services.diagnostic import DiagnosticSession
from app.services.events import EventLog, EventType
from app.services.student_store import StudentStore, student_id_from_name
from app.tools.sandbox.docker_sandbox import DockerSandbox
from app.tools.sandbox.languages import (
    LanguageSpec,
    available_languages,
    is_offerable,
    spec_for,
)
from app.tools.sandbox.runner import run_test_cases
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

SKILLS_CONFIG = "app/config/skills.yaml"

# ----------------------------------------------------------------- startup
# The repository root, resolved from this file rather than from the working directory.
# A deployed host may start the process from anywhere; "data/knowledge" relative to CWD
# is a coin flip, and the failure it produces -- an empty index -- is silent.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Set once the curriculum index is usable. Anything that needs grounded retrieval waits
# on this; nothing else does.
#
# It starts SET, and only the lifespan clears it. That asymmetry is deliberate: a waiter
# should block only when something is actually going to set the event later, and the
# lifespan is the only thing that starts the indexing thread. Importing this module
# without running the lifespan -- which is what the tests and any embedding caller do --
# must not make every request sit out a three-minute timeout for work nobody started.
INDEX_READY = threading.Event()
INDEX_READY.set()
INDEX_STATUS = "ready"


def _index_corpus() -> None:
    """Index the curriculum if the deployed image did not ship an index.

    A deployed host can start from a clean checkout with no `data/chroma`, and retrieval
    against an empty index does not raise -- it returns nothing, and every generated
    exercise quietly loses its grounding. The Streamlit UI has bootstrapped since its
    first commit; the API did not, which would have made "grounded in the functions
    chapter" false on the very first deployment while everything still appeared to work.

    Normally this is a no-op: the build step ingests the corpus so the index ships inside
    the image. It stays here because the build step is host configuration, and the one
    thing this must not depend on is a host being configured correctly.
    """
    global INDEX_STATUS

    from app.rag.ingest import ingest_corpus
    from app.rag.store import VectorStore

    try:
        store = VectorStore()
        if store.count() == 0:
            ingest_corpus(REPO_ROOT / "data" / "knowledge", store=store)
        INDEX_STATUS = "ready"
        print(f"[bootstrap] corpus chunks indexed: {store.count()}", flush=True)
    except Exception as exc:  # noqa: BLE001 - never take the service down over the index
        # Degraded retrieval is survivable; a service that refuses to boot is not.
        INDEX_STATUS = f"failed: {exc}"
        print(f"[bootstrap] corpus indexing failed: {exc}", flush=True)
    finally:
        # Set unconditionally. A waiter must be released by failure as surely as by
        # success -- an index that will never arrive must not hold a request forever.
        INDEX_READY.set()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Bind the port first; index behind it.

    Doing the indexing inline here cost a deployment: uvicorn does not open the port
    until startup returns, so a first boot that downloads an 80MB embedding model and
    embeds the corpus looks, from outside, exactly like a service that never came up.
    The host's port scan gives up, and the deploy fails with a perfectly healthy process
    sat there embedding chunks.

    So the work runs on a thread and readiness is a signal rather than a precondition.
    Only the endpoints that actually need grounded retrieval wait for it.
    """
    global INDEX_STATUS

    INDEX_STATUS = "indexing"
    INDEX_READY.clear()
    threading.Thread(target=_index_corpus, name="corpus-index", daemon=True).start()
    yield


app = FastAPI(
    title="CogniFlow API",
    version="1.0",
    description="Adaptive tutoring with prerequisite-aware remediation.",
    lifespan=lifespan,
)

# The browser calling this will not share an origin with it: the UI is on Vercel, the
# engine is not. The regex covers the project's production alias, its branch alias, and
# the per-deploy preview hostnames, which change on every push and so cannot be listed.
#
# Worth being straight about what this does and does not buy. CORS is a browser policy,
# not access control -- this API has no authentication, so anyone with curl can read any
# student's progress by guessing a display name, and no origin list changes that. What
# it does stop is an unrelated page a student has open reading their progress from their
# browser. Real access control arrives with real accounts, and the day it does, this is
# not the line that provides it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https://cogniflow(-[a-z0-9-]+)?\.vercel\.app",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- wire format
class StartRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_skill: str | None = None
    language: str | None = None


class SubmitRequest(BaseModel):
    code: str = Field(max_length=20_000)


class DiagnosticAnswer(BaseModel):
    skill: str
    code: str = Field(max_length=20_000)


# ----------------------------------------------------------------- sessions
@dataclass
class Session:
    """One student's in-flight graph, plus the store it writes through to."""

    student_id: str
    display_name: str
    store: StudentStore
    events: EventLog
    graph: Any
    cfg: dict[str, Any]
    state: dict[str, Any] | None = None
    diagnostic: DiagnosticSession | None = None
    language: str = Language.PYTHON.value
    _sandbox: SubprocessSandbox = field(default_factory=SubprocessSandbox)


SESSIONS: dict[str, Session] = {}


def _session(student_id: str) -> Session:
    session = SESSIONS.get(student_id)
    if session is None:
        raise HTTPException(404, f"no active session for {student_id!r}; POST /session first")
    return session


def _language_payload(specs: list[LanguageSpec]) -> list[dict[str, str]]:
    return [{"value": spec.language.value, "label": spec.label} for spec in specs]


def _offerable_language_specs() -> list[LanguageSpec]:
    return available_languages(docker_available=DockerSandbox.is_available())


def _language_or_400(raw: str | None) -> LanguageSpec:
    requested = (raw or Language.PYTHON.value).strip().upper()
    try:
        language = Language(requested)
    except ValueError as exc:
        specs = _offerable_language_specs()
        available = ", ".join(spec.language.value for spec in specs) or "none"
        raise HTTPException(
            400,
            f"unsupported language {raw!r}; available languages: {available}",
        ) from exc

    if language == Language.PYTHON:
        spec = spec_for(language)
        if is_offerable(spec, docker_available=False):
            return spec

    specs = _offerable_language_specs()
    available = ", ".join(spec.language.value for spec in specs) or "none"
    for spec in specs:
        if spec.language == language:
            return spec
    raise HTTPException(
        400,
        f"{language.value} is unavailable on this host; available languages: {available}",
    )


def _serialise_events(events: EventLog, limit: int = 40) -> list[dict[str, Any]]:
    """The decision trail, which is the thing worth showing about this system."""
    return [
        {
            "node": event.node,
            "type": event.event_type.value,
            "payload": {k: v for k, v in event.payload.items() if v not in (None, [], {}, "")},
            "reason": event.decision_reason,
            "evidence": event.evidence[:3],
        }
        for event in events.events[-limit:]
    ]


_DIFFICULTY_ORDER = {"EASY": 0, "MEDIUM": 1, "HARD": 2}


def _difficulty_change(events: EventLog) -> dict[str, Any] | None:
    """The last time this student's level moved, and why.

    Derived from the event log rather than tracked as extra state, because the log
    already records the difficulty of every problem generated and the reason behind
    every adaptation -- and two sources for one fact is how they come to disagree.

    A student who is moved between levels without being told why has been handed a
    harder problem for no visible reason, which reads as the system being arbitrary.
    The reason is already computed by the policy guard; this only carries it out.
    """
    generated = [e for e in events.events if e.event_type == EventType.GENERATED]
    if len(generated) < 2:
        return None

    before = str(generated[-2].payload.get("difficulty") or "")
    after = str(generated[-1].payload.get("difficulty") or "")
    if not before or not after or before == after:
        return None

    adaptations = [e for e in events.events if e.event_type == EventType.ADAPTATION]
    rank_before = _DIFFICULTY_ORDER.get(before, -1)
    rank_after = _DIFFICULTY_ORDER.get(after, -1)
    going_up = rank_after > rank_before

    skill = str(generated[-1].payload.get("skill") or "")
    was = rung_for(skill, Difficulty(before)) if before in _DIFFICULTY_ORDER else None
    now = rung_for(skill, Difficulty(after)) if after in _DIFFICULTY_ORDER else None

    # Two audiences, two sentences, and they are not interchangeable.
    #
    # `reason` is the policy guard's own words, carried through unmodified, because the
    # audit trail must not drift from the decision it records. But those words are
    # diagnostics: a student who levelled up was shown "insufficient evidence for mastery
    # or remediation decision", which is true, internal, and useless to them.
    #
    # `student_reason` is built from the ladder -- the authority on what each level
    # demands -- so it says what changed in terms of the work, and cannot invent a
    # motive the system did not have.
    student_reason = None
    if was and now:
        student_reason = (
            f"You handled {was.demands}. Now testing {now.demands}."
            if going_up
            else f"Stepping back to {now.demands} before trying {was.demands} again."
        )

    return {
        "from": before,
        "to": after,
        "direction": "up" if going_up else "down",
        "reason": adaptations[-1].decision_reason if adaptations else None,
        "student_reason": student_reason,
        "demands": generated[-1].payload.get("cognitive_level") or None,
        "concepts": [c for c in str(generated[-1].payload.get("concepts") or "").split(",") if c],
    }


def _view(session: Session) -> dict[str, Any]:
    """Everything a frontend needs to draw the current moment."""
    snapshot = session.graph.get_state(session.cfg)
    values, pending = snapshot.values, snapshot.next
    problem = values.get("current_problem") or {}
    grade = values.get("grader_result") or {}

    raw_outcome = str(values.get("error_type") or "")
    try:
        StudentOutcome(raw_outcome)
        student_evidence = True
    except ValueError:
        student_evidence = False

    return {
        "student_id": session.student_id,
        "name": session.display_name,
        "awaiting_student": bool(pending),
        "suspended_at": pending[0] if pending else None,
        "problem": {
            "title": problem.get("title"),
            "prompt": problem.get("prompt"),
            "starter_code": problem.get("starter_code", ""),
            "expected_output": problem.get("expected_output", ""),
            "assessment_type": problem.get("assessment_type"),
            "grounded_in": problem.get("grounding_sources", []),
        } if problem else None,
        "feedback": {
            "passed": grade.get("passed"),
            "score": grade.get("score"),
            "message": grade.get("feedback"),
            # A system fault is ours, and the frontend must be able to say so rather
            # than showing our outage as the student's mistake.
            "was_our_fault": bool(grade) and not student_evidence,
        } if grade else None,
        "target_skill": values.get("target_skill"),
        "language": values.get("language") or session.language,
        "teaching_mode": values.get("teaching_mode"),
        "difficulty": values.get("difficulty_level"),
        "mastery": values.get("mastery_scores", {}),
        "returning_to": (values.get("prereq_return_stack") or [None])[0],
        "recommended_next": values.get("recommended_next_skill"),
        "session_status": values.get("session_status"),
        "difficulty_change": _difficulty_change(session.events),
        "events": _serialise_events(session.events),
    }


# ----------------------------------------------------------------- endpoints
@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, plus whether generation will be live or templated.

    The second half matters: a frontend that cannot tell degraded from healthy will
    present a templated exercise as though a model wrote it.
    """
    reachable = [s.provider for s in available_chain(Role.GENERATE)]
    language_specs = _offerable_language_specs()
    return {
        "status": "ok",
        "providers": reachable,
        "generation": "live" if reachable else "deterministic-templates",
        "languages": _language_payload(language_specs),
        # Reported, not hidden. Retrieval that is still warming up is a real state of
        # this service, and a state the frontend is entitled to see.
        "corpus": INDEX_STATUS,
    }


@app.get("/skills")
def skills() -> dict[str, Any]:
    """The prerequisite graph, so a frontend can draw it."""
    graph = SkillGraph.from_yaml(SKILLS_CONFIG)
    return {
        "mastery_threshold": MASTERY_THRESHOLD,
        "skills": [
            {
                "skill": name,
                "prerequisites": graph.prerequisites(name),
                "unlocks": graph.dependents(name),
            }
            for name in sorted(graph.nodes)
        ],
    }


@app.post("/session")
def start_session(req: StartRequest) -> dict[str, Any]:
    """Begin or resume a student. New students are diagnosed before being taught."""
    language_spec = _language_or_400(req.language)
    student_id = student_id_from_name(req.name)
    if not student_id:
        raise HTTPException(422, "name must contain at least one letter or digit")

    store = StudentStore()
    is_new = store.ensure_student(student_id)
    if is_new:
        seed_student(store, student_id)

    events = EventLog()
    deps = GraphDeps(store, events)
    deps.retriever = Retriever()
    session = Session(
        student_id=student_id,
        display_name=req.name.strip(),
        store=store,
        events=events,
        graph=build_graph(deps),
        cfg={"configurable": {"thread_id": f"api-{student_id}"}},
        diagnostic=(
            DiagnosticSession(graph=SkillGraph.from_yaml(SKILLS_CONFIG)) if is_new else None
        ),
        language=language_spec.language.value,
    )
    SESSIONS[student_id] = session

    return {
        "student_id": student_id,
        "returning": not is_new,
        "needs_diagnostic": is_new,
        "target_skill": req.target_skill,
        "language": {"value": language_spec.language.value, "label": language_spec.label},
    }


@app.get("/session/{student_id}/diagnostic")
def diagnostic_question(student_id: str) -> dict[str, Any]:
    """The next probe, or the finished profile once there is nothing left to ask."""
    session = _session(student_id)
    if session.diagnostic is None:
        return {"complete": True, "reason": "already diagnosed"}

    question = session.diagnostic.next_question()
    if question is None:
        nodes, result = session.diagnostic.finish(MASTERY_THRESHOLD)
        session.store.save_skills(student_id, nodes)
        session.diagnostic = None
        return {
            "complete": True,
            "weakest_skill": result.target_skill,
            "missing_prerequisites": result.missing_prerequisites,
            "confidence": result.confidence,
            "mastery": {s: n.mastery for s, n in nodes.items()},
            "evidence": result.evidence,
        }

    return {
        "complete": False,
        "skill": question.skill,
        "prompt": question.prompt,
        "starter_code": question.starter_code,
        "answered": len(session.diagnostic.answered),
        "skipped": dict(session.diagnostic.skipped),
    }


@app.post("/session/{student_id}/diagnostic")
def diagnostic_answer(student_id: str, answer: DiagnosticAnswer) -> dict[str, Any]:
    """Grade one diagnostic answer by running it, exactly as a real exercise is graded."""
    session = _session(student_id)
    if session.diagnostic is None:
        raise HTTPException(409, "diagnostic already complete")

    question = next(
        (q for q in [session.diagnostic.next_question()] if q and q.skill == answer.skill),
        None,
    )
    if question is None:
        raise HTTPException(409, f"{answer.skill!r} is not the question currently being asked")

    suite = run_test_cases(session._sandbox, answer.code, question.as_problem()["test_cases"])
    outcome = StudentOutcome.CORRECT if suite.all_passed else StudentOutcome.WRONG_ANSWER
    session.diagnostic.record(answer.skill, outcome)
    return {"skill": answer.skill, "correct": suite.all_passed}


@app.post("/session/{student_id}/start")
def begin_tutoring(student_id: str, req: StartRequest) -> dict[str, Any]:
    """Run the graph until it suspends waiting for the student."""
    session = _session(student_id)
    language_spec = _language_or_400(req.language or session.language)
    session.language = language_spec.language.value

    # The one place grounding is actually about to be used. Waiting here on a cold
    # container is a slower first problem; NOT waiting is an ungrounded one, and an
    # ungrounded problem is indistinguishable from a grounded one until a judge asks
    # which page it came from.
    INDEX_READY.wait(timeout=180)

    session.state = session.graph.invoke(
        initial_state(
            student_id,
            f"api-{student_id}",
            target_skill=req.target_skill,
            language=language_spec.language,
        ),
        session.cfg,
    )
    return _view(session)


@app.post("/session/{student_id}/submit")
def submit(student_id: str, req: SubmitRequest) -> dict[str, Any]:
    """Resume the suspended graph with the student's code."""
    session = _session(student_id)
    session.state = session.graph.invoke(Command(resume={"code": req.code}), session.cfg)
    return _view(session)


@app.get("/session/{student_id}")
def current(student_id: str) -> dict[str, Any]:
    return _view(_session(student_id))


@app.post("/session/{student_id}/hints")
def hints(student_id: str, req: SubmitRequest) -> dict[str, Any]:
    """The hint ladder for whatever the student is stuck on, strongest last.

    Takes their draft, because an unfinished attempt says more about where they are
    stuck than the skill name does. Purely a read: asking for help submits nothing,
    moves no mastery, and does not advance the graph -- a student who is afraid that
    asking will cost them something will not ask.
    """
    session = _session(student_id)
    snapshot = session.graph.get_state(session.cfg)
    skill = str(snapshot.values.get("target_skill") or "")
    # The difficulty matters as much as the skill. Without it, an EASY base-case
    # exercise and a HARD divide-and-conquer one got the same two sentences, which is
    # what a student noticed and reported.
    difficulty = str(snapshot.values.get("difficulty_level") or "") or None
    ladder = hints_for(skill, req.code or None, difficulty)
    return {"skill": skill, "difficulty": difficulty, "hints": list(ladder)}


@app.get("/student/{student_id}/plan")
def learning_plan(student_id: str) -> dict[str, Any]:
    """The learning plan: every skill, its state, and what it is waiting on.

    The STATE is decided here rather than in a client. Whether a skill is locked is a
    prerequisite judgement, and prerequisite judgements are the entire subject of this
    system -- a frontend recomputing them would be a second, silently diverging
    implementation of the one thing that must not have two.
    """
    store = StudentStore()
    if not store.exists(student_id):
        raise HTTPException(404, f"no student {student_id!r}")

    nodes = store.load_skills(student_id)
    graph = SkillGraph(nodes)
    plan: list[dict[str, Any]] = []
    for name in sorted(nodes):
        node = nodes[name]
        # Locking is a routing judgement about PREREQUISITES and stays mastery-only,
        # exactly as the graph and the policy guard compute it. Confidence belongs in the
        # question below it -- "has this student finished this?" -- not here, or a
        # student would be shut out of a topic because the tutor is unsure about
        # something upstream, which is the tutor's problem and not theirs.
        blocking = graph.unmastered_prerequisites(name, MASTERY_THRESHOLD)

        if is_mastered(node.mastery, node.confidence):
            state = "completed"
        elif node.mastery >= MASTERY_THRESHOLD:
            # Answered well, but on thin evidence. Checked BEFORE `locked` on purpose:
            # this student has shown the skill, and the estimate is about them. Refusing
            # them a topic they just got right, because something upstream is unproven,
            # would be the tutor arguing with its own observation.
            state = "provisional"
        elif blocking:
            state = "locked"
        else:
            state = "available"
        plan.append(
            {
                "skill": name,
                "state": state,
                "mastery": round(node.mastery, 4),
                "confidence": round(node.confidence, 4),
                "attempts": node.attempts,
                "prerequisites": graph.prerequisites(name),
                "blocked_by": blocking,
                "unlocks": graph.dependents(name),
                "misconceptions": node.misconceptions,
                "overcome": node.resolved_misconceptions,
            }
        )

    # Where a student should go next: the weakest thing they can actually start. Not the
    # weakest overall, which is usually something locked three prerequisites deep.
    suggested = weakest_startable(nodes, MASTERY_THRESHOLD)

    return {
        "student_id": student_id,
        "suggested_next": suggested,
        "counts": {
            "total": len(plan),
            "done": sum(1 for i in plan if i["state"] == "completed"),
            # Reported separately rather than folded into either side. A quiz that leaves
            # five topics looking fine on one answer each has told the student something
            # real, and burying that in "upcoming" throws it away -- but calling it
            # "done" is the overclaim this state exists to stop.
            "provisional": sum(1 for i in plan if i["state"] == "provisional"),
            # The three counts PARTITION the total, so they can be read side by side and
            # add up. Before "provisional" existed, upcoming meant "not completed" and
            # that was the same thing; with a third state it silently started counting
            # the middle bucket twice -- 0 done, 3 looking good, 8 upcoming, out of 8.
            "upcoming": sum(
                1 for i in plan if i["state"] not in ("completed", "provisional")
            ),
        },
        "skills": plan,
    }


@app.get("/student/{student_id}/activity")
def activity(student_id: str, days: int = 120) -> dict[str, Any]:
    """Every attempt's timestamp, for a study-activity heatmap.

    Returns RAW UTC timestamps rather than day or hour buckets, and that is the whole
    design decision here. "When do I study?" is a question about the student's own
    clock -- someone in IST doing an exercise at 9pm local is at 15:30 UTC, and a
    server-side hourly bucket would file it under afternoon and quietly tell them they
    study in the afternoon. Only the browser knows the offset, so only the browser may
    bucket. The server's job is to hand over correct instants.

    Volume is not a concern at this scale: a student has tens of attempts, not
    thousands, and `days` bounds it regardless.
    """
    store = StudentStore()
    if not store.exists(student_id):
        raise HTTPException(404, f"no student {student_id!r}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    rows = []
    for row in store.attempts_for(student_id):
        try:
            when = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            # A row we cannot place in time cannot go on a calendar. Skipping it is
            # right; guessing a date for it would be inventing study history.
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < cutoff:
            continue
        rows.append(
            {
                "at": when.isoformat(),
                "skill": row["skill"],
                "outcome": row["outcome"],
                "correct": row["outcome"] == StudentOutcome.CORRECT.value,
            }
        )

    return {
        "student_id": student_id,
        "days": days,
        "since": cutoff.isoformat(),
        "attempts": rows,
        "total": len(rows),
    }


@app.get("/student/{student_id}/progress")
def progress(student_id: str) -> dict[str, Any]:
    """Durable state, readable without an active session -- this is the dashboard."""
    store = StudentStore()
    if not store.exists(student_id):
        raise HTTPException(404, f"no student {student_id!r}")
    nodes = store.load_skills(student_id)
    attempts = store.attempts_for(student_id)
    return {
        "student_id": student_id,
        "overall_mastery": (
            sum(n.mastery for n in nodes.values()) / len(nodes) if nodes else 0.0
        ),
        "skills": [
            {
                "skill": name,
                # Same word, same predicate, same authority as the learning plan. A
                # client deciding for itself whether 0.85-at-0.22 counts as mastered is
                # how the plan came to award five "Completed" topics the guard would not
                # have advanced on -- and two screens disagreeing about one student is
                # worse than either being wrong alone.
                #
                # "locked" is absent on purpose: that is a routing judgement about what
                # to do next, and this screen answers a different question -- what the
                # tutor believes, which does not depend on where the student may go.
                "state": (
                    "completed"
                    if is_mastered(node.mastery, node.confidence)
                    else "provisional"
                    if node.mastery >= MASTERY_THRESHOLD
                    else "unproven"
                ),
                "mastery": node.mastery,
                "confidence": node.confidence,
                "attempts": node.attempts,
                "misconceptions": node.misconceptions,
                "overcome": node.resolved_misconceptions,
            }
            for name, node in sorted(nodes.items(), key=lambda kv: kv[1].mastery)
        ],
        "recent_attempts": [
            {
                "skill": row["skill"],
                "outcome": row["outcome"],
                "mastery_before": row["mastery_before"],
                "mastery_after": row["mastery_after"],
                "at": row["created_at"],
            }
            for row in attempts[-10:][::-1]
        ],
        "total_attempts": len(attempts),
    }
