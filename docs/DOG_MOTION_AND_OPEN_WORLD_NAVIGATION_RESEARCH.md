# Dog-like motion and open-world semantic navigation

Research and repository-specific design, 2026-08-02.

## Executive decision

Parcel should use two independent hierarchies:

```text
semantic mission                         desired body velocity / skill
  -> known-map lookup                    -> learned, phase-aware locomotion policy
  -> open-vocabulary semantic lookup     -> joint targets at 50-100+ Hz
  -> active visual search                -> PD/impedance control on the robot
  -> safe goal/approach-pose planner
  -> Nav2/local planner/safety veto
```

An animator can provide valuable dog motion, but an FBX/BVH animation must not be
played directly on hardware. It is a reference that is retargeted to Go2's
12-DoF morphology, made contact- and dynamically feasible, and tracked by a
physics-trained policy. Likewise, the voice model should choose semantic goals,
not pixels, map cells, velocities, or joints.

For navigation, replace the mandatory `POI -> GoalPose` assumption with a goal
resolver that tries: (1) known POIs, (2) a queryable semantic map, and (3) an
active look/search behavior. A sidewalk is a region or traversability affordance,
not an object instance, so dense semantic grounding and geometry are required.

## What Parcel actually does today

### Motion

- `ScriptedTrotGait` in `src/parcel_robot/gait.py` is a sinusoidal, open-loop
  diagonal-pair animation. It has no foot-contact state, inverse kinematics,
  balance feedback, ground adaptation, body/head secondary motion, or learned
  transition model.
- `parcel-sim` applies those joint targets while translating the root
  kinematically. This explains both the sliding look and why making the joint
  curves prettier cannot establish physical credibility.
- Velocity acceleration limiting exists at the runtime layer, which is useful,
  but a 10 Hz semantic/control refresh is not a leg controller.
- `RLPolicyBackend` can load ONNX/TorchScript, but Parcel does not yet own the
  real-time observation-to-joint-action loop required to deploy it.

### Navigation and prompt context

- `PlaceGrounder.ground()` in `src/parcel_robot/navigation/grounder.py` only
  scores YAML strings and raises `LookupError` when no POI matches.
- `Mission` requires a concrete `GoalPose`; there is no unresolved semantic
  goal, candidate set, search state, or confidence/provenance representation.
- `NavObservation.rgb` and `lidar` exist but runtime `Dog.navigate()` does not
  populate them. Perception currently describes a contract; map context is a
  deliberately disabled placeholder.
- The prompt already has the correct insertion boundary:
  `PromptLibrary.render_system()` serializes a bounded runtime dictionary into
  `runtime_context.md.tmpl`. Extend this structured snapshot instead of adding
  arbitrary prompt strings.

## 1. Making motion look and react like a dog

### Recommended production path: animator reference -> retarget -> tracking policy

