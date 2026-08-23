# HW-6 `stopping-envelope` — PREREGISTRATION

Written **before** any row was measured and before `bridge/timing.py`,
`scripts/ci_gate.py` or the record files were edited. Rows are measured as
written; a miss is a miss. sha256 of this file goes in `HW6_STATUS.md`.

Every command below runs through the mandatory wrapper
`~/.cache/parcel-guard/pytest_guard.sh --label hw6` with `env -u TMPDIR`,
never `-n auto`, never `scripts/ci_gate.py --tier` (anti-crash rules 1-5,
`BATCHB_DISPATCH_FABLE_4a.md` § parcel-6c). `PY = .parcel/bin/python`.

## A. Pin rows — the RC-4 derivation must not move

| # | Row | Command | Threshold |
|---|---|---|---|
| A1 | The four RC-4 rows are byte-identical before my edit | `PY -m pytest tests/test_hw6_stopping_envelope.py -k rc4 -q` (written and run BEFORE `timing.py` is touched) | 100 % pass; the two rendered tables equal the sha256 recorded in the test |
| A2 | The same rows are byte-identical after my edit | same command, after the `CARD HW-6` region lands | identical result to A1, same shas |
| A3 | The existing RC-4 owner test still passes | `PY -m pytest tests/test_gateway_protocol_v1.py -q` | 100 % pass, count unchanged from the pre-edit run |
| A4 | `docs/GATEWAY_TTL_LATENCY_DERIVATION.md` still contains both rendered tables | inside A3 (`test_rc4_document_contains_the_executable_table`) | pass; `git diff -- docs/` empty |

## B. Arithmetic rows — the formula

| # | Row | Command | Threshold |
|---|---|---|---|
| B1 | `derive_envelope` computes `v*(t_cand+t_ipc+t_period+t_brake)+d_loc` term by term | `PY -m pytest tests/test_hw6_stopping_envelope.py -k arithmetic -q` | every term's contribution equals the hand-computed value to 1e-12 |
| B2 | The three regimes carry the speeds and envelopes of DESIGN §(d) | `-k regimes` | `one_axis` 0.05 m/s / 0.050 m; `leashed` 0.15 / 0.330; `restricted_free` 0.25 / 0.330 (approx 1e-9) |
| B3 | Mirrored constants equal their sources | `-k mirrors` | `ENVELOPE_MAX_LINEAR_MPS == commissioning.limits.MAX_LINEAR_MPS`; `ENVELOPE_STOP_TIMEOUT_S == ControlTiming().stop_timeout_s == configs/robot.yaml control.stop_timeout_s`; ring `== configs/robot.yaml safety.obstacle_stop_m`; footprint / tau / decel `== robot_profile.DEFAULT_ROBOT_PROFILE` |
| B4 | Sentinel propagation | `-k sentinel` | any one term `UNMEASURED` ⇒ `state == "UNMEASURED"`, `required_m is None`, `missing` names exactly that term; all five ⇒ all five named |
| B5 | Record shape is fail-closed | `-k record` | missing term, unknown term, negative value, non-finite value, missing provenance each raise `ValueError`; the literal `UNMEASURED` round-trips to the sentinel |

## C. Gate-row rows — the three states, in-process

No gate tier is run by this card. Each row calls
`scripts.ci_gate.evaluate_stopping_envelope(root=..., record=<temp file>)`
directly and reads the returned `GateResult`.

