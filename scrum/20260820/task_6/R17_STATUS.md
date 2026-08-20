# R17 — keep the voice, replay the voice — EXECUTOR STATUS

**Date:** 2026-08-20 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Card:** `scrum/20260820/task_6/README.md`
**Dispatch gate:** satisfied — `scrum/20260820/AUDIT_R12_R16_FABLE.md` records
ACCEPT_CLOSE on all five cards of the R12–R16 chain at 6732 passed.

## Verdict in one paragraph

The audio survives now, and the corpus can be replayed at it. `capture:` is a
new fail-closed block in the realtime config, default OFF; when the owner turns
it on the gateway tees both directions to `owner.wav` / `robot.wav` with a
per-utterance `index.json` whose byte ranges cannot drift from the audio,
bounded by a queue, a minute cap and an exception firewall so that a slow or
broken disk can never touch the conversation. `tools/run_voice_corpus.py` speaks
a WAV corpus at a LIVE stack through the real browser audio gateway, one query
at a time, at a pace a human can watch, and writes a scored run folder in
live_run_1's shape. Proven live on my own stacks (`:8823`, `:8824`) across three
sessions and 56 spoken queries for **$0.957**: the tee captured **6 506 204
owner bytes — exactly `gateway.bytes_in`, zero loss** — and 23 100 000 robot
bytes, which is `gateway.bytes_out` minus exactly `44 × 2040` RIFF headers, with
0 queue drops and 0 writer errors. All three `estop-pos` queries latched, were
asserted and were **released**, and the run ended `latched_at_end: false` —
live_run_1's 84-second blind spot is now structurally impossible.
**16 seeds RED**, every restore byte-identical, every fresh-interpreter canary
green. **Three things did not go the card's way and are reported as such**: the
owner has not recorded the corpus, so the replay used piper speech and is not
the owner's voice; the hosted lane went silent at q30 of the full replay and
twenty verdicts after it describe a dead lane rather than the product; and the
first live run exposed a defect in my own capture design (the index only existed
after a clean shutdown), which is now fixed and re-proven under `kill -9`.

---

## §1 — What changed

| File | Change |
| --- | --- |
| `src/parcel_robot/realtime/config.py` | `capture:` block — a nested config family beside `whisperer:`, fail-closed, default OFF; `CaptureConfig`; `resolve_capture_dir` with the `evals/` refusal and the cwd-independence rule |
| `src/parcel_robot/realtime/audio_gateway.py` | `SessionAudioCapture` (the bounded, non-blocking tee), `_CaptureStream`, `pcm_from_playback_chunk`, `verify_capture_index`, `new_capture_session_id`; four tee call-sites inside the existing relay methods; `capture` in `snapshot()` |
| `src/parcel_robot/runtime.py` | **one conditional wiring block** in `_build_realtime_sink` (deviation, §9.1) |
| `configs/realtime.yaml.example` | the documented `capture:` block |
| `tools/run_voice_corpus.py` | NEW (≈1 100 lines) — the UI-mounted sequential corpus runner |
| `tests/test_realtime_audio_capture.py` | NEW — 24 tests: the tee, its three bounds, its index, its config |
| `tests/test_realtime_audio_gateway.py` | +3 tests: the runtime wiring, both directions of the default, the `evals/` refusal end to end |
| `tests/test_voice_corpus_runner.py` | NEW — 21 tests: refusals, e-stop hygiene, the silence breaker, scoring, the run folder |
| `evals/20260820/voice_corpus_v1/replay_run_1/` | NEW run folder (runner output, not a fixture) + a dated READ-THIS-FIRST addendum |

---

## §2 — Item 1: the tee, and the one law it obeys

### 2.1 The defect it exists because of

`evals/20260820/voice_corpus_v1/live_run_1/results.json`, in its own words:

> `"raw_audio_persisted": false` — "`state.realtime.gateway` logged
> `frames_in=3605 / bytes_in=7383040` (~153.8 s of 24 kHz mono s16 owner audio)
> and `frames_out=296 / bytes_out=3397024` (~70.8 s of robot audio). **None of
> it was written to disk.**"

Every ASR-shaped finding in that run is therefore unreproducible: the Korean TV
sign-off attributed to the owner (F1, recurred verbatim from owner_session_1),
the spoken emergency phrase rendered as "Dice out!" and never matched (F6), q52's
code-switch normalised away. The transcripts survived; the sound did not.

