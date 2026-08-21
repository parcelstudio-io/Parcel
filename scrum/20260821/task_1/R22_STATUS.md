# R22 — the pump that cannot die quietly

**Date:** 2026-08-21 · **Card:** `scrum/20260821/task_1/README.md`
**Executor:** Claude Opus (agent) · **Auditor:** Fable — **DEFERRED at the owner's
request.** This document is written to audit cleanly weeks from now with nobody
to ask: every claim below names the file, the test, the seed or the artefact
that carries it, and every place the evidence stops is marked
`does_not_prove`.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Tree:** sole executor, one card, one tree. Nothing committed, staged or stashed.
**Trigger:** `scrum/20260820/AUDIT_FULL_FABLE.md` §Confirmed findings NOT
previously known or carded → Safety, bullet 1. CONFIRMED, and *strengthened* by
the adversarial refuter, who walked the exception MRO.

---

## §0 — One paragraph

The realtime pump thread could die permanently and silently, and the
conversation-ledger write — raw sqlite, on that same thread — was the trigger
sitting closest to hand. `sqlite3.Error` subclasses `Exception` and **none** of
the four types the driver caught, so a disk-full or a locked database mid-turn
killed the pump and with it the spoken e-stop relay, the stall watchdog, the
60-minute rollover and the idle hang-up, with the microphone still open and
nothing anywhere alarming. Three mechanisms close it and none of them is enough
alone: **the firewall** (every loop body now catches `Exception`, never
`BaseException`, each failure counted by exception TYPE), **the alarm** (a dead
pump sets `driver.alive` False, names a reason, ages a heartbeat, writes a
SAFETY-class row into the eviction-proof ring and the on-disk evidence log, and
raises a banner in the panel beside the emergency-stop history), and **bounded
revival** (the loop restarts itself on an exponential ladder, counted and
ledgered, five attempts, and then dies loudly rather than hot-looping against a
lane that is genuinely gone). The sqlite blindspot is killed at all four sites
the card named, **at the source**: `memory.write_realtime_turn` now catches the
whole `sqlite3.Error` family and returns row id `0`, while still raising
`ValueError` for bad arguments. EV-1's last open hole (§10.3) is closed:
`RetainedEvent` frames reach the session evidence log's own sink and never
`_note`. **36 seeds RED**, every restore byte-identical, every fresh-interpreter
canary green. **Full gate PASS at 7218 passed** (7164 → 7218, **+54, 0
removed**). Live on my own stack with a **real read-only sqlite file**, not a
monkeypatch: the pump survived, kept stepping, and a spoken "Die stop." latched
afterwards — **including against the real hosted provider**, for $0.0125.
**Four things went against me and are reported as such** (§8): two seeds came
back GREEN and both found real holes in my own panel tests; two more came back
BROKEN on a canary quoting bug; an existing lane test's assertion had to move
(§8.1); and the one work item with **no live evidence at all** is the ASR
retention handoff, because text mode produces zero ASR frames (§7.4).

---

## §1 — What changed

| File | Change | Card item |
| --- | --- | --- |
| `src/parcel_robot/realtime/driver.py` **258 → 667 lines** | the whole card, items 1/2/3/6: broad firewall on all four `step()` calls and on `_loop`; `alive`, `heartbeat_age_s()`, `ensure_alive()`; `_die` / `_revive` / `_alarm`; `failure_types`, `revivals`, `deaths`; the corrected module docstring | 1, 2, 3, 6 |
| `src/parcel_robot/realtime/lane.py` **2699 → 2843** | `_pump_locked` dispatch firewall + `_record_dispatch_failure`; `_write_ledger` broad guard + counters; the `RetainedEvent` branch and `_retain`; `retention_sink=` constructor arg; nine new snapshot keys | 1, 4, 5 |
| `src/parcel_robot/runtime.py` | `_realtime_pump_alarm`, `_realtime_pump_snapshot`, `_watch_realtime_pump`, `_retain_realtime_frame`; `_RealtimeLedgerMirror` firewalled at both halves + `snapshot()`; `_write_realtime_ledger` broad guard; two new safety kinds and one new safety source; the `pump` block in `realtime_snapshot()`; one line in `_service_health_loop`; the two wiring args at lane/driver construction | 1, 2, 3, 4, 5 |
| `src/parcel_robot/memory.py` **611 → 673** | `write_realtime_turn` catches `sqlite3.Error` at the primary write, counts it by type, returns `0`; `realtime_write_failures` / `_types` / `last_realtime_write_error`; a module `logger` | 4 |
| `src/parcel_robot/ui/index.html` | `#pump-alarm` banner inside the safety-log block + `renderPumpAlarm` + its call site; `SAFETY_KIND_LABELS` / `safetyKindLabel`; CSS for the banner and the two new row kinds | 2 |
| `tests/test_realtime_pump_survival.py` **(NEW, 1104 lines)** | **54 tests** | DoD |
| `tests/test_realtime_lane.py` | ONE existing test's assertion moved — declared as a deviation in §8.1 | 1 |

Nothing outside `OWNS` was touched. The ingress matcher, prompting/SI, whisperer
bands, broker tool set, yield policy, `evals/**` and every config are
byte-identical (the closing gate's `frozen-digest-sentinels` and
`release-parity` are the mechanical proof).

---

## §2 — The gate, verbatim

Run after the final source edit, read, then pasted. This is the **re-run after
the last edit in the card** (the status doc itself); the identical run at
`07:15:29Z`, before the doc was written, is at `<scratchpad>/r22/gate_1.txt` and
agrees line for line on every gate and every count.

