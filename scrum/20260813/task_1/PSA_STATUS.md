# PS-A status — channel matrix + `CaptureEnvelope`

**Card:** PS-A (`README.md` §PS-A) · **Executor:** Opus · **Date:** 2026-08-13
**Base:** `dd2e857` (working tree; the board cites `406f9d6`)
**Verdict:** complete, gates measured, two design calls flagged for the auditor
below (§OWNS deviations).

---

## What I built

| Path | Lines | What it is |
|---|---|---|
| `src/parcel_robot/capture/channels.py` | 796 | Machine-readable transcription of `CHANNEL_MATRIX.md`: 22 `Channel` records covering all 19 rows, each with channel id, human name, device, transport, address, message type, rate kind + nominal rate, `frame_id`, criticality, presence, matrix row, and a note. |
| `src/parcel_robot/capture/envelope.py` | 603 | `CaptureEnvelope` (per-message provenance), `ChannelSequenceBook` (mints the **per-channel** sequence at receipt), `ChannelSequenceLedger`/`ChannelSequenceReport` (reads number lines back off the record and attributes gaps), canonical JSON + digest. |
| `src/parcel_robot/capture/__init__.py` | 97 | Re-export surface + the two invariants stated for a reader. |
| `tests/test_capture_envelope.py` | 1103 | 51 cells across 7 gates, each property cell paired with a seeded-failure companion. |
| `scripts/parcel_capture/__init__.py` | 25 | Empty package skeleton for PS-B/C/D/E, plus the scope rules for that tree. **Docstring only, no code.** |

Nothing else in the repo was touched. `git status --porcelain` shows exactly
three new paths and no modification to any pre-existing file
(`git diff --stat` over `bags/`, `runtime.py`, `pose.py`, `navigation/`,
`route_memory/`, `evals/`, `scripts/ci_gate.py` is **empty**).

### The design point the card is about

`bags/recorder.py` stamps `sequence=self._sequence` (`:98`) and increments it
**after** the write (`:114`). Two distinct defects follow, and I test both:

1. **Write-assigned.** A message that is never written never advances the
   counter, so it leaves no hole at all. A bag that lost 3 messages is
   *identical* to a bag whose sensor published 3 fewer.
2. **Global.** Even minted at receipt — a strictly stronger scheme — one
   counter cannot attribute a gap to a channel.

`ChannelSequenceBook.stamp()` mints the sequence **per channel, in the reader,
at receipt**, before anything that can fail. `ChannelSequenceLedger` then reads
those numbers off the written record, so every hole names its channel.

**The limit, stated up front:** a message lost *in transit*, before the
subscriber callback ran, was never sequenced by us and is invisible to this
scheme. That needs a producer-side counter (`lowstate.tick`, a ROS header)
cross-checked against ours. That is PS-B's, and this module does not pretend to
do it. It is written into the module docstring, not just here.

---

## MEASURED claims

Every row is a command that was executed and its verbatim output. Nothing in
this table is an estimate; the two estimates in this document are labelled as
such in §does_not_prove.

### C1 — the suite

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_envelope.py -q
...................................................                      [100%]
51 passed in 0.26s
```

### C2 — matrix coverage and table shape

```
$ .parcel/bin/python -c "from parcel_robot.capture import CHANNELS, MATRIX_ROW_TITLES; from collections import Counter; print('channels =', len(CHANNELS), '| matrix rows covered =', len({c.matrix_row for c in CHANNELS}), 'of', len(MATRIX_ROW_TITLES)); print('presence  ', dict(Counter(c.presence.value for c in CHANNELS))); print('criticality', dict(Counter(c.criticality.value for c in CHANNELS))); print('rate_kind ', dict(Counter(c.rate_kind.value for c in CHANNELS)))"
channels = 22 | matrix rows covered = 19 of 19
presence   {'live': 18, 'confirm_on_hand': 3, 'awaiting_hardware': 1}
criticality {'critical': 6, 'important': 11, 'opportunistic': 5}
rate_kind  {'periodic': 9, 'event_driven': 1, 'unknown': 2, 'configured': 10}
```

### C3 — per-channel drop attribution (the headline gate), as a live artifact

20 receipts alternating `go2.utlidar.cloud` / `go2.lowstate`; the writer loses
the cloud channel's messages 3, 4, 5.

```
$ .parcel/bin/python -c "<20-receipt run, writer drops utlidar.cloud 3/4/5>"
{"go2.lowstate": {"channel_id": "go2.lowstate", "received": 10, "first_sequence": 0, "last_sequence": 9, "missing": [], "missing_count": 0, "missing_truncated": false, "duplicated": [], "duplicate_count": 0, "out_of_order": 0},
 "go2.utlidar.cloud": {"channel_id": "go2.utlidar.cloud", "received": 7, "first_sequence": 0, "last_sequence": 9, "missing": [3, 4, 5], "missing_count": 3, "missing_truncated": false, "duplicated": [], "duplicate_count": 0, "out_of_order": 0}}
