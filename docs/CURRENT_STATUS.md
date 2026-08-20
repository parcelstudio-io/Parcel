# Current implementation status

**Historical snapshot:** 2026-08-04. This page records the operational truth as
of that date; it is not the authority for the current checkout. Use the
[documentation index](README.md), current code and executable evidence for
later claims. The terms and capability distinctions below remain useful when
reading this historical record.

**2026-08-09 navigation audit correction:** the environmental proximity/TTC
gate is shared across motion sources, but it precedes the final S-curve shaper.
That shaper's emergency branch decelerates toward zero rather than guaranteeing
an exact-zero final command on the veto tick. Explicit E-stop/manager-stop paths
remain stronger. A typed post-shaper exact-zero disposition is now P0 work; do
not treat the present ordering as physically commissioned safety behavior.

Status terms used throughout the documentation:

- **Implemented** — runtime code and tests exist; this does not imply physical
  production readiness.
- **Wired** — the default runtime reaches that code path.
- **Verified** — repeatable command/test/eval evidence exists for the named
  scope; it does not automatically include a service, device, or physical robot.
- **Operational** — its required local service or device was verified on this
  desktop.
- **Commissioned** — verified on the intended physical hardware/environment
  with its frames, modes, safety envelope, and failure behavior checked.
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
| `grid_v1` navigation | Implemented | Wired and selected | Yes in headless/MuJoCo gates | Rolling 2-D occupancy, A*, forward-preferred tracking, and a shared reactive safety gate; missing/stale required LiDAR can still fall back to point-goal translation, so this is not a physical fail-closed navigation claim. |
| Semantic sidewalk/object goals | Implemented | Wired in the simulated city | In-view/known-target headless tests; the 2026-08-09 search-required audit was 0% | Semantic candidates currently come from simulator observations. Active search/re-ground can miss an object that enters the frustum, and a physical camera/LiDAR perception stack is not implemented. |
| Owner following and owner-relative motion | Implemented | Wired | Yes in simulation | Requires a fresh simulator owner track. The Kalman prediction path is enabled, but the measured direct-follow turn case showed no benefit because the owner-clearance clamp leaves only 0.05 m of lead. Physical owner detection/re-identification is missing. |
| Dynamic-agent planning + predictive TTC gate | Implemented | Wired in `grid_v1`/runtime | Unit/integration and companion-scenario evidence | The planner leaves a predicted pedestrian corridor and the gate engages, but current track-count normalization is non-monotone, schemas omit age/covariance, and socially correct passing-side selection has not been demonstrated. |
| Jerk-limited command shaping | Implemented | Wired after arbitration/environmental safety and before `ControlManager` | Partial-dispatch companion eval | Mean commanded jerk fell 0.9592→0.5530 m/s³ across 11 simulated episodes with no collision regression. That replica stops before `ControlManager`/HAL; calm-profile and physical-motion benefits are unverified. Explicit stop/E-stop paths reset shaping, but the ordinary environmental veto's emergency shaping is bounded deceleration, not an exact-zero post-shaper assertion. |
| `SearchOwner` reacquisition | Implemented system-authored skill | Wired after follow loss | Phase/unit coverage; the earlier scenario searched then gave up | It goes to the last observation, sweeps, and explores frontiers under a 45 s budget. Mobile phases are now planner-backed, but that update has not been rerun to a finite reacquisition; it also maintains a search-local occupancy grid. It is deliberately not model-callable. |
| Task/channel pause and resume foundations | Implemented | Pause path wired; automatic semantic resume is incomplete | Unit/composition tests | `resume_task()` can requeue, but NavigateTo redispatch does not consume its stored `ResumeIntent`/call `resume_navigation`; `requires_fresh_observation` is metadata only. Search→follow still resumes through a legacy tuple rather than the stored follow intent. |
| Stimulus/attention reaction arbiter | Implemented as pure modules | **Not wired** into the control loop | Unit tests only | The mic/prosody path does not feed `StimulusBus`; `ReactionArbiter` is not ticked. Existing expression reactions are a separate path. |
| Central command arbitration and leases | Implemented | Wired | Yes in simulation/tests | Covers `RobotRuntime`, not direct debug/Dog IPC paths; software E-stop/watchdogs never replace hardware E-stop. |
| Unitree Sport closed-loop supervisor | Implemented | Explicit commissioning path only | Not hardware-verified | SDK absent, configured NIC absent, axes/frame uncommissioned, and `allowed_modes` intentionally empty. |
| Microphone capture + interruptible speaker output | Implemented | Conditional on healthy STT/TTS and devices | No: native PortAudio is missing and PipeWire endpoints are disconnected | `speech.mode: auto` therefore degrades to text. No hardware AEC is attached yet. |
| whisper.cpp STT | Implemented | Conditional | Binary/model installed; service not running at the snapshot | Start with `scripts/run_speech_services.sh` or the stack's `--whisper` option. |
| Piper TTS | Implemented | Configured default | Not installed at the configured paths | Binary, voice, and companion JSON are all required. |
| Fish S2 TTS | Implemented | Opt-in | Local isolated environment/weights exist | GPU-heavy and license-constrained; not the onboard default. |
| Semantic endpointing | Implemented with energy fallback | Selectable; canonical config chooses `energy` | ONNX Runtime and endpointing weights are absent | Energy VAD/hangover is the effective path today. |
| Speech-synchronized expression | Implemented | Wired when audio chunks play | Timing/tests only | `ProsodyTap` schedules epoch-scoped head-pitch nod state, but Go2 has no neck so the nod is not actuated/visible; idle body offsets do actuate in MuJoCo. |
| Emotion poses and self-returning gestures | Implemented | Catalogued; personality affect maps can queue gestures, explicit aliases use the reviewed command path, and short-lived conversation reactions skip a busy body | Catalog/package/prompt/router/coordinator tests; simulator only | Adds whole-body Go2 proxies for `head_nod`, `head_shake`, `chuckle`, `shrug`, `confused_head_tilt`, and `observing_head_tilt`. Go2 has no neck, `chuckle` has no audio by itself, and every custom clip remains hardware-unverified. The physical runtime rejects direct pose/trajectory writes while Sport owns locomotion. |
| Latency dashboard | Implemented | Wired | Yes at `/latency` | Metrics describe observed software events, not physical actuation latency unless hardware feedback is present. |
| D0 aligned TEXT+ACT stream | Implemented | One frame per nominal 10 Hz control-loop tick; consumer is shadow-only | Unit/scripted-text eval paths | Frames are composed from reply text entering the delivery path and behavior already selected by existing code. Index/epoch continuity is tested, but wall-clock deadline misses are not detectable; neither a trained model nor the frame consumer chooses or drives motion. D1 does not exist. |
| Predictive/watchdog fillers | Implemented | Wired for slow routes and ~700 ms watchdog | Fake-TTS/scripted clocks only | The metric waits for the TTS/audible handoff, but no filler has been heard through real Piper or an audio device. The 2 s ceiling is therefore not acoustically validated. |
| D0 duplex corpus logging | Implemented, enabled by canonical config | Local rotating JSONL under `logs/duplex/` | Writer tests only | Logs contain reply-derived TEXT plus owner/context values and outcomes (not the user transcript today). Git ignore and `duplex.logging: false` exist, but the <2 MB/hour design budget, retention, and long-session privacy behavior are unverified. |
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

