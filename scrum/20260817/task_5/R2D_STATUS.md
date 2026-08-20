# R2-D — conversation store (raw turns, timestamp-indexed, swappable)

**Date:** 2026-08-17 · **Card:** `scrum/20260817/task_5` · **Executor:** Claude Opus
**Auditor:** Fable · **Baseline:** `877d9f4` ("Implemented voice agent") + three other
sessions' uncommitted work, all untouched
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Owner directive:** *"Build an internal database that can hold raw previous
conversations indexed by timestamp. Storage design is subject to change."*

## What landed, in one paragraph

A `ConversationStore` **Protocol** — six methods, no base class — plus one
SQLite implementation behind it, and a 168-test conformance suite that runs
against the *Protocol* and is parametrized over **two** implementations: the
shipped `SqliteConversationStore` and a fifty-line `ToyConversationStore` made
of a Python list that exists only in the test file. That second implementation
is the entire "subject to change" guarantee, executable. The SQLite backend owns
a **new** table `conversation_turns` (the `messages` table gains zero bytes),
runs in WAL, and carries explicit `ts_utc` and `(session_id, ts_utc)` indexes
that a test proves are *chosen* by the query planner, not merely present.
`memory.py` gained exactly one additive interception — `write_realtime_turn`'s
optional `store=` dual-write, default `None` ⇒ byte-identical — and a
Protocol-generic, idempotent backfill migrates rows R1/R2-C already wrote.
**Nothing reads the store yet; `runtime.py` was not touched; the live
`parcel_memory.sqlite3` was never opened; nothing committed.**

## Files

| File | Lines | What |
| --- | --- | --- |
| `src/parcel_robot/conversation_store.py` | 764 | `ConversationStore` Protocol, `TurnRecord`, `SqliteConversationStore`, `mirror_realtime_turn`, `import_realtime_turns` |
| `tests/test_conversation_store.py` | 1167 | 168 tests — conformance suite × 2 implementations, SQLite specifics, the memory seam, the backfill |
| `src/parcel_robot/memory.py` | **+29 / −1** | one optional kwarg, one import, one dual-write call, docstring |
| `scrum/20260817/task_5/R2D_STATUS.md` | this file | |

`git diff --numstat src/parcel_robot/memory.py` reads `29 1`. Of those 29, **13
are docstring** and 2 are a comment; the executable change is the import line,
the `store: ConversationStore | None = None` parameter, and a six-line
`mirror_realtime_turn(...)` call guarded by `if store is not None`. The single
deleted line is `return int(cursor.lastrowid or 0)`, which became `row_id =
int(cursor.lastrowid or 0)` inside the lock and `return row_id` after it — see
"the mirror runs outside the lock" below. No other pre-existing file was
touched.

## Frozen contract surface

**Protocol.** `ConversationStore` (`runtime_checkable`): `append(turn) ->
TurnRecord`, `by_time_range(start_utc, end_utc) -> list[TurnRecord]`,
`by_session(session_id)`, `latest(n=20)`, `count()`, `close()`.

**Record.** `TurnRecord` — frozen, **keyword-only** dataclass:
`session_id: str | None`, `source` ∈ `SOURCES = {realtime, local, corpus}`,
`speaker` ∈ `SPEAKERS = {owner, robot, system}`, `text` (non-empty),
`provider_item_id: str | None`, `meta: Mapping` (JSON round-trippable),
`ts_utc: float | None`, `seq: int | None`. `.meta_json` is the canonical
serialization, `.stamped(ts_utc=, seq=)` returns the stored copy, `.iso_utc()`
renders at read time. Every constraint is enforced in `__post_init__`, so an
invalid turn cannot exist — in memory or on disk.

**Backend.** `SqliteConversationStore(path=":memory:", *, clock=utc_now)`.
Table `conversation_turns`; indexes `idx_conversation_turns_ts`,
`idx_conversation_turns_session_ts`, `idx_conversation_turns_item`;
`.journal_mode`, `.connection`, `.path` public;
`.query_plan(kind)` for `{time_range, start_only, session, latest}`.
`open_store(path, *, clock=)` is the one construction site to change when the
backend changes.

