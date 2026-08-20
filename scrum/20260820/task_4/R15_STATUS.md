# R15 — "done" means done: the completion over-claim, closed

**Card:** `scrum/20260820/task_4/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable · **Date:** 2026-08-20

---

## §0 — The three ledger rows this card exists because of

`evals/20260820/owner_session_1/ledger.json`, rows 34–36, verbatim, and the
`created_at` values are the ledger's own:

```
14:12:26  user       walk in a small counterclockwise circle around me
14:12:26  assistant  Okay—I'll make the requested local circle around you safely.
14:12:27  assistant  Done—I made a small circle around you, and it was okay.
```

Row 35 is `RealtimeToolBroker._circle_owner`'s `detail` — the runtime's own
admission acknowledgement (`runtime._plan_acknowledgement`, `goal.relation ==
"orbit"`), passed through verbatim. Row 36 is R6's post-tool beat narrating it.
**One second.** A lap the dog had barely started was reported to a human being,
out loud, as finished, and the stack's own standing guardrail ("never claim a
completed physical action — the robot reports that itself") was broken not by
the model inventing anything but by being handed a promise and asked to say
what came back.

R5's audit had already endorsed the mild form of exactly this as a
carry-forward — broker detail `"Accepted paw_wave for the next control tick"` →
model: *"I waved. My paw moved."* (`scrum/20260818/task_2/AUDIT_R5_FABLE.md`
item 2). The owner session showed the full form.

**The diagnosis, stated as a shape rather than a bug:** navigation had two
halves and the activities had one. `navigate_to` says "the trip started" and
then, tens of seconds later, `_narrate_mission_terminal` says how it ended.
`circle_owner` and `play_gesture` had only the first half — no sentence for the
ending existed anywhere in the stack — so the model filled the silence with the
only material it had, which was the promise.

R15 gives the activities their second half, and marks the first half with its
tense so the model cannot mistake one for the other.

---

## §1 — What changed

| File | Change | Card item |
| --- | --- | --- |
| `src/parcel_robot/realtime/tool_broker.py` | `ACTIVITY_TOOLS`; `TENSE_STARTED`/`TENSE_WAITING`/`TENSE_NOT_STARTED` stamped in ONE place (`handle`); `finished: False` and `COMPLETION_NOTE` on every activity answer; the five per-tool details recomposed as present-progressive FACTS with the runtime's promise moved to `admitted`; `detail_tense_violation` (the rule, executable); four tool descriptions told the model never to claim an ending | 1 |
| `src/parcel_robot/realtime/lane.py` | `RESULT_BEAT_RULE` gains ONE sentence (present progressive for started-not-finished work, and never "done"), plus the comment block above it that says why. Wording only — no executable line of the lane changed | 3 |
| `src/parcel_robot/runtime.py` | `_narrate_activity_terminal` (the only place a completed physical action may be reported); `_step_spatial` and `_step_activities` terminals wired into it; `_realtime_gesture` marking door; `_mark_narratable_activity`/`_claim_narratable_activity`; `_claim_orbit_terminal`; `_narrate_finished_activity`; `_stop_spatial_locked` drops a stale mark; `_whisper_refusal` gets the caller R11 built it for | 2 |
| `tests/test_realtime_completion_tense.py` **(NEW)** | 36 tests over all three layers | DoD |
| `tests/test_realtime_tool_broker.py` | 4 assertions updated to the tense contract (details below) | DoD |

`prompting.py`/SI, `protocol.py`, `ingress.py`, `whisperer.py` and the yield
policy are **untouched by this card** — not one byte of any of them is in this
diff. The whisperer is used, not modified: the
activity terminals ride its existing `mission_ended` and `refusal` classes.

---

## §2 — Item 1: the result the model reads has a tense

### 2.1 One stamp, one place

`RealtimeToolBroker.handle` is the last thing that touches every answer, and
that is where the tense is stamped:

```python
result = self._dispatch(name=str(name), arguments=str(arguments))
if str(name) in ACTIVITY_TOOLS:
    result = _tensed(result)
