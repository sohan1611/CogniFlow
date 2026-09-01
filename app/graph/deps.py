"""Dependency container for graph nodes.

Invariant: nodes never construct their own collaborators. Everything a node touches --
the durable store, the sandbox, retrieval, the LLM client, the event log -- arrives
through this object.

That is what makes the graph testable offline: a test swaps in a stub LLM, an in-memory
store, and a fault-injecting sandbox without patching a single import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.llm.provider import Role, StructuredCaller, available_chain, build_caller
from app.llm.structured import LLMClient
from app.mastery.bkt import BKTParams
from app.rag.retriever import Retriever
from app.services.events import EventLog
from app.services.student_store import StudentStore
from app.tools.sandbox.base import Sandbox
from app.tools.sandbox.subprocess_sandbox import SubprocessSandbox


@dataclass
class GraphDeps:
    """Everything the graph needs, supplied from outside."""

    store: StudentStore
    events: EventLog
    sandbox: Sandbox = field(default_factory=SubprocessSandbox)
    retriever: Retriever | None = None
    bkt: BKTParams = field(default_factory=BKTParams)
    llm_clients: dict[Role, LLMClient] = field(default_factory=dict)
    skills_config: Path = Path("app/config/skills.yaml")
    max_loops: int = 25

    def llm(self, role: Role) -> LLMClient:
        """The client for a role, built lazily from whatever credentials exist.

        With no credentials the chain is empty, which is fine: LLMClient returns an
        LLM_FAILURE outcome and callers fall back to deterministic templates. The graph
        therefore runs end to end offline, which is exactly what lets us test
        interrupt/resume without spending anything.
        """
        if role not in self.llm_clients:
            callers: list[StructuredCaller] = [
                build_caller(spec) for spec in available_chain(role)
            ]
            self.llm_clients[role] = LLMClient(role, callers)
        return self.llm_clients[role]

    @classmethod
    def offline(
        cls,
        store: StudentStore,
        events: EventLog,
        *,
        caller: StructuredCaller | None = None,
        **kwargs: object,
    ) -> "GraphDeps":
        """Construct deps wired to a single stub caller (tests and demos)."""
        deps = cls(store=store, events=events, **kwargs)  # type: ignore[arg-type]
        if caller is not None:
            for role in Role:
                deps.llm_clients[role] = LLMClient(role, [caller], sleep=lambda _s: None)
        else:
            for role in Role:
                deps.llm_clients[role] = LLMClient(role, [], sleep=lambda _s: None)
        return deps
