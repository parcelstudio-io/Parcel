# Parcel robot dog

A safety-gated, simulation-first autonomy stack for a conversational Unitree
companion dog. The working simulator target is a **Go2** in MuJoCo with manual
motion, persistent navigation and owner-follow implementations, collision
braking, hosted and local reasoning lanes, and a browser control deck. The
current normal builder does not yet provision the new capability manifest, so
automatic embodied and navigation actions fail closed. Engine-neutral backend
and ROS boundaries keep the same intent layer usable for richer simulators and
a later physical dog.

Use the dated status section below for the current working-tree verdict. The
[engineering executive summary](docs/ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md)
provides the broader decision, hardware-readiness judgment, tradeoffs, and next
gates, but its recorded gate snapshot predates the latest audit. For the shortest
as-built call-path view, use the
[production-shaped runtime code map](docs/PRODUCTION_RUNTIME_CODE_MAP.md). The concise
[robotics code design](docs/ROBOTICS_CODE_DESIGN.md) explains package/process
boundaries, the feedback and authority model, failure behavior, and accepted
tradeoffs. Continue into the
[engineering handbook](docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md) for
long-form architecture and robotics theory; its older status passages are historical.
The [documentation index](docs/README.md)
routes to specialist designs and evidence, while [crucial design decisions](docs/DESIGN_DECISIONS.md)
records advantages, limitations, and revisit criteria. New learners can use the
[physics and robotics curricula](edu/INTRO.md) alongside the handbook.

> Current host note: this machine is Ubuntu 26.04 with Python 3.14 and does not
> currently have ROS 2 installed. Unitree documents Ubuntu 22.04 + ROS 2 Humble
> as its recommended ROS environment. The `.parcel` environment on this machine
> is fully set up for application development and MuJoCo, but native Unitree
> ROS 2 must be built in a supported Humble environment (host, VM, or container).

## Current implementation and readiness — 2026-08-26

Parcel is a simulation-first companion-autonomy stack. The latest social-progress
instrumentation is accepted for simulator shadow collection; autonomous physical
motion and conversation release remain **NO-GO**. A mechanically secured,
zero-motion Stage 0 capture is only conditional and has not been run.

| Surface | Implemented now | Current admission ceiling |
| --- | --- | --- |
| Conversation | The `si-companion-v5` and local prompts make Parcel an ongoing companion friend by default, preserve consent and owner space, and quote history/owner/sensor context as untrusted data. Strict dialogue, embodiment, action-admission, receipt, and terminal-claim contracts also exist. | Prompt freeze/digest/package parity is verified, but the contracts are not yet one fully wired live multi-turn executive. The normal builder currently lacks the manifest composition needed to admit embodied actions. Fresh personal-conversation evidence is 3/13 turns with 2/8 families passing, so conversation release is **NO-GO**. |
| Capability truth | `CapabilityManifestV1` binds declared actions to a deployment, exact asset/schema digests, adapters, and authenticated process-local commissioning evidence. | It is a software trust boundary, not proof that a trajectory or physical capability has been commissioned. |
| Navigation | `grid_v1` remains the command-producing planner implementation, with Follow, point navigation, semantic grounding, collision/person gates, and selected `NavigationSnapshotV2` consumers. | The current normal builder leaves automatic Navigate, Follow, and roam disarmed because it does not inject a capability manifest. Fresh NAV_INSTRUCT is 25/125 with one false arrival. The isolated H2b completion latch missed its frozen gate at 113/120 alias recoveries versus 114/120, remains default-off, and is not in `navigation.pipeline`. |
| Social progress | Only the prototype overlay enables a bounded observer for stall cause, track visibility, full swept-corridor evidence, venue proposals, and requested/final/achieved motion. It samples the requested winner before dispatch and records the final and achieved outcome after the unchanged final gate. | Shadow telemetry/proposals only: all four candidate-policy hypotheses were refuted, and it cannot resume or move the dog, shrink a person envelope, authorize a crosswalk, or enter an elevator. Base and physical profiles are inert. |
| Motion boundary | The normal runtime can compose through the Unix gateway to fake Sport using the permanently disarmed `motion_gateway_disarmed` adapter. Stops cross the socket and reconnect remains disarmed. | There is no acquire/velocity-command surface on this route. Native SDK2/DDS motion, an AGX run, synchronized physical feedback, and measured stopping evidence are absent. |
| Research and learning | A default-off summary-only research spool and immutable split, mining, evaluation, review, and rollback contracts are implemented. | No production crypto/KMS, cloud or Starlink uploader, trainer, deployer, hot swap, automatic self-promotion, or control authority exists. |

