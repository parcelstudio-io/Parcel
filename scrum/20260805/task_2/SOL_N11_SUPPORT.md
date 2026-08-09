# Sol N11 support — Opus wiring readiness (2026-08-06)

**Lane:** Sol (pure) supporting Opus wiring of N11 traffic-aware goal
placement + yield-advance pacing. **No pipeline / approach / runtime edits
in this drop.**

Prior pure status: [scrum/20260806/task_1/SOL_N11_STATUS.md](../../20260806/task_1/SOL_N11_STATUS.md).

## Verdict

Pure layer is **ready for Opus**. Both unit suites are green. One small
stdlib-pure helper was added so approach ranking can consume
`extras["dynamic_agents"]` without importing `dynamic_layer` / numpy.

## Verified green

```bash
.parcel/bin/python -m pytest tests/test_traffic_aware.py tests/test_proxemic_approach.py -q
# 53 passed (45 traffic_aware + 8 proxemic)
```

| Suite | Path | Result |
|---|---|---|
| traffic_aware | `tests/test_traffic_aware.py` | 45 passed |
| proxemic_approach | `tests/test_proxemic_approach.py` | 8 passed |

## Helper added this pass

| Artifact | Path |
|---|---|
| Pure payload → `TrackState` | `src/parcel_robot/navigation/traffic_aware.py` → `tracks_from_payload` |
| Cap constant | `DEFAULT_MAX_TRACKS = 16` (matches `dynamic_layer.MAX_TRACKS`) |
| Unit coverage | `tests/test_traffic_aware.py` (`test_tracks_from_payload_*`) |

### Why

Opus wiring at `_commit_semantic_candidate` / `safe_approach_pose` needs to
parse `observation.extras.get("dynamic_agents")`. The existing
`dynamic_layer.tracks_from_payload` returns numpy-backed `AgentTrack` and
pulls the planner cost stack. The new helper is the stdlib-pure sibling:
same field contract (`x`/`y`/`vx`/`vy` required, `radius_m` default 0.35),
loud reject on malformed content, `None`/empty → `()`, cap 16.

`coerce_tracks` still accepts `AgentTrack` duck-types if Opus prefers the
existing parser; either path feeds `rank_approach_candidates`.

### Suggested Opus call shape (not applied)

```python
from parcel_robot.navigation.traffic_aware import (
    RampMemory,
    rank_approach_candidates,
    tracks_from_payload,
)

try:
    tracks = tracks_from_payload(observation.extras.get("dynamic_agents"))
except (TypeError, ValueError):
    tracks = ()  # loud-then-degrade, same pattern as grid_navigator:477-483

ranked = rank_approach_candidates(
    points,
    tracks,
    static_cost_fn=distance_to_robot,
)
best = ranked[0]
```

## API surface Opus can import (unchanged + new)

From `parcel_robot.navigation.traffic_aware` (stdlib-only):

- `tracks_from_payload(payload, *, max_tracks=16) -> tuple[TrackState, ...]` **(new)**
- `TrackState`, `coerce_tracks`
- `traffic_occupancy_cost`, `rank_approach_candidates`, `RankedCandidate`
- `RampMemory` — `note_running` / `note_stopped` / `release` / `reset`

Complementary (numpy; optional veto later, not the N11 ranking seam):

- `parcel_robot.navigation.proxemic_approach.select_proxemic_approach`
  / `proxemic_costs` / `ProxemicApproachConfig`

Prefer `rank_approach_candidates` at the approach min-pick seam: empty
tracks keep static ordering byte-identical (ladder rule). Proxemic
`reject_cost` remains available as an *additional* fail-closed veto.

## Wiring seams (still Opus — cited only)

Unchanged from `SOL_N11_STATUS.md`:

1. **Placement:** `approach.py` `_safe_polygon_point` / `_safe_near_object_point`
   min-picks → `rank_approach_candidates`; thread tracks from
   `_commit_semantic_candidate`; record
   `approach_static_cost` / `approach_traffic_cost` in mission metadata.
2. **Pacing:** `NavPipeline` owns one `RampMemory`; hook after
   `apply_collision_brake`; seed via `GridNavigator.seed_ramp(vx)`.

## Explicit non-claims

- **Not wired** into pipeline / approach / grid_navigator / runtime.
- Pedestrian e2e xfail
  (`test_go_to_the_sidewalk_with_pedestrian_traffic`) **still xfail**
  until Opus lands both seams.
- No closed-loop evidence from this support pass.

## Paths + tests (return package)

```
src/parcel_robot/navigation/traffic_aware.py   # +tracks_from_payload
src/parcel_robot/navigation/proxemic_approach.py  # unchanged, still green
tests/test_traffic_aware.py                   # +payload adapter tests
tests/test_proxemic_approach.py               # unchanged, still green
scrum/20260805/task_2/SOL_N11_SUPPORT.md      # this note
scrum/20260806/task_1/SOL_N11_STATUS.md       # prior pure contract

pytest tests/test_traffic_aware.py tests/test_proxemic_approach.py -q
# → 53 passed
```
