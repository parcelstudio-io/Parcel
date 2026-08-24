"""Card R2-D: the raw conversation store — seam first, backend second.

WHAT THIS FILE IS FOR
---------------------
The owner's directive ends with *"storage design is subject to change"*, so the
deliverable under test is not a schema — it is a **seam**. Almost everything
below is written against the :class:`ConversationStore` Protocol and is run
twice, once against the shipped :class:`SqliteConversationStore` and once
against :class:`ToyConversationStore`, a fifty-line list-and-loop store that
exists **only in this file** and touches no database at all.

That second implementation is the whole proof. If the conformance suite could
only pass against SQLite, "swappable" would be a claim; because a store made of
a Python list passes the identical parametrized suite, the next backend —
Postgres, a vector index, an append-only log — has an executable definition of
done and nothing else in the codebase has to move. Every test taking the
``store`` fixture runs under both; pytest shows them as ``[sqlite]`` and
``[toy]``.

The SQLite-only section below (``EXPLAIN QUERY PLAN``, WAL, the additive-table
check) is deliberately quarantined: those are properties of *today's* backend,
not of the seam, and a future backend is not obliged to have them.

TIME IS INJECTED, ALWAYS
------------------------
No sleeps and no wall clock. ``_Clock`` is advanced by hand. This matters more
here than usual: a frozen clock makes consecutive turns share a ``ts_utc``
exactly, which is precisely the condition under which an ordering that relies
on timestamps alone becomes non-deterministic — so the frozen clock is not a
convenience, it is the adversarial case.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.memory.conversation import OWNER_FACTS_TABLE, ConversationMemory
from parcel_robot.memory.store import (
    ITEM_INDEX,
    ORIGIN_SOURCES,
    SESSION_TS_INDEX,
    SOURCES,
    SPEAKERS,
    TABLE,
    TS_INDEX,
    ConversationStore,
    ConversationStoreError,
    ImportResult,
    SqliteConversationStore,
    TurnRecord,
    canonical_meta_json,
    import_realtime_turns,
    mirror_realtime_turn,
    open_store,
    parse_sqlite_utc,
    source_for_origin,
    utc_now,
)

#: A round, fixed instant: 2023-11-14T22:13:20+00:00. Pinned rather than
#: "now" so the ISO rendering below is an assertion and not a restatement.
PINNED = 1_700_000_000.0


class _Clock:
    """A hand-advanced clock. The only source of time in this file."""

    def __init__(self, start: float = PINNED) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class ToyConversationStore:
    """A conversation store made of a Python list. No database, no SQL.

    This is not a mock — it is a second real implementation of the Protocol,
    and it is the evidence for "storage design is subject to change". It obeys
    the same three semantics the docstring of :class:`ConversationStore` states
    and nothing else: half-open ranges, ``(ts_utc, seq)`` ordering, and
    oldest-first returns.
    """

    def __init__(self, *, clock: Any = utc_now) -> None:
        self._clock = clock
        self._rows: list[TurnRecord] = []
        self._seq = 0
        self._closed = False

    def append(self, turn: TurnRecord) -> TurnRecord:
        self._require_open()
        if not isinstance(turn, TurnRecord):
            raise ConversationStoreError(f"append expects a TurnRecord, got {type(turn).__name__}")
        ts_utc = float(self._clock() if turn.ts_utc is None else turn.ts_utc)
        self._seq += 1
        stored = turn.stamped(ts_utc=ts_utc, seq=self._seq)
        self._rows.append(stored)
        return stored

    def by_time_range(self, start_utc: float | None, end_utc: float | None) -> list[TurnRecord]:
        self._require_open()
        if start_utc is not None and end_utc is not None and start_utc > end_utc:
            raise ConversationStoreError(f"time range runs backwards: {start_utc} > {end_utc}")
        return self._ordered(
            row
            for row in self._rows
            if (start_utc is None or row.ts_utc >= start_utc)
            and (end_utc is None or row.ts_utc < end_utc)
        )

    def by_session(self, session_id: str) -> list[TurnRecord]:
        self._require_open()
        if not isinstance(session_id, str):
            raise ConversationStoreError(f"session_id must be a string: {session_id!r}")
        return self._ordered(row for row in self._rows if row.session_id == session_id)

    def latest(self, n: int = 20) -> list[TurnRecord]:
        self._require_open()
        if isinstance(n, bool) or not isinstance(n, int):
            raise ConversationStoreError(f"latest(n) needs an int, got {n!r}")
        if n < 0:
            raise ConversationStoreError(f"latest(n) needs n >= 0, got {n}")
        if n == 0:
            return []
        return self._ordered(self._rows)[-n:]

    def count(self) -> int:
        self._require_open()
        return len(self._rows)

    def close(self) -> None:
        self._closed = True

    def _ordered(self, rows: Any) -> list[TurnRecord]:
        return sorted(rows, key=lambda row: (row.ts_utc, row.seq))

    def _require_open(self) -> None:
        if self._closed:
            raise ConversationStoreError("conversation store is closed")


#: Every implementation the conformance suite must hold for. Adding a backend
#: means adding one line here and changing no test.
STORE_IMPLEMENTATIONS = ("sqlite", "toy")


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture(params=STORE_IMPLEMENTATIONS)
def store(request: pytest.FixtureRequest, clock: _Clock, tmp_path: Path) -> Any:
    """One store per implementation. Never the live database — always tmp_path."""

    if request.param == "sqlite":
        made: Any = SqliteConversationStore(tmp_path / "turns.sqlite3", clock=clock)
    else:
        made = ToyConversationStore(clock=clock)
    yield made
    made.close()


def _turn(text: str = "hello", **overrides: Any) -> TurnRecord:
    fields: dict[str, Any] = {
        "session_id": "sess_1",
        "source": "realtime",
        "speaker": "owner",
        "text": text,
    }
    fields.update(overrides)
    return TurnRecord(**fields)


# ==================================================== the seam is really a seam
def test_both_implementations_satisfy_the_protocol(store: ConversationStore) -> None:
    assert isinstance(store, ConversationStore)


def test_the_conformance_suite_runs_against_more_than_one_implementation() -> None:
    """The 'subject to change' guarantee, stated as an assertion.

    A suite that only ever saw SQLite would prove the schema, not the seam.
    """

    assert len(STORE_IMPLEMENTATIONS) >= 2
    assert isinstance(SqliteConversationStore(":memory:"), ConversationStore)
    assert isinstance(ToyConversationStore(), ConversationStore)


def test_the_toy_store_is_not_a_database() -> None:
    """Guard against the toy quietly growing a SQLite dependency."""

    source = Path(__file__).read_text(encoding="utf-8")
    body = source.split("class ToyConversationStore")[1].split("STORE_IMPLEMENTATIONS")[0]
    assert "sqlite3" not in body
    assert "SELECT" not in body


# ========================================================= append and identity
def test_an_appended_turn_comes_back_stamped(store: ConversationStore, clock: _Clock) -> None:
    stored = store.append(_turn("good morning"))
    assert stored.ts_utc == clock.now
    assert stored.seq is not None
    assert stored.text == "good morning"
    assert store.count() == 1


def test_append_does_not_mutate_the_caller_s_record(store: ConversationStore) -> None:
    """``TurnRecord`` is frozen; the store hands back a copy, not a mutation."""

    original = _turn()
    stored = store.append(original)
    assert original.ts_utc is None
    assert original.seq is None
    assert stored is not original


def test_seq_strictly_increases_even_under_a_frozen_clock(store: ConversationStore) -> None:
    seqs = [store.append(_turn(f"turn {i}")).seq for i in range(5)]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 5


def test_a_pre_stamped_turn_keeps_its_own_instant(store: ConversationStore) -> None:
    """Backfill depends on this: history must not be filed under today."""

    stored = store.append(_turn("from last year", ts_utc=PINNED - 86_400.0))
    assert stored.ts_utc == PINNED - 86_400.0


def test_append_refuses_something_that_is_not_a_turn(store: ConversationStore) -> None:
    with pytest.raises(ConversationStoreError):
        store.append({"text": "not a record"})  # type: ignore[arg-type]


# ================================================================ vocabularies
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_every_known_source_is_accepted(store: ConversationStore, source: str) -> None:
    assert store.append(_turn(source=source)).source == source


@pytest.mark.parametrize("speaker", sorted(SPEAKERS))
def test_every_known_speaker_is_accepted(store: ConversationStore, speaker: str) -> None:
    assert store.append(_turn(speaker=speaker)).speaker == speaker


@pytest.mark.parametrize("source", ["Realtime", "hosted", "", "cloud", None, 3])
def test_an_unknown_source_is_refused_not_coerced(source: Any) -> None:
    with pytest.raises(ConversationStoreError, match="source"):
        _turn(source=source)


@pytest.mark.parametrize("speaker", ["oracle", "user", "assistant", "", None])
def test_an_unknown_speaker_is_refused_not_coerced(speaker: Any) -> None:
    """``user``/``assistant`` are the *messages* table's vocabulary, not this one."""

    with pytest.raises(ConversationStoreError, match="speaker"):
        _turn(speaker=speaker)


