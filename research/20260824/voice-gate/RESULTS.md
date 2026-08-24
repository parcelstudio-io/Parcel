# VOICE-GATE v2 — RESULTS · Opus executor · 2026-08-24

## The policy this study selects: **push-to-talk for M1**

Not because the ambient arms lost on their measurable rows — arm (b) at a
calibrated threshold comes close — but because the consolidated pass rule
**cannot be satisfied on this host at all**. Two of its rows (AEC ≥ 20 dB
through the XVF3800 → CQRobot path; barge-in acoustic stop) need a
loudspeaker, and **the only audio output on this machine is the array's own
DAC**, whose audibility could not be established. DESIGN v2's failure clause
then applies verbatim: *"Failure of every ambient arm selects push-to-talk for
M1 (the honest default until mounted bars pass)."*

Push-to-talk is also the arm that measured best. Of the rows it fails, **five
are arm-independent** — P4/P5/P7 belong to the STOP matcher (which bypasses every
arm by design), P11 is a quoted DUPLEX-1 miss, P12 is the local transcriber — and
they fail identically for all six arms. The only row push-to-talk fails *as a
policy* is P13, first-word loss: 1 truncated turn in 36 = 2.8 % against a 2 % bar,
which n=36 cannot meet with a single event. Every row that distinguishes the
arms — owner recall 1.000 at every geometry cell, zero hosted bytes for
television, second person and self-speech, 0 false hosted openings/day, $0.15/day
— push-to-talk passes.

## The consolidated table (generated: `results/consolidated_table.md`)

Arms ran **sequentially with early stop**; the early stop never fired, because no
arm passes every row. `PASS`/`FAIL` are against the pre-registered bar; `BLOCKED`
means this host cannot produce the evidence and is **not** a pass.

