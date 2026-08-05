# Day 58: Safe Learning and Runtime Assurance

## Mental model

Learning systems propose; runtime assurance disposes. Control barrier functions (CBFs), shields, and fallback controllers are mechanisms that keep state inside a safe set even when a learned policy is wrong. Ames et al.’s CBF treatment (arxiv 1903.11199) is the conceptual ancestor: safety as a constraint that can override nominal control.

```text
π_learned(o) -> a_nom
a_safe = argmin ||a - a_nom||  s.t.  safety constraints (CBF / shields / gates)
if infeasible: a_fb = fallback (stop / Sport stand / E-stop)
```

Parcel already practices a software form of this—even without naming Lyapunov functions. Think of it as an admission controller in front of a stateful datastore: the ML ranker may be brilliant; the controller still rejects writes that violate invariants.

## Tradeoffs and industry trends

Trend: “safe RL” papers with constrained MDPs, shielding, OOD detectors, and CBF-QPs. Industry reality: most deployed robots use hard gates, geofences, speed caps, and independent E-stops long before formal certificates on full SE(3)+contact systems. Formal filters are valuable when dynamics are simplified and sensing is trusted; they are theater when the disturbance model omits the child who reverses direction.

| Mechanism | Strength | Limit |
| --- | --- | --- |
| Distance speed caps | Simple, testable | Myopic; sensing dependent |
| Predictive TTC / ray shields | Forward looking | Model/sensor error |
| CBF-QP filters | Formal flavor on simplified dynamics | Hard on full quadruped contact |
| OOD abstention | Knows when to stop proposing | Needs calibrated uncertainty |
| Fallback controller | Always available | Must be independently trusted |

Design choice: **compose filters, don’t replace them.** A new CBF layer that deletes `person_stop_m` because “theory covers it” is a regression. Module 6 interrogation for any “safe learning” add-on: it still observes through Parcel sensors, still may not own Sport, still needs worst-case latency, still fails closed when uncertain.

## ASCII diagram

```text
  learned proposer (IL / RL / VLA / VLN)
              |
              v
        a_nominal (SE2 / twist / skill)
              |
              v
   ┌------------------------------┐
   | Runtime assurance (Parcel)   |
   | PlanValidator (no raw motors)|
   | GoalArbiter TTL / lethal veto|
   | Collision + ReactiveSafety   |
   | CommandArbiter TTL / priority|
   | ControlManager watchdog/E-stop|
   └--------------+---------------┘
                  |
         +--------+--------+
         | accept | reject |
         v        v
      ControlMgr  zero twist / stop
         |
         v
       Sport
```

## Map to Parcel / Go2

Parcel still keeps assurance deterministic in stacked gates while research explores richer filters.

Codebase-relative context:

- Semantic fail-closed: `PlanValidator` + forbidden motor/coordinate keys (`brain/validator.py`); recoveries already include `safe_stop`.
- Nav assurance: `GoalArbiter` lethal/TTL veto (`instructnav/arbiter.py`); `CollisionPolicy` / `apply_collision_brake` (`navigation/collision.py`); experimental research shield hook `experimental_all_ray_shield.py` via `DirectiveNavigator` (keep deployment-disabled until promoted—see redesign notes).
- Runtime final gate: `apply_reactive_safety` (`navigation/reactive_safety.py`) including stale telemetry handling; runtime metrics bucket labeled `CollisionGate` in `runtime.py`.
- Authority: `CommandArbiter` (`core/arbiter.py`) priority+TTL; `ControlManager` lifecycle, watchdog stops, emergency threads (`control/manager.py`).
- Tool validation: `SafetySupervisor` (`safety.py`) clamps `SafetyLimits` (`max_vx`/`max_vy`/`max_vyaw`) and backend names.
- Duplex: `DuplexCoordinator` + `ActTokenCodec` (`duplex/`) must not outrank these gates when emitting ACT/twist tokens; bins already sit inside the limits envelope.
- Follow/social: `FollowOwnerController` progress logic cannot override person-stop envelopes.

CBF research can **prototype** as an extra QP on mid-level twists on the same writer path—never as a reason to delete distance gates. **Reject** “uncertainty was low ⇒ skip reactive safety.” **Adopt** clearer OOD abstain → `safe_stop` / ask-user recoveries already in PlanIR vocabulary. **Shadow** log when a hypothetical CBF would have differed from today’s brake decision.

When writing design docs, phrase assurance as *authority*, not *accuracy*: a 99th-percentile calibrated network still loses to a stale LiDAR TTL. Parcel’s `telemetry_stale_s` stop behavior is the template—learning stacks should fail the same way, just with better proposers upstream. If a learned shield cannot explain which sensor field justified motion, it is not assurance; it is vibes with a matrix.

## Overconfidence story

A shield QP certified “safe” under a constant-velocity pedestrian model. A child stopped and reversed; the certificate’s assumption was false, but the dashboard still showed green CBF margins. Only `person_stop_m` in `ReactiveSafetyPolicy` zeroed translation. Overconfidence was formal décor on an incomplete disturbance model. The lesson for Parcel: keep the boring gate, then add theory as a *tightener*, not a replacement—and log both decisions so shadow mode can prove the QP never loosened the classical brake.

## Retrieval questions

1. List Parcel’s assurance layers from `PlanIR` to Sport in order.
2. What does a CBF filter still need from sensing that `apply_reactive_safety` also needs?
3. (Week-back) From Day 35: fail-safe vs fail-operational—which is Parcel’s default when telemetry is stale?

## Optional 10-minute exercise

Open `navigation/reactive_safety.py` and `core/arbiter.py`. For a hypothetical diffusion twist proposer, mark which function zeros motion on (a) stale observation, (b) person inside stop radius, (c) expired motion TTL, (d) E-stop. Note any gap a CBF would still not cover (e.g., wrong association of “person”).
