"""The episodic layer: dated events with outcomes, beside the fact profile.

RESEARCH H5 (``research/20260823/governed-continual-memory/DESIGN.md``).

WHAT WAS MISSING
----------------
The tree has two kinds of memory and neither of them is an *episode*.
``messages`` is a turn log — every sentence, no boundaries, no outcome.
``owner_facts`` is a profile — durable statements with no time in them ("they
live in Brooklyn" is true today and carries no record of the afternoon they
said so). Between those two sits the thing a dog actually remembers: *we went
to the park on Tuesday and could not find the fountain.* A dated event, with a
kind, a one-line summary, an outcome, and pointers back to the turns, facts and
map entries it came from.

This module is that row and its append-only log, and nothing else. It does not
schedule anything (:mod:`parcel_robot.memory.scheduler` does), it does not
summarize (the caller passes the summary in), and it holds no opinion about
consent — an episode summarises what *happened*, which is the robot's own
record of its own day, not a claim about the owner.

WHY ITS OWN FILE AND NOT A TABLE IN ``messages``
------------------------------------------------
Card R27's owner-store isolation guard lives on
:class:`~parcel_robot.memory.conversation.ConversationMemory.__init__`, and P2-A
put ``owner_facts`` in the same file precisely so it inherits that guard. An
episode log is different in one way that matters: it is written by background
passes (session close, mission terminal events) rather than by a turn, so the
failure mode is a background writer opening the owner's store. Hence a
*separate* file with an explicit refusal of the owner's paths at construction —
the isolation is re-established here rather than inherited, because the thing
that would breach it is not a turn.

APPEND ONLY, DELIBERATELY
-------------------------
``owner_facts`` upserts by key because a profile is not an event log. This *is*
an event log: two visits to the park are two episodes, and the second does not
overwrite the first. Nothing here updates or deletes; the only writer is
:meth:`EpisodeLog.append`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .path import owner_store_paths

#: What kind of thing happened. Closed set: a free-form kind is a kind nobody
#: can query for, and the three below are the three the runtime can actually
#: detect a boundary for (a session closing, a mission reaching a terminal
#: state, a place being seen).
EPISODE_CONVERSATION = "conversation"
EPISODE_MISSION = "mission"
EPISODE_SIGHTING = "sighting"
EPISODE_KINDS: frozenset[str] = frozenset(
    {EPISODE_CONVERSATION, EPISODE_MISSION, EPISODE_SIGHTING}
)

#: The table. Named for the row, not for the module, so a reader of the file
#: sees what it holds.
EPISODES_TABLE = "episodes"

EPISODES_DDL = f"""
CREATE TABLE IF NOT EXISTS {EPISODES_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    started_wall_s REAL NOT NULL,
    ended_wall_s REAL NOT NULL,
    summary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    turn_ids TEXT NOT NULL DEFAULT '',
    fact_keys TEXT NOT NULL DEFAULT '',
    map_entry_ids TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

#: A summary longer than this is a transcript, and the turn log already keeps
#: those. Same reasoning as ``owner_model.policy.MAX_FACT_CHARS``.
MAX_SUMMARY_CHARS = 400


class EpisodeStoreRefused(RuntimeError):
    """This path is the owner's conversation store; episodes never go there.

    ``RuntimeError`` for the reason
    :class:`~parcel_robot.memory.path.MemoryPathRefused` is one: a background
    writer's caller catches ``ValueError`` broadly to keep a turn alive, and a
    refusal that a never-break-a-turn guard can swallow is not a refusal.
    """


def _text(value: object, name: str, *, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if not clean:
        raise ValueError(f"episode {name} must be a non-empty string")
    return clean[:limit]


def _ids(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        clean = " ".join(str(value).split())
        if clean and clean not in out:
            out.append(clean)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Episode:
    """One dated thing that happened, with its outcome and its references.

    Frozen because an episode is a record of the past: an episode that can be
    edited after the fact is a diary the robot can rewrite, and the whole value
    of the layer is that yesterday stays what yesterday was.

    ``turn_ids`` / ``fact_keys`` / ``map_entry_ids`` are the references the
    design asks for, kept as plain ids rather than joins so this file never has
    to be opened in the same transaction as the store it points at.
    """

    episode_id: str
    kind: str
    started_wall_s: float
    ended_wall_s: float
    summary: str
    outcome: str
    session_id: str = ""
    turn_ids: tuple[int, ...] = ()
    fact_keys: tuple[str, ...] = ()
    map_entry_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _text(self.episode_id, "episode_id", limit=96))
        kind = str(self.kind).strip().lower()
        if kind not in EPISODE_KINDS:
            raise ValueError(
                f"unsupported episode kind: {self.kind!r} "
                f"(expected one of {sorted(EPISODE_KINDS)})"
            )
        object.__setattr__(self, "kind", kind)
        started = float(self.started_wall_s)
        ended = float(self.ended_wall_s)
        if ended < started:
            raise ValueError("an episode cannot end before it started")
        object.__setattr__(self, "started_wall_s", started)
        object.__setattr__(self, "ended_wall_s", ended)
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", limit=MAX_SUMMARY_CHARS)
        )
        object.__setattr__(self, "outcome", _text(self.outcome, "outcome", limit=64))
        object.__setattr__(
            self, "session_id", " ".join(str(self.session_id or "").split())[:96]
        )
        object.__setattr__(self, "turn_ids", tuple(int(i) for i in self.turn_ids))
        object.__setattr__(self, "fact_keys", _ids(self.fact_keys))
        object.__setattr__(self, "map_entry_ids", _ids(self.map_entry_ids))

    @property
    def duration_s(self) -> float:
        return self.ended_wall_s - self.started_wall_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "kind": self.kind,
            "started_wall_s": self.started_wall_s,
            "ended_wall_s": self.ended_wall_s,
            "summary": self.summary,
            "outcome": self.outcome,
            "session_id": self.session_id,
            "turn_ids": list(self.turn_ids),
            "fact_keys": list(self.fact_keys),
            "map_entry_ids": list(self.map_entry_ids),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Episode:
        if not isinstance(data, Mapping):
            raise TypeError("episode must be a mapping")
        return cls(
            episode_id=str(data["episode_id"]),
            kind=str(data["kind"]),
            started_wall_s=float(data["started_wall_s"]),
            ended_wall_s=float(data["ended_wall_s"]),
            summary=str(data["summary"]),
            outcome=str(data["outcome"]),
            session_id=str(data.get("session_id", "")),
            turn_ids=tuple(int(i) for i in data.get("turn_ids", ())),
            fact_keys=tuple(str(k) for k in data.get("fact_keys", ())),
            map_entry_ids=tuple(str(k) for k in data.get("map_entry_ids", ())),
        )


def _join(values: Iterable[Any]) -> str:
    return ",".join(str(v) for v in values)


def _split_ints(raw: object) -> tuple[int, ...]:
    text = str(raw or "").strip()
    if not text:
        return ()
    return tuple(int(part) for part in text.split(",") if part.strip())


def _split_text(raw: object) -> tuple[str, ...]:
    text = str(raw or "").strip()
    if not text:
        return ()
    return tuple(part for part in text.split(",") if part)


@dataclass
class EpisodeLog:
    """Append-only sqlite log of :class:`Episode` rows.

    ``path=":memory:"`` gives a throwaway in-process log, which is what a
    harness or a test wants; any other path is a file this class creates. The
    owner's conversation store is refused by path before the connection is
    opened, so the refusal cannot be reached by a writer that already has a
    handle.
    """

    path: str | Path = ":memory:"
    connection: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        target = str(self.path)
        if target != ":memory:":
            resolved = Path(target).expanduser().resolve()
            for owned in owner_store_paths():
                if resolved == owned:
                    raise EpisodeStoreRefused(
                        f"{resolved} is the owner's conversation store. The episodic "
                        "layer is a background writer and never opens it; point "
                        "EpisodeLog at its own file."
                    )
            resolved.parent.mkdir(parents=True, exist_ok=True)
            target = str(resolved)
            self.path = target
        self.connection = sqlite3.connect(target, check_same_thread=False)
        self.connection.execute(EPISODES_DDL)
        self.connection.commit()

    def append(self, episode: Episode) -> int:
        """Write one episode. Returns its row id; re-appending an id is refused.

        ``episode_id`` is UNIQUE so a retried session-close cannot silently
        double-write the same afternoon.
        """

        if not isinstance(episode, Episode):
            raise TypeError("EpisodeLog.append takes an Episode")
        cursor = self.connection.execute(
            f"INSERT INTO {EPISODES_TABLE} (episode_id, kind, started_wall_s, "
            "ended_wall_s, summary, outcome, session_id, turn_ids, fact_keys, "
            "map_entry_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                episode.episode_id,
                episode.kind,
                episode.started_wall_s,
                episode.ended_wall_s,
                episode.summary,
                episode.outcome,
                episode.session_id,
                _join(episode.turn_ids),
                _join(episode.fact_keys),
                _join(episode.map_entry_ids),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def recent(self, limit: int = 20, *, kind: str | None = None) -> tuple[Episode, ...]:
        """The newest episodes first, optionally filtered by kind."""

        query = (
            "SELECT episode_id, kind, started_wall_s, ended_wall_s, summary, "
            f"outcome, session_id, turn_ids, fact_keys, map_entry_ids FROM {EPISODES_TABLE}"
        )
        params: list[object] = []
        if kind is not None:
            query += " WHERE kind = ?"
            params.append(str(kind))
        query += " ORDER BY ended_wall_s DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = self.connection.execute(query, tuple(params)).fetchall()
        return tuple(_row_to_episode(row) for row in rows)

    def since(self, wall_s: float, *, limit: int = 100) -> tuple[Episode, ...]:
        """Episodes that ended at or after ``wall_s``, oldest first."""

        rows = self.connection.execute(
            "SELECT episode_id, kind, started_wall_s, ended_wall_s, summary, "
            f"outcome, session_id, turn_ids, fact_keys, map_entry_ids FROM {EPISODES_TABLE} "
            "WHERE ended_wall_s >= ? ORDER BY ended_wall_s ASC, id ASC LIMIT ?",
            (float(wall_s), int(limit)),
        ).fetchall()
        return tuple(_row_to_episode(row) for row in rows)

    def count(self) -> int:
        row = self.connection.execute(f"SELECT COUNT(*) FROM {EPISODES_TABLE}").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self.connection.close()


def _row_to_episode(row: tuple[Any, ...]) -> Episode:
    return Episode(
        episode_id=str(row[0]),
        kind=str(row[1]),
        started_wall_s=float(row[2]),
        ended_wall_s=float(row[3]),
        summary=str(row[4]),
        outcome=str(row[5]),
        session_id=str(row[6]),
        turn_ids=_split_ints(row[7]),
        fact_keys=_split_text(row[8]),
        map_entry_ids=_split_text(row[9]),
    )


__all__ = [
    "EPISODES_DDL",
    "EPISODES_TABLE",
    "EPISODE_CONVERSATION",
    "EPISODE_KINDS",
    "EPISODE_MISSION",
    "EPISODE_SIGHTING",
    "MAX_SUMMARY_CHARS",
    "Episode",
    "EpisodeLog",
    "EpisodeStoreRefused",
]
