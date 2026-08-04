# Sprint 2026-08-04 · task_2 — the walking companion

**Author:** Fable 5 (plan + integration + adversarial review).
**Executors:** Claude Opus (repo-integrated) and ChatGPT Sol 5.6 Ultra
(self-contained modules with frozen contracts), same split rationale as
[../task_1/README.md](../task_1/README.md).

**Theme.** Last sprint gave the dog a body that feels alive while mostly
standing still. This sprint makes it a companion that *walks with you*:
anticipates where you are going instead of trailing where you were, refuses to
path through where a pedestrian is about to be, moves with animal smoothness
rather than industrial steps, and — for the first time — knows what to do when
it loses you. Every card is sim-testable now; nothing waits on hardware.

Sources: [../../../backlog/NEXT.md](../../../backlog/NEXT.md) (N1–N4, N6, N8),
[../../../docs/RESEARCH_2026_ROADMAPS.md](../../../docs/RESEARCH_2026_ROADMAPS.md)
§3 steps 1–3, 5–6. Findings from the in-flight sprint review of 2026-08-04
work are fixed by Fable before integration begins.

## Board

| ID | Card | Owner | Depends on | Backlog |
|---|---|---|---|---|
| W1 | `OwnerMotionPredictor` — Kalman CV/CA module (pure numpy) | Sol | — | N2 |
| W2 | Follow the *predicted* owner path + NIS uncertainty brake | Opus | W1 | N2 · **landed** (opens U12) |
| W3 | `DynamicAgentCostField` + rollout TTC check (pure numpy) | Sol | — | N3 |
| W4 | Merge dynamic costs into `grid_v1`; compile the TTC gate | Opus | W3 | N3 · **landed** (opens U13) |
| W5 | `SCurveVelocityShaper` — jerk-limited filter (pure numpy) | Sol | — | N4 |
| W6 | Shaper between controllers and the SE2 HAL, affect-modulated | Opus | W5 | N4 · **landed** (opens U14) |
| W7 | `SearchOwner` — reacquisition skill (LOP → sweep → frontier) | Opus | — | N6 · **landed** (opens U11) |
| W8 | Emote triggers onto the playback clock (epoch-tagged) | Opus | — | N1 / U6 · **landed** (U6 closed) |
| W9 | Eval: new walk-with-owner scenarios + expression metrics + ledger | Opus | W2 W4 W6 W7 | N8 · **landed** (closes most of U14; opens U15 U16 U17) |
| — | Fix 2026-08-04 review findings; integration review; final suite | Fable | — | — |

Parallelism: W1, W3, W5 (Sol) and W7, W8 (Opus) have no mutual dependencies —
five cards can start at once. Sol again touches only new files.

## Working agreements

All seven agreements from [../task_1/README.md](../task_1/README.md)
carry over verbatim — safety authority untouchable, suite+ruff green per
handoff, loud degradation, manifest re-freeze on `robot.yaml` edits (compute
the hash **per named entry from disk**, never by line position — see the
2026-08-04 housekeeping incident), tests in the same card, honest handoffs,
and every "not verified" line lands in
[../../../backlog/UNVERIFIED.md](../../../backlog/UNVERIFIED.md).

One addition:

8. **New config keys get fail-closed validation in the same card.** The
   mis-indented-YAML incident survived a full sprint because a section
   accepted keys it never read. `build_prompting_stack` and
   `_build_expression_engine` show the pattern.

## Definition of done for the sprint

- **Anticipation:** in a scenario where the owner turns 90° mid-walk, the
  follower's mean distance-band error during the turn drops measurably vs the
  frozen baseline (record both numbers in the ledger).
- **Dynamic safety:** the pedestrian cut-in scenario completes with zero hard
  collisions *without* relying on the reactive gate alone — the planner's
  chosen path visibly yields (the gate remains the unconditional backstop).
- **Smoothness:** RMS jerk in the follow scenarios drops against the frozen
  baseline with the shaper on; no follow-success regression.
- **Reacquisition:** owner walks behind the occluder and keeps moving; the
  dog reaches last-observed-position, sweeps, searches, and reacquires within
  the scenario budget. Today's behavior (stand and wait forever) is the
  baseline to beat.
- **Emotes on the playback clock:** a queued-but-superseded sentence fires no
  gesture (U6 closed in the register with evidence).
