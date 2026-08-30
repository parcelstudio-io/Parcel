# NAV-INT-1 amendments — POST-START (written 15:41 08-29 from parcel-6c's code-verified lens; the executor had begun the harness). Labels and one mechanism; no criterion moves.

## N1 — "resume" is a RE-ISSUE (mechanism, binding)
There is no executive suspend/resume API: `brain/executive.py` has `submit`,
`replace` (defers to the next checkpoint unless interruptible), and
`request_interrupt` ({interrupt_now, at_checkpoint, when_idle}). Suspend /
resume live inside the runtime's amendment transaction:
`runtime._apply_goal_amend` (≈ :4381) engages a HOLD and parks amendable work
as a `ResumeIntent` via navigation `pause()`; when the replacement plan is
accepted, `_close_amendment_window("committed")` (≈ :3594) CONSUMES the
parked intent — only a rollback restores it. Therefore the harness
plan-queue policy (H-NI1b) must capture the ORIGINAL directive text itself
(its own record, or the last closed transaction journal ≈ :2248) and
RE-ISSUE it through `handle_text` after the amended goal's terminal
receipt — a fresh task and revision, navigation from scratch, NOT a resume.
Report it under the label **"re-issue"**; keep the path-length-ratio row.

## N2 — admission latency is admission-at-any-poll (label)
The runtime adapter reports every in-progress poll as a checkpoint
(`ControllerCheckpointV1` absent), so "admission within 1.0 s" measures
admission at any poll, not at a controller-certified safe point. Label the
row exactly so.

## N3 — sim hygiene (binding)
Sims launched by research scripts are NOT covered by `tests/_sim_guard.py`;
a `systemd-run` scope does not die with its parent shell. Trap teardown: kill
your own sim process group on every exit path (normal, exception, signal),
and verify with `pgrep -f "parcel_robot.sim --socket .*ni1"` at the end of
run.py that nothing of yours survives; record the check in RESULTS.md.

## N4 — name-scan (binding)
Any generated utterance or narration text that names a place must use only
names that pass the runtime's `_curiosity_admitted_names`; never the NAV
evals' held-out scene name anywhere in the folder.

## N5 — two admission paths, reported separately (POST-START, from the design review 16:05)
The C8 transactional amendment engages only when the utterance carries an
amend cue (`actually | instead | no, | change that/course | correction |
rather | not that one | the other`); a bare second directive is
`submit()` + `request_interrupt(source="correction", at_checkpoint)` that
CANCELS the first task at its next checkpoint — no HOLD, no suspend. Split
the revise family: `amend-cue` (≥ 12) vs `explicit-directive` (≥ 12), plus a
bare-"actually" HOLD row. Per episode record `agent.last_brain_metrics`
(`closed_intent`, `goal_amend_ok`, `goal_amend_replan`) and the executive
receipt kinds (`suspended:goal_amend` → `replacement_activated` for C8;
`cancelled_at_checkpoint` + new task for explicit). Admission latency =
`handle_text` entry → first suspend/replace/submit receipt (monotonic).
Record `use_llm=False` and reasoner "none (local sketch lane)".

## N6 — switch-window instrumentation
Poll `runtime.snapshot()['obstacle_distance_m']` and `['collision']` at
≥ 10 Hz from cue − 2 s to cue + 10 s; per-episode minimum clearance;
collision = min clearance ≤ 0 m (state the band if the stop band is used).
False arrival = the e2e's authority category (system succeeded ∧ K0 false)
on the final goal, AND goal 1 never marked succeeded at the switch. Write
into the criterion: n = 40 detects only rates ≥ 7.5 % (rule of three).

## N7 — H-NI1c is scored on a BLIND set
The classifier is the executor's; the 60-case gold (+ ≥ 10 adversarial per
class) is the VERIFIER's, authored blind, frozen by sha256 in
`gold_blind.json` BEFORE the classifier runs (see `gold_blind.sha256`).
Do NOT author your own gold; report the per-class confusion matrix and a
held-out-phrasing subset; the 0.9 bar applies to the blind set only.

## N8 — CIs and the path reference
Wilson/bootstrap 95 % CIs for admission, success, return; criteria are read
on point estimates with CIs shown. H-NI1b's reference = the oracle path
start → interruption pose → goal 2 → goal 1 (SPL-style from the actual
interruption pose), stratified by trigger fraction.

## N9 — the queue policy is PRE-runtime
Classifier first; `queue` utterances are HELD in the harness (never reach
`handle_text`) until the current task_id reads succeeded/failed in
`task_executive.snapshot()`, then the held text is issued as a new task;
"return" = a new task id (re-issue, N1); path ratio over the two fresh
missions. `navigation_directive_from_text` does not strip "after that".

## N10 — shape the tier as an additive NAV_INSTRUCT-style record
`interrupt_tier_v1.json` follows the generator's record schema (goal 1
crossed with the 5 families where the demo city allows and ≥ 3 tiers;
`frozen_baseline: false`; stays in this folder; frozen digests untouched);
report SR/SPL under the v4 recipe's budget policy so a later `v4i` tier can
adopt it. If time allows, ≥ 10 dynamic-city episodes via the e2e's
`live_dynamic` pattern.

## N11 — environment
Always `--socket <own short path>` (never the default `/tmp/parcel_sim.sock`);
HY-1's guard verbatim (`start_new_session`, killpg after confirming the
group, `try/except BaseException` around `build_runtime`);
`PARCEL_MEMORY_PATH` → scratch; `PARCEL_REALTIME_SPEND_LEDGER` →
`~/.cache/parcel-0e/wave20260829/spend.jsonl` even though this experiment
makes no hosted call (the runtime otherwise resolves the ledger to the
owner's `recordings/spend.jsonl`).
