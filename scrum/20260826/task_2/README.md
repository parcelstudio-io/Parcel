# Task 2 · SOCIAL-PROGRESS-1 — pedestrian-aware progress and semantic venues

**Date:** 2026-08-26 (America/New_York)
**Status:** RESEARCH COMPLETE · `SOCIAL-PROGRESS-1` SHADOW SLICE IMPLEMENTED ·
SIMULATOR EVALUATION READY · PHYSICAL SOCIAL MOTION `NO-GO`

**Owner problem:** The companion dog must walk with its owner among pedestrians
without freezing after a temporary obstacle, moving on a mere missed detection,
or treating close co-walkers the same as head-on/crossing people. It must also
behave coherently at crosswalks and in tight elevators.

## Recommendation

Build a visibility-aware social-progress layer upstream of the existing final
reactive gate. Give it per-agent tracks, probabilistic 2–4 s occupancy tubes,
fresh swept-corridor free-space evidence, cause-coded liveness, bounded probe
resume, committed passing side, formation switching, and explicit crosswalk/
elevator state machines. Keep the reactive gate, E-stop, gateway, speed caps,
and hard person envelope independent and unchanged.

Do **not** solve this by shortening the current persistence or yield timers.
Parcel presently has incompatible clocks: a saturated hard-grid pedestrian
cell needs about eight visible free rays (~0.8 s at 10 Hz), an occluded grid
cell has no decay, a dynamic track deletes after five misses, normal replan may
wait five ticks, and reactive safety can reopen after one fresh clear scan.
“Track missing” and “corridor explicitly free” must become separate states.

## Research result behind the task

The preregistered research harness exercised five arms across 475 deterministic
2-D episodes: radial wait, CV-TTC, uncertainty/visibility mixture, semantic
time-lattice, and a small learned risk critic. All four hypotheses were
refuted; no arm is promotable.

- Visibility-aware release eliminated missing-only resumes in its tested arm,
  but median visible-clear-to-motion was 1.85 s versus 0.80 s for the radial
  proxy. Evidence-to-motion was only 0.10 s, locating most delay in evidence/
  tracking rather than command release.
- The mixture arm reduced false-block time only 6.0%, lost 5.3 completion
  points, and had 20/95 contact episodes; every recorded contact was a scripted
  nonreactive actor advancing into a stationary robot.
- The semantic time-lattice improved combined crosswalk/elevator completion by
  18.2 points, sidewalk completion by 25 points, and recorded zero semantic or
  moving-into-hard-floor violations. It still had 20/95 actor-into-stationary
  contacts, so the hypothesis and promotion gate failed.
- The learned critic had AUROC 0.945, yet held-out false-negative rate was 4.12%
  and it increased false-block time 3.5% versus the semantic arm. This is direct
  evidence that good offline discrimination is not a closed-loop promotion
  result.

The harness uses authored 2-D truth, simple sensors, nonreactive actors and
oracle semantics. It did not run Parcel's product pipeline, ROS, Go2 dynamics,
natural camera/LiDAR perception, a deep trajectory model, or hardware. Its
contacts are rejection evidence for these candidate policies, not a calibrated
real-world incident rate.

## Build scope

### A. Typed evidence and track contract

Add `DynamicTrackV1` and `VisibilityEvidenceV1` carrying ID/class, world state,
velocity/covariance, existence probability, source/receive time, age,
visibility (`visible`, `occluded`, `out_of_fov`, `explicit_free`, `stale`),
camera/LiDAR provenance, owner identity lineage, and group/flow role.

Publish synchronized LiDAR mark/clear rays and camera frusta. A missed visible
detection may lower existence; an occluded/out-of-FOV miss only coasts with
growing uncertainty. Stale data never clears. People remain outside the
persistent static map; dynamic occupancy has its own time-indexed layer.

### B. Prediction and candidate planning

Benchmark in order:

1. calibrated CV/CA Kalman;
2. IMM stop/go/turn mixture;
3. ORCA and Social Force as fast interaction baselines/candidate generators;
4. chance-constrained velocity lattice or MPPI; and
5. Trajectron++ first learned challenger, with AgentFormer/diffusion only if it
   clears calibration, transfer and AGX timing gates.

Forecast distributions and calibrated occupancy risk, not a single intent
label. ORCA reciprocity and learned predictions are not safety guarantees.

### C. `SocialProgressV1`

Add proposal states `TRACK`, `SLOW_YIELD`, `HOLD_OCCUPIED`,
`HOLD_UNCERTAIN`, `PROBE_RESUME`, `COMMIT_PASSING_SIDE`,
`FORMATION_SWITCH`, `REROUTE`, `ASK_OWNER`, and `SAFE_HOLD` with typed cause,
blocker ID, evidence age, clear streak, risk upper bound, and recovery budget.

