# Parcel dependency & environment guide

Host inventory and install paths for running Parcel simulation, city navigation,
and (optionally) MetaUrban on this machine.

> **Targeted recheck, 2026-08-22.** The original host inventory below was made
> on 2026-08-04. The recheck covered the claims most likely to affect setup:
> kernel, local speech artifacts, semantic endpointing, USB audio, native
> PortAudio, and package-data parity. It did not recommission every service or
> device in this guide. In particular, an artifact being present is not evidence
> of a live service, a usable audio stream, or a physical robot capability.

> **Release-integrity warning from the current-code audit.** `pyproject.toml`
> advertises Python `>=3.10`, but CI exercises only 3.12. On Python 3.11.15,
> `realtime/protocol.py` fails dataclass import at `RetainedEvent.fields`, causing
> 69 collection errors and leaving 2,634 current test nodes absent relative to the
> 8,701-node Python 3.14 collection. The voice extra shown below also requires
> `websockets>=17`, whose interpreter floor conflicts with Python 3.10. Treat the
> supported-version claim as red until IG-2 defines and proves the matrix; the
> `.parcel` lock is a 3.14 host snapshot, not cross-Python evidence.
>
> The former independent `third_party/unitree_mujoco` blocker is closed. A
> license/provenance-reviewed 20-file Go2 subset is tracked and hash-pinned, and
> the asset-first gate compiles both product scenes from a clean checkout. This
> is source hermeticity only; it is not SDK2/DDS, articulated-policy, Orin, or
> physical-robot evidence.

## Host snapshot (checked 2026-08-04)

| Item | Value |
| --- | --- |
| OS | Ubuntu 26.04 (kernel `7.0.0-28-generic` on 2026-08-04; `7.0.0-29-generic` in the 2026-08-22 targeted recheck) |
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

Parcel uses **three isolated Python environments** on purpose (the third is a
planned environment until Conda/MetaUrban is installed):

| Environment | Python | Purpose | Where |
| --- | --- | --- | --- |
| **`.parcel`** | 3.14 | App, MuJoCo preview, skills, `grid_v1` navigation, offline scaffolds, tests | This repo |
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
| websockets | `>=17,<18` |

This table reports the current metadata, not a working Python-3.10 resolution.
The corrective design either uses interpreter markers for compatible WebSocket
branches or narrows the declared extra; every supported branch then needs real
install/import/loopback tests.

**Native OS note:** the Python `sounddevice` package is installed, but its
import currently fails because `libportaudio2` is absent. Install the native
runtime (`sudo apt install libportaudio2`) before treating capture/playback as
available. Hardware enumeration performed by Parcel is a separate check and
does not prove the Python PortAudio binding can open a stream.

### Recorded lock snapshot (incomplete relative to current `.parcel`)

See [`requirements-lock.txt`](../requirements-lock.txt) at the repo root (generated
from `pip freeze` after install). Key versions at last install:

The 2026-08-22 targeted recheck normalized installed/locked distribution names
and, ignoring the editable Parcel entry, found 17 distributions present in
`.parcel` but absent from the lock. They include the endpointing runtime
(`onnxruntime`, `sherpa-onnx`, and `sherpa-onnx-core`) and packages used by the
current test/model tooling. The table is therefore a useful historical version
snapshot, not a complete clean-environment reproduction input. Refresh and
classification are tracked by the in-flight
[R30 card](../scrum/20260821/task_18/README.md).

| Package | Version |
| --- | --- |
| mujoco | 3.11.0 |
| numpy | 2.5.1 |
| PyYAML | 6.0.3 |
| pytest | 8.4.2 |
| ruff | 0.16.1 |
| msgpack | 1.2.1 |
| sounddevice | 0.5.5 |
| websockets | 17.0.1 |
| parcel-robot-dog | 0.1.0 (editable) |

MuJoCo pulls transitive deps: `absl-py`, `etils`, `glfw`, `PyOpenGL`, `fsspec`, etc.

### Smoke checks

