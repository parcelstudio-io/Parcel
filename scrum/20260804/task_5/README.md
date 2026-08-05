# Sprint 2026-08-04 · task_5 — duplex dual-stream voice agent (D0)

**Design record:** [../../../docs/DUPLEX_DUAL_STREAM_DESIGN.md](../../../docs/DUPLEX_DUAL_STREAM_DESIGN.md).
**Scope:** the D0 slice — frame contract, system-composed producer, filler
policy, duplex eval, aligned-stream logging. D1 (trained dual-head model)
gates on D0's log corpus and eval; it is NOT this sprint.

**Executors:** Opus (existing files), Sol 5.6 Ultra (new pure modules only:
`src/parcel_robot/duplex/*` + tests). Conflict rule and working agreements
1–8 inherit from [../task_4/README.md](../task_4/README.md) and task_1.

Prerequisite state: task_4 foundations landed (registry, pause/resume,
attention modules); movement-speed raise landed with the embodied gate
re-frozen (1146 steps, provenance in `tests/test_embodied_plan_eval.py`).

## Board

| ID | Card | Owner | Depends on |
|---|---|---|---|
| D-S1 | `DuplexFrame` contract + `FrameInterleaver` (pure): clock, epochs, `<idle>`/`<silence>` fill, stream merge rules | Sol | — |
| D-S2 | `ActTokenCodec` (pure): twist-bin quantize/dequantize within SafetyLimits, gaze bins, skill/emote/filler token encode-decode, round-trip property tests | Sol | — |
| D-S3 | `FillerPool` (pure): variation pool, personality-conditioned sampling, no-repeat habituation, clause-boundary handoff rule | Sol | — |
| D-O1 | Filler wiring: predictive trigger (slow-route detection in agent/planner dispatch) + 700 ms watchdog + thinking-pose gesture; ≤2 s ceiling metric | Opus | D-S3 |
| D-O2 | D0 producer: interleave LLM text stream + arbiter/skill/expression events into frames; act-token executor through existing admissibility; epoch-atomic cancel | Opus | D-S1 D-S2 |
| D-O3 | Aligned-stream session logging (the D1 corpus): frames + context features + outcomes, rotating files, privacy note | Opus | D-O2 |
| D-O4 | `DUPLEX_V1` eval: scripted turns; TTFT/filler/continuity/atomicity metrics; nav suites in the same lane as regression gate | Opus | D-O1 D-O2 |
| — | Review at S-landings and D-O2/D-O4 exits; D1 go/no-go when the corpus and eval mature | Fable | standing |

All three S-cards and D-O1's scaffolding start now; D-O2 consumes S1+S2.

## Hard gates

- TTFT P50 < 1 s on scripted turns with the local pipeline; **no response
  ever exceeds 2 s without an audible filler already playing** (owner
  ceiling — the eval counts breaches, target zero).
- ACT stream continuity: zero missing frames at 10 Hz across a full
  scripted session.
- Barge-in atomicity: no post-epoch frame of either stream executes.
- Navigation quality unchanged: follow-bench + embodied rows stay at their
  2026-08-04 post-speed-raise values.

## Handoffs

### Coordinator (Grok) — 2026-08-04 — full task_5 D0 (Sol+Opus scopes)

Sol/Opus API limits; both scopes landed in one pass under the conflict rule
(Sol = `src/parcel_robot/duplex/*` + tests; Opus = existing files + evals/docs).

**D-S1 (Sol):** `duplex/frames.py` + `tests/test_duplex_frames.py` —
`DuplexFrame` / `FrameInterleaver`; always-stream idle/silence fill; text FIFO;
act last-wins; epoch drop; monotonic `t`; drift-free 10k ticks.

**D-S2 (Sol):** `duplex/act_codec.py` + `tests/test_act_codec.py` —
`TwistBins` / `ActTokenCodec` / `ActCommand`; round-trip on bin centers;
OOR clamp; unknown→ValueError; pinned sorted default vocabulary.

**D-S3 (Sol):** `duplex/fillers.py` + `tests/test_filler_pool.py` —
`FillerPool.default()` ≥6 variations; no consecutive repeat; all-suppressed
→ LRU not None; seeded determinism.

