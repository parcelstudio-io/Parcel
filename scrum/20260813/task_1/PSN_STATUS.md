# PS-N — the preflight half of the ingest hole, and what the plausibility layer missed

**Card:** PS-N (FIX tranche PS-3) · **Date:** 2026-08-13 · **Executor:** Opus 5
**Owns:** `scripts/parcel_capture/preflight.py`, `scripts/parcel_capture/ingest/**`,
`tests/test_capture_preflight.py`, `tests/test_capture_ingest.py`

**The one sentence:** preflight — the tool whose whole job is to prove a channel is
live before the session — could not reach a single channel, and told the operator
to use a flag that did not exist; it can now, and both halves are pinned by tests
that fail against the old code.

---

## Per-finding table

| # | Finding | Reproduced | Fixed | Regression test | Fails on old code |
|---|---|---|---|---|---|
| 1a | `run_preflight`/`probe_all_channels` default to `unavailable_reader_factory`; `main()` passes no factory | yes — §1.1 | `default_reader_factory` (composite: live adapter where one serves and could run, `unavailable_reader_factory` otherwise); both defaults changed; `main()` passes explicitly | `test_main_with_default_args_reaches_the_live_ingest_factory`, `test_the_two_probe_entry_points_default_to_the_live_factory`, `test_the_default_factory_reaches_the_real_adapter_when_its_dependency_is_there`, `test_the_default_factory_keeps_the_transport_remedy_for_channels_no_adapter_serves`, `test_the_default_factory_falls_back_when_the_dependency_is_missing_here` | **M1** — 2 failed |
| 1b | refusal at `preflight.py:2323-2327` names `--reader-module`, which does not exist | yes — §1.2 | `--reader-module MODULE:FACTORY` and `--reader {auto,none}` added via `add_reader_arguments()`; message rewritten to name only real flags | `test_every_flag_a_preflight_refusal_names_is_a_real_flag` (structural scan of every refusal string in a full run), `test_seeded_failure_the_flag_scan_catches_a_reintroduced_phantom_flag`, `test_the_reader_flags_parse_and_select_what_they_say`, 7 × `test_a_reader_module_spec_that_does_not_resolve_is_a_refusal_never_a_default`, `test_main_refuses_a_bad_reader_module_without_a_traceback`, `test_the_reader_module_flag_actually_drives_the_probe_end_to_end` | **M2** — 1 failed |
| 1c | *(found while fixing 1a)* `python -m scripts.parcel_capture.preflight` loads this module **twice**, so every receipt a live reader produces is rejected as `PROBE_CONTRACT_VIOLATION` | yes — §1.4 | `sys.modules.setdefault(_CANONICAL_MODULE, sys.modules[__name__])` in the `__main__` guard | `test_the_m_entry_point_does_not_load_this_module_twice` (subprocess, real `-m` entry point) | **M7** — 1 failed |
| 2 | `classify_channel(go2.sportmodestate) == ()` while its decoder emits `ImuSample` + `FootForceSample` | yes — §2.1 | `_SPORTMODESTATE_TYPE_TOKEN` → `(IMU, FOOT_FORCE)`; **not** POWER (see §2.2) | `test_sport_mode_state_has_imu_and_foot_force_rules_and_its_samples_are_assessed`, `test_the_lf_sport_mode_state_mirror_gets_the_same_rules` | **M3** — 4 failed |
| 2b | *(consequence of the naive fix)* `SportModeState`'s IMU becomes a spurious **fifth** IMU witness | yes — §2.3 | `imu_unit_id` resolves a `SportModeState` row to the device's `LowState` frame, derived from the matrix | `test_sport_mode_states_imu_is_the_body_imu_and_not_a_fifth_witness` | **M4** — 2 failed |
| 2c | the class of bug must be impossible to reintroduce | — | `ingest.decoder_for_channel()` (single dispatch per adapter, no second table) + a structural pin | `test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set` (all 28 rows, 23 with decoders), `test_seeded_failure_the_structural_pin_catches_a_decoder_whose_rules_were_removed`, `test_every_decoder_dispatch_is_reached_and_refuses_outside_its_own_channels` | **M3** — the pin is in M3's kill set |
| 3a | 202/743 (27.2 %) of the three live adapters had never executed | yes — §3.1, reproduced at **205/743 (27.6 %)** | 40 new tests incl. read-only doubles for `rclpy`, `pyrealsense2`, `unilidar_sdk2` | (the whole G8 block) | n/a — coverage, not behaviour |
| 3b | the status docs claimed the decoders were exercised | yes — §3.4 | corrected here, with the measured numbers and the residual | — | — |
| **X1** | *(my own, audit item "RealSense pipeline unconfigured" — REFUTED by the panel, but true)* `read_frames` called `handle.start()` with no `rs.config`, so **`d455.gyro` read 935 colour frames and reported PRESENT** | yes — §4.1, executed | `stream_selection()` builds an `rs.config` naming this channel's stream + index; `attributable()` discards any frame that did not decode as that stream | `test_the_pipeline_is_started_against_a_config_naming_this_channels_stream`, `test_seeded_failure_a_pipeline_that_ignores_the_config_reads_absent_not_present`, `test_a_build_that_cannot_select_a_stream_is_a_named_refusal_not_a_default_profile` | **M5** — 2 failed |
| **X2** | *(my own, audit item "L2 reader uninitialised" — REFUTED, but the absence is unnamed)* an un-attached `UnitreeLidarReader()` is indistinguishable from a dead L2 on the CRITICAL `l2.cloud` | yes — §4.2 | `require_attached()` consults `checkInit()` and refuses with the state named and a command attached. **Does not** call `initialize()` — see does_not_prove | `test_an_unattached_l2_reader_is_a_named_refusal_not_an_anonymous_silence`, `test_a_build_with_no_checkinit_refuses_rather_than_assuming_it_is_attached`, `test_a_checkinit_that_raises_is_absent_and_points_at_the_network_first`, `test_an_attached_l2_still_reads_and_the_check_is_not_a_new_wall` | **M6** — 3 failed |
| **X3** | *(audit item "DDS QoS wrong" — REFUTED)* | **not changed** | — | — | see does_not_prove |

