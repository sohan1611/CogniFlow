"""Reproducible demo driver.

Invariant: the demo drives the REAL graph. Nothing here fakes an adaptation, prints a
scripted narrative, or nudges the agent toward a decision. The scripted part is only
the STUDENT -- what they submit and when -- exactly as a real student would be the
unscripted part in a live session.

If the recursion -> functions redirect appears in the output, it is because the
prerequisite graph and live mastery estimates produced it.

This module is shared by `demo.py` and by the end-to-end test, so the thing judges
watch is the thing CI checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.graph.builder import build_graph
from app.graph.deps import GraphDeps
from app.graph.state import initial_state
from app.mastery.skill_graph import SkillGraph
from app.models.enums import SystemFault
from app.models.schemas import SkillNode
from app.services.events import EventLog
from app.services.student_store import StudentStore
from app.tools.sandbox.faults import FaultInjectingSandbox, FaultInjector
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

SKILLS_CONFIG = Path("app/config/skills.yaml")

# The scenario from the project brief. `conditionals` is deliberately HIGH: recursion
# depends on both conditionals and functions, and we want `functions` to be the genuine
# weakest link rather than an artefact of an unseeded default. weakest_prerequisite
# ranks on mastery * confidence, so:
#     conditionals  0.85 * 0.80 = 0.68
#     functions     0.55 * 0.60 = 0.33   <- the gap
DEMO_SEED: dict[str, tuple[float, float]] = {
    "variables": (0.90, 0.85),
    "conditionals": (0.85, 0.80),
    "loops": (0.80, 0.75),
    "functions": (0.55, 0.60),
    "function_call_tracing": (0.45, 0.40),
    "recursion": (0.35, 0.50),
    "recursion_tree": (0.20, 0.30),
    "nested_loops": (0.60, 0.55),
}


class Behaviour(StrEnum):
    """What the scripted student does on a given turn."""

    FAIL_RUNTIME = "fail_runtime"
    FAIL_WRONG = "fail_wrong"
    SUCCEED = "succeed"


@dataclass
class ScriptedStudent:
    """A student whose submissions are decided in advance.

    Being explicit: this scripts the LEARNER, not the tutor. The agent receives real
    execution results and makes its own decisions from them.
    """

    behaviours: list[Behaviour]
    index: int = 0

    def submit(self, problem: dict[str, Any]) -> dict[str, str]:
        behaviour = (
            self.behaviours[self.index]
            if self.index < len(self.behaviours)
            else Behaviour.SUCCEED
        )
        self.index += 1

        if behaviour is Behaviour.FAIL_RUNTIME:
            # A real recursion mistake: no base case, so it blows the stack.
            return {
                "code": (
                    "def factorial(n):\n"
                    "    return n * factorial(n - 1)\n"
                    "print(factorial(5))"
                )
            }
        if behaviour is Behaviour.FAIL_WRONG:
            # Runs cleanly, wrong answer: the classic 'forgot to return the recursive
            # call' error, which is really a FUNCTIONS misunderstanding.
            return {
                "code": (
                    "def total(n):\n"
                    "    if n == 0:\n"
                    "        return 0\n"
                    "    total(n - 1) + n\n"
                    "print(total(3))"
                )
            }
        expected = (problem or {}).get("expected_output", "").strip()
        return {"code": f"print({expected!r})" if expected else "print('done')"}


@dataclass
class DemoResult:
    """Everything a caller needs to assert on, or render."""

    events: EventLog
    final_state: dict[str, Any]
    turns: int
    skills_visited: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    mastery_before: dict[str, float] = field(default_factory=dict)
    mastery_after: dict[str, float] = field(default_factory=dict)

    @property
    def guard_overrides(self) -> list[dict[str, Any]]:
        """Every decision where the deterministic guard overruled the model.

        This is the ablation headline that only exists with a live provider: offline the
        model is a stub, so it proposes nothing to override.
        """
        from app.services.events import EventType

        return [e.payload for e in self.events.of_type(EventType.GUARD_OVERRIDE)]

    @property
    def adaptation_count(self) -> int:
        from app.services.events import EventType

        return len(self.events.of_type(EventType.ADAPTATION))

    @property
    def override_rate(self) -> float:
        """Fraction of adaptation decisions the guard had to correct."""
        return len(self.guard_overrides) / max(self.adaptation_count, 1)

    def violated_rules(self) -> list[str]:
        """Which invariants the model actually tried to breach, in order."""
        out: list[str] = []
        for payload in self.guard_overrides:
            out.extend(str(r) for r in payload.get("violated", []))
        return out

    def redirected_to(self) -> str | None:
        """The skill the agent detoured to, if it detoured at all."""
        from app.services.events import EventType

        hits = self.events.of_type(EventType.PREREQ_REDIRECT)
        return str(hits[0].payload.get("to_skill")) if hits else None


def seed_student(
    store: StudentStore,
    student_id: str,
    seed: dict[str, tuple[float, float]] | None = None,
) -> dict[str, SkillNode]:
    """Install a known starting skill graph."""
    nodes = SkillGraph.from_yaml(SKILLS_CONFIG).nodes
    for skill, (mastery, confidence) in (seed or DEMO_SEED).items():
        if skill in nodes:
            nodes[skill] = nodes[skill].model_copy(
                update={"mastery": mastery, "confidence": confidence, "attempts": 3}
            )
    store.seed(student_id, nodes)
    return nodes


def run_demo(
    *,
    store: StudentStore,
    events: EventLog,
    behaviours: list[Behaviour] | None = None,
    student_id: str = "demo-student",
    thread_id: str = "demo-thread",
    target_skill: str = "recursion",
    retriever: object | None = None,
    inject_fault_on_turn: int | None = None,
    max_turns: int = 12,
    checkpointer: object | None = None,
    live: bool = False,
) -> DemoResult:
    """Run the adaptive loop to completion, feeding scripted submissions.

    `inject_fault_on_turn` queues a SANDBOX_FAILURE before that turn (1-indexed), which
    is how the demo proves an infrastructure failure leaves mastery untouched.

    `live=True` uses the configured providers instead of the offline stub, so problems
    are model-authored rather than templated. The adaptation PATH is unchanged either
    way -- routing is deterministic and the guard validates whatever the model proposes
    -- which is exactly why the demo is safe to run live in front of a jury.
    """
    nodes = seed_student(store, student_id)
    before = {k: v.mastery for k, v in nodes.items()}

    injector = FaultInjector()
    sandbox = FaultInjectingSandbox(SubprocessSandbox(), injector)

    deps = GraphDeps(store=store, events=events) if live else GraphDeps.offline(store, events)
    deps.sandbox = sandbox
    if retriever is not None:
        deps.retriever = retriever  # type: ignore[assignment]

    app = build_graph(deps, checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": thread_id}}

    student = ScriptedStudent(behaviours or [Behaviour.FAIL_RUNTIME, Behaviour.FAIL_WRONG])
    state = app.invoke(initial_state(student_id, thread_id, target_skill=target_skill), cfg)

    turns = 0
    while "__interrupt__" in state and turns < max_turns:
        turns += 1
        if inject_fault_on_turn == turns:
            injector.queue(SystemFault.SANDBOX_FAILURE)

        snapshot = app.get_state(cfg).values
        submission = student.submit(snapshot.get("current_problem") or {})
        state = app.invoke(Command(resume=submission), cfg)

    return DemoResult(
        events=events,
        final_state=dict(state),
        turns=turns,
        skills_visited=events.skills_visited(),
        actions=events.actions(),
        mastery_before=before,
        mastery_after=dict(state.get("mastery_scores", {})),
    )
