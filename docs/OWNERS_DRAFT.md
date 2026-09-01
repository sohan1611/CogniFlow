# CogniFlow — Owner's Draft

**Team BloodCoded · 2 members · Agentic AI Hackathon, Tech Zephyr 4.0, IIT Bhubaneswar**
**Stage 1 submission: 12–13 September 2026**

---

## 1. Charter

CogniFlow is an agentic tutoring orchestrator. It models what a student knows as a
Bayesian belief over a prerequisite graph of skills, and when it infers that a surface
failure is caused by an underlying gap, **it reassigns its own teaching objective**.

The system is finished when it can do this, through real graph state transitions rather
than a script:

```
Recursion  →  Functions  →  Function-call tracing  →  Reassessment  →  Return to Recursion
```

**Success criteria, in priority order:**

1. The recursion → functions redirect happens because the prerequisite graph and live
   mastery estimates say it should — provable by reading the event log, not by trusting
   a demo narration.
2. An injected infrastructure failure leaves the student's mastery **bit-for-bit
   unchanged**.
3. LangGraph genuinely suspends at the student-interaction point and resumes in a
   *separate process* from the same checkpoint.
4. An ablation shows the full architecture beats both an LLM-only and a rules-only
   baseline on a simulated cohort with planted gaps.

If we run out of time, 1–3 are the submission. Item 4 is what makes us hard to beat.

---

## 2. What this project is NOT

Writing these down so scope creep has to argue with a document:

- ❌ Not a chatbot with a quiz generator attached.
- ❌ Not a multi-agent system. One goal, one coherent state. The rulebook says
  multi-agent is not mandatory, and coordination overhead would buy us nothing.
- ❌ Not a RAG demo. Retrieval has exactly two consumers, both justified.
- ❌ Not a fine-tuning project. The one ML component (BKT parameter fitting) is
  ~100 lines and has a stated fallback.
- ❌ Not a platform. A smaller complete system beats a larger unfinished one.

---

## 3. The claim we have to defend

Judges get 5 minutes of technical Q&A and rulebook §5 lets them interrogate
architecture, code, models, and design decisions. Our answer to *"why isn't this a
wrapper?"* is:

> **The model proposes; the policy guard disposes.**

An LLM emits a structured `AdaptationDecision`. A deterministic guard validates it
against hard invariants and overrides it when invalid, logging the override. This buys
three things simultaneously:

| | |
|---|---|
| **Safety** | The LLM cannot corrupt a student's learning path |
| **A metric** | "The guard overrode the model in N% of decisions" — our ablation headline |
| **Demo reliability** | Routing is deterministic, so the demo path holds even if the LLM says something odd on stage |

Supporting answer, when asked why so little of the system is an LLM:

> **We do not use an LLM where arithmetic is already correct and free.**

Only three call sites use a model: problem generation, conceptual grading, and
misconception analysis. Diagnosis, routing, mastery, and prerequisite selection are
deterministic and unit-tested.

---

## 4. Ownership split

Two people, working in parallel against a frozen interface.

| | **Owner A — Core & Tools** | **Owner B — Agents & Orchestration** |
|---|---|---|
| **Phases** | 0, 1, 2, 3, 7 | 4, 5, 6, 8 |
| **Owns** | schemas, skill DAG, BKT, policy + guard, sandbox, failure taxonomy, RAG ingestion and retrieval, student simulator, ablation harness | LLM provider abstraction, structured outputs, LangGraph nodes and edges, interrupt/resume, checkpointing, event stream, demo runner, UI |
| **Tests** | 1–9, 12, 14, 17 | 10, 11, 13, 15, 16, 18 |
| **Q&A lead on** | "how does mastery actually update?", "why won't infra bugs hurt students?" | "show me the graph pausing", "what happens when the LLM fails?" |

**Shared:** README, architecture diagram, demo video (A narrates architecture, B drives
the live demo), submission checklist.

### The interface contract

Frozen at the end of Phase 1: `app/models/schemas.py`, `app/models/enums.py`, and the
`policy.decide()` / `guard.validate()` signatures. Both owners code against these
independently. **Changing them requires both owners to agree** — that constraint is what
allows two people to work without blocking each other.

