# HW-4 status — the ear is the XVF3800, and its mouth is its clock

> **Correction pass appended at the bottom (2026-08-23 14:2x EDT), after the
> verifier's HOLD.** Everything above the `## Correction pass` heading is the
> FIRST pass, kept verbatim so the record shows what was believed and when —
> including the H3 miss, which was a defect in this card's own design and not
> a broken array. Read the correction section for the rows that now hold.

**Executor:** Claude Opus (wave 3a, parcel-6c session 31fcc2a0) · **Verifier:** Fable
**Card:** `README.md` · **Design:** `DESIGN.md` · **Pre-registration:**
`PREREGISTRATION.md` (sha256 `8683860f3a3e8feddfe0e81cfff78019a738eacadd6eba180c03d45b47ddae13`)
**HEAD at start:** `939001e` — batch B was COMMITTED before this card began, so
the 6c dispatch's "batch B is STAGED in the index (118 paths)" is superseded and
`git diff -- <file>` is the right diff to read. It is HW-4-only for every OWNS
file **except `src/parcel_robot/runtime.py`**, where HW-1 landed its own marked
region during this card; the hunk-level attribution is below.

## Headline

`ArrayAudioGateway` is in, behind the same `send_audio` seam the browser
gateway presents, selected by one new config key `audio.gateway: browser|array`
that defaults to `browser`. **Flag-off identity is proved through the real
`RobotRuntime._build_realtime_sink`, with a real `configs/robot.yaml` and a real
profile overlay on disk, and with no gateway class monkeypatched anywhere** —
with no `audio:` block the runtime constructs exactly the `BrowserAudioGateway`
it constructed at HEAD, with the same five keyword arguments. The resamplers are
exact: 16 → 24 kHz produces 24 000 samples from 24 000, peak at 1 000.0000 Hz
(1 Hz bins), out-of-band energy **−88.5 dB**; 24 → 16 kHz produces 16 000 from
16 000, peak at 1 000.0000 Hz, **−91.7 dB**. Twenty-six tests, eight seeded-RED
proofs on a byte-identical scratch, zero new ruff fingerprints, $0 spent.

**[FIRST PASS — SUPERSEDED BY THE CORRECTION SECTION.] And the headline
hardware row MISSED, for a reason worth the whole measurement.** The reSpeaker XVF3800 on this desk enumerates (`lsusb`
2886:001a), advertises 16 kHz S16_LE × 2 in **both** directions, opens, reports
`stream.active == True` — and returns `Input/output error` on the first capture
read. Thirty seconds through the product gateway yielded **zero frames**.
Reproduced identically outside Parcel through ALSA (`arecord -D hw:1,0` and
`plughw:1,0`), through PipeWire (`pw-record`), through PortAudio directly, and
through this card's own `tools/xvf3800_probe.py --rms`. The array's capture
mixer is on at 90 %/100 %; nothing holds the PCM node; the ACL grants access.
No Parcel code is implicated and none can fix it.

What that miss bought: the gateway sat there **looking perfectly armed** —
`mic_opens: 1`, `capture_errors: 0`, no exception, every counter healthy — while
delivering nothing. That is the worst shape this failure can take, and it is now
a reported fact (`ArrayAudioGateway._check_deaf`, `deaf_warnings`), added after
the row missed and declared as such below.

## What changed

`git diff --stat` restricted to this card's OWNS:

```
 scrum/20260822/task_25/SESSION.md          |   51 ++     (one marked addendum)
 src/parcel_robot/config.py                 |   25 +      (one marked entry)
 src/parcel_robot/realtime/audio_gateway.py | 1083 ++++   (three marked regions)
 src/parcel_robot/runtime.py                |   67 +- 8   (one marked branch; see note)
 tests/test_prototype_profile.py            |   14 +      (one marked entry; DEVIATION D1)
```

New files: `tests/test_hw4_array_gateway.py` (936 lines, 26 tests),
`scrum/20260822/task_37/{DESIGN,PREREGISTRATION,HW4_STATUS}.md`.

> **`runtime.py`'s `--stat` is shared.** HW-1 (task_35) landed its own marked
> region in the same file while this card was running, so `git diff --stat`
> reports 59 insertions / 8 deletions for the file. By hunk
> (`git diff -U0 | awk`): HW-1 owns `@@ -13 +13 @@` (+1 −1, the `timezone`
> import) and `@@ -373,0 +374,12 @@` (+11, its `UTC = timezone.utc`
> re-export). **HW-4 owns exactly the two hunks at `_build_realtime_sink`:
> `@@ -8230,6 +8242,16 @@` (+16 −6) and `@@ -8236,0 +8259,29 @@` (+27) — 43
> insertions, 6 deletions, all inside one `# ---- CARD HW-4 (task_37)` /
> `# ---- END CARD HW-4` pair.**

Outside the repo (never in the tree): `~/.cache/parcel-hw4/capture_30s.py`,
`capture_30s.json`, `probe.json`, `capture_30s_{24k,16k_ch1}.wav`, `scratch/`.

**The seam, in one line each.**

* `realtime/audio_gateway.py` — `RationalResampler` (streaming polyphase FIR on
  numpy), `ArrayAudioGateway`, `ArrayDeviceError`,
  `resolve_audio_gateway_selection`, the array constants, plus one marked
  `import numpy as _np` in the import block and the `__all__` additions.
* `runtime.py:_build_realtime_sink` — ONE marked `if/else`. The `else` arm is
  HEAD's construction verbatim, re-indented.
* `config.py` — `"audio"` added to `OVERLAY_INTRODUCIBLE_KEYS` with TRUTH-1's
  reasoning. One entry, not two: `check_overlay_keys` stops descending at an
  exempt parent, so an `"audio.gateway"` entry would look like a spelling guard
  and be inert. The typo check is at the read site.