---

## 1. Finding 1 — the preflight half of the ingest fix

### 1.1 Reproduction: `main()` names no factory, the defaults refuse everything

```
$ grep -n "reader_factory" scripts/parcel_capture/preflight.py   # at base
2301:def unavailable_reader_factory(entry: Channel) -> ChannelReader:
2407:    reader_factory: ChannelReaderFactory = unavailable_reader_factory,   # probe_all_channels
3283:    reader_factory: ChannelReaderFactory = unavailable_reader_factory,   # run_preflight
3329:        reader_factory=reader_factory,
```

`main()` (`:3936-3954`) called `run_preflight(window_s=…, configured_rates=…,
storage_path=…, builtin_lidar_operator=…, rest_period=…)` — **no
`reader_factory` argument at all**. So on an Orin with `rclpy` sourced and the dog
publishing, `unavailable_reader_factory`'s NOT_ATTEMPTED branch fires for every
DDS channel: *"rclpy is importable but this build ships no live reader"*.

### 1.2 Reproduction: the flag the refusal names does not exist

```
$ .parcel/bin/python -m scripts.parcel_capture.preflight --window 0.05
...
  [    note] CHANNEL_ABSENT: mic.xvf3800 (opportunistic, matrix says awaiting_hardware) is ABSENT:
  not_attempted — mic.xvf3800: sounddevice is importable but this build ships no live usb_audio
  reader; supply one via --reader-module or the reader_factory argument ...

$ .parcel/bin/python -m scripts.parcel_capture.preflight --reader-module foo
python -m scripts.parcel_capture.preflight: error: unrecognized arguments: --reader-module foo
```

### 1.3 The fix

