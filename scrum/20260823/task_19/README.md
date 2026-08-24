# DEC-N1 — navigation/pipeline.py: pure leaves out (D05 start) · Fable 2026-08-23

Program: `DECOMP_PROGRAM_FABLE.md` §2 M5/M6/M7/M9, §3. Prereqs: DEC-IG-2 and
DEC-FS-1 landed. Runs concurrently with DEC-R1 (disjoint: you never touch
`runtime.py` or its oracles; DEC-R1 never touches `navigation/pipeline.py`
or the pins below).

`navigation/pipeline.py` = 6,604 lines; `DirectiveNavigator` = 5,764 lines,
116 methods, 113 attributes, a 356-line `__init__`, a 353-line
`_step_semantic_resolution`, a 220-line `from_config`. This card moves
**zero state**; the reducer split (D05 proper, replay parity) is DEC-N2.

## Read first — this file is unusually pinned (DEC0_REGISTRY §4, all 14 rows)
Porting rules you MUST apply in-card, each named in the STATUS:
- **Barn V8 bundle** (`tests/test_barn_v8_policy_bundle.py:155`): every
  extracted module joins `V8_ADDITIONS` in
  `evals/external/barn_v8_policy_bundle.py:48` and the bundle file count
  (117) bumps by the number added — or the frozen-tree sidecar smoke
  raises `ImportError`. The test skips without the historical bundle
  cache: check `~/.cache` for it; if it skips on this host, say
  "does not prove" in the STATUS.
- **Literal-drift table** (`tests/test_authority_no_literal_drift.py:160-172,
  :400-470`): float-literal counts keyed by path (`0.32`×5, `0.35`×6,
  `1.2`×1 in pipeline.py). Moving N literals to module M lowers the
  pipeline entry by N and adds `("navigation/<M>.py", v)` — the stale-entry
  check reddens otherwise.
- **Pose archon** (`tests/test_pose_authority_archon.py:128,:135`): the
  hard-coded filename tuple extends with any new module containing a
  `_pose_in`/`pose_in` call.
- **`_build_grounder` + `PlaceGrounder` move TOGETHER**
  (`tests/test_c3_cutover.py:410` patches `pipeline_module.PlaceGrounder`
  then calls `pipeline._build_grounder`): put `_build_grounder` and
  `_semantic_source_policy` in `navigation/grounder.py` (where
  `PlaceGrounder` is defined — verify) and re-point the test's patch
  target to that module. The import-time invariant at `:1163`
  (importing pipeline installs no semantic source) must survive.
- **Guarded optional imports stay in pipeline.py TEXT**: `_HAS_INSTRUCTNAV`
  (`test_import_order_no_cycle.py:65`), `from .traffic_aware import
  RampMemory` + `_HAS_TRAFFIC_AWARE` (`test_approach_traffic_wiring.py:199`),
  and no module-scope `perception_abstention` import
  (`test_perception_abstention.py:811` — add every new module to
  `V8_REPLACEMENTS`/`V8_ADDITIONS` scan or it is uncovered). The helpers
  `_is_genuine_absence`, `_reraise_if_not_absent`, `soft_import_health`
  may move (to `navigation/optional_deps.py`), the flags and guarded
  import statements may not; `soft_import_health` keeps a bound name in
  pipeline.py (1 test imports it from there — rewrite that test instead).
- **VACUITY RISK** (`tests/test_value_directed_search.py:985`): the scan
  reads ONE file for `.goal_arbiter.resolve(` sites and the absence of
  `.proposer_bus.poll(`. Do not move any resolve site out of pipeline.py
  this card; if you do, extend the scan to the new file in the same edit.
- **Class attributes stay class attributes**: `ROUTE_MEMORY_RANGE_M`,
  `ROUTE_MEMORY_STALL_STEPS`, `UNROUTABLE_GOAL_STEPS`,
  `GRID_REPLAN_INTERVAL_STEPS` (`test_rm2_…:1359,:1590`); the six
  route-memory methods pinned by `inspect.getsource`
  (`test_rm3_…:179-222`) stay methods with their literal counter
  statements; `from_config(route_memory=False)` default stays.

