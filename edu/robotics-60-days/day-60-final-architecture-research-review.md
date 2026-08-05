# Day 60: Final Architecture and Research Review

## Mental model

Parcel’s next-generation companion stack is not “replace Nav2/Sport with a foundation model.” It is a **proposal hierarchy** with a **deterministic spine**:

```text
voice/duplex -> semantic plan -> skills/goals -> nav mid-level -> shields -> ControlManager -> Sport
                 (untrusted)      (typed)         (classical+)     (fail closed)   (single writer)
```

Every frontier technique from Days 51–59 must be classified by how it tips into that spine—not by demo aesthetics. Software analogy: microservices may add recommenders endlessly; there is still one payment authorizer and one database primary writer.

## Classification rubric

| Class | Meaning | Evidence bar |
| --- | --- | --- |
| **Adopt now** | Ship on product path | Live gates + evals green |
| **Prototype behind interface** | Real code, swappable, off by default | Harness + shadow metrics |
| **Research in shadow mode** | Log-only / offline | No actuator authority |
| **Reject for this embodiment** | Wrong action authority or timescale | Architectural mismatch |

Module 6 questions remain mandatory on every candidate: observe? act? rate/latency? data/compute? Unitree transfer? deterministic safety layer?

## ASCII diagram — target spine

```text
  DuplexCoordinator / ASR
           |
           v
  LLM/VLA semantic tip-in -----> PlanValidator -----> PlanIR
           |                                           |
           v                                           v
  VLN/IL/RL proposers ---> ProposerBus/GoalArbiter     TaskExecutive
           |                         |                    |
           +----------- SE2Goal ------+                    |
                                 |                        v
                                 v                   skill runner
                        DirectiveNavigator
                                 |
                                 v
              apply_collision_brake + apply_reactive_safety
                                 |
                                 v
                          CommandArbiter (TTL)
                                 |
                                 v
                           ControlManager
                                 |
                    +------------+------------+
                    | vendor (default)        | rl (gated research)
                    v                         v
             UnitreeSportController        Go2Env-class loco
```

## Map to Parcel / Go2 — adopt / prototype / shadow / reject

Codebase-relative spine (do not bypass):

- `PlanIR` + `PlanValidator` + `TaskExecutive` (`brain/contracts.py`, `brain/validator.py`, `brain/executive.py`)
- `SE2Goal` / `ProposerBus` / `GoalArbiter` (`instructnav/arbiter.py`)
- `DirectiveNavigator` + `FollowOwnerController` + `ModelRegistry` (`navigation/pipeline.py`, `follow.py`, `registry.py`)
- `apply_collision_brake` + `apply_reactive_safety` (`navigation/collision.py`, `reactive_safety.py`)
- `CommandArbiter` + `VelocitySmoother` (`core/arbiter.py`, `core/velocity_smoother.py`)
- `ControlManager` + `UnitreeSportController` (`control/manager.py`, `control/unitree_sport.py`)
- `SafetySupervisor` / `SafetyLimits` / `ALLOWED_BACKENDS` (`safety.py`)
- `DuplexCoordinator` + `ActTokenCodec` (`duplex/coordinator.py`, `duplex/act_codec.py`) — speech/ACT tips only

### Adopt now

- Untrusted semantic planner → typed `PlanIR` (Day 41/45 pattern).
- Waypoint/SE2 authority separation for any nav foundation model (Day 55).
- Stacked runtime assurance: validator → goal arbiter → collision/reactive → `CommandArbiter` → `ControlManager` (Day 58).
- Vendor Sport as default loco; backend switch fail-closed (`ALLOWED_BACKENDS`).
- Companion follow + person stop/slow metrics as first-class evals.
- Observability/latency budgets on the spine (Day 39).

### Prototype behind an interface

- Chunked IL / diffusion / flow as `SE2Goal` or bounded twist proposers (Days 51/53)—reuse `ActTokenCodec` bins where discrete.
- Nav scorers / offline RL cost shaping into `DirectiveNavigator` / `dynamic_costs` (Day 52).
- VLN/nav foundations registered on `ProposerBus` with TTL/confidence (Day 55).
- World models for scenario mining feeding `evals/` (Day 56).
- CBF-style twist filters as an *extra* QP ahead of existing gates (Day 58).
- Social predictors as cost layers, not motor policies (Day 59).
- Duplex twist tokens for UX—still through `CommandArbiter`.

### Research in shadow mode

- OpenVLA / openpi / Gemini Robotics / GR00T action heads vs logged PlanIR (Day 54).
- Learned loco student vs Sport on proprio logs; no outdoor `rl` backend (Day 57).
- MetaUrban/Habitat social rollouts while `use_metaurban` stays fail-closed (Day 59).
- Experimental all-ray shields until promotion evidence exists (`experimental_all_ray_shield.py`).

### Reject for this embodiment

- VLA/IL/RL emitting joints/torques on public sidewalks past `ControlManager`/Sport.
- End-to-end pixels→twist without collision/reactive veto.
- Cloud-round-trip models inside balance or collision deadlines.
- World-model certificates as substitutes for sensing gates.
- Duplex/LLM paths that write motors without `CommandArbiter` TTLs.
- Any feature that requires deleting `PlanValidator` forbidden keys “just for the foundation model.”

## Tradeoffs and industry posture

The industry is racing to collapse layers into foundation models. Parcel’s durable bet is the opposite of fashion and aligned with production robotics: **more proposers, one writer, stricter evidence.** That bet is not anti-learning; it is anti-authority-confusion. When a paper shows 90% success on a benchmark, ask which row of the spine it replaces—and whether Unitree contact dynamics were ever in the training loop.

## Overconfidence story

A roadmap slide marked “VLA + RL loco Q3” because papers moved fast. The codebase already had the spine above; the slide skipped promotion gates and pretended `Go2Env` joint targets were a drop-in for Sport twists. The correct next-gen story is boring: register proposers, keep shields, measure p99, classify honestly. Overconfidence is scheduling architecture violations.

## Retrieval questions

1. Place Diffusion Policy, OpenVLA, and a VLN waypoint model into adopt/prototype/shadow/reject for Parcel sidewalks—and justify with action interfaces.
2. Which single object is the locomotion writer, and which gates feed it?
3. (Week-back) Quote one PlanIR forbidden key class and explain why frontier models still hit it.

## Optional 10-minute exercise

Write a one-page ADR: pick one frontier tip-in (e.g. VLN → `ProposerBus`). Specify observe/act/rate, feature flag default off, shadow metric, and the exact functions that can zero its output. Classify it. If you cannot name `ControlManager` and `apply_reactive_safety` in the veto path, rewrite.
