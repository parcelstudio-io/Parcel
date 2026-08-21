# Task 5 — R26: the tier that never ran

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Trigger:** full-audit CONFIRMED major (§Tests-1/2): the 42 deselected
tests include **the entire voice-to-nav end-to-end tier**, and the nightly
mechanism meant to run them has never produced a recorded run — so the
gate's 7,000-plus green has never included the e2e path. Compounding it,
three load-sensitive wall-clock tests sit INSIDE the hard commit gate with
no owning card, having reddened at least six gate runs across four cards
(the register itself says "nobody owns them").

## Work

1. **Stand the nightly up for real:** a runnable entry point
   (`scripts/run_nightly.py` or a documented `ci_gate --tier nightly`)
   that runs the deselected e2e tier plus EV-1's nightly judge runner and
   writes a DATED run folder with the same evidence shape as the eval
   packs. "Never been run" must become "here is the run".
2. **Run it once, for real, and fix or file what it finds.** A first
   nightly that reveals failures is a success; record every failure with a
   verdict (fixed here / carded / environmental) — do not paper over.
3. **Relocate the load-sensitive tests:** the three wall-clock tests move
   out of the hard commit gate into the nightly tier (where load is
   controlled) OR gain a load guard that skips-with-a-named-reason under
   contention. Either way they get an owner in the register and stop
   reddening unrelated cards' gates.
4. **Document the tier map** in the status doc: what runs in commit, what
   runs nightly, what runs per-release, what never runs and why — the
   audit could not answer this from the repo.
5. **Hunt the time-bomb class** (found 2026-08-21, fixed in
   `tests/test_scene_and_memory_answers.py`): a test that mixes the REAL
   clock with a PINNED clock is not flaky — it passes until a calendar
   boundary and then fails forever. `test_a_read_only_store_still_answers
   _the_owners_question` wrote a row with SQLite's `CURRENT_TIMESTAMP` and
   recalled it against a fixed `PINNED_NOW`, so it began failing every run
   the day the calendar passed the pin. Flake inventories cannot see this
   class because it has not fired yet. Sweep the whole suite for
   real-clock/pinned-clock mixes and date-relative assertions (`now()`,
   `today`, `date.today`, hardcoded dates compared to live stamps),
   fix or pin each, and add a guard test that reddens on a new one —
   e.g. a suite run under a faked future clock (a `--future-clock` nightly
   variant) so the next bomb fires in the nightly, not in someone's gate a
   month from now.

OWNS: `scripts/ci_gate.py` (tier plumbing only — the commit tier's HARD
gate list must not lose an entry), a nightly runner script, pytest markers
on the three tests, tests, `R26_STATUS.md`.
MUST NOT TOUCH: the assertion-evals gate EV-1 just added (extend, never
weaken), source behavior outside test markers, evals fixtures, yield.
Standard house rules.

## Definition of done

Commit gate green and UNCHANGED in coverage; the nightly RUNS with its
output committed as a dated folder; every e2e-tier failure it surfaces is
resolved or carded with evidence; ≥6 seeds RED (a deselected test silently
dropped from the nightly; the nightly's failure exit-code swallowed; a
load-guard that skips unconditionally; the commit tier losing a hard
entry). `R26_STATUS.md` carries the tier map.
