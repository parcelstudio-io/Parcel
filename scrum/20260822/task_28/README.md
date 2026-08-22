# Task 28 — ENV-1: the dev box may carry a vendor SDK

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Status:** `ENV1_STATUS.md`.

## Why
The final Wave P1/P2 gate went red on seven capture-stack tests
(`test_capture_ingest` ×3, `test_capture_preflight`, `test_capture_rehearsal`,
`test_capture_sidecar`, `test_clockmap`). Every one encoded an *environment
premise* — "this hardwareless dev box has no vendor SDK installed" — that P1-A
made false on 2026-08-22 by legitimately installing `pyrealsense2` 2.58.3 and
`opencv-python-headless` into `.parcel` for the desk-camera venue. The premise
was never the property: the capture stack must refuse on a box with no
**device**, name what is missing, and never import a vendor SDK during
preflight. That property is still worth having once the wheel is present.

## Work
1. Re-cut the seven tests onto the property, clause by clause:
   (a) each live adapter refuses here naming the missing module **or** the
   missing device; (b) a full preflight run never imports a vendor SDK —
   `VENDOR []` kept word for word; (c) the motion SDKs (`rclpy`, `cyclonedds`,
   `unitree_sdk2py`, `unilidar_sdk2`, `mcap`, `zstandard`) stay absent from
   `.parcel` — that is the motion guarantee, unchanged — while a camera SDK may
   be present; (d) clockmap's `probe_availability` fails closed on device
   absence, not just module absence.
2. Whatever product change (a)–(d) need to be *true*, not merely asserted —
   expected to be one lazy-import line in `camera_channel/backends/realsense.py`
   (it was not; see the status doc's deviations).
3. Seeded RED per re-cut guard; nothing uninstalled; `pyproject.toml` untouched.

OWNS: the seven tests (their files), `scripts/parcel_capture/` as needed for
(a)–(d), `task_28/`. MUST NOT TOUCH: `src/parcel_robot/` regions owned by the
wave cards, `docs/`, the venv contents.

## Definition of done
Five files green in random order; ruff ratchet unchanged (7 fingerprints);
seeds RED; `ENV1_STATUS.md` in the lightweight register with every product
change declared; the Fable gate green on the quiesced tree.
