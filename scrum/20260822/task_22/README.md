# Task 22 — MARK-1: an interruption tells the truth about what was heard

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** the registered debt "barge-in mark
integrity" (`scrum/20260818/task_4/R7_STATUS.md:396-403`,
`AUDIT_R7_FABLE.md:60-62`, carried on `scrum/20260821/TASK_BOARD.md:64`);
the design study: the browser sends `played` acks only when a NEW chunk
arrives (`ui/index.html:2574-2578`), so after `sink.interrupt()` no ack ever
lands, `played_ms()` (`lane.py:2252-2271`, clamped by
`audio_gateway.ack_played` `:1412-1447`) reads 0, and the live truncation was
`[interrupted after 0 ms]` — the provider was told the owner heard none of a
reply they heard 13 chunks of. Consequence: context drift and repeats after
every barge-in. Also: `channelCount:1` makes PipeWire downmix the array's
ch0 (Conference) + ch1 (ASR) beams into the ear.

## Why
Barge-in exists (210 ms measured) but lies to the model about what was
heard. A companion that repeats itself after every interruption does not
feel alive. This is the cheapest fix with the largest conversational effect.

## Work
1. **Continuous played acks:** the browser reports `played` on a timer
   (≈100 ms) while audio is rendering, and once more on interrupt with the
   final position; `audio_gateway.ack_played` accepts monotonic updates and
   clamps as today. `conversation.item.truncate(audio_end_ms=…)` must carry
   the heard position: pre-register **`audio_end_ms` never 0 after ≥ 1
   chunk played** and **|truncate − heard| ≤ 150 ms p95** on the
   `fake_server` + headless client harness (the R7 rig).
2. **The ear takes ch1 explicitly:** `getUserMedia({channelCount: 2})` and
   pick the ASR beam (or a PipeWire loopback virtual source documented in
   the prototype example); pin the channel choice in the gateway hello so a
   downmixed ear is refused, not silently accepted.
3. **Backchannel tolerance (first slice, DUPLEX-1 owns the rest):** a
   `speech_started` shorter than a pre-registered floor (e.g. < 350 ms with
   no transcript content word) ducks instead of cancelling; a cancel is
   committed only past the floor. Measure on the R7 fixture set: backchannel
   survival reported (DUPLEX-1 sets the ≥ 0.9 bar).
4. Seeds RED: acks stop on interrupt; truncate sent with 0 after chunks
   played; the downmixed ear accepted.

OWNS: `src/parcel_robot/ui/index.html` played-ack + capture regions,
`src/parcel_robot/realtime/audio_gateway.py` `ack_played` + hello channel
pin, `src/parcel_robot/realtime/lane.py` `_on_speech_started` / `played_ms`
region only (TURN-1 owns the speech_stopped timing region; re-read before
each edit), `tests/test_mark1_*.py` + the R7 rig extension, `task_22/` docs.
MUST NOT TOUCH: `protocol.py`, `config.py` turn-detection keys (TURN-1), the
broker, the whisperer.

## Definition of done
Pre-registered rows met on the rig; the three seeds RED; one live
through-air row listed OWNER-GATED (AIR-1's session) with its command;
`MARK1_STATUS.md`.
