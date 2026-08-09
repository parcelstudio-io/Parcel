# B3 — the real open-vocab DETECTOR (task_11, Sol 5.6 Ultra + Opus)

Makes camera-search **real** behind the proven `detection_adapter.Detector`
protocol: a real open-vocabulary detector runs on rendered pixels and returns
boxes with `label`/`score`/`box`, `seg_id=None`; the B2 localizer falls back to
the box-interior valid-depth mask and everything below (erode/Z-score/back-project/
extrinsic/covariance → `DetectionMsg`) is unchanged. The protocol and
`localize_frame` were NOT touched — this card only added an implementation behind
the seam and a new eval cell that runs it alongside `SegTruthDetector`.

## Headline (read this first)

**Detector: OWLv2 — `google/owlv2-base-patch16-ensemble`, int8 ONNX, LICENSE =
Apache-2.0 (product-clean).** Reached, fetched no-sudo, loads under onnxruntime
(CPU), and produces correct boxes on real MuJoCo renders. The real gate ran.

| metric (8-scene MuJoCo render pack, 18 GT instances) | SegTruth (geometry-only ruler) | **OWLv2 (recognition + geometry)** |
|---|---|---|
| right-object rate | 1.0 | **1.0** |
| recall (GT instances found) | 1.0 | **0.889** (16/18) |
| localization error vs seg-truth ruler | 0.0 (by construction) | mean **0.075 m**, p95 0.140 m, max 0.223 m |
| ms/query (CPU) | ~13 ms | **~559 ms** (OFF the 10 Hz path) |

**Recognition-error DELTA (the honest number the P0 stance predicts):**
right-object drop **0.0**, recall drop **0.111** (2 missed instances), localization
error added **0.075 m mean / 0.223 m max** (well under the 0.30 m budget, decimeters
below the 1.0 m arrival band). All recognition error surfaces as *missed detections*
+ *box-vs-mask centroid drift* on top of already-proven geometry — exactly as B2
predicted a real detector would.

`does_not_prove`: rendered MuJoCo textures are NOT photoreal, so this recall tests
the pixels→localize→ground→lock-on pipeline + a **floor** of recognition, NOT
real-world D455 recognition (a hardware re-earn). No field recall/precision claimed.

## Detector pick + why (license-clean, verified reachable/runnable BEFORE committing)

- **PICK: OWLv2 open-vocab, Apache-2.0.** Upstream `google/owlv2-base-patch16-ensemble`
  is Apache-2.0 (verified via HF model card: `license=apache-2.0`). The ONNX export
  `onnx-community/owlv2-base-patch16-ensemble-ONNX` (tags: transformers.js, onnx,
  owlv2, zero-shot-object-detection; `base_model:google/owlv2-base-patch16-ensemble`)
  inherits Apache-2.0 + Apache/MIT export tooling — the natural sibling of the
  SigLIP `onnx-community` int8 pattern.
- **YOLO-World fallback NOT adopted** (and flagged): faster, but AGPL/Ultralytics —
  a product-license risk. Not needed since the Apache option is reachable + runnable.
