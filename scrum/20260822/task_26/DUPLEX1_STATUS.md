# DUPLEX-1 — "mm-hmm" survives (task_26)

**Executor:** Claude Opus · **Verifier:** Fable · **Card:** `README.md` ·
**Board:** `../TASK_BOARD.md` (P0 standing rules) · **Design:**
`../WAVE2_DESIGN_FABLE.md` §3 · Date 2026-08-22.

**Pre-registration:** `PREREGISTRATION.md`,
sha256 `4bce407811f15917f870418f06b63acec95e8f3cf07150be18084de68d0fbbae`,
written before any number below was measured. It fixed seven rows, the ten
acknowledgement tokens they are measured on, and — the part that matters — the
**decision rule** for picking the shipped floor, so the value could not be
chosen after seeing the table.

## Headline

A local turn controller (LISTEN / THINK / SPEAK / OVERLAP / YIELD) now sits
between server VAD and MARK-1's backchannel floor, and the reply **ducks
instead of dying**: on the pre-registered R7 rig, with TURN-1's two
prerequisites set together, **10/10 acknowledgement tokens survive** at a
700 ms floor (MARK-1 measured 0.38 over its own matrix), **0/10 survive** if
`interrupt_response` is left at the provider's default, and **4/10** if the
silence tail is left at ~500 ms — so both prerequisites are shown to be
prerequisites, not neighbouring niceties. The pre-registered **cancel ≤ 450 ms
row is a MISS** at that floor (p95 **740 ms**) and is recorded as one: a
time-only floor that protects a 380 ms "mm-hmm yeah" cannot also cancel in
450 ms. What makes 740 ms livable is the other half — **the reply is quiet
within one control frame of the onset** (lane overhead p95 **40 ms** at every
socket lag from 0 to 350 ms), so the floor is spent with the dog silent *under*
the owner rather than talking over them.

Also landed: MARK-1's two open handoffs (**H-7** the interrupt-onset stamp,
**H-4(c)** a survived backchannel no longer leaves a turn owed), and
**RT-TURNS-1** — a per-turn export with a wall stamp, which gives one of
AIR-1's two producerless rows a producer and says plainly why it cannot give
the other one.

**Three things ship OFF and are named here rather than buried:** the floor
(no config key exists — MARK-1 shipped it as a lane constructor argument and
`config.py` is TURN-1's), the prototype `turn_detection:` block (TURN-1's
landed guard pins it commented until the owner records), and the whisperer's
`initiative_allowed` gate (`whisperer.py` is outside this card's OWNS). Each
is one line, and each line is written out below.

## What changed

`git diff --stat` on this card's OWNS. `runtime.py` is shared with VENUE-1 and
CAP-1 today; the number quoted for it is **this card's region only**, measured
by its markers, not the file's total.

| File | Lines | What |
|---|---|---|
| `src/parcel_robot/duplex/turn_controller.py` | **534** (new file) | the state machine: five states, DUCK / RESUME / COMMIT, `initiative_allowed`, the owed-turn ledger |
| `src/parcel_robot/realtime/lane.py` | +314 / −2 | one marked region (`_apply_turn_action`, `initiative_allowed`) plus marked call sites in `_on_speech_started`, `_resolve_barge_in_hold`, `_commit_barge_in`, `_begin_response`, `_on_response_done`, `_arm_voice_turn`, and the two socket-lifetime resets beside MARK-1's hold reset |
| `src/parcel_robot/realtime/audio_gateway.py` | +125 / −7 | the `duck` control frame + counters; `onset_ago_s` threaded to `mark_interrupted` |
| `src/parcel_robot/realtime/browser_sink.py` | +76 / −2 | `duck()`, `accepts_interrupt_onset`, `interrupt(onset_ago_s=…)` |
| `src/parcel_robot/ui/index.html` | +97 / −1 | playback `GainNode`, `duckGainFor` / `applyDuck` / `resetDuck`, the `duck` frame |
| `src/parcel_robot/runtime.py` | **+141**, one region | RT-TURNS-1: `realtime_turn_rows()`, `export_realtime_turns()`, `_realtime_capture_dir()` |
| `configs/realtime.prototype.yaml.example` | +69 / −25 | the measured `turn_detection` recommendation with its numbers (commented — see D-a) |
| `tests/test_duplex1_rows.py` | 1 024 (new file) | D-1 … D-7 on the product lane |
| `tests/test_duplex1_turn_controller.py` | 482 (new file) | the pure machine + the onset stamp through the real capture index |
| `tests/test_duplex1_panel_duck.py` | 307 (new file) | the panel's own functions, evaluated in **gjs** |
| `tests/test_duplex1_rt_turns.py` | 267 (new file) | RT-TURNS-1 through a real `RobotRuntime`, read back by AIR-1's own scorer |
| `scrum/20260822/task_26/evidence/` | 3 files | the committed seeded-RED transcript + harness, and the two owner-gated readers (correction pass) |

### The design decisions worth arguing with

1. **One decider, not two.** MARK-1's `_BargeInHold` keeps every commit
   decision it already owned. The controller owns only what the hold has no
   opinion about: the gain while the floor runs, and whether the robot may
   speak unprompted. `_apply_turn_action` *ignores* a COMMIT from the
   controller by construction, and a test asserts the two counts are equal on
   every arm — if they ever diverge, two objects are racing over one socket.
2. **The duck is a gain, not a stop.** Nothing is discarded, the provider is
   told nothing, and MARK-1's played clock keeps running. The owner really did
   hear that audio, quietly, and the truncate mark still has to say so — a
   duck that reset the anchor would reintroduce the exact defect MARK-1 exists
   to remove. Pinned by `test_ducking_does_not_move_the_played_clock_or_the_mark`.
3. **`onset_ago_s` is a duration, not a timestamp.** The lane runs on
   `time.monotonic`; the capture index is stamped from the wall clock the tee's
   relay thread reads. "How long before now" is the one shape that cannot be
   read on the wrong clock.
4. **Feature detection, not a swallowed `TypeError`.** `BrowserSink` advertises
   `accepts_interrupt_onset`; `DiscardSink` and `voice_audio.SpeakerSink` are
   called exactly as before. A `TypeError` caught around a barge-in would be
   the same bug with a longer stack trace.
5. **`was_robot` is `null`, never `false`.** See D-c.
6. **The state machine belongs to the socket, and the owed turn belongs to the
   lane.** MARK-1's correction pass made a provisional hold die with its
   socket; a controller left in SPEAK or OVERLAP by a hang-up would refuse
   every unprompted remark for the rest of the process, so it is reset in the
   same two places — with `keep_owed=False`, **mirroring** the lane's own
   `_voice_turn_owed = False` four lines below rather than disagreeing with it.
   The drop is counted (`owed_turns_abandoned`) instead of being silent.
7. **The duck gain is 0.18, and that is taste.** Not zero: silence is
   indistinguishable from a dropped connection, and a backchannel that resolves
   inside the floor has to come back without a click. AIR-1's handoff says the
   right source for this number is `signal_to_echo_db` from its double-talk
   leg — owner-gated, so this is declared as taste rather than measured.

## How verified

Environment: `.parcel/bin/python` 3.14.4, `.parcel/bin/ruff` 0.16.1, `TMPDIR`
unset. The rig is offline (`FakeRealtimeServer`); **hosted spend $0.00** — no
socket to any provider is opened by anything in this card.

**No simulator, port or unix socket was ever opened by this card.** The "R7
rig" is entirely in-process (`transport_pair()` + a fake clock), so there is no
process to stop at the end and nothing that could have collided with the
owner's live stack on `:8765` / `/tmp/parcel_sim.sock` or with MOVE-1's patrol
sim. `scripts/ci_gate.py` was never run; git was read-only throughout; the
owner's `parcel_memory.sqlite3` was never opened (every test store is a
`tmp_path` scratch file).

