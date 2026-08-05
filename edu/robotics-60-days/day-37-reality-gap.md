# Day 37: The Reality Gap

## Mental model

The reality gap is the systematic difference between what your simulator computes and what the physical robot, sensors, and environment do. It is not one bug; it is a stack of mismatches: contact/friction, actuator delay, network jitter, thermal derating, lighting, LiDAR multipath, and human motion.

```text
policy that wins in sim  ≠  policy that is safe on tile, wet concrete, or crowds
```

Closing the gap is staged evidence, not a single “sim2real” checkbox: system identification, domain randomization, sensor corruption tests, hardware-in-the-loop (HIL), stand tests, fenced low-speed runs, then supervised field work (`INTRO.md` commissioning ladder).

System ID for Parcel starts at the *interfaces you own*: commanded body twist → measured twist lag; lease expiry → time-to-zero; scan age → shield engagement; axis signs after Sport messages. Domain randomization without those measurements just teaches a policy to overfit a different wrong world.

## Software-engineering analogy

Think of load tests against a mocked payment processor. Mocks teach you your retry logic; they do not prove the bank’s latency or idempotency. You graduate: contract tests → staging with canaries → limited prod traffic → full rollout. Skipping staging because “unit tests were green” is how you page the world.

**Tradeoffs:**

- Heavy randomization → harder CI flakes, better coverage of nuisance regimes.
- Exact digital twin chasing → expensive, still wrong somewhere.
- Vendor Sport opacity → you cannot ID internal gait gains; you must characterize the *leased velocity interface* you actually own.

## Light equations (mismatch as error)

```text
e_gap = g_real(x, u) − g_sim(x, u)
```

You rarely estimate `e_gap` fully. Instead you bound critical channels: stop distance, tracking lag, perception false-negative rate, command-to-motion delay. If the bound exceeds your safety margin, you slow down or stay fenced.

## ASCII diagram

```text
  unit / property tests
          |
          v
  deterministic headless sim  -->  seeded Monte Carlo + fault injection
          |                              |
          v                              v
     HIL (real control path,           stand / no-walk
      fake or constrained plant)            |
          |                                 v
          +-------> fenced low speed --> supervised sidewalk
                         |
                         v
              revisit limits, TTLs, shields
```

## Map to Parcel / Go2

From `INTRO.md`, `DESIGN_DECISIONS.md` D2/D4/D5/D9, and control factory gates:

- Kinematic MuJoCo smoothness ≠ physical stability (D4 limitation).
- Semantic tracks from scene metadata are cleaner than real detectors (D5)—plan for corruption and identity breaks.
- Sport is a closed subsystem: commission axes/frames/modes explicitly before trusting signs (`control/factory.py` flags).
- Jerk-shaping “42% reduction” evidence is a dispatch replica in companion evals—not a hardware smoothness result (D2). Treat such metrics as scaffolding.
- Reality-gap work for Parcel is mostly *interface characterization*: lease expiry → observed stop; scan dropout → `apply_reactive_safety` behavior; frame sign errors → immediate walk tests on a stand.

**Design choice:** admit classical nav + shields first; learn proposers behind the same SE(2) contract. Cost: less flashy demos. Benefit: gap failures fail closed at the shield, not at a motor token.

HIL for Parcel means exercising `ControlManager` + vendor/mock controller with a constrained plant (stand, tether, or recorded state playback)—not “SSH to the dog and hope.” Each stage on the INTRO ladder should add one failure class you could not see before (contact, RF loss, sun flare, thermal).

**Codebase anchors (gap / commissioning):**

- `control/factory.py` → `build_unitree_sport_control_manager` requires `enable_lease`, `axes_commissioned`, `state_frame_commissioned`, explicit `allowed_modes`.
- `control/unitree_sport.py` → `UnitreeSportStateSource` frame/sign transforms — wrong commission is a reality-gap landmine.
- `sim.py` / `HeadlessCityWorld` seeded layouts — reproducible *sim* evidence only.
- `navigation/reactive_safety.py` → stale telemetry stop; practice with dropped observations in harnesses.
- `evals/companion_nav/` → `_DispatchReplica` / reports’ `does_not_prove` — partial stacks must not claim hardware.
- `INTRO.md` ladder: unit → deterministic sim → randomized/fault → HIL → stand → fenced → supervised.

Randomized friction and added command delay in sim are useful *stressors*, not calibrated twins. Prefer a short list of gap hypotheses you can falsify on a stand (sign error, lease stop time, scan-hold behavior) over a long list you only animate.

## Failure story

A follow policy trained with perfect owner tracks in sim transferred to a sunny plaza. Detector flicker made the owner ID swap to a stranger in a similar jacket for 400 ms; the dog surged. In sim, identity was a stable integer. The gap was perception continuity, not PID gains. Mitigation: identity confidence gates, loss→search behavior already in product follow/search skills, and outdoor trials that *inject* ID swaps long before celebrating sidewalk autonomy.

## Retrieval questions

1. Why can perfect sim collision metrics still leave stop-distance risk on hardware?
2. What does `axes_commissioned` buy you that more MuJoCo training does not?
3. (Week-back) How does Day 24’s odometry drift interact with a map frame assumed perfect in sim?

## Optional 10-minute exercise

Write a one-page “gap budget” for owner-follow: list sim assumptions (tracks, latency, friction, Sport response). For each, name a Parcel mechanism that mitigates mismatch and a measurement you would collect on a fenced Go2 walk. Star items still only evidenced in `evals/` replicas.
