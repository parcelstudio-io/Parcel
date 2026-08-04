# Blocked work

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Ready to execute, waiting on something outside the repository. Each item names
the exact unblock action so nobody has to re-derive it.

---

## B1 — System packages for audio + the whisper build · **blocks U3, U4, U5, U9**

**Unblock:**

```bash
sudo apt install -y libportaudio2 cmake build-essential dfu-util
```

Verified missing on this desktop 2026-08-04: all four, plus `curl` (the B2
installer uses `wget`, which is present, so `curl` is optional). `sudo`
requires interactive authentication here, so an agent cannot run this.

**Then, in order:**

1. `.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"`
   — should print a device table instead of `PortAudio library not found`.
2. `scripts/install_speech_services.sh` — builds whisper.cpp v1.9.1, fetches
   Piper + the `en_US-lessac-medium` voice (both `.onnx` and `.onnx.json`).
3. `scripts/run_speech_services.sh --check` — must exit 0.
4. Start the panel with `speech.mode: audio` and hold a spoken conversation.

**What it unblocks:** the sprint's two outstanding definition-of-done items
(spoken conversation through a real mic; nods driven by real Piper audio) and
four UNVERIFIED entries.

---

## B2 — ONNX runtime + endpointing weights · **blocks U4**

**Unblock:** `.parcel/bin/pip install onnxruntime`, then fetch Silero VAD v6
and Smart Turn v3 into `models/endpointing/` (URLs are documented in
`src/parcel_robot/endpointing.py`). Set `speech.vad_model`, `speech.turn_model`,
and `speech.endpointing: semantic`.

Independent of B1 for the *model* work, though measuring real turn latency
needs a live microphone, so in practice do B1 first.

---

## B3 — ReSpeaker XVF3800 hardware · *in the post*

Ordered 2026-08-04 with a CQRobot 4 Ω 3 W JST-PH2.0 enclosed speaker. Full
arrival checklist, wiring constraint, and the speaker-specific cautions are in
[../scrum/20260804/B-audio-io.md](../scrum/20260804/B-audio-io.md) card B3.

The one thing worth repeating here: **the speaker must be wired to the array's
own JST amp output**. The AEC reference is the array's DAC path; a separate
USB speaker defeats echo cancellation entirely. And do not drive a 3 W driver
near clipping — a clipped speaker breaks AEC (the modelled echo is linear),
which shows up as barge-in false triggers rather than merely bad sound.

**Unblocks:** deleting the `echo_guard_scale` stopgap, real barge-in during
playback, and DoA-driven head orientation.

---

## B4 — Operator file deletion · *classifier-blocked for agents*

The 2026 redesign severed all code paths to the removed research trees, but
the files themselves are still on disk. Every candidate is archived at the
session scratchpad `deleted-archive/`. The prepared command (git rm from
`delete_list.txt`, then `rm -rf` of `src/parcel_robot/rl` and the BARN v5–v10
experiment trees) is in the earlier session transcript.

Low urgency: presence in the tree is not a production claim, and
[../docs/REDESIGN_2026_ASSESSMENT.md](../docs/REDESIGN_2026_ASSESSMENT.md) §6
says so explicitly. Do it when convenient; nothing depends on it.