### 0. The rig, and what makes it a product-path rig

`FakeRealtimeServer` → `RealtimeLane` → `BrowserSink` → `BrowserAudioGateway`
→ a headless port of `ui/index.html`'s playback path. It is MARK-1's rig
(`tests/test_mark1_barge_in_mark.py`) **imported, not forked** — same fixtures,
same clock, and in particular the same referee, `_AudioContext.rendered_ms()`,
which is computed from the scheduled buffers and is never a number under test.
`test_duplex1_rows.py` adds the panel's new `GainNode` and two stopwatches.

No monkeypatch of `played_ms`, `turn_timings`, the gateway's clamps or the
lane's hold. The only object the tests construct that the product does not is a
browser, which is the one piece of the loop that does not exist on this host —
and the JS it stands in for is evaluated separately in gjs (§4).

### 1. The pre-registered rows

```
.parcel/bin/python -m pytest tests/test_duplex1_rows.py -q -s
```

| Row | Bar | Measured | Verdict |
|---|---|---|---|
| **D-1** duck latency (lane saw onset → panel gain < 1), p95, nominal socket | ≤ 100 ms | **0.0 ms** — and 0.0 is an *identity* of a fake transport with no delay | **met, and worth almost nothing on its own** |
| **D-1 ladder** lane overhead (`quiet − socket lag`) p95 at lags 0/20/50/100/350 ms | — (added before measuring) | **0 / 40 / 40 / 40 / 40 ms**, max 40 ms | the row that is not free |
| **D-1b** time to quiet at a 350 ms socket lag | reported | p50 370 / p95 390 ms | reported |
| **D-2** cancel latency (onset → `conversation.item.truncate`), p95, shipped floor | ≤ 450 ms | **740 ms** (p50 730, max 740) | **MISS — declared, bar not moved** |
| **D-2 alt** the same at a 350 ms floor | — | cancel p95 **390 ms**, survival **2/10** | meets D-2, misses D-3 |
| **D-2b** time to quiet at the shipped floor, p95 | ≤ 100 ms | **0.0 ms** nominal; **lag + 40 ms** on the ladder | met (same caveat as D-1) |
| **D-3** backchannel survival over the ten pre-registered tokens | ≥ 0.9 | **10/10 = 1.00** | **met** |
| **D-4** proactive collisions | 0 | **0** over 70 samples of a live barge-in; 70 refusals, and a positive grant on the idle arm | **met** |
| **D-5** owed turns dropped by a state transition / holds left open | 0 / 0 | **0 / 0** over 40 runs | **met** |
| **D-6** the arms without the prerequisites | reported | tail 500 ms → **4/10**; `interrupt_response: true` → **0/10** | reported |
| **D-7** floor 0 is byte-identical to MARK-1's | identical | frames identical, truncates identical, 0 duck frames | **met** |

The floor ladder, run under the pre-registered decision rule (smallest floor
whose survival reaches 0.9), with `silence_duration_ms: 200`:

```
[DUPLEX-1 D-3] the floor ladder (silence_duration_ms = 200)
    floor=     0 ms  survival= 0/10 (0.00)
    floor=   250 ms  survival= 0/10 (0.00)
    floor=   350 ms  survival= 2/10 (0.20)
    floor=   450 ms  survival= 6/10 (0.60)
    floor=   700 ms  survival=10/10 (1.00)
    floor=  1000 ms  survival=10/10 (1.00)
    decision rule picks: 700.0 ms
```

*(Re-pasted from `pytest tests/test_duplex1_rows.py -k d3 -s` on the corrected
tree — the correction pass's finding 2 moved two boundary cells, 250 ms from
1/10 to 0/10 and 450 ms from 5/10 to 6/10, and both moved TOWARDS the
arithmetic: a burst of 120 ms plus a 200 ms tail is 320 ms and never did
survive a 250 ms floor. The chosen floor and D-3 are unchanged.)*

**Read D-2 and D-2b together or neither of them means anything.** A floor is
the only local evidence available that a noise was a turn and not a
backchannel — the hosted lane delivers the owner's transcript *after* the turn,
so there is no content word to cut the argument short, and server VAD's
"they stopped" arrives a tail late by construction. At 350 ms the dog cancels
fast and interrupts you for saying "okay". At 700 ms it survives every token in
§2 and takes 740 ms to yield. The duck is what pays for that 740 ms.

### 2. Seeded RED — one per new guard

Each: seed the **product** (never the test), watch the named test fail, restore
the exact bytes, verify **sha256 identical**, purge `__pycache__`, re-run green.
Harness **and transcript are committed with the card** (correction pass, note):
`evidence/seed_red.py`, `evidence/SEEDED_RED.txt`. The table below is S1–S14
from the first pass; S15–S20 are the correction pass's and are listed in its
section. **All twenty are in the committed transcript**, which is the file to
re-run rather than to trust.