**Seam.** `mirror_realtime_turn(store, *, session_id, speaker, text, origin,
provider_item_id=None, ledger_row_id=None) -> TurnRecord | None` — never
raises. `source_for_origin(origin)` is the only bridge from the ledger's
free-form `origin` to the store's closed `source`, via `ORIGIN_SOURCES =
{realtime: realtime, mic: local, panel_text: local, corpus: corpus}`.

**Backfill.** `import_realtime_turns(memory, store, *, session_id=None,
limit=100_000) -> ImportResult(scanned, imported, duplicates, refused)`.

**Helpers.** `utc_now()`, `canonical_meta_json(meta)`, `parse_sqlite_utc(value)`.

## The design points, and where each is proven

### 1. The Protocol is the deliverable; the schema is not

The card reads "storage design is subject to change" as a seam requirement, and
a seam only exists if more than one thing fits it. `ToyConversationStore` —
`self._rows: list[TurnRecord]`, `sorted(...)`, no SQL, no `sqlite3` import —
implements the same six methods, and **every test taking the `store` fixture
runs against both**. pytest shows the pairs as `[sqlite]` and `[toy]`:

```
$ .parcel/bin/python -m pytest tests/test_conversation_store.py -q --no-header \
    -k "range or latest or session or meta" --collect-only | head -4
tests/test_conversation_store.py::test_a_session_id_may_be_absent_but_not_a_number
tests/test_conversation_store.py::test_meta_round_trips_byte_exact_through_storage[sqlite]
tests/test_conversation_store.py::test_meta_round_trips_byte_exact_through_storage[toy]
tests/test_conversation_store.py::test_canonical_meta_is_stable_regardless_of_key_order

