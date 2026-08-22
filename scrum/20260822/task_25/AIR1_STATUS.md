# AIR-1 status — tools + runbook landed; every measurement row is OWNER-GATED

**Executor:** Claude Opus (session 799cb356) · **Verifier:** Fable ·
**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **HEAD at start:** `8862220`

## Headline

The three tools and the runbook are in, the 16 kHz rate pin and the scorecard
schema have tests with four seeded-RED proofs, and **not one acceptance number
was claimed** — the array is on the desk but the speaker, the second
loudspeaker, the udev rule, the enrolled voice and the television are all owner
actions, so every row in the card's pre-registered list is listed below with the
exact command that produces it and nothing else.

Three things were learned before the owner sits down, and two of them change the
session:

1. **The card's rate claim is exactly right, and now measured.** `hw:2,0`
   accepts 16 000 Hz in both directions and answers `PaErrorCode -9997` for
   8 000, 22 050, 24 000, 44 100 and 48 000. The hosted lane is 24 kHz and Piper
   is 22.05 kHz, so the array path must resample; `tests/test_air1_rate_pin.py`
   couples the pin to `protocol.PCM16_SAMPLE_RATE_HZ` and
   `voice_audio.SAMPLE_RATE_HZ` so moving either reddens a test instead of
   producing a mute robot.
2. ~~**ERLE cannot be measured the way `ACOUSTIC_BRINGUP_PLAN.md` §5.3 measures
   it.** That method reads the raw mic and the cancelled node side by side. The
   XVF3800 cancels on-chip and the 2-channel firmware exposes only processed
   beams (ch0 Conference, ch1 ASR) — there is no raw mic to read.~~
   **REFUTED in the correction pass — see §Correction pass, item 6.** Each USB
   capture channel is a runtime-selectable mux and the raw microphone, the
   canceller's input and the far-end reference are all available on the
   installed firmware. §5.3's same-instant method IS available, the second
   loudspeaker is unnecessary, and `--method mux` is now the primary path. The
   three-leg measurement described here survives only as the fallback for a host
   that cannot reach the control interface.
3. **Interrupt latency cannot be scored from the R17 tee at all.**
   `audio_gateway.note_interrupt` queues the interrupt *with* a wall stamp and
   `mark_interrupted` throws it away; `robot.wav` is written as fast as the
   provider streams, so it is not a clock either. The scorecard reports
   `interrupt_p50_s` as **unmeasured with that reason** rather than as a number.
   That is a handoff to MARK-1, filed below. `audio_gateway.py` was not touched.

## What changed

`git diff --stat` restricted to this card's OWNS (the two config files also
carry TURN-1's concurrent turn-detection block; only the marked AIR-1 region
below is mine):

```
 configs/realtime.prototype.yaml.example |  25 +      (AIR-1 device notes region)
 configs/realtime.yaml.example           |  25 +      (AIR-1 device notes region)
 tools/xvf3800_probe.py                  | 839 +      (new)
 tools/measure_erle.py                   | 620 +      (new)
 tools/bargein_through_air.py            | 643 +      (new)
 tests/test_air1_rate_pin.py             | 247 +      (new)
 tests/test_air1_scorecard.py            | 332 +      (new)
 scrum/20260822/task_25/SESSION.md       | 347 +      (new, the runbook)
 8 files changed, 3078 insertions(+), 0 deletions(-)
```

* **`tools/xvf3800_probe.py`** — four read-only sections (USB/udev, ALSA
  `stream0`, PipeWire defaults, the PortAudio rate matrix) plus two opt-in ones
  that touch the device (`--doa N`, `--rms SECONDS`). Carries the rate pin
  (`ARRAY_SUPPORTED_RATES_HZ`, `assert_array_rate`, `resample_plan`,
  `PRODUCER_RATES_HZ`) and the downmix hazard number. DoA polling goes through
  the **product** `realtime.voice_identity.UsbDoaReader`, not a private copy.
* **`tools/measure_erle.py`** — the three legs plus a double-talk leg, a
  deterministic speech-shaped 4 Hz-modulated probe (seed pinned; `--probe-wav`
  takes a real robot utterance instead), the first-2 s exclusion, and a
  **reference-microphone witness** (`--reference-device`) that proves the two
  legs were the same loudness without an SPL meter. A failed level match forces
  the verdict to `unmeasured` — the subtraction is reported but never laundered
  into a pass.
