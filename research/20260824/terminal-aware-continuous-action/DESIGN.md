# Terminal-aware continuous action — preregistered design

Date frozen: 2026-08-24  
Evidence venue: deterministic desktop simulation  
Parent evidence: H3 `drives-and-initiative`

## Problem and hypothesis

H3 produced useful initiative (5, 5 and 6 admitted expressive actions per
hour) and immediate preemption, but its radius-six arm recorded 319 contact
episodes across the three headline seeds. Of those, 316 occurred after the
dog had stopped translating. The reported mechanism is precise: a bounded
outbound errand ends without a terminal, leaving the robot parked on a
scripted pedestrian route. The directional `_toward` test also ignores a
closing person outside its forward cone.

**H-TA1:** replacing an implicit "budget expired, stop here" with an explicit
`ActionContract` terminal — `RETURN_HOME`, otherwise `STAND_ASIDE`, finally
`RELEASE_AUTHORITY` — and joining *all* dynamic tracks by predicted
time-to-contact will reduce the H3 stationary-contact mechanism by at least
95% and total contacts by at least 90%, while preserving nonzero bounded
initiative and owner/e-stop preemption within one 100 ms control tick.

This is a mechanism test, not a claim that autonomous motion is safe.

## Why this advances the physical prototype

A perpetually active companion cannot treat a self-authored action as a fire
and-forget velocity. Every action needs a lifecycle that says who owns the
body, what success means, where the body may safely remain afterward, and how
the owner or safety kernel takes authority back. That contract is portable
across Unitree Sport commands and a future custom whole-body controller.

The experiment asks the smallest question needed before designing that
contract into the product: does a terminal actually remove the mechanism H3
identified, or does it merely move the collisions into the return leg?

## Frozen mini-design

The harness imports H3's real `InitiativeArena`, drive proposer, admission
doors, `PatrolPolicy`, `DynamicCity`, MuJoCo city, reactive safety gate and
hard-stop finalizer. Product and H3 files are read-only.

Two arms run for one simulated hour at 10 Hz on seeds **1, 2 and 3**:

1. `h3_baseline`: byte-for-behavior H3 `radius6`.
2. `terminal_all_tracks`: the same arm plus the contract below.

For every admitted travel action:

```text
OUTBOUND
  normal budget / boxed-in
    -> RETURN_HOME (0.30 m/s max, 0.25 m arrival, 60 s)
    -> STAND_ASIDE (best of 16 local 0.8 m shoulder samples, 30 s)
    -> RELEASE_AUTHORITY (exact-zero command)

owner turn or e-stop at any phase
    -> RELEASE_AUTHORITY in the same control tick
```

The stand-aside sample is chosen once. Its score is the minimum predicted
center clearance to every dynamic track at 0, 1, 2, 3 and 4 seconds; ties
prefer the candidate nearer home. Samples outside the owner-consented 6 m
home tether are refused. Static safety is not inferred by that sampler: every
candidate command still passes through H3's existing scan/reactive gate.

The added dynamic join evaluates every social track, not only the nearest
track and not only tracks in the command cone. It uses circle time-to-contact
with the H3 robot and actor radii. It preserves the product gate's frozen TTC
bands: at `<= 0.8 s` it stops translation; from `0.8–1.8 s` it scales
translation linearly with the existing 0.15 floor. It does not invent an
evasive velocity or override the static gate.

The proposed arm also runs a deterministic terminal-preemption probe: on its
first return phase, an owner-turn event is scheduled three seconds later. The
normal H3 e-stop injection remains. This probe may only make the proposed arm
harder by aborting a return; it may not be removed after seeing the result.

## Frozen measurements and bars

All reductions use pooled episodes over seeds 1–3. A zero denominator is
reported, never silently replaced.

| row | measurement | confirmation bar |
|---|---|---|
| TA1 | stationary contact episodes | proposed <= 5% of baseline |
| TA2 | all contact episodes | proposed <= 10% of baseline |
| TA3 | moving contact episodes | proposed <= baseline |
| TA4 | admitted expressive initiatives/hour | each proposed seed > 0 and pooled count >= 80% of baseline |
| TA5 | owner/e-stop preemption latency | maximum <= 1 tick; command at yield exact zero |
| TA6 | natural travel terminals | >= 90% reach `HOME` or `STAND_ASIDE`; every terminal ends in release |
| TA7 | contact time | proposed <= 10% of baseline |

The hypothesis is **confirmed only if TA1, TA2, TA4, TA5 and TA6 all pass**.
TA3 and TA7 are diagnostic safety rows and cannot be hidden if they fail.

## Negative controls and integrity checks

- Re-run the H3 baseline through this harness and compare its seed-level
  initiative and contact rows to H3's canonical `results/runs.json`.
- Run a pure geometry unit table for front, side, rear, diverging and static
  tracks. Closing front/side/rear cases must be selected; diverging/static
  cases must not be assigned a collision time.
- Record command-stream hashes, terminal reasons and dynamic-gate counts.
- Save one compact JSON file sufficient to recompute every row.

## Refuters and interpretation

- If baseline replay differs, the comparison is invalid and must be marked
  inconclusive.
- If contacts move from stationary to translating, TA1 alone is not success;
  TA2/TA3 expose it.
- If a return is routinely blocked by the existing directional static gate,
  the ActionContract idea may still be right, but this controller is refuted.
- If terminal authority cannot be interrupted in one tick, the design is
  refuted regardless of contact count.

## Venue limits and physical promotion

The crowd follows scripts and does not avoid the robot. Tracks, pose and
velocity are simulator truth; there is no latency, occlusion, identity error,
wheel/foot dynamics, terrain, leash, fall, real braking or Unitree SDK. Even a
perfect result only promotes the contract to implementation-design review. It
is **not sufficient for physical motion promotion**. That requires, at
minimum, synchronized physical tracks, uncertainty-aware TTC, a commissioned
stopping envelope, through-air stop tests and supervised leashed trials.

## Owned files

Only `research/20260824/terminal-aware-continuous-action/**`. No product,
test, H3, gateway, NAV-CORE or scrum files are modified.
