"""The guard on CLAUDE.md RULE 1 -- tested, because it is the one rule with no undo.

A bot in the contributor list is permanent once pushed, so this check runs before every
push and its verdict is trusted without being re-read. That makes a BROKEN check worse
than no check: it reports FAILED exactly the way a real violation does, and the two are
indistinguishable at a glance.

Which is not hypothetical. `_git` decoded git's UTF-8 output with the platform default,
cp1252 on Windows, and the first commit message containing an emoji killed the reader
thread -- leaving stdout as None and the whole script dead on an AttributeError, three
commits before anyone noticed. CLAUDE.md said the script was self-tested. It was not.
It is now, and one of these cases is that emoji.

Each test builds a throwaway repository and runs the script against it, so the cases are
real git history rather than a stubbed parser.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_contributors.py"

HUMAN = {
    "GIT_AUTHOR_NAME": "Sohan Mandal",
    "GIT_AUTHOR_EMAIL": "sohanmandal1611@gmail.com",
    "GIT_COMMITTER_NAME": "Sohan Mandal",
    "GIT_COMMITTER_EMAIL": "sohanmandal1611@gmail.com",
}


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True)
    return tmp_path


def _commit(repo: Path, message: str, *, identity: dict[str, str] | None = None) -> None:
    (repo / "file.txt").write_text(message[:40], encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    env = {**HUMAN, **(identity or {})}
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--no-verify", "-F", "-"],
        input=message.encode("utf-8"),
        check=True,
        env={**dict(__import__("os").environ), **env},
    )


def _check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.parametrize(
    ("message", "identity", "should_pass", "because"),
    [
        (
            "Swap the Claude call for a Codex one\n\nDiscusses both by name, as tools.",
            None,
            True,
            "naming a model in prose is not authorship",
        ),
        (
            'Stop claiming five topics are "Completed \N{CLAPPING HANDS SIGN}"\n\n'
            "An arrow \N{RIGHTWARDS ARROW} and an em dash \N{EM DASH} too.",
            None,
            True,
            "a non-cp1252 character in a message must not crash the check",
        ),
        (
            "Add a feature\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
            None,
            False,
            "an attribution trailer is the silent way a bot joins the list",
        ),
        (
            "Bump a dependency",
            {"GIT_AUTHOR_NAME": "dependabot[bot]", "GIT_AUTHOR_EMAIL": "49699333+dependabot[bot]@users.noreply.github.com"},
            False,
            "a bot author is exactly what the contributor graph reads",
        ),
    ],
)
def test_the_check_separates_authorship_from_prose(
    tmp_path: Path, message: str, identity: dict[str, str] | None, should_pass: bool, because: str
) -> None:
    """Authorship is a git field; a model's name in prose is not.

    These commit messages legitimately discuss Claude and Codex as models and tools, so a
    check that flagged the word would cry wolf on ordinary technical writing -- and a
    check people learn to ignore is how a real violation reaches main.
    """
    repo = _repo(tmp_path)
    _commit(repo, message, identity=identity)
    result = _check(repo)

    assert result.returncode == (0 if should_pass else 1), (
        f"{because}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "Traceback" not in result.stderr, (
        "the check crashed rather than deciding; a crash reports FAILED the same way a "
        f"real violation does\n{result.stderr}"
    )


def test_a_tracked_dependabot_config_is_caught_before_it_ever_runs(tmp_path: Path) -> None:
    """Dependabot authors its own commits, so the file is the last moment to stop it."""
    repo = _repo(tmp_path)
    _commit(repo, "Initial commit")
    config = repo / ".github" / "dependabot.yml"
    config.parent.mkdir(parents=True)
    config.write_text("version: 2\n", encoding="utf-8")
    _commit(repo, "Add dependency automation")

    result = _check(repo)
    assert result.returncode == 1
    assert "dependabot" in result.stdout.lower()


def test_this_repository_passes_its_own_rule() -> None:
    """The check the pre-push gate actually runs, against real history."""
    result = _check(Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
