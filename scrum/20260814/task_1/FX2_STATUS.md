# FX-2 — the harness/sidecar fail-open family

**Card:** FX-2 (fix tranche FX, against AU-F's upheld findings) · **Date:**
2026-08-14 · **Owner of record:** Opus
**OWNS, and all that was written:** `scripts/parcel_capture/orin_rehearsal.py`,
the two named legs of `scripts/parcel_capture/sidecar.py`,
`tests/test_orin_rehearsal.py`, regressions in `tests/test_rosbag2_sidecar.py`,
the regenerated [ORIN_RUNBOOK.md](ORIN_RUNBOOK.md), dated addenda at the foot of
[OR1_STATUS.md](OR1_STATUS.md) and [S1_STATUS.md](S1_STATUS.md), and this file.
**No section of OR1_STATUS or S1_STATUS was rewritten.** Nothing else in the
tree was touched; `preflight.py`, `rosbag2.py`, `record.py`, `channels.py`,
`budget.py` and every S-2 surface were read only.

---

## 0 · Headline

Seven upheld findings, all seven reproduced first and pasted below before a line
was changed, all seven fixed, each with a regression test **proven to redden
against the old behaviour** by reverting the fix and re-running (nine mutations,
nine reddened, all three files restored byte-identically by sha256).

Two of them were the ones that mattered for tomorrow's bench: **P4 could report
a camera that delivered nothing as "worst stream 100.0%" PASS**, and **P5 could
report a support-topic gate that crashed as a green phase**. Both are now named
failures with remedies.

| | |
|---|---|
| Findings reproduced / fixed / regression-tested | **7 / 7 / 7** |
| Mutation sweep (revert the fix, re-run the test) | **9 reverts, 9 REDDENED**, 3 files restored byte-identical |
| `tests/test_orin_rehearsal.py` | **108 passed** (82 before) |
| `tests/test_rosbag2_sidecar.py` | **94 passed** (79 before) |
| `tests/test_no_arm_pin.py` | **76 passed** — unchanged, still green |
| ruff over all four files | `All checks passed!` |
| Python 3.10 grammar | both modules parse (`ast feature_version=(3,10)`) |
| Real ROS 2 re-run (Jazzy sandbox, fixed code) | **P5 PASS** on real bytes, 309 messages, `termination=clean` |
| Desktop run, fixed code | honest bundle, **EXIT=1**, zero tracebacks |

---

## 1 · Per-finding table

| # | Sev | Reproduced (output pasted) | Fixed | Regression | Reddens on old code |
|---|---|---|---|---|---|
| **F1** | MAJOR | §2 — real `_D455_FRAMES_SCRIPT` executed: three dead streams simply absent from its answer; P4 `PASS … worst stream 100.0%` with **all six** streams dead | child script emits the CONFIGURED set with zeros; P4 fails on zero-delivery, on total loss, and on a profile that never configured a plan stream | 6 tests, incl. two driven by **executing the real child script** | YES ×2 mutations (child loop; P4 scoring) |
| **F2** | MAJOR | §3 — raising `reconcile_support_topics` → `P5 verdict = PASS`; failing lazy import → `P5 verdict = PASS` | exception ⇒ step **FAIL**, exception line as detail, remedy names S-1's file; refusal-typed results keep their existing classification | 3 tests (raise, ImportError, positive control) driving the whole of P5 in-process | YES |
| **F3** | MINOR (was MAJOR) | §4 — `images=2, camera_infos=1` (50% deficit) → `GO-RECORD certified=True`; `3/2` (33%) likewise | allowance is proportional, no 1.0 floor; sub-10-image bags carry a finding | boundary sweep images 1..6 (11 cases) + the 40/39 control | YES (5 of 11 sweep cases) |
| **F4** | MINOR | §5 — perturbing the **last** CameraInfo byte: `verify ok=True`, digest unmoved | docstrings corrected to the true property **and** a mid-stream-drift finding added; digest now binds every distinct decoded calibration in the window | 3 tests (late-byte, drift finding, drift-vs-steady digest) | YES ×3 |
| **F5a** | MINOR | §6 — `bench_source_argv("/parcel_rehearsal/steer", "geometry_msgs/msg/Twist")` **ACCEPTED**; `unitree_api/msg/Request` ACCEPTED | message-type guard: deny-list of command markers + `sensor_msgs/msg/` allow-list, wired into P5's pre-check too | 8 tests (6 types + allow-list + P5 seeded) | YES (7 failed) |
| **F5b** | MINOR | §6 — every absent module read `detail='Traceback (most recent call last):'` | detail takes the **last** stderr line | 1 test, plus the live desktop bundle | YES |
| **F5c** | MINOR | §6 — permission-denied, I/O-error and missing-directory listings all classified `NONE` | failed listing ⇒ `UNKNOWN`; only exit-0-and-empty is `NONE`; P0 quotes the `ls` line | 5 cases + a P0 test | YES (5 failed) |
| **F5d** | MINOR | §7 — `--firmware-attested V1.1.13 --until p3_network` gives `p3_network SKIPPED`, not PASS | runbook `--until` row regenerated to say `--until` does not make the phase run | runbook row test + byte-identity pin | YES |
| **F5e** | MINOR | §8 — the documented bwrap recipe: `Failed opening file …/.ros/log/… Read-only file system` → `P5 FAIL` | writable-`$HOME` requirement documented in the generated runbook; OR-1 addendum carries the recipe correction | runbook test | YES |
| **F5f** | MINOR | §9 — `orin_rehearsal.cpython-314.pyc` present, 146,137 B, mtime `18:04:09`, before FX-2 ran anything | claim corrected by dated addendum; the two mutated modules' `.pyc` purged | n/a (a claim, not code) | n/a |

---

## 2 · F1 — P4 scored only the streams that delivered

**Reproduction.** The real `_D455_FRAMES_SCRIPT` was executed against a stub
`pyrealsense2` that configures all six streams and delivers only some, and its
real JSON was fed to the real `run_p4_sensors`:

```text
--- infra2 + IMU deliver NOTHING
    child JSON streams: ['Color', 'Depth', 'Infrared 1']
    P4 verdict=PASS  summary=D455 enumerated (1 device(s)); worst stream 100.0% over 60s at 848x480@30
    worst_stream_fraction=1.0
--- EVERY stream lost
    child JSON streams: []
    P4 verdict=PASS  summary=D455 enumerated (1 device(s)); worst stream 100.0% over 60s at 848x480@30
    worst_stream_fraction=1.0
```

The tally is keyed by frames that **arrived** (`counts.items()`), so a stream
that delivered nothing never entered the score, `worst` stayed at its initial
`1.0`, and a camera that delivered nothing at all read as a healthy camera.

**Fix, both halves.**

* The child script builds its `streams` map over `set(rates) | set(counts)` —
  `rates` comes from `profile.get_streams()`, i.e. what the pipeline actually
  configured — and emits `"configured": sorted(rates)`.
* `run_p4_sensors` scores that configured set: an empty configured list is a
  FAIL (*"a count with nothing to compare against is not a pass"*); zero total
  delivery is a **TOTAL LOSS** FAIL naming every configured stream; any
  individual zero-delivery stream is a FAIL naming it; and a profile that never
  configured one of `CONFIGURED_STREAMS` (colour, depth, both IR, accel, gyro —
  matched on the normalised name, because IR/IMU spellings vary between
  `pyrealsense2` builds) is a FAIL naming what is missing. Zero delivery is
  judged **before** the fraction ladder and independently of it, because a
  stream with no configured rate has no fraction at all and *"no expectation
  could be formed"* must never be why a dead stream reads as healthy.

```text
--- infra2 + IMU deliver NOTHING
    P4 verdict=FAIL  summary=configured stream(s) Accel, Gyro, Infrared 2 delivered ZERO frames
                     in 60s while others delivered; a configured stream that delivers nothing is
                     a lost stream, not an unscored one
--- EVERY stream lost
    P4 verdict=FAIL  summary=TOTAL LOSS: not one frame arrived on any of the 6 configured
                     stream(s) (Accel, Color, Depth, Gyro, Infrared 1, Infrared 2) in 60s.
                     The pipeline started and delivered nothing
--- all six deliver
    P4 verdict=PASS  summary=D455 enumerated (1 device(s)); 6 configured stream(s) all
                     delivering, worst stream 100.0% over 60s at 848x480@30
```

**Regressions** (`tests/test_orin_rehearsal.py`):
`test_the_real_frame_count_script_reports_every_configured_stream` (runs the
real script and pins its shape),
`test_p4_fails_naming_a_configured_stream_that_delivered_nothing`,
`test_p4_fails_naming_a_total_loss_when_no_stream_delivers_at_all`,
`test_p4_passes_only_when_every_configured_stream_including_the_imu_delivers`,
`test_p4_refuses_to_score_a_frame_count_that_names_no_configured_stream`,
`test_p4_fails_when_the_profile_never_configured_the_imu`.

---

## 3 · F2 — P5 step 8 swallowed exceptions into PASS

**Reproduction.** The whole of `run_p5_recorder` was driven end to end with a
shim `ros2` on `PATH` (answers `--help`, writes a rosbag2-shaped bag on SIGINT),
with S-1's reconcile replaced by one that raises:

```text
mode=raise
  P5 verdict = PASS
  summary    = help verified -> argv rendered for jazzy -> 2s recorded -> 40 message(s) read
               back clean -> sidecar refused the unmapped bench bag, as it must
  findings   = ["support reconciliation could not run: TypeError: reconcile_support_topics()
                takes a Mapping now, not str (this is S-1's surface and is reported, not
                edited, from this card)"]

mode=import          # the lazy import inside the same try
  P5 verdict = PASS
  findings   = ["support reconciliation could not run: ModuleNotFoundError: …"]
```

A finding, then PASS. On the Orin, with real `/camera/…` topics on the graph,
that is the branch where a crashed support-topic check reads green — and
OR1_STATUS §7 claimed the opposite.

**Fix.** The `except` is still blind (preflight is S-1's surface and in flight),
but blind is not green: it records the exception line, appends it to
`refusals`, and **fails the phase** with *"the support-topic gate did not
execute, so this phase certifies nothing about camera_info or the transform
topics"* plus a remedy naming `scripts/parcel_capture/preflight.py`. No
traceback reaches the operator. A reconciliation that **ran** and returned
refusals keeps its existing classification exactly: FAIL when real sensor topics
were recorded, REPORT on a synthetic bench.

```text
mode=raise    P5 verdict = FAIL   summary = support reconciliation could not run: TypeError:
              reconcile_support_topics() takes a Mapping now, not str — the support-topic gate
              did not execute, so this phase certifies nothing about camera_info or the
              transform topics
mode=none     P5 verdict = PASS   (positive control: the gate ran, refused the bench graph as
              it should, and the phase still passes)
```

**Regressions:** `test_p5_fails_when_the_support_reconciliation_raises`,
`test_p5_fails_when_the_support_reconciliation_cannot_even_be_imported`,
`test_p5_passes_when_the_support_reconciliation_actually_runs`. All three drive
the real `run_p5_recorder` in-process — a fake machine answers `--help` and
`ros2 topic list -t`, a fixture writer stands in for the recorder, and the bag
is then read, sidecar'd and reconciled by the real code. No ROS, no process.

---

## 4 · F3 — the short-bag rate leg failed open

**Reproduction**, with the suite's own fixture encoders, through
`finalize_rosbag2(require_go_record=True)`:

```text
  images=  2 camera_infos=  1 deficit= 50.0%  -> status=GO-RECORD certified=True
  images=  3 camera_infos=  2 deficit= 33.3%  -> status=GO-RECORD certified=True
  images=  4 camera_infos=  2 deficit= 50.0%  -> REFUSED
  images= 40 camera_infos= 39 deficit=  2.5%  -> status=GO-RECORD certified=True
```

`allowance = max(1.0, image_count * tol)`: below ten images the floor of one
whole message swallowed the entire deficit.

**Fix.** The allowance is proportional with no floor. The floor only ever
applied where it was wrong — at `image_count >= 10` the proportional allowance
already exceeds 1.0 — so nothing that passed on the strength of the tolerance
stopped passing. A bag below `CAMERA_INFO_RATE_MIN_MESSAGES` (= `round(1/0.10)`
= 10, derived from the tolerance, never a second hand-set number) additionally
carries a finding saying that this leg passing means the counts matched, not
that a real take was observed.

```text
  images=  2 camera_infos=  1 -> REFUSED (rate profile)
  images=  3 camera_infos=  2 -> REFUSED (rate profile)
  images= 40 camera_infos= 39 -> status=GO-RECORD certified=True   # control, unchanged
```

**Regression:** `test_no_count_is_small_enough_to_certify_a_camera_info_deficit`
(11 parametrised cases, images 1..6, asserting both directions and that the
certifying ones carry the small-N finding) and
`test_the_ordinary_off_by_one_at_a_real_take_length_still_certifies`.

---

## 5 · F4 — what the calibration digest covers, and the choice made

**Reproduction:**

```text
  recorded calibration_sha256 = fc65852675eb79e3de1c54dc8b1e5564ec5f9da958e0be32601b81f44278e8b9
  CameraInfo payloads present in the bag: 20
  after perturbing the LAST CameraInfo byte: verify ok=True failures=()
  digest moved? False
```

`assess_go_record` digested `_decode_first(...)` — payload `[0]` — and
`verify_calibration_digest` re-derived with `max_per_topic=1`, while two
docstrings claimed *"one perturbed byte in **any** CameraInfo payload"*.

**Which branch was taken, and why.** The finding offered the stronger fix *"if
cheap"*: hash all CameraInfo payloads per topic. **It is not cheap from inside
this card's OWNS.** `collect_topic_payloads` takes one `max_per_topic` for every
topic in the call, and the same call is what pulls image payloads — a
20-minute take's image messages are gibibytes, so the cap cannot simply be
raised. Covering every CameraInfo therefore needs either a second full parse of
a ~108 GiB bag (the pipeline already parses it for the scan, for payloads and
for `sha256_file`; a fourth pass is a real cost on the Orin, and the decode
alone measures **2.3 s per 144,000 payloads** on this desktop, aarch64 slower)
or a per-topic cap in `rosbag2.py`, **which FX-2 does not own**.

So: the documented branch — *correct both docstrings to the true property AND
add a mid-stream-drift finding* — plus as much of the stronger property as is
free. Concretely:

* `_collect_support_payloads` already **collected** 64 payloads per topic per
  split file and then threw all but one CameraInfo away. It now retains
  `_CALIBRATION_PAYLOADS = 64` of them: zero extra IO, zero extra collection.
* `calibration_digest_of` binds **every distinct decoded calibration per
  topic**, in first-seen order. Identical calibrations collapse to one entry
  (the normal case — a driver restating intrinsics per frame), so the digest
  stays a name for the calibration and grows only when the calibration moves.
* A topic with more than one distinct calibration in that window is a named
  **finding**: *"… published N DIFFERENT calibrations inside the first 64
  message(s) of each split file (changed field(s): d); every one of them is
  bound into the calibration digest, and a take whose intrinsics move
  mid-stream cannot be rectified with any single one of them"*.
* Both docstrings now state the true property and both **gaps**: raw bytes that
  decode identically are not covered here (they are covered by the per-file
  `sha256` the sidecar records and `verify_rosbag2_sidecar` recomputes), and a
  calibration that first changes past the window is not covered at all.

```text
  after perturbing the LAST CameraInfo byte: verify ok=False
    failures=("calibration digest mismatch: sidecar records 6f9b8a01…, the bag's decoded
               calibration set hashes to 26840b41…",)
  drift finding: /camera/camera/color/camera_info published 2 DIFFERENT calibrations inside the
    first 64 message(s) of each split file (changed field(s): d); …
```

**Regressions:** `test_a_perturbed_byte_in_a_LATER_camera_info_breaks_the_digest`,
`test_a_calibration_that_changes_mid_stream_is_a_named_finding`,
`test_the_drift_digest_differs_from_the_same_bag_without_the_drift` — the last
asserts the two bags open with a **byte-identical first CameraInfo**, which is
what makes the digest difference mean something.

---

## 6 · F5a/b/c — the harness minors

**F5a, reproduced:** the guard read topic NAMES only.

```text
  ACCEPTED: ros2 topic pub -r 10 /parcel_rehearsal/steer geometry_msgs/msg/Twist {}
  ACCEPTED: ros2 topic pub -r 10 /parcel_rehearsal/go unitree_api/msg/Request {}
  ACCEPTED: ros2 topic pub -r 10 /parcel_rehearsal/x geometry_msgs/msg/TwistStamped {}
  ACCEPTED: ros2 topic pub -r 10 /parcel_rehearsal/y unitree_go/msg/WirelessController {}
```

A `Twist` on a sensor-shaped name is a velocity command whatever the name says.
`refuse_unless_bench_message_type()` now checks the type independently — a
deny-list of command/request markers **and** a `sensor_msgs/msg/` allow-list,
because a deny-list can only name the surfaces somebody thought of — and P5's
pre-record check calls it alongside the topic guard, so the refusal lands before
`ros2 topic pub` or `ros2 bag record` is started. All four lines above are now
`RehearsalRefused`.

**F5b, reproduced:** `pyrealsense2: status=ABSENT detail='Traceback (most recent
call last):'`. The detail now takes the **last** stderr line. Live, from today's
desktop bundle: `pyrealsense2 -> ModuleNotFoundError: No module named
'pyrealsense2'`.

**F5c, reproduced:**

```text
  permission denied (rc=2)       -> NONE
  no such directory (rc=2)       -> NONE
  i/o error (rc=1)               -> NONE
  successful EMPTY read (rc=0)   -> NONE
```

All four collapsed to `NONE` — the settled statement *"there is no ROS distro
installed here"*, off a directory that was never read. Now: a failed listing is
`UNKNOWN`, only exit-0-with-nothing is `NONE`, and P0 adds a REPORT quoting the
`ls` line so the operator can still tell the cases apart:

```text
`ls /opt/ros` exited 2 and printed: ls: cannot access '/opt/ros': No such file or directory —
a listing that FAILED is classified UNKNOWN, never NONE: 'could not read' and 'read, and there
is nothing there' have different remedies, and only the second is an owner decision about
installing a distro. Confirm by hand before acting.
```

This changes what this desktop reports (`distro=UNKNOWN`, was `NONE`) — see the
OR-1 addendum, M2.

---

## 7 · F5d — the M10 command does not do what M10 says

```text
$ .parcel/bin/python -B -m scripts.parcel_capture.orin_rehearsal --evidence-dir <dir> \
    --record-target <dir> --firmware-attested V1.1.13 --until p3_network
[   PASS] p0_identity …
[   FAIL] p1_environment …
[SKIPPED] p2_storage     skipped: p1_environment failed and a failed phase stops the ones that
                         depend on it (pass --keep-going to run them anyway; …)
[SKIPPED] p3_network     skipped: p1_environment failed …
EXIT=1
```

`p3_network` is **SKIPPED**, not `PASS`. `--until` selects how far to go; it
does not override the stop-on-failure rule. The generated runbook row now says
so, which is the fix that survives the next reader:

```text
| `--until PHASE` | Stop after PHASE. Later phases are written as `SKIPPED`. It does **not**
make PHASE run: if an earlier phase FAILs, PHASE is `SKIPPED` too, so pair it with
`--keep-going` when you want the named phase to run regardless. |
```

---

## 8 · F5e — the Jazzy recipe needs a writable `$HOME`

The recipe as printed in OR1_STATUS §3 binds the repo read-only at `/mnt` and a
scratch at `/work`, and leaves `$HOME` on the read-only rootfs:

```text
$ bwrap --ro-bind …ros-jazzy-base-sandbox / … --bind <work> /work … \
    /bin/bash -lc 'source /opt/ros/jazzy/setup.bash; …'
HOME=/home/jaewoo-jang
touch: cannot touch '/home/jaewoo-jang/.probe': Read-only file system
HOME NOT WRITABLE

# P5 through that same shell:
P5 FAIL | the recorder wrote nothing to /work/parcel_rehearsal_bench_bag
          (Failed opening file /home/jaewoo-jang/.ros/log/python3_28_1786746162356.log
           for writing: Read-only file system)
```

With one word added — `export HOME=/work` — the identical command is:

```text
P5 PASS | help verified -> argv rendered for jazzy -> 8s recorded -> 309 message(s) read back
          clean -> sidecar refused the unmapped bench bag, as it must
```

That second run is also this card's **real-ROS-2 re-verification of the fixed
code**: 9 flags cleared against the installed `ros2 bag record --help`, a real
MCAP written to the record target (`102,636 B`, sha256
`6223a184882a17e597754fb7d0a41f225fbc04438b146fbc832d3e3df3355b4f`),
`counts={'/parcel_rehearsal/imu': 232, '/parcel_rehearsal/range': 77}`,
`termination=['clean']`, `count_basis=['walked_messages']`, the sidecar refusing
the unmapped bench bag as it must, and step 8's reconciliation **running** and
returning 5 refusals (`ok=False`) — the branch F2 now distinguishes from a
crash. The requirement is documented in the generated runbook, for the Orin as
much as for the sandbox.

---

## 9 · F5f — the `.pyc` claim

At 18:22, before FX-2 executed anything:

```text
-rw-rw-r-- 1 jaewoo-jang jaewoo-jang 146137 Aug 14 18:04 orin_rehearsal.cpython-314.pyc
$ stat -c '%n %y' scripts/parcel_capture/__pycache__/orin_rehearsal.cpython-314.pyc
scripts/parcel_capture/__pycache__/orin_rehearsal.cpython-314.pyc 2026-08-14 18:04:09 -0400
```

OR1_STATUS §8's *"no `.pyc` exists for the new module"* was false when written
and is unprovable as a standing claim: any import by any process without `-B`
recreates it. Every other `.pyc` in that directory was rewritten at 18:30–18:31
by a process that was not FX-2's (all FX-2 invocations carry `-B` and
`PYTHONDONTWRITEBYTECODE=1`). Corrected by dated addendum to the narrower claim
that OR-1's own invocations used `-B`. FX-2 purged the `.pyc` for both modules
it mutated, so no bytecode compiled from a mutant survives this card.

---

## 10 · Mutation discipline — every regression proven to redden

Each fix was reverted in place, the matching tests re-run, and the file restored
and sha256-compared. Full script: `scratchpad/fx2/mutate.py`.

```text
REDDENS              F1a child script scores only what delivered: 1 failed in 1.16s
REDDENS              F1b P4 scores the delivered map only: 2 failed in 2.18s
REDDENS              F2 step 8 swallows the exception into PASS: 2 failed in 0.16s
REDDENS              F3 the 1.0 allowance floor is back: 5 failed, 6 passed in 0.24s
REDDENS              F4 the digest sees one CameraInfo per topic again: 3 failed in 0.20s
REDDENS              F5a the guard reads the topic name only: 7 failed in 0.18s
REDDENS              F5b the probe detail takes the first stderr line: 1 failed in 0.12s
REDDENS              F5c a failed listing is NONE again: 5 failed in 0.16s
REDDENS              F5d/F5e the runbook rows lose the honesty: 3 failed in 0.15s

restored byte-identical  orin_rehearsal.py 4ed8e21e8160bfea
restored byte-identical  sidecar.py        ea74e1f3bcffa5ad
restored byte-identical  ORIN_RUNBOOK.md   0b19c19c438410c4

FAILURES: none
```

`F3`'s row shows `5 failed, 6 passed` because the sweep's 6 legitimately-certifying
cases must stay green under the mutation — only the 5 deficit cases redden,
which is the sweep proving it is comparing something.

---

## 11 · Gates

```text
$ .parcel/bin/python -B -m pytest tests/test_orin_rehearsal.py -q
108 passed

$ .parcel/bin/python -B -m pytest tests/test_rosbag2_sidecar.py -q
94 passed

$ .parcel/bin/python -B -m pytest tests/test_no_arm_pin.py -q
76 passed

$ .parcel/bin/python -B -m ruff check scripts/parcel_capture/orin_rehearsal.py \
    scripts/parcel_capture/sidecar.py tests/test_orin_rehearsal.py tests/test_rosbag2_sidecar.py
All checks passed!

$ .parcel/bin/python -B -c "ast.parse(…, feature_version=(3,10))"
parses under 3.10 grammar: scripts/parcel_capture/orin_rehearsal.py
parses under 3.10 grammar: scripts/parcel_capture/sidecar.py

$ .parcel/bin/python -B -m scripts.parcel_capture.orin_rehearsal --check-runbook
…/scrum/20260814/task_1/ORIN_RUNBOOK.md matches the generator
```

**Nothing arms anything.** No publisher, no motion client, no lease, no vendor
SDK; `.parcel/` untouched; the recursive no-arm pin is green over both modules,
statically and dynamically, and F5a made the bench source strictly narrower than
it was. No `git commit`, `stash` or `checkout` was run. All scratch lived under
the session scratchpad.

---

## 12 · does_not_prove

1. **P4 has still never seen a camera.** Every P4 result here comes from the
   real child script driven by a **stub** `pyrealsense2` this card wrote. The
   scoring logic is proven; the vendor API is not. OR1_STATUS §9.3 stands
   unchanged.
2. **The IMU spelling is now load-bearing and unverified.** P4 fails if the
   pipeline profile does not report streams matching `CONFIGURED_STREAMS`, and
   the accel/gyro names come from documentation and the stub, not from a
   `pyrealsense2` build on the Orin. If that build spells them differently the
   phase FAILs on a healthy camera — fail-closed, with the reported names in the
   bundle and a remedy saying so, but it is a false FAIL and it will cost bench
   minutes.
3. **F2's fix is proven against injected exceptions, not against a real S-1
   API change.** The regression raises `TypeError` and blocks the import; that
   the *real* preflight surface will fail in one of those two shapes is an
   assumption.
4. **F3 refuses more than it used to, and short bags are the cost.** A
   legitimately short bag (under 10 images) with a one-message CameraInfo
   deficit now refuses GO-RECORD. That is the intended direction, but no real
   short bag has been through it — every case in the sweep is a fixture.
5. **F4 leaves a named gap.** A calibration that first changes *after* the
   collected window (64 CameraInfo per split file) is still invisible to the
   digest, and closing it needs a change in `rosbag2.py`, which this card does
   not own. The drift check also cannot see drift *between* the sampled window
   and the end of a single-split bag — which, with `--max-bag-size 0`, is the
   session's normal shape. **This is the most consequential thing FX-2 did not
   fix.**
6. **The digest value changed.** Any external record of a calibration digest
   taken before today (S1_STATUS M4's `fc658526…`) no longer reproduces. No
   frozen manifest or sentinel pins one — checked — but a human comparing to an
   old status doc will see a mismatch that is not a defect.
7. **Nothing here ran on the Orin, or on Humble.** The real-bytes re-run is
   Jazzy in the repository's sandbox on x86-64. The Humble argv is still cleared
   against a fixture help text only.
8. **The `ros2` shim in §3's reproduction is not `ros2`.** It answers `--help`
   from the repository's captured Jazzy text and writes a fixture bag on SIGINT.
   It proves the harness's orchestration and the step-8 branch; the sandbox run
   in §8 is what proves the real recorder still works after the change.
9. **F5c's classification is coarser than the truth.** *"No such file or
   directory"* really does mean there is no ROS at `/opt/ros`, and it is now
   reported as `UNKNOWN` along with genuinely unreadable cases. The stderr line
   is quoted so a human can tell them apart; the harness does not, on purpose,
   because parsing localised `ls` messages is a worse dependency than a coarser
   verdict.
10. **A fix tranche is not a readiness verdict.** Nothing here moves the
    three-way verdict; that remains AU-F/Fable's, and it still requires H-2
    evidence from the actual Orin.

---

## 13 · Close gate

```text
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-14T22:50:16Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 |
                                          mutation panel clean | follow-bench 7 rows,
                                          hard_collision_total all 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.29s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              5347 passed, 9 skipped, 36 deselected, 5 warnings in 223.11s
RESULT: PASS — every hard gate green.
  elapsed 234.8s
```

**ruff: 7 violations, baseline 7, new 0** — this card contributed none, and the
two it did introduce while writing were fixed before the gate ran. The default
suite is **5,347 passed** (5,286 at OR-1's close): +26 in
`tests/test_orin_rehearsal.py`, +15 in `tests/test_rosbag2_sidecar.py`, the rest
from other cards in flight in this tree during the run. `frozen-digest-sentinels`
is green, which is the independent check that F4's changed calibration digest
pinned nothing immutable. Other FX tranches were editing this tree concurrently;
nothing FX-2 owns was red at the minute the gate ran.
