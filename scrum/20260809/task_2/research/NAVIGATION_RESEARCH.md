# Parcel navigation and instruction-following research

**Research date:** 2026-08-09  
**Scope:** Unitree Go2, camera + LiDAR only, Unitree Sport locomotion, low-latency owner companionship in indoor and urban environments  
**Evidence policy:** primary sources only (official documentation/repositories, project pages, and papers); all external claims were checked on 2026-08-09  
**Change scope:** research and design only; this report does not change runtime code, download a model, or promote an experimental controller

## Executive decision

Parcel should **not** replace its navigation stack with a monolithic VLA, and it should **not** train an end-to-end RL locomotion policy now. The best near-term system is a fast/slow hierarchy:

1. Keep Unitree's closed-loop Sport controller as the locomotion authority. Parcel supplies bounded body-frame velocity; Sport owns balance and gait.
2. Keep language models above the motor loop. The conversational brain may answer immediately, while the planning brain emits only a small typed semantic plan (`PlanSketch`), never coordinates, velocity, or joint targets.
3. Make a classical, sensor-closed navigation lane excellent first: one footprint/clearance authority, a cost-aware global planner, smooth yaw-aware path following, predicted-agent costs, and an unconditional post-shaper LiDAR/odometry safety gate.
4. Let vision-language/navigation models propose **semantic targets, pixel goals, or short local trajectories** through a time-bounded contract. A deterministic arbiter metricizes, validates, and may reject every proposal.
5. Evaluate learned systems in shadow before they can influence motion. The first useful learned experiments are open-vocabulary perception and frontier scoring, followed by local trajectory proposals. End-to-end learned motor control is the last experiment, not the first.

The concrete controller recommendation is:

- **Ship first:** Parcel's repaired semantic executive + a common costmap + Smac 2D/A* class global planning + Regulated Pure Pursuit (RPP)-style local tracking + current command shaper + final safety shield.
- **Shadow next:** Nav2 MPPI as a local-planner challenger, with Parcel-specific dynamic-person and lateral-motion critics.
- **Research shadow:** CityWalker, LeLaN, InternVLA-N1, NaVILA, and GenSafeNav behind one proposal adapter. None gets direct `/cmd_vel` or Sport access.
- **Watch only:** Qwen-RobotNav, Robostral Navigate, NavFoM, and the advertised SocialNav weights; usable official weights are not presently available for the first three, and SocialNav's two linked Hugging Face repositories are currently empty.

This is not a retreat from a capable robot dog. It preserves the embodiment and safety system while adding learned spatial judgment exactly where it is useful.

## 1. What Parcel actually has today

The current tree is more mature than a typical VLA demo, but several configuration names imply capabilities that do not exist on the live path.

| Area | Present implementation | Advantage | Limitation that matters now |
|---|---|---|---|
| Task planning | Compact `PlanSketch`, deterministic compilation to `PlanIR`, fail-closed validation, typed skills, resources, success facts, revisions and interruption policy | Correct separation of model semantics from trusted runtime bookkeeping | `ScanBehavior`/`SearchEntity` are not fully executable as system-authored plan skills, and common search paths are broken end to end |
| Navigation | `DirectiveNavigator` over `grid_v1`: rolling LiDAR occupancy grid, cost-aware 8-connected A*, known-free line-of-sight smoothing, replanning, yaw hysteresis, acceleration limits | Sensor-only, deterministic, understandable, already safe in tested product scenarios | Planner and gate use inconsistent clearance envelopes; excessive scan/rotation and final creep dominate time; search re-grounding fails |
| Dynamic agents | Predicted Gaussian-like cost lobes over constant-velocity tracks plus a command-level time-to-collision scale | Dynamic agents affect both planning and last-line braking | Track uncertainty is not propagated into the cost field; a `person_stop` can hold forever instead of causing a safe alternate-route decision |
| Owner following | Camera owner track, direct/behind formations, motion history, constant-velocity Kalman prediction, occlusion grace, owner-specific keepout | Appropriate companion-specific controller and fail-closed loss behavior | Identity enrollment/re-identification is not a complete product pipeline; nearest-person following must never be accepted as equivalent |
| Actuation | `UnitreeSportController` with measured `SportModeState`, supervised by `ControlManager` | Correct closed-loop boundary: Unitree owns gait/balance; Parcel can later swap locomotion backends | Navigation quality still depends on measured odometry freshness and a validated command cadence on hardware |
| Learned navigation | YAML records for CityWalker, NaVILA, NoMaD and ViNT; one CityWalker checkpoint and vendor tree are present | Useful artifact registry and legal provenance record | The live model factory supports only `stub` and `grid`. CityWalker's live adapter deliberately returns `UNVERIFIED`/skip; NaVILA/NoMaD/ViNT files are absent |
| Semantic perception | Seven authored classes, fixed aliases, semantic memory, geometric association, false-positive memory | Strong typed arrival/evidence design | The nominal SigLIP path is a hash placeholder, so this is still closed-world simulator semantics rather than open-vocabulary visual grounding |
| Safety | Collision brake, reactive person/obstacle gate, TTC supplement, command shaping, pose-uncertainty inflation | Zero hard collisions in the current product-path audit | Planning against a smaller radius than the gate creates routes the actuator must refuse; safety must inspect the final shaped command, not an earlier intent |

The measured evidence is in the [2026-08-09 task-1 audit](../../task_1/README.md). Its most important results are:

- Tier-C search-required episodes: **0% success**, even with 1,200 steps, although a target is emitted when it enters the camera frustum.
- Successful missions spend **44–88%** of wall time rotating, including an approximately 10.2 s opening scan.
- Mean translating speed is about **0.21 m/s** against a 0.9 m/s configured cap; the final 0.5 m closes near 0.032 m/s.
- Planner inflation is 0.42 m while the reactive gate rejects at 0.8 m, with no comfort-cost gradient; a live task spent 10.4 s stopped in that disagreement band.
- Plain `near` goals can stop roughly 1 cm outside the verified region; instance release can re-commit across semantic classes.
- A person at the approach pose can permanently defeat the task because `person_stop` never enters a safe reroute/reselection state.

These defects must be fixed before a learned challenger is credited with an improvement. Otherwise a model can merely route around a harness bug, and a regression can look like intelligence.

### Host and deployment constraints

The research workstation currently exposes an NVIDIA RTX 5000 Ada (32,760 MiB VRAM, compute capability 8.9), a 96-core Threadripper PRO 7995WX, and 246 GiB RAM. This is ample for parallel simulation and an 8B BF16 research model, subject to measured activation/KV-cache use. It does **not** prove an onboard Go2 computer can run the same workload.