### Definition of done, per phase

- Tests green, and the *previous* phases' tests still green
- No TODO / FIXME / stub in any core path
- Module docstrings name the invariant the module protects

---

## 5. Non-negotiable rules

1. **Contributor list stays two humans.** No `Co-Authored-By:` trailers, no Dependabot,
   no commit-authoring bots. See [AGENTS.md](../AGENTS.md) RULE 1. Verify before every
   push.
2. **No credentials in the repo.** `.env` is gitignored; `.env.example` holds names
   only. Rulebook §6 forbids it and §13 makes it a disqualification path.
3. **`SystemFault` can never change mastery.** Enforced by type, tested adversarially.
4. **Deterministic where it matters.** Routing, arithmetic, and limits are code, not
   prompts.
5. **Acknowledge third-party work** (rulebook §10) in the README.

---

## 6. Schedule

| Days | Work | Owner |
|---|---|---|
| Sep 1 | Phase 0 foundation + Phase 1 domain core | A |
| Sep 2–3 | Phase 2 sandbox and failure taxonomy | A |
| Sep 3–4 | Phase 3 RAG ingestion and retrieval | A |
| Sep 4–5 | Phase 4 LLM layer, structured outputs, failover | B |
| Sep 5–7 | Phase 5 LangGraph, interrupt/resume, checkpointing | B |
| Sep 7–8 | Phase 6 full adaptive loop | B |
| Sep 8–9 | Phase 7 simulator + ablation | A |
| Sep 9–10 | Phase 8 event stream, CLI demo, UI | B |
| Sep 10–11 | Freeze: brief, architecture diagram, video, README | both |
| Sep 12 | Clean-machine run, secret scan, **submit early** | both |
| Sep 13 | Buffer only | — |

**Cut order if we slip:** Streamlit UI first, then the Docker sandbox backend, then the
BKT parameter fitting (defaults still work). **Never cut the ablation** — it is the
differentiator. **Never cut the safety invariant tests** — they are the credibility.

---

## 7. Risks we are actively managing

| Risk | Mitigation | Owner |
|---|---|---|
| Venue Wi-Fi fails during the live demo | Mobile hotspot from the ₹2,500 reserve | both |
| Free-tier rate limit mid-demo | Claude primary, automatic provider failover | B |
| LLM says something odd on stage | Routing is deterministic — path holds regardless | B |
| Chroma model download on a fresh machine | **Pre-warm the 79 MB ONNX cache before demo day** | A |
| Judge has no Docker | subprocess sandbox is the default | A |
| Two people, twelve days | Phases 0–6 are the submission; 7–8 differentiate; 9 is cuttable | both |

---

## 8. Live status

| Phase | State |
|---|---|
| 0 - Foundation | DONE. Verified: deps install clean on Python 3.14.6; Chroma ONNX embeddings (dim 384) and LangGraph interrupt/resume both round-trip |
| 1 - Domain core | DONE. Verified: recursion -> functions redirect confirmed through real policy code; 30 adversarial safety-invariant tests |
| 2 - Sandbox + failure taxonomy | DONE. Verified: classifier exhaustive over all 12 status x started combinations; credential isolation confirmed with a canary key; end-to-end demo beat proven (runtime error and student infinite loop move mastery, injected SANDBOX_FAILURE does not) |
| 3 - RAG | DONE. Verified: skill-filtered retrieval isolates correctly in both directions; querying the call stack under skill=functions returns section 3.4 as top hit - the exact material the prerequisite redirect needs; degraded path returns RETRIEVAL_FAILURE without raising |
| 4 - LLM layer | NEXT |
| 5-10 | Not started |

**92 tests passing, 1 skipped** (Docker backend, skips cleanly when unavailable).

### Known issue being managed

Codex cannot read repository files or spawn processes in this environment. Work orders
must therefore INLINE every existing signature it needs. Phase 2 lost a round to this -
it guessed the wrong module for the enum imports. Phase 3's spec inlines the API.
