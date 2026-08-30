# MJLAB-1 — official Unitree Go2 simulator feasibility

## Outcome

The official `unitree_rl_mjlab` Go2 stack is **practically feasible as a
pinned, workstation-side lower-locomotion research substrate**. It is **not a
clean-install pass**, not a trained walking policy, and not evidence that Parcel
is safe to mount or move on a physical Go2.

The strict preregistered all-gates verdict is **FAIL** because the untouched
dependency declaration did not import after a clean install. After four
environment-only compatibility additions—without editing upstream source—the
Flat/Rough tasks registered, two independent 64-environment physics probes
passed, and the exact three-iteration PPO/checkpoint smoke passed.

| Gate | Result | What it means |
|---|---:|---|
| MJF-H1 clean install and registration | **FAIL** | Resolver-selected MuJoCo 3.12.0 is incompatible with pinned MuJoCo-Warp 3.5.0. |
| Remediated registration | **PASS** | Exact `Unitree-Go2-Flat` and `Unitree-Go2-Rough` tasks load with the pinned compatibility set. |
| MJF-H2 headless physics | **PASS, pinned env** | Two fresh processes exceeded the 3,200 environment-step/s gate with finite state. |
| MJF-H3 PPO/checkpoint pipeline | **PASS, pinned env** | 64 × 24 × 3 = 4,608 environment-steps, three iterations, native checkpoints, and ONNX export completed. |
| MJF-H4 applicability | **Useful but strict gate false** | Lower-layer hooks exist; companion perception, planning, conversation, social navigation, and safety do not. |
| Physical mount readiness | **NO-GO** | This probe supplies no hardware, safety, Orin, or locomotion-quality evidence. |

See [RESULTS.md](RESULTS.md) for measurements and failure provenance and
[VERDICT.md](VERDICT.md) for the integration decision.

## Reproduce the pinned environment

The test used upstream commit
`1425b15f73bd4095f0df53709d7c389c3eb9e790`, CPython 3.11, and an isolated
virtual environment. Parcel's `.parcel` environment was not changed.

```bash
git clone https://github.com/unitreerobotics/unitree_rl_mjlab.git /path/to/unitree_rl_mjlab
git -C /path/to/unitree_rl_mjlab checkout 1425b15f73bd4095f0df53709d7c389c3eb9e790
python3.11 -m venv /path/to/venv
/path/to/venv/bin/python -m pip install -c constraints.txt -e /path/to/unitree_rl_mjlab
/path/to/venv/bin/python -m pip install -c constraints.txt scipy wandb
```

`constraints.txt` is the minimal compatibility set. The complete observed
resolver output is in `raw/pip-freeze.txt`; it contains a local editable path
and is therefore an audit record, not a portable lockfile.

Run the task and physics checks from the upstream checkout so its `src` package
is importable:

```bash
PYTHONDONTWRITEBYTECODE=1 /path/to/venv/bin/python \
  /path/to/Parcel/research/20260829/mjlab-feasibility-1/probe_registration.py \
  --source /path/to/unitree_rl_mjlab \
  --out /tmp/mjlab-registration.json

CUDA_VISIBLE_DEVICES=0 MUJOCO_GL=egl PYTHONDONTWRITEBYTECODE=1 \
  /path/to/venv/bin/python \
  /path/to/Parcel/research/20260829/mjlab-feasibility-1/probe_physics.py \
  --source /path/to/unitree_rl_mjlab \
  --out /tmp/mjlab-physics.json \
  --run-id reproduction
```

The frozen H3 command was:

```bash
CUDA_VISIBLE_DEVICES=0 MUJOCO_GL=egl WANDB_MODE=offline \
  /path/to/venv/bin/python scripts/train.py Unitree-Go2-Flat \
  --env.scene.num-envs=64 \
  --agent.max-iterations=3 \
  --agent.save-interval=1 \
  --agent.seed=42 \
  --agent.run-name=mjlab1-h3-pinned
```

This command is a pipeline smoke only. Do not deploy the retained checkpoint.

## Evidence map

- `DESIGN.md` — preregistration and interpretation boundary
- `raw/clean-install.json` — frozen clean-install H1 failure
- `registration.json` — corrected task registry evidence
- `physics-run-3.json`, `physics-run-4.json` — the two evidentiary H2 runs
- `physics-run-5-posthoc-rss.json` — explicitly post-hoc RSS supplement
- `training-result.json` — H3 configuration, samples, resources, and hashes
- `applicability.json` — inspected lower-layer hooks and missing companion scope
- `verification.json` — independent recomputation plus an in-memory tamper test
- `artifacts/model_2.pt`, `artifacts/policy.onnx` — retained smoke outputs; **not deployable policies**
- `raw/` — stdout/stderr, failed attempts, timing, and dependency remediation evidence

Verify the retained bundle with:

```bash
python3 verify_results.py --root . --out verification.json
```

## Safety boundary

The tested task has no Parcel camera/Mid-360/audio pipeline, dynamic humans,
sidewalk/crosswalk/elevator/stair scenarios, semantic grounding, Model A/Model B
contract, interruption ledger, network/acoustic faults, EDU+ payload model,
independent safety supervisor, or commissioned sole-writer gateway. Its
`terrain_scan` is a simulated height-grid ray cast, not a Mid-360 integration.
The upstream deployment code was inspected but was not compiled, launched, or
connected to a robot.

