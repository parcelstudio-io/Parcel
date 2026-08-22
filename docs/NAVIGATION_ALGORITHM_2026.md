# Navigation algorithm for a city companion dog

**Decision and implementation plan — 2026-08-09.** This document is a target
design grounded in the current Parcel code. It is not a claim that Nav2, a
learned visual navigator, real-camera perception, or physical Go2 navigation is
already operational. Current capabilities remain described in
[engineering handbook](CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md).

## Outcome

Parcel should keep the architecture selected in the 2026 team review: a
deterministic, closed-loop real-time spine with asynchronous learned proposal
sources. The next production navigation baseline should be:

1. typed instruction and task-revision handling;
2. camera/LiDAR semantic grounding into an **acceptable goal region**, not a
   landmark center;
3. a city route graph for long trips and a rolling metric map for local motion;
4. a cost-aware 2-D global planner first, with a Go2 state-lattice challenger
   only if measured yaw/path executability warrants its extra complexity;
5. a regulated-pure-pursuit-style path tracker as the deterministic default;
6. a closed-loop omni MPPI controller evaluated in shadow mode for crowds and
   tight maneuvers;
7. predicted pedestrian occupancy and social costs, followed by a separate
   camera/LiDAR collision monitor that has the final exact-zero veto; and
8. Unitree Sport as the sole physical gait/balance controller behind Parcel's
   existing one-writer `ControlManager`.

This is deliberately not one vision-language model emitting motor commands.
Models may propose a task, referent, semantic goal, search frontier, waypoint,
or already-bounded trajectory candidate. They cannot choose safety priority,
declare arrival, write `vx/vy/vyaw`, or invoke Unitree directly.

## Why the current navigator needs a deeper change

The current `grid_v1` path is a sound safety-oriented prototype: it builds a
rolling LiDAR grid, inflates the footprint, adds constant-velocity agent costs,
runs A*, aligns the body, tracks a waypoint, and passes the command through
independent proximity/TTC gates. It also preserves `vy` in the robot command
contract while emitting `vy = 0` in ordinary route following.

The 2026-08-09 audit nevertheless found system-level problems that isolated
gain tuning could not solve. Its first item has since landed; the remaining
items continue to motivate the target design:

- **closed since that audit:** a typed post-shaper finalizer now makes hard
  stops exact zero and proximity stops exact-zero translation before dispatch;
- missing, stale, or unsynchronized required LiDAR can enter the point-goal
  fallback and translate instead of producing `HOLD`;
- there is no production localizer or commissioned `map -> odom` evidence join;
- semantic search can rotate through a complete scan without committing an
  object that should become visible;
- a fixed opening scan and wide rotate-first band spend a large fraction of
  task time stationary and turning;
- planner inflation and the later reactive stop envelope disagree, so the
  planner can repeatedly choose a corridor that the safety layer refuses;
- point goals and terminal heading can consume the budget even when the task's
  semantic vicinity predicate is already satisfied;
- constant-velocity crowd costs have neither identity-aware interaction nor
  uncertainty growth, and the current normalization can make an existing risk
  cheaper when another track is added; and
- the controller has no time-parameterized local trajectory optimizer and no
  measured physical command/odometry model.

The remedy is to make every layer agree on typed evidence, goal regions,
footprint and safety envelopes, while improving the controller without moving
authority into a learned model.

## Binding constraints

- The dog perceives the external environment through camera and LiDAR. Onboard
  odometry, joint/contact state, and Sport state are robot-state feedback, not
  extra environment sensors. Google Maps remains a disabled route-prior
  placeholder.
- Unitree Sport owns high-rate balance, gait, foot placement, and motor loops.
  Parcel sends only leased body velocity through one authority bridge.
- Normal goal-directed motion is forward-preferred. Lateral velocity remains
  legal for manual control, constrained avoidance, docking, and recovery, but
  carries a cost. It is not hard-coded to zero in the platform contract.
- A task succeeds only when an independent, fresh terminal witness proves the
  requested relation and the body is settled.
- Missing, stale, ambiguous, or frame-invalid evidence produces `HOLD`, search,
  clarification, or a stop—never optimistic motion.
- The post-shaper collision monitor may only preserve or reduce a command. A
  planner, smoother, model, or recovery cannot release its stop.