The as-built authority model keeps language and learned systems upstream of
deterministic admission and final safety:

```text
committed owner turn + stamped world evidence
                    |
                    v
       typed semantic/action proposal
                    |
 capability + identity + consent + body-state admission
                    |
       planner / executive / behavior loops
                    |
         priority + TTL arbitration
                    |
          final reactive safety
                    |
             ControlManager
              /          \
     MuJoCo backend       Unix gateway -> fake Sport (disarmed test rung)
   (manual/debug paths)               -> native SDK2/DDS -> Go2 (target only)
```

Feedback returns through the stamped observation path. Research, evaluation,
and learning are a separate side plane: they may record evidence or propose a
candidate, but they have no path to command or activate it. In the current
normal application composition, automatic embodied/navigation requests stop at
capability admission; manual simulator controls and the separately scoped pose
gallery remain available.

Scoped implementation evidence remains green: the P0 contract suite passes 187
tests, the independently reviewed social-progress tranche covered 555 focused
and regression tests, and its current focused suite passes 105 tests. Its social
replay reproduces all 475 frozen research rows byte-for-byte with digest
`932167875fd16bbd67256f60ef8b555b074bfb23fb2eb4b3695aa5051578c1ad`.
Current whole-working-tree verification (2026-08-26 23:05 ET) is **RED**. The
tier audit collected 10,954 total tests (10,871 commit and 83 nightly); the
commit main phase reported 10,684 passed, 147 failed, 22 skipped, and 5 xfailed,
while its serial source-sensitive phase passed 12 with 1 skipped. Two
hard gates are red: the default suite and two new Ruff import-order violations.
Parcel services were active during the run, but 22 representative answer-beat
and yield-policy failures reproduced in isolation, so this is not just
parallel-test contention. Treat the current checkout as non-releaseable until
the regressions are repaired and the guarded commit tier is rerun.

For design scope and historical artifacts, see the [current research synthesis](research/20260826/FINAL_REPORT.md),
[P0 implementation report](research/20260826/IMPLEMENTATION_REPORT.md),
[mount-readiness ladder](research/20260826/MOUNT_READINESS.md),
[social-progress implementation](research/20260826/dynamic-social-progress/IMPLEMENTATION.md),
and [robotics code design](docs/ROBOTICS_CODE_DESIGN.md). Their earlier
`FINAL_VERIFICATION_PENDING` or gate snapshots are historical; the current-tree
status above governs this checkout.

## Quick start

For a deterministic simulator and browser panel with no model or hosted API
cost, use:

```bash
cd /path/to/Parcel
./scripts/launch_sim.sh --no-llm
```

The panel opens at <http://127.0.0.1:8765> and the 2.5D viewer at
<http://127.0.0.1:8765/viewer>.

The default application launcher requires the hosted GPT Realtime lane and refuses
before starting anything if its local config or credential is absent. Create the
ignored local files once, then start the Realtime lane, Gemma reasoner, MuJoCo,
and browser panel together:

```bash
cd /path/to/Parcel
mkdir -p "$HOME/.config/parcel"
touch "$HOME/.config/parcel/realtime.env"
chmod 600 "$HOME/.config/parcel/realtime.env"
${EDITOR:-vi} "$HOME/.config/parcel/realtime.env"  # add OPENAI_API_KEY=...
cp --no-clobber configs/realtime.yaml.example configs/realtime.yaml
./scripts/launch_stack.sh
```

Do not place the real key directly in shell history. The example defaults to
hosted text mode; select `mode: audio` in the ignored local YAML to expose the
browser microphone gateway. To exercise the local STT/Gemma/TTS cascade
deliberately, use `./scripts/launch_stack.sh --legacy`; it is the rollback and
E2E-test path, not a silent fallback.

For the current simulator-research overlay, keep its editable Realtime config
outside the checkout, set `PARCEL_REALTIME_CONFIG` in
`~/.config/parcel/realtime.env` to that absolute path, and select the profile
explicitly:

```bash
cp --no-clobber configs/realtime.prototype.yaml.example \
  "$HOME/.config/parcel/realtime.prototype.yaml"
# In realtime.env: PARCEL_REALTIME_CONFIG=/home/you/.config/parcel/realtime.prototype.yaml
./scripts/launch_stack.sh --prototype
```

That overlay enables simulated camera ingress and the social-progress shadow
observer and changes prototype-only clearance settings. It is not a physical
robot configuration and grants no new motion authority.

