# CogniFlow — student frontend

The student-facing surface. It renders what the engine returns and decides nothing
itself: no skill is chosen here, no answer judged, no mastery moved. That is the same
promise `ui.py` makes, and having two surfaces is what proves the engine keeps it.

```bash
npm install
npm run dev          # http://localhost:3000
```

It needs the engine running:

```bash
python run.py api    # http://localhost:8000
```

## Why this is two services

Vercel is the right host for this app and the wrong host for the engine. The engine
needs things a serverless function does not have:

| It needs | Because |
|---|---|
| A long-lived process | A tutoring run takes ~40–70s; serverless functions are built for seconds |
| A real filesystem | LangGraph checkpoints to SQLite on disk, and that checkpoint *is* the suspend/resume feature |
| To spawn subprocesses | Student code runs in a sandboxed child process |
| ~200 MB of dependencies | chromadb + onnxruntime + langgraph strains a serverless bundle |

So the split is: **this app on Vercel, the Python engine on a host that gives it a
persistent process** — Render, Railway, Fly, or any Docker target.

## Deploying

**1. The engine**, on any host that runs a container or a Python process:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port $PORT
```

It needs `GROQ_API_KEY` and `GOOGLE_API_KEY` in the environment (both free), and a
writable volume for `data/` if you want mastery to survive restarts. Without a volume it
still runs — students just start fresh each deploy.

**2. This app**, on Vercel:

- Import the repository, set **Root Directory** to `web`
- Set `NEXT_PUBLIC_API_URL` to the engine's public URL
- Deploy

Next.js is auto-detected; no build configuration is needed.

## A note on CORS

The engine currently allows every origin, which is correct while it holds no credentials
and no personal data beyond a self-chosen display name. **The moment either changes,
narrow `allow_origins` in `app/api/main.py` to this app's deployed origin.** It is a
one-line change and it is left deliberately visible rather than buried in config.

## What is deliberately not here

No authentication, no accounts, no password. A student is identified by the name they
type, which is enough to remember what they know and not enough to be worth stealing.
Adding real accounts means holding real credentials, and that is a decision with
obligations attached — not a feature to slip in.
