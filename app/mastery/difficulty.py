"""What EASY, MEDIUM and HARD actually mean, per skill.

Before this existed, difficulty was a label and nothing else. `generate_problem` passed
the model the single word "HARD" with no definition of it, and the deterministic fallback
ignored difficulty entirely -- it emitted the same sentence at every level and changed
only the title, so a student who worked up from EASY to HARD was handed the identical
task three times with a different word in the heading.

The fix is not three stored questions. It is a declarative LADDER of CRITERIA: for each
skill, at each level, what concepts are in play, what cognitive demand is being made, and
what shape of task satisfies it. Those criteria do three jobs:

  1. they go into the generation prompt, so the model is told what HARD means here rather
     than being left to guess;
  2. they drive the deterministic fallback, which can then differ genuinely by level;
  3. they are attached to the generated problem as metadata, so a claim that a task is
     HARD is checkable rather than decorative.

The `variants` on each rung deserve their own note. A fallback that runs when no model is
reachable cannot invent novel prose -- that is what "no model is reachable" means. What it
can do is stop repeating itself, so each rung carries several genuinely distinct tasks and
the generator rotates through them by seed. That is a smaller claim than dynamic
generation and it is the honest one; the live path is where new problems get written.

The cognitive levels are the middle of Bloom's revised taxonomy, which is where a
programming exercise lives: APPLY (use a known procedure), ANALYSE (break a problem down,
reason about cases), CREATE (design something that did not exist). Recall is deliberately
absent: this system never asks a student to restate a definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Difficulty

APPLY = "apply"
ANALYSE = "analyse"
CREATE = "create"


@dataclass(frozen=True)
class Task:
    """One concrete exercise. Used by the fallback and as a shape example for the model."""

    prompt: str
    expected: str
    starter: str = ""


@dataclass(frozen=True)
class Rung:
    """One skill at one difficulty.

    `brief` is written at the model: it says what a task at this level must demand of the
    student, in the imperative. `demands` is written at a human reading the event log.
    """

    concepts: tuple[str, ...]
    cognitive_level: str
    complexity: str
    brief: str
    demands: str
    variants: tuple[Task, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- the ladder
LADDER: dict[str, dict[Difficulty, Rung]] = {
    "variables": {
        Difficulty.EASY: Rung(
            concepts=("assignment", "arithmetic"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief="One assignment, one operation on it, one print. No branching, no loops.",
            demands="a single stored value changed once",
            variants=(
                Task("Set a variable to 7, add 3 to it, and print the result.", "10"),
                Task("Set a variable to 20, halve it with integer division, and print the result.", "10"),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("assignment", "multiple_bindings", "expression_order"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief=(
                "Several variables that depend on each other, where the ORDER of "
                "assignment changes the answer. The student must track state, not just "
                "evaluate one expression."
            ),
            demands="several values whose order of assignment matters",
            variants=(
                Task(
                    "You have a = 5 and b = 12. Swap their values without using a third "
                    "variable, then print a followed by b on one line, separated by a space.",
                    "12 5",
                ),
                Task(
                    "Set price to 250 and discount to 40. Compute the final price after "
                    "the discount is taken off, then add 18% tax on that reduced amount. "
                    "Print the result rounded to two decimal places.",
                    "247.8",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("aliasing", "mutability", "reference_semantics"),
            cognitive_level=ANALYSE,
            complexity="O(1)",
            brief=(
                "Aliasing. Two names bound to the SAME mutable object, where mutating "
                "through one is visible through the other. The student must reason about "
                "references rather than values."
            ),
            demands="reasoning about two names bound to one object",
            variants=(
                Task(
                    "Work out what this prints, then write a program that prints that "
                    "value.\n\n"
                    "a = [1, 2, 3]\n"
                    "b = a\n"
                    "b.append(4)\n"
                    "c = a[:]\n"
                    "c.append(5)\n"
                    "print(len(a), len(b), len(c))",
                    "4 4 5",
                ),
            ),
        ),
    },
    "conditionals": {
        Difficulty.EASY: Rung(
            concepts=("if_else", "comparison"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief="A single if/else on one comparison. Exactly two outcomes.",
            demands="one comparison, two branches",
            variants=(
                Task("Print 'big' if x is greater than 5, otherwise print 'small'. Use x = 9.", "big"),
                Task("Print 'even' if n divides by 2 exactly, otherwise print 'odd'. Use n = 7.", "odd"),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("elif_chain", "boundary_conditions"),
            cognitive_level=ANALYSE,
            complexity="O(1)",
            brief=(
                "A chain of at least three branches where the BOUNDARIES matter -- a "
                "value sitting exactly on a threshold must land in the right band. The "
                "student has to get the comparison operators right, not just the shape."
            ),
            demands="a multi-band decision where the boundaries are the difficulty",
            variants=(
                Task(
                    "A score of 90 or above is grade A, 75 to 89 is B, 60 to 74 is C, and "
                    "anything below 60 is F. Print the grade for a score of exactly 75, "
                    "then on the next line the grade for exactly 60.",
                    "B\nC",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("boolean_logic", "short_circuit", "compound_conditions"),
            cognitive_level=ANALYSE,
            complexity="O(1)",
            brief=(
                "Compound boolean logic with an exception inside an exception, or "
                "short-circuit evaluation that changes whether an expression is even "
                "evaluated. Getting it right requires reasoning about the whole "
                "condition, not reading it left to right."
            ),
            demands="nested rules where a naive reading gives the wrong answer",
            variants=(
                Task(
                    "A year is a leap year if it divides by 4, EXCEPT century years, which "
                    "must divide by 400. Print True or False for 1900, then 2000, then "
                    "2024, one per line.",
                    "False\nTrue\nTrue",
                ),
            ),
        ),
    },
    "loops": {
        Difficulty.EASY: Rung(
            concepts=("for_loop", "accumulator"),
            cognitive_level=APPLY,
            complexity="O(n)",
            brief="One loop, one accumulator, a fixed range. Nothing to decide inside the loop.",
            demands="a single pass with a running total",
            variants=(
                Task("Print the total of the numbers 1 to 4 using a loop.", "10"),
                Task("Print the total of the even numbers from 1 to 10 using a loop.", "30"),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("loop_with_condition", "early_exit", "edge_cases"),
            cognitive_level=ANALYSE,
            complexity="O(n)",
            brief=(
                "A loop carrying a decision: skipping items, stopping early, or tracking "
                "two things at once. Include a case where the obvious implementation is "
                "off by one or mishandles an empty or single-element input."
            ),
            demands="a pass that must decide, and that has an edge case",
            variants=(
                Task(
                    "Given numbers = [4, 4, 9, 2, 9, 1], print the SECOND largest DISTINCT "
                    "value. Duplicates must not count twice. Print 'none' if there is no "
                    "second distinct value.",
                    "4",
                ),
                Task(
                    "Given words = ['apple', '', 'fig', '', 'plum'], print how many are "
                    "non-empty, then the longest of them, one per line.",
                    "3\napple",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("single_pass", "invariant", "complexity"),
            cognitive_level=CREATE,
            complexity="O(n)",
            brief=(
                "An algorithm the student has to DESIGN, not a pattern to follow. It must "
                "be solvable in ONE pass, and the obvious solution should be the slower "
                "multi-pass or sorted one, so there is a real choice to reason about."
            ),
            demands="designing a single-pass algorithm where the obvious answer is slower",
            variants=(
                Task(
                    "Given prices = [7, 1, 5, 3, 6, 4], you may buy once and sell once, "
                    "and you must buy before you sell. Print the largest profit possible. "
                    "Print 0 if no profit can be made. Solve it in a single pass -- do not "
                    "compare every pair.",
                    "5",
                ),
                Task(
                    "Given nums = [2, 2, 1, 3, 3, 1, 2], print the value that appears an "
                    "odd number of times. Exactly one value does. Do it in one pass "
                    "without building a count for every value.",
                    "2",
                ),
            ),
        ),
    },
    "functions": {
        Difficulty.EASY: Rung(
            concepts=("def", "return", "call"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief=(
                "Define one function that RETURNS a value, call it, print the result. The "
                "point is return versus print, so the task must require a returned value."
            ),
            demands="one function that returns rather than prints",
            variants=(
                Task(
                    "Write a function called double that RETURNS its argument multiplied "
                    "by 2, then print double(6).",
                    "12",
                ),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("composition", "parameters", "return_values"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief=(
                "Two or more functions where one consumes another's return value, or a "
                "function with a default parameter that is overridden. The student must "
                "follow a value across a boundary."
            ),
            demands="a value handed from one function to another",
            variants=(
                Task(
                    "Write a function area(w, h) that returns w * h, and a function "
                    "total_area(rooms) that takes a list of (w, h) pairs and returns the "
                    "sum of their areas using area(). Print total_area([(2, 3), (4, 5)]).",
                    "26",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("higher_order_functions", "closures", "scope"),
            cognitive_level=CREATE,
            complexity="O(n)",
            brief=(
                "A function that takes or returns another function, or a closure that "
                "captures state between calls. The student must treat a function as a "
                "value rather than as a place to put code."
            ),
            demands="building a function that produces or consumes another function",
            variants=(
                Task(
                    "Write make_counter() that returns a function. Each call to the "
                    "returned function gives the next integer, starting at 1. Two counters "
                    "made separately must not share state.\n\n"
                    "c1 = make_counter()\n"
                    "c2 = make_counter()\n"
                    "print(c1(), c1(), c2(), c1())",
                    "1 2 1 3",
                ),
            ),
        ),
    },
    "function_call_tracing": {
        Difficulty.EASY: Rung(
            concepts=("call_order", "return_value"),
            cognitive_level=APPLY,
            complexity="O(1)",
            brief="One function calling one other. Trace the value out and print it.",
            demands="following one value through one call",
            variants=(
                Task(
                    "Work out what this prints, then write a program that prints that "
                    "value.\n\n"
                    "def square(x):\n    return x * x\n\n"
                    "def calculate(a):\n    return square(a) + 1\n\n"
                    "print(calculate(3))",
                    "10",
                ),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("nested_calls", "argument_evaluation", "local_scope"),
            cognitive_level=ANALYSE,
            complexity="O(1)",
            brief=(
                "Several calls where a local name shadows an outer one, or where "
                "arguments are evaluated in an order that matters. Reading top to bottom "
                "should give the wrong answer."
            ),
            demands="calls where a shadowed name misleads a casual reading",
            variants=(
                Task(
                    "Work out what this prints, then write a program that prints that "
                    "value.\n\n"
                    "total = 10\n\n"
                    "def bump(total):\n"
                    "    total = total + 5\n"
                    "    return total\n\n"
                    "result = bump(total)\n"
                    "print(total, result)",
                    "10 15",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("mutable_default", "shared_state", "call_history"),
            cognitive_level=ANALYSE,
            complexity="O(1)",
            brief=(
                "State that survives between calls -- a mutable default argument, or an "
                "object mutated through a parameter. The output depends on the HISTORY of "
                "calls, not just the current one."
            ),
            demands="output that depends on what was called before",
            variants=(
                Task(
                    "Work out what this prints, then write a program that prints those "
                    "lines.\n\n"
                    "def collect(item, bag=[]):\n"
                    "    bag.append(item)\n"
                    "    return bag\n\n"
                    "print(collect(1))\n"
                    "print(collect(2))\n"
                    "print(collect(3, []))",
                    "[1]\n[1, 2]\n[3]",
                ),
            ),
        ),
    },
    "recursion": {
        Difficulty.EASY: Rung(
            concepts=("base_case", "recursive_call"),
            cognitive_level=APPLY,
            complexity="O(n)",
            brief="One base case, one recursive call, a number that shrinks by one.",
            demands="a single shrinking parameter and one stopping condition",
            variants=(
                Task(
                    "Write a recursive function that returns 1 + 2 + ... + n, and print it "
                    "for n = 4.",
                    "10",
                ),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("recursion_over_sequence", "empty_case", "accumulation"),
            cognitive_level=ANALYSE,
            complexity="O(n)",
            brief=(
                "Recursion over a sequence rather than a counter, where the EMPTY case is "
                "the base case and getting it wrong crashes or loops. The student must "
                "decide what 'smaller' means."
            ),
            demands="choosing the base case when the input is a sequence",
            variants=(
                Task(
                    "Write a recursive function that returns True if a string is a "
                    "palindrome and False otherwise. It must handle the empty string and "
                    "a single character. Print the result for 'racecar', then '', then "
                    "'abca', one per line.",
                    "True\nTrue\nFalse",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("divide_and_conquer", "recurrence_design", "complexity"),
            cognitive_level=CREATE,
            complexity="O(log n)",
            brief=(
                "The student must DESIGN the recurrence: split the problem, decide which "
                "half to recurse into, and prove to themselves it terminates. Not a "
                "pattern they can copy from the EASY rung."
            ),
            demands="designing a divide-and-conquer recurrence",
            variants=(
                Task(
                    "Write a recursive binary search that returns the INDEX of a target in "
                    "a sorted list, or -1 if it is absent. Do not scan the list. Print the "
                    "result for target 7 in [1, 3, 5, 7, 9, 11], then for target 4, one "
                    "per line.",
                    "3\n-1",
                ),
            ),
        ),
    },
    "recursion_tree": {
        Difficulty.EASY: Rung(
            concepts=("branching_recursion",),
            cognitive_level=APPLY,
            complexity="O(2^n)",
            brief="Write the naive two-branch recursion and print one value of it.",
            demands="a recursion that calls itself twice",
            variants=(
                Task(
                    "Write the naive recursive Fibonacci where fib(0) = 0 and fib(1) = 1, "
                    "and print fib(7).",
                    "13",
                ),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("call_counting", "tree_shape"),
            cognitive_level=ANALYSE,
            complexity="O(2^n)",
            brief=(
                "Make the SHAPE of the recursion visible -- count the calls, or the depth. "
                "The student has to instrument the recursion rather than just run it."
            ),
            demands="measuring the recursion instead of only using it",
            variants=(
                Task(
                    "Write the naive recursive Fibonacci and count how many times the "
                    "function is called in total when computing fib(6). Print fib(6) on "
                    "the first line and the call count on the second.",
                    "8\n25",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("memoisation", "complexity_tradeoff", "overlapping_subproblems"),
            cognitive_level=CREATE,
            complexity="O(n)",
            brief=(
                "Turn the exponential tree into a linear one with memoisation, and make "
                "the student demonstrate the difference. This is the level where "
                "complexity stops being trivia and becomes the point."
            ),
            demands="collapsing an exponential recursion and showing the saving",
            variants=(
                Task(
                    "The naive recursive Fibonacci recomputes the same values over and "
                    "over. Add memoisation so each value is computed once, then print "
                    "fib(35). The naive version cannot finish this inside the sandbox's "
                    "time limit; a memoised one is instant.",
                    "9227465",
                ),
            ),
        ),
    },
    "nested_loops": {
        Difficulty.EASY: Rung(
            concepts=("nested_iteration",),
            cognitive_level=APPLY,
            complexity="O(n^2)",
            brief="A loop inside a loop producing a fixed rectangular pattern.",
            demands="one loop inside another, no decisions",
            variants=(
                Task(
                    "Using two loops, print how many pairs (i, j) exist for i in 1..3 and "
                    "j in 1..3.",
                    "9",
                ),
            ),
        ),
        Difficulty.MEDIUM: Rung(
            concepts=("dependent_bounds", "condition_in_inner_loop"),
            cognitive_level=ANALYSE,
            complexity="O(n^2)",
            brief=(
                "The inner loop's range must DEPEND on the outer variable, or a condition "
                "inside it filters pairs. A fixed rectangle is not enough at this level."
            ),
            demands="an inner loop whose bounds depend on the outer one",
            variants=(
                Task(
                    "Count the pairs (i, j) with 1 <= i < j <= 5 whose sum is even. Use "
                    "two loops and print the count.",
                    "4",
                ),
            ),
        ),
        Difficulty.HARD: Rung(
            concepts=("quadratic_vs_linear", "algorithm_choice", "complexity"),
            cognitive_level=CREATE,
            complexity="O(n)",
            brief=(
                "Pose a problem whose obvious solution is the nested O(n^2) scan, and "
                "require the student to find and justify the linear alternative. The "
                "nested loop is what they are being taught to OUTGROW here."
            ),
            demands="recognising when a nested loop should be replaced",
            variants=(
                Task(
                    "Given nums = [3, 8, 2, 6, 5] and target = 10, print the two values "
                    "that add up to the target, smaller first, separated by a space. "
                    "Exactly one pair works. Solve it WITHOUT comparing every pair -- a "
                    "single pass is possible.",
                    "2 8",
                ),
            ),
        ),
    },
}


# A skill with no entry still needs a defensible answer rather than a crash.
_GENERIC: dict[Difficulty, Rung] = {
    Difficulty.EASY: Rung(
        concepts=("single_concept",),
        cognitive_level=APPLY,
        complexity="O(1)",
        brief="One concept applied directly, with a predictable input and no edge cases.",
        demands="one concept, applied directly",
    ),
    Difficulty.MEDIUM: Rung(
        concepts=("combined_concepts", "edge_cases"),
        cognitive_level=ANALYSE,
        complexity="O(n)",
        brief=(
            "Two or more concepts combined, with at least one edge case the obvious "
            "solution gets wrong."
        ),
        demands="several concepts together, with an edge case",
    ),
    Difficulty.HARD: Rung(
        concepts=("algorithm_design", "complexity"),
        cognitive_level=CREATE,
        complexity="O(n)",
        brief=(
            "An algorithm the student must design rather than follow, with non-obvious "
            "cases and a reason to prefer one approach over another."
        ),
        demands="designing an algorithm rather than following one",
    ),
}


def rung_for(skill: str, difficulty: Difficulty) -> Rung:
    """The criteria for one skill at one level. Never raises."""
    return LADDER.get(skill, _GENERIC).get(difficulty) or _GENERIC[difficulty]


def ladder_summary(skill: str) -> str:
    """All three levels for a skill, rendered for a generation prompt.

    The model is shown the WHOLE ladder rather than only the rung being asked for,
    because "make this HARD" is meaningless without knowing what EASY already covered.
    Difficulty is a relation between levels, not a property of one.
    """
    lines = []
    for level in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
        rung = rung_for(skill, level)
        lines.append(
            f"{level.value}: {rung.brief} "
            f"(concepts: {', '.join(rung.concepts)}; cognitive level: {rung.cognitive_level})"
        )
    return "\n".join(lines)
