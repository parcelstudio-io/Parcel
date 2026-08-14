# PS-B status — MCAP recorder + `parcel.bag.v1` sidecar

**Card:** PS-B (`README.md` §PS-B) · **Executor:** Opus · **Date:** 2026-08-13
**Base:** `406f9d6` (the board's stated base; confirmed `git log -1`)
**Verdict:** complete, every gate measured. One deliberate scope boundary and
one design call are flagged for the auditor in §OWNS deviations — the
self-contained MCAP writer, and the absence of live subscriber backends.

---

## What I built

| Path | Lines | What it is |
|---|---|---|
| `scripts/parcel_capture/record.py` | 1666 | Self-contained MCAP subset **writer**, a recovery **reader** that classifies how a bag ends, the crash-safe **`CaptureRecorder`**, the space-budget refusal, the live-source dependency seam, and the `--check`/`--verify` CLI. |
| `scripts/parcel_capture/sidecar.py` | 1202 | `parcel.bag.v1` sidecar built by **reading the bag back**: termination classification, per-channel counts/rates/deficits/number-lines, origin derivation, digest binding, mount-geometry validation, atomic durable write, verification. |
| `tests/test_capture_sidecar.py` | 1363 | 102 cells over 8 gate groups, every property cell paired with a seeded-failure companion. |

No other file was created or modified. `git status --porcelain` over every
MUST-NOT-TOUCH path is **empty** (C11).

### The one sentence this card serves

A bag whose recorder was killed must still yield a complete, honest manifest,
and that manifest must say **truncated**, never **the LiDAR was flaky**.

### Why `bags/recorder.py` could not carry a physical session

The card asked for this contrast precisely, so here it is at file:line. Its
**schema** is kept and called unmodified; only its **transport** is replaced.

| `bags/recorder.py` | Consequence for 2026-08-13 | What `record.py` does |
|---|---|---|
| `:111` `json.dumps(message)` per message | A 1280×720 RGB8 frame is 2.6 MiB of pixels; it is not a JSON line. Base64 in JSON would inflate it ~33% on a 132 MiB/s stream. | MCAP `Message` records carry **raw device bytes** after a length-prefixed envelope header. Measured header cost: **352 B/message** (C9). |
| `:116` `self._write_manifest()` after **every** `record()` | The manifest is rewritten in full in the per-message hot path — O(bag) work per message, and the file is `write_text`'d, so a crash during it can leave the manifest itself half-written. | Nothing already written is ever revisited. The manifest is a **recovery pass** over the bytes (`sidecar.build_sidecar`), so it is obtainable *after* a SIGKILL rather than destroyed by one. |
| `:40-41` refuses a non-empty bag, and there is **no `fsync` anywhere in the file** | An interrupted recording is both unresumable and unbounded in what it lost — the page cache decides. | `CaptureRecorder` fsyncs on a policy (`fsync_every_ns`, default 1 s; `fsync_every_messages`), fsyncs the channel table immediately at open, and `write_sidecar` does temp-file → fsync → `os.replace` → fsync-dir. |
| `:94-98,114` one **global** `sequence`, stamped before the write and incremented **after** it | A message never written never advances the counter, so a lost message leaves *no hole at all*; and one counter cannot attribute a hole to a channel. | PS-A's `ChannelSequenceBook.stamp()` mints **per channel, at receipt**. `CaptureRecorder.drop()` burns a number for a message received and not written, so backpressure loss is provable and attributed. |
| `schema.py:17-18` "metadata-first in the sim MVP" | — | `schema.py` is **called, not edited**: `make_manifest(source="hardware")` (`:254`), `default_clocks(source_clock="sensor")` (`:130`), `default_frames()` (`:113-127`), `extra` (`:293,311-313`). Its own `validate_manifest` accepts the result (C6). |

### How truncation is kept apart from a dropout

Four outcomes, from **disjoint evidence**, so neither can be inferred from the
other's signal:

| outcome | the evidence, and only this evidence |
|---|---|
| `TRUNCATED` | framing: no `DataEnd`+`Footer`+terminal magic, or a record whose declared length runs past EOF |
| `CORRUPT` | bytes all present, decode failed (bad envelope, unknown channel, MCAP/envelope sequence disagreement) |
| `LATCHED_WRITE_FAILURE` | the recorder's own close record, written **into** the bag before the footer, names a latch |
| per-channel `DEGRADED` | an **interior** hole in one channel's number line, or a delivered count outside tolerance |

The structural reason this works: a truncation removes a **suffix** of the
single append-only byte stream, so every channel loses its tail and *no channel
gets a hole*. A backpressure drop removes an **interior** receipt, so exactly
one channel gets a hole and the footer is still there. Measured both ways in
C3.

Rate assessment is computed over the **span actually present in the bag**, not
the session the operator asked for. Without that, a bag truncated at the
halfway mark would report all fifteen channels at 50% and turn one truncation
into fifteen fabricated sensor faults. C3 shows a truncated bag reporting both
its channels `present`.

---

## The MCAP decision, stated as the card requires

`mcap` is not installed in `.parcel/` and the board forbids installing it. Both
options the card offers are taken, but the load-bearing one is the second:

1. **The seam.** `cross_validate_with_mcap_library()` uses the reference `mcap`
   package when it exists and reports `("unavailable", …)` here. The sidecar
   records that status verbatim under
   `capture.mcap.reference_reader_validation` and adds a `does_not_prove` line
   whenever it is not `"validated"` — an unproven claim is recorded as
   unproven, never omitted.
2. **A self-contained writer.** `MinimalMcapWriter` emits a subset of MCAP 0.9:
   magic · `Header` · one `Schema` + one `Channel` per capture channel ·
   `Message` records · a `Metadata` close record · `DataEnd` · `Footer` ·
   terminal magic. **No chunking, no compression, no message index, no summary
   section** — and those omissions are the point: chunk-compressed writing
   buffers messages *inside* the writer, which is precisely the state a SIGKILL
   destroys, and an index written at close is precisely the structure a SIGKILL
   never reaches.

A fake would not have satisfied the crash gate. Killing a process that writes
JSON lines proves something about JSON lines. The SIGKILL test kills a process
writing **real MCAP bytes**, and the reader recovers 613–811 real messages from
them (C2).

**Risks of hand-rolling it, in full:**

* **This writer has never been read by the reference implementation.** That is
  the single biggest risk on this card. It is stated in every sidecar it
  produces, and `--check` prints `mcap reference reader: ABSENT`. The first
  action on the Orin should be `pip install mcap` **in the deploy venv** (never
  `.parcel/`) and `cross_validate_with_mcap_library(bag)`.
* `data_section_crc` and `summary_crc` are written as `0` — the spec's "not
  available" value. This is a deliberate refusal to emit a checksum whose exact
  byte range I could not validate against a reference reader; a wrong CRC is
  worse than an absent one. Integrity is carried instead by the sidecar's
  SHA-256 over the whole file (C4).
* No summary section means `mcap info`-style tooling may report no statistics,
  and seeking is linear. For a read-once dataset that is acceptable; if it is
  not, `mcap recover`/`mcap convert` on the Orin can add indexes — and the
  reader tolerates that (it steps over `MessageIndex`/`ChunkIndex`/`Statistics`
  and counts them in `skipped_records`, which becomes a sidecar finding).
* A `Chunk` record is deliberately **not** skipped: it contains messages, and
  stepping over one would silently lose them. It is classified `CORRUPT`.
* `profile="parcel-capture"` and `message_encoding="parcel.capture.envelope.v1+raw"`
  are custom strings. A generic ROS-shaped consumer will not decode the
  payloads without the framing, which is `uint32 header_len | envelope JSON |
  raw device bytes` and is documented in the module docstring and in every
  bag's own `Schema` records.

---

## MEASURED claims

Every row was executed; the command and its output are verbatim. This document
contains exactly one estimate — the session-wide envelope-overhead figure in
C10 — and it is labelled as an estimate where it appears.

### C1 — the suite

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 0.39s
```

### C2 — crash safety: a real `SIGKILL`, five trials

The child records `sportmodestate` + `utlidar/cloud` with `fsync_every_ns=None`
and an 8 KiB buffer, so the surviving bytes are exactly the ones userspace
flushed. The parent waits for the file to pass 60 KiB, then `SIGKILL`s it and
asserts `returncode == -9`.

```
$ .parcel/bin/python <scratchpad>/sigkill_trials.py
trial 0: bytes=262600 msgs=613 term=truncated trailing=0 close=None
trial 1: bytes=347014 msgs=811 term=truncated trailing=0 close=None
trial 2: bytes=285622 msgs=667 term=truncated trailing=0 close=None
trial 3: bytes=308644 msgs=721 term=truncated trailing=0 close=None
trial 4: bytes=339340 msgs=793 term=truncated trailing=0 close=None
```

The suite cell asserts, on the live kill: `termination is TRUNCATED`,
`message_count >= 50`, `close_metadata is None`, every recovered envelope
decodes with `origin=PHYSICAL`, **every channel's number line runs 0..n-1 with
`is_clean`** (nothing before the cut was lost), and the sidecar's
`termination.kind == "truncated"` with `saw_terminal_magic == False`.

**`trailing=0` in every trial is a real finding, not a flaw.** Python's
`BufferedWriter` never splits a single `write()`, and this writer emits exactly
one `write()` per record, so a SIGKILL always cuts on a record boundary. A
machine power cut does not — the page cache goes with it at an arbitrary
offset — so the mid-record case is proved **deterministically** instead, at
five different cut depths:

```
$ .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q -k truncation_is_recognised
.....                                                                    [100%]
5 passed
```

and directly, across the whole tail of a real bag:

```
cut= 40523 -> truncated msgs= 102 lco= 40516 trail=   7 | footer present but terminal magic is 7 of 8 bytes
cut= 40504 -> truncated msgs= 102 lco= 40487 trail=  17 | record opcode 0x02 at offset 40487 declares 20 bytes, 8 present
cut= 40324 -> truncated msgs= 102 lco= 39883 trail= 441 | record opcode 0x0c at offset 39883 declares 582 bytes, 432 present
cut=  4000 -> truncated msgs=   4 lco=  3855 trail= 145 | record opcode 0x05 at offset 3855 declares 357 bytes, 136 present
cut=   100 -> truncated msgs=   0 lco=    76 trail=  24 | record opcode 0x03 at offset 76 declares 558 bytes, 15 present
cut=     8 -> truncated msgs=   0 lco=     8 trail=   0 | file ends without a complete terminal structure (data_end=False, ...)
cut=     5 -> truncated msgs=   0 lco=     0 trail=   5 | file ends inside the leading MCAP magic after 5 of 8 bytes
```

### C3 — the refutation panel: two worlds a count-only oracle cannot separate

Both bags hold **exactly 90** recovered `utlidar/cloud` messages. One was cut
after its 90th message; the other ran to a clean close and lost ten to
backpressure in the middle.

```
$ .parcel/bin/python -m scripts.parcel_capture.record --verify <demo>/dropping.mcap
bytes: 35772  messages recovered: 90
termination: clean
recorder close record: {... 'messages_written': '90', 'counts': '{"go2.utlidar.cloud":90}', 'drops': '{"go2.utlidar.cloud":10}', ...}
  go2.utlidar.cloud            90  missing=10
PER-CHANNEL LOSS: 10 message(s) were received and never written. The framing is intact, so this is loss, not truncation.
exit=5

$ .parcel/bin/python -m scripts.parcel_capture.record --verify <demo>/truncated.mcap
bytes: 210081  messages recovered: 560
termination: truncated
detail: file ends without a complete terminal structure (data_end=False, footer=False, magic=False)
recorder close record: ABSENT (the recorder never closed this bag)
  go2.sportmodestate           466  missing=0
  go2.utlidar.cloud             94  missing=0
exit=4
```

The suite cell `test_a_truncated_bag_and_a_dropping_sensor_are_never_confused`
asserts the identical count (90 == 90), then the four disjoint discriminators:
`kind` truncated vs clean, `saw_terminal_magic` False vs True,
`missing_count` 0 vs 10 (with `missing == [40..49]`), and that **neither report
carries the other's language** (no `TRUNCATED` line in the dropping sidecar; no
`sequence_gap` reason anywhere in the truncated one). The recorder's own drop
tally is reconciled against the holes: `recorder_account.status == "agrees"`.

Even the CLI exit codes are kept apart: `4` = not byte-clean, `5` = byte-clean
with per-channel loss.

A truncated bag also does **not** manufacture rate faults — both channels above
report `present` over the recorded window:

```
"go2.sportmodestate": {"verdict": "present", "reason": "within_tolerance: 466 of 465 expected message(s) over 9.300s", ...}
"go2.utlidar.cloud":  {"verdict": "present", "reason": "within_tolerance: 94 of 93 expected message(s) over 9.300s", ...}
```

### C4 — digest binding

```
$ .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q -k "mutated_byte or appended_byte or different_bag or damaged_sidecar or digest_moves"
..........                                                               [100%]
10 passed
```

One flipped byte at the head, the middle, or the tail of the MCAP — **without
changing the file size** — makes `verify_sidecar` return `ok=False` naming
`digest mismatch`, and `verify_sidecar_or_raise` refuse. An appended byte trips
both the digest and the size check. A sidecar built for bag A does not verify
against bag B. `sidecar_digest` moves for all five single-field mutations tried
(6 distinct digests from 6 documents).

### C5 — per-channel expected count: 90% of nominal is degraded, with the deficit

`utlidar/cloud` (nominal 10 Hz) driven at 9.0 Hz for 20 s beside
`sportmodestate` at its nominal 50 Hz:

```
"go2.utlidar.cloud": {"verdict": "degraded",
  "reason": "rate_below_expectation: 180 of 199.8 expected message(s) over 19.980s, short by 19.8 (9.9%)",
  "messages": 180, "expected_messages": 199.8, "deficit_messages": 19.8,
  "deficit_fraction": 0.099099, "observed_rate_hz": 9.009009, "expected_rate_hz": 10.0,
  "is_fault": true}
"go2.sportmodestate": {"verdict": "present", ...}
```

**Refutation, and why this is a separate gate from PS-A.** A sensor publishing
at 90% of nominal delivers a **contiguous** number line — nothing was received
and lost, so PS-A's ledger is spotless:

```
$ .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q -k refutation_the_per_channel
.                                                                        [100%]
1 passed
```
asserting `report.is_clean`, `missing_count == 0`, `duplicate_count == 0`,
`first_sequence == 0`, `last_sequence == 179`. Only the expected-count
assertion sees the deficit. The two gates cannot be collapsed into one.

Companion verdicts, all measured in the suite: a silent **periodic** channel is
`absent` **and** a fault; a silent **event-driven** channel (`wirelesscontroller`)
is `absent` and **not** a fault; a `CONFIGURED` channel (`d455.color`) with no
supplied rate is `unassessable`, never `present`, and the sidecar says
"unassessed is not passed"; over-delivery is `rate_above_expectation`, reported
as a finding about the channel matrix rather than a pass.

### C6 — the manifest is unmodified `parcel.bag.v1`

```
$ .parcel/bin/python -c "<build a sidecar and print the schema-owned keys>"
{"schema_version": "parcel.bag.v1", "bag_id": "P5-DRY-20260813-demo", "source": "hardware",
 "hardware_claims": true, "message_count": 560,
 "topics": ["go2/utlidar/cloud", "go2/sportmodestate"],
 "clocks": {"source_clock": "sensor", "recording_monotonic_origin_ns": 1700000000000000000,
            "note": "... recording_monotonic_origin_ns is this host's monotonic clock at the first
                     message in the bag; it has a per-machine arbitrary epoch and is comparable
                     across devices only through the PS-C clock map."}}
```

`bags.schema.validate_manifest(sidecar)` accepts it, every `topic` passes
`validate_topic`, and `REQUIRED_MANIFEST_KEYS ⊆ set(sidecar)` — all asserted in
`test_the_manifest_is_an_unmodified_parcel_bag_v1`.

Two schema-facing decisions the auditor should see:

* `default_clocks` hands back `recording_monotonic_origin_ns: 0`
  (`schema.py:134`), which **is** the arbitrary-epoch defect the plan names. I
  overwrite it with the bag's first monotonic sample so intra-bag offsets mean
  something, and extend the note to say cross-device recovery still needs PS-C.
* `make_manifest` hard-codes `hardware_claims: False` (`schema.py:308`). I set
  it through `extra` to `source == "hardware"`, i.e. **True only when the
  envelopes in the bag actually declare `PHYSICAL`**. A consumer keying off that
  flag would otherwise under-read a real session bag. Flagged rather than
  slipped; `tests/test_bags_roundtrip.py:93` pins `False` for the *sim replayer*
  and is unaffected.

### C7 — `ENOSPC`/`EDQUOT` latch, the record survives, degradation fails closed

```
$ .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q -k "write_failure or latched or close_never_raises or declaring_drops"
.......                                                                  [100%]
7 passed
```

`ENOSPC` and `EDQUOT` latch `DISK_FULL`; `EIO` latches `WRITE_FAILED` under its
own name. After a latch every later `record()` raises `RecorderLatchedError` —
degradation is a refusal, not a silent drop — the bytes already written survive,
and `close()` **never raises** even when the volume is still broken (it reports
in `RecorderSummary.close_problem`, the W0-B rule that a teardown failure costs
a digest and never the evidence). A bag that latched but still got its footer
written is byte-`clean` **and** reported as
`termination.kind == "latched_write_failure"` with a `does_not_prove` line, and
carries **no** truncation language.

### C8 — refusing to start

```
$ .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q -k "refuses_to_start or free_space or nonsense_budget or overwrite or underdeclared or undeclared_channel"
...............                                                          [100%]
15 passed
```

No `SpaceBudget` ⇒ `RecorderRefusedError: refusing to start: no SpaceBudget
supplied — the PS-E budget for the requested duration is required before
recording; unknown is not permission`, and **no file is created**. A budget
that does not fit the measured free space refuses. `bytes_per_second` of 0,
negative, `NaN`, `inf`, `True`, a zero duration, or a negative margin are each
refused at construction. A non-empty destination bag is refused ("a session's
bytes are never reconstructable"). `EvidenceOrigin.UNKNOWN`, an empty channel
list, a duplicate channel, and a blank `bag_id` are each refused.

### C9 — the CLI refuses cleanly on this box, and nothing was installed

```
$ .parcel/bin/python -m scripts.parcel_capture.record --check --dest /tmp --duration-s 600 --bytes-per-second 60000000
channels requested: 22
  go2.utlidar.cloud        dds             live               UNAVAILABLE (missing: rclpy)
  ...
  go2.front_camera         vendor_video    live               UNAVAILABLE (missing: unitree_sdk2py)
  l2.cloud                 unilidar_sdk2   live               UNAVAILABLE (missing: unilidar_sdk2)
  d455.color               realsense       live               UNAVAILABLE (missing: pyrealsense2)
  orin.tegrastats          platform_tool   live               UNAVAILABLE (missing: tegrastats)
  gnss.zed_f9p             serial          confirm_on_hand    UNAVAILABLE (missing: serial)
  uwb.owner_fob            vendor_uwb      confirm_on_hand    UNAVAILABLE (missing: unitree_sdk2py)
  mic.xvf3800              usb_audio       awaiting_hardware  reader deps present

what each missing requirement needs:
  pyrealsense2: Orin only: pip install pyrealsense2 inside the deploy venv
  rclpy: Orin only: source /opt/ros/humble/setup.bash (JetPack 6.2.x ships it)
  serial: Orin only: pip install pyserial inside the deploy venv
  tegrastats: Orin only: ships with JetPack; absent on any non-Jetson host
  unilidar_sdk2: Orin only: build unitree unilidar_sdk2 and put it on PYTHONPATH
  unitree_sdk2py: Orin only, and NEVER into .parcel/ — its absence from the Parcel venv is the project's strongest motion guarantee (PHYSICAL_SESSION_PLAN.md)

space: OK — 128703524864 bytes free at /tmp, 41400000001 required for 600s at 6e+07 B/s (+15% margin)
mcap reference reader: ABSENT — optional, cross-validation only: pip install mcap inside the DEPLOY venv to check this writer against the reference reader

# stderr, captured separately:
REFUSED: this host cannot run a live capture. That is the expected outcome on the dev box: the
capture stack is a deploy artifact for the Orin (JetPack 6.2.x / Humble / Python 3.10). Nothing
was installed.
$ echo $?
3
```

No traceback on any path: `--verify` on a missing file and on a non-MCAP file
both print `REFUSED: …` and exit 2 (asserted in the suite, including that the
combined stdout+stderr contains no `"Traceback"`).

`orin.tegrastats` is probed with `shutil.which`, not a module lookup — a
module-only probe reported it `READY` on this laptop, which is exactly the
"unknown reads as ready" failure board rule 3 forbids. Fixed and gated.

**The motion guarantee, measured:**

```
$ .parcel/bin/python -c "import importlib.util as u; [print(f'{m}: {\"PRESENT\" if u.find_spec(m) else \"absent\"}') for m in ['rclpy','cyclonedds','unitree_sdk2py','pyrealsense2','cv2','mcap','zstandard']]"
rclpy: absent
cyclonedds: absent
unitree_sdk2py: absent
pyrealsense2: absent
cv2: absent
mcap: absent
zstandard: absent
$ git diff --stat pyproject.toml
 pyproject.toml | 2 ++      # pre-existing ruff extend-exclude, not mine; no dependency added
```

`test_nothing_in_these_scripts_can_arm_anything` walks the AST of both my
modules and asserts no `import` of `unitree_sdk2py` / `parcel_robot.control` /
`parcel_robot.runtime` / `rclpy`, and no identifier named `create_publisher`,
`Publisher`, `ControlManager`, `create_control_manager`, `set_target`,
`acquire_lease`, `Move`, `SportClient` — with a negative control proving the
scan really fires on `ControlManager()`. A companion cell asserts the module
*names* appear only as string data (they are the refusal list) and never in an
import statement.

### C10 — per-message framing cost (measured), and the session estimate (labelled)

```
$ .parcel/bin/python -c "<stamp one lowstate envelope, measure canonical_json>"
envelope json bytes: 317
per-message framing overhead: 352 bytes (record header + mcap fields + len prefix + envelope)
at 500 Hz: 171.875 KiB/s
```

**Estimate (labelled as such, not measured):** summing the matrix's nominal
rates for the DDS + L2 channels (~991 msg/s) gives ≈340 KiB/s ≈ **1.2 GiB/hour
of envelope overhead alone**, against a D455 budget PS-E puts at 205–464
GiB/hour. Negligible in context, but if PS-E wants it back, the lever is a
compact binary envelope in place of JSON — not a change to what is recorded.

### C11 — scope: nothing outside OWNS moved

```
$ git status --porcelain -- src/parcel_robot/bags/ src/parcel_robot/runtime.py src/parcel_robot/pose.py \
      src/parcel_robot/navigation/ src/parcel_robot/route_memory/ evals/ src/parcel_robot/core/collision.py
(empty)
$ git status --porcelain -- scripts/parcel_capture/ tests/test_capture_sidecar.py
?? scripts/parcel_capture/
?? tests/test_capture_sidecar.py
```

`bags/schema.py` is untracked-clean — it is *imported and called* by
`sidecar.py` and appears in no diff.

### C12 — lint

```
$ .parcel/bin/python -m ruff check --output-format=concise scripts/parcel_capture/record.py scripts/parcel_capture/sidecar.py tests/test_capture_sidecar.py
All checks passed!
```

Zero new `(file, rule)` fingerprints against `scripts/ci_ruff_baseline.json`
(baseline 7).

---

## Seeded-failure table

Every mutation below was applied to the **real source on disk** by a harness,
the suite re-run with bytecode caching fully disabled (`-B`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `__pycache__` removed —
PS-A's harness finding, which I adopted), and the source restored; the harness
verifies both files are byte-identical afterwards.

| # | Gate | Seeded fault | Proof it was caught |
|---|---|---|---|
| G1 | Framing / footer is the truncation signal | recorder never writes `DataEnd`+`Footer` (M1) | `FAILED test_a_clean_recording_round_trips_every_envelope_and_ends_with_a_footer`; the in-suite companion `test_seeded_failure_a_bag_without_its_footer_is_never_called_clean` flushes bytes without ever calling `finish()` and asserts `TRUNCATED` |
| G2 | Truncation is never called clean | `classify_termination` returns CLEAN for a truncated scan (M2) | `FAILED test_seeded_failure_a_bag_without_its_footer_is_never_called_clean` |
| G3 | A short record is truncation, not corruption | short read classified `CORRUPT` (M3) | `FAILED test_sigkill_mid_recording_leaves_a_readable_bag_recorded_as_truncated` |
| G4 | Digest binding | `verify_sidecar` ignores a digest mismatch (M4) | `FAILED test_seeded_failure_one_mutated_byte_breaks_sidecar_verification[head]`; in-suite: 3 flip positions, an appended byte, a foreign bag, and 3 damaged-sidecar shapes |
| G5 | 90%-of-nominal is degraded | `RATE_TOLERANCE` widened 0.02 → 0.50 (M5) | `FAILED test_a_channel_at_ninety_percent_of_nominal_is_degraded_with_the_deficit` |
| G6 | `ENOSPC`/`EDQUOT` lane | `_DISK_FULL_ERRNOS` emptied (M6) | `FAILED test_a_write_failure_mid_record_latches_by_name_and_the_record_survives[28-disk_full]` |
| G7 | No budget is not permission | `check_space(None)` returns `ok=True` (M7) | `FAILED test_the_recorder_refuses_to_start_without_a_budget` |
| G8 | A bag mixing origins is refused | mixed-origin guard relaxed (M8) | `FAILED test_a_bag_that_mixes_origins_is_refused_not_majority_voted` |
| G9 | Mount extrinsic must state method + uncertainty | required-key check removed (M9) | `FAILED test_seeded_failure_a_mount_entry_missing_a_required_key_is_refused`; in-suite: 9 malformed shapes and 6 missing-key shapes each refused |
| G10 | A malformed digest is a refusal, not an absence | malformed digest recorded as `status:"absent"` (M10) | `FAILED test_seeded_failure_a_malformed_digest_is_refused_never_recorded_as_absent[]`; in-suite: 7 malformed digests |
| G11 | A backpressure drop leaves an interior hole | `drop()` no longer burns a sequence number (M11) | `FAILED test_a_truncated_bag_and_a_dropping_sensor_are_never_confused` — the refutation panel is the cell that reddens, which is the point |
| G12 | The bag cross-checks itself | reader stops comparing MCAP `sequence` to the envelope's (M12) | `FAILED test_a_message_whose_envelope_disagrees_with_its_mcap_sequence_is_corrupt` |

```
$ .parcel/bin/python <scratchpad>/mutate_psb.py
baseline: GREEN | 102 passed in 0.40s
M1 recorder never writes the footer: CAUGHT | FAILED …::test_a_clean_recording_round_trips_every_envelope_and_ends_with_a_footer
M2 a truncated scan is classified CLEAN: CAUGHT | FAILED …::test_seeded_failure_a_bag_without_its_footer_is_never_called_clean
M3 a short record reads as CORRUPT, not TRUNCATED: CAUGHT | FAILED …::test_sigkill_mid_recording_leaves_a_readable_bag_recorded_as_truncated
M4 verify_sidecar ignores a digest mismatch: CAUGHT | FAILED …::test_seeded_failure_one_mutated_byte_breaks_sidecar_verification[head]
M5 rate tolerance widened past the 10% deficit: CAUGHT | FAILED …::test_a_channel_at_ninety_percent_of_nominal_is_degraded_with_the_deficit
M6 ENOSPC no longer classified as disk full: CAUGHT | FAILED …::test_a_write_failure_mid_record_latches_by_name_and_the_record_survives[28-disk_full]
M7 a missing space budget becomes permissive: CAUGHT | FAILED …::test_the_recorder_refuses_to_start_without_a_budget
M8 a bag mixing origins is majority-voted instead of refused: CAUGHT | FAILED …::test_a_bag_that_mixes_origins_is_refused_not_majority_voted
M9 mount geometry accepted without method or uncertainty: CAUGHT | FAILED …::test_seeded_failure_a_mount_entry_missing_a_required_key_is_refused
M10 a malformed digest is recorded as an absence: CAUGHT | FAILED …::test_seeded_failure_a_malformed_digest_is_refused_never_recorded_as_absent[]
M11 a backpressure drop no longer burns a sequence number: CAUGHT | FAILED …::test_a_truncated_bag_and_a_dropping_sensor_are_never_confused
M12 the reader stops cross-checking the envelope sequence: CAUGHT | FAILED …::test_a_message_whose_envelope_disagrees_with_its_mcap_sequence_is_corrupt
tree restored byte-identical
```

Additional seeded faults that live **inside** the suite rather than in the
harness (each is a mutant of the input, not of the module):

| Seeded fault | Proof |
|---|---|
| a fully-present record with one corrupted envelope byte | `CORRUPT`, not `TRUNCATED`; 10 messages still recovered; no `TRUNCATED` line in `does_not_prove` |
| a `Channel` record renamed to an id outside the matrix (same byte length) | `CORRUPT` with `unknown channel_id` — PS-A's fail-closed lookup |
| a bag truncated **before** its channel table | `build_sidecar` refuses ("registers no channels") rather than guessing; with `expected_channels` supplied, every channel is honestly `absent` and `source` falls back to `"sim"` |
| a recorder declaring 4 drops the bag does not show | `recorder_account.status == "disagrees"`, `Unreconciled finding` line in `does_not_prove` |
| `sequence = 2**32`, `log_time = 2**64`, `-1`, `True`, `1.0` at the writer | `McapWriteError` — a wrapped sequence would fabricate a duplicate |
| a file that is not MCAP at all vs one cut inside the leading magic | `NotAnMcapFileError` vs `TRUNCATED` — different findings, never conflated |

---

## OWNS deviations and scope boundaries

**D-1 — no live subscriber backends ship on this card. Stated, not slipped.**
`record.py` provides the writer, the reader, the recorder, the space gate and
the dependency seam. It does **not** provide DDS/RealSense/unilidar subscriber
implementations, and `resolve_live_source()` refuses with the reason. Every
gate the card lists is met without them, none of them could be tested on this
host (`rclpy`, `pyrealsense2`, `unilidar_sdk2`, `unitree_sdk2py` are all
absent — C9), and shipping untested vendor-SDK code on the critical path of a
session the next morning is exactly what board rule 5 forbids. The seam is
where PS-E's synthetic publishers attach, and it is where a backend with its
own measured gate attaches later. **If the auditor reads the card as requiring
a live path today, this is the gap.**

**D-2 — `CaptureRecorder.drop()` is API surface the card did not name.** It
exists because a bounded queue on an 8 GiB Orin *must* be able to drop under
backpressure, and because the alternative — dropping silently — is the defect
this tranche exists to fix. `drop()` burns the channel's next sequence number,
so the loss leaves an interior hole attributed to that channel, and it is
tallied into the close record so the sidecar has two independent statements to
reconcile. It is also what makes the truncation-vs-dropout refutation panel
constructible without reaching into privates.

**D-3 — `hardware_claims` is overridden through `extra`.** See C6. The schema
hard-codes `False`; I set it to `source == "hardware"`, derived from the
envelopes in the bag. Flagged because it changes a value a pre-existing schema
function chose.

**D-4 — the sidecar's `extra` is one namespaced key.** `make_manifest` merges
`extra` at the manifest's top level (`schema.py:313`), so everything the card
requires — `mcap_sha256`, per-channel counts and observed rates, the PS-D
attestation digest, the PS-C clock-map digest, mount geometry — lives under
`extra["capture"]` rather than scattering fifteen names into a namespace the
bag schema owns. `does_not_prove` goes through `make_manifest`'s own
parameter, so the schema validates it. A consumer looking for
`manifest["mcap_sha256"]` will need `manifest["capture"]["mcap"]["sha256"]`.

**D-5 — no import of PS-C's `clockmap.py` or PS-D's `attest.py`.** Those files
were being written by parallel cards while this one ran (`attest.py` last
modified 3 s before I checked). The coupling the card specifies is **by
digest**, which is exactly the decoupling I implemented:
`build_sidecar(clock_map_digest=…, attestation_digest=…)` takes 64-char hex
strings, refuses anything else, and records an absence as an absence. PS-C's
"round-trips through the PS-B sidecar `extra` by digest" gate is met by
`test_a_present_clock_map_and_attestation_digest_round_trip_through_extra`
(write → read → identical `sidecar_digest`). **A live cross-module integration
cell was deliberately not written**, because a test importing a module another
agent is still editing makes my card's redness depend on theirs.

---

## does_not_prove

1. **Nothing here has seen a sensor.** Every bag in every measurement was
   written by this test suite. No message in any of them came off a Go2, an L2,
   a D455 or an Orin. The rates, the message types and the payload sizes are
   PS-A's transcribed expectations, not observations.
2. **This MCAP writer has never been read by the reference `mcap`
   implementation.** It is a hand-rolled subset of the 0.9 spec, validated only
   against its own reader. A framing mistake that both halves share would be
   invisible to every test in this file. `cross_validate_with_mcap_library` is
   the settlement, it reports `unavailable` here, and the first Orin action
   should be to run it. Until then, treat "the bag is readable" as "readable by
   `parcel-capture`".
3. **The CRCs are absent, not verified.** `data_section_crc` and `summary_crc`
   are `0` ("not available"). Integrity is the sidecar's SHA-256 over the whole
   file, which is checked only when someone runs `verify_sidecar`; there is no
   per-record checksum, so a single-bit flip inside one message is detected by
   the file digest but cannot be localised or skipped past.
4. **The SIGKILL test does not model a power cut.** SIGKILL loses the userspace
   buffer; the page cache survives, so the cut lands on a record boundary
   (C2, `trailing=0` in 5/5 trials). A power loss or a kernel panic loses
   unflushed pages at an arbitrary offset. That case is covered by
   *deterministic byte truncation*, which is a faithful model of the resulting
   file but **not** a test of the machine losing power. Nobody has pulled the
   plug on an Orin mid-record.
5. **How much was lost to a truncation is unknowable from the bag.** The
   sequence book's state dies with the process, so a truncated bag can say
   *that* it was truncated and *where*, never *how many receipts the recorder
   had accepted and not yet flushed*. The sidecar says so in its own
   `does_not_prove`.
6. **Per-channel sequencing still does not detect transit loss** (PS-A's limit,
   inherited). A message dropped by DDS or USB before the subscriber callback
   ran was never sequenced and leaves no hole. Only a producer-side counter
   (`lowstate.tick`, a ROS header) cross-checked against ours closes it.
   `capture/envelope.py:34-36` assigns that cross-check to PS-B; **PS-B does not
   deliver it**, because there is no live subscriber here to read a producer
   counter from (D-1). It is the first thing to add once a backend exists, and
   the envelope framing leaves room for it: the producer's counter belongs in
   the payload the adapter hands to `record()`, and the comparison belongs in
   `observe_channels`.
7. **The rate tolerance of 2% is a choice, not a derivation.** It is wide enough
   to absorb the ±1-message edge effect of a finite window (there is also an
   absolute `max(1, …)` floor) and far tighter than the 10% deficit the board's
   gate names. It has never been checked against a real sensor's jitter. A
   bursty-but-complete channel could read `degraded` on a short window.
8. **The session window is the bag's own span.** If *every* channel stops at the
   same instant while the recorder keeps running, the window shrinks with them
   and the outage is invisible to the rate assertion. Only PS-D's live probing
   or an operator-supplied expected duration would catch a whole-rig stall, and
   neither is wired here.
9. **No claim about throughput, latency, memory or thermals.** Every bag written
   here is a few hundred kibibytes on a desktop NVMe. Nothing measures whether
   an Orin sustains 132 MiB/s, what `fsync` every second costs at that rate, or
   whether the 8 KiB/256 KiB buffer defaults are right. That is PS-E's, and the
   defaults in `CaptureRecorder` should be treated as **unvalidated** until it
   measures them.
10. **The read-only pin is a static AST scan**, like PS-A's. It proves no
    identifier or import in these two files names a publisher, a control
    manager or a vendor SDK. It does not prove the process cannot open a
    socket. The stronger guarantee remains the measured one: `unitree_sdk2py`
    is absent from the venv, and this card installed nothing.
11. **`source="hardware"` proves the envelopes said `PHYSICAL`, nothing more.**
    It is a declaration by whoever constructed the recorder, propagated
    faithfully. It is not evidence that a robot existed. That is PS-D's
    attestation, and when its digest is absent this sidecar says so in
    `does_not_prove`.
12. **Mount geometry is validated for shape, not for truth.** The sidecar
    refuses an extrinsic with no method or no uncertainty; it cannot tell a
    careful tape measurement from a plausible-looking invention. Only PS-F's
    sheet, filled while the rig is assembled, does that.

---

## CI_GATE

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T09:38:48Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.50s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.38s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.32s
[  PASS] HARD  default-suite              4491 passed, 9 skipped, 36 deselected, 5 warnings in 191.73s (0:03:11)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 203.6s
```

`ruff  7 violation(s), baseline 7, new 0` — this card added **zero** new
`(file, rule)` fingerprints to the ratchet. `frozen-digest-sentinels` and
`hard-safety` green confirm no MUST-NOT-TOUCH surface moved.

**Caveat the auditor should weigh:** the `default-suite` figure (4491) is the
whole tree at 09:38Z, which includes the parallel PS-A/PS-C/PS-D/PS-E cards'
files as they stood at that moment. It is honest evidence that PS-B is green
*in* that tree; it is not evidence about anyone else's card, and a re-run after
the tranche settles is the one that counts.

---

## Card-required closing command

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_sidecar.py -q
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 0.39s
```
