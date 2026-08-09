"""Build a frozen sqlite memory fixture from an event-graph YAML (PC-2).

The rows are AUTHORED and frozen in the YAML, never model-produced. A
LoCoMo-style event graph is a flat, ordered list of conversation events
(evidence rows the probe will later ask about, plus distractor rows that push
that evidence out of today's recency window). The builder replays those events
in order into a *fresh* :class:`~parcel_robot.memory.ConversationMemory`, so
each cross-session probe measures the memory subsystem itself, not context
carried over in a live turn buffer.

Determinism: rows are inserted in authored order; ``ConversationMemory.recent``
orders by row id, so ``recent(limit)`` is a pure function of the YAML and the
limit. No timestamps are read back into the fixture.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.memory import ConversationMemory

VALID_ROLES = frozenset({"user", "assistant", "tool"})
VALID_KINDS = frozenset({"evidence", "distractor"})


class MemoryGraphError(ValueError):
    """The event-graph YAML is malformed."""


@dataclass(frozen=True)
class MemoryEvent:
    """One authored conversation event."""

    event_id: str
    session: str
    role: str
    content: str
    kind: str


@dataclass(frozen=True)
class MemoryGraph:
    """A parsed, validated event graph plus its recall probe metadata."""

    graph_id: str
    recency_limit: int
    events: tuple[MemoryEvent, ...]
    probe_query: str
    required_any_groups: tuple[tuple[str, ...], ...]
    confabulation_guards: tuple[str, ...]

    @property
    def evidence(self) -> tuple[MemoryEvent, ...]:
        return tuple(event for event in self.events if event.kind == "evidence")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryGraphError(message)


def load_graph(path: str | Path) -> MemoryGraph:
    """Parse and validate one event-graph YAML."""

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    _require(isinstance(raw, Mapping), "event graph must be a mapping")
    assert isinstance(raw, Mapping)

    graph_id = raw.get("graph_id")
    _require(isinstance(graph_id, str) and bool(graph_id), "graph_id must be a non-empty string")

    recency_limit = raw.get("recency_limit", 8)
    _require(
        isinstance(recency_limit, int) and not isinstance(recency_limit, bool) and recency_limit > 0,
        "recency_limit must be a positive integer",
    )

    raw_events = raw.get("events")
    _require(isinstance(raw_events, list) and bool(raw_events), "events must be a non-empty list")
    assert isinstance(raw_events, list)
    events: list[MemoryEvent] = []
    seen: set[str] = set()
    for item in raw_events:
        _require(isinstance(item, Mapping), "each event must be a mapping")
        assert isinstance(item, Mapping)
        event_id = item.get("id")
        _require(isinstance(event_id, str) and bool(event_id), "event id must be a non-empty string")
        _require(event_id not in seen, f"duplicate event id: {event_id}")
        seen.add(str(event_id))
        role = item.get("role")
        _require(role in VALID_ROLES, f"event {event_id} role must be one of {sorted(VALID_ROLES)}")
        content = item.get("content")
        _require(
            isinstance(content, str) and bool(content),
            f"event {event_id} content must be a non-empty string",
        )
        kind = item.get("kind", "distractor")
        _require(kind in VALID_KINDS, f"event {event_id} kind must be one of {sorted(VALID_KINDS)}")
        events.append(
            MemoryEvent(
                event_id=str(event_id),
                session=str(item.get("session", "")),
                role=str(role),
                content=str(content),
                kind=str(kind),
            )
        )

    probe = raw.get("probe")
    _require(isinstance(probe, Mapping), "graph must carry a probe mapping")
    assert isinstance(probe, Mapping)
    query = probe.get("query")
    _require(isinstance(query, str) and bool(query), "probe.query must be a non-empty string")

    groups_raw = probe.get("required_any_groups", [])
    _require(isinstance(groups_raw, list), "probe.required_any_groups must be a list")
    assert isinstance(groups_raw, list)
    groups: list[tuple[str, ...]] = []
    for group in groups_raw:
        _require(isinstance(group, list) and bool(group), "each required group must be a non-empty list")
        assert isinstance(group, list)
        groups.append(tuple(str(term) for term in group))

    guards_raw = probe.get("confabulation_guards", [])
    _require(isinstance(guards_raw, list), "probe.confabulation_guards must be a list")
    assert isinstance(guards_raw, list)

    _require(
        any(event.kind == "evidence" for event in events),
        "graph must contain at least one evidence event",
    )

    return MemoryGraph(
        graph_id=str(graph_id),
        recency_limit=int(recency_limit),
        events=tuple(events),
        probe_query=str(query),
        required_any_groups=tuple(groups),
        confabulation_guards=tuple(str(guard) for guard in guards_raw),
    )


def build_memory(graph: MemoryGraph, path: str | Path = ":memory:") -> ConversationMemory:
    """Replay an event graph into a fresh ConversationMemory (sqlite).

    Passing ``":memory:"`` (default) yields a throwaway in-process store, which
    is exactly the "fresh process / empty live history" the cross-session
    probes require.
    """

    memory = ConversationMemory(path)
    for event in graph.events:
        memory.add(event.role, event.content)
    return memory


def evidence_within_window(graph: MemoryGraph) -> bool:
    """True iff every evidence row is inside the recency window.

    The cross-session probe is designed so this is False: the authored
    distractors push the evidence beyond ``recent(recency_limit)``, which is the
    concrete, honest shape of today's recency-window limitation.
    """

    window = build_memory(graph).recent(graph.recency_limit)
    window_contents = {row["content"] for row in window}
    return all(event.content in window_contents for event in graph.evidence)


def frozen_rows(graph: MemoryGraph) -> list[dict[str, Any]]:
    """The authored rows, for provenance/inspection in a result artifact."""

    return [
        {
            "event_id": event.event_id,
            "session": event.session,
            "role": event.role,
            "kind": event.kind,
            "content": event.content,
        }
        for event in graph.events
    ]


__all__ = [
    "MemoryEvent",
    "MemoryGraph",
    "MemoryGraphError",
    "build_memory",
    "evidence_within_window",
    "frozen_rows",
    "load_graph",
]
