# Day 24: IMU, Odometry, Drift, and Slip

## Mental model

Odometry answers “how did I move since the last tick?” by integrating proprioceptive motion — wheel/leg kinematics, IMU angular rate and acceleration, or a vendor body-state estimate. It is a **local, drifting frame**, not a surveyed map.

```text
integrate velocity / IMU  ->  odom pose grows
without absolute fixes    ->  error accumulates (drift)
slip / bias / latency     ->  odom ≠ ground truth
```

IMU alone cannot hold metric position: double-integrating acceleration amplifies bias into runaway position error. Gyro yaw bias integrates into heading drift; heading error then corrupts every LiDAR ray you paint into the grid.

## Software-engineering analogy

Odometry is an **append-only event log without snapshots or compaction**.

- Each tick appends a relative transform (good for short horizons).
- There is no checkpoint restore from GPS/landmarks on Parcel’s current city path.
- Slip is a **silent lost write**: the log advances while the durable store (the world) does not.
- Treating `NavObservation.position` as a globally consistent coordinate is like treating an unreplicated local sequence number as a cluster-wide transaction ID.

Short missions can live on odom. Long loops around a block cannot without localization or loop closure (Day 26).

## Light equations

Dead reckoning (planar, small steps):

```text
x ← x + v cos(θ) Δt
y ← y + v sin(θ) Δt
θ ← θ + ω Δt
```

IMU bias intuition:

```text
ω_meas = ω_true + b_gyro + noise
θ_error ≈ b_gyro · t          # grows ~linear in time if uncorrected
```

If heading is wrong by δθ, a ray at range r lands ~`r · δθ` metres off laterally — enough to smear a lamppost across multiple grid cells.

## ASCII diagram

```text
  truth path:     start ----------------> goal
  odom path:      start -----------/
                                 /  (drift + slip)
                                v
                           believed pose

  LiDAR hits are painted at believed pose → map warps with odom
```

## Map to Parcel / Go2

From `docs/NAVIGATION_CITY.md` and `edu/INTRO.md`:

- `grid_v1` plans in the pose carried by `NavObservation.position` / `heading_deg` — simulator state or Unitree `SportModeState`-class body feedback. Docs state explicitly: **no SLAM, relocalization, loop closure, or drift correction** on the current path.
- Rolling map recenters with the robot; old space falls out of the window. That bounds memory but does **not** cancel integrated odom error inside the window.
- Safe-valley experiments check `extras["odometry_fresh"]`, `odometry_timestamp_s` vs LiDAR stamps (`GridNavigator._sensor_frame_is_fresh`). Default `grid_v1` is less strict and can still map with older sync assumptions — know which profile you run.
- Follow/orbit controllers transform owner tracks into the robot odometry frame before control (`FollowConfig` comments in `follow.py`).

**Codebase anchors (odom / drift):**

- `navigation/base.py` → `NavObservation.position`, `heading_deg` — the pose bag planners trust.
- `navigation/grid_planner.py` → `Pose2D(x, y, heading_rad)`; `RollingGridPlanner.update(pose, scan)` paints rays at that pose.
- `navigation/grid_navigator.py` → builds `Pose2D` from observation each `act()`; optional freshness via `odometry_timestamp_s` / `lidar_timestamp_s`.
- `perception.PerceptionContract` — environment sensors are camera+LiDAR; body odometry is separate runtime state, not “maps enabled.”
- Honesty: `docs/NAVIGATION_CITY.md` sensor table row “Odometry / body state.”

## Tick-by-tick in Parcel

`NavObservation.position` / `heading_deg` are taken as the world frame for painting rays and measuring goal distance. There is no secondary absolute pose corrector on the `grid_v1` path. That is acceptable for short headless city tasks inside `HeadlessCityWorld`, where the kinematic base and oracle semantics keep missions short. It is not acceptable as an implicit claim of city-scale localization on a physical Go2. When you add hardware, budget a localization milestone before promising revisiting landmarks.

Practical SE habit: log commanded body velocity, measured velocity, and scan-to-map consistency residuals. Drift often appears first as “A* thrash” or “arrival never verifies,” not as an IMU fault code.

## Failure story

A long sidewalk traverse used perfect-looking occupancy while the dog’s feet slipped on wet leaves. Sport still reported smooth body velocity; odom crawled forward slower than commanded. The rolling grid kept clearing “free” cells ahead of the believed pose, A* looked healthy, and the mission timed out short of the lamppost with no hard fault — progress predicates compared goal distance in drifted coordinates. Fix direction: measure progress with multi-signal agreement (commanded vs measured velocity, scan consistency), bound mission length in odom-only mode, and never call odom “map.”

## Why slip fools “green” dashboards

Command success and Sport acceptance can stay green while feet skate. Odometry may still integrate a small motion; LiDAR may still look locally consistent inside a sliding window. The tell is cross-signal disagreement: commanded speed vs measured speed, expected free-space parallax vs scan, goal distance shrinking slower than integrated path length. Build alerts on disagreement, not on single-source health bits.

## Retrieval questions

1. Why does a constant gyro bias ruin a LiDAR occupancy map even if every range measurement is accurate?
2. What does Parcel’s city navigator use today instead of loop closure?
3. (From Day 18) How is integrating noisy velocity related to a feedback loop that never measures absolute position error?

## Optional 10-minute exercise

Open `docs/NAVIGATION_CITY.md` (odometry row) and `GridNavigator.act` where it constructs `Pose2D`. List three fields you would log to detect slip (`measured` speed vs command, scan inconsistency, mission timeout). Note whether default `grid_v1` or only safe-valley profiles enforce `odometry_fresh`.