| row | bar | vad_only | owner_id | owner_id_calibrated | wake_phrase | push_to_talk | restricted |
|---|---|---|---|---|---|---|---|
| P1 owner committed-turn recall 1-3 m <= 60 deg | >= 0.95 | PASS 1.000 (worst cell 1.000, n=36) | **FAIL** 0.000 (worst cell 0.000, n=36) | **FAIL** 0.889 (worst cell 0.667, n=36) | **FAIL** 0.250 (worst cell 0.167, n=24) | PASS 1.000 (worst cell 1.000, n=36) | PASS 1.000 (worst cell 1.000, n=36) |
| P2 hosted bytes for TV / self-TTS / non-owner | 0 | **FAIL** 42672768 B | PASS 0 B | PASS 0 B | PASS 0 B | PASS 0 B | **FAIL** 6301056 B |
| P3 false hosted openings per 24 h | <= 1 | **FAIL** 3238/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) | PASS 0/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) | PASS 0/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) | PASS 0/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) | PASS 0/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) | PASS 0/day with a TV on 4 h; quiet real room <= 87.0/24h (95% bound) |
| P4 local STOP recall | >= 0.99 | **FAIL** 0.875 (n=64) | **FAIL** 0.875 (n=64) | **FAIL** 0.875 (n=64) | **FAIL** 0.875 (n=64) | **FAIL** 0.875 (n=64) | **FAIL** 0.875 (n=64) |
| P5 STOP tail p95 (hotword end -> latch) | <= 800 ms | **FAIL** 935 ms | **FAIL** 935 ms | **FAIL** 935 ms | **FAIL** 935 ms | **FAIL** 935 ms | **FAIL** 935 ms |
| P6 STOP finite-sample: n >= 60, all <= 1.0 s | n >= 60 and 0 over 1.0 s | PASS n=64, 0 over 1.0 s | PASS n=64, 0 over 1.0 s | PASS n=64, 0 over 1.0 s | PASS n=64, 0 over 1.0 s | PASS n=64, 0 over 1.0 s | PASS n=64, 0 over 1.0 s |
| P7 false STOPs per 24 h | <= 1 | **FAIL** TV tape 864/24h; real room <= 87/24h | **FAIL** TV tape 864/24h; real room <= 87/24h | **FAIL** TV tape 864/24h; real room <= 87/24h | **FAIL** TV tape 864/24h; real room <= 87/24h | **FAIL** TV tape 864/24h; real room <= 87/24h | **FAIL** TV tape 864/24h; real room <= 87/24h |
| P8 self-transcribed motion commands | 0 | BLOCKED 3 with no AEC, 3 at a hypothetical 20 dB | PASS 0 — the gate admitted no self-speech at any echo level (0 to -30 dB) | PASS 0 — the gate admitted no self-speech at any echo level (0 to -30 dB) | PASS 0 — the gate admitted no self-speech at any echo level (0 to -30 dB) | PASS 0 — the gate admitted no self-speech at any echo level (0 to -30 dB) | PASS 0 — the gate admitted no self-speech at any echo level (0 to -30 dB) |
| P9 AEC attenuation, XVF3800 -> CQRobot | >= 20 dB | BLOCKED UNDETERMINED_ON_THIS_HOST | BLOCKED UNDETERMINED_ON_THIS_HOST | BLOCKED UNDETERMINED_ON_THIS_HOST | BLOCKED UNDETERMINED_ON_THIS_HOST | BLOCKED UNDETERMINED_ON_THIS_HOST | BLOCKED UNDETERMINED_ON_THIS_HOST |
| P10 barge-in acoustic stop p50 | <= 0.52 s | BLOCKED not measurable here | BLOCKED not measurable here | BLOCKED not measurable here | BLOCKED not measurable here | BLOCKED not measurable here | BLOCKED not measurable here |
| P11 cancel p95 | <= 700 ms | **FAIL** 740 ms (DUPLEX-1, shipped floor) | **FAIL** 740 ms (DUPLEX-1, shipped floor) | **FAIL** 740 ms (DUPLEX-1, shipped floor) | **FAIL** 740 ms (DUPLEX-1, shipped floor) | **FAIL** 740 ms (DUPLEX-1, shipped floor) | **FAIL** 740 ms (DUPLEX-1, shipped floor) |
| P12 critical-slot accuracy | >= 0.95 | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) | **FAIL** 0.700 (n=40, espeak); 0.850 (n=20, piper control) |
| P13 first-word loss with the 500 ms pre-roll | <= 2 % | **FAIL** 2.8 % (n=36) | **FAIL** nan % (n=0) | **FAIL** 21.9 % (n=32) | PASS 0.0 % (n=6) | **FAIL** 2.8 % (n=36) | **FAIL** 2.8 % (n=36) |
| P14 endpoint p50 | <= 0.8 s | PASS 0.56 s | **FAIL** nan s | PASS 0.56 s | PASS 0.62 s | PASS 0.56 s | PASS 0.56 s |
| P15 projected spend, H1 day model (14.5 turns/h, 12 h, TV 4 h) | <= $0.50/day | **FAIL** $3.31/day (owner $0.15 + TV $3.16); $99/month vs the $160 envelope | PASS $0.10/day (owner $0.10 + TV $0.00); $3/month vs the $160 envelope | PASS $0.16/day (owner $0.16 + TV $0.00); $5/month vs the $160 envelope | PASS $0.10/day (owner $0.10 + TV $0.00); $3/month vs the $160 envelope | PASS $0.15/day (owner $0.15 + TV $0.00); $5/month vs the $160 envelope | PASS $0.15/day (owner $0.15 + TV $0.00); $5/month vs the $160 envelope |
| P16 second-person false accept | <= 2 % | **FAIL** 100.0 % (n=62) | PASS 0.0 % (n=62) | PASS 0.0 % (n=62) | PASS 0.0 % (n=62) | PASS 0.0 % (n=62) | **FAIL** 100.0 % (n=62) |
| P17 owner-recording REPLAY acceptance (honesty row) | reported; no arm may claim immunity | — 100.0 % accepted (n=36) | — 0.0 % accepted (n=36) | — 69.4 % accepted (n=36) | — 0.0 % accepted (n=36) | — 0.0 % accepted (n=36) | — 100.0 % accepted (n=36) |

## Why the rule is unsatisfiable here (the hardware finding)

`scrum/20260822/task_44/HWMIC_STATUS.md` recorded `frames_out 0` — nothing had
ever been played through the board. This study pushed the first audio to it.

