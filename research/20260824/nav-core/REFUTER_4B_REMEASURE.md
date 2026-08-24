# Refuter 4b — operator-path re-measurement (Fable, verifier) · 2026-08-24

Trigger: parcel-6c's second lens (CONCUR-WITH-NOTES,
`~/.cache/parcel-verify/navcore-4b-lens/VERDICT.md`) found that the harness's
operator rescue passed `self.body.pose` (live truth) on EVERY tick ≥ 12 s —
158-event journals, 79 silent re-arms: functionally auto-resume under
ambiguity, and the RESULTS prose ("re-armed cleanly") under-reported it.

Fix (harness only, `arms.py`): the operator's statement is a ONE-SHOT
transaction — stated pose captured exactly once at the rescue tick, one
journalled `try_rearm_by_operator` attempt; afterwards only the margin path
may re-arm. `bench.py --stage refuters` re-run in full (all refuter rows
regenerated; non-operator rows unchanged in kind).

Re-measured operator rows (3 seeds × 2 arms, `results/refuters.json`):
journal exactly **3 events** per episode (`latched` at t=0.9 s on
`global_match_ambiguity`, margins 0.0004–0.0038; `rearmed` once at t=12.0 s
by the operator transaction; re-`latched` by standing ambiguity);
post-kidnap path **0.14–0.32 m** (the bounded motion one re-arm allows);
**0 false arrivals, 0 contacts**; every episode ends **latched**
(`failure_type` `arming_latched` / `verification_failed`).

Reading: in a world that remains globally ambiguous, one operator statement
re-arms once and the ambient-ambiguity latch correctly re-fires — the dog
holds. The earlier "~2.2 m clean re-arm" was the oracle-feed artifact. A4
path (b) evidence now means: the transaction works once and does not become
a standing authorization; guidance through a persistently aliased space is a
different (operator-continuous) mode that M1 does not ship.

Unexercised and now owed (lens note 2): the **normal-layout kidnap-onset**
catch — jump/mismatch detection via JUMP_BOUND with the robot armed and
moving — no journal anywhere fires `localization_jump_m`. Adopted as an A3
acceptance criterion and proposed as a NAV-CORE v3 row.
