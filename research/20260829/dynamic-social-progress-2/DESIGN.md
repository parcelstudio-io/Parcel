# DSP-2 — robust staging, evasion, and fast safe resume

**Status:** frozen before implementation or rollout  
**Date:** 2026-08-29  
**Evidence tier:** authored deterministic 2-D simulation with noisy tracks; no
camera, LiDAR, Go2 dynamics, human participant, ROS graph, Orin timing, or
physical-safety claim

## Question

The 2026-08-26 dynamic-social study found contact episodes in every arm. In
the predictive/semantic arms, all contacts came from a scripted person who
continued into a robot that had already commanded hold. DSP-2 asks the narrow
follow-up:

> Does a robust reachable-set candidate selector, context-specific safe staging,
> and asymmetric `BRAKE -> CLEAR_CONFIRM -> CREEP -> GO` release state reduce
> false stalls and prevent actor-into-stationary contacts without weakening the
> hard collision or semantic boundary?

This is not a search for one smaller "safe distance." The policy must condition
on relative velocity, uncertainty, predicted swept-volume overlap, braking,
visibility, corridor geometry, and semantic phase. A learned or predicted score
may rank candidates but may never admit a candidate rejected by the final
deterministic envelope.

## Frozen population and split

Create a new manifest before rollout. Whole episodes—not frames—are split into
train/development/test families. Test actor trajectories and sensor seeds must
be disjoint from the 2026-08-26 study and from DSP-2 development.

The population covers:

- sidewalk: owner-alongside, same-flow pass, oncoming, cut-in, crossing,
  overtaking, sudden stop/turn, group gap, occlusion, clear flicker, and a
  non-responsive actor advancing into the stopped robot;
- crosswalk: unauthorized curb wait, authorized entry, lateral flow, late
  entrant, persistent blocker, owner group, and a mid-crossing intrusion; and
- elevator: exit-first, temporary clear, occluded egress, occupied/full car,
  narrow entry, closing/reopening doorway, and a non-responsive exiting actor.

Each test family runs at least five independently derived sensor seeds. Sensor
mutations include bounded latency, position noise, dropped detections, retained
tracks, covariance growth, track-order permutation, and explicit free-ray
flicker. Actor truth and future trajectories are scorer-only. Policy input
contains only current/past noisy tracks, freshness, covariance, observed
corridor certificates, semantic phase, and robot state.

Responsive and non-responsive people are separate scenario strata. A
responsive actor may avoid the robot only through a frozen authored response
law; no arm may assume cooperation.

## Frozen arms

All arms pass the same final current-geometry/braking monitor and semantic
resource gate.

1. **S0 — semantic hold champion.** Re-run the 2026-08-26 A3 semantic lattice
   on the new population with no parameter changes.
2. **S1 — robust candidate MPC.** Score bounded hold, forward, diagonal,
   lateral, and retreat candidates against a two-second reachable tube formed
   from constant-velocity, stop, bounded-turn, and acceleration hypotheses plus
   covariance inflation. Choose maximum worst-case clearance/progress subject
   to the hard envelope. If the stationary trajectory is unsafe because a
   person continues toward it, select a braking-reachable escape only when the
   escape itself is robustly safe.
3. **S2 — S1 plus context staging.** Sidewalk yielding targets a visible free
   shoulder pocket while preserving the owner side. Crosswalk behavior may not
   reverse after committed entry and must retain a frozen time-to-clear margin.
   Elevator behavior stages outside and to the side of the door plane, keeps
   the exit corridor free, and may retreat from the threshold when an exiting
   actor advances.
4. **S3 — S2 plus asymmetric liveness.** One fresh high-risk frame enters
   `BRAKE`. Persistent approach with a safe escape enters `YIELD_ESCAPE`.
   Release requires three consecutive fresh low-risk/corridor-clear frames,
   then at least 0.4 seconds of bounded `CREEP` before `GO`. Any stale frame,
   risk rebound, semantic-phase change, or hard-monitor intervention returns
   to `BRAKE`.

The state machine is deterministic and explicit. No random body twitch or
expressive motion runs in a safety-critical interaction phase.

## Metrics

Report exact episode counts and per-family results for:

- contact and near-contact episodes, minimum/p05 surface clearance, and
  actor-into-stationary contacts;
- final-envelope intervention, current hard-floor, crosswalk authorization,
  crosswalk reverse-after-entry, elevator egress/capacity/door-plane, and
  staging-region violations;
- completion, path efficiency, false-block seconds, wrong-stall episodes,
  deadlocks, and retreat/evasion use;
- truth-clear -> evidence-clear, evidence-clear -> decision, and decision ->
  translating latency separately, with p50/p95;
- stop/start transitions, acceleration/jerk proxy, lateral travel, and minimum
  time to collision; and
- calibration of the reachable-tube risk against held-out contact-within-two-
  seconds truth. Calibration is diagnostic and never motion authority.

## Hypotheses and gates

### D2-H1 — robust escape fixes stop-only contact

S2 and S3 each have zero contact episodes, zero actor-into-stationary contacts,
zero hard-envelope admissions, and zero semantic violations. A single such
event refutes H1 and makes that arm ineligible for carry-forward.

### D2-H2 — staged semantics improve task completion

Against paired S0, S2 improves combined crosswalk/elevator completion by at
least 15 percentage points without lower sidewalk completion, higher
near-contact count, or any forbidden entry/reverse/egress/staging event.

### D2-H3 — asymmetric liveness resumes promptly without chatter

Against paired S2, S3 reduces false-block time by at least 20%, has
evidence-clear-to-decision p95 at most 0.4 seconds and decision-to-motion p95 at
most 0.2 seconds, and reduces stop/start transitions by at least 20%, while
retaining every H1 invariant and no worse completion.

### D2-H4 — robustness holds on the hardest strata

S3 completes at least 80% of otherwise feasible non-responsive-actor episodes
and at least 80% of clear-flicker/occlusion episodes, with zero release based
only on missing detections and every H1 invariant intact.

All clauses are conjunctive. Results are `SUPPORTED` or `REFUTED`; a useful
mechanism may be retained for research even when a hypothesis is refuted, but
no measured threshold becomes a physical clearance setting.

## Integrity procedure

1. Freeze the generated manifest, source hashes, parameters, seeds, and split
   inventory before reading any test outcome.
2. Fit or select nothing on test. This study has no learned arm; any development
   parameter choice is recorded before the first test rollout.
3. Run two fresh processes and require byte-identical normalized episode
   digests.
4. Use an independent verifier that recomputes inventory, scenario lineage,
   safety/semantic counters, metrics, and hypothesis decisions without calling
   the policy implementation.
5. Mutate one action, one actor trajectory, and one semantic-phase record; each
   tamper must be rejected.

## Claim boundary and next rung

A pass would justify carrying robust candidate selection, safe staging, and the
explicit liveness state into product-shadow replay and a higher-fidelity social
simulator. It would not establish safe proximity, pedestrian intent prediction,
human comfort, camera/LiDAR tracking, Go2 stopping, elevator thresholds,
crosswalk traffic safety, or physical readiness. The next required rung is the
same frozen contract in HuNavSim/ROS 2 or Habitat/Isaac with responsive people,
then recorded-sensor replay, motors-disabled HIL, and only later separately
approved tethered motion.
