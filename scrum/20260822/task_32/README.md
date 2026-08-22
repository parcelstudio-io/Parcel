# Task 32 — TRUTH-1: remedies and reports tell the truth about this box

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `AUDIT_WEEK1_FABLE.md` §ENV-1b
(refuted finding carried as SDK-REM-1), §TURN-1 (the report's missing
`settle_s`/wall time), §AIR-1 (naming; the raw-tap premise),
`task_25/AIR1_STATUS.md` correction pass, `task_21/TURN1_STATUS.md`.

## Why
Three operator-facing texts currently say something untrue about the dev box:
"install pyrealsense2 on the Orin" when the wheel is pip-installable here and
already in `.parcel`; "no wheel for 3.11+ / aarch64" (unverified; a cp314
wheel is installed); and a replay report that cannot tell a wall-indexed
`audio_end_ms` from an appended-audio one. Each costs a session morning.

## Work
1. **Per-device SDK remedies** in `scripts/parcel_capture/` (`clockmap`
   MODULE MISSING, `ingest/realsense.py` `requirements[0].remedy`, `record.py`,
   `preflight.py` `_TRANSPORT_REMEDIES`): the D455 says
   `.parcel/bin/pip install -e '.[camera-realsense]'`; go2/l2 keep the
   Orin/ROS 2 sentence; the stale wheel claims replaced by what `pip index`
   reports today (measured, dated). `record --check` stops reporting "reader
   deps present" from a module-only census — reuse ENV-1's `device_report()`.
   The `NO DEVICE (installed: …)` report text gets a product caller or is
   removed.
2. **The replay report carries `settle_s` and per-file wall-elapsed-since-open**
   so the first live run can detect *and correct* a wall-indexed
   `audio_end_ms` (TURN-1 handoff); the tool's docstring stops claiming
   `--arms/--check/--plan` never import `lane` (they import the package;
   `ws_transport` is the property).
3. **AIR-1 follow-through:** `asr_beam_echo_attenuation_db` naming in the
   runbook and the scorecard schema docs; the raw-tap mux path's
   prerequisites stated once (udev + `pyusb`, firmware v2.0.6, never flash the
   6-channel image).
4. Seeds RED: a module-only census reporting a device present; a remedy for
   the D455 that names the Orin; a report row without `settle_s`.

OWNS: `scripts/parcel_capture/{clockmap.py main() remedy block, ingest/realsense.py remedies, record.py --check, preflight.py remedies}`,
`tools/replay_turn_detection.py` report fields + docstring, `task_25/SESSION.md`
naming lines, `tests/test_truth1_*.py`, `task_32/` docs. MUST NOT TOUCH:
`probe_availability`/`PROBE_REQUIREMENTS` (Fable's corrections),
`ingest/base.py`, `pyproject.toml`, `lane.py`, the array's control path.

## Definition of done
The three texts measured true on this box (commands + outputs in the status
doc); seeds RED; `TRUTH1_STATUS.md`.
