# AWARE-1 status — the periodic head turn (executor: Opus, 2026-08-23)

Baseline: `e15e466` + wave A uncommitted (PROX-1, SENSE-1, GATE-1). All four
deliverables landed plus the wave's three runtime wire-ins. Every runtime.py
edit is inside a `# ---- CARD AWARE-1` region; nothing else in the tree is mine
except the one named pin update.

## 1. The R28 axis table

`scrum/20260823/task_4/R28_AXIS_TABLE.md`. Written against the shipped code,
not against a proposal.

**The headline finding: R28's premise is already implemented — it had simply
never been written down**, which is why the concern was worth a page rather
than a refactor.

* `runtime.py:14048-14050` — a HOLD refuses translation by rebuilding the command as
  `VelocityCommand(vyaw=command.vyaw)`. **Yaw survives every HOLD today.**
* `runtime.py:11156` — `_input_health_latched` forces `HARD_STOP`, whose
  shaping zeroes **all axes**. The sibling `PROXIMITY_STOP` branch has to
  *say* `vyaw=gated_command.vyaw` precisely because the emergency branch does
  not.

So the two semantics R28 feared might be conflated are real and deliberate.
The table pins them, then adds the AWARE-1 column — what a *discretionary*
sweep may ask for, which is strictly narrower than what the gate permits.
Grounded in the complete real class list (2 HOLD, 10 latching per-input, 2
global, 4 source-ordering that reach the join as `payload_malformed`).

## 2. The awareness sweep

`src/parcel_robot/navigation/awareness_sweep.py` (new, 383 lines, whole file is
the marked region). In `navigation/` rather than `patrol/` because that is
where the `core.input_health` import is already precedented
(`reactive_safety.py:16`) and where PROX-1 put its module.

| line | symbol | what |
|---|---|---|
| 63 | `AWARENESS_CONFIG_KEY` | `"awareness"` |
| 86 | `PERMITTED_HOLD_FAULTS` | **the R28 allow-list**, as `(input, class)` PAIRS |
| 96 | `AwarenessProposal` | yaw only — **there is no `vx`/`vy` field to set** |
| 110 | `AwarenessLimits` | `enabled` / `idle_period_s` / `sweep_arc_rad` / `sweep_vyaw`, all validated |
| 171 | `awareness_limits_from_config` | reads the base-config section; refuses unknown keys |
| 226 | `awareness_yaw_permitted` | the executable R28 table |
| 261 | `AwarenessSweep` | cadence + bounded out-and-back arc, pure and clock-injected |

