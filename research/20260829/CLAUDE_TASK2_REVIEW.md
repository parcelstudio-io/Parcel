# Independent review of Claude Task 2 (`FIX-SUBSTRATE-1`)

**Review date:** 2026-08-30
**Decision:** reject the integrated Task 2 work as mount-ready. Retain C7 as an
evaluator correction and C4/C5 as tested leaf prototypes only. Autonomous
physical motion remains **NO-GO**.

This is an independent current-checkout review, not a summary of the card
authors' status files. The separately linked Claude artifact could not be read
without authentication; this review covers the local code, retained artifacts,
and guarded executions available in the checkout.

## Card decisions

| Card | Independent result | Decision |
|---|---|---|
| C0 mutation panel | Initial guarded review: **2 failed, 9 passed**; the artifact was stale and `reactive_gate_disabled` survived. Post-review remediation pinned the 125-row v4 matrix digest, retained the prior five witnesses, added four clean intervention rows, and added exact gate-coverage counters. Two full nine-row campaigns matched after timestamp removal: clean authority 9/9 agreement, 0 collisions, 162 changed translating requests, 7/7 mutants killed, no survivor/equivalent. Focused freshness/hard-safety integration then passed 22 tests. No row exercised a hard stop. | Reject the original evidence; accept the repaired current panel as an eval substrate only. Hard-stop and physical safety coverage remain open. |
| C1 POI oracle | The isolated experiment removed generated-scene `crosswalk_a` grounding (90/90 → 0/90), false arrivals (41 → 0), and reached strict success 55/90 = 0.6111 with zero collisions. Shared-tree result was 54/90 = 0.600. However admission uses process-global “latest loader wins” scene state, changes the literal geometry-backed card, modifies config despite its scope constraint, and produced 11 isolated regressions before late test edits. | Retain the numerical experiment; reject product adoption pending an explicit per-navigator world/map identity seam and full guarded regressions. |
| C2 settle/arrival | Five-frame settle observation exists only in the headless harness. Product runtime and its executive adapter do not use it. Corrected rescore improves authority disagreements 16/80 → 10/80, missing the ≤2/80 bar; bench remains 10/29 rather than 0/29. | Reject product claim. Instrumentation is useful, but one runtime-owned arrival authority is absent. |
| C3 stall attribution | Enabled arm reduces non-POI stalls 43 → 10 with zero collisions, but `semantic_target_unreachable` increases 59 → 88 and strict success remains 335. Shipping config leaves the feature disabled; held state is mission-global, not candidate/epoch-scoped, and the default watchdog is about 20 seconds. | Retain attribution research; reject as rapid pedestrian-clear recovery or product capability. |
| C4 plan-acceptance narration | Guarded leaf selection passed 123 tests. The runtime never calls `note_plan_accepted`, and reroute capping is keyed by a human goal phrase rather than task identity. | Accept leaf module only; reject production claim. |
| C5 speech acts | Guarded leaf selection passed 91 tests. The 180-turn research arm reports grounding 1.0, coverage 0.9688, invented 0. Product config explicitly marks speech acts inert and the lane remains text-only. | Accept leaf module only; reject production claim. |
| C6 plan queue | No implementation or acceptance run exists. Runtime replaces a correction or submits a new plan and requests interrupts; it does not implement queue/keep/resume-parent lineage for “sofa, then resume door.” | Reject/unimplemented; this directly blocks the user's exemplar behavior. |
| C7 harness truth | Failed-receipt arrival language improves 10/10 → 0/10, receipt sequence stays 5/5, offline false arrivals improve 6 → 0, agreement 63 → 69, and six targeted sidewalk cases are 6/6 agreement. | Accept as scoped evaluator correction only; it changes no product queue or arrival authority. |

## Severity-ranked blockers

1. Queue/revise/keep parent lineage is absent, so a companion cannot reliably
   suspend the door task, inspect the sofa, and offer/resume the door task.
2. Arrival settle/receipt authority is not composed in product runtime and its
   current disagreement rate misses the registered bar by 5×.
3. POI admission lacks explicit per-navigator world/map identity and has
   unresolved regressions.
4. Stall recovery is disabled, slow, and not tied to blocker candidate/epoch or
   explicit gate-clear evidence.
5. Plan-acceptance and receipt-typed speech leaves do not reach the real
   activation/audio boundary atomically.
6. The repaired C0 panel exercises slowing but no nonzero-to-zero hard stop.

## Acceptance path

Before even treating the navigation/conversation substrate as ready for
motors-disabled HIL evaluation:

1. add a designed hard-stop mutation witness to the now-current C0 panel;
2. pass world/map identity explicitly into each navigator;
3. make one typed runtime/executive receipt the only arrival authority;
4. implement candidate-scoped clear/retry hysteresis from actual reactive-gate
   feedback;
5. implement C6 queue/revise/keep lineage and parent-resume offers; and
6. wire C4/C5 to real plan activation, generation epochs, provider output, and
   speaker cancellation before rerunning the complete C2/NAV-INT tier.

No Task 2 result supplies physical Go2/Orin timing, sensing, braking, balance,
or independent E-stop evidence.
