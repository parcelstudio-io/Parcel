# H2b independent completion — preregistered holdout design

**Frozen:** 2026-08-26 (America/New_York), before either result run
**Hardware exercised:** none
**Authority:** research-only, default-disabled terminal-claim proposal; never motion

## Decision question

Does a strict completion contract that independently requires (1)
discriminative place identity, (2) an identity-rooted reset into a strictly new
pose epoch with scan and landmark residual agreement, and (3) conservative
target-relative terminal geometry eliminate false completion on aliased,
outside-boundary and broken-lineage cases while preserving nominal coverage and
supporting recovery after an aliased localization reset?

H2 failed because its broad landmark range proved place identity but did not
prove the body was inside the 0.50 m terminal region. This follow-up does not
widen the scorer band, permit post-claim motion, or tune H2's witness after
observing its four misses.

## Frozen product seam

`parcel_robot.navigation.independent_completion` is an isolated, stateful
contract. It is deliberately not imported by the navigation pipeline. Its
default config is disabled, its positive result is only
`authorize_terminal_claim`, and every result has `authorizes_motion == False`.

The current post-result hardening keeps schema-v2 evidence and all frozen
thresholds unchanged, but no enabled latch can be created without three
role-specific process-local verifier channels. Identity, pose-reset and
terminal-geometry records enter only through typed HMAC wrappers. Each wrapper
binds the complete evidence payload, an exact provider ID, an exact verifier ID
and a role-specific domain; the latch rejects missing channels and requires all
three provider IDs, verifier IDs and authentication keys to be distinct. This
is an interface-provenance boundary added after the preregistered outcome, not a
claim that the synthetic providers are independent physical sensors. Evidence
DTOs and authentication channels live in the import-cycle-safe
`independent_completion_evidence` leaf; the public
`independent_completion` module re-exports their stable names.

The enabled research configuration freezes these thresholds:

| Check | Threshold |
|---|---:|
| discontinuity score | >= 0.70 |
| place score | >= 0.70 |
| place score minus runner-up | >= 0.15 |
| terminal identity age | <= 0.50 s |
| reset anchor age | <= 2.00 s |
| pose verification age | <= 8.00 s |
| scan residual | <= 0.12 m |
| landmark residual | <= 0.15 m |
| geometry age | <= 0.40 s |
| geometry upper bound | mean range + 3 sqrt(max covariance eigenvalue) |
| accepted terminal limit | <= goal radius minus 0.01 m |
| unresolved deadline | 4.00 s |

A discontinuity discards cached identity, epoch and geometry proofs and raises
the required epoch floor to the current epoch. A reset must be rooted in a
qualified identity observation from exactly that parent epoch. Completion then
requires a fresh observation of the requested target in the verified new epoch
and geometry linked to that exact observation. Missing, stale, replayed,
cross-epoch or high-residual evidence cannot authorize a claim. Schema-v2 binds
all three records to the goal ID and a fresh goal nonce, rejects records that
predate goal start, and revalidates cached pose-verification age on every step.
Raw evidence, a changed payload/tag, or evidence presented under a provider or
verifier identity other than the exact commissioned role is refused before it
can satisfy the lineage chain.

## Arms

All arms see the same case and synthetic observations. Scorer truth is retained
outside policy-facing records.

- **C0 map only:** trusts the healthy MAP completion candidate.
- **C1 H2 identity/range:** requires a target descriptor score >=0.65, margin
  >=0.12 and observed range in 0.90--2.30 m, matching the prior experiment's
  architectural rule. It can refuse an alias but cannot install/verify a pose
  reset or distinguish an exact 0.50 m body terminal.
- **H2b independent chain:** invokes the new product contract with the frozen
  thresholds above. On alias cases, the harness first presents an adversarial
  wrong-location candidate, then—only if refused—models an active globally
  discriminative anchor, a verified reset, replanning, and a fresh terminal
  candidate. This tests claim authority and architectural recovery, not a
  learned navigation controller.

## Untouched deterministic matrix

The literal schema is `parcel.independent-completion-h2b.holdout.v1`. Case IDs
are the schema plus family, unseen scene index 0--7, held-out sensor profile
0--4 and target index 0--2: 8 x 5 x 3 = 120 cases per family. Noise is produced
from SHA-256 of the complete case ID and named channel. Seeds are 64-bit values
with `2^40` added, so they cannot equal the <=2,000,000,000 seeds used by H2.

