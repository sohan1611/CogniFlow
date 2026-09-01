"""Plan requirement 18: the recursion -> functions adaptation, through the real graph.

These assertions are deliberately made against the EVENT STREAM and the DURABLE STORE,
not against printed text. A hardcoded narration could never satisfy them: the redirect
has to be produced by prerequisite-graph traversal over live mastery estimates, the
mastery numbers have to come from BKT, and the return has to come from popping the
return stack.

This is also the exact code path `demo.py` runs, so what judges watch is what CI checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.retriever import Retriever
from app.services.demo_runner import DEMO_SEED, Behaviour, run_demo, seed_student
from app.services.events import EventLog, EventType
from app.services.student_store import StudentStore

FULL_RUN = [
    Behaviour.FAIL_RUNTIME,
    Behaviour.FAIL_WRONG,
    Behaviour.SUCCEED,
    Behaviour.SUCCEED,
    Behaviour.SUCCEED,
]


@pytest.fixture(scope="module")
def demo():
    """One full run, shared across assertions (it is deterministic)."""
    events = EventLog()
    result = run_demo(
        store=StudentStore(":memory:"),
        events=events,
        retriever=Retriever(),
        behaviours=FULL_RUN,
        inject_fault_on_turn=3,
    )
    return result


# ------------------------------------------------------------- the premise
def test_seed_makes_functions_the_genuine_weakest_prerequisite() -> None:
    """The demo must not depend on an unseeded default.

    weakest_prerequisite ranks on mastery * confidence. If `conditionals` were left at
    the YAML default it would score 0.15 against functions' 0.33 and the agent would
    correctly pick conditionals -- making the script wrong, not the agent.
    """
    from app.mastery.skill_graph import SkillGraph

    store = StudentStore(":memory:")
    nodes = seed_student(store, "s")
    graph = SkillGraph(nodes)

    assert graph.unmastered_prerequisites("recursion") == ["functions"]
    assert graph.weakest_prerequisite("recursion") == "functions"

    cond = DEMO_SEED["conditionals"]
    func = DEMO_SEED["functions"]
    assert cond[0] * cond[1] > func[0] * func[1], "conditionals must not be the weaker link"


# --------------------------------------------------- TEST 18: the redirect
def test_18_visits_recursion_then_functions_then_returns_to_recursion(demo) -> None:
    """The headline claim, asserted on real planning events."""
    assert demo.skills_visited == ["recursion", "functions", "recursion"], demo.skills_visited


def test_18_redirect_is_caused_by_repeated_failure_not_by_a_script(demo) -> None:
    redirects = demo.events.of_type(EventType.PREREQ_REDIRECT)
    assert len(redirects) == 1
    event = redirects[0]
    assert event.payload["from_skill"] == "recursion"
    assert event.payload["to_skill"] == "functions"
    assert "prerequisite" in (event.decision_reason or "").lower()


def test_18_action_sequence_matches_the_intended_pedagogy(demo) -> None:
    """First failure retries; the SECOND triggers a prerequisite investigation."""
    actions = demo.actions
    assert actions[0] == "RETRY_VARIATION", actions
    assert actions[1] == "REVISIT_PREREQUISITE", actions
    assert actions[-1] == "COMPLETE", actions


def test_18_returns_to_the_original_objective(demo) -> None:
    returns = demo.events.of_type(EventType.PREREQ_RETURN)
    assert returns, "never returned to the original target"
    assert returns[0].payload["returning_to"] == "recursion"


def test_18_teaching_mode_changes_on_remediation(demo) -> None:
    """Remediating a prerequisite should not repeat the approach that already failed."""
    plans = demo.events.of_type(EventType.PLAN)
    functions_plans = [p for p in plans if p.payload.get("target_skill") == "functions"]
    assert functions_plans
    assert functions_plans[0].payload["teaching_mode"] == "CODE_TRACE"


def test_18_remediation_is_grounded_in_functions_material(demo) -> None:
    """RAG must fetch the FUNCTIONS chapter for the functions detour."""
    retrievals = demo.events.of_type(EventType.RETRIEVAL)
    functions_retrieval = [
        r for r in retrievals if r.payload.get("skill") == "functions"
    ]
    assert functions_retrieval, "no retrieval for the remediation skill"
    citations = functions_retrieval[0].evidence
    assert citations, "retrieval returned no citations"
    assert any("functions" in c for c in citations), citations


# ------------------------------------------- mastery actually moved, via BKT
def test_18_mastery_falls_on_failure_and_recovers_after_remediation(demo) -> None:
    mastery_events = demo.events.of_type(EventType.MASTERY)
    recursion = [e for e in mastery_events if e.payload["skill"] == "recursion"]
    functions = [e for e in mastery_events if e.payload["skill"] == "functions"]

    assert recursion[0].payload["after"] < recursion[0].payload["before"], "failure must cost"
    assert functions[-1].payload["after"] > functions[-1].payload["before"]
    assert demo.mastery_after["recursion"] > demo.mastery_before["recursion"], (
        "the student should end ahead of where they started on the original skill"
    )


# ------------------------------------- the infrastructure-failure beat
def test_18_injected_sandbox_failure_does_not_touch_mastery(demo) -> None:
    """The fault is real, routed through the graph, and costs the student nothing."""
    recoveries = demo.events.of_type(EventType.RECOVERY)
    assert recoveries, "the injected fault never reached the recovery node"
    assert recoveries[0].payload["fault"] == "SANDBOX_FAILURE"
    assert recoveries[0].payload["mastery_untouched"] is True

    # No mastery event may sit between the sandbox_error execution and the recovery.
    order = [
        e for e in demo.events.events
        if e.event_type in (EventType.EXECUTION, EventType.MASTERY, EventType.RECOVERY)
    ]
    for i, event in enumerate(order):
        if event.event_type is EventType.EXECUTION and event.payload.get("outcome") == "SANDBOX_FAILURE":
            assert order[i + 1].event_type is EventType.RECOVERY, (
                "a sandbox failure was followed by something other than recovery"
            )
            break
    else:
        pytest.fail("no SANDBOX_FAILURE execution event found")


def test_18_session_completes_cleanly(demo) -> None:
    assert demo.final_state["session_status"] == "COMPLETED"
    assert demo.turns < 12, "session should converge, not run to the turn cap"


def test_18_completion_reason_reports_mastery_not_a_bare_limit(demo) -> None:
    """A session ending at high mastery must not read like a failure."""
    adaptations = demo.events.of_type(EventType.ADAPTATION)
    assert "mastered" in (adaptations[-1].decision_reason or "").lower()


# --------------------------------------------------------- reproducibility
def test_demo_is_deterministic_across_runs() -> None:
    """Two identical runs must produce identical paths -- this is what makes the live
    demo safe to perform, and what lets CI assert on it at all."""
    runs = []
    for i in range(2):
        events = EventLog()
        runs.append(
            run_demo(
                store=StudentStore(":memory:"),
                events=events,
                retriever=Retriever(),
                behaviours=FULL_RUN,
                inject_fault_on_turn=3,
                thread_id=f"determinism-{i}",
            )
        )
    assert runs[0].skills_visited == runs[1].skills_visited
    assert runs[0].actions == runs[1].actions
    assert runs[0].mastery_after == runs[1].mastery_after
