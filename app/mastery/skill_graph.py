"""Skill graph wrapper for deterministic prerequisite traversal.

Invariant: edge (A -> B) means "A is a prerequisite of B"; prerequisites of X are
list(graph.predecessors(X)).
"""

from pathlib import Path
from typing import Any, Self

import networkx as nx
import yaml

from app.models.errors import SkillGraphError
from app.models.schemas import SkillNode


class SkillGraph:
    """Immutable wrapper around a directed acyclic prerequisite graph."""

    def __init__(self, nodes: dict[str, SkillNode]) -> None:
        """Build a DAG from skill nodes and their prerequisite lists."""

        self._nodes = dict(nodes)
        graph = nx.DiGraph()
        graph.add_nodes_from(self._nodes)
        for skill, node in self._nodes.items():
            if node.skill != skill:
                raise SkillGraphError(f"node key {skill!r} does not match node skill {node.skill!r}")
            for prerequisite in node.prerequisites:
                if prerequisite not in self._nodes:
                    raise SkillGraphError(f"unknown prerequisite {prerequisite!r} for skill {skill!r}")
                graph.add_edge(prerequisite, skill)
        if not nx.is_directed_acyclic_graph(graph):
            raise SkillGraphError("skill graph must be acyclic")
        self._graph = graph

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        """Load a SkillGraph from a YAML mapping of skill names to node fields."""

        with Path(path).open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        skills = raw.get("skills", raw) if isinstance(raw, dict) else raw
        if not isinstance(skills, dict):
            raise SkillGraphError("skills YAML must contain a mapping")
        nodes: dict[str, SkillNode] = {}
        for skill, payload in skills.items():
            if not isinstance(skill, str) or not isinstance(payload, dict):
                raise SkillGraphError("each skill YAML entry must be a mapping")
            data = dict(payload)
            data.setdefault("skill", skill)
            nodes[skill] = SkillNode(**data)
        return cls(nodes)

    @property
    def nodes(self) -> dict[str, SkillNode]:
        """Expose a copy of the skill-node mapping."""

        return dict(self._nodes)

    def prerequisites(self, skill: str) -> list[str]:
        """Return direct prerequisites for a skill in deterministic order."""

        self._require_skill(skill)
        return sorted(self._graph.predecessors(skill))

    def mastery(self, skill: str) -> float:
        """Return current mastery for a known skill."""

        self._require_skill(skill)
        return self._nodes[skill].mastery

    def is_mastered(self, skill: str, threshold: float = 0.6) -> bool:
        """Return whether a skill meets the mastery threshold."""

        self._require_skill(skill)
        return self._nodes[skill].mastery >= threshold

    def unmastered_prerequisites(self, skill: str, threshold: float = 0.6) -> list[str]:
        """Return direct prerequisites below the mastery threshold."""

        return [
            prerequisite
            for prerequisite in self.prerequisites(skill)
            if not self.is_mastered(prerequisite, threshold)
        ]

    def weakest_prerequisite(self, skill: str, threshold: float = 0.6) -> str | None:
        """Return the weakest unmastered direct prerequisite with alphabetical tie-break."""

        unmastered = self.unmastered_prerequisites(skill, threshold)
        if not unmastered:
            return None
        return min(
            unmastered,
            key=lambda item: (self._nodes[item].mastery * self._nodes[item].confidence, item),
        )

    def with_updated(self, node: SkillNode) -> Self:
        """Return a new SkillGraph with one node replaced."""

        self._require_skill(node.skill)
        nodes = dict(self._nodes)
        nodes[node.skill] = node
        return type(self)(nodes)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Return a JSON-serializable graph representation."""

        return {
            skill: self._nodes[skill].model_dump(mode="json")
            for skill in sorted(self._nodes)
        }

    @classmethod
    def from_dict(cls, d: dict[str, dict[str, Any]]) -> Self:
        """Rebuild a SkillGraph from to_dict output."""

        nodes: dict[str, SkillNode] = {}
        for skill, payload in d.items():
            data = dict(payload)
            data.setdefault("skill", skill)
            nodes[skill] = SkillNode(**data)
        return cls(nodes)

    def _require_skill(self, skill: str) -> None:
        if skill not in self._nodes:
            raise SkillGraphError(f"unknown skill {skill!r}")