$ ... --collect-only -q | grep -c "\[sqlite\]"   ->  37
$ ... --collect-only -q | grep -c "\[toy\]"      ->  37
```

**74 of the 168 tests are the parametrized conformance suite — 37 properties ×
2 implementations, each pair byte-identical in what it asserts.** The remaining
94 are SQLite specifics, the `memory.py` seam, `TurnRecord` validation and the
timestamp parser. `test_the_conformance_suite_runs_against_more_than_one_
implementation` asserts the guarantee directly, and `test_the_toy_store_is_not_
a_database` reads this file's own source and refuses to let the toy quietly
grow a `sqlite3` import — a toy that became a second SQLite store would prove
nothing.

The SQLite-only tests (query plans, WAL, the additive-table check) are
quarantined in their own section, because a future backend owes the conformance
suite and not those.

### 2. The index is *used*, not merely present

The card asked for `EXPLAIN QUERY PLAN`, not `SELECT ... FROM sqlite_master`,
and the difference is the point: an index that exists but is never chosen is
decoration. `query_plan(kind)` runs `EXPLAIN QUERY PLAN` over **the store's own
query strings** — the same `_range_query()` / `_SESSION_SQL` / `_LATEST_SQL` the
readers execute — so the proof cannot drift away from the code it claims to
prove. Over a 200-row table:

```
time_range  SEARCH conversation_turns USING INDEX idx_conversation_turns_ts (ts_utc>? AND ts_utc<?)
start_only  SEARCH conversation_turns USING INDEX idx_conversation_turns_ts (ts_utc>?)
session     SEARCH conversation_turns USING INDEX idx_conversation_turns_session_ts (session_id=?)
latest      SCAN conversation_turns USING INDEX idx_conversation_turns_ts
```

The tests assert `SEARCH` (not `SCAN`) for the range query, the composite index
for the session query, and **no `USE TEMP B-TREE FOR ORDER BY`** on the tail
read — the tail walks the timestamp index instead of filesorting. Seeds S1 and
S8 drop one index each and both redden.

### 3. Ranges are half-open, and that is a decision with a reason

`start_utc <= ts_utc < end_utc`. Not a convention — a requirement of
composition: consecutive windows `[t0,t1)`, `[t1,t2)` partition the timeline
exactly once. `test_consecutive_windows_partition_the_timeline_exactly_once`
asserts both halves (`len(first) + len(second) == store.count()` **and** the two
`seq` sets are disjoint), which a closed-closed range fails on both counts. Both
bounds accept `None`; a zero-width window is empty; a backwards range is
**refused** rather than silently returning nothing. Seed S5 flips `<` to `<=`
and reddens.

### 4. Time is injected, and ordering survives a frozen clock

`ts_utc` is a UTC epoch float from an injected clock; the default `utc_now()`
goes through `datetime.now(timezone.utc)` so the UTC claim is in the code rather
than a comment, and a test asserts it agrees with `time.time()`. A fixed clock
produces a pinned instant *and* a pinned rendering
(`1_700_000_000.0` → `"2023-11-14T22:13:20+00:00"`), which is what makes seed S2
— reading `datetime.now()` instead of `self._clock()` — redden inside the same
test run rather than at some future midnight.

**The frozen clock is also the adversarial case, not a convenience.** Under it,
consecutive turns share a `ts_utc` exactly, so an ordering keyed on timestamps
alone is non-deterministic. Every read therefore orders by `(ts_utc, seq)`.
`test_latest_is_deterministic_under_a_frozen_clock` is the guard and seed S9
(tiebreak reversed) reddens it. A broken clock returning `NaN` is refused before
anything is written, not stored as garbage.

### 5. Meta round-trips byte-exact — enforced by refusing what would not

Storage is canonical JSON (`sort_keys`, no spaces, `ensure_ascii=False`,
`allow_nan=False`). The test asserts more than equality: `read_back.meta_json ==
stored.meta_json == canonical_meta_json(meta)` over nested dicts, lists, `None`,
floats and `"안녕하세요 — café ☕"`.

The stronger half is the refusal. A tuple silently becomes a list and an `int`
key silently becomes a string, so `__post_init__` performs the round trip and
**rejects any mapping that does not come back identical** — tuples, int keys,
sets, `NaN`, `Infinity`, arbitrary objects, non-mappings. A store whose reads do
not return what its writes were given is worse than no store. Seed S4 (`str()`
instead of JSON) reddens.

### 6. The interception point is `memory.py`, and its default is byte-identical

`runtime.py` is owned by the concurrent R1.6 executor, so the wiring point is
the ledger writer itself. `store=None` is not just "the default" —
`test_the_default_store_is_none_and_behaviour_is_byte_identical` writes the same
three turns into two databases, one calling `write_realtime_turn` exactly as
every existing call site does and one passing `store=None` explicitly, then
compares the **full `messages` row dump** and the `sqlite_master` table list.
Identical, and neither database grew a table. The 65 pre-existing ledger tests in
`tests/test_realtime_lane.py` are unchanged and green.

**The mirror runs outside the lock.** The ledger row is committed inside
`self._lock`; the mirror is attempted after the `with` block. A slow or wedged
secondary store must not hold the writer that every hosted turn queues behind.
This is the one line that moved (`return` → `row_id = ...` + `return row_id`).

### 7. A turn never dies because storage hiccuped

`mirror_realtime_turn` catches **`Exception`**, not a tuple of expected types,
and logs a warning. `test_a_store_failure_never_kills_a_turn` is parametrized
over `sqlite3.OperationalError("database is locked")`, `RuntimeError`,
`ValueError` and **`MemoryError`** — the last deliberately, because it is *not*
a `ValueError` and would not be caught by `lane._write_ledger`'s own
`except (RuntimeError, TypeError, ValueError)`. In every case the ledger row is
present, the row id is returned, and the warning is on the record. A closed
store and an unmappable origin are covered too. Seed S6 narrows the except
clause and reddens.

Separately, `ConversationStoreError` subclasses `ValueError` on purpose, so a
store wired in behind the lane later inherits the lane's existing never-kill-a-
turn clause without editing an audited module.

### 8. The backfill is idempotent, Protocol-generic, and does not invent time

`import_realtime_turns` de-duplicates by `provider_item_id` — the card's
requirement — and by the natural key `(session_id, speaker, text, ts_utc)` for
rows that have none, because **every `system` marker the lane writes carries
`item_id=None`** (rollover notes, session summaries) and dropping them would
make the backfill lossy. Re-import adds zero rows; the markers stay at one copy.

It is written against the Protocol (`store.count()` + `store.latest(n)` to read
the existing key set, `store.append` to write), so it backfills into *any*
backend — and the backfill tests run under both implementations, like the rest.
It is O(rows) per pass, correct for a one-shot migration and not used on a hot
path.

Timestamps come from `messages.created_at`, which SQLite stamps in **UTC** with
no suffix saying so. `parse_sqlite_utc` attaches UTC rather than the machine's
local zone; seed S10 makes it local and reddens (this machine is `EDT`). A row
whose `created_at` cannot be parsed is **refused**, not given a fabricated
instant — a migration that filed a year of conversation under today's date
would defeat the entire point of a timestamp-indexed store.

Live mirror and backfill produce **identical records apart from stamping**
(`test_the_backfill_produces_the_same_record_the_dual_write_would_have`), which
is what makes the backfill safe to run over a database that has been
dual-writing all along; `test_a_dual_written_turn_is_not_imported_twice` runs
that mixed case end to end.

### 9. Vocabularies are closed, and agree with the ledger's

`source` and `speaker` are refused, not coerced — including `"user"` and
`"assistant"`, which are the *`messages`* table's vocabulary and not this one.
`test_the_speaker_vocabulary_matches_the_ledger_s` asserts
`set(memory._SPEAKER_ROLES) == SPEAKERS`, because two ledgers that disagree
about who is speaking make any future migration between them guesswork.

`test_every_transcript_origin_the_runtime_can_emit_is_mapped` imports
`runtime.TRANSCRIPT_ORIGINS` (read-only; `runtime.py` was not edited) and
asserts every origin has a `source` mapping. If R1.6 or a later card adds a
transcript origin, this reddens with the fix in the message — one line in
`ORIGIN_SOURCES` — instead of turns from that path silently landing nowhere.

### 10. Fail-closed on the way out, too

`_row_to_record` builds a `TurnRecord`, so a hand-corrupted row reddens on
**read** rather than returning a lie.
`test_a_corrupted_row_reddens_on_read_rather_than_returning_a_lie` states this
explicitly so it is a decision on the record and not a surprise in production.

## Gate table

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-18T03:29:51Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.37s
[  PASS] HARD  release-parity-integrity   10 passed in 0.78s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.54s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              6035 passed, 9 skipped, 41 deselected, 5 warnings in 234.86s (0:03:54)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 247.7s
```

