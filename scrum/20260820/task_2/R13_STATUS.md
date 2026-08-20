# R13 task_2 — the pace watcher never goes silent — EXECUTOR STATUS

**Date:** 2026-08-20 · **Card:** `scrum/20260820/task_2/README.md` ·
**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Reads first (all read in full):** `scrum/20260819/task_4/AUDIT_R11_FABLE.md`
(carry-forward), `scrum/20260819/task_5/E1_STATUS.md` (`run-with-me-flex`),
`src/parcel_robot/realtime/whisperer.py::_pace_watch`.

> **Document discipline.** Written INCREMENTALLY, section by section, as each
> piece finished — the R8 lesson (an executor finished its code and died before
> writing anything down). Sections appear in the order they were completed.

---

## §0 — What the three required reads changed before any code was written

**AUDIT_R11 carry-forward** names the defect and pins the fix's shape: *"the
fix must also pin 'every tick writes a row or a counted skip'"*. It also
records that the Ministral seam stays EMPTY — E1's only whisperer miss was
this implementation bug, not a class-rule gap — so nothing here goes near a
model.

**E1 §3 Finding 2 + `scenario_run-with-me-flex/verdict.md`** supply the
measurements this card is answerable to, and two of them changed the plan:

1. **The recorded failure was total, not partial.** 24 decision rows in the
   58.8 s window, all `never_band`, and **zero `owner_pace_change` rows** —
   the differ emits that class on *any* speed-band change including
   `None → value`, so zero of them means `owner_speed_mps` was `None` for the
   entire window, not for a patch of it. The offline probe measured a
   continuous **10 s** dropout across the run→walk transition. So a fix that
   only handles brief flickers would not have fixed the recorded run.
2. **The mechanism is intermittent, not broken.** Two control re-runs of the
   same setup fired `pace_mismatch_sustained` correctly. That is why the fix
   is a *state* (`pace_unknown`) rather than a rewrite of the watcher: the
   sustained-window machine was right, its input was not, and the input's
   absence was invisible.

**`_pace_watch` as it stood** gates on `digest.owner_speed_mps is not None`
inside a single `mismatched` boolean and returns `()` — no row, no counter, no
event — for every state that is not "measurably walking". That single boolean
conflated *"the owner is running"* with *"nobody can tell what the owner is
doing"*, which is the defect in one line.

### What this changed about the plan

* The window must **pause**, not reset (the card says so, and E1's shape
  demands it: a 10 s hole starting exactly at the transition means a resetting
  window can only ever start counting after the hole).
* `pace_unknown` needed a **skip-reason vocabulary**, not just one counter:
  "the watcher wrote nothing" has six other legitimate causes, and a fix that
  cannot tell them apart has moved the blind spot rather than closed it.
* The digest should carry the follow controller's **own word** for the track
  (`heading_track_status`), because E1's second question — *why* does the
  estimator drop out for ten seconds — is a separate investigation that will
  need this data, and it costs one read-only key.

### Scope decisions taken before writing code

* **E1 defect 3 (`follow_snapshot["distance_m"]` reads a key that does not
  exist) was left alone.** It sits three lines from my edit in the same method
  and it is not this card: it is `follow_tick`, not pace, it is filed as its
  own defect with its own seed requirement, and no card today owns it. Named in
  §8 so it is not lost.
* **Nothing in `navigation/follow.py` was touched.** The estimator's dropout is
  E1's separate investigation, and the card forbids moving follow safety caps.
  The digest READS `follow.snapshot()`; R11 seed S21 attacks that direction and
  is re-run here.

---

## §1 — What changed, and why each piece is there

Two source files. `src/parcel_robot/realtime/whisperer.py` (the policy) and
`src/parcel_robot/runtime.py` (three lines of pace wiring, read-only).

### 1.1 `None` is a state, with a name

`KIND_PACE_UNKNOWN = "pace_unknown"`, banded into the **never band**. Banded
rather than left undeclared for two reasons: `band_of` stays total (an
undeclared class fails closed and would log `unknown_kind_fails_closed`, which
would be a lie about what happened), and forwarding it would be the exact
chattiness this module exists to prevent — a flaky estimator would have the
robot narrating its own instrumentation once per hole.

Two rules write it:

| Rule | When | What it answers |
| --- | --- | --- |
| `pace_unknown` | the hole opens | "the dog went quiet here, and this is why" |
| `pace_known_resumed` | the measurement returns | "and it could see again here" |

One row per hole, not one per tick — the decision ring is 400 rows and a walk
is longer than that. The pair bounds the blind interval, so *how long was it
blind* is a subtraction on two `at_s` values rather than an inference.

The row's dedup key carries the estimator's own status:
`pace_unknown:insufficient_motion`. That word is the follow controller's, and
the code says plainly that it is a **hint and not a cause** — the estimate is
also `None` when too few updates have accumulated or the last good one went
stale, and the status reads `updated` through both.

### 1.2 The window pauses instead of resetting

`_pace_mismatch_banked_s` accumulates measured mismatch seconds; the hole banks
what has accrued and stops the clock. Read the window now as **"six seconds of
MEASURED walking inside one follow episode, contiguous or not"**:

* blind time banks **nothing** on its own (a minute of unmeasurable owner buys
  zero seconds — pinned by test);
* a measurably running owner still empties the bank and re-arms the latch;
* a follow that ends clears everything, and deliberately does **not** write a
  `pace_known_resumed` row: a subject that walked away is not a measurement
  that recovered.

**This is a behaviour change with a consequence, stated plainly.** An owner who
stops dead is *unmeasurable* to this estimator, not "measured at 0.0 m/s". So a
long standstill mid-follow no longer resets the window, and the ask can arrive
after a shorter final leg of walking than six seconds. The total measured
mismatch is still ≥ 6 s, which is the property R11's window was defending. It
is a trade the card asks for explicitly; §8 risk 2 records it as a trade rather
than as a free win.

### 1.3 Every tick is accounted for

`pace_watch_ticks == pace_watch_logged + sum(pace_watch_skips.values())`, with
seven named reasons (`PACE_SKIP_REASONS`): `session_baseline`,
`not_following`, `no_run_intent`, `owner_running`, `pace_unknown_holding`,
`window_accumulating`, `already_asked`.

The accounting is **structural, not bolted on**: the tick counter lives inside
`_pace_skip` / `_pace_logged`, and every exit from `_pace_watch` goes through
one of them. A future branch that forgets to account for itself does not
increment `ticks` either, so the identity holds instead of drifting quietly —
which is the failure mode this whole card is about.

Counters rather than rows because the ring evicts and a counter does not: the
owner-session capture (§4) had aggregates, one `last` row, and no way to answer
the question. `snapshot()` now publishes `pace_watch` — including `accounted`,
the identity itself — so `/api/state` and every future eval pack carry it.

### 1.4 The item refuses to be composed without a measurement

`_pace_mismatch_fact` rendered `None` as *"below a walking pace… which is a
walk"* — a measurement claim about an owner nobody could measure, in the one
item whose entire job is not overstating what the robot knows. It was
unreachable then and is a `WhispererError` now, so it cannot become reachable
by accident.

### 1.5 `STATE_DIGEST_VERSION` 1 → 2

`StateDigest` gained `owner_speed_status`. The constant's own contract is
"bumped whenever the field set changes meaning", and the reason it exists is
live here: `evals/20260819/run_1` and `evals/20260820/owner_session_1` both
hold logs recorded under schema 1, and a reader that finds `owner_speed_status`
missing must know it is reading an older schema rather than conclude the follow
controller said nothing. No recorded artifact was rewritten.

### 1.6 `runtime.py` — three lines, all reads

`_whisperer_digest` now also reads `follow_snapshot["heading_track_status"]`
and puts it in the digest. Nothing here writes a controller parameter; the
method's existing contract ("READS ONLY") is unchanged and R11 seed S21 still
attacks it from the other side.

---

## §2 — Seeds: 14/14 RED, 14/14 restored byte-identical

Harness `<scratchpad>/r13/r13_seeds.py`, results `<scratchpad>/r13/seeds.json`.
FIX-A discipline with the **R9 session-B** hardening: every touched file is
snapshotted ONCE into GOLD at startup, repaired from GOLD before each seed if it
has drifted, restored from GOLD (never from "whatever was there") in `finally`,
and re-verified against GOLD at teardown. The harness asserts at runtime that
every mutated path is under `src/parcel_robot/`; **no test, config or eval was
mutated at any point.**

| # | Seed | Mutated file | Target | Result |
| --- | --- | --- | --- | --- |
| S1 | **THE E1 HOLE RESTORED** — an unmeasurable owner is silently treated as "still running" and writes no row | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S2 | the same hole, seen from the REAL runtime and the REAL estimator | `realtime/whisperer.py` | `test_runtime_whisperer_wiring.py` | **RED** |
| S3 | **THE INVARIANT BROKEN** — a blind tick is neither logged nor counted | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S4 | the invariant broken from the other side — a tick that WRITES is not counted as a tick | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S5 | the ledger stops reaching `/api/state` (the owner-session blind spot reopened at the panel) | `realtime/whisperer.py` | `test_runtime_whisperer_wiring.py` | **RED** |
| S6 | the window RESETS across a hole instead of pausing | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S7 | the bank is kept but ignored at the decision point | `realtime/whisperer.py` | `test_runtime_whisperer_wiring.py` | **RED** |
| S8 | **OVER-CORRECTION** — the clock is not stopped, so blind seconds count as walking seconds | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S9 | the blind row stops naming the estimator's own track status | `realtime/whisperer.py` | `test_runtime_whisperer_wiring.py` | **RED** |
| S10 | the RUNTIME stops carrying the track status into the digest | `runtime.py` | `test_runtime_whisperer_wiring.py` | **RED** |
| S11 | the hole closes without a row, so its length is unreadable from the log | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S12 | a follow that ENDS mid-hole leaves the hole open forever | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S13 | the item guesses again: an unmeasurable owner is called "below a walking pace" | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |
| S14 | `pace_unknown` loses its band and could reach the model | `realtime/whisperer.py` | `test_realtime_whisperer.py` | **RED** |

