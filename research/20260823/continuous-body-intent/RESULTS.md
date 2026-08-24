# H4 — one continuous body intent, any body · RESULTS (Opus) · 2026-08-23/24

Tier **desktop-sim**. Tree at HEAD `0ec1d7c` (DEC-FS-1), nothing committed.
Hosted spend **$0.00**. Every number below is produced by
`results/rows.json` (built by `summarize.py` from the raw files beside it);
the criteria in that file are the DESIGN's, copied and not edited.

## What was run

```
research/20260823/continuous-body-intent/run_all.sh          # the whole thing
  parcel_robot.sim --socket research/.../h4_sim.sock --static-city
  harness.py --state {idle_hold,idle_look,navigating,estop} --seconds 600
  loop_cost.py --seconds 300 --iterations 100000
  limiter_bench.py --seconds 600        # jitter-free clock
  com_probe.py                          # headless MuJoCo, no viewer/socket
  portability_audit.py                  # row B8
  summarize.py                          # rows.json
```

Environment: own MuJoCo simulator on a private socket under this folder (the
owner's `/tmp/parcel_sim.sock`, `:8765`, `:8080` and `parcel_memory.sqlite3`
were never touched); composer at 50 Hz, behaviour/finalize chain at 10 Hz.
The host was heavily shared with the other hypothesis executors throughout:
1-minute load average **94 → 171** on 192 cores, GPU 2–100 % (H2/H6). No GPU
work of my own. That load is visible in rows B1, B3 and B9 and is called out
where it matters.

## Measurements (criterion = the DESIGN's, verbatim)

| row | criterion | measured | met? |
|---|---|---|---|
| B1 | ≥ 20 Hz, no gap > 100 ms | 49.52 / 49.85 / 49.92 / 49.95 Hz by state; worst gap **85.3 ms**; p99 gap 21.0–23.0 ms; **0** gaps > 100 ms over 119,552 ticks | **yes** |
| B2 | envelope compliance 100 % | **0** violations in 119,552 emitted intents (100.000000 %); amplitude clamp never bound (0 events, max excess 0.0) | **yes** |
| B3 | jerk within the limiter's declared bound; roll-off reported | jitter-free clock (30,000 ticks): **0** windows over bound on all 4 axes. Wall clock: **19 of 597,700** windows over (0.0032 %) — 3 are the declared e-stop bypass (27.8×), 16 are ≤ 1.18× on rate-saturated ticks. Roll-off below. | **no, as measured** (see §B3) |
| B4 | 0 IPC rejections over 10 min | **0** server rejections on 1,533 sampled replies, **0** local validation failures, 76,690 messages; seeded rejection probe detected in all four states | **yes** |
| B5 | COM drift while HOLD < 1 cm | whole-body COM excursion **0.13 mm** horizontal / 0.32 mm vertical over the 10-min idle_hold trace; **0.65 mm** / 1.60 mm at the worst corner of the entire ±2 cm / ±6° envelope | **yes** |
| B6 | e-stop → HOLD ≤ 1 tick | **17.66 ms = 0.883 tick** to the HOLD intent, and the same 17.66 ms to `backend.stop()` on the wire | **yes** |
| B7 | navigating velocity byte-identical | **byte-identical in all four states**: 3,402/3,402 messages (navigating), 1,699/1,699 (estop), 0/0 (both idle states) | **yes** |
| B8 | fake adapter ≤ 150 LOC; 0 product lines | **124 lines** (102 non-blank); **0** product modules changed (sha256 before/after); its only product import is `contracts.body_intent`; 0 degrade violations in 30,000 ticks | **yes** |
| B9 | loop P99 ≤ today + 5 % | harness control loop, with/without, 3,000 ticks each: **44.440 → 44.440 ms P99 (+0.00 %)**; composer's own cost **44 µs** P99 per tick, **0.25 ms** P99 for a whole 50 Hz batch of five | **yes** |

## §B3 — the jerk row, in full

The limiter is a **pass-through limiter, not a tracker**: a signal already
inside its rate/accel/jerk bounds reaches the body untouched. On an exact
20 ms grid over 10 minutes (`results/limiter_bench.json`):

| axis | declared rate / accel / jerk | emitted d1 / d2 / d3 | passed through unchanged | band energy out/raw, 0–1 / 1–5 / 5–25 Hz |
|---|---|---|---|---|
| posture_dz | 0.10 / 2.0 / 100 | 0.044 / 0.47 / **17.5** | 99.03 % | 1.00 / 1.00 / 1.00 |
| posture_pitch | 0.50 / 10 / 500 | 0.137 / 6.85 / **342.9** | 99.88 % | 1.00 / 1.00 / 1.00 |
| gaze_yaw | 4.0 / 80 / 4000 | 4.000 / 80.00 / **4000.0** | 99.12 % | 0.995 / 0.970 / **0.185** |
| gaze_pitch | 4.0 / 100 / 5000 | 1.655 / 72.18 / **4907.5** | 98.93 % | 0.977 / 0.939 / **0.731** |

