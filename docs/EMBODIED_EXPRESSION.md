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
| `attentive_nod` | restrained acknowledgement | 1.05 s | sad/happy: calm guardian profile |
| `curious_look` | bounded body lean suggesting curiosity | 1.20 s | explicit/future contextual use only |
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

## Personality mappings

| Personality | sadness | happiness | Intended character |
| --- | --- | --- | --- |
| `gentle_companion` | `comfort_bow` | `paw_wave` | warm and supportive |
| `playful_companion` | `comfort_bow` | `happy_wiggle` | expressive without treating sadness as play |
| `calm_guardian` | `attentive_nod` | `attentive_nod` | restrained acknowledgement |

The language model must select the active personality's exact mapping for an
inferred affect action. It may also choose no action. A neutral/unknown label,
weak confidence, repeated gesture within cooldown, or action that adds little
should result in speech only.

Parcel currently infers only bounded transcript labels (`happy`, `sad`,
`neutral`, `unknown`). Text transcription loses prosody, and no claim is made
that the system reliably recognizes a person's emotional state. A future audio
affect service may propose valence/arousal with provenance and confidence, but
it must remain non-authoritative and separately consented/evaluated.

## Arbitration and interruption

| Robot state | Inferred reaction | Explicit gesture | Trusted system posture |
| --- | --- | --- | --- |
| idle and safe | execute on a control tick | execute | execute if preconditions pass |
| navigating/searching | defer until idle or TTL expiry | defer today | only a safety/task transition may stop navigation |
| following owner | defer | defer | follow controller retains base |
| manual control | defer | defer | manual retains authority |
| recovery/critical phase | defer or expire | defer | recovery retains authority |
| E-stop/hazard | reject and clear | reject and clear | exact stop only |

The current coordinator uses a 20-second proposal TTL, per-gesture cooldown,
deduplication, and a bounded queue. `timing_preference=safe_checkpoint` is a
validated request but does not yet identify an intra-task checkpoint; current
behavior waits for the base activity to finish. That limitation is preferable
to falsely claiming mid-navigation gesture support.

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
targets; Go2 has no tail, ears, or neck articulation; the same motion may be
interpreted differently by different users; inferred text affect is crude; and
no custom trajectory has been proven safe on hardware. The right next step is
controller-owned Sport action commissioning and user evaluation, not increasing
gesture amplitude or letting a model generate joints.
