# K4 Status — SemanticMemory2D + Grounder v2 + ScanBehavior + SearchEntity

**Card:** K4 · **Owners:** Sol (pure) + Opus (wiring) · **Date:** 2026-08-05 ·
**State:** DONE for pure modules + navigator/PlanIR wiring; **hillclimb Tier B/C
gates UNVERIFIED** (no frozen minival SR win claimed)

**Plan refs:** [ADJUDICATION.md](ADJUDICATION.md) kickoff K4;
[`docs/INSTRUCTION_NAV_HILLCLIMB.md`](../../../docs/INSTRUCTION_NAV_HILLCLIMB.md)
rungs 1–5; Sol half in [K4_SOL_STATUS.md](K4_SOL_STATUS.md).

## Delivered

### Sol (pure)

| Artifact | Path |
|---|---|
| SemanticMemory2D | `src/parcel_robot/instructnav/memory.py` |
| Grounder v2 | `src/parcel_robot/instructnav/grounding.py` (`GrounderV2`) |
| ScanBehavior helpers | `src/parcel_robot/instructnav/scan.py` |
| SearchEntity frontier scoring | `src/parcel_robot/instructnav/search_entity.py` |
| Package exports | `src/parcel_robot/instructnav/__init__.py` |
| Unit tests | `tests/test_k4_instructnav.py` (+ memory/grounding tests) |

### Opus (wiring)

| Artifact | Path |
|---|---|
| Recovery glue | `src/parcel_robot/navigation/instructnav_recovery.py` |
| Navigator rewire | `src/parcel_robot/navigation/pipeline.py` |
| PlanIR system skills | `brain/validator.py`, `compiler.py`, `runtime_adapter.py` |
| Wired-path tests | `tests/test_k4_opus_wiring.py` |

## Checklist

- [x] **SemanticMemory2D** — region channel + instance store with decay
- [x] **Grounder v2** — typed `RESOLVED` / `MEMORY_HIT` / `UNSEEN` / `AMBIGUOUS`
- [x] **ScanBehavior** — pure PlanIR-shaped specs + navigator rotate/dwell recovery
- [x] **SearchEntity** — `semantic_prior − geodesic` frontier scoring in navigator
  (SearchOwner untouched; follow path unchanged)
- [x] UNSEEN → ScanBehavior → SearchEntity → honest report ladder (fail-closed)
- [x] Baseline mode (`instructnav_recovery=False`) still frustum-only refusal
- [x] PlanIR admits `ScanBehavior` / `SearchEntity` as system skills (not planner-authored)
- [x] GoalArbiter receives `search_entity` SE2 proposals during frontier crawl
- [x] DetectionMsg-shaped `extras["detections"]` ingest into SemanticMemory2D
- [x] Unit + wiring tests green
- [ ] Hillclimb Tier B ≥90% / Tier C ≥70% & +10pp on frozen minival — **not run**

## Constraints honored

- No Nav2 / ROS authority migration
- No teleports; no oracle / ground-truth on the agent path
- Fail-closed: ambiguous → clarify; exhausted recovery → honest report
- SearchOwner / FollowFormation not edited

## Remaining gaps (honest)

1. **Hillclimb gates** — wired paths are unit/integration tested; frozen
   nav-instruct minival SR is still unproven (see backlog U24 / U28).
2. **SigLIP-2 weights** — GrounderV2 string-fallback when weights missing (U25).
3. **Runtime.py callbacks** — PlanIR `ScanBehavior` / `SearchEntity` dispatch
   hooks exist on `SemanticTaskRuntimeAdapter`, but `RobotRuntime` does not yet
   pass navigator-bound callbacks (same pattern as early SearchOwner wiring).
   Navigator recovery inside `NavigateTo` / `DirectiveNavigator` is the live path.
4. **K5 DetectionMsg noise adapter** — memory accepts DetectionMsg mappings;
   full sim noise adapter population remains K5.
5. **A* geodesic costs** — SearchEntity currently uses Euclidean stand-in for
   geodesic cost (injected seam ready for grid_v1 path length).

## Test commands

```bash
.parcel/bin/python -m pytest tests/test_k4_instructnav.py \
  tests/test_instructnav_memory.py tests/test_instructnav_grounding.py -q

.parcel/bin/python -m pytest tests/test_k4_opus_wiring.py \
  tests/test_navigation.py::test_unknown_sidewalk_uses_bounded_multiview_semantic_search \
  tests/test_semantic_navigation_regressions.py -q
```
