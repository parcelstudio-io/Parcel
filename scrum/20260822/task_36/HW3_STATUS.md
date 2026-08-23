# HW-3 `mid360-band` — STATUS (executor: Opus, wave 3a, 2026-08-23)

**COMPLETE.** Rows R1-R9 all MET. `PREREGISTRATION.md` sha256
`5c1faacfa262116e0604cc351dad74ac2de51535d12a0d2b61389e32c42def93`
(written before any measurement, unchanged since).

## Headline

A Livox Mid-360 UDP point frame now decodes to points, and points now band
into the **exact** angular layout `SimObservation.lidar_ranges` already
carries — 360 bins, `angle_min = -pi`, CCW, `range_min 0.05` / `range_max
30.0` — in pure Python that imports on CPython 3.10 with no numpy, no mujoco,
no socket, no ROS and no vendor SDK (measured, not asserted: the package was
imported and exercised under `~/.cache/parcel-hw1/py310/bin/python`, and a
subprocess pin proves none of those modules is in `sys.modules` after
importing it). `nearest_obstacle_m` is not a new derivation: it is the sim's,
pinned by a differential test against the real
`parcel_robot.sim.select_relevant_obstacle` over 500 random candidate sets x 4
commands, 2000/2000 identical. 20 064 points -> ranges in **6.15 ms** on this
desktop. 144 new tests, five seeds RED, zero new ruff fingerprints.

Two findings the verifier should read before anything else are in §"Findings"
below: the card's `evidence_origin == physical` sentence is unreachable by
construction, and the capture matrix deliberately did not grow.

## What changed

    git diff --stat -- <OWNS>   (index vs working tree = this wave only)
    scripts/parcel_capture/ingest/l2.py  |  86 ++++++-
    src/parcel_robot/capture/channels.py | 278 +++++++++++++++++++++
    2 files changed, 361 insertions(+), 3 deletions(-)

`channels.py` is pure addition (`git diff | grep '^-[^-]'` is empty); the three
deletions in `l2.py` are my own two replaced lines (`notes`, the `__init__`
signature). Every edit in both files is inside `# ---- CARD HW-3 ... ----
END CARD HW-3` markers.

New files (untracked):

| Path | Lines | What |
|---|---|---|
| `src/parcel_robot/lidar/__init__.py` | 103 | package doc + **the HW-2 seam**, with the exact `Go2Backend.observe()` snippet |
| `src/parcel_robot/lidar/livox_udp.py` | 482 | frame parser, refusals, `sequence_report`, the socket adapter, the frame builder |
| `src/parcel_robot/lidar/band.py` | 349 | `BandProfile` / `BandScan` / `band_scan` / `scan_from_frames` / `nearest_obstacle_from_scan` / `travel_bearing_rad` |
| `tests/test_hw3_mid360_band.py` | 893 | 144 tests, R1-R8 |
| `scrum/20260822/task_36/{DESIGN,PREREGISTRATION,HW3_STATUS}.md` | — | this card's record |

sha256 of the five code/test files at close: `~/.cache/parcel-hw3/tree_sha256.txt`.

### The frame fields decoded, and the UNCONFIRMED ones

