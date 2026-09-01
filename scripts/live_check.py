"""One live call per configured provider, to verify the real wire format.

The offline test suite proves the recovery logic (retry, repair, failover, caching)
without spending anything. What it CANNOT prove is that our request shape is accepted
by the real API -- structured output, adaptive thinking, and the deliberate absence of
sampling parameters are all things a stub will happily accept and a provider might not.

Run this once whenever credentials change, and before any live demo:

    .venv/Scripts/python.exe scripts/live_check.py

Costs a handful of tokens. Exits non-zero if a configured provider fails.
Providers without credentials are skipped, not failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from app.llm.provider import Role, build_caller, default_chain  # noqa: E402
from app.llm.structured import LLMClient  # noqa: E402


class SkillCheck(BaseModel):
    """Deliberately mirrors the shape the real agents ask for."""

    skill: str = Field(description="the single programming skill being described")
    difficulty: str = Field(description="one of EASY, MEDIUM, HARD")
    one_line_summary: str = Field(description="a single sentence, under 20 words")


PROMPT = [
    {
        "role": "user",
        "content": (
            "A student cannot work out why their recursive function returns None. "
            "Identify the single skill most likely missing, rate its difficulty, "
            "and summarise the gap in one sentence."
        ),
    }
]


def main() -> int:
    failures = 0
    checked = 0

    for spec in default_chain(Role.ANALYZE):
        label = f"{spec.provider}:{spec.model}"
        if not spec.available():
            print(f"  [SKIP] {label} -- {spec.api_key_env} not set")
            continue

        checked += 1
        caller = build_caller(spec)
        client = LLMClient(Role.ANALYZE, [caller], cache=None)
        outcome = client.call_structured(SkillCheck, PROMPT)

        if outcome.ok and outcome.value is not None:
            v = outcome.value
            assert isinstance(v, SkillCheck)
            note = " (repaired)" if outcome.repaired else ""
            print(f"  [PASS] {label}{note}")
            print(f"           skill={v.skill!r} difficulty={v.difficulty!r}")
            print(f"           {v.one_line_summary}")
        else:
            failures += 1
            print(f"  [FAIL] {label}")
            print(f"           fault={outcome.fault} attempts={outcome.attempts}")
            print(f"           {outcome.error_message}")

    print()
    if checked == 0:
        print("No provider credentials configured.")
        print()
        print("Add ONE free key to .env and re-run:")
        print("  GROQ_API_KEY    -- free tier at console.groq.com")
        print("  GOOGLE_API_KEY  -- free tier at aistudio.google.com")
        print()
        print("ANTHROPIC_API_KEY also works but is metered pay-per-token, and is billed")
        print("separately from a Claude Pro/Max subscription. It is not required.")
        return 0
    if failures:
        print(f"{failures} of {checked} configured provider(s) FAILED")
        return 1
    print(f"All {checked} configured provider(s) verified against the live API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
