# Next up

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Unblocked work, ranked by impact per effort. Nothing here waits on hardware,
an install, or a decision — it can start now. Roadmap rationale lives in
[../docs/RESEARCH_2026_ROADMAPS.md](../docs/RESEARCH_2026_ROADMAPS.md).

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

## N10 — Kickoff board K0–K2′ of the adjudicated program plan · **hours–days** · supersedes ad-hoc sequencing

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

## N11 — Traffic-aware goal placement + yield-advance pacing · **FINAL-APPROACH HALF CLOSED 2026-08-07** · traffic xfail still did NOT flip

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

## N13 — "sit next to X" never sits · **CLOSED FOR THE LAMPPOST 2026-08-07; the bench is a K0/sidecar decision, not a nav defect**

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

## N15 — The localization seam has no `map` → `odom` transform · **days** · blocked on a real localizer

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

## N16 — Barge-in keeps talking for ~0.6 s after it stops · **hours** · found by acoustic_loop_v1

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

## N17 — Echo guard fragments the neural VAD's input · **hours** · found by acoustic_loop_v1

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

## N18 — Owner-gated acoustic cards · **blocked on B3** · runbook is written

Four cards are fully prepared and cannot be gated without a transducer:
`device-activation-snapshot`, `acoustic-hello-smoke`
(`scripts/acoustic_smoke.sh`), `aec-l0-pipewire` (config drafted, needs node
names from the snapshot), and the Tier-2 `doubletalk-operating-curve`. Exact
commands, expected output and gates:
[../docs/ACOUSTIC_BRINGUP_PLAN.md](../docs/ACOUSTIC_BRINGUP_PLAN.md) §5.

Nothing here needs re-derivation — it needs a mic plugged in.

## N19 — Fan the acoustic clocks into the latency ledger · **hours** · runtime lane

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

## N5 — Extend the BARN harness to all 300 public worlds · **days**

Today's honest 2%→44% figure is from a 50-world proxy subset. Running the full
public set produces an externally comparable score distribution with zero ROS
work — the cheapest step toward the primary external benchmark.

## N7 — Emote YAML schema upgrade · **week** · reduces U10 risk · absorbs the intensity no-op

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

## N9 — Self-run Follow-Bench comparison · **1–2 weeks**

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

## N21 — Give every personality a numeric temperament block · **hours**

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

## N22 — Land the system-utterance case in the acoustic pack · **hours** · needs a runner_version bump

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

## N-AUDIO-REC — Record the eval audio corpus (OWNER, hardware-gated) · **owner task**

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
