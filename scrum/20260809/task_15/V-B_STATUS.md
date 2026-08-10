# Card V-B status — D1+D2 pure modules

Base: `60ecea24168f839cb107a818799d0bc424bfee1d`

## Delivered

- `src/parcel_robot/detection_adapter/multi_view_confirm.py`
  - Frozen `update(detection) -> (confirmed, credibility, rejected_ids)` surface.
  - Class-agnostic 3-of-5 distinct-view confirmation.
  - Noisy-OR credibility accumulation and bounded false-positive memory.
  - Explicit `None` input advances a view with no detection.
  - IPDA is documented as a seam and is not implemented.
- `src/parcel_robot/detection_adapter/metric_localizer.py`
  - Frozen static `[x, y]` Kalman fusion surface emitting position + covariance.
  - Direct adapter for B2 `LocalizedDetection`.
  - Low-viewpoint covariance awareness.
  - Two-ray motion-parallax fallback only for explicitly unreliable depth.
- `evals/nav_instruct/cam_multiview_metric.py`
  - Additive, standalone T-cam pure-cell report consuming the existing camera
    foundation pack without changing frozen artifacts or runtime wiring.
- `tests/test_vb_multiview_metric.py`
  - D1 M-of-N, duplicate-view, low-score accumulation, single-frame rejection,
    rejected-box memory, D2 covariance contraction, rigid-transform,
    parallax-only-on-unreliable-depth, low-viewpoint, and additive eval gates.

No existing source contract, frozen pack, runtime, camera-channel, navigation,
core, grounding, or SigLIP file was changed by V-B.

## Measured evidence

Operating-threshold cell uses the observed lamppost score sequence
`0.28, 0.35, 0.42`. It remains unconfirmed for views 1 and 2, then confirms on
view 3 at credibility `0.72856`. A score-1.0 singleton does not confirm.
There is no class-specific threshold or per-class gate.

Standalone T-cam pure report:

- scenes: 24
- confirmed scenes after three low-score views: 24/24
- single-frame commits: 0
- injected singleton false-positive commits: 0/12
- singleton hypotheses entered rejected memory: 12/12
- same-id next-scan recommits suppressed: 12/12
- fused planar localization error: mean `0.002608 m`, p95 `0.006249 m`,
  max `0.006834 m`
- low-viewpoint-aware scenes: nonzero (asserted by the eval gate)

## Commands and results

- `.parcel/bin/python -m pytest -q tests/test_vb_multiview_metric.py`
  - `10 passed in 0.44s`
- `.parcel/bin/python -m pytest -q tests/test_cam_foundation.py tests/test_k5_camera_detection_gates.py tests/test_vb_multiview_metric.py`
  - `45 passed in 2.49s`
- `.parcel/bin/python -m ruff check src/parcel_robot/detection_adapter/multi_view_confirm.py src/parcel_robot/detection_adapter/metric_localizer.py evals/nav_instruct/cam_multiview_metric.py tests/test_vb_multiview_metric.py`
  - all checks passed
- `.parcel/bin/python -m evals.nav_instruct.cam_multiview_metric`
  - deterministic report with the measurements above
- `.parcel/bin/python scripts/ci_gate.py --tier commit`
  - first run: 7/8 hard gates passed; default suite had one transient,
    out-of-scope multiprocessing failure in
    `test_spawned_paired_builders_return_to_parent_for_exclusive_evidence_write`
  - isolated rerun of that exact test: `1 passed`
  - authoritative full-gate retry (2026-08-09T22:29:09Z): recorded below
- Sol stand-in re-verify (post API-limit):
  - `.parcel/bin/python -m pytest -q tests/test_vb_multiview_metric.py` → `10 passed in 0.45s`
  - V-B-owned ruff check → all checks passed
  - OWNS: MUST-NOT-TOUCH paths clean; no runtime/camera_channel/grounding wiring

## Does not prove / deferred

- No runtime wiring landed. The modules do not yet influence SEARCH, NAVIGATE,
  K0, or arrival.
- The pure FP cell proves no singleton can commit and rejected memory suppresses
  its next scan. It does not prove end-to-end T-cam false-positive *arrival*;
  full absent-target/runtime wiring belongs to Wave-2 V-E.
- Repeated, view-consistent hallucinations can still satisfy finite M-of-N.
  IPDA/existence-probability is intentionally not implemented.
- Seg-truth recognition is perfect by construction. Results do not prove
  real-texture open-vocabulary recognition, real D455 depth/calibration, or
  hardware low-viewpoint performance.
- The parallax fallback is two-ray static geometry, not bundle adjustment,
  image-based visual servoing, or moving-target estimation.

## Blockers

None inside V-B ownership. Full T-cam FP-arrival and lock-on gates require the
runtime integration owned by V-E; this card did not invade that scope.

## Final commit-tier gate

Authoritative retry: `.parcel/bin/python scripts/ci_gate.py --tier commit`
at `2026-08-09T22:29:09Z` — **FAIL 7/8 hard gates** (elapsed 104.2s).

| Gate | Result |
|---|---|
| ruff | FAIL — 40 violation(s), baseline 39, new 2 → `src/parcel_robot/core/hard_stop.py::RUF022`; `tests/test_core_hard_stop.py::I001` (out of V-B OWNS; S-A/core card residue) |
| hard-safety | PASS |
| frozen-digest-sentinels | PASS |
| model-off-non-inferiority | PASS — 23 passed in 0.46s |
| frozen-digest-integrity | PASS — 6 passed, 1 warning in 0.30s |
| mutation-panel-freshness | PASS — 1 passed in 0.09s |
| latency-tail | PASS — 6 passed, 2 warnings in 0.27s |
| default-suite | PASS — 3188 passed, 9 skipped, 34 deselected, 5 warnings in 101.45s |

Sole red is out-of-scope ruff on `core/hard_stop.py` / `tests/test_core_hard_stop.py`.
V-B module tests green (`10 passed`); V-B-owned ruff clean. No habitat-smoke red
this run. V-B did not touch those files and must not fix them under OWNS.
