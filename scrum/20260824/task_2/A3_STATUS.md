# A3 DISCONTINUITY-LATCH — executor register (Opus) · 2026-08-24

Card: `IMPLEMENTATION_PLAN.md` row A3 + `CLAUDE_RESPONSE.md` addenda A4/A10.
Grounding: `research/20260824/nav-core/{RESULTS,VERDICT,REFUTER_4B_REMEASURE}.md`
and `relocalize.py`'s `GlobalMatcher`. Guard label `a3-latch`, never `-n auto`,
never `ci_gate --tier`, git READ-ONLY, nothing committed. Owner's stack
(`:8765`, `/tmp/parcel_sim.sock`, `parcel_memory.sqlite3`) untouched. Zero
`noqa`, zero new ruff fingerprints, zero new `# ---- CARD` markers. Safety
floors, `apply_reactive_safety`, `apply_collision_brake` and `finalize_command`
untouched. **`runtime.py` untouched — no hunk to report (see UNDONE 1).**

## What landed

| # | thing | where |
|---|---|---|
| 1 | the discontinuity latch, six A10 signals, journal | `src/parcel_robot/localization/discontinuity.py` (new, 589 lines) |
| 2 | the whole-map second-best margin (fix 4) | `localization/global_match.py` (new, 324) + `contract.RelocalizationMatch` + `gicp_provider._relocalize` |
| 3 | the one-shot operator pose-reset transaction | `discontinuity.OperatorPoseReset` + `ArmingLatch.try_rearm_by_operator` |
| 4 | the `localization_jump_m` journal writer | `localization/jump_journal.py` (new, 223) |
| 5 | calibration floor on arrival confidence | `navigation/pipeline.py` `_inside_polygon_verified` |
| — | the product seam that feeds 1 and 4 | `localization/pose_adapter.LocalizedPoseProvider` (opt-in kwargs) |
| — | regression | `tests/test_a3_discontinuity_latch.py` (new, 32 cells) |

**Placement, justified.** The latch is in `localization/`, not `core/`. Every
A10 source is a statement about the localization estimate's continuity (the
estimator's boot epoch, the machine holding the map power-cycling, a carried
signature that voids the odometry prior, whole-map ambiguity, the `T_map_odom`
jump itself). `core/input_health.py` is a *pure freshness/provenance join over
three declared inputs*: a fourth `RequiredInput` there would move
`DEFAULT_REQUIRED_INPUTS` for every consumer and every test that pins its fault
set, and would still have nowhere to carry a margin or a jump magnitude. The
two COMPOSE instead — `ArmingLatch.action` returns `core.input_health
.HealthAction`, so a holder of both takes `max(verdict.action, latch.action)`
and gets the stricter (pinned by `test_the_latch_speaks_the_runtime_health_vocabulary`).

## 1 · The six A10 signals, with their journalled trigger values

Each row below is a real journal record from the suite. `value` is the
trigger's own measurement, never a bool.

| A10 signal | trigger key | journalled value | cell |
|---|---|---|---|
| boot-epoch change | `boot_epoch_change` | `8.0` (detail `was 7`) | `..._journals_the_new_epoch` |
| power-cycle flag | `power_cycle` | `1.0` | `..._power_cycle_flag_latches_motion` |
| IMU / foot-contact carried | `carried_signature` | `0.0` feet (detail `vertical_accel_mps2=-9.400 source=imu_test`) | `..._journals_the_foot_count` |
| global-match ambiguity | `global_match_ambiguity` | `1.170e-14` (threshold 0.25, 162 hypotheses) | the aliased kidnap episode |
| localization jump | `localization_jump_m` | **`2.6375` m** (bound 0.350 m) | the normal-layout kidnap onset |
| operator pickup | `operator_pickup` | `1.0` | `..._operator_pickup_latches_motion` |

The **carried seam is named, not faked**: `CarriedSignature(feet_in_contact,
vertical_accel_mps2, stamp_ns, source, measured)` is the contract a real IMU /
foot-contact estimator fills, and `StubCarriedSignatureSource` is the honest
stand-in for a host with no robot hardware — it reports standing with
`measured=False`, and a `measured=False` signature can never latch, so the stub
cannot mint a refusal it did not observe. That is pinned in both directions.

`test_every_a10_signal_is_implemented_and_none_is_missing` asserts the set of
observed triggers equals `{member.value for member in DiscontinuityTrigger}` —
six, and exactly six.

