# Bandwidth budget — the arithmetic nobody had done

> ## ⚠ GENERATED FILE — do not hand-edit
>
> Every number below is rendered by
> `scripts/parcel_capture/budget.py::render_document()`. Hand-editing this file is
> a defect, not a fix: the next regeneration silently reverts the edit, and
> `tests/test_bandwidth_budget_doc.py` reddens until it is reverted.
>
> ```
> .parcel/bin/python -m scripts.parcel_capture.budget --emit-doc    # regenerate
> .parcel/bin/python -m scripts.parcel_capture.budget --check-doc   # is it stale?
> ```

**Model:** card PS-E · **Generation + this revision:** card PS-P, tranche PS-3
**Producer:** `scripts/parcel_capture/budget.py` · **Rehearsal:** `scripts/parcel_capture/rehearse.py`
**Freshness gate:** `tests/test_bandwidth_budget_doc.py` · **Status:** [PSE_STATUS.md](PSE_STATUS.md) · [PSP_STATUS.md](PSP_STATUS.md)

### Why this file is generated

Because the hand-maintained version **went stale by 8.6% within one day**, while
remaining the number of record on every sheet the operator carries.

The PS-H channel corrections re-modelled the Go2 front camera — it is
**JPEG per frame** on `rt/frontvideostream`, ~204 KiB worst case, not a 4 Mb/s
H.264 stream at ~16 KB/frame, an under-model of roughly **13x** — and added five
channels. The code moved; the document did not. It went on publishing
**84.60 MiB/s · 297.4 GiB/h · 342.1 GiB · 114.1 GiB** while `budget.py` computed
**91.870 · 322.98 · 371.5 · 123.9**.

The delta decomposes exactly, which is the tell that this was staleness and not
disagreement: the front camera moved from 0.486 to 6.585 MiB/s
(**+6.099**), and PS-H's five added channels
(`utlidar/cloud_deskewed`, `utlidar/robot_odom`, `uwbstate`,
`utlidar/lidar_state`, `utlidar/switch`) contribute the remaining **+1.167**.

Arithmetic a human has to remember to re-run is arithmetic that goes stale. This
file is now a build artefact behind a sentinel, following the repo's frozen-digest
pattern (`scripts/ci_gate.py:DIGEST_SENTINELS`) — with the difference that the
sentinel does not pin the bytes, it pins them **to what the code computes**.

---

## 0. What this document does not know

Stated first, because a budget that hides its assumptions is worse than no
budget. This table is rendered from `budget.UNKNOWNS`, so the module and the
document cannot disagree about what is unmeasured.

| Unknown | What the module says, verbatim |
|---|---|
| **POWER AND THERMAL** | how long an Orin NX + D455 payload runs off the Go2 battery, and whether either throttles under a sustained write, is UNKNOWN. PLAN:1271 defers onboard compute/power/thermal/payload characterisation to Wave 4. It may well be the binding constraint on session length rather than disk, and guessing it would be dishonest. orin.tegrastats (matrix row 16) and go2.lowstate's BMS block are the two channels that settle it, and both are recorded from minute one. |
| **ORIN FREE SPACE** | unknown until PS-D's preflight reports it. Every session-length bound here is a function of free bytes, not a number. |
| **ORIN SUSTAINED WRITE** | unmeasured. The figure in this document was measured on the development host and is labelled dev-host, to be re-measured on the Orin. A desktop Gen5 NVMe is not a Jetson storage stack under thermal load. |
| **USB3 CONTENTION** | the D455 shares the Orin's USB controller with whatever else is plugged in (the L2 may be on /dev/ttyACM0). Whether the bus delivers the profile's frame rate is unmeasured. |
| **LIDAR POINT RATE** | assumed, not read. The built-in unit's model is repo-contradicted (L1 vs L2) and this budget takes the worse reading. PS-D reads the model and the payload size off the unit; loads_from_preflight() then replaces the assumption. |
| **FRONT CAMERA BITRATE** | assumed at 4 Mb/s. Nobody in this repo has connected to /frontvideostream, and PS-A marks its rate UNKNOWN. |
| **MESSAGE FIELD LISTS** | the DDS payload sizes are summed from transcribed field lists, not from an installed unitree_go IDL — no vendor SDK is present, and none may be installed into .parcel/. A wrong field list moves a row, never the headline. |
| **COMPRESSION** | none is assumed anywhere. Every figure is raw. If a decision is later taken to compress depth or IR, every row below changes and this document is wrong until it is re-derived. |

