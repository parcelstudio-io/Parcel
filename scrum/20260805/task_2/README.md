# Sprint 2026-08-05 · task_2 — "go to the sidewalk" admission regression + voice→nav e2e eval

**Owner report:** typing "go to the sidewalk" returns *"I couldn't admit that
command as a safe plan yet. Please clarify or let me inspect the scene
again."* — the robot doesn't try, can't run any navigation task. It got
worse. Owner asked for a proper integration eval: identity → plan →
execute, ending (post camera work) at identify-place-from-camera-and-arrive.

## Root cause (reproduced live, twice)

The in-flight K6 voice-lane work routes nav directives through
PlanSketch→PlanIR admission. Two admission rejections dead-ended into one
generic refusal (`agent.py::_admit_local_sketch` catch-all):

1. **Live sim:** `target_not_grounded` — the NavigateTo contract required
   the target to be **visible at admission time**
   (`brain/validator.py` contract table). The robot spawns not facing the
   sidewalk → frustum entity list lacks it → refused before the resolution
   ladder (frustum → memory → scan → frontier → honest report) could run.
   The original task_6 frustum bug reintroduced one layer up. The mistake
   was even codified: eval case `ungrounded_sidewalk_rejected` treats the
   rejection as correct.
2. **Cold runtime:** `camera_stale` — same generic dead-end, no honest
   reason given.

## Fix (landed, working tree)

- `brain/validator.py` — NavigateTo admission requires a **searchable**
  target, not a visible one: `target_grounded` removed from the contract
  (grounding-with-recovery is the skill's own ladder; its recovery
  vocabulary — rescan/alternate_candidate — is what makes that safe). The
  precondition token remains enforceable for plans that declare it
  explicitly.
- `agent.py` — `_admission_failure_reply`: refusals name the reason
  (camera/LiDAR stale, emergency stop latched, owner not visible/heading
  unknown); generic text only as last resort.
- Pins updated: `tests/test_plan_sketch.py` (compiled preconditions),
  `tests/test_companion_brain_eval.py` (annotated the mechanism-test
  fixture so the old semantics don't get re-read as the spec).

**Verified live:** "go to the sidewalk" now replies *"Okay—I'll move onto
sidewalk and verify it."*, admits, dispatches NavigateTo, robot walks.

## New evals (the owner's ask)

- `tests/test_navigation_admission_regression.py` (default gate, 6 tests):
  contract pin; the exact unseen-target-admits regression; explicit
  declaration still enforced; honest replies; **full runtime text-path**
  admits sidewalk / reports stale camera honestly.
- `tests/test_voice_nav_e2e.py` (`-m slow`): real MuJoCo sim + full
  RobotRuntime, entering at `handle_text` — the layer NAV_INSTRUCT
  bypasses (why its greens never caught this). Four staged assertions per
  case: admission (never generic refusal) → task exists → terminal state
  within budget → **arrival by the K0 GoalRegion authority AND the
  system's own verified success** (claim without predicate fails, and vice
  versa). Cases: sidewalk region, towards-lamppost band. When
  CameraChannel + detector land, the grounding source swaps behind the
  same contracts and this suite becomes the identify-from-camera
  acceptance test unchanged.

## Found and fixed by the new eval: the full defect chain (2026-08-06)

The e2e gate surfaced four more defects behind the admission one; all
diagnosed via workflow `wf_3fc8983d-a5b` (high confidence, file:line) and
fixed behind the gate:

1. **Speed authority split** — the 2026-08-04 speed raise missed
   `configs/navigation/default.yaml safety.max_vx` (0.45), silently capping
   clear-path speed while grid cruise claimed 0.85. → 0.9 (actuator still
   bounded by reactive/TTC gates + arbiter limits).
2. **Fixed slow-scale cliff** — `apply_collision_brake` used a flat ×0.35
   whenever a person <2.5 m or obstacle 0.8–1.2 m (observed steady
   0.2975 = 0.85×0.35) plus a stop/creep limit cycle at the 0.8 m
   boundary. → `predictive_mode: projected_speed_cap` (proportional, zero
   exactly at stop_distance_m; hard boundary unchanged) +
   `person_slow_m: 2.0` to stop double-banding with the runtime gate.
3. **Align cut at every waypoint flap** — `align_enter_deg` 28° cut vx to
   zero at effectively every corner (full stop + ~1 s re-align + ramp from
   zero). → 55° (cos² curvature slowing already covers moderate error).
4. **`inside` terminal verification structurally failed on furnished
   sidewalks** — required a same-tick frustum re-sighting of a region you
   are standing on (centroid outside FOV) and treated street furniture in
   the destination region as blocking obstacles. → committed-polygon
   authority for static regions + in-region lidar-return exclusion
   (verification only; reactive safety untouched).
5. **Same-label region instances read as AMBIGUOUS** — after a scan, both
   street sidewalks are in memory and "go to the sidewalk" failed with a
   clarification. → stuff-class interchangeability: same-label region
   candidates tie-break to nearest (`interchangeable` threaded through
   `resolve_grounding`/`GrounderV2.ground`/`ground_query`; objects keep
   tier-D clarification semantics).
6. **Budget ordering inverted** — navigator honest give-up (~250 s) > step
   timeout (120 s): failures arrived as blunt `step_timeout`. → watchdog
   window 400→200 steps, NavigateTo contract 120→240 s, eval deadline
   150→270 s (inner < step < eval restored). Silent
   `except RuntimeError: pass` on navigation submits now records the
   rejection into navigation detail.
7. **`--static-city` placed frozen mannequins on route start points** —
   one permanently walled the corridor north of spawn. → disabled dynamic
   city leaves mocap bodies at XML rest poses.

**Result: `pytest -m slow tests/test_voice_nav_e2e.py` → 2 passed, 1
xfailed.** Sidewalk and towards-lamppost arrive with both the system's
verified success and the independent K0 polygon/band predicate.

## Open (pinned as xfail in the e2e suite)

`test_go_to_the_sidewalk_with_pedestrian_traffic`: approach-pose selection
is traffic-blind — the sidewalk goal point lands beside the crosswalk
pedestrian stream and person-stop safety (correctly) never accumulates the
final metre; ramp-from-zero between passes compounds it. Owner: the
dynamic/social planning card (proxemic cost on goal placement +
yield-advance pacing). The xfail flips to a hard gate when it lands.

**Eval-row note:** the grounding/verification changes will move headless
NAV_INSTRUCT candidate rows (baseline rows stay frozen); the next minival
run should be read as the post-fix candidate, not compared silently.

## In-flight tree reds (not this task's; owners: K6/K8 executors)

All pass on clean HEAD `4f6342d`; broken by uncommitted executor work:
`test_barn_v8_policy_bundle` (sidecar RuntimeError),
5× `test_runtime` text-command replies (K6 now routes follow/stay through
admission; fixtures lack owner heading → `owner_heading_unavailable`),
`test_intelligence` scan-note rename, 2× `test_embodied_plan_eval`.
Deltas from this task verified green in isolation (104 brain/voice tests +
6 new + suite otherwise 1872 passed).
