"""Raw conversation store — full-fidelity turns, timestamp-indexed, swappable.

The owner's directive, verbatim: *"Build an internal database that can hold raw
previous conversations indexed by timestamp. Storage design is subject to
change."*

**"Subject to change" is the load-bearing half.** So what ships here is a *seam
plus one implementation*, not a schema commitment:

- :class:`ConversationStore` is a ``Protocol`` — six methods, no inheritance
  required. The conformance suite in ``tests/test_conversation_store.py`` is
  written against the Protocol and is run against **two** implementations (the
  SQLite one below and a toy in-memory one that lives only in the test file).
  A future Postgres/vector/append-only-log backend is "done" when it passes the
  same parametrized suite; nothing else in the codebase has to move.
- :class:`SqliteConversationStore` is today's backend. It owns a **new** table,
  ``conversation_turns``. The pre-existing ``messages`` table that
  :class:`~parcel_robot.memory.ConversationMemory` writes is **not touched, not
  read, and not migrated in place** — the two stores coexist, which is what
  makes this card reversible: delete the file and the robot still works.

**"Raw" is the other load-bearing word.** A :class:`TurnRecord` is the turn as
spoken or heard, plus its provenance — never a distilled summary. Summarizing
is :mod:`parcel_robot.tiered_memory`'s job and a different consumer's read.

Design decisions that are contracts, not preferences
----------------------------------------------------

**Time.** ``ts_utc`` is a UTC epoch float, stamped at *write* time from an
**injected** clock (:func:`utc_now` by default). Nothing here formats a
timestamp for a human; :meth:`TurnRecord.iso_utc` exists so a *reader* can
render one. A store that read the local wall clock would produce a database
whose ordering silently depends on the machine's timezone, so the clock is a
constructor argument and the tests pin it to a fixed instant.

**Ordering.** A fixed injected clock makes consecutive turns share a
``ts_utc`` exactly. Every read therefore orders by ``(ts_utc, seq)`` where
``seq`` is a monotonically increasing per-store append counter. Without the
tiebreak, "the last three turns" would be non-deterministic under a frozen
clock — which is precisely the condition every test runs in.

**Ranges are half-open: inclusive start, exclusive end** (``start <= ts <
end``). The reason is composition: consecutive windows
``[t0, t1)``, ``[t1, t2)`` partition the timeline exactly once, with no turn
dropped and no turn counted twice. A closed-closed range double-counts any turn
landing on a boundary, and under a frozen clock that is *most* of them. Either
bound may be ``None`` for an open end.

**Closed vocabularies.** ``source`` is one of :data:`SOURCES`, ``speaker`` one
of :data:`SPEAKERS`. Unknown values are refused at construction, not coerced —
an unrecognized speaker in a conversation ledger is a bug in the writer, and
silently storing it means discovering the bug later from bad data.

**Meta round-trips byte-exact.** ``meta`` is stored as canonical JSON
(``sort_keys``, no spaces, no ASCII escaping). A mapping that does *not*
survive the round trip — a tuple value, an ``int`` key, ``NaN`` — is refused at
construction rather than silently mutated into something else on the way back
out.

Honesty boundary: nothing in the shipped runtime *reads* this store yet. The
Realtime lane's history injection still reads
``ConversationMemory.realtime_turns``. This card provides the store, the
dual-write seam (:func:`mirror_realtime_turn`, wired into
``ConversationMemory.write_realtime_turn``'s optional ``store=`` argument) and
the backfill (:func:`import_realtime_turns`); re-pointing consumers is a
follow-up card.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .memory_path import resolve_memory_path

logger = logging.getLogger(__name__)

#: Where a turn came from. ``realtime`` = the hosted Realtime lane;
#: ``local`` = the on-device voice/panel path; ``corpus`` = replayed eval
#: fixtures. Closed on purpose — see the module docstring.
SOURCES: frozenset[str] = frozenset({"realtime", "local", "corpus"})

#: Who produced the turn. Mirrors ``memory._SPEAKER_ROLES``' keys deliberately:
#: the two ledgers must agree about who is speaking or a future migration
#: between them is a guessing game.
SPEAKERS: frozenset[str] = frozenset({"owner", "robot", "system"})

#: ``ConversationMemory`` rows carry a free-form ``origin`` string
#: (``runtime.TRANSCRIPT_ORIGINS``); this store carries a coarse closed
#: ``source``. This is the only bridge between the two vocabularies, and it is
#: fail-closed: an origin with no mapping is refused rather than guessed at.
#: The raw origin is preserved byte-exact in ``meta["origin"]`` regardless, so
#: the coarsening loses nothing.
ORIGIN_SOURCES: Mapping[str, str] = {
    "realtime": "realtime",
    "mic": "local",
    "panel_text": "local",
    "corpus": "corpus",
}

#: The store's own table. Additive: nothing else in the repo names it.
TABLE = "conversation_turns"

#: Explicit, named indexes. ``ts_utc`` alone answers "what was said between
#: these two instants" across every session; ``(session_id, ts_utc)`` answers
#: the same question inside one conversation without a filesort.
TS_INDEX = "idx_conversation_turns_ts"
SESSION_TS_INDEX = "idx_conversation_turns_session_ts"
#: Not UNIQUE. ``lane._write_ledger`` can legitimately write two rows carrying
#: the same provider item id (the ingress-refused path re-ledgers the same
#: transcript), and every ``system`` marker carries ``None``. Uniqueness would
#: turn a duplicate into a raised exception on the hot turn path; de-duplication
#: is instead an explicit concern of :func:`import_realtime_turns`.
ITEM_INDEX = "idx_conversation_turns_item"

_COLUMNS = "seq, ts_utc, session_id, source, speaker, text, provider_item_id, meta"
_SELECT = f"SELECT {_COLUMNS} FROM {TABLE}"


class ConversationStoreError(ValueError):
    """A turn was refused, or a store operation was asked for the impossible.

    Subclasses :class:`ValueError` deliberately: ``lane._write_ledger`` already
    catches ``(RuntimeError, TypeError, ValueError)`` around its ledger write,
    so a store wired in behind it inherits the lane's never-kill-a-turn rule
    for free rather than needing a new except clause in an audited module.
    """


def utc_now() -> float:
    """The default clock: UTC epoch seconds, explicitly through ``timezone.utc``.

    ``time.time()`` returns the same number, but spelling the timezone here
    means the UTC claim is in the code rather than in a comment — and the test
    that asserts the two agree is checking a real property instead of a tautology.
    """

    return datetime.now(timezone.utc).timestamp()


def canonical_meta_json(meta: Mapping[str, Any]) -> str:
    """Serialize ``meta`` to the exact bytes the store persists.

    Canonical means: keys sorted, no insignificant whitespace, no ASCII
    escaping (so unicode survives as unicode), and ``NaN``/``Infinity``
    refused — those are not JSON, and a store that emits them writes rows no
    other JSON reader on earth can parse.
    """

    if not isinstance(meta, Mapping):
        raise ConversationStoreError(f"turn meta must be a mapping, got {type(meta).__name__}")
    try:
        return json.dumps(
            dict(meta),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ConversationStoreError(f"turn meta is not JSON-serializable: {error}") from error


@dataclass(frozen=True, kw_only=True)
class TurnRecord:
    """One raw conversational turn, as spoken or heard.

    Keyword-only by construction: seven fields of which four are strings would
    otherwise be a positional-argument accident waiting to happen.

    ``ts_utc`` and ``seq`` are ``None`` on a turn that has not been stored yet.
    :meth:`ConversationStore.append` returns a *stamped* copy with both set;
    the caller's original is untouched (the record is frozen).
    """

    session_id: str | None
    source: str
    speaker: str
    text: str
    provider_item_id: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)
    ts_utc: float | None = None
    seq: int | None = None

    def __post_init__(self) -> None:
        if self.session_id is not None and not isinstance(self.session_id, str):
            raise ConversationStoreError(f"session_id must be str or None: {self.session_id!r}")
        if self.source not in SOURCES:
            raise ConversationStoreError(
                f"unsupported turn source {self.source!r}; known: {sorted(SOURCES)}"
            )
        if self.speaker not in SPEAKERS:
            raise ConversationStoreError(
                f"unsupported turn speaker {self.speaker!r}; known: {sorted(SPEAKERS)}"
            )
        if not isinstance(self.text, str) or not self.text.strip():
            raise ConversationStoreError("turn text must be a non-empty string")
        if self.provider_item_id is not None and not isinstance(self.provider_item_id, str):
            raise ConversationStoreError(
                f"provider_item_id must be str or None: {self.provider_item_id!r}"
            )
        if self.ts_utc is not None:
            _check_timestamp(self.ts_utc)
        if self.seq is not None and not isinstance(self.seq, int):
            raise ConversationStoreError(f"seq must be int or None: {self.seq!r}")

        # Refuse anything that would come back out as a different object. A
        # tuple silently becomes a list and an int key silently becomes a
        # string; either is a lie about what was stored.
        encoded = canonical_meta_json(self.meta)
        decoded = json.loads(encoded)
        if decoded != dict(self.meta):
            raise ConversationStoreError(
                "turn meta does not round-trip through JSON unchanged "
                f"({dict(self.meta)!r} -> {decoded!r}); use JSON types only"
            )
        # A plain dict copy, so a caller mutating the mapping it passed in
        # cannot reach into a stored record.
        object.__setattr__(self, "meta", decoded)

    @property
    def meta_json(self) -> str:
        """The canonical JSON the store persists for this record."""

        return canonical_meta_json(self.meta)

    def stamped(self, *, ts_utc: float, seq: int) -> TurnRecord:
        """This turn as stored: same content, with its write time and order."""

        _check_timestamp(ts_utc)
        return TurnRecord(
            session_id=self.session_id,
            source=self.source,
            speaker=self.speaker,
            text=self.text,
            provider_item_id=self.provider_item_id,
            meta=self.meta,
            ts_utc=float(ts_utc),
            seq=int(seq),
        )

    def iso_utc(self) -> str:
        """Render this turn's instant for a human. Read-time only, never stored."""

        if self.ts_utc is None:
            raise ConversationStoreError("an unstamped turn has no instant to render")
        return datetime.fromtimestamp(self.ts_utc, tz=timezone.utc).isoformat()


