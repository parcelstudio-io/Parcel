# Embodied expression: poses, gestures, and emotion reactions

**Implementation and commissioning note — 2026-08-09.** Parcel now includes a
small, tested simulator body-language palette. The custom joint trajectories
are **not commissioned for physical Go2 hardware**. The physical runtime still
rejects direct pose/trajectory actuation while Unitree Sport owns locomotion.

## Design decision

The dog's body language is a bounded semantic action, not an LLM-generated
joint trajectory. Conversation may propose one allow-listed reaction. The
deterministic activity coordinator decides whether to execute, defer, expire,
or reject it based on the current task and safety state.

Automatic reactions are short trajectories that start and end at neutral
stand. Persistent poses are reserved for explicit owner requests or trusted
system state. This prevents a low-confidence affect inference from leaving the
dog crouched, changing its support state indefinitely, or silently interrupting
navigation.

```text
voice/text + optional bounded affect label
               |
               v
personality maps label -> allow-listed semantic gesture
               |
               v
schema, confidence, cooldown, TTL, activity/safety admission
               |
        execute when idle / defer / expire / reject
               |
               v
sim trajectory today
Unitree-controller-owned action after physical commissioning
```

## Starter palette

### Poses

| Skill | Meaning | Intended use | Current status |
| --- | --- | --- | --- |
| `stand` | neutral readiness | default terminal posture | existing simulator pose |
| `attentive_stand` | alert, listening | explicit posture or future trusted state cue | new; simulator, hardware-unverified |
| `relaxed_crouch` | calm/resting | explicit posture or future idle/energy state | new; simulator, hardware-unverified |
| `sit` | rest/wait | explicit request; future low-battery state after safe stop | existing simulator pose; physical mapping uncommissioned |
| `crouch`, `bow`, `stretch`, `lie_down` | literal posture | explicit command or curated behavior plan | existing simulator poses |

`attentive_stand` and `relaxed_crouch` remain absent from personality affect
maps because they are persistent postures.

### Self-returning gestures

| Skill | Meaning | Duration | Automatic mapping |
| --- | --- | ---: | --- |
| `comfort_bow` | small supportive lowering, distinct from play | 1.45 s | sadness: gentle/playful profiles |
| `happy_wiggle` | short celebratory hind-body weight shift | 0.95 s | happiness: playful profile |
| `excited_paw_taps` | four rapid front-paw bend/return cycles | 0.96 s | explicit strong positive anticipation: all profiles |
| `attentive_nod` | restrained acknowledgement | 1.05 s | sad/happy: calm guardian profile |
| `curious_look` | bounded body lean suggesting curiosity | 1.20 s | explicit/future contextual use only |
| `head_nod` | affirmative forequarter bob | 1.05 s | explicit acknowledgement or optional conversational reaction |
| `head_shake` | lateral whole-body “no” proxy | 0.82 s | explicit negative response or optional conversational reaction |
| `chuckle` | three subtle body bobs; no audio by itself | 0.78 s | clearly humorous conversational moment |
| `shrug` | bounded forequarter uncertainty proxy | 1.05 s | genuine lack of information, never danger dismissal |
| `confused_head_tilt` | sustained asymmetric whole-body tilt proxy | 1.22 s | paired with a necessary clarification |
| `observing_head_tilt` | slow left/right attention proxy | 1.50 s | decorative attention after grounded perception |
| `paw_wave` | greeting or warm acknowledgement | existing | happiness: gentle profile |
| `play_bow` | invitation to play | existing | explicit play context; **not sadness** |

Every new gesture:

- provides all 12 Go2 joint values at every keyframe;
- starts and ends at the profile's neutral stand joints;
- lasts no more than 1.5 seconds;
- stays within 0.30 rad of neutral in the authored joint targets;
- carries `social`, `gesture`, `returns_to_stand`, and
  `hardware_unverified` tags; and
