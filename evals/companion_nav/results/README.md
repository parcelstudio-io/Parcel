# FOLLOW_BENCH_V1 result ledger

This append-only summary points to the immutable JSON reports produced by
`evals/companion_nav/run_follow_bench_v1.py`. Every CLI invocation writes one
new `follow-bench-v1-<utc>Z-<nonce>.json` report here and appends one line to
`ledger.jsonl`; existing reports are never overwritten. Add one row per run
you intend other people to rely on, newest last.

| UTC | Report | Features | Change | Hard collisions | Follow success | Navigate success | Mean band fraction | Mean RMS jerk |
| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: |
| 2026-08-04T10:07:21 | [follow-bench-v1-20260804100721Z-ac46a6f1.json](follow-bench-v1-20260804100721Z-ac46a6f1.json) | shipped | Cards W2/W4/W6: anticipatory following with the NIS brake, dynamic-agent costs in `grid_v1` with the TTC gate, and the S-curve shaper on the dispatch path | 0 | 6/6 | 2/2 | 0.85475 | n/a |
| 2026-08-04T10:41:05 | [follow-bench-v1-20260804104105Z-9b2f69bc.json](follow-bench-v1-20260804104105Z-9b2f69bc.json) | baseline | Card W9 frozen baseline: three new scenarios, expression metrics, and a dispatch replica in the runner, with every W2/W4/W6/W7 code path switched off | 0 | 8/9 | 2/2 | 0.74240 | 0.9592 |
| 2026-08-04T10:41:34 | [follow-bench-v1-20260804104134Z-d1adc373.json](follow-bench-v1-20260804104134Z-d1adc373.json) | shipped | Card W9 feature run: identical suite and geometry with the W2/W4/W6/W7 paths enabled, to be read only against the baseline row directly above it | 0 | 8/9 | 2/2 | 0.74010 | 0.5530 |
| 2026-08-09T09:45:11 | [follow-bench-v1-20260809094511Z-601d8c6e.json](follow-bench-v1-20260809094511Z-601d8c6e.json) | shipped | Card pedestrian-evidence-refresh: re-run on the current tree to re-validate the 2026-08-04 jerk/collision numbers after the F-1 near-band inset, the surface-anchored `next_to` band, and the yield policy. Follow success flipped **8/9 -> 9/9** (all nine follow scenarios pass), hard collisions still **0**, navigate still 2/2, jerk essentially unchanged (0.5530 -> 0.6025). The duplex nav-regression mirror (`evals/companion/duplex_v1/run_duplex_v1.py`) is re-pinned to this row. | 0 | 9/9 | 2/2 | 0.74334 | 0.6025 |

Rows from `runner_version` 1.0 are **not** comparable with 1.1 rows: 1.1 added
the dispatch replica (the pre-gate acceleration smoother, the predictive
brake, and the actuator shaper) to the runner, so every commanded-velocity
number moved. The mean band fraction also drops between them because 1.1
added three scenarios, two of which are deliberately hard. Compare within a
version, and within a `Features` value.

Column definitions:

- **UTC** — `generated_at_utc` from the report.
- **Report** — link to the immutable JSON artifact in this directory.
- **Features** — `features_label`: `shipped` runs `configs/robot.yaml` as it
  stands, `baseline` switches the W2/W4/W6/W7 paths off. A feature claim needs
  both rows, produced by the same runner version on the same day.
- **Change** — one line describing what changed since the previous row
  (code, config, or scenario suite). "None (rerun)" is a valid entry.
- **Hard collisions** — `aggregate.hard_collision_total`: static-obstacle
  collision events counted by the world truth oracle plus pedestrian contact
  events (surface separation <= 0). Zero tolerance; there is no wall-sliding
  forgiveness, and any nonzero value fails the affected episode.
- **Follow success** — `follow_success_count/follow_episode_count`. An episode
  succeeds only if it has zero hard collisions, its owner-distance band
  fraction meets the scenario threshold, and the owner is never lost longer
  than the scenario's `max_time_lost_s`.
- **Navigate success** — `navigate_success_count/navigate_episode_count`:
  directive verified as `arrived` with zero hard collisions.
- **Mean band fraction** — mean over follow episodes of the fraction of
  control steps with the owner inside the distance band.
- **Mean RMS jerk** — `aggregate.mean_rms_commanded_jerk_mps3`, the mean over
  episodes of the RMS commanded jerk. Mean rather than total so a single
  scenario run stays comparable with a full-suite run.

## What the 2026-08-04 baseline/feature pair actually shows

Read this before quoting a sprint win. All numbers are baseline -> shipped
from the two rows above, same geometry, same seeds, same runner.

