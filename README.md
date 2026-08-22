# Parcel robot dog

A safety-gated development stack for an owner-following, voice-enabled Unitree
robot dog. The working local target is a **Go2** in MuJoCo with persistent
navigation, collision braking, owner-follow behavior, manual controls, local
open-weight reasoning, and a browser control deck. Engine-neutral backend and
ROS boundaries keep the same intent layer usable for richer simulators and a
later physical dog.

Start with the [engineering handbook](docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
for the executive design, current quality snapshot, robotics foundations,
tradeoffs, and roadmap. The [documentation index](docs/README.md) routes to
specialist designs and evidence, while [crucial design decisions](docs/DESIGN_DECISIONS.md)
records advantages, limitations, and revisit criteria. New learners can use the
[physics and robotics curricula](edu/INTRO.md) alongside the handbook.

> Current host note: this machine is Ubuntu 26.04 with Python 3.14 and does not
> currently have ROS 2 installed. Unitree documents Ubuntu 22.04 + ROS 2 Humble
> as its recommended ROS environment. The `.parcel` environment on this machine
> is fully set up for application development and MuJoCo, but native Unitree
> ROS 2 must be built in a supported Humble environment (host, VM, or container).

## Quick start

The production launcher now requires the hosted GPT Realtime lane and refuses
before starting anything if its local config or credential is absent. Create the
ignored local files once, then start the Realtime lane, Gemma reasoner, MuJoCo,
and browser panel together:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
install -m 600 /dev/null ~/.config/parcel/realtime.env
printf '%s\n' 'OPENAI_API_KEY=replace-me' > ~/.config/parcel/realtime.env
cp configs/realtime.yaml.example configs/realtime.yaml
./scripts/launch_stack.sh
```

Replace the placeholder key before launching. The example defaults to hosted
text mode; select `mode: audio` in the ignored local YAML to expose the browser
microphone gateway. To exercise the local STT/Gemma/TTS cascade deliberately,
use `./scripts/launch_stack.sh --legacy`; it is the rollback and E2E-test path,
not a silent fallback.

The panel opens at <http://127.0.0.1:8765>. The city now includes seeded moving
pedestrians and a cyclist. Try manual hold-to-drive controls, move the simulated
owner, then send `follow me`, `navigate to the crosswalk`, `I am feeling sad`,
or `I am very happy`. The hosted route sends only the final text submission to
`/api/realtime/text`; the explicit legacy route may send partial hypotheses to
`/api/voice/text`, but executes only its final submission. In hosted audio mode,
the browser supplies microphone capture and playback without requiring native
PortAudio in the Python process. Fish S2 and whisper.cpp remain optional parts
of the explicit legacy/local path. Piper and its selected voice are installed,
but that path still has no commissioned local microphone/speaker stream or AEC.

To visually inspect every bounded pose and gesture without starting the
reasoning or audio services, launch the simulator commissioning gallery:

```bash
./scripts/launch_pose_review.sh           # 3-second countdown, then run all
./scripts/launch_pose_review.sh --manual  # inspect and run motions individually
```

This opens the native MuJoCo window plus <http://127.0.0.1:8765/poses>. Watch
MuJoCo for articulated leg motion; the browser page provides Run, Run All,
Previous/Next, Stop, filtering, normalized 0–1 motion speed, dwell timing, and
neutral reset. Speed `1` is authored timing and `0` is the slowest bounded
playback; Stop is the cancellation control. The preview
API is enabled only by this launcher, accepts only catalogued poses and
trajectories, and refuses non-MuJoCo runtimes. By default the complete catalog
plays in canonical order after the countdown.

```bash
./scripts/launch_stack.sh --fish       # start Fish service only; does not select it
./scripts/launch_stack.sh --whisper    # local ASR service
```

Those flags only start and health-check their named services. They do not select
Fish as `speech.tts_provider`, change the configured Piper selection, or create
an audio device. The
duplex coordinator, mic loop, and speaker sink are already wired, but audio
becomes active only when STT + TTS + PortAudio + input/output endpoints are all
healthy. Reliable overlap additionally requires AEC. Run
`./scripts/run_speech_services.sh --check` for the current readiness report.

The read-only latency dashboard is at <http://127.0.0.1:8765/latency>. Bluetooth
hardware, AirPods profile tradeoffs, metric definitions, camera/LiDAR boundaries,
and bounded commands such as `walk away from the owner 5 steps` and `walk in a
circle around me` are documented in [Audio, latency, and spatial intelligence](docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

Architecture, model choices, audio-device findings, and limitations are in
[Voice-enabled development stack](docs/DEVELOPMENT_STACK.md).

**2026 redesign:** the full assessment, adjudicated decisions, and the
seven-layer portable architecture (registry-based vendor HAL, occlusion-true
raycast LiDAR feeding the grid planner as the production default, real
STT/TTS/VAD voice transport, live brain safety wiring, second-vendor
portability proof) are documented for the team in
[REDESIGN_2026_ASSESSMENT.md](docs/REDESIGN_2026_ASSESSMENT.md) and
[REDESIGN_2026_ARCHITECTURE.md](docs/REDESIGN_2026_ARCHITECTURE.md).
The city simulator has a live 2.5D viewer at <http://127.0.0.1:8765/viewer>,
and the companion-navigation integration eval lives in `evals/companion_nav/`.

## What is included

- A transcript-to-command agent with a safe, explicit command grammar.
- A Gemma/llama.cpp structured-tool adapter with deterministic validation.
- whisper.cpp recognition plus Piper and cancellable Fish S2 adapters (the
  Sesame CSM adapter is legacy and has no production caller).
- YAML-defined poses and Wi-Fi/network-card profiles.
- A single-writer, feedback-supervised locomotion manager with replaceable
  **Unitree Sport**, simulator, and future custom-controller implementations.
- A Python extension interface for custom sensors, behaviors, or hardware.
- ROS topics for transcript input, pose/walk requests, and spoken replies.
- MuJoCo owner/obstacle telemetry and a browser panel for driving and text voice.
- Central priority arbitration, command TTLs, proximity braking, and latched E-stop.
- Persistent owner-follow and point-navigation behavior loops.
- Bounded owner-relative steps and local circle trajectories with deterministic
  parsing, owner visibility checks, timeouts, and normal collision arbitration.
- Per-turn E2E/model/TTS traces plus rolling control-component latency metrics.
- Rotate-first, forward-preferred goal navigation with bounded lateral motion
  available for manual control, skills, recovery, and compatible planners.
- A deterministic living-city crowd with full dynamic-agent telemetry.
- Trusted personality/function prompt templates, bounded Gesture emotes, and a
  subordinate 50 Hz expression channel. Idle body offsets actuate in MuJoCo;
  beat-scheduled head nods are telemetry-only because Go2 has no neck.
- MuJoCo, Python audio bindings, linting, and test packages in `.parcel`;
  native PortAudio and real endpoints are still absent.

The first ROS boundary is intentionally simple:

| Topic | Type | Purpose |
| --- | --- | --- |
| `/parcel/transcript` | `std_msgs/String` | Speech-to-text result enters the agent |
| `/parcel/pose_request` | `std_msgs/String` | JSON pose intent sent to a controller |
| `/parcel/walk_request` | `std_msgs/String` | JSON body-frame velocity for locomotion |
| `/parcel/skill_request` | `std_msgs/String` | Named catalog skill request |
| `/parcel/voice_reply` | `std_msgs/String` | Reply for a text-to-speech node |
| `/parcel/stop_request` | `std_msgs/String` | High-priority stop intent |

Pose and walk requests are not sent directly to motors. A controller/bridge must
validate limits, implement an emergency stop, and translate the request into
Unitree commands or RL joint targets. Only one locomotion backend should be
active at a time—see [Motion backends](docs/MOTION.md).

The implemented Unitree Sport path subscribes to physical motion feedback,
expires stale commands, refreshes active velocity targets, and stops on stale
state or controller faults. It also requires a Unitree lease, commissioned
mode/frame/axis settings, and post-`StopMove` settled feedback. Physical
commissioning is explicit and bounded:

```bash
.parcel/bin/python -m parcel_robot.unitree_control --vx 0.05 --duration 1 --arm
```

This is a bounded standalone commissioning path, not the normal autonomous
composition. `RobotRuntime` still consumes simulator observations, and the
standard Unitree builder does not yet assemble synchronized physical-origin
pose, scan, people, and controller evidence. Follow the handbook's physical
composition and capability-admission sequence before interpreting the adapter
as an end-to-end robot runtime.

Read and follow [Closed-loop locomotion and Unitree Sport](docs/MOTION.md)
before connecting hardware. The Python supervisor and software E-stop are not
substitutes for an independent hardware E-stop. The Unitree Python SDK is not
installed on this workstation, and the configured placeholder NIC `enp3s0`
does not exist here, so the physical path has not been hardware-validated.

## Installed Python environment

Full host GPU / dependency inventory: [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).
Environment snapshot: [requirements-lock.txt](requirements-lock.txt). The
2026-08-22 audit found 17 distributions from the active environment missing from
that file, so it is not yet a complete reproducible lock.

The existing `.parcel` virtual environment is used for every pip package. It
currently contains the editable project plus:

- `mujoco`
- `numpy`
- `PyYAML`
- `msgpack`
- `sounddevice`
- `websockets`
- `pytest`
- `ruff`

The `sounddevice` Python distribution is present, but importing it currently
fails until the missing OS package `libportaudio2` is installed. Package
presence alone is not audio readiness.

Activate and verify it:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
source .parcel/bin/activate
python -c "import mujoco; print(mujoco.__version__)"
.parcel/bin/python -m pytest -q
.parcel/bin/python -m ruff check .
```

To bootstrap the declared project extras in a compatible environment (not to
reproduce the audited environment byte-for-byte):

```bash
python3 -m venv .parcel
touch .parcel/COLCON_IGNORE
source .parcel/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,voice]"
```

`COLCON_IGNORE` prevents colcon from searching the virtual environment.
Development normally uses a source checkout/editable install. The curated
runtime config, prompt, skill, and navigation assets are now package-parity
gated; third-party MuJoCo meshes remain source-checkout assets. See the dated
release-integrity records linked from the [documentation index](docs/README.md).

## Skills catalog, city scene, and Dog API

See [Skills / city / RL implementation](docs/IMPLEMENTATION_SKILLS_CITY_RL.md).

Hierarchical companion navigation (PlanIR → grid_v1 → safety → ControlManager),
product eval policy, and the offline BARN/Habitat research boundary are in
[Companion navigation architecture](docs/COMPANION_NAVIGATION_ARCHITECTURE.md).
The redesign rationale and seven-layer map are in
[REDESIGN_2026_ASSESSMENT.md](docs/REDESIGN_2026_ASSESSMENT.md) and
[REDESIGN_2026_ARCHITECTURE.md](docs/REDESIGN_2026_ARCHITECTURE.md).
Doc index: [docs/README.md](docs/README.md).

The frozen live semantic-planning gate and its append-only run history are in
[planner quality v2](evals/companion/planner_quality_v2/README.md) and its
[result ledger](evals/companion/planner_quality_v2/results/README.md). The
admitted CPU and full-CUDA baselines both passed 5/5 selected semantic cases;
the GPU run reduced median usable-plan latency to 5.657 seconds but executed
zero physical episodes. The separate headless embodied PlanIR gate passed 4/4
supported cases with zero collisions while explicitly leaving moving-owner
follow unsupported. Neither result is a conversation or official benchmark
score.
The separate frozen conversation calibration records Gemma at 6/10 machine
cases and 9/10 structured-safety checks; human review is still absent. A fully
GPU-admitted Ministral 3 8B Instruct challenger started much faster but
regressed to 5/10 conversation cases and 3/5 PlanIR, so it remains
deployment-disabled. Exact artifacts live in the companion eval ledgers.
Product companion scenarios: `evals/companion_nav/`. Offline BARN/Habitat
proxies: [evals/external/README.md](evals/external/README.md).

```bash
source .parcel/bin/activate
# Public API
python - <<'PY'
from parcel_robot.skills import Dog
dog = Dog.from_config("configs/robot.yaml")
print(len(dog.list_skills()), "skills")
print(dog.execute("jump"))
PY

# City sim + browser control deck
./scripts/launch_sim.sh

# RL env smoke (no display)
python examples/rl_env_smoke.py

# City navigation (POI grounding + stub pedestrians / social reward)
python examples/nav_city_smoke.py

# Deterministic city-task outcome gate (no viewer)
python -m pytest -q tests/test_headless_city_tasks.py tests/test_mujoco_lidar.py \
  tests/test_city_orbit_clearance.py
```

City navigation, dynamic simulator research, action policy, open-weight model
registry, and MetaUrban setup:
see [City navigation](docs/NAVIGATION_CITY.md).
See also [Dynamic city and behavior architecture](docs/DYNAMIC_CITY_AND_BEHAVIOR.md).

```bash
# On a Conda Python 3.9 + GPU host (not this Python 3.14 venv):
./scripts/setup_metaurban.sh

# active_model: grid_v1 is the production default: the occupancy-grid A*
# planner consumes the occlusion-true raycast LiDAR scan and degrades loudly
# (scan_missing_fallback) to the point-goal stub if the scan is absent.

python - <<'PY'
from parcel_robot.skills import Dog
dog = Dog.from_config("configs/robot.yaml")
dog.set_nav_pose((0, 0, 0), 0)
mission, cmd = dog.navigate("I want you to go to the coffee shop at 42nd street")
print(mission.goal, cmd)
PY
```

```bash
source .parcel/bin/activate
parcel-agent --text "do the sit pose"
parcel-agent --text "walk forward"
parcel-agent --text "use sport backend"
parcel-agent --text "status"
```

Local MuJoCo pose/walk preview:

```bash
./scripts/launch_sim.sh
```

That starts `parcel-sim` and the `parcel-panel` browser UI together. Or run them
separately:

```bash
# terminal 1
python -m parcel_robot.sim

# terminal 2 — browser panel
python -m parcel_robot.web_panel --llm
```

The current editable environment predates the `parcel-panel` console-script
entry point, so the module form above is the verified command; reinstalling
`-e ".[dev,voice]"` regenerates entry points. `language_model` remains the
shared conversation/PlanIR default. To run a
separately evaluated planning specialist, configure and enable the optional
`planner_model` section on a different local endpoint. The browser runtime sends
the original transcript directly to that lane, reports conversation/planner
health independently, and attributes plan latency to the provider that served
it. `parcel-panel --no-llm` disables both lanes. A specialist section is
intentionally absent from the frozen default robot configuration because the
measured Ministral challengers did not beat the Gemma quality gates; add
`planner_model` only to an experimental deployment configuration.

```yaml
planner_model:
  enabled: true
  base_url: http://127.0.0.1:8082
  model: an-admitted-planner
  streaming: true
  plan_timeout: 90
  plan_max_tokens: 1024
```

Or focus the MuJoCo window and use keys: `W/S` forward/back, `A/D` strafe,
`Q/E` turn, `Space` stop, `1` sit, `2` bow.

You can still drive it from the agent:

```bash
parcel-agent --sim --text "do the sit pose"
parcel-agent --sim --text "walk forward"
```

The viewer hotkeys and direct `parcel-agent --sim` commands are debugging paths.
They use simulator-side limits, watchdog, and E-stop latch, but bypass
`RobotRuntime` priority arbitration and its owner/obstacle telemetry gate. Use
the browser control deck for end-to-end safety and behavior development.

With a local `llama-server` running and configured in `robot.yaml`:

```bash
parcel-agent --llm --text "Could you do the bow pose?"
```

This is useful for developing command parsing and modules before the native ROS
and Unitree stacks are available.

## ROS 2 and Unitree MuJoCo setup

Use Ubuntu 22.04 and ROS 2 Humble for the path Unitree recommends. ROS itself,
CycloneDDS, compilers, and graphics libraries are operating-system packages;
they cannot be installed into a Python virtual environment. In the supported
environment, install ROS 2 Humble Desktop using the official ROS instructions,
then install the Unitree ROS dependencies:

```bash
sudo apt update
sudo apt install ros-humble-desktop ros-humble-rmw-cyclonedds-cpp \
  ros-humble-rosidl-generator-dds-idl ros-dev-tools git cmake build-essential \
  libportaudio2
source /opt/ros/humble/setup.bash
```

`libportaudio2` is the native runtime used by the `.parcel` `sounddevice`
package. On the current machine it still needs to be installed by an
administrator because `sudo` requires an interactive password.

Clone and build the two official Unitree projects next to this repository:

```bash
mkdir -p "$HOME/unitree"
cd "$HOME/unitree"
git clone https://github.com/unitreerobotics/unitree_ros2.git
git clone https://github.com/unitreerobotics/unitree_mujoco.git

cd unitree_ros2/cyclonedds_ws
colcon build
cd ../example
colcon build
```

Build `unitree_mujoco` by following its C++ build section. It uses the official
MuJoCo archive and Unitree SDK2, rather than the pip MuJoCo binding used by this
application. Once built, start a Go2 simulation:

```bash
cd "$HOME/unitree/unitree_mujoco/simulate/build"
./unitree_mujoco -r go2 -s scene_terrain.xml
```

In a second terminal, configure Unitree ROS for loopback and simulation domain
1, then start Parcel:

```bash
source /opt/ros/humble/setup.bash
source "$HOME/unitree/unitree_ros2/setup_local.sh"
export ROS_DOMAIN_ID=1
cd /home/jaewoo-jang/Desktop/Projects/Parcel
source .parcel/bin/activate
parcel-agent --ros --config configs/robot.yaml
```

The virtual environment must be created with the same system Python used by the
selected ROS distribution. Do not copy the current Python 3.14 `.parcel` into a
Humble machine; recreate it there (Humble on Ubuntu 22.04 uses Python 3.10).

Send a simulated transcript:

```bash
ros2 topic pub --once /parcel/transcript std_msgs/msg/String \
  "{data: 'do the bow pose'}"
ros2 topic echo /parcel/pose_request
ros2 topic echo /parcel/voice_reply
```

The next integration step is a controller-owned whole-body action adapter that
subscribes to `/parcel/pose_request`, first confirms locomotion has stopped, and
then performs the pose. Never publish Unitree `LowCmd` while the onboard Sport
service is active. Develop a low-level replacement only in isolated simulation;
the official Unitree MuJoCo settings use loopback `lo` and DDS domain `1`.

## Add a custom pose

Create `configs/skills/poses/wave.yaml`:

```yaml
id: wave
name: Wave
kind: pose
enabled: true
tags: [pose, social]
duration: 1.5
joints:
  FL_hip_joint: 0.0
  FL_thigh_joint: 0.4
  FL_calf_joint: -0.8
  # Include and validate all joints expected by the target controller.
```

Add `wave` to `configs/skills/catalog.yaml`, restart the runtime, then say or
publish `do the wave pose`. The catalog parser does not establish physical
stability or joint safety; tune and validate the complete pose in simulation
and through a commissioned whole-body controller before hardware use.

The inline `poses:` mapping in `configs/robot.yaml` is retained only as a legacy
compatibility shim. New skills belong under `configs/skills/`.

## Add Wi-Fi/network cards

Profiles live under `wifi_cards` in `robot.yaml`:

```yaml
wifi_cards:
  simulator:
    interface: lo
    ros_domain_id: 1
    purpose: simulation
  robot:
    interface: enp3s0
    ros_domain_id: 0
    purpose: physical_robot
```

Replace `enp3s0` with the interface shown by `ip link`. A profile records the
correct interface/domain pairing; switching the OS network or Unitree DDS setup
remains an explicit operator action.

## Add a custom module

Create a class with `commands()` and `handle()` methods:

```python
class CameraModule:
    def __init__(self, config):
        self.device = config.get("device", "/dev/video0")

    def commands(self):
        return {"photo"}

    def handle(self, command, argument):
        if command == "photo":
            # Trigger the camera here.
            return "Photo captured"
        return None
```

Register its import path in `robot.yaml`:

```yaml
modules:
  - name: camera
    class: my_robot_modules.CameraModule
    enabled: true
    config:
      device: /dev/video0
```

## Voice pipeline

The browser runtime accepts partial and final text at `/api/voice/text`; partials
can interrupt output but never execute actions. The application also has a
direct `MicrophoneVoiceLoop` → STT → committed text path and an interruptible
`SpeakerSink`, so external ROS audio nodes are optional rather than required.
Keeping audio providers behind text/PCM contracts prevents their failures from
becoming motor authority. A ROS deployment may still isolate microphone/STT and
reply/TTS in separate nodes.

Before physical deployment, add authenticated remote commands, hardware AEC, an
independent hardware emergency stop, command timeouts, joint/velocity/torque
limits, and a watchdog that returns the robot to a stable state.

The implemented adapters are:

- `WhisperCppProvider`: WAV audio to whisper.cpp `/inference`
- `LlamaCppProvider`: transcript to strict Gemma JSON/tool calls
- `SafetySupervisor`: allowlist and pose-limit validation
- `PiperSpeechProvider`: installed/configured on-device TTS target; binary,
  voice, and 22.05 kHz metadata pass the readiness check
- `FishSpeechProvider`: local Fish S2 request adapter (opt-in docked mode); the
  current sentence wrapper does not expose Fish's native audio chunk stream
- `SentenceChunkedSynthesizer`: any blocking TTS becomes a cancellable stream
- `DuplexVoiceSession`: partial/final text, stale-turn suppression, and barge-in
- `MicrophoneVoiceLoop` / `SpeakerSink` (`voice_audio.py`): VAD-segmented
  capture, acoustic barge-in behind an echo guard, interruptible playback
- `SileroVad` / `TurnEndpointer`: selected semantic endpointing with loud energy
  fallback; ONNX Runtime and the Silero/Smart Turn weights are present
- `ProsodyTap` / `ExpressionEngine`: pre-playback accents, idle body offsets,
  and epoch-scoped timing-only Go2 nod metrics
- `VoicePipeline`: composes a single STT/reasoning/TTS utterance

See [Voice intelligence and model design](docs/VOICE_AI_MODELS.md) for model
selection, deployment commands, trust boundaries, privacy, and latency targets.

## Project layout

```text
src/parcel_robot/
├── agent.py             # transcript routing, deterministic safety grammar
├── brain/               # typed PlanIR, validator, executive, runtime adapter
├── control/             # controller HAL, single-writer manager, Unitree Sport
├── navigation/          # semantic grounding, follow/spatial, grid + safety
├── realtime/            # hosted lane, transport, restricted tools, evidence/spend
├── camera_channel/      # calibrated frame contracts and optional async ingress
├── detection_adapter/   # detector, localization, tracking and noise adapters
├── online_map/          # in-flight robot-written semantic map (not product-wired)
├── perception_source/   # in-flight oracle/map/shadow policy (partial integration)
├── patrol/              # standalone in-flight patrol/evaluation driver
├── skills/              # catalog, schema, executor, public Dog API
├── backends/            # replaceable simulator transport boundary
├── runtime.py           # arbitration, behavior loops, telemetry, final safety gate
├── voice_audio.py       # device capture, endpointing integration, playback
├── voice_pipeline.py    # text-first duplex voice coordination
├── endpointing.py       # optional Silero / semantic turn completion
├── prosody.py           # pre-playback accent/arousal analysis
├── expression.py        # subordinate idle/reaction/beat motion channel
├── sim.py               # MuJoCo city/owner/obstacle simulation
├── web_panel.py         # local HTTP API and browser control deck
└── ros_node.py          # optional ROS topic boundary
configs/                 # canonical runtime, navigation, and skill configuration
prompts/                 # trusted system/personality/function/schema templates
evals/                   # product gates and isolated external proxies
tests/                   # non-ROS regression suite
docs/README.md           # documentation index
```

Official references:

- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2)
- [ROS 2 Python virtual environments](https://docs.ros.org/en/jazzy/How-To-Guides/Using-Python-Packages.html)