### 2.2 The relay-path contract

Both tee call-sites are on paths R7 chose deliberately:

* `accept_audio` runs **on the socket reader's own thread** — R7's design, so a
  busy lane backpressures TCP rather than filling an unbounded queue. A tee
  that blocked here would become microphone latency.
* `send_audio` runs **inside `lane.pump()`** and is documented as never
  raising — an exception there surfaces as `pump failed` and takes the whole
  conversation down because a browser tab closed.

So the producer side does no I/O, holds no lock a writer can be inside, and
cannot raise:

```python
    def _offer(self, kind: str, payload: Any) -> bool:
        try:
            if not self._running or self._stopping: ...          # counted no-op
            if len(self._queue) >= self._max_queue:
                self.frames_dropped_queue_full += 1
                return False                                      # drop, never wait
            self._queue.append((kind, payload, self._wall()))
            self._wake.set()
            return True
        except Exception:   # the tee may never break the relay
            self.writer_errors += 1
            self._running = False
            return False
```

A single daemon thread does every write. **S2** pins the latency claim by
wedging that thread inside one drain for two seconds behind a two-frame queue
and asserting that 200 relay frames still complete in under half a second **and
that all 200 reached the lane** — the tee starves, the conversation does not.
**S3** pins the firewall.

### 2.3 Three bounds, not one

1. **The queue** (`DEFAULT_MAX_CAPTURE_QUEUE_FRAMES = 512`) — full ⇒ the frame
   is dropped and counted, never awaited (`frames_dropped_queue_full`).
2. **The clock** (`capture.max_minutes`, default 30, per stream) — reached ⇒
   capture closes ITSELF: it logs once, finalizes both WAVs and writes the
   index, and the session is untouched. The event says so out loud: *"audio
   capture reached its 30 min cap and stopped; the session is UNAFFECTED and
   keeps running."* (**S1**)
3. **The blast radius** — every producer entry point swallows its own
   exceptions and disables the tee rather than propagating.

### 2.4 The index, and why it cannot drift

The card asks for "utterance id → byte/time range so single turns are
extractable as fixtures". That is only worth anything if a byte range in the
index IS that audio in the WAV. Three choices make drift structural rather than
unlikely:

* **Segments tile the file.** The first starts at byte 0, each begins exactly
  where the previous ended, the last ends at `data_bytes`. There is no
  "unaccounted audio" state to drift into. Owner segments cut on a silence gap
  (`owner_gap_s`, default 0.75 s); robot segments cut on the lane's own
  `begin_utterance`.
* **Times are derived from bytes**, never measured: `t0_s = start_byte /
  (rate × 2)`. A writer thread descheduled for a second cannot desynchronise
  them. (**S4** flips exactly this and the verifier catches it.)
* **`verify_capture_index()`** is the executable statement of both, exported so
  the runner and any future fixture-extraction tool check the same invariant.
  A test hand-drifts a good index four ways — unindexed audio, a hole between
  segments, a time that no longer matches its offset, a header patched to the
  wrong size — and asserts each is named.

The robot half additionally unwraps every playback chunk (`pcm_from_playback
_chunk`), because the lane sends a self-contained WAV per 240 ms chunk and a
naive concatenation would bury a RIFF header every 240 ms inside the recording.
The live numbers in §7.2 are the proof that the unwrapping is exact. (**S10**)

### 2.5 Default OFF, and where the refusals are

`capture.enabled` defaults to false, an absent block means the same, and the
gateway snapshot reports `{"enabled": false}` rather than omitting the key — off
is a stated fact in `/api/state`, not something a reader has to infer.
Recording a household microphone to disk is asked for in writing, once, by the
person whose voice it is. (**S8**, **S11**)

`capture.dir` may never resolve inside `evals/`, and that is a **load-time**
refusal: eval fixtures are the record a run is scored against, and a live tee
appending into that tree could rewrite the record while it is being graded.
(**S7**) Relative dirs resolve against the repo root and never the cwd — which
is the same mistake, at the same layer, that put live_run_1's artifacts under a
doubled repo-relative prefix.

### 2.6 The design defect my own live run found

The first live session was killed rather than closed. Both WAVs survived intact
(headers are patched after every drained batch) and **`index.json` was simply
absent**, because I had only written it in `_finalize`. An index that exists
only after a clean shutdown is missing exactly when an investigation wants it.