```

The gap is attributed to `go2.utlidar.cloud` **only**; the continuous channel is
`is_clean`.

### C4 — the leaf property, measured directly (not just by AST)

```
$ .parcel/bin/python -B -c "import sys; before=set(sys.modules); import parcel_robot.capture; added=sorted(set(sys.modules)-before); print('parcel:', [m for m in added if m.startswith('parcel_robot')]); print('non-stdlib added:', [m for m in added if m.split('.',1)[0] not in sys.stdlib_module_names and not m.startswith('parcel_robot')])"
parcel: ['parcel_robot', 'parcel_robot.capture', 'parcel_robot.capture.channels', 'parcel_robot.capture.envelope', 'parcel_robot.evidence_origin']
non-stdlib added: []
```

The in-test version of this compares against a control subprocess so that
whatever `site` injects on this host cannot mask a real import.

### C5 — the motion guarantee is intact (no vendor SDK was installed)

```
$ .parcel/bin/python -c "import importlib.util as u; [print(f'{m}: {\"PRESENT\" if u.find_spec(m) else \"absent\"}') for m in ['rclpy','cyclonedds','unitree_sdk2py','pyrealsense2','cv2','mcap','zstandard','numpy']]"
rclpy: absent
cyclonedds: absent
unitree_sdk2py: absent
pyrealsense2: absent
cv2: absent
mcap: absent
zstandard: absent
numpy: PRESENT
```

`numpy` was already a declared project dependency (`pyproject.toml:12`) and the
capture package does not import it (C4). Nothing was installed by this card.

### C6 — lint

```
$ .parcel/bin/python -m ruff check --output-format=concise src/parcel_robot/capture/ scripts/parcel_capture/ tests/test_capture_envelope.py
All checks passed!
```

### C7 — Python 3.10 · how I verified it, honestly

**No Python 3.10 process was executed. There is no 3.10 interpreter on this
host.**

```
$ .parcel/bin/python -V
Python 3.14.4
$ ls /usr/bin/python3*
/usr/bin/python3
/usr/bin/python3.14
$ which uv pyenv docker podman conda
(none of uv/pyenv/docker/podman/conda on PATH)
```

The 3.10 claim is therefore **static**, and is made of three measured checks in
`test_the_package_parses_as_python_310_and_uses_no_post_310_surface`:

1. `ast.parse(source, feature_version=(3, 10))` accepts every package file —
   this really does reject newer syntax, demonstrated on three mutants:
   ```
   $ .parcel/bin/python -c "<ast.parse(mutant, feature_version=(3,10)) for three mutants>"
   REJECTED 'try:\n    pass\nexcept' -> Exception groups are only supported in Python 3.11 and greater
   REJECTED 'type Alias = int\n'     -> Type statement is only supported in Python 3.12 and greater
   REJECTED 'def f[T](x: T) -> T:'   -> Type parameter lists are only supported in Python 3.12 and greater
   ACCEPTED 'x = 1\n'
   ```
2. Every import is in an explicit allow-list — `__future__`, `collections.abc`,
   `dataclasses`, `enum`, `hashlib`, `json`, `types`, `typing`,
   `parcel_robot.evidence_origin` — each of which shipped in CPython 3.10 and
   each of which is asserted to be in this interpreter's
   `sys.stdlib_module_names`.
3. No symbol in the package is one of 23 enumerated post-3.10 stdlib/typing
   additions (`StrEnum`, `Self`, `tomllib`, `hashlib.file_digest`,
   `itertools.batched`, `ExceptionGroup`, …).

The 3.14 half is dynamic: the package imports and all 51 cells run on 3.14.4.
What remains unproven is in §does_not_prove.

### C8 — ci_gate

`RESULT: PASS — every hard gate green.` Full output in the CI_GATE section at
the end of this document. Note `ruff  7 violation(s), baseline 7, new 0`: this
card added **zero** new `(file, rule)` fingerprints to the ratchet.

---

## Seeded-failure table

Two kinds of row. **In-test mutants** re-implement the defective scheme inside
the test and show the oracle rejects it (the `test_w0a_physical_provenance.py`
idiom). **Shipped-module mutants** were applied to the real source on disk by a
harness, the suite re-run with bytecode caching disabled, and the source
restored; the harness verifies the tree is byte-identical afterwards.

| # | Gate | Seeded fault | Proof it was caught |
|---|---|---|---|
| G1 | Per-channel sequence | `ChannelSequenceBook` reverted to **one global counter** (shipped-module mutant M1) | `FAILED test_per_channel_sequence_attributes_a_drop_to_exactly_one_channel` |
| G2 | Refutation vs the *shipped* recorder | Two worlds — "A published 10, writer lost 3" and "A published 7, lost none" — recorded through the real `bags.recorder.BagRecorder` | `assert world_dropped == world_slow_sensor` holds: the bags are **identical message for message**, global sequence `0..16` contiguous. `loss_is_visible_oracle` raises `AssertionError("no evidence of loss")` on the bag and passes on the per-channel ledger. |
| G3 | Refutation vs a *stronger* global scheme | Global counter minted at **receipt**; two worlds where the two lost receipts belong to A vs to B | `assert global_a == global_b` — written records identical (`positions [0,1,2,3,6,7,8,9]`), yet `attribution_oracle` names A in one world and B in the other; feeding the wrong owner raises. |
| G4 | Drop / duplicate / late-arrival are distinct | A stream with a hole at 3, a late arrival of 3, and a re-delivery of 5 | `missing == ()`, `out_of_order == 1`, `duplicated == (5,)`, `duplicate_count == 1`, `received == 7`, `not is_clean` |
| G5 | Silence is visible | A channel that delivers **nothing** is absent from a bare report | `report(expected=[...])` yields `received=0`, `first_sequence=None`; the bare report omits it — asserted both ways |
| G6 | Round-trip byte-stable | 22 parametrised channels: `canonical_json → from_dict → canonical_json` | byte equality asserted (not just `==`), digest equality asserted, every dict value asserted `str`/`int`/`None` |
| G7 | Digest binds every field | 7 single-field mutations of one envelope | `len(digests) == 8` — every mutation moves the digest |
| G8 | Malformed input is refused, never defaulted | 17 malformed records: missing key, extra key, wrong schema, undecodable enum, non-mapping, `1.5`/`NaN`/`True`/`"1786000000"`/`None` clocks, negative sequence, unknown channel, frame mismatch, blank calibration ref | each asserted to raise `CaptureRefusedError` with the **exact** `RefusalReason`; unknown channel raises `UnknownChannelError` |
| G9 | Clock coercion | `_require_int` mutated to `int(value)` on floats (M4) | `FAILED test_seeded_failure_a_malformed_record_is_refused_not_defaulted` |
| G10 | `origin` fails closed | `stamp()` mutated to accept `UNKNOWN` (M2) | `FAILED test_origin_defaults_to_unknown_and_unknown_is_never_recorded_under`; also in-test: 6 spoofs (`"physical"`, `"PHYSICAL"`, `"unknown"`, `""`, `None`, `1`) all raise `ORIGIN_NOT_TYPED`, and a refusal is asserted **not** to consume a sequence number |
| G11 | Synthetic origin must name its fixture | fixture-label rule disabled (M10) | `FAILED test_a_synthetic_origin_must_name_its_fixture_and_physical_must_not` |
| G12 | Frame comes from the matrix | frame equality check disabled (M9) | `FAILED test_seeded_failure_a_malformed_record_is_refused_not_defaulted` (the `FRAME_MISMATCH` cell); plus `"frame_id" not in ChannelSequenceBook.stamp.__code__.co_varnames` — there is no argument on that path that can set a wrong frame |
| G13 | Presence fails closed | `utlidar/imu` upgraded to `LIVE` (M3) | `FAILED test_presence_fails_closed_where_the_matrix_hedges` |
| G14 | Matrix coverage | a channel deleted (duplicate id, M8) | import-time `CaptureError: duplicate channel_id in CHANNELS` → collection ERROR |
| G15 | Table refuses nonsense | 7 in-test malformed `Channel`s: flat id, uppercase id, `matrix_row=20`, blank note, nominal rate on a `CONFIGURED` kind, `inf` rate, `NaN` rate | each raises `CaptureError` with the matching message; the real table asserted untouched afterwards |
| G16 | Stdlib-only leaf | `import numpy` added to `channels.py` (M5) | `FAILED test_the_capture_package_is_a_stdlib_only_leaf`; in-test: 4 forbidden import forms (`parcel_robot.runtime`, `rclpy`, `parcel_robot.navigation`, `from ..control`) all rejected by the same budget |
| G17 | Read-only pin | `def create_publisher(...)` added to `envelope.py` (M6) | `FAILED test_no_symbol_in_the_capture_package_can_reach_a_motion_surface`; in-test: 8 mutants (publisher, `ControlManager` import, `def move`, `set_target`, `import parcel_robot.control`, `getattr(mod,'create_publisher')`, `import unitree_sdk2py`, `lease = api.acquire()`) all caught, **and** a negative control proves the scan does not fire on the legitimate vendor sensor names `wirelesscontroller` / `WirelessController_` / `unilidar_sdk2` |
| G18 | Dual-Python | `from enum import Enum, StrEnum` added to `envelope.py` (M7) | `FAILED test_the_package_parses_as_python_310_and_uses_no_post_310_surface`; in-test: 3 syntax mutants rejected by `feature_version=(3,10)` and 4 surface mutants caught by the symbol scan |
| G19 | Bounded memory under catastrophic loss | a 10,000,000-message sequence jump | `missing_count == 9_999_999` (exact), `missing_truncated is True`, `len(missing) == 100_000` — the count stays exact past the enumeration bound |
| G20 | Bag-topic usability | every channel's `bag_topic` fed to the real `bags.schema.validate_topic` | 22/22 accepted, none privileged per `is_privileged_key` |

Shipped-module mutation harness output (all 10 caught, tree restored):

```
$ .parcel/bin/python <scratchpad>/mutate.py
M1 global counter: CAUGHT | FAILED test_per_channel_sequence_attributes_a_drop_to_exactly_one_channel
M2 stamp accepts UNKNOWN origin: CAUGHT | FAILED test_origin_defaults_to_unknown_and_unknown_is_never_recorded_under
M3 utlidar/imu presence upgraded to LIVE: CAUGHT | FAILED test_presence_fails_closed_where_the_matrix_hedges
M4 clock coerces a float instead of refusing: CAUGHT | FAILED test_seeded_failure_a_malformed_record_is_refused_not_defaulted
M5 non-stdlib import added to the leaf: CAUGHT | FAILED test_the_capture_package_is_a_stdlib_only_leaf
M6 a symbol that can speak to the robot: CAUGHT | FAILED test_no_symbol_in_the_capture_package_can_reach_a_motion_surface
M7 post-3.10 stdlib surface (enum.StrEnum): CAUGHT | FAILED test_the_package_parses_as_python_310_and_uses_no_post_310_surface
M8 a channel dropped from the matrix: CAUGHT | ERROR duplicate channel_id in CHANNELS
M9 frame taken from the caller instead of the matrix: CAUGHT | FAILED test_seeded_failure_a_malformed_record_is_refused_not_defaulted
M10 synthetic origin no longer needs a fixture label: CAUGHT | FAILED test_a_synthetic_origin_must_name_its_fixture_and_physical_must_not
harness_exit=0
```

**Harness finding worth recording for the tranche.** The first run reported M9
and M10 as caught for the wrong reason: M8's mutation happened to be
*byte-length-identical* to the original, so CPython's `(mtime, size)` `.pyc`
validity check reused the mutated bytecode for the restored source and
contaminated the next two runs. Re-run with `-B`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider` and an explicit
`__pycache__` removal, the attributions are correct. **Any card in this tranche
running a mutation harness should do the same** — a same-size mutation is not
exotic (mine was a one-digit change).