---

## 1. The D455 decision table

The only real tuning knob. Colour is RGB8 (3 B/px), depth is Z16 (2 B/px), each
infrared is Y8 (1 B/px) — the format names *are* the arithmetic.

**The `rig` columns are the whole rig**: the D455 profile, plus every other
budgeted channel, plus the per-message framing PS-B writes. `MiB/s` is binary
(1024²); `MB/s` is decimal (10⁶), because decimal is the unit the rosbag2 ceiling
is quoted in and confusing the two is a 5% error on a number whose margin is 14%.
**USB Mb/s counts the image streams only** — the two motion streams are 32 B a
message and would imply a precision this figure does not have.

| D455 profile | rig MiB/s | rig GiB/hour | rig MB/s | D455 USB Mb/s | vs rosbag2 ceiling | vs USB ceiling | reserve 1 h (GiB) | h @ 256 GiB | @ 1 TiB | @ 2 TiB |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| 1280x720@30 CD | 142.17 | 499.8 | 149.1 | 1106 | OVER both readings (x0.74) | under | 574.8 | 0.45 | 1.78 | 3.56 |
| 1280x720@30 CDI | 194.92 | 685.3 | 204.4 | 1548 | OVER both readings (x0.54) | **OVER** | 788.1 | 0.32 | 1.30 | 2.60 |
| 1280x720@15 CDI | 102.62 | 360.8 | 107.6 | 774 | THIN (x1.02) | under | 414.9 | 0.62 | 2.47 | 4.94 |
| 848x480@60 CDI | 173.43 | 609.7 | 181.8 | 1368 | OVER both readings (x0.60) | **OVER** | 701.2 | 0.37 | 1.46 | 2.92 |
| 848x480@30 CD | 68.56 | 241.0 | 71.9 | 488 | FITS (x1.53) | under | 277.2 | 0.92 | 3.69 | 7.39 |
| **848x480@30 CDI** | **91.87** | **323.0** | 96.3 | 684 | **THIN (x1.14)** | under | 371.5 | 0.69 | 2.76 | 5.51 |
| 848x480@15 CDI | 51.09 | 179.6 | 53.6 | 342 | FITS (x2.05) | under | 206.6 | 1.24 | 4.96 | 9.91 |
| 848x480@30 DI | 56.92 | 200.1 | 59.7 | 391 | FITS (x1.84) | under | 230.2 | 1.11 | 4.45 | 8.90 |
| 640x480@30 CDI | 71.87 | 252.7 | 75.4 | 516 | FITS (x1.46) | under | 290.6 | 0.88 | 3.52 | 7.05 |
| 424x240@30 CDI | 30.73 | 108.0 | 32.2 | 171 | FITS (x3.41) | under | 124.3 | 2.06 | 8.24 | 16.48 |

The free-space columns are **illustrative** — the Orin's actual free space is
unknown (§0) — and each already has the recorder's 15% margin removed. The
session-length bound is `free / (1 + margin) / rate`; PS-B's `SpaceBudget` uses
the same margin, so a take that clears this table is a take the recorder will
agree to start.

### The plan's anchors, verified rather than copied

`PHYSICAL_SESSION_PLAN.md:69-72` and `CHANNEL_MATRIX.md` §D quote ≈132 MiB/s /
≈464 GiB/h at 1280×720/30 and ≈58 MiB/s / ≈205 GiB/h at 848×480. Derived here:

```
1280×720 colour RGB8 : 1280 × 720 × 3 = 2,764,800 B/frame
1280×720 depth  Z16  : 1280 × 720 × 2 = 1,843,200 B/frame
                       sum 4,608,000 B/frame × 30 = 138,240,000 B/s
                       = 131.84 MiB/s = 463.49 GiB/hour        ✓ (quoted ≈132 / ≈464)

 848×480 colour RGB8 :  848 × 480 × 3 = 1,221,120 B/frame
 848×480 depth  Z16  :  848 × 480 × 2 =   814,080 B/frame
                       sum 2,035,200 B/frame × 30 =  61,056,000 B/s
                       =  58.23 MiB/s = 204.71 GiB/hour        ✓ (quoted ≈58 / ≈205)
```

