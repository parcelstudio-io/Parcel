# Day 47: Owner Following and Companion Navigation

## Mental model

Following a person is not “set `vx` toward a blob.” It is a social navigation skill with formations, speed adaptation, loss/reacquisition, proxemics, and identity uncertainty. The dog must stay useful without invading personal space or chasing the wrong pedestrian after occlusion.

```text
owner track (est) + formation policy + obstacles
        → bounded body velocity intent
        → Sport gait
        → re-observe owner / clearance / identity
```

Companion navigation prefers living beside a moving frame (`owner`) over winning a shortest-path contest to a static map goal. Progress is relational: standoff error, heading coherence in `behind` mode, and track freshness—not Euclidean distance to a waypoint that ignores the human beside you.

**Tradeoff:** tighter standoff feels attentive but raises nuisance stops when crowds compress; looser standoff feels safer socially but loses the owner at corners. Tune with logged standoff variance and wrong-target incidents, not demo aesthetics alone.

## Software-engineering analogy

Think of following as tracking a mobile leader lease in a cluster: you maintain soft affinity to the leader’s address, back off when overloaded (crowding), and fail closed when the lease expires (track stale). Reacquisition is service discovery with authentication—appearance re-ID is a claim, not a root of trust, until cross-checked with geometry and recent trajectory continuity. `SearchOwner` is the bounded rediscovery protocol, not infinite wander.

## ASCII diagram

```text
  camera + LiDAR tracks
           |
           v
  owner association / re-ID belief
           |
           v
  FollowOwnerController
    mode: direct | behind
    states: idle → acquiring → following / holding / holding_behind / stale / lost ...
           |
           +--> FollowConfig.owner_keepout_m + standoff
           +--> prediction (FollowPredictionConfig) + uncertainty brake
           +--> ReactiveSafetyPolicy (person/obstacle stop & slow)
           |
           v
  CommandArbiter + collision gate + velocity shaping
           |
           v
  Unitree Sport (body velocity)
           |
           v
  track lost? → SearchOwnerController (SYSTEM_SKILL path)
```

## Map to Parcel / Go2

From `navigation/follow.py`, `navigation/spatial.py`, `navigation/search_owner.py`, and runtime wiring:

- **`FollowOwnerController`** — fail-closed follow over camera/LiDAR observations. Modes: default `direct` distance following; explicit `behind` derives owner heading from timestamped tracks and does **not** fall back to chasing the owner point when heading is unavailable (enters `acquiring_heading` / `holding_behind` instead).
- **`FollowConfig.owner_keepout_m`** — must cover person-stop distance plus owner collision envelope; `RobotRuntime` rejects configs that undercut reactive policy.
- **`parse_follow_intent`** (`navigation/spatial.py`) — high-confidence grammar for follow utterances (`follow me`, `heel`, …); pairs with deterministic router direct paths so “follow me” need not wait on deliberative PlanIR.
- **`FollowFormation`** in `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS` — language compiles into this controller, not a parallel chase loop invented by the model.
- **`SearchOwner`** — `SYSTEM_SKILL_NAMES` / `SYSTEM_SKILLS`; `SearchOwnerController` runs phased frontier search when follow declares `lost`—the LLM may not author it, but the executive may dispatch it after timeout.
- **Social constraints:** doorways stress clearance; `holding_behind` can be correct progress. Identity swaps after occlusion are a known city failure—require continuity before resuming cruise speeds.
- **Prediction:** anticipatory lead via configured prediction hooks; lead points still clamp to keepout.

Parcel’s brain updates follow intents on the order of ~10 Hz; Sport closes balance faster. Do not put LLM calls inside the follow update.

Deterministic follow grammar in `simulation/headless_city.py` calls `parse_follow_intent` before engaging the controller—useful regression harness when tuning standoff without invoking the GPU stack. Orbit and follow share owner tracks but differ in success geometry; do not reuse orbit “done” heuristics when verifying `FollowFormation`.

**Codebase anchors (follow / spatial / search / shields):**

- `navigation/follow.py` → `FollowOwnerController`, `FollowConfig`, states including `following`, `holding`, `holding_behind`, `stale`, `lost`, `blocked`.
- `navigation/spatial.py` → `parse_follow_intent` (regex imperative filter via `_imperative_body`).
- `navigation/search_owner.py` → `SearchOwnerController`, `SearchOwnerConfig`.
- `navigation/reactive_safety.py` → `ReactiveSafetyPolicy`, `apply_reactive_safety` (used from follow path and runtime).
- `brain/runtime_adapter.py` → `FollowFormation` dispatch callback; `SearchOwner` runtime callback when configured.
- `runtime.py` → constructs `FollowOwnerController` from store `follow` section; wires `search` controller for owner reacquisition.

## Failure story

In a crowded crosswalk the track briefly locked onto a stranger with similar clothing after the owner turned. Follow stayed in `following` at cruise pace; keepout was satisfied relative to the *wrong* person. The owner shouted; barge-in cancelled speech but follow remained enabled until explicit stop grammar latched. Fix: uncertain identity or abrupt track jumps must force `holding` / reacquisition UX and slow policies—not silent target swaps—and voice cancel must be able to disable follow, not only mute TTS. Logging now correlates track ID jumps with follow state transitions for postmortems.

## Retrieval questions

1. Why is `behind` formation stricter about owner heading than `direct` mode?
2. What does `owner_keepout_m` protect that pure goal-seeking navigation ignores?
3. (Week-back) From Day 29: how do occlusion and data association threaten follow safety, and where does `SearchOwner` fit?

## Optional 10-minute exercise

Open `FollowOwnerController`’s docstring and `FollowConfig` defaults in `src/parcel_robot/navigation/follow.py`. Note `owner_keepout_m` and behind-distance constraints. Write a one-line policy for “owner lost > T seconds” that names whether you dispatch `SearchOwner`, enter `Hold`, or ask for clarification.
