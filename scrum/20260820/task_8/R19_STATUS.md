# R19 — the silent companion: answers eaten by the beat gate

**Card:** `scrum/20260820/task_8/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable · **Date:** 2026-08-20
**Chain:** after R17 (`task_6`), coordinating with R15 (`task_4`), inside R6's
(`20260818/task_3`) and R11's (`20260819/task_4`) invariants.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

---

## §0 — ROOT CAUSE, written before a line was changed

The card's hypothesis is that R6's answer-tool exemption drifted and
`get_status`/`recall_memory` were being suppressed. **It did not drift, and
they were not suppressed.** The run's own counters refute it, and refuting it
is what makes the real cause visible. There are **four** mechanisms, not one,
and only the second is a "suppression" defect at all.

### 0.1 The arithmetic that closes the suppression question

`state.realtime.lane` from live_run_1, verbatim:

```
tool_beats_requested = 10
tool_beats_suppressed = 8
brokered_tool_calls = [navigate_to ×8, follow_owner ×2, play_gesture,
                       set_pose, get_status, recall_memory,
                       play_gesture, navigate_to ×3]      (18 calls)
broker: calls 18, executed 14, dropped 0, rejected 4
```

10 + 8 = 18, so **every call got a decision** and none is unaccounted for.
Decompose the 18 against the shipped gate (`lane._beat_reason`,
`DEFAULT_RECEIPT_TOOLS = {navigate_to, play_gesture, set_pose}`):

| class | count | gate verdict | why |
| --- | --- | --- | --- |
| `get_status`, `recall_memory` | 2 | **beat requested** | not receipt tools |
| `follow_owner` ×2 | 2 | **beat requested** | R10 tool, not in the receipt set |
| receipt tools, `status: rejected` (the 4 e-stop refusals) | 4 | **beat requested** | `status != ok` |
| receipt tools, `ok`, model spoke | 8 | **suppressed** | spoke + ok + receipt |
| receipt tools, `ok`, model silent | 2 | **beat requested** | nothing said yet |
| | **18** | 10 requested / 8 suppressed | ✅ matches the snapshot exactly |

There is exactly one decomposition of 18 into 10/8 under the shipped rule and
this is it. **The eight suppressed beats were all `navigate_to` / `play_gesture`
/ `set_pose` receipts. The battery figure and the memory answer each had their
beat REQUESTED.** R6's third condition — the one R6 added as its own deviation 3
against the card that did not name it — held perfectly, and R10's two additions
sit outside the receipt set exactly as R15 §9.1 pinned
(`test_the_two_R10_tools_still_always_get_their_beat`).

So `results.json` q23's note — *"8 of 10 tool beats were suppressed this run and
this is one of them; the suppression policy is eating owner-requested answers"* —
is **false as stated**, and `README.md` headline 2 inherits it. The battery beat
was asked for. It came back as filler.

### 0.2 Mechanism A — the beat fired and the model answered it with filler

`ledger.json`, the silence window, verbatim (ids 2794–2802):

```
14:27:49  owner  How's your battery?                  → get_status executed, beat REQUESTED
14:27:57.736 robot  Let me think through what I can safely check and describe.
14:27:57.739 robot  Let me check what I can safely report and then we'll go from there.
14:28:07  owner  So, what do you remember about me?
14:28:08.263 robot  Nice question—let me think about what I can pull from past chats.
              ~14:28:08  recall_memory executed, beat REQUESTED
14:28:18.728 robot   let me take a [interrupted after 0 ms]
```

Two robot rows **3 ms apart** at 14:27:57 is two responses landing together —
the owner's turn and a beat. Both are deliberation announcements. The
`recall_memory` beat, 10.5 s later, opens `" let me take a"`. Every surviving
sentence in the window is the model saying it is *about to* answer.

`RESULT_BEAT_RULE` (`lane.py:160`) says *"Say ONE short spoken sentence about
what actually came back"* and then spends its longest, most concrete clause on
R15's activity tense. For `get_status` — whose result is
`{"status":"ok","detail":"current robot state","state":{…battery 90.0…}}` — the
rule never says **the owner asked a question and this result IS the answer:
speak the value**. Nothing in the per-response instruction distinguishes "narrate
a receipt" from "answer a question", so the model treated the answer beat as one
more receipt and announced that it was checking. **The answer beat is not
suppressed; it is unbriefed.**

### 0.3 Mechanism B — filler counts as "the model already spoke"

`_spoke_this_response` (`lane.py:1310`, `lane.py:1581`) is set by ANY non-blank
transcript delta. R6's condition reads *"the model already SPOKE in the response
that carried the call — an announcement the owner has heard is a beat"*, and R6
was right about that for the sentence it measured (`"Okay, let's head over to
the sidewalk"` — which names the destination and the act). But the provider
co-emits whatever it likes, and in this run it co-emitted content-free
deliberation:

```
14:26:21  Okay, let me check how to get you there.        (navigate_to, beat suppressed)
14:27:34  «nothing at all»                                 (play_gesture wave — q19)
14:27:38  «nothing at all»                                 (set_pose sit — q21)
```

A "let me check" that carries no fact satisfies a condition written for an
announcement that carried one — **the exact failure R6's rule was designed
against, inverted**, as the card says. And R15 sharpened the cost: R15 moved the
FACT out of the model's mouth and into the broker detail (`"started: the robot
is walking to the sidewalk"`), so post-R15 the suppressed beat is the **only**
place that fact is ever spoken. R6 suppressed a beat that would have restated a
plan; R6+R15 suppresses the beat that carries the tense-correct truth. Eight
times in four minutes.

### 0.4 Mechanism C — the beat's `response.create` raced the response that carried the call

