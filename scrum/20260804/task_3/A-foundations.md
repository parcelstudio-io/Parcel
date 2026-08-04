# Workstream A — foundations (V0, V1)

The audit's verdict makes this non-optional: pause/resume is missing at all
three layers, preemption is destructive at 16 hand-enumerated call sites,
and the arbitration layer scores an effective 4/10 for this project without
the registry. Owner decision: this lands **before** any steering code.

---

## V0 — Spike + hygiene · **Opus** · days

1. **Go2 posture-composition spike plan** (hardware-gated; write the exact
   procedure now): does `Euler(roll,pitch)`/`BodyHeight` compose with
   `Move(vx,vy,vyaw)` while trotting? Public docs verifiably silent; Spot's
   equivalent restricts body pose to standing and silently saturates —
   procedure must read *achieved* posture back and drive conclusions off
   achieved, not commanded, values. Outcome decides HAL Option A vs B.
2. **Pause-semantics convention doc** (`docs/` one-pager): ticked-vs-unticked
   per behavior. Known inconsistency to resolve: the pipeline progress
   watchdog counts `step()` invocations (400 no-progress ticks ≈ 40 s —
   output-suppression "pause" kills the mission mid-conversation) while
   SearchOwner's 45 s budget is wall-clock (burns while unticked). Rule:
   suspension freezes *both* kinds of budget explicitly.
3. **B4 dead-code sweep**: the deletion list is prepared and archived
   (`backlog/BLOCKED.md` B4); execute with the operator, plus lazy-import the
   v8 shield so 55 BARN test files stop appearing in greps of the area about
   to be refactored.

## V1 — Foundations refactor · **Opus** · ~1.5 weeks

The audit's ranked items 1–6 + 8, consolidated. **Freeze the current
follow-bench + embodied ledger rows first; byte-identical rows are the exit
criterion.**

1. **BehaviorChannel registry + declarative preemption/resume table.**
   Protocol: `name, arbiter_source, priority, stop(reason), snapshot(),
   pause()/resume() (optional)`. Wrap follow / navigation / spatial /
   search / activities. Replace the 16 hand-enumerated stop sites with one
   `runtime.preempt(source, policy)`; derive `ActivityContext.busy_reason`,
   the expression gate, the prompt-context ladder, and
   `SemanticRuntimeState` channel fields from the registry.
2. **Navigation pause seam.** `DirectiveNavigator.pause()/resume()` freezes
   `_steps_without_progress` + `_terminal_verification_steps` and retains
   the `Mission`; runtime suspend path distinct from `stop_navigation()`;
   `Mission.status` becomes an Enum including `paused`.
3. **Executive `SUSPENDED`** as a **status, not an outcome** (a pause read
   as step-failure triggers replan/abandon — the most likely bug in this
   feature). Suspend releases leases via the existing reconcile-stop path;
   resume re-queues keyed on (task, revision, step, attempt) + a
   completed-set to kill double-dispatch; the `voice` interrupt source gets
   a declared suspend-vs-overlap policy table (it is a hardcoded no-op
   today).
4. **Typed `ResumeIntent`** {channel, step cursor, typed args, validity
   condition, suspend reason, timestamp} held by the registry — replaces
   `_resume_follow_after_search` (hand-cleared at 5 sites today).
5. **Per-channel generation tokens** replacing global
   `_behavior_generation` (the global counter cannot express
   non-destructive pause).
6. **Adapter verifier table-ization**: skill→verifier registry over frozen
   controller sub-views; terminal-state constants imported from the
   controllers that own them (kills silent literal drift when `paused`
   appears as a state).
7. **Typed frozen detail dataclasses** with `as_dict()` at the snapshot
   boundary (navigation/spatial/follow/voice) — before the attention channel
   would add a fifth stringly dict.

**Exit:** suite green; ledger rows byte-identical; preemption graph exists
in exactly one table; a demo script can pause and resume a navigation
mission from the REPL with the mission surviving.

---

## Go2 posture-composition spike procedure (V0 / HAL Option A)

**Status:** written for hardware arrival; do not run until U1 velocity+E-stop
bring-up through `ControlManager` is green. Outcome chooses HAL Option A
(capability-gated Euler/BodyHeight expressive posture) vs Option B (bounded
twist deltas).

### Preconditions

1. Physical Go2 on a clear flat floor; Sport mode lease held by the dedicated
   control process (`unitree_sport` via `ControlManager` only).
2. SDK `SportClient` available; `allowed_modes` temporarily includes the
   standing/trot modes under test (restore empty afterward).
3. Operator E-stop reachable; second person spotting.
4. Logging: record commanded Euler/BodyHeight/Move and **achieved** body
   attitude from `SportModeState` (IMU / body pose fields) at ≥50 Hz.

### Exact SportClient call sequence

For each trial block below, start from a confirmed stand, then:

1. `SportClient.Init()` / lease already held by the supervisor.
2. Enter trot (or the standing locomotion mode under test) using the existing
   mode transition the supervisor already owns — do **not** invent a parallel
   mode client.
3. `Move(vx, vy, vyaw)` with a mild forward command, e.g. `(0.25, 0.0, 0.0)`,
   held for 3 s while logging achieved SE2 velocity.
4. While `Move` continues, issue posture composition commands in this order
   (1 s settle each, still logging achieved posture — never commanded-only):
   1. `BodyHeight(δ)` with `δ ∈ {+0.02, -0.02}` m (expression clamp band).
   2. `Euler(roll, pitch, yaw)` with `(0, ±6°, 0)` then `(±4°, 0, 0)` (deg→rad
      per SDK).
   3. Combined: `BodyHeight(+0.02)` + `Euler(0, +6°, 0)` while `Move` holds.
5. `StopMove()`, return to stand, clear posture offsets (`BodyHeight(0)`,
   `Euler(0,0,0)`), 2 s settle.
6. Repeat steps 3–5 at `vx=0` (standing in place) as the control condition.

Spot analogy to falsify: Spot silently saturates absolute body pose while
walking — if Go2 does the same, achieved posture will diverge from commanded
while trotting even when standing trials look perfect.

### Pass / fail criteria (HAL Option A)

| Check | Pass | Fail → Option B |
| --- | --- | --- |
| Achieved pitch/roll within 2° of commanded while trotting for ≥2 s | Option A viable | Saturation / no-op under motion |
| Achieved body height within 1 cm of commanded while trotting | Option A viable | Height ignored or fights balance |
| Measured `|vx|` stays within 20% of pre-posture baseline (no trip/slip) | Safe composition | Posture disturbs locomotion |
| E-stop / `StopMove` still feedback-confirmed during composed posture | Hard gate | Abort spike; do not ship Option A |
| Standing (`vx=0`) composition meets the same posture tolerances | Required control | Sensor/logging invalid |

**Decision rule:** all pass rows → ship HAL Option A (capability-gated
expressive-posture track). Any fail row → Option B (bounded additive twist
deltas upstream of the gate; glance degrades to heading-bias + cadence dip).
Record the decision + raw achieved-vs-commanded traces under
`backlog/UNVERIFIED.md` until hardware closes U1.
