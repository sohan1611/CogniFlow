# CogniFlow

**A tutoring agent that changes its own objective when it works out *why* you're failing.**

Built for the Agentic AI Hackathon — Tech Zephyr 4.0, IIT Bhubaneswar.
Team **BloodCoded**.

---

## The problem

A student fails a recursion exercise. Twice.

Most AI tutors respond by generating an easier recursion question. But the student's
actual problem often isn't recursion at all — it's that they don't understand what
`return` does when a function calls another function. Give them an easier recursion
problem and they will fail that too, for the same invisible reason.

CogniFlow is built to notice this and act on it:

```
Recursion  →  Functions  →  Function-call tracing  →  Reassessment  →  Return to Recursion
```

That redirect is not scripted. It is computed from a prerequisite graph and live
Bayesian estimates of what the student knows, and it is the behaviour the whole
architecture exists to produce.

---

## Why this is an agent, not a chatbot with a quiz generator

Four claims, each of which can be checked against the code rather than taken on trust:

**1. The action sequence isn't knowable in advance.**
Which skill is taught next is a function of live mastery estimates and prerequisite-graph
traversal. Nothing is hardcoded; the path is computed from evolving state.

**2. It revises its own model of the world.**
Every submission updates a persistent Bayesian belief about the student, and that belief
changes future decisions. A feedback loop over durable state, not a chain of prompts.

**3. It reasons about causes, not symptoms.**
Repeated failure triggers a *prerequisite investigation*, which can reassign the target
skill. The agent changes its own goal.

**4. It genuinely suspends and resumes.**
The graph checkpoints to disk and halts at the student-interaction point. A *separate
process*, minutes later, resumes the same thread from that checkpoint.

### The architectural spine

> **The model proposes; the policy guard disposes.**

An LLM emits a structured `AdaptationDecision`. A deterministic guard
([`app/mastery/guard.py`](app/mastery/guard.py)) validates it against hard invariants —
you may not `ADVANCE` below a mastery threshold, you may not `REVISIT_PREREQUISITE` when
no unmastered prerequisite exists — and overrides it when invalid, logging the override.

This buys three things at once: the LLM cannot corrupt a learning path; the override rate
is a measurable quantity; and the demo's adaptation path holds **even if the model says
something odd**, because routing is deterministic.

### What we deliberately did *not* do

The hackathon brief states that multi-agent architectures, vector databases, RAG, and
long-term memory are **not mandatory**. We use no multi-agent orchestration and no
embedding-based lookup for the rules:

- **No multi-agent** — one goal, one coherent state. Splitting it would add coordination
  failure modes and buy nothing.
- **No fuzzy retrieval over rules** — prerequisite relations and mastery thresholds must
  be applied *exactly*. Approximate matching there would be a correctness regression.

Only **three call sites use an LLM at all**: problem generation, conceptual grading, and
misconception analysis. Diagnosis, routing, mastery arithmetic, and prerequisite
selection are deterministic and unit-tested.

*We do not use an LLM where arithmetic is already correct and free.*

---

## The safety invariant

The most important rule in this codebase:

> **A student's mastery score can only ever be changed by evidence about the student.**

`StudentOutcome` (wrong answer, syntax error, runtime error, their infinite loop) and
`SystemFault` (sandbox crash, LLM timeout, malformed model output) are **disjoint types**.
Mastery is reachable only from the first. Passing a `SystemFault` to the mastery updater
raises rather than silently penalising the learner.

This is enforced by the type system, not by a conditional a reviewer has to notice — and
it is verified by 30 adversarial tests in
[`tests/test_safety_invariant.py`](tests/test_safety_invariant.py), including the case
that matters most in practice: a bare string `"CORRECT"` arriving from a JSON round-trip
or an LLM response is **rejected**, because the guard uses `isinstance` rather than value
comparison.

If our infrastructure breaks, the student does not pay for it.

---

## What it actually does

