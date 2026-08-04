# Workstream C — proof, and one debt

The sprint's claims only count if the eval measures them (working agreement:
the register drains by *doing the verification*). Plus the one unblocked debt
item from the register.

---

## W8 — Emote triggers onto the playback clock · **Owner: Opus** · independent

Closes [../../backlog/UNVERIFIED.md](../../backlog/UNVERIFIED.md) **U6** /
NEXT **N1**. Today `[emote:...]` tags fire when their sentence is
*synthesized*; with a deep audio queue the bow lands seconds before the words.
A4 already built the anchor.

1. In `SentenceChunkedSynthesizer`, stop firing `on_emote` directly; instead
   attach the sentence's emotes to the chunk token the runtime already passes
   to `SpeakerSink.enqueue` (extend the `(track, epoch)` token to
   `(track, epoch, emotes)`).
2. Fire the emote proposals from `_audio_chunk_started` — the same
   playback-start callback that arms nods — and only when the token's epoch
   is current. Barge-in already supersedes the epoch, so pending gestures die
   with their audio for free.
3. Tests: emote fires at playback start of its own sentence, not at
   synthesis; a queued-but-superseded sentence fires nothing; the
   text-only path (no synthesizer) still fires emotes immediately (there is
   no playback clock to wait for — document that).
4. Close U6 in the register: move it to the Closed section with the test
   names as evidence.

---

## W9 — Walk-with-owner eval scenarios + expression metrics · **Owner: Opus** · after W2/W4/W6/W7

Extend `evals/companion_nav/` (same scenario/runner/metric/ledger discipline):

**New scenarios (each with a frozen baseline row BEFORE the feature lands —
run them on today's code first so every claim has a before/after):**

- `owner_turn_90` — owner walks 6 m, turns 90°, walks 6 m. Metrics: mean
  distance-band error during the turn window, time outside band. Proves W2.
- `pedestrian_cut_in_predictive` — a pedestrian crosses the follow corridor
  on a collision course with the *future* path. Metrics: hard collisions
  (must stay 0), reactive-gate intervention count (must *decrease* vs
  baseline — the planner now yields first), min TTC. Proves W4.
- `owner_corner_loss` — owner rounds an occluding corner and keeps walking.
  Metrics: time-to-reacquire, search distance, gave-up flag. Today's
  baseline is "stands forever" — record it honestly as a timeout. Proves W7.
- Jerk deltas ride the existing follow scenarios (no new scenario needed) —
  before/after ledger rows with the shaper toggled. Proves W6.

**Expression metrics (backlog N8), folded into the same runs:**

- latency-to-acknowledgment (speech-onset event → head-orient offset visible
  in the snapshot), blend-continuity jerk at expression-layer transitions,
  interruption correctness (an emote firing mid-navigation must never
  produce a hard collision — assert against the trace), and an emote
  duty-cycle report (fraction of conversation time in gesture; the HRI
  annoyance failure mode is over-triggering).

**Rules:** pedestrians visible to metrics vs raycast stays as documented in
the eval's `does_not_prove`; no BARN-style speed scoring; one ledger row per
change with a one-line "Change" description; `does_not_prove` updated for
every new scenario (e.g. `owner_corner_loss` does not prove real-camera
re-identification — the sim track is identity-perfect).

---

## Operator items (nobody else can do these)

Unchanged from [../../backlog/BLOCKED.md](../../backlog/BLOCKED.md):

1. **B1:** `sudo apt install -y libportaudio2 cmake build-essential dfu-util`
   → then `scripts/install_speech_services.sh` → spoken conversation closes
   the two outstanding 2026-08-04 DoD items and four UNVERIFIED entries.
2. **U7/U8 eyeballs:** open `/viewer` in a browser (gaze + Expression HUD)
   and the MuJoCo viewer (breathing) — two minutes each, closes two register
   entries.
3. **B3:** when the XVF3800 + speaker arrive, follow the arrival checklist in
   [../20260804/B-audio-io.md](../20260804/B-audio-io.md).
