# C4 · WHISPER-ACCEPT-1 — executor status (Opus)

**Card:** `C4_WHISPER_ACCEPT.md` · **Verifier:** Fable · **Second lens:** parcel-6c
**Wave:** A (whisperer leaf + tests). The `runtime.py` install hook is **wave B** and is
NOT written here; its exact line and location are §6.
**Spend:** $0.00 hosted. No git writes. No `ci_gate.py`. No `-n auto`. No `--pdb`.

---

## 0 · Pre-flight — the off-path digest, pinned BEFORE the first edit

The card requires the whisperer's output over MB-1's 40 scenarios to be byte-identical
with no executive receipts. The digest was computed **first**, on the unmodified tree:

```
.parcel/bin/python <scratch>/offpath_digest.py     # arm D over ev.build_corpus(), bands 2 / 15.0
```

| | value |
|---|---|
| **digest BEFORE any edit** | `4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663` |
| **digest AFTER the whole card** | `4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663` |
| rows | 150 decision rows over 40 scenarios |
| totals | `critical_bypass` 65, `block_debounce_elapsed` 10, `clear_after_forwarded_block` 10, `never_band` 55, `block_debounce_holding` 10 |

The totals reproduce MB-1 `RESULTS.md` §0's published arm-D ledger row for row (85
forwarded / 65 suppressed), so the replay is faithful to `run.py --decisions`. The digest
is pinned in the test file as `OFF_PATH_DIGEST` and re-checked by
`test_the_off_path_output_over_the_mb1_corpus_is_byte_identical`.
**Nothing was written into any research folder; MB-1's modules are imported read-only.**

---

## 1 · The `KIND_REROUTE` band decision — DECIDED ON THIS FILE FIRST

> Card, check 2 (verbatim): *"Decide `KIND_REROUTE`'s band on this card before writing its
> constructor, with the spend consequence written: either move it to the normal band with
> its own min-gap, or keep it CRITICAL and cap reroutes per mission (state the cap)."*

### Decision: **`KIND_REROUTE` STAYS CRITICAL, and is CAPPED at 3 reroutes per mission.**

`REROUTE_PER_MISSION_CAP = 3` (`whisperer.py`, in the tuning constants, with the argument
below written beside it).

**Why it stays critical — two reasons, both load-bearing.**

1. The bench's disqualifying counterexample IS a reroute: *"reroute at t=96 was silently
   dropped because a mission_clear forwarded at t=90 held the 15 s min-gap — G3 missed by
   both deterministic arms"*. In this module the min-gap exemption **is** the critical set
   (`MIN_GAP_EXEMPT_KINDS = CRITICAL_KINDS | {KIND_MISSION_BLOCK_CLEAR}`), and
   `runtime._narrate_mission` reads that same set for the monthly ceiling on purpose
   ("one list, one answer"). Moving reroute out re-opens G3 **and** splits "which facts
   outrank the owner's cost knob" into two lists that can drift.
2. It is also forced by frozen evidence outside this card's OWNS:
   `tests/test_realtime_whisperer.py::test_the_exempt_set_is_exactly_the_terminal_like_events`
   asserts `MIN_GAP_EXEMPT_KINDS == CRITICAL_KINDS | {KIND_MISSION_BLOCK_CLEAR}` *and*
   `KIND_REROUTE in MIN_GAP_EXEMPT_KINDS`. Any "normal band" variant reddens a test this
   card does not own.

**The spend consequence, priced.** A reroute is not an edge like every other critical
class: it is fed from `SocialProgressStateV1.REROUTE`, a policy **state** the navigator
re-enters whenever `liveness.alternate_route_available` flips, and the only thing under an
uncapped critical class is the 20 s `CRITICAL_DEDUP_TTL_S`.

| | forwards / mission | $ / mission | $ / month @ 20 missions/day |
|---|---|---|---|
| uncapped, 10-minute trip at the 20 s dedup floor | ≤ 30 | ~$0.072 | **~$43** — a quarter of `hosted_budget.DEFAULT_ENVELOPE_USD` ($160), spent by the one path allowed to ignore the envelope |
| **capped at 3** | ≤ 3 | ~$0.007 | **~$4.3** |

