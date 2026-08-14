# PS-E status — budget + synthetic-publisher rehearsal

**Card:** PS-E (`README.md` §PS-E) · **Executor:** Opus · **Date:** 2026-08-13
**Base:** `dd2e857` (working tree; the board cites `406f9d6`)
**Verdict:** complete. Both card halves measured, 14 shipped-module mutants
seeded and caught, **six cross-card composition findings** reported below
rather than worked around.

---

## What I built

| Path | Lines | What it is |
|---|---|---|
| `scripts/parcel_capture/budget.py` | 1,471 | The arithmetic. Per-channel load models with a declared `LoadBasis`, the D455 profile type and its declared-mode allow-list, exact framing measured against PS-B's own MCAP writer, session-length bounds, a real fsynced sustained-write measurement, and the `UNKNOWNS` list the CLI prints. |
| `scripts/parcel_capture/rehearse.py` | 1,772 | The rehearsal. Deterministic synthetic publishers for all 21 recorded channels, driving the **real** PS-A/B/C/D stack; six seeded fault classes including a real `SIGKILL` and a real kernel write refusal; a classifier that never sees the plan; and `check_expectations`, which asserts both that every seeded fault is named and that no unseeded fault is claimed. |
| `tests/test_capture_rehearsal.py` | 1,171 | 88 cells over 5 gate groups, every property paired with a seeded-failure or refutation companion. |
| `scrum/20260813/task_1/BANDWIDTH_BUDGET.md` | 301 | The decision table, the per-channel derivation, the measured write rate labelled *dev-host*, and what the budget does not know. |

Nothing outside my OWNS list was created or modified (C11).

### The one sentence this card serves

> **The first time this stack runs must not be on the dog.**

It has now run end to end — budget → preflight → attestation → recorder → clock
map → sidecar → classification — four times per `--selftest`, four more times
per suite run, and once on a bare `/usr/bin/python3` from outside the repo, on a
box with no ROS, no vendor SDK, no camera and no robot.

---

## MEASURED claims

Every row was executed; the command and its output are verbatim. This document
makes **exactly one estimate**, labelled at §does_not_prove 10. The
extrapolation a reader will most want — this host's throughput scaled to an Orin
NX — is explicitly **refused** at §does_not_prove 3 rather than made.

### C1 — the suite

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_rehearsal.py -q
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 10.05s
```

### C2 — the plan's anchors, verified rather than copied

`PHYSICAL_SESSION_PLAN.md:69-72` quotes ≈132 MiB/s ≈464 GiB/h and ≈58 MiB/s
≈205 GiB/h. Derived independently from the format names:

```
$ .parcel/bin/python -c "<pixel arithmetic for four modes>"
1280x720@30 IR=False: 4,608,000 B/frame x 30 = 138,240,000 B/s = 131.84 MiB/s = 463.49 GiB/h
848x480@30 IR=False:  2,035,200 B/frame x 30 =  61,056,000 B/s =  58.23 MiB/s = 204.71 GiB/h
1280x720@30 IR=True:  6,451,200 B/frame x 30 = 193,536,000 B/s = 184.57 MiB/s = 648.88 GiB/h
848x480@30 IR=True:   2,849,280 B/frame x 30 =  85,478,400 B/s =  81.52 MiB/s = 286.59 GiB/h
```

**Both anchors are correct**, to the precision they were quoted at. They are
colour+depth only — no IR pair, no other channel, no recording framing. The
whole-rig figures and the decision table are in
[BANDWIDTH_BUDGET.md](BANDWIDTH_BUDGET.md) §1.

`test_the_plans_own_anchors_reproduce_from_the_derivation` re-derives them in
the suite rather than comparing against a stored constant, and
`test_the_d455_figure_is_pixels_times_bytes_times_frames` does the same for the
module's own output — which is why mutant **M7** (depth counted at 1 B/px) is
caught.

### C3 — the decision table

```
$ .parcel/bin/python -m scripts.parcel_capture.budget
D455 profile                 MiB/s   GiB/hour    msg/s  cam %  hours @ free
----------------------------------------------------------------------------
1280x720@30 CD              134.90     474.27     1882  97.9%       unknown
1280x720@30 CDI             187.66     659.73     1942  98.5%       unknown
1280x720@15 CDI              95.35     335.22     1882  97.0%       unknown
848x480@60 CDI              166.16     584.15     2062  98.3%       unknown
848x480@30 CD                61.29     215.49     1882  95.4%       unknown
848x480@30 CDI               84.60     297.43     1942  96.7%       unknown
848x480@15 CDI               43.83     154.08     1882  93.5%       unknown
848x480@30 DI                49.66     174.58     1912  94.3%       unknown
640x480@30 CDI               64.61     227.14     1942  95.6%       unknown
424x240@30 CDI               23.46      82.49     1942  87.9%       unknown