| # | Guard | Product seed | Named test | Result |
|---|---|---|---|---|
| S1 | the duck is asked for at all | `lane._on_speech_started`: drop `_apply_turn_action(...)` | `test_duplex1_d1_the_reply_goes_quiet_within_100ms_of_the_onset` | RED → GREEN |
| S2 | the reply comes back up after a backchannel | `lane._resolve_barge_in_hold`: drop the RESUME apply | `test_a_surviving_backchannel_ducks_and_then_comes_back_up` | RED → GREEN |
| S3 | a "mm-hmm" does not leave a turn owed (**MARK-1 H-4c**) | `lane._resolve_barge_in_hold`: `if False:` on the retraction | `test_a_survived_backchannel_does_not_leave_a_turn_owed` | RED → GREEN |
| S4 | the onset reaches the capture index (**MARK-1 H-7**) | `SessionAudioCapture.mark_interrupted`: rename `interrupted_onset_at` | `test_the_cut_now_carries_the_onset_and_not_only_the_commit` | RED → GREEN |
| S5 | a duck with no reply to attenuate is refused | `gateway.duck`: drop the `seq <= 0` half of the guard | `test_the_gateway_refuses_a_duck_with_no_reply_to_attenuate` | RED → GREEN |
| S6 | every playback source goes through the gain node | `index.html`: restore `source.connect(mic.playback.destination)` | `test_every_playback_source_goes_through_the_gain_node` | RED → GREEN |
| S7 | a stale duck cannot attenuate the next reply | `index.html duckGainFor`: `if (false) return null;` | `test_a_duck_for_another_utterance_is_refused_by_the_panel` (**gjs**) | RED → GREEN |
| S8 | `stop` puts the panel's gain back to unity | `index.html stopPlayback`: drop `resetDuck(mic)` | `test_the_gain_returns_to_unity_on_both_frames_that_end_an_utterance` | RED → GREEN |
| S9 | initiative is refused while anyone holds the floor | `TurnController.initiative_allowed`: `allowed = True` | `test_duplex1_d4_initiative_is_refused_whenever_anyone_holds_the_floor` | RED → GREEN |
| S10 | an owed turn survives every transition | `TurnController._enter`: clear `_owed` on transition | `test_an_owed_turn_survives_every_state_transition` | RED → GREEN |
| S11 | one overlap per reply (a second VAD start must not re-arm the floor) | `TurnController.note_owner_started`: `if False:` on the guard | `test_a_second_vad_start_inside_one_burst_does_not_rearm_the_deadline` | RED → GREEN |
| S12 | RT-TURNS-1 stamps a WALL clock | `runtime.realtime_turn_rows`: `wall = monotonic_s` | `test_every_ledger_row_becomes_one_turn_row_with_a_wall_stamp` | RED → GREEN |
| S13 | `was_robot` is null, never a vacuous false | `runtime.realtime_turn_rows`: `"was_robot": False` | `test_was_robot_is_null_and_says_why_rather_than_claiming_false` | RED → GREEN |
| S14 | the state machine does not outlive its socket | `lane`: drop `turn_controller.reset(keep_owed=False)` (both sites) | `test_the_state_machine_does_not_survive_the_hang_up_that_ends_its_reply` | RED → GREEN |

