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

## Deploy to Hugging Face Spaces

You need a free account at huggingface.co. **These steps are yours to run — they need
your account.**

**1. Create the Space**

huggingface.co → New Space → SDK **Streamlit**, hardware **CPU basic (free)**.
Name it `cogniflow`.

**2. Build the deployable tree**

```bash
python run.py space
```

That assembles `build/space/` — the app package, the curriculum, the UI, and the Space
config. It excludes `data/chroma` and the SQLite files, which are rebuilt on first boot.

**3. Push it**

```bash
cd build/space
git init && git remote add origin https://huggingface.co/spaces/<your-username>/cogniflow
git add -A && git commit -m "CogniFlow"
git push -u origin main
```

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

## What to check once it is live

- [ ] **Watch the demo** produces `recursion → functions → recursion`
- [ ] **Be the student** shows *"Graph suspended at await_student — checkpointed to disk"*
- [ ] Submitting `import os` is refused with a readable message, and mastery does not move
- [ ] The event stream shows retrieval citations pointing at real chapters

---

## Honest note for the submission

A hosted Space is a convenience, not the evidence. The reproducible artefact is the
repository: `python run.py install && python run.py ingest && python run.py verify` runs the whole thing from a
clean clone and checks its own claims. If the Space is asleep or rate-limited on the day,
that path still stands.
