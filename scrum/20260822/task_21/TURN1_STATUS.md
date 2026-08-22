# TURN-1 status — endpointing is a knob on the production lane

**Executor:** Claude Opus · **Verifier:** Fable · **Card:** `README.md` ·
**Board:** `../TASK_BOARD.md` · **Pre-registration:** `TURN1_PREREGISTRATION.md`
(written before the first edit) · **Base:** HEAD `8862220`

## Headline

`session.audio.input.turn_detection` was the string literal `"server_vad"` on
line 149 of `realtime/protocol.py`; it is now a validated object the owner
writes in `configs/realtime.yaml` — `type: server_vad | semantic_vad`,
`threshold`, `prefix_padding_ms`, `silence_duration_ms` (200–800),
`eagerness: low | medium | high | auto`, `interrupt_response`,
`create_response`. **Absent keys produce a byte-identical `session.update`**,
pinned against a payload captured from HEAD before the first edit and proved by
a seed. The lane now records, per spoken turn, `speech_stopped → response.created`
and `→ first sink byte`, published on `/api/state`. `tools/replay_turn_detection.py`
is the instrument that will pick the prototype default.

**Ten of the ten CI rows met (T1–T10). The three rows that decide the default
(G1–G3) are OWNER-GATED and are listed with their exact commands** — the
recording does not exist and no number was invented to stand in for it. The
prototype example therefore ships the block **commented out**, so the robot
listens exactly as it did before this card until the owner records ten minutes.

## What changed

`git diff --numstat` on the tracked OWNS is not a TURN-1 figure — `protocol.py`,
`config.py` and `lane.py` all carry other cards' uncommitted work right now
(GATE-0's `protocol.py:415`, CURIO-1's chatter block in `config.py`, MARK-1
throughout `lane.py`). The TURN-1 column below was measured by reconstructing
each file with this card's edits reverse-applied and running
`git diff --no-index --numstat` against the working tree; the right-hand column
is the whole working-tree delta on the same file, for contrast.

| file | TURN-1 | whole tree delta | what |
|---|---|---|---|
| `src/parcel_robot/realtime/protocol.py` | **+169 / −2** | +190 / −4 | `TurnDetection`, its bounds and enums, `SessionUpdate.turn_detection` |
| `src/parcel_robot/realtime/config.py` | **+149 / −0** (+1/−1 shared) | +381 / −3 | `turn_detection:` block, its loader, `RealtimeConfig.turn_detection` |
| `src/parcel_robot/realtime/lane.py` | **+148 / −0** | +422 / −1 | the knob reaches `session.update`; per-turn timings |
| `configs/realtime.yaml.example` | **+65 / −0** | +90 / −0 | the documented (commented) block |
| `configs/realtime.prototype.yaml.example` | **+47 / −0** | +133 / −0 | the prototype block, commented, with the owner's ten minutes |
| `tools/replay_turn_detection.py` | **new, 676 lines** | — | the instrument |
| `tests/test_turn1_endpointing.py` | **new, 757 lines** | — | 68 tests |
| `scrum/20260822/task_21/` | new | — | this doc + the pre-registration |

The shared line in `config.py` is `from dataclasses import dataclass` →
`dataclass, field`, needed for `field(default_factory=TurnDetection)`; CURIO-1
needs the same import and it is now there for both.

### The design decisions worth reading

1. **One object, in the codec.** `TurnDetection` lives in `protocol.py`, not in
   `config.py`, because it is a WIRE object: it must render the exact mapping
   the provider reads. `config.py` imports it (acyclic — `protocol` imports
   nothing from the package and does no I/O) and re-raises its refusals as
   `RealtimeConfigError`, so one `except` in the loader still catches every way
   a config file can be wrong. A second copy of that shape would be a second
   place for it to drift.
2. **`None` means "the key is not sent", never "send the provider's default".**
   That is the whole payload-identity contract, and it is the thing seed **S2**
   attacks.
3. **A knob the chosen endpointer never reads is REFUSED, not ignored.**
   `eagerness` under `server_vad`, and `threshold` / `prefix_padding_ms` /
   `silence_duration_ms` under `semantic_vad`, raise. The provider accepts such
   a frame and drops the key — which is precisely how, before 2026-08-18, every
   session this repo ever opened ran on the wrong voice and the wrong VAD while
   believing otherwise (`protocol.py:143-147`). This is the one place this card
   adds a refusal, and it is a config-typo boundary, not behavioural
   fail-closed logic; the standing rule's physical-safety core is untouched.