Teardown: `0 file(s) needed a final repair`, both files `matches_gold=True`
(`whisperer.py 6930b1441812bd5f`, `runtime.py 6956a50970eb51e1`, sha256 first
16).

### One seed came back GREEN first, and the TEST was strengthened

**S11** (the closing row is dropped) was GREEN on the first pass, and the reason
is worth recording because it is a fact about this module, not a typo: the
mutation removed the row from the tuple `_pace_watch` RETURNS, but `_record`
had already appended it to the ring, so the decision log looked identical. My
test read the log and saw two rows.

That is a real hole in the test, not just in the seed. The returned tuple is
what the runtime iterates — it is how a forward reaches the lane and how a
refused narration gets undelivered — so a row the watcher records and keeps to
itself is invisible to every consumer except an eval pack reading the ring
afterwards. `test_the_blind_interval_is_a_length_the_log_can_be_read_for` now
asserts on **both** the log and the returned tuples. Re-run: **S11 RED.** The
seed was kept.

### R11's pace-family seeds, re-run against R13's code

The card protects the follow safety caps explicitly, so the seeds that guard
them were re-run from R11's own harness (`<scratchpad>/r11/r11_seeds.py`)
against this tree — not re-implemented, the originals:

| R11 seed | What it attacks | Result against R13 |
| --- | --- | --- |
| S16 | the ask-hint is dropped from `pace_mismatch` | **RED** |
| S18 | the honesty guard (current-gait line) is removed | **RED** |
| S19 | the honesty guard is removed on the REAL stack (runtime digest) | **RED** |
| S20 | the watcher fires on a single sample instead of a sustained window | **RED** |
| S21 | **the pace watcher RAISES a follow speed cap** | **RED** |
| S35 | a follow that ended keeps its pace declaration | **RED** |

6/6 still RED, all restored. R13 did not weaken any of R11's pace protections.

---

## §3 — The live proof: E1's `run-with-me-flex`, with the dropout in it

Script `<scratchpad>/r13/r13_live_proof.py`; report
`<scratchpad>/r13/r13_live_report_20260820T153625Z.json`. **Own stack
throughout.** Own sim process on its own socket, `configs/robot.yaml` COPIED to
`<scratchpad>/livework/robot_r13_<STAMP>.yaml` with **only** `memory.path`
changed to a scratch sqlite (R5 deviation 6); the owner's
`parcel_memory.sqlite3` was never opened and `~/.config/parcel/realtime.yaml`
was never read — `PARCEL_REALTIME_CONFIG` pointed at a scratch yaml carrying the
shipped knob values verbatim (`max_updates_per_minute: 2`, `min_gap_s: 15.0`).
The owner's stack on `:8765` was left alone; it was not probed, restarted or
POSTed to.

### The script, and why it is not E1's script exactly

E1 drove `run` then `walk` and the estimator's dropout — the thing that made
the scenario fail — was a matter of luck. This drives **run → walk_a → still →
walk_b**, wedging a stationary phase into the middle of the walk. A stationary
owner is *unmeasurable* to that estimator (it has a speed floor and a staleness
horizon, not a zero reading), so the hole is guaranteed to open, and one
recording answers both halves of the card:

| Phase | Seconds | Owner | What it is for |
| --- | --- | --- | --- |
| `run` | 10 | 2.2 m/s | the request and the world agree — nothing may fire |
| `walk_a` | 4 | 1.0 m/s | measured walk that banks seconds but has not earned the ask |
| `still` | 8 | 0.0 | the hole R11 wrote nothing about |
| `walk_b` | 10 | 1.0 m/s | the measurement returns; the ask is owed after the REMAINDER |

Mocap driven at 10 Hz through `backend.move_owner`, bouncing between x = ±5.5
in the road corridor exactly as E1 did (the sim clamps at ±10 m, so a straight
leg would park the owner against the clamp and the speed would be a comment
rather than a displacement).

### Pre-flight, for $0

The same script with `--offline` (no credential, no lane, everything else the
shipping stack) ran first —
`r13_live_report_20260820T153517Z.json`. It fired
`pace_mismatch_sustained` **2.102 s** after the measurement returned, with
4.008 s banked across the hole. Only then was the hosted run allowed to spend
anything.

### The hosted run — session `rt_632c37b350bb`, 2026-08-20 15:36:27Z

The owner typed one sentence into the live session. The model called
`follow_owner` (`status: ok`, one broker call, nothing fabricated), the runtime
recorded `pace_intent = "run"`, and the body followed at its own cap.

**The decision log, verbatim from the report:**

```
seq  1  t=396912.166  pace_unknown   key="pace_unknown:duplicate"  forwarded=false
                                     rule=pace_unknown
seq  3  t=396917.470  pace_unknown   key="pace_unknown:duplicate"  forwarded=false
                                     rule=pace_known_resumed
seq 12  t=396931.083  pace_unknown   key="pace_unknown:duplicate"  forwarded=false
                                     rule=pace_unknown          <- the STILL phase
seq 17  t=396939.496  pace_unknown   key="pace_unknown:duplicate"  forwarded=false
                                     rule=pace_known_resumed    <- 8.41 s of blindness
seq 19  t=396940.593  pace_mismatch  key="pace_mismatch"          forwarded=TRUE
                                     rule=pace_mismatch_sustained
        "The robot's follow controller reports: you asked it to run with you, but its
         current gait is its own steady follow pace and it has NOT changed speed for
         that request (its follow speed is capped at 0.35 m/s). Your own measured pace
         over the last 6 seconds is 1.0 m/s, which is a walk. Say what gait you are
         actually in right now, then ask the owner whether they would rather just walk."
seq 23  t=396948.907  pace_unknown   key="pace_unknown:duplicate"  forwarded=false
                                     rule=pace_unknown
```

