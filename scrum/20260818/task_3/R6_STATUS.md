# R6 task_3 — the answered turn (turn-retry + single-beat tool turns)

**Date:** 2026-08-18/19 · **Card:** `scrum/20260818/task_3` · **Executor:** Claude Opus (agent)
**Auditor:** Fable
**Depends on:** R5 (`20260818/task_2`), R4L (`20260818/task_1`), R1.6+R3 (`20260817/task_6`)
**Baseline:** `877d9f4` at session start, plus the large uncommitted wave from the
other in-flight cards (`lane.py`, `protocol.py`, `runtime.py`, `memory.py`,
`web_panel.py`, `index.html`, `launch_stack.sh`, two test files, and the
untracked realtime modules). Nothing of theirs was touched except `lane.py` and
`tests/test_realtime_reconnect.py`, both of which are this card's OWNS.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## What landed, in one paragraph

Both defects are fixed in `lane.py` and both are proven live. A reconnect now
**repays** the turn it inherited — one `response.create` per reconnect, only
when `_responses_pending` says something was genuinely owed, counted in the
snapshot (`turn_repays`) and explained in the ledger (`[turn repaid] …`), on the
stall, rollover *and* disconnect paths, with a bound so a turn the provider dies
on every time is abandoned out loud instead of re-asked forever. The
unconditional post-tool `response.create` at the old `lane.py:1024` is now
**conditional**: it is skipped only when the model already spoke in the response
that carried the call, the call actually succeeded, and the result is a
*receipt* rather than an *answer* — so a navigation turn is one beat, and every
refusal, deferral, drop, silent call, unreadable result and information-tool
answer still gets its sentence, carried by per-response `instructions` that are
composed on top of the session prompt rather than replacing it. The live session
then found a third defect, in this card's own file: the watchdog measured
silence from the provider's **last frame** instead of from **our own request**,
so any turn typed after a pause longer than `stall_timeout_s` was declared
stalled about two seconds after it went up — the manufacturer of the very
incident this card exists to repair. That is fixed and seeded too. And two
live findings that are NOT mine to fix are reported with transcripts: the
provider refuses every `assistant` and `system` conversation item this lane
sends, which silently halves the replayed memory and makes R4L's narration
channel a no-op on the wire.

## Root cause — Defect 1, the swallowed turn

`_reconnect` (`lane.py`, pre-fix 1122-1164) replaced the session and re-injected
the memory tail, and nothing then asked the new session for anything:

```python
self._connect()          # session.update, tools, tail — the QUESTION is in there
self._note(f"reconnected after {reason}: …")
                         # …and the new session is never asked to answer it
```

`_connect` resets `_responses_pending = 0`, so the fact that a response was owed
died with the socket. Observed twice live before this card (R4L session 3, R5
session 3): a navigation turn produced no response, no refusal and **no
billing** — the owner's sentence was simply gone while every panel counter said
the session was healthy.

The fix reads what was owed **before** `_connect` erases it, and repays after
the tail is up (`_reconnect` at `lane.py:1291`, `_repay_turn` at `lane.py:1346`).

## Root cause — Defect 2, the second beat

The old `lane.py:1024`:

```python
self._send(FunctionCallOutput(call_id=event.call_id, output=output))
self._send(ResponseCreate())        # <- every brokered tool answer, always
```

R5 proved the pre-call announcement is co-emitted by the provider with the
`function_call` and is not suppressible on `gpt-realtime-2.1-mini` under three
SI wordings, including the card's own. So the removable beat is this one, and
the R5/Fable carry-forward said exactly that. `_on_function_call`
(`lane.py:1086`) now asks `_beat_reason` (`lane.py:1151`) for a reason to speak
and skips the frame only when there is none:

