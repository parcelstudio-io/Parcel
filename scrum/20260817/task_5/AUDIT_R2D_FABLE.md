# AUDIT — R2-D conversation store · Fable

**Date:** 2026-08-18 · **Card:** task_5 R2-D · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE.** All five declared deviations accepted; no
blocking findings.

## Independently verified

1. **Gate:** my own full commit-tier run on the identical final tree — PASS,
   6,035 — matches the executor's run to the test count (two independent runs,
   same verdict).
2. **Seeds re-run by the auditor:** RED with the expected first failures, tree
   restored, clean 168 green. S5 reddening `[sqlite]` only is real evidence the
   toy and SQLite implementations are independent.
3. **Deviation claims checked against code, not prose:** the lane really does
   re-ledger the same `item_id` on ingress refusal (`lane.py:676/686` — so a
   UNIQUE constraint would raise on the hot path, exactly as argued);
   `realtime_turns` really is a projection without the original timestamp;
   `seq` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so ordering survives process
   restarts structurally, and the reopen test proves durability.
4. **The live database was never opened** (mtime 2026-08-16, two days before
   this card).
5. **Bonus beyond the card:** fail-closed on the way OUT — a corrupted row
   raises `ConversationStoreError` on read instead of returning a lie. In this
   repo's culture that is exactly right and worth naming.
6. The concurrency event the executor reported (my corpus re-scrape landing
   mid-gate) was my own work; its wait-and-rerun handling followed the card's
   rule precisely.

## Adjudication of the five deviations

All **ACCEPT**. Each is reality-correcting rather than scope-creeping: `seq`
exists because the tests' own frozen clocks would otherwise make every ordered
read non-deterministic; the backfill reads `created_at` because the projection
has no timestamp; natural-key de-dup exists because system markers carry
`item_id=None`; the non-UNIQUE index is forced by the lane's refusal
re-ledgering; the lock-release fix is pinned by a byte-identical-behavior test.

## Carry-forwards (not blocking)

1. **Wire a consumer.** Nothing reads the store and nothing constructs it in
   the runtime — deliberate (R1.6 owns `runtime.py` right now), but until the
   construction lands and DI history reads the store, this is infrastructure
   without a heartbeat. First item once R1.6 frees the file.
2. **Backfill against the live database** is an owner-witnessed step: it has
   never run against real data.
3. Concurrency and performance are structurally argued, not measured — fine
   for R2-D, must be measured before any multi-writer future.

## Owner directive check

"Internal database holding raw previous conversations indexed by timestamp,
storage design subject to change": raw turns ✓ (text + provenance + byte-exact
meta), timestamp-indexed ✓ (proven by query plan, not index existence),
subject-to-change ✓ (37 conformance properties × 2 independent implementations,
with a meta-test preventing the toy from quietly becoming a database).
