# Independent completion authority — preregistered design

**Date:** 2026-08-26 (America/New_York)
**Repository baseline:** `f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8`
**Hardware exercised:** none
**Evidence tier:** deterministic synthetic architecture experiment over the
existing NAV-CORE/NAV-ACCEPT physical-shaped room, pose, LiDAR, planner and
reactive-safety loop

## Decision question

Can a completion authority that latches localization discontinuities and
requires a fresh, independently generated target-relative landmark witness
remove the aliased-kidnap false arrivals that survive covariance and temporal
streak checks, while preserving nominal completion and producing an explicit
uncertain outcome when the witness is unavailable?

The preceding navigation-generalization experiment found three aliased
kidnaps in which both the commissioned completion rule and a five-tick rule
declared arrival 5.21--5.30 m from truth. All five temporal samples shared the
same wrong MAP hypothesis. This package tests a different *kind* of evidence;
it does not tune that streak.

## Freeze-before-run policy

This document fixes the scenario generator, policy constants, metrics and
decision thresholds before the first result run. The 360-case matrix uses no
rows or seeds from the earlier three-case alias experiment. Results may refute
the proposal. Any post-result threshold or matrix change creates a new schema
and is exploratory, never a replacement for this run.

No product code, configuration, prior research artifact, frozen corpus or
ledger will be edited. The experiment imports:

- NAV-CORE's room, kinematic body, drifting ODOM + scan-matched MAP stack,
  synthetic LiDAR and scorer;
- NAV-ACCEPT's production-commissioned point-goal controller; and
- the prior navigation-generalization package only as a hashed provenance
  dependency, not as an input dataset.

## Arms

All arms receive the same MAP pose and commissioned planner behavior. Ground
truth remains in the inherited NAV-CORE scorer and the synthetic sensor
boundary; no completion-policy input contains truth pose, truth goal distance,
`arrived`, `false_arrival` or scenario kind.

### C0 — covariance only

The current commissioned rule: declare when MAP health is `HEALTHY` and the
chance-constrained probability of lying inside the 0.50 m goal disc is at
least 0.90.

### C1 — correlated five-tick streak

Require C0 to remain true for five consecutive 10 Hz ticks. While quarantined,
hold velocity at zero. This is the known negative control: repeated samples
from one MAP hypothesis are not independent evidence.

### H2 — latched discontinuity plus independent witness

The candidate has two local safeguards:

1. A displacement/impulse sensor proxy, separate from MAP/ODOM, emits a noisy
   scalar discontinuity score. A score of at least 0.70 latches motion and
   completion. The latch never clears merely because covariance becomes small.
2. Every completion, latched or not, requires two fresh observations of the
   requested physical landmark, at least 0.20 s apart. Each observation must:
   have target descriptor score at least 0.65; beat the best runner-up by at
   least 0.12; have age no greater than 0.35 s; and report landmark range in
   the 0.90--2.30 m band expected at the NAV-CORE stand point.

The descriptor sensor is queried at 5 Hz. A qualifying pair can therefore add
at least 0.20 s. A pending/latching condition that cannot obtain independent
evidence within 3.50 s terminates as typed `localization_uncertain`; it does
not silently wait, re-use old evidence or declare from MAP confidence.

The candidate may pass through the commissioned planner's requested velocity
only while unlatched and before a MAP arrival claim. A latch or pending
completion commands a zero velocity in this architecture experiment.

## Why the witness is not an oracle

The target-relative sensor is a separate noisy synthetic measurement, not a
call to the scorer:

- It observes physical landmark instances within a 3.20 m active-scan range.
- It scores all six landmark identities from a deliberately confusable
  descriptor model. C2 twins have high cross-similarity (0.72 versus 0.95 for
  the correct identity), so a wrong twin produces a high raw target score but
  should lose to its runner-up.
- It adds deterministic per-frame Gaussian score and range noise, 8% base
  frame loss, 0--0.20 s latency and explicit blackout cases.
- Its range is to the observed wall landmark, not to the scorer's goal point.
  The 0.90--2.30 m gate is intentionally broader than the 0.50 m truth-arrival
  disc and therefore cannot reproduce the scorer predicate.
- The discontinuity proxy is also imperfect: every eighth alias case loses
  the impulse sample, and registered nominal/dropout cells inject false
  discontinuity artifacts. Success cannot depend on a perfect kidnap flag.

