# Robotics Systems for Senior Software Engineers (60 days)

Companion course for building **Parcel** on a **Unitree Go2**. Start with the
[orientation](../INTRO.md). Use the parallel [Day 0–60 physics crash
course](../physics-60-days/README.md) when you want a slower, calculation-first
explanation of the physical concepts.

Each lesson is ~800–1,100 words (hard cap ~1,200): one mental model, light equations, an SE analogy, one ASCII diagram, Parcel/Go2 mapping with codebase pointers, a failure story, three retrieval questions, and an optional ~10-minute exercise.

## Module 1: The physical robot — Days 1–10

Ground truth for everything that follows: physics, morphology, power, and sensing — before control theory and autonomy software.

| Day | File | Topic |
| ---: | --- | --- |
| 1 | [day-01-physical-truth.md](day-01-physical-truth.md) | Physical truth vs software state |
| 2 | [day-02-units-dimensional-analysis.md](day-02-units-dimensional-analysis.md) | Units and dimensional analysis |
| 3 | [day-03-linear-mechanics.md](day-03-linear-mechanics.md) | Linear mechanics |
| 4 | [day-04-rotational-mechanics-balance.md](day-04-rotational-mechanics-balance.md) | Rotational mechanics and balance |
| 5 | [day-05-electricity-batteries-power-heat.md](day-05-electricity-batteries-power-heat.md) | Electricity, batteries, power, heat |
| 6 | [day-06-links-joints-dof.md](day-06-links-joints-dof.md) | Links, joints, DoF (Go2 × 12) |
| 7 | [day-07-motors-gearing-actuator-modes.md](day-07-motors-gearing-actuator-modes.md) | Motors, gearing, actuator modes |
| 8 | [day-08-proprioception.md](day-08-proprioception.md) | Proprioception (body sensing) |
| 9 | [day-09-exteroception.md](day-09-exteroception.md) | Exteroception (world sensing) |
| 10 | [day-10-synthesis-physical-chain.md](day-10-synthesis-physical-chain.md) | Synthesis: one command through the physical chain |

**Codebase touchstones for Module 1:** `configs/robot.yaml`, `docs/MOTION.md`, `src/parcel_robot/control/`, `src/parcel_robot/robot_profile.py`, `src/parcel_robot/backends/base.py`, `src/parcel_robot/models.py`.

## Module 2: Geometry, time, dynamics, and control — Days 11–20

| Day | File | Topic |
| ---: | --- | --- |
| 11 | [day-11-clocks-sampling-deadlines.md](day-11-clocks-sampling-deadlines.md) | Clocks, sampling, timescales, deadlines |
| 12 | [day-12-signals-noise-filtering-delay.md](day-12-signals-noise-filtering-delay.md) | Signals, noise, filtering, delay |
| 13 | [day-13-coordinate-frames-planar.md](day-13-coordinate-frames-planar.md) | Coordinate frames and planar transforms |
| 14 | [day-14-3d-rotations.md](day-14-3d-rotations.md) | Three-dimensional rotations |
| 15 | [day-15-forward-inverse-kinematics.md](day-15-forward-inverse-kinematics.md) | Forward and inverse kinematics |
| 16 | [day-16-jacobians-trajectory-generation.md](day-16-jacobians-trajectory-generation.md) | Jacobians and trajectory generation |
| 17 | [day-17-rigid-body-dynamics-contact.md](day-17-rigid-body-dynamics-contact.md) | Rigid-body dynamics, contact, friction |
| 18 | [day-18-feedback-control-pid.md](day-18-feedback-control-pid.md) | Feedback control and PID |
| 19 | [day-19-state-space-constrained-control.md](day-19-state-space-constrained-control.md) | State-space and constrained control |
| 20 | [day-20-synthesis-unitree-sport-nested-loop.md](day-20-synthesis-unitree-sport-nested-loop.md) | Synthesis: Unitree Sport nested loop |

## Module 3: Perception, estimation, and navigation — Days 21–30

| Day | File | Topic |
| ---: | --- | --- |
| 21 | [day-21-probability-uncertainty.md](day-21-probability-uncertainty.md) | Probability and uncertainty |
| 22 | [day-22-camera-fundamentals.md](day-22-camera-fundamentals.md) | Camera fundamentals |
| 23 | [day-23-lidar-fundamentals.md](day-23-lidar-fundamentals.md) | LiDAR fundamentals |
| 24 | [day-24-imu-odometry-drift.md](day-24-imu-odometry-drift.md) | IMU, odometry, drift, slip |
| 25 | [day-25-state-estimation-sensor-fusion.md](day-25-state-estimation-sensor-fusion.md) | State estimation and sensor fusion |
| 26 | [day-26-mapping-slam.md](day-26-mapping-slam.md) | Mapping and SLAM |
| 27 | [day-27-planning-search.md](day-27-planning-search.md) | Planning and search |
| 28 | [day-28-smooth-local-navigation.md](day-28-smooth-local-navigation.md) | Smooth local navigation |
| 29 | [day-29-dynamic-obstacles-owner-tracking.md](day-29-dynamic-obstacles-owner-tracking.md) | Dynamic obstacles, owner tracking |
| 30 | [day-30-synthesis-sidewalk-lamppost-owner.md](day-30-synthesis-sidewalk-lamppost-owner.md) | Synthesis: sidewalk, lamppost, and owner-orbit tasks |

## Module 4: Autonomy and production robotics software — Days 31–40

