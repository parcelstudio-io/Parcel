# FOLLOW_BENCH_V1 result ledger

This append-only summary points to the immutable JSON reports produced by
`evals/companion_nav/run_follow_bench_v1.py`. Every CLI invocation writes one
new `follow-bench-v1-<utc>Z-<nonce>.json` report here and appends one line to
`ledger.jsonl`; existing reports are never overwritten. Add one row per run
you intend other people to rely on, newest last.

| UTC | Report | Change | Hard collisions | Follow success | Navigate success | Mean band fraction |
| --- | --- | --- | ---: | --- | --- | ---: |

Column definitions:

- **UTC** — `generated_at_utc` from the report.
- **Report** — link to the immutable JSON artifact in this directory.
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
- Reports prove closed-loop controller/navigator quality in this rig only.
  See the `does_not_prove` list embedded in every report.
