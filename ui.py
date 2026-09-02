"""CogniFlow web UI.

    .venv/Scripts/python.exe -m streamlit run ui.py

Two modes:

  Watch      replay the scripted prerequisite-redirect scenario, step by step.
  Be the     a real tutoring session where YOU are the student. This exercises the
  student   genuine LangGraph interrupt/resume cycle -- the graph checkpoints and halts
            while you think, and resumes when you submit.

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
from app.rag.retriever import Retriever  # noqa: E402
from app.services.demo_runner import (  # noqa: E402
    DEMO_SEED,
    Behaviour,
    run_demo,
    seed_student,
)
from app.services.events import EventLog, EventType  # noqa: E402
from app.services.student_store import StudentStore  # noqa: E402

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
mode = st.sidebar.radio("Mode", ["Watch the demo", "Be the student"])
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

# =========================================================== interactive mode
else:
    st.title("You are the student")
    st.markdown(
        "This is a real session. The graph **checkpoints and halts** while you think, "
        "then resumes from that checkpoint when you submit."
    )

    if "app" not in st.session_state:
        store = StudentStore(":memory:")
        seed_student(store, "you")
        events = EventLog()
        deps = GraphDeps(store, events) if LIVE else GraphDeps.offline(store, events)
        deps.retriever = Retriever()
        st.session_state.update(
            store=store,
            events=events,
            app=build_graph(deps),
            cfg={"configurable": {"thread_id": "ui-session"}},
            started=False,
            state=None,
        )

    app = st.session_state["app"]
    cfg = st.session_state["cfg"]
    events: EventLog = st.session_state["events"]

    target = st.selectbox("Target skill", list(DEMO_SEED), index=list(DEMO_SEED).index("recursion"))

    if not st.session_state["started"]:
        if st.button("▶ Start session", type="primary"):
            st.session_state["state"] = app.invoke(
                initial_state("you", "ui-session", target_skill=target), cfg
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

                code = st.text_area(
                    "Your code", value=problem.get("starter_code", ""), height=180
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
                    for key in ("app", "started", "state", "events", "store", "cfg"):
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
