# CogniFlow — Problem & Solution Brief

**Team BloodCoded · Agentic AI Hackathon, Tech Zephyr 4.0, IIT Bhubaneswar**
**Domain: Education**

---

## 1. The problem

A student fails a recursion exercise. Then fails another. Then a third.

Every AI tutor available today responds the same way: it generates an easier recursion
problem. Sometimes it adds a hint. Sometimes it explains recursion again, more slowly.

**All of that is treating a symptom.** The student's actual problem is very often not
recursion at all — it is that they do not understand what `return` does when one
function calls another. Give them an easier recursion problem and they will fail that
too, for exactly the same invisible reason. They will conclude they are "bad at
recursion" when they have never been taught the thing recursion is built on.

A good human tutor does something an LLM wrapper structurally cannot: they stop, form a
hypothesis about the *cause*, and go back a step.

### Why this is a high-friction workflow worth automating

- Diagnosis is the expensive part of tutoring, and it is exactly what does not scale.
  One teacher cannot hold a live model of forty students' prerequisite structures.
- Getting it wrong is costly and compounding. A missed prerequisite does not stay
  missed in one topic; it silently blocks every downstream topic that depends on it.
- The failure is invisible from the outside. Both the student and a naive tutor see
  "keeps failing recursion", which is precisely the wrong conclusion.

## 2. Target users

**Primary — a self-directed learner** working through programming fundamentals without
a tutor to notice that their recursion problem is really a functions problem.

**Secondary — an instructor** with more students than diagnostic attention, who needs to
know *which* prerequisite is blocking *which* student rather than a class-average score.

## 3. Why this genuinely requires an agent

Four claims, each checkable against the code rather than taken on trust.

**The action sequence is not knowable in advance.** Which skill is taught next is a
function of live mastery estimates and prerequisite-graph traversal. There is no fixed
pipeline to hardcode, because the path depends on evidence that does not exist yet.

**The system revises its own model of the world.** Every submission updates a persistent
Bayesian belief about the student, and that belief changes future decisions. This is a
feedback loop over durable state, not a chain of prompts.

**It reasons about causes, not symptoms.** Repeated failure triggers a *prerequisite
investigation*, which can reassign the target skill. The agent changes its own
objective — the thing a wrapper cannot do.

**It genuinely suspends and resumes.** The graph checkpoints to disk and halts at the
student-interaction point. A separate process, minutes later, resumes the same thread.
Verified across two OS processes, not merely in-process.

### The sharpest objection, answered

*"Why not just write rules? Or just ask an LLM?"*

Neither alone is sufficient, and CogniFlow is deliberately both:

- **Rules alone** cannot author a novel exercise grounded in a specific student's
  misconception and a specific page of curriculum.
- **An LLM alone** cannot be trusted with a student's learning path. It has no
  calibrated model of what they know, and it will happily advance a student who is not
  ready.

So the LLM *proposes* and a deterministic guard *disposes*. The model does the
generative work; the arithmetic does the arithmetic.

## 4. The solution

An agentic tutor built on four decoupled layers — LangGraph orchestration, a Bayesian
student model over a prerequisite DAG, a grounded retrieval layer, and a role-based
model layer with failover. Eleven graph nodes, of which **three call a model**.

The behaviour it exists to produce:

```
Recursion  →  Functions  →  Function-call tracing  →  Reassessment  →  Return to Recursion
```

Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

### What is actually built

| | |
|---|---|
| **163 tests**, all offline | no API key, no network, no spend |
| Interrupt/resume | verified **across two OS processes** |
| Safety invariant | infra failure cannot move mastery — enforced by types, tested adversarially |
| Sandbox | student code cannot read the parent's API keys (verified with a canary) |
| RAG | skill-filtered retrieval with citations back to the source page |
| Evaluation | three-arm ablation over 80 simulated students with planted gaps |

## 5. Expected impact

**Measured, not asserted.** Against a cohort of 80 simulated students where the
prerequisite gap is *planted* — so detection is scored exactly rather than judged:

| | no prerequisite awareness | CogniFlow |
|---|---|---|
| Median attempts to true mastery | 14 | **10** (29% fewer) |
| Planted gap identified | **0%** | **65%** |
| Error in its model of the student | 0.211 | **0.106** (halved) |
| Redirected a student with no gap | 0% | 25% |

The last row is the honest cost, reported rather than hidden: diagnosis is not free, and
one student in four with no gap gets a detour they did not need.

**Why the middle row is the real result.** The no-prerequisite arm finds the gap in 0% of
cases — not because it is badly tuned, but because it *cannot*, by construction. That is
the difference between adjusting difficulty and understanding causes, and it is the whole
argument for the architecture.

**Where this could go.** The prerequisite graph is data, not code. Swapping
`skills.yaml` and the curriculum corpus retargets the system at a different subject
entirely. The 25% false-redirect rate is the obvious next thing to attack, most likely
by requiring more evidence before a detour.

## 6. Limitations we are not hiding

- **A prototype, not a deployed product.** Not validated on real learners. Its mastery
  estimates should not drive consequential decisions about a person.
- **The evaluation is simulated.** The cohort is synthetic, which is what makes exact
  scoring possible — and also what stops it from being evidence about real students.
- **Narrow curriculum.** Python fundamentals, a hand-authored eight-skill graph.
- **Sandbox isolation is honestly reported.** On the Windows subprocess backend there is
  no network or memory isolation, and `capability()` says so rather than claiming
  otherwise. The optional Docker backend provides both.
- **No live-API verification yet.** Every result here was produced offline against
  deterministic fallbacks and a stub model. `scripts/live_check.py` closes that gap in
  one command using a free Groq or Gemini key — no paid API is required.

## 7. Responsible use

No personal data is collected; student records are local, synthetic, and keyed by an
arbitrary identifier. Student-submitted code executes in a separate process with a
timeout and a minimal environment, so it cannot read the host's credentials. Third-party
work is acknowledged in the README. AI coding assistants were used during development,
which the rules expressly permit; the architecture, decisions, and verification are the
team's own, and every number reported here was produced by running the code.
