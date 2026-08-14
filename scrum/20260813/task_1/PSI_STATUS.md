# PS-I — clock discipline redesigned around physical sync events

**Card:** PS-I, corrective tranche **PS-2** · **Date:** 2026-08-13 · **Executor:** Opus
**Driver:** [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) §*The clock card needs redesign*
**OWNS:** `scripts/parcel_capture/syncevents.py` (new) ·
`scripts/parcel_capture/clockmap.py` · `tests/test_syncevents.py` (new) ·
`tests/test_clockmap.py`

---

## 1 · The defect, verified at source before anything was written

```
$ grep -n "device_source_ns: int$\|round_trip_ns: int$" scripts/parcel_capture/clockmap.py
487:    device_source_ns: int
490:    round_trip_ns: int

$ .parcel/bin/python -c "<construct ClockSample with each field None>"
device_source_ns -> non_integer_field: device_source_ns must be an int (nanoseconds), got None
round_trip_ns    -> non_integer_field: round_trip_ns must be an int (nanoseconds), got None
go2.lowstate source_clock=wrapping_counter rate=500.0 anchor=False
```

Both clock fields are mandatory; neither is obtainable from the Go2. The dog
exposes no queryable clock and no round-trip primitive, and `lowstate` — the
500 Hz IMU, the highest-timing-value channel on the robot — carries **no
timestamp field at all**, only `tick`: `uint32` milliseconds, wrapping, starting
at an arbitrary value. PS-H's `channels.py` already marks it
`SourceClock.WRAPPING_COUNTER` with `is_usable_anchor=False`. **`ClockMapV1`
could not be populated for the dog, exactly as the risk assessment says.**

## 2 · What I built

**`syncevents.py` (3,499 lines)** — detect, match, estimate, fit, for the
bracketed physical ritual. Six layers, each fail-closed:

| Layer | Surface | What it refuses |
|---|---|---|
| Events | `SyncEvent`, `EventTrain`, `TimeDomain`, `merge_trains` | a train on a channel not in the matrix; a train whose device contradicts the matrix; **a train claiming `DEVICE_TIMESPEC` on a channel the matrix says has no device time** — the PS-C fiction, refused at the type level; a zero or absent bracket |
| Counter | `unwrap_tick_ms`, `TickUnwrap` | a tick outside `uint32`; a forward jump past 60 s; a *small* backward step (reordering, not a wrap); an empty series. Rebases to elapsed and carries `epoch_is_arbitrary` as a field a reader must walk past |
| Detectors | `detect_accel_spikes` · `detect_gyro_onsets` · `detect_brightness_steps` · `detect_button_edges` (+ `magnitudes_from_xyz`, `wireless_remote_keys`) | NaN/inf/None in any sample; unequal lengths; a non-increasing or duplicated timestamp; unordered thresholds; a runaway threshold (>64 events). Every threshold is the caller's — none is inferred, none has a permissive default |
| Matching | `match_trains`, `TrainMatch`, `MatchStatus` | **ambiguity**: if a well-separated alternative alignment fits as well, the status is `AMBIGUOUS` and there is no offset. Four outcomes, three of which are UNKNOWN; none is zero |
| Estimation | `estimate_pair_offset`, `PairOffset` | an offset from a non-matched train. Uncertainty split systematic (brackets + dropout penalty, does not shrink with n) / statistical (Student-t on the matched residuals, does) |
| Fit | `pair_clock_samples`, `detect_ritual_step`, `SyncStep`, `BlindInterval`, `SyncFitV1`, `sidecar_sync_block` | a reference train that is not the host clock; a *target* that is also host-stamped (that offset is a **transport delay**, not a clock relation); a reference event with no `host_realtime_ns`; a session where no ritual matched |

**The bridge is the whole fix.** `ClockSample`'s algebra never needed an
interrogation — only a bracketed correspondence. One matched event pair becomes
one sample:

```
round_trip_ns     = 2 * (ref_bracket + tgt_bracket + dropout_penalty)
host_monotonic_ns = reference_event - (that half-width)
device_source_ns  = target_event
=> host_mid_ns = reference_event,  offset_ns = target - reference
```

