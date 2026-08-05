# Instruction navigation: the hillclimb plan

**Date:** 2026-08-04 · **Method:** 3-agent deep research (downloadable
models / grounding+memory+exploration layers / eval methodology) +
max-effort synthesis, adjudicated against the codebase. Execution:
[../scrum/20260804/task_6/](../scrum/20260804/task_6/). Full agent output in
the session task log.

## Diagnosis, confirmed and sharpened

The frustum-gating / no-search / tiny-vocabulary diagnosis is confirmed —
the literature names all three as distinct failure classes with distinct
fixes. The research adds what the diagnosis missed:

1. **Memory is the deeper bug.** The camera frustum is a fine *sensor*
   model; treating it as the *database* is the defect. GOAT: persistence
   lifts SR from ~60% (first goal) to ~90% (previously seen) — the single
   biggest compounding win available.
2. **"Sidewalk" is a region/stuff class, not an object.** Detector boxes
   are the wrong representation; it needs a segmentation-shaped **region
   channel rasterized onto the 2D grid** — which sim GT polygons supply
   honestly today and a Cityscapes-class segmenter fills identically later.
3. **Only 2 of 5 commands need the full ground+memory+search stack.**
   Follow/circle are tracking + parametric goal streams (zero grounding);
   "sit next to the bench" is the lamppost pipeline + a relation-
   parameterized pose sampler. Keeping them off the model path is itself a
   plan decision.