This is the one that ate the refusals, and it is a protocol race, not a policy.

`_on_function_call` (`lane.py:1683`) sends `ResponseCreate` **the instant** it
answers the call. But `response.function_call_arguments.done` arrives *inside*
an open response; `response.done` comes after. The provider's own words, from
`state.realtime.lane.recent_server_errors`:

```json
{"code": "conversation_already_has_active_response",
 "message": "Conversation already has an active response in progress:
             resp_EEy3T5quJvQDbJRVd2JNe. Wait until the response is finished
             before creating a new one."}
```

The beat was **refused by the provider**, and the lane had already counted it
(`_send` returns "the transport accepted the frame", which is all
`tool_beats_requested += 1` has ever meant) and already incremented
`_responses_pending`. Nothing re-offers a refused beat. The refusal is silent to
the owner and the pending count leaks.

That is the full explanation of the four e-stop rejections producing one
narration:

| time | event | beat |
| --- | --- | --- |
| 14:29:11.502 | `play_gesture` **and** `navigate_to` both rejected in ONE response (the compound q45), model still speaking *"Let me do a quick gesture and then move toward the bench"* | both raced the open response — **no speech** |
| 14:29:36.094 | `navigate_to` rejected in the same millisecond as *"Okay, let me try to get there safely, and then I'll tell you what happened."* | raced — **no speech** |
| 14:29:55 | `[session stall] reconnected` — the leaked `_responses_pending` from those beats is what the watchdog finally noticed | |
| 14:29:58.320 | `navigate_to` rejected on the fresh session, carrying response already closed | **narrated**, 14:29:59.433 |

The README's irony — *"it took a session stall and a turn repay to make the
robot mention the e-stop it had been ignoring for 100 seconds"* — is this
mechanism's signature: R6's Defect-1 repay machinery accidentally paid a debt
that R6's Defect-2 beat had dropped. **`stalls=1` in this run is a symptom of
the refused beats, not an independent event.**

Why this never showed up before: R6/R15 proved the beat live in `mode: text`,
where the carrying response closes within milliseconds of the function call. In
`mode: audio` the response stays open for the *duration of the spoken audio* —
seconds — so the race window went from a coin-flip to near-certain. **This is
the first card whose defect only exists in audio mode.**

R15 wrote the contract this breaks, in `_whisper_refusal`'s own docstring
(`runtime.py:7993`): *"a `rejected` broker result is the case
`lane._beat_reason` refuses to go quiet on, so the model already says it in the
same turn, and saying it twice was never the fix."* R19's job is to make that
sentence true on the wire rather than to add a second channel beside it.

### 0.5 Mechanism D — an activity that expires undelivered has no reporter at all

`results.json` q21: `set_pose` → `broker.executed`, while
`state.activities.recent id=2` reads
`{"name":"sit","trigger":"explicit_command","status":"expired",
"disposition":"defer","detail":"proposal_ttl_elapsed"}`. q20's bow: the same,
and no broker call at all.

`ActivityCoordinator._expire` (`core/activities.py:212`) moves a TTL'd proposal
straight into `_recent` from inside `submit`/`start_ready`/`snapshot`. It
returns nothing and calls nobody. R15 wired terminals for the two endings that
pass through `_step_activities` — `finish(success=True)` and the
dispatch-cancelled/preempted arms — but **an expiry never becomes a terminal**,
so `_narrate_finished_activity` is never reached. The whisperer's counters agree
that nothing was ever offered: `narrations 0`, `forwarded 0`,
`critical_bypass 0` for the entire run.

### 0.6 The four mechanisms, and what each one costs

| | mechanism | what the owner lost in live_run_1 |
| --- | --- | --- |
| A | the answer beat is unbriefed | battery 90.0%, the recalled memory |
| B | filler satisfies "already spoke" | 8 receipt facts, incl. the wave and the sit |
| C | the beat races the open response | 3 of 4 e-stop refusals, + the stall they caused |
| D | expiry has no terminal | the sit and the bow that never happened |

**The card's stated direction — "one beat too many, never silence" — is the
frame for all four fixes, and every new branch below fails toward speech.**

---

## §1 — What changed

| File | Change | Mechanism / card item |
| --- | --- | --- |
| `src/parcel_robot/realtime/lane.py` | `speech_is_substantive` / `clause_is_filler` + their tables (`FILLER_CLAUSE_PREFIXES`, `FILLER_ACKNOWLEDGEMENTS`, `MIN_SUBSTANTIVE_WORDS`); `_response_speech`; `_is_answer_result` + `DEFAULT_ANSWER_TOOLS` + `ANSWER_RESULT_KEY` + the `answer_tools=` argument; `ANSWER_BEAT_RULE` and `_beat_instructions(answer=…)`; one sentence added to `RESULT_BEAT_RULE`; `_request_beat` / `_beat_refused_by_provider` / `_flush_pending_beat` / `_drop_pending_beat` + `CODE_RESPONSE_ALREADY_ACTIVE`; three snapshot counters | A, B, C · items 1–3 |
| `src/parcel_robot/realtime/tool_broker.py` | `ANSWER_TOOLS`, `ANSWER_RESULT_KEY`, and the `answer: true` stamp in `handle` — one stamp, one place, beside R15's tense stamp | A · item 2 |
| `src/parcel_robot/runtime.py` | `_narrate_expired_activities` + `ACTIVITY_STATUS_EXPIRED` + `_seen_activity_endings`, wired first in `_step_activities`; `_narrate_activity_terminal` gains a `started=` arm for work that never began | D · item 4 |
| `tests/test_realtime_answer_beat.py` **(NEW)** | 1039 lines, 27 test functions, 81 collected cases | DoD |