Fixed: the index is flushed at every segment boundary and at most once a second
otherwise, and a mid-session index includes the segment still being written
(provisionally closed at the current byte offset, `"open": true`) so the tiling
invariant holds at every instant instead of only at the end. Re-proven at the
process level with `SIGKILL` (§7.3): the index survives, and the residual —
bounded by the one-second flush interval — is **reported by the verifier as an
exact byte count** rather than hidden.

---

## §3 — Item 2: the UI-mounted corpus runner

`tools/run_voice_corpus.py --corpus DIR --out RUN [--port N] [--pace S]`

* **Real gateway path, not a shortcut.** It opens the panel's websocket at
  `/api/realtime/audio` with `parcel-audio` + `parcel-csrf.<token>` (the token
  lifted from the panel page exactly as a browser does), waits for `hello`,
  sends the owner's `{"type":"mic","on":true}` gesture as its own control frame
  — the gesture is what opens the paid session — and only then streams 20 ms
  PCM16 frames **in real time**, because the provider's server VAD is watching
  that stream and a corpus blasted up at disk speed is one enormous utterance.
* **It sends `played` acks.** R7's `does_not_prove` #2 was that every live
  barge-in truncated at 0 ms because its headless client never acked. This one
  acks every chunk; the live run recorded `played_acks 2034 · stale_acks 6`.
* **One query at a time, and it waits for the turn to be over.** Settle =
  a substantive response (reply, tool or mission) **and** `--quiet` seconds with
  no new row, **and** no mission still running, up to `--mission-settle`; then a
  hard `--turn-timeout`. live_run_1 could never score arrival because the next
  query preempted every mission 4–6 s in; here the wait is explicit and the
  settle reason is recorded per query.
* **`--pace` is spent reading the socket, not sleeping on it** — a client that
  stops draining playback is a client the gateway starts counting backpressure
  drops against.
* **The panel and the MuJoCo window stay live the whole time.** That IS the UI
  mount: nothing here is headless-by-design, and the terminal prints, per query,
  the gold cell, what was heard, what was said, which tools fired with their
  status, the goals, the verdict and the running spend.

### 3.1 Refusals, before anything is touched

| Guard | Behaviour | Seed |
| --- | --- | --- |
| the owner's stack | `--stack owner` **and** a bare `--port 8765` both refuse without `--i-am-the-owner`; the refusal happens before any socket, any GET and any spend | S6 |
| the output path | `--out` is resolved once, printed, and a resolved path that repeats a run of segments is refused — live_run_1's doubled repo-relative prefix, fixed at the collector as its README asked | S12 |
| overwriting | an existing `--out` refuses; run folders are written once | — |

### 3.2 Scoring: mechanical, or explicitly deferred

Verdicts come from checkable predicates against the gold column — a tool fired,
a goal matched, the latch did or did not engage, a mission started where the
cell forbade one. Where the gold cell asks for a judgement about wording
("warm in-character reply") the runner records everything and returns
**`NEEDS_REVIEW`**, the one documented extension to live_run_1's verdict set
(§9.2). Two rules are worth naming:

* **A fabricated mission fails a refusal cell** — live_run_1's finding 3, where
  Narnia and the moon became real missions. (**S14**)
* **Silence is a FAIL, on the runner's own authority** — live_run_1's finding 2
  was that the dominant defect is not wrong answers but *no* answers, and no
  human is needed to grade that. (**S13**) A judgement cell is never inflated
  into a PASS. (**S15**)

---

## §4 — Item 3: e-stop hygiene

live_run_1's defining event, from its own README:

> **The owner latched the emergency stop at 14:28:19 and never noticed.** The
> last 84 seconds of the corpus were spoken into a robot that could not move,
> and it never said so. … 18 owner turns … the latch was **never released**; it
> was still engaged 350 s later at the snapshot.

The harness makes that state impossible to sustain:

* **Pre-flight.** The run does not start against a latched robot. (The owner's
  own stack was still latched hours after live_run_1 — a run started there would
  have scored every query against a frozen robot.)
* **After every query, not only the estop-positives.** A latch can arrive from
  the panel's Space key or from a mis-transcription of anything, so the check is
  unconditional.