```
$ python demo.py --verify

Learning path : recursion -> functions -> recursion
Actions       : RETRY_VARIATION -> REVISIT_PREREQUISITE -> REVISIT_PREREQUISITE -> REASSESS -> COMPLETE
Session       : COMPLETED in 6 turns

Mastery movement:
  recursion    0.350 -> 0.877  (up)
  functions    0.550 -> 0.869  (up)

Injected infrastructure failure:
  SANDBOX_FAILURE -> routed to recovery, mastery untouched

SELF-VERIFICATION
  [PASS] visited recursion -> functions -> recursion
  [PASS] first failure retried, second escalated to prerequisite
  [PASS] redirect target was chosen as the weakest prerequisite
  [PASS] returned to the original objective
  [PASS] infrastructure fault did not move mastery
  [PASS] student ended ahead on recursion
  [PASS] remediation was grounded in retrieved material
```

The student failed recursion twice. The agent did not generate an easier recursion
problem — it walked the prerequisite graph, found `functions` was the weakest unmastered
dependency, **reassigned its own objective**, taught functions in a different mode
(`CODE_TRACE`) grounded in the retrieved functions chapter, absorbed an injected sandbox
failure without penalising the student, and then came back to recursion and finished.

Only the *student* is scripted — what they submit and when. Every tutoring decision is
computed from live mastery estimates. The same code path is asserted in
[`tests/test_demo_e2e.py`](tests/test_demo_e2e.py), so what you watch is what CI checks.

---

## Does any of this actually help?

Most projects assert that their architecture is better. We measured it, against a cohort
of 80 simulated students with **planted** prerequisite gaps — so "did it find the gap?"
is scored exactly rather than judged.

```
arm                  mastered   med steps  gap found   false rdr   est err
------------------------------------------------------------------------------
A_no_prerequisite      100.0%          14       0.0%        0.0%     0.211
B_rules                100.0%          10      65.0%       25.0%     0.106
C_guarded_model        100.0%          10      65.0%       25.0%     0.106
```

- Prerequisite-aware adaptation reached true mastery in **29% fewer attempts**.
- It found the planted gap in **65%** of affected students. The no-prerequisite arm
  found it in **0%** — it cannot, by construction.
- Its mastery estimates were **2x closer** to students' true hidden skill.
- **Honest cost: it also redirected 25% of students who had no gap.** Diagnosis is not
  free, and the harness is built to surface that rather than hide it.

Arm C matches Arm B exactly because no LLM provider is configured here, so the guarded
arm falls back to the deterministic policy. Stated rather than glossed over.

Reproduce it yourself — it costs nothing and takes seconds:

```bash
.venv/Scripts/python.exe scripts/run_ablation.py
```

### The simulator is what makes this meaningful

If success on recursion depended only on a `recursion` parameter, no policy could beat
another by finding prerequisites, and the comparison would measure nothing. So the
simulator encodes the pedagogical claim itself: a missing prerequisite **suppresses**
performance on the dependent skill, and practising a blocked skill **barely teaches**.
Drilling recursion when the real gap is functions is therefore genuinely wasteful —
exactly as it is for a real student.

Half the cohort has no gap at all. That control half is what separates diagnosis from a
reflex: a policy that always redirects would look excellent without it.

### The ML component, and its honest negative result

CogniFlow uses **Bayesian Knowledge Tracing** for mastery. We also built a fitting
pipeline to learn BKT's four parameters from data, trained on simulator trajectories
deliberately **not** generated by a BKT process, and judged on held-out data:

```
recursion   AUC 0.850->0.856 (+0.006)  |  logLik -0.6370->-0.6075 (+0.0295)  ->  KEEP defaults
functions   AUC 0.849->0.852 (+0.003)  |  logLik -0.6479->-0.6200 (+0.0279)  ->  KEEP defaults
loops       AUC 0.876->0.880 (+0.003)  |  logLik -0.6264->-0.5966 (+0.0298)  ->  KEEP defaults
```

**Fitting did not beat literature defaults meaningfully, so we ship the defaults.**