so `clockmap`'s uncertainty machinery, sidecar binding and digests are reused
rather than reimplemented. **The flagship pair is `go2.lowstate` in host-receipt
time against `go2.lowstate` in its own unwrapped tick** — the only way the dog's
500 Hz IMU channel gets onto the session timeline at all.

**`clockmap.py` — four additive changes, no wire-format change:**
`ProbeRequirement.interrogable` (Go2 = `False`, its `method` rewritten to name
the ritual); public `t_critical_95` and `fit_relation`; and `fit_relation(...,
splits=)` / `_build_relation(..., splits=)` — an explicit-segmentation path,
justified in §4. `ClockSample`, `ClockMapV1` and every schema string are
untouched: 130 pre-existing `test_clockmap.py` cells pass unchanged.

**`--ritual-card`** prints the operator sheet for tomorrow (4 events, 25 s,
what sees each, why each exists) and **`--check`** prints the per-channel clock
truth: 17 of 28 channels have no usable device clock.

## 3 · Three findings I did not expect, each now load-bearing

**(a) The sign convention was inconsistent and the report exposed it.**
`PairOffset` first reported `reference - target` while `ClockSample.offset_ns` is
`device - host`, so the same fit printed `-3987998 ms` per ritual and
`+3988070 ms` for the fit. One convention now: `target - reference`, positive
means the target clock is ahead, everywhere.

**(b) `clockmap`'s step scan cannot be used on ritual data, measured.** With the
evidence in two 8 s bursts an hour apart, a segment covering one burst has a
slope determined by 8 s of data. Extrapolating it to the burst boundary carries
**±1304 ms** (measured: `systematic 1226 ms + statistical 78 ms`), so a real
500 ms step cannot clear it — while pairs of unconstrained extrapolated lines
cross often enough to declare steps that never happened. On the seeded 3-ritual
fixture the scan declared **two** steps, one of them `-25.382 ms ± 2511 ms`.
A clock step changes the **offset, not the rate**, so the right model is a common
drift with a per-segment intercept, fitted over the per-ritual offsets
(`detect_ritual_step`). Its verdict — not the sample scan — sets the
segmentation, which is why `fit_relation` gained `splits=`.

**(c) A step needs FOUR rituals to be located, not three.** A step model has
three parameters, so three offsets fit it *exactly* and every gap explains them
equally well: `+S` in the second gap and `-S` in the first at a different drift
produce identical offsets. Measured: at K=3 the module reports the step's size
(`+499.977 ms ± 8.232 ms`) and refuses the location; at K=4 it places it in the
right gap. This is now on the operator card as **"perform the ritual again at
every battery swap"** — 25 s that buys step localisation, and unrecoverable
afterwards.

## 4 · MEASURED claims

Every row is a command run on this host today; nothing is estimated.
Test runs use `PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest`.

