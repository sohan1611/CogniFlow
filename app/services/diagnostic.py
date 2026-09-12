"""Adaptive diagnostic: work out what a new student already knows, by asking.

Until now a new student was handed a fixed starting profile -- everyone began believing
exactly the same things, because `seed_student` wrote the same numbers every time. A
tutor whose first act is to assume is not a tutor that "remembers what you know"; it is
one that has decided in advance.

What makes this adaptive rather than a quiz:

  * Questions are asked in prerequisite order, foundations first, because an answer
    about recursion means nothing until we know whether they have functions.
  * **A failed skill prunes everything downstream of it.** Someone who cannot write a
    function will fail recursion too, and asking them to prove it twice tells us nothing
    we did not already know and costs them the will to continue. The prerequisite graph
    already encodes exactly which questions those are.
  * Every answer updates a real BKT belief. Mastery after the diagnostic is EVIDENCE,
    not a constant.

Graded by execution, like everything else here. No model is called: a diagnostic whose
questions change between runs cannot be compared across students, and comparing students
is most of what a diagnostic is for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.mastery.bkt import BKTParams, update
from app.mastery.evidence import (
    Observation,
    accumulate,
    confidence_from_evidence,
    coverage,
)
from app.mastery.skill_graph import SkillGraph
from app.models.enums import StudentOutcome
from app.models.schemas import DiagnosticResult, SkillNode

# The prior for someone we have never met. It is BKTParams.p_init and nothing else: this
# module used to carry its own 0.5, which silently overrode the p_init the rest of the
# system believed it was using, so two disagreeing priors existed and the documented one
# was the unreachable one.
UNKNOWN_MASTERY = BKTParams().p_init


@dataclass(frozen=True)
class DiagnosticQuestion:
    """One probe at one skill.

    `expected_output` is what a correct submission prints, so the answer is graded by
    running it -- the same path a real exercise takes.
    """

    skill: str
    prompt: str
    starter_code: str
    expected_output: str

    def as_problem(self) -> dict[str, object]:
        """The shape the sandbox runner and the UI already understand."""
        return {
            "title": f"Diagnostic: {self.skill}",
            "prompt": self.prompt,
            "skill": self.skill,
            "starter_code": self.starter_code,
            "expected_output": self.expected_output,
            "test_cases": [
                {"name": "diagnostic", "stdin": "", "expected_output": self.expected_output}
            ],
        }


# One question per skill, deliberately short. A diagnostic that takes twenty minutes is
# one students abandon, and an abandoned diagnostic produces a worse profile than a brief
# one. Each probes the single idea the skill is named for, not its edge cases.
QUESTIONS: tuple[DiagnosticQuestion, ...] = (
    DiagnosticQuestion(
        skill="variables",
        prompt="Set a variable to 7, add 3 to it, and print the result.",
        starter_code="",
        expected_output="10",
    ),
    DiagnosticQuestion(
        skill="conditionals",
        prompt="Print 'big' if x is greater than 5, otherwise print 'small'. Use x = 9.",
        starter_code="x = 9\n",
        expected_output="big",
    ),
    DiagnosticQuestion(
        skill="loops",
        prompt="Print the total of the numbers 1 to 4 using a loop.",
        starter_code="",
        expected_output="10",
    ),
    DiagnosticQuestion(
        skill="functions",
        prompt=(
            "Write a function called double that RETURNS its argument multiplied by 2, "
            "then print double(6)."
        ),
        starter_code="",
        expected_output="12",
    ),
    DiagnosticQuestion(
        skill="function_call_tracing",
        prompt=(
            "Work out what this prints, then write a program that prints that value.\n\n"
            "def square(x):\n"
            "    return x * x\n\n"
            "def calculate(a):\n"
            "    return square(a) + 1\n\n"
            "print(calculate(3))"
        ),
        starter_code="",
        expected_output="10",
    ),
    DiagnosticQuestion(
        skill="recursion",
        prompt="Write a recursive function that returns 1 + 2 + ... + n, and print it for n = 4.",
        starter_code="",
        expected_output="10",
    ),
    DiagnosticQuestion(
        skill="nested_loops",
        prompt="Using two loops, print how many pairs (i, j) exist for i in 1..3 and j in 1..3.",
        starter_code="",
        expected_output="9",
    ),
    DiagnosticQuestion(
        skill="recursion_tree",
        prompt=(
            "A function calls itself twice per level, for 3 levels. "
            "Print how many calls are made at the deepest level."
        ),
        starter_code="",
        expected_output="8",
    ),
)


@dataclass
class DiagnosticSession:
    """A diagnostic in progress.

    Holds its own belief state rather than mutating the student's, so an abandoned
    diagnostic leaves nothing behind. Only `finish()` produces something to persist.
    """

    graph: SkillGraph
    bkt: BKTParams = field(default_factory=BKTParams)
    answered: dict[str, StudentOutcome] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    """skill -> the failed prerequisite that made asking pointless."""

    _beliefs: dict[str, tuple[float, int, float, float, float]] = field(default_factory=dict)
    """skill -> (mastery, attempts, evidence_weight, agree_correct, agree_wrong).

    The last three are what confidence is computed from. Carried here rather than
    recomputed from `answered` so the diagnostic's arithmetic is identical to the one the
    graph uses for ordinary attempts."""

    def __post_init__(self) -> None:
        if not self._beliefs:
            self._beliefs = {s: (UNKNOWN_MASTERY, 0, 0.0, 0.0, 0.0) for s in self.graph.nodes}

    # -- ordering ----------------------------------------------------------
    def _order(self) -> list[DiagnosticQuestion]:
        """Questions in prerequisite order: nothing is asked before its foundations.

        Depth in the prerequisite graph is the ordering key, so `variables` precedes
        `functions` precedes `recursion` regardless of how QUESTIONS happens to be
        written.
        """
        def depth(skill: str, seen: frozenset[str] = frozenset()) -> int:
            if skill in seen:
                return 0
            prereqs = self.graph.prerequisites(skill)
            if not prereqs:
                return 0
            return 1 + max(depth(p, seen | {skill}) for p in prereqs)

        return sorted(QUESTIONS, key=lambda q: (depth(q.skill), q.skill))

    def next_question(self) -> DiagnosticQuestion | None:
        """The next question worth asking, or None when the diagnostic is done.

        Skips anything whose prerequisite the student has already failed: that answer is
        already known, and making them prove it twice is discouraging and uninformative.
        """
        for question in self._order():
            if question.skill in self.answered or question.skill in self.skipped:
                continue
            blocker = self._failed_prerequisite(question.skill)
            if blocker is not None:
                self.skipped[question.skill] = blocker
                continue
            return question
        return None

    def _failed_prerequisite(self, skill: str) -> str | None:
        """A prerequisite this student got wrong, directly or further up the chain."""
        for prereq in self.graph.prerequisites(skill):
            if self.answered.get(prereq) not in (None, StudentOutcome.CORRECT):
                return prereq
            if prereq in self.skipped:
                return self.skipped[prereq]
            deeper = self._failed_prerequisite(prereq)
            if deeper is not None:
                return deeper
        return None

    # -- recording ---------------------------------------------------------
    def record(self, skill: str, outcome: StudentOutcome) -> None:
        """Fold one answer into the belief for that skill."""
        mastery, attempts, weight, agreed, against = self._beliefs.get(
            skill, (UNKNOWN_MASTERY, 0, 0.0, 0.0, 0.0)
        )
        # Every diagnostic question is graded against a SINGLE expected output, so
        # distinct_expectations is 1 and guess_for prices it at 0.20 -- the weakest
        # instrument we own. Four of the eight expect the literal "10", so `print(10)`
        # passes half the diagnostic; a pass here is deliberately worth less than a pass
        # on a real exercise carrying several distinct cases.
        obs = Observation(outcome=outcome, score=0.0, distinct_expectations=1)
        weight, agreed, against = accumulate(weight, agreed, against, obs)
        self._beliefs[skill] = (
            update(mastery, obs, self.bkt), attempts + 1, weight, agreed, against,
        )
        self.answered[skill] = outcome

    # -- result ------------------------------------------------------------
    def finish(self, mastery_threshold: float) -> tuple[dict[str, SkillNode], DiagnosticResult]:
        """The student profile this diagnostic justifies, and what it concluded.

        A skipped skill inherits the belief its failed prerequisite earned, capped below
        the mastery threshold. That is honest in both directions: we did not test it, but
        we have real evidence they are not ready for it, and recording 0.5 "unknown"
        would let the planner send them straight at a skill we already know is blocked.
        """
        nodes: dict[str, SkillNode] = {}
        for skill, node in self.graph.nodes.items():
            mastery, attempts, weight, agreed, against = self._beliefs[skill]
            if skill in self.skipped:
                blocker = self.skipped[skill]
                inherited = self._beliefs.get(
                    blocker, (UNKNOWN_MASTERY, 0, 0.0, 0.0, 0.0)
                )[0]
                mastery = min(inherited, mastery_threshold - 0.05)
            nodes[skill] = node.model_copy(
                update={
                    "mastery": round(mastery, 4),
                    "confidence": round(
                        confidence_from_evidence(
                            weight, agreed, against, self.bkt.p_slip, self.bkt.p_guess
                        ),
                        4,
                    ),
                    "attempts": attempts,
                    "evidence_weight": round(weight, 6),
                    "agree_correct": round(agreed, 6),
                    "agree_wrong": round(against, 6),
                }
            )

        graded = SkillGraph(nodes)
        weak = sorted(
            (s for s, n in nodes.items() if n.mastery < mastery_threshold),
            # Alphabetical tie-break, matching skill_graph.weakest_startable exactly.
            #
            # This deliberately still names the weakest skill OVERALL, even one that is
            # locked -- "your weakest area is recursion, and functions is what stands in
            # the way" is the whole product, and reducing it to the startable skill
            # would throw the diagnosis away and keep only the next step.
            #
            # What it must not do is disagree with the plan for no reason. Seen on the
            # deployed app: loops and functions were both unmastered, both startable and
            # TIED, and the two selectors broke the tie differently -- this one by graph
            # order, the plan alphabetically -- so the check said "Start here: loops"
            # while the plan flagged functions, one screen apart. With the same
            # tie-break they agree whenever the weakest skill is startable, and when it
            # is not, the difference is the diagnosis rather than a contradiction.
            # Ties prefer a skill the student can actually START. Same mastery, but
            # one of them is blocked -- naming the blocked one as the headline is
            # arbitrary and puts the plan's suggestion at odds with it for no reason.
            # A STRICTLY weaker locked skill still wins, which is the case that
            # matters: "your weakest area is recursion, and functions is in the way".
            key=lambda s: (
                nodes[s].mastery,
                bool(graded.unmastered_prerequisites(s, mastery_threshold)),
                s,
            ),
        )
        target = weak[0] if weak else None
        missing = (
            graded.unmastered_prerequisites(target, mastery_threshold) if target else []
        )
        evidence = [
            f"{skill}={outcome.value}" for skill, outcome in sorted(self.answered.items())
        ] + [f"{skill}=skipped:{blocker}" for skill, blocker in sorted(self.skipped.items())]

        return nodes, DiagnosticResult(
            weak_skills=weak[:5],
            target_skill=target,
            missing_prerequisites=missing,
            # Confidence in the DIAGNOSIS, which is a function of how much we asked --
            # not of how well they did. Four answers is a sketch; eight is a picture.
            confidence=round(coverage(len(self.answered)), 4),
            evidence=evidence,
        )