4. **Timings do not go in the conversation ledger.** The card's work item 2 says
   "the ledger carries them per turn". A per-turn timing row written through
   `_write_ledger` would enter the memory tail and be replayed to the provider
   at every session open and every reconnect — a measurement that changes what
   it measures, and tokens paid for it every time. They ride in
   `lane.turn_timings` and in `snapshot()` instead — read from
   `/api/state` (`realtime.lane.turn_timings` / `turns_timed` /
   `turn_detection`) and, in the replay, from the tool's own in-process lane.
   **Corrected in the correction pass:** an earlier draft of this line said "the
   R17 tee", which is wrong — nothing but `lane.py`, `tools/replay_turn_detection.py`
   and `tests/test_turn1_endpointing.py` references `turn_timings` anywhere in
   the tree, and the tee records audio, not counters. **Declared as deviation D2.**

## How verified

Environment: `.parcel/bin/python` (3.14.4), `.parcel/bin/ruff` 0.16.1,
`TMPDIR` unset for every pytest invocation, scratch under
`/home/jaewoo-jang/.cache/parcel-turn1/`. No sim, no daemon, no socket, no
process started or killed. **Zero hosted spend** — no credential was read and
no session was opened.

### Reference bytes, captured from HEAD before the first edit

```
$ .parcel/bin/python -c "…SessionUpdate(...).to_payload()…" > head_session_update.json
a87d9fac19edc5b96208fed0ae4f4194865fd2452ba2fb14aa1617a7dcfc619f  head_session_update.json
$ .parcel/bin/python wire_trace.py > head_wire_trace.json      # every client frame,
dcfa10d58a479850e21d321dd649827e393968ebdf3bb8134980a4e1591960a6  # handshake+happy_turn
                                                                  # and handshake+barge_in
```

### The pre-registered rows

| id | row | target | measured | verdict |
|---|---|---|---|---|
| **T1** | payload identity, three ways of not asking | 3/3 identical | 3/3, and `json.dumps` equal key-for-key | **MET** |
| **T2** | `RealtimeConfig().as_dict()` vs HEAD's 17 keys | +1 key, 0 changed | added `{turn_detection}`, removed none | **MET** |
| **T3** | `silence_duration_ms` 200/800 accepted, 199/801 refused | 2 accept / 2 refuse | 2/2 and 2/2 (plus 0, −200, 5000 refused) | **MET** |
| **T4** | enums | 6 accept / 2 refuse | 2 types + 4 eagerness accepted; 5 bad types, 4 bad eagerness refused | **MET** |
| **T5** | cross-key refusals | 4/4 refuse | 5/5 refuse, each naming "not read when" | **MET** |
| **T6** | unknown key names the allowed set | 1/1 | refusal lists all 7 allowed keys | **MET** |
| **T7** | timing counters on a scripted turn | 1 row, both fields | `response_created_ms == 400.0`, `first_audio_ms == 550.0`, `turns_timed == 1` | **MET** |
| **T8** | client frames byte-identical to HEAD's trace | sha match | `dcfa10d5…960a6` both before and after — **and again just now with MARK-1's and CURIO-1's work in the tree** | **MET** |
| **T9** | the replay tool: `--arms`, `--check`, refusal | 3/3 | 4 arms / exit 0; 16 of 16 checks / exit 0; missing recording → exit 2, no socket | **MET** |
| **T10** | ruff clean, baseline still 7 | clean, 7 | `All checks passed!`; baseline `count: 7`, same 7 fingerprints, none in my files | **MET** |

Commands and results:

```
$ .parcel/bin/python -m pytest tests/test_turn1_endpointing.py -q
68 passed, 1 warning in 0.34s

$ .parcel/bin/python -m pytest tests/test_realtime_protocol.py tests/test_realtime_ws_transport.py \
    tests/test_realtime_audio_capture.py tests/test_realtime_driver.py \
    tests/test_realtime_idle_hangup.py tests/test_p0b_companion_unlocks.py -q
225 passed, 1 warning in 8.97s

$ .parcel/bin/python -m pytest tests/test_realtime_whisperer.py tests/test_realtime_voice_identity.py \
    tests/test_realtime_spend_budget.py tests/test_realtime_tool_broker.py \
    tests/test_realtime_corpus_replay.py -q
405 passed, 1 xfailed, 1 warning in 1.89s

$ .parcel/bin/python -m pytest tests/test_realtime_reconnect.py tests/test_realtime_answer_beat.py \
    tests/test_realtime_pump_survival.py tests/test_realtime_system_initiated_motion.py \
    tests/test_realtime_completion_tense.py tests/test_prototype_profile.py -q
317 passed, 1 warning in 3.23s

$ .parcel/bin/ruff check src/parcel_robot/realtime/{protocol,config,lane}.py \
    tools/replay_turn_detection.py tests/test_turn1_endpointing.py --output-format concise
All checks passed!

$ .parcel/bin/python tools/replay_turn_detection.py --check
16/16 rows held.   (exit 0)

$ .parcel/bin/python tools/replay_turn_detection.py --replay --recording <absent> --arm semantic_auto
refused: … This row is OWNER-GATED … (exit 2, no socket opened)
```

`scripts/ci_gate.py` was **not** run and neither was the full suite, per the
standing rules. `tests/test_realtime_lane.py` could not be collected at one
point mid-run (`NameError: DEFAULT_BACKCHANNEL_FLOOR_MS`) — that is MARK-1's
work in flight in the same tree, not a TURN-1 regression; it collects and
passes now and is included in none of the counts above only because it is
theirs to green.

### Seeded RED — one per new guard

Each seed: capture the file's sha256, run the named row green, inject one exact
string, re-run and watch it fail, restore the original text, re-run green,
re-check the sha, with `__pycache__` purged before every run.
Harness: `/home/jaewoo-jang/.cache/parcel-turn1/seed.py`.

| seed | defect injected | row | green | **SEEDED** | restored | sha |
|---|---|---|---|---|---|---|
| **S1** | the `silence_duration_ms` 200–800 bound deleted | `test_silence_duration_outside_the_band_is_refused` | 5 passed | **5 failed** | 5 passed | identical |
| **S2** | `prefix_padding_ms` defaults to `300`, so an absent key changes the payload | the two T1/T2 rows | 2 passed | **2 failed** | 2 passed | identical |
| **S3** | `mid_sentence_commits` dropped from the replay report | `test_the_report_always_carries_the_mid_sentence_count` | 1 passed | **1 failed** | 1 passed | identical |
| **S4** | the first-sink-byte stamp removed from `_emit_audio` | the two T7 rows | 2 passed | **1 failed** | 2 passed | identical |

`protocol.py` sha `37bf81e854af…d7c9f1` before and after S1 and S2;
`replay_turn_detection.py` `d98c577212…4ab34a` before and after S3;
`lane.py` `6582533c84…6bb339` before and after S4 — restored byte-identically
with another executor writing to `lane.py` in the same window, which is why
each seed was a single exact-string replace and its reverse rather than a
whole-file backup.

## What it does not prove

1. **Nothing about how the provider actually endpoints.** Every row above is
   about the KNOB — that it exists, that it validates, that not using it
   changes nothing, and that the instrument works. Whether `semantic_vad` at
   `eagerness: low` actually stops cutting the owner off mid-sentence is
   G1–G3 and needs the owner's voice. No live session was opened by this card.
2. **`semantic_vad`, `eagerness`, `interrupt_response` and `create_response`
   have never been sent to the provider from this repo.** They are validated
   against the provider's documented schema, not against a refusal captured on
   a wire. If the provider has renamed one, the first live replay finds it —
   which is exactly what the replay is for. Contrast `type: "realtime"` and the
   audio-object relocation, which ARE live-verified and are cited as such in
   `protocol.py`.
3. **The commit-latency definition is the tool's, not the provider's.** The
   report grades G1 on `audio_end_ms − end_of_speech_ms(wav)` — the provider's
   own boundary index minus an RMS-envelope estimate of where the owner stopped
   talking. That estimate has a threshold (`SILENCE_RMS = 500`) chosen for the
   array's noise floor and never calibrated on a real recording; it will bias
   every arm the same way, but the absolute number is an estimate. The lane's
   wall-clock `response_created_ms` / `first_audio_ms` are reported beside it
   and are exact.
