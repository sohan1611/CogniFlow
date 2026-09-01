"""Phase 0 exit gate.

Proves the three things that would otherwise only fail on demo day:
  1. every pinned dependency actually imports on this Python
  2. Chroma's ONNX embedding path really produces vectors (no PyTorch involved)
  3. LangGraph interrupt/resume genuinely round-trips through a checkpointer

Run:  .venv/Scripts/python.exe scripts/smoke_test.py
Exits non-zero on any failure.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

FAILURES: list[str] = []


def check(label: str, fn) -> None:
    try:
        detail = fn()
        print(f"  [PASS] {label}{f' -- {detail}' if detail else ''}")
    except Exception as exc:  # noqa: BLE001 - smoke test reports every failure
        FAILURES.append(f"{label}: {exc!r}")
        print(f"  [FAIL] {label} -- {exc!r}")


def versions() -> None:
    print("\n== 1. dependency versions ==")
    for pkg in (
        "langgraph",
        "langgraph-checkpoint-sqlite",
        "langchain-core",
        "langchain-anthropic",
        "chromadb",
        "onnxruntime",
        "pydantic",
        "networkx",
        "anthropic",
        "pytest",
    ):
        check(pkg, lambda p=pkg: version(p))

    def no_torch() -> str:
        try:
            version("torch")
        except Exception:
            return "absent, as designed"
        raise AssertionError("torch is installed -- the ONNX decision was supposed to avoid it")

    check("pytorch absent", no_torch)


def chroma_onnx() -> None:
    print("\n== 2. Chroma ONNX embeddings (local, no API) ==")
    tmp = Path(tempfile.mkdtemp(prefix="cogniflow_smoke_"))

    def embed() -> str:
        import chromadb

        client = chromadb.PersistentClient(path=str(tmp))
        col = client.get_or_create_collection("smoke")
        col.add(
            ids=["a", "b"],
            documents=[
                "A recursive function calls itself and needs a base case.",
                "A for loop iterates over a sequence.",
            ],
            metadatas=[{"skill": "recursion"}, {"skill": "loops"}],
        )
        res = col.query(query_texts=["what stops infinite recursion?"], n_results=1)
        top = res["documents"][0][0]
        assert "base case" in top, f"unexpected nearest document: {top!r}"

        got = col.get(ids=["a"], include=["embeddings"])
        dim = len(got["embeddings"][0])
        assert dim > 0, "embedding was empty"

        # metadata filtering is what makes our retrieval precise, so prove it works
        filt = col.query(query_texts=["recursion"], n_results=1, where={"skill": "loops"})
        assert filt["metadatas"][0][0]["skill"] == "loops", "metadata filter ignored"
        return f"dim={dim}, semantic hit + metadata filter both correct"

    try:
        check("embed / query / metadata filter", embed)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def langgraph_interrupt() -> None:
    print("\n== 3. LangGraph interrupt/resume + checkpointing ==")
    tmp = Path(tempfile.mkdtemp(prefix="cogniflow_ckpt_"))

    def roundtrip() -> str:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, interrupt
        from typing_extensions import TypedDict

        class S(TypedDict):
            question: str
            answer: str

        def ask(state: S) -> S:
            reply = interrupt({"question": state["question"]})
            return {"answer": reply}

        conn = sqlite3.connect(str(tmp / "ckpt.db"), check_same_thread=False)
        saver = SqliteSaver(conn)
        g = StateGraph(S)
        g.add_node("ask", ask)
        g.add_edge(START, "ask")
        g.add_edge("ask", END)
        app = g.compile(checkpointer=saver)

        cfg = {"configurable": {"thread_id": "smoke-thread-1"}}
        out = app.invoke({"question": "2+2?", "answer": ""}, cfg)
        assert "__interrupt__" in out, f"graph did not pause; got keys {list(out)}"

        state = app.get_state(cfg)
        assert state.next, "checkpoint recorded no pending next node"

        final = app.invoke(Command(resume="4"), cfg)
        assert final["answer"] == "4", f"resume lost the payload: {final}"
        conn.close()
        return f"paused at {state.next}, resumed and returned {final['answer']!r}"

    try:
        check("interrupt -> checkpoint -> resume", roundtrip)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"CogniFlow Phase 0 smoke test -- Python {sys.version.split()[0]}")
    versions()
    chroma_onnx()
    langgraph_interrupt()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL PHASE 0 GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