**20/20 behaved** on the final run (14 here plus the correction pass's six),
and every restore was verified byte-identical by sha256
before the green re-run — `lane.py` `dcc4b40452c0…`, `audio_gateway.py`
`be18b8134c8f…`, `index.html` `85106d4e6e7a…`, `turn_controller.py`
`675498258e50…`, `runtime.py` `34969c847382…` — superseded by the shas in
`evidence/SEEDED_RED.txt`, which is the run that ships (the files moved under
the correction pass, and under peers editing `runtime.py`).

One honest caveat about that sha check: it proves **I** restored what **I**
read, not that nobody else wrote the file. `runtime.py`'s sha differs between
this run and an earlier one (`5511cf47001d…` → `34969c847382…`) because
VENUE-1 or CAP-1 committed to their own regions in between — visible, expected,
and the reason each seed window is one targeted test long. See D-f.

### 3. RT-TURNS-1, through a real runtime

```
.parcel/bin/python -m pytest tests/test_duplex1_rt_turns.py -q      # 8 passed
```

A real `RobotRuntime` (scratch store, hosted lane in text mode), rows written
through the **product ledger door** `_write_realtime_ledger`, then exported and
handed to `tools/bargein_through_air.py::score_turns` — AIR-1's own scorer,
loaded from the file. `owner_turns` comes back correct. `robot_as_owner` comes
back 0, and the test asserts that number **while saying it is not a number this
card claims** — see D-c.

### 4. The panel, in a real JS engine

```
.parcel/bin/python -m pytest tests/test_duplex1_panel_duck.py -q    # 9 passed
```

`/usr/bin/gjs` (SpiderMonkey) exists on this host — MARK-1's correction pass
established that after "no JS engine here" turned out to be false and a
string-matched test shipped a blocker. So `duckGainFor` is **lifted out of
`index.html` verbatim** and evaluated against duck frames minted by the real
`BrowserAudioGateway`: the live frame gives 0.18, a frame for another utterance
gives `null`, and a panel with no gain node gives `null`. The whole 2 900-line
script still parses under `new Function`.

> **CORRECTED — this paragraph originally claimed the ToNumber family was
> refused, and the shipped panel admitted all of it as a silent mute.** The
> claim was false when written and the test that was supposed to back it could
> not fail. Both are fixed in the correction pass, finding 1 below; the
> assertions above are the post-correction ones.

### 5. Regression surface

```
.parcel/bin/python -m pytest tests/test_duplex1_*.py tests/test_mark1_*.py \
    tests/test_turn1_endpointing.py tests/test_air1_*.py tests/test_duplex_*.py -q
    -> 293 passed, 1 skipped     (73 of them new: 24 + 26 + 15 + 8)

.parcel/bin/python -m pytest tests/ -k "realtime or runtime or gateway or capture \
    or browser or ci_gate or prototype" -q
    -> 2336 passed, 2 skipped, 2 xfailed
```

MARK-1's 43 and TURN-1's 73 are green **unchanged** — no test of either card
was edited (see D-a for the one place that mattered).

### 6. Ruff — nothing from this card enters the ratchet

```
.parcel/bin/ruff check src/parcel_robot/duplex/turn_controller.py \
    src/parcel_robot/realtime/lane.py src/parcel_robot/realtime/browser_sink.py \
    src/parcel_robot/realtime/audio_gateway.py src/parcel_robot/runtime.py \
    tests/test_duplex1_rows.py tests/test_duplex1_turn_controller.py \
    tests/test_duplex1_panel_duck.py tests/test_duplex1_rt_turns.py
    -> All checks passed!
```

**No `noqa` was added by this card.** Three broad `except Exception` handlers
were written first (the `lane.py` firewall convention) and then narrowed to
explicit tuples so no suppression is needed — `_apply_turn_action` catches
`(AttributeError, OSError, RuntimeError, TypeError, ValueError)` and says on
the line why narrow is safe there (R22's firewall in `_dispatch` is already
outside the call). Seven findings in the new test files were fixed rather than
silenced: an import block, two `ISC004`, an `S110` (now `contextlib.suppress`),
two `B018`, and the `RUF100` that the first fix made unnecessary.

A tree-wide `ruff check .` today reports 34 findings, not 7, and **none of them
are in a DUPLEX-1 file**. All seven `scripts/ci_ruff_baseline.json`
fingerprints are present and unchanged (`camera_channel/` ×4,
`detection_adapter/` ×3); every extra sits in
`scrum/20260822/task_18/evidence/*.py` — NM-1/ASK-1's in-flight evidence
scripts. Named here so the verifier does not attribute them to this card. The
baseline file itself is untouched: no re-pin.

## What this does not prove

1. **Not one acoustic number.** There is no microphone, no loudspeaker and no
   acoustic path on this host. Nothing here is evidence about Chrome's AEC3,
   the XVF3800's on-chip AEC, echo, or whether a real "mm-hmm" through air is
   even detected as speech. Every such row is owner-gated below.
2. **The ten burst durations are stand-ins**, fixed in the pre-registration
   with their provenance stated: there is no backchannel corpus on this host.
   If real acknowledgements are longer than 380 ms, the floor the decision rule
   picks moves and D-2 gets worse. OG-3.
3. **D-1 and D-2b are 0.0 ms because the fake transport has no delay.** They
   clear their bars trivially. The ladder is the honest measurement and it says
   the lane adds ≤ 40 ms on top of whatever the socket costs.
4. **The 40 ms is quantisation, not physics.** It is one 20 Hz pump plus one
   drain tick of the harness. A real browser adds a `setTargetAtTime` ramp
   (`DUCK_RAMP_S = 20 ms`) that nothing here models.
5. **The local endpointer does not exist.** The card's design wants offsets
   from Silero on ch1, which would decouple survival from the VAD tail
   entirely. `TurnEndpointer` is wired to the LOCAL voice pipeline, not to the
   hosted lane's gateway. Every offset measured here is server VAD's, tail
   included. The seam is `lane.note_owner_speech_stopped()` and it is one call
   wide; the producer is not built.
6. **`note_owner_words` has no product caller.** The hosted lane delivers the
   owner's transcript after the turn, so no partial transcript reaches the
   controller. It is tested so the machine has a defined answer when a producer
   arrives; it is not wiring.
7. **`consult_initiative` has no product caller** (D-b). It is measured on the
   controller and on the lane; the whisperer does not knock on it yet.
   `initiative_allowed` beside it is a pure read and moves no counter
   (correction pass, note).
8. **The shipped default is still floor 0.** Everything measured at 700 ms
   here is measured with the knob passed explicitly. D-d.
9. **No soak of one hour.** D-5 is 40 barge-ins across four arrival fixtures
   and both outcomes — the transitions a soak would exercise, not the wall
   clock. A deadlock that needs an hour of drift to appear would not be caught.
10. **The controller's thread-safety is by construction, not by test.** One
    `RLock`, held only across bookkeeping; nothing here runs it from two
    threads at once.

## Deviations from OWNS / the card (declared)

* **D-a — the prototype `turn_detection:` block ships COMMENTED, against the
  dispatch's instruction to ship the keys set.** I wrote it live first and
  `tests/test_turn1_endpointing.py::test_the_shipped_examples_have_no_live_turn_detection_key`
  went RED: TURN-1 landed a guard that both examples must carry no live
  `turn_detection` key, because the TYPE decision is pre-registered to come
  from a recording of the owner's voice that does not exist yet. That test is
  TURN-1's, not mine, and weakening another card's landed guard to make my own
  instruction fit is exactly the move the standing rules forbid. So the block
  ships commented **with its measurements attached** and a one-line
  "uncomment this pair together". Both TURN-1 assertions are green again.
  **RULED (Fable, verification of this card): obeying TURN-1's guard over the
  dispatch was correct. The block stays COMMENTED this wave** — the type
  decision belongs to a measurement on the owner's recording, which does not
  exist yet. This is settled, not open.
  Note for whoever eventually uncomments it: **TWO pins break, not one.**
  `test_the_shipped_examples_have_no_live_turn_detection_key` is the obvious
  one; TURN-1's payload-identity pin is the other — it loads every shipped
  config and asserts the `session.update` payload is byte-identical to the
  no-key default, and a live block in either example changes that payload by
  construction. Both are TURN-1's to carve out.
* **D-b — `whisperer.py` was not touched.** The card's work item 2 asks for
  `whisperer.offer` gated on `initiative_allowed`; the dispatch's OWNS list
  does not include `whisperer.py`, and CURIO-1's chatter scheduler lives there.
  The gate is built, counted and measured; the seam is one condition at the top
  of `Whisperer.offer`. Handoff DX-2.
* **D-c — `was_robot` is `null` and AIR-1's second row is still not
  measurable.** The runtime cannot decide whether a turn credited to the owner
  was really the robot arriving back through the microphone: an owner turn
  overlapping robot playback is what a barge-in IS, so "the robot was speaking"
  is not evidence, and the separation is acoustic. Emitting `false` would make
  AIR-1's 0/20 row pass for the same vacuous reason its own verification caught
  in `hosted_spend_usd`. `score_turns` reads a missing/`None` `was_robot` as
  false and will therefore *report* 0 — that is a defect in the join, filed as
  handoff DX-4, not a row I claim.
* **D-d — no config key for `backchannel_floor_ms`, so it still ships off.**
  MARK-1 shipped it as a lane constructor argument; a key would be an edit
  inside TURN-1's `config.py`, which the card's MUST-NOT-TOUCH names. Turning
  it on is one line where the runtime builds the lane
  (`RealtimeLane(..., backchannel_floor_ms=700.0)`). Handoff DX-1.
* **D-e — MARK-1's and TURN-1's lane code was edited, declared here as the
  dispatch requires.** MARK-1's regions in `lane.py` are single comment lines,
  not fenced blocks, and this card's seams are inside them by necessity. Eight
  sites: `_on_speech_started` (+3 marked inserts), `_resolve_barge_in_hold`
  (+3), `_commit_barge_in` (the `sink.interrupt()` call and the onset reset),
  `_begin_response` (+1), `_on_response_done` (+1), `_arm_voice_turn` (+1), and
  the two socket-lifetime resets that sit directly under MARK-1's "a
  provisional barge-in belongs to a socket" comment in `_connect()` and
  `close()`.
  **No TURN-1 hunk at all** — its `# CARD TURN-1 — MARKED REGION` blocks are
  byte-identical, and `protocol.py` and `config.py` are untouched. In
  `audio_gateway.py` MARK-1's `mark_interrupted` gained an optional keyword and
  its `_drain` branch one argument; the pre-DUPLEX-1 behaviour is pinned by
  `test_without_an_onset_the_index_is_exactly_what_mark1_shipped`.
* **D-h — every file this card touched outside the card README's OWNS,
  declared in one place** (correction pass; three of the four product files
  were previously undeclared). The README's OWNS names
  `duplex/turn_controller.py`, `lane.py`'s barge-in region, `index.html`'s gain
  region, `whisperer.py`, `tests/test_duplex1_*.py` and `task_26/`. Also
  edited, each granted by the dispatch's own OWNS list and each by marked
  region: **`realtime/audio_gateway.py`** (the `duck` frame, the onset stamp —
  MARK-1's file), **`realtime/browser_sink.py`** (the sink half of both — also
  MARK-1's), **`runtime.py`** (one region, RT-TURNS-1 — shared with VENUE-1 and
  CAP-1 today), and **`configs/realtime.prototype.yaml.example`**, which is
  **P0-A's file** from week 1 and was named by the dispatch but not by the card;
  the overlap is real and this is the declaration of it. Nothing was written to
  `whisperer.py` (D-b), `protocol.py`, `realtime/config.py` or the broker.
* **D-f — the seeded-RED harness purges `__pycache__` tree-wide** between runs
  and briefly writes to `lane.py` / `runtime.py` / `audio_gateway.py` /
  `index.html`, which five other executors share. Each window is one targeted
  test (sub-second for all but two), the restore is verified by sha256, and no
  drift was observed. It is still a shared-tree risk and is named rather than
  hidden.
  **Observed once, during the correction pass's wide re-run:** three
  source-pin tests (`test_realtime_pump_survival.py`'s health-loop pin,
  `test_p1b_map_learns.py`, `test_capture_ingest.py`) went RED in one sweep and
  green individually seconds later — a peer was mid-write on `runtime.py` and
  the pins read a partially-written file (my region's first line moved 7321 →
  7332 during that run). Nothing to do with this card; recorded because I saw
  it, and because a verifier sweeping the same selection may see it too.
* **D-g — the card's `--` five rows are not the dispatch's three.** The card
  README pre-registers survival / confirm-cancel / false-interrupt /
  proactive-collision / a 1-h soak; the dispatch narrowed to duck ≤ 100 ms,
  cancel ≤ 450 ms, survival ≥ 0.9 "and report the arms without them too". I
  measured the dispatch's three plus the card's collision and owed-turn rows.
  **The card's "false interrupt ≤ 0.02 on noise fixtures" is NOT measured** —
  it is an acoustic row (AIR-1 owns the noise fixtures and its own 0.02 figure
  is labelled synthetic), and a false-interrupt rate computed from silent PCM
  on a fake server would be a number about the harness. OG-1.

## Owner-gated rows — commands, never claims

Every one of these needs AIR-1's session (the XVF3800 in the loop, the browser
as the ear). **Never play audio through the array and never write a control
command to it** outside AIR-1's own opt-in mux path.

