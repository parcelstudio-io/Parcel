# Day 35: Safety Engineering

## Mental model

Safety is not a feature flag named `be_careful`. It is a structured practice: identify hazards, decide severity, allocate *independent* protections, define safe states, and prove stop authority under failure. Companion robots share sidewalks with people; severity is not theoretical.

Layers of defense (defense-in-depth):

```text
1. design limits     — speeds, keepouts, admitted skills
2. runtime shields   — reactive_safety, TTC, collision brake
3. control watchdog  — TTL, state freshness, single writer
4. software E-stop   — latching veto across arbiter/manager/backend
5. hardware E-stop   — independent power/cut path (required for real ops)
6. operational       — fencing, spotter, commissioning gates
```

Software E-stop ≠ hardware E-stop. Parcel’s latch is necessary and insufficient alone (D2 limitation, stated plainly).

Hazard analysis (informal HAZOP/HARA-style thinking is enough to start) forces you to name energy sources: kinetic body, jaws/gesture contacts, tipped battery packs, and *stale autonomy* that keeps walking. Each hazard needs a control that still works when the LLM, UI, or Wi-Fi is dead.

## Software-engineering analogy

Think of payment fraud controls + break-glass: allowlists, rate limits, anomaly vetoes, kill switches, and a physical card-network disconnect that application servers cannot override. A dashboard “Stop” button that shares the stuck request worker is like an E-stop on the same thread as the hanging model call—theatre.

Fail-safe vs fail-operational:

- **Fail-safe:** on doubt, stop/sit/power-down actuators toward a safe state.
- **Fail-operational:** keep a degraded mission alive (aircraft-style redundancy).

Parcel’s sidewalk default is fail-safe for locomotion. Conversation may degrade; motion must not “wing it.”

**Tradeoff:** aggressive shields reduce collisions and increase nuisance stops / social deadlock. Tune with measured near-miss and false-stop rates, not vibes.

## Light equations (stopping budget)

A crude planning check:

```text
d_stop ≈ v² / (2 a_brake) + v * t_reaction + d_margin
require: range_obstacle > d_stop
```

`t_reaction` includes sense age + compute + command lease + actuator delay. Parcel’s `ReactiveSafetyPolicy.reaction_time_s` (~0.12 s) is a policy parameter—not proof of physical brake distance on a Go2. Always re-measure on hardware.

## ASCII diagram

```text
  hazard ID ──► severity/likelihood ──► risk decision
                      │
        ┌─────────────┼──────────────┐
        v             v              v
   eliminate     software shield   procedure
   (no skill)    (veto/slow/stop)  (spotter/fence)
                      │
                      v
              safe state machine
         IDLE → ACTIVE → STOPPING → ESTOP
                      │
                      v
           evidence: stop latency, confirm,
           independence test, residual risk log
```

## Map to Parcel / Go2

From `safety.py`, `navigation/reactive_safety.py`, `ControlManager`, `CommandArbiter`, `INTRO.md` priorities, and DESIGN D2/D3/D13:

- `SafetyLimits` / arbiter clamps are admission bounds; `ControlLimits` are last-line physical clamps—two walls.
- `apply_reactive_safety` is a runtime-wide veto on velocity sources: obstacle/person stop and slow bands, stale telemetry → stop translation, owner envelopes for follow/orbit.
- Grid planner + TTC brake (D3) are classical and debuggable; learned proposers fail closed until evidence exists.
- Emergency latch dominates; clear is explicit. Stop confirmation uses settled speed samples and sequence numbers—not “we sent stop.”
- Observability must not become a shadow control path (D13): dashboards diagnose; they do not command.
- Unitree Sport may refuse or interpret stops differently under faults; commissioning must verify *observed* stop, including vendor quirks documented in redesign notes (Sport release damage modes when mixed with low-level cmd—never run Sport and `LowCmd` together).

**Design choice:** independent final veto even when the planner “already inflated obstacles.” Cost: duplicate logic. Benefit: planner bugs cannot remove the last brake.

**Codebase anchors (E-stop / shields / limits):**

- `safety.py` → `SafetyLimits` (tool/velocity clamps), `SafetySupervisor.validate` (fail-closed tools), `engage_emergency_stop` / `clear_emergency_stop`.
- `core/arbiter.py` → E-stop latch empties active `MotionIntent`; `runtime.py` engages both `agent.safety` and `arbiter` on hard stops.
- `navigation/reactive_safety.py` → `ReactiveSafetyPolicy` + `apply_reactive_safety` (runtime-wide veto; used from `runtime.py`, follow, search, `headless_city.py`).
- `control/manager.py` → lifecycle `EMERGENCY_STOPPED`, stop confirmation via settled samples / sequence; `ControlLimits` last-line clamps.
- `backends/mujoco.py` → `emergency_stop` / `clear_emergency_stop` over the sim socket; `sim.py` latches `emergency_stopped` independently of the UI.
- D2 honesty: software latch ≠ independent hardware E-stop — still required before unsupervised people-space ops.

## Failure story

A hazard analysis listed “collision with pedestrian” but treated software E-stop as adequate mitigation. In a warehouse aisle test, the compute tether cable snagged and yanked the Ethernet path used for both teleop and E-stop. The dog’s last leased command continued until the control watchdog timed out—longer than the spotter expected because demos had always used a responsive UI. Independent wireless E-stop and a shorter command timeout were added; the analysis was updated to mark software-only stop as residual risk, not closed.

## Retrieval questions

1. Name three Parcel mechanisms that can zero translation without the LLM’s cooperation.
2. Why is “planner said clearance was fine” not a substitute for `reactive_safety`?
3. (Week-back) How do Day 03’s stopping-distance ideas change when `t_reaction` includes a 0.35 s command timeout and stale LiDAR?

## Optional 10-minute exercise

Write a one-page mini hazard list for “voice follow on a wet sidewalk”: at least five hazards, each with a Parcel control that mitigates it and one residual risk that still needs operational controls (fence, spotter, speed cap). Star any item that currently relies only on simulation evidence.