**Both anchors are correct, and both are colour+depth only** — they exclude the
IR pair, the D455 IMU, every non-camera channel, and the recording framing. The
gap between an anchor and a `rig` column above is exactly what the plan's quoted
figures leave out, and most of that gap is now the Go2 front camera.

---

## 2. Does the plan of record actually fit? — the two ceilings

The decision this document exists to drive, answered in the operator's language.

> **848x480@30 CDI — the plan of record — offers 91.87 MiB/s,**
> **which is 96.3 MB/s.**
>
> Against rosbag2's observed recorder ceiling of 110–120 MB/s that is
> **THIN** — a margin of **×1.14** on the low reading, i.e. about
> **14% of headroom**. That ceiling is a band of field
> reports from **stronger x86 machines**, not a measurement of this Jetson. An
> Orin NX is the weaker box, so the local ceiling is more likely to sit *below*
> that band than above it.
>
> Against Intel's ~1200 Mb/s USB3 budget the same profile
> draws **684 Mb/s** of image data — comfortably under. USB is not the
> binding ceiling at 848×480. It is the binding ceiling at 720p.

**So: yes on paper, conditionally, and it is not yet proven here.**
848x480@30 CDI is recordable if — and only if — the Orin's own
recorder sustains ~96 MB/s. Nobody has measured that. Two steps measure
it before the dog is ever involved, and both are tonight:

- `session/TONIGHT_CHECKLIST.md` **N3** — `fio` **tail** throughput on the real
  record destination. Read the tail, not the peak: a DRAM-less NVMe falls off
  after its SLC cache is exhausted, and the peak hides exactly that.
- `session/TONIGHT_CHECKLIST.md` **N4** — the exact `ros2 bag record -s mcap`
  command line at the real byte rate for ten minutes. This is the one that
  measures the ceiling in §2, because the ceiling is a property of *the recorder*
  and not of the disk.

**Until N4 comes back green, treat this profile as a hypothesis.**

Three rows in §1 are **not recordable** and must never be selected on the day:
`1280x720@30 CD`, `1280x720@30 CDI` and `848x480@60 CDI` are all over the recorder
ceiling, and two of those three are over the USB ceiling as well — two independent
ceilings, both below the ask. `1280x720@15 CDI` clears the recorder ceiling by
×1.02, which is not a margin, it is a coin toss.

### If it does not fit: what to drop, in order, and what each drop costs

Rung 1 is taken first and every other rung sits on top of it. Rungs 2, 3 and 4 are
**alternatives to each other**, not successive steps — that is why rung 4 saves
less than rung 3 — so pick the one whose cost the session can afford. The rates
are computed; the *order* and the alternatives are engineering judgement, argued
rung by rung so they can be disagreed with at 09:00 rather than re-derived.

| # | Drop | rig MiB/s | rig MB/s | saved vs plan of record | vs rosbag2 ceiling |
|---|---|---:|---:|---:|---|
| 1 | Front camera JPEG off (H.264 path only) | 85.29 | 89.4 | 6.58 | THIN (x1.23) |
| 2 | ...and the IR pair off (848x480@30 C+D) | 61.98 | 65.0 | 29.89 | FITS (x1.69) |
| 3 | ...or instead keep IR and halve the rate (848x480@15 C+D+IR) | 44.51 | 46.7 | 47.36 | FITS (x2.36) |
| 4 | ...colour off, IR kept (848x480@30 D+IR) | 50.34 | 52.8 | 41.53 | FITS (x2.08) |

1. **Front camera JPEG off (H.264 path only)** — Costs the dog's own forward view at ~33 Hz as JPEG. The H.264 substitute is RTP over multicast 230.1.1.1:1720, which is NOT a topic and which a multicast-unfriendly NIC or switch drops silently — so this rung may cost the channel outright rather than degrading it. It is first because the D455 already looks forward: this is the only rung that removes no unique sensing modality, only a redundant view at a different exposure and lens.
2. **...and the IR pair off (848x480@30 C+D)** — Costs the only streams that work in the dark and the only independent stereo baseline. CHANNEL_MATRIX.md §D calls the pair explicitly NOT free — it is a real +40% disk and +50% USB — which is also why it is the first real sensing loss on the ladder rather than the last.
3. **...or instead keep IR and halve the rate (848x480@15 C+D+IR)** — Costs frame rate, and frame rate is the one thing that cannot be recovered from a bag: resolution downsamples, 15 fps does not interpolate into 30. Take this rung instead of the one above only when the IR pair matters more than temporal resolution — for a hand-carried calibration take it does, for a walking take it does not.
4. **...colour off, IR kept (848x480@30 D+IR)** — Costs every colour pixel from the D455 — no texture for visual SLAM, no appearance data, no human-readable review footage. This is the dark-run rung: it is here because in darkness the colour stream is already worthless and the IR pair is not.

