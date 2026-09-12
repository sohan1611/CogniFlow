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

## 2026-09-02 - Phase 8: observability + UI (Claude direct)
- Built: ui.py (Streamlit, two modes), demo.py --trace JSONL export, make ui target.
- VERIFIED IN A REAL BROWSER, not merely imported. Streamlit reports syntax errors in
  the browser rather than the console, so "it starts" proves nothing. Loaded
  localhost:8601 and drove it:
  * Watch mode: renders the full narrative, learning path "recursion -> functions ->
    recursion", colour-coded event stream, mastery deltas.
  * Interactive mode: shows "Graph suspended at await_student - checkpointed to disk,
    waiting for you", the generated problem with its RAG grounding citations, a code
    box, and the live tutor belief panel. This is the genuine HITL surface.
- demo.py --trace writes 55 structured events as JSONL. Records decisions and evidence
  only; no private model reasoning is stored, per the brief.
- OBSERVATION worth carrying into the freeze: the second generated problem logs
  repeat=True. The anti-repetition mechanism (recent_problem_hashes) correctly DETECTS
  the duplicate, but the deterministic template fallback cannot actually vary its
  output, so with no API key the same problem is reissued. With a live model this
  resolves itself. Detection works; avoidance needs the model.
- Verified: 162 passed, 1 skipped.

## 2026-09-02 - Phase 9: freeze + submission documents (Claude direct)
- Wrote docs/BRIEF.md (problem, users, why agentic, measured impact, limitations),
  docs/ARCHITECTURE.md (Mermaid diagrams that render natively in GitHub - no image
  files to go stale), docs/DEMO_SCRIPT.md (4:30 script with timings, the exact screen
  lines to pause on, and a Q&A table), docs/SUBMISSION_CHECKLIST.md.
- CLEAN-CLONE RELEASE GATE PASSED. Cloned fresh from GitHub into an empty directory
  with no index and no database - the state a judge actually finds - and ran the
  documented flow:
    ingest        -> 16 chunks
    demo --verify -> 7/7 self-checks, path recursion -> functions -> recursion
    pytest        -> 162 passed, 1 skipped
    ablation      -> reproduces (B: 65% gap detection vs A: 0%)
    check_contributors -> exit 0
  Nothing depended on state outside the repo.
- Note: ablation false-redirect reads 30% at n=40 vs 25% at n=80 - small-sample
  variance, not a regression. The headline numbers (65% vs 0% detection, 10 vs 14
  median steps) are stable across both.
- REMAINING BEFORE SUBMISSION: record the video, and run `make live` once a key exists.
  Everything to date is offline against fallbacks; the real wire format is still
  unverified and that is stated openly in the checklist and the brief.

## 2026-09-02 - COST CORRECTION (user caught a real error)
- The user challenged the "₹0" claim: an Anthropic API key costs money.
- THEY WERE RIGHT. Claude assumed "Claude is already bought" meant Anthropic API
  credits. A Claude Pro/Max SUBSCRIPTION and an Anthropic API KEY are separate products
  with separate billing; a subscription grants no API access. Leading the provider chain
  with Anthropic would have quietly turned a zero-cost project into a paid one
  (~$8 realistically: ~$0.35/demo run, ~$7 development).
- FIXED:
  * default_chain now leads with GROQ then GOOGLE (both genuinely free tiers), with
    Anthropic last and opt-in via COGNIFLOW_PROVIDER_ORDER.
  * A test now enforces it: `assert chain[0].provider != "anthropic"` - cost is treated
    as a correctness property so this cannot regress silently.
  * Two existing tests failed on the change and were CORRECT to fail; they encoded the
    old premise and were updated.
  * COSTS.md section 5 rewritten to record the error, the subscription-vs-API
    distinction, and an honest estimate if the team chooses Anthropic anyway.
  * .env.example, README, BRIEF, SUBMISSION_CHECKLIST and live_check.py all now point
    at the free tiers first.
- Verified: 163 passed, 1 skipped. ₹0 now holds without qualification.

## 2026-09-02 - LIVE API VERIFICATION (Groq free tier) - three real bugs found
- User added a GROQ key. Several things surfaced, in order:
  0. The key was pasted into .env.example, which is TRACKED BY GIT. Caught before any
     commit (verified with `git log -S`), moved to .env, template restored. Never pushed.
  1. NOTHING CALLED load_dotenv(). A key in .env was invisible to
     ProviderSpec.available(), so every provider reported "no credentials" -
     indistinguishable from a missing key. Fixed in provider.py before the env reads.
  2. MODEL NAME WRONG. `llama-3.3-70b-versatile` 404s on this account. Listed the real
     catalogue via the groq SDK -> `openai/gpt-oss-120b`. Note: a urllib probe returned
     Cloudflare 1010 and misled the diagnosis; the SDK gets through. Measure with the
     client that actually works.
  3. RUNNER CRASHED ON MODEL OUTPUT. run_test_cases did raw_case["name"], which the
     template always supplies and a real model does not -> KeyError took down the graph.
     Model output is untrusted input; now defaults/skips malformed cases.
  4. MISSING GUARD INVARIANT (the important one). The model proposed ADVANCE while a
     prerequisite return was still owed, abandoning the skill the student came for. The
     deterministic policy never does this because of branch ordering, so the gap was
     INVISIBLE until a live provider proposed freely. Added
     `must_return_to_original_objective` + 2 regression tests.
- RESULT: `demo.py --live --verify` passes ALL 7 self-checks with model-authored
  problems. Guard override rate is now a REAL measurement: 20%, and the override it
  caught was exactly bug 4. That is the strongest argument for the architecture - the
  guard caught the model doing something the rules never would.
- Added --live to demo_runner and demo.py; offline remains the default.
- 165 passed, 1 skipped.

## 2026-09-02 - Misconception diagnosis (Claude direct)
- AUDIT FIRST: compared the submission docs against the code and found a real honesty
  gap. BRIEF.md and ARCHITECTURE.md both claimed THREE model call sites; only TWO
  existed. MisconceptionAnalysis was imported but unused, detected_misconceptions was
  declared but never written, and skill nodes never accumulated misconceptions - all
  of which the original spec explicitly asked for.
- Built app/mastery/misconceptions.py: 7 deterministic patterns keyed on interpreter
  evidence. Rules run FIRST; the model is consulted only for failures they cannot name.
  A RecursionError means a missing base case - that is what the exception means, not an
  opinion, so paying a model to infer it adds cost and nondeterminism for nothing.
- KEY PROPERTY: a misconception implicates the skill ACTUALLY at fault, which is usually
  not the one being practised. "NoneType + int" during recursion implicates FUNCTIONS.
  The redirect reason changed from "repeated failures indicate an unmastered
  prerequisite" to "diagnosed misconception implicates functions" - heuristic to
  diagnosis.
