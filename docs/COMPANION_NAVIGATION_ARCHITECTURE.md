# Companion navigation and instruction-following architecture

Current production design (aligned with
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md), 2026-08-03).

## Decision

Parcel is not one language model that continuously predicts body velocity. It is
a hierarchical, closed-loop system:

```text
audio/text + scene tracks + task state
  -> IntentFrame router (conversation | skill | PlanIR | clarify)
  -> typed PlanIR / skill proposal
  -> deterministic validator + executive
  -> semantic goal resolver (POI → search → geometry)
  -> grid_v1 navigator (rolling occupancy + A*) or stub fallback
  -> independent collision / social safety gate
  -> bounded VelocityCommand (vx, vy, vyaw) with TTL
  -> ControlManager / LocomotionController
  -> robot state feedback
```

The reasoning model proposes the next **semantic skill** or typed plan and may
explain success criteria. It must not output joint targets or raw motor
commands. The executive may accept, defer, reject, or replace a proposal after
checking task state, perception freshness, battery, and safety.

Useful external patterns (interfaces only — none is a drop-in Parcel controller):

- SayCan / Inner Monologue style affordance + success feedback
- InternVLA-N1 / NaVILA style slow semantic layer above a fast safe controller
- Classical global map / local track / independent safety shield

## What is authoritative today

| Layer | Authority |
| --- | --- |
| Conversation / planning | Shared Gemma profile behind `IntentFrame` + PlanIR |
| Geometric navigation | `active_model: grid_v1` over the occlusion-true raycast scan |
| Collision | Unconditional `collision.py` / `reactive_safety.py` under every source |
| Locomotion | `ControlManager` + vendor `LocomotionController` (Sport or mock) |
| Product nav eval | `evals/companion_nav/` (follow / reacquire / cut-in / doorway / POI) |

Learned visual navigators (CityWalker, NaVILA, NoMaD, ViNT) remain **research
checkpoints only**. Their registry metadata may exist; `build_navigator` fails
closed until a tested inference adapter lands. See
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

## Evaluation policy

**Product gate:** companion-nav scenarios in `evals/companion_nav/` — following
success, hard collisions (no sliding forgiveness), personal-space intrusion,
jerk, and time-to-reacquire.

**Research / offline proxies:** BARN and Habitat adapters under
`evals/external/` measure collision-free metric navigation on non-Go2
abstractions. They are useful for planner stress tests and are **not** the
companion product score. Official leaderboard claims still require the
organizers' stacks and attestation.

Headless city semantic tasks (`tests/test_headless_city_tasks.py` and related)
remain the fast MuJoCo behavior regression gate for sidewalk / lamppost /
owner-orbit predicates.

## Non-goals that stay non-goals

- LLM tokens never cross the motor trust boundary.
- BARN Jackal differential-drive success is not a Go2 companion quality metric.
- MetaUrban / Isaac / SimWorld are optional later backends behind
  `SimulatorBackend`, not imports into the Python 3.14 runtime.