4. **Termination is its own failure class** (OSR−SR isolates "got there,
   never stopped") — without goal predicates and stop rules, perfect
   grounding still fails.
5. **The missing egocentric RGB(-D) camera is the binding constraint** for
   every downloadable model — none consume planar LiDAR or GT entity lists.
   And once open-vocab perception lands, **false-positive grounding becomes
   the dominant error class** — the eval needs an absent-target tier from
   day one.
6. **Propose/dispose is validated, not a handicap:** zero-shot modular VLFM
   beats trained end-to-end policies on ObjectNav SPL, and the 2026
   async-edge line (AsyncShield/AsyncVLA) formalizes exactly our shape:
   semantic layer proposes asynchronously, classical 10 Hz loop disposes.

## The layer plan (all proposers; grid_v1 + collision gate stay the only writers)

Every component emits typed `SE2Goal{source, pose, frame, confidence, TTL,
plan_step_id}` into a **GoalArbiter** at 0.3–5 Hz; grid_v1 A* is the sole
consumer; goals past TTL or in lethal cost are vetoed (AsyncShield's
staleness lesson: timestamp, pose-buffer transform, drop on expiry).

| # | Component | When | Key point |
|---|---|---|---|
| 1 | `SemanticMemory2D` — region channel co-registered with the occupancy grid + instance store {class, SigLIP-2 embedding, centroid, last_seen, decaying confidence} | sim-now | GOAT memory at 2D weight; frustum stays the sensor, memory becomes the database |
| 2 | Grounder v2 — SigLIP-2 embedding match, typed outcomes RESOLVED / MEMORY_HIT / UNSEEN / AMBIGUOUS | sim-now | UNSEEN triggers recovery instead of refusal; synonyms ("streetlight") nearly free |
| 3 | `ScanBehavior` PlanIR op — rotate-in-place full turn, populate memory, re-ground | sim-now | VLFM's own initialization move; fixes the reported failure for in-range targets |
| 4 | `SearchEntity` — **generalize SearchOwner's existing frontier machinery**; score = semantic prior (sidewalk-borders-road table; optional cached LLM scores at plan time) − A* geodesic cost | sim-now | The scorer is swappable (VLFM value map later); the plumbing is not |
| 5 | `GoalPoseSampler` — "next to" = 0.3–1.5 m polar-weighted ring, free-space filtered; "towards" = stop-short ray goal | sim-now | LINGO-Space pattern; relations are parameters, never new plan types |
| 6 | `PersonTrack` + Follow/Orbit behaviors | sim-now | Sim GT track today; detector+ReID later behind the identical interface |
| 7 | `DetectionAdapter` — GT → `DetectionMsg{class, embedding, bearing, range, score}` with Habitat-style noise (range cutoff, p_detect(distance), confusion, jitter) + widened sim vocabulary | sim-now | The stack becomes detector-shaped before any pixel exists |
| 8 | `CameraChannel` — MuJoCo offscreen EGL RGB + metric depth + segmentation, D455 intrinsics, head-mounted per StreamVLN's Go2 rig | gates model era | Frustum-gated GT semantics derive **from the same rendered camera** models see — visibility and VLM inputs can never disagree |
| 9 | `GoalArbiter` / ProposerBus | sim-now | What makes every candidate hot-swappable for paired A/B |

## Model shortlist (verified availability, license, connector)

| Rank | Model (org) | Role | License | Connector |
|---|---|---|---|---|
| 1 | **VLFM** (BD/RAI Institute) | Pattern donor now; camera-era SearchEntity frontier scorer (BLIP-2/SigLIP value map) | MIT end-to-end | CameraFrame+odom in; **replace** its depth map with grid_v1's grid+frontiers; **delete** its PointNav policy — waypoints go to the GoalArbiter |
| 2 | **NaVILA** (NVIDIA/UCSD) | Instruction-rich VLA arm; strongest legged evidence (88% SR on real Go2/G1) | Apache-2.0 code+weights (verified on HF) | Remote-GPU service (≥24 GB, ~1 Hz): 8 RGB frames + instruction → text actions → regex → clamped ≤1.5 m SE2 goals with TTL |
| 3 | InternVLA-N1 System-2 (Shanghai AI Lab) | Research track only — weights CC BY-NC-SA (not productizable); Go2 camera-mount STEP files reusable | MIT code / NC weights | Pixel goal + depth unprojection → SE2 goal, ~2 Hz; discard its System-1 executors |
| — | **SigLIP-2 B/16** (DeepMind) | **Download now**: Grounder v2 + memory embedding glue | Apache-2.0 | Text-embed classes + directives; cosine + threshold |
| — | NanoOWL / MM-Grounding-DINO | Dock-era detector filling `DetectionMsg` (NanoOWL: 95 FPS on AGX Orin) | Apache-2.0 | Same message contract as the sim noise adapter — grounder never knows the source changed |
| — | Uni-NaVid (PKU/BAAI) | Watch: only downloadable VLA covering *following*; no deployment code — offline benchmark vs recorded logs first | MIT + weights | Video in, discrete actions → short SE2 goals, if ever promoted |
| — | StreamVLN / NavFoM / AsyncVLA | Pattern donors & watch list; StreamVLN code is CC BY-NC-SA (legally dead for product); NavFoM still no public weights | — | Copy the D455 rig spec + async 4-action-burst pattern only |

## The experiment ladder (each rung gated by the eval)

0. **Eval first** (days): harness + seeded generator (5 families × 5
   tiers) + frozen 25-episode minival in CI + panel UI skeleton with goal
   regions pre-drawn.
1. **ScanBehavior** (days) — Tier B SR ≥ 90%; the original "go to the
   sidewalk" repro seed passes.
2. **SemanticMemory2D + Grounder v2** (days) — repeat-directive SR ≥ 95%
   with no re-search; synonyms ground.
3. **SearchEntity** (week) — Tier C SR ≥ 70% within 90 s; ≥ +10 pp over
   nearest-frontier baseline (paired seeds, McNemar p<0.05).
4. **Relations + person behaviors** (days) — sit-next-to predicate ≥ 80%;
   Following Rate ≥ 0.8 with zero collisions; circle ≥ 360° swept, radial
   RMSE ≤ 0.3 m.
5. **Honest sensor** (week) — ≤ 10 pp degradation at nominal noise; Tier E
   (absent target) ≥ 90% correct bounded-search-then-report; oracle
   counterfactual replay auto-attributes every failure.
6. **CameraChannel + VLFM bridge** (week) — pixels→value-map→waypoint→
   grid_v1 proven headless; VLFM scorer ≥ prior table on Tier C, wins
   unseen-category cells.
7. **VLA arm** (weeks) — NaVILA service A/B on the frozen paired split; a
   VLA earns a permanent slot only at ≥ +5 pp on some family without
   raising gate interventions.
8. **Only on measured plateau** (month+): make-path — imitate grid_v1+GT
   as privileged expert (SPOC recipe) / FLaRe RL fine-tune; or a
   waypoint-native foundation model if one actually releases.

## Eval spec (the load-bearing details)

- **Metrics:** SR (agent-issued stop inside region — headline), Oracle SR
  (OSR−SR isolates termination bugs), SPL/soft-SPL against grid_v1's own
  shortest path, distance-to-goal, gate-intervention count (proposer
  quality), MultiON-style progress for multi-step; Habitat-3.0 following
  protocol; circle = swept bearing + radial RMSE.
- **Failure attribution:** OVMM-style waterfall Parse→Ground→Reach→
  Terminate→Posture, refined into L1–L6 with **L2a vocabulary / L2b
  visibility-gated / L3 exploration kept separate** (they are the three
  different fixes for today's bug); **oracle counterfactual auto-replay**
  (inject oracle grounding, then oracle grounding + scripted exploration —
  the first that flips the episode names the culpable layer); per-commit
  GROUNDING GAP and EXPLORATION GAP are the two numbers that say whether a
  better model would even help.
- **Tiers:** A visible <5 m (sanity) · B in-range outside frustum (today's
  bug lives here) · C beyond the block (search) · D ambiguity + synonyms ·
  E absent/unreachable (bounded search then honest report). Follow/circle
  swap C–E for corners/occlusion and pedestrian-distractor ReID stress.
- **Goal regions are predicates/polygons, never bare radii**, always
  rendered in the viewer (a mis-specified region masquerades as a model
  failure). "Next to the bench": lateral 0.3–1.5 m from the footprint
  polygon ∧ same walkable region ∧ no overlap ∧ sit held ≥ 2 s.
- **Stats:** 50–100 seeded episodes/cell (~25 cells, nightly headless);
  Wilson intervals; promotion only via paired-seed McNemar; regression
  gate: no family drops > 5 pp on the frozen split; agent-stop only.

## Sequencing note

Rungs 0–5 need **no camera and no downloaded model** — they fix the actual
reported failure with components Parcel mostly already owns (SearchOwner's
frontier machinery, the approach-pose sampler, the grid). The camera
(rung 6) is the gate to the model era, and the shortlist is downloaded in
license-verified order: SigLIP-2 immediately, VLFM at rung 6, NaVILA at
rung 7. Anything trained replaces the modular stack only by beating it on
the same frozen paired split it is measured on.
