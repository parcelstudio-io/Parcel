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
3. Corrected acoustic v2 passes 6 gates, fails 3, and marks 2 not measured. Four
   of 13 endpoint cases are invalid, virtual-audible acknowledgement p50 is
   0.790 s, and isolated acoustic STOP plus physical motion sync remain
   unmeasured. A two-run 1,560-cell direct sensitivity study found 0/30 declared
   settings pass and failed corrected-rig parity, so it nominates no production
   threshold. No real room, mounted microphone/loudspeaker, AEC, owner voice, or
   Starlink variability has been tested.
4. Historical conversation responses are semantically mixed/poor. MB-1 hosted Q
   completed 120/120 scenarios but failed every absolute gate: grounding
   0.6120–0.7274, coverage 0.2283–0.2883, 99/225 acknowledgments, 11–27/165
   completions, and 45 machine action flags. Hosted D stopped at 2/120, and no
   calibrated human quality rate or paired effect exists.
5. DMC-4's source-level owner-authored journal and journal-only authenticated
   bridge pass their frozen transaction gates. The normal runtime now drains
   the journal into bounded, process-local, non-actuating Model-B frames, but
   those frames only reach a local queue. They preserve and drain-revalidate
   available authority lineage, but the lane does not bind them to persisted
   executive/outbox/read/provider-ack state, an independently authenticated
   live speech epoch, provider, or audio path. Transition freshness also starts
   at poll rather than commit. The retained old-path LIT-1 traces
   expose the consequence directly: five failed bench terminals produced five
   “I've reached the bench” claims.
6. The positive embodied-plan result is four supported frozen kinematic cases.  It
   is an integration smoke test, not a generalization or physical-safety result.
7. Model A has no qualified learned artifact or production binding. The normal
   launcher neither injects nor arms a commissioned physical manager, normal
   observations carry simulation provenance, and `Go2Backend` rejects motion.
8. DSOAK-1's retained artifact self-reports 12.050004 desktop wall-clock hours
   and 66,434 procedural episodes; all 17 gate predicates pass post-run
   aggregate checks and it records 664 sampled replays / zero mismatches. That
   is only partially corroborated process-durability evidence: the unsigned
   monitor began 2.365 h late, strict process/temporal provenance is absent,
   the narration oracle is refuted, key safety zeroes are coupled, and
   deterministic L0 still outperformed learned A1 (66,433 vs 66,116 successes).
9. The August 30 commit tier is green, but the complete extended nightly tier
   is red. Six degraded-pose arms missed frozen success floors, while the slow
   selection exposed literal/scene, navigation, pedestrian-evaluator, and
   wheel-environment findings. Bounded remediation cleared the literal/scene,
   wheel, and lamppost cases; the repeated slow selection is 1 failed / 74
   passed / 8 skipped / 3 expected failures / 1 unexpected pass, with only the
   unchanged 0.875-vs-0.90 person-cell pin red. This cannot erase the
   degraded-pose capability result or authorize motion.

## Promotion gates that must close

- Extend the new disarmed DMC-4 runtime-frame composition with production key
  ownership, a persisted cursor, restart supervision, live speech-epoch
  cancellation, separate-child resume lineage, provider context, and audio
  tests while retaining typed progress/suspend/resume/replan/blocked events.
- Raise family-disjoint NAV_INSTRUCT and social-navigation performance, with zero
  false arrivals and zero contacts, across multiple layouts and seeds.
- Implement moving-owner tracking/re-identification and formation control without
  oracle identity or ground-truth semantics.
- Use corrected acoustic v2 without fitting its discovery corpus: build a frozen
  human/room/AEC holdout, repair semantic endpointing and persistent-stream
  audible latency, and add isolated STOP channels plus actual motion observation.
  Then pass mounted mic/speaker/AEC, real
  barge-in, Starlink loss/jitter, and offline-fallback tests.
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
