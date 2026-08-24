# A5 C8-FIX · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard run — A5 suite + r24 + nominal-stop + nm1 + executive/
runtime/preempt/pause suites + both DEC ratchets = **212 passed, 1 skipped**;
scope = exactly two product files (+504/−55) + the test + the status doc;
the hunks read line-by-line: the executive guard is STRUCTURAL
(`GOAL_AMEND_FORBIDDEN_ACTIONS` refuses `cancel_now` for any goal-amend
reason — no future policy-table edit can make an amendment destroy its own
goal), and `_apply_goal_amend` is HOLD-first → suspend (fail-closed on the
RETURNED decision, task membership, and post-state) → controller teardown →
arbiter-verified quiescence → only then `_amendment_pending`; every rollback
step journalled before taken; zero lock changes, zero marker changes, zero
re-pins.

## Disposition: **ACCEPTED — the C8 BUILD_BLOCKER is cleared**

- The regression watches the command stream, not task records: the headline
  row shows `ControlManager.set_target` going silent over 5 ticks with the
  arbiter empty; the multi-task forced-partial-failure is observed from
  INSIDE the window (under the held `_command_lock`), with the first task
  resumed, the amendment refused, and an exact 11-row journal.
- Controller teardown was correctly identified as the missing half of the
  live defect — suspending a record does not stop a spatial behavior — and
  the abandon path repairs a second real defect (RESUME previously stranded
  the mission behind a window nobody could close).
- Seeded-red discipline is exemplary: the exact pre-fix C8 defect
  (teardown dropped) reddens 11 rows including the headline; product-file
  seeds applied and reverted with sha verification.
- Whole-tree: 10,277 passed; every failure reproduced at pristine HEAD by
  a hash-verified working-tree revert — the correct attribution method.

Consequence: connected replanning and the CONNECTED-PLANNER probe are no
longer build-blocked (the probe still waits on the owner's compound-
instructions decision). Undone, accepted as recorded: spatial behaviors
cold-start after a refused amendment (no `ResumeIntent` of their own);
`activities` stays outside the targeted-source map for the reason given
(shared `voice` arbiter source); the journal lives on metrics, not the
panel. Does not prove: anything physical; the executive-suspension window
has never been exercised against a real body.