* **There is no second loudspeaker.** Both other ALSA cards report every
  non-`off` profile `available: no` (HD-Audio Generic ALC1220 and the NVIDIA
  HDMI block), and no Bluetooth sink is paired. So the owner, a second person, a
  television and a fan **cannot be presented through air**: playing them through
  the array's own DAC would hand the XVF3800's on-chip AEC its own reference and
  cancel the stimulus. Every arm row below is therefore tier `replay`, over a
  **real recorded room floor**, and none of them is through-air evidence.
* **Whether the robot's speaker makes a sound is undetermined, and undeterminable
  from this host.** At 0.95 amplitude, five 150 ms bursts with 2 s gaps (an
  adaptive canceller must re-converge at each onset) raised the ASR beam by
  **0.6–2.8 dB** (ch0, the Conference beam: −1.4 to +4.2 dB) against a room floor
  of −52.3 dBFS. That is equally consistent with an unwired amp and with a
  canceller doing its job; there is no independent microphone here to break the
  tie. The owner action that settles it is one sentence long: play something and
  listen, or put any second microphone in the room.
* **Consequence for the self-speech row (P8).** With the array's own DAC playing
  the robot's piper voice at −0.9 dBFS, the captured ASR beam yielded
  **0 VAD spans and no words** over five utterances — the transcriber returned `[BLANK_AUDIO]`, `[ Silence ]` and `(wind blowing)`, and the capture RMS never left the room floor (−51.4 to −54.3 dBFS). Under either explanation this is a real-device
  observation that no self-transcribed motion command occurred — it is *not* an
  AEC attenuation figure and is not offered as one.

## The findings

**F1 — The product's speaker-ID threshold is mis-calibrated for a room, and that
is the whole of arm (b)'s failure.** `voice_identity.DEFAULT_THRESHOLD` is 0.55.
Enrollment on clean audio scores 0.64–0.83 against its own gallery, but the same
speaker heard across this room at 25 dB SNR scores **p50 0.47** (2 s window,
channel-matched gallery). At 0.55 the owner is admitted **16.7 %** of the time.
Yet the *separation* is perfect: **EER 0.000** at ≥ 2 s, and the threshold that
buys 0.95 owner recall (**0.352**) accepts **0.0 %** of impostors (n=36 owner,
31 impostor). Owner-voice gating is not refuted — its shipped operating point is.
The threshold must be calibrated on the deployment channel; a gallery enrolled
through the same microphone and room is measurably better than a clean one.

**F2 — Replay is not defeated by identity, exactly as A9 predicted.** At the
product threshold nothing replayed is admitted, because nothing is admitted at
all. At the *calibrated* threshold — the only one at which the owner can talk to
the dog — **52.8 %** of simulated loudspeaker replays of the owner are accepted
(2 s window). Wake phrase does not help: a recording contains the phrase too.
**No arm may claim replay immunity, and this one does not.** Push-to-talk is the
only arm that refuses replay here, and only under the stated assumption that the
spoofer does not also hold the owner's button.

**F3 — STOP-LOCAL does not exist in the product, and the harness reference
implementation misses three of its four bars.** `realtime/lane.py:47-53` is explicit:
"A spoken 'stop' during a hosted session is transcribed in the cloud. It is
supplemental." The A6/STOP-LOCAL reference built here is Silero v6 + a resident
`whisper.cpp base.en` whole-word spot on a 1.0 s sliding window at a 300 ms
cadence, with a single in-flight transcription (so a transcriber too slow to keep
up produces late latches, as it would in a room). Measured, n=64 trials over four voices, four
phrasings and four geometry cells, with the transcriber idle (mean ASR latency
**357 ms**, matching its isolated benchmark, so no contention inflated these):

| A9 bar | measured | |
|---|---|---|
| recall ≥ 0.99 | **0.875** (56/64) | **MISS.** Every miss is at 3 m, 30–60° off-axis |
| p95 ≤ 800 ms | **935 ms** (p50 349, max 979) | **MISS** |
| n ≥ 60, all ≤ 1.0 s | 64 trials, **0 over 1.0 s** | met, on the 56 that latched |
| ≤ 1 false STOP / 24 h | **6 in 10 min of TV ⇒ ≈ 864/24 h** | **MISS by ~3 orders of magnitude** |