The animator workflow is viable and has strong research precedent. Animal
motion has been retargeted across morphology and then tracked with reinforcement
learning on real quadrupeds. STMR explicitly separates spatial feasibility from
temporal/dynamic feasibility and validates complex animal motion on two robot
morphologies ([paper](https://arxiv.org/abs/2404.11557)). Work on biological-dog
skills similarly retargets dog capture into robot references and preserves the
motion style in a reusable low-level latent controller
([paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10780440/)). Recent lifelike
quadruped work reports raw BVH clips and retargeted trajectories
([paper](https://www.nature.com/articles/s42256-024-00861-3)).

Ask the animator for:

- A quadruped skeleton with named root/pelvis, spine/chest/head, and four
  hip-knee-ankle/paw chains; consistent axes, meters, and a documented bind pose.
- FBX or BVH plus a 30/60 fps preview. Preserve root translation/orientation,
  paw trajectories, gait phase, and explicit contact annotations. Export looped
  walk/trot/run clips with clean cycle boundaries and non-looping transitions:
  stand-to-walk, walk-to-stop, turns, speed changes, sit/lie/rise, head looks,
  recoil/startle, and recovery.
- Several speeds and turn radii. A single fixed-speed loop cannot produce smooth
  command response.
- Motion intent metadata: gait, nominal speed, phase, contacting paws, loop
  interval, and permissible time scaling. The render mesh and ornamental tail
  are irrelevant to Go2 control; body and paw motion are the useful signal.

Build an offline importer with a canonical, versioned format such as NPZ:

```text
fps, time
root_position[N,3], root_quaternion[N,4]
canonical_keypoints[N,K,3]
go2_joint_position[N,12]
go2_foot_position[N,4,3]
foot_contact[N,4]
source_clip, retarget_version, scale, quality_metrics
```

The importer should read FBX/BVH through Blender/Maya offline, normalize axes and
scale, resample, detect/accept paw contacts, and solve constrained retargeting.
Optimize root and Go2 joints against body/paw keypoints while enforcing joint
limits, paw-contact velocity, ground penetration, self-collision, and smooth
velocity/acceleration. A physics pass should allow time warping and reject
untrackable clips. Direct Euler-angle bone copying will fail because dog and Go2
link proportions, joint axes, joint count, mass, and torque limits differ.

Train a phase-conditioned tracking policy in MuJoCo/mjlab or Isaac Lab. Reward
root pose/velocity, joint pose/velocity, end-effector position, and contact
timing, while penalizing slip, impact, torque/energy, joint-limit proximity, and
action jerk. Randomize friction, latency, sensor noise, payload, motor strength,
terrain, and external pushes. Include command tracking so the result can vary
speed and yaw rather than replay one clip. NVIDIA's documented quadruped workflow
uses state, desired velocity and previous action, with friction/mass/push
randomization for sim-to-real transfer
([Isaac Lab example](https://developer.nvidia.com/blog/closing-the-sim-to-real-gap-training-spot-quadruped-locomotion-with-nvidia-isaac-lab/)).

For Parcel's Go2 and existing MuJoCo direction, the lowest-friction starting
point is Unitree's official `unitree_rl_mjlab`, which already lists a Go2
velocity task and ONNX export/deployment flow. Its published motion-imitation
task is currently shown for G1, so a Go2 tracking environment still needs to be
implemented rather than assumed
([repository](https://github.com/unitreerobotics/unitree_rl_mjlab)). Isaac Lab is
the heavier alternative when GPU-parallel domain randomization and richer sensor
simulation become more important
([official overview](https://developer.nvidia.com/isaac/lab)).

### Naturalness is more than imitation

A dog-like controller needs continuous style and transitions:

- Condition on desired `vx`, `vy`, `yaw_rate`, gait/style, body height, step
  frequency, foot clearance, and phase/contact schedule.
- Use speed-dependent gait selection (walk at low speed, trot in the middle,
  run/bound only where safe), with hysteresis so it does not chatter.
- Blend command/style embeddings over time, but let contact-aware logic finish a
  planted step before changing phase. Smooth joint actions and rate-limit the
  high-level commands independently.
- Train recovery and perturbation response, not just nominal loops. Reactions
  should first preserve balance, then express character through head/body poses.
- Layer non-locomotor animation only where the hardware supports it. Go2 has no
  articulated neck, spine, or tail, so recognizable dog character must come
  from base pitch/roll/height, stance width, foot placement, cadence, pauses,
  and gaze direction—not impossible bone motion.

`Walk These Ways` is a useful open reference for a single policy with selectable
cadence, footswing, posture and gait families, plus robustness to pushes
([project](https://gmargo11.github.io/walk-these-ways/)). It is a better model
for interactive smoothness than one policy per animation clip.

### Fast visual improvement before a learned policy

For simulator presentation only, replace `ScriptedTrotGait` with a contact-state
gait generator:

1. Maintain one phase oscillator and explicit stance/swing state per foot.
2. Plan stance feet stationary in world coordinates; use cubic/Bezier swing-foot
   arcs with zero endpoint velocity and speed-scaled clearance.
3. Solve per-leg inverse kinematics to Go2 joints.
4. Add body bob/pitch/roll from phase and measured/estimated support polygon.
5. Cross-fade velocity, cadence, stride and turn parameters without resetting
   phase; transition to stand only after a stable support pattern.
6. Stop kinematically teleporting the root when evaluating realism. Let contacts
   move the body, or clearly retain this as preview-only mode.

This will look substantially better, but it is not a deployable balance
controller. Keep `preview_gait` and `learned_locomotion` as explicit backends.

### Motion acceptance criteria

- No visible foot sliding during stance in physics playback; report stance-foot
  RMS velocity and penetration, not only a video judgment.
- Track commanded velocity and yaw across a matrix of speeds and turns; measure
  error, falls, torque, energy, and action jerk.
- Start/stop/turn/style changes do not reset phase or cause discontinuous joint
  targets.
- Survive randomized friction, latency, payload, slopes, sensor noise, and
  bounded pushes before hardware shadow mode.
- Hardware rollout progresses suspended -> safety tether/clear pen -> bounded
  speeds, with watchdog, joint/torque limits, fall detection, and Sport controller
  mutually exclusive with low-level policy control.

## 2. Navigating to things that are not known POIs

### Use a semantic-goal lifecycle

Replace the current one-step grounding contract with:

```text
directive
  -> SemanticGoal(query="sidewalk", relation="on/inside", constraints=...)
  -> resolve known POI (optional fast path)
  -> query local semantic map
  -> if unresolved: ACTIVE_SEARCH
       rotate/scan -> detect/segment -> depth/LiDAR project -> fuse observations
       -> rank stable candidates -> plan next viewpoint/frontier -> repeat
  -> choose safe approach/inside pose
  -> route + local collision/social planner
  -> VERIFY at arrival; replan or fail with reason
```

The goal types should include `KnownPoseGoal`, `SemanticRegionGoal`,
`SemanticObjectGoal`, and `RelativeGoal`. `Mission` should carry resolution
status, candidate IDs, confidence, observation count, source/provenance,
`last_seen_at`, timeout/search budget, and a verification rule. A target becomes
actionable only after deterministic thresholds (for example, confidence plus
multi-view support plus reachable geometry), never because the LLM said it
exists.

For a sidewalk specifically:

1. Parse `move/go to the sidewalk` as `SemanticRegionGoal("sidewalk",
   terminal_relation="inside")`.
2. Rotate through bounded viewpoints while the low-level safety monitor remains
   active.
3. Produce a sidewalk mask, fuse depth/LiDAR points into the local map, reject
   road/curb/obstacle cells, and require temporal/multi-view agreement.
4. Erode the region by robot footprint plus clearance; select a reachable
   interior cell or boundary entry pose, not the mask centroid blindly.
5. Plan to it, then verify that the robot footprint lies on the detected region.
6. If no confident candidate is visible, select a safe semantic/frontier
   viewpoint under a time/distance budget. Stop and report `not_found`,
   `ambiguous`, `unreachable`, or `perception_unavailable`; never invent a POI.

### Perception/map recommendation

Start with two complementary channels:

- A safety/traversability channel built from LiDAR/depth and conservative fixed
  classes. This is authoritative for obstacles and where the body may move.
- An open-vocabulary semantic channel for language matching. It proposes regions
  and landmarks but cannot remove obstacles from the safety costmap.

VLMaps is the closest direct architectural reference: it fuses visual-language
features into geometric maps, supports natural-language and spatial queries,
and can construct open-vocabulary obstacle maps
([project](https://vlmaps.github.io/), [code](https://github.com/vlmaps/vlmaps)).
ConceptGraphs is attractive later for compact object-centric memory and
relationships, but a sidewalk is better represented as a dense region than an
object node ([project](https://concept-graphs.github.io/)). OpenMask3D is useful
for novel object instances, not the primary sidewalk solution
([project](https://openmask3d.github.io/)).

For the earliest end-to-end sidewalk proof, a closed-set segmentation model is
acceptable and easier to validate; Nav2 publishes an example whose classes are
sidewalk, grass and background and feeds semantic output into navigation
([tutorial](https://docs.nav2.org/tutorials/docs/navigation2_with_semantic_segmentation.html)).
Then add open-vocabulary dense features for new language concepts. On a mapped
outdoor site, map hints may query OpenStreetMap, where separately mapped
sidewalks commonly use `highway=footway` plus `footway=sidewalk`
([OSM tagging](https://wiki.openstreetmap.org/wiki/Tag%3Afootway%3Dsidewalk)).
Map data is a prior and routing aid; camera/geometry still verifies the local
surface and temporary hazards.

### Query Context Service and feature-gated prompt context

Create a `QueryContextService` that returns a typed `ContextSnapshot`, not prose:

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-02T14:30:00Z",
  "location": {
    "enabled": true,
    "source": "localization",
    "latitude": 40.0,
    "longitude": -74.0,
    "accuracy_m": 2.1,
    "age_ms": 80
  },
  "time": {
    "enabled": true,
    "source": "system_clock",
    "local_iso": "2026-08-02T10:30:00-04:00",
    "timezone": "America/New_York"
  },
  "map": {
    "enabled": false
  },
  "scene": {
    "enabled": true,
    "summary": {
      "visible_semantic_labels": ["road", "sidewalk", "crosswalk"],
      "target_candidates": []
    },
    "observed_at": "2026-08-02T14:29:59Z"
  }
}
```

Recommended configuration:

```yaml
query_context:
  enabled: false
  timeout_ms: 150
  max_age_s: 2.0
  enable_location_context: false
  enable_time_context: false
  enable_map_context: false
  enable_scene_context: false
  include_precise_coordinates_in_prompt: false
```

Apply gating twice:

1. **Acquisition gate:** a disabled provider is not queried at all. This avoids
   privacy leakage, network work, latency, and accidental dependence.
2. **Serialization gate:** even cached fields are omitted from the voice prompt
   unless their flag is enabled. Test absence, not merely `enabled:false`.

The service should gather providers concurrently under one deadline, validate
schemas and finite/ranged coordinates, attach timestamp/accuracy/source, cache
with per-provider TTL, and return partial data plus structured errors. A slow
weather/map provider must not block speech. Time should use the configured local
timezone; location should default to a coarse human-readable area in the prompt,
with exact coordinates reserved for deterministic navigation components.

Wire it in two places with different projections:

- `RobotRuntime._prompt_runtime_context()`: add a compact `query_context` object
  only for enabled voice-agent fields. It helps interpret phrases like “the
  shaded sidewalk” or “the entrance open now.”
- semantic goal resolver: receive the full typed snapshot as data for map query,
  candidate ranking and search priors. This is the path that actually enables
  navigation. Prompt enrichment alone cannot make the robot perceive a sidewalk.

External map/place text must be treated as untrusted data, length-limited and
reduced to allow-listed fields; never concatenate retrieved descriptions into
system instructions. NIST describes agent hijacking through malicious
instructions embedded in ingested data
([NIST](https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations)),
and OWASP notes that RAG does not eliminate prompt injection
([OWASP](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)). Tool outputs
remain proposals; existing safety, authority and schema validation stay outside
the model.

### Suggested repository shape

```text
src/parcel_robot/context/
  models.py                 # typed snapshot and provenance
  service.py                # deadlines, cache, feature gates
  providers/{clock,localization,map,scene}.py
src/parcel_robot/navigation/
  goals.py                  # semantic and resolved goal variants
  semantic_map.py           # query interface + candidates
  search.py                 # bounded scan/frontier state machine
  goal_resolver.py          # POI -> semantic map -> active search
  approach.py               # mask/point cloud -> safe goal pose
```

Keep `PlaceGrounder` as the known-POI fast path. Do not silently broaden it to
return guessed coordinates.

### Navigation acceptance tests

- With all context flags false, no provider is called and no location/time/map/
  scene keys appear in the rendered prompt.
- Each flag independently adds only its field; timeout/stale/malformed provider
  data degrades to an explicit unavailable state without blocking a voice turn.
- Exact location is absent from the prompt unless its separate privacy flag is
  enabled, while the deterministic resolver can still use authorized location.
- With an empty POI catalog and a sidewalk visible in two views, the mission
  transitions `UNRESOLVED -> SEARCHING -> RESOLVED -> NAVIGATING -> VERIFYING ->
  ARRIVED` and finishes inside the safe mask.
- A one-frame false detection does not initiate translation. Ambiguous or
  unreachable candidates produce a bounded scan/replan and then a reasoned
  failure.
- Loss of camera/localization, stale telemetry, person intrusion, or E-stop
  immediately prevents/halts motion independently of model output.
- Retrieved labels containing instruction-like text remain quoted data and
  cannot add tools, change authority, or alter safety limits.

## Implementation order

1. **Make the contracts honest:** add semantic goal/candidate/search types and a
   fake semantic-map provider; remove POI-only assumptions without adding a VLM.
2. **Add context safely:** implement `QueryContextService`, all flags default-off,
   prompt projection, provider timeouts/provenance, and absence/privacy tests.
3. **Prove sidewalk behavior in simulation:** use simulator semantic ground
   truth only as a test provider, exercise scan/resolution/approach/verification,
   and keep diagnostics clearly separated from production perception.
4. **Add real perception:** fixed sidewalk segmentation + depth/LiDAR fusion
   first; open-vocabulary VLMap next; map hints after localization is reliable.
5. **Improve visual gait:** contact phases, swing trajectories and IK while the
   physics-trained policy is developed separately.
6. **Animator pilot:** commission a small clip pack, build the canonical importer
   and retarget-quality report, then train one command-conditioned walk/trot
   policy before expanding expressive skills.
7. **Deploy progressively:** shadow semantic candidates and policy outputs,
   regression/sim randomization, hardware safety staging, then feature-gated
   rollout with metrics and an instant fallback backend.

The two efforts meet only at the bounded body-velocity interface: semantic
navigation decides a safe short-horizon command, and the locomotion policy makes
that command physically smooth and dog-like. Keeping this boundary is what lets
both systems improve without allowing perception or an LLM to become a motor
controller.