4. **The timing rows are correct for a turn the provider answers.** A turn
   committed and then never answered leaves an incomplete row (both milestones
   `null`), which is honest; but a turn that gets `response.created` and no
   audio at all keeps its row open until the session boundary, so a much later
   robot-initiated reply on the SAME session could stamp its `first_audio_ms`.
   `_note_turn_milestone` closes a row as soon as both are filled, and
   `_reset_session_state` clears it, which covers every path a test exercised;
   the "created but never any audio, then a narration" sequence was uncovered.
   **SUPERSEDED by the correction pass, note A:** `_note_turn_milestone` now
   refuses any milestone while `_response_provenance` is not
   `RESPONSE_FROM_OWNER`, so a reply nobody asked for contributes nothing to
   any row. Guarded and seeded (S10).
5. **`turn_timings` is per-lane, in memory, and evicted at 200 rows.** It is not
   persisted, so a replay must read it from the live process (which the tool
   does) and a crash loses it.
6. **The prototype default is unchanged.** `configs/realtime.prototype.yaml.example`
   documents the arms and ships them commented; the prototype listens today
   exactly as it did before this card. That is a miss against the card's
   sentence "carries the prototype choice" and it is deviation **D3**.

## Deviations from the card, declared

| # | deviation | reason |
|---|---|---|
| **D1** | `eagerness` accepts **`medium`** as well as the card's `low \| auto \| high`. | The provider documents four values. Refusing one the provider takes would be a wrong refusal, and this card exists to give the owner the choice. The three the card names are what the replay arms use. |
| **D2** | The per-turn timings are published in `lane.snapshot()` and `lane.turn_timings`, **not written to the conversation ledger** as the card's phrase "the ledger carries them" could be read to require. | A ledger row per turn enters the memory tail, is replayed to the provider at every session open and reconnect, and is paid for in input tokens each time — a measurement that changes what it measures. They are read from `/api/state` and from the replay tool's own lane; **not** from the R17 tee, which records audio and has no view of these counters (an earlier draft of this row said otherwise — corrected). |
| **D3** | `configs/realtime.prototype.yaml.example` ships the block **commented out** rather than carrying a chosen prototype default. | The card pre-registers that the default is picked "from the numbers", and the numbers are owner-gated. Writing a guessed value into a prototype config and never measuring it is how `robot.yaml speech.endpointing: semantic` ended up applying only to a loop nobody runs. The file names the expected winner (`semantic_vad` / `eagerness: low`) and the exact commands that settle it. |
| **D4** | Two bounds the card did not specify were invented: `prefix_padding_ms` ∈ [0, 2000] and `threshold` ∈ [0, 1]. | `threshold` is a normalised probability, so [0,1] is the provider's own domain. 2000 ms of prefix padding is a mistyped `silence_duration_ms`; the bound is stated in `PREFIX_PADDING_MS_RANGE` with its reason and is trivially widened. |
| **D5** | TURN-1 touches **nine** marked sites in `lane.py`, only one of which is the literal `speech_stopped` dispatch branch the card names. The earlier draft of this row listed two of them; all nine are enumerated below the table. | The card's own work item 2 requires "→ first sink byte" and "the ledger carries them per turn", neither of which can live in the dispatch branch. Every site carries a `CARD TURN-1` marker; none is in MARK-1's `_on_speech_started` / `played_ms` region, and MARK-1 has since added its own line two lines above mine in `_emit_audio` with both coexisting. |
| **D6** | `tests/test_turn1_endpointing.py::test_the_stopwatch_adds_no_frame_and_no_row_to_a_barge_in` asserts less than the pre-registration's T8 wording. | T8's byte-identical trace was measured and MET as a sha comparison (twice). The in-file test deliberately does not assert what a barge-in *does*, because MARK-1 is redefining that right now (backchannel floor); coupling to it would make two cards fail together for one card's reason. |

**The nine `lane.py` sites (D5), by line number as of the correction pass:**