* `default_reader_factory(entry)` — live adapter when one **serves** the channel
  **and** its dependency is satisfied; otherwise `unavailable_reader_factory`.
  The fallback is deliberate and is *not* a downgrade: `"tegrastats is not on
  PATH, this host is not a Jetson"` and the `Do NOT pip install the vendor SDK
  into .parcel/` warning are more actionable than anything the adapter registry
  could say, and both are preserved (pinned by two tests).
* `--reader-module MODULE:FACTORY` (import + `getattr` + callable check, four
  distinct refusals, no fallback) and `--reader {auto,none}` — mutually exclusive.
* Added by `add_reader_arguments()` in `main()` only, **not** in the shared
  `build_arg_parser()`: that parser is also `attest.py`'s, which does not resolve
  these flags and is not this card's file. Advertising a flag a command ignores is
  the same defect one step along. The refusal text names the command the flag
  belongs to (`READER_MODULE_FLAG_HELP`).

Dev-box posture unchanged — fail closed:

```
$ .parcel/bin/python -m scripts.parcel_capture.preflight --window 0.02 ; echo EXIT=$?
  present=0 degraded=0 absent=28
RESULT: NOT READY — 6 blocking finding(s). See .../STAGE0_RUN_SHEET.md §6 (DEGRADE-MMP).
EXIT=1
grep -c Traceback  -> 0 (stdout), 0 (stderr)
```

### 1.4 The defect my own fix introduced, caught by running it

The first time a reader actually delivered a receipt through the `-m` entry point:

```
$ PYTHONPATH=$SCRATCH .parcel/bin/python -m scripts.parcel_capture.preflight \
      --reader-module ps_n_demo_reader:factory --window 0.3
  [ABSENT  ] go2.sportmodestate  - not_applicable (critical) plausibility=UNKNOWN
      why: probe_contract_violation — go2.sportmodestate: reader yielded SampleReceipt,
           not a SampleReceipt
```

`python -m scripts.parcel_capture.preflight` runs the file as `__main__`; the
ingest package then imports `..preflight` **by name** and gets a second module
object with a different `SampleReceipt` class. On the Orin this would have turned
all 23 served channels ABSENT for a reason naming our own code. Fixed by aliasing
the running module under its canonical name in the `__main__` guard. After:

```
  [PRESENT ] go2.sportmodestate  50.00Hz nominal  (critical) plausibility=UNKNOWN
      15 message(s) received on dds 'sportmodestate'; first 176 B
  [UNKNOWN] go2.sportmodestate   15 sample(s), classes imu, foot_force
      PASS imu.accel_finite / imu.accel_within_sensor_range / imu.accel_magnitude_at_rest …
```

That last block is both fixes visible at once: the channel is reachable, and its
samples now reach rules.

---

## 2. Finding 2 — SportModeState's measurements reached no rule

### 2.1 Reproduction

```
$ .parcel/bin/python scratchpad/repro_f2.py
channel: go2.sportmodestate criticality: critical
message_type: unitree_go/msg/dds_/SportModeState_
classify_channel -> ()
decode_sport_mode_state emits: ['ImuSample', 'FootForceSample']
receipts: 10 measurements on first: ['ImuSample']
verdict: PlausibilityVerdict.UNKNOWN classes: () samples_assessed: 0
```

### 2.2 Why `(IMU, FOOT_FORCE)` and not `(IMU, POWER, FOOT_FORCE)`

`SportModeState` carries no `power_v` and no `BmsState`, and its decoder emits no
`PowerSample`. A POWER rule with no measurement behind it reports
`power.no_measurement → UNKNOWN`, and UNKNOWN never decays into PASS — so adding
it would have parked a CRITICAL channel at UNKNOWN for the whole session. The
rule set is exactly what the decoder feeds.

### 2.3 The trap in the obvious fix