- Full suite green, ruff clean, one ledger row per eval-visible change.

## Handoffs

(append here)

### W1 — OwnerMotionPredictor (Sol)

- **Changed:** Added the frozen `PredictedPath` / `OwnerMotionPredictor`
  contract as a deterministic constant-velocity Kalman filter with
  acceleration process noise, adaptive covariance inflation on hot
  innovations, and 10-sample windowed NIS confidence. No CA promotion was
  needed to meet the turn and endpoint criteria.
- **Verified:** Straight-line endpoint accuracy, three-observation 90-degree
  turn response, teleport confidence, staleness, invisible observations,
  non-finite rejection, determinism, and the 0.5 ms performance budget in
  `tests/test_owner_prediction.py`; full suite and new-file ruff are green.
- **Verification gaps:** None within the pure-module card scope.

### W3 — DynamicAgentCostField + TTC (Sol)

- **Changed:** Added vectorized constant-velocity Gaussian rollout costs and
  exact quadratic circle-contact TTC. Agent radius broadens each Gaussian;
  rollout weights decay by the configured half-life.
- **Verified:** Empty/static/moving fields, future-corridor cost, approaching,
  receding, stationary-robot and overlap TTC cases, malformed/NaN rejection,
  and the 8-track × 10-step × 4,000-point 2 ms budget in
  `tests/test_dynamic_costs.py`; full suite and new-file ruff are green.
- **Verification gaps:** None within the pure-module card scope.

### W5 — SCurveVelocityShaper (Sol)

- **Changed:** Added independent per-axis acceleration/jerk state, a
  switching-curve acceleration cap for monotonic no-overshoot tracking,
  emergency max-acceleration zero slew, reset, and state-preserving scaled
  profiles.
- **Verified:** Velocity/acceleration continuity, acceleration and jerk
  bounds, variable-dt no-overshoot tracking, emergency bypass, scaling,
  validation, zero-cost settled behavior, and the 50 us step budget in
  `tests/test_velocity_shaping.py`; full suite and new-file ruff are green.
- **Verification gaps:** None within the pure-module card scope.

### W7 — SearchOwner reacquisition skill (Opus)

- **Changed.** New `navigation/search_owner.py`: `SearchOwnerConfig` (fail-closed
  `from_mapping`, rejects unknown keys and out-of-order budgets) and
  `SearchOwnerController`, three bounded states — `go_to_last_observed` →
  `sweep` (±120° in place) → `frontier_search` (ring lattice around the loss
  point, pruned by an `owner_max_speed_mps × elapsed` reachability disk, scored
  by unknown-cell information gain against the controller's own
  `RollingOccupancyGrid` minus a travel penalty). Packaged as a semantic skill:
  validator contract (`SearchOwner`, success fact `owner_reacquired`, no
  `owner_visible` precondition), `reacquire` goal relation, compiler canonical
  success, adapter dispatch + verified completion, `search: 35` in
  `SOURCE_PRIORITIES`, and an `owner_search` section in `configs/robot.yaml`
  (manifest `robot_config` sha256 re-frozen from disk).
- **Trigger.** Deterministic, never a model. `_maybe_trigger_owner_search` watches
  the follow controller for a continuous `lost` state; after
  `lost_timeout_s` (3 s) the runtime authors a `SearchOwner` `PlanIR` and pushes
  it through `compile_plan_contracts` → `system_plan_validator` →
  `task_executive.submit(task_class="system")`. It is an ordinary plan from
  there: same invariants, same interruption, same verified completion. Follow is
  stopped and cached only *after* the task is queued, so the base lease is
  released in the order the search step needs it.
- **Planner surface.** `SearchOwner` is a *system skill*: absent from
  `SkillContractRegistry.default()` and from
  `SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS`, so no PlanIR/PlanSketch schema,
  prompt catalog, or frozen eval registry changed. It is reachable only through
  `default(include_system_skills=True)` (runtime `system_registry`) and
  `EXECUTABLE_SKILLS` (adapter dispatch guard). `agent.brain.skills` rejects it
  explicitly.