* **The assertion and the release are separate.** An `estop-pos` query PASSES
  **iff** the latch fired — that is the assertion — and only then is the latch
  released (owner-authorised for eval runs). An `estop-neg` query that latches
  is a `FALSE LATCH` FAIL *and* is still cleaned up.
* **A release that does not take ABORTS the run.** (**S5**) The remaining
  queries are never spoken and are recorded `NOT_ATTEMPTED` with the reason. A
  verdict produced against a robot that cannot move is worse than no verdict.
* **The record survives the abort.** The query that caused the latch is scored
  and banked *before* the release is attempted — losing the verdict for the very
  utterance that latched the robot would throw away the run's best row.

### 4.1 The same lesson, arriving from the other direction

The full replay's hosted lane went silent at q30 and the harness dutifully spoke
**twenty more queries into it**, producing sixteen FAILs and four PARTIALs that
describe a lane's health rather than a product's behaviour — and about $0.25 of
spend to learn it twenty times over. That is scoring against a frozen robot with
a different cause. The runner now carries the matching circuit breaker:
`--silence-abort` (default 4) aborts when N consecutive queries produce nothing
at all — no transcript, no reply, no tool, no event — naming
`state.realtime.lane` as the place to look. An isolated dropped turn does not
trip it. This is a scope extension and is declared as one in §9.3.

---

## §5 — Gate

Run after the final edit, verbatim:

```
CI GATE — tier=commit  (2026-08-20T20:08:04Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.52s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.40s
[  PASS] HARD  release-parity-integrity   10 passed in 0.76s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.42s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.41s
[  PASS] HARD  default-suite              6780 passed, 9 skipped, 42 deselected, 5 warnings in 276.12s (0:04:36)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 289.5s
```

A confirming re-run after the last edit in this tree (a documentation edit —
this section) was identical: **PASS, 6780 passed**, `<scratchpad>/r17/
gate_confirm.txt`. Baseline entering the card was 6732; the delta is exactly the
48 tests this card adds (24 + 21 + 3), and nothing was removed.

The first gate run of this card was **RED**, and honestly:
`tests/test_realtime_ingress.py::test_the_spoken_phrase_exists_exactly_once_in
_the_source_tree` failed because a docstring I wrote in `realtime/config.py`
quoted the spoken emergency phrase while narrating live_run_1's ASR failures.
That test exists because U33 cost a stop that stopped nothing when a grammar had
three copies of the phrase. The docstring was rewritten to name the phrase
indirectly (and to say why), and the same wording was removed from the
`configs/realtime.yaml.example` comment for the same reason.

---

## §6 — Seeds — 16, all RED, R9 session-B standard + the R12–R16 bytecode addendum

Harness: `<scratchpad>/r17/seed_r17.py`. One startup snapshot of all four
touchable source files; per seed: repair drift → mutate → **purge every
`__pycache__` under `src/`, `tools/` and `tests/`** → run the named pytest
target → restore in a `finally` → purge again → run a **fresh-interpreter
canary** asserting the behaviour the mutation removed is back → assert the file
is byte-identical. A final whole-tree check closes the run. No test, config or
eval file is ever mutated.