---

## OWNS deviations and design calls for the auditor

**D-1 — 19 matrix rows became 22 channels. Flagged, not slipped.**
`README.md:53` says "15 entries"; `CHANNEL_MATRIX.md` — which my brief names as
the authoritative enumeration — has **19 numbered rows**. I built against the
matrix. Three of its rows textually bundle streams that arrive and drop
separately:

* row 7 names **two topics** (`lf/lowstate`, `lf/sportmodestate`);
* row 14 says "Infrared **×2** … Y8 left + right";
* row 15 says "accel **+** gyro", which `pyrealsense2` delivers as two motion
  streams at two selectable rates.

Bundling either of those pairs behind one sequence counter reintroduces the
exact defect this card exists to fix, one level down: a drop on IR-left hidden
behind IR-right's traffic is invisible for the same reason a drop on
`lidar/scan` is invisible behind `imu/data`. So the recording unit is the
**stream**. `MATRIX_ROW_TITLES` keeps all 19 rows verbatim and every channel
names its row, so coverage is machine-checkable in both directions and the
document remains the authority. `test_every_matrix_row_is_covered_and_no_
channel_invents_a_row` pins that exactly rows {7, 14, 15} may expand — a fourth
expansion reddens.

**D-2 — `utlidar/imu` is `CONFIRM_ON_HAND`, not `LIVE`.**
`CHANNEL_MATRIX.md:26` transcribes it as "LIVE if published". A conditional is
not a confirmation, and board rule 3 says unknown is absent, so it sits with
GNSS and UWB in the confirm-at-preflight set. If the auditor reads the matrix
as asserting `LIVE`, this is a one-line change — but I believe the fail-closed
reading is the one the board rule requires, and PS-D will settle it empirically
in any case.

