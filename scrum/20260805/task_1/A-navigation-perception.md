# Workstream A — navigation, perception, tracking, and semantic space

## Mission

Produce a closed-loop navigation substrate that can use the same Parcel task
logic in deterministic headless tests, dynamic simulators, sensor replay, and a
physical Go2. The baseline must navigate safely without an LLM. Language and
learned models add semantic goals; they do not become the local controller.

## Boundary with the current repository

Preserve and strengthen these seams:

- `control/base.py::LocomotionController` and `RobotStateSource` remain the
  embodiment boundary;
- `ControlManager` remains the exclusive physical command/stop/fault owner;
- `navigation/base.py::Navigator` becomes a versioned adapter rather than a
  loose `Any` observation bag;
- `DirectiveNavigator`, semantic regions, approach pose sampling, terminal
  verification, and `instructnav.SE2Goal/GoalArbiter` remain product concepts;
- `grid_v1` remains the deterministic in-process reference and CI fallback;
- Nav2 is added as a separate ROS 2 execution backend, not imported into the
  Python 3.14 application process;
- Unitree vendor avoidance is tested as an **exclusive** alternative backend,
  never cascaded invisibly with Nav2 and Parcel collision logic.

## Contract freeze

Use a common envelope for every cross-process observation and proposal:

```text
EvidenceEnvelopeV1 {
  schema_version
  evidence_id
  source
  source_timestamp_ns
  received_monotonic_ns
  sequence
  frame_id
  scene_revision
  expires_monotonic_ns
  calibration_id
  provenance[]
}
```

Do not mix ROS/system/simulator time directly with Python monotonic time.
Adapters must record both the source clock and locally observed monotonic time,
detect clock jumps, and reject an untransformable or expired sample.

```text
OwnerTrackV1 {
  envelope
  enrolled_owner_id
  transient_track_id
  state: confirmed | ambiguous | lost
  pose_xyz_yaw + covariance
  velocity_xyz_yaw + covariance
  identity_score
  visibility_score
  appearance_evidence_refs[]
  last_confirmed_at
}

DynamicTrackV1 {
  envelope
  track_id
  class_id
  pose + velocity + covariance
  predicted_occupancy[]       # timestamped polygons or Gaussians
}

SemanticRegionV1 {
  envelope
  concept_scores{}
  geometry                    # polygon/raster/point cloud, never just a label
  geometry_covariance
  free_space_support
  observation_count
  evidence_refs[]
}

GoalRegionV1 {
  goal_id
  source_task_id / plan_step_id
  frame_id
  acceptable_polygon
  preferred_pose
  approach_constraints
  forbidden_regions[]
  relation: inside | near | behind | orbit | hold | visible
  hold_duration
  confidence
  issued_at / expires_at
  evidence_refs[]
}
```

The scorer and task verifier consume the same `GoalRegion`; the agent never
receives the scorer's privileged world-state predicate.

## Geometric navigation baseline

### ROS 2 graph

```text
Unitree camera/LiDAR + SportModeState
  -> calibration/time adapters
  -> odometry/localization -------------> map -> odom -> base_link -> sensors
  -> elevation/occupancy mapping -------> global/local costmaps
  -> person/dynamic tracks -------------> predictive/social layer
  -> semantic regions ------------------> keepouts/preferred routes/goals

GoalRegion/OwnerTrack
  -> Parcel ROS Action adapter
  -> Nav2 BT Navigator / Following Server
  -> global planner + smoother
  -> MPPI local controller
  -> velocity smoother
  -> Collision Monitor
  -> Parcel command lease/ControlManager adapter
  -> Unitree Sport Move/StopMove
```

Exactly one component owns each TF edge and command topic. In particular,
there must be only one `map->odom`, one `odom->base_link`, and one final body
command writer in a run manifest.

### Initial navigation configuration

- Use Nav2 MPPI as the primary controller candidate. It supports differential,
  omnidirectional, and Ackermann motion models and reports 100+ Hz on a modest
  CPU in its official documentation. Start with a forward-preferred
  differential model for destination travel, then A/B an omni profile that
  gives lateral motion a material cost rather than forbidding it.
- Use a rotation shim or a bounded orient phase when the route heading error is
  large. Do not stop-and-turn at every path sample; transition continuously and
  measure hesitation, curvature, side-slip ratio, and jerk.
