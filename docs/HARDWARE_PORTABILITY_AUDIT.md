# Hardware portability audit — how Go2-coupled is Parcel, and what custom hardware would cost

**Date:** 2026-08-05 · **Method:** 4-auditor workflow (`wf_8228bbfc-1d6`) over
control boundary, sensor assumptions, morphology/expression, and the claimed-
agnostic core, with file:line evidence. Prompted by the owner's question:
*"How hardware-agnostic is the software, and what would migrating to
self-built hardware cost?"*

## Headline numbers

`src/parcel_robot/`: **127 files, 42,229 LOC.**

| Category | Share | What |
|---|---|---|
| Zero hardware assumptions | ~46% of LOC | brain/ (PlanIR/executive/validator, 4,882), voice/duplex/providers/prosody/endpointing, attention/, instructnav/, core/ (SE2-twist-only), evals |
| Interface-mediated (hardware only through a typed contract) | ~52% | navigation, runtime, expression engine, sim backends, skills executor |
| Go2-specific **code** | **~800 LOC (≈2%)** | `control/unitree_sport.py` (389), `unitree_control.py` CLI (133), factory builder (~100), `rl/` 12-DOF/48-obs package (278, unused at runtime), `skills/api.py` obs stub |
| Go2-specific **data** | — | 26 pose/trajectory YAMLs (Go2 joint tables), `scenes/city_block.xml` go2.xml include, `robot.yaml` `unitree_sport:` block, `geometry.py` scale constants |

## The three contracts that make it portable (verified, not aspirational)

1. **`LocomotionController` / `RobotStateSource`** (`control/base.py`):
   leased SE(2) body-velocity setpoints + stop/E-stop lifecycle + sequenced
   base_link feedback. No mode enums, canned-move names, topics, or joint
   counts cross it. **Empirical proof:** `control/mock_vendor.py` — a
   164-line second vendor adapter runs the full 1,205-line `ControlManager`
   (watchdogs, TTL, feedback-confirmed stop, latched E-stop) with zero
   generic-layer edits.
2. **`RobotProfile`** (`robot_profile.py`): morphology (leg names, link
   lengths, stance, scan height) as a config-overridable dataclass, threaded
   through sim, gait, and expression IK.
3. **Backends telemetry schema** (`backends/base.py` SimObservation /
   `backends/mujoco.py` strict JSON validation): pose, planar scan, owner
   track, dynamic-agent tracks, semantic objects — vendor-neutral shapes.

## Honest leak list (what would actually bite)

- `gait.py:19,132` — FL/FR/RL/RR phase tables + `endswith("L")` sign
  convention behind the "generic" profile: a renamed-leg profile validates
  fine and then the scripted gait **silently animates zero legs**. Sim-only.
- `control/models.py:152` — raw Sport mode int in the "vendor-neutral"
  `RobotMotionState` (contained: only the Unitree adapter reads it).
- `perception.py:43` — sensor suite frozen to exactly `{camera, lidar}`;
  any other suite requires editing the file.
- `geometry.py:3` — `ROBOT_FOOTPRINT_RADIUS_M=0.32` /
  `ROBOT_OBSTACLE_HEIGHT_M=0.9` Go2-scale module constants imported directly.
- `navigation/pipeline.py:445` — relational-goal terminal approach keys on
  **MuJoCo geom names stamped onto lidar returns** (oracle leak that hits
  ANY real hardware, Go2 included).
- `rl/spaces.py` + `skills/api.py` — 12-DOF/48-obs layout hardcoded (no
  shipped policy depends on it).
- Expression clamps / `MAX_EXPRESSION_OFFSET_RAD` / `max_abs_joint_position`
  — morphology-sensitive scalars, should be profile-derived.

## Migration bill A — porting Parcel itself: **1–3 engineer-weeks**

1. New adapter pair (LocomotionController + StateSource, ~200–500 lines,
   `mock_vendor.py` is the template) + factory registration + a clone of the
   ~130-line commissioning CLI (there is deliberately no config-only way to
   arm hardware).
2. One `robot.profile` YAML block; fix the `gait.py` leg-name leak if naming
   differs.
3. Re-author the 26 skill clip YAMLs against the new joint table (executor/
   catalog are name-agnostic and fail loudly).
4. New named-actuator MJCF for sim (sim binds joints/actuators by
   introspection; nothing else changes).
5. Re-derive speed caps, settle thresholds, expression clamps, footprint
   constants (current values are sim-pace-derived, not Go2 measurements).
6. Rewrite `rl/` only if training policies.

**Custom hardware is strictly better for expression:** with joint-level
control, the already-built-and-tested additive joint overlay becomes the
real hardware path, replacing the unvalidated Go2 Sport-Euler workaround.
A neck is half-built (head yaw/pitch channels are produced, epoch-cancelled,
and currently unactuated — they need one `head_joint_offsets` mapping).
Tail/ears = a bounded rewrite of the frozen `ExpressiveOffsets` vocabulary
(weeks); the engine architecture survives.

## Migration bill B — what the platform must provide (the dominant cost)

What Go2's Sport firmware supplies for free, and self-built hardware must
recreate below the interface:

- A **self-balancing, gait-generating, velocity-tracking whole-body
  controller** accepting base_link (vx, vy, vyaw): state estimation, balance,
  gait generation or a trained RL policy, joint/motor control. The repo
  contains **no locomotion controller** — sim "walking" is kinematic base
  teleportation with scripted leg animation; `rl/` is a stub with no
  policy-to-actuator path. This is a from-scratch legged-controls project:
  **person-months to person-years**, i.e. recreating what the Go2 SKU buys.
- Sequenced proprioceptive feedback ≥10 Hz in base_link frame (stale
  feedback hard-refuses all motion by design).
- A stop that physically settles <0.08 m/s / 0.12 rad/s within ~1 s while
  continuing to balance standing, and a latching E-stop that keeps feedback
  alive.
- A battery state source (today a config stub).

## The cost that is identical either way

The real perception daemon — drift-bounded world localization at ~10 Hz
(nothing in the stack does SLAM), planar-scan production, owner ReID
tracking, multi-object tracks with velocity/class/TTC, semantic detection
with per-return instance IDs — is **sim-only today even for the Go2**.
Building it is the program's Phase 1–3 work regardless of vendor; it is not
a migration penalty. (The Habitat depth-row bridge in `evals/external/`
proves the planar-scan adapter is ~100 lines.)

## Verdict

The codebase is honestly **~95%+ portable**: ~2% Go2-specific code behind a
clean, empirically-proven seam, plus re-authorable data files. Migrating
Parcel to self-built hardware is **weeks**; building self-built hardware
that satisfies Parcel's boundary is **person-years**, dominated by the
whole-body locomotion controller the Go2 includes in its price. The
architecture keeps the buy-vs-build decision cheap to revisit: nothing above
the three contracts would change.