def test_the_speaker_vocabulary_matches_the_ledger_s(store: ConversationStore) -> None:
    """The two stores must agree about who speaks or migration is guesswork."""

    from parcel_robot.memory.conversation import _SPEAKER_ROLES

    assert set(_SPEAKER_ROLES) == set(SPEAKERS)


@pytest.mark.parametrize("text", ["", "   ", "\n\t", None, 7])
def test_an_empty_turn_is_refused(text: Any) -> None:
    with pytest.raises(ConversationStoreError, match="text"):
        _turn(text=text)


def test_a_session_id_may_be_absent_but_not_a_number() -> None:
    assert _turn(session_id=None).session_id is None
    with pytest.raises(ConversationStoreError, match="session_id"):
        _turn(session_id=17)


# =============================================================== meta fidelity
def test_meta_round_trips_byte_exact_through_storage(store: ConversationStore) -> None:
    meta = {
        "nested": {"b": [1, 2, {"deep": True}], "a": None},
        "unicode": "안녕하세요 — café ☕",
        "float": 0.125,
        "empty": {},
    }
    stored = store.append(_turn(meta=meta))
    read_back = store.latest(1)[0]
    assert read_back.meta == meta
    # Byte-exact, not merely equal: the canonical serialization is identical.
    assert read_back.meta_json == stored.meta_json == canonical_meta_json(meta)
    assert json.loads(read_back.meta_json) == meta


