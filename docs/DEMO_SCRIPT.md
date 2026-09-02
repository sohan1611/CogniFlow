# CogniFlow — 3–5 minute demo video script

**Two speakers.** A narrates architecture, B drives the machine. Total target: **4:30**.

> **Golden rule:** never say a thing the screen is not showing. Judges have seen a lot of
> narrated slideware. Everything below is on-screen output from a real run.

---

## Rulebook §7 — say the judges' words

§7 names the workflow a demo should showcase: **Goal → Decision → Action → Evaluation →
Adaptation → Outcome.** The system already does all six — they are distinct nodes in the
graph — but an earlier draft of this script never used those six words, which leaves a
judge holding a rubric to map it themselves. Say the word, then point at the line.

| §7 stage | On screen | Where |
|---|---|---|
| **Goal** | `[plan_action] target_skill=recursion` | 0:45 |
| **Decision** | `[adapt] action=… overridden=…` — model proposes, guard disposes | 1:15 |
| **Action** | `[retrieve]` then `[generate_problem]`, then `[execute]` in the sandbox | 0:45 |
| **Evaluation** | `[execute] outcome=…` and `[update_mastery] 0.350 -> 0.204` | 1:15 |
| **Adaptation** | `[prereq_redirect] recursion -> functions` — **the moment** | 1:30 |
| **Outcome** | `[finalize] status=COMPLETED`, `recursion 0.35 -> 0.88` | 2:45 |

§7 also asks for **failures, unexpected inputs, tool failures, and changing conditions**.
Three are already in the run below, and naming them as a set is worth ten seconds:

| §7 asks for | We show |
|---|---|
| Tool failure | injected `SANDBOX_FAILURE` → recovery, mastery untouched (2:15) |
| Changing conditions | Groq hits its 8k-tokens/minute ceiling mid-run and the chain **fails over to Google live** — `provider=google:…` appears in the stream |
| Unexpected input | `import os` → `EXECUTION_REFUSED`, a SystemFault, mastery unmoved (optional beat) |

---

## Before you record

```bash
python run.py ingest        # build the retrieval index (one-time)
python run.py check         # one real call per provider, proves the wire format FIRST
python run.py live          # the demo against real models, with self-verification
```

**Record the live run, not the offline one.** Both free keys are configured, and a live
run now completes with **zero degraded generation** — every problem is model-authored.
The offline path prints `degraded=True` and repeats a templated problem, and while §10
prohibits fabricated *results* rather than templated prose, a judge who sees
`degraded=True` will reasonably ask what else was not real. Do not hand them that
question when the live path works.

Run `python run.py live` **three times** and confirm the path is identical each time. If it
varies, stop and fix that before recording — a demo you cannot reproduce is a demo that
will fail in front of judges. The path is deterministic by construction, so variation
means something is wrong, not that the model had an off day.

Terminal at ~110 columns, large font. Close everything else.

---

## 0:00 – 0:25 · The problem (A, on the seeded state)

> "A student fails a recursion exercise. Twice. Every AI tutor does the same thing here:
> it generates an easier recursion problem.
>
> But the student's real problem usually isn't recursion. It's that they don't
> understand what `return` does when one function calls another. Give them an easier
> recursion problem and they'll fail that too — for the same invisible reason.
>
> CogniFlow is built to notice that and go back a step."

**Screen:** the seeded model. Point at `functions 0.55` and `recursion 0.35`.

---

## 0:25 – 0:45 · What is and isn't scripted (A)

> "One thing before we run it. The *student* is scripted — what they submit, and when.
> **Nothing the tutor does is scripted.** Every decision you're about to see is computed
> from a prerequisite graph and live Bayesian estimates of what this student knows.
>
> At the end the demo checks its own claims, so you don't have to take my word for it."

**Why this beat exists:** it pre-empts the "is this hardcoded?" question rather than
waiting for it in Q&A.

---

## 0:45 – 1:30 · Attempt 1 (B runs `python run.py demo`)

**Screen:** the live event stream. Pause on these lines:

```
[diagnose]  target_skill=recursion  mastery=0.350  missing_prerequisites=['functions']
[retrieve]  skill=recursion  chunks=4     evidence: 05_recursion.md#5.1 The idea
[execute]   status=runtime_error  started=True  outcome=STUDENT_RUNTIME_ERROR
[mastery]   recursion  0.350 -> 0.204
[adapt]     action=RETRY_VARIATION
```

> B: "Real diagnosis, real retrieval with citations back to the source page, real code
> execution in a sandbox. The student's code raised — mastery drops, and the agent
> retries a variation. So far, a normal tutor."

---

## 1:30 – 2:15 · **THE MOMENT** — attempt 2 (A narrates over the screen)

```
[mastery]          recursion  0.204 -> 0.176
[misconception]    implicates=functions  source=deterministic
   'recursive call is computed but not returned, so the function yields None'
[adapt]            action=REVISIT_PREREQUISITE  target_skill=functions
   reason: diagnosed misconception implicates 'functions'
[prereq_redirect]  from_skill=recursion -> to_skill=functions
[plan_action]      target_skill=functions  teaching_mode=CODE_TRACE
[retrieve]         skill=functions  evidence: 03_functions.md#3.4 The call stack
```

