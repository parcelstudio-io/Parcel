# Day 54: Vision-Language-Action Foundation Models

## Mental model

A vision-language-action (VLA) model extends a vision-language backbone so that it can emit robot actions conditioned on images and language. Architecturally it is an untrusted semantic-motor proposal generator with a glamorous training recipe. Parcel’s Day 41 lesson still applies: fluency is not authority.

Compare systems along interfaces, not brand names:

```text
language + images (+ state)  -->  VLA  -->  actions
                                      |
                                      +--> still need embodiment adapter
                                      +--> still need safety envelope
```

## Critical comparison (OpenVLA, openpi/π, Gemini Robotics, GR00T)

Approximate product shapes as of public materials—verify against primary sources before committing engineering:

| System | Observe (typical) | Act (typical) | Rate / latency posture | Data / compute posture | Embodiment story |
| --- | --- | --- | --- | --- | --- |
| **OpenVLA** | Camera (+ instruction) | Tokenized continuous actions (manipulation-centric) | Interactive demo rates; not hard RT loco | Open datasets + fine-tunes; research GPUs | Arms / tabletop transfer via fine-tune |
| **openpi / π models** | Vision + language (+ proprio) | Flow / continuous action experts; strong chunking culture | Tuned for robot control loops in their stack | Large proprietary+public mix; heavy train | Cross-robot claims; still adapter-heavy |
| **Gemini Robotics** | Multimodal Google stack | Embodied actions in their runtime | Cloud/edge hybrid latency realities | Frontier data/compute | Broad demos; product integration opaque |
| **GR00T** (NVIDIA) | Humanoid-centric multimodal | Cross-embodiment action generation | Aimed at humanoid platforms | Synthetic + real at scale | Humanoid gravity well |

Honest Module 6 answers for Parcel:

1. **Observe?** Mostly RGB (+ language). Parcel’s sidewalk competence also needs LiDAR geometry, owner tracks, battery/thermal, and stale-state handling these models do not own.
2. **Act?** Often end-effector twists, joint targets, or tokenized deltas—not `PlanIR` skills and not Unitree Sport setpoints.
3. **Rate/latency?** Semantic-to-action at a few Hz may be fine for skills; p99 cloud round-trips are incompatible with collision avoidance and balance.
4. **Data/compute?** Frontier pretraining budgets exceed a companion startup’s fine-tune budget. Fine-tuning still needs on-robot coverage.
5. **Unitree transfer?** Not a weight download. You must redefine actions, collect Go2 demos, and revalidate.
6. **Deterministic safety?** Non-negotiable. A VLA is a proposer inside the same envelope as an LLM planner—stricter, because it may speak fluent motor coordinates.

## Tradeoffs and industry trends

Trend: collapse perception, language, and control into one foundation model. Counter-trend (quiet, necessary): **hierarchical control returns**—foundation models propose, classical stacks dispose. Another trend: “generalist robot policies” trained across embodiments. The risk is average competence everywhere and reliable companionship nowhere.

Design choice for Parcel is not “which VLA wins a leaderboard.” It is “where does a VLA tip enter the architecture without inheriting motor authority?”

```text
good tip-in:   VLA -> skill sketch / waypoint / affordance  -> compiler -> PlanIR
bad tip-in:    VLA -> joint torques / raw Sport bypass
```

## ASCII diagram

```text
  "go wait by the door" + camera tokens
              |
              v
     ┌-------------------------┐
     |  VLA foundation weights |
     |  (OpenVLA / π / ... )   |
     └------------+------------┘
                  |
        proposal: joints OR EE OR tokens
                  |
                  v
     Parcel adapter (must exist)
       - remap to skills / SE2 / vel bounds
       - drop unknown motor dims
                  |
                  v
     PlanIR validate + SafetySupervisor
                  |
         +--------+--------+
         | reject | accept |
         v        v
       speak     nav/skills -> Sport
       clarify
```

## Map to Parcel / Go2

Parcel already has the right skepticism for LLMs. Extend it to VLAs with the same boundaries.

Codebase-relative context:

- Model proposals become `PlanIR` (`brain/contracts.py`) only after `PlanValidator` / compiler (`brain/validator.py`, `brain/compiler.py`)—VLAs tip in here or at grounding (`instructnav/grounding.py`), not at joints.
- `TaskExecutive` (`brain/executive.py`) owns closed-loop skill progress; a VLA must not preempt it via a private motor channel.
- Motion authority remains `CommandArbiter` → reactive/collision gates → `ControlManager` → `UnitreeSportController` (`control/unitree_sport.py`).
- Duplex path (`runtime.py` + `DuplexCoordinator`) already shows how streamed semantics stay off the loco writer; treat VLA tokens like duplex ACT proposals: codec → arbiter, never Sport RPC.

Classification: **shadow** offline agreement with PlanIR; **prototype** semantic grounding into skills; **reject** joint heads on sidewalks; **adopt** only after companion/nav promotion gates—not demo reels.

## Overconfidence story

A prototype wired an open VLA’s action head to “Go2 joint targets” because the README said cross-embodiment. In a living room demo it stacked blocks in simulation footage and then, on hardware, issued a crouch-shaped joint pattern the vendor controller was never meant to receive concurrently. The fall was not mysterious; the architecture violated the HAL. Overconfidence was believing a generalist action tokenizer understood Sport’s contract.

## Retrieval questions

1. List the six Module 6 interrogation questions and answer them briefly for OpenVLA-class systems on a Go2.
2. Why is “language → joints” a worse tip-in than “language → PlanIR skills” for Parcel?
3. (Week-back) From Day 41: what does it mean operationally that a VLA is still an *untrusted* planner?

## Optional 10-minute exercise

Build a comparison matrix cell for Parcel: pick two of {OpenVLA, openpi, Gemini Robotics, GR00T}. Fill observe/act/rate/data/transfer/safety. Classify each as adopt / prototype / shadow / reject for *sidewalk owner-follow* specifically—not for tabletop manipulation.
