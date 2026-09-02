"""Static restriction of student code before it is executed.

Invariant: this is a PRE-EXECUTION gate. Code that fails it never runs at all, so the
analysis cannot be defeated by anything the code does at runtime.

WHY THIS EXISTS
The subprocess backend gives a timeout and a minimal environment, which is enough when
you are running your own code on your own machine. It is not enough for a publicly
reachable deployment: without this gate, student code can read the filesystem, make
outbound network requests, and spawn processes -- so a hosted CogniFlow would be an open
proxy with a text box.

WHY AN ALLOWLIST AND NOT A BLOCKLIST
Blocklists lose. `socket` can be reached through `urllib`, `urllib` through
`__import__("urllib")`, and `__import__` through `getattr(__builtins__, ...)`. An
allowlist inverts the burden: anything not explicitly permitted is refused. For a
Python-fundamentals tutor that costs nothing, because the exercises are about variables,
conditionals, loops, functions and recursion -- none of which need a network.

A REFUSAL IS NOT A WRONG ANSWER
Rejected code yields SystemFault.EXECUTION_REFUSED, never a StudentOutcome. A student
who writes a correct recursive function and also imports `os` has not demonstrated a
misconception, and their mastery must not move because of a restriction nobody told
them about.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "math",
        "cmath",
        "decimal",
        "fractions",
        "statistics",
        "random",
        "itertools",
        "functools",
        "operator",
        "collections",
        "heapq",
        "bisect",
        "string",
        "re",
        "textwrap",
        "typing",
        "dataclasses",
        "enum",
        "copy",
        "json",
        "datetime",
        "time",
    }
)
"""Everything a Python-fundamentals exercise could legitimately need. Deliberately
excludes os, sys, subprocess, socket, urllib, requests, shutil, pathlib, importlib,
ctypes, multiprocessing, threading and builtins."""

FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__", "open", "breakpoint", "globals",
     "locals", "vars", "getattr", "setattr", "delattr", "memoryview"}
)
"""`getattr` is here because `getattr(obj, "__" + "class__")` defeats attribute checks;
`open` because file access is not needed and is the first step of most escapes.

`input` is deliberately NOT here. Exercises legitimately read stdin, and the stdin they
read is supplied by the test harness -- blocking it would break real exercises to
prevent nothing."""

FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {"__class__", "__bases__", "__subclasses__", "__mro__", "__globals__", "__code__",
     "__closure__", "__builtins__", "__dict__", "__getattribute__", "__reduce__"}
)
"""The standard sandbox-escape ladder: from any object, walk to `type`, then to every
subclass, then to something that can open a file."""


@dataclass(frozen=True)
class Restriction:
    """Why a submission was refused."""

    rule: str
    detail: str
    line: int | None = None

    def message(self) -> str:
        """Student-facing explanation. Says what to do, not merely what was wrong."""
        where = f" (line {self.line})" if self.line else ""
        return f"{self.detail}{where}"


def check(code: str) -> Restriction | None:
    """Return the first restriction violated, or None if the code may run.

    A syntax error is NOT a restriction: that is the student's mistake to learn from,
    and the sandbox reports it as a normal syntax error so mastery updates correctly.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    return Restriction(
                        "forbidden_import",
                        f"this exercise does not allow importing {root!r}",
                        node.lineno,
                    )

        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_MODULES:
                return Restriction(
                    "forbidden_import",
                    f"this exercise does not allow importing from {root or 'a relative module'!r}",
                    node.lineno,
                )

        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if name in FORBIDDEN_CALLS:
                return Restriction(
                    "forbidden_call",
                    f"{name}() is not available in this exercise",
                    node.lineno,
                )

        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                return Restriction(
                    "forbidden_attribute",
                    f"access to {node.attr} is not available in this exercise",
                    node.lineno,
                )

        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_ATTRIBUTES:
                return Restriction(
                    "forbidden_attribute",
                    f"access to {node.id} is not available in this exercise",
                    node.lineno,
                )

    return None


def describe_policy() -> str:
    """Human-readable summary, so the restriction is documented rather than mysterious."""
    return (
        "Student code runs under an allowlist: standard computation modules are "
        f"available ({', '.join(sorted(list(ALLOWED_MODULES)[:8]))}, ...), while "
        "filesystem, network, process and introspection access are refused before "
        "execution. A refusal never affects a student's mastery."
    )
