# Task 11 — P2-B: the dog notices you — identity, affect, and initiative

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Roadmap:** audit §10 Phase 2 items
2–3, §5 "What to do" items 3–5, §9 rows "voice identity", "idle hang-up /
narration", "affect".

## Why
Identity is wired and inert (`realtime/voice_identity.py` boots
`verify_disabled` with no enrolled profile and whispers about it); "I am
feeling sad" on the production lane does nothing because affect
(`brain/router.py: explicit_affect_from_text`) runs only on the legacy lane;
the dog never initiates toward the owner — the whisperer
(`realtime/whisperer.py`) narrates the robot (battery, arrival) and the idle
lane hangs up after 600 s. A companion that never greets you is not one.

## Work
1. **Identity as a label, not a gate (§9):** stamp the speaker verdict on
   every ledger row; emergency class stays ungated; with no enrolled profile
   the gate is silent (no whisper about itself). The one-minute enrollment
   (`tools/enroll_owner_voice.py`) stays an OWNER ACTION — the card makes the
   system correct both before and after it.
2. **Affect on the hosted lane:** run `explicit_affect_from_text` on hosted
   `KIND_NONE` turns at confidence 0.5, log an affect row, offer a comfort
   gesture through `propose_action` (runtime region — re-read P0-B's
   `submit_realtime_transcript` edits; add a new region), keep a rolling
   affect history that P2-A's distiller may read through the public API.
3. **Owner-event classes in the whisperer:** `owner_appeared`,
   `owner_returned_after_Nh`, `greeting_due`, `question_of_the_day`, fed from
   the owner track (P1-C's `OwnerTrackV1` when present; the UWB/mocap track
   otherwise) and the session ledger; ride the existing cap/cost/band
   machinery with the prototype cap (6/min) and the P0-B idle behaviour
   (stay live while the owner is present).
4. **Voice-tier experiment (owner action, packaged):** one config line for
   full-size gpt-realtime vs mini; the card writes the comparison script and
   the probe list; the owner runs one session.
5. Pre-register: greet-on-appearance fires once per appearance within 5 s on
   a scripted track; "I'm sad" yields an affect row + one gesture proposal
   within one turn; identity verdict present on 100 % of rows; zero whispers
   about the unenrolled gate.

## Proves
On the hosted lane with a scripted owner track: the dog greets the owner
unprompted, reacts to "I'm sad" with a gesture offer, and every row carries
an identity label — without a single refusal added.

OWNS: `realtime/voice_identity.py`, `realtime/whisperer.py` NEW owner-event
bands (P0-B's narration-cap edits are elsewhere in the file — re-read first),
`runtime.py` NEW affect region, `brain/router.py` hosted-lane affect entry,
`configs/realtime.yaml.example` owner-event keys, `tools/voice_tier_ab.py`,
`tests/test_p2b_*.py`, `task_11/` docs.
MUST NOT TOUCH: `memory.py`/`tiered_memory.py`/`prompting.py` (P2-A),
`tool_broker.py` (P0-B/P2-A), safety core, the owner's live store.

## Definition of done
Five pre-registered rows measured; seeds RED for gate-becomes-blocking,
affect-on-legacy-only regression, greeting storms past the cap;
`P2B_STATUS.md`.

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* Affect: EXTEND the `_hosted_affect` helper P0-B added to `runtime.py` and its
  `hosted_affect` key — do not add a second affect region. Owner-event bands
  extend `whisperer.window_s` / the 6-per-min cap P0-B set; idle behaviour is
  `idle_close_after_s: 0` (already landed) — consume it.
