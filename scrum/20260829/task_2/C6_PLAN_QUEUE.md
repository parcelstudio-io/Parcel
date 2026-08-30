# C6 · PLAN-QUEUE-1 — a plan queue with lineage on the executive (queue / revise / keep)

**Executor:** Opus · **Verifier:** Fable · **Wave:** B — `brain/executive.py` and `runtime.py` are in the OWNER's uncommitted diff; this card starts only after the owner lands or discards it. Design now, implement then.

## Defect (NAV-INT-1)

There is no plan queue: an owner-referring amendment suspends goal 1 and cannot admit the replacement (robot parked); a held queue utterance re-issued verbatim is refused (the cue must be stripped); "resume" is a re-issue that costs 1.3–1.5× the oracle path because `_apply_goal_amend` (`runtime.py` ~4381) parks a `ResumeIntent` consumed on commit. The executive has `suspend_task` (`executive.py:1362`) and `resume_task_running` (`:1287`, restores without re-dispatch) but no queue POLICY. Evidence: `nav-interrupt-1/VERDICT_FABLE.md` items 1–4; `model-a-stream-1/RESULTS.md` §5 seam appendix.

## Design (write now as `C6_DESIGN.md`; implement in wave B)

- One record schema per plan: `{plan_id, lineage: new|revise|queue|keep, parent_id, goal, state: accepted|running|blocked|completed|failed|cancelled|resumed, receipts[]}` — DMC-1's fact taxonomy.
- `queue` = suspend current (state preserved via `ResumeIntent`) + admit next; on completion, `resume_task_running` the parent (no re-dispatch); `revise` = `replace` on the same task id; `keep` = no-op with a receipt.
- Amendment admission: cue-robust (strip "actually / wait / instead"), owner-referring amendments admitted.

## Acceptance (verbatim bars, wave B)

NAV-INT-1 tier: instruction admission ≥ 0.9 (24/32 today), amended success ≥ 0.8 (11/28 today), queue no longer a re-issue (resume path ratio ≤ 1.1×, 1.49 today), the two live defects' rows green; `tests/test_executive*.py`, `tests/test_voice_nav_e2e.py -k amend` through the guard.
