# Task 40 — HW-2: `go2-backend` — the physical `SimulatorBackend`, observe-only, with scan authority typed

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + the anti-crash rules in `../BATCHB_DISPATCH_FABLE_4a.md`;
wave-3 COMMON brief in `../WAVE3_DISPATCH_FABLE_6c.md`). **Design:**
`../WAVE3_HW_DESIGN_FABLE.md` §4 rows S1/S3/S4, §5.3, §5.4 (as corrected
after HW-3), §6 (the sixth envelope term), §9 HW-2. **Evidence:** HW-3's
`task_36/HW3_STATUS.md` + `src/parcel_robot/lidar/__init__.py` (the seam
snippet: `scan_from_frames`, `nearest_obstacle_from_scan`, `BandProfile`;
`ranges_m == ()` means NO scan — never copy an empty `BandScan` across),
`~/.cache/parcel-verify/hw3/VERDICT.md` F5 (no typed physical
scan-evidence seam exists; `evidence_origin` stamps every `SimObservation`
SIMULATION; `CommissionedStateSource` carries `RobotMotionState`, not
scans), HW-6's `bridge/timing.py:derive_envelope` (scan age is not among
the five terms — add it), HW-8's `docs/BOX_DAY.md` S19/HO-6 (`observe` has
no duration mode).

## Why
`MujocoSocketBackend` is the only `SimulatorBackend` (`backends/base.py:154`
Protocol; constructed at `web_panel.py:728`, handed to the runtime at
`runtime.py:1498`). On the dog there is no MuJoCo. `Go2Backend.observe()`
composes the ODOM pose from `rt/sportmodestate` (the existing
`UnitreeChannelContext` subscriber, `control/unitree_sport.py:20`,
read-only) and the scan from HW-3's band. It is an EYE: `apply`/`step`
refuse with the MOTION.md citation until the native gateway exists.

## Work
1. `DESIGN.md` first: the `Go2Backend` class (module:symbol), its inputs
   (`UnitreeChannelContext.latest()` → `RobotMotionState` → `RobotPose`;
   `parcel_robot.lidar.receive_frames` → `scan_from_frames` → `BandScan`),
   the `SimObservation` fields it fills and the ones it leaves default (cite
   `backends/base.py:124-153`), `backend="go2"`, the refusal of motion, the
   selection key (`backend: go2` in the profile — coordinate with HW-5: HW-5
   owns the profile file and the introducible key; you own the branch at
   `web_panel.py:728` in a marked `CARD HW-2` region), and **the typed
   scan-evidence seam**: a `PhysicalScanSource` (or the name you justify)
   that declares `EvidenceOrigin.PHYSICAL` on the datum the way
   `CommissionedStateSource` does for motion (`control/base.py:87-153`), and
   the read in `runtime.py:_evaluate_dispatch_input_health` (:13799) that
   consults it INSTEAD of `scan_evidence_from_observation` when the backend
   is physical — a marked region; the sim path byte-identical (flag-off).
2. `src/parcel_robot/backends/go2.py` (new): observe-only; recorded-DDS
   fixture support (a `.jsonl` of `SportModeState_` samples + Livox frames
   the tests replay — the 08-13 Stage-0 recording format; no vendor SDK
   import at module scope — `unitree_sdk2py` is imported lazily inside the
   live adapter and refused with a typed error naming the motion venv when
   absent); empty `BandScan` → `lidar_ranges=()` (no scan → the join HOLDs).
3. The observe-duration row HO-6: `parcel_robot.unitree_control observe`
   gets `--duration <s>` (marked region in `unitree_control.py`; the
   existing `--min-samples/--timeout` semantics unchanged; default absent).
4. Scan age as the sixth envelope term: `bridge/timing.py`
   `StoppingEnvelopeInputsV1.scan_age_s` with provenance, in HW-6's region's
   own style (a new marked `CARD HW-2` sub-region INSIDE the file, outside
   HW-6's fence — coordinate: HW-6 is closed), the two record files gain the
   key as UNMEASURED, `derive_envelope` adds `v·scan_age_s`; HW-6's tests
   still pass; a pin that the RC-4 rows are unchanged.
5. Tests `tests/test_hw2_go2_backend.py`: observe() from the recorded
   fixture yields a `SimObservation` with `scan_present` true (real
   `reactive_safety` functions); `apply`/`step` raise; physical authority:
   under `requirements_requiring_physical_inputs()` the runtime's join no
   longer latches `sim_fixture_forbidden` for a `Go2Backend` scan but DOES
   for a sim scan (prove through `_evaluate_dispatch_input_health` with a
   real runtime object built via `web_panel.build_runtime` on a profile —
   zero monkeypatch of the evidence functions); empty scan → HOLD; flag-off:
   with no `backend` key the sim path is byte-identical to HEAD; seeds RED
   per guard on an import-verified scratch.

OWNS: `backends/go2.py` (new), `backends/__init__.py` export (marked), the
`CARD HW-2` branch at `web_panel.py:~728`, the `CARD HW-2` region in
`runtime.py:_evaluate_dispatch_input_health` and the typed source
(`core/input_health.py` or `control/base.py` — choose, marked), the
`CARD HW-2` sub-region in `bridge/timing.py` + the two
`configs/envelope/*.yaml` keys, `unitree_control.py` `--duration` region,
`tests/test_hw2_*.py`, `task_40/` docs. MUST NOT TOUCH: `backends/mujoco.py`,
`reactive_safety.py`, `core/hard_stop`, the e-stop latch, `limits.py`,
`lidar/` (HW-3's — call it), HW-6's fence, HW-4's regions, the safety core.
Shared files: `runtime.py` (HW-5 may add a key read — mkdir-lock),
`web_panel.py` (HW-MIC edits a different region — mkdir-lock),
`bridge/timing.py`, `configs/envelope/`.

## Definition of done
Recorded-fixture observe through the product runtime with physical
authority proven at the join; motion refused; empty scan HOLDs; sixth
envelope term in; `--duration` works; seeds RED; flag-off identity;
`HW2_STATUS.md` with pre-registered rows.

## Hardware-compat (§e)
Class NEW (S1/S3). The desktop proves everything on the recorded fixture;
the box proves the live adapter (Stage 0, S19). Nothing imports a vendor
SDK at module scope; the live adapter names the motion venv it needs.
