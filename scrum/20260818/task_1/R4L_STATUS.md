# R4-lite task_1 — the mission you can see, the session that survives

**Date:** 2026-08-18 · **Card:** `scrum/20260818/task_1` · **Executor:** Claude Opus (agent)
**Auditor:** Fable
**Depends on:** R1.6+R3 (`20260817/task_6`), R1.5 (`20260817/task_1`), FIX-A (`20260814/task_1`)
**Baseline:** `8473a51` at session start, plus a large uncommitted wave from
other cards (untouched). **HEAD moved during this session, not by me:** the
owner's own commit `877d9f4 "Implemented voice agent"` (author Jae, dated
2026-08-17) landed on top of `8473a51` mid-session and touches `lane.py`
(+860) and `runtime.py` (+180). Verified that **none** of this card's work is
in it — `narrate_event`, `ensure_session`, `_responses_pending`, `_entered`,
`recovering`, `mission_log`, `_log_mission_terminal` and
`_emit_proximity_change` all appear 0 times in the committed blobs and only in
the working tree. This card staged, committed and stashed nothing; `git stash
list` is empty. Both green gate runs below were taken against the tree as it
stands now, i.e. on top of `877d9f4`.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## What landed, in one paragraph

Defect A had a single root cause and it was not in the reconnect logic — it was
in the *window* the reconnect leaves open. `_reconnect` closed the socket,
blocked in the backoff, and only then opened a new one, and for that whole
window `lane.active` read False. `submit_realtime_text` read exactly that flag
from the panel's HTTP thread, concluded the lane had no session, opened one of
its own, and sent the owner's turn into it; the driver thread then finished its
reconnect and replaced `self.transport`, **orphaning the socket holding the
turn** — open, unread, answered to nobody. The lane now owns a re-entrant lock,
`_connect` closes whatever transport it replaces, `ensure_session` takes the
"do I need a session?" decision while holding the lane, a dropped owner frame
raises instead of returning a phantom 202, and the watchdog covers the
`response.create` that follows a tool answer and can recover a lane whose
socket died. Defect B's silent terminal was `_stop_navigation_channel` — the
choke point every non-arrival terminal passes through — writing `enabled:
False` into the detail and telling nobody; it now records to a dedicated
20-slot `mission_log` ring, emits a panel event, and hands the fact to the
model behind a floor gate. The panel renders the ring and a live mission status
line beside the chat. Two live proofs found two real defects that the offline
tests had missed, both now fixed and seeded.

## Root cause — Defect A (exact state and line)

`RealtimeLane._reconnect`, `lane.py` (pre-fix lines 926–950):

```python
if self.transport is not None:
    self.transport.close()      # <- self.transport is now a closed corpse
self._backoff_wait(reason)      # <- blocks here, 0.25 s .. 30 s
...
self._connect()                 # <- only NOW is self.transport usable again
```

`active` (lane.py:399–401) is `transport is not None and not transport.closed`,
so it is **False for the whole blocking window**. `runtime.submit_realtime_text`
(runtime.py 4608–4619, pre-fix) read that flag from the HTTP thread:

```python
if not lane.active:
    lane.open_session(handshake_token=token, mic_gesture=True)
lane.send_text(clean)
```

The interleaving, reproduced deterministically offline (`probe_race.py`, now
`test_a_turn_that_arrives_during_the_backoff_is_not_lost`):

| # | driver thread | HTTP thread | result |
| --- | --- | --- | --- |
| 1 | watchdog fires, `stalls=1` | | |
| 2 | `_reconnect`: close socket S1, `reconnects=1` | | |
| 3 | blocked in `_backoff_wait` | reads `active` → **False** | |
| 4 | | `open_session()` → builds **S2** | |
| 5 | | `send_text()` into S2 — ingress runs: ledger row written, `utterance_sequence` advanced | panel returns **202** |
| 6 | wakes, `_connect()` → builds **S3**, overwrites `self.transport` | | **S2 orphaned** |
| 7 | pumps S3 forever | | the turn's answer arrives on a socket nobody reads |

Every observable in the incident report is reproduced exactly: `stalls: 1`,
`reconnects: 1`, turn accepted with 202, ledgered, `utterance_sequence`
advanced, no response, no tool call, broker counters frozen — and a perfectly
healthy session on the panel that had never heard the question.

Four further deafness holes were found while pinning it, each its own seed:

1. `_send` answered `TransportClosed` with a note and returned, so `send_text`
   could accept, ledger and 202 a turn whose frames never left the process.
2. `_on_response_done` cleared `_expecting_server` outright. A tool turn has
   **two** responses outstanding — the owner's and the follow-up the lane sends
   with the tool answer — so the first `response.done` disarmed the watchdog for
   the second. A provider that went silent after a tool call was invisible.
3. `tick()` returned `None` whenever `active` was False, i.e. the watchdog — the
   only thing in the product that reconnects — refused to run in precisely the
   state it exists for.
4. `_connect` never closed the transport it replaced.

## Root cause — the silent mission terminal (Defect B)

`RobotRuntime._stop_navigation_channel`, runtime.py 1348–1356 (pre-fix):

```python
if was_enabled:
    self._navigation_detail = NavigationDetail.from_dict(
        {**self._navigation_detail, "enabled": False, "state": state, "reason": reason}
    ).as_dict()
```

No `_emit`, no record, no sentence. `was_enabled` is True exactly when a live
mission was just ended, so the method *knows* it is a terminal and says nothing.
Every non-arrival terminal funnels through here: `preempt()`,
`_stop_semantic_dispatches` (the executive's task teardown),
`stop_navigation()`, `set_behavior("stay")`, `_enable_owner_follow`, the yield
policy's honest give-up. The dataclass default `reason="navigation_disabled"`
(`core/details.py:24`, keyword default at runtime.py:1331) is what the detail is
left holding when the caller does not say why — which is precisely the
`enabled: false, goal: sidewalk, reason: navigation_disabled` the owner saw.
`goal` survives because the write spreads the previous detail.

Second, independent half: even a terminal that *did* emit could be evicted.
`_events` is `deque(maxlen=100)` shared with every source in the runtime, and
the proximity slow/clear pair was edge-triggered against a threshold that flaps
at the 10 Hz control rate — ~10 events/s, enough to flush the whole deque in ten
seconds.

## What landed

| File | Lines (this card) | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/lane.py` | +277 / −35 | Lock + `ensure_session` + `recovering`; `_connect` closes what it replaces; `required` sends; `_responses_pending`; self-recovering watchdog; `narrate_event`; snapshot fields |
| `src/parcel_robot/runtime.py` | +313 / −8 | `mission_log` ring + `_log_mission`/`_log_mission_terminal`/`_note_mission_block`; terminal emission at every site; `_emit_proximity_change`; narration gate; `ensure_session` wiring; snapshot key |
| `src/parcel_robot/ui/index.html` | +139 / −0 | Mission log list, live mission status line, CSS, two render calls |
| `src/parcel_robot/realtime/tool_broker.py` | +7 / −1 | Defect C: structured `navigate_to` detail |
| `tests/test_realtime_reconnect.py` | 731 (new) | 19 tests: the race, orphans, drops, watchdog arming, self-recovery, narration gate |
| `tests/test_mission_log.py` | 543 (new) | 24 tests: silent terminal, blocked edges, ring bounds, chatter, narration |
| `tests/test_realtime_tool_broker.py` | +22 / −0 | Defect C pin |
| `tests/test_nominal_stop_wiring.py` | +12 / −1 | **Ratchet regenerated** — see Deviations |
| `scrum/20260818/task_1/R4L_STATUS.md` | this file | |

`web_panel.py` needed **no change**: `/api/state` passes `runtime.snapshot()`
through verbatim, so a new top-level key reaches the browser with no
registration. Line counts for `lane.py`/`runtime.py`/`index.html` are this
card's share, derived by subtracting task_6's reported figures from the current
cumulative `git diff --numstat`; the cumulative numbers are 452/40, 799/18 and
224/1 and include other cards' uncommitted work.

## Gate — `ci_gate --tier commit`, verbatim

```
CI GATE — tier=commit  (2026-08-18T06:11:32Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  release-parity-integrity   10 passed in 0.72s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.28s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.33s
[  PASS] HARD  default-suite              6151 passed, 9 skipped, 42 deselected, 5 warnings in 236.77s (0:03:56)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 249.3s
```

## Seeds — 19 seeded defects, all RED

(Re-run after the final source edit: all 19 still RED.)

Harness restores every file byte-identically and asserts it. Full table:

| # | Seeded defect | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- |
| S1 | reconnect window race restored: the panel opens a competing session mid-reconnect | **RED** | 1 failed, 18 passed in 0.60s :: test_a_turn_that_arrives_during_the_backoff_is_not_lost |
| S2 | reconnect orphans the socket it replaces (the live incident's fingerprint) | **RED** | 1 failed, 18 passed in 0.52s :: test_opening_over_a_live_session_closes_the_socket_it_replaces |
| S3 | a dropped owner turn is swallowed again: 202 for a turn that never left | **RED** | 1 failed, 18 passed in 0.52s :: test_a_dropped_owner_turn_refuses_instead_of_acknowledging |
| S4 | post-tool `response.create` no longer arms the watchdog | **RED** | 1 failed, 18 passed in 0.52s :: test_the_watchdog_watches_the_response_that_follows_a_tool_answer |
| S5 | an armed lane that lost its transport cannot recover itself | **RED** | 1 failed, 18 passed in 0.52s :: test_an_armed_lane_that_lost_its_transport_recovers_itself |
| S6 | `close()` during a reconnect resurrects the socket (a live socket keeps billing) | **RED** | 1 failed, 18 passed in 0.52s :: test_closing_during_a_reconnect_does_not_resurrect_the_socket |
| S7 | the mission terminal goes silent again: `_stop_navigation_channel` tells nobody | **RED** | 12 failed, 12 passed in 1.50s :: test_a_mission_terminal_is_never_silent, test_the_default_reason_terminal_is_recorded_too |
| S8 | the mission log is folded back into a 1-slot ring and evicted by chatter | **RED** | 7 failed, 17 passed in 1.43s :: test_the_way_clearing_again_is_its_own_entry, test_a_changed_block_class_is_a_new_entry |
| S9 | blocked entries stop being edge-triggered: 10 Hz of rows floods the ring | **RED** | 1 failed, 23 passed in 1.44s :: test_the_ring_survives_a_long_block_with_room_for_the_terminal |
| S10 | narration becomes per-tick spam | **RED** | 2 failed, 22 passed in 1.42s :: test_the_way_clearing_again_is_its_own_entry, test_the_ring_survives_a_long_block_with_room_for_the_terminal |
| S11 | the narration floor gate is removed: the robot talks over its own voice | **RED** | 3 failed, 21 passed in 1.43s :: test_the_floor_gate_refuses_when_the_floor_is_taken[×3] |
| S12 | proximity chatter is un-coalesced again and flushes the event deque | **RED** | 1 failed, 23 passed in 1.43s :: test_proximity_chatter_is_coalesced_not_repeated |
| S13 | a proximity STOP is withheld by the rate limiter (safety fact suppressed) | **RED** | 1 failed, 23 passed in 1.43s :: test_a_proximity_stop_is_never_withheld |
| S14 | the legacy ack template returns to the model on the realtime navigate path | **RED** | 1 failed, 33 passed in 1.04s :: test_the_navigate_detail_is_structured_not_the_legacy_ack |
| S15 | the mission log never reaches the snapshot | **RED** | 1 failed, 23 passed in 1.43s :: test_the_mission_log_reaches_the_snapshot |
| S16 | narration is no longer floor-gated inside the lane either | **RED** | 2 failed, 17 passed in 0.53s :: test_narration_is_refused_while_the_model_has_the_mouth |
| S17 | the blocked edge keys on the raw note again (live telemetry = every tick is an edge) | **RED** | 1 failed, 23 passed in 1.43s :: test_the_ring_survives_a_long_block_with_room_for_the_terminal |
| S18 | blocked rows evict lifecycle rows again: a long block pushes the terminal out | **RED** | 1 failed, 23 passed in 1.44s :: test_a_flapping_pedestrian_stream_cannot_fill_the_ring |
| S19 | blocked rows are no longer rate-limited: real pedestrian flapping floods the ring | **RED** | 2 failed, 22 passed in 1.44s :: test_a_flapping_pedestrian_stream_cannot_fill_the_ring, test_blocked_rows_are_rate_limited_on_the_injected_clock |

The card's four required seeds map to: reconnect-deafness = S1–S6, terminal
event dropped = S7, mission_log evicted by chatter = S8/S9/S17/S18/S19,
narration spams per-tick = S10/S11/S16.

## Live proof

The owner's stack on :8765 was **already down** when this card started
(connection refused), so nothing of theirs was disturbed. Three sessions were
spent on a stack of my own on **:8799**, socket `/tmp/parcel_r4l.sock`, model
`gpt-realtime-2.1-mini`, `mode: text`, config `~/.config/parcel/realtime.yaml`
(the owner's own, outside the repo — `configs/realtime.yaml` stays absent, so
`test_the_repo_ships_no_realtime_config_so_flag_off_is_file_absent` is untouched).

| Session | Purpose | Outcome | Cost |
| --- | --- | --- | --- |
| 1 (05:53) | end-to-end proof | **found a real defect** — 20/20 mission_log slots filled with blocked rows in 2 s, and 69 model narrations from one turn | not sampled before teardown; ~74 responses |
| 2 (05:57) | re-proof after the class-key fix | **found a second defect** — 18/20 slots still blocked; class flapping is real | not sampled |
| 3 (06:03) | final end-to-end proof | **PASS** | `spend_usd: 0.011146` |

Session 3, verbatim highlights:

```
POST /api/realtime/text -> 202  {"accepted":true,"session_id":"rt_5d6c83bca91a","mode":"text"}

[LOG    2.3s] started  searching    Navigating to sidewalk.
[CHAT   2.3s] assistant: Okay, let me check and get ready to move toward that sidewalk with you.
[CHAT   3.3s] assistant: Alright, I'm moving toward the sidewalk now.
[LOG   13.3s] blocked  blocked      Waiting: someone is in the way near sidewalk.
[LOG   24.4s] blocked  blocked      Waiting: someone is in the way near sidewalk. (+3 more changes in the last few seconds)
[LOG   36.4s] blocked  blocked      Waiting: something is blocking the way to sidewalk. (+10 more changes ...)
[LOG   59.4s] blocked  navigating   The way to sidewalk is clear again; carrying on. (+6 more changes ...)
[LOG  ~132s] ended    failed       Mission to sidewalk ended (failed): semantic_target_unreachable.

lane:   stalls: 2, reconnects: 2, disconnects: 0, dropped_sends: 0,
        recovering: false, active: true, protocol_errors: [],
        backoff_waits_s: [0.30266, 0.453404], narrations: 2, narrations_skipped: 0
broker: calls 1, executed 1, last.detail "mission accepted: sidewalk"
driver: failures: []
spend_usd: 0.011146
```

What this proves, item by item:

* **Defect A, live.** Two stall-reconnects happened *during* the run
  (`stalls: 2, reconnects: 2`) and the lane stayed `active: true` with
  `dropped_sends: 0` and no orphaned session; the mission kept running and the
  panel kept showing it. Backoff was bounded and jittered on the live clock:
  `[0.303, 0.453]`.
* **Defect B, live.** `Mission to sidewalk ended (failed): semantic_target_unreachable`
  is exactly the class of ending that was silent before — now a `mission_log`
  row *and* a panel event. The start row and the terminal both survived a
  two-minute mission that spent most of its life blocked.
* **Defect C, live.** `broker.last.detail == "mission accepted: sidewalk"`.
* **Chatter, live.** Proximity events coalesced to a handful with explicit
  `(+N more proximity changes …)` counts; blocked rows likewise.

### Did the model NARRATE the pedestrian block? — honestly, not proven

The four spoken lines about the pedestrian in session 3 are the **pre-existing
deterministic yield-policy utterances**, not model narration. They are
hardcoded at `core/yield_policy.py:275,279` and `configs/personality.yaml:75,78`
("Someone is standing right where I need to go, so I've stopped…"). The
narration hook *did* fire — `narrations: 2, narrations_skipped: 0`, so two
system items plus `response.create` reached the provider through the floor gate
— but no assistant turn attributable to them came back inside the window, and
`usage_rows: 2` against `stalls: 2` says those two responses are the two that
stalled. **The narration path is wired, floor-gated, bounded and delivered, but
"the model says it out loud" is NOT proven live.** This is the card's single
unmet claim and is listed as an open risk below.

## Deviations

1. **The `_dispatch_active` stopping-predicate ratchet was regenerated.**
   `tests/test_nominal_stop_wiring.py` pins an AST digest of `_dispatch_active`,
   and moving the proximity transition event into `_emit_proximity_change`
   moved it. The test's own docstring provides for this ("regenerate … and
   record WHY in the batch status doc — do not delete this test"); the
   regeneration log has a new dated entry. Nothing about *which stops may ramp*
   changed: `proximity_state` still comes from the same `_collision_safe` call,
   is still assigned on every transition, and `emergency_stopping`,
   `zero_intent`, `stopping` and `nominal_ramp` are untouched. Only the event
   text moved. This file is outside the card's OWNS list and is flagged
   deliberately.
2. **No goal-distance in the status line.** The card asks for
   "state/goal/distance/blocked-reason". `NavigationDetail` carries no distance
   (`core/details.py:19–33`) and `goal` is a label, not coordinates, so the
   browser cannot compute one. The line shows nearest-obstacle **clearance**,
   labelled as clearance, rather than mislabelling it as distance-to-goal.
   Publishing a real `goal_distance_m` needs the navigation pipeline and was
   out of scope.
3. **The mission log lives in the "Behavior & safety" panel**, not as a fourth
   column in the command layout: adding a fourth `.log-box` would have forced
   edits to the three-column grid and both media queries. The live status line
   is where the card asked for it — directly under the chat heading.
4. **`ensure_session` is new API on the lane** and `submit_realtime_text` now
   calls it instead of reading `lane.active`. That is a runtime change inside
   OWNS, but it is the half of the Defect A fix that lives outside `lane.py`;
   the lock alone cannot fix a decision taken before the lock is acquired.
5. **Two live sessions were spent on debugging**, both because a live run
   falsified an offline test. Within the card's authorisation (one proof, one
   forced-stall check, up to two debug sessions); the forced-stall check was
   not needed separately because both stall-reconnects occurred naturally
   inside the final proof and are recorded above.

## Owner-gated / not touched

* **Yield patience itself is B22 and was not touched.** No threshold, profile,
  keepout or give-up timing changed. `test_narration_never_shortens_the_wait`
  asserts that recording and narrating a block leaves `person_stop_m`, the
  yield profile and the yield tracker byte-identical. The card's rule —
  *narrate the wait, never shorten it* — is honoured: the new code only
  observes.
* The deterministic yield utterances stay the audible channel. Nothing in this
  card adds a second one.

## Open risks, honestly

1. **Model narration of terminals is unproven live** (see above). It is
   delivered and bounded; it has never been *heard*. A cheap follow-up is one
   forced narration with no mission running, checking for an assistant turn.
2. **The blocked-row rate limit is a judgement call at 10 s.** It is right for
   a demo where the live status line carries "blocked right now", but a mission
   that flaps for minutes produces a log that undercounts episodes. The folded
   count keeps it honest rather than accurate.
3. **`stalls: 2` in a two-minute live session is high** and is *not* explained
   by this card. The lane now survives it, which is the fix; why
   `gpt-realtime-2.1-mini` goes quiet mid-turn that often is unexamined. The
   watchdog masking question is answered — counters keep counting, and the
   panel now shows `recovering` and `dropped_sends` — but the underlying
   provider behaviour is an open question for a future card.
4. **The entry timeout is 10 s.** A provider outage deep in the backoff ladder
   (cap 30 s) will make `/api/realtime/text` refuse with a clear message rather
   than wait. That is deliberate — a loud refusal beats a phantom 202 — but it
   is a behaviour change the owner will notice during a bad provider day.
5. **Session-1 and session-2 costs were not sampled** before teardown; only
   session 3 has a recorded `spend_usd` (0.011146). Session 1 was the expensive
   one (~74 responses from a single turn, the narration-spam defect) and is
   likely a few cents. Total for this card is well under a dollar but the exact
   figure for sessions 1–2 is lost.
6. **A pre-existing `pump failed: … DuplexVoiceSession output is live` appeared
   three times in live session 1** and not at all in session 3. It is a
   sink-ownership assertion firing in text mode where there is no local voice
   session; it predates this card and was not investigated.
7. **The `mission_log` blocked-row cap is `MISSION_LOG_MAX // 2`.** If a future
   card raises the ring size it changes silently with it. That is intended, but
   it is a coupling worth knowing about.

## Restart required

The fixes are in `runtime.py`, `lane.py`, `tool_broker.py` and `index.html`.
The owner's stack must be **restarted** to pick any of them up — none of it is
hot-reloadable, and `index.html` is read at request time but the snapshot key
it renders comes from the running runtime. My own stack on :8799 has been shut
down; nothing of the owner's was started, stopped or touched.
