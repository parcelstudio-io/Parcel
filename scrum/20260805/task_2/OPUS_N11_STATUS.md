# task_2 · Opus N11 wiring status (2026-08-06)

## Lane
Wire Sol's pure N11 layer (`traffic_aware.py`) into existing approach /
pipeline / grid navigator seams. Do **not** rewrite the pure module.

## Wired paths

| Seam | Where | Behavior |
| --- | --- | --- |
| 1 — traffic-aware goal placement | `approach.safe_approach_pose` ← `rank_approach_candidates`; tracks from `_commit_semantic_candidate` via `traffic_aware.tracks_from_payload(observation.extras["dynamic_agents"])` | Empty tracks ⇒ static nearest order (ladder). Active tracks ⇒ traffic cost + default `traffic_weight=2.0` at the call site; LiDAR hits coinciding with tracks are filtered so ranking sees the full free set. Cost breakdown recorded as `approach_static_cost` / `approach_traffic_cost` / `approach_total_cost` in mission metadata. |
| 2 — yield-advance pacing | `DirectiveNavigator` owns `RampMemory`; `person_stop` → `note_stopped`; release → `GridNavigator.seed_ramp` + `pending_ramp_seed_mps` for the runtime S-curve + same-tick post-brake lift when `cnote=="clear"` | Never a gate. Align/zero ticks do not wipe held velocity (`RAMP_RUNNING_FLOOR_MPS`). Progress watchdog does not count person-stop ticks as stalls. |
| Soft import | `RampMemory` import is soft for historical BARN bundles | Degrades to no ramp memory. |

`proxemic_approach.reject_cost` was **not** wired — it fail-closes to `None` and would break empty-tracks identity; Sol's ranking seam is the N11 card.

## Verification

```text
.parcel/bin/pytest tests/test_traffic_aware.py tests/test_approach_traffic_wiring.py tests/test_navigation.py -q
→ 98 passed (incl. empty-tracks identity + quieter-entry + seed_ramp pins)

.parcel/bin/pytest -m slow tests/test_voice_nav_e2e.py -v --runxfail
→ test_go_to_the_sidewalk_grounds_plans_and_arrives PASSED
→ test_walk_towards_the_lamppost_grounds_plans_and_arrives PASSED
→ test_go_to_the_sidewalk_with_pedestrian_traffic FAILED (states=['failed'], last_detail=step_timeout)
```

## Xfail: **not flipped**

`test_go_to_the_sidewalk_with_pedestrian_traffic` stays `@pytest.mark.xfail`.

### Why (honest remaining gap)

Wiring is live and attributable (mission metadata shows non-zero
`approach_traffic_cost` and quieter commits than the static nearest point).
Closed-loop still dies at the sidewalk edge:

1. **Destination is occupied.** Scripted pedestrians walk *on* the sidewalk
   strip (y≈2.85–3.55). Constant-velocity ranking at commit picks a
   lower-exposure south-edge pose (~y=2.64), but person-stop correctly
   refuses the final ~0.3 m when agents sweep that edge. End pose in the
   failing runs sits around y≈2.07 — short of both the polygon (y≥2.2) and
   the K0 eval region (y≥2.4).
2. **One-shot placement.** Approach pose is committed once; tracks change
   over the ~240 s NavigateTo window. No mid-mission re-rank when the
   committed point becomes a person-stop corridor.
3. **Yield-advance is necessary but not sufficient here.** Ramp seeding +
   clear-window boost + watchdog freeze-during-yield are in place; clear
   windows are still too short / too contested to accumulate the final
   metre before `step_timeout`.

Safety gates (person-stop, collision brake, reactive/TTC, all-ray shield)
were not weakened.

### Follow-ons (not this card)

- Re-rank / re-commit approach pose when dwelling in `person_stop` near the
  goal with fresh tracks.
- Or a dwell-based `inside` arrival trigger that uses
  `point_in_polygon_with_clearance` (not raw edge hit) once the robot has
  entered the committed region — today `_inside_arrival_goal_region`
  intentionally returns False for `inside`.
- Optional later: `proxemic_approach.reject_cost` as an *additional* veto on
  top of `rank_approach_candidates`, only after empty-tracks identity is
  preserved by keeping the veto inactive when tracks are empty.

## Files touched

- `src/parcel_robot/navigation/approach.py` — traffic ranking + track-LiDAR filter
- `src/parcel_robot/navigation/pipeline.py` — tracks thread, RampMemory, watchdog yield freeze
- `src/parcel_robot/navigation/grid_navigator.py` — `seed_ramp`
- `tests/test_approach_traffic_wiring.py` — wiring pins
- `scrum/20260805/task_2/OPUS_N11_STATUS.md` — this note
- `scrum/20260805/task_2/PROGRAM_STATUS.md` — open-row update