## Proposed stack

```text
final transcript / UI instruction
        |
        v
TaskRequestV1 + authorization + monotonically increasing revision
        |
        v
semantic grounding and goal-region candidates <--- camera detections/tracks
        |                                           LiDAR surfaces/free space
        v
city route graph ----> local rolling semantic-cost map <--- state estimate
        |                         |
        v                         v
state lattice / 2-D A*      predicted people occupancy
        |                         |
        +------------ path ------+
                         |
        deterministic RPP-style tracker (default)
        MPPI-omni candidate generator (shadow, then gated challenger)
                         |
        kinematic admission + acceleration/jerk shaping
                         |
        independent camera/LiDAR footprint + TTC monitor
                         |
        authority lease and stale-command watchdog
                         |
        Unitree Sport Move(vx, vy, vyaw)
                         |
        pose/Sport feedback closes progress and stop witnesses
```

Conversation, semantic planning, mapping, global planning, and local control
run at different timescales. A late semantic result never stalls or rewrites a
valid control tick: it is accepted only if task revision, evidence IDs,
authorization, deadline, and executive state still match.

## 1. Instruction and task transaction

Common commands should remain on the deterministic low-latency route. The
reasoning model is used for long-tail paraphrases, referent ambiguity, compound
tasks, explanations, and social context. Both paths compile into the same
bounded request:

```python
TaskRequestV1(
    task_id: UUID,
    revision: int,
    intent: NavigateTo | FollowFormation | OrbitOwner | Search | Gesture | ...,
    referent_query: SemanticQuery | None,
    relation: inside | near | next_to | behind | around | None,
    quantity: TypedQuantity | None,
    constraints: tuple[ConstraintV1, ...],
    source: voice | ui | autonomy,
    authorization: AuthorizationV1,
    deadline_ns: int,
)
```

Corrections create a new revision; they do not mutate an executing plan in
place. Every asynchronous proposal carries the revision it observed. Stale
results are discarded rather than reconciled by the motor loop. A plan is a
sequence of semantic skills with preconditions, postconditions, resources,
retry policy, and checkpoints—not a list of velocities.

## 2. State and world-model contract

The navigation snapshot must be immutable, timestamped, and frame-explicit:

```python
NavigationSnapshotV1(
    observed_at_ns: int,
    odom_T_base: Pose2DWithCovariance,
    body_twist: Twist2DWithCovariance,
    lidar_scan: CalibratedScanV1,
    semantic_tracks: tuple[SemanticTrackV1, ...],
    owner_track: OwnerTrackV1 | None,
    dynamic_tracks: tuple[DynamicTrackV1, ...],
    map_revision: int,
    transform_revision: int,
    freshness: EvidenceFreshnessV1,
)
```

Camera detections supply semantic identity, bearings, masks, and optional depth.
LiDAR supplies metric free/occupied geometry. Fusion must retain source IDs and
uncertainty rather than turning a label into certain occupancy. A semantic
track is not drivable proof; a LiDAR gap is not an object identity.

For first hardware deployment, use commissioned Sport/odometry feedback with a
LiDAR odometry or graph-SLAM sidecar. KISS-ICP is a small LiDAR-odometry
baseline; RTAB-Map is the stronger loop-closure/map option when calibrated
camera/depth is available. Neither may be presented as operational until frame,
timestamp, covariance, relocalization, and slip behavior are measured on Go2.

## 3. Semantic grounding and common-sense goal regions

“Go to the lamppost” is not a point at the lamppost center. “Get off the road”
is not a fixed coordinate. The grounder generates feasible pose regions and
scores candidates using current evidence:

\[
S(g)=w_s\log p_{semantic}(g)-w_p C_{path}(g)
    +w_c C_{clearance}(g)+w_v C_{visibility}(g)
    -w_u\operatorname{tr}(\Sigma_g)-w_r C_{road}(g)
    -w_h C_{human}(g).
\]

Hard filters run before ranking:

- the candidate class must match the admitted query/alias class;
- `inside(sidewalk)` must lie inside a sufficiently eroded sidewalk polygon;
- `near(lamppost)` must lie in a collision-free annulus around its observed
  surface, not inside the object;