- **Verified** (`tests/test_search_owner.py`, 25 tests): state progression and
  the blocked-last-observed timeout; reacquisition as immediate terminal success
  from *any* state with a zero command; a sub-threshold glimpse is not a
  reacquisition; budget exhaustion gives up cleanly; stale perception and
  collision contact both zero the command without ending the search; the missing
  scan degrades loudly; the contract's precondition/success shape and the four
  safety invariants a search plan compiles (`stop_on_stale_perception`,
  `keep_collision_margin`, `yield_to_people`, `avoid_road_when_not_crossing`);
  dispatch
  fails closed without a callback; completion requires the controller *and* the
  camera track to agree (`OWNER_TRACK_CONFIDENCE_MIN`), and a controller claim
  without a confident track fails rather than succeeds; give-up fails the step
  and claims nothing; the trigger waits out `lost_timeout_s`, is cancelled by
  recovery, and holds instead of searching with no confident last position;
  E-stop ends an active search; give-up says so out loud and leaves the arbiter
  with no owner; and the full loop trigger → dispatch → reacquire →
  `owner_reacquired_verified`.
- **Bug found and fixed while testing.** `_step_goto`/`_step_sweep` computed the
  phase clock as `now - (self._phase_started_at or now)`, so a phase that began
  at t=0.0 read as never started and its timeout could never fire. Replaced with
  an explicit `is None` check.
- **Verification gaps.** U11 in the register: the frontier stage builds its own
  occupancy grid from the observation's LiDAR rather than sharing the
  navigator's, and `owner_max_speed_mps` / the 45 s budget are argued, not
  measured. No test has reacquired anything but a synthesized `OwnerTrack`.
  The W9 scenario (owner walks behind an occluder and keeps moving) is what
  actually exercises this.

### W8 — Emote triggers onto the playback clock (Opus)

- **Changed.** `SentenceChunkedSynthesizer` no longer takes or fires `on_emote`.
  It yields `SpeechChunk` — a `bytes` subclass carrying the emotes authored in
  its own sentence — so the association travels with the audio through a
  deliberately byte-oriented path. `_enqueue_speech_chunk` puts them on the
  `SpeakerSink` playback-start token as `(track, epoch, emotes)`, the anchor
  `BeatLayer` already used; `_audio_chunk_started` arms the nods, then fires the
  emotes, only when the token's epoch is still current. Nods are armed first so
  a gesture the arbiter rejects cannot cost the sentence its beats. Text mode
  has no playback clock, so `_fire_text_mode_emotes` fires on reply — and not at
  all when the turn was superseded.
- **Verified** (`tests/test_emote_skill.py`): `..._fires_at_playback_start_not_at_synthesis`,
  `test_superseded_sentence_fires_no_emote`,
  `test_text_only_path_fires_emotes_immediately`,
  `test_a_superseded_text_reply_fires_no_emote`,
  `test_playback_start_survives_an_inadmissible_emote`,
  `test_streaming_attaches_each_emote_to_its_own_chunk`,
  `test_blocking_synthesize_strips_tags_and_keeps_their_emotes`; plus
  `tests/test_beat_sync.py` updated for the 3-tuple token.
- **U6 closed** in the register with those test names.
- **Verification gaps.** Only the *scheduling* claim is closed. Whether a
  gesture now looks synchronized with the words needs real audio output, which
  U5 blocks; noted in the closure entry rather than claimed.

### Suite status after W7 + W8

`.parcel/bin/python -m pytest -q` → **1474 passed, 2 skipped**.
`.parcel/bin/python -m ruff check src/ tests/ evals/` → clean.
`tests/test_habitat2020_contract_smoke.py` needs `os.kill` and therefore an
unsandboxed shell; it passes there and fails with `PermissionError` under a
restricted one. Not a code condition.

### W2 — Follow the predicted owner path + NIS uncertainty brake (Opus)

- **Changed.** `src/parcel_robot/navigation/follow.py` (new
  `FollowPredictionConfig`, lead-point resolution, owner-keepout clamp, the
  brake, and the `prediction` snapshot block); `src/parcel_robot/runtime.py`
  (owns one `OwnerMotionPredictor`, feeds it from the same owner track
  `observe_owner` uses, passes the path into `follow.step`);
  `configs/robot.yaml` (`owner_follow.prediction`);
  `evals/companion_nav/runner.py` (replicates the merge and the predictor so
  the bench measures the shipped path); `tests/test_follow_prediction.py` (22).
