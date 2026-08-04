# Current implementation status

**Snapshot:** 2026-08-04. This page is the operational truth for the current
checkout and desktop. Architecture and research documents explain where Parcel
is going; this page distinguishes code that exists from code that is wired,
configured, and verified on the available hardware.

Status terms used throughout the documentation:

- **Implemented** — runtime code and tests exist; this does not imply physical
  production readiness.
- **Wired** — the default runtime reaches that code path.
- **Operational** — its required local service or device was verified on this
  desktop.
- **Experimental** — isolated research code or an eval adapter exists, but it
  is not an admitted product path.
- **Planned** — design only; do not infer a working capability.

## Capability matrix

| Capability | Code | Default runtime | Verified here | Important boundary |
| --- | --- | --- | --- | --- |
| Browser text conversation and commands | Implemented | Wired | Yes | A local reasoner must be healthy for LLM conversation; deterministic commands still work with `--no-llm`. |
| Gemma conversation + PlanIR | Implemented | Wired when `--llm` is used | Installed; CPU and admitted CUDA launch profiles exist | The model proposes typed semantic plans. It never owns motor or joint output. |
| Separate planning model | Implemented | Optional; absent from the canonical config | Evaluated challengers were not admitted | With no `planner_model:` section, conversation and planning share Gemma. |
| MuJoCo city | Implemented | Wired | Yes | Dynamic actors and sensor contracts are useful regressions; Go2 base motion is still a kinematic preview, not validated legged dynamics. |
| `grid_v1` navigation | Implemented | Wired and selected | Yes in headless/MuJoCo gates | Rolling 2-D occupancy, A*, forward-preferred tracking, and an independent reactive safety gate; it is not a learned social-navigation policy. |
| Semantic sidewalk/object goals | Implemented | Wired in the simulated city | Yes in headless tests | Semantic candidates currently come from simulator observations. A physical camera/LiDAR perception stack is not implemented. |
| Owner following and owner-relative motion | Implemented | Wired | Yes in simulation | Requires a fresh, visible owner track. Physical owner detection/re-identification is missing. |
| Central command arbitration and leases | Implemented | Wired | Yes in simulation/tests | Covers `RobotRuntime`, not direct debug/Dog IPC paths; software E-stop/watchdogs never replace hardware E-stop. |
| Unitree Sport closed-loop supervisor | Implemented | Explicit commissioning path only | Not hardware-verified | SDK absent, configured NIC absent, axes/frame uncommissioned, and `allowed_modes` intentionally empty. |
| Microphone capture + interruptible speaker output | Implemented | Conditional on healthy STT/TTS and devices | No: native PortAudio is missing and PipeWire endpoints are disconnected | `speech.mode: auto` therefore degrades to text. No hardware AEC is attached yet. |
| whisper.cpp STT | Implemented | Conditional | Binary/model installed; service not running at the snapshot | Start with `scripts/run_speech_services.sh` or the stack's `--whisper` option. |
| Piper TTS | Implemented | Configured default | Not installed at the configured paths | Binary, voice, and companion JSON are all required. |
| Fish S2 TTS | Implemented | Opt-in | Local isolated environment/weights exist | GPU-heavy and license-constrained; not the onboard default. |
| Semantic endpointing | Implemented with energy fallback | Selectable; canonical config chooses `energy` | ONNX Runtime and endpointing weights are absent | Energy VAD/hangover is the effective path today. |
| Speech-synchronized expression | Implemented | Wired when audio chunks play | Timing/tests only | `ProsodyTap` schedules epoch-scoped head-pitch nod state, but Go2 has no neck so the nod is not actuated/visible; idle body offsets do actuate in MuJoCo. |
| Latency dashboard | Implemented | Wired | Yes at `/latency` | Metrics describe observed software events, not physical actuation latency unless hardware feedback is present. |
| Google Maps | Placeholder | Disabled | No | It supplies no localization, route, or safety authority. |
| MetaUrban / learned navigation | Scaffolding and fail-closed registry entries | Not wired | No | Separate environment/adapters/weights are still required. |
| BARN/Habitat external evals | Experimental adapters and provenance records | Offline only | Partial smoke/proxy evidence | External scores are not product companion scores and cannot authorize deployment. |
| Relocatable Python wheel | Incomplete | Source-checkout/editable only | Not supported | `prompts/`, skill YAML, and navigation YAML are not package data; the packaged fallback config is divergent. |