def test_canonical_meta_is_stable_regardless_of_key_order() -> None:
    assert canonical_meta_json({"b": 1, "a": 2}) == canonical_meta_json({"a": 2, "b": 1})
    assert canonical_meta_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'


def test_unicode_is_stored_as_unicode_not_escaped() -> None:
    assert canonical_meta_json({"k": "café"}) == '{"k":"café"}'


def test_meta_defaults_to_empty_and_survives_the_round_trip(store: ConversationStore) -> None:
    store.append(_turn())
    assert store.latest(1)[0].meta == {}


@pytest.mark.parametrize(
    "meta",
    [
        {"tuple": (1, 2)},
        {1: "int key"},
        {"set": {1, 2}},
        {"nan": float("nan")},
        {"inf": float("inf")},
        {"object": object()},
        "not a mapping",
        None,
    ],
)
def test_meta_that_would_not_survive_the_round_trip_is_refused(meta: Any) -> None:
    """Silent mutation is the failure mode this refuses.

    A tuple comes back a list and an int key comes back a string; storing them
    means the record read out is not the record written in.
    """

    with pytest.raises(ConversationStoreError):
        _turn(meta=meta)


def test_a_caller_mutating_its_own_mapping_cannot_reach_a_stored_record(
    store: ConversationStore,
) -> None:
    mutable = {"k": "v"}
    stored = store.append(_turn(meta=mutable))
    mutable["k"] = "changed"
    assert stored.meta == {"k": "v"}
    assert store.latest(1)[0].meta == {"k": "v"}


# ================================================================ UTC and time
def test_a_fixed_injected_clock_produces_a_pinned_timestamp(
    store: ConversationStore, clock: _Clock
) -> None:
    """The S2 detector: nothing here may read the machine's wall clock."""

    stored = store.append(_turn())
    assert stored.ts_utc == PINNED
    assert stored.iso_utc() == "2023-11-14T22:13:20+00:00"
    clock.advance(3600.0)
    later = store.append(_turn("an hour on"))
    assert later.ts_utc == PINNED + 3600.0
    assert later.iso_utc() == "2023-11-14T23:13:20+00:00"


def test_the_default_clock_is_utc_epoch_seconds() -> None:
    import time

    assert abs(utc_now() - time.time()) < 2.0


def test_timestamps_are_stored_as_floats_and_rendered_only_on_read(
    store: ConversationStore,
) -> None:
    stored = store.append(_turn())
    assert isinstance(stored.ts_utc, float)
    assert stored.iso_utc().endswith("+00:00")


def test_an_unstamped_turn_has_no_instant_to_render() -> None:
    with pytest.raises(ConversationStoreError):
        _turn().iso_utc()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "12", True, None])
def test_a_nonsense_timestamp_is_refused(bad: Any) -> None:
    if bad is None:
        assert _turn(ts_utc=None).ts_utc is None
        return
    with pytest.raises(ConversationStoreError, match="ts_utc"):
        _turn(ts_utc=bad)


def test_a_store_whose_clock_is_broken_refuses_rather_than_writes_garbage(
    tmp_path: Path,
) -> None:
    broken = SqliteConversationStore(tmp_path / "b.sqlite3", clock=lambda: float("nan"))
    with pytest.raises(ConversationStoreError):
        broken.append(_turn())
    assert broken.count() == 0
    broken.close()


# ============================================================== range queries
def _three_turns(store: ConversationStore, clock: _Clock) -> list[TurnRecord]:
    first = store.append(_turn("t0"))
    clock.advance(1.0)
    second = store.append(_turn("t1"))
    clock.advance(1.0)
    third = store.append(_turn("t2"))
    return [first, second, third]


def test_a_range_is_inclusive_of_its_start_and_exclusive_of_its_end(
    store: ConversationStore, clock: _Clock
) -> None:
    """The S5 detector. Documented in the module docstring; asserted here."""

    _three_turns(store, clock)
    window = store.by_time_range(PINNED, PINNED + 2.0)
    assert [row.text for row in window] == ["t0", "t1"]


def test_consecutive_windows_partition_the_timeline_exactly_once(
    store: ConversationStore, clock: _Clock
) -> None:
    """Why half-open: no turn dropped between windows, none counted twice."""

    _three_turns(store, clock)
    first = store.by_time_range(PINNED, PINNED + 1.0)
    second = store.by_time_range(PINNED + 1.0, PINNED + 3.0)
    assert [row.text for row in first] == ["t0"]
    assert [row.text for row in second] == ["t1", "t2"]
    assert not {row.seq for row in first} & {row.seq for row in second}
    assert len(first) + len(second) == store.count()


def test_a_zero_width_window_is_empty(store: ConversationStore, clock: _Clock) -> None:
    _three_turns(store, clock)
    assert store.by_time_range(PINNED, PINNED) == []


def test_either_bound_may_be_open(store: ConversationStore, clock: _Clock) -> None:
    _three_turns(store, clock)
    assert [row.text for row in store.by_time_range(None, None)] == ["t0", "t1", "t2"]
    assert [row.text for row in store.by_time_range(PINNED + 1.0, None)] == ["t1", "t2"]
    assert [row.text for row in store.by_time_range(None, PINNED + 1.0)] == ["t0"]


