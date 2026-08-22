# Next up

**Opened:** 2026-08-04 · **Refreshed:** 2026-08-22 from the
[conversational-autonomy HLD](../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
· Conventions in [README.md](README.md).

The detailed `N` cards are repository work that is either ready now or waits only on
another `N` card. The portfolio map also references `B` decisions/evidence at their
required point, but those cards remain in `BLOCKED.md` and are not made executable by
appearing here. Roadmap rationale lives in
[../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md](../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md).

## Active worktree delta — 2026-08-22

The dependency map below remains the durable first-ODD architecture queue, but the
current uncommitted engineering wave is newer than its N-card refresh. Its detailed
register is [`scrum/20260821/TASK_BOARD.md`](../scrum/20260821/TASK_BOARD.md).
Until those changes are reviewed and committed, they are visible worktree evidence,
not the shipped baseline.

| Priority | Current work | State / exit |
| ---: | --- | --- |
| 0 | R29 engineering handbook and documentation truth | Re-audit current architecture/quality, retire the misleading legacy status page, repair live links and stale current claims |
| 1 | Perception cutover integration closure | C-1 camera, C-2 map and C-3 policy exist, but no production composition root drains camera frames into the map or installs the learned source; fail closed on incomplete non-oracle configurations |
| 2 | PG-4 learned-map admission signal | Owner-gated: ranking margin is structurally zero in the measured label-primary distribution; fix/re-derive on textured evidence before enabling abstention |
| 3 | C-3 tail and generalization | Live voice plus at least three learned-map closed-loop development missions, VLM veto/duty cycle and re-derived thresholds precede the still-unspent held-out evaluation |
| 4 | MOVE-1 residuals | Patrol plumbing ran, but fix compounding slow-band attenuation, attribute dynamic-city contacts, repair vacuous evidence guards and repeat the narrow 5 m result |
| 5 | Measurement and eval wave | M-1 reliability/pass-k, M-2 adversarial sets, arrival across every class, R30 eval/lock/model provenance hygiene and SI-v3 prompt alignment |
| 6 | Red-team fixture decision | Choose an isolated derived variant or an explicitly re-pinned development scene for poster/decal decoys; do not spend held-out evidence to discover plumbing failures |

The key correction to the earlier board language is architectural: the source
selection helpers are not merely “not promoted”; their production binding is
incomplete. A YAML value can disable the demo POI oracle while the process-global
semantic candidate source remains the default oracle. Treat that combination as a
startup defect to close, not a usable shadow/cutover mode.

## Prioritized delivery and dependency map — 2026-08-16

This table is the current portfolio front door. Only `N` rows marked `READY` are
active repository work; `AFTER` rows have repository-internal predecessors. `B` rows
are shown only to make decisions and physical evidence occur at the right point in
the dependency graph—their executable unblock actions remain in
[BLOCKED.md](BLOCKED.md). Detailed cards follow below; older landed or superseded
cards are retained only as history.

| Rank | HLD lane | Task | State and hard predecessor |
| ---: | --- | --- | --- |
| 0A | Regression closure | **N45** lamppost/object-class semantic-arrival reliability (R28 successor) | **READY**; current hard nightly reproducer is RED |
| 0B | Evaluation truth | **N46** current-nav baseline re-freeze + follow-bench rerun | **AFTER N45**; never freeze the known arrival defect as acceptable |
| 1A | P0 physical authority | **N24** gateway protocol/fake-Sport slice | **LANDED 2026-08-16**; bounded software/fake/process evidence, explicitly not the complete gateway |
| 1B | P0 release truth | **N27** source/package parity | **LANDED 2026-08-16**; current gate verifies 91 packaged assets |
| 1C | P0 admission truth | **N29** strict configuration/capability admission | **READY**; consume N27's landed manifest at exit |
| 1D | P1 sensor truth | **N23**, **N25**, **N26** sensor/replay/plausibility/loss slices | **READY**, parallel; N23 no longer waits on S-1 hardware |
| 1E | Early owner semantics | **B5, B6, revised B7, B8, B14, B18, B19, B22, B23** | **OWNER-BLOCKED**; decide in parallel so implementation/promotion does not stall later |
| 2A | P0 physical authority | **N28** gateway process, launcher, credential isolation, commissioning client, fault campaign | **READY** for native/product process substrate after N24; generated contract/envelope integration exit after N29 |
| 2B | Early physical evidence | **B16** gateway bench/single-axis HIL | **AFTER N28 + N29** and hardware/operator unblock; explicitly before advanced navigation |
| 3A | P0–P4 evidence | **N42** base causal envelope, nonblocking recorder and refutation runner | **READY**; full-chain exit integrates later contracts |
| 3B | P1 world evidence | **N30** live/replay sources + `WorldModel` + `WorldSnapshotV2` + `NavigationSnapshotV2` | **AFTER N23** |
| 3C | P1 real sensor evidence | **B25** executed Stage-0 capture/calibration artifact | Capture **AFTER N23/N25/N26 + B9–B12** and hardware/operator unblock; N30 consumes it before B17 |
| 4A | P1 localization | **N31** fail-closed provider and timestamped `T_map_odom` software seam | **AFTER N30**; canonical fallback activation needs B8 |
| 4B | P1 localization evidence | **B17** physical localizer commissioning | Offline bake-off **AFTER N31 + B25**; physical-profile exit also needs B8 implementation + N43 |
| 4C | P1 actuation admission | **N43** minimal sole product gateway client + `SafetyDispositionV1` final governor | **AFTER N28 + N29 + N30** |
| 4D | P1 navigation substrate | **N44** fail-closed observed-space planner/grid seam | Substrate **AFTER N29 + N30 + N31**; integration exit after N43; product policy promotion needs B6/B7 |
| 4E | P1 product-client evidence | **B30** N43 TTL/stop HIL rerun | **AFTER N43 + B16** and hardware/operator unblock |
| 4F | P1 observed-space evidence | **B31** bounded N44 static-obstacle run | **AFTER N44 + B17 + B30** and hardware/operator unblock |
| 5A | P2 interaction | **N32** committed-turn/command-authority/turn-disposition contracts and dialogue sequencer | Base **AFTER N29**; world/task reference+narration integration after N30/N33/N36 |
| 5B | P2 inference | **N35** inference broker + bounded read-only tool synthesis | **AFTER N29**, parallel with N32 |
| 6 | P2 task authority | **N33** `PlanSketch` default, deadlines/retries, certified checkpoints, one consequential-action lifecycle | **AFTER N30 + N32 + N43** |
| 7A | P2 closed-loop autonomy | **N34** bounded `MissionSupervisor` + typed navigation intent/grounding/execution goals | Contract work after N30 + N33 base; navigation/terminal exit also needs N31; full promotion needs B5/B22 and B23 if restore is admitted |
| 7B | P2 memory | **N36** governed dialogue/episodic/profile retrieval and world-model projections | **AFTER N30 + N35 + N32 base**, parallel with N34 |
| 7C | P2 audio | **N37** priority speech, duck/restore, streaming partial-ASR software lane | **AFTER N32**; broker integration follows N35, acoustic/AEC promotion remains B3/B15 |
| 7D | P2 human evidence | **B29** held-out companion review | **EXTERNAL/OWNER-BLOCKED** after the evaluated N32/N35–N37 slice |
| 8 | P3 identity | **N38** evidence-independence-safe perception + `OwnerBeliefV1`/re-ID | **AFTER N30 + N31**; bounded robot evidence is B26 |
| 9 | P3 navigation | **N39** behavior-scoped goals, moving formation, social recovery and shadow challengers | Generic work **AFTER N31 + N34 + N44**; formation integration exit also needs N38; promotion needs B6/B7 |
| 10A | P3 spatial continuity | **N40** map-versioned place/semantic memory and geofence/drop-off/traversability constraints | **AFTER N31 + N39** for replay/spec; terminal/collision promotion needs B5/B6 |
| 10B | P3 fault isolation | **N41** migrate local maps/tracking/controller into the N43 sidecar | **AFTER N39 + N43**; it does not create a second gateway client/governor |
| 10C | Interleaved robot evidence | **B26–B28** identity/follow, local-nav/governor, terminal/geofence/terrain rungs | Run immediately after each owning software seam and external unblock |
| 11 | P4 integrated commissioning | **B24** repeated first-ODD mission campaign | **AFTER** its named software, policy, early-HIL, localization and staged field gates |
| Ops | Hosted execution proof | **B20** GitHub Actions enablement/run evidence | Parallel repository-admin action; not by itself a physical P4 gate |

Physical execution is deliberately absent from `NEXT`: B16/B17/B25–B31 interleave
hardware evidence with software, and B24 owns final integrated commissioning.
Phase-5 learned navigation remains absent until N42 records a repeatable residual
that beats the deterministic baseline in shadow/replay.

Each applicable N28–N44 slice must also reduce, not grow, the current concentration in
`RobotRuntime` and `DirectiveNavigator`: extract the named state owner behind its
typed port, wire it from one composition root, and retain the existing behavior as a
tested rollback path. No card is permission for a whole-runtime rewrite or another
parallel mutable state store.

### Lower-priority existing cards

These remain useful, but they are not predecessors of the first-ODD architecture:

| Card | Disposition |
| --- | --- |
| N5 full BARN and N9 Follow-Bench | Run after N38/N39/N42 as external proxy comparisons; never promote from proxy scores alone. |
| N7 emote schema | Run after N28/N33 so physical clips use the admitted `GatewayActionV1` lifecycle; simulator schema work may proceed earlier. |
| N21 temperament block | Run after N36 and only promote mappings supported by U36 measurement. |
| N22 system-utterance acoustic case | Absorbed by N37 software behavior and N42's versioned evaluation runner. |

> **Landed 2026-08-04:** N1 (W8, closed U6), N6 (W7, opened U11),
> N2/N3/N4 (W1–W6), and N8 (W9).
>
> W9 measured N2–N4 rather than assuming them, and the answers are mixed. N4
> (the shaper) is **proven**: RMS commanded jerk fell 42% across all eleven
> bench episodes, which closes most of U14. N2 (anticipation) is **not shown**
> and U12 now carries the measurement that says so. N3's gate **engages but
> does not reduce gate interventions** (new U15), while its planner half buys
> an 11% clearance margin. N6's search sequences and gives up cleanly but never
> reacquires (new U16). N8 also turned up U17: the expression stack is gated
> off for 47–84% of a follow because the owner trips the proximity gate.
>
> The four open follow-ups are U15, U16, U17, and the calm-profile remainder
> of U14. None is scheduled.

---

## N10 — Kickoff board K0–K2′ · **CLOSED; sequencing superseded 2026-08-16**

Not active. K0, K1, K2, and the Phase-1 gate have landed status records under
`scrum/20260805/task_1/`. The “hardware last” ordering is superseded by the HLD's
early gateway HIL and interleaved physical evidence. Retained below as history.

The 2026-08-05 final plan
([scrum/20260805/task_1/ADJUDICATION.md](../scrum/20260805/task_1/ADJUDICATION.md),
as amended by the owner: **hardware last, sim throughout**) names three
first actions: **K0** goal-calibration fix (one arrival authority shared by
navigator/semantics/scorer; step-limit audit; honest baseline re-freeze —
hours, and every later eval delta is uninterpretable until it lands), **K1**
contract RFC + CI contract tests (Sol's V1 DTO family merged with
DetectionMsg + the dialogue-state channel), **K2′** sim-bag
recorder/replayer with a real-sensor-shaped bag schema + the
hardware-readiness ledger (every place sim stands in for hardware gets a
named re-run gate for the final hardware phase). Hardware procurement moved
to the final phase by owner decision.

## N11 — Traffic-aware goal placement · **LANDED PORTION CLOSED; policy residual moved to B22**

### 2026-08-07 (card F-1, scrum/20260807/task_2/NAV_FINISH_STATUS.md)

The **final-approach geometry** this card kept pointing at is fixed and one
pin flipped. Three root causes, all measured live before anything changed:

1. the `next_to` pose was planned on the K0 band's **outer edge** while the
   controller declares arrival anywhere within `arrival_radius` of it — a
   pose at 1.5000 m admits a stop at 1.5800 m, and the 2026-08-06 trace
   stopped at 1.572 m. `approach.py` now plans inside an inset band;
2. the `next_to` occupancy test compared a robot **centre** against a
   **surface** point with a footprint-to-surface threshold — the body radius
   was missing — and ignored id-less returns entirely;
3. **routable and impassable**: A\* inflates by 0.42 m, the collision gate
   hard-stops at 0.8 m footprint-to-surface, and a corridor between those
   numbers deadlocks the body at exactly the boundary while the route still
   reports `planned`. The mission now releases such a commitment
   (`_gate_blocked_route_recovery`), as it already does for `goal_blocked`.

`test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit` is a **hard gate**
(arrives 1.493 m from `lamp_post_1`, inside the band, and sits).

**Still open, and both re-pinned with exhaustive measurement, not traces:**

* **the bench sit** is *geometrically impossible*, not short: the K0 `next_to`
  band is measured from the anchor CENTRE while stand-off is measured from its
  SURFACE, and a 3601×551 sweep of the whole band finds **zero** admissible
  poses at the shipping envelopes — with `pedestrian_5` standing inside the
  band in the static city. Fixing it is a **K0/sidecar decision** (scale the
  band with the footprint, or drop `next_to` from `bench`'s affordances the
  way `building` already does), not a navigation card;
* **the traffic case** fails 3/3 on the clock, but now with the robot
  **inside** the scored polygon (K0 distance 0.000 m) holding
  `status=planned|person_stop` because a pedestrian is parked on the last
  0.2 m to the approach pose. The residual is a **yield-vs-deadline product
  decision** — how long may a `NavigateTo` yield before it reports "blocked by
  a person" rather than `step_timeout`? — not final-approach behaviour.

<details><summary>Original card (2026-08-06)</summary>

Found by the voice→nav e2e gate (scrum/20260805/task_2): with pedestrians
active, the sidewalk approach pose lands beside the crosswalk stream and
person-stop safety (correctly) never accumulates the final metre;
ramp-from-zero between passes compounds it.

**Landed:** `navigation/traffic_aware.py` (Sol, pure) + wiring (Opus) —
traffic-aware ranking inside `approach.safe_approach_pose`, byte-identical to
static ordering when no tracks are present, and `RampMemory` yield-advance
seeding applied to **both** serial rate limiters (grid slew + the runtime
S-curve shaper; seeding only the navigator was measured at +6.4% because the
jerk-limited shaper re-ramps from zero regardless — see
scrum/20260806/task_1/).

**Gate outcome — honest:** the xfail did **not** flip.
`test_go_to_the_sidewalk_with_pedestrian_traffic` still fails, but the failure
changed shape: measured post-wiring the robot travels 2.09 m and stops 0.33 m
outside the sidewalk GoalRegion, failing on `step_timeout` against the 240 s
NavigateTo budget — a near-miss on the clock rather than a robot that never
advances. The residual work is **final-approach behaviour in traffic**, not
goal placement.

**Remaining (the card that flips the gate):** proxemic cost on the approach
*pose* (not just which candidate point) + a final-metre yield policy; the
parked `navigation/proxemic_approach.py` is the intended ingredient — its TTC
term and `reject_cost` shape are the right basis for a fail-closed veto on the
ranked winner (do not wire it as a competing selector; two disagreeing
proxemic authorities is the D5 defect class). Belongs to the D0/P3
social-planning card.

### Residual LANDED 2026-08-07 (Lane D, card D-5) · xfail still NOT flipped, and the reason moved again

Both ingredients are wired.
(a) `proxemic_approach` is a **fail-closed veto on the traffic-aware ranked
winner**, never a selector: it walks the ranking in order, may only strike
candidates out, and all-struck returns `None` (an honest no-pose). Empty tracks
skip the veto entirely, so the static ladder rule stays byte-identical.
(b) A **final-metre yield policy**: inside 1.0 m of the goal, on a tick where
`apply_collision_brake` has *already* returned `clear`, if the classical
tracker's own predictions say no confirmed person enters the person-stop
envelope within 1.5 s, the `RampMemory` release seed floors at a 0.12 m/s creep
instead of zero. It is not a gate and not a command source — same safety
argument as `RampMemory`, no stronger. Predictions come from a second tracker
fed **positions only**, so no oracle velocity reaches the decision.

**Measured, n=3 paired seeds, instrumented product path (sim + runtime +
`handle_text`, dynamic city). The e2e xfail was NOT edited.**

| seed | before | after |
|---|---|---|
| 7 | `failed`/`step_timeout`, 241 s, 0.328 m out, path 2.09 m | **`succeeded`/`navigation_goal_verified`, 46 s** — but at `sidewalk_south`, 5.342 m from the scored polygon |
| 11 | `failed`/`step_timeout`, 240 s, 0.420 m out, path 1.98 m | `failed`/`step_timeout`, 240 s, **0.295 m out**, path **11.81 m** |
| 23 | `failed`/`step_timeout`, 241 s, 0.330 m out, path 2.09 m | **`succeeded`/`navigation_goal_verified`, 51 s** — at `sidewalk_south`, 5.814 m out |

The before column reproduces this row's pinned baseline exactly (2.09 m,
(−0.28, 2.07), 0.33 m, `step_timeout`).

