"""Tests for deterministic skill graph behavior.

Invariant: prerequisite graphs are acyclic and address only known skills.
"""

from pathlib import Path

import pytest
import yaml

from app.mastery.skill_graph import SkillGraph
from app.models.errors import SkillGraphError
from app.models.schemas import DEFAULT_MASTERY_PRIOR, SkillNode


def node(
    skill: str,
    mastery: float = 0.5,
    confidence: float = 0.3,
    prerequisites: list[str] | None = None,
) -> SkillNode:
    return SkillNode(
        skill=skill,
        mastery=mastery,
        confidence=confidence,
        prerequisites=prerequisites or [],
    )


def test_skills_yaml_loads_and_is_a_dag() -> None:
    graph = SkillGraph.from_yaml(Path("app/config/skills.yaml"))
    assert set(graph.nodes) == {
        "variables",
        "conditionals",
        "loops",
        "functions",
        "function_call_tracing",
        "recursion",
        "recursion_tree",
        "nested_loops",
    }


def test_cyclic_definition_raises() -> None:
    nodes = {
        "a": node("a", prerequisites=["b"]),
        "b": node("b", prerequisites=["a"]),
    }
    with pytest.raises(SkillGraphError):
        SkillGraph(nodes)


def test_unknown_prerequisite_raises() -> None:
    nodes = {
        "a": node("a", prerequisites=["missing"]),
    }
    with pytest.raises(SkillGraphError):
        SkillGraph(nodes)


def test_recursion_prerequisites_are_sorted() -> None:
    graph = SkillGraph.from_yaml(Path("app/config/skills.yaml"))
    assert graph.prerequisites("recursion") == ["conditionals", "functions"]


def test_weakest_prerequisite_uses_score_and_alphabetical_tie_break() -> None:
    graph = SkillGraph(
        {
            "a": node("a", mastery=0.5, confidence=0.8),
            "b": node("b", mastery=0.2, confidence=1.0),
            "c": node("c", mastery=0.2, confidence=1.0),
            "target": node("target", prerequisites=["c", "b", "a"]),
        }
    )
    assert graph.weakest_prerequisite("target") == "b"


def test_weakest_prerequisite_returns_none_when_all_prereqs_mastered() -> None:
    graph = SkillGraph(
        {
            "a": node("a", mastery=0.6, confidence=0.1),
            "b": node("b", mastery=0.9, confidence=0.1),
            "target": node("target", prerequisites=["a", "b"]),
        }
    )
    assert graph.weakest_prerequisite("target") is None


def test_to_dict_from_dict_round_trips() -> None:
    graph = SkillGraph.from_yaml(Path("app/config/skills.yaml"))
    serialized = graph.to_dict()
    assert SkillGraph.from_dict(serialized).to_dict() == serialized


# ------------------------------------------------------------------ next_skills
def test_next_skills_only_returns_what_is_genuinely_unlocked() -> None:
    """A recommendation the student cannot start is worse than none.

    A dependent counts only when EVERY prerequisite of it is mastered. Otherwise
    "study this next" just moves them to a different wall.
    """
    graph = SkillGraph({
        "variables": SkillNode(skill="variables", mastery=0.9, confidence=0.9),
        "functions": SkillNode(skill="functions", mastery=0.9, confidence=0.9,
                               prerequisites=["variables"]),
        "loops": SkillNode(skill="loops", mastery=0.2, confidence=0.5,
                           prerequisites=["variables"]),
        # needs BOTH functions and loops; loops is still weak
        "comprehensions": SkillNode(skill="comprehensions", mastery=0.1, confidence=0.3,
                                    prerequisites=["functions", "loops"]),
        "recursion": SkillNode(skill="recursion", mastery=0.1, confidence=0.3,
                               prerequisites=["functions"]),
    })

    unlocked = graph.next_skills("functions")
    assert "recursion" in unlocked, "recursion's only prerequisite is mastered"
    assert "comprehensions" not in unlocked, "loops is still unmastered, so it is blocked"


def test_next_skills_is_empty_when_the_skill_itself_is_not_mastered() -> None:
    """Nothing is unlocked by a skill the student has not actually learned."""
    graph = SkillGraph({
        "functions": SkillNode(skill="functions", mastery=0.3, confidence=0.5),
        "recursion": SkillNode(skill="recursion", mastery=0.1, confidence=0.3,
                               prerequisites=["functions"]),
    })
    assert graph.next_skills("functions") == []