| # | Seeded defect | File | Target test | Result |
| --- | --- | --- | --- | --- |
| S1 | capture is unbounded: the minute cap never fires | `audio_gateway.py` | `test_capture_stops_itself_at_the_cap_and_says_so` | **RED** (1 failed) |
| S2 | the tee BLOCKS the relay: a full queue waits for the disk | `audio_gateway.py` | `test_the_tee_never_slows_the_relay_down` (+1) | **RED** (1 failed, 1 passed) |
| S3 | the tee RAISES into the relay instead of disabling itself | `audio_gateway.py` | `test_a_broken_tee_disables_itself_instead_of_breaking_the_lane` | **RED** (1 failed) |
| S4 | the per-utterance index DRIFTS: segment times stop coming from bytes | `audio_gateway.py` | `test_the_index_tiles_both_files_exactly` (+1) | **RED** (2 failed) |
| S5 | the runner PROCEEDS past an unreleased latch | `run_voice_corpus.py` | `test_the_run_aborts_rather_than_scoring_a_frozen_robot` | **RED** (1 failed) |
| S6 | the runner POSTs to the OWNER's stack without the flag | `run_voice_corpus.py` | `test_the_owner_stack_is_refused_unless_asked_for_in_full` (+1) | **RED** (2 failed) |
| S7 | recordings may be written into the eval tree again | `config.py` | `test_capture_may_never_be_pointed_at_the_eval_tree` (+1) | **RED** (2 failed) |
| S8 | capture defaults ON: a microphone records without being asked | `config.py` | `test_capture_is_off_unless_the_owner_writes_it_down` (+1) | **RED** (1 failed) |
| S9 | the capture block stops being validated: a typo becomes a default | `config.py` | `test_a_typo_in_the_capture_block_is_a_refusal[…]` | **RED** (1 failed, 7 passed) |
| S10 | playback chunks are recorded with their RIFF headers still in them | `audio_gateway.py` | `test_playback_chunks_are_unwrapped_into_one_continuous_stream` (+1) | **RED** (2 failed) |
| S11 | the runtime wires the tee unconditionally (mode audio ⇒ recording) | `runtime.py` | `test_capture_is_not_constructed_unless_the_config_asks_for_it` | **RED** (1 failed) |
| S12 | the doubled repo-relative output prefix is accepted again | `run_voice_corpus.py` | `test_a_doubled_repo_relative_prefix_is_refused` | **RED** (1 failed) |
| S13 | silence scores as a soft verdict instead of a FAIL | `run_voice_corpus.py` | `test_silence_is_a_fail_and_not_a_partial` | **RED** (1 failed) |
| S14 | a fabricated mission stops failing a refusal cell (Narnia passes) | `run_voice_corpus.py` | `test_a_fabricated_mission_fails_a_refusal_cell` | **RED** (1 failed) |
| S15 | the runner invents a PASS for a judgement it cannot make | `run_voice_corpus.py` | `test_a_judgement_about_wording_is_deferred_not_invented` | **RED** (1 failed) |
| S16 | the owner half is never teed (R7's silent-mic defect, in the recorder) | `audio_gateway.py` | `test_the_gateway_records_both_directions_through_the_real_relay` | **RED** (1 failed) |

Full run: `<scratchpad>/r17/seeds_final.txt`, against the FINAL tree, ending:

```
final whole-tree check against the startup snapshot:
  2e074d5e43ecc0f5…  src/parcel_robot/realtime/audio_gateway.py  (ok)
  1c1940420a381627…  src/parcel_robot/realtime/config.py  (ok)
  59179e440fc41835…  src/parcel_robot/runtime.py  (ok)
  be0764cbd34cd1c4…  tools/run_voice_corpus.py  (ok)
  0 file(s) needed a final repair

16/16 seeds RED
```

The card names five seeds. They map to: **capture unbounded** → S1; **the tee
blocks the relay** → S2 (with S3 as the other half of the same law); **the
runner proceeds past an unreleased latch** → S5; **the runner POSTs to the owner
stack without the flag** → S6; **the per-utterance index drifts** → S4 (with the
four hand-drifted indexes in `test_the_verifier_catches_an_index_that_drifts` as
the direct statement of the invariant).

**Two harness rejections are reported rather than hidden:**

1. **S2's first mutation did not fail the test — it hung it.** Replacing the
   drop with `while len(queue) >= max: time.sleep(0.01)` makes the relay wait
   forever, and pytest simply never returned; the harness died on a 900 s
   subprocess timeout with the mutation restored by its `finally` (verified
   byte-identical afterwards). The mutation was replaced with a bounded
   `time.sleep(0.05)` before the drop — which is the same defect, "the tee
   waits for the disk", in a form a test can report — and the harness now names
   a hang as **RED-by-hang** instead of crashing.
2. **S8's first mutation came back GREEN**, and correctly: I had edited the
   docstring above the field rather than the field. A comment is not a defect.
   Replaced with the actual `enabled: bool = False → True` flip; RED.

---

## §7 — Live proof

**The owner's stack was never touched.** `:8765` was up throughout (it is theirs
and it was running the whole time); the only interaction was **read-only GETs**
of `/api/state`. Nothing of theirs was started, stopped, POSTed to or restarted.

