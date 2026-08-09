# VISUAL-SEARCH FOUNDATION — B1 + B2 status (task_9, sol)

Detector-agnostic foundation for the generalized-visual-search arc
(scrum/20260809/task_4). Built so the owner's **B3** open-vocab detector pick
drops in behind a `Detector` protocol with zero change below it.

**Adopted stance (P0, owner-authorized default):** the sim proves the
pixels→localize→ground→lock-on **machinery** + geometry + false-positive
handling against MuJoCo **segmentation-truth** as the honest ruler. Real-texture
**recognition** is re-earned on hardware. This card therefore uses MuJoCo
segmentation as the detector stand-in behind the protocol — no external
open-vocab model (that is B3).

---

## B1 — MuJoCo-EGL intrinsics + extrinsics geometry fix

**Two silent geometry bugs found and fixed in
`src/parcel_robot/camera_channel/backends/mujoco_egl.py`:**

1. **Intrinsic (fovy).** The free camera rendered at MuJoCo's default
   `vis.global_.fovy = 45°`, i.e. `fy ≈ 869 px`, while the channel advertises
   `fx = fy = 644`. Every depth back-projection was silently ~35 % off. Fix:
   bind the render frustum to the explicit intrinsic
   `fovy = 2·atan(H/(2·fy)) = 58.41°`, which reproduces `fx = fy = 644`,
   `cx = 640`, `cy = 360` exactly (verified: `fy_reconstructed == 644.0`). A
   centered-principal-point + square-pixel guard rejects any intrinsic a free
   camera cannot represent (points at the fixed-MJCF-camera path, MuJoCo #1183).
2. **Extrinsic (camera pose).** `_free_camera` used the wrong MuJoCo
   azimuth/elevation convention (`az = deg(yaw) − 90`, `el = −deg(pitch)`), so
   even with the intrinsic corrected the back-projected world point landed
   **~0.28 m** off a small target. Fix: `az = deg(yaw)`, `el = deg(pitch)`,
   `lookat = centre + dist·viewdir` so the optical centre lands on the mount and
   the optical axis points along yaw at the mount's upward pitch. This matches
   `CameraExtrinsics.from_mount_pose` (the extrinsic B4 will build), which is the
   whole point — render pose and localizer extrinsic are now provably one model.

**Empirical, real MuJoCo render (this environment):**

| target | bugged (fovy 45, old az/el) | fixed |
|---|---|---|
| sphere r = 0.09 @ ~3.2 m | 0.28 m error | **0.069 m** (≈ radius; surface-vs-centre offset) |

The 0.069 m residual is the irreducible monocular surface-vs-volumetric-centre
offset (the back-projection sees the front surface ~one radius in front of
`geom_xpos`), not geometry error.

**Depth convention confirmed empirically:** MuJoCo `enable_depth_rendering`
returns perpendicular **z-depth** (distance along the optical axis), exactly the
`D` the OpenNav pinhole formula `X=(u−cx)D/fx, Y=(v−cy)D/fy, Z=D` wants.

**Seg-truth self-check (the ruler):** pure + guarded, in
`tests/test_k5_camera_detection_gates.py`:
- pure synthetic pinhole round-trip: back-projection is the exact inverse of
  projection to **< 1e-9 m**;
- pure seg-truth self-check (flat facing patch): world point lands on the
  seg-truth centroid to **< 0.01 m**;
- rigid-transform (SE2) equivariance of the localized world point to **< 1e-6 m**;
- **guarded real MuJoCo render**: back-projected geom centroid within
  `radius + 0.03 m`, and the un-fixed `fovy = 45` misses the *same* gate
  (`err_bug > radius+0.03` and `> 1.5× err_fixed`) — the fix is load-bearing.
  Skips cleanly where no offscreen GL context exists (CI).

---

## B2 — pixels → DetectionMsg via a Detector protocol

New pure module **`src/parcel_robot/detection_adapter/pixel_detections.py`**
(exported from `detection_adapter/__init__.py`):

- **`Detector` protocol** — `detect(rgb, depth, seg, query) -> list[PixelDetection]`.
  The single seam B3's real open-vocab detector satisfies.
- **`SegTruthDetector`** — the first (and only, pre-B3) impl: reads the MuJoCo
  segmentation buffer as a *perfect* detector (each geom id = one instance,
  `score = 1.0`), filtered by the queried noun. Recognition is perfect *by
  construction* — that is the point: it isolates geometry from recognition.
- **Localizer** (`localize_detection` / `localize_frame`) — the OpenNav recipe:
  segment → **erode 3×3** → **Z-score reject (τ=2)** depth outliers →
  back-project the inlier centroid pixel at its metric depth → `CameraExtrinsics`
  → world. Emits `contracts.DetectionMsg` with `bearing_rad`/`range_m` derived
  from that same world point (self-consistent with `bearing_range_from_pose`),
  `score` = detector conf, `class_id` = label, and an **embedding** =
  optional injected SigLIP crop embedding (`embed_fn`) **else** the deterministic
  label embedding (the DetectionMsg schema requires a non-empty embedding — there
  is no `None` seam, so the fallback keeps it contract-valid without hard-depending
  on the sibling's SigLIP).
- **Per-detection covariance** (`LocalizedDetection`, alongside the DetectionMsg
  since the schema has no covariance field): `sigma_range` from the
  perception_chain D455 quadratic model (`D455_DEPTH_SIGMA_COEFF_PER_M · r²`),
  `sigma_bearing` from box-centroid pixel error (`atan2(σ_px, fx)`), rotated into
  a 2×2 world `covariance_xy` — ready for D2/D4.

---

## B2 gate — T-cam-foundation eval tier (additive / opt-in)

New module **`evals/nav_instruct/cam_foundation.py`** + frozen pack
**`evals/nav_instruct/cam_foundation_pack.json`** + tests
**`tests/test_cam_foundation.py`**.

A deterministic **pinhole-projected synthetic** render pack (24 seeded scenes,
no GL → CI-safe) drives `SegTruthDetector` + the localizer and reports:

| metric | value |
|---|---|
| localization error (world point vs seg-truth centroid) | max **0.0076 m**, p95 0.0071, mean 0.0038 (bound 0.02) |
| right-object rate | **1.0** |
| recall (queried instance found) | **1.0** |
| scenes / detections | 24 / 24 |

Localization error is **near-zero by construction** — pure pixel-quantization,
not geometry error (the seg buffer IS the ruler). Scenes have clean
non-overlapping masks (occlusion/depth-bleed is D2's tier); a handful of gross
depth outliers per mask exercise the Z-score reject stage (a broken stage moves
the world point past the bound — asserted).

**Byte-equal proof (additive tier):** the tier adds **only new files** — it does
not touch `runner.py`, `perception_chain.from_tier`, the frozen episode sets, or
any frozen result JSON. Proven two ways in `tests/test_cam_foundation.py`:
- `test_frozen_gt_source_artifacts_are_byte_identical` pins the sha256 of the
  frozen v3 baseline + candidate reports and the v1/v2/v3 episode manifests;
- `test_tier_does_not_install_a_perception_chain` asserts the process-default
  ingress stays `T0` pass-through after running the tier.

Honesty (`does_not_prove`, carried in the report + the module): proves geometry
+ localization + the DetectionMsg pipeline + FP-handling machinery; **not**
real-texture recognition (B3 + hardware). No detector recognition accuracy is
claimed.

---

## What B3 drops into

The owner's detector pick implements **one method**:

```python
class MyOpenVocabDetector:              # satisfies detection_adapter.Detector
    name = "mm_grounding_dino"          # or NanoOWL / GDINO-1.5-Edge (hardware era)
    def detect(self, *, rgb, depth, seg, query) -> list[PixelDetection]:
        ...  # boxes on RGB; seg may be ignored (real detectors are box-only)
```

`localize_frame(detector, ...)` is unchanged: a box-only detection leaves
`seg_id=None` and the localizer falls back to the box interior (valid-depth) mask
instead of the exact geom mask. Everything below — erode/Z-score/back-project/
extrinsic/covariance/DetectionMsg — is already proven. The only new error a real
detector introduces is **recognition** (which box, which class), which then shows
up as a non-zero localization error and a right-object rate < 1.0 against the same
seg-truth ruler. Optional: pass `embed_fn` to attach real SigLIP crop embeddings
once the sibling's `embed_image` is importable + weighted.

B4 (opus) wires the camera onto the mission path; this card built the pure
producer + protocol + gates only, no runtime wiring.

---

## Files touched

New:
- `src/parcel_robot/detection_adapter/pixel_detections.py`
- `evals/nav_instruct/cam_foundation.py`
- `evals/nav_instruct/cam_foundation_pack.json` (frozen, regenerate via `--regenerate`)
- `tests/test_cam_foundation.py`

Modified:
- `src/parcel_robot/camera_channel/backends/mujoco_egl.py` (fovy + extrinsic fix, `render_fovy_deg`)
- `src/parcel_robot/detection_adapter/__init__.py` (exports)
- `tests/test_k5_camera_detection_gates.py` (B1 gate additions)

Untouched (per lane): `navigation/pipeline.py`, `runtime.py`,
`instructnav/grounding.py`, `instructnav/siglip.py`, `voice/**`, `brain/**`,
frozen eval packs/digests.

## Verify
- `tests/test_cam_foundation.py` + `tests/test_k5_camera_detection_gates.py`: **35 passed** (with and without `MUJOCO_GL`).
- Adjacent suites (perception_chain, metamorphic, scene_truth, episodes_v3, rescoring): green.
- ruff: new files clean; the one modified backend + K5 test clean (the pre-existing
  `close()` teardown `S110`/`BLE001` is noqa-covered, matching the committed
  `factory.py` pattern).
- Frozen digests byte-identical (pinned).
