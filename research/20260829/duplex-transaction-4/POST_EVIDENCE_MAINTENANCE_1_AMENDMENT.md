# DMC-4 maintenance 1 amendment: preserve resume resource-conflict evidence

Date: 2026-08-30 UTC  
Timing: after the allow-listed static edits, before maintenance source freeze or
any maintenance run/result  
Status: **BINDING PRE-EVIDENCE CORRECTION**

Reviewing the exact diff after the lint edit exposed a pre-existing semantic
regression in the DMC-4 implementation: `resume_task_running()` still receives
the conflicting `ResourceLease` tuple, but the new implementation had stopped
copying it into `_TaskRecord.conflicts` before returning
`ignored_resources_unavailable`. Merely renaming that tuple to `_conflicts`
would make static lint green while hiding useful fail-closed evidence.

This amendment replaces the planned ignored binding with the historical and
intended behavior: bind `conflicts`, store it on the still-suspended record when
acquisition fails, and add a regression proving the blocker identity appears in
the executive snapshot without appending an accepted transition or returning a
dispatch. All other maintenance limits and non-claims remain unchanged.