The city includes seeded moving pedestrians and a cyclist. Manual hold-to-drive
controls remain the current motion smoke path. Text such as `follow me`,
`navigate to the crosswalk`, `I am feeling sad`, or `I am very happy` can still
exercise conversation and refusal telemetry, but automatic embodied actions are
expected to fail closed until the normal builder supplies an admitted simulator
capability manifest. The hosted route sends only the final text submission to
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

**Current architecture:** the decision-oriented version is the
[engineering executive summary](docs/ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md); the
concise as-built package and authority map is the
[robotics code design](docs/ROBOTICS_CODE_DESIGN.md); and detailed target designs,
robotics theory, tradeoffs and gates are in the long-form
[engineering handbook](docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md). Its
baseline status passages are dated; this README's dated status and the newest
August 26 implementation records govern current capability claims.
The [2026 redesign assessment](docs/REDESIGN_2026_ASSESSMENT.md) remains dated
historical rationale; its former seven-layer status page has been retired because
the code and quality baseline have materially changed.
The city simulator has a live 2.5D viewer at <http://127.0.0.1:8765/viewer>,
and the companion-navigation integration eval lives in `evals/companion_nav/`.

## What is included

- A transcript-to-command agent with a safe, explicit command grammar.
- A Gemma/llama.cpp structured-tool adapter with deterministic validation.
- Versioned local and hosted prompts that default to a continuing companion
  relationship while keeping quoted history, owner, and sensor data untrusted.
- Deployment-bound capability manifests plus typed consent, dialogue, action,
  receipt, and terminal-claim contracts. These contracts are only partially
  consumed by the live session and do not authorize motion.
- whisper.cpp recognition plus Piper and cancellable Fish S2 adapters (the
  Sesame CSM adapter is legacy and has no production caller).
- YAML-defined poses and Wi-Fi/network-card profiles.
- A single-writer, feedback-supervised locomotion manager with simulator and
  controller interfaces. The normal Unix-gateway composition is permanently
  disarmed; the direct **Unitree Sport** path is commissioning-only.
- A Python extension interface for custom sensors, behaviors, or hardware.
- ROS topics for transcript input, pose/walk requests, and spoken replies.
- MuJoCo owner/obstacle telemetry and a browser panel for driving and text voice.
- An immutable, provenance-bearing `NavigationSnapshotV2` observation contract;
  the simulator source is wired while the synchronized physical source remains
  a fail-closed skeleton.
- Central priority arbitration, command TTLs, proximity braking, and latched E-stop.
- Persistent owner-follow and point-navigation behavior loops; they remain
  unavailable in the normal application composition until its capability
  manifest is wired.
- Bounded owner-relative steps and local circle trajectories with deterministic
  parsing, owner visibility checks, timeouts, and normal collision arbitration.
- Per-turn E2E/model/TTS traces plus rolling control-component latency metrics.
- Rotate-first, forward-preferred goal navigation with bounded lateral motion
  available for manual control, skills, recovery, and compatible planners.
- A deterministic living-city crowd with full dynamic-agent telemetry.
- A prototype-only social-progress shadow observer that diagnoses false stalls,
  retained tracks, and explicit corridor clearance without consuming its own
  proposals or changing the final safety gate.
- Default-off research and learning planes with bounded local summaries,
  immutable dataset splits, reproducible candidate evaluation, and no model
  activation or control authority.
- Trusted personality/function prompt templates, bounded Gesture emotes, and a
  subordinate 50 Hz expression channel. In an admitted simulator composition,
  idle body offsets actuate in MuJoCo; beat-scheduled head nods are telemetry-
  only because Go2 has no neck.
- MuJoCo, Python audio bindings, linting, and test packages in `.parcel`, plus
  a repo-selected user-space PortAudio runtime and visible host audio endpoints.
  No product microphone/speaker stream or AEC is commissioned.

The first ROS boundary is intentionally simple:

| Topic | Type | Purpose |
| --- | --- | --- |
| `/parcel/transcript` | `std_msgs/msg/String` | Speech-to-text result enters the agent |
| `/parcel/pose_request` | `std_msgs/msg/String` | JSON pose intent sent to a controller |
| `/parcel/walk_request` | `std_msgs/msg/String` | JSON body-frame velocity for locomotion |
| `/parcel/skill_request` | `std_msgs/msg/String` | Named catalog skill request |
| `/parcel/voice_reply` | `std_msgs/msg/String` | Reply for a text-to-speech node |
| `/parcel/stop_request` | `std_msgs/msg/String` | High-priority stop intent |

