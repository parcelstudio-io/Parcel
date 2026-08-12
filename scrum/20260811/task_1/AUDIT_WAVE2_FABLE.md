# Fable audit — Wave 2 (VS-1..VS-6), 2026-08-11

Pre-registered protocol; adversarial verify mandatory on VS-4 (record §7).
Base dd2e857 + Wave 1 + AF-1 + Wave 2, uncommitted. Fable's own fresh
`ci_gate --tier commit`: **PASS — 3594 passed, every hard gate green.**

## Verdict

**VS-1, VS-2, VS-3, VS-6: CONFIRMED.**
**VS-4: RETURNED — one BLOCKING defect** (revision-ledger usurpation on the
refusal path) **+ three should-fix**, all dispatched to mini-lane **AF-2**.
**VS-5: CONFIRMED-with-corrections** (the effect-gate STOP stands as an honest
and valuable negative result; two methodology corrections dispatched to AF-2).

The wave's substance survives: the B-05 wrong-instance false arrival is
structurally closed on the eval path, the phantom chain
(commit→refute→suppress) works live, the value map is evidence-fed with a real
delegation proof, and the measured bottleneck for ranged search moved from
"search policy" to **planner reach** — a finding that redirects the roadmap
(route_memory / long-horizon routing is now the measured next capability).

## BLOCKING — VS-4's refusal flush usurps the revision authority

With the flag on, one lock-on refutation can **permanently veto every later
semantic commit for the task** on the runtime product path:
`_flush_lock_on_proposal` self-commits `plan_revision+1` into the shared
ProposerBus/GoalArbiter ledgers — but revision authority belongs to the
EXECUTIVE (the P0-C discipline). The runtime restamps the navigator with the
executive's (lower) revision on every nav start/resume and plan-accept; from
then on every published goal is "stale", the arbiter returns None, and the
mission dies `arbiter_veto`. The ledger never lowers, so it does not self-heal.
The auditor ran an executable repro (commit rev 1 as pipeline, publish at rev
0, resolve → None). Invisible to every gate because the eval harness never
constructs a runtime — exactly the class of gap the independent audit exists
for. **Fix direction (AF-2, binding):** the pipeline must NOT bump revisions;
the refusal purge must be revision-neutral (an explicit buffered-proposal clear
on bus+arbiter for the active task) or routed through the executive's
authority. The P0-C contracts may be amended with provenance if a
`flush_task()` API is the honest shape.

## Should-fix (AF-2)

1. **The verify-bypass shell is wider than `towards`.** `next_to`'s K0 outer
   edge (R+1.5) exceeds the outermost checkpoint (R+1.32) by 0.18 m — an
   arrival claimable with zero checkpoints due; and `near`'s metadata
   `relative_band` override can reopen the same gap. **Fable authorizes the
   VS-1 contract amendment** (with provenance): the checkpoint derivation must
   include the active relation's K0 outer band edge as the first checkpoint,
   so no relation can claim arrival with zero checkpoints due. One derivation
   closes towards + next_to + metadata-near.
2. **FP-memory keying is nearly inert against the dominant refutation class**:
   refinement refusals record at the ESTIMATE's cell but admission consults
   the CANDIDATE's cell, so a wrong reference >~1–2 m from its estimate is
   re-committed and re-refuted, burning the replan ladder (corroborated live:
   24 refutations, 1 suppression). Record refutations at BOTH cells (or
   consult at both) — fail-safe direction preserved.
3. **Re-anchoring vs the frozen reference**: `_reanchor_landmark_goal`
   translates goal/region/candidate under drift but never the verify session's
   `GroundedReference` — under real frame drift the object gate would falsely
   refute a healthy commitment and self-suppress the true target for ~30
   views. Translate the session reference in the same re-anchor transaction.
   (Static-sim invisible; hardware-relevant; retract-only so safe-direction.)
4. **VS-5 partition circularity + comparator scope**: add the independent
   control the auditor specified (partition keyed off a flag-off replay, and
   state the note-channel exclusion explicitly in the claim); document the
   scan-viewpoint side channel; pin the digest-recipe corrections (the
   ee234c63 recipe as documented does not reproduce; the payload shas are
   serializer-unpinned — record the exact recipe or drop the numbers).
5. **v4s docs must pin the matcher arm**: the "unfindable flag-off" property is
   matcher-relative (SigLIP-on: LA SR 0.100, false arrivals 0 — independently
   reproduced). State the arm in the cells' docs and W2_EVAL_STATUS.

## Notes (recorded, no action this wave)

- The OLD defective arm (`detection_lock_on` ON, verify OFF) remains reachable
  — record-compliant (flag-conditional changes) and honestly reported. AF-2
  adds a loud construction warning; whether to hard-refuse the combination
  joins the owner flag-decision item.
- Failed-mission session lifecycle: ladder-spent branches leave the session
  alive on a failed mission; harmless under current callers (start() clears),
  pinned as a note for the next pipeline card.
- VS-4's out-of-OWNS count pin (3→4, exact, card-named): **ACCEPTED**.
- VS-5's five fixture corrections: strictly reclassification, no assertion
  weakened (diff-verified): **ACCEPTED**, with the one semantic-shift case
  noted in the audit trail.
- VS-6 additivity independently confirmed (4 sentinels at pins, v4 diff empty,
  v4s reproduces); the VS-4 ledger-append incident verified fully reverted
  (ledger byte-equal to dd2e857).

## Owner decision queue after this wave (consolidated)

1. Jerk: accept 1.0813 (flag on) vs hold OFF. Fable's leaning: accept.
2. H-1: publish people to the planner (makes person-aware nav live; moves
   frozen rows — same authorization class as the v4 re-freeze).
3. pedestrian_group 0.75 band gate: refused as provably unreachable; Y-4 memo
   prices the options.
4. **NEW — SigLIP as default-on matcher**: real matching lifts baseline search
   (LA 0.000→0.100) and zeroes its 10 false arrivals; the alias fallback
   ("tree"→lamppost) is actively harmful where weights exist.
5. **NEW — planner reach**: the measured bottleneck for ranged search
   (~8 m costmap vs 12+ m sensing). The deferred route_memory /
   long-horizon-routing lane is now evidence-backed, not speculative.
6. Flag-flip decisions (value-map, lock-on+verify) once AF-2 lands — plus
   whether the defective lock-on-without-verify combination should be refused
   outright.