### The first gate run, and why it was red (not this card)

An earlier run at `03:24:40Z` reported `default-suite  7 failed, 6028 passed`,
**all seven in `tests/test_realtime_corpus_replay.py`** — R2-C's file, not this
card's. The live corpus scrape finished during that run and its owner landed 25
scraped fixtures, a regenerated `corpus.manifest.json` (mtime `23:23:30`) and an
adapted test file (mtime `23:24:02`) **while the default suite was already
executing**, so pytest had collected the pre-scrape tests (three hand-authored
seeds, zero billing data) against post-scrape fixtures. The failures name that
transition exactly: `test_three_seed_fixtures_exist_and_span_the_three_shapes`,
five `test_billing_data_matches_fixture_provenance[rt-conv-02x]`, and
`test_a_navigate_to_proposal_is_answered_by_the_r1_refusal_stub`. That test name
no longer exists in the file. Per the card's scrape-wait rule the tree was left
to settle — `tests/test_realtime_corpus_replay.py` alone then read
`151 passed` — and the gate was re-run clean. Nothing in this card touches
`evals/`, and the corpus suite imports neither `conversation_store` nor
`write_realtime_turn`.

## Seeded-failure table

`<scratchpad>/seed_r2d.py` (session scratchpad, never the repo) mutates one
shipped file per seed, runs the tests that own the property with `-x`, and
restores the original bytes in a `finally` block. `git status --short` before
and after the whole run is byte-identical, and the clean suite is re-run at the
end.

