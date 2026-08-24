# A2 NAV-GLUE — executor brief (Fable → Opus) · 2026-08-24

The decision card: fix the three glue defects NAV-CORE measured, then re-run
the frozen corpus unchanged; its N1 decides retain-vs-simplify for M1.
Grounding: `research/20260824/nav-core/{RESULTS.md, VERDICT.md,
REFUTER_4B_REMEASURE.md}`; plan row A2 in `IMPLEMENTATION_PLAN.md`.

## Fix 3 — ONE clearance authority (the row that caps both arms; a DESIGN change)
Today: planner inflates 0.42 m (`footprint 0.32 + map_safety_margin_m 0.10`)
while the pipeline brake stops at 0.80 m and the reactive gate demands
0.752 m at grid_v1's 0.85 m/s — 8/8 sampled stalls sat inside a brake ring
with the route still `status=planned` (NAV-CORE `stall_probe.py`).
The agreement number ALREADY EXISTS: `ReactiveSafetyPolicy.planner_inflation_m`
(`navigation/reactive_safety.py:416`, "P1-E audit §6, one number two
consumers") — but no call site passes it, and
`navigation/grid_navigator.py:21 _planner_coupling_ring_m` caps tighter-only
BY DESIGN because raising inflation moves planned routes and re-cuts frozen
navigation evidence — "DOOR-1's HALTED item H-2 … belongs to whoever owns
those baselines". This card IS that owner, by integrator delegation:
1. Wire `policy.planner_inflation_m` (and `person_stop_m`'s ring where the
   map cells are people) into `GridPlannerConfig.gate_clearance_m` at both
   production sites (`grid_navigator.py:292` and `navigation/search_owner.py`).
2. Remove/bypass the tighter-only cap **under a FORMAL RECORDED RE-FREEZE**:
   pre-register in your STATUS which frozen navigation evidence moves
   (NAV_INSTRUCT v4 rows, MOVE-1/ROAM unit baselines, any literal-drift/
   authority table entries — check `tests/test_authority_no_literal_drift.py`
   and the barn V8 roster if `pipeline.py` changes), re-run the owning
   harnesses, record old→new with the cause ("planner now agrees with the
   commissioned gate"), and NEVER quietly edit a frozen number. The E3 rule:
   a moved digest is a recorded decision or a STOP.
3. **Safety floors are untouchable**: `obstacle_stop_m` 0.65, the gate's
   enforcement in `apply_reactive_safety`, `finalize_command` — the planner
   moves UP to agree with the gate; the gate never loosens toward the planner.
4. Brake→replan signalling: when the pipeline brake or reactive gate holds
   the body while a route is `planned`, the planner must learn it (replan
   with the blocking cell/ring marked) instead of silently stalling —
   NAV-CORE's `silent_stall_step_limit` (33/60 A, 31/60 B) must become
   typed outcomes (replanned or honest failure), never a step-limit death.

## Fix 1 — region/object kind tolerance
`goals.semantic_goal_from_directive("bed")` → `kind="region"`;
`semantic_map.learned_map_candidates` stamps `kind="object"`;
`ObservationSemanticMap.query` requires equality ⇒ all 12 `bed` episodes
`not_found`. Fix at the ingress (emit region kind where the place-class
table says so) or make the query kind-tolerant — pick one, say why, port
`tests/test_navcore_probe.py`'s pin.

## Fix 2 — off-oracle arrival verification
`_semantic_arrival_verified` writes `target_surface_unobserved` because the
learned map has no polygon and no `associated_lidar_ids` (15/60 arm-A
episodes reached the place and could not claim it). Add the off-oracle
verification path: metric band + detector re-confirmation (fresh detection
of the goal class within the band) — with the oracle path retained where
oracle evidence exists. NO arrival claim from covariance alone (NAV-CORE R3:
false arrival at p=0.9922 — that case must REFUSE until A3's calibration
lands; a conservative interim: require detector confirmation whenever the
localizer's NEES calibration is unproven, i.e., always for now).

## Then: the decision
Re-run `research/20260824/nav-core/bench.py --stage corpus` UNCHANGED
(same corpus, seeds, bars). Arm A ≥ 0.80 ⇒ retain the semantic ladder for
M1; only arm B ≥ 0.80 ⇒ simplify (M1 ships arm B's shape + typed refusal;
fixes 1–2 remain for post-M1 semantics). Report N1/N4 before/after per fix
where separable. Do not tune past the decision.

## Rules
Guard label `a2-navglue`; every pytest through the wrapper; never `-n auto`;
never `ci_gate --tier`; git READ-ONLY; targeted edits; no `noqa`; both DEC
ratchets + `test_navcore_probe.py` + the navigation suites
(`test_navigation.py`, `test_grid_planner.py`, `test_grid_navigator.py`,
`test_dynamic_costs.py` [R26 perf pin re-run alone if red],
`test_authority_no_literal_drift.py`, `test_value_directed_search.py`,
`test_c3_cutover.py`, `test_rm2/rm3`) green with every port named; the
pipeline.py pins from `scrum/20260823/task_14/DEC0_REGISTRY.md` §4 apply to
any pipeline.py hunk. runtime.py untouched. Owner's stack untouched. Write
`scrum/20260824/task_2/A2_STATUS.md` (short register: fixes, re-freeze
table old→new with causes, corpus re-run N-rows, the DECISION, suites).
Do NOT commit.
