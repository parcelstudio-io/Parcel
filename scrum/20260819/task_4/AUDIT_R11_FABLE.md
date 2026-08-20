# AUDIT — R11 "the situational whisperer" · Fable

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_4` (revised on bench
evidence; owner cost knob added by ruling) · **Verdict:** **ACCEPT_CLOSE.**

## Independently verified

1. **Gate, auditor's own run: PASS, 6601 passed** (+115 over R10's close,
   0 removed), ruff `new 0`.
2. **All 36 seeds re-run solo: 36/36 RED, restored** (harness self-verifies
   restoration).
3. **The design is the bench's winner, verbatim:** `whisperer.py` carries a
   typed StateDigest (no free-text field — nothing for a downstream to
   parse), the two bands, the three deterministic mechanisms, caps + dedup +
   folding OUTSIDE the bands, deterministic HINTS templates, the pace
   watcher, and a decision log recording every forward AND suppression. No
   LLM anywhere in the path; the config seam awaits evidence per the
   synthesis.
4. **The owner's knob is real and fail-closed:** `whisperer.enabled` /
   `max_updates_per_minute` / `min_gap_s` in the realtime yaml, documented
   in the example file, snapshot-exposed (`updates_this_minute`, folded
   counts) so the panel shows what it suppressed.
5. **The motion gate is narrow and held in production:** lane's
   `_response_provenance` tag (set by `narrate_event`, reset by owner
   turns) + the broker refusing motion-class tools on system-initiated
   responses — and E1's combined run recorded `system_initiated_responses:
   12, system_initiated_tool_calls: 0`. The bench's C1 hazard is dead.
6. **Verifier CLEAN.** One wording imprecision worth recording: "the always
   band forwards instantly" is true of its CRITICAL subset (safety,
   terminals, refusals — cap-exempt per the owner's knob spec); battery
   state and pace_mismatch ride the caps. That is the correct design (the
   owner's cost ceiling stays a true ceiling); the doc's sentence was
   sloppy, the code is right.

## Carried forward

E1's run-with-me failure traced to the pace watcher treating a `None`
`owner_speed_mps` as "still running" and writing NO decision row — the one
place the decision log has a blind spot. Filed as its own defect card
(dispatch after the owner's session); the fix must also pin "every tick
writes a row or a counted skip". The Ministral seam stays EMPTY: E1's only
whisperer miss was this implementation bug, not a class-rule gap — the
deterministic design's trigger condition has not been met.