Three bounds, none of which is a safety device: **rate** (per-command, default
0.35 rad/s vs the patrol's 0.8), **arc** (total commanded angle per sweep), and
**cadence** (idle period between sweeps). The behaviour cannot propose
translation structurally, not by discipline.

**Measured end-to-end through the real 10 Hz control loop** (fake backend, 3 s,
`idle_period_s=0.5`, `arc=0.7`): 14 commands reached the actuator, **all 14
yaw-only, zero translation ever commanded**, one sweep started and completed,
zero refusals. The intermediate values (0.1697, −0.1904, −0.0103) are the
velocity smoother ramping — i.e. it went through the full shaping/gating path.

### Two corrections the measurements forced

1. **The arc bound overran by one tick.** Stopping at `swept >= arc` still
   commands one more tick's worth, because a proposal is held until the next
   tick. Now it stops when another tick *would* cross. Measured: commanded arc
   exactly 1.4 against a 1.4 bound, on three different (arc, rate, dt) triples.
2. **Rule D would have made the feature dead on arrival.** The first draft
   forbade the sweep under any `controller_feedback` HOLD. Measuring it on a
   real runtime showed it could then *never start*: a stationary runtime
   publishes no motion state (the buffer is filled inside `_dispatch_active` /
   `_collision_safe`, both of which need a command to run), so feedback appears
   one tick *after* the first command — the sweep would need motion in order to
   be allowed to propose motion. Rule D now splits: `missing` permits (a robot
   at rest), `stale` forbids (a controller that answered and then stopped,
   which is what a dying controller produces mid-sweep). Recorded in the table
   as the row corrected by measurement.

## 3. Marked-region map

| file:line | region | what |
|---|---|---|
| `runtime.py:184-194` | import | the proposer + the R28 predicate |
| `runtime.py:216-225` | import | PROX-1's context seam |
| `runtime.py:478-486` | constant | `AWARENESS_TICK_S = 0.25` (:485) |
| `runtime.py:1805-1846` | **PROX-1 wire-in** | `ProximityContextOwner` (:1829) + the venue read |
| `runtime.py:2085-2098` | `__init__` state | limits (:2089), sweep (:2094), counters |
| `runtime.py:5612-5754` | the behaviour | `_awareness_idle` (:5625), `_step_awareness` (:5657), `awareness_snapshot` (:5708), `set_proximity_context` (:5725), `proximity_snapshot` (:5743) |
| `runtime.py:10704-10712` | control loop | `_step_awareness(observation)` (:10710), below roam |
| `runtime.py:14156-14194` | **SENSE-1 wire-in** | `pose_evidence_source` read at the join (:14188) |

No new lock, no new arbiter source, no gate touched. `patrol/mission.py` and
`reactive_safety.py` are **byte-unchanged** — the proposer reuses the patrol's
*lesson*, not its types.

## 4. PROX-1 wire-in — and the defect it avoided

`runtime.py:1805-1846`. A profile is applied at build **only when the venue
names a context**; every other deployment keeps the policy constructed above it,
byte for byte.

**Why conditional, measured not assumed.** PROX-1's `default` rung is derived
from the shipped envelope (1.2 / 2.5). Applying it unconditionally would have
*overwritten* a deliberately retuned deployment:
`configs/robot.prototype.yaml:197` commissions `person_stop_m: 0.7` under a
recorded owner authorisation, and `tests/test_prototype_profile.py:886` pins
that the runtime reports it. The result would have been
`runtime.person_stop_m` reading 0.7 while the gate enforced 1.2 — the reported
and the enforced distance silently disagreeing, which is worse than either
number alone. Measured: `go2_edu_plus` → `indoor` (0.95 / 2.00); no venue →
`plain.reactive_safety_policy is owner.base_policy`.

`set_proximity_context` (:5725) stays reachable for the later reasoning-model
tool and takes a preregistered NAME only — `set_proximity_context(0.4)` is a
`TypeError` and the active policy is unchanged after the refusal.

**Carried forward from PROX-1's handoff, unchanged and named:**
`owner_follow.owner_keepout_m` does not follow a context switch (follow stays
wider than required — safe), and `headless_city.py:1025` is a second
construction site that would need the same treatment for parity.

## 5. SENSE-1 wire-in + the one pin update

`runtime.py:14156-14194`, its own region adjacent to HW-2's, not folded into it.

**One deliberate difference from the scan seam**, and it is not an oversight.
HW-2 may only ever *re-stamp* a scan the observation has (`scan is not None`).
A pose is the other way round — one is stamped unconditionally — so a
declared-PHYSICAL pose source is **authoritative**: its answer replaces the
stamp, and its `None` becomes `pose:missing` → recoverable HOLD. Keeping the
observation's SIMULATION stamp there would latch `sim_fixture_forbidden` on a
real dog whose DDS stream merely skipped a sample, and it is exactly the row
SENSE-1 measured (`test_a_pose_the_source_has_no_datum_for_holds_and_never_stubs`).

### PIN UPDATE — `tests/test_hw2_go2_backend.py::test_b3_pose_authority_is_not_in_this_card`

**Cause:** the row measured the ABSENCE of the pose seam. SENSE-1 built the
seam but could not read it at the join (`runtime.py` was that card's
MUST-NOT-TOUCH); its STATUS deviation 1 names this row as the one that moves
when someone lands the wiring. AWARE-1 landed it.

**Before:** `LATCHED_STOP`, `pose:sim_fixture_forbidden` + `controller_feedback:missing`.
**After (measured):** the pose fault is gone entirely; `controller_feedback:missing`
remains; verdict is `HOLD`, `stop_latched is False`, translation still refused.

The function NAME is kept deliberately: `core/input_health.py:491` and
`backends/go2.py:880` both cite it by name and are SENSE-1's files, not mine.
This is the only edit I made outside my OWNS.

**No other pin moved.** `test_r24_lock_discipline` and
`test_nominal_stop_wiring` are green with no re-pin: I added no lock, and my
regions are outside every symbol in `STOPPING_PREDICATE_PIN`
(`_dispatch_active`, `_finalize_for_actuator`, `_nominal_stop_ramp_tick`,
`_regate_nominal_stop`, `_is_zero_command`, `_finite_command_values`,
`_command_translates`).

## 6. Tests

`tests/test_aware1_head_turn.py` (new, 587 lines) — **47 passed**, capability
tests only: cadence, the arc bound, the heading a sweep leaves behind,
suppression abandoning rather than pausing, the config loader's refusals, the
R28 table against the real classes (36 parametrised latching rows + the HOLD
split), the sweep reaching the arbiter as a yaw-only voice intent, clean
refusal when the body is held at higher priority, R28 suppression on the
product path, the PROX-1 venue rows, and the pose seam **through the runtime
join**.

Through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label aware1`,
never `-n auto`, never `ci_gate.py --tier`, one suite at a time:

* required set — **182 passed**: `test_aware1_head_turn`, `test_hw2_go2_backend`,
  `test_prox1_proximity_profiles`, `test_sense1_mount_readiness`,
  `test_r24_lock_discipline`, `test_nominal_stop_wiring`.
* no-regression neighbours — **408 passed**: `test_prototype_profile`,
  `test_hw5_physical_profile`, `test_e2_safety_wiring`, `test_runtime`,
  `test_release_parity`, `test_authority_config_drift`, `test_hw3_mid360_band`,
  `test_p1e_social_zone_is_config`, `test_door1_doorway`, `test_e6_owner_band`,
  `test_import_order_no_cycle`.

Ruff: my files clean, **no `noqa` added**, baseline still exactly 7
fingerprints. The 12 repo-wide `ruff check .` findings are all pre-existing, in
`detection_adapter/` and `camera_channel/`, which I never touched.

## 7. Deviations — two, both forced, both with precedent this wave

1. **`configs/robot.yaml` was NOT modified — blocked, needs owner
   authorisation.** The card asks for base-config awareness keys. That file is
   SHA-locked: its digest `f7b57dcd…` is pinned in
   `evals/companion/embodied_plan_v1/manifest.json` `robot_config` and
   `tests/test_hw5_physical_profile.py:69`, cascading to `ci_gate.py`
   `DIGEST_SENTINELS`, whose re-pin protocol requires explicit owner
   authorisation plus re-measured embodied-plan rows plus a dated log entry.
   The overlay escape hatch is `OVERLAY_INTRODUCIBLE_KEYS` in `config.py`,
   which is this card's MUST-NOT-TOUCH — so no overlay can introduce the
   section either. **PROX-1 hit this identical wall this wave**, measured the
   two reds and reverted; this is the same open owner decision, not a second
   one. The limits therefore ship as validated code defaults, and
   `awareness_limits_from_config` reads `awareness` the moment it exists.
   The exact block, proven loadable, is `PROPOSED_AWARENESS_BLOCK` in
   `tests/test_aware1_head_turn.py`.

2. **The feature ships DEFAULT OFF (`AwarenessLimits.enabled = False`),** and
   this is the decision most worth the owner's attention. The shipped base
   config is a locked input to the `embodied_plan_v1` eval (997 steps, minimum
   clearance 0.883147 m), and that eval has idle stretches: a robot that turned
   itself during them would move a digest-pinned row silently — the exact
   baseline drift the re-pin protocol exists to prevent. **Turning it on is a
   one-line default flip plus a re-measured eval row**; the mechanism is landed,
   proven end-to-end, and hardware-ready. On today's hardware the backend
   refuses motion regardless, so nothing visible is being withheld this week.

## 8. Notes for the integrator

* `CODEBASE_INDEX.md` is stale (two new files). Not regenerated — the card
  assigns that to the close-out.
* No new arbiter source: the sweep rides `"voice"` (priority 60), the channel
  roam already rides, so `core/commands.py` is untouched. An owner at `manual`
  (80) outbids it, which is the refusal path and is measured.
* `awareness_snapshot()` and `proximity_snapshot()` are new public reads for
  the panel; neither is wired into `web_panel.py`, which is not my OWNS.
* The one thing this does not prove: any of it on a robot. No stop distance, no
  yaw rate under load, no D455 re-acquisition time, and nothing about whether a
  real quadruped's turn-in-place holds its centre well enough for the R28
  table's rule B. That row is flagged in the table as the one to re-measure on
  hardware before it is trusted.
