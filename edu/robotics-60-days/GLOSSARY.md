# Glossary (short)

Focused on Module 6 terms. Paths are Parcel codebase anchors.

| Term | Meaning | Parcel anchor |
| --- | --- | --- |
| **Action chunking** | Predict a short action sequence; execute prefix; replan | Tip into `SE2Goal` / bounded twists—not joints |
| **ACT tokens** | Discrete action vocabulary for duplex/UX research | `duplex/act_codec.py` (`ActTokenCodec`, `TwistBins`) |
| **Behavior cloning (BC)** | Supervised IL from demos | Must still clear `PlanValidator` / gates |
| **CBF** | Control barrier function; constraint filter on controls | Prototype only; cannot retire reactive gates |
| **CommandArbiter** | Priority + TTL gate for velocity intents | `core/arbiter.py` |
| **ControlManager** | Single writer, watchdog, E-stop lifecycle for loco | `control/manager.py` |
| **Diffusion / flow policy** | Generative distribution over action chunks | Proposer role; p99 latency matters |
| **DirectiveNavigator** | NL/semantic directive → mid-level nav command | `navigation/pipeline.py` |
| **GoalArbiter / ProposerBus** | Hot-swappable `SE2Goal` competition with TTL/lethal veto | `instructnav/arbiter.py` |
| **Go2Env** | Gym-like RL stub; joint-target actions | `rl/env.py`, `rl/spaces.py` |
| **PlanIR** | Typed plan contract from deliberative models | `brain/contracts.py` + `PlanValidator` |
| **Reactive safety** | Final body-frame person/obstacle / stale-telemetry gate | `navigation/reactive_safety.py` |
| **SafetySupervisor** | Fail-closed tool/backend/limit validation | `safety.py` |
| **SE2Goal** | Pose/waypoints + confidence + TTL in map/odom | Safer FM interface than motors |
| **Shadow mode** | Log model outputs; no actuator authority | Default for VLAs / unproven loco |
| **Sport / vendor backend** | Unitree locomotion controller path | `control/unitree_sport.py`; default product |
| **VLA** | Vision-language-action foundation model | Untrusted proposer; Day 54 |
| **VLN** | Vision-language navigation | Prefer waypoints via `ProposerBus` |
| **World model** | Learned future predictor / neural sim | Eval/scenario tool—not a shield |