**The transcript, verbatim:**

```
owner:  Come on, run with me!
robot:  Alright, let's get moving. Let me think about how to keep up with you.
robot:  It came back saying it'll follow you safely, but it hasn't changed speed yet.
robot:  It's in a steady follow gait, not running, and it's capped to that level.
        Want to just walk together?
```

That last sentence is the one E1's scenario 5 was supposed to produce and did
not. It is the robot noticing the owner dropped to a walk and asking about it,
and it is honest about the gait and the cap.

### The two numbers the card's claim reduces to

```
last pace_known_resumed   t = 396939.496
pace_mismatch forwarded   t = 396940.593
                          ----------------
after the measurement returned:  1.098 s     (PACE_MISMATCH_WINDOW_S = 6.0)
```

**A window that RESET would have needed six.** The 1.098 s is the remainder of
a walk that began before the estimator went blind — the pause, measured on the
real stack, against the real estimator, in a real hosted session.

### The rest of the session, because it is evidence too

```
pace_watch  ticks 72 = logged 6 + skips 66     accounted: true
            skips {session_baseline 1, not_following 17, owner_running 6,
                   window_accumulating 6, pace_unknown_holding 29, already_asked 7}
            pace_unknown_episodes 3   pace_unknown_seconds 13.716
whisperer   forwarded 1, suppressed 22
            suppressed_by_rule {never_band 17, pace_unknown 3, pace_known_resumed 2}
            forwarded_by_rule  {pace_mismatch_sustained 1}
            schema_version 2
lane        reconnects 0, stalls 0, rollovers 0, protocol errors [], dropped_sends 0
            narrations 1, narrations_refused 0
            system_initiated_responses 1, system_initiated_tool_calls 0
broker      1 call: follow_owner -> ok
```

* **The run phase fired nothing.** Measured owner speed 2.19–2.24 m/s for ten
  seconds, `owner_running` ×6, `mismatch_banked_s` 0.0 throughout. The ask is
  not a metronome.
* **`already_asked` ×7** — one ask per episode, the latch doing its job while
  the owner kept walking.
* **`system_initiated_tool_calls: 0`** — the whisperer started a reply off the
  robot's own state and the model did not try to move. R11's C1 gate, held
  again under production conditions.

### Cost

| | USD |
| --- | --- |
| Offline pre-flight (no provider) | 0.000000 |
| Hosted run, 3 usage rows | **0.021677** |
| **Receipted total** | **0.021677** |
| Target | well under 1.00 |

**does_not_prove:** that this scene's own furniture produces a run→walk owner —
the mocap is scripted, exactly as E1's was. Everything below `move_owner` is
shipping code: the estimator, the digest, the whisperer, the lane, the model.
It also does not prove anything about `follow_owner(pace="run")` changing a
commanded speed. It still does not, by design (R10 open risk 2, R11 open risk
7, owner-gated) — the robot follows at its own cap and says so.

### One honest wrinkle in the row key

The live rows read `pace_unknown:duplicate`, not
`pace_unknown:insufficient_motion`. `duplicate` is the follow controller's word
for *"this passive observation carried the same timestamp as the last one"* —
on the live sim the runtime hands `observe_owner` the same frame more than once
per cycle, and `_latest_track_status` records whichever call came last. The
wiring test, which feeds the estimator a clean 10 Hz track, gets
`insufficient_motion`.

Both are true and the code says the status is a **hint, not a cause**. But it
means that on the live stack today the word in the key mostly describes the
observation cadence rather than the owner, which is worth knowing before anyone
reads a pack of these rows as a diagnosis. It is also a free datum for the
separate estimator investigation E1 filed: the passive path is being fed
duplicate frames.

---

## §4 — Work item 3: was the watcher in the None-hole during owner session 1?

`evals/20260820/owner_session_1/` was read **read-only** (`README.md`,
`state.json`, `session_slices.json`, `ledger.json`). Nothing under `evals/**`
was written, and the E1 pack's FAIL verdicts stand.

### The window

```
14:12:33.876  realtime  tool follow_owner: ok — "Okay—I'll follow you safely."
14:12:33.877  behavior  Owner-follow enabled
14:12:33.881  owner     "Run with me. Make sure you follow me and don't hit other people, okay?"
14:12:35.446  owner     "Keep up."
14:12:36.107  robot     "It didn't change speed—it's keeping a safe pace while it stays close."
14:12:33 → 14:13:33   follow  "holding: at_follow_distance"  x8, interleaved with
                              "blocked: collision_contact" / "blocked: obstacle_stop"
14:13:34.141  navigation  mission "coffee shop at 42nd street" starts (the follow ends)
```

