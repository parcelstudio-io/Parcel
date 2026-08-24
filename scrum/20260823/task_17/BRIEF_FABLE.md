# DEC-R1 — executor brief (Fable → Opus) · 2026-08-23

Read: this file, then `README.md` (the card), `DECOMP_PROGRAM_FABLE.md` §2
(M5/M6/M7/M9), `task_14/DEC0_REGISTRY.md` §2 in full (every runtime.py pin)
and §12. Prereqs: DEC-IG-2 and DEC-FS-1 landed (import-free barrels, the
`perception/`, `memory/`, `audio/`, `simulation/`, `motion/` packages exist).
DEC-N1 (pipeline.py) may run concurrently — it never touches runtime.py or
your oracles; you never touch `navigation/pipeline.py` or its tests.

## The owner's goal
"Break up the god object; oversized-file metrics need to be fixed."
`runtime.py` = 16,724 lines; `RobotRuntime` = 350 methods, 288 `self`
attributes, 1,393-line `__init__`. This card is the pure exodus: it moves
**zero state** and is judged on the file shrinking (target **≥ −1,500
lines**, or a written reason) with method count falling or unchanged, attr
count unchanged, marker count falling, and the safety oracles green with
every ported pin named.

## Verified inventory (integrator's AST sweep — your worklist, in order)

A. **Module-level pure code, lines 667–1236 (~570 lines)** — the scene
   report family: `scene_evidence_phrase`, `scene_bearing_words`,
   `_scene_distance`, `_scene_thing`, `_learned_map_scene_rows`,
   `scene_report` (128 lines — a >100-line function; keep its NAME when
   moving, or split it below 100), `_scene_closest`, `_is_person_track`,
   `scene_fact_lines`, `_place_matches`, plus `_polygon_centre`,
   `_dynamic_agent_payload`, `_camera_query_from_directive`, and the
   `SCENE_*` / `SCENE_HONESTY_NOTE*` / `SCENE_EVIDENCE_PHRASES` constants
   they use. Destination: **`perception/scene_report.py`** (the rendering
   of perception evidence into words). Importers of these names from
   `parcel_robot.runtime` (tests: `scene_report` ×3, `scene_fact_lines`,
   `scene_bearing_words`, `scene_evidence_phrase`, `SCENE_*` ×~8,
   `_camera_query_from_directive` ×1) are rewritten to the leaf — no
   re-export left behind. Inside runtime.py the names stay BOUND by a
   leaf import (`from parcel_robot.perception.scene_report import
   scene_report, …`) so any namespace patch keeps working (DEC-0 §12.1).
B. **Stop-predicate helpers** `_is_zero_command`, `_finite_command_values`,
   `_command_translates`, `_finite` → **`core/command_predicates.py`**.
   Digest-pinned (`tests/test_nominal_stop_wiring.py:923`, TRANSITIONAL):
   the scanner reads top-level symbols per file; port by adding the key
   `"src/parcel_robot/core/command_predicates.py"` with the SAME digests
   (`ast.unparse` is position-independent — a pure move re-verifies
   bit-for-bit) and removing the three names from the `runtime.py` key in
   the same edit. Keep `_is_zero_command` bound in runtime.py's namespace
   (the `:948` INCIDENTAL substring pin reads `_dispatch_active`'s source,
   which still calls it by that name).
C. **`CameraStreamConfig` (109 lines) + `CAMERA_STREAM_CONFIG_KEYS`** →
   **`camera_channel/stream_config.py`** (3 test importers rewritten).
   Pure config DTO; verify it holds no runtime state.