- The hint is EVIDENCE, NOT AN OVERRIDE: it can only promote a genuine unmastered
  prerequisite, so a bad diagnosis can never redirect somewhere arbitrary. Tested.
- TWO MORE GUARD GAPS found by running live:
  * The model redirected on a SINGLE failure. Added
    premature_redirect_without_evidence - one bad answer is noise, one bad answer plus
    a diagnosed cause is evidence.
  * demo.py and ui.py were not displaying MISCONCEPTION events at all.
- 182 passed, 1 skipped. demo.py --live --verify passes all 7 checks.

## 2026-09-02 - Work order 4: false-redirect reduction (Claude -> Codex -> heavily reviewed)
- Task: cut the 25% false-redirect rate without losing gap detection. Numeric acceptance
  criteria: false < 12%, gap > 55%, 182 existing tests still passing.
- Codex: implemented the spec faithfully and, to its credit, REFUSED TO FAKE the ablation
  numbers - it marked them pending because it could not run anything. Exactly right.
- REVIEW FOUND FOUR PROBLEMS, one of them MINE:
  1. IndentationError in guard.py - a mechanical splice error, fixed.
  2. MY SPEC WAS CONCEPTUALLY BACKWARDS. I asked for a relative margin ("prerequisite
     must be meaningfully weaker than the target"). But by the time a redirect is
     considered the student has failed the TARGET twice, so the target's estimate is
     already BELOW the prerequisite's. The gate could never fire. Measured result: gap
     detection dropped to 0% - arm B became identical to arm A. Codex implemented my
     spec correctly; the spec was wrong.
  3. Codex's guard test had a broken _violation_ids helper (iterated model fields
     instead of reading .violated_rules). Rewrote the test file.
  4. Its chosen constants were unreachable: PREREQ_MIN_ATTEMPTS=3 against a 2-attempt
     pre-test budget, so no redirect could ever pass.
- CLAUDE RAN THE GRID Codex could not. Findings:
  * absolute threshold: a CLIFF not a curve (0.40 -> 65%/25%, 0.35 -> 42.5%/5%). No
    setting met both targets, because with 2 observations the posterior lands on a
    handful of discrete values.
  * THE REAL FIX IS EVIDENCE, NOT TUNING. A third pre-test observation separates the
    populations: 57.5% gap / 7.5% false. Four is WORSE than three on both axes.
  * The evidence budget is now DERIVED: the policy needs confidence >= 0.5 to redirect,
    and confidence_from_attempts crosses 0.5 at three observations.
  * PREREQ_REDIRECT_THRESHOLD is currently INERT (every value 0.30-0.50 identical).
    Documented as inert rather than credited with an improvement it did not produce.
- FINAL: false redirect 25% -> 7.5% (3.3x lower), gap 65% -> 57.5%, steps 10 -> 13.
  Trade stated openly in docs/ABLATION.md including the approach that failed.
- Two pre-existing tests needed updating, both legitimately: one fixture had attempts=0
  (a prior, which the policy now correctly refuses to act on) and one canary asserted
  false_redirect_rate > 0 on the premise that zero would be suspicious - now checks the
  controls are real instead. Neither was weakened; both gained rationale and the
  demo-scenario test now pins BOTH directions.
- 195 passed, 1 skipped. demo --verify and demo --live --verify both 7/7.

## 2026-09-02 - Work order 5: expand the curriculum corpus (Claude -> Codex -> reviewed)
- MEASURED FIRST and the problem was worse than "thin corpus": 6 of 8 skills had NO
  material, so skill-filtered retrieval silently WIDENED and served the wrong chapter.
  A `conditionals` remediation was being taught out of the recursion notes. Nothing
  looked broken - retrieval degrades quietly, which is the dangerous kind.
- Spec tied the corpus to the DIAGNOSER rather than just asking for more text: every
  skill a misconception can implicate must have a chapter that ADDRESSES that
  misconception. Otherwise the system diagnoses correctly and then teaches from material
  that never discusses the problem.
- Claude wrote tests/test_corpus_coverage.py FIRST, red on exactly 4 assertions, so the
  fix could be verified rather than asserted.
- Codex authored 6 documents (~1400-1650 words, 7-8 sections each). Quality is genuine
  teaching prose, and it picked up the cross-linking idiom from the existing chapters -
  "a Unit 1 problem wearing a Unit 2 costume" echoes the recursion chapter's phrasing.
  It touched no existing file, no code, no test.
- VERIFIED: corpus 2 -> 8 documents, 16 -> 69 chunks, all 8 skills covered evenly.
  Zero fallbacks. All 6 misconception->material alignments confirmed by retrieving the
  implicated skill and checking the text actually treats it.
- 204 passed, 1 skipped. demo --verify and --live --verify both 7/7.

## 2026-09-02 - Optional improvements: retrieval quality + guard-override metric (Claude)
- RETRIEVAL: built eval/retrieval_eval.py with 14 ground-truth cases drawn from the two
  real consumers (remediation queries, and the diagnoser's own misconception labels
  verbatim). MEASURED BEFORE OPTIMISING.
    recall@1 92.9%, recall@4 100.0%, MRR 0.964
  recall@4 is 100%, and that is the metric that matters: the model sees all 4 chunks, so
  a correct chunk at rank 3 is as usable as rank 1. A reranker only reorders within the
  retrieved set and the right chunk is ALREADY always in it.
  => RERANKER MEASURED AND DELIBERATELY NOT BUILT. Same discipline as the BKT negative.
- GUARD OVERRIDE: now a first-class metric on DemoResult (guard_overrides, override_rate,
  violated_rules) and printed by demo.py. Live run: 3 of 6 decisions overruled (50%),
  catching premature_redirect_without_evidence, redirect_without_sufficient_evidence and
  advance_requires_mastery.
- THE BIG FIND. Measuring the override rate required running the demo live REPEATEDLY,
  which exposed something a single run never would:
    run1 7/7  run2 7/7  run3 6/7  run4 7/7  run5 4/7
  THE HEADLINE PATH FAILED 2 RUNS IN 5. Run 5 never returned to recursion at all.
  Cause: the model emits test_cases carrying stdin but NO expectation, alongside a
  perfectly usable top-level expected_output. Those unusable cases were honoured, so
  every submission was compared against "" and failed regardless of correctness; the
  student never mastered functions, so the return never fired.
  Fixed in two places: the runner now skips empty expectations, and the grading node
  filters unusable cases before falling back to expected_output.
  After the fix: 5/5 runs at 7/7.
  A single green run would have gone straight into the recorded video and the failure
  would have surfaced in front of a jury instead.
- 213 passed, 1 skipped. Two regression tests pin the shadowing bug.

## 2026-09-02 - Deployment readiness: static code restrictions + HF Space scaffolding
- The user asked about deploying. Probed the sandbox FIRST rather than assuming, and
  found student code could read the filesystem, make OUTBOUND NETWORK REQUESTS, and
  spawn processes. Fine locally where you run your own code; a publicly hosted
  CogniFlow would have been an open proxy with a text box.