Pose and walk requests are not sent directly to motors. A controller/bridge must
validate limits, implement an emergency stop, and translate the request into
Unitree commands or RL joint targets. Only one locomotion backend should be
active at a time—see [Motion backends](docs/MOTION.md).

The standalone Unitree Sport commissioning path subscribes to physical motion
feedback, expires stale commands, refreshes active velocity targets, and stops
on stale state or controller faults. It also requires a Unitree lease,
commissioned mode/frame/axis settings, and post-`StopMove` settled feedback.
Its current CLI enforces an `observe -> run -> review -> apply` evidence
lifecycle. Start with the read-only command help; there is intentionally no
copy-paste armed command here:

```bash
.parcel/bin/python -m parcel_robot.unitree_control observe --help
.parcel/bin/python -m parcel_robot.unitree_control run --help
```

This is a bounded standalone commissioning path, not the normal autonomous
composition. `RobotRuntime` still consumes simulator observations, and the
standard Unitree builder does not yet assemble synchronized physical-origin
pose, scan, people, and controller evidence. Follow the handbook's physical
composition and capability-admission sequence before interpreting the adapter
as an end-to-end robot runtime.

Read the safety model in [Closed-loop locomotion and Unitree Sport](docs/MOTION.md)
before connecting hardware, but use the current four-stage CLI help above for
syntax; pre-subcommand one-line examples are historical. The Python supervisor
and software E-stop are not substitutes for an independent hardware E-stop.
The Unitree Python SDK is not installed on this workstation, and the configured
placeholder NIC `enp3s0` does not exist here, so the physical path has not been
hardware-validated.

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

The `sounddevice` distribution is present. A plain unsourced import still fails
because the system PortAudio package is absent, but `scripts/env-audio.sh`
selects the user-space PortAudio 19.7 prefix under `~/.local/opt/portaudio`.
After sourcing it, `sounddevice` imports and currently enumerates the reSpeaker
XVF3800 capture path plus PipeWire/default endpoints. Device discovery is not a
commissioned through-air stream or AEC result.

Activate it and run the repository-owned checks:

```bash
cd /path/to/Parcel
source .parcel/bin/activate
source scripts/env-audio.sh
python -c "import mujoco; print(mujoco.__version__)"
python -c "import sounddevice as sd; print(sd.get_portaudio_version())"
.parcel/bin/python -m ruff check .
scripts/ci_gate.sh commit --json
```

The current checkout is expected to return nonzero for the regressions recorded
in the readiness section above. A release claim requires this exact tier to be
green again; a focused subsystem pass does not substitute for it.

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
Development normally uses a source checkout/editable install. The curated runtime
config, prompt, skill, and navigation assets have an internal parity gate. The
Unitree dependency is also hermetic now: a reviewed 20-file Go2 MJCF/mesh subset
is tracked under `third_party/unitree_mujoco`, pinned by upstream revision and
hashes in `PROVENANCE.json`, and compiled by the asset-first release gate. That
closes the former clean-checkout asset blocker; it does not validate the native
SDK2/DDS control boundary, Go2 dynamics, or any physical robot behavior.

## Skills catalog, city scene, and Dog API

See [Skills / city / RL implementation](docs/IMPLEMENTATION_SKILLS_CITY_RL.md).

Hierarchical companion navigation (PlanIR → grid_v1 → safety → ControlManager),
product eval policy, and the offline BARN/Habitat research boundary are in
[Companion navigation architecture](docs/COMPANION_NAVIGATION_ARCHITECTURE.md).
The dated redesign rationale is in
[REDESIGN_2026_ASSESSMENT.md](docs/REDESIGN_2026_ASSESSMENT.md); current architecture
and implementation status live in the
[engineering handbook](docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md).
Doc index: [docs/README.md](docs/README.md).