Read across: the two posture axes are spectrally *identical* to their input —
breathing and weight shifts are never touched. The limiter's whole effect is
on head yaw above 5 Hz, where it removes 81.5 % of the energy. That energy is
not motion anyone authored; it is the step discontinuities described under
"surprises" below.

Under wall-clock ticks the same code produced 19 over-bound windows in
597,700, in three groups, none of which is the limiter failing:

* **estop / gaze_yaw, 3 windows, 27.8×** — the single declared bypass.
  `compose(emergency=True)` snaps posture and gaze to zero in the same tick
  it commands HOLD, exactly as `ExpressionGate` mode `off` already clears the
  overlay and as `SCurveVelocityShaper.step(emergency=True)` documents for the
  velocity axis ("accel/jerk limits are intentionally ignored"). Reproduced
  offline: one snap lands inside exactly 3 four-sample third-difference
  windows, which is the count observed.
* **idle_look / gaze_yaw, 14 windows, ≤ 1.16×** and **navigating, 1 window,
  1.18×** — all on ticks where the axis was already rate-saturated at exactly
  4.000 rad/s. A divided difference of a jittered clock on a saturated axis
  reads high; the host's worst tick in that run was 85 ms against a 20 ms
  period. 3 of these 15 exceed the bound by more than 1 %.
* **idle_look / gaze_pitch, 1 window, 1.005×** — same cause, 0.5 % over.

I am reporting this row as **not met as measured**, because the criterion is
"within the declared bound" and 19 wall-clock windows are not. The limiter's
own arithmetic is exact and the jitter-free run shows it; the verifier should
decide whether a clock artifact and a documented stop bypass count against it.
Nothing was tuned to the bar.

## §B9 — loop cost

The pre-registered measurement is "the composer inside a harness copy of the
control loop cadence": a 10 Hz loop that fetches one observation over the
simulator socket (what `backend.observe()` does), runs the real smoother /
rotate-in-place rule / S-curve shaper / `finalize_command` / dispatch rule, and
times the body the way `component_metrics.observe_ms("ControlLoopWork", ...)`
does. 3,000 ticks per arm.

| arm | p50 | p95 | p99 | max | 1-min load at start |
|---|---|---|---|---|---|
| baseline | 11.94 ms | 34.48 ms | **44.440 ms** | 110.2 ms | 165 |
| + composer in the loop (5 ticks/tick) | 11.34 ms | 32.99 ms | **44.440 ms** | 68.5 ms | 221 |
| composer on its own 50 Hz thread | 7.32 ms | 15.79 ms | 18.24 ms | 23.3 ms | 103 |

The composer is **not detectable** in the loop: identical P99 (+0.00 %) even
though the in-loop arm ran at a *higher* host load than its baseline. The
thread arm's −59 % is a host-load artifact (103 vs 165), not evidence that a
thread is faster — the socket round trip dominates all three arms and this host
was carrying five other executors.

Two absolute numbers are what generalise off this host, both with the transport
replaced by a sink and n = 100,000:

* one `compose` + `adapter.apply`: **p50 28.6 µs, p99 44.4 µs, max 203 µs**;
* the loop body plus a full 50 Hz batch of five composer ticks minus the same
  loop body without them: **+0.143 ms p50, +0.252 ms p99** — 0.25 % of the
  10 Hz loop's 100 ms period.

A caveat I will not hide: that socket-free loop body costs only **15 µs P99**
on its own (a smoother, a shaper and `finalize_command` are a few dozen float
operations), so *as a percentage of it* the composer is +1705 %. The percentage
form of this criterion only means something against a real `ControlLoopWork`,
which also carries perception, navigation, the brain step, activities and the
duplex producer; the absolute 0.25 ms is the number to carry forward. I did not
measure the runtime's own `ControlLoopWork` P99 — reaching it means running
`RobotRuntime`, and the DESIGN puts `runtime.py` out of bounds.

## Surprises

1. **Today's expression stream contains step discontinuities.** Measured on
   the raw `ExpressionEngine` output at 50 Hz: head yaw reaches **28.9 rad/s**
   — a 0.58 rad jump inside one 20 ms tick — because `IdleLayer`'s
   `suppress_head` hands the head channel to `ReactionHooks`/`BeatLayer`
   instantaneously. Head pitch reaches 3.5 rad/s the same way. This costs
   nothing today (a Go2 has no neck, and in MuJoCo the overlay is decorative),
   but it is a *step command* to the first body that has a neck servo. It is
   the only thing the new limiter actually limits.