- Built app/tools/sandbox/restrictions.py: an AST allowlist applied BEFORE execution, so
  it cannot be defeated by anything the code does at runtime. Allowlist not blocklist,
  because blocklists lose - socket via urllib, urllib via __import__, and so on.
- Modelled the refusal honestly: new ExecutionStatus.BLOCKED and
  SystemFault.EXECUTION_REFUSED. Deliberately on the SystemFault side - a student who
  writes a correct function and also imports os has demonstrated NO misconception, and
  their mastery must not move for a rule nobody told them about.
- FOUND MY OWN OVER-RESTRICTION: I had blocked input(), which student exercises
  legitimately use to read stdin (supplied by our own harness). Removed - it prevented
  nothing and broke real exercises.
- Four existing tests failed and all four were CORRECT to fail:
  * two classifier tests asserted the specific fault where they meant "a SystemFault"
  * the exhaustive status test needed a branch for the new status (correct fix for an
    exhaustive test is to add the case)
  * the env-isolation test used `import os`, now blocked; switched to restrict=False
    because it tests the SECOND layer, and a test that passes only because the first
    layer held proves nothing about the second
- 35 adversarial tests: every escape route refused (subclass ladder, globals walk,
  getattr bypass, dynamic import, relative import), every legitimate exercise allowed.
- Space scaffolding in deploy/, `make space`, and deploy/DEPLOY.md. VERIFIED by building
  a clean staging copy, booting it, and driving it in a browser: it bootstrapped the
  index from scratch and produced recursion -> functions -> recursion with no errors.
- Cannot deploy myself - it needs the user's Hugging Face account. Exact steps documented.
- 253 passed, 1 skipped.

## 2026-09-02 - Gradio UI for deployment (Hugging Face retired the Streamlit SDK)
- The user hit the New Space form and it offered only Static / Gradio / Docker. Checked
  the docs rather than guessing: the Streamlit page is STALE, but the authoritative
  config reference says sdk can be "gradio, docker, or static". Docker is a paid tier.
  So `sdk: streamlit` in our Space README would have failed the build.
- Told the user before creating anything, laid out the three options with the honest
  note that the Space was always OPTIONAL - rulebook section 6 accepts a local setup,
  and the repo already clones-and-runs with self-verification.
- Built app_gradio.py: three tabs (watch / be the student / how it works). ADDITIVE -
  ui.py is untouched and still the local Streamlit UI. Both are thin renderers over the
  same graph, so there is one implementation of the behaviour and two ways to look at it.
- VERIFIED IN A BROWSER, twice: once against the working tree, once against a CLEAN
  build/space checkout with no index and no .env.
  * watch tab: recursion -> functions -> recursion, misconception + recovery events
  * interactive tab: "Graph suspended at await_student", model-authored problem
  * SECURITY GATE IN THE UI: submitted `import os` ->
    status=blocked, started=False, outcome=EXECUTION_REFUSED
- Space now: sdk gradio 6.26.0, python_version 3.12, app_file app.py. The Space
  requirements drop streamlit and add gradio; requirements-dev keeps both.
- Space entry imports `demo` from app_gradio rather than copying it, so the deployed and
  local versions cannot drift.
- 253 passed, 1 skipped.

## 2026-09-06 — Work order 1 (Claude -> Codex)
- Task: P1 items 4 and 6 — durable student identity + persistence in ui.py, a "My progress" dashboard, and `StudentStore.distinct_skills`.
- Codex: implemented all three plus tests/test_ui_persistence.py; could not run the suite (its Windows sandbox cannot spawn processes) and said so.
- Review: verified pass. 266 tests green; persistence round-tripped through a real graph session and a database reopen (0.35 -> 0.877 survived); dashboard and returning-student greeting checked in a live browser. One correction sent: `student_id_from_name` was defined in ui.py and tested by AST-extracting and exec'ing a copy — moved to app/services/student_store.py so the test imports the real function.
- Note: `codex exec resume` rejects both `-C` and `-s`; its flag set is much smaller than `codex exec`. Corrections went as a fresh `exec` with a self-contained spec instead.

## 2026-09-06 — Work order 2 (Claude -> Codex)
- Task: P2.7 progressive hints — a two-level ladder per misconception, `hints_for()`, and an "I'm stuck" button that reveals one at a time.
- Codex: implemented all three plus tests/test_hints.py. To make hint selection recognise a base-case-less draft, it added `code_patterns` and `outcomes` to the `missing_base_case` pattern.
- Review: corrections sent. Those two fields are what `detect()` matches on, and `missing_base_case` is first in PATTERNS, so it shadowed `print_instead_of_return` — a print-vs-return mistake started reporting `prerequisite_hint="conditionals"` instead of `"functions"`, which would redirect a student to the wrong prerequisite. The existing suite caught it (`test_print_instead_of_return_is_detected_from_source`).
- Fix: hint matching moved to its own `HINT_CODE_SIGNATURES` table that never calls `detect()`. Detection and hint selection answer different questions — one runs after a failure on interpreter evidence and changes the learning path, the other runs on an unfinished draft and only changes a displayed sentence. A guess good enough for a hint is not good enough to reroute a student.
- Verified: 288 pass, ALL GATES PASSED, demo path `recursion -> functions -> recursion` 7/7, diagnosis still implicates `functions`.
- Lesson for future specs: say explicitly which behaviour must NOT change, not only which files are out of scope.

## 2026-09-08 13:10 — Work order 3 (Claude → Codex)
- Task: mobile-first "spatial" redesign of web/ — fix 267px of horizontal overflow at 375px, dark phone theme, sticky compact header, fixed bottom bar, More sheet, and the prerequisite DAG rendered as a vertical spine below 768px.
- Codex: implemented across globals.css, layout.tsx, shell.tsx, page.tsx, plan.tsx. Reported it could not run the build (sandbox cannot spawn processes) but did in-process TS and PostCSS checks.
- Review: verified pass. Build clean; measured zero horizontal overflow at 320/360/375/390/412/768/1024/1440 (was 267px at 375); no fabricated content; health probe, useGlassSwap and all api.* calls intact; desktop unchanged.
- Two defects found by RUNNING it, not reading it: the exercise prompt had inherited the plan card's `-webkit-line-clamp: 2`, so the question a student must answer was cut off mid-sentence; and the answer box computed to 13.92px, under the 16px threshold that makes iOS zoom on focus. Corrections sent as a fresh `exec` — `exec resume` still rejects `-C`, as noted in work order 2.
- Escalated one item to a direct edit: Codex hid a redundant "Change name" heading with `:has()` + `display:none` because shell.tsx was outside the scope line I gave it. Deleted the JSX instead. Lesson: a scope list that excludes the file holding the markup forces a CSS workaround for a markup problem.

