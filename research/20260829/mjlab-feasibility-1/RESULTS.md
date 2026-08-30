# MJLAB-1 results

## Bottom line

Strict preregistered verdict: **FAIL**. Practical pinned-environment verdict:
**feasible for lower-layer locomotion research**. Physical readiness:
**unsupported / NO-GO**.

The distinction matters. The official stack executed real MuJoCo-Warp physics,
PPO optimization, checkpointing, and ONNX export. It did so only after explicit
dependency pins that the upstream install metadata does not currently enforce.
Nothing in this experiment establishes a useful walking policy or the companion
robot's navigation, conversation, or safety.

## Source and machine

- Upstream repository: `unitreerobotics/unitree_rl_mjlab`
- Commit: `1425b15f73bd4095f0df53709d7c389c3eb9e790`
- Upstream tracked source edits: none
- Host: Ubuntu 26.04, Linux 7.0.0-30
- GPU: NVIDIA RTX 5000 Ada Generation, 32,760 MiB; driver 595.84
- Python: CPython 3.11.15 in an isolated 5.9 GiB virtual environment
- Key final versions: MjLab 1.2.0, MuJoCo-Warp 3.5.0, MuJoCo 3.5.0,
  Warp 1.12.0, Torch 2.13.0, RSL-RL 5.0.1, SciPy 1.17.1, W&B 0.22.3

## MJF-H1 — clean install failed

The unmodified upstream package declares `mjlab==1.2.0` and
`mujoco-warp==3.5.0`. Their transitive metadata places lower bounds, but no upper
bounds, on MuJoCo and Warp. On 2026-08-29 the resolver selected MuJoCo 3.12.0,
Warp 1.16.0, and W&B 0.29.0. `pip check` reported no broken requirements.

The first task-list import nevertheless failed before CLI parsing:

```text
AttributeError: type object 'mujoco._enums.mjtEnableBit'
has no attribute 'mjENBL_MULTICCD'
```

MuJoCo-Warp 3.5.0 imports that enum, while resolver-selected MuJoCo 3.12.0 no
longer exposes it. This is a verified H1 failure, not waived by later repairs.
The failure stderr hash is
`1f2b5fb2f4a9a2020a17781c9507049eee04ad918b9555a45b964979e3d8d76e`.

### Environment-only remediation sequence

No upstream source was patched.

1. `mujoco==3.5.0` fixed the enum mismatch.
2. The next import exposed an undeclared module-scope `scipy` dependency in
   MjLab terrain code; `scipy==1.17.1` fixed it.
3. Exact `Unitree-Go2-Flat` and `Unitree-Go2-Rough` registration then passed.
4. The first environment construction exposed `warp-lang==1.16.0` API drift:
   MjLab 1.2.0 accesses `wp.context`, which 1.16 removed. Pinning MjLab's exact
   lower bound, `warp-lang==1.12.0`, fixed construction.
5. The first training initialization exposed W&B 0.29 API drift in RSL-RL's
   `wandb.Settings(start_method="thread")`. Pinning MjLab's exact W&B lower
   bound, `wandb==0.22.3`, and using offline logging fixed training.

The raw bundle preserves every layer. `raw/training-cli-failure.log` is a test
harness invocation error (`--gpu-ids 0` was not the Tyro list syntax); the
successful run used the upstream default `[0]`. It is not counted as an
upstream defect. `raw/physics-run-2.log` likewise preserves a probe-only type
assumption about raw Warp arrays; the frozen gate requires tensor observations,
rewards, and robot state, all of which the corrected probe checks.

## MJF-H2 — remediated headless physics passed

Both evidentiary runs were fresh OS processes with the same probe hash
`a048429c8ae3084e78a593c9216fd48154e1812fcbdbf0536b9bbe11669ca88e`.
Each constructed 64 `Unitree-Go2-Flat` environments on CUDA, reset at seed 42,
ran 64 warm-up plus 256 timed policy steps, and checked finiteness on every step
for actor and critic observations, reward, root pose/velocity, and all 12 joint
positions/velocities.

