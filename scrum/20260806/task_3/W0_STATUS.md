# Wave 0 — truth-keeping round · status

**Date:** 2026-08-06 · **Plan:** [docs/STRATA_GENERALIZATION_PLAN.md](../../../docs/STRATA_GENERALIZATION_PLAN.md)
(Wave 0 + eval instruments 5 and 6) · **Constraint honored: ZERO product-behavior
change.** No navigation, control, grounding, or agent code was touched. This
round added scoring options, logging, derived artifacts, and tests only.

## Outcome per card

| card | outcome |
|---|---|
| W0-A — U31 closure by derived re-scoring | **done.** Predicted 4/25 bound confirmed on the candidate; 3/25 on the baseline. Derived rows appended, frozen rows byte-identical. |
| W0-B — `false_arrival` as a scorer class | **done.** D-15 lands in `FALSE_ARRIVAL` in *both* runs. Success set proven identical before/after. |
| W0-C — differential authority verdict logging | **done** in all three harnesses. |
| W0-D — derived eval tables + regeneration diff | **partly deferred, deliberately.** Artifact + both tests landed. The generator does **not** adopt the derived values: the equality precondition **failed** — the hand transcription is wrong in 7 fields across 5 entities. Details below. |

---

## W0-A — derived re-scoring (U31)

**Entry point:** `evals/nav_instruct/rescore.py`
(`.parcel/bin/python -m evals.nav_instruct.rescore --all --append-ledger`).
Both persisted reports carry full per-episode traces at the same
`runner_version` (`nav-instruct-v1.1-k0-arrival`) and the same
`episode_digest` (`cf4d5384…`); the re-scoring refuses to run if either drifts.

**The derived rule — `hold-or-trace-end-v1`, stated exactly.** An episode
counts as arrived when **either**:

- **(a)** the frozen rule holds — some contiguous run of trace samples all
  inside the `GoalRegion` *and* stopped spans ≥ `arrival_hold_s`; **or**
- **(b)** the trace **ends** inside-and-stopped — the final sample is inside the
  `GoalRegion`, is stopped by the scorer's own `sample_stopped` convention, and
  the trace was **not** cut off by the step limit (no `step_limit` flag, no
  `navigation_step_limit` note on the final sample).

Branch (b) is the correction: the runner ends the episode one 0.1 s tick after
the mission's `arrived_verified`, so the 1.0 s hold is **unobservable, not
unmet**. The step-limit exclusion is what keeps (b) honest — a trace that ran
out of budget did not choose to stop and earns nothing. `arrival_hold_s` per
family is replayed exactly as the runner used it: 1.0 s for the navigation
families, 0.0 s for `follow_owner`/`circle_owner`.

**What (b) assumes, plainly:** that a robot stopped inside the goal when the
recording ended would have stayed there for the remaining 0.9 s. That is an
assumption, not a measurement — which is why these are derived diagnostic rows
and can never replace a frozen baseline.

### SR table — same episode set, same traces, two rules

| run | rows | frozen rule (as measured) | derived rule | Δ | SPL frozen → derived |
|---|---|---|---|---|---|
| baseline `nav-instruct-v1-baseline-20260805T070524Z` | 25 | **0.04 (1/25)** | **0.12 (3/25)** | +0.08 | 0.000165 → 0.0802 |
| candidate `nav-instruct-v1-candidate-20260806T070335Z` | 25 | **0.04 (1/25)** | **0.16 (4/25)** | +0.12 | 0.000165 → 0.1202 |

**The 4/25 bound is confirmed.** The candidate's derived SR is exactly the
corrected upper bound from arbitration OB-6; the retracted 8/25 figure is
unreachable under any hold rule.

Flipped episodes (all: `mission_status="arrived"`, `reason="arrived_verified"`,
final sample inside + stopped, `derived_branch="trace_end_hold"`):

