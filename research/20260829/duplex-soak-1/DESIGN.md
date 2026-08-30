# DSOAK-1 design — 12-hour duplex mission-control stability soak

Date frozen: 2026-08-29, before implementation or results.

## Question

Does the DMC-1 candidate remain fail-closed and operationally stable during at
least 12 continuous wall-clock hours of unseen procedural navigation,
instruction-interruption, receipt-corruption, and narration streams?

This soak is a durability and invariant experiment. It is not a second chance
to tune DMC-1 after seeing its frozen result, and it does not promote the
learned controller over the stronger deterministic baseline.

## Frozen procedure

- Run one uninterrupted Python process for at least **12.0 monotonic hours**.
- Load the exact DMC-1 policies and simulator sources already verified in
  `../duplex-mission-control-1/verification.json`.
- Alternate batches of `frozen` and `adversarial` generator modes, using seeds
  starting at `1_000_000` and `2_000_000`. These do not overlap DMC-1 train,
  development, frozen-test, adversarial-test, or known refuter seeds.
- Exercise all five DMC-1 arms on every episode. No arm may affect another.
- Use one CPU worker and one Torch thread. This makes elapsed time auditable and
  avoids turning a stability test into a workstation saturation test.
- Every 100 primary episodes, rerun the just-completed seed and require an
  identical semantic digest after excluding measured encode latency.
- Checkpoint at least once per minute with UTC time, monotonic elapsed time,
  source hashes, cumulative counters, throughput, current RSS, bounded RSS
  samples, deterministic-replay results, and a bounded failure manifest.
- Do not retain full successful episode traces in RAM. Metric state, RSS
  samples, and failure samples are bounded.
- A crash, source drift, signal termination, or restart makes the run
  incomplete. An incomplete checkpoint cannot pass.

## Preregistered gates

The final verdict is `SUPPORTED_PROCEDURAL_SOAK` only if every gate passes:

1. elapsed monotonic wall time is at least 12.0 hours;
2. at least 20,000 primary episodes and at least 5,000 adversarial episodes
   complete;
3. DMC-1 A1 mission success is at least 0.99 overall and at least 0.98 on the
   adversarial subset;
4. A1 has zero admitted unsafe actions, zero accepted stale-revision actions,
   zero post-STOP motion, and zero premature completion claims;
5. A1 narration semantic precision and terminal-claim precision are exactly
   1.0, and terminal coverage is at least 0.99;
6. every sampled deterministic replay has the same semantic digest;
7. final RSS is below 2 GiB and the least-squares RSS slope after the first ten
   minutes is at most 10 MiB/hour; and
8. the DMC-1 source/model hashes are unchanged from process start to finish.

The 20,000-episode floor prevents a very slow or wedged process from passing on
duration alone. Both a denominator and a count accompany every reported rate.
Every A1 mission failure is counted; at most 1,000 detailed failure records are
retained so memory remains bounded.

## Interpretation rules

- A pass supports only long-run stability of the typed ledger/gate/narration
  architecture in a desktop procedural semantic stream.
- A pass does **not** establish camera/LiDAR perception, audio duplex quality,
  social navigation, contact safety, dynamics, stairs, crosswalk judgment,
  elevator behavior, AGX Orin latency, Starlink reliability, ROS 2 integration,
  Unitree SDK correctness, or physical mount readiness.
- DMC-1 already found that A1 did not clear the preregistered improvement bar
  over A0 and that L0 had better mission reliability. This soak cannot reverse
  that model-selection result; it can only reveal additional instability.
- If a gate fails, preserve the counterexamples and recommend the deterministic
  temporal controller until a new, separately preregistered model study earns
  scope.

## Safety boundary

The runner imports only the isolated DMC-1 research simulator and policy
artifacts. It must not import Parcel runtime composition, open a ROS/domain or
Unix socket, access cameras/microphones/USB, call the motion gateway, access
`parcel_memory.sqlite3`, or make hosted model calls. Cardinal steps remain
semantic proposals, never velocity, gait, pose, or joint commands.
