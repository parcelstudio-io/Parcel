# Dynamic city, smooth navigation, and social actions

Living-city simulator and social-action policy for Parcel. Architecture context:
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) and
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

Short version:

1. Keep MuJoCo as the fast, deterministic Go2 development backend.
2. Production navigation is `grid_v1` over the raycast scan (not the stub).
3. Add MetaUrban as the first procedural SocialNav service (separate process).
4. Add URBAN-SIM/Isaac Lab when articulated Go2 training is the priority.
5. Treat the reasoning model as a semantic action proposer, never a motor
   controller.

## What now works in the default MuJoCo launch

`city_block.xml` is now a small living-city regression scene rather than a
static block. It contains seven pedestrians, one cyclist, opposing sidewalk
traffic, crosswalk traffic, a plaza loop, street furniture, storefronts, lane
markings, and a manually movable owner. `DynamicCity` advances seeded routes
and publishes every actor's position, velocity, radius, and heading.

The simulator and browser panel now expose:

- all mapped dynamic tracks and the current safety-focus actor's range/bearing;
- true first-contact time-to-collision across pedestrians, cyclists, and owner;
- personal-space rings and velocity vectors on the top-down map;
- directional obstacle selection plus social collision braking shared by manual,
  follow, and navigation sources;
- deterministic scenario seeds for replay (`simulation.dynamic_city.seed`);
- `--static-city` for controlled A/B tests.

This is a useful functional test world, not a photorealistic crowd simulator.
The people are visible mocap collision proxies, their routes avoid the fixed
street furniture but do not yet use ORCA with one another, and the Go2 root is
still translated kinematically. The scripted gait is
now continuous across command refreshes, but physically credible foot contact
still requires a learned locomotion policy or Isaac/URBAN-SIM.

## Simulator research conclusion

### iGibson: use its ideas, not its city backend

