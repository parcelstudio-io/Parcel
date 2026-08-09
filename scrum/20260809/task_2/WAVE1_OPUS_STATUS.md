# Wave 1 · Opus lane — status (2026-08-09)

Executor: Claude Opus. Five cards from the approved gap-closure plan
(`scrum/20260809/task_1/README.md`), all landed. Ran concurrently with the
search-reground executor (owns `instructnav_recovery.py` + the scan/re-ground
block of `pipeline.py`) and an emotion/gesture lane (owns `runtime.py`'s
social-affect path, `test_runtime.py`, personalities, `collision.py` config).

Default suite after all five cards: **2956 passed / 3 failed / 2 skipped**
(`pytest -m 'not slow'`, stable order). The 3 red are proven **outside my
files** — see "Concurrent-lane red" below. My changes add **0** new failures.

---

## CARD near-band-inset (audit #2 blocker) — DONE

**Defect (measured live, before):** plain `go to the lamppost` walks to the
right object (`lamp_post_1`) and declares `semantic_arrival_verification_failed`
3/3. Two root causes, both found by live instrumentation, not the audit's
single one:

1. The F-1 inset shape (plan the approach pose INSIDE the arrival band so the
   controller's stop still lands in it) had been applied to `next_to` and never
   to `near`. The lamppost's `stand_off_m` metadata (1.32 m) is the band's
   OUTER edge (vicinity 1.38 m − arrival 0.06 m), so any settle overshoot landed
   outside the verify max.
2. The K0 `near` band is a full **annulus**, but the valid stand region is
   `band ∩ support_polygon` (the sidewalk the lamppost stands on). The
   annulus arrival trigger (`_inside_arrival_goal_region`) fired the instant the
   robot crossed the band from the OFF-sidewalk (south) side — at (0.28, 1.78),
   1.37 m from centre, geometrically in-band but 0.42 m OFF the sidewalk — where
   `_semantic_arrival_verified`'s support-polygon check then failed. After
   adding the support gate, the robot reached the sidewalk but was not facing
   the anchor → `target_not_resighted`.

**Fix (files):**
- `navigation/approach.py`: new `_near_planning_band()` mirrors
  `_next_to_planning_band` — insets BOTH near-band edges by
  `arrival_radius + stand_off_margin` and clamps the planned stand-off inside.
  Lamppost pose moves 1.32 m (outer edge) → **1.28 m (band centre)**; a razor-thin
  band whose two inset edges collapse to the midpoint is treated as one
  admissible ring, not empty. Narrowing only; K0 authority unchanged.
- `navigation/pipeline.py`: the `near` arrival TRIGGER now requires
  `band ∩ support_polygon` AND the target re-sighted (same predicate the
  terminal verification uses — factored into `_on_support_surface()` and
  `_resight_committed_candidate()`, so trigger and verify read one definition).
  This is what lets the robot finish the approach and its terminal heading
  align before verifying. Also added `arrival_not_verified_reason` diagnostic
  tags at every verification False-return (observability; behaviour-preserving).

**Before/after (distance-outside-band, plain `go to the lamppost`):**
- before: pose at outer edge 1.32 m, worst outward stop 1.38 m == vicinity;
  live stop landed off-sidewalk → `semantic_arrival_verification_failed` 3/3.
- after: arrives at ~(1.36, 2.61), **1.27 m from the lamppost — INSIDE the
  [1.18, 1.38] band AND on the sidewalk, distance-outside-band = 0.00**,
  `arrival_trigger=goal_region`, `terminal_relation_verified=True`,
  `reason=arrived_verified`.

**Live (MUJOCO_GL=egl):**
- `test_go_to_the_lamppost_grounds_plans_and_arrives` (NEW): arrived_verified in
  **3 of 4** runs; the 4th ended `navigation_no_progress` during the
  **pre-translation opening full-turn scan** (~24 s at spawn) — the audit's
  SEPARATE SEAMLESSLY blocker, owned by search-reground (`_step_scan_behavior`)
  + seamless-pacing, NOT the near-band arrival. The test is pinned honestly: it
  asserts `semantic_arrival_verification_failed` is **never** the terminal
  reason, and arrived_verified on completion; it tolerates the scan stall
  (see HANDOFF). Passed live in its final robust form.
- `test_find_the_nearest_lamppost` (touched): PASSED live. I initially
  strengthened it to also assert K0 arrival, but that surfaced the same
  scan-phase `navigation_no_progress` on the superlative path, so I reverted to
  the original movement-only assertions (my binding gate is "stay green"; the
  arrival proof lives in the plain go-to case).
- `test_run_to_the_nearest_lamppost`, `test_walk_towards_the_lamppost`,
  `test_sit_next_to_the_lamppost`: PASSED live (no regression from the trigger
  change; near/next_to/towards all green).

**Unit:** `tests/test_next_to_approach_geometry.py` +10 pure-geometry pins
proving the near planner band == the verified band inset (one band), the
lamppost band collapses to its midpoint, and every pose the controller may stop
at is inside the verified band.

---

## CARD n20-person-release — DONE

`DirectiveNavigator.release_current_candidate(reason) -> bool`
(`navigation/pipeline.py`) drives the EXISTING single release door
(`_release_unreachable_candidate`) — same exclusion set + replan budget A\*, the
obstacle gate, and the approach solver share, so no second person-stop dwell
counter (the D5 rule). Returns True when the mission continues (replan budget
had room), False when the ladder is spent (honest end).

Runtime wiring (`runtime.py::_yield_release_and_replan`, called from
`_act_on_yield_decision` BEFORE the give-up line is spoken — saying "I couldn't
get there" and then continuing would be the finality lie the yield rules
forbid): on a yield give-up, offer the release; if it continues, reset the yield
tracker and look for another approach; else the honest end stands.
`person_stop` is untouched as a motion gate.

**Tests (`tests/test_yield_policy.py`, +6):** navigation entry point (release via
the single door + replan + exclusion; commits the alternate; returns False when
the ladder is spent; no-op without a committed target) and the runtime seam
(give-up releases and replans instead of ending; the honest-end branch still
ends honestly) — with `vx == 0.0` asserted on every gated tick throughout.
100 passed (yield + unroutable). Traffic e2e xfail reason updated (N20 landed;
stays xfail on U35 / stratum-3 — a pedestrian STREAM blocks every alternative
approach). `backlog/NEXT.md` N20 flipped to LANDED.

---

## CARD no-llm-honesty — DONE

`brain/router.py::split_compound_clauses()` (uses the same `_COMPOUND` grammar
the router routes on). Two no-planner dead-ends fixed in `agent.py`:

(a) A compound that reaches the single-skill navigation parser WITHOUT a planner
would compile the whole conjunction as one literal destination label
("go to the sidewalk and then sit" → search for a nonexistent "sidewalk and
then sit" entity). Now intercepted at the nav-parser site (narrow: only
compounds that actually parse as a directive; "sit then sprint" returns None and
stays with the conversation lane) → clarify, naming the two clauses, never the
literal query.

(b) Goal-amend without a planner no longer pauses forever behind
`deferred_no_planner`. `_goal_amend_without_planner`: a concrete replacement
("actually, go to the lamppost") retargets deterministically through the local
sketch lane (`local_retarget_no_planner`); an anaphoric one ("the other one",
"the same") takes an HONEST, non-hanging reply (`no_planner_honest`).

**Pins (`tests/test_closed_intent_product_path.py`, +5, +1 updated;
`tests/test_p2_dialogue.py` +1 updated):** compound clarifies / never compiles a
literal NavigateTo; retarget admits a NavigateTo; honest reply mentions the
planner and never claims a revision is underway.

---

## CARD llm-lane-dead-ends — DONE

(a) The conversation-lane "Unknown proposed skill: navigate" validator string
never reaches the owner: `agent._execute` translates it to a clarify. (The
preferred re-route-to-NavigateTo is unreachable in practice — the router sends
every nav-parseable turn to `direct_skill` before the LLM lane — so I kept the
clarify safety-net and dropped the dead re-route branch.)

(b) Polite question-shaped motion requests now reach navigation:
`navigation/goals.py` adds gait verbs (`trot/jog/scoot/…`) to the destination
grammar and `mind` to the polite prefix, and `router._PHYSICAL_CUE` learns the
same verbs. "would you mind trotting over to the lamppost?" →
**direct_skill → NavigateTo** (goal near/lamppost). A polite NON-motion question
("would you mind telling me a story?") stays conversational.

**Pins (`tests/test_closed_intent_product_path.py`):** the polite trot/jog/scoot
requests start NavigateTo; the non-motion question does not manufacture
navigation; and a fake conversation model proposing the stripped `navigate` tool
gets a clarify — the raw validator string is asserted never to appear.

---

## CARD pedestrian-evidence-refresh — DONE

Re-ran `evals/companion_nav/run_follow_bench_v1.py --scenario all --features
shipped` on the current tree (post F-1 / surface-band / yield-policy). Ledger
**appended** (frozen 4 rows byte-identical, `git diff` shows only a `+` line):

```
utc 2026-08-09T09:45:11  features shipped
hard_collision_total 0   follow_success 9/9   navigate_success 2/2
mean_band_fraction 0.7433   mean_rms_commanded_jerk_mps3 0.6025
```

**follow_success flipped 8/9 → 9/9** (all nine follow scenarios pass now);
hard collisions still 0; jerk essentially unchanged (0.553 → 0.6025).

The **duplex mirror pin** (8/9 vs live 9/9) WAS still mismatched — re-pinned
honestly: `evals/companion/duplex_v1/run_duplex_v1.py` `FOLLOW_BENCH_POST_SPEED`
now tracks the fresh 9/9 latest-shipped row. `tests/test_duplex_v1.py` 3/3 green.
`evals/companion_nav/results/README.md` row appended.

---

## Concurrent-lane red (proven outside my files)

Isolated via neutralization (each fails with my near-band change disabled) and
`git diff` authorship:

1. `test_dynamic_layer::test_the_collision_gate_behaviour_is_untouched_on_this_branch`
   — `CollisionPolicy` gained fields (person_slow_m, obstacle_stop_m, …).
   `collision.py` is **unchanged by me** (`git diff` empty); a config/authority
   change by another lane.
2. `test_embodied_plan_eval::test_full_gate_executes_physics…` — the frozen
   `simulator_step_count` (1250) moved (region-instance / collision changes).
   Fails with my change **neutralized** too. All five cases still pass
   (`failed_case_count 0`); only the frozen count assertion is red.
3. `test_embodied_plan_eval::test_correction_waits_for_checkpoint…` — same
   concurrent frozen-count / checkpoint drift; fails with my change neutralized.

A one-line literal-drift red I DID contribute (a new `0.32` in
`_inside_arrival_goal_region`) is already resolved — the support check is
factored into `_on_support_surface` (net −1 literal); the remaining
`test_no_new_retired_family_literals` `0.35` drift is the concurrent scan block's
and is no longer in the failure set.

---

## HANDOFFS to the search-reground executor

- **Opening full-turn scan trips `navigation_no_progress`.** Plain
  `go to the lamppost` spends ~24 s rotating in place at spawn before any
  translation (`_step_scan_behavior`, your block ~1558–2078). In 1 of 4 live
  runs the progress watchdog fired during that pre-translation scan and the
  mission ended `navigation_no_progress` — the ONLY reason `go_to_the_lamppost`
  does not arrive 4/4. My near-band arrival fix is complete and proven
  (arrived_verified, inside band, on sidewalk); this residual is your scan block
  + the seamless-pacing card. My e2e pins it honestly (tolerates the scan stall,
  never the near-band failure).
- **Shared `pipeline.py`.** My edits are in the arrival/verification/release
  methods (`_semantic_arrival_verified` ~2760, `_on_support_surface`,
  `_resight_committed_candidate`, `_inside_arrival_goal_region` ~3030,
  `_release_unreachable_candidate` neighbourhood ~2600) and
  `_build_arrival_goal_region` metadata (`support_polygon` already flowed).
  None overlap your scan/re-ground block. Watch for merge on the shared file.

## Files touched (mine)

`src/parcel_robot/navigation/approach.py`, `.../pipeline.py` (shared),
`.../goals.py`, `src/parcel_robot/brain/router.py`, `src/parcel_robot/agent.py`,
`src/parcel_robot/runtime.py` (shared with emotion lane),
`tests/test_next_to_approach_geometry.py`, `tests/test_voice_nav_e2e.py`,
`tests/test_yield_policy.py`, `tests/test_closed_intent_product_path.py`,
`tests/test_p2_dialogue.py`, `backlog/NEXT.md`,
`evals/companion/duplex_v1/run_duplex_v1.py`,
`evals/companion_nav/results/{ledger.jsonl, README.md, follow-bench-v1-20260809094511Z-601d8c6e.json}`.