- **Reachability verified first** (my guesses have 401'd before): `onnx-community/owlv2-*`
  without the `-ONNX` suffix 401s; **`onnx-community/owlv2-base-patch16-ensemble-ONNX`
  exists** and serves the int8 export. LFS oid == file sha256 confirmed via the CDN
  `X-Linked-ETag`, so the big-file pin is exact.
- **Variant: int8 (`model_int8.onnx`, 163 MB).** onnxruntime here is **CPU-only**
  (providers: CPU + Azure; the RTX 5000 is NOT reached by ORT) and VRAM is claimed by
  Gemma + Fish, so the pick is CPU/RAM-driven: fp32 (614 MB) is the heavy accuracy
  ref; fp16 (307 MB) is a poor CPU pick (x86 up-casts fp16→fp32, no speedup); int8
  runs on ORT native int8 CPU kernels. `model_int8` == `model_quantized` ==
  `model_uint8` by content on this export (identical sha).

## What was fetched (`scripts/fetch_owlv2.sh`, no-sudo, sha-pinned, .part staging, ran in ~25 s)

Mirrors `fetch_siglip2.sh` exactly (curl/wget fallback, sha256-gated, idempotent,
`--force`). Landed in `~/.cache/parcel/owlv2-b16` (override `PARCEL_OWLV2_DIR`):

| file | bytes | sha256 |
|---|---|---|
| `model_int8.onnx` | 163,173,570 | `e9cc288738a96a5a9b730801f622b2e1a531ed2a93d02dd1227a4d35fd9690c6` |
| `tokenizer.json` | 3,642,208 | `e277946093d72c7748281a6a344d6c79a5226c48954d6797dc36984aea23ac60` |
| `config.json` | 544 | `9222fb235dd16154d94e7bdc7f4d8b0c0bf696eba9f68fd260da6733fd18f731` |
| `preprocessor_config.json` | 425 | `cf3e396635b797ee1a464e1b2836e98748f8edac19e89aaa2c93b55ac15b0064` |
| `tokenizer_config.json` | 960 | `bf011c6d421981c3102428c6390472e83d8c097653262b15573ff10af44348ee` |
| `special_tokens_map.json` | 576 | `c4dbb96da703fb38f10ccf0490df2fd476811c5a3e71b7e0189cffeed3224e25` |

No new pip wheels needed — `onnxruntime` + `numpy` + `tokenizers` (the SigLIP rust
wheel) were already in `.parcel`. No torch, no transformers, no PIL.

## Detector impl (`src/parcel_robot/detection_adapter/owlv2_onnx.py`)

`OwlV2Detector` satisfies `detection_adapter.Detector` (`name="owlv2"`,
`detect(*, rgb, depth, seg, query) -> list[PixelDetection]`):

- **ONNX I/O (verified by loading the model):** inputs `input_ids[Q,16]`,
  `attention_mask[Q,16]`, `pixel_values[1,3,960,960]`; outputs `logits[1,3600,Q]`,
  `pred_boxes[1,3600,4]` (cxcywh, normalized to the padded square). 3600 = (960/16)².
- **Preprocess (numpy only, no PIL):** rescale 1/255 → **pad to square** with gray
  0.5 (bottom-right) → bilinear resize 960 (half-pixel centered) → CLIP mean/std,
  matching `Owlv2ImageProcessor`.
- **Text (tokenizers rust wheel):** CLIP tokenizer from `tokenizer.json` (bos 49406 /
  eos 49407 / pad `!`=0), lower-cased, right-padded/truncated to **16** with an
  attention mask. `_`/`-` → space so sim nouns (`trash_can`→`trash can`) tokenize.
- **Decode:** `score = sigmoid(logit)` per (box, query); threshold (default 0.1,
  `PARCEL_OWLV2_THRESHOLD`); box mapped to image px by `* max(H,W)` (OWLv2 pads
  bottom-right, top-left origin shared) then clipped; per-label greedy NMS (IoU 0.3),
  capped at 64. Returns `PixelDetection(label, score, box, seg_id=None)`.
- **Loud degrade → "detector unavailable" (never crashes):** opt-in `PARCEL_OWLV2_ONNX`
  (default OFF ⇒ `load_owlv2_detector()` returns `None` **even with weights present**),
  so CI/mission stay byte-identical; absent weights / absent onnxruntime / absent
  tokenizers all degrade to `None` with a warning. Proven byte-identical below.

## Wired into the T-cam tier ALONGSIDE SegTruthDetector (`evals/nav_instruct/cam_detector.py`)

A NEW, additive `T-cam-detector` cell (sibling of the foundation's `cam_foundation`):
builds a deterministic 8-scene MuJoCo set of recognizable colored primitives (red
ball / green box / blue cylinder / …), renders real RGB+depth+seg via the existing
`MujocoEglCameraBackend`, and runs BOTH `SegTruthDetector` (geometry-only ruler) and
`OwlV2Detector` (recognition + geometry) through the **same `localize_frame` seam** on
the identical frames. Localization error is measured **OWLv2-vs-SegTruth** (not vs the
volumetric geom centre) so the common monocular surface-vs-centre offset cancels and
the number is pure recognition. NOT on the runtime mission path (that is B4).

- **Optional SigLIP embed_fn seam:** left at the default deterministic label embedding
  — the sibling's `embed_image` (`instructnav.siglip2_onnx`) is importable and the
  vision weights are present, but wiring real crop embeddings through `embed_fn` is
  B4/D-lane work (the DetectionMsg embedding is not on the B3 gate). The seam is ready.
- **Guarded / opt-in:** the cell runs only with `MUJOCO_GL=egl` **and**
  `PARCEL_OWLV2_ONNX=1` **and** weights present; otherwise it returns
  `{"status":"skipped","blocker":…}` (never raises). Renders are not byte-frozen (GL
  is driver-dependent) — this is an on-demand gate, not a frozen digest.

Run: `MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 .parcel/bin/python -m evals.nav_instruct.cam_detector --report`

## Gate results

- **fetch runs no-sudo + model loads via onnxruntime** — ✅ (25 s fetch; 0.37 s load).
- **real detector produces boxes on the rendered pack; right-object/localization
  reported** — ✅ (table above). Empirically: red ball 0.66 score, green box 0.14–0.17,
  boxes land on the objects; localizes to within 0.05–0.22 m of the seg-truth ruler.
- **detection stays OFF the 10 Hz path** — ✅ ~559 ms/query CPU (`off_10hz_path=True`);
  a discrete grounding-time query, never per-tick.
- **T-cam frozen T0/T1 GT-source baselines byte-equal (additive/opt-in)** — ✅ proven:
  (1) my footprint is new files + additive `__all__` exports only — no `runner.py`, no
  `perception_chain.from_tier`, no frozen pack, no frozen result JSON touched; (2) with
  `PARCEL_OWLV2_ONNX` unset, `load_owlv2_detector()` returns `None` even with weights on
  disk (`test_default_is_detector_unavailable`); (3) `cam_foundation --check` →
  `drifted: false` (foundation pack digest unchanged); (4) the frozen nav_instruct
  digest tests (`test_nav_instruct_episodes_v2`/`_v3`, embodied 997 row) pass inside the
  full suite.
- **full suite 0 failed** — ✅ `pytest -m 'not slow'` (env OFF, CI-like): **3097 passed,
  9 skipped, 33 deselected, 0 failed** in 97 s. The 9 skips include this card's 2
  real-weight OWLv2 cells (`skipif` no weights/env). (The 3 `conversation_quality_v1`
  reds the SigLIP lane saw earlier are now green — another lane's manifest churn
  resolved; none referenced my files.)
- **ruff clean** — ✅ on all 4 new/modified Python files; `bash -n` clean on the fetch script.
- **frozen nav_instruct digests immutable** — ✅ (covered by the passing frozen-digest tests).

New tests (`tests/test_owlv2_detector.py`): loud-degrade (env-off/absent-weights →
None), pure decode math against a **mock onnxruntime session** (box cxcywh→pixel
mapping incl. pad-square scaling + clipping, sigmoid threshold, per-label NMS, phrase
normalization, fixed-16 tokenize + attention mask, pad-to-square preprocess), plus
`skipif`-guarded real-weight + real-render recognition cells. 12 passed / 2 skipped
(env off); 13 passed / 1 skipped (env on + EGL).

## Files touched (mine only)

- **NEW** `scripts/fetch_owlv2.sh` — sha-pinned no-sudo fetch (Apache-2.0 header).
- **NEW** `src/parcel_robot/detection_adapter/owlv2_onnx.py` — `OwlV2Detector` + loader.
- **NEW** `evals/nav_instruct/cam_detector.py` — the `T-cam-detector` real-detector cell.
- **NEW** `tests/test_owlv2_detector.py` — CI-safe + guarded real-weight tests.
- **MOD (additive)** `src/parcel_robot/detection_adapter/__init__.py` — export
  `OwlV2Detector`, `load_owlv2_detector`, `owlv2_*`, `OWLV2_DOES_NOT_PROVE`.
- Weights (cache, gitignored): `~/.cache/parcel/owlv2-b16/`.

(Working-tree changes to `mujoco_egl.py`, `dynamic_prompting.py`, `voice_audio.py`,
`tiered_memory.py`, `cam_foundation*`, `backlog/`, the ledger, etc. are the
concurrent gesture / tiered-memory / foundation lanes — NOT this card.)

## What B4 (camera on the mission path) needs next

1. **Attach + capture on-mission:** build the EGL backend via
   `camera_channel.backends.factory.open_camera_backend(model, data)`,
   `CameraChannel.attach_backend()`, capture per relevant tick, run `OwlV2Detector`
   → `localize_frame` → `DetectionMsg`, feed those through the SAME perception chain so
   `extras['semantic_candidates']` derive from RENDERED PIXELS, not the GT frustum.
   `MUJOCO_GL=egl` must be set before the first `mujoco` import (factory enforces).
2. **Keep detection ASYNC / off the 10 Hz control tick** — it is ~559 ms/query CPU. Run
   it at command-interpretation / scan-dwell cadence and propose into the arbiter; the
   reactive gate must never wait on it.
3. **Threshold calibration on a real pack:** 0.1 is the transformers default;
   `PARCEL_OWLV2_THRESHOLD` is the knob. Recall drop (0.111 here) trades against
   false-positive rate — D1's multi-view / M-of-N / FP-memory is what absorbs the FP
   side once the oracle is gone. Calibrate against the FP tier, never against the
   unseen split.
4. **Real crop embeddings (optional):** pass `instructnav.siglip2_onnx.embed_image` as
   `localize_frame(..., embed_fn=...)` so DetectionMsg carries real SigLIP crop vectors
   instead of the label embedding (both weights + seam are present now).
5. **Honesty stays binding:** every T-cam number carries the P0 `does_not_prove` — sim
   recognition on non-photoreal renders is a FLOOR, not a field claim. Recognition
   accuracy is re-earned on hardware; the DELTA reported here is the sim recognition
   error on top of proven geometry.
