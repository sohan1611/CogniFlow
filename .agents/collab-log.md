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

## 2026-09-02 - Phase 4: LLM layer (Claude direct, NOT Codex)
- Codex 5h quota exhausted, so Claude implemented this phase directly.
- Built: errors.py (retryable/permanent/malformed classification by exception class,
  not string matching), cache.py (content-addressed disk replay cache), provider.py
  (role-based chain: Claude primary, Groq/Gemini free-tier backups; lazy construction
  so no credentials are needed to import), stub.py (programmable offline caller),
  structured.py (LLMClient: cache -> repair-once -> retry-with-backoff -> failover ->
  deterministic fallback, and it NEVER raises).
- Verified by Claude: 121 passed, 1 skipped. langchain confined to app/llm/provider.py
  and imported lazily inside _build(). Importing and constructing callers works with
  zero credentials present.
- HONEST GAP: no API key exists on this machine, so the real wire format is UNVERIFIED
  - structured output, adaptive thinking, and the deliberate omission of temperature
  are all things a stub accepts and a live provider might not. Added
  scripts/live_check.py to make that a one-command check the moment a key exists.
  This must be run before any live demo.
- Note: temperature is deliberately never set. Current Claude models reject sampling
  parameters with a 400, and LangChain omits the field when it is None.

## 2026-09-02 - RULE 1 check hardened (Claude)
- The AGENTS.md pre-push grep was FALSE-POSITIVING: `grep -i claude` matched ordinary
  commit prose ("Chain leads with Claude", "current Claude models reject sampling"),
  which are legitimate references to a model, not attribution.
- Why that mattered: a check that cries wolf gets ignored, and an ignored check is
  exactly how a real violation reaches main.
- Replaced with scripts/check_contributors.py, which inspects the fields that actually
  determine authorship: author/committer identity, attribution trailers, tracked bot
  config. Whitelists the root commit's GitHub web-UI committer explicitly (author is
  human, and GitHub attributes by author).
- SELF-TESTED in a throwaway repo: clean commit mentioning Claude -> exit 0;
  Co-Authored-By trailer -> exit 1 and named; dependabot[bot] author -> exit 1 and named.

## 2026-09-02 - Phase 5: LangGraph orchestration (Claude direct)
- Built: state.py (serializable AgentState), events.py (structured CogniEvent stream),
  student_store.py (durable SQLite mastery, write-through), deps.py (dependency
  injection so nodes never build their own collaborators), nodes.py (11 nodes),
  builder.py (conditional edges + three independent loop ceilings + checkpointing).
- REAL BUG FOUND AND FIXED during bring-up: LangGraph warned
  "Deserializing unregistered type app.models.enums.Difficulty ... will be blocked in a
  future version". StrEnum members were reaching the checkpoint via model_dump() and
  direct enum assignment. Fixed by storing plain strings in state and using
  model_dump(mode="json"). Confirmed zero serialization warnings afterwards. Left
  unfixed this would have become a hard failure on a LangGraph upgrade - i.e. exactly
  the kind of thing that breaks a demo after an unrelated dependency bump.
- Verified: 134 passed, 1 skipped.
  * TEST 16 resumes in a genuinely SEPARATE OS PROCESS (subprocess with a cold
    interpreter reading the same SQLite checkpoint) - in-process resume would only
    prove the object stayed in memory.
  * TEST 15 checkpoint survives closing and reopening the saver; pending node preserved.
  * route_evidence checked EXHAUSTIVELY over every StudentOutcome and every SystemFault.
  * injected SANDBOX_FAILURE through real graph routing: mastery unchanged, recovery
    node reached, mastery node never ran, no attempt logged.
- OBSERVATION for Phase 6 tuning (not a bug): a single correct answer moves BKT mastery
  0.50 -> 0.845, which triggers ESCALATE_DIFFICULTY at confidence 0.22. The guard's
  escalate rule checks mastery but not confidence. Pedagogically that is an
  overconfident tutor; worth gating escalation on confidence too.
