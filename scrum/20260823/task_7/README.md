# EAR-1 — constant desk listening, $0 (wave A · Tier B)

Design: scrum/20260823/TRANCHE2_MIND_DESIGN_FABLE.md (grounded fact 1, card
EAR-1). The LOCAL lane already listens wake-free (MicrophoneVoiceLoop →
Silero VAD + semantic endpointing → whisper.cpp → VoiceAgent → piper) and
arms automatically when whisper.cpp + a real mic exist. This card makes it
first-class on the XVF3800, hosted lane OFF, zero hosted spend.

## Build
1. `configs/robot.desk.yaml` profile overlay: `speech:` block pinning
   `input_device` to the XVF3800 source by name, `mode: auto`,
   `stt_provider: whisper_cpp`, `tts_provider: piper`, endpointing knob,
   `echo_guard_scale` tuned for the array speaker. NO realtime section
   (hosted stays off). Check which speech keys need
   OVERLAY_INTRODUCIBLE_KEYS admission — `speech` may already be a base
   section; if a NEW key family is needed, follow the roster's
   one-subtree-entry pattern with a read-site validator.
2. Beam-channel selection: where the XVF3800 exposes its processed/beam
   channel, let `MicrophoneVoiceLoop`'s stream open select it (the
   ARRAY_ASR_CHANNEL=1 semantics from audio_gateway.py:2042/2925 applied
   at voice_audio.py:976) via a `speech.input_channel` knob (default
   None = current behavior byte-identical).
3. `speech.aec` knob wiring the existing (currently unwired) `AecStage`
   (voice_audio.py:177) — default off; on = the stage's own contract.
4. `scripts/launch_desk_voice.sh`: preflight (whisper.cpp on :8178,
   PipeWire profile not Off — cite the known outage memory, device
   present) then launch with PARCEL_PROFILE=desk.

## OWNS
`configs/robot.desk.yaml` (new), `src/parcel_robot/voice_audio.py`
(marked region), `scripts/launch_desk_voice.sh` (new),
`src/parcel_robot/config.py` ONLY if a roster entry is genuinely needed
(one marked region, one subtree entry + census line in
tests/test_prototype_profile.py per the SENSE-1/AWARE-1 precedent),
`tests/test_ear1_desk_voice.py`, this folder.

## MUST NOT TOUCH
`runtime.py` (NARR-1 owns this wave's slot), `realtime/` (lane, driver,
audio_gateway), `agent.py`, other fences, git. Do NOT arm real audio
devices in tests — use the injectable `frames=` seam (voice_audio.py:394).

## Prove (capability tests only, ~5-7)
Multi-utterance PCM script through `frames=` → continuous re-segmentation
(N commits, no re-arm); channel-select picks the configured channel from
multi-channel frames; aec knob off = byte-identical path; echo-guard
suppression while playback_active; desk profile loads (overlay admission
green) with hosted lane absent; default behavior with no new keys
byte-identical.

## Rules
Guard wrapper (`--label ear1`), no `-n auto`, no `--tier`, no `noqa`,
ruff clean, no commit/push, owner's stack/store untouched. May TEST
against the real XVF3800 read-only (arecord-style capture probe) but the
pytest suite must pass without it. Short EAR1_STATUS.md.
