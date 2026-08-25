# Task 4 · QEV-1 — prototype quality gate and mount decision

**Date:** 2026-08-24 (America/New_York)

**Status:** COMPLETE · MOTION `NO-GO` · STATIONARY STAGE-0 `CONDITIONAL`

**Author:** Codex, after independent review of Claude's accepted
`DEPLOYABLE-MOTION-SEAM`

## Owner request

Assess the current prototype code, implement and run the missing quality
evaluations for conversation and navigation tasks, decide whether the software
is ready to be mounted on the physical prototype, and evaluate how much
simulation can improve the remaining capabilities.

This task is the dated decision record. The detailed measurements, commands,
limitations and simulator assessment are in `QUALITY_EVAL_REPORT.md`.

## Exact review boundary

The reviewed commit was
`2ce919a1d49ba55224ae7c6cd66f3a99255a8ca5`
(`feat: DEPLOYABLE-MOTION-SEAM — installable gateway, production client,
hung-I/O containment`). `main`, `origin/main` and `origin/HEAD` agreed at that
commit when the evaluation began.

Claude's seam is accepted as useful **desktop/bench** work:

- the gateway is installable on CPython 3.10;
- the typed Unix client, restart-disarmed behavior and bounded hung-vendor-I/O
  behavior have focused test evidence; and
- the service definition now names the real executable and refuses an absent
  vendor body instead of silently selecting fake Sport.

Its evidence ceiling is also binding: the product runtime does not yet compose
the client, `--sport vendor` deliberately refuses, no Unitree SDK port exists,
no Orin service has run, and no physical stop envelope has been measured.
This quality task does not reinterpret fake-Sport evidence as robot evidence.

The working overlay created for this evaluation consists of conversation
scoring/provenance changes, acoustic-eval fail-closed teardown changes, their
tests, and this task record. Generated reports and ledgers were directed to
`/tmp/parcel-quality-20260824.VYhnnR`; no tracked result ledger was retained.

## Decision

### Motion-enabled installation: `NO-GO`

Do not authorize stand pulses, floor translation, autonomous navigation,
Follow, or unattended operation. Independent fresh evidence contains all of
the following release blockers:

1. the shipped localization/navigation path declares false arrival after a
   simulated pose kidnapping;
2. a moved-obstacle/no-route case silently remains running for 900 ticks;
3. the 125-episode instruction-navigation suite reaches only 0.256 success and
   records six false arrivals;
4. the voice-to-runtime-to-MuJoCo suite has product-path semantic-goal and
   arrival-verification failures;
5. fresh BARN PR succeeds in only one of ten worlds, with nine zero-progress
   stops;
6. Follow passes only seven of nine Follow scenarios, its slow acceptance gate
   fails four of five tests, and the yield extension produces one simulated
   hard collision/contact; and
7. the real product still has no runtime-wired vendor motion client, real
   physical observation source, commissioned LIO, owner-perception pipeline,
   independent STOP measurement or stopping envelope.

### Stationary observe-only installation: `CONDITIONAL`

A mechanically secure, supervised Stage-0 installation may be prepared only
to collect sensor/audio/thermal/power evidence, and only when all of these are
true:

- Unitree Sport motion is disabled and no Parcel motion authority is armed;
- the operator holds a tested independent remote stop;
- the robot is supported against translation and the runbook has a second
  person for power isolation;
- only log/capture services are enabled; a service or dependency failure
  cannot fall through to motion;
- mounts, power, thermals, storage, clock mapping and extrinsics are inspected;
  and
- every bag names hardware identity, firmware, calibration, clock provenance
  and teardown state.

This conditional rung is permission to gather evidence, not permission to
drive. No robot was available in this evaluation, so even Stage 0 remains
unexecuted.

## Recommendation: execute `PRE-MOUNT-CLOSE-1`

Before requesting a motion-enabled mount, complete one product-path closure
tranche in this order:

1. **Wire, but do not arm, the motion seam.** Compose
   `MotionGatewayClientV1` into the normal runtime against fake Sport only.
   Prove that runtime death, gateway death/restart, TTL expiry, stale feedback
   and reconnect all leave authority disarmed. Keep the vendor port absent and
   keep physical motion forbidden.
