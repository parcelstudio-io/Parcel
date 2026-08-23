# HW-6 `stopping-envelope` — executor status (Claude Opus, 2026-08-23)

Card `scrum/20260822/task_38/README.md` · design `../WAVE3_HW_DESIGN_FABLE.md`
§4 S5, §6, §9 · `DESIGN.md` · `PREREGISTRATION.md`
(sha256 `fcf68a29db1f5d9938ae9e16a961907cbd35d5435aade58924f3904b69ec5639`,
byte-unchanged since it was written) · `BOX_DAY_INPUTS.md`.

## Headline

HLD §8.8's sentence — "worst-case candidate age, IPC delay, gateway
scheduling/watchdog period, vendor braking latency, and sensor/localization
uncertainty must fit inside the commissioned stopping envelope at the active
speed regime" — is now **executable and gated**. `bridge/timing.py` gained a
pure derivation with a typed `UNMEASURED` sentinel; `configs/envelope/*.yaml`
is where a host writes down what it has measured; `scripts/ci_gate.py` gained
one **soft** commit-tier row, `stopping-envelope`, registered the way card
GATE-0b registered `skip-list` and **without one byte of edit to
`tests/test_ci_gate.py`** (XD-1's file — 91 passed, `git diff` empty).

On this box the row prints, in the commit tier:

```
UNMEASURED — gateway_period_s, stop_command_to_standstill_s,
localization_jump_m (record jaewoo-jang-parcel.yaml, host jaewoo-jang-parcel); no verdict is
claimed until every term is measured
    ACTIVE one_axis @ 0.05 m/s, envelope 0.050 m: UNMEASURED - …
           leashed @ 0.15 m/s, envelope 0.330 m: UNMEASURED - …
           restricted_free @ 0.25 m/s, envelope 0.330 m: UNMEASURED - …
```

and it goes **HARD-red** only when every term is measured and the ACTIVE
regime's sum exceeds its envelope. The card's seed is proved exactly as
written: a record at `restricted_free` with 0.450 s of vendor braking latency
fits with **6.25 mm** to spare, and **+50 ms of braking latency reddens it**
by the same 6.25 mm (0.25 m/s × 0.050 s = 12.5 mm of travel, the full swing).

**Rows: 24 pre-registered, 24 MET** (A1-A4, B1-B5, C1-C7, D1-D4, seeds
S1-S3, F1), one with a declared deviation in its command text (D1 — the
measurement lives in the OWNS test file instead of a new `tools/` script).
No gate tier was run by this card (anti-crash rule 3). Every one of the
**23 guarded runs** went through `pytest_guard.sh --label hw6`; zero `-n` on
any command line; zero exit 137.

## 1. The formula, and every number in it

```
required_travel_m(regime) = v · (t_candidate + t_ipc + t_period + t_braking)
                          + d_localization
```

| term | `module:symbol` | unit | source |
|---|---|---|---|
| `v` | `bridge.timing:StoppingRegimeV1.speed_mps` | m/s | regime table |
| `t_candidate` | `:StoppingEnvelopeInputsV1.candidate_age_s` | s | record |
| `t_ipc` | `:…ipc_delay_s` | s | record |
| `t_period` | `:…gateway_period_s` | s | record |
| `t_stop` | `:…stop_command_to_standstill_s` | s | record |
| `d_localization` | `:…localization_jump_m` | m | record |

`v·t_stop` replaces HLD C.6's `v²/(2 a_b)` on purpose. With `t_stop`
measured **command-to-standstill** it decomposes into the vendor's reaction
`t_vr` and the deceleration `t_d`, and `v·t_stop = v·t_vr + v·t_d ≥ v·t_vr +
∫v(t)dt` for **any** profile with `v(t) ≤ v` — a rigorous upper bound, not
merely a constant-deceleration identity. The reserve is **not a flat factor
of two** (verifier N3): the deceleration sub-part is covered 2×, the reaction
sub-part 1×. The one way it can under-count is overshoot — a lurch above `v`
after the stop command — which `DESIGN.md` risk (3) names. Bought in exchange
for never having to measure `a_b` on a stand.

The footprint is counted **once**: both sides are travel distances, and the
envelope column is the one that subtracts it (`authority.py:
CLEARANCE_CONVENTION` = `base_center_to_obstacle_surface`).

### The three regimes (pinned, `-k regimes` / `-k mirrors`)

| regime | `v` m/s | speed source | envelope m | envelope source |
|---|---|---|---|---|
| `one_axis` | 0.05 | `commissioning/limits.py:78 MAX_LINEAR_MPS` | 0.050 | `v × stop_timeout_s` (`configs/robot.yaml:119` = `ControlTiming.stop_timeout_s` = `limits.py DEFAULT_MAX_DURATION_S` = 1.0) |
| `leashed` | 0.15 | design §9 HW-12 — **no config source today** | 0.330 | `safety.obstacle_stop_m 0.65` (`configs/robot.yaml:313`, `reactive_safety.py:31`) − `footprint_radius_m 0.32` (`robot_profile.py:37`) |
| `restricted_free` | 0.25 | `patrol/mission.py:156 PatrolLimits.cruise_vx`, `configs/robot.prototype.yaml:286` | 0.330 | same ring |

Each regime also reports `modelled_travel_m = v·τ + v²/(2a)` (τ = 0.12 s, a =
1.4 m/s², `robot_profile.py:56,49`) — what `SafetyEnvelope.stop_distance`
assumes — printed beside the measured sum and **never** part of the verdict.
At `restricted_free` the model assumes 0.052 m; the seeded measured chain
needs 0.324 m. That gap is the finding the row exists to surface.

### Finding F1 — the design's "one-axis 0.10 m/s" is a RETIRED speed cap

`WAVE3_HW_DESIGN_FABLE.md` §6 and §9 (HW-12) say the first armed regime is
"one-axis **0.10 m/s**". The verifier traced it: at `22c9721` (2026-08-03)
`unitree_control.py:20-22` carried `COMMISSIONING_MAX_LINEAR_MPS = 0.10`, yaw
0.25, duration 2.0 — the design's exact triple — and W0-B (`406f9d6`,
2026-08-13) replaced it with the band `[0.02, 0.05]` m/s, yaw
`[0.0625, 0.15625]`, step ≤ 1.0 s. My first reading (that 0.10 was only the
`0.05 × 2.0 = 0.10 m` travel bound of `limits.py:52`) was half the story: the
travel-bound coincidence is real, but 0.10 m/s was also a real cap once.

