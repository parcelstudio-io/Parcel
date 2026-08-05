# Day 26: Mapping and SLAM

## Mental model

A map is a persistent belief about space. Parcel’s production city navigator builds a **rolling occupancy grid** in the odometry frame: free, occupied, or unknown cells with log-odds evidence. That is mapping. **SLAM** (simultaneous localization and mapping) additionally corrects the robot’s pose using the map — loop closure, scan matching, landmark fixes — so odom drift does not permanently warp the world.

```text
mapping only:  pose assumed true -> paint scans into grid
SLAM:          pose uncertain   -> jointly fix pose + map
```

`docs/NAVIGATION_CITY.md` is explicit: Parcel’s current path does **mapping without SLAM**. Know the difference before you promise city-scale memory.

## Software-engineering analogy

- Rolling log-odds grid ≈ **LRU cache of spatial evidence** with Bayesian upserts.
- Unknown cells ≈ cache miss (not “null means free”).
- Full SLAM ≈ distributed consensus that rewrites history when a loop closes.
- Calling the rolling window a “global map” is like calling a single Redis shard the system of record.

## Light equations

Occupancy log-odds (Day 21 reprise):

```text
L <- clip(L ± update, L_min, L_max)
occupied <=> L >= L_occ  (and observed)
```

Loop-closure intuition (not implemented on Parcel city path):

```text
detect revisit -> estimate pose error -> correct pose graph -> remap
```

Without that correction, long trajectories accumulate inconsistency between early and late paints of the same lamppost.

## ASCII diagram

```text
  Parcel today (rolling map in odom)
  ---------------------------------
  [ window ~16.1 m ]  robot near center
   free / occ / unk from LiDAR
   old cells fall off the back

  Classical SLAM (not current product path)
  ----------------------------------------
  pose graph: x0 -- x1 -- ... -- xn
                 ^______________/  loop closure
```

## Map to Parcel / Go2

- Default navigator `grid_v1`: `RollingGridPlanner` over `RollingOccupancyGrid`, 0.10 m cells, 161 cells/side (~16.1 m window), `lidar_range_cap_m=12`, footprint inflation via robot radius + `map_safety_margin_m`.
- `CellState`: UNKNOWN / FREE / OCCUPIED / OUT_OF_BOUNDS before inflation; inflation produces the hard mask A* sees.
- Unknown is traversable but costly (`unknown_cost=2.5`); controller still prefers observed-clear execution.
- Static POIs (`configs/navigation/cities/demo_pois.yaml`) are demo coordinates, not a localized map frame.
- `perception.NullMapProvider` — Google Maps placeholder cannot be enabled.
- `instructnav.memory.SemanticMemory` can remember entities with confidence decay — semantic memory, not metric SLAM.

**Codebase anchors (mapping vs SLAM):**

- `navigation/grid_planner.py` → `RollingOccupancyGrid`, `RollingGridPlanner`, `CellState`, `MappingUpdate`, `RoutePlan`
- `configs/navigation/models/grid.yaml` → resolution, size, margins, unknown cost
- `docs/NAVIGATION_CITY.md` → “no SLAM, relocalization, loop closure”
- `perception.NullMapProvider` / `PerceptionContract.snapshot`
- Eval geometry: `headless_city.HeadlessCityWorld` scores tasks; navigator API must not require simulator collision oracles

## Tick-by-tick in Parcel

`RollingOccupancyGrid` recenters as the dog moves so CPU/memory stay bounded. Overlapping evidence is retained when the window slides — that is incremental mapping quality, still not loop closure. `CellState.UNKNOWN` remains the honest default outside rays. Experimental frontier modes (`reachable_frontier_fallback`, `frontier_search_mode`) explore how to leave local minima; they are not enabled in default `grid.yaml` and must not be described as production SLAM features.

SemanticMemory in `instructnav` can recall that a lamppost was seen earlier with decayed confidence. That helps grounding; it does not correct x/y drift in the occupancy window.

## Failure story

A pitch claimed “Parcel SLAM holds a city block.” The demo succeeded because the rolling window and short scripted path never revisited a drifted corner. On a longer loop, the same lamppost painted twice in inconsistent odom places; A* threaded a ghost gap. Fix: rename the capability honestly (local rolling occupancy), bound mission length, and treat loop closure as a future localization milestone — not a checkbox on `grid_v1`.

## What “good enough” mapping means here

For companion sidewalk tasks of a few metres, a fresh rolling occupancy grid plus reactive safety is a coherent product bet. For multi-block autonomy, you need localization against a durable map or robust loop closure — a different milestone with its own evals. Keep research YAML profiles (`grid_frontier_*`, larger windows) behind explicit promotion criteria in `docs/NAVIGATION_CITY.md`. A larger window without pose correction only delays the day the map disagrees with itself.

## Frames: map vs odom (Parcel today)

Textbooks draw `map -> odom -> base_link`. Parcel’s city navigator effectively plans in a sliding odom-local window. Demo POIs in YAML assume a prior coordinate bargain with the simulator. On hardware, enabling a real `map` frame means localization publishing `map→odom`, not renaming the rolling grid. Until that exists, keep goals short-horizon and relative (owner, visible lamppost) rather than “absolute city pin.”

## Retrieval questions

1. What does Parcel’s rolling grid guarantee, and what does it refuse to claim?
2. How does unknown space differ from free space in `CellState` / A* cost?
3. (From Day 24) Why is mapping-without-SLAM especially fragile when feet slip?

## Optional 10-minute exercise

Open `RollingOccupancyGrid.update` and `cell_state` in `grid_planner.py`, plus the geometric planner table in `docs/NAVIGATION_CITY.md`. Write one sentence: what falls out of the window, and why that is not loop closure.