- OBSERVATION for the demo seed: with conditionals left at the yaml default (0.50/0.30),
  weakest_prerequisite picks CONDITIONALS over FUNCTIONS (0.15 vs 0.33 on
  mastery*confidence). The demo seed must raise conditionals so functions is the
  genuine gap - otherwise the agent is right and the script is wrong.

## 2026-09-02 - Phase 6: full adaptive loop + demo (Claude direct)
- Built: demo_runner.py (reusable driver shared by demo.py AND test_demo_e2e.py, so the
  thing judges watch is the thing CI checks), demo.py (--verify self-checks), Makefile.
- TWO REAL BUGS FOUND BY RUNNING THE DEMO, both invisible to per-branch unit tests:
  1. POLICY ORDERING: ESCALATE_DIFFICULTY was evaluated before the prereq_return_stack
     check, so once the agent mastered `functions` it kept escalating inside functions
     and NEVER returned to recursion. The headline behaviour silently did not happen.
     Fixed by hoisting return-to-original above escalation.
  2. MISLEADING COMPLETION REASON: a session ending at mastery 0.88 reported
     "limit tripped: topic_attempts", which reads as a failure. Now distinguishes
     mastery-achieved from a bare limit trip.
- Also applied the Phase 5 findings: escalation now requires confidence as well as
  mastery (one lucky answer used to push BKT past 0.8 at confidence 0.22), and the demo
  seed raises `conditionals` so `functions` is the genuine weakest prerequisite rather
  than an artefact of an unseeded default.
- Verified: 146 passed, 1 skipped. demo.py --verify passes all 7 self-checks.
  Path: recursion -> functions -> recursion. recursion 0.350 -> 0.877,
  functions 0.550 -> 0.869, injected SANDBOX_FAILURE left mastery untouched.
- test_demo_e2e.py asserts on the EVENT STREAM and DURABLE STORE, never on printed
  text, so a hardcoded narration cannot satisfy it. Includes a determinism test:
  two identical runs must produce identical paths.

## 2026-09-02 - Phase 7: simulator + ablation + BKT fitting (Claude direct)
- Built: eval/simulator.py (latent skills with CAUSAL prerequisite gating and blocked
  learning), eval/ablation.py (3 arms over an identical cohort), eval/bkt_fit.py
  (likelihood fitting + held-out AUC and log-likelihood), scripts/run_ablation.py.
- THREE HARNESS BUGS FOUND AND FIXED, two of which had REVERSED the result:
  1. UNEQUAL BUDGETS: arm A ran 40 steps while arm B stopped at 4-7, because a policy
     returning COMPLETE ended the session. A "won" purely on 6-10x more practice.
     Fixed: every arm now gets exactly max_steps attempts.
  2. THE PRE-TEST WAS TEACHING: two attempts at a prerequisite with learn_rate 0.22
     quietly fixed the planted gap for EVERY arm, so nothing could distinguish them.
     Fixed by adding SimulatedStudent.assess() which measures without learning.
  3. TEST ASSUMPTION WRONG, NOT CODE: deliberately terrible BKT params beat fitted ones
     on AUC. Cause: AUC is rank-invariant and blind to calibration. Now report held-out
     log-likelihood alongside AUC, and the disagreement became a genuine finding.
- HONEST RESULT (80 students/arm, identical cohorts):
    A no-prereq  100% mastered, median 14 steps, 0% gap found,  est err 0.211
    B rules      100% mastered, median 10 steps, 65% gap found, est err 0.106,
                 false redirect 25%
  -> 29% fewer attempts, 65% vs 0% gap detection, half the estimate error, at a real
     25% false-redirect cost which is REPORTED not hidden.
- Arm C == Arm B because no API key: the guarded arm falls back to rules. Stated openly
  in the output rather than glossed.
- BKT FITTING: honest NEGATIVE result. AUC +0.003..+0.006, below the 0.01 adoption
  threshold, so literature defaults are retained. Log-likelihood DID improve (+0.03),
  which explains why: fitting improves calibration, the system depends on ranking.
  This is exactly the commitment made in plan section 16.
- Verified: 162 passed, 1 skipped. Ablation is deterministic across runs.
