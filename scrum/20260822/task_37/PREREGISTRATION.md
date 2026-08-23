# HW-4 `array-gateway` — PREREGISTRATION

Written **before** any row was measured. Rows are measured as written; a miss
is a miss with its mechanism, and no threshold moves afterwards. Every pytest
row runs through `~/.cache/parcel-guard/pytest_guard.sh --label hw4` with
`env -u TMPDIR`. `PARCEL_REALTIME_KEY_ENV` is unset for every row: **$0**.

Executor: Claude Opus (wave 3a, parcel-6c). Card: `README.md`. Design:
`DESIGN.md`.

> **One correction, declared.** A1/A2's closed form for the output length was
> written as `((N-1)*L)//M + 1` and is `(N*L - 1)//M + 1`. Corrected here at
> 13:2x EDT, **before any resampler existed and before any row was measured**;
> nothing else moved. Pre-correction sha256
> `232e46338d770ac4eeec9f0f2a54afebb68db81c6bccb9ed1d469fa94b655a43`.

## A · Code rows (hermetic, no hardware)

| id | row | command | threshold |
|---|---|---|---|
| **A1** | 16 kHz → 24 kHz resample is exact on a synthetic tone | `pytest tests/test_hw4_array_gateway.py::test_the_up_resampler_is_exact_on_a_tone` | input = 1.000 s of a 1 000 Hz sine at 16 000 Hz, 0.5 FS, int16 (16 000 samples). Output length **exactly** `(16000*3 - 1)//2 + 1 = 24 000` samples. Peak of the output's rFFT within **1 bin** of 1 000 Hz. |
| **A2** | 24 kHz → 16 kHz resample is exact on a synthetic tone | `…::test_the_down_resampler_is_exact_on_a_tone` | input = 1.000 s of a 1 000 Hz sine at 24 000 Hz, 0.5 FS, int16 (24 000 samples). Output length **exactly** `(24000*2 - 1)//3 + 1 = 16 000` samples. Peak within **1 bin** of 1 000 Hz. |
| **A3** | the resamplers do not smear the band (auxiliary, fixed here) | same two tests | with a Hann analysis window, the energy **outside** 1 000 ± 150 Hz is ≤ **−40 dB** of the in-band energy, both directions. |
| **A4** | streaming is not per-chunk | `…::test_the_resampler_is_chunk_size_invariant` | feeding the A1 tone in 1, 7, 640 and 4 096-sample chunks yields **byte-identical** output to feeding it in one call. |
| **A5** | the browser chunk contract is pinned from its two sources | `…::test_the_browser_chunk_contract_is_what_this_card_pins` | `BrowserAudioGateway(...).hello()["input"] == {"format": "pcm16", "rate": 24000, "channels": 1, "max_frame_bytes": 32768}`; `src/parcel_robot/ui/index.html` still contains `const frames = 2048;`, `createScriptProcessor(frames, mic.captureChannels, 1)` and `encodeMicFrame(event.inputBuffer.getChannelData(ear), mic.capture.sampleRate, mic.rate)`; `accept_audio` refuses `> 32768` bytes and drops empty payloads. |
| **A6** | the array gateway MEETS that contract | `…::test_the_array_gateway_feeds_the_lane_the_browser_contract` | every payload handed to `on_audio` from a fake 16 kHz 2-channel PortAudio stream is: non-empty; an **even** byte count; **≤ 32 768** bytes; decodes as **mono PCM16 at 24 000 Hz**; duration `40 ms ± 1` output sample at `frame_ms=40`; and the **whole** capture, concatenated, equals the resampler's output for column **1** of the input (never column 0, never the average). |
| **A7** | the three passengers run in the browser's order | `…::test_the_tee_and_the_identity_gate_ride_in_the_same_order` | recorded call order per frame is `capture.offer_owner` → `identity.observe_frame` → `on_audio`, identical to `accept_audio`'s, with the same bytes. |
| **A8** | the playback half resamples 24 → 16 and never opens a device until it must | `…::test_playback_unwraps_the_wav_and_reaches_the_array_at_16k` | a real 24 kHz WAV chunk from the lane reaches the fake output device as PCM16 at **16 000 Hz**; no output stream is opened before the first non-empty `send_audio`; `played_started_monotonic` is `None` before the first chunk and a float after. |
| **A9** | device absent ⇒ a **typed** refusal that names the fix | `…::test_an_absent_array_is_a_typed_refusal_naming_the_udev_rule` | `set_mic(True)` with no matching device raises `ArrayDeviceError` (a `GatewayError`); the message contains `2886:001a`, `scripts/env-audio.sh` and `/etc/udev/rules.d/99-respeaker-xvf3800.rules`; the gateway is **not** replaced by a `BrowserAudioGateway` and `mic_open` stays `False`. |
| **A10** | **FLAG-OFF IDENTITY** through the real construction path | `…::test_with_no_audio_key_the_runtime_builds_exactly_what_head_builds` | with no `audio:` block, `web_panel.build_runtime` (real base `configs/robot.yaml`, real `PARCEL_REALTIME_CONFIG` with `mode: audio`) yields `type(runtime.realtime_gateway) is BrowserAudioGateway`, a `BrowserSink` sink, `on_audio` bound to `RobotRuntime._realtime_owner_audio`, `on_mic` to `_realtime_mic_gesture`, `capture is None`, and `sample_rate_hz == 24000`. **No monkeypatch of any gateway class.** |
| **A11** | the flag ON selects the array through the same path | `…::test_the_audio_gateway_key_selects_the_array` | the same call with a real sibling profile overlay `audio: {gateway: array}` yields `type(runtime.realtime_gateway) is ArrayAudioGateway`; construction opens **no** audio device. |
| **A12** | the key is introducible, and the guard is at the read site | `…::test_the_audio_section_is_introducible_and_its_typos_are_refused` | `"audio" in OVERLAY_INTRODUCIBLE_KEYS`; **no** `audio.` child is listed; `check_overlay_keys(base, {"audio": {"gatewayy": "array"}})` **merges** (the subtree is exempt); `resolve_audio_gateway_selection({"gatewayy": "array"})` raises `ValueError` naming `gatewayy`; an unknown VALUE (`gateway: chrome`) raises `ValueError` naming it; `{}` and `None` resolve to `browser`. |
| **A13** | CAP-1's survey stays empty | `…::test_the_survey_of_unreachable_config_sections_is_still_empty` | `{s for s in admission.product_config_sections() if s not in base and s not in OVERLAY_INTRODUCIBLE_KEYS} == set()`. |
| **A14** | corpus replay on the **new path** | `…::test_a_corpus_fixture_replays_through_the_array_gateway` | one corpus fixture, a real `RealtimeLane` against `FakeRealtimeServer`, sink = `BrowserSink(ArrayAudioGateway(...))`: the ledger rows match the fixture exactly, and the fake array device received PCM16 mono at 16 000 Hz whose sample count equals `2/3` of the lane's 24 kHz payload (± 1 sample per chunk boundary). |
| **A15** | the existing corpus-replay suite is unchanged | `pytest tests/test_realtime_corpus_replay.py` | **all pass**, 0 failed, 0 error. |
| **A16** | the touched suites are unchanged | `pytest tests/test_prototype_profile.py tests/test_cap1_admission.py tests/test_truth1_texts.py tests/test_air1_rate_pin.py tests/test_realtime_audio_gateway.py` (plus any `test_browser_sink`/`duplex1` file that exists) | **all pass**. |
| **A17** | lint | `.parcel/bin/ruff check <OWNS>` and `.parcel/bin/ruff format --check <OWNS>` | clean; `scripts/ci_ruff_baseline.json` count **7**, unchanged, no `noqa` added. |

