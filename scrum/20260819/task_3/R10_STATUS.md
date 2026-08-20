# R10 task_3 — arrive like you mean it — EXECUTOR STATUS

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_3/README.md` (REVISED
2026-08-20 on bench evidence) · **Executor:** Claude Opus (agent) ·
**Auditor:** Fable
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Depends on:** R8 (`20260819/task_1`, narration wire), R9 (`20260819/task_2`,
e-stop) — `lane.py`, `protocol.py`, `ingress.py` FROZEN for this card and
untouched.
**Evidence read before the card:**
`<scratchpad>/csbench/reports/bench_navmodel.md`,
`res_semnav.md`, `res_grounding.md`. Scratchpad root
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`.

> **Document discipline.** This file is written INCREMENTALLY, section by
> section, as each piece completes — the R8 lesson (an executor died after
> finishing its code and before writing anything down). Sections below appear in
> the order they were finished, not in card order.

---

## §0 — File map, written BEFORE any edit (card requirement)

The card requires the exact navigation files to be mapped here before editing.
This section was written first; the git working tree was clean at that moment
(`git status` clean, HEAD `8473a51`).

### OWNED — files this card will edit

| File | Why it is touched | Card work item |
| --- | --- | --- |
| `src/parcel_robot/navigation/arrival_semantics.py` **(NEW)** | The local arrival-semantics table keyed by semantic class (region→inside, portal→near+do-not-cross, object→near, person→social) plus the hybrid-relation validator (`resolve_relation`) and the face/etiquette policy the model may never override | 2, 4 |
| `src/parcel_robot/navigation/orbit_feasibility.py` **(NEW)** | Orbit clearance-annulus affordance test with a machine-readable cause and the blocked arc, used at admission AND mid-orbit | 5 |
| `src/parcel_robot/navigation/goals.py` | `SemanticGoal` gains the arrival-table fields (`face`, `do_not_cross`); `semantic_goal_from_directive` accepts an optional VALIDATED relation hint | 2 |
| `src/parcel_robot/navigation/pipeline.py` | In-region goal resampling for `inside` when the support-gated solver finds nothing; the give-up names the candidates tried; portal terminal etiquette (face owner, never cross) | 1, 4 |
| `src/parcel_robot/navigation/spatial.py` | Mid-orbit abort wired to the feasibility validator (the orbit controller is here) | 5 |
| `src/parcel_robot/realtime/tool_broker.py` | Declare `circle_owner` + `follow_owner(pace)`; `navigate_to` gains the optional `relation` hint and place-argument validation with a structured refusal naming nearest valid places | 2, 3 |
| `src/parcel_robot/runtime.py` | New doors (`orbit`, `follow`, place candidates) routed through the SAME router→`_admit_local_sketch` chain `navigate_to` uses; orbit admission feasibility; arrival fact carrying the ask-hint through R8's narration channel | 3, 4, 5 |
| `tests/test_arrival_semantics.py` **(NEW)**, `tests/test_orbit_feasibility.py` **(NEW)**, `tests/test_realtime_tool_broker.py`, `tests/test_navigation_inside_resampling.py` **(NEW)** | Pins for every behaviour above | DoD |
| `scrum/20260819/task_3/R10_STATUS.md` | This document | DoD |

### NOT TOUCHED — frozen by the card

`lane.py`, `protocol.py`, `ingress.py`, `prompting.py`, `agent.py`,
`configs/robot.yaml`, `evals/**`, yield/person-stop policy B22, the owner's
processes. No commit / stage / stash at any point.

### Decisions taken at map time (rationale recorded before the code existed)

1. **The arrival table lives in `navigation/`, not in the scene sidecar.**
   `configs/scenes/city_block.semantics.yaml` is scene VOCABULARY (which geom
   prefix means which class); the arrival table is a per-CLASS policy that must
   answer for classes this scene does not contain (`door`, `person`). Putting
   `door` into the city-block sidecar would declare a class with no geom prefix
   and no instance — a lie about the scene, and it would drag the packaged
   asset + `runtime_assets/MANIFEST.json` release-parity digest along with it.
   The sidecar stays untouched; see Deviations.
