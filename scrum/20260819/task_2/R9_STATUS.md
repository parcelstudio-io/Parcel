# R9 — the owner's e-stop: Space, and "Die Stop" — EXECUTOR STATUS

**Date:** 2026-08-19/20 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Card:** `scrum/20260819/task_2/README.md`

## The owner policy ruling, verbatim

> "Space bar should be the e-stop. In voice command it should be 'Die Stop'."
> — owner, 2026-08-19

That ruling closes the owner-gated wake-word/e-stop question left open by
`AUDIT_R7_FABLE` and unfroze `realtime/ingress.py` for exactly this change.

## Verdict in one paragraph

Both halves are done and both are proven live. The panel's Space bar now latches
the EMERGENCY stop instead of requesting a nominal one, a latched dog raises an
unmissable banner that carries its own release button, and "Die Stop" is a
spoken emergency phrase matched with ASR-shaped tolerance — variants of "die",
any separator or none, anywhere inside the utterance — while the word "stop"
alone stays exact-match, so "let's stop by the store" still stops nothing. Six
live hosted-audio sessions on my own stack (`:8822`, socket `/tmp/parcel_r9.sock`,
`gpt-realtime-2.1-mini`, `mode: audio`) with piper-synthesized speech: the
owner's phrase latched a RUNNING MISSION 4 times out of 4 spoken attempts, the
typed origin latched, the negative sentence did not, and the release path was
exercised end to end four times — refused motion while latched, accepted motion
after release. Total spend **$0.127042**. Sixteen seeds RED, every file restored
byte-identically. **One thing did not go the card's way and is reported as the
top open risk**: the *variant* "Dye stop." never latched live, because this
transcriber drops the leading /s/ of "stop" after an /aɪ/ word ("Dice top",
"die top") — the same failure R7 measured as "Top". Widening the SECOND word is
a grammar change the ruling did not authorise, so it is reported, pinned as a
regression, and left owner-gated.

## The gate — FULLY GREEN, verbatim

Run after the final edit:

```
CI GATE — tier=commit  (2026-08-20T04:59:10Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.58s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              6396 passed, 9 skipped, 42 deselected, 5 warnings in 249.23s (0:04:09)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 262.7s
```

The default suite went from **6269** passing at the start of this card to
**6396** — 127 new tests, no deletions, and `ruff … new 0`. A pre-final run at
`2026-08-20T04:33:19Z` was also fully green but straddled the first edits of
this card, so it is not offered as a clean baseline; the run above is the
authoritative one and it followed the last edit.

## What changed, by file

### `src/parcel_robot/realtime/ingress.py` — the spoken phrase (unfrozen by the ruling)

* **L68–119, the design block and the grammar.** `SPOKEN_EMERGENCY_PHRASE =
  "die stop"` (L102), `SPOKEN_EMERGENCY_VARIANTS = ("die", "dye", "dai", "di")`
  (L111), and `_SPOKEN_EMERGENCY` (L117), a compiled
  `\b(?:die|dye|dai|di)\W{0,4}stop\b`.
* **L174/L184, two predicates.** `_spoken_emergency_in(folded)` trusts an
  already-folded string; `matches_spoken_emergency(text)` folds first and is
  exported, so the next surface that needs this phrase reads THIS definition
  instead of writing the repo's fifth stop grammar.
* **L242, the one behavioural line.** `if folded in EMERGENCY_STOP_PHRASES or
  _spoken_emergency_in(folded):` — both emergency readings in ONE branch, so
  they are at the same priority and both are still reached before closed
  intents, follow, hold, and before the caller has asked the cloud anything.
  The 4-step restricted-ingress ordering is otherwise untouched.

Three design decisions, all recorded in the source and all seeded:

1. **Why it is not in `closed_intents.py`.** That set is the grammar the local
   agent, `brain/router.py` and this ingress all share for TYPED text, where
   exact matching is right because a text box delivers exactly what was typed.
   A fuzzy rule inside `parse_closed_intent`'s exact-set contract would change
   what every other caller of that parser means. `closed_intents.py` carries no
   edit from this card.
