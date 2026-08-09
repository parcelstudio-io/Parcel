# task_2 · Opus cleanup status (2026-08-06)

## Lane
Existing tests + minimal product honesty for K6 PlanIR admission replies.
Did **not** flip the pedestrian-traffic e2e xfail (social planning owns that).

## In-flight reds fixed (6/6)

| Test | Root cause | Fix |
| --- | --- | --- |
| `test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts` | MoveRelative ack is `_plan_acknowledgement` ("bounded move"), not the old "5 small steps" spatial string | Assert new admission ack; keep move + intent checks |
| `test_runtime_text_commands_switch_follow_and_stay` | FollowFormation fail-closed on missing heading; dispatch async; Hold didn't stop follow; sketch distance 1.5 < keepout 1.60 | Seed heading; `_step_brain`; `_brain_hold` preempts follow; sketch default 1.9 m |
| `test_runtime_streaming_text_executes_only_final_transcript` | Same follow admission/dispatch path | Seed heading + `_step_brain`; expect local_plan_sketch behind ack |
| `test_runtime_navigation_persists_and_manual_control_preempts_it` | NavigateTo inside ack renamed | Expect "Okay—I'll move onto crosswalk…" |
| `test_social_affect_action_defers_until_navigation_finishes` | Same nav ack | Same |
| `test_direct_semantic_navigation_reports_search_without_resolved_goal` | Recovery note renamed `semantic_search_scan` → `scan_behavior_dwell` | Accept new note (keep searching / unresolved goal) |

## Minimal product honesty (not admission weakening)

1. **`RobotRuntime._brain_hold`** — PlanIR `Hold` now preempts follow/nav/search/activities (stay means settle), instead of `stop_motion`'s spatial-only preempt.
2. **`_plan_acknowledgement(hold)`** — "Okay—I'll stay here."
3. **`sketch_follow` / `sketch_come` default `distance_m=1.9`** — matches `FollowOwnerController.behind_distance_m` so admitted plans don't die at dispatch (`1.5` was below keepout+0.05).

Fail-closed admission unchanged: heading / camera / lidar / emergency still reject with named replies.

## Fable M1 BINDING: FIX (2026-08-06)

Sol must-fix upheld: `_brain_hold` STOPed channels but left `_resume_store` intents, so a prior pause could resurrect follow/nav after settle.

- **`_brain_hold`** — after settle preempt, clear `follow` / `navigation` / `search` ResumeIntents (Hold remains destructive settle, not PAUSE).
- **`set_behavior("stay")`** — same clear (sibling settle path).
- Regression: `test_brain_hold_clears_resume_intents_and_blocks_follow_resurrection` (+ stay sibling).

## Verification

```text
.parcel/bin/pytest tests/test_runtime.py -q
→ 49 passed

.parcel/bin/pytest tests/test_runtime.py tests/test_resume_transaction.py -q
→ 56 passed

(prior suite, still green from earlier task_2 work)
.parcel/bin/pytest tests/test_runtime.py tests/test_intelligence.py \
  tests/test_navigation_admission_regression.py -q
→ 84 passed

(+ fallout from hold ack)
tests/test_runtime_brain_integration.py included → 89 passed total with the suite above
```

Pedestrian-traffic voice-nav e2e xfail left alone.

## Files changed

- `src/parcel_robot/runtime.py` — `_brain_hold`, hold ack; M1 resume-store clear on Hold + stay
- `src/parcel_robot/voice/local_plans.py` — follow/come distance defaults
- `tests/test_runtime.py` — `_seed_owner_heading`, updated 5 tests; M1 Hold/stay resume clear regressions
- `tests/test_intelligence.py` — scan note assert
- `tests/test_runtime_brain_integration.py` — hold ack fallout (3 asserts)
- `scrum/20260805/task_2/OPUS_STATUS.md` — this note
