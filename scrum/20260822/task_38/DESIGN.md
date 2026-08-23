# HW-6 `stopping-envelope` — DESIGN (card `scrum/20260822/task_38`)

## (a) Purpose

HLD §8.8:1276-1279 says "short TTL is an evidence requirement, not a
convenient constant: worst-case candidate age, IPC delay, gateway
scheduling/watchdog period, vendor braking latency, and sensor/localization
uncertainty must fit inside the commissioned stopping envelope at the active
speed regime." Today `bridge/timing.py` derives the RC-4 table from
`ControlTiming` with two *assumed* pilot speeds and no measured term, and
nothing anywhere turns "the sum does not fit" into a red row. This card makes
the sentence executable: a typed input record with a per-term `UNMEASURED`
sentinel, a pure derivation, and one soft gate row that goes HARD-red only
when every term is measured and the ACTIVE regime's sum exceeds its envelope.
It measures nothing about the dog and claims nothing about it — three of the
five terms are box-day reads (`BOX_DAY_INPUTS.md`).

## (b) Architecture fit — seams, and who calls them

Seam row **S5** of `WAVE3_HW_DESIGN_FABLE.md` §4 (`bridge/{protocol,fake_
gateway,timing}.py`, class **VI (contract) / NEW (row)**), and §6's one
paragraph ("the RC-4 derivation is re-run with the measured numbers before
the leashed stage — that re-run is a gate row, not a note").

* `parcel_robot.bridge.timing:derive_envelope` — pure, no I/O, no clock. The
  arithmetic. Callable from the gate, from a future `Go2Backend`
  commissioning check (HW-12), and from a status doc.
* `parcel_robot.bridge.timing:load_stopping_envelope_record` /
  `:resolve_stopping_envelope_record` — the record reader and its host
  resolution. The only I/O this card adds to the product package.
* `scripts/ci_gate.py:evaluate_stopping_envelope` — the product-path caller
  **today**: it is what runs on every `--tier commit`. Registered in
  `COMMIT_TIER_STAGE_NAMES` and `run_commit_tier`'s tuple by the shape card
  GATE-0b used (`task_30/GATE0B_STATUS.md` §2, `ci_gate.py:2051-2056,
  2145-2150`), so `tests/test_ci_gate.py` — XD-1's file, not edited — keeps
  holding the tier to its declared stage list.
* On the dog the second caller is HW-12 `first-armed-step`, which may not
  `--arm` until this row is green with measured numbers. Not built here.

`bridge/timing.py` **must not import the commissioning package** (its own
rule, `timing.py:12-17`): every limit it needs is a mirrored constant pinned
by test against `commissioning.limits`, `ControlTiming`, `robot_profile` and
`configs/robot.yaml`, exactly like the existing `W0B_*` block.

## (c) The formula — every term as `module:symbol`, unit, source

```
required_travel_m(regime) =
      v_regime * ( t_candidate_age + t_ipc + t_gateway_period + t_stop )
    + d_localization
```

| Term | `module:symbol` | Unit | Source |
|---|---|---|---|
| `v_regime` | `bridge.timing:StoppingRegimeV1.speed_mps` | m/s | the regime table below |
| `t_candidate_age` | `…:StoppingEnvelopeInputsV1.candidate_age_s` | s | measurement record — age of the freshest robot state the writer can consult |
| `t_ipc` | `…:StoppingEnvelopeInputsV1.ipc_delay_s` | s | measurement record — client→gateway→ack round trip |
| `t_gateway_period` | `…:StoppingEnvelopeInputsV1.gateway_period_s` | s | measurement record — watchdog wake period under load |
| `t_stop` | `…:StoppingEnvelopeInputsV1.stop_command_to_standstill_s` | s | measurement record — the gateway ISSUING the stop command → standstill (settled **and** planted), never the vendor reaction delay alone |
| `d_localization` | `…:StoppingEnvelopeInputsV1.localization_jump_m` | m | measurement record — worst LIO `T_map_odom` jump (ISO/TS-15066 `Zr`; `authority.py:620` pins it at 0.0 today) |

**Why `v·t_stop` and not HLD C.6's `v²/(2·a_b)`.** C.6 (HLD:2211) splits
reaction from braking and needs a guaranteed deceleration `a_b`. Measuring
`a_b` on a stand needs an instrumented treadmill; measuring the *time from the
stop command to the stationary witness* needs the foot-force sensor we already
plan to use. With `t_stop` measured command-to-standstill it decomposes into
the vendor's reaction `t_vr` and the deceleration `t_d`, and

```
v·t_stop = v·t_vr + v·t_d  ≥  v·t_vr + ∫₀^{t_d} v(t) dt
```

for **any** profile with `v(t) ≤ v` — a rigorous upper bound, not merely a
constant-deceleration identity. The reserve is **not a flat factor of two**:
under constant deceleration the *deceleration* sub-part is covered 2×
(`v·t_d` vs `v·t_d/2 = v²/(2a_b)`), the *reaction* sub-part 1×. The one way
the form can under-count is overshoot — `v(t) > v` after the stop command, a
lurch — which risk (3) names. Stated here because it is the one place the
card is deliberately more conservative than the HLD, and because feeding it a
reaction-only number instead would silently drop the whole deceleration
distance (hence the field's name, §(c)).

**Footprint is counted exactly once.** `authority.py:CLEARANCE_CONVENTION`
is `base_center_to_obstacle_surface` and consumers "must not re-add the
footprint". Both sides of this comparison are *travel* distances, not
clearance rings: the envelope column subtracts the footprint from the ring
once (below), the required column never adds it.

## (d) The regimes and the stopping distance each allows

| Regime | `v` m/s | speed source | envelope m | envelope source |
|---|---|---|---|---|
| `one_axis` | 0.05 | `commissioning/limits.py:78 MAX_LINEAR_MPS` | 0.050 | `v × stop_timeout_s`; `configs/robot.yaml:119` = `ControlTiming.stop_timeout_s` = 1.0 s. W0-B's own derivation (`limits.py:52`, rendered by `timing.py:133-135`) bounds the whole step at `0.05×(1.0+1.0)=0.10 m`; the stop half of it is this row. |
| `leashed` | 0.15 | design §9 HW-12 / this card's README — **not a config value today** | 0.330 | `safety.obstacle_stop_m − footprint_radius_m` = `0.65` (`configs/robot.yaml:313`, `reactive_safety.py:31`) − `0.32` (`robot_profile.py:37`): the room between the ring where the reactive gate commands stop and the obstacle surface. |
| `restricted_free` | 0.25 | `patrol/mission.py:156 PatrolLimits.cruise_vx`, `configs/robot.prototype.yaml:286` — the speed the product actually commands on "go explore" | 0.330 | same ring |

Each regime also carries `modelled_travel_m = v·τ + v²/(2a)` with
`τ = 0.12 s` (`robot_profile.py:56`) and `a = 1.4 m/s²` (`:49`) — the
post-decision travel `SafetyEnvelope.stop_distance` *assumes*. It is printed
beside the measured sum and **is not part of the verdict**; it is there so
the reader can see how far the measured chain is from the planner's premise.

**Finding F1 (owner / design owner).** `WAVE3_HW_DESIGN_FABLE.md` §6 and §9
HW-12 say the first armed regime is "one-axis **0.10 m/s**". That number is a
**retired speed cap**: at `22c9721` (2026-08-03) `unitree_control.py:20-22`
carried `COMMISSIONING_MAX_LINEAR_MPS = 0.10` / yaw 0.25 / duration 2.0 — the
design's exact triple — and W0-B (`406f9d6`, 2026-08-13) replaced it with the
band `[0.02, 0.05]` m/s, yaw `[0.0625, 0.15625]`, step ≤ 1.0 s. (The
coincidence that `0.05 × 2.0 = 0.10 m` is W0-B's travel bound, `limits.py:52`,
is real but separate.) What the band refuses today: `vx = 0.10` →
`CommissioningRefusedError(OVER_LIMIT)` at `limits.py:466-470`;
`duration = 2.0` → `OVER_DURATION` at `:486-490`; and constructing
`CommissioningLimits(max_linear_mps=0.10)` → `ValueError` at `:249-252`
(three different refusals, only the last of which is a `ValueError`). The
regime table uses the code's 0.05 m/s and needs no change. `docs/MOTION.md:369`
still prints the retired triple — stale, and MUST-NOT-TOUCH for this card.
If the owner wants 0.10 m/s back, `commissioning/limits.py` needs its own
card; the table is one tuple, so that card changes one line.

## (e) UNMEASURED, and the three row states

`bridge.timing:UNMEASURED` is a typed singleton (`Unmeasured` enum member,
so `float | Unmeasured` type-checks and `is UNMEASURED` is the test) — never
`None`, never `0.0`, never `math.inf`. A `0.0` would make an unmeasured term
*help* the sum; `None` would be indistinguishable from a missing key. Every
term also carries a mandatory `provenance` string, so an UNMEASURED term
must say what will measure it.

| State | Condition | Row |
|---|---|---|
| `UNMEASURED` | ≥ 1 term is the sentinel | soft (`hard=False`, status `pass`), detail `UNMEASURED — <terms>`; no sum is printed as if it were a verdict |
| `FITS` | all measured, active regime `required ≤ envelope` | soft `pass` with the sum, the envelope and the headroom |
| `OVER` | all measured, active regime `required > envelope` | **HARD-red** (`hard=True`, status `fail`) naming the regime, the sum, the envelope and the overrun |

Non-active regimes are always printed and never gate — HLD says "at the
active speed regime", and a regime nobody has commissioned yet must not
block a commit. `active_regime` is a declared field of the record.

Status `pass` (not `report`) for the two soft states is deliberate and is
GATE-0b's precedent (`ci_gate.py:930-936`): `hard=False` is what makes a row
non-gating, and `tests/test_ci_gate.py:937` holds every stage of a clean
tier to `pass`.

## (f) The measurement record — where it lives and how it is found

`configs/envelope/<host>.yaml`, resolved by
`resolve_stopping_envelope_record()`: `$PARCEL_ENVELOPE_RECORD` →
`configs/envelope/<socket.gethostname()>.yaml` if present →
`configs/envelope/default.yaml` (tracked, all five UNMEASURED, so a fresh
clone and the hosted runner are green and honest). The Orin drops in
`configs/envelope/<orin-hostname>.yaml` on box day and changes no code.

Not `scrum/…/evidence`: the gate reads it on every commit run and the dog
will ship one, which makes it configuration, not a sprint artefact. It is
**not** a runtime asset — `tools/sync_runtime_assets.py:49-56` includes
`configs/` by explicit glob and `configs/envelope/*` matches none of them, so
release-parity's manifest walk (`ci_gate.py:1022-1027`, packaged tree only)
is untouched. Shape is fail-closed: exactly the five terms, each with
`value` (a non-negative finite float or the literal `UNMEASURED`) and
`provenance`; unknown or missing terms raise.

This box's record carries measured `candidate_age_s` and `ipc_delay_s` taken
through the real N24 fake-gateway process (AF_UNIX `SOCK_SEQPACKET`,
`bridge/fake_gateway_process.py` + `bridge/client.py`, the path
`tests/test_gateway_process.py` already exercises) and UNMEASURED for the
three box-day terms.

## (g) Hardware-compat §e — class VI (contract) / NEW (row)

Venue-independent by construction: the arithmetic is pure and takes every
physical fact from the record, so the same code renders an honest verdict on
this x86-64 box, on `ubuntu-latest`, and on the Orin. Must-configure: one
YAML per host. UNKNOWN until the box: all three box-day terms, and whether
the dog's `StopMove` damps at all when the head board is unplugged (Q-stop,
design §7) — the answer changes what `stop_command_to_standstill_s` even means. What
the desktop cannot prove: that the fake gateway's IPC delay resembles the
native gateway's, that a LIO jump is bounded, or that a Go2 stops in the time
Unitree's docs imply. The row says UNMEASURED for exactly those things.

## (h) Test strategy and seeds

Pre-registered rows in `PREREGISTRATION.md`. Arithmetic pinned term by term;
sentinel propagation (any one term UNMEASURED ⇒ state `UNMEASURED`, and the
missing list names it); the three row states proven **in-process** through
`ci_gate.evaluate_stopping_envelope` with a temp record file (rule 3: this
card runs no gate tier); the RC-4 rows and both rendered tables pinned
byte-identical BEFORE the region is written and again after; the mirrors
pinned against `commissioning.limits`, `ControlTiming`, `robot_profile` and
`configs/robot.yaml`. Seeds (scratch tree, never the working tree): S1 an
all-measured over-budget record on the shipped path must redden the
"shipped record is a soft UNMEASURED row" test; S2 dropping the
`d_localization` term from the formula must redden the arithmetic pin; S3 a
one-byte change to an RC-4 row must redden the RC-4 pin.

## (i) Risks / what this does not cover

1. `active_regime` is declared, not detected — a record could name a slow
   regime while the dog runs fast. Mitigated only by printing every regime's
   state; the real fix is HW-12 reading the commissioned regime from the
   commissioning record, which does not exist yet.
2. A deleted or malformed record downgrades the row to a **non-gating**
   `error` (GATE-0b's trade, `ci_gate.py:895-901`), not a red. The pin test
   in `tests/test_hw6_stopping_envelope.py` is what makes that a RED
   somewhere.
3. `v·t_stop` is an upper bound for any `v(t) ≤ v`, so the only way it
   under-counts is **overshoot** — a dog that lurches faster than `v` after
   the stop command before it settles. Nothing here models that, and B2's
   procedure would not see it either (it stamps endpoints, not the profile);
   a velocity trace from the same stand session would.
4. Nothing here touches `core/hard_stop`, the e-stop latch, TTLs, watchdog
   values, `commissioning/limits.py` values, `reactive_safety`, or
   `docs/MOTION.md`. The row is evidence about those numbers, not authority
   over them.
