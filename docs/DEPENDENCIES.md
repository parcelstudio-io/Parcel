# Parcel dependency & environment guide

Host inventory and install paths for running Parcel simulation, city navigation,
and (optionally) MetaUrban on this machine.

## Host snapshot (2026-08-02)

| Item | Value |
| --- | --- |
| OS | Ubuntu 26.04 (kernel 7.0.0-28-generic) |
| System Python | **3.14.4** only (`/usr/bin/python3`) |
| GPU | **NVIDIA RTX 5000 Ada Generation** (AD102GL) |
| VRAM | 32760 MiB |
| NVIDIA driver | **595.84** (`nvidia-driver-595-open`) |
| Reported CUDA (driver) | **13.2** |
| `nvcc` toolkit | Not installed (optional; not required for PyTorch wheels) |
| Conda / Miniconda | **Not installed** |
| Parcel app venv | `.parcel` (Python 3.14) at repo root |

Verify GPU at any time:

```bash
nvidia-smi
```

## Isolated environments (do not mix)

Parcel uses **two** Python stacks on purpose:

| Environment | Python | Purpose | Where |
| --- | --- | --- | --- |
| **`.parcel`** | 3.14 | App, MuJoCo preview, skills, stub city nav, tests | This repo |
| **Fish `.venv`** | 3.12 | Fish S2 Pro, Torch 2.8 + CUDA 12.9 | `third_party/fish-speech/` |
| **`parcel-metaurban`** (Conda) | ~3.9 | Living city + SMPL pedestrians (MetaUrban) | Separate Conda env |

MetaUrban / `metaurban` expects **Python ~3.9** and refuses 3.12+. It must
**not** be installed into `.parcel`.

---

## 1. `.parcel` — primary app environment

### Create / activate

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel

# If python3-venv is available:
#   python3 -m venv .parcel

# On this host ensurepip was missing; venv was bootstrapped with get-pip.py.
# Prefer recreating via:
python3 -m venv --without-pip .parcel   # only if recreate needed
# then bootstrap pip, OR keep the existing .parcel below.

touch .parcel/COLCON_IGNORE
source .parcel/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,voice]"
```

Daily use:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
source .parcel/bin/activate
```

### Declared dependencies (`pyproject.toml`)

**Core**

| Package | Constraint |
| --- | --- |
| mujoco | `>=3.3,<4` |
| numpy | `>=2,<3` |
| PyYAML | `>=6,<7` |

**Optional `dev`**

| Package | Constraint |
| --- | --- |
| pytest | `>=8,<9` |
| ruff | `>=0.12,<1` |

**Optional `voice`**

| Package | Constraint |
| --- | --- |
| sounddevice | `>=0.5,<1` |
| msgpack | `>=1.1,<2` |

**Native OS note:** `sounddevice` needs `libportaudio2` (`sudo apt install libportaudio2`).

### Locked freeze (installed in `.parcel`)

See [`requirements-lock.txt`](../requirements-lock.txt) at the repo root (generated
from `pip freeze` after install). Key versions at last install:

| Package | Version |
| --- | --- |
| mujoco | 3.11.0 |
| numpy | 2.5.1 |
| PyYAML | 6.0.3 |
| pytest | 8.4.2 |
| ruff | 0.16.1 |
| sounddevice | 0.5.5 |
| parcel-robot-dog | 0.1.0 (editable) |

MuJoCo pulls transitive deps: `absl-py`, `etils`, `glfw`, `PyOpenGL`, `fsspec`, etc.

### Smoke checks

```bash
source .parcel/bin/activate
python -c "import mujoco; print(mujoco.__version__)"
pytest tests/test_navigation.py -q
python examples/nav_city_smoke.py
```

City navigation smoke works **offline** with the kinematic stub city and
stub pedestrians (no MetaUrban required).

## 2. Local model services installed on this host