def test_a_backwards_range_is_refused_not_silently_empty(
    store: ConversationStore, clock: _Clock
) -> None:
    _three_turns(store, clock)
    with pytest.raises(ConversationStoreError, match="backwards"):
        store.by_time_range(PINNED + 5.0, PINNED)


def test_turns_sharing_an_instant_all_land_in_the_window(store: ConversationStore) -> None:
    """A frozen clock is the adversarial case for a timestamp index."""

    for i in range(4):
        store.append(_turn(f"same instant {i}"))
    window = store.by_time_range(PINNED, PINNED + 0.001)
    assert [row.text for row in window] == [f"same instant {i}" for i in range(4)]


def test_a_range_query_returns_oldest_first(store: ConversationStore, clock: _Clock) -> None:
    _three_turns(store, clock)
    stamps = [row.ts_utc for row in store.by_time_range(None, None)]
    assert stamps == sorted(stamps)


# ============================================================ session queries
def test_by_session_partitions_the_store(store: ConversationStore, clock: _Clock) -> None:
    store.append(_turn("a1", session_id="a"))
    clock.advance(1.0)
    store.append(_turn("b1", session_id="b"))
    clock.advance(1.0)
    store.append(_turn("a2", session_id="a"))
    assert [row.text for row in store.by_session("a")] == ["a1", "a2"]
    assert [row.text for row in store.by_session("b")] == ["b1"]
    assert store.by_session("nope") == []


def test_a_sessionless_turn_belongs_to_no_session_but_is_still_stored(
    store: ConversationStore,
) -> None:
    store.append(_turn("orphan", session_id=None))
    assert store.by_session("anything") == []
    assert [row.text for row in store.by_time_range(None, None)] == ["orphan"]
    assert store.count() == 1


def test_by_session_refuses_a_non_string(store: ConversationStore) -> None:
    with pytest.raises(ConversationStoreError, match="session_id"):
        store.by_session(None)  # type: ignore[arg-type]


# ============================================================== latest / count
def test_latest_returns_the_tail_oldest_first(store: ConversationStore, clock: _Clock) -> None:
    for i in range(5):
        store.append(_turn(f"turn {i}"))
        clock.advance(1.0)
    assert [row.text for row in store.latest(3)] == ["turn 2", "turn 3", "turn 4"]


def test_latest_is_deterministic_under_a_frozen_clock(store: ConversationStore) -> None:
    """Without the ``seq`` tiebreak this is the test that flaps."""

    for i in range(5):
        store.append(_turn(f"turn {i}"))
    assert [row.text for row in store.latest(3)] == ["turn 2", "turn 3", "turn 4"]


def test_latest_clamps_to_what_exists(store: ConversationStore) -> None:
    store.append(_turn("only"))
    assert [row.text for row in store.latest(50)] == ["only"]
    assert store.latest(0) == []


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
def test_latest_refuses_a_nonsense_count(store: ConversationStore, bad: Any) -> None:
    with pytest.raises(ConversationStoreError):
        store.latest(bad)


def test_count_tracks_appends(store: ConversationStore) -> None:
    assert store.count() == 0
    for i in range(3):
        store.append(_turn(f"turn {i}"))
    assert store.count() == 3


def test_an_empty_store_answers_every_read(store: ConversationStore) -> None:
    assert store.count() == 0
    assert store.latest() == []
    assert store.by_time_range(None, None) == []
    assert store.by_session("s") == []


# ==================================================================== lifecycle
def test_close_is_idempotent_and_a_closed_store_refuses(store: ConversationStore) -> None:
    store.append(_turn())
    store.close()
    store.close()
    with pytest.raises(ConversationStoreError, match="closed"):
        store.count()
    with pytest.raises(ConversationStoreError, match="closed"):
        store.append(_turn())


# ======================================================= SQLite-only specifics
# Properties of TODAY'S backend. A future backend owes the section above, not
# this one.
def test_the_time_range_query_uses_the_timestamp_index(tmp_path: Path) -> None:
    """The S1 detector, and the point of the whole card.

    ``EXPLAIN QUERY PLAN`` over the store's OWN query string — not a hand-typed
    lookalike — so this cannot drift away from the reader it claims to prove.
    An index that exists but is never chosen is decoration.
    """

    store = SqliteConversationStore(tmp_path / "plan.sqlite3", clock=_Clock())
    for i in range(200):
        store.append(_turn(f"turn {i}", ts_utc=PINNED + i))
    plan = " ".join(store.query_plan("time_range"))
    assert TS_INDEX in plan, plan
    assert "SEARCH" in plan and "SCAN " not in plan, plan
    assert TS_INDEX in " ".join(store.query_plan("start_only"))
    store.close()


def test_the_session_query_uses_the_composite_index(tmp_path: Path) -> None:
    store = SqliteConversationStore(tmp_path / "plan2.sqlite3", clock=_Clock())
    for i in range(200):
        store.append(_turn(f"turn {i}", session_id=f"s{i % 4}", ts_utc=PINNED + i))
    plan = " ".join(store.query_plan("session"))
    assert SESSION_TS_INDEX in plan, plan
    assert "SEARCH" in plan, plan
    store.close()