Replan continuously while held. Enter a jerk-limited probe only after the full
short swept corridor is explicitly free for the configured fresh-bundle
streak. Revoke it immediately on contradictory/stale evidence. Suppress generic
spin/back-up recoveries in crowds.

### D. Companion and venue semantics

- Sidewalk: left/right side-by-side formation region where width permits;
  trailing formation through bottlenecks; owner identity continuity; committed
  pass side; flow is only a soft prior.
- Crosswalk: `APPROACH_CURB -> WAIT_AUTHORITY -> OWNER_COMMITTED ->
  COMMIT_CROSS -> EXIT`; other pedestrians never authorize road entry; no
  comfort-only prolonged stop or side switch in the road.
- Elevator: `QUEUE_OFFSET -> VERIFY_OPEN -> ALLOW_EGRESS -> VERIFY_CAPACITY ->
  ENTER_TRAILING_OWNER -> PARK_HOLD -> EXIT`; disagreement means wait; no spin
  or reverse in the cabin.

All three are default off on the physical profile. Crosswalk and elevator need
separate traffic/door/threshold hazard work.

### E. Proximity learning contract

Never train a scalar “safe distance.” Commission the hard envelope from the
mounted swept footprint, worst measured sensing/control delay, braking
distribution by gait/surface, state-estimation/extrinsic uncertainty, and a
margin. Owner identity, density, urgency, and learned output cannot shrink it.

Learn only a directional soft comfort cost above that floor using relative
motion, role/consent, formation, group/flow, width, density, venue and escape
space. Unknown identity receives stranger treatment. Use consented preference
data and retain a conservative owner control.

## Qualification matrix

Freeze 1,200 solvable episodes—400 each sidewalk/crosswalk/elevator—plus 240
adversarial stress episodes, split by geometry, actor behavior, appearance,
sensor mutations and templates. Mix scripted nonreactive and reactive humans;
pair each blocker-departure case with a counterfactual. Add 17–40 actor
overload, occlusion/ID switch/ghost/dropout/skew, reversal/cut-in/group split,
curbs/signals/owner hesitation/vehicles, reflective elevator walls/door cycles,
localization jumps, control delay and braking variation.

Promotion floors:

- zero contacts, hard-envelope violations, unauthorized road entry,
  entry-before-egress, capacity violation, false unreachable, and avoidable
  deadlock;
- evidence-valid resume at least 99%; evidence-to-release p95 ≤0.40 s;
  evidence-to-motion p95 ≤0.80 s and max ≤2.0 s;
- false-block time ≤1% overall and episodes with >2 s false block ≤2%;
- task success ≥90% overall and ≥85% per venue; sidewalk formation ≥0.80; and
- local stack p99 ≤50 ms with zero 100 ms misses on the intended AGX workload.

Train in one human-behavior family and test in others. Use Parcel's deterministic
harness, SocialGym 2.0, HuNavSim, SocNavBench real-trajectory replay, the exact
Unitree MuJoCo/gateway contract, Isaac domain randomization, and finally
timestamped real-bag shadow replay. No candidate self-promotes.

## OWNS

- default-off typed dynamic-track/visibility/social-progress contracts;
- research-only free-space/existence filter and CV/IMM/time-lattice baselines;
- sidewalk/crosswalk/elevator simulators and frozen evaluator/metrics;
- product-path shadow logging after the same-path simulation contract exists;
- AGX timing/calibration reports and dated immutable research artifacts.

## MUST NOT TOUCH OR ENABLE

- physical Go2 motion, Follow, side-by-side, road crossing, elevator entry,
  stairs, or proactive approach;
- E-stop, TTL, final reactive/TTC gate, speed caps, sole-writer gateway, or
  startup-disarmed invariants;
- VLM/LLM/Starlink authority over clearance, traffic state, velocity, joints,
  or mission completion;
- learned reductions of the hard person envelope; or
- owner memory/live ports as research storage or test targets.

Research artifacts: `research/20260826/dynamic-social-progress/`.

## Implementation update

The default-off, proposal-only product seam is now implemented and verified.
The prototype simulator profile enables `mode: shadow`; the base/physical
profile remains disabled by absence. The observer runs after the unchanged
final dispatch gate and records typed requested/final/achieved motion,
planner-liveness facts, retained track visibility, and explicit LiDAR
free-corridor certificates in a bounded in-memory trace. It cannot issue a
command or authorize motion.

Verification completed: 104 focused/adversarial tests, 451 relevant regressions, and a
byte-identical replay of the frozen 475-episode research result. See
`research/20260826/dynamic-social-progress/IMPLEMENTATION.md` for the exact
boundary, evidence contract, results, remaining blockers, and next tranche.

Adversarial closure subsequently fixed the direct-HeadlessCity simulator/host
clock mismatch at observation ingress. Its time-zero-fresh/251-ms-stale
regression passed 1/1, and the final cross-surface focused suite passed 269
tests. The observer remains shadow-only and cannot authorize motion.