- `next_to` must preserve object clearance and the requested reference side;
- road avoidance is a hard constraint unless an authenticated crossing task
  and crossing state are active; and
- the entire robot footprint, arrival tolerance, and stop uncertainty must fit
  the acceptable region.

Arrival is a set-membership predicate with hysteresis. Let `G_enter` be the
valid terminal region and `G_exit` a slightly larger region. Entering
`G_enter`, stopping, and re-observing the relation declares success; transient
localization motion inside `G_exit` does not immediately revoke it. Heading is
required only when the task semantics require orientation or visibility.

## 4. Global planning: route graph plus local lattice

For city-scale goals, a single rolling A* map is insufficient. Use two levels:

- a sparse route graph stores sidewalks, indoor corridors, doors, crossings,
  elevators, speed policies, and temporary closures; and
- a local metric planner connects the robot to the next route segment and the
  segment to the acceptable goal region.

Nav2's Route Server is a useful reference because edges can carry semantic
operations and be closed dynamically. It should remain a route prior, not a
source of obstacle truth.

The first local global planner should retain Parcel's current cost-aware 2-D A*
or use Smac 2-D. A Smac-style state lattice over `(x, y, yaw)` is a later
challenger, promoted only if the 2-D planner plus smooth local controller still
shows measurable yaw/path-executability failures. Its Go2-specific primitive
library would contain:

- forward straight segments and gentle arcs: normal, lowest cost;
- in-place rotations: legal, with switching and accumulated-turn penalties;
- short lateral translations: legal when clearance or task geometry warrants;
- short reverse segments: recovery or an explicitly owner-relative request;
- no primitive whose swept footprint violates hard occupancy.

One useful edge objective is:

\[
J_e=d_e+\lambda_m C_{map}+\lambda_h C_{human}
   +\lambda_{lat}\int v_y^2dt
   +\lambda_{rev}\int\max(0,-v_x)^2dt
   +\lambda_{turn}|\Delta\psi|
   +\lambda_{switch}N_{mode\ switch}.
\]

This encodes “lateral is allowed but not preferred” without pretending Go2 is
differential drive. Cache no obstacle heuristic whose cost field can become
stale while people move.

## 5. Smooth deterministic local controller

Use a regulated-pure-pursuit-style tracker as the first product controller.
For speed `v`, choose adaptive lookahead

\[
L_d=\operatorname{clip}(L_0+k_v|v|,L_{min},L_{max}).
\]

Transform the lookahead point to `base_link`, `(x_L,y_L)`, and compute

\[
\kappa=\frac{2y_L}{x_L^2+y_L^2}, \qquad \omega=v\kappa.
\]

The commanded forward speed is the minimum of independently interpretable
bounds:

\[
v=\min(v_{desired},v_{curvature},v_{clearance},v_{braking},v_{goal},v_{social}).
\]

Required behavior:

- enter rotate-in-place only for a large initial/path discontinuity error and
  leave it with hysteresis; do not re-enter for every small waypoint change;
- prune the path behind the robot and select lookahead by arc length;
- slow continuously with curvature, obstacle distance, stopping distance, and
  remaining goal-region distance;
- cap angular acceleration and pass every output through the existing final
  acceleration/jerk shaper;
- predict the command's footprint arc up to a bounded time-to-collision horizon;
- declare controller completion by region membership, not exact point/heading;
- preserve `vy` in the command type while nominal RPP emits zero lateral speed.

This directly addresses sliding and rotate-stop-go behavior. Nav2's RPP is
reported to run well above Parcel's required rate and explicitly supports
legged bases, but its standard form does not predict moving agents and does not
emit lateral velocity. Those remain Parcel layers, not reasons to discard RPP.

## 6. MPPI as a bounded challenger

MPPI is the preferred second controller because its omni motion model naturally
proposes `(vx, vy, yaw_rate)` and optimizes a time-indexed trajectory. At each
tick it samples control perturbations, rolls them through a measured motion
model, evaluates costs, and updates the nominal sequence with exponential
weights:

\[
w_k=\frac{\exp(-(S_k-\rho)/\lambda)}
          {\sum_j\exp(-(S_j-\rho)/\lambda)}.
\]

Parcel's critic set should include:

```text
goal-region progress + path alignment + swept-footprint clearance
+ time-indexed person occupancy + proxemic side preference
+ owner visibility/formation error + road/semantic constraints
+ acceleration + jerk + yaw oscillation
+ lateral penalty + reverse penalty + mode-switch penalty
+ terminal settling and controller-deadline penalty
```

Run MPPI in closed-loop mode using measured state, never an open-loop assumption.
Start it as a recorder: it receives the same snapshot and path as RPP, but its
output cannot actuate. Promote it only for an explicitly defined context, such
as dense crowds or tight docking, after paired replay shows better task and
social metrics with no safety, deadline, or oscillation regression. The final
collision monitor and Sport bridge remain unchanged.

Nav2 Humble's MPPI lacks acceleration constraints present in newer releases, so
Parcel's smoother and final shaper are mandatory if Humble is chosen for Unitree
compatibility. Do not copy current Nav2 parameter names into a Humble config
without a version pin.

## 7. Dynamic people and social navigation

Today a constant-velocity Kalman track and Gaussian route cost are reasonable
fallbacks. Extend them into uncertainty tubes:

\[
\mu_i(t)=p_i+v_i t, \qquad
\Sigma_i(t)=\Sigma_{p,i}+t^2\Sigma_{v,i}+Q_i(t).
\]

The soft cost should be anisotropic: more room in front of a walking person,
less behind, plus larger covariance and margins when classification, tracking,
or occlusion confidence falls. The local optimizer may prefer passing behind,
yielding, or replanning. It must never infer that a person will cooperate.

Separately, the final monitor evaluates current LiDAR geometry and conservative
relative-motion TTC. For object/person `i`, a simple barrier is

\[
h_i(p)=\|p_r-p_i\|^2-(r_r+r_i+m_i)^2.
\]

Commands that cannot preserve the configured barrier under bounded braking are
reduced or replaced by exact zero. Track loss near a recent person increases
uncertainty and holds; it does not erase the person immediately.

Initial product policy remains conservative: slow, stop, wait briefly, and
replan around people. Interaction-aware social policies, ORCA negotiation, or
learned crowd prediction remain shadow candidates until missed-detection,
minimum-separation, and deadlock behavior are measured. HuNavSim, SocNavBench,
and MetaUrban are useful complementary evaluation environments because the
current scripted MuJoCo crowd does not negotiate with the dog.

## 8. Owner following

Owner follow is not “navigate repeatedly to a moving point.” It is an
identity-aware formation task:

1. an enrolled camera track supplies identity confidence, bearing, visibility,
   heading, and velocity with uncertainty;
2. a short predictor estimates owner motion only while evidence is fresh;
3. the formation generator places a rolling goal region behind or beside the
   owner's heading, clipped to free, non-road, socially acceptable space;
4. local navigation preserves visibility, clearance, and a comfortable
   following distance rather than targeting the owner's body; and
5. loss transitions through `VISIBLE -> OCCLUDED -> REACQUIRE -> HOLD`, with a
   bounded targeted scan and no movement toward an unverified stranger.

Nav2's Following Server is a useful filtered moving-target controller reference,
but it does not solve owner enrollment/re-identification, sidewalk/road policy,
visibility-preserving formation, social passing, or terminal conversation.
Those stay in Parcel's `FollowFormation` layer.

## 9. Active semantic search

Replace the unconditional full-turn scan with information-directed search:

1. use a fresh in-frustum detection immediately when it passes class,
   confidence, repeat-observation, and reachability checks;
2. consult bounded semantic memory, reducing confidence with time, pose
   uncertainty, and scene change;
3. turn toward the best expected bearing or nearby occlusion edge;
4. if still unseen, rank reachable frontiers by semantic relevance,
   information gain, travel cost, risk, and owner-separation cost;
5. re-ground after every useful view, and stop scanning once evidence is
   sufficient; and
6. return honest `not_found` or clarify after a bounded budget.

A VLFM-style vision-language value map is a good learned proposal source for
frontier ranking. VLMaps/ConceptGraphs-style semantic memory can later improve
open-vocabulary place/object queries. Free-space admission, road policy,
referent class consistency, and terminal truth remain deterministic.

## 10. Behavior and reaction arbitration

The behavior executive owns priorities and checkpoints:

```text
latched E-stop / collision stop
    > operator manual command
    > system recovery / critical task phase
    > explicit owner motion or posture request
    > explicit social gesture
    > inferred-affect gesture
    > ambient expression
```

Conversation may stream during locomotion because it does not own the base.
An inferred emotion action never interrupts navigation or following. It may be
queued with a short TTL and executed only when the activity coordinator observes
an idle, safe checkpoint. A spoken empathetic response does not wait for body
motion. See [EMBODIED_EXPRESSION.md](EMBODIED_EXPRESSION.md) for the gesture
contract and current implementation boundary.

## Stable controller seams

The migration should preserve the current `Navigator` and `ControlManager`
boundaries while adding explicit candidate and evidence types:

```python
class GlobalPlanner(Protocol):
    def plan(self, snapshot: NavigationSnapshotV1,
             goal: GoalRegionV1) -> TimedPathV1: ...

class LocalController(Protocol):
    def propose(self, snapshot: NavigationSnapshotV1,
                path: TimedPathV1, deadline_ns: int) -> MotionCandidateV1: ...

class CandidateAdmitter(Protocol):
    def admit(self, candidate: MotionCandidateV1,
              snapshot: NavigationSnapshotV1,
              task: TaskRequestV1) -> AdmissionResultV1: ...

class TerminalWitness(Protocol):
    def evaluate(self, task: TaskRequestV1,
                 snapshot: NavigationSnapshotV1) -> WitnessResultV1: ...
```

`MotionCandidateV1` contains a finite horizon, frame, timestamps, bounds,
generator/version, task revision, evidence IDs, and predicted footprint. It is
not a command. Only the admitted winner is converted to one leased
`TimedVelocitySetpoint`; the final monitor may still reduce it.

## Component comparison

| Component | Use now | Advantage | Important limitation |
| --- | --- | --- | --- |
| Current rolling A* | Keep as fallback and regression oracle | CPU-fast, inspectable, already wired | 2-D and local; weak heading/motion continuity |
| Smac 2-D | First ROS-side global baseline | Cost-aware, simple, robust | Grid headings are not kinematically faithful |
| Smac State Lattice | Measured challenger after Smac 2-D | Go2-specific forward/lateral/rotation primitives and swept footprint | Extra state/primitive complexity; generate and validate only for a demonstrated residual |
| Regulated Pure Pursuit | First actuating local controller | Deterministic, smooth, light, legged-compatible | Path follower; no lateral output or predicted crowd interaction |
| MPPI Omni | Shadow challenger, then gated contexts | Time-indexed optimization and native `vy` | More tuning/compute; standard critics do not predict people |
| Nav2 Collision Monitor | Reference/possible ROS component in the final velocity chain | Independent stop/slow zones after the controller | Not safety-certified and not a substitute for hardware E-stop |
| Nav2 Route Server | City/indoor topological route layer | Semantic edges, closures, speed policies | Requires mapped route graph and local connectors |
| Nav2 Following Server | Reference for filtered moving-target goals | Useful lost-target/filter patterns | No owner identity or companion formation semantics |

## Learned navigation research lane

| System | Useful idea for Parcel | Placement | Do not claim yet |
| --- | --- | --- | --- |
| CityWalker | Urban video/history to waypoint/action proposal | Shadow semantic waypoint proposer after an RGB/history adapter and checkpoint-license review | Current Parcel factory cannot execute it; installed checkpoint alone proves nothing |
| NaVILA | Slow VLA emits spatial-language subgoals to a fast locomotion policy | Evidence for the slow-semantics/fast-control split | Not a direct Sport controller or product safety case |
| StreamVLN / InternNav | Streaming slow/fast visual context and Go2 research deployment | Research service for long-horizon instruction following | Heavy 8B-class runtime and benchmark transfer do not establish city companion safety |
| Uni-NaVid | Unified video navigation/tracking action model | Offline challenger on recorded observations | Discrete benchmark actions require an embodiment adapter |
| VLFM | Vision-language semantic value map over classical exploration | Frontier/semantic-search proposal | Does not replace metric collision avoidance |
| VLMaps / ConceptGraphs | Open-vocabulary spatial memory | Semantic referent and place retrieval | Map accuracy, change detection, and real-time budget must be measured |