| run | flips |
|---|---|
| baseline | `nav-region_goal-A-00-1c735162`, `nav-object_goal-A-00-4caa923b` |
| candidate | `nav-region_goal-A-00-1c735162`, `nav-region_goal-B-05-586317e4`, `nav-object_goal-A-00-4caa923b` |

Every flip's **observed** trailing inside-and-stopped hold is **0.1 s** — one
control tick against the 1.0 s the frozen rule demands. That 0.9 s gap is U31,
measured rather than argued.

**Not hold-fixable, confirmed:** the four `circle_owner … spatial_step_limit`
rows (`A-00`, `B-05`, `D-15`, `E-20`). All four are geometrically inside the
goal disc (`dtg = 0.0`) with `trailing_hold_s = 0.0` — still moving when the
budget ended. They stay `termination`, and instrument 5 separately logs them as
`authority_disagreement`.

**Ledger.** Two `kind="derived_rescoring"` rows appended with `parent_run_id`,
`rescore_rule`, `scorer_version`, both failure histograms, the authority
histogram, and the flip/false-arrival episode lists. `frozen_baseline: false`
on both.

- ledger sha256 **before**: `e7cb5139b8194fe6882ea626fb9ba5458992d10a0c648686ea6762eaf86fe9e5` (7 lines)
- ledger sha256 **after**: `dab60242975a86f26e0518571158c3f3bd8191f16623f8f51cc8b80c7f1f2fe0` (9 lines)
- sha256 of the **first 7 lines after the append**: `e7cb5139…fe9e5` — **identical**. No frozen row was rewritten. The prefix hash is pinned in `tests/test_nav_instruct_rescoring.py`.

**Not claimed:** the runner is unchanged, so the next measured run reproduces
the same understatement. Closing U31 for real is option 2 (keep stepping for
`arrival_hold_s` after a terminal stop, re-freeze both rows together) — a
behavior change, out of scope here.

---

## W0-B — `false_arrival` as a first-class scorer category (U32)

`FailureClass.FALSE_ARRIVAL` added to `instructnav/scoring.py`
(`SCORING_VERSION = instructnav-scoring-v1.2-differential-authority`).

- **Trigger:** the mission claims arrival (`system_arrival`, from an explicit
  argument or an explicit `system_arrival`/`arrival_claimed` trace flag) and the
  final pose is outside the `GoalRegion` by more than the epsilon.
- **Epsilon:** `ARRIVAL_BOUNDARY_EPSILON_M = 0.05 m`, a *symmetric* boundary
  tolerance zone (see W0-C). ~20× narrower than the narrowest arrival band in
  the system (`NEXT_TO_BAND_M` is 1.1 m wide), so it cannot swallow a real
  disagreement.
- **Precedence:** refusal → grounding → search → control → **false_arrival** →
  termination → planning. Safety still outranks attribution (a collision stays
  `control_error`); a false arrival can never fall through to `planning_error`
  or `termination` again. Attribution layer: **L6** — terminal verification is
  the disagreeing party; no new layer was invented.
- **Never sniffed from prose.** Only explicit booleans count as a claim; free
  text in `note`/`reason` is deliberately ignored, so no historical trace can be
  reclassified by accident.

**Measured on the persisted traces:** `nav-object_goal-D-15-109547e2` is
`FALSE_ARRIVAL` in **both** runs — candidate `dtg = 3.1995 m`, baseline
`dtg = 3.206 m`. It is not a candidate-only regression; the frozen baseline
claimed it too and it was bucketed as `planning_error` there as well. Confirmed
live: a fresh 3-episode runner smoke reproduces `dtg 3.1995` and
`failure=false_arrival` exactly.

**Safety property, proven over the persisted traces** (not just synthetic ones):
the set of episodes scored `success=True` under the frozen rule is byte-identical
to what the reports recorded, for both runs, and the **only** row whose failure
label moved is D-15. A success can never become a false arrival and vice versa —
also pinned by a parametric property test over `{claim True/False/None} ×
{hold 0.0/1.0} × 5 trace shapes`.