**60.3 seconds of active follow**, i.e. roughly sixty whisperer digest ticks at
`WHISPERER_TICK_INTERVAL_S = 1.0`.

### The answer, in two halves

**Half one — the measurement was absent, and that half is settled.** At capture
the follow snapshot reads `heading_available: false`, `owner_speed_mps: null`,
`heading_track_status: "insufficient_motion"` — the estimator's own word for
*the owner track has not moved far enough to derive a velocity*. The behaviour
rows agree: for the whole minute the controller reported `holding:
at_follow_distance` and never once chased, which is what a follow does when the
owner is standing still. The owner was at a desk speaking into a mic; the mocap
owner had nobody moving it. So `digest.owner_speed_mps` was `None` across that
follow, and the shipped watcher's gate (`owner_speed_mps is not None`) could not
have been satisfied at any tick.

**Half two — whether the watcher was ENGAGED cannot be read from the artifacts,
and that is the finding.** The watcher only has an opinion when
`follow_pace_intent == "run"`. Three ways to check, all closed:

1. The ledger's internal directive row for the tool call reads `"follow me"` —
   `runtime._realtime_follow` builds that string for **every** pace, so it
   carries no pace.
2. `realtime.pace_intent` is `""` in `state.json`, because a follow that ends
   takes its declaration with it (R11's falling-edge clear, R11 seed S35).
   The capture is ~80 s after the follow ended.
3. `_realtime_last_pace` does hold it — and is published nowhere.

So the artifact cannot distinguish *"engaged and blind"* from *"never engaged"*.
**Both produce exactly zero rows under R11's code**, which is the blind spot
this card exists to close, seen from the other end: the one session that
mattered cannot answer the question the decision log was built to answer.

### What the artifacts DO rule out

The whisperer's own aggregates for that session were
`forwarded: 1` (`critical_bypass` ×1, a mission terminal),
`suppressed: 74`, `suppressed_by_rule: {never_band 67, block_debounce_holding 3,
clear_without_forwarded_block 3, narration_floor_refused 1}`.

There is **no pace-family rule of any kind** in there — no `min_gap`, no
`budget_exhausted`, no `duplicate_within_dedup_window` on a `pace_mismatch`.
Under the shipped code, a watcher that had *evaluated* a mismatch and been
suppressed downstream would have left one of those. So the watcher never
reached `_forward` at any of those sixty ticks: it was declining upstream,
silently, exactly as described.

And the sentence the owner actually heard —

> "It didn't change speed—it's keeping a safe pace while it stays close."

— was the model answering the owner's own "Keep up." one second later. It came
from R10's `pace_applied: false` tool result, **not** from the whisperer. The
robot never noticed anything; it answered a question. (Owner session 1's verdict
table scores this row PASS for *follow with cap honesty*, which it is. It is not
the pace ask, and the two should not be read as the same behaviour.)

### What the same session would have produced under R13

Reproduced as a test rather than asserted:
`test_an_owner_the_estimator_cannot_measure_is_a_row_and_not_a_silence` drives
the REAL runtime and the REAL estimator with a stationary owner and a `run`
declaration — owner session 1's exact shape — and gets

```
row   kind=pace_unknown  key="pace_unknown:insufficient_motion"  rule=pace_unknown
      forwarded=false                       (and nothing spoken: lane.narrated == [])
pace_watch  pace_unknown: true, pace_unknown_episodes: 1,
            skips {pace_unknown_holding: 10, session_baseline: 1}, accounted: true
```

Had the intent NOT been `run`, the same session would instead have shown
`skips {no_run_intent: ~60}`. Either way the artifact answers the question. That
is the whole difference, and it is why the counters are published in
`snapshot()` rather than left in the ring.

**Stated plainly, because the card asks for a determination:** the pace watcher
in owner session 1 was silent, the owner-speed estimate was absent for the whole
follow, and the None-hole is the only mechanism consistent with the recorded
aggregates **if** the pace intent was `run` — which the owner's words
("Run with me") suggest and which no artifact in the capture can confirm.
That last clause is the honest limit and is not dressed up as a yes.

---

## §5 — A defect in the SEED METHOD itself, found the hard way

This one is not about the pace watcher and it is the most portable thing this
card found, so it gets its own section.

**Byte-identical restoration of a source file is not enough to un-do a seed.**
CPython validates a cached `.pyc` against the source's `(mtime_seconds, size)`.
A mutation that keeps the file the **same length** and is restored inside the
**same wall-clock second** leaves a `__pycache__` entry compiled from the
mutated source that every later process silently accepts. The source on disk is
correct, the sha256 matches GOLD, the harness prints `restored=True` — and the
next interpreter imports the mutation.

**R11 seed S20 is exactly such a mutation**: `PACE_MISMATCH_WINDOW_S = 6.0` →
`0.0`, same byte count. Re-running R11's pace seeds against this tree poisoned
`src/parcel_robot/realtime/__pycache__/whisperer.cpython-314.pyc`, and this
card's first live proof ran against a whisperer whose sustained window was
**zero** while the file read 6.0. The symptoms were visible in the transcript
if you knew to look:

```
"Your own measured pace over the last 0 seconds is 0.3 m/s, which is a walk."
```

and the ask firing three times during the RUN phase, on single walk-band samples
— i.e. exactly the behaviour S20 exists to seed. The header, dumped:

```
pyc source_mtime: 1787239592 (Thu Aug 20 11:26:32 2026)  size: 56523
src mtime       : 1787239592 (Thu Aug 20 11:26:32 2026)  size: 56523
flags: 0  (timestamp-validated)
```

### What was done about it

* Every `__pycache__` under `src/` and `tests/` was purged, and the constants
  re-read in a fresh interpreter (`6.0 1.9 2 7 1.0`).
* `r13_seeds.py` now runs children with `PYTHONDONTWRITEBYTECODE=1`, deletes the
  touched modules' cache entries after every restore, and re-reads a **canary**
  (`PACE_MISMATCH_WINDOW_S, WALK_CEILING_MPS, STATE_DIGEST_VERSION,
  len(PACE_SKIP_REASONS), WHISPERER_TICK_INTERVAL_S`) in a fresh interpreter at
  teardown. The harness exits non-zero if the canary does not match. It printed
  `CANARY (fresh interpreter): 6.0 1.9 2 7 1.0  match=True`.
* Every seed run and the live proofs reported in this document were **re-run
  after the purge**. The poisoned first live run is described here and is not
  quoted anywhere as evidence.
* It also records `same_size` per seed in `seeds.json`, so a future reader can
  see which mutations were in the hazard class at a glance.

### Why this is worth a section

The R9 session-B standard verifies the SOURCE bytes and nothing else, and it is
the standard every card in this wave uses. This is a way for a seed to leak into
the next process — including into a `ci_gate` run — while every check the
harness performs says "restored". The gate quoted in §6 was run **after** the
purge and with a verified canary; the earlier gate run in this session predates
the poisoning (15:22Z, before the R11 seed re-run at 11:26 local) and is not
relied on.

**Recommended for the register:** the snapshot-restore standard should require
a bytecode purge on restore and a fresh-interpreter canary at teardown. Filed as
an owner-gated item rather than applied to other cards' harnesses, because
editing another card's harness is not this card's business.

---

## §6 — `ci_gate --tier commit`, verbatim

Read before pasting. Run after the final source edit, after the seed harness's
teardown verified both files byte-identical to GOLD, and after the
`__pycache__` purge and canary described in §5 (`CANARY 6.0 1.9 2 7 1.0`).
Saved at `<scratchpad>/r13/gate_final.txt`.

```
CI GATE — tier=commit  (2026-08-20T15:45:51Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.38s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.34s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.44s
[  PASS] HARD  default-suite              6644 passed, 9 skipped, 42 deselected, 5 warnings in 252.54s (0:04:12)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 265.8s
```

**6644 passed.** The card's brief names 6601 as the baseline entering this
chain; that is R11/E1's number. **R12 (`20260820/task_1`) closed at 6629**, and
that is the number this card was handed. 6644 − 6629 = **15 new tests**: 11 in
`test_realtime_whisperer.py`, 3 in `test_runtime_whisperer_wiring.py`, and one
new parametrized case (`KIND_PACE_UNKNOWN` joining `NEVER_BAND`, which the
"never band never leaks" test walks member by member). **Nothing was removed.**

### The gate's first run in this session went RED, and it is reported

```
[  FAIL] HARD  default-suite   2 failed, 6642 passed, 9 skipped, 42 deselected in 312.02s
    FAILED tests/test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove
    FAILED tests/test_dynamic_costs.py::test_cost_field_vectorization_performance
```

Both are wall-clock performance assertions, and both are load flakes, not
regressions:

* `test_cost_field_vectorization_performance` asserts `per_call < 0.002`; on the
  re-run in isolation it failed with `0.0031336`, and it passes on an idle
  machine. The owner's stack was live throughout this card (`parcel_robot.sim`
  ~60% CPU, `web_panel` ~45%, plus two `llama-server` processes), and the first
  gate ran at a 15-minute load average of **65**; the green gate above ran at
  **20** and falling.
