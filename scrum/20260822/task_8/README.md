# Task 8 — P1-C: the dog knows which person is you — pixels to OwnerTrackV1

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Roadmap:** audit §10 Phase 1 item 3,
§6 "owner localization path to real".

> **CORRECTION 2026-08-22 (owner's statement):** no robot hardware is on hand — no Go2, D455, L2 or Orin. Earlier wording in this card that assumes a D455/Go2 'on the bench' inherited a false fact from scrum/20260813/task_1; the only device present is the reSpeaker XVF3800 mic array. Live rows that need a camera wait for a purchase, not a cable.

## Why
The owner is a mocap body with confidence 1.0 (audit §1); no identity, no
re-ID, and reacquisition after loss has never succeeded. The real path is
already designed: OWLv2 person boxes → a re-ID embedding → `OwnerTrackV1`
(`contracts/v1.py`), fused with `rt/uwbstate` through `OwnerFusionStub`
(`uwb/fusion.py`); the reactive identity gate already consumes the track. None
of it is connected to pixels.

## Work
1. **`owner_tracking/` package:** take person detections from the ingress
   stream (the typed `CameraDetectionFrame` C-1 defined), crop, embed with the
   SigLIP-2 image encoder (re-use P1-B's `embed_fn` seam — consume, don't
   re-implement), and maintain a short-horizon track with a re-ID gallery: the
   owner's gallery is ENROLLED (a handful of crops the owner confirms), every
   other person is `unknown`. Output: `OwnerTrackV1` with a confidence that is
   a measured similarity, not 1.0.
2. **Fusion:** feed the pixel track into `OwnerFusionStub` beside UWB; the
   reactive identity gate then sees a real confidence. Pre-register the
   behaviour when the track is lost (confidence decays; follow degrades to
   `searching`, never to a guess).
3. **Enrollment flow:** `tools/enroll_owner_appearance.py` — ten seconds of
   frames, the owner confirms, gallery persisted beside the voice profile
   (`owner store` rules: the memory sqlite is never opened read-write by tests;
   appearance gallery is its own file under the owner's config dir).
4. **Fixtures:** a recorded clip with two people (synthetic or the owner's own
   recorded session, owner-gated) for the track/reacquire tests; seeds RED for
   confidence-1.0 constant, gallery-less owner claims, and track swap on
   crossing.
5. Pre-register: person recall ≥ 0.8 on held-out frames of the owner (live,
   owner-gated on a camera), track continuity across one occlusion on the
   recorded clip, zero `owner` claims with an empty gallery.

## Proves
On the recorded clip: the track follows the enrolled person across a crossing
with a second person and reacquires after occlusion; confidence is a
similarity. Live (owner-gated): the owner track follows the owner across the
room with the camera panned by hand.

OWNS: new `owner_tracking/` package, `uwb/fusion.py` (pixel-track input
seam only), `tools/enroll_owner_appearance.py`, `tests/test_p1c_*.py`,
`tests/data/p1c_*`, `task_8/` docs.
MUST NOT TOUCH: `ingress.py` (P1-B), `online_map/`, `reactive_safety`
semantics, the voice identity stack (P2-B), safety core.

## Definition of done
Recorded-clip rows measured; seeds RED; `P1C_STATUS.md` register with live
rows marked OWNER-GATED (camera + enrollment) and their exact commands.

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* Consume P0-B's `proactive_motion_tools` allowlist for any approach-to-standoff
  behaviour the track enables; do not add a new motion path.