| # | line | site | what |
|---|---|---|---|
| 1 | 452 | module constants | `LIFECYCLE_RESPONSE_CREATED` |
| 2 | 1239 | `__init__` | `turn_timings`, `turns_timed`, `_turn_timing_limit`, `_turn_timing` |
| 3 | 1453 | `_connect` (session reset) | `self._turn_timing = None` — a stopwatch cannot survive its socket |
| 4 | 1482 | `_connect` (session open) | `turn_detection=self.config.turn_detection` on `SessionUpdate` |
| 5 | **2114** | `_dispatch`, `SpeechStopped` | **the literal region the card names** |
| 6 | 2172 | `_dispatch`, `LifecycleEvent` | `response.created` → the commit milestone |
| 7 | 2320–2395 | new methods | `_on_speech_stopped`, `_note_turn_milestone` |
| 8 | 2467 | `_emit_audio` | the first-sink-byte stamp, one line after the enqueue |
| 9 | 3630 | `snapshot()` | `turn_detection`, `turns_timed`, `turn_timings` |

**Nothing was reverted.** `protocol.py:415` is GATE-0's and was not touched;
`lane.py`'s `_on_speech_started` / `played_ms` are MARK-1's and were not
touched; `ui/index.html`, `tool_broker.py` and `audio_gateway.py` were not
opened. No git command other than `diff`/`status`/`log` was run.

## OWNER-GATED rows — the ten minutes that pick the default

Nothing below can be run without the owner's voice. Listed with exact commands,
never claimed.

**Step 1 — write and record the corpus (~10 minutes, the reSpeaker array):**

```
.parcel/bin/python tools/replay_turn_detection.py --plan \
    --out ~/.cache/parcel-turn1/recording
~/.cache/parcel-turn1/recording/record.sh
```

Twenty two-clause utterances, each with a deliberate ~400 ms pause at the `...`.
The pause is the experiment: an endpointer that commits during it has cut the
owner off. `PARCEL_MIC_DEV` defaults to `plughw:2,0` (ALSA card 2 is the
XVF3800); 16 kHz mono, 8 s per take, resumable.

