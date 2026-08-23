# HW-5 `physical-profile` — STATUS (task_41, slug hw5)

Executor: Opus, wave-3b dispatch (session 31fcc2a0), 2026-08-23.
`DESIGN.md` 135 lines. `PREREGISTRATION.md` sha256
`38505fa29a5d0fc618994e7c30370723f8a99f28eb2587fdcefab646d58a645d` (frozen
before any measurement).

## Headline

`configs/robot.go2_edu_plus.yaml` exists, loads over the SHA-locked base, and
says what rig this is: the venue, the eye, the ear, the source of facts, the
Mid-360's band. Six new scalar keys, each refused by name when misspelled AT
THE LOADER — no read-site validator needed and none faked. The venue reaches
the capture lane, so HW-3's L2 retirement gate stops being inert: under this
profile `l2.cloud` and `l2.imu` move from served to unserved with the Mid-360
remedy in the message, and every other adapter is constructed byte-identically.
The profile carries no truth or oracle field, and a test greps it for thirteen
forbidden paths. On this desktop it REFUSES, naming the missing D455.

**R1–R12 MET, R13 MET (one unrelated failure, HW-7's in-flight `ci_gate.py`),
R14 half-met — the `ruff format --check` half is a pre-registration defect (see
Deviations D3).** Seven seeds RED on an import-verified scratch.

**Two findings the design owner must take.** (F1) `check_required_capabilities`
CANNOT be the desktop refusal the design describes, and (F2) the declaration
had to go under `configs/navigation/venues/` to keep CAP-1's own guard honest.
Both are in "Deviations and findings" below and in `DESIGN.md` §(g).

## What changed

`git diff --stat` (index vs working tree, this wave only):

```
 scripts/parcel_capture/ingest/__init__.py | 118 +++++++++++++++++++++++++++++-
 src/parcel_robot/config.py                |  95 ++++++++++++++++++++++++
 tests/test_prototype_profile.py           |  55 ++++++++++++++
 3 files changed, 266 insertions(+), 2 deletions(-)
```

Both deletions are inside marked regions: `return adapter` became
`return _venue_bound(factory, adapter)`, and `coverage()`'s
`except IngestRefusedError` became `except (IngestRefusedError,
IngestUnavailableError)`.

New files:

| file | lines | what |
|---|---|---|
| `configs/robot.go2_edu_plus.yaml` | 221 | the overlay; every forbidden field enumerated in its own header with the reason |
| `configs/navigation/venues/go2_edu_plus.yaml` | 289 | `default.yaml` with exactly two deltas: `semantic_source: learned_map`, and the eight `required_capabilities` |
| `tests/test_hw5_physical_profile.py` | 657 | 16 tests, R1–R12 |
| `scrum/20260822/task_41/{DESIGN,PREREGISTRATION,HW5_STATUS}.md` | — | this card |

The six new `OVERLAY_INTRODUCIBLE_KEYS` entries, in one `CARD HW-5` region:
`venue`, `backend`, `perception.lidar_band_min_m`,
`perception.lidar_band_max_m`, `perception.lidar_min_populated_bins`,
`perception.lidar_extrinsic_xyz_rpy`. `required_capabilities` is deliberately
NOT among them — see F1.

## How verified

Every pytest through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh
--label hw5 .parcel/bin/python -m pytest …`. No `-n auto`, no `ci_gate.py
--tier`, no background run, no simulator, no `runtime.py` edit and therefore no
lock taken. Pre-flight before every suite-scale run: 230 GB available, 0 other
pytest processes.

| row | result | evidence |
|---|---|---|
| R1 | MET | `ConfigStore(configs/robot.yaml, profile="go2_edu_plus")` loads; `venue=go2_edu_plus`, `backend=go2`, `navigation.config=configs/navigation/venues/go2_edu_plus.yaml`, `audio={'gateway': 'array'}`, band 0.10/0.60/1, extrinsic ABSENT |
| R2 | MET | `configs/robot.yaml` sha256 `f7b57dcd…d6c1` = the manifest's |
| R3 | MET | `check_overlay_keys(base, overlay)` returns; the six ⊆ `OVERLAY_INTRODUCIBLE_KEYS`; no entry under any of them; no `lidar` / `perception.lidar` subtree entry; every path the profile writes resolves in the base or is exempt at/above itself |
| R4 | MET | 6/6 one-character misspellings raise `ProfileError` naming the path through a real sibling overlay + `$PARCEL_PROFILE`; the correct spelling of each loads |
| R5 | MET | under the profile, `adapter_for(l2.cloud)` raises `IngestUnavailableError` naming `'go2_edu_plus'` and pointing at `parcel_robot.lidar`; `go2.sportmodestate` and `d455.color` still resolve |
| R6 | MET | with no profile, all 28 matrix channels: same adapter class and identical `__dict__` as `factory()`; unserved transports still raise `IngestRefusedError`; `L2Ingest().venue == 'go2_edu_addon_l2'`. Coverage census 23 served / 5 unserved with no profile, 21 / 7 under it — the delta is exactly `l2.cloud`, `l2.imu` |
| R7 | MET | `RobotRuntime(configs/robot.yaml, …).start()` under `$PARCEL_PROFILE` raises with the message quoted below; it is NOT a `CapabilityRefused`, i.e. the CAP-1 door one line earlier was passed |
| R8 | MET | declaration well formed, all eight names registered; the counterfactual (one line: `semantic_source: oracle`) raises `CapabilityRefused` naming `learned_map_source` with the table; unmodified, the runtime starts with `unmet_capabilities == []` |
| R9 | MET | none of the thirteen forbidden paths appears in the profile; `battery` and `simulation` in the merged result are byte-equal to the base's |
| R10 | MET | `ConfigStore(base, profile="")` `== yaml.safe_load(base)` exactly; `profile="prototype"` `== deep_merge(base, prototype)`; neither carries `venue`/`backend`. Merged digests (sorted safe_dump): none `cd6437b3…fcfb`, prototype `d869d98a…f73e`, go2_edu_plus `98998641…2eb7` |
| R11 | MET | `DECLARED_AHEAD` is exactly the five non-`venue` keys, each with its owed read site; the four `lidar_*` names appear in NO `.py` under `src/`, `scripts/`, `tools/` except `config.py`'s own region — a real negative; `web_panel.build_runtime` still constructs `MujocoSocketBackend(socket_path)` unconditionally, which is the line HW-2 replaces |
| R12 | MET | across `configs/navigation/**/*.yaml`, exactly one file declares, and it is `venues/go2_edu_plus.yaml` |
| R13 | MET (1 unrelated) | `test_hw5_physical_profile.py` 16 passed; `test_prototype_profile.py` + `test_cap1_admission.py` + `test_capture_ingest.py` + `test_truth1_texts.py` 175 passed; `test_no_arm_pin.py` + `test_capture_preflight.py` + `test_capture_envelope.py` + `test_release_parity.py` + `test_ci_gate.py` 496 passed / **1 failed**; `test_agent.py` + `test_capture_sidecar.py` + `test_capture_rehearsal.py` + `test_dynamic_prompting.py` + `test_fail_closed_limits.py` + `test_runtime_assets.py` + `test_roam1_behavior.py` + `test_unitree_control.py` + `test_venue1_physical_venue.py` 492 passed. **1,179 passed, 1 failed.** |
| R14 | half | `ruff check` on all four OWNS files: clean. Tree-wide 20 findings = the 7 baseline (`detection_adapter/sim_bridge.py`) + 13 in HW-2's in-flight files (`backends/go2.py` ×4, `camera_channel/*` ×4, `unitree_control.py`, `detection_adapter/noise.py`, `backends/__init__.py`, `task_40/evidence/`, `test_hw2_go2_backend.py`). **Zero from HW-5, zero `noqa` in any HW-5 file.** The `ruff format --check` half is NOT MET — see D3 |

The one R13 failure is `tests/test_ci_gate.py::test_the_json_summary_still_emits_when_the_first_evaluator_raises`, and it is **not this card's**: `scripts/ci_gate.py` carries 527 uncommitted insertions and was last written at 14:34 by the live HW-7 executor; the test seeds `evaluate_ruff` to raise and gets `status == "pass"` where it expects `"error"`. HW-5 touches neither `scripts/ci_gate.py` nor `tests/test_ci_gate.py`.

### The exact refusal on this desktop

```
camera venue 'realsense' was selected (PARCEL_CAMERA_BACKEND or
perception.camera_backend) and could not be opened. RealSenseUnavailable:
cannot start the RealSense pipeline: No device connected. RealSense devices on
the bus: none. Attach the D455 and re-run; `.parcel/bin/python -m
parcel_capture record --check` prints the device census and the attach remedy.
```

Raised by `runtime._venue1_open_failure` through `_venue1_attach_physical_ingress`, from `RobotRuntime.start()`, with the real shipped base, the real sibling overlay and `$PARCEL_PROFILE`. No product symbol monkeypatched (only `PARCEL_MEMORY_PATH`, `PARCEL_ONLINE_MAP_PATH` and `PARCEL_PROFILE`, which is how a profile is selected).

### Seeds

Byte-identical scratch at `~/.cache/parcel-hw5/scratch` (`rsync -a --exclude
.cache --exclude .parcel --exclude .git --exclude __pycache__` of `src/
scripts/ tools/ tests/ configs/ prompts/` + `pyproject.toml`), run with
`PYTHONPATH=<scratch>:<scratch>/src`; `import parcel_robot` verified to resolve
to `<scratch>/src/parcel_robot/__init__.py`; control run 16 passed; each seed
restored by sha256 and `__pycache__` purged; re-green 16 passed.

| seed | mutation | reddened |
|---|---|---|
| S1 | `adapter_for` reverted to plain `factory()` | `…retirement_gate_reachable` (1 failed) |
| S2 | `"venue"` deleted from `OVERLAY_INTRODUCIBLE_KEYS` | `…loads_over_the_sha_locked_base`, `…no_new_key_is_a_dotted_child` (2 failed) |
| S3 | profile `camera_backend: realsense` → `mujoco` | `…no_d455` (1 failed) |
| S4 | venue nav `required_capabilities` → `[]` | `…declaration_is_live…` (1 failed) |
| S5 | `battery.simulated_percent: 100.0` added to the profile | `…no_truth_or_oracle_field` (1 failed) |
| S6 | the four `lidar_*` scalars replaced by one `perception.lidar` subtree | `…no_new_key_is_a_dotted_child` + 4 misspelling arms (5 failed, 2 passed) |
| S7 | `_venue_bound` passes `"go2_edu_plus"` with no profile active | `…constructed_exactly_as_before` (1 failed) |

S6 is the one worth reading: it turns the six-scalar family into the subtree
the card's text suggested, and four of the six misspelling guards go dark
immediately. That is HW-4's D6 reproduced on demand.

## What it does not prove

* **That the declared capabilities BIND on the dog.** All eight bind on this
  x86 desktop (measured); the four soft-import rows are the ones that can
  genuinely be missing on aarch64 / CPython 3.10, and that is a box-day read.
* **Any number in the profile.** The band (0.10–0.60 m) is the design's opening
  value, `min_populated_bins: 1` is HW-3's default, and the extrinsic is
  ABSENT. B11 measures all three. The robot-LAN NIC and the array's PortAudio
  index are commented out for the same reason (B-con / Q-usb).
* **That `backend: go2` selects anything.** It has no reader (HW-2's).
* **That `audio.gateway: array` opens the array.** The realtime lane is off on
  this host, so the value is proved to MERGE and to be the spelling HW-4's
  `resolve_audio_gateway_selection` accepts; HW-4's own tests own the device.
* **The runtime under the profile end to end.** It refuses at the eye, by
  design — that is R7, and it means no run of the full profile exists.

## Deviations and findings

**D1 / F1 — the CAP-1 desktop refusal cannot exist as specified, and the card's
headline row is delivered a different way.** Card §Work 1 and design §4 S14 /
§5.8 / §9 all say `check_required_capabilities` refuses on this desktop because
the D455 is absent. Measured: `admission.REGISTERED_CAPABILITIES` contains
eight names, every one about the semantic-source axis
(`semantic_source_matches_config`, `learned_map_source`,
`learned_map_installed`, `poi_oracle_disabled`) or `navigation.pipeline`'s four
soft imports — no hardware row exists, and all eight BIND on this host
(`soft_import_health()` returns four `True`; a runtime under
`semantic_source: learned_map` admits the other four). A hardware capability
would be an `admission.py` change, which this card is forbidden ("declare,
don't change the check"). So the card's proof is delivered as two rows instead
of one: R7, the real refusal with the real profile, which is VENUE-1's and
names the D455; and R8, the declaration proved load-bearing by a counterfactual
whose only delta is one line of the navigation file. **Owed to parcel-6c:**
§4 S14's "first proof" column, §5.8's last sentence and §9's HW-5 acceptance
row each attribute the desktop refusal to CAP-1 and should attribute it to
`_venue1_attach_physical_ingress`.

**D2 / F2 — the declaration lives under `configs/navigation/venues/`.**
`tests/test_cap1_admission.py::test_startup_is_inert_when_nothing_is_declared`
asserts that every `configs/navigation/*.yaml` declares nothing. That glob is
non-recursive (`cities/`, `experiments/`, `models/` have always been outside
it). Putting the venue file at the top level would redden another card's test;
editing that test to exempt my file would weaken a guard I do not own. So the
file is under `venues/`, it is stated in three places (the file's header,
`DESIGN.md` §(g) F2, here), and HW-5 adds R12, which walks
`configs/navigation/**/*.yaml` recursively and asserts that EXACTLY ONE file
declares and names it — strictly more coverage than CAP-1's loop. **Handoff to
CAP-1's owner:** widen that loop's sentence ("no profile reachable without an
explicit venue overlay declares"), not its glob.

**D3 — R14's `ruff format --check` half is a pre-registration defect.** The row
was written before measurement and it measures the wrong thing: this tree has
never been `ruff format`-clean. `ruff format --check src/parcel_robot/
admission.py src/parcel_robot/web_panel.py` — two files this card does not
touch — reports both would be reformatted, and the diff on my own files lands
entirely in lines I did not write. HW-4's verifier recorded the same (their
F4). `ruff check` (the ratchet the gate actually runs) is clean on all four
OWNS files and adds zero fingerprints.

**D4 — a `venue` key rather than `configs/profiles/`.** Design §5.8 names
`configs/profiles/go2_edu_plus.yaml`. That path cannot load: `ConfigStore`
resolves a profile as the SIBLING `<base>.<profile><ext>`
(`config.profile_overlay_path`) and `config._PROFILE_NAME` refuses any name
containing a separator. The card README already had the correct spelling
(`configs/robot.go2_edu_plus.yaml`); the design sentence is stale.

**D5 — the key shapes moved, deliberately.** The card names a `lidar` key with
band / `min_populated_bins` / extrinsic inside it. Delivered as four flat
scalars under the existing `perception` parent, because an exempt subtree is
only honest once something validates it at the read site and this family's read
site is HW-2's, not mine — HW-4's D6 exactly. Seed S6 measures the difference.
The extrinsic is `xyz_rpy` (six reals), not a 4×4, for the reason in
`DESIGN.md` §(c).

**D6 — one extra marked region in a file the card did not enumerate.**
`coverage()` in `scripts/parcel_capture/ingest/__init__.py` caught
`IngestRefusedError` only, and a venue-retired adapter raises
`IngestUnavailableError` (a sibling, not a subclass), so the whole census died
on `l2.cloud` under the profile. Fixed in the same file, in its own `CARD HW-5`
region, by naming both arms rather than widening to `IngestError` —
`IngestContractError` is our own defect and must still crash the census.

**D7 — `tests/test_prototype_profile.py`** gained a marked `CARD HW-5` block in
the family-enumeration test (granted by the card; TRUTH-1/HW-4 precedent) and a
second marked block asserting the six scalars' guard behaviour beside the three
subtree families'.

## Handoffs

* **HW-2 (task_40).** You own the read sites for five admitted keys:
  `backend: go2` at `web_panel.build_runtime`, where
  `MujocoSocketBackend(socket_path)` is still constructed unconditionally; and
  `perception.lidar_band_min_m` / `_max_m` / `_min_populated_bins` /
  `_extrinsic_xyz_rpy` in `backends/go2.py` over HW-3's `parcel_robot.lidar`.
  `tests/test_hw5_physical_profile.py:DECLARED_AHEAD` is the list, and the test
  that pins their unreadness is what you edit when one lands. NOTE: `backend`
  is NOT `control.controller` — that key is the writer axis and
  `RobotRuntime.__init__` refuses any value but `simulator` without an injected
  `control_manager`.
* **parcel-6c (design owner).** F1 above: §4 S14 first-proof column, §5.8's
  last sentence, §9's HW-5 acceptance row. And D4: §5.8's `configs/profiles/`
  path is not loadable.
* **CAP-1's owner.** F2 above.
* **The integrator.** `configs/navigation/venues/` is a new directory and
  `configs/robot.go2_edu_plus.yaml` a new file; both must land in the same
  commit as the `config.py` and `ingest/__init__.py` hunks, or the profile
  refuses to load. `CODEBASE_INDEX.md` needs regenerating after the commit
  (three new tracked files); that is not this card's file to write.
* **HW-3.** Your F4 is closed: the venue gate has a caller. The inertness
  paragraph in `ingest/l2.py`'s `CARD HW-3` region ("nothing passes `venue=`…
  no `configs/profiles/` exists yet") is now stale in two sentences; it is your
  region, so it is your edit.

---

# Correction pass (19:xx EDT, 2026-08-23)

Verdict HOLD (`~/.cache/parcel-verify/hw5/VERDICT.md`): H1 blocking, F1 and F2
FIX, six NOTEs. All three taken, plus the integrator's four binding design
decisions. Nothing in the earlier sections is edited; where a claim changed it
is corrected below by name.

## H1 — the profile now speaks HW-2's vocabulary, and R11 is a call, not a grep

**What was wrong.** HW-2 (task_40) landed `web_panel._build_backend` at 14:45,
four minutes before HW-5's DESIGN was written, and `build_runtime` now calls
`_build_backend(store.section("backend"), socket_path)`. HW-2 reads `backend:`
as a SECTION with its own read-site validators. HW-5 shipped `backend: go2` as
a scalar, so `ConfigStore.section("backend")` raised a bare `TypeError` and the
profile could not be built through the launcher at all; the four
`perception.lidar_*` keys were admitted, merged and read by nothing; and R11's
`assert "MujocoSocketBackend(socket_path)" in panel` still passed because the
literal survived inside `_build_backend` — the guard written to notice HW-2
landing could not notice it.

**Profile.** `backend:` is now `kind: go2` + `band: {z_lo_m: 0.10, z_hi_m:
0.60, min_populated_bins: 1}`, nothing HW-2 does not read. `interface:` is
commented out for B9/B-con with the refusal it produces quoted beside it. The
extrinsic is ABSENT: `band_profile_from_config` accepts a 4×4 today, the
decided form is six reals `xyz_rpy`, and a key HW-2's validator would refuse is
worse than no key — so the NAME `backend.band.extrinsic_xyz_rpy` is a handoff,
not a line in the file. `fixture`, `domain_id`, `session_epoch` and
`max_frames_per_drain` are deliberately unset, each with its reason in the file.

**`config.py`.** The four `perception.lidar_*` entries are gone; the region now
carries two entries and says why they have different shapes — `venue` a scalar
whose guard is the loader, `backend` one entry exempting a subtree whose guards
are HW-2's two read sites. The retraction is written into the region so the
next reader does not re-derive the wrong premise.

**Tests.** `NEW_KEYS = ("venue", "backend")`; `DECLARED_AHEAD = {}` with the
retraction stated. R11 is replaced by two product-path rows plus a third:

* `test_the_profile_reaches_the_product_launcher_and_refuses_there` — real
  base, real sibling overlay, `$PARCEL_PROFILE`, `web_panel.build_runtime`;
* `test_a_backend_typo_is_refused_by_name_at_the_launcher` — `backend.kin`
  merges at the loader (asserted) and is refused at the read site, reached
  through `build_runtime` (TRUTH-1's F2 lesson: pin the CALL, not the function);
* `test_the_two_nic_keys_are_written_from_one_reading` — the profile sets
  `backend.interface` and `control.unitree_sport.interface` both or neither.

R1 now asks HW-2's own allow-lists rather than restating them
(`set(backend) <= _BACKEND_KEYS`, `band_profile_from_config(backend["band"])`
round-trips to 0.10 / 0.60 / 1), so a rename on HW-2's side reddens this row
instead of silently making the profile unreadable.

### The launcher refusals, measured

```
(a) shipped profile, zero monkeypatch
    Go2SdkUnavailable: the live Go2 source needs the robot NIC name
    (backend.interface); read it from `ls /sys/class/net` on the Orin

(b) same, with backend.interface: eth0 filled in as B-con will fill it
    Go2SdkUnavailable: unitree_sdk2py is not importable in this interpreter.
    The live Go2 backend runs in the MOTION venv on the Orin (design §3: the
    vendor SDK and rclpy must never share a process because CycloneDDS is
    process-global). On a desktop use a recorded fixture instead:
    `backend: {kind: go2, fixture: <path>.jsonl}`.

(c) backend.kin: go2 (a typo inside the exempt subtree)
    ValueError: unknown backend config key(s): kin; allowed: band, domain_id,
    fixture, interface, kind, max_frames_per_drain, session_epoch
```

**(b) is NOT the D455 refusal, and the dispatch's expectation that it would be
is worth correcting.** `_build_backend` runs before `RobotRuntime` is
constructed, so with the NIC set the launcher refuses one step later at
`LiveGo2Sources._probe_sdk` — the vendor SDK is not in the product venv on this
desktop and by design never will be. VENUE-1's D455 refusal (R7, unchanged) is
one layer down at `RobotRuntime.start()` and is reachable only once a backend
can be BUILT: on the Orin, or from a recorded fixture. Both are real; they
answer different questions, and design §9's "expected refusal" should say which
one it means (verifier N6).

## F1 — format measured properly, and D3 corrected

D3's sentence "the diff on my own files lands entirely in lines I did not
write" was true for `config.py` and `ingest/__init__.py` and FALSE for both
test files, and citing HW-4's F4 as agreement inverted it (F4 was a FIX). Ran
`ruff format` on `tests/test_hw5_physical_profile.py` (the whole file is this
card's) and reflowed the one `assert` in the `test_prototype_profile.py` HW-5
block. Measured the verifier's way — wave-ADDED lines ∩ format-REMOVED lines:

| file | wave-added | ruff would rewrite | of mine |
|---|---|---|---|
| `src/parcel_robot/config.py` | 91 | 6 | **0** |
| `scripts/parcel_capture/ingest/__init__.py` | 118 | 13 | **0** |
| `tests/test_prototype_profile.py` | 59 | 14 | **0** |
| `tests/test_hw5_physical_profile.py` | (new file) | 0 | **0** |

The tree-wide half of D3 stands and is the verifier's own measurement: `ruff
format --check` on `git show HEAD:` of all three shared files says three files
would be reformatted, so the tree has never been format-clean and the remaining
hunks are other people's lines.

## F2 — an unreadable profile is a refusal, never a stated gap

`active_venue()` wrapped `ProfileError` in `IngestRefusedError`, which is the
class `coverage()` and `preflight.default_reader_factory` both read as "this
transport has no reader, here is the stated reason". So `PARCEL_PROFILE=
go2_edu_plu` printed `served: 0  unserved: 28` and a remedy for twenty-eight
transports with the real reason discarded — contradicting the region's own
header. The wrap is gone: `active_venue()` raises whatever the config layer
raised. Measured on all four surfaces:

```
coverage()                     -> ProfileError: config profile 'go2_edu_plu'
dependency_report_text()          selected but .../configs/robot.go2_edu_plu.yaml
adapter_for(l2.cloud)             does not exist
preflight.default_reader_factory
```

`IngestContractError` still crashes the census (our own defect must not read as
a missing reader), and the correctly spelled profile still answers.

## Test counts (all through `pytest_guard.sh --label hw5`, `env -u TMPDIR`, no `-n`, no tier, no background, no sim)

| suite | result |
|---|---|
| `tests/test_hw5_physical_profile.py` | **16 passed** |
| `tests/test_cap1_admission.py` | 24 passed |
| `tests/test_prototype_profile.py` | 42 passed |
| `tests/test_hw2_go2_backend.py` | **45 passed** (HW-2 green with this profile) |
| `tests/test_capture_ingest.py` | 91 passed |
| `tests/test_capture_preflight.py` | 248 passed |
| `test_no_arm_pin` + `capture_rehearsal` + `capture_sidecar` + `capture_envelope` + `truth1_texts` + `venue1_physical_venue` | 402 passed |

**868 passed, 0 failed.** `ruff check` clean on all four OWNS files; tree-wide
12 = the 7 baseline (`sim_bridge.py`) + 5 in HW-2-adjacent files
(`camera_channel/*` ×4, `detection_adapter/noise.py`) — none HW-5's, and the
verifier's N5 count reproduced. Zero `noqa` in any HW-5 file. R13's earlier
`test_ci_gate.py` failure is gone (HW-7 moved that file at 15:00; N5).

## Seeds — re-run on a rebuilt import-verified scratch

`~/.cache/parcel-hw5/scratch` rebuilt from the corrected tree,
`parcel_robot.__file__` verified inside it, control 16 passed, every seed
restored by sha256 with `__pycache__` purged, re-green 16 passed, no `.orig`
left behind. Whole-file runs this time, not `-k` (verifier N4).

| seed | mutation | reddened |
|---|---|---|
| S1 | `adapter_for` reverted to plain `factory()` | 2 failed (retirement gate, F2 row) |
| S2 | `"venue"` deleted from `OVERLAY_INTRODUCIBLE_KEYS` | 10 failed |
| S3 | profile `camera_backend: realsense` → `mujoco` | 2 failed (R1, D455 refusal) |
| S4 | venue nav `required_capabilities` → `[]` | 2 failed (R8, R12) |
| S5 | `battery.simulated_percent: 100.0` added to the profile | 1 failed (no-oracle) |
| S7 | `_venue_bound` passes the venue with no profile active | 1 failed (flag-off identity) |
| **S8** | **`backend:` back to the pre-correction SCALAR — the H1 defect itself** | **9 failed**, including both launcher rows |
| S9 | `backend.kind: go2` → `mujoco` | 2 failed (R1, launcher row) |
| S10 | `active_venue()` re-wraps `ProfileError` as `IngestRefusedError` | 1 failed (F2 row) |
| S11 | B-con fills `backend.interface` and forgets the other NIC key | 2 failed (NIC pin, launcher row) |
| S12 | `"backend.kind"` listed beside `"backend"` (HW-4's D6 shape) | 1 failed (R3) |

S8 is the one to read: it restores exactly what the verifier found and nine
rows go red, including the two that could not see it before.

S6 of the first pass (the four lidar scalars replaced by a `perception.lidar`
subtree) is RETIRED — those keys no longer exist. Its lesson survives as S12,
which asserts the same property for the family that does: listing a CHILD of an
exempt parent looks like a spelling guard and is inert.

## Row corrections to the first pass

* **R11** is a different row: the launcher call, not the grep. The old row's
  sentence "`web_panel.build_runtime` still constructs
  `MujocoSocketBackend(socket_path)` unconditionally" was **false when written**
  (web_panel 14:45, STATUS 14:47) and is deleted.
* **`DECLARED_AHEAD` is empty.** The first pass's claim that five keys were
  "admitted ahead of the card that reads them" was wrong on both halves:
  `backend` had a reader, and the four lidar keys had no future one.
* **R10 unchanged and re-measured:** no-profile `cd6437b3…fcfb` and prototype
  `d869d98a…f73e` are byte-identical to the first pass. Only the go2 profile's
  digest moved, to `1f295051…b20a`.
* **R14** now reads: `ruff check` clean, zero `noqa`, and zero wave-added lines
  that `ruff format` would rewrite (table above).

## Handoffs after the correction

* **HW-2 (task_40).** (1) `backend.band.extrinsic_xyz_rpy` — six reals, the
  integrator's decided form; `band_profile_from_config` accepts a 4×4 today and
  the profile writes neither, so the change is yours to make in your own
  correction pass and nothing is blocked until B11. (2) `backend.interface` is
  now a documented box-day key with `control.unitree_sport.interface` as its
  twin; HW-5 pins that the profile writes both or neither.
* **parcel-6c (design owner).** §5.8's shape sentence becomes "`venue` (scalar)
  + `backend` (one-entry subtree, read-site-validated by HW-2)"; §9's expected
  first refusal is HW-2's `Go2SdkUnavailable`, not VENUE-1's D455 (both quoted
  above); §5.8's `configs/profiles/` path is still not loadable (D4); and the
  two NIC keys need one sentence saying they are two processes (N6).
* **CAP-1's owner.** Unchanged (F2 of the first pass / verifier N1): rewrite
  the inertness loop to assert by REACHABILITY and keep HW-5's R12 as the
  tree-wide allow-list pin.
* **HW-3.** Unchanged: `ingest/l2.py:90-98`'s inertness paragraph is stale in
  two sentences now that the gate has a caller. Its region, its edit.
* **N7, flagged not fixed.** An overlay can only set, never delete, so under
  this profile the merged mapping still carries the base's
  `battery.simulated_percent: 90.0`. Whether the runtime reads battery from
  config or from the backend under `Go2Backend` is HW-2's to state; the first
  dog run must not report a 90 % battery it never measured.

---

## Addendum (integrator decision from HW-2's verdict F6) — what this rig accepts as evidence

`PREREGISTRATION.md` Amendment 1 (dated, written before measurement) carries
rows A1–A4 and seeds S13–S15; the file's sha256 is now
`32f623dcdedce1977aa4ee7ea45349a8178a304c680ba951067a705e74ba9157`.

**The gap this closes.** `runtime.py:1707-1731` picks the requirements table
from `safety.require_physical_inputs`. It is absent from the SHA-locked base,
defaults False, and was NOT introducible — so no profile could set it and HW-2's
own tests have to write it into a modified copy of the base and say so
(`tests/test_hw2_go2_backend.py:179-183`). Under the physical profile that
meant `requirements_allowing_sim_fixtures()`: a REPLAY scan and a SIMULATION
pose SATISFIED the dispatch health join on a rig that is supposed to BE a robot.

### The key line in the profile

```yaml
safety:
  require_physical_inputs: true
```

Admitted as `"safety.require_physical_inputs"` in the `CARD HW-5` region of
`OVERLAY_INTRODUCIBLE_KEYS` — a scalar nested under a parent the base already
defines, so the loader descends into `safety:` and checks that exact path
itself (the C-1 `camera_ingress_rate_hz` shape; no read-site validator needed).

**The profile's `safety:` rule is now DIRECTIONAL, not a blanket ban**, and both
the file header and the test say so: every threshold in the section
(`obstacle_stop_m`, `obstacle_slow_m`, `person_stop_m`, `person_slow_m`,
`telemetry_stale_s`, `time_to_collision`) is forbidden because it could be
LOOSENED on a body nobody has braked; `require_physical_inputs` is allowed
because `true` can only make the join stricter. The test pins the whole block
as exactly `{"require_physical_inputs": True}`, so `false` is refused too — a
profile may not buy a looser join.

### Pin test names

| test | what it pins |
|---|---|
| `test_the_profile_loads_over_the_sha_locked_base_and_that_base_did_not_move` | `store.section("safety")["require_physical_inputs"] is True` (R1, extended) |
| `test_every_key_the_profile_writes_is_admitted_and_no_new_key_is_a_dotted_child` | the key ∈ `OVERLAY_INTRODUCIBLE_KEYS`, no dotted child of it (A1) |
| `test_a_misspelling_of_each_new_key_refuses_by_name_at_the_real_loader[safety.require_physical_inputs-safety.require_physical_input-overlay3]` | `safety.require_physical_input` refused BY NAME at the loader through a real sibling overlay (A1) |
| `test_the_switch_reaches_the_runtime_from_the_profile` | the VALUE arrives: real profile → `RobotRuntime._require_physical_inputs is True`; `web_panel.build_runtime` → `True`; no profile → `False` (A2) |
| `test_under_this_profile_a_replayed_scan_does_not_pass_the_join` | HW-2's B1a through HW-5's profile, plus the counterfactual (A3) |
| `test_the_profile_contains_no_truth_or_oracle_field` | the `safety:` block is exactly `{"require_physical_inputs": True}` (A4) |
| `test_introducible_keys_are_exactly_the_three_documented_families` (`test_prototype_profile.py`, `CARD HW-5` block) | the key in the family census; both spellings exercised |

### The launcher row — MEASURED (not skipped)

`backend.fixture` does let `_build_backend` succeed on this desktop (HW-2's
shipped `tests/data/hw2_stage0_replay.jsonl`), so the row is real. Through
`web_panel.build_runtime` with `$PARCEL_PROFILE=go2_edu_plus`, two trees
differing in ONE key of one file:

```
--- A  the profile as shipped (safety.require_physical_inputs: true)
    _require_physical_inputs = True
    scan origin              = EvidenceOrigin.REPLAY
    action                   = HealthAction.LATCHED_STOP
    faults                   = [('controller_feedback', 'missing'),
                                ('pose',  'sim_fixture_forbidden'),
                                ('scan',  'sim_fixture_forbidden')]

--- B  the same tree with that one key DELETED (the shipped default)
    _require_physical_inputs = False
    scan origin              = EvidenceOrigin.REPLAY
    action                   = HealthAction.HOLD
    faults                   = [('controller_feedback', 'missing')]
```

Arm B is the defect reproduced rather than described: the identical recording
satisfies both SCAN and POSE, and only the missing controller feedback holds.
That is exactly "a replay scan plus a SIMULATION pose PASS the join under the
physical profile".

**One timing note, recorded because it is a shared-tree fact and not a claim
about this card.** At 15:31 the row could not be measured — HW-2's
`backends/go2.py` was mid-correction (written 15:31:14; `Go2Backend.__init__`
raised `TypeError: commissioned scan source must expose a callable
scan_datum_for()`, and HW-2's own suite was 20 failed / 25 passed). It
completed at 15:32:21 and the row measured green immediately after. Two
consequences kept in the code: (1) `test_the_switch_reaches_the_runtime_from_the_profile`
deliberately does NOT depend on HW-2's physical construction — arm 1 is the
real profile through `RobotRuntime` with this file's own fake backend, arm 2 is
the launcher with `backend.kind` switched to `mujoco` in a tmp copy for that
stated reason — so the A2 claim stands on its own; (2) the A3 row carries
`_hw2_replay_backend_is_constructible()`, a NARROW precondition that asks only
whether HW-2's own fixture backend builds from HW-2's own fixture with no HW-5
input, and skips with that exact reason if it does not. It cannot excuse a
wrong profile, key or value — every one of those is asserted elsewhere with no
escape hatch — and it did not fire in the final runs.

### Counts (addendum re-run, all through `pytest_guard.sh --label hw5`)

| suite | result |
|---|---|
| `tests/test_hw5_physical_profile.py` | **19 passed** (16 + the 2 addendum rows + the split misspelling arm) |
| `tests/test_cap1_admission.py` | 24 passed |
| `tests/test_prototype_profile.py` | 42 passed |
| `tests/test_hw2_go2_backend.py` | **47 passed** (HW-2 green with this profile, after their 15:32 correction) |

**132 passed, 0 failed.** `ruff check` clean on all four OWNS files, zero
`noqa`; `ruff format --check` clean on `test_hw5_physical_profile.py`, and zero
wave-added lines in the other three would be rewritten (config.py 0 of 116,
ingest/__init__.py 0 of 118, test_prototype_profile.py 0 of 74). Tree-wide ruff
read 20 at the close, moving while HW-2 edits (`test_hw2_go2_backend.py` ×8,
`sim_bridge.py` ×7 = the baseline, `camera_channel/*` ×4,
`detection_adapter/noise.py`) — none HW-5's.

**R10 identity unchanged again:** no-profile `cd6437b3…fcfb` and prototype
`d869d98a…f73e` are byte-identical across all three passes. The go2 profile's
digest moved to `656fd9c1…9f3d`.

### Seeds S13–S15 (rebuilt import-verified scratch, control 19 passed, re-green 19 passed, all restored by sha256, no `.orig` left)

| seed | mutation | reddened |
|---|---|---|
| S13 | `"safety.require_physical_inputs"` deleted from `OVERLAY_INTRODUCIBLE_KEYS` | 12 failed (the profile stops loading at all) |
| S14 | profile value `true` → `false` | 3 failed: R1, the directional `safety:` rule, and the switch pin — i.e. buying a looser join is refused by name |
| S15 | the key deleted from the profile | 11 failed |

### What the addendum does not prove

That the requirements table is *right* — `requirements_requiring_physical_inputs()`
is board decision D-2's and untouched here. That a real Mid-360 scan passes it:
that is HW-2's B1b with an injected vendor boundary, and on the dog it is
box-day. And nothing here changes a threshold, an envelope or a gate; it
changes which evidence counts.

### Handoff added

**HW-2.** `safety.require_physical_inputs` is now introducible, so
`tests/test_hw2_go2_backend.py:169-195` `_config_tree` no longer has to write it
into a modified base and its comment ("`"backend"` is not in
`OVERLAY_INTRODUCIBLE_KEYS` yet — that entry is card HW-5's") is stale for both
keys. Your file, your edit.