**Correction pass:** the readers below are committed as scripts under
`evidence/` rather than pasted as one-liners. The first version of OG-1 raised
`KeyError` (it reached for lane keys directly under `["realtime"]`; they live
under `["realtime"]["lane"]`) and OG-2/OG-4 pointed at `~/recordings/…`, which
does not exist — `capture.dir` resolves against the **repo root**. These rows
are spent inside a ~1.3 h owner session; a command that needs its key path
debugged at the microphone is a row that does not get measured. Both scripts
were run here against real objects before being written down.

* **OG-1 — does a real "mm-hmm" survive through air?** The row this card is
  named for, and the only one that settles it.
  ```bash
  # ONE-TIME, before the session (two edits, both temporary):
  #  a) arm the floor — D-d's one line, where the runtime builds the lane:
  #        RealtimeLane(..., backchannel_floor_ms=700.0)
  #  b) set BOTH prerequisites in the live realtime.yaml — D-a's block:
  #        turn_detection:
  #          type: server_vad
  #          silence_duration_ms: 200
  #          interrupt_response: false
  #
  # DURING the session: ask a long question, say "mm-hmm" over the reply, ×10.
  # THEN, from the repo root:
  curl -s localhost:8765/api/state \
    | .parcel/bin/python scrum/20260822/task_26/evidence/read_duplex_counters.py
  ```
  Pass: `backchannels_survived / backchannel_holds` ≥ 0.9,
  `barge_ins_committed` 0 on those attempts, `turn_decider_disagreements` 0 —
  and it *sounded* like ducking rather than a dropout. The script prints the
  survival ratio and shouts if the floor is still off.
* **OG-2 — the onset stamp end to end.** With `realtime.capture.enabled: true`,
  after at least one committed barge-in:
  ```bash
  .parcel/bin/python scrum/20260822/task_26/evidence/read_onset_stamps.py
  ```
  (No argument: it takes the newest session under the capture root the PRODUCT
  resolves. Pass a directory to pick another.) Then compare
  `interrupted_onset_at` against the array's own recording of when the owner
  started — that difference is AIR-1's interrupt-latency row, and
  `interrupted_byte` locates the cut in `robot.wav` without re-deriving it.
* **OG-3 — a real backchannel corpus**, to replace the pre-registration's ten
  stand-in durations. Ten "mm-hmm"s recorded through the array; measure their
  true burst lengths; edit `BACKCHANNELS` in `tests/test_duplex1_rows.py` and
  re-run:
  ```bash
  .parcel/bin/python -m pytest tests/test_duplex1_rows.py -k d3 -q -s
  ```
  If any real token exceeds ~500 ms the decision rule picks a higher floor and
  D-2 gets worse.
* **OG-4 — RT-TURNS-1 on a live session**, so AIR-1's `--turns` has a file.
  There is **no product caller** (correction pass): the export must be invoked
  before the stack exits, from a shell attached to the runtime —
  `runtime.export_realtime_turns()` — after which:
  ```bash
  .parcel/bin/python scrum/20260822/task_26/evidence/read_onset_stamps.py
  # prints "turns.jsonl: N row(s)" or says it is ABSENT, then:
  .parcel/bin/python tools/bargein_through_air.py --turns \
      "$(git rev-parse --show-toplevel)"/recordings/<session>/turns.jsonl ...
  ```
  `owner_turns` is real. `robot_as_owner` is **not** (D-c).