## 2026-09-08 13:40 — Work order 4 (Claude → Codex)
- Task: replace the answer textarea with CodeMirror 6 (Tab indent, auto-indent, Python highlighting), add a local-time study heatmap over the new /student/{id}/activity endpoint, and re-scope dark from a breakpoint to a light/dark/system theme with a pre-paint script.
- Codex: attempt 1 changed nothing — the sandbox blocked process spawning AND no filesystem fallback was exposed, so it could not read the sources. It declined to write code against files it had not seen rather than guess, which is the right call under RULE 5.
- Review: retried with an explicit instruction to use the node_repl MCP fallback (which had worked on work order 3) and a note that the CodeMirror packages were already installed.
- Codex (retry): delivered all three. editor.tsx (CodeMirror 6, indentWithTab, 4-space indentUnit, Escape unbound so it can still be left), dashboard.tsx (16-week heatmap + hour strip, bucketed in the browser), theme re-scoped from a breakpoint to [data-theme] + prefers-color-scheme with a pre-paint script.
- Review: verified pass. Build clean. Tab -> 4 spaces and Enter after "def f(n):" -> auto-indent, both proven headlessly against @codemirror/commands because the browser harness cannot deliver synthetic text to CodeMirror's DOM-mutation path. Theme stamps data-theme and persists; tokens and color-scheme both flip. Heatmap renders 112 real cells and puts an 08:55 UTC attempt at ~14:00 local.

## 2026-09-08 15:20 — Difficulty ladder (Claude, direct)
- Task: EASY/MEDIUM/HARD were labels only. Not delegated: this is core pedagogy and the failure mode is silent.
- Diagnosis: `_template_problem` ignored difficulty entirely (one sentence at every level, only the title changed) and the generation prompt passed the bare word "HARD" with no definition. Anti-repetition was computed and logged as `"repeat": true`, then ignored. The deployed engine has no provider key, so students were seeing the fallback.
- Built app/mastery/difficulty.py: 8 skills x 3 rungs of criteria (concepts, cognitive level, complexity) driving both the prompt and the fallback, with 30 authored tasks.
- Every expected_output verified by running a reference solution through the real sandbox — a wrong one marks correct work wrong, which is a StudentOutcome and lowers mastery. Two tasks were rejected during authoring: a memoised-fib call count (implementation-dependent) and a two-sum with two valid answers.
- Live run caught the model returning problem_id="loop_sum_easy_001" — a slug, not an identifier. The server now assigns it unconditionally.

## 2026-09-11 — Work order 5 (Claude → Codex): audit remediation of the deployed app
- Mode: Claude is architect/reviewer ONLY for this audit — no source edits by Claude. No commit or push without Sohan's explicit authorisation.
- Findings reproduced BEFORE writing the order:
  1. Cold start measured 64 s end to end (Render schedule ~26 s + interpreter ~31 s + ~7 s); the frontend probe budget is 12 x 5 s ≈ 60 s and then terminal — the page stays "Engine offline" until reloaded. Every GET also sends Content-Type: application/json, so each /health is preceded by a CORS preflight (visible in engine logs).
  2. More → "Open session detail" with no learner runs changeTab inside the shared `busy` guard (Start flips to "Starting…"), requests /student//progress, and shows the raw 404 statusText "Not Found".
  3. More sheet derives status from `health` alone, which stays null after the probe gives up → "Checking engine status" beside a page saying "Engine offline".
  4. Offline banner has no retry, no status, no help.
  5. Offline banner names NEXT_PUBLIC_API_URL; api.ts error embeds the engine URL.
  6. Name stage h1 → h3 (feature cards); Learn tab has no h1 at all (problem title h3, then h2); diagnostic card h3 under h1.
- Engine import time measured locally at 1.5 s, so the Render interpreter phase is free-tier CPU/disk, not code — remediation is frontend-side (a wake window sized to the measurement, non-terminal offline, retry), not an import-time refactor.
- Order: one `useEngineStatus` hook as the single source of truth (checking/waking/online/offline, 180 s wake window, 25 s per-probe abort, 30 s offline re-probe, one probe in flight, reportUnreachable on mid-session network failure), `engineCopy()` shared by page/Start/More, retry + live status + help, student-safe error mapping, split busy flags, one-h1/no-skip headings with unchanged visuals. Scope: web/lib/api.ts, web/lib/engine.ts (new), page.tsx, shell.tsx, plan.tsx (headings only), globals.css.
- Codex: delivered web/lib/engine.ts (useEngineStatus + engineCopy), api.ts (no Content-Type on bodyless requests, AbortSignal, ApiError.kind, student-safe status mapping), page.tsx (status banner with retry, split starting/submitting/actionBusy/navigating flags, id guard, heading promotions), shell.tsx (engine prop, disabled session detail, offline retry), globals.css (heading-class styles, banner, 44px retry). It could not run the build.
- Review (Claude): `npm run build` exit 0, no type errors; tests/test_theme_tokens.py 3/3. Grep: NEXT_PUBLIC_API_URL / statusText / ${BASE} only in the BASE constant and the fetch URL — none user-visible. No threshold comparisons added, no View Transitions/flushSync.
- Live verification against the REAL engine, which had gone cold during review (local prod build → Render):
  * F1: "Waking the tutoring engine · attempt 2" at 41 s → online at ~65 s, Start Learning enabled with NO reload (old budget expired at ~60 s). Engine logs: process 07:54:08 → first 200 at 07:54:43, and the GET arrived with NO preceding OPTIONS (preflight gone).
  * F3: page banner, Start label and More "Engine status" identical at every sampled transition.
  * F2: More → Open session detail with no learner: disabled, "Available once you've started.", sheet stays open, Start label unchanged, 0 /student/ requests, no error.
  * F6: name stage h1→h2×4; diagnostic h1→h2; learn h1 (problem title)→h2; dashboard h1→h2→h2→h3; progress h1→h2×4. Promoted headings' computed style identical to the old h3 (16px/700/20.8px/margin 0 0 6px, same colour).
  * Flows: onboarding → diagnostic (Variables, Conditionals answered; Functions, Loops skipped) → "Start here: Functions, 63%" → plan → live RAG-grounded exercise → hint 1 targeted at print-vs-return → wrong answer: misconception feedback, functions 0.24→0.18, targeted debug variant, hint ladder reset → correct: "Correct 100%", EASY→MEDIUM with student reason → Progress shows both attempts, heatmap 112 cells, 0 px overflow. Neon: two attempt_log rows with exact mastery (0.2444→0.1830→0.5767), 8 skill rows.
- Verdict: ACCEPTED WITH CORRECTIONS. Three defects found in review:
  D1 the banner's aria-live region contains the per-second "Trying for N s" counter → a screen reader re-announces every second for up to 3 min;
  D2 Enter in the name field calls begin() regardless of the Start button's disabled condition → POST /session while waking/offline;
  D3 a mid-session network error stays on screen after the engine is back online — the same status contradiction as finding 3.