## 2 · The whole-map second-best margin (defect 4)

**`WholeMapMatcher`** productizes the harness `GlobalMatcher`'s shape: 0.40 m
coarse grid, two-finalist refinement on a 0.10 m sub-grid, exact yaw sweep by
circular shift, rivals separated by ≥ 1.00 m, re-ordered AFTER refinement. The
hypothesis source is a seam (`RangeTemplateSource`: `free(x,y)` +
`template(x,y)` at heading zero), so the algorithm is in the product and the
world stays outside it.

| room | margin | hypotheses | verdict at threshold 0.25 |
|---|---|---|---|
| normal (asymmetric) | **61.07** | 153 | discriminative — re-arms |
| C2-aliased | **0.000** | 162 | refuses (bar: ≤ 0.005) |

NAV-CORE's harness measured 2.2–30.7 vs 0.002–0.03 on its 8 m MuJoCo room; the
separation reproduces, larger, because this room's alias is exact to float
noise (`test_the_aliased_room_is_aliased_to_float_noise`: worst per-ray
disagreement **0.0 m**).

**`ScanMatchLocalizer._relocalize` now keeps a runner-up.** The update carries
`RelocalizationMatch(pose, residual_m, runner_up, runner_up_residual_m,
separation_m, hypotheses, source)` with `.margin` and `.is_discriminative()`.
Selection is byte-identical to the pre-A3 provider (still `inliers / (1 + rms)`,
same gates, same stride); only the reporting is new. The refusal is flag-gated:
`ScanMatchConfig.require_relocalization_margin` defaults **False**.

What that flag measured on the normal-layout kidnap — the reason it exists:

| arm | event | jump | health | margin |
|---|---|---|---|---|
| shipped (`False`) | `relocalized` | 2.6375 m | DEGRADED → HEALTHY | **-0.1365** |
| gated (`True`) | `relocalize_ambiguous` ×7 | 0.0 | **LOST** | -0.1365 |

The winner's residual (0.2932) was **worse than its runner-up's** (0.2532) at
3.705 m separation: the shipped provider commits to a place its own map cannot
distinguish from another one and then publishes HEALTHY on top of it. With the
pre-registered margin required it stays LOST and says why. Left OFF by default
because turning it on changes localizer output, and the milestone's flag rule
says a behaviour change ships gated.

**Honest limit, stated in the docstring and not papered over:** the localizer's
hypothesis set is the KEYFRAME CHAIN sampled at `relocalize_candidates` (22 on
this run), so "whole map" there means "everywhere this map has been".
A venue-wide grid is what `WholeMapMatcher` is for; the two answer the same
question at different granularities.

## 3 · The kidnap, through the product path

