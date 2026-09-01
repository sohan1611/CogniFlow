"""A simulated student with a hidden, causally-structured skill vector.

Invariant: the simulator's latent skills are NEVER visible to any policy under test.
Policies see only correct/incorrect, exactly as the real system does.

WHY THE CAUSAL STRUCTURE MATTERS
If success on recursion depended only on a `recursion` parameter, then no adaptation
policy could beat another by discovering prerequisites -- drilling recursion would work
just as well as fixing functions first, and the ablation would measure nothing.

So this simulator encodes the pedagogical claim the whole project rests on:

  1. GATING -- a missing prerequisite suppresses performance on the dependent skill.
     A student who does not understand function calls will fail recursion problems no
     matter how many they attempt.
  2. BLOCKED LEARNING -- practising a skill whose prerequisites are missing barely
     teaches anything. This is what makes drilling the surface skill genuinely wasteful
     and finding the prerequisite genuinely valuable.

Both effects are properties of the ENVIRONMENT, not of any policy, so every arm of the
ablation faces exactly the same world.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.mastery.skill_graph import SkillGraph

# A prerequisite is "held" once the latent skill passes this. Distinct from the
# system's own mastery threshold, which is an ESTIMATE of this and never sees it.
PREREQ_HELD = 0.60


@dataclass
class SimConfig:
    """Knobs for the simulated world."""

    prereq_penalty: float = 0.30
    """Multiplier applied per unheld prerequisite. 0.30 means a student with a missing
    prerequisite performs at ~30% of their nominal ability on the dependent skill."""

    learn_rate: float = 0.22
    """Fraction of the remaining gap closed by one productive attempt."""

    blocked_learn_rate: float = 0.03
    """Learning rate when prerequisites are missing. Deliberately near zero: this is
    the 'drilling recursion does not teach recursion' effect."""

    slip: float = 0.08
    guess: float = 0.15
    forget: float = 0.0


@dataclass
class SimulatedStudent:
    """A student whose true competence is hidden from the tutor."""

    true_skill: dict[str, float]
    graph: SkillGraph
    config: SimConfig = field(default_factory=SimConfig)
    rng: random.Random = field(default_factory=random.Random)
    history: list[tuple[str, bool]] = field(default_factory=list)

    # -- hidden mechanics --------------------------------------------------
    def _gate(self, skill: str) -> float:
        """Multiplier from unheld prerequisites."""
        gate = 1.0
        for prereq in self.graph.prerequisites(skill):
            if self.true_skill.get(prereq, 0.0) < PREREQ_HELD:
                gate *= self.config.prereq_penalty
        return gate

    def effective_ability(self, skill: str) -> float:
        return self.true_skill.get(skill, 0.0) * self._gate(skill)

    def prerequisites_held(self, skill: str) -> bool:
        return all(
            self.true_skill.get(p, 0.0) >= PREREQ_HELD
            for p in self.graph.prerequisites(skill)
        )

    # -- what the tutor observes ------------------------------------------
    def attempt(self, skill: str) -> bool:
        """Answer one problem, then learn from it. Returns correctness only."""
        ability = self.effective_ability(skill)
        p_correct = ability * (1 - self.config.slip) + (1 - ability) * self.config.guess
        correct = self.rng.random() < p_correct

        rate = (
            self.config.learn_rate
            if self.prerequisites_held(skill)
            else self.config.blocked_learn_rate
        )
        current = self.true_skill.get(skill, 0.0)
        self.true_skill[skill] = current + rate * (1.0 - current)

        if self.config.forget:
            for other in self.true_skill:
                if other != skill:
                    self.true_skill[other] *= 1.0 - self.config.forget

        self.history.append((skill, correct))
        return correct

    def assess(self, skill: str) -> bool:
        """Observe performance WITHOUT teaching.

        A diagnostic question measures; it does not remediate. Keeping assessment
        learning-free is what stops a pre-test from quietly fixing the very gap the
        experiment is trying to detect -- with learning enabled, two attempts at a
        prerequisite closes it for every arm and the ablation measures nothing.
        """
        ability = self.effective_ability(skill)
        p_correct = ability * (1 - self.config.slip) + (1 - ability) * self.config.guess
        return self.rng.random() < p_correct

    def has_mastered(self, skill: str) -> bool:
        return self.true_skill.get(skill, 0.0) >= PREREQ_HELD


def make_cohort(
    graph_nodes: dict,
    *,
    n: int,
    target: str = "recursion",
    planted_gap: str = "functions",
    seed: int = 20260913,
    config: SimConfig | None = None,
) -> list[tuple[SimulatedStudent, str]]:
    """Build a cohort where a KNOWN prerequisite gap causes failure on `target`.

    Returns (student, planted_gap_skill) pairs. Because we plant the gap ourselves,
    "did the policy find it?" is scored exactly rather than judged.

    Half the cohort gets the planted gap; the other half is weak at the target skill
    with prerequisites intact. That control half matters: a policy that redirects to a
    prerequisite ALWAYS would look good on gapped students alone. Including students
    with no gap is what separates diagnosis from a reflex.
    """
    from app.mastery.skill_graph import SkillGraph

    rng = random.Random(seed)
    graph = SkillGraph(graph_nodes)
    cohort: list[tuple[SimulatedStudent, str]] = []

    for i in range(n):
        gapped = i % 2 == 0
        true_skill = {
            skill: rng.uniform(0.72, 0.95) for skill in graph_nodes
        }
        true_skill[target] = rng.uniform(0.15, 0.35)

        if gapped:
            # The real cause: the prerequisite is genuinely missing.
            true_skill[planted_gap] = rng.uniform(0.15, 0.40)
            gap = planted_gap
        else:
            # Control: weak at the target, prerequisites genuinely intact.
            true_skill[planted_gap] = rng.uniform(0.75, 0.95)
            gap = ""

        cohort.append(
            (
                SimulatedStudent(
                    true_skill=true_skill,
                    graph=graph,
                    config=config or SimConfig(),
                    rng=random.Random(seed + i * 7919),
                ),
                gap,
            )
        )
    return cohort