The false-STOP row is the one that should change the design, and its evidence is
its own transcripts: `stop talking to me`, `I'm not going to stop the tattoo`,
`just stop talking`, `stop at the intersection`. **"Stop" is an ordinary English
word**, and a matcher that must bypass identity (A2: the stop may not depend on
any gate) therefore cannot also be rare. The whole-word rule is already doing
work — it *refused* `stopped at the meeting` and `stopping to tell me`, which a
substring matcher would have latched on — but it cannot refuse the word itself.
**None of the six false triggers contained the dog's name.** A name-prefixed stop
("Parcel, stop") would have scored zero false triggers on this tape, at the cost
of changing the STOP contract so a bare shouted "Stop!" no longer latches. That
trade is an owner decision, not an executor's, and it is the concrete
recommendation this row produces for the STOP-LOCAL build gate.

**F3b — Two content rows were measuring the proxy voice, and a control says how
much.** espeak scored critical slots at 0.700 and the wake phrase at 0.542; the
transcripts show why ("Go to the **lampost**", "**Pausell**, come here"). The same
sentences re-synthesized with `models/piper/voice.onnx` through the same channel,
gate and transcriber score **0.850** and **1.000**. So the wake-phrase row's
apparent failure is entirely the proxy's, while critical-slot accuracy is
genuinely below bar in both voices — whisper `base.en` misses the dog's name
("Pursal") and place names ("crosewalk") often enough that a **constrained or
biased decoder over the place/name vocabulary is a build item**, not a tuning
knob. Arm (c)'s own P1 (0.250) is measured on wake-carrying turns in espeak and
should be re-read against the piper control's 1.000 detection.

**F4 — A plain VAD still cannot gate a room with a television in it, and now the
number is on a real floor.** H1 measured 960.6 VAD opens/hour on attenuated TV
speech over *synthetic* silence. On this room's **measured** floor (−52.3 dBFS
RMS on the ASR beam) the same gate opens **809.4/hour** on the TV proxy and
uploads 3 047 s of audio per hour. Arm (b) at the calibrated threshold, arm (c)
and push-to-talk each admit **zero bytes** of it.

**F5 — The real room is quiet, and that is not the same as proving a bar.**
**49.6 minutes** of this room through the array
(0 xruns over 49 logged minutes, floor −53.5 dBFS RMS, frame p5/p50/p99 −55.9/−54.1/−49.3 dBFS, peak
−36.3 dBFS) produced **0 VAD openings, 0 owner-ID admissions and 0 false STOPs** —
the STOP matcher never even reached its transcriber, because Silero never called
it speech. That is the desired behaviour, and it proves less than it looks:
with zero events in T hours the 95 % upper bound on the rate is 3/T, so this tape
supports **≤ 87 events/24 h**, not ≤ 1. Establishing the pre-registered ≤ 1/24 h
bar needs roughly **72 h** of event-free tape, and a room with a television in it is the
case that actually matters — where the same gate opens 809 times an hour. The
tape was stopped at 49.6 min of its 120 min schedule; the bound is the only row
that would have improved (to ≈ 36/24 h), and it would still not reach 1.

## What was run

```bash
source scripts/env-audio.sh                       # PortAudio, user-space prefix
LD_LIBRARY_PATH=third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64 \
  third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64/whisper-server \
  -m models/whisper/ggml-base.en.bin -t 8 --host 127.0.0.1 --port 8099
.parcel/bin/python research/20260824/voice-gate/harness/record_ambient.py \
  $SCRATCH/ambient_tape.raw --seconds 7200 --device 4
research/20260824/voice-gate/run.sh $SCRATCH        # corpus -> arms -> summarize
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label voicegate \
  .parcel/bin/python -m pytest tests/test_voicegate_probe.py -q
```

Raw rows: `results/*.json` (11 files) plus the generated
`results/consolidated_table.md`; `logs/` untracked per C14.

## Environment

