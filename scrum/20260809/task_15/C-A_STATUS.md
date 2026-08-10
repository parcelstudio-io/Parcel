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

## does_not_prove

- Seed ledger row is **clock-honest against the N19 stage vocabulary**, not a live duplex / PipeWire wall-clock measurement; sub-700 ms AcousticAck on hardware is unproven.
- Ledger ratchet is intentionally **skipped** until `window=5` rows exist; today the percentile-pin pytest gate is still the authoritative latency-tail hard check.
- walk_with_me stub `hard_collision_total=0` is stub geometry, not headless/hardware collision evidence.
- Ruff remainder in camera_channel / detection_adapter is other cards' debt, not cleared.

## Blockers

None for C-A scope. Habitat smoke red is pre-existing and outside OWNS.
