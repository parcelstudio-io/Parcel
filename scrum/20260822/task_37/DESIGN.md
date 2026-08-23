# HW-4 `array-gateway` — DESIGN

**Card:** `README.md` · **Seams:** design §4 S11/S12/S13, §5.6, §9 HW-4 ·
**Executor:** Claude Opus (parcel-6c wave 3a) · **Class (§e): NEW (S11).**

## (a) Purpose

Today the hosted lane's ear is a Chrome tab: `BrowserAudioGateway` is the ONLY
caller of `realtime.lane.RealtimeLane.send_audio`, and `BrowserSink` plays the
reply back through the same websocket. On the dog the ear is the reSpeaker
XVF3800 on the Orin and the mouth is that array's own amplifier. This card adds
a second gateway behind the *same* seam — `ArrayAudioGateway` — selected by one
config key, defaulting to the browser so that nothing changes for anyone who
does not write the key down. The XVF3800 is the one piece of hardware on hand,
so the seam is measurable on this desk today.

## (b) Architecture fit — the named seams

| seam (module:symbol) | who calls it on the product path | HW-4 |
|---|---|---|
| `realtime/lane.py:RealtimeLane.send_audio` (:1752) | `runtime.py:_realtime_owner_audio` (:8608), passed as `on_audio=` | unchanged; the array gateway calls the same callback with the same bytes |
| `realtime/audio_gateway.py:BrowserAudioGateway.accept_audio` (:1308) | `serve_websocket` reader thread | unchanged; `ArrayAudioGateway._on_capture` is its twin for a PortAudio callback |
| `realtime/browser_sink.py:PlaybackGateway` (`begin_utterance`/`send_audio`/`interrupt`/`played_started_monotonic`, + feature-detected `duck`/`accepts_interrupt_onset`) | `BrowserSink` ← `lane.pump()` | `ArrayAudioGateway` satisfies it structurally; `runtime.py` still returns `BrowserSink(gateway)` |
| `runtime.py:_build_realtime_sink` (:8173, construction at :8230) | `RobotRuntime.__init__` when `realtime.mode: audio` | ONE marked `if` chooses the class |
| `config.py:OVERLAY_INTRODUCIBLE_KEYS` (:109) | `check_overlay_keys` on every profile load | one new entry, `audio` |
| `duplex/turn_controller.py` + TURN-1 `protocol.TurnDetection` (S12) | wire field of `SessionUpdate`; `BrowserSink.duck`/`interrupt` | **untouched** — both live downstream of `send_audio`, so they cannot see which gateway produced the frame |
| the spoken emergency stop (`realtime/ingress.py`) | `runtime.submit_realtime_transcript` | **untouched** — it is built from the transcript that comes back, not from the audio that went up |

Composition with the batch-A/B regions: R17's tee (`SessionAudioCapture`) and
F1-SI's `VoiceIdentityGate` are passengers on the inbound frame. The array
gateway runs **the same three passengers in the same order** as
`accept_audio` — `capture.offer_owner(frame)`, then
`identity.observe_frame(frame)`, then `on_audio(frame)` — so a session recorded
through the array has the same shape of `owner.wav`, and F1-SI's verdict
arrives at the same point of the turn. The safety core is not on this path at
all.

## (c) Interfaces and contracts

```python
class ArrayAudioGateway:                       # realtime/audio_gateway.py
    def __init__(self, *, on_audio, on_mic=None, on_event=None,
                 clock=time.monotonic, lane_rate_hz=PCM16_SAMPLE_RATE_HZ,
                 array_rate_hz=ARRAY_RATE_HZ, device=None,
                 capture_channels=ARRAY_CAPTURE_CHANNELS,        # 2, never 1
                 capture_beam=ARRAY_ASR_CHANNEL,                 # ch1 (ASR)
                 frame_ms=DEFAULT_ARRAY_FRAME_MS,                # 40
                 capture=None, voice_identity=None, audio=None) -> None
```

* `ARRAY_RATE_HZ = 16_000` — the only rate the XVF3800 opens, **in both
  directions** (AIR-1 measured `Pa_IsFormatSupported`: 16 000 only, −9997 for
  8 k/22.05 k/24 k/44.1 k/48 k).
* `ARRAY_CAPTURE_CHANNELS = 2`, `ARRAY_ASR_CHANNEL = 1`. The device is opened
  with **two** channels and column 1 is taken. Asking PortAudio for one channel
  makes the stack average ch0 (Conference) and ch1 (ASR) — a third microphone
  that is neither beam (AIR-1 §4, MARK-1). This is a constant, not a knob.
