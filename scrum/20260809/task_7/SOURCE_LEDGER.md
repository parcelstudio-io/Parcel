# Primary-source evidence ledger

**Checked:** 2026-08-09  
**Policy:** official documentation, author repositories, and original papers only.
Search snippets, blogs, videos, benchmark rank claims, and third-party summaries are not
decision evidence. “Released” distinguishes code, weights, datasets, and deployment
artifacts; these frequently have different licenses.

This ledger records research selection, not a dependency lockfile. Every adopted source
must later be pinned to a commit/release and re-audited for transitive licenses and
security.

## A. Unitree and primary locomotion stack

### A1. Unitree RL Lab

- **Source:** [unitreerobotics/unitree_rl_lab](https://github.com/unitreerobotics/unitree_rl_lab)
- **Observed:** official Unitree Isaac Lab project; Go2/H1/G1 support; Train/Play and a
  documented Unitree MuJoCo sim-to-sim then sim-to-real workflow; Apache-2.0 code.
- **Use:** primary upstream Go2 baseline and deployment-contract reference.
- **Limit:** verify pinned Go2 rough task, export and deployment path directly. Public
  deployment instructions/examples are G1-heavy; “supports Go2” is not proof that every
  deploy stage is complete.

### A2. Official Go2 environment configuration

- **Source:** [Go2 velocity environment config](https://github.com/unitreerobotics/unitree_rl_lab/blob/main/source/unitree_rl_lab/unitree_rl_lab/tasks/locomotion/robots/go2/velocity_env_cfg.py)
- **Observed:** Go2 robot and rough-terrain parameters are available; terrain-family
  configuration includes slope/box/stair concepts, with some rows commented/config-
  dependent in the current source.
- **Use:** reproduce exactly at a pinned commit before enabling Parcel changes.
- **Limit:** a configured terrain range is a training input, not a validated physical
  capability envelope.

### A3. Unitree MuJoCo

- **Source:** [unitreerobotics/unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco)
- **Observed:** official Go2-capable MuJoCo simulator, SDK2/DDS-shaped interfaces,
  C++/Python, low-level control and a terrain generator with stairs, rough surfaces and
  heightmaps; BSD-3-Clause at review time.
- **Use:** independent articulated sim-to-sim and API-schema gate.
- **Limit:** repository documents low-level control; it does not emulate the proprietary
  onboard Sport-controller dynamics. Do not infer Sport capability from it.

### A4. Unitree SportClient

- **Source:** [Go2 SportClient header](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp)
- **Observed:** official high-level closed-loop operations include body `Move(vx, vy,
  vyaw)`, stop, balance/recovery/gait and related services.
- **Use:** retain as the first hardware locomotion backend.
- **Limit:** API availability is not a guarantee of camera/LiDAR navigation or an
  unmeasured stair/slope envelope; robot edition/service support must be commissioned.

### A5. Unitree Point-LIO adapter

- **Source:** [unitreerobotics/point_lio_unilidar](https://github.com/unitreerobotics/point_lio_unilidar)
- **Observed:** official adaptation of Point-LIO to Unitree L1/L2 LiDAR for LiDAR/IMU
  odometry/mapping; GPL-2.0 and ROS 1/Noetic-oriented.
- **Use:** sensor/hardware integration reference and accuracy comparator.
- **Limit:** GPL/product and ROS-version implications; not selected as the core contract.

## B. Isaac training, sensors, and randomization

### B1. Isaac Lab environments

- **Source:** [Isaac Lab available environments](https://isaac-sim.github.io/IsaacLab/develop/source/overview/environments.html)
- **Observed:** an `Isaac-Velocity-Rough-Unitree-Go2` family is supplied with supported
  RL workflows.
- **Use:** primary vectorized articulated locomotion environment.
- **Limit:** pin the exact released task ID/config; development documentation can move.

### B2. Terrain generator

- **Source:** [Isaac Lab terrain API](https://isaac-sim.github.io/IsaacLab/develop/source/api/lab/isaaclab.terrains.html)
- **Observed:** procedural height/mesh slopes, ascending/inverted stairs, objects,
  stepping stones, gaps/holes and difficulty curricula.
- **Use:** training and held-out terrain-family generation.
- **Limit:** hold out generator and mesh families, not just seeds; procedural terrains
  do not cover deformable/loose material reality.

### B3. Sensors

- **Sources:** [Isaac Lab sensor API](https://isaac-sim.github.io/IsaacLab/develop/source/api/lab/isaaclab.sensors.html),
  [ray-caster concepts](https://isaac-sim.github.io/IsaacLab/main/source/overview/core-concepts/sensors/ray_caster.html),
  [Isaac Sim RTX sensor API](https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.sensors.experimental.rtx/docs/index.html)
- **Observed:** camera, contact, IMU, ray-cast and RTX LiDAR/camera sensor families.
  Fast ray casting has static-mesh limitations; RTX paths trade throughput for richer
  sensor behavior and are partly marked experimental.
- **Use:** fast privileged/teacher batches plus smaller sensor-faithful student/release
  batches.
- **Limit:** version experimental APIs; static ray casts are not valid dynamic-person
  observations.

### B4. Domain randomization and multi-GPU

- **Sources:** [Isaac Sim domain randomization](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.replicator.domain_randomization/docs/index.html),
  [Isaac Lab multi-GPU training](https://isaac-sim.github.io/IsaacLab/develop/source/features/multi_gpu.html),
  [cross-backend policy transfer guidance](https://isaac-sim.github.io/IsaacLab/develop/source/how-to/transfer_policies_between_physx_and_newton.html)
- **Observed:** physics/visual randomization and distributed RL are supported; transfer
  guidance emphasizes dynamics/observation differences.
- **Use:** versioned physics/sensor distributions and cross-engine discipline.
- **Limit:** this host has one GPU; distributed claims are irrelevant initially.
  Randomization is not a substitute for system identification.

### B5. RSL-RL

- **Source:** [leggedrobotics/rsl_rl](https://github.com/leggedrobotics/rsl_rl)
- **Observed:** permissive GPU PPO framework, student/teacher/distillation patterns,
  integrations with Isaac Lab and other simulators.
- **Use:** default locomotion optimizer after upstream reproduction.
- **Limit:** framework availability does not supply a ready perceptive Go2 checkpoint.

## C. State estimation, mapping, and perception

### C1. GLIM

- **Source:** [koide3/glim](https://github.com/koide3/glim)
- **Observed:** MIT-licensed ROS 2 factor-graph LiDAR/range-inertial localization and
  mapping, GPU acceleration, multiple LiDAR forms and RGB-D support; current releases
  and Ubuntu/Jetson documentation exist.
- **Use:** lead 6-DoF state-estimation benchmark.
- **Limit:** reproduce latency/covariance/failure behavior on Go2 motion and the exact
  sensor configuration; current release recency increases integration risk.

### C2. FAST-LIO2

- **Source:** [hku-mars/FAST_LIO](https://github.com/hku-mars/FAST_LIO)
- **Observed:** tightly coupled LiDAR-inertial odometry with high-rate claims; GPL-2.0,
  ROS-oriented, and calibration/time synchronization sensitive.
- **Use:** research comparator.
- **Limit:** GPL/product implications and older ROS integration make it an unsuitable
  default shipped dependency without legal/architecture review.

### C3. Elevation Mapping CuPy

- **Sources:** [leggedrobotics/elevation_mapping_cupy](https://github.com/leggedrobotics/elevation_mapping_cupy),
  [releases](https://github.com/leggedrobotics/elevation_mapping_cupy/releases),
  [ROS-neutral core extraction](https://github.com/leggedrobotics/elevation_mapping_cupy_core)
- **Observed:** MIT, GPU probabilistic multimodal elevation maps, ray visibility cleanup,
  height-drift compensation, traversability filters and semantic/RGB layers. Current
  releases add ROS 2 Jazzy work and performance/correctness fixes.
- **Use:** lead rolling terrain-map implementation/reference.
- **Limit:** replay and audit the current ROS 2/core paths; the extracted core is young.
  Traversability output is uncertain evidence, not collision truth.

### C4. Isaac ROS nvblox

- **Sources:** [NVIDIA-ISAAC-ROS/isaac_ros_nvblox](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox),
  [official documentation](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/index.html)
- **Observed:** Apache-2.0 GPU 3-D reconstruction and Nav2 costmap from depth and/or
  3-D LiDAR; people and general dynamic reconstruction modes.
- **Use:** complementary local volume/ESDF and overhang/body-clearance candidate.
- **Limit:** requires accurate pose; it is not a terrain-capability planner or dynamic
  multi-object tracker. Official platform/container matrix must be respected.

### C5. Wavemap

- **Source:** [ethz-asl/wavemap](https://github.com/ethz-asl/wavemap)
- **Observed:** BSD-3-Clause multiresolution, multi-sensor 3-D occupancy mapping.
- **Use:** CPU/portable volume-map challenger.
- **Limit:** public ROS integration/version needs an adapter and profiling.

### C6. RTAB-Map ROS

- **Source:** [introlab/rtabmap_ros](https://github.com/introlab/rtabmap_ros)
- **Observed:** permissive ROS 2 visual/RGB-D/LiDAR SLAM integration and Nav2 ecosystem.
- **Use:** integration and loop-closure comparator, especially indoors.
- **Limit:** a general SLAM toolkit rather than a legged-terrain map or guaranteed
  camera–LiDAR calibration solution.

## D. Route/local planning and safety

### D1. Nav2 MPPI

- **Source:** [official MPPI documentation](https://docs.nav2.org/configuration/packages/configuring-mppic.html)
- **Observed:** sampling-based predictive control, differential/omni/Ackermann models,
  actuator delay, trajectory validator, full-footprint options, plugin critics and
  forward-preference/path-angle behavior; official documentation reports 100+ Hz on a
  modest CPU for its reference setup.
- **Use:** flat/local-surface baseline and algorithmic seed for Parcel terrain MPPI.
- **Limit:** SE(2) body models and 2-D costmaps do not solve foot placement, support,
  negative obstacles, or stairs.

### D2. Nav2 Collision Monitor

- **Source:** [official Collision Monitor documentation](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html)
- **Observed:** raw laser/point-cloud/range sources, stop/slow/limit/TTC approach modes,
  velocity-dependent polygons and source timeouts, downstream of normal navigation.
- **Use:** final raw-sensor safety pattern and mutation cases.
- **Limit:** official docs explicitly disclaim hard real-time/safety certification.

### D3. ArtPlanner

- **Source:** [leggedrobotics/art_planner](https://github.com/leggedrobotics/art_planner)
- **Observed:** BSD-3-Clause 2.5-D PRM/local planning with learned ANYmal motion cost;
  consumes elevation maps and recommends Elevation Mapping CuPy.
- **Use:** transferable geometric/capability-aware planner reference.
- **Limit:** ANYmal weights, old ROS/ODE dependencies, gated retraining/simulator context,
  and unsupported path follower prevent direct Go2 adoption.

### D4. SCAN-Planner

- **Source:** [wuyi2121/SCAN-Planner](https://github.com/wuyi2121/SCAN-Planner)
- **Observed:** Apache-2.0 author release of a spatial collision-aware quadruped planner
  using LiDAR or depth, reference paths and multi-floor keypoints; code/release is very
  recent.
- **Use:** shadow challenger after audit.
- **Limit:** primarily Ubuntu 20.04/ROS Noetic and limited independent reproduction;
  recheck the pinned commit and transitive dependencies before adoption.

### D5. Wild Visual Navigation

- **Source:** [leggedrobotics/wild_visual_navigation](https://github.com/leggedrobotics/wild_visual_navigation)
- **Observed:** MIT self-supervised visual traversability learned online, integrated
  with elevation mapping and demonstrated on legged/wheeled robots.
- **Use:** optional uncertain traversability cost/challenger.
- **Limit:** ROS 1 and research embodiment; never hard collision truth.

### D6. ViPlanner

- **Source:** [leggedrobotics/viplanner](https://github.com/leggedrobotics/viplanner)
- **Observed:** semantic/depth local navigation, simulator training and released model
  material.
- **Use:** design/reference evaluation only.
- **Limit:** repository rights statement is restrictive; legacy ROS/ANYmal assumptions.
  Do not put it on a commercial dependency path without permission.

## E. Perceptive locomotion and safety research

### E1. Learning robust perceptive locomotion

- **Source:** [ETH project page and paper](https://leggedrobotics.github.io/rl-perceptiveloco/)
- **Observed:** privileged teacher/student pattern with elevation/proprioceptive fusion
  and reported stairs/rough-terrain traversal.
- **Use:** central teacher/noisy-student architecture reference.
- **Limit:** research evidence on other embodiments; not a Go2 artifact or safety proof.

### E2. Blind locomotion

- **Source:** [ETH blind locomotion project](https://leggedrobotics.github.io/rl-blindloco/)
- **Observed:** robust proprioceptive locomotion under terrain/disturbance variability.
- **Use:** rationale for balance/stand/recovery fallback during exteroceptive outages.
- **Limit:** blind balance does not authorize blind navigation near cliffs/obstacles.

### E3. Robot Parkour Learning

- **Sources:** [ZiwenZhuang/parkour](https://github.com/ZiwenZhuang/parkour),
  [Go2 deployment guide](https://github.com/ZiwenZhuang/parkour/blob/main/onboard_codes/Deploy-Go2.md)
- **Observed:** MIT training/deployment code and Go1 checkpoints; depth/proprioceptive
  parkour; Go2 guide expects a user-trained distilled log and low-level setup.
- **Use:** best permissive training-design seed beyond the official rough baseline.
- **Limit:** no ready verified Go2 checkpoint; disabling Sport and low-level control
  materially changes risk.

### E4. Extreme Parkour

- **Sources:** [chengxuxin/extreme-parkour](https://github.com/chengxuxin/extreme-parkour),
  [original paper](https://arxiv.org/abs/2309.14341)
- **Observed:** full camera-distillation/parkour training pipeline and author-reported
  extreme terrain results.
- **Use:** curriculum, depth perception and teacher/student research reference.
- **Limit:** non-commercial licensing/legacy Isaac Gym stack; not a default product
  dependency or ready Go2 controller.

### E5. Agile But Safe

- **Source:** [LeCAR-Lab/ABS](https://github.com/LeCAR-Lab/ABS)
- **Observed:** agile/recovery policy switching guided by a learned reach-avoid value
  function.
- **Use:** safety-supervisor/recovery research inspiration.
- **Limit:** non-commercial and Go1/specific sensor-compute assumptions; learned value
  cannot replace Parcel's deterministic final safety.

### E6. DreamWaQ++

- **Source:** [official project page](https://dreamwaqpp.github.io/)
- **Observed:** paper/project reports point-cloud and proprioceptive fusion, sensor-
  failure resilience, stairs/slopes and a multi-rate controller architecture.
- **Use:** architecture/rate/reference only.
- **Limit:** no official code or weights found during this audit; do not cite it as an
  available model.

### E7. Walk These Ways

- **Source:** [Improbable-AI/walk-these-ways](https://github.com/Improbable-AI/walk-these-ways)
- **Observed:** released pretrained locomotion policies and sim-to-real pipeline.
- **Use:** deployment/reproducibility reference.
- **Limit:** Go1 EDU and legacy Isaac Gym, not a perceptive Go2 terrain policy.

### E8. Barkour

- **Sources:** [google-deepmind/barkour_robot](https://github.com/google-deepmind/barkour_robot),
  [Barkour paper](https://arxiv.org/abs/2305.14654)
- **Observed:** open robot/software and links to MuJoCo model, obstacle-course simulation
  and scoring; software Apache-2.0, non-software materials may be CC BY-NC.
- **Use:** adapted external agility course and metric taxonomy.
- **Limit:** different embodiment; report adapted Go2 results, not official benchmark
  parity. Audit each asset's license.

### E9. RoboGauge

- **Sources:** [project page](https://robogauge.github.io/),
  [repository](https://github.com/robogauge/code/tree/main/RoboGauge)
- **Observed:** newly released MuJoCo Go2 benchmark with progressive terrain families
  and metrics.
- **Use:** experimental external challenger.
- **Limit:** very new/immature and limited provenance at review time; audit evaluator
  sensitivity and license before making it a release gate.

## F. Simulation and environment diversity

### F1. MuJoCo and MJX

- **Sources:** [google-deepmind/mujoco](https://github.com/google-deepmind/mujoco),
  [MJX documentation](https://mujoco.readthedocs.io/en/latest/mjx.html),
  [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground),
  [MuJoCo Menagerie Go2](https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_go2)
- **Observed:** open articulated contact simulator, GPU/TPU batch path through MJX, a
  growing sim-to-real training suite, and public Go2 assets.
- **Use:** deterministic/cross-physics tests and possible later training challenger.
- **Limit:** rendering/sensors/world diversity require authoring; current Parcel harness
  is kinematic despite using MuJoCo.

### F2. Gazebo Harmonic

- **Sources:** [Gazebo sensor documentation](https://gazebosim.org/docs/harmonic/sensors/),
  [headless/server documentation](https://gazebosim.org/docs/harmonic/getstarted/),
  [actor documentation](https://gazebosim.org/docs/garden/actors/)
- **Observed:** ROS-friendly camera/depth/segmentation/IMU/contact/GPU-LiDAR, sensor
  noise and server-only operation. Scripted actors are visual/kinematic rather than
  gravity/contact bodies.
- **Use:** ROS 2 timing/TF/QoS/noise and later HIL validation.
- **Limit:** not the high-throughput RL engine; physics-enabled people are needed for
  contact tests.

### F3. MetaUrban

- **Sources:** [metadriverse/metaurban](https://github.com/metadriverse/metaurban),
  [official observations](https://metaurban-simulator.readthedocs.io/en/latest/observation.html),
  [dynamic environments](https://metaurban-simulator.readthedocs.io/en/latest/rl_environments.html)
- **Observed:** Apache-2.0 procedural urban worlds, pedestrians/vehicles, urban objects,
  rigid-body and social-navigation tasks, RGB/depth/semantic/LiDAR observations and
  pretrained PPO examples.
- **Use:** dynamic city, semantic, sidewalk/curb and social stress sidecar.
- **Limit:** embodiment/contact fidelity is not the authority for Go2 joints; full asset
  access has separate requirements.

### F4. URBAN-SIM

- **Sources:** [metadriverse/urban-sim](https://github.com/metadriverse/urban-sim),
  [CVPR 2025 paper](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_Towards_Autonomous_Micromobility_through_Scalable_Urban_Simulation_CVPR_2025_paper.html)
- **Observed:** Isaac/PhysX urban simulation research with explicit Go2 locomotion/
  navigation/traverse material.
- **Use:** promising secondary urban-Go2 evaluation/training challenger.
- **Limit:** public repository marks several urban locomotion, long-horizon navigation,
  reactive-agent and checkpoint items TODO. Not a critical path today.

### F5. Habitat

- **Sources:** [facebookresearch/habitat-sim](https://github.com/facebookresearch/habitat-sim),
  [facebookresearch/habitat-lab](https://github.com/facebookresearch/habitat-lab),
  [Habitat 3](https://aihabitat.org/habitat3/)
- **Observed:** high-throughput RGB-D/semantic indoor simulation, Bullet articulation,
  URDF assets, established PointNav/ObjectNav/VLN/social tasks.
- **Use:** frozen indoor semantic/instruction/follow evaluation distribution.
- **Limit:** official repos state no active Meta development beyond v0.3.4; most
  benchmark assumptions are not quadruped contact qualification.

### F6. iGibson and OmniGibson

- **Sources:** [StanfordVL/iGibson](https://github.com/StanfordVL/iGibson),
  [StanfordVL/BEHAVIOR-1K / OmniGibson](https://github.com/StanfordVL/BEHAVIOR-1K)
- **Observed:** interactive indoor assets, RGB/LiDAR/semantic sensing and domain
  randomization; OmniGibson is the Isaac-based successor focused on household behavior.
- **Use:** indoor semantic/interactivity test distribution.
- **Limit:** iGibson is older; neither is the first-line Go2 terrain-controller trainer.

### F7. RaiSim and legacy legged_gym

- **Sources:** [RaiSim license](https://raisim.com/sections/License.html),
  [leggedrobotics/legged_gym](https://github.com/leggedrobotics/legged_gym)
- **Observed:** RaiSim is fast but proprietary/licensed; ETH directs new legged_gym work
  toward Isaac Lab and gives the legacy project limited support.
- **Use:** none for new critical dependencies.
- **Limit:** licensing/ecosystem and migration status respectively.

## G. Navigation foundation models and semantic planners

### G1. InternNav / InternVLA-N1

- **Source:** [InternRobotics/InternNav](https://github.com/InternRobotics/InternNav)
- **Observed:** MIT code, Habitat/Isaac integration, datasets/model zoo/training, single-
  and dual-system VLN, continuous trajectory models, current releases and community Go2
  deployment guidance; weights/data carry their own licenses.
- **Use:** best later open high-level goal/corridor proposer and evaluation toolbox.
- **Limit:** reproduce author-reported numbers; it does not replace terrain mapping,
  collision safety or low-level Go2 control.

### G2. Qwen-RobotNav

- **Source:** [QwenLM/Qwen-RobotNav](https://github.com/QwenLM/Qwen-RobotNav)
- **Observed:** dual-system navigation architecture and short `(x,y,theta)` waypoint
  outputs across multiple navigation tasks, with reported Go2 deployment.
- **Use:** architecture reference.
- **Limit:** official repository states weights are not planned for release; not an open-
  weight adoption candidate.

### G3. NavDP

- **Source:** [InternRobotics/NavDP](https://github.com/InternRobotics/NavDP)
- **Observed:** RGB-D diffusion navigation policy and Isaac evaluation material.
- **Use:** short-trajectory shadow challenger.
- **Limit:** checkpoint access and non-commercial/share-alike licensing need careful
  review; not collision or locomotion authority.

### G4. NaVILA

- **Source:** [AnjieCheng/NaVILA](https://github.com/AnjieCheng/NaVILA)
- **Observed:** Apache-2.0 repository, released large checkpoint/evaluation path and
  language-navigation research.
- **Use:** high-level instruction/waypoint challenger.
- **Limit:** legacy Habitat/hotfix dependencies and no turnkey Go2 terrain controller.

### G5. CityWalker

- **Source:** [ai4ce/CityWalker](https://github.com/ai4ce/CityWalker)
- **Observed:** Apache-2.0 urban visual-navigation training/fine-tuning code and released
  pretrained model.
- **Use:** urban route/waypoint prior benchmark.
- **Limit:** not a 3-D terrain map, collision shield, or contact locomotion policy.

### G6. OneMap

- **Source:** [KTH-RPL/OneMap](https://github.com/KTH-RPL/OneMap)
- **Observed:** open-vocabulary feature mapping and real-time-oriented semantic map work.
- **Use:** Task 4 semantic-layer/reference integration.
- **Limit:** semantics do not establish metric terrain support or locomotion capability.

## H. External navigation metrics retained

### H1. BARN

- **Sources:** [BARN project](https://www.cs.utexas.edu/~xiao/BARN/BARN.html),
  [challenge repository](https://github.com/Daffan/the-barn-challenge)
- **Observed:** obstacle navigation benchmark and difficulty/time-weighted scoring in
  planar Jackal/Gazebo settings.
- **Use:** flat clutter and local-planner regression only.
- **Limit:** embodiment, kinematics, sensors and official runtime differ from Parcel's
  native adapter; not stairs/hills or quadruped agility evidence.

### H2. Habitat navigation metrics

- **Source:** [Habitat challenge](https://aihabitat.org/challenge/2021/)
- **Observed:** success, SPL and related navigation benchmark conventions.
- **Use:** semantic/indoor task metrics.
- **Limit:** navmesh/task success does not qualify contact-rich legged traversal.

## I. Workstation evidence

Read-only local checks on 2026-08-09 reported:

```text
Ubuntu 26.04; Linux 7.0.0-28
NVIDIA RTX 5000 Ada Generation; 32,760 MiB; driver 595.84; compute 8.9
AMD Threadripper PRO 7995WX; 96 cores / 192 threads
~246 GiB RAM; ~2.9 TB free disk
Python 3.14.4
no nvcc, Isaac Lab executable, or uv found on PATH
```

**Ruling:** capable single-GPU research workstation, but use an upstream-supported,
pinned Ubuntu 24.04/ROS 2 Jazzy container or isolated Isaac environment. Do not mutate
system Python. Record container/source/model/config hashes for every result.

## J. Final adoption matrix

| component | lead | challenger/reference | decision now |
|---|---|---|---|
| locomotion training | Isaac Lab + Unitree RL Lab + RSL-RL | MJX/MuJoCo Playground | reproduce lead first |
| flat/mild physical control | Unitree Sport | learned low-level | retain vendor baseline |
| terrain learned control | train Go2 teacher/student | Parkour/DreamWaQ++ patterns | no ready checkpoint found |
| state estimation | GLIM | FAST-LIO2 / RTAB-Map | benchmark behind contract |
| elevation/support map | Elevation Mapping CuPy | custom/core extraction | lead prototype |
| 3-D clearance map | nvblox | Wavemap | complementary, not replacement |
| flat local control | terrain-aware MPPI based on mature MPPI ideas | current grid tracker | preserve baseline |
| rough/multi-floor route | geometric capability planner | SCAN/ArtPlanner | challenger in shadow |
| final safety | Parcel raw-sensor/stability exact-hold admission | Nav2 Collision Monitor pattern | P0 mandatory |
| articulated training | Isaac Lab | MJX | Isaac first |
| independent physics | Unitree MuJoCo | Gazebo | required cross-sim |
| dynamic city | MetaUrban | URBAN-SIM | sidecar, not foot authority |
| indoor semantics | pinned Habitat/iGibson | OmniGibson | evaluation sidecar |
| high-level learned nav | InternNav | CityWalker/NaVILA/NavDP | later proposal-only bake-off |
| voice | existing simple path | none in task_7 | freeze scope |