The two metrics disagree, and the reason is the finding: fitting clearly improves
*calibration* (log-likelihood) but barely moves *ranking* (AUC), because AUC is
rank-invariant. Since CogniFlow consumes mastery as a **threshold comparison**, ranking
is what it depends on — so better-calibrated parameters buy it nothing here. Worth
noting the defaults already reach ~0.85 AUC against a generative process BKT cannot
represent.

We report this rather than tuning until the number looked good. That is what a held-out
set is for.

---

## Status

Built incrementally, deterministic core before anything probabilistic — an agent built
against a half-finished world produces debugging you cannot separate from model
behaviour.

| Phase | Component | State |
|---|---|---|
| 0 | Environment, dependency gate, smoke tests | ✅ Verified |
| 1 | Schemas, skill DAG, BKT mastery, policy, guard | ✅ Verified |
| 2 | Sandboxed code execution + failure taxonomy | ✅ Verified |
| 3 | RAG ingestion and retrieval | ✅ Verified |
| 4 | LLM provider abstraction, structured outputs | ✅ Verified offline |
| 5 | LangGraph orchestration, interrupt/resume | ✅ Verified |
| 6 | Full adaptive loop | ✅ Verified |
| 7 | Student simulator + ablation study | ✅ Verified |
| 8 | Event stream, CLI demo, UI | 🔄 Next |