**D-3 — I added three fields the card did not enumerate**, because the ten it
did enumerate could not be made fail-closed without them:

* `rate_kind` — so `nominal_rate_hz=None` is never ambiguous. `EVENT_DRIVEN`
  (silence is normal), `CONFIGURED` (PS-E/PS-D supplies the number),
  `UNKNOWN` (unassessable) are three different things, and a consumer that
  branches on `None` alone would treat all three the same. 10 of 22 channels
  are `CONFIGURED` — the whole D455 group, the L2 cloud (matrix says 10–20 Hz,
  which is a device setting, not a constant), and `tegrastats`.
* `matrix_row` — makes D-1's coverage claim checkable rather than asserted.
* `note` — non-empty by construction; carries the provenance or the specific
  uncertainty (e.g. the L1-vs-L2 contradiction on the built-in unit, the
  unconfirmed `voxel_map_compressed` message type).

`CaptureEnvelope` also carries `fixture_label` beyond the card's list: PS-E
drives this same stack from synthetic publishers, and a rehearsal envelope must
be impossible to mistake for a session envelope once both are in a bag. Reusing
`evidence_origin.SYNTHETIC_ORIGINS`, a synthetic origin **must** name its
fixture and a physical origin **must not** carry one.

**D-4 — no deviation on scope.** I created `scripts/parcel_capture/__init__.py`
and nothing else in that tree, per the card. No file outside my OWNS list was
created or modified.

