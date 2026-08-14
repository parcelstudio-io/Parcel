# PS-C status — clock discipline

**Card:** PS-C (`README.md` §PS-C) · **Executor:** Opus · **Date:** 2026-08-13
**Base:** `dd2e857` (working tree; the board cites `406f9d6`)
**Verdict:** complete. Five card gates measured, twelve shipped-module mutants
seeded and caught, one OWNS-adjacent design addition flagged below (§D-1).

---

## What I built

| Path | Lines | What it is |
|---|---|---|
| `scripts/parcel_capture/clockmap.py` | 2,553 | `ClockSample` (the offset triple + its bracket), `ClockMapV1` (per-device + per-host fits, self-sufficient for conversion), the segmenting fitter, `interrogate()` (bracket discipline), append-only fsynced sample log, `sidecar_clock_block()` for PS-B, `planned_elapsed_ns()` (the card's schedule, executable), a read-only probe-availability CLI. |
| `tests/test_clockmap.py` | 1,379 | 130 cells: every card gate with a paired refutation. |

Nothing outside my OWNS list was created or modified.

```
$ git status --porcelain scripts/parcel_capture/ tests/test_clockmap.py
?? scripts/parcel_capture/
?? tests/test_clockmap.py

$ git diff --stat -- src/parcel_robot/runtime.py src/parcel_robot/pose.py \
    src/parcel_robot/navigation src/parcel_robot/route_memory \
    src/parcel_robot/bags evals scripts/ci_gate.py
(empty)
```

`scripts/parcel_capture/` shows as one untracked directory because PS-A created
it and PS-B/PS-D landed files in it concurrently; `clockmap.py` is the only file
in that tree I wrote.

### The design point the card is about

Three things had to be true or the artifact is worthless in six months.

**1. A bracket, not a timestamp.** A sample is `t1` (host monotonic, before the
interrogation), the wall clock read beside it, the device's own clock reading,
and `t4 - t1`. The device read happened *somewhere inside* `[t1, t4]` and we do
not know where, so the offset is `device - (t1 + rtt/2)` and it is uncertain by
**±rtt/2** — the irreducible NTP bound. `round_trip_ns` has **no default**,
because a fabricated bracket is a fabricated confidence. A passive one-way
receipt reduces to the same algebra with the bracket set to the widest interval
the stamp could belong to.

**2. Two kinds of uncertainty that must never be mixed.** The statistical half
(Student-t 95% from residual scatter) shrinks like `1/√n`. The systematic half —
the worst-case bias the brackets permit — **does not shrink at all**, because an
asymmetric path biases every sample the same way and averaging a million of them
removes none of it. Both are computed exactly: `Σ|c_i|·b_i` over the OLS weights,
which collapses to `mean(b)` at the fit's own mean instant and to
`Σ|x_i−x̄|·b_i / Sxx` for the slope. `total` is `None` — not zero, not the
statistical part alone — when either half is unknown, and an unbounded relation
makes the whole map uncertifiable.

**3. Segment before fitting.** A clock that jumps does not drift. Binary
segmentation (O(1) segment fits from prefix sums) splits the series wherever a
discontinuity clears the two candidate segments' combined prediction
uncertainty; only then is each segment fitted. Measured consequence in §C3: the
same 500 ms step turns a single-line fit into **772.5 ppm against a true 40 ppm**.

The host's own `realtime`-vs-`monotonic` relation is fitted too, and that is
what the card's third clock field is for: `bags/schema.py:default_clocks()`
writes `recording_monotonic_origin_ns: 0`, a placeholder for a number nobody
ever measured, and `CLOCK_MONOTONIC` has a per-boot arbitrary epoch. Without
that fit, every `received_monotonic_ns` in every bag is meaningless outside this
boot.

---

## MEASURED claims

Every row is a command that was executed and its verbatim output. The two
estimates in this document are labelled as estimates in §does_not_prove.

### C1 — the suite

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_clockmap.py -q
........................................................................ [ 55%]
..........................................................               [100%]
130 passed in 2.36s
```

### C2 — GATE: seeded 40 ppm recovered, with an uncertainty

Fixture: 900 s session on the module's own schedule (opening burst at 10 Hz,
1 Hz cruise, closing burst), n=1081, 2 ms round trip, ±50 µs jitter.

```
$ .parcel/bin/python -c "<build map, 40 ppm, no step>"
  drift_ppm=39.999788  unc_total=2.936069 ppm (sys 2.930165 + stat 0.005903)  |err|=0.000212
  offset_ns=-4182000725  unc_total=1001764.7 ns  basis=ols  n=1081
```

**Stated tolerance: ±3.0 ppm**, and it is not a fudge factor — it is the
uncertainty this design reports for *itself* on this fixture (2.94 ppm, of which
2.93 ppm is the irreducible bracket bound at a 2 ms round trip over 900 s). A
recovery claim tighter than the reported bound would be a claim the evidence
cannot support. Measured error: **0.000212 ppm**.

Coverage, which is the property that actually matters, over 60 independent noise
seeds (`test_the_reported_drift_interval_covers_the_truth_across_60_noise_seeds`):
**60/60 intervals contained the true 40 ppm.**

### C3 — GATE: a seeded 500 ms step is a step, not drift

```
$ .parcel/bin/python -c "<same fixture + 500 ms step at t=450 s>"
  steps=1  magnitude=499997514 ns (seeded 500000000)  err=-2486 ns  unc=5200992 ns  gap=1000000000 ns
  seg0 drift=39.997073 ppm +/- 6.122500  n=540
  seg1 drift=40.009767 ppm +/- 6.109125  n=541
  REFUTATION naive one-line fit: 772.5 ppm (19x the true 40 ppm)
```

One step, magnitude within **2.5 µs** of the seeded 500 ms, located to within
the 1 s sampling gap it happened in and **not claimed narrower**. Both segments
still recover 40 ppm inside the stated tolerance. The refutation is the point:
the estimator without segmentation reports 772.5 ppm — its error (732 ppm) is
**four orders of magnitude** past the segmented fit's.

### C4 — GATE: asymmetric round trip widens the offset uncertainty

```
$ .parcel/bin/python -c "<same offset and drift, symmetric vs one-sided path>"
  rtt=  2000000 ns frac=0.50 -> offset_unc_total= 1001764.7 ns (sys  1000000.0 + stat 1764.7) |bias|=      725 ns  covered=True  covered_by_stat_only=True
  rtt= 20000000 ns frac=0.95 -> offset_unc_total=10001764.7 ns (sys 10000000.0 + stat 1764.7) |bias|=  8999275 ns  covered=True  covered_by_stat_only=False
```

The uncertainty widens 10x (1.00 ms → 10.00 ms), and the widening is entirely in
the half that cannot be averaged away. **The last column is the refutation and
the reason the assertion is not tautological:** under the one-sided path the
point estimate is biased by 9.0 ms, the honest interval still contains the truth,
and an interval quoting the statistical part alone (1.76 µs) would have
*confidently excluded* it. The systematic term is load-bearing, not decoration.

Separately, when the round trip **varies**, the asymmetry is directly detectable
as the NTP wedge (slope of residual against bracket, `2α−1`):

```
  request_leg_fraction=0.50 -> asymmetry_slope=0.0 detected=False
  request_leg_fraction=1.00 -> asymmetry_slope=1.0 detected=True
```

It is reported and **not corrected for** — correcting would trade a bounded
error for an unbounded modelling assumption. When the round trip does not vary,
a constant asymmetry is undetectable *in principle*; that is `does_not_prove` #2
and a dedicated cell asserts the module says so rather than guessing.

### C5 — GATE: NaN / inf / None refused, never defaulted

35 parametrised cells: 5 clock fields × {NaN, +inf, −inf, 1.5, `True`,
`"1786000000"`, −1}, plus 4 more for `None` in each required field. Each asserts
the **exact** `ClockRefusalReason`, not merely that something raised.

```
tests/test_clockmap.py::test_seeded_failure_every_malformed_clock_field_is_refused[...]  35 passed
tests/test_clockmap.py::test_seeded_failure_none_in_a_required_clock_field_is_refused[...] 4 passed
```

Plus the fail-closed rule this card added on its own evidence: a
`host_realtime_ns` below 2020-01-01Z is an **unset RTC**, not a timestamp. The
Jetson ships with no RTC battery, so this is the single most likely clock fault
of the session — trivially fixable *at* the session and unfixable afterwards.
The refusal names the fix (`sudo date -s`).

### C6 — GATE: round-trips through the PS-B sidecar `extra` by digest

PS-B's `sidecar.py` landed while I was working; I tested against the frozen
surface it must call, `bags/schema.py:make_manifest` (imported and called, never
edited).

```
$ .parcel/bin/python -c "<make_manifest(source='hardware', clocks=sidecar_clock_block(m), extra={'clock_map': m.to_dict(), ...}); validate_manifest; json round trip; from_dict>"
map_digest      = 38ab86c2028a1d344e913a0e56df6763bb66566a07dd878b4fba6e760a1dbf22
after_roundtrip = 38ab86c2028a1d344e913a0e56df6763bb66566a07dd878b4fba6e760a1dbf22
digest_stable   = True
canonical_bytes_equal = True
manifest clocks: {"clock_map_certifiable": true, "clock_map_devices": ["go2"], "clock_map_sample_sha256": "6353ef3a...", "clock_map_schema": "parcel.capture.clockmap.v1", "clock_map_sha256": "38ab86c2...", "clock_map_shortfalls": [], "recording_monotonic_origin_ns": 12000000100, "source_clock": "sensor"}
default_clocks recording_monotonic_origin_ns = 0 -> ours = 12000000100
```

The last line is the concrete hand-off: `sidecar_clock_block()` replaces the
schema's `0` placeholder with the first host instant the map actually observed,
and carries both digests so the bag is bound to the fit that can interpret it.

### C7 — the schedule's two halves, each measured

The card specifies ~1 Hz plus dense bursts. `planned_elapsed_ns()` makes that
executable and `_coverage` checks it was *achieved* (derived from the recorded
times, never asserted by the prober). Both halves earn their place:

```
burst+cruise  n=1081  drift_unc_total=2.936069 ppm (sys 2.930165 + stat 0.005903)
uniform       n=1081  drift_unc_total=3.337036 ppm (sys 3.330250 + stat 0.006786)
bursts-only: steps=1 located within gap=880.0 s; certifiable=False
burst+cruise: steps=1 located within gap=1.0 s
```

Bursts beat uniform sampling at equal n (they maximise `Sxx`, the drift lever).
The cruise is what makes a step *locatable*: without it the same step is only
placed to within the 880 s hole it happened in, and the map refuses to certify
and says why. Neither claim is asserted in prose only —
`test_end_bursts_beat_uniform_sampling_for_drift_at_equal_sample_count` and
`test_but_bursts_alone_miss_a_mid_session_step_that_the_cruise_catches`.

### C8 — read-only, and no vendor SDK was installed

```
$ .parcel/bin/python -c "<find_spec over the vendor set>"
rclpy: absent
cyclonedds: absent
unitree_sdk2py: absent
pyrealsense2: absent
cv2: absent
mcap: absent
zstandard: absent
unitree_lidar_sdk_pybind: absent
```

The module names those strings only as data fed to `importlib.util.find_spec`,
which is a path lookup that never executes a module. An AST pin asserts no
import statement (or dotted prefix of one) names any of them, no symbol names a
publisher / `ControlManager` / `Move` / `set_target` / lease, and neither
`import_module` nor `__import__` appears. A negative control proves the scan
does not fire on the legitimate vendor *sensor* names.

### C9 — the CLI refuses cleanly on this hardwareless box

```
$ .parcel/bin/python -m scripts.parcel_capture.clockmap --check
[ ABSENT] go2   read `tick` off a `lowstate` message, or the `sportmodestate` stamp
[ ABSENT] d455  frame metadata timestamp plus its timestamp DOMAIN
[ ABSENT] l2    cloud/IMU packet stamp over the add-on L2's own transport
[PRESENT] orin  host clock pair (this IS the recording host)

REFUSED: no clock probe is possible for: d455, go2, l2
This host cannot record offset triples for those devices. Run this on the Orin
inside the ROS 2 Humble environment that owns the vendor SDKs. Recording a
session without them leaves their timestamps permanently unrecoverable.
$ echo $?
2
```

Exit 2, no traceback, and the message says what to do. Asserted by subprocess.

### C10 — it runs on the Orin as a plain script

The deploy invocation has no editable install and no `PYTHONPATH`. Measured on
`/usr/bin/python3`, which genuinely cannot import `parcel_robot`
(`ModuleNotFoundError` confirmed separately), run from `/`:

```
$ cd / && env -u PYTHONPATH /usr/bin/python3 .../scripts/parcel_capture/clockmap.py --selftest
ClockMapV1  session=clockmap-selftest  host=selftest-host
  origin=simulation  fixture=clockmap-selftest  samples=1081
  digest=1021eed5584d85c49eefc0900e8429a47781b0a03e23fcc185b962a884e7c178
  certifiable=True
  [go2:device_source_to_host_monotonic] n=1081 span=900.0s segments=2 steps=1
    seg0 n=540 span=449.0s basis=ols
      offset@ref -4192.484443 ± 1.002560 ms (sys 1.000000 + stat 0.002560, two-sided-95)
      drift      +40.000355 ± 6.122851 ppm (sys 6.105085 + stat 0.017766, two-sided-95)
    seg1 n=541 span=450.0s basis=ols
      offset@ref -3671.536105 ± 1.002397 ms (sys 1.000000 + stat 0.002397, two-sided-95)
      drift      +40.009182 ± 6.108525 ppm (sys 6.091923 + stat 0.016602, two-sided-95)
    STEP at 461501000000 +499.999 ms ± 5.201 ms (located within a 1.000s gap)
exit=0
```

Same digest as under the project venv, on a different interpreter with a
different `sys.path`. Whole run: **0.085 s for 1,081 samples**.

### C11 — Python 3.10, honestly

**No Python 3.10 process was executed. There is no 3.10 interpreter on this
host** (`.parcel/bin/python -V` → 3.14.4; `/usr/bin/python3*` → only 3.14). The
3.10 claim is therefore **static**:

```
$ .parcel/bin/python -c "<ast.parse(feature_version=(3,10)) on the module + 3 mutants>"
ast.parse(clockmap.py, feature_version=(3,10)): ACCEPTED
REJECTED 'type A = int' -> Type statement is only supported in Python 3.12 and greater
REJECTED 'def f[T](x: T) -> T:\n ' -> Type parameter lists are only supported in Python 3.12 and greater
REJECTED 'try:\n    pass\nexcept* ' -> Exception groups are only supported in Python 3.11 and greater
```

The mutants demonstrate the check really rejects newer syntax rather than
accepting everything. `ruff target-version = py310` is a second static check,
and a symbol scan rejects `StrEnum`/`tomllib`/`file_digest`/`itertools.batched`/
`ExceptionGroup`. Every import is stdlib (`itertools.pairwise` and
`dataclass(slots=True)` both shipped in 3.10) plus
`parcel_robot.capture.channels` and `parcel_robot.evidence_origin`, which PS-A
pinned as a 3.10-safe stdlib leaf. Measured leaf property:

```
$ .parcel/bin/python -B -c "<sys.modules delta on importing scripts.parcel_capture.clockmap>"
[]      # nothing outside stdlib + parcel_robot + scripts
```

### C12 — lint and CI gate

```
$ .parcel/bin/python -m ruff check --output-format=concise scripts/parcel_capture/clockmap.py tests/test_clockmap.py
All checks passed!

$ .parcel/bin/python scripts/ci_gate.py --tier commit
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                ...collisions=0 false_arrival=0...
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        ...
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.57s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.35s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.54s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              4491 passed, 9 skipped, 36 deselected, 5 warnings in 189.86s
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 201.9s
```

This card added **zero** new `(file, rule)` fingerprints to the ruff ratchet.

**Note for the auditor — a transient red I did not cause.** My first gate run at
09:35Z failed on `ruff  11 violation(s), baseline 7, new 4 ->
tests/test_capture_preflight.py::{F401,PLW1510,RUF015,UP031}`. That is PS-D's
file, caught mid-write (its mtime moved twice during my run, as did PS-B's
`record.py`/`sidecar.py`). Re-running four minutes later gave the PASS above
with `new 0`. **The gate is a moving target while four cards land in parallel;
the closing gate for this tranche should be Fable's, not any one card's.**

---

## Seeded-failure table

Twelve mutations applied to the **shipped module on disk**, suite re-run, source
restored, tree verified byte-identical. Per PS-A's harness finding, every run
used `-B`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider` and an explicit
`__pycache__` removal, so a same-size mutation cannot contaminate the next run.

| # | Gate | Seeded fault | Proof it was caught |
|---|---|---|---|
| M1 | Step is a step | step scan disabled (`_find_splits` returns immediately) | `FAILED test_a_seeded_500ms_step_is_reported_as_a_step` |
| M2 | Uncertainty has a systematic half | bracket bound zeroed in the offset fit | `FAILED test_no_estimate_is_ever_a_bare_number` |
| M3 | Fail closed on clocks | `_require_ns` coerces floats with `int(value)` | `FAILED test_seeded_failure_every_malformed_clock_field_is_refused[1.5-…]` |
| M4 | Zero never means unknown | unestimable statistical term reported as `0.0` | `FAILED test_a_short_segment_fails_closed_rather_than_claiming_zero_drift` |
| M5 | Unknown drift ≠ zero drift | single sample reports `drift_ppm=0.0` | same cell |
| M6 | Unset RTC refused | `REALTIME_EPOCH_FLOOR_NS = 0` | `FAILED test_an_unset_rtc_is_refused_at_the_session_not_recorded` |
| M7 | Coverage gates certification | coverage shortfalls dropped from `certification_shortfalls` | `FAILED test_but_bursts_alone_miss_a_mid_session_step_that_the_cruise_catches` |
| M8 | Origin fails closed | `UNKNOWN` origin accepted | `FAILED test_seeded_failure_origin_declaration_fails_closed[unknown-…]` |
| M9 | Bracket discipline | `interrogate` reads the device clock **before** starting the bracket | `FAILED test_interrogate_brackets_the_device_read_in_the_only_honest_order` |
| M10 | Step threshold is derived | threshold reduced to the 1 ns floor alone | `FAILED test_a_seeded_500ms_step_is_reported_as_a_step` |
| M11 | Unknown = absent | unmeasured host pair bracket treated as `0.0` | `FAILED test_a_map_without_the_host_pair_bracket_is_not_bounded_in_wall_time` |
| M12 | Digest binds inputs | `sample_digest` replaced by a constant | `FAILED test_seeded_failure_one_mutated_sample_moves_the_map_digest` |

```
$ .parcel/bin/python <scratchpad>/mutate_clockmap.py
M1 …: CAUGHT | FAILED tests/test_clockmap.py::test_a_seeded_500ms_step_is_reported_as_a_step
M2 …: CAUGHT | FAILED tests/test_clockmap.py::test_no_estimate_is_ever_a_bare_number
M3 …: CAUGHT | FAILED tests/test_clockmap.py::test_seeded_failure_every_malformed_clock_field_is_refused[1.5-non_integer_field-host_monotonic_ns]
M4 …: CAUGHT | FAILED tests/test_clockmap.py::test_a_short_segment_fails_closed_rather_than_claiming_zero_drift[1-single_sample-False]
M5 …: CAUGHT | FAILED tests/test_clockmap.py::test_a_short_segment_fails_closed_rather_than_claiming_zero_drift[1-single_sample-False]
M6 …: CAUGHT | FAILED tests/test_clockmap.py::test_an_unset_rtc_is_refused_at_the_session_not_recorded
M7 …: CAUGHT | FAILED tests/test_clockmap.py::test_but_bursts_alone_miss_a_mid_session_step_that_the_cruise_catches
M8 …: CAUGHT | FAILED tests/test_clockmap.py::test_seeded_failure_origin_declaration_fails_closed[unknown-None-origin_not_declared]
M9 …: CAUGHT | FAILED tests/test_clockmap.py::test_interrogate_brackets_the_device_read_in_the_only_honest_order
M10 …: CAUGHT | FAILED tests/test_clockmap.py::test_a_seeded_500ms_step_is_reported_as_a_step
M11 …: CAUGHT | FAILED tests/test_clockmap.py::test_a_map_without_the_host_pair_bracket_is_not_bounded_in_wall_time
M12 …: CAUGHT | FAILED tests/test_clockmap.py::test_seeded_failure_one_mutated_sample_moves_the_map_digest
restored_identical=True sha256=4fe706a1fa41f010
clean_rerun_exit=0 | 130 passed in 2.41s
```

**Two findings from the harness worth recording, because both were real gaps I
would otherwise have shipped:**

1. **M4 was MISSED on the first run.** The gate asserted a short segment is not
   `is_bounded` — but `is_bounded` is dominated by the *drift* half, so an
   offset uncertainty that faked its statistical part as `0.0` slipped through.
   Fixed by asserting the offset half explicitly (`statistical is None`,
   `total is None`, `residual_std_ns is None`). The property was right; the
   assertion was not tight enough to hold it.
2. **The read-only pin had an escape hatch**, found by its own seeded-failure
   cell on the first run of the test file: `from
   unitree_sdk2py.go2.sport.sport_client import SportClient` walked straight
   past a pin that only knew the top-level name `unitree_sdk2py`. The pin now
   expands every dotted prefix. **Any card in this tranche running an
   import-name pin should check the same thing.**

---

## OWNS deviations and design calls for the auditor

**D-1 — a fifth sample field the card did not enumerate: `host_pair_bracket_ns`.**
The card's triple is `(host_monotonic_ns, host_realtime_ns, device_source_ns,
round_trip_ns)`, and all four are present and required. I added one **optional**
field: the width of the interval containing the wall-clock read, i.e. the gap
between the monotonic reads that straddle it.

Reason: the `round_trip_ns` bracket bounds the *device* offset, and nothing in
the card's four fields bounds the *host realtime vs monotonic* offset — which is
the relation that fixes the arbitrary-epoch problem the card exists to solve.
Without it that fit has a statistical uncertainty and no systematic bound, so it
is honest only if it says so. It defaults to `None`, and `None` produces
`systematic=None → total=None → is_bounded=False → not certifiable`: the
**non-permissive** outcome, per board rule 3. `interrogate()` fills it in for
free from clock reads it already makes, so any prober using the supplied helper
supplies it. Measured both ways in
`test_a_map_without_the_host_pair_bracket_is_not_bounded_in_wall_time`.

**D-2 — the map fits a per-host relation, not only per-device ones.** The card
says "per device (dog, D455, L2, Orin)". A device relation is emitted for every
`SourceDevice` that has samples (any of PS-A's seven, so GNSS is supported if it
turns up), plus exactly one pooled `host_realtime → host_monotonic` relation.
For the Orin specifically, that host relation *is* its clock relation — the Orin
is the recording host, so there is no second clock to interrogate. This is
flagged rather than assumed because it changes what "four devices mapped" means.

**D-3 — the schedule is enforced by derivation, not by declaration.** I added
`planned_elapsed_ns()` (the card's "~1 Hz plus dense bursts" as executable code)
and `ScheduleCoverage`, which recomputes what the samples *actually* covered
from their recorded times. A prober cannot assert it kept the schedule. The four
schedule constants each carry a derivation in the module docstring
(`MIN_BURST_SAMPLES = 30` from the Student-t table flattening; `BURST_WINDOW_NS
= 10 s` from the drift accrued at an assumed worst case; `MAX_CRUISE_GAP_NS =
3 s` from two consecutive lost probes; `MIN_SPAN_NS = 300 s` from
`bracket/drift` resolvability), and `ASSUMED_WORST_CASE_DRIFT_PPM = 100` is
explicitly **labelled an engineering assumption**, not a derivation.

**D-4 — `synthesize_samples()` ships in the module, not the test.** PS-E's
rehearsal needs synthetic clock samples driving the real stack, and a fixture
that diverges from the one the tests use is a fixture that proves nothing. It is
deterministic (`random.Random(seed)`) and its docstring states that any map
built from it must carry a synthetic origin — which `ClockMapV1` enforces, so a
rehearsal map cannot be mistaken for a session map even after both are in a bag.
One cell builds samples by hand with exact integer arithmetic so the fit is not
only ever checked against its own generator.

**D-5 — `bags/schema.py` is imported and called, never edited.** `bags`
constants I depend on (`REQUIRED_CLOCK_KEYS`) are **mirrored as a literal** so
this module stays importable without the autonomy package's bag layer, and
`test_sidecar_clock_block_mirrors_the_live_bag_schema` pins the mirror against
the live constant. Precedent: `commissioning/limits.py`'s `FOOTPRINT_RADIUS_M`.

**No blocker.** Nothing about this card required a MUST-NOT-TOUCH surface.

---

## does_not_prove

1. **Nothing here has interrogated a clock.** Every number in this document
   comes from a synthetic fixture. What is proven is that the *estimator* is
   honest under seeded step, drift, jitter and asymmetry — not that any device
   behaves that way. The Go2's `tick`, the D455's timestamp domain, and the L2's
   packet stamp are all **unmeasured**, and the first real evidence is Stage 0.
2. **The probe callables do not exist.** `interrogate()` owns the bracket
   discipline and takes a `read_device_clock` callable; nothing in this repo
   supplies one, because doing so needs `rclpy` / `pyrealsense2` /
   `unilidar_sdk2`, none of which is installed (C8) and none of which may be
   installed into `.parcel/`. **This card produces a fitter and a discipline,
   not a running prober.** Wiring the three callables on the Orin is the single
   largest remaining risk to the session, and it belongs on the Stage-0 sheet.
3. **The L2 python import name is a guess and is marked as one.**
   `unitree_lidar_sdk_pybind` is what `PROBE_REQUIREMENTS` looks for; I did not
   verify it against an installed SDK. Fail-closed, so it reports ABSENT — which
   on the day is indistinguishable from "not installed". **PS-D must resolve the
   real name**, or the L2 clock probe will silently look unavailable.
4. **A constant asymmetry at a constant round trip is invisible, permanently.**
   The bound stays honest (the truth is inside the interval) but the point
   estimate is biased and no estimator can see it. Only a symmetric-by-
   construction transport, or a hardware timestamp, removes this.
5. **Drift is only fitted over the observed span.** Extrapolation past the last
   sample is bounded by the quoted drift uncertainty and nothing else, and a
   clock that steps *after* the closing burst leaves no evidence at all. This is
   why the closing burst is a certification requirement rather than a nicety.
6. **No absolute time is claimed.** With no GNSS discipline and no PTP
   grandmaster the whole session floats against UTC by the host's own realtime
   error, which this map cannot measure. If the ZED-F9P (matrix row 17) turns
   out to be on hand, it is the **only** absolute reference available and PS-D
   should say so loudly.
7. **The step detector's threshold is calibrated, not proven optimal.** It
   catches a 500 ms step under a 2 ms bracket by a factor of ~100 and correctly
   declines a 100 µs step under the same bracket. Where exactly it turns over
   between those is **not** characterised, and a real clock's steps may not be
   the clean discontinuities I seeded. Binary segmentation is also greedy: it
   finds the most significant split first, so a pathological pattern of many
   small steps could be mis-segmented. The `MAX_STEPS = 8` cap is procedural,
   and hitting it is surfaced as a certification shortfall rather than absorbed.
8. **The read-only pin is a static AST scan, not a sandbox** (PS-A's caveat,
   inherited). It proves no import statement or symbol in this module reaches a
   motion surface or a vendor SDK. It does not prove the process *cannot* open a
   socket. The stronger guarantee remains the absent SDK (C8).
9. **The 3.10 claim is static** (C11). No 3.10 interpreter exists on this host,
   so nothing was executed under 3.10; syntax and known post-3.10 symbols are
   checked, a behavioural difference would not be. **The first real
   verification is `python3.10 -m scripts.parcel_capture.clockmap --selftest` on
   the Orin, and it belongs on the Stage-0 sheet.**
10. **Performance is measured on this dev host only** — 1,081 samples fitted in
    0.085 s. An hour of 1 Hz sampling plus bursts is ~5,800 samples and the
    segmentation scan is O(n) per level; I have **not** measured it on the Orin
    and the arithmetic that it stays sub-second there is an **estimate**.
11. **`ClockSample` accepts `round_trip_ns = 0`.** It is a legitimate reading
    for a same-process clock pair, but it produces a zero systematic bound, so a
    caller who passes it for a real network interrogation gets an overconfident
    interval. There is no default (the field is required), but there is no floor
    either.
12. **This proves nothing about MCAP, sidecar crash-safety, attestation, or
    bandwidth.** Those are PS-B/PS-D/PS-E. What PS-C hands them is a type that
    refuses to be filled in wrongly, a digest to bind it by, and a `clocks`
    block that fills in the `recording_monotonic_origin_ns` placeholder
    `bags/schema.py` has carried since the sim MVP.

---

## The one thing to carry into tomorrow

If nothing else on this card survives review, this must: **the offset triples
have to be recorded live, on the day, for every device, or the bags are
unusable across devices forever.** The fitter can be rewritten next week. The
samples cannot be collected next week. `--check` currently refuses on every
device but the Orin, which means **as of right now the session would record no
clock samples at all** — closing that is PS-D's probe wiring and it is the
highest-risk open item on the board.
