# Sprint 2026-08-04 · task_6 — instruction navigation: eval, grounding, model harness

**The failure being fixed (owner report, confirmed by diagnosis):** "go to
the sidewalk" dies. Root causes already identified in-repo: (1) semantic
grounding is **camera-frustum-gated** — an entity not currently in view
simply does not exist to the grounder; (2) there is **no look-around or
semantic-search recovery** — the plan fails instead of scanning; (3) the
semantic **vocabulary is two classes** (sidewalk/crosswalk regions,
lamppost objects) — bench, tree, planter, building are invisible; (4)
failure surfaces as a dead-end refusal instead of a recovery behavior.

**Deep research in flight** (task `wqm526wnx`): downloadable
language-navigation models from NVIDIA/UCSD (NaVILA), AI2 (SPOC/PoliFormer),
BD AI Institute (VLFM), Meta/CMU (GOAT/HomeRobot), DeepMind (MobilityVLA)
+ grounding/semantic-memory/exploration layers + eval methodology. Its
synthesis finalizes workstream C; workstreams A and B are correct under
every research outcome and start now.

**Executors:** Sol 5.6 Ultra (new pure modules only), Claude Opus (existing
files + wiring + UI). Conflict rule and agreements inherit from
[../task_4/README.md](../task_4/README.md). This is a big sprint — the
owner expects it to be.

## Board

| ID | Card | Owner | Depends on |
|---|---|---|---|
| N-S1 | Scenario spec + scoring core (pure): episode schema, goal regions, SR/SPL/DTG metrics, failure attribution | Sol | — |
| N-S2 | `SemanticMemory` (pure): persistent entity map with confidence decay — "seen once, remembered" | Sol | — |
| N-S3 | Region/relation goal geometry (pure): nearest-reachable-point on region polygons; "next to"/"towards" placement solvers | Sol | — |
| N-S4 | Scripted episode generator (pure): seeded placement randomization, distractors, ambiguity cases | Sol | N-S1 |
| N-O1 | Scene + vocabulary expansion: bench/tree/planter/building semantics with aliases; goal-region markers in scene metadata | Opus | — |
| N-O2 | Grounding pipeline rewire: memory-backed grounder (N-S2), region goals (N-S3), look-around `ScanForTarget` recovery before any refusal | Opus | N-S2 N-S3 N-O1 |
| N-O3 | `NAV_INSTRUCT_V1` headless harness: five instruction families × scenario matrix, baseline-first, ledger | Opus | N-S1 N-S4 N-O1 |
| N-O4 | Clickable eval UI: `/evals` panel page (list, run, live progress), goal-region overlay in `/viewer`, per-episode result drill-down | Opus | N-O3 |
| N-C1 | Model connector seam + downloaded-model adapter + A/B eval lane | Opus+Sol | research synthesis |
| — | Review at S-landings, N-O2 and N-O4 exits; C1 finalization from research | Fable | standing |

## The five instruction families (the product bar)

| Instruction | Family | Needs |
|---|---|---|
| "go to the sidewalk" | region goal | region geometry (N-S3), memory (N-S2), look-around (N-O2) |
| "can you walk towards the lamppost" | object goal | vocabulary + memory + look-around |
| "sit next to the bench" | object-relative placement | N-O1 bench semantics + N-S3 "next to" solver + task_3 settle grammar |
| "follow the owner" | person-relative | existing follow (regression lane — must not break) |
| "circle around the owner" | person-relative | existing orbit (regression lane) |

## Research addendum (synthesis landed 2026-08-04)

The deep-research synthesis confirmed the diagnosis and refined the cards:

- **N-S1 scoring**: add Oracle SR (OSR−SR isolates termination failures) and
  the L1–L6 attribution refinement with **oracle counterfactual auto-replay**
  (re-run failed episodes with oracle grounding, then oracle grounding +
  scripted exploration; the first flip names the layer). Track per-commit
  GROUNDING GAP and EXPLORATION GAP aggregates.
- **N-S2 memory**: add the **region channel** (per-cell semantic labels
  co-registered with the occupancy grid) alongside the instance store —
  "sidewalk" is a stuff class; boxes are the wrong shape for it.
- **N-S4 tiers are now A–E**: A visible <5 m · B in-range-outside-frustum
  (the reported bug) · C requires-search · D ambiguity+synonyms · E
  **absent/unreachable target** (bounded search then honest report — guards
  the hallucination error class before open-vocab perception arrives).
- **N-O2**: grounder outcomes are typed (RESOLVED/MEMORY_HIT/UNSEEN/
  AMBIGUOUS); SigLIP-2 embedding matching replaces string match.
- **Goal regions are predicates/polygons, never bare radii**, and the viewer
  always renders exactly the scorer's region.
- Experiment ladder + model shortlist (VLFM → NaVILA, SigLIP-2 now) live in
  the design doc; rungs 0–5 need no camera and no downloaded model.

## Hard gates

- **Baseline first:** N-O3 runs the matrix on today's code before N-O2
  lands, honestly recording the refusals ("couldn't form a plan") as the
  frozen starting row. Every later claim is a delta against it.
- **Failure attribution is mandatory:** every failed episode is classified
  {grounding_error, search_error, planning_error, control_error,
  refusal} — a hillclimb that can't say *which layer failed* isn't one.
- Existing follow-bench + embodied rows unchanged (post-speed-raise
  values); collision-gate violations zero everywhere, always.
- UI: every scenario runnable from the panel with the goal region visibly
  marked before the run starts and the verdict shown at the end.

## Handoffs

### Coordinator (Grok) — 2026-08-04 — full task_6 (Sol+Opus scopes)

Sol/Opus API limits; both scopes landed under the conflict rule
(Sol = `instructnav/*` + pure generator; Opus = existing files + harness/UI).