| # | Claim | Command | Output |
|---|---|---|---|
| M1 | The PS-C mechanism is impossible for the dog | see §1 | both fields refuse `None`; `go2.lowstate` is a wrapping counter, `anchor=False` |
| M2 | Owned tests pass | `pytest tests/test_clockmap.py tests/test_syncevents.py -q` | `230 passed in 3.73s` (95 new + 135 clockmap) |
| M3 | Whole capture stack still passes | `pytest tests/test_clockmap.py tests/test_capture_*.py ... -q` | `605 passed in 12.73s` |
| M4 | **Gate: 40 ppm recovered** (3600 s, 2 rituals) | `--selftest` | `FIT drift +40.005 ppm ± 1.794 ppm (two-sided-95)`, error **0.005 ppm**, inside the stated ±4 ppm |
| M5 | The stated tolerance is derived, not chosen | drift uncertainty at 1800/3600/7200 s | `3.589 / 1.794 / 0.897 ppm` — exactly `bracket / half-span`; halving the span doubles it. The systematic half (3.514/1.757/0.878) does **not** shrink with more events |
| M6 | **Gate: 500 ms step is a STEP** (K=4) | `build_selftest_fit(labels=4, step_ns=5e8, step_from_ritual=3)` | `mag=+499.951 ms ± 6.166 ms localizable=True gap=SWAP-2->CLOSE`, `segs=2`, `drift=39.997 ppm` — **not** smoothed |
| M7 | …and it is placed in whichever gap it happened in | same, `step_from_ritual=2` | `mag=+500.017 ms gap=SWAP-1->SWAP-2`, `drift=39.945 ppm` |
| M8 | At K=3 the size is known and the place is not | K=3 fixture | `mag=+499.977 ms ± 8.232 ms localizable=False after_ritual=None`, `is_certifiable=False`, shortfall names it |
| M9 | At K=2 no step is claimed at all | K=2 fixture | `n_steps=0`, `"a step is not testable"`, one `3594.9 s` blind interval, drift aliased to `178.9 ppm` and the caveat says so |
| M10 | **Gate: 2 of 5 flashes missed ⇒ offset, WIDER** | flash pair, keep `(0,2,4)` vs all | `10/10: +17.031 ms ± 33.881 (sys 33.293 + stat 0.588)` → `6/10: +16.976 ms ± 47.519 (sys 46.454 + stat 1.065)`. **Both halves widen**; penalty `13.272 ms`; the offset is still right to 0.06 ms |
| M11 | **Gate: no matched events ⇒ UNKNOWN, never zero** | IMU taps vs camera flashes | `status=no_match offset=None pairs=()`; `estimate_pair_offset` raises `not_matched`; `build_sync_fit` raises `no_matched_events` with *"It is not zero"* in the message |
| M12 | Uneven flash gaps are load-bearing | even 3-vs-2 / uneven 5-vs-3 | `EVEN: ambiguous None` · `UNEVEN: matched, best 3, runner-up 2` |
| M13 | Tick wrap is unwrapped and counted | `unwrap_tick_ms([2^32-6,…,4])` | `elapsed_ms=(0,2,4,6,8,10) wraps=1 first_tick=4294967290 arbitrary=True`; the naive difference would have been **−49.7 days** |
| M14 | Nothing arms anything | AST pin + `ruff` | no publisher/`ControlManager`/`Move`/lease symbol; no `rclpy`/`unitree_sdk2py`/`pyrealsense2`/`cv2`/`mcap` import; no `import_module`/`__import__` |
| M15 | Leaf import | subprocess `sys.modules` diff | `[]` — nothing outside stdlib + `parcel_robot` + `scripts` |
| M16 | Python 3.10 | `ast.parse(feature_version=(3,10))` | both modules parse. **STATIC ONLY — this host is 3.14.4 and has no 3.10 interpreter**, same limitation PS-A recorded |
| M17 | Runs from a bare checkout with no PYTHONPATH | `cd / && PATH=/usr/bin:/bin python syncevents.py --selftest` | full report, exit 0, no traceback |
| M18 | Sidecar round-trip by digest | `test_the_fit_round_trips_through_the_bag_sidecar_extra_by_digest` | `make_manifest(extra=sidecar_sync_block(fit))` carries `sync_fit_sha256`; decode→re-encode is byte-identical and re-digests equal |
| M19 | ruff | `ruff check scripts/parcel_capture/ tests/test_syncevents.py tests/test_clockmap.py` | `All checks passed!` (gate: `7 violation(s), baseline 7, new 0`) |
| M20 | **ci_gate** | `.parcel/bin/python scripts/ci_gate.py --tier commit` | `RESULT: PASS — every hard gate green.` · `default-suite 4878 passed, 9 skipped, 36 deselected in 201.36s` |

## 5 · Seeded-failure table — one row per gate