**What the residual is now.** Two of three runs stop dying on the clock and
reach a verified arrival in ~50 s. They arrive at the **south** sidewalk: the
crosswalk stream is north, the veto strikes out every north approach pose, the
mission replans, and grounding's documented region tie-break ("any same-label
instance satisfies a stuff-class directive; tie-break to the nearest") picks
the other instance. The e2e assertion is pinned to one of two equally valid
instances, so `goal.contains(x, y)` is False and the case still fails.

**The remaining question is no longer a navigation one:** does "go to the
sidewalk" mean a specific polygon or any sidewalk? That is Lane C's
region-instance-selection question (stratum 3), not final-approach behaviour.
The third seed shows the final-approach half is also not finished — 11.81 m of
path against 1.98 m and 0.295 m out against 0.420 m is real motion where there
was none, but not enough to close the last third of a metre in budget.

Full evidence:
[scrum/20260806/task_3/LANE_D_STATUS.md](../scrum/20260806/task_3/LANE_D_STATUS.md)
card D-5. **The xfail flip is the review round's call.**

**Related, same root cause, opened by the same round:** the U34 yaw fix
(card D-4) flips which `sidewalk` instance a directive from the origin grounds
to — the two centroids are 3.2 m (north) and 3.0 m (south) away, and the
documented stuff-class tie-break takes the nearest. Four suite cases pin the
north instance and are now red:
`test_embodied_plan_eval` ×2 and `test_voice_nav_e2e::{test_go_to_the_sidewalk_grounds_plans_and_arrives,
test_walk_towards_the_lamppost_grounds_plans_and_arrives}`. The question behind
all of them, and behind N11's residual above, is one sentence: **does "the
sidewalk" mean a specific polygon or any sidewalk?** That is a stratum-3
region-instance-selection decision, and it should be taken once, together with
W0-D's scene-truth adoption and U31 option 2, so the frozen inputs are
re-decided in a single re-freeze.

</details>

## N12 — "go to the owner" cannot reach the owner · ~~hours~~ · **LANDED 2026-08-07 (Lane C)**

**Closed.** `navigation/goals.py` gained `OWNER_REFERENT_TABLE` +
`owner_referent_from_directive`, and `voice/local_plans.sketch_navigate`
returns `sketch_come()` for any owner-referring target — the SAME approach
lane "come here" uses, so there is exactly one way to mean "the owner".
`NavigateTo` can no longer be emitted for `owner`/`me`/`you`/`my side`
(pinned over the whole table in
`tests/test_owner_and_settle_plans.py::test_no_owner_phrasing_can_produce_a_navigate_to_step`).
The e2e xfail
`test_go_to_the_owner_arrives_in_the_owner_anchored_region` **flipped to a
hard gate and passes live** (2026-08-07: owner walked 3 m up the block,
formation held, owner-anchored predicate satisfied, navigation lane never
armed). Record: [scrum/20260806/task_3/LANE_C_STATUS.md](../scrum/20260806/task_3/LANE_C_STATUS.md).

<details><summary>Original card (2026-08-06)</summary>

Measured 2026-08-06 on the product path (`tests/test_voice_nav_e2e.py`,
pinned xfail `test_go_to_the_owner_arrives_in_the_owner_anchored_region`).

`"go to the owner"` routes correctly (`direct_skill` /
`navigation_directive`, `last_reasoning_source="local_plan_sketch"`, no
admission error) and compiles to `NavigateTo` with goal relation `near` and
target label `"owner"` — that is, it asks the **semantic map** for an object
labelled "owner". The owner is not a semantic-map object; it is a tracked
entity on the owner channel (`observation.owner`, `visible=True`,
`confidence=1.0`, 2.06 m away at the time of the request). The resolution
ladder therefore runs `scan_behavior_rotate` → `search_entity_frontier` →
`search_entity_align` for ~38 s and the task ends **failed** with
`navigation.reason="semantic_target_not_found"`, having travelled 1.4 m *away*
from the owner.

The capability itself exists and works: `"come here"` reaches the owner
through the approach lane (`FollowFormation(relation="follow")`, measured
5.03 m → 1.78 m). Only this phrasing cannot reach it.