**N-S1–N-S4 (Sol):**
- `instructnav/scoring.py` — GoalRegion / FailureClass / EpisodeScore /
  score_episode + Oracle SR + L1–L6 counterfactual hooks.
- `instructnav/memory.py` — SemanticMemory instance store + region/stuff channel.
- `instructnav/relations.py` — nearest_point_in_region / next_to / towards.
- `instructnav/grounding.py` — typed RESOLVED/MEMORY_HIT/UNSEEN/AMBIGUOUS.
- `instructnav/arbiter.py` + `siglip.py` — ProposerBus/GoalArbiter + SigLIP stub.
- `evals/nav_instruct/generator.py` — families × tiers A–E, ≥20/family, seeded.

**N-O1:** `city_semantics.py` vocabulary — bench/tree/planter/building/crosswalk
with aliases, lidar ids, shared `goal_region` metadata; headless via same extract.

**N-O3 HARD GATE (baseline first):** historical minival frozen at
`scrum/20260804/task_6/freeze/nav-instruct-baseline.json` (pinned; CLI needs
`--freeze` to overwrite)
- n=25, SR=0.0, SPL=0.0, collisions=0
- failures: planning_error=16, refusal=6, search_error=2, control_error=1
- Going forward, `--mode baseline` is frustum-only (no memory/scan/frontier);
  `--mode candidate` enables N-O2 recovery. Episode `shortest_path_m` now uses
  grid A* when possible (digest may differ from the pinned freeze digest).

**N-O2:** pipeline frustum→memory→ScanForTarget→frontier→honest refusal;
relations in approach; directive parser gains towards/sit/next-to; alias table
shared with N-O1. Follow/orbit product-bar phrases parse; placements apply on
reset; no goal-disc teleport on spatial success.

**N-O3 complete + N-O4:** `evals/nav_instruct/runner.py` + CLI; `/evals` panel
with goal-region thumbnails; `/api/evals/*`; viewer GoalRegion overlay via
`state.eval`.

**N-C1:** GoalArbiter wired at semantic commit; SigLIP stub loud-degrades.

**Not verified →** UNVERIFIED U24–U26. Follow-bench / embodied rows not re-run
in this pass (collision total on nav-instruct minival = 0).

## Arbitration (coordinator standing in for Fable)

Cross-reviews REQUEST CHANGES: Sol modules (`6a4b448c-b25e-44e0-99e8-dc07d3762810`)
and Opus wiring (`5d042f22-c407-4b32-95f8-68d838b0e10d`). Coordinator standing in
for Fable — BINDING fixes below; DEFER listed last.

### Sol BINDING (accepted)

1. **SemanticMemory decay** — stop compounding. Decay from `last_seen` only
   (stored confidence stays the observe-time value; recalls at the same clock
   are identical).
2. **UNSEEN / not_found attribution** — classify as `grounding_error` unless
   the trace shows search was attempted (scan / frontier / looked-around), then
   `search_error`.
3. **Oracle SR** — when `oracle_success` is omitted, derive from the trace
   (ever inside goal, ignore hold) so OSR−SR isolates termination.
4. **Oracle no-flip layers** — map `GROUNDING_ERROR` → L2, `SEARCH_ERROR` → L3
   (not L6).
5. **Generator `shortest_path_m`** — use grid path length when possible; do not
   claim grid A* while emitting bare Euclidean.

### Opus BINDING (accepted)

1. **Episode placement** — apply `placement_overrides` / distractors /
   `remove_entities` on reset.
2. **`--mode baseline`** — actually disable N-O2 memory / scan / frontier
   (frustum-only recovery). Candidate enables them. Baseline must be
   reproducible from the CLI.
3. **Follow / orbit parsing** — expand parser + harness so the regression lane
   exercises follow / circle (not `directive_not_understood`).
4. **No teleport success** — stop writing a synthetic final pose into the goal
   disc on spatial “success.”
5. **ScanForTarget / frontier honesty** — prefer real ScanForTarget via
   SearchOwner-style frontier machinery; otherwise refusal text + UNVERIFIED
   must match open-loop crawl.
6. **SigLIP** — wire matcher into the grounder path with loud degrade, or
   strengthen U25 to say unwired. Prefer wiring + loud degrade.
7. **Batch eval API** — wire `/api/evals/batch` (or stop claiming batch in UI).
8. **Follow-bench + embodied freeze** — re-run or pin verification; do not
   claim unchanged without evidence.

### DEFER (accepted)

- `max_time_s` unused in scorer success path
- Centroid empty-polygon fallback edge cases
- Disc vs polygon goal shape for object landmarks
- `_instance_id` hardcoding all `bench_*` → `bench_1` while the scene has a
  single bench

### Constraints (unchanged)

`collision.py` / `reactive_safety.py` untouched. Suite + ruff green. U24–U26
honesty updated. Frozen baseline remaining honest (historical pre-rewire row;
CLI `--mode baseline` reproduces frustum-only behavior going forward).

### Verification notes (coordinator pass)

- Follow-bench pin (duplex nav regression): ledger latest shipped row
  `follow-bench-v1-20260804104134Z-d1adc373` → follow 8/9, navigate 2/2,
  hard_collision_total 0. Spot-checked `straight_follow` / `follow_turn_corner`
  / `owner_stops` complete with 0 hard collisions (single-scenario reports not
  left on the ledger).
- Embodied pin: `EMBODIED_POST_SPEED.simulator_step_count == 1146`,
  collisions 0, supported success rate 1.0 (duplex gate).
- Nav-instruct: `--mode baseline` → frustum-only (grounding/refusal path);
  `--mode candidate` → memory/scan/frontier. Freeze file not overwritten
  without `--freeze`.