* `test_cpu_budget_proxy` passed on immediate re-run with no change.

Neither test imports anything R13 touched. They are named here rather than
quietly dropped, and the green run is the one that ran last, after the final
edit.

### An inherited flake, measured and handed on

`tests/test_runtime.py::test_runtime_streaming_text_executes_only_final_transcript`
fails intermittently in this tree. It is **not** R13's, and that is measured
rather than asserted:

| Tree | 10 isolated runs |
| --- | --- |
| with R13's `runtime.py` edit | 4 pass / 6 fail |
| with R13's `runtime.py` edit neutralised | 4 pass / 6 fail |

and a probe plugin over the failing run shows the reason it cannot be R13's:
**`_step_whisperer` is called 0 times and `_whisperer_digest` is built 0 times
in that test**, in both outcomes. On a failing run `_enable_owner_follow` is
never reached at all, so the race is upstream, in the behaviour-channel drain
between `submit_voice_text(is_final=True)` and `_step_brain()` —
`runtime_channels.py` is in this wave's modified set (R12). It passed in the
green gate above. Handed to the sprint, not fixed here: `tests/test_runtime.py`
is not this card's file and a quiet edit to somebody else's test is how a real
regression gets hidden.

---

## §7 — Deviations, each with its reason

1. **The live proof's script is not E1's script.** E1 drove `run` then `walk`;
   this drives `run → walk_a → still → walk_b`. The reason is in §3: E1's
   dropout was luck, and a proof of "the window pauses across a hole" needs a
   hole that is guaranteed to open **and** banked seconds on both sides of it.
   The two phases E1 used are still there, in the same corridor, at the same
   speeds.
