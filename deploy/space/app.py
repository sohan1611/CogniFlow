"""Hugging Face Space entry point.

Differences from running locally, all of them about the fact that this is PUBLIC:

  * the retrieval index is built on first boot, because the Space starts from a clean
    checkout with no `data/chroma`
  * code restrictions are forced ON regardless of environment, so a misconfigured
    secret cannot turn a public instance into an open proxy
  * the interactive mode is available, but every submission passes the static gate
    before any process is created

The Space needs one secret: GROQ_API_KEY (free tier at console.groq.com). Without it the
app still runs — problem generation falls back to deterministic templates and says so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Force the static restriction gate ON before anything imports the sandbox. A public
# deployment must never depend on an env var being set correctly to stay safe.
os.environ["COGNIFLOW_RESTRICT_CODE"] = "1"

import streamlit as st  # noqa: E402


@st.cache_resource(show_spinner="Building the retrieval index (first boot only)…")
def bootstrap() -> dict[str, int]:
    """Ingest the corpus once per container.

    Cached as a resource so it survives Streamlit reruns; a Space restart pays it again,
    which is a one-time ~79 MB embedding-model download plus a few seconds of indexing.
    """
    from app.rag.ingest import ingest_corpus
    from app.rag.store import VectorStore

    store = VectorStore()
    if store.count() == 0:
        return ingest_corpus(Path("data/knowledge"), store=store)
    return {"documents": 0, "chunks": store.count(), "skills": 0}


bootstrap()

# Hand off to the real UI. Kept as a separate module so the Space and local runs share
# exactly one implementation -- a Space-only copy would drift.
exec(compile((ROOT / "ui.py").read_text(encoding="utf-8"), "ui.py", "exec"))