```

so there is no return path in the class — including the refusals raised before
an argument is even parsed — that can hand the model an untensed activity
answer. `TENSE_BY_STATUS` maps `ok → started`, `deferred → waiting`,
`dropped/rejected → not started`. **There is no fourth tense and there is no
"finished"**: the broker returns while the body is still moving, so there is no
disposition for which a completed physical action is a thing this module could
truthfully report. `finished` is unconditionally `False` for exactly that
reason, and that is a structural claim rather than a value.

`ACTIVITY_TOOLS` is identical to `MOTION_TOOLS` today and is deliberately not an
alias: the two sets answer different questions (*may this commit the body* vs
*does this describe work that is still happening*), and a future read-only tool
that nevertheless starts something would belong to one and not the other.

### 2.2 The promise moved out of the mouth and onto the record

R4-lite's Defect C already established the rule for `navigate_to` — "the model
does not need the robot's script; it needs the fact" — and put the admission
sentence under `admitted`. R15 applies it to the other four:

| tool | before (what the model read) | after |
| --- | --- | --- |
| `circle_owner` | `Okay—I'll make the requested local circle around you safely.` | `started: the robot is walking a counterclockwise circle around you, 1 of a lap` |
| `play_gesture` | `Accepted paw_wave for the next control tick` | `started: the paw_wave gesture is running on the robot's body` |
| `set_pose` | `Accepted sit for the next control tick` | `started: the robot is settling into the sit pose` |
| `follow_owner` | `Okay—I'll follow you safely.` | `started: the robot is keeping station on you and walking with you` |
| `navigate_to` | `mission accepted: the sidewalk` | `started: the robot is walking to the sidewalk` |

`navigate_to` was not broken and is changed anyway: "mission accepted" is
tense-NEUTRAL — accepted by whom, and is the robot walking yet? A rule that
holds for four tools out of five is a rule a sixth tool falls out of.

Non-`ok` dispositions keep the runtime's own reason verbatim, because the reason
is the half that explains itself — they just wear the tense in front of it
(`not started: Gesture is cooling down`, `waiting: Deferred paw_wave while
navigation is active`).

`get_status` and `recall_memory` are untouched: their result IS the answer, and
"started: current robot state" would be a lie of a different kind.

### 2.3 `detail_tense_violation` is a predicate, not a sanitiser — on purpose

The rule is executable (`missing tense marker` / `completion language: 'done'` /
`speaks in the robot's own voice: 'okay'`) and the tests run it over every tool ×
every disposition. It deliberately does NOT run inside the broker. A sanitiser
would make the regression invisible: the seed that puts completion language back
into a detail would come back GREEN, and the suite would be pinning the scrubber
instead of the wording. Seeds S1/S2 are the reason this is stated rather than
assumed.

---

## §3 — Item 2: completion comes from the body

### 3.1 What I found, against the card's premise

The card says "R10 built orbit abort narration; verify the SUCCESS terminal
narrates too". **Neither terminal narrated.** R10 built the *detection* — the
mid-orbit annulus lookahead in `navigation/spatial.py`, which ends the behaviour
with `state="failed"`, `reason="orbit_annulus_blocked"` — and `_step_spatial`
turned that into an `_emit("spatial", …)` mission-log row and nothing else. The
model was never told, on either outcome. R10's own status doc §5.4 records the
orbit REFUSAL at admission time reaching the model (as a `rejected` tool
result), which is a different event on a different path.

R11 had already built the door and named the caller it was waiting for, in
`_whisper_refusal`'s docstring: *"NOTHING IN PRODUCTION CALLS THIS YET … the
door is here, tested and banded, for the refusals that have no tool call in
flight — a mid-behaviour safety abort is the obvious next one."* R15 is that
caller. The docstring is updated to say so rather than left claiming it has none.

### 3.2 The wiring

`_narrate_activity_terminal(activity, completed, reason)` is the only place in
the stack that may report a completed physical action:

* **completed** → `StateEvent(kind=KIND_MISSION_ENDED, hint_carried=True)` with a
  fact that carries its own speech act — *"…has now FINISHED. This is the moment
  it is true to say it is done — tell the owner it is done."* `hint_carried`
  because the generic `mission_ended` hint ("tell the owner you stopped and
  why") is the wrong sentence for a lap that went perfectly; this is the same
  mechanism R10's arrival fact uses.
* **stopped short** → `_whisper_refusal`, i.e. `KIND_REFUSAL`, whose stock hint
  ("say the refusal out loud, with the reason") is exactly right — from the
  owner's side, a circle that stopped at 0.32 laps IS a refusal of what they
  asked for.

**No new event class.** The whisperer's band table is `MUST NOT TOUCH` on this
card, and an activity terminal is precisely the "terminal" class that table
already declares critical (`CRITICAL_KINDS`, budget-exempt, min-gap-exempt).
Both arms therefore reach the owner without spending the per-minute knob, and
both are still counted so the panel's number stays honest.

Terminals are collected UNDER the command lock and narrated AFTER it is
released, in both `_step_spatial` and `_step_activities` — the narration path
takes the lane's lock, and a control-loop step must not hold the command lock
across another subsystem's. `_step_activities`'s dispatch-cancelled arm changed
from `return` to `else` for that reason; the control flow is identical (the
dispatch below is skipped exactly when it was skipped before) and the method now
has one exit.

### 3.3 The mark — why every terminal does NOT narrate

`_speech_emote` runs `_brain_gesture` for **every inline `[emote:…]` tag the
robot authors inside its own sentences**. Narrating those endings would have the
dog interrupting itself to announce a nod it never said it was making, at one
billed `response.create` per tag. `ActionProposal.trigger` cannot tell them
apart — the inline path and the hosted path both use `explicit_command`.

So a terminal is narratable only when the OWNER asked for the activity through
the conversation surface. Two one-shot marks carry that:

* `_narratable_activity` — set by `_realtime_gesture` (a new marking wrapper
  around the unchanged `_brain_gesture`, now the broker's `gesture` door) and by
  `_realtime_pose`, and **only when the coordinator actually took the request**
  (`Accepted`/`Deferred`); a rejected proposal has no ending to report and a
  mark left behind would be claimed by the next unrelated activity.
* `_narratable_orbit` — set by `_realtime_orbit` AFTER admission succeeds, and
  dropped by `_stop_spatial_locked` so an e-stop or a new command cannot leave a
  stale mark for the next spatial behaviour's terminal to eat.

Both claims fail toward silence. Seeds S8, S11 and S12 attack each of these
directly.

---

## §4 — Item 3: the beat rule

One sentence added to R6's `RESULT_BEAT_RULE`, and nothing else in `lane.py`
changed:

> …If the result says the work has only STARTED, say so in the present
> progressive — the robot is doing it right now — and never say it is done,
> finished or that you have already made, walked or performed it: the robot
> reports the ending itself, when it actually ends.

R6's four original claims survive intact (one short spoken sentence; no
restating the plan; no promising a next step; say what stopped a refusal). It is
still composed as `session instructions + "\n" + RESULT_BEAT_RULE`, so the
persona and every guardrail still ride the beat — the R6 property
`test_the_beat_carries_the_whole_prompt_not_just_the_result_rule` is unchanged
and still green. **SI is untouched**: this is per-response wording about one
result, not a standing rule about who the robot is.


---

## §5 — Live proof (card item 4)

Two live sessions, **one process each**, one monotonic clock each. Everything is
real: the MuJoCo static-city sim, the real `RobotRuntime`, the real
`DeterministicIntentRouter`, the real `RealtimeToolBroker`, the real
`SpatialBehaviorController`, the real whisperer, and the real provider
`gpt-realtime-2.1-mini` on a live WebSocket. Nothing is injected and nothing is
stubbed. Harness: `<scratchpad>/r15/live_r15.py`; reports
`<scratchpad>/r15/r15_live_<STAMP>.json`.

### 5.1 Session `rt_0230390c6f29`, stamp `20260820T170933Z` — the model picked a quarter lap

```
t=0.000   owner    Circle around me.
t=3.111   spatial  moving / approach_orbit_ring
t=3.513   robot    "I'm walking around you clockwise in a small arc, about a
                    quarter circle, and it hasn't finished yet."
t=6.721   spatial  orbiting / orbit_owner
t=15.547  spatial  completed / orbit_complete        progress 1.0
t=16.547  robot    "It's done. My circle around you has finished."
```

The broker answer the model read, verbatim from `broker.snapshot()["last"]`:

```json
{"tool": "circle_owner", "status": "ok",
 "detail": "started: the robot is walking a clockwise circle around you, 0.25 of a lap"}
```

**cost $0.021348**, 0 stalls, 0 reconnects.

### 5.2 Session `rt_06c6d7842de0`, stamp `20260820T171044Z` — a full lap, so "tens of seconds" is literal

```
t=0.000   owner    Walk one full lap all the way around me, please.
t=1.442   robot    "Okay, got it—let me get moving around you now."      (announcement)
t=2.244   robot    "It's started. I'm walking a clockwise circle around you,
                    and it hasn't finished yet."                          (the beat)
t=5.854   spatial  orbiting / orbit_owner
t=48.597  spatial  completed / orbit_complete        progress 1.0
t=49.197  robot    "It's done. The circle around you has finished."
```

```json
{"tool": "circle_owner", "status": "ok",
 "detail": "started: the robot is walking a clockwise circle around you, 1 of a lap"}
```

**cost $0.025723**, 0 stalls, 0 reconnects. **Both sessions together: $0.047071**
(card target: well under $1).

### 5.3 The two timestamps the card asked for

| | owner session 1, 2026-08-20 (the defect) | R15 session 2 (the fix) |
| --- | --- | --- |
| ack | `14:12:26` "Okay—I'll make the requested local circle around you safely." | `t=2.244` "It's started. …and it hasn't finished yet." |
| "done" | `14:12:27` "Done—I made a small circle around you" | `t=49.197` "It's done. The circle around you has finished." |
| gap | **1 s**, with the dog barely moving | **46.95 s**, and the lap was genuinely over 0.6 s earlier |

### 5.4 The ending came through the channel, not from the model's imagination

The whisperer's own decision row, verbatim from the session report:

```json
{"seq": 43, "kind": "mission_ended", "key": "activity_finished:circle around you",
 "band": "always", "forwarded": true, "rule": "critical_bypass",
 "text": "The robot's own systems report that the circle around you it started for
          you has now FINISHED. This is the moment it is true to say it is done —
          tell the owner it is done."}
```

Lane counters for that session: `narrations 1`, `narrations_refused 0`,
`narrations_skipped 0`, `system_initiated_responses 1`. The narration was not
merely counted — R8's refusal echo would have said so — and the model's next
sentence is the one above. Meanwhile `suppressed 43 {never_band: 43}`: the
position telemetry that ran under the whole lap reached nobody. The channel is
doing both halves of its job in the same session.

**does_not_prove:** that a HUMAN heard any of this (`mode: text`, no
microphone, no audio); that the same wording survives `gpt-realtime-2.1` (the
full tier was not exercised — the mini tier is what the owner session ran);
that a gesture terminal narrates live (only the orbit was driven end-to-end on
the provider — the gesture terminal is proven offline, by
`test_a_gesture_the_owner_asked_for_is_narrated_when_it_ACTUALLY_ends` and seed
S5); that the mid-orbit ABORT narrates live (no configuration of the static city
boxes this owner in — R10 §5.4 found the same and had to inject at
`backend.observe`; the abort arm is proven offline and by seeds S6/S7).

### 5.5 The owner's live stack was not touched

`:8765` was listening for the whole card (`mode audio`, lane active, session
`rt_debea855e480`). It received exactly **one read-only `GET /api/state`** and
nothing else: no POST, no restart, no config write.
`~/.config/parcel/realtime.yaml` was never read or written — both proofs used a
scratch lane config of their own. Both used a COPY of `configs/robot.yaml` with
only `memory.path` redirected into the scratchpad (R5 deviation 6), so the
owner's `parcel_memory.sqlite3` gained no rows from this card.

---

## §6 — Gate and seeds

### Gate, verbatim, after the final edit

Read before pasting. Run at `17:22:08Z`, **after** the last source edit
(`_narrate_finished_activity`'s activity label). The `17:17:23Z` run before it
was also fully green and is superseded by this one rather than deleted;
`<scratchpad>/gate_r15_final.txt` holds it.

```
CI GATE — tier=commit  (2026-08-20T17:22:08Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.38s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              6693 passed, 9 skipped, 42 deselected, 5 warnings in 247.28s (0:04:07)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 260.2s
```

**6657 → 6693 passed, +36 = exactly the 36 tests in
`tests/test_realtime_completion_tense.py`.** 6657 is R14's closing number
(`scrum/20260820/task_3/R14_STATUS.md`), and `9 skipped / 42 deselected` is
unchanged from it — no test was removed, skipped or deselected to get here. The
card quotes 6601 as the chain's entry baseline; R12/R13/R14 landed between, and
the arithmetic above is against the number this card actually started from.
`ruff` is at its baseline of 7 with 0 new violations; all seven pre-existing
violations are in `camera_channel/` and `detection_adapter/`, which this card
does not touch.

### Seeds — 12, all RED, R9 session-B standard

ONE startup snapshot of all three touchable source files; per-seed mutate → named
pytest target → restore in `finally`; per-seed byte-identical restore assertion;
a repair pass before each seed if the file has drifted; and a final **whole-tree**
check against the startup snapshot. Harness: `<scratchpad>/r15/seed_r15.py`; full
run `<scratchpad>/r15/seeds_full.txt`. No test, config or eval file is ever
mutated.

| # | Seeded defect | File | Target test | Result |
| --- | --- | --- | --- | --- |
| S1 | completion language restored in the circle detail (`the … circle around you is complete`) | `tool_broker.py` | `test_every_accepted_activity_says_it_STARTED_and_never_that_it_finished` | **RED** — 1 failed |
| S2 | the F2 promise put back into the detail (the R10 passthrough, byte for byte) | `tool_broker.py` | `test_the_exact_sentence_that_produced_F2_can_no_longer_reach_the_model` | **RED** |
| S3 | the tense stamp dropped from every activity answer | `tool_broker.py` | `test_a_gesture_that_did_not_start_says_so_in_its_tense` | **RED** — 3 failed |
| S4 | the coordinator's acceptance passed through as the gesture fact | `tool_broker.py` | `test_the_gesture_receipt_is_a_fact_and_not_the_coordinators_acceptance` | **RED** |
| S5 | the activity terminal narration dropped | `runtime.py` | `test_a_gesture_the_owner_asked_for_is_narrated_when_it_ACTUALLY_ends` | **RED** |
| S6 | the orbit terminal narration dropped | `runtime.py` | `test_the_orbit_terminal_is_the_only_thing_that_may_say_the_lap_is_over` | **RED** |
| S7 | an orbit abort narrated as a completion | `runtime.py` | `test_an_orbit_that_aborts_mid_lap_says_it_did_not_finish` | **RED** |
| S8 | every activity terminal narrated, including the robot's own inline emotes | `runtime.py` | `test_the_robots_own_inline_emotes_end_in_silence` | **RED** |
| S9 | the beat rule's tense sentence regressed to R6's wording | `lane.py` | `test_the_beat_rule_asks_for_the_present_progressive_and_forbids_done` | **RED** |
| S10 | `navigate_to` loses its tense (back to `mission accepted: …`) | `tool_broker.py` | `test_the_navigate_detail_is_structured_not_the_legacy_ack` | **RED** |
| S11 | an externally cancelled orbit leaves a stale mark behind | `runtime.py` | `test_an_orbit_cancelled_from_outside_drops_its_mark_rather_than_speaking` | **RED** |
| S12 | a REFUSED proposal is marked as owed an ending | `runtime.py` | `test_a_refused_request_leaves_no_ending_owed` | **RED** (see below) |

`whole-tree repair check: 3/3 file(s) byte-identical to the startup snapshot.`
`all 12 seeds RED, all files restored byte-identically`

The run above (`<scratchpad>/r15/seeds_final.txt`) is against the FINAL tree —
the same bytes the `17:22:08Z` gate scored. The earlier full run
(`<scratchpad>/r15/seeds_full.txt`) is kept because it is where S12's GREEN
happened.

The card named three seeds — completion language restored in a detail (S1),
the terminal narration dropped (S5, S6) and the beat rule tense regressed (S9).

**S12 came back GREEN on the first full run and is recorded here as it
happened.** Its original target was `test_one_ending_is_narrated_once`, whose
second activity goes through `_speech_emote` — a path that never reaches the
marking door — so removing the "`Accepted`/`Deferred` only" condition from
`_mark_narratable_activity` left it passing. Per the house rule I **wrote the
missing test rather than deleting the seed**: `test_a_refused_request_leaves_no_ending_owed`
drives a hosted `set_pose` refused under a latched e-stop (the door that
RETURNS a rejection instead of raising one, which is the only way the seed is
observable at all), then runs the same skill from a non-hosted caller and
asserts silence. S12 then went RED. The first run's GREEN is the reason the
second run's RED means anything.

---

## §7 — Deviations, each with its reason

1. **The card's premise about R10 was wrong and I have said so rather than
   worked around it.** "R10 built orbit abort narration; verify the SUCCESS
   terminal narrates too" — R10 built the abort *detection*, not its narration.
   Neither terminal reached the model. Both are wired here (§3.1). If the card
   meant "R10 built the abort detection", the work is the same; the difference
   matters because an auditor reading the card would otherwise expect to find
   half of this already present.
2. **`navigate_to`'s detail changed although navigation was not the defect.**
   `mission accepted: the sidewalk` was tense-neutral and R15's rule is
   structural (one stamp, one place, all five tools). Leaving one activity tool
   outside the rule is how the sixth tool falls out of it. The cost is one
   updated assertion in `test_the_navigate_detail_is_structured_not_the_legacy_ack`,
   which now pins the stronger sentence, and seed S10 guards it.
3. **Four assertions in `tests/test_realtime_tool_broker.py` were updated, not
   deleted.** `test_a_cooling_down_gesture_is_dropped_with_the_reason`,
   `test_a_deferred_pose_reports_deferred_rather_than_ok`,
   `test_the_navigate_detail_is_structured_not_the_legacy_ack`, and
   `test_a_latched_estop_refuses_both_new_tools_for_the_supervisors_reason` each
   asserted a bare detail string and now assert the tensed one. Every other
   assertion in those tests is untouched, and none of them lost a claim.
4. **`_step_activities`'s dispatch-cancelled arm changed from `return` to
   `else`.** Mechanically entailed by the lock rule: the narration path takes
   the lane's lock and must not run while the command lock is held, so the
   method needs one exit. The control flow is identical — the dispatch below is
   skipped in exactly the cases it was skipped in before — and it is called out
   here because a reviewer scanning the diff sees a re-indented block.
5. **A new test FILE rather than additions to three existing ones.** The claim
   spans the broker, the lane and the runtime, and it only means anything as one
   claim. `tests/test_realtime_completion_tense.py` is where the F2 ledger rows
   are quoted, so the next person to read the rule reads the session that
   produced it.
6. **`circle_owner`/`follow_owner` were NOT added to R6's
   `DEFAULT_RECEIPT_TOOLS`.** The card scopes `lane.py` to "RESULT_BEAT_RULE
   wording only", so this is left alone and named in §9 instead — it is a real
   question and it is R6's, not R15's.
7. **The whisperer's `mission_ended` / `refusal` classes are reused for activity
   terminals.** The band table is `MUST NOT TOUCH`; reusing the class the table
   already declares critical is the way to get the terminal to the owner without
   editing it. The reuse is documented at the call site, not implied.
8. **Two live sessions, not one.** The first let the model choose the lap size
   and it chose a quarter, so the ack→done gap was 13 s. A second session asked
   for a full lap to make the card's "tens of seconds" literal (46.95 s). Both
   are reported; the first is not hidden because it was less impressive.

---

## §8 — What this does NOT prove (does_not_prove)

* **No human has heard any of this.** Both live sessions were `mode: text` with
  no microphone and no audio. The defect was found by a human in a spoken
  session; the fix is proven in a typed one.
* **Only `circle_owner` was driven end-to-end on the live provider.** The
  gesture and pose terminals, the abort arm, and the marking rules are proven
  offline (36 tests) and by seeds S5–S8, S11, S12 — not by a session.
* **Only the mini tier was exercised.** `gpt-realtime-2.1` may narrate the same
  facts differently. The owner session that produced F2 ran the mini tier, so
  this is the tier that matters most, but it is one of two.
* **The tense rule is enforced by tests, not by the broker.** §2.3 argues that
  is correct. It does mean a future contributor who writes a new activity tool
  and a new detail by hand can produce a bad sentence; what they cannot do is
  produce one that the matrix test does not catch, because the matrix iterates
  `ACTIVITY_TOOLS`.
* **A gesture that ends while the model has the mouth is silently dropped.**
  `narrate_event`'s floor gate returns False and the whisperer's slot is given
  back (`RULE_NARRATION_FLOOR_REFUSED`). Nothing re-offers it later. Neither
  live session hit this — `narrations_skipped 0` in both — but a busy
  conversation will, and then the owner hears the beginning and not the end.
  Named in §9.
* **`revolutions: 1` renders as "1 of a lap".** Grammatically odd, factually
  exact; the model said "a clockwise circle around you" and dropped it. Not
  worth a special case, but it is a wording an auditor will notice.
* **Nothing here changes what happens on a REAL body.** The 48.6 s lap is sim
  time on the static city.

---

## §9 — Open risks and owner-gated items

1. **`circle_owner`/`follow_owner` are not in R6's `DEFAULT_RECEIPT_TOOLS`, so
   their answer always gets a beat.** That beat is the sentence that said
   "Done", and in live session 2 it produced two robot sentences before the lap
   started ("Okay, got it—let me get moving around you now." then "It's
   started…"). Now that their endings are narrated separately, they arguably
   satisfy R6's third bullet exactly as `navigate_to` does. **Owner/R6 decision,
   deliberately not taken here** — pinned as a fact by
   `test_the_two_R10_tools_still_always_get_their_beat` so whoever takes it has
   to change the test on purpose.
2. **An ending offered while the model is speaking is lost, not queued.** See
   §8. A one-slot "owed ending" retry is the obvious fix and is a design
   decision about interrupting, not a bug fix.
3. **`follow_owner` has no terminal at all.** Follow runs until something stops
   it, so there is no moment at which "I followed you" becomes true — which is
   why its detail is pure present progressive. But when follow is turned OFF
   nothing tells the model either. Out of scope; worth a card with the pace work.
4. **The mark is keyed on the proposal NAME, not the activity id.** The
   coordinator's id is not returned through `propose_action`. Two same-named
   activities in flight would let the first terminal claim the mark; both claims
   fail toward silence, never toward a false completion, so the failure
   direction is safe. Making `propose_action` return the id is a small change
   that touches a wider surface than this card owns.
5. **`_narrate_activity_terminal` spends a critical-band slot per activity.**
   A conversation full of "sit", "wave", "bow" now costs one billed
   `response.create` per ending. Both live sessions cost ~$0.02–0.03 total, so
   the scale is right, but the owner's cost knob does not gate it (critical
   kinds bypass the budget by design) and that is worth their eyes.
6. **F5's idle-rollover hygiene is still open** (`task_5`), and the 7 rollover
   rows sit directly above the F2 rows in the same ledger.

---

## §10 — Files touched

| File | Lines before → after |
| --- | --- |
| `src/parcel_robot/realtime/tool_broker.py` | 1141 → 1385 |
| `src/parcel_robot/realtime/lane.py` | 1995 → 2007 |
| `src/parcel_robot/runtime.py` | 8488 → 8725 |
| `tests/test_realtime_completion_tense.py` **(NEW)** | 0 → 811 (36 tests) |
| `tests/test_realtime_tool_broker.py` | 4 assertions updated |
| `scrum/20260820/task_4/R15_STATUS.md` **(NEW)** | this file |

Nothing was committed, staged or stashed. No file outside this list was written
by this card; the seed harness's whole-tree check confirms the three source
files are byte-identical to their post-edit state.
