# Day 52: Reinforcement Learning for Navigation and Locomotion

## Mental model

Reinforcement learning (RL) searches for a policy that maximizes expected return. Unlike imitation learning, it does not need a demonstrator for every situation—but it *does* need a reward, a reset distribution, and a place to make mistakes. On a quadruped those mistakes cost hardware, reputation, and sometimes injury. Treat RL as an optimizer that will exploit every loophole in your reward and every missing constraint in your action space.

```text
MDP sketch:
  s_{t+1} ~ P(·|s_t, a_t)
  maximize E[ Σ_t γ^t r(s_t, a_t) ]

Parcel-relevant split:
  navigation RL  -> choose body goals / costs  (slow, semantic)
  locomotion RL  -> choose gait / joint effort (fast, contact)
```

Navigation RL and locomotion RL are different products. Confusing them is how teams “solve Nav2 with PPO” in slides and then discover the dog cannot balance while the policy thinks about sidewalks.

## Tradeoffs and industry trends

Trends that matter for Parcel:

- **Sim-heavy locomotion RL** (Isaac / MuJoCo / Isaac Lab lineages) with domain randomization is now the default path to agile gaits—often with a privileged teacher and a student that sees realistic sensors.
- **Offline / batch RL** and conservative Q-learning variants try to learn from logs without more unsafe exploration.
- **Reward hacking** remains undefeated: agents spin in place for “progress,” hug walls for “clearance bonuses,” or fall safely forever if fall penalty is mis-scaled.
- **Curriculum learning** (flat → rough → stairs; sparse → dense pedestrians) is often more important than the algorithm name on the paper.

| Design choice | Prefer when | Avoid when |
| --- | --- | --- |
| Dense shaped reward | Early learning signal | It encodes a bad local optimum |
| Sparse task reward | You can afford exploration | Sidewalks, people, hardware |
| Body-velocity action space | You keep Unitree Sport | You need true joint authority |
| Joint-torque action space | Research loco replacement | Companion product without HIL gates |
| Online RL on robot | Carefully instrumented lab | Public urban deployment |
| Offline RL from logs | You already have coverage | Logs lack failures/recoveries |

Module 6 interrogation: observe? act? rate/latency? data/compute? Unitree transfer? deterministic safety layer? An RL nav policy that outputs waypoints at 2–5 Hz behind a shield can transfer. An RL loco policy that needs 200–1000 Hz joint torque and privileged friction estimates does not drop into Parcel’s Python 10 Hz brain.

## ASCII diagram

```text
                 reward designer (human)
                         |
                         v
  sim / log buffer ---> RL update ---> πθ
                         |
            +------------+-------------+
            |                          |
            v                          v
   nav action: SE2 goal /          loco action: joint tgt
   cost map tweak                  or residual torque
            |                          |
            v                          v
   classical planner +             Sport OR research
   collision / TTC shield          loco stack (gated)
            |                          |
            +---------> measured progress / falls / timeouts
```

## Map to Parcel / Go2

Parcel already has an RL-shaped seam—and keeps product motion deterministic around it.

Codebase-relative context:

- `SafetySupervisor` / `ALLOWED_BACKENDS` in `safety.py` admit only `vendor` and `rl` (plus deprecated `sport`→`vendor` alias)—backend switching is gated, not free-form.
- Loco research loop: `Go2Env` (`rl/env.py`) with `action_space_spec()` = 12 joint position targets (`rl/spaces.py`). That is **not** what `ControlManager` sends to Sport (`TimedVelocitySetpoint` body twists).
- Nav research loop: `MetaUrbanNavEnv` (`navigation/envs/metaurban_env.py`) is a kinematic scaffold; `use_metaurban=True` is fail-closed until a real adapter exists.
- Product nav still runs `DirectiveNavigator` (`navigation/pipeline.py`) → `apply_collision_brake` (`navigation/collision.py`) → runtime `CommandArbiter` + `ControlManager`.

Practical Parcel mapping:

- **Navigation RL:** scorers / detour preferences / supervisory proposers into `ProposerBus`—not end-to-end motors. Keep `CollisionPolicy` + `ReactiveSafetyPolicy` on.
- **Locomotion RL:** vendor-replacement track with stand/fenced commissioning. Do not couple to voice → `PlanIR` until loco promotion criteria exist.
- **Rewards:** companion values carefully—see `rl/rewards.py` / `navigation/envs/rewards.py` as sketch surfaces, not safety cases.

Compute reality: loco training may need GPU-days; hard-rate inference is outside the Python ~10 Hz brain.

## Overconfidence story

An offline RL run on logged city episodes maximized a “distance-to-goal decrease” reward. In replay it looked brilliant. Deployed as a local navigator, the policy learned to cut inside corners where the log distribution had few pedestrians. The first near-miss was a jogger entering from occlusion—the training metric never penalized *surprise* occupancy, only geometric progress on logged maps. The team had optimized the reward, not urban competence. Overconfidence was metric laundering: a scalar rose while the hazard model stayed naive.

## Retrieval questions

1. Why is “RL for navigation” not the same engineering project as “RL for locomotion” on a Go2?
2. Give one concrete reward-hacking failure mode for owner-following and the constraint that would catch it.
3. (Week-back) From Day 35/58 preview: what still has to stop the robot if the RL policy outputs a high-reward but unsafe action?

## Optional 10-minute exercise

Draft a reward and action-space card for *one* problem only (pick nav or loco). Include: observation vector with rates, action bounds, episode termination, three reward terms with scales, two known hacking modes, and the deterministic shield that remains on during any real-robot trial. If you cannot name the shield, you are not ready to train.
