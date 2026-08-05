# Day 57: Learned Quadruped Locomotion and Adaptation

## Mental model

Learned locomotion replaces (or residuals) the vendor gait/balance stack with a policy trained mostly in simulation: a privileged teacher sees friction and contacts; a student sees IMU, joints, and noisy terrain. The product question is not “can RL trot in a video?”—it is “when may Parcel revoke Unitree Sport’s authority?”

```text
Parcel today:   brain -> body twist -> Sport -> joints/motors
Research loco:  brain -> (twist or none) -> πθ @ high rate -> joints/torques
```

Those are different control authorities. Mixing them without a lifecycle is how dogs fall during a voice demo. Software analogy: swapping your OS scheduler for a research kernel module mid-flight—possible in a lab, reckless in production without a boot path and rollback.

## Tradeoffs and industry trends

Industry: sim-to-real RL locomotion is real for quadrupeds (domain randomization, teacher-student, adaptive curricula). Residual policies that add corrections atop a nominal controller sometimes transfer safer than clean-sheet replacements. System identification and online adaptation fight wear, payload, and surface change. The quiet trend: many “learned loco” successes still keep a strong fall detector and outdoor geofence.

| Choice | Upside | Downside for Parcel |
| --- | --- | --- |
| Keep Sport | Vendor balance maturity | Less agile / less custom |
| Full πθ replacement | Research performance | Owns falls; huge HIL burden |
| Residual on Sport | Smaller blast radius | Clean torque interface may not exist |
| Blind indoor demo | Fast video | Unacceptable companion risk |

Module 6 interrogation:

1. **Observe?** Proprioception-heavy (quat, gyro, `joint_q/dq`)—see Parcel’s `rl/spaces.py` layout (`OBS_DIM = 48`).
2. **Act?** Often joint targets/torques at 200–1000 Hz—not Python ~10 Hz.
3. **Rate/latency?** Hard real-time process; deadline misses = falls.
4. **Data/compute?** Massive parallel sim; onboard inference must be WCET-bounded.
5. **Unitree transfer?** Requires Sport-off modes, torque/joint interfaces, fenced commissioning.
6. **Safety layer?** Watchdogs, geofence, stand support, E-stop—learning is not the shield.

## ASCII diagram

```text
                 privileged teacher (sim)
                         |
                         v
                   student πθ
                         |
         +---------------+----------------+
         |                                |
         v                                v
  research backend "rl"              product "vendor"
  Go2Env joint targets               UnitreeSportController
         |                                |
         v                                v
  ControlManager lifecycle           ControlManager lifecycle
  (armed, watchdog, e-stop)          (default companion path)
```

## Map to Parcel / Go2

Parcel still keeps vendor locomotion as the default product path while exposing a narrow research backend.

Codebase-relative context:

- `SafetySupervisor` only allows motion backends `vendor` | `rl` (`safety.py`, `ALLOWED_BACKENDS`); switching is an explicit validated tool call (`set_motion_backend`), not a model whim. Deprecated `sport` aliases to `vendor`.
- `ControlManager` (`control/manager.py`) remains single writer + watchdog + E-stop lifecycle regardless of backend—learned loco must still arm/disarm here and honor stop confirmation.
- `UnitreeSportController` / `build_unitree_sport_control_manager` (`control/unitree_sport.py`, `control/factory.py`) is the production adapter.
- `Go2Env` (`rl/env.py`) is the Gym-like stub; `action_space_spec()` documents 12 joint position targets (`rl/spaces.py`)—**not** `TimedVelocitySetpoint` body twists that Sport consumes.
- Voice/`PlanIR`/`TaskExecutive` must keep emitting skills and high-level motion intents, never joint vectors—`PlanValidator` already forbids joint/coordinate keys (`brain/validator.py`).
- Nav/follow shields (`apply_collision_brake`, `apply_reactive_safety`, `CommandArbiter`) still apply to mid-level twists even if loco backend changes; do not confuse “better gait” with “permission to ignore people.”
- Duplex/`ActTokenCodec` may tokenize twists for UX research; they must not become a parallel joint commander past `ControlManager`.

Promotion criteria (minimum): stand/fenced fall-rate evidence, stop-confirmation parity with Sport, thermal/power budgets under duplex+perception load, and no path for LLM/VLA to select `rl` outdoors. Until then: **shadow** student vs Sport on logged proprioception; **prototype** only in harnessed HIL; **reject** public sidewalk replacement.

Remember the timescale split from Day 20: even a perfect student policy is a *locomotion* component. Companion navigation, PlanIR skills, and duplex conversation remain outer loops that may only request body twists through the existing HAL—never joint PD setpoints from Python at conversational rates.

## Overconfidence story

A residual policy reduced tracking error on a treadmill and was enabled during an owner-follow outdoor take. A Bluetooth voice glitch coincided with a terrain transition; the residual—trained without that latency spike—injected a pitch correction Sport was already handling. The dog stumbled. Overconfidence was “small residual ⇒ small risk” without proving non-interference under Parcel’s real `ControlTiming` and duplex load. The missing gate was not another reward term; it was a lifecycle rule: `rl` backend cannot arm while duplex+follow are live until WCET evidence exists, and `ControlManager` stop confirmation must match the vendor path’s fault classes.

## Retrieval questions

1. What action-space mismatch separates `Go2Env` from `TimedVelocitySetpoint` → Sport?
2. Which Parcel object must still own E-stop/watchdog if `rl` backend is armed?
3. (Week-back) From Day 20: why can’t the conversation brain join the balance loop even with a great loco policy?

## Optional 10-minute exercise

Draft a go/no-go checklist to flip `set_motion_backend` to `rl`: required metrics, enclosure rules, who may toggle it, how `ControlManager` stop confirmation is proven, and which voice tools remain disabled while `rl` is armed.
