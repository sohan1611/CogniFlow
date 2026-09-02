"""Cross-platform task runner.

    python run.py            list the tasks
    python run.py demo       run one

A Makefile is convenient on Linux and macOS and absent on most Windows machines --
including the one this project was built on. Since the whole project is Python, a Python
runner works everywhere Python does, which is the only dependency a judge is guaranteed
to have already installed.

`make <task>` still works if you have make; the Makefile delegates here.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def sh(*args: str) -> int:
    """Run a command, streaming its output. Returns its exit code."""
    print(f"$ {' '.join(args)}", flush=True)
    return subprocess.run(args, cwd=ROOT).returncode


def install() -> int:
    """create the venv and install pinned dependencies"""
    if not VENV_PY.exists():
        launcher = ["py", "-3.14"] if sys.platform == "win32" else [sys.executable]
        if sh(*launcher, "-m", "venv", ".venv"):
            return 1
    # Re-resolve rather than reusing PY. On a fresh clone `.venv` did not exist when
    # this module was imported, so PY is the system interpreter -- and installing with
    # it puts every dependency outside the venv that was just created. The next task
    # runs in a new process, finds the venv, and fails on the first import. That is
    # exactly what a judge cloning this repository would hit.
    target = str(VENV_PY) if VENV_PY.exists() else PY
    return sh(target, "-m", "pip", "install", "-q", "-r", "requirements-dev.txt")


def smoke() -> int:
    """prove the environment works before trusting anything else"""
    return sh(PY, "scripts/smoke_test.py")


def test() -> int:
    """the full offline suite - no API key, no network, no spend"""
    return sh(PY, "-m", "pytest", "tests/", "-q")


def ingest() -> int:
    """build the retrieval index from data/knowledge"""
    return sh(PY, "scripts/ingest_corpus.py")


def demo() -> int:
    """the prerequisite-redirect demo, with the live event stream"""
    return sh(PY, "demo.py")


def verify() -> int:
    """the demo, checking its own claims instead of narrating them"""
    return sh(PY, "demo.py", "--verify")


def live() -> int:
    """the demo against a real model (needs a free GROQ_API_KEY in .env)"""
    return sh(PY, "demo.py", "--live", "--verify")


def check() -> int:
    """one real call per configured provider, to verify the wire format"""
    return sh(PY, "scripts/live_check.py")


def ablation() -> int:
    """three-arm study, BKT fitting, retrieval quality (costs nothing)"""
    return sh(PY, "scripts/run_ablation.py")


def ui() -> int:
    """the web UI - watch the demo, or be the student yourself"""
    return sh(PY, "-m", "streamlit", "run", "ui.py")


def scan() -> int:
    """enforce AGENTS.md RULE 1 before pushing"""
    return sh(PY, "scripts/check_contributors.py")


def space() -> int:
    """assemble build/space, ready to push to Hugging Face"""
    target = ROOT / "build/space"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item in ("app", "data", "ui.py", "app_gradio.py", "conftest.py"):
        src = ROOT / item
        dst = target / item
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    for item in ("app.py", "README.md", "requirements.txt"):
        shutil.copy2(ROOT / "deploy/space" / item, target / item)

    # rebuilt on first boot; shipping them would bloat the push and stale the index
    shutil.rmtree(target / "data/chroma", ignore_errors=True)
    for db in (target / "data").glob("*.db"):
        db.unlink()

    files = sum(1 for _ in target.rglob("*") if _.is_file())
    print(f"\nbuild/space ready -- {files} files.")
    print("Next: deploy/DEPLOY.md")
    return 0


def gates() -> int:
    """every release gate, in order. Run this before submitting."""
    failed = []
    for name, fn in (("test", test), ("verify", verify), ("ablation", ablation), ("scan", scan)):
        print(f"\n{'=' * 70}\nGATE: {name}\n{'=' * 70}")
        if fn():
            failed.append(name)
    print(f"\n{'=' * 70}")
    if failed:
        print(f"FAILED GATES: {', '.join(failed)}  -- do not submit until these pass")
        return 1
    print("ALL GATES PASSED")
    return 0


TASKS = {
    name: fn
    for name, fn in sorted(globals().items())
    if callable(fn) and not name.startswith("_") and fn.__module__ == __name__
    and name not in {"sh"}
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(__doc__.strip())
        print("\nTasks:\n")
        for name, fn in TASKS.items():
            print(f"  {name:<10} {(fn.__doc__ or '').strip()}")
        return 0

    name = sys.argv[1]
    if name not in TASKS:
        print(f"unknown task {name!r}. Run `python run.py` to list them.")
        return 2
    return TASKS[name]()


if __name__ == "__main__":
    raise SystemExit(main())
