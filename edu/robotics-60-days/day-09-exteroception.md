# Day 09: Exteroception

## Mental model

**Exteroception** senses the outside world: cameras (appearance and semantics), LiDAR (metric range and geometry), microphones (sound for speech), optional map providers (prior geography). It answers “what is around me and where is the owner?” — never directly “what is my knee angle?”

Sensors do not deliver truth; they deliver **partial, delayed, modality-specific measurements** that become tracks, obstacles, and semantic beliefs only after estimation. A confident label with a wrong metre is still a bad follow target.

In Parcel, the application-visible world sample is largely `SimObservation` in `src/parcel_robot/backends/base.py`, fed by simulator LiDAR (`src/parcel_robot/simulation/mujoco_lidar.py`) or future hardware drivers — declared via `perception.spatial_sensors: [camera, lidar]` in `configs/robot.yaml`.

## Software-engineering analogy

Camera is a full-text search index: rich, ambiguous, excellent for “looks like the owner.” LiDAR is a structured probe fan-out with timeouts: metric ranges, weak semantics. Microphone is an async event stream with echo and barge-in. A prior map is a stale CDN cache of geography — useful hints, never live authority (`perception.maps.enabled: false` placeholder in `configs/robot.yaml`).

Fusion is a materialized view over heterogeneous replicas. If one replica is stale or contradictory, the view must degrade loudly — slow/stop/reacquire — not average nonsense into a smooth wrongness.

## Light equations / measurement models

```text
camera:  pixels ← projection(scene); depth ambiguous from one view
LiDAR:   r ≈ (c Δt)/2 along ray θ; no-return ≠ proven free forever
audio:   pressure(t) → features → text/intent (huge many-to-one)
```

Complementarity (`edu/INTRO.md`):

```text
camera: "that object looks like the owner"
LiDAR:  "that object is approximately 2.1 meters away"
```

Age budgets matter as much as geometry: a perfect owner box from 800 ms ago is a different person-shaped hazard.

## ASCII diagram

```text
  mic ──► ASR / duplex ──► intent (semantic belief)
  cam ──► tracks / labels ──┐
  lidar─► ranges/obstacles ─┼─► SimObservation / nav gates
  map? ─► prior (optional) ─┘         │
                                      ▼
                         follow / search / collision TTC
                                      │
                                      ▼
                         VelocityCommand proposals (not joints)
```

## Map to Parcel / Go2

- `SimObservation` fields: `owner`, `lidar_ranges` + `lidar_angle_*` / `lidar_range_*_m`, `lidar_obstacles`, nearest person/obstacle distances and bearings, `nearest_person_ttc_s`, `dynamic_agents`, `semantic_objects` / `semantic_regions`, collision/E-stop flags.
- Navigation consumers: `navigation/follow.py`, `navigation/search_owner.py` (`_scan` builds a `LidarScan` from observation ranges), `navigation/reactive_safety.py` for proximity gates; semantic helpers in `navigation/semantic_map.py` (`lidar_payload_from_observation`).
- Owner-follow freshness: `owner_follow.heading_stale_after_s` and the `prediction:` block in `configs/robot.yaml` — exteroceptive tracks expire; motion must not trust them forever. Lost-owner handoff uses `owner_search.lost_timeout_s`.
- Spatial behaviors use metric knobs (`default_orbit_radius_m`, `owner_collision_envelope_m`) — exteroception supplies the owner/obstacle estimates those metres refer to.
- Architecture notes: `docs/COMPANION_NAVIGATION_ARCHITECTURE.md` and the camera/LiDAR gate section of `docs/MOTION.md`.
- What exteroception **cannot** replace: IMU/encoders for balance (Day 08). A perfect owner box does not stabilize roll.

## Failure story

Follow used a confident camera ID while LiDAR showed the “owner” cluster jump 1.5 m through a glass-door reflection. The dog accelerated toward a pane. Root cause: semantic belief outran metric gating. Fix: require moderate LiDAR/range consistency before translating; on disagreement, slow/stop and reacquire (`owner_search`) instead of trusting the prettier modality.


## Building habit

Require cross-modality consistency for translation toward people: semantic ID from camera plus plausible range/bearing from LiDAR (or an explicit degraded mode). Honor stale-track knobs (`heading_stale_after_s`, `owner_search.lost_timeout_s`) as hard motion inhibitors. When adding a perception field, extend `SimObservation` carefully and update every consumer that assumed absence means “empty world” versus “sensor unavailable”—`lidar_ranges` empty already means mapped nav must degrade loudly. Keep map providers disabled until they have a typed, non-authoritative role (`perception.maps`). Never feed exteroceptive beliefs into joint or torque commands; they propose `VelocityCommand` candidates that still pass arbiter, gates, and `ControlManager`.

Exteroception measures the world; it does not certify task success alone. Pair owner-bearing estimates with proprioceptive body motion when deciding that an orbit or approach finished (Day 10). Glass, sun glare, and multipath are not edge cases outdoors—they are normal adversaries for a sidewalk companion.


Microphone and speech are exteroception with extreme many-to-one compression: many waveforms become one intent string. That string is a belief, not a metric waypoint. Keep audio pipelines from claiming spatial authority unless a calibrated direction-of-arrival path exists; Parcel’s current companion navigation authority for metres remains camera/LiDAR geometry gated through `SimObservation` and the motion stack in `docs/MOTION.md`. When ASR is wrong, the failure mode is a bad semantic plan—not a wrong encoder.


Also remember occlusion: LiDAR and camera both lie by omission when the owner steps behind a car. Absence of a track is not proof of absence of a person—search and slow policies exist for that gap (`owner_search`).
## Retrieval questions

1. What does a single LiDAR return guarantee, and what does a no-return *not* guarantee?
2. Which Parcel structure carries application-visible world measurements for nav/follow?
3. (Day 08) Why can excellent camera tracks still leave the dog unable to balance?

## Optional 10-minute exercise

Open `SimObservation` in `src/parcel_robot/backends/base.py` and tick each field as proprio, extero, or status/bookkeeping. Then find one read of `lidar_ranges` or `lidar_obstacles` under `src/parcel_robot/navigation/`.