2. **The hosted proof drove the owner turn through `submit_realtime_text`, not
   audio.** `mode: text`, as every card in this wave has used. The acoustic path
   is untested here and is named in §8.
3. **The live harness imports `Stack` / `Session` / `wait_for` from E1's
   `e1_pack.py`** rather than retyping the sim spawn and hosted-turn plumbing.
   Its scratch-config helpers are NOT reused — R13 writes R13-named config and
   memory files. One cosmetic consequence: the sim socket is named
   `/tmp/claude-1000/e1s<HHMMSS>Z.sock` because `Stack` builds the name from
   `e1_pack`'s import-time stamp. The stamp is this run's; only the prefix is
   inherited.
4. **The sim socket lives under `/tmp/claude-1000/` rather than the scratchpad.**
   `AF_UNIX` caps the path at ~107 bytes and the scratchpad root alone is 92
   (R10 deviation 6). Only the socket moved; every artifact is in the scratchpad.
5. **`_pace_mismatch_fact` is imported by name (a leading underscore) in the
   unit tests.** Its `None` guard is unreachable through `observe` by
   construction, and a guard with no test is a comment. The import carries that
   reason inline.
6. **One real `time.sleep(0.85)` was added to the wiring tests.**
   `FollowOwnerController.snapshot` reads `time.monotonic()` itself and the
   digest calls it with no clock seam, so the only alternatives were to let
   `heading_stale_after_s` elapse for real or to stub the estimator — and
   stubbing the estimator is precisely what let E1's defect through 36 seeds and
   a live proof. The other test in that pair needs no sleep.
7. **`STATE_DIGEST_VERSION` was bumped 1 → 2** (§1.5). Deliberate, and the
   constant's own contract requires it.
8. **`__pycache__` directories under `src/` and `tests/` were deleted** (§5).
   They are build artifacts, `.gitignore`d, and one of them was serving mutated
   bytecode. No tracked file was touched.

## §8 — Open risks and honest limits

1. **The estimator still drops out, and this card did not fix that.** It made
   the dropout *visible and survivable*; the question of why
   `FollowOwnerController` publishes no speed for tens of seconds belongs to the
   follow controller and is E1's separate investigation. Nothing in
   `navigation/follow.py` was touched, and R11 seed S21 (a pace watcher that
   raises a follow cap) is still RED.
2. **The pause is a trade, not a free win.** A standstill is *unmeasurable*, not
   *measured at zero*, so a long stop mid-follow no longer resets the window and
   the ask can arrive after a short final leg of walking. The invariant that
   survives is "≥ `PACE_MISMATCH_WINDOW_S` seconds of MEASURED walking within one
   follow episode, contiguous or not", and blind time banks nothing. R11's
   kerb-pause defence (`test_the_sustained_window_is_long_enough_to_survive_a_kerb`)
   is about the window's LENGTH and still holds; whether a 30-second stop should
   also clear the bank is a policy question, not a bug — **owner-gated item 1**.
3. **The `pace_unknown` key's status word is weak on the live stack** (§3): it
   reads `duplicate` there, because the runtime hands `observe_owner` the same
   frame more than once per cycle. The code says the status is a hint and not a
   cause; do not read a pack of these rows as a diagnosis.
4. **`pace_intent` is still only settable through the hosted `follow_owner`
   tool.** An owner who says "run with me" and lands on the LOCAL voice grammar
   gets a follow with no declaration, and the watcher stays silent (counted as
   `no_run_intent`, which is at least now visible). Wiring the local path is
   outside "runtime.py pace wiring" and touches `voice/local_plans.py`.
5. **E1 defect 3 is still open and unowned.** `runtime._whisperer_digest` reads
   `follow_snapshot["distance_m"]`; the controller publishes
   `desired_distance_m`. `follow_distance_dm` is therefore permanently 0 and
   `KIND_FOLLOW_TICK` can never fire. It is three lines from this card's edit and
   was deliberately left (§0). It needs its own seed. **No card today owns it.**
6. **The whisperer is still a 1 Hz sampler.** A hole that opens and closes
   between two ticks is invisible, and now shows up as *no* `pace_unknown` row
   rather than as a short one. R11 finding 2 said the same thing about block
   episodes; it is true of blindness too.
7. **`pace_unknown_seconds` excludes the hole that is still open** — the open
   one is `pace_unknown_for_s`. A reader summing the wrong field under-reports.
   Both are published; neither is derived from the other.
8. **One live run is a sample.** E1's own scenario 5 is the standing proof of
   that. This run's numbers (1.098 s after resume, 3 blind episodes, 13.7 s
   blind) are an existence proof, not a rate.
