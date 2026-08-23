# AIR-1 · the through-air session · ~1 h 20 min at the desk

*(90 min end to end; ~1 h 20 min once step 2's speaker is already on the amp
from the week-1 list, which is the ~1.3 h the card budgets. Step 5e is
optional and worth its 3 minutes.)*

**You need:** the reSpeaker XVF3800 (already on USB), a small speaker on the
array's **JST-PH2.0 amplifier** header, a second powered speaker or a pair of
earbuds you can lay next to the array, and — for the last arm — a television.
Optionally a second microphone on the green analog jack; it saves you an SPL app.

**You do not need:** a robot, a camera, or anything that has not shipped.

Everything below was rehearsed by the agent as far as it could go without you.
The read-only probe already runs green on this host, so if step 1 disagrees with
what is written here, something moved and that is itself the finding.

> **One rule for the whole session.** Every number goes in the scorecard as
> what it was. A miss is a row with its mechanism, never a re-run until it
> passes and never a threshold nudged afterwards — `verify_scorecard` refuses a
> card whose thresholds moved, so it would not work anyway.

---

## 0 · Before you sit down (2 min)

```bash
cd ~/Desktop/Projects/Parcel
source scripts/env-audio.sh                 # puts PortAudio on the path; do this in EVERY shell
mkdir -p ~/.cache/parcel-air1
```

The credential, if a hosted turn is involved:

```bash
set -a; . ~/.config/parcel/realtime.env; set +a
```

---

## 1 · The array says what we think it says (3 min)

```bash
.parcel/bin/python tools/xvf3800_probe.py --json ~/.cache/parcel-air1/probe.json
```

Expected, measured 2026-08-22:

```
usb       2886:001a at /sys/bus/usb/devices/3-1 (/dev/bus/usb/003/008, mode 0o664,
          control read-only — udev rule missing)
alsa      hw:2,0  capture [16000] Hz x2 S16_LE · playback [16000] Hz x2
pipewire  default sink   reSpeaker XVF3800 4-Mic Array Analog Stereo (vol 0.4) — array
pipewire  default source reSpeaker XVF3800 4-Mic Array Analog Stereo (vol 0.82) — array
rates     input accepts ['16000'] Hz; every other rate is PaError -9997
```

(No `mux` line yet — that section only runs with `--mux`, and it needs step 3.)

Write down the PortAudio device indices it implies — you need two of them:

```bash
.parcel/bin/python -c "import sounddevice as sd; [print(i, d['name'], d['max_input_channels'], d['max_output_channels'], d['default_samplerate']) for i, d in enumerate(sd.query_devices())]"
```

On this host, 2026-08-22: **5** = `reSpeaker XVF3800: USB Audio (hw:2,0)` and
**4** = `HD-Audio Generic: ALC1220 Analog (hw:1,0)`. They are not guaranteed
stable across reboots — read them, do not remember them.

---

## 2 · The speaker goes on the array's own amplifier (10 min)

The XVF3800's echo canceller references **its own DAC**. A speaker on any other
output is echo the chip has never heard of, and it comes back as false
barge-ins — which is the number this whole session exists to measure. So:

1. Speaker leads into the array's **JST-PH2.0** amp header.
2. Leave the sink at its current **0.40**. Do not raise it to "hear it better":
   a clipped 3 W driver breaks AEC and the miss looks like a bad canceller
   (`backlog/BLOCKED.md` B3).
3. Prove sound comes out, at 16 kHz, on the array's own device:

```bash
speaker-test -D plughw:2,0 -r 16000 -c 2 -t sine -l 1
```

If that is silent, stop here — every later number would be a number about
silence. If it is distorted, turn the sink **down**
(`wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.3`) and note the volume you settled
on; it goes into every ERLE leg's JSON automatically, so two legs taken at
different volumes are caught rather than averaged.

---

## 3 · Grant the vendor control interface (5 min)

This one rule unlocks **two** things, not one: the direction-of-arrival read the
TV arm needs, and the output-mux selector that makes step 5 a five-minute job
instead of a fifteen-minute one. Until it exists both are `Errno 13`.

