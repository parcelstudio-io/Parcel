# MARK-1 — an interruption tells the truth about what was heard

**Card:** `README.md` (task_22) · **Executor:** Claude Opus · **Verifier:** Fable
**Board:** `../TASK_BOARD.md` · **Pre-registration:** `MARK1_PREREGISTRATION.md`
(written before the harness existed) · **HEAD at start:** `8862220`
**Hosted spend: `$0.00`.** No live turn was needed for any row.

## Headline

**All four pre-registered rows met, on a harness that reproduces the recorded
failure before it fixes it.** The registered debt — R7's live
`[interrupted after 0 ms]` — now reproduces on demand (**24/24 barge-ins truncate
at 0 ms** on the historical client with the pre-MARK-1 played clock, while the
owner had heard up to **2 970 ms**), and with MARK-1's client the same 24
barge-ins truncate at **|truncate − heard| p50 0.0 ms / p95 1.0 ms / max 1.0 ms**
and **0/24 at zero**. The panel that shipped — one ack per arriving chunk — is
measured too and misses the bound by an order of magnitude (**p95 1 200 ms, max
1 440 ms**): its playback origin is re-stamped on every underrun, so mid-reply it
reports ~0.

Three things changed shape rather than gaining a number:

* **The ear is now a stated choice.** `hello()` carries a `capture` block naming
  the channel count and the beam; the browser applies it and reports back which
  ear it actually opened; the gateway records it always and refuses a downmix
  **only when a beam is pinned**. Host fact measured here: `hw:2,0` (the
  XVF3800) is `S16_LE / 16 000 Hz / CHANNELS: 2`, so there really are two beams
  to pick between. **The pin ships OFF** — see deviation D-2.
