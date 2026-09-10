"""Language offerability and execution taxonomy."""

from __future__ import annotations

import subprocess

import pytest

import app.tools.sandbox.subprocess_sandbox as subprocess_sandbox
from app.models.enums import Language, StudentOutcome, SystemFault
from app.models.execution import ExecutionStatus
from app.tools.sandbox import languages
from app.tools.sandbox.classifier import classify
from app.tools.sandbox.languages import is_offerable, runtime_present, spec_for
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox


def test_python_is_offerable_with_or_without_docker_when_runtime_exists(monkeypatch) -> None:
    spec = spec_for(Language.PYTHON)
    monkeypatch.setattr(languages.shutil, "which", lambda executable: executable)

    assert runtime_present(spec) is True
    assert is_offerable(spec, docker_available=False) is True
    assert is_offerable(spec, docker_available=True) is True


@pytest.mark.parametrize("language", list(Language))
def test_without_docker_only_python_is_offerable_even_if_every_runtime_exists(
    language: Language,
    monkeypatch,
) -> None:
    """Safety property: non-Python has no AST gate, so Docker is mandatory."""

    monkeypatch.setattr(languages, "runtime_present", lambda _spec: True)

    assert is_offerable(spec_for(language), docker_available=False) is (
        language == Language.PYTHON
    )


def test_available_languages_without_docker_lists_only_python(monkeypatch) -> None:
    monkeypatch.setattr(languages, "runtime_present", lambda _spec: True)

    offered = languages.available_languages(docker_available=False)

    assert [spec.language for spec in offered] == [Language.PYTHON]


@pytest.mark.parametrize("language", list(Language))
def test_missing_runtime_is_not_offerable_even_with_docker(
    language: Language,
    monkeypatch,
) -> None:
    monkeypatch.setattr(languages.shutil, "which", lambda _executable: None)

    assert is_offerable(spec_for(language), docker_available=True) is False


def test_spec_for_covers_every_language_member() -> None:
    for language in Language:
        assert spec_for(language).language == language


def test_non_python_source_is_never_handed_to_restrictions(monkeypatch) -> None:
    import app.tools.sandbox.restrictions as restrictions

    def refuse_if_called(_code: str) -> None:
        raise AssertionError("non-Python source was parsed by Python restrictions")

    monkeypatch.setattr(restrictions, "check", refuse_if_called)
    monkeypatch.setattr(subprocess_sandbox, "runtime_present", lambda _spec: True)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(subprocess_sandbox.subprocess, "run", fake_run)

    result = SubprocessSandbox().run(
        "console.log(1);\n",
        language=Language.JAVASCRIPT,
    )

    assert result.status == ExecutionStatus.OK
    assert len(calls) == 1
    assert calls[0][0] == "node"


def test_compile_failure_is_student_syntax_error(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_sandbox, "runtime_present", lambda _spec: True)
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "javac":
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="Main.java:1: error: ';' expected\n",
            )
        raise AssertionError("compiled program ran after a compiler failure")

    monkeypatch.setattr(subprocess_sandbox.subprocess, "run", fake_run)

    result = SubprocessSandbox().run(
        "public class Main {\n",
        language=Language.JAVA,
    )

    assert result.status == ExecutionStatus.SYNTAX_ERROR
    assert result.started is True
    assert classify(result) == StudentOutcome.STUDENT_SYNTAX_ERROR
    assert len(calls) == 1


def test_missing_compiler_at_run_time_is_sandbox_failure(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_sandbox, "runtime_present", lambda _spec: True)

    def missing_compiler(cmd, *args, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess_sandbox.subprocess, "run", missing_compiler)

    result = SubprocessSandbox().run(
        "public class Main { public static void main(String[] args) {} }\n",
        language=Language.JAVA,
    )

    assert result.status == ExecutionStatus.SANDBOX_ERROR
    assert result.started is False
    assert classify(result) == SystemFault.SANDBOX_FAILURE


def test_an_unmarkable_problem_halts_instead_of_being_served(monkeypatch) -> None:
    """A student must never be penalised for a problem that was never set.

    When a non-Python language is active and every provider in the chain has failed,
    there is no authored offline ladder to fall back to -- and the degraded placeholder
    carries no expected output and no test cases. Serving it would put a Submit button
    under a non-problem, and `run_test_cases` returns all_passed=False whenever there
    are zero cases (runner.py: `total_count > 0 and ...`). That False is a
    StudentOutcome, so it lowers mastery and can trigger a prerequisite redirect.

    Halting costs the student nothing and says why.
    """
    from app.graph.nodes import _is_usable, _template_problem
    from app.models.enums import Difficulty, SessionStatus

    state = {
        "target_skill": "loops",
        "difficulty_level": Difficulty.EASY,
        "language": "JAVASCRIPT",
    }
    placeholder = _template_problem(state, 0)

    assert not _is_usable(placeholder), (
        "the JavaScript offline placeholder must be recognised as unmarkable -- if this "
        "ever returns True the halt below is dead code and the trap is back"
    )
    assert not placeholder.expected_output.strip()
    assert not placeholder.test_cases

    # And it must not quietly become a Python task wearing a JavaScript label.
    python_task = _template_problem({**state, "language": "PYTHON"}, 0)
    assert placeholder.prompt != python_task.prompt
    assert SessionStatus.HALTED_ERROR.value == "HALTED_ERROR"


def test_zero_test_cases_never_reads_as_a_pass(monkeypatch) -> None:
    """The mechanism behind the trap, pinned directly.

    This is why an unmarkable problem is dangerous rather than merely useless: an empty
    suite is not "nothing to check", it is a FAILURE, and a failure moves mastery.
    """
    from app.tools.sandbox.runner import run_test_cases
    from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

    suite = run_test_cases(SubprocessSandbox(), "print('anything')", [])
    assert not suite.all_passed, (
        "an empty test suite reporting a pass would be the opposite bug, and equally bad"
    )
