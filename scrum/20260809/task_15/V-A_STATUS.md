# Card V-A status — B4 arrival closure (pixel path arrives)

Base: `60ecea24168f839cb107a818799d0bc424bfee1d`

Status: **complete**. Live b4 Mission A flips `arrival=succeeded` with
`candidate_source=pixel_detector`. Authoritative `ci_gate --tier commit` GREEN.

## Delivered

- `src/parcel_robot/camera_channel/ingress.py`
  - `radius_m_from_box_depth(box, depth_m, fx)` — honest footprint =
    box angular half-extent × depth (`(side_px/2) * D / fx`).
  - Full city_semantics near-envelope field set stamped on every pixel
    candidate via consumed `object_near_envelope_m` (not edited):
    `radius_m`, `stand_off_m`, `arrival_radius_m`,
    `minimum_vicinity_radius_m`, `vicinity_radius_m`,
    `target_min_surface_clearance_m`, plus the city-parity clearance fields.
  - Centre recovery: front-surface (min valid box depth) back-projection,
    then +`radius_m` along robot→surface, so `position` matches the
    city-object CENTRE convention (median-inlier depth alone sits inside
    curved bodies and misaligns the 0.2 m surface-clearance band).
- `scrum/20260809/task_12/b4_gate.py` (owned rig)
  - Target geoms use HeadlessCityWorld LiDAR prefixes (`obstacle_` / `lamp_`)
    so terminal near-verification can observe the target surface.
  - Capturing navigator already reports arrival metadata
    (`candidate_radius_m`, vicinity, reason).
- `evals/nav_instruct/cam_arrival.py` + `tests/test_cam_arrival.py`
  - Additive T-cam-arrival cell: offline envelope contract
    (stand_off inside planning band; envelope == `object_near_envelope_m`).
- `tests/test_runtime_activation.py`
  - Pins `radius_m_from_box_depth`, envelope stamping, centre push.

MUST NOT touched: `runtime.py`, `instructnav/scoring.py`, `navigation/**`,
`detection_adapter/**`, existing `cam_foundation.py` / `cam_detector.py`.

## Measured evidence (Mission A — live OWLv2 + EGL)

**RE-RECORDED 2026-08-10 by lane E4 on the repaired tree.** The block below is
this run, not the pre-repair one. Superseded numbers are kept at the bottom of
this section so the delta is visible rather than quietly overwritten.

Tree state: `HEAD = 6bd945d` **plus the uncommitted E1 (import-cycle) + E2
(safety-wiring) + E3 (eval-integrity) repairs**. Command run verbatim, no
wrapper, no preload:

```
MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 \
  .parcel/bin/python scrum/20260809/task_12/b4_gate.py A
```

| field | value (2026-08-10 re-run) |
|---|---|
| `arrival` | **succeeded** |
| `candidate_source` | **pixel_detector** |
| `grounding_outcome` | RESOLVED |
| `resolution_state` | verified |
| `mission_status` / `reason` | arrived / arrived_verified |
| `arrival_trigger` | goal_region |
| OWLv2 confidence | 0.858 |
| localization error vs truth | **0.035 m** |
| **arrival distance** (`final_distance_m`) | **1.717 m** (inside band [1.5263, 1.7263]) |
| `candidate_radius_m` | 0.4063 |
| vicinity band | [1.5263, 1.7263] m |
| oracle objects seen by navigator | 0 |
| **wall time** | 0.41 s closed-loop (68 steps); 2.2 s process wall incl. imports |
| detect / ingress read | 598.3 ms vs 0.071 ms max |
| `owlv2_threshold` | 0.1 (unset → default) |

### Reproducibility and tree-state attribution

* Two consecutive runs on the repaired tree: **byte-identical except the timing
  fields** (`detect_ms`, `ingress_detect_ms`, `ingress_read_max_ms`,
  `wall_time_s`). Every geometry/confidence field is deterministic.
* Controlled A/B — `git checkout HEAD -- camera_channel/ingress.py
  headless_city.py`, re-run, restore: the report is **identical modulo timing**.
  So the E1/E2/E3 repairs move **nothing** in this measurement.
* E3's pixel-clearance derivation confirmed bit-identical to the literals it
  replaced (`struct.pack('<d', …)` equality):
  `arrival_radius_m 0.06`, `target_surface_clearance_m 0.8`,
  `footprint_radius_m 0.32`. Metadata unchanged, as predicted.

### Superseded numbers (pre-repair publication)

The originally published row read confidence `0.881`, localization error
`0.037 m`, `candidate_radius_m 0.4156`, band `[1.536, 1.736]`. Those do **not**
reproduce today. The controlled A/B above rules out the repair lanes as the
cause, so the residual is the detector/render stack across sessions, not a code
change in this batch. **The gate verdict is unchanged and re-earned:
`arrival=succeeded` with `candidate_source=pixel_detector`.** The exact
confidence/radius are re-recorded above and the old ones are not restated as
current.

Mission B (lamppost recognition floor) was not required for the V-A gate;
OWLv2 scores there remain below the unmodified 0.55 grounder floor — now
**measured** across five distinct views in V-B's live cell.

## Offline / additive gates

- `.parcel/bin/python -m pytest -q tests/test_runtime_activation.py tests/test_cam_arrival.py -k "not live_owlv2"`
  - **20 passed**
- `.parcel/bin/python -m evals.nav_instruct.cam_arrival`
  - `stand_off_inside_planning_band=true`, envelope match true, `radius_m=0.4006`
- Flag-off byte-identical: `test_semantic_candidates_default_is_oracle_byte_identical` +
  `model-off-non-inferiority` hard gate PASS (camera ingress default OFF → oracle path).
- `.parcel/bin/ruff check` on owned files: clean.

## Authoritative CI

`.parcel/bin/python scripts/ci_gate.py --tier commit`

- **PASS — every hard gate green** (elapsed ~103 s)
- ruff: 7 violation(s), baseline 7, new 0
- default suite: **3210 passed**, 9 skipped, 34 deselected
- frozen digests unmoved; model-off-non-inferiority green

## Why plain `radius_m` alone was never enough (task_12, confirmed)

Stand-off and the vicinity band are both additive in `r`, so the surface-clearance
verify band stays `[0.8, 1.0]` for every radius. Closing arrival required:
(1) the full envelope field set city objects already stamp, and (2) a CENTRE
position (front depth + radius), not a median-depth surface point. The synthetic
rig also needed LiDAR-visible geom name prefixes — without them verification
fails closed as `target_surface_unobserved`. Band constants were not touched.

## does_not_prove

- Field D455 recognition / photoreal recall (rendered MuJoCo floor only).
- Lamppost Mission B arrival (recognition floor; V-B multi-view absorber).
- Runtime.py wiring changes (flag path already live from B4; this card only
  made pixel candidates arrival-capable).
- Wave-2 detection-triggered SEARCH→NAVIGATE lock-on (V-E).