**Memory isolation (R5 recipe), verified after teardown.** `configs/robot.yaml`
was COPIED to the scratchpad with `memory.path` repointed at a scratch sqlite and
passed with `--config`; sha256 `f7b57dcd…90d6f1` **byte-identical before and
after** (the same hash R7_STATUS recorded). The scratch DB holds all 208 rows my
sessions produced ("Die Stop!", the bench mission, the release); the owner's
`parcel_memory.sqlite3` contains **none of my corpus** — its newest rows are
its own stack's hourly `[session rollover]` pair at 19:30:08/19:30:10 UTC, which
is the R16-documented behaviour of a live lane, not a write of mine. The owner's
`~/.config/parcel/realtime.yaml` mtime is unchanged (01:28:24, before this
session). The credential was sourced with
`set -a; . ~/.config/parcel/realtime.env; set +a` and never printed, asserted
against or written anywhere.

**No human spoke.** All 50 clips were synthesized with the local piper voice
(`third_party/piper`, 22 050 Hz) from `queries.tsv`, resampled by the runner to
the 24 kHz the session negotiates. Queries 51/52 (Korean, code-switch) were not
synthesizable with an English voice and are `NOT_ATTEMPTED`.

### 7.1 Three sessions, all on my own stacks

| # | Stack | What | Queries | Outcome | Cost |
| --- | --- | --- | --- | --- | --- |
| 1 | `:8823` sock `/tmp/parcel_r17.sock` | smoke: q01/q19/q32/q35 | 4 | 4 PASS; **the latch fired on q32 and was released, and q35 then ran** | `$0.072298` |
| 2 | `:8823` (same session) | **the run of record** — the full corpus, UI-mounted → `evals/20260820/voice_corpus_v1/replay_run_1/` | 52 (50 spoken) | 10 PASS / 15 PARTIAL / 16 FAIL / 9 NEEDS_REVIEW / 2 NOT_ATTEMPTED; **3 latches asserted and released, `latched_at_end: false`** | `$0.853421` |
| 3 | `:8824` sock `/tmp/parcel_r17b.sock` | confirmation on the FINAL tree, then `kill -9` | 2 | 2 PASS; latch fired and released; index survived the kill | `$0.031511` |
| | | | | **total** | **`$0.957230`** |

The MuJoCo window and the panel were live for all three; the panel was served on
its own port and the sim on its own socket, so nothing of the owner's was shared
but the display.

### 7.2 The tee, measured against the gateway's own counters

From `replay_run_1/state.json` at teardown of session 2:

```
gateway  frames_in  6807   bytes_in  6506204     frames_out 2040   bytes_out 23189760
capture  owner_bytes      6506204               robot_bytes       23100000
         owner_segments        54               robot_segments          80
         frames_dropped_queue_full 0   frames_dropped_after_stop 0   writer_errors 0
gateway  frames_dropped_backpressure 0   frames_dropped_no_client 0   control_errors 0
         played_acks 2034   stale_acks 6   utterances 80   interrupts 0
```

Two numbers are the whole proof:

* **`bytes_in − owner_bytes = 0`.** Every microphone byte the lane was given is
  in `owner.wav`. Not "approximately"; exactly.
* **`bytes_out − robot_bytes = 89 760 = 44 × 2040`** — precisely one 44-byte
  RIFF header per playback chunk, which is what `pcm_from_playback_chunk`
  strips. The recording is one continuous stream, and `wave` opens it:
  `1ch 16bit 24000 Hz, 11 550 000 frames = 481.25 s`. `owner.wav` reads back as
  `3 253 102 frames = 135.55 s`.

Zero drops, zero writer errors, zero backpressure — with the tee running for
18 minutes alongside a live conversation.

### 7.3 The killed-process probe

Session 3's stack was `kill -9`'d mid-session; `index.json` was present and the
verifier reported the shortfall precisely. Repeated at the process level with a
standalone streamer SIGKILLed after 4 s:

```
SIGKILL'd mid-stream. index.json present: True
owner: 192960 bytes | robot: 192960 bytes
verify: ['owner: owner.wav holds 240000 payload bytes, index says 192960',
         'robot: robot.wav holds 240000 payload bytes, index says 192960']
```

47 040 bytes = **0.98 s**, which is the one-second flush interval doing exactly
what it says. The audio is all there; the index lags by at most a second, and
the verifier names the number instead of leaving a reader to guess.

### 7.4 A turn cut out of the recording as a fixture, by byte range

From session 3's index, owner segment #1 `[103124:193430]` → a standalone
1.88 s WAV containing that single spoken query. That is the card's "single turns
are extractable as fixtures", executed rather than asserted.

### 7.5 What the run of record found (product, not harness)