## 2026-09-11 — Work order 5b (Claude → Codex): corrections D1–D3
- Scope: page.tsx, engine.ts, globals.css only. Live region limited to title+detail; one `canStart` predicate for button and Enter; clear an error on the transition to online ONLY if it was a network error (HTTP errors stay).
- Codex: nested `.engine-status-live` (role=status, aria-live=polite) around title+detail only; `canStart` shared by button and Enter; error state now `{message, kind}` with an effect that clears kind "network" on a real non-online → online transition.
- Review (Claude): build exit 0 (rebuilt with NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 so the engine could be killed at will). Verified in a browser against a local engine:
  * D1: one aria-live region; its text is title+detail only; "Trying for 31 s · attempt 5" sits outside it.
  * D2: name typed, Enter dispatched while waking → 0 /session requests, Start disabled.
  * Offline at 180 s: page and More sheet both "Can't reach the tutoring engine right now", "Last checked 4 s ago", help line, Try again now on page and (46 px) in the sheet, Start "Engine offline". Retry during waking → "Checking…"/disabled, exactly 1 /health, attempt counter reset.
  * Auto-recovery: engine started 08:13:29 → banner gone and Start enabled by 08:13:41, no reload.
  * Mid-session outage: engine killed with an exercise open → click Progress → "We couldn't reach the tutoring engine." + banner flips to waking, learner stays on the exercise, typed draft preserved. Engine back → D3: error cleared on the transition to online.
  * After an engine restart the in-memory session is gone → Submit → "We couldn't find that record. Try starting again from your name." — no raw "Not Found".
  * No env var name or URL in any rendered text, in any state.
- NOT A DEFECT (recorded so nobody chases it): a light-theme "Try again now" measured transparent. With transitions disabled it is #2f5fe0; getAnimations() empty and timeline advancing → the reading was the 0.18 s `.btn` background transition caught mid-flight by the harness after a theme switch. White on #2f5fe0 ≈ 5.9:1.
- Verdict: ACCEPTED.
- Found during the audit, PRE-EXISTING (identical on the live site): on the name stage the disabled "Learning Plan" nav still carries aria-current="page", so the active-pill style renders near-white text on white — 1.42:1 dark, 1.04:1 light. → work order 5c.
- Found during the audit, NOT fixed here (reported to Sohan): sessions live in LangGraph's MemorySaver, so every Render sleep discards the exercise a learner has open (progress itself is safe in Postgres). Also dashboard.tsx heatmap month labels collide ("MayJun") at 375 px.

## 2026-09-11 — Work order 5c (Claude → Codex): nav pill contrast before a learner exists
- Scope: shell.tsx (+ globals.css only if needed). `aria-current` only when there is a learner, on both navs; disabled labels ≥ 3:1 and active pill unchanged once a learner exists.
- Codex: `aria-current={name && tab === t.id ? "page" : undefined}` on both navs; `.bottom-nav button:disabled` opacity .42 → .72 with color var(--ink-2).
- Review (Claude): final production build exit 0 (default engine URL); tests/test_theme_tokens.py 3/3; `run.py gates` ALL GATES PASSED (88 commits, one human author); data/chroma rewritten by the local-engine run was restored with `git restore` so only intended files are dirty.
- MEASUREMENT LESSON (twice today): two "failures" were the harness, not the app — a theme switch starts 0.18 s colour/background transitions, and reading computed style before they finish returns the PREVIOUS theme's value (dark --ink-2 #d9deeb read in light; a transparent button). Every contrast number is now taken after `document.getAnimations().forEach(a => a.finish())`.
- Settled measurements: name stage has no aria-current in either nav ✓; disabled labels 5.84 (light desktop) / 14.09 (dark desktop) / 3.23 (light mobile) / 7.88 (dark mobile) ✓; light desktop pill with learner 18.41 ✓.
- Verdict: ACCEPTED for its own change. Signed-in measurement exposed three PRE-EXISTING failures (all on the live site): dark desktop current pill white-on-white 1.04:1; light mobile enabled inactive labels incl. "More" 3.02:1; dark mobile current item 4.27:1. → work order 5d.

## 2026-09-11 — Work order 5d (Claude → Codex): nav contrast, both navs, both themes
- Scope: globals.css only. Enabled nav labels ≥ 4.5:1 and disabled ≥ 3:1 (and visibly weaker) in light and dark, 375 px and ≥ 768 px, with and without a learner; current tab stays distinct; dark blocks stay identical.
- Codex: dark `--chrome-active` #ffffff → rgba(255,255,255,.14) (white text kept); new `--mobile-nav-ink` (light #5b6473, dark #c5ccd8) and `--mobile-nav-current-ink` (light #2f5fe0, dark #c4b5fd), defined on :root and identically in both dark blocks.
- Review (Claude): build exit 0; test_theme_tokens 3/3. Settled measurements (animations finished): desktop light current 18.41 / others 5.84, dark current 14.09 / others 14.09; mobile light current 4.75 / others 5.95 / disabled 3.23 vs More 5.95; mobile dark current 9.79 / others 12.53 / disabled 7.88 vs More 12.53; 0 px overflow at 375. The top nav has no separate disabled style, but before a learner exists all three are disabled together, so there is nothing enabled beside them to be confused with.
- Verdict: ACCEPTED. The audit's six findings, plus the three contrast defects found along the way, are closed locally; nothing is committed.

## 2026-09-11 — New request from Sohan: accounts (sign-up, Google, forgot password), progress saved per account
- Decisions (Sohan, via questions): upgrade Next 15 → 16 (Neon's Next SDK @neondatabase/auth 0.5.0-beta requires next >= 16; the framework-neutral client would sign in with third-party cookies, which Safari/iOS block); Neon Managed Better Auth enabled by Claude with permission; ACCOUNT REQUIRED, no guest mode.
- Neon Auth: CogniFlow project, production branch, database CogniFlow. The first provision call errored ("neon_auth schema already exists" — an empty leftover: 0 users/sessions/accounts, 1 project_config row) but DID register the integration at 12:53:25; a second call then reported "already exists". Nothing was dropped. Config: email+password on, Google on with Neon's SHARED credentials (fine for the demo; production needs Sohan's own Google OAuth client), shared email sender for password reset, localhost allowed; trusted domain https://cogniflow-nine.vercel.app added. Base URL (public, not a secret) recorded in memory, not here.
- Plan: WO6 Next 16 upgrade (web only) ‖ WO8 engine token verification (Python only) in parallel, then WO7 auth screens + token plumbing (web). Deployment must be coordinated: push code with the engine still in name mode, then set NEON_AUTH_BASE_URL on Render and the auth env vars on Vercel together — never the engine alone, which would lock out the live frontend.
- Codex: WO6 and WO8 running.