Unit price ~$0.0024 per forwarded narration, from MB-1's own hosted ledger
(**$1.33 / 550 rows**, `VERDICT_FABLE.md`). Three admits a real re-plan sequence (first
alternate, one revision, a last one) — more than the one reroute per mission the bench
corpus contains.

**Mechanics.** The cap is per mission (the goal label the trip is for) and resets when the
mission changes. Over the cap the item is dropped with `RULE_REROUTE_MISSION_CAP`, still
logged, never billed. A reroute the lane's floor gate refuses gives its allowance back in
`undeliver`, for `undeliver`'s own stated reason: the allowance is spent by a sentence the
owner *hears*.

---

## 2 · What was built (`realtime/whisperer.py`, additive; §7 carries follow-up A1)

The one deleted line is `gap = float(self.config.min_gap_s)` inside `_forward`, replaced by
the per-class lookup. `_diff` is **untouched** — no `nav_goal` branch was added and none of
its existing branches moved.

| addition | what it is |
|---|---|
| `KIND_PLAN_ACCEPTED` | new class, ALWAYS band, **not** in `CRITICAL_KINDS` |
| `PlanAcceptedReceipt` | typed receipt mirroring `ExecutiveSubmission` (`accepted`, `disposition`, `task_id`, `plan_revision`) + `goal_label`, `lineage`, `plan_digest`, `receipt_id`. Mirrored, not imported: `realtime` takes no dependency on `brain`. Never raises. |
| `RerouteReceipt` | `mission`, `state`, `cause`, `blocker_id` — the `SocialProgressDecisionV1` fields the sentence needs |
| `Whisperer.note_plan_accepted(receipt)` | the door. Re-issue guard → band → dedup → own min-gap → the owner's cap |
| `Whisperer.note_reroute(receipt)` | `KIND_REROUTE`'s first constructor, enforcing the per-mission cap |
| `plan_accepted_event` / `reroute_event` | total (never-raising) event builders |
| `PLAN_ACCEPTED_MIN_GAP_S = 2.0`, `KIND_MIN_GAP_S` | the own-gap table (§3) |
| `REROUTE_PER_MISSION_CAP = 3`, `PLAN_ADMISSION_MEMORY = 32` | the two bounds |
| 7 new rules | `plan_admitted`, `plan_reissue`, `plan_not_admitted`, `plan_receipt_invalid`, `plan_acceptance_requires_a_receipt`, `reroute_mission_cap`, `reroute_door_wrong_state` |

`SocialProgressStateV1` / `SocialBlockCauseV1` are **imported**, not copied as strings, so a
rename in the navigator's contract moves this module with it (the wave's
"import the constant" discipline). No cycle: `navigation` never imports `realtime`, and
`social_progress_contracts` imports only `contracts` + the stdlib.

`config.py` is **unchanged** (it is at the DEC-0 ceiling): the own-gap number and the
reroute cap are module constants, not knobs.

### The finding this card produced: the acknowledgement must not hold the shared min-gap

Written down because it was **measured, not assumed**. The first implementation spaced
`KIND_PLAN_ACCEPTED` with its own *value* against the *shared* `_last_forward_at`. Replayed
over MB-1's corpus that loses **10/10 block reports and 10/10 clears**: the acknowledgement
lands at t=0.3, the 8 s block debounce elapses at t=13.5, which is inside the owner's 15 s,
so *"someone is standing in the way"* is suppressed and the clear can no longer prove its
block was spoken. Trading a block report for a courtesy sentence is a strictly worse robot.

So a class in `KIND_MIN_GAP_S` is spaced against **its own** last forward and does not
advance the shared clock the other classes read. The shared clock is the owner's spacing for
the robot's *unsolicited status*, which an answer to something they just said is not. The
**budget** is still shared — the acknowledgement obeys `max_updates_per_minute` like
everything non-critical. Pinned by `test_the_acknowledgement_never_silences_a_block_report`.

---

## 3 · Acceptance rows (bars quoted verbatim)

> **Unit:** *"a re-issue of the same goal (same task id, `replace` with identical plan) does
> **not** fire `KIND_PLAN_ACCEPTED`; a new goal does, once; a revise carries
> `lineage=revise`."*

