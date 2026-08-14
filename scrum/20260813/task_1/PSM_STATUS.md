# PS-M — make the primary recorder actually work

**Card:** PS-M (FIX tranche PS-3) · **Date:** 2026-08-13 · **Owner of record:** Opus
**OWNS:** `scripts/parcel_capture/rosbag2.py`, `tests/test_rosbag2_sidecar.py`
**Nothing else was written.** `git status --porcelain -- scripts/parcel_capture
tests/test_rosbag2_sidecar.py` → `?? scripts/parcel_capture/` ·
`?? tests/test_rosbag2_sidecar.py` (both still untracked from PS-G; no tracked
file moved).

---

## 0 · Headline

Both assigned findings reproduced against **real bytes from the real writer**,
not against my reading of the spec. Then, re-checking the argv, I found a
**third defect of the same severity**: the command line the operator was going
to type carries three flags that **do not exist in Humble's recorder**, where
argparse exits 2 and records nothing. All three are fixed, each with a
regression test proven to fail against the shipped code.

The decisive tool was already in the repo and unused for this: the ROS 2 Jazzy
sandbox at `.cache/external-evals/runtime/ros-jazzy-base-sandbox`, which carries
`librosbag2_storage_mcap.so` and `libmcap.so` (PSK M8). Running
`rosbag2_py.SequentialWriter` inside it — **no node, no publisher, `--unshare-net`,
nothing installed** — produces genuine rosbag2 MCAP bags and genuinely exercises
the storage plugin's config parser. Everything below marked MEASURED comes from
there or from `ros2/rosbag2`'s own source.

| # | Finding | Reproduced | Fixed | Regression test | Fails on old code |
|---|---|---|---|---|---|
| **F1** | `Chunk.records` read as uint32; MCAP says uint64 ⇒ every uncompressed chunked bag = CORRUPT/0 msgs | **YES** — real libmcap 1.3.1 bag: `termination=corrupt, counts={}` | `_Cursor.blob64()`, `_decode_chunk`, `write_fixture_bag` | `test_a_chunk_records_length_prefix_is_read_as_uint64_not_uint32`, `test_a_chunked_bag_written_by_the_real_libmcap_writer_reads_back_clean`, `test_our_fixture_writer_frames_chunk_records_the_way_libmcap_does` | **YES** — 4 fail under revert F1 |
| **F2** | `compression: ""` / `compressionLevel: ""` ⇒ plugin refuses, `ros2 bag record` exits 1, **zero bytes** | **YES** — real plugin: `yaml-cpp: error at line 12, column 14: Failed to convert field 'compression'`, both profiles | `"None"`/`"Default"` + `validate_writer_options()` fail-closed | `test_no_writer_option_is_ever_an_empty_enum_string`, `test_an_invalid_enum_value_is_refused_before_it_can_reach_a_file` | **YES** — 2 fail under revert F2 |
| **F3 (new, mine)** | argv carried `--topics`, `--disable-keyboard-controls`, `--node-name`; **Humble's recorder has none of them** ⇒ argparse exit 2, zero bytes | **YES** — `ros2/rosbag2` `humble` + tags 0.15.13/0.15.14/0.15.16 `record.py`: topics is positional, no keyboard flag | `RosDistro` gate (default HUMBLE = the intersection argv), `validate_argv_against_help()` | `test_the_humble_argv_carries_no_flag_humbles_recorder_does_not_have`, `test_the_jazzy_argv_is_refused_against_humbles_recorder`, `test_the_cli_can_clear_the_argv_against_a_saved_help_file`, `test_the_split_thresholds_are_explicit_even_when_they_are_zero` | **YES** — 3 fail under revert F3 |

---

## 1 · F1 — the uint32/uint64 chunk length

### 1.1 Reproduction, on bytes we did not write

A real rosbag2 bag, written inside the Jazzy sandbox by
`rosbag2_py.SequentialWriter` → `librosbag2_storage_mcap.so` → `libmcap 1.3.1`,
with **no storage config at all** (i.e. exactly what the module's own documented
fallback tells the operator to do when the config is rejected):

```text
$ jazzy.sh 'python3 write_bag.py - /work/bag_default 40'
WROTE OK
-rw-rw-r-- 1 ubuntu ubuntu 5116 bag_default_0.mcap

$ .parcel/bin/python -c "...read_rosbag2_mcap('bag_default_0.mcap')..."
profile = "ros2"
library = "libmcap 1.3.1"
termination = "corrupt"
detail = "record opcode 0x06 at offset 549: field chunk.record.body wants 1301425422336 bytes, 2353 remain"
counts = {}
count_basis = "walked_messages"
chunk_compressions = ["none"]
channels = []
```

