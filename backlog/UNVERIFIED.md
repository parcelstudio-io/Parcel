# Unverified claims register

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Everything here is code that exists and passes tests, but whose behaviour
nobody has confirmed against the thing it models. Ordered by how badly a wrong
assumption would hurt.

---

## U1 — Nothing has ever moved a real motor · **critical**

- **Claim:** Parcel navigates, follows, poses, and gestures.
- **Reality:** every number in this repository comes from simulation. The
  Unitree Sport supervisor has never run against hardware: SDK absent, NIC
  unconfigured, axes and frames uncommissioned, `allowed_modes` deliberately
  empty.
- **To verify:** velocity + E-stop bring-up on a physical Go2 through
  `ControlManager` only — never the joint path first. Confirm commanded vs
  measured SE2 velocity, and that a latched E-stop is feedback-confirmed.
- **Risk:** every latency, clearance, and success rate in the docs is a
  simulation result. Treat all of them as unvalidated until this closes.

## U2 — The simulator is kinematic, not dynamic · **critical**

- **Claim:** gait, pose, and expression previews show what the robot will do.
- **Reality:** `sim_control.PoseController` writes joint angles kinematically.
  There is no contact, slip, or balance model. Expression offsets are applied
  as an additive overlay on `qpos` — a real robot must absorb them through a
  balance controller that does not exist here.
- **To verify:** replay the same commands on hardware and compare foot
  placement and body attitude; specifically confirm the ±2 cm body-height and
  ±6° pitch expression clamps do not disturb stance.
- **Risk:** an expression amplitude that looks fine in sim could perturb
  balance on hardware. The clamps are argued, not measured.

## U3 — Prosody has never seen real speech · **major**

- **Claim:** `prosody.analyze_wav_chunk` finds the beats in the dog's voice.
- **Reality:** exercised only on synthetic acoustics — click trains, steady
  tones, and amplitude-modulated carriers. No Piper output, no human speech,
  no scored prosody corpus. Recall measured 50–75% on synthetic speech-like
  signals with varying F0, ~25% when F0 is constant (the acceptance rule is
  relative: "F0 above median **or** onset in top quartile").
- **To verify:** install Piper (blocked, see [BLOCKED.md](BLOCKED.md) B1),
  synthesize ~20 varied sentences, and check accent times against hand-marked
  stressed syllables. Target: accents land on perceptually stressed syllables
  at 1–3/s.
- **Risk:** nod timing could be systematically wrong on real TTS while every
  test stays green. The 3.46 ms `ApexToAccentError` is *scheduler* accuracy —
  it says nothing about whether the accents themselves are right.

## U4 — Semantic endpointing has never run a real model · **major**

- **Claim:** `speech.endpointing: semantic` gives ~200 ms turn commits.
- **Reality:** `onnxruntime` is not installed and neither model file exists.
  Every test drives `TurnEndpointer` through an injected `_infer`. Real
  Silero v6 / Smart Turn v3 accuracy and on-device latency are unknown. The
  config therefore ships defaulted to `energy`.
- **To verify:** `pip install onnxruntime`, fetch both weights, set
  `speech.endpointing: semantic`, and measure `TurnCommitLatency` over ~30
  real turns; compare false-commit rate against the energy path.
- **Risk:** the headline "~200 ms commit vs 500–800 ms fixed tail" win is
  projected from the model's published behaviour, not measured here.

## U5 — No audio device has ever been opened · **major**

- **Claim:** device selection by name/index works (`speech.input_device`).
- **Reality:** `libportaudio2` is absent, so `sounddevice` cannot import.
  Resolution logic is unit-tested against a stubbed device table only; the
  *unset* path and the loud-failure path are confirmed on this desktop, but no
  `InputStream` or `OutputStream` has ever been constructed.
- **To verify:** after the apt install (B1), run
  `.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"`,
  then start the panel in `speech.mode: audio` and confirm
  `/api/state → speech.input_device_detail` names the intended device.
