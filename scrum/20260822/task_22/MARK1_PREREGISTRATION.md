# MARK-1 — pre-registration (written BEFORE any measurement)

**Card:** `README.md` (task_22) · **Executor:** Claude Opus · **Verifier:** Fable
**Written:** 2026-08-22, before the harness existed and before a single number
was read. Nothing below was chosen after seeing a result.

## The harness (the R7 rig, extended — not forked)

`FakeRealtimeServer` (`parcel_robot.realtime.fake_server`) → `RealtimeLane` →
`BrowserSink` → `BrowserAudioGateway` → **a headless browser** that is a
line-by-line port of `ui/index.html`'s playback path over a virtual
`AudioContext`. The port is pinned to the JS by source assertions (R7's own
technique: `index.html` is never executed by any test on this host).

**Ground truth for "heard"** is computed by the virtual `AudioContext` from the
scheduled source list (overlap of each scheduled buffer with `(-inf, now]`) —
*not* from the number the browser reports. The reported number is the code
under test; the context's sum is the referee.

### Fixture set (deterministic, seeded, no wall-clock)

Four chunk-arrival patterns × six barge-in instants = **N = 24 barge-ins**:

| pattern | what it models |
|---|---|
| `burst` | the provider dumps the whole reply faster than real time (the live R7 shape: 13 chunks in < 1 s) |
| `realtime` | chunks arrive at roughly the rate they play |
| `underrun` | a stall long enough that the browser's schedule runs dry mid-reply and playback restarts |
| `jitter` | seeded arrival jitter around real time, one short stall |

Barge-in instants: 6 fractions of the reply's duration, spread across it, at
least one after the last chunk has arrived and at least one inside a gap.

## Pre-registered rows

**R1 — `audio_end_ms` is never 0 after ≥ 1 chunk played.**
Over all N = 24 barge-ins: `audio_end_ms > 0` for **24/24**, and
`audio_end_ms <= enqueued_ms` for **24/24** (it must never overstate either).

**R2 — |truncate − heard| ≤ 150 ms p95.**
`heard` = the virtual `AudioContext`'s ground truth at the instant the lane
emitted `conversation.item.truncate`. **p95 ≤ 150 ms** over N = 24.
p50 and max reported alongside, whatever they are.

**R3 — the ear takes ch1, and a downmixed ear is refused not accepted (4 rows).**
 a. `hello()` carries a `capture` block naming the channel count and the beam.
 b. With a beam pinned, a client that arms the mic reporting a **1-channel
    (downmixed)** ear is **refused**: the mic never opens, the refusal is
    counted, and the browser is told why.
 c. With a beam pinned and a client reporting 2 channels / beam 1, the mic opens.
 d. With **no** pin (the shipped default), the arming path is behaviourally
    identical to today: mic opens, no new refusal, no new counter movement.

**R4 — the backchannel floor (first slice; DUPLEX-1 owns the rest).**
 a. `backchannel_floor_ms = 0` (the shipped default) ⇒ the frame sequence the
    lane sends on a barge-in is **identical** to today's: `response.cancel`
    then `conversation.item.truncate`, same order, same values, same
    `truncations` row.
 b. With the floor armed, an owner burst **resolved as sub-floor inside the
    hold** produces **no** `response.cancel` and **no** truncate, and playback
    is never interrupted.
 c. A burst not resolved before the hold expires commits **exactly one**
    cancel and **exactly one** truncate, and the truncate carries the position
    heard *at commit time* (not at speech-start).
 d. **Backchannel survival is reported** over the fixture set. No bar is set
    here — DUPLEX-1 (task_26) sets the ≥ 0.9 bar. Whatever the number is, it
    is printed.

## Seeded-RED proofs (one per new guard)

* **S1 — acks stop when chunks stop.** Restore `index.html`'s per-arrival-only
  ack in the headless port ⇒ R1 and/or R2 must go RED.
* **S2 — a regressive ack re-anchors the played clock.** Remove the monotonic
  guard in `ack_played` ⇒ the underrun pattern must truncate at ~0 ms after
  chunks played (R1 RED).
* **S3 — the downmixed ear is accepted.** Remove the capture-pin check in
  `set_mic` ⇒ R3b must go RED.

Each seed: seed, watch it fail, restore byte-identically (`git diff` empty on
that hunk), purge `__pycache__`, rerun green.

## Gates

Targeted only, on OWNS: `.parcel/bin/python -m pytest` on the MARK-1 test files
plus the two files whose behaviour I change (`tests/test_realtime_lane.py`,
`tests/test_realtime_audio_gateway.py`), and `.parcel/bin/ruff check` on the
touched paths. **The ruff ratchet stays at exactly 7 baseline fingerprints; I
add none.** No `scripts/ci_gate.py`, no full suite.

## Owner-gated (listed, never claimed)

One live through-air barge-in belongs to AIR-1's session (task_25). Command in
`MARK1_STATUS.md`. No live hosted turn is needed for any row above, so MARK-1's
hosted spend is **$0.00**.
