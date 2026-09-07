"""Enforce AGENTS.md RULE 1: the contributor list stays exactly two humans.

Run before every push:

    .venv/Scripts/python.exe scripts/check_contributors.py

Exits non-zero if anything would put a bot in this repository's history.

WHY THIS IS A SCRIPT AND NOT A GREP
A naive `git log | grep -i claude` also matches legitimate prose -- our commit messages
discuss Claude and Codex as *models and tools*, which is normal technical writing. A
check that cries wolf gets ignored, and an ignored check is how a real violation reaches
main. So this looks at the fields that actually determine authorship:

  1. commit author and committer identity (what GitHub's contributor graph reads)
  2. attribution TRAILERS in the message body (Co-Authored-By and friends)
  3. bot configuration files that would create bot-authored commits later

Known and accepted: the repository's root commit was created through the GitHub web UI,
so its *committer* is `GitHub <noreply@github.com>` while its *author* is human. GitHub
attributes contributions by author, so this does not put a bot in the contributor list.
It is whitelisted explicitly rather than silently ignored.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Substrings that indicate a non-human identity.
BOT_MARKERS = (
    "claude",
    "codex",
    "copilot",
    "dependabot",
    "renovate",
    "[bot]",
    "noreply@anthropic",
    "noreply@openai",
    "actions@github",
    "pre-commit-ci",
    "allcontributors",
)

# Trailers that add a person or bot to a commit's authorship.
TRAILER_RE = re.compile(
    r"^\s*(co-authored-by|signed-off-by|on-behalf-of)\s*:", re.IGNORECASE | re.MULTILINE
)

# (committer_email, reason) pairs that are known-safe.
WHITELISTED_COMMITTERS = {
    "noreply@github.com": "GitHub web UI created the root commit; author is human",
}

SEP = "\x1f"
REC = "\x1e"


def _git(*args: str) -> str:
    """Read git output as UTF-8, whatever the console codepage says.

    `text=True` decodes with the platform default, which on Windows is cp1252, and git
    hands back UTF-8. One commit message containing a character outside cp1252 -- an
    emoji quoted from the UI, an arrow, a curly apostrophe -- and this raised
    UnicodeDecodeError inside a reader thread, leaving `.stdout` as None and the whole
    check dead on an AttributeError three lines later.

    That is the worst way for this particular script to fail. It is the enforcement
    mechanism for the one hard rule in CLAUDE.md, and a crash reports FAILED the same
    way a real bot author would, so the finding that matters is indistinguishable from
    the tool being broken. errors="replace" because a mangled character in a commit
    message must never stop the check from answering the question it exists to answer.
    """
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def main() -> int:
    problems: list[str] = []

    fmt = SEP.join(["%H", "%an", "%ae", "%cn", "%ce", "%B"]) + REC
    raw = _git("log", f"--format={fmt}")
    commits = [c for c in raw.split(REC) if c.strip()]

    authors: set[str] = set()

    for commit in commits:
        parts = commit.lstrip("\n").split(SEP)
        if len(parts) < 6:
            continue
        sha, an, ae, cn, ce, body = parts[0][:8], *parts[1:6]
        authors.add(f"{an} <{ae}>")

        if any(m in an.lower() or m in ae.lower() for m in BOT_MARKERS):
            problems.append(f"{sha}: bot AUTHOR {an} <{ae}>")
        if ce.lower() not in WHITELISTED_COMMITTERS and any(
            m in cn.lower() or m in ce.lower() for m in BOT_MARKERS
        ):
            problems.append(f"{sha}: bot COMMITTER {cn} <{ce}>")

        found = TRAILER_RE.search(body)
        if found:
            line = next(
                (ln.strip() for ln in body.splitlines() if TRAILER_RE.match(ln)), ""
            )
            problems.append(f"{sha}: attribution trailer -> {line!r}")

    tracked = _git("ls-files").splitlines()
    for path in tracked:
        low = path.lower()
        if "dependabot" in low or "renovate" in low:
            problems.append(f"bot config file tracked: {path}")

    print(f"Checked {len(commits)} commit(s).")
    print("Distinct authors:")
    for a in sorted(authors):
        print(f"  - {a}")

    if len(authors) > 2:
        problems.append(f"{len(authors)} distinct authors; RULE 1 allows at most 2")

    print()
    if problems:
        print("FAILED -- RULE 1 violations:")
        for p in problems:
            print(f"  ! {p}")
        return 1

    print("PASS -- no bot authors, no attribution trailers, no bot config.")
    for email, reason in WHITELISTED_COMMITTERS.items():
        if any(email in c for c in commits):
            print(f"  note: committer {email} present and accepted ({reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