Do not train a new end-to-end RL navigation model now. Existing open systems
are useful challengers, while Parcel currently lacks enough representative
camera/LiDAR/Go2 outcome data to justify a safe learned motor policy. Training
becomes rational only after the deterministic stack produces a versioned log,
a fixed observation/action schema, strong scripted and external baselines, and
a stable residual that simpler planning/controller changes cannot remove.

## Target rates and latency budgets

These are design targets to measure, not current guarantees:

| Loop | Target | Deadline behavior |
| --- | ---: | --- |
| sensor capture/timestamp validation | 20–30 Hz or device rate | stale frame is marked unusable |
| state estimation and dynamic tracking | 20–50 Hz | propagate bounded covariance; HOLD on frame fault |
| final collision monitor / command watchdog | at least 50 Hz on hardware path | exact zero and `StopMove` on stale/fault |
| local controller | 20–50 Hz | reuse safe fallback or zero on miss |
| global/local-map replan | 1–5 Hz and on invalidation | continue only along still-admitted prefix |
| open-vocabulary detector/segmenter | 5–15 Hz, asynchronous | previous evidence ages; never block control |
| VLM frontier/goal proposal | roughly 1–2 Hz, asynchronous | discard stale task/evidence revision |
| conversation/planning LLM | event-driven | acknowledgment and speech stream independently |

Each tick should trace sensor age, transform age, grounding, planning, controller,
admission, shaping, monitor, bridge, and feedback latency. Add p50/p95/p99,
deadline-miss counts, and `UserQueryEndToFirstReasoningResponse`/
`UserQueryEndToFirstResponse` correlation to task outcome rather than optimizing
only a single end-to-end number.

## Evaluation and promotion gates

Use the unchanged product behavior through adapters; never edit a benchmark to
make the dog easier to score. Freeze seeds, scene/episode versions, model hashes,
configuration, compute profile, and oracle access.

### Product task metrics

- semantic task success and success weighted by path length/time;
- correct referent/relation, false-arrival rate, and honest-not-found rate;
- collision count, minimum clearance, near-collision/TTC, and road violations;
- path efficiency, time to first progress, rotation fraction, lateral/reverse
  distance, jerk, yaw reversals, stop-start count, and settle time;
- owner formation error, visibility loss, identity swaps, reacquisition time,
  and personal-space intrusion;
- dynamic deadlocks, yield duration, replan oscillation, and recovery outcome;
- controller deadline misses, CPU/GPU/VRAM, sensor-to-stop p95/p99, and command
  age at the Sport bridge.

### Environment ladder

1. deterministic unit/property tests for transforms, goal regions, primitives,
   braking, arbitration, and witnesses;
2. Parcel's headless MuJoCo city tasks and dynamic-agent regressions;
3. BARN for geometric maze stress, Habitat/VLN for instruction/semantic stress;
4. HuNavSim and SocNavBench for pedestrian/social metrics;
5. MetaUrban for procedural city distribution shift;
6. recorded sensor replay, hardware-in-the-loop, then fenced low-speed Go2 tests.

A candidate promotes only on paired episodes against the current default. It
must improve its declared target metric, preserve all safety and truthfulness
gates, meet control deadlines on the target device, and retain the deterministic
fallback. Benchmark percentile is diagnostic; product task quality remains the
goal.

## Phased implementation and parallel work

### P0 — repair and freeze the baseline

- Fix search/re-ground, class-consistent commit, near-band terminal behavior,
  shared safety margins, person-release behavior, and budget attribution.
- Freeze traces and product scenarios before changing the controller.

Parallel lanes: semantic search; approach/terminal witness; safety-envelope
derivation; evaluation/trace substrate.

### P1 — smooth deterministic control

- Implement the RPP-style tracker behind the existing `Navigator` interface.
- Add adaptive lookahead, arc collision projection, continuous speed regulation,
  and rotate-mode hysteresis.
- Add rotation/lateral/reverse/path-efficiency metrics and paired scenarios.

Parallel lanes: controller implementation; property tests; tuning corpus;
instrumentation. Do not combine a new goal-grounding policy in the same A/B.

### P2 — route graph, formation, and an evidence-gated lattice experiment