The frozen live semantic-planning gate and its append-only run history are in
[planner quality v2](evals/companion/planner_quality_v2/README.md) and its
[result ledger](evals/companion/planner_quality_v2/results/README.md). The
historical CPU and full-CUDA baselines both passed 5/5 selected semantic cases;
the GPU run reduced median usable-plan latency to 5.657 seconds but executed
zero physical episodes. A fresh 2026-08-26 run of the currently admitted planner
reproduced only 3/5 for both full PlanIR and PlanSketch, so 5/5 is not the current
readiness baseline. The separate headless embodied PlanIR gate passed 4/4
supported deterministic cases while explicitly leaving moving-owner follow
unsupported. None is a conversation or official benchmark score.
The historical frozen conversation calibration records Gemma at 6/10 machine
cases and 9/10 structured-safety checks. The fresh personal multi-turn run is
3/13 turns with 2/8 families passing, and the companion remains a conversation
release NO-GO; human review is still absent. A fully
GPU-admitted Ministral 3 8B Instruct challenger started much faster but
regressed to 5/10 conversation cases and 3/5 PlanIR, so it remains
deployment-disabled. Exact current artifacts and their limitations are in
[`research/20260826/system-readiness/RESULTS.md`](research/20260826/system-readiness/RESULTS.md)
and the companion eval ledgers.
Product companion scenarios: `evals/companion_nav/`. Offline BARN/Habitat
proxies: [evals/external/README.md](evals/external/README.md).

```bash
source .parcel/bin/activate
# Public API
python - <<'PY'
from parcel_robot.skills.api import Dog
dog = Dog.from_config("configs/robot.yaml")
print(len(dog.list_skills()), "skills")
print(dog.execute("jump"))
PY

# City sim + browser control deck
./scripts/launch_sim.sh --no-llm

# RL env smoke (no display)
python examples/rl_env_smoke.py

# City navigation (POI grounding + stub pedestrians / social reward)
python examples/nav_city_smoke.py

# Deterministic city-task outcome gate (no viewer)
python -m pytest -q tests/test_headless_city_tasks.py tests/test_mujoco_lidar.py \
  tests/test_city_orbit_clearance.py
```

The `Dog` snippets exercise the direct skill/planner library surface for
development. They do not represent the normal capability-admitted runtime or a
physical command path.

City navigation, dynamic simulator research, action policy, open-weight model
registry, and MetaUrban setup:
see [City navigation](docs/NAVIGATION_CITY.md).
See also [Dynamic city and behavior architecture](docs/DYNAMIC_CITY_AND_BEHAVIOR.md).

```bash
# On a Conda Python 3.9 + GPU host (not this Python 3.14 venv):
bash scripts/setup_metaurban.sh

# active_model: grid_v1 is the command-producing default: the occupancy-grid A*
# planner consumes the occlusion-true raycast LiDAR scan and degrades loudly
# (scan_missing_fallback) to the point-goal stub if the scan is absent.

python - <<'PY'
from parcel_robot.skills.api import Dog
dog = Dog.from_config("configs/robot.yaml")
dog.set_nav_pose((0, 0, 0), 0)
mission, cmd = dog.navigate("I want you to go to the coffee shop at 42nd street")
print(mission.goal, cmd)
PY
```

```bash
source .parcel/bin/activate
parcel-agent --text "status"
parcel-agent --text "walk forward"  # expected fail-closed capability refusal
```

Local MuJoCo pose/walk preview:

```bash
./scripts/launch_sim.sh --no-llm
```

That starts `parcel-sim` and the `parcel-panel` browser UI together. Or run them
separately:

```bash
# terminal 1
.parcel/bin/python -m parcel_robot.sim

# terminal 2 — browser panel
.parcel/bin/parcel-panel --llm
```

The module form, `.parcel/bin/python -m parcel_robot.web_panel --llm`, is equivalent.
`language_model` remains the shared conversation/PlanIR default. To run a
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

The viewer hotkeys are a simulator debugging path and bypass `RobotRuntime`
priority arbitration and owner/obstacle telemetry. Browser manual controls run
through the runtime arbiter and final safety path. Stock `parcel-agent --sim`
text actions currently refuse because the CLI does not provision a capability
manifest; do not treat them as a simulator drive path.

With a local `llama-server` running and configured in `robot.yaml`:

```bash
parcel-agent --llm --text "Could you do the bow pose?"
```

This is useful for developing command parsing and fail-closed admission before
the native ROS and Unitree stacks are available; it does not currently execute
the proposed bow.

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
  libportaudio2 libyaml-cpp-dev
source /opt/ros/humble/setup.bash
```

`libportaudio2` is the normal system runtime for `sounddevice` in this Humble
setup. The current workstation instead uses the repo-selected user-space
PortAudio prefix through `scripts/env-audio.sh`; reproduce and verify whichever
audio boundary the deployment actually selects.

Clone and build the two official Unitree projects next to this repository:

```bash
mkdir -p "$HOME/unitree"
cd "$HOME/unitree"
git clone https://github.com/unitreerobotics/unitree_ros2.git
git clone https://github.com/unitreerobotics/unitree_mujoco.git

