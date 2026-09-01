# CogniFlow — Cost Breakdown

**Budget: ₹2,500 (~$25), excluding Claude (already owned).**
**Projected spend: ₹0. Reserve retained: ₹2,500.**

Every component below is open-source, runs locally, or sits inside a free tier. The
constraint that actually binds is not the rupee figure — it is the design rule it
implies: **no GPU training, no paid data feeds, no paid third-party APIs.**

---

## 1. Build phase — one-time

| # | Component | Choice | Why it is free | Cost |
|---|---|---|---|---|
| 1 | Orchestration | LangGraph 1.2.11 + `langgraph-checkpoint-sqlite` 3.1.1 | MIT | ₹0 |
| 2 | LLM — primary | Claude via `langchain-anthropic` 1.7.0 | Already owned → ₹0 marginal | ₹0 |
| 3 | LLM — bulk eval | Groq / Gemini free tiers | Free tier covers cohort runs | ₹0 |
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
| Development / debugging | ~500 calls | Claude (owned) + disk replay cache | ₹0 |
| Ablation cohort, 3 arms | policy-only, no content generation | Groq / Gemini free tier | ₹0 |
| BKT parameter fitting | fully offline (EM on synthetic trajectories) | none | ₹0 |
| Demo runs | ~15 calls each | Claude (owned) | ₹0 |
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

## 5. Corrections applied to the original cost estimate

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
