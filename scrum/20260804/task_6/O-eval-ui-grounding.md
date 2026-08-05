# Workstream O — Claude Opus: scene, grounding rewire, harness, clickable UI

Owns existing files; consumes S-card modules by their frozen signatures.

---

## N-O1 — Scene + vocabulary expansion · days · start now

1. `extract_city_semantics` learns the full scene: **bench** (exists in the
   scene XML, invisible to semantics — the exact "sit next to the bench"
   killer), **tree/planter/building/crosswalk-as-goal**, via a general
   prefix→class table with aliases ("bench", "seat"; "lamppost", "lamp
   post", "streetlight"...), reusing the lamppost metadata scheme
   (stand-off, vicinity radii). Every class gets `associated_lidar_ids` so
   grounding and collision agree about the same object.
2. Goal-region metadata: regions get their polygons (already true for
   sidewalk) and objects get their vicinity discs exported in the semantics
   payload so the eval and the viewer draw *the same* region the scorer
   uses — one definition, three consumers.
3. Headless parity: the same expansion in `headless_city.py`'s semantics
   path. Tests: every class present in both sims, labels/aliases pinned.

## N-O2 — Grounding rewire: memory + look-around + no dead-end refusals · ~1 week

The core fix. Order of resolution for a NavigateTo directive becomes:

1. **Live frustum** (today's path) →
2. **SemanticMemory recall** (N-S2; runtime feeds every observation's
   visible semantics into memory each tick) →
3. **`ScanForTarget` recovery**: a bounded look-around — in-place yaw sweep
   (reusing SearchOwner's sweep machinery through the task_4 registry, so
   pause/resume and preemption come free) while memory ingests what the
   sweep reveals; found → proceed; not found →
4. **Semantic frontier search** (bounded, reuses SearchOwner's frontier
   scorer; budget configurable, default 30 s) →
5. Only then an honest reply — and it names what it did: "I looked around
   and couldn't find a bench nearby", never the dead-end "couldn't form a
   plan".

Wiring details: region goals route through `nearest_point_in_region`
(N-S3) instead of centroids; "towards X" uses `towards_waypoint`;
"next to X" uses `next_to_placement` feeding the existing approach-pose
machinery; the grounder's alias matching moves to one table shared with
N-O1's vocabulary. The refusal-text change is part of the card: the reply
must state the recovery attempted (this is also what the eval's REFUSAL vs
SEARCH_ERROR attribution keys on).

Regression: follow/orbit untouched (their lane in N-O3 proves it).

## N-O3 — `NAV_INSTRUCT_V1` headless harness · ~4 days · after N-S1/N-S4/N-O1

`evals/nav_instruct/`: runner drives the full runtime pipeline (directive →
grounder → planner → control) in `HeadlessCityWorld` per episode spec;
records the trace fields N-S1's scorer and failure-attributor need
(grounding events, search events, route status, collisions, refusal
replies); ledger + immutable reports + `does_not_prove` (sim ground-truth
semantics ≠ camera perception — that closes with hardware perception).

**Baseline first, before N-O2 merges:** run the full matrix on today's
code; the expected result is refusals across most non-visible episodes —
that row is the honest starting point every improvement is measured
against. Aggregate dashboard per family × tier: SR, SPL, DTG, failure-class
histogram.

## N-O4 — Clickable eval UI · ~4 days · after N-O3

The owner's requirement: *see* the tests, click, run, watch, with the goal
marked.

1. **`/evals` panel page**: scenario matrix as cards (family × tier ×
   episode), each with the instruction text, a mini-map thumbnail with the
   **goal region pre-drawn**, and a Run button. Filters by family/tier/
   last-result.
2. **Two run modes**, one scenario spec:
   - *Live mode* (the visible one): the panel's running sim adopts the
     episode (places entities via the existing owner/actor placement
     hooks, injects the instruction through `submit_voice_text`), and
     `/viewer` renders the **goal region overlay** (polygon/disc/band from
     the same `GoalRegion` the scorer uses), the live trajectory, and a
     PASS/FAIL banner with the failure class at episode end.
   - *Headless mode*: N-O3's runner in a background thread for batch runs;
     progress bar + results table per family; drill-down to per-episode
     trace summary (grounding→search→plan→control timeline).
3. API: `GET /api/evals/scenarios`, `POST /api/evals/run {episode_id,
   mode}`, `GET /api/evals/status`, results persisted next to the ledger.
4. Viewer overlay work: `GoalRegion` → polygon/disc rendering (goal fill +
   outline + label), plus the search-state indicator (scanning / frontier
   target) so "it's looking around" is *visible* — the owner's complaint
   included "it doesn't even look around"; the UI must show when it does.

## N-C1 — Model connector seam · FINALIZED from the research synthesis

Full rationale: [../../../docs/INSTRUCTION_NAV_HILLCLIMB.md](../../../docs/INSTRUCTION_NAV_HILLCLIMB.md).

1. **ProposerBus + GoalArbiter** (Sol builds the pure arbiter; Opus wires):
   typed `SE2Goal{source, pose|waypoints, frame, confidence, TTL,
   plan_step_id}`; proposers register (grounder goals, ScanBehavior,
   SearchEntity, Follow/Orbit streams, later VLFM/VLA bridges); resolution
   by plan-step ownership + priority + freshness; TTL-expired or
   lethal-cost goals vetoed with re-request (timestamp + pose-buffer
   transform — the AsyncShield staleness lesson). grid_v1 A* is the sole
   consumer. This bus is what makes every candidate hot-swappable for
   paired A/B.
2. **Download now:** SigLIP-2 B/16 (Apache-2.0) as Grounder v2's embedding
   glue — text-embed classes + directives, cosine + threshold.
3. **Rung 6 (camera-gated):** VLFM (MIT) — keep its BLIP-2/SigLIP value
   map as SearchEntity's frontier scorer; replace its depth-built map with
   grid_v1's grid + frontiers; delete its PointNav policy (waypoints go to
   the arbiter).
4. **Rung 7:** NaVILA (Apache-2.0, verified HF checkpoints) as a remote-GPU
   service (≥24 GB, ~1 Hz): last-8 RGB frames + instruction → text actions
   → regex → clamped ≤1.5 m SE2 goals with TTL ≈ 2× period. A VLA earns a
   permanent slot only at ≥ +5 pp on some family without raising
   gate-intervention rates (paired frozen split, McNemar).
5. **Do not build on:** InternVLA-N1 weights (CC BY-NC-SA — research track
   only), StreamVLN code (NC; copy only its D455 rig + async-burst
   pattern), NavFoM (no public weights as of Aug 2026).
