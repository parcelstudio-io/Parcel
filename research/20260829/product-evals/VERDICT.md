# Independent interpretation: current-tree product evaluations

## Decision

**Motion-enabled mount on the Unitree Go2 EDU+: NO-GO.**

An observe-only, motors-disabled sensor/computing integration can proceed after the
mechanical, electrical, thermal, e-stop, and data-capture checklist is reviewed.
Nothing in this folder licenses autonomous movement, stairs, sidewalks, crosswalks,
elevators, or close pedestrian operation.

## Why this is the controlling verdict

1. The fresh, repeatable NAV_INSTRUCT result is 34/125 (27.2%).  Planning,
   termination, grounding, search, and false-arrival errors are all present.
   The dedicated interruption study also refutes admission, return-efficiency, and
   blind steering hypotheses; queue accuracy is 66.7% and arrival authorities
   disagree on 17/80 legs.
2. Current follow behavior misses two of nine scripted follow cases. In DSP-2,
   S2 and S3 each contacted in 25/145 episodes and all four registered
   safety/liveness hypotheses were refuted.
3. Four of nine software acoustic gates fail before any real room, microphone,
   loudspeaker, echo cancellation, owner voice, or Starlink variability is added.
4. Historical conversation responses are semantically mixed/poor. MB-1 hosted Q
   completed 120/120 scenarios but failed every absolute gate: grounding
   0.6120–0.7274, coverage 0.2283–0.2883, 99/225 acknowledgments, 11–27/165
   completions, and 45 machine action flags. Hosted D stopped at 2/120, and no
   calibrated human quality rate or paired effect exists.
5. DMC-4's source-level owner-authored journal and journal-only authenticated
   bridge pass their frozen transaction gates. The normal runtime now drains
   the journal into bounded, process-local, non-actuating Model-B frames, but
   does not bind them to a persisted cursor, live speech epoch, provider, or
   audio path. The retained old-path LIT-1 traces
   expose the consequence directly: five failed bench terminals produced five
   “I've reached the bench” claims.
6. The positive embodied-plan result is four supported frozen kinematic cases.  It
   is an integration smoke test, not a generalization or physical-safety result.

## Promotion gates that must close

- Extend the new disarmed DMC-4 runtime-frame composition with production key
  ownership, a persisted cursor, restart supervision, live speech-epoch
  cancellation, separate-child resume lineage, provider context, and audio
  tests while retaining typed progress/suspend/resume/replan/blocked events.
- Raise family-disjoint NAV_INSTRUCT and social-navigation performance, with zero
  false arrivals and zero contacts, across multiple layouts and seeds.
- Implement moving-owner tracking/re-identification and formation control without
  oracle identity or ground-truth semantics.
- Pass deterministic acoustic gates with physical mic/speaker/AEC replay and real
  barge-in, then test Starlink loss/jitter and offline fallback.
- Run payload-randomized Go2 dynamics, sim-to-sim policy transfer, gateway fault
  injection, hardware-in-loop timing, stationary hardware checks, and tethered
  stop-distance characterization.
- Keep learned Model A outputs proposal-only behind the independent safety shield
  until they outperform the explicit temporal controller on blind families.

## Simulator feasibility

Simulation is **highly feasible** for contract learning, interruption/queue policy,
fault injection, data generation, counterfactual replay, social-scenario coverage,
and relative policy ranking.  It is **moderately feasible** for perception and
locomotion transfer when trained with dynamics, sensor, latency, payload, and visual
randomization and tested in a second engine.  It is **not sufficient** to establish
mount integrity, thermal/power margins, real acoustics/AEC, camera/LiDAR calibration,
foot-ground interaction, actuator braking, or human-safe stop distance.