2. **`circle_owner` / `follow_owner` render text for the deterministic router**,
   exactly as `navigate_to` already does (`_realtime_navigate`: "the ROUTER
   decides, the broker only renders"). No `IntentFrame` and no `PlanSketch` is
   ever constructed inside the broker, so the new tools inherit the audited
   validate→router→`_admit_local_sketch` chain rather than growing a second one.
3. **Place validation resolves against the live semantic map UNION the scene
   vocabulary**, not the sidecar alone — otherwise a real, currently-visible
   instance whose class the sidecar does not declare (the door) would be
   refused as junk.

### Correction to §0, recorded rather than edited away

§0 states the working tree was clean at map time. It was not, and the map was
written by an earlier executor pass that then stopped before any code existed.
`git status --short` at the start of THIS pass shows the R8/R9 work still
uncommitted (`M lane.py protocol.py ingress.py runtime.py …`, plus the whole
`?? scrum/20260819/` tree). HEAD is `8473a51`, which matches §0; the "clean"
claim does not. Nothing was reverted or restaged — the card forbids
commit/stage/stash — the sentence is simply wrong and is left in place with this
correction under it, because silently rewriting a prior section is how a status
doc stops being evidence. The file map itself was re-derived from the source
this pass and is accurate; see §1 for one change to it.

---

## §1 — Root cause of the live `semantic_target_unreachable` (card work item 1)

Read the code before writing this section; the answer is a relation gate, not a
tolerance.

### The chain, file and line

1. `pipeline.py:2938` — `_commit_semantic_candidate` calls
   `safe_approach_pose(...)` for every grounded candidate.
2. `approach.py:70` — for `terminal_relation == "inside"` with a polygon, the
   solver runs `_safe_polygon_point(...)` (`approach.py:383`). That sampler
   accepts an interior point ONLY when all four of these hold:
   `_inside(point, polygon)`, `_has_clearance(point, polygon, clearance)`,
   `_clear_of_observed_obstacles(point, blocked, obstacle_clearance)`, and
   **`_segment_clear_of_observed_obstacles(robot, point, blocked,
   obstacle_clearance)`** — the straight ROBOT→POINT segment must be clear.
3. `approach.py:104` — if that returns `None`, one retry:
   `nearest_point_in_region(polygon, robot_xy, inset_m=approach_clearance)`,
   a single point, which raises `ValueError` when the inset empties the
   polygon and is then ranked through the proxemic veto
   (`_rank_approach_point`, `PROXEMIC_VETO_DEPTH = 16`), which can veto it.
4. `pipeline.py:2963` — `pose is None` → `_fallback_near_arrival_pose(...)`,
   whose **second line** is
   `if getattr(semantic_goal, "terminal_relation", "") not in {"near",
   "next_to"}: return None` (`pipeline.py:3155`).
5. `pipeline.py:2978` → `_release_unreachable_candidate` → replan budget spends
   → `pipeline.py:5305` `MidLevelCommand(stop=True,
   note="semantic_target_unreachable")`.

### The root cause, stated plainly

**A region (`inside`) goal has no second-chance pose solver at all.** The K0-band
fallback added on 2026-08-09 for the boxed-in-bench defect is explicitly gated to
`near`/`next_to`. So for "go to the sidewalk" the whole arrival machinery is one
inset grid sample plus one nearest-point retry, and *any* of four vetoes — the
one that matters live being the **straight-segment veto**, which a single
pedestrian standing between the robot and the sidewalk trips for EVERY interior
sample simultaneously — collapses the entire region to "unreachable". The
replan re-grounds the same polygon from the same frustum, re-derives the same
verdict, and burns the budget.

`tolerance_m: 0.0` is a red herring and is NOT the defect: against a polygon,
zero tolerance is the correct and meaningful value (containment is binary), as
`res_semnav.md` §1 states. Nothing in the tolerance path produced this failure.

### Why the segment veto is the wrong authority here, and what replaces it

The segment test asks "is the straight line clear?" — but the robot does not
drive straight lines. `grid_planner` routes around obstacles and
`apply_reactive_safety` is the disposer. Using a straight-line occlusion test as
an ARRIVAL-POSE admissibility test conflates "can I reach this pose" with "is
this pose safe", and only the second is this function's business. The fix is an
in-region resampler that keeps every POINT-clearance requirement at full
strength (polygon containment with edge clearance, full footprint-to-surface
clearance from every observed surface, plus person keepout discs — which the old
path did not consider at all) and drops only the straight-segment precondition,
then names the candidates it tried when it still finds nothing.

### One change to the §0 file map

`spatial.py` is still owned (mid-orbit abort), and `pipeline.py` still owns the
resampling; the resampler itself lands in `approach.py`, not `pipeline.py`,
because that is where `_safe_polygon_point` and every clearance primitive it
must reuse already live. Putting it in `pipeline.py` would have meant a second
copy of `_inside`/`_has_clearance`/`_clear_of_observed_obstacles` — the D5 defect
class this repo names by number. `approach.py` is therefore added to OWNED.

---

## §2 — Baseline, and a self-inflicted red I am recording rather than hiding

The first `ci_gate --tier commit` of this pass came back **RED**:

```
[  FAIL] HARD  default-suite             6 failed, 6390 passed, 9 skipped, 42 deselected
    FAILED tests/test_pose_authority_archon.py::test_no_direct_pose_reads_outside_the_seam_or_the_allowlist
    FAILED tests/test_pose_authority_archon.py::test_allowlist_entries_still_have_a_direct_read[navigation/approach.py]
    ... (4 more archon parametrizations)
```

**Cause: mine, and not a code defect.** I launched the gate in the background and
then wrote new modules into `navigation/` while its `pytest` was running. One of
those writes was on disk in a syntactically broken intermediate state, and the
pose archon walks and parses the whole navigation package — so every archon
parametrization failed at once. Re-running that file alone immediately after:
`7 passed in 3.88s`.

**Rule adopted for the rest of the card, and it held:** never edit the tree while
a gate or suite is running. Every subsequent run was started only after the last
edit landed.

Clean re-run of the gate's own default-suite command
(`pytest -m "not slow"`) with the tree quiescent found exactly **one** real
failure, and it was a genuine finding against my new code:

```
FAILED tests/test_authority_no_literal_drift.py::test_no_new_retired_family_literals
  navigation/arrival_semantics.py: 1x 1.2 (F-proximity) is not allowlisted —
  derive it from parcel_robot.authority
1 failed, 6395 passed, 9 skipped, 42 deselected in 245.58s
```

I had written the social stand-off as the literal `1.2`. The repo's authority
archon is right: that value is `authority.PERSON_SOCIAL_ZONE_M`, and a second
hand-typed copy is exactly the drift the family tags exist to stop. Fixed by
deriving it (`SOCIAL_STANDOFF_M: float = PERSON_SOCIAL_ZONE_M`) rather than by
allowlisting the literal. Both archons then green:
`tests/test_authority_no_literal_drift.py tests/test_pose_authority_archon.py
… 34 passed in 4.35s`.

**Baseline for this card is therefore: full suite green at 6395 passed**, and the
hard-safety / frozen-digest / release-parity / latency-tail / jerk-ratchet gates
all PASS in the first run above (their output is quoted verbatim in §8).

---

## §3 — Orbit feasibility, and the false refusal it nearly shipped with

`navigation/orbit_feasibility.py` (NEW) samples the ring around the owner and
returns `OrbitFeasibility{feasible, cause, blocked: (BlockedArc…)}`, where a
`BlockedArc` carries its bearing span, what blocked it, and by how much. One
function, `evaluate_orbit_annulus`, is used twice with the same clearance: at
admission over the planned sweep (`SpatialBehaviorController.assess_orbit`) and
mid-orbit over a bounded 60° lookahead (`_lookahead_feasibility`, called every
tick from `_step_orbit`).

### The finding: my first draft refused orbits that are demonstrably fine

The mid-orbit check reddened
`tests/test_voice_nav_e2e.py::test_orbit_the_owner_completes_one_revolution`
(both phrasings) at **32% progress**:

```
AssertionError: orbit did not verify success: states=['failed']
details=['orbit_annulus_blocked'] spatial={… 'orbit_radius_m': 1.6,
'progress': 0.3195…, 'reason': 'orbit_annulus_blocked'}
```

That is a full-sim orbit the repo has always completed with zero collisions.
**Two real bugs, both mine:**

1. **Wrong frame lift.** I built map-frame surface points as
   `robot + distance_m`, but the LiDAR contract reports *footprint*-to-surface
   clearance, not centre range — `approach._observed_obstacle_points` has always
   added the body radius back. Every obstacle was 0.32 m closer than reality.
2. **Wrong threshold, and this is the interesting one.** I used the reactive
   gate's braking distance as the feasibility criterion. That is a category
   error: the gate is a *speed governor* — slowing near a surface is correct
   behaviour, not impossibility. Refusing every orbit the gate would slow for
   produces a **false** "I can't walk around you here", which is precisely the
   dishonesty this validator exists to prevent (the bench caught realtime-mini
   making that same false claim, `bench_navmodel.md` §6/A3).

The criterion is now **does the body fit**: `footprint_radius_m +
orbit_clearance_margin_m`, footprint radius read from
`authority.DEFAULT_SAFETY_ENVELOPE`, never spelled as a literal. Both fixes
carry the reasoning in comments at the code, because "why is this not the gate
distance" is the question the next reader will have.

`2 passed in 104.35s` after the fix — the same live-sim orbit, unrefused.

**Safety direction, stated plainly:** this check can only ever STOP an orbit. It
never widens a ring, never weakens a keepout, never continues one the geometry
refuses, and `apply_reactive_safety` still runs after it as the sole disposer.
It also returns `None` (not "infeasible") on a tick with no surfaces and no
tracks, so a sensor-quiet tick cannot manufacture a refusal — absence of
evidence reported as absence.

---

## §4 — Seed table (21 seeds, all RED, all restored byte-identical)

Harness: `<scratchpad>/r10_seeds.py`. FIX-A discipline — mutate ONE source
file, run a NAMED pytest target, restore in `finally`, assert the file came
back byte-identical by sha256. **No test, config or eval was ever mutated:**
every `file` below is under `src/parcel_robot/`.

| # | Seed | Mutated file | Target | Result |
| --- | --- | --- | --- | --- |
| S1 | inside regressed to near | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 6 failed |
| S2 | in-region resampling removed | `navigation/approach.py` | `test_navigation_inside_resampling.py` | **RED** — 7 failed |
| S3 | resampler stops honouring person keepouts | `navigation/approach.py` | `test_navigation_inside_resampling.py` | **RED** — 3 failed |
| S4 | resampler stops honouring obstacle clearance | `navigation/approach.py` | `test_navigation_inside_resampling.py` | **RED** — 1 failed |
| S5 | inset ladder drops below the footprint radius | `navigation/approach.py` | `test_navigation_inside_resampling.py` | **RED** — 3 failed |
| S6 | door crossed (do_not_cross dropped) | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 4 failed |
| S7 | the pipeline stops enforcing do-not-cross | `navigation/pipeline.py` | `test_arrival_etiquette_pipeline.py` | **RED** — 1 failed |
| S8 | the arrival fact drops the ask-hint | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 1 failed |
| S9 | the terminal stops turning back to the owner | `navigation/pipeline.py` | `test_arrival_etiquette_pipeline.py` | **RED** — 3 failed |
| S10 | conflicting relation hint beats the table | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 1 failed |
| S11 | an unsupported refinement is accepted | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 2 failed |
| S12 | unknown class guesses instead of falling back to near | `navigation/arrival_semantics.py` | `test_arrival_semantics.py` | **RED** — 4 failed |
| S13 | face becomes a model-settable tool parameter | `realtime/tool_broker.py` | `test_arrival_semantics.py` | **RED** — 1 failed |
| S14 | junk place accepted (function-word gate removed) | `realtime/tool_broker.py` | `test_realtime_tool_broker.py` | **RED** — 3 failed |
| S15 | circle_owner bypasses the supervisor | `realtime/tool_broker.py` | `test_realtime_tool_broker.py` | **RED** — 1 failed |
| S16 | follow_owner claims the pace was applied | `realtime/tool_broker.py` | `test_realtime_tool_broker.py` | **RED** — 1 failed |
| S17 | orbit refusal is silent | `navigation/orbit_feasibility.py` | `test_orbit_feasibility.py` | **RED** — 5 failed |
| S18 | mid-orbit closure keeps orbiting | `navigation/spatial.py` | `test_orbit_feasibility.py` | **RED** — 1 failed |
| S19 | the blocked arc is not reported | `navigation/orbit_feasibility.py` | `test_orbit_feasibility.py` | **RED** — 4 failed |
| S20 | orbit feasibility uses the brake distance again | `navigation/spatial.py` | `test_orbit_feasibility.py` | **RED** — 1 failed |
| S21 | the owner's own body blocks their own orbit | `navigation/spatial.py` | `test_orbit_feasibility.py` | **RED** — 1 failed |

All 21 restored byte-identical (`restored: true` on every row).

### Two seeds came back GREEN first, and the TESTS were strengthened

The card's rule ("a GREEN seed means strengthen the test, never delete the
seed") earned its keep twice on the first harness run — `19/21 seeds RED`:

* **S20** (orbit feasibility reverts to the brake distance) was GREEN because
  my false-refusal test called `evaluate_orbit_annulus` **directly** with a
  clearance argument, so it never exercised `_ring_clearance_m` at all. Fixed by
  adding a CONTROLLER-level pair of tests that go through `assess_orbit`: a
  bollard 0.50 m from the ring must stay feasible (outside the 0.42 m body-fit
  clearance, inside the ~1.12 m brake distance) and a kerbstone 0.30 m from it
  must refuse. A LiDAR helper inverts the footprint-to-surface contract so the
  geometry in the test is the geometry the code sees.
* **S21** (the owner's own body blocks their own orbit) was GREEN because my
  test used a *realistically sized* 0.35 m owner disc — which cannot reach a
  1.6 m ring, so deleting the owner exclusion changed nothing and the test
  pinned nothing. Fixed by testing the case the exclusion actually exists for: a
  merged/mis-sized 1.9 m owner blob that DOES overlap the ring. The reasoning is
  written into the test docstring so the odd-looking radius is not "fixed" back
  later.

Both were real weaknesses in my tests, not in the code. Re-run: **21/21 RED**.

---

## §5 — Live proofs

Own stack throughout. `configs/robot.yaml` was **copied** to
`<scratchpad>/livework/robot_r10_<STAMP>.yaml` with **only** `memory.path`
changed to a scratch sqlite file (R5 deviation 6 recipe); the owner's
`parcel_memory.sqlite3` was never opened for writing, moved, or read. Scripts:
`<scratchpad>/r10_live_proof.py`, `r10_refusal_proof.py`,
`r10_refusal_boxed.py`, `r10_hosted_proof.py`. Paths are timestamped JSONL under
`<scratchpad>/paths/` for task_5.

### 5.1 "Go to the sidewalk" ends INSIDE the sidewalk

```
places seen by the broker: ('crosswalk', 'planter', 'tree', 'building', 'bench', 'lamppost', 'sidewalk')
broker: {"admitted": "Okay—I'll move onto sidewalk and verify it.", "detail": "mission accepted: the sidewalk",
         "directive": "go to the sidewalk", "place": "the sidewalk", "relation_hint": "inside",
         "status": "ok", "tool": "navigate_to"}
final pose: 1.3891 2.5248   nav: arrived / arrived_verified
containment (scene truth):
  [{"region": "sidewalk", "polygon": [[-8.0,2.2],[8.0,2.2],[8.0,4.2],[-8.0,4.2]],
    "centre_inside": true, "footprint_inside": true},
   {"region": "sidewalk_south", ..., "centre_inside": false, "footprint_inside": false}]
```

Containment is scored against `evals/nav_instruct/scene_truth.json`, the
generated geometry table — **not** the live frustum. The first run of this script
scored against `observation.semantic_regions` and printed `containment: []`,
because a robot standing on a sidewalk usually cannot see the whole polygon. An
empty list is not a pass; it is a measurement that proves nothing, and it was
replaced rather than reported.

Path: `paths/r10-sidewalk-inside-<STAMP>.jsonl`.

### 5.2 The door terminal, through the narration channel

The city_block scene has no door instance, so this is the FACT the channel
carries, generated from the same table row the planner uses
(`runtime._arrival_fact_for("the door")`), verbatim:

```
The robot's navigation system reports: You have stopped just short of the door,
without going through it. You are turned back to face your owner. Now ask the
owner what they would like to do next.
```

R11 has not landed (`scrum/20260819/task_4` has a README and no status doc), so
per the card the hint text is inline. The geometry half — refuse a pose inside
the threshold, orient to the owner — is pinned at the planner in
`tests/test_arrival_etiquette_pipeline.py` and seeded by S7/S9.
**does_not_prove:** an end-to-end door mission in a scene containing a door.

### 5.3 "Circle around me" WORKS through the new tool

```
broker: {"detail": "Okay—I'll make the requested local circle around you safely.",
         "direction": "counterclockwise", "revolutions": 1.0, "size": "normal",
         "status": "ok", "tool": "circle_owner"}
spatial: completed / orbit_complete / progress 1.0
```

Path: `paths/r10-circle-owner-<STAMP>.jsonl`.

**This is the run that found the bug §5.6 describes** — on the first attempt it
came back `rejected: the robot's spatial grammar does not recognize that circle
(router rule: ambiguous_physical_request)`.

### 5.4 The orbit REFUSES with narration when boxed in

24 live probes at the wide radius with the owner in open space were **admitted
24/24** with no refusal — which is the no-false-refusal result §3 argued for,
recorded at `paths/r10-orbit-refusal-probe-<STAMP>.jsonl`. The static city keeps
the owner at (2.0, −0.5) in open space and no configuration of this scene boxes
them in, so the refusal was driven through the real doors with the crowd
injected at the perception seam (`backend.observe`):

```
{"broker": {"detail": "I can't walk around you here — someone is in the way; there isn't room in front of you.",
            "status": "rejected", "tool": "circle_owner"},
 "verdict": {"feasible": false, "cause": "orbit_annulus_blocked", "radius_m": 1.6,
             "clearance_m": 0.42, "samples": 37,
             "blocked": [{"start_deg": 6.0, "end_deg": 356.0, "width_deg": 350.0,
                          "label": "someone", "clearance_m": 0.387}]}}
after clear: {"detail": "Okay—I'll make the requested local circle around you safely.", "status": "ok", ...}
```

Everything below `backend.observe` is real: `_realtime_orbit` → `assess_orbit` →
`evaluate_orbit_annulus` → the broker JSON the model reads. **does_not_prove:**
that this scene's own furniture can produce boxed-in geometry.

### 5.5 The hosted model USES the new tools instead of fabricating

Real provider, `gpt-realtime-2.1-mini`, text modality, real
`build_tool_specs` surface. Transcript:
`<scratchpad>/r10_hosted_transcript_20260820T061828Z.json`.

| Prompt | Tool the model called | Bench baseline (hole open) |
| --- | --- | --- |
| "Circle around me." | `circle_owner{direction: clockwise, size: normal, revolutions: 0.5}` | realtime-mini **falsely denied the ability** 2/3 |
| "Run with me." | `follow_owner{pace: run}` | mini proxy **fabricated `navigate_to`** 5/6 |
| "Come on, run with me!" | `follow_owner{pace: run}` | " |
| "Let's go for a run together." | `follow_owner{pace: run}` | " |
| "Get to the door." | `navigate_to{place: door, relation: near}` | — |

**0 fabricated `navigate_to` places across all six turns**, and the relation hint
on the door was `near` — the table's own answer, agreeing.

The pace honesty design also landed, verbatim from the model:

> "It enabled follow mode, but it kept me at my own safe pace, so running wasn't
> applied."

That is the model reading `pace_applied: false` + `pace_note` and telling the
truth, against the bench's B2 finding where it claimed "I'm matching your slower
pace" while the injected gait was still RUN.

**Costs:** `$0.017932` (first run) + `$0.037702` (second) = **`$0.055634`**,
against the card's `<$1.50`.

### 5.6 What the live proof caught that no unit test could

`circle_owner` **refused every default request** the first time it ran live:

```
{"detail": "the robot's spatial grammar does not recognize that circle
            (router rule: ambiguous_physical_request)", "status": "rejected"}
```

The broker declares `size: small|normal|wide`. The deterministic spatial grammar
alternates on `small|tight|wide` — there is no literal "normal", because a circle
with no adjective *is* the normal one. So the default rendered "walk in a normal
counterclockwise circle around me", matched nothing, and the router honestly
refused. **Neither side was wrong on its own**, which is exactly why no unit test
saw it: the broker's enum was right, the grammar was right, and they disagreed
about one word at the seam between them.

Fixed by rendering the adjective only when it is not "normal", and closed by
`test_every_orbit_argument_combination_renders_a_directive_the_grammar_PARSES`,
which walks the FULL enum cross product and asserts the rendered sentence
round-trips back through `parse_spatial_intent` to the arguments that produced
it. That test would have caught it, and now guards the whole surface.

---

## §6 — `ci_gate --tier commit`, verbatim, after the final edit

Read before pasting. Every hard gate green, **hard-safety included, and the
frozen nav baseline did not move** (the card's card-stopping condition).

```
CI GATE — tier=commit  (2026-08-20T06:27:06Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.39s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.34s
[  PASS] HARD  default-suite              6486 passed, 9 skipped, 42 deselected, 5 warnings in 242.90s (0:04:02)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 255.8s
```

Baseline was 6395 passed; final is **6486** (+91 new tests, 0 removed).

**Ruff:** 5 new violations were introduced by this card's code (import ordering
in four files, one `RUF046` in `orbit_feasibility.py`). All five were FIXED. The
baseline was not re-pinned — `new 0` above is against the unchanged
`scripts/ci_ruff_baseline.json`.

---

## §7 — Deviations, each with its reason

1. **`voice/local_plans.py` was edited** (not in OWNS, not in MUST NOT TOUCH).
   `sketch_navigate` gained five optional keyword arguments, all defaulted to the
   pre-R10 behaviour, that pass the relation hint and the scene vocabulary
   through to `semantic_goal_from_directive`. It is a pure CARRIER — it does not
   inspect, trust, or act on the hint. There is no other seam between a
   `navigate_to` tool call and the goal compiler: the PlanSketch is what travels.
   A caller that passes nothing gets byte-identical output.
2. **`approach.py` was added to OWNS** (§1). The resampler needs `_inside`,
   `_has_clearance` and `_clear_of_observed_obstacles`, all of which live there;
   putting it in `pipeline.py` would have been a second copy of three clearance
   primitives.
3. **`pipeline.py` imports the arrival table SOFTLY.** That file is one of the
   three the BARN v8 policy bundle replaces into a frozen historical
   `parcel_robot` tree, which predates `arrival_semantics.py`. A hard import
   reddened `test_barn_v8_policy_bundle` with `ModuleNotFoundError` from inside
   the policy sidecar. Adding the module to the bundle was not available — its
   file counts and digests are pinned and frozen — so the import follows the
   pattern the file already documents for `p_inside_polygon`, with the reason at
   the code.
4. **The junk-place gate refuses ONLY non-place NAMES, not unknown places.** The
   card asks for "a place must resolve against the semantic map/place list". A
   literal reading refuses "narnia", and
   `test_navigate_to_grants_exactly_what_a_typed_sentence_grants` forbids exactly
   that: a broker stricter than the typed panel path gives the hosted lane its
   own private grammar. So `unknown_place` is admitted, routed, and allowed to
   fail honestly at grounding, while `not_a_place_name` (a preposition or a
   motion verb — the class of ALL THREE bench fabrications) is refused with the
   vocabulary named. Both classes are reported on the verdict.
5. **Conjunctions were deliberately left OUT of the function-word set.** "the
   sidewalk and then sit" is a compound, and the ROUTER has always been the thing
   that refuses compounds. Catching it in the broker would move that refusal into
   a second grammar and change the reason the owner hears, for no gain.
6. **The live sim socket lives at `/tmp/claude-1000/` rather than the
   scratchpad.** `AF_UNIX` caps the path at ~107 bytes and the scratchpad root
   alone is 92; the sim died with `OSError: AF_UNIX path too long`. Only the
   socket moved. Every artifact is still in the scratchpad.
7. **The boxed-in orbit refusal injects its geometry at `backend.observe`.**
   The static city puts the owner in open space (24/24 live admissions, §5.4) and
   nothing in this scene boxes them in. Everything downstream of the perception
   seam is real. Stated as `does_not_prove` in §5.4.
8. **The hosted proof used a recording broker, not the live sim runtime.** It
   answers with the real broker's own JSON (real `build_tool_specs`, real
   validate chain, real result shapes) so the model sees truthful results, but no
   body moves — motion is proved separately in §5.1/§5.3 on the live stack.
   Combining them would have made a single flaky test of two independent claims.
9. **I edited the tree while a gate was running, once, and reddened it** (§2).
   Recorded rather than quietly re-run.

Nothing was committed, staged, or stashed. `lane.py`, `protocol.py`,
`ingress.py`, `prompting.py`, `agent.py`, `configs/robot.yaml`, `evals/**` and
the yield/person-stop policy are untouched.

---

## §8 — Open risks and honest limits

1. **No door exists in `city_block`.** The portal class is exercised by unit
   tests, the planner guard, and the narration fact — never by a live mission to
   a real door. The first scene with a door is the real test of `do_not_cross`.
2. **`pace` is carried, not applied.** `follow_owner(pace="run")` records the
   pace and reports `pace_applied: false`. That is deliberate and R11 owns the
   consumer — but until R11 lands, an owner who says "run with me" gets a follow
   at the robot's own pace. The model narrates this honestly today (§5.5); it is
   still a capability gap, not just a wording one.
3. **One hosted turn is unattributed.** "Go to the sidewalk." (the last prompt)
   recorded no tool call inside its drain window while the model said "I'm headed
   toward the sidewalk now." The most likely explanation is the call landing after
   the loop closed, but I did not prove that, and an unsupported "I'm headed
   there" would be an honesty defect. Re-running that case in isolation is the
   cheap next step. I am not claiming 6/6 tool fidelity — I am claiming 5 of 6
   turns observed and one unmeasured.
4. **The in-region resampler only runs when tiers 1 AND 2 both fail.** Tier 2
   (`nearest_point_in_region`) returns a point for any ≥3-vertex polygon, so the
   resampler is reached only when the proxemic veto rejects that single point —
   i.e. when dynamic tracks are present, which is the live failure's shape. A
   region goal that fails with no tracks at all still has no third tier.
   Separately: tier 2's point is ranked but never clearance-checked against
   surfaces, which is pre-existing behaviour I did not change and which the
   resampler is strictly safer than.
5. **SI v3 is stale.** The system instructions do not mention `circle_owner` or
   `follow_owner`, so the model discovers them from the tool schemas alone. That
   worked (§5.5), but the SI still implies the robot's physical repertoire is
   gestures, poses and navigation. **REPORTED, not touched** — `prompting.py` is
   MUST NOT TOUCH and SI v3 is its own card.
6. **The mid-orbit lookahead is 60° at a fixed radius.** It does not anticipate a
   pedestrian's velocity — a person walking INTO the arc from outside is seen
   only once they are in it. Feeding the dynamic tracks' velocities into the
   sweep is the obvious next increment.
7. **`_realtime_places` orders by distance using the region VERTEX MEAN**, which
   is not a centroid for non-convex polygons. It affects only the ORDER of the
   places named in a refusal sentence, never admission.

---

## §9 — Final state

* `ci_gate --tier commit`: **PASS**, every hard gate green, re-run after the last
  edit (§6). 6486 passed / 9 skipped.
* Seeds: **21/21 RED and restored byte-identical**, re-run against the final tree
  after the ruff fixes reordered imports (`<scratchpad>/seeds_final.json`).
* Frozen files verified untouched by mtime: `lane.py`, `protocol.py`,
  `ingress.py` all last written 05:16 UTC — before this pass's first edit at
  05:21 UTC — and `prompting.py`, `agent.py`, `configs/robot.yaml` are days old.
* Nothing committed, staged, or stashed.
* Live spend: **$0.055634** of the $1.50 cap.

### Owner-gated list (nothing here was done)

1. **SI v3 does not mention the two new tools.** The model found them from the
   schemas, but the instructions still describe a body that cannot circle or
   follow on request. `prompting.py` is frozen for this card.
2. **`pace` needs R11 to become real.** Until then "run with me" is an honest
   follow at the robot's own pace.
3. **A scene with a door** is what would turn §5.2 from a table-and-planner proof
   into an end-to-end one.
4. **Velocity-aware orbit lookahead** (risk 6) — a design decision, not a bug fix.