| # | Seeded defect | Result | First failing test |
| --- | --- | --- | --- |
| S1 | `ts_utc` index never created | **RED** 1 failed | `test_the_time_range_query_uses_the_timestamp_index` |
| S2 | naive wall clock instead of the injected UTC clock | **RED** 1 failed, 2 passed | `test_a_fixed_injected_clock_produces_a_pinned_timestamp[sqlite]` |
| S3 | unknown `source` accepted instead of refused | **RED** 1 failed, 6 passed | `test_an_unknown_source_is_refused_not_coerced[Realtime]` |
| S4 | meta stringified with `str()` instead of JSON | **RED** 1 failed | `test_meta_round_trips_byte_exact_through_storage[sqlite]` |
| S5 | range end made inclusive (boundary off-by-one) | **RED** 1 failed | `test_a_range_is_inclusive_of_its_start_and_exclusive_of_its_end[sqlite]` |
| S6 | store exception escapes `write_realtime_turn` | **RED** 1 failed, 2 passed | `test_a_store_failure_never_kills_a_turn[error0]` |
| S7 | backfill stops de-duplicating | **RED** 1 failed, 4 passed | `test_the_backfill_is_idempotent_by_provider_item_id[sqlite]` |
| S8 | `(session_id, ts_utc)` composite index never created | **RED** 1 failed, 1 passed | `test_the_session_query_uses_the_composite_index` |
| S9 | `latest()` tiebreak reversed | **RED** 1 failed, 4 passed | `test_latest_is_deterministic_under_a_frozen_clock[sqlite]` |
| S10 | `created_at` parsed as local time instead of UTC | **RED** 1 failed, 6 passed | `test_the_backfill_preserves_the_original_instants[sqlite]` |

10 seeds, 10 RED. The card asked for six (S1–S6); S7–S10 cover the backfill's
idempotence, the second index, the frozen-clock tiebreak and the UTC parse —
each cheap and each a real way this could rot.

```
=== tree restored: YES ===
clean: PASS :: 168 passed, 2 warnings in 0.43s
```

Note S5 reddens the `[sqlite]` parametrization only — `ToyConversationStore`
has its own range logic and is unaffected. That is the two implementations
being genuinely independent rather than one delegating to the other, which is
what makes the conformance suite worth anything.

## Test runs

```
$ .parcel/bin/python -m pytest tests/test_conversation_store.py -q
168 passed, 2 warnings in 0.55s
```

```
$ .parcel/bin/python -m pytest tests/test_realtime_lane.py tests/test_tiered_memory.py \
    tests/test_realtime_protocol.py tests/test_realtime_ingress.py tests/test_runtime.py \
    tests/test_agent.py tests/test_fixa_transcript_persistence.py \
    tests/test_fixa_mic_arming.py tests/test_duplex_integration.py -q
306 passed, 3 warnings in 10.38s
```

```
$ .parcel/bin/python -m ruff check src/parcel_robot/conversation_store.py \
    src/parcel_robot/memory.py tests/test_conversation_store.py
All checks passed!
```

Both new files are also `ruff format`-clean. `memory.py` was **not**
reformatted; it was already format-clean and stayed that way.

The two warnings in this card's suite are the pre-existing
`ROBOT_FOOTPRINT_RADIUS_M` deprecation, raised by importing `runtime` inside
the single origin drift-guard test. Not introduced here.

## Deviations, and why