```
CI GATE — tier=commit  (2026-08-21T07:25:16Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.32s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              7218 passed, 9 skipped, 42 deselected, 5 warnings in 271.98s (0:04:31)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 285.0s
```

**7164 → 7218, +54, 0 removed** — exactly the 54 cases in
`tests/test_realtime_pump_survival.py`, so this card added tests and broke none.
`9 skipped / 42 deselected` is unchanged from the entering baseline, so nothing
was skipped or deselected to get here. `ruff` is at its pinned baseline of **7
with new 0**; all seven pre-existing violations remain in `camera_channel/` and
`detection_adapter/`, untouched, and every file this card writes is clean under
`ruff check` on its own. Two `S110` violations *were* introduced mid-card and
are gone: `_note` and `_alarm` originally ended `except Exception: pass`, which
ruff correctly flags. They now count the failure instead
(`driver.note_failures` / `driver.alarm_failures`), which is a better answer
than the lint that forced it — a driver whose only two wires out are both cut
should not be the one fact that is silent.

Artefact: `<scratchpad>/r22/gate_1.txt`.

---

## §3 — Item 1: the firewall, and the type that got through

### 3.1 The fact the whole card rests on

The refuter's MRO claim is now **asserted in the suite** rather than quoted from
a markdown file
(`test_the_refuters_mro_claim_is_true_here_and_not_only_in_the_audit`):

```python
assert issubclass(sqlite3.Error, Exception)
assert not issubclass(sqlite3.Error, (OSError, RuntimeError, TypeError, ValueError))
```

If a future Python ever made `sqlite3.Error` an `OSError`, the old four-type
list would have been adequate and this card's premise would be wrong. That is
now a red test rather than an assumption.

### 3.2 Five sites, all broad

| Site | Was | Is |
| --- | --- | --- |
| `driver.step` → `lane.pump()` | `except (OSError, RuntimeError, TypeError, ValueError)` | `except Exception` |
| `driver.step` → `instructions.refresh()` | `except (RuntimeError, TypeError, ValueError)` | `except Exception` |
| `driver.step` → `lane.tick()` | `except (OSError, RuntimeError, TypeError, ValueError)` | `except Exception` |
| `driver.step` → `self._on_reason()` | **nothing at all** | `except Exception` |
| `driver._loop` → `self.step()` | **nothing at all** | `except Exception`, and `except BaseException` around the whole loop that ALARMS before re-raising |
| `lane._pump_locked` → `self._dispatch(event)` | **nothing at all** | `except Exception` → `_record_dispatch_failure` |