def test_the_latest_query_walks_the_timestamp_index_instead_of_sorting(
    tmp_path: Path,
) -> None:
    """No ``USE TEMP B-TREE FOR ORDER BY``: the tail read must not filesort."""

    store = SqliteConversationStore(tmp_path / "plan3.sqlite3", clock=_Clock())
    for i in range(200):
        store.append(_turn(f"turn {i}", ts_utc=PINNED + i))
    plan = " ".join(store.query_plan("latest"))
    assert TS_INDEX in plan, plan
    assert "TEMP B-TREE" not in plan, plan
    store.close()


def test_query_plan_refuses_an_unknown_query_kind(tmp_path: Path) -> None:
    store = SqliteConversationStore(tmp_path / "plan4.sqlite3")
    with pytest.raises(ConversationStoreError, match="unknown query kind"):
        store.query_plan("everything")
    store.close()


def test_the_indexes_exist_and_are_named(tmp_path: Path) -> None:
    store = SqliteConversationStore(tmp_path / "idx.sqlite3")
    names = {
        row[0]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (TABLE,)
        )
    }
    assert {TS_INDEX, SESSION_TS_INDEX, ITEM_INDEX} <= names
    store.close()


def test_the_item_index_is_not_unique(tmp_path: Path) -> None:
    """Uniqueness would turn a duplicate item id into a raised exception.

    ``lane._on_owner_transcript`` re-ledgers the same transcript when the
    ingress refuses it, carrying the same ``item_id``; de-duplication belongs
    to the backfill, not to a constraint on the hot turn path.
    """

    store = SqliteConversationStore(tmp_path / "dupe.sqlite3", clock=_Clock())
    store.append(_turn("said once", provider_item_id="item_a"))
    store.append(_turn("said once", provider_item_id="item_a"))
    assert store.count() == 2
    store.close()


def test_a_file_backed_store_runs_in_wal(tmp_path: Path) -> None:
    store = SqliteConversationStore(tmp_path / "wal.sqlite3")
    assert store.journal_mode == "wal"
    assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()


def test_an_in_memory_store_reports_memory_journalling_honestly() -> None:
    """No write-ahead log exists for ``:memory:``; recorded, not pretended."""

    store = SqliteConversationStore(":memory:")
    assert store.journal_mode == "memory"
    store.close()


