"""Tests for deterministic skill graph behavior.

Invariant: prerequisite graphs are acyclic and address only known skills.
"""

from pathlib import Path

import pytest

from app.mastery.skill_graph import SkillGraph
from app.models.errors import SkillGraphError
from app.models.schemas import SkillNode


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