**Fix:** bridge owner-referring targets to the owner track — either resolve
`"owner"`/`"me"`/`"you"` in `semantic_goal_from_directive` to the owner
channel, or route owner-referring navigation directives to the approach cap
instead of `NavigateTo`. Prefer one authority: two ways to mean "the owner"
that resolve differently is the D5 disagreement class.

**Gate:** flips the xfail above to a hard gate.

</details>

## N13 — "sit next to X" · **LANDED PORTION CLOSED; affordance/band residual moved to B22**

**2026-08-07 (card F-1).** The lamppost half is a **hard gate**: the dog walks
to `lamp_post_1`, stops 1.493 m from it (inside the K0 `next_to` band, miss
0.000 m) and **sits** — `posture='sit'`, `terminal_relation_verified=True`.
The placement fixes are in N11 above.

The bench half does **not** flip and is no longer an N11 item: an exhaustive
sweep of its whole band against the true scene geometry finds **zero**
admissible poses, because the band is measured from the anchor centre while
stand-off is measured from its surface, and `pedestrian_5` stands inside the
band in the static city. Deciding it needs K0 (`NEXT_TO_BAND_M` scaling with
the anchor footprint, with a re-freeze) or the scene sidecar (drop `next_to`
from `bench`'s affordances, as `building` already does). Full numbers:
`scrum/20260807/task_2/NAV_FINISH_STATUS.md`.

<details><summary>Compile-half card (2026-08-07, Lane C)</summary>

**What landed.** `sketch_navigate("sit next to X")` now returns
`sketch_settle_next_to`: **two** steps, `NavigateTo` + `Pose(name="sit")`,
under a `hold`/`current_pose` goal — the only goal shape
`PlanValidator._validate_goal_completion` admits for a terminal `Pose` step.
`Pose` joined `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS` and
`configs/robot.yaml`'s brain skill list, dispatching through the same runtime
posture door as `ReturnToSafePose` (stop motion, then apply a catalog pose)
and verified against the same `state.posture` witness — one posture authority,
not two. The e2e now reports the two defects **separately**:

- `test_sit_next_to_the_lamppost_emits_a_posture_step_and_reaches_it_if_it_arrives`
  — **hard gate, passing live** (2026-08-07): the admitted plan is
  `["NavigateTo", "Pose"]`, and the posture is asserted whenever navigation
  reaches terminal success;
- `test_sit_next_to_the_{bench,lamppost}_settles_beside_it_in_a_sit` — still
  xfail, reason rewritten to **placement only**, attributed to the N11
  final-approach family (bench: `navigation_no_progress` 0.21 m outside the
  band; lamppost: `semantic_arrival_verification_failed` 0.072 m outside).

**Remaining:** the placement half, which is the N11 residual card. The posture
condition starts biting with no edit the moment navigation succeeds.

</details>

**Measured 2026-08-07, later the same day (runtime lane, full e2e run,
`MUJOCO_GL=egl`): `test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit`
XPASSes.** So the lamppost placement *and* the posture both happened on a real
run — the "starts biting with no edit" prediction fired. The bench variant
still xfails, so the fix is not uniform and the card is not closed here. Flip
the lamppost pin after a confirming re-run; owner is whoever owns
`tests/test_voice_nav_e2e.py` / `navigation/**`. Also observed in that run: the
two pre-existing approach hard gates and all four of Lane C's unverified
pinned cases now pass, i.e. Lane C H8 (`safe_approach_pose → None`) appears
fixed.

**One correction to the record above:** `configs/robot.yaml` was **not**
changed for this — the paragraph saying `Pose` joined its brain skill list is
wrong, and Lane C's own status says why (the file is a locked input of the
frozen embodied-plan manifest and is byte-identical to entry). `Pose` is
admitted through `RUNTIME_AUTHORED_SKILLS` in the *system* registry instead.
Since 2026-08-07 the compiler no longer needs a fallback for it either: the
runtime selects the registry by route, so a `direct_skill` sketch compiles
against the system registry (Lane C H7, done).

<details><summary>Original card (2026-08-06)</summary>

Measured 2026-08-06 on the product path (pinned xfails
`test_sit_next_to_the_bench_settles_beside_it_in_a_sit` and
`..._the_lamppost_...`).

`"sit next to the bench"` compiles to a plan with **exactly one step**,
`NavigateTo(directive="sit next to the bench")`. No Sit pose step is emitted.
The "sit" verb survives only inside the directive string, where the navigator
re-reads it as the `next_to` *placement relation* (`goals.py` `\bsit\b`
gate). `terminal_behavior="hold"` is written to mission metadata and has **no
consumer**. Measured `runtime._last_posture` at the end of both runs:
`"unknown"` — the dog has never sat. The compound placement+posture predicate
(`instructnav.scoring.evaluate_sit_next_to`, landed with this card) therefore
cannot pass its posture gate by construction.

**Fix:** compile `sit next to X` as navigate **+ settle**: a second plan step
that applies the `sit` pose after arrival, verified against `_last_posture`
the way `ReturnToSafePose` already is. The predicate and its unit tests
(`tests/test_instructnav_compound_predicates.py`) are already in place and
report the posture gate separately, so the fix has a scoreboard on day one.

**Also observed in the same runs (separate, N11 family):** both sit cases fail
their *placement* half too, in static city with no traffic — bench:
`navigation_no_progress` at 1.71 m from centre (0.21 m outside the K0
`next_to` band) after repeated proximity stops; lamppost:
`semantic_arrival_verification_failed` at 1.572 m (0.072 m outside the band).
Final-approach behaviour, same family as N11's residual card.

</details>

## N14 — RESUME restores the channel but not the executive task · **LANDED 2026-08-07** (runtime/voice lane)

**Opened 2026-08-07 (Lane C), fixed the same day.** Record:
[scrum/20260807/task_2/RUNTIME_HANDOFFS_STATUS.md](../scrum/20260807/task_2/RUNTIME_HANDOFFS_STATUS.md).

**Original finding.** `handle_text("go to the sidewalk")` → `"pause"` →
`"resume"` restored the navigation channel (`state="searching"`,
`reason="navigation_resumed"`) while the executive task record stayed
`state="suspended"`, `last_detail="suspended:closed_intent_pause"` — the robot
driving with the authorizing plan step's verification, timeout, and recovery
policy switched off.

**Corrected on re-measurement (2026-08-07, before the fix).** Lane C recorded
the channel as "advancing across further `_step_brain()` ticks". It was not:
the *first* tick after the resume re-paused it. `_reconcile_semantic_tasks`
sees a still-suspended task, drops its dispatch record, and pauses the channel
again with `reason="task_suspended"`. So the true failure was worse and
quieter than pinned — a spoken RESUME held for less than one control tick and
then parked the mission permanently. Both the fix and the pins are written
against that measurement.

**Fix.** The channel and the plan step now resume together or not at all, in
`RobotRuntime._apply_closed_intent`'s resume branch:

- `TaskExecutive.resume_task_running` returns a suspended task to `running`
  **without** re-dispatching (resources re-acquired, timeout clock restarted),
  and `SemanticTaskRuntimeAdapter.adopt` re-binds tracking to the controller
  that kept its state. `resume_task` (re-queue → re-dispatch) would have
  cold-started the mission it had just restored.
- The join is on the suspend *reason*: only tasks parked by
  `closed_intent_pause` are restored, and a channel whose task is parked by
  someone else (owner summons, goal amendment) is **not** released — refusing
  is honest; releasing it alone is the same defect through another door.
- Fail-closed both ways: an empty store still answers "There's nothing paused
  to resume right now", a freshness rejection still leaves *both* halves
  paused, and a task that cannot re-acquire its resources re-pauses its
  channel rather than driving unauthorized.

**Pins (xfail flipped on measured behaviour):**
`tests/test_closed_intent_product_path.py::test_resume_also_restores_the_executive_task_record`
plus `..._survives_a_control_tick_between_pause_and_resume`,
`..._continues_the_paused_mission_rather_than_restarting_it`,
`test_a_stale_resume_leaves_both_the_channel_and_the_task_paused`, and
`test_resume_does_not_restart_work_it_did_not_pause`.

**Not claimed:** never run in live sim. Every measurement above is the
product-path layer (real `RobotRuntime`, fake backend, entered at
`handle_text`), which is where the composition is real but the physics is not.

## N15 — `map` → `odom` gap · **SPLIT 2026-08-16 into N31 + B17**

Not active as one card. N31 owns the unblocked fail-closed transform contract,
golden replay, covariance/health, and jump semantics. B17 owns physical-localizer
selection, installation, real-bag integration, and commissioning. The original
finding remains below as historical context.

**Recorded 2026-08-07** from Lane B hand-off 3, so it lives somewhere other
than a code comment. `grid_navigator` is ODOM-bound while `mission.goal` is a
MAP quantity, and no transform connects them. Under `TruthPoseProvider` the
two frames are identical, so nothing moves today and nothing is measurably
wrong; the moment a real localizer occupies the MAP role, `grid_navigator.act`
is the one call site that needs it. Named in the code at
`navigation/grid_navigator.py:333`. Owner: whoever owns `navigation/**`.

**Second, smaller residue found while wiring the LOST announcement:** the
`"pose_lost_hold"` note literal now exists in three trees —
`navigation/pipeline.py` (producer), `runtime.py` (`POSE_LOST_HOLD_NOTE`), and
`evals/walk_with_me/runner.py` (`POSE_LOST_NOTE`). Three copies of a control
string is how "halt" got lost (U33). The shared home is `navigation/base.py`
next to `MAP_FRAME`/`ODOM_FRAME`; it was not made because that file belongs to
another lane.

## N16 — Barge-in acoustic stop · **software landed; physical proof tracked by N37 + B3/B15**

`SpeakerSink.interrupt()` sets the latch and stops **writing** at the next
~50 ms block, but samples already handed to PortAudio still play out. Measured
on the virtual rig: detection 0.128 s, queue flush 71 µs, **acoustic stop
p50 0.72 s** against a 0.52 s bar. The robot talks over the owner for roughly
half a second after it has correctly decided to stop.

`duplex_v1` cannot see this: it asserts no chunk-token leakage, which is true.
Only an acoustic-boundary measurement catches it.

**Fix:** abort the output stream on interrupt rather than merely ceasing to
write it (`sounddevice.OutputStream.abort()` discards buffered frames;
`stop()` drains them). Re-run
`evals/companion/acoustic_loop_v1 --families bargein` and expect
`bargein_acoustic_stop_p50_s` to fall toward the detection figure. Baseline to
beat: `results/acoustic-loop-v1-20260807-baseline-run01.json`.