hours @ free: UNKNOWN — pass --free-bytes, or run PS-D's preflight on the Orin. Unknown free space is not a long session.
```

The `unknown` column is the fail-closed rule working: the Orin's free space is
not known to this repo, so no session length is asserted. **Recommendation:
848×480@30 colour + depth + IR pair** (297.4 GiB/hour), reasoning in the budget
doc §1.

### C4 — sustained write, MEASURED, on the dev host

```
$ .parcel/bin/python -c "measure_sustained_write('/home/jaewoo-jang/.cache/parcel-pse', total_bytes=32*1024**3, block_bytes=4*1024*1024, fsync_interval_s=1.0)"
{"path": "/home/jaewoo-jang/.cache/parcel-pse", "host": "jaewoo-jang-parcel",
 "filesystem": "ext4", "bytes_written": 34359738368, "seconds": 8.67306,
 "block_bytes": 4194304, "fsync_count": 9, "fsync_interval_s": 1.0,
 "bytes_per_second": 3961662603.153, "mib_per_second": 3778.136,
 "gib_per_hour": 13282.509, "note": "dev-host, to be re-measured on the Orin"}
```

**3,778 MiB/s — dev-host, to be re-measured on the Orin.** Crucial T700 4 TB
(`CT4000T700SSD3`) on ext4, `/dev/nvme0n1p5`, confirmed non-rotational
(`/sys/block/nvme0n1/queue/rotational` = 0). 32 GiB written sequentially with an
fsync every second and a final fsync inside the timed window — not `dd`, which
on a host with 246 GiB of RAM would measure the page cache. **The Orin is not
reachable from this host and this number says nothing about it**; the Stage-0
sheet has a line for the Orin's own figure (`STAGE0_RUN_SHEET.md:237`).

Headroom against the recommended profile on this host: **44.7×**.

### C5 — throughput through the whole capture stack, in real time

Raw disk speed is not what the recorder achieves. This drives PS-B's real
`CaptureRecorder` at full payload size — JSON envelope per message, MCAP
framing, buffered handle, 1 Hz fsync:

```
$ .parcel/bin/python -c "measure_stack_throughput(...)"
{"bag_bytes": 355565456, "messages": 7768, "seconds": 0.376206, "mib_per_second": 901.351,
 "messages_per_second": 20648.3, "profile": "848x480@30 CDI",
 "required_mib_per_second": 84.6, "speedup_vs_realtime": 10.63}
{"bag_bytes": 787795856, "messages": 7768, "seconds": 0.601575, "mib_per_second": 1248.889,
 "messages_per_second": 12912.8, "profile": "1280x720@30 CDI",
 "required_mib_per_second": 187.65, "speedup_vs_realtime": 6.65}
```

This is the measurement `PSB_STATUS.md`'s `does_not_prove` #9 asks for
("nothing measures whether an Orin sustains 132 MiB/s, what `fsync` every second
costs at that rate") — **answered for the dev host, still open for the Jetson**.
Scaling it to an Orin NX is an estimate and is deliberately not made.

### C6 — the framing overhead, measured against PS-B's own writer

```
$ .parcel/bin/python -c "<per-channel framing at the end-of-session sequence>"
  go2.wirelesscontroller   payload        32 B  framing 318 B  ratio     9.94x
  d455.accel               payload        32 B  framing 319 B  ratio     9.97x
  d455.gyro                payload        32 B  framing 319 B  ratio     9.97x
  d455.depth               payload   814,080 B  framing 321 B  ratio     0.00x
  d455.color               payload 1,221,120 B  framing 321 B  ratio     0.00x
framing total: 0.581 MiB/s = 2.04 GiB/h at 1942 msg/s
```

`framing_bytes()` writes a real `Message` record with PS-B's
`MinimalMcapWriter` into an in-memory handle and takes the byte count it
returns; nothing re-implements the wire format. The suite pins it against the
independent identity `35 + len(canonical_json(envelope))`
(`test_framing_is_measured_against_ps_bs_own_writer_not_estimated`), and mutant
**M3** (return a remembered `352`) is caught.

This **refines** `PSB_STATUS.md` C10's labelled estimate (≈1.2 GiB/h over ~991
msg/s of DDS+L2 channels): the same per-message cost over the whole 1,942 msg/s
matrix is 2.04 GiB/h. It is 0.7% of the recommended profile.

### C7 — the rehearsal, green end to end, no hardware and no ROS

```
$ .parcel/bin/python -m scripts.parcel_capture.rehearse --selftest --workdir <scratch>
REHEARSAL REHEARSAL-SYNTHETIC-clean
  profile      848x480@30 CDI  84.60 MiB/s  297.4 GiB/h  required 2 GiB
  preflight    22 channel(s), verdict go_record
  clock map    3 device(s), certifiable=True
  sidecar      source=sim hardware_claims=False termination=clean
  take         offered 38840, recorded 38840, dropped 0
  ...
  RESULT: GREEN — every seeded fault named, no unseeded fault claimed.
