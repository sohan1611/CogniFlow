# CogniFlow — Cost Breakdown

**Budget: ₹2,500 (~$25). Projected spend: ₹0. Reserve retained: ₹2,500.**

> **Note:** an earlier draft assumed a Claude subscription provided API access. It does
> not — see §5. The provider chain now leads with genuinely free tiers, so the ₹0 figure
> holds without qualification.

Every component below is open-source, runs locally, or sits inside a free tier. The
constraint that actually binds is not the rupee figure — it is the design rule it
implies: **no GPU training, no paid data feeds, no paid third-party APIs.**

---

## 1. Build phase — one-time

| # | Component | Choice | Why it is free | Cost |
|---|---|---|---|---|
| 1 | Orchestration | LangGraph 1.2.11 + `langgraph-checkpoint-sqlite` 3.1.1 | MIT | ₹0 |
| 2 | LLM — primary | **Groq free tier** (`langchain-groq`) | Genuinely free API tier | **₹0** |
| 3 | LLM — fallback | **Google Gemini free tier** (AI Studio) | Genuinely free API tier | **₹0** |
| 3b | LLM — optional | Anthropic API | ⚠️ **Metered, pay-per-token. NOT covered by a Claude Pro/Max subscription.** Opt-in only. | see §5 |
| 4 | **Embeddings** | Chroma built-in ONNX (`all-MiniLM-L6-v2`) | Local inference, no API calls, **no PyTorch** | ₹0 |
| 5 | **Vector store** | Chroma 1.5.9, local persistent | Runs in-process | ₹0 |
| 6 | Code sandbox | `subprocess` (default), Docker (opt-in) | stdlib / Docker CE free | ₹0 |
| 7 | Student state | SQLite (stdlib) + NetworkX 3.6.1 | Bundled / BSD | ₹0 |
| 8 | Checkpoints | `SqliteSaver` | Local file | ₹0 |
| 9 | UI | Streamlit 1.63.0 | Apache-2.0 | ₹0 |
| 10 | Source hosting | GitHub public repo | Free | ₹0 |
| 11 | Demo hosting | Hugging Face Spaces free tier | Free (CPU) | ₹0 |
| 12 | Curriculum corpus | Original text written for this project | Authored in-house, CC BY-SA | ₹0 |
| | **Build subtotal** | | | **₹0** |

## 2. Run phase — recurring

| Activity | Volume | Provider | Cost |
|---|---|---|---|
| Development / debugging | ~500 calls | Groq free tier + disk replay cache | ₹0 |
| Ablation cohort, 3 arms | policy-only, no model calls at all | none | ₹0 |
| BKT parameter fitting | fully offline (EM on synthetic trajectories) | none | ₹0 |
| Demo runs | ~15 calls each | Groq free tier | ₹0 |
| | | **Run subtotal** | **₹0** |

## 3. Reserve — what the ₹2,500 is actually held for

| Contingency | Estimate | Trigger |
|---|---|---|
| ⭐ **Mobile hotspot / data pack for the finale** | ₹300–600 | **Recommended spend.** Rulebook §9 requires a *live, unscripted* demo and teams bring their own credentials. Venue Wi-Fi failing mid-demo is the classic way a working project dies on stage. Cheapest insurance available. |
| Paid LLM overflow | ₹500 | Only if ablation runs exceed free-tier quota |
| Hosting upgrade | ₹0–800 | Only if judges must click a link and Spaces cold-start proves unacceptable |
| Domain name | ₹0 | Not needed |
| **Unallocated** | **₹600+** | — |

## 4. Explicitly excluded — ₹0 by design

No GPU compute · no model fine-tuning · no paid vector DB (Pinecone, Weaviate) ·
no paid embeddings API · no paid data feeds · no PyTorch · no paid code sandbox
(E2B, Judge0) · no paid observability.

---

## 5. Correction: a Claude subscription is not an API key

**An earlier version of this document was wrong**, and the error is worth recording
because it would have quietly turned a zero-cost project into a paid one.

The plan assumed "Claude is already paid for" meant Anthropic API access. It does not.
These are separate products with separate billing:

| | What it covers | Cost here |
|---|---|---|
| **Claude Pro / Max subscription** | claude.ai and Claude Code | already held; grants **no API access** |
| **Anthropic API key** | `api.anthropic.com`, metered per token | a **separate purchase** |

**What changed as a result:** the provider chain now leads with **Groq**, then **Google
Gemini** — both of which offer genuinely free API tiers ample for this project — with
Anthropic last and opt-in. A test now enforces that the paid provider cannot lead, so
this cannot regress silently:

```python
assert chain[0].provider != "anthropic", "the paid provider must not lead"
```

### If you do want to use the Anthropic API anyway

It is stronger at structured output. Rough estimate at Claude Opus 5 rates
($5 / $10⁶ input, $25 / $10⁶ output), ~2K in and ~500 out per call:

| | Calls | Estimate |
|---|---|---|
| One demo run | ~15 | ~$0.35 (~₹30) |
| Development and tuning | ~300 | ~$7 (~₹600) |
| **Total if adopted** | | **~$8, well inside the ₹2,500 reserve — but not ₹0** |

Enable it deliberately:

```bash
COGNIFLOW_PROVIDER_ORDER=anthropic,groq,google
```

**Recommendation: don't.** The free tiers are sufficient, the architecture is
provider-agnostic by design, and the judging criteria reward the system, not the model
behind it.

---

## 6. Corrections applied to the original cost estimate

The initial estimate reached the right total but contained three errors and two
omissions. Recorded here because each changed a real decision:

| Item | Original | Correction |
|---|---|---|
| LLM | `gpt-4o-mini` or Gemini 1.5 Flash | Both outdated; Gemini 1.5 Flash is retired. Claude is already owned, so it is both cheaper (₹0 marginal) and stronger at structured output. |
| Framework | "LangGraph / CrewAI" | **CrewAI cannot satisfy this spec.** Checkpointed `interrupt`/`resume` is LangGraph-specific and is the backbone of the human-in-the-loop design. |
| **Embeddings** | *omitted* | The one RAG line that can actually cost money. Chroma's ONNX path keeps it at ₹0 **and avoids a ~2 GB PyTorch dependency** — the single most valuable correction here. |
| **Vector store** | *omitted* | Chroma, local persistent. |
| Hosting | HF Spaces | Correct, but free Spaces sleep. Local `make demo` is the real demo; Spaces is the clickable link. |

---

## 6. Operational note — the one non-obvious cost

Chroma's `all-MiniLM-L6-v2` model is a **one-time 79 MB download** (167 MB on disk),
cached at `~/.cache/chroma/onnx_models/`. On the build machine it took several minutes.

It costs ₹0, but it costs **time on a machine that has never run CogniFlow before** —
which includes any fresh laptop used at the finale. **Pre-warm the cache as part of
demo-day setup.** A judge watching a progress bar is exactly the failure the hotspot
reserve exists to prevent, and this one is avoidable for free.