**PASS.** `test_a_reissue_of_the_same_plan_is_not_news` /
`test_a_new_goal_is_acknowledged_once_from_the_executives_own_receipt` /
`test_a_revision_fires_and_carries_its_lineage`. The fake executive mirrors the shipped
`submit`/`replace` including the fact that **`replace` compares revisions and never plan
content** — so it *accepts* an identical plan at a higher revision, and the whisperer's
guard (keyed on `plan_sha256`, checked at t+120 s so it is not the dedup doing the work) is
the only thing between that and the robot saying "okay, the sofa" twice. A `replace` the
executive rejects lands on `plan_not_admitted`, not on silence.

> **Band:** *"`KIND_PLAN_ACCEPTED` obeys caps/ceiling (test with the governor at $0
> remaining: item is dropped, not billed); `KIND_REROUTE` behaves as decided (test the cap
> or the min-gap)."*

**PASS**, at both layers the product has:

* the whisperer's cap — `max_updates_per_minute=0` ⇒ `forwarded=False`, `rule=budget_exhausted`,
  `text=""`, `whisperer.forwarded == 0`. `_narrate_mission` is never reached, so nothing is
  sent and nothing is billed (`test_the_acceptance_is_not_critical_and_is_dropped_unbilled_at_a_spent_cap`);
* the month's ceiling — a `HostedCallGovernor` with a $0 envelope **refuses** the acceptance
  (`envelope_reached`, because `KIND_PLAN_ACCEPTED ∉ CRITICAL_KINDS` ⇒ `CLASS_ROUTINE`) and
  **admits** a reroute (`never_governed`, because it is critical). Same set, one layer out
  (`test_the_hosted_governor_at_zero_refuses_an_acceptance_and_never_a_reroute`).
* reroute: cap enforced at 3, the 4 over-cap items composed nothing, a fresh mission gets a
  fresh allowance, a floor refusal gives the allowance back, a non-`reroute` state is
  refused at the door, the 20 s critical dedup still folds a second reroute on one trip.

> **MB-1 corpus replay:** *"with the fake executive emitting receipts for the 40 scenarios,
> `narration_decisions` show b1 'new goal acknowledged' **75/75** from the new kind (MB-1's
> trigger table unchanged otherwise); the 2/min, 15 s band ledger unchanged for the other
> kinds."*

**PARTIAL — reported honestly, per working-agreement rule 3.** The corpus has exactly **75**
"new goal" opportunities (65 `accepted` + 10 `resumed`), and **75/75 now produce a decision
row from the new class** where today's product produces none. What each one costs is the
band's business, and the two halves of the bar cannot both hold at 2/min:

| bands | acceptance ledger | other kinds' ledger |
|---|---|---|
| **prototype 6 / 4.0** | `plan_admitted` **65**, `plan_not_admitted` 5, `plan_reissue` 5 | **UNCHANGED, row for row** (65 `critical_bypass`, 10 `block_debounce_elapsed`, 10 `clear_after_forwarded_block`, 55 `never_band`, 10 `block_debounce_holding`) |
| **shipped 2 / 15.0** | `plan_admitted` **50**, `budget_exhausted` **15**, `plan_not_admitted` 5, `plan_reissue` 5 | one row moves: 10 `clear_after_forwarded_block` → 10 `budget_exhausted`. No band moves, no mechanism changes its mind. |

Three things the verifier should check, because they are the whole of the shortfall:

1. **65 and not 75 forwarded** — the 10 `resumed` receipts are the *same plan* resuming.
   Five (`queued` family) resume T2 at the **same revision**, which the real `replace`
   rejects ("replacement revision must increase"); five (`resumed` family) resume T1 at
   revision 3 with the plan it already ran, which the re-issue guard holds. Both are correct
   for the vocabulary wave A has — a resume is a *lifecycle transition* of an
   already-admitted plan, not a new admission — and it is precisely what the card defers:
   *"lineage (new / revise / queue — from C6 when it lands)"*. `LINEAGE_QUEUE` and its fact
   template are declared and tested now so C6 has one vocabulary to produce into.
2. **50 and not 65 at 2/min** — a 40-scenario corpus that already spends 85 forwards cannot
   absorb 65 more at a two-per-minute cap. This is the class deliberately **not** allowed to
   outrank the owner's cost knob; the drops are `budget_exhausted` and are unbilled.