```bash
source .parcel/bin/activate
python -c "import mujoco; print(mujoco.__version__)"
pytest tests/test_navigation.py -q
python examples/nav_city_smoke.py
```

The city-navigation smoke works **offline** with `grid_v1` in its loud
missing-scan fallback inside a kinematic scaffold with synthetic pedestrians
(no MetaUrban required). Use the headless/MuJoCo tests for the real raycast-grid
path; this small smoke is an API check, not planner-quality evidence.

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

Piper is the configured local-cascade TTS choice. In the 2026-08-22 recheck its
binary, configured voice, and companion JSON all exist at
`third_party/piper/piper`, `models/piper/voice.onnx`, and
`models/piper/voice.onnx.json`. Parcel's separate in-process endpointing stack is
also present: the configured Silero v6 and Smart Turn v3 ONNX weights resolve,
`.parcel` imports `onnxruntime 1.28.0` and `sherpa_onnx 1.13.6`, and the canonical
local-cascade profile selects `endpointing: semantic`. These files are distinct
from whisper.cpp's own Silero model.

Check the exact speech state without starting anything:

```bash
./scripts/run_speech_services.sh --check
```

In the 2026-08-22 recheck it exits nonzero only because whisper.cpp is installed
but not running; it reports all three Piper artifacts healthy and reads the
voice metadata as 22,050 Hz. `scripts/install_speech_services.sh` remains the
tracked installer. Existing artifacts prove readiness checks and provider
resolution, not that every installer download/build branch is reproducible or
that audio has played through a physical endpoint.

Fish was installed with
`uv sync --python 3.12 --extra cu129 --no-install-package pyaudio`. The API
server does not use PyAudio; omitting it
avoids a false dependency on missing PortAudio development headers. The Fish
model requires roughly 24 GB of VRAM and has a research/non-commercial model
license, so it is opt-in in `launch_stack.sh`.

The 2026-08-04 desktop audit found the Realtek ALC1220 and a powered Bluetooth
controller, but only a PipeWire dummy output and no USB array. That last fact is
now superseded: the 2026-08-22 recheck sees a Seeed ReSpeaker XVF3800 4-Mic
Array as USB ID `2886:001a`. USB enumeration is only attachment evidence. The
default `.parcel` process still cannot import `sounddevice` because the native
PortAudio library is absent; no physical input/output product stream or
through-air AEC result was produced. XVF3800 control/DoA reads are additionally
blocked by the current usbfs permissions until the documented udev rule is
applied. The hosted browser-audio lane can bypass Python PortAudio, but it does
not commission this local hardware path.

The D0 duplex-frame, filler, and local JSONL logging code adds no model weights
or third-party runtime: it is stdlib/NumPy code inside `.parcel`. This is an
interface and corpus-building slice, not a downloaded dual-head model. D1 model
training/inference dependencies and weights do not exist in this checkout.

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

The historical frozen five-case GPU planner run passed 5/5 and reduced median
usable-plan latency from 19,664.294 ms on CPU to 5,657.459 ms, but it executed
zero physical episodes. A fresh 2026-08-26 evaluation of the current admitted
path scored 3/5, so the older row is retained as artifact evidence rather than
the current capability claim. The safe staging recipe, exact audit, placement
evidence, and limitations are in
[`REASONER_GPU_PROFILE.md`](REASONER_GPU_PROFILE.md); current results are in
[`../research/20260826/system-readiness/RESULTS.md`](../research/20260826/system-readiness/RESULTS.md).
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
bash scripts/setup_metaurban.sh
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

### Navigators

| Model id | Type | Notes |
| --- | --- | --- |
| `grid_v1` | grid | **Production default**; raycast occupancy + A* |
| `stub_v0` | stub | Loud fallback / tests; no weights |
| `citywalker_v1` / `navila_v1` / … | learned metadata | Fail closed until an inference adapter exists |

Keep `active_model: grid_v1`; see [`NAVIGATION_CITY.md`](NAVIGATION_CITY.md).

---

## 4. Recommended extras (not yet installed)

