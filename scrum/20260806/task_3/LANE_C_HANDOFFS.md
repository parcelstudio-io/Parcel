# Lane C → handoffs · 2026-08-07

Work Lane C could not do this round because the target file belongs to another
lane (file ownership is hard while lanes run concurrently), plus the entry reds
it inherited. Everything here is **measured**, not speculated; each item names
the exact file and lines and what the change must preserve.

Record: [LANE_C_STATUS.md](LANE_C_STATUS.md).

---

## H1 — RelationSpec registry consumption inside the navigator (owner: Lane D / review round)

`src/parcel_robot/navigation/relation_registry.py` landed as a **lookup layer**
only. Nothing in `pipeline.py` or `scoring.py` consumes it yet, because both are
Lane D-owned this round. The registry delegates to the existing K0 builders, so
each of these is a *substitution with an equality test available*, never a
behaviour change.

| target | lines (2026-08-07) | today | after |
|---|---|---|---|
| `instructnav/scoring.py::arrival_goal_region_for_relation` | 655–694 | `if relation == "inside" / "next_to" / "towards"` then a default-`near` fallthrough | `RELATIONS.get(relation).goal_region(RelationAnchor(...))`; the metadata-override branches (`raw["goal_region"]`) stay where they are — they are an *authority* choice, not a relation choice |
| `navigation/pipeline.py::_terminal_relation_verified` | 2274 (`if relation == "inside"`), 2284 (`if relation == "near"`) | per-relation literals | keep the evidence/clearance logic; replace only the *region* half with the registry predicate |
| `navigation/pipeline.py` | 1125 | `terminal_relation not in {"near","next_to","towards"}` | `terminal_relation in relation_registry.PROXIMITY_FAMILY` |
| `navigation/pipeline.py` | 2456, 2514 | `terminal_relation == "inside"` | `RELATIONS.get(relation).goal_region(...).kind == "polygon"` — the polygon-ness is what those branches actually test |

**Equality test to write with it:** for every `(relation, center, radius, label,
metadata)` combination the current NAV_INSTRUCT episode set produces, the
registry's `goal_region` must equal `arrival_goal_region_for_relation`'s output
byte-for-byte. `tests/test_relation_registry.py::test_registry_goal_region_is_the_k0_builder_output`
already does this for the four builders; extend it over the episode set rather
than trusting the substitution.

**Soft-import discipline:** `pipeline.py` is copied verbatim into frozen BARN
bundles whose `parcel_robot` tree predates new modules. Any import of
`relation_registry` from `pipeline.py` must follow the existing
`paths`/`attributes`/`traffic_aware` pattern (try/except ImportError with a
`_HAS_*` guard), or `tests/test_barn_v8_policy_bundle.py` goes red the way it
did when `navigation/attributes.py` landed.

---

## H2 — `_plan_acknowledgement` has no case for a compound settle plan (owner: runtime.py)

**File:** `src/parcel_robot/runtime.py`, `_plan_acknowledgement`, lines 1042–1062.

N13's "sit next to X" now compiles to `NavigateTo + Pose` under a
`hold`/`current_pose` goal — the only goal shape `PlanValidator` admits for a
terminal `Pose` step (`validator.py:847–853` and `:581–593`). The
acknowledgement table keys on `goal.relation`, so the reply is the `hold`
branch: **"Okay—I'll stay here."** for a command that will walk to a bench and
sit down.

Not a safety issue and not a false arrival claim, but it is a wrong answer. The
fix is a branch that reads the *plan* rather than only the goal relation, e.g.
a `hold` goal whose steps contain a `NavigateTo` acknowledges the navigation
plus the settle. Lane C could not make it: `runtime.py` is Lane D-owned.

Measured: `tests/test_owner_and_settle_plans.py::test_sit_next_to_the_bench_publishes_a_two_step_plan_on_the_product_path`
shows the two-step plan; the reply string is what this item is about.

---

## H3 — RESUME restores the channel but leaves the executive task suspended (owner: runtime.py)

**File:** `src/parcel_robot/runtime.py`, `_apply_closed_intent`, the
`if directive.resume:` branch, lines 1448–1480.

**Measured 2026-08-07** on the product path (fake backend, no sim needed),
`handle_text("go to the sidewalk")` → `"pause"` → `"resume"`:

| after | navigation channel | executive task |
|---|---|---|
| pause | `state="paused"`, `reason="closed_intent_pause"` | `state="suspended"`, `last_detail="suspended:closed_intent_pause"` |
| resume | `state="searching"`, `reason="navigation_resumed"` — **advancing** | `state="suspended"` — **unchanged**, across further `_step_brain()` ticks |