**Still open:** classification is a detector, not a fix. Nobody has yet replayed
D-15 tick by tick to name *which* party is wrong. Owner: Lane D. The plan's
gate is zero `false_arrival` rows at T0/T1; it is currently 1.

---

## W0-C — differential authority verdict logging (instrument 5)

New in `instructnav/scoring.py`:
`AuthorityCategory` (`agreement` / `tolerated_boundary` /
`authority_disagreement` / `false_arrival` / `unknown`),
`ArrivalAuthorityVerdict`, `differential_arrival_verdict(...)`,
`system_arrival_claim(status, reason)`, and
`GoalRegion.signed_distance_to_boundary(...)` (negative inside — `distance_to`
saturates at 0 inside and cannot express "inside, 1 cm from the edge").

The implication under test is **one-way** — `scorer_arrival ⇒ system_arrival` —
because the scorer is a derived geometric view, not a peer:

| verdicts | category |
|---|---|
| agree (both, or neither) | `agreement` |
| differ, `abs(signed boundary margin) ≤ 0.05 m` | `tolerated_boundary` |
| scorer only, beyond epsilon | `authority_disagreement` |
| system only, beyond epsilon | `false_arrival` |
| no system verdict available | `unknown` (never a fabricated agreement) |

`scorer_arrival` is the K0 predicate on the **final pose with no settle hold** —
deliberately *not* `EpisodeScore.success`. Conflating the two is what made U31
and U32 look like one defect.

One definition of "the system claimed arrival", shared by all three harnesses:
status in `{arrived, succeeded}` or reason in `{arrived, arrived_verified,
at_follow_distance, goal_reached}`. `completed`/`tracking_owner` is
**deliberately not** a claim — a follow that is still tracking has asserted
nothing about arrival.

**Wired into:**

- `evals/nav_instruct/runner.py` — three fields on every `EpisodeRunResult` and
  in `as_dict()`; `system_arrival` also written onto the final trace sample;
  `authority_histogram` + `arrival_epsilon_m` in `aggregate_results` and in the
  ledger row (which also gained `kind: "measured_run"`).
- `evals/walk_with_me/runner.py` — same three fields on `ScriptRunResult`, an
  `authority_histogram` in the aggregate and the ledger row. Scripts with no
  goal region (resume/barge-in themes) or no harness status record `unknown`.
- `tests/test_voice_nav_e2e.py` — `_run_command_to_terminal` records
  `system_arrival` on **every** run; `_score_arrival_authority` fills in the
  scorer verdict (inline for the two static-city cases, immediately post-run for
  the owner-anchored and sit cases whose goal region depends on the final owner
  pose). `_assert_authorities_agree` hard-asserts **only** in the two cases that
  already assert both success and the K0 predicate — where it is implied by
  assertions already present, so **no case's pass/xfail status moved**. The
  fountain honesty case gained `assert result["system_arrival"] is False`, which
  its existing `all(state == "failed")` assertion already implies.

The e2e suite is `-m slow` and was not run (per instruction). Its two new pure
helpers are covered by non-slow tests that import the module and drive them with
synthetic evidence dicts, so the code path is verified without a sim.

**First finding from the instrument:** on both runs, 20/25 `agreement`,
4 `authority_disagreement` (the `circle_owner` step-limit rows: geometrically
in the goal, no arrival claim), 1 `false_arrival` (D-15), 0
`tolerated_boundary`, 0 `unknown`.

---

## W0-D — derived eval tables + regeneration diff (instrument 6)

`evals/nav_instruct/scene_truth.py` derives the landmark/goal tables from
`extract_city_semantics(model)` over `src/parcel_robot/scenes/city_block.xml`
and emits the checked-in artifact `evals/nav_instruct/scene_truth.json`
(scene path + sha256 + `derived` table + `transcribed` table + `transcription_deltas`).
`mujoco` is imported lazily so the pure eval path stays sim-free.

### ⚠ The equality test FAILED — the hand transcription is wrong

The card's step 1 was "prove the derived tables reproduce the hand-transcribed
values exactly". **They do not.** Seven fields across five entities disagree:

| entity | field | transcribed (generator) | derived (scene) |
|---|---|---|---|
| `sidewalk` | polygon | y ∈ [2.4, 3.6] | **y ∈ [2.2, 4.2]** |
| `sidewalk_south` | polygon | y ∈ [−3.6, −2.4] | **y ∈ [−3.75, −2.25]** |
| `crosswalk` | polygon | x ∈ [2.3, 3.9] | **x ∈ [2.35, 3.85]** |
| `bench_1` | position | (−2.5, 3.0) | **(−2.5, 3.045)** |
| `bench_1` | radius_m | 0.7 | **0.733757** |
| `tree_1` | radius_m | 0.45 | **0.58** |
| `bldg_1` | radius_m | 1.8 | **2.343075** |

Exactly correct: `lamp_post_1`, `lamp_post_2`, `planter_1` (position **and**
radius, byte-equal) — which is the equality half of the proof that the
derivation path is real.

**Consequences, stated honestly.** The sidewalk region the eval scores against
is **0.8 m narrower** than the sidewalk in the scene (1.2 m vs 2.0 m tall), so
`region_goal` episodes are scored against a region the robot can be standing on
and still be "outside". `tree_1`'s radius is under-stated by 0.13 m and
`bldg_1`'s by 0.54 m, which shifts every derived stand-off band. None of this is
new today — it has been true for every NAV_INSTRUCT row ever measured — but it
was invisible until now.

**Neither value was silently adopted.** Adopting the derived values moves the
affected episode goals, changes the frozen minival digest, and invalidates the
paired baseline/candidate comparison — i.e. it needs a re-freeze, which is a
behavior change and out of scope for this round. So:

- the generator now reads its table **from the artifact** (`transcribed`
  section) instead of a literal in `generator.py` — one checked-in place, and
  the frozen minival digest `cf4d5384…` is **unchanged**, verified;
- the delta is **pinned**, field by field, in
  `tests/test_nav_instruct_scene_truth.py::test_transcription_delta_is_exactly_the_pinned_set`.
  A new row (fresh drift) is red; a missing row (someone adopting a derived
  value without a re-freeze) is also red.

**Deferred with reason:** flipping the generator to the `derived` table is a
re-freeze card, not a Wave 0 card. It should be sequenced with U31 option 2 so
the baseline is re-frozen once, not twice.

### Tests landed

1. `test_checked_in_artifact_equals_a_fresh_derivation` — PR-tier regeneration
   diff. A hand-edited artifact or an un-regenerated scene edit is a red build.
   This is the "any scene edit currently corrupts goals silently" fix.
2. `test_derivation_reproduces_the_landmarks_the_transcription_got_right` —
   the equality half (`lamp_post_1/2`, `planter_1`).
3. `test_transcription_delta_is_exactly_the_pinned_set` — the honest
   substitute for the equality test that could not pass.
4. `test_artifact_pins_the_scene_it_was_derived_from` (sha256),
   `test_artifact_is_valid_json_and_sorted`,
   `test_every_generator_landmark_exists_in_the_scene`,
   `test_generator_reads_its_landmarks_from_the_artifact` (incl. tuple shape,
   which the digest depends on),
   `test_frozen_minival_episode_digest_is_unchanged`.

---

## Verification

| check | result |
|---|---|
| `pytest tests/ -q` | **2129 passed, 7 skipped, 4 xfailed, 0 failed** (655 s) |
| entry state, same command | 2021 passed, 7 skipped, 4 xfailed, 1 failed (`test_walk_with_me_k8::test_cli_smoke`, an artefact of editing during the run) |
| new tests | +59 (`test_arrival_authority_differential` 28, `test_nav_instruct_rescoring` 23, `test_nav_instruct_scene_truth` 8) |
| `tests/test_voice_nav_e2e.py` alone | **6 passed, 4 xfailed** — identical to entry state; no case's pass/xfail status moved |
| `ruff check` on every touched file | clean (pre-existing errors elsewhere in the repo untouched) |
| frozen minival episode digest | `cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf` — **unchanged** |
| frozen ledger rows byte-identical | **yes** — prefix sha256 identical before/after append, pinned in a test |
| derived ledger rows present | **yes** — 2 rows, `kind="derived_rescoring"`, with `parent_run_id` |
| `-m slow` | **not run** as a separate invocation. Note: `tests/conftest.py` only *registers* the `slow` marker — nothing deselects it — so `pytest tests/ -q` already includes the 10 live-sim `voice_nav_e2e` cases. The 4 xfails in the default suite are exactly those. |

