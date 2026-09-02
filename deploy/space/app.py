"""Hugging Face Space entry point.

Differences from a local run, all of them consequences of being PUBLIC:

  * the retrieval index is built on first boot, because a Space starts from a clean
    checkout with no `data/chroma`
  * code restrictions are forced ON in code, so a misconfigured secret cannot turn a
    public instance into an open proxy
  * the UI is Gradio rather than Streamlit: Hugging Face retired the Streamlit SDK, and
    `sdk` now accepts only gradio, docker or static

The Space needs one secret: GROQ_API_KEY (free tier at console.groq.com). Without it the
app still runs; problem generation falls back to deterministic templates and says so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ["COGNIFLOW_RESTRICT_CODE"] = "1"


def bootstrap() -> None:
    """Index the corpus once per container, before the UI accepts traffic."""
    from app.rag.ingest import ingest_corpus
    from app.rag.store import VectorStore

    store = VectorStore()
    if store.count() == 0:
        summary = ingest_corpus(Path("data/knowledge"), store=store)
        print(f"[bootstrap] indexed {summary} ", flush=True)
    else:
        print(f"[bootstrap] index already present ({store.count()} chunks)", flush=True)


bootstrap()

# One implementation shared with local runs -- a Space-only copy would drift.
from app_gradio import demo  # noqa: E402

if __name__ == "__main__":
    demo.launch()