| condition | beat | why |
| --- | --- | --- |
| the model spoke no text in the response carrying the call | **sent** | nothing has been said yet; silence would be the whole turn |
| `status` is not `ok` (deferred/dropped/rejected/broker raised) | **sent** | the announcement is now false and the owner must hear it |
| result JSON unreadable / not an object | **sent** | fail toward speech; an unparseable result proves nothing |
| tool is not in `DEFAULT_RECEIPT_TOOLS` (e.g. `get_status`, `recall_memory`) | **sent** | the result IS the answer; nothing else will ever say it |
| spoke + `ok` + receipt tool (`navigate_to`/`play_gesture`/`set_pose`) | **skipped** | the announcement the owner heard is the turn's beat |

`_responses_pending` moves only for frames the transport accepted (`_send` now
returns delivery, `lane.py:1402`), so the R4L watchdog and the repay read a
number that matches what actually went up.

## Root cause — Defect 3 (found live, fixed here): the phantom stall

`_tick_locked` compares `now - self._last_event_at` against `stall_timeout_s`
while `_expecting_server` is true. `_expecting_server` was armed by whoever
asked for a response; `_last_event_at` only ever moved when a frame **arrived**.
So the patience clock for a new question started at the previous answer:

```
live session 1, 2026-08-19
  t =  8.4s   response.done for "Go to the sidewalk."      <- _last_event_at
  t = 18.4s   owner types "Wave at me please."             <- _expecting_server = True
  t ≈ 19s     watchdog: 10.0s > 8.0s  ->  STALL, socket hung up ~2s after the question
```

Every conversation with a pause in it hit this. It is the most likely
explanation for R4L's `stalls: 2` inside a two-minute session and R5's four
stalls across four short sessions — and for the turns that vanished with them.
`_arm_watchdog` (`lane.py:1441`) now starts the clock when the request goes up,
which is what the watchdog's own note always claimed it measured. Live session 2
(same prompts, an 11-second gap before the same turn): `stalls: 0` until I
forced deafness myself.

## What landed

