# R12 STATUS — "the terminal tells the truth" (e-stop reason propagation)

**Date:** 2026-08-20 · **Card:** `scrum/20260820/task_1` · **Executor:** Claude
Opus (agent) · **Auditor:** Fable · **Tree:** sole executor, one card, one tree.

**Owner ruling being implemented (verbatim):** "rename to emergency stop" —
approving AUDIT_R9_FABLE owner-gated finding 2.

**Dispatch gate honoured.** The card runs only after R10→R11→E1 close. Verified
before the first edit: `scrum/20260819/task_3/AUDIT_R10_FABLE.md` **ACCEPT_CLOSE**,
`task_4/AUDIT_R11_FABLE.md` **ACCEPT_CLOSE** (gate 6601), `task_5/AUDIT_E1_FABLE.md`
**ACCEPT_CLOSE**. No concurrent mutating agent was spawned at any point.

---

## §0 — One-paragraph answer

The reason was thrown away **twice**, and only the first throw was on file.
`NavigationChannel.stop(reason)` did `del reason` and called a zero-argument
`stop_fn`, so every preempt-driven mission terminal fell back to
`NavigationDetail`'s `navigation_disabled` default (R9's finding). Fixing that
was necessary and **not sufficient**: the first live run of this card recorded
`ended (idle): task_no_longer_active`, because on the real stack `emergency_stop`
tears the executive task down *before* it preempts its own channels, and the
teardown — which hardcoded its own generic word — wins the race and writes the
terminal. Both throws are now closed: the channel passes the caller's reason
through unaltered, and the cause travels with the interrupt so whichever of the
two writes the terminal writes the same word. Live: `Mission to sidewalk ended
(idle): emergency_stop`, narrated as *"the trip to sidewalk ended because the
emergency stop was latched"*, hosted model says *"I stopped because the
emergency stop was latched."*

---

## §1 — What changed, and where

| File | Change | Lines |
| --- | --- | --- |
| `src/parcel_robot/runtime_channels.py` | `NavigationChannel.stop` passes `reason` to `stop_fn`; `stop_fn` retyped `Callable[[str], None]` | +19 / −3 |
| `src/parcel_robot/runtime.py` | `_stop_navigation_channel(reason, *, state)` positional-or-keyword + empty-reason floor; `EMERGENCY_STOP_TERMINAL_REASONS`; e-stop narration branch; `_interrupt_brain(..., stop_reason=)` → `_reconcile_semantic_tasks(stop_reason=)` → `_stop_semantic_dispatches`; 6 call sites declare their cause | +87 / −12 |
| `tests/test_mission_log.py` | new §"card R12: the reason survives" — 24 tests | +288 |
| `tests/test_owner_estop.py` | new §4 "the terminal names the latch" — 4 tests | +123 |

`runtime.py`'s count is measured against a reconstructed pre-card copy
(`<scratchpad>/r12/runtime_pre_r12.py`, built by reversing this card's 14 hunks
and asserting each anchor occurs exactly once), **not** against `HEAD`: the file
carries a large uncommitted R8–R11 batch, so `git diff HEAD` would attribute
~1650 lines of other cards' work to this one. `runtime_channels.py`'s count IS
`git diff --numstat` against HEAD — nothing before this card had touched it.
Both test files are untracked (created by R4-lite and R9, never committed), so
their counts are added-line counts of the sections this card wrote.

**Nothing else was touched.** `realtime/*`, `ingress.py`, yield/person-stop,
`configs/**`, `evals/**` are byte-identical (`git status` shows them exactly as
this card found them); `~/.config/parcel/realtime.yaml` was never opened — the
live proofs write their own scratch configs. Nothing was committed, staged, or
stashed; nothing else in the shared tree was reverted or restaged.

### The choke point is the CURRENT one

The card warned that R10 moved the terminal write. Checked, not assumed: the
non-arrival terminal write is `runtime.py:_stop_navigation_channel` → three
consumers — `_log_mission_terminal`, `_emit("navigation", …)` and
`_narrate_mission_terminal`. R10's arrival layer added a SECOND terminal site in
`_step_navigation` which already carries a real reason (`command.note or
mission_status`) and needed no change. The fix is at the channel→choke-point
seam, not at R9's line numbers.