Aliased room, `ScanMatchLocalizer` under `LocalizedPoseProvider`, the A3 latch,
then the untouched `apply_reactive_safety`, then a kinematic body. The ODOM feed
is re-based across the jump (H7's mechanism), so proprioception cannot see it.

| arm | total path | post-kidnap path | moved while latched | HEALTHY ticks | journal |
|---|---|---|---|---|---|
| latch DISABLED (control) | 3.965 m | **2.765 m** | — | 109 / 110 | empty |
| latch ENABLED | 0.600 m | **0.000 m** | **0.000 m** | — | `latched global_match_ambiguity 1.17e-14` |

Two counters, both zero and both asserted: motion after the FIRST latch row, and
motion on any tick where `provider.motion_latched` was true. The second is the
invariant that has to hold in the operator episode as well, where the latch does
clear for a while — and it does.

That reproduces NAV-CORE R4b on this tree (there: shipped arms 0.84 / 0.27 /
0.71 m at 824–840 of 840 HEALTHY ticks; gated 0.00 / 0.00 / 0.00) and the
attribution is non-circular: same room, same localizer, same gate, latch off.

## 4 · The kidnap-ONSET row (VERDICT amendment note 2 — this card's own criterion)

The row NAV-CORE never exercised: a NORMAL layout, the body armed and moving,
caught by the JUMP bound rather than by ambient ambiguity.

```
nominal travel (170 ticks, smooth 1.25-lap loop):
    localization_jump_m  max 0.0905 m   median 0.0240 m   n=180   latched: NO
kidnap onset (moved to unvisited ground 0.5 m+ off the mapped track):
    reject → reject → LOST → relocalized, jump = 2.6375 m
    journal: latched      / localization_jump_m       / 2.6375   ("bound 0.350 m health degraded")
             retriggered  / global_match_ambiguity    / -0.1365  (the localizer's OWN margin,
                                                                  same tick, same event)
```

Two independent A10 rows caught the same discontinuity and the journal keeps
both — the jump tripped the latch, and the keyframe margin said on the same tick
that the place it relocalized into was ambiguous. (The journal deduplicates a
STANDING cause and records a DIFFERENT one as `retriggered`, so an ambiguity
check re-asked every few ticks writes one row, not one per ask.)

`journal.max_m == the latch's trigger value` and
`journal.over(0.35)[0].jump_m == 2.6375` are both asserted, so the writer and
the latch agree on the number. The control (same room, same track, no kidnap)
never latches and never exceeds the bound — `test_the_jump_bound_does_not_fire_on_the_same_travel_without_a_kidnap`.

Order-of-magnitude sanity against the two prior measurements: NAV-CORE's
room-scale nominal max was 0.029 m (median 0.009 m) and the H7 delegation bench
saw 7.15 m on a kidnap / 10.47 m on the relocalization after it. This fixture
sits between them on both ends, which is what a smaller room and a coarser ray
engine should give.

## 5 · `localization_jump_m` journal writer

`LocalizationJumpJournal` observes every `LocalizationUpdate`, keeps exact
`count`/`max_m` and a windowed median, and emits the entry
`bridge/timing.load_stopping_envelope_record` demands — `{"value": …,
"provenance": …}` — plus `merge_into_envelope_record` (pure) and
`write_envelope_record`. Proven end to end through the **shipped** loader:

```
measured 0.0905 m -> record -> load_stopping_envelope_record
  record.missing() == ()            # the term every host record has carried as UNMEASURED
  derive_envelope(record, "leashed").contributions["localization_jump_m"] == 0.0905
  the other four terms keep the value AND provenance the record already had
```

A journal that saw no updates publishes the **sentinel**, not a confident 0.0 —
"zero jumps observed" is a different claim from "the jump is zero" — and that
record still reads `missing() == ("localization_jump_m",)` and derives
`UNMEASURED`. `bridge/timing.py` was NOT edited: the term name is one string and
the entry is one mapping, and importing that module (yaml, socket, two closed
cards' marked regions) into a localization leaf would buy nothing the
round-trip test does not already prove.

## 6 · Operator transaction semantics (A4 path b, as re-measured)

`OperatorPoseReset` is a **statement object**: the pose is captured at
construction, the latch settles it exactly once (`COMMITTED` or `REFUSED`), and
a settled statement can never re-arm again. That is the 79-silent-re-arms
failure mode made structurally impossible rather than rate-limited.

| case | attempts | re-arms | journal | end state |
|---|---|---|---|---|
| truthful pose, statement fed on **every tick** from t=5.1 s | **59** | **1** | `latched → rearmed(0.001297) → latched` | latched |
| wrong pose (1.66 m RMS vs 0.35 bound), fed 20× | 20 | **0** | one `operator_refused` row | latched |
| committed statement re-offered after a NEW latch | 1 | 0 | — | latched |

Exactly the re-measured shape: one journalled re-arm, bounded motion after it
(0.06 m here — one ambiguity period at the controller's speed; 0.14–0.32 m in
the re-measure), the standing ambiguity re-latches, the episode ends latched.
A refused statement is **spent**, so a wrong operator cannot grind at it, and
`try_rearm_by_operator` raises `TypeError` on a bare pose tuple — there is no
API through which a standing pose feed can even be offered.

`test_health_and_covariance_re_arm_nothing` drives 50 HEALTHY zero-jump updates
into a latched latch and asserts it stays latched: A4's last sentence, pinned.

## 7 · Fix 5 — the calibration floor (fix VERIFIED as still needed)

The card asked me to verify whether any path still trusts raw covariance after
A2. **One does.** A2's off-oracle branch correctly refuses on covariance
("no covariance and no probability threshold may verify anything here"), but
`pipeline._inside_polygon_verified` still returns `p_inside_polygon(...) >=
inside_probability_threshold` as a POSITIVE verdict, and the committed-region
branch of `_semantic_arrival_verified` (`pipeline.py:5850-5857`) reaches it with
**no detector confirmation at all** — the re-sighting is deliberately skipped
there because a region's centroid is routinely outside the frustum.

Swept for siblings, and there are none: `arrival_region.contains(...,
anchor_covariance=..., probability_threshold=...)` at `pipeline.py:5866` and
`:6270` is REFUSAL-ONLY (`if not region.contains(...): return False`) and was
left alone; `_arrival_confidence_floor` feeds the DETECTOR evidence gate
(`evidence_arrival_verified`), not a pose covariance; `instructnav.scoring
.p_inside_goal_region` only writes metadata. `_inside_polygon_verified` was the
one site that turned a covariance into a positive verdict.

The whole `pipeline.py` change is three hunks, for the verifier: the constant
at `:317-323`, the `detector_confirmed=False` at the committed-region call
(`:5859-5871`), and the parameter + refusal branch in `_inside_polygon_verified`
(`:6144-6194`). Nothing else in that file moved.

Fix: `_inside_polygon_verified` gains `detector_confirmed: bool = True`, that
one caller passes `False`, and an inexact pose with no detector now refuses with
the typed reason `ARRIVAL_UNCALIBRATED_CONFIDENCE_REASON =
"arrival_confidence_uncalibrated"` (the probability is still written to
`mission.metadata` — a refusal has to be auditable). **Exact-covariance poses
take the identical branch they always did**, so every `TruthPoseProvider` run is
byte-equal: the floor can only ever refuse. Landed ON rather than flag-gated
because a default-off safety tightening ships the defect; pinned by three cells
including the T0 equality one.

**Measured blast radius on this tree: zero.** The probe above counted 110
`_inside_polygon_verified` calls through the live demo-city runtime and every
one carried an exact pose, so the new branch never executed. That is the honest
reading of this fix today: it costs nothing NOW because nothing in the product
ships a covariance-bearing pose, and it will start refusing the moment one does
— which is exactly the milestone the latch above is built for. A verifier
wanting to see it bite should install `LocalizedPoseProvider` (or any
`pose.yaml` drift profile) behind the pipeline and re-run a region goal.

## Suites — all through `~/.cache/parcel-guard/pytest_guard.sh --label a3-latch`

| suite | result |
|---|---|
| `tests/test_a3_discontinuity_latch.py` (new) | **32 passed**, 3.6 s |
| `test_dec0_debt_ratchet.py` + `test_decig2_import_ratchet.py` | **23 passed** |
| `test_h7_localization_contract.py`, `test_pose_seam.py`, `test_pose_consumers.py`, `test_navcore_probe.py`, `test_a2_navglue.py` | **85 passed** |
| the three above in ONE final run (A3 + both ratchets + all five pose/localization suites) | **140 passed**, 36.7 s |
| arrival/region sweep `-k "arrival or inside or polygon or chance or region"` | **314 passed**, 4 skipped |
| `test_navigation`, `test_portal_world`, `test_semantic_navigation_regressions`, `test_grid_navigator`, `test_grid_planner`, `test_door1_doorway`, `test_value_directed_search`, `test_ve_detection_lock_on`, `test_superlative_directives`, `test_arrival_etiquette_pipeline` | **251 passed** |
| `test_voice_nav_e2e.py` (`PARCEL_MEMORY_PATH=:memory:`) | 14 passed, 1 xfailed, **3 failed** — all three attributed below, **none of them A3** |
| ruff | `All checks passed` on every touched file; **0 new fingerprints** (the one delta vs the pinned baseline, `research/20260823/search-before-refuse/runtime_probe.py::F401`, is the pre-existing row A2's register already named) |

### The three `test_voice_nav_e2e` reds, attributed by measurement not by guess

| test | verdict |
|---|---|
| `test_go_to_the_lamppost_grounds_plans_and_arrives` | **PRE-EXISTING** — A2's register already recorded it failing with all four A2 fixes disabled. |
| `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` | **A2's**, recorded in A2_STATUS as the measured price of fix 3 (the demo city admits 0.885 m of planner inflation, not 1.022 m). |
| `test_go_to_the_sidewalk_grounds_plans_and_arrives` | **FLAKY FIXTURE, not fix 5** — proven, see below. |

The sidewalk row looked like mine at first: with the `ignore_detector` mutant
the `-k "sidewalk or lamppost"` subset went 3 failed -> 2 failed. That was a
coincidence, and the code path settles it. Run alone, the test fails at
`_LiveRuntime.heading()` with `AttributeError: 'NoneType' object has no
attribute 'robot'` — `runtime._observation` is None, beside
`expression overlay publish failing: [Errno 32] Broken pipe`, in 23.7 s rather
than the ~2 min a healthy run takes. That is the live-runtime fixture, not an
arrival verdict.

Then the decisive measurement, a probe that wraps the real
`_inside_polygon_verified` and records every call (fix 5 fully live):

```
1 passed in 23.62 s
110 calls to _inside_polygon_verified
    is_exact=True,  detector_confirmed=True,  -> False   x 106
    is_exact=True,  detector_confirmed=True,  -> True    x 1
    is_exact=True,  detector_confirmed=False, -> True    x 3
    calls with an INEXACT pose and no detector: 0
```

Every call carried an EXACT pose, because `configs/navigation/pose.yaml` ships
`provider: truth`. The branch fix 5 added is therefore **unreachable in this
e2e**, including on the three calls that pass `detector_confirmed=False` — they
short-circuit into the unchanged boolean geometry. The test passes with fix 5
live; the earlier failures were the fixture.

**No ported pin, no re-frozen number.** Nothing in the tree asserted the
behaviour A3 changed: `test_h7_localization_contract.py::test_a_kidnapping_is_NOT_detected_the_H7_finding`
still passes untouched, because A3 does not change what the localizer
*estimates* — it changes what is allowed to *move* on that estimate, and leaves
the shipped relocalization commit in place behind a default-off flag.

### Seeded-red — six mutants, over the real suite

Each mutation neuters one mechanism in the product and the suite is re-run
whole (throwaway pytest plugin in session scratch; no file in the tree edited):

| mutant | cells reddened |
|---|---|
| `ArmingLatch._latch` never latches | **17** |
| `RelocalizationMatch.is_discriminative` always True | **9** |
| `OperatorPoseReset.spent` always False | **3** |
| `_inside_polygon_verified` ignores `detector_confirmed` | **2** |
| `LocalizationJumpJournal.envelope_measurement` always UNMEASURED | **1** |
| `ArmingLatch.observe_update` never latches (the jump bound) | **3** |

Every headline row has a live measurement behind it; no cell is vacuous.

## Undone, and why

1. **`runtime.py` was not edited, and I judge the hook AVOIDABLE today.**
   `RobotRuntime` has the right shape for it (`_input_health_latched` +
   `clear_input_health_latch`, the operator-ack latch at `runtime.py:14025`),
   but **nothing in the product installs a `LocalizerProvider`** — the
   `localization/` package is still reached only by the H7 bench, NAV-CORE and
   tests — so a runtime field wired to a latch nobody feeds would be dead
   weight plus a flag. The composition point is deliberate instead:
   `LocalizedPoseProvider(..., arming_latch=…)` is where every
   `LocalizationUpdate` already passes, `provider.motion_latched` is the
   authority a caller reads, and `ArmingLatch.action` already speaks
   `HealthAction`. The one-line runtime composition
   (`translation_allowed = … and not localization_latched`) belongs with **A4
   SPINE**, which is the card that gives the runtime a stamped observation with
   a localizer behind it. Handed up rather than guessed.
2. **`require_relocalization_margin` ships OFF.** It is the flag rule, and the
   evidence for turning it on is one fixture, not a corpus. The row to run
   before flipping it: NAV-CORE's frozen corpus with the flag on, watching for
   relocalizations that were CORRECT and are now refused (a false refusal is a
   dog that will not walk).
3. **The carried/airborne thresholds are engineering choices, not calibrations**
   (`minimum_feet_in_contact=2`, `free_fall_mps2=6.0`). No IMU or foot-contact
   stream exists on this host to calibrate them against; box day owns that, and
   `StubCarriedSignatureSource` keeps the row wired and inert until then.
4. **`WholeMapMatcher` has no product installer.** Like the latch it is
   constructed by its caller; nothing renders map templates on a robot yet.
   That renderer is a map-side item (A4/the on-robot LIO ADR), and inventing one
   here would have been a second unmeasured thing.
5. **The jump journal is not wired to a record WRITER on this host.** It
   produces the entry and the merge; who runs it, on which traverse, and into
   which `configs/envelope/<host>.yaml` is a commissioning decision (HW-6's
   record surface, two closed cards' regions), not an executor's.
6. **`CODEBASE_INDEX.md` is STALE** (three new modules). CLAUDE.md ties
   regeneration to the commit, and this card commits nothing, so the integrator
   should run `.parcel/bin/python tools/codebase_index.py` at close.
7. **Nothing committed.** `git` was read-only throughout.
