# Deploying CogniFlow

The rulebook accepts a local setup as the runnable version, and `python run.py demo` is that. A
hosted link is stronger: a judge can click it without cloning anything.

**Cost: ₹0.** Hugging Face Spaces CPU basic is free, and the app runs on a free Groq key.

---

## Before you deploy: the security position

This app **executes Python that strangers submit**. That is fine locally, where you are
running your own code. It is not fine on a public URL without a gate, so submissions pass
a **static allowlist before any process is created**:

| | |
|---|---|
| Allowed | `math`, `itertools`, `collections`, `re`, `random`, `json`, … — everything a Python-fundamentals exercise needs |
| Refused | filesystem, network, process spawning, `eval`/`exec`/`open`, and the `__subclasses__` escape ladder |
| On refusal | reported as `EXECUTION_REFUSED`, a **SystemFault** — a student's mastery never moves for it |

The gate is an **allowlist, not a blocklist**, because blocklists lose: `socket` is
reachable through `urllib`, `urllib` through `__import__`, and so on. 35 adversarial
tests in `tests/test_restrictions.py` cover the escape routes.

`deploy/space/app.py` forces `COGNIFLOW_RESTRICT_CODE=1` in code, so a misconfigured
secret cannot silently open it up.

> Hugging Face also runs each Space in its own container, so the platform is a second
> layer. Neither layer is relied on alone.

---

## Pick a host first

There are two free routes, and the better one depends on your account age.

| | Streamlit Community Cloud | Hugging Face Space (Gradio) |
|---|---|---|
| Cost | free | free |
| UI it runs | `ui.py` — the Streamlit UI | `app_gradio.py` |
| Deploys from | **your GitHub repo directly** | a separate push of `build/space` |
| Gotcha | none known | free Gradio Spaces run on **ZeroGPU**, which requires a **verified account older than 30 days** |
| Effort | ~3 minutes | ~10 minutes |

**Streamlit Community Cloud is the simpler route** and has no account-age gate: it
deploys straight from `github.com/sohan1611/CogniFlow`, so there is nothing to build or
push. Use the Hugging Face route if you specifically want the Space, or if Streamlit
Cloud is unavailable to you.

> On ZeroGPU: CogniFlow uses **no GPU at all**, so it would never request one and never
> consume the daily GPU quota. It should simply run on the CPU side. But it is
> infrastructure built for a different job, and the 30-day account gate is a hard stop
> if your account is new — which is why it is the second option, not the first.

---

## Route A — Streamlit Community Cloud (recommended)

1. Go to **share.streamlit.io** and sign in with GitHub.
2. **New app** → **Deploy a public app from GitHub**.
   - Repository: `sohan1611/CogniFlow`
   - Branch: `main`
   - Main file path: `ui.py`
3. **Advanced settings** → Python version **3.12** (3.13 also fine).
4. **Secrets** — paste this, with your own key:

   ```toml
   GROQ_API_KEY = "gsk_..."
   ```

5. **Deploy.** First boot takes a few minutes: it installs dependencies, downloads the
   ~79 MB embedding model, and indexes the corpus. `ui.py` builds the index itself on
   first run, so there is nothing to prepare.

Your URL will look like `https://cogniflow.streamlit.app`.

---

## A note on the Hugging Face SDK