* Refusal type `ArrayDeviceError(GatewayError)`. Device absent ⇒ raised, never a
  silent fall-back to the browser. Its text names the three things that can be
  missing, in the order you would check them: `lsusb` `2886:001a`,
  `source scripts/env-audio.sh` (PortAudio), and
  `/etc/udev/rules.d/99-respeaker-xvf3800.rules` (the rule `task_25/SESSION.md`
  §3 installs; without it the control interface is `Errno 13`).
* Config: `audio.gateway: browser | array` (default `browser`), plus
  `audio.device: <index|name fragment>` (default: match `"XVF3800"`).
  `RobotRuntime.audio_config` is the read site and refuses an unknown key by
  name, and an unknown `gateway` value by name.
* The runtime-facing surface `BrowserAudioGateway` already owes the runtime is
  reproduced: `bind_token`, `start`, `stop`, `running`, `close_mic`,
  `snapshot`. `set_mic(want_open)` asks `on_mic` first and stays shut if the
  runtime refuses — rule 2 ("connected is not listening") applies to a physical
  microphone exactly as it does to a browser one.

### The resampler, and why it is not `audioop`

`audioop.ratecv` was the obvious answer and it does not exist: PEP 594 removed
`audioop` in Python 3.13 and this tree runs 3.14 (`pyproject.toml:9`). `scipy`
is not a dependency and will not become one for this. **numpy is a base
dependency** (`pyproject.toml:12`, `numpy>=2,<3`), so the resampler is a small
streaming **rational polyphase FIR** built on numpy alone:

* 16 kHz → 24 kHz is exactly **L=3, M=2**; 24 kHz → 16 kHz is **L=2, M=3**.
  Rational, so there is no interpolation error to argue about — every output
  sample is a dot product of the prototype filter's phase `p = (n·M) mod L`
  with `K` real input samples.
* prototype = Kaiser-windowed sinc, cutoff `min(1/L, 1/M)` of the intermediate
  Nyquist, gain `L`, `K = 32` taps per phase. Cost ≈ 32 multiply-adds per
  output sample; a 40 ms frame is ~640 in / 960 out.
* **streaming**: the tail of the input is carried between calls, so chunk
  boundaries are not discontinuities. The alternative (resample each chunk
  independently) puts a click every 40 ms into the owner's audio and a
  broadband smear into the false-barge-in number this card exists to measure.
* linear interpolation — what the browser's `encodeMicFrame` does — is fine for
  its 48→24 **decimation** of an already-anti-aliased stream and wrong for a
  16→24 **upsample**, where the images at `16 kHz − f` land in the 8–12 kHz
  band the ASR reads.

## (d) Data flow and lifecycle

```
XVF3800 hw:N,0 ──PortAudio InputStream(16k, 2ch, int16, blocksize=640)──┐
   callback thread: take column 1 (ASR beam) ─► _Resampler(3/2) ─► PCM16 24k mono
      ─► capture.offer_owner ─► identity.observe_frame ─► on_audio ─► lane.send_audio
lane.pump ─► BrowserSink.enqueue ─► ArrayAudioGateway.send_audio(WAV 24k)
   ─► pcm_from_playback_chunk ─► _Resampler(2/3) ─► PCM16 16k ─► OutputStream(array DAC)
```

* One `threading.RLock` over the counters and the two stream handles; the
  PortAudio callback never takes a lock it can block on and never raises into
  PortAudio (an exception there is a dead stream, and a dead stream is a deaf
  robot). Every `except` names its exceptions — `ARRAY_THREAD_ERRORS`, plus
  `sounddevice.PortAudioError` through `_portaudio_errors(audio)` at the sites
  that talk to the device, because it subclasses `Exception` directly.
* **THE PLAYBACK STREAM IS THE CAPTURE CLOCK, so the two are opened together.**
  Corrected after measurement: this design first opened the output lazily, on
  the first `send_audio` chunk, so that an armed ear would hold no speaker.
  That is a good rule on hardware where it is true. On the XVF3800 both USB
  endpoints are SYNC and the capture endpoint does not stream unless the
  playback endpoint is running — capture alone returns `Input/output error` and
  zero frames through ALSA, PipeWire and PortAudio alike; the same capture
  beside a stream of digital ZEROS delivers 16 kHz exactly (this card measured
  0 frames in 30 s; its verifier measured 124 blocks in 5 s duplex; the fixed
  gateway then measured 751 frames in 30.04 s). `_open_capture` opens the
  output first, then the input; `_close_capture` closes both. What reaches the
  amplifier while nobody is talking is silence from `_on_playback`'s own fill.
* **The reader thread starts LAST**, after `_in_stream` is assigned. It used to
  start first, and `_reader_loop` exits when `_in_stream` is `None` and its
  queue is empty — so any device whose open took longer than `DEFAULT_POLL_S`
  (50 ms) lost its reader silently, dropped every block at the queue bound, and
  disabled `_check_deaf` (which lives in that loop) into the bargain.