```bash
sudo tee /etc/udev/rules.d/99-respeaker-xvf3800.rules <<< 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001a", MODE="0660", GROUP="plugdev", TAG+="uaccess"'
sudo udevadm control --reload && sudo udevadm trigger --action=change /sys/bus/usb/devices/3-1
.parcel/bin/pip install pyusb
```

(A trigger re-applies node permissions; it does not reset the device. Separately,
Bench A measured that the DoA *read* leaves the ALSA stream state `closed →
closed` and the bus address unchanged — it is EP0 only, and it never claims an
interface or touches the two UAC streams.)

Then, **the DoA row** — pre-registered at **≥ 95 % ok over 100 reads**:

```bash
.parcel/bin/python tools/xvf3800_probe.py --doa 100 --json ~/.cache/parcel-air1/probe.json
```

`control RW` in the `usb` line and `doa 100/100 ok (100%)` is the pass. If it
still says `Errno 13`, check you are in `plugdev` (`id`) and re-plug the array.

---

## 4 · What the microphone hears while you talk (5 min)

Speak normally at about 1 m for five seconds after you press return:

```bash
.parcel/bin/python tools/xvf3800_probe.py --rms 5 --json ~/.cache/parcel-air1/probe_rms.json
```

Two beams come back. **ch1 is ASR** — the one the ear must take. The `downmix`
line tells you what a browser that asked for one channel would have received
instead: the average of ch0 and ch1, which is neither beam. Note the number; it
is MARK-1's evidence as much as yours.

---

## 5 · The echo number — the headline row (5 min, or 15 the long way)

Pre-registered: **≥ 20 dB** at 1 m at normal level, first 2 s excluded.

**What this number is.** It is the echo attenuation of the whole XVF3800
pipeline on the beam the ASR listens to — the linear canceller, the residual
suppressor, the beamformer's spatial rejection, and the capture gain, together.
It is the right number for the gate — it is what a barge-in detector actually
lives with.

**What it is called, exactly** (card TRUTH-1, so the runbook and the tools agree
in writing). The measured field is **`asr_beam_echo_attenuation_db`**: textbook
ERLE is *one stage* of that chain and this number measures all of them. Three
facts, each true of the code as it stands today:

* `tools/measure_erle.py` writes **both** keys into the report with the same
  value — `asr_beam_echo_attenuation_db` and `erle_db` — so nothing that reads
  the old name breaks.
* `tools/bargein_through_air.py` reads `asr_beam_echo_attenuation_db` **first**
  and falls back to `erle_db`. The long name is the source of the number.
* The **scorecard row id stays `erle_db`** — it is the pre-registered row's
  identifier, frozen in `ROWS`, and renaming an id mid-card would silently
  break the ≥ 20 dB gate's continuity. So: long name for the measurement, short
  name for the row. If a document says only "ERLE", it means this.

### 5A · The short way (preferred): one recording, no second speaker

**Prerequisites for the mux path — all of them, once, here** (card TRUTH-1; they
were scattered across step 3, this section and two tool docstrings, and a
prerequisite you have to assemble from three places is one you find out about by
failing):

1. **Step 3's udev rule, plus `pyusb`.** The mux is selected over the same EP0
   vendor control interface the DoA read uses. Without the rule every control
   transfer on this host is `Errno 13`; without `pyusb` there is no transfer at
   all. Both are installed by step 3 above — do not run them twice.
2. **Firmware v2.0.6 is what this array has and is enough.** Measured on this
   host as `bcdDevice 0206` (`task_25/AIR1_STATUS.md`). It predates the
   `AUDIO_MGR_OP_CH3..CH6` additions, and it does not matter: the two channels
   this path needs — the canceller's input and its output — are both selectable
   on it.
