# Day 40: Synthesis — Production Readiness

## Mental model

Production readiness for a companion quadruped is not “the demo worked.” It is an evidence pack that the authority diagram, failure tree, and commissioning gates hold under load. Module 4’s pieces must compose:

```text
typed intents → executive → arbiter/leases → shields → ControlManager → vendor
        ↑                         ↑
   validated PlanIR          observability (read-only)
```

Python may orchestrate; C++/SDK (and maybe Rust later) own hard edges when measured (D10). The LLM remains an untrusted semantic planner. Until hardware E-stop, commissioned frames, and stop-latency evidence exist, the dog is a supervised prototype—not a product.

Production readiness is a *conjunction*: architecture (Days 31–35) ∧ simulation honesty (36–37) ∧ evaluation (38) ∧ operable telemetry (39). Any missing conjunct is a no-go, even if the demo reel looks fine.

## Software-engineering analogy

Treat release like shipping a payments service to a new region: threat model, blast radius, kill switches, on-call runbooks, staged traffic, and explicit non-goals. A beautiful UI on a laptop sim is localhost. Fenced Go2 walks are staging. Unsupervised sidewalk is multi-region prod—earn it.

**Tradeoffs to keep visible:**

- Strict schemas vs novel behaviors (D1).
- Fail-closed shields vs social liveness (D3).
- Fast Python iteration vs tail latency (D10).
- Proxy benchmarks vs companion gates (D11).
- Rich sim worlds vs honest observation contracts (D5/D9).

## Light equations (go / no-go)

A release gate sketch:

```text
ready_hw ⇔ estop_independent
        ∧ axes/frame/modes commissioned
        ∧ stop_latency_max < budget
        ∧ lease_expiry → observed_stop
        ∧ product_evals pass ∧ proxies don’t override shields
        ∧ does_not_prove reviewed
```

Any false clause → stay fenced or on the stand.

## ASCII diagram

```text
                 Authority (who may write motion?)
  LLM/PlanIR --propose--> Validator/Executive --dispatch-->
        skills/nav/follow --MotionIntent--> CommandArbiter
                |                               |
                |                        reactive_safety
                v                               v
                         ControlManager (single writer)
                                |
                     BackendVelocity / UnitreeSport
                                |
                         motors (vendor)

  Failure tree (condensed):
  model hang → TTL expiry → stop
  scan stale → shield zeros translation
  tilt/comms/power fault → manager fault/E-stop path
  operator hazard → latch E-stop (+ hardware cut)
  debug hotkey path → MUST be disabled on HW profiles
```

## Map to Parcel / Go2

Synthesize `INTRO.md`, `DESIGN_DECISIONS.md`, and Module 4 code:

- **Boundaries:** PlanIR + HAL; no torque from intelligence layers (Day 31).
- **Comms honesty:** ROS concepts guide seams; desktop bus is `SimulatorBackend` (Day 32).
- **Failure:** leases, watchdogs, latches (Day 33).
- **Behavior:** `TaskExecutive` + preemption table; pause ≠ replay velocity (Day 34).
- **Safety:** defense in depth; software latch insufficient alone (Day 35).
- **Sim truth vs product observations** (Day 36); **gap ladder** (Day 37).
- **Eval pyramid + `does_not_prove`** (Day 38); **read-only latency/ops** (Day 39).

Commissioning checklist (minimum): Sport lease on; axes/frame/modes flags true; E-stop path tested with blocked UI thread; max feedback age and stop latency recorded; debug bypasses off; spotter + fence for first walks.

**Design choice:** evidence before embodiment expansion. Cost: slower hype. Benefit: fewer irreversible lessons taught by damaged hardware or frightened pedestrians.

Before unfencing: read Day 31–39 failure stories aloud as a pre-mortem; confirm debug hotkeys/direct IPC are disabled on the hardware profile; confirm a spotter holds an independent stop. Paper architecture without that ritual is cosplay.

**Codebase anchors (readiness stack):**

- `safety.py` → `SafetySupervisor` / E-stop; `core/arbiter.py` → `CommandArbiter`; `control/manager.py` → `ControlManager`.
- `brain/executive.py` + `brain/validator.py` → admit/execute; `core/preemption.py` → channel matrix.
- `navigation/reactive_safety.py` → final veto; `runtime.py` → wires arbiter, shields, latency, control.
- `control/factory.py` → hardware build gates (`enable_lease`, `axes_commissioned`, `state_frame_commissioned`).
- `backends/base.py` / `sim.py` — sim path; must not be the only evidence.
- `observability.py` + `web_panel.py` — diagnose only (D13).
- `evals/**` reports — admission with `does_not_prove`; `tests/test_brain_executive.py` for interrupt truth.

Language choice recap (D10): keep product behavior in Python until a measured deadline forces a native extract behind an existing Protocol. Premature rewrites do not substitute for leases, shields, or commissioning gates.

## Failure story

A team declared “production ready” after a weekend of sidewalk demos with a laptop in a backpack. They had green headless orbits, a ROS bridge WIP, and a software E-stop bound to the same SSH session that died when the LTE hotspot hiccupped. The dog continued on a stale follow lease toward a curb. Spotter grabbed the hardware cut. Postmortem checklist became Module 4’s syllabus: independent stop, short leases, commissioned frames, eval honesty, and a written failure tree signed before the next unfence.

## Retrieval questions

1. List the order of authority from LLM output to motor current in Parcel’s intended stack.
2. Which three evidence items would you require before raising `SafetyLimits.max_vx` on hardware?
3. (Week-back) Pick one Day 33 failure mode and show where Days 35, 38, and 39 each catch it.

## Optional 10-minute exercise

Draft a one-page go/no-go sheet for first fenced Go2 walk: authority diagram (boxes = real classes above), five fault-injection tests you will run on the stand, and the `does_not_prove` list you will read aloud before power-on. Cross-check each box against a path under `src/parcel_robot/`.
