# AUDIT — Week 1 "Voice through air + roam" · Fable · 2026-08-22

**Board:** `TASK_BOARD.md` (Build-order table). **Cards:** GATE-0 (task_20),
TURN-1 (task_21), MARK-1 (task_22), ROAM-1 (task_23), CURIO-1 (task_24), AIR-1
tools (task_25), ENV-1b (task_28 follow-up). **Baseline:** `8862220`.
**Method per card:** the executor's status doc + my diff read, then a read-only
three-lens workflow (seeds/weakening · product correctness + OWNS discipline ·
product-path integration), every non-note finding attacked by a skeptic who must
reproduce it to confirm. Rows are reported as *reproduced through the product
path*, *harness-only*, or *owner-gated* — never as the executor's number alone.

## Interruption — the monthly spend limit (12:00 EDT)

At ~12:00 the account's monthly spend limit terminated four agents mid-flight:
the ROAM-1, CURIO-1 and GATE-0 correction passes and the AIR-1
re-verification. Tree state verified afterwards: every changed module
compiles; 366 targeted tests across the three cards green; the two lines of
lint debris ROAM-1's pass left in `tests/test_roam1_behavior.py` removed by
the verifier (import order; `_ = runtime.roam_config`), ratchet back at
exactly 7. What each pass had landed, and what remains, is itemised in
**`task_29/README.md` (FINISH-1)** — one card, sections A–E for the executor,
F for the integrator. Rows below marked *pending close* are finished by it.

## Verdict table

