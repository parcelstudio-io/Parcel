# P4 Status — Route memory + learned proposers (sim)

**Phase:** 4 (sim) · **Date:** 2026-08-05 · **State:** DONE (MVP pure modules +
CI stubs; learned proposers gated; no hardware; no Nav2; no model-authored
velocity)

Binding: [ADJUDICATION.md](ADJUDICATION.md) Owner amendment P4 + D7
(GuideNav-adapted teach-and-repeat → CityWalker A/B → VLFM into SearchEntity).
Ledger: [hardware-readiness.md](hardware-readiness.md) **HR-12**, **HR-13**,
**HR-14**.

## Delivered

| Artifact | Path |
|---|---|
| Route memory package | `src/parcel_robot/route_memory/` |
| Keyframe / path store | `…/route_memory/memory.py` |
| Stub VPR (rendered-frame stand-in) | `…/route_memory/vpr.py` |
| Teach-and-repeat API | `…/route_memory/teach_repeat.py` |
| Gated SE2Goal proposer | `…/route_memory/proposer.py` |
| CityWalker fail-closed adapter | `…/route_memory/citywalker.py` |
| VLFM heuristic scorer | `…/route_memory/vlfm.py` |
| Thin runtime/test hook | `…/route_memory/runtime_hook.py` |
| CI tests | `tests/test_p4_route_memory.py` |
| Hardware-readiness HR-12/13/14 | [hardware-readiness.md](hardware-readiness.md) |

## Checklist

- [x] **Route memory store** — pose + optional embedding stub keyframes;
  JSON save/load; `does_not_prove` on every path
- [x] **Teach-and-repeat** — `teach(poses)` / incremental teach / `follow(path_id)`
  → `RouteMemoryProposer` (SE2Goal + TTL only)
- [x] **GoalArbiter-compatible** — ProposerBus registration; TTL expiry;
  lethal-cost veto still applies at arbiter
- [x] **Promotion gate** — `gate_enabled=False` by default; gated proposers
  emit `None`
- [x] **CityWalker adapter** — vendor detect (`third_party/CityWalker`);
  fail-closed / UNVERIFIED skip when weights/torch/live path unavailable;
  offline cached-waypoint path for sim A/B; CI does not require torch
- [x] **VLFM scorer stub** — `HeuristicVLFMScorer` implements `FrontierScorer`
  for SearchEntity `select_frontier`; labeled UNVERIFIED
- [x] No model-authored velocity; no Nav2; no hardware wiring into default
  `RobotRuntime`

## Explicit non-claims / honest gaps

- **Stub VPR ≠ CosPlace / MegaLoc.** Embeddings are deterministic hash/pose
  stand-ins for rendered-frame wiring only (HR-12).
- **No GuideNav Reloc3r.** Pose regression and 5 Hz Orin NX budgets are
  unmeasured (see backlog U27).
- **CityWalker live weight inference is not wired.** Checkpoint may exist on
  disk; MVP only accepts cached offline waypoints when the gate is on, else
  skips with UNVERIFIED. No public sample trajectory ships in
  `third_party/CityWalker` (playlists only) — bring your own recorded sim walk
  JSON for A/B.
- **Heuristic VLFM ≠ real VLFM.** No VLM value-map; table/radial prior only
  (HR-14).
- Learned proposers are **not** admitted to the default runtime. Promotion
  still requires replay → sim shadow → sim active (D7 / A-doc ladder).

## Test command

```bash
pytest tests/test_p4_route_memory.py -q
```