| Service | Runtime | Weights | Launch |
| --- | --- | --- | --- |
| Gemma 4 26B-A4B QAT Q4 | official llama.cpp CPU binary | 14.4 GB GGUF | `scripts/launch_reasoner.sh` |
| Gemma CUDA profile | official, provenance-pinned llama.cpp b10236 CUDA 12 OCI runtime | same verified GGUF | `scripts/launch_reasoner_gpu.sh` (**admitted; 31/31 layers measured**) |
| Ministral 3 8B Instruct challenger | same pinned b10236 CUDA 12 OCI runtime through an overlay profile | 5.20 GB Q4_K_M GGUF | **installed and measured at 35/35 layers, but rejected for activation after 5/10 conversation and 3/5 PlanIR** |
| Ministral 3 8B Reasoning planner control | same pinned b10236 CUDA 12 OCI runtime through a separate overlay profile | 5.20 GB Q4_K_M GGUF | **installed and measured at 35/35 layers, but rejected at a predeclared 0/1 PlanSketch compatibility gate after malformed output exhausted 1,024 tokens; no full-suite or conversation claim** |
| Fish Audio S2 Pro | isolated uv Python 3.12, Torch 2.8 `cu129` | about 11 GB | `scripts/launch_fish_speech.sh` |
| whisper.cpp `base.en` | official CPU binary | 142 MB | `scripts/launch_whisper.sh` |
| Silero VAD v6.2 | whisper.cpp VAD model | 885 KB | enabled by `scripts/launch_whisper.sh` |

Fish was installed with
`uv sync --python 3.12 --extra cu129 --no-install-package pyaudio`. The API
server does not use PyAudio; omitting it
avoids a false dependency on missing PortAudio development headers. The Fish
model requires roughly 24 GB of VRAM and has a research/non-commercial model
license, so it is opt-in in `launch_stack.sh`.

ALSA detects the Realtek ALC1220 and direct capture works, but PipeWire has no
connected source and only Dummy Output. Parcel therefore selects text mode.
Connecting a microphone/speaker is still required before enabling audio I/O.

The b10235 CPU fallback is not CUDA-capable, but Parcel now stages the exact
official b10236 CUDA 12 OCI runtime separately. Its 13/13 image layers, 7/7
critical files, server version/hash, model hash, CUDA device, compute
capability, and VRAM floors passed admission. A verbose run measured 31/31
layers offloaded and 15,280 MiB attributed to the idle loaded server. Run the
read-only doctor before making any GPU claim:

```bash
PYTHONPATH=src .parcel/bin/python -m parcel_robot.reasoner_gpu \
  --profile configs/reasoner/llama_cpp_cuda12_oci_b10236.json \
  --use-cuda-build-output --require-inference-ready
```

The frozen five-case GPU planner run passed 5/5 and reduced median usable-plan
latency from 19,664.294 ms on CPU to 5,657.459 ms, but it executed zero
physical episodes. The safe staging recipe, exact audit, placement evidence,
and limitations are in [`REASONER_GPU_PROFILE.md`](REASONER_GPU_PROFILE.md).
The OCI path never overwrites the working CPU binary.

---

## 3. MetaUrban city + pedestrians (GPU path)

**Status on this host:** GPU is healthy; Conda / Python 3.9 is **not** installed
yet, so MetaUrban cannot be activated until a Conda env is created.

### Prerequisites

1. Miniconda or Anaconda (user-space install; no need to use system Python 3.14)
2. NVIDIA driver (already OK — 595.84)
3. Prefer a CUDA-enabled PyTorch wheel matching the driver when loading nav models

### Install

```bash
# After Miniconda is on PATH:
cd /home/jaewoo-jang/Desktop/Projects/Parcel
./scripts/setup_metaurban.sh
# Creates/uses conda env: parcel-metaurban (Python 3.9 by default)
```

Packages the script installs into that env:

| Package | Role |
| --- | --- |
| gymnasium `>=0.28` | RL API |
| numpy, pyyaml | Shared basics |
| metaurban (editable from `third_party/metaurban`) | Living city + pedestrians |

Then:

```bash
conda activate parcel-metaurban
cd /home/jaewoo-jang/Desktop/Projects/Parcel
PYTHONPATH=src python examples/nav_city_smoke.py
```