- has an exact runtime-packaged copy so installed builds and source checkouts do
  not silently diverge.

These numeric bounds are packaging/regression bounds, not evidence of physical
stability, motor torque, foot contact, thermal safety, or perceptual meaning.

The four skills whose names contain `head` do not actuate an independent head.
Go2 has no neck joint, and the current skill schema carries only its 12 leg
joints. They are deliberately tagged `head_proxy` and `embodiment_proxy`: the
legs suggest a forequarter/body motion while the rigid head follows the torso.
Likewise, `chuckle` is only a body bounce. An audible chuckle must come from the
ordinary reply/TTS lane.

`excited_paw_taps` is a trajectory even though it may be described casually as
an excited pose. Repetition is finite in the authored keyframes: the front-left
leg bends and returns four times, below the five-cycle ceiling, and the final
frame is neutral stand. It is not a loop and cannot leave the paw raised.

## Personality mappings

| Personality | sadness | happiness | strong anticipation | Intended character |
| --- | --- | --- | --- | --- |
| `gentle_companion` | `comfort_bow` | `paw_wave` | `excited_paw_taps` | warm and supportive |
| `playful_companion` | `comfort_bow` | `happy_wiggle` | `excited_paw_taps` | expressive without treating sadness as play |
| `calm_guardian` | `attentive_nod` | `attentive_nod` | `excited_paw_taps` | normally restrained; clear anticipation remains legible |

The language model must select the active personality's exact mapping for an
inferred affect action. It may also choose no action. A neutral/unknown label,
weak confidence, repeated gesture within cooldown, or action that adds little
should result in speech only.

Parcel currently infers only bounded transcript labels (`excited`, `happy`,
`sad`, `neutral`, `unknown`). `Excited` requires an explicit first-person cue
such as “I'm really excited,” “I can't wait,” or “I'm looking forward to …”; it
is not inferred from an ordinary command or general happiness. Text
transcription loses prosody, and no claim is made that the system reliably
recognizes a person's emotional state. A future audio affect service may
propose valence/arousal with provenance and confidence, but it must remain
non-authoritative and separately consented/evaluated.

## Arbitration and interruption

| Robot state | Personality affect | Conversation reaction | Explicit gesture | Trusted system posture |
| --- | --- | --- | --- | --- |
| idle and safe | execute on a control tick | execute with 2 s TTL | execute | execute if preconditions pass |
| navigating/searching | defer until idle or TTL expiry | skip immediately | defer today | only a safety/task transition may stop navigation |
| following owner | defer | skip | defer | follow controller retains base |
| manual control | defer | skip | defer | manual retains authority |
| recovery/critical phase | defer or expire | skip | defer | recovery retains authority |
| E-stop/hazard | reject and clear | reject | reject and clear | exact stop only |

The current coordinator uses a 20-second proposal TTL, per-gesture cooldown,
deduplication, and a bounded queue. `timing_preference=safe_checkpoint` is a
validated request but does not yet identify an intra-task checkpoint; current
behavior waits for the base activity to finish. That limitation is preferable
to falsely claiming mid-navigation gesture support.

Contextual reactions use `trigger=conversation_reaction`, `when_safe`, and no
interruption request. They are not new owner-affect labels: “confused,”
“observing,” and “amused” describe Parcel's discourse choice, not a diagnosis of
the owner. A busy body drops them rather than replaying a stale chuckle or tilt
after a task. Explicit phrases such as “nod your head,” “shake your head no,”
“shrug,” and “look curious” still enter the reviewed explicit-command path and
may wait for the current task under the existing policy.

The spoken response is independent: “I'm here with you” may stream immediately
while the gesture is deferred or omitted. The dog should not narrate a gesture
as completed until its execution result says it completed.

## Two expression channels must stay distinct