What the band refuses **today** (corrected cites, verifier N7 — three
different refusals, only the last a `ValueError`): `vx = 0.10` →
`CommissioningRefusedError(OVER_LIMIT)` at `limits.py:466-470`;
`duration = 2.0` → `OVER_DURATION` at `:486-490`; constructing
`CommissioningLimits(max_linear_mps=0.10)` → `ValueError` at `:249-252`.
Admitted: 0.05 m/s, 0.15625 rad/s, 1.0 s.

**Owner / design owner:** HW-6's regime table uses 0.05 m/s and needs no
change. The design's §5.5:257, §6:339-340, §8:391 and §9:418 carry the
retired triple, and `docs/MOTION.md:369` still prints it (stale;
MUST-NOT-TOUCH for this card). If 0.10 m/s is wanted back,
`commissioning/limits.py` needs its own card — the regime table is one tuple,
so that card changes one line here.

## 2. What changed

`git diff --stat` (index vs working tree — this wave's edits only, per the
dispatch's tree-state note):

| file | diff | in `CARD HW-6` regions |
|---|---|---|
| `src/parcel_robot/bridge/timing.py` | **+468 −0** | 467 in 2 fenced hunks (a 15-line import fence with an inline END, and the 452-line region at the bottom) |
| `scripts/ci_gate.py` | **+142 −0** | 140 in 3 fenced hunks (the evaluator; the `COMMIT_TIER_STAGE_NAMES` entry; the `run_commit_tier` entry) |

(Counts after the correction pass of §9; the executor pass landed +442 / +133.)

Purely additive in both: **zero deleted lines**, and the RC-4 derivation is
byte-identical (§3, row A). New files:

* `tests/test_hw6_stopping_envelope.py` (738) — 30 tests (27 before §9's F1).
* `configs/envelope/default.yaml` (55) — the tracked fallback: all five terms
  UNMEASURED, so a fresh clone and `ubuntu-latest` get an honest soft row.
* `configs/envelope/jaewoo-jang-parcel.yaml` (51) — this box: two measured,
  three UNMEASURED.
* `scrum/20260822/task_38/{DESIGN,PREREGISTRATION,BOX_DAY_INPUTS}.md`, this doc.

Seams, by `file:symbol`:

* `bridge/timing.py:UNMEASURED` / `Unmeasured` — one typed sentinel (an Enum
  member, so `float | Unmeasured` is checkable and `is UNMEASURED` is the
  test). Never `None`, never `0.0` (which would let an unmeasured term HELP
  the sum), never `inf` (which would red every row until someone deleted it).
* `…:StoppingEnvelopeInputsV1` — the five terms, each with a **mandatory**
  provenance string, plus `active_regime` / `host` / `source`. Frozen, slots,
  validated at construction.
* `…:derive_envelope(inputs, regime) -> EnvelopeVerdictV1` — pure: no clock,
  no I/O. Three states: `UNMEASURED` (and `required_m is None` — no number is
  produced at all), `FITS`, `OVER`. The comparison is a plain `<=` with **no
  epsilon**: an epsilon on a safety envelope is a silent loosening, and the
  last value that fits is the one that lands exactly on it (pinned with
  `math.nextafter`).
* `…:resolve_stopping_envelope_record` / `load_stopping_envelope_record` —
  `$PARCEL_ENVELOPE_RECORD` → `configs/envelope/<hostname>.yaml` →
  `configs/envelope/default.yaml`. The Orin drops in a file and changes no
  code. Shape is fail-closed (exactly five terms, each `{value, provenance}`).
* `scripts/ci_gate.py:evaluate_stopping_envelope` — `hard=False` in both soft
  states so `GateResult.gating_red` is False by construction; `hard=True,
  status="fail"` only in `OVER`. Status `pass` (not `report`) for the soft
  states, for the reason GATE-0b wrote down: `hard=False` is what makes a row
  non-gating, and `tests/test_ci_gate.py:937` holds every stage of a clean
  tier to `pass`. No subprocess, no pytest, no import of the test tree; one
  ~2 kB YAML read and a pure call.

**How the stage was registered** (the card asked this explicitly). Exactly
GATE-0b's shape, read from `task_30/GATE0B_STATUS.md` §2/§11 first:
`"stopping-envelope"` is added to `COMMIT_TIER_STAGE_NAMES` **and** to
`run_commit_tier`'s stage tuple, in the same position in both (after
`tier-coverage`, before the targeted pytest stages — a 2 kB file read that
can hard-fail belongs before the 400 s suite). Both edits sit in their own
`# ---- CARD HW-6 …` fences, **outside** XD-1's three regions (`:551-560`,
`:603-791`, `:2129-2144`) and outside GATE-0b's four. Because
`tests/test_ci_gate.py` imports that literal and compares it against what
`run_commit_tier` produces, the stage list stays pinned and **the test file
needed no edit at all** — `git diff -- tests/test_ci_gate.py` is empty and 91
tests pass. `test_the_stage_is_registered_the_way_gate_0b_registered_its_own`
asserts all of that from the source text, without running a tier.