| Day | File | Topic |
| ---: | --- | --- |
| 31 | [day-31-typed-hardware-controller-boundaries.md](day-31-typed-hardware-controller-boundaries.md) | Typed hardware and controller boundaries |
| 32 | [day-32-ros2-robot-communication.md](day-32-ros2-robot-communication.md) | ROS 2 and robot communication |
| 33 | [day-33-realtime-distributed-failure.md](day-33-realtime-distributed-failure.md) | Real-time and distributed failure |
| 34 | [day-34-task-executives-behavior-control.md](day-34-task-executives-behavior-control.md) | Task executives and behavior control |
| 35 | [day-35-safety-engineering.md](day-35-safety-engineering.md) | Safety engineering |
| 36 | [day-36-what-simulator-computes.md](day-36-what-simulator-computes.md) | What a simulator computes |
| 37 | [day-37-reality-gap.md](day-37-reality-gap.md) | The reality gap |
| 38 | [day-38-testing-evaluation.md](day-38-testing-evaluation.md) | Testing and evaluation |
| 39 | [day-39-observability-latency.md](day-39-observability-latency.md) | Observability and latency |
| 40 | [day-40-synthesis-production-readiness.md](day-40-synthesis-production-readiness.md) | Synthesis: production readiness |

## Module 5: Building a voice-enabled companion — Days 41–50

| Day | File | Topic |
| ---: | --- | --- |
| 41 | [day-41-llm-untrusted-semantic-planner.md](day-41-llm-untrusted-semantic-planner.md) | LLM as untrusted semantic planner |
| 42 | [day-42-digital-audio-speech-pipelines.md](day-42-digital-audio-speech-pipelines.md) | Digital audio and speech pipelines |
| 43 | [day-43-full-duplex-barge-in.md](day-43-full-duplex-barge-in.md) | Full-duplex conversation and barge-in |
| 44 | [day-44-conversation-vs-planning-brain.md](day-44-conversation-vs-planning-brain.md) | Conversation brain vs planning brain |
| 45 | [day-45-language-to-typed-skills.md](day-45-language-to-typed-skills.md) | Language to typed skills |
| 46 | [day-46-closed-loop-task-execution.md](day-46-closed-loop-task-execution.md) | Closed-loop task execution |
| 47 | [day-47-owner-following-companion-nav.md](day-47-owner-following-companion-nav.md) | Owner following and companion nav |
| 48 | [day-48-personality-emotion-gestures.md](day-48-personality-emotion-gestures.md) | Personality, emotion, gestures |
| 49 | [day-49-open-weight-model-deployment.md](day-49-open-weight-model-deployment.md) | Open-weight model deployment |
| 50 | [day-50-synthesis-voice-to-safe-motion.md](day-50-synthesis-voice-to-safe-motion.md) | Synthesis: voice to safe motion |

**Codebase touchstones for Module 5:** `docs/VOICE_AI_MODELS.md`, `docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`, `docs/DUPLEX_DUAL_STREAM_DESIGN.md`, `src/parcel_robot/voice/agent.py`, `src/parcel_robot/voice/pipeline.py`, `src/parcel_robot/audio/voice_loop.py`, `src/parcel_robot/audio/devices.py`, `src/parcel_robot/duplex/`, `src/parcel_robot/brain/` (`router.py`, `contracts.py`, `executive.py`, `runtime_adapter.py`), `src/parcel_robot/navigation/follow.py`, `prompts/personalities/`, `prompts/system/`.

### Module 5 checklist

- [ ] LLM is untrusted: router → schema → `PlanValidator` / skills → `TaskExecutive` (never joints/torques)
- [ ] Audio cascade ends at final text before `VoiceAgent`; `CommitGuard` + `speech_epoch` fence stale turns
- [ ] Duplex D0 frames (`DuplexCoordinator`) observe; they do not outrank safety or double-drive motion
- [ ] Follow uses `FollowOwnerController` + keepout / reactive safety; personality cannot raise limits
- [ ] Trace one utterance: ASR → route → PlanIR/skills → arbiter → Sport → TTS / metrics / recovery

## Module 6: Frontier research and critical analysis — Days 51–60

| Day | File | Topic |
| ---: | --- | --- |
| 51 | [day-51-imitation-learning-action-chunking.md](day-51-imitation-learning-action-chunking.md) | Imitation learning and action chunking |
| 52 | [day-52-rl-navigation-locomotion.md](day-52-rl-navigation-locomotion.md) | RL for navigation and locomotion |
| 53 | [day-53-diffusion-flow-action-tokenization.md](day-53-diffusion-flow-action-tokenization.md) | Diffusion, flow, action tokenization |
| 54 | [day-54-vision-language-action-models.md](day-54-vision-language-action-models.md) | Vision-language-action models |
| 55 | [day-55-navigation-foundation-vlm.md](day-55-navigation-foundation-vlm.md) | Navigation foundation / VLN |
| 56 | [day-56-world-models-learned-sim.md](day-56-world-models-learned-sim.md) | World models and learned simulation |
| 57 | [day-57-learned-quadruped-locomotion.md](day-57-learned-quadruped-locomotion.md) | Learned quadruped locomotion |
| 58 | [day-58-safe-learning-runtime-assurance.md](day-58-safe-learning-runtime-assurance.md) | Safe learning and runtime assurance |
| 59 | [day-59-social-robotics-dynamic-cities.md](day-59-social-robotics-dynamic-cities.md) | Social robotics in dynamic cities |
| 60 | [day-60-final-architecture-research-review.md](day-60-final-architecture-research-review.md) | Final architecture and research review |
