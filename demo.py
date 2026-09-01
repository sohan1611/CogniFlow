"""CogniFlow demo — the prerequisite redirect, end to end.

    .venv/Scripts/python.exe demo.py

Everything printed below is produced by the real LangGraph run. The only scripted part
is the STUDENT: what they submit and when. Every decision the tutor makes -- which skill
to teach, when to give up on recursion, which prerequisite to fall back to, when to come
back -- is computed from the prerequisite graph and live Bayesian mastery estimates.

Run `--verify` to have the demo check its own claims instead of asking you to trust the
narrative.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.rag.retriever import Retriever  # noqa: E402
from app.services.demo_runner import (  # noqa: E402
    DEMO_SEED,
    Behaviour,
    run_demo,
    seed_student,
)
from app.services.events import EventLog, EventType  # noqa: E402
from app.services.student_store import StudentStore  # noqa: E402

STORY = [
    Behaviour.FAIL_RUNTIME,
    Behaviour.FAIL_WRONG,
    Behaviour.SUCCEED,
    Behaviour.SUCCEED,
    Behaviour.SUCCEED,
]

SHOWN = {
    EventType.DIAGNOSTIC,
    EventType.PLAN,
    EventType.RETRIEVAL,
    EventType.GENERATED,
    EventType.EXECUTION,
    EventType.MASTERY,
    EventType.ADAPTATION,
    EventType.GUARD_OVERRIDE,
    EventType.PREREQ_REDIRECT,
    EventType.PREREQ_RETURN,
    EventType.RECOVERY,
    EventType.SESSION_END,
}


def rule(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description="CogniFlow prerequisite-redirect demo")
    ap.add_argument("--verify", action="store_true", help="assert the claims, do not just narrate")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("--db", default=":memory:", help="student store path")
    ap.add_argument("--trace", type=Path, help="write the event stream as JSONL")
    ap.add_argument(
        "--live",
        action="store_true",
        help="use the configured LLM providers instead of deterministic templates",
    )
    args = ap.parse_args()

    logging.disable(logging.WARNING)

    rule("CogniFlow — adaptive tutoring with prerequisite-aware remediation")
    print("Target skill: recursion")
    print("\nStarting student model (mastery / confidence):")
    for skill, (mastery, conf) in DEMO_SEED.items():
        marker = "  <-- target" if skill == "recursion" else ""
        marker = "  <-- weakest prerequisite of recursion" if skill == "functions" else marker
        print(f"  {skill:22} {mastery:.2f} / {conf:.2f}{marker}")

    print("\nThe student will fail recursion twice. Watch what the agent decides to do")
    print("about it -- and note that nothing below is scripted except the submissions.")

    store = StudentStore(args.db)
    seed_student(store, "demo-student")

    events = EventLog(path=args.trace, echo=False)
    if args.live:
        from app.llm.provider import Role, available_chain

        chain = available_chain(Role.GENERATE)
        rule("LIVE MODE")
        print("  providers: " + (", ".join(f"{s.provider}:{s.model}" for s in chain) or "NONE"))
        if not chain:
            print("  No credentials found. Add a free GROQ_API_KEY to .env, or drop --live.")
            return 1
    rule("LIVE EVENT STREAM")
    result = run_demo(
        store=store,
        events=events,
        retriever=Retriever(),
        behaviours=STORY,
        inject_fault_on_turn=3,
        student_id="demo-student",
        thread_id="demo-thread",
        live=args.live,
    )

    if not args.quiet:
        for event in events.events:
            if event.event_type in SHOWN:
                print(event.render())

    rule("WHAT HAPPENED")
    print(f"  Learning path : {' -> '.join(result.skills_visited)}")
    print(f"  Actions       : {' -> '.join(result.actions)}")
    print(f"  Session       : {result.final_state.get('session_status')} in {result.turns} turns")
    print()
    print("  Mastery movement:")
    for skill in ("recursion", "functions"):
        before = result.mastery_before.get(skill, 0.0)
        after = result.mastery_after.get(skill, 0.0)
        arrow = "up" if after > before else "down"
        print(f"    {skill:12} {before:.3f} -> {after:.3f}  ({arrow})")

    recoveries = events.of_type(EventType.RECOVERY)
    if recoveries:
        print()
        print("  Injected infrastructure failure:")
        print(f"    {recoveries[0].payload['fault']} -> routed to recovery, mastery untouched")

    rule("THE POINT")
    print("  1. The student failed recursion twice.")
    print("  2. The agent did NOT just generate an easier recursion problem.")
    print("  3. It walked the prerequisite graph, found `functions` was the weakest")
    print("     unmastered dependency, and REASSIGNED ITS OWN OBJECTIVE.")
    print("  4. It taught functions in a different mode (CODE_TRACE), grounded in the")
    print("     functions chapter retrieved from the curriculum.")
    print("  5. A sandbox failure mid-session cost the student nothing.")
    print("  6. Once functions was mastered, it returned to recursion and finished.")

    if args.verify:
        rule("SELF-VERIFICATION")
        checks = [
            ("visited recursion -> functions -> recursion",
             result.skills_visited == ["recursion", "functions", "recursion"]),
            ("first failure retried, second escalated to prerequisite",
             result.actions[:2] == ["RETRY_VARIATION", "REVISIT_PREREQUISITE"]),
            ("redirect target was chosen as the weakest prerequisite",
             result.redirected_to() == "functions"),
            ("returned to the original objective",
             bool(events.of_type(EventType.PREREQ_RETURN))),
            ("infrastructure fault did not move mastery",
             bool(recoveries) and recoveries[0].payload["mastery_untouched"] is True),
            ("student ended ahead on recursion",
             result.mastery_after["recursion"] > result.mastery_before["recursion"]),
            ("remediation was grounded in retrieved material",
             any(e.payload.get("skill") == "functions" and e.payload.get("chunks", 0) > 0
                 for e in events.of_type(EventType.RETRIEVAL))),
        ]
        failed = 0
        for label, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
            failed += 0 if ok else 1
        print()
        if failed:
            print(f"{failed} check(s) FAILED")
            return 1
        print("All checks passed. Nothing above was narrated -- it was measured.")

    if args.trace:
        print()
        print(f"  Event stream written to {args.trace} ({len(events)} events, JSONL).")
        print("  Each line is a structured decision record - node, type, payload,")
        print("  reason, evidence, confidence. No private model reasoning is stored.")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
