# Dynamic city, smooth navigation, and social actions

Implementation snapshot: 2026-08-04, with emotion-palette and navigation
safety-ordering corrections audited on 2026-08-09. Living-city simulator and
social-action policy for Parcel. Architecture context:
[REDESIGN_2026_ARCHITECTURE.md](REDESIGN_2026_ARCHITECTURE.md) and
[NAVIGATION_CITY.md](NAVIGATION_CITY.md).

Short version:

1. Keep MuJoCo as the fast, deterministic Go2 development backend.
2. Production-path navigation is `grid_v1` over the raycast scan, with soft
   constant-velocity dynamic-agent costs and independent proximity/TTC gates.
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
- directional obstacle selection plus social collision braking after
  arbitration for every velocity source;
- a per-tick, two-second constant-velocity dynamic-agent cost field in
  `grid_v1`, with a lower owner weight and a separate outgoing-command TTC
  brake;
- deterministic scenario seeds for replay (`simulation.dynamic_city.seed`);
- `--static-city` for controlled A/B tests.

This is a useful functional test world, not a photorealistic crowd simulator.
The people are visible mocap collision proxies, their routes avoid the fixed
street furniture but do not use ORCA with one another, and the Go2 root is
still translated kinematically. The planner predicts published tracks with a
constant-velocity Gaussian cost, but the actors do not perceive or negotiate
with the dog or one another. The scripted gait is now continuous across command
refreshes, but physically credible foot contact still requires a learned
locomotion policy or Isaac/URBAN-SIM.

The dynamic cost is a preference, not a safety mask. `grid_v1` accepts at most
16 validated non-owner tracks plus a separately weighted owner track, scores
only a six-meter window, and replans every tick while the layer is active. A
malformed payload logs a warning and drops the soft layer for that tick. The
universal proximity gate still consumes the simulator's earliest social
contact candidate (which can be the owner), while the later configured TTC
gate recomputes contact for non-owner dynamic tracks against the outgoing
command and can only reduce the command at that gate. The later S-curve shaper
can still leave residual velocity while decelerating, which the 2026-08-09 audit
marks as a P0 ordering defect. Neither dynamic layer models prediction
uncertainty or social intent.

The expression layer is now also live in this backend. A separate 50 Hz channel
publishes bounded body-height/pitch offsets for idle breathing and weight shift;
voice-stage head/gaze state is exposed for UI/metrics. Prosody schedules
speech-accent head-pitch nods, but Go2 has no neck joint, so head yaw/pitch is
timing/telemetry only and does not visibly or physically move the current
embodiment. Locomotion reduces expression to this head-only channel, which
therefore produces no joint overlay on the current Go2; skills, hazards,
critical battery, and E-stop suppress it entirely. This remains a behavioral
preview: no physical support-polygon, torque, thermal, or vendor-Sport
interaction has been validated.

## Simulator research conclusion

### iGibson: use its ideas, not its city backend

