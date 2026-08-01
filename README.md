# Parcel robot dog

An extensible starting point for a voice-controlled Unitree robot dog. The first
target is a **Go2** in Unitree's MuJoCo simulator, connected through **ROS 2**.
The application keeps voice, poses, network selection, and optional hardware
modules separate so the same intent layer can later run against a physical dog.

> Current host note: this machine is Ubuntu 26.04 with Python 3.14 and does not
> currently have ROS 2 installed. Unitree documents Ubuntu 22.04 + ROS 2 Humble
> as its recommended ROS environment. The `.parcel` environment on this machine
> is fully set up for application development and MuJoCo, but native Unitree
> ROS 2 must be built in a supported Humble environment (host, VM, or container).

## What is included

- A transcript-to-command agent with a safe, explicit command grammar.
- A Gemma/llama.cpp structured-tool adapter with deterministic validation.
- whisper.cpp speech recognition and isolated Sesame CSM-1B client adapters.
- YAML-defined poses and Wi-Fi/network-card profiles.
- A Python extension interface for custom sensors, behaviors, or hardware.
- ROS topics for transcript input, pose requests, and spoken replies.
- MuJoCo, audio capture, linting, and test packages installed in `.parcel`.

The first ROS boundary is intentionally simple:

| Topic | Type | Purpose |
| --- | --- | --- |
| `/parcel/transcript` | `std_msgs/String` | Speech-to-text result enters the agent |
| `/parcel/pose_request` | `std_msgs/String` | JSON pose intent sent to a controller |
| `/parcel/voice_reply` | `std_msgs/String` | Reply for a text-to-speech node |
| `/parcel/stop_request` | `std_msgs/String` | High-priority stop intent |

Pose requests are not sent directly to motors. A controller/bridge must validate
joint limits, interpolate the trajectory, implement an emergency stop, and then
translate the request into Unitree low-level commands.

## Installed Python environment

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
cd /home/jaewoo-jang/Desktop/parcel
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

## Try the agent without ROS

```bash
source .parcel/bin/activate
parcel-agent --text "do the sit pose"
parcel-agent --text "status"
```

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
cd /home/jaewoo-jang/Desktop/parcel
source .parcel/bin/activate
parcel-agent --ros --config src/parcel_robot/config/robot.yaml
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

Edit [`src/parcel_robot/config/robot.yaml`](src/parcel_robot/config/robot.yaml):

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

The core accepts finalized transcripts and emits reply text, so speech providers
are replaceable. Add two ROS nodes:

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
- `CsmSpeechProvider`: reply text to an isolated CSM WAV service
- `VoicePipeline`: composes one complete utterance

See [Voice intelligence and model design](docs/VOICE_AI_MODELS.md) for model
selection, deployment commands, trust boundaries, privacy, and latency targets.

## Project layout

```text
src/parcel_robot/
├── agent.py          # transcript command routing
├── config.py         # YAML loaders and dynamic modules
├── config/robot.yaml # poses, cards, and modules
├── modules.py        # extension protocol and example
└── ros_node.py       # ROS topic boundary
tests/                # non-ROS unit tests
```

Official references:

- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2)
- [ROS 2 Python virtual environments](https://docs.ros.org/en/jazzy/How-To-Guides/Using-Python-Packages.html)
