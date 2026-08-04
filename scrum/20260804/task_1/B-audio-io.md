# Workstream B — real audio input/output

Goal: a spoken conversation with the sim dog through a real microphone and
speaker on this desktop **today** (echo-guard mode), and a plug-in-ready path
for the ReSpeaker XVF3800 when it arrives. Design source:
[../../../docs/RESEARCH_2026_ROADMAPS.md](../../../docs/RESEARCH_2026_ROADMAPS.md) §1.

## Operator install runbook (this machine — run once)

Verified state 2026-08-04: `sounddevice` 0.5.5 already in `.parcel`;
`alsa-utils` installed; **`libportaudio2` MISSING** (this is why the mic loop
currently degrades to text with "PortAudio library not found").

```bash
# 1. PortAudio + a toolchain for the whisper.cpp build + DFU for XVF3800 firmware.
#    (Verified missing on this desktop 2026-08-04: libportaudio2, cmake,
#    build-essential, curl. wget IS present and is what the installer uses.)
sudo apt install libportaudio2 cmake build-essential dfu-util

# 2. ONNX runtime for workstream A endpointing models
.parcel/bin/pip install onnxruntime

# 3. Sanity: list devices, then a 3 s loopback test with the default mic/speaker
.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"
arecord -r 16000 -f S16_LE -d 3 /tmp/mic_test.wav && aplay /tmp/mic_test.wav
```

whisper.cpp + Piper are installed by the B2 scripts below (no sudo needed)
**after** that toolchain exists — the installer preflights and stops with a
clear apt hint otherwise. Note `run_speech_services.sh` can already bring
whisper up from the prebuilt release tree in `third_party/whisper.cpp-bin/`
without building, but Piper must be installed for `speech.mode: audio` to
pass its fail-closed TTS gate.

## B1 — Audio device selection + desktop bring-up · **Owner: Claude Opus**

Today `MicrophoneVoiceLoop._sounddevice_frames` and `SpeakerSink._play` both
use the system-default device; there is no way to pin Parcel to a specific
mic/speaker. Add:

- `speech.input_device` / `speech.output_device` config keys (int index or
  substring name match, resolved via `sounddevice.query_devices`; unset →
  default device, current behavior). Thread through `build_speech_stack` →
  `MicrophoneVoiceLoop(device=...)` / `SpeakerSink(device=...)`.
- Resolution errors at startup → the existing loud degrade-to-text path (the
  B-series must never invent a new failure mode).
- Extend the mic preflight (`start()`) to check the *selected* device.
- Snapshot: `speech.input_device_detail` / `output_device_detail` (resolved
  name), so `/api/state` shows which physical device is live.
- Tests: name-substring resolution against a stubbed `query_devices`, bad
  device → degrade path, config default passthrough.
- Runbook addendum in this file: the exact command to start the panel in audio
  mode and a troubleshooting table (no device / permission / busy device).

Acceptance: on this desktop with B2 services running, `speech.mode: audio`
starts, speaking to the default mic produces a transcript event in
`/api/state`, and the reply plays audibly. Echo-guard barge-in expectations
documented (owner must speak up over the robot until the XVF3800 arrives).

### B1 runbook (implemented 2026-08-04)

Config keys (both optional, under `speech:` in `configs/robot.yaml`):

```yaml
speech:
  input_device: ReSpeaker    # PortAudio index, or a case-insensitive
  output_device: ReSpeaker   # substring of the device name
```

Name matching is preferred over an index: a USB array's index moves between
reboots, the name does not. List candidates with

```bash
.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"
```

Resolution semantics (`voice_audio.resolve_audio_device`):

- **unset** → system default, and it never enumerates devices, so a host with
  no PortAudio at all still starts in text mode exactly as before;
- **set but unresolvable** → the runtime emits a `voice` warning
  (`Configured input audio device 'X' is unusable: …; falling back to the
  system default`) and continues on the default rather than silently opening
  the wrong hardware;
- devices are filtered by direction, so `input_device: HDMI` fails rather
  than matching an output-only device, and an ambiguous substring lists the
  candidates instead of guessing.

Both resolved names appear in `/api/state` under
`speech.input_device_detail` / `speech.output_device_detail`, so the panel
always shows which physical device is live.

Start the panel in audio mode:

```bash
scripts/run_speech_services.sh          # whisper.cpp up (card B2)
.parcel/bin/python -m parcel_robot.web_panel --config configs/robot.yaml
```

