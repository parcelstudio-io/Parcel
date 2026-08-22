# Task 21 — TURN-1: endpointing is a knob on the production lane

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `PLAN_ASSESSMENT_FABLE.md` voice
section; the design study: turn detection is sent as exactly
`{"type":"server_vad"}` (`realtime/protocol.py:128,149`) and
`realtime/config.py` has no `threshold / prefix_padding_ms /
silence_duration_ms / semantic_vad / eagerness / interrupt_response` keys —
endpointing is the provider's ~500 ms silence tail and cannot be tuned from
`realtime.yaml`. `robot.yaml speech.endpointing: semantic` (Silero + Smart
Turn) applies only to the `--legacy` loop.

## Why
Natural endpointing is half of "talks like a living dog": today every pause
longer than the provider's default ends the owner's turn, and there is no
way to trade eagerness for patience without editing protocol code. The
hosted API already offers `semantic_vad` with `eagerness` and
`interrupt_response`; the repo just never exposed them.

## Work
1. **The object, not the string:** `SessionUpdate.turn_detection` becomes a
   validated object — `type: server_vad | semantic_vad`, `threshold`,
   `prefix_padding_ms`, `silence_duration_ms` (200–800 accepted, refuse
   outside), `eagerness: low | auto | high`, `interrupt_response: bool`,
   `create_response: bool`. New validated keys in `realtime/config.py`
   (prototype overlay per P0-A: `configs/realtime.prototype.yaml.example`
   carries the prototype choice; the shipped example documents the keys).
   **Absent keys ⇒ byte-identical `session.update` payload to today** —
   seed it.
2. **Timing counters:** `lane._on_speech_stopped` records
   `speech_stopped → response.created` and `→ first sink byte`; the ledger
   carries them per turn so TURN-1's rows are measurable from the tee.
3. **Measure on the owner's recording** (owner action, ~10 min: 20
   two-clause utterances with a ~400 ms mid-sentence pause, recorded with
   `record.sh` through the array): replay through the lane with the R17 tee
   for `server_vad` (today) vs `semantic_vad` at each eagerness.
   Pre-register before replay: **commit p50 ≤ 0.6 s**, **0/20 mid-sentence
   commits**, scripted barge-in still fires **3/3** with truncation rows
   present. Report all arms, pick the prototype default from the numbers.
4. Seeds RED: an out-of-range `silence_duration_ms` accepted; a
   `turn_detection` key that changes the payload when absent; the
   mid-sentence commit count not reported.

OWNS: `src/parcel_robot/realtime/protocol.py` (`SessionUpdate.turn_detection`
— NOT line 415, which is GATE-0's), `src/parcel_robot/realtime/config.py`
(new keys beside P0-B's and P2-B's — re-read first), `src/parcel_robot/realtime/lane.py`
speech_stopped timing region only (MARK-1 owns the played-ack region),
`configs/realtime.yaml.example` + `configs/realtime.prototype.yaml.example`
turn-detection blocks, `tools/replay_turn_detection.py`, `tests/test_turn1_*.py`,
`task_21/` docs. MUST NOT TOUCH: the browser ear (`ui/index.html`), the
broker, `audio_gateway.py`.

## Definition of done
Pre-registered rows measured on the owner's 20 utterances (owner-gated row
listed with its exact command until the recording exists; the payload-identity
and validation rows do not wait); seeds RED; `TURN1_STATUS.md`.
