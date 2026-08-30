# LHO-1 results

## Outcome

The frozen mechanism verifier reports H1–H4 pass. Each of the two original full
runs contained 1,980 paired cases and 5,940 arm episodes and produced the
identical normalized episode digest:

```text
f5807113f297d2e1a8aa4d4831c7e0c2ddeb19dd35d39bedea92995afcf31991
```

The paired population was 900 ordinary/control episodes and 1,080 local
invalidation episodes per arm. The latter comprised 540 emergency-STOP and 540
predicted occupied-prefix schedules. All three arms reached the current scalar
endpoint before timeout in 900/900 ordinary/control episodes. Endpoint reach is
the frozen success rule; it is not a stationary-arrival test.

## Aggregate comparison

| Metric | B0 blocking | F0 fixed 400 ms | G0 guarded prefix |
|---|---:|---:|---:|
| Episodes | 1,980 | 1,980 | 1,980 |
| Ordinary/control success | 900/900 | 900/900 | 900/900 |
| Waiting time | 8,388.00 s | 3,464.15 s | **676.75 s** |
| Visible gaps (>0.50 s) | 6,183 | 2,739 | **555** |
| Wait runs | 12,111 | 5,185 | **1,601** |
| Explicit prefix exhaustions | 14,790 | 7,836 | **3,895** |
| STOP/invalidation completed | 1,080/1,080 | 1,080/1,080 | 1,080/1,080 |
| Collision/boundary violations | 0 | 0 | 0 |
| Positive commands after invalidation deadline | 0 | 0 | 0 |
| Stale-tail distance | 0 m | 0 m | 0 m |
| Old-revision dispatch beyond prefix | 0 | 0 | 0 |
| Maximum live requests/prefix records | 1/1 | 1/1 | 1/1 |

Waiting time, visible gaps, wait runs, and explicit prefix exhaustions in this
table are accumulated over the 900 ordinary/control episodes per arm. The
invalidation rows contribute to their separately reported 1,080-case STOP/
invalidation gates, not to those fluidity totals.

Relative to B0, G0 reduced waiting time by **91.9319%** and visible gaps by
**91.0238%**, exceeding H1's frozen 30% and 50% thresholds. This number is a
within-simulator mechanism effect. It must not be quoted as a robot-level
navigation, latency, or safety improvement.

For the single revision splice per revision episode, G0 observed and applied
540/540 revised tails. Its p95 splice acceleration was 1.20 m/s² versus 1.20
m/s² for F0. Its p95 splice jerk was 49.92 m/s³ versus 49.56 m/s³ for F0,
within the frozen 10% limit. No arm dispatched old revision content beyond its
authorized prefix.

## Latency-estimator error strata for G0

Each row contains 180 ordinary/control and 216 invalidation cases. Mission
success was 180/180 and local invalidation completion was 216/216 in every
row, with zero collisions, boundary violations, stale-tail distance, old-tail
dispatch, or late positive command.

| Estimator error | Waiting | Visible gaps | Explicit exhaustions |
|---:|---:|---:|---:|
| -50% | 232.80 s | 164 | 1,737 |
| -25% | 130.80 s | 96 | 1,054 |
| 0% | 108.95 s | 126 | 342 |
| +25% | 89.80 s | 60 | 384 |
| +50% | 114.40 s | 109 | 378 |

The non-monotonic pause counts reflect interaction between tracker
quantization, periodic planning, route length, and corridor caps in the frozen
covering array. The experiment supports boundedness and explicit exhaustion;
it does not identify a universally optimal error margin.

## Hypothesis decisions

- **H1 passed:** 91.93% less waiting and 91.02% fewer visible gaps versus B0,
  with no success loss.
- **H2 passed:** zero stale-tail distance, old-tail overrun, collision, and
  boundary violation; splice acceleration and jerk stayed inside the frozen
  F0 +10% gate.
- **H3 passed:** all 1,080 invalidations per arm completed, with zero command
  past the one-tick deadline and zero invalidation collision.
- **H4 passed:** every error stratum preserved H2/H3, all raw prefix
  usable-to-unusable transitions were explicitly recorded, and live storage
  stayed bounded at one request and one prefix.
- **H5 passes through the additive supplement:** the original verifier
  recomputed traces and detected its five content mutations but did not enforce
  distinct process identity. The separately frozen supplement observed C and D
  live as distinct sequential child processes, linked A/B/C/D to the same
  normalized digest and aggregate, and rejected all ten process/output tamper
  mutations.

## Integrity and provenance

- Internal frozen manifest digest:
  `06364896027e38cd2143b4c379ebbe6bf9d0d7cb5ec4b6393c33ad997eee0e68`
- Internal frozen source-manifest digest:
  `510f11ef4b9477ef6a6cad4f1e17534482518849ef92201ab5d4ba7ac7fe7eb7`
- Verifier decision digest:
  `24f63fe46886962734b80f895edf250a499899a995dba679e5b781b2b1143d1b`
- Run runtimes: 14.806708 s and 14.673589 s under Python 3.14.4.
- File hashes and the five tamper results are bound in
  [source-manifest.json](source-manifest.json) and
  [verification.json](verification.json).

## What the result does not establish

LHO-1 has no learned policy, camera, LiDAR, semantic map, social actor model,
2-D trajectory, quadruped dynamics, hardware interface, real network delay,
Orin timing, or physical braking measurement. Its obstacle/contact geometry is
an authored one-dimensional oracle. A pass therefore justifies implementing
and testing the handoff transaction; it does **not** justify energizing the
Go2's motors.

An independent post-evidence audit found that the original H5 verifier accepts
the same run file in both input slots because it checks output equality but not
distinct OS-process identity. The separately frozen
[fresh-process supplement](FRESH_PROCESS_RESULTS.md) is the controlling
remediation and passed all eight gates. Its local `/proc` evidence is not remote
attestation. The audit also found that compressed trace-length metadata is not
independently recomputed; decoded bytes, raw length, hash, tick count, and
semantics are checked, so this does not alter a mechanism gate.