Details and the full addendum are in
`evals/20260820/voice_corpus_v1/replay_run_1/README.md`. In short:

1. **q01–q29 are the scoreable part.** `nav-direct` swept 5/5 PASS with real
   missions; `nav-indirect` 2 PASS / 2 PARTIAL.
2. **The hosted lane went silent at q30** and returned nothing at all for the
   remaining 21 queries — `stalls 5 · reconnects 5 · voice_turns_owed 70 ·
   server_errors 2`, including `conversation_already_has_active_response`. The
   sixteen FAILs and four PARTIALs after q30 describe the lane's health, not the
   product's behaviour, and are labelled as such in the run's README. **This is
   a candidate card**: the lane degrades over a long sequential session and
   stops answering.
3. **The emergency stop still worked while the lane was dead.** All three
   `estop-pos` queries latched — locally, pre-cloud — on a session that was
   returning nothing at all. That is R9's local-first ordering earning its
   design under exactly the conditions where a cloud-dependent stop would have
   failed, and it is the strongest single result in the run.
4. **A latched robot does not just stay quiet — it contradicts itself.** In
   session 3, one second after the latch fired, the model said out loud: *"There's
   no 'stop' command in the tools, so we're still moving."* live_run_1's
   candidate card (i) "speak the latch at the moment it fires" now has field
   evidence that silence is not the worst case.
5. **Tool-narration suppression reproduced.** `tool_beats_requested 33 /
   suppressed 7` in the first half; gesture and status queries repeatedly
   produced a reply with no tool ("talks about it, does not do it"), which is
   live_run_1's §2 in a different corpus.

---

## §8 — OWNS compliance

| Path | In OWNS? | Status |
| --- | --- | --- |
| `src/parcel_robot/realtime/audio_gateway.py` | yes (tee only) | tee added; **no existing behaviour changed** — the four call-sites add a call and nothing else, and `capture=None` (the default) leaves every audio path byte-for-byte what R7 shipped |
| `src/parcel_robot/realtime/config.py` | yes (additive keys) | one new nested block, one new dataclass, two new functions; no existing key's parsing changed |
| `tools/run_voice_corpus.py` | yes (NEW) | new file |
| `configs/realtime.yaml.example` | yes | appended block only |
| tests | yes | 2 new files, 3 tests appended to the R7 file |
| `scrum/20260820/task_6/R17_STATUS.md` | yes | this file |
| `src/parcel_robot/runtime.py` | **no** | one conditional wiring block — declared deviation §9.1 |
| `evals/20260820/voice_corpus_v1/replay_run_1/` | permitted ("runner OUTPUT goes to new run folders only") | new folder; **no existing eval fixture was read-modified** — `queries.tsv` was copied to the scratchpad, never edited |
| lane / protocol / ingress / broker / whisperer / prompting | MUST NOT TOUCH | untouched |
| owner's config, DB, processes | MUST NOT TOUCH | untouched — §7 |

Nothing was committed, staged or stashed. `git status` shows this card's files
alongside the pre-existing uncommitted wave described in `PLAN.md` item B.

---

## §9 — Deviations

1. **One block in `runtime.py`, which is not in OWNS.** The loader owns the
   schema and the gateway owns the tee, and there is no third place where they
   can meet: without the wiring the feature is unreachable and the card's item 1
   cannot be satisfied. The block is conditional on `capture.enabled`, is
   guarded with `getattr` so a config without the attribute is unaffected, and
   is pinned in both directions by tests (S8/S11). Precedent: AUDIT_R12_R16
   accepted R12's extension into executive code for the same kind of reason.
2. **The config key is `capture.enabled`, not the card's literal
   `capture_audio: true`.** The feature needs a directory, a cap and a
   segmentation threshold as well as a switch, and three loose top-level keys
   (`capture_audio` / `capture_dir` / `capture_max_minutes`) would not be a
   "block family" — the card's own words. `capture:` is a sibling of
   `whisperer:` with identical refusal discipline, and `capture.enabled: true`
   is the switch the card asked for.
3. **A sixth verdict, `NEEDS_REVIEW`, extends live_run_1's five.** A program
   cannot grade "warm in-character reply", and a program that pretends it can
   produces a scoreboard nobody should trust. The other five verdicts and every
   top-level key of `results.json` are unchanged, so one reader reads both runs;
   `NEEDS_REVIEW` is explained in the generated README and in `scored_by`.
