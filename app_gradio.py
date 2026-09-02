"""Gradio UI — the deployable surface.

    python app_gradio.py

Hugging Face Spaces supports `gradio`, `docker` and `static`; the Streamlit SDK was
retired, so the public build uses this while `ui.py` remains the local Streamlit UI.
Both are thin renderers over the same graph: neither decides anything, and if both
disappeared the tutoring behaviour would be identical.

Two tabs:

  Watch          replay the prerequisite-redirect scenario with its event stream.
  Be the student a real session. The graph checkpoints and HALTS while you think, then
                 resumes from that checkpoint when you submit.

Student code passes a static allowlist before any process is created, because this is
reachable by anyone. A refusal is reported and never affects mastery.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Force the restriction gate on before the sandbox is imported. A public deployment must
# not depend on an environment variable being set correctly in order to stay safe.
os.environ["COGNIFLOW_RESTRICT_CODE"] = "1"

import gradio as gr  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.graph.builder import build_graph  # noqa: E402
from app.graph.deps import GraphDeps  # noqa: E402
from app.graph.state import initial_state  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402
from app.services.demo_runner import DEMO_SEED, Behaviour, run_demo, seed_student  # noqa: E402
from app.services.events import EventLog, EventType  # noqa: E402
from app.services.student_store import StudentStore  # noqa: E402
from app.tools.sandbox.restrictions import describe_policy  # noqa: E402

ICONS = {
    EventType.DIAGNOSTIC: "🔍", EventType.PLAN: "🗺️", EventType.RETRIEVAL: "📚",
    EventType.GENERATED: "✏️", EventType.EXECUTION: "⚙️", EventType.MISCONCEPTION: "🧠",
    EventType.MASTERY: "📈", EventType.ADAPTATION: "🧭", EventType.GUARD_OVERRIDE: "🛡️",
    EventType.PREREQ_REDIRECT: "↩️", EventType.PREREQ_RETURN: "↪️",
    EventType.RECOVERY: "🩹", EventType.SESSION_END: "🏁",
}
HIDDEN = {EventType.SESSION_START, EventType.AWAITING_STUDENT, EventType.SUBMISSION}


def render_events(events: EventLog, limit: int = 60) -> str:
    lines: list[str] = []
    for event in events.events[-limit:]:
        if event.event_type in HIDDEN:
            continue
        icon = ICONS.get(event.event_type, "•")
        bits = " · ".join(
            f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
            for k, v in event.payload.items()
            if v not in (None, [], {}, "")
        )
        lines.append(f"{icon} **{event.event_type.value}** `{event.node}`  \n{bits}")
        if event.decision_reason:
            lines.append(f"&nbsp;&nbsp;&nbsp;*{event.decision_reason}*")
    return "\n\n".join(lines) or "_no events yet_"


def mastery_rows(scores: dict[str, float]) -> list[list[Any]]:
    return [[s, round(v, 3)] for s, v in sorted(scores.items(), key=lambda kv: kv[1])]


# ------------------------------------------------------------------ watch
def run_watch() -> tuple[str, str, list[list[Any]]]:
    events = EventLog()
    result = run_demo(
        store=StudentStore(":memory:"),
        events=events,
        retriever=Retriever(),
        behaviours=[Behaviour.FAIL_RUNTIME, Behaviour.FAIL_WRONG, Behaviour.SUCCEED,
                    Behaviour.SUCCEED, Behaviour.SUCCEED],
        inject_fault_on_turn=3,
        thread_id="gradio-watch",
    )

    path = " → ".join(f"`{s}`" for s in result.skills_visited)
    summary = [f"### Learning path\n\n{path}\n"]
    if len(result.skills_visited) >= 3 and result.skills_visited[0] == result.skills_visited[-1]:
        summary.append(
            f"The agent left **{result.skills_visited[0]}**, remediated "
            f"**{result.skills_visited[1]}**, and returned. That redirect was computed "
            "from the prerequisite graph and live mastery estimates — it is not scripted.\n"
        )
    summary.append("**Mastery movement**\n")
    for skill in ("recursion", "functions"):
        before = result.mastery_before.get(skill, 0.0)
        after = result.mastery_after.get(skill, 0.0)
        summary.append(f"- `{skill}` {before:.3f} → **{after:.3f}**")

    if events.of_type(EventType.RECOVERY):
        summary.append(
            "\n**An infrastructure failure was injected mid-session.** It routed to "
            "recovery and left mastery untouched — students never pay for our outages."
        )
    if result.adaptation_count:
        summary.append(
            f"\n**Guard oversight:** {len(result.guard_overrides)} of "
            f"{result.adaptation_count} adaptation decisions overruled."
        )
    return "\n".join(summary), render_events(events), mastery_rows(result.mastery_after)


# ------------------------------------------------------- interactive session
def start_session(target: str) -> tuple[dict, str, str, str, list[list[Any]]]:
    store = StudentStore(":memory:")
    seed_student(store, "you")
    events = EventLog()
    deps = GraphDeps(store=store, events=events)
    deps.retriever = Retriever()
    graph = build_graph(deps)
    cfg = {"configurable": {"thread_id": "gradio-session"}}

    graph.invoke(initial_state("you", "gradio-session", target_skill=target), cfg)
    session = {"graph": graph, "cfg": cfg, "events": events}
    return (session, *_session_view(session))


def submit_code(session: dict | None, code: str) -> tuple[dict | None, str, str, str, list[list[Any]]]:
    if not session:
        return session, "Start a session first.", "", "", []
    session["graph"].invoke(Command(resume={"code": code}), session["cfg"])
    return (session, *_session_view(session))


def _session_view(session: dict) -> tuple[str, str, str, list[list[Any]]]:
    snapshot = session["graph"].get_state(session["cfg"])
    values, pending = snapshot.values, snapshot.next
    events: EventLog = session["events"]

    if pending:
        problem = values.get("current_problem") or {}
        header = [
            f"### ⏸ Graph suspended at `{pending[0]}`",
            "_Checkpointed to disk, waiting for you. It is not looping — it has stopped._\n",
            f"**{problem.get('title', 'Your task')}**\n",
            problem.get("prompt", ""),
        ]
        if problem.get("grounding_sources"):
            header.append(f"\n*Grounded in: {', '.join(problem['grounding_sources'])}*")
        if problem.get("expected_output"):
            header.append(f"\n*Expected output:* `{problem['expected_output']}`")
    else:
        header = [
            f"### 🏁 Session {values.get('session_status', 'finished')}",
            f"after {values.get('loop_count', 0)} loops.",
        ]

    status = (
        f"**Target** `{values.get('target_skill')}` · "
        f"**Mode** `{values.get('teaching_mode')}` · "
        f"**Difficulty** `{values.get('difficulty_level')}` · "
        f"**Consecutive failures** `{values.get('consecutive_failures', 0)}`"
    )
    stack = values.get("prereq_return_stack") or []
    if stack:
        status += (
            "\n\n⚠️ Detoured from " + ", ".join(f"`{s}`" for s in stack)
            + " — the agent will come back."
        )
    return "\n".join(header), status, render_events(events), mastery_rows(values.get("mastery_scores", {}))


# ---------------------------------------------------------------------- app
SEED_TABLE = "\n".join(f"| `{s}` | {m:.2f} | {c:.2f} |" for s, (m, c) in DEMO_SEED.items())

with gr.Blocks(title="CogniFlow", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# 🎓 CogniFlow\n"
        "### An agentic tutor that changes its own objective when it works out *why* you are failing\n\n"
        "A student fails recursion twice. Most AI tutors generate an easier recursion "
        "problem. CogniFlow walks a prerequisite graph, works out the real gap is "
        "`functions`, **reassigns its own teaching objective**, and then comes back.\n\n"
        "[Source, architecture and the measured ablation →](https://github.com/sohan1611/CogniFlow)"
    )

    with gr.Tab("Watch the demo"):
        gr.Markdown(
            "Only the *student* is scripted — what they submit and when. Every tutoring "
            "decision is computed live from the graph."
        )
        watch_btn = gr.Button("▶ Run the scenario", variant="primary")
        with gr.Row():
            with gr.Column(scale=3):
                watch_summary = gr.Markdown()
                watch_events = gr.Markdown(label="Event stream")
            with gr.Column(scale=2):
                watch_mastery = gr.Dataframe(
                    headers=["skill", "mastery"], label="Final student model",
                    interactive=False,
                )
        watch_btn.click(run_watch, outputs=[watch_summary, watch_events, watch_mastery])

    with gr.Tab("Be the student"):
        gr.Markdown(
            "A real session. The graph **checkpoints and halts** while you think, then "
            "resumes from that checkpoint when you submit."
        )
        with gr.Row():
            target = gr.Dropdown(
                choices=list(DEMO_SEED), value="recursion", label="Target skill", scale=2
            )
            start_btn = gr.Button("▶ Start session", variant="primary", scale=1)

        session = gr.State(None)
        with gr.Row():
            with gr.Column(scale=3):
                problem_box = gr.Markdown()
                code_box = gr.Code(label="Your code", language="python", lines=8)
                submit_btn = gr.Button("Submit", variant="primary")
                session_events = gr.Markdown(label="Event stream")
            with gr.Column(scale=2):
                session_status = gr.Markdown()
                session_mastery = gr.Dataframe(
                    headers=["skill", "mastery"], label="What the tutor believes",
                    interactive=False,
                )

        start_btn.click(
            start_session, inputs=[target],
            outputs=[session, problem_box, session_status, session_events, session_mastery],
        )
        submit_btn.click(
            submit_code, inputs=[session, code_box],
            outputs=[session, problem_box, session_status, session_events, session_mastery],
        )

    with gr.Tab("How it works"):
        gr.Markdown(
            "## The architectural spine\n\n"
            "> **The model proposes; the policy guard disposes.**\n\n"
            "An LLM emits a structured adaptation decision. A deterministic guard "
            "validates it against hard invariants and overrides it when invalid, logging "
            "the override. So the model cannot corrupt a learning path, the override rate "
            "is measurable, and the demo path holds even if the model says something odd.\n\n"
            "**Only three of eleven graph nodes call a model.** Diagnosis, routing, "
            "mastery arithmetic and prerequisite selection are deterministic and "
            "unit-tested — we do not use an LLM where arithmetic is already correct and free.\n\n"
            "## The safety invariant\n\n"
            "`StudentOutcome` and `SystemFault` are disjoint types, and mastery is "
            "reachable only from the first. If *our* infrastructure breaks — a sandbox "
            "crash, a model timeout — the student does not pay for it. Enforced by the "
            "type system, not by a conditional someone has to notice.\n\n"
            "## Running your code\n\n"
            f"{describe_policy()}\n\n"
            "## Starting student model\n\n"
            "| skill | mastery | confidence |\n|---|---|---|\n" + SEED_TABLE
        )


# `demo` is imported by deploy/space/app.py, so the Space and local runs share one
# implementation rather than drifting apart.
if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
