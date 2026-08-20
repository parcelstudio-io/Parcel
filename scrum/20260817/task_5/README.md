# Task 5 — R2-D: conversation store (raw turns, timestamp-indexed, swappable)

**Date:** 2026-08-17 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Owner directive:** "Build an internal database that can hold raw previous
conversations indexed by timestamp. Storage design is subject to change."

## Design reading of the directive

"Subject to change" means the deliverable is a **seam plus one implementation**,
not a schema commitment: a `ConversationStore` Protocol with conformance tests
any future backend must pass (Postgres, vector store, whatever comes), and a
SQLite implementation behind it today. "Raw" means full-fidelity turn records —
text as spoken/heard plus provenance and metadata — never distilled summaries
(those are TieredMemory's job, a different consumer).

## Scope — OWNS

- `src/parcel_robot/conversation_store.py` (NEW — top-level, NOT under
  `realtime/`: the store will eventually hold local-lane and corpus turns too).
  - `ConversationStore` Protocol: `append(turn) -> TurnRecord`,
    `by_time_range(start_utc, end_utc)`, `by_session(session_id)`,
    `latest(n)`, `count()`, `close()`.
  - `TurnRecord` frozen dataclass: `ts_utc` (float, injectable clock),
    `session_id`, `source` (closed vocabulary: `realtime | local | corpus` —
    unknown refused), `speaker` (`owner | robot | system`), `text`,
    `provider_item_id`, `meta` (JSON-serializable mapping, round-tripped
    byte-exact). Timestamps are UTC floats at write time; render at read time.
  - `SqliteConversationStore`: own table `conversation_turns` (additive — the
    existing `messages` table is untouched), WAL, **explicit index on
    `ts_utc`** plus `(session_id, ts_utc)`; a test asserts the query plan uses
    the index (`EXPLAIN QUERY PLAN`), not just that the index exists.
  - One writer discipline (the repo's ledger rule); reads from anywhere.
  - `import_realtime_turns(memory)` helper migrating existing
    `memory.realtime_turns()` rows in (idempotent by `provider_item_id`).
- `src/parcel_robot/memory.py` — ONE additive interception:
  `write_realtime_turn` gains an optional `store: ConversationStore | None`
  dual-write (default None ⇒ byte-identical behavior). This is the wiring
  point precisely because `runtime.py` is OWNED BY THE CONCURRENT R1.6
  EXECUTOR right now — do not touch runtime.py at all this card.
- `tests/test_conversation_store.py`: conformance suite written against the
  **Protocol** (parametrizable over implementations — the "subject to change"
  guarantee), plus SQLite specifics: index-used proof, UTC discipline (a
  fixed injected clock produces pinned timestamps), meta round-trip including
  nested/unicode, range queries at boundaries (inclusive start, exclusive
  end — document the choice), refusal of unknown source/speaker, store
  failure never raises out of `write_realtime_turn` (same never-kill-a-turn
  rule the ledger writer has), idempotent re-import.
- `scrum/20260817/task_5/R2D_STATUS.md` — the register.

## MUST NOT TOUCH

`src/parcel_robot/runtime.py` (R1.6 executor owns it right now),
`src/parcel_robot/realtime/**` (audited or in-flight),
`src/parcel_robot/ui/**`, `web_panel.py` (R1.6),
`configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`, `evals/**`
(the corpus scrape is RUNNING in this checkout — treat
`evals/companion/realtime_convo_v1/fixtures/` and its manifest as volatile
and read-only), `tools/`, anything uncommitted from other cards beyond the one
`memory.py` interception. Never commit/stage/stash.

## Seeded failures (minimum 6)

| # | Defect | Expected RED |
| --- | --- | --- |
| S1 | ts index dropped | query-plan test |
| S2 | naive local time written instead of UTC injected clock | timestamp pin |
| S3 | unknown `source` accepted | vocabulary test |
| S4 | meta not round-tripped (str() instead of JSON) | round-trip test |
| S5 | range boundary off-by-one | boundary test |
| S6 | store exception escapes `write_realtime_turn` | never-kill-a-turn test |

## Definition of done

Full `ci_gate --tier commit` green; seeds RED then restored; the conformance
suite demonstrably runs against the Protocol (a second in-memory toy impl in
the test file passing the same suite is the proof); status doc honest that no
consumer reads the store yet (DI history still reads `memory.realtime_turns`;
re-pointing consumers is the follow-up card once R1.6 lands and runtime.py is
free).
