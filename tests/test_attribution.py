"""Which skill a failure is debited against.

The bug this file exists to prevent: a student on a loops exercise writes a name before
defining it, the tutor correctly says so in its feedback, and loops takes the whole
penalty while variables -- the skill actually implicated -- is untouched.
"""

from pathlib import Path

import pytest

from app.mastery.attribution import ALPHA, debits
from app.mastery.bkt import BKTParams, update_skill
from app.mastery.evidence import Observation, evidence_weight
from app.mastery.skill_graph import SkillGraph
from app.models.enums import StudentOutcome
from app.models.schemas import SkillNode

PRM = BKTParams()

# The real curriculum DAG, not a fixture: the one-hop rule is only meaningful against the
# actual prerequisite edges the app ships.
SKILLS = Path(__file__).resolve().parents[1] / "app" / "config" / "skills.yaml"


@pytest.fixture(scope="module")
def graph() -> SkillGraph:
    return SkillGraph.from_yaml(str(SKILLS))


def test_shares_always_partition_one_observation(graph):
    """No arrangement of inputs can create or destroy evidence."""

    names = list(graph.nodes)
    for target in names:
        prereqs = graph.nodes[target].prerequisites
        for hint in names + [None]:
            got = debits(target, hint, prereqs)
            assert sum(share for _, share in got) == pytest.approx(1.0)
            assert len({skill for skill, _ in got}) == len(got)  # no skill twice


def test_a_direct_prerequisite_is_debited(graph):
    got = debits("loops", "variables", graph.nodes["loops"].prerequisites)
    assert got == [("loops", 1.0 - ALPHA), ("variables", ALPHA)]


def test_a_two_hop_hint_is_ignored(graph):
    """functions is a prerequisite of recursion, not of recursion_tree. One mistake must
    not repaint a skill two edges away."""

    prereqs = graph.nodes["recursion_tree"].prerequisites
    assert "functions" not in prereqs
    assert debits("recursion_tree", "functions", prereqs) == [("recursion_tree", 1.0)]


def test_no_hint_is_a_full_debit(graph):
    assert debits("loops", None, graph.nodes["loops"].prerequisites) == [("loops", 1.0)]


def test_a_hint_naming_the_target_is_a_full_debit(graph):
    assert debits("loops", "loops", graph.nodes["loops"].prerequisites) == [("loops", 1.0)]


def test_at_most_two_skills_move(graph):
    for target in graph.nodes:
        for hint in list(graph.nodes) + [None]:
            assert len(debits(target, hint, graph.nodes[target].prerequisites)) <= 2


def test_the_published_nameerror_example(graph):
    """The demo: a scope error on a loops exercise moves BOTH skills, and honestly.

    Before this change loops alone fell to 0.1695 and variables did not move at all.
    """

    obs = Observation(
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR, score=0.0, distinct_expectations=2
    )
    assert evidence_weight(obs) == pytest.approx(0.60)

    loops = SkillNode(skill="loops", mastery=0.300, confidence=0.0)
    variables = SkillNode(skill="variables", mastery=0.450, confidence=0.0)
    split = debits("loops", "variables", graph.nodes["loops"].prerequisites)

    moved = {}
    for skill, share in split:
        node = loops if skill == "loops" else variables
        updated, audit = update_skill(
            node, obs, PRM, share=share,
            attributed_from=None if skill == "loops" else "loops",
        )
        moved[skill] = (updated, audit)

    assert round(moved["loops"][0].mastery, 4) == 0.2330
    assert round(moved["variables"][0].mastery, 4) == 0.3205

    # The audit trail says why variables moved during a loops exercise.
    assert moved["variables"][1].attributed_from == "loops"
    assert moved["loops"][1].attributed_from is None

    # And the two slices are exactly one observation, not two.
    total = moved["loops"][1].weight + moved["variables"][1].weight
    assert total == pytest.approx(evidence_weight(obs))


def test_splitting_costs_the_target_less_than_the_whole_debit(graph):
    """The point of attribution: the practised skill stops absorbing someone else's fault."""

    obs = Observation(
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR, score=0.0, distinct_expectations=2
    )
    node = SkillNode(skill="loops", mastery=0.300, confidence=0.0)
    whole, _ = update_skill(node, obs, PRM, share=1.0)
    part, _ = update_skill(node, obs, PRM, share=1.0 - ALPHA)
    assert part.mastery > whole.mastery
    assert round(whole.mastery, 4) == 0.1695


def test_a_well_established_prerequisite_is_still_dented(graph):
    """Protecting a high score from real evidence would stop it being a measurement."""

    obs = Observation(
        outcome=StudentOutcome.STUDENT_RUNTIME_ERROR, score=0.0, distinct_expectations=2
    )
    strong = SkillNode(skill="variables", mastery=0.95, confidence=0.9)
    updated, _ = update_skill(strong, obs, PRM, share=ALPHA)
    assert updated.mastery < 0.95


def test_debiting_an_unmeasured_prerequisite_marks_it_measured(graph):
    obs = Observation(outcome=StudentOutcome.WRONG_ANSWER, score=0.0, distinct_expectations=2)
    fresh = SkillNode(skill="variables", mastery=PRM.p_init, confidence=0.0)
    assert fresh.measured is False
    updated, _ = update_skill(fresh, obs, PRM, share=ALPHA)
    assert updated.measured is True
    assert updated.confidence > 0.0