## Build (pure only; in this order)
1. Module-level pure functions at the file tail (L6290–6604, ~315 lines):
   `_wrap_to_pi`, `_polygon`, `_position`, `_translated_goal_region`,
   `_candidate_xy`, `_candidate_obstacle_ids`, `_candidate_ground_distance_m`,
   `_ray_hits_target`, `_current_semantic_candidate`, `_metadata_float`,
   `_refusal_label`, `_label_matches`, `_motion_feedback_is_settled` →
   `navigation/candidate_geometry.py`; `_person_payload_entries`,
   `_dynamic_tracks_from_observation` → `navigation/person_tracks.py`.
   Names stay bound in pipeline.py by leaf import.
2. Module-level head helpers (L199–492): `_build_grounder`,
   `_semantic_source_policy` → `navigation/grounder.py`; the three
   soft-import helpers → `navigation/optional_deps.py`.
3. Self-free methods: `_person_keepout_policy`, `_lock_on_reference_xy`,
   `_owner_xy`, `_build_arrival_goal_region` → module functions in
   `person_keepout.py` / a new `lock_on_geometry.py` / `arrival_semantics.py`
   (existing owners — verify no cycle with the DEC-IG-2 ratchet; the
   `arrival_semantics ↔ goals` 2-cycle is grandfathered, do not widen it).
4. `from_config` (220 lines, classmethod, public): keep the classmethod
   and its 15-kwarg signature; split its BODY into <100-line pure
   builders (`_navigation_config_sections`, `_planner_from_config`, …) in
   `navigation/pipeline_config.py`. The long-function ratchet keys by
   leaf name — never rename a >100-line function; split it.
5. Read-only methods (no `self.x =`, no `self.method()`, no locks) with
   ≤ 5 `self` reads → parameterized pure functions in the owning leaf;
   the method becomes a delegate or the call site calls the function.
   Skip anything in the pinned lists above and anything on the
   `step()` → `_step_*` path this card.

Every `# ---- CARD` marker inside moved code dies (M7). Every new module
≤ 600 lines, one concept each, no `utils/`.

## OWNS
`navigation/pipeline.py` (removal + import hunks), the new/extended
navigation leaves, `evals/external/barn_v8_policy_bundle.py:48` and its
count, the pins named above (their path/roster lines only),
`tests/test_decn1_pure_leaves.py` (thin: importable from new home + one
behavior spot-check per module, captured BEFORE the move), this folder
(`DECN1_STATUS.md`).

## MUST NOT TOUCH
`DirectiveNavigator` state/attributes/locks, `step()` and `_step_*`
bodies, `runtime.py`, `evals/` beyond the roster line, frozen bundles
and fixtures, git, the owner's stack/store.

## Metrics (M9)
pipeline.py lines before/after (target ≥ −800 or a written reason);
DirectiveNavigator methods/attrs (methods may fall, attrs unchanged);
long-function count 153 → lower (from_config split); markers; ratchets
green; pins ported (file:line, old→new).

## Prove (guard `--label decn1`; never `-n auto`; never `--tier`)
`tests/test_navigation.py`, `test_authority_no_literal_drift.py`,
`test_pose_authority_archon.py`, `test_import_order_no_cycle.py`,
`test_approach_traffic_wiring.py`, `test_perception_abstention.py`,
`test_c3_cutover.py`, `test_rm2_*`, `test_rm3_*`, `test_value_directed_search.py`,
`test_barn_v8_policy_bundle.py` (note skip), `test_dec0_debt_ratchet.py`,
`test_decig2_import_ratchet.py`, the new test — then one full
`-m 'not slow' -n 8 --dist loadfile -p no:cacheprovider` COORDINATED with
DEC-R1: only one full-suite run on the host at a time (message the
integrator before starting yours). Ruff clean, zero `noqa`.