def test_next_skills_orders_by_readiness_then_name() -> None:
    """Nearest to ready first, so the recommendation is the gentlest next step."""
    graph = SkillGraph({
        "functions": SkillNode(skill="functions", mastery=0.9, confidence=0.9),
        "alpha": SkillNode(skill="alpha", mastery=0.5, confidence=0.5,
                           prerequisites=["functions"]),
        "beta": SkillNode(skill="beta", mastery=0.1, confidence=0.5,
                          prerequisites=["functions"]),
    })
    assert graph.next_skills("functions") == ["alpha", "beta"]


def test_dependents_is_the_inverse_of_prerequisites() -> None:
    graph = SkillGraph({
        "functions": SkillNode(skill="functions", mastery=0.9, confidence=0.9),
        "recursion": SkillNode(skill="recursion", mastery=0.1, confidence=0.3,
                               prerequisites=["functions"]),
    })
    assert graph.dependents("functions") == ["recursion"]
    assert graph.prerequisites("recursion") == ["functions"]


def test_the_next_skill_is_chosen_by_one_rule_even_on_a_tie() -> None:
    """Found on the deployed app, not by a test.

    The diagnostic ended "Start here: loops" while the learning plan put its START HERE
    flag on functions. Both skills were unmastered and TIED on mastery, and the two
    selectors broke the tie differently -- one walked the graph's own order, the other
    went alphabetically. The student was told one thing and shown another, one screen
    apart.

    The earlier test for this passed because its scenario happened not to tie. This one
    constructs the tie deliberately.
    """
    from app.mastery.skill_graph import weakest_startable
    from app.models.schemas import SkillNode

    def node(skill, mastery, prereqs=()):
        return SkillNode(
            skill=skill, mastery=mastery, confidence=0.3, attempts=1,
            prerequisites=list(prereqs), misconceptions=[],
        )

    # variables is mastered; functions and loops are tied and both startable.
    nodes = {
        "variables": node("variables", 0.85),
        "functions": node("functions", 0.244, ["variables"]),
        "loops": node("loops", 0.244, ["variables"]),
    }
    picked = {weakest_startable(nodes, 0.6) for _ in range(20)}
    assert len(picked) == 1, f"a tie must resolve deterministically, got {picked}"
    assert picked == {"functions"}, "alphabetical tie-break"


def test_skills_yaml_is_only_the_prerequisite_dag() -> None:
    raw = yaml.safe_load(Path("app/config/skills.yaml").read_text(encoding="utf-8"))
    for payload in raw.values():
        assert set(payload) == {"skill", "prerequisites", "misconceptions"}

    nodes = SkillGraph.from_yaml(Path("app/config/skills.yaml")).nodes
    assert all(node.mastery == DEFAULT_MASTERY_PRIOR for node in nodes.values())
    assert all(node.confidence == 0.0 for node in nodes.values())
    assert all(node.attempts == 0 for node in nodes.values())


def test_a_locked_skill_is_never_suggested() -> None:
    """"Start here" pointing at a topic the student cannot open is an instruction they
    cannot follow -- worse than naming nothing at all."""
    from app.mastery.skill_graph import weakest_startable
    from app.models.schemas import SkillNode

    def node(skill, mastery, prereqs=()):
        return SkillNode(
            skill=skill, mastery=mastery, confidence=0.3, attempts=1,
            prerequisites=list(prereqs), misconceptions=[],
        )

    # recursion is the weakest overall, but it is blocked by functions.
    nodes = {
        "functions": node("functions", 0.40),
        "recursion": node("recursion", 0.10, ["functions"]),
    }
    assert weakest_startable(nodes, 0.6) == "functions", (
        "recursion is weaker but locked; the suggestion must be the one they can start"
    )


def test_nothing_is_suggested_when_everything_is_mastered() -> None:
    from app.mastery.skill_graph import weakest_startable
    from app.models.schemas import SkillNode

    nodes = {
        "variables": SkillNode(
            skill="variables", mastery=0.9, confidence=0.8, attempts=5,
            prerequisites=[], misconceptions=[],
        )
    }
    assert weakest_startable(nodes, 0.6) is None