* **`tools/bargein_through_air.py`** — the seven-row scorecard, its frozen
  thresholds, and `verify_scorecard`, which refuses six specific lies (moved
  goalpost, flipped direction, verdict that does not follow from its value, pass
  with no evidence, unmeasured carrying a number, `n` below the row's minimum).
  False barge-ins come out of the R17 index; the owner's silence is *checked*
  against `owner.wav` rather than assumed.
* **`configs/realtime*.example`** — a marked `AIR-1 device notes` region inside
  the existing `voice_identity` DoA comment (disjoint from TURN-1's
  turn-detection block and CURIO-1/ROAM-1's keys), recording the four facts a
  person needs at 2 a.m.: the node mode and this host's real sysfs path, 16 kHz
  only with the −9997 symptom, ch0/ch1 and the downmix, and "the AEC references
  its own DAC, so the speaker hangs off the array".
* **`SESSION.md`** — the runbook, ten steps, 90 min end to end / ~1 h 20 min
  once the week-1 speaker step is already done.

## How verified

Environment: `.parcel/bin/python`, `.parcel/bin/ruff` 0.16.1, `TMPDIR` unset,
`source scripts/env-audio.sh` where PortAudio is needed.

**Targeted tests (both files, host with the array attached):**

```
$ source scripts/env-audio.sh
$ env -u TMPDIR .parcel/bin/python -m pytest \
      tests/test_air1_rate_pin.py tests/test_air1_scorecard.py -q
34 passed, 1 warning in 7.81s
```

**Same tests without PortAudio on the path (the CI shape):**

```
$ env -u TMPDIR .parcel/bin/python -m pytest \
      tests/test_air1_rate_pin.py tests/test_air1_scorecard.py -q
33 passed, 1 skipped, 1 warning in 7.32s
```

The one skip is the live hardware row, which names its own reason
(`PortAudio is not loadable here` / `no XVF3800 hw: device`) instead of
disappearing.

**Ruff:**

```
$ .parcel/bin/ruff check tools/xvf3800_probe.py tools/measure_erle.py \
      tools/bargein_through_air.py tests/test_air1_rate_pin.py \
      tests/test_air1_scorecard.py
All checks passed!
```

Ratchet: the baseline is 7 fingerprints and **this card adds none**. A
whole-tree `ruff check . --output-format=json` run during this card showed 12,
the five extras being `tests/test_mark1_barge_in_mark.py` (F401, ISC004, RUF046),
`tests/test_curio1_chatter.py` (RUF100) and `tests/test_roam1_behavior.py`
(RUF100) — three concurrent cards mid-flight, none of them mine. `ci_gate.py`
was not run (P0-E/GATE-0's, per the standing rules).

**The device probe, read-only, on this host:**

```
$ .parcel/bin/python tools/xvf3800_probe.py --json ~/.cache/parcel-air1/probe.json
usb       2886:001a at /sys/bus/usb/devices/3-1 (/dev/bus/usb/003/008, mode 0o664,
          control read-only — udev rule missing)
alsa      hw:2,0  capture [16000] Hz x2 S16_LE · playback [16000] Hz x2
pipewire  default sink   reSpeaker XVF3800 4-Mic Array Analog Stereo (vol 0.4) — array
pipewire  default source reSpeaker XVF3800 4-Mic Array Analog Stereo (vol 0.82) — array
rates     input accepts ['16000'] Hz; every other rate is PaError -9997
          hosted_realtime   24000 Hz → resample
          legacy_loop       16000 Hz → direct
          piper_tts         22050 Hz → resample
exit 0
```

Nothing in that run writes: no PipeWire profile change, no default-device move,
no USB control write, no ALSA stream opened (`--rms` and `--doa` were not
passed). The device's own `Status: Stop` was unchanged before and after.

**The product-path dry run** — the false-barge-in metric computed from a session
written by the **product** tee (`realtime.audio_gateway.SessionAudioCapture`),
not from a hand-made index, and passed through the product's own
`verify_capture_index` first:

```
verify_capture_index: []
scored: {'utterances': 100, 'interrupted': 2, 'rate': 0.02}
owner_silence: {'checked': True, 'frames': 100, 'p50_dbfs': -76.33,
                'fraction_over_speech_floor': 0.0, 'silent': True}
verify_scorecard: []
pass        false_barge_in_rate              0.02
unmeasured  erle_db / robot_utterances_as_owner_turns / interrupt_p50_s /
            tv_owner_attributed_turns / doa_ok_fraction / hosted_spend_usd
```

That 0.02 is a **synthetic** rate from a synthetic session; it proves the
metric's plumbing, not the array.

### Seeded RED, one per new guard

Each seed was applied to the product file, watched fail, restored from a
byte-identical copy (sha256 checked), `__pycache__` purged, and re-run green.

| # | guard | seed | RED | restored |
|---|---|---|---|---|
| A | the 16 kHz rate pin | `ARRAY_SUPPORTED_RATES_HZ = (16_000, 24_000)` | 5 failed, 7 passed — incl. `test_the_array_itself_refuses_24k` on the real hardware | `48b2d0ab…4bc6` → 12 passed |
| B | `verify_scorecard` requires evidence | the evidence check made unreachable | 1 failed (`test_a_pass_with_no_evidence_is_refused`), 19 passed | `f0cf032d…47b4` → 20 passed |
| C | the owner's silence is checked | `"silent": True` hard-coded | 1 failed (`test_a_silent_arm_that_was_not_silent_is_not_scored`), 19 passed | `f0cf032d…47b4` → 20 passed |
| D | an untrustworthy ERLE cannot become a pass | `erle_trustworthy = erle is not None` | 1 failed (`test_an_erle_report_that_could_not_be_measured_does_not_become_a_pass`), 21 passed | `2988686f…c9ef` → 22 passed |

## Pre-registered numbers

The card's seven acceptance rows are frozen verbatim in
`bargein_through_air.ROWS` and asserted against the card text by
`test_the_rows_are_exactly_the_cards_pre_registered_acceptance`. None of them
was measured, so none is met or missed yet.

Three **auxiliary** thresholds are new with this card and were fixed before any
measurement existed:

* `FLOOR_MARGIN_DB = 3.0` — closer than this to the noise floor and ERLE is
  reported as a lower bound, not a number.
* `REFERENCE_TOLERANCE_DB = 2.0` — the two ERLE legs may differ by this much at
  the witness microphone before the level match is called failed.
* `OWNER_SILENCE_DBFS = -45.0` with a 2 % frame ceiling — above this the silent
  arm is not silent and the false-barge-in row refuses to score.

## What this does not prove

* **Nothing acoustic.** No ERLE, no false-barge-in rate, no interrupt latency,
  no TV arm, no far-field arm. The array is present; the speaker on its amp, the
  second loudspeaker, the udev rule, the enrolled voice and the television are
  not, and no number was estimated in their absence.
* **The DoA path is unexercised end to end.** `pyusb` is not installed in
  `.parcel` and `/dev/bus/usb/003/008` is `root:root 0664`, so every
  `DOA_VALUE` read would be `Errno 13` today. What is proved is that the
  permission state is *detected and named*, not that a read succeeds.
* **The rate pin is a pin, not a fix.** It says the hosted lane's 24 kHz must be
  resampled to reach this array. It does not resample anything, and no
  production path was rewired — the production ear is the browser and stays
  there.
* **The scorecard's plumbing is proved on synthetic sessions.** A real session
  may expose shapes the tee's own test fixtures do not.
* **`verify_scorecard` cannot detect an honest mistake.** It catches a card that
  contradicts itself. A perfectly consistent card built from a badly run session
  passes.

## Deviations from the card, declared

1. **ERLE is a three-leg differential measurement, not one recording.** The card
   says "robot speech … vs array capture ch1 with the owner silent". That gives
   a residual level, which is not ERLE — ERLE needs the uncancelled level too,
   and on a chip AEC with no raw-mic tap the only way to get it is a second
   loudspeaker. Reason: a single-recording "ERLE" would have been a number with
   the wrong name on it, and the week-3 gate reads the name.
2. **`bargein_through_air.py` scores; it does not drive.** The card's phrasing
   ("with the R17 tee, scores interrupt latency …") could be read as a session
   driver. Driving a hosted session costs money the owner is present for anyway,
   and the panel already drives it. Reason: an assembler over the session's
   artefacts is re-runnable, costs nothing, and cannot corrupt a live lane.
3. **Interrupt latency is not scored from the tee.** Mechanism in the headline.
   Reported as an unmeasured row with its reason; HALTED on the fix because it
   lives in `audio_gateway.py`, which is MARK-1's.
4. **The rate sweep ran before the pin was written.** The card states the
   −9997 claim as a fact to pin; the sweep was run to confirm it and then the
   constant was written to match. Declaring it because "measured, then
   pre-registered" is the wrong order even when the card supplied the
   prediction.
5. **`pyusb` was not installed.** The card's runbook lists `pip install pyusb`
   as an owner step and `.parcel` is shared with six concurrently executing
   cards; a package install into their interpreter mid-run is not a risk this
   card needed to take. It is step 3 of `SESSION.md`.
6. **A `--reference-device` witness was added** beyond the card's scope, because
   the level match between the two ERLE legs is the measurement's weakest joint
   and this host has a second analog input that can witness it for free.

## OWNER-GATED rows — every command, in order

`SESSION.md` is the sit-down version with timings and the mechanism table. The
rows, condensed:

| row | gate | command |
|---|---|---|
| DoA poll | ≥ 95 % of 100 | `sudo tee /etc/udev/rules.d/99-respeaker-xvf3800.rules <<< 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001a", MODE="0660", GROUP="plugdev", TAG+="uaccess"'` then `sudo udevadm control --reload && sudo udevadm trigger --action=change /sys/bus/usb/devices/3-1`, `.parcel/bin/pip install pyusb`, `.parcel/bin/python tools/xvf3800_probe.py --doa 100 --json ~/.cache/parcel-air1/probe.json` |
| ch0/ch1 levels + downmix | reported, no gate | `.parcel/bin/python tools/xvf3800_probe.py --rms 5 --json ~/.cache/parcel-air1/probe_rms.json` |
| speaker on the array's amp | audible, undistorted at sink 0.40 | `speaker-test -D plughw:2,0 -r 16000 -c 2 -t sine -l 1` |
| ERLE floor leg | — | `.parcel/bin/python tools/measure_erle.py --leg floor --seconds 12 --out ~/.cache/parcel-air1/floor.json` |
| ERLE uncancelled leg | — | `.parcel/bin/python tools/measure_erle.py --leg uncancelled --seconds 12 --play-device 4 --play-rate 48000 --reference-device 4 --out ~/.cache/parcel-air1/uncancelled.json` |
| ERLE cancelled leg | — | `.parcel/bin/python tools/measure_erle.py --leg cancelled --seconds 12 --reference-device 4 --out ~/.cache/parcel-air1/cancelled.json` |
| double talk | residual vs owner p90 | `.parcel/bin/python tools/measure_erle.py --leg doubletalk --seconds 12 --out ~/.cache/parcel-air1/doubletalk.json` |
| **ERLE** | **≥ 20 dB** | `.parcel/bin/python tools/measure_erle.py --report ~/.cache/parcel-air1/{floor,uncancelled,cancelled,doubletalk}.json --out ~/.cache/parcel-air1/erle_report.json` |
| 20 turns + 20 interruptions | 0/20 robot-as-owner; p50 ≤ 0.52 s | `scripts/launch_stack.sh --prototype` with `mode: audio`, `capture.enabled: true`, `voice_identity.doa: true`; then the panel |
| **false barge-in** | **≤ 2 %** | 10 min of robot monologue, owner silent, then `--capture recordings/<session>` |
| **TV arm** | **0** owner turns in 10 min | `.parcel/bin/python tools/xvf3800_probe.py --doa 200` while the TV plays → `rejected_sector: [angle−15, angle+15]`, restart, 10 min |
| the scorecard | schema-valid | `.parcel/bin/python tools/bargein_through_air.py --capture … --tv-capture … --erle … --probe … --spend recordings/spend.jsonl --out scrum/20260822/task_25/AIR1_SCORECARD.json` |
| hosted spend | ≤ $2 | read from `recordings/spend.jsonl` by the line above |

After the session, `AIR1_SCORECARD.json` and the tool's printed table go into a
new §"the scorecard" here, **verbatim, including the unmeasured rows**.

## Handoffs

* **→ MARK-1 (`task_22`, owns `audio_gateway.py`).** `note_interrupt(seq)` queues
  the interrupt with `self._wall()`; `_drain` calls `mark_interrupted()`, which
  sets a boolean and drops the timestamp. One field —
  `segment["interrupted_at"] = _iso(wall)` — turns AIR-1's `interrupt_p50_s`
  from an unmeasured row into a measurement taken from the tee alone, with no
  browser instrumentation and no `--events` file. `bargein_through_air.py` will
  need a three-line change to read it; AIR-1 will take that when MARK-1 lands.
* **→ MARK-1.** The ch0/ch1 downmix number from step 4 of `SESSION.md` is the
  evidence for "the ear takes ch1 explicitly"; `downmix_hazard()` produces it in
  one call and MARK-1 is welcome to import it.
* **→ DUPLEX-1 (`task_26`).** `measure_erle.py`'s double-talk leg reports the
  owner's p90 level against the cancelled residual as `signal_to_echo_db`. That
  ratio, not ERLE, is what a VAD actually sees, and it is the number the
  provisional-duck threshold should be set from.
* **→ PO-1 (`task_27`).** The scorecard is the artefact the week-3 gate reads.
  Until the owner session runs, PO-1 has **no** through-air evidence — not a
  weak signal, none — and should say so rather than treating the tools' landing
  as progress on the acoustics question.
* **→ the owner.** Two purchases this card implies and neither is a robot: a
  small speaker for the array's JST-PH2.0 amp (if the week-1 one has not
  arrived) and, optionally, any second powered speaker for the uncancelled leg —
  earbuds laid next to the array work.

---

# Correction pass — Fable verification, 2026-08-22

Six confirmed findings, all fixed; four notes, all acted on. One of the six
refuted a premise this card was built on, so the headline changed with it.

## Headline of the correction

**The instrument was broken in a way that would have produced a confident wrong
answer, and the premise under it was false.**

* The `uncancelled` ERLE leg — the exact command the runbook told the owner to
  run — recorded the **noise floor**, because `sounddevice.play(blocking=False)`
  followed by `sounddevice.rec(blocking=True)` stops the playback as its first
  act. The owner would have got ≈0 dB attenuation, a `fail`, and a printed
  mechanism ("a clipped amplifier") that had nothing to do with it.
* And the second loudspeaker that leg exists for was **never necessary**: the
  array's two USB capture channels are a runtime-selectable mux, so the raw
  microphone, the canceller's input and the far-end reference are all readable
  on the firmware already installed.

## What changed

File sizes after the pass (all of these are this card's OWNS; the two config
files also carry TURN-1's concurrent block, so only the marked AIR-1 region is
counted for them):

```
 tools/xvf3800_probe.py                  | 1203 lines  (was 848; +XvfControl, gain state, exit code)
 tools/measure_erle.py                   |  966 lines  (was 620; +explicit streams, mux method, rename)
 tools/bargein_through_air.py            | 1060 lines  (was 643; +spend join, override, owner split)
 tests/test_air1_streams.py              |  324 lines  (new — the blocker's guard)
 tests/test_air1_mux.py                  |  242 lines  (new — control-write discipline)
 tests/test_air1_scorecard.py            |  591 lines  (was 332)
 tests/test_air1_rate_pin.py             |  247 lines  (unchanged)
 configs/realtime*.example               |   32 lines each in the AIR-1 region (was 24)
 scrum/20260822/task_25/SESSION.md       |  433 lines  (was 347)
```

## 1 · BLOCKER — the two-device branch recorded silence

`sounddevice` 0.5.5's `play()`, `rec()` and `playrec()` share one module-level
context, and `_CallbackContext.start_stream` opens with `stop()`. Verified in
the installed source, not inferred:

```
$ .parcel/bin/python -c "import inspect,sounddevice as sd; print(inspect.getsource(sd._CallbackContext.start_stream))"
    def start_stream(self, StreamClass, samplerate, channels, dtype, callback,
                     blocking, **kwargs):
        stop()  # Stop previous playback/recording
```

**Fixed** with explicit `_ProbePlayer` (`OutputStream` + callback) and
`_StreamRecorder` (`InputStream` + callback), which the shared context cannot
reach — the pattern `_ReferenceRecorder` already used, now the pattern
everywhere. The one-device path keeps `playrec` (one duplex stream, nothing to
overlap). A **runtime guard** additionally refuses the leg if the player is not
active when the recorder opens, and a short capture is refused rather than
padded.

`tests/test_air1_streams.py` drives `play_and_record` with fake stream classes
and asserts the output stream is still active at the instant the input starts —
no device, no PortAudio.

**And `build_report` now refuses the symptom independently:** an uncancelled leg
within `FLOOR_MARGIN_DB` of the floor leg is `unmeasured` with *"the probe did
not reach the microphone — check --play-device"*, never subtracted.

## 2 · Two rows had no producer, and now say so

`score_turns` reads a `speaker`/`origin`/`was_robot` JSONL that **nothing in this
tree writes**. The runtime does keep per-turn identity — `_stamp_speaker_label`
into a 400-row ring, readable via `speaker_label_rows()` — but it is not on
`/api/state`, never written to disk, and stamped with `time.monotonic()`, which
cannot be joined to the capture's wall clock. `runtime.py` is another card's
file, so the export was **not** written; the schema is filed as handoff
**RT-TURNS-1** below.

Both rows now carry `MISSING_TURN_PRODUCER`, which says *"OWNER-GATED ON A TOOL
THAT DOES NOT EXIST YET"* in those words, names `speaker_label_rows`, and points
at the handoff. `SESSION.md` marks them ⚠ in the row table and adds a section
titled "Three rows will come back unmeasured, and that is the finding".

## 3 · `hosted_spend_usd` was a vacuous pass

The spend ledger is keyed by the provider's `rt_…` session; the tee names folders
`sess_…`. The old code matched one against the other, selected nothing, summed
`$0.00`, and passed a `≤ $2` gate for a session that may have cost real money.

**Fixed** with two joins that work — `--spend-session rt_…`, and the capture's
own wall window (`index.json`'s `started_at`/`closed_at` against each ledger
row's `wall`, ±120 s) — and, decisively, `matched: False` when zero rows are
selected, which the scorecard renders as **unmeasured**, never as zero.

Better still, the provider id is now **recovered automatically**: the evidence
log's `retained_event` rows carry `session_id: "rt_…"`, so `--events` closes the
join for free. `SESSION.md` step 10 explains why `--events` is not optional.

## 4 · The silent arm could not tell echo from speech

`owner_silence_check` collapsed all loud frames into one boolean, so the B3
failure this card exists to catch — a speaker off the array's DAC putting the
robot's own voice into the microphone — came back `unmeasured` instead of failing.

**Fixed** by putting both streams on one wall clock (owner segments' `started_at`
plus the real-time byte cursor; robot segments' `started_at`/`ended_at`) and
splitting loud frames into two populations:

| where the loud frames are | verdict | why |
|---|---|---|
| in **robot-silent gaps** | `unmeasured` | only a person makes that; interrupts cannot be attributed |
| during **robot playback** | **`fail`**, rate kept | the robot's own voice is arriving uncancelled — a finding, not an obstacle |

Measured on real product-tee sessions: `gap` → 27 loud in gaps / 13 during,
`owner_spoke=True`; `playback` → 0 in gaps / 10 during, `owner_spoke=False`,
`echo_in_owner_stream=True`.

Making a passing number report `fail` needed a new invariant rather than a
special case. `make_row` gained `override_reason`, and `verify_scorecard` now
enforces: **a row may always be called worse than its number says, with a stated
reason; it may never be called better.** An upward override has no spelling and
is refused.

## 5 · The ERLE report was trusted by deny-list

`erle_trustworthy = verdict != "unmeasured"` trusted `{}` and any mapping
without the word. **Fixed** to an allow-list: `schema` must equal
`parcel.air1.erle_report.v1`, `verdict` must be in
`{pass, pass_lower_bound, fail}`, and the attenuation must be numeric —
otherwise the row is unmeasured with the reason. The seeded test isolates the
schema check specifically (a v2 report that is otherwise perfect), because the
first attempt at that seed stayed green — the other checks happened to cover it,
which means the guard was not yet proven.

## 6 · The number is renamed, and the premise it rested on was false

**Renamed.** The three-leg figure is not textbook ERLE: it is everything the
chip does to an echo between microphone and USB endpoint — linear AEC, residual
suppressor, beamformer rejection and capture gain together. The field is now
`asr_beam_echo_attenuation_db`; **`erle_db` stays as an alias with the same
value**, because the card, the plan and §5.3 all say "ERLE ≥ 20 dB" and a reader
looking for that key should find it. Every report carries a `measures` string,
so the number cannot travel without its own definition.

**Gain state recorded.** `xvf3800_probe.alsa_gain_state()` reads
`amixer -c 2 scontents` (read-only) into every leg. On this host today: playback
`PCM,0` at 37/60 = **−23.00 dB**, capture `Headset,0` at 54/60 = **−6.00 dB**. A
change between two legs now forces the verdict to `unmeasured` — part of the
difference would be a mixer setting, not the room. Over the vendor interface,
`PP_AGCONOFF` and `PP_AGCGAIN` are both readable and are read by `--mux`.

**And the premise was refuted.** Before asserting "no raw mic tap exists" I
checked the XVF3800 host-control interface, as instructed. What I found:

* **Each USB capture channel is a mux.** `AUDIO_MGR_OP_L` (resource 35,
  command 15) and `AUDIO_MGR_OP_R` (35, 19), both `rw`, take a
  `(category, source)` pair. Categories include **1 = raw microphone**,
  **3 = amplified microphone as the canceller receives it**, **4/5 = far-end
  reference**, **7 = per-microphone AEC residual**, 6 = processed beam.
* So **(a) a raw mic channel and (b) the far-end reference are both AVAILABLE
  NOW**, two at a time, on the installed firmware. §5.3's same-instant method is
  available and **the second loudspeaker is unnecessary.**
* **The 6-channel firmware is NOT the route and must not be flashed.** It is a
  separate DFU image, not a USB alternate setting — this host's descriptors
  carry exactly one 2-channel altset. Flashing re-enumerates the device with a
  different channel count (breaking every ALSA/PipeWire/PortAudio assumption in
  the voice stack), resets parameters, and is recoverable only via a bundled
  `4mb_all_ff.bin`. This host is at firmware v2.0.6 (`bcdDevice 0206`), which
  predates even the `AUDIO_MGR_OP_CH3..CH6` additions. The mux makes it moot.
* Writes are **runtime-only** unless `SAVE_CONFIGURATION` is issued; a power
  cycle restores defaults.

**Acted on.** `XvfControl` implements the interface with the discipline the
finding demands:

* reads always allowed; **writes require `allow_writes=True` AND membership of a
  five-entry allow-list**; `SAVE_CONFIGURATION` is not in the command table at
  all, so no code path can persist anything;
* `mux_session()` reads the current routing, applies the pairing, restores in a
  `finally` **and reads the restore back** — a routing left changed would leave
  the owner's stack listening to a raw microphone with nothing in the audio path
  saying so, which is the worst outcome available here. A failed restore raises
  in capital letters and tells the owner to power-cycle.
* `measure_erle.py --method mux` pairs L = amplified mic 0 (into the canceller)
  against R = processed beam (out of it), plays through the array's own
  amplifier, and records both at once: one recording, one gain, nothing to
  level-match. It is now the **primary** path in `SESSION.md` step 5A; the
  three-leg method is 5B, for a host that cannot reach the control interface.
* `xvf3800_probe.py --mux` reports the routing and AGC read-only and says
  whether the same-instant measurement can run at all.

**This path has never touched hardware and I have not run it.** Every control
transfer on this host is `Errno 13` (`/dev/bus/usb/003/008` is `root:root 0664`;
the udev rule is an owner action) and `pyusb` is not installed. The encoding, the
allow-list and the restore discipline are tested against a fake device in
`tests/test_air1_mux.py`; **the wire behaviour is untested and the owner is its
first run.** `SESSION.md` 5A says so in those words.

## Notes, all acted on

* **`false_barge_in_rate` auto-filled its mechanism**, which made "a miss must
  name its mechanism" vacuous for that row. The mechanism is now set only on an
  actual miss, and `verify_scorecard` **refuses a mechanism on a passing row** —
  so the check cannot be satisfied by an unconditional builder.
* **The probe exited 0 with PortAudio absent** although the config note promises
  non-zero when a fact cannot be confirmed. It now exits 1 with
  `UNCONFIRMED  the rates section could not run: …`. Measured: exit 0 with
  PortAudio on the path, exit 1 without.
* **The docstring cited `~/.local/share/parcel/recordings`**, which the product
  does not use — `capture.dir` resolves against the repo root. Corrected to
  `recordings/`, with the resolution rule stated.
* **The MARK-1 handoff was half the story.** `interrupted_at` alone yields no
  latency, because the **onset** is stamped nowhere either:
  `input_audio_buffer.speech_started` is not in
  `protocol.RETAINED_EVENT_TYPES`, so it never reaches `events.jsonl`, and the
  lane's `_note` keeps barge-in messages in an in-memory list with no clock. Now
  filed as **two** handoffs, and the row's reason says both halves are missing.

## How the correction pass was verified

```
$ source scripts/env-audio.sh
$ env -u TMPDIR .parcel/bin/python -m pytest tests/test_air1_rate_pin.py \
      tests/test_air1_scorecard.py tests/test_air1_streams.py tests/test_air1_mux.py -q
71 passed, 1 warning in 14.21s

$ env -u TMPDIR .parcel/bin/python -m pytest <the same four> -q     # no PortAudio
70 passed, 1 skipped, 1 warning in 13.70s

$ .parcel/bin/ruff check <the three tools + the four test files>
All checks passed!
```

Ruff ratchet: **7 fingerprints, unchanged, and zero of them mine** (re-derived
from a whole-tree `ruff check . --output-format=json` at the end of the pass —
the five extras seen mid-pass belonged to MARK-1/CURIO-1/ROAM-1 and those cards
have since cleared them). `ci_gate.py` not run.

### Seeded RED, one per new guard

Each seed was applied to the product file, watched fail, restored from a
byte-identical copy (sha256 verified), `__pycache__` purged, re-run green.

| # | guard | seed | RED |
|---|---|---|---|
| E | explicit streams overlap | reverted to `play()` + `rec()` | 4 failed / 6 passed |
| F | the numerator must be an echo | `if uncancelled - floor < margin:` → `if False:` | 1 failed / 9 passed |
| G | mixer gain must not move between legs | the gain comparison disabled | 1 failed / 9 passed |
| H | zero matched ledger rows ≠ $0.00 | `"matched": True` | 1 failed / 34 passed |
| I | an override may only go downward | `downgrade = bool(override)` | 1 failed / 34 passed |
| J | the ERLE report allow-list | schema check → `if False:` | 1 failed / 35 passed **(after the test was re-cut to isolate it — the first attempt stayed green, so the guard was unproven and is now proven)** |
| K | echo during playback is a fail | `echo_in_stream = False` | 1 failed / 34 passed |
| L | the mux restore is verified | restore errors swallowed | 1 failed / 12 passed |
| M | control writes are opt-in | `allow_writes = True` | 1 failed / 12 passed |
| N | the probe's exit code | `unconfirmed` dropped from the return | exit 0 (was 1) |

Restore verified by sha256 at the moment of each restore: `measure_erle.py
34c940d2…86bf`, `bargein_through_air.py b7d64736…30bb`, `xvf3800_probe.py
2f1e547f…afc2`.

`measure_erle.py`'s hash then moved to `0e938e20…1299` on a later, deliberate
edit — the module docstring, rewritten to retract the refuted "there is no raw
mic to read" premise (§6). Recording that here because a hash quoted in a status
doc and a hash on disk that do not match is exactly the kind of small
discrepancy a verifier should not have to chase. The other two files are
byte-identical to their restores.

## What the correction pass still does not prove

* **Nothing acoustic. Still zero measured rows.** No attenuation figure, no
  false-barge-in rate, no latency, no TV arm.
* **The mux path is unexecuted.** It is the primary method in the runbook and it
  has never run against the device. If the vendor command ids are wrong, the
  owner finds out — the failure mode is a `ProbeError` on the first read, and
  the fallback is 5B.
* **The same-instant pairing measures the whole pipeline, not the AEC alone.**
  True per-microphone AEC residual (category 7) needs `AEC_ASROUTONOFF 0`, whose
  resource/command ids I did not confirm, so that control is deliberately absent
  from the table. Documented as an extension, not implemented on a guess.
* **The two turn rows are still unproducible** and one runtime change away.

## Handoffs (revised)

* **RT-TURNS-1 → whoever owns `runtime.py`.** Expose per-turn identity with a
  WALL stamp. Minimum viable schema, one JSONL row per ledger row, written
  beside the capture as `turns.jsonl`:
  `{"wall": "<ISO-8601 Z>", "session_id": "rt_…", "item_id": "…", "speaker":
  "owner"|"robot"|"system", "identity": {"verdict": "…", "cosine": <float>,
  "doa_deg": <int|null>, "enrolled": <bool>}}`. The data already exists in
  `_stamp_speaker_label`; what is needed is a wall clock instead of
  `time.monotonic()` and a sink other than a 400-row in-memory ring. That single
  change produces **two** of AIR-1's seven rows.
* **MARK-1-STAMP → MARK-1 (`audio_gateway.py`) — CLOSED, 2026-08-22.**
  MARK-1's own correction pass landed it: `mark_interrupted(wall)` now writes
  `interrupted_at` (the wall clock `_offer` read on the RELAY thread),
  `interrupted_byte` and `interrupted_t_s` onto the open robot segment, and
  FINISH-1 (`../task_29` §E) made `tools/bargein_through_air.py` read them —
  see the FINISH-1 section at the end of this file.
* **TURN-1-ONSET → TURN-1 (`protocol.py`).** Add
  `input_audio_buffer.speech_started` to `RETAINED_EVENT_TYPES` (keys
  `("audio_start_ms",)`) so the onset reaches `events.jsonl` with a wall stamp.
  **MARK-1-STAMP alone yields no latency** — the pair needs both ends, and this
  is the missing one.
* **→ MARK-1.** The ch0/ch1 downmix number is still `downmix_hazard()`, one call.
* **→ DUPLEX-1.** `signal_to_echo_db` from the double-talk leg is what the
  provisional-duck threshold should be set from, not the attenuation figure.
* **→ PO-1.** Unchanged and worth repeating: until the owner session runs there
  is **no** through-air evidence, and the tools landing is not progress on the
  acoustics question.
* **→ the owner.** The second loudspeaker is **no longer needed** if the udev
  rule lands — 5A replaces it. The speaker on the array's own JST-PH2.0 amp is
  still required, and is still the one purchase this card implies.

---

# The cross-card seam — FINISH-1 (`../task_29` §E), 2026-08-22 · Claude Opus

The card's §E is one item; the rest of AIR-1's correction pass is the
verifier's to re-check, and nothing else in this file was touched.

## What was wrong

`tools/bargein_through_air.py` did not read `interrupted_at`, did not know the
field existed, and **said so in three places that were no longer true**: the
module docstring's "THE ONE METRIC THE TEE CANNOT GIVE" section
(*"`mark_interrupted` throws it away"*), `score_interrupt_latency`'s docstring,
and the `interrupt_p50_s` row's `unmeasured_reason` — which
`tests/test_air1_scorecard.py` **pinned**, so the false sentence was a test
fixture. MARK-1's correction pass had landed the stamp hours earlier.

## What it reads now

* **`capture_latency_events(index)`** — new. Out of one R17 index it takes two
  kinds of wall-stamped event: `capture.interrupted`, one per robot segment
  carrying `interrupted_at` (with `interrupted_byte` / `interrupted_t_s`
  travelling as the POSITION in the reply — `robot.wav` is written faster than
  real time, so they are never used as a clock), and `capture.owner_burst`, one
  per owner segment **after the first**, i.e. the first microphone frame
  following `owner_gap_s` (0.75 s) of silence.
* **`score_interrupt_latency(rows, capture_events=…)`** — merges the two
  sources on one timeline and **de-duplicates**: a `conversation.item.truncated`
  landing within 2.0 s after the tee's own stamp is the same interrupt seen by a
  second witness, and the tee's stamp — earlier and closer to the instant — is
  the one that survives. It returns `kinds`, `interrupts_stamped_by_the_tee`,
  `onsets_estimated_from_owner_bursts`, `onset_is_an_estimate` and
  `positions_into_reply_s` beside the median.
* The CLI passes `--capture`'s index in automatically, so **a session with no
  `--events` file can now produce this row**.

## The honest half, and it is half

**The interrupt instant is stamped; the onset instant is estimated.**
`input_audio_buffer.speech_started` is still not in
`protocol.RETAINED_EVENT_TYPES` (checked on this tree), so the provider's own
view of "the owner started talking" reaches no file. The owner-burst boundary
is the gateway's view of a burst starting: **later** than the acoustic onset by
the browser's encode-and-send latency, **earlier** than the provider's VAD
decision. A median built on it is a **bound**, not a measurement, and the
scorecard says so — in `sources.latency.onset_is_an_estimate`, and in a NOTE
the CLI prints under the table.

It is deliberately **not** in the row's `mechanism` field: `verify_scorecard`
refuses a mechanism on a row that is not a `fail` (a mechanism is an
explanation of a miss), so putting the caveat there would have made every card
carrying this row invalid. That is the check doing its job.

**TURN-1-ONSET stands, and is now the only missing half.** One line in
`protocol.RETAINED_EVENT_TYPES` (`input_audio_buffer.speech_started`, keys
`("audio_start_ms",)`) turns the bound into a measurement.

## Seeded RED

| direction | seed | result |
|---|---|---|
| present ⇒ a number | `capture_latency_events` stops reading `interrupted_at` (`when = None`) | **1 failed** — `test_the_tee_alone_yields_an_interrupt_median`; 39 passed |
| absent ⇒ `unmeasured` | the index's `interrupted_at`/`_byte`/`_t_s` stripped from every robot segment | `p50_s is None`, `interrupts 0`, the row is `unmeasured`, `verify_scorecard == []` — asserted by `test_a_capture_without_the_stamp_is_unmeasured_not_zero` |

`tools/bargein_through_air.py` sha256 `cd8edb3ecabcb539…` identical before and
after, `__pycache__` purged, **40 passed** restored.
(`../task_29/evidence/seed_e1.sh`.)

The four new tests build a **real** R17 session through the product tee
(`SessionAudioCapture` with its own wall clock, so the owner stream really does
go quiet between bursts), and `verify_capture_index` is asserted clean on it
before anything is scored. `test_latency_names_both_missing_halves_not_one` is
replaced by `test_latency_names_the_one_missing_half_and_no_longer_the_closed_one`,
which asserts the reason no longer says `drops the wall stamp`.

```
$ unset TMPDIR; .parcel/bin/python -m pytest -q tests/test_air1_scorecard.py  -> 40 passed
$ .parcel/bin/ruff check tools/bargein_through_air.py tests/test_air1_scorecard.py
                                                                              -> All checks passed!
```

**No audio was played and no control byte was written to the XVF3800 by this
pass**, and no acoustic number is claimed: the seam is a file-format change on
disk, measured against a capture this test wrote itself.
