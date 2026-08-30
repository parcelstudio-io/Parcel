# W3 · WORLD-IDENTITY-1 — the loaded world's identity is passed explicitly to each navigator

**Executor:** Opus · **Verifier:** Fable · From Sol's review (`research/20260829/CLAUDE_TASK2_REVIEW.md` blocker 4) and `scrum/20260829/task_2/C1_POI_ORACLE.md` wave-B row.

## Build
1. `DirectiveNavigator(world_identity: WorldIdentity | None = None)` / `from_config(..., world_identity=…)`: a small typed value (scene id + source + digest) supplied by the composition root that loaded the world — `runtime.py`'s sim adapter, `sim.py:204`, `web_panel.py:202`, `HeadlessCityWorld` → harness, the NAV_INSTRUCT / mutation-panel runners. `poi_admission` consults the explicit identity first; the process-scoped published scene (C1-F1) becomes the FALLBACK, logged as such (`identity_source: explicit|published|none`).
2. No behaviour change: every path that published before now also passes explicitly; `no_scene` / `scene_mismatch` reasons unchanged.
3. Hunks in `runtime.py` confined (record the avoided dirty hunks); `pipeline.py` net-negative or unchanged (report the count).

## Acceptance
- NAV-GEN-1 A0 (`--arms A0`, own scratch) rows **byte-identical** to the post-C1-F1 rows (crosswalk_a 0/90; frozen 16/16 known_poi; `identity_source=explicit` on every row); minival digest `021b67ab…`; mutation panel {agreement 4, authority_disagreement 1} in an isolated worktree; `tests/test_poi_admission.py` + the F2/F3 fixtures pass with the fixtures now supplying an explicit identity where they can.
- A test that a navigator built with NO identity and NO published scene refuses (`no_scene`), and one that an explicit identity wins over a stale published scene.