cd unitree_ros2/cyclonedds_ws
colcon build
source install/setup.bash
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
cd /path/to/Parcel
source .parcel/bin/activate
parcel-agent --ros --config configs/robot.yaml
```

The virtual environment must be created with the same system Python used by the
selected ROS distribution. Do not copy the current Python 3.14 `.parcel` into a
Humble machine; recreate it there (Humble on Ubuntu 22.04 uses Python 3.10).

Subscribe before publishing because these ROS topics use volatile delivery:

```bash
# terminal 1
ros2 topic echo --once /parcel/voice_reply

# terminal 2, after the echo is ready
ros2 topic pub --once /parcel/transcript std_msgs/msg/String \
  "{data: 'do the bow pose'}"
```

The current ROS node does not provision a capability manifest or authorization
context, so this bow request is expected to produce a fail-closed reply on
`/parcel/voice_reply` and no `/parcel/pose_request`. A motion-capable ROS path
still needs admitted manifest composition plus a controller-owned whole-body
adapter that first confirms locomotion has stopped. Never publish Unitree
`LowCmd` while the onboard Sport service is active. Develop a low-level
replacement only in isolated simulation; the official Unitree MuJoCo settings
use loopback `lo` and DDS domain `1`.

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

Add `wave` to `configs/skills/catalog.yaml`, then inspect it through
`./scripts/launch_pose_review.sh --manual`. Catalog registration alone does not
make a voice or ROS action admissible: the selected deployment manifest must
also authenticate the exact trajectory digest, and the stock CLI/ROS builders
do not yet provision that manifest. The catalog parser also does not establish
physical stability or joint safety; tune and validate the complete pose in
simulation and through a commissioned whole-body controller before hardware
use.

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
- `MicrophoneVoiceLoop` / `SpeakerSink` (`audio/voice_loop.py`): VAD-segmented
  capture, acoustic barge-in behind an echo guard, interruptible playback
- `SileroVad` / `TurnEndpointer` (`audio/endpointing.py`): selected semantic
  endpointing with loud energy fallback; ONNX Runtime and the Silero/Smart Turn
  weights are present
- Prosody analysis / `ExpressionEngine` (`audio/prosody.py`,
  `motion/expression.py`): pre-playback accents, idle body offsets, and
  epoch-scoped timing-only Go2 nod metrics
- `VoicePipeline` (`voice/pipeline.py`): composes a single
  STT/reasoning/TTS utterance

See [Voice intelligence and model design](docs/VOICE_AI_MODELS.md) for model
selection, deployment commands, trust boundaries, privacy, and latency targets.

## Project layout

```text
src/parcel_robot/
├── realtime/ voice/ audio/ duplex/     # hosted/local conversation and speech
├── brain/ contracts/ capabilities/     # plans, admission, receipts, capability truth
├── attention/ memory/ owner_model/     # initiative and consented relationship state
├── observation/ localization/          # stamped snapshots, replay and pose evidence
├── camera_channel/ detection_adapter/  # calibrated ingress and perception adapters
├── perception/ owner_tracking/ lidar/  # semantic, identity and range evidence
├── navigation/ route_memory/ maps/      # grounding, grid planning, Follow and safety
├── core/ motion/ control/              # arbitration, expression and locomotion HAL
├── backends/ simulation/ bags/ rl/      # MuJoCo, deterministic worlds and replay
├── research_plane/ learning_loop/       # default-off data and proposal-only learning
├── counterfactual/                     # offline candidate arbitration replay
├── skills/ prompting/ runtime_assets/   # admitted actions and packaged assets
├── runtime.py                           # composition, behavior loop and final gate
├── sim.py / web_panel.py                # simulator and browser control deck
└── ros_node.py                          # optional ROS topic boundary
gateway/                                 # isolated lease/watchdog/sole-writer process
configs/                                 # canonical config plus explicit overlays
prompts/                                 # trusted system/personality/function templates
evals/                                   # product gates and external research proxies
research/                                # dated hypotheses, artifacts and verdicts
tests/                                   # non-ROS regression and safety suite
deploy/                                  # target service and Orin deployment material
docs/README.md                           # documentation index
```

Official references:

- [Unitree MuJoCo](https://github.com/unitreerobotics/unitree_mujoco)
- [Unitree ROS 2](https://github.com/unitreerobotics/unitree_ros2)
- [ROS 2 Python virtual environments](https://docs.ros.org/en/jazzy/How-To-Guides/Using-Python-Packages.html)