**The rung that is deliberately absent is dropping small channels.** Everything
that is neither the D455 nor the front camera totals **3.512 MiB/s**;
turning all of it off saves less than any single rung above and costs the only
ground-truth contact signal, the only device clock the dog emits, and the only
non-LiDAR proximity sensing on the robot. Storage is cheap relative to a second
physical session, and there is no second session.

---

## 3. Every channel, with its working shown

At 848x480@30 CDI, over a one-hour take. `frame B` is the per-message
recording overhead — measured against PS-B's own MCAP writer, not estimated — and
it grows by one byte per decimal digit of the session's final sequence number, so
it is evaluated at the *end* of the take.

| channel | msg/s | payload B | frame B | MiB/s | GiB/h | basis |
|---|---:|---:|---:|---:|---:|---|
| `d455.color` | 30.0 | 1,221,120 | 321 | 34.946 | 122.86 | derived_pixels |
| `d455.depth` | 30.0 | 814,080 | 321 | 23.300 | 81.91 | derived_pixels |
| `d455.infra1` | 30.0 | 407,040 | 323 | 11.655 | 40.97 | derived_pixels |
| `d455.infra2` | 30.0 | 407,040 | 323 | 11.655 | 40.97 | derived_pixels |
| `go2.front_camera` | 33.0 | 208,896 | 331 | 6.585 | 23.15 | assumed_worst_case |
| `l2.cloud` | 20.0 | 34,688 | 305 | 0.667 | 2.35 | assumed_worst_case |
| `go2.utlidar.cloud_deskewed` | 10.0 | 69,248 | 326 | 0.664 | 2.33 | assumed_worst_case |
| `go2.utlidar.cloud` | 10.0 | 69,248 | 317 | 0.663 | 2.33 | assumed_worst_case |
| `go2.lowstate` | 500.0 | 1,056 | 307 | 0.650 | 2.28 | derived_fields |
| `go2.front_camera_h264` | 30.0 | 16,666 | 336 | 0.486 | 1.71 | assumed_worst_case |
| `d455.gyro` | 400.0 | 32 | 319 | 0.134 | 0.47 | derived_fields |
| `go2.utlidar.imu` | 200.0 | 376 | 320 | 0.133 | 0.47 | derived_fields |
| `d455.accel` | 250.0 | 32 | 319 | 0.084 | 0.29 | derived_fields |
| `l2.imu` | 200.0 | 64 | 302 | 0.070 | 0.25 | derived_fields |
| `go2.utlidar.voxel_map` | 1.0 | 65,536 | 318 | 0.063 | 0.22 | assumed_worst_case |
| `go2.wirelesscontroller` | 100.0 | 32 | 318 | 0.033 | 0.12 | assumed_worst_case |
| `go2.sportmodestate` | 50.0 | 256 | 307 | 0.027 | 0.09 | derived_fields |
| `go2.lf.lowstate` | 10.0 | 1,056 | 308 | 0.013 | 0.05 | derived_fields |
| `go2.utlidar.robot_odom` | 10.0 | 736 | 310 | 0.010 | 0.04 | derived_fields |
| `gnss.zed_f9p` | 10.0 | 512 | 313 | 0.008 | 0.03 | assumed_worst_case |
| `uwb.owner_fob` | 20.0 | 64 | 312 | 0.007 | 0.03 | assumed_worst_case |
| `go2.uwbstate` | 20.0 | 64 | 311 | 0.007 | 0.03 | assumed_worst_case |
| `go2.lf.sportmodestate` | 10.0 | 256 | 309 | 0.005 | 0.02 | derived_fields |
| `go2.utlidar.robot_pose` | 10.0 | 96 | 310 | 0.004 | 0.01 | derived_fields |
| `orin.tegrastats` | 1.0 | 320 | 309 | 0.001 | 0.00 | assumed_worst_case |
| `go2.utlidar.lidar_state` | 1.0 | 256 | 317 | 0.001 | 0.00 | assumed_worst_case |
| `go2.utlidar.switch` | 1.0 | 32 | 312 | 0.000 | 0.00 | assumed_worst_case |
| **TOTAL** | **2,017** | | | **91.870** | **322.98** | |

