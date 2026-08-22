# DUPLEX-1 — pre-registration

Written **before** any number in this card was measured. The sha256 of this
file is quoted in `DUPLEX1_STATUS.md`; if the file changes after a row is
measured, the row is void.

Executor: Claude Opus (session DUPLEX-1). Date: 2026-08-22.

## 0. The rig every row is measured on

`FakeRealtimeServer` → `RealtimeLane` → `BrowserSink` → `BrowserAudioGateway`
→ a headless port of `ui/index.html`'s playback path — MARK-1's R7 rig
(`tests/test_mark1_barge_in_mark.py`), imported, not forked, and extended with
the playback `GainNode` this card adds to the panel. No monkeypatch of
`played_ms`, `turn_timings`, or the gateway's clamps. The referee for "what the
owner actually heard" stays MARK-1's `_AudioContext.rendered_ms()`, which is
computed from the scheduled buffers and never from any number under test.

Every row is a **product-path** row in that sense and in no other: there is no
browser, no microphone and no acoustic path on this host. Everything that
depends on real audio hardware is owner-gated and listed as such.

## 1. The two prerequisites, set together

MARK-1 H-4 (extended) and the AUDIT §MARK-1 finding 2: any
`backchannel_floor_ms > 0` is inert unless BOTH of TURN-1's knobs are set.

* `turn_detection.interrupt_response: false` — otherwise the provider cancels
  its own reply the moment its VAD hears the owner and the floor protects
  nothing.
* `turn_detection.silence_duration_ms` tuned — server VAD only reports the
  owner stopped after its silence tail, so a floor buys survival only while
  `floor >= burst + tail`. TURN-1's accepted range is 200–800 ms; this card
  uses **200** (the low end) for the measured arms.

Rows measured with the prerequisites NOT set are reported beside the ones with
them set (row D-6).

## 2. The backchannel fixture set (fixed here, before measuring)

Ten acknowledgement tokens with a burst duration each. **Provenance, stated
rather than implied:** there is no backchannel corpus on this host and the
owner has recorded none, so these are stand-in durations for typical English
monosyllabic and disyllabic acknowledgements, chosen before the floor ladder
was run and NOT adjusted afterwards. A real corpus is owner-gated (row OG-3).

| # | token | burst ms |
|---|---|---|
| 1 | `mm` | 120 |
| 2 | `mm-hmm` | 150 |
| 3 | `yeah` | 180 |
| 4 | `sure` | 200 |
| 5 | `uh-huh` | 220 |
| 6 | `right` | 240 |
| 7 | `okay` | 260 |
| 8 | `[laugh]` | 300 |
| 9 | `yeah okay` | 320 |
| 10 | `mm-hmm yeah` | 380 |

The interruption fixtures (what must NEVER be swallowed): bursts of 600, 900
and 1400 ms — a real sentence taking the floor.

## 3. The decision rule for the shipped prototype default

Fixed here so it cannot be chosen after seeing the numbers:

> The shipped `backchannel_floor_ms` is the **smallest** floor on the ladder
> `(0, 250, 350, 450, 700, 1000)` whose survival over §2's fixture set is
> **≥ 0.9** with the prerequisites of §1 set. Cancel latency is then reported
> at that floor whatever it comes out at.

If the chosen floor's cancel latency exceeds row D-2's bar, **D-2 is recorded
as a MISS** — the bar is not moved — and row D-2b is reported beside it as the
number that describes what the owner experiences instead.

## 4. The rows

| Row | What | Bar |
|---|---|---|
| **D-1** | **duck latency**: server `speech_started` reaching the lane → the panel's playback gain is below 1.0, p95 over the barge-in sweep, nominal socket | **≤ 100 ms** |
| **D-1b** | the same at a 350 ms socket lag (the transport-bound arm) | reported, no bar |
| **D-2** | **cancel latency**: owner speech onset → `conversation.item.truncate` on the wire, p95, at the shipped floor | **≤ 450 ms** |
| **D-2b** | **time to quiet**: onset → playback gain below 1.0, p95, at the shipped floor | **≤ 100 ms** |
| **D-3** | **backchannel survival**: survived / 10 over §2 at the shipped floor with §1 set | **≥ 0.9** |
| **D-4** | **proactive collision**: turns the controller allowed initiative on while the robot held the floor, over the whole sweep | **0** |
| **D-5** | **no owed turn is dropped**: over a bounded soak of barge-ins, holds left open at the end, and owed turns abandoned by a state transition | **0 / 0** |
| **D-6** | the arms WITHOUT the prerequisites: survival at `interrupt_response: true`, and at the provider's 500 ms tail | reported, no bar |
| **D-7** | **floor 0 is byte-identical**: with the floor off, the frames on the wire and the truncate rows equal today's | **identical** |

`p95` is MARK-1's `_p()` (nearest-rank on the sorted list), so the two cards'
percentiles mean the same thing.

## 5. Seeded RED

Every new guard gets one: the PRODUCT is seeded (not the test), the named test
is watched to fail, the file is restored **byte-identically by sha256**,
`__pycache__` is purged, and the test is re-run green. The list of guards and
their seeds is written into the status doc with the sha before/after.

## 6. Owner-gated rows (never claimed here)

* **OG-1** — a through-air session with real backchannels (AIR-1's session):
  does a real "mm-hmm" through the XVF3800 + Chrome AEC3 survive at the
  shipped floor, and does the duck sound like ducking rather than a dropout.
* **OG-2** — the interrupt onset stamp end to end: `interrupted_onset_at` in
  the capture index vs the array's own recording of when the owner started.
* **OG-3** — a real backchannel corpus to replace §2's stand-in durations.
* **OG-4** — RT-TURNS-1: `turns.jsonl` from a live hosted session, so AIR-1's
  `owner_turns` / `robot_as_owner` rows have a producer.

## 7. What this pre-registration does not promise

No acoustic number. No claim about Chrome's AEC3, the array's on-chip AEC, or
false barge-in through air. No claim that a local (Silero) endpointer is wired
— it is not; the seam is `lane.note_owner_speech_stopped()` and the producer
does not exist. No hosted spend: the rig is offline and every arm runs against
`FakeRealtimeServer`.