[iGibson](https://github.com/StanfordVL/iGibson) is an excellent reference for
task/environment separation, social-navigation metrics, personal space, and
ORCA crowd baselines. Its released worlds are predominantly homes and offices,
and its latest GitHub release is from 2023. Its active successor,
[BEHAVIOR-1K/OmniGibson](https://github.com/StanfordVL/BEHAVIOR-1K), is based on
Isaac Sim and remains household-interaction focused. Neither is the best new
foundation for a city dog.

### Recommended backend order

| Backend | Best use | Why | Integration caveat |
| --- | --- | --- | --- |
| [MetaUrban](https://github.com/metadriverse/metaurban) | First procedural city/SocialNav backend | Urban blocks, pedestrians, vehicles, ORCA routes, RGB/depth/semantic/LiDAR, Gym interface, permissive code | Separate Conda Python 3.9 service; full assets require registration; its default embodiment is not authoritative Go2 joint physics |
| [URBAN-SIM](https://github.com/metadriverse/urban-sim) | Long-term articulated Go2 city training | Isaac Sim/Lab, explicit Go2 support, procedural dynamic cities and high-throughput RL | Official host targets Ubuntu 22.04/24.04 and substantial GPU/storage; use a pinned 24.04 container on this Ubuntu 26.04 workstation |
| [SimWorld](https://github.com/SimWorld-AI/SimWorld) | Game-like, photorealistic demos | Unreal Engine 5, procedural cities, traffic, pedestrians, custom agent import | Importing a sensorized, physically controlled Go2 is significant Unreal work |
| MuJoCo Parcel scene | Daily tests and skills | Fast startup, official Go2 model, deterministic and low GPU use | Compact scene and kinematic root |

[Habitat 3.0](https://aihabitat.org/habitat3/) is also a strong reference for
owner following and humanoid collaboration, but its benchmark scenes are
indoors. CARLA is useful if vehicle traffic becomes the main research problem,
but is vehicle-first rather than quadruped-first.

On this RTX 5000 Ada (32 GB), MetaUrban is the most practical next process.
URBAN-SIM and Fish S2 should use separate launch profiles: Fish has already
measured near 22 GB VRAM in this setup, leaving too little margin for a rich
Isaac workload.

The engine boundary should remain:

```text
semantic mission / personality
          ↓
grid_v1 (rolling occupancy + A*) or stub fallback
          ↓
forward-preferred track / recovery + independent safety veto
          ↓
bounded vx/vy/vyaw → ControlManager
          ↓
SimulatorBackend
  ├── MuJoCo (working)
  ├── MetaUrban service (next)
  ├── URBAN-SIM service (later)
  └── SimWorld client (visual demo profile)
```

Only one process is authoritative for the world at a time. MetaUrban should run
in its own Python 3.9 process and communicate over versioned IPC rather than be
imported into Parcel's Python 3.14 threaded runtime.

## Smooth navigation decision

The old stub always retained at least 15% forward speed, even with a large
heading error. That produced the visible diagonal slide. It now uses an
explicit forward-preferred state machine for ordinary point goals:

```text
ALIGN: vx=0, vy=0, bounded yaw → exit below 7°
TRACK: default point-goal policy uses vy=0; forward speed is tapered by
       heading/distance
       → re-enter ALIGN above 30°
```

This does not make the quadruped nonholonomic. Body-frame lateral velocity is
supported end to end and remains useful for manual strafing, close repositioning,
recovery, and planners that intentionally request it. It is simply not the
preferred mode for sustained progress toward a particular location. Any lateral
request remains acceleration- and safety-limited like forward motion. Obstacle
avoidance uses the same alignment handoff before translating. Safety/E-stop can
still force translation to zero immediately. The simulator also preserves gait
phase when the 10 Hz runtime refreshes an otherwise compatible walk command.

For the physical ROS 2 stack, use established local control rather than an LLM:

```text
Nav2 Smac State Lattice
    → Rotation Shim
    → MPPI (forward-preferred profile for ordinary point goals)
    → Velocity Smoother
    → Collision Monitor
    → Go2 locomotion controller
```

The [Nav2 Rotation Shim](https://docs.nav2.org/tutorials/docs/using_shim_controller.html)
exists specifically to rotate into the path heading before handing off to a
controller. [Regulated Pure Pursuit](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html)
is the simpler exact path follower and includes rotate-to-heading behavior.
[MPPI](https://docs.nav2.org/configuration/packages/configuring-mppic.html) is
the stronger later choice for locally deviating around dynamic occupancy. A
pedestrian prediction layer is still needed for time-indexed crowd motion.

## Where learned navigation belongs

Production path is classical geometry (`grid_v1`) under an independent collision
gate. CityWalker / NoMaD / ViNT / NaVILA remain research checkpoints: YAML
metadata and downloads may exist, but `build_navigator` fails closed until a
tested inference adapter lands. Any future learned proposer may emit waypoints
or mid-level motion only; it must not replace heading alignment, collision
monitoring, the velocity arbiter, or leg control. See
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

## Reasoning model and next-action policy

Gemma should output a spoken reply plus an optional **semantic action proposal**,
not the next velocity tick. The strict result allows one bounded skill:

```json
{
  "reply": "I'm here with you.",
  "tool_calls": [],
  "intent": "conversation",
  "affect": {"label": "sad", "confidence": 0.86},
  "next_action": {
    "kind": "skill",
    "name": "play_bow",
    "trigger": "inferred_affect",
    "timing_preference": "when_safe",
    "interruption_request": "none",
    "reason": "gentle acknowledgement"
  }
}
```

There is deliberately no `force` field, numeric priority, joint target, or raw
velocity. Unknown fields fail closed. Inferred affect must map exactly to the
active personality's allow-listed social trajectory. The deterministic
`ActivityCoordinator` rechecks current state after model inference and chooses
execute, defer, expire, or reject; dispatch is serialized with Stop, manual,
navigation, follow, and E-stop authority changes.

| Current work | Inferred emotion gesture | Explicit gesture | Emergency/manual |
| --- | --- | --- | --- |
| Idle and safe | Execute on control tick | Execute on control tick | Preempt |
| Navigation | Defer until arrival or expiry | Defer; safe checkpoints are future work | Preempt |
| Owner follow | Defer | Defer | Preempt |
| Manual control | Defer | Defer | Manual retains motion lease |
| E-stop | Reject and clear queue | Reject and clear queue | Operator must clear latch |

The spoken empathetic reply does not wait for the gesture. Inferred transcript
affect must meet the configured confidence threshold. Whisper transcription
does not preserve prosody; if vocal affect matters later, add a separate audio
affect classifier that emits only a bounded label/confidence. Fish/Sesame audio
codec tokens remain inside speech services and never become robot instructions.

## Prompt templates and configuration

Trusted templates live under `prompts/`:

```text
prompts/
├── system/core.md
├── system/action_policy.md
├── dynamic/runtime_context.md.tmpl
├── personalities/{gentle_companion,playful_companion,calm_guardian}.yaml
├── functions/{companion,navigator,manual_assistant,patrol}.yaml
└── schemas/agent_decision.schema.json
```

The UI selects profile IDs only; it never accepts arbitrary system prompt text.
The dynamic template receives a small JSON snapshot of current activity,
motion source, freshness/proximity state, and allowed social skills. Event logs,
chat history dumps, and arbitrary instructions are excluded from that system
context.

Useful configuration:

```yaml
simulation:
  dynamic_city:
    enabled: true
    seed: 7
    speed_scale: 1.0

agent:
  prompts_root: prompts
  personality: gentle_companion
  functions: [companion, navigator, manual_assistant]
  affect:
    minimum_confidence: 0.75
    social_action_cooldown_s: 8
    proposal_ttl_s: 20
```

Try `I am feeling sad` (queues `play_bow`) or `I am very happy` (queues
`paw_wave`, which lifts a leg and returns to stand). If navigation is active,
the event stream shows the gesture deferred until the robot arrives.