$ echo $?
0
```

`verdict go_record` is the whole PS-D chain reaching its positive verdict, which
it **cannot** do without PS-E's storage budget (`PSD_STATUS.md` design call
D-3). That coupling is now exercised rather than described.

### C8 — four faults in one bag, each named, none confused

The headline gate. One 20-second take with a sensor that **stopped**, a sensor
that **slowed**, a recorder that **dropped**, and a clock that **stepped**:

```
    [DETECTED ] seeded sensor_silence       via bag
        go2.utlidar.cloud: 50.0% short of its expected count, longest silence 10.098 s
        against 0.500 s (5 nominal periods) — it STOPPED
    [DETECTED ] seeded rate_degradation     via bag
        go2.sportmodestate: 10.0% short of its expected count, longest silence 0.040 s
        against 0.100 s (5 nominal periods) — it SLOWED, evenly
    [DETECTED ] seeded backpressure_loss    via bag
        go2.lowstate: 500 interior sequence hole(s) — minted at receipt, never written;
        the framing is intact, so this is loss, not truncation
    [DETECTED ] seeded clock_step           via clock_map
        go2: step of +499.999 ms at host_monotonic 459501000000
    [absent   ]        write_exhaustion     via bag
    [absent   ]        process_kill         via bag
  RESULT: GREEN — every seeded fault named, no unseeded fault claimed.
```

Per-channel evidence in the sidecar, asserted in
`test_a_backpressure_drop_is_a_hole_and_a_stopped_sensor_is_not`:

| channel | `missing_count` | `reason` | verdict |
|---|---|---|---|
| `go2.lowstate` (dropped) | **500** | `sequence_gap: …` | degraded |
| `go2.utlidar.cloud` (stopped) | **0** | `rate_below_expectation: …` | degraded |

Neither carries the other's language — asserted both ways.

### C9 — SIGKILL is a truncation, and costs no channel a hole

A real child process, a real `SIGKILL` from inside its record loop, exit status
`-9`:

```
  sidecar      source=sim hardware_claims=False termination=truncated
  note         process_kill: child pid exited -9 (SIGKILL)
    [DETECTED ] seeded process_kill         via bag
        the bag ends without its terminal structure (file ends without a complete
        terminal structure (data_end=False, footer=False, magic=False))
```

`test_sigkill_is_a_truncation_and_costs_no_channel_a_hole` asserts
`saw_terminal_magic is False`, `recorder_close_record is None`, more than 100
messages recovered, and — for **every** channel — `missing_count == 0`,
`duplicate_count == 0`, and no `sequence_gap` in its reason. A truncation
removes a *suffix* of one append-only byte stream, so every channel loses its
tail and none gets a hole; that is the structural reason these can never be
confused. `test_a_truncated_bag_does_not_manufacture_rate_faults` asserts the
other direction: **no** channel reads `degraded`, so one truncation does not
become twenty-one fabricated sensor faults.

### C10 — write exhaustion latches, the bytes survive, nothing is called a drop

```
  note         write_exhaustion: child pid exited 0 (closed after latching)
    [DETECTED ] seeded write_exhaustion     via out_of_band
        the recorder latched under 'write_failed': OSError(27) writing d455.accel:
        [Errno 27] File too large
```

Produced by `RLIMIT_FSIZE` in the child with `SIGXFSZ` ignored: a **genuine
kernel refusal to extend the file**, mid-write, on a real path. It yields
`EFBIG` where a full volume yields `ENOSPC`; PS-B latches the first
`WRITE_FAILED` and the second `DISK_FULL`, and **that errno→reason mapping is
PS-B's own gate** (`PSB_STATUS.md` M6) which this card does not restate. What
the rehearsal adds is the rest of the chain: the recorder stops, the bytes
already written survive and re-read, every channel's number line is spotless,
and the latch is recoverable. See finding **F-E2** for what is *not*
recoverable.

### C11 — scope: nothing outside OWNS moved

```
$ git status --porcelain -- src/parcel_robot/runtime.py src/parcel_robot/pose.py \
    src/parcel_robot/navigation/ src/parcel_robot/route_memory/ src/parcel_robot/bags/ \
    evals/ src/parcel_robot/core/collision.py scripts/ci_gate.py configs/
(empty)
```

`bags/schema.py`, `capture/`, `record.py`, `sidecar.py`, `clockmap.py`,
`preflight.py` and `attest.py` are **imported and called, never edited**. The
`pyproject.toml` diff in the tree (`extend-exclude` for `.tmp_ci`) is
pre-existing and not mine — `PSB_STATUS.md` C9 already reports it.

### C12 — the motion guarantee, and nothing installed

```
$ .parcel/bin/python -c "<find_spec over the vendor set>"
rclpy: absent
cyclonedds: absent
unitree_sdk2py: absent
pyrealsense2: absent
cv2: absent
mcap: absent
zstandard: absent
```

`test_a_full_rehearsal_never_imports_a_vendor_module` runs a **whole rehearsal**
in a subprocess and then inspects `sys.modules`: `[]`. This is stronger than a
static scan — it is a measurement over the composed stack, which is the only
place a transitive vendor import could hide.

### C13 — it runs on a bare interpreter, as a plain script, from outside the repo

```
$ cd / && env -u PYTHONPATH /usr/bin/python3 \
      /home/.../scripts/parcel_capture/rehearse.py --workdir <scratch> --duration 10