The integrity verifier will assert that policy-facing evidence schemas do not
contain scorer-only field names. The result must also demonstrate non-perfect
evidence: at least one nominal query must be missing/ambiguous and at least one
alias query must have a raw target score above 0.65. This is an architectural
anti-tautology check, not physical sensor validation.

## Untouched 360-case matrix

Case IDs and seeds are generated from SHA-256 of the literal schema
`parcel.independent-completion.matrix.v1` and the listed factorial coordinates;
the earlier seeds 101/202/303/404/505/606 are not used.

### Nominal — 120 cases

Full factorial: 4 NAV-CORE clutter layouts x 5 starts x 6 goals. LiDAR dropout
is disabled so this cell isolates normal completion. Every tenth canonical
case injects one false discontinuity artifact at its first MAP claim, testing
whether independent evidence can re-arm a false latch.

### Aliased kidnap — 120 cases

Full factorial: 5 starts x 6 goals x kidnap times 0.0/0.2/0.4/0.6 s in the
C2-symmetric NAV-CORE room. Every eighth canonical case drops the independent
discontinuity sample at the jump. Those blind cells force the witness itself,
rather than a perfect latch detector, to reject the wrong C2 landmark.

### Independent-sensor dropout — 120 cases

Full factorial: 4 layouts x 5 starts x 6 goals. When the commissioned MAP rule
first presents a completion candidate, the target-relative sensor begins a
registered query-relative blackout of 0.60/1.20/1.80/4.20 s, selected by the
layout coordinate. The 30 long-blackout cases exceed the 3.50 s uncertainty
deadline by construction; the other 90 test bounded recovery. Every fifth case
also injects a false discontinuity artifact at that first MAP claim.

Query-relative blackout is a deliberate interface fault injection, not a
claim about camera physics. It makes the absence-of-evidence branch occur at
the safety decision under test without consulting truth distance.

## Metrics

Reported per arm and case family:

- false arrivals and false-arrival rate;
- true declared arrivals and nominal recall;
- first MAP-claim to independent authorization latency;
- latch-to-rearm latency for injected false-latch cases that recover;
- `localization_uncertain`, other typed outcomes and silent outcomes;
- missing, raw-high-target, margin-qualified and paired witness frames;
- contacts and opportunity-set counts, where an alias opportunity is a case in
  which C0 actually made a false completion claim.

Percentiles use the nearest-rank definition over deterministic finite values.

## Falsifiable acceptance gates

The H2 hypothesis is supported only if every gate passes:

1. **Matrix validity:** exactly 120 cases per family; 360 distinct case IDs;
   all three arms run every case; at least 80 C0 alias false-arrival
   opportunities exist.
2. **Negative controls bite:** C0 and C1 each falsely arrive on at least 80% of
   C0's alias-opportunity set.
3. **Alias safety:** H2 has zero false arrivals over all 120 alias cases,
   including zero in discontinuity-blind cells.
4. **Nominal recall:** H2 truly arrives in at least 118/120 nominal cases
   (98.33%) and has no more contacts than C0.
5. **Bounded recovery:** H2 recovers at least 85/90 short-blackout cases; its
   p95 first-claim-to-authorization latency across recovered short-blackout
   cases is no more than 2.50 s.
6. **Typed uncertainty:** every unresolved H2 alias or dropout case terminates
   `localization_uncertain`; no H2 case ends in a silent timeout. All 30
   4.20-second blackout cases must be uncertain rather than falsely complete.
7. **False-latch re-arm:** at least 20 injected false-latch cases re-arm; p95
   latch-to-rearm latency is no more than 2.50 s.
8. **Evidence audit:** at least one H2 nominal/dropout query is missing or
   ambiguous, at least one alias query has raw target score >=0.65, no
   policy-facing schema contains scorer-only fields, and both deterministic
   reruns have identical payload digests.

## Evidence limits

This is synthetic, architectural evidence only. The landmark descriptor,
active 360-degree observation, latency/dropout, impulse detector, ODOM drift,
scan matching and kinematic body have not been calibrated against a Go2,
Mid-360, camera or AGX Orin. The room has no realistic texture, lighting,
occlusion, footfall, slip, actuator delay, pickup physics, stairs or network
transport. A pass justifies implementing and collecting data for this
completion seam; it cannot authorize physical locomotion or establish a
fielded false-arrival probability.