| File | Lines (this card) | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/lane.py` | 1272 → 1548 (net +276) | repay (`_repay_turn`, `turn_repays`, abandon bound); conditional beat (`_beat_reason`, `_beat_instructions`, `TOOL_STATUS_OK`, `DEFAULT_RECEIPT_TOOLS`, `RESULT_BEAT_RULE`, `DEFAULT_REPAY_LIMIT`); `_send` returns delivery; `_arm_watchdog`; four new snapshot keys |
| `tests/test_realtime_reconnect.py` | 708 → 1389 (net +681) | 25 new tests (19 → 44 collected); two R4L tests strengthened; `_Rig(reconnect_script=…)` |
| `scrum/20260818/task_3/R6_STATUS.md` | this file | |

Net line counts, not a `+/−` split: `lane.py` was already dirty at session start
with other cards' uncommitted work, so `git diff` cannot separate this card's
share. The line counts above are measured against the files as this session
found them (`lane.py` md5 `740700eab1b5344ce4e241f83cec97ba` at 22:02).
The gate's own arithmetic agrees: R5's `6177 passed` → `6202 passed`, +25.

`protocol.py` **needed no edit**: `ResponseCreate.instructions` already exists in
the committed tree (`protocol.py:224-233`), so the card's narrow opening was
not used. It is wire-verified below.

New snapshot keys: `turn_repays`, `turn_repays_abandoned`,
`tool_beats_requested`, `tool_beats_suppressed`. `/api/state` passes
`lane.snapshot()` through verbatim, so no panel change was needed.

## Gate — `ci_gate --tier commit`, verbatim

Run after the final source edit. Four full gate runs were taken across this
card and all four are green; this is the last one, on the tree exactly as it
stands now (after the 16-seed sweep restored every mutation).

```
CI GATE — tier=commit  (2026-08-19T02:35:14Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.31s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6202 passed, 9 skipped, 42 deselected, 5 warnings in 233.39s (0:03:53)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 246.0s
```

R5's baseline on this tree was `6177 passed`; this card adds 25 tests
(`6202`). `ruff` unchanged at the pinned baseline of 7 fingerprints, `new 0`;
digest sentinels and release-parity byte-identical, which is the mechanical
confirmation that nothing under `evals/` or the packaged assets moved.

The other three: `02:12:04Z` (`6200 passed`) — everything except the
phantom-stall fix and its two tests; `02:23:46Z` (`6202 passed`) — the first
run with the complete change; `02:31:07Z` (`6202 passed`) — a confirmation
run taken after the seed sweep, proving the 16 mutate/restore cycles left the
tree exactly as the gate found it.

## Seeds — 16 seeded defects, all RED

Harness: `scratchpad/r6/seed_r6.py`. Each seed mutates ONE **source** file
(never a test), runs a named pytest target, restores the file in a `finally`
and asserts the restore is byte-identical. Nothing under `configs/` or `evals/`
is touched. Re-run in full after the final source edit.

| # | Seeded defect | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- |
| S1 | the swallowed turn restored: a reconnect stops repaying what was owed | **RED** | 6 failed, 2 passed, 36 deselected, 1 warning in 0.40s :: test_a_turn_the_dead_session_never_answered_is_repaid_on_the_new_one, test_the_repay_is_visible_in_the_snapshot_and_explained_in_the_ledger, test_one_repay_per_reconnect_even_when_two_responses_were_owed, test_a_rollover_repays_the_turn_it_interrupted |
| S2 | repay is unbounded within one reconnect: one per response owed | **RED** | 1 failed, 1 warning in 0.26s :: test_one_repay_per_reconnect_even_when_two_responses_were_owed |
| S3 | the repay double-answers a response that actually completed | **RED** | 1 failed, 1 warning in 0.26s :: test_a_response_that_actually_completed_is_never_repaid |
| S4 | repay loops forever: the abandon limit is removed | **RED** | 1 failed, 1 warning in 0.26s :: test_a_turn_that_kills_every_session_is_abandoned_out_loud_not_re_asked_forever |
| S5 | the repay is silent in the record: no ledger row explains the late answer | **RED** | 1 failed, 1 warning in 0.26s :: test_the_repay_is_visible_in_the_snapshot_and_explained_in_the_ledger |
| S6 | the success-path tool turn asks for a response again: two beats return | **RED** | 1 failed, 1 warning in 0.26s :: test_an_announced_navigation_turn_gets_exactly_one_spoken_beat |
| S7 | the failure-path tool turn goes silent (the dangerous over-correction) | **RED** | 4 failed, 40 deselected, 1 warning in 0.28s :: test_a_call_that_did_not_succeed_is_always_narrated[deferred-Deferred, test_a_call_that_did_not_succeed_is_always_narrated[dropped-the, test_a_call_that_did_not_succeed_is_always_narrated[rejected-motion, test_a_broker_that_raises_is_narrated_rather_than_hidden |
| S8 | an answer-shaped result is swallowed: every ok tool counts as a receipt | **RED** | 2 failed, 1 warning in 0.27s :: test_an_answer_shaped_tool_result_is_never_swallowed[get_status], test_an_answer_shaped_tool_result_is_never_swallowed[recall_memory] |
| S9 | a silently-made tool call is answered with silence too | **RED** | 1 failed, 1 warning in 0.26s :: test_a_tool_call_the_model_made_silently_still_gets_its_beat |
| S10 | the spoken flag never clears: one announcement pays for every later call | **RED** | 1 failed, 1 warning in 0.26s :: test_speech_in_one_response_does_not_pay_for_a_call_in_the_next |
| S11 | the beat's per-response instructions replace the persona and guardrails | **RED** | 1 failed, 1 warning in 0.26s :: test_the_beat_carries_the_whole_prompt_not_just_the_result_rule |
| S12 | pending accounting drifts from what was sent: a dropped frame is waited for | **RED** | 1 failed, 1 warning in 0.26s :: test_a_beat_whose_frame_was_dropped_is_not_counted_as_a_beat |
| S13 | the suppressed beat is still counted as pending (phantom stalls forever) | **RED** | 1 failed, 1 warning in 0.26s :: test_the_suppressed_beat_leaves_the_pending_ledger_exactly_as_sent |
| S14 | a new owner turn inherits the previous turn's spent repay budget | **RED** | 1 failed, 1 warning in 0.26s :: test_a_new_owner_turn_gets_its_own_repay_budget |
| S15 | the repay is not watched: a repay that stalls is invisible | **RED** | 1 failed, 1 warning in 0.26s :: test_the_repaid_turn_is_watched_like_any_other |
| S16 | the phantom stall returns: arming does not start the patience clock | **RED** | 2 failed, 42 deselected, 1 warning in 0.27s :: test_a_turn_typed_after_a_quiet_gap_is_not_instantly_a_stall, test_owner_audio_also_starts_the_patience_clock |

The card's six required seeds map to: swallowed turn restored → S1; repay
unbounded → S2 (within one reconnect) and S4 (across cycles); repay
double-answers a completed response → S3; success-path tool turn requests a
response again → S6; failure-path tool turn goes silent → S7 (plus S8, the same
over-correction against information tools, and S9 against a silent call);
pending accounting drifts from what was sent → S12 (dropped frame) and S13
(suppressed beat counted as owed).

S15 went **UNANCHORED** mid-card when `_send` was refactored to call
`_arm_watchdog`; the harness reported it as unanchored rather than passing it
off as RED. It was re-anchored and re-run RED.

## Live proof

The owner's stack was **not running** when this card started (nothing listening
on 8765 or anywhere in 87xx/88xx; re-checked at teardown). No HTTP request of
any kind left this session — the proofs build a `RobotRuntime` in-process with
the headless MuJoCo city, exactly as `tests/test_realtime_live_smoke.py` does,
so no port was bound at all.

**Memory isolation, stronger than the card's recipe:** rather than copying
`configs/robot.yaml`, the runtime config is *synthesized* in the scratchpad with
`memory:\n  path: ":memory:"`. The owner's `parcel_memory.sqlite3` was never
opened, for reading or writing, in any of the three sessions —
`configs/robot.yaml` was not read, copied or touched either. The realtime config
is likewise a scratch file (`persona`, `mode: text`, `model`,
`monthly_budget_usd: 5.0`); the owner's `~/.config/parcel/realtime.yaml` was
read once, by eye, to confirm the model name. The credential was loaded with
`set -a; . ~/.config/parcel/realtime.env; set +a` and never printed, asserted
against or written anywhere.

| Session | Purpose | Outcome | Cost |
| --- | --- | --- | --- |
| 1 | (a)+(b)+(c) on the fixed lane | **all three proven**, and **found the phantom stall** plus the refused-item defect | `$0.033610` |
| 2 | re-proof after the phantom-stall fix | phantom stall **gone** (`stalls: 0` across the same gaps); (b) and (c) reproduced | `$0.038297` |
| 3 | one-turn probe: does `narrate_event` reach the model? | **it does not** — the provider refuses the item | not sampled (2 responses) |
| | | **total** | **≈ `$0.072` (two sampled sessions)** |

### (b) PROVEN — a navigation turn is ONE spoken beat

Session 1, verbatim, and reproduced in session 2:

```
[   7.2s]   [owner] Go to the sidewalk.
[   8.4s]   [robot] Okay, let me see what I can do with that request.
[   8.4s]   [tool] navigate_to: ok — mission accepted: sidewalk
[   8.4s]   [response] resp_EEQ52l1cvuVwnD6HibwY9 completed
[  18.4s] BEATS FOR THE NAVIGATION TURN: 1
[  18.4s]   suppressed=1 requested=0 narrations=0 errors=[]
```

Session 2: `Alright, let me check where we can head together.` — again one beat,
`suppressed=1 requested=0`. R5's session 4, the same prompt, produced two:

```
R5:  [CHAT 2.8s] Okay, let's get you headed onto the sidewalk together.   <- beat 1
     [EVT  2.8s] tool navigate_to: ok — mission accepted: sidewalk
     [CHAT 3.8s] Alright, I've got the directive to move towards the      <- beat 2
                 sidewalk. Now I'll check that it's safe and on my path.
```

The unmet half of R5 is met. **What the owner loses:** the surviving beat is the
model's announcement, not the outcome — see §does_not_prove and §Open risks 1.

### (c) PROVEN — a deferred call is still narrated

Session 1 (the model announced, then the gesture was deferred behind the live
mission — so the beat is REQUESTED, exactly as the failure path requires):

```
[  18.4s]   [owner] Wave at me please.
[  23.2s]   [robot] Okay, I'll try to help. Let me check my systems and see what comes back.
[  23.2s]   [tool] play_gesture: deferred — Deferred paw_wave while navigation is active
[  24.0s]   [robot] It was deferred while navigation is active.
```

Session 2 exercised the *other* branch — the model made the call **silently**,
so the beat was requested for that reason and the whole turn is one truthful
sentence:

```
[  17.4s]   [owner] Wave at me please.
[  18.2s]   [tool] play_gesture: deferred — Deferred paw_wave while navigation is active
[  19.4s]   [robot] It didn't wave—while it's moving, the paw wave gesture was put off
                    for safety until it finishes.
```

Both beats are result-only, with no "I'll…"/"let me…" preamble — which is what
`RESULT_BEAT_RULE` asks for on the per-response `instructions`.

### `response.create` + `instructions` — wire-verified

No `unknown_parameter` / `invalid_type` / discard was returned for any of the
three beats sent with per-response `instructions` across sessions 1-2 (the
provider is demonstrably loud about parameters it dislikes — see the refusals in
the next section, and R1.6's `session.type` finding). Caveat stated honestly: a
silently-ignored field cannot be told apart from an obeyed one by wording alone,
though the beats *did* come back result-only.

### (a) PROVEN — a forced mid-turn stall is answered after the reconnect

The transport is made deaf under a live session (`_DeafTransport`: the real
socket stays open, frames still go up, nothing ever comes down — the exact state
R4L/R5 recorded). From the moment it is installed, **nothing is done by hand**:

```
[  29.4s] the lane is now deaf to a live socket; responses owed: 1.
          From here NOTHING is done by hand.
[  29.4s]   [owner] What is the tallest building in New York?
[  39.9s]   [system] [session stall] reconnected rt_ad3715d787bd -> rt_8cf54486e90d
[  40.2s]   [system] [turn repaid] the previous session owed 1 answer(s) when it died
                     (stall); asked the new session to answer the turn it inherited
[  42.4s]   [robot] …                                        (session 2, see below)
[  51.0s] recovered in 21.6s; answered=True; stalls 0->1 repays 0->1
```

Session 1's repaid turn answered the question outright:

```
[  38.8s]   [robot] The tallest building in New York City is One World Trade Center,
                    also known as the Freedom Tower.
```

Session 1 also contains an **unforced** instance, and it is worth being precise
about what caused it: the "Wave at me please" turn hit the *phantom* stall
(Defect 3, still present in session 1), the lane hung up a healthy socket
mid-turn, repaid, and the turn was answered on the new session — `[session
stall] reconnected` → `[turn repaid] …` → `Okay, I'll try to help…` → the tool
call. Before this card that sequence ended at "reconnected" and the sentence was
gone. So session 1 shows the R4L/R5 incident happening by itself, being
recovered by Defect 1's repay, *and* handing over the diagnosis of why it
happened at all — which Defect 3 then removed, as session 2 confirms.

Session 2's repay was answered but **answered the wrong thing** — the model
re-attempted the pending gesture instead of the question — because the replayed
history it inherited had no assistant turns in it. Which is the next section.

### Live finding 1 (NOT FIXED, not mine) — the provider refuses every assistant and system item

```
session 1, after each reconnect:
  [server error] invalid_value: Invalid value: 'text'. Value must be 'output_text'.   x2
  [server error] invalid_value: Invalid value: 'text'. Value must be 'output_text'.   x4
```

The counts match the assistant rows in the tail exactly (2 of 5 items, then 4 of
8; session 2: 3 of 7). `ConversationItemCreate.to_payload`
(`protocol.py:163-176`) sends `{"type": "input_text"}` for `role: user` and
`{"type": "text"}` for everything else; the API wants `output_text` for
assistant items and `input_text` for system ones. So:

* **every reconnect and every session open replays the owner's half of the
  conversation and none of the robot's** — silently, since R1;
* **`narrate_event` is a no-op on the wire.** Probe 3, decisive:

```
[   7.0s] narrate_event returned True
[   7.2s]   [server error] invalid_value: Invalid value: 'text'. Value must be 'input_text'.
[   8.4s]   [robot] Hey! I'm glad you're feeling good today. Anything fun happening? …
```

The lane counted `narrations: 1`, the provider dropped the fact, and the
response that followed said nothing about the robot arriving anywhere. This is
R4L's Open risk 1 ("model narration of terminals is unproven live") turned from
unproven into **proven broken**, and it is the reason session 2's repay went
astray.

**Not fixed here on purpose.** `protocol.py` is MUST-NOT-TOUCH in this card
except for the `ResponseCreate.instructions` field, and the remedy — two content
types — changes what every session sends on every open, which deserves its own
card, its own pins (no existing test asserts the content *type*) and its own
live proof. The remedy, ready to paste:

```python
# protocol.py, ConversationItemCreate.to_payload
"type": "input_text" if self.role in {"user", "system"} else "output_text",
```

### Live finding 2 (FIXED here) — the phantom stall

Covered under §Root cause — Defect 3. **Both** of session 1's stalls fired on a
stale clock: the "Wave at me please" one purely so (a healthy socket, 10.0 s
gap, 8.0 s timeout), and the forced-deafness one was *detected instantly*
instead of after the 8 s of silence I had actually imposed. Session 2, with the
fix in, ran the same prompts across gaps of 11.0 s and 12.0 s at `stalls: 0`,
and its forced stall took the full timeout (deaf at 29.4 s, reconnect at
39.9 s) — which is both the fix working and the cleaner version of proof (a).

## Deviations

1. **`protocol.py` was not opened at all.** The card offers it for an additive
   optional `ResponseCreate.instructions`; that field is already in the
   committed tree (`877d9f4`, `protocol.py:227`). Nothing to add — so the file
   is byte-identical to how this card found it.
2. **A third defect was fixed** — the phantom stall (`_arm_watchdog`). Outside
   the card's two defects, inside `lane.py` (OWNS), and it manufactures the
   incident the card exists to fix: without it a repay fires on a healthy
   session every time the owner pauses, which costs a socket, a reconnect and a
   billed response each time. Seeded (S16) and proven live in both directions.
3. **The success path has a THIRD condition the card did not name:** the tool
   must be a *receipt* tool. The card's rule ("`status: ok` AND the model
   already spoke") would silence `get_status` and `recall_memory`, whose ok
   result IS the answer and which have no later reporter — "what do you
   remember about the willow?" would be answered by "let me check" and nothing
   else. `DEFAULT_RECEIPT_TOOLS` is a lane-side constant (the lane has never
   imported the broker; it holds it behind a Protocol) and is constructor-
   injectable. An unknown tool name is NOT a receipt tool, so the failure
   direction is always one beat too many, never silence. Seed S8.
4. **The repay is bounded across cycles as well as within one.** The card says a
   repay that stalls is the next watchdog cycle's problem; that is honoured for
   the first `DEFAULT_REPAY_LIMIT = 3` cycles, after which the turn is abandoned
   with a `[turn abandoned]` ledger row and a counter, rather than re-asked at
   the backoff cap forever on a socket that keeps billing. A new owner turn
   resets the budget (seed S14) — one poisoned sentence must not disarm the
   mechanism for the rest of the conversation.
5. **The repay also covers the `disconnect` path**, not only `stall` and
   `rollover`: all three funnel through `_reconnect`, and a socket that hangs up
   mid-turn loses the turn exactly like a silent one.
6. **Per-response `instructions` are composed, not substituted.** They are sent
   as `session instructions + "\n" + RESULT_BEAT_RULE`, because
   `response.instructions` REPLACES the session prompt for that response —
   sending the bare rule would strip the persona and every guardrail from the
   one beat that reports what the robot actually did. Seed S11; and
   `result_beat_instruction=None` still asks for the beat (pinned), so a
   provider that ever refuses the field costs the wording, never the sentence.
7. **Two R4-lite tests were strengthened rather than left to drift.** The repay
   lands on the same new socket as the owner's next turn, so
   `test_the_first_turn_after_a_stall_reconnect_is_answered` and
   `test_a_turn_that_arrives_during_the_backoff_is_not_lost` would have kept
   passing for the wrong reason. `_Rig` gained an optional `reconnect_script`
   (default `None` = R4L behaviour byte-for-byte), the baselines are now taken
   after the repay lands, and the second test asserts the owner's turn by
   `response_id` (`resp_next`) instead of "any usage row".
8. **Three live sessions, not one.** Session 1 found the phantom stall; session
   2 re-proved the card's claims on the fixed lane; probe 3 is a single-turn
   answer to a question Defect 2 depends on ("does the narration channel
   work?"). Total ≈ `$0.072`, far inside the card's "well under $1".
9. **The live proofs bind no port and start no stack.** The card suggests
   `:8813` and `/tmp/parcel_r6.sock`; an in-process `RobotRuntime` needs
   neither, keeps the whole thing in one file, and removes any possibility of
   touching the owner's stack. Nothing was launched, killed or probed.

## What this does NOT prove (does_not_prove)

* **The surviving beat is an announcement, not an outcome.** "Okay, let me see
  what I can do with that request" is one beat and it is true, but it does not
  tell the owner the mission was accepted. The card's design says the robot's
  own systems report what happens next — and live finding 1 says that channel is
  currently refused by the provider. Until that is fixed, a successful
  navigation turn tells the owner *less* than R5's two beats did (R5's second
  beat at least restated the directive). The mission log, the panel events and
  the deterministic yield utterances are unaffected and still carry the facts.
* **The repay's answer is only as good as the replayed tail**, and the tail is
  currently missing the robot's half (live finding 1). Session 1 answered its
  question correctly; session 2 answered a different, stale one.
* **No voice turn was repaid.** The repay keys on `_responses_pending`, which is
  only non-zero for turns the lane explicitly asked for — `send_text`, the
  post-tool beat, `narrate_event`. A server-VAD **audio** turn is answered by a
  response the provider creates itself, so nothing is owed by this lane's
  bookkeeping and nothing is repaid. That is deliberate (repaying on
  `_expecting_server` alone would re-answer stale history when transcription
  never completed) and it is a real gap for `mode: audio`, named in Open risks 3.
* **No human heard any of this.** `mode: text` throughout, `output_modalities:
  ["audio"]` on the wire but no speaker, no microphone, no barge-in.
* **`set_pose` was never exercised live** — it is in `DEFAULT_RECEIPT_TOOLS` by
  the same reasoning as the other two motion tools, pinned offline only.
* **The abandon bound was never reached live.** Three consecutive repays with no
  completed response in between is an offline pin (S4).
* **Nothing here says the provider stalls are gone.** Session 2 stalled exactly
  once, when I made it deaf. Whether `gpt-realtime-2.1-mini` also stalls on its
  own — R4L's and R5's open question — is now *less* certain than before,
  because the phantom stall explains an unknown share of what they measured.

## Owner-gated / not touched

* **`protocol.py`, `runtime.py`, `tool_broker.py`, `prompting.py`,
  `ingress.py`, `transport.py`, `ws_transport.py`, `config.py`,
  `fake_server.py`, `agent.py`, `web_panel.py`, `ui/index.html`, `configs/**`,
  `evals/**` — all untouched.** `fake_server.py` needed no extension: its
  existing `Step`/frame helpers express an announced tool call directly, so the
  new scripts live in the test file.
* **SI v2 stays exactly as R5 shipped it.** This card removes the beat the SI
  could not; it does not reword the SI, and `lane.GUARDRAILS` is unchanged.
* **The 25-thread corpus stays an SI-v1 artifact.** No `evals/` file was read or
  written; the frozen-digest and release-parity gates confirm it.
* **The content-type defect (live finding 1) is left for the owner to schedule.**
  It is a two-line change with a session-wide blast radius and it deserves its
  own card and live proof.
* **Nothing was committed, staged or stashed.** `git stash list` is empty and
  the other cards' uncommitted work is exactly as it was found.

## Open risks, honestly

1. **The refused `assistant`/`system` items are now the biggest hole in this
   lane, and R6 makes them matter more.** The repay's whole value is that the
   new session inherits the question; today it inherits only the owner's side of
   everything. Recommend this as the next card, ahead of the audio gateway,
   with the two-line remedy above, pins on the content *type* in
   `tests/test_realtime_protocol.py`, and one live turn checking that
   `narrate_event` produces an assistant line that mentions the fact.
2. **`narrate_event` returns `True` for an item the provider refused.** The lane
   counts a narration that never landed. Nothing in the lane can currently see
   an `error` frame as belonging to a specific item; the honest fix is probably
   to surface `server_errors` in the snapshot the way `dropped_sends` already
   is. Not attempted here.
3. **A stalled voice turn is still not repaid** (see does_not_prove). When the
   audio gateway lands, the repay needs an owed-turn signal for server-VAD
   turns — probably "an input transcription completed and no response has
   started since" — and that is a design question, not a one-liner.
4. **`DEFAULT_RECEIPT_TOOLS` is a name list in the lane.** If the broker grows a
   sixth tool, it gets a beat until someone adds it — which is the safe
   direction, but it is a coupling between two modules that deliberately do not
   import each other. A `receipt_tools` attribute on the handler (read via
   `getattr`) would be the tidier seam; the constructor argument is there today.
5. **The phantom-stall fix changes what "stall" means in the counters.** Any
   comparison of `stalls` against R4L's or R5's numbers is now apples to
   oranges, and some of the provider-behaviour worry in those documents should
   be considered withdrawn until re-measured.
6. **One repay costs one response.** On a genuinely dead provider the lane now
   spends up to three extra responses per turn before abandoning it. Bounded and
   counted, but it is real money on a bad provider day, and `turn_repays` is the
   number to watch in the snapshot.

## Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r6/`

| File | What |
| --- | --- |
| `seed_r6.py` | the 16-seed harness (mutate one source file → named pytest target → restore in `finally` → assert byte-identical) |
| `seeds_final.txt` | the final full seed sweep, verbatim |
| `gate_1.txt` / `gate_2.txt` / `gate_3.txt` | the three full gate runs (pre-phantom-fix, final, and a confirmation run after the seed sweep) |
| `live_r6.py`, `live_r6_session2.py`, `live_probe3.py` | the live harnesses (in-process runtime, headless MuJoCo city, `:memory:` ledger) |
| `live_run1.log`, `live_run2.log` | the full session transcripts quoted above |
| `live/evidence.json`, `live2/evidence.json`, `live3/evidence.json` | machine-readable evidence packs: beats, broker calls, server errors, lane snapshots, spend |

## Restart required

`lane.py` is not hot-reloadable. The owner's stack must be relaunched to pick up
the repay, the single-beat tool turn and the phantom-stall fix:

```
./scripts/launch_stack.sh
```

No config change is needed — the new behaviour is on by default, and the two new
constructor arguments (`receipt_tools`, `result_beat_instruction`) exist for
tests and for a future build with a different tool surface.
