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

## 2026-09-02 - Work order 2: Phase 2 sandbox (Claude -> Codex -> reviewed)
- Task: sandboxed execution, failure taxonomy, fault injection, classifier, test runner,
  settings factory, plus tests 5-9 and suite-level test 14.
- Codex: delivered 9 modules + 4 test files. Could not run anything, AND could not read
  the Phase 1 files it had to integrate with (same process-spawn block).
- Review: FOUND A REAL DEFECT. Codex imported StudentOutcome / SystemFault /
  is_student_evidence from app.models.errors instead of app.models.enums - it had
  guessed the module layout from the work order because it could not read the files.
  3 test modules failed at collection.
- Fix: Claude corrected the import module in 6 files directly rather than spending a
  round-trip, since Codex cannot read files and would likely repeat the guess.
- PROCESS LESSON: future work orders must INLINE the relevant existing signatures.
  Codex cannot inspect the repo, so any spec that says "read file X first" is unusable.
- Verified independently after the fix:
  * pytest: 79 passed, 1 skipped (docker, correctly skipped)
  * classifier exhaustive over all 12 (status x started) combinations: disjointness
    holds, and `not started` is ALWAYS a SystemFault
  * ambiguous case correct: TIMEOUT+started -> STUDENT_TIMEOUT, TIMEOUT+not-started
    -> SANDBOX_FAILURE
  * SECURITY, empirical canary: parent held sk-ant-SECRET-CANARY, child process read
    None for every KEY/TOKEN/SECRET var. Student code cannot see credentials.
  * capability() honestly reports NO network/memory isolation on Windows subprocess
    rather than claiming isolation it lacks
  * end-to-end demo beat: runtime error 0.3500 -> 0.2036, student infinite loop
    0.2036 -> 0.1763, injected SANDBOX_FAILURE blocked by the type system with mastery
    unchanged at 0.1763
- Verdict: ACCEPTED after the import fix.

## 2026-09-02 - Work order 3: Phase 3 RAG (Claude -> Codex -> reviewed)
- Task: document parsing, heading-aware chunking, Chroma store, ingest, retriever,
  ingest CLI, plus test 12. Spec INLINED all existing signatures (the Phase 2 lesson).
- Codex: delivered 5 rag modules + 2 schemas + CLI + tests. No import mismatch this
  time - inlining the API worked.
- Review found ONE real defect: scripts/ingest_corpus.py failed with
  ModuleNotFoundError: No module named 'app' when run as documented in the README.
  pytest worked (rootdir insertion) but a bare script run did not. A judge following
  the README would have hit this. Claude fixed it with a sys.path bootstrap in the
  script plus a root conftest.py so pytest resolution is explicit rather than
  incidental.
- Verified independently:
  * pytest: 92 passed, 1 skipped
  * chromadb confined to app/rag/store.py; no sentence_transformers anywhere
  * tests use tmp_path and did NOT pollute data/chroma
  * real corpus ingest: 2 docs -> 16 chunks (functions 8, recursion 8)
  * DEMO PATH: query "how does the call stack work..." with skill=functions returns
    "3.4 The call stack" as top hit - the exact material the redirect needs
  * skill filter isolates in BOTH directions ("base case" under recursion vs functions)
  * fallback on unknown skill sets used_fallback=True and still returns results
  * degraded path: a store that raises yields degraded=True + RETRIEVAL_FAILURE and
    does NOT propagate the exception
- Verdict: ACCEPTED after the path-bootstrap fix.