Not recorded in this profile: `mic.xvf3800` — `AWAITING_HARDWARE`, in the post
(`BLOCKED.md:74-97` B3). Its slot exists and its model is carried (6 ch × 16 kHz ×
16 bit = 0.21 MiB/s, 0.75 GiB/h) so it drops in without re-deriving anything;
`--include-awaiting` adds it.

**`basis` is not decoration.** `derived_pixels` is exact arithmetic;
`derived_fields` is exact given a transcribed field list; `assumed_worst_case` is
an engineering assumption taken at its worse end.
**13 rows are assumptions and together they are 9.185 MiB/s
of 91.870**, i.e. 10.0% of the
budget. That fraction is the thing this revision changes most: the previous table
could say its assumptions were 2.3% of the total and therefore harmless. They are
not any more, because the largest of them is now the front camera. **If the front
camera's JPEG assumption is wrong by a factor of three in either direction the
headline moves by more than 10%** — and question 4 of `CHANNEL_MATRIX.md`'s open
list (does `Go2FrontVideoData_` populate one resolution or all three?) is exactly
that factor.

### Three findings from doing the arithmetic

**(a) Imaging is 96.2% of the budget, and the D455
alone is 89.0%.** `CHANNEL_MATRIX.md` §G's
*"<2 MiB/s for the non-camera channels"* is false as written — the real figure is
**3.512 MiB/s** — but the claim it was making survives intact:
everything that is not a camera is still a rounding error against the cameras.

**(b) The recording framing is 0.604 MiB/s ≈ 2.12 GiB/hour**, at
2,017 msg/s — 0.7% of the profile. It is
**not worth optimising**.

**(c) …but framing costs ~10× the payload on the smallest channels.**
`go2.wirelesscontroller` carries 32 B of sticks and buttons inside a ~318 B
envelope; `d455.accel` and `d455.gyro` are the same shape. That is the price of
every message being independently attributable — per-channel sequence, dual
clocks, frame, origin, calibration ref — and it is the right trade for this
session. If it ever has to come back, the lever is a compact binary envelope in
place of JSON, **not** recording fewer channels.

---

## 4. Session length

```
hours = free_bytes / (1 + margin) / bytes_per_second / 3600      margin = 0.15
```

At 848x480@30 CDI, `bytes_per_second = 96,332,521` (91.87 MiB/s):

| free space | session length |
|---|---|
| 256 GiB | 0.69 h (41 min) |
| 512 GiB | 1.38 h (83 min) |
| 1 TiB | 2.76 h (165 min) |
| 2 TiB | 5.51 h (331 min) |

**These are disk bounds only.** The binding constraint may be battery or thermal,
and that is unknown (§0). Treat the disk bound as a ceiling and expect the real
bound to be lower.

The number PS-D's go/no-go wants is `--required-free-gib`, which is the *reserve
for the planned take* rather than a session length:

```
123.9    # 20-minute take at 848x480@30 CDI
371.5    # one-hour take
```

PS-B's recorder **refuses to start** below it, and PS-D's `attest()` cannot reach
`GO_RECORD` without one (`PSD_STATUS.md` design call D-3). Both couplings are
exercised in the rehearsal.

---

## 5. Can the destination keep up? — measured

```
$ .parcel/bin/python -c "measure_sustained_write(
      '/home/jaewoo-jang/.cache/parcel-psp',
      total_bytes=32*1024**3, block_bytes=4*1024*1024, fsync_interval_s=1.0)"
  path: /home/jaewoo-jang/.cache/parcel-psp
  host: jaewoo-jang-parcel
  filesystem: ext4
  bytes_written: 34359738368
  seconds: 8.693122
  block_bytes: 4194304
  fsync_count: 9
  fsync_interval_s: 1.0
  bytes_per_second: 3952519977.058
  mib_per_second: 3769.417
  gib_per_hour: 13251.856
  note: dev-host, to be re-measured on the Orin
```