- **Risk:** frame size, dtype, and blocksize negotiation with a real PortAudio
  backend is untested; a mismatch would surface only at first capture.

## U6 — Emote tags fire at synthesis time, not playback time · **major**

- **Claim:** an `[emote:play_bow]` tag makes the gesture land with the words.
- **Reality:** `SentenceChunkedSynthesizer(on_emote=...)` fires when the
  sentence is *synthesized*, which precedes playback by an unbounded queue
  delay. A4 built the correct anchor for this (`SpeakerSink` playback-start
  tokens, already used by `BeatLayer`) but the emote path was not moved onto
  it.
- **To verify:** move the emote trigger into `_audio_chunk_started` alongside
  the beat arming, epoch-tag it so barge-in cancels pending gestures, and add
  a test that a queued-but-superseded sentence fires no emote.
- **Risk:** with a deep audio queue the dog bows several seconds before it
  says the line. Unblocked — this is real work, not a dependency wait.

## U7 — The web viewer's JavaScript has never executed · **minor**

- **Claim:** `/viewer` renders gaze direction and the Expression HUD card.
- **Reality:** no JS runtime exists on this desktop (`node`, `deno`, `bun` all
  absent), so the edits were verified only by serving the page (HTTP 200,
  44,887 bytes, 8 `hudExpr` references) and re-reading the diff. Nobody has
  looked at the rendered page.
- **To verify:** open `/viewer` in a browser with the panel running; confirm
  the head/ear glyph swings with `head_yaw_rad` and the Expression card shows
  mode/producer/gaze/breath.
- **Risk:** a syntax error would blank the whole canvas, and the served-bytes
  check would still pass.

## U8 — Body breathing has never been seen in the MuJoCo viewer · **minor**

- **Claim:** the dog visibly breathes and shifts weight.
- **Reality:** confirmed numerically (±4 mm oscillation sampled live off
  `/api/state`, joint deltas unit-tested against the profile IK) but the
  MuJoCo viewer — the only place body height and pitch are actually visible —
  has not been opened since the expression overlay landed. The 2.5D web viewer
  deliberately shows numbers instead, because ±4 mm is sub-pixel there.
- **To verify:** run `parcel-sim`, stand the robot idle, and watch the torso.
- **Risk:** the sim-side `set_expression` overlay could be applying to the
  wrong joints in a way the unit tests' profile round-trip does not catch.

## U9 — B2 installer downloads were never fetched · **minor**

- **Claim:** `scripts/install_speech_services.sh` installs pinned, checksummed
  artifacts.
- **Reality:** pins and sizes come from GitHub/HuggingFace *metadata* APIs; no
  URL was actually retrieved. The one exception is `ggml-base.en.bin`, whose
  SHA256 was confirmed against the copy already in this repo. The Piper
  tarball layout is from documentation, not inspection, and its checksum is
  reported rather than enforced (rhasspy publishes none). The whisper.cpp
  build was never compiled. `shellcheck` is not installed, so the scripts were
  hand-checked against its rules.
- **To verify:** run the installer end to end once the toolchain exists (B1)
  and confirm every checksum gate passes.
- **Risk:** a moved URL or changed archive layout fails at first real use.

## U10 — Gestures have never executed on hardware · **minor**

- **Claim:** the curated emote catalog is safe to run.
- **Reality:** the allowlist excludes gaits, velocity skills, and postural
  settling, and dispatch is gated on `robot_stopped` — but every clip has only
  ever played in the kinematic sim. Joint velocity and acceleration limits are
  unchecked; the card's planned per-clip feasibility gates (joint limits,
  support-polygon stability) were deferred with the YAML schema upgrade.
- **To verify:** replay each admitted emote on hardware at intensity 1.0 and
  1.5 with a spotter, logging measured joint velocity against limits.
- **Risk:** an authored keyframe could demand a velocity the real actuators
  cannot deliver safely.

---

## Closed

*(none yet — add closures here with the date and the evidence that closed
them, so the register also records what has been genuinely confirmed)*