> A: "**There.** Second failure. The agent did *not* generate an easier recursion
> problem. It walked the prerequisite graph, found `functions` was the weakest unmastered
> dependency, and **reassigned its own objective**.
>
> And look at *why*. It read the actual error — a `NoneType` arithmetic failure — and
> diagnosed the cause: the recursive call is computed but never returned. That's a
> `return` problem, which is a **functions** problem wearing a recursion costume.
>
> The teaching mode switched to `CODE_TRACE`, so it isn't repeating the approach that
> already failed. And retrieval followed it: it's pulling *The call stack* from the
> functions chapter."

**Slow down here.** This is the whole project. Give it room.

---

## 2:15 – 2:45 · The infrastructure failure (B)

```
[execute]   status=sandbox_error  started=False  outcome=SANDBOX_FAILURE
[recover]   fault=SANDBOX_FAILURE  mastery_untouched=True
   reason: infrastructure fault; student model deliberately left unchanged
```

> B: "We inject a sandbox failure mid-session. Watch the mastery number — **it doesn't
> move.**
>
> `StudentOutcome` and `SystemFault` are disjoint types, and mastery is reachable only
> from the first. If *our* infrastructure breaks, the student doesn't pay for it. That's
> enforced by the type system, not by a conditional someone has to remember."

---

## 2:45 – 3:15 · The return (A)

```
[mastery]        functions  0.550 -> 0.869
[adapt]          action=REVISIT_PREREQUISITE  target_skill=recursion
   reason: prerequisite mastered, returning to original target
[prereq_return]  returning_to=recursion
[mastery]        recursion  0.176 -> 0.567 -> 0.877
```

> A: "Functions is mastered. The agent pops its return stack and goes back to what the
> student originally came for. Recursion: **0.35 to 0.88.**"

**Screen:** `Learning path : recursion -> functions -> recursion`

---

## 3:15 – 3:45 · It checks its own claims (B)

```
[PASS] visited recursion -> functions -> recursion
[PASS] first failure retried, second escalated to prerequisite
[PASS] redirect target was chosen as the weakest prerequisite
[PASS] returned to the original objective
[PASS] infrastructure fault did not move mastery
[PASS] student ended ahead on recursion
```

> B: "The demo verifies itself. And the same code path is asserted in CI against the
> event stream and the database — not against printed text. A hardcoded narration
> couldn't pass those tests."

---

## 3:45 – 4:20 · Does it actually help? (A runs `python run.py ablation`)

```
arm                  mastered   med steps  gap found   false rdr
A_no_prerequisite      100.0%          16       0.0%        0.0%
B_rules                100.0%          13      57.5%        7.5%
```

> A: "Eighty simulated students, prerequisite gaps *planted* so detection is scored
> exactly. Prerequisite-aware adaptation reaches mastery in **19% fewer attempts** and
> finds the gap **57%** of the time. The arm without a skill graph finds it **0%** — it
> can't, by construction.
>
> And the honest cost: it still redirects **7.5%** of students who had no gap. That was
> 25% until we required evidence before a detour. Diagnosis isn't free, and we report
> it."

---

## 4:20 – 4:30 · Close (A)

> "Three of eleven nodes call a model. Diagnosis, routing, and mastery are deterministic
> and unit-tested, because arithmetic is already correct and free.
>
> The model proposes. The guard disposes. That's CogniFlow."

---

## Optional 20s add-on — the live interrupt

If you have room, `python run.py ui` → **Be the student** → Start session:

> "The graph is suspended at `await_student`, checkpointed to disk. It's not looping —
> it has genuinely stopped. A *separate process* can resume this thread. Type an
> answer and it continues from that checkpoint."

Strong for the finale, where a judge can type the answer themselves.

---

## Q&A preparation

| Likely question | Answer |
|---|---|
| "Is the redirect hardcoded?" | Show `app/mastery/policy.py`. It's graph traversal over live mastery. Test 18 asserts on state transitions, not text. |
| "Why not just an LLM?" | It has no calibrated model of the student and will advance someone who isn't ready. The LLM proposes; the guard disposes. |
| "Why not just rules?" | Rules can't author a novel exercise grounded in a specific misconception and a specific page. |
| "Why so few LLM calls?" | We don't use an LLM where arithmetic is already correct and free. |
| "Is mastery just a counter?" | Bayesian Knowledge Tracing, Corbett & Anderson 1995. Models slip and guess; yields a confidence signal the policy consumes. |
| "Did you train anything?" | We built BKT parameter fitting. It produced a **negative** result on held-out data, so we ship literature defaults and report it. Same with a retrieval reranker: recall@4 was already 100%, so we measured it and didn't build it. |
| "Is the sandbox real?" | Separate process, timeout, minimal env — student code can't read our API keys, verified with a canary. `capability()` honestly reports what Windows subprocess *doesn't* isolate. Docker backend adds network and memory isolation. |
| "What breaks it?" | 7.5% false-redirect rate — a student with no gap still gets an unnecessary detour. It was 25%; requiring evidence cut it. Both numbers are in the results table. |

**If something fails live:** say so plainly, run `python run.py verify`, and keep going. The event
stream is the evidence; a recovered failure demonstrates the recovery path you claimed.
