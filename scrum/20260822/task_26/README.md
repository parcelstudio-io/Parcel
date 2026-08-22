# Task 26 — DUPLEX-1: a turn controller that lets "mm-hmm" survive

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Dispatch gate: after MARK-1 and TURN-1 land**
(it builds on their acks and knobs). **Evidence:** the design study §C
architecture (3) — the hybrid engineered duplex `docs/RESEARCH_2026_ROADMAPS.md:29-75`
already chose: a local state machine owns turn-taking, the hosted model is
the mouth; today every `speech_started` during playback cancels
(`lane.py:2274`) and proactive speech can never overlap anyone.

## Why
Natural conversation is not "cancel on any sound": backchannels ("yeah",
"mm-hmm") must not kill a reply; a real interruption must duck within
100 ms and commit within ~450 ms; proactive remarks must wait for a real
gap. That is a state machine, not a threshold.

## Work
1. **`duplex/turn_controller.py`** — pure, testable, shaped like
   `filler_policy.py`: states LISTEN / THINK / SPEAK / OVERLAP / YIELD;
   inputs are local VAD onset/offset on ch1 (Silero, reused from
   `endpointing.py`), server `speech_started/stopped`, partial transcript
   content words, playback position (MARK-1's acks); outputs are DUCK,
   CANCEL, RESUME, and an `initiative_allowed` flag the whisperer reads.
2. **Hooks:** `lane._on_speech_started` consults the controller (provisional
   DUCK ≤ 100 ms; COMMIT cancel at > 400 ms of speech or a content word);
   browser gain control for ducking; `whisperer.offer` gated on
   `initiative_allowed` (LISTEN-idle only); the prosody tap on outbound PCM
   in `lane._emit_audio` so the body moves to the hosted voice.
3. **Pre-register:** backchannel survival **≥ 0.9** on a fixture set of
   short acknowledgements; confirm-cancel **≤ 450 ms**; false interrupt
   **≤ 0.02** on noise fixtures; proactive-collision **0**; no owed turn left
   unanswered in a **1-h fake-server soak** (the deadlock risk named in the
   study).
4. Seeds RED: a backchannel cancelling a reply; initiative during SPEAK; an
   owed turn dropped on a state transition.

OWNS: new `src/parcel_robot/duplex/turn_controller.py`, `lane.py` barge-in
region (after MARK-1 closes it), browser gain region in `ui/index.html`,
`whisperer.py` `initiative_allowed` gate (after CURIO-1), `tests/test_duplex1_*.py`,
`task_26/` docs. MUST NOT TOUCH: `protocol.py`, `config.py` keys (TURN-1),
the broker, `reactive_safety`.

## Definition of done
Five pre-registered rows measured on fixtures + the soak; live row
OWNER-GATED (a through-air session with backchannels) with its command;
`DUPLEX1_STATUS.md`.