4. **`--silence-abort` is a scope extension** (§4.1). It was not in the card. It
   was added because the card's own live proof produced twenty worthless
   verdicts for the same structural reason the card's item 3 exists, and because
   the fix is fifteen lines and two tests. **The run of record predates it**,
   which is precisely why that run ran to the end.
5. **The replay used synthesized speech.** Card item 4 is conditional on the
   owner recording the corpus with `record.sh`; they have not, and a captured
   session could not yield per-utterance owner audio before the tee existed.
   Piper was the only way to prove the runner live today. This is the largest
   `does_not_prove` in this card and is stated as one below.
6. **Spend is `$0.957`, which is under the $1.50 cap but not "well under".**
   The corpus is 52 queries and a paced UI-mounted replay bills roughly $0.012–
   0.018 per turn; a shorter run would have been cheaper and would not have been
   the card's deliverable. Reported rather than rounded.

---

## §10 — does_not_prove

1. **This is not the owner's voice, and nothing here says anything about ASR.**
   Accent, prosody, room, code-switching, the reSpeaker array — none of it is
   exercised. Every ASR-shaped finding in live_run_1 (F1's Korean sign-off, F6's
   missed emergency phrase, q47's shredded utterance) remains exactly as open as
   it was. The corpus replay proves the *harness*, not the transcription.
2. **The corpus WAVs the card is ultimately for still do not exist.** Until the
   owner runs `record.sh`, `voice_corpus_v1` has a `queries.tsv` and no audio.
3. **Twenty-one verdicts in the run of record are about a dead lane.** They are
   labelled, but they are still in the totals; the honest scoreboard for the
   product is q01–q29.
4. **The tee has never run for 30 minutes.** The cap is proven with a
   one-second cap in a unit test and the longest live capture was 18 minutes.
   Disk-full behaviour is not tested at all — the writer thread would raise,
   count and disable, which is the designed answer, but it has not been observed.
5. **`played` acks are sent but barge-in truncation is still unproven live.**
   `interrupts 0` across all three sessions: nothing ever barged in, because the
   runner speaks one query at a time by design. The ack path is exercised (2034
   acks, 6 stale); the truncation arithmetic it feeds is not.
6. **No human has watched the UI mount.** The panel and MuJoCo window were live
   and the run is paced for a viewer, but the viewer was a process. The owner
   watching their dog run the corpus is theirs to trigger.
7. **The index's crash-tolerance is bounded, not absolute.** A killed process
   can leave up to one second of audio unindexed. The verifier reports it; the
   WAV still contains it.
8. **`verify_capture_index` is not run automatically anywhere in production.**
   It is exported and used by tests and by hand; nothing calls it at session
   close.

---

## §11 — Open risks and handoffs

1. **`recordings/` is not in `.gitignore`** (that file is not in OWNS). If the
   owner enables capture with the default `dir: recordings`, household audio
   lands at the repo root and `git add -A` would stage it. **Owner-gated:** add
   `recordings/` to `.gitignore`, or set `capture.dir` to a path outside the
   repo. This is the single highest-value one-line follow-up in this card.
2. **The lane goes silent under a long sequential session.** Reproduced twice
   (live_run_1's stall/reconnect pattern, and q30–q50 here with
   `voice_turns_owed 70` and `conversation_already_has_active_response`).
   Candidate card; `--silence-abort` only stops the harness from lying about it.
3. **A latched robot contradicts itself out loud** (§7.5.4). Strengthens
   live_run_1's candidate card (i) "speak the latch when it fires" — it is not
   just silence, it is a wrong statement.
4. **Nothing prunes recordings.** The cap bounds one session; a stack left with
   capture on accumulates one folder per gateway start forever. Retention is a
   policy decision for the owner, not a default this card should have picked.
5. **The `estop-neg` set is still only half-measured**, exactly as live_run_1
   said: all four negatives here landed while the lane was silent, so they are
   PARTIAL ("no latch, but no reply either") rather than the affirmative proof
   the smoke run got for q35. The negatives want a run of their own, spoken
   before the positives, on a healthy lane.
6. **`--i-am-the-owner` is a flag, not an authorisation.** It stops an accident;
   it cannot stop an intent. The owner's stack remains protected by convention
   plus this tripwire, and by nothing else.