Untouched, and verified untouched: `prompting.py` / the SI, `protocol.py`,
`ingress.py`, `whisperer.py`, the yield policy, `core/activities.py`,
`configs/**`, `evals/**`. **`whisperer.py` needed no edit** — the card offered
it "if the always-band refusal entry is missing" and it is not: R11's
`KIND_REFUSAL` is already `always` / `critical_bypass`, which is what the
expiry narration rides and what the live decision log confirms (§5.3).

File sizes as this card leaves them: `lane.py` 2699, `tool_broker.py` 1417,
`runtime.py` 8926, `tests/test_realtime_answer_beat.py` 1039. **No `+/−` split
is given, and that is deliberate:** all three source files were already dirty
with other cards' uncommitted work when this session opened, so `git diff`
cannot separate this card's share and any number claiming to would be invented.
The gate's own arithmetic is the honest measure — R17's `6780 passed` →
`6861 passed`, +81, exactly the new file's collected cases — and the seed
harness's startup snapshot
(`lane 0aade6d7…`, `tool_broker e049c071…`, `runtime 25dec883…`) is the same
tree the closing gate scored.

## §2 — Mechanism A: the answer beat is told to say the answer

`ANSWER_BEAT_RULE` is a SECOND per-response rule, appended to
`RESULT_BEAT_RULE`, never substituted for it. R6's composition property
survives untouched (`session instructions + "\n" + rules`), so the persona and
every guardrail still ride the beat, and R15's tense sentence is still in it.

> The owner asked you a QUESTION and this result is the ANSWER to it. Say the
> answer itself — the actual figures, names and facts that are in the result —
> in your very first words. Do not say you are checking, looking, thinking
> about it, pulling it up or getting back to them: the lookup is already
> finished and its answer is the thing you are holding. If the result is empty,
> say plainly that you have nothing for them.

`RESULT_BEAT_RULE` gains exactly one clause, and the SI is not touched to get
it (card item 3): *"Never open this sentence by saying you are checking,
looking, thinking, seeing or pulling anything up: the checking already happened
and its result is in front of you."*

**Why two rules rather than one longer one.** A `navigate_to` receipt is not an
answer; telling the model to "say the figures in the result" for one invites it
to read a route id out loud. `test_a_receipt_beat_is_not_told_to_answer_a_
question_nobody_asked` pins the scoping in the other direction.

### The unsuppressible property, made structural

R6 protected `get_status`/`recall_memory` by leaving them OUT of
`DEFAULT_RECEIPT_TOOLS`. That is protection by OMISSION, and R6 shipped a
`receipt_tools=` constructor argument in the same card that can put them back
in. R19 makes it positive: `_beat_reason` asks `_is_answer_result` **before** it
looks at the status or the receipt set, and a tool is an answer tool if EITHER

* the result says so in-band — `{"answer": true}`, stamped by the broker; **or**
* it is named in `answer_tools` (default `{get_status, recall_memory}`).

The in-band half is the one that matters for the future: live_run_1 re-cut F3 as
a **missing perception tool**, and whatever that tool ends up being called, this
lane will not have heard of it and the receipt list will not mention it. This
also closes R6's Open risk 4 ("`DEFAULT_RECEIPT_TOOLS` is a name list in the
lane… a coupling between two modules that deliberately do not import each
other") from the side that fails safe: the classification travels WITH the
result. The lane still does not import the broker.

The whole seven-tool surface is pinned tool by tool
(`test_every_tool_on_the_current_broker_surface_has_a_pinned_beat_verdict`),
R10's `circle_owner`/`follow_owner` included, so an eighth tool is a decision
somebody writes down rather than an accident of which frozenset it landed in.

## §3 — Mechanism B: filler is not speech

`speech_is_substantive` strips deferral and acknowledgement clauses and asks
whether ≥ 3 words of content are left. Two design points, both about the
failure direction the card pinned:

1. **Filler is matched as a clause PREFIX, never as a substring.** "let me
   check the map" is a deferral; "the bench is clear, so let me check the map"
   is not, because the owner already heard something true.
2. **Anything the predicate is unsure about is CONTENT, not filler** — and
   calling content "filler" costs one extra beat while calling filler
   "content" costs the owner an answer. Every entry in
   `FILLER_CLAUSE_PREFIXES` is a phrase `gpt-realtime-2.1-mini` actually
   produced in live_run_1 or in R6's own live sessions; none is invented.

**R6's fix is narrowed, not reverted.** R6's own live announcement —
`"Okay, let's head over to the sidewalk."` — names the destination and commits
to the act, stays SUBSTANTIVE, and its turn is still exactly one beat. That is
pinned in both directions by
`test_the_announcement_R6_measured_still_buys_its_silence` (seed S4) and
`test_a_filler_announcement_is_not_the_turns_answer` (seed S1), and it is
re-proven live in §5.4. What changes is the deliberation form R6 never
measured, which is what the provider actually said for eight suppressed beats.