## 2026-09-11 — Work order 6 (Claude → Codex): Next.js 15.5.25 → 16.3.4
- Codex: web/package.json only — next pinned to 16.3.4; the dead `lint` script (`next lint` is removed in 16, and the project never had ESLint) replaced by `"typecheck": "tsc --noEmit"`. next.config.mjs and tsconfig.json left for Next to adjust. It listed the upgrade-guide items it judged not to apply (Turbopack default, Node/TS minimums, no sync request APIs, no middleware yet) and correctly flagged the smooth-scroll change without opening globals.css, which was out of its scope.
- Review (Claude): I ran `npm install` (Codex cannot spawn processes) → next 16.3.4, 0 vulnerabilities; `npm run build` exit 0 on Turbopack; `npm run typecheck` exit 0. The only scroll-behavior rule is `auto !important` inside a reduced-motion block, so the smooth-scroll change does not apply. Next 16's build auto-edited tsconfig.json (reviewed separately).
- Verdict: ACCEPTED pending the browser smoke test of the unchanged app on Next 16.
- Smoke test (Next 16 build → live engine): engine online, landing h1 + 4×h2, returning learner reaches the dashboard, Progress and Learning Plan load with no error and 0 px overflow. tsconfig.json edits are Next 16's own (`jsx: react-jsx`, `.next/dev/types` include) — kept. ACCEPTED.
- Installed for WO7/WO8 (Codex cannot run installers): @neondatabase/auth 0.5.0-beta (exact pin) in web; PyJWT[crypto] 2.13.0 in the venv. web/.env.local created by Claude with the public auth URL and a locally generated cookie secret — git-ignored (verified with `git check-ignore`), value never printed.

## 2026-09-11 — Work order 8 (Claude → Codex): the engine verifies who is asking
- Codex: app/services/auth.py (TokenVerifier: EdDSA-only, alg checked before any key lookup; keys only from the configured JWKS URL, jku/x5u/jwk headers ignored; kid required; OKP/Ed25519 kty check; JWKS cached 10 min, unknown-kid refetch throttled to 1/60 s; exp/iat/sub required, iss and aud = auth origin, strict_aud, 30 s leeway on an injectable clock; fetch failure fails closed; logs the reason, never the token). main.py: `token_verifier()` (None in name mode), `_caller` → 401 "Please sign in again." + WWW-Authenticate, `_student_owner` → 403 on every {student_id} route (9 routes, listed in its report and checked against the route table), POST /session keyed by the token's sub, /health "auth": required|off. settings `neon_auth_base_url`, requirements `PyJWT[crypto]==2.13.0`, .env.example note, tests/test_auth.py (19).
- Review (Claude): full suite 436 passed / 5 skipped (417 before + 19), test_auth 19/19, name mode unchanged. `_require_name_in_name_mode` rebuilds the old 422 shapes by hand so StartRequest.name can be optional in account mode — inelegant but real and covered by the existing API tests.
- Two notes: the CORS comment in main.py still says "this API has no authentication" (stale → one-line correction with the WO7 round); `strict_aud` assumes Neon's aud is a single string, as documented — to be confirmed against a real token from Sohan's sign-in.
- Verdict: ACCEPTED (live token check pending).

## 2026-09-11 — Sohan: "Why wrong data?" (dashboard: "24 attempts · 4 of 8 confirmed")
- He was right. Production rows for sohan-mandal, arka and ar are EXACTLY DEMO_SEED (variables 0.90/0.85 … recursion_tree 0.20/0.30, attempts=3 on every skill): 24 attempts stored on skills, 0 rows in attempt_log. Cause: POST /session calls `seed_student(store, student_id)` for every new student — the hackathon demo's scripted state installed into real learners since the API was written. "4 of 8 confirmed" = the four demo skills above the mastery bar.
- Second defect: `needs_diagnostic = is_new`, so a learner who abandons the quick check and comes back is "returning", skips it, and lands on the demo profile.
- Third: the dashboard sums skill.attempts (seed + diagnostic answers) while Progress counts attempt_log rows — two different totals for one learner.
- → Work order 9 (engine): priors from skills.yaml for new students, a durable diagnosed_at marker (needs_diagnostic = NULL AND no attempt_log rows, so real history is never overwritten and seed-only rows get repaired by the check), plan.total_attempts from attempt_log. The frontend switch to that count goes with WO7's corrections, since WO7 is editing page.tsx.
- Existing polluted rows: deletion needs Sohan's permission — asked.
- WO9 (Codex): POST /session stores SkillGraph priors (0.5/0.3/0) for new students; `store.needs_diagnostic(id)` (diagnosed_at IS NULL AND no attempt_log rows) drives both needs_diagnostic and whether a DiagnosticSession is created; `mark_diagnosed` on finish; plan `total_attempts` = attempt_log rows. student_store: diagnosed_at in both schemas, SQLite `_migrate` ALTER, Postgres `ADD COLUMN IF NOT EXISTS`. tests/test_honest_start.py (7), the returning-student API test corrected (it had encoded the defect), parity exercise extended.
- Review (Claude): full suite 443 passed / 5 skipped; Postgres parity + honest-start against a real PostgreSQL 17 → 17 passed. The API no longer imports seed_student. ACCEPTED.
- Residual outside WO9's scope: ui.py (the public Streamlit app) still calls seed_student for interactive learners — same fake-data defect on the second surface. → WO11, with the stale CORS/docstring text in main.py.

## 2026-09-11 — Work order 11 (Claude → Codex): Streamlit stops inventing progress
- Codex: ui.py — named newcomers get `store.save_skills(id, SkillGraph.from_yaml(...).nodes)`, the anonymous in-memory learner gets the same priors via `store.seed`; the "Watch the demo" branch (run_demo → DEMO_SEED) untouched; seed_student import removed. main.py: module docstring (SQLite locally / PostgreSQL with DATABASE_URL) and the CORS comment (account tokens are the access control; CORS never is) rewritten — text only. No helper test added (it was optional).
- Review (Claude): full suite 443 passed / 5 skipped. The suite never imports ui.py (a Streamlit script), so a green suite proves nothing about it: checked separately that it compiles and that every name it uses is defined (a missing SkillGraph import would crash the public app on the first new learner). Result: SkillGraph imported at line 36, py_compile OK, AST scan finds no undefined names (only the module global __file__). ACCEPTED.