`imu_unit_id` grouped by `(device, frame_id)`. `go2.sportmodestate`'s `frame_id`
is `odom` — the frame of the **pose** it reports — while the `imu_state` inside it
is the dog's **body IMU**, the same physical sensor `LowState` carries at
`base_link`. The naive fix therefore mints a fifth "independent witness" out of
the fourth, and the four-IMU cross-check starts comparing a sensor against itself.
`imu_unit_id` now resolves a `SportModeState` row to the `LowState` frame on the
same device, **looked up from PS-A's table** rather than written down here; if the
table ever stops naming exactly one such frame it falls back to the row's own
frame and the extra unit appears in the report rather than being papered over.
`test_sport_mode_states_imu_is_the_body_imu_and_not_a_fifth_witness` asserts both
the fix and that the naive grouping really would have produced five.

### 2.4 The structural pin

`ingest.decoder_for_channel(entry)` routes to the one dispatch each adapter owns
(`dds.decoder_for`, `l2.decoder_for`, `realsense.decoder_for` — the last two are
new; `frame_from_l2`/`frame_from_realsense` now go through them, so there is one
dispatch per transport and no fourth table).
`test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set` then, for
**every** row of the matrix, runs the decoder the live adapter would run against a
fully-populated synthetic message, collects the `PhysicalSample` types that come
out, and requires `classify_channel` to name the rule set that consumes each.
23 of 28 rows are checked; the other 5 have no live adapter and G6 already states
why. A decoder with no fixture fails the pin rather than being skipped.

---

## 3. Finding 3 — coverage, measured

### 3.1 The audit's number, reproduced

No `coverage` package exists in `.parcel/` (`pip list` has no `coverage`), so line
coverage was measured with a 90-line stdlib tracer
(`sys.settrace` for executed lines; executable lines from `co_lines()` walked
recursively through `co_consts` — the same definition `coverage.py` uses). It
independently agrees with the audit on the denominator:

| measurement | executable | covered | never executed |
|---|---|---|---|
| audit's claim | 743 | 541 | **202 (27.2 %)** |
| my reproduction, 4 capture test files, pre-fix sources | **743** | 538 | **205 (27.6 %)** |

### 3.2 After

| file | before | after |
|---|---|---|
| `ingest/dds.py` | 369/462 (79.9 %) | **462/462 (100 %)** |
| `ingest/l2.py` | 79/145 (54.5 %) | **171/171 (100 %)** |
| `ingest/realsense.py` | 90/136 (66.2 %) | **172/172 (100 %)** |
| **total** | **538/743 (72.4 %)** | **805/805 (100 %)** |

(The denominator grew from 743 to 805 because the X1/X2 fixes added code.)
Command, both times:

```
LINECOV_OUT=… .parcel/bin/python scratchpad/linecov.py \
  scripts/parcel_capture/ingest/dds.py,scripts/parcel_capture/ingest/l2.py,\
scripts/parcel_capture/ingest/realsense.py -- \
  tests/test_capture_ingest.py tests/test_capture_preflight.py \
  tests/test_capture_rehearsal.py tests/test_capture_sidecar.py \
  tests/test_capture_envelope.py -q
→ LINECOV {"executable": 805, "covered": 805, "pct": 100.0, "pytest_rc": 0}
```

### 3.3 How, and what it is worth

Three read-only doubles installed with `monkeypatch.setitem(sys.modules, …)` —
`rclpy` (+`unitree_go.msg`), `pyrealsense2`, `unilidar_sdk2`. Each ships the
command surface it really has (`create_publisher`, `hardware_reset`, `startLidar`)
and each of those raises `AssertionError` if reached; none is reached. Nothing is
installed into `.parcel/` — `pip list` is unchanged, and
`test_a_full_preflight_run_never_imports_a_vendor_sdk` still passes
(`VENDOR []` in a fresh subprocess).

That reaches: `open_session`/`open_reader`/`open_pipeline`, the subscribe, the
spin loop, `_SubscribeOnlySession`'s sealed calls, `_message_class` (both
refusals), the three read loops, all nine decoders, every `missing_fields`
branch, every unusable-cloud branch, the `MAX_RANGE_SAMPLES` cap, and the three
"module vanished between the probe and the open" arms.

### 3.4 The residual, plainly