2. **Why the rule is different in kind.** A transcript is not a text box. R7
   measured this exact latch failing three times live; the strongest of those
   was a CORRECTLY transcribed "Stop. Stop right now, please stop." matching
   nothing because the whole utterance was not one of the four exact phrases.
   So the spoken phrase is matched anywhere inside the utterance, with any run
   of ≤4 non-word characters (or none) joining the two words.
3. **What was deliberately NOT relaxed.** "stop" on its own is still only ever
   matched as a whole normalized utterance against `EMERGENCY_STOP_PHRASES`.
   "day" is not a variant — "call it a day, stop the recording" is a sentence
   people say, and admitting it would trade a rare false latch for a routine
   one. Both refusals are executable tests, not comments.

The module docstring's "nothing here contains a copy of a phrase" law is
amended rather than quietly broken (L34–39): this is the *only* definition of
the phrase in the repo, it is exported, and
`test_the_spoken_phrase_exists_exactly_once_in_the_source_tree` greps `src/`
to keep it that way.

### `src/parcel_robot/ui/index.html` — Space, the banner, the release

* **L1993, the Space handler.** Now posts `{action: "emergency_stop"}` with the
  message `"Emergency stop latched (Space)"`. `clearMotionInputs()` still runs
  first, and the branch still `return`s.
* **The `isTypingTarget` guard is byte-identical** and still the FIRST thing
  the keydown handler does. A space typed into the chat box latches nothing.
* **L974–984, the banner.** `#estop-banner`, `role="alert"`,
  `aria-live="assertive"`, `hidden` by default, containing the release button
  `#estop-release` with `data-action="clear_emergency_stop"` — wired by the
  EXISTING `[data-action]` loop, so there is one code path from the panel to
  `runtime.action` rather than a second private one.