- Keep `vy` available for manual commands, owner formation, narrow recovery,
  and locally justified avoidance. Report lateral distance divided by total
  distance so a controller cannot silently become a sideways slider.
- Use global and local keepout filters for roads/restricted areas, and speed
  filters with lookahead for curbs, doorways, crowds, and crossing approaches.
- Pin the ROS 2/Nav2 distribution in the spike manifest. The current Nav2
  Following Server is not assumed to be packaged in Parcel's target Humble
  environment; if absent, evaluate the separately maintained
  [`opennav_following`](https://index.ros.org/p/opennav_following/) package or
  keep Parcel's follower behind the same ROS Action contract.
- Put Collision Monitor after velocity smoothing and before the final command
  handoff. Its own documentation says it is not hard-real-time or certified;
  it is an independent software defense, not the hardware safety case.
- Maintain Unitree's onboard protections and Sport closed-loop gait/balance.

Primary references: [Nav2 MPPI](https://docs.nav2.org/configuration/packages/configuring-mppic.html),
[dynamic following](https://docs.nav2.org/tutorials/docs/navigation2_dynamic_point_following.html),
[Collision Monitor](https://docs.nav2.org/tutorials/docs/using_collision_monitor.html),
[keepout](https://docs.nav2.org/configuration/packages/costmap-plugins/keepout_filter.html),
and [speed filter](https://docs.nav2.org/tutorials/docs/navigation2_with_speed_filter.html).

### Localization and terrain study

Run candidates on identical bags; do not select by paper headline:

| Candidate | Role | Advantage | Limitation / gate |
| --- | --- | --- | --- |
| [KISS-ICP](https://github.com/PRBonn/kiss-icp) | LiDAR odometry baseline | small, permissive, simple | no loop closure; measure drift and recovery |
| [Unitree Point-LIO](https://github.com/unitreerobotics/point_lio_unilidar) | sensor-matched LIO baseline | direct Unitree reference | GPL-2.0 and older ROS path; legal/architecture review |
| [RTAB-Map](https://github.com/introlab/rtabmap_ros) | persistent graph map/relocalization | camera/LiDAR and loop closure | more compute/tuning; establish TF ownership first |
| [slam_toolbox](https://github.com/SteveMacenski/slam_toolbox) | 2-D mapped indoor baseline | mature Nav2 path | flat-world limitation |
| [Elevation Mapping CuPy](https://github.com/leggedrobotics/elevation_mapping_cupy) | legged 2.5-D traversability | GPU, semantic layers, quadruped lineage | target GPU/VRAM and ROS version spike |
| [nvblox](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox) | 3-D reconstruction/Nav2 costmap | depth camera or 3-D LiDAR; dynamic modes | NVIDIA dependency and target-device budget |

Score translational/yaw drift, loop-closure correction, relocalization success,
pose jumps, map artifacts, low/overhanging obstacle recall, CPU/GPU/VRAM,
sensor-to-pose latency, and downstream route success. A localization reset is
a task event: slow/stop, invalidate goals in the old epoch, relocalize, then
re-ground and replan.

The [CMU Go2 autonomy stack](https://github.com/jizhang-cmu/autonomy_stack_go2)
is the best immediate whole-stack reference on the stock Go2, but its authors
document L1 noise, weak detection below roughly 0.3 m, occasional SLAM drift,
and unsynchronized camera timestamps. Use it as a frozen comparison and source
of commissioning lessons, not as proof that those limitations are solved.

## Perception planes

Separate the safety/geometric plane from the semantic plane:

```text
safety plane:  LiDAR + pose -> terrain/occupancy -> dynamic prediction -> veto
semantic plane: RGB -> region/object/text evidence -> semantic memory -> goal
```

Semantic inference may be slow, absent, or wrong without delaying the safety
plane. All GPU queues are bounded latest-frame queues. A result computed on an
old frame is either transformed into the current frame with a valid pose buffer
or discarded.

### Road, sidewalk, curb, and traversability

`road` and `sidewalk` are dense regions, not object boxes. Build a compact
closed-set segmenter trained/evaluated on dog-height urban video for the
safety-relevant classes. [Cityscapes](https://www.cityscapes-dataset.com/dataset-overview/)
provides standard road/sidewalk labels, but its vehicle-height European imagery
is not sufficient validation for the Go2 camera domain.

Fuse the mask into LiDAR/elevation geometry and retain uncertainty near
boundaries. A candidate sidewalk goal needs:

1. multi-frame semantic support;
2. a polygon in a valid map frame;
3. free/traversable surface support;
4. a collision-free approach pose;
5. a route that does not enter a road keepout except through an explicit
   crossing task;
6. terminal re-observation and stopped-body confirmation.

[CAT-Seg](https://github.com/cvlab-kaist/CAT-Seg) or another open-vocabulary segmenter is a useful offline challenger,
but a large open-vocabulary model is not the safety authority.

### Objects, places, shops, and brands

Use a cascade, not one universal prompt:

1. query-driven open-vocabulary detector for `lamppost`, `bench`, `entrance`,
   `storefront`, and long-tail landmarks;
2. SAM 2 mask propagation for temporal support and more precise geometry;
3. camera/LiDAR association for metric position and covariance;
4. OCR for storefront/sign text;
5. optional logo/image retrieval and known-map/place memory;
6. multi-view evidence fusion and an explicit ambiguous/absent outcome.

Benchmark [OmDet-Turbo](https://github.com/om-ai-lab/OmDet) and the original
local [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO),
[SAM 2](https://github.com/facebookresearch/sam2), and
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR). Grounding DINO 1.5's
public repository is an authenticated API client rather than an open local
checkpoint, so it is not the offline production default.

`wait by the lamppost` resolves to a free stand-off region on the sidewalk,
not the pole centroid. `go to the Nike store` requires text/logo/place evidence
plus an entrance/sidewalk approach region; if the sign is unreadable or there
are multiple candidates, inspect or ask rather than guessing.

### Semantic memory and active inspection

Extend the current region/instance memory with:

- evidence references and source-model versions;
- map pose covariance and scene revision;
- visibility/occlusion state, observation count, decay, and invalidation;
- contradiction handling rather than last-write-wins;
- place/room/route edges;
- query latency and whether the result was cached, observed, or inferred.

Parcel should own the minimal contract first. Spike
[Hydra](https://github.com/MIT-SPARK/Hydra),
[ConceptGraphs](https://github.com/concept-graphs/concept-graphs), DualMap, or
OVO as sidecars only after license/dependency review.

Active perception is a real skill:

```text
InspectScene(query, budget)
  -> stop or acquire a safe checkpoint
  -> bounded body-yaw viewpoints
  -> publish fresh evidence
  -> re-ground
  -> success / ambiguous / bounded-not-found
```

Because the Go2 has no neck, a physical scan acquires `base + attention`; it
cannot be treated as a decorative gaze overlay while walking.

## Correct-owner tracking

Use four distinct components:

1. a fast person detector;
2. ByteTrack (or measured challenger) for short-term association;
3. an enrollment/ReID gallery for persistent owner identity;
4. LiDAR association and a filter for metric pose, velocity, covariance, and
   predicted owner path.

SAM 2 may propagate an owner mask between detector frames, but it is not an
identity model. ReID refreshes candidates on keyframes and after ambiguity.
The policy is fail-closed:

```text
confirmed: identity and geometry fresh -> follow
ambiguous: slow/hold, widen evidence, never switch person
lost: stop or go to last safe observation, bounded scan/frontier search
reacquired: require identity + temporal confirmation, then replan
failed: hold and report; do not attach to nearest person
```

Evaluate [ByteTrack](https://github.com/FoundationVision/ByteTrack) and
[FastReID](https://github.com/JDAI-CV/fast-reid) on an owner-specific,
dog-height dataset with similar-looking distractors, crossings, full occlusion,
clothing changes, glare, motion blur, re-entry, and partial crops.

## Dynamic and social planning

Start with deterministic tracking and uncertainty-aware constant-velocity or
IMM prediction. Raster time-indexed swept occupancy and asymmetric personal
space into the local costmap. The predictor creates soft route costs; current
LiDAR geometry and the collision monitor retain stop authority.

Initial social rules are explicit and auditable:

- do not cut between a group unless no safe alternative exists;
- slow before blind corners, doorways, and storefront exits;
- yield rather than oscillate in a bottleneck;
- maintain a larger forward than rear personal-space lobe;
- never infer that a human will reciprocate simply because simulated ORCA
  agents do;
- expose passing-side policy by locale instead of burying it in model weights.

Use [nav2_social_costmap_plugin](https://github.com/robotics-upo/nav2_social_costmap_plugin)
as a heuristic baseline, [HuNavSim](https://github.com/robotics-upo/hunav_sim)
for configurable ROS 2 crowd scenarios, and
[SocNavBench](https://github.com/CMU-TBD/SocNavBench) for external social
evaluation. A learned trajectory predictor is shadow-only until it beats the
deterministic predictor on calibration, collision recall, latency, and closed-
loop outcomes with a product-compatible license.

## Learned navigation lane

Every learned adapter emits the existing bounded shape:

```text
SE2Goal {
  source, pose | waypoints, frame, confidence,
  issued_at, ttl, plan_step_id, priority
}
```

Add maximum distance/yaw, route-frame transform, freshness, lethal-cost,
line-of-sight/observability, and uncertainty checks before publication. The
adapter never gets `cmd_vel` or Unitree DDS credentials.

Order of experiments:

1. [NoMaD/ViNT/GNM](https://github.com/robodhruv/visualnav-transformer) for
   visual goal/exploration waypoint proposals;
2. [LeLaN](https://github.com/NHirose/learning-language-navigation) for
   language-conditioned visible-goal proposals;
3. [VLFM](https://arxiv.org/abs/2312.03275) as a frontier-value-map pattern;
4. [NaVILA](https://navila-bot.github.io/) as the most relevant legged VLA
   architecture, only after the exact checkpoint, license, memory, and adapter
   are independently verified;
5. research-only systems without released weights or clear licenses remain
   architectural references, not backlog promises.

Promotion order is recorded replay -> simulator shadow -> simulator active at
low speed -> hardware shadow -> fenced hardware active. No phase is skipped.

## Cards and acceptance tests

| Card | Code/result | Required tests |
| --- | --- | --- |
| A0 | frozen V1 DTOs and serialization/validation | malformed, NaN, expired, wrong frame, clock jump, schema mismatch |
| A1 | ROS 2 action/service bridge and one-writer manifest | goal/feedback/result/cancel, process death, duplicate writer/TF rejection |
| A2 | bag replay and calibration/time checker | deterministic digest, drift, missing calibration, timestamp skew/drop |
| A3 | KISS-ICP/LIO study and TF choice | paired bag drift, relocalization, CPU/latency, pose-jump fail-stop |
| A4 | costmap/elevation and low-obstacle suite | curb, cable, stair, glass/reflective, overhang, slope, negative obstacle |
| A5 | Nav2 MPPI + filters + collision chain | orientation, lateral ratio, jerk, keepout, speed lookahead, stale scan, cancel |
| A6 | owner detector/ReID/3-D track | ID switch, false follow, ambiguity, occlusion, covariance calibration |
| A7 | FollowObject versus Parcel follower | band error, visibility, jerk, lost/reacquire, dynamic obstacle and stop |
| A8 | sidewalk/road/curb segmentation | class IoU, boundary error, false-safe region, lighting/weather/domain shift |
| A9 | object/mask/OCR semantic cascade | long-tail recall, duplicate/absent target, named-store precision, pose error |
| A10 | dynamic prediction/social costs | collision recall, TTC, intrusion, freezes, deadlock, passing, p99 deadline |
| A11 | GoalRegion and active inspection | inside/near/behind/orbit predicates, moved/stale target, bounded not-found |
| A12 | learned proposer harness | TTL/range/lethal checks, replay determinism, paired A/B, no direct control access |

## License and deployment cautions

Audit code, checkpoints, training data, and transitive dependencies separately.
Known traps include GPL/AGPL detector repositories, non-commercial CoTracker
assets, and non-commercial larger Depth Anything V2 checkpoints. Unitree
Point-LIO's GPL-2.0 and the CMU stack's unclear aggregate license require an
explicit product decision. TensorRT/ONNX optimization begins only after an
accuracy baseline is frozen; an optimized model is a new candidate with a new
artifact hash and evaluation row.