| # | Deviation | Reason |
| --- | --- | --- |
| 1 | `TurnRecord` carries a `seq` field the card did not name | A fixed injected clock makes consecutive turns share `ts_utc` exactly, so `latest(n)` and every ordered read would be non-deterministic without a tiebreak — under precisely the condition every test runs in. `seq` is storage-neutral (the toy assigns 1,2,3…), so it belongs on the Protocol rather than being a SQLite `rowid` leaking upward. |
| 2 | `ts_utc` is optional on `TurnRecord` (`None` = "stamp me") | The card puts the clock in the store and `append(turn)` in the Protocol; something has to represent an unstamped turn. `append` returns a stamped copy and leaves the caller's frozen record alone. A pre-stamped turn keeps its instant, which is what makes the backfill possible at all. |
| 3 | The backfill reads `messages.created_at` directly, not only `realtime_turns()` | `realtime_turns()` does not project a timestamp, so a backfill built on it alone would stamp every historical row with the import-time clock. `realtime_turns()` is still the row source of truth — its `speaker IS NOT NULL` filter is load-bearing — and one extra query fetches only the missing column for the ids it already returned. |
| 4 | De-duplication also uses a natural key, not `provider_item_id` alone | Every `system` marker the lane writes carries `item_id=None`. Keying on the item id alone would either drop them (lossy) or duplicate them on every re-import (not idempotent). |
| 5 | `ITEM_INDEX` on `provider_item_id` is **not** UNIQUE | `lane._on_owner_transcript` re-ledgers the same transcript with the same `item_id` when the ingress refuses it (lane.py:676 / lane.py:686). A unique constraint would turn that into a raised exception on the hot turn path; de-duplication is an explicit concern of the backfill instead. Asserted by `test_the_item_index_is_not_unique`. |
| 6 | A fourth `source`/origin value, `corpus`, is mapped although nothing emits it | The card's own vocabulary includes `corpus` and the eval pack replays fixtures through the real lane. Mapping it costs one dict entry and stops the first corpus replay that wires a store from being refused. |
| 7 | Ten seeded failures instead of six | S1–S6 are the card's. S7–S10 cover the backfill's idempotence, the composite index, the ordering tiebreak and the UTC parse. |
| 8 | One test imports `parcel_robot.runtime` | The origin→source drift guard needs `TRANSCRIPT_ORIGINS`. This is a read-only import; `runtime.py` was not created, edited, formatted or linted by this card. |
| 9 | `memory.py`'s diff moved one existing line | `return int(cursor.lastrowid or 0)` had to leave the `with self._lock` block so the mirror does not run while holding the ledger writer's lock. Behaviour is unchanged and pinned by the byte-identical test. |

## does_not_prove

* **No consumer reads this store.** The lane's history injection still calls
  `ConversationMemory.realtime_turns`, and `runtime.py` never constructs a
  store. Nothing in the shipped product would notice if this table stayed empty
  forever. Re-pointing consumers is the follow-up card, once R1.6 lands and
  `runtime.py` is free.
* **The dual-write has no production call site.** `write_realtime_turn(store=…)`
  is exercised only by this card's tests. Every real caller — `lane._write_ledger`
  and `runtime.py:4436` — passes no store and therefore takes the unchanged
  path. What is proven is that the seam works and that the default is inert.
* **The live `parcel_memory.sqlite3` was never opened, read, written or
  migrated.** Every test uses `tmp_path` or `:memory:`. The backfill has
  therefore never run against real data, and the only ledgers it has been
  pointed at are ones these tests created seconds earlier.
* **No concurrency claim.** The one-writer discipline is an `RLock` plus WAL,
  matching `ConversationMemory`. No test runs two threads, no test runs two
  processes, and nothing here has observed a `database is locked` in anger —
  `sqlite3.OperationalError` appears only as an *injected* failure proving the
  mirror swallows it.
* **No performance claim.** The query-plan tests prove the planner *chooses* the
  index over a 200-row table. Nothing here has been timed, and nothing has been
  run at a size where the index matters. "Timestamp-indexed" is proven as a
  structural property, not a latency one.
* **`ToyConversationStore` is not a candidate backend.** It is evidence that the
  Protocol is implementable twice. It has no persistence, no concurrency story
  and no size limit; nobody should ship it.
