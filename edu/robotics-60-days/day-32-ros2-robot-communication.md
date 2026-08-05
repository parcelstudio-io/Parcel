# Day 32: ROS 2 and Robot Communication

## Mental model

ROS 2 is not “the robot.” It is a *middleware dialect* for composing processes that publish observations, offer services, run long actions, and share coordinate frames. The concepts matter even when Parcel does not run a full ROS graph today:

| Concept | Job |
| --- | --- |
| Node | Process/component with a lifecycle |
| Topic | Continuous stream (sensors, cmd_vel-like intents) |
| Service | Short request/response |
| Action | Long goal with feedback, preempt, cancel |
| `tf2` | Time-stamped transform tree |
| QoS | Reliability, history, deadline expectations |
| Lifecycle | Unconfigured → inactive → active → finalized |

Parcel’s honesty: the product brain speaks PlanIR and leased SE(2) velocity through Python contracts and a simulator Unix-socket protocol. ROS 2 / Unitree is a *future backend seam*, not a requirement that every lesson pretend DDS is already the runtime bus. Learn the ideas; do not cargo-cult a graph you have not commissioned.

## Software-engineering analogy

ROS topics are like Kafka/NATS subjects for telemetry; services are like unary RPCs; actions are like durable workflows with cancellation tokens; `tf2` is a distributed clocked cache of pose edges; QoS is like choosing at-most-once vs at-least-once plus backlog policy.

Nav2’s lesson for Parcel: navigation is a stack of planners, controllers, and behavior trees behind clear interfaces—not one node that “does autonomy.” Official ROS 2 docs separate topics/services/actions for a reason; Parcel separates PlanIR steps, arbiter leases, and ControlManager lifecycle for the same reason.

**Tradeoff:** full ROS 2 brings ecosystem (Nav2, bags, `tf`) and operational complexity (DDS discovery, Humble vs Python 3.14 packaging friction called out in D10). Parcel currently prefers a thin `SimulatorBackend` protocol and will adopt ROS where hardware integration demands it—not as ideology.

## Light equations (message usability)

A subscribed sample is usable only if:

```text
usable ⇔  (t_recv − t_header) < freshness
       ∧  QoS matched (no silent incompatible pairing)
       ∧  frame_id ∈ expected
       ∧  ¬cancelled(action_goal)
```

Stale odometry on a “reliable” topic is still stale. Reliability ≠ freshness.

## ASCII diagram

```text
  ROS-shaped mental model (concepts)     Parcel today (honest mapping)
  ---------------------------------     ------------------------------
  /scan, /camera  (topics)       ~      SimObservation / LiDAR contract
  /tf, /tf_static                ~      named frames in planning (map/odom/base)
  NavigateToPose (action)        ~      executive step + success predicate
  cancel goal                    ~      preempt / stop / E-stop latch
  cmd_vel (twists)               ~      VelocityCommand → ControlManager
  lifecycle_manager              ~      ControlLifecycle + backend start/close
  rosbag replay                  ~      headless scenarios + eval corpora
```

## Map to Parcel / Go2

From `INTRO.md` (backend seam), `DESIGN_DECISIONS.md` D2/D5/D9/D10, and runtime code:

- The intended production split is Python brain → typed intent (sequence, timestamp, TTL, frame, bounds) → control/safety process → Unitree Sport. That *is* a ROS-like layering without requiring every message to be an IDL type yet.
- `SimulatorBackend` is the replaceable seam for MuJoCo now and ROS 2 / richer sims later (D9). Do not import Isaac/Habitat into the app process.
- Camera/LiDAR are perception authority (D5); no privileged sim geometry in planners—same discipline as refusing `/ground_truth` topics in onboard code.
- Cancellation must be first-class: voice barge-in, explicit stop, and E-stop are different severities. ROS actions teach preempt; Parcel’s executive and arbiter encode related policies.
- QoS analogue: arbiter TTLs and `ControlTiming` timeouts are Parcel’s deadline/liveliness policy. A forever-open socket without TTL is QoS “unspecified”—dangerous.

**Design choice:** delay full ROS until hardware bring-up needs vendor bridges, bags, and fleet tooling. Cost: less out-of-box interoperability. Benefit: one authority diagram students can actually run on desktop.

**Codebase anchors (comms concepts ↔ Parcel today):**

- `backends/base.py` → `SimulatorBackend` / `SimObservation` — today’s “topic-like” observation + `move` command seam (`backends/mujoco.py` → `MujocoSocketBackend`).
- `core/arbiter.py` → `CommandArbiter.submit` / `cancel` / `engage_emergency_stop` — exclusive writer + cancel semantics (action preempt analogue).
- `core/commands.py` → `MotionIntent.ttl` / `expired()` — liveliness/deadline stand-in for QoS freshness.
- `brain/executive.py` → `TaskExecutive` + `DispatchRequest` — long-running goal with report/preempt (action analogue); not a ROS action server yet.
- `control/manager.py` → `ControlLifecycle` arming/active/stopping — lifecycle-node analogue for locomotion authority.
- Honesty: no `rclpy` graph in-tree; ROS 2 is the intended hardware/backend dialect, not the current desktop bus (`DESIGN_DECISIONS.md` D9/D10).

## Failure story

A team “ROS-ified” the dog by publishing `cmd_vel` from three nodes (follow, teleop, Nav2) with default QoS and no exclusive controller. Intermittent Wi-Fi reordered messages; the dog stuttered between intents. On the desktop sim it looked like “DDS being flaky.” Root cause: multiple writers without arbitration—the same bug Parcel forbids with a single `ControlManager` writer and priority arbiter. Migrating to ROS without preserving *single locomotion writer + lease + E-stop* merely relocates the race into DDS.

## Retrieval questions

1. When is an action a better fit than a topic for “circle the owner once then sit”?
2. What does Parcel currently use instead of a full ROS graph, and what must stay true when a ROS backend arrives?
3. (Week-back) Why must `/tf` (or Parcel’s frame chain) carry time and frame ids, given Day 13’s SE(2) composition lessons?

## Optional 10-minute exercise

Sketch a minimal ROS 2 graph for Parcel hardware: nodes, topics, one Navigate-style action, and where `ControlManager`/E-stop live. Mark which edges are *product authority* vs *debug*. Compare to `DEVELOPMENT_STACK.md`’s architecture diagram and list three mismatches you must resolve before commissioning.
