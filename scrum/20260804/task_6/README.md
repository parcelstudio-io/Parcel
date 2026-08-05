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

(append here)