- **Config deviation, deliberate.** The card names
  `navigation.follow.prediction`. Follow configuration lives under the
  top-level `owner_follow:` section in this repo — `navigation:` holds only
  `enabled` and a path — so the block went to `owner_follow.prediction`.
  Unknown keys inside it raise at startup; the nested mapping is popped and
  validated separately so a typo cannot ride through as an unknown top-level
  follow key.
- **Predictor ownership.** Reset on owner-identity change and on the tick that
  observes follow having stopped (one place in the control loop covers all
  thirteen `follow.stop()` sites, since they all end with the controller
  disabled). It is **not** reset on follow *start*, against the card's letter:
  the filter is fed on every perception tick, so resetting at activation would
  spend the first second of every follow in fallback — the same reasoning the
  controller already documents for its passive heading history.
- **Lead point.** `points[round(lead_s / step_s) - 1]`. Direct follow
  substitutes it for the owner position in the existing distance law; behind
  formation moves the anchor and the anchor heading to it and drops the legacy
  0.25 m short-horizon extrapolation so the lookahead is not counted twice.
  The keepout geometry deliberately stays on the *measured* owner: a
  prediction may say where to aim, never license driving through where the
  owner was actually seen.
- **The clamp, and why W2 does nothing on the bench.** Holding
  `desired_distance_m` from a lead point holds `desired_distance_m − lead`
  from the visible owner, so the lead is clamped to
  `standoff − owner_keepout_m`. Direct follow ships 1.60 m against a 1.55 m
  keepout → **0.05 m of lead**. Behind formation ships 1.90 m → 0.35 m. The
  follow-bench rerun is therefore byte-identical to the baseline and
  `follow_turn_corner` is still 0.4625. This is **U12**, and W9 must not read
  W2 as a following improvement until it runs behind formation or
  `desired_distance_m` moves with provenance.
- **The brake.** A system-owned rule, not a suggestion: translation is scaled
  by a linear ramp on the predictor's confidence — full speed at 0.5,
  standstill at 0.1, exactly ×0.5 at the card's worked example of 0.3. It
  applies whenever a prediction exists, including when confidence is too low
  to trust the lead point, because that is precisely the evidence the owner is
  unpredictable. Yaw is untouched so an uncertain follower may still keep the
  owner in frame. Scaling the finished command means the brake composes
  strictly *under* the reactive policy and the collision gate; a test sweeps
  every confidence and asserts the result never exceeds the unbraked command.
- **Snapshot.** `follow.prediction` carries `enabled`, `active`, `reason`,
  `confidence`, `lead_x_m`, `lead_y_m`, `speed_scale`. Every fallback has a
  distinct reason (`disabled`, `no_prediction`, `confidence_below_threshold`,
  `lead_beyond_horizon`, `non_finite_prediction`,
  `lead_clamped_to_owner_keepout`) so a deployment silently living in fallback
  is visible rather than invisible.
- **Verification gaps.** U12. The predictor itself is Sol's, tested in W1.

### W4 — Dynamic costs into `grid_v1` + the TTC gate (Opus)

- **Changed.** New `src/parcel_robot/navigation/dynamic_layer.py` (both
  fail-closed configs, payload validation, the mask merge, the TTC query);
  `grid_planner.py` (`set_dynamic_cost_layer`, `cell_centers_xy`, and one
  additive `_dynamic_penalty(neighbor)` term in each of the three cost
  expressions); `grid_navigator.py` (per-tick layer build);
  `pipeline.py` / `skills/api.py` (a public `dynamic_cost_active` accessor so
  the snapshot need not reach through two private attributes);
  `runtime.py` (track payloads into `_navigation_extras`, the gate after
  `apply_reactive_safety`, the snapshot fields);
  `configs/navigation/models/grid.yaml`; `configs/robot.yaml`;
  `tests/test_dynamic_layer.py` (31).
- **Integration choice.** The local window, not the cells A* touches. The cost
  is a per-cell additive penalty exactly like the existing comfort-cost mask,
  which meant one term per cost expression instead of a callback inside the
  expansion loop; cells beyond `window_radius_m` (6 m) are never scored. The
  layer is rebuilt every tick — the tracks moved, that is the point — and
  repeated A* at 10 Hz is what makes that affordable. No D* Lite.