**W6, the actuator shaper — proven, and the strongest result.** RMS commanded
jerk fell in all eleven episodes; the suite mean went 0.9592 -> 0.5530 m/s^3,
a 42% reduction. The largest single drop is `pedestrian_group` at 1.5983 ->
0.5003 (-69%), followed by `navigate_crossing_ped` at 1.4879 -> 0.5868 (-61%).
Nothing regressed: hard collisions stayed at zero, follow success at 8/9, and
navigate success at 2/2. This measures the shaper's contribution inside the
bench's dispatch replica, which reproduces the runtime's smoother, gate,
brake, and shaper stages but not the arbiter or the SE2 HAL.

**W2, anticipatory following — not shown, exactly as UNVERIFIED U12 predicts.**
`owner_turn_90` was written to isolate the claim, and it reports mean band
error 0.0114 -> 0.0120 m and time outside the band 2.5 -> 2.6 s. That is a
hair *worse*, and well inside run-to-run noise either way: the direct-follow
lead point is clamped to roughly 0.05 m by the owner keepout, so there is
almost nothing for the predictor to contribute. Do not cite this scenario as
evidence for anticipation; cite it as the measurement that confirms U12.

**W4, the predictive brake — engages, but does not reduce interventions.**
`pedestrian_cut_in_predictive` reports a minimum time-to-collision of 1.688 s
shipped versus no finite value at baseline, so the gate demonstrably fires
inside its 2.0 s brake band. Geometric-gate interventions did *not* fall
(4 -> 4, of which 2 -> 2 were stops), because `reactive_safety.py` already
contains its own person time-to-collision brake driven by the
`nearest_person_ttc_s` channel, and for a single scripted pedestrian the two
brakes cover the same encounter. The acceptance criterion "interventions must
decrease" is therefore **not met**; see UNVERIFIED U15. Hard collisions stayed
at zero, which is the criterion that does hold.

**W4, dynamic costs in `grid_v1` — a small, real margin improvement.**
`navigate_crossing_ped` minimum pedestrian surface separation went 0.1582 ->
0.1756 m (+11%) with no loss of navigate success. Which side of the pedestrian
the route passes is still an artifact of the cost decay rather than a social
decision (UNVERIFIED U13), so this row is evidence about clearance, not about
politeness.

**W7, owner search — the machinery is proven, the reacquisition is not.**
`owner_corner_loss` reproduces today's documented failure exactly: at baseline
the robot freezes at the moment of occlusion and stays there for the remaining
48 s of the episode, never reacquiring. With the search enabled it triggers on
the lost timeout, runs all three phases in order, travels 1.39 m, exhausts its
45 s budget and reports `search_gave_up = true` — a clean terminal give-up
rather than a hang. It still does not find the owner: both the go-to-last-seen
and frontier phases are proportional controllers with no planner, so both
stall against the building corner under the obstacle gate. See UNVERIFIED U16.

**Expression (backlog N8) — measured for the first time, with one surprise.**
Acknowledgment latency is 0.2 s on `owner_turn_90`, which is the orient
reaction's 0.3 s ease arriving on schedule. Emote duty cycle is 12.3% and 9.9%
of conversation time on the two scripted scenarios, and no emote window
contains a hard collision in any episode. The surprise is
`expression_gated_fraction`: the stack is gated to MODE_OFF for 47% of
`owner_turn_90` and 84% of `pedestrian_cut_in_predictive`, because holding the
follow band puts the owner inside the proximity gate's slow radius and a
non-clear proximity state takes expression off entirely. A closely following
robot therefore cannot visibly acknowledge you for most of a follow. That is
shipped behaviour, not a bench artifact; see UNVERIFIED U17.

## Metric definitions and thresholds

All metrics are computed by `evals/companion_nav/metrics.py` from the recorded
0.1 s control-step trace. Scoring follows the 2026 person-following consensus
(Follow-Bench arXiv 2509.10796, SocNavBench, Gervet et al., SRCC/Kadian et
al.). BARN-style speed scoring is deliberately excluded.

- **Hard collision count** — static collision events from the world's
  geometric truth oracle plus pedestrian contact entries. Any contact fails
  the episode.
- **Band fraction / following success** — the owner must stay within the
  scenario distance band (default 1.2-3.0 m, center-to-center) for at least
  the scenario's `min_band_fraction` of steps (0.9 for nominal scenarios;
  deliberately lower for stress scenarios whose scripts break the band, see
  `scenarios.py`).
- **Owner lost time** — maximal continuous no-line-of-sight span; must not
  exceed the scenario `max_time_lost_s` (default 5 s).
- **Time to reacquire** — duration of each occlusion span that ended with the
  owner visible again; the mean and max are reported per episode.