2. **The simulator drops expression frames under load, silently.** In the
   `idle_look` run, **58 of 29,713** messages (0.20 %) failed with
   `BlockingIOError` after three attempts, plus 133 that succeeded on retry,
   and 3 status polls failed. `PoseSocketServer` is one connection per message
   behind `listen(8)` and accepts at most `MAX_CLIENTS_PER_POLL = 4` per frame;
   at 50 Hz on a loaded host the backlog overflows. `ipc.send_message` never
   reads a reply and `_step_expression` swallows exactly this exception, so
   today the expression channel loses frames with no counter anywhere. First
   observed as a crash of my own harness, which is how it was found.
3. **The simulator cannot answer B5 on its own.** `place_kinematic_base`
   writes `qpos[:3]` every step, so the base pose reported over the status
   socket is pinned: the 0.000 m drift it reports proves the pin, not the
   posture. The physical answer came from a headless `mj_forward` +
   `subtree_com` probe, which is what the numbers in B5 are.
4. **`SCurveVelocityShaper` is the wrong reuse for this channel.** The first
   composer drove posture through the product's own shaper. It is a *velocity*
   tracker: applied to a position it bounds the second derivative, not the
   third, and its tracking dynamics ring — 25 % overshoot on a 4 mm step,
   which pushed `ExpressiveOffsets.clamped()` into clipping, and a clip is a
   step with unbounded jerk. Replaced with the pass-through limiter; the
   amplitude clamp has not bound since (0 events in 119,552 intents).
5. **The manifest cannot say "posture, but only two of its three axes".**
   A Go2's `Euler` carries pitch and roll; body height is a different,
   separately uncommissioned primitive. `BodyCapabilityManifest` has one
   `posture_offsets` flag, so `control/go2_sport_body_adapter.py` has to state
   it in a module constant (`POSTURE_AXES_SUPPORTED`) instead. Per the DESIGN's
   refutation clause this is the named missing axis — it did **not** require
   any product edit to support the fake body (B8 held), but the milestone
   design should widen the field to per-axis flags.

## Gates

`tests/test_h4_body_intent.py` — 11 cells, 0.61 s, all pass, run through
`~/.cache/parcel-guard/pytest_guard.sh --label h4` with `TMPDIR` unset. Both
decomposition ratchets re-run and green with the four new product modules in
the tree: `tests/test_dec0_debt_ratchet.py` + `tests/test_decig2_import_ratchet.py`,
23 cells, 32.9 s. `.parcel/bin/ruff check` clean on every file added (product,
research and test), zero `noqa`. No `ci_gate.py --tier`, no full suite, no
`-n auto`. Git untouched: nothing added, committed or stashed.

## Raw files

`results/state_{idle_hold,idle_look,navigating,estop}.json` (per-state
summaries) and `trace_*.json` (2 Hz intent traces; joint offsets are
`stance_joint_offsets(profile, posture)` and are reproducible from them),
`results/limiter_bench.json`, `results/com_probe.json`,
`results/portability_audit.json`, `results/loop_cost.json`,
`results/rows.json`, `logs/*.log`.

## Files added

Product (all inert — **zero call sites** outside the capability test and this
folder; grep for the module names over `src/ tests/ examples/ evals/ scripts/
tools/` returns nothing else):

* `src/parcel_robot/contracts/body_intent.py` (341) — `BodyIntentV1`,
  `Velocity`/`HOLD`, `BodyCapabilityManifest`, `degrade`, `dropped_axes`,
  `is_no_stronger_than`.
* `src/parcel_robot/motion/body_composer.py` (419) — the composer and its
  limiter.
* `src/parcel_robot/simulation/body_adapter.py` (166) — MuJoCo adapter.
* `src/parcel_robot/control/go2_sport_body_adapter.py` (163) — refusing stub;
  no vendor import at module or method scope.
* `tests/test_h4_body_intent.py` (352) — 11 cells, 0.6 s.

Research: `harness.py`, `loop_cost.py`, `limiter_bench.py`, `com_probe.py`,
`portability_audit.py`, `summarize.py`, `fake_quadruped_adapter.py`,
`run_states.sh`, `run_all.sh`.

## What this does NOT prove

Everything here is simulator and arithmetic. It says nothing about Go2 balance,
contact, foot placement, or whether Unitree Sport's `Euler` accepts these
offsets at all — `Go2SportBodyAdapter` refuses every method precisely because
none of that has been commissioned. B7's "byte-identical" is against a
*replica* of `_dispatch_active`'s send rule (`TodayPathShadow`, transcribed
from `runtime.py`), not against the runtime itself: the DESIGN forbids
touching `runtime.py`, so nobody has yet run this composer inside
`RobotRuntime`. B5 is a kinematic COM under `mj_forward`, not a support-polygon
or stability claim. B1 was measured on a host at load 94–171; a quieter host
would be better, not worse, but an Orin would be a different question. And the
fake quadruped is a fake: it proves the manifest is sufficient to *describe* a
different body, not that a real second robot would be satisfied by it.
