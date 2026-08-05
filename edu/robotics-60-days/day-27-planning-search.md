# Day 27: Planning and Search

## Mental model

Planning turns a metric goal + occupancy belief into an ordered sequence of places to be. On a grid, **A*** is Dijkstra with a heuristic: expand the cell that minimizes `f = g + h`, where `g` is cost-so-far and `h` underestimates remaining cost (usually Euclidean distance in metres).

```text
start cell + goal cell + costs(free/unk/dynamic) -> waypoint polyline
```

Inflation expands occupied cells by the robot footprint so the path is for a **disk**, not a point. Clearance is a planning-time promise; the controller and reactive gates still enforce it at runtime.

## Software-engineering analogy

A* is a **priority-queue path search on a graph** — like routing packets on a weighted mesh, not like gradient descent on a neural net.

- Graph nodes = cells; edges = neighbor moves with travel + terrain costs.
- Heuristic admissibility ≈ “optimistic ETA that never overclaims.”
- Replanning ≈ invalidating a cached route when the dependency (scan / dynamic layer) changes.
- Footprint inflation ≈ compiling a process with a larger sandbox than the binary’s byte size.

## Light equations

```text
f(n) = g(n) + h(n)
h(n) = Euclidean(n, goal)     # admissible on uniform free space
```

Soft costs (unknown, dynamic Gaussians) add to `g` without necessarily marking lethal occupation. Lethal = hard inflated occupied (and policy-dependent unknown blocking — Parcel default allows unknown with penalty).

## ASCII diagram

```text
  S = start   G = goal   # = inflated occupied   . = free   ? = unknown

  ##########
  #..??....#
  #S..##..G#   A* prefers . over ? (unknown_cost)
  #........#   never steps through #
  ##########

  output: waypoints -> next_waypoint(lookahead)
```

## Map to Parcel / Go2

- `RollingGridPlanner.plan` → `_astar` → `RoutePlan.waypoints_world`; `next_waypoint` picks a body-frame pursuit target using `lookahead_m` (0.90 m in `grid.yaml`).
- Replan: every `replan_interval_steps` (5) for static maps; **every tick** when `dynamic_cost_active` so cached routes do not lag pedestrians.
- Unknown: `allow_unknown=True`, `unknown_cost=2.5`. Partial goals / frontiers are experimental (`reachable_frontier_fallback`, etc.) — default profile stays conservative.
- Semantic layer chooses the goal pose (`approach.safe_approach_pose`); A* does not parse language.
- `SearchOwnerController` reuses the same `RollingGridPlanner` when calibrated LiDAR exists.

**Codebase anchors (A* / planning):**

- `navigation/grid_planner.py` → `RollingGridPlanner.plan`, `_astar`, `next_waypoint`, `GridPlannerConfig.max_expansions`
- `navigation/grid_navigator.py` → replan interval vs dynamic rebuild; `RoutePlan` consumption
- `configs/navigation/models/grid.yaml` → `lookahead_m`, `replan_interval_steps`, `unknown_cost`, `dynamic_agents`
- `navigation/approach.py` → `safe_approach_pose` (terminal metric goal before A*)
- `docs/NAVIGATION_CITY.md` → geometric planner design table

## Tick-by-tick in Parcel

After a `GoalPose` exists, `RollingGridPlanner.plan` runs A* on the inflated grid. Costs include travel, unknown penalty, optional comfort costs, and soft dynamic lobes. The returned `RoutePlan` is not executed blindly: the navigator tracks with lookahead, validates observed-clear segments, and may enter scan-only recovery at unknown frontiers. Expansion limits (`max_expansions`) fail closed rather than burning the 100 ms budget. When dynamic agents are active, skipping replans is a logic bug — the cost field moved under your feet.

## Failure story

An engineer zeroed `unknown_cost` to “make the dog braver.” A* dashed through unobserved courtyard corners; the execute-clear segment logic kept stopping/scanning, producing hesitation that looked like a controller bug. The planner and controller disagreed about courage. Fix: keep unknown expensive, invest in better exploration frontiers explicitly, and do not silently equate unknown with free.

## Heuristics, footprints, and honesty

A* with Euclidean `h` is fine when costs are mostly metric distance. Soft dynamic costs and unknown penalties make the *executed* path quality a separate question from “A* returned a polyline.” Always judge planners with the controller attached (`GridNavigator`), not on path length alone. Footprint inflation is binary and conservative by default — narrow gates may become impassable in the grid even if a careful human could squeeze. That is a known tradeoff, not an accident.

## Partial goals and recovery

If the true goal cell is occupied or unreachable inside the window, planners may return partial routes or frontier escapes depending on profile flags. Default recovery leans scan-in-place rather than reverse (`recovery_reverse_steps: 0`) because of rear FOV limits on hardware-like scans. When reading experimental `grid_frontier_*` YAML, ask: did product scenarios improve, and did invariant tests pass? Presence beside `grid.yaml` is not promotion.

Clearance is compiled into the graph via inflation before search. If a corridor is narrower than footprint plus margin, A* correctly reports difficulty — widening the robot in software is safer than shrinking inflation for a demo GIF.

## Retrieval questions

1. What do `g` and `h` mean in A*, and what goes wrong if `h` overestimates?
2. Why does Parcel replan every tick when dynamic agent costs are active?
3. (From Day 23) If the scan is missing, does A* still run — and what note do you see instead?


Open `configs/navigation/models/grid.yaml` beside `_astar` while you read: every cost weight is a product decision, not a math constant.

## Optional 10-minute exercise

Open `RollingGridPlanner.plan` / `_astar` and `grid.yaml` keys `unknown_cost`, `lookahead_m`, `replan_interval_steps`. Predict one behavioral change if `replan_interval_steps` were 50 with pedestrians present.
