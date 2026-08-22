# Task 17 — OT-2: the running robot stops believing the owner at 1.0

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** P1-C's handoffs
(`task_8/P1C_STATUS.md` §6.4), verified: `headless_city.py:370` still emits
`OwnerTrack(confidence=1.0)`; nothing in `runtime.py` constructs an
`OwnerTracker`; `navigation/reactive_safety.py:63`
`OWNER_IDENTITY_CONFIDENCE_MIN = 0.65` applied at `:496` would accept a
stranger at cosine 0.917. P1-C's own finding: an uncalibrated gallery claims a
stranger on occluded-owner frames; the calibrated headroom is only 0.03.

> **CORRECTION 2026-08-22 (owner's statement):** no robot hardware is on hand — no Go2, D455, L2 or Orin. Earlier wording in this card that assumes a D455/Go2 'on the bench' inherited a false fact from scrum/20260813/task_1; the only device present is the reSpeaker XVF3800 mic array. Live rows that need a camera wait for a purchase, not a cable.

## Why
P1-C built the tracker and proved its failure modes, but the robot that moves
still runs on a mocap body with confidence 1.0. Wiring the tracker in without
re-deriving the identity threshold would be WORSE than today: a constant
tuned for a 0/1 confidence meets a cosine that scores strangers at 0.92.

## Work
1. **Wire the tracker:** under the physical venue (VENUE-1) person detections
   from the ingress feed an `OwnerTracker` the runtime owns; its
   `OwnerTrackV1` goes through `OwnerFusionStub`'s pixel-track seam (P1-C's
   +155 lines) beside UWB. Under the MuJoCo venue the mocap path is unchanged
   (flag-off identity, byte-for-byte).
2. **Re-derive `OWNER_IDENTITY_CONFIDENCE_MIN` on the cosine scale** — but do
   NOT key it on the raw number: the fusion seam already carries `state`
   (`confirmed | tracking | ambiguous`) and P2-B's `owner_presence_sample`
   correctly gates on state. Make the reactive gate consume state + calibrated
   margin, with the constant retired or re-derived from the enrollment's
   measured boundary (pre-register the derivation; the stranger at 0.917
   must NOT be trusted, the enrolled owner at ≥ 0.94 must).
3. Follow/standoff consumers read the same track; reacquisition after loss
   degrades to `searching`, never a guess (P1-C's R5 decay is the input).
4. Seeds RED: constant-1.0 confidence reappearing; a raw-cosine gate; a
   stranger trusted at 0.917.
5. Pre-register the recorded-clip rows (P1-C's two-person clip) through the
   RUNTIME path; live rows OWNER-GATED (camera + appearance enrollment).

OWNS: `runtime.py` owner-track region (NEW, marked), `headless_city.py`
owner-track emission, `navigation/reactive_safety.py` identity-gate SOURCE
only (semantics unchanged — the AST ratchet in `tests/test_dynamic_layer.py`
is the instrument; regenerate its pin only with a log entry, as P1-E did),
`tests/test_ot2_*.py`, `task_17/` docs. MUST NOT TOUCH: `owner_tracking/`
internals (consume), `uwb/fusion.py`, `core/hard_stop`, the e-stop latch.

## Definition of done
Recorded-clip rows green through the runtime; three seeds RED; the AST
ratchet shows only the identity-gate source moved; `OT2_STATUS.md`.
