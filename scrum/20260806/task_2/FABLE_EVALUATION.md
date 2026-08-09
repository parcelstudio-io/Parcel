# Fable evaluation — slim NAV_E2E delivery (Opus, 2026-08-06)

**Verdict: APPROVE. No changes requested.** All claims verified against the
tree, not the report.

## What was verified first-hand

| Claim | Verification | Result |
|---|---|---|
| Default suite 2016 passed / 0 failed | full `-m "not slow"` run | **confirmed** (2016/2 skipped, 59.9 s) |
| New unit/API tests | ran all three new/touched test files | 62 passed |
| e2e outcomes | live re-run of come-here, sit-lamppost, honesty cases | **pass / xfail / pass — identical to report**, xfail reason string precise |
| Router fix trust boundary | read `brain/router.py` | rule fires only when `parse_closed_intent` itself recognizes COME (no second grammar); routes `direct_skill` → system registry — correct because the sketch IS system-authored; not reachable from model output |
| Predicate purity | scoring.py imports | stdlib + geometry constant only |
| Backlog honesty | N12 / N13 / U33 entries | present; N12's fix direction correctly names the one-authority rule (owner is a tracked entity, not a map object — bridge to the approach lane, avoid the D5 two-resolutions class) |

## Judgment on the discretionary decisions (all endorsed)

1. **Facing report-only in v1** — right call: gate after measuring the
   distribution, not before; `None` (unknown) never silently becomes
   `False`.
2. **Come-here vacuity guard** — walking the owner 3 m before the case and
   asserting the start gap is exactly the discipline that keeps an
   owner-anchored predicate from passing vacuously; good test design.
3. **The in-lane router fix** — was necessary (every "come here" dead-ended
   at admission; OB-7's fix was unreachable from the product bar), was
   narrow, and was correctly escalated into U33 (the other five closed
   intents have the same never-spoken coverage shape).
4. **Four xfails over silent skips** — each with two-sided attribution and
   named fix owners; the suite now *measures* the sit/owner gaps instead of
   hiding them.

## What this round proved about the product (the owner-facing summary)

The product path now demonstrably handles: sidewalk region goals,
towards-object, **come-here approach with hold-and-release**, **orbiting
the owner (0.986 rev, 100% in corridor)**, and **honest absent-target
refusal**. The four measured gaps, all pinned and carded: "go to the
owner" phrasing can't reach the owner channel (N12, hours), "sit next to
X" compiles no Sit step (N13, hours–day), the 7 cm/0.21 m next-to-band
near-misses (N11 final-approach residual), and sidewalk-in-traffic (N11).

## Program note

Test surface moved 1971 → 2033 with zero regressions, entirely inside
existing harnesses — the slim plan delivered the owner's coverage ask at
~¼ the rejected design's cost, and the /evals voice-mode toggle closes the
UI-debugging ask on the existing panel. Sequential-by-construction holds.
