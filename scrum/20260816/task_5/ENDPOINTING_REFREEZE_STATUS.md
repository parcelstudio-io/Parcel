# Semantic endpointing — owner-authorized re-freeze

**Date:** 2026-08-16 · **Executor:** Claude Opus · **Authorization:** owner, this session
**Decision:** flip `speech.endpointing` `energy` → `semantic`, accepting the
re-freeze of `evals/companion/embodied_plan_v1/manifest.json` that it forces.

## What changed, and why it needed an owner

`configs/robot.yaml` is a **locked input** of the frozen embodied-plan manifest,
which is itself pinned in `DIGEST_SENTINELS`. Editing one byte of it moves two
frozen digests, so this was a 2×2 decision, not a config edit. The win it buys is
the largest single latency item in the Voice Spine plan: every owner turn was
waiting out the **2.5 s** incomplete-silence fallback instead of committing at
**0.20 s** once Smart Turn reads the turn as complete.

The weights were never missing. Silero v6 and Smart Turn v3 have been on disk
since 2026-08-07; only the config said `energy`.

| Artifact | Before | After |
| --- | --- | --- |
| `configs/robot.yaml` | `aff691130b25` | `f7b57dcdf0b5` |
| `embodied_plan_v1/manifest.json` | `22736f6e0e4b` | `1725a246dd00` |
| `DIGEST_SENTINELS` entry | re-pinned; prior value retained in-comment | |

The packaged mirror and the `src/parcel_robot/config/robot.yaml` side mirror were
re-synced by `tools/sync_runtime_assets.py`; `release-parity` stayed green.

## Blast radius, measured rather than assumed

**No eval output moved.** Two independent reasons, both checked:

1. None of the three sentinel-locked suites constructs a `MicrophoneVoiceLoop`.
   Endpointing is reached only from the runtime's microphone path; these evals
   are text-lane. Before and after: **32 passed**, identical.
2. `acoustic_loop_v1` — the one suite that *does* measure endpointing (ep50 /
   ep90 / ep-cutoff) — builds `SileroVad`/`TurnEndpointer` from **hardcoded model
   paths** (`run_acoustic_loop_v1.py:78-79`), not from `robot.yaml`. Its frozen
   rows already characterise the semantic stack and cannot move. It is also not a
   `DIGEST_SENTINELS` entry.

So the input digest moved and no measured behaviour did — which is exactly what a
re-freeze exists to record.

## The stack is live, not silently degraded

The flip would be theatre if onnxruntime or the weights were unusable, because
`_build_endpointing` degrades to the energy path. Verified **before** the edit:

```
onnxruntime: OK
SileroVad.available: True
TurnEndpointer.detail: smart-turn-v3
resolved: semantic: smart-turn-v3 + silero(models/endpointing/silero_vad_v6.onnx)
```

The degrade path remains loud (warning event plus `speech.stack` in
`/api/state`), so this adds no new silent-failure surface.

## Gates

```
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  default-suite              5471 passed, 9 skipped, 40 deselected
RESULT: PASS — every hard gate green.   elapsed 249.5s
```

Live-sim e2e, re-run after the flip:

```
$ MUJOCO_GL=egl .parcel/bin/python -m pytest tests/test_voice_nav_e2e.py -q
17 passed, 1 xfailed, 3 warnings in 689.14s (0:11:29)
```

Identical to the pre-flip baseline in this same session (17 passed / 1 xfailed,
694.64 s) and to the FIX-A baseline (694.45 s). The single xfail is the
pre-existing P-1/P-3 yield-policy pin; it did not flip and was not expected to.

## does_not_prove

* **No latency was measured.** The 2.5 s → 0.20 s figure is the configured commit
  threshold, not an observed end-to-end improvement. N19's ledger fan-in is still
  open, so `/latency` cannot show it. **This is the number to go get next** — the
  change is now worth measuring, which it was not before.
* **Never exercised on a live microphone.** This host has no transducer and
  PortAudio is not loadable. Smart Turn's accuracy on the owner's actual voice,
  and whether a 0.20 s commit clips real speech, are unmeasured.
* **The 2.5 s fallback still exists** for turns Smart Turn reads as incomplete.
  What changed is that it is no longer the *only* path.
* B2's frozen ep50 endpointing eval is untouched and was not re-opened.

## Handoffs

1. Land N19's ledger fan-in, then re-measure. This is the first voice-stack
   change whose effect should be large enough to see.
2. The first live-mic session should watch for premature commits (0.20 s cutting
   the owner off mid-sentence) and record `speech.stack` from `/api/state` in the
   session log.