def test_the_table_is_new_and_the_messages_table_is_untouched(tmp_path: Path) -> None:
    """Additive: the store's file has no ``messages`` table and never writes one."""

    store = SqliteConversationStore(tmp_path / "additive.sqlite3", clock=_Clock())
    store.append(_turn())
    tables = {
        row[0]
        for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert TABLE in tables
    assert "messages" not in tables
    store.close()


def test_turns_survive_reopening_the_file(tmp_path: Path) -> None:
    path = tmp_path / "durable.sqlite3"
    store = SqliteConversationStore(path, clock=_Clock())
    store.append(_turn("remembered", meta={"k": "v"}))
    store.close()

    again = SqliteConversationStore(path, clock=_Clock())
    rows = again.latest(10)
    assert [row.text for row in rows] == ["remembered"]
    assert rows[0].meta == {"k": "v"}
    assert rows[0].ts_utc == PINNED
    again.close()


def test_a_corrupted_row_reddens_on_read_rather_than_returning_a_lie(tmp_path: Path) -> None:
    """Fail-closed on the way out as well as in. Stated so it is not a surprise."""

    store = SqliteConversationStore(tmp_path / "corrupt.sqlite3", clock=_Clock())
    store.append(_turn())
    store.connection.execute(f"UPDATE {TABLE} SET speaker='oracle'")
    store.connection.commit()
    with pytest.raises(ConversationStoreError, match="speaker"):
        store.latest(1)
    store.close()


def test_open_store_builds_the_default_backend(tmp_path: Path) -> None:
    store = open_store(tmp_path / "default.sqlite3", clock=_Clock())
    assert isinstance(store, SqliteConversationStore)
    assert isinstance(store, ConversationStore)
    store.close()


# ============================================== the memory.py interception seam
def test_the_default_store_is_none_and_behaviour_is_byte_identical(tmp_path: Path) -> None:
    """The whole safety case for touching ``memory.py`` at all.

    Two ledgers get the same writes; one is called exactly as every existing
    call site calls it, the other passes ``store=None`` explicitly. The
    ``messages`` tables must be byte-identical, and neither may have grown a
    table **that the dual-write seam put there**.

    CARD P2-A MOVED THE EXPECTED SET, AND ONLY THE SET. It was ``{"messages"}``;
    it is now ``{"messages", "owner_facts"}``, because P2-A puts the owner-fact
    table beside ``messages`` in the same file on purpose — card R27's
    owner-store isolation guard is on ``ConversationMemory.__init__``, and a
    separate ``owner_facts.sqlite3`` would be a second path resolved by a second
    set of rules.

    What this test was written to catch is untouched: the assertion is still an
    EXACT set, so a third table appearing — from the dual-write seam or from
    anywhere else — still reddens it, and the two ledgers must still agree with
    each other. What changed is the baseline, once, visibly. See
    ``scrum/20260822/task_10/P2A_STATUS.md``.
    """

    def dump(path: Path, pass_store: bool) -> tuple[list[Any], set[str]]:
        memory = ConversationMemory(path)
        for i, speaker in enumerate(("owner", "robot", "system")):
            kwargs: dict[str, Any] = {
                "session_id": "s1",
                "speaker": speaker,
                "text": f"turn {i}",
                "origin": "realtime",
                "provider_item_id": f"item_{i}",
            }
            if pass_store:
                kwargs["store"] = None
            memory.write_realtime_turn(**kwargs)
        rows = memory.connection.execute(
            "SELECT id, role, content, session_id, speaker, origin, provider_item_id FROM messages"
        ).fetchall()
        tables = {
            row[0]
            for row in memory.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        return rows, tables

    without, tables_without = dump(tmp_path / "a.sqlite3", pass_store=False)
    explicit, tables_with = dump(tmp_path / "b.sqlite3", pass_store=True)
    assert without == explicit
    assert tables_without == tables_with == {"messages", OWNER_FACTS_TABLE}


def test_a_dual_write_lands_in_both_stores(tmp_path: Path, clock: _Clock) -> None:
    memory = ConversationMemory(tmp_path / "ledger.sqlite3")
    store = SqliteConversationStore(tmp_path / "turns.sqlite3", clock=clock)
    row_id = memory.write_realtime_turn(
        session_id="sess_9",
        speaker="owner",
        text="where are my keys",
        origin="realtime",
        provider_item_id="item_9",
        store=store,
    )
    assert [row["content"] for row in memory.realtime_turns()] == ["where are my keys"]
    stored = store.latest(1)[0]
    assert stored.text == "where are my keys"
    assert stored.session_id == "sess_9"
    assert stored.source == "realtime"
    assert stored.speaker == "owner"
    assert stored.provider_item_id == "item_9"
    assert stored.ts_utc == PINNED
    # The raw origin and the ledger row id survive, so neither store's row is
    # orphaned from the other.
    assert stored.meta == {"origin": "realtime", "ledger_row_id": row_id}
    store.close()


def test_a_local_origin_is_filed_as_a_local_source(tmp_path: Path, clock: _Clock) -> None:
    memory = ConversationMemory(tmp_path / "ledger2.sqlite3")
    store = SqliteConversationStore(tmp_path / "turns2.sqlite3", clock=clock)
    memory.write_realtime_turn(
        session_id=None, speaker="owner", text="typed", origin="panel_text", store=store
    )
    stored = store.latest(1)[0]
    assert stored.source == "local"
    assert stored.meta["origin"] == "panel_text"
    store.close()


class _ExplodingStore:
    """Every method fails. The store from hell, and the turn must survive it."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def append(self, turn: TurnRecord) -> TurnRecord:
        self.calls += 1
        raise self.error

    def by_time_range(self, start_utc: float | None, end_utc: float | None) -> list[TurnRecord]:
        raise self.error

    def by_session(self, session_id: str) -> list[TurnRecord]:
        raise self.error

    def latest(self, n: int = 20) -> list[TurnRecord]:
        raise self.error

    def count(self) -> int:
        raise self.error

    def close(self) -> None:
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        sqlite3.OperationalError("database is locked"),
        RuntimeError("wedged"),
        ValueError("nope"),
        MemoryError("out of memory"),
    ],
)
def test_a_store_failure_never_kills_a_turn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """The S6 detector.

    A conversation ledger that drops turns because a *secondary* store hiccuped
    is worse than no secondary store. The ledger row is committed first and the
    mirror is best-effort — including for errors nobody predicted, which is why
    ``MemoryError`` (not a ``ValueError``, not caught by the lane's own except
    clause) is in this list.
    """

    memory = ConversationMemory(tmp_path / "ledger3.sqlite3")
    store = _ExplodingStore(error)
    with caplog.at_level(logging.WARNING, logger="parcel_robot.memory.store"):
        row_id = memory.write_realtime_turn(
            session_id="s", speaker="owner", text="still here", origin="realtime", store=store
        )
    assert row_id > 0
    assert [row["content"] for row in memory.realtime_turns()] == ["still here"]
    assert store.calls == 1
    assert any("mirror failed" in record.message for record in caplog.records)


def test_an_unmappable_origin_is_logged_and_the_turn_still_lands(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    memory = ConversationMemory(tmp_path / "ledger4.sqlite3")
    store = SqliteConversationStore(tmp_path / "turns4.sqlite3", clock=_Clock())
    with caplog.at_level(logging.WARNING, logger="parcel_robot.memory.store"):
        memory.write_realtime_turn(
            session_id="s", speaker="owner", text="from nowhere", origin="teleport", store=store
        )
    assert [row["content"] for row in memory.realtime_turns()] == ["from nowhere"]
    assert store.count() == 0
    assert any("mirror failed" in record.message for record in caplog.records)
    store.close()


def test_mirror_realtime_turn_returns_none_on_failure() -> None:
    assert (
        mirror_realtime_turn(
            _ExplodingStore(RuntimeError("x")),
            session_id="s",
            speaker="owner",
            text="t",
            origin="realtime",
        )
        is None
    )


def test_a_closed_store_does_not_kill_a_turn(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "ledger5.sqlite3")
    store = SqliteConversationStore(tmp_path / "turns5.sqlite3")
    store.close()
    assert (
        memory.write_realtime_turn(
            session_id="s", speaker="owner", text="survives", origin="realtime", store=store
        )
        > 0
    )


def test_the_ledger_still_refuses_what_it_always_refused(tmp_path: Path) -> None:
    """The interception must not have widened the ledger's own fail-closed gate."""

    memory = ConversationMemory(tmp_path / "ledger6.sqlite3")
    store = SqliteConversationStore(tmp_path / "turns6.sqlite3")
    with pytest.raises(ValueError):
        memory.write_realtime_turn(
            session_id="s", speaker="oracle", text="hi", origin="realtime", store=store
        )
    with pytest.raises(ValueError):
        memory.write_realtime_turn(
            session_id="s", speaker="owner", text="  ", origin="realtime", store=store
        )
    assert store.count() == 0
    store.close()


# ===================================================== the origin -> source map
def test_every_known_origin_maps_to_a_known_source() -> None:
    assert set(ORIGIN_SOURCES.values()) <= SOURCES
    for origin in ORIGIN_SOURCES:
        assert source_for_origin(origin) in SOURCES


def test_an_unmapped_origin_is_refused() -> None:
    with pytest.raises(ConversationStoreError, match="no store source mapped"):
        source_for_origin("browser_push")


def test_every_transcript_origin_the_runtime_can_emit_is_mapped() -> None:
    """Drift guard.

    If a new ``TRANSCRIPT_ORIGIN_*`` constant appears in ``runtime.py``, turns
    from that path would be refused by the mirror and land nowhere. Add the
    origin to ``ORIGIN_SOURCES`` — one line — rather than deleting this test.
    """

    from parcel_robot.runtime import TRANSCRIPT_ORIGINS

    unmapped = set(TRANSCRIPT_ORIGINS) - set(ORIGIN_SOURCES)
    assert not unmapped, f"add these origins to conversation_store.ORIGIN_SOURCES: {unmapped}"


# ==================================================================== backfill
def _ledger_with_history(path: Path) -> ConversationMemory:
    """A ledger holding what R1/R2-C would have written, with pinned times."""

    memory = ConversationMemory(path)
    memory.add("user", "a typed panel command")  # pre-realtime row: never imported
    memory.write_realtime_turn(
        session_id="sess_a",
        speaker="owner",
        text="hello there",
        origin="realtime",
        provider_item_id="item_1",
    )
    memory.write_realtime_turn(
        session_id="sess_a",
        speaker="robot",
        text="hello yourself",
        origin="realtime",
        provider_item_id="item_2",
    )
    # The lane's session markers carry no provider item id at all.
    memory.write_realtime_turn(
        session_id="sess_a",
        speaker="system",
        text="[session rollover]",
        origin="realtime",
    )
    memory.write_realtime_turn(
        session_id="sess_b",
        speaker="owner",
        text="second session",
        origin="realtime",
        provider_item_id="item_3",
    )
    # SQLite stamps CURRENT_TIMESTAMP in UTC; pin it so the assertions are exact.
    for row_id, stamp in enumerate(
        (
            "2026-08-17 09:00:00",
            "2026-08-17 09:00:04",
            "2026-08-17 09:30:00",
            "2026-08-17 10:00:00",
        ),
        start=2,
    ):
        memory.connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?", (stamp, row_id)
        )
    memory.connection.commit()
    return memory


def test_the_backfill_imports_every_hosted_turn_and_nothing_else(
    store: ConversationStore, tmp_path: Path
) -> None:
    memory = _ledger_with_history(tmp_path / "history.sqlite3")
    result = import_realtime_turns(memory, store)
    assert result.as_dict() == {"scanned": 4, "imported": 4, "duplicates": 0, "refused": 0}
    texts = [row.text for row in store.latest(10)]
    assert texts == ["hello there", "hello yourself", "[session rollover]", "second session"]
    assert "a typed panel command" not in texts


def test_the_backfill_is_idempotent_by_provider_item_id(
    store: ConversationStore, tmp_path: Path
) -> None:
    """The card's requirement: a re-import adds zero rows."""

    memory = _ledger_with_history(tmp_path / "history2.sqlite3")
    first = import_realtime_turns(memory, store)
    before = store.count()
    second = import_realtime_turns(memory, store)
    assert first.imported == 4
    assert second.imported == 0
    assert second.duplicates == 4
    assert store.count() == before


def test_the_backfill_de_duplicates_id_less_system_markers_too(
    store: ConversationStore, tmp_path: Path
) -> None:
    """Dropping them would be lossy; importing them twice would be wrong."""

    memory = _ledger_with_history(tmp_path / "history3.sqlite3")
    import_realtime_turns(memory, store)
    import_realtime_turns(memory, store)
    markers = [row for row in store.latest(20) if row.speaker == "system"]
    assert len(markers) == 1


def test_the_backfill_preserves_the_original_instants(
    store: ConversationStore, tmp_path: Path
) -> None:
    """A migration that filed a year of history under today defeats the point."""

    memory = _ledger_with_history(tmp_path / "history4.sqlite3")
    import_realtime_turns(memory, store)
    stamps = [row.iso_utc() for row in store.latest(10)]
    assert stamps == [
        "2026-08-17T09:00:00+00:00",
        "2026-08-17T09:00:04+00:00",
        "2026-08-17T09:30:00+00:00",
        "2026-08-17T10:00:00+00:00",
    ]


def test_the_backfill_produces_the_same_record_the_dual_write_would_have(
    tmp_path: Path, clock: _Clock
) -> None:
    """Live mirror and backfill must be indistinguishable apart from stamping.

    That is what makes the backfill safe to run over a database that has been
    dual-writing all along.
    """

    mirrored = SqliteConversationStore(tmp_path / "live.sqlite3", clock=clock)
    imported = SqliteConversationStore(tmp_path / "back.sqlite3", clock=clock)
    memory = ConversationMemory(tmp_path / "both.sqlite3")
    memory.write_realtime_turn(
        session_id="sess_a",
        speaker="owner",
        text="hello there",
        origin="realtime",
        provider_item_id="item_1",
        store=mirrored,
    )
    import_realtime_turns(memory, imported)

    live_row, back_row = mirrored.latest(1)[0], imported.latest(1)[0]
    comparable = ("session_id", "source", "speaker", "text", "provider_item_id", "meta")
    assert {f: getattr(live_row, f) for f in comparable} == {
        f: getattr(back_row, f) for f in comparable
    }
    mirrored.close()
    imported.close()


def test_the_backfill_can_be_scoped_to_one_session(
    store: ConversationStore, tmp_path: Path
) -> None:
    memory = _ledger_with_history(tmp_path / "history5.sqlite3")
    result = import_realtime_turns(memory, store, session_id="sess_b")
    assert result.imported == 1
    assert [row.text for row in store.latest(10)] == ["second session"]


def test_the_backfill_refuses_rather_than_guesses_an_unmapped_origin(
    store: ConversationStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    memory = ConversationMemory(tmp_path / "history6.sqlite3")
    memory.write_realtime_turn(
        session_id="s", speaker="owner", text="from nowhere", origin="teleport"
    )
    with caplog.at_level(logging.WARNING, logger="parcel_robot.memory.store"):
        result = import_realtime_turns(memory, store)
    assert result.as_dict() == {"scanned": 1, "imported": 0, "duplicates": 0, "refused": 1}
    assert store.count() == 0
    assert any("backfill refused" in record.message for record in caplog.records)


def test_the_backfill_refuses_a_row_with_no_parseable_timestamp(
    store: ConversationStore, tmp_path: Path
) -> None:
    """No fabricated instants. A row with no honest time is left behind."""

    memory = ConversationMemory(tmp_path / "history7.sqlite3")
    memory.write_realtime_turn(
        session_id="s", speaker="owner", text="when?", origin="realtime", provider_item_id="i"
    )
    memory.connection.execute("UPDATE messages SET created_at = 'sometime'")
    memory.connection.commit()
    result = import_realtime_turns(memory, store)
    assert result.refused == 1
    assert store.count() == 0


def test_the_backfill_on_an_empty_ledger_does_nothing(
    store: ConversationStore, tmp_path: Path
) -> None:
    memory = ConversationMemory(tmp_path / "empty.sqlite3")
    assert import_realtime_turns(memory, store) == ImportResult()


def test_a_dual_written_turn_is_not_imported_twice(
    store: ConversationStore, tmp_path: Path, clock: _Clock
) -> None:
    """The realistic migration: some turns are already mirrored, some are not."""

    memory = ConversationMemory(tmp_path / "mixed.sqlite3")
    memory.write_realtime_turn(
        session_id="s",
        speaker="owner",
        text="mirrored live",
        origin="realtime",
        provider_item_id="item_live",
        store=store,
    )
    memory.write_realtime_turn(
        session_id="s",
        speaker="robot",
        text="written before the store existed",
        origin="realtime",
        provider_item_id="item_old",
    )
    memory.connection.execute("UPDATE messages SET created_at = '2026-08-17 09:00:00'")
    memory.connection.commit()

    result = import_realtime_turns(memory, store)
    assert result.imported == 1
    assert result.duplicates == 1
    assert sorted(row.text for row in store.latest(10)) == [
        "mirrored live",
        "written before the store existed",
    ]


# ============================================================ timestamp parsing
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-08-17 09:00:00", "2026-08-17T09:00:00+00:00"),
        ("2026-08-17 09:00:00.500", "2026-08-17T09:00:00.500000+00:00"),
        ("2026-08-17T09:00:00", "2026-08-17T09:00:00+00:00"),
        ("2026-08-17T09:00:00+02:00", "2026-08-17T07:00:00+00:00"),
    ],
)
def test_sqlite_timestamps_are_read_as_utc_not_local(value: str, expected: str) -> None:
    """SQLite's ``CURRENT_TIMESTAMP`` is UTC and carries no suffix saying so.

    A naive parse attached to the machine's local zone would shift every
    imported row by the developer's timezone offset.
    """

    parsed = parse_sqlite_utc(value)
    assert parsed is not None
    assert (
        TurnRecord(
            session_id=None, source="realtime", speaker="owner", text="x", ts_utc=parsed
        ).iso_utc()
        == expected
    )


@pytest.mark.parametrize("value", ["", "   ", "sometime", None, object()])
def test_an_unparseable_timestamp_is_none_not_a_guess(value: Any) -> None:
    assert parse_sqlite_utc(value) is None


def test_a_numeric_timestamp_is_taken_as_epoch_seconds() -> None:
    assert parse_sqlite_utc(PINNED) == PINNED
