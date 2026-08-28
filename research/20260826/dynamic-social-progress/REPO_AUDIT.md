# Dynamic social progress · repository audit

**Audit date:** 2026-08-26
**Method:** read-only source and persisted-evidence review; line references are
to the working tree at audit time. No hardware or live simulator was touched.

## Bottom line

Parcel contains reusable tracking, prediction, reactive-safety, replanning,
yield, and deterministic-evaluation pieces, but no single typed social-
navigation liveness layer. Persistent occupancy, dynamic-track deletion,
global replanning, person yield, reactive release, and progress timeouts each
run on different state and clocks. That is the central cause of both false
stalls and stop/resume chatter.

The current Go2 path cannot close this gap on hardware: its backend is
observation-only, supplies pose and LiDAR while leaving person/owner perception
unmeasured, and refuses motion. This audit therefore supports a research-only
simulator/shadow implementation and leaves physical social motion **NO-GO**.

## Existing failure evidence

- The moved-obstacle corpus completed `0/3`; all three reached a 900-tick
  silent stall 4.26–4.50 m from the goal
  (`navigation-generalization/RESULTS.md:46-57`).
- In the expanded research baseline, all `24/24` blocker cases silently timed
  out. A post-hoc typed-looking supervisor over both `no_path` and
  `goal_blocked` converted `24/24` to explicit non-arrivals while preserving
  `60/60` nominal outcomes, but that state set was learned after the first run
  and has no untouched confirmation (`RESULTS.md:108-130`). It also terminates
  rather than tests obstacle departure and safe continuation.
- The persisted Follow/yield evidence includes seven misses, one simulated
  person contact, and −0.468 m minimum surface clearance
  (`navigation-generalization/RESULTS.md:46-57`).
- The “walk-with-me” suite does not establish moving side-by-side sidewalk
  behavior: its Follow owner is stationary, while curb stop and owner search
  are behavior stubs (`evals/walk_with_me/generator.py:281-296,451-491` and
  `runner.py:492-513`). The recorded `5/10` must not be interpreted as a
  crowded-sidewalk result.

## Why an obstacle can remain after a person leaves

The occupancy grid updates free rays by `-0.45`, occupied hits by `+0.85`, caps
log odds at `4.0`, and treats values at least `0.65` as occupied
(`navigation/grid_planner.py:127-178,476-530`). A saturated pedestrian cell
therefore requires eight unobstructed free observations to become free—about
0.8 s at 10 Hz. If the cell lies behind an occluder, it receives no free ray;
there is no temporal decay, so the ghost can persist indefinitely. Hard
inflation then closes neighboring cells (`grid_planner.py:686-702`).

The dynamic-agent layer is additive soft cost and cannot reopen a hard occupied
cell (`grid_planner.py:798-834`). Meanwhile:

- the Kalman tracker deletes after five misses, roughly 0.5 s at 10 Hz
  (`navigation/tracker.py:274-320,436-454`);
- disappearance removes the dynamic layer, but routine global replanning may
  wait five ticks (`configs/navigation/models/grid.yaml:34-48`,
  `navigation/grid_navigator.py:496-531`); and
- the final reactive gate reopens immediately on a fresh clear scan and has no
  release hysteresis (`navigation/reactive_safety.py:471-609`).

There is no blocker-departure event, evidence-valid clear streak, or
departure-to-resume metric joining these components.

## Why the progress supervisor cannot explain every stall

The current budgets are unrelated:

| Mechanism | Current approximate budget |
|---|---:|
| General progress watchdog | 200 ticks / 20 s, two semantic replans |
| No-route/unroutable commitment | 60 ticks / 6 s |
| Obstacle-block commitment | 60 ticks / 6 s; people excluded |
| Social-yield patience | 8 s; 12 s re-ask; two asks |
| Yield episode release bookkeeping | 3 s |
| Owner-search budget | 45 s |

Sources: `configs/navigation/default.yaml:24-32`,
`navigation/pipeline.py:4595-4709,5631-5729`,
`core/yield_policy.py:142-172,457-578`, and `configs/robot.yaml:84-90`.