- **`GridPlannerConfig` untouched**, so the frozen model-lock profiles are
  unchanged; the layer is installed on the planner instance instead.
- **Owner weighting.** Strangers and the owner are scored separately and
  summed, so the owner's reduced weight applies to the owner's lobe alone.
  `owner_weight > weight` is rejected at load: a follower may not avoid its own
  owner harder than a stranger. The owner track carries the W2 predictor's
  velocity when it is live and a zero velocity otherwise.
- **The gate.** Runs in `_collision_safe` *after* `apply_reactive_safety`, on
  the outgoing command, and only ever multiplies by a factor in [0, 1] — it
  can brake something the geometric gate allowed and can never release
  something the geometric gate stopped. The body-frame command is rotated into
  the track frame before the query. `collision.py` and `reactive_safety.py` are
  untouched, and `test_the_safety_authority_files_are_untouched_on_this_branch`
  asserts that against `git status` rather than trusting the claim.
- **Snapshot.** `navigation.dynamic_cost_active`,
  `navigation.min_time_to_collision_s`, `navigation.time_to_collision_gate`.
- **Verification gaps.** U13: the route leaves the predicted corridor (peak
  cost 1.0 → <0.25) but the *side* it picks is an artifact of `agent_cost_at`'s
  lookahead decay, which makes passing in front cheaper than passing behind.
  Pinned by a named test so W9 cannot mistake it for social behaviour.

### W6 — The shaper on the dispatch path + affect modulation (Opus)

- **Changed.** New `src/parcel_robot/core/motion_shaping.py`
  (`MotionShapingConfig`); `runtime.py` (the shaper call in `_dispatch_active`,
  profile selection, `_reset_motion_shaper` on every bypassing stop path, and
  arousal capture in `_audio_chunk_started`); `core/__init__.py`;
  `configs/robot.yaml` (`motion.shaping`, default ON);
  `tests/test_motion_shaping.py` (25).
- **Placement.** Immediately before `control_manager.set_target`, after the
  arbiter and after `_collision_safe`. Safety sees the intent; the actuator
  sees the smooth version. The pre-existing `VelocitySmoother` keeps its place
  *before* the gate and is unchanged — this stage removes the velocity steps
  the gate and arbiter introduce, it is not a second rate limiter.
- **Ten stop entry points, each routed and each tested.** Six leave
  `_dispatch_active` entirely and reach the HAL through
  `control_manager.stop`/`emergency_stop`; they now also drop shaper state so a
  hard stop cannot later ramp out of a velocity that is no longer real. Four
  are decided inside the dispatch and take the shaper's `emergency=True`
  bypass.

  | # | Entry point | Route |
  |---|---|---|
  | 1 | `emergency_stop()` | direct HAL + state reset |
  | 2 | simulator-adopted E-stop | direct HAL + state reset |
  | 3 | `stop_motion()` | direct HAL + state reset |
  | 4 | `stop_on_stale_perception` | direct HAL + state reset |
  | 5 | `intent_expired` (arbiter lease) | direct HAL + state reset |
  | 6 | collision-gate proximity stop | `emergency=True` bypass |
  | 7 | `navigation_terminal_verification` | direct HAL + state reset |
  | 8 | `pose_started` | direct HAL + state reset |
  | 9 | `trajectory_started` | direct HAL + state reset |
  | 10 | zero target from an active source | `emergency=True` bypass |

- **Found while wiring.** The bypass decision must read the *arbiter's intent*,
  not the post-`VelocitySmoother` value: with the pre-gate smoother still
  ramping down, a zero target arrives at the shaper as a non-zero number and
  the stop was being jerk-limited. Entry point 10's test spies on the shaper's
  `emergency` argument rather than a velocity, so this cannot regress silently.
- **Affect.** Vocal arousal captured at playback start (the W8 clock) is the
  only affect signal measured from the robot's own behaviour rather than
  inferred from text, so it is what selects the profile: arousal ≤ 0.35 within
  the last 20 s → `scaled(0.6)`. With no recent evidence the nominal profile
  wins — calm must be observed, not assumed, or the robot would live at 60% of
  its acceleration budget. Velocity is carried across a profile change so the
  swap is not itself a step.