* **The conformance suite is not exhaustive.** It states the semantics this
  card thought of. A backend could pass all 59 conformance tests and still
  differ in transactionality, ordering under concurrent appends, or behaviour
  when `close()` races a read — none of which the suite touches.
* **The `origin → source` map is only as complete as `runtime.py` is today.**
  The drift guard catches a new `TRANSCRIPT_ORIGIN_*` constant. It does **not**
  catch a caller passing a literal origin string that never became a constant.
* **`meta` is validated, not schema'd.** Any JSON-round-trippable mapping is
  accepted. There is no registry of meta keys, so two writers can disagree
  about what `meta["origin"]` means and nothing will notice.
* **The refusal-on-read decision is untested against real corruption.** The
  corrupted-row test writes a bad `speaker` by hand. What a *partially written*
  or torn row does has not been examined.

## Handoffs

* **R2/R3 — a reader.** The first real consumer should replace
  `memory.realtime_turns(limit=N)` at `runtime.py:1152` / `:1164` with
  `store.latest(N)` or `store.by_time_range(...)`. `TurnRecord` carries strictly
  more than the dict those return.
* **R1.6 / whoever frees `runtime.py`** — construct the store next to
  `ConversationMemory` (`runtime.py:962`) with `open_store(path)` and pass it as
  `store=` at `runtime.py:4436` and into `RealtimeLane`'s ledger. That is the
  whole wiring, and it is two lines plus a config key.
* **Owner — a store path.** `configs/robot.yaml` is hash-locked and was **not**
  edited. A `memory.conversation_store_path` key (or reusing the existing
  `memory.path` directory) is an owner decision with a re-freeze attached.
  Until one exists, `open_store` has no configured location.
* **Whoever runs the backfill first.** `import_realtime_turns(memory, store)`
  against the live database is a one-way action on a fresh store file; run it
  against a copy first and check `ImportResult.refused` before trusting the
  result. Refusals are logged with the `messages` row id.
* **A future backend author.** Make it pass
  `tests/test_conversation_store.py` with one line added to
  `STORE_IMPLEMENTATIONS` and a branch in the `store` fixture. If a conformance
  test needs changing to accommodate a backend, that is a semantics change and
  belongs in a card, not in a fixture.

## OWNS compliance

`git status --short` after the full run:

```
 M requirements-lock.txt
 M src/parcel_robot/memory.py
 M src/parcel_robot/realtime/protocol.py
 M src/parcel_robot/runtime.py
 M tests/test_realtime_protocol.py
?? evals/companion/realtime_convo_v1/
?? live_stream.json
?? scrum/20260817/
?? src/parcel_robot/conversation_store.py
?? src/parcel_robot/realtime/prompting.py
?? src/parcel_robot/realtime/ws_transport.py
?? tests/test_conversation_store.py
?? tests/test_realtime_corpus_replay.py
?? tests/test_realtime_live.py
?? tests/test_realtime_prompting.py
?? tests/test_realtime_ws_transport.py
```

From this card: ` M src/parcel_robot/memory.py`,
`?? src/parcel_robot/conversation_store.py`,
`?? tests/test_conversation_store.py`, and `scrum/20260817/task_5/`.

Everything else belongs to the three concurrent actors and was **not**
read-modified, staged, reverted, formatted, linted or committed here:
`runtime.py`, `realtime/protocol.py`, `test_realtime_protocol.py`,
`realtime/prompting.py`, `realtime/ws_transport.py`, `test_realtime_live.py`,
`test_realtime_ws_transport.py`, `test_realtime_corpus_replay.py`,
`requirements-lock.txt`, `live_stream.json`, and all of
`evals/companion/realtime_convo_v1/`. `src/parcel_robot/ui/`, `web_panel.py`,
`realtime/audio_gateway.py`, `browser_sink.py`, `configs/robot.yaml`,
`pyproject.toml`, `scripts/ci_gate.py` and `tools/` gained **zero bytes**.

`parcel_memory.sqlite3` — the live database — was never opened; its mtime is
still `2026-08-16 14:18:49`, a day before this card began. Nothing was
committed, staged or stashed.
