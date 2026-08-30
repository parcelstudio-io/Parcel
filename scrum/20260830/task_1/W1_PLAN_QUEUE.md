# W1 · PLAN-QUEUE-1 (C6) — queue / revise / keep lineage on the executive, resume-parent offers

**Executor:** Opus · **Verifier:** Fable · **Lens:** parcel-6c (receipt shapes) · Design already written: `scrum/20260829/task_2/C6_PLAN_QUEUE.md` (record schema, lineage, DMC-1 facts).

## Defect (NAV-INT-1, `research/20260829/nav-interrupt-1/VERDICT_FABLE.md` items 1–4)
No plan queue: an owner-referring amendment suspends goal 1 and cannot admit the replacement (robot parked); "resume" is a re-issue (`runtime.py` `_apply_goal_amend` parks a `ResumeIntent` consumed on commit) costing 1.3–1.5× the oracle path; instruction admission 24/32, amended success 11/28. The executive has `suspend_task` / `resume_task_running` (restores without re-dispatch) / `replace` (revision-compared; `defer` when parked for a checkpoint) but no queue POLICY.

## Build
1. Leaf `brain/plan_queue.py`: one record per plan `{plan_id, lineage: new|revise|queue|keep, parent_id, goal, state: accepted|running|blocked|completed|failed|cancelled|resumed, receipts[]}`; policy: `queue` = suspend current (state preserved via `ResumeIntent`) + admit next; on completion, `resume_task_running` the parent (no re-dispatch) and emit a `resume_offer` receipt; `revise` = `replace` on the same task id (higher revision); `keep` = no-op with a receipt. Steering decision comes from the existing keyword classifier (NAV-INT-1 `queue_policy.py` shape, 0.83 blind) — port it as a leaf, do not retrain.
2. Amendment admission cue-robust: strip "actually / wait / instead / after that" before grounding; owner-referring amendments ("come here", "to me") admitted through the same door.
3. `runtime.py` `_apply_goal_amend`: consult the queue policy; the `ResumeIntent` is consumed on the PARENT's resume, not on commit of the child. Confined hunk; record the dirty-diff hunk headers you avoid.
4. Receipts: every state transition files a typed receipt the whisperer (C4) and speech acts (C5) can consume; `plan_accepted` fires on ACTIVATION for a deferred replacement (task_2 C4 wave-B row 2).

## Acceptance (verbatim bars)
- NAV-INT-1 tier (`research/20260829/nav-interrupt-1/run.py`, pinned export, own sockets, `systemd-run … MemoryMax=12G`, `PARCEL_MEMORY_PATH` → scratch): instruction admission **≥ 0.9** (24/32 today), amended success **≥ 0.8** (11/28), queue no longer a re-issue: resume path ratio **≤ 1.1×** (1.49), the two live defects' rows green (owner-referring amendment admits; held queue utterance admits after cue-stripping); `gold_blind.json` sha256 `c253df2f…` unchanged.
- Unit: lineage table, deferred-activation firing, parent resume without re-dispatch, cue-stripping table; `tests/test_executive*.py`, `tests/test_voice_nav_e2e.py -k amend` through the guard.
- No `noqa`; `config.py` unchanged; executive hunks confined and listed with the avoided dirty hunks.