**Two transient full-suite failures were observed and chased down; both passed
in isolation and neither is attributable to this round.**

- `test_voice_nav_e2e::test_go_to_the_sidewalk_grounds_plans_and_arrives` —
  failed once under full-suite load, passed standalone in 26 s and again in a
  full-file run. Live-sim timing flake.
- `test_barn_v8_policy_bundle::test_real_historical_bundle_derives_only_the_reviewed_v8_delta`
  — failed once, passes standalone. It hashes the working tree under
  `evals/external/` and asserts exact file counts, so it is sensitive to other
  tests writing result artefacts during the same run. Nothing in this round
  touches `evals/external/`.

Related observation, not caused here: the collected test count grows between
consecutive full-suite runs (2033 → 2092 → 2140) because several BARN/external
suites parametrise over result directories that earlier runs create. Worth a
backlog note for whoever owns eval-integrity CI (instrument 6's own hygiene).

## Files touched

**Source (scoring only — no navigation/control/grounding/agent code):**
`src/parcel_robot/instructnav/scoring.py`,
`src/parcel_robot/instructnav/__init__.py`

**Evals:** `evals/nav_instruct/rescore.py` (new),
`evals/nav_instruct/scene_truth.py` (new),
`evals/nav_instruct/scene_truth.json` (new, generated),
`evals/nav_instruct/generator.py`, `evals/nav_instruct/runner.py`,
`evals/nav_instruct/run_nav_instruct_v1.py`, `evals/nav_instruct/README.md`,
`evals/nav_instruct/results/README.md`,
`evals/nav_instruct/results/ledger.jsonl` (2 rows appended),
`evals/walk_with_me/runner.py`, `evals/walk_with_me/run_walk_with_me_v1.py`

**Tests:** `tests/test_arrival_authority_differential.py` (new, 28),
`tests/test_nav_instruct_rescoring.py` (new, 23),
`tests/test_nav_instruct_scene_truth.py` (new, 8),
`tests/test_voice_nav_e2e.py` (evidence recording + one gate; no case moved)

**Records:** `backlog/UNVERIFIED.md` (U31, U32), this file.

## Non-claims

- **Nothing was fixed.** No navigation, control, grounding, or agent behavior
  changed. U31's runner defect and U32's verification defect are both still
  live; what changed is that they are now measured and named.
- **The derived SR numbers are not a new baseline.** 3/25 and 4/25 are what the
  same traces score under a rule that *assumes* an unobserved hold. They are
  diagnostics with a `parent_run_id`, not a capability claim, and they are not
  comparable to any future run scored under the frozen rule.
- **The 4/25 ceiling is a ceiling, not a target.** 21/25 candidate episodes fail
  for reasons no hold rule touches.
- **The scene-truth deltas are unexplained, not resolved.** It is not yet known
  whether the transcription or the scene is what someone intended; only that
  they differ, by how much, and in which fields.
- **`tolerated_boundary` has never fired.** The 0.05 m epsilon is a documented
  choice justified by tick × cruise speed, not a value calibrated against a
  measured disagreement distribution — no episode has yet landed in the zone.
- **The voice_nav_e2e wiring was not executed** (`-m slow` not run). Its pure
  helpers are unit-tested; the live sim path is unverified this round.
- **`walk_with_me` verdict logging is untested against a real headless run** —
  the stub path exercises it, the headless path is code-only here.
