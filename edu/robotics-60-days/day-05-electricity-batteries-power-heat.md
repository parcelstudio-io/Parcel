# Day 05: Electricity, Batteries, Power, and Heat

## Mental model

Every Newton of foot force and every GPU inference ultimately comes from the battery. Electrical power is the scarce shared bus between **actuation, compute, sensing, and cooling**. Voltage sag, current limits, and temperature are first-class runtime signals — peers of LiDAR obstacles — not ops afterthoughts.

If you only model “CPU %” and “disk,” you will ship a companion that dies mid-follow on a cold incline with the UI still logically healthy. Motors and computers fail differently under the same brownout: legs limp, hosts reboot, DDS/RPC blip — and your follow controller may keep a stale velocity lease until a timeout saves you.

In Parcel, battery policy is already wired as application state: `configs/robot.yaml` → `battery:` (`simulated_percent`, `low_threshold_percent`, `critical_threshold_percent`), consumed in `RobotRuntime` and exposed as `BatteryStateSnapshot` (`src/parcel_robot/brain/contracts.py`).

## Light equations

```text
V = I R                 # Ohm (wires, internal resistance)
P = V I                 # electrical power
E = P t = V I t         # energy drawn over time
P_mech ≈ τ ω            # mechanical power at a joint
P_loss → heat           # inefficiency becomes temperature
V_loaded = V_oc - I * R_internal   # sag under load
```

Brownout: voltage under load drops below controller/compute thresholds even if a resting voltage looked fine. High motor current + weak pack ⇒ simultaneous compute glitches and limp motors. Capacity in A·h or W·h only predicts runtime at an *average* power; bursts are what trip you.

## Software-engineering analogy

The battery is a shared rate-limited quota with burst capacity — like a cloud account with CPU credits. Actuators are spiky workers; the LLM/GPU is a long-running heavy job; Wi-Fi and LiDAR are always-on sidecars. Thermal limit is an involuntary throttle / OOM killer: motors fold back torque; GPUs clock down.

`FaultReason.POWER` on `RobotMotionState` is a hard inhibit class for generic control code — not a soft “replan the sidewalk.” Watchdogs on comms loss matter because a browning compute node may fail halfway through “just one more” velocity update; Sport must stop safely without waiting for Python (`control.command_timeout_s` in `configs/robot.yaml`).

## ASCII diagram

```text
                 ┌──────── battery pack ────────┐
                 │  V, I, SoC, temp             │
                 └───────┬──────────┬───────────┘
                         │          │
            ┌────────────▼──┐   ┌───▼────────────┐
            │ 12× actuators │   │ compute + radio│
            │ high burst I  │   │ steadier draw  │
            └───────┬───────┘   └───────┬────────┘
                    │ heat              │ heat
                    ▼                   ▼
              motor thermal         CPU/GPU thermal
              derate / fault        throttle / drop

  Parcel brain still at ~10 Hz — useless if power fault stops legs first
```

## Map to Parcel / Go2

- `edu/INTRO.md`: battery constrains actuator power, payload, compute, cooling, and mission time. Voltage, motor temperature, and communication loss are software-visible safety concerns.
- Sim has no real pack: `battery.simulated_percent` keeps `battery_critical` procedures (e.g. `ReturnToSafePose` referenced from `brain/validator.py` / `brain/compiler.py`) testable until a hardware state source replaces it — `runtime.py` states this explicitly.
- Control plane: branch on `FaultReason.POWER`, not raw vendor integers in `vendor_extra` (`control/models.py`). Quarantine vendor codes so feature modules cannot scrape them inconsistently.
- Production split: Python may host conversation/planning on a separate computer from Unitree’s locomotion machine. Both still sit on finite energy and thermal envelopes when integrated on the dog.
- Companion workloads: ASR, VLM/LLM, LiDAR processing — real watts. Budget demos as “compute + walk.” `docs/REASONER_GPU_PROFILE.md` is a reminder that model choice is also a power/thermal choice.
- Command timeouts and stop confirmation exist partly for comms/power flakiness: if the brain stalls, motion must quiesce.

Do not plan missions that assume constant peak torque and constant GPU clocks. Derating is normal operation near limits.

## Failure story

An outdoor follow test added a heavier compute payload for live vision. Average current rose; on a short grass incline Sport demanded a current spike for the uphill gait. Pack voltage sagged, the perception NUC rebooted, Parcel lost state updates, and a stale follow velocity briefly continued until the control timeout stopped the dog. The bug was filed as a software crash; the cause was power architecture: burst actuation + compute without brownout margin. Mitigation: lower `max_vx` on low SoC, shed noncritical vision, and treat power faults as immediate motion inhibits.


## Building habit

Budget missions as “compute + locomotion,” not locomotion alone. Before outdoor tests, decide which features shed first on low SoC (`language_model`, heavy vision, then speed caps) and wire that policy to `BatteryStateSnapshot` states rather than hoping operators notice. Keep `FaultReason.POWER` handling next to `COMMS` and `TILT` in control reviews—same severity class for motion inhibit. Use simulated battery thresholds in `configs/robot.yaml` to exercise `ReturnToSafePose` / `battery_critical` paths in CI so they are not dead code until hardware arrives. Remember brownout is a loaded-voltage phenomenon: resting percent is not a climb clearance certificate.

## Retrieval questions

1. Why can a battery show a healthy resting voltage and still brown out when the Go2 climbs?
2. How should Parcel react to `FaultReason.POWER` compared to a soft navigation replan?
3. (Day 04) Why is thermal motor derating especially dangerous when the CoM is near the edge of the support polygon?

## Optional 10-minute exercise

Estimate energy for 20 minutes at an average 80 W locomotion+compute budget (`E = P t`). Then estimate a 5 s climb burst at 400 W. Open `configs/robot.yaml` `battery:` and `RobotRuntime._battery_snapshot` in `src/parcel_robot/runtime.py`. Draft one shed-first policy line for low SoC.