---

## does_not_prove

1. **Nothing here has seen a sensor.** Every value in `channels.py` —
   `message_type`, `nominal_rate_hz`, `frame_id`, `presence` — is a transcribed
   expectation from `CHANNEL_MATRIX.md` and vendor documentation, not a
   measurement. PS-D falsifies them against the unit. The least certain entry
   is `go2.utlidar.voxel_map`'s `std_msgs/msg/dds_/String_`; the built-in LiDAR
   model is repo-contradicted (Unitree says L2, `P5_PROCUREMENT_BOM.md:35` says
   L1) and is *deliberately* not resolved here.
2. **Per-channel sequencing does not detect transit loss.** A message dropped
   by DDS or USB before our subscriber callback ran was never sequenced by us
   and leaves no hole. Only a producer-side counter (`lowstate.tick`, ROS
   header) cross-checked against ours can see it. This scheme detects loss
   *between receipt and record*, which is the writer/backpressure/truncation
   class — the class PS-B's crash-safety card is about.
3. **The 3.10 claim is static.** No 3.10 interpreter exists on this host, so
   nothing was executed under 3.10. `ast.parse(feature_version=(3,10))` catches
   syntax and my symbol allow-list catches known post-3.10 names, but neither
   would catch a **behavioural** 3.10/3.14 difference (dict ordering guarantees
   are unaffected here; `dataclass(slots=True)` and `frozenset` semantics are
   3.10-stable; but this is reasoning, not measurement). **The first real
   verification is running `python3.10 -c "import parcel_robot.capture"` on the
   Orin, and that belongs on the Stage-0 sheet.**
