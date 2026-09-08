"""Every task on the ladder must be solvable, and its expected output must be right.

This is the highest-consequence test in the file tree. `expected_output` is what a
submission is graded against, so a task whose expected output is wrong marks a CORRECT
answer wrong -- and a wrong answer is a StudentOutcome, which moves mastery down and can
trigger a prerequisite redirect. A typo in a string literal here would quietly teach the
system that a student who did everything right has a knowledge gap.

So each task gets a reference solution, run through the REAL sandbox the students' code
goes through, and the output is compared to what the ladder promises. The solutions live
here rather than in difficulty.py for two reasons: production code should not carry the
answers to its own exercises, and a proof belongs next to the thing that checks it.

Coupling is positional, and the first test fails loudly if a variant is added without a
solution -- which is the failure mode this arrangement is designed to make impossible to
miss.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.mastery.difficulty import LADDER, Task, ladder_summary, rung_for
from app.models.enums import Difficulty
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox

# (skill, difficulty, variant index) -> a program that solves it.
SOLUTIONS: dict[tuple[str, Difficulty, int], str] = {
    ("variables", Difficulty.EASY, 0): "x = 7\nx = x + 3\nprint(x)",
    ("variables", Difficulty.EASY, 1): "x = 20\nx = x // 2\nprint(x)",
    ("variables", Difficulty.MEDIUM, 0): "a = 5\nb = 12\na, b = b, a\nprint(a, b)",
    ("variables", Difficulty.MEDIUM, 1): (
        "price = 250\ndiscount = 40\n"
        "reduced = price - discount\n"
        "final = reduced * 1.18\n"
        "print(round(final, 2))"
    ),
    ("variables", Difficulty.HARD, 0): (
        "a = [1, 2, 3]\nb = a\nb.append(4)\nc = a[:]\nc.append(5)\nprint(len(a), len(b), len(c))"
    ),
    ("conditionals", Difficulty.EASY, 0): "x = 9\nif x > 5:\n    print('big')\nelse:\n    print('small')",
    ("conditionals", Difficulty.EASY, 1): "n = 7\nif n % 2 == 0:\n    print('even')\nelse:\n    print('odd')",
    ("conditionals", Difficulty.MEDIUM, 0): (
        "def grade(s):\n"
        "    if s >= 90:\n        return 'A'\n"
        "    elif s >= 75:\n        return 'B'\n"
        "    elif s >= 60:\n        return 'C'\n"
        "    return 'F'\n"
        "print(grade(75))\nprint(grade(60))"
    ),
    ("conditionals", Difficulty.HARD, 0): (
        "def leap(y):\n"
        "    if y % 400 == 0:\n        return True\n"
        "    if y % 100 == 0:\n        return False\n"
        "    return y % 4 == 0\n"
        "print(leap(1900))\nprint(leap(2000))\nprint(leap(2024))"
    ),
    ("loops", Difficulty.EASY, 0): "total = 0\nfor i in range(1, 5):\n    total += i\nprint(total)",
    ("loops", Difficulty.EASY, 1): "total = 0\nfor i in range(1, 11):\n    if i % 2 == 0:\n        total += i\nprint(total)",
    ("loops", Difficulty.MEDIUM, 0): (
        "numbers = [4, 4, 9, 2, 9, 1]\n"
        "distinct = sorted(set(numbers), reverse=True)\n"
        "print(distinct[1] if len(distinct) > 1 else 'none')"
    ),
    ("loops", Difficulty.MEDIUM, 1): (
        "words = ['apple', '', 'fig', '', 'plum']\n"
        "kept = [w for w in words if w]\n"
        "print(len(kept))\n"
        "best = ''\n"
        "for w in kept:\n"
        "    if len(w) > len(best):\n        best = w\n"
        "print(best)"
    ),
    ("loops", Difficulty.HARD, 0): (
        "prices = [7, 1, 5, 3, 6, 4]\n"
        "best = 0\n"
        "low = prices[0]\n"
        "for p in prices[1:]:\n"
        "    if p - low > best:\n        best = p - low\n"
        "    if p < low:\n        low = p\n"
        "print(best)"
    ),
    ("loops", Difficulty.HARD, 1): (
        "nums = [2, 2, 1, 3, 3, 1, 2]\n"
        "acc = 0\n"
        "for n in nums:\n    acc ^= n\n"
        "print(acc)"
    ),
    ("functions", Difficulty.EASY, 0): "def double(n):\n    return n * 2\n\nprint(double(6))",
    ("functions", Difficulty.MEDIUM, 0): (
        "def area(w, h):\n    return w * h\n\n"
        "def total_area(rooms):\n"
        "    total = 0\n"
        "    for w, h in rooms:\n        total += area(w, h)\n"
        "    return total\n\n"
        "print(total_area([(2, 3), (4, 5)]))"
    ),
    ("functions", Difficulty.HARD, 0): (
        "def make_counter():\n"
        "    n = 0\n"
        "    def step():\n"
        "        nonlocal n\n"
        "        n += 1\n"
        "        return n\n"
        "    return step\n\n"
        "c1 = make_counter()\nc2 = make_counter()\nprint(c1(), c1(), c2(), c1())"
    ),
    ("function_call_tracing", Difficulty.EASY, 0): "print(10)",
    ("function_call_tracing", Difficulty.MEDIUM, 0): "print(10, 15)",
    ("function_call_tracing", Difficulty.HARD, 0): "print([1])\nprint([1, 2])\nprint([3])",
    ("recursion", Difficulty.EASY, 0): (
        "def total(n):\n"
        "    if n <= 0:\n        return 0\n"
        "    return n + total(n - 1)\n\n"
        "print(total(4))"
    ),
    ("recursion", Difficulty.MEDIUM, 0): (
        "def pal(s):\n"
        "    if len(s) <= 1:\n        return True\n"
        "    if s[0] != s[-1]:\n        return False\n"
        "    return pal(s[1:-1])\n\n"
        "print(pal('racecar'))\nprint(pal(''))\nprint(pal('abca'))"
    ),
    ("recursion", Difficulty.HARD, 0): (
        "def search(xs, target, lo=0, hi=None):\n"
        "    if hi is None:\n        hi = len(xs) - 1\n"
        "    if lo > hi:\n        return -1\n"
        "    mid = (lo + hi) // 2\n"
        "    if xs[mid] == target:\n        return mid\n"
        "    if xs[mid] < target:\n        return search(xs, target, mid + 1, hi)\n"
        "    return search(xs, target, lo, mid - 1)\n\n"
        "xs = [1, 3, 5, 7, 9, 11]\nprint(search(xs, 7))\nprint(search(xs, 4))"
    ),
    ("recursion_tree", Difficulty.EASY, 0): (
        "def fib(n):\n"
        "    if n < 2:\n        return n\n"
        "    return fib(n - 1) + fib(n - 2)\n\n"
        "print(fib(7))"
    ),
    ("recursion_tree", Difficulty.MEDIUM, 0): (
        "calls = 0\n\n"
        "def fib(n):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if n < 2:\n        return n\n"
        "    return fib(n - 1) + fib(n - 2)\n\n"
        "print(fib(6))\nprint(calls)"
    ),
    ("recursion_tree", Difficulty.HARD, 0): (
        "memo = {}\n\n"
        "def fib(n):\n"
        "    if n < 2:\n        return n\n"
        "    if n not in memo:\n        memo[n] = fib(n - 1) + fib(n - 2)\n"
        "    return memo[n]\n\n"
        "print(fib(35))"
    ),
    ("nested_loops", Difficulty.EASY, 0): (
        "count = 0\n"
        "for i in range(1, 4):\n"
        "    for j in range(1, 4):\n        count += 1\n"
        "print(count)"
    ),
    ("nested_loops", Difficulty.MEDIUM, 0): (
        "count = 0\n"
        "for i in range(1, 6):\n"
        "    for j in range(i + 1, 6):\n"
        "        if (i + j) % 2 == 0:\n            count += 1\n"
        "print(count)"
    ),
    ("nested_loops", Difficulty.HARD, 0): (
        "nums = [3, 8, 2, 6, 5]\ntarget = 10\n"
        "seen = set()\n"
        "for n in nums:\n"
        "    if target - n in seen:\n"
        "        a, b = sorted((n, target - n))\n"
        "        print(a, b)\n        break\n"
        "    seen.add(n)"
    ),
}


def _all_variants() -> list[tuple[str, Difficulty, int, Task]]:
    out = []
    for skill, rungs in LADDER.items():
        for level, rung in rungs.items():
            for index, task in enumerate(rung.variants):
                out.append((skill, level, index, task))
    return out


def test_every_task_has_a_reference_solution() -> None:
    """A task nobody has solved is a task nobody has checked."""
    missing = [
        (skill, level.value, index)
        for skill, level, index, _ in _all_variants()
        if (skill, level, index) not in SOLUTIONS
    ]
    assert not missing, f"tasks with no reference solution: {missing}"

    stale = [k for k in SOLUTIONS if k not in {(s, l, i) for s, l, i, _ in _all_variants()}]
    assert not stale, f"solutions for tasks that no longer exist: {stale}"


@pytest.mark.parametrize(
    ("skill", "level", "index", "task"),
    [pytest.param(s, l, i, t, id=f"{s}-{l.value}-{i}") for s, l, i, t in _all_variants()],
)
def test_the_expected_output_is_what_a_correct_program_actually_prints(
    skill: str, level: Difficulty, index: int, task: Task
) -> None:
    """Run the reference solution through the real sandbox and compare.

    If this fails, a student who solved the exercise correctly would be graded WRONG --
    and being graded wrong is a StudentOutcome, so it lowers their mastery and can send
    them into a prerequisite they do not need. That is the failure this test exists to
    make impossible.
    """
    solution = SOLUTIONS[(skill, level, index)]
    result = SubprocessSandbox().run(solution, timeout_s=10)

    assert result.stderr.strip() == "", (
        f"{skill}/{level.value}#{index} reference solution errored:\n{result.stderr}"
    )
    assert result.stdout.strip() == task.expected.strip(), (
        f"{skill}/{level.value}#{index}\n"
        f"  prompt promises : {task.expected!r}\n"
        f"  correct code prints: {result.stdout.strip()!r}"
    )


def test_difficulty_is_a_real_progression_not_three_labels() -> None:
    """The complaint that started this: EASY, MEDIUM and HARD were the same task.

    Every skill must demand something genuinely different at each level -- different
    concepts, and a cognitive level that never goes backwards as difficulty rises.
    """
    for skill in LADDER:
        rungs = {lvl: rung_for(skill, lvl) for lvl in Difficulty}
        briefs = {lvl: r.brief for lvl, r in rungs.items()}
        assert len(set(briefs.values())) == 3, f"{skill}: levels share a brief"

        concepts = {lvl: set(r.concepts) for lvl, r in rungs.items()}
        assert concepts[Difficulty.EASY] != concepts[Difficulty.HARD], (
            f"{skill}: EASY and HARD test the same concepts"
        )

        order = {"apply": 0, "analyse": 1, "create": 2}
        rising = [order[rungs[lvl].cognitive_level] for lvl in
                  (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD)]
        assert rising == sorted(rising), (
            f"{skill}: cognitive demand drops as difficulty rises: {rising}"
        )


def test_no_two_tasks_anywhere_are_the_same() -> None:
    """The exact bug reported: the same prompt served at three difficulties."""
    prompts = [t.prompt.strip().lower() for _, _, _, t in _all_variants()]
    duplicates = {p for p in prompts if prompts.count(p) > 1}
    assert not duplicates, f"the ladder repeats itself: {duplicates}"


def test_the_prompt_shows_the_model_the_whole_ladder() -> None:
    """"Make this HARD" is meaningless without knowing what EASY already covered."""
    summary = ladder_summary("loops")
    for level in ("EASY", "MEDIUM", "HARD"):
        assert level in summary
    assert "cognitive level" in summary


def test_the_server_owns_the_problem_id(monkeypatch) -> None:
    """A generator-supplied id is a slug, not an identifier.

    Observed on a live run: the model returned problem_id="loop_sum_easy_001". Readable,
    plausible, and guaranteed to collide the next time any student anywhere is given an
    easy loop-sum task. The requirement is uniqueness, and only the server can promise it.
    """
    from app.models.enums import AssessmentType
    from app.models.schemas import GeneratedProblem

    ids = {
        GeneratedProblem(
            title="t",
            prompt="Sum a list",
            skill="loops",
            difficulty=Difficulty.EASY,
            assessment_type=AssessmentType.CODING,
            problem_id="loop_sum_easy_001",
        ).problem_id
        for _ in range(2)
    }
    # The model CAN set it on the schema -- the graph is what overwrites it, so this
    # asserts the shape, and test_graph covers the node behaviour.
    assert ids == {"loop_sum_easy_001"}, "schema should accept a supplied id"

    fresh = {GeneratedProblem(
        title="t", prompt="Sum a list", skill="loops",
        difficulty=Difficulty.EASY, assessment_type=AssessmentType.CODING,
    ).problem_id for _ in range(50)}
    assert len(fresh) == 50, "the default must be unique per instance"


def test_a_problem_the_grader_cannot_mark_is_rejected() -> None:
    """Observed live: the model returned a coding task with an empty expected_output and
    no test cases.

    The student writes a correct program, the grader has nothing to compare it against,
    and they are marked WRONG -- which is a StudentOutcome, so it lowers their mastery
    and can send them into a prerequisite they do not need. A problem nobody can pass is
    worse than a repeated one, which is the ranking the generator's retry loop uses.
    """
    from app.graph.nodes import _is_usable
    from app.models.enums import AssessmentType
    from app.models.schemas import GeneratedProblem

    def problem(**kw):
        return GeneratedProblem(
            title="t", prompt="p", skill="loops",
            difficulty=Difficulty.EASY, assessment_type=AssessmentType.CODING, **kw
        )

    assert not _is_usable(problem()), "nothing to grade against"
    assert not _is_usable(problem(expected_output="   ")), "whitespace is not an answer"
    assert _is_usable(problem(expected_output="10"))
    assert _is_usable(
        problem(test_cases=[{"name": "a", "stdin": "", "expected_output": "10"}])
    )


def test_every_ladder_task_is_gradeable() -> None:
    """The fallback is what the retry loop drops to, so it must never be unmarkable."""
    from app.graph.nodes import _is_usable, _template_problem

    for skill in LADDER:
        for level in Difficulty:
            built = _template_problem({"target_skill": skill, "difficulty_level": level})
            assert _is_usable(built), f"{skill}/{level.value} cannot be graded"


def test_every_skill_in_the_curriculum_has_a_ladder() -> None:
    """A skill in skills.yaml but not in LADDER falls to the generic rung, which has no
    authored tasks -- so its fallback has no expected output and cannot be graded.

    That is a silent failure: the skill works, generates, and then marks every correct
    answer wrong. Adding a skill without a ladder must break a test rather than a student.
    """
    import yaml

    configured = set(yaml.safe_load(Path("app/config/skills.yaml").read_text(encoding="utf-8")))
    missing = configured - set(LADDER)
    assert not missing, f"skills with no difficulty ladder: {sorted(missing)}"

    for skill in configured:
        for level in Difficulty:
            assert rung_for(skill, level).variants, (
                f"{skill}/{level.value} has no authored task, so its fallback is ungradeable"
            )