* **OG-5 — the duck gain.** AIR-1's double-talk leg reports
  `signal_to_echo_db`; set `TurnController(duck_gain=…)` from it rather than
  from taste (its handoff says so in as many words). 0.18 until then, floored
  at `MIN_DUCK_GAIN = 0.05` — the constant now refuses to build a controller
  that would duck to silence.

## Handoffs

* **DX-1 → whoever wires the prototype profile (P0-A's launcher, or FINISH-2).**
  The floor is one argument at the lane's construction site:
  `RealtimeLane(..., backchannel_floor_ms=700.0)`. It must ship **together**
  with D-a's two `turn_detection` keys or it buys nothing (measured: 0/10 with
  `interrupt_response: true`). A config key for it is an edit inside TURN-1's
  `config.py` and belongs to whoever owns that file next.
* **DX-2 → CURIO-1 / whoever owns `whisperer.py`.** `lane.initiative_allowed`
  is built, counted and measured (D-4: 0 collisions over 70 samples). The gate
  is one condition at the top of `Whisperer.offer`. Without it, a proactive
  remark can still be composed while the robot or the owner holds the floor —
  the collision this card measured at zero is a property of the controller, not
  yet of the product's chatter path.
* **DX-3 → TURN-1 / TRUTH-1.** `test_the_shipped_examples_have_no_live_turn_detection_key`
  now blocks the prototype example from carrying the measured DUPLEX-1 pair
  (D-a). If the intent is that the *prototype* profile may ship a measured
  default while the production example stays commented, that guard needs a
  carve-out — from TURN-1's side, not from mine.
* **DX-4 → AIR-1 / FINISH-1 §E.** `score_turns` treats a missing or `None`
  `was_robot` as `False`, so it reports `robot_as_owner: 0` for a file that
  explicitly says the field is undecidable. Suggested: treat `None` as
  `unmeasured` and let the scorecard row say so, the same way the ERLE verdict
  now must.
* **DX-5 → MARK-1's H-2, still open.** `browser_sink.py`'s
  `first_chunk_started_monotonic` docstring still says a barge-in "truncates at
  zero"; the lane now falls back to the first-enqueue anchor. I did not take it:
  it is a docstring in a region this card edits, and rewriting another card's
  prose while its verifier is mid-flight is noise. Two sentences, ready in
  MARK1_STATUS.md H-2.
* **DX-6 → whoever builds the local endpointer.** `TurnController` consumes
  whichever offset reaches it first; `lane.note_owner_speech_stopped()` is the
  door. A local Silero (or even energy) offset on ch1 would decouple survival
  from `silence_duration_ms` entirely and let the floor come down to ~400 ms,
  which is the only route to satisfying D-2 and D-3 at the same time. That is
  the single highest-value follow-up this card leaves behind.

## What the verifier should look at first

