# Day 51: Imitation Learning and Action Chunking

## Mental model

Imitation learning (IL) turns demonstration trajectories into a policy that maps observations to actions. The senior-SE trap is treating it like supervised fine-tuning of an API client: if the labels look good, the model should work. On a robot, every wrong action *changes the next observation*, so train-time error compounds into deployment-time distribution shift. That is covariate shift under your own closed loop.

Behavior cloning (BC) minimizes action prediction error under the demonstrator’s state distribution. Action chunking predicts a short *sequence* of future actions (or waypoints) and executes the prefix before replanning. Chunking is not magic competence—it is a bias that reduces myopic stuttering and lets the policy commit through brief occlusions, at the cost of slower reaction to sudden hazards.

```text
open-loop BC:     a_t = π(o_t)                    # one step; errors accumulate
chunked BC:       (a_t … a_{t+H-1}) = π(o_t)      # commit H steps, then replan
DAgger-style:     label states the policy visits   # close the covariate gap
```

## Tradeoffs and industry trends

Industry trend (2022–2026): teleop + BC + chunking beat brittle scripted skills for short-horizon manipulation and some mobile skills, especially when demos include recoveries. ACT-style temporal ensembling and chunked transformers reduced “twitchy” single-step policies. The frontier narrative is “scale demos, scale models.” The production narrative is “coverage, interventions, and authority.”

Critical design choices:

| Choice | Win | Loss |
| --- | --- | --- |
| Single-step BC | Low latency, reactive | Compounding error, jitter |
| Chunk length H | Smoothness, occlusion tolerance | Stale commitment under sudden pedestrians |
| Expert-only demos | Clean labels | No recovery distribution |
| Human interventions in the dataset | Teaches corrections | Expensive; must tag intent |
| Absolute joint targets | Precise in lab frames | Brittle across embodiments |
| Relative / delta actions or SE(2) goals | Transfer friendlier | Needs consistent frames |

Ask every IL system the Module 6 questions: What does it observe? What action does it emit? At what rate/latency? What data/compute? Does evidence transfer to a Unitree Go2? What deterministic safety layer remains?

For Parcel, answers that emit *joint torques* or unbounded `vx,vy,vyaw` fail the transfer and safety questions even if the paper’s success rate looks excellent on a tabletop arm.

## ASCII diagram

```text
  teleop / scripted demo log
        |
        v
  dataset: (o_t, a_t..a_{t+H})  +  intervention tags
        |
        v
  chunk policy πθ  ----predict---->  action chunk [t .. t+H)
        |                              |
        |                              v
        |                     execute first k steps
        |                              |
        +----- replan on o_{t+k} <-----+
                                       |
                                       v
                         SafetySupervisor / collision gate
                                       |
                                       v
                         Unitree Sport (body vel) or skill runner
```

## Map to Parcel / Go2

Parcel already separates semantic intent from motion authority. IL should live *above* Sport for companion behaviors, or *beside* classical navigation as a proposer—not as a replacement for balance.

Codebase-relative context (foundations stay put while research explores):

- `PlanValidator` in `src/parcel_robot/brain/validator.py` forbids raw `vx`/`vy`/`vyaw`/`joint*` keys in model plans—IL outputs must not invent a side door around `PlanIR`.
- Runtime motion still passes `CommandArbiter` (`core/arbiter.py`) with TTLs, then `ControlManager` (`control/manager.py`) toward `UnitreeSportController`.
- Final geometric veto remains `apply_reactive_safety` / `apply_collision_brake` in the nav/runtime path—chunk policies propose; shields dispose.
- Hot-swap SE(2) tips: `SE2Goal` + `ProposerBus` + `GoalArbiter` in `instructnav/arbiter.py` (TTL + lethal-cost veto).

Concrete Parcel-shaped uses:

- **Adopt-shaped:** intervention chunks that still compile to typed skills / bounded velocity segments under `SafetySupervisor` (`safety.py`).
- **Prototype-shaped:** chunked BC → `SE2Goal` onto `ProposerBus`, never joints (`rl/spaces.py`’s 12-DoF joint targets are a *different* research seam).
- **Reject-shaped:** BC that bypasses `ControlManager` / Sport on a sidewalk.

Observation design matters more than model fashion. Train only on fields you will have at the same latency on hardware; keep Day 01’s `cmd`/`ack`/`meas`/`est`/`belief` discipline in logs.

## Overconfidence story

A team recorded twenty clean “circle the owner” demos indoors, trained a chunked policy (H=16), and watched validation MSE collapse. On the first outdoor demo the owner paused mid-orbit; the policy finished the remaining chunk as if the owner were still a fixed landmark, clipping a planter. The metrics said the model was accurate; the chunk was accurate *for the training distribution*. Overconfidence came from confusing demo coverage with closed-loop competence and from executing chunks without a freshness check on the owner track.

## Retrieval questions

1. Why does low action-prediction loss on a demo set fail to guarantee closed-loop success?
2. Name one benefit and one hazard of increasing action-chunk horizon H on a sidewalk follow task.
3. (Week-back) From Day 45/46: why must an IL policy’s outputs still cross PlanIR / `SafetySupervisor` rather than calling motors directly?

## Optional 10-minute exercise

Pick one Parcel skill (follow-behind, orbit, sit-after-nav). Write a one-page data contract: observation fields with max age, action representation (chunk of SE(2) goals vs body velocities), H and replan period, required intervention tags, and the exact deterministic gate that can zero the command. Mark any field that exists only in MuJoCo as forbidden for the hardware policy.