The fourth row is one nobody had named. `_on_reason` runs *outside* the `tick`
guard by design (R1.6's ordering note), and it appends and notes — so a broken
`on_event` sink or a full failure list could kill the pump through the one hook
added to make the pump observable. Seed S30.

### 3.3 Counted BY TYPE, and bounded

`driver.failure_types` / `lane.dispatch_failure_types` /
`lane.ledger_failure_types` / `memory.realtime_write_failure_types` are all
`{TypeName: count}`. §Safety-1 is a story about a type that was not on a list;
a failure log reading "pump failed: database is locked" leaves the next reader
doing the MRO walk by hand. The text logs are capped
(`FAILURE_LOG_LIMIT = 200`, `DISPATCH_FAILURE_LOG_LIMIT = 200`) while the
counts stay exact — a lane failing every frame at 20 Hz must not grow an
unbounded list inside the process the firewall is protecting (seed S29).

### 3.4 The line the firewall does not cross

`BaseException` is never caught to be swallowed. `KeyboardInterrupt` and
`SystemExit` are instructions to stop; a pump that ignored Ctrl-C would be its
own incident. `_loop`'s outermost handler catches `BaseException` **only to
alarm**, then re-raises. Seed S6 is the over-correction in the other direction
and is RED.

### 3.5 A frame that blows up is still a frame that arrived

`_pump_locked` counts `handled` before dispatch. A frame that was received,
parsed and then failed is not a frame that failed to arrive, and pretending
otherwise would make `handled` lie to the driver about whether the socket had
traffic. Dispatch failures are kept in their **own** list and never folded into
`protocol_errors`: one is the provider changing, the other is this process
breaking, and an operator watching a rising number needs to know which. Seed
S27.

---

## §4 — Item 2: the alarm

The card's sentence is "a `driver.failures` entry is not enough… Silence is the
defect." A death is therefore recorded in **five** places, and the card's
requirement is met by the first three:

1. **`driver.alive` goes False and `driver.death_reason` says why.** `alive` is
   deliberately NOT `running`. `running` folds in intent — it answers "does the
   owner's next gesture need to start a pump" — so it was already False for a
   dead pump and told nobody a thread had died. `alive` answers the operator's
   question: is there a living thread on this lane. The state only `alive` can
   see (told to stop, thread still winding down) is asserted directly in
   `test_alive_and_running_answer_different_questions`; seed S8 aliases the two
   and is RED.
2. **`heartbeat_age_s()`** — a thread can be alive and wedged inside a blocking
   call, and only the heartbeat says so. Never raises: an injected clock that
   misbehaves must not break the health question
   (`test_a_broken_clock_cannot_break_the_health_question`).
3. **A SAFETY-class runtime event.** `on_alarm` → `RobotRuntime._realtime_pump_alarm`
   → `_log_safety(kind=pump_died|pump_revived, source=realtime_pump)`. That ring
   is R21's, is never evicted by chatter, and from EV-1 is also written to the
   on-disk session evidence log. Two new kinds and one new source were added to
   the closed vocabularies (`SAFETY_LOG_PUMP_DIED`, `SAFETY_LOG_PUMP_REVIVED`,
   `SAFETY_SOURCE_REALTIME_PUMP`). No row with this source ever engages or
   releases anything — it shares the ring because it answers the same question
   the ring exists for: what is the state of the thing that stops the robot when
   I say so.
4. **Its own bounded list** (`_realtime_pump_alarms`, 32 slots) so `/api/state`
   can show the history without competing for the 24 safety slots.
5. **The event ring**, so the panel's ordinary event stream carries it too.

The message names what stopped **and what did not**:

> REALTIME PUMP DEAD: … The hosted lane is no longer being pumped: the spoken
> e-stop relay, the stall watchdog, the session rollover and the idle hang-up
> are all stopped until it restarts. The local emergency stop (panel, Space,
> typed) is unaffected.

That last clause is load-bearing. An alarm that made the owner believe the
robot could not be stopped at all would be a worse failure than the one it
reports.

### 4.1 The panel

`realtime_snapshot()["pump"]` is a flat, driver-shape-free block — `armed`,
`alive`, `running`, `heartbeat_age_s`, `deaths`, `death_reason`, `revivals`,
`revivals_exhausted`, `alarms` — so the browser can raise the alarm without
knowing what a `RealtimeDriver` is. `renderPumpAlarm` puts a
`role="alert" aria-live="assertive"` banner **inside the safety-log block**,
above the section divider, in one of three loud states (`dead`, `stale`,
`revived`) and hidden otherwise.

`armed` is the honest third state and the reason the banner is not simply
`!alive`: before the owner's first gesture there is no session to pump, and a
panel that shouted about that would be the boy who cried wolf for the first
minute of every session (seed S32).

**does_not_prove:** `ui/index.html` is executed by zero tests — the audit says
so and this card does not change that. `test_the_panel_renders_the_alarm_beside_the_safety_log`
is a **string pin** and is labelled as one in its own docstring. It pins the
wiring (the call is present AND not commented out; the render reads
`realtime.pump`, `pump.death_reason`, `pump.heartbeat_age_s`; the alarm's
element sits between the safety-log element and the next divider; the two kind
labels exist). It cannot prove a browser paints anything.

---

## §5 — Item 3: revival, bounded

```
DEFAULT_REVIVE_AFTER          3      consecutive failed steps ⇒ sick, not unlucky
DEFAULT_MAX_REVIVALS          5      restarts before the driver declares itself dead
DEFAULT_REVIVAL_BACKOFF_S     0.5    first wait
DEFAULT_REVIVAL_BACKOFF_MAX_S 8.0    cap
```

Three consecutive failed steps at 20 Hz is 150 ms in which the lane cannot
complete a single pass — a fault, not a blip. `_revive` is called from inside
the sick thread, starts the replacement, and the old thread returns one line
later, so the invariant `start()` has always defended — **one pump per lane** —
survives. Past the cap it stops trying and calls `_die` instead, because a lane
whose transport is genuinely gone fails every step and an unbounded ladder
against it is a hot loop that bills the provider while the operator is told
nothing new (seed S13, and S14 for revival being absent altogether).

An explicit `start()` is a **fresh mandate**: `revivals`, `revivals_exhausted`
and `consecutive_failures` all reset, or a driver that spent its five could
never be revived again for the life of the process and the owner's gesture
would buy one loop and no resilience. `deaths` and `death_reason` deliberately
do **not** reset — "it died at 14:02 and was restarted" is a fact an operator
needs an hour later (seed S16).

### 5.1 The supervisor

`RobotRuntime._service_health_loop` calls `driver.ensure_alive()` once per
10 s period. `_die` fires from inside the dying thread and covers every death
the process can observe from the inside; this covers the ones it cannot — a
thread the interpreter took down, an alarm hook that itself killed the thread, a
`_die` that never ran. It alarms **at most once per undetected death** (`_die`
sets `_stop`, which the next probe reads as "already told"), so polling it is
safe (seed S31). It deliberately does not restart anything: bounded revival
belongs to the driver, which knows how much budget it has spent.

**does_not_prove:** the health-loop wiring is a **source pin**
(`test_the_health_loop_probes_the_pump_and_is_quiet_when_it_is_well`), stated as
one in its docstring. Asserting it end to end would put a ten-second sleep in
the commit gate. A source pin cannot prove the loop runs; it does prove that a
refactor which drops the call reddens rather than silently removing the
supervisor.

---

## §6 — Item 4: the sqlite blindspot, killed at four sites

| # | Site | Was | Is | Seed |
| --- | --- | --- | --- | --- |
| 1 | `lane._write_ledger` | `except (RuntimeError, TypeError, ValueError)` | `except Exception`, counted by type, `last_ledger_failure` | S17 |
| 2 | `memory.write_realtime_turn` (**the primary**) | **nothing** | `except sqlite3.Error` → counted, logged, **returns 0** | S18 |
| 3 | `runtime._write_realtime_ledger` | `except (AttributeError, RuntimeError, TypeError, ValueError)` | `except Exception`, and the chat mirror moved INSIDE a guard of its own | S19 |
| 4 | `_RealtimeLedgerMirror.write_realtime_turn` | **nothing, at either half** | both halves guarded independently, both counted, `snapshot()` | S20, S21 |

Site 2 is the card's "firewalled at the source", and the design choice inside it
is the one an auditor should check hardest:

* `ValueError` for a bad speaker or empty text **still raises**. That is
  argument validation: deterministic, three call sites depend on it, and a
  caller passing garbage has a bug rather than a full disk. Seed S22 is the
  over-correction and is RED.
* `sqlite3.Error` — the whole family, caught **on the base class** rather than
  by a list of subclasses, which is the entire lesson of the finding — degrades
  to a counted note and returns row id `0`. Grep confirms no caller in this tree
  branches on the return value; it is a correlation aid. Seed S33 makes it
  return `-1` instead and is RED, because a *fake* row id is worse than an
  honest zero.

Site 4's docstring previously claimed "a failing mirror can never change what
was recorded". That was a claim about **order**, and order alone does not make
it true — a `mirror_realtime_chat` that raised propagated out of the mirror, out
of `lane._write_ledger`'s three-type catch, out of `pump()` and up the pump
thread. Losing a session's spoken e-stop over a chat pane. The claim is now
enforced rather than intended.

---

## §7 — Item 5: EV-1 §10.3, closed

EV-1 taught the codec to KEEP the payloads of the three frame types
`live_run_1` refused 95 times (44 ASR deltas, 44 buffer commits, 7 truncations)
and then had nowhere to put them, because its card scoped it to `protocol.py`
and listed `lane.py` under MUST NOT TOUCH. Its §10.3 named the fix and the trap
in the same breath: three lines in `_dispatch`, **plus a sink that is not
`_note`**, because 44 deltas a session through the 100-slot panel ring is the
exact resource EV-1 exists to stop overflowing.

Delivered exactly that way:

* `lane._dispatch` gains one `isinstance(event, RetainedEvent)` branch → `_retain`;
* `_retain` counts by type and calls the injected `retention_sink`, swallowing
  and counting any failure (evidence never kills a conversation);
* `runtime._retain_realtime_frame` is that sink and calls `_offer_evidence(STREAM_EVENT, …)`
  — non-blocking, drops rather than waits, no-op when the log is not armed;
* `retention_sink=None` keeps the pre-R22 behaviour byte-for-byte (frames
  parsed, counted, dropped) — pinned by
  `test_an_unwired_lane_is_byte_identical_to_the_pre_r22_behaviour`.

It remains a **no-op for the conversation**: nothing here marks activity, arms a
turn, touches the sink or writes the ledger
(`test_a_retained_frame_changes_nothing_about_the_conversation`).

`test_the_runtime_retention_sink_writes_evidence_and_not_panel_events` drives
EV-1's own number — 44 — and asserts the panel ring grew by **zero**.

---

## §8 — What went against me

### 8.1 An existing lane test's assertion had to move — DEVIATION

`tests/test_realtime_lane.py::test_the_lane_refuses_to_enqueue_while_a_duplex_output_is_live`
asserted the sink-ownership law by catching `SinkOwnershipError` **out of
`pump()`**. The dispatch firewall stops that escape, so the test failed.

I did not weaken it. The law is still a raise and is still asserted as one —
directly, via `lane.assert_sink_free()`. What moved is where the *pump-level*
refusal is observed, and the escape was never the guarantee: it was the
§Safety-1 defect wearing a useful hat. `runtime.py`'s own R7 note records three
`pump failed: … DuplexVoiceSession output is live` lines in live session 1 from
exactly this path — that exception reaching the driver is the incident, not the
proof. The rewritten test now asserts **more**: nothing was enqueued, no
`begin_utterance`, the refusal is counted and typed on the lane, it is NOT
laundered into `protocol_errors`, a note was written, and the session is still
active afterwards. Seed **S27** reddens it if the laundering is reintroduced.

An auditor who disagrees should look at `git diff tests/test_realtime_lane.py`
— it is the only existing test assertion this card moved.

### 8.2 Two seeds came back GREEN, and both found real holes in my tests

Sweep 1: **S12** (`renderPumpAlarm` call commented out) and **S35**
(`safetyKindLabel` stops consulting its own table) both passed their targets.

Both were my fault, and both are the same mistake — the one EV-1's §6.2 hit
too. `assert "renderPumpAlarm(snapshot.realtime);" in panel` is satisfied by
`// renderPumpAlarm(snapshot.realtime);`, which renders nothing. And
`assert "safetyKindLabel(item.kind)" in panel` says nothing about whether
`safetyKindLabel` consults `SAFETY_KIND_LABELS`. The panel test now checks that
**every** line mentioning the call is a live call, and pins the table lookup and
both label strings. Both seeds are RED in the final sweep.

This is what seeds are for, and it is worth recording that a string-pin test on
an untested 2,600-line HTML file is exactly where this class of hole hides.

### 8.3 Two seeds came back BROKEN on a canary quoting bug

S1 and S2's canaries embedded a newline as `\n` inside a `python -c` string that
the shell had already unescaped, producing `SyntaxError: unterminated string
literal`. The harness did exactly what it should: reported **BROKEN, not RED**,
because a canary that cannot see the mutation cannot certify anything. Rewritten
with `chr(10)`; both RED in the final sweep. Reported rather than renumbered.

### 8.4 One incidental defect found and fixed

`RealtimeDriver.start()` ended `self._note(f"… at {1.0 / self._interval_s:.0f} Hz")`
with no guard. `interval_s=0.0` is a legal, documented, constructor-clamped
value meaning "never sleep", and it raised `ZeroDivisionError` out of `start()`
**after the thread was already running** — the owner's gesture would have seen a
traceback while a pump it could not see was turning. Found by this card's own
test, fixed in place because a start path that can raise is the same class of
defect. Declared here because it is outside the card's six work items.

### 8.5 A pre-existing double-write, observed and NOT fixed

The live run shows the same owner sentence ledgered twice for a panel text turn
(`lane.send_text` → `_write_ledger`, and `submit_realtime_transcript` →
`_write_realtime_ledger`). This predates R22 and is untouched by it. It is
recorded in §10 as an open risk rather than fixed inside a safety card.

---

## §9 — Live proof

**The owner's stack was not running.** `ss -ltnp` showed nothing on 8765 or
anywhere in 87xx/88xx, checked before the first session and again before the
closing gate. Nothing of theirs was started, stopped, POSTed to or restarted,
and no read-only GET was needed because there was nothing to GET.
`~/.config/parcel/realtime.yaml` was never opened (mtime unchanged at
`2026-08-20 01:28:24`, before this session). Every scenario used its own scratch
`realtime.yaml` and a scratch `robot.yaml` with `memory.path` redirected into
the scratchpad, so the owner's `parcel_memory.sqlite3` is **byte-identical
before and after**:
`44e50c9f6d34c054639b409947ba9a2ec297e6924c9af76fda4d823ad64aa29f`, checked at
the start and again after the final seed sweep. The credential was sourced with
`set -a; . ~/.config/parcel/realtime.env; set +a` for scenario C only, and never
printed, asserted against or written anywhere.

Script `<scratchpad>/r22/live_r22.py`; reports `<scratchpad>/r22/live/report_*.json`.

**The store failure is not a monkeypatch.** The ledger is a real sqlite file;
mid-session its permissions and its directory's permissions are revoked, and the
**engine** raises. Confirmed in-band in every scenario:

```
engine_says: "OperationalError: attempt to write a readonly database"
```

### 9.1 Scenario A — the incident, reproduced and survived · $0.00

One real `RobotRuntime`, real driver thread, real lane, real transport, fake
server (no provider). Two complete replies on one session — one before the
break, one after.

**Which thread wrote what.** This is what makes the proof about §Safety-1 and
not merely about sqlite:

```
"write_attempts_by_thread": [
  {"speaker": "owner", "thread": "MainThread",             "row_id": 1},
  {"speaker": "robot", "thread": "parcel-realtime-driver", "row_id": 2},   <- healthy
  {"speaker": "owner", "thread": "MainThread",             "row_id": 0},
  {"speaker": "robot", "thread": "parcel-realtime-driver", "row_id": 0},   <- store broken
  {"speaker": "owner", "thread": "MainThread",             "row_id": 0}
]
"robot_row_written_before_break": true
"robot_row_lost_on_pump_thread":  true
```

The fourth line is the incident. A robot-side ledger write, on the pump thread,
against a read-only database. Before R22 that raised `sqlite3.OperationalError`
out of `_dispatch`, out of `pump()`, out of `_loop`, and the thread was gone for
the rest of the session.

```
(a) THE PUMP SURVIVES
    pump_alive               true
    pump_deaths              0
    pump_steps_at_failure    3
    pump_steps_after         12          <- still stepping, not merely un-dead
    heartbeat_age_s          0.048

(b) THE FAILURE IS RECORDED, NOT SWALLOWED
    memory_write_failures        2
    memory_write_failure_types   {"OperationalError": 2}
    memory_last_error            "OperationalError: attempt to write a readonly database"

(c) A SPOKEN "DIE STOP" STILL LATCHES AFTERWARDS
    spoken_stop_kind          "emergency"
    spoken_stop_executed      true
    emergency_stopped         true
    arbiter_latched           true
    safety_log_latched_rows   [{"kind": "latched", "source": "voice", "phrase": "Die stop."}]
```

**Read this honestly:** `ledger_failures_lane` and `ledger_failures_runtime` are
**0**, and that is the design working, not the guard missing. The
memory-level firewall (site 2) absorbs the engine error at the source and
returns `0`, so the lane's and runtime's guards — the second and third lines of
defence — never see an exception. Each of them is proven independently by seeds
S17/S19/S20/S21 and by
`test_the_runtime_ledger_writer_and_its_chat_mirror_are_both_firewalled`, which
breaks them one at a time.

The `spend_usd: 0.002792` in report A is the lane's estimator applied to the
**fake server's** usage rows. **Real cost of scenario A: $0.00.**

### 9.2 Scenario B — the alarm, and bounded revival · $0.00

A lane whose `pump()` raises `sqlite3.OperationalError("database is locked")` on
every call, the way a wedged transport would. Backoffs shortened to 0.02/0.08 s
so the ladder runs inside a test window; ratios unchanged.

```
revivals             5              revival_waits  [0.02, 0.04, 0.08, 0.08, 0.08]
revivals_exhausted   true           failure_count  18   {"OperationalError": 18}
pump_alive           false
pump_death_reason    "revival exhausted after 5 attempt(s); the last was
                      3 consecutive failed steps (OperationalErrorx18)"
```

Six safety rows, in order — five `pump_revived` (level `warning`) and then one
`pump_died` (level `error`), all `source: realtime_pump`:

```
realtime pump revival 1/5 after 3 consecutive failed steps (OperationalErrorx3); restarting the loop in 0.02s
realtime pump revival 2/5 after 3 consecutive failed steps (OperationalErrorx6); restarting the loop in 0.04s
realtime pump revival 3/5 after 3 consecutive failed steps (OperationalErrorx9); restarting the loop in 0.08s
realtime pump revival 4/5 after 3 consecutive failed steps (OperationalErrorx12); restarting the loop in 0.08s
realtime pump revival 5/5 after 3 consecutive failed steps (OperationalErrorx15); restarting the loop in 0.08s
REALTIME PUMP DEAD: revival exhausted after 5 attempt(s); the last was 3 consecutive failed steps
(OperationalErrorx18). The hosted lane is no longer being pumped: the spoken e-stop relay, the stall
watchdog, the session rollover and the idle hang-up are all stopped until it restarts. The local
emergency stop (panel, Space, typed) is unaffected.
```

The panel block the browser reads:

```
"panel_pump_block": {"armed": true, "alive": false, "running": false,
                     "heartbeat_age_s": 0.245, "deaths": 1,
                     "death_reason": "revival exhausted after 5 attempt(s); …",
                     "revivals": 5, "revivals_exhausted": true}
"panel_alarm_rows": 6
"event_ring_says_dead": ["REALTIME PUMP DEAD: …"]
```

And it is restartable by the ordinary gesture path with a fresh budget:
`restartable: true`, `revival_budget_after_restart: 0`.

### 9.3 Scenario C — the same incident against the REAL hosted provider · $0.012512

A real hosted realtime session (`sess_EFDeKSRbxnDJ3Vh9Axeov`), a real reply, then
the same real read-only-store break, then a spoken stop.

```
rows_before_break   [["owner", "Hello. Please answer in one short sentence."],
                     ["robot", "Hi—I'm right here beside you, ready to keep you company."]]
engine_says         "OperationalError: attempt to write a readonly database"
memory_write_failures 2
pump_alive          true      pump_deaths       0
pump_steps_before   28        pump_steps_after  645     pump_still_stepping true
lane_active         true      dispatch_failures 0       protocol_errors []
spoken_stop_kind    "emergency"
emergency_stopped   true      arbiter_latched   true
safety_log_kinds    ["latched"]
usage_rows          2         spend_usd         0.012512   (rates_are_assumed)
```

617 pump steps across a real store failure on a real provider session, and the
spoken stop still latched. `protocol_errors: []` is worth noting on its own: the
95 refusals `live_run_1` recorded are gone from a clean text session because
EV-1 typed them and R22 consumes them.

### 9.4 Scenario D — the retention handoff, to a real file on disk · $0.00

95 frames — the exact three types and payload shapes `live_run_1` refused, 44 +
44 + 7 — pushed over a real transport into a real lane whose retention sink is a
real `SessionEventLog` writing to a scratch directory.

```
frames_sent            95     frames_handled          95
protocol_errors         0     dispatch_failures        0
retained_events        95     retention_failures       0
retained_event_types   {"conversation.item.input_audio_transcription.delta": 44,
                        "input_audio_buffer.committed": 44,
                        "conversation.item.truncated": 7}
panel_ring_grew_by      0     <- EV-1 §10.3's whole point
evidence_rows_total   102     evidence_retained_rows  95
evidence_verify_problems  []  (verify_event_log clean: no gaps, no reorder)
die_stop_delta_on_disk  true
```

One row off the file, verbatim:

```json
{"seq": 27, "stream": "event", "wall": "2026-08-21T07:09:40.055670+00:00",
 "kind": "retained_event",
 "type": "conversation.item.input_audio_transcription.delta",
 "fields": {"item_id": "item_owner_21", "delta": "die stop", "content_index": 0},
 "session_id": "rt_c2cb58119c50", "timestamp": "2026-08-21T07:09:40.055668+00:00"}
```

That row is the artefact `live_run_1` could not produce: the ASR fragment an
emergency phrase was assembled from, joined to its item id, on disk, uncapped.

**does_not_prove (§7.4):** these 95 frames were **synthesized to EV-1's recorded
shapes and injected at the transport**, not received from the provider. Scenario
C, the only real-provider run, retained **zero** frames — all three retained
types are audio-path frames and text mode produces none. Proving this end to end
against the provider needs `mode: audio`, the browser gateway and a real
microphone, which this card had no way to drive. **The retention handoff has no
real-provider evidence.** It is offline-proven, disk-proven, and seed-proven
(S23–S26), and that is all.

### 9.5 Cost

| Scenario | Provider | Real spend |
| --- | --- | --- |
| A | none (fake server) | $0.00 |
| B | none | $0.00 |
| C | **real hosted session, 2 turns** | **$0.012512** (rates_are_assumed) |
| D | none | $0.00 |
| **Total** | | **$0.012512** |

Well under the $1 ceiling. The `rates_are_assumed` caveat is the ledger's own
and this card does not lift it.

---

## §10 — Seeds — 36, all RED

Harness `<scratchpad>/r22/seed_r22.py`; final sweep
`<scratchpad>/r22/seeds_final.txt` + `seeds.json`; sweep 1
`<scratchpad>/r22/seeds_sweep1.txt`.

R9 session-B protocol: ONE GOLD snapshot of all five touchable files at startup;
per seed — repair drift from GOLD, mutate exactly one file, **purge every
`__pycache__` under `src/`, `tests/`, `scripts/` and `evals/`**, run a
**fresh-interpreter canary that must SEE the mutation on disk** (a seed whose
canary fails is BROKEN, never RED — a stale `.pyc` from a mutated source passes
byte-identity checks and has poisoned a live run before), run the named pytest
target, restore from GOLD in a `finally`, purge again, assert byte-identical.
The harness asserts at import time that every mutable path is under
`src/parcel_robot/`. **No test, config, eval or fixture file was ever mutated.**

GOLD (sha256, first 16) — these are also the bytes the closing gate scored:

```
75a7674126fea88d  src/parcel_robot/realtime/driver.py
c2b538d66e719b92  src/parcel_robot/realtime/lane.py
c53253e3d4398599  src/parcel_robot/runtime.py
ff0b7f263faf963f  src/parcel_robot/memory.py
3f1743bcb3368104  src/parcel_robot/ui/index.html
```

All targets are in `tests/test_realtime_pump_survival.py` except S27, which is
in `tests/test_realtime_lane.py`.

| # | Seeded defect | File | Target test | Result |
| --- | --- | --- | --- | --- |
| S1 | driver pump: the four-type catch list is back | driver | `test_a_step_survives_every_exception_outside_the_old_catch_list` | **RED** ¹ |
| S2 | driver tick: the four-type catch list is back | driver | same | **RED** ¹ |
| S3 | driver instruction refresh: narrow catch list is back | driver | `test_a_step_survives_a_raising_instruction_source_of_any_type` | **RED** |
| S4 | the loop's own guard is removed: `step()` escapes the thread | driver | `test_the_loop_survives_a_step_that_explodes_in_its_own_scaffolding` | **RED** |
| S5 | lane dispatch is bare again: `sqlite3.Error` leaves `pump()` | lane | `test_a_dispatch_that_blows_up_is_counted_and_never_leaves_the_pump` | **RED** |
| S6 | over-correction: `step()` swallows `BaseException` too | driver | `test_a_base_exception_is_never_swallowed` | **RED** |
| S7 | the death alarm is removed: a dead pump is silent again | driver | `test_a_dead_pump_is_alive_false_and_says_why` | **RED** |
| S8 | `alive` is aliased to `running`: the incident state vanishes | driver | `test_alive_and_running_answer_different_questions` | **RED** |
| S9 | the heartbeat stops ageing: a wedged pump looks fresh | driver | `test_the_heartbeat_ages_and_reaches_the_snapshot` | **RED** |
| S10 | the alarm never reaches the safety ring | runtime | `test_the_pump_alarm_reaches_the_safety_ring_and_the_snapshot` | **RED** |
| S11 | the driver's alarm hook is never wired at construction | runtime | same | **RED** |
| S12 | the panel stops rendering the alarm beside the safety log | index.html | `test_the_panel_renders_the_alarm_beside_the_safety_log` | **RED** ² |
| S13 | revival is UNBOUNDED: it never gives up and never alarms | driver | `test_revival_is_BOUNDED_and_the_last_word_is_a_death` | **RED** |
| S14 | revival is ABSENT: repeated failures just end the loop | driver | `test_a_pump_that_keeps_failing_really_does_hand_off_to_a_new_thread` | **RED** |
| S15 | the revival backoff ladder is flattened to zero | driver | `test_the_revival_ladder_is_exponential_capped_and_counted` | **RED** |
| S16 | a restart does NOT restore the revival budget | driver | `test_a_fresh_start_is_a_fresh_revival_budget_but_keeps_the_record` | **RED** |
| S17 | `lane._write_ledger`: the three-type catch list is back | lane | `test_the_lane_ledger_write_degrades_to_a_counted_note` | **RED** |
| S18 | `memory.write_realtime_turn`: the primary write is bare again | memory | `test_the_memory_write_path_firewalls_the_engine_but_not_bad_arguments` | **RED** |
| S19 | `runtime._write_realtime_ledger`: the four-type list is back | runtime | `test_the_runtime_ledger_writer_and_its_chat_mirror_are_both_firewalled` | **RED** |
| S20 | `_RealtimeLedgerMirror`: the ledger half is unguarded again | runtime | same | **RED** |
| S21 | `_RealtimeLedgerMirror`: the chat-mirror half is unguarded | runtime | same | **RED** |
| S22 | over-correction: bad arguments are swallowed too | memory | `test_the_memory_write_path_firewalls_the_engine_but_not_bad_arguments` | **RED** |
| S23 | retention routed through `_note`: the 100-slot ring floods | lane | `test_retained_frames_reach_the_evidence_sink_and_never_the_note_ring` | **RED** |
| S24 | the `RetainedEvent` branch is removed: EV-1's hole reopens | lane | same | **RED** |
| S25 | the runtime wires retention to the panel ring, not the log | runtime | `test_the_runtime_retention_sink_writes_evidence_and_not_panel_events` | **RED** |
| S26 | a broken retention sink raises into the pump again | lane | `test_a_broken_retention_sink_costs_a_counter_and_not_a_turn` | **RED** |
| S27 | a dispatch failure is laundered into `protocol_errors` | lane | `test_the_lane_refuses_to_enqueue_while_a_duplex_output_is_live` | **RED** |
| S28 | failures stop being counted by exception TYPE | driver | `test_a_step_survives_every_exception_outside_the_old_catch_list` | **RED** |
| S29 | the failure log grows without bound inside the pump | driver | `test_the_failure_log_is_bounded_but_the_counts_are_exact` | **RED** |
| S30 | the reason handler is unguarded again (the fourth call) | driver | `test_a_step_survives_a_raising_reason_handler` | **RED** |
| S31 | the health probe alarms on EVERY poll, not once per death | driver | `test_ensure_alive_names_a_death_nobody_reported` | **RED** |
| S32 | an UNARMED pump is reported as an alarm (cries wolf) | runtime | `test_an_unarmed_pump_is_not_an_alarm` | **RED** |
| S33 | a failed write returns a fake row id instead of 0 | memory | `test_the_memory_write_path_firewalls_the_engine_but_not_bad_arguments` | **RED** |
| S34 | the health loop stops probing the pump entirely | runtime | `test_the_health_loop_probes_the_pump_and_is_quiet_when_it_is_well` | **RED** |
| S35 | the panel renders raw wire values ("Pump_died") again | index.html | `test_the_panel_renders_the_alarm_beside_the_safety_log` | **RED** ² |
| S36 | the docstring's "keeps going" claim is false again | driver | `test_the_driver_docstring_states_what_it_actually_does` | **RED** |

`final whole-tree check: 0 file(s) needed a final repair` — all five files
byte-identical to GOLD at teardown, and GOLD is the state the closing gate
scored.

¹ BROKEN on sweep 1 (canary quoting bug, §8.3); re-written and RED.
² GREEN on sweep 1; both found real holes in my own tests (§8.2).

**The card names eight seed classes by hand and all eight are here:** each
restored narrow catch-list → **S1, S2, S3, S17, S19** (plus S4, S5, S20, S21,
S30 for the sites that had *no* catch at all); alarm removed → **S7** (with S10,
S11, S12 for the three other ways it could go silent); revival unbounded →
**S13**; revival absent → **S14**; ledger guard removed at each of the four
sites → **S17, S18, S19, S20+S21**; retention routed through `_note` → **S23**.

---

## §11 — does_not_prove

1. **The retention handoff has no real-provider evidence** (§9.4). Text mode
   produces zero ASR frames; scenario C retained zero. The 95 frames in scenario
   D were synthesized to EV-1's recorded shapes and injected at the transport.
2. **`ui/index.html` is still executed by zero tests.** The panel work is
   proven by string pins, labelled as such in the test's own docstring, plus
   two seeds. No browser rendered anything in this card.
3. **The health-loop wiring is a source pin** (§5.1), not an end-to-end proof
   that the ten-second loop calls it in a running process.
4. **`ensure_alive()` closes a window it cannot demonstrate in production.** The
   offline test constructs a genuinely dead thread by hand. No real thread was
   killed out from under the driver.
5. **`_die` under interpreter shutdown is untested.** `_alarm` is guarded, but a
   `KeyboardInterrupt` arriving during teardown is a path no test drives.
6. **The revival hand-off has a small check-then-start race.** `_revive` tests
   `_stop.is_set()` and then starts a thread; a `stop()` landing between those
   two lines leaves a daemon thread that exits at the top of its first loop
   iteration. Bounded, harmless, daemon — and stated rather than hidden.
7. **No claim is made about actuation.** As the audit records for the whole
   tree, nothing here reaches a real joint; the spoken-stop proofs are latch
   records (`arbiter.emergency_stopped`, `agent.safety.emergency_stopped`) and
   dispatch records.
8. **The `spend_usd` figures carry the ledger's own `rates_are_assumed`.**
   Scenario A's `0.002792` is a fake-server artefact and is $0.00 in reality
   (§9.1).

---

## §12 — Open risks and owner-gated

1. **A panel text turn ledgers the owner sentence twice** — once through
   `lane.send_text` → `_write_ledger`, once through `submit_realtime_transcript`
   → `_write_realtime_ledger` (§8.5). Pre-existing, visible in this card's live
   report, deliberately not fixed inside a safety card. Wants a small card of
   its own; the fix is a decision about which path owns the owner row, not a
   patch.
2. **`REALTIME_PUMP_ALARM_MAX = 32` and `SAFETY_LOG_MAX = 24` are now sharing a
   ring with a new writer.** A pump that dies and is restarted repeatedly across
   one long session can occupy safety slots that latches would otherwise hold.
   Bounded (at most `max_revivals + 1` rows per `start()`), but it is a new
   pressure on R21's ring and an owner may want the pump rows in a ring of their
   own.
3. **`DEFAULT_MAX_REVIVALS = 5` and `DEFAULT_REVIVE_AFTER = 3` are engineering
   judgements, not measurements.** Nothing in the field has yet produced a
   repeated-failure pump, so the ladder's shape is derived from the lane's
   reconnect ladder rather than from data. Owner-gated: if a real degraded
   session ever runs, these are the two numbers to re-derive.
4. **The evidence log now carries `retained_event` rows** — 95 per busy audio
   session on top of what EV-1 already writes. EV-1's own §10.6 already flags
   that nothing prunes `recordings/`; this makes that a little more urgent. Still
   an owner policy decision, not a default this card should pick.
5. **`memory.write_realtime_turn` returning `0`** is a silent-degradation
   contract. No caller in this tree branches on it today; a future caller that
   does must read the counters. Documented in the method's own docstring, seeded
   at S33, and named here so it cannot be discovered by surprise.
6. **The audit's other Safety findings are untouched by this card.** The
   `robot.yaml` NaN velocity clamp (PARTIAL), the panel-origin latch that does
   not reach `SafetySupervisor`, and the typed "Stop." punctuation gap all
   remain open and are not R22's.

---

## §13 — Artefacts

| Path | What |
| --- | --- |
| `<scratchpad>/r22/seed_r22.py` | the 36-seed harness |
| `<scratchpad>/r22/seeds_final.txt`, `seeds.json` | the final sweep, 36/36 RED |
| `<scratchpad>/r22/seeds_sweep1.txt` | sweep 1, with the 2 BROKEN and 2 GREEN (§8.2, §8.3) |
| `<scratchpad>/r22/gold/` | the GOLD snapshot the sweep restored from |
| `<scratchpad>/r22/gate_1.txt` | the gate output pasted in §2 |
| `<scratchpad>/r22/live_r22.py` | the four live scenarios |
| `<scratchpad>/r22/live/report_a.json`, `report_b.json`, `report_c.json`, `report_d.json` | their reports |
| `<scratchpad>/r22/live/evidence_d/<session>/events.jsonl` | 102 rows, 95 of them retained ASR/boundary frames |

`<scratchpad>` is
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`.
**These paths are session-scoped and will evaporate** — the audit's own Ops
finding about status docs citing `/tmp` applies to this document too. Everything
load-bearing has been quoted inline above for exactly that reason.


## Audit correction — Fable, 2026-08-21

§13's artifact table attributes the §2 gate paste to `gate_1.txt`; the paste's timestamp (07:25:16Z) matches `gate_final.txt`. Label corrected by the auditor; the gate result itself was independently reproduced green.