So after a resume the robot drives while the plan step that authorized it is
suspended: its verification, timeout, and recovery policy are not running. The
pause branch suspends *both* (it explicitly walks the task list and issues
`InterruptRequest(requested="interrupt_now")`); the resume branch only walks
`("navigation", "follow", "search")` channels.

Pinned, not fixed:
`tests/test_closed_intent_product_path.py::test_resume_also_restores_the_executive_task_record`
(xfail, `strict=False`, with the measurement in the reason). Backlog: **N14**.

---

## H4 — Freeze the closed-intent routes in the brain_v1 router cases (owner: whoever owns `evals/**`)

U33's own "to verify" list ends with: *freeze the route in
`evals/companion/brain_v1/router_cases.jsonl`, which today contains no `come`
case at all.* `evals/**` is off-limits to Lane C this round, so the routes are
pinned in `tests/test_closed_intent_product_path.py::test_router_rule_is_pinned_for_every_closed_intent`
instead. The frozen file still needs these seven rows:

| transcript | expected route | expected matched_rule | speech_act |
|---|---|---|---|
| `stop` | `direct_skill` | `emergency_stop` | `cancel` |
| `halt` | `direct_skill` | `emergency_stop` | `cancel` |
| `pause` | `direct_skill` | `closed_intent:pause` | `request` |
| `resume` | `direct_skill` | `closed_intent:resume` | `request` |
| `faster` | `direct_skill` | `closed_intent:faster` | `request` |
| `slower` | `direct_skill` | `closed_intent:slower` | `request` |
| `come here` | `direct_skill` | `come_to_owner` | `request` |
| `actually, the other one` | `deliberative_plan` | `task_correction` | `correction` |

(`requires_fresh_scene` is `False` for the four cap intents — a cap retimes or
suspends work already admitted against a snapshot; demanding a fresh one would
make "pause" fail exactly when perception is degraded. `come_to_owner` keeps
`True` and `spatial_references=("owner",)`.)

---

## H5 — Two entry reds inherited, both Lane A's family migration

Measured at Lane C entry (`pytest tests/ -q`, 2026-08-07, before any Lane C
edit): **2 failed, 2397 passed, 7 skipped, 5 xfailed** in 667 s. Both failures:

```
tests/test_authority_no_literal_drift.py::test_no_new_retired_family_literals
tests/test_authority_no_literal_drift.py::test_collision_and_approach_hold_only_the_documented_non_radius_residue
```

Cause: `src/parcel_robot/navigation/collision.py` lines 19 and 25 hold two
`1.2` literals (F-proximity family) inside the `_FrozenBundleEnvelope`
fallback class added for frozen BARN bundles that predate
`parcel_robot.authority`. The allowlist in `tests/test_authority_no_literal_drift.py`
was not updated for them, and the second test asserts
`measured.get(("navigation/collision.py", 1.2)) is None` outright.

Lane C did not touch either file. Deciding whether the fallback literals are
allowlisted (with family tag + owner) or derived is a Lane A value decision —
`authority.py` is on Lane C's do-not-touch list. Both are still red at Lane C
exit.

---

## H6 — Carried-forward items Lane C did not take

- **N-SUP-1** (distance-first ordering for explicit superlatives): the natural
  home named in `SUPERLATIVE_STATUS.md` is the RelationSpec registry, but the
  ordering itself lives in `instructnav/grounding.py::_rank_candidates`
  (`(-confidence, distance, id)`). The registry now exists; the change is a
  `superlative`-aware sort key at that one site.
- **N-SUP-2** (`RememberedEntity` carries size, so an attribute-qualified goal
  can be satisfied from memory) — `instructnav/memory.py`, untouched.
- **The sidecar's `detector_query_set()`** has no consumer yet. It is the third
  derived view the plan names (NanoOWL prompt list) and is deliberately built
  now so the open-vocabulary step reads the sidecar rather than growing a
  fourth copy of the vocabulary.

---

## H7 — Remove the compiler's runtime-authored contract fallback (owner: runtime.py)

**Files:** `src/parcel_robot/brain/compiler.py` (`_contract_for`) and
`src/parcel_robot/brain/validator.py` (`RUNTIME_AUTHORED_SKILLS`,
`SkillContractRegistry.get`).

N13's settle step needs the `Pose` skill admitted. Every straightforward route
to that is blocked by something that must not move:

| route | blocker |
|---|---|
| add `Pose` to `agent.brain.skills` in `configs/robot.yaml` | that file is a **locked input of the frozen embodied-plan manifest** (`evals/companion/embodied_plan_v1/manifest.json` pins its SHA-256). Editing it fails manifest verification — measured: 1 failure + 7 errors in `tests/test_embodied_plan_eval.py`. |
| move `Pose` into `SYSTEM_SKILL_NAMES` | that set is what `SkillContractRegistry.default()` filters on, and the frozen live-planner probe (`standalone_probe_profile: full_default_registry/raw_plan_schema`) asserts `Pose` **is** in the full default registry and raw schema. Measured: `tests/test_live_planner_eval.py` red. |
| add `Pose` to `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS` | that set is the model-facing schema enum; `tests/test_planner_quality_v2.py` asserts `"Pose" not in schema_skills`. Measured: red. |

What landed instead, deliberately narrow:

- `RUNTIME_AUTHORED_SKILLS = {"Pose"}` — skills only the runtime's own
  deterministic sketches author.
- `SkillContractRegistry.get()` resolves them **only when
  `system_authored=True`**. It is in `get`, *not* `names`, so every derived
  surface (response schemas, prompt contracts, the duplex skill list) is
  provably unchanged and a model still cannot see `Pose` in its schema.
- `compiler._contract_for` falls back to the system contract table for the
  same set, because `RobotRuntime._materialize_brain_planner_output` compiles
  **every** sketch against `self.brain_registry` — even a `direct_skill` one
  the runtime authored itself — while `_accept_plan` then re-compiles and
  validates against the route-selected registry.

**The one-line fix that makes the compiler fallback unnecessary:**
`_materialize_brain_planner_output` (runtime.py ~line 880) should select the
registry the same way `_accept_plan` already does —
`self.system_registry if frame.route == "direct_skill" else self.brain_registry`.
Once that lands, delete `_contract_for`'s `except` branch and keep only
`registry.get(skill)`; `RUNTIME_AUTHORED_SKILLS` in `get()` stays, because it
is what makes `system_registry` admit the step at validation.

---

## H8 — The navigation stack is red in the shared tree (owner: Lane D)

**Not Lane C's, and it blocks live e2e verification.** At Lane C exit,
`safe_approach_pose` returns `None` for a plain near-object goal, so grounding
resolves and the mission then fails `unreachable` with `goal=None`.

Minimal reproduction, no Lane C module in the path (from `tests/`):

```python
nav = test_navigation._semantic_nav()
mission = nav.start("wait by the lamppost")
nav.step(test_navigation._lamppost_observation())
nav.step(test_navigation._lamppost_observation())
# mission.goal is None; metadata: resolution_state='unreachable',
# grounding_outcome='RESOLVED'; semantic_goal is exactly
# SemanticGoal(query='lamppost', kind='object', terminal_relation='near',
#              terminal_behavior='hold')
```

Reddened by it at Lane C exit (all green in the Lane C **entry** measurement at
02:41–02:52):

```
tests/test_navigation.py::test_near_object_arrival_requires_vicinity_and_safe_support_region
tests/test_navigation.py::test_near_arrival_rejects_unsafe_current_target_lidar_range
tests/test_approach_traffic_wiring.py::test_release_publishes_a_seed_for_the_runtime_and_seeds_the_navigator
tests/test_approach_traffic_wiring.py::test_align_ticks_do_not_wipe_the_held_ramp
tests/test_embodied_plan_eval.py::test_full_gate_executes_physics_and_separates_unsupported
tests/test_embodied_plan_eval.py::test_sidewalk_and_lamppost_use_evaluator_truth_after_execution
tests/test_headless_city_tasks.py::test_walk_to_sidewalk_reaches_safe_interior_and_stops_from_multiple_starts[default-origin]
```

File mtimes at Lane C exit: `navigation/approach.py` 08-07 03:03,
`navigation/pipeline.py` 08-07 03:04, `instructnav/scoring.py` 08-07 02:58,
`runtime.py` 08-07 02:58 — all after the entry suite finished, none touched by
Lane C.

**Consequence for Lane C's live e2e evidence:** every case whose pass depends
on reaching a near-object or region goal fails, including the two
**pre-existing, entry-green** cases
`test_go_to_the_sidewalk_grounds_plans_and_arrives` and
`test_walk_towards_the_lamppost_grounds_plans_and_arrives`. Lane C's four
unverified cases (two paraphrases, two superlatives) are in that set and must
be re-run once the approach path is green. The cases that do **not** depend on
it — the N12 owner gate, the N13 posture gate, the misleading-negation case,
and the `find the fountain` paraphrase — were all run live and passed.