**UPDATE 2026-08-09 (card acoustic-close, `scrum/20260809/task_8`).** Code
landed in `SpeakerSink._play` (`abort()` before the context-manager's draining
`stop()`), unit-pinned in `tests/test_acoustic_defects.py`. **The rig gate did
NOT move (0.78 s), and this is a rig limit, not the fix:** the null sink's
`OutputStream.latency` is 0.0000 s, so there is no output-buffer drain to
abort — with and without the change the robot stops 0.02 s after `interrupt()`.
The 0.78 s the gate reports is owner-interrupt **residual** in
`robot_only_envelope`'s power subtraction (frame dump: robot silent at
interrupt+0.12 s, then spurious 1-frame owner-residual spikes at +0.5–0.7 s set
`acoustic_end`). `abort()` needs a real output device to validate →
`does_not_prove` on the null-sink tier. **Still OPEN as a rig-measurable gate.**

## N17 — Echo/self-capture diagnosis · **software landed; physical proof tracked by N37 + B3/B15**

False barge-in rate **1.00** against a 0.02 bar on the frozen noise set. Silero
is not at fault — probed directly it rates those fixtures at max p = 0.21/0.23
(threshold 0.5) and real interrupt speech at 1.00.

The cause is ordering in `MicrophoneVoiceLoop._handle_frame`: during playback
the echo guard runs **before** the neural VAD and `return`s on suppressed
frames, so Silero receives only the frames that survived the guard — a
discontinuous stream of loud fragments with artificial onsets, not the
continuous signal it was trained on. The gate fragments the model's input and
the fragments look like speech.

**Fix candidates:** feed Silero the continuous stream and apply the echo guard
to its *decision* rather than to its input; or keep the guard as a gate on
barge-in only and let the VAD see everything. Either way, re-run the `bargein`
family. Interacts with N18 — with real AEC the guard should be redundant.

**UPDATE 2026-08-09 (card acoustic-close, `scrum/20260809/task_8`).** Code
landed (echo guard moved from the VAD's input to its decision; Silero now sees
the continuous stream), unit-pinned in `tests/test_acoustic_defects.py`. **The
original fragmentation diagnosis is WRONG and the rig gate did NOT move (1.00):**
directly measured, Silero rejects the raw noise fixtures (max p 0.170 / 0.287)
and **both old and new code reject every noise fixture at gains 1×–10×** on clean
frames. The real cause of the rig false positives is that **the robot's own
audio is in the loop's mic capture at full scale** — with the robot playing and
NO owner injected, a barge-in still fires (capture RMS mean 2570, peak 32767).
`pw-record --target <mic>` is being connected by WirePlumber to `<sink>:monitor`
(which carries the robot); it survives wireplumber/pipewire restarts and
`--target <mic>.monitor`. An energy guard cannot suppress a full-scale echo, so
this is unfixable in `voice_audio.py`; it needs a clean mic capture (rig/env
fix, `append/new only` barred this lane) or real AEC (N18). The decision-gating
code is correct for a real *attenuated* echo, which this tier cannot create →
`does_not_prove`. **Still OPEN as a rig-measurable gate.**

## N18 — Owner-gated acoustic cards · **MOVED to B3/B15; not active NEXT work**

Four cards are fully prepared and cannot be gated without a transducer:
`device-activation-snapshot`, `acoustic-hello-smoke`
(`scripts/acoustic_smoke.sh`), `aec-l0-pipewire` (config drafted, needs node
names from the snapshot), and the Tier-2 `doubletalk-operating-curve`. Exact
commands, expected output and gates:
[../docs/ACOUSTIC_BRINGUP_PLAN.md](../docs/ACOUSTIC_BRINGUP_PLAN.md) §5.

Nothing here needs re-derivation — it needs a mic plugged in.

## N19 — Fan acoustic clocks into the latency ledger · **ABSORBED by N42**

The measurement surfaces landed (`WhisperCppProvider.last_metrics`,
`MicrophoneVoiceLoop.last_turn_clocks`,
`SpeakerSink.first_chunk_started_monotonic`). The fan-in did not: every ledger
write goes through `RobotRuntime._voice_stage`, and `STAGES` in
`observability.py` is a closed vocabulary whose `mark()` raises on unknown
names — both outside the audio lane's ownership.

Exact five-step diff (new `STAGES` entries, the hardcoded `source="text"` at
`runtime.py:4886`, the chunk-token extension, `_record_turn_commit`, and the
`latency.html` `metricNames` array) is in
[../docs/ACOUSTIC_BRINGUP_PLAN.md](../docs/ACOUSTIC_BRINGUP_PLAN.md) §3.

**Until it lands no sub-700 ms ack claim may be made from `/latency`.** The
acoustic tier has now measured the gap the dashboard hides: **0.54–0.64 s**
between enqueue and audible.

**UPDATE 2026-08-09 (card acoustic-close, `scrum/20260809/task_8`).** The
`STAGES` half landed: `capture_speech_end`, `semantic_commit`,
`stt_request_start`, `stt_final`, `audio_first_sample` are now in
`observability.STAGES` (the keystone — `mark()` raised on them before), and the
three measurement surfaces are verified present. Unit-pinned in
`tests/test_acoustic_defects.py`. **The runtime fan-in remains OPEN and is now
the ONLY blocker:** the four marks are all in `runtime.py`
(`_audio_chunk_started` @1303, the `source="text"` @5353, `_record_turn_commit`
@5511, the STT `last_metrics` read), which is DO-NOT-TOUCH for this card and
whose `_audio_chunk_started` is shared with the gesture/emote lane. The
`DuplexVoiceSession` cannot relocate the fan-in (it holds neither the tracker
nor the sink/recognizer/turn-token). Remaining diff = §3 of
`docs/ACOUSTIC_BRINGUP_PLAN.md`, now unblocked, for the runtime lane.

## N5 — Extend the BARN harness to all 300 public worlds · **DEFERRED after N39/N42 · proxy only**

Today's honest 2%→44% figure is from a 50-world proxy subset. Running the full
public set produces an externally comparable score distribution with zero ROS
work — the cheapest step toward the primary external benchmark.

## N7 — Emote YAML schema upgrade · **after N28/N33 · week** · reduces U10 risk

Note (2026-08-04 sprint review): Gesture `intensity` is validated end-to-end
(0.5–1.5) and travels with the dispatch, but nothing scales the clip yet —
execution runs the YAML as authored. The prompt policy no longer advertises
the knob. Wiring intensity → duration/amplitude scaling lands here with the
per-clip schema, not before.

Before authoring more clips: per-clip entry/exit stance declarations, a
pose-transition graph enforced by the validator, interruptible/truncatable
flags, and feasibility gates in the kinematic preview (joint limits, per-joint
velocity/acceleration bounds, support-polygon static stability). Laban
parameterization (valence→amplitude, arousal→tempo) then turns the existing
clips into many perceptibly distinct expressions with zero ML.

Doing this *before* growing the catalog avoids re-authoring later.

## N9 — Self-run Follow-Bench comparison · **DEFERRED after N38/N39/N42 · proxy only**

Port `FollowOwnerController` into the MIT-licensed, pure-Python, no-ROS
Follow-Bench harness and report success/jerk/personal-zone against its
published planners. The planner I/O is nearly isomorphic to Parcel's HAL. Pin
the evaluated commit — the paper is under review and the repo is young.

Pays three times: an external comparison number, the recipe donor for N2, and
metric alignment for the in-house eval.

## N20 — Re-plan after a yield give-up, instead of ending the mission · **LANDED 2026-08-09**

**Closed (card n20-person-release).** `DirectiveNavigator.release_current_candidate(reason) -> bool`
(`navigation/pipeline.py`) is the runtime-callable entry point; it drives the
existing single release door (`_release_unreachable_candidate`) — the same
exclusion set and replan budget A\*, the obstacle gate, and the approach solver
share, so there is no second person-stop dwell counter (the D5 rule). The
runtime's yield policy calls it at give-up (`runtime.py::_yield_release_and_replan`,
before the give-up line is spoken): a replan may find an alternative and the
mission continues, or the ladder is spent and the honest end stands. Pinned in
`tests/test_yield_policy.py` (navigation entry point + runtime wiring, with
person-stop still zeroing every gated tick). The traffic e2e stays xfail on U35 /
the stratum-3 region-instance decision — a pedestrian STREAM blocks every
alternative approach, so release alone does not flip it (reason text updated).

The original hand-off, for the record:

The yield policy (2026-08-08, card P-1,
[../docs/YIELD_POLICY.md](../docs/YIELD_POLICY.md)) ends a mission honestly
when a person will not clear the approach:
`blocked_by_person_unanswered`, spoken and attributable, ~32 s instead of
240 s of `step_timeout`. That is strictly better than what it replaced, and it
is still the *simplest* answer. A blocked approach pose often has an
alternative — the navigation lane already has the machinery
(`_release_unreachable_candidate`, one exclusion door via `_ExcludingSemanticMap`,
one replan budget) and already uses it for three other authorities (A\*
`goal_blocked`/`no_path`, the obstacle gate, and a `None` approach pose).

**The hand-off, exactly.** A fourth release authority is a navigation-side
edit and this card does not own `navigation/**`. What it needs is either

* a `DirectiveNavigator` entry point the runtime may call — e.g.
  `release_current_candidate(reason: str) -> bool` — returning whether an
  alternative exists and the mission continues, or
* a `person_stop`-dwell counter inside `pipeline.py` mirroring
  `_gate_blocked_route_recovery`'s `obstacle_stop` counter, driven by a
  runtime-supplied patience value so the *policy* still lives with personality.

Prefer the first: two dwell counters in two trees disagreeing about the same
tick is the D5 defect class, which is exactly what the single
`_release_unreachable_candidate` door was built to avoid. Until one exists,
the runtime's only honest options are the three shipped ones (`ask_for_help`,
`wait`, `give_up_honestly`).

## N21 — Give every personality a numeric temperament block · **DEFERRED after N36/U36 · hours**