| Gate | Seeded failure | Would the harness notice? |
|---|---|---|
| Step is a step | naive single-line fit over the same 4 ritual offsets | `naive > 100 ppm` against a true 40; error **>10×** the stepped fit's. `test_seeded_failure_a_single_line_fit_turns_the_step_into_drift` |
| Step is a step | a clean session (K=2,3,4) | zero steps, one segment, certifiable — the detector does not fire on everything |
| Drift tolerance | interval must cover truth at 3 spans | `abs(drift-40) <= total` at 1800/3600/7200 s |
| Drift tolerance | systematic term must not shrink with n | asserted as the `bracket / half-span` scaling law (ratio 1.8–2.2 for a 2× span) |
| Partial modality | remove the dropout penalty | `without_penalty.total < offset.total`, and the penalty is `13.3 ms`, not decorative |
| Partial modality | a modality that saw ONE event | `AMBIGUOUS`, no offset; and where it is matchable, `statistical=None` ⇒ unbounded |
| No matched events | empty train | `NO_EVENTS`, `offset=None`, detail contains *"not zero"* |
| No matched events | a ritual that matched nothing is still carried | `unresolved` row survives into `SyncFitV1`, `is_certifiable=False` |
| Fail-closed clocks | 12 malformed detector inputs (NaN, inf, None, reordered, duplicated, length mismatch, empty, zero bracket, unordered thresholds, int-as-bool) | each raises its own typed `SyncRefusalReason` |
| Fail-closed counter | 6 malformed tick series + a 60 ms backward step | `TICK_OUT_OF_RANGE` / `TICK_JUMP` / `NON_INTEGER_FIELD` / `EMPTY_FIELD` |
| Ambiguity | an evenly spaced partial train | `AMBIGUOUS` — with the uneven pattern as the positive control |
| Runaway detector | 100 spikes on a quiet channel | `TOO_MANY_EVENTS` — with an alternating series as the negative control (robust threshold suppresses it: 0 events, not 250) |
| Domain lie | `DEVICE_TIMESPEC` claimed on `go2.lowstate` | `DOMAIN_MISMATCH`; the same channel in `UNWRAPPED_COUNTER` is accepted |
| Digest binding | move one detected event by 1 ns | `events_digest` moves; the fit digest is otherwise stable |
| Hand-editing | `"is_certifiable": true` + emptied `shortfalls` written into the file | recomputed on decode; the fit is still not certifiable |
| Read-only pin | 5 mutants (`import rclpy`, `SportClient`, `create_publisher`, `ControlManager()`, `parcel_robot.runtime`) | all caught; benign sensor names do not fire it |
| 3.10 pin | `type Alias = int`, PEP-695 generics | both raise `SyntaxError` under `feature_version=(3,10)` |
| clockmap splits | a split leaving a <3-sample segment, a float split | `MALFORMED_RECORD` |

## 6 · OWNS deviations