Five families yield 600 cases and 1,800 arm rows:

1. **nominal (120):** truth endpoint 0.20--0.37 m from target. All three proof
   channels exist; deterministic camera, residual and geometry noise comes from
   held-out sensor profiles.
2. **alias recovery (120):** initial MAP candidate is 4.5--6.5 m from target.
   Forty cases attack identity, forty reset residuals and forty terminal
   geometry. After the false candidate is refused, a valid global anchor/reset
   and replanned endpoint 0.20--0.37 m from target are presented. A registered
   5% recovery-frame loss can end typed uncertain.
3. **outside boundary (120):** physical endpoint is 0.501--0.580 m from the
   target, while MAP and broad H2 range claim completion. Identity and pose
   reset are otherwise valid. H2b geometry must refuse rather than widen truth.
4. **sensor dropout (120):** the true endpoint is nominal, but identity, epoch
   verification or geometry is absent in 40 cases each. The four-second
   deadline must produce typed uncertainty.
5. **lineage attack (120):** the false MAP candidate is 3.5--5.5 m away and is
   accompanied by, respectively, an identity replay cleared by a discontinuity,
   a reset from the wrong parent epoch, or geometry linked across identity/pose
   epochs (40 each). The contract must refuse all and time out explicitly.

No case ID or seed from H2 is read. The generator does not import H2 results.
The source digest and matrix digest are recorded before case execution.

## Metrics

- true and false terminal claims per arm/family;
- H2b initial false claims and recovered true claims for alias cases;
- selective coverage (true claims / truth-positive opportunities);
- typed uncertainty and silent outcomes;
- first-candidate-to-terminal latency;
- first failing layer in alias/dropout/attack cells;
- lineage and scorer-boundary field audit; and
- deterministic payload/source/matrix digests.

The scorer alone receives `truth_distance_m`, `truth_positive`, `false_claim`
and family/attack labels. H2b DTO construction receives only IDs, epochs,
monotonic stamps, descriptor scores, residuals and target-relative mean/covariance.

## Falsifiable acceptance gates

H2b is supported by this synthetic holdout only if every gate passes:

1. Exactly 120 cases per family, 600 unique cases and all three arms on every
   case; H2 seeds/IDs remain disjoint.
2. C0 falsely claims at least 100/120 alias, 100/120 outside-boundary and
   100/120 lineage-attack candidates; C1 falsely claims at least 100/120
   outside-boundary cases.
3. H2b makes zero initial or terminal false claims across all 360
   alias/outside/lineage cases.
4. H2b nominal true completion is at least 118/120 and no worse than C0 by more
   than two cases.
5. H2b recovers at least 114/120 alias cases after reset, with p95
   first-candidate-to-recovered-claim latency <=2.50 s.
6. Every unresolved H2b dropout or lineage case ends
   `localization_uncertain`; there are zero silent outcomes.
7. Each alias failure layer (identity, residual, geometry) blocks all 40
   adversarial first candidates before recovery.
8. H2b true-positive selective coverage across the 240 resolvable nominal and
   alias-recovery cases is at least 232/240 (96.67%); the intentionally
   unresolvable dropout cell is reported separately, and false-claim rate over
   all false opportunities is zero.
9. Policy DTO field names do not intersect the scorer-only names, the decision
   has no command/velocity fields, `authorizes_motion` is always false, and the
   synthetic harness commissions three distinct authenticated provider and
   verifier IDs.
10. Two independent runs produce identical payload digests; source, matrix and
    row-integrity verification all pass.

## Interpretation limit

Even a pass is synthetic architectural evidence. The harness supplies the
post-reset/replan phase; it does not prove a real relocalizer, Go2 controller,
camera descriptor, Mid-360 residual, pickup detector, active view planner or
physical recovery. Noise distributions are deterministic design probes, not
calibrated hardware models. A supported verdict can justify a recorded-sensor
replay integration while the seam remains default-off; it cannot authorize a
pipeline promotion, Orin mount, or physical motion. The evidence contracts are
authenticated only across process-local software interfaces. The harness keys
are deterministic test material, and distinct local channel IDs do not prove
independent sensor hardware, processes, operators, key custody, calibration or
failure domains. Production sensor independence remains wholly unestablished.
