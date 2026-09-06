"""CogniFlow web UI.

    .venv/Scripts/python.exe -m streamlit run ui.py

Three modes:

  Watch      replay the scripted prerequisite-redirect scenario, step by step.
  Be the     a real tutoring session where YOU are the student. This exercises the
  student   genuine LangGraph interrupt/resume cycle -- the graph checkpoints and halts
            while you think, and resumes when you submit.
  My progress
            review a named student's durable mastery and recent attempts.

Invariant: this module renders state, it never decides anything. Every adaptation shown
here was produced by the graph. If the UI disappeared, the behaviour would be identical.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.graph.builder import build_graph  # noqa: E402
from app.graph.deps import GraphDeps  # noqa: E402
from app.graph.state import initial_state  # noqa: E402
from app.llm.provider import default_chain  # noqa: E402
from app.mastery.misconceptions import hints_for  # noqa: E402
from app.mastery.policy import MASTERY_THRESHOLD  # noqa: E402
from app.models.enums import StudentOutcome  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402
from app.services.demo_runner import (  # noqa: E402
    DEMO_SEED,
    Behaviour,
    run_demo,
    seed_student,
)
from app.services.events import EventLog, EventType  # noqa: E402
from app.services.student_store import StudentStore, student_id_from_name  # noqa: E402

st.set_page_config(page_title="CogniFlow", page_icon="🎓", layout="wide")


def _bridge_secrets() -> None:
    """Copy Streamlit secrets into the process environment.

    Streamlit Community Cloud supplies secrets through `st.secrets`. The provider chain
    reads `os.environ`, because it must also work from a plain CLI run, a test, and a
    Hugging Face Space. Bridging here means one credential mechanism serves all of them.

    Done explicitly rather than relying on Streamlit mirroring top-level keys into the
    environment: if that ever changed, the app would not error - it would silently fall
    back to templated problems, which is the failure mode this project keeps meeting.
    Existing environment values win, so a local .env still takes precedence.

    Secrets are TOML, so a key pasted under a section header (`[groq]`) arrives nested
    one level down rather than at the top. Both shapes are accepted: a deployment that
    runs on templates because the key was indented is indistinguishable, from the
    outside, from one where the key was never set.
    """
    try:
        secrets = dict(st.secrets)
    except Exception:  # noqa: BLE001 - no secrets file locally is normal, not an error
        return

    flat: dict[str, str] = {}
    for key, value in secrets.items():
        if isinstance(value, str):
            flat[key] = value
        elif hasattr(value, "items"):  # a TOML section, not a scalar
            flat.update({k: v for k, v in value.items() if isinstance(v, str)})

    for key, value in flat.items():
        if not os.environ.get(key):
            os.environ[key] = value


_bridge_secrets()


@st.cache_resource(show_spinner="Building the retrieval index (first run only)…")
def _bootstrap() -> int:
    """Index the corpus if it is not already indexed.

    The index is gitignored, so any host that deploys straight from the repository
    starts without one. Doing this here means `streamlit run ui.py` works on a fresh
    clone rather than failing on empty retrieval -- and retrieval failing SILENTLY is
    exactly the mode this project has already been bitten by once.
    """
    from app.rag.ingest import ingest_corpus
    from app.rag.store import VectorStore

    store = VectorStore()
    if store.count() == 0:
        ingest_corpus(Path("data/knowledge"), store=store)
    return store.count()


_bootstrap()

EVENT_STYLE: dict[EventType, tuple[str, str]] = {
    EventType.DIAGNOSTIC: ("🔍", "#3b82f6"),
    EventType.PLAN: ("🗺️", "#6366f1"),
    EventType.RETRIEVAL: ("📚", "#0891b2"),
    EventType.GENERATED: ("✏️", "#7c3aed"),
    EventType.EXECUTION: ("⚙️", "#64748b"),
    EventType.MISCONCEPTION: ("🧠", "#be185d"),
    EventType.MASTERY: ("📈", "#059669"),
    EventType.ADAPTATION: ("🧭", "#ea580c"),
    EventType.GUARD_OVERRIDE: ("🛡️", "#dc2626"),
    EventType.PREREQ_REDIRECT: ("↩️", "#dc2626"),
    EventType.PREREQ_RETURN: ("↪️", "#16a34a"),
    EventType.RECOVERY: ("🩹", "#d97706"),
    EventType.SESSION_END: ("🏁", "#475569"),
}

HIDDEN = {EventType.SESSION_START, EventType.AWAITING_STUDENT, EventType.SUBMISSION}


def render_event(event) -> None:
    icon, colour = EVENT_STYLE.get(event.event_type, ("•", "#94a3b8"))
    bits = " · ".join(
        f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
        for k, v in event.payload.items()
        if v not in (None, [], {}, "")
    )
    st.markdown(
        f"<div style='border-left:3px solid {colour};padding:.35rem .6rem;margin:.2rem 0;'>"
        f"<strong>{icon} {event.event_type.value}</strong> "
        f"<span style='color:#64748b;font-size:.85em'>{event.node}</span><br>"
        f"<span style='font-size:.85em'>{bits}</span>"
        + (
            f"<br><em style='color:#475569;font-size:.85em'>{event.decision_reason}</em>"
            if event.decision_reason
            else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def mastery_table(scores: dict[str, float], highlight: str | None = None) -> None:
    for skill, value in sorted(scores.items(), key=lambda kv: kv[1]):
        label = f"**{skill}**" if skill == highlight else skill
        st.markdown(
            f"{label} &nbsp; `{value:.3f}`", unsafe_allow_html=True
        )
        st.progress(min(max(value, 0.0), 1.0))


def render_progress_dashboard(store: StudentStore, student_id: str) -> None:
    nodes = store.load_skills(student_id)
    scores = {skill: node.mastery for skill, node in nodes.items()}

    if not scores:
        st.info("No saved starting profile yet — start a session in 'Be the student'.")
        return

    overall = sum(scores.values()) / len(scores)
    attempts = store.attempts_for(student_id)
    practised = store.distinct_skills(student_id)

    top_left, top_right = st.columns(2)
    top_left.metric("Overall mastery", f"{overall:.1%}")
    top_right.metric("Skills practised", len(practised))
    st.metric("Total attempts", len(attempts))

    needs_work = sorted(
        ((skill, value) for skill, value in scores.items() if value < MASTERY_THRESHOLD),
        key=lambda item: item[1],
    )
    strong = sorted(
        ((skill, value) for skill, value in scores.items() if value >= MASTERY_THRESHOLD),
        key=lambda item: item[1],
        reverse=True,
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Needs work")
        if needs_work:
            st.table(
                [
                    {"Skill": skill, "Mastery": f"{value:.2f}"}
                    for skill, value in needs_work
                ]
            )
        else:
            st.caption("No skills below the mastery threshold.")
    with right:
        st.subheader("Strong")
        if strong:
            st.table(
                [
                    {"Skill": skill, "Mastery": f"{value:.2f}"}
                    for skill, value in strong
                ]
            )
        else:
            st.caption("No skills at the mastery threshold yet.")

    st.subheader("Recent activity")
    if not attempts:
        st.info("No attempts recorded yet — start a session in 'Be the student'.")
        return

    recent = list(reversed(attempts))[:10]
    st.table(
        [
            {
                "Skill": row["skill"],
                "Outcome": row["outcome"],
                "Mastery": f"{row['mastery_before']:.2f} -> {row['mastery_after']:.2f}",
            }
            for row in recent
        ]
    )


def tutor_response(values: dict) -> None:
    """What the tutor says to the STUDENT about their last attempt.

    Everything rendered here was already being computed -- the grade, the diagnosed
    misconception, the reason for a detour -- and was previously visible only in the
    event stream, which is written for us rather than for the person being taught. A
    tutor that works out why you are stuck and then does not tell you has not taught
    anybody anything.
    """
    grade = values.get("grader_result") or {}
    if not grade:
        return

    raw = str(values.get("error_type") or "")
    try:
        StudentOutcome(raw)
        student_evidence = True
    except ValueError:
        student_evidence = False

    if not student_evidence:
        # Our failure, not theirs. Say so plainly, and say what it did NOT cost them.
        st.info(
            "⚙️ **Code execution was temporarily unavailable.** Your submission and your "
            "progress have been preserved, and nothing was counted against you."
        )
        return

    if grade.get("passed"):
        st.success("✅ **Correct.**" + (
            f"  Passed every test case (score {grade['score']:.0%})."
            if grade.get("score") else ""
        ))
        return

    feedback = (grade.get("feedback") or "").strip()
    st.warning("**Not quite — but the mistake is a useful one.**")
    if feedback:
        st.markdown(f"> {feedback}")
    if grade.get("failing_case"):
        st.caption(f"First failing case: `{grade['failing_case']}`")


def redirect_explainer(values: dict) -> None:
    """Tell the student WHY they are suddenly being taught something else.

    Without this the prerequisite redirect -- the entire point of the product -- reads
    from the student's side as the tutor changing the subject for no reason.
    """
    stack = values.get("prereq_return_stack") or []
    if not stack:
        return
    original, current = stack[0], values.get("target_skill")
    implicated = None
    for entry in reversed(values.get("detected_misconceptions") or []):
        if entry.get("implicates"):
            implicated = entry["implicates"]
            break

    because = (
        f" Your mistakes on **{original}** point at **{implicated}** rather than at "
        f"{original} itself."
        if implicated else ""
    )
    st.info(
        f"↩️ **Let's back up for a moment.**{because} We're going to work on "
        f"**{current}** first, then go straight back to **{original}** — that is still "
        "what you came here for, and it has not been forgotten."
    )


def path_banner(path: list[str]) -> None:
    if not path:
        return
    st.markdown(
        "### Learning path\n\n" + "  →  ".join(f"`{s}`" for s in path)
    )
    if len(path) >= 3 and path[0] == path[-1]:
        st.success(
            f"The agent left **{path[0]}**, remediated **{path[1]}**, and returned. "
            "That redirect was computed from the prerequisite graph and live mastery "
            "estimates — it is not scripted."
        )


# ---------------------------------------------------------------- sidebar
st.sidebar.title("🎓 CogniFlow")
st.sidebar.caption("Adaptive tutoring with prerequisite-aware remediation")
mode = st.sidebar.radio("Mode", ["Watch the demo", "Be the student", "My progress"])
name = st.sidebar.text_input("Your name", value="", placeholder="e.g. Aarav")
student_id = student_id_from_name(name)
st.sidebar.divider()
st.sidebar.markdown("**Starting model**")
for skill, (mastery, _conf) in DEMO_SEED.items():
    st.sidebar.text(f"{skill:22} {mastery:.2f}")

st.sidebar.divider()
st.sidebar.markdown("**Generation**")
# Whether a model is reachable decides how the graph is built below, so this is a
# live capability check and not decoration. Reporting one thing and doing another is
# how a deployment ends up claiming to be live while running on templates.
_reachable = [s.provider for s in default_chain("generate") if s.available()]
LIVE = bool(_reachable)
if _reachable:
    # The whole chain, not just the leader: with one provider a rate limit ends the
    # live run, with two it fails over. "Is the second key actually configured?" is
    # not answerable from a display that only ever names the first.
    st.sidebar.success("live · " + " → ".join(_reachable))
else:
    st.sidebar.warning("deterministic templates — no provider key configured")
    st.sidebar.caption(
        "Every tutoring decision below is still real: routing, mastery and the "
        "prerequisite redirect are deterministic and need no model. Only the wording "
        "of each problem is templated."
    )


# ================================================================ watch mode
if mode == "Watch the demo":
    st.title("The prerequisite redirect")
    st.markdown(
        "A student fails recursion twice. Watch what the agent decides to do about it. "
        "Only the *student* is scripted — every tutoring decision is computed live."
    )

    if st.button("▶ Run the scenario", type="primary"):
        events = EventLog()
        with st.spinner("Running the real graph…"):
            result = run_demo(
                store=StudentStore(":memory:"),
                events=events,
                retriever=Retriever(),
                behaviours=[
                    Behaviour.FAIL_RUNTIME,
                    Behaviour.FAIL_WRONG,
                    Behaviour.SUCCEED,
                    Behaviour.SUCCEED,
                    Behaviour.SUCCEED,
                ],
                inject_fault_on_turn=3,
                live=LIVE,
            )
        st.session_state["watch"] = (events, result)

    if "watch" in st.session_state:
        events, result = st.session_state["watch"]
        path_banner(result.skills_visited)

        left, right = st.columns([3, 2])
        with left:
            st.subheader("Event stream")
            for event in events.events:
                if event.event_type not in HIDDEN:
                    render_event(event)
        with right:
            st.subheader("Mastery movement")
            for skill in ("recursion", "functions"):
                before = result.mastery_before.get(skill, 0.0)
                after = result.mastery_after.get(skill, 0.0)
                st.metric(skill, f"{after:.3f}", f"{after - before:+.3f}")
            st.divider()
            st.subheader("Final model")
            mastery_table(result.mastery_after, highlight="recursion")
            st.divider()
            if events.of_type(EventType.RECOVERY):
                st.warning(
                    "An infrastructure failure was injected mid-session. It routed to "
                    "recovery and left mastery **untouched** — students never pay for "
                    "our outages."
                )

# =============================================================== progress mode
elif mode == "My progress":
    st.title("My progress")
    if not student_id:
        st.info("Enter your name in the sidebar to see your progress.")
    else:
        progress_store = StudentStore()
        try:
            if not progress_store.exists(student_id):
                st.info(
                    "No progress found for this name yet — start a session in "
                    "'Be the student'."
                )
            else:
                st.caption(f"Student: {name.strip()}")
                render_progress_dashboard(progress_store, student_id)
        finally:
            progress_store.close()

# =========================================================== interactive mode
else:
    st.title("You are the student")
    st.markdown(
        "This is a real session. The graph **checkpoints and halts** while you think, "
        "then resumes from that checkpoint when you submit."
    )

    active_student_id = student_id or "you"
    build_key = f"durable:{active_student_id}" if student_id else "anonymous:you"
    returning_student = False

    if (
        "app" not in st.session_state
        or st.session_state.get("built_for") != build_key
    ):
        old_store = st.session_state.get("store")
        if old_store is not None:
            old_store.close()

        if student_id:
            store = StudentStore()
            is_new = store.ensure_student(active_student_id)
            if is_new:
                seed_student(store, active_student_id)
            returning_student = not is_new
        else:
            store = StudentStore(":memory:")
            seed_student(store, active_student_id)

        thread_id = f"ui-{active_student_id}"
        events = EventLog()
        deps = GraphDeps(store, events) if LIVE else GraphDeps.offline(store, events)
        deps.retriever = Retriever()
        st.session_state.update(
            store=store,
            events=events,
            app=build_graph(deps),
            cfg={"configurable": {"thread_id": thread_id}},
            thread_id=thread_id,
            built_for=build_key,
            returning_student=returning_student,
            started=False,
            state=None,
        )

    store: StudentStore = st.session_state["store"]
    app = st.session_state["app"]
    cfg = st.session_state["cfg"]
    events: EventLog = st.session_state["events"]

    if student_id and st.session_state.get("returning_student"):
        st.success(f"Welcome back, {name.strip()}. Picking up where you left off.")
        attempts = store.attempts_for(active_student_id)
        if attempts:
            st.info(f"Where you left off: **{attempts[-1]['skill']}**.")

    target = st.selectbox(
        "Target skill", list(DEMO_SEED), index=list(DEMO_SEED).index("recursion")
    )

    if not st.session_state["started"]:
        if st.button("▶ Start session", type="primary"):
            st.session_state["state"] = app.invoke(
                initial_state(
                    active_student_id,
                    st.session_state["thread_id"],
                    target_skill=target,
                ),
                cfg,
            )
            st.session_state["started"] = True
            st.rerun()
    else:
        snapshot = app.get_state(cfg)
        pending = snapshot.next
        values = snapshot.values

        left, right = st.columns([3, 2])

        with left:
            if pending:
                problem = values.get("current_problem") or {}
                # The tutor speaks before it sets the next task, in that order, because
                # that is the order a person needs them in: what happened to my last
                # answer, why are we moving, then what am I doing now.
                tutor_response(values)
                redirect_explainer(values)
                st.info(
                    f"⏸ **Graph suspended at `{pending[0]}`** — checkpointed to disk, "
                    "waiting for you."
                )
                st.subheader(problem.get("title", "Your task"))
                st.write(problem.get("prompt", ""))
                if problem.get("grounding_sources"):
                    st.caption("Grounded in: " + ", ".join(problem["grounding_sources"]))
                if problem.get("expected_output"):
                    st.caption(f"Expected output: `{problem['expected_output']}`")

                problem_id = values.get("current_problem_id") or "current"
                hint_count_key = f"hint_count:{problem_id}"
                code_key = f"student_code:{problem_id}"
                hint_ladder = hints_for(
                    str(values.get("target_skill") or ""),
                    st.session_state.get(code_key),
                )
                if st.button(
                    "I'm stuck - give me a hint",
                    key=f"hint_button:{problem_id}",
                ):
                    shown = st.session_state.get(hint_count_key, 0)
                    st.session_state[hint_count_key] = min(
                        shown + 1, len(hint_ladder)
                    )
                hint_count = st.session_state.get(hint_count_key, 0)
                for index, hint in enumerate(hint_ladder[:hint_count], start=1):
                    st.info(f"**Hint {index}.** {hint}")
                if hint_count >= len(hint_ladder):
                    st.info(
                        "That's as much as I can give you without doing it for you - "
                        "have a go, and I'll tell you exactly what went wrong."
                    )

                code = st.text_area(
                    "Your code",
                    value=problem.get("starter_code", ""),
                    height=180,
                    key=code_key,
                )
                if st.button("Submit", type="primary"):
                    st.session_state["state"] = app.invoke(Command(resume={"code": code}), cfg)
                    st.rerun()
            else:
                st.success(
                    f"🏁 Session {values.get('session_status', 'finished')} "
                    f"after {values.get('loop_count', 0)} loops."
                )
                if st.button("Start over"):
                    for key in (
                        "app",
                        "started",
                        "state",
                        "events",
                        "store",
                        "cfg",
                        "thread_id",
                        "built_for",
                        "returning_student",
                    ):
                        st.session_state.pop(key, None)
                    st.rerun()

            st.divider()
            st.subheader("Event stream")
            for event in events.events[-25:]:
                if event.event_type not in HIDDEN:
                    render_event(event)

        with right:
            st.subheader("What the tutor believes")
            mastery_table(values.get("mastery_scores", {}), highlight=values.get("target_skill"))
            st.divider()
            st.markdown(
                f"**Target** `{values.get('target_skill')}`  \n"
                f"**Mode** `{values.get('teaching_mode')}`  \n"
                f"**Difficulty** `{values.get('difficulty_level')}`  \n"
                f"**Consecutive failures** `{values.get('consecutive_failures', 0)}`"
            )
            stack = values.get("prereq_return_stack") or []
            if stack:
                st.warning(
                    "Detoured from " + " → ".join(f"`{s}`" for s in stack)
                    + ". The agent will come back."
                )
            path_banner(events.skills_visited())