D. **The four `@staticmethod`s (118 lines):** `_plan_acknowledgement`,
   `_settle_acknowledgement`, `_load_personality_policy`, `_ask_revision`
   — become module functions in their feature home (acknowledgement
   phrasing → `voice/`; personality policy → `prompting/`; `_ask_revision`
   → wherever its callers' concept lives — read it) and every
   `self._name(` call site becomes a plain call. Method count −4.
E. **Five self-free methods (124 lines):** `_scene_learned_map`,
   `_learned_map_vocabulary` → `online_map/` leaf; `_venue1_declared_origin`,
   `_venue1_depth_available`, `_venue1_open_failure` → `camera_channel/`
   leaf (venue composition). Same treatment as D.
F. **Read-only methods (51 methods, 1,694 lines; no `self.x =`, no
   `self.method()` calls, no `with` locks)** — the reservoir that reaches
   −1,500. Convert to pure module functions ONLY where (i) the function
   reads ≤ 5 distinct `self` attributes (pass them as explicit parameters;
   the method body becomes a 1–3 line delegate, or the call sites call the
   function directly), (ii) the method is not named in any DEC-0 §2 pin
   you have not ported, and (iii) it is not on the control path pinned by
   `test_nm1_*` reachability (`_control_loop` edges) or the r24 lock
   scans. Start with the biggest that qualify: `_evaluate_dispatch_input_health`
   (161 — CHECK nm1 first), `_roam_sense` (65), `_p1b_map_settings` (61),
   `_venue1_composition` (58), `_roam_limits` (48), `_ask_revision` (46),
   `_realtime_recall` (40), `_camera_ingress_enabled` (40),
   `_ot2_latest_rgb` (39), `_p1b_semantic_source` (37), `_p1b_scene_id`
   (34), `_resolve_emote_catalog` (33), `_activity_verification_state`
   (33), `_venue1_resolve_venue` (32), `roam_config` (31)… Destinations by
   family (M6): `roam_*` → `navigation/roam_policy.py`; `_p1b_*` →
   `online_map/runtime_settings.py`; `_venue1_*` → `camera_channel/venue.py`;
   `_ot2_*` → `owner_model/`; `_realtime_*` → `realtime/`; `_curiosity_*`
   → `voice/` or `brain/` (read the concept). One module = one concept,
   ≤ 600 lines each. Do NOT touch `_dispatch_active`, `_finalize_for_actuator`,
   `_nominal_stop_ramp_tick`, `_regate_nominal_stop`, `snapshot`,
   `_control_loop*`, `start`, `close`, anything under a lock — DEC-R2+.
G. **Constants (62 assignments, 114 lines)** move only with their family
   (SCENE_* with A). `SAFETY_*`, `MISSION_LOG_*`, `TRANSCRIPT_ORIGIN_*`,
   `POSE_LOST_*` stay this card.
H. **Markers:** every `# ---- CARD` line inside moved code dies (M7); the
   destination module docstring carries the one-line invariant. Net
   marker count must fall (46 in runtime.py today; the ratchet's
   `test_no_new_card_markers` enforces the tree total).

## Binding rules from DEC-0 (read §2.8 "blast radius" before the first edit)
- **Vacuity (F1):** `test_r24_lock_discipline` scans `class RobotRuntime`
  and `__init__` for lock construction; `test_nm1_*` scans runtime.py by
  path for forbidden `vlm_veto` imports and for control-loop reachability;
  `test_ot2_identity:681-707` iterates a loop inside the class; the
  anti-vacuity floors (`r24:701, :762, :1020, :1595-1603`; `nm1:396`) must
  end HIGHER or equal, never lower. This card moves no locks and no
  control-path code, so r24 should not move at all — run it first and
  last; if it reddens or its floors drop, you moved something you must not.
- **`admission.py` rosters (F2):** any new module that reads
  `store.section(` joins `_PRODUCT_CONFIG_SOURCES`; a new file that reads
  a runtime region joins `_RUNTIME_REGION_SOURCES` (`admission.py:389-410`;
  `test_cap1_admission.py:267-276` fails on omission).
- **Namespace patching (§12.1):** `explicit_affect_from_text`,
  `http_service_health`, `finalize_command`, `time`, `AWARENESS_TICK_S`,
  `build_speech_stack`, `apply_reactive_safety`, `time_to_collision_verdict`
  must remain bound names in `parcel_robot.runtime`. Never alias imports.
- **Long-function ratchet keys by leaf NAME:** moving `scene_report`
  under the same name is free; renaming a >100-line function reddens as
  new debt. Splitting one into <100-line pieces is the improvement.
- **The private-symbol importers** (`_RealtimeLedgerMirror`,
  `_LockedNavigationChannel`) are state-bearing → they STAY this card.
- `RobotRuntime` public method signatures, `__init__`, locks, the 17
  `on_*=self._method` callbacks: untouched.

## Deliverables
- The moves above; `runtime.py` import block updated to leaves.
- `tests/test_decr1_pure_exodus.py` (thin): each moved function importable
  from its new home; one behavior spot-check per destination module
  (e.g. `scene_report` on a fixed observation renders the same text as a
  frozen expected string you capture BEFORE moving — capture first, then
  move, then compare).
- Ported pins named: `test_nominal_stop_wiring` key, any `test_*` import
  rewrites, admission rosters, `test_ot2_identity`/`test_p1b_*` paths if a
  `_p1b_*`/`_ot2_*` method moved (§2.8 items 3, 6).
- `scrum/20260823/task_17/DECR1_STATUS.md` (M9): runtime.py lines
  before/after; RobotRuntime methods/attrs before/after; new modules with
  line counts; markers before/after (file and tree); ratchet numbers
  (oversized 45 → ?, long-fn 153 → ?, markers 178 → ?); pins ported
  (file:line, old→new); suites with counts; what you left and why.

## Proof (guard wrapper `--label decr1`; TMPDIR unset; never `-n auto`; never `--tier`)
`tests/test_r24_lock_discipline.py`, `tests/test_nominal_stop_wiring.py`,
every `tests/test_nm1_*`, `tests/test_ot2_identity.py`,
`tests/test_p1b_map_learns.py`, `tests/test_cap1_admission.py`,
`tests/test_runtime.py`, `tests/test_dec0_debt_ratchet.py`,
`tests/test_decig2_import_ratchet.py`, the new test — then one full
`-m 'not slow' -n 8 --dist loadfile -p no:cacheprovider`. Known flakes:
`test_yield_policy` (order-dependent), `test_dynamic_costs…performance`
(R26). Ruff clean, zero `noqa`, no `ruff format` on files failing at HEAD.

## Rules
Git READ-ONLY; targeted edits only (runtime.py is 16k lines — never
rewrite it whole; delete moved blocks by exact line ranges you verified
twice); no behavior change; no new `# ---- CARD` lines; owner's live
stack and memory store untouched; reduced testing policy (capability
proof + the ported oracles, nothing combinatorial). Finish the whole
worklist A–F; where an item is blocked by a pin you decide not to port,
say so in the STATUS with the pin's file:line.
