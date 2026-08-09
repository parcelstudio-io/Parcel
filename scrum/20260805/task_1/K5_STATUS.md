# K5 Status — CameraChannel + DetectionAdapter + low-viewpoint gates

**Card:** K5 · **Lane:** Sol (pure) + Opus (sim) · **Date:** 2026-08-05 ·
**State:** DONE (pure modules + sim/CI wiring; **no** real D455 validation, **no** Nav2)

## Verdict

Sol delivered the pure CameraChannel / DetectionNoiseAdapter / low-viewpoint gate
pack. Opus wired a **MuJoCo-EGL CameraBackend** (when offscreen GL works) plus a
deterministic **synthetic backend** for CI, a thin sim→DetectionMsg agent path
through the noise adapter, and a sample-config smoke for the gate pack.

## Delivered

| Artifact | Path | Lane |
|---|---|---|
| CameraChannel package | `src/parcel_robot/camera_channel/` | Sol |
| D455 + 35 cm mount constants | `…/camera_channel/d455.py` | Sol |
| RGB / depth / seg envelopes | `…/camera_channel/frames.py` | Sol |
| Channel + `CameraBackend` protocol | `…/camera_channel/channel.py` | Sol |
| Synthetic CameraBackend (CI) | `…/camera_channel/backends/synthetic.py` | Opus |
| MuJoCo EGL CameraBackend | `…/camera_channel/backends/mujoco_egl.py` | Opus |
| Backend factory / probe | `…/camera_channel/backends/factory.py` | Opus |
| DetectionMsg noise adapter | `src/parcel_robot/detection_adapter/` | Sol |
| Sim→DetectionMsg bridge | `…/detection_adapter/sim_bridge.py` | Opus |
| Low-viewpoint gate pack | `src/parcel_robot/low_viewpoint/` | Sol |
| Sample configs + smoke | `…/low_viewpoint/samples.py` + `runtime_assets/configs/perception/low_viewpoint_samples.yaml` | Opus |
| CI tests (Sol) | `tests/test_k5_camera_detection_gates.py` | Sol |
| CI tests (Opus) | `tests/test_k5_opus_sim_wiring.py` | Opus |

## Checklist

### Sol (pure)

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

### Opus (sim / wire)

- [x] MuJoCo offscreen EGL backend implementing `CameraBackend` (when GL available)
- [x] Deterministic synthetic backend so CI stays green without EGL
- [x] Factory `prefer=auto|synthetic|mujoco_egl` + `probe_mujoco_offscreen`
- [x] Wire DetectionMsg noise adapter into sim→DetectionMsg agent path
- [x] Privileged GT helper isolated for scorer/tests only
- [x] Low-viewpoint gate pack smoke against authored sample YAML
- [x] Document real-EGL path as UNVERIFIED / HR-4 (no hardware claims)

## Test commands

```bash
# CI-safe (synthetic backend; EGL test skips if offscreen unavailable)
.parcel/bin/python -m pytest tests/test_k5_camera_detection_gates.py tests/test_k5_opus_sim_wiring.py -q

# Optional local EGL (set before process start / first mujoco import)
MUJOCO_GL=egl .parcel/bin/python -m pytest tests/test_k5_opus_sim_wiring.py::test_mujoco_egl_backend_optional -q
```

## Explicit non-claims (hardware-readiness honesty)

- **No real camera / D455 validation.** Nominal intrinsics and 35 cm mount are
  sim/contract constants (`d455-intrinsics-nominal`), not commissioned calibration.
- **MuJoCo EGL renders are synthetic pixels.** Enabling `MUJOCO_GL=egl` proves
  envelope wiring + offscreen render plumbing only — see
  [hardware-readiness.md](hardware-readiness.md) **HR-4** (status remains
  **unvalidated**).
- CI synthetic backends prove **envelope / adapter / gate wiring**, not
  perception accuracy.
- Passing low-viewpoint gates on authored YAML metrics is **sim evidence only**.
- Detection adapter noise is Habitat-style honesty for rung-7, not a fitted
  field detector model.
- Agent path must consume noisy `DetectionMsg`; privileged GT helpers are
  scorer/test-only.
- **No Nav2.**

## Honest gaps (remaining)

| Gap | Notes |
|---|---|
| Real-EGL in CI | Not assumed; synthetic backend is the CI default |
| Mount-aligned camera in full city scenes | Free-camera approx from SE2 + mount; not a calibrated D455 extrinsic on Go2 mesh |
| Pixel→detector cascade | Bridge uses privileged semantic tracks → noise adapter, not NanoOWL on rendered RGB |
| HeadlessCity observe integration | Bridge helpers exist; not yet hard-wired into every headless tick |
| P5 HR-4 | Re-run gate pack on day-one D455 bags; report delta vs sim |

## Pointers

- Sol-only notes: [K5_SOL_STATUS.md](K5_SOL_STATUS.md)
- Hardware ledger: [hardware-readiness.md](hardware-readiness.md) HR-4