* **L1340, the driver.** `el("estop-banner").hidden = !emergencyStopped;` in
  `renderSnapshot`, reading the same `emergencyStopped` field the E-stop badge
  already read — so a latch the panel did not itself request (a spoken "Die
  stop", a watchdog, another tab) raises it just the same.
* **L546–609, the styles**, including `.estop-banner[hidden] { display: none; }`
  (the banner's own `display: flex` would otherwise defeat the attribute) and a
  `prefers-reduced-motion` opt-out for the pulse.
* **L1096 / L949, the keycap moved with the meaning.** `<kbd>Space</kbd>` left
  the nominal Stop button and now sits on the Emergency stop button; a panel
  that documents the opposite of what it does is worse than one that documents
  nothing. Exactly one button may claim the key, pinned by a `count == 1`.
* **L1052, the focus caveat where the keys are documented**: "Space latches the
  emergency stop — not this Stop button — and only while this browser page has
  keyboard focus; the simulator window has its own separate keyboard controls."

**The fresh R5/R4L panel work was not touched.** `renderLogs` dedupe,
`clearMotionInputs` gating and the toggle label are untouched, and seed S13
proves R5's typed-turn path still reddens if disturbed.

### `src/parcel_robot/runtime.py` — six lines, and they are a Deviation

`submit_realtime_transcript`'s tail (L4678–4688) used to emit
`realtime | stop: Die stop` at **info** for every executed outcome including an
emergency. That reads as a routing note, and it sat next to a generic
`safety | Emergency stop latched` that says nothing about where the stop came
from. The emergency arm now emits on the **safety** channel at **error** level
naming the words: `Emergency stop latched by voice: 'Die Stop! Die Stop'`. Every
other arm is byte-unchanged. Justified in Deviations below; seeded (S11).

**No other runtime change was needed.** The release path already existed
end to end and was verified rather than built: `/api/action
{action: "clear_emergency_stop"}` → `web_panel.py:359` → `runtime.action`
(L3910) → `runtime.clear_emergency_stop` (L3032), which clears the controller,
the arbiter, `agent.safety`, and the P0-B input-health latch. `web_panel.py`
carries **no edit from this card**.

### `tests/`

* `tests/test_realtime_ingress.py` — the GRAMMAR. Variant×separator matrix,
  sentence-break matrix, "anywhere in the utterance", the negative-sentence
  class, the "day" refusal, the typed-grammar-not-widened pin, the
  single-definition grep, and `LIVE_TRANSCRIPTS` — every owner row this card's
  live proof produced, frozen as a regression **including the two rows that did
  not latch**.
* `tests/test_prod_default_path.py` — the PANEL, added to the file that already
  owns this panel's source pins. Space, the typing guard, the banner + release,
  the focus caveat and the keycap.
* `tests/test_owner_estop.py` — NEW. The two properties nothing else pins:
  **local-first** (the ingress runs before `response.create` goes on the wire,
  observed on the wire, not read from the source) and **releasable** (latch →
  motion refused → release → the SAME motion accepted).

## Seed table — 16/16 RED, all restored byte-identically

Harness: `<scratchpad>/r9/seeds_r9.py` (FIX-A shape). It snapshots the bytes of
every file any seed touches ONCE at startup and every restore writes THAT
snapshot back — see Deviation 4 for why that mattered here. No test, config or
eval file was ever mutated.

| # | Seed | File | Test | Verdict |
| --- | --- | --- | --- | --- |
| S1 | **Space reverts to the NOMINAL stop** | `ui/index.html` | `test_prod_default_path.py::test_space_latches_the_emergency_stop_and_not_the_nominal_stop` | RED |
| S2 | **the typing-target guard removed (typing latches)** | `ui/index.html` | `test_prod_default_path.py::test_the_typing_target_guard_still_stands_in_front_of_the_latch` | RED |
| S3 | **variant tolerance removed — exact-only again** | `realtime/ingress.py` | `test_realtime_ingress.py::test_every_asr_variant_and_separator_latches` | RED |
| S4 | whole-utterance-only matching restored (the R7 live failure) | `realtime/ingress.py` | `test_realtime_ingress.py::test_the_spoken_phrase_latches_anywhere_inside_the_utterance` | RED |
| S5 | **the latch moved AFTER the cloud round-trip** | `realtime/lane.py` | `test_owner_estop.py::test_the_typed_origin_latches_before_the_cloud_is_asked_for_a_reply` | RED |
| S6 | **the negative case latches ("stop by the store" halts the dog)** | `realtime/ingress.py` | `test_realtime_ingress.py::test_an_ordinary_sentence_containing_stop_never_latches` | RED |
| S7 | **release path broken — the latch is forever** | `runtime.py` | `test_owner_estop.py::test_the_spoken_latch_stops_the_dog_and_the_release_makes_it_drivable_again` | RED |
| S8 | the latched banner is never raised | `ui/index.html` | `test_prod_default_path.py::test_the_latched_state_is_unmissable_and_carries_its_own_way_out` | RED |
| S9 | the release affordance leaves the banner | `ui/index.html` | `test_prod_default_path.py::test_the_latched_state_is_unmissable_and_carries_its_own_way_out` | RED |
| S10 | the high-frequency homophone admitted ("day" becomes a variant) | `realtime/ingress.py` | `test_realtime_ingress.py::test_an_ordinary_sentence_containing_stop_never_latches` | RED |
| S11 | the spoken latch demoted back to an INFO routing note | `runtime.py` | `test_owner_estop.py::test_the_latch_names_the_words_that_caused_it` | RED |
| S12 | U33 drift — the phrase copied into the TYPED grammar | `voice/closed_intents.py` | `test_realtime_ingress.py::test_the_spoken_phrase_exists_exactly_once_in_the_source_tree` | RED |
| S13 | R5 freshness — a typed live turn no longer reaches the hosted lane | `ui/index.html` | `test_prod_default_path.py::test_typed_commands_go_to_the_hosted_lane_whenever_it_exists` | RED |
| S14 | normalization removed — punctuated "Stop." stops matching | `realtime/ingress.py` | `test_realtime_ingress.py::test_every_punctuated_emergency_phrase_still_latches` | RED |
| S15 | the Space keycap left on the button Space no longer presses | `ui/index.html` | `test_prod_default_path.py::test_the_panel_says_where_the_space_bar_works_and_where_it_does_not` | RED |
| S16 | the separator class narrowed to a space ("Die. Stop." misses) | `realtime/ingress.py` | `test_realtime_ingress.py::test_a_sentence_break_between_the_two_words_still_latches` | RED |

The card's six named seeds are S1, S2, S3, S5, S6 and S7.

### Two seeds came back GREEN first and the TESTS were strengthened

Recorded because the rule is "a GREEN seed means the test does not pin the fix":

1. **"normalization removed" was GREEN** against the spoken-phrase punctuation
   test. Investigating showed why, and it is a *property*, not a defect: the
   spoken matcher searches with `\b` boundaries, so it survives `normalize`
   being deleted, while the exact TYPED set does not. The seed was retargeted
   at `test_every_punctuated_emergency_phrase_still_latches` — the R1 test that
   actually pins the normalizer — and a NEW seed (S16) was written for the
   property the spoken punctuation test does pin. Both RED.
2. **`test_every_asr_variant_and_separator_latches` was parametrized over
   `SPOKEN_EMERGENCY_VARIANTS` itself**, which means deleting three variants
   made it run three fewer cases and stay green — a vacuous pass. The test now
   parametrizes over a LITERAL `_ASR_SPELLINGS` tuple and a separate test
   asserts `SPOKEN_EMERGENCY_VARIANTS == _ASR_SPELLINGS`, so the set is pinned
   against narrowing (a missed latch) as well as widening.

## Live proof

**Owner's stack was UP on :8765 for the whole card and was never touched**
beyond a single read-only `GET /api/health` (→ `200 {"status":"ok"}`) recorded
at the start. No POST, no restart, no signal; its process (`launch_sim.sh
--llm`, pid 1703400) was verified alive at teardown. A THIRD stack belonging to
another agent (`:8844`, `/tmp/parcel_r9b.sock`) was running concurrently and was
likewise left alone; only my own pid tree (1876337 + 2 children) was terminated.

**Memory isolation (R5 recipe).** `configs/robot.yaml` was COPIED to the
scratchpad with `memory.path` repointed at a scratch sqlite and passed with
`--config`. Verified after teardown: `configs/robot.yaml` sha256
`f7b57dcd…90d6f1`, **byte-identical** before and after; the owner's
`parcel_memory.sqlite3` mtime is `2026-08-20 00:23:30`, before my stack started
at 00:46, i.e. never opened. The realtime config was a scratch `realtime_r9.yaml`
(`mode: audio`) handed over via `PARCEL_REALTIME_CONFIG`; the owner's
`~/.config/parcel/realtime.yaml` and `realtime.env` are untouched (mtime
2026-08-18). The credential was sourced with
`set -a; . ~/.config/parcel/realtime.env; set +a` and was never printed,
asserted against or written anywhere.

**No microphone was involved.** Every "spoken" sentence was synthesized with the
local piper the runtime already uses (`third_party/piper/piper --model
models/piper/voice.onnx --output-raw`, 22 050 Hz), linearly resampled to the
24 000 Hz the session negotiates, and pumped through the REAL R7 audio gateway
in real-time 20 ms frames by a headless client that does what `index.html` does
minus the DOM (`<scratchpad>/r9/live/proof_client_r9.py`, extended from R7's).

### (a) the spoken latch, while a mission is running

Session 1 — `"Hey, could you go to the sidewalk please?"` then `"Die stop."`:

```
state after "mission":
  emergency_stopped: False
  navigation: {'enabled': True, 'state': 'searching', 'goal': 'sidewalk'}
  mission_log: [{'id': 1, 'kind': 'started', 'goal': 'sidewalk', ...,
                 'text': 'Navigating to sidewalk.'}]
  events: 16 realtime info | tool navigate_to: ok — mission accepted: sidewalk
          17 navigation success | Navigating to sidewalk.

state after "die_stop":
  emergency_stopped: True                       <-- THE LATCH
  navigation: {'enabled': False, 'state': 'idle', 'goal': 'sidewalk',
               'reason': 'navigation_disabled'}
  mission_log: [... {'id': 3, 'kind': 'ended', 'goal': 'sidewalk',
                     'state': 'idle', 'reason': 'navigation_disabled',
                     'text': 'Mission to sidewalk ended (idle): navigation_disabled.'}]
  events: 19 navigation warning | Mission to sidewalk ended (idle): navigation_disabled
          20 safety     error   | Emergency stop latched
          21 safety     error   | Emergency stop latched by voice: 'Die stop'   <-- the reason
```

Session 3 — a second mission (`crosswalk`) interrupted by
`"Die stop! Die stop!"`, which is the property R7 could not get:

```
ledger row 25  user owner realtime | Die Stop! Die Stop!
state after:   emergency_stopped: True
               navigation {'enabled': False, 'state': 'idle', 'goal': 'crosswalk'}
               mission_log id 7 kind 'ended' goal 'crosswalk'
events: 70 navigation warning | Mission to crosswalk ended (idle): navigation_disabled
        71 safety     error   | Emergency stop latched
        72 safety     error   | Emergency stop latched by voice: 'Die Stop! Die Stop'
```

Under R7's exact-phrase rule that utterance would have matched **nothing**.

### (b) the typed path, (c) the negative, (d) the release

`<scratchpad>/r9/live/http_proof_r9.py` — real POSTs to the panel routes
`index.html` uses, on my stack, in an order where each step's precondition is
the previous step's result:

```
{"step": "0-start",                       "emergency_stopped": true}
{"step": "1-motion-while-latched",        "status": 409, "body": {"detail": "motion is disabled by emergency stop"}}
{"step": "2-release",                     "status": 200, "body": "Emergency stop cleared", "emergency_stopped": false}
{"step": "3-motion-after-release",        "status": 200, "body": {"message": "accepted manual motion"}}
{"step": "4-nominal-stop-tidy",           "status": 200, "body": "Stopped"}
{"step": "5-typed-negative",              "status": 202, "emergency_stopped": false}   <-- "Let's stop by the store on the way home."
{"step": "6-typed-die-stop",              "status": 202, "emergency_stopped": true}    <-- "Die stop"
{"step": "7-motion-while-latched-again",  "status": 409, "body": {"detail": "motion is disabled by emergency stop"}}
{"step": "8-release-again",               "status": 200, "body": "Emergency stop cleared", "emergency_stopped": false}
{"step": "9-motion-after-release-again",  "status": 200, "body": {"message": "accepted manual motion"}}
```

with the matching event tail:

```
36 safety   warning | motion is disabled by emergency stop
37 safety   warning | Emergency stop cleared by operator
40 safety   error   | Emergency stop latched
41 safety   error   | Emergency stop latched by voice: 'Die stop'
42 safety   warning | motion is disabled by emergency stop
43 safety   warning | Emergency stop cleared by operator
```

The spoken negative was run too (session 2): `"Let's stop by the store on the
way home."` was transcribed verbatim and left `emergency_stopped: false`, and
the model answered it conversationally ("I can do that, but I need a clearer
destination…") — which is the honest outcome: nothing local happened.

### Every owner row the hosted transcriber wrote

| Spoken (piper) | Transcribed | Latched |
| --- | --- | --- |
| "Die stop." | `Die stop` | **yes** |
| "Die stop! Die stop!" | `Die Stop! Die Stop!` | **yes** |
| "Die stop." (repeat) | `Die Stop!` | **yes** |
| "Die stop, die stop, please die stop." | `Die Stop! Die Stop! Please Die Stop!` | **yes** |
| "Dye stop." | `Dice top` | **no** ← open risk 1 |
| "Dye. Stop." | `die top` | **no** ← open risk 1 |
| "Let's stop by the store on the way home." (×2) | verbatim | no (correct) |
| typed "Die stop" | `Die stop` | **yes** |

The owner's own phrase: **4/4 spoken**. Frozen as
`LIVE_TRANSCRIPTS` in `tests/test_realtime_ingress.py`, the two misses included.

### Session and cost ledger

| Session | Spoken | Outcome | Running spend |
| --- | --- | --- | --- |
| 1 | mission → "Die stop." | **latch on a running mission PROVEN** | `$0.010810` |
| — | HTTP: release / typed negative / typed "Die stop" / release | **(b) (c) (d) PROVEN** | `$0.023257` |
| 2 | "Let's stop by the store…" then "Dye stop." | negative correct; **variant missed** (`Dice top`) | `$0.032664` |
| 3 | mission → "Die stop! Die stop!" | **anywhere-in-utterance PROVEN live** | — |
| 4 | "Dye. Stop." | **variant missed** (`die top`) | — |
| 5 | "Die stop." | latched | — |
| 6 | "Die stop, die stop, please die stop." | latched | — |
| | | **total** | **`$0.127042`** |

Final gateway / lane counters across all six sessions:

```
connections 6 · connections_refused 0 · mic_opens 6 · mic_refusals 0
frames_in 6227 · bytes_in 5977920      (owner microphone, 24 kHz PCM16)
frames_out 212 · bytes_out 2387728     (hosted speech, WAV-wrapped)
utterances 17 · interrupts 0 · played_acks 212 · stale_acks 0 · control_errors 0
frames_refused_unarmed 0 · frames_dropped_backpressure 0
frames_dropped_no_client 184 · frames_discarded_interrupt 0
lane: reconnects 5, stalls 5, dropped_sends 0, server_errors 0, usage_rows 20,
      text_turns 2, voice_turn_repays 3
driver: steps 6834, frames 1091, failures []
```

Incidental, not claimed as this card's work: the five stalls were the idle gaps
between utterances, and **R8's voice-turn repay handled all three of the ones
that interrupted an owner turn** (`voice_turn_repays: 3`, and ledger rows
"[turn repaid] … asked the new session to answer"). `dropped_sends 0`,
`server_errors 0`, `driver.failures []`.

## does_not_prove

1. **No human has spoken to it.** Every utterance was piper output through a
   headless client. `getUserMedia`, the `ScriptProcessorNode` resampler and
   browser playback have still never been executed; they are pinned only as
   source assertions. Unchanged from R7.
2. **The panel was never rendered.** Space, the banner and the release button
   are pinned as SOURCE assertions in `test_prod_default_path.py`, because this
   repo has no browser in its test suite. What is proven end to end is the
   HTTP layer underneath them — `/api/action {emergency_stop}` and
   `{clear_emergency_stop}` were both driven live with the exact bodies the
   panel sends. That the `<kbd>` reads "Space" and the banner is visible is a
   claim about the source, not about pixels.
3. **This is not cloud-independent.** A spoken latch travels to a hosted
   transcriber and back before any of this code sees a word. "Local-first"
   here means "before the model is asked for a REPLY", which is what S5 pins;
   it does not mean "without a network". The cloud-independent guarantees
   remain the Space bar, the panel buttons, the operator stop and the local
   watchdogs.
4. **Four spoken samples is not a rate.** "4/4" is four utterances of one
   piper rendering, on one model, in one session family. It is evidence that
   the phrase survives this transcriber, not a measured miss rate.
5. **The false-latch surface is argued, not measured.** No corpus was run
   against `_SPOKEN_EMERGENCY` to count how often "<die-variant> stop" appears
   in ordinary speech. The claim that it is a rare bigram is a judgement plus a
   test list, not a statistic.
6. **Cost is estimated.** `spend_usd` uses `realtime/cost.py`'s assumed rates.
   `$0.127042` is an estimate, not an invoice.
7. **Concurrency was not exercised.** Nothing tests two latches racing, or a
   release racing a latch.

## Open risks

1. **The transcriber drops the leading /s/ of "stop", and the latch has no
   tolerance for that.** Measured twice here (`"Dye stop."` → `Dice top`,
   `"Dye. Stop."` → `die top`) and once by R7 (bare `"Stop."` → `Top`). Three
   measurements, two cards, one mechanism. The owner's own phrase survived 4/4,
   plausibly because in "die stop" the /s/ sits between two stressed vowels
   rather than after a silence — but if it ever does happen to "Die Stop", the
   latch MISSES, and a missed latch is the failure that matters.

   **The fix is one character** — `\W{0,4}s?top\b` — and it is deliberately NOT
   taken here. It widens the grammar of a safety latch beyond what the ruling
   authorised, and it buys a real false latch: "I love your tie-dye top"
   matches. That trade is the owner's to make, not mine. It is pinned as a
   red-on-change regression in `LIVE_TRANSCRIPTS` so the next person to widen
   it has to do it on purpose. **Owner decision requested.**
2. **The mission-log terminal for an e-stopped mission says
   `navigation_disabled`, not `emergency_stop`.** Root cause is exact:
   `runtime_channels.py:150-152`, `NavigationChannel.stop(reason)` does
   `del reason` and calls `self._stop_fn()` with no arguments, so
   `_stop_navigation_channel` falls back to its `reason="navigation_disabled"`
   default — for EVERY preempt path, not just this one. It is visibly the same
   text R4-lite's own docstring quotes as the owner's original incident. Not
   fixed: `runtime_channels.py` is outside this card's OWNS and threading the
   reason through changes the mission-log reason of every preemption in the
   system. The latch itself is fully attributed in the event log, so this is a
   legibility gap, not a safety gap.
3. **Space needs the panel focused.** Browser keys only reach the page that has
   keyboard focus — click into the MuJoCo window and Space is the simulator's
   key, not the e-stop (B14's cousin). Stated in the panel itself (L1052) and
   in the emergency button's own caption, but it remains true, and an owner who
   believes Space is a hardware e-stop is holding a wrong belief about a safety
   device. A real hardware e-stop is owner-gated and unbuilt.
4. **A false latch is cheap only while a human is at the panel.** The whole
   asymmetric-cost argument assumes somebody can click Release. An unattended
   dog that false-latches is a dog stopped until someone comes back. That is
   the correct failure direction and still worth naming.
5. **The two pre-existing unknown server events still log every session**
   (`input_audio_buffer.committed`,
   `conversation.item.input_audio_transcription.delta`) into
   `lane.protocol_errors` — 18 rows across six sessions. Reported by R7,
   unchanged; `protocol.py` was frozen for this card (R8 landed there today).
6. **`emergency_stop` is not idempotent-free of side effects.** Each latch
   re-runs `preempt` and `_interrupt_brain`. Repeating "Die stop" four times in
   one utterance latches once (one transcript, one scan), but four separate
   utterances would run it four times. Harmless as observed; untested.

## Owner-gated (unchanged or newly raised)

* **A hardware / always-local hotword detector** that works with zero cloud and
  zero panel focus. Still the honest answer to "what stops the dog when the
  network is down and nobody is looking at the browser", and still not built.
  R7 raised it; this card narrows the gap for the panel and the hosted lane but
  does not close it.
* **Whether `top` is accepted as `stop`** — open risk 1. One character, one
  named false positive.
* **Whether the LEGACY typed path should learn "die stop" too.** Today a "die
  stop" typed into the box with the live toggle UNTICKED goes to
  `submit_voice_text` → the local agent's fast path → `closed_intents`'s exact
  set, which does not contain it, so it does NOT latch. That is correct for
  this card's scope (`agent.py` and `closed_intents.py` are MUST-NOT-TOUCH, and
  the legacy path is e2e-testing-only per R5), but an owner who has learned one
  emergency phrase will not remember which checkbox changes whether it works.

## Deviations from the card

1. **`runtime.py` was edited, six lines, and the card allows it only "if the
   emergency action/release wiring genuinely requires it".** The wiring did not
   require it; the card's own live-proof acceptance criterion did — item 3(a)
   demands "the mission log + events must show the latch **and its reason**",
   and `realtime | stop: Die stop` at INFO level next to a generic
   `Emergency stop latched` does not show a reason. Smallest possible touch: one
   `if/else` inside one method, no signature change, no new symbol, no
   mission-log row (see open risk 2 for why the mission log was left alone).
   Seeded (S11).
2. **`lane.py` was MUTATED BY A SEED and never edited.** S5 is the card's
   required "latch moved AFTER the cloud round-trip" seed, and the only place
   that ordering exists is `RealtimeLane.send_text`. The mutation was applied,
   the target run, and the file restored to its exact pre-seed bytes
   (`c875378f…52b5`, verified by sha256 both per-seed and in a final tree
   check). R8's landed work in that file is untouched. `protocol.py` was neither
   edited nor seeded.
3. **`voice/closed_intents.py` was MUTATED BY A SEED and never edited** (S12,
   the U33 drift seed), restored the same way (`0d5e324d…db16`).
4. **The seed harness had to be hardened mid-card, and one stale mutation
   reached the working tree before it was.** The first full seed run restored
   each file to "whatever was on disk when that seed started". Something else in
   this workspace writes these files concurrently (my own test files were
   rewritten under me twice during this card), and the result was that S3's
   mutation was picked up as S4's "original" and written back — leaving
   `ingress.py:242` reading `folded == SPOKEN_EMERGENCY_PHRASE` (exact-only) and
   `runtime.py` carrying S11's demoted emit. **Both were caught by inspection
   before the final gate, restored, and re-verified.** The harness now snapshots
   every touched file ONCE at startup, restores from that snapshot, repairs
   before each seed if the file has drifted, and prints a final tree check. The
   re-run reported `0 file(s) needed a final repair` and the five touched files
   match the golden manifest at teardown. The lesson generalises: a restore
   whose reference is read at mutation time cannot detect a concurrent writer,
   and will cheerfully assert byte-identical restoration of a corrupted file.
5. **Six live sessions, not one.** The card asks for one spoken proof. Session 1
   is that proof. Sessions 2 and 4 exist because the ASR variant failed and it
   was worth establishing whether that was a fluke or a mechanism (it is a
   mechanism); sessions 3, 5 and 6 exist to measure whether the OWNER's phrase
   itself is robust, which is the number the ruling actually depends on. Total
   spend is still an order of magnitude under the $1 target.
6. **Panel pins live in `tests/test_prod_default_path.py`, the runtime/lane
   pins in a new `tests/test_owner_estop.py`.** The card's OWNS names
   "prod-default panel pins" and "new", and this is that split: the panel file
   already has one owner for its source pins and did not need a second.
7. **A third agent's stack was running on `:8844`** during my live work. It was
   left strictly alone; only my own process tree was signalled.
8. **`HEAD` moved under this card and it was not me.** It read
   `8473a51 Land FIX-A fail-closed mic arming and voice transcript persistence.`
   at the start and `877d9f4 Implemented voice agent` (authored 2026-08-17) at
   the end. Nothing from this card is in it: every R9 file is still `M` or `??`
   in `git status`, and this executor ran no `commit`, `add`, `stash`, `reset`
   or `checkout` at any point. Recorded because an auditor diffing against HEAD
   will see a different base than the one this work was written on.

## Frozen files — confirmed untouched

`realtime/lane.py` and `realtime/protocol.py` (R8, landed today), `web_panel.py`,
`tool_broker.py`, `prompting.py`, `realtime/config.py`, `agent.py`,
`voice/closed_intents.py`, `audio_gateway.py`, `browser_sink.py`, `driver.py`,
`runtime_channels.py`, the yield/person-stop policy, `configs/**` and `evals/**`
carry **no edits from this card**. `lane.py` and `closed_intents.py` were
seed-mutated and restored byte-identically (Deviations 2–3). The fresh R5/R4L
panel work is undisturbed and seed-guarded (S13). Nothing was committed, staged
or stashed; other cards' uncommitted work in the tree was not touched.

Golden manifest at teardown:

```
636ea47c3889dc61c54ecfefeda72cb491bb39ea48980b6d38e5a15fadc79826  src/parcel_robot/realtime/ingress.py
64cc6a778fc358d64d80e4f0291c3ea440ba4890aff3eb70150f3cd0ed2e0c6f  src/parcel_robot/runtime.py
2404b48daa33b33877086afab6b9d939527b5798a0ff1a5302afef2c4fa4e7f9  src/parcel_robot/ui/index.html
c875378fd486a8f096f267bd25f42a7dc8b9f4773a4de1f5590e06543be052b5  src/parcel_robot/realtime/lane.py
0d5e324da2b67720cbe319941ef08c51b398d01c7a8dd8c89b4d002437c3db16  src/parcel_robot/voice/closed_intents.py
```

## Artifacts

* Seed harness: `<scratchpad>/r9/seeds_r9.py`; full run `<scratchpad>/r9/seeds_full.txt`
* Golden manifest: `<scratchpad>/r9/golden.sha`
* Gate runs: `<scratchpad>/r9/gate_final.txt`
* Live clients: `<scratchpad>/r9/live/proof_client_r9.py`, `<scratchpad>/r9/live/http_proof_r9.py`
* Live transcripts: `<scratchpad>/r9/live/proof_session{1..6}.json`, `<scratchpad>/r9/live/proof_http.json`
* Scratch configs: `<scratchpad>/r9/live/robot_r9.yaml`, `<scratchpad>/r9/live/realtime_r9.yaml`
* Scratch ledger: `<scratchpad>/r9/live/parcel_memory_r9.sqlite3`
* Stack log: `<scratchpad>/r9/live/stack.log`; launcher `<scratchpad>/r9/live/run_stack.sh`
* Piper utterances: `<scratchpad>/r9/live/utt_*.raw`

(`<scratchpad>` =
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`)