REHEARSAL REHEARSAL-SYNTHETIC-cli
  profile      848x480@30 CDI  84.60 MiB/s  297.4 GiB/h  required 1 GiB
  preflight    22 channel(s), verdict go_record
  clock map    3 device(s), certifiable=True
  sidecar      source=sim hardware_claims=False termination=clean
  RESULT: GREEN — every seeded fault named, no unseeded fault claimed.
$ echo $?
0
```

No editable install, no `PYTHONPATH`, working directory outside the repo — the
Orin's invocation, and the one `STAGE0_RUN_SHEET.md:123` (T6) names. Note this
carries `record.py` and `sidecar.py` with it: they work perfectly as **imports**
from a bootstrapped process. What does not work is invoking them directly — see
**F-E1**.

### C14 — lint

```
$ .parcel/bin/python -m ruff check --output-format=concise scripts/parcel_capture/budget.py scripts/parcel_capture/rehearse.py tests/test_capture_rehearsal.py
All checks passed!
```

Zero new `(file, rule)` fingerprints against `scripts/ci_ruff_baseline.json`.

---

## Seeded-failure table

Every mutation below was applied to the **real source on disk** by a harness,
the suite re-run with bytecode caching fully disabled (`-B`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `__pycache__` removed — PS-A's
harness finding, adopted), and the source restored; the harness verifies both
files are byte-identical afterwards.

| # | Gate | Seeded fault | Proof it was caught |
|---|---|---|---|
| M1 | A budget over-estimates or refuses | a channel's load model deleted, so it contributes zero bytes | `FAILED test_seeded_failure_a_channel_with_no_load_model_is_refused_never_zero` |
| M2 | Unmeasured is never a pass | `sustained_by(None)` returns `SUSTAINS` | `FAILED test_seeded_failure_no_write_measurement_is_never_a_pass` |
| M3 | Framing is measured, not remembered | `framing_bytes` returns the constant `352` | `FAILED test_framing_is_measured_against_ps_bs_own_writer_not_estimated` |
| M4 | A mode nobody confirmed is not a mode | the `D455_DECLARED_MODES` check disabled | `FAILED test_seeded_failure_an_undeclared_d455_mode_is_refused[1920x1080@30]` |
| M5 | Unknown free space is not a long session | the negative-`free_bytes` guard removed | `FAILED test_seeded_failure_unknown_free_space_is_not_a_long_session[-1]` |
| M6 | A page-cache reading is not a disk rate | the `MIN_MEASUREMENT_BYTES` floor removed | `FAILED test_a_measurement_that_did_not_reach_the_disk_is_refused` |
| M7 | The pixel arithmetic is right | depth counted at 1 B/px instead of 2 | `FAILED test_the_d455_figure_is_pixels_times_bytes_times_frames[1280-720-30-False]` |
| M8 | Stopped ≠ slowed | gaps measured between messages only, not against the session span | `FAILED test_four_faults_in_one_bag_are_each_named_on_the_right_channel` |
| M9 | **No unseeded fault may be claimed** | `check_expectations` stops checking the unseeded direction | `FAILED test_a_fault_the_plan_never_seeded_is_a_violation_not_a_pass` |
| M10 | A truncation is not a drop | `classify` reports `BACKPRESSURE_LOSS` when the bag is truncated | `FAILED test_sigkill_is_a_truncation_and_costs_no_channel_a_hole` |
| M11 | "We could not tell" ≠ "it did not happen" | `UNRESOLVED` collapsed to `ABSENT` when gap evidence is absent | `FAILED test_seeded_failure_without_gap_evidence_the_two_are_not_separable` |
| M12 | A backpressure drop leaves an interior hole | `recorder.drop()` replaced by a silent skip | `FAILED test_four_faults_in_one_bag_are_each_named_on_the_right_channel` |
| M13 | A rehearsal cannot wear a session label | the `REHEARSAL-SYNTHETIC` prefix check disabled | `FAILED test_a_session_label_without_the_rehearsal_prefix_is_refused` |
| M14 | The stall threshold is load-bearing | `STALL_GAP_PERIODS = 1e9`, so nothing is ever a stall | `FAILED test_four_faults_in_one_bag_are_each_named_on_the_right_channel` |

```
$ .parcel/bin/python <scratchpad>/mutate_pse.py
baseline: GREEN | 88 passed in 10.10s
M1 a channel with no load model contributes zero bytes: CAUGHT | FAILED …::test_seeded_failure_a_channel_with_no_load_model_is_refused_never_zero
M2 an unmeasured destination reads as sustaining: CAUGHT | FAILED …::test_seeded_failure_no_write_measurement_is_never_a_pass
M3 framing is a remembered constant, not measured against PS-B's writer: CAUGHT | FAILED …::test_framing_is_measured_against_ps_bs_own_writer_not_estimated
M4 an undeclared D455 mode is computed instead of refused: CAUGHT | FAILED …::test_seeded_failure_an_undeclared_d455_mode_is_refused[1920x1080@30]
M5 unknown free space becomes a long session: CAUGHT | FAILED …::test_seeded_failure_unknown_free_space_is_not_a_long_session[-1]
M6 a page-cache-sized write is reported as a disk rate: CAUGHT | FAILED …::test_a_measurement_that_did_not_reach_the_disk_is_refused
M7 depth is counted at one byte per pixel: CAUGHT | FAILED …::test_the_d455_figure_is_pixels_times_bytes_times_frames[1280-720-30-False]
M8 gaps are measured between messages only, not against the session: CAUGHT | FAILED …::test_four_faults_in_one_bag_are_each_named_on_the_right_channel
M9 expectations are checked in one direction only: CAUGHT | FAILED …::test_a_fault_the_plan_never_seeded_is_a_violation_not_a_pass
M10 a truncation is reported as per-channel loss: CAUGHT | FAILED …::test_sigkill_is_a_truncation_and_costs_no_channel_a_hole
M11 'we could not tell' becomes 'it did not happen': CAUGHT | FAILED …::test_seeded_failure_without_gap_evidence_the_two_are_not_separable
M12 a backpressure drop no longer burns a sequence number: CAUGHT | FAILED …::test_four_faults_in_one_bag_are_each_named_on_the_right_channel
M13 a rehearsal may wear a session label: CAUGHT | FAILED …::test_a_session_label_without_the_rehearsal_prefix_is_refused
M14 nothing is ever a stall: CAUGHT | FAILED …::test_four_faults_in_one_bag_are_each_named_on_the_right_channel
tree restored byte-identical: True
clean re-run: GREEN | 88 passed in 10.10s
survivors: []
```

### Two harness findings worth recording, because both were real gaps

**S7 — the rehearsal found a bug in its own classifier, and that is the point.**
The first `channel_gaps()` measured only *interior* gaps, between a channel's
own messages. A channel that dies half-way through a take has evenly-spaced
messages right up to the moment it stops, so it has **no interior gap at all** —
and the classifier called `go2.utlidar.cloud` *slow* when it had *stopped*, then
attributed the rate-degradation finding to two channels instead of one. The
rehearsal went RED, which is exactly what it exists to do. Fixed by bracketing
against the bag's own span, the way PS-D's `probe_channel` already does; pinned
by `test_channel_gaps_brackets_by_the_session_not_the_channel` and by mutant M8.

**M9 survived the first harness run.** `check_expectations` has two loops and
only the first was exercised: every green rehearsal proves seeded faults are
found, and nothing proved that an *unseeded* detection is a failure. Deleting
the second loop left all 84 cells green. That is the single most important
property on this card — "a drop is not reported as a truncation" *is* the
unseeded direction — and it was untested. Four cells added
(`test_a_fault_the_plan_never_seeded_is_a_violation_not_a_pass`,
`…wrong_channel…`, `…the_artifacts_miss…`, `…a_missing_classification…`); M9 now
fails. **Any card asserting a two-directional property should check that both
directions have a cell that can see them independently.**

---

## Composition findings — the integration card's actual output

None of these is fixed here; every one is outside my OWNS. All six were found
by making the pieces run together — none is visible from inside a single card.

### F-E1 — `record.py` and `sidecar.py` cannot be invoked as scripts (MAJOR)

`STAGE0_RUN_SHEET.md:121-122` names `record.py` at T4 and `sidecar.py` at T5.
On a bare checkout with no editable install — the Orin's state — the invocation
ends in a traceback, not the actionable refusal board rule 4 requires:

```
$ cd / && env -u PYTHONPATH /usr/bin/python3 .../scripts/parcel_capture/record.py --verify /nonexistent.mcap
  File ".../scripts/parcel_capture/record.py", line 93, in <module>
    from parcel_robot.capture import (
ModuleNotFoundError: No module named 'parcel_robot'
```

PS-C's `clockmap.py` (`:135`) and PS-D's `preflight.py` (`:88`) / `attest.py`
(`:67,96`) each bootstrap `src/` onto `sys.path` and run cleanly from the same
place; PS-B's two modules do not. `sidecar.py` additionally uses a relative
import (`from .record import …`), so it needs `-m` as well as the path.
**Impact:** T4/T5 on the run sheet fail on session morning unless the operator
knows to set `PYTHONPATH`. **Fix:** three lines, copied from `clockmap.py:135`.
Pinned by `test_record_py_and_sidecar_py_cannot_be_invoked_as_plain_scripts`,
which skips itself if the bootstrap lands, and which uses `clockmap.py` as a
negative control so it is a comparison and not an opinion.

My own two modules follow PS-D's pattern (absolute imports plus a `sys.path`
bootstrap), so driving the whole stack *through* `rehearse.py` works on a bare
interpreter today — C13. That is a workaround for the rehearsal, not for T4/T5.

### F-E2 — a genuinely full volume hides its own latch (MAJOR)

`CaptureRecorder.close()` writes the recorder's account **into** the bag before
the footer. On a volume that will not take another byte, that write fails too.
Measured: after a real `EFBIG` mid-write, the bag reads

```
termination.kind          = truncated
saw_terminal_magic        = False
recorder_close_record     = None
```

— **byte-identical evidence to a SIGKILL.** So write-exhaustion and a crash are
indistinguishable from the bag alone, and `RecorderSummary` (which does carry
`latch_reason`) is returned to the caller and never persisted by PS-B.

`test_the_finding_that_a_full_volume_hides_its_own_latch` proves both halves:
classified from the bag alone, the exhaustion run reads `process_kill DETECTED /
write_exhaustion ABSENT`; only the out-of-band summary separates them.

**Mitigation implemented inside my OWNS:** `record_take()` writes
`<bag>.recorder-summary.json` the instant the recorder closes, and
`classify(..., recorder_summary=…)` uses it, recording `source="out_of_band"` so
the provenance of the verdict is never silently upgraded.
**Honest limit:** with `RLIMIT_FSIZE` the small summary file still writes
(the limit is per file); on a genuinely full filesystem it would not. **What the
session needs:** either PS-B persists the latch outside the bag, or the operator
records the recorder's exit line in the run sheet. Neither exists today.

### F-E3 — the sidecar cannot separate a stopped channel from a slowed one (MAJOR)

Both deliver the same count over the same window, so both read
`degraded / rate_below_expectation` with the same deficit shape. A channel at
50% of nominal and a channel silent for half the take are **the same sidecar
entry**. The discriminator is the longest inter-message gap; the bag carries
every `host_monotonic_ns` needed to compute it and the sidecar computes none of
them. PS-D's `probe_channel` *does* have a stall detector (`max_gap_ns`,
`MAX_GAP_PERIODS = 5.0`) — but preflight runs for 12 seconds before the take and
says nothing about what happened during it.

**Consequence for the session:** a bag whose LiDAR died at minute three and a
bag whose LiDAR ran at half rate throughout produce the same manifest, and the
operator debugs the wrong thing.
**Mitigation inside my OWNS:** `rehearse.channel_gaps()` computes it from the
bag, `classify()` uses it, and refuses to choose between the two verdicts when
it is absent (`UNRESOLVED`, which `check_expectations` treats as a violation).
**Fix:** one `max_gap_ns` field per channel in `observe_channels` — PS-B's, ~10
lines. `STALL_GAP_PERIODS` here is pinned equal to PS-D's `MAX_GAP_PERIODS` so
the two cards cannot drift.

### F-E4 — a synthetic preflight mints `PHYSICAL` for 21 channels (MAJOR)

Measured: `attestation.physical_channels` is **21 of 22** on a rehearsal run
(only `mic.xvf3800` stays `UNKNOWN`, and only because it publishes nothing).

`ChannelAttestation.origin` (`attest.py:399-408`) derives
`EvidenceOrigin.PHYSICAL` from `messages_received >= 1` **and nothing else**.
PS-D has no notion of a synthetic reader, so an attestation built from this
card's fixtures declares PHYSICAL for twenty-one channels no sensor produced,
and is structurally indistinguishable from a session attestation.

This is the class of defect the tranche exists to prevent: PS-A solved it for
envelopes (`SYNTHETIC_ORIGINS` require a `fixture_label`, `PSA_STATUS.md` D-3),
PS-C solved it for clock maps (a synthetic map must name its fixture), and PS-D
did not solve it for attestations.

**Mitigations inside my OWNS, all of them weak:** the session label must start
with `REHEARSAL-SYNTHETIC` (refused otherwise, mutant M13), every synthetic
receipt carries `SYNTHETIC REHEARSAL FIXTURE - no sensor was involved` in its
`detail`, which PS-D copies into `evidence` and thence into the attestation
JSON, and rehearse.py writes no attestation outside its own workdir. **None of
those is a typed field**, and a prose marker is what W0-A retired.
`test_the_finding_that_a_synthetic_attestation_still_claims_physical` asserts
the current behaviour so the finding is visible; if PS-D gains a typed probe
origin, that test is the one that changes. **Fix:** carry the reader's declared
`EvidenceOrigin` on `SampleReceipt` and require `PHYSICAL` for a PHYSICAL
attestation — the same shape PS-A already uses.

### F-E5 — two seams that do not compose (NOTE, two parts)

**(a) PS-C's `sidecar_clock_block()` is dead code in the composed path.** It
exists to hand `bags/schema.py:make_manifest` a `clocks` block carrying
`clock_map_certifiable` and `clock_map_shortfalls`; PS-B's `build_sidecar`
composes its own `clocks` block and binds the map by digest only. Result:
**whether the bound clock map is certifiable reaches no field of the manifest.**
Both modules are internally right and their gates both pass — they were written
in parallel and coupled by digest (`PSB_STATUS.md` D-5). Carried here as a
session note in every rehearsal sidecar so the information is not lost, and
pinned by `test_the_budget_is_written_into_every_rehearsal_sidecar`.

**(b) PS-D discards the payload sizes it measures.** `SampleReceipt.payload_bytes`
is validated per receipt and thrown away; only `observed_rate_hz` survives on
`ChannelProbe`, and the first receipt's size survives only inside a prose
`evidence` string. So a budget cannot be re-derived from a preflight report on
session morning — which is the one moment the assumptions in
[BANDWIDTH_BUDGET.md](BANDWIDTH_BUDGET.md) §0 could be replaced by measurements.
`loads_from_preflight()` therefore takes the sizes as a required argument rather
than parsing a sentence for a number the budget depends on. **Fix:** a
`mean_payload_bytes` property on `ChannelProbe` — PS-D's, ~5 lines.

### F-E6 — minor, recorded for completeness

**A volume that is already full raises a raw `OSError` from the recorder's
constructor.** Measured against `/dev/full`, which is a genuine kernel `ENOSPC`
source:

```
$ CaptureRecorder("/dev/full", …)
refused: OSError [Errno 28] No space left on device
```

`check_space` passes (devtmpfs has room), then the channel-table `fsync` in
`__init__` fails and the raw `OSError` propagates. A caller catching
`RecorderRefusedError` — the documented refusal type — sees a traceback. Low
impact today because no production caller constructs a recorder yet, and PS-E's
CLI catches `OSError` with `ENOSPC`/`EDQUOT` and prints a refusal.

**A clock map cannot span a short take.** `clockmap.planned_elapsed_ns` refuses
a duration under two burst windows and will not certify a fit under
`MIN_SPAN_NS` (300 s). Correct and fail-closed, but it has a concrete
consequence the run sheet should carry: **the clock prober runs across the whole
session, not once per take**, and short takes inherit the session's map.
Pinned by `test_a_clock_map_spans_the_session_not_the_take`.

---

## OWNS deviations and design calls

**D-1 — no OWNS deviation.** Exactly four paths created:
`scripts/parcel_capture/budget.py`, `scripts/parcel_capture/rehearse.py`,
`tests/test_capture_rehearsal.py`, `scrum/20260813/task_1/BANDWIDTH_BUDGET.md`,
plus this status doc. Nothing else in the repo was touched (C11).

**D-2 — the rehearsal's clocks are virtual, and the throughput measurement is
separate.** `record_take` takes `host_monotonic_ns` from the timetable, not from
`time.monotonic_ns()`, so a 20-second take is reproducible in milliseconds and
every derived rate is exact. That means the rehearsal proves *logic*, not
real-time behaviour, and it is why `measure_stack_throughput` exists as a second,
wall-clock measurement (C5). Both facts are written into every rehearsal
sidecar's `does_not_prove`.

**D-3 — payloads are scaled, message counts are not.** `payload_scale` (default
1/4096) shrinks the bytes so a 297 GiB/hour profile can be rehearsed in a test
suite. It changes **only** how many bytes move — not how many messages, which
sequence numbers they carry, or how anything is classified — and
`test_payload_scale_changes_bytes_and_nothing_else` asserts exactly that. The
scale is written into the sidecar's session notes. The throughput measurement
uses `payload_scale=1.0`.

**D-4 — `WRITE_EXHAUSTION` is seeded with `EFBIG`, not `ENOSPC`.** No
unprivileged process on this host can produce a genuinely full filesystem (no
mount, no quota, and `/tmp` is a 124 GiB tmpfs). `RLIMIT_FSIZE` with `SIGXFSZ`
ignored is a *real kernel refusal to extend the file* at a real `write()`,
which is the closest true thing available; PS-B latches it `WRITE_FAILED` rather
than `DISK_FULL`, and the errno→reason mapping is PS-B's own gate (its M6). The
sidecar-level lane is identical, which is what this card is about. **What
remains unrehearsed is a filesystem with zero free blocks**, and `/dev/full`
(F-E6) is the only genuine `ENOSPC` this host offers.

**D-5 — `classify()` never sees the plan.** Asserted by signature
(`test_a_classification_never_sees_the_plan`). A classifier that knew what was
seeded could not fail to find it, and the whole card would prove nothing.

**D-6 — the recommendation is a recommendation, not a decision.** The budget doc
recommends 848×480@30 C+D+IR with a stated fallback ladder. The owner or the
Stage-0 operator makes the call, and `STAGE0_RUN_SHEET.md:381-387` has the
blanks for what was actually selected.

---

## does_not_prove

1. **Nothing here has seen a sensor.** Every byte in every bag came from
   `random.Random(20260813)`. The rates, sizes and message types are PS-A's
   transcribed expectations and this card's assumptions, not observations. What
   is proven is that the *stack* behaves correctly when driven, not that any
   Unitree topic carries what we believe it carries.
2. **The dev-host write rate says nothing about the Orin.** 3,778 MiB/s on a
   Crucial T700 over ext4 is a floor for rehearsal work on this machine. The
   Orin was not reachable from here, and a Jetson's storage stack under thermal
   load is a different device. **Re-measure on the unit** — the command is in
   the budget doc §5 and the blank is at `STAGE0_RUN_SHEET.md:237`.
3. **Scaling the stack throughput to the Orin is an estimate and is not made.**
   901 MiB/s at 848×480@30 was measured single-threaded on a machine with far
   more single-core throughput than an Orin NX. Whether the Jetson clears
   84.6 MiB/s through the same path is **unmeasured**, and it is the first thing
   `rehearse.measure_stack_throughput` should be run for on the unit.
4. **No power or thermal claim is made at all.** How long the rig runs off the
   Go2 battery, and whether the Orin or the D455 throttles under a sustained
   write, are unknown and deferred to Wave 4 (`PLAN:1271`). The disk bound in
   the budget doc is a **ceiling**; the real bound may be well below it.
5. **The clocks in every rehearsal bag are virtual.** Derived from the
   timetable, so nothing here measures jitter, scheduling latency, callback
   cost, or what happens when the recorder competes with a SLAM process for the
   CPU. The rehearsal is a logic proof.
6. **Eight of the twenty-one load rows are assumptions** — both LiDAR clouds,
   the vendor voxel map, the front camera, the handheld, GNSS, UWB and
   `tegrastats`. They total 1.93 MiB/s of 84.60 — 2.3% — so a factor-of-three
   error in all of them moves the headline by 5%. They are individually wrong in unknown ways
   and each is labelled `assumed_worst_case` in the table.
7. **The DDS message sizes are transcribed field lists, not an IDL.** No vendor
   SDK is installed and none may be. `go2.lowstate` at 1,056 B is the largest of
   them and the one most worth falsifying at preflight.
8. **The D455 mode list is vendor-declared and unconfirmed.** Nobody in this
   repo has enumerated a real device's profiles. `D455_DECLARED_MODES` refuses
   anything outside it, which fails closed but does not make the list right; PS-D
   reads the device's profiles at preflight.
9. **`848×480 is the D455's native depth resolution` is a documented property,
   not something measured here.** It is the strongest argument in the
   recommendation and it rests on vendor documentation.
10. **The rehearsal covers six fault classes and there are more.** Not covered:
    a partially-corrupted message mid-bag (PS-B's own gate), a duplicated
    sequence, a channel that publishes *faster* than declared, a reader that
    hangs inside a C call past its deadline (`PSD_STATUS.md` #2 — the most
    likely way session-morning preflight hangs instead of refusing), two devices
    stepping their clocks at once, and thermal throttling of any kind. The
    estimate that the six chosen classes are the ones that matter on day one is
    **an estimate**.
11. **`check_expectations` proves classification, not detection sensitivity.**
    It shows that a 50% silence and a 10% rate deficit are named. Where the
    classifier turns over — the smallest deficit it sees, the shortest silence
    it calls a stall — is **not characterised**, and `STALL_GAP_PERIODS = 5.0` is
    PS-D's engineering choice inherited, not a derivation.
12. **The rehearsal's preflight is healthy by construction.** Faults are injected
    during the take, not during the T-30 probe, so this card does not rehearse a
    preflight that *finds* something. PS-D's own suite covers that.
13. **`verify_sidecar` is checked, `mcap` cross-validation is not.** PS-B's
    `cross_validate_with_mcap_library` reports `unavailable` on this box and this
    card does not change that: every bag here is readable by `parcel-capture` and
    by nothing else that has ever been tried.
14. **This proves nothing about mount geometry, the firmware pin against a real
    unit, the DDS segment, or the network path.** PS-D and PS-F own those, and
    the rehearsal's robot is a dict literal.

---

## CI_GATE

Run after the final edit to every file this card owns.

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T10:38:04Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.69s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.41s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.30s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.36s
[  PASS] HARD  default-suite              4580 passed, 9 skipped, 36 deselected, 5 warnings in 197.70s (0:03:17)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 210.1s
```

`ruff  7 violation(s), baseline 7, new 0` — this card added **zero** new
`(file, rule)` fingerprints to the ratchet. `frozen-digest-sentinels`
byte-identical and `hard-safety` green confirm no MUST-NOT-TOUCH surface moved.
The `default-suite` figure (4,580) is the whole tree with all six PS-1 cards in
it, so it is evidence that PS-E is green *in* that tree and not evidence about
anyone else's card; the closing gate for the tranche is Fable's.

---

## Card-required closing command

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_rehearsal.py -q
........................................................................ [ 81%]
................                                                         [100%]
88 passed in 9.74s
```