### Defect 1 — the channel (R9's finding)

```python
    def stop(self, reason: str) -> None:
        del reason            # ← every caller's cause, discarded
        self._stop_fn()
```

`_stop_navigation_channel`'s `reason` is now positional-or-keyword, so the
method *is* the `BehaviorChannel.stop(reason)` shape and the adapter hands it
straight through — no defaulting and no relabelling in the adapter, because a
channel that substituted its own word would be the same defect with a better
vocabulary. Every existing caller passes `reason=` by keyword and is unaffected.

Two things fell out of reading the seam:

1. **The PAUSE half of `preempt` was already honest** (`runtime.py`:
   `detail["reason"] = reason` on pause). The same method recorded the true
   reason for a *paused* mission and the default for a *stopped* one. That
   asymmetry is what makes `del reason` a defect rather than a design decision —
   nobody chose it twice.
2. **Propagation opens a hole it must close in the same change.** While the
   reason was discarded, no caller could write an empty terminal; now one can.
   `reason = reason or "navigation_disabled"` is the floor. `navigation_disabled`
   as an honest "no reason given" is a different claim from a wrong reason.

### Defect 2 — the executive teardown race (found by the live proof, not by tests)

The first live run, with defect 1 already fixed, recorded:

```
Mission to sidewalk ended (idle): task_no_longer_active
```

`RobotRuntime.emergency_stop` does, in order:

```python
self._interrupt_brain("emergency", "emergency stop latched")   # tears the task down
self.preempt("safety", reason="emergency_stop", targets=(..., "navigation", ...))
```

`_interrupt_brain` → `_reconcile_semantic_tasks` → `_stop_semantic_dispatches(
to_stop, "task_no_longer_active")` → `preempt("manual", …)` → the channel → the
terminal. By the time the caller's own `preempt("safety", reason="emergency_stop")`
runs, `was_enabled` is already `False` and no second terminal is written. **The
teardown always wins, and it hardcoded its own word.** Every offline test in this
repo missed it because they all arm the mission by hand, so no executive task
exists and the caller's preempt does write the terminal — the wiring the tests
skipped is exactly where the bug lived.

The fix carries the cause with the interrupt rather than reordering anything on
a safety path:

```python
def _interrupt_brain(self, source, reason, *, stop_reason="task_no_longer_active")
def _reconcile_semantic_tasks(self, *, stop_reason="task_no_longer_active")
```

**The rule for which call sites pass it, applied mechanically and inventing no
words:** a site passes `stop_reason` only when the *same method* immediately
performs a `preempt(..., reason=R, ...)` that targets navigation, and it passes
exactly that `R`. Six sites qualify — `close` (`runtime_closed`), `manual_motion`
(`manual_control`), `_voice_motion` (`voice_motion_started`), `emergency_stop`
(`emergency_stop`), `action("stop")` (`operator_stop`), simulator-adopt
(`simulator_emergency_stop`). The four `"correction"` sites (`set_behavior`,
`start_follow_formation`, `start_navigation`, `start_spatial_behavior`) delegate
to another method that preempts later, on a branch-dependent reason, so they keep
the default rather than guess. The executive's own tick-side reconciliation keeps
it too — `task_no_longer_active` is the right word for a plan step that simply
ended, and `test_a_plan_step_that_simply_ended_still_says_so` pins that the
propagation is not collateral damage.

### `state` is deliberately unchanged

