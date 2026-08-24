# H4 — one continuous body intent, any body · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A body-neutral **`BodyIntentV1`** stream — locomotion (velocity or explicit
HOLD), posture offsets, gaze, breathing phase, gait-style hint — emitted
continuously at ≥ 20 Hz by a pure composer that merges the FINALIZED
velocity from the existing arbiter/finalize chain with the expression
engine's clamped offsets, can be consumed unchanged by (a) the MuJoCo
adapter, (b) a fake custom quadruped with a *different capability
manifest* (no posture, gaze-yaw only), and (c) a Go2 Sport adapter stub —
with 100 % envelope compliance, jerk within bound, zero IPC rejections over
10 minutes, COM drift < 1 cm while "holding", preemption to HOLD within
one tick, and no measurable change to the 10 Hz loop's P99.

## Why (lifelike-behavior + portability surveys)
- Today there is no continuous intent: `_dispatch_active` emits only while
  an intent is active and sends `stop("intent_expired")` once, then
  nothing (`runtime.py:~10943`); a stationary hold is the *absence* of a
  command. The owner asked for a planner that is always emitting
  (breathing, looking) — PROTO-0 correctly notes "continuous" must include
  a stationary hold.
- Expression runs at 50 Hz on its own thread, publishes only on change,
  actuates only in MuJoCo (`backends/go2.py:~1173` is a no-op); head yaw
  actuates nowhere. `ExpressiveOffsets.clamped()` is the single amplitude
  authority — keep it.
- Portability: `SimulatorBackend.expression(joint_offsets)` is a 12-DoF
  joint dump; the survey's top-2 design change is "expression as a
  capability manifest, not joint tables", and top-3 is "a whole-body
  command interface above `TimedVelocitySetpoint` that Sport, a custom
  WBC, and an RL policy all implement". The Go2 has no neck/tail/ears;
  a custom robot may — the manifest is how the same brain drives both.
- Safety: the composer sits BELOW `finalize_command` on the locomotion
  axis (it consumes the finalized velocity, never produces one) and
  posture/gaze stay inside the expression gate — no new authority.

## Objective
Define and measure the body contract the milestone design commits to, and
prove portability by adapter LOC, not by argument.

## Experiment
1. **Contracts** (`contracts/body_intent.py`, new): `BodyIntentV1(frozen)`
   {stamp_ns, epoch, seq, ttl_ms, locomotion: `Velocity(vx,vy,vyaw)` |
   `HOLD`, posture: (dz, pitch, roll), gaze: (yaw, pitch), breathing_phase,
   style ∈ {calm, alert, playful}, source, priority}; `BodyCapabilityManifest`
   {locomotion_velocity, hold_is_command, posture_offsets, gaze_yaw,
   gaze_pitch, gestures: tuple[str,...], max_rates}; `degrade(intent,
   manifest)` pure — drops unsupported axes, never invents motion.
2. **Composer** (`motion/body_composer.py`, new pure): inputs = finalized
   velocity (or None ⇒ HOLD), `ExpressiveOffsets` (clamped), gaze target,
   style; output = one `BodyIntentV1` per tick at 20–50 Hz with a jerk
   limiter on posture/gaze; ALWAYS emits (HOLD included).
3. **Adapters**: `simulation/body_adapter.py` (→ `PoseController.set_expression`
   + backend velocity, byte-identical to today's path when the composer
   passes through); `research/.../fake_quadruped_adapter.py` (manifest:
   no posture, gaze_yaw only, hold_is_command=True) — target ≤ 150 LOC;
   `control/go2_sport_body_adapter.py` STUB mapping to the Sport
   primitives named in `docs/EMBODIED_EXPRESSION.md:~196` (`Euler` for
   posture, `Move` for velocity, `StopMove` for HOLD) with NO SDK import
   and every method refusing until commissioned — the shape only.
4. **Harness**: 10-minute MuJoCo runs (owner's sim untouched — start your
   own `parcel_robot.sim` on a private socket) in four states: idle hold;
   idle + look-around; navigating; e-stop injected at t=5 min. Record the
   intent stream, the sim's joint offsets, IPC rejections
   (`simulation/ipc.py MAX_EXPRESSION_OFFSET_RAD`), base COM.
5. **Loop cost**: run the composer inside a harness copy of the control
   loop cadence and measure `ControlLoopWork`-style P99 with/without.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| B1 | emission rate (steady, all states) | ≥ 20 Hz, no gap > 100 ms |
| B2 | envelope compliance (±2 cm / ±6° / head limits) | 100 % |
| B3 | posture/gaze jerk (finite-diff, 3rd derivative) bound | within the limiter's declared bound; spectral roll-off reported |
| B4 | IPC rejections over 10 min | 0 |
| B5 | COM drift while HOLD | < 1 cm |
| B6 | e-stop → HOLD latency | ≤ 1 tick |
| B7 | navigating-state velocity byte-identical to today's path | yes |
| B8 | fake-quadruped adapter LOC; product-code diff to support it | ≤ 150; 0 lines |
| B9 | loop P99 with composer | ≤ today + 5 % |

## What would refute it
B7 fails ⇒ the composer altered locomotion — a design violation, stop and
report; B8 needs product edits ⇒ the manifest is incomplete (name the
missing axis); B1 cannot hold at 20 Hz in Python ⇒ the composer belongs in
the native governor tier (say so with numbers).

## Evidence tier / does not prove
`desktop-sim`. Proves the contract, portability-by-adapter, and loop cost;
proves nothing about Go2 balance/contact or Sport API behavior.

## OWNS
`research/20260823/continuous-body-intent/**`, new `contracts/body_intent.py`,
`motion/body_composer.py`, `simulation/body_adapter.py`,
`control/go2_sport_body_adapter.py` (stub), one capability test
`tests/test_h4_body_intent.py` (degrade never invents motion; HOLD always
emitted; manifest round-trip). Must not touch: `runtime.py`, `core/`,
`motion/expression.py` semantics (consume it), the owner's sim on
`/tmp/parcel_sim.sock`.