`_response_speech` is kept BESIDE `_spoke_this_response` rather than replacing
it. The boolean still answers its own question correctly ("did anything at all
come out?") and it is what R6's seeds S9/S10 pin.

## §4 — Mechanism C: the beat the provider refused

The frame still goes up at function-call time. **This is deliberate and it is
the difference between coordinating with R6/R11 and overwriting them.** My
first implementation deferred every beat to `response.done`; it was correct on
the wire and it broke two seeds — R6's S2 anchor
(`test_one_repay_per_reconnect_even_when_two_responses_were_owed`, which reads
`_responses_pending == 2` because a tool turn legitimately has two responses in
flight) and R11's provenance anchor
(`test_the_tag_survives_the_beat_and_clears_when_the_last_response_completes`).
Both encode "a tool turn has two responses outstanding" as a property of this
lane. The card says their seeds must stay green, so the repair is reactive
rather than pre-emptive:

```
function_call  →  answer the call  →  send the beat  →  remember it (_beat_in_flight)
                                          ↓
                       conversation_already_has_active_response
                                          ↓
        un-count the beat, un-owe the response, queue it (_pending_beat)
                                          ↓
                      response.done for the carrying response
                                          ↓
                        ask again, now that nothing is active
```

Three properties fall out, and each is separately seeded:

* the refusal is **spoken** (S9) — the defect that ate three of four e-stop
  rejections;
* the refused create no longer **leaks** a `_responses_pending` (S10) — which
  is what made live_run_1's single stall, 48 s later, and is therefore also
  why its one narrated rejection was narrated at all;
* a beat that dies with its session is **counted and said** rather than silent
  (S11, `tool_beats_lost` + a ledger note naming the tool and the reason).

**Attribution is stated honestly rather than claimed to be exact.** The
provider names the ACTIVE response in the message, not the refused one, so this
cannot be matched by id: the rule is "a beat is in flight and the provider says
a response is already active". The beat is sent microseconds after the frame
that opened the window, which is why it is the overwhelmingly likely candidate;
if it is ever wrong the cost is one extra beat, never a silence. `S12` seeds the
opposite error — an attribution wide enough to claim a rate limit.

**R15's contract is honoured, not duplicated.** `runtime._whisper_refusal`'s
docstring says: *"Refusals that DO have a tool call in flight still do not come
through here: a `rejected` broker result is the case `lane._beat_reason`
refuses to go quiet on, so the model already says it in the same turn, and
saying it twice was never the fix."* R19's job was to make that sentence true on
the wire. A second always-band channel for the same fact was considered and
deliberately NOT built — see §7 deviation 3 and §9 risk 2.

## §5 — Live proof

Five sessions, one process and one monotonic clock each. Everything real: the
headless MuJoCo static city, the real `RobotRuntime`, the real
`DeterministicIntentRouter`, the real `RealtimeToolBroker`, the real whisperer,
and the real provider `gpt-realtime-2.1-mini` on a live WebSocket. Nothing
injected, nothing stubbed. Harness `<scratchpad>/r19/live_r19.py`; reports
`<scratchpad>/r19/r19_live_<scene>_<STAMP>.json`.

The scorer in the harness is **independent of the fix**: it reads the ledger
and applies its own filler regex, so the proof is not the lane marking its own
homework.

### 5.1 Scene A — the exact live_run_1 sequence, answered (`rt_0a8b76cd4f04`)

```
t=14.491  owner  How's your battery?
t=16.092  robot  "Battery is at 90 percent and normal."
t=28.502  owner  So, what do you remember about me?
t=29.703  robot  "Let me think back over what I know about you and then I'll share it."
t=30.904  robot  "Nothing is recorded about that yet."
t=42.515  owner  What are you doing right now?
t=43.716  robot  "Good question—let me check what I'm doing right now."
t=44.717  robot  "Status: inactive. I'm not following, navigating, or doing a
                  gesture. I'm just idle."
```

**The battery figure live_run_1 never spoke is the first and only thing this
run said about it** — one row, no filler at all. The other two turns show the
mechanism working exactly as designed: the provider co-emits its deliberation,
the lane no longer accepts that as the turn's speech, and the beat that follows
carries the answer instead of more deliberation. `broker_calls =
[get_status ok, recall_memory ok, get_status ok]`, `tool_beats_requested 3,
suppressed 0, refused 0, lost 0, stalls 0, server_errors 0`. **$0.050545.**

### 5.2 Scene B — a latched e-stop, every rejection narrated (`rt_f0b46bbaca3b`)

The e-stop is latched by the runtime before a word is spoken
(`emergency_stopped=True` confirmed from `snapshot()`), which is live_run_1's
14:28:19 state.

```
t=1.003   owner  Go to the bench.
t=3.163   robot  "Okay, I'll try to head to the bench safely, then I'll let you
                  know what happened."
t=4.164   robot  "I can't move yet because the emergency stop is latched, so the
                  movement command was dropped."
t=15.972  owner  Wave at me, and then go to the bench.
t=17.774  robot  "I'll wave first, then try to head toward the bench and see what happens."
t=18.574  robot  "The wave was rejected because the emergency stop is still
                  latched, so nothing started."
```

**2 of 2 rejections narrated.** live_run_1 narrated 1 of 4, and only by
accident. Note the first announcement is verbatim the broken promise §f of the
scoring complains about — *"then I'll tell you what happened"* — and this time
it is kept, 1.0 s later. `tool_beats_requested 2, suppressed 0`. **$0.033571.**

Scene D (`rt_4f489a2773de`) is the same shape for `set_pose`: *"It didn't start
sitting because of an emergency stop—so nothing happened yet."* **$0.018927.**

### 5.3 Scene C — the memory question (`rt_33fe31b6e796`), and a finding

```
t=0.309   owner  My name is Jae, and my favourite spot is the willow by the river.
t=14.322  owner  What do you remember about the willow?
t=15.523  robot  "Let me check what I've heard about that willow and then share what comes up."
t=16.123  robot  "Nothing's been recorded yet about the willow."
```

The narration half is proven — the beat SPEAKS the result instead of dying as
filler, which is precisely what live_run_1 lost, and `ANSWER_BEAT_RULE`'s
empty-result clause is what produced that sentence rather than another "let me
check". **The retrieval half is a separate defect and it is NOT fixed here:**
`runtime._realtime_recall` is an exact-substring search over the realtime
ledger, so a natural question ("what do you remember about the willow?") does
not match the row that contains the answer, and the tool honestly reports
nothing. Reported as a live finding for R18's memory half (§9.4).

### 5.4 Scene E — R6's own live prompt, re-run (`rt_592cb18ff397`)

```
t=0.347   owner  Go to the sidewalk.
t=1.748   robot  "Heading over to the sidewalk now."
          broker  navigate_to ok — "started: the robot is walking to sidewalk"
```

`tool_beats_requested 0, tool_beats_suppressed 1`. **One beat.** R6's fix is
intact live under R19: the announcement carried a fact, so the lane stayed
quiet, and R15's tense-correct detail was the thing the model was reading.
**$0.009500.**

### 5.5 Cost and the owner's stack

| scene | session | what | cost |
| --- | --- | --- | --- |
| A | `rt_0a8b76cd4f04` | battery → memory → status in succession | `$0.050545` |
| B | `rt_f0b46bbaca3b` | latched e-stop, nav + compound rejections | `$0.033571` |
| C | `rt_33fe31b6e796` | the willow memory question | `$0.023432` |
| D | `rt_4f489a2773de` | latched e-stop, pose rejection | `$0.018927` |
| E | `rt_592cb18ff397` | R6's successful navigation turn | `$0.009500` |
| | | **total** | **`$0.135975`** |

**The owner's stack was not running** for the whole card — nothing listening on
8765 or anywhere in 87xx/88xx, checked at the start. No HTTP request of any kind
left this session: not even a read-only GET, because there was nothing to GET.
`~/.config/parcel/realtime.yaml` was never read or written; each session used a
scratch lane config of its own. Each used a COPY of `configs/robot.yaml` with
only `memory.path` redirected into the scratchpad (R5 deviation 6), so the
owner's `parcel_memory.sqlite3` gained no rows. The credential was loaded with
`set -a; . ~/.config/parcel/realtime.env; set +a` and never printed, asserted
against or written anywhere.

### 5.6 What the live proof does NOT show

**The refusal race (mechanism C) cannot be reproduced in `mode: text`, and I
did not pretend otherwise.** All five sessions ran `refused 0, deferred 0,
lost 0, server_errors 0, stalls 0` — the carrying response closes within a
millisecond of the function call, so the beat wins the race every time. That is
exactly what §0.4 predicts and it is why R6 and R15, both proven in text mode,
never saw it. Scene D was written to force the 14:29:11 shape (two calls in one
response) and the mini tier declined to emit two: one call per response, every
time, in text mode. So mechanism C's repair rests on live_run_1's own artifacts
for the DEFECT and on offline seeds S9–S12 for the FIX, and the first
`mode: audio` run is what will confirm it end to end. Named in §9.1.

## §6 — Gate and seeds

### Gate, verbatim, after the final edit

Two full gate runs were taken. The first (`20:43:17Z`, `6854 passed`) scored
the source tree as it now stands; this one is after the last test-file edit
(the three tests written to anchor seeds S2/S16/S18 and the S21 parametrise
fix), and it is the one that counts. Read before pasting.

```
CI GATE — tier=commit  (2026-08-20T21:00:08Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.46s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.33s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6861 passed, 9 skipped, 42 deselected, 5 warnings in 267.86s (0:04:27)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 280.7s
```

**6780 → 6861 passed, +81 = exactly the 81 cases in
`tests/test_realtime_answer_beat.py`** (27 test functions; the difference is
parametrisation). 6780 is R17's closing number
(`scrum/20260820/task_6/R17_STATUS.md`); the card quotes 6732, which is R16's
(`task_5`) — R17 landed between. `9 skipped / 42 deselected` is unchanged from
R17, so no test was removed, skipped or deselected to get here. `ruff` is at its
pinned baseline of 7 with `new 0`; all seven pre-existing violations are in
`camera_channel/` and `detection_adapter/`, untouched by this card. The frozen
digest sentinels and release-parity being byte-identical is the mechanical
confirmation that nothing under `evals/` or the packaged assets moved.

### Seeds — 23, all RED, R9 session-B + AUDIT_R12_R16 §register 1

Harness `<scratchpad>/r19/seed_r19.py`. ONE startup snapshot of the three
touchable source files; per seed: repair drift, mutate exactly one SOURCE file,
**purge every `__pycache__` under `src`**, **verify a fresh-interpreter canary
actually sees the mutation**, run the named pytest target, restore in a
`finally`, purge again, assert byte-identical. A whole-tree check closes the
run. No test, config or eval file is ever mutated.

| # | Seeded defect | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- |
| S1 | filler counts as substantive again (R6's condition, unnarrowed) | **RED** | 1 failed, 2 warnings in 0.45s :: test_a_filler_announcement_is_not_the_turns_answer |
| S2 | the substantive floor is removed: any one word is an answer | **RED** | 3 failed, 2 passed, 2 warnings in 0.46s :: test_a_two_word_remainder_is_an_acknowledgement_wearing_a_coat[Sure,, test_a_two_word_remainder_is_an_acknowledgement_wearing_a_coat[Okay,, test_a_two_word_remainder_is_an_acknowledgement_wearing_a_coat[Hmm, |
| S3 | the deliberation prefixes are dropped: 'let me check' is content again | **RED** | 5 failed, 8 passed, 2 warnings in 0.47s :: test_the_filler_the_robot_actually_said_is_not_an_answer[Okay,, test_the_filler_the_robot_actually_said_is_not_an_answer[Let, test_the_filler_the_robot_actually_said_is_not_an_answer[Let, test_the_filler_the_robot_actually_said_is_not_an_answer[Nice |
| S4 | R6's direction 1 reverted: EVERY tool turn gets a beat again (two beats) | **RED** | 1 failed, 2 warnings in 0.44s :: test_the_announcement_R6_measured_still_buys_its_silence |
| S5 | an answer tool is suppressible again: the exemption is by omission only | **RED** | 2 failed, 2 warnings in 0.45s :: test_an_answer_tool_is_never_suppressed_even_when_named_a_receipt[get_status], test_an_answer_tool_is_never_suppressed_even_when_named_a_receipt[recall_memory] |
| S6 | the in-band answer mark is ignored: the lane trusts its name list only | **RED** | 1 failed, 2 warnings in 0.44s :: test_a_result_that_declares_itself_an_answer_is_never_suppressed |
| S7 | the answer beat is never told to say the answer | **RED** | 1 failed, 2 warnings in 0.44s :: test_the_answer_beat_is_told_to_say_the_answer |
| S8 | the beat rule stops forbidding the deliberation opening | **RED** | 1 failed, 2 warnings in 0.46s :: test_the_result_beat_rule_forbids_the_deliberation_opening |
| S9 | a beat the provider refused is never asked for again (the live defect) | **RED** | 1 failed, 2 warnings in 0.46s :: test_a_beat_the_provider_refused_is_asked_for_again |
| S10 | the refused beat leaks a response nobody will ever answer (the phantom stall) | **RED** | 1 failed, 2 warnings in 0.46s :: test_a_refused_beat_does_not_leave_a_response_owed_forever |
| S11 | a beat lost with its session is silent instead of counted | **RED** | 1 failed, 2 warnings in 0.45s :: test_a_refused_beat_that_dies_with_the_session_is_counted_and_said |
| S12 | any server error claims the in-flight beat (attribution too wide) | **RED** | 1 failed, 2 warnings in 0.47s :: test_an_error_that_is_not_about_a_beat_leaves_the_beat_alone |
| S13 | the broker stops marking its answer results (R15's stamp rule, undone) | **RED** | 2 failed, 5 passed, 2 warnings in 0.45s :: test_the_broker_stamps_its_answer_tools_and_only_those[get_status], test_the_broker_stamps_its_answer_tools_and_only_those[recall_memory] |
| S14 | a motion tool is declared an answer tool (the two sets overlap) | **RED** | 1 failed, 2 warnings in 0.45s :: test_the_two_classifications_do_not_overlap |
| S15 | an activity that expired undelivered is silent again (the sit that never sat) | **RED** | 1 failed, 2 warnings in 0.40s :: test_an_activity_that_expired_undelivered_is_narrated |
| S16 | a stale expiry claims a LATER request's mark (the id ledger removed) | **RED** | 1 failed, 2 warnings in 0.41s :: test_an_old_expiry_never_claims_a_later_requests_ending |
| S17 | an expiry nobody asked for is narrated (R15's mark ignored) | **RED** | 1 failed, 2 warnings in 0.40s :: test_an_expiry_nobody_asked_for_stays_silent |
| S18 | every ending in the coordinator's window is reported as never having run | **RED** | 1 failed, 2 warnings in 0.39s :: test_an_ending_that_is_not_an_expiry_is_left_to_its_own_reporter |
| S19 | the never-ran fact reuses R15's 'stopped before it finished' wording | **RED** | 1 failed, 2 warnings in 0.40s :: test_an_activity_that_expired_undelivered_is_narrated |
| S20 | R6 seed S7 restored: the failure-path tool turn goes silent | **RED** | 3 failed, 1 warning in 0.29s :: test_a_call_that_did_not_succeed_is_always_narrated[deferred-Deferred, test_a_call_that_did_not_succeed_is_always_narrated[dropped-the, test_a_call_that_did_not_succeed_is_always_narrated[rejected-motion |
| S21 | the answer-tool set is emptied (R6's exemption by omission, alone again) | **RED** | 2 failed, 2 warnings in 0.44s :: test_an_answer_tool_is_never_suppressed_even_when_named_a_receipt[get_status], test_an_answer_tool_is_never_suppressed_even_when_named_a_receipt[recall_memory] |
| S22 | R11 restored: the provenance tag dies before the beat inherits it | **RED** | 1 failed, 1 warning in 0.25s :: test_the_tag_survives_the_beat_and_clears_when_the_last_response_completes |
| S23 | R15 restored: the beat rule loses the present progressive | **RED** | 1 failed, 2 warnings in 0.39s :: test_the_beat_rule_asks_for_the_present_progressive_and_forbids_done |

`whole-tree repair check: 3/3 file(s) byte-identical to the startup snapshot.`
`23/23 seeds RED; 0 not RED.` Full run: `<scratchpad>/r19/seeds_3.txt`.

The card named eight: filler counts as substantive again → **S1** (plus S2, S3
on the predicate itself); answer tool suppressed → **S5** (plus S6 for the
in-band mark and S21 for the name list); rejection unnarrated → **S9** (plus
S10, S11, S12 for the accounting and the attribution); expiry silent → **S15**
(plus S16–S19); R6's two-beat regression both directions → **S4** (silence must
survive) and **S1** (silence must not be bought with filler). S20/S22/S23 are
R6's, R11's and R15's own invariants re-seeded from inside this card, because
"their seeds stay green" is worth more when this card can also break them on
purpose.

### The two earlier sweeps, and why they are reported

`seeds_1.txt` came back **17/23**, and every one of the six is in this document
because each was real information rather than a harness excuse:

| seed | first result | what it actually said |
| --- | --- | --- |
| S2 | GREEN | the corpus test is all-filler lines, so the word FLOOR never binds on it. Wrote `test_a_two_word_remainder_is_an_acknowledgement_wearing_a_coat` — "Sure, no problem." is an acknowledgement in a coat — and re-targeted. |
| S8 | GREEN | my mutation deleted the wrong half of a concatenated string and left the asserted phrase intact. A badly-aimed seed, re-aimed. |
| S11 | **UNANCHORED** | the canary refused it: the canary string appears in two methods, so the harness could not prove the interpreter was reading the mutation. This is the register's §1 machinery doing its job, and it is why UNANCHORED exists as a verdict. |
| S16 | GREEN | the id ledger is NOT what makes an expiry speak once — the one-shot mark is, and R11's dedup window is behind that. What the ledger uniquely prevents is a stale `recent` row claiming a LATER request's mark, which is only visible in the whisperer's decision log. New test asserts on `decision_rows()`, because "offered and deduplicated" and "never offered" look identical from the lane. |
| S18 | GREEN | the completed-activity path claims its mark inside the same `_step_activities` call, before the record reaches `recent`, so the status filter never had to hold. The path where it does hold is `ActivityCoordinator.clear()` — an e-stop retires a pending proposal as `cancelled` and leaves the mark armed. New test drives that. |
| S21 | GREEN | **the strongest single result in the sweep.** R6's own S8 mutation — naming `get_status`/`recall_memory` as receipt tools — no longer reproduces its defect, because R19's answer rule catches them first. Protection-by-omission has been replaced by a positive rule, which was the point of the card. The seed was re-cut at `DEFAULT_ANSWER_TOOLS` itself, and that goes RED. |

`seeds_2.txt` came back 21/23 (S16 and S21 still GREEN); `seeds_3.txt` is the
final sweep against the tree the gate scored.

## §7 — Deviations, each with its reason

1. **The card's root-cause hypothesis is wrong and I said so rather than
   working around it** (§0.1). "Determine exactly which condition drifted"
   presumes one did; none did. `get_status` and `recall_memory` had their beats
   REQUESTED in live_run_1, and the arithmetic that shows it is reproducible
   from the artifact in one line. The card's *prescription* — filler must not
   count as speech, answer tools must never be suppressible — is right anyway
   and is implemented in full; but an auditor reading the card would otherwise
   go looking for a drifted `DEFAULT_RECEIPT_TOOLS` that is byte-identical to
   R6's. The scoring note in `results.json` q23 and headline 2 of the run
   README should be corrected; I have not edited `evals/` to do it (§8).
2. **The beat is still SENT at function-call time.** The protocol-correct fix
   is to wait for `response.done`; I wrote that first, and it broke R6's seed
   S2 anchor and R11's provenance anchor, both of which encode "a tool turn has
   two responses outstanding" (§4). The card says those seeds must stay green,
   so the repair is reactive — detect the provider's refusal, un-count it,
   re-offer when the conversation is free. It fixes the same defect and it is
   strictly additive to both cards. If a future card is allowed to change that
   invariant, deferring is the tidier shape and the machinery is already here.
3. **No second always-band channel for tool rejections was built**, although
   card item 4 calls a rejection "R11 always-band material". R15's
   `_whisper_refusal` docstring already RULES OUT that duplication in as many
   words, and it is right: the lane's narration floor refuses a whisper while a
   response is pending or playing, so a duplicate offered at rejection time is
   dropped anyway (live_run_1: `narration_floor_refused: 9`), and a duplicate
   that DID land would have the dog say the same refusal twice. The card's
   requirement — a rejected tool call is always narratable — is met by making
   the beat reliable and pinned by
   `test_a_call_that_did_not_succeed_is_narrated_for_every_tool`, 21 cases over
   the whole surface × three non-ok statuses. The re-offer-later gap is R15's
   own §9.2 open risk and is named again in §9.2.
4. **`_narrate_activity_terminal` grew a keyword-only `started=` parameter**
   rather than a new method. R15 owns that method and its two arms are correct
   for a body that MOVED; an expired proposal is a body that never moved, and
   R15's own tense discipline is the argument for a third fact rather than a
   reused one. Default `True` keeps every existing caller byte-identical.
5. **Expiry is polled from `runtime.py`, not fixed in the coordinator.**
   `ActivityCoordinator._expire` is where the event actually happens, and
   returning the retired records from it would be three lines. `core/
   activities.py` is outside this card's OWNS, so the runtime polls the
   coordinator's own `recent` window instead — read-only, bounded to the 20
   entries the coordinator keeps, and guarded by
   `test_the_coordinator_still_calls_a_timed_out_proposal_expired` so a rename
   there fails loudly instead of silently switching the narration off.
   Returning the records is the tidier seam and is named in §9.3.
6. **A new test FILE rather than additions to three existing ones.** The claim
   spans the lane, the broker and the runtime and only means anything as one
   claim, and the file is where live_run_1's ledger rows are quoted verbatim so
   the next person to read the rule reads the session that produced it. No
   existing test was modified, weakened or deleted by this card — R6's, R11's
   and R15's files are byte-identical to how it found them.
7. **Five live sessions, not one.** A is the card's required sequence; B and D
   are the latched-e-stop rejection in two tool classes; C exists because A's
   memory answer came back empty and it was worth knowing whether that was the
   narration or the retrieval (it is the retrieval — §5.3); E re-runs R6's own
   successful navigation turn, because a card that narrows R6's rule owes a
   live demonstration that it did not revert it. Total `$0.135975`.
8. **Three seed sweeps, and the first two are reported** (§6). Six seeds were
   not RED on the first pass. Per the house rule I wrote the missing tests
   rather than deleting the seeds, and one of the six — S21 — is reported as a
   GREEN that is a RESULT rather than a gap.

## §8 — What this does NOT prove (does_not_prove)

* **No human has heard any of this.** Every session was `mode: text` with no
  microphone and no speaker. The defect was found by a human speaking to the
  robot; the fix is proven in typing.
* **The refusal race was not reproduced live** (§5.6). `refused 0` in all five
  sessions. Mechanism C's defect is evidenced by live_run_1's own
  `recent_server_errors`; its repair is evidenced by seeds S9–S12 only.
* **Only the mini tier was exercised.** `gpt-realtime-2.1` may narrate the same
  results differently. The mini tier is the one the owner's runs use.
* **The filler predicate is a word list, and word lists are never complete.**
  Every entry is a phrase the model actually produced, but the next session can
  invent a deferral that is not in it, and that one will buy silence again. The
  failure direction is the only real defence: it costs one beat to be wrong the
  safe way and an answer to be wrong the other way, so the list is biased
  toward calling things filler. `FILLER_CLAUSE_PREFIXES` is public and
  additions are one line.
* **The 3-word floor is a judgement, not a measurement.** It was chosen against
  the corpus in this file and R6's live sessions; nobody has A/B'd it.
* **`recall_memory` still cannot find what it was told** (§5.3). R19 makes the
  robot SPEAK the recall result; it does not make the recall result correct,
  and in scene C the correct answer was in the ledger two turns earlier.
* **The e-stop still does not announce itself when it latches.** live_run_1's
  headline finding — 84 s and 18 turns with no disclosure — is only half
  addressed here: every REJECTED tool call now speaks, so an owner who asks for
  anything physical learns immediately. An owner who asks for nothing physical
  still will not be told. That is the other candidate card in §b of the run
  README and it is not this one.
* **`broker.executed` is still not "the robot did it."** R19 gives the expiry
  a voice; it does not change what `executed` means, and the scoring's
  instruction to read it as "dispatched" stands.
* **The scoring artifacts were not corrected.** `results.json` q23 and README
  headline 2 still say the suppression policy ate the battery figure. `evals/`
  is not this card's to write and the frozen-digest gate would notice; the
  correction is §0.1 and it is owner-gated.

## §9 — Open risks and owner-gated items

1. **The first `mode: audio` run is the real test of mechanism C**, and it is
   the run that should be watched. Three numbers say whether it worked:
   `tool_beats_refused` (how often the race is lost — expected to be non-zero
   in audio and zero in text), `tool_beats_deferred` (how many of those were
   recovered — must equal `refused`), and `tool_beats_lost` (**must be zero**;
   any value is a refusal or an answer the owner never heard).
2. **A beat that dies with its session is still lost, not re-offered.** It is
   counted and written to the ledger now, which is the difference between a
   known gap and an invisible one, but the sentence is gone. Re-offering across
   a reconnect means replaying a `function_call` from a conversation that no
   longer exists, which is a design question about what the new session is even
   being asked. Same shape as R15's §9.2.
3. **The expiry poll reads the coordinator instead of being told.**
   `ActivityCoordinator._expire` could return what it retired in three lines
   and every caller would be better off. Owner-gated because
   `core/activities.py` is outside this card.
4. **`_realtime_recall`'s exact-substring match is the remaining half of F4**
   (§5.3), and R18's memory work depends on it. The narration defect this card
   fixes was hiding it: until now the robot never said the recall result, so
   nobody could see that the result was empty for a question the ledger could
   answer. Recommend it as R18's first item, with scene C as its reproduction.
5. **The filler list and the SI are now saying overlapping things.** The card
   forbade touching the SI and I did not, so the anti-deliberation instruction
   lives in `RESULT_BEAT_RULE` and applies only to the beat. The pre-call
   announcement the provider co-emits is still filler and still costs a turn's
   worth of audio — R5 proved it is not suppressible under three SI wordings on
   this tier. **Reported as SI-v3 / model-tier input, exactly as card item 3
   asks**: the habit persists, the beat now routes around it, and removing the
   habit itself needs either a different tier or an SI experiment that is not
   this card's.
6. **Two extra beats now cost money that R6 saved.** Every filler-announced
   receipt turn is one more billed `response.create` than yesterday. Scene A's
   three-question sequence cost `$0.0505`, so the scale is right, but
   `tool_beats_requested` climbing against `tool_beats_suppressed` is the
   number an operator should watch, and the owner's per-minute whisperer knob
   does not gate it.
7. **Nothing was committed, staged or stashed.** `git stash list` is empty and
   the other cards' uncommitted work is exactly as this session found it.

## §10 — Restart required

`lane.py`, `tool_broker.py` and `runtime.py` are not hot-reloadable. The
owner's stack must be relaunched to pick up the answer beat, the filler gate,
the refused-beat repair and the expiry narration:

```
./scripts/launch_stack.sh
```

No config change is needed — every new behaviour is on by default. The two new
constructor arguments (`answer_tools`, `answer_beat_instruction`) exist for
tests and for a future build with a different tool surface, and follow R6's
pattern exactly: `answer_beat_instruction=None` still asks for the beat.

## §11 — Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r19/`

| File | What |
| --- | --- |
| `seed_r19.py` | the 23-seed harness (snapshot → mutate one source file → purge `__pycache__` → fresh-interpreter canary → named pytest target → restore → purge → byte-identity assert) |
| `seeds_1.txt` / `seeds_2.txt` / `seeds_3.txt` | all three sweeps; `seeds_3.txt` is the final one, against the tree the gate scored |
| `gate_final.txt` | the gate run pasted in §6 |
| `live_r19.py` | the live harness (in-process runtime, headless MuJoCo static city, scratch memory db, independent filler scorer) |
| `r19_live_{A,B,C,D,E}_<STAMP>.json` | the five machine-readable session reports: turns, per-turn verdicts, broker calls, lane snapshot, whisperer decision rows, spend |
