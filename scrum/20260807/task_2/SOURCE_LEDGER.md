# Primary-source research ledger

**Checked:** 2026-08-07. This ledger favors official repositories,
documentation, project pages, and papers. “Released” means an artifact was
publicly visible; it does not mean Parcel has downloaded, integrated,
reproduced, security-reviewed, or accepted it. Repository license and model
weight/data/asset terms are tracked separately. Recheck every commit, model
card, and transitive dependency at acquisition time.

External scores are author-reported and not cross-benchmark comparable.

## Classical navigation, control, and Unitree

| Source | What it contributes | Artifact/terms note |
| --- | --- | --- |
| [Nav2 repository](https://github.com/ros-navigation/navigation2) | ROS 2 navigation architecture and source | Open code; package-level terms still need a dependency audit |
| [Route Server](https://docs.nav2.org/configuration/packages/configuring-route-server.html) and [route graph generation](https://docs.nav2.org/tutorials/docs/route_server_tools/route_graph_generation.html) | semantic/topological route edges, closures, costs, operations | Documentation/design source |
| [Smac planners](https://docs.nav2.org/configuration/packages/configuring-smac-planner.html) | 2-D, Hybrid-A*, State Lattice global planning | First global-planner comparison |
| [Regulated Pure Pursuit](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html) | interpretable path tracking with speed regulation | Recommended deterministic controller baseline |
| [MPPI](https://docs.nav2.org/configuration/packages/configuring-mppic.html) | optimization-based local controller and critic plugins | Recommended dynamic-controller challenger |
| [Rotation Shim](https://docs.nav2.org/tutorials/docs/using_shim_controller.html) | contextual turn-before-track behavior | Use contextually, not universally |
| [Smoother Server](https://docs.nav2.org/configuration/packages/configuring-smoother-server.html), [velocity smoother](https://docs.nav2.org/configuration/packages/configuring-velocity-smoother.html) | path/velocity smoothing | Parcel must ensure only one final velocity smoother |
| [Collision Monitor](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html) | final velocity-level collision zones and source freshness | Valuable defense; not treated as safety certification |
| [Following Server](https://docs.nav2.org/configuration/packages/configuring-following-server.html) | dynamic-point following reference | Does not solve enrolled identity or Parcel formation semantics |
| [Nav2 behavior trees](https://docs.nav2.org/behavior_trees/index.html) | replanning, recovery, action composition | Navigation subtree reference |
| [ROS 2 actions design](https://design.ros2.org/articles/actions.html) | async goal/feedback/result/cancel lifecycle | Cancel is not complete until acknowledged/resulted |
| [Unitree SDK2 Sport client header](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp) | official Go2 high-level Move/Stop API surface | Retain as locomotion boundary; exact firmware must be commissioned |
| [Unitree ROS2](https://github.com/unitreerobotics/unitree_ros2) | official ROS2 integration | Distribution/firmware compatibility must be pinned |
| [CMU Go2 autonomy stack](https://github.com/jizhang-cmu/autonomy_stack_go2) | Point-LIO-derived SLAM, terrain, collision avoidance, waypoint following on Go2 | Hardware baseline, not turnkey safety: its README reports low-obstacle limits (>0.3 m guidance), occasional SLAM drift, unsynchronized camera versus LiDAR/IMU timestamps, and >1 s delay in an external Humble path |
| [SLAM Toolbox](https://github.com/SteveMacenski/slam_toolbox) | mature planar ROS2 SLAM | Indoor planar baseline |
| [FAST-LIO2](https://github.com/hku-mars/FAST_LIO) | high-rate LiDAR–inertial odometry with direct point registration | Preferred Phase-1 ODOM candidate when an external Mid-360-class LiDAR is fitted; Parcel bag/profile evidence is still required |
| [Point-LIO](https://github.com/hku-mars/Point-LIO) | high-bandwidth LiDAR–inertial odometry | Candidate for L1/3-D LiDAR state estimation |
| [LIO-SAM](https://github.com/TixiaoShan/LIO-SAM) | factor-graph LiDAR–inertial mapping and loop closure | Mapping/long-loop backend candidate, not the default reactive ODOM producer |
| [Direct LiDAR-Inertial Odometry](https://github.com/vectr-ucla/direct_lidar_inertial_odometry) | continuous-time tightly coupled LIO | Logged-bag challenger; thinner Go2 operations evidence than FAST-LIO2/Point-LIO |
| [RTAB-Map ROS2](https://github.com/introlab/rtabmap_ros) | RGB-D/stereo/3-D LiDAR mapping and Nav2 integration | Vendor-neutral mapping/localization candidate |
| [Isaac ROS nvblox](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox) | GPU TSDF/ESDF, depth/3-D LiDAR fusion, Nav2 costmaps | Strong Orin geometry candidate; dynamic-mode caveats must be tested |
| [elevation_mapping_cupy](https://github.com/leggedrobotics/elevation_mapping_cupy) | robot-centric elevation/variance/semantic layers | Legged terrain/curb/slope challenger |

## Open/downloadable navigation and tracking models

| Candidate | Public status observed | Parcel role and caution |
| --- | --- | --- |
| [MiniCPM-RobotTrack repository](https://github.com/OpenBMB/MiniCPM-Robot) / [weights](https://huggingface.co/openbmb/MiniCPM-RobotTrack) / [Go2 deployment](https://github.com/OpenBMB/MiniCPM-Robot/blob/main/MiniCPM-RobotTrack/docs/GO2_DEPLOYMENT.md) | Apache-2.0 code and model card/weights; model card says eight `(x,y,yaw)` waypoints and Go2 local deployment; official loader uses `trust_remote_code=True`; DINOv3 is gated and upstream vision encoders retain separate terms | First owner-follow shadow. Author reports ~180 ms/5+ FPS and nonzero benchmark collision rates; review/sandbox custom code and transitive assets; never owns identity or safety |
| [InternNav code](https://github.com/InternRobotics/InternNav), [InternVLA-N1 project](https://internrobotics.github.io/internvla-n1.github.io/), [System 2](https://huggingface.co/InternRobotics/InternVLA-N1-System2), [DualVLN](https://huggingface.co/InternRobotics/InternVLA-N1-DualVLN), [NavDP combination](https://huggingface.co/InternRobotics/InternVLA-N1-w-NavDP), [InternData-N1](https://huggingface.co/datasets/InternRobotics/InternData-N1) | InternNav code is MIT; System 2/DualVLN README badges declare CC BY-NC-SA 4.0 while machine-readable Hub metadata/artifact grants are absent; InternData's gated text says CC BY-NC-SA while YAML says CC BY-SA | Strong desktop instruction-navigation research challenger, but product use is blocked and isolated research needs artifact-by-artifact legal approval |
| [X-NavDP code](https://github.com/InternRobotics/NavDP/tree/master/baselines/x-navdp), [weights](https://huggingface.co/InternRobotics/X-NavDP), [paper](https://arxiv.org/abs/2607.28560), [results](https://yty-sky.github.io/x-navdp-project-page/), [parent NavDP](https://github.com/InternRobotics/NavDP) | only the self-contained X-NavDP subtree has an MIT file; HF checkpoint has no license metadata; parent has no top-level license file and its README says CC BY-NC-SA; Isaac/NVIDIA assets are separate | Promising RGB-D local-trajectory/recovery challenger; terms block acquisition until legal review; author-reported Go2 evidence is not Parcel proof |
| [CE-Nav code/checkpoints](https://github.com/amap-cvlab/CE-Nav), [paper](https://arxiv.org/abs/2509.23203) | MIT repository publishes cross-embodiment evaluation, a VelFlow expert, and a Go2 policy checkpoint; training code remains listed as forthcoming | First Go2 local-policy screen pending artifact/dependency review; its exact Isaac Sim 2023.1.0-hotfix.1 dependency and checkpoint terms remain separate deployment risks |
| [CityWalker code/release](https://github.com/ai4ce/CityWalker/releases/tag/v1.0), [converted weights](https://huggingface.co/ai4ce/citywalker), [CVPR paper](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_CityWalker_Learning_Embodied_Urban_Navigation_from_Web-Scale_Videos_CVPR_2025_paper.html) | Apache-2.0 project/converted weights; converted loader uses `trust_remote_code=True`; Parcel's original checkpoint is byte-identical to official v1.0 (`a423…c1c29`) but has no asset-specific notice/embedded SPDX (`NOASSERTION`) | Urban waypoint/traversability prior; clear original-asset license scope and sandbox custom code; no language, yaw, identity, or social authority |
| [NaVILA code](https://github.com/AnjieCheng/NaVILA), [8B checkpoint](https://huggingface.co/a8cheng/navila-llama3-8b-8f), [paper](https://navila-bot.github.io/static/navila_paper.pdf) | Apache-2.0 code; the public HF checkpoint has no model card or declared license, and packaged Llama terms need review | Authors measure FP16 594.58 ms/18.5 GB and W4A16 367.80 ms/8.6 GB on RTX 4090; it emits a discrete verb plus continuous distance/angle mapped to velocity/duration, so it remains a secondary research comparator |
| [StreamVLN code](https://github.com/InternRobotics/StreamVLN), [paper](https://arxiv.org/abs/2507.05240), [Go2 instructions](https://github.com/InternRobotics/StreamVLN/blob/main/realworld/realworld.md) | Official work/repository is CC BY-NC-SA 4.0 and documents remote Go2 execution; checkpoint/upstream terms are separate | Desktop research comparator; target-device latency and VRAM are not specified |
| [Uni-NaVid code](https://github.com/jzhzhang/Uni-NaVid), [checkpoint](https://huggingface.co/Jzzhang/Uni-NaVid/tree/main/uninavid-7b-full-224-video-fps-1-grid-2) | MIT code; public large checkpoint with unclear weight metadata | Generalist/human-follow research baseline; not Orin default |
| [VLFM code](https://github.com/rai-opensource/vlfm), [paper](https://arxiv.org/abs/2312.03275) | MIT orchestration code; component models have separate terms | Promising pattern for open-vocabulary frontier/value-map search; replace its controller with Parcel planning/safety |
| [NoMaD paper](https://arxiv.org/abs/2310.07896), [ViNT paper](https://arxiv.org/abs/2306.14846), [visualnav-transformer code/checkpoints](https://github.com/robodhruv/visualnav-transformer) | MIT code; checkpoint terms must be checked separately | Teach-repeat/topological memory and exploration, not semantic conversation |
| [VAMOS inference/ROS code](https://github.com/vamos-vla/vamos), [3B planner](https://huggingface.co/mateoguaman/vamos), [artifact collection](https://huggingface.co/collections/mateoguaman/vamos-a-hierarchical-vision-language-action-model-for-capab), [project](https://vamos-vla.github.io/) | Public planner and Spot/HOUND affordance checkpoints; planner is under Gemma terms and a noncommercial training-data restriction; repository has no detected top-level license | Research-only semantic pixel-path/affordance comparison; there is no Go2 affordance model and released artifacts cannot be presumed product-eligible |
| [OmniNav code/checkpoints](https://github.com/amap-cvlab/OmniNav) | Public training/inference code and visual-only/slow-fast ModelScope checkpoints; no detected top-level repository license and artifact terms require review | Research-only OVON/R2R/RxR exploration comparison; legacy Habitat versions and no Go2 evidence make it unsuitable as the product controller |
| [OmTrackVLA code](https://github.com/om-ai-lab/OmTrackVLA), [0.6B checkpoint](https://huggingface.co/omlab/OmTrackVLA-0.6B) | HF checkpoint declares MIT; repository has no detected top-level license | Second compact owner-tracking comparator; no verified Go2/Orin evidence found |

## Code/paper-only architecture references

| Source | Useful lesson | Availability consequence |
| --- | --- | --- |
| [Qwen-RobotNav official repository](https://github.com/QwenLM/Qwen-RobotNav) | unified task-adaptive context and eight `(x,y,theta)` waypoints in a two-tier agent | Official README explicitly says there is no plan to release weights; north star only |
| [NavFoM project](https://pku-epic.github.io/NavFoM-Web/) | broad task/embodiment foundation-navigation concept | No verified public weights in this audit |
| [TrackVLA repository](https://github.com/wsakobe/TrackVLA), [paper](https://arxiv.org/abs/2505.23189) | embodied target-tracking benchmark and diffusion/anchor ideas | Public repository is evaluation-oriented; original runtime weights unavailable/noncommercial terms |
| [SocialNav repository](https://github.com/AMAP-EAI/SocialNav) / [CVPR paper](https://openaccess.thecvf.com/content/CVPR2026/html/Chen_SocialNav_Training_Human-Inspired_Foundation_Model_for_Socially-Aware_Embodied_Navigation_CVPR_2026_paper.html) | social reasoning plus trajectory expert | Linked checkpoint set appeared incomplete; watch rather than integrate |
| [G2-Nav paper](https://arxiv.org/abs/2607.16956) | semantic VLM costmap above a high-frequency LiDAR reflex | No released implementation verified; architecture reference |

## Perception, identity, and world memory

| Source | Proposed use | Caveat |
| --- | --- | --- |
| [RT-DETR](https://github.com/lyuwenyu/RT-DETR) | fast closed-set people/vehicle/door/pole/obstacle detector | Fine-tune and profile on mounted-camera data; published FPS is not Orin proof |
| [PP-LiteSeg / PaddleSeg](https://github.com/PaddlePaddle/PaddleSeg) | road/sidewalk/floor/grass/curb/stair/doorway regions | Profile accuracy and TensorRT deployment on Parcel data |
| [DeepStream tracker](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html) | NvDCF/DeepSORT deployment substrate | Track IDs can change after long occlusion; Parcel identity layer stays above it |
| [deep-person-reid / OSNet](https://github.com/KaiyangZhou/deep-person-reid), [FastReID](https://github.com/JDAI-CV/fast-reid) | appearance evidence for consented owner enrollment/association | Appearance alone is not identity; combine with geometry/motion/ambiguity |
| [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) | local prompted open-vocabulary boxes | On-demand only; model/release terms and prompt calibration reviewed separately |
| [SAM 2](https://github.com/facebookresearch/sam2) | masks and short-horizon propagation | Not an identity or free-space authority |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | ROI-only storefront/sign OCR with temporal voting | Low viewpoint, blur, and perspective require active view/rectification |
| [Isaac ROS Grounding DINO guidance](https://nvidia-isaac-ros.github.io/v/release-4.0/repositories_and_packages/isaac_ros_object_detection/isaac_ros_grounding_dino/index.html) | deployment recommendation to interleave open-vocab inference and train fast detector for runtime | Supports fast/slow perception split |
| [ROS 2 message filters](https://docs.ros.org/en/ros2_packages/rolling/api/message_filters/message_filters.html) | timestamp synchronization tools | Capture-time transforms still require calibrated clocks/history |
| [Isaac ROS extrinsic calibration](https://nvidia-isaac-ros.github.io/v/release-4.5/getting_started/sensors/amr_extrinsic_calibration.html) | sensor-to-base calibration requirements | Calibration must be versioned and validated on the actual mount |
| [Clio](https://github.com/MIT-SPARK/Clio) | task-driven open-set 3-D scene graph | Later adapter after basic typed memory/localization works |
| [Khronos](https://github.com/MIT-SPARK/Khronos) | dynamic metric-semantic scene memory | ROS2 implementation described as incomplete/active development |
| [VLMaps](https://github.com/vlmaps/vlmaps) | language-addressable posed RGB-D maps | Useful semantic-memory baseline |
| [ConceptGraphs](https://github.com/concept-graphs/concept-graphs) | open-vocabulary object graphs | Dependency/API burden; offline experiment first |

## Instruction following and behavior planning

| Source | Design lesson | Parcel decision |
| --- | --- | --- |
| [FunctionGemma documentation](https://ai.google.dev/gemma/docs/functiongemma), [270M checkpoint](https://huggingface.co/google/functiongemma-270m-it) | small model meant for a defined tool/API surface and fine-tuning; HF access requires accepting Gemma usage terms | Shadow candidate for `TaskRequestV1`, not conversation or task authority; acquisition and derivative use remain terms-gated |
| [SayCan code](https://github.com/google-research/google-research/tree/master/saycan) / [Google explanation](https://research.google/blog/towards-helpful-robots-grounding-language-in-robotic-affordances/) | combine language usefulness with embodied skill feasibility | Keep model proposals separate from system feasibility/admission |
| [Inner Monologue](https://innermonologue.github.io/) | close the high-level loop with environment feedback/replanning | Feed typed observations/outcomes, not uncontrolled prose/world truth |
| [PlanBench](https://papers.neurips.cc/paper_files/paper/2023/hash/efb2072a358cefb75886a315a6fcf880-Abstract-Conference.html) | executable planning needs external verification | Retain compiler/validator/executive; do not use LLM-only planning |
| [BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP) | typed async reactive behavior subtrees and tracing | Candidate inside the ROS navigation/recovery sidecar |
| [PlanSys2](https://github.com/PlanSys2/ros2_planning_system) | PDDL/ROS2 planning for combinatorial domains | Defer until Parcel has genuinely combinatorial long-horizon tasks |
| [llama.cpp grammars](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) | constrained JSON generation | Precompile/test schema and still apply semantic validation |
| [KnowNo / language-model uncertainty](https://github.com/google-research/google-research/tree/master/language_model_uncertainty) | calibrated abstention/clarification pattern | Calibration guarantees do not transfer without a Parcel calibration set |
| [SayPlan](https://sayplan.github.io/) | retrieve a relevant scene subgraph, plan, and iteratively verify | Useful memory-to-planner pattern; no reusable dog policy |
| [RT-H](https://rt-hierarchy.github.io/) | language-action hierarchy and corrective language | Research pattern; manipulation-specific |

## Social navigation and evaluation

| Source | Scope | Decision/terms note |
| --- | --- | --- |
| [Follow-Bench](https://github.com/MedlarTea/follow-bench), [paper](https://arxiv.org/abs/2509.10796) | randomized socially aware person-follow planning, crowds/layouts/formations/metrics | First external owner-follow adapter; review top-level/component licenses before vendoring |
| [HuNavSim](https://github.com/robotics-upo/hunav_sim), [paper](https://arxiv.org/abs/2305.01303) | ROS2 human behavior and social evaluator across simulators | Next social regression service; v2 is still evolving |
| [MetaUrban](https://github.com/metadriverse/metaurban), [paper](https://arxiv.org/abs/2407.08725) | procedural dynamic urban simulator with multimodal sensing and social navigation | Best dynamic-city stress lane; full asset terms/registration separate |
| [Arena-Rosnav](https://github.com/Arena-Rosnav) | planner/social simulator comparison and training framework | Secondary broad comparison after Follow-Bench/HuNavSim |
| [Habitat 3](https://aihabitat.org/habitat3/), [Habitat-Lab](https://github.com/facebookresearch/habitat-lab) | indoor human/robot social navigation and follow | Code MIT; repository says no active Meta maintenance beyond v0.3.4; scene/data terms separate |
| [OmniGibson/BEHAVIOR overview](https://behavior.stanford.edu/omnigibson/overview.html), [installation](https://behavior.stanford.edu/getting_started/installation.html), [iGibson](https://github.com/StanfordVL/iGibson) | current Stanford successor path for interactive indoor physics and household tasks | Later indoor-interaction lane, not the primary city/follow benchmark; assets and Isaac terms separate |
| [Trajectron++](https://github.com/StanfordASL/Trajectron-plus-plus), [paper](https://arxiv.org/abs/2001.03093) | multimodal probabilistic human prediction | Promote only over calibrated simple predictors in closed-loop eval |
| [RVO2](https://github.com/snape/RVO2) | reciprocal multi-agent collision avoidance and crowd simulation | Useful simulated humans; reciprocal responsibility is not a live human safety guarantee |
| [nav2 social costmap plugin](https://github.com/robotics-upo/nav2_social_costmap_plugin) | reference proxemic costmap implementation | Soft social cost only; geometry remains hard authority |

## External navigation benchmarks

| Source | What it tests | Current use |
| --- | --- | --- |
| [BARN 2026 official protocol](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html), [ROS2 repository](https://github.com/Saadmaghani/The-Barn-Challenge-Ros2) | 300 public development worlds; official score over 50 new organizer-hidden worlds × 10 trials; simulation on Xeon with no specific compute restriction; physical i3/16 GB with no GPU | First external controller gate; only organizer hidden evaluation supports leaderboard claims; repo license visibility requires review |
| [BARN 2026 retrospective](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf) | reports all physical finalists used classical navigation for a second consecutive year | Evidence to exhaust mature classical control first; Jackal constrained-space evidence does not settle semantic/social/quadruped navigation |
| [BARN 2026 retrospective: DynaBARN](https://people.cs.gmu.edu/~xiao/papers/barn26_report.pdf) | optional parenthesized simulation result excluded from final scoring/ranking; physical dynamic arena was not run; organizers plan static focus | Keep DynaBARN as a separate nonofficial regression, not a 2026 official leaderboard claim or owner-follow proxy |
| [VLN-CE repository](https://github.com/jacobkrantz/VLN-CE) | language navigation in continuous Habitat environments | Legacy isolated research comparator with scene/data terms |
| [NaVILA-Bench](https://github.com/yang-zj1026/NaVILA-Bench) | physics-aware quadruped/humanoid VLN in Isaac | Later quadruped instruction benchmark |
| [ABotN-Bench](https://github.com/amap-cvlab/ABot-Navigation) | public PointBench, POIBench, and short-horizon OVON evaluator with a minimal `reset()`/`predict()` adapter over real-world 3DGS scenes | Apache-2.0 evaluator; 3DGS scene/data terms remain separate. Use as a role-specific closed-loop point/POI lane, not physical or safety evidence |
| [EmbodiedBench](https://github.com/EmbodiedBench/EmbodiedBench) | MLLM planning/navigation/manipulation benchmark with local serving | Planner/reasoner research lane, not motor safety evidence |
| [SocNavBench](https://github.com/CMU-TBD/SocNavBench) | grounded pedestrian/social navigation scenarios | Secondary archival social benchmark |
| [NavVerse project](https://umich-curly.github.io/NavVerse-Benchmark/) | proposed indoor/outdoor multi-task navigation in Isaac | Watch only; project page still said code coming soon at audit time |

## Learning and RL decision sources

| Source | Lesson used | Parcel implication |
| --- | --- | --- |
| [DAgger](https://proceedings.mlr.press/v15/ross11a/ross11a.pdf) | aggregate expert labels on learner-visited states | Use BC/DAgger before RL once a valid expert/sensor corpus exists |
| [Residual RL](https://arxiv.org/abs/1812.03201) | additive action residuals can build on a competent controller | Background only: it does **not** justify Parcel's proposed discrete candidate ranker, and additive velocity/joint residuals remain out of scope |
| [Implicit Q-Learning](https://arxiv.org/abs/2110.06169) | offline RL without querying out-of-distribution actions during training | No use until broad representative logged support exists |
| [TD3+BC](https://arxiv.org/abs/2106.06860) | constrain offline actor improvement toward behavior data | Same data prerequisite; not a fix for absent/biased logs |
| [FLaRe](https://arxiv.org/abs/2409.16578) | on-policy RL fine-tuning of a strong foundation navigation policy | Evidence for post-training only after a pretrained baseline and valid simulator |
| [SPOC](https://arxiv.org/abs/2312.02976) | scaled shortest-path imitation for object navigation | Supports expert imitation before expensive reward engineering |
| [Unitree RL mjlab](https://github.com/unitreerobotics/unitree_rl_mjlab), [Unitree RL lab](https://github.com/unitreerobotics/unitree_rl_lab) | maintained Go2 low-level training/deployment lineages | Use only in a separate future LowCmd program if replacing Sport is justified |

## Model-artifact security

| Source | Lesson used | Parcel implication |
| --- | --- | --- |
| [Hugging Face custom-model loading](https://huggingface.co/docs/transformers/en/models#custom-models) | custom model code executes with `trust_remote_code`; documentation recommends pinning a specific revision | Pin immutable commits/hashes, review code, and never load remote code in the control process |
| [Hugging Face Hub security](https://huggingface.co/docs/hub/en/security), [pickle scanning](https://huggingface.co/docs/hub/security-pickle) | Hub scanners are useful but not foolproof; pickle deserialization can execute arbitrary code | Prefer safetensors, scan artifacts, sandbox inference without network/credentials, record SBOM and provenance |

## Source-selection conclusion

The strongest released exact-platform opportunity is MiniCPM-RobotTrack for
owner-follow proposals. CE-Nav is the first Go2 local-policy screen. InternVLA-
N1 remains a compelling desktop research candidate, but its current weight
README badges declare CC BY-NC-SA 4.0 while machine-readable artifact metadata
is absent, and its gated training dataset has conflicting CC BY-SA versus
CC BY-NC-SA declarations. X-NavDP is likewise blocked by an
undeclared checkpoint license and mixed parent/subtree terms. CityWalker is
already present and is the lowest-cost first adapter. Nav2 supplies the
strongest immediate classical comparison.

No source removes the need for real localization, calibrated camera/LiDAR
evidence, owner identity, task lifecycle, independent terminal predicates, or
final independent metric-geometry safety. Those are Parcel's core product
responsibilities.