- Build Go2 motion primitives and shadow a state-lattice planner only if P1
  traces show a repeatable heading/path-executability residual.
- Add the route-graph service/interface and semantic edge policies.
- Implement identity-aware rolling owner formation and bounded reacquisition.

Parallel lanes: primitive generator; route/map schema; owner perception; follow
evaluation. All converge on the same snapshot and goal-region contracts.

### P3 — dynamic-social challenger

- Add uncertainty tubes and anisotropic social costs.
- Run closed-loop MPPI Omni in shadow mode with the same observations and path.
- Promote only an explicit gated context after paired city/social benchmarks.

Parallel lanes: tracker/prediction; MPPI sidecar; HuNavSim/SocNavBench adapters;
deadline profiling.

### P4 — learned semantic challengers

- Resolve licenses and pin artifacts.
- Add RGB/history and semantic-map service adapters.
- Evaluate VLFM first for search, then CityWalker/StreamVLN/Uni-NaVid only as
  proposal sources on frozen replay and product episodes.

Parallel lanes: model service; recording/replay; license/model cards; offline
evaluation. No learned result receives direct motor authority.

### P5 — physical commissioning

- Validate timestamps, transforms, axes/signs, velocity deadbands, command lag,
  stopping distance, odometry drift, and conservative limits.
- Shadow navigation before actuation, then tethered/fenced low-speed trials.
- Preserve a physical E-stop and an independent onboard/native watchdog.

## Primary sources

- Macenski et al., [Regulated Pure Pursuit for Robot Path
  Tracking](https://arxiv.org/abs/2305.20026), and the official
  [Nav2 RPP implementation notes](https://github.com/ros-navigation/navigation2/blob/main/nav2_regulated_pure_pursuit_controller/README.md).
- Williams et al., [Model Predictive Path Integral Control](https://arxiv.org/abs/1509.01149),
  and the official [Nav2 MPPI configuration](https://docs.nav2.org/configuration/packages/configuring-mppic.html).
- Macenski et al., [Cost-Aware Kinematically Feasible Planning](https://arxiv.org/abs/2401.13078),
  and official [Nav2 planner selection](https://docs.nav2.org/setup_guides/algorithm/select_algorithm.html).
- Official Nav2 [Route Server](https://docs.nav2.org/configuration/packages/configuring-route-server.html),
  [Following Server](https://docs.nav2.org/configuration/packages/configuring-following-server.html),
  [Collision Monitor](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html),
  and [behavior-tree concepts](https://docs.nav2.org/concepts/).
- [CityWalker](https://github.com/ai4ce/CityWalker),
  [NaVILA](https://arxiv.org/abs/2412.04453),
  [StreamVLN](https://github.com/InternRobotics/StreamVLN),
  [Uni-NaVid](https://github.com/jzhzhang/Uni-NaVid),
  [VLFM](https://github.com/bdaiinstitute/vlfm), and
  [VLMaps](https://github.com/vlmaps/vlmaps).
- [HuNavSim](https://arxiv.org/abs/2305.01303),
  [SocNavBench](https://github.com/CMU-TBD/SocNavBench), and
  [MetaUrban](https://metaurban-simulator.readthedocs.io/).
- Official Unitree [Go2 Sport API](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp)
  and [ROS 2 integration](https://github.com/unitreerobotics/unitree_ros2).
- [KISS-ICP](https://github.com/PRBonn/kiss-icp) and
  [RTAB-Map](https://introlab.github.io/rtabmap/) for localization research.

## Known limitations of this recommendation

- Nav2 Humble is the safest current compatibility target for Unitree's official
  ROS 2 environment, but it lacks some newer controller features. A pinned
  cross-process sidecar adds lifecycle and schema work.
- A planar body-velocity abstraction cannot reason about stairs, footholds,
  deformable terrain, or whole-body contacts. Those require a terrain-aware
  locomotion interface later.
- Social navigation norms depend on culture, context, crowd density, and
  accessibility needs. Soft costs require user studies, not only collision-free
  simulation.
- Camera/LiDAR perception, localization, and owner identity are currently the
  largest reality gaps. Perfect simulator metadata must never be treated as
  evidence that those problems are solved.
- Collision Monitor and software TTC gates reduce risk but are not certified
  functional-safety systems.
