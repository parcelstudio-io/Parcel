# K5 Status — CameraChannel + DetectionAdapter + low-viewpoint gates (Sol)

**Card:** K5 · **Owner lane:** Sol (pure) · **Date:** 2026-08-05 ·
**State:** DONE (pure modules + CI; no MuJoCo/EGL wiring, no hardware claims)

## Delivered

| Artifact | Path |
|---|---|
| CameraChannel package | `src/parcel_robot/camera_channel/` |
| D455 + 35 cm mount constants | `…/camera_channel/d455.py` |
| RGB / depth / seg frame envelopes | `…/camera_channel/frames.py` |
| Channel + `CameraBackend` protocol | `…/camera_channel/channel.py` |
| DetectionMsg noise adapter | `src/parcel_robot/detection_adapter/` |
| Habitat-style noise config | `…/detection_adapter/noise.py` |
| Low-viewpoint gate pack | `src/parcel_robot/low_viewpoint/` |
| CI tests | `tests/test_k5_camera_detection_gates.py` |

## Checklist

- [x] Pure **CameraChannel** model: D455-like intrinsics, 35 cm mount, frame envelopes
- [x] No EGL in pure layer; `CameraBackend` protocol for Opus MuJoCo
- [x] **DetectionNoiseAdapter**: range cutoff, `p_detect(distance)`, confusion, jitter
- [x] Produces/consumes `contracts.DetectionMsg`
- [x] Low-viewpoint gates (pass/fail + reason):
  - `ocr_upward_angle`
  - `legs_first_reid`
  - `vpr_at_35cm`
  - `curb_height_map_without_d455`
- [x] Intrinsics/mount align with K2′ bag `camera/color/meta` + HR-4

## Explicit non-claims (hardware-readiness honesty)

- **No real camera validation.** Nominal D455 numbers are sim/contract
  constants (`d455-intrinsics-nominal`), not commissioned calibration.
- Passing low-viewpoint gates on authored/synthetic metrics is **sim evidence
  only** — see [hardware-readiness.md](hardware-readiness.md) **HR-4**.
- `CameraChannel.capture` refuses to invent pixels without an Opus backend.
- Detection adapter noise is Habitat-style honesty for rung-7, not a fitted
  field detector model.

## Remaining (merged into K5_STATUS)

Opus wiring landed — see [K5_STATUS.md](K5_STATUS.md). Still out of K5:

- P5: re-run gate pack on day-one D455 bags (HR-4)
- Pixel detector cascade on rendered RGB (not privileged tracks)
- Hard-wire bridge into every headless tick (helpers exist)

## Test command

```bash
pytest tests/test_k5_camera_detection_gates.py -q
```
