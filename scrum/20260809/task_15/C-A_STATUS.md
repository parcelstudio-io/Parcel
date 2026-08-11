# C-A STATUS — CI debt + N19 clock fan-in

**Primary executor:** Claude Opus (`dadb49ca-c2f6-459b-bd52-84def1221cf0`) — API limit mid-card  
**Stand-in (finish):** inherit agent (Opus stand-in due to API limit)  
**Base note:** Wave-1 pre-dispatch already had default-suite red on habitat smoke; unchanged by this card.

## Already present (Opus partial — verified, not redone)

| Area | Fact |
|---|---|
| `observability.py` | `ACOUSTIC_ACK_LATENCY_DEFINITIONS`; acoustic spans in `_trace_row`; signed `stage_offsets`; `ACOUSTIC_ACK_STAGES`; `LATENCY_LEDGER_RELPATH` / `PARCEL_LATENCY_LEDGER`; `latency_ledger_row` / `append_latency_ledger_row` / `resolve_latency_ledger_path` / `latency_tail_series` |
| `runtime.py` | `_mark_acoustic_capture_clocks`, `_mark_audio_first_sample` (via `_audio_chunk_started`), `audio_output_turn_id` + consumed guards, `write_latency_ledger_row`, `close()` opt-in ledger write, `query_end` / `tts_start` hooks |

## Finished by stand-in

