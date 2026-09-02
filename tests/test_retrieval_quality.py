"""Retrieval quality gates and the guard-override metric.

Retrieval failures are invisible: something always comes back and it always looks
plausible. These tests turn "the retrieval seems fine" into a number that fails loudly
when the corpus or the chunker regresses.
"""

from __future__ import annotations

import pytest

from eval.retrieval_eval import CASES, evaluate, evaluate_by_kind


@pytest.fixture(scope="module")
def result():
    return evaluate()


def test_the_right_section_always_reaches_the_model(result) -> None:
    """recall@k is the metric that actually matters here.

    The model sees all k retrieved chunks, so a correct chunk sitting at rank 3 is just
    as usable as one at rank 1. This is precisely why a reranker was measured and then
    NOT built: reranking reorders within the retrieved set, and the right chunk is
    already always in it.
    """
    assert result.recall_at_k == 1.0, (
        f"{len(result.misses)} case(s) never surfaced the expected section: "
        f"{[c.query[:40] for c in result.misses]}"
    )


def test_top_hit_is_usually_correct(result) -> None:
    assert result.recall_at_1 >= 0.85, f"recall@1 regressed to {result.recall_at_1:.2f}"
    assert result.mrr >= 0.90, f"MRR regressed to {result.mrr:.3f}"


def test_misconception_retrieval_is_held_to_the_same_bar() -> None:
    """A misconception miss is the more expensive failure.

    The diagnoser has already worked out what is wrong; fetching the wrong passage
    wastes that work and teaches the student something they did not need.
    """
    by_kind = evaluate_by_kind()
    assert by_kind["misconception"].recall_at_k == 1.0
    assert by_kind["remediation"].recall_at_k == 1.0


def test_the_benchmark_covers_every_skill() -> None:
    """A benchmark that skips skills would hide exactly the regressions it exists for."""
    from pathlib import Path

    from app.mastery.skill_graph import SkillGraph

    skills = set(SkillGraph.from_yaml(Path("app/config/skills.yaml")).nodes)
    covered = {c.skill for c in CASES}
    assert not skills - covered, f"benchmark has no case for {sorted(skills - covered)}"


def test_the_benchmark_covers_every_misconception_target() -> None:
    from app.mastery.misconceptions import PATTERNS

    implicated = {p.prerequisite_hint for p in PATTERNS if p.prerequisite_hint}
    covered = {c.skill for c in CASES if c.kind == "misconception"}
    missing = implicated - covered - {"recursion"}  # recursion is covered by a remediation case
    assert not missing, f"no misconception case for implicated skills: {sorted(missing)}"


# ------------------------------------------------------- guard override
def test_guard_override_metric_is_exposed_and_coherent() -> None:
    """The override rate is the ablation headline; it must be reportable, not ad hoc."""
    from app.rag.retriever import Retriever
    from app.services.demo_runner import Behaviour, run_demo
    from app.services.events import EventLog
    from app.services.student_store import StudentStore

    result = run_demo(
        store=StudentStore(":memory:"),
        events=EventLog(),
        retriever=Retriever(),
        behaviours=[Behaviour.FAIL_RUNTIME, Behaviour.FAIL_WRONG, Behaviour.SUCCEED,
                    Behaviour.SUCCEED, Behaviour.SUCCEED],
        thread_id="override-metric",
    )

    assert result.adaptation_count > 0
    assert 0.0 <= result.override_rate <= 1.0
    assert len(result.guard_overrides) <= result.adaptation_count
    # every override must name the rule it enforced -- an unexplained override is
    # indistinguishable from a bug
    for payload in result.guard_overrides:
        assert payload.get("violated"), "an override recorded no violated rule"
        assert payload.get("proposed") and payload.get("final")


def test_offline_runs_report_zero_overrides_honestly() -> None:
    """With no provider the model is a stub, so there is nothing to overrule.

    A zero here is a fact about the run, not evidence the guard is inert -- the live
    path exercises it. Pinned so nobody later mistakes the zero for a broken guard.
    """
    from app.rag.retriever import Retriever
    from app.services.demo_runner import Behaviour, run_demo
    from app.services.events import EventLog
    from app.services.student_store import StudentStore

    result = run_demo(
        store=StudentStore(":memory:"),
        events=EventLog(),
        retriever=Retriever(),
        behaviours=[Behaviour.FAIL_RUNTIME, Behaviour.FAIL_WRONG],
        thread_id="override-offline",
        live=False,
    )
    assert result.override_rate == 0.0
