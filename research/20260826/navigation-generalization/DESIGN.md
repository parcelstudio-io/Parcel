# Navigation generalization research design

**Date:** 2026-08-26 (America/New_York)
**Repository baseline:** `f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8`
**Hardware exercised:** none
**Evidence tier:** deterministic desktop simulation with the existing NAV-CORE
physical-shaped observation harness

## Decision question

What should Parcel learn in simulation, and what must remain a typed,
deterministic supervisor, to improve generalized instruction navigation,
person-following and terrain mobility on a Unitree Go2 EDU + AGX Orin without
mistaking simulator success for physical safety?

The immediate evidence has two different failures:

1. the commissioned point-goal arm succeeds on 60/60 generous room episodes
   but silently waits for 900 ticks after a moved obstacle makes its isotropic
   route infeasible; and
2. the same arm declares arrival 5.2 m from truth after an aliased localization
   kidnapping. Its pose is `HEALTHY` and its scalar arrival confidence is
   0.988--0.998, so threshold tuning is not a remedy.

The experiment below tests one supervisor for each failure before recommending
product work.

## Scope and invariants

- No product code, configuration, frozen corpus, ledger or baseline is edited.
- The experiment imports the existing NAV-CORE/NAV-ACCEPT world, drifting
  odometry, scan matcher, learned-map fixture, detector noise, commissioned
  planner and reactive gate.
- Ground truth is used only by the scorer. The arms receive the same MAP pose,
  LiDAR scan and stored semantic goal as the existing harness.
- The kinematic body and synthetic scans do **not** model Go2 contacts,
  footfall, stairs, motor latency, real Mid-360 artifacts or physical stops.

## Hypotheses

### H1 — bounded evidence-based liveness supervisor

If a deterministic supervisor converts **30 consecutive 10 Hz planner reports
of `status=no_path`** into a typed `unreachable` terminal outcome, then:

- nominal arrival, false-arrival and contact counts will be identical to the
  unmodified commissioned arm on all 60 NAV-CORE nominal episodes;
- every non-arrival in a held-out moved-obstacle matrix will terminate with a
  typed outcome rather than `silent_stall_step_limit`; and
- termination will occur no later than 3.1 seconds after the first persistent
  `no_path` report.

The 30-tick value is fixed before the run. It is long relative to a single
planner tick but short relative to the existing 90-second ceiling. The
supervisor does not invent a route; it stops and reports.

**Promotion bar:** no nominal regression, zero false arrivals/contacts, zero
silent non-arrivals, and every supervisor termination within the bound.

### H2 — temporal confidence is not independent arrival evidence

Requiring five consecutive ticks of the existing chance-constrained arrival
claim will **not** eliminate aliased-kidnap false arrivals, because all five
claims share the same wrong MAP frame and map-derived goal. This is a negative
hypothesis: refuting the temporal filter prevents the team from spending time
on threshold/streak tuning that cannot observe the failure.

**Test:** compare the commissioned arm with a five-tick quarantine arm on the
aliased room, using three held-out seeds and the same 6-second kidnap onset.

**Decision bar:** if any temporal-filter episode still falsely arrives, scalar
confidence/streak tuning is rejected as the R4b remedy. A future arrival
authority must require evidence that is independent of the aliased MAP
hypothesis: globally discriminative place evidence, a carried signature,
operator reset, or a separately localized target observation.

### H3 — compositional instruction execution should be constraint-checked

A typed hierarchy

`dialogue intent -> ordered subgoals -> perceptual constraint -> metric goal -> execution -> verified transition`

should outperform one-shot free-form action generation on held-out
compositions, while making failure attribution local. This is motivated by
CA-Nav's constraint-aware sub-instruction completion and NaVILA's separation
of high-level language actions from real-time locomotion.

**Future falsifiable test:** build a 5-axis split over unseen scene, landmark,
paraphrase, relation and disturbance, with 200 composite episodes such as
“find me, come close enough to ask, then walk with me to the door.” Compare
one-shot goal generation against the typed hierarchy. Require higher
subgoal-completion rate and lower false-transition rate without worse collision
or human-space metrics. Do not score only final success.

### H4 — paired simulator/real residual curriculum is more useful than broad
randomization alone

After Stage-0 bags exist, prioritize simulator mutations in proportion to
measured sim/real residuals (scan dropout, clock skew, pose jumps, person-track
occlusion, command delay, friction/payload) while retaining a fixed broad
holdout. This should reduce held-out real-bag error faster than uniform
domain-randomization effort.

**Future falsifiable test:** freeze 20 paired physical/replay scenarios and
compare two equal-compute curricula over three iterations. Primary metric is
paired real-bag failure reduction; secondary metrics are simulator holdout
success and calibration error. Sim2Val-style paired measurements can later be
used to estimate real metrics more efficiently, but only after correlation is
measured rather than assumed.

## Experiment matrix

### Nominal non-inferiority

- arms: commissioned baseline vs H1 supervisor;
- episodes: existing 20 generated room episodes x seeds 101/202/303 = 60 per
  arm;
- metrics: arrival, false arrival, contact, typed failure and paired outcome
  changes.

### Held-out moved-obstacle generalization

- arms: commissioned baseline vs H1 supervisor;
- seeds: 404/505/606, not used by NAV-CORE/NAV-ACCEPT;
- four clutter layouts x two obstacle-onset times (3.0, 6.0 s) = 24 episodes
  per arm;
- start and goal are deterministically varied with layout/onset;
- metrics: success, typed failure, silent timeout, contacts, false arrivals,
  ticks to terminal and supervisor-bound compliance.

This matrix changes multiple scenario coordinates but reports each row, so it
is a stress test rather than a causal estimate for any one coordinate.

### Aliased completion authority

- arms: commissioned baseline vs H2 five-tick quarantine;
- seeds: 404/505/606;
- exact C2-symmetric room, 6.0 s kidnap, no injected scan gap;
- metrics: declared/true/false arrival, truth distance, arrival confidence,
  MAP health and time added by quarantine.

## Reproducibility and acceptance

`experiment.py` writes all rows plus an environment block and a SHA-256 digest
of the deterministic experiment payload. It will be run twice through the
Parcel process guard. Matching payload digests are required. Ruff and the
script's own invariant checks must pass.

The hypotheses and thresholds in this file were written before the first
experiment run. Results do not authorize physical motion.

## Post-run amendment: H1b (exploratory, not preregistered confirmation)

**Added after run-1 digest
`95726bddf90466c81c4a859ff479e00cd18daba96f8e3e60039f934abc7100e6`.**

H1 was refuted because 17/24 held-out blockers emitted persistent
`status=no_path` and terminated, while 7/24 emitted persistent
`status=goal_blocked` and rotated until tick 900. This was not a noisy miss:
all seven retained the latter explicit planner state at the ceiling.

H1b changes one registered set from `{no_path}` to
`{no_path, goal_blocked}` and keeps the 30-tick/3.0-second bound unchanged.
It will be evaluated on the exact same 60 nominal and 24 held-out blocker
specifications. Promotion still requires 60/60 nominal non-inferiority, zero
false arrivals/contacts, and 24/24 bounded typed blocker outcomes. Because the
state set was learned from run 1, a pass is exploratory evidence for a product
design and requires a newly generated frozen holdout before promotion.