All keys in the canonical `speech:` section are now bound: `fish_reference_id`
is passed to `FishSpeechProvider`. `fish_streaming` and `barge_in` appear only
in the divergent packaged fallback config; current speech-config validation
rejects them as unknown rather than treating them as switches. Barge-in is
wired on whenever the microphone loop exists. Remove or migrate those two
legacy fallback keys before relying on packaged startup.

[`configs/personality.yaml`](../configs/personality.yaml) (2026-08-08) is a
**bound, not inert** surface: it carries the per-personality blocked-by-a-person
yield policy and its utterance templates, and every key reaches the runtime's
`_step_navigation` seam. It is a separate file because `configs/robot.yaml` is
hash-locked by `evals/companion/embodied_plan_v1`. Loading is fail-closed on
unknown keys; a tree that ships no such file gets the documented built-in
defaults and reports `source="builtin"`. See
[YIELD_POLICY.md](YIELD_POLICY.md).

## Desktop evidence

The application virtual environment contains MuJoCo, NumPy, PyYAML, the Python
`sounddevice` distribution, and the test/lint tooling. However, importing
`sounddevice` currently raises an `OSError` because the native
`libportaudio2` runtime is not installed. Separately, the desktop has a powered
Bluetooth controller and ALSA capture hardware, but PipeWire exposes only a
dummy output and no source. No USB audio array appears in the current `lsusb`
inventory. Parcel therefore reports text mode. `onnxruntime` is also not
installed in `.parcel`.

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

- `.parcel/bin/python -m pytest -q`: **1,655 passed, 6 skipped**, with two
  expected warnings exercising documented semantic-endpointing fallback paths.
- `.parcel/bin/python -m ruff check .`: **passed**.
- local Markdown link/path check across the root README and 21 docs (22 files):
  **passed**.
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
(including a Fish default, an older brain skill contract, and no current
duplex/expression/navigation-shaping sections). Its legacy `fish_streaming` and
`barge_in` keys are rejected by current speech-config validation, so fallback
startup can fail before later asset-path problems are reached.

Production packaging must include/version every runtime asset, remove the
silent divergent fallback, resolve paths relative to installed resources, and
test a clean wheel outside the source tree. Until then, successful editable
execution is not installation portability evidence.

## Claims this checkout deliberately does not make

- no physical Go2 commissioning or outdoor autonomy;
- no production owner recognition, localization, or camera perception;
- no physically validated expressive poses or speech/motion synchronization;
- no acoustically validated filler or D0 duplex latency;
- no model-generated ACT stream or live ACT-token actuator authority;
- no demonstrated successful `SearchOwner` reacquisition or direct-follow
  prediction improvement;
- no control-loop wiring for the pure attention-reaction modules;
- no installed semantic endpointing runtime on this desktop;
- no authoritative Google Maps integration;
- no admitted learned navigation policy; and
- no top-decile claim across external benchmarks without their official
  protocol, assets, runtime, and recorded score.

Update this page whenever one of those boundaries changes. Evidence should name
the command, device/service, date, and failure semantics—not only the intended
architecture.
