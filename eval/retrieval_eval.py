"""Retrieval quality benchmark.

Invariant: retrieval quality is MEASURED before it is optimised. The corpus is small and
skill-filtered, so it is entirely possible that plain semantic search is already
sufficient — in which case adding a reranker would be complexity bought with nothing,
and saying so is the correct outcome.

WHY A BENCHMARK RATHER THAN AN OPINION
Retrieval failures are invisible: something always comes back, and it always looks
plausible. The only way to know whether the top chunks are the RIGHT chunks is to write
down in advance which section should win, then check.

GROUND TRUTH
Each case names a query the system genuinely issues, and the section that should surface.
The queries are drawn from the two real consumers:

  * remediation — the agent redirects to a skill and needs material teaching it
  * misconception — the diagnoser names a misunderstanding and needs the passage that
    addresses it (these are the labels in app/mastery/misconceptions.py verbatim)

`expect_section` matches on a case-insensitive substring of the chunk's heading, so the
benchmark survives harmless rewording of a title.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from app.rag.retriever import DEFAULT_K, Retriever


@dataclass(frozen=True)
class Case:
    """One retrieval expectation."""

    query: str
    skill: str
    expect_section: str
    kind: str = "remediation"


# Ground truth. Written against what the corpus is FOR, not against what it happens to
# contain -- if a case fails, the honest first question is whether the corpus is missing
# something a student needs, not whether the case is inconvenient.
CASES: tuple[Case, ...] = (
    # --- misconception -> the passage that addresses it -----------------
    Case(
        "recursive call is computed but not returned, so the function yields None",
        "functions", "misconception", kind="misconception",
    ),
    Case(
        "recursive function has no reachable base case, so it never terminates",
        "conditionals", "never", kind="misconception",
    ),
    Case(
        "loop condition never becomes false, so execution does not terminate",
        "loops", "infinite", kind="misconception",
    ),
    Case(
        "uses a name that was never defined, or defined only inside another scope",
        "variables", "name", kind="misconception",
    ),
    Case(
        "uses print where a return value is required, so the caller receives None",
        "functions", "misconception", kind="misconception",
    ),
    # --- remediation -> the teaching material ---------------------------
    Case("how does the call stack work when a function calls another function",
         "functions", "call stack"),
    Case("trace a function call step by step and predict the output",
         "function_call_tracing", "trace"),
    Case("what stops infinite recursion", "recursion", "base case"),
    Case("difference between return and print in a function", "functions", "return"),
    Case("how do I write a loop that counts up to a number", "loops", "loop"),
    Case("how do nested loops produce a grid", "nested_loops", "nested"),
    Case("how does a recursive call branch into a tree", "recursion_tree", "tree"),
    Case("what is a variable and how does assignment work", "variables", "variable"),
    Case("how do if and elif decide which branch runs", "conditionals", "elif"),
)


@dataclass
class EvalResult:
    """Aggregate retrieval quality."""

    total: int
    hits_at_1: int
    hits_at_k: int
    reciprocal_ranks: list[float] = field(default_factory=list)
    misses: list[Case] = field(default_factory=list)
    k: int = DEFAULT_K

    @property
    def recall_at_1(self) -> float:
        return self.hits_at_1 / max(self.total, 1)

    @property
    def recall_at_k(self) -> float:
        return self.hits_at_k / max(self.total, 1)

    @property
    def mrr(self) -> float:
        return fmean(self.reciprocal_ranks) if self.reciprocal_ranks else 0.0

    def render(self) -> str:
        lines = [
            "",
            f"Retrieval quality over {self.total} ground-truth cases (k={self.k})",
            "-" * 62,
            f"  recall@1   {self.recall_at_1 * 100:5.1f}%   the right section is the top hit",
            f"  recall@{self.k}   {self.recall_at_k * 100:5.1f}%   it appears anywhere in the context",
            f"  MRR        {self.mrr:5.3f}   1.0 means always first",
        ]
        if self.misses:
            lines.append("")
            lines.append(f"  {len(self.misses)} case(s) where the expected section never appeared:")
            for case in self.misses:
                lines.append(f"    [{case.skill}] {case.query[:58]}")
                lines.append(f"        expected a section matching {case.expect_section!r}")
        return "\n".join(lines)


def evaluate(retriever: Retriever | None = None, k: int = DEFAULT_K) -> EvalResult:
    """Score the benchmark. Never raises."""
    retriever = retriever or Retriever()
    result = EvalResult(total=len(CASES), hits_at_1=0, hits_at_k=0, k=k)

    for case in CASES:
        evidence = retriever.retrieve(case.query, skill=case.skill, k=k)
        rank: int | None = None
        for position, chunk in enumerate(evidence.chunks, start=1):
            haystack = f"{chunk.section} {chunk.text[:400]}".lower()
            if case.expect_section.lower() in haystack:
                rank = position
                break

        if rank is None:
            result.misses.append(case)
            result.reciprocal_ranks.append(0.0)
            continue

        result.hits_at_k += 1
        result.reciprocal_ranks.append(1.0 / rank)
        if rank == 1:
            result.hits_at_1 += 1

    return result


def evaluate_by_kind(k: int = DEFAULT_K) -> dict[str, EvalResult]:
    """Split the score by consumer, since they have different failure costs.

    A misconception miss is worse than a remediation miss: the diagnoser has already
    worked out what is wrong, and retrieving the wrong passage wastes that.
    """
    retriever = Retriever()
    out: dict[str, EvalResult] = {}
    for kind in sorted({c.kind for c in CASES}):
        subset = [c for c in CASES if c.kind == kind]
        res = EvalResult(total=len(subset), hits_at_1=0, hits_at_k=0, k=k)
        for case in subset:
            evidence = retriever.retrieve(case.query, skill=case.skill, k=k)
            rank = None
            for position, chunk in enumerate(evidence.chunks, start=1):
                if case.expect_section.lower() in f"{chunk.section} {chunk.text[:400]}".lower():
                    rank = position
                    break
            if rank is None:
                res.misses.append(case)
                res.reciprocal_ranks.append(0.0)
                continue
            res.hits_at_k += 1
            res.reciprocal_ranks.append(1.0 / rank)
            if rank == 1:
                res.hits_at_1 += 1
        out[kind] = res
    return out