2. **Make localization discontinuity fail closed in the shipped path.** Move
   the proven ambiguity/discontinuity latch into the product composition.
   The R4b kidnapping refuter must yield zero false arrivals; operator re-arm
   may proceed only after independent pose validation.
3. **Terminate no-route honestly.** The R3 moved-obstacle case must return a
   typed `blocked`/`unreachable` result inside a bounded deadline instead of a
   900-tick running stall.
4. **Constrain conversation to installed capabilities and evidence.** The
   live model must not emit unavailable action names or claim motion,
   perception, arrival, durable memory or monitoring without the matching
   verified result. Re-run the ten-case live quality set and the 13-turn
   personal set; set a release bar before tuning.
5. **Repair the acoustic evaluator before using its numbers.** Give the
   PipeWire rig explicit port ownership/routing, cancellable reads, a bounded
   first-frame deadline and zero-process/node teardown proof. Then run the
   frozen endpointing, barge-in, duplex and prosody families. Mounted AEC and
   human-voice acceptance still belong to Stage 0/box day.
6. **Keep Follow disabled.** Do not promote Follow from scripted/oracle-owner
   simulation. Fix its red jerk/predictive/yield cases and later require real
   owner identity, crossing, occlusion and reacquisition evidence.

After those software gates are green, perform the stationary Stage-0 capture
described above and replay the exact real bags through the production
assembler/localizer. Only then should a separately authorized, tethered,
single-axis pulse be considered.

## Acceptance contract for `PRE-MOUNT-CLOSE-1`

The tranche is complete only when:

- the normal runtime reaches fake Sport solely through the Unix gateway and
  starts/restarts disarmed;
- all shipped R4b seeds have zero false arrivals and an anti-vacuity witness
  shows that the discontinuity was actually injected;
- all shipped R3 seeds end in a typed terminal failure within the declared
  bound and never translate while evidence is invalid;
- conversation evaluators exit nonzero on a red or incomplete report;
- live conversation emits only capability-registry actions and makes no
  unsupported world-state claims;
- the acoustic rig captures nonzero samples and leaves zero matching nodes and
  child processes, including when no samples ever arrive;
- Follow remains default-off and every existing collision/contact gate is
  green before any enable discussion;
- the focused suites pass three consecutive guarded runs, Ruff adds no debt,
  and the integrator's commit gate passes once; and
- the close record says `desktop/bench` and explicitly does not claim Orin,
  robot, mounted audio, physical stop or motion readiness.

## Simulator work authorized by the recommendation

Simulation is high-value for capability improvement, but it is not promotion
evidence. Use it in this sequence:

1. deterministic gateway/runtime fault injection;
2. existing MuJoCo/city plus BARN for no-route, false-arrival, dropout,
   kidnapping, clutter and recovery refuters;
3. Stage-0 bag replay through the exact observation and localization path;
4. social-navigation identity/crossing/occlusion campaigns; and
5. official Unitree articulated MuJoCo for SDK axes, rates and command-shape
   checks after a real vendor adapter exists.

MetaUrban is a plausible later social-navigation source but needs an adapter;
Habitat has low near-term return because only the public adapter contract is
currently runnable, not a licensed scene/evaluator score. No simulator may set
the physical stopping distance, prove mount safety, validate real clocks or
extrinsics, prove AEC, or authorize motion.

## Stop conditions

Return `NO-GO` without discretion if any of these is true:

- a localization discontinuity can remain `HEALTHY` and later declare arrival;
- a no-route state can remain nonterminal indefinitely;
- a runtime or service restart can restore authority;
- motion can bypass the gateway or select fake Sport in a robot profile;
- independent STOP, operator ownership or the physical stop envelope is
  missing;
- a real observation carries simulated truth or unknown calibration;
- Follow can move with ambiguous/lost owner identity;
- mounted audio cannot prove local STOP under playback/noise; or
- any physical trial is proposed from simulator-only evidence.

## Deliverable

See `QUALITY_EVAL_REPORT.md` for the complete evaluation matrix, exact fresh
measurements, implementation changes, physical readiness ladder, simulator
feasibility and known evidence limitations.