**Zero executable lines in the three adapters will first execute on the dog.**
That is a true statement about *lines* and a misleading one about *risk*, so:
what has never executed is the **vendor libraries behind those lines**. Every
call below is exercised only against a double written from documentation about
somebody else's Go2, and each is a place tomorrow can still surprise us:

* `rclpy.spin_once` actually delivering — including **QoS matching** (X3 below);
* whether the `unitree_ros2` overlay's generated types match `_message_class`'s
  derived names (`unitree_go/msg/dds_/LowState_` → `unitree_go/msg/LowState`);
* `rs.config().enable_stream(stream, index)` selecting the profile we asked for on
  this D455 + this `pyrealsense2` build, and whether UVC per-frame metadata
  survives the pip wheel;
* `UnitreeLidarReader().checkInit()` existing and meaning what we assume;
* every field name in every decoder — 100 % coverage of `read_field` calls proves
  the *fallback* works, not that the field is spelled that way on our unit.

The first 45 minutes of the session is what replaces each of these with a
measurement.

### 3.5 The status-doc claim, corrected

`PSG_STATUS.md`'s does_not_prove was **right** that "not one line of the live
transport code has ever executed" — credit where it is due. The claim beside it,
that the decoders "are correct against synthetic messages", was the overstated
one: true for the DDS decoders (79.9 %), but `l2.py` was at 54.5 % and
`realsense.py` at 66.2 %, and `frame_from_l2` had **never been called for either
L2 channel** while `frame_from_realsense` had never been called for any of the six
D455 rows.

A dated **PS-N addendum** has been appended to `PSG_STATUS.md` with the per-file
table, the method, and the two behaviour changes (X1, X2). Nothing in that
document was deleted — the board's rule is to supersede visibly.

In the code: every `# pragma: no cover` marker on a line that now executes is
gone (9 in `dds.py`, 1 in `l2.py`, 4 in `realsense.py`), and the `read_frames`
docstrings that said "UNEXECUTED here" now say what is true instead — that the
loop runs against a double, and that what the double cannot tell us is whether
the vendor library delivers.

---

## 4. Three refuted audit items, re-examined with my own executed evidence

### 4.1 X1 — RealSense: REFUTED by the panel, and true

```
$ .parcel/bin/python scratchpad/repro_rs.py
start() called with: [()]   <- no rs.config: DEFAULT profile
frames yielded on d455.gyro: 1094
measurements on the first frame: ()  <- no ImuSample
payload: {"...","message":"realsense/gyro","missing_fields":["motion_data"],...}

preflight verdict for the D455 GYROSCOPE: present messages_received= 935
plausibility: unknown
```

`STREAM_PROFILES` was declared and used only for a membership check.
`pipeline.start()` with no config runs librealsense's default profile (depth +
colour), so all six D455 rows were the same stream wearing six names, and
**preflight reported the gyroscope PRESENT on the strength of colour pixels** —
a fail-**open** in the go/no-go tool. Fixed at the source (`stream_selection`,
using `read_field` for every vendor reach so an unfamiliar build is a named
refusal) and behind it (`attributable()`: a frame that did not decode as this
channel's stream is discarded, so a config that silently did not take reads
ABSENT — which is the correct answer). `enable_stream` sets **stream and index
only**; resolution and rate are PS-E's budget decision and the matrix marks these
rows CONFIGURED with no nominal rate, so librealsense picks the profile rather
than this module inventing numbers nobody chose.

### 4.2 X2 — L2: REFUTED by the panel; fail-closed, but the absence had no name

`UnitreeLidarReader()` constructs a reader; it does not open the socket. The
allowlist named `checkInit` and `initialize` and the adapter called neither, so
every getter returned nothing and `l2.cloud` — CRITICAL — came back
`NO_MESSAGE: the reader finished early having yielded nothing`: the same words
preflight prints for an L2 that is unplugged. `require_attached()` now consults
`checkInit()` and refuses with the state named, the reason *this adapter does not
attach* stated, and the vendor-ROS-2-node command attached (plus the
192.168.1.2 / 192.168.1.7 NIC collision, which is where it actually bites). It
still does **not** call `initialize()` — see does_not_prove.

