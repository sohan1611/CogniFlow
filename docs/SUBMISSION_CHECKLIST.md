# CogniFlow — Stage 1 Submission Checklist

**Deadline: 12–13 September 2026** · Team BloodCoded

---

## Rulebook §6 — required deliverables

| # | Requirement | Artefact | Status |
|---|---|---|---|
| 1 | Problem & solution brief | [BRIEF.md](BRIEF.md) — problem, users, why agentic, solution, impact | ✅ |
| 2 | System architecture / workflow | [ARCHITECTURE.md](ARCHITECTURE.md) — Mermaid diagrams, renders in GitHub | ✅ |
| 3 | Source code / public repo | [github.com/sohan1611/CogniFlow](https://github.com/sohan1611/CogniFlow) | ✅ |
| 4 | 3–5 minute demo video | [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — script ready | ⬜ **record** |
| 5 | Runnable / deployed version | `make demo`, `make ui`, `make verify` | ✅ |

## Repo hygiene

| Check | Command | Status |
|---|---|---|
| No credentials committed (§6) | `git ls-files \| grep -E '^\.env$'` → empty | ✅ |
| Setup instructions | README quick start, verified end to end | ✅ |
| Dependencies pinned | `requirements.txt` — the resolved set, not guesses | ✅ |
| Env configuration documented | `.env.example` (names only, no values) | ✅ |
| Architecture docs | `docs/ARCHITECTURE.md` | ✅ |
| Third-party acknowledged (§10) | README acknowledgements | ✅ |
| Limitations & safeguards stated (§11) | README + BRIEF §6 | ✅ |
| Contributor list is two humans | `make scan` → exit 0 | ✅ |
| License | MIT | ✅ |

## Release gates — must all pass before submitting

```bash
make test        # 204 passed, 1 skipped
make verify      # 7/7 self-checks, path recursion -> functions -> recursion
make ablation    # three-arm table reproduces
make scan        # exit 0
```

Plus, on a machine that has never run CogniFlow:

```bash
git clone https://github.com/sohan1611/CogniFlow.git
cd CogniFlow && make install && make ingest && make verify
```

Time it. **If it takes more than five minutes or needs one undocumented step, fix that
before submitting** — a judge who cannot run it scores only what they can see.

> ⚠️ The first `make ingest` on a fresh machine downloads a **79 MB** embedding model.
> It is a one-time cost and it is free, but it is *slow*. **Pre-warm it before any live
> demo** rather than letting a judge watch a progress bar.

---

## Outstanding before submission

### 1. ✅ Live API verification — DONE

**Verified against Groq (`openai/gpt-oss-120b`, free tier) on 2 Sep 2026.**
`make live` passes, and `demo.py --live --verify` passes **all 7 self-checks** with
model-authored problems.

Going live found three real defects that offline testing could not:

1. **`.env` was never loaded.** Nothing called `load_dotenv()`, so a key sitting in
   `.env` was invisible and every provider reported "no credentials" — indistinguishable
   from a missing key.
2. **The test-case runner crashed on model output.** It assumed a `name` field the
   template always emits and a real model does not. Model output is untrusted input; a
   generation quirk must never end a session.
3. **A missing guard invariant.** The model proposed `ADVANCE` while a prerequisite
   return was still owed, silently abandoning the skill the student came for. The
   deterministic policy never does this because of branch ordering, so the gap was
   invisible until a real provider proposed freely. Now blocked by
   `must_return_to_original_objective`, with regression tests.

The third is the strongest possible argument for the architecture: **the guard caught
the model doing something the rules never would.**

```bash
# Free key from console.groq.com, then:
.venv/Scripts/python.exe scripts/live_check.py
.venv/Scripts/python.exe demo.py --live --verify
```

> **Model ids drift.** `llama-3.3-70b-versatile` was not available on this account;
> `openai/gpt-oss-120b` is. List what your key can reach before assuming:
> `client.models.list()` via the `groq` SDK. Override with `COGNIFLOW_GROQ_MODEL`.

**Use a free tier.** Groq and Google both offer genuinely free API tiers that are ample
for this project, and the chain leads with them by default. An Anthropic API key is
metered pay-per-token and is **billed separately from a Claude Pro/Max subscription** —
a subscription grants no API access. See [COSTS.md §5](COSTS.md).

**Do this before recording the video.** Two consequences if skipped:

- The problem *text* is templated rather than model-authored, so the second generated
  problem logs `repeat=True` — the anti-repetition mechanism correctly *detects* the
  duplicate, but the template cannot vary. A live model resolves this.
- Arm C of the ablation is identical to arm B, because the guarded arm falls back to
  rules with no provider. With a key, the **guard-override rate** becomes a real number
  and a much stronger Q&A answer.

### 2. Record the demo video

Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Run `make verify` three times first and confirm
the path is identical — a demo you cannot reproduce will fail in front of judges.

### 3. Final pass

- [ ] Re-run all four release gates
- [ ] Clean-machine clone test, timed
- [ ] `make scan` immediately before the final push
- [ ] Submit **on the 12th**, not the 13th — leave a day of margin

---

## Known limitations (stated, not hidden)

These are in the README and BRIEF deliberately. A system that models students and knows
its own reach is more credible than one that does not.

- Prototype, not validated on real learners; not for consequential decisions about a person
- Evaluation is simulated — exact scoring is possible *because* the cohort is synthetic,
  which is also why it is not evidence about real students
- Narrow curriculum: Python fundamentals, eight skills with a chapter each
- 7.5% false-redirect rate on students with no gap (down from 25%) — see docs/ABLATION.md
- Windows subprocess sandbox has no network or memory isolation; `capability()` says so,
  and the Docker backend provides both

---

## Finale preparation (Stage 2, on campus)

Rulebook §8: **50% of the finale score is defending this build.** §9 requires a live,
unscripted demo, and teams bring their own hardware and credentials.

- [ ] **Mobile hotspot / data pack** — venue Wi-Fi failing mid-demo is the classic way a
      working project dies on stage. Budgeted in [COSTS.md](COSTS.md).
- [ ] Pre-warm the Chroma model cache on the demo laptop
- [x] `.env` populated with a working key, `make live` green (Groq free tier)
- [ ] Rehearse the Q&A table at the end of DEMO_SCRIPT.md
- [ ] Owner A leads on mastery and safety questions; Owner B on the graph and failure
      handling ([OWNERS_DRAFT.md](OWNERS_DRAFT.md))