A healthy 40-message recording, read as **corrupt with zero channels**.

### 1.2 The width, proven from the file's own arithmetic

```text
record at 549: opcode=0x06 length=2402
chunk fields:
  message_start_time = 1000000000
  message_end_time   = 1078000000
  uncompressed_size  = 2362
  uncompressed_crc   = 0
  compression        = b'' (len 0)
  records length prefix at offset 590: raw bytes = 3a 09 00 00 00 00 00 00
     read as uint32 -> 2362
     read as uint64 -> 2362
  chunk content length declared by record header = 2402 ; 32 + len(compression) + 8 + records = 2402
  wrong start parses as opcode=0x00 length=1301425422336
  right start parses as opcode=0x03 length=303
```

`2402 = 32 + 0 + **8** + 2362`. A uint32 prefix would balance at 2398. The
width is not a matter of opinion about the spec; it is arithmetic in the file.
Four bytes early, the first inner record's opcode reads `0x00` and its length
`1301425422336` — the observed failure exactly.

### 1.3 What the operator would have been told

Not merely "corrupt". The sidecar refuses to exist:

```text
# runtime-patched reader back to uint32; no file touched
SIDECAR REFUSED: SidecarRefusedError: .../take_real carries no topic that maps
to a channel of the matrix (saw []); a bag with no known channel is a finding,
not a manifest
```

After the fix, the same bag, same call:

```text
termination: {"kind": "clean", "detail": "every file carries a complete MCAP terminal
structure (1 file(s))", ... "messages_recovered": 40 ...}
channel go2.lowstate: {"verdict": "present", "reason": "within_tolerance: 40 of 39
expected message(s) over 0.078s", "messages": 40, "observed_rate_hz": 512.82 ...}
```

### 1.4 The full width audit — every field, against a real bag

One wrong width was reason to check them all. The audit is now a table in the
module (`MCAP_INTEGER_WIDTHS`, pinned by a test) and, more usefully, it was
**executed**: the fixed reader walks a real bag record-by-record from the
leading magic to the trailing magic with **zero bytes left over**, and every
record type a real rosbag2 file contains appears in it:

```text
Statistics record decoded -> {1: 40}
  message_count=40 schema_count=1 channel_count=1 attach=0 meta=2 chunk=1
  start=1000000000 end=1078000000
Footer: summary_start=4359 summary_offset_start=4981 summary_crc=345576070 (content 20 bytes)
trailing magic ok: True | bytes after: 0
record opcodes present: {'0x1': 1, '0x2': 1, '0x3': 1, '0x4': 1, '0x6': 1, '0x7': 1,
                         '0x8': 1, '0xb': 1, '0xc': 2, '0xd': 2, '0xe': 5, '0xf': 1}
```

Every one of those numbers is independently checkable (`schema_count=1`,
`chunk_count=1`, `meta=2` = the two `0x0C` Metadata records rosbag2 writes,
Footer content = 8+8+4 = 20 bytes). A wrong width anywhere in Header, Schema,
Channel, Message, Chunk or Statistics turns them into garbage or throws.

**Result: exactly one width was wrong** — `Chunk.records`, the spec's only
uint64-prefixed byte array. `Schema.data`, `Channel.metadata` and
`Statistics.channel_message_counts` are uint32-prefixed and were already right;
`Statistics.schema_count` is uint16 among uint32 neighbours and was already
right; the uint8/uint64 record framing was already right; the magic is 8 bytes
at both ends and was already right.

Records this reader does **not** decode (ChunkIndex, MessageIndex, Attachment,
AttachmentIndex, Metadata, MetadataIndex, SummaryOffset) are skipped by the
generic record framing, which is now proven correct by the zero-leftover walk.
Their internal widths are documented in `MCAP_INTEGER_WIDTHS` where they matter
and are **not** exercised — see `does_not_prove`.

### 1.5 Why the shipped suite was green