The progress watchdog executes before the final collision-brake verdict and
discounts a person blockage only when scalar nearest distance is inside one
static ring (`navigation/pipeline.py:1415-1463,4595-4632`). It can therefore
misclassify predictive reaction-ring stops, TTC-only stops, slow comfort crawl,
and downstream runtime stops. Yield accounting recognizes the literal
free-form note segment `person_stop`; it does not join those other causes
(`core/yield_policy.py:128-139`).

## What can be reused

- `navigation/tracker.py`: CV Kalman, covariance, Mahalanobis gate, Hungarian
  association, 3-of-5 confirmation, five-miss deletion. Its
  `existence_probability` field is explicitly an unused IPDA seam.
- `navigation/dynamic_costs.py`, `dynamic_layer.py`, and
  `traffic_aware.py`: two-second CV/TTC costs, age-aware tracks, approach
  candidate ranking, and ramp memory.
- `navigation/yield_aside.py`: bounded space-time corridor/yield candidates.
- `navigation/reactive_safety.py`: direction-aware final person/obstacle gate,
  reaction-distance augmentation, and TTC brake. Preserve it as an independent
  disposer.
- `evals/companion_nav/runner.py:370-627,852-925`: production-order dispatch
  replica and actor rig that can be extended with departures, dropout, and
  scripted trajectories.
- `evals/external/barn_v9_liveness.py`: note-independent stationary-run and
  safe-escape witness patterns.

## Information lost before planning

The tracker retains covariance, but runtime serialization reduces dynamic
agents to `x`, `y`, `vx`, `vy`, and radius
(`runtime.py:791-805`; `navigation/dynamic_layer.py:159-184`). Age, source
timestamp, covariance, existence/confidence, identity, visibility/occlusion,
sensor provenance, interaction role, and multimodal intent are absent from the
planner contract. The collision brake receives only nearest-person distance
and is radial (`navigation/collision.py:100-189`). The richer final reactive
gate is bearing-aware, but it too receives only nearest distance/bearing/TTC,
not per-agent future distributions.

Owner prediction is separate and applies only to the owner. Direct Follow is a
point chase with obstacle hold rather than a route-planned, liveness-aware
formation controller (`navigation/follow.py:97-194,650-669,858-926`). Stranger
filtering by geometric proximity to the owner is vulnerable to close groups
and ID swaps (`follow.py:1358-1382`).

## Missing venue semantics

`maps/crossing.py` provides a disconnected curb/announcement/owner-voice/
geofence policy primitive, while the validator explicitly has no road-crossing
skill (`brain/validator.py:630-656`). The simulator's crosswalk is a static
semantic polygon, not perceived traffic state (`perception/city_semantics.py:
267-289`). Repository search found no runtime consumer of
`CrossingModePolicy`.

No elevator implementation or evaluator exists: no door phase, egress
priority, threshold gait, capacity, call/floor interaction, cabin localization,
or destination-exit transition was found.

## Minimal product seam to test next

Introduce a proposal-only pure decision before final safety:

```python
decide_social_liveness(
    snapshot,
    route_corridor,
    previous_state,
    config,
) -> SocialLivenessDecision
```

It consumes requested and finally dispatched motion, achieved progress, typed
planner state, fresh swept-corridor/free-ray evidence, per-track uncertainty/
existence/visibility/role, semantic venue and prior blocker state. It returns
only `HOLD`, `RESUME_ELIGIBLE`, `SLOW_FLOW`, `YIELD_ASIDE`, `REPLAN`, or `ASK`,
with a cause, blocker ID, risk upper bound, evidence age, and clear streak. It
does not emit velocity and cannot override reactive/TTC safety.

The first untouched evaluation should extend `_ActorRig` with temporary
sidewalk blockers and measure actual-departure→evidence, evidence→first final
nonzero command, departure→0.5 m progress, false release/contact, safely
avoidable stop time, restart chatter, and p95 slices by occlusion, dropout,
direction, and crowd flow. Then add moving-owner formation, crosswalk authority,
and elevator phase scenarios.