4. **The read-only pin is a static scan, not a sandbox.** It proves no symbol
   or non-docstring literal in the package names a publisher, a control
   manager, `Move`, `set_target`, or a control module, and that the import
   graph reaches only stdlib + `evidence_origin`. It does not prove the process
   *cannot* write to a socket — a sufficiently determined `__import__` built
   from concatenated fragments would evade it. The stronger guarantee remains
   the one the plan names: `unitree_sdk2py` is absent from the venv (C5).
5. **Docstrings are excluded from the literal scan**, by design — prose cannot
   execute, and the module docstrings deliberately name these surfaces in order
   to forbid them. A reviewer who disagrees should know the exclusion is exact
   (first-statement string constants of Module/ClassDef/FunctionDef only).
6. **The ledger's classification of a late arrival vs a duplicate is
   heuristic at the margin.** A sequence below `expected_next` that is not a
   *known* hole is called a duplicate. That is exact while the pending-hole set
   is untruncated; past `MISSING_TRACKING_CAP` (100,000 outstanding holes on one
   channel) a late arrival filling an untracked hole would be miscounted as a
   duplicate. `missing_count` stays exact; only the classification degrades, and
   only under loss that is already catastrophic.
7. **No bandwidth, storage, timing or thermal claim is made here.** `d455.color`
   carries the plan's ≈132 MiB/s / ≈464 GiB/h figure in a *note* as inherited
   arithmetic; it is PS-E's to measure and I did not verify it. Likewise the
   nominal rates are the matrix's, not observed.
8. **`criticality` is my judgement, not a derivation.** Six channels are
   `CRITICAL` (both LiDAR clouds, `lowstate`, `sportmodestate`, D455
   colour+depth). That assignment feeds PS-D's go/no-go and PS-F's failure
   branch, so if the owner disagrees with any row it should be changed before
   the session, not after.
9. **This proves nothing about MCAP, sidecars, clock maps or attestation.**
   Those are PS-B/C/D. What PS-A hands them is an enumeration and an envelope
   type that refuses to be filled in wrongly.

---

## CI_GATE

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T08:56:36Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.42s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              4134 passed, 9 skipped, 36 deselected, 5 warnings in 183.06s (0:03:03)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 194.7s
```

The `default-suite` figure includes this card's 51 cells; the whole repo suite
is green with the capture package in the tree, and no MUST-NOT-TOUCH surface
moved (`frozen-digest-sentinels` byte-identical, `hard-safety` green).