`write_fixture_bag(chunked=True)` wrote the same uint32 prefix the reader read.
Broken writer plus broken reader agreed, and
`test_a_chunked_bag_is_walked_and_a_compressed_one_falls_back_and_says_so`
passed. Measured: under the **fully shipped** state (revert
`F1-reader-and-fixture-uint32`) that old test still passes and only the new
tests fail. That is why the new witness is (a) a bag hand-assembled from the
spec tables inside the test and (b) 5148 bytes written by `libmcap 1.3.1`,
embedded zlib+base64 in the test file, sha256
`cf32e5ff86be4475c0433118b8c78b860baaf8a0ebaff815b6dbdbc39fd0cafa` — bytes no
module of ours produced.

The compressed path masked the bug too: with a non-empty `compression` the
shifted blob is never parsed, so the zstd fixture read "clean" and the defect
only ever showed on the uncompressed chunks that are the crash-safe profile's
entire point.

---

## 2 · F2 — the empty-string enums

### 2.1 Reproduction against the real plugin

The exact bytes `storage_config_yaml()` emitted, both profiles, handed to a real
MCAP writer:

```text
$ jazzy.sh 'python3 try_open.py crash_safe.yaml /work/bag_crashsafe'
[ERROR] [rosbag2_storage]: Could not open '/work/bag_crashsafe/bag_crashsafe_0' with 'mcap'.
        Error: yaml-cpp: error at line 12, column 14: Failed to convert field 'compression'
[ERROR] [rosbag2_storage]: Could not load/open plugin with storage id 'mcap'
OPEN FAILED: RuntimeError: No storage could be initialized. Abort
EXIT=1
--- (indexed.yaml: byte-identical failure, line 12 column 14) ---
```

Line 12 column 14 is `compression: ""`. This is the recorder of record for the
whole session, exiting 1 with zero bytes written, on both profiles.

### 2.2 The allowed value sets, measured rather than assumed

```text
$ strings -n 3 librosbag2_storage_mcap.so | grep -E "^(None|Lz4|Zstd|Fast|Fastest|Slow|Slowest|Default)$"
None / Lz4 / Zstd            (the YAML::convert<mcap::Compression> table)
Fastest / Fast / Default / Slow / Slowest   (YAML::convert<mcap::CompressionLevel>)
```

and each candidate actually opened:

| storage config | real plugin |
|---|---|
| `compression: "None"`, `compressionLevel: "Default"` | **OPEN OK** |
| `compression: "None"` alone | OPEN OK |
| both keys omitted | OPEN OK (default measured **chunked, uncompressed**) |
| `compression: "none"` (lower case) | **OPEN FAILED** — case-sensitive |
| `compression: "Zstd"`, `compressionLevel: "Fast"` (the TONIGHT_CHECKLIST spelling) | OPEN OK |
| `compression: "None"`, `compressionLevel: ""` | **OPEN FAILED** |

Two corrections to the card's brief: the level set includes **`Slow`** (five
values, not four), and `compressionLevel: ""` is fatal **independently** — a fix
that repaired only `compression` would still have recorded nothing.

### 2.3 The fix, round-tripped end to end

Emit valid spellings (not omission: omitting is accepted here, but libmcap's own
struct default is `Zstd` and the module's whole crash-safe argument is that a
compressed chunk is uncountable by the stdlib tonight — so the value is stated,
never inherited). `validate_writer_options()` refuses any non-member value
**before** a file is written, and `storage_config_yaml()` calls it.

The actual emitted files, fed back to the real plugin:

```text
$ python -m scripts.parcel_capture.rosbag2 --emit-storage-config emitted_crash_safe.yaml
$ python -m scripts.parcel_capture.rosbag2 --profile indexed --emit-storage-config emitted_indexed.yaml
$ jazzy.sh '... write_bag.py emitted_crash_safe.yaml ...'   -> WROTE OK
$ jazzy.sh '... write_bag.py emitted_indexed.yaml ...'      -> WROTE OK
$ read_rosbag2_mcap on what they produced:
  bag_emitted_crash_safe_0.mcap   clean counts={'/lowstate': 12} compressions=()
  bag_emitted_indexed_0.mcap      clean counts={'/lowstate': 12} compressions=('none',)
```

That last line also proves the options are not silently ignored: `noChunking:
true` produced a file with **no chunk record at all**, `noChunking: false` +
`chunkSize: 4194304` produced an uncompressed chunk.

---

## 3 · F3 (new) — the argv the operator was going to type

The card said re-check every flag and every value. Three of them do not exist on
the target distro.

### 3.1 Primary-source evidence

`ros2/rosbag2`, `ros2bag/ros2bag/verb/record.py`:

