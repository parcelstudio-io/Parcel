# Task 16 — VENUE-1: the runtime opens the physical eye

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** P1-A's declared HALT
(`task_6/P1A_STATUS.md` §8 handoff 1): `runtime.py`
`_attach_configured_camera_ingress` (~line 10208) builds the MuJoCo/EGL ingress
UNCONDITIONALLY; the three physical backends, the GPU detector daemon and the
`--camera` launcher switch all exist but nothing in the runtime selects them.
P1-A wrote the ~20-line change out verbatim (including skipping the
`MUJOCO_GL` preamble when the venue is physical).

> **CORRECTION 2026-08-22 (owner's statement):** no robot hardware is on hand — no Go2, D455, L2 or Orin. Earlier wording in this card that assumes a D455/Go2 'on the bench' inherited a false fact from scrum/20260813/task_1; the only device present is the reSpeaker XVF3800 mic array. Live rows that need a camera wait for a purchase, not a cable.

## Why
Phase 1's "proves" rows (a room map from pixels; "go to the couch" from the
dog's own map; person recall on real frames) all run through the runtime's
attach site. Until the venue is selectable there, a plugged-in camera feeds
nothing.

## Work
1. Land P1-A's change at the attach site: venue from config
   (`perception.camera.backend: mujoco | uvc | realsense | recorded`, in the
   prototype overlay per P0-A), the daemon's `DaemonDetector` as the detector
   when `perception.detector: daemon`, `EvidenceOrigin.PHYSICAL` propagated
   end-to-end, and the `MUJOCO_GL` preamble skipped for physical venues.
   Edit-only; re-read — P2-A/P2-B/P1-B have regions in `runtime.py`.
   **The verifier's catch (binding):** `CameraIngress` never reads
   `buffers.origin` — the published frame carries `self.origin`, which
   defaults to `"unknown"`. P1-A's original handoff snippet omitted
   `origin=`; the attach site MUST pass `origin=backend.origin.value` (as
   P1-B's sim path passes `EvidenceOrigin.SIMULATION.value`), and a
   physical-venue runtime whose published frames carry `unknown` is a seeded
   RED this card must turn green.
   **P1-A's post-verification finding (binding):** an RGB-only UVC venue
   cannot feed `CameraIngress` today — the ingress requires depth buffers,
   so a plain webcam yields a counted poll error and publishes nothing
   (pinned by P1-A's own cell). This card either adds an explicit RGB-only
   ingress mode (depth-dependent gates report `depth_unavailable`, never a
   silent pass) or states plainly that the D455 is the day-one device. Do
   not ship a synthetic-depth fallback that lets planarity 'pass'.
2. Re-run P1-A's `live_camera_proof.py` rows through the RUNTIME path (not
   the daemon client alone) on the recorded backend in CI, and list the
   uvc/realsense rows as OWNER-GATED with exact commands.
3. Pre-register: capture→publish p50 < 300 ms through the runtime with the
   daemon; 100 consecutive `PHYSICAL` frames, zero drops; a sim-origin frame
   reaching a physical-venue runtime is REFUSED (origin mixing, seed it);
   flag-off (mujoco venue) byte-identical behaviour.

OWNS: `runtime.py` attach-site region only, `config.py` venue keys if the
key walk needs them (P0-A's mechanism), `configs/robot.prototype.yaml`
camera block, `tests/test_venue1_*.py`, `task_16/` docs. MUST NOT TOUCH:
the backends/daemon (P1-A), `ingress.py` (P1-B), safety core.

## Definition of done
Recorded-backend rows green through the runtime; origin-mixing seed RED;
flag-off identity proven; `VENUE1_STATUS.md` with the owner-gated live rows.