| Component | Why | Env |
| --- | --- | --- |
| Miniconda + Python 3.9 | MetaUrban | `parcel-metaurban` |
| torch (CUDA) | CityWalker / NaVILA / NoMaD | `parcel-metaurban` |
| gymnasium | Already in MetaUrban script; optional in `.parcel` for Gym typing | either |
| stable-baselines3 | Future PPO experiments only **after** a real MetaUrban observation/action/reward adapter and Gymnasium compliance exist | `parcel-metaurban` |
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
| MuJoCo `grid_v1` raycast navigation | Yes in runtime/headless regression paths; kinematic simulation only |
| Predictive owner/dynamic-agent navigation | Yes in the source runtime: owner filter, predicted-agent cost, all-track TTC gate, S-curve handoff, and `SearchOwner`; measured product gains are mixed and physical perception is absent |
| D0 TEXT+ACT frames and fillers | Yes in text/scripted paths, with a shadow ACT consumer; no model-driven ACT execution and no real audible-filler timing |
| Attention reaction foundations | Pure Python modules/tests only; no mic/prosody/control-loop wiring |
| Navigation suspend/resume | Pause/runtime primitives and unit/composition tests exist; automatic semantic resume does not yet consume stored NavigateTo/follow intents or enforce fresh-observation metadata |
| MetaUrban API scaffold + synthetic pedestrians | Yes (`MetaUrbanNavEnv(use_metaurban=False)`); missing-scan fallback, not the real vendor backend |
| Gemma structured action reasoning | Yes (CPU fallback or admitted CUDA llama.cpp profile) |
| Gemma GPU offload | Yes: verified official b10236 CUDA 12 OCI runtime; 31/31 layers measured. Source compilation remains optional/unavailable. |
| Fish S2 Pro server | Yes, opt-in (uses most GPU VRAM) |
| Microphone/speaker duplex | Hosted browser audio is implemented; the local physical path remains **blocked/uncommissioned**. The XVF3800 and Piper artifacts are present, but native PortAudio is absent, no physical product stream has completed, DoA access awaits the udev permission, and hardware AEC has not been measured. |
| Semantic endpointing | Implemented, runtime-wired, and selected in the canonical local-cascade config; ONNX Runtime and both configured weights resolve. No live-microphone cutoff/latency result follows from startup availability. |
| BARN ROS/Gazebo runtime smoke | Yes, cache-only Bubblewrap/PRoot: unchanged upstream MPPI completed one public world; no Parcel/SIF/score claim |
| BARN Parcel 50×10 public protocol | **Blocked**: the corrected single-world hook started but never translated enough to begin the evaluator trial, so no row exists; first-sensor/command telemetry must localize the liveness stall, and upstream-tested Singularity/SIF execution is still unavailable |
| Living MetaUrban city + SMPL humans | **Blocked** on a real Parcel backend adapter (and Conda 3.9) |
| CityWalker / NaVILA inference | **Blocked** on vendor adapters, dependencies, and weights |

---

## 6. Bootstrap from the incomplete environment snapshot

These commands bootstrap an environment **from a Parcel source checkout**; they
do not reproduce the audited environment byte-for-byte. The current
`requirements-lock.txt` omits 17 distributions present in `.parcel`, including
parts of the endpointing runtime, as documented above. Treat it as an incomplete
snapshot until a clean, verified lock-generation workflow closes that gap.
The earlier package-data drift is no longer the current blocker: N27 generates a
manifest and byte-checks 91 curated runtime config, prompt, skill, fixture, and
navigation assets against canonical source. The former fallback-only
`fish_streaming` / `barge_in` divergence is therefore historical. Keep two
claims separate, however: the in-process source/package parity gate is recorded
green, while a clean build/install-wheel smoke is a distinct slow-tier check and
has no recorded result in this targeted recheck. The visible, uncommitted W-1
worktree separately adds package-data globs and integrity tests for the city
scene's referenced textures/meshes; that is not part of the committed 91-asset
parity claim and still is not an installed-wheel result. Third-party services,
model weights, native libraries, and simulator/vendor assets not explicitly in
those ship sets remain external deployment dependencies.

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
