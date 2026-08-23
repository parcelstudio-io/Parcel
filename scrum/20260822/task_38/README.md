# Task 38 — HW-6: `stopping-envelope` — the TTL derivation takes measured inputs and the gate says when the sum does not fit

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + anti-crash rules in `../BATCHB_DISPATCH_FABLE_4a.md`).
**Design:** `../WAVE3_HW_DESIGN_FABLE.md` §4 row S5, §6, §9 HW-6; HLD §8.8
("short TTL is an evidence requirement"). **Evidence:** `bridge/timing.py`
(`latency_derivation_rows`, `LatencyGateV1`, `W0B_MAX_TTL_S = 0.35`),
`docs/MOTION.md:158,357,441-442,491-492`, intent constraint "worst-case
candidate age + IPC delay + gateway watchdog period + vendor braking latency +
localization uncertainty must fit inside the commissioned stopping envelope".

## Why
The RC-4 derivation exists for the fake gateway with fixed inputs. On the dog
three of the five terms are measurements (braking latency of
`StopMove`/Damp, LIO jump magnitude, gateway period under load) and the
commissioned speed regime sets the envelope. Nothing today turns "the sum
does not fit" into a red gate row, so a bad measurement could be argued
past. This card is pure software: the derivation parameterised, a gate row,
seeds — and the box-day test plan for the inputs (Q-avoid, Q-stop).

## Work
1. `DESIGN.md` first: the envelope formula with every term named
   (`module:symbol`), units, and its SOURCE (config / measurement file /
   UNMEASURED placeholder); the commissioned regimes (one-axis 0.10 m/s,
   leashed ≤ 0.15, restricted free) and the stopping distance each allows
   (from `commissioning/limits.py` and `configs/robot.yaml` — cite); how an
   UNMEASURED input is represented (a typed sentinel that makes the row print
   `UNMEASURED — <which>` as a soft row, never a silent PASS) and what makes
   the row HARD-red (a measured sum that exceeds the regime's envelope).
2. `bridge/timing.py`: `StoppingEnvelopeInputsV1` (dataclass; measured
   values with provenance strings; `UNMEASURED` sentinel), `derive_envelope(
   inputs, regime) -> EnvelopeVerdictV1` (pure), keeping the existing RC-4
   rows byte-identical for the fake gateway (a pin test).
3. A measurement record file format `configs/envelope/<host>.yaml` (or
   under `scrum/…/evidence` — decide in DESIGN) with the dev-box file
   carrying UNMEASURED for the three box-day terms and the sim's measured
   values for the other two (measure them: candidate age and IPC delay on
   the N24 fake gateway path, `bridge/` tests already time them — cite).
4. `scripts/ci_gate.py`: ONE new marked `CARD HW-6 stopping-envelope` region
   adding a soft row `stopping-envelope` that prints the verdict per regime
   and goes HARD-red only when every input is measured and the sum exceeds
   the envelope; outside XD-1's three and GATE-0b's regions; the row appears
   in `run_commit_tier` via the same shape GATE-0b used (read its §11 note
   about registering a stage from a helper region).
5. Tests `tests/test_hw6_stopping_envelope.py`: arithmetic pinned; sentinel
   propagation; the gate row's three states; seeded: a 50 ms braking latency
   over budget reddens the row; the fake-gateway RC-4 rows unchanged.
6. Box-day test plan (doc, `task_38/BOX_DAY_INPUTS.md`): how each of the
   three terms is measured on a stand (foot-force sensor as the clock for
   braking; LIO jump from the B17 recording; gateway period under load),
   and the Q-avoid / Q-stop procedures from the design §7.

OWNS: `bridge/timing.py` (marked region; RC-4 rows unchanged), the new
config/evidence file, `scripts/ci_gate.py` `CARD HW-6` region,
`tests/test_hw6_*.py`, `task_38/` docs. MUST NOT TOUCH: `core/hard_stop`,
the e-stop latch, command TTLs/watchdog values, `commissioning/limits.py`
values, `reactive_safety`, any other card's region, `docs/MOTION.md`.

## Definition of done
Soft row printing UNMEASURED on this box; seeded over-budget reddens; RC-4
rows pinned unchanged; the box-day plan written; `HW6_STATUS.md` with
pre-registered rows. Gate runs: NONE by you (rule 3) — prove the row through
`evaluate_*` in-process with `run_pytest` untouched, as XD-1's verifier did.

## Hardware-compat (§e)
Class VI (contract) / NEW (row). Every box-day input named with its
measurement procedure; nothing assumes the sim's numbers hold on the dog.