HEAD `9d6b37a` (working tree dirty from concurrent
sessions on `src/parcel_robot/navigation/**`, none of it this card's).
`.parcel/bin/python`, `.parcel/bin/ruff` clean on every added file, **zero
`noqa`**. PortAudio via `scripts/env-audio.sh`; XVF3800 at PortAudio device 4
(`hw:1,0`), 16 kHz duplex, ch0 Conference / ch1 ASR — **all rows use ch1**.
Capture needs the playback endpoint open (`audio_gateway.py` hardware fact 3b:
an input-only stream on this device never fires a callback), so the ambient tape
was recorded with the DAC clocking digital silence.

One server started by this card and **stopped at close**: `whisper-server`
(`ggml-base.en.bin`, 8 threads) on **127.0.0.1:8099** — a private port, not the
owner's `:8080`/`:8081`/`:8765`; 616 transcriptions in the arm run at a mean
**357 ms**. No judge server. GPU untouched (1 %, 1.5 GB, another session's).
1-min load 1.5–8.3, well under the 60 the preamble sets for latency rows. No
simulator, no perception daemon, no `ci_gate.py --tier`; git read-only.

**Audio settings: nothing was changed.** The XVF3800 profile was already
`Analog Stereo Duplex`, and both other cards were already `off`; sink volume
0.40 and source 0.82 before and after, verified by `pw-dump` and `wpctl` at both
ends. No `wpctl set-profile` was ever needed or issued.

## Deviations from the DESIGN, declared

1. **No through-air presentation.** The DESIGN's §Experiment 1–2 (playback
   calibrated to 60–70 dB(A), 1 m/3 m × 0°/30°/60°, 20 trials per cell) could not
   be executed: there is no loudspeaker. Geometry is *simulated* in
   `harness/channel.py` — free-field spreading, an off-axis high shelf, three
   reverb taps at 3 m — over a real room bed, and every cell carries n=6, not 20.
2. **The owner is a proxy.** No recording of the owner's voice exists on this
   disk (`evals/20260820/voice_corpus_v1` keeps only its six espeak impostors;
   `recordings/` holds no `owner.wav`), and the owner is not present. The
   designated research owner is one real human prompt voice
   (`models/csm-1b/prompts/conversational_a.wav`); impostors are the other five.
   Content rows (STOP, wake, critical slots) use espeak voices because arbitrary
   words cannot be put in a fixed recording's mouth. The owner's live gallery was
   never opened; the research gallery is in the session scratchpad because
   `tools/enroll_owner_voice.py` refuses to write a voice profile inside the repo.
3. **Calibration is an SNR anchor, not a sound level.** Speech sits 25 dB above
   the array's measured floor, assuming a ~40 dB(A) room and 65 dB(A) speech.
   There is no SPL meter here; no row may be read as one.
4. **The television is a proxy** — real human conversational speech plus espeak
   news lines at −8 dB relative to the owner, not a television.
5. **Push-to-talk and restricted listening use perfect oracle signals** (the
   owner never fumbles the button; the presence detector never errs), so both
   arms' numbers are upper bounds. The restricted arm's television protection
   holds only while nobody is home: with a person present it degenerates to arm
   (a), whose TV row is 809.4 opens/hour.
6. **No product seam was added.** DESIGN OWNS permits `audio/activation_gate.py`
   (pure, flag-off). Since the study's decision is push-to-talk and no ambient arm
   is evidenced, shipping a flag-off ambient gate would be code with no result
   behind it. The gate lives in the harness.
7. **The calibrated arm's threshold is fitted on the trials it is scored on.**
   36 owner trials is too few to hold out a calibration split; arm (b)'s
   calibrated recall is an upper bound and is labeled as one in `arms.json`.

## What this does not prove

Nothing about the robot's acoustics: no motor or gait noise, no body-mounted
array, no real speaker, no AEC figure, no outdoor wind (the fan row is pink noise
with a gust envelope). Nothing about *this owner's* voice or how TitaNet behaves
on it. Nothing about a real television, a real second person in the room, or a
replay through a real phone. No hosted call was made, so nothing here measures a
hosted lane — only what a gate would have handed one. The STOP matcher is harness
code with no product caller; its latency excludes the acoustic path, driver
buffering and the physical stop (A5's envelope). A 49.6 min event-free tape
cannot establish ≤ 1/24 h: the 95 % bound is 3/T, so that bar needs ~72 h.

## Cost

**$0.00 hosted.** No hosted call was made at any point; every "hosted byte" is a
counter on a fake transport in `harness/gate.py`. Projected spend rows use
`realtime/cost.py`'s `MINI_RATE_CARD` and H1's measured 10 audio tokens/second.