| flag | Humble (branch + tags 0.15.13 / 0.15.14 / 0.15.16) | Jazzy (measured `--help`, rosbag2 0.26.11) |
|---|---|---|
| topic list | `parser.add_argument('topics', nargs='*')` — **positional** | `--topics Topic [Topic ...]`; positional kept, marked *(deprecated)* |
| `--topics` | **ABSENT** | present |
| `--disable-keyboard-controls` | **ABSENT** (the string `keyboard` does not occur in the file) | present |
| `--node-name` | **absent in 0.15.13, 0.15.14, 0.15.16**; the branch tip appears to declare it | present, default `rosbag2_recorder` |
| `--output` / `--storage` / `--max-cache-size` / `--max-bag-size` / `--max-bag-duration` / `--storage-config-file` / `--qos-profile-overrides-path` | present | present |

`ros2cli` uses argparse: an unrecognised option is exit 2 before any recording
starts. The shipped argv ended `--topics /utlidar/cloud ...` and carried
`--disable-keyboard-controls` and `--node-name`. On a Humble Orin that is a
session that records nothing.

### 3.2 The fix, and why HUMBLE is the default

`Rosbag2Plan.distro: RosDistro = HUMBLE`. The Humble argv uses the positional
topic list and omits all three flags — and that argv is **also legal on Jazzy**
(positional is deprecated there, not removed), so it is the fail-safe form for a
machine whose distro nobody has yet read off `/etc/nv_tegra_release`
(RISK_ASSESSMENT platform risk #1). Both forms were parsed by Jazzy's own
argparse, in the sandbox, with no node created:

```text
### JAZZY argv under Jazzy's own parser:
ARGPARSE OK: --topics=25 positional=0 storage=mcap max_bag_size=0 max_cache=8388608
             node_name=parcel_rosbag2_recorder
### HUMBLE argv under Jazzy's own parser (the intersection claim):
ARGPARSE OK: --topics=0 positional=25 storage=mcap max_bag_size=0 max_cache=8388608
             node_name=rosbag2_recorder
```

`--node-name` is gated for a weaker reason than the other two and deliberately:
two fetches of the `humble` branch and the 0.15.16 tag disagree about whether it
exists there, the flag is cosmetic, and nothing depends on our name
(`/events/*` are namespace-relative, not node-name-relative;
`grep -rn parcel_rosbag2_recorder` finds only this module and a stale
`PSG_STATUS.md` line). Unknown = absent.

### 3.3 The four-second gate that replaces guessing

`validate_argv_against_help(argv, help_text)` + `--verify-help PATH`:
`ros2 bag record --help > f` on the Orin, then
`python -m scripts.parcel_capture.rosbag2 --verify-help f`. It refuses on any
`--flag` the installed recorder lacks, and refuses a help text it does not
recognise (unknown ≠ clearance). Exit 2 on refusal, 0 on clearance.

### 3.4 Values, not just flags

The emitted argv (Humble, default plan):

```text
ros2 bag record --storage mcap --output /data/parcel/take01 --max-cache-size 8388608
  --max-bag-size 0 --max-bag-duration 0 /utlidar/cloud ... /events/messages_lost
```

* `--storage mcap` — the plugin name; `-s` choices are built from installed
  plugins, so a missing `ros-humble-rosbag2-storage-mcap` is an argparse error,
  which the readiness report names.
* `--max-cache-size 8388608` — 8 MiB, deliberate against a 104857600 default
  that is **double-buffered** (up to 2× in RAM).
* `--max-bag-size 0` / `--max-bag-duration 0` — **now emitted explicitly, and
  the default is 0.** It was 4 GiB, and omitted-when-zero. At the recommended
  profile's measured 84.60 MiB/s (`BANDWIDTH_BUDGET.md` §1) a 4 GiB threshold
  splits every **48 seconds** — 37 files across the 30-minute core block —
  while `TAKE_SCRIPT.md` / `TONIGHT_CHECKLIST.md:876` tell the operator
  "more than one `.mcap`, or `write_split` count > 0 ⇒ **STOP**". The recorder
  plan must not trip the sheet that governs the session. Splitting remains
  available as an explicit choice; the value is one line to change back.
* `--storage-config-file` is still optional, and the readiness report now warns
  when the named file does not exist: on Humble that argument is argparse's
  `FileType('r')`, so a missing file is exit 2 before recording starts.
* still never `-a`.

---

## 4 · Seeded-failure table (the fixes are load-bearing)

Harness: `scratchpad/ps_m/revert_harness.py` — puts one shipped defect back,
runs the suite with `-B` and `PYTHONDONTWRITEBYTECODE=1`, purges `__pycache__`
before and after, restores from bytes held in memory, verifies sha256.

```text
baseline sha256 05fe96cfec5458cd9b002237260eadbbc123d2916b5c2bef63ec4f533ed875f2  (77230 bytes)

=== revert F1-reader-uint32 ===              4 failed, 50 passed
  FAILED test_a_chunk_records_length_prefix_is_read_as_uint64_not_uint32
  FAILED test_a_chunked_bag_is_walked_and_a_compressed_one_falls_back_and_says_so
  FAILED test_a_chunked_bag_written_by_the_real_libmcap_writer_reads_back_clean
  FAILED test_our_fixture_writer_frames_chunk_records_the_way_libmcap_does

=== revert F1-reader-and-fixture-uint32 ===  3 failed, 51 passed
  FAILED test_a_chunk_records_length_prefix_is_read_as_uint64_not_uint32
  FAILED test_a_chunked_bag_written_by_the_real_libmcap_writer_reads_back_clean
  FAILED test_our_fixture_writer_frames_chunk_records_the_way_libmcap_does
  (note: the PRE-EXISTING chunk test PASSES here — this is the fully shipped
   state, and it is why the old suite was green over a dead reader)

=== revert F2-empty-enum-strings ===         2 failed, 52 passed
  FAILED test_no_writer_option_is_ever_an_empty_enum_string
  FAILED test_the_crash_safe_profile_turns_chunking_and_compression_off

=== revert F3-humble-hostile-argv ===        3 failed, 51 passed
  FAILED test_the_cli_can_clear_the_argv_against_a_saved_help_file
  FAILED test_the_humble_argv_carries_no_flag_humbles_recorder_does_not_have
  FAILED test_the_split_thresholds_are_explicit_even_when_they_are_zero

restored sha256 05fe96cfec5458cd9b002237260eadbbc123d2916b5c2bef63ec4f533ed875f2  identical=True
git diff --stat vs HEAD: (clean — the file is untracked, from PS-G)
```

---

## 5 · Gates

```text
$ .parcel/bin/python -m pytest tests/test_rosbag2_sidecar.py -q
54 passed in 0.18s

$ .parcel/bin/python -m pytest tests/test_rosbag2_sidecar.py tests/test_capture_sidecar.py \
    tests/test_capture_envelope.py tests/test_capture_preflight.py \
    tests/test_capture_rehearsal.py tests/test_clockmap.py -q
664 passed in 13.33s

$ .parcel/bin/python -m ruff check scripts/parcel_capture/rosbag2.py tests/test_rosbag2_sidecar.py
All checks passed!

$ .parcel/bin/python -c "import ast,pathlib; ast.parse(pathlib.Path('scripts/parcel_capture/rosbag2.py').read_text(), feature_version=(3,10))"
rosbag2.py parses under Python 3.10 grammar (ast feature_version=(3,10)); dev interpreter is 3.14.4
```

### ci_gate, twice, because the tree moved under it

```text
$ .parcel/bin/python scripts/ci_gate.py --tier commit          # 13:46:13Z
[  FAIL] HARD  ruff          15 violation(s), baseline 7, new 8
[  FAIL] HARD  default-suite 8 failed, 4962 passed, 9 skipped, 36 deselected in 324.12s
RESULT: FAIL — 2 hard gate(s) red: ruff, default-suite

$ .parcel/bin/python scripts/ci_gate.py --tier commit          # 13:51:14Z, five minutes later
[  FAIL] HARD  ruff          20 violation(s), baseline 7, new 13 -> scripts/parcel_capture/ingest/l2.py::F821;
      scripts/parcel_capture/preflight.py::RUF100; tests/test_bandwidth_budget_doc.py::PLW1510;
      tests/test_bandwidth_budget_doc.py::RUF100; tests/test_capture_ingest.py::F401;
      tests/test_capture_ingest.py::I001; tests/test_capture_ingest.py::RUF100;
      tests/test_no_arm_pin.py::FURB188; tests/test_no_arm_pin.py::ISC004;
      tests/test_no_arm_pin.py::PERF102; tests/test_no_arm_pin.py::PLW1510;
      tests/test_no_arm_pin.py::SIM114; tests/test_tonight_checklist_drivers.py::RUF100
[  PASS] HARD  default-suite 5002 passed, 9 skipped, 36 deselected, 5 warnings in 218.89s
RESULT: FAIL — 1 hard gate(s) red: ruff
  elapsed 231.0s
```

**RESULT: FAIL — 1 hard gate(s) red: ruff.** Attribution, measured:

* **None of the 13 new ruff violations is in a file this card owns.** They are in
  `scripts/parcel_capture/ingest/l2.py`, `preflight.py`,
  `tests/test_bandwidth_budget_doc.py`, `tests/test_capture_ingest.py`,
  `tests/test_no_arm_pin.py`, `tests/test_tonight_checklist_drivers.py` — all
  other PS-3 cards, all in flight at the minute the gate ran. `ruff check` on my
  two files is clean.
* The count **grew from 8 to 13 between the two runs**, which is the same
  concurrent-editing artefact PSK recorded as M14.
* The first run's 8 `default-suite` failures were all
  `tests/test_no_arm_pin.py`, another card's file mid-edit; five minutes later
  that file passes 65/65 and the whole suite is green with my 54 tests in it.
* I did not touch another card's file to turn the gate green.

Nothing was armed. No publisher, no `ControlManager`, no lease, no motion
client, no vendor SDK; `.parcel/` is untouched. The sandbox work ran under
`bwrap --ro-bind ... --unshare-net --unshare-pid` against a read-only rootfs
that was already in the repo, created no ROS node, published no topic, and wrote
only into a scratch bind mount.

---

## 6 · does_not_prove

1. **Nothing here ran on Humble.** Every execution was ROS 2 **Jazzy**
   (`rosbag2` 0.26.11, `libmcap` 1.3.1) in the repo's sandbox. The Humble facts
   — no `--topics`, no `--disable-keyboard-controls`, positional topic list —
   come from `ros2/rosbag2`'s source, not from the Orin. The Orin's distro
   itself is still an assertion nobody has verified. `--verify-help` exists
   precisely because I could not settle this here.
2. **`--node-name` is unresolved, not decided.** Two reads of the `humble`
   branch and of tag 0.15.16 disagreed. I omitted it because it is cosmetic and
   an unknown option is fatal; if the Orin's `--help` shows it, nothing is lost
   by its absence.
3. **The storage config was never read by the version that will read it.** Key
   names and enum spellings are measured against 0.26.11. A Humble-era
   `rosbag2_storage_mcap` could name a key differently; an unknown key is
   *silently ignored*, which is why `TONIGHT_CHECKLIST.md` N4e verifies the
   setting from the written file and not from the exit code.
4. **The MCAP width audit is proven only for the record types a real rosbag2 bag
   contains.** Attachment, AttachmentIndex and SummaryOffset internals are never
   decoded by this reader and were checked against the spec by eye, not against
   bytes. ChunkIndex and MessageIndex are likewise skipped, not parsed — the
   zero-leftover walk proves their *framing*, not their contents.
5. **Compressed chunks are still counted on trust.** `count_basis` says
   `unavailable_compressed` and quotes the writer's `Statistics`; no zstd/lz4
   decompressor exists here and the board forbids installing one. If the session
   is recorded with `zstd_fast`, the stdlib walk cannot corroborate the counts.
6. **The `--max-bag-size` default change is a judgement, not a measurement.**
   The 48-seconds-per-split arithmetic is derived from `BANDWIDTH_BUDGET.md`'s
   figure, which is itself an estimate for a rate nobody has recorded on this
   hardware. If the owner prefers bounded corruption damage to an unsplit file,
   the value changes in one line — but then `TAKE_SCRIPT.md`'s abort rule must
   change with it, or the sheet stops a healthy session.
7. **The embedded real bag is 40 messages of `std_msgs/String` on one topic.**
   It proves the framing and the record types. It does not prove behaviour at
   session scale — hundreds of gibibytes, 25 topics, split files, a recorder
   killed mid-chunk. `write_fixture_bag` still carries those cases, and it is
   our code testing our code.
8. **No claim about `/events/messages_lost`, the eight driver topic names, or
   the DDS topic list** is touched by this card; they remain UNVERIFIED as PS-G
   left them.
9. **`PSG_STATUS.md` is now stale** in three places (the quoted argv at :196–197,
   the quoted storage config at :219–227, and the `compression: ""` claim at
   :38). I did not edit another card's status document. Someone should.