3. **The other kinds' displacement is the CAP, not the class** — it is zero at the prototype
   bands and bounded to a single rule (`budget_exhausted`) at the shipped ones. Pinned by
   `test_at_the_shipped_cap_the_owners_knob_is_what_pays_for_the_courtesy`, which asserts the
   exact delta rather than tolerating it.

Reproducing the transcript-level b1 score (the 75/75 in `RESULTS.md`) would need MB-1's
`run.py` fake-responder arm re-driven with the new kind, which means editing `narrate.py` in
a research folder this card may not write to. The decision-ledger row above is the closest
faithful thing; the verifier decides.

> **Off-path byte-identical:** *"with no executive receipts, the whisperer's output over
> MB-1's 40 scenarios is identical to today's (pin a digest)."*

**PASS.** Digest identical before and after — see §0.

> *"`tests/test_whisperer*.py`, `tests/test_realtime_*` subsets green through the guard; no
> `noqa`; `config.py` unchanged."*

**PASS.** §5. `grep -c noqa` = **0** in both files touched. `config.py` carries no C4 edit
(its working-tree diff is C5's `speech_acts` block).

---

## 4 · The `nav_goal` string diff, refused twice

The card's first check is that the class is fed by a receipt "never from a `StateDigest`
`nav_goal` string diff". Two tests hold that shut:

* `test_the_differ_still_has_no_nav_goal_branch` — a `nav_goal` change through `observe`
  still produces only `nav_tick`, in the never band;
* `test_the_class_cannot_be_spoken_around_its_own_door` — `KIND_PLAN_ACCEPTED` handed to
  bare `offer()` is refused with `plan_acceptance_requires_a_receipt`, the same discipline
  `RULE_MIDDLE_BAND_NEEDS_MECHANISM` applies to a block. Without it a future caller could
  reach the band table around the re-issue guard, which is the string diff back one caller
  at a time. (`KIND_REROUTE` is deliberately **not** guarded this way: `offer()` on a
  reroute is asserted by `test_realtime_whisperer.py:401`, which this card does not own.)

---

## 5 · Commands and results (all through the guard, `TMPDIR` unset)

```
~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_whisperer_plan_accepted.py -q
                                                     -> 26 passed (29 after follow-up A1, §7)

~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_realtime_*.py tests/test_whisperer_plan_accepted.py -q -p no:randomly
                                                     -> 1245 passed, 2 skipped

~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_dec0_debt_ratchet.py tests/test_p0b_companion_unlocks.py \
    tests/test_prototype_profile.py tests/test_curio1_chatter.py \
    tests/test_p2b_owner_awareness.py tests/test_r24_lock_discipline.py \
    tests/test_mission_log.py tests/test_h3_drives.py \
    tests/test_social_progress_runtime.py tests/test_unknown_place_admission.py \
    tests/test_safety_log.py tests/test_ot2_identity.py \
    tests/test_turn1_endpointing.py -q -p no:randomly
                                                     -> 579 passed, 2 failed (both foreign, below)

.parcel/bin/ruff check src/parcel_robot/realtime/whisperer.py tests/test_whisperer_plan_accepted.py
                                                     -> All checks passed
```

**The two red rows are NOT C4's** — the board's DoD allows "gate green except rows
attributed to the owner's diff", and both are:

* `test_dec0_debt_ratchet::test_no_new_oversized_module` — new offenders
  `audio/voice_loop.py`, `brain/executive.py`, `bridge/protocol.py`,
  `control/motion_gateway.py`. All four are dirty working-tree files from the owner's diff /
  other executors. `realtime/whisperer.py` is **already in the baseline** (line 125), so its
  +480 lines do not redden this row — verified by calling `measure_oversized_modules()`
  directly: `set(current) - set(baseline)` is exactly those four.
* `test_dec0_debt_ratchet::test_no_new_long_function` — `_accept_wire_state_locked`,
  `arm_and_set_target`, `build_motion_gateway_commissioned_control_manager` (`control/*`),
  `report`, `request_interrupt` (`brain/executive.py`), `from_mapping`
  (`bridge/protocol.py`), `_run_session` (`unitree_control.py`), `_transition`
  (`voice/execution_narrative.py`). None is in `realtime/`. C4's longest new function is
  `note_plan_accepted` at **52 lines**, well under the 100-line ceiling.

---

## 6 · Wave B — the install hook, exactly

**File:** `src/parcel_robot/runtime.py` · **method:** `RobotRuntime._accept_plan`
**Insert at line 3625**, immediately after the `self._emit("brain", f"Accepted plan …")`
call that closes at line 3624 and immediately before `return self._plan_acknowledgement(plan)`.
Everything the receipt needs is in scope there and nowhere earlier: `plan` (PlanIR),
`validated` (carries `plan_sha256`), `submission` (the `ExecutiveSubmission`), and `frame`
(whose `speech_act` is the branch that chose `replace` over `submit` at line 3548).

```python
        self._whisper_plan_accepted(plan, validated, submission, frame)
```

The sibling it calls is the `_whisper_curiosity` shape and belongs to wave B (it is 12 lines
and it touches `runtime.py`, which wave A may not):

```python
    def _whisper_plan_accepted(self, plan, validated, submission, frame) -> bool:
        whisperer = self.realtime_whisperer
        if whisperer is None:
            return False
        decision = whisperer.note_plan_accepted(
            PlanAcceptedReceipt(
                task_id=plan.task_id,
                goal_label=plan.goal.target.query,
                plan_revision=submission.plan_revision,
                lineage=LINEAGE_REVISE if frame.speech_act == "correction" else LINEAGE_NEW,
                accepted=submission.accepted,
                disposition=submission.disposition,
                plan_digest=validated.plan_sha256,
            )
        )
        if not decision.forwarded:
            return False
        # critical=False is not a parameter and never will be: KIND_PLAN_ACCEPTED
        # is not in CRITICAL_KINDS, so an acknowledgement can spend past neither
        # the owner's per-minute cap nor the month's ceiling.
        if self._narrate_mission(decision.text, critical=False):
            return True
        whisperer.undeliver(decision)
        return False
```

Notes for whoever lands it: `note_plan_accepted` **never raises**, so no `try` is needed
around it and none should be added — a malformed or rejected receipt is a logged suppression
row, which is what keeps a narration fault from being able to take down a plan admission.
When C6's plan queue lands, the `lineage` expression becomes the queue's own
`new | revise | queue` and `LINEAGE_QUEUE` is already declared, tested and templated.

`KIND_REROUTE`'s install is the same shape from the social-progress path
(`RerouteReceipt(mission=<goal label>, state=decision.state.value,
cause=decision.cause.value, blocker_id=decision.blocker_id or "")` →
`whisperer.note_reroute(...)` → `self._narrate_mission(text, critical=True)`), and it is
wave B too.

---

## 7 · Follow-up A1 — the shared clock's rewind (parcel-6c, second lens)

**Reported:** own-gap forwards are appended to the SHARED `_forwards` deque, and
`undeliver`'s rewind set `_last_forward_at = _forwards[-1]`. So for
`[S1@t1, plan_accepted@t2, S2@t3]`, undelivering S2 rewound the owner's spacing clock to
**t2** instead of **t1**. Before C4 every `_forwards` entry *was* a shared-clock advance, so
`_forwards[-1]` was always the right answer; C4's own-gap class broke that assumption and
left the old expression reading it. **Confirmed, and fixed.** Direction was safe (more
spacing, never less) and it was still wrong: the clock has to mean one thing.

**Fix (chosen option: the kind travels beside the timestamp).** `_forwards` is now
`deque[tuple[float, str]]` — `(at, kind)`. One deque, not two: the budget and the spacing
are the same list of events read two different ways, and a second deque would be a second
thing to keep in step with `_spent`'s eviction.

| site | change |
|---|---|
| `__init__` | `deque[float]` → `deque[tuple[float, str]]`, with the assumption that broke written into the comment |
| `_forward` | `append(at)` → `append((at, kind))` |
| `_spent` | eviction reads `self._forwards[0][0]`; **`len(self._forwards)` is untouched, so the budget count is unchanged** |
| `undeliver` | top-of-deque match reads `self._forwards[-1][0]` (still timestamp-only, so no pre-C4 behaviour moves); the shared branch rewinds to `self._last_shared_forward_at()` |
| new `_last_shared_forward_at()` | scans the deque backwards for the last entry whose kind is not in `KIND_MIN_GAP_S`; `None` when there is none. Bounded by the budget window exactly as the old expression was — a shared forward already aged out cannot be rewound to, and `None` then means "no spacing is being held", which is what the pre-C4 code answered in the same situation |

Net: **+568 / −8** on `whisperer.py` for the whole card; the 8 deletions are the one C4
min-gap-lookup line plus A1's six touched lines. `whisperer.py` only — no other file, no git.

**Tests added (3), all in `tests/test_whisperer_plan_accepted.py`:**

* `test_undelivering_a_shared_class_rewinds_past_an_own_gap_forward` — exactly the sequence
  parcel-6c named. `battery_state@t1`, `plan_accepted@t1+2.5`, `pace_mismatch@t1+16.0`;
  undeliver the last ⇒ `_last_forward_at == t1`. It also asserts the consequence an owner
  would feel: a status fact offered at `t1 + min_gap_s` is affordable again, where under the
  drift it was held for 2.5 s more. **Seeded discriminating**, shown rather than asserted —
  at the moment of the rewind the deque is
  `[(1000.0, 'battery_state'), (1002.5, 'plan_accepted')]`, so the old `_forwards[-1]`
  expression returns **1002.5** where `_last_shared_forward_at()` returns **1000.0**.
* `test_a_late_undeliver_pops_nothing_and_rewinds_nothing` — the documented case. Something
  forwarded after the decision, so its slot is not on top: nothing is popped, the budget
  count is unchanged, `_last_forward_at` stays at the later forward, and the
  `narration_floor_refused` row is still written. Pre-C4 behaviour, unchanged by A1, and the
  reason `_last_shared_forward_at` is only ever consulted on the top-of-deque path.
* `test_the_budget_slot_is_still_given_back_exactly_once` — A1 changed what the deque
  carries, not what it counts: 3 forwards ⇒ `updates_this_minute == 3`, one undeliver ⇒ 2.

**Runs (through the guard, `TMPDIR` unset).** Both were queued several minutes behind
another executor's suite on `~/.cache/parcel-guard/suite.lock` — the serialisation working
as intended, not a failure:

```
~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_whisperer_plan_accepted.py -q                     -> 29 passed
~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_whisperer_plan_accepted.py tests/test_realtime_whisperer.py -q
                                                                 -> 123 passed
~/.cache/parcel-guard/pytest_guard.sh --label C4 .parcel/bin/python -m pytest \
    tests/test_runtime_whisperer_wiring.py -q                    -> 15 passed
.parcel/bin/ruff check src/parcel_robot/realtime/whisperer.py tests/test_whisperer_plan_accepted.py
                                                                 -> All checks passed
```

`test_realtime_whisperer.py` is unmoved, and the reason is structural rather than lucky:
with no own-gap forward in the deque, `_last_shared_forward_at()` returns `_forwards[-1]` —
the identical value the old expression returned — and `_spent`'s count never changed. A1
can only differ on a sequence that contains a `KIND_MIN_GAP_S` class, which is exactly the
one class C4 introduced.

**Off-path digest after A1:** `4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663`
— **identical** to the pre-card pin in §0.

---

## 8 · Files touched

| file | change |
|---|---|
| `src/parcel_robot/realtime/whisperer.py` | +568 / −8 (C4 +480/−1, follow-up A1 +88/−7); additive; no reformatting; `_diff` byte-identical |
| `tests/test_whisperer_plan_accepted.py` | new, 29 tests (26 + A1's 3) |
| `scrum/20260829/task_2/C4_STATUS.md` | this file |

Nothing else. `runtime.py`, `brain/executive.py`, `realtime/lane.py`, `realtime/config.py`,
every owner-diff file, every research folder and every safety floor are untouched by C4.

## 9 · Does not prove

Hosted-model behaviour (no hosted calls on this card, $0). The runtime hook (wave B, §6).
The transcript-level b1 score — only the decision ledger is reproduced here. The corpus's
resume path, which needs C6's queue receipt. `RerouteReceipt`'s producer: the social-progress
policy's `REROUTE` state is not yet wired to any door, so `KIND_REROUTE` has a constructor
and still has no caller until wave B.
