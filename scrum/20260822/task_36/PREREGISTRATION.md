# HW-3 `mid360-band` — PREREGISTRATION

Written before any row was measured. Rows are measured as written; a miss is
a miss. Card `README.md` §Work 4 (a)-(d) + §Work 5 (seeds) map onto R1-R9.
Every pytest invocation goes through the guard:

    G="$HOME/.cache/parcel-guard/pytest_guard.sh --label hw3"
    env -u TMPDIR $G .parcel/bin/python -m pytest <args>

No `-n auto`, no `-n` > 8, no `ci_gate.py --tier`, no background pytest.
Seeds run on a byte-identical scratch copy at `~/.cache/parcel-hw3/scratch`
(never the working tree), with `PYTHONPATH=<scratch>:<scratch>/src` and
`python -c "import parcel_robot; print(parcel_robot.__file__)"` verified to
resolve INSIDE the scratch, restored by sha256, `__pycache__` purged.

| Row | Claim | Command | Threshold (pre-registered) |
|---|---|---|---|
| R1 | The parser round-trips a synthesised Cartesian-high frame: every header field and every point (x,y,z in m, reflectivity, tag, per-point timestamp) comes back exactly as the builder put it in. | `pytest tests/test_hw3_mid360_band.py -k round_trip` | PASS; float compare exact for the mm->m scale of integral mm values; `t_i == base + i*(time_interval*100//dot_num)` for all i |
| R2 | The parser REFUSES, with a typed `LivoxDecodeError` naming the field: truncated frame (payload shorter than `36 + dot_num*S`), unknown `data_type` (0, 3, 0x11, 0x7f), unknown `version`, `dot_num == 0`, `dot_num` over cap, non-`bytes` input, header shorter than 36. | `pytest tests/test_hw3_mid360_band.py -k refus` | 8/8 refusals raise `LivoxDecodeError`; no refusal message is generic (each names the field and the byte count) |
| R3 | Out-of-order / duplicated `udp_cnt` across frames of one sweep is DETECTED and reported, not silently reordered or dropped. | `pytest tests/test_hw3_mid360_band.py -k udp_cnt` | the assembler returns the gap/duplicate report; no exception; points from the bad frame are not silently merged |
| R4 | Band property: no point with `z'` outside `[z_lo, z_hi]` can influence any bin; points inside can. Randomised, seed `20260823`. | `pytest tests/test_hw3_mid360_band.py -k band_property` | 2000 random points, 200 trials: 0 violations |
| R5 | A wall at 2.000 m at bearing theta lands in the bin for theta at 2.000 m, for every theta on a 720-point sweep of `[-pi, pi)`; empty bins are `NaN`; the layout (`bins`, `angle_min`, `increment`, `range_min`, `range_max`) equals `mujoco_lidar`'s five numbers. | `pytest tests/test_hw3_mid360_band.py -k wall or -k layout` | bin index exact for all 720; `abs(range - 2.0) <= 1e-9`; layout equality exact against `mujoco_lidar.DEFAULT_SCAN_*` imported in the test |
| R6 | Through the REAL product functions on a `SimObservation(backend="go2")` built from band output: `reactive_safety.scan_present` is True; `scan_evidence_from_observation` returns the evidence the real `evidence_origin` rule produces; `evaluate_input_health` ALLOWS translation on the SCAN input under `reactive_safety`'s own spec. No monkeypatch, no stub, no fake. | `pytest tests/test_hw3_mid360_band.py -k scan_present or -k evidence` | `scan_present is True`; evidence origin is whatever `core/input_health.py:evidence_origin` really returns for `"go2"` and the test states it explicitly; `verdict.translation_allowed is True` |
| R7 | `nearest_obstacle_from_scan` is IDENTICAL to the sim's derivation: differential against the real `parcel_robot.sim.select_relevant_obstacle` over 500 random candidate sets x {translating, stationary}, plus the `max(0, r - footprint_radius)` clearance rule. | `pytest tests/test_hw3_mid360_band.py -k nearest_obstacle` | 500/500 identical selection (same bearing, same distance to 1e-12); 0 disagreements |
| R8 | Performance, RECORDED not gated: one 20 000-point sweep -> ranges. | `pytest tests/test_hw3_mid360_band.py -k performance -s` | number recorded in `HW3_STATUS.md` with the host; the card's < 20 ms is the desktop expectation and is NOT a gate; the Orin number is box-day |
| R9 | Seeded RED on the PRODUCT for every guard, on the scratch copy: (S1) delete the `data_type` refusal -> R2's data-type cell fails; (S2) delete the byte-count check -> R2's truncation cell fails; (S3) widen the band test to `z <= z_hi + 1` -> R4 fails; (S4) change `angle_min` to `0.0` -> R5 layout+wall fail; (S5) drop the corridor filter from `nearest_obstacle_from_scan` -> R7 fails. | see `HW3_STATUS.md` command ledger | each seed reddens EXACTLY its named row(s) and the tree is restored byte-identically (sha256 before == after) |

Owner-gated rows: none. Hardware-gated (box-day, HW-9): a pcap from a real
Mid-360, the extrinsic, per-bin coverage, the Orin timing, the M8 wiring.
Not measured here and not claimed.

Lint row: `.parcel/bin/ruff check` on every touched file; `scripts/
ci_ruff_baseline.json` stays at exactly 7 fingerprints; no `noqa` added.
