"""Static restrictions on student code.

These exist so CogniFlow can be deployed publicly. Without them, a hosted instance is an
open proxy with a text box: student code could read the filesystem, make outbound network
requests, and spawn processes.

The tests are adversarial on purpose. A restriction layer that only blocks the obvious
`import os` is worse than none, because it invites trust it has not earned.
"""

from __future__ import annotations

import pytest

from app.mastery.bkt import BKTParams, update
from app.models.enums import StudentOutcome, SystemFault, is_student_evidence
from app.models.execution import ExecutionStatus
from app.models.errors import InvalidEvidenceError
from app.tools.sandbox.classifier import classify
from app.tools.sandbox.restrictions import check, describe_policy
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

ESCAPES = [
    ("filesystem", "import os\nprint(os.listdir('.'))"),
    ("filesystem via pathlib", "from pathlib import Path\nprint(list(Path('.').iterdir()))"),
    ("network via urllib", "import urllib.request\nprint(urllib.request.urlopen('http://x').read())"),
    ("network via socket", "import socket\nprint(socket.socket())"),
    ("process spawn", "import subprocess\nsubprocess.run(['ls'])"),
    ("interpreter state", "import sys\nprint(sys.argv)"),
    ("dynamic import", "m = __import__('os')\nprint(m.getcwd())"),
    ("eval", "print(eval('1+1'))"),
    ("exec", "exec('x = 1')"),
    ("compile", "compile('x=1', '<s>', 'exec')"),
    ("file open", "print(open('/etc/passwd').read())"),
    ("subclass ladder", "print(().__class__.__bases__[0].__subclasses__())"),
    ("globals walk", "print((lambda: None).__globals__)"),
    ("getattr bypass", "print(getattr(object, '__' + 'subclasses__'))"),
    ("builtins reach", "print(__builtins__)"),
    ("relative import", "from . import something"),
]

LEGITIMATE = [
    ("recursion", "def f(n):\n    return 1 if n <= 1 else n * f(n - 1)\nprint(f(5))"),
    ("math module", "import math\nprint(math.factorial(5))"),
    ("itertools", "from itertools import count\nprint(next(iter(count())))"),
    ("stdin", "print(input().strip().upper())"),
    ("comprehension", "print([x * x for x in range(5)])"),
    ("classes", "class A:\n    def go(self):\n        return 7\nprint(A().go())"),
    ("collections", "from collections import Counter\nprint(Counter('aab')['a'])"),
    ("string formatting", "n = 3\nprint(f'value {n}')"),
]


@pytest.mark.parametrize("label,code", ESCAPES, ids=[e[0] for e in ESCAPES])
def test_escape_attempts_are_refused(label: str, code: str) -> None:
    restriction = check(code)
    assert restriction is not None, f"{label} was NOT refused"
    assert restriction.message(), "a refusal must explain itself to the student"


@pytest.mark.parametrize("label,code", LEGITIMATE, ids=[e[0] for e in LEGITIMATE])
def test_legitimate_exercise_code_is_allowed(label: str, code: str) -> None:
    """A restriction layer that blocks real exercises is a broken tutor."""
    assert check(code) is None, f"{label} was wrongly refused"


def test_a_syntax_error_is_not_a_restriction() -> None:
    """A student's syntax mistake must reach them as a syntax error.

    If unparseable code were refused instead, they would lose the mastery signal AND the
    error message that teaches them what they got wrong.
    """
    assert check("def broken(:\n  pass") is None


# ------------------------------------------------------ end to end
@pytest.mark.parametrize("label,code", ESCAPES[:6], ids=[e[0] for e in ESCAPES[:6]])
def test_the_sandbox_refuses_before_running(label: str, code: str) -> None:
    result = SubprocessSandbox().run(code, timeout_s=10.0)
    assert result.status is ExecutionStatus.BLOCKED
    assert result.started is False, "blocked code must never have started a process"
    assert classify(result) is SystemFault.EXECUTION_REFUSED


def test_a_refusal_cannot_move_mastery() -> None:
    """The safety invariant, applied to restrictions.

    Someone whose correct solution happens to import `os` has demonstrated no
    misconception. Penalising them for an undisclosed rule would be unjust, and the
    type system makes it impossible.
    """
    fault = classify(SubprocessSandbox().run("import os\nprint(1)", timeout_s=10.0))
    assert not is_student_evidence(fault)
    with pytest.raises(InvalidEvidenceError):
        update(0.5, fault, BKTParams())  # type: ignore[arg-type]


def test_legitimate_code_still_executes_and_scores() -> None:
    result = SubprocessSandbox().run("print(120)", timeout_s=10.0)
    assert result.status is ExecutionStatus.OK
    assert result.stdout.strip() == "120"
    assert classify(result) is StudentOutcome.WRONG_ANSWER  # correctness decided by expectation


def test_restrictions_can_be_disabled_for_trusted_local_use() -> None:
    """Local development against your own code should not fight the gate."""
    permissive = SubprocessSandbox(restrict=False)
    result = permissive.run("import os\nprint('ok')", timeout_s=10.0)
    assert result.status is ExecutionStatus.OK


def test_the_policy_is_documented_not_mysterious() -> None:
    text = describe_policy()
    assert "allowlist" in text.lower()
    assert "mastery" in text.lower(), "the policy must state that a refusal is not a penalty"