That smoke command uses Parcel's offline kinematic scaffold. Installing
MetaUrban prepares the vendor research environment, but `use_metaurban=True`
currently fails explicitly because a real step/observation/reward adapter has
not been implemented.

Enable in config when ready:

```yaml
# configs/navigation/default.yaml
metaurban:
  enabled: true
  density_ped: 1.0
  density_obj: 0.4
  mode: social_nav
```

### Open-weight navigators (optional, GPU)

The following models are registered as research targets:

| Model id | Type | Notes |
| --- | --- | --- |
| `stub_v0` | stub | Default; no weights |
| `citywalker_v1` | citywalker | Urban visual nav |
| `navila_v1` | navila | Legged + language |
| `nomad_v1` / `vint_v1` | foundation | Fine-tune / IL base |

These adapters are not inference implementations: they raise even if a
checkpoint exists until vendor preprocessing, inference, and output conversion
are wired and tested. Keep `active_model: stub_v0`; see
[`NAVIGATION_CITY.md`](NAVIGATION_CITY.md).

---

## 4. Recommended extras (not yet installed)

| Component | Why | Env |
| --- | --- | --- |
| Miniconda + Python 3.9 | MetaUrban | `parcel-metaurban` |
| torch (CUDA) | CityWalker / NaVILA / NoMaD | `parcel-metaurban` |
| gymnasium | Already in MetaUrban script; optional in `.parcel` for Gym typing | either |
| stable-baselines3 | PPO fine-tune on `MetaUrbanNavEnv` | `parcel-metaurban` |
| `portaudio19-dev` | Optional Python/PyAudio client; Fish API does not need it | OS |
| `python3-tk` | `parcel-control` GUI | OS |
| CUDA toolkit (`nvcc`) | llama.cpp CUDA build and optional CUDA extensions; absent now | isolated toolchain or OS (optional) |
| CMake + Ninja + C/C++ compilers | pinned llama.cpp CUDA build; absent now | isolated toolchain or OS (optional) |

---

## 5. What runs today vs blocked

| Capability | On this host now |
| --- | --- |
| GPU compute / CUDA driver | Yes (RTX 5000 Ada) |
| `.parcel` MuJoCo + skills + tests | Yes |
| Stub city nav + pedestrian braking | Yes (`MetaUrbanNavEnv` kinematic stub) |
| Gemma structured action reasoning | Yes (CPU fallback or admitted CUDA llama.cpp profile) |
| Gemma GPU offload | Yes: verified official b10236 CUDA 12 OCI runtime; 31/31 layers measured. Source compilation remains optional/unavailable. |
| Fish S2 Pro server | Yes, opt-in (uses most GPU VRAM) |
| Microphone/speaker duplex | Text prerequisite only; no connected endpoints |
| BARN ROS/Gazebo runtime smoke | Yes, cache-only Bubblewrap/PRoot: unchanged upstream MPPI completed one public world; no Parcel/SIF/score claim |
| BARN Parcel 50×10 public protocol | **Blocked**: the corrected single-world hook started but never translated enough to begin the evaluator trial, so no row exists; first-sensor/command telemetry must localize the liveness stall, and upstream-tested Singularity/SIF execution is still unavailable |
| Living MetaUrban city + SMPL humans | **Blocked** on a real Parcel backend adapter (and Conda 3.9) |
| CityWalker / NaVILA inference | **Blocked** on vendor adapters, dependencies, and weights |

---

## 6. Reproduce from lockfile

```bash
source .parcel/bin/activate
python -m pip install -r requirements-lock.txt
# Prefer editable project install for development:
python -m pip install -e ".[dev,voice]"
```

Canonical declared deps remain in [`pyproject.toml`](../pyproject.toml).
The lock uses `-e .` for the local project rather than a private SSH Git URL, so
run it from the repository root.
Refresh the lock after intentional upgrades:

```bash
source .parcel/bin/activate
python -m pip freeze > requirements-lock.txt
```