1. **`_apply_turn_action` in `lane.py`.** It is the one place a second decider
   could have crept in. Confirm it can only DUCK or RESUME, and that the
   controller's COMMIT is discarded — then confirm
   `test_the_controller_and_marks_hold_never_disagree_about_a_barge_in`
   actually discriminates (seed the controller's floor to differ from the
   lane's and it should go RED).
2. **D-2's miss.** 740 ms is the honest cost of 10/10 survival. If you think
   the pre-registered decision rule was gamed, the ladder is printed in full
   and the ten tokens were fixed in a file whose sha is at the top of this doc.
3. **D-1's 0.0 ms.** I have called it an identity of the harness rather than a
   result. If you disagree that the ladder rescues it, the row should be
   downgraded to "not measured".
4. **D-a** — settled by the ruling recorded there; read it for the two pins,
   not for an open question.
5. **The `interrupted_onset_at` arithmetic** in `mark_interrupted` — a duration
   subtracted from a wall stamp read on a different thread. If that join is
   wrong, AIR-1's latency row will be wrong in a way nobody notices.

**After the correction pass, start with these two instead:**

6. **`duckGainFor` in `index.html`, and the Python port beside it.** Finding 1
   hid for a whole card because the port was STRICTER than the product and the
   gjs test could not fail. Check that every row about the panel exists on the
   gjs side and not only in `_DuckBrowser`, and that
   `_eval_duck_raw` still reports `null` / `nan` / `number` as three answers.
7. **`_check_turn_deciders_agree`.** The invariant that used to live only in a
   test. Confirm it runs after every settle and that
   `turn_decider_disagreements` reaches the snapshot — it is the only thing
   that will report finding 2's class from a live session.

---

# Correction pass — 2026-08-22, after Fable's 15-agent verification

Verdict was **ACCEPT with corrections**. Six findings plus a note list; all
addressed below. Same rules as the first pass: Edit-only, git read-only,
`TMPDIR` unset, a seeded RED for every new guard, targeted tests on the OWNS.
The seeded-RED transcript is now **committed with the card** at
`evidence/SEEDED_RED.txt`, produced by `evidence/seed_red.py`.

| # | Finding | Result |
|---|---|---|
| 1 | major — `duckGainFor` admitted `null`/`[]`/`""`/`false` as gain 0: a **silent mute**, and the test could not fail | fixed, 3 seeds (`S15`, `S16`, plus a rewritten family test) |
| 2 | major — a pump gap spanning the deadline **and** the stop split the two deciders and left the reply permanently ducked | fixed, seeded (`S17`) + a runtime invariant |
| 3 | major→minor — `duck` detected BY NAME would hand a linear gain to `SpeakerSink`'s **decibel** scale | fixed, seeded (`S18`) |
| 4 | minor — H-7's onset derivation had no test; the lane's own line could vanish and 58 tests stay green | fixed, seeded (`S19`) |
| 5 | minor — the D-3 ladder in this doc was not reproducible; the line count was wrong | re-run and re-pasted |
| 6 | minor — every owner-gated command was broken | two committed readers, both run here |
| 7 | notes ×7 | all taken; see below |

## 1. major — the panel muted the dog, and the test could not say so

**MARK-1's blocker, in the same file, one card later.** `Number(x)` is not a
type check: `ToNumber(null)`, `ToNumber("")`, `ToNumber([])` and
`ToNumber(false)` are all `+0` — finite, in range, and clamped straight to a
**silent** reply. A `duck` frame with a missing or null gain would have muted
the reply mid-sentence with nothing on the wire to say it was coming back,
which is precisely the state `turn_controller.py`'s own comment calls
forbidden ("silence is indistinguishable from a dropped connection").

Three separate defects, and the third is the one that let the other two ship:

* **the panel** coerced instead of type-checking;
* **the gateway's** clamp bottomed out at `0.0`, so its own out-of-range
  handling produced the same silence by a different door — and
  `test_the_panel_clamps_rather_than_refusing_an_out_of_range_gain` asserted
  that `-2` clamps to `0.0` *under a banner reading "our own bug must not
  silence the dog"*, which is exactly what it was doing;
* **the test was unfailable.** `assert result is None or result == 0.0` covers
  the only two outcomes the code could produce. The verifier re-ran the family
  against a mutant with the finiteness guard deleted and got identical results,
  green. Worse, `_eval_duck` round-tripped through `JSON.stringify`, which
  encodes `NaN` as `null`, so the harness could not tell a refusal from a `NaN`
  leaking through the clamp.

**Fixed.** The panel type-checks first and coerces nothing:

```js
if (typeof body.gain !== "number" || !Number.isFinite(body.gain)) return null;
return Math.max(MIN_DUCK_GAIN, Math.min(1, body.gain));
```

`MIN_DUCK_GAIN = 0.05` is now a real constant with one home
(`duplex/turn_controller.py`), imported by `audio_gateway.DUCK_GAIN_RANGE`, and
pinned to the panel's literal by a test — so the "not zero on purpose" rule is
enforced in all three places it was previously only *stated*. `TurnController`
also refuses to be built with a `duck_gain` below it. A real mute is
`sink.interrupt()`: a different act, with a different name.

The harness reports `(kind, text)` — `null` / `nan` / `number` — instead of
JSON, so the three answers are three answers. The family test is now
parametrised over nine shapes (`missing`, `null`, `""`, `[]`, `false`, `true`,
`"0.18"`, `"loud"`, `{}`) and asserts **refusal** for every one.
`test_the_panel_never_produces_a_silent_reply` replaces the clamp test and
asserts `-2`, `0`, `0.0001` and `MIN_DUCK_GAIN/2` all land on `MIN_DUCK_GAIN`;
`test_the_gateway_also_refuses_to_clamp_a_duck_to_silence` asserts the same on
the sending side through the real gateway.

**And the Python port was stricter than the product**, which is why no row
here caught any of it: `_DuckBrowser._control` refused `None`/`[]`/`""` that
the shipped JS admitted. It now mirrors the shipped rule line for line,
including `isinstance(gain, bool)` — Python's `bool` is an `int`, JS's `false`
is not a number.

Seeds: **S15** (restore the `Number()` coercion → the four ToNumber ids go RED),
**S16** (restore the `0` floor → the silence row goes RED).

## 2. major — one pump gap, two deciders, and a reply stuck quiet

`_resolve_barge_in_hold` asked only "did a stop happen since the hold opened?".
If a single pump pass is late enough to span **both** the floor's deadline and
the `speech_stopped` that follows it — a slow ledger write, a GC pause, a
stalled disk in the tee — then the resolver saw a stop and called it a
backchannel, while the controller, handed the same stop on the same clock,
correctly read it as past the deadline and moved to YIELD.

The symptom is the worst one available: nobody sends the RESUME, so a
still-playing reply finishes its sentence **permanently ducked**. The owner
hears the dog fade out and never come back.

**Fixed** by comparing against the deadline — `<=`, not `<`, so MARK-1's R4d
boundary is unmoved on both sides:

```python
if speech_ended_at is not None and speech_ended_at <= hold.deadline:
```

**And the invariant is now checked at runtime, not only in a test.**
`_check_turn_deciders_agree()` runs after every settle, compares
`turn_controller.commits` with `barge_ins_committed`, and on any divergence
increments `turn_decider_disagreements` and writes a note naming the controller
state. Counted, never raised — it runs on the pump thread, and an invariant
that ends the conversation it is protecting is worse than the drift it found.
The counter is in `snapshot()` and `evidence/read_duplex_counters.py` shouts if
it is ever non-zero.

Two new tests: `test_a_stop_that_lands_past_the_deadline_never_splits_the_two_deciders`
(the gap, driven by moving the clock past the deadline and delivering the stop
on the same pass) and `test_a_stop_that_lands_on_the_deadline_is_still_a_backchannel`
(the boundary MARK-1 fixed, unmoved). Seed **S17**.

This moved two cells of the D-3 ladder, and both moved *towards* the
arithmetic: 250 ms 1/10 → 0/10 (a 120 ms burst plus a 200 ms tail is 320 ms and
never did survive a 250 ms floor) and 450 ms 5/10 → 6/10. The chosen floor,
D-2, D-3 and D-6 are unchanged.

## 3. major→minor — a linear gain, handed to a decibel scale

`_apply_turn_action` feature-detected the **name** `duck`.
`voice_audio.SpeakerSink` has a `duck`, and its argument is **attenuation in
decibels**. Handed this card's `0.18` it would not even raise — 0.18 dB is
inside its accepted `(0, 60]` range — it would set the gain to **0.979**: an
inaudible "duck", on the one path with no browser to reveal it. And `duck(1.0)`
is not its unity call; `restore()` is, so the resume would have been wrong too.

**Fixed:** the gate is an explicit capability flag naming the SCALE.
`BrowserSink.accepts_gain_duck = True`; `_apply_turn_action` gates on that and
nothing else, and counts the sinks without it in `ducks_unsupported`. The
`SinkLike` comment is corrected — it claimed SpeakerSink "has no gain to
change", which is false; it has one, on a different scale — and now names the
conversion a future wiring would need (`-20 * log10(gain)` dB, `restore()` for
unity). Seed **S18**, with a `_DecibelSink` double shaped like the real one:
under the old gate it recorded `[0.18]`; now it records nothing.

## 4. minor — H-7's onset had no test that could fail

Every assertion about `interrupted_onset_at` hand-fed `onset_ago_s` **at the
sink**, and S4 seeded the key *name* inside the gateway. Nothing exercised the
one line that derives the number — `lane._barge_in_onset`, set in
`_on_speech_started` and turned into a duration in `_commit_barge_in`. Had it
never been set, the stamp would have vanished from every real capture and all
58 tests would have stayed green.

**Fixed:** `_DuplexRig` can now bind a real `SessionAudioCapture` (the tee is a
gateway constructor argument, so the chain is rebuilt from the gateway down
rather than poked into a private).
`test_the_lane_itself_derives_the_onset_that_reaches_the_capture_index` runs a
real barge-in at the shipped floor and asserts
`interrupt_hold_ms == approx(700, abs=60)` — a number only the lane can know —
plus `interrupted_onset_at < interrupted_at`.
`test_with_the_floor_off_the_cut_carries_no_onset_keys` asserts both keys are
**absent** at floor 0, not zero: a `0.0` hold on every pre-DUPLEX-1 capture
would make the two eras indistinguishable to AIR-1's join. Seed **S19**.

## 5. minor — the anti-gaming evidence had to be reproducible

The D-3 ladder is re-run and re-pasted from
`pytest tests/test_duplex1_rows.py -k d3 -s` on the corrected tree, with the two
moved cells explained in place. Line counts corrected: `test_duplex1_rows.py`
is **1 024**, not 770 (and the other three files with it).

## 6. minor — the owner-gated commands did not run

`OG-1` raised `KeyError` (lane keys live under `["realtime"]["lane"]`);
`OG-2`/`OG-4` pointed at `~/recordings/…`, but `capture.dir` resolves against
the **repo root**. Both are now committed scripts, each run here against real
objects before being written down:

* `evidence/read_duplex_counters.py` — reads `/api/state` on stdin, prints the
  controller state, the floor counters, both duck counters and the survival
  ratio, and shouts if the floor is off or the deciders ever disagreed;
* `evidence/read_onset_stamps.py` — takes the newest capture session under the
  root **the product resolves** (`resolve_capture_dir`, not arithmetic of my
  own — my first attempt got it wrong by one directory), prints every
  interrupted segment's stamps, and says whether `turns.jsonl` is beside it.

## 7. The notes, each acted on

* **OWNS overlaps** — all now declared in one place, **D-h**, including that
  `configs/realtime.prototype.yaml.example` is **P0-A's** file.
* **`export_realtime_turns`' docstring claimed callers it does not have** —
  rewritten to say plainly that it has **no product caller**, that a human runs
  it at the end of an owner session (OG-4) and that the tests are the other
  caller.
* **Reading the gate mutated the counters it is scored from** —
  `initiative_allowed` is now a **pure** read on both the controller and the
  lane; `consult_initiative()` is the counted door and the one the whisperer
  will knock on. D-4 samples the pure one and makes one real consultation per
  non-idle sample, so its 70 refusals are evidence about the product door
  rather than about how often a loop looked. Seed **S20**.
* **D-4's idle arm called `note_turn_answered` on itself** — dead scaffolding
  that read like a manufactured precondition. Removed: the reply now finishes
  on its own, `_on_response_done` gives the floor back and clears the owed turn
  through the product path, and the gate is asked once.
* **`PlaybackGateway` gained a mandatory member described in-line as optional** —
  a contradiction, since every Protocol member is mandatory. `duck` is removed
  from the Protocol; the comment explains the feature detection instead.
* **Uncommenting D-a's block breaks TWO pins, not one** — recorded in D-a
  alongside the ruling.
* **No seeded-RED transcript was committed** — `evidence/SEEDED_RED.txt` and
  `evidence/seed_red.py` now ship with the card.

## Re-verification after the corrections

```
.parcel/bin/python -m pytest tests/test_duplex1_rows.py \
    tests/test_duplex1_turn_controller.py tests/test_duplex1_panel_duck.py \
    tests/test_duplex1_rt_turns.py tests/test_mark1_barge_in_mark.py \
    tests/test_mark1_browser_ear.py tests/test_turn1_endpointing.py -q
```

**Two RED tests in the shared tree are NOT this card's, and one of them is a
live regression somebody must take.** Both are `runtime.py` source pins:

* `tests/test_p1b_map_learns.py::test_the_runtime_region_wires_all_three_seams`
  fails **deterministically**, in isolation, on this tree. P1-B pins the
  ordering with the literal
  `"self._attach_configured_camera_ingress()\n            self._thread"`, and
  **CAP-1** has inserted its `# ---- CARD CAP-1: required capabilities are
  startup-fatal` region between those two lines (`runtime.py:4304-4305`). The
  anchor no longer matches and the assertion raises `ValueError: substring not
  found`. Nothing to do with DUPLEX-1 — my region is 3 000 lines away and
  additive — but it will be RED at the gate, so it is named here: **CAP-1's to
  fix, or P1-B's anchor to loosen.**
* `tests/test_capture_ingest.py::test_no_adapter_import_ever_installs_or_imports_a_vendor_module`
  fails only in a large sweep and passes in isolation: it asserts
  `pyrealsense2` / `rclpy` / `unilidar_sdk2` are absent from `sys.modules`, so
  any earlier test in the session that imported one reddens it (the ENV-1 /
  HY-1 class, made reachable by P1-A's sanctioned wheel). **Proved not mine:**
  importing `parcel_robot.realtime.audio_gateway` and
  `parcel_robot.duplex.turn_controller` — the one new import this card adds —
  pulls in none of those four modules.

Every pre-registered row re-measured on the corrected tree and **unchanged**:
D-3 10/10, D-6 4/10 and 0/10, D-2 p95 740 ms (still a declared MISS), D-1
overhead p95 40 ms at every lag, D-4 0 collisions, D-5 0/0, D-7 identical.
MARK-1's 43 and TURN-1's 73 green; 293 passed on the targeted suite (73 of them
this card's). Ruff clean on every OWNS file **and** on the two committed
evidence scripts and the harness. **20/20 seeds behaved**, each restore
sha256-verified — `evidence/SEEDED_RED.txt`.

Two simulator processes left over from an earlier `test_voice_nav_e2e` sweep in
this session are still running on `pytest-of-jaewoo-jang/pytest-3848/…` sockets
(pids 2447765, 2447909, 2448046, started 13:20). They are the **HY-1** defect —
a test that leaks its sim — and they may well be mine. I have **not killed
them**, because the standing rule is to never kill a process I cannot prove I
started and a peer's suite may be attached; they are on scratch sockets under
`/tmp/pytest-…`, not on the owner's `/tmp/parcel_sim.sock`, and they are named
here so whoever gates can reap them deliberately.

## What the correction pass still does not prove

The three "not proven" items that findings 1 and 2 sharpen rather than close:

1. **The panel port is still a port.** It now mirrors the shipped rule line for
   line and the rule itself is evaluated in gjs — but the port drifting
   *stricter* is exactly how finding 1 hid for a whole card, and only the gjs
   arms can catch that class. A row that exists only in `_DuckBrowser` and not
   in `test_duplex1_panel_duck.py` should be read as unpinned.
2. **`turn_decider_disagreements` has never been non-zero here.** Finding 2's
   gap is constructed by moving a fake clock; whether a real pump ever stalls
   that long is an owner-session question, and the counter is what will answer
   it.
3. **`MIN_DUCK_GAIN = 0.05` is still taste** (OG-5). What is no longer taste is
   that *nothing in the pipeline can reach zero* — which is the part the design
   actually asserted and nothing enforced.