| Symptom | Cause | Fix |
|---|---|---|
| `Speech: stt=…unreachable` | whisper-server not running | `scripts/run_speech_services.sh` |
| `Microphone unavailable: audio capture unavailable: PortAudio library not found` | system dep missing | `sudo apt install libportaudio2` |
| `…is unusable: no input device matches 'X'` | name/index wrong | re-list devices; match on a distinctive substring |
| `…is ambiguous (0:…, 3:…)` | substring matches several | use a longer substring or the index |
| Device busy / permission denied | another process holds it | close it, or add the user to the `audio` group |
| Robot transcribes its own speech | no AEC yet | raise `speech.echo_guard_scale`, or fit the XVF3800 (B3) |

## B2 — Speech services install scripts · **Owner: Claude Opus**

New `scripts/install_speech_services.sh` + `scripts/run_speech_services.sh`
(idempotent, no sudo, everything under `third_party/` and `models/` which are
gitignored — verify, and add ignore entries if missing):

- **whisper.cpp**: clone pinned tag into `third_party/whisper.cpp`, cmake
  build, download `ggml-base.en.bin` into `models/whisper/`. Run script
  launches `whisper-server` on `127.0.0.1:8178` (the configured
  `speech.whisper_url`) and waits for `/health`.
- **Piper**: download the pinned release binary into `third_party/piper/`,
  download voice `en_US-lessac-medium` as `models/piper/voice.onnx` **and**
  `models/piper/voice.onnx.json` (the runtime auto-reads the sample rate from
  that JSON — do not omit it).
- Both scripts print resolved versions + SHA256 of downloads; failures are
  explicit (no partial silent installs). Document expected disk/CPU footprint.
- Smoke test target: `scripts/run_speech_services.sh --check` probes both
  health endpoints and exits nonzero with a reason.

Acceptance: fresh run of both scripts on this machine → `build_speech_stack`
reports `stt=whisper.cpp at http://127.0.0.1:8178`, `tts=piper (...)` in the
startup voice event; `speech.mode: audio` passes its fail-closed gate.

## B3 — XVF3800 arrival checklist · **Owner: Claude Opus** · *blocked on shipping*

Hardware (ordered 2026-08-04): Seeed ReSpeaker XVF3800 USB 4-mic array +
**CQRobot 4 Ω 3 W JST-PH2.0 enclosed speaker** wired to the array's own JST amp
output (**mandatory** — the AEC far-end reference is the array's own DAC path;
a separate USB speaker defeats echo cancellation).

Speaker notes for the part actually purchased:

- **Impedance is right.** 4 Ω sits in the XVF3800's supported 4–8 Ω range and
  is the louder end of it — good for being heard over a walking robot.
- **Power headroom is the thing to watch.** The board's amp can drive more
  than this driver's 3 W rating. Do not run it near maximum: set the system
  output volume so normal speech peaks sit well below clipping, and confirm
  by ear that loud sentences stay clean. A clipping speaker wrecks AEC (the
  echo the canceller predicts is linear; a clipped one is not), so distortion
  shows up as *barge-in false triggers*, not just bad sound.
- **The enclosure is a real advantage.** An enclosed driver has a far more
  predictable response than a bare cone, which is exactly what the echo
  canceller wants; it also keeps the acoustic path from coupling straight
  into the chassis.
- **Mount it away from the mic array and off the leg servos.** Vibration
  through a shared plate is structure-borne echo that the AEC cannot see.
- Record the volume setting that passed step 4 below; treat it as a
  calibration constant, not a preference.

On arrival:
1. Plug in USB → it enumerates as a standard USB Audio Class device (no
   driver). Verify with `arecord -l` / `aplay -l` / `sounddevice.query_devices`.
2. Set `speech.input_device: ReSpeaker` and `speech.output_device: ReSpeaker`
   (B1 is implemented — name matching, so the index may move freely). Confirm
   `/api/state` → `speech.input_device_detail` names the array. Its processed
   capture stream is 16 kHz — matches `SAMPLE_RATE_HZ` exactly.
3. Fetch Seeed's `xvf_host` control utility (per the Seeed XVF3800 wiki);
   verify firmware version, test `AEC_AZIMUTH_VALUES` (DoA readout) — record
   the exact commands here for the repo.
4. Validation: play TTS through the array's speaker while recording the
   processed capture; robot speech must be absent from the capture (AEC
   working). Then run the barge-in test: interrupt mid-sentence at normal
   voice volume.
5. **Only after step 4 passes:** drop `speech.echo_guard_scale` to 1.0 (guard
   effectively off) via config — keep the code path; it is the fallback for
   non-AEC hosts. Update `docs/REDESIGN_2026_ARCHITECTURE.md`'s AEC row.
6. Stretch: expose DoA azimuth as a context feed for workstream A's
   head-orient hook (replaces owner-bearing guess when hardware is present).
