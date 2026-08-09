# task_2 Status — Sol lane (proxemic approach + admission pin)

**Card:** task_2 · **Owner lane:** Sol (pure) · **Date:** 2026-08-06 ·
**Constraint:** no Nav2; do not edit `collision.py` / `reactive_safety` ·
fail-closed · **not wired** into the navigator

## Verdict

Pure proxemic approach-pose scorer landed for the pinned pedestrian e2e
xfail. Occupancy + TTC urgency prefer quieter poses inside a goal region.
**Opus wires** into `safe_approach_pose` / pipeline later.
`test_go_to_the_sidewalk_with_pedestrian_traffic` **remains xfail** until
that wiring (and any yield-advance pacing) lands.

## Deliverables

| Artifact | Path |
|---|---|
| Proxemic approach scorer | `src/parcel_robot/navigation/proxemic_approach.py` |
| Unit tests (proxemic) | `tests/test_proxemic_approach.py` |
| Admission contract pin (searchable ≠ visible) | `src/parcel_robot/brain/navigate_admission.py` |
| Pin tests | `tests/test_navigate_admission_pin.py` |
| Regression test uses shared pin | `tests/test_navigation_admission_regression.py` |

### Proxemic API (for Opus wiring)

- `ProxemicApproachConfig` — weights, CV rollout horizon, `reject_cost`
- `proxemic_costs(poses, tracks, *, robot_xy=None, config=None)` — per-pose
  cost = `occupancy_weight * agent_cost_at` + `ttc_weight * TTC urgency`
  (+ soft distance tie-break). TTC is for a **stationary** robot at the
  candidate pose.
- `select_proxemic_approach(...)` — argmin under `reject_cost`; returns
  `None` if empty or all poses fail-closed (does not hand back a stream
  landing).

Reuses `dynamic_costs.AgentTrack` / `agent_cost_at` / `time_to_collision_s`.
No pipeline / approach.py / safety edits.

### Admission pin

Documents the task_2 contract already enforced by `validator.py` and
`tests/test_navigation_admission_regression.py`: NavigateTo admission
requires `camera_fresh` / `lidar_fresh` / `base_available` and must **not**
require `target_grounded` (searchable ≠ visible). Explicit plan-declared
`target_grounded` remains enforceable elsewhere.

## Explicit non-claims

- **Not wired** into `approach.safe_approach_pose` or `DirectiveNavigator`.
- Pedestrian e2e **still xfail** — person-stop on a traffic-blind goal is
  correct until proxemic goal placement is composed in.
- No yield-advance pacing in this drop (same social card; Opus / follow-on).
- Does not touch reactive safety or collision brake.

## Open (Opus)

1. Score / re-rank polygon samples from `_safe_polygon_point` (and related
   approach samplers) with `select_proxemic_approach` when dynamic tracks
   are present.
2. Flip `test_go_to_the_sidewalk_with_pedestrian_traffic` from xfail to
   hard gate once composed behavior arrives within budget.
3. Optional: yield-advance pacing on the social card.

## Test command

```bash
pytest tests/test_proxemic_approach.py tests/test_navigate_admission_pin.py \
  tests/test_navigation_admission_regression.py -q
```