> ### 3,769 MiB/s — **dev-host, to be re-measured on the Orin**
>
> Crucial T700 4 TB (`CT4000T700SSD3`), ext4, `/dev/nvme0n1p5`.
> 32 GiB written sequentially with an fsync
> every second and a final fsync inside the timed window. **This is not a
> statement about the Orin.** It is a floor for rehearsal work on this host and
> nothing more. `session/TONIGHT_CHECKLIST.md` **N3** is where the Orin's own
> figure comes from.

Against the plan of record that is **×41.0 headroom on the dev
host**. The measurement is not `dd`: it fsyncs, so it is not measuring this host's
246 GiB of page cache, and it grows itself until the timed window clears one
second, because 256 MiB finishes in a tenth of a second on this drive and a tenth
of a second is a cache reading.

### And through the whole capture stack, which is the number that matters

Raw disk speed is not what a recorder achieves: every message is JSON-encoded into
an envelope, length-prefixed, wrapped in an MCAP record, written through a
buffered handle and fsynced once a second. Measured end to end through PS-B's real
`CaptureRecorder`, at full payload size:

| profile | achieved | required | vs real time | msg/s |
|---|---:|---:|---:|---:|
| 848x480@30 CDI | 1,213 MiB/s | 91.9 MiB/s | **×13.2** | 26,586 |
| 1280x720@30 CDI | 1,373 MiB/s | 194.9 MiB/s | **×7.0** | 14,197 |

**Dev-host, to be re-measured on the Orin**, and single-threaded on a machine with
far more single-core throughput than an Orin NX. This answers `PSB_STATUS.md`'s
`does_not_prove` #9 for the dev host and leaves it open for the Jetson; the scaling
to the Orin is **an estimate and is not made here**. Re-run
`rehearse.measure_stack_throughput` on the unit.

**And note what this is a measurement OF.** It is the `parcel-capture` recorder,
not `ros2 bag record`, and PS-G makes rosbag2 the recorder of record. The ceiling
that actually binds the session is the one in §2, and it has never been measured
on any of our hardware at all.

---

## 6. How to re-derive any of this

```
# the decision table
.parcel/bin/python -m scripts.parcel_capture.budget

# one profile, per-channel, with the unknowns printed
.parcel/bin/python -m scripts.parcel_capture.budget --profile 848x480@30 --duration 3600

# with a real sustained-write measurement on the destination volume
.parcel/bin/python -m scripts.parcel_capture.budget --profile 848x480@30 \
    --measure-write /path/on/the/orin \
    --free-bytes $(df --output=avail -B1 /path | tail -1)

# the rehearsal that drives the whole stack at that profile
.parcel/bin/python -m scripts.parcel_capture.rehearse --selftest --workdir /tmp/rehearsal

# regenerate THIS DOCUMENT, and check whether it has gone stale
.parcel/bin/python -m scripts.parcel_capture.budget --emit-doc
.parcel/bin/python -m scripts.parcel_capture.budget --check-doc
```

On the Orin, with no editable install and no `PYTHONPATH`, the same files run as
plain scripts:

```
python3 scripts/parcel_capture/budget.py --profile 848x480@30 --measure-write /data
python3 scripts/parcel_capture/rehearse.py --selftest --workdir /data/rehearsal
```

---

## What this document does not prove

- It does not prove that any of these channels exists on **our** unit, publishes at
  its declared rate, or carries the payload size assumed for it. §0 names every
  assumption; the session's first 45 minutes is where they become readings.
- It does not prove the Orin can record any row in §1. Every sustained-write and
  stack-throughput number in §5 is **dev-host**, on a desktop Gen5 NVMe and a far
  faster core, and this document explicitly declines to extrapolate them.
- **It does not prove the rosbag2 ceiling in §2 applies here.** That band is field
  reports from other people's x86 machines. It is used to classify a profile, never
  to authorise one, and `session/TONIGHT_CHECKLIST.md` N4 is the only thing on the
  board that can settle it.
- It does not prove the drop ladder's *order* is right for the session's purpose.
  The rates are computed; the ordering is judgement, argued rung by rung.
- It states **no power or thermal bound**, which may well be the binding constraint
  on session length rather than disk (§0).
- **Being generated does not make it true.** The freshness gate proves the document
  equals the model. It says nothing whatever about whether the model is right.