**162 tests passing** (1 skipped — the Docker backend, which skips cleanly when Docker
isn't installed). Everything marked ✅ is independently test-verified, not self-reported.

Phase 2 highlights, each verified by running it rather than by inspection:

- The classifier was checked **exhaustively over all 12 `status × started` combinations**.
  A process that never started is *always* an infrastructure fault; a timeout where the
  process *did* start is the student's own infinite loop and counts as real evidence.
- **Student code cannot read the parent process's credentials** — verified empirically
  with a canary key, not assumed from the design.
- The sandbox reports the isolation it *actually* has. On the Windows subprocess backend
  that means no network or memory isolation, and `capability()` says so rather than
  claiming protection it lacks. The optional Docker backend provides both.

---

## Quick start

Requires **Python 3.14** (verified on 3.14.6; 3.12+ should also work).

```bash
git clone https://github.com/sohan1611/CogniFlow.git
cd CogniFlow
py -3.14 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

Verify the environment actually works before trusting anything else:

```bash
.venv/Scripts/python.exe scripts/smoke_test.py
```

This checks every dependency imports, that Chroma's local ONNX embeddings really produce
vectors, and that LangGraph's `interrupt` → checkpoint → `resume` cycle genuinely round-trips.

> **First run downloads a ~79 MB embedding model** (cached at `~/.cache/chroma/`).
> This happens once. Pre-warm it before any live demo.

See the whole thing work:

```bash
.venv/Scripts/python.exe scripts/ingest_corpus.py
.venv/Scripts/python.exe demo.py --verify
```

That runs the real graph and then checks its own claims rather than narrating them.
Expected path: **recursion -> functions -> recursion**.

Run the tests:

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

The whole suite runs **offline** — no API key, no network, no spend. Once you add a
key, verify the real wire format with one live call per provider:

```bash
.venv/Scripts/python.exe scripts/live_check.py
```

On Linux/macOS substitute `.venv/bin/python`.

### Configuration

Copy `.env.example` to `.env` and fill in whichever provider you have.
**No API key is needed for the tests** — the entire deterministic core runs offline.

```bash
cp .env.example .env
```

Keys are read from the environment only and are never committed.

---

## Architecture

```
┌──────────────────── ORCHESTRATION (LangGraph) ────────────────────┐
│  stateful graph · conditional edges · interrupt/resume · checkpoints│
└────┬───────────────────────────────────────────────────────┬──────┘
     │                                                       │
┌────▼─────────┐  ┌──────────────┐  ┌────────────┐  ┌────────▼──────┐
│ STUDENT MODEL│  │ KNOWLEDGE    │  │   TOOLS    │  │  MODEL LAYER  │
│              │  │ (RAG)        │  │            │  │               │
│ skill DAG    │  │ Chroma+ONNX  │  │ sandboxed  │  │ provider      │
│ BKT mastery  │  │ metadata     │  │ execution  │  │ abstraction   │
│ misconception│  │ filter+top-k │  │ retrieval  │  │ + failover    │
│ SQLite       │  │ citations    │  │            │  │               │
└──────────────┘  └──────────────┘  └────────────┘  └───────────────┘
```

Four decoupled layers; the orchestration layer knows only interfaces.

### Mastery — Bayesian Knowledge Tracing

Mastery is not an ad-hoc counter. CogniFlow uses **Bayesian Knowledge Tracing**
(Corbett & Anderson, 1995) with four parameters per skill — prior knowledge, learn rate,
slip, and guess. Observing a response yields a Bayesian posterior; a learning transition
is then applied.

This is chosen over `mastery += 0.1` because it is calibrated, handles *slip* (knows it,
answered wrong) and *guess* (didn't know it, answered right) explicitly, and produces a
**confidence** signal from effective sample size that the adaptation policy actually
consumes — three attempts and thirty attempts at the same mastery are not equally
trustworthy, and the policy needs to know that.

Implementation: [`app/mastery/bkt.py`](app/mastery/bkt.py).

### Repository layout

```
app/
├── models/     schemas, enums, errors — the frozen interface contract
├── mastery/    BKT, skill graph, adaptation policy, invariant guard
├── tools/      sandboxed code execution, retrieval
├── rag/        ingestion, chunking, vector store, retriever
├── llm/        provider abstraction, structured outputs, replay cache
├── graph/      LangGraph nodes, edges, state
└── config/     settings, skills.yaml curriculum
data/knowledge/ curriculum corpus for retrieval
eval/           student simulator, ablation harness
tests/          offline test suite
docs/           owner's draft, costs, architecture
```

---

## Testing

```bash
.venv/Scripts/python.exe -m pytest tests/ -q          # everything
.venv/Scripts/python.exe -m pytest tests/test_safety_invariant.py -v   # the invariant
```

The deterministic core is tested **entirely offline** — no API key, no network, no spend.
That is deliberate: adaptation logic that can only be verified by calling a paid API
isn't really verified.

---

## Limitations and safeguards

Stated plainly, because a system that models students should be honest about its reach:

- **CogniFlow is a prototype, not a deployed educational product.** It has not been
  validated against real learners, and its mastery estimates should not be used to make
  consequential decisions about a person.
- **The curriculum is narrow** — Python fundamentals, a small hand-authored skill graph.
- **Student-submitted code is executed.** The default backend runs it in a separate
  process with a timeout and a minimal environment, so student code cannot read the
  parent process's API keys. On Windows, memory and network isolation require the
  optional Docker backend; the sandbox reports its real capability level rather than
  claiming isolation it does not have.
- **No personal data is collected.** Student records are local, synthetic, and keyed by
  an arbitrary identifier.
- **BKT parameters are literature defaults** unless fitted; any fitted values are
  reported with held-out validation, and if fitting does not beat defaults we ship the
  defaults and say so.

---

## Acknowledgements

Third-party work this project builds on:

| | |
|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) / LangChain | orchestration, MIT |
| [Chroma](https://github.com/chroma-core/chroma) | vector store + ONNX embeddings, Apache-2.0 |
| [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | embedding model, Apache-2.0 |
| [NetworkX](https://networkx.org/) | prerequisite graph, BSD |
| [Pydantic](https://docs.pydantic.dev/) | structured schemas, MIT |
| [Streamlit](https://streamlit.io/) | UI, Apache-2.0 |
| Corbett & Anderson (1995) | *Knowledge tracing: Modeling the acquisition of procedural knowledge* — the BKT formulation |

Curriculum material in `data/knowledge/` was written for this project and is released
under CC BY-SA 4.0.

AI coding assistants were used during development, which the hackathon rules expressly
permit. All architecture, design decisions, and verification are the team's own, and
every test result reported here was produced by running the suite.

---

## License

MIT — see [LICENSE](LICENSE).
