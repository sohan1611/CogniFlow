# CogniFlow - Claude <-> Codex collaboration log

Claude is chief (architecture, specs, review). Codex is the implementer.
Newest entries at the bottom. Gists only, never secrets.

## 2026-09-01 22:5x — Work order 1 (Claude → Codex)
- Task: Phase 1 deterministic domain core — enums (StudentOutcome/SystemFault disjoint),
  Pydantic schemas, BKT mastery, skill DAG, rule policy, guard, plus 4 test modules
  covering required tests 1-4 and 17. Explicitly offline: no LLM, no network.
- Codex: (pending — first launch failed on a bad `-m gpt-5.5-codex` override, which the
  ChatGPT-account login rejects; relaunched with `-m gpt-5.5 -c model_reasoning_effort=xhigh`
  matching the user's own config.toml)
- Review: pending Claude verification via pytest.

## 2026-09-01 23:05 — Phase 0 gate VERIFIED (Claude, independently run)
- `scripts/smoke_test.py` exit 0 — ALL PHASE 0 GATES PASSED (13 checks).
- Chroma ONNX embeddings: dim=384, semantic hit + metadata filter both correct.
- LangGraph HITL: paused at ('ask',), checkpointed, resumed, returned '4'.
- PyTorch confirmed absent. All 16 deps installed on Python 3.14.6, no compiler.
- Consequence: the plan's largest risk (3.14 incompatibility) is closed by measurement,
  not assumption. No 3.12 downgrade needed.
- Note for demo prep: Chroma's all-MiniLM-L6-v2 is a ONE-TIME 79 MB download (167 MB on
  disk) that took several minutes on this connection. Pre-warm the cache before any
  live demo or clean-machine run; it is not needed again afterwards.

## 2026-09-01 23:20 - Work order 1 REVIEWED (Claude)
- Codex delivered 12 files (~900 LOC app + tests). It could not run anything
  (CreateProcessAsUserW failed: 5), exactly as the delegation skill predicts.
- Claude ran verification independently:
  * pytest: 61 passed in 0.25s
  * no forbidden imports in app/ (offline confirmed), no TODO/FIXME, no bare except
  * every module carries a docstring naming its invariant
  * BKT math read line-by-line against Corbett & Anderson - correct
- Claude ADDED tests/test_safety_invariant.py (30 adversarial cases, reviewer-authored
  rather than implementer-authored, to avoid circular testing). Notable case: a bare
  string "CORRECT" arriving from a JSON round-trip is correctly rejected, because
  is_student_evidence uses isinstance rather than value comparison.
- Independent demo check: seeded state (functions 0.55 / loops 0.80 / recursion 0.35)
  produces RETRY_VARIATION on failure 1 and REVISIT_PREREQUISITE -> functions on
  failure 2, through real policy code. The redirect is not scripted.
- Verdict: ACCEPTED. Committed as the first commit; contributor check clean.
