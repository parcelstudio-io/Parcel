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

### CORRECTION (lane E4, 2026-08-10) — what the old headline claimed vs proved

Fable's independent audit returned this card on evidence strength. Three findings,
all confirmed by E4 and all now corrected:

1. **`PARCEL_OWLV2_THRESHOLD` was never exercised by any V-B file.** The card
   claimed a lower detector operating point was safe without ever running the
   detector at one. Repo-wide the env var appeared only in `b4_gate.py` and
   `owlv2_onnx.py`.
2. **`scores = (0.28, 0.35, 0.42)` was a HARDCODED LITERAL** at
   `cam_multiview_metric.py:45`, described as "the observed lamppost score
   sequence". It was not a recording.
3. **`false_positive_commits=0` was ARITHMETICALLY GUARANTEED**: one
   `confirmer.update(phantom)` on a fresh `MultiViewConfirm` per phantom, against
   a 3-of-5 rule. One view can never satisfy 3-of-5. It is a single-frame-
   rejection assertion, not a false-positive measurement.

**The "a lower detector operating point is safe" framing is DELETED.** What
replaces it is measured, in the honest form the measurement supports.

### NEW: live operating-point cell (option (a) — the real detector was run)

`evals/nav_instruct/cam_multiview_metric.py::evaluate_live_cells`,
tier id `T-cam-proxy-vb-live`. Real OWLv2 ONNX on live MuJoCo-EGL renders of the
b4-gate lamppost prop, from **5 distinct camera poses** on a 3.0 m orbit
(azimuths −40°/−20°/0°/+20°/+40°, each facing the target). Every score below is
recorded by the run.

```
MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 \
  .parcel/bin/python -m evals.nav_instruct.cam_multiview_metric --live
```

| | threshold **0.2** | threshold **0.55** (unmodified grounder floor) |
|---|---|---|
| distinct views | 5 | 5 |
| views yielding a box | **5 / 5** | **1 / 5** |
| recorded lamppost scores | `0.4309, 0.4598, 0.5539, 0.3139, 0.2308` | `0.5539` (the other four fall below the gate) |
| lamppost confirmed (3-of-5) | **yes, on view index 2**, credibility 0.86285 | **no** — 3-of-5 unreachable |
| absent-class (`"fire hydrant"`) boxes | **0** across 5/5 views | **0** across 5/5 views |
| `live_absent_class_commits` (measured) | **0** | **0** |
| `live_repeated_phantom_commits` (measured) | **1**, on view index 2 | 0 (never reaches 3 views) |

Credibility trace at 0.2: `0.43086 → 0.69254 → 0.86285 → 0.90589 → 0.92761`.
Re-run after an internal refactor: identical.

**What this supports, stated exactly.** On this prop, lowering the operating
point from the unmodified 0.55 grounder floor to 0.2 is what makes multi-view
confirmation *possible at all*: at 0.55 only one of five views survives the gate
and the 3-of-5 rule can never be met; at 0.2 all five survive and confirmation
lands on the third view. In the same run the absent class produced **zero** boxes
at both operating points, so the extra recall was not bought with a hallucination
**on this scene**.

**What this refutes.** It is *not* evidence that a lower operating point is safe.
The same run injects a view-consistent phantom — a hypothesis with no object
behind it, re-observed at constant bearing/range — and it **commits on exactly
the same view as the real target**. Finite-window M-of-N offers no protection
against a persistent false positive. `false_positive_commits = 0` must never be
quoted from this card without that sentence.

### Pure cell (unchanged in value, corrected in description)

`tier_id` is now `T-cam-proxy-vb-pure` and the report carries
`operating_scores_are_synthetic: true` and
`false_positive_commits_is_arithmetic: true`. Numbers are byte-unchanged so the
two publications stay comparable:

Operating-threshold cell uses a **synthetic** score sequence
`0.28, 0.35, 0.42` (a literal, not a recording). It remains unconfirmed for views
1 and 2, then confirms on view 3 at credibility `0.72856`. A score-1.0 singleton
does not confirm. There is no class-specific threshold or per-class gate.

Standalone pure report (`T-cam-proxy-vb-pure`):

- scenes: 24
- confirmed scenes after three low-score views: 24/24
- single-frame commits: 0
- injected singleton false-positive commits: 0/12 — **arithmetically guaranteed,
  not measured** (one `update()` per phantom against a 3-of-5 confirmer)
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