3. **Never flash the 6-channel image.** It is a separate DFU image
   (`respeaker_xvf3800_usb_dfu_firmware_6chl_*.bin`), not a USB alternate
   setting; this host's descriptors carry exactly one 2-channel altset. Flashing
   re-enumerates the array with a different channel count, which breaks every
   ALSA/PipeWire/PortAudio assumption in the voice stack, resets parameters, and
   is recoverable only through a bundled `4mb_all_ff.bin`. The mux makes it
   unnecessary — that is the whole point of this path
   (`tools/xvf3800_probe.py`, "THE 6-CHANNEL FIRMWARE IS NOT THE ANSWER";
   `task_25/AIR1_STATUS.md`).

Then check:

```bash
.parcel/bin/python tools/xvf3800_probe.py --mux
```

`mux  L=[6, 3] R=[6, 3] AGC on=[1] gain=[…] — same-instant echo measurement AVAILABLE`
means you can skip 5B entirely. If it says `unreadable`, go to 5B.

Each of the array's two USB capture channels is a **mux**. It can be pointed at
the raw microphone, at the amplified microphone *as the canceller receives it*,
at the far-end reference, or at the processed beam. So the two signals ERLE
compares can be recorded **at the same instant, on one device, at one gain** —
which removes the second loudspeaker, the SPL match and the noise-floor leg in
one go.

```bash
.parcel/bin/python tools/measure_erle.py --method mux --seconds 12 \
  --out ~/.cache/parcel-air1/erle_report.json
```

It reads the current routing, points the left channel at the canceller's input
and the right at its output, plays the probe through the array's own amplifier,
records both, and **puts the routing back** — verified by reading it again. If
the restore ever fails it says so in capital letters; power-cycle the array
(nothing is written to flash).

> **Two cautions.** While this runs, anything else listening to the array gets a
> raw microphone instead of the beam — do not run it during a live session on
> :8765. And it is the one path in this card that **writes** to the device;
> everything else is read-only.

> **This path has never been run against hardware.** The udev rule is an owner
> action and every control transfer on this host is `Errno 13` today, so the
> encoding and the restore discipline are tested against a fake device and the
> wire behaviour is not tested at all. You are its first run. If it misbehaves,
> the routing is restored by unplugging the array.

### 5B · The long way (fallback): three legs and a second loudspeaker

Only if 5A said `unreadable`. The array cancels on-chip; without the mux there
is no tap on the pre-cancellation signal, so the "before" half has to come from
a second recording made with a loudspeaker the canceller cannot reference.

**5b-i — the witness.** If you have a microphone on the green analog jack, use
it: it hears both legs and proves they were the same loudness. Add
`--reference-device 4` to the two legs below. If not, use any phone SPL meter app
at the array; the report will say the match rests on your reading.

**5b-ii — the noise floor.** Silence, nothing playing:

```bash
.parcel/bin/python tools/measure_erle.py --leg floor --seconds 12 \
  --out ~/.cache/parcel-air1/floor.json
```

**5b-iii — uncancelled.** Second speaker where the array's speaker is, ~1 m out:

```bash
.parcel/bin/python tools/measure_erle.py --leg uncancelled --seconds 12 \
  --play-device 4 --play-rate 48000 --reference-device 4 \
  --out ~/.cache/parcel-air1/uncancelled.json
```

**5b-iv — cancelled.** Nothing changes except which speaker plays:

```bash
.parcel/bin/python tools/measure_erle.py --leg cancelled --seconds 12 \
  --reference-device 4 --out ~/.cache/parcel-air1/cancelled.json
```

**5b-v — double talk (optional, 3 min).** Speak over the robot at 1 m throughout:

```bash
.parcel/bin/python tools/measure_erle.py --leg doubletalk --seconds 12 \
  --out ~/.cache/parcel-air1/doubletalk.json
```

**5b-vi — combine:**

```bash
.parcel/bin/python tools/measure_erle.py --report \
  ~/.cache/parcel-air1/{floor,uncancelled,cancelled,doubletalk}.json \
  --out ~/.cache/parcel-air1/erle_report.json
```

> Device **4** is the ALC1220 analog codec, which does 44 100 and 48 000 Hz in
> **both** directions (measured 2026-08-22), so it can be the second speaker and
> the witness microphone at once. If PortAudio refuses to open both halves, drop
> `--reference-device` and use the phone app.

