# R25 status — the budget that actually refuses

**Card:** `scrum/20260821/task_4/README.md` · **Executor:** Claude Opus (agent)
**Auditor:** Fable — **DEFERRED at the owner's request.** Nothing below assumes
a reader who can ask me a question. Every path is root-anchored, every number
has the command that produced it, and every place I stopped short is named.
**Tree:** working tree at HEAD `2c27496` (`feat: land hosted realtime companion
and embodied voice navigation`). Nothing committed, staged or stashed.

---

## §1 — The defect, restated exactly

The full audit (`scrum/20260820/AUDIT_FULL_FABLE.md` §Ops, second bullet):

> **monthly_budget_usd is a documented control that does not exist:** the
> arming gate never reads it. False documented safety = must fix or un-document.

Measured before touching anything:

* `src/parcel_robot/realtime/lane.py::decide_realtime_arming` has had the
  comparison since R1 — `if spend_usd >= config.monthly_budget_usd:` — with the
  parameter defaulted: `spend_usd: float = 0.0`.
* Its **only** caller was `RealtimeLane.arm`, and that call passed
  `config`, `handshake_token`, `mic_gesture`, `transport_available` — and no
  spend figure at all.
* So for R1 through R24 the owner's ceiling evaluated `0.0 >= 25.0` on every
  session. The `CODE_BUDGET_EXHAUSTED` branch was unreachable on every
  constructible path.
* `configs/realtime.yaml.example:106-109` documented it as a live control:
  *"The arming gate refuses to open a session once this month's estimated spend
  reaches this number."*
* The only spend arithmetic that existed —
  `realtime_spend_usd(lane.usage_rows)` at `runtime.py:7391` — is **this
  process's** sessions. `usage_rows` is a plain list on the lane, emptied by
  every restart. Feeding *that* to the gate would have been worse than nothing:
  the ceiling would reset every time the robot rebooted, which is also the
  moment a runaway loop restarts.

The audit's framing is the right one and I want it on the record before the
diff: this is not "a feature was missing". The owner read their own config file
and reasonably believed a ceiling existed. Weeks of operation happened under
that belief.

---

## §2 — What shipped

### 2.1 The ceiling is real (work item 1)

`src/parcel_robot/realtime/lane.py`

* `RealtimeLane.arm` now reads the durable month-to-date figure and passes it
  (plus `spend_readable`, `spend_month`, `spend_note`) into
  `decide_realtime_arming`. This is the one-line-shaped change the whole card
  hangs from; everything else exists to make that number trustworthy.
* `decide_realtime_arming` gained `spend_readable` / `spend_month` /
  `spend_note`, and `RealtimeArmingDecision` gained `warnings: tuple[str, ...]`
  (carried in `as_dict()`), because a *degraded yes* previously had nowhere to
  put a reason — a refusal carries one, an arm did not.
* The refusal names the figure, the period and the key. Verbatim, from the live
  proof:

  > Realtime lane not armed: an estimated $0.0109 in 2026-08 has reached the
  > $0.0054 realtime.monthly_budget_usd ceiling (config source: …/realtime.yaml;
  > rates are ASSUMED, not billed). Raise realtime.monthly_budget_usd in your
  > realtime.yaml (or wait for the 1st of next month, UTC) to open a session.
  > Safety-class narrations on a session that is already open are never gated by
  > this ceiling.

* `_budget_sentence()` builds the figure/period/source clause once. Both
  numbers share ONE precision, chosen off the smaller of the two — see §5.1,
  which is a defect the live proof found in my own first implementation.

**Fail-OPEN on an unreadable ledger, and the card is right that this is the
correct direction.** `spend_readable=False` ⇒ the gate does **not** refuse; it
arms and attaches the ledger's own warning, which reaches `lane.events`,
`/api/state` and the panel. This is the single deliberate inversion of this
package's fail-closed doctrine and it is stated in three places (the
`spend_ledger` module docstring, `decide_realtime_arming`'s docstring, and
`configs/realtime.yaml.example`). It is pinned in **both** directions —
`test_an_unreadable_ledger_arms_with_a_warning_instead_of_refusing` and
`test_a_broken_ledger_lets_the_lane_open_and_says_so` for the open half,
`test_the_gate_refuses_at_the_ceiling_and_names_figure_period_and_key` for the
closed half — so a future "hardening" reddens a test instead of silently
grounding the dog. Seed **S4** is that over-correction.