def _check_timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConversationStoreError(f"ts_utc must be a float, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ConversationStoreError(f"ts_utc must be finite, got {value!r}")
    return number


@runtime_checkable
class ConversationStore(Protocol):
    """Everything a conversation backend must do. Six methods, no base class.

    Implementations are free about *how* — a table, a log segment, a vector
    index with a payload — and bound only by the semantics stated here and
    enforced by the parametrized conformance suite.
    """

    def append(self, turn: TurnRecord) -> TurnRecord:
        """Persist ``turn``; return it stamped with ``ts_utc`` and ``seq``.

        An unstamped turn (``ts_utc is None``) is stamped from the store's own
        injected clock. A pre-stamped turn keeps its instant — that is what
        makes backfilling historical rows possible. ``seq`` is always assigned
        by the store and strictly increases.
        """

    def by_time_range(self, start_utc: float | None, end_utc: float | None) -> list[TurnRecord]:
        """Turns with ``start_utc <= ts_utc < end_utc``, oldest first.

        Either bound may be ``None`` for an open end. ``start_utc > end_utc``
        is refused rather than quietly returning nothing.
        """

    def by_session(self, session_id: str) -> list[TurnRecord]:
        """Every turn of one session, oldest first.

        Turns written with ``session_id=None`` belong to no session and are
        never returned here; :meth:`by_time_range` still sees them.
        """

    def latest(self, n: int = 20) -> list[TurnRecord]:
        """The ``n`` most recent turns, returned **oldest first**.

        Oldest-first matches ``ConversationMemory.recent`` and
        ``realtime_turns``: the tail is almost always about to be replayed as
        conversation history, and history reads forwards.
        """

    def count(self) -> int:
        """How many turns are stored."""

    def close(self) -> None:
        """Release the backend. Idempotent; a closed store refuses reads."""


class SqliteConversationStore:
    """Today's backend: one SQLite table, WAL, two explicit time indexes.

    One writer, many readers — the repo's ledger discipline. Writes take an
    ``RLock`` and commit; reads are lock-free at the SQLite level but take the
    same lock to keep a read from observing a half-written batch, exactly as
    :class:`~parcel_robot.memory.ConversationMemory` does.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        clock: Callable[[], float] = utc_now,
        purpose: str | None = None,
    ) -> None:
        """Card R27: this store's path goes through the same refusal as the ledger.

        The raw-conversation store is not wired into the runtime yet (see the
        module docstring's honesty boundary), so it has never polluted anything.
        That is exactly why the guard belongs here NOW: the moment a config gains
        a ``conversation_store.path`` it will be relative — every other path in
        ``robot.yaml`` is — and this card would otherwise have fixed one ledger
        and left its designated replacement carrying the original defect.
        """

        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        #: The resolved decision, same shape and same rules as
        #: ``ConversationMemory.store``.
        self.store = resolve_memory_path(path, purpose=purpose)
        self.path = self.store.path
        self.connection = sqlite3.connect(self.store.path, check_same_thread=False)
        with self._lock:
            # WAL lets readers run while the single writer commits. An
            # in-memory database has no write-ahead log to enable and reports
            # "memory"; recorded rather than asserted so the difference is
            # visible instead of surprising.
            row = self.connection.execute("PRAGMA journal_mode=WAL").fetchone()
            self.journal_mode = str(row[0]) if row else "unknown"
            self.connection.execute(
                f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts_utc REAL NOT NULL, "
                "session_id TEXT, "
                "source TEXT NOT NULL, "
                "speaker TEXT NOT NULL, "
                "text TEXT NOT NULL, "
                "provider_item_id TEXT, "
                "meta TEXT NOT NULL)"
            )
            self.connection.execute(f"CREATE INDEX IF NOT EXISTS {TS_INDEX} ON {TABLE}(ts_utc)")
            self.connection.execute(
                f"CREATE INDEX IF NOT EXISTS {SESSION_TS_INDEX} ON {TABLE}(session_id, ts_utc)"
            )
            self.connection.execute(
                f"CREATE INDEX IF NOT EXISTS {ITEM_INDEX} ON {TABLE}(provider_item_id)"
            )
            self.connection.commit()

    # ------------------------------------------------------------------ write
    def append(self, turn: TurnRecord) -> TurnRecord:
        self._require_open()
        if not isinstance(turn, TurnRecord):
            raise ConversationStoreError(f"append expects a TurnRecord, got {type(turn).__name__}")
        ts_utc = _check_timestamp(self._clock() if turn.ts_utc is None else turn.ts_utc)
        with self._lock:
            cursor = self.connection.execute(
                f"INSERT INTO {TABLE}"
                "(ts_utc, session_id, source, speaker, text, provider_item_id, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ts_utc,
                    turn.session_id,
                    turn.source,
                    turn.speaker,
                    turn.text,
                    turn.provider_item_id,
                    turn.meta_json,
                ),
            )
            self.connection.commit()
            seq = int(cursor.lastrowid or 0)
        return turn.stamped(ts_utc=ts_utc, seq=seq)

    # ------------------------------------------------------------------- read
    def by_time_range(self, start_utc: float | None, end_utc: float | None) -> list[TurnRecord]:
        self._require_open()
        sql, params = _range_query(start_utc, end_utc)
        return self._fetch(sql, params)

    def by_session(self, session_id: str) -> list[TurnRecord]:
        self._require_open()
        if not isinstance(session_id, str):
            raise ConversationStoreError(f"session_id must be a string: {session_id!r}")
        return self._fetch(_SESSION_SQL, (session_id,))

    def latest(self, n: int = 20) -> list[TurnRecord]:
        self._require_open()
        limit = _check_limit(n)
        if limit == 0:
            return []
        rows = self._fetch(_LATEST_SQL, (limit,))
        rows.reverse()
        return rows

    def count(self) -> int:
        self._require_open()
        with self._lock:
            row = self.connection.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            self._closed = True
            self.connection.close()

    # -------------------------------------------------------------- internals
    def query_plan(self, kind: str) -> list[str]:
        """``EXPLAIN QUERY PLAN`` for the store's **own** read queries.

        The plan is taken over the exact SQL string the reader executes, not a
        hand-typed lookalike, so the index proof in the test suite cannot drift
        away from the implementation it claims to be proving.
        """

        self._require_open()
        plans = {
            "time_range": _range_query(0.0, 1.0),
            "start_only": _range_query(0.0, None),
            "session": (_SESSION_SQL, ("s",)),
            "latest": (_LATEST_SQL, (5,)),
        }
        if kind not in plans:
            raise ConversationStoreError(f"unknown query kind {kind!r}; known: {sorted(plans)}")
        sql, params = plans[kind]
        with self._lock:
            rows = self.connection.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return [str(row[3]) for row in rows]

    def _fetch(self, sql: str, params: Sequence[Any]) -> list[TurnRecord]:
        with self._lock:
            rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [_row_to_record(row) for row in rows]

    def _require_open(self) -> None:
        if self._closed:
            raise ConversationStoreError("conversation store is closed")


_SESSION_SQL = f"{_SELECT} WHERE session_id = ? ORDER BY ts_utc, seq"
_LATEST_SQL = f"{_SELECT} ORDER BY ts_utc DESC, seq DESC LIMIT ?"


def _range_query(start_utc: float | None, end_utc: float | None) -> tuple[str, tuple[float, ...]]:
    """Build the half-open range query. Inclusive start, exclusive end."""

    if start_utc is not None:
        _check_timestamp(start_utc)
    if end_utc is not None:
        _check_timestamp(end_utc)
    if start_utc is not None and end_utc is not None and start_utc > end_utc:
        raise ConversationStoreError(f"time range runs backwards: {start_utc} > {end_utc}")
    clauses: list[str] = []
    params: list[float] = []
    if start_utc is not None:
        clauses.append("ts_utc >= ?")
        params.append(float(start_utc))
    if end_utc is not None:
        clauses.append("ts_utc < ?")
        params.append(float(end_utc))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return f"{_SELECT}{where} ORDER BY ts_utc, seq", tuple(params)


def _check_limit(n: object) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise ConversationStoreError(f"latest(n) needs an int, got {n!r}")
    if n < 0:
        raise ConversationStoreError(f"latest(n) needs n >= 0, got {n}")
    return int(n)


def _row_to_record(row: Sequence[Any]) -> TurnRecord:
    seq, ts_utc, session_id, source, speaker, text, provider_item_id, meta = row
    try:
        decoded = json.loads(meta)
    except (TypeError, ValueError) as error:
        raise ConversationStoreError(f"stored meta is not JSON for seq={seq}: {error}") from error
    return TurnRecord(
        session_id=session_id,
        source=source,
        speaker=speaker,
        text=text,
        provider_item_id=provider_item_id,
        meta=decoded,
        ts_utc=float(ts_utc),
        seq=int(seq),
    )


# ============================================================ the write seam
def source_for_origin(origin: str) -> str:
    """Map a ``ConversationMemory`` ``origin`` onto this store's ``source``.

    Fail-closed. A new transcript origin appearing in ``runtime.py`` without a
    mapping here means turns from that path would otherwise be filed under a
    guess; refusing makes the omission loud (a logged warning on the dual-write
    path, and a red test in ``tests/test_conversation_store.py``).
    """

    mapped = ORIGIN_SOURCES.get(origin)
    if mapped is None:
        raise ConversationStoreError(
            f"no store source mapped for transcript origin {origin!r}; "
            f"known: {sorted(ORIGIN_SOURCES)}"
        )
    return mapped


def mirror_realtime_turn(
    store: ConversationStore,
    *,
    session_id: str | None,
    speaker: str,
    text: str,
    origin: str,
    provider_item_id: str | None = None,
    ledger_row_id: int | None = None,
) -> TurnRecord | None:
    """Dual-write one already-ledgered turn into ``store``. Never raises.

    This is the never-kill-a-turn rule, and it is not negotiable: the ledger
    row is already committed by the time this runs, so a store that is full,
    locked, closed or simply broken must cost a log line, not the turn. Returns
    the stored record, or ``None`` if the mirror failed.

    ``meta`` deliberately keeps the *raw* origin string and the ``messages``
    row id, so a coarsened ``source`` loses no provenance and either row can be
    found from the other.
    """

    try:
        record = TurnRecord(
            session_id=session_id,
            source=source_for_origin(origin),
            speaker=speaker,
            text=text,
            provider_item_id=provider_item_id,
            meta=_mirror_meta(origin, ledger_row_id),
        )
        return store.append(record)
    except Exception as error:  # noqa: BLE001 - a turn must outlive its storage
        logger.warning(
            "conversation store mirror failed for speaker=%s origin=%s item=%s: %s",
            speaker,
            origin,
            provider_item_id,
            error,
        )
        return None


def _mirror_meta(origin: str, ledger_row_id: int | None) -> dict[str, Any]:
    """The meta shape shared by the live dual-write and the backfill.

    Identical on both paths on purpose: a turn that was mirrored live and the
    same turn imported from the ledger must be indistinguishable apart from
    when they were stamped, which is what makes the backfill safe to run over a
    database that has been dual-writing all along.
    """

    meta: dict[str, Any] = {"origin": origin}
    if ledger_row_id is not None:
        meta["ledger_row_id"] = int(ledger_row_id)
    return meta


# ============================================================== the backfill
class RealtimeLedgerLike(Protocol):
    """The part of ``ConversationMemory`` the backfill reads.

    A Protocol rather than an import so this module depends on nothing in the
    package: ``memory`` imports ``conversation_store``, never the reverse.
    """

    connection: sqlite3.Connection

    def realtime_turns(
        self, *, session_id: str | None = ..., limit: int = ...
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class ImportResult:
    """What one :func:`import_realtime_turns` pass did. All four are asserted."""

    scanned: int = 0
    imported: int = 0
    #: already present, by provider item id or by natural key
    duplicates: int = 0
    #: unmapped origin, or a ``created_at`` this module refuses to guess at
    refused: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "refused": self.refused,
        }


def import_realtime_turns(
    memory: RealtimeLedgerLike,
    store: ConversationStore,
    *,
    session_id: str | None = None,
    limit: int = 100_000,
) -> ImportResult:
    """Backfill rows R1/R2-C already wrote into ``messages`` into ``store``.

    **Idempotent**: running it twice imports zero rows the second time. The
    de-duplication key is ``provider_item_id`` where there is one — the card's
    requirement — and the natural key ``(session_id, speaker, text, ts_utc)``
    where there is not, because every ``system`` marker the lane writes
    (rollover notes, summaries) carries no item id and dropping them would make
    the backfill lossy.

    Written against the :class:`ConversationStore` Protocol, so it backfills
    into *any* backend, not just SQLite. It reads the existing key set through
    :meth:`~ConversationStore.count` + :meth:`~ConversationStore.latest`, which
    is O(rows) — correct for a one-shot migration, wrong for a hot path, and
    not used on one.

    Timestamps come from the ``messages.created_at`` column that SQLite stamps
    in UTC, **not** from the clock at import time: a backfill that filed a
    year of conversation under today's date would defeat the entire point of a
    timestamp-indexed store. A row whose ``created_at`` cannot be parsed is
    refused rather than given a fabricated instant.
    """

    rows = memory.realtime_turns(session_id=session_id, limit=limit)
    created = _created_at_map(memory, [int(row["id"]) for row in rows if row.get("id") is not None])

    existing = store.latest(store.count())
    keys = {_dedupe_key(record) for record in existing}

    scanned = imported = duplicates = refused = 0
    for row in rows:
        scanned += 1
        row_id = row.get("id")
        ts_utc = created.get(int(row_id)) if row_id is not None else None
        if ts_utc is None:
            logger.warning("backfill refused messages row %s: no parseable created_at", row_id)
            refused += 1
            continue
        try:
            record = TurnRecord(
                session_id=_as_optional_str(row.get("session_id")),
                source=source_for_origin(str(row.get("origin"))),
                speaker=str(row.get("speaker")),
                text=str(row.get("content")),
                provider_item_id=_as_optional_str(row.get("provider_item_id")),
                meta=_mirror_meta(str(row.get("origin")), None if row_id is None else int(row_id)),
                ts_utc=ts_utc,
            )
        except ConversationStoreError as error:
            logger.warning("backfill refused messages row %s: %s", row_id, error)
            refused += 1
            continue
        key = _dedupe_key(record)
        if key in keys:
            duplicates += 1
            continue
        store.append(record)
        keys.add(key)
        imported += 1
    return ImportResult(scanned=scanned, imported=imported, duplicates=duplicates, refused=refused)


def _dedupe_key(record: TurnRecord) -> tuple[object, ...]:
    if record.provider_item_id:
        return ("item", record.provider_item_id)
    return ("natural", record.session_id, record.speaker, record.text, record.ts_utc)


def _as_optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _created_at_map(memory: RealtimeLedgerLike, row_ids: Sequence[int]) -> dict[int, float]:
    """``messages.id -> UTC epoch float``, read straight from the ledger table.

    ``realtime_turns()`` is the row source of truth (its ``speaker IS NOT
    NULL`` filter is load-bearing — it is what keeps a typed panel command out
    of the hosted history), but it does not project ``created_at``. Rather than
    re-implement its filter here, this reads only the one missing column for
    the ids it already returned.
    """

    if not row_ids:
        return {}
    placeholders = ",".join("?" for _ in row_ids)
    rows = memory.connection.execute(
        f"SELECT id, created_at FROM messages WHERE id IN ({placeholders})",
        tuple(row_ids),
    ).fetchall()
    stamps: dict[int, float] = {}
    for row_id, created_at in rows:
        parsed = parse_sqlite_utc(created_at)
        if parsed is not None:
            stamps[int(row_id)] = parsed
    return stamps


def parse_sqlite_utc(value: object) -> float | None:
    """SQLite's ``CURRENT_TIMESTAMP`` text -> UTC epoch float, or ``None``.

    SQLite stamps ``YYYY-MM-DD HH:MM:SS`` in **UTC** with no timezone suffix,
    so a naive parse is attached to UTC rather than to the machine's local
    zone. An explicit offset, if some other writer left one, is honoured and
    converted.
    """

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def open_store(
    path: str | Path, *, clock: Callable[[], float] = utc_now, purpose: str | None = None
) -> SqliteConversationStore:
    """Construct the default backend. One call site to change when it changes."""

    return SqliteConversationStore(path, clock=clock, purpose=purpose)


__all__ = [
    "ORIGIN_SOURCES",
    "SOURCES",
    "SPEAKERS",
    "TABLE",
    "ConversationStore",
    "ConversationStoreError",
    "ImportResult",
    "SqliteConversationStore",
    "TurnRecord",
    "canonical_meta_json",
    "import_realtime_turns",
    "mirror_realtime_turn",
    "open_store",
    "parse_sqlite_utc",
    "source_for_origin",
    "utc_now",
]