| Item | Fact |
|---|---|
| Duplex mark proof | `tests/test_acoustic_defects.py::test_n19_runtime_fans_in_acoustic_clocks_on_duplex_voice_path` — injects mic `last_turn_clocks` + recognizer `last_metrics`, drives `_voice_stage(query_end/tts_start/turn_complete)` + `_audio_chunk_started`; asserts all 5 N19 stages in `stage_offsets_ms` and in a written ledger row. **PASS** |
| `evals/latency/` | `ledger.jsonl` (1 clock-honest seed row `latency-seed-n19-20260809T000000Z`), `baseline.json` (`window=5`, pinned AcousticAck/EndpointDecision/SttTranscribe/PlaybackEnqueueToFirstSample/TurnTotal/UserQueryEndToFirstResponse), `README.md` |
| Latency-tail source switch | `scripts/ci_gate.py`: `evaluate_latency_ledger` reads ledger vs baseline; under-window → `skip` (never red); pytest pin gate **kept** as `latency-tail`. Self-test `test_latency_ledger_reddens_on_seeded_spike` + existing `test_latency_tail_reddens_on_p99_regression` still redden |
| walk_with_me hard-safety | Aggregate + ledger emit `hard_collision_total`; hard-safety counts **only** rows carrying the field. Legacy stub row (20260805) skipped; new smoke row `walk-with-me-v1-stub-20260809T222935Z` with `hard_collision_total=0` joins |
| `ui/latency.html` | Acoustic metricNames added (display only) |
| Ruff burn-down | Baseline **39 → 7** fingerprints; `new=0`. Remainder is exclusively V-A `camera_channel/**` + V-B `detection_adapter/**` (excluded). Burned storefront/uwb/route_memory/bags/voice/tests/tools/etc. Did not touch core/** / camera_channel/** / detection_adapter/** sources |

## ci_gate --tier commit (raw)

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                ... walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5; ratchet skipped
[  PASS] HARD  model-off-non-inferiority
[  PASS] HARD  frozen-digest-integrity
[  PASS] HARD  mutation-panel-freshness
[  PASS] HARD  latency-tail               6 passed
[  FAIL] HARD  default-suite              1 failed, 3209 passed, 9 skipped
    FAILED tests/test_habitat2020_contract_smoke.py::test_real_subprocess_sidecar_smoke_uses_unchanged_config
RESULT: FAIL — 1 hard gate(s) red: default-suite
elapsed 107.3s
```

All C-A-owned hard gates green. Sole red = pre-existing habitat smoke (DISPATCH_WAVE1 pre-dispatch note); this card did not touch that test or habitat config.

## Latency-ledger reachability — CLOSED by lane E4 (2026-08-10)

**The defect.** `resolve_latency_ledger_path` returned `None` unless
`PARCEL_LATENCY_LEDGER` was set, and **nothing in the repo ever set it**.
`LATENCY_LEDGER_RELPATH` was declared and never used as a default. So the only
writer (`RobotRuntime.close()`) was permanently inert, the ledger held its 1
hand-seeded row for its whole life, and `ci_gate`'s `latency-tail-ledger` gate
was permanently `skip` — a hard gate that could not fire.

**The fix** (`src/parcel_robot/observability.py`, ledger-path resolution only —
`runtime.py` untouched):

1. `resolve_latency_ledger_path()` now falls back to
   `REPO/evals/latency/ledger.jsonl` via the new `default_latency_ledger_path()`.
2. `PARCEL_LATENCY_LEDGER_OFF` is the **explicit opt-out** that restores the
   old write-nothing behaviour byte-for-byte.
3. A **pytest process never resolves the committed ledger.** A unit test's
   runtime teardown is not a measurement and must not mutate a committed
   measurement artifact; ~29 test files close a runtime. Tests that do want a
   ledger pass an explicit path (`tests/test_acoustic_defects.py` does), which is
   honoured above the default.
4. `append_latency_ledger_row` **refuses a turn-less row into the committed
   ledger** (returns `None`). This one is load-bearing: `evaluate_latency_ratchet`
   iterates the *baseline's* metrics and `continue`s on any the row lacks, so a
   row with no percentile series would have made the newly-reachable gate return
   a **vacuous pass**. Making a gate reachable must not make it meaningless.
5. `evals/companion/duplex_v1/run_duplex_v1.py` (ledger emission only) replays
   the `DuplexVoiceSession` stage clocks it *already collects* for TTFT into a
   `LatencyTracker` and appends one real row per run. No new measurement, no new
   dependency.

**Measured.** Ledger rows **1 → 5** across four duplex runs. `ci_gate`'s gate
flipped:

```
before: [  skip] HARD  latency-tail-ledger  ledger rows=1 < window=5; ratchet skipped
after:  [  PASS] HARD  latency-tail-ledger  latest row latency-20260810T082415Z-4d83035f:
                                            6 metric series within 1.2x tail ceiling (rows=5, window=5)
```

Example real row: `turns=2`, `TurnTotal p95 40.635 ms` (pin 1250 ms),
`UserQueryEndToFirstResponse` present, `stages_observed` = the 10 stages the text
path genuinely produces.

**Honest limit, stated because the gate message hides it.** The duplex text path
has no microphone, endpointer or audio sink, so the four **acoustic** pins
(`AcousticAck`, `EndpointDecision`, `SttTranscribe`,
`PlaybackEnqueueToFirstSample`) are **absent by omission** from duplex rows. The
ratchet reads only `rows[-1]`, so today it actually compares **2 of the 6**
pinned metrics. `ci_gate`'s detail string says "6 metric series" because it
counts *baseline* metrics, not compared ones — that string is misleading and is
flagged here as a follow-up for the `scripts/ci_gate.py` owner (out of E4's
OWNS). The percentile-pin pytest gate (`latency-tail`) remains the authoritative
latency-tail hard check, exactly as before, so nothing was lost.

Pinned by `tests/test_e4_evidence_seams.py` (resolution order, opt-out env,
pytest suppression, turn-less-row refusal).

## does_not_prove

- Seed ledger row is **clock-honest against the N19 stage vocabulary**, not a live duplex / PipeWire wall-clock measurement; sub-700 ms AcousticAck on hardware is unproven.
- The duplex-emitted rows are real wall-clock measurements of the **text** path
  only. They do **not** exercise the acoustic clocks, so the AcousticAck ratchet
  is still aspirational until a real capture/playback run writes a row.
- ~~Ledger ratchet is intentionally **skipped** until `window=5` rows exist~~ —
  superseded: the ratchet now fires (rows=5), with the partial-coverage caveat
  above.
- walk_with_me stub `hard_collision_total=0` is stub geometry, not headless/hardware collision evidence.
- Ruff remainder in camera_channel / detection_adapter is other cards' debt, not cleared.

## Blockers

None for C-A scope. Habitat smoke red is pre-existing and outside OWNS.
