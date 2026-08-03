# Parcel robot dog

A safety-gated development stack for an owner-following, voice-enabled Unitree
robot dog. The working local target is a **Go2** in MuJoCo with persistent
navigation, collision braking, owner-follow behavior, manual controls, local
open-weight reasoning, and a browser control deck. Engine-neutral backend and
ROS boundaries keep the same intent layer usable for richer simulators and a
later physical dog.

> Current host note: this machine is Ubuntu 26.04 with Python 3.14 and does not
> currently have ROS 2 installed. Unitree documents Ubuntu 22.04 + ROS 2 Humble
> as its recommended ROS environment. The `.parcel` environment on this machine
> is fully set up for application development and MuJoCo, but native Unitree
> ROS 2 must be built in a supported Humble environment (host, VM, or container).

## Quick start

The models and native servers are installed in ignored local directories. Start
the CPU Gemma reasoner, MuJoCo window, and browser panel together:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
./scripts/launch_stack.sh
```

The panel opens at <http://127.0.0.1:8765>. The city now includes seeded moving
pedestrians and a cyclist. Try manual hold-to-drive controls, move the simulated
owner, then send `follow me`, `navigate to the crosswalk`, `I am feeling sad`,
or `I am very happy`. The text box streams partial hypotheses to `/api/voice/text` but
executes only the final submission. Fish S2 and whisper.cpp servers are optional
while this desktop has no connected microphone/speaker endpoint:

```bash
./scripts/launch_stack.sh --fish       # GPU TTS; review Fish's model license
./scripts/launch_stack.sh --whisper    # local ASR service
```

Those flags start and health-check the isolated speech services; they do not
enable browser microphone capture or playback. Connecting them to the running
duplex coordinator is the next device-transport step after adding a real audio
endpoint and acoustic echo cancellation.

The read-only latency dashboard is at <http://127.0.0.1:8765/latency>. Bluetooth
hardware, AirPods profile tradeoffs, metric definitions, camera/LiDAR boundaries,
and bounded commands such as `walk away from the owner 5 steps` and `walk in a
circle around me` are documented in [Audio, latency, and spatial intelligence](docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

Architecture, model choices, audio-device findings, and limitations are in
[Voice-enabled development stack](docs/DEVELOPMENT_STACK.md).

## What is included

- A transcript-to-command agent with a safe, explicit command grammar.
- A Gemma/llama.cpp structured-tool adapter with deterministic validation.
- whisper.cpp recognition plus cancellable Fish S2 and Sesame CSM adapters.
- YAML-defined poses and Wi-Fi/network-card profiles.
- A motion router with exclusive **Sport Move** and **RL locomotion** backends.
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
- Trusted personality/function prompt templates and deferred social gestures.
- MuJoCo, audio capture, linting, and test packages installed in `.parcel`.

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

## Installed Python environment

Full host GPU / dependency inventory: [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).
Locked pip freeze: [requirements-lock.txt](requirements-lock.txt).

The existing `.parcel` virtual environment is used for every pip package. It
currently contains the editable project plus:

- `mujoco`
- `numpy`
- `PyYAML`
- `sounddevice`
- `pytest`
- `ruff`

Activate and verify it:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
source .parcel/bin/activate
python -c "import mujoco; print(mujoco.__version__)"
pytest
ruff check .
```

To reproduce the Python install in a compatible environment:

```bash
python3 -m venv .parcel
touch .parcel/COLCON_IGNORE
source .parcel/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,voice]"
```

`COLCON_IGNORE` prevents colcon from searching the virtual environment.

## Skills catalog, city scene, and Dog API

See [Skills / city / RL implementation](docs/IMPLEMENTATION_SKILLS_CITY_RL.md).

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
```

City navigation, dynamic simulator research, action policy, open-weight model
registry, and MetaUrban setup:
see [City navigation](docs/NAVIGATION_CITY.md).
See also [Dynamic city and behavior architecture](docs/DYNAMIC_CITY_AND_BEHAVIOR.md).

```bash
# On a Conda Python 3.9 + GPU host (not this Python 3.14 venv):
./scripts/setup_metaurban.sh

# Keep active_model: stub_v0 for the implemented adapter. The other registry
# entries are research metadata and fail closed until vendor inference is wired.

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
parcel-sim

# terminal 2 — browser panel
parcel-panel --llm
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

The next integration step is a `pose_controller` node that subscribes to
`/parcel/pose_request` and publishes Unitree `LowCmd` messages. Begin with the
official `stand_go2` ROS 2 example and keep its simulation settings:
loopback interface `lo` and `ROS_DOMAIN_ID=1`.

## Add a custom pose

Edit the canonical [`configs/robot.yaml`](configs/robot.yaml):

```yaml
poses:
  wave:
    duration: 1.5
    joints:
      FL_hip_joint: 0.0
      FL_thigh_joint: 0.4
      FL_calf_joint: -0.8
      # Include all joints expected by your controller.
```

Then say or publish `do the wave pose`. The included sit and bow values are
development placeholders; tune and validate them in simulation before use.

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
can interrupt output but never execute actions. It emits reply text, so speech
providers remain replaceable. Add two ROS nodes for physical audio:

1. microphone + voice activity detection + speech-to-text → `/parcel/transcript`
2. `/parcel/voice_reply` → text-to-speech + speaker

Keeping those nodes separate prevents microphone or cloud failures from touching
motor control. Before physical deployment, also add authentication for remote
commands, a hardware emergency stop, command timeouts, joint/velocity/torque
limits, and a watchdog that returns the robot to a stable state.

The implemented adapters are:

- `WhisperCppProvider`: WAV audio to whisper.cpp `/inference`
- `LlamaCppProvider`: transcript to strict Gemma JSON/tool calls
- `SafetySupervisor`: allowlist and pose-limit validation
- `FishSpeechProvider`: local Fish S2 MessagePack/WAV streaming with cancellation
- `DuplexVoiceSession`: partial/final text, stale-turn suppression, and barge-in
- `CsmSpeechProvider`: optional legacy Sesame CSM WAV adapter
- `VoicePipeline`: composes a single STT/reasoning/TTS utterance

See [Voice intelligence and model design](docs/VOICE_AI_MODELS.md) for model
selection, deployment commands, trust boundaries, privacy, and latency targets.

## Project layout

```text
src/parcel_robot/
├── agent.py          # transcript command routing
├── runtime.py        # arbitration, behavior loops, telemetry, final safety gate
├── backends/         # replaceable simulator / robot transport boundary
├── config.py         # YAML loaders and dynamic modules
├── motion.py         # Sport Move + RL locomotion router
├── modules.py        # extension protocol and example
├── sim.py            # MuJoCo city/owner/obstacle simulation
├── web_panel.py      # local HTTP API and browser control deck
├── voice_pipeline.py # text-first duplex voice coordination
└── ros_node.py       # ROS topic boundary
tests/                # non-ROS unit tests
docs/MOTION.md        # Sport vs RL setup guide
configs/robot.yaml    # canonical runtime configuration
```

Official references:

- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2)
- [ROS 2 Python virtual environments](https://docs.ros.org/en/jazzy/How-To-Guides/Using-Python-Packages.html)
