# Superlative + attribute-qualified directives (SUP-1..SUP-4) · status

**Date:** 2026-08-07 · **Scope:** everything below the product e2e layer.
**Concurrency:** `evals/**`, `src/parcel_robot/instructnav/scoring.py`,
`tests/test_voice_nav_e2e.py`, and `evals/nav_instruct/generator.py` belong to
the Wave 0 executor this round and were **not** touched (read-only reference
only). **No e2e cases were added — that is next round, by explicit scope.**

Owner request: handle "find the nearest lamppost", "go to the closest big
tree", "running to the closest big tree" (motion verb implying pace).

## Outcome per card

| card | outcome |
|---|---|
| SUP-1 — superlative / pace / attribute parsing | **done.** `SemanticGoal` gains `superlative`, `attributes`, `pace`. Four module-level vocabulary tables. `find`/`locate`/`look for` added as a destination verb class (the owner's headline phrasing was not a navigation directive at all before). |
| SUP-2 — nearest selection | **done.** `superlative == "nearest"` sets the same `interchangeable=True` flag the region channel uses, so distance-sorted candidates resolve to the nearest instead of AMBIGUOUS. |
| SUP-3 — attribute filtering seam | **done.** New pure module `navigation/attributes.py`, applied at both selection points (grounding **and** multi-view confirmation). |
| SUP-4 — pace wiring | **done, wired** (not deferred). ~38 added lines in `runtime.py`, single-purpose, reusing the existing `PaceCap` + `resolve_cap(FASTER)`. Live-confirmed at 1.15 during locomotion. |
| (unplanned) POI grounder word-boundary fix | **done.** Found while smoking SUP-1; see "Defect found and fixed" below. |

---

## SUP-1 — parsing (`src/parcel_robot/navigation/goals.py`)

`SemanticGoal` gained three optional fields, all defaulted so every existing
construction site is unchanged:

```
superlative: str | None = None
attributes:  tuple[str, ...] = ()
pace:        str | None = None
```

### Vocabulary tables (one module-level table per family)

These are the stratum-3 seam: the per-scene semantics sidecar can replace the
literals without touching the parsing code.

| table | entries | canonical values |
|---|---|---|
| `SUPERLATIVE_TABLE` | `closest`, `nearby`, `nearest` | `nearest` |
| `PACE_VERB_TABLE` | `hurry(-ing)`, `run(-ning/-s)`, `sprint(-ing/-s)` | `fast` |
| `PACE_ADVERB_TABLE` | `quick`, `quickly` | `fast` |
| `ATTRIBUTE_TABLE` | `big`, `large`, `tall`, `small`, `little` | `size` |
| `attributes.SIZE_POLARITY_TABLE` | same five words | `at_least` / `at_most` |

A test pins `set(ATTRIBUTE_TABLE) == set(SIZE_POLARITY_TABLE)` so the parser and
the matcher cannot drift apart.

### Parsing rules

- Superlative and size adjectives are peeled off the **head** of the noun
  phrase (articles skipped); a single trailing superlative is also handled
  ("the lamppost nearby").
- `attributes` stores the **surface word the owner said** (`("large",)`, not
  `("big",)`) so refusals can quote it back. Canonicalization happens in the
  matcher.
- **Fail-safe by construction.** Only words in the tables are peeled — "go to
  the red bench" still has `query == "red bench"` and `attributes == ()`.
  A phrase that would reduce to nothing ("go to the nearest") is returned
  untouched rather than inventing a target.
- Pace is read by `pace_from_directive()` from at most the first three words
  after the address/politeness prefix, so "walk to the fun **run** sign" is
  not a sprint. Pace verbs joined the `to|onto|into` and `towards` verb
  alternations; pace adverbs are stripped as a prefix ("quickly go to X").
- **`find` is now a destination verb.** `find|locate|look for|search for
  (me)? <target>` is a navigation directive, with `find out ...` excluded as a
  question. Justification: the semantic resolution ladder already *is* a
  search (frustum → memory → scan → SearchEntity → honest refusal), so "find
  the nearest lamppost" is that ladder, not a new verb class. Before this,
  the owner's headline directive matched no pattern and never reached the
  navigation lane at all.

Existing directives are pinned unchanged in tests: `go to the sidewalk`,
`walk to the bench`, `go towards the tree`, `sit next to the bench`,
`wait by the lamppost`, `go to the nearest sidewalk`, and the
safety-rationale form. Negation/hypothetical blocking is re-pinned against
the new pace verbs.

---

## SUP-2 — nearest selection (`navigation/pipeline.py`)

```python
interchangeable = (
    semantic_goal.kind == "region"
    or getattr(semantic_goal, "superlative", None) == "nearest"
)
```

Nothing else changed in `instructnav/grounding.py` — the mechanism already
existed for region "stuff" classes. An explicit superlative is the owner
*asking for that same tie-break by name*, so it reuses it rather than adding a
second selection rule. Ambiguity across **distinct** labels still stands
(sidewalk vs crosswalk), pinned by a test.

Verified on the real city-block geometry from spawn (0, 0):

| case | without superlative | with superlative |
|---|---|---|
| lamp_post_1 (0.2, 3.15) @3.16 m vs lamp_post_2 (−6.7, −2.9) @7.30 m | AMBIGUOUS | **RESOLVED → lamp_post_1** |
| tree_1 (−5.0, 3.15) @5.91 m vs tree_2 (5.0, 3.1) @5.88 m | AMBIGUOUS (0.024 m apart, inside the 0.75 m band) | **RESOLVED → tree_2** |

---

## SUP-3 — attribute filtering (`navigation/attributes.py`, new)

Pure functions, no mission state. Attributes filter **before** the superlative
selects, so "the closest big tree" is "among the big trees, the closest".

**Chosen semantics, pinned by tests:**

- `big`/`large`/`tall` → keep size **≥** the per-class median.
- `small`/`little` → keep size **≤** the per-class median.
- Comparison is **inclusive**, so two identical trees both survive a "big"
  filter — the honest answer, since neither is bigger.
- **A single candidate of a class passes any size attribute** (it is trivially
  both the biggest and the smallest one). Documented, not accidental.
- Size is relative to the candidate's own **class**: a building does not make
  every tree small.
- Size is read from `radius_m`, falling back to `height_m`.
- A candidate with **no** size metadata is **dropped** and named in
  `unmeasurable` — never kept as if it matched.
- An unknown attribute filters nothing and is reported in `unsupported`
  (defensive: the parser leaves unknown adjectives in the noun query).

Applied at **two** selection points, because there are two:

1. `pipeline._step_semantic_resolution` — before grounding, over frustum and
   memory candidates.
2. `search.ActiveSemanticSearch.observe` — the multi-view confirmation that
   actually commits the target. Without this, "the big tree" would have been
   confirmed by whichever tree happened to be seen twice first.

**Honest empty path.** If the filter empties the candidate set, the goal falls
into the normal UNSEEN recovery ladder with `attribute_filter` and
`attribute_query` on the mission, and every `honest_not_found_reply` call site
now goes through `_refusal_label(semantic_goal)`, which quotes the attribute:
*"I looked around and couldn't find a **big tree** nearby."* The attribute is
never silently dropped.

---

## SUP-4 — pace wiring (`runtime.py`, ~38 added lines)

29 lines for two single-purpose helpers, 3 in `__init__`, 1 import, 5 call-site
lines. Inside the card's ~40-line budget, so this landed wired rather than
deferred to a backlog item. **No new speed authority:**

- `_apply_directive_pace(pace)` — on navigation start, if the directive's pace
  is `"fast"`, call `resolve_cap(ClosedIntent.FASTER, current_pace=<current>)`
  and set exactly the scale it returns on the existing `PaceCap`. The previous
  scale is saved.
- `_restore_directive_pace()` — idempotent hand-back, called from every
  navigation terminal: the arrived / unreachable branches of
  `_start_navigation_locked`, the terminal branch of `_step_navigation`, and
  `_stop_navigation_channel`.

The cap is consumed where it already was — `submit_motion` scales
`navigation`-sourced velocity by `PaceCap.scale` before arbitration, and
`manual`/`safety`/`emergency` are untouched. Arbitration semantics were not
modified. SpeedRegime consolidation remains Lane A's.

---

## Defect found and fixed: POI grounder substring match

`PlaceGrounder.ground` scored POI name words with `word in text`. The demo POI
`crosswalk_a` has the name *"crosswalk **near** coffee"*, and `"near"` is a
substring of `"nearest"` — so **every superlative directive** grounded to the
crosswalk POI at (3.5, −0.6) and never reached the semantic path.

This is **pre-existing**, not caused by this round: `go to the nearest
sidewalk` was already mis-grounded the same way. It surfaced because the
owner's headline phrasing hits it every time.

Fix: whole-word match (`\bword\b`) in that weak scoring loop only. Confirmed in
the headless city harness:

| directive | before fix | after fix |
|---|---|---|
| `find the nearest lamppost` | target `crosswalk_a`, `navigation_no_progress`, 223 steps, ends (0.45, 0.04) | target `lamp_post_1`, 96 steps, ends (1.15, 2.15) — **identical to the baseline** |
| `go to the nearest sidewalk` | target `crosswalk_a` | target `sidewalk`, **`arrived_verified`, succeeded** |

Real POI phrasings still ground: `crosswalk` → `crosswalk_a`, `coffee shop` →
`coffee_42nd`, `bookstore` → `bookstore_main`, `park` → `park_entrance`.

---

## Live smoke evidence

`MUJOCO_GL=egl` · real `parcel_robot.sim` city block, `--static-city` ·
`build_runtime(configs/robot.yaml, socket, use_llm=False)` ·
entry point `RobotRuntime.handle_text` · **one sim + one runtime per case**
(a reused runtime bleeds mission metadata and robot pose between commands and
made the first run's evidence worthless — that run was discarded).
Script: scratchpad `smoke_superlative.py` (not committed; this is a smoke, not
a test — the e2e cases land next round).

All four cases: `reasoning_source = local_plan_sketch`, `reasoning_error =
None` — the deterministic lane, no LLM, no admission dead-end.

| command | reply | grounding | target id | resolution_state | pace writes | final xy |
|---|---|---|---|---|---|---|
| `go to the lamppost` *(baseline)* | "Okay—I'll go wait near lamppost safely." | RESOLVED | `lamp_post_1` | `verification_failed` | — | (0.248, 1.791) |
| **`find the nearest lamppost`** | same | RESOLVED | **`lamp_post_1`** | `verification_failed` | — | (0.241, 1.792) |
| `go to the tree` *(baseline)* | "Okay—I'll go wait near tree safely." | RESOLVED | none committed | `unreachable` | — | (0.0, 0.0) |
| **`running to the closest big tree`** | same | RESOLVED | none committed | `unreachable` | **[1.15, 1.0]** | (0.0, 0.0) |
| **`run to the nearest lamppost`** | same | RESOLVED | **`lamp_post_1`** | `verification_failed` | **[1.15, 1.0]**, observed peak **1.15** during motion | (0.190, 1.808) |

Mission metadata recorded on the new cases:
`directive_superlative="nearest"`, `directive_attributes=["big"]`,
`directive_pace="fast"`, `attribute_query="big tree"`,
`attribute_filter="attribute_size:big attribute_unmeasurable:big"`.

**Reading of the residual failures — they are the baselines', not this
round's.** Each new directive lands on the *same* outcome, target, and final
pose as its established-phrasing baseline, to within 7 mm:

- lamppost cases end in `verification_failed` — a pre-existing terminal
  verification gap, identical for `go to the lamppost`.
- tree cases end in `unreachable` (no safe approach pose) — identical for
  `go to the tree`. In the city scene `tree_1` is co-located with `planter_1`
  and `tree_2` with `planter_2`, which is what defeats approach-pose search.

Nothing in this round makes a superlative or attribute-qualified directive
worse than its plain counterpart; the two live gaps are pre-existing and are
**not** claimed as fixed here.

**Pace, precisely.** `pace_scale_writes = [1.15, 1.0]` is the cap being raised
to `PACE_DEFAULT + PACE_STEP` and handed back at mission end.
`run to the nearest lamppost` additionally shows `observed_peak = 1.15`
sampled *while the robot was moving* (0, 0) → (0.19, 1.81), so the cap was
live during locomotion, not merely written and reverted.

---

## Verification

- **New tests:** `tests/test_superlative_directives.py` — 49 passing
  (12 parametrized parse cases, 7 pinned existing directives, fail-safe and
  blocking cases, the POI-grounder regression, 10 matcher cases, 4
  grounding-level nearest cases, 5 navigator-level integration cases, 5
  runtime pace cases).
- **ruff:** clean on every touched file.
- **Full default suite:** `.parcel/bin/python -m pytest tests/ -q` →
  **2130 passed, 7 skipped, 4 xfailed, 0 failed** (655 s). **Zero reds**, so no
  red needed attributing to a Wave-0-owned file.

  One real regression was found and fixed mid-round. The first full run failed
  `tests/test_barn_v8_policy_bundle.py` with
  `ModuleNotFoundError: parcel_robot.navigation.attributes` — `pipeline.py` is
  copied verbatim into frozen BARN bundles whose `parcel_robot` tree predates
  the new module. The import is now soft, matching the existing
  `parcel_robot.paths` / `traffic_aware` / `instructnav` pattern already in that
  file, and guarded by `_HAS_ATTRIBUTES` (a frozen bundle's own `goals.py` has
  no attribute field either, so the filter never engages there). `search.py` is
  not a v8 replacement source, so its import needs no guard.

## Non-claims

1. **No e2e cases yet.** `tests/test_voice_nav_e2e.py` is Wave-0-owned this
   round and untouched. Product-path coverage for these directives lands next
   round. The live smoke above is evidence, not a regression test.
2. **Attribute data is radius-based until the sidecar.** `radius_m` comes from
   MJCF geom size in `city_semantics`; `height_m` is read if present but no
   scene supplies it today. Real per-object attributes are stratum-3 sidecar
   work.
3. **Memory rows cannot satisfy an attribute.** `RememberedEntity` has no size
   field, so an attribute-qualified goal drops memory candidates and reports
   `attribute_unmeasurable`. Visible (frustum) candidates are unaffected. This
   is why the live tree case shows both `attribute_size:big` and
   `attribute_unmeasurable:big`.
4. **"Nearest" rides confidence-first ordering.** Candidates are sorted
   `(-confidence, distance, id)`; the superlative only disables the ambiguity
   veto. With materially different confidences the higher-confidence (possibly
   farther) instance still wins. In practice the simulator semantic camera
   emits 0.98 for every landmark, so distance decides — but this is *not* a
   true distance-first ordering.
5. **Superlative attributes are not modelled.** "the **biggest** tree" is a
   strict maximum, not "≥ median"; `biggest/largest/smallest/tallest` are
   deliberately **absent** from `ATTRIBUTE_TABLE`, so they stay inside the noun
   query (the fail-safe path) rather than being answered with the wrong
   semantics.
6. **Only one superlative value (`nearest`) and one pace value (`fast`).**
   "farthest", "slowly", and comparatives are not parsed.
7. **The pre-existing lamppost `verification_failed` and tree `unreachable`
   product-path failures are untouched** and are not claimed as fixed.

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/navigation/goals.py` | SUP-1: four vocabulary tables, three `SemanticGoal` fields, `pace_from_directive`, `_split_noun_phrase`, `_strip_leading_prefixes`, `find`/`locate`/`look for` destination pattern |
| `src/parcel_robot/navigation/attributes.py` | **new** — SUP-3 pure matcher |
| `src/parcel_robot/navigation/pipeline.py` | SUP-2 `interchangeable`, SUP-3 filter + metadata, `_refusal_label` at 6 refusal sites, directive modifiers in `parse()` metadata, soft `attributes` import for frozen BARN bundles |
| `src/parcel_robot/navigation/search.py` | SUP-3 on the multi-view confirmation path (3 lines + import) |
| `src/parcel_robot/navigation/grounder.py` | whole-word POI scoring (the `near` ⊂ `nearest` defect) |
| `src/parcel_robot/runtime.py` | SUP-4 `_apply_directive_pace` / `_restore_directive_pace` + 4 call sites |
| `tests/test_superlative_directives.py` | **new** — 49 tests |
| `scrum/20260807/task_1/SUPERLATIVE_STATUS.md` | **new** — this record |

Wave-0-owned files (`evals/**`, `instructnav/scoring.py`,
`tests/test_voice_nav_e2e.py`, `evals/nav_instruct/generator.py`): **untouched**.

## Carried forward (for backlog/NEXT)

- **N-SUP-1:** distance-first ordering for explicit superlatives, so "nearest"
  outranks confidence rather than only disabling the ambiguity veto. Natural
  home: the stratum-3 RelationSpec registry.
- **N-SUP-2:** carry object size (and, later, sidecar attributes) on
  `RememberedEntity` so an attribute-qualified goal can be satisfied from
  memory.
- **N-SUP-3:** superlative attributes (`biggest`, `smallest`) as a distinct
  polarity — strict argmax within a class, not a median split.
- **N-SUP-4:** tree/planter co-location in `city_block.xml` defeats
  approach-pose search for every tree directive, superlative or not.
