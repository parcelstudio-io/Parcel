# HW-2 `go2-backend` — STATUS (executor, Opus)

**Card** `README.md` · **DESIGN** `DESIGN.md` · **PREREGISTRATION**
`PREREGISTRATION.md` (sha256 `5e1646de12bbf523607102ed8b820958d120f888ce7a8d5103f2cfdda1233e55`
with Amendment 1; `3aa1eacb01ea95e5e421fbad3747f22ee6d79ac8ec3c3a28f66623da50892bfe`
before it — Amendment 1 was written BEFORE any row command was run and splits
row B1 only). First dispatch; nothing resumed.

## Headline

`Go2Backend` exists and is an **eye**: it composes the ODOM pose from a
recorded `rt/sportmodestate` and the scan from HW-3's Mid-360 band, and every
motion method refuses with the `docs/MOTION.md` citation. Through the real
`navigation/reactive_safety.py`, one recording drives the gate from `clear` to
`slowing` to `stopped` as a wall closes 2.00 m → 0.85 m, and a tick that drains
no frames publishes **no scan** (`lidar_ranges=()`), which HOLDs.

The part that is not a port: **a scan can now carry physical authority through
a TYPED source instead of a string.**
`core/input_health.py:CommissionedScanSource` is the scan twin of
`control/base.py:CommissionedStateSource` — it stamps the commissioned origin,
keeps the producer's clocks and sequence, and LATCHES on an ordering fault —
and `runtime.py:_evaluate_dispatch_input_health` reads it instead of
`scan_evidence_from_observation` when, and only when, `declared_origin` says
PHYSICAL. Measured at the join: the `scan:sim_fixture_forbidden` fault is gone
for a live-source `Go2Backend` and still latches for a sim scan **and for a
recorded fixture** — because the fixture source declares REPLAY *by
construction*, and no config key can launder a file into a sensor.

45/45 new tests; 561 neighbour tests green; 7 seeds RED on an import-verified
scratch; imports and runs on real CPython 3.10.21; zero new ruff findings.

## What changed

New files:

| File | Lines | What |
|---|---|---|
| `src/parcel_robot/backends/go2.py` | 816 | `Go2Backend`, `RecordedStage0Source`, `LiveGo2Sources`, `Go2MotionRefused`/`Go2SdkUnavailable`/`Go2ReplayError`, `band_profile_from_config` |
| `tests/test_hw2_go2_backend.py` | 1,292 | 45 tests, rows A/B/C/D/E |
| `tests/data/hw2_stage0_replay.jsonl` | 37 | the SYNTHESISED fixture, sha256 `454f10132ccbedece933cfcb26faf63483c9c875ca6a967bd01f29d28d2aaa63` |
| `scrum/20260822/task_40/evidence/make_stage0_fixture.py` | 155 | its deterministic generator |
| `scrum/20260822/task_40/{DESIGN,PREREGISTRATION,HW2_STATUS}.md` | — | this card's record |

`git diff --numstat` on the shared files (index → worktree; the wave-3 edits.
`runtime.py` and `web_panel.py` also carry other cards' hunks — HW-1's import
line and HW-4's gateway branch in `runtime.py`, HW-MIC's two regions in
`web_panel.py` — which are NOT mine and are excluded from the descriptions):

