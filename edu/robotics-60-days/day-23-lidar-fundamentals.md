# Day 23: LiDAR Fundamentals

## Mental model

LiDAR measures **time of flight along rays**: emit light, time the return, convert to range. Each sample is approximately “along this bearing, something returned at range r — or nothing did.” It is geometric and metric. It is not semantic. A lamppost and a person can look identical as occupied cells until camera tracks label them.

```text
camera: "that blob looks like the owner"
LiDAR:  "occupied / free along ray θ at range r"
```

Planar 2-D LiDAR (Parcel’s current city mapping input) is one horizontal slice. It misses curb drop-offs, overhanging signs, glass quirks, and obstacles above/below the plane.

## Software-engineering analogy

A scan is a **fan-out of probes with timeouts**:

- A return is a successful probe with a latency→distance conversion.
- A no-return is a **timeout**: maybe free space, maybe specular miss, maybe max range, maybe absorption.
- Self-returns are **reading your own pod’s health check as customer traffic** — filter by range/angle mask.
- Motion distortion is **using a half-written buffer** while the process moved: early rays and late rays belong to different poses unless you deskew.

Treat malformed or missing calibration like a failed schema migration: loud degraded mode, not silent empty map.

## Light equations

Range from time of flight (two-way):

```text
r = (c · Δt) / 2
```

Ray endpoint in the sensor frame (planar):

```text
x = r cos θ
y = r sin θ
```

Then transform into `odom` / map-local frame using the robot pose at (ideally) each ray’s timestamp. If you use one pose for a spinning/scanning sweep while the dog walks, the cloud shears.

Occupancy update intuition (ties to Day 21): hit cells get `+hit_log_odds`; free cells along the ray before the hit get `−miss_log_odds`; clamp.

## ASCII diagram

```text
              max range
                 |
  robot ----θ----* hit at r     => occupied near *
           \                    => free along segment
            \  no return        => unknown / cautious free (policy)
             \

  Blind wedge / occlusion:
  person blocks rays => nothing seen behind them (not "free forever")
```

## Map to Parcel / Go2

From `docs/NAVIGATION_CITY.md` and `navigation/`:

- Simulator LiDAR: 360-ray MuJoCo `mj_multiRay`, reported max ~30 m, seeded hit noise (~0.008 m) and dropout (~0.2%). Navigator **subsamples stride 2** and **caps mapping at 12 m** (`lidar_range_cap_m`).
- `grid_v1` builds a rolling log-odds occupancy grid from calibrated planar scans + odometry. Footprint inflation (~0.32 m robot radius + ~0.10 m hard margin) turns point hits into traversable clearance.
- Missing or malformed calibrated scan: navigator falls back to deterministic point-goal control, emits `scan_missing_fallback`, and increments a counter — **loud degraded mode**, not equivalent mapped planning.
- Dynamic people may appear in the MuJoCo raycast **and** as separate track payloads. Soft dynamic costs (Day 29) do not replace hard occupancy from static geometry.
- Hardware honesty: a 270° eval/hardware FOV creates a rear blind wedge; recovery behaviors that reverse into unseen space are deliberately avoided in default design notes (`configs/navigation/models/grid.yaml`: `recovery_reverse_steps: 0`).

**Codebase anchors (LiDAR rays → map):**

- `navigation/grid_planner.py` → `LidarScan` / `LidarScan.from_extras`: `+inf` and max-range are no-returns (clear free space, no phantom ring); NaN / negative ignored.
- `navigation/grid_navigator.py` → `GridNavigator._scan_from_observation` builds `LidarScan` from `NavObservation.lidar` + extras (`lidar_angle_min_rad`, `lidar_angle_increment_rad`, `lidar_range_max_m`) with `lidar_stride`; on failure stamps `note="scan_missing_fallback"`.
- `RollingOccupancyGrid.update` / `RollingGridPlanner.update(pose, scan)` apply hit/miss log-odds inside `lidar_range_cap_m`.
- `perception.PerceptionContract.lidar_role` = range, free-space, collision perception — not semantics.
- Contract prose: `docs/NAVIGATION_CITY.md` “Sensor and map contract.”

LiDAR is the backbone of Parcel’s geometric planner. Camera semantics choose *what* to approach; LiDAR decides *whether space exists*.

## Tick-by-tick in Parcel

Each navigation tick (~10 Hz), `GridNavigator.act` rebuilds a `LidarScan` (stride-subsampled ranges + angular geometry from `extras`). `RollingGridPlanner.update` ray-marches hits/misses into log-odds, inflates by footprint, and optionally merges soft dynamic costs. A* may reuse a cached route for a few static ticks, but the map itself is continuously evidence-updated. If geometry keys are missing, mapping turns off loudly — operators should treat `scan_missing_fallback` like a red dashboard light, not a quiet alternate algorithm.

## Failure story

A mapping bug treated no-return rays as “definitely free to max range.” In a glass-heavy atrium, many rays dropped; the grid painted a highway through a planter the dog could not see in returns. A* threaded the ghost corridor; the reactive brake saved a collision at the last metre when a few grazing returns finally appeared. Fix: distinguish unknown from free; penalize unknown in planning; only execute observed-clear segments; never equate dropout with emptiness.

## Retrieval questions

1. Name three reasons a LiDAR ray might produce no return even though space is not safely traversable.
2. Why does Parcel cap mapping range below the sensor’s reported maximum?
3. (From Day 12) How does scan noise relate to why log-odds updates are preferred over toggling a Boolean occupied bit each tick?

## Optional 10-minute exercise

Open `src/parcel_robot/navigation/grid_navigator.py` around `GridNavigator.act` / `_scan_from_observation` and `LidarScan`’s docstring in `grid_planner.py`. Write the degraded-mode contract in two lines: what input fails, what controller runs (`StubNavigator` point-goal fallback), and what telemetry (`scan_missing_fallback`, `scan_fallback_count`) an operator must see.