Sources read (URLs in `livox_udp.py`'s docstring and `DESIGN.md` §c): the SDK2
`include/livox_lidar_def.h` (structs inside `#pragma pack(1)`), the HAP wire
table on the SDK2 wiki, `livox_ros_driver2/src/comm/pub_handler.cpp` (the
vendor's own decode), `livox_ros_driver2/README.md`, and
`samples/livox_lidar_quick_start/mid360_config.json`. The **Mid-360** wiki
protocol page did not load (GitHub wiki error) — that is why the UNCONFIRMED
list below is as long as it is.

DECODED: `version` (refused unless 0), `time_interval` (x100 = ns window),
`dot_num`, `udp_cnt`, `frame_cnt`, `data_type`, `time_type` (`comm.h:96-98`:
0 = no sync / power-on clock, 1 = gPTP or PTP, **2 = GPS** — added in the
correction pass, F3; `synchronised` is true for 1 and 2), `timestamp` (base;
8 bytes in HOST order, LE on x86_64/aarch64 — the driver memcpy's them into a
`uint64`, `pub_handler.cpp:265-268`), and the point body for `data_type` 1 (`int32 x,y,z` mm + `u8
reflectivity` + `u8 tag`, 14 B) and 2 (`int16` cm, 8 B). Per-point time is
`t_i = timestamp + i * (time_interval*100 // dot_num)` and the metric scale is
`/1000.0` and `/100.0` — both lifted verbatim from `pub_handler.cpp`, not
inferred.

UNCONFIRMED, therefore carried verbatim or refused, never guessed:

* `length` — "bytes from sof to end of data" is the **HAP** page's wording;
  carried as `declared_length` and never decoded with.
* `rsvd[12]` — the HAP page names byte 12 `pack_info` (safety_info / tag type);
  the SDK2 header says twelve reserved bytes. Carried raw.
* `crc32` — "CRC-32 algorithm" is stated; polynomial, seed, reflection and
  xorout are not. **Not verified** — a guessed CRC would reject every real
  packet.
* `tag` (per point) — bit meanings in none of the sources. Carried raw, never
  interpreted.
* ~~`data_type` 3 / 0x11 undocumented~~ — **CORRECTED in the correction pass
  (verifier F3): both are DOCUMENTED and both are still REFUSED, as out of
  scope for HW-3 rather than as unknown.** Spherical:
  `pub_handler.cpp:429-431` (theta/phi at 0.01 deg, depth mm). Double echo:
  `livox_lidar_def.h:174-185` (`LivoxLidarDoubleEchoRawPoint`, 2 x 14 B),
  decoded at `pub_handler.cpp:469-482`. `data_type` 0 (IMU) — documented, not
  point data; **REFUSED** with the port. The refusal strings now say which.
* `frame_cnt` — "HAP keeps 0"; Mid-360 behaviour unknown, so nothing branches
  on it.
* Contradiction recorded: `livox_ros_driver2/src/comm/comm.h` has
  `KCartesianPointSize = 13` / `KSphericalPointSzie = 9`. Those are the SDK **1**
  raw points (no `tag` byte: 13 = 3x4+1, 9 = 4+2+2+1), not the SDK2 wire sizes
  (14 / 10). The byte-count refusal is what would catch it if I have this
  backwards, on the first real datagram.

### The HW-2 seam

    from parcel_robot.lidar import (
        scan_from_frames,            # frames -> BandScan (the 5 SimObservation scan fields)
        nearest_obstacle_from_scan,  # BandScan -> ObstacleFix (clearance, bearing, bin)
        travel_bearing_rad,          # (vx, vy) -> bearing | None, the sim's 1e-6 test
        BandProfile,                 # z_lo/z_hi/extrinsic/layout, all injected
    )

`src/parcel_robot/lidar/__init__.py` carries the full `Go2Backend.observe()`
snippet. `BandScan`'s first five fields are, in order, the five
`SimObservation` scan fields, so HW-2 copies rather than converts.
`parse_point_frame` / `receive_frames` are the reader half.

## How verified

Every command through `~/.cache/parcel-guard/pytest_guard.sh --label hw3` with
`env -u TMPDIR`; no `-n auto`; no `ci_gate.py --tier`; no background pytest;
27 `label=hw3` rows in `guard.log`. Pre-flight before each: `free -g`
available 232 GB (>= 120) and `ps -eo args | grep -c '^[^ ]*python[^ ]* -m
pytest'` <= 1.

| Row | Command | Result |
|---|---|---|
| R1-R8 | `pytest_guard.sh --label hw3 .parcel/bin/python -m pytest tests/test_hw3_mid360_band.py -q` | **144 passed** in 0.84 s |
| R8 number | same, `-s -k twenty_thousand` | `HW-3 R8: 20064 points -> ranges in 6.15 ms` (desktop; the Orin's is box-day) |
| Neighbours | `... -m pytest tests/test_hw3_mid360_band.py tests/test_no_arm_pin.py tests/test_capture_{envelope,ingest,sidecar,rehearsal,preflight}.py tests/test_clockmap.py tests/test_rosbag2_sidecar.py -q -n 8` | **1053 passed** in 16.8 s |
| 3.10 grammar | `python3.10 -c "ast.parse(..., feature_version=(3,10))"` on all five files | ok |
| 3.10 runtime | `~/.cache/parcel-hw1/py310/bin/python -c "import parcel_robot.lidar; ..."` | decoded a frame and returned an `ObstacleFix` |
| Lint | `.parcel/bin/ruff check src/parcel_robot/lidar/ src/parcel_robot/capture/channels.py scripts/parcel_capture/ingest/l2.py tests/test_hw3_mid360_band.py` | **All checks passed**; `ci_ruff_baseline.json` untouched at 7 fingerprints; no `noqa`. Tree-wide `ruff check .` at close: 17 findings across the 7 baseline files plus `scrum/20260822/task_35/evidence/{import_sweep,run_census}.py` (HW-1's, not mine) — no HW-3 file appears |

Rows worth naming individually:

* **R6 runs the product functions.** `scan_present`,
  `scan_evidence_from_observation` and `evaluate_input_health`, imported from
  `navigation/reactive_safety.py` and `core/input_health.py`, on a real
  `SimObservation(backend="go2")` whose `lidar_ranges` came out of
  `parse_point_frame` -> `scan_from_frames`. No monkeypatch, no stub, no fake
  evidence anywhere in the file.
* **R7 is differential, not a restatement.** The test imports the real
  `parcel_robot.sim.select_relevant_obstacle` (which drags mujoco+numpy, which
  is exactly why `band.py` reimplements it) and compares 500 x 4 selections.
* **R1's first cell does not use our own builder.** One frame is assembled
  byte by byte from the offset table so a drift shared by builder and parser
  still reddens.

### Seeded RED (R9) — five seeds, all on a byte-identical scratch

Harness `~/.cache/parcel-hw3/seed.sh`; scratch `~/.cache/parcel-hw3/scratch`
(`rsync -a --exclude .cache --exclude .parcel --exclude .git src scripts tools
tests configs prompts`), `PYTHONPATH=<scratch>:<scratch>/src`, verified with
`import parcel_robot; print(parcel_robot.__file__)` ->
`.../parcel-hw3/scratch/src/parcel_robot/__init__.py`, `__pycache__` purged
before and after each seed, restore checked by sha256 every time. Baseline in
the scratch: 144 passed. **The working tree was never seeded** (`sha256sum -c
~/.cache/parcel-hw3/tree_sha256.txt` -> 5/5 OK at close, and scratch == tree
for every OWNS file).

| Seed | Defect injected | Reddened | Restored |
|---|---|---|---|
| S1 | `data_type` refusal becomes "assume Cartesian-high" | `test_a_documented_but_undecodable_data_type_is_refused_by_name[0-56400 / 3 / 17]` — 3 failed | byte-identical |
| S2 | byte-count check disabled | `..._truncated_frame_is_refused...`, `..._longer_than_its_header_declares...` — 2 failed | byte-identical |
| S3 | band upper bound widened by 1 m | `test_no_point_outside_the_band_can_influence_any_bin` — 1 failed | byte-identical |
| S4 | `angle_min_rad` default moved to 0.0 | `test_band_profile_defaults_match_the_sim_scan_contract`, `test_a_band_scan_carries_the_five_sim_observation_scan_fields` — 2 failed | byte-identical |
| S5 | corridor filter dropped from `nearest_obstacle_from_scan` | `test_nearest_obstacle_matches_the_simulators_own_selection`, `test_a_closer_obstacle_behind_never_masks_one_in_the_travel_corridor` — 2 failed | byte-identical |

S4 deviation from its pre-registered blast radius, stated rather than
smoothed: R9 predicted S4 would redden "R5 layout+wall". It reddened the two
layout cells and **not** the 103 wall cells, because the wall property is
angle-origin invariant by construction (the test derives the expected bin from
the profile's own `angle_min`). The layout equality is what pins `angle_min`,
and it did. No test was changed to make a seed behave.

## What this does not prove

1. **That a real Mid-360's bytes match this table.** No hardware is on hand
   and no Mid-360 pcap exists in this tree or in Livox's public samples that I
   could reach; every frame in the tests is synthesised from the documented
   layout. One real datagram on box-day (HW-9) confirms or falsifies it, and
   the byte-count and version refusals are what will say so loudly.
2. **The extrinsic and the band bounds.** `[0.10, 0.60]` m and identity are
   PLACEHOLDERS marked "tune at B11". Nothing here measures a mount.
3. **Per-bin coverage.** How many frames a bin needs before it may be declared
   free space is unmeasured — which is precisely why an empty bin is NaN here
   and not the free-space sentinel (see Findings 3).
4. **Timing on the Orin.** 6.15 ms is a 192-core x86 desktop number.
5. **Anything about the M8 plug, the NIC, the subnet or the voltage** (Q-wire;
   hardware facts 7/24 are `inferred`, not `documented`).
6. **That the capture rows are right.** They are DECLARED EXPECTATIONS with
   `Confidence.UNVERIFIED` and `presence=awaiting_hardware`; the topic names
   are the driver's conventional defaults and are the first thing a session
   must check.

## Findings (read these first)

1. **The card's "labels it physical when `backend='go2'`" is unreachable by
   construction — and so is design §4 row S1's `evidence_origin == physical`,
   as written.** `core/input_health.py:114-134 evidence_origin` returns
   `(EvidenceOrigin.SIMULATION, str(label))` for **every** sample carried on a
   `SimObservation`: board decision D-1 / card W0-A made authority come from
   the CARRIER TYPE, and "there is no string — not `physical`, not `""`, not
   `unknown` — that reaches `EvidenceOrigin.PHYSICAL` from here or from
   anywhere else". R6 therefore asserts what is true: `scan_present` is True,
   the evidence is `SIMULATION` + `fixture_label="go2"`, and
   `evaluate_input_health` **ALLOWS** translation on it under
   `reactive_safety`'s own SCAN spec (`sim_fixture_allowed=True`).
   **Handoff to HW-2:** a physical `evidence_origin` requires publishing the
   scan through `control/base.py:CommissionedStateSource(inner,
   origin=EvidenceOrigin.PHYSICAL)` — the seam that exists for exactly this —
   not through `SimObservation`. Whoever writes `Go2Backend` should read this
   before promising the S1 "first proof on the box" row as stated.
2. **The capture payload matrix did not grow, deliberately.** `CHANNELS` is a
   verbatim transcription of the immutable `scrum/20260813/task_1/
   CHANNEL_MATRIX.md` (25 rows / 28 channels / 11 field rows, all three quoted
   across the tranche and pinned at `tests/test_capture_envelope.py:149,160,1489`
   — a file outside HW-3's OWNS, in a tree four peers are editing). And a
   raw-UDP `Transport` member would raise at
   `scripts/parcel_capture/record.py:1434` and redden
   `tests/test_capture_sidecar.py:1274` (`set(TRANSPORT_DEPENDENCIES) ==
   set(Transport)`). So `SourceDevice.MID360` landed with its two rows
   **beside** the matrix as `MID360_CHANNELS` / `VenueChannel`, exactly as card
   S-1 landed `SUPPORT_ARTIFACTS` beside it, with `venue="go2_edu_plus"` in
   place of a row number. `len(CHANNELS)` is still 28 and every capture suite
   is green. See handoffs H1/H2.
3. **An empty bin is `NaN`, not `range_max_m` — a stated deviation from the
   card's wording.** The card says "empty bins are the sim's 'no return'
   value". I read what the sim emits (`mujoco_lidar.PlanarScan` docstring): it
   emits two different values for two different facts, and `range_max` means
   "this ray looked and saw nothing" — it clears free space. One Mid-360 frame
   cannot say that about a bin nothing was sampled in: the pattern is
   non-repetitive, and at 10 m a 0.5 m band subtends ~3 deg of the 59 deg
   vertical FOV. Emitting the free-space sentinel there would clear space on no
   evidence in the one channel the safety layer reads. `NaN` is the sim's own
   word for "clears nothing", so that is what an empty bin gets, and the
   coverage question becomes a box-day measurement rather than a desk decision.
   Pinned by `test_an_empty_bin_is_nan_and_never_the_free_space_sentinel`.
4. **`nearest_obstacle_m` is NOT derived from the sim's scan** and a reader of
   §5.3 could easily assume it is. `sim.py:265-272` takes analytic geom hits
   whose `distance_m` is `max(0, surface_distance - footprint_radius)` and
   selects with `select_relevant_obstacle`'s travel corridor. HW-3 reproduces
   that rule over populated bins and pins it differentially; it does not
   reproduce MuJoCo's geom picking, which has no physical counterpart.
5. **The `tests/test_no_arm_pin.py` reach census caught a real thing.** My
   first `VenueChannel.__post_init__` looped over field names with `getattr`,
   and the capture stack's no-arm pin is an EXACT census of (file, function,
   reach-builtin). It reddened; the validation is now spelled out. The pin
   works, and it is worth knowing it works before someone adds `getattr` to a
   capture module for a less innocent reason.

## Deviations

* `DESIGN.md` is 234 lines against the COMMON brief's <= 150 target. Reason
  stated in its own first paragraph: the frame table and the two
  "identical to the sim" derivations are the deliverable a verifier has to be
  able to check without re-reading Livox.
* Finding 3 (NaN vs `range_max`) is a deliberate departure from the card's
  §Work 4(b) wording.
* Finding 1 (R6 asserts SIMULATION, not PHYSICAL) is a deliberate departure
  from the card's §Work 4(c) wording; the card's version is unreachable.
* Finding 2: the Mid-360 rows are beside the matrix, not in it. The card said
  "`SourceDevice.MID360` and its channel rows in a marked `CARD HW-3` region",
  which is what landed; what did not land is a growth of the 25/28 counts.
* The L2 retirement is a **venue-gated refusal**, not an unconditional one.
  `L2Ingest(venue="go2_edu_plus")` refuses with a pointer to
  `parcel_robot.lidar` and to this card, `refuse_retired_venue` is exported for
  HW-9's run sheet, and `RETIREMENT_NOTE` now rides on every report the adapter
  emits. An unconditional refusal in `open_reader()` would redden three tests
  in `tests/test_capture_ingest.py` (lines 1615, 1637, 2459), a file outside
  this card's OWNS, while four peers share the tree — so the decision is
  recorded rather than taken across an OWNS boundary (H3).
* `channels.py`'s `__all__` and `capture/__init__.py`'s re-export list were
  NOT edited: both are outside the `CARD HW-3` region. The new names import
  normally from `parcel_robot.capture.channels` (H2).
* `build_point_frame` is product code, not a test helper, on purpose: it is the
  machine-readable statement of what this module believes the wire looks like,
  and box-day falsifies *it*. The risk that a builder and a parser drift
  together is covered by the hand-written-bytes test.

## Owner-gated rows

None. Nothing here needs the owner, hardware, a simulator, a network, or spend
($0 spent; `PARCEL_REALTIME_KEY_ENV` never set).

## Handoffs

* **H1 (capture-matrix owner / HW-9, box-day):** re-cut `CHANNEL_MATRIX.md`
  table A for the EDU+ rig, then move `MID360_CHANNELS` into `CHANNELS` with
  real `matrix_row`s and bump `CHANNEL_MATRIX_ROWS` (25 -> 27),
  `tests/test_capture_envelope.py:149,160,1489` (25 -> 27, 28 -> 30) and
  `VENUE_CHANNEL_ROWS` in one commit. Nothing else depends on the split.
* **H2 (integrator or the capture owner):** add `MID360_CHANNELS`,
  `MID360_CHANNELS_BY_ID`, `VenueChannel`, `VENUE_CHANNEL_ROWS`,
  `GO2_EDU_PLUS_VENUE`, `venue_channel`, `venue_channels_for` to
  `channels.py`'s `__all__` and, if wanted, to `capture/__init__.py`. Both are
  outside this card's marked region.
* **H3 (verifier / owner call):** whether `L2Ingest.open_reader()` should
  refuse unconditionally. One line — `refuse_retired_venue(self.venue)` becomes
  an unconditional raise — plus the three `tests/test_capture_ingest.py` cells
  named above.
* **H4 (HW-2 `go2-backend`):** the seam above; Finding 1 (PHYSICAL needs
  `CommissionedStateSource`); `nearest_obstacle_id` has no physical counterpart
  (the sim fills it from a MuJoCo geom name) — leave it `None` or mint
  something declared. `BandProfile` is what HW-5's
  `configs/profiles/go2_edu_plus.yaml` must be able to express.
* **H5 (HW-2/HW-9):** the `L2` -> `HEAD_LIDAR` rename, untouched here by
  instruction. `SourceDevice.L2`, `l2.cloud`, `l2.imu` and `Transport.
  UNILIDAR_SDK2` are all unchanged; six-month-old bags join on those ids.
* **H6 (integrator):** `CODEBASE_INDEX.md` is STALE (measured:
  `tools/codebase_index.py --check`) — this card adds a package and a test
  module. Regenerate after the commit; no gate row reads it today.
* **H7 (a raw-UDP capture transport):** a `Transport.LIVOX_UDP` member needs
  `record.py`'s `TRANSPORT_DEPENDENCIES` + `TRANSPORT_EXECUTABLES` in the same
  commit (import-time refusal at `record.py:1434`) and the exhaustiveness pin
  at `test_capture_sidecar.py:1274`. Not needed until something records raw
  Livox datagrams.

## What the verifier should look at first

1. `DESIGN.md` §c against `src/parcel_robot/lidar/livox_udp.py` — is any field
   decoded that the cited sources do not define? (The UNCONFIRMED list above is
   the claim; `_undecodable_reason` and `SUPPORTED_PROTOCOL_VERSIONS` are where
   it is enforced.)
2. Finding 1, then `tests/test_hw3_mid360_band.py::
   test_the_real_evidence_rule_labels_a_sim_observation_a_labelled_fixture` —
   the card asked for something the safety core forbids, and this is the whole
   of what R6 claims instead.
3. Finding 3 — the NaN decision is the one judgment call with a safety edge.
4. `test_nearest_obstacle_matches_the_simulators_own_selection` — the
   differential is the only thing standing between "identical to the sim's
   derivation" and a plausible restatement of it.
5. `~/.cache/parcel-guard/guard.log`, `label=hw3` — 27 rows, all through the
   wrapper, none with `-n auto`, none a tier run.

---

# Correction pass (2026-08-23, 13:5x–14:0x EDT)

Against `~/.cache/parcel-verify/hw3/VERDICT.md` (Fable, **HOLD**). F1–F4
addressed, F5 recorded, F6/F7/F8 noted. Same rules: git read-only, every
pytest through `pytest_guard.sh --label hw3`, no `-n auto`, no tier, seeds on
an import-verified scratch with byte-identical restore.

`git status --porcelain` of my files, **before and after this pass — identical
set** (no file added, none dropped, none moved):

    M  scripts/parcel_capture/ingest/l2.py
    M  src/parcel_robot/capture/channels.py
    ?? scrum/20260822/task_36/
    ?? src/parcel_robot/lidar/
    ?? tests/test_hw3_mid360_band.py

Tests: **144 -> 156** (12 added, none removed, one strengthened). Neighbour set
(9 files): **1053 -> 1065**. Ruff: `All checks passed` on all four touched
files; `ci_ruff_baseline.json` untouched at 7 fingerprints; `grep -c noqa` = 0
in every file of mine. 3.10 re-checked: grammar on all six files, and under
`~/.cache/parcel-hw1/py310/bin/python` the package decodes a frame, bands it,
returns `ObstacleFix(1.68, 0.0, 180)`, gives `()` for an empty sweep, reports
`synchronised` True for a GPS stamp, and pulls in none of
numpy/mujoco/socket/_socket/rclpy.

## F1 (HOLD) — a silent sensor is now the ABSENCE of a scan

Accepted in full; the verifier is right and the reproduction is exact.

**Product change** (`band.py`): `BandProfile.min_populated_bins: int = 1`
(validated `1..bins`, documented as the FLOOR with the venue's real minimum
**tuned at B11** against measured coverage). `band_scan` now counts populated
bins and, below the threshold, emits `ranges_m=()` — the `SimObservation`
value for "no calibrated scan" — so `scan_present` is False, the core health
join reports SCAN missing, and translation HOLDs. `points_seen`,
`points_in_band` and `populated_bins` are still reported on that `BandScan`,
because box-day needs the coverage number even for a sweep that was not a
scan. The module docstring and `BandScan`'s docstring both state that
whole-sweep emptiness and per-bin emptiness are different facts and only the
second is NaN.

**Seam change** (`lidar/__init__.py`): the `Go2Backend.observe()` snippet now
branches — "**Never copy an empty `BandScan` across as if it were a scan**" —
and shows the `lidar_ranges=()` / `nearest_obstacle_m=None` return.

**Test (new): `test_a_silent_sensor_is_no_scan_not_a_clear_one`.** The
verifier's exact path through the REAL functions, no monkeypatch:
`scan_from_frames([])` -> `ranges_m == ()`, `points_seen == 0` ->
`SimObservation(backend="go2", lidar_ranges=())` -> `scan_present is False`,
`scan_evidence_from_observation is None` ->
`apply_reactive_safety(VelocityCommand(0.3), obs, policy=ReactiveSafetyPolicy(),
now=obs.timestamp)` -> `(0.0, 0.0), "stopped"`. It then keeps the
counterfactual as a live assertion: the same observation carrying a 360-NaN
tuple gives `scan_present True` and `(0.3, "clear")` — so the finding cannot
silently come back. Plus
`test_min_populated_bins_is_a_profile_parameter_tuned_at_b11` (knob works,
coverage evidence survives the gate, `0`/`-1`/`361` refused, `1.5` a
`TypeError`).

**Seed C1** — the gate disabled (the F1 defect restored) on the scratch:
`test_a_silent_sensor_is_no_scan_not_a_clear_one` and
`test_min_populated_bins_is_a_profile_parameter_tuned_at_b11` — **2 failed**;
restored byte-identical (`4fbfcafd…7a9d`).

## F2 — absolute direction pins, and the two seeds that must now die

The verifier is right that every layout assertion derived its expectation from
`profile.bin_bearing_rad` and was therefore self-referential.

**Absolute indices used, derived from the sim and written as literals.** From
`mujoco_lidar.raycast_planar_scan`: `angle_min = -math.pi`,
`body_angles = angle_min + angle_increment * np.arange(num_rays)`,
`angle_increment = 2*pi/num_rays`, `num_rays = DEFAULT_SCAN_RAYS = 360` — so
the ray looking along body bearing `b` is `(b + pi) / increment`:

| body direction | point (m) | **bin index** | `ObstacleFix.bearing_rad` |
|---|---|---|---|
| dead ahead | `(2, 0)` | **180** | `0.0` |
| LEFT (+y, +pi/2) | `(0, 2)` | **270** | `+pi/2` |
| RIGHT (−y, −pi/2) | `(0, −2)` | **90** | `−pi/2` |
| behind | `(−2, 0)` | **0** | `−pi` |
| ahead-and-left | `(2, 0.2)` | **186** | `> 0` |
| ahead-and-right | `(2, −0.2)` | **174** | `< 0` |

`test_a_wall_lands_in_the_absolute_bin_the_sim_would_use` (4 params) asserts
`ranges_m[index] == 2.0`, that it is the ONLY populated bin, and
`fix.bin_index` / `fix.bearing_rad` against the literals.
`test_those_absolute_indices_are_the_sims_own_ray_order` re-derives
`(180, 270, 90, 0)` from the sim's formula with `DEFAULT_SCAN_RAYS` imported,
so literal and derivation can never drift.
`test_the_scan_runs_counter_clockwise_the_way_the_sim_does` was rewritten:
its first version compared the two returns to each other and, as the verifier
would predict, **passed under the mirror** — it now asserts the literals 186
and 174.

**Seed results (both must be RED, both are):**

* **C2a** `angle_min_rad` default -> `0.0`: **6 failed** — the layout-equality
  cell, all four absolute-cardinal cells, and the CCW cell. (Before this pass
  the same seed reddened 1 of 104 selected.)
* **C2b** consistent clockwise mirror — the verifier's three-site seed
  (binning `angle_min − atan2`, `bin_bearing_rad` and `ObstacleFix.bearing_rad`
  both `_wrap`-mirrored), which used to pass **144/144**: **3 failed** — LEFT
  (270), RIGHT (90) and the CCW cell. Front and behind lie on the mirror axis
  and are correctly invariant.

Both restored byte-identical (`4fbfcafd…7a9d`).

## F3 — the two refusals now state the true reason, and GPS is in the enum

Both formats stay REFUSED (out of scope for HW-3), with corrected words in
`_undecodable_reason`, the `LivoxDataType` docstring, the module docstring,
`DESIGN.md` §c (table rows + a correction note) and the "UNCONFIRMED" list
above:

* **SPHERICAL (0x03)** — "*DOCUMENTED but NOT DECODED in card HW-3 (out of
  scope, not unknown): `pub_handler.cpp:429-431` gives theta/phi in 0.01 deg
  and depth in mm. Configure the LiDAR for Cartesian output, or implement the
  spherical path and pin it against those lines.*"
* **DOUBLE_ECHO (0x11)** — "*DOCUMENTED but NOT DECODED in card HW-3 (out of
  scope, not unknown): `livox_lidar_def.h:174-185` defines
  `LivoxLidarDoubleEchoRawPoint` (2 x 14 B) and `pub_handler.cpp:469-482`
  decodes it. Which echo a band bin should take is a B11 question, not a
  decoder detail.*"

The `LivoxDataType` docstring now says the same for all three refusals and adds
why each is deferred rather than unknown. The test asserts the citation
strings and that the word `UNCONFIRMED` is **absent** from those messages.

`LivoxTimeType.GPS = 2` added (`comm.h:96-98`), `synchronised` is now true for
`GPTP` (1) and `GPS` (2) and false for `NO_SYNC` (0) and for any undocumented
value — pinned by
`test_gps_is_a_synchronised_clock_and_an_unknown_time_type_is_not`
(`0 -> False, 1 -> True, 2 -> True, 7 -> False`).

Also from F6: the DESIGN header table now reads "8 bytes in HOST order (LE on
x86_64/aarch64; the driver memcpy's them into a `uint64`,
`pub_handler.cpp:265-268`)" instead of calling `u64` a wire type.

## F4 — the L2 retirement gate is INERT, said plainly

No behaviour change (an unconditional raise in `__init__` would break
`adapter_for` for every adapter; one in `open_reader()` would redden the legacy
rig's own contract at `tests/test_capture_ingest.py:1615,1637,2459`, which is
not this card's to change). What changed is that the tree and both documents
now say so instead of implying a gate exists. The wording, in the `CARD HW-3`
region of `l2.py` and in `DESIGN.md` §b/§g:

> **The venue gate is INERT today.** Nothing passes `venue=`.
> `ingest/__init__.py:117-118 adapter_for` constructs every entry of
> `LIVE_ADAPTERS` as `factory()`, `orin_rehearsal.py:2072` does `L2Ingest()`,
> no `configs/profiles/` exists yet and no venue concept exists anywhere
> outside this card. The only effect reachable today is `RETIREMENT_NOTE`
> riding on `L2Ingest.notes`. The mechanism is here so the wiring is a
> one-argument change; the wiring belongs to **HW-5**, which owns the physical
> profile that names the venue, and the injection point is
> `ingest/__init__.py:117-118`.

`H3` in the original handoffs stands, now paired with this. For parcel-6c:
design §9's HW-3 row "unilidar path retired" should read "retirement gate
landed, inert until HW-5".

## F5 — the HW-2 handoff, corrected

My Finding 1 was right that `SimObservation` can never mint `PHYSICAL`, and
**imprecise** about the remedy. The verifier's sharpening, which supersedes the
last sentence of Finding 1 and of handoff H4:

`control/base.py:CommissionedStateSource` carries a `RobotMotionState` through
`latest()` — pose and controller feedback — **not a scan**. There is no typed
physical scan-evidence seam anywhere in the tree; `evidence_origin`'s own
docstring calls migrating `reactive_safety.py` onto one "a W0-F/W1 follow-up".
Measured by the verifier: under `requirements_requiring_physical_inputs()` a
band scan on `SimObservation(backend="go2")` yields
`LATCHED_STOP ['sim_fixture_forbidden']`, which is the CORRECT fail-closed
result, not a defect. So **HW-2 cannot reach a physical scan origin by routing
through `CommissionedStateSource`**: it needs a NEW typed scan-evidence source
that declares `EvidenceOrigin.PHYSICAL` on the datum, plus a runtime read of
it in place of `scan_evidence_from_observation` in
`runtime.py:_evaluate_dispatch_input_health`. Until that exists, `Go2Backend`
is observe-only by construction as well as by decision. The two replacement
sentences for design §4 S1 and §5.4 are in the verdict and are parcel-6c's to
land.

## F6/F7/F8 — notes

F6: the `version` refusal risk was already recorded (DESIGN §g.2) and stands;
the timestamp wording is fixed above. F7: the "27 rows" line was a `grep -c`
of matching lines, not runs — the correct statement is 14 START/END pairs at
that point (52 `label=hw3` lines / **26 runs** at the close of this pass, 7 of them on
the executor scratch); no `-n auto`, no tier, no 137. F8: the neighbour
counts differ because the verifier ran 4 files and I ran 9; both green.

## Command ledger (correction pass)

| What | Command | Result |
|---|---|---|
| own file | `pytest_guard.sh --label hw3 … -m pytest tests/test_hw3_mid360_band.py -q` | **156 passed**, 0.84 s |
| own + neighbours | `… -m pytest tests/test_hw3_mid360_band.py tests/test_no_arm_pin.py tests/test_capture_{envelope,ingest,sidecar,rehearsal,preflight}.py tests/test_clockmap.py tests/test_rosbag2_sidecar.py -q -n 8` | **1065 passed**, 17.2 s |
| seeds | `~/.cache/parcel-hw3/seed.sh` (single) and `seed_multi.sh` (multi-site), scratch rebuilt and `band.__file__` verified inside it | C1 2 failed · C2a 6 failed · C2b 3 failed · S1 3 · S2 2 · S3 1 · S5 2 — **all restored byte-identical** |
| lint | `.parcel/bin/ruff check <4 touched files>` | All checks passed; baseline 7, `noqa` 0 |
| 3.10 | `python3.10 ast.parse(feature_version=(3,10))` x6; `~/.cache/parcel-hw1/py310/bin/python` import + decode + band | ok; forbidden modules `[]` |

Scratch, harnesses and sha256 ledgers kept as evidence at
`~/.cache/parcel-hw3/{scratch,seed.sh,seed_multi.sh,seed_c1.json,seed_c2a.json,seed_c2b.json,tree_sha256.txt,tree_sha256_c.txt}`.
