# Lane C — vocabulary / relations / language (stratum 3) · status

**Date:** 2026-08-07 · **Plan:**
[docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
stratum 3 + the language half of eval instrument 4 · **Builds on:**
[SUPERLATIVE_STATUS.md](../../20260807/task_1/SUPERLATIVE_STATUS.md) (SUP-1..4,
landed the day before — not redone), [W0_STATUS.md](W0_STATUS.md),
[LANE_A_STATUS.md](LANE_A_STATUS.md), [LANE_B_STATUS.md](LANE_B_STATUS.md).
**Handoffs:** [LANE_C_HANDOFFS.md](LANE_C_HANDOFFS.md).

## Outcome per card

| card | outcome |
|---|---|
| C-1 — RelationSpec registry | **done.** New pure module `navigation/relation_registry.py`; 7 relations registered, every one delegating to the existing K0 builder. `goals.py` reads its preposition alternations from it. JEPD measured, not assumed — the proximity family is neither disjoint nor exhaustive, and both the overlaps and the gaps are pinned. |
| C-2 — scene semantics sidecar | **done.** `configs/scenes/city_block.semantics.yaml` + `scene_semantics.py` (fail-closed). `city_semantics.py`'s three tables and its duplicated `_label_for_instance` chain now derive from it, with whole-output bit-equality proven against the retired literals. |
| C-3 — N12 owner bridge | **done, xfail flipped, verified live.** |
| C-4 — N13 compile half | **done.** Two-step plan lands; posture half is a new hard-gate e2e case that **passes live**; placement half stays xfail, reason rewritten to placement-only. |
| C-5 — U33 sweep | **done.** All 7 `ClosedIntent`s have a product-path case. **Two defects found and one fixed**: `handle_text("halt")` stopped nothing (fixed); RESUME leaves the executive task suspended (pinned, backlog N14 — `runtime.py` is Lane D's). |
| C-6 — language robustness | **(a) done** (clarify fallback); **(b) done** — 3 paraphrases + 1 misleading; the misleading case and the `find the fountain` paraphrase pass live, the other two paraphrases are pinned with their own baselines; **(c) cases written, both superlative cases UNVERIFIED live** — the object-approach path is red in the shared tree (Lane D card D-5). See "Why four cases are pinned". |

---

## C-1 — RelationSpec registry

`src/parcel_robot/navigation/relation_registry.py` (new, pure). Each relation
is one registered unit: `name · aliases · anchor kinds · frame-of-reference
policy · predicate · goal-region builder`.

| relation | aliases | anchor | frame | goal region (delegated to) |
|---|---|---|---|---|
| `near` | at, beside, by, near | object | absolute | `object_near_goal_region` |
| `next_to` | next to | object, owner | absolute | `object_next_to_goal_region` |
| `towards` | toward, towards | object | relative | `object_towards_goal_region` |
| `inside` | in, inside, within | region | absolute | `region_inside_goal_region` |
| `follow` | come, follow, heel | owner | relative | `owner_anchored_goal_region` |
| `behind` | behind | owner | **intrinsic** | `owner_anchored_goal_region` |
| `orbit` | around, circle, orbit | owner | relative | **none, on purpose** |

**No new geometry.** Every builder is a three-line adapter onto the K0
functions in `instructnav/scoring.py`, and the predicate is
`GoalRegion.contains` — literally the call the scorer makes — so planning and
K0 verification cannot drift apart by convention.
`test_registry_goal_region_is_the_k0_builder_output` asserts equality of the
built regions; `test_the_predicate_is_the_same_call_the_scorer_makes` asserts
the predicate agrees pointwise.

**`orbit` reports `has_goal_region == False`** rather than being handed a
plausible disc. Orbit success is net signed swept angle
(`orbit_revolutions`), a trajectory property; a fabricated disc would be a
second arrival authority that disagreed with the sweep.

**`behind` is the only intrinsic-frame relation**, which is exactly why it —
and not plain follow — carries `owner_heading_available` at admission. The
registry now *states* that; before, it was a comment in `compiler.py`.

### goals.py stopped keeping its own copy

Three literal alternations became registry reads:

```python
_PROXIMITY_PREPOSITIONS = RELATIONS.preposition_alternation(("near", "next_to"))
_NEXT_TO_ALIASES        = RELATIONS.alias_alternation(("next_to",))
_TOWARDS_ALIASES        = RELATIONS.alias_alternation(("towards",))
```

They reproduce the previous literals exactly, pinned twice: by equality with
the derived alternation and by the literal set itself
(`{at, beside, by, near, next\s+to}`, `{toward, towards}`). Ten directive
parses are re-pinned unchanged.

`preposition_aliases` is a *subset* of `aliases` per relation, because the two
questions differ: `inside` has aliases (so `resolve_relation_word("inside")`
works, which the clarify fallback needs) but **no** destination preposition —
"go to the sidewalk" contains no relation word at all; the region-noun
classifier is what selects `inside`.

### JEPD: the honest answer is "no", and here is how much

The card asked for a JEPD-style exactly-one-of property test for the
proximity family, *or* documentation of why the bands legitimately overlap
plus a pin on the overlap. It is the second, and the measurement is more
interesting than the property would have been.

Measured at a lamppost anchor (point anchor, radius 0):

| pair | overlap interval |
|---|---|
| `next_to` ∩ `towards` | **0.60 – 1.50 m** |
| `next_to` ∩ `near` | **1.12 – 1.32 m** |
| `near` ∩ `towards` | **1.12 – 1.32 m** |

and at **1.2 m all three hold at once**. Not disjoint. Nor exhaustive:

- 0.2 m from a lamppost → **no** proximity relation holds (inside every floor);
- 2.6 m from a lamppost → **no** relation holds (past every ceiling);
- **3.0 m from a building → no relation holds**, but 3.5 m is `near` — a
  *middle* gap between `towards`' 2.5 m ceiling and a building's 3.46 m near
  floor.

Why the overlap is legitimate rather than a bug: `next_to` is a *social
placement* band, `towards` is a *stopped-short-of* band, and `near` is derived
per anchor radius from the stand-off envelope. A pose 1.2 m from a lamppost
honestly satisfies all three; collapsing them would mean lying about one.
What must not move silently is the size of the overlap, so
`proximity_band_overlaps()` computes it and the tests pin it.

One consequence is load-bearing elsewhere: **`next_to` is the empty set around
a building.** `GoalRegion.contains` requires the pose to be outside the anchor
footprint *and* inside the band, and a 2.34 m footprint against a 0.4–1.5 m
band admits nothing. That is why the sidecar refuses to advertise `next_to`
for `building` (below), and it is checked both ways.

**Consumption sites** in `pipeline.py` / `scoring.py` are **not** wired — both
files are Lane D-owned this round. Exact target lines are in
[LANE_C_HANDOFFS.md](LANE_C_HANDOFFS.md) H1, including the soft-import
discipline the frozen BARN bundles require.

---

## C-2 — per-scene semantics sidecar

`configs/scenes/city_block.semantics.yaml` (new) +
`src/parcel_robot/scene_semantics.py` (new loader).

**Fail closed at every level.** Unknown top-level or per-class keys, an
affordance that is not a registered relation, an affordance whose anchor kind
the relation does not accept, a landmark role outside the closed vocabulary, an
attribute key the attribute matcher cannot read, a prefix naming an undeclared
class, a class no prefix can ever match, and a prefix ordering that would
shadow a longer sibling are each an error, each with a test.

That last one converts a comment into a rule: `tree_top_` **must** precede
`tree_`, or every canopy geom files under the trunk. The loader now proves it.

**Derived from the sidecar, proven bit-identical to the literals they
replaced:** `OBJECT_PREFIX_TABLE`, `REGION_PREFIX_TABLE`, `CLASS_ALIASES`, and
`_label_for_instance` (which was a *second* hand-written copy of the object
prefix table — a class added to one and forgotten in the other would have
extracted with label `"object"` and grounded against nothing).

The equality claim is made on the **whole extraction output**, not just the
tables: `test_extraction_is_bit_identical_to_the_retired_literals` re-extracts
the real `city_block.xml` twice — once derived, once with the literals and the
old label chain monkeypatched back — and compares the serialized result,
including key order and goal-region metadata. It is identical.

**Affordances are relation names**, validated against the registry, so the
sidecar can never advertise a relation the robot has no predicate for. The
`building` class deliberately omits `next_to` with the reason written down;
`test_declared_affordances_are_achievable_at_the_scenes_real_radii` checks
every advertised affordance has a non-empty goal region at the scene's
*derived* radii (read from `evals/nav_instruct/scene_truth.json`, never from
the sidecar), and a companion test shows building/`next_to` would fail it.

**Attribute metadata seam.** The sidecar may declare per-class metadata, and
its keys are validated against `navigation.attributes.SIZE_METADATA_KEYS`: the
matcher owns what counts as a size, the sidecar owns the values. Every class
declares `{}` today, which is why bit-equality holds — the seam exists and
nothing rides it yet. The `tree` class carries the scene fact in prose: the two
trees are geometrically identical (0.58 m derived radius each), so **no size
attribute can distinguish them**, which is what makes `attributes.py`'s
inclusive median comparison the honest choice rather than a rounding accident.

**Not merged with `evals/nav_instruct/scene_truth.json`**, and the sidecar
header says why: that file is *generated* geometry (Wave 0, W0-D), this file is
*hand-authored* vocabulary with no coordinates at all. A test asserts the
sidecar carries no coordinates.

A third derived view, `detector_query_set()`, is built and unused — it is the
NanoOWL prompt list the plan names, present so the open-vocab step reads this
sidecar instead of growing a fourth copy of the vocabulary.

---

## C-3 — N12: one authority for "the owner"

`goals.OWNER_REFERENT_TABLE` (`owner`, `the owner`, `my owner`, `your owner`,
`me`, `my side`, `my position`, `you`, `your side`) +
`owner_referent_from_directive()` (pure, negation-blocked).
`local_plans.sketch_navigate` returns `sketch_come()` for any of them — the
**same** `FollowFormation(relation="follow")` sketch "come here" produces.

Two phrasings that resolve differently is the D5 disagreement class, so the
bridge is a *substitution*, not a parallel path:
`test_no_owner_phrasing_can_produce_a_navigate_to_step` iterates the whole
table and asserts the plan is always `["FollowFormation"]`.

Admission is unchanged in the direction that matters: "go to the owner" routes
`direct_skill`/`navigation_directive`, and `direct_skill` is what selects the
**system** registry — the only one that admits `relation="follow"`
(arbitration OB-2). Validating the same sketch against the model-facing
registry is still refused with `must be one of ['behind']`, pinned, so the
bridge did not widen what a language model can author.

**Live, 2026-08-07 — `test_go_to_the_owner_arrives_in_the_owner_anchored_region`
PASSED as a hard gate** (owner walked 3 m up the block first so the approach is
non-vacuous; formation held; owner-anchored predicate satisfied; the navigation
lane never armed). The xfail is gone.

---

## C-4 — N13 compile half: "sit next to X" emits a real plan

`sketch_settle_next_to` produces **two** steps —
`NavigateTo(directive="sit next to the bench")` + `Pose(name="sit")` — under a
`hold` / `current_pose` goal.

That goal shape is not a style choice. `PlanValidator._validate_goal_completion`
admits a terminal `Pose` step proving `skill_completed` **only** under a `hold`
goal, and `_validate_plan_level` allows `hold` only with a `current_pose`
target. Any other shape is refused. K6's compound machinery was already built
for exactly this; nothing had ever emitted it.

Wiring, minimal and without a second posture authority:

- Dispatch reuses the runtime's existing posture door
  (`_brain_return_to_safe_pose`: stop motion, then apply a catalog pose).
  `Pose` differs from `ReturnToSafePose` only in its admission contract (no
  `battery_critical` gate — which is what made `ReturnToSafePose` unusable for
  a settle) and its argument name. Its contract already existed in
  `validator.py`; it was simply unreachable.
- The verifier branch is `posture` for both, reading `state.posture` — the
  applied posture, never the request. A pose that is requested but not settled
  stays `in_progress`; a robot still moving does not complete it.

**Admitting it cost the most design thought in this round**, because three
obvious routes each break something frozen. Measured, not guessed:

| route | what it breaks |
|---|---|
| add `Pose` to `agent.brain.skills` in `configs/robot.yaml` | that file is a **locked input of the frozen embodied-plan manifest** (`evals/companion/embodied_plan_v1/manifest.json` pins its SHA-256). 1 failure + 7 errors in `tests/test_embodied_plan_eval.py`. |
| move `Pose` into `SYSTEM_SKILL_NAMES` | that set is what `SkillContractRegistry.default()` filters on, and the frozen live-planner probe asserts `Pose` **is** in the full default registry and raw schema. `tests/test_live_planner_eval.py` red. |
| add `Pose` to `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS` | that set *is* the model-facing schema enum; `tests/test_planner_quality_v2.py` asserts `"Pose" not in schema_skills`. Red. |

What landed instead is deliberately narrow, and `configs/robot.yaml` is
**byte-identical to entry**:

- `RUNTIME_AUTHORED_SKILLS = {"Pose"}` — skills only the runtime's own
  deterministic sketches author.
- `SkillContractRegistry.get()` resolves them **only when
  `system_authored=True`**. It is in `get`, *not* in `names`, so every derived
  surface — response schemas, prompt contracts, the duplex skill list — is
  provably unchanged, and the model-facing registry still refuses a `Pose` step
  with `unknown_skill` (pinned).
- `compiler._contract_for` falls back to the system contract table for the same
  set, because `RobotRuntime._materialize_brain_planner_output` compiles
  *every* sketch against `brain_registry` — even a `direct_skill` one the
  runtime authored — while `_accept_plan` re-compiles and validates against the
  route-selected registry. The fallback is not general: any other unknown skill
  still raises, pinned by
  `test_the_compiler_fallback_covers_system_skills_only`. Removing it is a
  one-line change in `runtime.py` (H7).

`robot_stopped` on the second step is what keeps the sit from firing
mid-approach; the compiler owns it, so a model omission cannot weaken it.

**The two defects are now reported separately** in the e2e:

- `test_sit_next_to_the_lamppost_emits_a_posture_step_and_reaches_it_if_it_arrives`
  — **HARD GATE, passed live 2026-08-07.** Asserts the admitted plan is
  `["NavigateTo", "Pose"]`, and asserts the posture *conditionally* on
  navigation reaching terminal success. Conditional on purpose: gating the
  posture on an arrival that does not yet happen would report the placement
  defect twice and the posture defect never. It starts biting with no edit the
  moment placement lands.
- `test_sit_next_to_the_{bench,lamppost}_settles_beside_it_in_a_sit` — still
  xfail, **reasons rewritten to placement-only** and re-attributed to the N11
  final-approach family. Both **xfailed live 2026-08-07**, i.e. the placement
  half is still exactly where it was.

**What the lamppost sit case actually does now** (live, 2026-08-07): admission
is clean, the published plan is `["NavigateTo", "Pose"]`, navigation does not
reach terminal success (the pre-existing 7 cm near-miss), so the `Pose` step
never runs and `_last_posture` stays `unknown`. The posture defect is gone by
construction; what remains is one defect, not two.

**Known wart, handed off:** the plan acknowledgement for a `hold` goal is
"Okay—I'll stay here." — wrong for a command that will walk to a bench and sit.
`_plan_acknowledgement` lives in `runtime.py` (Lane D's). See
[LANE_C_HANDOFFS.md](LANE_C_HANDOFFS.md) H2.

---

## C-5 — U33 sweep: every ClosedIntent on the product path

`tests/test_closed_intent_product_path.py` (new, admission-regression shaped —
a real `RobotRuntime` over a fake backend, entered at `handle_text`, no sim).
Every `ClosedIntent` gets route → registry → admission → **executive effect**,
plus a guard that a new enum member reddens the file until covered.

**Two defects found by writing it**, both of the predicted shape.

### 1. `handle_text("halt")` stopped nothing — FIXED

`parse_closed_intent("halt")` returned `ClosedIntent.STOP`. But
`EMERGENCY_STOP_PHRASES` was a *separate literal* — `{stop, stop now,
emergency stop}` — that omitted it, and `_handle_text` deliberately skips
`STOP` inside the closed-intent handler (STOP is handled on the fast path
above). So "halt" fell past **both** branches, answered *"I did not understand
that command"*, and the robot kept moving. Measured on the product path:
`arbiter.emergency_stopped` stayed `False`.

Three copies of "which words stop the robot" is how it got lost, so the fix is
one source: `closed_intents.closed_intent_phrases(ClosedIntent.STOP)` now
feeds both `agent.EMERGENCY_STOP_PHRASES` and the router's `_EMERGENCY_STOP`.
Pinned by `test_the_stop_grammar_has_exactly_one_source` and by a parametrized
case over **every** stop phrase.

### 2. Cap intents routed `conversation_only` — FIXED

`pause`, `resume`, `faster`, `slower` matched no router rule and fell to
`conversation_default`. Nothing misbehaved — the agent parses closed intents
before consulting the route — but every consumer of `IntentFrame.route`
(metrics, the frozen router cases, any future barge-in policy) saw an
executive command labelled as chat. Same route/registry split that hid COME,
one layer up.

Router rule `closed_intent:<name>` → `direct_skill`, membership read from
`parse_closed_intent` so there is no second grammar. `requires_fresh_scene` is
`False` for caps: a cap retimes or suspends work already admitted against a
snapshot, and demanding a fresh one would make "pause" fail exactly when
perception is degraded.

The amendment grammar was unified the same way: the router's correction test is
now `_CORRECTION ∪ (parse_closed_intent(...) is GOAL_AMEND)`, so "the other
one" / "not that one" no longer route `conversation_only` while the agent
pauses and replans them.

### Measured effects, per intent

| intent | route / rule | executive effect asserted |
|---|---|---|
| STOP | `direct_skill` / `emergency_stop` | every stop phrase latches `arbiter.emergency_stopped` |
| PAUSE | `direct_skill` / `closed_intent:pause` | navigation `state="paused"`, ResumeIntent stored, task `suspended` |
| RESUME | `direct_skill` / `closed_intent:resume` | channel returns to `searching`/`navigation_resumed`; honest "nothing paused" when idle |
| FASTER | `direct_skill` / `closed_intent:faster` | `PaceCap` +0.15, saturates at 1.25 |
| SLOWER | `direct_skill` / `closed_intent:slower` | `PaceCap` −0.15, saturates at 0.35 |
| COME | `direct_skill` / `come_to_owner` | system sketch admitted, follow lane `direct` |
| GOAL_AMEND | `deliberative_plan` / `task_correction` | gate ok, navigation `paused`/`goal_amend`, replan `deferred_no_planner`; honest refusal when nothing is active |

**PAUSE deliberately leaves `navigation.enabled == True`** — it is a true
pause, not a stop; the channel keeps its goal. Asserting `enabled is False`
would be asserting a STOP, which the pause path is written not to do (a stop
destroys the ResumeIntent).

### The defect this sweep could not fix — backlog N14

RESUME restores the navigation *channel* but never un-suspends the executive
*task*: after pause→resume the channel reads `state="searching"`,
`reason="navigation_resumed"` and advances, while the task record stays
`state="suspended"`, `last_detail="suspended:closed_intent_pause"` across
further `_step_brain()` ticks. The robot drives while the plan step that
authorized it is suspended. The fix is in `RobotRuntime._apply_closed_intent`'s
resume branch (Lane D's file), so it is **pinned xfail with the measurement**
and written up in [LANE_C_HANDOFFS.md](LANE_C_HANDOFFS.md) H3 + backlog N14.

---

## C-6 — language robustness

### (a) Novel-verb clarify fallback

`voice/scene_reference.py` (new, pure) + one branch in `agent._handle_text`
immediately before the flat `"I did not understand that command"`.

> *"I'm not sure what you want me to do with the bench — I can go to it, sit
> next to it, or walk towards it. Which would you like?"*

Both halves are data. The class comes from the sidecar (longest surface form
wins, so "street light" resolves to `lamppost` rather than stopping at
"street"); the offers come from each relation's own `offer_phrase`, filtered by
that class's **affordances**. So the building offer omits "sit next to it" —
the robot does not advertise a placement its own arrival authority could never
certify.

Two guards keep it honest:

- **Gated on `router.physical_cue_present`** (exported so the agent asks the
  *same* question the router asks, rather than keeping a second verb list). An
  utterance that *does* carry a motion verb but matched no rule is left to the
  existing path — inviting a retry there would be a motion suggestion, not a
  clarification.
- **Returns `None` when nothing is recognized.** "Befriend the neighbour",
  "tell me a joke", and "xyzzy" still get the flat reply. It must not
  manufacture a helpful-sounding answer out of nothing.

The sidecar load is lazy and soft *here only* (a deployment with no sidecar
falls back to today's reply rather than making the agent unusable over a
clarification helper); the loader itself stays fail-closed on a malformed one.

### (b) Paraphrase + misleading variants

| existing case | paraphrase | invariant asserted |
|---|---|---|
| `go to the sidewalk` | `please move onto the sidewalk` | same region label, same K0 arrival |
| `can you walk towards the lamppost` | `head towards the lamppost` | same target, same towards band |
| `go to the fountain` | `find the fountain` | same honest refusal — the `find` verb class inherits the bounded search, terminal failure, and named not-found report |

Paraphrases vary the **verb and politeness, never the noun**: swapping in an
alias would test the grounder's alias table (which has its own tests) and
confound the two failures.

**Misleading variant — `don't go to the sidewalk`, where NON-compliance is the
pass.** It contains a complete, well-formed destination directive, so a system
that pattern-matches the noun phrase and drops the negation obeys it.
Deliberately not routed through `_run_command_to_terminal` (that helper asserts
the deterministic *plan* lane was taken; here the pass condition is that no
plan was made). Asserts: no plan admitted, **no executive task created and the
navigation lane never armed, polled for 8 s**, total displacement ≤ 0.08 m, and
no arrival claim in chat. **Passed live 2026-08-07.**

### (c) Superlative cases

Two new cases, split so a superlative regression cannot hide behind the known
lamppost arrival gap:

- `test_find_the_nearest_lamppost_selects_and_approaches_the_near_one` — hard
  gate on what the superlative work owns: the phrasing reaches the navigation
  lane at all (before SUP-1, `find` matched no pattern), `directive_superlative
  == "nearest"` reaches the mission, the committed candidate is `lamp_post_1`
  (3.16 m) and not `lamp_post_2` (7.30 m), and the robot closes >1 m on it. It
  deliberately does **not** assert the K0 `near` predicate: that band is only
  0.20 m wide for a point anchor and its terminal-verification gap is
  pre-existing.
- `test_run_to_the_nearest_lamppost_applies_the_pace_cap_during_motion` — the
  pace cap is sampled **across execution** (`pace_peak`), not read at the end,
  because a cap written and reverted before the robot moves is not a pace
  change; plus the cap must be released at mission end or a directive-scoped
  pace would leak into every later command.

**Neither is verified live — see below.**

---

## Verification

### Entry state (measured before any Lane C edit)

`.parcel/bin/python -m pytest tests/ -q` →
**2 failed, 2397 passed, 7 skipped, 5 xfailed** in 667 s.

Both failures are **pre-existing and Lane A's**:
`tests/test_authority_no_literal_drift.py::test_no_new_retired_family_literals`
and `::test_collision_and_approach_hold_only_the_documented_non_radius_residue`,
both caused by two un-allowlisted `1.2` literals in
`navigation/collision.py` lines 19/25 (the `_FrozenBundleEnvelope` fallback
added for frozen BARN bundles). The BARN red the coordinator reported fixed
**is** fixed — `test_barn_v8_policy_bundle` passed. Lane C touched neither file;
both are still red at exit. See [LANE_C_HANDOFFS.md](LANE_C_HANDOFFS.md) H5.

The e2e block at entry read `...xx...xx.` — 6 passed, 4 xfailed, the known
state.

### Exit state (measured, full suite, `MUJOCO_GL=egl`)

`.parcel/bin/python -m pytest tests/ -q` →
**15 failed, 2618 passed, 7 skipped, 5 xfailed** in 845 s
(+221 passing tests against entry).

The 15, every one attributed:

| count | tests | owner |
|---|---|---|
| 2 | `test_authority_no_literal_drift.py` ×2 | **Lane A** — inherited entry reds (H5), untouched |
| 7 | `test_navigation.py` ×2, `test_approach_traffic_wiring.py` ×2, `test_embodied_plan_eval.py` ×2, `test_headless_city_tasks.py` | **Lane D** — `safe_approach_pose → None`, card D-5 (H8). All green at Lane C entry. |
| 2 | e2e `test_go_to_the_sidewalk…`, `test_walk_towards_the_lamppost…` | **Lane D**, same cause. Pre-existing hard gates, not Lane C's to pin. |
| 4 | e2e paraphrase ×2 + superlative ×2 | **Lane C's new cases, same cause** — pinned xfail *after* this run (see below) |

The four Lane C cases were pinned after this measurement; re-run of exactly
those four afterwards: **3 xfailed, 1 xpassed** (the `towards` paraphrase
XPASSes alone on an uncontended box while its own baseline fails, so that band
is marginal rather than broken — recorded in the pin, which is non-strict for
this reason). Expected suite state with the pins: **11 failed, 9 xfailed**, and
**none of the 11 is a Lane C file**.

**The navigation reds are Lane D's, and they were watched clearing in real
time.** Two non-e2e-only runs (`--deselect tests/test_voice_nav_e2e.py`) at
different minutes of the same session, with no Lane C edit between them:

| run | result | navigation reds |
|---|---|---|
| earlier | 9 failed, 2610 passed, 7 skipped, 2 xfailed (73 s) | `test_navigation.py` ×2, `test_approach_traffic_wiring.py` ×2, `test_embodied_plan_eval.py` ×2, `test_headless_city_tasks.py` |
| later | **4 failed, 2619 passed**, 7 skipped, 2 xfailed (75 s) | only `test_embodied_plan_eval.py` ×2 |

Five of the seven cleared while Lane D kept landing work in
`navigation/approach.py` and `navigation/pipeline.py`. The two that remain are
the same family: `sidewalk_then_lamppost` fails its **lamppost leg**
(`lamppost_controller_arrived: false`) while the standalone
`correct_active_task_to_lamppost` case passes with `controller_arrived: true`
— a frozen PlanIR suite that never parses a directive through any Lane C
module. Nothing Lane C changed moved between those two runs.

At the last measurement the only non-e2e reds are **2 Lane A** + **2 Lane D**.

**Two Lane C regressions were found and fixed during this round**, both caught
by the suite rather than by reasoning:

1. Adding `Pose` to `configs/robot.yaml` broke the frozen embodied-plan
   manifest's SHA-256 lock (1 failure + 7 errors). Reverted; the file is
   byte-identical to entry, and the settle skill is admitted through
   `RUNTIME_AUTHORED_SKILLS` instead.
2. The packaged copy `src/parcel_robot/config/robot.yaml` must stay
   byte-identical to `configs/robot.yaml` (`test_authority_config_drift`);
   both are back to their entry bytes.

### New tests

| file | count |
|---|---|
| `tests/test_relation_registry.py` (new) | 28 |
| `tests/test_scene_semantics.py` (new) | 22 |
| `tests/test_closed_intent_product_path.py` (new) | 35 passed + 1 xfail |
| `tests/test_owner_and_settle_plans.py` (new) | 38 |
| `tests/test_voice_nav_e2e.py` | +7 cases (1 flipped from xfail, 1 new hard gate, 3 paraphrase, 1 misleading, 2 superlative); 17 collected, up from 11 |

Net: **+221 passing tests** between the entry and exit full-suite runs.

### ruff

Clean on every touched file, including the two pre-existing findings in
`agent.py` that surfaced once it was touched (import order; a nested `if` that
is now a single condition with the STOP exclusion documented).

### Live e2e (`MUJOCO_GL=egl`, real `parcel_robot.sim` city block, one sim +
one runtime per case, node-id invocations)

| case | outcome | what it proves |
|---|---|---|
| `test_go_to_the_owner_arrives_in_the_owner_anchored_region` | **PASSED** (was xfail) | N12 hard gate: approach lane, formation held, owner-anchored predicate, navigation lane never armed |
| `test_sit_next_to_the_lamppost_emits_a_posture_step_and_reaches_it_if_it_arrives` | **PASSED** (new hard gate) | N13 compile half: admitted plan is `["NavigateTo","Pose"]` |
| `test_sit_next_to_the_bench_settles_beside_it_in_a_sit` | **XFAIL**, reason rewritten to placement-only | the placement defect, unchanged |
| `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` | **XFAIL**, reason rewritten to placement-only | the placement defect, unchanged |
| `test_misleading_negated_directive_must_not_be_obeyed` | **PASSED** (new) | non-compliance: no plan, no task, no motion, no arrival claim |
| `test_paraphrase_find_the_fountain_still_reports_honestly` | **PASSED** (new) | the `find` verb class inherits the honest refusal |
| `test_paraphrase_move_onto_the_sidewalk_resolves_the_same_way` | **PINNED xfail** | see below |
| `test_paraphrase_head_towards_the_lamppost_resolves_the_same_way` | **PINNED xfail** | see below |
| `test_find_the_nearest_lamppost_selects_and_approaches_the_near_one` | **PINNED xfail — unverified** | see below |
| `test_run_to_the_nearest_lamppost_applies_the_pace_cap_during_motion` | **PINNED xfail — unverified** | pace assertions passed; displacement did not |

### Why four cases are pinned rather than green, with the evidence

**The navigation-arrival path is red in the shared tree at Lane C exit, and it
was green at Lane C entry.** Two independent demonstrations that this is not
Lane C's:

1. **The pre-existing hard gates fail too.**
   `test_go_to_the_sidewalk_grounds_plans_and_arrives` and
   `test_walk_towards_the_lamppost_grounds_plans_and_arrives` — untouched by
   Lane C, green in the entry measurement — both fail in the same window. The
   sidewalk case ends at (0.37, −2.84), *inside* `sidewalk_south`, 5.24 m from
   the frozen north polygon the eval scores.
2. **A minimal reproduction with no Lane C module in the path.** Driving
   `DirectiveNavigator` directly with `"wait by the lamppost"` and a synthetic
   lamppost observation gives `grounding_outcome="RESOLVED"` and then
   `goal=None`, `resolution_state="unreachable"` — `safe_approach_pose`
   returned `None`. The `SemanticGoal` in that mission is byte-identical to
   what it has always been (`query='lamppost'`, `near`, `hold`).

The same signature reddens seven non-e2e tests Lane C did not touch
(`test_navigation.py` ×2, `test_approach_traffic_wiring.py` ×2,
`test_embodied_plan_eval.py` ×2, `test_headless_city_tasks.py`).
`navigation/approach.py` and `navigation/pipeline.py` were modified at 03:03
and 03:04 on 2026-08-07, after the Lane C entry suite finished at 02:52.

**Lane D's own record explains half of it and hands the other half to Lane C.**
[LANE_D_STATUS.md](LANE_D_STATUS.md) card D-5 landed a fail-closed proxemic
veto on the ranked approach pose and documents the `sidewalk_south` outcome
precisely: the veto strikes out every north approach pose, the mission
replans, and grounding's region tie-break picks the other equally valid
sidewalk instance. Lane D writes: *"does 'the sidewalk' mean a specific polygon
or any sidewalk? That is a Lane C vocabulary question (region instance
selection)."* **Lane C did not do it this round** — it is not in the C-1..C-6
card set — so it is carried forward.

**What this costs the two superlative cases specifically.** Their claim (the
`nearest` superlative selects `lamp_post_1` and the robot closes on it) has
**never been observed to fail**; it cannot be measured while every near-object
approach returns `unreachable`. Their pins say so in those words and ask for a
re-run, not for acceptance.

**Also confirmed, mutually:** live-sim contention. Lane D ran its own sim
batches through this window and reports Lane C's three concurrent EGL sims
killing several of its runs; Lane C's first e2e batches ran with the box at
load average 112–130 for the same reason. All Lane C outcomes reported as
PASSED above were re-observed outside that contention.

## Non-claims

1. **The registry is not wired into the navigator.** `pipeline.py` and
   `scoring.py` still branch on relation literals; the registry is a lookup
   layer plus tests. Consumption is a handoff (H1), and until it happens the
   "one predicate serves planning and verification" property is *available*,
   not *enforced*.
2. **The sidecar does not change any behavior.** It is a derivation with a
   bit-equality proof. No class declares attribute metadata; nothing consumes
   affordances except the clarify fallback; `detector_query_set()` has no
   consumer at all.
3. **N13's placement half is untouched.** "Sit next to X" still does not sit,
   because it still does not arrive. What changed is that the *reason* is now
   one defect instead of two, and the posture half has its own gate.
4. **The `hold`-goal acknowledgement is wrong for a settle plan** and was not
   fixed (H2).
5. **RESUME's half-restore was found, not fixed** (N14, H3).
6. **The four pinned e2e cases are unverified, not accepted.** Two of them
   (`find the nearest lamppost`, `run to the nearest lamppost`) have never been
   observed green on any machine state. Their pins are measurement gaps with a
   re-run instruction, and they must be re-run before anyone reports the
   superlative work as product-path verified.
7. **Region-instance selection ("does 'the sidewalk' mean a specific polygon or
   any sidewalk?") was NOT done.** Lane D's D-5 record assigns it to Lane C;
   it is not in the C-1..C-6 card set and no code in this round addresses it.
8. **The compiler's runtime-authored contract fallback is a workaround**, not a
   design improvement. It exists because `runtime.py` compiles every sketch
   against the model-facing registry; the proper fix is one line in a file this
   lane does not own (H7).
9. **The frozen router cases were not updated** — `evals/**` was off-limits.
   The eight rows are written out in H4.
10. **The two entry reds are still red** and belong to Lane A (H5).
11. **No new harness, no ontology engine, no config-framework adoption, no
   expose-everything-to-YAML sweep.** The sidecar's knob count is *lower* than
   the literals it replaced: `_label_for_instance` went from six branches to
   zero, and the prefix ordering rule became machine-checked rather than a
   comment.

## Files touched

**New source:** `src/parcel_robot/navigation/relation_registry.py`,
`src/parcel_robot/scene_semantics.py`,
`src/parcel_robot/voice/scene_reference.py`

**New config:** `configs/scenes/city_block.semantics.yaml`

**Modified source:** `src/parcel_robot/navigation/goals.py` (registry-derived
alternations, `OWNER_REFERENT_TABLE`, `owner_referent_from_directive`),
`src/parcel_robot/city_semantics.py` (sidecar-derived tables,
`_label_for_instance`, attribute-metadata seam),
`src/parcel_robot/voice/local_plans.py` (`sketch_settle_next_to`, owner bridge,
`SETTLE_POSE_NAME`), `src/parcel_robot/voice/closed_intents.py`
(`closed_intent_phrases`), `src/parcel_robot/brain/router.py`
(one stop grammar, `closed_intent:*` rules, unified amendment grammar,
`physical_cue_present`), `src/parcel_robot/brain/validator.py`
(`RUNTIME_AUTHORED_SKILLS` + the `get()` admission),
`src/parcel_robot/brain/compiler.py` (`_contract_for`),
`src/parcel_robot/brain/runtime_adapter.py` (`Pose` dispatch + posture
verifier), `src/parcel_robot/agent.py` (derived `EMERGENCY_STOP_PHRASES`,
clarify fallback)

**Deliberately NOT modified:** `configs/robot.yaml` — byte-identical to entry
(sha256 `f64688874525f2…`), because it is a locked input of the frozen
embodied-plan manifest.

**New tests:** `tests/test_relation_registry.py`,
`tests/test_scene_semantics.py`, `tests/test_closed_intent_product_path.py`,
`tests/test_owner_and_settle_plans.py`

**Modified tests:** `tests/test_voice_nav_e2e.py`

**Records:** this file, `LANE_C_HANDOFFS.md`, `backlog/NEXT.md` (N12, N13,
new N14), `backlog/UNVERIFIED.md` (U33)

**Untouched, per file ownership:** `navigation/pipeline.py`,
`navigation/approach.py`, `navigation/semantic_map.py`,
`instructnav/scoring.py`, `detection_adapter/**`, `runtime.py`,
`authority.py`, `pose.py`, `geometry.py`, `evals/**`.
