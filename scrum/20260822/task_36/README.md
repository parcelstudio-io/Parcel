# Task 36 — HW-3: `mid360-band` — a Livox Mid-360 sweep becomes the scan the runtime already consumes

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + anti-crash rules in `../BATCHB_DISPATCH_FABLE_4a.md`).
**Design:** `../WAVE3_HW_DESIGN_FABLE.md` §2.3–2.4, §4 rows S1/S2/S6, §5.3,
§9 HW-3. **Evidence:** `research.json` hardware facts 4, 5, 23 (Mid-360 spec,
livox_ros_driver2 ports/IPs, SDK2 protocol), codebase facts 6, 7, 9, 10
(no Livox code in the tree; `SimObservation.lidar_ranges`;
`reactive_safety.scan_present`).

## Why
The runtime's only physical-fact source is `SimulatorBackend.observe()` →
`SimObservation` (`backends/base.py:124-170`; `lidar_ranges`,
`nearest_obstacle_m`). The Mid-360 publishes ~200 k pts/s at 10 Hz over UDP
(cmd 56100, point 56300, IMU 56400) with a vertical FOV −7°…+52° — it sees
up, not down. The scan the planner and `reactive_safety` consume is a planar
band in the sim's angular layout; nothing in the tree reads Livox. There is
no hardware: this card is pure, testable code that HW-2's `Go2Backend` will
call, proven against packets built from the published frame format.

## Work
1. `DESIGN.md` first: the Livox SDK2 point-cloud UDP frame layout you will
   decode (cite the field table from `livox_ros_driver2` / SDK2 headers you
   read — URL in the doc; if a field is UNCONFIRMED say so and make the
   decoder refuse on it), the band definition (z ∈ [z_lo, z_hi] above
   base_link after a 4×4 extrinsic, both numbers PROFILE parameters not
   constants, defaults `[0.10, 0.60]` marked "tune at B11"), the angular
   binning that reproduces `SimObservation.lidar_ranges`' layout (read
   `mujoco_lidar.py` for the sim's exact layout and cite it), the
   `nearest_obstacle_m` derivation identical to the sim's, the extension seam
   for HW-2 (`module:symbol` of the pure function `Go2Backend` calls).
2. New package `src/parcel_robot/lidar/`: `livox_udp.py` (frame parser, pure,
   bytes → points with per-point timestamp; refuses unknown data types;
   no sockets — a thin `receive()` adapter is a separate function so the
   parser is testable offline), `band.py` (points → band → ranges tuple; pure;
   numpy optional — must work on the 3.10/aarch64 `base` extra), `__init__.py`
   exports. No ROS, no SDK.
3. `capture/channels.py`: `SourceDevice.MID360` and its channel rows in a
   marked `CARD HW-3` region; retire the "add-on Unitree L2 via unilidar_sdk2"
   concept by making `ingest/l2.py`'s live adapter refuse with a pointer to
   this card (do NOT delete the file or rename `L2` — the L2→HEAD_LIDAR rename
   is HW-2/HW-9's, record it as a handoff).
4. Tests `tests/test_hw3_mid360_band.py`: (a) parser round-trip on frames you
   SYNTHESISE from the documented layout (a builder in the test), incl. a
   truncated frame, a wrong data-type, an out-of-order timestamp; (b) band
   filter property tests (points outside the band never appear; a wall at
   2 m at bearing θ yields range 2 m in the bin for θ; empty bins are the
   sim's "no return" value — read what the sim emits); (c)
   `reactive_safety.scan_present` is TRUE on a `SimObservation` built from
   the band output and `scan_evidence_from_observation` labels it physical
   when `backend="go2"` — through the real functions, no monkeypatch; (d)
   performance: one 20 k-point sweep → ranges in < 20 ms on this box
   (recorded, not gated — the Orin number is box-day).
5. Seeded RED for every guard (refusals in the parser; band bounds); a pcap
   from a real Mid-360 is box-day (HW-9) — say so.

OWNS: `src/parcel_robot/lidar/` (new), the `CARD HW-3` region in
`capture/channels.py`, the refusal in `scripts/parcel_capture/ingest/l2.py`
(marked), `tests/test_hw3_*.py`, `task_36/` docs. MUST NOT TOUCH:
`backends/base.py`, `reactive_safety.py`, `mujoco_lidar.py`, the grid
planner, the nine `ClearanceProfile`s, `navigation/`, the safety core.

## Definition of done
Synthesised-frame round trip; band properties; `scan_present` true through
the product functions; seeds RED; the HW-2 seam named; `HW3_STATUS.md` with
pre-registered rows.

## Hardware-compat (§e)
Class NEW (S6) feeding VI (S2). State exactly which numbers are profile
parameters, which are UNCONFIRMED until the box (NIC/subnet — Q-wire; M8
voltage), and that the head LiDAR (`rt/utlidar/*`) is NOT consumed here.