| Card | Verdict | Confirmed findings | Corrections landed | Owner-gated rows |
|---|---|---|---|---|
| ENV-1b | **ACCEPT** | 0 (1 refuted: HEAD status quo) | none needed | attached-camera arms |
| TURN-1 | **ACCEPT** (after one correction pass, re-verified) | 6 (2 major in the replay tool, 1 vacuous test, 1 doc; 3 refuted) | replay token + clean refusals; 16→24 kHz + per-file offsets; guard made real; provenance gate on timings | G1/G2/G3 on the owner's 20 utterances |
| AIR-1 | **corrected · pending close** (all 10 fixed + the premise refuted: the XVF3800 exposes a raw-mic/reference mux, so §5.3's same-instant method is the primary path; re-verification died on the spend limit → FINISH-1 §E) | 10 (1 blocker ×3 lenses, 5 major, 1 minor; 2 refuted) | explicit `OutputStream`; turn rows owner-gated on RT-TURNS-1; spend wall-window join; owner-silence split; verdict allow-list; `asr_beam_echo_attenuation_db`; `XvfControl.mux_session` (opt-in, no `SAVE_CONFIGURATION`, restore + read-back) | all 7 measurement rows (owner session) |
| GATE-0 | **ACCEPT** (short correction pass in flight: 7 minor/doc) | 7 (xdist hazard in one probe test; handoff mis-sized; doc counts; 3 refuted) | pack `git add` at close (integrator); seat for `CODEBASE_INDEX.md` | B20 (Actions click); the pack becoming real on `main` |
| MARK-1 | **ACCEPT** (after one correction pass, re-verified) | 6 (1 blocker: the unpinned default disabled Chrome AEC; 1 major: hold vs `interrupt_response`; 3 minor; 1 note; 3 refuted) | null-beam guard + gjs test; cancelled-response commit; drained ack; hold reset; `interrupted_at`; final-ack race | OG-1 live barge-in (AIR-1's session) |
| ROAM-1 | **behavior/intents/clock ACCEPT · pending close** (pass died on the spend limit after landing the allowlist + product-door guards, the yield fix, `PatrolLimits.tether_m`, and the prototype `roam:` keys; the three tethered runs, the restated number, the ledger deviation and the doc remain → FINISH-1 §A) | 11 (1 blocker: `TOOL_ROAM` rejected by the supervisor allowlist; 3 major: yield cancels the owner's command, the 20.67 m run left the scene, undeclared ledger write; minors; 1 refuted) | ledger restored to HEAD by me; lint debris removed by me | hosted model reaching for the tool; felt session |
| CURIO-1 | **headline ACCEPT · pending close** (pass complete through §9.11 — `verdict.candidate`, two feed tests, clock test, gesture ruling, two cadences with `idle_remark`, `roam_idle_checkpoint()` consumed, shipped-default run A 3/0/0/2/$0 — but the seed-777 shipped run's cells are unfilled → FINISH-1 §B) | 7 (all minor after refutation; 4 refuted) | the two-cadence ruling (my card error) | owner taste row |

## ENV-1b — the capture-test follow-up (task_28) · ACCEPT

All six items reproduced through the product callers in **both** venv arms —
wheel present, and wheel hidden by each lens's *own* import shim (one lens also
hid `cv2` and every extra beyond base+dev: 667/667 each way). `--check`'s
REFUSED paragraph now splits MODULE MISSING from DEVICE MISSING and prints the
attach remedy for the latter; all six d455 rows are pinned; no module-present
arm is a skip; `pyproject.toml` untouched by this card (its only hunk is
GATE-0's ruff pin). My ENV-1 corrections, `probe_availability`,
`PROBE_REQUIREMENTS`, and `ingest/base.py` are byte-identical to HEAD. Four
seeds mutate the product and restore byte-identically. Item 5 (refuse by name
when a build exposes no `rs.context`) is a new refusal path by the letter of
the prototype rule, judged correct: `rs.context` is librealsense's root object
(present on the installed 2.58.3), so the branch is inert on every known build,
and where it would fire it replaces `probe_raised — RuntimeError` with a named,
remedied refusal raised before any pipeline exists.

**Refuted (1, minor):** "MODULE MISSING still sends a desk D455 operator to the
Orin/ROS 2 environment" — true, but HEAD text in four sibling remedies
(`clockmap`, `ingest/realsense.py:271`, `record.py`, `preflight.py`) and out of
the card's scope. **Carried as a wave-2 wording item (SDK-REM-1):** per-device
remedies — `.parcel/bin/pip install -e '.[camera-realsense]'` for the D455, the
Orin/ROS 2 sentence only for go2/l2; drop the stale "no wheel for 3.11+" and
"no aarch64 wheel" claims (unverified; a cp314 wheel is installed here);
`record --check` still runs a module-only census on a camera-less host; the
`NO DEVICE (installed: …)` report text has no product caller.

**Vacuous phrasings in the status doc (noted, not defects):** the "random
order" column — `pytest-randomly` is not installed in `.parcel`, so the column
was default order (the lenses supplied real shuffles: 667/667); "pyproject.toml
byte-unchanged" is true of the card's contribution, not of the tree.

**Not proven (by construction):** every attached-camera arm — `device_report()`
ATTACHED, `rs.context().query_devices() > 0`, the read loop past
`pipeline.start()` — waits for the D455.

## TURN-1 — endpointing is a knob (task_21) · knob ACCEPT, instrument HOLD

**The knob is real and changes nothing until asked.** Three lenses re-derived
the payload identity independently — HEAD `8862220`'s `protocol.py` loaded by
path from `git show` vs the working tree — and the `session.update` payload is
byte-identical four ways (no key, `TurnDetection()`, the config default, the
real YAML loader over 24 files including both shipped examples); the scripted
wire traces hash `dcfa10d5…` on both trees; conversation-ledger rows carry no
timing key (D2 is right — a ledger row would enter the memory-tail replay and be
paid for at every reconnect). `silence_duration_ms` outside 200–800 refuses at
load with the fix named; a plain `server_vad` block never refuses; the new
cross-key refusal (`eagerness` under `server_vad`) is judged a config-typo
boundary in the existing `ALLOWED_KEYS` discipline, not behavioural
fail-closed logic. Per-turn timings ride `lane.turn_timings` → `snapshot()` →
`/api/state`. MARK-1's backchannel floor reads `turn_timings[*]["speech_stopped_at"]`
from a disjoint region with a stable name. GATE-0's `protocol.py:415` untouched.
1,093 targeted realtime tests green (TMPDIR unset); ruff clean on the card's
files. The owner-gated rows (commit p50 ≤ 0.6 s, 0/20 mid-sentence commits,
barge-in 3/3) claim no number, and the doc states plainly that `--replay` cannot
stage barge-ins.

**Confirmed (6; 3 refuted):**
1. *(major)* `tools/replay_turn_detection.py` opens the lane with
   `handshake_token=None`; `decide_realtime_arming` refuses a falsy token
   (`CODE_NO_HANDSHAKE`, unchanged since HEAD) before any transport exists, and
   `RealtimeLaneError` is not in `main()`'s except tuple — so every G1/G2/G3
   command in the status doc dies with a traceback. Reproduced through the real
   `RealtimeLane` on `transport_pair()`: token `None` → refused, 0 sockets;
   token `"replay_turn_detection"` → opened. 68 green tests never reached it.
2. *(major)* Units and frame: the tool streams 16 kHz PCM raw through
   `lane.send_audio` into a session that declares no `audio.input.format`
   (provider default 24 kHz — `PCM16_SAMPLE_RATE_HZ`; the browser ear
   resamples; the gateway hello says 24000), so the provider hears the corpus
   at 1.5× (the 400 ms experimental pause becomes ~267 ms, under `server_vad`'s
   500 ms tail — G2 flattered on every arm), and a cumulative `audio_end_ms`
   over one session for all 20 files is subtracted from a per-file 16 kHz
   `end_of_speech_ms`.
3. *(minor)* `test_the_first_audio_stamp_does_not_move_for_later_chunks` is
   vacuous: with the `_emit_audio` stamp removed (the executor's own S4 row:
   "2 passed / 1 failed / 2 passed") `first` is `None == None`; the script is
   exhausted after the third speak so "does not move" is never exercised.
4. *(minor, doc)* "read by the R17 tee" — nothing but `lane.py` and the tool
   reference `turn_timings`; D5 lists 2 of 6 marked out-of-region sites.

Refuted: the 6-dp rounding of `speech_stopped_at` vs MARK-1's unrounded
compare (unreachable by physical ordering); "T8 identity is guarded only by the
scratch harness" (the CI subset check catches the failure mode); "D5
under-declares" (no pre-existing region to under-declare against). Notes: a
robot-initiated `response.created` can stamp an open owner-turn row; `ruff
format` would touch three new files (not gated).

**Correction pass — re-verified ACCEPT (all six).** A read-only re-check
drove the tool's own `replay()` through a real `RealtimeLane` on
`transport_pair()` with a two-file corpus: the session opens (`armed`), the
first socket frame is the arm's `session.update`, no `--live` → `refused:`
exit 2, `--live` without a credential → `refused: … RealtimeAuthError` exit 2
with no traceback, and `--arms/--check/--plan` never import `ws_transport`.
`resample_pcm16` is 2→3 with the same grid as `encodeMicFrame` (max 2 LSB
from `round` vs truncation); 960-byte frames = 20 ms at 24 kHz; `rate_hz` is
a required keyword; every report row carries `commits_raw_ms` and
`audio_offset_ms` with `commit = raw − offset`. The once-guard now asserts
`first is not None` while the row is still open and the server is not
exhausted. `_note_turn_milestone` ignores `RESPONSE_FROM_SYSTEM` (driven
through the real `narrate_event`, not the provenance poke the shipped test
uses). Payload identity still byte-identical to HEAD. 73 passed; ruff clean;
the tree-wide ratchet is back at exactly 7. Notes carried to DUPLEX-1: the
doc's "`--arms/--check/--plan` cannot touch `lane`" overstates (the package
`__init__` imports `lane`; `ws_transport` is the property that matters); the
report has no `settle_s`/per-file wall time, so if the provider's
`audio_end_ms` turns out to be wall-indexed rather than appended-audio-indexed
(no in-repo trace settles it), the first live run can detect but not correct
it.

## AIR-1 — the voice reaches its own mic (task_25) · tools ACCEPT, instrument HOLD

**What holds (reproduced through the product code):** the 16 kHz pin is a real
`Pa_IsFormatSupported` sweep on `hw:2,0` (16000 only; −9997 elsewhere; device
left in `Status: Stop`) with a named skip and a genuine coupling to
`protocol.PCM16_SAMPLE_RATE_HZ` / `voice_audio.SAMPLE_RATE_HZ`; the scorecard's
six refusals and seed D (an `unmeasured` ERLE report can never pass) hold
through the CLI; `score_monologue` drives the product `SessionAudioCapture`
through `verify_capture_index` and the 0.02 false-barge-in figure is labelled
synthetic; `xvf3800_probe.py` runs read-only here and reports the missing udev
rule / `pyusb` as Errno 13 through the product `UsbDoaReader` instead of
crashing; the HALT on interrupt latency is true of the current
`audio_gateway.py` (`note_interrupt` queues a wall stamp, `mark_interrupted`
drops it — and the interrupt *onset* is not stamped anywhere either; DUPLEX-1's
seam). OWNS clean: no AIR-1 text in `lane.py`/`audio_gateway.py`, the
digest-locked `echo_guard_scale` untouched, both config examples parse with
TURN-1's and CURIO-1's blocks intact and disjoint. Not one acoustic number was
claimed. Sink volume 0.40 really governs `hw:` playback on this array (retires
a runbook worry).

**Confirmed (10; 2 refuted):**
1. *(blocker, all three lenses)* `measure_erle.py`'s two-device branch calls
   `sounddevice.play(…, blocking=False)` then `sounddevice.rec(…)`; in
   sounddevice 0.5.5 `rec()` begins by stopping and closing the play stream, so
   the "uncancelled" leg — SESSION.md step 5c exactly — records the room floor.
   Without the witness that yields a `fail` with the canned clipping/AEC3
   mechanism; with `--reference-device` it yields `unmeasured` → "Redo 5c"
   forever. Reproduced through the product function with fake streams and the
   real PortAudio loaded. `build_report` also never checks the uncancelled leg
   stands above the floor.
2. *(major)* Two of seven rows have no producing path: step 10 never passes
   `--turns`/`--tv-turns`, and nothing in the tree writes the
   speaker/origin/`was_robot` JSONL `score_turns` reads (`SOURCES` never
   contains `robot`). The 0/20 robot-as-owner row bears on the F1 TV-hijack
   question.
3. *(major)* `hosted_spend_usd` is a vacuous pass: the ledger is keyed by the
   provider's `rt_` id, the capture by the tee's `sess_` id → 0 rows → $0.00.
4. *(major)* The owner-silence check cannot tell residual echo from owner
   speech, so the B3 failure the card exists to catch (speaker off the array's
   DAC) makes the false-barge-in row `unmeasured` instead of `fail`.
5. *(minor)* `build_scorecard` trusts any ERLE verdict except the literal
   `unmeasured`; a report with no verdict key passes.
6. *(major, honesty)* The three-leg figure is post-pipeline ASR-beam echo
   attenuation, not AEC ERLE; and "no raw-mic tap exists" was asserted without
   checking the XVF3800's output-channel selector / host-control interface.

Refuted: "the MARK-1 handoff is incomplete" (a wording gap, not a defect);
"the card does not carry the upstream report" (not reachable through the
product path). Notes: `false_barge_in_rate` auto-fills its mechanism; the probe
exits 0 without PortAudio though the config note promises non-zero.

**Correction pass sent** (explicit `OutputStream` + fake-stream guard +
floor-margin refusal; the turns export or an honest "owner-gated on a tool
that does not exist"; spend rows selected by wall window, 0 rows →
`unmeasured`; owner level evaluated outside robot segments; verdict/schema
required; `asr_beam_echo_attenuation_db` naming + the raw-tap check). Result
appended below when it returns.

## MARK-1 — an interruption tells the truth (task_22) · server ACCEPT, browser HOLD

**What holds, through the product lane with no monkeypatch** (`RealtimeLane`
+ `BrowserSink` + `BrowserAudioGateway.handle_control`, the defaults
`runtime.py:2650/7636` actually pass): the recorded debt reproduces first —
R7's live client + the pre-MARK-1 played clock gives 24/24 truncations at
0 ms while the owner had heard up to 2,970 ms; the arrival-only ack panel
misses by an order of magnitude (p95 1,200 ms, max 1,440 ms); the delivered
client gives **0/24 zero truncations, |truncate − heard| p50 0.0 / p95 1.0 /
max 1.0 ms**, and the acks alone carry it (first-enqueue fallback off gives
the same). The referee `_AudioContext.rendered_ms()` is independent of the
product's played clock (probed), though it shares the port's scheduling model
— the 1 ms p95 is partly an algebraic identity of that model, and browser-side
behaviours the headless port does not model stay owner-gated (OG-1). D-1/D-2/
D-5/D-6/D-7 correct; `_speech_ended_after()` reads the field TURN-1 writes from
a disjoint region with a safe degrade path; no MARK-1 text in `protocol.py`,
`config.py`, the broker, the whisperer; ruff 7/7. The floor and the pin are
harness-only knobs (no config key, no runtime caller) — the right default
under ask-over-refuse and declared, but the card's definition of done
overstates it.

**Confirmed (6; 3 refuted):**
1. *(blocker, browser half)* `armEar()`'s guard
   `Number.isFinite(Number(pin.beam))` is true for the shipped
   `{"channels": 1, "beam": null}` (ToNumber(null) = +0), so the DEFAULT path
   calls `applyConstraints({channelCount: 1, echoCancellation: false,
   noiseSuppression: false, autoGainControl: false})` on the owner's mic on
   the first click — D-3 ("unpinned path unchanged") and R3d are wrong, and the
   executor's "no JS engine on this host" claim was false (`/usr/bin/gjs`;
   the skeptic fed the product's real hello JSON into the extracted line).
   With no on-chip AEC reference routed yet, Chrome's AEC3 is the only echo
   canceller in the loop; off, the robot barges in on itself in AIR-1's
   session. One-line fix + a gjs-evaluated guard test.
2. *(major)* Any floor > 0 is incompatible with the provider default
   `interrupt_response: true`: a genuine interruption during the hold makes
   the provider cancel the response; the `finished` branch counts it as a
   survived backchannel, nothing is truncated, the browser keeps playing.
   TURN-1's `interrupt_response: false` is a hard prerequisite for DUPLEX-1's
   floor, alongside `silence_duration_ms`.
3. *(minor)* The played-ack timer goes quiet when the schedule drains, so the
   gateway extrapolates through a stall; only the `enqueued_ms` clamp bounds
   the truncate.
4. *(minor)* A hold survives a session reset and is later miscounted.
5. *(minor)* AIR-1's handoff (the interrupt wall stamp dropped by
   `mark_interrupted`) is inside MARK-1's OWNS and was not taken; the seam is
   two lines (`interrupted_at` on the open segment).
6. *(note)* Pre-registered seeds S1/S2 were replaced without a declared
   deviation — prereg S2 could not have fired (the continuous client emits
   only 2 regressive acks ≈ 20 ms over the sweep; the guard matters for the
   arrival client, p95 1,441 → 1,200).

Refuted: "the referee shares inputs so R2 is non-discriminating" (the
replaced clients fail on it); "S1/S6 are source-text pins" (declared in "what
this does not prove"); "R3/R4 are harness-only" (declared as D-2/D-4).

**Correction pass — re-verified ACCEPT (all six).** The extracted `const
wants =` line now reads `pin && pin.beam !== null && Number.isInteger(pin.beam)
? pin : null`; under gjs against the product's real default hello it is
`null`, non-null for `{channels:2, beam:1}` and for beam 0; the shipped test
lifts the line from `index.html` and feeds the product `hello()`, and the whole
panel parses under `new Function` (67,538 bytes, PARSE OK). A provider
`response_done(status='cancelled')` during a 700 ms hold: `survived 0,
committed 1, sink.interrupts 1`, truncate at the heard position, zero
`response.cancel` frames. The drained ack freezes the gateway anchor (live ack
lifts it); with the socket 350 ms behind the tab, p95 330 → 269 ms, and once
any ack lands p95 1.0 ms — reported separately; R1/R2's 24 rows unchanged.
Hold reset at `_connect()` and `close()`. `interrupted_at` /
`interrupted_byte` / `interrupted_t_s` on a cut segment, absent otherwise.
`_record_final_ack` folds max-wins, bounded at 4, reset per utterance. 152
passed across four files; ruff clean; no MARK-1 hunk inside a `CARD TURN-1`
region. Three doc notes carried to FINISH-1 (task_29 §D): "unknown status ⇒
falls through to the floor" is false (it settles as *finished*); TURN-1's
`lane.py` share is ~159 lines, not +73; and AIR-1's tool does not yet read
`interrupted_at` (§E).

## CURIO-1 — the dog talks about what it sees (task_24) · headline ACCEPT

**The hard row reproduces through the product path on the verifier's own
run** (real MuJoCo sim on its own socket, real `RobotRuntime`, the runtime's
`OnlineSemanticMap`, real `RealtimeLane` on the shipped `FakeRealtimeServer`,
roam via MOVE-1's harness): 6 remarks in 120 s at the 25 s harness cadence
(door, tree, storefront, window, lamppost, building), every label re-checked
against `known_places()` from the evidence log's 4 Hz vocabulary timeline at
≤ 0.24 s before utterance — **0 hallucinated**; 0 inside the 29.9 s owed
window (29 `lane_busy` skips; nothing was even attempted); worst rolling
minute 4 of the cap 6; `recordings/spend.jsonl` and the owner store
sha256/mtime identical before and after, the store never opened. The
executor's roamB/roamC re-score identically from their own logs. The shipped
default (`mean_gap_s` 360) yields 0 remarks in 120 s, exactly as
pre-registered. OWNS clean: `whisperer.py` purely additive at AST level (no
pre-existing body changed; P2-B's bands untouched), `runtime.py` one marked
region + one call line + 9 tagged imports with zero deletions, `config.py`
keys co-load with TURN-1's and ROAM-1's, the production example untouched and
P0-A's gate green; seeds on a byte-identical copy of `src/` are valid evidence.
479 targeted tests green; ruff clean.

**Confirmed (7, all minor after refutation; 4 refuted):**
1. The `ask_about` feed reads `verdict.ask_place`; the real `AbstentionVerdict`
   carries the subject as `candidate`. On the product path the spoken place is
   always the queried label, the re-check is unreachable, and seed A2 plus two
   tests assert a stub attribute (the skeptic drove a real verdict with an
   unadmitted candidate through the feed: narrated, `dropped_unadmitted` 0).
2. `place_learned` and `scene_change` feed branches have no test; "proven at
   unit level" is false for them (the skeptic drove both branches: they
   behave). The template renders "the the front step".
3. The polled conversation clock is untested on the product path; no roam
   exercised it (the owed window exercised the floor gate).
4. The cap-spent free gesture consumes the fact and re-arms the gap, against
   `note_remark`'s contract; it routes via `_brain_gesture('curious_look')`,
   not `proactive_motion_tools`.
5. Doc counts: `runtime.py` share is +478, imports 9; the seed sha pair
   predates two docstring edits.

Refuted: the seed-evidence staleness (delta is two docstrings); "P0-A's gate
is blind to a nested prototype-only block" (declared deviation); "harness
interventions on private members" (declared); "`curiosity_snapshot()` reaches
no product surface" (not this card's).

**Ruling on the cadence contradiction — my card error.** "Mean 4–8 min" and
"3–6 per 120 s" were two different cadences: stimulus-driven remarks during a
roam (novelty events, bounded by the cap and a ~25 s gap) and idle chatter when
nothing is happening. The correction pass implements both as config
(`stimulus_min_gap_s`, `mean_gap_s`) and re-measures the roam row with the
shipped defaults, and consumes ROAM-1's `roam_idle_checkpoint()` for the
idle-checkpoint rule now that ROAM-1 has landed. Result appended below.

## ROAM-1 — "go explore" (task_23) · behavior ACCEPT, tool + purchase number HOLD

**What holds, through the product runner on the verifier's own socket:**
"Go explore." via `runtime.submit_realtime_transcript` (the callable the lane
is built with) starts the runtime's own `PatrolPolicy` tick in 0.06–0.10 s;
"stop roaming" latches on return of the ingress call; a spoken "stop" ends the
roam as `emergency_stop` next tick; the roam ends at its budget with 0
contacts and ≥ 1.06 m person clearance; the paired `nav_instruct` minival is
byte-identical with and without `time_s` at 10 Hz (sha `f64dedd2…`, all 25
episodes, re-run with the ledger redirected) and tracker dt follows
`control_dt`; `ALLOWED ∪ REFUSED == MOTION_TOOLS` with `roam` in REFUSED and a
system-initiated call rejected; seeds S1–S4 reproduced on a scratch copy (S1's
re-cut guard is real — the runtime budget check is the only one reachable when
the eye is quiet). Arm A (the shipped policy) reproduces the donut exactly:
0.31–0.79 m net, 1404° of heading, every avoidance turn the same sign, a
1.8 × 2.3 m box — a real defect found by the card; the one-line default-OFF
`alternate_turns` with both arms on the record is acceptable evidence. OWNS
clean: zero deletions in `runtime.py`, 453 lines marked ROAM-1 vs 478 CURIO-1
and nothing unmarked, the ingress ladder appended not reordered, `config.py`'s
11 lines, three foreign test files carrying only the new tool's verdict rows,
`patrol.yaml`'s digest intact. 742 targeted tests green.

**Confirmed (11; 1 refuted):**
1. *(blocker)* **`TOOL_ROAM` is dead on the product path.** A broker built
   with the product validate door and OWNER provenance gets `rejected: not
   started: Unknown behavior: roam` (and `roam_stop`) from the supervisor's
   behavior allowlist; `follow_owner` passes on the same door. The executor's
   broker tests used a stub validator. Ruling: extend the allowlist with the
   two names in a marked region — entries only, no semantics — and guard it
   through the product door (admitted for the owner, refused under latch,
   refused with system provenance). `reactive_safety` and `core/hard_stop`
   stay untouchable.
2. *(major)* The roam "yields" to an owner spatial command by cancelling it:
   `stop_roam(owner_command)` → `stop_motion()` → `preempt(manual)` stops the
   owner's just-issued circle/move-steps one tick later.
3. *(major — the purchase number)* The 20.67 m run is a block-exit regime:
   through the bldg_5/bldg_6 gap at t≈52 s, off the 24 × 24 m road plane at
   t≈85 s, 138/479 samples on the unfenced infinite plane at a constant
   heading; 8.66 m of the net accrued off the rendered map (the verifier's
   replicate: 20.36 m, same trajectory). The honest Go2 input is **two
   in-block runs ≥ 1.0 m (3.37, 2.05) plus one scene exit**; the ≥ 1.0 m ×3
   row is still met (12.0 m even at the last in-plane sample). Ruling: a roam
   is a bounded wander around home — `PatrolLimits.tether_m` (default None,
   set by `limits_from_safety`), an in-bounds qualifier on the metric, and
   three pre-registered in-block runs re-measured.
4. *(major, discipline)* The two minival runs appended two rows to
   `evals/nav_instruct/results/ledger.jsonl` (append-only provenance, outside
   OWNS), one from a tree with `time_s` seeded out. **Restored to HEAD by me**
   (`git checkout` of that one file; both rows ROAM-1's by report_id).
   Follow-up for the eval owner: a `--no-ledger` switch on
   `run_nav_instruct_v1.py`.
5. *(minor)* A stop racing an in-flight tick can be followed by one stale
   roam command (≤ 0.3 s TTL).
6. *(minor)* No owner-turnable roam knob reaches the product path (the
   prototype overlay loader refuses the `roam:` section `_roam_limits` reads).
7. *(minor)* `roam_idle_checkpoint()` is published but nothing consumed it —
   handed to CURIO-1's correction pass.
8. *(doc)* Seed driver invocation not in the evidence; test-file names in the
   brief that do not exist; `stop_latency_s` is the harness's sleep; the
   owner-gated row's PASS criterion names a panel block the UI does not
   render.

Refuted: "`_step_roam` runs outside the control loop's exception wrapper" (a
pre-existing loop-wide property; the invariant is enforced elsewhere).

**Correction pass sent** (allowlist + product-door guard; yield without
`stop_motion()`; tether + in-bounds metric + three re-measured runs; ledger
deviation declared; race fix; prototype roam keys; doc hygiene). Result
appended below when it returns.

## GATE-0 — the gate tells the truth on a clean clone (task_20) · ACCEPT

**Reproduced in the verifier's own tracked-only clone** (git clone of
`8862220` + GATE-0's 34 uncommitted files + the pack, committed in scratch and
re-cloned; fresh CPython 3.12.13 venv, `pip install -e '.[dev,voice]'`):
`scripts/ci_gate.py --tier commit --json` → valid JSON naming all ten stages,
zero stderr, `unitree-assets` PASS (both scenes compile geometry-only in
0.24 s / 0.09 s), `hard-safety` PASS, ruff 7 / new 0 on the pinned 0.16.1,
8/10 green with the same 51 / 8,564 default-suite count as the executor's
run D. Negative half: `foot.obj` deleted **and** the first evaluator forced to
raise → still ten stages, `unitree-assets` FAIL naming the file and both
scenes, `hard-safety` contained as a bounded ERROR, no traceback. Run A
(HEAD's runner, pack hidden) reproduces the zero-bytes-of-stdout `ValueError`.
The pack: `git add --dry-run` lists exactly 20 files and no gitlink; 19/19
sha256 + sizes match; every blob byte-identical to upstream tree
`ae6a8403` (the renamed clone's HEAD — the pin is derived independently of
the manifest); BSD-3 licence shipped; 27.11 MiB; scenes and frozen digests
byte-unchanged. `run_stage` is `except Exception` only with ERROR still
gating-red. The 3.11 defect reproduces on HEAD (`ValueError: mutable default
<class 'mappingproxy'>`) and is gone after; the EV-1 repair still binds
`k=1`/`k=3` literally. AST diff of `ci_gate.py`: only `evaluate_ruff`,
`update_ruff_baseline`, `run_commit_tier`, one appended nightly line — XD-1's
region untouched. Git writes confined to the executor's cache; working tree
HEAD `8862220`, nothing staged.

**Confirmed (7, minor/doc; 3 refuted):** the carve-out probe test writes a
real file into the pack directory (spurious reds at one-worker-per-test xdist
— reproduced at `-n 26`/`-n auto`; a SIGKILL leaves a stray the gate blames
on the pack); the 51-failure table is off by one in two rows and the GATE-0b
handoff is mis-sized (`results/*` explains ~5 of 35; ~17 need
`.cache/external-evals/runtime/barn-parcel-bundles`, ~7 fail the V9
training-manifest mode-bit premise that no carve-out can fix, 3 habitat
provenance, 1 generator checkout, 1 under a third `.gitignore`); seeds E/F
counts are pre-integration; a hand-written `ruff_version_stamped_at` key the
re-pin would drop; run B's ruff FAIL is an A/B artefact. Refuted: region
markers "overclaim"; "the clean clone is RED so the DoD fails" (the row was
pre-registered as JSON-with-no-traceback); "R10 holds only under the commit
tier" (declared).

**Mine to fix:** the nightly held-out prose scan is red on `CODEBASE_INDEX.md`
(the generated repo index lists every tracked path, the held-out scene's
filename among them) — a seat with that reason, added by GATE-0 which owns
the seat file this wave. **At close (integrator):** `git add
third_party/unitree_mujoco` — 20 files, 0 gitlinks. Owner-gated: B20 (the
Actions click; the hosted job will be red for the pre-existing 51 and its
20-minute timeout is at risk).