Parcel already has a subordinate 50 Hz expression layer for small additive
idle/prosody offsets and an attention/audio social-reaction bridge. On Go2,
head-yaw/head-pitch state is largely timing/telemetry because the embodiment has
no articulated neck. This channel may overlap locomotion only inside its
strictly clamped, controller-approved envelope.

The new whole-body gesture trajectories are different: they acquire physical
activity, serialize with base motion, stop the velocity path, and run only when
the coordinator admits them. Do not relabel a posture/base trajectory as a
head-only overlay to bypass arbitration.

## Configurable playback speed

Every catalog pose and trajectory has a normalized `speed` setting in `[0, 1]`.
It is optional in skill YAML and defaults to `1.0`:

```yaml
id: head_nod
kind: trajectory
speed: 0.6
```

Trusted callers can override that default for one execution with
`dog.execute("head_nod", speed=0.4)`. The simulator pose-review gallery exposes
the same control as a global slider and snapshots its value at the start of an
autoplay sequence. The gallery honors each YAML default until the operator
turns off **Use each skill's catalog speed** and applies the global slider.

This value is a bounded style control, not raw motor velocity. `1` preserves
the authored timing; `0` selects the slowest safe playback. The rate is
`floor + speed * (1 - floor)`, where the floor is at least `0.25` and rises when
needed to keep the command inside the 10-second pose or 30-second trajectory
limit. Stop remains the explicit way to halt motion.

For poses, speed changes only the transition time into the target posture; the
posture remains held until another command or reset. For trajectories, every
keyframe timestamp is retimed. Joint angles, amplitude, keyframe order,
repetition count, and return-to-stand frames never change. The executor returns
the requested speed, effective rate, and effective duration so the activity
scheduler and UI use the same timing authority.

Model-produced affect `intensity` remains separate from playback speed. The LLM
does not receive direct timing authority; personality/behavior selection stays
semantic, while YAML and trusted operator calls own tempo. Physical Unitree
execution continues to fail closed until each controller-owned action has a
commissioned playback-rate envelope.

## Physical Go2 implementation

The first hardware implementation should map meanings to Unitree Sport's
controller-owned actions where appropriate:

| Parcel meaning | Candidate Sport action | Required evidence before enablement |
| --- | --- | --- |
| sit / rise | `Sit` / `RiseSit` | exact model/firmware support, completion feedback, abort/recovery test |
| greeting / paw wave | `Hello` | clearance, support/contact, timeout, cancel and recovery tests |
| stretch | `Stretch` | clearance envelope, duration, cancel and recovery tests |
| bounded lean/nod | carefully bounded `Euler` if supported | measured axes/signs, stability envelope, return-to-neutral and stop behavior |
| stand/recovery | `BalanceStand`, `StandUp`, `RecoveryStand` | state transitions and feedback witness |

This should be exposed as a typed whole-body action interface owned by the
selected locomotion controller—not as raw `LowCmd` from the voice or skill
layer. Never publish raw joint commands while Sport mode is active.

A physical action adapter needs:

- capability discovery tied to robot model, SDK, firmware, and mode;
- explicit preconditions: stationary body, sufficient clearance, acceptable
  tilt/contact/battery/thermal state, and no hazard;
- bounded call and completion deadlines plus fresh state feedback;
- cancellation semantics that return control to a stable Sport state;
- an abort path to exact stop/recovery, and exclusive authority with Move;
- per-action swept-clearance zones, including space for the raised paw/body;
- hardware-in-the-loop traces followed by fenced low-speed commissioning; and
- an allowlist that stays disabled by default until each action passes.

Custom trajectories should remain simulator-only until a future whole-body
controller owns balance/contact constraints and implements the same lifecycle.

## Evaluation

Unit tests currently prove catalog/runtime parity, joint completeness, bounded
authored deltas, return-to-stand, duration limits, and valid personality maps.
They do not prove that a gesture is safe or emotionally legible.

For human visual review in the source checkout:

```bash
./scripts/launch_pose_review.sh
```

