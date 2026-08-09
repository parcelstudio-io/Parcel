# ACOUSTIC_LOOP_V1 results

Immutable JSON reports from
`python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1`.

Every report carries a `does_not_prove` list. **This is a virtual rig: no air,
no room, no transducer, no echo.** Nothing here is a hardware or
room-acoustics claim, and AEC cannot be evaluated at this tier at all.

## First baseline — 2026-08-07

`acoustic-loop-v1-20260807-baseline-run01.json` and `...-run02.json`.
25 cases, ~134 s per run, no root, no physical audio hardware.

**Determinism gate: PASS.** Two consecutive runs produced identical
`case_verdicts`, identical gate statuses, and zero orphan PipeWire nodes after
teardown. A third run after a refactor of the runner (closure bindings,
alignment search window) reproduced the same verdicts and the same nine gate
statuses again.

Latency *values* jitter run to run and are deliberately **not** part of the
determinism contract — ep50 moved 0.792 / 0.772 s and barge-in acoustic stop
0.720 / 0.720 / 0.780 s across the three runs, the last under heavy CPU
contention. The contract is `case_verdicts` and gate status.

| gate | value | limit | status |
|---|---|---|---|
| `endpointing_ep_cutoff_rate` | 0.00 | ≤ 0.05 | **pass** |
| `endpointing_ep50_s` | 0.792 | ≤ 0.500 | **FAIL** |
| `endpointing_ep90_s` | 0.840 | ≤ 1.000 | **pass** |
| `bargein_detection_p50_s` | 0.128 | ≤ 0.400 | **pass** |
| `bargein_flush_max_s` | 0.0001 | ≤ 0.060 | **pass** |
| `bargein_acoustic_stop_p50_s` | 0.720 | ≤ 0.520 | **FAIL** |
| `bargein_false_rate` | 1.00 | ≤ 0.02 | **FAIL** |
| `duplex_acoustic_ack_p50_s` | 0.800 | ≤ 0.700 | **FAIL** |
| `prosody_apex_within_window_rate` | 0.643 | ≥ 0.80 | **FAIL** |

**These five failures were recorded, not tuned away.** No threshold was moved
and no code was changed to make a number go green after seeing it. Each has a
diagnosis below and a backlog item.

### What passed, and what it means

Semantic endpointing never cut the owner off — `ep_cutoff_rate` 0.00 across
all 13 turns, including the three `pause_heavy` fixtures with a real 0.75 s
mid-utterance silence. Smart Turn correctly held those and committed only at
the true end. Incomplete turns were held (`incomplete_hold_p50_s` 1.70 s),
which is the designed behaviour, not a latency defect.

Barge-in **detection** is fast and extremely consistent: 0.128 s at p50 with
p90 at 0.129 s. Queue flush is essentially free (max 71 µs) — the drain-window
fix holds, and there is no token leakage.

### FAIL 1 — `bargein_acoustic_stop_p50_s` 0.72 s vs 0.52 s

The most valuable finding in this run, and one the software tier structurally
cannot see. `duplex_v1` correctly asserts that no chunk tokens leak after
`interrupt()`. That is true. **The audio keeps playing anyway.**

Decomposition: detection 0.128 s + flush ~0 s + **~0.6 s of already-buffered
audio draining out of the output stream**. `SpeakerSink.interrupt()` sets the
latch and stops *writing* at the next ~50 ms block, but samples already handed
to PortAudio are still presented. The robot talks over the owner for roughly
half a second after it has correctly decided to stop.

Fix is not applied here on purpose (this is the baseline): aborting the output
stream rather than merely ceasing to write it. Backlog N-item.

### FAIL 2 — `bargein_false_rate` 1.00 vs 0.02

Both noise-only injections triggered a barge-in. This is **not** Silero
failing: probed directly, Silero rates these fixtures at max p = 0.21 and 0.23
(threshold 0.5) and rates real interrupt speech at 1.00. It rejects the noise
cleanly.

The interaction: during playback, `MicrophoneVoiceLoop._handle_frame` applies
the echo guard *before* the neural VAD and `return`s on suppressed frames. So
Silero receives only the frames that survived the guard — a discontinuous
stream of loud fragments with artificial onsets, not the continuous signal it
was trained on. The gate fragments the model's input and the fragments look
like speech.

With no acoustic coupling in this rig the guard is comparing against a stale
initial noise floor (120.0), which makes the effect easy to trigger here. The
code path is real on hardware too. Backlog N-item.

### FAIL 3 — `duplex_acoustic_ack_p50_s` 0.80 s vs 0.70 s

The headline number, and the one that retires a claim. Measured from the
acoustically-anchored end of owner speech to the first audible robot sample,
both read off one sink-monitor recording.

| quantity | value |
|---|---|
| acoustic ack (p50) | 0.800 s |
| enqueue ack — what the software ledger reports | 0.13–0.26 s |
| **sink presentation delay** | **0.54–0.64 s** |

The software ledger's `audio_first_playback` is an enqueue timestamp. On this
rig it understates the acoustic ack by **0.54–0.64 s** — comparable to the
entire 0.7 s `filler_watchdog_s` budget. `docs/AUDIO_LATENCY_AND_SPATIAL_
INTELLIGENCE.md` already said the dashboard could not honestly support a
sub-700 ms claim; this is the first measurement of how large the gap is.

Note the caveat honestly in both directions: a null sink is not a sound card,
and its presentation latency is not necessarily a real device's. What is
established is that the gap is not negligible and must be measured, never
assumed.

### FAIL 4 — `prosody_apex_within_window_rate` 0.643 vs 0.80

64.3 % of nod apexes landed within ±150 ms of a pitch accent in the *captured*
audio (9 of 14). Median signed lag is 0.04 s — most nods are well placed — but
|lag| p95 is 0.47 s, so a minority are badly off. The captured audio yielded 19
accents against the synthesis side's 14, i.e. the transport surfaces accents
the synthesis-side analysis did not predict, and some apexes then match the
wrong one.

### FAIL 5 — `endpointing_ep50_s` 0.792 s vs 0.500 s

Endpoint commit lands ~0.79 s after the Silero-derived ground-truth turn end
(complete turns alone: 0.756 s). The shipped `complete_silence_s` default is
0.20 s, so roughly 0.55 s is Silero's own speech-tail hangover plus the
480→512 sample re-buffering plus frame quantisation. `ep90` (0.840 s) still
passes its 1 s bar, and nothing was cut off.

The practical reading: **the config comment's implied "~0.20 s semantic
commit" is not what the assembled pipeline delivers.** It delivers ~0.8 s.