| File | +/− | Mine |
|---|---|---|
| `src/parcel_robot/core/input_health.py` | +191/−0 | all of it: `ScanDatum`, `ScanEvidenceSource`, `CommissionedScanSource`, two marked import lines, two `__all__` entries |
| `src/parcel_robot/bridge/timing.py` | +671/−0 | 201 lines, the `CARD HW-2` region AFTER `# ---- END CARD HW-6 ----` (the other 470 are HW-6's, unstaged) |
| `src/parcel_robot/web_panel.py` | +208/−2 | 98 lines: `_BACKEND_KEYS`/`_BACKEND_KINDS`/`_build_backend` + the one branch at the `RobotRuntime(...)` call |
| `src/parcel_robot/runtime.py` | +93/−7 | 35 lines: one region inside `_evaluate_dispatch_input_health` |
| `src/parcel_robot/unitree_control.py` | +85/−1 | all of it: `--duration` (HO-6) |
| `src/parcel_robot/backends/__init__.py` | +18/−0 | all of it: the marked export |
| `configs/envelope/{default,jaewoo-jang-parcel}.yaml` | — | UNTRACKED (HW-6's new files): each gains a trailing `scan_age:` block |

Every hunk in a shared file lies inside `# ---- CARD HW-2 … ---- / # ---- END
CARD HW-2 ----` markers or is a marked single import line. **Nothing inside
HW-6's fence (`bridge/timing.py:183-634`) moved a byte**. `git diff --stat` is
EMPTY for `backends/mujoco.py`, `backends/base.py`, `navigation/reactive_safety.py`,
`core/hard_stop.py`, `commissioning/`, `lidar/`, `control/`,
`tests/test_hw6_stopping_envelope.py` and `tests/test_w0b_commissioning.py`.
`scripts/ci_gate.py` (+542) and `config.py` (+95) ARE dirty in this tree, and
every added marker in them reads `CARD HW-4`, `HW-5`, `HW-6` or `HW-7` — none
is HW-2's.

Locks taken and released, one short Edit pass each:
`~/.cache/parcel-batchb/lock-runtime.py`, `lock-web_panel.py` (owner file
inside, `rmdir` after). No locks held at close.

## How verified

Every pytest ran through
`env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw2 .parcel/bin/python -m pytest …`.
**35 guarded runs**, all `label=hw2`; no `-n auto` (the one `REFUSED -n auto`
line in `guard.log` is parcel-6c's 06:14 self-test), no `ci_gate.py --tier`, no
background pytest, no exit 137, no simulator started, nothing on `:8765` or
`/tmp/parcel_sim.sock`, `PARCEL_MEMORY_PATH` redirected to `tmp_path` in every
runtime test. Pre-flight before each suite-scale run: 230 GB available, 0
pytest processes.

### Rows

| Row | Verdict | Result |
|---|---|---|
| A1 `scan_present` from the fixture | MET | 360 ranges, `points_seen > 0`, real `reactive_safety.scan_present` True; pose z = 0.32 from the recorded state |
| A2 the band drives the real gate | MET | clearances `1.68, 1.68, 1.28, 0.88, 0.63, 0.53` → `clear, clear, clear, slowing, stopped, stopped` through the real `apply_reactive_safety` at 0.25 m/s |
| A2′ travel bearing | MET | `travel_bearing_rad(0, 0.4) = +π/2` handed to `nearest_obstacle_from_scan`; the corridor excludes the wall and the global fallback returns it |
| A3 empty band → no scan | MET | `lidar_ranges == ()`, `nearest_obstacle_m is None`, `scan_present` False, `latest_scan() is None`, gate `stopped` |
| A4 motion refused | MET | 5 methods raise `Go2MotionRefused` (also `NotImplementedError`), message carries `MOTION.md` |
| A5 the stop path never raises | MET | `stop`/`emergency_stop`/`clear_emergency_stop`/`expression` return None; a real `BackendVelocityController(Go2Backend)` completes activate/stop/e-stop/close |
| A6 no vendor import at module scope | MET (measured, restated) | fresh `-I` interpreter: `unitree_sdk2py`/`mujoco`/`rclpy`/`numpy` absent; `parcel_robot.core` and `parcel_robot.control` absent; `socket` present, from the sibling `backends.mujoco` |
| A6′ commissioning stays light | MET | the W0-B chain through `backends` → `go2` leaks no `runtime`/`navigation`/`brain`/`instructnav` |
| A7 live adapter names the venv | MET | `Go2SdkUnavailable`, message names `unitree_sdk2py` + the MOTION venv + the fixture alternative |
| A8 Protocol satisfied | MET | every `SimulatorBackend` method callable; `isinstance` raises (not `runtime_checkable`), pinned |
| A9/A10 broken/synthesised fixture | MET (extra) | 6 malformed recordings refused; the header says `synthesised: true` |
| **B1a** replay does NOT mint authority | MET | through `web_panel.build_runtime`, zero patches: `scan:sim_fixture_forbidden` present, verdict LATCHED_STOP |
| **B1b** the authority row | MET | `RobotRuntime(config, Go2Backend(LiveGo2Sources(injected transports)))`: **no SCAN fault at all**; evidence origin PHYSICAL, no fixture label |
| B2 a sim scan still latches | MET | control: `scan:sim_fixture_forbidden`, LATCHED_STOP |
| B3 what this card does NOT buy | MET | verdict still LATCHED_STOP for `pose:sim_fixture_forbidden`; `controller_feedback:missing`; `translation_allowed` False |
| B4 empty scan HOLDs | MET | the only SCAN fault is `missing`, action HOLD |
| B5 undeclared origin refused | MET | UNKNOWN, a `str`, a missing `latest_scan`, an unlabeled REPLAY and a labeled PHYSICAL all refused at construction |
| B6 the ordering latch | MET | 4 faults × (fault tick + 3 clean ticks still invalid) |
| B7 a string is not a declaration | MET | `origin = "physical"` is not read; the join falls back and latches |
| B8 / C2 flag-off identity | MET | `MujocoSocketBackend`, `scan_evidence_source` absent, faults exactly `{controller_feedback:missing}`, action HOLD |
| C1 selection | MET | `Go2Backend` with the config's band profile and session epoch |
| C3 unknown key refused (×2) | MET | `backend.fixtur`, `backend.bandd`, `backend.band.z_lo` each refused BY NAME |
| C4 unknown kind refused | MET | names `mujoco` and `go2` |
| C5 overlay selects the backend | MET | `$PARCEL_PROFILE` overlay flips mujoco → go2; and the loader still refuses an overlay that INTRODUCES `backend` (HW-5's entry) |
| D1 `--duration` absent by default | MET | one window, stdout JSON == `evidence.as_dict()`, no summary |
| D2 duration runs windows | MET | 3 windows over 2.5 s (fake clock), worst interval 0.044, modes `[1, 3]` |
| D3 refusal propagates | MET | rc 1, observer closed |
| D4 non-positive refused | MET | `0`, `-1`, `nan`, `inf` all `SystemExit` at parse time |
| E1 the sixth term is in the sum | MET | six contributions to 1e-12; `required − five-term required == v·scan_age` exactly |
| E2 UNMEASURED poisons | MET | state UNMEASURED, `missing == ("scan_age_s",)`, no number; negative and provenance-less refused |
| E3 both records carry it | MET | UNMEASURED + provenance naming `Go2Backend.latest_scan_age_s()` and box-day B11 |
| E4 HW-6's V1 untouched | MET | `ENVELOPE_TERMS_V1` still the five; both files still load as V1; the dev-box missing set is still the same three |
| E5 record without the term | MET (extra) | V1 reads it, V2 refuses it |
| E6 RC-4 byte-identical | MET | `466cad1f…`, `2a2927d5…`, and the pins re-read from HW-6's own test file |
| E7 the gate row is unchanged | MET (a DECLARED LIMIT, pinned) | `ci_gate.py` still calls `derive_envelope_rows`; the test says what to do when that changes |
| E8 the term has a measurer | MET (extra) | `latest_scan_age_s()` returns None → 0.0 → 0.037 |
| F1 ruff | MET / PARTIAL | `ruff check` on all OWNS: **All checks passed**. Tree-wide fingerprints are **exactly the 7 baseline entries**; zero `noqa` anywhere in my files. `ruff format --check`: my three own files are clean; see deviation D3 |
| F2 neighbours | MET | 561 passed across 10 suites (HW-6 30, HW-3 156, W0-A, `test_control`, `test_no_arm_pin`, prototype profile, HW-4, `test_ci_gate` 91, core input-health, pose-health) + 328 across web_panel/TRUTH-1/fail-closed/CAP-1/W0-B/this file |
| F3 marked regions | MET | every shared-file hunk fenced; other cards' regions untouched |
| F4 CPython 3.10 | MET | `~/.cache/parcel-hw1/py310/bin/python` 3.10.21: `backends.go2` imports with none of `unitree_sdk2py/mujoco/rclpy/numpy`; a full `observe()` returns 360 ranges and nearest 1.68; the V2 envelope record loads |

### Seeds — all RED on a byte-identical scratch, restored by sha256

Scratch `~/.cache/parcel-hw2/scratch` (`rsync -a` of `src/ scripts/ tools/
tests/ configs/ prompts/`), run with `PYTHONPATH=<scratch>:<scratch>/src`, and
`tests/test_hw2_scratch_guard.py` asserts **from inside pytest** that
`parcel_robot.__file__` is inside the scratch (the editable `.pth` otherwise
imports the working tree). `__pycache__` purged before and after each seed.

| Seed | Mutation | Reddened |
|---|---|---|
| S1 | the empty `BandScan` is copied across (`if not scan.ranges_m:` → `if False:`) | `a3_empty_band_is_published_as_no_scan`, `b4_an_empty_scan_holds_at_the_join` (2 failed) |
| S2 | the runtime believes any scan source (drop `declared_origin(...) is PHYSICAL`) | `b7_a_string_is_not_a_declaration` (1) |
| S3 | `CommissionedScanSource` stops latching | `b6_…latches_on_an_ordering_fault` ×4 (4) |
| S4 | `move()` becomes a no-op | `a4_motion_is_refused_with_the_motion_md_citation` (1) |
| S5 | go2 selected whenever a section resolves | `b2_a_sim_scan_still_latches`, `b8_flag_off_identity` (2) |
| S6 | the scan-age contribution is dropped | `e1_the_sixth_term_is_in_the_sum` (1) |
| S7 | the `backend:` key guard is deleted | `c3_an_unknown_backend_key_is_refused` (1) |

Control run on the restored scratch: **46 passed** (45 + the scratch guard).

## What it does not prove

* **No robot and no LiDAR exist on this host.** The fixture is SYNTHESISED and
  says so in its own header line; box-day HW-9 falsifies both the
  `SportModeState` field names and the Livox datagram in one capture. Nothing
  here is evidence about a Go2.
* **Pose authority is not in this card.** `evidence_origin` still stamps POSE
  SIMULATION, so a `Go2Backend` runtime still LATCHES — for pose. The card's
  claim is per-FAULT (`scan:sim_fixture_forbidden` gone) and B3 pins the rest.
* **`scan_age_s` is UNMEASURED on this host** and the sixth term is not
  gate-printed (deviation D1).
* **The `backend:` key is inert in production until HW-5** (deviation D2).
* The live adapter has never opened a real DDS subscriber or a real UDP socket;
  its transports were injected. `UnitreeChannelContext`'s NIC check, the SDK
  import and the real `receive_frames` socket path are Stage-0 rows (S19).
* `--duration` was exercised against a `CommissioningObserver` stand-in; the
  observer itself is `tests/test_w0b_commissioning.py`'s and was not edited.

## Deviations

* **D1 — the sixth envelope term is an additive V2 layer, not a sixth field on
  `StoppingEnvelopeInputsV1`, and it is NOT gate-printed.** The card asked for
  `StoppingEnvelopeInputsV1.scan_age_s`, "the two record files gain the key",
  and "HW-6's tests still pass". **Measured: those cannot all hold.** Adding
  `scan_age_s` to `ENVELOPE_TERMS_V1` reddens five assertions in
  `tests/test_hw6_stopping_envelope.py` — `_inputs()` (:303) supplies five
  terms, so a sixth makes every arithmetic row UNMEASURED, and :683 pins the
  dev-box record's missing set at exactly three names. That file belongs to a
  CLOSED, verified card and is outside this card's OWNS. So: a `CARD HW-2`
  region AFTER `# ---- END CARD HW-6 ----` defines `ENVELOPE_TERMS_V2`,
  `StoppingEnvelopeInputsV2`, `derive_envelope_v2`,
  `load_stopping_envelope_record_v2`; the records carry the term in a
  **top-level `scan_age:` block** that V1's loader ignores by construction, so
  both files remain valid V1 records. Consequence, stated rather than hidden:
  `scripts/ci_gate.py:evaluate_stopping_envelope` still prints the five-term
  row. Wiring it is one call swap plus those five assertions, and it needs
  leave from the dispatcher (`ci_gate.py` is HW-7's file in 3b). Test `e7`
  pins the limit so it cannot be forgotten.
* **D2 — the `backend:` selection key is INERT in production until HW-5.**
  `configs/robot.yaml` is SHA-locked and omits `backend:`, so an overlay cannot
  introduce it until `"backend"` is in `config.OVERLAY_INTRODUCIBLE_KEYS` (ONE
  entry, whole subtree — the ROAM-1/TRUTH-1 rule). `config.py` is HW-5's in
  wave 3b. This is HW-3's finding F4 in the same shape and is stated in the
  code, in DESIGN §c and in test `c5_the_overlay_still_refuses_an_unknown_key`,
  which asserts today's refusal AND passes once HW-5 lands. The read-site
  spelling guard (`_check_backend_section`'s vocabulary) is in place now.
* **D3 — `ruff format --check` is not clean on three shared files, and was not
  clean before this card.** `core/input_health.py`, `web_panel.py` and
  `runtime.py` fail it in the index too (613 of 1,805 files fail it tree-wide;
  `ruff format` is NOT in `ci_gate.py`). My three own files are formatted.
  `bridge/timing.py`'s single deviation is at :318, inside HW-6's fence.
  `unitree_control.py` and `backends/__init__.py` were clean and still are.
  Reformatting the shared files would rewrite other cards' code.
* **D4 — PREREGISTRATION Amendment 1 (row B1 split), written before any row
  command ran.** Two scratchpad probes (`probe_join.py`, `probe_live.py`) were
  run first to validate the design; they are named in the amendment and no row
  is claimed from them. The reason for the split is a fact about the tree, not
  about the implementation: `build_runtime` on this desktop can only produce a
  REPLAY-fed backend, and REPLAY is a synthetic origin. Meeting the row as
  literally written would have required a config key that mints PHYSICAL for a
  file — the W0-A defect. B1a and B1b both MET.
* **D5 — two cross-card guards were tripped and fixed during the card, both by
  the `backends/__init__.py` export.** (i)
  `test_w0b_commissioning.py::test_importing_commissioning_does_not_import_the_runtime`:
  a module-scope `from parcel_robot.core.input_health import …` in `go2.py`
  dragged `brain`/`instructnav`/`navigation` into the armed commissioning
  tool's import chain. Fixed at the source — `EvidenceOrigin` now comes from
  the leaf module card W0-A carved out for exactly this, and the two health
  types are imported inside the functions that use them (the same idiom
  `runtime.py:_evaluate_dispatch_input_health` already uses). (ii) W0-B's
  GATE 5 refuses even a dotted mention of that package outside its seam; two
  comments in `go2.py` were reworded. Both are pinned by
  `test_a6_importing_commissioning_stays_light`.
* **D6 — `DESIGN.md` is 224 lines against the ≤ 150 target**, because §(f) and
  §(g) each record an obstruction the card did not anticipate and the shape
  chosen instead; both are decisions a verifier must be able to re-derive.
  **It was edited in this same pass** where implementation moved the design
  (the COMMON brief's rule): the constructor takes ONE source rather than two,
  the origin is declared by the source's construction rather than configured,
  the read-site guard is `_BACKEND_KEYS`/`band_profile_from_config` rather than
  a single `_check_backend_section`, `evidence()` takes no argument, §(c) now
  records the `core`/`control` import discipline D5 forced, and §(d) now says
  that a REPLAY fixture still latches.
* **D7 — `stop()`/`emergency_stop()`/`clear_emergency_stop()` do NOT raise.**
  A judgment call, argued in DESIGN §c and in the code: `control/adapters.py`
  calls `backend.stop()` on its startup, stop, emergency-stop and close paths,
  and an eye that threw there would convert a safe no-op into an exception on
  the safety path. The backend never commanded anything, so "stop" is
  truthfully nothing to do.

## Owner-gated / box-day rows (never claimed)

| Row | Command |
|---|---|
| The live `Go2Backend` against a real `rt/sportmodestate` | Stage 0 on the Orin, `docs/BOX_DAY.md` S19 — `python3 -m parcel_robot.unitree_control observe --duration 60` in the MOTION venv |
| The live band against a real Mid-360 | box-day B11 (extrinsic + `min_populated_bins` tuning), then `backend: {kind: go2, interface: <NIC>}` |
| `scan_age_s` | p99 of `Go2Backend.latest_scan_age_s()` under load on the Orin; replaces the UNMEASURED entry in `configs/envelope/<host>.yaml` |

## Handoffs

* **HW-5 (blocking for the product path, one line + the profile):** add
  `"backend"` to `config.OVERLAY_INTRODUCIBLE_KEYS` — ONE entry exempting the
  whole subtree; the read-site guard is already in `web_panel.py`. Then
  `configs/profiles/go2_edu_plus.yaml` sets
  `backend: {kind: go2, interface: <NIC>, band: {...}}` and
  `safety.require_physical_inputs: true`. Also HW-3's must: pass `venue=` at
  `ingest/__init__.py:117`.
* **HW-7 / the dispatcher:** wiring the sixth envelope term into the gate is
  `evaluate_stopping_envelope` → `derive_envelope_rows_v2` +
  `load_stopping_envelope_record_v2`, plus five assertions in
  `tests/test_hw6_stopping_envelope.py` (:303 `_inputs()`, :317 arithmetic,
  :344 exact-envelope, :640 VALID_RECORD rows, :683 the dev-box missing set).
  Both files are outside HW-2's OWNS. See deviation D1.
* **POSE authority (unowned, the obvious next card):** a pose-evidence source of
  the same shape as `CommissionedScanSource`, read in the same `CARD HW-2`
  region. Until it exists a `Go2Backend` runtime LATCHES on pose, which is the
  correct fail-closed state but means the dog cannot translate even with a real
  scan. `Go2Backend` already holds the real ODOM datum.
* **`parcel_robot.core` is not a leaf** (found by D5): importing anything from
  `core/input_health.py` executes `core/__init__.py` → `core.motion_shaping` →
  `parcel_robot.navigation` → `brain`/`instructnav`. Card W0-A solved this once
  for `EvidenceOrigin` by carving out `parcel_robot/evidence_origin.py`. The
  health vocabulary (`InputEvidence`, `RequiredInput`, `ScanDatum`) deserves the
  same treatment; every boundary module now pays a lazy import instead.
* **`SimObservation` has no scan-age field**, so `latest_scan_age_s()` is read
  off the backend rather than off the observation. `backends/base.py` is not in
  this card's OWNS; a later card may want the field.

## Verifier — what to look at first

1. **`test_b1b_the_join_no_longer_latches_the_scan` and
   `test_b1a_the_join_does_not_believe_a_replay` together.** They are the card.
   Check that the origin really is declared by construction
   (`RecordedStage0Source.origin = REPLAY`, `LiveGo2Sources.origin = PHYSICAL`,
   neither reachable from config) and that B1b's only double is the vendor
   transport. If a config key can reach PHYSICAL, the card is wrong.
2. **`runtime.py`'s region** (`_evaluate_dispatch_input_health`, one hunk):
   that `declared_origin` is the typed lookup, that `evidence()` can only make
   the verdict stricter or equal, and that `MujocoSocketBackend` cannot reach it.
3. **Deviation D1** — the V2 layer. Confirm `bridge/timing.py:183-634` is
   byte-identical to HW-6's verified state, that both records still load as V1
   with HW-6's own missing sets, and judge whether the gate-wiring gap should be
   closed in a correction pass (it needs leave to touch `ci_gate.py` and HW-6's
   test file).
4. **The empty-scan branch** (`A3`, `B4`, seed S1) — HW-3's F1 lesson lands here.
5. `guard.log` rows `label=hw2`: 35 runs, 24 with rc≠0 = the 7 seed runs (RED by
   design) plus iterative development failures; no 137, no `-n auto`, no tier.

---

# Correction pass (19:xx; host clock 2026-08-23 15:2x–16:0x EDT)

Verifier verdict **HOLD** (`~/.cache/parcel-verify/hw2/VERDICT.md`): two product
defects inside HW-2's own contract (H1, H2), seven FIXes, twelve NOTEs. Both
HOLDs were reproduced through a real `RobotRuntime`; both are one design change.
`PREREGISTRATION.md` **Amendment 2** was written BEFORE any corrected-code row
was measured, and re-cuts row B6 and seed S3 honestly rather than quietly.
sha256 `57fe2c7dc4f64c5c0c59d84453318635411c92dfb824735871557d54b5e8a9ee` as
first written, `a2022433b015b3a5d1c5be37e43a46d24e94c01e13d846a64a3cb1334de5f0b4`
final — the one edit between them is the verifier's N2 (stamp the amendment
with `date` output, host clock `Sun Aug 23 03:29:06 PM EDT 2026`); no row,
threshold or seed text moved. Both shas are recorded so the ordering is
checkable: `PREREGISTRATION.md` mtime **15:29:22**, first corrected-code
`label=hw2` guard row **15:35:02**.

## H1 + H2 — one change: the datum travels with the observation it graded

The defect was one assumption — *"this view is read once per tick, on the
current observation"* — and the runtime does neither.

* `Go2Backend.scan_datum_for(observation)` returns the `ScanDatum` built from
  the frames that produced THAT observation's `lidar_ranges`, identity-keyed
  over a bounded history (`GRADED_HISTORY = 8`; an unbounded map keyed on
  observations leaks in a process that runs for days). `observe()` is now
  serialized by a lock (verifier N4: the loop and HTTP handler threads drain one
  socket and raced on the sequence counter).
* `CommissionedScanSource.evidence(key)` takes the key; the runtime region
  passes the observation it is grading. **Two preconditions, both load-bearing:**
  `scan is not None` (the source may RE-STAMP the origin of a scan the
  observation carries, never supply presence it lacks) and the keyed read (the
  join cannot grade observation N against sweep N+1).
* `_ordering_fault` exempts an identity — or full field-equality — re-read of
  the datum it already accepted, exactly as `control/base.py
  :CommissionedStateSource` does and for the same measured reason. A DIFFERENT
  datum under a repeated sequence still latches.

## Rows (all through the wrapper; the four required suites green)

| Row | Verdict | Result |
|---|---|---|
| **H1a** one corrupt datagram costs one datagram | MET | `[good, corrupt, good]` in one drain → 2 frames delivered, `refused_datagrams == 1`, **socket empty** (the good datagram behind the corrupt one is no longer abandoned); three ticks joined through the real runtime → no `payload_malformed` on any, `latched_reason is None` |
| **H1b** the operator can clear the latch | MET | `clear_input_health_latch()` on the runtime's own `_observation`, twice → `_input_health_latched` False, no `scan:payload_malformed`, `latched_reason is None`. Run on the DEFAULT table, which is what any shipped profile actually gets today (F6) — the clear can then succeed, which is what makes "it clears" observable |
| **H2a** stricter-or-equal, enumerated | MET | four cases measured with AND without the source through the real `scan_evidence_from_observation` + `evaluate_input_health` on the runtime's own requirements table: `missing` → (`missing`/HOLD, `missing`/HOLD) — never cleared; `sim_fixture_forbidden` (REPLAY source) → identical both ways; `payload_malformed` (latched source) → severity(with) ≥ severity(without); `ok` → the ONE permitted relaxation, `sim_fixture_forbidden` cleared on an observation that already carries a scan |
| **H2a′** a source that answers anything | MET | added because seed S8 did NOT redden on the first attempt: `Go2Backend` records no datum for a scan-less observation, so the keying alone already produced `missing` and the region's `scan is not None` precondition was an INERT guard. It is now exercised against the case it exists for — a scan-evidence source that answers for every key (a different, buggy or hostile backend) — and S8 reddens exactly this row |
| **H2b** a later sweep cannot grade an earlier observation | MET | the verifier's reproduction: sweep → empty tick → sweep, then join the EMPTY one → `scan:missing`, HOLD; each observation still grades against its own datum and the two data are distinct objects |
| **F2a** no fabricated pose | MET | `Go2StateUnavailable` (a `RuntimeError`, which is what the runtime's `except` around `observe()` catches → `observation=None` → HOLD); message names `rt/sportmodestate`; the refused tick does NOT consume frames (the state is read BEFORE the drain) |
| **F3a** the live scan transport | MET | `backend.livox: {host, port}` → `open_livox_socket` binds a real non-blocking UDP socket (`gettimeout() == 0.0`); `livox.hostt` refused BY NAME; `fixture` + `livox` together refused ("two different sensors"); port out of range refused; an injected BLOCKING socket refused at construction; an endless socket is cut off by `drain_budget_s` (2 frames, not an infinite loop); a quiet sensor → `()` |
| **F5a** the declaration is visible | MET | `input_health_latch()` carries `scan_source_origin`/`scan_source_name`: `replay`/`go2_stage0_replay`, `physical`/`go2_live`, `None`/`None` for the sim backend. `SimObservation.backend` is the source's name too |
| **B6** (re-cut) | MET | four ordering faults still latch across three clean ticks; **identity and equality re-reads do not** (new sub-rows, both parametrisations) |
| A/B/C/D/E (re-run) | MET | 55 passed in `tests/test_hw2_go2_backend.py` (was 45). Rows that MOVED: A1 and F5a — `observation.backend` is now `go2_stage0_replay`, not `go2` (F5, deliberate); B1b/B4 call `evidence(observation)`; B5's producer implements `scan_datum_for` |

**Suites:** `test_hw2_go2_backend.py` 55 + `test_w0b_commissioning.py` +
`test_hw5_physical_profile.py` + `test_hw6_stopping_envelope.py` = **179
passed**; wider neighbours (`web_panel`, TRUTH-1, HW-3, W0-A, `control`,
`core_input_health`, fail-closed, CAP-1) = **492 passed**. CPython 3.10.21
re-checked end-to-end: import with no `numpy/mujoco/rclpy/unitree_sdk2py`,
`observe()`, the keyed datum, the identity re-read, and `open_livox_socket`
(`gettimeout() == 0.0`).

## Seeds — ten, all RED on an import-verified scratch, restored by sha256

| Seed | Reddened |
|---|---|
| S1 empty `BandScan` copied across | a3, b4, h2a′, h2b (4 failed) |
| S2 the typed `declared_origin` guard dropped | b7 (1) |
| **S3a** (re-cut) the ordering latch removed | b6 ×4 + the two identity sub-rows + h2a (7) |
| **S3b** (new) the identity exemption removed | b6-identity ×2, **h1b** (3) |
| S4 `move()` a no-op | a4 (1) |
| S5 go2 selected whenever a section resolves | b2, b8, f5a (3) |
| S6 the scan-age contribution dropped | e1 (1) |
| S7 the `backend:` key guard deleted | c3 (1) |
| **S8** (new) the `scan is not None` precondition dropped | h2a′ (1) |
| **S9** (new) `scan_datum_for` returns `latest_scan()` | h2b (1) |
| **S10** (new) `observe()` fabricates a pose again | f2a (1) |

Control run on the restored scratch: **56 passed** (55 + the scratch guard).

## The remaining FIXes

* **F1** — the stop-path comment now says it: *"A MOTION-CAPABLE SUCCESSOR MUST
  NOT INHERIT THESE NO-OPS."* The argument for them is "nothing was ever
  commanded", and it expires the moment a backend can command.
* **F4** — `on_refusal` is wired (`LiveGo2Sources._count_refusal`): a corrupt
  datagram is counted on `refused_datagrams` and skipped. Proved by H1a,
  including that the good datagram behind it is no longer left in the socket.
* **F7** — the fixture generator takes `--out` and refuses unknown arguments;
  with no `--out` it prints to stdout and touches nothing. `--help` no longer
  rewrites the shipped fixture (its sha is unchanged: `454f1013…`), and
  `--out <tmp>` still reproduces it byte-for-byte.
* **N6** (recorded, not fixed — it is not this card's to fix): battery under a
  `Go2Backend` stays the config's `simulated_percent` (90 %,
  `runtime.py:2174`). `SportModeState_` carries no battery; `BmsState` does.
  **The first dog run will report a battery it never measured.**
* **N12** — `_config_tree`'s docstring now says C5 proves the overlay path.
* **N5** — DESIGN §h risk (6): `max_frames_per_drain=32` against ~2,000
  datagrams/s is a partial sweep per tick, so the sweep the join grades is
  bounded-stale by the socket buffer while `captured_at` is a host receipt —
  queueing delay is invisible to the sixth term meant to measure it.
  `source_time_ns` is carried unfused; B11 decides accumulate-vs-per-tick.

## What changed (correction pass)

| File | +/− (this card's share) |
|---|---|
| `src/parcel_robot/backends/go2.py` | 1,001 lines (was 816): `scan_datum_for`, the lock, `Go2StateUnavailable`, `open_livox_socket`/`_checked_socket`/`_count_refusal`/`drain_budget_s`, `name` from the source, the successor sentence |
| `src/parcel_robot/core/input_health.py` | +224/−0 (was +191): keyed `evidence`, the identity exemption, `name=` |
| `src/parcel_robot/runtime.py` | +147/−7 (mine: the region + `_scan_source_record`; the rest is HW-1's and HW-4's) |
| `src/parcel_robot/web_panel.py` | +276/−2 (mine ≈130: `_BACKEND_LIVOX_KEYS`, the livox read-site guard, the fixture/livox refusal; the rest is HW-MIC's) |
| `tests/test_hw2_go2_backend.py` | 1,827 lines, 55 tests (was 1,292 / 45) |
| `scrum/20260822/task_40/{DESIGN,PREREGISTRATION,HW2_STATUS}.md` | Amendment 2; DESIGN §c/§d/§h corrected in the same pass |

Locks: `lock-runtime.py` taken and released for one Edit pass;
`lock-web_panel.py` waited for (HW-MIC held it), then taken and released.
`git status --porcelain` 64 lines before, 65 after — the single new line is
`?? scrum/20260823/`, another session's folder; this pass introduced no new
paths. Ruff: **exactly the 7 baseline fingerprints tree-wide**, `All checks
passed!` on every HW-2 file, 0 `noqa` in my files or hunks (`runtime.py`'s three
are pre-existing and outside the HW-2 region), `ruff format --check` clean on
all five files that are wholly or newly mine. Guard ledger `label=hw2`: 83
runs, 61 rc≠0 (the ten seed runs ×2 sweeps + iterative development), **no 137,
no `-n auto`, no `--tier`, no simulator, no background pytest**.

## Handoffs added or sharpened

* **F6 → integrator / design owner (blocking for the physical table on the
  dog).** `safety.require_physical_inputs` is in neither the SHA-locked base nor
  `OVERLAY_INTRODUCIBLE_KEYS`, and HW-5's profile refuses `safety.*` by policy,
  so **no profile can put a `Go2Backend` under
  `requirements_requiring_physical_inputs()`**. With `control.controller:
  simulator` the runtime takes `requirements_allowing_sim_fixtures()`, where a
  REPLAY scan and a SIMULATION pose both pass. Motion is still refused by the
  backend, so nothing moves — but the authority semantics on the dog are the
  permissive table. Fix: admit the key (tightening-only) or add it to the base
  as `false`, and set it `true` in `configs/robot.go2_edu_plus.yaml`, before any
  hand exists. Corrected in DESIGN §h risk (5); the old handoff sentence
  ("HW-5's profile sets it true") was impossible as written.
* **D1 / N1 → HW-6b at the wave-3b close.** The sixth term stays a V2 layer.
  Wiring it is `evaluate_stopping_envelope` → `derive_envelope_rows_v2` +
  `load_stopping_envelope_record_v2`, the five HW-6 assertions (`:303, :317,
  :344, :640, :683`), delete `test_e7`. **The hazard of leaving it unwired is
  concrete:** the day the five V1 terms are measured on the box, the row prints
  FITS with scan age silently absent — "a term nobody wrote down" read as
  measured-at-zero, on the one gate row the design calls "a gate row, not a
  note".
* **HW-5 — the new Livox keys to admit:** `backend.livox.host` and
  `backend.livox.port` (nested under the `backend` subtree HW-5 already exempts,
  so they merge today; named here so the profile can carry them). Also
  `backend.drain_budget_s`. The VALUE of host/port is a box-day measurement
  (design §8 Q-wire, host `192.168.1.5x`); `port` defaults to HW-3's
  `HOST_POINT_DATA_PORT`.
* **N10 → integrator:** record `sha256(head -634 bridge/timing.py) =
  cbd37558292b7e979b5bae38edcfa4da17053ebffcd638954cc75c27ba801808` in HW-6's
  record — HW-6's verifier left no post-rename pin and this verdict had to use a
  scratch copy as its witness.
* **N7 → design owner:** HW-5's profile comments an extrinsic FORM
  (`extrinsic_xyz_rpy`, six reals) that `band_profile_from_config` does not
  accept (it takes a 4×4). No conflict today (the value is absent); decide
  before B11.
* POSE authority and the `parcel_robot.core`-is-not-a-leaf handoffs stand
  unchanged from the first pass.

## What the re-verify should look at first

1. **H2a + H2a′ together.** The first enumerates the four cases; the second is
   the read site's own rule against a source that answers anything. S8 reddens
   only the second — that gap is exactly what the first attempt missed and it is
   recorded above rather than quietly closed.
2. **The identity exemption** (`input_health.py:_ordering_fault`) and H1b: that
   the operator's clear can clear, and that a DIFFERENT datum under a repeated
   sequence still latches (S3b reddens the exemption, S3a the latch).
3. **F3's socket**: that `open_livox_socket` is reachable from
   `build_runtime` through `backend.livox`, that a blocking socket is refused,
   and that `drain_budget_s` bounds a transport that keeps giving.
4. **F6** — that the permissive-table finding is recorded as an integrator item
   and not quietly assumed away; nothing in this card can fix it.