Hugging Face **retired the Streamlit SDK**. The [config reference](https://huggingface.co/docs/hub/spaces-config-reference)
now accepts only `gradio`, `docker` or `static`, and the New Space form agrees. Docker is
a paid tier.

So the Space runs a **Gradio** UI (`app_gradio.py`), while `ui.py` remains the local
Streamlit UI. Both are thin renderers over the same graph — neither decides anything, so
there is one implementation of the behaviour and two ways to look at it.

---

## Deploy to Hugging Face Spaces

**These steps need your account, so they are yours to run.**

**1. Create the Space**

huggingface.co → **New Space**

| Field | Value |
|---|---|
| Owner | `Rick1611` |
| Space name | `CogniFlow` |
| License | `mit` |
| **SDK** | **Gradio** → template **Blank** |
| Hardware | **CPU Basic · free** (not ZeroGPU — we need no GPU) |
| Visibility | **Public** |

The frontmatter in the pushed `README.md` sets the SDK properly on first push, so the
template choice only matters until then.

**2. Build the deployable tree**

```bash
python run.py space
```

That assembles `build/space/` — the app package, the curriculum, the UI, and the Space
config. It excludes `data/chroma` and the SQLite files, which are rebuilt on first boot.

**3. Push it**

```bash
cd build/space
git init
git add -A
git commit -m "CogniFlow"
git branch -M main
git remote add origin https://huggingface.co/spaces/Rick1611/CogniFlow
git push -u origin main
```

Git will ask for credentials: your username is `Rick1611`, and the **password is a
write token** from Settings → Access Tokens. Your account password will not work.

**4. Add the secret**

Space → Settings → Variables and secrets → New secret:

```
GROQ_API_KEY = <your free key from console.groq.com>
```

Without it the Space still runs; problem generation falls back to deterministic
templates and the UI says so.

**5. First boot takes a few minutes**

The container downloads the ~79 MB embedding model and builds the retrieval index once.
Subsequent starts are fast. **Open the Space yourself before sending anyone the link** —
free Spaces sleep after inactivity, and a cold start in front of a judge looks like a
broken app.

---

## Route C — the split deploy: Next.js on Vercel, the engine on Render

This is what is live now, and it is a different shape from routes A and B. Those host
`ui.py`, which is one Python process rendering its own screens. This one splits the
system in two:

| | Where | What it is |
|---|---|---|
| Frontend | Vercel — `cogniflow-nine.vercel.app` | `web/`, Next.js. Renders. Decides nothing. |
| Engine | Render — `cogniflow-engine.onrender.com` | `app/api/main.py`, FastAPI over the same graph. |

**Vercel alone cannot host this.** It is worth being explicit, because "deploy it on
Vercel" is the obvious instruction and it produces a site that looks fine and works for
nobody. The engine needs a subprocess sandbox, a vector store, and checkpoints that
outlive a request — none of which a serverless function has — and `onnxruntime` plus
`chromadb` are past the Python bundle limit before any of that matters. Deploying only
the frontend leaves `NEXT_PUBLIC_API_URL` pointing at `127.0.0.1:8000`, which means every
visitor's browser calls *their own machine*. It fails silently and looks like a bug in
the app.

### Wiring

- Render: runtime **python**, build `pip install -r requirements.txt`, start
  `uvicorn app.api.main:app --host 0.0.0.0 --port $PORT --workers 1`, `PYTHON_VERSION`
  `3.13.4`. One worker, deliberately: in-flight graph handles live in a dict in that
  process, so a second worker would answer half the requests with "no active session".
- Vercel: root directory `web`, framework auto-detected. The engine URL is baked into
  `next.config.mjs` for production builds — it is a public endpoint, not a secret, and a
  dashboard setting nobody can see is a worse place for it. `NEXT_PUBLIC_API_URL` still
  overrides.
- CORS on the engine names the Vercel origins and nothing else. It is not access
  control: the API has no authentication, so `curl` still reaches everything. What it
  stops is another page in the student's browser reading their progress.

### The one thing that is not automated

**Provider keys.** `GROQ_API_KEY` and `GOOGLE_API_KEY` go in the Render dashboard →
*Environment* → *Add environment variable*, by a human, because keys should not pass
through anything that keeps a transcript. Until they are set, `/health` reports
`"generation": "deterministic-templates"` and the frontend says so on screen: every
routing, mastery and prerequisite decision still runs exactly as it would live, and only
the exercise *wording* is templated. That is a real degraded mode, not a broken one --
but it is not what you want a judge to see.

### Free-tier facts, stated rather than discovered on demo day

- **Both services sleep after fifteen idle minutes.** A wake is roughly thirty seconds.
  The frontend shows "Waking the tutoring engine" and retries for a minute instead of
  declaring the backend dead. **Open both links a minute before any demo.**
- **The engine's disk does not survive a restart.** Student mastery persists across a
  session and is lost on redeploy. `StudentStore` is interface-backed, so Postgres is a
  config swap when that matters.
- **`data/chroma` is committed** so a cold start does not re-embed the curriculum. It
  measured at 3m46s when it did. `tests/test_rag.py` fails if the index drifts from
  `data/knowledge`; if it does, run `python scripts/ingest_corpus.py` and commit.

---

## What to check once it is live

- [ ] **Watch the demo** tab produces `recursion → functions → recursion`
- [ ] **Be the student** tab shows *"Graph suspended at `await_student`"*
- [ ] Submitting `import os` is refused with a readable message, and mastery does not move
- [ ] The event stream shows retrieval citations pointing at real chapters

---

## Honest note for the submission

A hosted Space is a convenience, not the evidence. The reproducible artefact is the
repository: `python run.py install && python run.py ingest && python run.py verify` runs the whole thing from a
clean clone and checks its own claims. If the Space is asleep or rate-limited on the day,
that path still stands.