- **Ledger.** Follow-bench rerun after all three cards: unchanged at 6/6,
  0 hard collisions, mean band fraction 0.85475, row appended to
  `evals/companion_nav/results/README.md`. That is the no-regression half.
  RMS jerk on a square-wave target through the configured limits: 16.64 →
  1.69 m/s³ nominal (−89.8%), 1.02 m/s³ calm (−93.8%).
- **Verification gaps.** U14: the jerk number is unit-level. The bench models
  the follow controller and the reactive gate, not the arbiter/dispatch layer
  the shaper lives in, so there is no end-to-end jerk delta and I did not
  manufacture one.

### Suite status after W2 + W4 + W6

`.parcel/bin/python -m pytest -q` → **1552 passed, 2 skipped**.
`.parcel/bin/python -m ruff check src/ tests/ evals/` → clean.
`configs/robot.yaml` changed, so `robot_config` was re-frozen in
`evals/companion/embodied_plan_v1/manifest.json` (hash computed per named
entry from disk): `467190ff2809…` → `d8a090a4879d…`.

**Ready for W9**, with three caveats the eval card must plan around: W2 is
inert in direct follow (U12), W4's detour side is not socially adjudicated
(U13), and W6's jerk result is not yet end-to-end (U14).

---

## W9 handoff — walk-with-owner scenarios + expression metrics · Opus

The card's job was to measure this sprint, not to advertise it. Two of the
four claims came back positive, two came back negative, and the negatives are
on the ledger in the same words as the positives.

### Files changed

- `evals/companion_nav/scenarios.py` — `SpeechTurn` / `EmoteWindow` /
  `ExpressionScript` (validated, non-overlapping, inside the episode);
  `turn_window_s` and `expression` on `Scenario`; three new scenarios.
- `evals/companion_nav/metrics.py` — six new step fields and fifteen new
  episode fields, plus `distance_band_error_m`, `gate_intervention_spans`,
  `time_to_reacquire_s`, `path_length_m`, `blend_continuity_jerk_rad_s3`,
  `acknowledgment_latency_s`.
- `evals/companion_nav/runner.py` — `BenchFeatures`, `_DispatchReplica`,
  `_ExpressionRig`, the owner-search trigger, and the dynamic-cost toggle.
  `RUNNER_VERSION` 1.0 → **1.1**; 1.0 numbers are not comparable.
- `evals/companion_nav/run_follow_bench_v1.py` — `--features`, five new
  `does_not_prove` entries, feature provenance and five aggregates in the
  report, two new ledger columns.
- `src/parcel_robot/navigation/dynamic_layer.py` — the TTC gate extracted
  into `time_to_collision_verdict` / `body_to_world` so the runtime and the
  bench share one implementation instead of forking it.
- `src/parcel_robot/runtime.py` — `_time_to_collision_gate` now calls the
  shared verdict; local `_body_to_world` deleted. No behaviour change.
- `tests/test_follow_bench_v1.py` — nine new tests, three of them closed-loop
  under `PARCEL_FOLLOW_BENCH_SLOW`.
- `evals/companion_nav/results/README.md` — two ledger rows and a
  "what the pair actually shows" section.
- `backlog/UNVERIFIED.md` — U12 and U14 updated with measurements, U15/U16/U17
  added.

`configs/robot.yaml` was **not** touched, so no manifest re-freeze was needed.

### The one design decision worth arguing with

Every claim needed a before *and* an after on identical geometry, and the
runner built its controllers straight from `robot.yaml`. Rather than edit
config between runs — which would have needed a hash re-freeze per run and
left baseline rows unreproducible — `BenchFeatures` switches the W2/W4/W6/W7
paths at construction time, and the report records which set was live. A
report without `features_label` cannot be compared with anything.

The second decision was to make the bench honest about dispatch. U14 said the
W6 claim could not be measured because the bench gated a command and then
wrote it straight to the world, skipping the smoother and the shaper.
`_DispatchReplica` now runs the runtime's stages in the runtime's order. The
pre-gate smoother is deliberately *not* a feature switch: it has always been
in production and its absence here was a bench bug, so it is on in both the
baseline and the feature run. Its arrival is why `pedestrian_group` lost about
two and a half points of band membership and had its threshold re-calibrated
0.8 → 0.75, with that provenance recorded in `scenarios.py`.

### Results — baseline → shipped, same geometry, same seeds