| Measurement | Run 3 | Run 4 |
|---|---:|---:|
| Physics timestep | 5 ms | 5 ms |
| Policy timestep | 20 ms (50 Hz) | 20 ms (50 Hz) |
| Actor / critic dimensions | 47 / 74 | 47 / 74 |
| Action / joint dimensions | 12 / 12 | 12 / 12 |
| Timed environment-steps | 16,384 | 16,384 |
| Timed wall time | 2.6429 s | 2.7612 s |
| Throughput | 6,199.34 env-step/s | 5,933.55 env-step/s |
| Whole-process wall time | 12.245 s | 12.150 s |
| Non-finite values | 0 | 0 |
| Termination events across warm-up + timed loop | 490 | 488 |

Aggregate evidentiary sample count was 32,768 timed and 40,960 checked
environment-steps. Both runs cleared the 3,200 environment-step/s gate by at
least 85%. Their JSON hashes are
`433f3a50b37cb7d5d4b018e7ba93c7b621c980e4b799f998bdb4eba6ce19d564`
and `b97b94940a42db5cdcc8ce56ce08e3f6171d64fb042c8aa136cbf5a596610964`.

The 490/488 resets are not a success signal. The deterministic actions were
deliberately low-amplitude, untrained residuals used to test execution. Frequent
illegal-contact/fall resets are expected and explicitly prohibit a locomotion
quality claim.

### Post-hoc RSS supplement

A third identical run was added only after H2 to measure RSS; it does not
replace the two preregistered evidentiary runs. It passed at 5,864.05
environment-step/s with maximum RSS 2,697,268 KiB (2.572 GiB).

## MJF-H3 — remediated PPO/checkpoint pipeline passed

The exact upstream trainer ran 64 environments, 24 rollout steps per
environment, three learning iterations, checkpoint interval one, and seed 42:

- total samples: exactly 64 × 24 × 3 = **4,608 environment-steps**;
- iteration indices: 0, 1, 2;
- whole-process wall time: **13.20 s**;
- maximum RSS: **3,155,128 KiB (3.009 GiB)**;
- native checkpoints: `model_0.pt`, `model_1.pt`, `model_2.pt`, each 4,741,375 bytes;
- final checkpoint hash: `c94bba8935f26b18018d9eed7a1d92a36dc75830eb1a1a38b74bf00662d1060a`;
- ONNX export: 763,857 bytes, hash
  `672c9118480fbd9900f57849e69e5a2d7978a9044d7aac044a9a1b9b8e1e9791`.

The retained native checkpoint reloads and contains actor, critic, optimizer,
iteration, and info state. `agent.yaml` and `env.yaml` independently record all
frozen parameters.

This is not a training-quality result. Mean reward was -3.26, -3.82, and -3.90
across the three logged iterations, and illegal-contact terminations were common.
Three iterations are enough to validate rollout, gradient update, logging,
checkpoint, and export plumbing—nothing more.

## MJF-H4 — lower-layer hooks exist; companion scope does not

Inspection and runtime metadata found:

- 12 named Go2 leg joints and a 12-dimensional joint-position action;
- 50 Hz velocity-command task with actor/critic observations;
- foot contact and non-foot collision sensing;
- procedural rough terrain plus flat terrain;
- friction, encoder-bias, center-of-mass, and push randomization hooks;
- ONNX export and a separate Go2 deployment controller with an aarch64 branch;
- upstream guidance to validate in `unitree_mujoco` before real deployment.

The tested task does not contain Parcel camera or Mid-360 data, audio, dynamic
humans, sidewalks, crosswalks, elevators, stairs, semantic grounding, Model A or
Model B, interruption/resume task state, Starlink/acoustic faults, AGX Orin
benchmarks, EDU+ payload dynamics, or Parcel's independent STOP/sole-writer
authority. The simulator `terrain_scan` is a height-grid ray cast, not a Mid-360
sensor model.

## Verification

`verify_results.py` recomputed source/script/file hashes and all numeric gates,
verified the retained model/config/ONNX copies, and rejected an in-memory record
whose probe hash was tampered. `verification.json` reports:

- clean H1 failure verified: true;
- remediated registration: true;
- remediated H2: true;
- remediated H3: true;
- pinned lower-layer hooks: true;
- strict all-preregistered gates: false;
- practical pinned-environment feasibility: true;
- physical readiness: false;
- verifier pass: true.

