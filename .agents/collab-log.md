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