### 4.3 X3 — DDS QoS: REFUTED, and **not changed**

`session.subscribe(cls, topic, sink, depth)` passes an `int`, which `rclpy`
expands to a `QoSProfile` with the **RELIABLE** default; a BEST_EFFORT publisher
would then deliver zero messages with no error. I could not produce **executed**
evidence for or against this without `rclpy` and a publisher, and the card is
explicit that the refuted items are not to be rewritten on the audit's say-so.
Changing QoS the night before, on the strength of documentation alone, is the
riskier act. **Left as is, and named in does_not_prove as the highest-value thing
to check in the first ten minutes on the Orin.**

---

## 5. Seeded-failure table (mutation harness)

`scratchpad/mutate.py`: each mutant is one revert of one fix; `-B`,
`PYTHONDONTWRITEBYTECODE=1`, explicit `__pycache__` purge, restore verified by
sha256 after every mutant.

| mutant | what it reverts | tests | result | restored byte-identically |
|---|---|---|---|---|
| M1 | both `reader_factory` defaults + `main()`'s explicit pass | 2 | **2 failed** | yes |
| M2 | phantom `--reader-module` wording restored, flag removed | 1 | **1 failed** | yes |
| M3 | `classify_channel`'s SportModeState branch | 4 | **4 failed** | yes |
| M4 | `imu_unit_id`'s body-IMU resolution | 2 | **2 failed** | yes |
| M5 | `handle.start(config)` → `handle.start()`, attribution gate removed | 2 | **2 failed** | yes |
| M6 | `require_attached` call removed | 3 | **3 failed** | yes |
| M7 | the `__main__` module alias removed | 1 | **1 failed** | yes |

Final run (after the docstring/pragma edits of §3.5, so these are the shas of the
files as they stand):

```
baseline sha256 l2.py         = 4bdbfd58173620869746d7f2231ca03f2e13398b207fb33d1b3930833adc31e0
baseline sha256 preflight.py  = c3e01ad4de09a8e6dcd4444a72a6276566081b6a5dc31468f062c358514f2601
baseline sha256 realsense.py  = bfee4a648b25ee2cdf88f711732aa47a7d750463a701a854f985c977a8f95460
final    sha256 l2.py         = 4bdbfd58173620869746d7f2231ca03f2e13398b207fb33d1b3930833adc31e0  identical=True
final    sha256 preflight.py  = c3e01ad4de09a8e6dcd4444a72a6276566081b6a5dc31468f062c358514f2601  identical=True
final    sha256 realsense.py  = bfee4a648b25ee2cdf88f711732aa47a7d750463a701a854f985c977a8f95460  identical=True
```

(The three files are untracked in git — `git status` reports `?? scripts/parcel_capture/` —
so `git diff` cannot witness the restore; sha256 is the check.)

---

## 6. Tests

```
$ .parcel/bin/python -m pytest tests/test_capture_ingest.py tests/test_capture_preflight.py \
    tests/test_capture_rehearsal.py tests/test_capture_sidecar.py tests/test_capture_envelope.py \
    tests/test_no_arm_pin.py tests/test_clockmap.py tests/test_rosbag2_sidecar.py \
    tests/test_bandwidth_budget_doc.py -q
860 passed in 33.34s          (final run, after every edit in this document)

$ .parcel/bin/python -m ruff check scripts/parcel_capture/ tests/test_capture_preflight.py \
    tests/test_capture_ingest.py
All checks passed!
```

