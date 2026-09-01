"""CLI for ingesting the local knowledge corpus.

Invariant: zero produced chunks is a failed ingest and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Make the project importable when this script is run directly
# (python scripts/ingest_corpus.py) rather than via pytest or -m.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.chunker import chunk_document
from app.rag.documents import load_corpus
from app.rag.ingest import ingest_corpus
from app.rag.store import VectorStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest CogniFlow knowledge corpus into Chroma.")
    parser.add_argument("directory", nargs="?", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--chroma-path", type=Path, default=None)
    return parser


def _chunk_counts(directory: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for document in load_corpus(directory):
        counts[document.meta.skill] += len(chunk_document(document))
    return counts


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = VectorStore(path=args.chroma_path) if args.chroma_path is not None else VectorStore()
    summary = ingest_corpus(args.directory, store)
    counts = _chunk_counts(args.directory)

    print(f"documents: {summary['documents']}")
    print(f"chunks: {summary['chunks']}")
    print(f"skills: {summary['skills']}")
    print("per-skill chunks:")
    for skill, count in sorted(counts.items()):
        print(f"  {skill}: {count}")

    return 0 if summary["chunks"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