The launcher reuses the normal MuJoCo/panel lifecycle and opens the
simulator-only `/poses` gallery. It automatically runs the complete catalog
after a three-second countdown; pass `--manual` to inspect motions individually.
Watch the native MuJoCo window; the browser's city viewer intentionally omits
articulated robot geometry. Stop and page-close request neutral stand. The
gallery API is disabled in ordinary panel sessions, rejects gait/velocity/
policy skills, and refuses every non-MuJoCo backend. This is a commissioning
aid, not physical-safety evidence.

Desktop smoke evidence on 2026-08-09: the earlier gallery run loaded 24 bounded
catalog motions, dispatched `excited_paw_taps` through the live MuJoCo socket, restored
standing joints through Stop, and cleaned up its panel process and Unix socket.
The host emitted non-fatal Wayland window-position and OpenGL context warnings;
the simulator, HTTP gallery, trajectory dispatch, and reset remained functional.

Follow-up smoke evidence on the same desktop: the expanded gallery exposed 30
bounded motions and dispatched `head_shake`, `head_nod`, `chuckle`, `shrug`,
`confused_head_tilt`, and `observing_head_tilt` through the live MuJoCo socket.
The final Stop restored neutral, and shutdown removed the isolated port/socket.

Promotion requires three additional tiers:

1. **Simulation:** no self-collision, contact loss, base displacement, obstacle
   contact, or residual posture error across initial stance/terrain variants.
2. **Hardware:** state transition, tilt/contact, current/temperature, swept
   clearance, completion/cancel latency, and recovery under fenced HIL trials.
3. **Human interpretation:** blinded studies across users and contexts measuring
   intended-label agreement, comfort, repetition annoyance, cultural variance,
   and whether speech plus gesture feels congruent.

Useful research supports a cautious design rather than universal semantics:
quadruped proxemics and zoomorphic gesture studies show that body motion and
distance affect social interpretation, while robot-posture studies find that
small idle/posture cues can communicate affect. Meaning remains contextual and
must be tested with Parcel's exact body, voice, timing, and users.

## Implementation locations

- source skills: `configs/skills/poses/` and `configs/skills/trajectories/`;
- packaged skills: `src/parcel_robot/runtime_assets/configs/skills/`;
- personality maps: `prompts/personalities/` and packaged mirrors;
- semantic output policy: `prompts/system/action_policy.md`;
- reviewed natural-language aliases: `src/parcel_robot/brain/router.py`;
- queue/arbitration: `src/parcel_robot/core/activities.py`;
- physical rejection boundary: `RobotRuntime._run_pose` and
  `RobotRuntime._run_trajectory`;
- regression contract: `tests/test_emotion_gesture_library.py`.

## Research references

- Unitree's official [Go2 Sport client API](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp).
- [Reactive Robot Dog](https://arxiv.org/abs/2512.17136), a recent study of
  generated quadruped gestures; useful as research evidence, not production
  validation for Parcel.
- [Quadruped Robot Proxemics](https://arxiv.org/abs/2302.10729).
- [Emotion Expression through Posture and Idle Motion](https://arxiv.org/abs/2209.00983).
- [Zoomorphic Gestures for Communicating Cobot States](https://arxiv.org/abs/2102.10825).

## Advantages and limitations

The palette makes reactions semantically clearer, corrects the old mistake of
using a playful bow for sadness, returns automatic reactions to neutral, and
preserves the current safety/activity boundary. It also gives each personality
a distinct but bounded physical vocabulary.

Its limitations are equally important: these are hand-authored simulator joint
targets; neither the rapid paw taps nor the new body proxies have physical
balance/contact evidence; Go2 has no tail, ears, or neck articulation; the same
motion may be interpreted differently by different users; inferred text affect
is crude; and no custom
trajectory has been proven safe on hardware. The right next step is
controller-owned Sport action commissioning and user evaluation, not
increasing gesture amplitude or letting a model generate joints.