`configs/personality.yaml` is the first place a personality carries **numbers**
rather than prompt text, and today it carries exactly one family
(`yield_policy` + `yield_speech`). `docs/ATTENTION_STEERING_DESIGN.md` names
the intended block — continuous 0–1 `sociability`, `reactivity`, `patience`,
`playfulness`, `independence` — and the arbiter already accepts arbitrary
numeric factors (`ReactionSpec.factor_gains`, "Improv exponents, from
temperament"). The per-tick factor vector is still the hardcoded literal
`{"sociability": 0.7, "playfulness": 0.5}` at `runtime.py`'s reaction-bridge
call.

The file, its fail-closed loader, and the `set_personality` re-install path now
exist, so this is wiring rather than design: move the factor vector into
`profiles.<id>.temperament`, derive `yield_policy.patience_s` from the same
`patience` scalar if the sweep in U36 says the mapping is real, and keep
`/api/social` honest about which numbers came from where.

## N22 — Land the system-utterance case in the acoustic pack · **ABSORBED by N37/N42**

`speak_system` (2026-08-09, U35,
[../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md](../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md))
was measured on the `acoustic_loop_v1` **rig module** rather than as a pack
case, because `evals/companion/acoustic_loop_v1` is frozen and adding a case is
not free:

* a new `family` value is refused by `result.schema.json`'s `family` enum, and
  that schema is hash-locked in `manifest.json` (`2551939a24f5ab67…`); and
* filing it under the existing `duplex` family avoids the schema but still
  moves `metrics.duplex.cases` / `responded` and the `case_verdicts`
  determinism object **under an unchanged `runner_version`**, so the two
  retained baseline rows would stop describing the same suite.

The measurement itself is done and repeatable (n=2, 5.27 s / 5.58 s of audio on
the sink monitor, against a silent pre-fix control). What this card buys is
that a regression in the system-utterance path gets caught by the tier-1 gate
instead of by somebody noticing the dog went quiet.

Shape: add a `system_utterance` family (schema enum + its sha in the manifest +
`runner_version` bump to `virtual-pipewire-rig-v2`), one case that drives
`RobotRuntime._brain_vocalize` with `speech.output_device` pointed at the rig
sink and asserts acoustic onset plus a non-trivial peak, and a gate of the form
`system_utterance_audible_rate_min: 1.0`. Re-baseline both retained rows under
the new runner version in the same commit, or the determinism contract is
broken in a second way. The probe body is in the U35 record.

## N-AUDIO-REC — Record the eval audio corpus · **MOVED to B21**

Audio-hardware finding (2026-08-09, coordinator): the workstation has an
**onboard analog mic input** (ALSA `card 1: HD-Audio Generic, ALC1220 Analog`,
Realtek ALC1220 codec) but it is **disabled** (PipeWire card profile = Off, zero
Sources exposed, capture RMS 0.00) and **nothing is plugged into the jack**.
There is **no USB microphone** attached. The planned robot mic is the USB
XVF3800/ReSpeaker array (still to be procured — hardware-last).

To record the PERSONAL_CONVO_V1 human-utterance corpus (the ~12.5% human-vs-TTS
gap; the load-bearing eval stratum), the owner must EITHER:
1. plug a 3.5 mm mic into the onboard jack, run `wpctl set-profile <ALC1220
   card-id> 1` (Analog Duplex) + `wpctl set-default <source-id>` per
   docs/ACOUSTIC_BRINGUP_PLAN.md §5, then record against the committed script at
   `evals/companion/personal_convo_v1/human_recording/SCRIPT.md`; OR
2. attach a USB mic (immediate, enumerates as a PipeWire source with no profile
   dance).

The recording is for EVAL TRUSTWORTHINESS only — it does not make live audio I/O
work (that is the same transducer + `wpctl` activation) and does not fix
barge-in (N16/N17 need real output latency + attenuated echo). The
PERSONAL_CONVO text tier and all synthetic-voice acoustic gates run without it.

---

## N23 — PE-D: freeze `SensorFrameV2` + first rosbag2 replay source · **READY · days**

**Opened:** 2026-08-14 (deferred from REVISED_BOARD; was parallel PE-D).

S-1's support-artifact / CameraInfo / TF / sync truth table is now gated in
software (`S1_STATUS.md`). PE-D may start without waiting on Orin hardware.

- **Build:** simulator-neutral `SensorFrameV2`/`SensorSource` carrying raw
  image+CameraInfo, raw PointCloud2 (unknown vendor fields preserved), IMU,
  source/host clocks + uncertainty, frame ID + TF/calibration digests, typed
  provenance — **no** semantic IDs, true pose or collision truth on the agent
  side. First deterministic rosbag2-MCAP replay adapter through that boundary.
- **Tests:** live-shaped fixture ≡ normalized replay; drop/duplicate/reorder/
  clock-step/missing-TF/bad-calibration/NaN/unknown-field fixtures fail or
  degrade as specified; stale LiDAR never free space; stale camera blocks
  semantic authority; oracle fields refused from agent input.
- **Exit:** `PE_D_STATUS.md` + focused tests. Do not claim localization,
  fusion or navigation improvement.
- **Unblocks:** IS-F producer work once B13's supported host exists.

## N24 — SG-E: W0-C/W0-F gateway contract/fake slice · **LANDED 2026-08-16 · not the complete gateway**

**Opened:** 2026-08-14 (deferred from REVISED_BOARD; required before
Parcel-driven motion, **not** before mounting).

**Landed subset:** strict bounded V1 gateway DTOs, executable RC-4 table plus
W0-B H2 companion derivation, deterministic fake-Sport faults, per-boot epoch/
sequence/local-TTL/stop-epoch substrate, a real separate-process client-`SIGKILL`
stop and restart-disarmed proof, and frozen N24 invariant/failure-seed inventories.
Measured status and exact remaining W0-C/F gates:
[scrum/20260816/task_1/SG_E_STATUS.md](../scrum/20260816/task_1/SG_E_STATUS.md).
N28 remains the native credential-isolated product gateway; N42 remains the shared
`authority-invariants` evaluator/CI owner; B16 remains physical evidence.

- **Slice:** TTL/latency derivation table; versioned gateway DTOs (boot epoch,
  sequence, local TTL, hashes, ack/state/stop); fake Sport service with
  delayed/no-reply Move, stale state, lease loss, writer conflict; process-
  level proof that client death after a nonzero proposal → local stop, never
  auto-resume, restart disarmed. Freeze the gateway invariant list and seeded
  failure fixtures here; N42 owns assembly/evaluator behavior of the shared
  `authority-invariants` CI gate.
- **Do not silently decide B5–B8** (owner 2×2). Fixtures/specs only until
  authorized.
- **Exit:** `SG_E_STATUS.md` naming which subset landed and which W0-C/F gates
  remain. A partial slice is not a gateway.
- **Hard rule:** no motion-auth product change in this card without owner
  2×2; no vendor SDK in `.parcel`.

## N25 — Camera plausibility samples for optical streams · **hours**

**Opened:** 2026-08-14 (DOC-G residual from PS-N does_not_prove #6; was
hidden only in 20260813 status).

- **Defect:** `go2.front_camera` and the four D455 video rows carry
  `ChannelClass.CAMERA`, but live decoders emit **no `ImageSample`**, so
  `camera.non_degenerate` (lens-cap) never fires and those channels report
  `camera.no_measurement → UNKNOWN` all session.
- **Unblock:** emit attributable image/sample frames on the live camera decode
  path (or a documented UNAVAILABLE reason per stream), then seed a lens-cap /
  all-zero frame that reddens the plausibility pin. Fail closed and visible —
  never silence the channel on FAIL (PS-J rule).
- **Does not replace** S-1 CameraInfo/TF GO-RECORD gates; those are orthogonal.

## N26 — Primary rosbag interior-loss attribution · **hours–days**

**Opened:** 2026-08-14 (DOC-G residual; PS-B contrast vs CaptureRecorder).

- **Defect:** a single global sequence stamped before write and incremented
  after means a message never written leaves **no hole**, and one counter
  cannot attribute a hole to a channel. Parcel's SECONDARY `CaptureRecorder`
  path already mints per-channel receipt sequences and burns numbers on
  `drop()` — the primary rosbag2 path does not yet expose equivalent
  attribution.
- **Unblock:** design a per-topic loss ledger for the rosbag2 primary path
  (sidecar or companion artifact) that attributes drops without inventing
  messages; seed a backpressure/truncation case that proves attribution; keep
  fail-closed (unknown ≠ zero loss).
- **Relation:** rehearsal SIGKILL/truncation tests prove bags stay readable;
  they do not prove per-channel interior-loss attribution on the primary path.

---

## N27 — HLD P0: source/package release parity · **LANDED 2026-08-16**

Landed evidence: [N27 release-parity status](../scrum/20260816/task_2/N27_RELEASE_PARITY_STATUS.md).
The current commit gate verifies the generated manifest and all 91 packaged assets.
The original card is retained below as historical scope, not active work.

- **Opened / priority:** 2026-08-16 · P0 release integrity.
- **Depends on:** none; run in parallel with N24.
- **Build:** make canonical config, prompt, skill, schema, and map assets the one
  source for `runtime_assets`; generate a manifest with paths and digests. Remove
  hand-maintained deploy copies. In particular, eliminate the verified navigation
  drift: packaged timeout 400 vs source 200, `max_vx` 0.45 vs 0.9, grid alignment
  28° vs 55°, and missing perception/route-memory/predictive/person-band blocks.
- **Tests / refutation:** zero-diff and digest tests for every packaged tree; build a
  wheel, install it in an empty temporary environment, resolve every default asset,
  and run a source-vs-wheel behavior smoke with identical config hashes.
- **Exit:** CI fails on any source/package drift and the installed wheel reports the
  same effective navigation/prompt/capability configuration as the source checkout.
- **Does not prove:** that any numeric limit is safe on hardware or that the wheel
  has a production sensor/gateway path.

## N28 — HLD P0: complete software gateway and physical-effect authority · **READY for process substrate; integration exit after N29 · days–weeks**

- **Opened / priority:** 2026-08-16 · P0; completion card for N24's contract/fake
  slice, not permission to skip it.
- **Depends on:** N24's landed process/fake substrate; N29 for generated gateway
  validators and immutable safety-envelope integration. B5–B8/B14 may land fixtures/
  specifications in parallel; this card must not silently choose their product
  semantics. Physical promotion is B16.
- **Build:** versioned `RobotGatewayV1`, `GatewayCommandV1`, `ActionRequestV1`,
  `GatewayActionV1`, and `GatewayFeedbackV1`; bounded local IPC; native sole vendor
  writer with peer-credential checks; restart-disarmed boot epoch; sequence/TTL/
  lease/limits/stop/stationary witness; capability-admitting launcher. Route
  allowlisted physical posture and gesture through the gateway's local envelope and
  capability checks. Add one explicit operator-scoped, non-product commissioning/
  fault client for B16. Revoke robot-network/vendor-command access from legacy ROS
  JSON, direct/debug Dog, UI, and Python paths before any HIL motion; N43 later
  becomes the sole product client without changing the gateway protocol.
- **Tests / refutation:** kill/SIGSTOP/restart, prior epoch, duplicate/reordered
  sequence, expiry, malformed/oversized IPC, late Move, lease loss, two writers,
  feedback loss, action cancellation, and command/action conflict. Safety reductions
  bypass comfortable slew and exact zero remains exact at the fake vendor write.
  Generated DTO/version or N29 envelope-ID mismatch hard-refuses at the gateway.
- **Exit:** only the authenticated, capability-scoped commissioning client can reach
  the fake robot service; no product runtime path or other repository path can write
  a physical effect. Client death or TTL expiry stops and restart never auto-resumes.
- **Does not prove:** robot SDK compatibility, physical stopping distance, balance,
  gesture feasibility, or commissioning. Those are B16.

## N29 — HLD P0: strict configuration and capability admission · **READY · days**

- **Opened / priority:** 2026-08-16 · P0 startup truth.
- **Depends on:** none to start; consume N27's landed source/package manifest at
  this card's exit.
- **Build:** a versioned strict root runtime schema with unknown-key rejection,
  migrations, source provenance, and derived configuration. Define capability
  requirements for sensors, frames, calibration, localization, gateway, maps,
  actions, models, and ODD. Validate feature dependencies (for example lock-on
  cannot start without verification-on-approach). Admit local/remote voice and
  inference provider profiles by versioned capability, exact model/version, region,
  data/retention class, codec/session limits, and credential **reference**; secrets
  never enter YAML, manifests, logs, or snapshots. Maintain one compatibility
  registry for gateway, snapshot, authority, action, invariant-lease/admission, and
  telemetry contracts and generate native/Python validators and fixtures. The
  invariant-lease schema carries task/revision, invariant/monitor IDs, issuer class,
  issue/expiry/renewal sequence, capability/envelope hashes, reset obligations, and
  signature; N29 generates schemas/validators, never live lease instances. Produce
  and verify a signed
  release/config/model/map/calibration/capability manifest; physical profiles fail
  closed when incomplete. Derive one immutable, hashed `RobotProfile` ×
  `SpeedRegime` × `SafetyEnvelope` artifact from the effective config; planner,
  N43 governor, gateway, scorer, and telemetry consume that same ID rather than
  re-deriving limits.
- **Tests / refutation:** unknown/inert keys, conflicting duplicated limits, unsafe
  flag combinations, missing capability, mismatched hash/version, uncommissioned
  action, incompatible process versions, tampered/unknown-signing-key manifest, and
  simulator oracle field in a physical profile all refuse startup. A planner/
  governor/gateway envelope-ID mismatch is a hard refusal, not a warning.
- **Exit:** the runtime prints one effective, attributable configuration and cannot
  arm a physical profile with an incomplete or contradictory capability manifest.
- **Does not prove:** the declared capabilities work; commissioning evidence remains
  separate.

## N30 — HLD P1: evidence-enveloped `WorldModel` and revisioned snapshots · **after N23 · days–weeks**

- **Opened / priority:** 2026-08-16 · P1 world-evidence spine.
- **Depends on:** N23 `SensorFrameV2`/replay; N25/N26 strengthen its inputs.
- **Build:** bounded live ROS 2 `SensorSource` adapters for CameraInfo/Image,
  PointCloud2, IMU, TF, controller/`GatewayFeedback`, and timing evidence, plus
  simulator and rosbag replay adapters through the same N23 contract. Add versioned
  evidence envelopes; one `WorldModel` owner for belief/history
  association and immutable `WorldSnapshotV2` projections; a direct bounded
  high-rate `NavigationSnapshotV2` projection for local motion. Preserve capture and
  receive clocks, unique sequence/view identity, frame/transform/calibration
  revisions, covariance, origin, expiry, and source evidence. Physical profiles do
  not expose truth/oracle fields.
- **Tests / refutation:** deterministic replay snapshot hashes; drop/duplicate/
  reorder/clock-step/missing-TF/bad-calibration/NaN fixtures; incompatible revisions
  are detected; the same cached observation cannot become independent evidence;
  ROS discovery/source loss expires the affected projection; persistence,
  association, logging, UI, and GPU stalls cannot block the high-rate projection.
- **Exit:** live-shaped and replay sources produce the same coherent revisioned
  projection; dialogue/planning/semantic verification can cite it while local
  control consumes the bounded direct path. No authority-bearing `extras`/metadata
  field is required. B25 supplies real capture evidence; N43 proves expiry reaches
  the gateway stop chain.
- **Does not prove:** physical perception, localization accuracy, or useful semantic
  beliefs.

## N31 — HLD P1: localization and `T_map_odom` software contract · **after N30 · days**

- **Opened / priority:** 2026-08-16 · unblocked software half of former N15.
- **Depends on:** N30. B8 controls the frozen no-provider behavior change; N31 can
  build the explicit adapters/contract/golden replay before that decision. Physical
  promotion is B17.
- **Build:** timestamped MAP and ODOM poses, `T_map_odom` lookup, covariance/health,
  provider loss, relocalization/jump events, transform epochs, and goal conversion at
  one timestamp. Keep simulator/eval truth as an explicit adapter with pinned
  behavior; specify no-provider as unavailable/unknown rather than synthesized truth,
  and activate that canonical fallback only after B8.
- **Tests / refutation:** golden `map -> odom -> base_link`, yaw/sign/axis cases,
  delayed transforms, provider loss, covariance growth, reanchor jumps, and no local
  command discontinuity from mixing epochs. Pose loss expires positive authority.
- **Exit:** replayed MAP goals reach the ODOM controller only through a healthy
  timestamp-compatible transform, and jump/provider-loss behavior is explicit.
- **Does not prove:** which localizer wins, physical drift, or map quality; B17 owns
  real-bag bake-off and commissioning.

## N32 — HLD P2: committed-turn and command-authority plane · **base after N29 · days**

- **Opened / priority:** 2026-08-16 · P2 interaction authority.
- **Depends on:** N29 version/capability registry. B18 governs the eventual
  principal/enrollment/privacy product policy; use a conservative test principal now.
- **Build:** `CommittedTurnV1` with immutable text/reference, hash, normalization,
  source/epoch and `authority_ref`; `CommandAuthorityV1` with principal, scope,
  expiry/revocation; `TurnDispositionV1` for routed, planning-failed, clarification,
  unsupported, rejected, and admitted outcomes. Add one dialogue-act sequencer:
  “heard/working” is noncommittal and only admitted task events can say started or
  completed.
- **Tests / refutation:** partial/final/correction shuffles, late generations,
  revoked/expired/wrong principals, echo/junk origins, validation rejection before a
  task exists, and concurrent narration. No partial, tool result, or untrusted
  principal can authorize positive motion or claim task completion.
- **Base exit:** every spoken action disposition cites a committed turn and typed
  authority/task outcome; stale narration is discarded by revision.
- **Narration/reference integration after N30/N33/N36:** implement one
  `DialogueNarrator`/reference resolver over exact committed discourse state, a
  compatible `WorldSnapshotV2`, and typed `TaskEventV2` progress. It emits a typed
  resolved referent or clarification—not guessed geometry—and supplies typed task
  state to prompts instead of summary strings. Test pronouns, “there/that one/continue,”
  changed/disappeared entities, conflicting memory, stale task revisions, delayed
  narration, and explanation claims. B29 evaluates human-perceived quality.
- **Does not prove:** speaker recognition, real-microphone authorization, or policy
  consent; those require B18/B15 evidence.

## N33 — HLD P2: one consequential-action task lifecycle · **after N30/N32/N43 · days–weeks**

- **Opened / priority:** 2026-08-16 · P2 executive authority.
- **Depends on:** N30 snapshots, N32 turn authority, and N43 product action admission.
  B23 governs any post-disruption restore; the fail-closed no-auto-resume default is
  implementable before that policy decision.
- **Build:** add `TaskTransactionV2`, then make `plan_sketch_v1` the default and align
  the planner prompt; keep the
  compiler as sole author of resources, success, invariants, retries, and timeouts.
  Replace `max_attempts=1` with system-owned per-skill policy. Add distinct admission,
  grounding, resource-wait, execution, and mission deadlines; certified
  `ControllerCheckpointV1`; durable `TaskEventV2`. N33 is the sole product issuer/
  renewer and monitor owner for lease instances conforming to N29's generated
  per-task/revision invariant-lease schema; N43 only validates/enforces them. Route
  every consequential walk,
  pose, gesture, follow, and navigation request through `TaskExecutive`; keep STOP
  independent. Add task/revision-scoped invariant leases with one monitor registry
  through terminal state. Permit disjoint-resource task concurrency under explicit
  priority/fairness/starvation policy; critical locomotion phases veto conflicting
  overlays/actions. Implement a `BehaviorCoordinator` that routes bounded voice/gaze
  and simulator/decorative-expression reactions with revision/TTL and no locomotion
  ownership. Physical expression stays shadow-only/unsupported unless N28 admits a
  specific `GatewayActionV1` profile; N37 owns speech delivery.
- **Tests / refutation:** recovery is reachable only within budget; resources cannot
  wait forever; delayed step/attempt/revision reports are rejected; only a settled
  controller-certified checkpoint permits replacement/restore; disjoint tasks make
  fair progress, resource conflicts obey priority, critical-phase veto is dominant,
  invariant monitors cannot be replaced by another task/revision, stale reactions
  expire, and no direct consequential action bypass remains.
- **Base exit:** one `TaskTransactionV2` ledger explains admission, ownership,
  progress, correction, pause/resume, cancellation, failure, and completion
  disposition. Before N34, navigation remains non-complete/unsupported at its terminal
  seam; other actions complete only from admitted gateway/controller feedback.
- **Integration gate after N34:** enable navigation `completed` only from a compatible
  `TerminalWitnessV2`. This later gate does not make N34 a predecessor of N33's base
  contract/lifecycle exit.
- **Does not prove:** autonomous mission repair quality or physical action safety.

## N34 — HLD P2: bounded mission repair + typed navigation lifecycle · **after N30/N33 base; integration after N31 · days–weeks**

- **Opened / priority:** 2026-08-16 · P2 closed-loop semantic autonomy.
- **Depends on:** N30 evidence projections and N33's base task transaction/event/
  resource contract for scaffolding; N31's timestamped transform/pose contract is
  required for metric navigation and terminal-witness integration/exit. B5 governs
  the selected pose-error reserve, B22 the remaining `next_to`/region/yield semantics,
  and B23 any post-disruption mission restore.
- **Build:** add `NavigationTaskV2` around unresolved `NavigationIntentV2`, evidence-
  backed `GroundedGoalV2`, and metric `ExecutionGoalV2`. Add `TerminalWitnessV2`
  with a typed completion/termination policy for every supported goal class,
  independent semantic/geometric evidence, pose/covariance reserve, settled
  controller/gateway
  feedback, and explicit `NOT_ARRIVED`/`UNCERTAIN` outcomes. Continuous moving-
  formation tasks never reuse arrival; they end only by their explicit task condition,
  cancellation, expiry, identity loss, or failure. Build a deterministic-first
  `MissionSupervisor` with shared budgets for
  attempts, replans, time, distance, energy, and model calls. Split navigation into
  the typed stages above; stop reparsing validated free text. Consume typed blocked
  causes and choose deterministic retry/scan/alternate approach or instance, bounded
  plan revision, clarification, or honest termination. Every model revision
  recompiles and revalidates against a compatible fresh snapshot and certified
  checkpoint.
- **Tests / refutation:** changed-world, ambiguous referent, target absence, exhausted
  local recovery, late model repair, correction during planning, and nested-budget
  double-spend cases; every finite point/region/relation goal has positive, negative,
  stale, correlated-evidence, pose-error, and unsettled-feedback terminal cases, and
  continuous formation cannot report arrival. Text is audit/explanation data, not
  the downstream control contract.
- **Exit:** an admitted mission can recover or explain why it cannot without an LLM
  entering a control loop or waiving an invariant, and no goal class can report
  success without a compatible `TerminalWitnessV2`.
- **Does not prove:** grounding accuracy, navigation success, or physical autonomy.

## N35 — HLD P2: inference broker and bounded read-only tool synthesis · **after N29 · days**

- **Opened / priority:** 2026-08-16 · P2 model fault isolation.
- **Depends on:** N29 model/config identity. Integrates with N32/N34 when available.
- **Build — N35-A text/model provider registry:** replace front-door-specific model
  construction with one registry used by web, CLI, and ROS. Add versioned
  `ConversationProviderV1`/`PlanningProviderV1` lifecycle, capabilities, health,
  model/config/region identity, structured text/tool proposal events, and generation
  fencing. Then add role-scoped queues/endpoints for conversation, planning, summarization,
  embeddings, and perception; per-role deadlines, cancellation, concurrency, circuit
  breaker, overload disposition, hashes, budgets, and one bounded structured-output
  repair. Add a maximum-two-pass read-only tool loop (select, then grounded synthesis)
  with source/trust labels. Local inference is the first-ODD default; remote use is
  optional, privacy-governed, and never a safety dependency.
- **Tests / refutation:** conversation cancellation cannot cancel planning or memory;
  saturation/OOM/timeout/fallback leaves the control trace unchanged; tool prompt
  injection, stale results, excess calls, and physical-truth/authority claims are
  refused.
- **Exit:** each model role has independent lifecycle and measured overload behavior;
  deterministic closed intents/tasks remain available without inference.
- **Does not prove:** model quality or acceptable human-perceived latency.

## N36 — HLD P2: governed conversational, episodic, profile, and spatial memory · **after N30/N35/N32 base · days–weeks**

- **Opened / priority:** 2026-08-16 · P2 continuity/privacy.
- **Depends on:** N30 world evidence, N35 inference isolation, and N32's base
  committed-turn schema. B18 supplies the owner consent/retention policy before
  promotion.
- **Build:** query-aware deadline-bounded retrieval; asynchronous writes,
  summarization, distillation, and indexing; separate working dialogue, episodic
  task, explicit owner profile, and evidence-backed spatial/semantic stores. Add
  confidence, source, frame/revision, expiry, edit/export/delete, retention, and a
  logging/memory kill switch. Model-proposed profile facts require deterministic
  policy; model text can never establish a physical fact. Expose committed discourse
  references and typed retrieval results to N32's resolver without copying current
  world/task truth into a second mutable store.
- **Tests / refutation:** actual current query reaches retrieval; timeout degrades to
  no memory; session separation; stale/contradicted spatial belief; consent revoke;
  delete/export; poisoned summary; synchronous summarization cannot delay response or
  control.
- **Exit:** memory improves a held-out follow-up only when its cited source remains
  valid, and privacy controls deterministically remove it.
- **Does not prove:** human personalization quality or long-term field correctness.

## N37 — HLD P2: real-time voice interaction software lane · **after N32 · days**

- **Opened / priority:** 2026-08-16 · P2 acoustic software; absorbs the open software
  surface of N16/N17/N18/N22.
- **Depends on:** N32 turn authority. Queue/ducking/partial-ASR work can land without
  N35; model-backed ASR scheduling must use N35 when integrated. Real acoustic/AEC
  tuning remains B3+B15; human corpus recording is B21.
- **Build — N37-A voice/media provider contracts:** add `AudioFormatV1`,
  `AudioFrameV1`, `ProviderCapabilitiesV1`, `StreamingRecognizerV1`,
  `StreamingSynthesizerV1`, and an optional `ManagedVoiceSessionAdapterV1` over one
  normalized PCM/media boundary. Managed adapters emit only transcript, reply/audio,
  usage/fault, and tool **proposal** events into N32; they never execute robot tools
  or mint authority. Require sequence/generation fencing, exactly one terminal event,
  bounded backpressure, cancel acknowledgement/no post-cancel audio, codec/rate/
  channel normalization, and shared adapter conformance tests. Also build the
  priority-aware system speech queue, duck/restore, audible-start
  disposition, capture identity, streaming partial-ASR adapter for display/
  preparation/interruption only, and an AEC stage interface. Preserve final-only
  physical authorization. Filter typed non-speech markers and carry echo/playback
  evidence without guessing real-device thresholds.
- **Tests / refutation:** busy-speaker safety message, superseded filler, partial
  emergency lookahead without execution, echo/junk origin, queue overload, AEC
  absent/degraded, and zero changes to model-off motion traces.
- **Exit:** the software path cannot lose a priority system utterance or execute a
  partial; through-air gates are ready to run unchanged when B3/B15 unblock them.
- **Does not prove:** AEC, real barge-in, speaker authorization, or audible hardware.

## N38 — HLD P3: evidence-safe perception and identity-locked owner belief · **after N30/N31 · weeks**

- **Opened / priority:** 2026-08-16 · P3 identity-safe following.
- **Depends on:** N30 evidence identity and N31 transforms. B18 owns enrollment,
  consent, and identity-retention policy; B7 governs any search rotation. Physical
  promotion is B26 after B17/B25, and follow translation also needs N39/N43.
- **Build:** live/replay camera/depth/LiDAR detector/tracker adapters with unique capture
  identity and independence groups (time, view/parallax, source/model correlation,
  track lineage). Add `OwnerBeliefV1`: enrolled identity, LOCKED/OCCLUDED/SEARCHING/
  AMBIGUOUS/LOST, covariance, expiry, and evidence. Only healthy LOCKED permits first-
  ODD translation; no nearest-person fallback. Search rotation is a separate admitted
  sensing intent; occlusion does not authorize predicted translation.
- **Tests / refutation:** cached-frame replay cannot satisfy M-of-N or arrival;
  twins/crossing tracks/occlusion/reappearance/stranger-nearer cases; stale or
  ambiguous belief holds; identity never changes without enrollment authority.
- **Exit:** held-out replay maintains owner identity or stops/clarifies honestly, with
  every state transition attributable to independent evidence.
- **Does not prove:** physical re-ID quality, crowd comfort, or follow success.

## N39 — HLD P3: behavior-scoped goals, moving formation, social recovery, and shadow challengers · **after N31/N34/N44 · weeks**

- **Opened / priority:** 2026-08-16 · P3 deterministic navigation baseline.
- **Depends on:** N31 transforms, N34 typed goal/mission contract, and N44's
  fail-closed observed-space baseline. N38 is required for the identity-aware moving-
  formation integration exit; generic GoalManager/social fixtures can start earlier.
  Product promotion is conditioned on B6/B7; specs/replay work can begin before those
  decisions.
- **Build:** task/preemption selects the behavior owner, then a behavior-scoped
  `GoalManager` consumes typed `GoalProposalV2` from system-calibrated route-memory,
  exploration, recovery, and operator sources; proposal fields never self-assert
  priority/confidence/capability. Preserve a distinct versioned moving-formation
  contract with owner-band/side/behind geometry, identity/covariance/occlusion state,
  and freshness rather than turning it into static waypoint churn. Add uncertainty-
  aware people tracks, social bands, yield/pass choices, and cause-aware recovery.
  Local micro-recovery and mission repair share one budget ledger and typed blocked
  causes; no blind reverse. Evaluate regulated tracking and MPPI/learned trajectory
  challengers in shadow/replay only against N44's deterministic baseline.
- **Tests / refutation:** singleton/proposer competition, calibrated-confidence
  attacks, stale revision/TTL, crossing people, owner occlusion/ambiguity, changing
  formation side, yield/pass deadlock, unknown-space deadlock, frontier/recovery
  bypass, planner unavailable, and budget exhaustion. Challenger output cannot
  actuate or weaken a constraint.
- **Exit:** every goal proposal and translation candidate cites task/revision, goal
  owner, transform/envelope, evidence, and expiry; moving formation remains identity-
  and uncertainty-aware; failure degrades to HOLD/blocked; challengers publish paired
  deltas without actuation authority.
- **Does not prove:** global localization, physical clearance, or learned superiority.

## N40 — HLD P3: map-versioned spatial memory and geofence/traversability constraints · **after N31/N39 · weeks**

- **Opened / priority:** 2026-08-16 · P3 spatial continuity and hard environment
  constraints.
- **Depends on:** N31 localization and N39 local baseline. B5/B6/B7/B17/B19 and
  applicable B22 decisions gate physical promotion.
- **Build:** persist semantic/place nodes against map/submap IDs, transform revisions,
  covariance, evidence, and change history; route memory proposes topology but never
  free space. Produce signed, revisioned private-ODD geofence/road/terrain constraints
  at goal/corridor connected-component admission and for planner/final-governor
  consumers; N43/N41 alone compose/enforce the final command constraint. Add
  elevation, curb/stair/drainage/drop-off/traversability evidence and capability
  requirements. Crossing stays disabled in the first ODD.
- **Tests / refutation:** loop closure/reanchor invalidation, moved landmark/blocked
  edge, stale map, off-road goal whose corridor crosses a road, localization
  covariance touching a geofence, negative obstacle, missing low-viewpoint evidence,
  and route memory facing a new obstacle.
- **Exit:** remembered topology can improve a route but cannot authorize current
  geometry, terminal success, a keepout crossing, or unsupported terrain.
- **Does not prove:** physical negative-obstacle/drop-off sensing, geofence or
  terminal/collision enforcement, or outdoor/stair/public-road capability; B28 owns
  bounded robot evidence.

## N41 — HLD P3: migrate local navigation into the N43 sidecar · **after N39/N43 · weeks**

- **Opened / priority:** 2026-08-16 · P3 timing/fault isolation; completion of N43,
  not a second client or governor.
- **Depends on:** N39 behavior baseline and N43's already-sole product gateway client.
- **Build:** move deadline-critical 20–50 Hz local maps, people tracking, route
  tracking, micro-recovery candidate generation, and deterministic controller into
  the existing N43 C++/ROS 2/native process. Preserve N43's `MotionCandidateV2` →
  `SafetyDispositionV1` → gateway authority boundary and client identity. The current
  Python grid/controller remains a replay rollback baseline.
- **Tests / refutation:** deterministic Python-vs-sidecar replay, latency tails,
  process kill/stall/restart, ROS discovery loss, logger/GPU/UI failure, snapshot
  expiry, malformed candidate/action, envelope reduction, and rollback. These are
  fake/replay tests; B27 owns the post-migration physical kill/TTL/stopping rerun.
- **Exit:** local navigation deadlines and the unchanged N43 safety/gateway lease are
  independent of Python interaction/model/storage liveness, with an equivalent
  deterministic rollback trace and no client handover at promotion.
- **Does not prove:** real sensor latency, robot stopping, or public safety.

## N42 — HLD cross-cutting: causal observability, refutation, and promotion ledger · **READY in slices · days–weeks**

- **Opened / priority:** 2026-08-16 · P0–P4 evidence plane; absorbs N19's runtime
  fan-in and provides the versioned evaluation home for N22.
- **Depends on:** none for the base envelope/recorder/runner. Full-chain exit depends
  on N28/N30/N32/N33/N34/N43; each producer card owns its typed adapter while N42
  owns the shared schema, recorder, runner, and promotion ledger.
- **P0 promotion checkpoint:** the base recorder does not close Phase 0. Its promotion
  row closes only after N27/N28/N29, B16's bounded hardware evidence, and implemented/
  re-frozen B5–B8/B14 decisions for every enabled capability all cite compatible
  release/capability hashes. Early single-axis B16 may still run with excluded
  capabilities disabled.
- **Build:** one causal envelope from release/run/session/turn/generation through
  task/revision/step/attempt, world/evidence sequence, goal/motion/action candidate,
  safety disposition, gateway epoch/sequence/feedback, and terminal witness. Include
  config/model/map/calibration/capability hashes and monotonic/wall mapping. Move all
  serialization/rotation/storage to bounded nonblocking queues with drop accounting;
  the gateway retains only its local command/action/fault ring. Add the
  `authority-invariants` CI/refutation gate, contract compatibility/fuzzing, product
  scorecard, evidence-dated capability matrix, evidence ladder, confidence intervals,
  and `does_not_prove` fields. Make the durable docs index point to this HLD/current
  executable evidence, banner obsolete snapshots as historical, and validate backlog
  IDs plus local links as part of the docs gate. Build the preregistered, blinded
  held-out human companion-review protocol/harness for coherence/helpfulness,
  correction/reference accuracy, interruption, explanation truth, memory
  correctness/forgetting, and comfort; B29 owns participant/reviewer execution.
  Automated parsing/safety packs remain separate.
  **N42-A provider comparison:** add normalized provider/model/config/region/session/
  request, usage, cost, latency, cancel, and fault fields to the causal envelope and
  a versioned `evals/companion/provider_swap_v1/` runner. The credential-free fake/
  recorded-replay lane may gate CI; credentialed and live-microphone/chassis lanes
  report separately. Use the hard gates and scorecard in
  [VOICE_PROVIDER_ARCHITECTURE.md](../docs/VOICE_PROVIDER_ARCHITECTURE.md), preserve
  exact endpoint manifests, and report invoice per committed turn and successful
  task rather than a component price alone.
- **Tests / refutation:** logger/storage failure changes no control bytes; causal IDs
  reject mismatched revisions; seeded hard-gate/evaluator failure makes the runner
  nonzero; kill/clock/drop/reorder campaigns reproduce from a pinned manifest;
  unique backlog IDs and local doc links validate. Refresh stale `docs/CI.md` counts
  without claiming hosted CI (B20).
- **Exit:** the base slice proves nonblocking recording and seeded evaluator failure;
  the full-chain gate then requires every refusal, clamp, retry, correction, action,
  and terminal claim to replay to its evidence and release manifest. The human-review
  harness is deterministic and versioned; B29 results are reported separately. Hard
  safety cannot be averaged away by task/conversation scores.
- **Does not prove:** hosted CI, HIL, acoustic hardware, or first-ODD readiness.

## N43 — HLD P1: sole product actuation-admission client and final governor · **after N28/N29/N30 · days–weeks**

- **Opened / priority:** 2026-08-16 · P1 deadline/failure isolation, promoted ahead
  of advanced navigation so the Phase-1 stop chain is testable.
- **Depends on:** N28 gateway protocol/process, N29 compatibility/capability
  admission, and N30 bounded `NavigationSnapshotV2`/controller feedback.
- **Build:** a minimal deterministic C++/ROS 2/native actuation-admission process that
  is the sole product `RobotGatewayV1` client. It accepts untrusted
  `MotionCandidateV2`/`ActionRequestV1`, validates task/revision/snapshot/transform/
  envelope ID/TTL/capability/invariant leases, composes axis/lifecycle constraints,
  and emits typed
  `SafetyDispositionV1` plus `GatewayCommandV1`/`GatewayActionV1`. The final governor
  may preserve or reduce a candidate but never increase an axis; HOLD/STOP are exact
  zero and bypass comfort smoothing. Commissioning and product credentials/profiles
  are mutually exclusive, so N28's temporary client cannot become a second writer.
  For pre-N33 HIL only, also build a test-only `HilSessionV1` fixture emitter using
  the N29-generated schemas. It mints signed, short-lived task/revision/candidate IDs
  plus a bounded metric test-goal ID and narrowly scoped invariant leases under an
  operator-approved one-axis/course manifest; it has no gateway socket/credential,
  is absent/refused in product
  profiles, and does not replace N33 as the sole product lease issuer/monitor owner.
- **Tests / refutation:** stale/mixed revision, missing/malformed candidate/action,
  lifecycle loss, expiry, stop dominance, nonzero CLAMP after shaping, and independent
  exact-zero finalization. Kill/stall ROS sources so evidence authority expires,
  positive refresh ceases, and the gateway TTL stops; separately kill GPU, Python
  models, UI, logger, and storage and prove the admitted control/gateway path remains
  deadline-bounded. Include process kill/restart and credential/writer-conflict cases.
  Expired, overbroad, wrong-envelope, wrong-revision, unsigned, or product-profile
  `HilSessionV1`/test leases must be rejected.
- **Exit:** the Phase-1 chain `source loss -> snapshot expiry -> no positive refresh
  -> gateway TTL stop` is deterministic, and no Python/model/UI/storage process is a
  product motion writer or a liveness dependency. N41 can move local maps/controller
  into this same process without changing client identity or final safety ownership.
- **Does not prove:** physical sensor timing, braking distance, navigation quality, or
  action feasibility; B16 proves the gateway commissioning client, B30 the N43
  product-client TTL/stop chain, and B27 the post-N41 navigation rerun.

## N44 — HLD P1/P3: fail-closed observed-space local-planning substrate · **after N29/N30/N31 · days–weeks**

- **Opened / priority:** 2026-08-16 · early safety substrate extracted from N39 so a
  malformed scan cannot wait on the conversational mission stack.
- **Depends on:** N29's immutable safety-envelope artifact, N30 navigation snapshots,
  and N31 transforms for the substrate; N43 is required for the monotonic final-
  admission integration/exit. B6/B7 govern promoted directional-collision and
  sensing-rotation semantics; fixtures can land first.
- **Build:** unify grid/reactive validity for missing, stale, malformed, wrong-frame,
  future, uncalibrated, and NaN scans; invalid evidence yields typed exact HOLD. Add
  the deterministic observed-first receding-horizon baseline: execute only to the
  furthest currently observed/reachable frontier, reobserve, and preserve the true
  goal. Consume the same N29 envelope ID as N43/gateway/scorer; never re-derive
  footprint or limits. Route every translation-bearing local/recovery frontier
  through this seam;
  prohibit point-goal and blind-reverse fallbacks. Keep the current Python path as
  the replay baseline until N41 migration.
- **Tests / refutation:** every invalid-input class and axis; unknown-space deadlock;
  cached-frame, frontier, micro-recovery, direct-follow, and route-memory bypass;
  transform epoch change; planner unavailable; and stop/clamp monotonicity through
  N43. Mutants that reinterpret unknown as free or bypass the planner must be killed.
- **Exit:** all translation candidates cite fresh observed free space and a compatible
  transform/snapshot or become HOLD/blocked; no conversational/task feature is needed
  to exercise this contract.
- **Does not prove:** physical clearance, directional-collision policy, social
  navigation, global localization, or learned-planner superiority; B31 owns the
  bounded physical observed-space/static-obstacle rung.

## N45 — R28 successor: semantic-arrival reliability across shipped object classes · **READY · days**

- **Opened / priority:** 2026-08-21 · P0 regression closure; durable owner for the
  R26 hard-nightly finding formerly filed only as “R28”.
- **Depends on:** none to reproduce. Any policy change that touches B5 terminal
  truth remains owner-gated; a defect fix must preserve honest refusal/failure.
- **Build:** reconcile approach goals, near-band geometry, semantic completion,
  and terminal verification for lamppost, planter, door, bench, and tree without
  weakening collision or arrival truth. Fix the shared product seam rather than
  special-casing the flagship test or reshaping the scene to fit a predicate.
- **Tests / refutation:** start from the currently RED slow test
  `test_go_to_the_lamppost_grounds_plans_and_arrives`; add a table-driven case for
  every shipped object class plus wrong-instance, unreachable, stale-evidence,
  and false-arrival mutations. Re-run the full slow voice-nav tier and require
  no semantic-arrival failure to be hidden as success.
- **Exit:** the current lamppost reproducer and the shipped-class matrix pass with
  independent terminal evidence, while false-arrival and collision invariants
  remain green. Record before/after geometry and denominators.
- **Does not prove:** physical localization, outdoor perception, or arrival on a
  Go2; this closes simulator product-path semantics only.

## N46 — Current navigation baseline re-freeze and follow-bench rerun · **AFTER N45 · days**

- **Opened / priority:** 2026-08-21 · evaluation integrity; restores ownership
  lost when the planned “R27 baseline re-freeze” identifier was used by the
  owner-store-isolation card instead.
- **Depends on:** N45, so the known hard-nightly arrival defect is not normalized
  into a fresh baseline. Any safety-relevant value change follows the repository's
  attribution/re-freeze policy.
- **Build:** rerun the current nav-instruct candidate/frozen-baseline protocol and
  follow-bench on one pinned tree/config/scene/model manifest; compare against the
  existing ledgers; update pins only with explicit provenance and a value-change
  rationale.
- **Tests / refutation:** artifact digest and manifest closure, repeatability,
  frozen-input drift, collision/false-arrival/jerk regressions, and a seeded stale
  result that must be rejected by the gate.
- **Exit:** one reproducible current-stack baseline and follow-bench row are
  committed with denominators, hashes, confidence/variance where applicable, and
  explicit `does_not_prove`; every affected gate is green.
- **Does not prove:** physical navigation quality, generalization, or superiority
  over an external benchmark.
