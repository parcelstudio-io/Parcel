# Day 14: Three-Dimensional Rotations

## Mental model

Planar heading was one angle. In 3D, orientation is a member of SO(3): the set of valid rotations. There are many *coordinates* for the same rotation — matrices, Euler angles, axis-angle, quaternions — and they are not interchangeable without discipline.

- **Rotation matrix** \(R\): 3×3 orthogonal matrix with \(\det R = 1\). Compose by multiply; rotate a body vector by \(v_w = R v_b\). Numerically drifts off SO(3) if you integrate carelessly — re-orthonormalize or avoid integrating matrices.
- **Euler / Tait–Bryan (roll, pitch, yaw)**: human-readable, horrible near singularities (gimbal lock) when two axes align and you lose a degree of freedom in the parameterization — not in the physics.
- **Axis-angle**: rotate by \(\phi\) about unit axis \(u\). Intuitive for “small tilt.”
- **Quaternion**: 4 numbers on a sphere; compose smoothly; remember \(q\) and \(-q\) are the same rotation (double cover). Prefer for filtering and interpolation (`slerp`).

For a quadruped, roll/pitch are balance-critical; yaw is heading. Parcel’s supervisory tilt limit (`max_tilt_rad`) is a coarse SO(3) safety check on reported attitude, not a full attitude controller.

## Software-engineering analogy

Rotations are like non-commutative API composition.

- Matrix multiply order is function composition: \(R_2 R_1\) means “apply \(R_1\) then \(R_2\)” (for column vectors). Swap the order and you shipped the wrong transform — silent, geometric, catastrophic.
- Euler angles are like overloaded constructor args `(x,y,z)` without labeled fields: everyone argues about XYZ vs ZYX.
- Quaternions are a compact binary format with a weird equality (`q ≡ -q`); compare with a dot-product threshold, not string equality.
- Gimbal lock is a serializer that cannot represent a state you can still physically be in — fix the representation, not the robot.

## Light equations

Small-angle intuition (radians):

```text
roll  φ ≈ rotation about body x (forward)
pitch θ ≈ rotation about body y (left)
yaw   ψ ≈ rotation about body z (up)

For tiny angles, R ≈ I + [ω]_×  (skew-symmetric)
```

Compose yaw-then-pitch-then-roll carefully; document the convention next to every log line that prints rpy.

Quaternion unit constraint:

```text
|q| = 1
normalize after noisy updates; never PID each component independently as if Euclidean
```

## ASCII diagram

```text
same physical tilt, four spellings:

  R_3x3        rpy (φ,θ,ψ)        axis-angle (u, ϕ)        q (w,x,y,z)
     \              |                    |                     /
      \             |   gimbal lock      |                    /
       \            v   near pitch±90    v                   /
        +--------------> pick ONE for storage/filtering <---+
                              |
                              v
                     convert at boundaries
                     (logs may show rpy; estimators use q)
```

## Map to Parcel / Go2

**Codebase anchors (attitude / SO(3) safety):**

- `UnitreeSportStateSource._on_message` copies `imu_state.rpy` into `RobotMotionState.roll/pitch/yaw` (`src/parcel_robot/control/unitree_sport.py`).
- `ControlLimits.max_tilt_rad` (default 0.75) in `control/models.py`; `ControlManager` faults with `"robot_tilt_limit"` when `abs(roll)` or `abs(pitch)` exceeds it (`manager.py`) — last-line supervision, not the balancer.
- Physical poses/trajectories: `RobotRuntime._run_pose` / `_run_trajectory` stop locomotion and, when not on the sync sim path, raise that physical poses/trajectories must be controller-owned (`runtime.py`) — see also `docs/MOTION.md`.
- Camera/LiDAR extrinsics are 3D `base_link`←sensor transforms; wrong pitch tilts obstacles into floor/sky. Owner rays need extrinsics + attitude, not yaw-only planar hacks on ramps.
- Commission attitude sense against right-hand `base_link` before trusting tilt stops.


## Why builders care

Attitude bugs show up as “navigation spun for no reason” or “tilt fault on flat ground.” Before retuning planners, verify rpy convention, quaternion sign, and that `RobotMotionState` roll/pitch match the physical lean you see. Extrinsic pitch errors look like perception failures. Keep one storage representation (prefer quaternion/matrix in estimators) and treat Euler angles as a logging view with an explicit convention string.

Small-angle practice: for |roll|,|pitch| under about 0.2 rad, linear approximations help intuition, but commissioning and fault thresholds must still use the real reported rpy from `RobotMotionState`.

## Failure story

A perception hotfix converted Sport quaternion feedback to yaw with `atan2` after an undocumented roll-pitch-yaw order. On a gentle slope the reconstructed yaw jumped 15°, navigation commanded a “corrective” spin, and the dog corkscrew-walked while Sport happily tracked the spinning velocity command. The quaternion was fine; the Euler extraction convention was not. Fix: standardize on quaternion (or matrix) through the stack; emit rpy only in logging with an explicit convention string; add a unit test that a 90° pitch fixture does not NaN or flip yaw.

## Retrieval questions

1. What is gimbal lock — a physical inability to rotate, or a coordinate singularity? Why does that matter for choosing a state representation?
2. Why is comparing quaternions with component-wise `==` a bug?
3. (From Day 04) How does tip-over risk relate to center of mass and support, and which Parcel limit watches attitude as a coarse proxy?

## Optional 10-minute exercise

Find where `max_tilt_rad` is defined and enforced under `src/parcel_robot/control/`. Note whether it uses roll/pitch thresholds and what lifecycle state a breach should produce. Write one sentence on why this check cannot replace onboard balance.
