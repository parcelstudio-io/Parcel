# Dynamic social progress · preregistered study design

Preregistered: 2026-08-26T07:27:48Z
Evidence tier: authored deterministic 2-D desktop simulation with noisy tracked
states; no Go2, Orin, ROS graph, camera, LiDAR, human participant, or physical
motion.

## Question

How can Parcel distinguish a truly occupied path from a temporary pedestrian
crossing or a false/stale obstacle, resume promptly when fresh evidence says the
path is clear, and avoid deadlock while accompanying a person on a sidewalk,
crossing a crosswalk, or entering a tight elevator?

The study tests mechanisms, not a production clearance value. A simulator can
measure contact and policy consistency in its own geometry; it cannot establish
what physical or socially acceptable proximity is safe for a Go2 around a real
person.

## Frozen safety separation

Every candidate is evaluated as three distinct envelopes:

1. **Contact/hard floor:** current geometry, braking and fresh sensor evidence;
   learned output cannot weaken this boundary.
2. **Predicted interaction risk:** relative motion, uncertainty, visibility and
   bounded horizon; this may slow, hold or reject a candidate.
3. **Social comfort:** context, role, direction and owner preference; this is a
   soft ranking cost above the hard floor and must eventually be learned from
   consented human preference data.

No arm may infer cooperation, treat urgency as permission to reduce the hard
floor, enter a road without the frozen authorization bit, or enter an elevator
before a frozen egress/capacity predicate allows it.

## Frozen scenario split

The generator will create independent episodes, not randomly split frames.
Train/dev/test seeds and scenario-template IDs are recorded in `fixtures.json`.

- **Sidewalk:** consented owner-parallel formation, same-direction stranger,
  oncoming stranger, crossing pedestrian, sudden stop/turn, group gap,
  visible false positive, and an occluded person who remains hazardous.
- **Crosswalk:** unauthorized curb wait, authorized crossing with lateral
  pedestrians, a late entrant, owner-group formation, and a persistent blocker.
  Vehicle/signal perception is not simulated; authorization is an input.
- **Elevator:** people exiting, temporarily clear doorway, occluded egress,
  occupied cabin, capacity-full refusal, and narrow-cabin owner formation.

Sensor mutations are independently seeded: Gaussian position noise, missed
detections, bounded latency, a visible false-positive track, and occlusion.
The semantic context/zone is supplied as an authored input; semantic perception
accuracy is outside this experiment.

## Arms

### A0 · radial wait proxy

Forward goal pursuit plus a symmetric 1.2 m person surface-clearance stop.
Clearance has no bearing, relative velocity, uncertainty or interaction role.
The motion gate reopens on the next detected-clear tick; the product's separate
three-second mission-level yield-accounting grace does not prevent motion.
This is not a byte-identical product execution; it isolates the current
direction-agnostic radial-stop behavior class.

### A1 · deterministic CV-TTC

Estimate velocity from recent measurements. Sample robot and constant-velocity
person trajectories over two seconds. Current hard-floor violation or predicted
closest approach below the floor stops; a wider predicted band scales speed.
Two fresh visible-clear observations release the stop. No semantic interaction
policy is used.

### A2 · visibility- and uncertainty-aware mixture

Add track existence probability, negative evidence only when the swept corridor
is observed, covariance growth during occlusion, and a conservative mixture of
constant-velocity, stop, and bounded turn hypotheses. Release requires fresh
free-space evidence and low corridor-occupancy risk; an occluded recent person
is retained rather than erased.

### A3 · semantic time-lattice

Evaluate a bounded set of forward/lateral/hold velocity candidates over a
time-indexed horizon using A2 occupancy tubes. Context is structural:

- sidewalk: preserve the owner formation region, prefer flow-consistent passing
  and passing behind a crossing trajectory;
- crosswalk: require prior authorization, avoid reverse/lateral dithering in the
  road, and preserve progress only when the predictive envelope permits it;
- elevator: people exit first, doorway/capacity is a resource predicate, entry
  is a latched phase, and cabin motion is slower.

The final hard-floor monitor is applied after candidate selection.

### A4 · learned risk critic, soft use only

Fit a small regularized logistic model on whole training episodes. Inputs are
current clearance, relative longitudinal/lateral velocity, bearing terms,
track uncertainty/existence, role and context. The label is contact within the
two-second nominal-continuation counterfactual. Select the probability threshold
on whole dev episodes by the highest-progress threshold satisfying at most 1%
false negatives. On test, the critic may alter A3's soft trajectory ranking but
cannot admit a candidate rejected by A2 or the hard-floor monitor.

This tests whether a data-driven context/risk signal can help ranking without
becoming a safety authority. Synthetic labels are not evidence of human comfort.

## Metrics

- episode completion and time to goal;
- physical contact and near-contact (`surface_clearance < 0.15 m`);
- minimum and p05 surface clearance, split by owner/stranger and context;
- false-block time: commanded hold while an oracle-safe, semantically permitted
  candidate exists for the next 0.5 s;
- unsafe-motion time: commanded translation when no oracle-safe candidate exists;
- unblock latency: first translating command after a truly occupied forward
  corridor becomes and remains clear for at least one second;
- wrong-stall episodes: more than one continuous second of false blocking;
- deadlock: incomplete with at least eight seconds of false blocking;
- stop/start transitions, lateral distance and acceleration/jerk proxy;
- crosswalk authorization violations;
- elevator egress-priority, capacity and door-phase violations; and
- A4 AUROC, Brier score, false-negative rate and false-positive rate on the
  held-out templates/seeds.

`oracle-safe candidate` is used only for scoring. No policy receives future
truth.

## Preregistered hypotheses

### H1 · evidence-conditioned release

On visible-clear events, A2 median unblock latency will be at most 0.6 s and at
least 50% lower than A0. On occluded-survivor cases, A2 will have zero contacts
and zero release decisions based solely on missing detections.

### H2 · prediction reduces false stalls without trading contact

Across the full held-out test, A2 will reduce false-block time by at least 40%
relative to A0, improve completion by at least 15 percentage points, and have
zero contacts and no increase in near-contact episode count.

### H3 · semantics resolves interaction-specific deadlocks

A3 will improve completion by at least 15 percentage points relative to A2 on
the combined crosswalk/elevator slice, with zero crosswalk-authorization,
elevator-egress, capacity, contact, or hard-floor violations. It must not worsen
sidewalk completion.

### H4 · a learned critic is useful only behind the deterministic envelope

A4 will achieve held-out AUROC at least 0.85 and false-negative rate at most 1%
under the dev-selected rule. As a soft critic behind A2, it will reduce false-
block time at least 10% relative to A3 without a contact, hard-floor or semantic
violation.

## Decision rules

- A single contact or authorization/egress/capacity violation makes an arm
  ineligible for product carry-forward, regardless of mean completion.
- A hypothesis is reported PASS or REFUTED exactly against the bars above.
- Post-hoc variants, threshold changes and discovered scenario defects are
  labeled exploratory and never replace the frozen result.
- Results support a research implementation only. Promotion requires product-
  path replay, external social-navigation environments, natural perception,
  human preference studies, exact-device timing and staged physical evidence.
