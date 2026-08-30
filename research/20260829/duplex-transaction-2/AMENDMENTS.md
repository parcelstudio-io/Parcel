# DMC-2 pre-implementation clarifications

These clarifications were written after freezing `DESIGN.md` and before any
harness code or result existed.

1. In H1, "rejects an unverified success fact" means **rejects the success
   claim**. `TaskExecutive.report` is permitted to consume that report and
   transition the task to `failed`; the required disposition is
   `accepted=true, action=task_failed, state=failed`, never `succeeded`.
2. Every corruption has a frozen expected disposition, not just a Boolean.
   An integrity pass requires the exact `accepted/licensed`, reason/action,
   and state tuple.
3. A post-terminal input starts from an already terminal pre-state. Its gate
   is no *new* terminal mutation (`before == after`), rather than the
   nonsensical requirement that the pre-state not be terminal.
4. Authentication tags and keys remain process-local and are excluded from
   traces; `authenticated_by_expected_channel` is recorded as a Boolean.

## A2 — independent boundary review, after smoke and before the full run

The one-trial smoke produced no evidentiary result. An independent production
boundary review then required these stricter rules for the full population:

1. DMC-2 is two independent seam suites. It does **not** fabricate or claim a
   shipped executive-to-receipt bridge. `ActionReceiptV1` currently lacks
   task ID, revision, step, attempt, source epoch, and speech generation, and
   the runtime does not mint it from `TaskExecutive.report`.
2. Runner traces contain observations and state only—no `expected` field and
   no `oracle_pass`. The stdlib-only verifier is the sole pass/fail oracle.
3. Trace rows are hash-chained. The verifier checks inventory, row hashes,
   chain order, state hashes, exact outcomes, and aggregates.
4. The dialogue reducer starts from a directly constructed but contract-valid
   pending-state fixture. Therefore it tests reducer/claim conformance, not
   `begin_admitted_action` or admission-policy composition. This limitation is
   carried into the verdict.
5. Architecture promotion separately requires end-to-end tuple binding,
   restart/epoch replay protection, stale speech-generation rejection, and
   typed progress/suspend/resume evidence. Those are **NOT EVALUABLE / RED**
   on today's interfaces even if all seam cases pass.