**The chunk contract this card pinned** (row A5, read off both sources in the
test, not restated): the browser sends **mono PCM16 little-endian at 24 000 Hz**
(`hello()["input"] == {"format": "pcm16", "rate": 24000, "channels": 1,
"max_frame_bytes": 32768}`), produced by `ui/index.html`'s
`createScriptProcessor(frames=2048, mic.captureChannels, 1)` resampled from the
capture context's hardware rate by `encodeMicFrame` — 2 048 bytes ≈ 42.7 ms at a
48 kHz capture context. `accept_audio` refuses anything over 32 768 bytes and
drops empty payloads; every accepted frame goes whole to `on_audio`. The array
gateway meets it at `frame_ms=40`: **1 920 bytes = 960 samples = 40.0 ms**, mono
PCM16 LE at 24 000 Hz, from column **1** (ASR beam) of a **two**-channel open.

## How verified

Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label hw4` with
`env -u TMPDIR`; never `-n auto`; never `ci_gate.py --tier`; pre-flight
`free -g` available ≥ 231 GB and pytest count ≤ 1 before every run; **no exit
137 anywhere** in `guard.log` (`grep 'label=hw4' | grep -c rc=137` → 0).
`PARCEL_REALTIME_KEY_ENV` unset throughout: **$0**.

### Code rows

| row | verdict | result |
|---|---|---|
| A1 16→24 exact | **MET** | 16 000 in → **24 000** out `= (16000*3-1)//2+1`; peak **1000.0000 Hz**, 1.00000 Hz bins |
| A2 24→16 exact | **MET** | 24 000 in → **16 000** out `= (24000*2-1)//3+1`; peak **1000.0000 Hz** |
| A3 out-of-band ≤ −40 dB | **MET** | **−88.5 dB** (up), **−91.7 dB** (down) |
| A4 chunk-size invariant | **MET** | byte-identical at 1, 7, 640, 4 096 samples |
| A5 browser contract pinned | **MET** | from `hello()` and `ui/index.html`, in the test |
| A6 array meets it | **MET** | 25 blocks; every frame 1 920 B / 960 samples; stream opened `channels=2, samplerate=16000, dtype=int16, blocksize=640`; concatenation equals the resampler's own output for column 1; the 300 Hz conference beam is **> 40 dB** below the 1 kHz ASR beam |
| A7 rider order | **MET** | `tee → identity → lane`, same bytes, identical to `accept_audio`'s |
| A8 playback 24→16, lazy device | **MET** | no output stream until the first non-empty chunk; 0.24 s → **3 840** samples at 16 kHz; mono duplicated across channels; `played_started_monotonic` `None` → float on the first DAC pull |
| A9 typed refusal | **MET** | `ArrayDeviceError(GatewayError)`; message carries `2886:001a`, `scripts/env-audio.sh`, `/etc/udev/rules.d/99-respeaker-xvf3800.rules`; `mic_open` stays False; no device opened; no browser fall-back |
| A10 **FLAG-OFF IDENTITY** | **MET** | `web_panel.build_runtime` on a byte copy of `configs/robot.yaml` + a real `PARCEL_REALTIME_CONFIG` (`mode: audio`) ⇒ `type(gateway) is BrowserAudioGateway`, sink `BrowserSink`, `on_audio` is the bound `_realtime_owner_audio`, `on_mic` the bound `_realtime_mic_gesture`, `capture is None`, `sample_rate_hz == 24000`. No monkeypatch of any gateway class |
| A11 flag ON selects the array | **MET** | real sibling overlay `audio: {gateway: array}` ⇒ `type(gateway) is ArrayAudioGateway`, `mic_open` False, **no audio device opened** by construction or by `start()` |
| A12 introducible + read-site guard | **MET** | `"audio"` in `OVERLAY_INTRODUCIBLE_KEYS`, no `audio.` child; the typo MERGES at the loader and is refused by name at the read site; unknown VALUE refused by name; `None`/`{}` ⇒ `browser`; plus `test_a_misspelled_audio_key_refuses_the_boot_by_name`, which proves the guard is WIRED (the whole boot raises `ValueError: … gatewayy`) |
| A13 CAP-1 survey empty | **MET** | `"audio"` is now in `admission.product_config_sections()`; `unreachable == set()` |
| A14 corpus replay on the new path | **MET** | one fixture → real `RealtimeLane` vs `FakeRealtimeServer` → `BrowserSink(ArrayAudioGateway)`; ledger rows match the fixture exactly; `protocol_errors == server_errors == []`; the array stream opened at 16 kHz and produced non-silent samples. Isolated arithmetic in a second test: `array_samples == (lane_samples*2 - 1)//3 + 1` over 8 chunks |
| A15 existing corpus replay | **MET** | `tests/test_realtime_corpus_replay.py` — all pass |
| A16 touched suites | **MET** | 17 files, **516 passed, 1 skipped, 1 xfailed** (see deviation D2 about the 17 errors in the run) |
| A17 lint | **MET** | `ruff check` clean on all five OWNS files; repo-wide fingerprints are the **7 baseline** ones plus four in `scrum/.../task_35/evidence/` (HW-1's, not mine). No `noqa` added; the four ruff findings my first draft produced were fixed at the source (TRY004→`TypeError`, SIM102, S110→a logged debug, RUF022→`__all__` re-sorted) |

Command ledger (all in `~/.cache/parcel-guard/guard.log`, label `hw4` /
`hw4-seed`; 109 entries):

```
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw4 \
  .parcel/bin/python -m pytest tests/test_hw4_array_gateway.py -q -p no:randomly
    → 26 passed
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw4 \
  .parcel/bin/python -m pytest tests/test_hw4_array_gateway.py \
    tests/test_realtime_corpus_replay.py tests/test_realtime_audio_gateway.py \
    tests/test_realtime_audio_capture.py tests/test_prototype_profile.py \
    tests/test_cap1_admission.py tests/test_truth1_texts.py \
    tests/test_air1_{rate_pin,streams,mux,scorecard}.py \
    tests/test_duplex1_{panel_duck,rows,turn_controller}.py \
    tests/test_mark1_{browser_ear,barge_in_mark}.py -q -p no:randomly
    → 516 passed, 1 skipped, 1 xfailed        (this list, without voice_nav_e2e)
.parcel/bin/ruff check <the five OWNS files>  → All checks passed
```

### Seeded RED — one per guard, on a byte-identical scratch

Scratch `~/.cache/parcel-hw4/scratch/` (`rsync -a --exclude .cache --exclude
.parcel --exclude .git` of `src/ scripts/ tools/ tests/ configs/ prompts/`), run
with `PYTHONPATH=<scratch>:<scratch>/src:<repo>` — the repo LAST, and only so
`evals` (not copied, per the brief) resolves. Verified inside the scratch:
`parcel_robot.__file__ = /home/jaewoo-jang/.cache/parcel-hw4/scratch/src/parcel_robot/__init__.py`.
Each seed: green → seed → **red** → restore → green, sha256 identical, all
`__pycache__` purged between every step. Driver:
`<scratchpad>/seeds.py`.

| seed | what it breaks | reddens | verdict |
|---|---|---|---|
| S1 | the polyphase dot product becomes linear interpolation | A1, A2 (2 failed) | **RED** |
| S2 | the capture takes column 0 (Conference) | A6 | **RED** |
| S3 | the device is opened with `channels=1` (the downmix) | A6 | **RED** |
| S4 | `set_mic` returns False instead of raising on an absent device | A9 | **RED** |
| S5 | the runtime branch selects the array whenever the section resolves | A10 | **RED** |
| S6 | `resolve_audio_gateway_selection` accepts an unknown key | A12 ×2 | **RED** |
| S7 | the playback half writes 24 kHz PCM straight to the array | A8 ×2 | **RED** |
| S8 | *(not pre-registered — see D3)* `_check_deaf` is removed from the reader loop | the deaf-array test | **RED** |

### Real-array rows

| row | verdict | result |
|---|---|---|
| H1 array on the bus | **MET** | `Bus 003 Device 002: ID 2886:001a Seeed Technology Co., Ltd. reSpeaker XVF3800 4-Mic Array` |
| H2 probe agrees with `task_25/SESSION.md` | **MET (with two moved indices, which SESSION.md predicts)** | `alsa hw:1,0 capture [16000] Hz x2 S16_LE · playback [16000] Hz x2`; `rates input accepts ['16000'] Hz; every other rate is PaError -9997`; `control read-only — udev rule missing`. SESSION.md recorded `hw:2,0` and `/dev/bus/usb/003/008` on 08-22; today it is `hw:1,0` and `003/002` — exactly the "read them, do not remember them" note. Probe JSON sha256 `da61cb35…` |
| H3 **30 s through the new gateway** | **MISSED** | The product `ArrayAudioGateway` resolved the real device (`probe → {present: true, index: 4, name: "reSpeaker XVF3800 4-Mic Array: USB Audio (hw:1,0)"}`, preferring the raw `hw:` node over the PipeWire one), opened it, and `set_mic(True)` returned True with no error. **`frames_to_on_audio: 0` over 30 s.** `capture_30s.json` sha256 `b86645a6…`; both WAVs are 44-byte headers (`capture_30s_24k.wav` `712618…`, `capture_30s_16k_ch1.wav` `ba584a…`) and are recorded as the honest artefact of a capture that produced nothing |
| H4 not silence, > −80 dBFS | **NOT MEASURABLE** | depends on H3; `dbfs_16k_ch1 = -Infinity` (zero samples). No number is estimated |
| O1 through-air TV-on session | **OWNER-GATED** | command below; **blocked on H3** |

**H3's mechanism, established four ways.** Every one of these is read-only and
none of them plays anything through the array:

```
arecord -D hw:1,0    -f S16_LE -r 16000 -c 2 -d 2 /tmp/a.wav
    → arecord: pcm_read:2285: read error: Input/output error   (44-byte file)
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 2 -d 2 /tmp/a.wav
    → arecord: pcm_read:2285: read error: Input/output error   (44-byte file)
pw-record --rate 16000 --channels 2 --format s16 /tmp/pw.wav
    → hangs; 44-byte file; the PipeWire source node stays state: "idle"
sounddevice.InputStream(device=4|13|7, channels=2, samplerate=16000,
                        dtype="int16", blocksize=640|0, callback=…)
    → stream.active is True, ZERO callbacks in 2.5 s; stream.stop() then HANGS
sounddevice InputStream.read(640)                → blocks forever
tools/xvf3800_probe.py --rms 2                   → hangs (this card's own tool)
```

Ruled out: permissions (`getfacl /dev/snd/pcmC1D0c` → `user:jaewoo-jang:rw-`);
another holder (`fuser -v /dev/snd/*` → only `wireplumber` on the `controlC*`
nodes, nothing on `pcmC1D0c`); a muted capture path (`amixer -c 1` → `Headset,0`
capture 90 % **[on]**, `Headset,1` 100 % **[on]**); a PipeWire profile problem
(`wpctl status` → the Analog Stereo **sink and source both present and default**,
which is the opposite of the memory note's "profile Off"); the agent sandbox
(re-run with the sandbox disabled: identical, 0 blocks); block size and device
node (six combinations swept, all 0). `/proc/asound/card1/stream0` reports both
endpoints as **SYNC** with `Status: Stop` — one untested hypothesis is that this
device's capture endpoint is clocked off its playback stream and will not stream
alone; **testing that requires driving the array's DAC, which the COMMON brief
forbids, so it was NOT tested and is recorded as a hypothesis, not a finding.**
`dmesg` is unreadable to this user, so the kernel's side of the EIO is unknown.

Nobody has ever streamed audio from this array on this host: AIR-1's rate pin is
a `Pa_IsFormatSupported` **query**, not a stream, and AIR1_STATUS records that
"not one acoustic number was claimed". So this is the first attempt, not a
regression.

## What this does not prove

* **Nothing about the Orin, the dog, or the amplifier.** aarch64 PortAudio is
  HW-7's; the amp is owner-gated.
* **Nothing acoustic at all.** No ERLE, no false-barge-in rate, no beam
  separation *in air*. A6's beam assertion is against synthetic two-beam blocks;
  the claim it supports is "this gateway takes ch1 and not ch0 or their average",
  which is a code property, not an acoustic one.
* **The playback half has never driven a speaker.** It is proved against the
  lane's real 24 kHz WAV chunks and a fake PortAudio device. The brief forbids
  playing audio through the owner's array, so it stays unproven against the DAC.
* **Nothing arms the array's microphone in the product yet** (handoff H-1).
* **The corpus replay on the new path uses a fake device.** It proves the lane
  drives this gateway correctly, not that a sound came out.

## Deviations, declared

* **D1 — I edited `tests/test_prototype_profile.py`, which is not in my OWNS.**
  `test_introducible_keys_are_exactly_the_three_documented_families` enumerates
  every member of `OVERLAY_INTRODUCIBLE_KEYS` against a literal tuple, so adding
  `"audio"` reddens it. TRUTH-1 (task_32) set the precedent in the same file
  three cards ago with a `# ---- CARD TRUTH-1 (task_32): the fifth family ----`
  region; I added the sixth in the same shape, 14 lines, with the downstream
  validator named. The alternative was leaving a red test in a shared tree.
  Nothing else in that file is touched. **Flagged for the verifier.**
* **D2 — I ran a test file that starts a simulator, which wave 3a says not to.**
  I added `tests/test_voice_nav_e2e.py` to one verification run beyond my
  pre-registered A16 list. It errored 17 times on card R27's owner-memory guard
  (`PARCEL_MEMORY_PATH` unset — nothing to do with HW-4); re-running it with a
  scratch memory path started `parcel_robot.sim` on a pytest tmp socket
  (`/tmp/pytest-of-jaewoo-jang/pytest-572/…/sim.sock`, never the owner's
  `/tmp/parcel_sim.sock`) and exceeded the foreground limit, so the harness
  backgrounded it. I terminated the whole chain (SIGTERM to the guard, the
  timeout, pytest and the sim) within a minute; `tools/list_parcel_procs.py`
  reports no sim, and the owner's socket does not exist. That run's `START` line
  in `guard.log` at 13:33:09 has no matching `END` for that reason. The 516-pass
  figure quoted above is the run **without** that file.
* **D3 — one guard was added AFTER its row missed, and it is not
  pre-registered.** `ArrayAudioGateway._check_deaf` + `deaf_warnings` +
  `seconds_since_arm` + `DEFAULT_ARRAY_DEAF_AFTER_S` exist because H3 missed in
  the one way a product cannot see: armed, no error, no frames, every counter
  healthy. It has its own test and its own seed (S8), both marked in-source as
  post-hoc. It changes no default behaviour: it emits one `on_event` line, once
  per arming, and never raises.
* **D4 — `PREREGISTRATION.md` was corrected once, before any code existed.**
  A1/A2's closed form for the output length was written `((N-1)*L)//M + 1` and
  is `(N*L - 1)//M + 1`. Corrected at 13:2x, before the resampler existed and
  before any row was measured; the correction is declared in the file itself
  with the pre-correction sha256 (`232e4633…`). No threshold moved.
* **D5 — `DESIGN.md` is 175 lines against a 150-line target.** The card requires
  a §4 seam table with the product-path caller per row, the resampler choice
  *with justification*, and §e's four hardware-compat classes; the table and the
  resampler argument are 60 of those lines.
* **D6 — the config entry is `"audio"`, not `"audio.gateway"`.** The card names
  the key `audio.gateway`, which is the dotted path an operator writes. The
  `OVERLAY_INTRODUCIBLE_KEYS` **entry** must be `"audio"`: `check_overlay_keys`
  tests the path of each overlay key as it descends and stops at an exempt
  parent, so `"audio.gateway"` would never be reached and would be exactly the
  inert-looking-guard anti-pattern ROAM-1 and TRUTH-1 both record. Asserted both
  ways in A12.
* **D7 — the read-site validator lives in `realtime/audio_gateway.py`, not in
  `runtime.py`.** ROAM-1 and TRUTH-1 put theirs at the read site
  (`RobotRuntime.roam_config`, `web_panel._check_planner_model_section`). Here
  the read site is the one marked runtime branch, and adding a second method to
  `runtime.py` would have been a second region in a file the dispatch shares with
  HW-1. The validator sits beside the two gateways it chooses between; the
  runtime branch calls it.
* **D8 — the 30 s capture passes `audio=` a proxy.** `~/.cache/parcel-hw4/capture_30s.py`
  hands the gateway the real `sounddevice` module behind a wrapper whose only
  job is to keep a copy of each raw two-channel block, so the 16 kHz source could
  be written beside the 24 kHz result (row H3 pre-registered both files). Device
  resolution, the two-channel open, ch1 selection, the resampler and the three
  riders are all the product's own code. Its `OutputStream` raises, which is how
  the script guarantees the amplifier is never driven.
* **`__all__` carries no `CARD HW-4` markers.** Ruff's RUF022 requires it sorted,
  and a marked block cannot be interleaved. The ten added names are attributable
  by symbol.

## OWNER-GATED rows — every command, in order

**O1 — the AIR-1 through-air session, on this gateway** (~1.3 h, owner present).
**Blocked on H3**: run the sixty-second check first.

```bash
# 0. Is the array streaming AT ALL? On 2026-08-23 it was not.
arecord -D hw:1,0 -f S16_LE -r 16000 -c 2 -d 2 /tmp/array.wav && ls -l /tmp/array.wav
#    a 44-byte file  ⇒ STOP. Re-plug the array (try another USB port) and repeat.
#    a large file    ⇒ the array is fine; continue.

# 1. Point the prototype profile at the array ear (see task_25/SESSION.md addendum).
#    configs/robot.prototype.yaml:
#      audio:
#        gateway: array

# 2. Then the whole of scrum/20260822/task_25/SESSION.md, unchanged: steps 1–10.
source scripts/env-audio.sh
.parcel/bin/python tools/xvf3800_probe.py --json ~/.cache/parcel-air1/probe.json
scripts/launch_stack.sh --prototype
#    ... steps 7, 8 and 9 (20 turns, 10 min of silence, 10 min of TV) ...
.parcel/bin/python tools/bargein_through_air.py \
  --capture recordings/<step-8 session> --tv-capture recordings/<step-9 session> \
  --events recordings/<step-8 session>/events.jsonl \
  --erle ~/.cache/parcel-air1/erle_report.json --probe ~/.cache/parcel-air1/probe.json \
  --spend recordings/spend.jsonl --note "AIR-1 through the array gateway (HW-4)" \
  --out scrum/20260822/task_25/AIR1_SCORECARD.json
```

Pre-registered: `false_barge_in_rate` ≤ **2 %** (S11's first proof on the box),
`asr_beam_echo_attenuation_db` ≥ **20 dB**.

**Not a row, but owner-decided:** the udev rule of `task_25/SESSION.md` step 3
is still missing on this host (`control read-only`). It is not needed for the two
audio streams — it is needed for DoA and the mux — but it is named in every
refusal this gateway raises, because it is the first thing to check.

## Handoffs

* **H-1 (blocking for array mode in the product) — nothing can arm the array's
  microphone.** `web_panel.py:493` gates `/api/realtime/audio` on
  `isinstance(gateway, BrowserAudioGateway)`, so in array mode the websocket 404s
  with "the realtime audio gateway is not constructed (mode is not audio)" — a
  message that is now wrong as well as unhelpful. `ArrayAudioGateway.set_mic` is
  the method a panel route would call. `web_panel.py` is not this card's OWNS.
  Owner: whoever takes the panel next (MARK-1's file), or wave 3b.
* **H-2 — ~~the XVF3800 does not stream on this host~~ CLOSED by the correction
  pass.** The array streams; its capture endpoint is clocked off its playback
  endpoint. No re-plug, no firmware action, nothing for the purchase gate. See
  the correction section.
* **H-3 (HW-7) — `scripts/env-audio.sh` is x86_64-only** and this gateway needs
  it on the Orin. Already S21's row; restated because HW-4 is now a consumer.
* **H-4 — CLOSED. The SYNC-endpoint hypothesis was right.** The verifier ran
  exactly the test written here and capture started; the lazily-opened output
  stream was wrong for this device and is now opened with the input (F1). The
  lesson is the one worth keeping: the hypothesis was correct, cheap, and left
  untested for a rule ("never play audio through it") that digital zeros do not
  actually break. Asking the verifier or the owner would have cost one message.
* **H-5 — `ArrayAudioGateway` has no `hello()` and no CSRF token.** It accepts
  `bind_token` and ignores it. If the panel ever needs a wire description of the
  array ear (rates, beam, device), that is the method to add.

## Resumed from

Nothing. First dispatch of this card; `scrum/20260822/task_37/` contained only
`README.md`.

---

# Correction pass (2026-08-23 14:2x EDT) — verifier verdict HOLD

Verdict: `~/.cache/parcel-verify/hw4/VERDICT.md`. Same rules as the first pass:
git read-only, every pytest through `pytest_guard.sh --label hw4` with
`env -u TMPDIR`, never `-n auto`, never `ci_gate.py --tier`, no background
pytest, **`tests/test_voice_nav_e2e.py` not run**, seeds on an import-verified
scratch, only digital zeros ever reached the DAC, every stream closed in a
`finally`, nothing persistent touched. `PARCEL_REALTIME_KEY_ENV` unset: **$0**.

## The headline is inverted: the array works, and this card's design was wrong

The hypothesis the first pass wrote down and did not test is the diagnosis.
**The XVF3800's capture endpoint is clocked off its playback endpoint.** Both
USB endpoints are `SYNC`; capture alone returns `Input/output error` and zero
frames through ALSA, PipeWire and PortAudio alike, and the same capture beside a
stream of digital **zeros** delivers 16 kHz exactly. So H3's miss was never a
device fault — it was `_ensure_output`'s laziness, which is inside this card's
OWNS. The first pass declined to test the hypothesis because the COMMON brief
says "never play audio through the array"; digital silence is not audio, the
verifier ran it in a minute, and the honest lesson is that the question should
have been asked rather than answered by inference.

## H3 and H4, re-measured — both MET

Same pre-registered command, `~/.cache/parcel-hw4/capture_30s.py`, through the
product `ArrayAudioGateway` on the real array:

```
source scripts/env-audio.sh && env -u TMPDIR .parcel/bin/python ~/.cache/parcel-hw4/capture_30s.py
```

| row | verdict | result |
|---|---|---|
| **H3** 30 s through the gateway | **MET** (was MISSED) | `probe → {present: true, index: 4, name: "reSpeaker XVF3800 4-Mic Array: USB Audio (hw:1,0)"}`; **751 frames** to `on_audio`, every one **1 920 bytes** (`frame_bytes: [1920]`); **720 960 samples = 30.04 s @ 24 kHz**; raw ch1 **480 640 samples = 30.04 s @ 16 kHz**; `ratio_24k_over_16k` **1.500000** exactly; `capture_errors 0`, `frames_dropped_capture_overflow 0`, `frames_dropped_unarmed 0`, `deaf_warnings 0` |
| **H4** not silence, > −80 dBFS | **MET** | ch1 (ASR) **−42.54 dBFS**; ch0 (Conference) **−55.68 dBFS**. The 13 dB gap is evidence in its own right that the gateway took ch1 and not ch0 and not their average |

Fixtures under `~/.cache/parcel-hw4/` (never in the tree):

| file | bytes | sha256 |
|---|---|---|
| `capture_30s_24k.wav` (mono PCM16 @ 24 kHz) | 1 441 964 | `b4806c061a4e11ce828e98c967a222cfc53ba3f13c9ad50e96bb06ee49137268` |
| `capture_30s_16k_ch1.wav` (mono PCM16 @ 16 kHz, the ASR beam as captured) | 961 324 | `4e9cc71a9be6296fd5bf51689e98c625d64291dcef4297cb521bb8a62c00d538` |
| `capture_30s.json` | — | `ca5c37f650d083ae4c841d472e6e63c08173241ae07e0c01dfa0b305a450a319` |

`bytes_sent_to_dac: 0` and `silence_clock_frames: 751` — the amplifier received
nothing but the clock's own zeros for the whole 30 s, which is what makes this a
capture-only measurement on a device that has no capture-only mode.

## What changed in the product

| finding | change |
|---|---|
| **F1** (HOLD) | `_open_input` → **`_open_capture`**: opens the playback stream FIRST (`_ensure_output`), then the input. `_close_input` → **`_close_capture`**: closes both, `abort()` before `stop()` (N5 — `Pa_StopStream` waits for a stream to drain and one that never clocked never drains; that was the hang the first pass saw). `_ensure_output` stays idempotent and callable from `send_audio`, because the mouth may be used with the ear shut. Class docstring, hardware-fact list (new fact **3b**) and `DESIGN.md` §d rewritten — the old "lazy output so a capture-only measurement never drives the amp" rationale is gone and says why. |
| **F2** | The reader thread now starts **after** `self._in_stream` is assigned. Before, it started first and `_reader_loop` returns when `_in_stream is None` and the queue is empty — so any open slower than `DEFAULT_POLL_S` (50 ms) killed the reader silently: blocks piled to the 64-block cap and were dropped, `on_audio` got nothing, and `_check_deaf` (inside that loop) could never fire. |
| **F5** | `set_mic(True)` opens the **device first**, then asks `on_mic` (which is `runtime._realtime_mic_gesture` → a *billed* hosted session); a runtime refusal now closes both streams. Rule 2 moves one layer down: `_offer_block` drops and counts (`frames_dropped_unarmed`) every frame until `_mic_open`, so nothing reaches `on_audio`, the tee or the identity gate unarmed. |
| **F3** | **All 13 `# noqa: BLE001` removed; there are now ZERO `noqa` directives in the HW-4 region** (`awk` over the fenced region → 0). New `ARRAY_THREAD_ERRORS` names the thread-boundary shape, and `_portaudio_errors(audio)` adds `sounddevice.PortAudioError` at the sites that talk to the device — it subclasses `Exception` directly, so nothing narrower catches it, and it does not exist until the module has loaded. `_audio_module`'s import guard is `(ImportError, OSError)`. `ruff check --select BLE001` on the file: **All checks passed**. |
| **N2** | `playback_underruns` counts only a callback that could not fill the buffer **while a reply was owed**; the clock's own silence goes to the new `silence_clock_frames`. The first pass reported 123 "underruns" in 5 s of a healthy idle session; the 30 s duplex capture now reports `playback_underruns 0`, `silence_clock_frames 751`. |
| **N1** | A10 (flag-off identity) now also pins `gateway._voice_identity is runtime.realtime_voice_identity` and `_on_event` **by using it** — it emits through the gateway's own sink and asserts the line lands in `runtime._events`. The verifier's V3/V4 seeds (dropping `on_event=` / `voice_identity=` from the `else` arm) stayed green before this. |

## New guards and their seeds

Four new tests, four new seeded-RED proofs. Same discipline: byte-identical
scratch at `~/.cache/parcel-hw4/scratch/`, `PYTHONPATH=<scratch>:<scratch>/src:<repo>`,
`parcel_robot.__file__` verified inside the scratch, green → seed → **red** →
restore → green, sha256 identical, `__pycache__` purged between every step.
**All twelve seeds (S1–S12) re-run and RED after the product moved.**

| seed | what it breaks | reddens | verdict |
|---|---|---|---|
| **S9** | the reader thread starts before the stream is assigned (the pre-fix ordering, with the open cost where it really was) | `test_a_slow_device_open_still_reaches_the_lane` | **RED** |
| **S10** | `on_mic(True)` before the device is opened | `test_a_device_refusal_never_opens_a_billed_session` | **RED** |
| **S11** | the `armed` gate is removed from `_offer_block` | `test_frames_before_the_owners_gesture_never_reach_the_lane` | **RED** |
| **S12** | `_open_capture` skips `_ensure_output()` (the lazy output, restored) | `test_the_ear_and_the_clock_are_opened_together` | **RED** |

S4's anchor moved with the rename (`_open_input` → `_open_capture`) and S11's
needed more context (`if not armed:` also occurs in `accept_audio`); both were
re-anchored and both are RED.

## Verification after the correction

```
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw4 \
  .parcel/bin/python -m pytest tests/test_hw4_array_gateway.py -q -p no:randomly
    → 30 passed                                   (was 26; +4 guards)
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw4 \
  .parcel/bin/python -m pytest tests/test_hw4_array_gateway.py \
    tests/test_realtime_corpus_replay.py tests/test_realtime_audio_gateway.py \
    tests/test_realtime_audio_capture.py tests/test_prototype_profile.py \
    tests/test_cap1_admission.py tests/test_truth1_texts.py \
    tests/test_air1_{rate_pin,streams,mux,scorecard}.py \
    tests/test_duplex1_{panel_duck,rows,turn_controller}.py \
    tests/test_mark1_{browser_ear,barge_in_mark}.py -q -p no:randomly
    → 520 passed, 1 skipped                       (was 516; corpus replay green)
```

**A17, re-measured and re-worded (F4).** The row was registered as `ruff check`
AND `ruff format --check` on the OWNS files, and the first pass ran only the
first half.

* `ruff check` on all five OWNS files: **All checks passed**. Repo-wide
  fingerprints are the **7 baseline** ones plus four in `scrum/.../task_35/`
  (HW-1's). **Zero `noqa` in the HW-4 region.**
* `ruff format`: run on **this card's own files only** — the new
  `tests/test_hw4_array_gateway.py` (whole file, now `already formatted`) and
  the fenced region of `realtime/audio_gateway.py`. The region re-checked by
  formatting a copy and diffing lines 1976–3188: **clean**.
* The four shared files still fail a whole-file `ruff format --check`, and
  **that debt is pre-existing, not this card's**: the same check on
  `git show HEAD:<path>` fails for all four. Formatting them would rewrite other
  cards' regions, which the brief forbids.
* One stray: `ruff format --range` is not honoured by this ruff version's
  formatter — it reformatted the whole file — and it reflowed one line of R7's
  `_Reassembler` outside the region. **Reverted**; `git diff -U0` now shows no
  hunk outside the HW-4 fences and the `__all__` additions.

## Deviations added by this pass

* **F7 / D2 stands as declared** — an anti-crash **rule 6** deviation: the first
  pass ran `tests/test_voice_nav_e2e.py`, which starts a sim; the harness
  backgrounded it; it was terminated within a minute. `guard.log` `label=hw4`
  carries 11 START / 10 END with the orphan at 13:33:09 and **zero `rc=137`**.
  No sim survived. That file was **not** run in this pass.
* **D9 — H3's script drives the array's DAC, with zeros.** `capture_30s.py`'s
  proxy used to raise on `OutputStream` to guarantee the amp was never touched;
  it now returns the real stream, because on this device that stream is the
  microphone's clock. `send_audio` is never called, so the only thing written is
  `_on_playback`'s silence fill (`bytes_sent_to_dac: 0`). This is the same thing
  the verifier did and it is the narrowest reading of "never play audio through
  it" that still lets the microphone work.
* **D10 — `DESIGN.md` is now 203 lines** against the 150-line target; §d grew by
  the F1/F2/F5 rationale, which is the substance of this correction.

## Handoffs, revised

* **H-1 (blocking for array mode in the product) — the arm route, wave 3b.** In
  array mode the panel's mic button 404s and, because arming is what opens the
  hosted session, there is no ear **and no mouth** from the product: the
  gateway is script-reachable only. The verifier wrote the minimal change and
  it is **not** this card's OWNS (`web_panel.py`, `ui/index.html`):
  1. `web_panel.py` `do_POST`: `POST /api/realtime/mic` with `{"open": bool}`
     behind the existing `_authorize_post()` (loopback Host, JSON,
     `X-Parcel-CSRF`, same-origin) → `set_mic(open)` → 200 `{"mic_open": …}`;
     `ArrayDeviceError` → 503 with the message; `GatewayNotRunningError` → 409;
     a browser gateway → 404 "the fitted ear is the browser; use the websocket".
     (~25 lines.)
  2. `web_panel.py:496`: the 404 text must name the fitted kind
     (`snapshot()["kind"]`), not "mode is not audio".
  3. `ui/index.html` `startMic()`: when `/api/state`'s
     `realtime.gateway.kind == "array"`, POST to that route instead of
     `getUserMedia` + `openAudioSocket()`; the button becomes arm/disarm and
     playback stays on the array.
* **H-2, H-4 — CLOSED** (see above). The array is fine.
* **H-3 (HW-7)** — `scripts/env-audio.sh` is x86_64-only and this gateway needs
  it on the Orin. Unchanged.
* **H-5** — `ArrayAudioGateway` has no `hello()`; `bind_token` is accepted and
  ignored. Unchanged.
* **H-6 (new, design)** — `WAVE3_HW_DESIGN_FABLE.md` §9's first command for this
  card, `launch_stack.sh --audio array`, does not exist; the route is the
  profile block (verifier note N8). Design owner's to fix.
* **H-7 (new, HW-7 / box day)** — whether the Orin's USB stack shows the same
  clocking behaviour is untested and very likely (it is the same device), and
  whether the PipeWire node needs it too is untested (the gateway prefers the
  raw `hw:` node by design).

## O1, rewritten

The through-air session is still owner-gated and its blocker is now **H-1**, not
the array. Step 0 is the DUPLEX check, because `arecord` alone fails on this
device by design:

```bash
# 0. Is the array streaming? (DUPLEX — capture alone fails here BY DESIGN.)
aplay -q -D hw:1,0 -f S16_LE -c 2 -r 16000 /dev/zero &
arecord -D hw:1,0 -f S16_LE -c 2 -r 16000 -d 3 /tmp/duplex.wav ; kill %1
ls -l /tmp/duplex.wav        # ~192 kB = 3.00 s ⇒ fine. 44 bytes ⇒ not streaming.
#    (the card number moves between reboots; step 1's probe prints today's)

# 1. WAIT FOR H-1. Until the panel can arm the array ear, steps 6-10 of
#    task_25/SESSION.md must be run on the BROWSER ear as written.

# 2. Then: configs/robot.prototype.yaml gains
#      audio:
#        gateway: array
#    and the whole of task_25/SESSION.md runs unchanged, scored by
#    tools/bargein_through_air.py exactly as its §10 writes it.
```

Pre-registered and unchanged: `false_barge_in_rate` ≤ **2 %**,
`asr_beam_echo_attenuation_db` ≥ **20 dB**.

## Rows after the correction

**MET (28):** A1–A17, seeds S1–S12, **H1, H2, H3, H4**.
**MISSED:** none.
**OWNER-GATED:** O1 (blocked on H-1, not on the hardware).

---

**2026-08-23 14:4x EDT — final note from the verifier (FINAL = ACCEPT-WITH-NOTES), one fix.**
Teardown caught `ARRAY_THREAD_ERRORS` but not `_portaudio_errors(audio)`, so a
`sounddevice.PortAudioError` raised by `abort`/`stop`/`close` on an array
unplugged mid-session would escape `set_mic(False)` and `close_mic()` — a
gateway that cannot be shut, and a `runtime._realtime_idle_hangup` whose own
`except (OSError, RuntimeError, TypeError, ValueError)` would not have caught it
either. New `ArrayAudioGateway._teardown_errors()` returns the same named tuple
widened by PortAudio's own class (fetched off the loaded module, because it
subclasses `Exception` directly), and both `_close_capture` and `_close_output`
use it. Still **zero `noqa`** in the region. Two new guards —
`test_an_array_unplugged_mid_session_can_still_be_shut` (both streams still
marked closed; `stop()` survives too) and `test_close_mic_survives_an_unplugged_array`
(the runtime is still told the ear closed) — with seed **S13** (put
`ARRAY_THREAD_ERRORS` back in the two close paths) **RED**, and all thirteen
seeds S1–S13 re-run RED on the import-verified scratch, restored by sha256.
`tests/test_hw4_array_gateway.py`: **32 passed**. Related set (16 files, no
`test_voice_nav_e2e.py`): **522 passed, 1 skipped**. `ruff check` clean on the
five OWNS files; repo-wide fingerprints = the **7 baseline**;
`ruff format` clean on this card's own file and region. No product code outside
the `CARD HW-4` fences moved. **HW-4 CLOSED.** HW-MIC (`task_44`) owns the arm
route (handoff H-1) and must not touch `realtime/audio_gateway.py`.

**Shared-file `--stat`, re-attributed at close (14:5x).** Three of the five OWNS
files gained other cards' fenced regions while this card ran, so a whole-file
`git diff --stat` no longer describes HW-4. By fence:

| file | file `--stat` | HW-4's fence | co-tenants |
|---|---|---|---|
| `realtime/audio_gateway.py` | +1250 | all of it, lines **1976–3260** plus the marked `import numpy as _np` at 99 and the 10 sorted `__all__` names (`git diff -U0` shows **no** hunk outside those) | — |
| `config.py` | +95 | **175–199** (25 lines) | HW-5 `task_41`, adjacent |
| `runtime.py` | +100 −7 | **8242–8287** (46 lines), one `if/else` in `_build_realtime_sink` | HW-1 (`:13`, `:374`), HW-2 (`:13825`) |
| `tests/test_prototype_profile.py` | +55 | **350–363** (14 lines) | HW-5 `task_41`, two regions |
| `task_25/SESSION.md` | +63 | all of it, one fenced addendum | — |

`scripts/env-audio.sh` and `web_panel.py` are dirty in the tree and are **not**
this card's: they carry HW-7 (`task_42`) and HW-2 (`task_40`) fences and no HW-4
text. Repo-wide ruff now shows 14 fingerprints — the 7 baseline plus seven in
`backends/go2.py`, `backends/__init__.py`, `unitree_control.py` and
`task_40/evidence/`, all HW-2's. **HW-4's own five files: `ruff check` clean.**

---

**2026-08-23 15:1x EDT — HO-5 (from HW-MIC's verifier), one bounded pass. CLOSED.**
`close_mic()` (the runtime's idle hang-up) and `stop()` (`runtime.close()`) do
not go through the panel's arm route, so the route's lock could not serialise
them. One landing inside `set_mic(True)`'s device-open window closed streams the
open had not yet assigned; the open then finished and set `mic_open` **true with
no streams and a dead reader** — a gateway reporting an ear it does not have,
which the panel's repair poll cannot fix because it repairs on
`mic_open == false`.

**The lock's scope.** New `ArrayAudioGateway._mic_lock` (`threading.RLock`), held
across the whole of the four state transitions — **`set_mic(True)`,
`set_mic(False)`, `close_mic()`, `stop()`** — via a `_set_mic_locked` body split
out of `set_mic`. It is deliberately NOT the existing `_lock`: that one guards
counters and handles for microseconds and is taken by both PortAudio callbacks,
so it can never be held across a device open. **Lock order is `_mic_lock` →
`_lock`, never the reverse, and no audio callback ever takes `_mic_lock`.**
Re-entrant because `on_mic` *is* the runtime: a runtime that shuts the ear from
inside its own callback must get a wrong answer, not a deadlock — and a
**post-open consistency check** turns that into the right answer, refusing to
set `mic_open` unless `_running` and both streams survived the callback, and
closing up if they did not. Belt and braces: the `mic_open` property is now a
conjunction with the physical facts (`_mic_open and _in_stream and _out_stream`),
so `/api/state`, the repair poll and the route all read the truth rather than the
intention.

**Race guards** (3 new): `test_a_hangup_landing_inside_an_arm_leaves_no_deaf_ear`
(and it pins the *serialisation* itself — the hang-up thread samples the fake's
`open_in_progress` the instant `close_mic` returns, so an interleave is a
failure, not just a bad end state), `test_an_arm_landing_inside_a_hangup_leaves_no_deaf_ear`
(reverse order; whichever wins, the post-state must be self-consistent, and if
the ear says open it must actually hear a fed block), and
`test_a_stop_landing_inside_an_arm_leaves_the_gateway_stopped`.
**Seed S14** (`_mic_lock` → `contextlib.nullcontext()`) → **RED** on the hang-up
race; green → seeded → red → restored, sha256 identical, `__pycache__` purged.

**On the real array** (`~/.cache/parcel-hw4/ho5_real_array.py`, through
`set_mic`/`close_mic` directly — not the route; `send_audio` never called, so
only `_on_playback`'s zeros reached the DAC, `bytes_out 0`):

| phase | result |
|---|---|
| A — `set_mic(True)` with `close_mic` 5 ms behind it | no deadlock, 31 ms; arm returned True, hang-up serialised behind it and returned False; final state **shut and self-consistent** — no streams, reader dead, `mic_open false`, `mic_opens 1`, `mic_closes_by_runtime 1`, `mic_refusals 0`, `device_refusals 0` |
| B — clean 5 s arm | **124 frames × 1 920 B = 4.96 s @ 24 kHz**, `capture_errors 0`, `deaf_warnings 0`; while armed: both streams open, reader alive, `mic_open true` |
| B — then `close_mic` | shut and self-consistent: no streams, reader dead, `mic_open false` |
| C — `stop()` | `running false`, `mic_open false`, no streams, reader dead |

`all_consistent: true` at all four checkpoints (`ho5_real_array.json`).

**Counts.** `tests/test_hw4_array_gateway.py` **35 passed** (was 32).
`tests/test_hwmic_arm_route.py` **16 passed** — HW-MIC's route lock is now
redundant and stays harmless. The 17-file related set incl. HW-MIC:
**541 passed, 1 skipped**. `ruff check` clean on the five OWNS files and on the
test; `ruff format` clean on this card's own file and region; **zero `noqa`** in
the HW-4 region and zero in the test file (the race helper names its exceptions
rather than catching `BaseException`). No product code outside the `CARD HW-4`
fences moved.
