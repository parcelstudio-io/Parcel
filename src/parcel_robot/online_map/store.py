"""The map's own store, and the refusals that keep it out of the owner's.

Card C-2 work item 2: the map persists *in its own store, NEVER the
conversation store*, with PARCEL_MEMORY_PATH-class isolation **from birth**.

The phrase "from birth" is the load-bearing one. R27 exists because
``memory.path`` was a relative path resolved against the process CWD, so four
consecutive card-chains wrote 256 synthetic rows into the owner's real
conversation database while reporting isolation in good faith. Nothing told
them otherwise. The lesson R27 drew was not "remember to isolate" — it was that
a process which has not declared where it may write **finds that out as an
exception rather than as a row**.

So this module opens with the same three rules, and adds a fourth that is
specific to being a second store:

1. :data:`~.entries.ENV_MAP_PATH` (``PARCEL_ONLINE_MAP_PATH``) must be
   ``:memory:`` or **absolute**. A relative override re-imports the exact CWD
   bug R27 closed, so it is refused.
2. No override, no store. The default is a **refusal**, not a silent temp file
   — a temp-file fallback would make a run look like it had memory and teach
   the executor nothing about which file they wrote.
3. The refusal message names the ways out, because a guard nobody can satisfy
   gets deleted.
4. **The owner's conversation store is refused by identity, not by convention.**
   The candidate is compared against
   :func:`parcel_robot.memory_path.owner_store_paths` — the same authority the
   conversation side uses — so the two cannot drift apart. Seed 4 pins it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Self

from parcel_robot.memory_path import OWNER_STORE_NAME, owner_store_paths

from .entries import ENV_MAP_PATH, MAP_SCHEMA, MAX_ENTRIES, MapEntry


class MapStoreRefused(RuntimeError):
    """This process may not open that file as the dog's map."""


_IN_MEMORY = ":memory:"


def _ways_out() -> str:
    return (
        f"Set {ENV_MAP_PATH} to an ABSOLUTE path for a real store, or to "
        f"'{_IN_MEMORY}' for an ephemeral one. The map deliberately has no "
        "default location: a default is how a store ends up somewhere nobody "
        "audited."
    )


def resolve_map_store_path(
    explicit: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Where may this process keep its map? Answers, or raises.

    Returns either ``":memory:"`` or an absolute filesystem path as a string.
    Never returns a relative path, and never returns the owner's conversation
    store.
    """

    environ = os.environ if env is None else env
    source = "explicit argument"
    candidate: str | None
    if explicit is not None:
        candidate = str(explicit)
    else:
        candidate = environ.get(ENV_MAP_PATH)
        source = ENV_MAP_PATH

    if candidate is None or not str(candidate).strip():
        raise MapStoreRefused(
            "the online map has no store to open: nothing declared where it "
            f"may write. {_ways_out()}"
        )

    candidate = str(candidate).strip()
    if candidate == _IN_MEMORY:
        return _IN_MEMORY

    path = Path(candidate)
    if not path.is_absolute():
        raise MapStoreRefused(
            f"{source} gave a RELATIVE map path {candidate!r}. A relative path "
            "is a question ('relative to where?') whose answer changes with the "
            "process CWD — that is the exact defect card R27 exists to close, "
            f"and it is refused here for the same reason. {_ways_out()}"
        )

    resolved = path.expanduser().resolve()

    # Rule 4: identity, not convention.
    if resolved.name == OWNER_STORE_NAME:
        raise MapStoreRefused(
            f"refusing to open {resolved} as the dog's map: that filename is "
            "the owner's conversation store. The map is object-centric places "
            "the robot saw; the conversation store is things the owner said. "
            "One file holding both is how 'find the nearest lamppost' became "
            "something the owner had apparently told the robot (R18/R27)."
        )
    for owner in owner_store_paths():
        try:
            same = resolved == owner.expanduser().resolve()
        except OSError:  # pragma: no cover - unresolvable owner path
            same = False
        if same:
            raise MapStoreRefused(
                f"refusing to open {resolved} as the dog's map: it resolves to "
                "the owner's conversation store."
            )
    return str(resolved)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS map_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS map_entries (
    entry_id   TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    status     TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS map_entries_label ON map_entries(label);
"""


class OnlineMapStore:
    """A bounded, typed, append-and-update SQLite store for map entries.

    There is deliberately **no delete method**. Decay marks; quarantine marks;
    nothing removes. ``save`` is an upsert and ``load_all`` returns everything,
    including decayed and quarantined entries, because an auditor asking "what
    did the robot stop believing, and when?" must be able to get an answer.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._path = resolve_map_store_path(path, env=env)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
        self._check_schema()

    @property
    def path(self) -> str:
        return self._path

    @property
    def in_memory(self) -> bool:
        return self._path == _IN_MEMORY

    def _check_schema(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM map_meta WHERE key = 'schema'"
        ).fetchone()
        if row is None:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO map_meta(key, value) VALUES ('schema', ?)",
                    (MAP_SCHEMA,),
                )
            return
        if row[0] != MAP_SCHEMA:
            raise MapStoreRefused(
                f"store at {self._path} was written by schema {row[0]!r}, this "
                f"build speaks {MAP_SCHEMA!r}. Refusing to reinterpret rows "
                "whose meaning may have changed."
            )

    # -- meta --------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO map_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM map_meta WHERE key = ?", (str(key),)
        ).fetchone()
        return None if row is None else str(row[0])

    # -- entries -----------------------------------------------------------

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM map_entries").fetchone()
        return int(row[0])

    def save(self, entry: MapEntry) -> None:
        if not isinstance(entry, MapEntry):
            raise TypeError("only MapEntry rows may be stored")
        existing = self._conn.execute(
            "SELECT 1 FROM map_entries WHERE entry_id = ?", (entry.entry_id,)
        ).fetchone()
        if existing is None and self.count() >= MAX_ENTRIES:
            raise MapStoreRefused(
                f"map store is full at {MAX_ENTRIES} entries; refusing to grow "
                "without bound. A map that can grow forever is a memory leak "
                "with a story attached."
            )
        payload = json.dumps(entry.as_dict(), sort_keys=True, separators=(",", ":"))
        with self._conn:
            self._conn.execute(
                "INSERT INTO map_entries(entry_id, label, status, payload) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(entry_id) DO UPDATE SET "
                "label = excluded.label, status = excluded.status, "
                "payload = excluded.payload",
                (entry.entry_id, entry.label, entry.status, payload),
            )

    def save_all(self, entries: Iterable[MapEntry]) -> int:
        written = 0
        for entry in entries:
            self.save(entry)
            written += 1
        return written

    def load_all(self) -> tuple[MapEntry, ...]:
        rows = self._conn.execute(
            "SELECT payload FROM map_entries ORDER BY entry_id"
        ).fetchall()
        out: list[MapEntry] = []
        for (payload,) in rows:
            data: Any = json.loads(payload)
            if not isinstance(data, Mapping):
                raise MapStoreRefused("stored map row is not a mapping")
            out.append(MapEntry.from_mapping(data))
        return tuple(out)

    def close(self) -> None:
        with closing(self._conn):
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = [
    "MapStoreRefused",
    "OnlineMapStore",
    "resolve_map_store_path",
]