**Containment asymmetry, declared.** `run_commit_tier`'s loop passes
`hard=stage_name != "skip-list"` to `run_stage`; that line is inside GATE-0b's
region and is not mine to edit, so an *uncaught* crash in my evaluator would
be reported as a hard ERROR row even though the row itself is soft. Every
expected failure (missing file, bad YAML, bad shape) is caught and returned
as a non-gating `error`; what is left is a defect in the gate, and a defect in
the gate should be loud. Written into the region's comment.

## 3. How verified — every command and its result

All through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw6
.parcel/bin/python -m pytest …`. `PY` below = `.parcel/bin/python`.

### A — the RC-4 derivation did not move (written and run BEFORE the edit)

| row | command | result |
|---|---|---|
| A1 | `PY -m pytest tests/test_hw6_stopping_envelope.py -q` — the RC-4 pin, written first, run **before `timing.py` was touched** | **1 passed** (ledger 13:02:23; the pre-edit pair is 13:02:23 and 13:05:19). Both rendered tables' sha256 recorded in the test: `466cad1f…` (latency) / `2a2927d5…` (H2) |
| A2 | same, after the region landed | **MET** — same shas, 27 passed in the final run |
| A3 | `PY -m pytest tests/test_gateway_protocol_v1.py -q` | **24 passed** before the edit, **24 passed** after |
| A4 | `test_rc4_document_contains_the_executable_table` (inside A3) | pass; `git diff --stat -- docs/` **empty** |

### B — the arithmetic

| row | result |
|---|---|
| B1 | MET — every term's contribution equals the hand value to 1e-12, and the distance term is proved NOT to scale with speed |
| B2 | MET — the three regimes carry 0.05/0.050, 0.15/0.330, 0.25/0.330 |
| B3 | MET — mirrors equal `limits.MAX_LINEAR_MPS`, `ControlTiming().stop_timeout_s` and `configs/robot.yaml control.stop_timeout_s`, `ReactiveSafetyPolicy().obstacle_stop_m` and `safety.obstacle_stop_m`, `DEFAULT_ROBOT_PROFILE.{footprint_radius_m,reaction_latency_s,decel_max_mps2}`, `PatrolLimits().cruise_vx` |
| B4 | MET — each of the five terms alone poisons the verdict and names itself; `required_m is None`; the sentinel is not `None`, not `0.0` |
| B5 | MET — 7 parametrised shapes refused (`schema`, missing term, unknown term, wrong entry keys, negative value, unknown regime, non-mapping); the literal `UNMEASURED` round-trips to the sentinel |

### C — the gate row's three states, proved IN-PROCESS (no tier run)

| row | result |
|---|---|
| C1 | MET — `hard=False`, `status="pass"`, detail starts `UNMEASURED — gateway_period_s, stop_command_to_standstill_s`, all three regimes printed |
| C2 | MET — `FITS` prints required / envelope / headroom for every regime |
| C3 | **MET, the card's seed** — 0.450 s fits with 6.25 mm spare; **0.500 s → `hard=True`, `status="fail"`, `gating_red=True`, over by 6.25 mm**; the swing equals 0.25 m/s × 0.050 s exactly |
| C4 | MET — with `active_regime: leashed`, the same 0.500 s fits the leash (0.282 m of 0.330 m) while `restricted_free` is OVER (0.336 m): row stays soft, and the OVER regime is still printed |
| C5 | MET — absent file → `error`, `hard=False`, `FileNotFoundError` named; bad schema → `error`, `hard=False` |
| C6 | MET — both tracked records load; this host's row is `hard=False`/`pass`/`UNMEASURED` with exactly `{gateway_period_s, stop_command_to_standstill_s, localization_jump_m}`. (Registered wording listed those three in a different order; the set is what was asserted — the printed order is HLD order.) |
| C7 | MET — `"stopping-envelope"` in `COMMIT_TIER_STAGE_NAMES` and in `run_commit_tier`'s tuple, both inside HW-6 fences and outside every other card's; `tests/test_ci_gate.py` **91 passed**, file byte-unchanged |

### D — the two terms this box can measure

Through the **real** N24 process (`python -m
parcel_robot.bridge.fake_gateway_process` over AF_UNIX `SOCK_SEQPACKET`,
driven by `bridge/client.py:FakeGatewayClientV1`) — the path
`tests/test_gateway_process.py` already spawns. Nothing stubbed, nothing
monkeypatched. `PARCEL_HW6_SAMPLES=2000`, three runs:

| run | `ipc_delay_s` p99 | median | `candidate_age_s` p99 | median |
|---|---|---|---|---|
| 1 | 302.1 µs | 192.4 µs | 1.652 µs | 1.09 µs |
| 2 | **328.5 µs** | 215.5 µs | **1.763 µs** | 1.31 µs |
| 3 | 308.6 µs | 184.0 µs | 1.732 µs | 1.10 µs |

Recorded: `ipc_delay_s: 0.000329`, `candidate_age_s: 0.0000018` — the **worst
of the three**, because the sentence asks for the worst case. D3 MET (both
provenance strings name the command, the sample count, the date and the three
runs; the three box-day terms stay `UNMEASURED`). D4 MET (§4 below).

A 300-sample run in the same session showed a p99 of 354 µs — a p99 over 300
samples is the 3rd-worst value, so the recorded number is **not a ceiling**;
the protocol is part of the claim and the provenance says so.

### E — seeds, RED then green, on a scratch copy only

`~/.cache/parcel-hw6/scratch` (`rsync -a --exclude .cache --exclude .parcel
--exclude .git` of `src/ scripts/ tools/ tests/ configs/ prompts/` +
`pyproject.toml` for `[tool.pytest.ini_options]`), run with
`PYTHONPATH=<scratch>:<scratch>/src`; import verified inside the scratch
(`parcel_robot from: …/scratch/src/parcel_robot/__init__.py`, `ci_gate REPO:
…/scratch`). **The working tree was never seeded.** Control run: 27 passed.

| seed | what was changed in the scratch | result |
|---|---|---|
| S1 | the host record replaced by an all-measured OVER-budget one | `test_the_shipped_records_are_valid_and_this_host_reads_as_unmeasured` **FAILED**; restored by sha (`2785eb26…` before and after) → **1 passed** |
| S2 | `+ d_localization` deleted from `derive_envelope` | `test_the_envelope_arithmetic_is_pinned_term_by_term` **FAILED** (and `…row_state_fits…` with it) |
| S3 | RC-4 `proposed_p99_ms` 100.0 → 101.0 | `test_the_rc4_rows_and_rendered_tables_are_byte_identical` **FAILED** |

`timing.py` restored byte-identically after S2/S3 — sha
`40fff6318258661928eab274c70614bfd30b2e42f6296af7dd0289ee12ae6137` before the
seeds, after the restore, and in the working tree. `__pycache__` purged
between every step; final scratch run **27 passed**.

### F — lint

`.parcel/bin/ruff check src/parcel_robot/bridge/timing.py scripts/ci_gate.py
tests/test_hw6_stopping_envelope.py` → **All checks passed!**
`scripts/ci_ruff_baseline.json` byte-unchanged; **zero `noqa` added**
anywhere (`git diff | grep -c '^+.*noqa'` = 0). Two ruff findings were fixed
at the source during the pass, not suppressed: `TRY004` (three shape checks
now raise `TypeError`) and `RUF046`.

### Closing run

`PY -m pytest tests/test_hw6_stopping_envelope.py tests/test_ci_gate.py
tests/test_gateway_protocol_v1.py tests/test_w0b_commissioning.py
tests/test_fake_sport_gateway.py tests/test_gateway_process.py -q
--deselect tests/test_ci_gate.py::test_tier_coverage_is_green_against_the_real_tree`
→ **233 passed, 1 deselected, 7.86 s**. The one deselected row is H2 below
(HW-3's uncollectable module), not this card's.

### Guard ledger

**23 guarded runs** in the executor pass (plus 5 in the correction pass, §9), label `hw6`, all `mem=40G`; no `-n` on any command line;
no `-n auto` refusal; **no rc=137**. Nine `rc=1`/`rc=2` entries are accounted
for: three seeded REDs (S1/S2/S3), one seeded-RED control (S1's first form),
four self-inflicted fixes during development (ack disposition, C4's premise,
GATE-5 text guard, HW-3's collection error), one `--collect-only` diagnosis.

## 4. What this does not prove

1. **Nothing about the dog.** Three of the five terms are UNMEASURED and the
   row says so on every run. `BOX_DAY_INPUTS.md` is the plan, not a result.
2. **The two measured numbers are dev-box numbers.** `ipc_delay_s` is a
   Unix socket between two CPython processes on a 192-thread x86-64 desktop,
   not the Orin's socket to a native gateway. `candidate_age_s` (1.8 µs) is
   an artefact of the fake sport service refreshing its state on every
   command — **on the dog it is a 50 Hz publisher, so ~20 ms**, four orders
   of magnitude larger. It is recorded as a floor with that written into its
   provenance, and it must be replaced, never scaled.
3. **`leashed`'s 0.15 m/s has no source in the tree** — it is a design
   intent (§9 HW-12) and the table is the first place it is written down.
4. **`active_regime` is declared, not detected.** A record could name a slow
   regime while the robot runs fast. The row prints every regime's state,
   which is mitigation, not a fix; the fix is HW-12 reading the commissioned
   regime from the commissioning record, which does not exist yet.
5. **A deleted record is a non-gating `error`, not a red** — GATE-0b's trade.
   `test_the_shipped_records_…` is what makes a broken *shipped* record red.
6. **No gate tier was run.** The row is proved by calling
   `evaluate_stopping_envelope` in-process. Whether the commit tier as a
   whole is green is the integrator's measurement, not mine.
7. Nothing here touched `core/hard_stop`, the e-stop latch, TTLs, watchdog
   values, `commissioning/limits.py` values, `reactive_safety`, `docs/`, or
   any other card's region.

## 5. Deviations (declared)

1. **D1's command text.** The pre-registration wrote
   `tools/measure_envelope_inputs.py`. `tools/` is not in this card's OWNS, so
   the measurement lives in `tests/test_hw6_stopping_envelope.py:
   measure_n24_envelope_inputs` instead, run as
   `PARCEL_HW6_SAMPLES=2000 pytest …::test_the_two_dev_box_terms_are_
   measurable_on_the_n24_path`. Same code path, same sample count, and it now
   also runs (at 300 samples, with sanity-only bounds) in the default suite,
   so the measurement path cannot rot.
2. **`DESIGN.md` is 213 lines** (191 before §9's corrections) against the brief's ≤ 150 target. It carries
   three tables the card asked for by name (every term with unit and source;
   the regimes with their envelopes and citations; the three row states) plus
   finding F1. Cutting it would have cut cited numbers.
3. **The F2 rename moves a registered literal.** Rows C3/C6 of
   `PREREGISTRATION.md` name `braking_latency_s`; the field is now
   `stop_command_to_standstill_s` (§9 item 3). The pre-registration is
   deliberately left byte-identical, no threshold moved, and both rows were
   re-run green under the new name.
4. **C6's registered wording** listed the three missing terms in a different
   order than the row prints them (the row uses HLD order). The set is what
   the test asserts; no threshold moved.
5. **One line of a shared file outside a HW-6 fence: none.** But the import
   fence in `timing.py` necessarily encloses the pre-existing
   `from dataclasses import dataclass` line, because isort orders it between
   two of mine. It is unchanged; the comment says so.

## 6. Handoffs

* **H1 — F1, the 0.10 m/s question** (owner / PO-1): design §6/§9 vs
  `commissioning/limits.py:78`. Named in §1 above and in `DESIGN.md` §(d).
* **H2 — `tests/test_hw3_mid360_band.py` does not collect** at 13:16 on this
  tree: `ImportError: cannot import name 'IngestUnavailableError' from
  'scripts.parcel_capture.preflight'`. It reddens
  `tests/test_ci_gate.py::test_tier_coverage_is_green_against_the_real_tree`
  (a collection error is a dark tier to R26's gate). **HW-3's card, mid-edit,
  not HW-6's** — `tests/test_ci_gate.py` was 91/91 green 12 minutes earlier
  with the HW-6 stage already registered. Flagged for the integrator: this
  must be clear before the close-out tier run.
* **H3 — `bridge/timing.py` GATE 5 is a text guard.**
  `tests/test_w0b_commissioning.py::test_no_module_outside_the_commissioning_
  seam_imports_it` scans for the *string* `parcel_robot.commissioning` in any
  `src/parcel_robot/**.py`, so even a docstring mention of the dotted path
  fails it. My region's comment tripped it once and was rephrased (no test
  edited, 116 passed after). Worth a line in the guard's own docstring
  someday — not this card's file.
* **H5 — N4, does `one_axis` carry the localization term?** (design owner)
  Its envelope is `v·stop_timeout_s`, a time budget converted to distance; a
  0.05 m LIO jump alone puts it OVER and blocks HW-12's `--arm`. HLD §8.8's
  sentence says the jump belongs in the sum; a commissioning step on a stand
  over one stop budget arguably is not localization-gated. Decide before
  HW-12.
* **H6 — N5, where does obstacle-observation age live?** (design owner) For
  `leashed`/`restricted_free` the envelope is the reactive ring *seen through
  the LiDAR*, but none of HLD's five terms is the Mid-360 scan period + band
  filter + planner tick; `candidate_age_s` is robot-state age
  (`GatewayStateV1.state_age_ms`). HW-6 implemented the list as written.
* **H7 — `docs/MOTION.md:369` is stale**: it still prints the 2026-08-03
  `unitree_control` commissioning triple (0.10 m/s / 0.25 rad/s / 2 s) that
  W0-B retired on 08-13. Docs are MUST-NOT-TOUCH for this card.
* **H4 — the Orin's record.** On box day the only code change any of
  `BOX_DAY_INPUTS.md` produces is one new
  `configs/envelope/<orin-hostname>.yaml`. HW-12 must not `--arm` while this
  row reads UNMEASURED.

## 7. Owner-gated

None. No hardware was touched, no simulator started, no hosted spend, no
process killed that this card did not start.

## 8. Board row text for `TASK_BOARD.md` (not my OWNS — for parcel-6c)

> **HW-6** `task_38/` — HLD §8.8's "short TTL is an evidence requirement" is
> now a commit-tier row. `bridge/timing.py` gains a pure `derive_envelope`
> with a typed `UNMEASURED` sentinel and three commissioned regimes
> (one-axis 0.05 m/s / 0.050 m, leashed 0.15 / 0.330, restricted-free 0.25 /
> 0.330, every number cited); `configs/envelope/{default,<host>}.yaml` is
> where a host records the five terms; `scripts/ci_gate.py` gains the soft
> `stopping-envelope` row, registered GATE-0b-style with **no edit to
> `tests/test_ci_gate.py`** (91 green, byte-unchanged). On this box it prints
> `UNMEASURED — gateway_period_s, stop_command_to_standstill_s,
> localization_jump_m`;
> the card's seed lands exactly (0.450 s of braking fits by 6.25 mm,
> **+50 ms reddens by 6.25 mm**). Two terms measured through the real N24
> process (ipc p99 329 µs, candidate age 1.8 µs, both flagged as dev-box
> floors). 24/24 rows, 3 seeds RED→green on a scratch, 23 guarded runs,
> zero gate runs; **ACCEPT-WITH-NOTES**, corrected 13:5x (hostname-independent
> shipped-record test — it would have reddened the hosted tier on push — and
> `braking_latency_s` renamed `stop_command_to_standstill_s`).
> **Finding for the owner: the design's "one-axis 0.10 m/s" is a speed cap
> `unitree_control.py` carried on 2026-08-03 and W0-B retired on 08-13; the
> band refuses > 0.05 m/s and `docs/MOTION.md:369` is stale.**

---

## 9. Correction pass — 2026-08-23 13:3x–13:5x EDT

Verifier verdict **ACCEPT-WITH-NOTES**, 2 FIX (one before the push), 0 HOLD;
record `~/.cache/parcel-verify/hw6/VERDICT.md`, read in full before this pass.
`PREREGISTRATION.md` is **byte-unchanged** (sha256 still
`fcf68a29db1f5d9938ae9e16a961907cbd35d5435aade58924f3904b69ec5639`). No gate
tier run; every pytest through `pytest_guard.sh --label hw6`.

| # | item | what changed | proof |
|---|---|---|---|
| 1 | **F1** — the shipped-record test pinned THIS box's three terms, so `ubuntu-latest` (`fv-az…`) and the Orin, which fall back to `default.yaml` and have five, would have **reddened the hosted commit tier on first push** | `test_the_shipped_records_are_valid_and_this_host_reads_as_unmeasured` is replaced by `test_the_shipped_records_are_valid_and_the_row_follows_the_resolved_one`, **parametrised over `jaewoo-jang-parcel` / `fv-az1234-567` / `fictional-orin-host`**, asserting four *structural* invariants: a shipped record never gates (`hard is False`, unconditional — seed S1's target); the row reports the resolved record's own missing set (`set(extra["missing"]) == set(record.missing())`); it points at the file the resolver chose; every term has provenance. The dev box's three terms are asserted only where they are true, and `default.yaml` is asserted complete-and-empty (all five) so a host without a record cannot inherit another host's numbers. A second test, `test_the_row_resolves_by_hostname_on_its_own_default_path`, proves the **default** path (`evaluate_stopping_envelope()` with no argument) picks the same files. | **30 passed** (was 27: one test became a 3-way parametrisation plus one new test). Both hostnames proved: the parametrised test drives `record=` explicitly; the default-path test patches the resolver's hostname source. **Which source:** `bridge/timing.py` does `import socket` at module scope and the resolver calls `socket.gethostname()`, so `timing.socket` **is** the stdlib module — `monkeypatch.setattr(timing.socket, "gethostname", …)` is a process-wide patch of `socket.gethostname`, undone by monkeypatch. There is no narrower hook and I did not invent one for a test. Results: `jaewoo-jang-parcel` → `jaewoo-jang-parcel.yaml` (3 missing), `fv-az1234-567` → `default.yaml` (5), `fictional-orin-host` → `default.yaml` (5); all three `hard=False`, `status="pass"`, `state="UNMEASURED"`. |
| 2 | **F1 second half** — N9, the env leak | The default-path test clears `PARCEL_ENVELOPE_RECORD` first, and then asserts the override still wins when it *is* set. | in the same 30 |
| 3 | **F2 — the rename** (chosen over the field comment) | `braking_latency_s` → **`stop_command_to_standstill_s`** in `bridge/timing.py` (the term tuple and the field), both record files, `BOX_DAY_INPUTS.md`, `DESIGN.md` and all 21 uses in the test file. **Why the rename and not the comment:** the *name* is what a record-writer and HW-12 copy, and the file they copy it into (`configs/envelope/<host>.yaml`) carries no code comments at all — only the key. Every field also gained a `#:` definition, and `stop_command_to_standstill_s`'s says what a reaction-only number would cost: the whole `v²/(2a_b)` term, 22 mm at 0.25 m/s with the profile's 1.4 m/s² and 62 mm at a quadruped-realistic 0.5 m/s², against a 330 mm envelope with a 6 mm seeded margin. The same paragraph is now in `ci_gate.py`'s region header where it quotes HLD's ambiguous phrase. | `grep -rn braking_latency_s` over `src/ scripts/ tests/ configs/` → **0**; the row now prints `UNMEASURED — gateway_period_s, stop_command_to_standstill_s, localization_jump_m`. **Declared deviation:** rows C3/C6 of `PREREGISTRATION.md` name the old literal; the pre-registration is deliberately not edited, and no threshold moved. |
| 4 | **N3** — "exactly a factor-of-two reserve" was overstated | Reworded in all three places (`DESIGN.md` §(c), the `timing.py` region comment, §1 above) to the verifier's statement: with `t_stop = t_vr + t_d`, `v·t_stop = v·t_vr + v·t_d ≥ v·t_vr + ∫v(t)dt` for **any** `v(t) ≤ v` — a rigorous upper bound; 2× on the deceleration sub-part, 1× on the vendor reaction; under-counts only under overshoot. `DESIGN.md` risk (3) now names overshoot as the single failure mode and says B2's endpoint-stamping procedure would not see it (a velocity trace from the same session would). | `grep -n 'factor of two'` → only the negated form |
| 5 | **N6** — `default.yaml` cited non-existent rows I1/I2 | `BOX_DAY_INPUTS.md` gains the **I1 / I2** section: the two terms already measured on the desktop and why **the Orin must re-measure both** (candidate age is producer-bound — 50 Hz `rt/sportmodestate`, ~20 ms, four orders of magnitude above the desktop's 1.8 µs; IPC is a different kernel and a native gateway). Both are now rows with a procedure and the same three load conditions as B1, not footnotes. The field comments in `timing.py` cite them too. | `grep -n '^## '` → `I1 / I2`, `B1`, `B2`, `B3`, `Q-avoid` |
| 6 | **N7** — wrong refusal cite | `limits.py:249-252` raises `ValueError` (band construction). The per-step refusals are `assert_commissioning_command` `:466-470` (`OVER_LIMIT`) and `assert_commissioning_duration` `:486-490` (`OVER_DURATION`). All three are now named separately in `DESIGN.md` §(d) and §1 above. Finding F1's story is also corrected to the verifier's: **0.10 m/s is a retired speed cap** (`unitree_control.py:20-22` at `22c9721`, retired by W0-B `406f9d6`), not only a distance; `docs/MOTION.md:369` still prints the retired triple and is stale (MUST-NOT-TOUCH here). | the three refusals re-run by the verifier; cites re-read |
| 7 | **N8** — B2's definition vs its clock | "from the vendor accepting `StopMove`" → "from **the gateway ISSUING** `StopMove`/Damp", which is the instant the procedure stamps as `t_stop` and a conservative superset (it includes the vendor's receipt path, and nothing between the two is observable from outside the dog). Heading follows. | `sed -n '79,90p' BOX_DAY_INPUTS.md` |
| 8 | **N10** — cosmetic | §3's "13:04" for A1 is the ledger's **13:02:23** (pre-edit) and **13:05:19**. | `guard.log` |

**Seed S1 re-proved against the rewritten test** on a fresh import-verified
scratch (`~/.cache/parcel-hw6/scratch2`; `parcel_robot`, `bridge.timing` and
`scripts.ci_gate` all confirmed to resolve inside it, `ci_gate REPO` = the
scratch). Control **3 passed**; the seeded all-measured over-budget host
record → **`FAILED …[jaewoo-jang-parcel]`, 1 failed, 2 passed** — the two
foreign hostnames stay green, which is F1's property demonstrated by the seed
itself; restored by sha256 `03e68583a98c87d402167e8ffae6ec397c3d04d5eaaca7ffc1c1d899b3a163f1`
(identical before and after), `__pycache__` purged, **3 passed** again.

**Runs in this pass** (all guarded, `--label hw6`, no `-n`, no rc=137):
`tests/test_hw6_stopping_envelope.py` → **30 passed**;
`tests/test_ci_gate.py` → **91 passed**, file still byte-unchanged
(`git diff -- tests/test_ci_gate.py` empty); three targeted scratch runs for
S1. Ruff on the three touched `.py` → **All checks passed!**;
`scripts/ci_ruff_baseline.json` byte-unchanged, 7 fingerprints; **0 `noqa`**.

**Left for the design owner (parcel-6c), not fixed here.** N4: `one_axis`'s
envelope is a time budget converted to distance (`v·stop_timeout_s`) and the
row adds `localization_jump_m` to it, so a 0.05 m LIO jump alone puts
`one_axis` OVER and would block HW-12's `--arm` — HLD's sentence says the
jump belongs, the envelope's meaning may not. N5: for `leashed`/
`restricted_free` the envelope is the reactive ring seen through the LiDAR,
but none of HLD's five terms is the **obstacle-observation age** (Mid-360 scan
period + band filter + planner tick); `candidate_age_s` is robot-state age.
HW-6 implemented HLD's list as written; the design owes a sentence on where
scan age lives. Both are recorded as handoffs H5 and H6.

**Integrator (verifier N2):** `configs/envelope/` must be in the same commit
as the two shared-file hunks. Without it the real evaluator (which
`fast_commit_tier` does not stub) returns a soft `error` and
`test_ci_gate.py::test_the_clean_commit_tier_reports_exactly_the_declared_stages`
— which asserts every status is `pass` — fails on the hosted runner. Add:
`configs/envelope/`, `tests/test_hw6_stopping_envelope.py`,
`scrum/20260822/task_38/`.

**Final notes closed — 2026-08-23 14:0x EDT.** **N11**: `HW6_STATUS.md`'s
rendering of the row's printed output (§Headline and §3 rows C1/C6, the §1
term table and the board row) still showed `braking_latency_s`; all now read
`stop_command_to_standstill_s`. The three remaining mentions of the old name
(§5 deviation 3, §9 item 3, the board row's rename sentence) are deliberate —
they are the record OF the rename and of the pre-registration's literal.
**N12**: the parametrised hostname `orin-nx` is replaced by
**`fictional-orin-host`** — on box day the real Orin gets its own
`configs/envelope/<its-hostname>.yaml`, and the `else` branch's
`assert resolved.name == "default.yaml"` would then fail for a reason that has
nothing to do with what the test checks; a hostname no machine can ever carry
keeps the branch true forever, and the comment says exactly that. Same change
in the default-path test's table. One guarded run,
`pytest_guard.sh --label hw6 … tests/test_hw6_stopping_envelope.py -q` →
**30 passed, 1 warning in 0.57 s**; ruff on the test file **All checks
passed!**; no other file touched, no threshold moved, no re-verify round
requested.