The doctrine still holds where it belongs: the CONFIG fails closed. A typo'd
`monthly_budget_usd` refuses to load, and now `.inf` does too (§2.5).

### 2.2 The durable ledger (work item 2)

**New file:** `src/parcel_robot/realtime/spend_ledger.py` (≈470 lines,
docstring-heavy on purpose — this is the file a future reader will have to
trust).

* One append-only JSON-lines file at **`<capture root>/spend.jsonl`**
  (default `<repo>/recordings/spend.jsonl`), a *sibling* of the per-session
  folders rather than a file inside one, because "this month" spans sessions by
  construction. Path resolved through the existing `resolve_capture_dir`, which
  buys two guarantees for free: repo-relative resolution against the repo root
  (not the cwd — the doubled-prefix incident of 2026-08-20), and a **load-time
  refusal of any root inside `evals/`**, so a live spend ledger can never append
  into the frozen fixture tree a run is scored against. Asserted by
  `test_the_default_ledger_path_is_beside_the_recordings_and_never_in_evals`.
* One row per hosted response, written from `lane._append_cost_row` (the one
  place a response's usage is known). Real row from the live run:

  ```json
  {"cached_tokens": 0, "estimated_usd": 0.009892, "input_tokens": 1973,
   "month": "2026-08", "output_tokens": 125, "rates_are_assumed": true,
   "response_id": "resp_EFFwKk33wCXbDVAhLUtBT",
   "schema": "parcel.realtime_spend.v1",
   "session_id": "rt_86748840dec1", "wall": "2026-08-21T09:35:01Z"}
  ```

* **`rates_are_assumed` is on EVERY row**, not once in a header, and on the
  `MonthToDateSpend` object, and in every snapshot. A reader who greps one line
  must not be able to mistake this for an invoice. Seed **S12**.
* Period is **UTC** (`month_key` ⇒ `"YYYY-MM"`), deliberately not local time: a
  DST-shifting local boundary would make "this month" ambiguous for an hour
  twice a year. The refusal names the period so the owner never has to infer it.
* Three degradations, graded rather than lumped:
  * **absent file** → `readable=True, usd=0.0`, no note. A ledger that has never
    been written is not a broken one; a fresh install must not wear a warning it
    did not earn.
  * **corrupt lines** → skipped, **counted** (`skipped_rows`), `readable` stays
    True, note says `UNDERCOUNT`. Same fail-open *direction* as the unreadable
    case, deliberately not a second, contradictory policy.
  * **unreadable file** → `readable=False`, note names the OSError and says the
    ceiling is NOT being enforced.
* Never raises at either entry point. `record()` runs on the pump thread — card
  R22 §Safety-1's whole subject was an exception there killing the crank — so
  it returns a bool and counts `write_failures`. `month_to_date()` is total.
  `lane._append_cost_row` wraps the call in its own broad catch and counts
  `lane.spend_ledger_failures` on top (`test_a_ledger_that_raises_never_takes_
  the_pump_down`).
* A 5 s TTL cache with **in-place updates on write**, so the narration gate can
  consult the ceiling per fact without touching the disk per fact, and the
  in-process number is exact between re-reads rather than merely fresh.

**Wiring:** `RobotRuntime._arm_spend_ledger()` (beside `_arm_session_evidence`,
armed in the same place, `runtime.py`) constructs it and hands it to the lane as
`spend_ledger=`. Never raises: an unconstructible ledger is a WARNING and a
`None`, and `None` means *not metered* — the pre-R25 behaviour byte-for-byte, a
different claim from "$0.00 spent" and rendered differently everywhere.
`PARCEL_REALTIME_SPEND_LEDGER` names an explicit file;
`PARCEL_SESSION_EVIDENCE_DIR` moves the whole root.

### 2.3 Surfacing (work item 3)

* `RealtimeLane.snapshot()` gained `month_to_date` (the ledger's own dict, or
  `None` when unmetered), `monthly_budget_usd`, `spend_ledger_failures`,
  `narrations_skipped_budget`, `narrations_over_budget`.
* `RobotRuntime.realtime_snapshot()` gained `month_to_date`, which is
  `SpendLedger.snapshot(budget_usd=…)` — measurement **plus** `budget_usd`,
  `remaining_usd`, `fraction_of_budget`, `over_budget`. The panel does no
  arithmetic, so it cannot disagree with the gate about whether the ceiling has
  been reached.
* `src/parcel_robot/ui/index.html::realtimeBudgetLabel` renders three states and
  never collapses them: **no ledger** ("monthly ceiling not enforced"),
  **unreadable** ("spend ledger UNREADABLE — monthly ceiling not enforced"),
  and a figure ("2026-08 ~$0.01 of $25.00 (0%)", plus "— CEILING REACHED, new
  sessions refused" past the line). Seed **S17**.

### 2.4 The safety/cost asymmetry — decided and pinned (work item 4, and F1-SI open risk 10.2)

**The decision, in one paragraph.** SAFETY-class facts outrank the owner's cost
ceiling. On an open session, `whisperer.CRITICAL_KINDS` — the emergency latch
and its clear, a refusal of the owner's own command, a mission terminal — are
narrated **past** `monthly_budget_usd` and counted in `narrations_over_budget`.
Everything else — battery state, pace mismatch, a voice rejection — is held back
and counted in `narrations_skipped_budget`. This is the same asymmetry those
classes already have against the whisperer's `max_updates_per_minute`, and it
reads off **the same list**: `runtime._whisper` and `runtime._step_whisperer`
pass `critical=<kind> in CRITICAL_KINDS` rather than re-listing kinds, so
"which facts outrank the owner's cost knob" has one answer in this codebase and
cannot drift into two.

**Where it lives, and why not in the arming gate.** I deliberately did **not**
give `decide_realtime_arming` a safety exemption. Card R16's older and stronger
rule already decides that case: a robot-initiated fact may never OPEN a paid
session, because a latch announced into a session the owner walked away from an
hour ago is spend with no listener. A closed lane therefore stays closed for
every class of fact at every budget, nothing safety-related ever reaches the
arming gate, and an exemption there would have been a parameter no caller could
pass. I wrote one, saw it was unreachable, and removed it. The gate's docstring
says so in full.

**The other direction of the ceiling, stated plainly:** it refuses to OPEN a
session and never hangs up one already open. The owner mid-sentence is worth
more than the rounding error, and the overshoot is bounded by `session_max_s`.
What the ceiling does to an open session is stop the ROBOT from starting billed
exchanges the owner did not ask for; the owner's own turns are never gated.

**F1-SI open risk 10.2 — answered, NO.** `voice_rejected` does **not** bypass
the cost ceiling, because the bypass set is defined by one rule — facts about
the OWNER'S OWN request, or the latch — and a rejection is by construction a
fact about somebody else's. A talkative television must not be able to spend
past a ceiling the owner set. This is the direction F1-SI §10.2 flagged as
uncomfortable and I am not pretending it is free: **a FALSE reject of the real
owner, in a month that has hit its ceiling, gets no spoken explanation.** Three
mitigations, all real, none complete: the counter and the panel event for a
rejection are unconditional (the fact is never lost, only the sentence);
`VoiceIdentityGate.note_rejection`'s own 60 s rate limit is unchanged; and the
panel now shows month-to-date against the ceiling, so "the robot went quiet" is
diagnosable in one glance instead of being indistinguishable from a fault. The
residual risk is carried forward as **§8.2**, and moving `KIND_VOICE_REJECTED`
into `CRITICAL_KINDS` remains a one-line owner decision — **§9, item 1**.

Pinned by `test_a_safety_narration_is_spoken_past_the_ceiling`,
`test_non_safety_chatter_is_held_back_by_the_ceiling`,
`test_the_bypass_set_is_exactly_the_whisperers_critical_set`,
`test_the_runtime_marks_safety_classes_critical_on_the_way_to_the_lane`.
The over-correction (a ceiling that gags the latch) is seed **S5**; the
under-correction (no ceiling on an open session at all) is seed **S6**.

### 2.5 `+inf` — R23's registered gap, closed here

`scrum/20260821/task_2/R23_STATUS.md` §7.2 measured that
`realtime/config.py::_positive` uses `not number > 0.0`, which refuses NaN by
accident of IEEE comparison and **accepts `float("inf")`** — which YAML spells
`.inf`. In that file `+inf` means an infinite stall timeout, an unbounded
session, a mic that never idle-closes, and *an unlimited monthly budget*. R23
could not fix it (the realtime package was outside its OWNS list), pinned the
behaviour in `test_realtime_positive_still_accepts_infinity_registered_gap`, and
left instructions: *"When that lands, delete this test and remove the skip in
`test_documented_fail_closed_loaders_that_R23_owns_also_refuse_infinity`."*

My card OWNS `realtime/config.py` validation and owns the budget, so I did
exactly that. `_positive`, `_non_negative`, `_voice_positive` and
`_voice_non_negative` now all require `math.isfinite` first, with an error that
says *why* a non-finite limit is not "no limit". The registered-gap test is
deleted, the skip is gone (so `+inf` is now asserted against **every** loader in
R23's table with no exceptions), and
`test_realtime_config_refuses_infinity_on_every_positive_key` covers all four
realtime keys in both signs. Seed **S16**.

**This is the one place I edited another card's test file** (`tests/test_fail_
closed_limits.py`). It is the handoff R23 wrote down rather than scope creep,
and R23's comment block is rewritten to say the gap is closed and by whom.

---

## §3 — Files touched (root-anchored)

**New**
* `/home/jaewoo-jang/Desktop/Projects/Parcel/src/parcel_robot/realtime/spend_ledger.py`
* `/home/jaewoo-jang/Desktop/Projects/Parcel/tests/test_realtime_spend_budget.py` (34 tests)
* `/home/jaewoo-jang/Desktop/Projects/Parcel/scrum/20260821/task_4/R25_STATUS.md` (this file)

**Modified**
* `src/parcel_robot/realtime/lane.py` — arming path, `warnings`,
  `SpendLedgerLike`/`MonthToDateSpendLike` protocols, `month_to_date_spend()`,
  `_over_monthly_budget()`, `narrate_event(..., critical=)`,
  `_append_cost_row` second destination, snapshot keys, `__all__`.
* `src/parcel_robot/realtime/config.py` — finiteness on the four number
  validators; module docstring records the closed gap.
* `src/parcel_robot/realtime/__init__.py` — exports.
* `src/parcel_robot/runtime.py` — `_arm_spend_ledger`, `_realtime_month_to_date`,
  `spend_ledger=` on the lane, `critical=` on both narration doors,
  `month_to_date` in the snapshot.
* `src/parcel_robot/ui/index.html` — `realtimeBudgetLabel` + detail line.
* `configs/realtime.yaml.example` — the `monthly_budget_usd` block now describes
  what the code does (the audit's "must fix **or un-document**" — I fixed, and
  re-documented to match).
* `tests/conftest.py` — see §5.2.
* `tests/test_fail_closed_limits.py` — R23's handoff (§2.5).
* `tests/test_r24_lock_discipline.py` — R24's re-entry roster (§5.3).
* `tests/test_mission_log.py`, `tests/test_realtime_answer_beat.py`,
  `tests/test_runtime_whisperer_wiring.py`,
  `tests/test_realtime_completion_tense.py` — lane doubles (§5.4).

**Not touched, per the card:** ingress, prompting, the broker tool set, yield,
evals fixtures, `~/.config/parcel/realtime.yaml`, the owner's
`parcel_memory.sqlite3` (never opened read-write; never opened at all).

---

## §4 — Gate — FULLY GREEN, verbatim

Re-run after the final edit
(`.parcel/bin/python scripts/ci_gate.py --tier commit`):

```
CI GATE — tier=commit  (2026-08-21T09:40:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.37s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.26s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.33s
[  PASS] HARD  default-suite              7442 passed, 9 skipped, 42 deselected, 5 warnings in 284.04s (0:04:44)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 297.0s
```

Baseline entering the chain was 7164; this tree entered at **7407 passed, 10
skipped** (the R22/R23/R24/EV-1/F1-SI work already in the tree) and leaves at
**7442 passed, 9 skipped** — +35 tests (34 new in
`tests/test_realtime_spend_budget.py`, plus one new
`test_realtime_config_refuses_infinity_on_every_positive_key`, less the deleted
registered-gap test), and one fewer skip because R23's `+inf` skip is gone
(§2.5). Ruff: `7 violation(s), baseline 7, new 0` — the pre-existing debt, none
of it mine.

---

## §5 — Things that went wrong, and what they cost

### 5.1 My own refusal message was silent at sub-cent budgets — found by the live proof

The card's live proof asks for a `$0.001` budget. My first implementation
formatted both figures with `:.2f`, so act A refused with:

> an estimated **$0.00** in 2026-08 has reached the **$0.00**
> realtime.monthly_budget_usd ceiling

That is the "refusal reason silent" failure with a number in front of it. Fixed:
both figures now share ONE precision chosen off the smaller of the two (4 places
under $0.10, 2 above), because formatting them independently would produce
"$0.01 has reached the $0.0052 ceiling", which reads like a bug. Re-run gives
"an estimated $0.0010 … has reached the $0.0010 … ceiling". New test
`test_a_sub_cent_ceiling_still_names_a_figure_the_owner_can_act_on`; new seed
**S3b**. **The DoD's live proof is what caught this** — the unit tests I had
written all used round-dollar budgets.

### 5.2 The suite would have accumulated a real ceiling — `tests/conftest.py`

The ledger is ON by default wherever the lane is. Left alone, any suite run that
drove a fake `response.done` through a runtime-built lane would append to
`<repo>/recordings/spend.jsonl` — and keep appending, run after run, until the
repo's own test suite crossed `monthly_budget_usd` and the arming gate started
refusing sessions in unrelated tests, months later, for no visible reason. That
is a slow-fuse time bomb of exactly the kind this chain has been fixing.

`pytest_configure` now **relocates** the ledger to a per-run `tempfile.mkdtemp`
(removed in `pytest_unconfigure`) via `PARCEL_REALTIME_SPEND_LEDGER`.
Relocated, **not** switched off — I considered mirroring EV-1's
`PARCEL_SESSION_EVIDENCE=0` and rejected it: an off switch on a cost control is
the "silent off switch" this codebase refuses everywhere else, and relocating
means the production wiring (arm → write → read the ceiling) is the code the
suite actually exercises. Tests that assert on ledger contents point the same
variable at their own `tmp_path`.

### 5.3 A new re-entry lambda, caught by R24's ratchet

`_arm_spend_ledger` passes `on_note=lambda message: self._emit(...)` — the
ledger's fail-open warning sink, fired from `month_to_date()`, which the arming
path and the narration gate both call from different threads. R24's
`test_the_lambda_reentry_callbacks_reach_only_the_sink_lock` went red on the
unrostered `on_note`. Correct behaviour by the ratchet; the lambda reaches only
`self._emit` → `_lock`, and `_lock` is a sink in R24's verified order graph, so
the structural safety argument is unchanged. Rostered with the reasoning rather
than waved through.

### 5.4 21 suite failures from a *silent* signature break — the ugliest thing I found

Adding `critical` to `narrate_event` broke five test doubles that declared
`def narrate_event(self, text: str)`. The failure mode is what matters:
`runtime._narrate_mission` wraps its lane call in
`except (RuntimeError, TypeError, ValueError)` — narration is a nicety and must
never take a mission terminal down — so **every narration raised TypeError and
was reported as "the robot had nothing to say"**. No exception surfaced, no
counter moved. In production a lane whose `narrate_event` signature drifted
would go quiet about the emergency latch and nothing would say why.

Fixed the doubles (they now record `narrated_critical` too), and added
`test_the_narration_door_and_the_lane_agree_on_the_critical_keyword`, which
pins the two signatures against each other by `inspect`. I am flagging the
underlying catch as **§8.4**: it is correct policy with a real blind spot, and
it is not mine to redesign on this card.

### 5.5 A `ruff check --fix` over-reached

I ran `ruff check --fix src/ tests/` and it auto-fixed four files outside my
card (`camera_channel/__init__.py`, `camera_channel/channel.py`,
`detection_adapter/noise.py`, `detection_adapter/sim_bridge.py`). Reverted
immediately with `git checkout --` on those two directories; verified by mtime
that no other pre-existing file was touched, and the ruff ratchet is back at
`7 violation(s), baseline 7, new 0`. Recorded because a silent reformat of
someone else's file is exactly what a deferred audit cannot ask about.

---

## §6 — Seeds — 19, all RED

Harness `<scratchpad>/r25/seed_r25.py`, canary `<scratchpad>/r25/canary_r25.py`,
results `<scratchpad>/r25/seeds_final.txt` + `seeds.json`
(`<scratchpad>` = `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`).

House rule R9, session-B: snapshot exact bytes → apply one exact-string mutation
→ run the guarding tests in a **fresh interpreter** → restore the bytes → purge
every `__pycache__` under `src/` and `tests/` → assert sha256 byte-identity. The
purge runs on **both** sides of every seed, because a stale `.pyc` compiled from
a mutated source passes a byte-identity check on the `.py` while still being
what the interpreter imports. A separate fresh-interpreter canary runs after all
restores.

| # | Seed | Target | Re-opens | Result |
|---|---|---|---|---|
| S1 | `budget-ignored-again` | `realtime/lane.py` | **THE AUDIT'S DEFECT** — `arm()` stops passing the figure; the gate compares `0.0` again | **RED** 4 failed |
| S2 | `gate-branch-deleted` | `realtime/lane.py` | the refusal branch removed outright | **RED** 6 failed |
| S3 | `refusal-reason-silent` | `realtime/lane.py` | the refusal stops naming figure, period and key | **RED** 3 failed |
| S3b | `sub-cent-refusal-rounds-to-zero` | `realtime/lane.py` | §5.1's own finding: "$0.00 has reached the $0.00 ceiling" | **RED** 1 failed |
| S4 | `fail-closed-on-unreadable-restored` | `realtime/lane.py` | the deliberate fail-OPEN inverted — a broken file grounds the robot | **RED** 1 failed |
| S5 | `safety-narration-blocked-by-budget` | `realtime/lane.py` | **THE OVER-CORRECTION** — a cost ceiling that gags the emergency latch | **RED** 1 failed |
| S6 | `narration-gate-removed-entirely` | `realtime/lane.py` | the other half — chatter bills past the ceiling, so it is decorative | **RED** 2 failed |
| S7 | `over-budget-helper-fails-open-always` | `realtime/lane.py` | the shared over-budget predicate becomes a rubber stamp | **RED** 2 failed |
| S8 | `cost-row-never-reaches-the-ledger` | `realtime/lane.py` | responses stop being priced; the ceiling silently stops moving | **RED** 2 failed |
| S9 | `ledger-not-durable-truncating-write` | `realtime/spend_ledger.py` | `"a"` → `"w"`: month-to-date collapses to the last response, a restart forgets everything | **RED** 4 failed |
| S10 | `month-key-ignored` | `realtime/spend_ledger.py` | every month ever recorded counts as this one; the ceiling never resets | **RED** 1 failed |
| S11 | `unreadable-ledger-reads-as-a-measured-zero` | `realtime/spend_ledger.py` | fail-open without the loudness — a broken file indistinguishable from "$0.00" | **RED** 3 failed |
| S12 | `assumed-rate-flag-dropped` | `realtime/spend_ledger.py` | `rates_are_assumed` stops riding every row | **RED** 2 failed |
| S13 | `runtime-never-hands-the-ledger-to-the-lane` | `runtime.py` | a ledger armed and never consulted — the exact shape the audit found | **RED** 1 failed |
| S14 | `runtime-marks-nothing-critical` | `runtime.py` | the refusal door stops setting `critical`, making the lane's exemption unreachable | **RED** 1 failed |
| S15 | `latch-path-marks-nothing-critical` | `runtime.py` | the DIGEST path — the one the latch travels — loses the flag | **RED** 1 failed |
| S16 | `config-accepts-infinite-budget-again` | `realtime/config.py` | R23 §7.2 re-opened: `monthly_budget_usd: .inf` loads as unlimited | **RED** 2 failed |
| S17 | `panel-collapses-the-three-ledger-states` | `ui/index.html` | "no ledger" rendered as nothing; the panel stops saying "I cannot tell you" | **RED** 1 failed |
| S18 | `guard-file-deleted` | `tests/…` | the whole ratchet deleted — the DoD's explicit seed | **RED** collection error |

The DoD asked for ≥8 covering *"budget ignored again; refusal reason silent;
safety narration blocked by the budget; ledger non-durable; fail-closed-on-
unreadable restored"* — S1/S2/S13 (ignored), S3/S3b (silent), S5 (the
over-correction), S9/S10 (non-durable), S4/S11 (fail-closed restored), plus
seven more.

**Integrity:** every `restored=OK` (`sha_before == sha_after` asserted in-harness
for all 19; recorded in `seeds.json`). Fresh-interpreter canary after all
restores:

```
FRESH-INTERPRETER CANARY: OK
CANARY refusal: Realtime lane not armed: an estimated $5.00 in 2026-08 has reached the $5.00 realtime.monthly_budget_usd ceiling (config source: canary; rates are ASSUMED, not billed). Raise realtime.monthly_budget_usd in your realtime.yaml (or wait for the 1st of next month, UTC) to open a session. Safety-class narrations on a session that is already open are never gated by this ceiling.
POST-RESTORE tests/test_realtime_spend_budget.py + tests/test_fail_closed_limits.py: 194 passed, 2 warnings in 1.40s

19/19 seeds RED
```

No seed came back GREEN; nothing needed re-strengthening.

---

## §7 — Live evidence

Script `<scratchpad>/r25/live_r25.py`, report `<scratchpad>/r25/live_report.json`,
transcript `<scratchpad>/r25/live_run.txt`. Own in-process stack, scratch
`realtime.yaml`, scratch memory sqlite, scratch capture root — the owner's
`~/.config/parcel/realtime.yaml`, `parcel_memory.sqlite3` and `:8765` stack were
never written to, and `:8765` was never contacted at all. Credential loaded with
`set -a; . ~/.config/parcel/realtime.env; set +a` and never printed.

**Act A — `monthly_budget_usd: 0.001`, ledger pre-seeded with one $0.001 row.
Refused, offline.**

```
"refused": true, "code": "monthly_budget_exhausted", "socket_opened": false,
"transport_available": true          <- a key WAS present; the ceiling refused anyway
"message": "Realtime lane not armed: an estimated $0.0010 in 2026-08 has reached
  the $0.0010 realtime.monthly_budget_usd ceiling (config source: …/realtime.yaml;
  rates are ASSUMED, not billed). Raise realtime.monthly_budget_usd in your
  realtime.yaml (or wait for the 1st of next month, UTC) to open a session.
  Safety-class narrations on a session that is already open are never gated by
  this ceiling."
"month_to_date_snapshot": {"usd": 0.001, "budget_usd": 0.001,
  "remaining_usd": 0.0, "fraction_of_budget": 1.0, "over_budget": true, "readable": true}
```

`transport_available: true` with `socket_opened: false` is the load-bearing
pair: the credential and the websocket transport were both present and the lane
still opened no socket. Cost of act A: **$0.00**.

**Act B — same stack, `monthly_budget_usd: 25.0`. A REAL hosted session.**

```
"session_id": "rt_86748840dec1"
"provider_session_id": "sess_EFFwKjZWnbWOKGFmRLe58"
"armed": {"armed": true, "code": "armed", "warnings": []}
owner: "Say hello in five words or fewer."
robot: "Hello, nice to be."
"usage": {"responses": 1, "input_tokens": 1973, "output_tokens": 125,
          "output_audio_tokens": 33, "cached_tokens": 0,
          "estimated_usd": 0.009892, "rates_are_assumed": true}
"protocol_errors": [], "server_errors": []
"month_to_date_before": {"usd": 0.001,    "over_budget": false}
"month_to_date_after":  {"usd": 0.010892, "over_budget": false,
                         "remaining_usd": 24.989108, "fraction_of_budget": 0.0004,
                         "rows": 2, "rows_written": 1, "write_failures": 0}
```

The response's own priced row landed in `spend.jsonl` on disk, with
`rates_are_assumed: true`, the UTC month key, and the session id it belongs to.

**Act C — a fresh runtime + fresh ledger object over the SAME file, ceiling set
below what act B measured. Refused.**

```
"budget_usd": 0.005446, "measured_month_to_date_usd": 0.010892
"refused": true, "code": "monthly_budget_exhausted", "socket_opened": false
"message": "… an estimated $0.0109 in 2026-08 has reached the $0.0054
  realtime.monthly_budget_usd ceiling …"
"month_to_date_snapshot": {"usd": 0.010892, "over_budget": true,
  "remaining_usd": -0.005446, "fraction_of_budget": 2.0, "rows_written": 0}
```

`rows_written: 0` on a total of `0.010892` is the durability proof stated as a
number: this ledger object wrote nothing itself and read the live session's
spend off the disk. **Act C is the claim the card is really about** — the
ceiling refuses on money a *previous* run actually spent.

**Cost.** Two full runs of the proof (I re-ran after fixing §5.1), one hosted
turn each: `$0.009488 + $0.009892 = $0.019380` estimated at assumed rates.
Nothing else in this card touched the network. Well under the $1 budget.

**does_not_prove.** Act B ran ONE short text turn on
`gpt-realtime-2.1-mini`; nothing here measures audio-mode cost, a long session,
prompt-cache behaviour or rollover accounting. The dollar figures are estimates
at `realtime/cost.py`'s ASSUMED rates and were not checked against an invoice —
that is the same honesty the module has always carried, and this card did not
improve on it. Act A's refusal is proven against a *pre-seeded* ledger row
rather than one produced by a real session; act C closes that gap for the real
row. The panel rendering (§2.3) is asserted against the shipped
`index.html` source text, not against a browser.

---

## §8 — Open risks

**8.1 — The ledger is a LOWER BOUND, and the ceiling inherits that.** Rows are
appended on `response.done`. A response the provider billed whose completion
frame never arrived — a socket death mid-response, which card R19 documents
happening — is money spent that this ledger never sees. Month-to-date is
therefore an undercount by construction, and the ceiling fires later than the
true spend would justify. Bounding it would need reconciliation against a real
invoice, which needs a billing API this project does not have.

**8.2 — A false voice reject in an exhausted month is silent (F1-SI 10.2's
residual).** Decided in §2.4 and I stand by it, but the uncomfortable case is
real: the owner is misidentified, the month is over budget, and the spoken
explanation is withheld. The counter and panel event still fire, and the panel
now shows why the robot is quiet. One line moves it (§9 item 1).

**8.3 — Two machines, two ledgers, two ceilings.** The file lives under the
capture root, so a month spent across two hosts is two independent totals and
each enforces its own ceiling. Correct for a single robot; wrong the day there
are two.

**8.4 — `_narrate_mission`'s TypeError catch hides signature drift.** §5.4 in
full: a lane whose `narrate_event` signature does not match makes every
narration vanish with no exception and no counter. I pinned the current pair by
`inspect` rather than narrowing the catch, because narrowing it risks a
narration bug taking a mission terminal down — which is the thing that catch
exists to prevent. A `narrations_errored` counter would be the honest fix and
belongs to whoever owns `runtime.py`'s narration door next.

**8.5 — `month_to_date()` reads the file on the arming path.** Bounded (a
5 s TTL and an append-only file of ~200-byte rows), and it never blocks a
control loop because failure is fail-open and instant. But a ledger left to grow
for years is a linear scan on every arm. A month-partitioned filename would fix
it; not needed at this scale and not done.

**8.6 — The suite's ledger relocation is a `pytest_configure` side effect.**
§5.2. A developer who runs a test module without the repo's `conftest.py` on the
path — a bare `python -m pytest` from elsewhere, an editor's ad-hoc runner —
gets the real `<repo>/recordings/spend.jsonl`. Harmless per run; it is the
accumulation that matters, and I have not made that impossible, only
unlikely.

---

## §9 — Owner-gated (nothing below was attempted)

1. **Decide whether a voice rejection may bypass the cost ceiling.** F1-SI
   §11 item 5, now answerable: I shipped **NO** with the reasoning in §2.4 and
   the residual in §8.2. Changing it is adding `KIND_VOICE_REJECTED` to
   `CRITICAL_KINDS` in `realtime/whisperer.py` — which also gives it the
   per-minute-cap bypass, because they are deliberately one list. Your call; it
   is a cost decision with a security flavour, not a code problem.
2. **Pick your real ceiling.** `monthly_budget_usd: 25.0` is the shipped
   default and was never enforced, so it has never been tested against your
   actual usage. One measured turn cost $0.0099 estimated; your own
   `~/.config/parcel/realtime.yaml` is where to set it, and I did not touch that
   file.
3. **Decide what to do with `<repo>/recordings/spend.jsonl` on the live stack.**
   Your running stack has been billing without a ledger, so its first
   month-to-date starts at zero on next restart regardless of what has already
   been spent. If you want the ceiling to mean anything this month, that is a
   number only you have (from the provider's dashboard), and back-filling it is
   one hand-written row in that file.
4. **`configs/realtime.yaml.example` is the example, not your config.** I
   rewrote its `monthly_budget_usd` block to describe the real behaviour. Your
   own file is untouched and still carries the old comment.
5. Standing from R23 §7.1: `configs/navigation/default.yaml`'s velocity clamp
   has the same bare-`float()` shape. Still open, still not mine.

---

## §10 — What an auditor should check first, weeks from now

1. `git log -1` — this was written against HEAD `2c27496` with an uncommitted
   tree. If the tree moved, §4's numbers are stale before anything else is.
2. `rg -n "spend_usd=" src/parcel_robot/realtime/lane.py` — if `arm()` is not
   passing `float(total.usd)`, the audit's defect is back and seed S1 is the
   test that should have caught it.
3. `.parcel/bin/python -m pytest tests/test_realtime_spend_budget.py -q` — 34
   tests, ~0.5 s, no network.
4. `<scratchpad>` paths in §6 and §7 are `/tmp` and **will have evaporated**.
   The seed harness is reproducible from the table (target file + the exact
   anchor is in `seed_r25.py`, which is also gone); the live report's contents
   are quoted inline here precisely because of that, and the audit's own §Ops
   bullet about status docs citing `/tmp` paths is why I inlined them.