9. **Audio was never in the loop.** `mode: text` throughout.

### Owner-gated (nothing here was done)

1. **Should a long standstill clear the banked mismatch seconds?** (risk 2).
   Making blindness reset the window would restore R11's behaviour and re-open
   this card's defect; making a *measured* stop reset it is a different rule
   than the one the card specified. The owner's call on what "we've been walking
   for a while now" should mean.
2. **Should the snapshot-restore standard require a bytecode purge and a
   fresh-interpreter canary?** (§5). It affects every card's harness in the
   register, which is why it is proposed rather than applied.
3. **Should `pace_unknown` ever be spoken?** Today it is never-band and the
   owner is never told the robot cannot measure them. A long blindness during a
   run-follow is arguably worth one honest sentence ("I can't tell how fast
   you're going right now"). That is a policy change to the band table and needs
   the same bench treatment the other bands got.

## §9 — Final state

* `src/parcel_robot/realtime/whisperer.py` (sha256 `9614347a8da39e45`) and
  `src/parcel_robot/runtime.py` (`6956a50970eb51e1`) — the same bytes the seed
  harness verified against GOLD at teardown and the same bytes the last green
  gate ran on. (§2's teardown quotes the whisperer's earlier hash,
  `6930b1441812bd5f`; one docstring paragraph changed after it and the whole
  ladder was re-run — see the §6 addendum 2.)
* **`ci_gate --tier commit`: PASS, every hard gate green, 6644 passed / 9
  skipped** (§6), three times: after the final code edit, after this document,
  and after the last docstring edit. All after the cache purge and with the
  canary verified.
* **Seeds: 14/14 RED, 14/14 restored byte-identical, 0 final repairs**, plus
  R11's six pace-family seeds re-run and still 6/6 RED.
* **Live proof:** one hosted session (`rt_632c37b350bb`) on the real sim, the
  ask fired **1.098 s** after the measurement returned, and the model said
  *"It's in a steady follow gait, not running, and it's capped to that level.
  Want to just walk together?"* — E1 scenario 5's missing sentence.
* **Receipted live spend: `$0.021677`** (plus a $0 offline pre-flight).
* `evals/**` was read-only; the E1 pack's FAIL verdicts stand and no eval file
  was written. `configs/**` untouched. The owner's stack on `:8765` was never
  probed, POSTed to or restarted; `~/.config/parcel/realtime.yaml` was never
  read; the owner's `parcel_memory.sqlite3` was never opened.
* Nothing was committed, staged or stashed. `git status --short` is 61 entries,
  the same set R12 left, with this document added inside the already-untracked
  `scrum/20260820/`.

### Defects filed for the sprint

1. **`tests/test_runtime.py::test_runtime_streaming_text_executes_only_final_transcript`
   races the behaviour-channel drain** — 6/10 failures in isolation, unreachable
   by R13, `_enable_owner_follow` never called on a failing run (§6).
2. **The seed-harness bytecode hazard** (§5) — proposed for the register.
3. **E1 defect 3, `follow_snapshot["distance_m"]`** — still open, still unowned
   (risk 5).

### §6 addendum — confirming re-run, after this document was written

The run in §6 quotes itself, which is circular, so the gate was run once more
with every artifact of this card on disk — the code, the tests and this
document — in case anything walks `scrum/**`. Same result, `default-suite`
**6644** again:

```
CI GATE — tier=commit  (2026-08-20T15:51:42Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.37s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              6644 passed, 9 skipped, 42 deselected, 5 warnings in 246.86s (0:04:06)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 259.7s
```

Both green runs include the inherited `test_runtime.py` flake passing; it is
described in §6 with its measurement, and it is not claimed to be fixed.

### §6 addendum 2 — the last edit, and the gate after it

One docstring paragraph in `_pace_watch` was rewritten after the run above (a
`:data:` role had been split across a line break and read badly; the sentence it
sits in is one an auditor will read). `whisperer.py` therefore ends at sha256
`9614347a8da39e45`, not the `6930b1441812bd5f` quoted in §2's teardown. The
full ladder was re-run against those final bytes — ruff clean, both whisperer
suites 102 passed, **seeds 14/14 RED with `matches_gold=True` and
`CANARY 6.0 1.9 2 7 1.0`** — and then the gate, once more:

```
CI GATE — tier=commit  (2026-08-20T15:57:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.36s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.32s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.38s
[  PASS] HARD  default-suite              6644 passed, 9 skipped, 42 deselected, 5 warnings in 248.55s (0:04:08)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 261.4s
```

**Three green gates, three identical `default-suite` numbers.** The live proof
in §3 ran against the pre-docstring bytes; the change was to prose inside a
docstring and nothing it describes moved, which the re-run seeds and the
identical suite count are the evidence for.

**Final tree:**

```
9614347a8da39e45  src/parcel_robot/realtime/whisperer.py
6956a50970eb51e1  src/parcel_robot/runtime.py
f258b456cdd0e5ed  tests/test_realtime_whisperer.py
48084e63c1a120a0  tests/test_runtime_whisperer_wiring.py
```
