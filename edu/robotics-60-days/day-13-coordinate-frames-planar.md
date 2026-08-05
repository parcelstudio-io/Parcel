# Day 13: Coordinate Frames and Planar Transforms

## Mental model

A number without a frame is a bug waiting for a PR review. Planar robotics lives in SE(2): position \((x, y)\) plus heading \(\theta\). A transform \(T_a^b\) says how to take a point expressed in frame \(b\) and express it in frame \(a\) (convention varies by library — pick one and stick to it; ROS-style `tf` thinks in “pose of child in parent”).

Parcel-relevant frames from `edu/INTRO.md`:

```text
base_link  — dog body (command frame for vx, vy, vyaw)
camera     — fixed offset from body (extrinsics)
lidar      — fixed offset from body
odom       — locally smooth motion frame (drifts long-term)
map        — shared world / prior map frame
owner      — dynamic frame on the tracked person
```

Composing transforms is matrix (or pose) multiplication. Inverting undoes a change of coordinates. Mixing `odom` and `map` without the bridge transform is how you “teleport” goals.

## Software-engineering analogy

Frames are schemas; transforms are migrations.

- `base_link` velocities are like a service’s internal DTO.
- `odom` is a monotonically updated local shard view — great for control, wrong for “meet at the cafe door” across a session.
- `map` is the globally consistent database.
- `owner` is a row whose primary key keeps moving; you subscribe to updates, you do not cache forever.
- Publishing a goal in the wrong frame is a type error that typecheckers miss unless you tag units *and* frames in the type.

`TimedVelocitySetpoint.frame` defaulting to `"base_link"` is intentional typing at the control boundary.

## Light equations

Planar pose of body in `odom`:

```text
T_odom_base = (x, y, θ)

point in base -> odom:
  x_o = x + cosθ · x_b - sinθ · y_b
  y_o = y + sinθ · x_b + cosθ · y_b
```

Body-frame velocity command (Parcel contract after commissioning):

```text
+vx forward,  +vy left,  +vyaw counter-clockwise
```

If Sport reports planar velocity in `odom` but you command in `base_link`, rotate before comparing — `state_velocity_frame` exists for this reason.

## ASCII diagram

```text
map ---- T_map_odom ----> odom ---- T_odom_base ----> base_link
                                                    /    |    \
                                            camera /  lidar    \ owner (dynamic)
                                                  /             \
                                           image rays        "1.5 m left of me"

command: VelocityCommand in base_link
feedback: may arrive as odom-frame twist -> rotate if configured
```

## Map to Parcel / Go2

**Codebase anchors (frames / SE(2)):**

- `VelocityCommand` in `src/parcel_robot/models.py` is the body twist DTO (`vx`, `vy`, `vyaw`).
- `TimedVelocitySetpoint.frame` is hard-required `"base_link"` in `src/parcel_robot/control/models.py`.
- `UnitreeSportStateSource` (`unitree_sport.py`): if `velocity_frame == "odom"`, rotates vendor `message.velocity` into body using yaw from `imu_state.rpy`; then applies `lateral_sign` / `yaw_sign`. Config key: `control.unitree_sport.state_velocity_frame`.
- `build_unitree_sport_control_manager` in `src/parcel_robot/control/factory.py` refuses build unless `axes_commissioned` and `state_frame_commissioned` are true.
- `docs/MOTION.md`: holonomic contract (+vx forward, +vy left, +vyaw CCW after commissioning); ordinary planners prefer turn-then-forward.
- Owner-orbit / “walk away from me” need owner pose in a frame connected to `base_link` with a usable stamp — geometry without freshness is still wrong (Day 11).

## Why builders care

Every navigation bug that “feels like control” should be asked: *wrong frame, wrong time, or wrong dynamics?* Frame mistakes are cheapest to prevent with types and commissioning flags, and most expensive when they ship — the dog moves confidently in the wrong direction. Prefer failing to build the physical manager over guessing `odom` vs `base_link`.


Composition discipline: when you need owner in `base_link`, explicitly chain `T_base_odom * T_odom_owner` (or the inverse chain your library uses)—never subtract raw XYZ from mixed frames. Stamp every pose; a correct transform on a 500 ms-old owner pose is still a wrong command (Day 11).

Logging checklist: every pose line should include frame id, stamp, and yaw convention. If a metric dashboard cannot answer “is this `odom` or `map`?”, it cannot debug motion.

## Failure story

During early Sport bring-up, velocity feedback was interpreted as `base_link` while firmware published an odom-aligned twist. A stop-settling check saw “still moving” sideways in the wrong basis and retried `StopMove` until timeout, even though the dog was standing. Separately, a nav bug added goal offsets in `map` meters to `odom` coordinates after a localization jump — the dog bolted toward a phantom point. Both were frame bugs, not “bad PID.” Fix: explicit `state_velocity_frame`, commissioning gates in `factory.py`, and frame tags on every pose in logs.

## Retrieval questions

1. What does SE(2) contain, and which Parcel command lives naturally in `base_link`?
2. Why can `odom` be right for short motion control and wrong for a long-lived semantic goal?
3. (From Day 11) If transform lookups are correct but the owner pose stamp is 400 ms old at a 10 Hz planner, what fails first — geometry or freshness?

## Optional 10-minute exercise

From `docs/MOTION.md`, list every place frame or axis commissioning is mentioned. Write the exact config flags that must be true before physical `Move`, and one sentence on what each prevents.
