# Go2Env locomotion-substrate readiness audit — preregistration

Date: 2026-08-28  
Evidence tier: local executable contract and MuJoCo dynamics audit on the
tracked Go2 MJCF. No policy is trained or compared, no ROS or Unitree transport
is used, and no physical robot is exercised.

## Question

Is the current `parcel_robot.rl.Go2Env` a faithful enough substrate to train or
evaluate generalized Go2 locomotion, specifically with truthful root-velocity,
posture, fall termination, model dimensions/mappings, reset behavior, and
action-to-physics coupling?

## Frozen subject

The audit is bound to these pre-run inputs:

| Input | SHA-256 |
|---|---|
| `src/parcel_robot/rl/env.py` | `16c461bb93257ad8a70b0d54e61cd9ccbf0354c12881bfc448045591f0282c00` |
| `src/parcel_robot/rl/spaces.py` | `f739cc3b94058c2c6e8297a7f82a13ddefa514cace227c23267966ada4c9f400` |
| `third_party/unitree_mujoco/unitree_robots/go2/go2.xml` | `2014a3d76e30f17ab9447d8a67bd015291f74fa4d71ae30d005f1a32bd693d4b` |
| `third_party/unitree_mujoco/unitree_robots/go2/scene.xml` | `6c1fda780e7883665d1c84113b9275b6d448f586a8b1c110e438a37417cbccd0` |

The recorded repository revision is
`f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8`; the file digests, rather than a
clean-worktree claim, define the subject because concurrent work is present.

## Hypothesis and decision rule

**H-RL-READY:** `Go2Env` is ready to support locomotion policy comparisons.

The hypothesis is supported at this limited local-simulator tier only if every
critical gate G1–G8 passes in MuJoCo mode and the offline mode passes G0. Any
failure refutes readiness. A missing MuJoCo dependency or tracked MJCF makes
G1–G8 `NOT_EVALUATED` and the overall result `INCONCLUSIVE`, never a pass.

This is deliberately a substrate test, not evidence for generalized movement,
sim-to-real transfer, controller quality, or hardware safety.

## Preregistered protocol and gates

All comparisons use float64 values. Absolute/relative closeness means
`abs(a-b) <= 1e-6 + 0.01 * max(abs(a), abs(b))` unless a gate states another
threshold. MuJoCo uses the tracked official simple Go2 `scene.xml`, never the
live simulator socket.

- **G0 — offline-stub honesty (critical):** an offline `step()` must identify
  itself in `info` as non-physics, and physics-derived fields (`actual_vx`,
  `base_height`, `upright`, fall termination) must be absent, `None`, or carry
  explicit validity flags set false. Unlabelled numeric/boolean claims fail.
- **G1 — dimensions (critical):** action shape is `(12,)`, returned observation
  shape is `(48,)`, MuJoCo `nu == 12`, `nq == 19`, `nv == 18`, the model has one
  free joint and 12 one-DoF leg joints, and all 12 actuator targets are
  represented once in the joint-position and joint-velocity blocks.
- **G2 — action/state semantic mapping (critical):** the action ordering stated
  by the environment and the observation `joint_q`/`joint_dq` ordering must each
  equal the MuJoCo actuator-to-joint ordering. A dimensionally correct but
  permuted vector fails.
- **G3 — root velocity truth (critical):** after initializing forward root
  velocity to `0.5 m/s`, `info.actual_vx` from each of three steps must match
  finite-difference `(root_x_after-root_x_before)/model.opt.timestep`; all three
  comparisons must pass.
- **G4 — base-height truth (critical):** `info.base_height` must match the
  post-step free-joint root `qpos[2]` in both the home and forced-fall cases.
- **G5 — upright truth (critical):** define observed upright as root height
  `>= 0.18 m` and the world-Z projection of body-Z `>= 0.5` (within 60 degrees).
  `info.upright` must equal this derived value for home and a forced state with
  root height `0.08 m` and a 180-degree roll.
- **G6 — fall termination (critical):** the forced-fall state from G5 must
  produce `terminated == true` no later than the immediately following
  `step()`.
- **G7 — reset determinism/history independence (critical):** two fresh
  environments are dirtied by different finite action histories, then reset
  with seed `20260828` and given the same four-action sequence. Reset
  observations and every subsequent `(observation, reward, terminated,
  truncated, info)` value must match exactly after canonical JSON conversion.
- **G8 — action affects physics (critical):** from identical seeded resets, 25
  steps of a home joint target and 25 steps of an alternating offset target are
  run in separate environments. The final generalized-position L2 distance
  must be finite and at least `1e-3`; otherwise the action seam is inert.

Additional diagnostics (non-gating) record the real model names/order, reset
observation residuals, per-step velocities, final state separation, package
versions, and exceptions. The experiment will not mutate product files or
tracked evaluation ledgers.

## Planned reproduction

```bash
.parcel/bin/python research/20260828/rl-env-readiness/experiment.py \
  --out research/20260828/rl-env-readiness/results-run1.json
.parcel/bin/python research/20260828/rl-env-readiness/experiment.py \
  --out research/20260828/rl-env-readiness/results-run2.json
.parcel/bin/python research/20260828/rl-env-readiness/verify_results.py \
  --first research/20260828/rl-env-readiness/results-run1.json \
  --second research/20260828/rl-env-readiness/results-run2.json \
  --out research/20260828/rl-env-readiness/verification.json
```

