# NARR-1 — off-thread narration (wave A · runtime-toucher · Tier B)

Design: scrum/20260823/TRANCHE2_MIND_DESIGN_FABLE.md (grounded fact 2, card
NARR-1). Fixes ARCH-1 verdict blocking finding 1: the 10 Hz control thread
performs a blocking `websockets.sync` send + a spend-ledger disk read via
`_step_whisperer` → `_narrate_mission` → `RealtimeLane.narrate_event`.

## Build
1. `RealtimeLane.enqueue_narration(...)`: bounded FIFO (deque maxlen ~8),
   entries stamped with the session id at enqueue; overflow drops the
   OLDEST non-critical entry with a counter; critical entries
   (whisperer.CRITICAL_KINDS decisions) are never dropped.
2. `RealtimeDriver.step()` drains the FIFO between `pump()` and `tick()`
   on the pump thread, calling the existing `narrate_event` there —
   the ws send, ledger read, and lane lock all leave the control thread.
   Single-FIFO drain preserves item/response ordering and
   `_response_provenance` tagging exactly as today.
3. Cancellation semantics: entries whose stamped session no longer
   matches, or drained while the lane is inactive, invoke
   `whisperer.undeliver` (already RLock-safe) and are dropped with a
   counter; the inbox is CLEARED on hang-up — the whisperer must never
   be able to re-open a paid session (R16 invariant).
4. `_narrate_mission` (runtime whisperer region) becomes enqueue-only.
   `_step_owner_events` / `_step_curiosity` narration paths route through
   the same inbox.

## OWNS
`src/parcel_robot/realtime/lane.py` (marked region `# ---- CARD NARR-1`),
`src/parcel_robot/realtime/driver.py` (marked region),
`src/parcel_robot/runtime.py` (whisperer marked region ONLY — you are this
wave's sole runtime.py writer), `tests/test_narr1_offthread.py`, this
folder.

## MUST NOT TOUCH
`whisperer.py` internals (undeliver's contract is your dependency, not
your OWNS), spend policy/budget thresholds, `ws_transport.py`,
`audio_gateway.py`, voice_* files (EAR-1's), other fences, git.

## Prove (capability tests only, ~6-8)
Fake transport whose send sleeps 200 ms → `_step_whisperer` returns in
single-digit ms; FIFO order across three enqueues; undeliver + budget-slot
return on stale-session and inactive-lane drains; overflow drops oldest
non-critical only, never critical; inbox cleared on close (counter);
existing realtime corpus replay suite stays green
(tests/test_realtime_corpus_replay.py) and r24/nominal-stop oracles green
with zero re-pins (you touched runtime.py).

## Rules
Guard wrapper (`--label narr1`, `env -u TMPDIR`), no `-n auto`, no
`--tier`, no `noqa` (baseline exactly 7), ruff clean, no commit/push, no
:8765 / parcel_sim.sock / parcel_memory.sqlite3. Short NARR1_STATUS.md.