The host is Ubuntu 26.04 and currently has no `ros2` command. Unitree's BSD-3-Clause ROS 2 repository still lists Ubuntu 22.04 + Humble as its recommended tested combination; its latest visible release is v0.3.0 dated 2025-08-15. ROS 2 Lyrical is the 2026 LTS for Ubuntu 26.04, but moving the robot bridge to it without Unitree validation would add risk. Use an isolated Ubuntu 22.04/Humble Unitree bridge first, or a carefully versioned process boundary; do not contaminate Parcel's Python environment merely to get Nav2. Sources: [Unitree ROS 2 README](https://github.com/unitreerobotics/unitree_ros2/blob/master/README.md), [v0.3.0 release](https://github.com/unitreerobotics/unitree_ros2/releases/tag/v0.3.0), [Unitree ROS 2 license](https://raw.githubusercontent.com/unitreerobotics/unitree_ros2/master/LICENSE), [ROS 2 distribution table](https://docs.ros.org/en/humble/Releases.html), [ROS 2 Lyrical release notes](https://docs.ros.org/en/kilted/Releases/Release-Lyrical-Luth.html).

## 2. Recommended production architecture

```text
microphone/text                                                      camera + LiDAR
      |                                                                    |
      v                                                                    v
streaming conversation lane                                  timestamped perception lane
  - ASR / response / affect                                    - open-vocab detections
  - may speak concurrently                                     - owner identity + tracks
      |                                                        - metric occupancy + semantics
      +----------------- semantic intent -----------------------+
                                |
                                v
                   planner lane (event driven / slow)
             rule router -> PlanSketch -> compiler -> validator
                                |
                                v
                    typed task executive / behavior tree
           task_id + revision + step + resource + checkpoint policy
                                |
                   semantic goal / formation / search request
                                v
             proposal arbiter + metric global/local navigation
        classical route | learned pixel/waypoint/trajectory proposals
                                |
                                v
                command shaper (acceleration and jerk bounds)
                                |
                                v
         FINAL LiDAR/odometry/person safety gate (may tighten or zero)
                                |
                                v
                 Unitree Sport Move(vx, vy, vyaw)
                                |
                                +------ SportModeState feedback -----+
```

The four non-negotiable invariants are:

1. A model output is a proposal, never proof that a target exists and never actuator authority.
2. Camera answers semantic questions; LiDAR and calibrated geometry answer metric traversability and clearance questions.
3. Every proposal carries observation time, frame, task ID, plan revision, step ID, expiry, source, confidence, and evidence references. Stale or cross-revision proposals are rejected.
4. The last safety check consumes the **actual outgoing shaped command** and freshest odometry/LiDAR snapshot. It can reduce or zero that command; it cannot invent motion.

### Separate conversation and planning brains

The system should separate them logically even if they share one set of weights initially.

- The **conversation lane** streams a natural response and manages dialogue memory. It may say “Okay, I’ll wait by the lamppost” quickly, but must phrase physical completion only after runtime evidence.
- The **intent fast path** deterministically compiles common commands: follow, stop, wait, move away N steps, orbit owner N times, sit, and known semantic `NavigateTo` forms. This avoids an LLM round trip for the most frequent commands.
- The **planning lane** handles ambiguity, multi-step requests, constraints and corrections. Its only model-owned fields should remain the goal relation/query, skill sequence, and bounded skill arguments. Parcel already has the correct `PlanSketch` shape.
- The **navigation proposal lane** is a different model role. A VLM/VLA may score frontiers or propose a pixel/local trajectory from fresh images. It should not write or revise conversational history.

This separation reduces latency, makes evaluation attributable, and prevents a friendly conversational reply from being mistaken for a physical action decision.

### Control timescales and budgets

These are target budgets to validate, not claims about current measured rates:

| Loop | Target cadence | Hard responsibility |
|---|---:|---|
| Unitree Sport internal locomotion | vendor-owned, faster than Parcel | balance, contacts, gait and body-velocity tracking |
| Final collision/TTC gate + command shaping | 50 Hz target; never below validated sensor cadence | inspect every outgoing command; stale input means stop |
| Local path tracker | 20–50 Hz | smooth SE(2) tracking and dynamic avoidance |
| Dynamic tracking/prediction | 10–20 Hz | people/owner state and uncertainty |
| Local costmap | sensor cadence, typically 10–20 Hz | free/occupied/unknown and dynamic layers |
| Global/local replanning | 2–10 Hz or on invalidation | route around new obstacles without path flapping |
| Semantic detector/tracker | measured 5–15 Hz target | open-vocabulary evidence; may run asynchronously |
| Slow VLM/VLA navigation proposal | 1–5 Hz | pixel/mid-term/trajectory suggestion only |
| LLM task planning | event-driven | semantic plan and revision, never a real-time controller |

Each loop needs a deadline-miss and stale-age metric. Do not hold the last nonzero command across an expired sensor or proposal lease.

## 3. Classical navigation: what to implement and why

### 3.1 One map and one clearance convention

The current 0.42 m planner versus 0.8 m gate disagreement is the first navigation defect to remove. Define one derived envelope:

```text
r_plan(v, Sigma_pose) = r_footprint
                      + margin_static
                      + k_v * |v|
                      + sqrt(chi2_2(1-alpha) * lambda_max(Sigma_pose_xy))
```

Use it consistently for occupancy inflation, line-of-sight smoothing, approach-pose generation, local planning, and the final gate. Social comfort is a **larger soft cost**, not a substitute for the hard collision envelope. The final gate may add uncertainty conservatism but the planner must know the same minimum refusal band, or it will keep requesting impossible routes.

Nav2's layered costmap provides a useful standard: the obstacle layer accepts `LaserScan`/`PointCloud2`, while inflation turns lethal geometry into a graded field. Sources: [Nav2 obstacle layer](https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html), [inflation layer](https://docs.nav2.org/configuration/packages/costmap-plugins/inflation.html), [costmap configuration](https://docs.nav2.org/configuration/packages/configuring-costmaps.html).

### 3.2 Global planner: Smac 2D first, State Lattice only if evidence warrants it

Nav2's [Smac planner](https://docs.nav2.org/configuration/packages/configuring-smac-planner.html) includes:

- cost-aware 2D A* for circular differential/omnidirectional bodies;
- Hybrid-A* for car-like constrained motion; and
- State Lattice planning with arbitrary motion primitives, including legged/omnidirectional control sets.

Go2 Sport accepts body-frame `vx`, `vy`, and yaw rate; it is not an Ackermann car. Therefore Hybrid-A* is not automatically the right choice just because it is “kinematically feasible.” Start with Smac 2D or Parcel's equivalent A*, using a well-shaped inflation field. Add State Lattice only if evaluation shows that explicit yaw state and primitive costs materially improve executability.

For a cell/primitive edge `e`, use a cost of the form:

```text
g(next) = g(current)
        + w_d * distance(e)
        + w_occ * occupancy_cost(e)
        + w_turn * |delta_yaw(e)|
        + w_lat * |lateral_distance(e)|
        + w_rev * reverse_distance(e)
        + w_dyn * predicted_agent_risk(e)
```

with `w_lat > w_d`: lateral motion is supported, but forward/yaw-aligned travel is preferred for ordinary point-to-point movement. Reverse is permitted for a bounded, freshly observed escape, not as the nominal style.

Retain partial/frontier routes in unknown environments. For long city routes, a route graph may provide sidewalks, crossings and building entrances, while LiDAR remains the local traversability authority. Nav2's route graph is a useful future pattern, not a replacement for perception: [Navigate on Route Graph behavior tree](https://docs.nav2.org/behavior_trees/trees/navigate_on_route_graph_w_recovery.html).

### 3.3 Local controller: RPP is the first baseline

Regulated Pure Pursuit is the lowest-risk improvement over Parcel's current point-waypoint tracker. It retains an understandable geometric path follower while regulating speed for curvature, obstacle proximity and terminal approach. Official sources: [RPP configuration](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html), [RPP paper](https://arxiv.org/abs/2305.20026), [Nav2 implementation README](https://github.com/ros-navigation/navigation2/blob/main/nav2_regulated_pure_pursuit_controller/README.md).

For a lookahead point `(x_L, y_L)` in the robot frame:

```text
L(v)       = clip(|v| * t_lookahead, L_min, L_max)
kappa      = 2 * y_L / L^2
omega      = kappa * v
v_command  = min(v_desired, v_curvature, v_obstacle_cost, v_goal_approach)
```

Parcel-specific behavior should be:

- enter a yaw-only alignment state when heading error exceeds an evaluated threshold;
- exit it at a smaller threshold (hysteresis); and
- otherwise turn **while moving** according to path curvature, which eliminates repeated stop/rotate cycles on modest bends.

RPP's rotate-to-heading mode is appropriate when the path starts behind the robot. Do not also wrap it with a second rotation shim; two heading state machines will fight. If MPPI is later used, Nav2's [Rotation Shim](https://docs.nav2.org/configuration/packages/configuring-rotation-shim-controller.html) can provide the same closed-loop yaw-first acquisition, using fresh odometry.

Humble RPP outputs `linear.x` and `angular.z`, not `linear.y`. Thus it preserves Parcel's preferred forward/yaw point-to-point style but cannot exercise Go2 lateral motion. That is acceptable for the first baseline; MPPI's `Omni` model is the later lateral-capable challenger.

The current Parcel preference remains valid: `vy` is allowed, but point-goal progress normally uses forward velocity plus yaw. A controller objective can express this without banning lateral motion:

```text
J_motion = w_path * cross_track_error^2
         + w_yaw * heading_error^2
         + w_lat * vy^2                 # w_lat deliberately high
         + w_acc * ||u_t-u_(t-1)||^2
         + w_jerk * ||u_t-2u_(t-1)+u_(t-2)||^2
```

Use lateral velocity for collision escape, close formation correction, and constrained docking where it objectively improves clearance or comfort.

### 3.4 MPPI is the strongest local-planner challenger, not the day-one authority

Nav2's [MPPI controller](https://docs.nav2.org/configuration/packages/configuring-mppic.html) samples perturbed control sequences, forward-simulates the motion model, scores trajectories with plugins, and updates controls using a soft minimum:

```text
S_k = terminal_cost(x_T) + sum_t q(x_t, u_t)
rho = min_k S_k
w_k = exp(-(S_k-rho)/lambda) / sum_j exp(-(S_j-rho)/lambda)
u_t <- u_t + sum_k w_k * epsilon_(k,t)
```

Its key advantage for Parcel is not generic “AI”; it is joint optimization of path tracking, yaw, speed, obstacle cost, predicted-person occupancy, lateral preference and smoothness over a horizon. It supports differential, omnidirectional and Ackermann motion models.

Why shadow first:

- cost weights can produce plausible but socially wrong local minima;
- a dynamic-person critic and Unitree-specific motion limits must be written and evaluated;
- its compute claim (the official docs report over 100 Hz on one older Intel i5) is upstream evidence, not a Parcel/Go2 guarantee; and
- it still needs the independent final safety gate.

For the Unitree-compatible Humble lane, MPPI uses `motion_model: "Omni"` and can emit `(vx, vy, wz)`. Its common default `model_dt=0.05`, `time_steps=56` gives a 2.8 s rollout; the controller period must not exceed `model_dt`, and the local costmap must contain the full reachable rollout. Humble MPPI does not model acceleration bounds—the `ax/ay/az` limits arrived on later release lines—so Parcel's external shaper/slew limiter is mandatory. Its standard critics see the current costmap, not future tracked-person trajectories; a Parcel dynamic-agent critic/layer is additional work. Source: [Humble MPPI README](https://raw.githubusercontent.com/ros-navigation/navigation2/humble/nav2_mppi_controller/README.md), [Humble optimizer](https://raw.githubusercontent.com/ros-navigation/navigation2/humble/nav2_mppi_controller/src/optimizer.cpp), [Nav2 Iron/Jazzy migration](https://docs.nav2.org/migration/Iron.html).

Promotion gate: against the same frozen scenarios, MPPI must preserve zero collisions and improve at least two of time-to-goal, path jerk, time stopped, or minimum social clearance without increasing semantic false arrival.

### 3.5 Behavior trees belong inside the executive, below model semantics

Nav2's default [NavigateToPose behavior tree](https://docs.nav2.org/behavior_trees/overview/detailed_behavior_tree_walkthrough.html) replans periodically, performs contextual recovery, then bounded system recovery. This is the right model for `PlanPath -> FollowPath -> Verify -> bounded recovery` and for a dynamic target whose goal updates.

It is not a reason to let an LLM generate XML. Parcel's `task_id`, revision, typed success fact, resource arbitration and interruption checkpoint remain the outer executive. Each admitted physical skill may map to a tested BT subtree:

```text
NavigateTo(entity)
  Sequence
    ResolveOrSearch(entity)
    ComputeSafeGoalRegion(entity)
    RepeatUntilArrived
      Fallback
        Sequence(UpdateCostmap, PlanPath, FollowPath)
        ContextRecovery
    StopAndVerify(entity, relation, evidence_window)
```

Recovery counts, timeouts and allowed nodes are system-owned. A model may select `NavigateTo` or `SearchEntity`; it may not select an arbitrary recovery primitive.

Do not copy current-main XML or parameter names into Humble. Humble uses BehaviorTree.CPP v3, slash-form plugin names such as `nav2_smac_planner/SmacPlanner2D`, and an RPP parameter surface that predates current Dynamic Window Pure Pursuit. Its default navigation tree replans at 1 Hz and includes spin/wait/backup recovery; Parcel must either replace unsafe/inapplicable recoveries or route them through the same shaper and final gate. The newer Following Server is a useful design reference but is not a Humble baseline. Sources: [Humble default BT XML](https://raw.githubusercontent.com/ros-navigation/navigation2/humble/nav2_bt_navigator/behavior_trees/navigate_to_pose_w_replanning_and_recovery.xml), [Humble Smac plugin XML](https://raw.githubusercontent.com/ros-navigation/navigation2/humble/nav2_smac_planner/smac_plugin_2d.xml), [Kilted migration notes](https://docs.nav2.org/migration/Kilted.html).

## 4. Semantic and instruction-following navigation

### 4.1 Treat commands as goal sets and constraints, not points

“Go to the sidewalk” does not mean one coordinate. It means enter any locally reachable, sufficiently large sidewalk region while avoiding the road. “Wait by the lamppost” means stop in an annulus around the selected lamppost, outside forbidden road space, with safe clearance. “Walk around me once” is a path topology condition around an enrolled owner track.

Represent a task with:

```text
GoalSet = {
  semantic predicate,       # sidewalk, lamppost, enrolled owner
  spatial relation,         # inside, near, behind, orbit
  allowed metric band,
  forbidden semantic regions,
  final heading rule,
  evidence and confidence requirements
}
```

The planner chooses a reachable pose **inside** that set with an inset for discretization and stop error. Arrival verification evaluates the same set. This directly prevents the current “stop 1 cm outside the `near` band” failure.

For a `near` object with surface distance `d_s`, target band `[d_min, d_max]`, and margin `epsilon`, plan toward:

```text
d_target = clip((d_min + d_max)/2, d_min + epsilon, d_max - epsilon)
```

and reject any bearing whose swept body footprint intersects hard geometry or forbidden semantic regions.

### 4.2 Open-vocabulary perception should propose evidence, not write the map directly

A practical first stack is:

1. Open-vocabulary boxes from [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) (Apache-2.0 code).
2. Temporal masks/tracks from [SAM 2](https://github.com/facebookresearch/sam2) (Apache-2.0 code/checkpoints) or a lighter measured alternative.
3. Image/text candidate scoring with [SigLIP 2](https://github.com/google-research/big_vision) (Apache-2.0 unless a particular artifact says otherwise).
4. Camera-to-LiDAR association to obtain metric surface/region geometry and covariance.
5. A classical multi-object tracker and semantic memory with negative observations, TTL, revisit suppression and class/instance commitment.

The detector query can be open-ended (“red pharmacy sign,” “Starbucks,” “sidewalk”), but a candidate is admitted only with timestamped image evidence, class score, metric association quality and a reachable goal region. Brand recognition may require OCR/sign retrieval in addition to object detection.

For owner following, use explicit enrollment plus separate tracking and re-identification:

- associate detections over adjacent frames with a tracker such as [ByteTrack](https://github.com/FoundationVision/ByteTrack);
- compare enrolled appearance embeddings with a reviewed re-identification model such as [FastReID](https://github.com/JDAI-CV/fast-reid) (Apache-2.0 code); and
- retain a stable owner identity only through confidence hysteresis and geometric continuity.

If two people are ambiguous, hold/reacquire. Never silently switch to the nearest person. Appearance embeddings are biometric-like personal data and need a privacy/retention policy; repository license does not establish training-data provenance or product legality.

### 4.3 Search: implement the VLFM/InstructNav pattern, not a blind full turn

[VLFM](https://github.com/rai-opensource/vlfm) (ICRA 2024, MIT code) constructs depth occupancy frontiers and uses a VLM-derived language value map; [InstructNav](https://arxiv.org/abs/2406.04882) decomposes language into landmark/action structure and fuses multiple value maps. They support the right design boundary: the learned component scores semantic promise; classical geometry decides which frontier is reachable.

For each reachable frontier `f`:

```text
J(f) = alpha * semantic_score(f, query)
     + beta  * information_gain(f)
     - gamma * geodesic_distance(f)
     - delta * predicted_dynamic_risk(f)
     - eta   * revisit_or_refutation_cost(f)
```

Required changes to Parcel's search loop:

- re-ground after **every** new semantic frame while scanning or traveling;
- stop searching as soon as the same-class target meets admission confidence;
- lock the requested class across unreachable release; never turn “big tree” into a lamppost;
- maintain persistent see-then-lose memory across commands;
- scan while moving toward a known-safe frontier when possible;
- use a bounded yaw-only scan only when no safe translational information action exists; and
- distinguish `not observed yet`, `observed and rejected`, `unreachable instance`, and `target class absent within budget`.

The upstream VLFM environment is old (Python 3.9, Torch 1.12/CUDA 11.3, pinned GroundingDINO, YOLOv7 and Habitat dependencies). Reimplement the small algorithm against Parcel's typed frontier/scorer interfaces; do not vendor the entire dependency stack into production.

### 4.4 Owner following is formation control around an identity, not generic PointNav

Given enrolled owner state `(p_o, v_o, Sigma_o)`, define a short-lived lead and behind point:

```text
p_lead   = p_o + tau * v_o
h_o      = v_o / ||v_o||                     if heading is reliable
p_behind = p_lead - d_follow * h_o
```

The desired goal lease should be short (for example 0.2–0.5 s), replanned continuously, and invalidated on stale/ambiguous identity. If heading is unreliable, direct follow may use a radial standoff; the explicit `behind` relation must hold until heading becomes reliable rather than chasing the owner point.

Nav2's current [Following Server](https://docs.nav2.org/configuration/packages/configuring-following-server.html) is a useful implementation reference: it follows a changing `PoseStamped`/TF target, maintains standoff, has detection timeout, and searches after loss. It does **not** solve owner identity. Parcel should retain enrollment, formation semantics and safety, while borrowing the short-TTL dynamic-goal/control pattern.

### 4.5 Dynamic people: uncertainty-aware planning now, learned prediction in shadow

Parcel already has constant-velocity tracks and TTC. Extend them to propagate covariance:

```text
mu_i(t)    = F(t) * state_i
Sigma_i(t) = F(t) * Sigma_i(0) * F(t)^T + Q(t)
```

A conservative collision tube at confidence `1-alpha` is:

```text
r_tube_i(t) = r_robot + r_person
            + sqrt(chi2_2(1-alpha) * lambda_max(Sigma_i,xy(t)))
unsafe if ||p_robot(t) - mu_i,xy(t)|| <= r_tube_i(t)
```

This converts low-confidence prediction into **more caution**, not an arbitrary lower model confidence score. A person blocking the current approach should cause: stop -> wait briefly -> replan around the predicted tube -> select another semantic approach pose -> honest blocked result. It must never “release” the safety stop into the person.

Use [Trajectron++](https://github.com/StanfordASL/Trajectron-plus-plus) as a multi-modal, map-aware prediction shadow, and [GenSafeNav](https://github.com/tasl-lab/GenSafeNav) as a current conformal-uncertainty/RL research reference. GenSafeNav released MIT-licensed test, training, pretrained-model and ROS 2 code by 2026, but its crowd-state observation assumptions must be made sensor-equivalent before any comparison. Constant velocity with calibrated covariance is the deployable baseline.

[ORCA/RVO2](https://github.com/snape/RVO2) (Apache-2.0) is valuable as a fast velocity-obstacle baseline and simulator crowd policy. Its reciprocal-responsibility assumption is unsafe as Parcel's sole real-world rule: a distracted pedestrian is not guaranteed to take half the avoidance action. Use full-responsibility robot constraints or treat ORCA as a proposal under the final gate.

## 5. Model landscape: what is actually usable

“Open paper” and “open repository” do not imply downloadable, product-licensed weights. The table separates algorithmic value from deployability.

| System | Officially available on 2026-08-09 | Fit for Parcel | Decision |
|---|---|---|---|
| [VLFM](https://github.com/rai-opensource/vlfm) | MIT code and component weights through upstream projects | Best immediate blueprint for semantic frontier scoring; deployed by authors on Spot | Implement the algorithm against Parcel interfaces now; no wholesale environment import |
| [InstructNav](https://arxiv.org/abs/2406.04882) | Paper/project artifacts; no production-ready Parcel dependency | Typed landmark/action decomposition and value-map fusion | Preserve/adapt the concepts; repair Parcel's current partial implementation |
| [CityWalker](https://github.com/ai4ce/CityWalker) | Apache-2.0 repository; official checkpoint exists; Parcel already has the 1.75 GB v1.0 artifact | Urban point-goal imitation prior, not language grounding or a safety layer | First installed learned trajectory shadow, after a real RGB/history adapter; original Parcel lock correctly marks the exact checkpoint license `NOASSERTION` |
| [LeLaN](https://github.com/NHirose/learning-language-navigation) | MIT code, public weights, Go1 + Jetson Orin AGX deployment | Strong visible-target last-mile language-conditioned policy | Shadow for bounded last-mile proposals only. Its README says the default deployment does not consider collision avoidance; LiDAR gate remains mandatory |
| [NaVILA](https://github.com/AnjieCheng/NaVILA) | Apache-2.0 code, Llama-3-based 8B checkpoints/training artifacts, Go2 research system | Very relevant high-level language action decomposition | Shadow its mid-level semantic actions; do not replace Unitree Sport with its learned joint locomotion. Check Meta Llama weight terms and every dataset license |
| [InternVLA-N1 / DualVLN](https://github.com/InternRobotics/InternNav) | MIT toolbox and official 8B BF16 checkpoints; official Go2 community deployment link | Strongest downloadable 2026 fast/slow VLN candidate: slow pixel-goal grounding + fast smooth trajectory policy | Highest-priority sandbox model. Its Hugging Face model card has missing license metadata; InternData-N1 is gated CC BY-NC-SA 4.0. No product promotion before legal provenance review |
| [SocialNav](https://github.com/AMAP-EAI/SocialNav) | Apache-2.0 code; repository says Qwen2/Qwen2.5 SAFE-GRPO checkpoints are available | Directly targets social traversability and flow-based trajectories | **Unavailable today:** both official HF links contain only `.gitattributes` (1.52 kB), with no model files or card. Track and retry later; do not claim installed weights |
| [LISN](https://social-nav.github.io/LISN-project/) | Research code targets ROS Noetic/Ubuntu 20.04 and calls external VLM APIs; repository license is not explicit | Excellent fast/slow idea: language/VLM selects bounded controller and costmap modulation | Reproduce the interface idea, not the legacy stack. A model may choose a safe profile or add costs, never lower hard safety limits |
| [GenSafeNav](https://github.com/tasl-lab/GenSafeNav) | MIT code, training, pretrained policies and ROS 2 implementation | Strong crowd-navigation and uncertainty challenger | Shadow after a camera/LiDAR track adapter; extract conformal uncertainty ideas before considering its RL policy |
| [Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav) | Technical report and demos only; official README explicitly says no plan to release weights | Highly relevant unified 8-waypoint `(x,y,theta)` interface and context-control design; official Go2/Jetson Thor demonstration | Watch/reimplement interface lessons only; cannot download or evaluate the model |
| [Robostral Navigate](https://mistral.ai/news/robostral-navigate/) | Official article/paper and sales contact; no official downloadable checkpoint located | Useful pointing + local-displacement proposal design | Watch only. Do not call it open-weight |
| [NavFoM](https://pku-epic.github.io/NavFoM-Web/) | Paper/project page; no official code or weight link located | Cross-embodiment/task foundation-model research | Watch only |
| [OmniNav](https://github.com/amap-cvlab/OmniNav) | Code and some ModelScope checkpoints | Strong prospective exploration/slow-fast research | Legal hold: official repository exposes no license file/label; do not integrate until terms are explicit |

### What to learn from the unavailable leaders

Qwen-RobotNav is still architecturally instructive. It uses one waypoint head but controls visual token budget, temporal decay, per-camera weights and frame sampling by task. Its 2026 technical report describes eight `(x,y,theta)` waypoints and an upper planner with compact memory; the authors report 196 ms / 5.1 Hz on Go2 with Jetson Thor. Treat that number as upstream evidence, not a Parcel budget. The lesson is a typed, task-adaptive observation protocol—not model-to-motor authority.

Robostral's useful idea is to predict a pixel target plus terminal orientation when visible, falling back to a local-frame displacement when the target is outside the image. Parcel can metricize a pixel through calibrated camera/LiDAR geometry and reject it if no safe ground intersection exists.

The common winning pattern across InternVLA, Qwen-RobotNav, SocialNav and LISN is a **dual system**: a slower semantic model establishes intent or a mid-term target, while a fast trajectory/controller loop reacts to geometry. That confirms Parcel's current boundary rather than replacing it.

### Do not train our own broad navigation foundation model now

Training a CityWalker/InternVLA-scale foundation model is not justified by Parcel's present evidence. It would require large, legally usable embodied datasets, extensive simulation variation, closed-loop DAgger/RL, and hardware transfer work while known deterministic bugs remain.

Training becomes rational only after all of these are true:

1. the classical baseline and proposal adapter are frozen and reproducible;
2. a licensed open checkpoint loses on a clearly defined Parcel residual (for example, owner-crowd identity recovery or sidewalk social compliance);
3. at least thousands of representative sensor-faithful failure/recovery trajectories exist;
4. held-out city, indoor, weather, lighting, crowd and embodiment splits are immutable;
5. reward hacking is checked with safety, comfort and semantic counter-metrics; and
6. a trained model improves closed-loop success with a confidence interval, not merely waypoint imitation loss.

Before RL, try in this order: adapter/harness fixes -> prompt/schema and deterministic compiler -> open-weight zero-shot -> supervised adapter/LoRA on licensed data -> DAgger in simulation -> constrained/offline RL -> hardware shadow. RL may optimize a residual local cost or proposal ranker; it must not learn around or weaken the safety gate.

## 6. Typed learned-proposal interface

Extend the existing `SE2Goal`/proposer design rather than adding a parallel direct-control path. A minimal contract is:

```python
@dataclass(frozen=True)
class NavProposalV1:
    schema_version: Literal[1]
    proposal_id: str
    task_id: str
    plan_revision: int
    step_id: str
    source_model: str
    source_artifact_sha256: str
    frame: Literal["camera", "base", "odom"]
    kind: Literal["pixel_goal", "local_goal", "local_trajectory", "frontier_scores"]
    observed_through_monotonic_s: float
    issued_monotonic_s: float
    expires_monotonic_s: float
    confidence: float
    points: tuple[TrajectoryPoint, ...]       # bounded count/horizon; no joint/raw motor target
    evidence_refs: tuple[str, ...]
    uncertainty: tuple[Covariance2D, ...]
```

Admission pseudocode:

```python
def admit(proposal, snapshot, active_task):
    require proposal.task_id == active_task.task_id
    require proposal.plan_revision == active_task.revision
    require proposal.step_id == active_task.current_step_id
    require now <= proposal.expires_monotonic_s
    require proposal.observed_through_monotonic_s >= snapshot.minimum_usable_time
    require calibrated_frame_transform(proposal.frame)

    metric = metricize_with_camera_and_lidar(proposal)
    require all_finite_bounded(metric)
    require same_semantic_target(metric, active_task.goal)
    require reachable_on_current_costmap(metric)
    require collision_and_dynamic_risk_below_limit(metric)
    return short_ttl_reference(metric)       # still followed by local controller and final gate
```

Record every rejected proposal and reason. Shadow evaluation must replay the same timestamped sensor snapshot to each challenger; giving one model oracle poses or future frames invalidates the comparison.

## 7. Preemption and natural companion behavior

The planner may output the **next semantic action**, but not the next motor command. Interruption is a runtime decision based on priority, resources, and safe checkpoints.

Recommended precedence:

```text
emergency/manual/deadman/stale-sensor stop
  > collision avoidance / balance recovery
  > explicit user cancel or correction
  > critical battery return/sit policy
  > active navigation/follow task
  > requested gesture
  > inferred-affect gesture / idle animation
```

Examples:

- If the user sounds sad during safe idle, queue `Pose(bow)` and a gentle spoken response.
- If the user jokes during navigation, speech may chuckle concurrently; a leg gesture waits until navigation releases the base/pose resources.
- If the user says “stop,” cancellation is immediate and system-owned.
- If low battery becomes critical, the trusted policy cancels/revises navigation, reaches a safe pose if feasible, then sits. An LLM does not decide the battery threshold.
- If the user corrects “not that lamp—the one by the shop,” create a new plan revision, invalidate all old proposals, preserve safe stop, and re-ground.

This uses Parcel's existing `interruptibility`, resources and revision semantics. Do not add a free-form “override current action” bit from the language model.

## 8. Phased implementation plan

### Phase 0 — repair and instrument the current baseline (must happen first)

1. Fix the `SearchEntity`/`ScanBehavior` re-ground loop and make those skills executable through the runtime adapter.
2. Use one class-locked commitment key; unreachable release may change instance but not requested class.
3. Plan to an inset of every verified goal set and check “inside goal” before terminal heading alignment/step-limit accounting.
4. Derive planner inflation, approach clearance, safe-valley radius and final gate from one footprint/envelope authority; add a soft comfort field.
5. Replace permanent `person_stop` waiting with stop -> bounded dwell -> predicted-tube replan -> alternate approach; never move while the hard person gate is active.
6. Skip the opening full turn when the target is already resolved. Re-ground continuously and scan toward information gain while translating safely.
7. Preserve `SemanticMemory2D` across multi-command episodes and add see-then-lose tests.
8. Instrument per-loop latency, stale ages, time rotating/translating/stopped, gate reasons, replan reasons, proposal rejection and task revision.

**Exit gate:** frozen v3 minival exceeds current baseline rather than merely matching it; Tier-C search succeeds; false arrival 0; cross-class arrival 0; hard collisions 0; no step-limit result while already in the goal; planner-gate disagreement time 0.

### Phase 1 — smooth classical controller A/B

Build one isolated ROS 2/Nav2 compatibility spike or port the exact algorithms behind Parcel's existing navigator interface:

- common costmap/footprint;
- Smac 2D and RPP configuration;
- dynamic target updates;
- command adapter `Twist -> MidLevelCommand -> shaper -> final Parcel gate -> Sport`;
- no second actuator authority.

A/B current `grid_v1` against RPP/Smac on identical sensor traces. Keep a hardware-independent interface so simulation and Go2 differ only below the control backend.

**Exit gate:** zero collisions; at least 30% reduction in rotate fraction and 25% reduction in median time-to-goal on the existing successful set; 95th-percentile command jerk does not regress; 99.9th-percentile control loop meets deadline on the target computer.

### Phase 2 — open-vocabulary semantic navigation

- Replace hash semantics with a measured GroundingDINO/SAM2/SigLIP2 candidate pipeline.
- Add camera-LiDAR metric association and covariance.
- Implement VLFM-style reachable frontier scoring, negative memory, class lock and explicit not-found budgets.
- Add brand/sign OCR as a separate evidence provider.

**Exit gate:** held-out synonyms/classes and distractors; calibrated precision/recall; zero oracle semantic IDs; target instance success and semantic false-arrival confidence intervals; latency measured under concurrent voice load.

### Phase 3 — owner identity and social dynamics

- Enrolled owner re-identification plus short-term tracking.
- Covariance-propagated dynamic-agent tubes and alternate-route handling.
- HuNavSim/MetaUrban crowd scenarios: crossing, overtaking, bottleneck, group, stationary blocker, threatening blocker, owner/person crossing and prolonged occlusion.

**Exit gate:** zero owner switches, collision upper confidence bound below the product threshold, owner reacquisition success, minimum-clearance distribution, discomfort/intrusion time, formation error and task completion.

### Phase 4 — learned proposer tournament

Implement only `NavProposalV1` adapters. Suggested order:

1. installed CityWalker checkpoint (urban local trajectory);
2. LeLaN (visible-target last mile);
3. InternVLA-N1 System 2 / DualVLN in a license-isolated research sandbox;
4. NaVILA mid-level language actions;
5. GenSafeNav crowd proposal; and
6. MPPI with learned semantic/social critics.

Each runs shadow -> advisory -> gated canary. A proposal model is promoted only if the deterministic baseline remains available as a per-tick fallback.

### Phase 5 — targeted learning only after residual analysis

Train a small ranker, critic or adapter for the measured residual. Prefer parameter-efficient tuning and imitation/DAgger before RL. Keep the base planner, proposal schema and safety checks unchanged so gains are attributable and reversible.

## 9. Falsifiable evaluation design

### Three levels; never blend their metrics

1. **Pure algorithm tests:** fixed grids/tracks/commands; no perception. Test optimality, reachability, collision geometry, prediction and state-machine invariants.
2. **Sensor-faithful closed-loop simulation:** only camera/LiDAR/odometry inputs visible to Parcel; semantic truth is evaluator-only.
3. **Hardware validation:** measured Go2 odometry, DDS loss/delay, Sport response, sensor timestamps, emergency stop and human safety supervision.

Oracle-state benchmark scores must be labeled separately from sensor-faithful product-path scores.

### Required scenario families

| Family | Examples | Primary success predicate |
|---|---|---|
| Semantic regions | go/get off road to sidewalk; enter shop; avoid lawn | final footprint contained in requested allowed region; forbidden exposure bounded |
| Semantic objects | wait by lamppost; nearest bench; red sign by store | correct instance/class, surface-distance band, collision-free stable stop |
| Search | target behind; target initially absent; distractors; see-then-lose | find or honestly exhaust budget; no repeated refuted frontier |
| Owner behaviors | follow, behind, orbit once, move away five steps | enrolled identity retained; formation/orbit topology and distance satisfied |
| Dynamic social | crossing, oncoming, overtaking, group, bottleneck, blocker | collision 0; comfort clearance; progress or honest blocked terminal |
| Corrections/preemption | “not that one”; stop; manual takeover; low battery | old revision produces no later command; bounded stop latency |
| Robustness | lighting, blur, dropout, LiDAR noise, pose covariance, latency burst | graceful degradation; stale data cannot cause motion |

### Metrics and gates

Report distributions and confidence intervals, not one mean:

- task success, semantic success, search success, SPL and navigation error;
- wrong-class, wrong-instance and false-arrival rates;
- collision/contact rate with one-sided 95% upper confidence bound;
- minimum hard clearance, personal-space intrusion duration, time-to-collision interventions;
- time-to-first-progress, time-to-goal, path length, rotate/translate/stop fractions;
- mean/95th/99th command acceleration and jerk; lateral-motion fraction;
- owner ID switches, lost time, reacquisition time, formation RMS error;
- planner/controller/safety deadline misses and sensor/proposal age;
- proposal accept/reject/fallback counts by source; and
- UserQueryEndToFirstReasoningResponse and UserQueryEndToFirstResponse, measured separately from physical completion.

For paired policies, use identical seeds and episodes. Publish the manifest hash, code commit, artifact digest, config digest, driver/CUDA version, GPU, warmup policy and raw per-episode rows. Do not tune on the held-out city/person trajectories.

### External environments worth adding

- [MetaUrban](https://github.com/metadriverse/metaurban) (Apache-2.0 code) is the best immediate dynamic urban simulator: procedural streets, objects, pedestrians/vehicles/robots, RGB/depth/semantic/LiDAR, Gym interface, and provided RL baselines. Its full assets require registration and carry their own terms. The official docs say one simulator instance per process; parallelize by process, not thread.
- [HuNavSim 2.0](https://github.com/robotics-upo/hunav_sim) (MIT, tested ROS 2 Humble) is the best focused human-behavior test source. It includes groups and regular, impassive, surprised, curious, scared and threatening reactions, plus evaluator metrics and multiple simulator wrappers.
- [SocNavBench](https://github.com/CMU-TBD/SocNavBench) (MIT) provides scenarios grounded in real pedestrian trajectories. It is useful for planner comparison, though its older environment should remain isolated.
- [SocNavGym](https://github.com/gnns4hri/SocNavGym) is lightweight and useful for policy experiments, but is GPL-3.0 and exposes structured entity state. Its oracle observation must not be reported as Parcel camera/LiDAR performance.
- [NaVILA-Bench](https://github.com/yang-zj1026/NaVILA-Bench) and InternNav/Habitat are useful for model-native shadow scores, not as the product bar. Adapter code must not change Parcel behavior or grant oracle inputs.

The earlier BARN/Habitat portfolio remains archived as decided by task 1. Revive one external environment only with an immutable container/commit, a sensor-equivalent adapter, and a metric that tests a current product hypothesis. Top-10-percentile external scores are a research goal, but never a license to distort the Go2 embodiment or bypass safety.

## 10. Parallel work boundaries

These lanes can proceed concurrently after Phase 0 contracts are frozen:

| Lane | Owns | Must not own |
|---|---|---|
| Navigation/control | costmap, planner/controller adapters, shaper and replay A/B | language semantics or owner identity |
| Perception/grounding | open-vocab evidence, camera-LiDAR association, tracking/memory | actuator commands or arrival policy |
| Owner/social | enrollment, formation, prediction uncertainty and social scenarios | generic object grounding |
| Executive/voice | PlanSketch contracts, corrections, resources, speech timing | raw geometry/control |
| Learned-model lab | isolated model images, proposal adapters, shadow inference and artifact licenses | runtime promotion or safety changes |
| Evaluation | manifests, adapters, metrics, confidence intervals and ledgers | policy tuning on the held-out split |

Every lane integrates through versioned contracts and a recorded sensor snapshot. This permits parallel model research without allowing multiple teams to create competing command paths.

## 11. Immediate backlog in order

1. Repair search re-grounding and executable scan/search skills.
2. Unify hard clearance and goal-region geometry; fix near-band inset and cross-class release.
3. Add a bounded dynamic-person reroute state; preserve stop while blocked.
4. Remove unnecessary opening scan and terminal creep; measure phase occupancy.
5. Build frozen RPP/Smac 2D A/B behind `Navigator`; decide whether to port algorithms or run a Humble Nav2 bridge after the compatibility spike.
6. Define and test `NavProposalV1`; add a no-model deterministic fake and rejection telemetry.
7. Replace stub semantics with an open-vocabulary, camera-LiDAR evidence lane.
8. Complete enrolled-owner identity/re-identification and ambiguity tests.
9. Add MetaUrban dynamic-city and HuNavSim crowd adapters without oracle observation leakage.
10. Wire the already-installed CityWalker checkpoint for **shadow-only** inference, then benchmark LeLaN and InternVLA-N1 under the same proposal contract.
11. Shadow MPPI and GenSafeNav; promote only against frozen paired gates.
12. Revisit targeted training only from a documented residual-error taxonomy.

Before the first hardware-moving Nav2 trial, measure Go2's realizable `vx`, `vy`, yaw-rate, acceleration/deceleration, deadbands, command latency and stale-command stopping behavior. Unitree's official sources expose `Move(vx, vy, vyaw)` but do not publish authoritative safe axis bounds. The one command bridge must clamp to measured conservative limits, stop on lease/watchdog/lifecycle failure, call `StopMove()`, and be mutually exclusive with joystick/manual publishers.

## 12. Source and licensing register

All entries were accessed 2026-08-09. A repository license covers that repository unless the artifact/model/data page explicitly extends it; it does not automatically license every dataset or upstream checkpoint.

### Robot and classical navigation

- [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2) — official Go2/B2/H1 DDS/ROS 2 integration; recommended Ubuntu 22.04/Humble.
- [Unitree SDK2 Go2 Sport client header](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp) — high-level `Move(vx, vy, vyaw)` surface.
- [Nav2 repository and release history](https://github.com/ros-navigation/navigation2) — predominantly C++, current visible Jazzy release 1.3.12 dated 2026-04-29; Apache-2.0 components with package notices.
- [Regulated Pure Pursuit docs](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html) and [paper](https://arxiv.org/abs/2305.20026).
- [MPPI docs](https://docs.nav2.org/configuration/packages/configuring-mppic.html).
- [Smac planner docs](https://docs.nav2.org/configuration/packages/configuring-smac-planner.html) and [implementation README](https://github.com/ros-navigation/navigation2/blob/main/nav2_smac_planner/README.md).
- [Nav2 behavior trees](https://docs.nav2.org/behavior_trees/) and [Following Server](https://docs.nav2.org/configuration/packages/configuring-following-server.html).
- [Nav2 collision monitor](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html) — useful defense-in-depth reference; Parcel's post-shaper safety remains authoritative.
- [RVO2/ORCA](https://github.com/snape/RVO2) — Apache-2.0 C++ implementation.

### Semantic, language and learned navigation

- [VLFM](https://github.com/rai-opensource/vlfm) / [paper](https://arxiv.org/abs/2312.03275) — MIT code; upstream component/data terms separate.
- [InstructNav paper](https://arxiv.org/abs/2406.04882) — Dynamic Chain-of-Navigation and value-map fusion.
- [CityWalker](https://github.com/ai4ce/CityWalker) / [paper](https://arxiv.org/abs/2411.17820) — Apache-2.0 code; Parcel's original v1.0 checkpoint lock is `NOASSERTION`.
- [LeLaN](https://github.com/NHirose/learning-language-navigation) — MIT code; YouTube content is not redistributed by the authors because of copyright.
- [NaVILA](https://github.com/AnjieCheng/NaVILA) / [paper](https://arxiv.org/abs/2412.04453) — Apache-2.0 code; Llama and dataset terms separate.
- [InternNav](https://github.com/InternRobotics/InternNav) / [InternVLA-N1 DualVLN checkpoint](https://huggingface.co/InternRobotics/InternVLA-N1-DualVLN) — MIT code; checkpoint card has missing license metadata; [InternData-N1](https://huggingface.co/datasets/InternRobotics/InternData-N1) is gated CC BY-NC-SA 4.0 despite inconsistent top-level metadata.
- [SocialNav](https://github.com/AMAP-EAI/SocialNav) / [paper](https://arxiv.org/abs/2511.21135) — Apache-2.0 code; linked weight repositories currently contain no weights/model card.
- [LISN](https://social-nav.github.io/LISN-project/) / [code](https://github.com/Social-Nav/tvss_nav) — research fast/slow modulation; no explicit repository license found.
- [GenSafeNav](https://github.com/tasl-lab/GenSafeNav) — MIT code and pretrained crowd policies.
- [Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav) — official repository explicitly says weights will not be released.
- [Robostral Navigate](https://mistral.ai/news/robostral-navigate/) / [paper](https://arxiv.org/abs/2607.20785) — no official downloadable checkpoint located.
- [NavFoM](https://pku-epic.github.io/NavFoM-Web/) / [ICLR 2026 paper](https://openreview.net/forum?id=kkBOIsrCXh) — no official code/checkpoint link located.
- [OmniNav](https://github.com/amap-cvlab/OmniNav) — checkpoints/code exist, but no explicit repository license found.

### Perception, prediction and evaluation

- [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) — Apache-2.0 code.
- [SAM 2](https://github.com/facebookresearch/sam2) — Apache-2.0 code/checkpoints; demo font assets have separate terms.
- [SigLIP 2 in Big Vision](https://github.com/google-research/big_vision) — Apache-2.0 unless explicitly noted.
- [ByteTrack](https://github.com/FoundationVision/ByteTrack) and [FastReID](https://github.com/JDAI-CV/fast-reid) — tracking/re-identification research; FastReID code is Apache-2.0.
- [Trajectron++](https://github.com/StanfordASL/Trajectron-plus-plus) / [paper](https://arxiv.org/abs/2001.03093) — probabilistic heterogeneous-agent prediction.
- [MetaUrban](https://github.com/metadriverse/metaurban) / [paper](https://arxiv.org/abs/2407.08725) — Apache-2.0 code; registered assets and upstream datasets require separate review.
- [HuNavSim 2.0](https://github.com/robotics-upo/hunav_sim) / [paper](https://arxiv.org/abs/2507.17317) — MIT, ROS 2 Humble, simulator-agnostic crowd behaviors.
- [SocNavBench](https://github.com/CMU-TBD/SocNavBench) / [paper](https://arxiv.org/abs/2103.00047) — MIT code; pedestrian dataset terms separate.
- [SocNavGym](https://github.com/gnns4hri/SocNavGym) — GPL-3.0.

## Final recommendation

Parcel's core design is already pointed in the state-of-the-art direction: typed slow reasoning over fast sensor-closed execution. Preserve it. The next meaningful leap will come from repairing semantic search and clearance consistency, adopting a smoother path controller, and adding real open-vocabulary evidence—not from handing motion to a larger LLM.

After that baseline is healthy, run a disciplined proposal tournament. CityWalker is already local but incomplete; InternVLA-N1 is the most capable downloadable research candidate; LeLaN is an excellent last-mile control study; GenSafeNav is the strongest crowd-uncertainty/RL study; MPPI is the most credible classical local-planner challenger. Every one should be forced through the same typed, expiring, sensor-grounded proposal contract and the same final Unitree-safe control path.