* **The backchannel floor exists and ships at 0** (R16's behaviour to the frame).
  Its measurement produced the finding that matters: survival is not a property
  of the floor alone. The lane cannot know the owner stopped until the
  endpointer says so, and server VAD only says so after its silence tail — so a
  floor buys survival exactly while `floor >= burst + tail`. At the provider's
  **default ~500 ms tail a 350 or 450 ms floor buys nothing**; 700 ms is the
  first floor that survives a 150 ms "mm-hmm". **TURN-1's `silence_duration_ms`
  is a prerequisite for this feature, not a neighbouring nicety.**
* **`played_ms` stopped answering the wrong question.** Returning 0 when the
  sink has proven nothing was the honest answer to "has playback been proven"
  and the wrong answer to "what did the owner hear". It now falls back to the
  first-enqueue anchor, bounded by what was enqueued, and counts every reply it
  had to.

## What changed

`git diff --stat` on OWNS. `lane.py` is shared with **TURN-1**, which landed
`_on_speech_stopped` in the same tree while this card was executing; the split
below is by hunk, and every MARK-1 hunk carries a `MARK-1` marker comment.

| File | MARK-1 | also in the file (not mine) |
|---|---|---|
| `src/parcel_robot/realtime/lane.py` | **+281 / −1** | TURN-1: +141 / −0 |
| `src/parcel_robot/realtime/audio_gateway.py` | **+208 / −8** | — |
| `src/parcel_robot/ui/index.html` | **+103 / −11** | — |
| `tests/test_realtime_audio_gateway.py` | **+20 / −5** | (1 line: TURN-1 context) |
| `tests/test_mark1_barge_in_mark.py` | **new, 762 lines** | — |
| `tests/test_mark1_browser_ear.py` | **new, 316 lines** | — |
| `scrum/20260822/task_22/*.md` | new | — |

Attribution command (hunk-level, re-runnable):

```
$ .parcel/bin/python  # see the script in §"how verified", step 0
src/parcel_robot/realtime/lane.py
    MARK-1 hunks: +281 / -1   |   other cards' hunks in the same file: +141 / -0
src/parcel_robot/realtime/audio_gateway.py   MARK-1: +208 / -8
src/parcel_robot/ui/index.html               MARK-1: +103 / -11
```

### `realtime/lane.py` (regions: `_on_speech_started` / `played_ms`, + D-1)

* `_ResponseState.first_enqueue_at` and one line in `_emit_audio` that stamps it.
* `played_ms()` — falls back to that anchor when the sink reports no playback
  mark, **in `audio` mode only** (`text` mode's `DiscardSink` really does drop
  every byte and 0 is the true answer there), counted as
  `played_anchor_fallbacks`, gated by `assume_playback_without_ack=True`.
* `_on_speech_started()` — with `backchannel_floor_ms == 0` (shipped) it calls
  `_commit_barge_in()` immediately, which is R16 unchanged. Above 0 it opens a
  `_BargeInHold`: nothing is sent to the provider, nothing is taken from the
  sink, the reply keeps playing.
* `_resolve_barge_in_hold()` / `_settle_barge_in_hold()` / `_commit_barge_in()`
  / `_speech_ended_after()` / `note_owner_speech_stopped()`.
* `DEFAULT_BACKCHANNEL_FLOOR_MS = 0.0`, six counters, and six new
  `snapshot()` keys including `truncations` — the record the debt was about is
  now visible from `/api/state` instead of only from a wire trace.

### `realtime/audio_gateway.py`

* `ack_played` gains a fourth clamp: **within one utterance the position may
  only go up** (`regressive_acks`). The floor is per utterance, reset by
  `begin_utterance` and `interrupt`.
* `_record_final_ack` — the single post-interrupt ack a client is invited to
  send. Recorded (`final_acks`, `last_final_played_ms`, clamped to what was
  transmitted), **anchors nothing**; a second one is a stale ack exactly as before.
* `hello()` gains `capture: {channels, beam}`. `input` still describes the PCM
  the browser must SEND; they are different questions and were being answered by
  one number.
* `set_mic(..., channels=, beam=)` + `_check_capture_pin` + `_ear_text`. Refusal
  happens **before** `on_mic`, so a mic that will be refused never opens a paid
  session first.

### `ui/index.html` (regions: played-ack timer, capture channelCount)

* `PLAYED_ACK_INTERVAL_MS = 100` and a `setInterval` that reports while
  `playAt > currentTime`; cleared in `stopMic`.
* `playedMs(mic)` = `scheduledMs − max(0, (playAt − currentTime) * 1000)`, and
  `mic.scheduledMs` accumulated in `playChunk`. The formula it replaces
  (`currentTime − playStart`) is **gone**, and its absence is asserted.
* `stopPlayback` sends one final position **before** stopping the sources.
* `armEar(mic, pin)` — applies the pinned channel count with
  `echoCancellation/noiseSuppression/autoGainControl: false` (the array does all
  three on-chip; Chrome's AEC3 downmixes to mono to do its job), then sends
  `{"type":"mic","on":true,"channels":N,"beam":I}`. `createScriptProcessor` is
  opened with `mic.captureChannels` and the frame is `getChannelData(ear)`.

## How verified

Environment: `.parcel/bin/python` (3.14.4), `.parcel/bin/ruff` 0.16.1.
**`TMPDIR` unset on every pytest invocation** (`env -u TMPDIR …`), per the board.
No `scripts/ci_gate.py`, no full suite, no process started that outlived a command.

### 0. Diff attribution

```
$ .parcel/bin/python - <<'PY'   # classifies each `git diff -U0` hunk by marker
… (regex over MARK-1 / _BargeInHold / backchannel / first_enqueue_at / capture_pin / …)
PY
src/parcel_robot/realtime/lane.py  MARK-1 hunks: +281 / -1 | other: +141 / -0
```
Every "other" hunk in `lane.py` was read and is TURN-1's (`_on_speech_stopped`,
`LifecycleEvent`, `turn_timings`, `turn_detection` on the wire). `audio_gateway.py`,
`index.html` and both `test_mark1_*` files are 100 % MARK-1.

### 1. The harness (the R7 rig, extended — not forked)

`FakeRealtimeServer` → `RealtimeLane` → `BrowserSink` → `BrowserAudioGateway` →
`_HeadlessBrowser`. The last is the piece R7 had in `<scratchpad>/live/proof_client.py`
and never committed; it is now `tests/test_mark1_barge_in_mark.py`, a port of
`index.html`'s playback path over a virtual `AudioContext` on the same fake clock,
driven at the driver's real 20 Hz.

**The referee is not the code under test.** "What the owner heard" is the
`_AudioContext`'s sum of each scheduled buffer's overlap with `(-inf, now]` —
what came out of the speaker. The number the browser reports and the number the
lane truncates at are both measured against it and neither computes it.

**Fixtures:** 4 arrival patterns (`burst` = R7's live shape, 13 chunks inside
0.6 s; `realtime`; `underrun`, a stall that runs the schedule dry; `jitter`) ×
6 barge-in instants each = **N = 24**, two of them inside a silent gap.

**Three clients, one harness:** `none` (R7's live client, no acks at all),
`arrival` (`index.html` as R7 shipped it), `continuous` (MARK-1).

### 2. Pre-registered rows

```
$ env -u TMPDIR .parcel/bin/python -m pytest tests/test_mark1_barge_in_mark.py \
      tests/test_mark1_browser_ear.py -q
27 passed, 1 warning in 2.02s
```

| Row | Pre-registered | Measured | Verdict |
|---|---|---|---|
| **R1** `audio_end_ms` never 0 after ≥1 chunk | 24/24 non-zero **and** 24/24 ≤ enqueued | `zero_truncations=0`, no row overstates | **MET** |
| **R2** \|truncate − heard\| p95 | ≤ 150 ms | **p50 0.0 · p95 1.0 · max 1.0 · mean 0.4 ms** | **MET** |
| **R3a** hello names the ear | present | `{"channels": 1, "beam": null}` unpinned; `{"channels": 2, "beam": 1}` pinned | **MET** |
| **R3b** downmixed ear refused under a pin | refused, counted, mic never opens, `on_mic` never called | `capture_pin_refusals=1`, `mic_opens=0`, `arms == []` | **MET** |
| **R3c** pinned beam arms | opens | opens, `capture_beam_reported=1` | **MET** |
| **R3d** unpinned = today | opens, nothing counted | opens, `capture_pin_refusals=0` | **MET** |
| **R4a** floor 0 ≡ today | identical frames | `sent_types()` and `truncations` identical to omitting the kwarg; tail is exactly `response.cancel, conversation.item.truncate`; `backchannel_holds == 0` | **MET** |
| **R4b** sub-floor burst survives | no cancel, no truncate, sink untouched | `[]` barge frames, `sink.interrupts == 0`, playback continued > 900 ms further | **MET** |
| **R4c** supra-floor commits once, at commit-time position | 1 cancel + 1 truncate, mark ≥ speech-start + floor | met; `error_ms ≤ 150 ms` still holds on the held mark | **MET** |
| **R4d** survival **reported** | reported (no bar; DUPLEX-1 sets ≥ 0.9) | see the matrix below — **9/24 (0.38)** over the matrix | **MET (reported)** |

Printed measurements, verbatim (`pytest -s`):

```
[MARK-1 continuous acks] n=24 zero_truncations=0 p50=0.0ms p95=1.0ms max=1.0ms mean=0.4ms
[MARK-1 R2] p50=0.0ms p95=1.0ms max=1.0ms
[R7 live client, pre-MARK-1 played clock] 24/24 truncated at 0 ms while the owner had heard up to 2970 ms
[silent client + first-enqueue fallback] zero_truncations=0 p50=0.0ms p95=500.0ms max=820.0ms
[R7 shipped: ack per arriving chunk] n=24 zero_truncations=0 p50=0.0ms p95=1200.0ms max=1440.0ms mean=201.8ms

[MARK-1 R4d] backchannel survival — floor_ms × (burst, VAD tail)
    burst= 150 ms tail= 200 ms       0: .      250: .      350:yes     450:yes     700:yes    1000:yes
    burst= 150 ms tail= 500 ms       0: .      250: .      350: .      450: .      700:yes    1000:yes
    burst= 300 ms tail= 200 ms       0: .      250: .      350: .      450: .      700:yes    1000:yes
    burst= 300 ms tail= 500 ms       0: .      250: .      350: .      450: .      700: .     1000:yes
    survival over the whole matrix: 9/24 (0.38) — DUPLEX-1 sets the >= 0.9 bar
```

Two numbers in that block are findings rather than rows:

* **the silent client is now 500 ms p95 wrong instead of 1 200–2 970 ms wrong.**
  The residual is exactly the stall: with no ack the anchor runs on wall clock
  while playback does not. Strictly better than claiming zero, and bounded by
  `enqueued_ms`.
* **the gateway's monotonic guard helps the shipped client and does not repair
  it** (mean 330 → 202 ms, p95 1 441 → 1 200 ms, measured by running the
  `arrival` sweep before and after adding the guard). The client fix is
  load-bearing; the server guard is a backstop for a stale cached page.

### 3. Seeded RED — one per new guard

Driver: `/home/jaewoo-jang/.cache/parcel-mark1/seed.py` (seed → run → restore →
sha256 compare → purge `__pycache__` → rerun).

| Seed | What was removed | RED | Restored byte-identically |
|---|---|---|---|
| **S6** acks stop when chunks stop | the `setInterval` block in `index.html` | `…reports_what_was_heard_on_a_timer_not_only_on_arrival` | ✅ `26ff8f137862` |
| **S1** the arrival-only formula returns | `playedMs` → `currentTime − playStart` | 2 tests incl. the port-fidelity link | ✅ `26ff8f137862` |
| **S2** the played clock may walk backwards | the `clamped < self._played_ack_ms` guard | `…walks_the_played_clock_backwards_is_dropped_and_counted` | ✅ `36fedc3640f1` |
| **S3** the downmixed ear is accepted | the `_check_capture_pin` refusal in `set_mic` | 3 tests incl. `…downmixed_ear_is_refused_when_a_beam_is_pinned` | ✅ `36fedc3640f1` |
| **S4** truncate at 0 after chunks played | the `_fallback_play_anchor()` call in `played_ms` | `…client_that_never_acks_is_no_longer_told_the_owner_heard_nothing` | ✅ `6582533c844f` |
| **S5** the floor is a hope, not a deadline | `_settle_barge_in_hold()` in `pump()` | 4 tests incl. R4b/R4c/R4d | ✅ `6582533c844f` |

The card's three named seeds are S6/S1 ("acks stop on interrupt"), S4 ("truncate
sent with 0 after chunks played") and S3 ("the downmixed ear accepted"). S2 and
S5 are the two guards this card added that the card did not name.

Two of these are **standing** witnesses rather than one-shot seeds:
`test_the_r7_live_client_that_never_acked_is_why_the_provider_heard_zero`
reproduces the recorded live failure (24/24 at 0 ms) on every run with
`assume_playback_without_ack=False`, and
`test_the_shipped_arrival_only_ack_collapses_the_moment_the_stream_stalls`
keeps measuring the client this card replaces.

### 4. Regression surface

Every test file that reads the gateway, the lane snapshot, the panel source or
`index.html` (found by `grep -rln`), run together:

```
$ env -u TMPDIR .parcel/bin/python -m pytest tests/test_mark1_barge_in_mark.py \
    tests/test_mark1_browser_ear.py tests/test_realtime_lane.py \
    tests/test_realtime_audio_gateway.py tests/test_realtime_audio_capture.py \
    tests/test_realtime_driver.py tests/test_realtime_idle_hangup.py \
    tests/test_realtime_pump_survival.py tests/test_realtime_spend_budget.py \
    tests/test_realtime_tool_broker.py tests/test_realtime_voice_identity.py \
    tests/test_realtime_reconnect.py tests/test_realtime_answer_beat.py \
    tests/test_realtime_system_initiated_motion.py tests/test_realtime_corpus_replay.py \
    tests/test_realtime_prompting.py tests/test_p2a_memory_probes.py \
    tests/test_p0b_companion_unlocks.py tests/test_prod_default_path.py \
    tests/test_safety_log.py -q
967 passed, 2 xfailed, 1 warning in 24.52s
```

R7's own barge-in test (`test_barge_in_interrupts_cancels_and_truncates_at_played_milliseconds`,
`audio_end_ms == 100`) passes **unchanged** — the shipped default is R16 to the frame.

### 5. Ruff — the ratchet is still exactly 7

```
$ .parcel/bin/ruff check src/parcel_robot/realtime/lane.py \
    src/parcel_robot/realtime/audio_gateway.py tests/test_mark1_barge_in_mark.py \
    tests/test_mark1_browser_ear.py tests/test_realtime_audio_gateway.py
All checks passed!

$ (whole-tree fingerprints vs scripts/ci_ruff_baseline.json)
beyond baseline: ['tests/test_roam1_behavior.py::RUF100']
mine beyond baseline: NONE
```
The one new fingerprint is **ROAM-1's file (task_23), in flight in the same tree.
Not touched, not reported as mine, not fixed by me.**

### 6. Host fact measured (read-only, no device claimed)

```
$ arecord -l
card 2: Array [reSpeaker XVF3800 4-Mic Array], device 0: USB Audio [USB Audio]
$ arecord -D hw:2,0 --dump-hw-params -d 1 /dev/null
FORMAT: S16_LE   CHANNELS: 2   RATE: 16000
```
Two capture channels really exist, which is what makes the beam pin a real
choice rather than a theory. **No claim is made that ch1 is the ASR beam on this
firmware** — that is AIR-1's commissioning measurement.

## What this does not prove

1. **No browser has ever run this JavaScript.** There is no browser, no DOM and
   no `node` on this host (`which node` → nothing). `index.html` is pinned by
   source assertion and by a Python port whose two load-bearing expressions are
   asserted against the JS lines character-for-character
   (`test_the_python_port_of_the_panel_uses_the_same_two_numbers`). The only
   syntax check performed was a regex-aware brace/paren balance over the
   `<script>` block, before and after (both balanced). **A real browser session
   is owner-gated and is listed below.** This is the same caveat R7 carried, no
   weaker and no stronger.
2. **No hosted turn was made.** Every number is against `FakeRealtimeServer`.
   The provider's real behaviour on `conversation.item.truncate` — whether an
   honest `audio_end_ms` actually stops the repeats — is unmeasured. That is the
   whole point of the card and it needs one live session.
3. **`getUserMedia` may simply refuse two channels.** `applyConstraints` is
   best-effort by specification and Chrome has historically forced mono whenever
   `echoCancellation` is on. The code turns AEC off when a beam is pinned for
   exactly that reason, but whether Chrome then hands over two channels **on
   this machine, with this array, through PipeWire** is unknown and untestable
   here. If it does not, `armEar` reports 1 channel and a pinned gateway refuses
   — loudly, with a reason, which is the intended failure.
4. **Backchannel survival is measured against a SIMULATED endpointer.** The
   burst/tail pairs in R4d are constructed, not recorded. What is proven is the
   wiring and the arithmetic; what the owner's real "mm-hmm" looks like through
   the array is TURN-1's recording and DUPLEX-1's session.
5. **The 150 ms bound is only as good as the fixture set.** Four arrival
   patterns is not a distribution over real networks; the p95 of 1.0 ms is the
   p95 of *these* twenty-four, and the two rows that could have been ugly (the
   in-gap barge-ins) are saved by the `enqueued_ms` clamp rather than by the
   ack. A network where the socket is seconds behind the browser's buffer is not
   modelled.
6. **A survived backchannel still arms an owed voice turn.** `_arm_voice_turn`
   fires from the `speech_stopped` branch (R8's region, not MARK-1's), so a
   surviving "mm-hmm" leaves `voice_turns_owed` incremented and the watchdog
   armed for an answer the provider may never send. **No live impact today**
   because the floor ships at 0, but it is a real defect for whoever turns the
   floor on — see handoff H-4.

## Deviations from OWNS / the card (declared)

**D-1 — one call site in `lane.pump()`, outside the named region.** The card
scopes `lane.py` to "`_on_speech_started` / `played_ms` region only". The
backchannel floor is a **deadline**, and a deadline needs a tick that fires
whether or not the provider sends a frame; without one, a held barge-in that
nobody resolves simply never happens, which would silently regress the
live-proven 210 ms barge-in. `pump()` is owned by no card (TURN-1 owns the
`speech_stopped` region; P0-B owns `submit_realtime_transcript`; P2-A owns the
replay region), the change is 5 lines with a `CARD MARK-1` marker, and it is a
no-op unless a hold is open — which is impossible at the shipped default. Also
one line in `_emit_audio` (the playback bridge, adjacent to `played_ms`) that
stamps `first_enqueue_at`.

**D-2 — the capture pin ships OFF (`capture_beam=None`).** The card says "a
downmixed ear is refused, not silently accepted". The mechanism is built and
seeded RED; the **default** does not refuse. Reasons: (a) board rule 1 —
prototype, not production; do not add fail-closed defaults. A pinned default
would take the owner's microphone away on the first click, with no
hardware/commissioning fix available in this card. (b) It is not knowable from
here whether Chrome will hand over 2 channels through PipeWire; arming a refusal
against an untestable condition is how a companion stops being able to hear.
(c) AIR-1 (task_25) is the card that commissions the array with the owner
present, and it is the right place to turn the pin on. Handoff H-1 carries the
exact two-line change. **This is a declared miss against the card's wording, not
a claim that it was met.**

**D-3 — `getUserMedia({channelCount: 2})` became `applyConstraints` after hello.**
The card asks for the constraint at capture time. It cannot be: `startMic` calls
`getUserMedia` **before** the socket opens, so the gateway's pin is not known
yet. Moving `getUserMedia` after the handshake would restructure the arming
sequence of a file no test on this host can execute. Instead the initial request
is byte-identical to today's (`channelCount: 1`, AEC on) and the pin is applied
by `track.applyConstraints` in `armEar` **only when a beam is pinned**, so the
unpinned path is unchanged. Better, and different from what the card wrote.

**D-4 — the backchannel floor ships at 0.** The card describes ducking; with the
region constraints available (`index.html` limited to the played-ack + capture
regions), a real gain duck is not implementable here — the browser has seconds
of audio already scheduled in Web Audio and only a browser-side gain change can
attenuate it. What ships is "hold the cancel, keep playing", which for a genuine
interruption costs the owner `floor` ms of the dog still talking. Defaulting
that on would regress the live-proven 210 ms barge-in to ~560–910 ms for every
real interruption, which is a *felt* regression traded for a benefit this card
cannot measure on a live voice. Both arms are measured (R4a and R4b–d) and the
default is DUPLEX-1's to set. Card text supports this: "first slice, DUPLEX-1
owns the rest".

**D-5 — two R7 source assertions in `tests/test_realtime_audio_gateway.py` were
updated.** That file is "the R7 rig" (in OWNS as "the R7 rig extension") and no
concurrent card owns it. `test_the_browser_arms_the_microphone_only_after_the_gateway_says_hello`
and `test_the_browser_resamples_to_the_rate_the_gateway_named` pinned the exact
JS lines this card changed. **Both keep their original point** — the arming frame
is still sent from the hello branch and nowhere else (now asserted as
`source.count('type: "mic", on: true') == 1`), and the resample is untouched.

**D-6 — HALTED on one item: the `speech_stopped` wiring.** MARK-1's floor needs
to know when the owner stopped. The obvious edit is one line in the
`SpeechStopped` dispatch branch — **which is TURN-1's marked region**, so I did
not make it. Instead `_speech_ended_after()` **reads** the `turn_timings` rows
TURN-1 writes (read-only, defensive, degrades to "the floor expired" if those
rows ever change shape) and `note_owner_speech_stopped()` is exposed as the seam
DUPLEX-1's local endpointer will use. The coupling is a real, declared
dependency on another card's in-flight data structure — see handoff H-3.

**D-7 — `browser_sink.py` now carries one stale sentence** and is not in OWNS,
so it was not edited. See H-2 for the exact replacement text.

## Owner-gated rows (listed with commands, never claimed)

**OG-1 — one live through-air barge-in, in AIR-1's session (task_25).** This is
the only row that can prove the mark is honest end to end: a real browser
executing this JavaScript, a real hosted reply, the owner talking over it.

```bash
# 1. credentials, never printed
set -a; . ~/.config/parcel/realtime.env; set +a

# 2. the stack on a socket and port that cannot collide with the live one on :8765
scripts/launch_stack.sh --prototype --socket /tmp/parcel_mark1.sock --port 8791

# 3. open http://127.0.0.1:8791, click "Enable microphone", ask a question long
#    enough to get a multi-sentence reply, and talk over it after ~2 seconds.

# 4. read the mark the provider was actually given
curl -s http://127.0.0.1:8791/api/state \
  | .parcel/bin/python -m json.tool \
  | grep -A 40 '"realtime"' \
  | grep -E 'truncations|audio_end_ms|enqueued_ms|played_acks|regressive_acks|final_acks|last_final_played_ms|played_anchor_fallbacks|capture_channels_reported|capture_beam_reported'
```

**Pass condition, pre-registered here:** `audio_end_ms > 0`, within 150 ms of
`last_final_played_ms` (the browser's own last word), `played_anchor_fallbacks == 0`
(a real browser acked), and `regressive_acks == 0`.
`capture_channels_reported` answers D-2/D-3's open question in one line: **if it
reads 2, AIR-1 can turn the pin on; if it reads 1, Chrome would not widen the
track and the beam has to come from a PipeWire loopback source instead.**

**OG-2 — the same reading with the array's speaker in the loop** belongs to
AIR-1's ERLE/false-barge-in arm and is that card's row, not this one's.

## Handoffs

* **H-1 → AIR-1 (task_25).** Turning the pin on is two constructor arguments
  where the runtime builds the gateway (`runtime.py`, not MARK-1's OWNS):
  `BrowserAudioGateway(..., capture_channels=2, capture_beam=1)`. Do it only
  after OG-1 shows `capture_channels_reported == 2`, and only after confirming
  on the firmware which of ch0/ch1 is the ASR beam. Everything server-side is
  built, counted (`capture_pin_refusals`) and seeded RED (S3).
* **H-2 → whoever owns `realtime/browser_sink.py`.** Its
  `first_chunk_started_monotonic` docstring still says "…so ``played_ms`` is zero
  and a barge-in truncates at zero rather than at 'however much we sent'." The
  property's own behaviour is unchanged and that half is still true; the
  consequence is not — the lane now falls back to the first-enqueue anchor.
  Suggested replacement for the second sentence: *"``None`` until the browser
  acks its first mark. The LANE no longer reads that as 'nothing was heard' —
  card MARK-1 anchors ``played_ms`` on the first enqueue instead and counts it —
  but this property still reports only what the browser has proven."*
* **H-3 → TURN-1 (task_21).** `lane._speech_ended_after()` reads your
  `turn_timings` rows (`speech_stopped_at`) to classify a backchannel, because
  the one-line alternative was an edit inside your marked region. If you rename
  or reshape those rows, MARK-1's floor degrades to a plain timeout — safe, but
  the feature stops working. If you would rather own the seam, call
  `lane.note_owner_speech_stopped()` from `_on_speech_stopped` and the read goes
  away. **Also: R4d shows your `silence_duration_ms` is a prerequisite for
  backchannel survival at any sane floor.** At the provider's default ~500 ms
  tail, nothing under 700 ms survives.
* **H-4 → DUPLEX-1 (task_26).** Three things are yours now: (a) choose
  `backchannel_floor_ms` from a live session — the knob is on the lane
  constructor, the counters are `backchannel_holds` / `backchannels_survived` /
  `barge_ins_committed`, and survival over the R4d matrix is **0.38**, well under
  your ≥ 0.9 bar, because a time-only floor cannot beat the VAD tail; (b) a real
  **duck** needs a browser-side gain change (a `duck` control frame plus a
  `GainNode` in `index.html`) which was outside MARK-1's index.html region; (c)
  a survived backchannel still arms an owed voice turn (does_not_prove 6) — the
  fix belongs with the turn controller.
* **H-5 → the verifier.** The harness prints its whole table under
  `pytest -s`; `_report()` in `tests/test_mark1_barge_in_mark.py` is the one
  function to read if you want to re-derive any number in this document.
* **H-6 → nobody yet.** `tests/test_eval_assertions.py::test_the_gate_is_wired_into_both_tiers_with_the_right_k`
  is RED in this working tree against **GATE-0's** in-flight `scripts/ci_gate.py`
  (the assertion looks for `results.append(evaluate_assertion_evals(tier=tier, k=1))`).
  Nothing to do with MARK-1; recorded because I ran it and saw it.

## What the verifier should look at first

1. **`_AudioContext.rendered_ms()`** in `tests/test_mark1_barge_in_mark.py`. If
   the referee is wrong, every number here is wrong. It is deliberately a
   different representation from the position formula under test — confirm that.
2. **The `arrival` sweep still fails** (`p95 1 200 ms`). If a change ever makes
   the client MARK-1 replaces look fine, the fixtures stopped exercising the
   defect.
3. **D-2** — the pin ships off. That is the one place this card is narrower than
   its README.
4. **D-1 and D-6** — the `pump()` call site and the read of TURN-1's
   `turn_timings`, the two places MARK-1 reaches outside its named region.

---

# Correction pass — 2026-08-22, after Fable's 12-agent verification

**Verdict incoming:** the server half was ACCEPTED (R1/R2 reproduced through the
product lane with no monkeypatch, the replaced clients still fail on the same
rig, the referee independent of the product clock, OWNS clean, ruff 7/7). Six
findings were confirmed; **all six are fixed, each with its own seeded RED.**

The headline correction is uncomfortable and worth stating plainly: **the
browser half of this card shipped a defect that would have hurt AIR-1's owner
session, and I had claimed it was unverifiable when it was not.** There is an
ECMAScript engine on this host — `/usr/bin/gjs`, SpiderMonkey 1.88.0 — and
`which node` returning nothing was taken as "no JS engine" without checking for
another. Every browser-half claim in the sections above rested on pattern
matching that a real engine could have decided.

| # | Finding | Status |
|---|---|---|
| 1 | **BLOCKER** — `armEar` treated the shipped unpinned hello as a pin, turning Chrome's AEC off on the owner's mic | fixed, seeded (`C1`) |
| 2 | major — a provider-side cancel during a hold was counted as a survived backchannel | fixed, seeded (`C2`) |
| 3 | minor — the ack timer goes quiet exactly when the schedule drains | fixed, seeded (`C3a`, `C3b`) |
| 4 | minor — a hold survived a reconnect/hang-up and was later miscounted | fixed, seeded (`C4`, `C4b`) |
| 5 | minor — AIR-1's handoff: an interrupted segment did not say WHEN | fixed, seeded (`C5`) |
| 6 | note — prereg seed S1/S2 substitution; the final-ack slot race | declared **D-8**; race was real, fixed, seeded (`C6`) |

## 1. BLOCKER — the unpinned hello was read as a pin (browser half)

**Reproduced first, in the engine, against the product's own JSON.** The runtime
builds the gateway with neither `capture_channels` nor `capture_beam`
(`runtime.py:7636`), so every owner session receives
`capture: {"channels": 1, "beam": null}`:

```
$ gjs wants_repro.js
Number(null)          = 0
isFinite(Number(null))= true
shipped -> wants      = {"channels":1,"beam":null}     ← "no pin" read as a pin
pinned  -> wants      = {"channels":2,"beam":1}
```

ECMA-262 `ToNumber(null)` is `+0`, and `+0` is finite. So the default path ran
`applyConstraints({channelCount: 1, echoCancellation: false, noiseSuppression:
false, autoGainControl: false})` on the owner's microphone on the first click.
With no array AEC reference routed yet (that is AIR-1's card), **Chrome's AEC3 is
the only echo canceller in the loop**, and removing it is the robot barging in on
its own voice for a whole session — the precise failure MARK-1 exists to remove,
delivered by MARK-1.

**Fix:** `pin && pin.beam !== null && Number.isInteger(pin.beam)`.
`Number.isInteger(null)` is `false`; `Number.isInteger(0)` is `true`, so a
legitimate pin on beam 0 is still a pin. The code comment that said the opposite
of what the code did is rewritten and now names the coercion, the shipped hello
and the AEC consequence.

**Test:** `test_the_unpinned_hello_leaves_the_microphone_alone` **extracts** the
`const wants = …` line from `index.html` (never restates it), wraps it in a
function, and evaluates it under `gjs` against `gateway.hello()["capture"]` —
the product's real JSON, from the product's real default gateway. Four cases:
shipped ⇒ no pin; `{2, 1}` ⇒ pin; `{2, 0}` ⇒ pin (beam 0 is real); no capture
block ⇒ no pin. A second test asserts the engine's own coercion table so the
premise is measured, not asserted.

**D-3 and R3d are corrected below.**

## 2. major — `interrupt_response: true` made a real interruption look like a "mm-hmm"

The hosted default is `turn_detection.interrupt_response: true`: server VAD
hearing the owner makes the **provider** cancel its own reply, and
`response.done` arrives with `status: "cancelled"` *before* the floor expires.
The `finished` branch read that as "the reply ended", counted a survived
backchannel and returned — so nothing called `sink.interrupt()` and nothing
truncated the item. The owner is talked over by the seconds already scheduled in
the browser **and** the provider still believes it said all of it.

**Fix:** `_response_was_cancelled(hold)` reads `usage_rows` (which
`_on_response_done` already writes one row into per response, carrying the
provider's own `status`) — matched on both the response id and the hold's start
time. Cancelled ⇒ `_commit_barge_in(send_cancel=False)`: the sink is still
interrupted and the mark is still sent, but no second `response.cancel` goes on
the wire, because the provider already sent one. Completed ⇒ still a survived
backchannel.

**Corrected by FINISH-1 (task_29 §D1) — the sentence that used to stand here
("Unknown ⇒ `False`, so the hold falls through to the ordinary floor: late,
never wrong in the dangerous direction") was false, and this is the behaviour as
it is.** This branch is only entered when the reply has ALREADY ended, and the
hold is dropped (`self._barge_in_hold = None`) *before* the status is consulted
— so there is no floor left to fall through to. An unknown status, a missing
`usage_rows` row, a differently-shaped row and the provider's `incomplete` all
settle exactly like `completed`: `backchannels_survived += 1`, the note "the
reply finished before the floor did", and **no** `sink.interrupt()` and **no**
truncate.

**Kept as it is, not changed, and why.** Treating unknown as *cancelled* would
mean sending a truncate for a response that has already ended on every shape
change — a new fail-closed path in a wave whose standing rule is
prototype-not-production and ask-over-refuse. The one status the provider emits
for the failure this defect is about is the literal `"cancelled"`, and it is
pinned by the correction pass's own fixture, so the unknown case is a
schema-drift case rather than a live one. **The residual, stated plainly:** if a
future provider ever cancels a response under a different status word, this
branch reports a survived backchannel and the browser plays out whatever was
already scheduled — the D-2 failure returning through the schema rather than
through the logic. That is DUPLEX-1's to close (it owns the local turn
controller and does not need the provider's word for "I stopped").

Read rather than re-derived, for the same reason as TURN-1's `turn_timings`: no
other card's region has to move.

## 3. minor — the played-ack timer went quiet exactly when it mattered

A timer that reports only *while* audio renders stops reporting at the one moment
the audio clock and the wall clock diverge. Only the `enqueued_ms` clamp then
bounded the truncate — and that clamp covers you exactly while the socket is
**not** running ahead of the tab.

**Fix, both halves.** Browser: one `drained: true` ack on the EDGE where the
schedule runs dry (once, not per tick), plus `drained` on the final ack.
Gateway: `played_started_monotonic` recomputes the anchor against the current
clock while drained, so the elapsed time the lane derives stays pinned at the
last reported position; any ordinary ack lifts the freeze. A *regressive*
non-drained ack also lifts it, re-anchored at the monotonic floor — that is the
common shape right after an underrun resumes, where the 20 ms scheduling lead-in
is not audio anyone has heard yet.

**Measured** on a new arrival pattern: the two stalling fixtures with the socket
**350 ms behind** the gateway — the case `enqueued_ms` does not cover.

```
[correction pass, defect 3] socket 350 ms behind the gateway, n=12
    no drain ack (MARK-1 as first written): p50=1.0ms p95=330.0ms max=480.0ms
    with the drain ack:                     p50=1.0ms p95=269.0ms max=330.0ms
    once ANY ack has landed (n=10):        p50=1.0ms p95=1.0ms max=1.0ms
    before the first ack arrives (n=2): the lane's first-enqueue fallback
        overstates by up to the lag itself (330 ms measured, bound 350 ms)
```

Two honest readings. **Once the browser has said anything at all, the mark is
1 ms accurate even with a third of a second of socket lag.** The residual is a
different thing entirely: in the window before the first ack lands, `played_ms`
is running on the first-enqueue fallback, which overstates by exactly the lag.
That is a named limitation of the fallback (bounded, and still far better than
claiming 0), not of the drain fix — and the split is asserted, not narrated.

Reported separately and **not folded into R1/R2**: the pre-registered sweep is
the 24 rows it was pre-registered on, and its numbers are unchanged
(`p50 0.0 · p95 1.0 · max 1.0 ms`).

## 4. minor — a hold outlived its socket

`_connect()` (reconnect) and `close()` (hang-up) both build a fresh
`_ResponseState`. A hold carried past either names a response id from a
conversation that no longer exists: on the next pump it was settled as a
**survived backchannel the owner never made**, and on the reconnect path it could
aim a cancel at a reply nobody interrupted.

**Fix:** one marked MARK-1 pair of lines at each reset site
(`_barge_in_hold = None; _speech_end_override = None`). Both sites are covered by
their own test and their own seed, because one line each is exactly the kind of
fix that gets half-applied.

## 5. minor — AIR-1's handoff, taken (it is inside MARK-1's OWNS)

`interrupted: true` answers "was this reply cut off". Through-air barge-in is a
**latency**: the owner's voice reaches the array at one instant and the WAV stops
at another, and without a stamp the second instant can only be recovered by
counting bytes and trusting the tee never dropped one.

`SessionAudioCapture.mark_interrupted(wall=None)` now writes, on the open robot
segment:

| field | meaning |
|---|---|
| **`interrupted_at`** | ISO wall clock of the cut — **the field AIR-1 asked for, and the name to read** |
| `interrupted_byte` | byte offset in `robot.wav` where playback stopped |
| `interrupted_t_s` | the same instant as seconds into the stream |

The stamp is the clock `_offer` read **on the relay thread** — the moment
`interrupt()` actually ran — not the moment the writer thread reached the queue
entry, which can be a whole drain batch later. Absent `wall` ⇒ no field, so an
older caller records exactly what it always did (asserted).

**On the ONSET, precisely.** It is *not* in the segment and I did not fake one.
`streams.owner.segments[].started_at` is not it: the owner stream cuts on a gap
in **mic frames**, and mic frames flow continuously while the mic is armed
(`_write_owner`), so that timestamp is "the microphone opened", not "the owner
spoke". What is true today: **with the shipped `backchannel_floor_ms = 0`,
`interrupted_at` IS the `speech_started` onset** to within one pump pass (≤ 50 ms
at 20 Hz), because `_on_speech_started` commits in the same pass. If a floor is
ever armed they differ by exactly that floor, which `/api/state` publishes as
`realtime.lane.backchannel_floor_ms`, so onset = `interrupted_at − floor`. A
true independent onset would need an argument threaded through
`browser_sink.py` → `BrowserSink.interrupt()` (**not** in MARK-1's OWNS); that is
one line in each and it is handoff **H-7**. I did not add a field that would
always be null.

## 6. note → **D-8**, plus one real race

**D-8 (declared).** The pre-registered seeds S1/S2 were substituted, and one of
them could not have fired as written. Prereg S2 said "remove the monotonic guard
⇒ the underrun fixture truncates at ~0 ms". It does not: MARK-1's own client
reports a position that does not walk backwards in any way that matters, so the
guard is barely load-bearing for it. Measured, over the 24-fixture sweep:

```
[correction pass, D-8] regressive acks refused over the 24-fixture sweep:
    MARK-1 client=16, shipped client=31
```

and the MARK-1 client's mark is **≤ 5 ms wrong on every row with the guard in
place** — i.e. its accuracy does not rest on the guard at all (asserted).
The client the guard is actually for is the one this card **replaces**, where it
is worth `p95 1441 → 1200 ms, mean 330 → 202 ms`. The guard stays — a stale
cached tab *is* the old client — but the pre-registered seed named the wrong
place, and `test_the_monotonic_guard_is_for_the_client_this_card_replaces` is the
standing measurement that says so. S1 is carried by the standing arrival witness
rather than a one-shot seed, which is stronger, and is also seeded (`S1`, `S6`).

**The final-ack race was real.** `interrupt()` clears `_first_send_at` at once,
but the browser's ~100 ms timer may already have a `played` frame in flight. That
frame reaches `_record_final_ack` *before* the browser has even seen `stop`, took
the single latched slot, and the browser's true final position was then discarded
as stale — so `last_final_played_ms` was silently up to one timer period early,
in the exact field OG-1's pass condition compares against `audio_end_ms`.
**Fix:** fold, do not latch. Heard audio only grows, so the largest
post-interrupt position wins whatever order the frames arrive in; the count is
bounded by `MAX_FINAL_ACKS_PER_UTTERANCE = 4` so a chatty client cannot spin a
counter, and both the count and the value reset per utterance (asserted — a new
reply must not open holding the previous reply's number).

## Corrections to the sections above

* **D-3 is withdrawn as written.** It claimed the unpinned path was "byte-identical
  to today's". It was not: the unpinned path ran `applyConstraints` and disabled
  Chrome's AEC. It is now true, and it is now *tested* rather than asserted —
  under a real engine, against the product's own hello.
* **R3d ("unpinned = today") was false for the browser half** and true only for
  the gateway half, which is what the original test measured. It now holds on
  both halves: gateway (`test_a_client_that_says_nothing_about_its_ear_is_refused_only_by_a_pin`)
  and browser (`test_the_unpinned_hello_leaves_the_microphone_alone`).
* **does_not_prove 1 is corrected.** "There is no browser, no DOM and no `node`
  on this host" was true; "no JS engine" was not. `gjs` 1.88.0 is installed. The
  panel is now **parsed** by SpiderMonkey (`new Function(src)` compiles without
  executing) instead of brace-counted, and its pin expression is **evaluated**.
  Still not proven: that the panel *works* — nothing here has a DOM, a socket or
  an `AudioContext`, and OG-1 remains owner-gated.
* **does_not_prove 5** gains a measured bound: with the socket 350 ms behind the
  tab, the mark is 1 ms honest once any ack has landed, and before the first ack
  the fallback overstates by at most the lag.

## What changed in this pass

| File | MARK-1 total after the pass | also in the file (not mine) |
|---|---|---|
| `src/parcel_robot/realtime/lane.py` | **+449 / −2** | TURN-1: **151–187 / −0** (corrected, below) |
| `src/parcel_robot/realtime/audio_gateway.py` | **+313 / −17** | — |
| `src/parcel_robot/ui/index.html` | **+137 / −11** | — |
| `tests/test_realtime_audio_gateway.py` | **+20 / −5** | — |
| `tests/test_mark1_barge_in_mark.py` | 1 049 lines, 19 tests | — |
| `tests/test_mark1_browser_ear.py` | 614 lines, 24 tests | — |

**Corrected by FINISH-1 (task_29 §D2).** The table used to credit TURN-1 with
`+73 / −0` in `lane.py` and that number is wrong. Re-attributed from
`git diff -U0 8862220 -- src/parcel_robot/realtime/lane.py` (522 added lines in
29 hunks): the hunks that mention **only** TURN-1 sum to **151** added lines
(`+8` at 459, `+25` at 1246, `+6` at 1467, `+5` at 1496, `+6` at 2134, `+14` at
2192, `+82` at 2341, `+5` at 2488). Three further hunks are shared and cannot be
split by hunk — most of all the `+189` barge-in-hold block at 2582, which is
MARK-1's own region citing TURN-1's `turn_timings` rows. A line-level pass that
carries the last marker seen forward gives TURN-1 **187**. So the honest range
is **151–187**, and the method is named rather than the number asserted.
MARK-1's own `+449` is the figure this card's regions were counted with and is
not re-derived here; the two are not disjoint by construction, which is the
whole reason the range exists.

## How the correction pass was verified

```
$ env -u TMPDIR .parcel/bin/python -m pytest <the same 20 files as §4> -q
982 passed, 2 xfailed, 1 warning in 25.46s

$ .parcel/bin/ruff check <the five OWNS python files>
All checks passed!

$ (whole-tree fingerprints vs scripts/ci_ruff_baseline.json)
beyond baseline: NONE
```

The ratchet is now clean at 7/7 with **nothing beyond baseline at all** — the
`tests/test_roam1_behavior.py::RUF100` fingerprint reported in §5 was ROAM-1's
and has been resolved by that card in the meantime.

### Seeded RED — 14 guards, every one restored byte-identically

| Seed | Guard removed | RED | sha256 restored |
|---|---|---|---|
| `C1` | `Number.isInteger` pin test → `Number.isFinite(Number(...))` | `…unpinned_hello_leaves_the_microphone_alone` | ✅ |
| `C2` | the `_response_was_cancelled` branch | `…provider_side_cancel_during_the_hold_is_committed…` | ✅ |
| `C3a` | the gateway's drained freeze | 2 tests | ✅ |
| `C3b` | the browser's drain edge | `…panel_says_so_once_when_its_schedule_runs_dry` | ✅ |
| `C4` | the hold reset in `close()` | `…hold_does_not_survive_the_hang_up…` | ✅ |
| `C4b` | the hold reset in `_connect()` | `…hold_does_not_survive_the_reconnect…` | ✅ |
| `C5` | the `wall` argument at the `mark_interrupted` caller | `…interrupted_robot_segment_carries_the_moment_it_was_cut` | ✅ |
| `C6` | fold → latch on post-interrupt acks | 3 tests | ✅ |
| `S1` `S2` `S3` `S4` `S5` `S6` | the original six | as recorded in §3 above | ✅ |

Driver: `/home/jaewoo-jang/.cache/parcel-mark1/seed.py` (seed → run → restore →
sha256 compare → purge `__pycache__` → rerun green). All fourteen re-run at the
end of the pass, not only when written.

## Additional handoffs from this pass

* **H-7 → whoever owns `browser_sink.py`.** A true speech-onset stamp on the
  interrupted robot segment needs an argument threaded
  `_commit_barge_in` → `SinkLike.interrupt(onset=…)` → `BrowserSink.interrupt`
  → `BrowserAudioGateway.interrupt` → `note_interrupt`. One line in each; the
  gateway end is already shaped for it (`mark_interrupted(wall=…)`). Only worth
  doing once a `backchannel_floor_ms > 0` ships, because until then
  `interrupted_at` *is* the onset (§5).
* **H-3 → TURN-1, extended.** `turn_detection.interrupt_response: false` is a
  **hard prerequisite** for any `backchannel_floor_ms > 0`, alongside
  `silence_duration_ms`. With the provider default (`true`) every held barge-in
  is resolved by the provider cancelling first: MARK-1 now handles that
  correctly (§2) but the floor buys nothing, because the reply is already dead
  before the floor can protect it.
* **H-4 → DUPLEX-1, extended.** Before turning the floor on, set BOTH of TURN-1's
  knobs: `interrupt_response: false` (or the floor is inert) and
  `silence_duration_ms` low enough that `floor >= burst + tail` (or nothing
  survives). The R4d matrix is the map.
* **H-8 → AIR-1.** `interrupted_at` / `interrupted_byte` / `interrupted_t_s` are
  live on the robot segments of the capture index; `tools/bargein_through_air.py`
  can read them today. `interrupted_byte` lets the cut be found in `robot.wav`
  without re-deriving it from the index arithmetic.