### ci_gate

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T14:15:04Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 | …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        …
[  PASS] HARD  follow-bench-jerk-ratchet  …
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.53s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.36s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.25s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.37s
[  PASS] HARD  default-suite              5071 passed, 9 skipped, 36 deselected, 5 warnings in 220.86s
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 232.7s
```

Run **before** the §3.5 docstring/pragma edits and the `PSG_STATUS.md` addendum;
the capture suite was re-run green after those (below), and neither touches
behaviour.

**Tests added:** 21 in `tests/test_capture_preflight.py` (GATE 26–27), 40 in
`tests/test_capture_ingest.py` (G7, G8, G8b, G8c).

**Three tests I did not add but had to repair.** A parallel card (PS-O) rewrote
`ingest/base.py` and `ingest/dds.py` under me at 09:30–09:31 — `ReadOnlyHandle`
became a closure-built class and `_SubscribeOnlySession` stopped holding the node
at all — which left three cells in `tests/test_capture_ingest.py` (my file) red.
I updated them to the new surface **without weakening the property**:
`VETTED_DYNAMIC_REACHES` (later deleted wholesale by PS-O in favour of
delegation), the facade test (now pins **both** refusal branches instead of one),
and the session test (now asserts *no* attribute yields the node or the module,
which is strictly stronger than the old "the slot is name-mangled").

---

## does_not_prove

1. **Nothing here was measured against hardware.** Every live branch is exercised
   against a test double written from documentation about other Go2 EDUs. 100 %
   line coverage of the three adapters proves the *code* runs and its contracts
   hold; it proves nothing about `rclpy`, `pyrealsense2` or `unilidar_sdk2`.
2. **The DDS QoS question is open and I did not touch it.** An `int` queue depth
   is a RELIABLE subscriber. If any Unitree topic publishes BEST_EFFORT, preflight
   will report it ABSENT with a perfectly plausible "nothing had been received"
   and the topic will be live. This is the single highest-value thing to check in
   the first ten minutes on the Orin: `ros2 topic info -v /lowstate` and compare
   the publisher's reliability against the subscriber's. If they differ, the fix
   is one `QoSProfile` in `DdsIngest.__init__`.
3. **The L2 is still not attached by this adapter.** `require_attached()` makes
   the state *legible*; it does not make the L2 readable. `initialize()`'s
   signature is unverified against our unit and I refused to guess it. Take the
   L2's presence from the vendor ROS 2 node's topics tomorrow, not from this
   preflight row.
4. **`rs.config().enable_stream(stream)` and `enable_stream(stream, index)` are
   the documented overloads, not measured ones.** If this `pyrealsense2` build
   rejects them, `stream_selection` raises `IngestUnavailableError` and the D455
   rows read ABSENT — fail closed, but a session-morning surprise.
   `attributable()` is the belt behind that brace.
5. **`--reader-module` is a preflight flag only.** `attest.py` shares
   `build_arg_parser` but does not resolve reader flags, so it gets the corrected
   *default* (the live factory) and no override. Wiring attest's CLI is one line
   in a file this card does not own.
6. **The structural decoder/rule pin is one-directional.** It catches a decoder
   that emits samples into a channel with no rules. It does **not** catch the
   converse: `go2.front_camera` and the four D455 video rows carry
   `ChannelClass.CAMERA` and their decoders emit **no `ImageSample`**, so the
   lens-cap rule (`camera.non_degenerate`) can never fire on the live path and
   those channels will report `camera.no_measurement → UNKNOWN` all session.
   That is fail-closed and visible, and it is a real gap in the plausibility
   layer that no card currently owns.
7. **Coverage was measured in-process.** `tests/test_no_arm_pin.py` also executes
   these adapters in subprocesses against its own fake SDKs; that contribution is
   invisible to my tracer and is not counted in any number above. My numbers are
   therefore a lower bound on what the suite executes, and the pre-fix baseline
   (205/743) is measured the same way as the after (0/805), so the comparison is
   like-for-like.
8. **The repo was being edited by other cards throughout.** `ingest/base.py`,
   `ingest/dds.py`, `tests/test_capture_ingest.py`, `budget.py`, `rosbag2.py` and
   `tests/test_no_arm_pin.py` all changed under me during this card. Every number
   above was measured against the tree as it stood at the time stated; the final
   test run and `ci_gate` are the only claims about the tree as it stands now.
9. **`--reader none` is a dependency census, not a probe**, and reports nothing
   about presence. It exists so the old behaviour remains reachable deliberately
   rather than by accident.