| Card | Scenario | Metric | Baseline | Shipped | Verdict |
| --- | --- | --- | ---: | ---: | --- |
| W6 | all 11 | mean RMS jerk (m/s³) | 0.9592 | 0.5530 | **proven**, −42% |
| W2 | `owner_turn_90` | mean band error (m) | 0.0114 | 0.0120 | **not shown** (U12) |
| W2 | `owner_turn_90` | time outside band (s) | 2.5 | 2.6 | **not shown** (U12) |
| W4 | `pedestrian_cut_in_predictive` | min TTC (s) | none | 1.688 | gate engages |
| W4 | `pedestrian_cut_in_predictive` | gate interventions / stops | 4 / 2 | 4 / 2 | **not reduced** (U15) |
| W4 | `navigate_crossing_ped` | min pedestrian surface (m) | 0.1582 | 0.1756 | +11% margin |
| W7 | `owner_corner_loss` | time to reacquire (s) | none | none | **not reacquired** (U16) |
| W7 | `owner_corner_loss` | search distance / gave up | none / n/a | 1.39 m / true | machinery proven |
| N8 | `owner_turn_90` | acknowledgment latency (s) | 0.2 | 0.2 | measured |
| N8 | `owner_turn_90` / cut-in | emote duty cycle | 12.3% / 9.9% | same | measured |
| N8 | all | emote hard collisions | 0 | 0 | interruption correct |
| N8 | `owner_turn_90` / cut-in | expression gated fraction | 47% / 84% | same | **new finding** (U17) |

Hard collisions are zero in every episode of both runs; navigate success is
2/2 in both; follow success is 8/9 in both, the miss being `pedestrian_group`
against its pre-existing threshold before re-calibration.

### What each new scenario deliberately does not prove

Added to the report's `does_not_prove` list, not just to this document:
owner re-identification (`owner_corner_loss`'s track is identity-perfect and
visibility is a geometric ray); the owner-search *plan* path (the bench drives
the controller from the same deterministic trigger, but compilation, the
validator, and the executive are unit-tested rather than exercised here);
gesture kinematics (an emote is modelled only by its arbitration consequence);
conversational timing realism (fixed script times, no ASR or playback clock);
and production dispatch in full (no arbiter, control manager, or SE2 HAL).
The pre-existing pedestrian-sensing note is unchanged.

### Verification gaps

- **U15** — W4's gate engages but does not reduce gate interventions, because
  `reactive_safety.py` already brakes on the social candidate's own TTC. The
  card's acceptance criterion is not met and I did not reword it into one that
  was.
- **U16** — W7's search triggers, sequences, budgets, and gives up cleanly,
  but travels 1.39 m and never finds the owner: both mobile phases are
  proportional controllers with no planner and stall against a wall.
- **U17** — the expression stack is gated off for 47–84% of a follow because
  the owner trips the proximity gate. New, and the most interesting thing this
  card found.
- **U14** (remainder) — the affect-modulated calm profile is still unit-level;
  no bench episode drives vocal arousal.

### Suite status after W9

`.parcel/bin/python -m pytest -q` → **1564 passed, 6 skipped**, plus the
known `tests/test_habitat2020_contract_smoke.py` sandbox artifact (an
`os.kill` `PermissionError` in subprocess teardown, unrelated to this card and
present before it).
`.parcel/bin/ruff check src/ tests/ evals/` → clean.
Full suite both ways: `--features baseline` and `--features shipped`, reports
`…104105Z-9b2f69bc.json` and `…104134Z-d1adc373.json`.

---

## Arbitration (coordinator standing in for Fable)

Claude Fable was requested as arbiter after both cross-reviews returned
**REQUEST CHANGES**, but the Fable API hit a usage limit twice
([attempt 1](65448fee-d5d2-4a83-b168-73e0d25d326a),
[attempt 2](6577deac-c5ea-461c-accb-8594b127048f)).
This section is the binding ruling from the coordinator, grounded in both
reviews and re-measured on the default cost field (behind 1.0/1.5 m =
0.937/0.304 vs front = 1.0/1.0; weight sum = 5.351; saturated span ≈ 3.6 m).

Reviewers: [Sol→Opus](9f16e2aa-5f4a-4f7f-a42e-fdbeb3439a3b),
[Opus→Sol](4c702c55-7d5e-4062-ac22-83bbb8d46541).