### Read the verdict, not just the number

| verdict | it means |
|---|---|
| `pass` | ≥ 20 dB, and the measurement was sound |
| `pass_lower_bound` | (5B only) the residual is buried in the noise floor; the figure is **at least** this, and the room is the limit |
| `fail` | a real miss — `problems` names the mechanism |
| `unmeasured` | the measurement did not hold up. In 5B: the two legs were not the same loudness, the array's mixer gain moved between them, or the uncancelled leg never got above the noise floor (the probe did not reach the microphone — check `--play-device` and that the second speaker is actually on). Fix and redo; do not report the number. |

---

## 6 · Turn on the tee and the microphone (5 min)

The scorecard's acoustic rows are read out of the R17 capture. Create the live
config from the prototype example if you have not already:

```bash
cp configs/realtime.prototype.yaml.example configs/realtime.prototype.yaml
```

and set, in that file:

```yaml
mode: audio                 # the browser is the ear and the mouth
capture:
  enabled: true             # the R17 tee; sessions land in ./recordings/<id>/
voice_identity:
  enabled: true
  doa: true                 # step 3 made this readable
```

Enroll your voice if you never have (needed for the TV arm's identity half):

```bash
.parcel/bin/python tools/enroll_owner_voice.py --wav a.wav b.wav c.wav d.wav e.wav
.parcel/bin/python tools/enroll_owner_voice.py --show
```

Bring the stack up and open the panel:

```bash
scripts/launch_stack.sh --prototype
```

---

## 7 · Twenty turns and twenty interruptions (20 min)

Arm the microphone in the panel. Then, at about 1 m, at normal volume:

* **20 ordinary turns.** Ask it things. Let it finish.
* **20 interruptions.** Start talking about 1–2 s into each reply, mid-sentence.

Note the session id the panel shows (it is also the folder name under
`recordings/`).

Pre-registered rows from this arm: **0/20** robot utterances transcribed as
owner turns, and interrupt **p50 ≤ 0.52 s (n = 20)**.

> **Read this before you expect the latency number.** Both halves of the pair
> are missing, not one. The R17 index records *that* an utterance was
> interrupted, never *when* (`mark_interrupted` drops the wall stamp
> `note_interrupt` queued), and `robot.wav` is written faster than real time so
> it is not a clock. The evidence log carries the truncate — but **not the
> onset**, because `input_audio_buffer.speech_started` is not a retained event
> type. So `interrupt_p50_s` comes back **unmeasured with that reason**, and it
> would still come back unmeasured if only one of the two were fixed. Do the
> twenty interruptions anyway; they are recorded. Do not estimate it by hand.

---

## 8 · Ten minutes of the robot talking to itself (10 min)

Ask for something long ("tell me about every street you know"), then **say
nothing at all** for ten minutes. Leave the room if it helps.

This is the false-barge-in row: **≤ 2 %** of utterances self-interrupted. Every
`interrupted` mark in this session was caused by the robot's own echo, because
nothing else made a sound — and the tool checks that claim against `owner.wav`'s
own level rather than believing you.

---

## 9 · The television arm (10 min)

Turn on the TV, with people talking on it, at a normal viewing level. Stay
silent yourself for ten minutes with the microphone armed.

First find the TV's bearing so the sector prefilter has something to reject:

```bash
.parcel/bin/python tools/xvf3800_probe.py --doa 200 --json ~/.cache/parcel-air1/tv_doa.json
```

Take the modal angle from `angles_deg` and put a sector around it (±15°) into
the config, then restart the stack:

```yaml
voice_identity:
  doa: true
  rejected_sector: [95, 125]     # your angle ±15
```

Pre-registered: **0 owner-attributed turns in 10 min**. The voice check is the
authority; the sector is the belt.

---

## 10 · The scorecard (5 min)

```bash
.parcel/bin/python tools/bargein_through_air.py \
  --capture recordings/<the step-8 session> \
  --tv-capture recordings/<the step-9 session> \
  --events recordings/<the step-8 session>/events.jsonl \
  --erle ~/.cache/parcel-air1/erle_report.json \
  --probe ~/.cache/parcel-air1/probe.json \
  --spend recordings/spend.jsonl \
  --note "AIR-1 first through-air session" \
  --out scrum/20260822/task_25/AIR1_SCORECARD.json
```

**`--events` is not optional even though the latency row will still come back
unmeasured.** The evidence log is the only artefact that names the *provider's*
session id (`rt_…`), and the spend ledger is keyed by it. Without that, the
spend row matches nothing, and nothing summed is `$0.00` — a pass for a session
that may have cost real money. The tool now reports that as **unmeasured**, and
`--events` is what turns it into a number. If the evidence log is off, read the
session id off the panel and pass it directly:

```bash
  --spend-session rt_ab12cd34ef56
```

It prints seven rows and refuses to write a card that contradicts itself. Paste
the output verbatim into `AIR1_STATUS.md` §"the scorecard" — verbatim including
the unmeasured rows, which are findings.

---

## The pre-registered rows, and what a miss means

| row | gate | where the number comes from |
|---|---|---|
| `asr_beam_echo_attenuation_db` (scorecard row id: `erle_db`) | **≥ 20 dB** | step 5A, or 5B-vi |
| `robot_utterances_as_owner_turns` | **0** of 20 | ⚠ **OWNER-GATED ON A TOOL THAT DOES NOT EXIST YET** |
| `interrupt_p50_s` | **≤ 0.52 s** (n = 20) | ⚠ **not recoverable from any artefact this tree writes** |
| `false_barge_in_rate` | **≤ 2 %** | step 8, from the R17 index |
| `tv_owner_attributed_turns` | **0** in 10 min | ⚠ **OWNER-GATED ON A TOOL THAT DOES NOT EXIST YET** |
| `doa_ok_fraction` | **≥ 95 %** | step 3 |
| `hosted_spend_usd` | **≤ $2** | `spend.jsonl`, joined via `--events` or `--spend-session` |

### Three rows will come back unmeasured, and that is the finding

Two of the seven rows need per-turn identity attribution — which turns the robot
credited to you, and whether the sound that produced each one was actually you.
The runtime keeps exactly that in `ChassisRuntime._speaker_labels`, readable
through `speaker_label_rows()`. But it is **not on `/api/state`, never written
to disk, and stamped with `time.monotonic()`**, which cannot be joined to the
capture's wall clock. So there is no export to run, and doing step 7 and step 9
will not produce those two numbers. Do the arms anyway — the audio is recorded
and can be scored later — but expect the rows to say so.

The third is interrupt latency, and it needs **two** stamps that do not exist:
the interrupt (`mark_interrupted` throws away the wall time `note_interrupt`
queued) and the onset (`input_audio_buffer.speech_started` is not in
`protocol.RETAINED_EVENT_TYPES`, so it never reaches `events.jsonl`). Fixing
only one of them yields nothing. Both are filed as handoffs in
`AIR1_STATUS.md`.

If a row misses, the mechanism is almost always one of four, and the scorecard
makes you name which:

* **clipping** — the amp is driven past its 3 W and the AEC is cancelling
  against a reference that no longer matches what came out. Turn the sink down
  and re-run leg 5d; the residual should drop faster than the playback did.
* **the speaker is not on the array's DAC** — check step 2. This one shows up as
  a large ERLE miss *and* a large false-barge-in rate together.
* **AEC3 double-cancel** — Chrome's own canceller is in the loop
  (`getUserMedia`), stacked on the array's. Symptom: the first syllable of every
  barge-in is eaten, interrupt latency looks fine and the transcript does not.
* **downmix** — the ear took the average of ch0 and ch1 instead of ch1. Step 4
  quantifies it; MARK-1 owns the fix on the browser side.

## What this session cannot settle

Nothing here says anything about a Go2, a D455, or an Orin — none of them exist
on this desk. It settles one question: whether the robot's voice can come out of
a speaker and not be mistaken for yours coming back in. That is the input the
week-3 purchase gate reads, and it is the cheapest one on the list to retire.
