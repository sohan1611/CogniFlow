"""Structured event stream — how agentic behaviour becomes visible.

Invariant: events record DECISIONS and EVIDENCE, never private model reasoning. We log
the structured fields our schemas define (selected action, reason, evidence, confidence)
and nothing else.

Judges cannot read state transitions out of a database mid-demo. They can read a live
event log, so this is the layer that makes the architecture observable rather than
merely present. The CLI renders these now; a UI can consume the same JSONL later.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """What kind of thing happened."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    DIAGNOSTIC = "diagnostic"
    PLAN = "plan"
    RETRIEVAL = "retrieval"
    GENERATED = "generated"
    AWAITING_STUDENT = "awaiting_student"
    SUBMISSION = "submission"
    EXECUTION = "execution"
    GRADE = "grade"
    MISCONCEPTION = "misconception"
    MASTERY = "mastery"
    ADAPTATION = "adaptation"
    GUARD_OVERRIDE = "guard_override"
    PREREQ_REDIRECT = "prereq_redirect"
    PREREQ_RETURN = "prereq_return"
    RECOVERY = "recovery"
    FAULT = "fault"


@dataclass
class CogniEvent:
    """One observable step."""

    node: str
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    decision_reason: str | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: float | None = None
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    def render(self) -> str:
        """Human-readable one-liner for the CLI demo."""
        head = f"[{self.node}] {self.event_type.value}"
        bits: list[str] = []
        for key, value in self.payload.items():
            if value is None or value == [] or value == {} or value == "":
                continue
            if isinstance(value, float):
                value = f"{value:.3f}"
            bits.append(f"{key}={value}")
        line = head + ("  " + " ".join(bits) if bits else "")
        if self.decision_reason:
            line += f"\n    reason: {self.decision_reason}"
        if self.evidence:
            line += f"\n    evidence: {'; '.join(str(e) for e in self.evidence[:4])}"
        if self.confidence is not None:
            line += f"\n    confidence: {self.confidence:.2f}"
        return line


class EventLog:
    """Collects events in memory, optionally mirroring them to a JSONL file.

    Thread-safe because the graph and a UI may read and write concurrently. Never
    raises on a write failure -- losing an observability line must not end a session.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        echo: bool = False,
        sink: Callable[[CogniEvent], None] | None = None,
    ) -> None:
        self.path = Path(path) if path else None
        self.echo = echo
        self.sink = sink
        self.events: list[CogniEvent] = []
        self._lock = threading.Lock()

    def emit(
        self,
        node: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        reason: str | None = None,
        evidence: list[str] | None = None,
        confidence: float | None = None,
    ) -> CogniEvent:
        event = CogniEvent(
            node=node,
            event_type=event_type,
            payload=payload or {},
            decision_reason=reason,
            evidence=evidence or [],
            confidence=confidence,
        )
        with self._lock:
            self.events.append(event)

        if self.echo:
            print(event.render(), flush=True)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(event.to_json() + "\n")
            except OSError as exc:
                logger.warning("event log write failed: %s", exc)
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception as exc:  # noqa: BLE001 - a bad sink must not kill a session
                logger.warning("event sink raised: %s", exc)
        return event

    def of_type(self, *types: EventType) -> list[CogniEvent]:
        wanted = set(types)
        return [e for e in self.events if e.event_type in wanted]

    def actions(self) -> list[str]:
        """The adaptation actions taken, in order -- the demo's storyline."""
        return [
            str(e.payload.get("action"))
            for e in self.of_type(EventType.ADAPTATION)
            if e.payload.get("action")
        ]

    def skills_visited(self) -> list[str]:
        """Ordered target skills, so the redirect path is readable at a glance."""
        out: list[str] = []
        for e in self.of_type(EventType.PLAN):
            skill = e.payload.get("target_skill")
            if skill and (not out or out[-1] != skill):
                out.append(str(skill))
        return out

    def render_all(self) -> str:
        return "\n".join(e.render() for e in self.events)

    def __len__(self) -> int:
        return len(self.events)
