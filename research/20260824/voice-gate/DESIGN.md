# VOICE-GATE — who may open the dog's mouth and ears · DESIGN (Fable) · 2026-08-24

## The one decision (RTP-1 C9; H1's C5 refutation is the motivating number)
Choose the activation policy for the all-day ear: **owner-voice gating**,
**wake phrase**, **push-to-talk**, or **restricted listening windows** —
measured through the air on the hardware we actually have (the reSpeaker
XVF3800 is on this host's USB), not in a virtual rig. H1 measured a plain
VAD opening 960×/hour on television speech; the gate that fixes that is a
product requirement for the connected companion.

## Hypothesis (falsifiable)
Owner-voice gating (Silero VAD → TitaNet speaker-ID against the enrolled
owner, `models/speaker_id/`, measured 0.802/0.033 same/cross cosine) in
front of the hosted session cuts false opens on TV/other-person speech to
≤ 4/hour while keeping owner-open success ≥ 0.95 at 1–3 m and 0–60° off-axis,
spoken-STOP recall ≥ 0.99 (STOP bypasses the gate by design), and zero
self-transcribed motion commands while the robot's own TTS plays at
conversational volume with AEC on.

## Experiment (through-air, desk; the one hardware study we can run now)
1. **Sources**: the owner's enrolled voice (live + 10 recorded utterances),
   a second person (recorded corpus voices), television (news + drama
   clips), the robot's own piper TTS through the desk speaker, fan/footfall
   noise. Playback levels calibrated to 60–70 dB(A) at the array.
2. **Geometry**: 1 m / 3 m, 0° / 30° / 60°; 20 trials per cell for the
   owner-open row; 60 min continuous for each false-open row.
3. **Pipeline**: `ArrayAudioGateway` → Silero → TitaNet gate →
   (fake transport — $0; no hosted calls) with `AecStage` on for the
   self-speech rows; every event ledgered.
4. **Arms**: (a) VAD only (H1's baseline, reproduced through air);
   (b) VAD + owner-ID; (c) VAD + wake phrase ("hey <name>", detector =
   whisper on the gated window); (d) push-to-talk (reference floor).
5. **Rows**: false opens/h per source per arm; owner-open success and
   latency; owner-miss rate; false-accept of the second person; spoken-STOP
   recall per arm (STOP must bypass); first-word truncation with the H1
   pre-roll; self-speech immunity (own-TTS transcription rate, AEC on/off);
   endpoint p50 through air.

## Bars (pre-registered)
V1 false opens ≤ 4/h on TV and other-person speech (arm b or c);
V2 owner-open ≥ 0.95 at 1–3 m ≤ 60°; V3 STOP recall ≥ 0.99 every arm;
V4 second-person false accept ≤ 2 %; V5 self-transcribed motion commands = 0
with AEC on (report AEC off); V6 truncation ≤ 2 %; V7 endpoint p50 ≤ 0.8 s
through air. Decision rule: the cheapest arm meeting V1–V5 wins; if none
does, push-to-talk ships for M1 and the gap list goes to the milestone.

## Evidence tier / does not prove
`desktop-real-sensor` (the array is real; the room is not the robot's).
Does not prove on-robot acoustics (motor/gait noise), the robot speaker, or
outdoor wind.

## OWNS
`research/20260824/voice-gate/**`, `tests/test_voicegate_probe.py` (thin),
additive gate seam `audio/activation_gate.py` (pure, flag-off). Must not
touch: the hosted lane, `runtime.py`, the owner's PipeWire config beyond
wpctl profile selection (memory: profile Off ⇒ device not found — set it
back), the owner's stack. Enrollment uses `tools/enroll_owner_voice.py`
against a RESEARCH gallery path, never the owner's live gallery. $0 hosted.
Guard label `voicegate`.