[iGibson](https://github.com/StanfordVL/iGibson) is an excellent reference for
task/environment separation, social-navigation metrics, personal space, and
ORCA crowd baselines. Its released worlds are predominantly homes and offices,
and are not a city backend. The actively developed household-task lineage,
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
soft dynamic-agent cost + forward-preferred track / recovery
          ↓
independent proximity/TTC vetoes + jerk-limited hand-off
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

Ordinary point-goal controllers use an explicit forward-preferred state
machine:

```text
ALIGN: vx=0, vy=0, bounded yaw → exit below 7°
TRACK: default point-goal policy uses vy=0; forward speed is tapered by
       heading/distance
       → re-enter ALIGN above 28° (`grid_v1`) or 30° (`stub_v0`)
```

This does not make the quadruped nonholonomic. Body-frame lateral velocity is
supported end to end and remains useful for manual strafing, close repositioning,
recovery, and planners that intentionally request it. It is simply not the
preferred mode for sustained progress toward a particular location. Any lateral
request remains acceleration- and safety-limited like forward motion. Obstacle
avoidance uses the same alignment handoff before translating. Explicit E-stop
uses the stronger manager stop path; ordinary environmental vetoes require the
post-shaper exact-zero correction described above. The simulator preserves gait
phase when the 10 Hz runtime refreshes an otherwise compatible walk command.

The configured speed numbers have different authority. `grid_v1` now requests
up to `0.85 m/s`, the default navigation pipeline caps its output at
`0.45 m/s`, and the wider body-level clamp is `1.0 m/s`. A post-safety S-curve
shaper bounds acceleration and jerk; ordinary environmental vetoes currently
enter its bounded emergency ramp. The current calm
profile is driven by prosody measured from the robot's own synthesized speech,
not by a classifier of the owner's mood. These simulator pacing changes have
not been commissioned on hardware.

For a future physical ROS 2 stack, the recommended local-control composition is
established geometry rather than an LLM:

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
None of these Nav2 components is installed or wired into Parcel today.

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
    "name": "comfort_bow",
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

`timing_preference` and `interruption_request` are validated schema fields but
the current `ActivityCoordinator` does not branch on either value. All admitted
gestures use the same policy: wait until `ActivityContext.busy_reason` is clear,
then start before the 20-second proposal TTL expires. In particular,
`safe_checkpoint` describes the requested policy; it does not yet locate or
preempt at a task checkpoint.

The spoken empathetic reply does not wait for the gesture. Inferred transcript
affect must meet the configured confidence threshold. Whisper transcription
does not preserve prosody; if vocal affect matters later, add a separate audio
affect classifier that emits only a bounded label/confidence. Speech-provider
codec tokens remain inside speech services and never become robot instructions;
Fish is implemented, while Sesame artifacts are a legacy experiment with no
active provider.

There are now two intentionally compatible entry paths:

- ordinary conversation uses `AgentDecision.next_action`, then the
  `ActivityCoordinator` may execute, defer, expire, or reject it; and
- a deliberative physical plan uses the allowlisted PlanIR `Gesture` skill,
  which reaches the same coordinator/runtime checks and verifies completion.

Inline `[emote:name:intensity]` reply tags provide sentence-local timing for
curated emotes. They are stripped before TTS, never become joint instructions,
and cannot make speech fail if the emote is inadmissible. The current intensity
is an admitted semantic parameter and log signal; it is not yet a physically
validated amplitude/tempo transform for every skill.

This dual path keeps chat latency low while preserving complex-plan semantics.
Its cost is duplicated policy surface: the affect-to-action map, PlanIR
contracts, prompt catalog, and runtime allowlist must be changed together. The
tests protect that alignment, but a future unified semantic event envelope
would reduce drift.

## Prompt templates and configuration

Trusted templates live under `prompts/`:

```text
prompts/
├── system/core.md
├── system/action_policy.md
├── system/{planner,planner_sketch,planner_v1,planner_v2}.md
├── dynamic/runtime_context.md.tmpl
├── personalities/{gentle_companion,playful_companion,calm_guardian}.yaml
├── functions/{companion,navigator,spatial_reasoner,manual_assistant,patrol}.yaml
└── schemas/{agent_decision,intent_frame_v1,observation_snapshot_v1,plan_ir_v1,
             plan_sketch_v1,execution_result_v1}.schema.json
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

The current profiles map sadness to the self-returning `comfort_bow` (or the
restrained `attentive_nod` for calm guardian), while happiness maps to
`paw_wave`, `happy_wiggle`, or `attentive_nod`. `play_bow` now means an explicit
invitation to play rather than sadness. If navigation is active, the event
stream shows the gesture deferred until the robot arrives. The added custom
joint trajectories are simulator-only and hardware-unverified; see
[EMBODIED_EXPRESSION.md](EMBODIED_EXPRESSION.md).
