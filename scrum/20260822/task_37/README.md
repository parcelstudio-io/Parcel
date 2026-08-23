# Task 37 — HW-4: `array-gateway` — the ear moves from Chrome to the XVF3800

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + anti-crash rules in `../BATCHB_DISPATCH_FABLE_4a.md`).
**Design:** `../WAVE3_HW_DESIGN_FABLE.md` §4 rows S11/S12/S13, §5.6, §9 HW-4.
**Evidence:** `task_25/SESSION.md` + `task_25/AIR1_STATUS.md` (the array is
16 kHz both ways; ch0 = Conference, ch1 = ASR beam; a mono request averages
beams; playback through the array's own DAC/amp or hardware AEC loses its
reference; udev/DoA rules), `tools/xvf3800_probe.py`, `AUDIT_WEEK1_FABLE.md`
§AIR-1 (the owed through-air session), codebase fact 13
(`BrowserAudioGateway` → `lane.send_audio` is the ONLY caller,
`runtime.py:8230` constructs it; `BrowserSink` plays hosted audio back).

## Why
Today the hosted Realtime lane's ear and mouth are a browser tab. On the dog
the ear is the XVF3800 on the Orin and the mouth is the array's amp. The
XVF3800 is the one piece of hardware on hand, so this card is measurable on
the desktop today, and the through-air tell (TV-on false barge-in ≤ 2 %) is
still owed from week 1.

## Work
1. `DESIGN.md` first: the `ArrayAudioGateway` seam — same `send_audio`
   contract as `BrowserAudioGateway`, PortAudio capture of ch1 (ASR beam) at
   16 kHz → resample to the lane's 24 kHz INSIDE the gateway (name the
   resampler: stdlib/`audioop`-free on 3.13+, so choose `numpy` polyphase or
   a vendored small resampler — justify), hosted audio 24 kHz → 16 kHz →
   the array's playback device (never a USB/Bluetooth speaker); the
   selection key `audio.gateway: browser|array` (default `browser`, no
   behaviour change); where TURN-1's endpointer and the hotword stop attach
   (they must be unchanged); what happens on device absence (typed refusal
   naming the udev rule, not a silent fallback to the browser).
2. Implement `ArrayAudioGateway` in `realtime/audio_gateway.py` (marked
   region) + the construction branch at `runtime.py:~8230` (marked; one
   `if`), + the config key as a new `OVERLAY_INTRODUCIBLE_KEYS` entry with a
   pin test (TRUTH-1's pattern in `config.py`).
3. Tests `tests/test_hw4_array_gateway.py`: the resamplers are exact on a
   synthetic tone (length and spectral peak within 1 bin both ways); the
   gateway feeds `lane.send_audio` with 24 kHz PCM16 mono in the same chunk
   contract as the browser path (read it; pin it); device-absent refusal;
   `audio.gateway` absent ⇒ browser gateway constructed (flag-off identity —
   `runtime.py` constructs exactly what HEAD constructs); seeded RED per
   guard.
4. Desktop measurement with the real array (it is on hand — `lsusb`
   2886:001a): `tools/xvf3800_probe.py` enumeration; a 30 s capture through
   the new gateway showing ch1 PCM at 16 kHz reaching `send_audio` at 24 kHz
   (a recording fixture under `~/.cache/parcel-hw4/`, sha in the doc); the
   corpus replay (`tests/test_realtime_corpus_replay.py`) green on the new
   path. The hosted lane is NOT opened ($0 spend; `PARCEL_REALTIME_KEY_ENV`
   unset); the through-air TV-on session (1.3 h, owner present) is an
   OWNER-GATED row with its exact command.

OWNS: `realtime/audio_gateway.py` `CARD HW-4` region, `runtime.py` one
marked branch at the gateway construction, `config.py` one introducible key
(marked), `tests/test_hw4_*.py`, `task_37/` docs, a runbook paragraph
appended to `task_25/SESSION.md` (marked). MUST NOT TOUCH: `lane.py`,
`duplex/`, `endpointing.py`, the broker, `tools/xvf3800_probe.py`,
`scripts/env-audio.sh` (HW-7), the owner's PipeWire config.

## Definition of done
Flag-off identity; resamplers exact; real-array capture reaches
`send_audio`; corpus replay green; seeds RED; owner-gated through-air row
written; `HW4_STATUS.md` with pre-registered rows.

## Hardware-compat (§e)
Class NEW (S11). Desktop proves the gateway with the real array; the Orin
proves PortAudio/aarch64 (HW-7) and the amp path. Never a USB/Bluetooth
speaker; 16 kHz both ways; ch1 for ASR.
