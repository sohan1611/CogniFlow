"""Language registry for sandboxed student-code execution.

Invariant: a language is listed to students only when this process can actually run it
under the isolation required for that language.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

from app.models.enums import Language


@dataclass(frozen=True)
class LanguageSpec:
    language: Language
    label: str
    source_name: str
    executables: tuple[str, ...]
    compile_cmd: tuple[str, ...] | None
    run_cmd: tuple[str, ...]
    comment_prefix: str
    needs_container: bool


_SPECS: dict[Language, LanguageSpec] = {
    Language.PYTHON: LanguageSpec(
        language=Language.PYTHON,
        label="Python",
        source_name="main.py",
        executables=(sys.executable,),
        compile_cmd=None,
        run_cmd=(sys.executable, "-I", "-B", "{src}"),
        comment_prefix="#",
        needs_container=False,
    ),
    Language.JAVASCRIPT: LanguageSpec(
        language=Language.JAVASCRIPT,
        label="JavaScript",
        source_name="main.js",
        executables=("node",),
        compile_cmd=None,
        run_cmd=("node", "{src}"),
        comment_prefix="//",
        needs_container=True,
    ),
    Language.JAVA: LanguageSpec(
        language=Language.JAVA,
        label="Java",
        source_name="Main.java",
        executables=("javac", "java"),
        compile_cmd=("javac", "{src}"),
        run_cmd=("java", "-cp", "{out}", "Main"),
        comment_prefix="//",
        needs_container=True,
    ),
    Language.CPP: LanguageSpec(
        language=Language.CPP,
        label="C++",
        source_name="main.cpp",
        executables=("g++",),
        compile_cmd=("g++", "{src}", "-O2", "-std=c++17", "-o", "{out}"),
        run_cmd=("{out}",),
        comment_prefix="//",
        needs_container=True,
    ),
    Language.C: LanguageSpec(
        language=Language.C,
        label="C",
        source_name="main.c",
        executables=("gcc",),
        compile_cmd=("gcc", "{src}", "-O2", "-std=c11", "-o", "{out}"),
        run_cmd=("{out}",),
        comment_prefix="//",
        needs_container=True,
    ),
}


def spec_for(language: Language | LanguageSpec | str) -> LanguageSpec:
    """Return the execution metadata for a supported language."""

    if isinstance(language, LanguageSpec):
        return language
    if isinstance(language, Language):
        return _SPECS[language]
    return _SPECS[Language(str(language))]


def runtime_present(spec: LanguageSpec) -> bool:
    """Return True only when every executable required by the spec is on PATH."""

    return all(shutil.which(executable) is not None for executable in spec.executables)


def is_offerable(spec: LanguageSpec, *, docker_available: bool) -> bool:
    """Return whether a language can be offered without weakening execution safety.

    Python is offerable when its runtime exists because Python submissions still pass
    through the AST allowlist before execution. Every other language lacks that static
    gate, so runtime presence is not enough: it is offerable only when the runtime exists
    and Docker isolation is available.
    """

    if spec.language == Language.PYTHON:
        return runtime_present(spec)
    return runtime_present(spec) and docker_available


def available_languages(*, docker_available: bool) -> list[LanguageSpec]:
    """Return languages that can honestly be shown on this host."""

    return [
        spec
        for language in Language
        if is_offerable((spec := spec_for(language)), docker_available=docker_available)
    ]
