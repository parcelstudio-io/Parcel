# R8 task_1 — the whole conversation on the wire — EXECUTOR STATUS

**Date:** 2026-08-19/20 · **Card:** `scrum/20260819/task_1/README.md`
**Executors:** Claude Opus (agent) — **two of them**: executor 1 wrote all the
code, tests, probes, live sessions and the body of this document, then was
killed; executor 2 audited that work, re-ran the seed sweep and the gate
independently, and finished the card. The provenance split is stated in full in
§Orphaned work assessment, and no claim below is executor 1's word alone.
**Auditor:** Fable
**Depends on:** R6 (`20260818/task_3`), R7 (`20260818/task_4`), R5, R4L, R1.6+R3
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Baseline at session start:** the large uncommitted wave from the other in-flight
cards (`lane.py`, `protocol.py`, `runtime.py`, `memory.py`, `web_panel.py`,
`index.html`, `launch_stack.sh`, `config.py`, two tracked test files, and the
untracked realtime modules). Nothing of theirs was touched except this card's
OWNS. Test baseline on that tree: `test_realtime_reconnect.py` 44,
`test_realtime_lane.py` 65, `test_realtime_protocol.py` 30 = **139**; gate
baseline `6242 passed` (R7's number).

## Verdict in one paragraph

R6's decisive live finding is fixed and the fix is proven on the wire. The three
content types are **live-verified per role before a line of test was written** —
nine `(role × content type)` pairs down one socket, six refusals read back, and
the provider's own sentences are quoted in the pins. A session open and a
reconnect now replay **both halves** of the conversation with **zero
`invalid_value` errors**, and `narrate_event` has been **HEARD** for the first
time since R1: the model's next reply named the fact the robot's systems
reported. A refused item is no longer invisible — the probe also established that
the provider echoes our client `event_id` inside the error frame, so per-item
attribution needed **no protocol surgery at all**, and a counted-but-dropped
narration is now a number in `/api/state` (`narrations_refused`) beside the item
that was lost. The voice-turn owed signal is built as a **separate** counter next
to `_responses_pending` rather than folded into it — R6's invariant survives
untouched, all 44 of its tests still pass with no edit — and it was proven
against the real provider with synthesized speech: the signal armed at
`voice_turn_owed=True, responses_pending=0` (exactly the pair R6 could not see),
and a spoken turn the socket died on was **repaid and correctly answered**.
Twenty-six seeds RED, all files restored byte-identically. Gate fully green at
`6269 passed` (= R7's 6242 + this card's 27).

## Wire verification FIRST — the API is the authority

Before any code changed, one bare socket, no lane, no runtime, no
`response.create` (so: nothing generated, nothing billed beyond a session's worth
of nothing). Nine `conversation.item.create` frames, one per `(role ×
content type)` pair, each tagged with its own client `event_id`.

Harness: `<scratchpad>/r8/wire_content_types.py`; raw frames in
`<scratchpad>/r8/wire_content_types.json`. Model `gpt-realtime-2.1-mini`.

```
=== verdict, per (role, content type) ===
  user       input_text   accepted
  user       text         REFUSED   Invalid value: 'text'. Supported values are: 'input_text' and 'input_audio'.
  user       output_text  REFUSED   Invalid value: 'output_text'. Supported values are: 'input_text' and 'input_audio'.
  assistant  input_text   REFUSED   Invalid value: 'input_text'. Value must be 'output_text'.
  assistant  text         REFUSED   Invalid value: 'text'. Value must be 'output_text'.
  assistant  output_text  accepted
  system     input_text   accepted
  system     text         REFUSED   Invalid value: 'text'. Value must be 'input_text'.
  system     output_text  REFUSED   Invalid value: 'output_text'. Value must be 'input_text'.

=== error.event_id echoes the client event_id: True ===
=== items created (accepted): 3 ===
```

Three findings, all load-bearing:

1. **R6's prediction is confirmed exactly** — `user`/`system` → `input_text`,
   `assistant` → `output_text`.
2. **`"text"` is accepted for NO role at all.** The pre-R8 code sent it for every
   non-`user` role, so the failure was total rather than partial.
3. **The provider echoes the client `event_id` inside `error.event_id`** — six
   refusals, six correct echoes. This is the whole of work item 2's "per-item
   attribution if feasible without deep protocol surgery": it is a field read.

One verbatim error frame, because the two `event_id` fields are the point:

```json
{
  "error": {
    "code": "invalid_value",
    "event_id": "r8_assistant_text",
    "message": "Invalid value: 'text'. Value must be 'output_text'.",
    "param": "item.content[0].type",
    "type": "invalid_request_error"
  },
  "event_id": "event_EEniMBBcM71KaUlP9sXyV",
  "type": "error"
}
```

The **top-level** `event_id` is the id of the ERROR; the **nested** one is the id
of OUR frame. Only the nested one is an attribution — reading the other would
hand every refusal a unique id matching nothing the lane ever sent, i.e.
attribution that is always wrong. Seeded as S10.

## What changed, by file

| File | Lines (start → end) | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/protocol.py` | 633 → 701 (+68) | `CONTENT_TYPE_BY_ROLE` (the live-verified table, with the provider's sentences in the comment); `ConversationItemCreate` reads it and gains optional `event_id`; `__post_init__` admits exactly the table's keys; `ErrorEvent.event_id`; `_parse_error` reads the echo from the nested object only |
| `src/parcel_robot/realtime/lane.py` | 1562 → 1866 (+304) | `_send_item` (tagged items + bounded descriptor trace); `_on_server_error` (attribution, `narrations_refused`, `server_error_records`); `_arm_voice_turn` + the `SpeechStopped` / transcription branches; `_voice_turn_owed` read in `_reconnect` and cleared in `_on_response_done` / `_connect` / `close`; `_repay_turn(voice=...)`; `narrate_event` fourth no; six new snapshot keys; four `ITEM_PURPOSE_*` and two bound constants |
| `tests/test_realtime_protocol.py` | 384 → 518 | +9 tests (30 → 39) |
| `tests/test_realtime_reconnect.py` | 1389 → 1945 | +17 tests (44 → 61) |
| `tests/test_realtime_lane.py` | 1158 → 1199 | +1 test (65 → 66) |
| `scrum/20260819/task_1/R8_STATUS.md` | this file | |

Net counts, not a `+/−` split: both source files were already dirty with other
cards' uncommitted work at session start, so `git diff` cannot separate this
card's share. Final md5: `lane.py` `3fd34906518e215a90b895e08527acc1`,
`protocol.py` `1cce5131846cbeebfe6247053d95fd75`.

The gate's own arithmetic agrees: R7's `6242 passed` → `6269 passed`, **+27**,
which is 9 + 17 + 1.

**New snapshot keys** (six). `/api/state` passes `lane.snapshot()` through
verbatim, so no panel change was needed and none was made:

| Key | Meaning |
| --- | --- |
| `narrations_refused` | narrations the PROVIDER threw away after the lane counted them. `narrations` minus this is what was actually heard |
| `server_errors` | count of every refusal, attributed or not |
| `recent_server_errors` | the last 5, each `{code, message}` plus `item: {role, purpose, text}` where the provider echoed our id |
| `items_refused` | how many of those named a specific item |
| `voice_turn_owed` / `voice_turns_owed` | is a spoken turn outstanding right now, and how many have been |
| `voice_turn_repays` | repays fired for a spoken turn. A **breakdown** of `turn_repays`, never a second total |

### Work item 1 — content types per role

`ConversationItemCreate.to_payload` sent `input_text` for `user` and `"text"` for
everything else. It now reads one table:

```python
CONTENT_TYPE_BY_ROLE: Mapping[str, str] = MappingProxyType(
    {"user": "input_text", "system": "input_text", "assistant": "output_text"}
)
```

A `Mapping` rather than a conditional expression, and `__post_init__` now checks
`self.role not in CONTENT_TYPE_BY_ROLE` rather than against a duplicate literal
set. That makes the admitted-role list and the content-type list **the same
list**, so a fourth role cannot be admitted without someone stating what it puts
on the wire. Pinned by `test_the_content_type_table_covers_exactly_the_roles_the_codec_admits`.

### Work item 2 — a refused item is visible

Three pieces, all in the lane:

* **`_send_item`** — every `conversation.item.create` the lane sends now goes
  through one method that tags it with an `event_id` and records a descriptor
  (`role`, `purpose`, `text`). Five call sites moved onto it: the memory tail, the
  owner's typed turn, the two ingress action reports, and `narrate_event`.
* **`_on_server_error`** — pops the descriptor by echoed id. Attributed: a record
  naming the item, `refused_items`, and `narrations_refused` when the purpose was
  a narration. Unattributed (a rate limit, a session-frame refusal, anything whose
  id we never sent): still recorded in the aggregate, never dropped. Both
  directions pinned (S6, and `test_a_refusal_the_lane_cannot_attribute_still_reaches_the_snapshot`).
* **The trace is bounded** (`DEFAULT_ITEM_TRACE_LIMIT = 64`, oldest evicted
  first). An ACCEPTED item never produces an error frame, so its descriptor is
  never claimed and an unbounded map would grow one entry per item for the life of
  the session. A refusal arrives within a frame or two of its item — six for six
  in the probe — so anything evicted that far back was accepted. Seeds S12, S13
  (a dropped frame leaves no descriptor for an unrelated refusal to claim), S14 (a
  reconnect forgets the dead socket's ids; a new session can never echo them).

**What `narrate_event` returning `True` means, stated honestly in the docstring
and unchanged in behaviour:** the frame left this process, and no more than that.
A refusal is asynchronous — it arrives frames later, long after the method
returned — so no boolean returned there can carry it. The card asked for the
aggregate if per-item attribution was infeasible; attribution turned out to be
feasible, so both are there and `narrations` beside `narrations_refused` is the
pair to read.

### Work item 3 — the voice-turn owed signal

`_voice_turn_owed` is a **separate flag beside** `_responses_pending`, not a
number folded into it. That was the design question R6's carry-forward named, and
the reason is R6's own invariant: `_responses_pending` moves only for frames the
transport accepted (`_send`), and the watchdog, the repay, the beat accounting
and four of R6's sixteen seeds all read it through that invariant. Incrementing
it for a response nobody asked for would make it a count of two different things
and break every one of them silently. Seed **S21** is exactly that mutation; it
reddens six tests. All 44 of R6's tests pass **with no edit to any of them**.

| | armed by | cleared by | read by |
| --- | --- | --- | --- |
| `_responses_pending` | our own `response.create` (unchanged) | `response.done` (unchanged) | watchdog, repay, beats |
| `_voice_turn_owed` | `speech_stopped` **or** input transcription completed | `response.done`, `_connect`, `close` | repay, watchdog arm, narration floor gate |

* **Arming** happens on either frame and de-duplicates: `speech_stopped` and the
  transcription that follows are ONE utterance, so `voice_turns_owed` counts one
  (S19). The transcription arm is belt-and-braces for a session where
  `speech_stopped` was dropped by a full inbound buffer.
* **The repay budget resets on every arm**, outside the de-dupe guard, exactly as
  `send_text` resets it for a typed turn (R6 seed S14's principle). S23.
* **The watchdog's patience clock starts at the end of the owner's speech.** This
  one took a green seed to pin properly — see §Seeds that came back GREEN.
* **`_reconnect` reads both signals before `_connect` clears them and repays
  ONCE** — `if owed > 0 or voice_owed`. Two outstanding signals are still one
  conversation with one question at the end of it (S18 doubles the repay and
  reddens ten tests, R6's included).
* **The ledger row tells the truth about which kind of turn it was.** For a spoken
  turn `owed` is 0, and "the previous session owed 0 answer(s)" is a lie about a
  question the owner definitely asked. S25.
* **`narrate_event` gained a fourth no.** "The robot does not talk over its own
  pending answer" was only ever enforced for turns this lane asked for; a spoken
  question was invisible to it, so a mission terminal could interrupt the owner's
  own question in `mode: audio`. S26. Flagged as a deviation below because the
  card did not ask for it.

## The gate — FULLY GREEN, verbatim

Run after the final edit, on the tree exactly as it stands now (after the 26-seed
sweep restored every mutation).

```
CI GATE — tier=commit  (2026-08-20T04:18:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.89s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.81s
[  PASS] HARD  release-parity-integrity   10 passed in 1.28s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 5.06s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.48s
[  PASS] HARD  default-suite              6269 passed, 9 skipped, 42 deselected, 5 warnings in 300.08s (0:05:00)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 320.6s
```

`ruff` unchanged at the pinned baseline of 7 fingerprints, `new 0`. Digest
sentinels and release-parity byte-identical, which is the mechanical confirmation
that nothing under `evals/` or the packaged assets moved.

### Confirming run — executor 2, independent, after the final edit

Executor 1's green run above is `04:18:49Z`. Because this card changed hands, the
gate was run again from scratch by executor 2 on the tree as it finally stands —
after the independent 26-seed re-sweep had mutated and restored both source files
— so that the green is not a single executor's single observation.
`<scratchpad>/r8/gate_confirm.txt`, verbatim:

```
CI GATE — tier=commit  (2026-08-20T04:31:52Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.44s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.28s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6269 passed, 6 warnings, 9 skipped, 42 deselected in 248.47s (0:04:08)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 261.1s
```

Two independent runs, thirteen hard gates each, same `6269 passed`. Note also
that **`test_cpu_budget_proxy` passed here**, on a machine whose 1-minute load
average was `0.48` when the run started versus the `66.6` recorded for the red
runs. That is the direct confirmation of Open risk 4's diagnosis: the same test,
the same tree, red under the owner's inference load and green without it.

**Exactly what tree that green describes, because another card is in flight.**
The ci_gate header timestamp is the run's *completion* time (executor 1's
`gate_final3.txt` header `04:18:49Z` equals that file's mtime to the second, and
so does this one). So the confirming run occupied roughly `00:27:31 → 00:31:52`
local. Within a second of it finishing, a **different card's executor** wrote
`src/parcel_robot/runtime.py` (mtime `00:31:52.114`) and then
`src/parcel_robot/ui/index.html` (`00:32:26`). Neither file is R8's; both are
MUST-NOT-TOUCH here and neither was touched by either R8 executor. An auditor
looking at mtimes will therefore find two source files **newer than the green
gate**, and should read that as another card's in-flight work rather than as an
unvalidated R8 change. This card's two OWNS source files are unchanged from the
digests the gate ran against — `lane.py` `3fd34906518e215a90b895e08527acc1`,
`protocol.py` `1cce5131846cbeebfe6247053d95fd75`, re-checked after the run.

The gate was deliberately **not** run a third time. The only edits made after it
were to this status document, and `ci_gate.py` never reads `scrum/` (the string
appears in its docstrings only, never as a checked path; `ruff` does not lint
markdown, and both `frozen-digest-sentinels` and `release-parity` passed, which
mechanically confirms no manifest or packaged asset moved). A third run would now
be scored against the other card's half-finished `runtime.py`, so a red would be
misattributed to R8 and a green would say nothing this one does not already say.

### Two gate runs before this one were RED, and NOT on this card's tree — reported in full

`04:02:32Z` and `03:55:56Z` both failed one hard gate with exactly one test:
`tests/test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove`
(`1 failed, 6268 passed`). I did not write this section until I had established
what it was, and it is **not this card**:

* the test asserts `report["budget"]["within_budget"] is True` against a
  **wall-clock** median latency ceiling of 176 ms;
* the machine was under the owner's live stack — `llama-server` at **1469 % CPU**
  and their panel `python` at **346 %**, load average **66.6** on 192 cores. Their
  stack is live on `:8765` and I did not touch, restart, throttle or probe it;
* `parcel_robot.realtime` appears nowhere in that test's import graph; this
  card's changes are confined to `realtime/lane.py`, `realtime/protocol.py` and
  three realtime test files;
* the test passes in isolation and passed a **full standalone suite run**
  (`6269 passed, 9 skipped, 42 deselected in 302.58s`) taken between the two red
  gate runs and the green one, on the same tree;
* the green run above was taken at load average **50** and passed the same test.

So: an environment-sensitive wall-clock assertion, reddened by the owner's
inference server, on a test this card cannot reach. It is listed under Open risks
because it is a real fragility in the gate that another executor will hit.

## Seeds — 26 seeded defects, all RED

Harness: `<scratchpad>/r8/seed_r8.py`, FIX-A shape. Each seed mutates ONE
**source** file (never a test, never `configs/`, never `evals/`), runs a named
pytest target, restores the file in a `finally` and asserts the restore is
byte-identical by sha256. Re-run in full after the final edit; full verbatim
output in `<scratchpad>/r8/seeds_final.txt`.

**Independently re-swept by executor 2.** The table below is executor 1's. It was
re-run from scratch against the tree as it now stands, by a different executor,
with source digests taken before and after: **26/26 RED, harness exit 0, both
source files restored byte-identically** (`pre_seed_digests.txt` vs
`post_seed_digests.txt`, diff clean). No seed came back GREEN on the re-sweep, so
no test needed strengthening a second time. Verbatim output:
`<scratchpad>/r8/seeds_rerun.txt`.

| # | Seeded defect | File | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- | --- |
| S1 | user items regress to the bare 'text' content type | `protocol.py` | **RED** | 2 failed, 3 passed, 34 deselected in 0.29s :: test_each_role_carries_the_content_type_the_provider_accepts[user-input_text-Supported, test_no_role_sends_the_bare_text_type_that_every_role_refuses |
| S2 | system items regress to 'text' (narration refused again) | `protocol.py` | **RED** | 2 failed, 3 passed, 34 deselected in 0.26s :: test_each_role_carries_the_content_type_the_provider_accepts[system-input_text-Invalid, test_no_role_sends_the_bare_text_type_that_every_role_refuses |
| S3 | assistant items regress to 'text' (the robot's half of the tail refused again) | `protocol.py` | **RED** | 2 failed, 3 passed, 34 deselected in 0.26s :: test_each_role_carries_the_content_type_the_provider_accepts[assistant-output_text-Invalid, test_no_role_sends_the_bare_text_type_that_every_role_refuses |
| S4 | the pre-R8 one-branch rule restored verbatim | `protocol.py` | **RED** | 1 failed in 0.30s :: test_the_replayed_tail_carries_BOTH_halves_of_the_conversation |
| S5 | assistant items swap to input_text (the OTHER wrong value the provider names) | `protocol.py` | **RED** | 1 failed in 0.30s :: test_the_replayed_tail_carries_BOTH_halves_of_the_conversation |
| S6 | refused-item visibility removed: a refusal never names its item again | `lane.py` | **RED** | 2 failed, 5 passed, 54 deselected in 0.29s :: test_a_refused_narration_is_counted_and_named_rather_than_silently_dropped, test_a_refused_memory_tail_item_names_the_half_of_the_conversation_it_cost |
| S7 | narrations_refused never moves: a dropped narration counts as delivered | `lane.py` | **RED** | 1 failed in 0.27s :: test_a_refused_narration_is_counted_and_named_rather_than_silently_dropped |
| S8 | the snapshot stops surfacing server errors | `lane.py` | **RED** | 2 failed, 6 passed, 53 deselected in 0.29s :: test_the_snapshot_carries_the_server_error_count_and_the_most_recent_few, test_a_refusal_the_lane_cannot_attribute_still_reaches_the_snapshot |
| S9 | the snapshot's error window is unbounded | `lane.py` | **RED** | 1 failed in 0.28s :: test_the_snapshot_carries_the_server_error_count_and_the_most_recent_few |
| S10 | attribution reads the error frame's OWN id: every refusal names a phantom | `protocol.py` | **RED** | 2 failed, 2 passed, 35 deselected in 0.27s :: test_an_error_frame_echoes_the_client_event_id_it_is_about, test_the_error_frames_own_id_is_never_mistaken_for_the_echo |
| S11 | items go up untagged: nothing can ever be attributed | `lane.py` | **RED** | 2 failed, 5 passed, 54 deselected in 0.29s :: test_a_refused_narration_is_counted_and_named_rather_than_silently_dropped, test_a_refused_memory_tail_item_names_the_half_of_the_conversation_it_cost |
| S12 | the item trace is unbounded | `lane.py` | **RED** | 1 failed in 0.28s :: test_the_item_trace_is_bounded_and_forgets_the_oldest_first |
| S13 | a dropped frame keeps its descriptor and can be falsely claimed | `lane.py` | **RED** | 1 failed in 0.36s :: test_a_frame_the_socket_dropped_leaves_nothing_for_a_refusal_to_claim |
| S14 | a reconnect keeps the dead session's descriptors | `lane.py` | **RED** | 1 failed in 0.51s :: test_a_reconnect_forgets_the_dead_sessions_item_descriptors |
| S15 | **the voice-turn owed signal is removed: a spoken turn is swallowed again** | `lane.py` | **RED** | 7 failed, 2 passed, 52 deselected in 0.56s :: test_a_spoken_turn_the_dead_session_never_answered_is_repaid, test_a_typed_and_a_spoken_turn_outstanding_together_are_still_one_repay, test_a_spoken_turn_starts_the_watchdogs_patience_clock, test_a_spoken_repay_says_in_the_ledger_that_the_turn_was_spoken |
| S16 | the repay reads only `_responses_pending` again (R6's exact blind spot) | `lane.py` | **RED** | 1 failed in 0.43s :: test_a_spoken_turn_the_dead_session_never_answered_is_repaid |
| S17 | **the owed signal DOUBLE-COUNTS: an answered spoken turn is re-asked** | `lane.py` | **RED** | 1 failed in 0.54s :: test_a_spoken_turn_that_was_answered_is_never_repaid |
| S18 | two signals buy two repays: a duplicate answer and a duplicate bill | `lane.py` | **RED** | 10 failed, 4 passed, 47 deselected in 0.69s :: test_a_turn_the_dead_session_never_answered_is_repaid_on_the_new_one, test_the_repay_is_visible_in_the_snapshot_and_explained_in_the_ledger, test_one_repay_per_reconnect_even_when_two_responses_were_owed, test_a_rollover_repays_the_turn_it_interrupted |
| S19 | the de-dupe guard is gone: one utterance counted as two owed turns | `lane.py` | **RED** | 1 failed in 0.42s :: test_speech_stopped_and_the_transcription_that_follows_are_one_owed_turn |
| S20 | speech_stopped stops arming: only a transcription that may never come does | `lane.py` | **RED** | 1 failed in 0.42s :: test_a_new_spoken_turn_gets_its_own_repay_budget |
| S21 | the voice signal is folded INTO `_responses_pending` (R6's invariant broken) | `lane.py` | **RED** | 6 failed, 10 passed, 45 deselected in 0.52s :: test_a_spoken_turn_the_dead_session_never_answered_is_repaid, test_a_typed_and_a_spoken_turn_outstanding_together_are_still_one_repay, test_a_spoken_turn_starts_the_watchdogs_patience_clock, test_a_spoken_repay_says_in_the_ledger_that_the_turn_was_spoken |
| S22 | a spoken turn does not arm the watchdog | `lane.py` | **RED** | 1 failed in 0.42s :: test_a_spoken_turn_starts_the_watchdogs_patience_clock |
| S23 | a new spoken turn inherits the previous one's spent repay budget | `lane.py` | **RED** | 1 failed in 0.42s :: test_a_new_spoken_turn_gets_its_own_repay_budget |
| S24 | a voice repay does not SPEND the budget: the bound runs one cycle too long | `lane.py` | **RED** | 1 failed in 0.38s :: test_a_spoken_turn_is_bounded_by_the_same_repay_budget |
| S25 | the spoken repay's ledger row claims 0 answers were owed | `lane.py` | **RED** | 1 failed in 0.41s :: test_a_spoken_repay_says_in_the_ledger_that_the_turn_was_spoken |
| S26 | a narration talks over a spoken question the owner is still waiting on | `lane.py` | **RED** | 1 failed in 0.41s :: test_a_narration_never_talks_over_a_spoken_turn_awaiting_its_answer |

The card's four required seeds map to: **content type regressed per role (all
three)** → S1, S2, S3 (plus S4, the exact pre-R8 code restored, and S5, the other
wrong value the provider names for `assistant`); **refused-item visibility
removed** → S6 (attribution) with S7 (the counter), S8 (the snapshot) and S11
(the tag); **voice-turn owed signal removed** → S15, with S16 for the narrower
"the repay reads only `_responses_pending`" version; **owed signal
double-counts** → S17, with S18 for the double-repay direction.

### Seeds that came back GREEN, and what was done about them

Three seeds were GREEN on the first sweep. None was deleted. Two were tests that
did not pin what they claimed; one was a mutation that turned out to be
behaviour-equivalent, and finding that out changed the design note in the source.

1. **S22 — "a spoken turn does not arm the watchdog" was GREEN, and the TEST was
   wrong.** `send_audio` also arms the watchdog, so in an ordinary spoken turn
   `_expecting_server` is already `True` and arming again changes nothing an
   assertion can see. The case that actually matters is narrower: the provider
   finishes the PREVIOUS answer and server VAD closes the NEXT utterance in the
   same batch of frames — `_on_response_done` disarms (correctly; nothing it knows
   about is outstanding), and if the spoken turn does not arm the clock itself the
   lane is left waiting on an answer it is not watching for. The test was
   rewritten to that script. Re-run: **RED**.
2. **S23 — "a new spoken turn inherits the spent repay budget" was GREEN as
   first written**, because the mutation moved `_repays_since_answer = 0` *inside*
   the de-dupe guard, and that placement is currently **behaviour-equivalent**:
   `_repays_since_answer` is only ever non-zero after a repay, every repay path
   runs `_connect`, and `_connect` clears `_voice_turn_owed` — so the guard is
   never taken on the path where the budget is non-zero. The seed was re-aimed at
   the mutation that actually causes the defect it names (delete the reset).
   Re-run: **RED**. The equivalence is stated here rather than buried: the
   ordering in `_arm_voice_turn` is defensive, not load-bearing today.
3. **S24 — "the voice signal routes around the repay bound" was GREEN, and the
   reason is a real structural finding.** `_repay_turn` can never be reached with
   `voice=True` *and* `_repays_since_answer >= limit`, for the same chain as
   above. The seed was re-aimed at the reachable version — a voice repay that does
   not SPEND the budget, which makes the bound run one cycle too long (4 repays
   instead of 3). Re-run: **RED**. The consequence for the product is in Open
   risks 2.

## Live proof

**The owner's stack WAS live on `:8765` for the whole card** (`ss -ltn` at start;
their `llama-server` and panel `python` visible in `ps` at the end). It was never
contacted: **no HTTP request of any kind left this session, not even a read-only
GET**, nothing of theirs was started, stopped, restarted or throttled. Both proofs
build a `RobotRuntime` in-process with the headless MuJoCo city (R6's port-free
pattern), so no port was bound at all.

**Memory isolation, R6's stronger form of the R5 recipe:** rather than copying
`configs/robot.yaml`, the runtime config is *synthesized* in the scratchpad with
`memory:\n  path: ":memory:"`. `configs/robot.yaml` was not read, copied or
touched — verified after teardown, sha256
`f7b57dcdf0b5981537ced874b63e010b4f0d6090de7a18118613e13f2990d6c1`, the same
value R7 recorded. The owner's `parcel_memory.sqlite3` was never opened; its
mtime is `Aug 19 23:25`, twenty minutes **before** my first live session began
(`23:44` local / `03:44Z`) and unchanged after both. The realtime config is
likewise a scratch file (`persona`, `mode: text`, `model`,
`monthly_budget_usd: 5.0`). The credential was loaded with
`set -a; . ~/.config/parcel/realtime.env; set +a` and never printed, asserted
against or written anywhere.

| Session | Purpose | Outcome | Cost |
| --- | --- | --- | --- |
| 0 | wire probe: nine (role × content type) pairs | content types + the `event_id` echo established | not sampled (0 responses) |
| 1 | (a) both halves on the wire, (b) narration heard, (c) mission terminal, (d) stalls | **all four proven** | `$0.025539` |
| 2 | the voice-turn owed signal against the real provider | **armed live, and a spoken turn repaid and answered** | `$0.020180` |
| | | **total** | **`$0.045719`** |

Well inside the card's "well under $1", on `gpt-realtime-2.1-mini`.

### (a) PROVEN — a session open replays BOTH halves, with zero `invalid_value`

Session 1. One turn is answered (so the ledger holds both an owner row and a
robot row), then a rollover reconnect is taken and the frames the NEW socket is
sent are read off the wire by a recording proxy that observes and never
substitutes:

```
[   1.5s]   [owner] Hello! Tell me one short fact about Central Park.
[   3.3s]   [robot] Oh, fun one! Central Park is huge—around 843 acres—so it's basically
                    a giant playground right in the middle of the city.
[   9.3s] ledger tail the reconnect will replay:
            [('user', 'Hello! Tell me one short fact about Central Park.'),
             ('assistant', 'Oh, fun one! Central Park is huge—around 843 acres—so it's b')]
[  11.6s]   [system] [session rollover] reconnected rt_ca714c739e42 -> rt_8703987d69d5
[  17.6s] items replayed on the new session, by role -> content type:
            {'user': ['input_text'], 'assistant': ['output_text']}
[  17.6s] tail_items_injected=2
[  17.6s] errors raised by the replay: []
[  17.6s] INVALID_VALUE ERRORS: 0   <-- (a) passes at zero
```

R6's session 1, same event, for contrast:

```
  [server error] invalid_value: Invalid value: 'text'. Value must be 'output_text'.   x2
  [server error] invalid_value: Invalid value: 'text'. Value must be 'output_text'.   x4
```

Independently confirmed a second time in session 2, whose stall-driven reconnect
also finished with `server_errors=0, items_refused=0`.

### (b) PROVEN — the narration was HEARD, for the first time since R1

```
[  17.6s] narrate_event returned True
[  19.2s]   [robot] Okay, fun update: my sensors just spotted a blue umbrella left on
                    the bench by the fountain. Want to know what happened next?
[  27.2s] errors raised by the narration: []
[  27.2s] THE MODEL REFLECTED THE FACT: True   <-- (b)
[  27.2s] narrations=1 narrations_refused=0
```

R6's probe 3, the same call, on the same model:

```
[   7.0s] narrate_event returned True
[   7.2s]   [server error] invalid_value: Invalid value: 'text'. Value must be 'input_text'.
[   8.4s]   [robot] Hey! I'm glad you're feeling good today. Anything fun happening? …
```

R4L's Open risk 1 ("model narration of terminals is unproven live") went from
*unproven* to *proven broken* in R6. It is now **proven working**. The two
counters agreeing at `narrations_refused=0` is what that looks like from
`/api/state`, which is the point of work item 2.

### (c) PROVEN — a mission terminal narrated end to end, in text mode

```
[  27.2s]   [owner] Please go to the sidewalk.
[  28.2s]   [robot] Okay, let me get you ready to head toward the sidewalk.
[  28.2s]   [tool] navigate_to: ok — mission accepted: sidewalk
[ 118.0s]   [robot] I tried to go to the sidewalk, but the navigation system reports it
                    didn't move—so we didn't actually get anywhere.
[ 128.0s] mission narrations fired: 1
[ 128.0s] TERMINAL NARRATED: True   <-- (c)
```

with the mission log behind it:

```
{"kind": "started", "goal": "sidewalk", "state": "searching", "reason": "scan_behavior_rotate"}
{"kind": "ended",   "goal": "sidewalk", "state": "failed",    "reason": "navigation_no_progress"}
```

**Two honest notes.** The mission *failed* rather than arrived —
`navigation_no_progress`, because this scratch config runs the RL backend with an
empty `policy_path`, so the robot never moved. That exercises the non-arrived
branch of `_narrate_mission_terminal` rather than the arrival branch, and the
arrival wording is untested live (see does_not_prove). But it also demonstrates
the thing that matters most about this channel: the model narrated the **failure
truthfully** — "it didn't move, so we didn't actually get anywhere" — instead of
claiming to have arrived. That is `GUARDRAILS` doing its job on a fact it could
only have got from the narration, and it is the first time this repo has been
able to observe that at all.

Note also what the single beat for the navigation turn now costs the owner. R6
suppressed the second beat and wrote, honestly, that "a successful navigation
turn tells the owner *less* than R5's two beats did" **because the narration
channel was refused**. That caveat is discharged: the announcement is beat one,
and the robot's own systems supply the outcome as beat two, 90 seconds later,
through a channel that now works.

### Work item 3, LIVE against the real provider — the voice-turn owed signal

*(Not one of the card's four lettered claims — those are (a), (b), (c) above and
(d) below. This is work item 3's own live proof, which the card did not demand
but which pins a claim about provider behaviour that offline tests cannot.)*

Session 2. Piper synthesizes the owner's speech
(`third_party/piper/piper --model models/piper/voice.onnx --output-raw`,
22 050 Hz), linearly resampled to the 24 000 Hz the session negotiates, and
pumped in real-time 20 ms frames straight into `lane.send_audio`. No microphone,
no browser, no gateway, no socket of my own. The session is opened by the
product's own audio path (`_realtime_mic_gesture(True)` — what the gateway calls
when the owner presses the microphone), not by hand.

**The signal arms on the provider's own VAD:**

```
[   0.7s] hosted session opened by the mic gesture: rt_261cdcc559ec
[   1.1s] piper -> 173440 bytes at 24000 Hz (3.61s)
[   6.1s] === (2) THE SIGNAL ARMED: {'voice_turn_owed': True, 'voice_turns_owed': 1,
                                     'responses_pending': 0} ===
[   6.7s]   [owner] Hey there, tell me one short fact about the Brooklyn Bridge.
[   6.9s]   [robot] Did you know the Brooklyn Bridge was one of the first suspension
                    bridges ever built? …
[  14.9s] after the answer: voice_turn_owed=False usage_rows=1
```

`voice_turn_owed=True` with `responses_pending=0` **is** the defect R6 could not
see, on the wire, in one line. And `voice_turn_owed=False` after the answer is
the double-count guard working live.

**And a spoken turn the socket died on is repaid and correctly answered.** The
transport is made deaf under a live session (`_DeafTransport`: the real socket
stays open and billing, frames still go up, nothing comes down — R6's exact
shape). From the moment it is installed, **nothing is done by hand**:

```
[  19.0s] the lane is now DEAF to a live socket. voice_turn_owed=True,
          responses_pending=0. From here NOTHING is done by hand.
[  19.0s]   [owner] What is the tallest building in New York City?
[  29.5s]   [system] [session stall] reconnected rt_261cdcc559ec -> rt_16cbf5dd75d5
[  30.0s]   [system] [turn repaid] the previous session was answering a turn the owner
                     had SPOKEN when it died (stall); asked the new session to answer
                     the turn it inherited
[  31.8s]   [robot] The tallest building in New York City right now is One World Trade
                    Center. It's the tallest structure in the Western Hemisphere, and it
                    stands tall in Lower Manhattan, making quite a statement.
[  39.8s] recovered in 20.8s; answered=True; stalls 0->1 turn_repays 0->1
          voice_turn_repays 0->1
```

Before this card that sequence ended at `reconnected` and the spoken sentence was
gone — R6's does_not_prove, "No voice turn was repaid", stated as a known gap.

**One more thing this proves that is not work item 3.** R6's session 2 repaid a
turn and the model **answered the wrong thing**, because the replayed history it
inherited had no assistant turns in it. Here the repay answered the *right*
question. Work items 1 and 3 are the same fix seen from two ends: the repay's
value was always "the new session inherits the question", and until the content
types were right it inherited only half a conversation.

### (d) Stall counts — the first honest measurement post-phantom-fix

R6's audit asked for this: exonerate or indict the provider.

| Session | Wall time | Longest quiet gap | `stalls` | of which forced by me |
| --- | --- | --- | --- | --- |
| 1 | ~128 s, 4 responses | ~90 s (waiting out the mission) | **0** | 0 |
| 2 | ~40 s, 2 responses | ~11 s | **1** | **1** (`_DeafTransport`) |

**Zero unforced stalls across both sessions**, including a 90-second gap that
pre-R6 would have manufactured a phantom stall out of several times over. On this
evidence R6's Defect 3 fix holds and `gpt-realtime-2.1-mini` did not stall on its
own once. Stated with the honest caveat it deserves: two sessions and six
responses is a small sample, and R6 open risk 5 (any comparison against R4L's or
R5's numbers is apples to oranges) still stands.

## Deviations from the card

1. **`narrate_event` gained a fourth floor-gate no** (`_voice_turn_owed`). The
   card scoped work item 3 to the repay accounting. But the narration gate's third
   no already reads `_responses_pending` for exactly the reason the new signal
   exists — "the robot does not talk over its own pending answer" — and leaving a
   *spoken* question invisible to it would mean a mission terminal can interrupt
   the owner mid-turn in `mode: audio`, which is the product bug the gate was
   written to prevent. Seeded (S26) and pinned.
2. **`ConversationItemCreate` gained an optional `event_id`, and `ErrorEvent`
   gained one.** The card allows `protocol.py` for "content types + any pin the
   change needs"; this is a little more than that. It is the entire mechanism for
   work item 2's per-item attribution, it is two optional fields that default to
   the pre-R8 behaviour exactly, and the card explicitly invites attribution "if
   feasible without deep protocol surgery". Both are wire-verified.
3. **`__post_init__`'s role allowlist now reads `CONTENT_TYPE_BY_ROLE`** instead
   of a duplicate literal set. One line, and it is what makes "a role the codec
   admits but the table does not know" unrepresentable rather than merely absent.
4. **Two live sessions plus a wire probe, not one session.** The card asks for
   four claims; session 1 carries (a)-(d) as written. Session 2 exists because
   work item 3 is a claim about *provider behaviour* and pinning it only offline
   would have shipped the same class of unverified assumption this whole card
   exists to repair. Total `$0.045719`.
5. **The card suggests nothing about ports and I bound none.** In-process
   `RobotRuntime`, R6's pattern, chosen deliberately because the owner's stack was
   LIVE this time and the safest number of sockets to open near it is zero.
6. **Six new snapshot keys, not one.** The card asks for `server_errors` "count +
   most recent few". That is two of them; the other four are `narrations_refused`
   (the number the card's own text says makes a counted-but-refused narration
   diagnosable), `items_refused`, and the two voice-turn numbers without which
   work item 3 is invisible from `/api/state`.
7. **Two gate runs were red before the green one** and both are reported above
   rather than quietly re-rolled, with the causal work that established it was the
   owner's inference server and not this tree.

## What this does NOT prove (does_not_prove)

* **The arrival wording of a mission terminal is untested live.** Session 1's
  mission ended `failed: navigation_no_progress` (empty RL `policy_path` in the
  scratch config), so `_narrate_mission_terminal`'s `arrived` branch — "The
  robot's navigation system reports it arrived at X" — has never been narrated to
  a live model. The failure branch was, and was narrated truthfully.
* **No human has spoken to it or heard it.** Session 2's "speech" is piper output
  fed into `lane.send_audio`; session 1 is `mode: text` throughout. No microphone,
  no speaker, no barge-in, and the browser capture/playback path in `index.html`
  was not executed (that is R7's does_not_prove 1 and it still stands).
* **The voice-turn repay was proven for a SPOKEN turn on a deaf socket, once.**
  The abandon bound for a voice turn, the double-repay guard with both signals
  set, and the trace eviction are offline pins only (S24, S18, S12).
* **A refusal that arrives more than 64 items after its own item would go
  unattributed.** The bound is justified by six-for-six same-batch attribution in
  the probe, not by a survey of the provider's timing.
* **`items_refused` and `narrations_refused` were 0 in every live session**, so
  the attribution path was exercised live only in the negative (nothing was
  refused, and nothing claimed to be). Its positive direction is pinned offline
  by six seeds.
* **Cost is estimated**, not invoiced: `realtime/cost.py` reports
  `rates_are_assumed: True`.
* **Nothing here says a real provider stall never happens.** Two sessions, six
  responses, zero unforced stalls. That is evidence, not a proof.

## Owner-gated / not touched

* **`ingress.py` (R9's today), `tool_broker.py`, `prompting.py`, `runtime.py`,
  `web_panel.py`, `ui/index.html`, `config.py`, `transport.py`,
  `ws_transport.py`, `fake_server.py`, `agent.py`, `audio_gateway.py`,
  `configs/**`, `evals/**` — all untouched.** `fake_server.py` needed no
  extension: the R8 error frame (with both `event_id` fields) and the spoken-turn
  scripts are expressible with the existing `Step` and frame helpers, so they live
  in the test file, exactly as R6 did it.
* **SI v2 stays exactly as R5 shipped it.** `lane.GUARDRAILS` is unchanged. And
  the narration now being heard did **not** make any SI sentence wrong — the
  relevant clause ("If the robot's own systems report an action, describe it;
  never decide it") was written for precisely this channel and was live-observed
  working in session 1(c), where the model described a failure it could only have
  learned from the narration. Nothing to report there.
* **The 25-thread corpus stays an SI-v1 artifact.** No `evals/` file was read or
  written. Its `scrape_realtime_convo.py` builds `user` items with `input_text`,
  which is the value R8 confirms, so there is no provenance conflict to resolve
  and no test conflates the two. The frozen-digest and release-parity gates
  confirm nothing moved.
* **The two pre-existing unknown server events are still unknown** (R7 open risk
  4): `input_audio_buffer.committed` and
  `conversation.item.input_audio_transcription.delta` landed in
  `lane.protocol_errors` four times in session 2. Left alone deliberately — see
  Open risks 3.
* **Nothing was committed, staged or stashed.** `git stash list` is empty and the
  other cards' uncommitted work is exactly as it was found.

## Open risks, honestly

1. **A repay is bounded per TURN, and a new spoken turn resets the bound — so a
   provider that emits `speech_stopped` and never answers can be repaid
   indefinitely.** This is exactly symmetric with `send_text`, which has always
   reset the budget for every typed turn, and it is rate-limited by the backoff
   ladder (doubling, capped at 30 s) rather than by `_repay_limit`. But server VAD
   fires on noise as well as on the owner, so in `mode: audio` the resetting
   party need not be a person. `voice_turns_owed` beside `turn_repays` in the
   snapshot is the pair to watch; a VAD-noise floor is the real fix and it is a
   design question, not a one-liner.
2. **`_repay_turn` can never currently be reached with `voice=True` and the
   budget spent**, because `_connect` clears `_voice_turn_owed` and only a fresh
   utterance can set it again — and a fresh utterance resets the budget. So the
   `voice` argument's interaction with the abandon bound is, today, unreachable
   code. It is written the safe way (a voice repay spends the budget like any
   other, seed S24) so that it stays correct if `_connect`'s clearing is ever
   relaxed, but an auditor should know it is defensive rather than exercised.
3. **`protocol_errors` is still noise that will hide a real protocol error.** Two
   unknown event types log on every audio session (four rows in 40 seconds in
   session 2). R8 makes this *worse* in one specific way: `server_errors` is now a
   genuinely useful diagnostic surface, and having a second, permanently-dirty
   error list next to it invites a reader to ignore both. Adding the two types to
   `LIFECYCLE_EVENT_TYPES` is a three-line change I deliberately did not make —
   it is not "a pin the change needs" and it deserves its own wire capture — but
   it should be the next `protocol.py` card's first line.
4. **`test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove`
   is a wall-clock assertion in a HARD gate.** It reddened two full gate runs of
   mine purely because the owner's `llama-server` was at 1469 % CPU. Any executor
   who runs the gate while the owner's stack is inferencing will hit it and may
   waste a long time deciding whether it is theirs. It should either get headroom
   or be marked `slow`.
5. **The narration channel now works, which means it can now spam.** Every
   `narrate_event` that lands costs a response, and until this card none of them
   did — so every historical measurement of hosted spend was taken with the
   narration channel silently free. `narrations` is the number to watch, the floor
   gate (now four noes) is what bounds it, and the first long live session in
   `mode: audio` should be looked at with that in mind before anyone concludes
   the cost model is unchanged.
6. **`recent_server_errors` puts item text into `/api/state`.** Bounded to five
   records, and the text is a memory-tail row or a narration the panel already
   renders elsewhere — but it is conversation content in a diagnostic field, and
   if `/api/state` is ever exposed beyond loopback that is a consideration.
7. **`voice_turn_owed` clears on ANY `response.done`.** If the provider ever
   completes a response that is not about the spoken turn (a stray tool beat, a
   cancelled response landing late), the spoken turn is marked answered when it is
   not. This mirrors `_responses_pending`'s existing coarseness — neither
   correlates by response id — and correlating them properly is the tidier fix
   whenever someone next opens this accounting.

## Orphaned work assessment — who wrote what

**This card had two executors.** The first was killed; the second (me) finished
it. The auditor asked for the provenance split explicitly, so here it is, with
the timestamps that establish it. Everything above this section except where
noted was written by executor 1; my contribution is verification, not code.

**What happened.** Executor 1 did the whole card — code, tests, wire probe, seed
harness, both live sessions, three gate runs — and was killed. I was dispatched
on the stated understanding that it had died *before writing anything down* and
that no `R8_STATUS.md` existed. That understanding was very slightly stale:
`R8_STATUS.md` (704 lines, the document you are reading) appeared on disk at
**`00:23:23`**, a few minutes into my session, between my first `ls` of
`scrum/20260819/task_1/` (which showed `README.md` alone) and my next listing.
Executor 1 was evidently alive long enough to flush it and then died. No process
was writing it by the time I looked (`ps` showed only the owner's stack; no agent
was reachable). **I did not author the body of this document.** I audited it.

**Inherited from executor 1 — verified correct, not redone:**

| Artifact | mtime | Verified how |
| --- | --- | --- |
| `protocol.py` — `CONTENT_TYPE_BY_ROLE`, `event_id` on items and errors | 23:49:33 | md5 `1cce5131846cbeebfe6247053d95fd75`, matches the doc's claim exactly |
| `lane.py` — `_send_item`, `_on_server_error`, `_arm_voice_turn`, `_repay_turn(voice=)`, six snapshot keys | 23:49:49 | md5 `3fd34906518e215a90b895e08527acc1`, matches exactly |
| `tests/test_realtime_protocol.py` | 23:36 | collects **39** — the claimed 30 + 9 |
| `tests/test_realtime_lane.py` | 23:38 | collects **66** — the claimed 65 + 1 |
| `tests/test_realtime_reconnect.py` | 23:42 | collects **61** — the claimed 44 + 17 |
| wire probe `wire_content_types.py` / `.json` | 23:26 / 23:27 | read in full: nine pairs, six refusals, `error.event_id` echo present on all six |
| seed harness `seed_r8.py` + `seeds_final.txt` | 23:42 / 23:49:49 | re-run from scratch by me — see below |
| live session 1 `live_r8.py`, `live/` | 23:44–23:48 | evidence JSON read in full; claims (a)(b)(c)(d) all present in it |
| live session 2 `live_voice_r8.py`, `live_voice/` | 23:48–23:49 | evidence JSON read in full; armed signal + repay present |
| gate runs `gate_final.txt` (RED), `gate_final2.txt` (RED), `gate_final3.txt` (GREEN) | 23:55 / 00:02 / 00:18 | all three read; the two reds are the `test_cpu_budget_proxy` flake reported above |
| `R8_STATUS.md` body | 00:23:23 | audited claim by claim |

**Added by me (executor 2) — this is the whole of my contribution:**

1. **An independent 26-seed re-sweep.** I did not take `seeds_final.txt` on
   trust. I re-ran `seed_r8.py` end to end against the tree as it stands, having
   first recorded sha256 digests of both source files. Result: **26/26 RED,
   harness exit 0, and both files restored byte-identically** (`pre_seed_digests.txt`
   vs `post_seed_digests.txt` diff clean). Verbatim output in
   `<scratchpad>/r8/seeds_rerun.txt`. This is a second, independent confirmation
   of the seed table above, taken by a different executor.
2. **A fresh full `ci_gate --tier commit` run** on the final tree — quoted
   verbatim in §The gate below as the *confirming* run, alongside executor 1's.
3. **Digest and count verification** of every mechanical claim the document
   makes: both md5s, `configs/robot.yaml` sha256
   (`f7b57dcd…`, unmoved), the three test collection counts, and `git stash list`
   empty. All matched.
4. **A MUST-NOT-TOUCH sweep.** `find src tests scripts -newermt '2026-08-19 23:00'`
   returns **only** the five OWNS files (two source, three test) and their
   `__pycache__`. `ingress.py` (**Aug 16** 20:23 — R9's file, untouched all card),
   `tool_broker.py`, `prompting.py`, `runtime.py`, `web_panel.py` all predated the
   R8 window by days at the time of the sweep. The card's coordination constraint
   with R9 held. *After* my confirming gate, another card's executor wrote
   `runtime.py` and `ui/index.html` — see the note under §The gate; that is their
   work, not R8's, and R8's two OWNS source files still carry the exact digests
   the gate ran against.
5. **One correction to a claim that has since gone stale** — below.

**The one correction.** The Live-proof section states the owner's
`parcel_memory.sqlite3` mtime was `Aug 19 23:25` and "unchanged after both"
sessions. That was true when written. It is **no longer true**: the file's mtime
is now **`2026-08-20 00:23:30`**. It is not this card. `lsof` shows the owner's
own live panel — `PID 1703565`, `python -m parcel_robot.web_panel --port 8765`,
started `23:21:51` and still running — holding it open read-write on FD `4u`, and
it is the **only** process with the file open. The write lands 7 seconds after
executor 1 flushed this document and roughly 34 minutes after the last R8 live
session ended (`03:49Z`). Neither executor opened it; both live proofs ran on
`memory: path: ":memory:"`. The isolation claim stands; only the *evidence* for
it (an unmoved mtime) has been overtaken by the owner's own stack, and an auditor
checking that mtime today should not read it as a violation.

**What I did not do:** I wrote no source code, no test, and no seed. I changed
nothing under `src/` or `tests/`. My only repository edit is this section, the
seed re-run note, and the confirming gate output.

8. **This card was finished on a tree that other cards are actively editing.**
   `runtime.py` and `ui/index.html` moved within a minute of the confirming gate,
   and `scrum/20260819/task_3`, `task_4` and `task_5` were being written
   throughout. R8's own surface is small and digest-pinned, so its green is
   sound — but nobody should read "the gate is green" as a statement about the
   *whole* working tree at any moment after `00:31:52`. Whoever commits this wave
   should re-run the gate once the other cards have landed.

## Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r8/`

| File | What |
| --- | --- |
| `wire_content_types.py` / `.json` | the nine-pair wire probe and every frame it read back |
| `seed_r8.py` | the 26-seed harness (mutate one source file → named pytest target → restore in `finally` → assert sha256 identical) |
| `seeds_final.txt` | the final full seed sweep, verbatim |
| `gate_final3.txt` | the green gate quoted above |
| `gate_final.txt` / `gate_final2.txt` | the two red runs, kept rather than deleted |
| `live_r8.py` | session 1 (claims a-d), in-process runtime, headless MuJoCo city, `:memory:` ledger |
| `live/session.log` | session 1's full transcript, verbatim |
| `live/evidence.json` | session 1 machine-readable: tail replay by role, narration, mission log, snapshot, spend |
| `live_voice_r8.py` | session 2, the voice-turn signal: piper → `lane.send_audio` → real provider → forced deafness → repay |
| `live_voice/evidence.json` | session 2 machine-readable: the armed signal, the repay, system rows, snapshot, spend |
| `seeds_rerun.txt` | **executor 2's** independent 26-seed re-sweep, verbatim |
| `pre_seed_digests.txt` / `post_seed_digests.txt` | source sha256 either side of that re-sweep; diff is clean |
| `gate_confirm.txt` | **executor 2's** confirming gate run on the final tree |

## Restart required

`lane.py` and `protocol.py` are not hot-reloadable. The owner's stack — currently
LIVE on `:8765` and running the pre-R8 code, which means it is *right now*
replaying only half of every conversation and dropping every narration — must be
relaunched to pick this up:

```
./scripts/launch_stack.sh
```

No config change is needed. The two new constructor arguments
(`item_trace_limit`, `server_error_window`) exist for tests and default to the
values above.