**Step 2 — one hosted session per arm (four short sessions, a few cents each;
the card's ≤ $2 ceiling is not close to being reached):**

```
set -a; . ~/.config/parcel/realtime.env; set +a
for arm in server_vad_default semantic_low semantic_auto semantic_high; do
  .parcel/bin/python tools/replay_turn_detection.py --replay --live \
      --recording ~/.cache/parcel-turn1/recording --arm "$arm" \
      --out ~/.cache/parcel-turn1/results
done
```

**The rows, pre-registered before any replay:**

| id | row | target |
|---|---|---|
| **G1** | `commit_latency_p50_ms` per arm | ≤ 600 ms |
| **G2** | `mid_sentence_commits` on the chosen arm | 0 / 20 |
| **G3** | scripted barge-in still fires with a truncation row present | 3 / 3 |

**G3 is not covered by `--replay` as built** and is a second miss: the replay
streams recordings and never talks over the robot, so it reports
`truncations` (visible in every report) but does not *stage* three barge-ins.
Staging them needs a second speaker in the room or MARK-1's rig; the honest
version is the owner interrupting the robot three times during arm 2 and
reading `truncations` out of the report.

Then uncomment the winning block in `configs/realtime.prototype.yaml.example`
(or `configs/realtime.yaml`) — the block is written out, ready.

## Handoffs

1. **MARK-1 already consumes TURN-1's rows.** `lane._speech_ended_after`
   (MARK-1's backchannel floor) reads `turn_timings[*]["speech_stopped_at"]`
   read-only and defensively. **That field name and its meaning — the monotonic
   clock reading at `input_audio_buffer.speech_stopped` — are now load-bearing
   for two cards.** Do not rename it, do not change its units, and note that
   the 200-row eviction bound could in principle drop a row MARK-1 wants (it
   reads newest-first, so in practice it cannot).
2. **DUPLEX-1** is the card that turns these two numbers into a policy. It gets
   `turn_timings` per turn, `turn_detection` on the snapshot, and a replay
   harness that already streams recorded audio through the lane in real time —
   `tools/replay_turn_detection.py --replay` is most of a DUPLEX-1 rig.
3. **AIR-1** should run its session AFTER the owner records this corpus: the
   same twenty WAVs are a false-barge-in corpus for free.
4. **GATE-0 / the gate:** `tests/test_turn1_endpointing.py` is 73 tests, ~1.0 s,
   no sim, no socket, no tmp path, no credential — it belongs in the commit
   tier. It reads `configs/realtime.yaml.example` and
   `configs/realtime.prototype.yaml.example` from the repo root, so it needs a
   real checkout (not the packaged asset mirror).
5. **P0-A / runtime assets:** `configs/realtime*.example` are not in
   `runtime_assets/MANIFEST.json`, so nothing needed mirroring.
6. **The one thing a verifier should re-run first:** the payload identity. From
   a clean checkout of `8862220`, dump
   `SessionUpdate(instructions="be a good dog", model="gpt-realtime-2.1-mini", voice="cedar").to_payload()`,
   then dump it again on this tree, and diff. It must be identical; if it is
   not, everything else in this card is a behaviour change wearing a knob.


---

# Correction pass — 2026-08-22, after Fable's 12-agent verification

Fable **accepted the knob** (payload identity byte-identical four ways, D2
sound, MARK-1's region disjoint, the cross-key refusal judged an acceptable
config-typo boundary) and **rejected the instrument**. Four confirmed findings,
two notes and a lint addendum. All fixed; the whole card re-verified.

## The findings

### 1 (major) — every owner-gated command in this doc would have died at `open_session`

`tools/replay_turn_detection.py` called
`lane.open_session(handshake_token=None, mic_gesture=True)`.
`decide_realtime_arming` refuses a falsy token (`CODE_NO_HANDSHAKE`, "a
reachable service is not consent"), `_open_locked` turns that into
`RealtimeLaneError` — and `main()`'s `except` tuple was
`(ReplayRefusal, RealtimeConfigError)`. So the G1/G2/G3 recipe printed in this
doc, in `configs/realtime.yaml.example` and in
`configs/realtime.prototype.yaml.example` would have ended in a traceback,
after the owner had spent ten minutes recording, before one frame went up.

**This was invisible to every row I ran**, because `--replay` was only ever
exercised on its *refusal* paths (missing recording, missing `--live`). A guard
that only tests the door being shut proves nothing about the room.

Fixed three ways:

* `REPLAY_HANDSHAKE_TOKEN = "replay_turn_detection"` — a named constant with the
  reason beside it. It is not a credential and not the panel's CSRF token:
  there is no HTTP server in this process and nothing else can reach this lane.
  The consent gesture it stands in for is the owner typing `--live`.
* `_live_failure_types()` resolves `RealtimeLaneError` and
  `RealtimeTransportError` **lazily** (so `--arms` / `--check` / `--plan` still
  cannot import a module that can open a socket) and `main()` turns both into
  `refused: …` + exit 2. `RealtimeAuthError`, `RealtimeConnectError` and
  `RealtimeQuotaError` are subclasses of the base and are covered.
* `replay()` gained an injectable `build_lane`, defaulting to
  `_build_live_lane`, so the harness can be driven end to end against
  `transport_pair()`.

### 2 (major) — the corpus would have played at 1.5×, and file 2 onward would have lied

Two independent errors in the same arithmetic:

* **Rate.** The tool streamed the array's 16 kHz PCM straight into
  `lane.send_audio`. The session declares no `audio.input.format` (adding one
  would move the payload-identity row), so the provider assumes its 24 kHz
  default — which is also what the browser ear resamples to in
  `encodeMicFrame`, and what the gateway hello states. The corpus would have
  arrived 1.5× fast: the deliberate ~400 ms mid-sentence pause becomes ~267 ms,
  and **G2 — the row that decides the default — is flattered on every arm**.
* **Origin.** `audio_end_ms` indexes the whole SESSION's input buffer. It was
  being subtracted from a per-FILE `end_of_speech_ms`, so utterance 20 would
  have reported a "silence tail" containing the previous nineteen recordings.

Fixed: `to_provider_rate()` / `resample_pcm16()` — deliberately the same linear
interpolation as `ui/index.html`'s `encodeMicFrame`, because the harness must
not sound better than the product; frames paced at `PROVIDER_BYTES_PER_MS`
(960 bytes = 20 ms at 24 kHz, not 640); `end_of_speech_ms(pcm, *, rate_hz=…)`
with the rate **required and no default** — the whole bug was a default nobody
looked at; and a per-file `audio_offset_ms` carried in every row beside
`commits_raw_ms`, so `commit = raw − offset` is auditable from the report file
alone. The report now states `analysis_rate_hz` and `recorded_rate_hz`.
`SessionUpdate` was **not** touched — declaring an input format would move T1.

### 3 (minor) — a guard that could not fail

`test_the_first_audio_stamp_does_not_move_for_later_chunks` compared
`None == None` when the stamp was deleted (it passed under my own seed S4), and
the script was exhausted by the third `speak()`, so the fourth delivered no new
chunks and an overwriting stamp would have passed too. Rewritten: `first is not
None` is asserted, the second batch of audio arrives **while the row is still
open** (before `response.created`, since a closed row cannot be stamped anyway —
otherwise the test proves the row-close and not the once-guard), and the row is
asserted still open at that moment.

### 4 (minor, doc) — two wrong statements in this file, corrected in place

* The headline reasoning and D2 said the timings are read by "the R17 tee".
  They are not: `grep -rn turn_timings` over `src/`, `tools/`, `tests/` and
  `scripts/` matches only `lane.py`, `tools/replay_turn_detection.py` and
  `tests/test_turn1_endpointing.py`. The tee records audio and has no view of
  these counters. Corrected to `/api/state` + the replay tool's own lane.
* D5 listed 2 of the marked `lane.py` sites outside the literal `speech_stopped`
  dispatch branch. **All nine are now enumerated with line numbers** under the
  deviations table.

## The notes

**Note A — a robot-initiated `response.created` could stamp an open owner row.**
Judged worth fixing, and cheap. It is the residual I had already written into
"what it does not prove" §4, and the lane already knows the answer: card R11's
`_response_provenance`. A turn the provider answers with text or a tool call
only never gets a `first_audio_ms`, so its row stays open; the next thing the
robot says *by itself* would have stamped its own audio in as a wait of
minutes, in the middle of the p50 this card grades. `_note_turn_milestone` now
returns immediately unless `_response_provenance == RESPONSE_FROM_OWNER`
(+15 lines in that method, all in TURN-1's own region). New guard:
`test_a_narration_the_robot_started_cannot_stamp_the_owners_row`; new seed S10.
"What it does not prove" §4 is superseded by this fix.

**Note B — `ruff format`.** Declined, deliberately. It is not gated, it would
touch three files that `git diff` currently shows other cards writing to
(`config.py`, `lane.py`), and a whitespace-only reflow in a shared tree
mid-wave costs every concurrent executor a merge for no gate benefit. Worth
doing as a tree-wide pass when the wave lands, not by one card now.

## The lint addendum

Both named fingerprints are fixed **at the source** — no `noqa`, no baseline
re-pin, no rule disabled.

| fingerprint | before | after | when |
|---|---|---|---|
| `src/parcel_robot/realtime/config.py::RUF009` | `config.py:698:37: RUF009 Do not perform function call ``TurnDetection`` in dataclass defaults` | `turn_detection: TurnDetection = field(default_factory=TurnDetection)` | fixed in the ORIGINAL pass — ruff cannot see that `TurnDetection` is frozen from another module, the same reason GATE-0 uses `default_factory` at `protocol.py:415` |
| `tools/replay_turn_detection.py::RUF046` | `replay_turn_detection.py:472:47: RUF046 Value being cast to ``int`` is already an integer` | `out[index] = max(-32_768, min(32_767, round(value)))` | **introduced by this correction pass** (the new resampler wrote `int(round(value))`) and fixed within it |

The tree-wide ratchet, reproduced with `ci_gate._ruff_fingerprints`' exact
invocation:

```
$ .parcel/bin/python -m ruff check . --output-format=json   # from the repo root
TOTAL fingerprints tree-wide: 7
MINE: none
   src/parcel_robot/camera_channel/__init__.py::RUF022
   src/parcel_robot/camera_channel/backends/factory.py::ISC004
   src/parcel_robot/camera_channel/backends/factory.py::S110
   src/parcel_robot/camera_channel/channel.py::I001
   src/parcel_robot/detection_adapter/noise.py::I001
   src/parcel_robot/detection_adapter/sim_bridge.py::B009
   src/parcel_robot/detection_adapter/sim_bridge.py::ISC004
```

Exactly the seven baseline fingerprints, none of them mine — the other cards
have cleared theirs as well, so the ratchet is green tree-wide right now.

```
$ .parcel/bin/ruff check src/parcel_robot/realtime/{protocol,config,lane}.py \
    tools/replay_turn_detection.py tests/test_turn1_endpointing.py --output-format concise
All checks passed!
$ .parcel/bin/ruff check --select RUF009,RUF046 <the same five files>
All checks passed!
```

## Re-verification after the corrections

The two rows the whole card rests on were re-measured **after** every change
above, against the bytes captured from HEAD before the first edit:

```
T1 payload identity after correction pass: True
$ sha256sum head_wire_trace.json after_correction_trace.json
dcfa10d58a479850e21d321dd649827e393968ebdf3bb8134980a4e1591960a6  head_wire_trace.json
dcfa10d58a479850e21d321dd649827e393968ebdf3bb8134980a4e1591960a6  after_correction_trace.json
```

```
$ .parcel/bin/python -m pytest tests/test_turn1_endpointing.py -q
73 passed, 1 warning in 1.00s          # was 68; +5 guards

$ .parcel/bin/python -m pytest <the 16 neighbouring realtime test files> -q
905 passed, 1 xfailed, 1 warning in 13.07s
```

`tools/replay_turn_detection.py` 676 → **838 lines**;
`tests/test_turn1_endpointing.py` 757 → **1044 lines**; `lane.py` +15.

### Seeded RED — all ten, re-run together

Same harness (`/home/jaewoo-jang/.cache/parcel-turn1/seed.py`): sha the file,
run the row green, inject one exact string, watch it fail, restore, re-run
green, re-check the sha, `__pycache__` purged before every run. S1–S4 were
re-run because their rows changed; S5–S10 are new.

| seed | defect injected | row | green | **SEEDED** | restored | sha |
|---|---|---|---|---|---|---|
| **S1** | `silence_duration_ms` bound deleted | out-of-band refusal | 5 passed | **5 failed** | 5 passed | identical |
| **S2** | `prefix_padding_ms` defaults to 300 | T1 + T2 | 2 passed | **2 failed** | 2 passed | identical |
| **S3** | `mid_sentence_commits` dropped from the report | the report row | 1 passed | **1 failed** | 1 passed | identical |
| **S4** | first-sink-byte stamp removed | the two T7 rows | 2 passed | **2 failed** | 2 passed | identical |
| **S5** | `handshake_token` back to `None` (finding 1) | the session-opens row | 1 passed | **1 failed** | 1 passed | identical |
| **S6** | the 16→24 kHz resample dropped (finding 2, rate) | the stream-rate row | 1 passed | **1 failed** | 1 passed | identical |
| **S7** | the per-file `audio_offset_ms` dropped (finding 2, origin) | the two-file corpus row | 1 passed | **1 failed** | 1 passed | identical |
| **S8** | the once-guard overwrites on every chunk (finding 3) | the stamp-does-not-move row | 1 passed | **1 failed** | 1 passed | identical |
| **S9** | `main()` catches nothing live (finding 1) | the refusal-not-traceback row | 1 passed | **1 failed** | 1 passed | identical |
| **S10** | the provenance check removed (note A) | the narration row | 1 passed | **1 failed** | 1 passed | identical |

S4 now reddens **2/2** rather than 1/2 — that is finding 3 fixed, visible in the
seed table itself.

## What the correction pass still does not prove

1. **No hosted session has been opened.** The replay is now driven end to end
   against `transport_pair()` with a scripted server: the arming, the session
   frame, the frame size, the pacing and the per-file arithmetic are all
   measured. What a real socket does — the provider's `audio_end_ms` semantics,
   whether it indexes appended bytes or wall time from session open, whether
   `semantic_vad` is spelled the way the docs say — is still G1–G3.
2. **`audio_end_ms` is assumed to be an index into the appended audio.** If the
   provider instead measures wall time from session open, the per-file offset is
   right in shape but will carry the gap between files. Both `commits_raw_ms`
   and `audio_offset_ms` are in every report row precisely so the first live run
   can settle this from the data instead of from a re-run.
3. **`SILENCE_RMS = 500` is still uncalibrated** against a real recording from
   this array. It biases every arm identically; the absolute latency is an
   estimate. Unchanged from the original pass.
4. **G3 still is not staged by the tool.** Unchanged and still listed as a miss
   in the owner-gated section: the replay streams recordings and never talks
   over the robot, so it reports `truncations` but does not create them.