* **The device is opened BEFORE the runtime is asked for consent.** `on_mic` is
  `runtime._realtime_mic_gesture`, and that opens a *billed* hosted session; a
  device refusal after it would leave the owner paying for a lane with no ear.
  Rule 2 ("existing is not listening") therefore moves one layer down:
  `_offer_block` drops and counts (`frames_dropped_unarmed`) every frame until
  `_mic_open` is true, so nothing reaches `on_audio`, the tee or the identity
  gate before the gesture.
* `set_mic(False)` / `close_mic()` / `stop()` all close both streams;
  `runtime.close()` (:4448) already calls `stop()`. `abort()` is tried before
  `stop()`: `Pa_StopStream` waits for a stream to drain and a stream that never
  clocked never drains.
* No new process, no new file, no new socket.

## (e) Hardware compatibility — class NEW (S11)

* **Venue-independent by construction:** the seam. `lane.send_audio`,
  `BrowserSink`, TURN-1's endpointing and the hotword stop see PCM16 mono at
  24 kHz whichever gateway produced it, so S12's "same corpus replay on
  aarch64" is true for this path by construction and is asserted here on x86.
* **Must-configure on the dog:** `audio.gateway: array` plus `audio.device`;
  `scripts/env-audio.sh` needs an aarch64 variant (HW-7 owns that); the speaker
  must be on the array's **own JST-PH2.0 amp header**, never a USB or Bluetooth
  speaker, or the XVF3800's canceller is referencing audio it never emitted.
* **UNKNOWN until the Orin:** PortAudio/ALSA device naming and index on
  aarch64; whether the Orin's USB stack sustains a 16 kHz duplex stream under
  load; the amp's real ERLE in the dog's chassis. None of them is decidable
  here and none is claimed.
* What the desktop **cannot** prove: anything about the Orin, the dog, or the
  amp; and — because the owner's speaker, TV and enrolled voice are owner
  actions — the through-air false-barge-in tell (S11's "first proof"), which
  stays an OWNER-GATED row with its exact command.

## (f) Test strategy → the pre-registered rows

`tests/test_hw4_array_gateway.py`: resampler exactness on a synthetic tone both
ways (length exact, FFT peak within 1 bin); the `send_audio` chunk contract
read off the browser path and pinned, then met by the array gateway; the
device-absent refusal typed and naming the udev rule; **flag-off identity**
through the real `_build_realtime_sink` with no monkeypatch of any gateway
class; a corpus fixture replayed through a real `RealtimeLane` into an
`ArrayAudioGateway` playback device. Each guard gets a seeded-RED proof on a
byte-identical scratch copy. The measurement rows are the real array
(`lsusb` 2886:001a → `tools/xvf3800_probe.py` → a 30 s capture through the new
gateway to `~/.cache/parcel-hw4/`), the existing corpus-replay suite green, and
the OWNER-GATED through-air session.

## (g) Risks and what this design does NOT cover

1. **Nothing arms the array's microphone yet, so array mode is script-only.**
   `web_panel.py:493` gates the websocket on
   `isinstance(gateway, BrowserAudioGateway)`, so in array mode
   `/api/realtime/audio` 404s, the panel's mic button has no route to
   `set_mic`, and because arming is what opens the hosted session there is no
   ear AND no mouth from the product. `web_panel.py` is not this card's OWNS.
   HANDOFF H-1, with the minimal route written out in `HW4_STATUS.md`; the
   measurement drives the product `set_mic` directly, which is the same method
   that route would call.
2. **The mouth carries a signal only in tests.** The playback stream is open
   against the real array (it has to be — it is the capture clock), but the
   only thing this card ever sent through it is digital zero. Its 24 → 16 kHz
   half is proved against the lane's real WAV chunks and a fake device. What an
   actual voice sounds like out of that amp is owner-gated (O1).
3. **`audio` is exempted as a SUBTREE**, because `check_overlay_keys` stops
   descending at an exempt parent — an `"audio.gateway"` entry would look like
   a spelling guard and be inert, which is the exact anti-pattern ROAM-1 and
   TRUTH-1 record. The typo check therefore lives at the read site, like
   `roam`'s and `planner_model`'s.
4. **Echo cancellation is the array's, not ours.** No AEC, no ducking maths and
   no `echo_guard_scale` is touched. If the speaker is off the array's DAC the
   canceller has no reference and the false-barge-in row misses; that is a
   session finding, not something code here can fix.
5. Not covered: the hosted lane's link (S13), DoA/sector rejection, the mux
   measurement path, and `tools/xvf3800_probe.py` (MUST NOT TOUCH).