### Binding rulings

| Finding | Ruling | Rationale |
|---|---|---|
| U13 decay→front-cheaper story | **REJECT** (mechanism); keep observation | Re-measured: behind is cheaper; stationary still north = geometry. Register + test docstring corrected. |
| W3 cost saturation mesa | **BINDING** Sol fix | Normalize by weight sum before clip; restores gradient inside frozen signature. Spec sentence "Sum, clip" re-read as sum→normalize→clip. |
| `query_t` / social behind | **DEFER** | Needs contract extension; file under U13 to-verify. |
| U12 0.05 m lead clamp | **BINDING** Opus-fault; **DEFER** policy | Keepout-on-direct is integration. Do not silently lower keepout or raise standoff this pass — U12 stays until a product decision. |
| Smoothing ignores `_dynamic_cost` | **BINDING** Opus fix | Can erase the A* detour; acceptance-breaking. |
| Replan every 5 ticks with live dynamics | **BINDING** Opus fix | Force replan when dynamic layer is active (or on material layer change). |
| U15 causal claim | **REFINE** | Composed interventions 4→4 proven; *reactive*-only decrease unproven until metric splits pre/post TTC. |
| W9 multi-feature attribution | **BINDING** language fix | Weaken ledger/handoff to "feature set", not single-card causation, unless ablations land. |
| W7 proportional vs grid navigator | **BINDING** Opus fix | Card required existing grid navigator; U16 strengthens to acceptance miss. |
| Shaper vs ControlManager watchdog | **BINDING** Opus fix | Test the real watchdog path; reset shaper state there. |
| `predict()` mutates filter | **BINDING** Sol fix | Determinism / cadence bug; advance a copy. |
| NIS 1 s freeze after jump | **DEFER** | Tuning; register if desired. Brake ramp is Opus scope later. |
| `scaled()` multiplies accel | **DEFER** | Minor continuity nit. |
| W1/W5 module quality | **APPROVE WITH NITS** | Per Opus review. |

### Sprint-must-fix (ordered)

**Sol:** (1) normalize `agent_cost_at` weights before clip + pin saturation/front-behind tests; (2) make `predict()` side-effect free.

**Opus:** (1) preserve dynamic cost through route smoothing / shortcuts; (2) replan while dynamic layer active; (3) SearchOwner mobile phases through `grid_v1`; (4) split pre/post-TTC intervention metrics + U15 wording; (5) ControlManager watchdog → shaper reset + real test; (6) weaken multi-feature ledger attribution.

**Coordinator/Fable-stand-in (done here):** correct U13 register + docstring; record this arbitration.

### Sprint DoD status

| DoD claim | Status |
|---|---|
| Anticipation / turn band error | **Open (U12)** — not shown |
| Dynamic safety zero hard collisions + planner yield | **Partial** — collisions 0; side not social (U13); smoothing/replan gaps open until Opus fixes |
| TTC gate reduces reactive interventions | **Open (U15)** — metric confounded; gate engages |
| Smoothness / RMS jerk | **Proven at feature-set level (−42%)** — do not over-attribute to W6 alone until ablations |
| Reacquisition within budget | **Failed (U16)** until SearchOwner uses the navigator |
| Emotes on playback clock (U6) | **Closed** (scheduling) |
| Suite green / ruff / ledger rows | **Met** at W9 land; re-verify after must-fixes |

### Arbitration fixes (coordinator; Sol/Opus API-limited)

Fable, Sol, and Opus all hit API usage limits on the fix pass. The coordinator
landed the binding must-fixes directly:

- **W3:** `agent_cost_at` normalizes by weight sum before clip (gradient
  restored; front/behind + mesa tests pinned).
- **W1:** `predict()` advances a copy; cadence test added.
- **W4:** route smoothing and world-shortcut checks preserve `_dynamic_cost`;
  navigator replans every tick while the dynamic layer is active.
- **W7:** SearchOwner mobile phases use `RollingGridPlanner` when a map exists.
- **W6:** ControlManager watchdog stop syncs shaper reset + test.
- **W9:** pre-TTC `reactive_proximity_state` vs composed `proximity_state`;
  `composed_gate_*` metrics added. U13 register + docstring already corrected
  above; U16 marked pending re-measure.
