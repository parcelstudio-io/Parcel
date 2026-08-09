# Sol review of Opus · N11 wiring (2026-08-06)

**Reviewer:** Sol 5.6 Ultra (cross-review stand-in)  
**Subject:** Opus N11 seam wiring — `rank_approach_candidates` +
`RampMemory` / `seed_ramp` into approach / pipeline / grid / runtime  
**Sources:** `OPUS_N11_STATUS.md`, `SOL_N11_SUPPORT.md`,
`scrum/20260806/task_1/SOL_N11_STATUS.md`, diffs in
`approach.py`, `pipeline.py`, `grid_navigator.py`, `runtime.py`,
`tests/test_approach_traffic_wiring.py`, `tests/test_voice_nav_e2e.py`  
**Out of scope for re-litigation:** pure `traffic_aware` contract (already
arbitrated SB-1..SB-7); `proxemic_approach` (parked, correctly unwired).

---

## Verdict: **APPROVE**

Opus composed the Sol pure APIs at the right seams, preserved the empty-tracks
ladder, kept RampMemory off the safety-gate path, and left the pedestrian e2e
xfail honest. No must-fixes.

Verified locally:
`pytest tests/test_traffic_aware.py tests/test_approach_traffic_wiring.py tests/test_navigation.py -q`
→ **102 passed**.

---

## Criteria checklist

| Criterion | Result | Evidence |
| --- | --- | --- |
| Empty tracks ⇒ byte-identical static order (ladder) | **Pass** | `safe_approach_pose` only bumps `traffic_weight` to 2.0 when `tracks` is truthy; empty/`()` keeps weight 1.0 and skips the track-LiDAR filter. `_rank_approach_point` → `rank_approach_candidates(..., static_cost_fn=distance)`. Pinned by `test_safe_approach_empty_tracks_matches_static_nearest` + pure `test_empty_tracks_ordering_identical_to_static_ordering`. |
| Uses `traffic_aware.tracks_from_payload` at approach seam (not numpy `dynamic_layer`) | **Pass** | `_dynamic_tracks_from_observation` imports `traffic_aware.tracks_from_payload` only; loud-then-degrade on `TypeError`/`ValueError` → `()`. Grid navigator still uses `dynamic_layer` for its planner cost mask — correct split; approach seam is clean. |
| RampMemory never bypasses person-stop / collision / reactive safety | **Pass** | `note_stopped` on `cnote == "person_stop"`; `person_gate_stop` captured **before** shield note rewrite; zero return retained. Same-tick vx lift requires `cnote == "clear"` and runs **before** all-ray shield; then `_stop` notes still zero. Runtime seed clamped to authorised `command.vx` and dropped on stopping/emergency. Downstream `_collision_safe` / reactive policy untouched. |
| Xfail not flipped without hard pass | **Pass** | `test_go_to_the_sidewalk_with_pedestrian_traffic` still `@pytest.mark.xfail`; reason updated with measured post-wiring near-miss (`step_timeout` at ~y=2.07). Matches OB-9. |
| Correct composition of Sol pure APIs; no silent weakening | **Pass** | Ranking seam is `rank_approach_candidates` (not `proxemic_approach.reject_cost` — correctly refused as fail-closed / ladder-breaking). Metadata records `approach_static_cost` / `approach_traffic_cost` / `approach_total_cost`. Soft `RampMemory` import degrades to no pacing (OB-1). Align/zero ticks do not `note_running` below `RAMP_RUNNING_FLOOR_MPS` (OB-4). |

---

## What looks good

- **Seam 1 shape matches the support note:** tracks threaded from
  `_commit_semantic_candidate` → `safe_approach_pose` → polygon/near min-pick
  replacement; quieter-entry pin is real.
- **Seam 2 safety argument held under composition:** RampMemory is memory +
  seed publisher only; person-stop authority remains `apply_collision_brake`.
- **Dual rate-limiter seed is measured, not magical:** RampMemory is the single
  *source*; navigator slew + runtime S-curve are both consumers because
  shaper-only was measured as a near no-op when the navigator still ramps from
  zero. Documented with the recovery table in `_update_ramp_memory`.
- **Honest closed-loop claim:** wiring attributable via mission metadata;
  e2e still fails for destination-occupied / one-shot placement / short clear
  windows — not sold as green.

---

## Nits (not blocking)

- **OB-3 literal wording vs measured dual seed.** Arbitration said seed the
  shaper and drop/sim-gate navigator `seed_ramp`. Opus keeps both with a
  measured rationale. Acceptable under these review criteria (no safety
  bypass; single value source). Flag only if Fable wants a literal
  single-consumer re-cut.
- **Track-coincident LiDAR filter at placement** (`_blocked_points_without_tracks`,
  `match_m=0.9`) softens *approach free-space pruning* when tracks are active.
  Runtime collision / person-stop / reactive paths are unchanged. Prefer
  keeping this placement-only and not generalising it into the brake chain.
- **`top_k` / `max_age_s` unused at the call site.** Sol offered them for large
  candidate grids and stale CV tracks; defaults are fine for the sidewalk
  pin, but a later card should bound eval cost and staleness explicitly.
- **Watchdog freezes progress counting inside `person_stop_m`.** Correct for
  yield-advance; means contested scenes die on NavigateTo wall-clock rather
  than `navigation_no_progress` — already what the updated xfail reports.

---

## Explicit non-issues

- Not wiring `proxemic_approach.reject_cost` — required for empty-tracks
  identity; parked by arbitration.
- Pedestrian e2e still red — expected; flipping without a hard pass would be
  the defect.
- `grid_navigator` continuing to use numpy `dynamic_layer.tracks_from_payload`
  for planner costs — orthogonal to the approach ranking seam.

---

## Must-fix

None.
