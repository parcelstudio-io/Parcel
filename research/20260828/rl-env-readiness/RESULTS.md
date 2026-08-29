# Go2Env locomotion-substrate audit — results

## Result

`H-RL-READY` is **REFUTED** at the local executable/MuJoCo evidence tier.
Only 2 of 9 critical gates passed; 7 failed and none were skipped. The current
`Go2Env` is suitable as a narrow API/PD-wiring smoke stub, not as the substrate
for training, comparing, or promoting generalized locomotion policies.

No policy was trained or compared. No ROS graph, Unitree transport, live
socket, physical robot, or hardware safety path was exercised.

## Gate results

| Gate | Result | Measured evidence |
|---|---:|---|
| G0 offline-stub honesty | **FAIL** | Offline `info` emitted `actual_vx=0.0`, `base_height=0.0`, and `upright=true` without a non-physics mode label or false validity flag. |
| G1 dimensions | **PASS** | API action/observation shapes were 12/48; the loaded model had `nq=19`, `nv=18`, `nu=12`, one free joint, and 12 unique actuated leg joints. |
| G2 semantic mapping | **FAIL** | Action/actuator order was `FR, FL, RR, RL`; both observation joint blocks were raw model order `FL, FR, RL, RR`. Correct widths concealed a leg permutation. |
| G3 root velocity truth | **FAIL** | Finite-difference forward speeds were `0.461368`, `0.424047`, and `0.388035 m/s`; every reported `actual_vx` was `0.0`. |
| G4 base-height truth | **FAIL** | Home root height was `0.269988 m` while reported height was `0.0000327`; forced-fall root height was `0.079961 m` while reported height was `0.0`. The implementation uses observation index 2, which belongs to the quaternion block. |
| G5 upright truth | **FAIL** | Home matched `true`; a forced 180-degree roll at low height derived `false` but was reported `true`. |
| G6 fall termination | **FAIL** | The forced-fall state returned `terminated=false` on the immediately following step. |
| G7 reset determinism | **FAIL** | After different histories, same-seed resets differed at all last-action indices 31–42, with maximum difference `0.3`; the prior action survives reset. |
| G8 action affects physics | **PASS** | After 25 steps, home and perturbed joint targets produced final generalized-position L2 separation `0.354196`, above the preregistered `1e-3` floor. |

G8 proves only that the PD/action seam changes MuJoCo state. It does not show
stable standing, walking, command tracking, terrain traversal, or useful reward
learning.

## Determinism and independent verification

The two raw results were byte-identical:

- file SHA-256:
  `e70f7357db537c0f54a155518883f332c14df1ddbe6294040bf92096d9292d19`;
- embedded canonical payload SHA-256:
  `9e5f35fee28ac370cf97b08ee73dcfb4c76b63946b7d9242e07dcd2365be15d4`;
- size: 23,806 bytes each.

`verify_results.py` independently recomputed the source binding, payload
digest, each G0–G8 result, summary, and decision. It passed 14/14 artifact
integrity checks while preserving the underlying `REFUTED` decision.

## Additional source-audit findings (not preregistered gates)

- Each environment `step()` calls `mj_step` once. The loaded MJCF timestep is
  `0.002 s`, while the repository's RL motion/skill configuration describes a
  `0.02 s` control interval. There is no explicit frame-skip/control-decimation
  contract in `Go2Env`, so elapsed physics time and intended policy time are not
  aligned.
- `terminated` is unconditionally false. There is no fall, NaN, joint-limit,
  contact, or task-success termination.
- `pose_error`, `kick_reach`, and `gesture_score` are fixed zero values. The
  corresponding rewards therefore do not measure their named tasks.
- The environment contains no terrain/domain randomization, disturbance or
  latency model, actuator-strength variation, sensor corruption, curriculum,
  privileged critic state, or held-out scenario split.
- `reset(seed)` calls global `numpy.random.seed`, but the environment itself has
  no stochastic training distribution to seed and does not clear all episode
  state.

These observations reinforce the gate result but were not used to change the
frozen decision rule after seeing results.

## Exact commands and outputs

```text
$ .parcel/bin/python research/20260828/rl-env-readiness/experiment.py --out research/20260828/rl-env-readiness/results-run1.json
{"decision": "REFUTED", "out": "research/20260828/rl-env-readiness/results-run1.json", "payload_sha256": "9e5f35fee28ac370cf97b08ee73dcfb4c76b63946b7d9242e07dcd2365be15d4", "summary": {"fail": 7, "not_evaluated": 0, "pass": 2, "total": 9}}

$ .parcel/bin/python research/20260828/rl-env-readiness/experiment.py --out research/20260828/rl-env-readiness/results-run2.json
{"decision": "REFUTED", "out": "research/20260828/rl-env-readiness/results-run2.json", "payload_sha256": "9e5f35fee28ac370cf97b08ee73dcfb4c76b63946b7d9242e07dcd2365be15d4", "summary": {"fail": 7, "not_evaluated": 0, "pass": 2, "total": 9}}

$ .parcel/bin/python research/20260828/rl-env-readiness/verify_results.py --first research/20260828/rl-env-readiness/results-run1.json --second research/20260828/rl-env-readiness/results-run2.json --out research/20260828/rl-env-readiness/verification.json
{"artifact_integrity": "PASS", "checks": "14/14", "underlying_hypothesis_decision": "REFUTED"}

$ .parcel/bin/python -m ruff check research/20260828/rl-env-readiness/experiment.py research/20260828/rl-env-readiness/verify_results.py
All checks passed!
```

