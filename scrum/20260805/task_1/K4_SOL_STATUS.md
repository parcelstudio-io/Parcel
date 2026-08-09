# K4 Status — SemanticMemory2D + Grounder v2 + ScanBehavior + SearchEntity

**Card:** K4 · **Owner lane:** Sol (pure) · **Date:** 2026-08-05 ·
**State:** DONE (pure modules + unit tests; **no** MuJoCo/runtime wiring)

**Plan refs:** [ADJUDICATION.md](ADJUDICATION.md) kickoff K4;
[`docs/INSTRUCTION_NAV_HILLCLIMB.md`](../../../docs/INSTRUCTION_NAV_HILLCLIMB.md)
rungs 1–5 (Sol scope: 1–4 pure APIs; rung 5 relations already in
`relations.py` / scoring — not re-owned here).

## Delivered

| Artifact | Path |
|---|---|
| SemanticMemory2D | `src/parcel_robot/instructnav/memory.py` |
| Grounder v2 | `src/parcel_robot/instructnav/grounding.py` (`GrounderV2`) |
| ScanBehavior helpers | `src/parcel_robot/instructnav/scan.py` |
| SearchEntity frontier scoring | `src/parcel_robot/instructnav/search_entity.py` |
| Package exports | `src/parcel_robot/instructnav/__init__.py` |
| Unit tests | `tests/test_k4_instructnav.py` (+ existing memory/grounding tests) |

## Checklist

- [x] **SemanticMemory2D** — region channel co-registered with grid + instance
  store `{class, embedding optional, centroid, last_seen, decaying confidence}`;
  `observe_detections(DetectionMsg)` / `observe_goal_region(GoalRegionV1)`
- [x] **Grounder v2** — typed outcomes `RESOLVED` / `MEMORY_HIT` / `UNSEEN` /
  `AMBIGUOUS`; SigLIP-2 matcher seam (string fallback offline)
- [x] **ScanBehavior** — `ScanPlanSpec` / stop yaws / recovery ladder (pure
  PlanIR-shaped dicts; no brain import)
- [x] **SearchEntity** — `FrontierScorer` protocol;
  `semantic_prior − geodesic_cost`; ring candidates generalize SearchOwner
  patterns **without editing** `search_owner.py`
- [x] Unit tests for decay, grounder outcomes, scan/search interfaces
- [x] This status note

## Constraints honored

- New/extended **pure** instructnav modules only — no `runtime.py` /
  `agent.py` / MuJoCo wiring (Opus lane)
- Prefer `DetectionMsg` / `GoalRegionV1` from `contracts/` where natural
- Existing `SemanticMemory` name kept as alias of `SemanticMemory2D`

## Remaining (out of Sol lane)

- Opus wiring: see merged [K4_STATUS.md](K4_STATUS.md) (navigator recovery +
  PlanIR system skills landed; runtime.py callback bind + hillclimb gates open)
- Opus: populate memory from sim DetectionMsg noise adapter (K5)
- Eval gates (Tier B/C SR) on frozen minival after wiring

## Test command

```bash
pytest tests/test_k4_instructnav.py tests/test_instructnav_memory.py tests/test_instructnav_grounding.py -q
```