A preempt-driven terminal still records `state: "idle"`, so the owner's e-stop
reads `ended (idle): emergency_stop`. The card's own wording is `ended (…):
emergency_stop` — the reason is what the ruling names. `state` feeds the
executive's navigation verifier and the arrived/failed level choice; moving it
to `cancelled` is a behaviour change this ruling does not authorize. Filed
below as an owner-gated candidate.

---

## §2 — Gate (verbatim, run after the final edit)

```
CI GATE — tier=commit  (2026-08-20T14:44:30Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.76s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.38s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.33s
[  PASS] HARD  default-suite              6629 passed, 9 skipped, 42 deselected, 5 warnings in 248.86s (0:04:08)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 261.7s
```

**6601 → 6629, +28, 0 removed.** ruff `new 0` (no violation was baselined; the
touched files are clean under `ruff check` on their own). Saved verbatim at
`<scratchpad>/r12/gate_final.txt`.

**One source, three kinds of evidence.** The seed harness's GOLD snapshot, the
live proof and this gate all ran against the same bytes — `runtime.py`
`1a7967f1fe7df324`, `runtime_channels.py` `a6af0cd4aeacb74a` (sha256, first 16),
still the tree's hashes at teardown. Only test files were edited after the live
run.

**A note on the card's opening gate, because it is evidence too.** The first
gate of this session was launched in the background and my first edits landed
while it was still running, so it read `runtime.py` mid-write and reported
`2 failed, 6599 passed`. That run is **not** a baseline and is not claimed as
one; the 6601 baseline is R11's audited number. One of the two failures was
real and mine: `test_the_spoken_phrase_exists_exactly_once_in_the_source_tree`
went red because a comment I had just written spelled the owner's spoken
phrase — a fourth copy of the U33 grammar, in a card about the e-stop. The
comment now points at `realtime/ingress.py` instead. The other failure did not
reproduce and was the mid-write artefact.

---

## §3 — Seeds: 17/17 RED, 17/17 restored byte-identical

Harness `<scratchpad>/r12/r12_seeds.py`, results `<scratchpad>/r12/seeds.json`.
**R9 session-B hardening**, and it is why this is not a copy of `r11_seeds.py`:
every touched file is snapshotted ONCE into GOLD at startup, repaired from GOLD
before each seed if it has drifted, restored from GOLD (never from "whatever was
there") in `finally`, and re-verified against GOLD at teardown. A restore whose
reference is read at mutation time cannot detect a concurrent writer and will
cheerfully assert byte-identical restoration of a file it just corrupted.

The harness asserts at runtime that every mutated path is under
`src/parcel_robot/`. **No test, config or eval was mutated at any point.**

| # | Seed | File | Target | Result |
| --- | --- | --- | --- | --- |
| S1 | `NavigationChannel.stop` does `del reason` again (the exact R9 defect) | `runtime_channels.py` | `test_mission_log.py` | **RED** |
| S2 | the same drop, seen from the OWNER'S DOORS | `runtime_channels.py` | `test_owner_estop.py` | **RED** |
| S3 | the choke point ignores the reason it was handed | `runtime.py` | `test_mission_log.py` | **RED** |
| S12 | the registration re-drops the reason at the wiring | `runtime.py` | `test_owner_estop.py` | **RED** |
| S4 | the mission-log ROW loses the reason (event + narration keep it) | `runtime.py` | `test_mission_log.py` | **RED** |
| S5 | the NARRATED fact loses the reason (row + event keep it) | `runtime.py` | `test_mission_log.py` | **RED** |
| S6 | the panel EVENT loses the reason (row + narration keep it) | `runtime.py` | `test_mission_log.py` | **RED** |
| S7 | the channel labels EVERY stop `emergency_stop` (the cheap wrong answer) | `runtime_channels.py` | `test_mission_log.py` | **RED** |
| S8 | every terminal is NARRATED as a latched e-stop | `runtime.py` | `test_mission_log.py` | **RED** |
| S11 | the e-stop set is matched by SUBSTRING instead of membership | `runtime.py` | `test_mission_log.py` | **RED** |
| S9 | the e-stop narration wording is dropped (back to "because of: …") | `runtime.py` | `test_mission_log.py` | **RED** |
| S10 | the empty-reason floor is removed (a terminal recorded as `""`) | `runtime.py` | `test_mission_log.py` | **RED** |
| S13 | the executive teardown reverts to its own generic word (**the live defect**) | `runtime.py` | `test_mission_log.py` | **RED** |
| S14 | `_interrupt_brain` drops the cause the caller handed it | `runtime.py` | `test_mission_log.py` | **RED** |
| S15 | the e-stop door stops declaring its cause to the interrupt | `runtime.py` | `test_mission_log.py` | **RED** |
| S16 | the owner's own stop door stops declaring its cause | `runtime.py` | `test_mission_log.py` | **RED** |
| S17 | over-correction: a plan step that simply ended is relabelled an e-stop | `runtime.py` | `test_mission_log.py` | **RED** |

Harness teardown: `0 file(s) needed a final repair`; both touched files match
GOLD by sha256 (`runtime_channels.py a6af0cd4aeacb74a`, `runtime.py
1a7967f1fe7df324`). **No seed came back GREEN**, so no test needed strengthening
on this card — but note that the seed set could not have caught defect 2 before
the live run existed: S13–S17 are seeds written *against a defect the live proof
found*, not seeds that found it.

### The five the card's DoD names by hand, mapped

| DoD seed | Here |
| --- | --- |
| reason dropped again | S1, S2, S3, S12 |
| e-stop terminal reads `navigation_disabled` | S1, S2, S3 (and S13–S16 for the `task_no_longer_active` variant the live run exposed) |
| log row loses it | S4 |
| narration loses it | S5, S9 |
| a non-estop preempt mislabelled AS `emergency_stop` | S7, S8, S11, S17 |

---

## §4 — Tests added (28)

`tests/test_mission_log.py` (24) — the mechanism. Every pre-existing test in
that file calls `_stop_navigation_channel` **directly**, which is exactly why
they all passed while the owner's e-stop reached the log as
`navigation_disabled`; the new ones enter through `preempt` and the channel.

| Test | What it pins |
| --- | --- |
| `test_a_preempt_reason_reaches_the_terminal_through_the_channel` | log row + panel event + navigation detail all name the cause |
| `test_every_preempt_reason_survives_the_channel_verbatim` (×13) | all 13 real preempt reasons, verbatim — a fix that special-cased the e-stop would leave the same hole under every other word |
| `test_a_non_emergency_preempt_is_never_relabelled_an_emergency_stop` | the over-correction; also asserts the arbiter did NOT latch, so the test cannot pass by accidentally being a real e-stop |
| `test_a_latched_estop_is_narrated_as_a_latched_estop` | the narrated FACT, not just the row |
| `test_the_estop_wording_is_chosen_by_membership_never_by_substring` | R11's keying lesson: a reason merely *containing* the word is not an e-stop |
| `test_a_blank_reason_falls_back_to_the_default_not_to_a_blank` | the hole propagation opens, closed in the same change |
| `test_the_executive_teardown_records_the_cause_that_interrupted_it` (×4) | **defect 2**, reproduced offline: e-stop / panel action / owner stop / manual control, each with a real active executive dispatch planted first |
| `test_a_plan_step_that_simply_ended_still_says_so` | the default is not collateral damage |
| `test_the_channel_adapter_does_not_invent_a_reason_of_its_own` | the adapter is a pass-through, asserted against the adapter itself |

`tests/test_owner_estop.py` (4) — the owner's doors.

| Test | What it pins |
| --- | --- |
| `test_every_estop_door_ends_the_running_mission_as_an_emergency_stop` (×3) | panel/Space `action("emergency_stop")`, the spoken phrase through the restricted ingress, and the in-process `emergency_stop()` all file the same record |
| `test_the_estop_reason_does_not_stick_to_the_next_mission` | latch → record → release → the dog takes orders again → the NEXT mission ends on its own cause |

`_plant_a_running_executive_step` writes one `ActiveSemanticDispatch` into
`semantic_tasks._active` rather than calling `dispatch()`, which would start a
real navigation. It reproduces the *state* the executive is holding when the
owner hits the e-stop, which is the thing that turns an interrupt into a channel
teardown. That reach into a private dict is deliberate and is the only one.

---

## §5 — Live proof

Own sim on its own socket, own runtime, scratch memory DB. The owner's stack
**was** live on `127.0.0.1:8765` (pid 2386623) for the whole card: never posted
to, never restarted, and the only interaction with it was one `ss -ltnp` to
confirm it was there. `configs/robot.yaml` was COPIED with only `memory.path`
changed (R5 deviation 6); the owner's `parcel_memory.sqlite3` and
`~/.config/parcel/realtime.yaml` were never touched.

### Run 1 — `<scratchpad>/r12/r12_live_report_20260820T143321Z.json` — the defect

Channel propagation in place, spoken phrase during a running mission:

```
"reason": "task_no_longer_active"
"text":   "Mission to sidewalk ended (idle): task_no_longer_active."
narrated: "... the trip to sidewalk ended (idle) because of: task_no_longer_active."
```

This run is the reason defect 2 is in this card. It is kept as evidence.

### Run 2 — `<scratchpad>/r12/r12_live_report_20260820T143558Z.json` — the proof

Script `<scratchpad>/r12/r12_live_proof.py`. Mission `go to the sidewalk`,
`state: navigating`, body moved 0.37 m, then the owner's spoken phrase (read from
`ingress.SPOKEN_EMERGENCY_PHRASE`, never re-typed):

```
ingress outcome   {"kind": "emergency", "name": "stop", "executed": true, "reply": "Stopping."}
emergency_stopped true

mission-log row   {"kind": "ended", "goal": "sidewalk", "state": "idle",
                   "reason": "emergency_stop", "level": "warning",
                   "text": "Mission to sidewalk ended (idle): emergency_stop.",
                   "timestamp": "2026-08-20T14:36:12.109324+00:00", "id": 2}

panel events      "Navigating to sidewalk."
                  "Mission to sidewalk ended (idle): emergency_stop"
safety events     "Emergency stop latched"
                  "Emergency stop latched by voice: 'Die stop'"

narrated (floor-gated channel, R8's audible one)
  "The robot's navigation system reports the trip to sidewalk ended because the
   emergency stop was latched. Tell the owner you stopped and why, then ask what
   they want to do instead."
  "The robot's safety system reports it has latched an emergency stop and is not
   moving. Say plainly that you have stopped, and why."

navigation detail {"enabled": false, "state": "idle", "goal": "sidewalk",
                   "reason": "emergency_stop", ...}
```

Then release, and a new mission admits cleanly:

```
action("clear_emergency_stop") -> "Emergency stop cleared";  emergency_stopped false
"go to the bench" -> "Okay—I'll go wait near bench safely.";  state: navigating, moved 0.561 m
next terminal     {"goal": "bench", "reason": "operator_stop",
                   "text": "Mission to bench ended (idle): operator_stop."}
```

The last row is two claims at once: the e-stop did not stick to the next
mission, and the owner's own stop now names itself instead of borrowing the
executive's word.

**Cost: $0.00** — no provider call; the lane is a recorder.

### Hosted proof — the real provider

`<scratchpad>/r12/r12_hosted_proof.py`, transcript
`<scratchpad>/r12/r12_hosted_transcript_20260820T143932Z.json`, session
`rt_27c354259a06`, model `gpt-realtime-2.1-mini`, **one session, three items,
`spend_usd 0.010537`**. Same session, same instructions — the only variable is
the sentence the robot handed up. The lane is a real `RealtimeLane`, so the
floor gate, the system-initiated tagging and the ledger are the shipping ones.
All three items were accepted (`accepted: true`), so this measures wording, not
delivery:

| Item handed up | What the companion said |
| --- | --- |
| A — before the card: `… ended (idle) because of: navigation_disabled` | "I stopped because navigation is disabled, so the trip to the sidewalk is idle. What do you want to do next?" |
| B — after defect 1 only: `… because of: task_no_longer_active` | "I stopped because the task isn't active anymore—what would you like me to do next?" |
| C — what this card ships: `… because the emergency stop was latched` | **"I stopped because the emergency stop was latched. What would you like me to do next?"** |

A is a companion telling its owner a config flag stopped the dog, seconds after
the owner shouted the stop phrase. B is true and useless to a person. C is the
sentence the ruling asked for.

**Total card spend: $0.010537.**

---

## §6 — OWNS compliance

| Owned | Touched | Notes |
| --- | --- | --- |
| `runtime_channels.py` | yes | `NavigationChannel` only |
| terminal-write glue in `runtime.py` | yes | the choke point, its three consumers, and the interrupt seam that races them |
| tests (mission-log + e-stop suites) | yes | extended, not rewritten |
| `scrum/20260820/task_1/R12_STATUS.md` | yes | this file |

MUST NOT TOUCH — all verified untouched: `realtime/*` (read only, for
`SPOKEN_EMERGENCY_PHRASE` and `HINTS`), `ingress.py`, yield/person-stop,
`configs/**`, `evals/**`, the owner's processes. Never committed, staged or
stashed.

**One judgement call to flag for audit:** `_interrupt_brain` /
`_reconcile_semantic_tasks` / `_stop_semantic_dispatches` are executive-teardown
code, not obviously "the terminal-write glue". They are in scope because they
are the thing that *writes the terminal* on every real e-stop — the card's own
Work item 1 says "verify each preempt call-site passes its true reason", and
this is the preempt call-site that actually fires. Had I stopped at the channel,
the card's live proof would have failed and its DoD would not have been met. The
signature change is additive and keyword-only; all three existing tick-side and
test callers are unchanged and pass.

---

## §7 — does_not_prove

1. **It does not prove the terminal is narrated on a second, near-identical
   mission.** `_narrate_mission_terminal` keys the whisperer on
   `mission_ended:{goal}:{state}` with a 60 s dedup TTL, and the reason is
   deliberately NOT in that key. Two terminals for the same goal and state
   inside 60 s narrate once, whichever reasons they carry. Adding the reason to
   the key would reopen R11's flooding class outright: `_step_navigation`'s
   terminal reason is `command.note`, live navigator telemetry whose numbers
   move every 10 Hz tick, and keying on it is precisely the mistake that filled
   the ring with 20 rows in two seconds on 2026-08-18. The mission-log row and
   the panel event carry the reason in every case; only the spoken line is
   deduplicated. Left as-is, on purpose, and listed here rather than fixed.
2. **It does not prove anything about a spoken e-stop's latency.** The words
   still cross the network to become text before `submit_realtime_transcript`
   sees them; R9 said so and this card does not change it.
3. **The hosted proof is one session of three items on one model.** It shows
   what this wording does to a companion's sentence; it is not a measurement of
   how often the model gets it right across sessions.
4. **The offline reproduction of defect 2 plants an executive dispatch by
   hand.** It is the real chain from `_interrupt_brain` onward, but it does not
   run a real plan through the executive; the live runs are what prove the
   ordering on the real stack.
5. **`state` is unproven as correct** — only unchanged. A preempt terminal says
   `idle` for an e-stopped mission and this card did not re-litigate that.
6. **Four `"correction"` interrupt sites still record
   `task_no_longer_active`** when they tear a mission down (see §1). No test
   claims otherwise.

---

## §8 — Owner-gated candidates (decisions, not defects)

1. **`state: "idle"` for an e-stopped mission.** `ended (idle): emergency_stop`
   is accurate about the reason and bland about the state. `cancelled` would
   read better and would flow into the executive's navigation verifier and the
   plan record. Say the word and it is a one-line change plus its seeds.
2. **The four `"correction"` doors.** `set_behavior`, `start_follow_formation`,
   `start_navigation`, `start_spatial_behavior` interrupt the executive and let
   a later method preempt with a branch-dependent reason, so a mission ended by
   "owner asked for something else" still records `task_no_longer_active`. The
   honest words exist (`owner_requested_stay`, `owner_follow_started`,
   `navigation_started`, `replaced_by_new_spatial_behavior`); wiring them means
   moving the interrupt inside the branch, which is a restructure this ruling
   does not cover.
3. **`FollowChannel.stop` and `SearchChannel.stop` still `del reason`.** They
   have no terminal write behind them today — follow's stop reaches only
   `arbiter.cancel`, and search overwrites its detail with a hardcoded
   `search_stopped`. Same shape as the R9 finding, no owner-visible record
   behind it yet. Filed, not fixed.
4. **`stop_navigation()` (the exception path in `_step_navigation`) still
   defaults to `navigation_disabled`** while emitting `Navigation failed:
   {error}`. It is not a preempt site, so it is outside the propagation this
   ruling authorized.

---

## §9 — Handoffs

* The reason vocabulary now reaching the mission log is a **contract**: 13
  preempt reasons plus `task_no_longer_active`, `stop_on_stale_perception`,
  `blocked_by_person…`, `navigation_disabled`.
  `test_every_preempt_reason_survives_the_channel_verbatim` is where a rename
  has to be answered — a reason that stops existing must not quietly become the
  default again.
* `EMERGENCY_STOP_TERMINAL_REASONS` picks the narrated wording only. A new
  e-stop origin must be added to it or its mission will be narrated with the raw
  reason (true, just blunter). Pinned by S9/S11.
* Anyone touching `_interrupt_brain` inherits the rule in §1: pass the reason
  your own following `preempt` uses, or pass nothing.
