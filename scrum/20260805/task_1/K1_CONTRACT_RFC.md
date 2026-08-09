# K1 Contract RFC — Parcel V1 cross-track DTOs

**Card:** K1 · **Date:** 2026-08-05 · **Lane:** Sol (pure modules only) ·
**Status:** implemented in `src/parcel_robot/contracts/` · CI:
`tests/test_contracts_v1.py`

## Purpose

Freeze the Phase-0 interface contracts so Tracks A/B/C/D can parallelize
without rewriting seams. This RFC merges Sol's V1 DTO family (A-doc envelope +
tracks/regions; B-doc dialogue/social/query/feedback) with Fable's
`DetectionMsg` and **dialogue-state** StimulusBus channel
([ADJUDICATION.md](ADJUDICATION.md) K1).

**Non-goals:** no ROS message generation, no runtime/`agent.py` wiring, no
Nav2, no I/O. Opus owns later integration.

## Package layout

| Path | Role |
|---|---|
| `src/parcel_robot/contracts/v1.py` | Frozen dataclasses + exact-field `from_mapping` / `as_dict` |
| `src/parcel_robot/contracts/freshness.py` | Fail-closed TTL / age / clock-jump / v·τ speed cap |
| `src/parcel_robot/contracts/__init__.py` | Public re-exports |
| `tests/test_contracts_v1.py` | Round-trip, NaN, expiry, schema mismatch, clock jump |

Style matches `instructnav` / `brain.contracts`: `@dataclass(frozen=True,
slots=True)`, `__post_init__` bounds, no numpy/ROS.

## Clock and freshness rules (binding)

1. Every evidence sample carries **both** `source_timestamp_ns` (sensor/sim
   clock) and `received_monotonic_ns` (local monotonic). Do not mix clocks.
2. Consumers compare expiry and age **only** on the monotonic axis via
   `check_freshness` / `require_fresh` / `EvidenceEnvelopeV1.require_fresh`.
3. Adapters call `detect_clock_jump` across consecutive samples; backward
   source/monotonic steps or source advancing without monotonic progress are
   **rejected**.
4. Expired, stale (`max_age_ns`), or untransformable samples fail closed —
   never become soft evidence.
5. Commanded speed may be capped by `speed_cap_from_staleness_m_s` so
   `v · τ ≤ max_displacement_m` (default 15 cm).

Default TTLs (monotonic ns): track 500 ms, detection 300 ms, semantic 2 s,
social cue 5 s, dialogue-state 500 ms.

## DTO catalog

### `EvidenceEnvelopeV1`

```text
schema_version, evidence_id, source,
source_timestamp_ns, received_monotonic_ns, sequence,
frame_id, scene_revision, expires_monotonic_ns,
calibration_id, provenance[]
```

Common wrapper for every cross-process observation and proposal.

### `OwnerTrackV1`

Envelope + `enrolled_owner_id`, `transient_track_id`,
`state ∈ {confirmed, ambiguous, lost}`, pose/velocity + 4×4 covariances,
identity/visibility scores, appearance refs, `last_confirmed_at_monotonic_ns`
(required when `confirmed`). Fail-closed identity SM remains a consumer
policy; the DTO only carries state.

### `DynamicTrackV1`

Envelope + `track_id`, `class_id`, pose/velocity + covariance,
`predicted_occupancy[]` (timestamped polygon or Gaussian).

### `SemanticRegionV1`

Envelope + `concept_scores{}`, `GeometryV1` (polygon | disc | point_cloud |
raster — **never a bare label**), geometry covariance, `free_space_support`,
`observation_count`, evidence refs.

### `GoalRegionV1`

Shared by scorer and task verifier (agent never sees privileged world
predicates). Fields: `goal_id`, `source_task_id`, `plan_step_id`, `frame_id`,
`acceptable_polygon`, optional `preferred_pose`, approach constraints,
forbidden regions, `relation ∈ {inside, near, behind, orbit, hold, visible}`,
`hold_duration_s`, confidence, issued/expires monotonic stamps, evidence refs.

Distinct from `instructnav.scoring.GoalRegion` (eval disc/polygon helper).

### `DialogueActV1`

Conversation-lane output: turn id, text, speech style, acknowledgement kind,
`claims[]` (each `verified` claim cites evidence; else `tentative`), social
cue ids, `asks_clarification`. No velocity/goal/priority schema.

### `SocialCueV1` / `ReactionProposalV1`

Cue: kind, modality, evidence, confidence, valence/arousal, observed/expires.
Proposal: source cues, allowlisted `behavior_id`, `required_tracks` from
`{base, posture, voice, attention, perception_scan, expression_audio}`,
confidence/urgency, dwell/duration, interruption policy, suppress_if,
personality rule. Arbiter decides execute/overlay/defer/suppress/expire.

### `SceneQueryV1` / `SkillFeedbackV1`

Broker seam: skills request evidence (`terms`, relation, freshness ms,
confidence, search budget, cached/scan flags); skills report status,
checkpoint/critical_phase, progress, verified facts, blocking reason, scene
revision.

### `DetectionMsg` (Fable)

```text
envelope, class_id, embedding[], bearing_rad ∈ [-π, π],
range_m, score ∈ [0, 1], track_id?
```

Sim-noise adapter and real detectors are indistinguishable behind this shape.

### `DialogueStateMsg` (Fable channel)

10 Hz StimulusBus channel:

```text
schema_version, channel="dialogue_state",
phase ∈ {speaking, listening, thinking, idle},
engagement ∈ [0, 1], turn_id?, published/expires monotonic, sequence
```

T2 maps phase/engagement → gaze/gait/pace; high engagement may defer
non-urgent autonomy mid-sentence.

## Single-owner / authority notes (contract-level)

| Seam | Owner (later wiring) | Contract invariant |
|---|---|---|
| Final body command | `ControlManager` | DTOs never carry `cmd_vel` |
| Goal admission | GoalArbiter / PlanIR validator | `GoalRegionV1` + freshness |
| Owner identity | Owner track SM | never attach on `ambiguous`/`lost` |
| Scene evidence broker | perception broker | skills emit `SceneQueryV1` only |
| Social body motion | `ReactionArbiter` | proposals expire; no model priority |

## Acceptance (A0 / B0 aligned)

CI must fail on: malformed / unknown fields, wrong `schema_version`, NaN /
non-finite numerics, expired TTL, monotonic inversion, source clock jump,
verified claim without evidence ref, geometry without geometry, disallowed
resource tracks, wrong dialogue-state channel name.

## Out of scope for K1 (explicit)

- Wiring into `StimulusBus`, `runtime.py`, or `agent.py`
- ROS 2 IDL / Nav2 action adapters
- Bag schema (K2′) and sim DetectionMsg noise adapter (K5)
- Changing existing `brain.contracts` PlanIR / IntentFrame

## Revision

| Ver | Change |
|---|---|
| 1 | Initial freeze (K1) |