## Configuration binding and inert keys

The audio keys in [`configs/robot.yaml`](../configs/robot.yaml) now live under
the `speech:` section read by the runtime. Device selectors (when uncommented),
`endpointing`, model paths, `echo_guard_scale`, and `fish_url` therefore reach
their consumers. The canonical selection remains `endpointing: energy` and
`tts_provider: piper`.

Three present keys are not currently consumed by provider/runtime construction:
`fish_reference_id`, `fish_streaming`, and `barge_in`. Barge-in is wired on
whenever the microphone loop exists, and the Fish adapter uses its implemented
request behavior rather than these switches. Treat them as reserved/inert until
code and configuration-contract tests explicitly bind them; their presence is
not a feature toggle.

## Desktop evidence

The application virtual environment contains MuJoCo, NumPy, PyYAML, the Python
`sounddevice` distribution, and the test/lint tooling. However, importing
`sounddevice` currently raises an `OSError` because the native
`libportaudio2` runtime is not installed. Separately, the desktop has a powered
Bluetooth controller and ALSA capture hardware, but no connected PipeWire input
or output endpoint. Parcel therefore reports text mode. `onnxruntime` is also
not installed in `.parcel`.

The speech readiness check currently reports:

- whisper.cpp binary and `base.en` model present, server not running;
- Piper binary missing;
- Piper voice missing; and
- Piper voice metadata missing.

The checked-in `parcel-panel` entry point exists in `pyproject.toml`, but the
current editable environment was installed before it was added and has no
`.parcel/bin/parcel-panel`. The verified launch scripts call
`python -m parcel_robot.web_panel` directly; use that module form or reinstall
the editable project to refresh console scripts.

Re-check instead of relying on this dated snapshot:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
source .parcel/bin/activate

python - <<'PY'
from parcel_robot.audio_io import detect_audio_devices
print(detect_audio_devices())
PY

./scripts/run_speech_services.sh --check
```

The second command is expected to exit nonzero until the missing services are
installed and whisper.cpp is running.

## Verification record

Run from the source checkout on 2026-08-04:

- `.parcel/bin/python -m pytest -q`: **1,426 passed, 2 skipped**; the two
  warnings exercise documented semantic-endpointing fallback paths.
- `.parcel/bin/python -m ruff check .`: **passed**.
- local Markdown link/path check across the root README and all docs: **passed**.
- `scripts/run_speech_services.sh --check`: **failed as expected** with the four
  speech-readiness blockers listed above.

These results prove regression health on this workstation, not physical Go2,
acoustic, or relocatable-package readiness.

## Safe working entry points

```bash
# Full text-first development stack: Gemma + MuJoCo + browser panel
./scripts/launch_stack.sh

# Deterministic command path, without a model service
./scripts/launch_stack.sh --no-reasoner

# Headless regression tests
source .parcel/bin/activate
.parcel/bin/python -m pytest -q
.parcel/bin/python -m ruff check .
```

Do not use `--fish` and assume that enables duplex capture: it only starts the
Fish service. Audio mode additionally needs a healthy STT, a TTS provider, real
input/output endpoints, correct `speech:` configuration, and AEC suitable for
barge-in.

## Packaging boundary

Run Parcel from this repository with an editable install. A relocatable wheel is
not supported today: `pyproject.toml` packages only the module config, scene,
and UI assets, while runtime behavior also needs repository-level `prompts/`,
`configs/skills/`, and `configs/navigation/`. The internal fallback
`src/parcel_robot/config/robot.yaml` has also drifted from the canonical config
(including a Fish default and missing current brain/expression settings).

Production packaging must include/version every runtime asset, remove the
silent divergent fallback, resolve paths relative to installed resources, and
test a clean wheel outside the source tree. Until then, successful editable
execution is not installation portability evidence.

## Claims this checkout deliberately does not make

- no physical Go2 commissioning or outdoor autonomy;
- no production owner recognition, localization, or camera perception;
- no physically validated expressive poses or speech/motion synchronization;
- no installed semantic endpointing runtime on this desktop;
- no authoritative Google Maps integration;
- no admitted learned navigation policy; and
- no top-decile claim across external benchmarks without their official
  protocol, assets, runtime, and recorded score.

Update this page whenever one of those boundaries changes. Evidence should name
the command, device/service, date, and failure semantics—not only the intended
architecture.
