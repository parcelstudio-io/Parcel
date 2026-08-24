# VOICE-GATE v2 · VERDICT (Fable) · 2026-08-24

Basis: the executor's RESULTS.md + consolidated table + 11 raw JSONs;
my guard re-run of `tests/test_voicegate_probe.py` + both DEC ratchets
(27 passed) on the quiet host; footprint verified research-only (no product
file touched — the executor's declared deviation, accepted: a flag-off
ambient gate with no evidence would be debt); audio settings verified
unchanged; $0 hosted; 4 seeded-RED proofs with sha-restored files.

## Disposition: **CONFIRMED — push-to-talk ships for M1** (by the
pre-registered failure clause, and it also measured best)

| claim | disposition |
|---|---|
| Pass rule unsatisfiable on this host (P9 AEC / P10 barge-in need a loudspeaker; the only output is the array's own DAC, whose audibility is undeterminable without a second mic) | CONFIRMED — every arm row is honestly tier `replay` over a real recorded room floor; through-air geometry/AEC/barge-in move to the box-day mounted packet |
| PTT arm: owner recall 1.000 (all six geometry cells), 0 hosted bytes for TV/second-person/self-speech, 0 false openings/day, $0.15/day, 0 % replay | CONFIRMED (the arm-independent failures — STOP rows, cancel 740 ms, slots 0.850 — fail identically for all arms and are build items, not arm discriminators) |
| `voice_identity.DEFAULT_THRESHOLD = 0.55` mis-calibrated for room audio: owner recall 0.167, while EER = 0.000 at ≥ 2 s and 0.352 buys 0.95 recall at 0.000 impostor FA | CONFIRMED — **product fix for A7**: recalibrate on the deployment channel, channel-matched enrollment; the model is fine, the operating point is wrong |
| Replay accepted 52.8 % at the usable threshold; no arm immune | CONFIRMED — A9's honesty row; ship policy documents replay as an accepted indoor risk or defers liveness post-M1 |
| STOP-LOCAL bare keyword: recall 0.875, p95 935 ms, ≈864 false/24 h on TV; none of the false triggers contained the dog's name | CONFIRMED — a bare "stop" spotter cannot meet A9's bars; **owner decision flagged**: name-prefixed STOP (0 false on this tape, loses bare "Stop!") vs bare (fails the false bar) vs context-scoped hybrid (bare "stop" live only while the dog is speaking/moving on an owner mission — the prior shifts; unmeasured, proposed for the A6 card) |
| whisper `base.en` misses names/places (slots 0.850 even with piper) | CONFIRMED — constrained/boosted decoding over the known vocabulary is an A7 build item |
| H1 C5 reproduced through air (809 opens/h on TV proxy); 49.6 min real room = 0 opens/admits | CONFIRMED-WITH-NOTE — the ≤1/24 h bar needs ~72 h of tape; 3/T supports only ≤87/24 h |

Product path: none (by design this run); the evidence now exists for A6/A7
to wire the gate. The ambient tape's early stop (49.6/120 min) is accepted —
only the confidence bound would have improved, not the conclusion.

Three sentences. Measured: push-to-talk is the only policy that satisfies
everything measurable here, at $0.15/day with zero non-owner bytes; the
identity model separates perfectly but ships mis-calibrated; a bare local
"stop" hotword is unusable as a safety path on ordinary television audio.
Still assumed: everything through-air (geometry, AEC, barge-in, the mounted
acoustics with gait/fan noise) and the real speaker path's audibility.
The design consequence: M1's voice is PTT + the calibrated identity gate,
STOP-LOCAL ships name-prefixed unless the owner rules otherwise, and the
ambient upgrade path is a box-day decision on mounted evidence.