## 2026-09-11 13:35 — Sohan: "the button stopped responding, I can't go back" (LIVE site, old code)
- Live engine logs, 13:30:53–13:30:56, instance mdh7q (freshly restarted): ~10 OPTIONS + ~20 GET for /student/sohan-mandal/{plan,progress,activity} in three seconds — repeated clicks, EVERY ONE 200 OK, each taking 2–3 s (preflight + fresh instance).
- So nothing was broken server-side. The live page (a) shows no loading state while a tab's data loads, (b) lets overlapping clicks race so the last response wins, and (c) renders the active tab as white-on-white in dark (fixed locally by 5d, not deployed). It looked frozen, so he kept clicking.
- My repro on an awake engine: dashboard → Learn → Learning Plan works in ~1 s.
- None of today's fixes are live: nothing has been pushed, by Sohan's instruction. The remaining fixes join a full-sweep list rather than being chased one complaint at a time.
- Full sweep, auth screens (local WO7 build, signed out): "/" → /auth/sign-in ✓; one h1 per screen, labelled 16px inputs with correct autocomplete, show/hide password, no target < 44px, 0 px overflow at 375 and desktop, no technical text; reset-password without a token shows the expired message + "Request a new one" ✓; client bundle (16 files) contains no cookie secret, no auth host, no env names ✓. Defects: forgot-password has NO link back; light-theme password rule and "or" divider 3.03:1.
- Google sign-in, checked without navigating or entering anything: POST /api/auth/sign-in/social {provider: google} → 200, redirect true, URL = the project's auth host /CogniFlow/auth/sign-in/social/init (Neon's shared-credential OAuth start). The Google screen itself is Sohan's to confirm when he signs in.
- WO7 code review (files WO10 does not touch): proxy.ts protects only "/" (auth pages stay reachable); lib/auth/server.ts builds createNeonAuth lazily and throws a clear "NEON_AUTH_BASE_URL is not set" at request time — the reason the build passes without the vars; client.ts talks only to our own /api/auth, so cookies are first-party; the route handler delegates GET/POST. No defects.
- → Work order 10 (frontend, one order for the whole sweep): D1 tab switches at once with a loading state and last-click-wins (the live freeze); D2 timeouts on every request + visible progress for generation/grading; D3 an engine restart silently re-opens the session instead of stranding the student on a 404; D4 one real attempt count from plan.total_attempts; D5 heatmap month labels colliding on phones; D6 the two auth defects.
- WO10 (Codex): page.tsx — tabs switch synchronously, `navigationId` drops stale responses, `loadingTab` shows cached data with "Updating…" or a per-view loading state (aria-busy); 3 s progress notes for generation/grading; `reopenSession` re-opens a dropped engine session once, returns to Plan with the "tutor restarted" note, keeps drafts per skill, reloads the diagnostic; dashboard total from plan.total_attempts (fallback Progress, else hidden). api.ts — 20 s reads / 120 s tutor calls, kind "timeout" that does not call reportUnreachable. shell.tsx — nav stays enabled during loads. dashboard.tsx — month labels keep >= 2 columns apart. globals.css — loading/progress styles, light auth helper/divider raised. forgot-password — "Back to sign in".
- Review (Claude), static: build exit 0 (NEXT_PUBLIC_API_URL=http://127.0.0.1:8000), typecheck exit 0, test_theme_tokens 3/3; stayed inside its six files; did not touch the collab log. Browser verification needs a signed-in session → local engine started in account mode (local SQLite, never production) and Sohan asked to sign in.
- Pre-sign-in checks (16:4x UTC): local engine /health → "auth":"required", "storage":"sqlite"; GET /student/anyone/plan with no token → 401; with an invented bearer token → 401 {"detail":"Please sign in again."}; POST /session with no token → 401; signed-out visit to localhost:3000 → /auth/sign-in. Handing the browser pane to Sohan for sign-up/sign-in (Claude does not create accounts or type passwords).
- WO7 (Codex): four auth screens, lazy createNeonAuth, /api/auth proxy, proxy.ts protecting "/", JWT caching/refresh + 401 retry/redirect + 403 mapping, Sign out, account-backed welcome stage. Claude: build exit 0 WITH and WITHOUT the auth env vars, typecheck exit 0; routes: /api/auth/[...path] (ƒ), /auth/sign-in, /auth/sign-up, /auth/forgot-password (○), /auth/reset-password (ƒ), Proxy (Middleware).

## 2026-09-12 — Accounts live, and the three token bugs behind "Start Learning does nothing"
- Deployed: engine account mode (Render NEON_AUTH_BASE_URL) + frontend auth (Vercel NEON_AUTH_BASE_URL / NEON_AUTH_COOKIE_SECRET, both added by Sohan). Live checks: /health "auth":"required","storage":"postgres"; anonymous /student/{id}/plan → 401.
- Sohan signed up on production and could not start. Three separate bugs, each found in logs, none guessed:
  1. WO12b — `authClient.token()` did not send the session cookie. Vercel: GET /api/auth/token 401 twice from the app; the same route with `credentials: "include"` in the same browser/session → 200. Next's `createAuthClient()` takes no config, so the option goes on the call.
  2. WO13 — with the cookie fixed, the engine logged `authentication failed: malformed token` on every POST /session. We were sending Better Auth's OPAQUE `session.token`, not a JWT, because the SDK's token() call never reached the network (no /api/auth/token lines at all) and the WO12 fallback returned session.token unchecked. Now: plain `GET /api/auth/token` (the measured-working call), documented `{ token }` body, and a guard — nothing is sent unless it parses as a JWT (3 base64url segments, header with `alg`). The opaque token fails that test.
  3. WO14 — a backgrounded tab showed "Trying for 57 s · attempt 0" with zero requests: the wake loop correctly pauses while `document.hidden`, but the banner kept counting, the 180 s window kept expiring unattended, and retry() did nothing. Timers now count visible time only, the copy says it is paused, and a hidden retry runs on return.
- Verified in Sohan's own signed-in browser (Claude in Chrome, his session, no credentials typed): token endpoint returned a well-formed JWT and POST /session returned 200 with student_id = his account UUID, needs_diagnostic true. Then his own session in the engine logs: diagnostic questions fetched and answered, plan, progress and activity all 200, zero authentication failures.
- Cleanup (his explicit permission): the four name-keyed rows — sohan-mandal, arka, ar (pure DEMO_SEED, 0 logged attempts) and audit-check (Claude's test learner) — deleted from production. Account-keyed rows untouched.

## 2026-09-12 — Work order 15 + 15b (Claude → Codex): real logo, background matched to it
- Sohan: use the two existing logo images, theme-aware, top-left, and make the app background EXACTLY the colour inside those images so the logo's rectangle disappears. Follow-up: "dont change design structure or structural things colour, just change the main background colouring part".
- Claude first: found the assets at the repo root (no web/public existed), sampled their backgrounds with Pillow from a 1px border ring — light #f4ede3 (rgb 244,237,227), dark #1c2a45 (rgb 28,42,69) — and read the theme architecture (pre-paint script stamps data-theme; tokens on bare :root + two dark blocks; no next-themes/Tailwind/context). Decided the swap must be CSS-only, which removes flash and hydration risk by construction.
- WO15 (Codex): byte-identical copies to web/public/brand/, two <img> swapped by --brand-logo-*-display tokens set in all three blocks, sized by height with width:auto (the files differ in aspect 2.000 vs 2.016, so a shared fixed box would squash one), --page/--body-bg/--topbar-bg set to the sampled colours, dark glow gradients replaced by the flat navy. Contrast repairs: light --ink-3 #8b95a4 → #808997 (2.61 → 3.04); new --brand-ink (dark #b495f9) for small accent TEXT only, leaving accent fills alone (old violet on the lighter navy was 2.65:1).
- Review 1 (Claude): assets byte-identical (cmp) at 512x256 / 512x254; build, typecheck and test_theme_tokens green; measured on the auth screen — the logo's own edge pixel EQUALS the surface behind it exactly in both themes (light rgb(244,237,227); dark rgb(28,42,69)), rendered aspect = intrinsic aspect, no border/radius/shadow/background. REJECTED on two counts: (1) `--shell` was still #080b12 and `.shell` paints it at >= 768px, so desktop dark would show a navy header over a near-black body — a seam, and the main background would not be the logo colour (phones were fine, which is how this ships unnoticed); (2) dead CSS left by the replaced markup: .brand-tile, .wordmark, .wordmark-flow and the tokens --brand-tile-size/radius/shadow and --wordmark-ink.
- WO15b (Codex): --shell #1c2a45 in both dark blocks, dead rules and tokens removed (including .brand-tile inside a shared selector group and the two dark `display: grid` rules). Verified: only .auth-wordmark remains in the markup; build/typecheck/theme tokens green.
- Review 2 / ACCEPTED (Claude, measured on a reloaded build so no stale CSS): at 1280px the logo's edge pixel equals the surface behind it in both themes (light rgb(244,237,227), dark rgb(28,42,69)), logo 88x44 / 89x44 with rendered aspect = intrinsic aspect, overflowX 0. Dark at >= 768px has no seam: body, --shell and --plate all resolve to rgb(28,42,69) (--plate is `transparent` in both dark blocks, so the content area shows the shell navy). At 375px both themes match exactly at 36px, overflowX 0.
- Two false alarms during review, both in the harness and not the app: contrast/colour readings taken mid theme-transition returned the PREVIOUS theme's values (every measurement now runs after document.getAnimations().forEach(a => a.finish())), and the tab served stale CSS after a server restart, making --shell look unfixed until the page was reloaded. Worth remembering: a measurement that disagrees with the source is the measurement's fault first.
- .topbar is transparent at >= 768px by design, so the header shows whatever is under it — cream body in light, --shell navy in dark; below 768px it is opaque --topbar-bg (#f4ede3 / #1c2a45). Both paths land on the logo's own background colour, which is why the rectangle is invisible at every width.
- Final gate on the accepted state: npm run build exit 0, npm run typecheck exit 0, tests/test_theme_tokens.py 3 passed. No reference to .brand-tile, .wordmark, .wordmark-flow, --brand-tile-* or --wordmark-ink remains anywhere in web/. Uncommitted, awaiting Sohan's push authorization.

## 2026-09-12 — Work order 16: the v1.0 chip, and four tokens the background migration missed
- Sohan: "fix that more panel colour too also remove that v1.0".
- The More sheet was `--more-bg: rgba(8,11,18,.98)`, a near-black chosen when the page was #05070c. Grepping both dark blocks for values that never moved found it was one of FOUR: `--shell-2` (#0d1119, consumed only by --button-hover-bg, so hovering a button went near-black), `--spine-node-bg` (#0a0d14), `--mobile-nav-bg` (rgba(5,7,12,.9)) and --more-bg itself. Every OTHER dark surface in this theme is a white veil — rgba(255,255,255,.03….09) over the base — which is exactly why they all adapted to the navy for free and these four did not. Replaced with the opaque equivalents of that same veil over #1c2a45: 6% -> #2a3750 (sheet, button hover), 4% -> #25324c (spine node), and rgba(42,55,80,.92) for the nav, which keeps its alpha because that rule carries a backdrop-filter.
- Version chip: the constant and the span in shell.tsx plus four CSS rules. Two of those rules grouped `.version-chip` WITH `.who`, so only the selector came out. `.brand-line` now renders only when it has an engine dot in it, so it cannot leave an empty flex row beside the logo.
- Process note: this went to Codex as a work order and Codex ran ~20 minutes without writing a single patch, so on Sohan's "do it fast" it was killed and Claude implemented directly. Worth remembering that the delegation is not free when the change is four token values and one span.
- Contrast, measured in the browser against the new grounds with translucent colours composited first (lightening the sheet makes text WORSE, which is the whole risk): --ink 11.49, --ink-2 8.86, --ink-3 7.38, --tagline-ink 6.47, --chip-ink 5.67, --brand-ink 4.89 on the sheet; --ink-3 7.93 on the node; --ink 11.49 on the hover; --mobile-nav-ink 7.50 and --mobile-nav-current-ink 6.56 on the composited nav. Lowest 4.89 against a 4.5 threshold, so no token needed changing.
- THE MEASUREMENT TRAP, TWICE NOW: the first two readings returned the OLD values and would have "verified" a change that had not rendered. The served CSS was correct the whole time; the browser tab was holding the previous stylesheet, and a server restart did not clear it — only a cache-busting navigation did. Check the served bytes (curl the stylesheet) before trusting anything the page reports.
- Gate: tests/test_theme_tokens.py 3 passed, npm run typecheck exit 0, npm run build exit 0. No `version-chip` or `VERSION_LABEL` reference remains in web/. Not visually confirmed inside the More sheet itself, which needs a signed-in session.
- Infra, same day: the engine service (srv-daemde6q1p3s739vfhb0, Render free, singapore) had autoDeploy on `main` with NO build filter, so both of today's frontend-only pushes rebuilt the Python engine and took it offline while they ran — the 503s seen mid-audit. Sohan added ignoredPaths ["web/**","docs/**",".agents/**","*.md"]; confirmed in the service config. Denylist, not allowlist, deliberately: this service builds from the repo root and indexes a corpus from data/, so an allowlist that omits one path would silently stop deploying real engine changes, which you would only notice when a fix failed to take.
- Favicon (Sohan: the light logo's icon only, no cream around it): the icon's bounds were found programmatically rather than eyeballed — ink rows form two bands, 36-167 (icon) and 180-219 (wordmark), so the icon is exactly x177-334, y36-167 (158x132). The cream was NOT colour-keyed, which would have punched a hole through the window's interior since it is the same cream; instead the fill floods inward from the border, so cream reachable from outside goes transparent and the interior, sealed by the navy frame, survives. Supersampled 4x before the fill and downsampled after, so the rounded corners antialias. Verified: all four corners alpha 0, centre rgb(250,233,225) opaque. web/app/icon.png (256, transparent) + web/app/favicon.ico (16/32/48); Next wires both by filename, no code change. Legible at 32+; at 16 the braces blur into the infinity loop but the silhouette reads. No apple-icon on purpose: iOS composites transparent touch icons onto black and that wants an opaque version.