- **Social spaces** — total time with the nearest scripted pedestrian center
  closer than 1.2 m (personal) and 0.45 m (intimate), plus the minimum
  center and surface separations. Reported, not thresholded, in v1.
- **RMS commanded jerk** — RMS magnitude of the second difference of the
  commanded planar velocity sequence (m/s^3). Reported, not thresholded.
- **Path irregularity** — accumulated absolute heading change of the executed
  path per meter traveled (rad/m). Reported, not thresholded.
- **Navigate episodes** — success (`arrived` after terminal verification with
  zero hard collisions), time-to-goal, and minimum static clearance.

Card W9 added the following, all reported and none thresholded:

- **Turn band error / time outside band** — over a scenario's `turn_window_s`
  only, the mean distance from the follow band (zero anywhere inside it, and
  the gap to the nearer edge outside it) and the time spent outside. Scored on
  a window because a two-second corner averaged over a thirty-second episode
  of straight walking is invisible.
- **Reactive-gate interventions** — distinct *entries* into a non-clear
  proximity state, and separately into `stopped`. Entries rather than steps so
  one long brake and forty short ones are distinguishable. During a follow the
  owner is themselves a person to the geometric gate, so the slowing count is
  dominated by the band; the stop count is the sharp signal.
- **Minimum time-to-collision** — smallest finite predicted contact time the
  W4 brake saw. `null` means the brake was off, or that nothing was ever on a
  collision course; those are different situations and the report cannot tell
  them apart on its own.
- **Time to reacquire (episode)** — from the first loss of the owner to the
  first recovery after it. `null` means never recovered, which is a timeout,
  not a fast reacquisition.
- **Search distance / gave-up** — executed path length while an owner search
  was running, and whether the search terminated by exhausting its budget.
  Both are `null` when no search ran at all.
- **Acknowledgment latency** — from a scripted speech onset to the first step
  where the expression stack's *reaction* producer holds the head past
  0.02 rad. Requiring the reaction producer matters: the idle layer's
  look-around would eventually cross any small threshold on its own.
- **Blend-continuity jerk** — RMS third difference of commanded head yaw,
  scored only in the windows spanning a producer hand-off. Averaging over a
  whole episode of smooth breathing hides the transient.
- **Emote duty cycle / emote hard collisions** — gesture time as a fraction of
  the interaction span (first speech onset to the last conversational event of
  either kind), and any hard collision on a step a gesture owned the base.
- **Expression gated fraction** — steps where the gate held the stack at
  MODE_OFF. Read the latency and the duty cycle against this: a `null` latency
  next to a high gated fraction is a robot that was never allowed to react,
  not a reaction that failed.

## Known v1 limitations (read before citing any number)

- **Pedestrian sensing is partially injected.** Scripted pedestrians are
  embodied as the scene's mocap capsules, so they are visible to the
  occlusion-true raycast scan and they physically block the owner
  line-of-sight ray. They are however *absent* from the analytic
  nearest-obstacle telemetry and from the static-collision truth oracle; the
  controllers see them through the injected `dynamic_agents`/`nearest_person`
  observation fields, exactly as the production runtime would receive them
  from a person tracker. Pedestrian contact is therefore scored from recorded
  separations, never by the collision oracle.
- Pedestrians follow fixed scripts and never react to the robot.
- The base is kinematic (no contact physics); the owner track is an oracle
  with a geometric 1.0 m-height visibility ray instead of a camera pipeline.
- The `doorway_gap` scenario documents that the production keepout stops the
  robot short of the narrowest section; its scored quantity is minimum
  clearance, not full traversal.
- **The dispatch replica is partial.** `runner_version` 1.1 reproduces the
  runtime's acceleration smoother, collision gate, predictive brake, and
  actuator shaper in that order, which is what makes the W4 and W6 numbers
  meaningful. It does *not* reproduce the arbiter, the control manager, or the
  SE2 HAL, so a jerk figure here is the shaper's contribution and not the
  robot's.
- **The owner search runs without its plan.** `owner_corner_loss` drives
  `SearchOwnerController` from the same deterministic lost-timeout trigger the
  runtime uses, but the compiled plan, the validator, and the executive are
  not in the loop; those are covered by unit tests instead.
- **Emotes are modelled by their arbitration only.** A scripted emote window
  preempts the base exactly as a running activity would, and nothing else
  about the gesture is simulated.
- **`owner_corner_loss` does not prove re-identification.** The owner track is
  identity-perfect and visibility is a geometric ray, so a reacquisition here
  says nothing about whether a camera pipeline would recognise the right
  person.
- Reports prove closed-loop controller/navigator quality in this rig only.
  See the `does_not_prove` list embedded in every report.