## B · Seeded RED (one per new guard, on a byte-identical scratch copy)

Scratch = `rsync -a --exclude .cache --exclude .parcel --exclude .git` of
`src/ scripts/ tools/ tests/ configs/ prompts/` into
`~/.cache/parcel-hw4/scratch/`, run with `PYTHONPATH=<scratch>:<scratch>/src`
and `parcel_robot.__file__` **verified inside the scratch**, restored by
sha256, `__pycache__` purged. Never the working tree.

| id | seed | must redden |
|---|---|---|
| **S1** | resampler returns linear interpolation instead of the polyphase filter | A1/A2/A3 |
| **S2** | the capture callback takes column 0 (Conference) instead of column 1 | A6 |
| **S3** | the capture callback opens the device with `channels=1` (the downmix) | A6 |
| **S4** | `set_mic` falls back to a `BrowserAudioGateway` when the device is absent | A9 |
| **S5** | the runtime branch selects the array whenever the `audio` section exists | A10 |
| **S6** | `resolve_audio_gateway_selection` accepts an unknown key | A12 |
| **S7** | the playback half writes the lane's 24 kHz PCM straight to the array | A8 |

## C · Real-array rows (the XVF3800 is on hand; nothing is played through it)

| id | row | command | threshold |
|---|---|---|---|
| **H1** | the array is on the bus | `lsusb \| grep 2886:001a` | one line, recorded verbatim. |
| **H2** | the probe agrees with `task_25/SESSION.md` | `source scripts/env-audio.sh && .parcel/bin/python tools/xvf3800_probe.py --json ~/.cache/parcel-hw4/probe.json` | `alsa` capture `[16000] Hz x2 S16_LE`, playback `[16000] Hz x2`; `rates` input accepts `['16000']`. A disagreement is itself the finding and is recorded, not fixed. |
| **H3** | **30 s of the real array through the new gateway** | `source scripts/env-audio.sh && .parcel/bin/python ~/.cache/parcel-hw4/capture_30s.py` — a script that constructs the product `ArrayAudioGateway` with `on_audio` appending to a list, calls the product `set_mic(True)`, waits 30 s, `set_mic(False)` | ≥ 29.0 s of PCM reaches `on_audio`; every payload meets **A6**'s contract; the concatenated stream is written to `~/.cache/parcel-hw4/capture_30s_24k.wav` (mono PCM16 @ 24 000 Hz) with its **sha256** in the status doc; the 16 kHz ch1 source is written beside it as `capture_30s_16k_ch1.wav` with its sha256. **Input only — the array's amplifier is never driven.** If the device cannot be opened, the exact error text is the row's result and no number is estimated. |
| **H4** | the capture is not silence and not a downmix | same script's JSON summary | ch1 RMS > ch0 RMS is NOT asserted (the room decides); what IS asserted: dBFS of the 16 kHz ch1 stream is recorded, and it is **> −80 dBFS** (i.e. the stream is not digital silence). |

## D · OWNER-GATED (not claimed; commands only)

| id | row | command | threshold |
|---|---|---|---|
| **O1** | AIR-1's owed through-air session, **on this gateway** | the full `task_25/SESSION.md` session (~1.3 h, owner present, speaker on the array's JST-PH2.0 amp, TV for step 9), with `configs/robot.prototype.yaml` carrying `audio: {gateway: array}` and `scripts/launch_stack.sh --prototype`; scored by `.parcel/bin/python tools/bargein_through_air.py …` exactly as `SESSION.md` §10 writes it | `false_barge_in_rate` ≤ **2 %** (S11's first proof), `asr_beam_echo_attenuation_db` ≥ **20 dB**. |
| **O2** | the panel arm route for array mode | — | there is none today (`web_panel.py:493` gates the websocket on `isinstance(gateway, BrowserAudioGateway)`); **HANDOFF**, not a row this card measures. |

## E · What no row here can prove

The Orin, the Go2, aarch64 PortAudio, the amp's real ERLE, and anything about
the hosted provider (the lane is never opened; $0). The playback half is proved
against the lane's real WAV chunks and a fake device only, because the COMMON
brief forbids playing audio through the owner's array.