| # | Row | Command | Threshold |
|---|---|---|---|
| C1 | UNMEASURED state | `-k row_unmeasured` | `hard is False`, `status == "pass"`, detail starts `UNMEASURED — ` and names every missing term |
| C2 | FITS state | `-k row_fits` | `hard is False`, `status == "pass"`, detail carries required/envelope/headroom for all three regimes |
| C3 | OVER state (the seed) | `-k row_over` | `hard is True`, `status == "fail"`; a record at `restricted_free` with `braking_latency_s = 0.45 s` FITS with ≤ 10 mm headroom, and **`0.50 s` (+50 ms) reddens it** |
| C4 | Only the ACTIVE regime gates | `-k active_regime` | the same over-budget numbers with `active_regime: one_axis` … `restricted_free` OVER ⇒ row still `hard=False`, and the non-active OVER is printed |
| C5 | Malformed / absent record is visible and non-gating | `-k row_error` | `status == "error"`, `hard is False`, detail names the file and the exception type |
| C6 | The shipped records are valid and this box's row is a soft UNMEASURED | `-k shipped` | `configs/envelope/default.yaml` and `configs/envelope/jaewoo-jang-parcel.yaml` both load; the resolved row on this host is `hard=False`, `status="pass"`, `UNMEASURED — braking_latency_s, gateway_period_s, localization_jump_m` |
| C7 | The stage is registered without editing XD-1's file | `-k registered` + `PY -m pytest tests/test_ci_gate.py -q` | `"stopping-envelope" in COMMIT_TIER_STAGE_NAMES` and in `run_commit_tier`'s produced names (via the stage tuple, asserted by source read, no tier run); `tests/test_ci_gate.py` passes unchanged (`git diff -- tests/test_ci_gate.py` empty) |

## D. Measurement rows — this box's two measured terms

Measured through the real N24 fake-gateway **process** (`python -m
parcel_robot.bridge.fake_gateway_process` over AF_UNIX `SOCK_SEQPACKET`,
driven by `bridge/client.py:FakeGatewayClientV1`), the same path
`tests/test_gateway_process.py` exercises. Recorded as p99 of N samples, so
the record carries the worst case the sentence asks for, not a mean.

| # | Row | Command | Threshold / what is recorded |
|---|---|---|---|
| D1 | `ipc_delay_s` = p99 of `client.command(...)` submit→ack round trip | `PY tools/measure_envelope_inputs.py --samples 2000` under the wrapper (a pytest module driving the same code, so it runs guarded) | recorded, not thresholded. Registered expectation: p99 < 0.010 s on this box; if it is larger the record still carries the measured number and the status doc says so |
| D2 | `candidate_age_s` = p99 of `GatewayStateV1.state_age_ms` sampled straight after a command | same run | recorded, not thresholded. Registered expectation: p99 < 0.010 s |
| D3 | Both values land in `configs/envelope/jaewoo-jang-parcel.yaml` with a provenance string naming the command, the sample count and the date | `grep provenance configs/envelope/jaewoo-jang-parcel.yaml` | both present; three box-day terms still `UNMEASURED` |
| D4 | The dev-box numbers are declared NOT to be the dog's | `HW6_STATUS.md` §"what this does not prove" | present in prose |

## E. Seeds — RED before green, on a scratch copy only

Scratch = `rsync -a --exclude .cache --exclude .parcel --exclude .git` of
`src/ scripts/ tools/ tests/ configs/ prompts/` into
`~/.cache/parcel-hw6/scratch`, run with
`PYTHONPATH=<scratch>:<scratch>/src`, import verified with
`python -c "import parcel_robot; print(parcel_robot.__file__)"` inside the
scratch, restored by sha256, `__pycache__` purged.

| # | Seed | Expected RED |
|---|---|---|
| S1 | Replace the scratch's `configs/envelope/<host>.yaml` with an all-measured over-budget record | `test_the_shipped_record_for_this_host_is_a_soft_unmeasured_row` FAILS (the row is hard/fail, not a soft pass) |
| S2 | Delete the `+ d_localization` term from `derive_envelope` in the scratch | `test_the_envelope_arithmetic_is_pinned_term_by_term` FAILS |
| S3 | Change one RC-4 row value (`proposed_p99_ms` 100.0 → 101.0) in the scratch | `test_the_rc4_rows_and_rendered_tables_are_byte_identical` FAILS |

## F. Lint

| # | Row | Command | Threshold |
|---|---|---|---|
| F1 | Ruff clean on every file this card writes | `.parcel/bin/ruff check <OWNS>` | `All checks passed!`, no `noqa` added anywhere, `scripts/ci_ruff_baseline.json` byte-unchanged |

## Owner-gated

None. No hardware, no hosted spend, no sim.