**D-O1 (Opus):** `duplex/filler_policy.py` + `config.py`; agent
`slow_path_hook` before deliberative_plan / info tools; 700 ms watchdog polled
on the control loop; `DuplexVoiceSession.play_filler` + clause-boundary wait;
`FillerLatency` / `ResponseCeilingBreach` in component metrics +
`/api/state`→`duplex`; fail-closed `duplex:` in `robot.yaml` (manifest
`robot_config` sha re-frozen).

**D-O2 (Opus):** `DuplexCoordinator` + `DuplexFrameConsumer` (shadow);
`FrameInterleaver` ticked in `_control_loop` at 10 Hz; TEXT from reply tokens;
ACT from post-gate twists + filler gestures; epoch synced from
`voice_session.speech_epoch` / barge-in.

**D-O3 (Opus):** `duplex/session_log.py` → `logs/duplex/<session>.jsonl`
rotating; gitignored; privacy note in design record; `duplex.logging` kill
switch.

**D-O4 (Opus):** `evals/companion/duplex_v1/` scripted turns + ledger +
`does_not_prove`; nav regression pins post-speed-raise follow-bench shipped
row + embodied 1146 steps.

**Not verified → UNVERIFIED.md:** U21 (real TTS filler), U22 (D0 shadow ≠
live ACT drive), U23 (log privacy/size on long sessions).

**Suite (pre-arbitration):** 1648 passed, 6 skipped; ruff clean.

## Arbitration (coordinator standing in for Fable) — 2026-08-04

Cross-review: Sol D-S1/S2/S3 APPROVE WITH NITS (agent b4c0ca43);
Opus D-O1–O4 REQUEST CHANGES (agent 4959f706). Rulings:

### BINDING must-fixes (Opus) — implement now, priority order

1. **Watchdog/ceiling on TTS queue, not LLM text.** Cancel watchdog /
   clear ceiling only when the first token reaches the TTS queue (or the
   text-only audible/delivery path). `reasoning_response` alone must not
   mark the turn answered — fast text + stalled TTS must still fire filler
   / count a ceiling breach.
2. **DUPLEX_V1 eval must measure, not invent.** Stop hardcoding TTFT;
   measure from scripted pipeline timing. Continuity must exercise the
   runtime producer path (or a faithful replica of control-loop ticks with
   ACT/TEXT pushes), not a bare `FrameInterleaver` alone.
   `embodied_unchanged` must verify the frozen step count / gate (or call
   the existing check), not `True`.
3. **ACT feed completeness.** Push gaze/emote/skill tokens when those
   events fire (attention decisions, skill dispatches, expression), not
   only twist + filler.
4. **TEXT stream observe.** Push tokens as the reply streams (chunk/word
   as the spoken path gets them), not only dump the full reply at
   `reasoning_response`.
5. **FillerLatency.** Record end-of-turn → audible (playback start / TTS
   enqueue audible), not fire time as the primary sample.
6. **ResponseCeilingBreach.** Stop `observe_ms` every tick; keep as a
   counter in the duplex snapshot only.
7. **Per-turn outcomes in session log.** Wire coordinator turn-outcome
   writes from runtime (TTFT, filler used, barge-in).
8. **Filler double-fire race.** Synchronize predictive + watchdog so only
   one filler fires per turn.
9. **Clause-boundary.** Wire `note_clause_boundary_pending` into the voice
   path OR document + test the path that actually exists; strengthen the
   mid-filler handoff test if feasible.

### DEFER (Sol nits)

- `pick()`-level no-repeat without `notify_spoken`
- `now_s`-derived frame index (drift-free nit)
- `filler_speech` vs `filler_gesture` kind

### Constraints (unchanged)

- Do not break collision / reactive_safety
- Nav ledger rows stay at post-speed-raise values
- Suite + ruff green; update U21–U23 if claims change
- `robot.yaml` hash re-freeze if touched

### Post-arbitration landing (coordinator)

All nine BINDING must-fixes landed. Sol DEFER items remain deferred.
`robot.yaml` untouched (no hash re-freeze). U21–U23 claims refreshed for
audible-path metrics, gaze/skill/emote ACT feed, and turn-outcome logging.

**Suite (post-arbitration):** 1655 passed, 6 skipped; ruff clean.