1. **I added four surfaces to `clockmap.py` beyond "redesign the card".**
   `interrogable`, `t_critical_95`, `fit_relation`, and `splits=`. The first
   three are additive and used by `syncevents`; `splits=` is the only behaviour
   change, and it is opt-in (`None` = today's automatic scan). Justified by the
   ±1304 ms measurement in §3(b) and pinned by four new `test_clockmap.py` cells.
   **No wire format, schema string, or existing default changed**; all 130
   pre-existing cells pass untouched.
2. **`pair_clock_samples` refuses a host-stamped TARGET.** Not on the card. The
   card names the `wireless_remote` ↔ `wirelesscontroller` press as "a
   cross-check on a single device" — but both are host-stamped, so their offset
   is a *transport delay*, not a clock relation, and typing it
   `DEVICE_TO_HOST_MONOTONIC` would put a lie in the enum. That pairing still
   produces a `PairOffset` (the delay **is** measured); it produces no
   `ClockSample`.
3. **The card said "3 sharp taps ~1 s apart"; the operator sheet now says do NOT
   space them evenly.** Same reason the flash gaps are uneven, and M12 measures it.
4. **`RITUAL_SCRIPT` names a mid-session repeat at every battery swap.** Not on
   the card; forced by finding §3(c). It is 25 s and it is the difference between
   knowing a step happened and knowing where.
5. **The dropout penalty (`DROPOUT_PENALTY_FACTOR = 1.0`) is an engineering
   assumption**, labelled as one in the source beside
   `ASSUMED_WORST_CASE_DRIFT_PPM`'s precedent. One bracket width per fully-lost
   train is the smallest penalty that is not zero; zero is the one value that is
   certainly wrong.
6. **I did not touch `record.py`, `sidecar.py`, `preflight.py`, `attest.py`,
   `rehearse.py`, `channels.py` or any MUST-NOT-TOUCH surface.** `sidecar.py`,
   `rosbag2.py` and `test_capture_ingest.py` changed on disk during my card —
   that is the concurrent PS-G ingest card, not me. `sidecar_sync_block()` is
   offered for PS-B/PS-G to fold into `extra`; **nothing calls it yet**, so the
   wiring into the recorder is an open hand-off (§8).

## 7 · does_not_prove

1. **Nothing here has seen a robot.** Every number in §4 comes from a
   deterministic synthetic fixture built by this same module. The detectors have
   never run on a real accelerometer, a real frame, or a real
   `wireless_remote[40]` block, and the *first* time they do will be tomorrow.
2. **A constant pipeline latency is indistinguishable from a clock offset.**
   Exposure, driver buffering and transport delay that are identical for every
   event of a ritual are absorbed into the reported offset. The brackets bound
   only the part that varies. The `wireless_remote`↔`wirelesscontroller`
   cross-check bounds one path's delay against another's; neither against truth.
3. **The `wireless_remote` key offset is UNVERIFIED.** It is transcribed from
   community descriptions of Go2 EDUs, which is why `wireless_remote_keys` has no
   default `key_offset` and the candidate lives in a constant named
   `..._UNVERIFIED`. PS-D settles it by pressing one button on the bench.
4. **Between two rituals there is no evidence.** A step inside a blind interval
   is aliased into the drift. The module reports the interval; it did not look
   inside it.
5. **The ritual-level step test assumes the drift is common across the session.**
   A clock whose *rate* changed at the same instant is reported as a step of the
   wrong size. Declared in the class docstring, not hidden.
6. **The matcher's ambiguity test only excludes alternatives the observed events
   permit.** A whole train shifted together — a buffer flushed late, a driver
   that batched a ritual — passes every alignment check this module can run.
7. **This module does not read point clouds.** The 10 s twist exists so both
   LiDARs record the same motion for the downstream extrinsic tools; nothing here
   measures a LiDAR-to-IMU alignment, and the card's "visible in both LiDARs"
   claim is a property of the *ritual*, not of any code I wrote.
8. **Python 3.10 was verified STATICALLY only** (`ast.parse(feature_version)`).
   No 3.10 interpreter exists on this host. The same caveat PS-A recorded.
9. **`sidecar_sync_block` round-trips through `make_manifest` in a test; no
   recorder calls it.** Until PS-B/PS-G wire it, a real bag will not carry a sync
   digest.
10. **The tolerance in M4 is this design's own reported uncertainty, not an
    independent check.** It is honest arithmetic about brackets, and it would
    move with any real channel whose sampling differs from the fixture's.

## 8 · Hand-offs before the session

1. **PS-B / PS-G:** fold `sidecar_sync_block(fit)` into the manifest `extra`
   (keys are flat and survive `reject_privileged_fields`; verified in
   `test_the_fit_round_trips_through_the_bag_sidecar_extra_by_digest`).
2. **PS-F run sheet:** add the ritual at SYNC-OPEN, SYNC-CLOSE **and every
   battery swap**. `python3 scripts/parcel_capture/syncevents.py --ritual-card`
   prints the sheet; it needs no dependency and runs on any Python 3.10+.
3. **PS-D:** settle `WIRELESS_REMOTE_KEY_OFFSET_UNVERIFIED` on the bench, and
   record the per-channel sample period each detector needs as its
   `sample_bracket_ns` — the brackets in every uncertainty here come from it.
4. **Kit:** a torch that emits **white and 850 nm**, and something hard to tap
   the payload plate with. Both are on the ritual card; neither is in the BOM.
