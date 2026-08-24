# NAV-CORE v2 · VERDICT (Fable) · 2026-08-24

Basis: RESULTS.md read in full against the DESIGN (byte-identical to its
committed v2, refuter 4b included); `results/{corpus,refuters,
stall_mechanism}.json` spot-read; `tests/test_navcore_probe.py` (4 passed) +
both DEC ratchets (27 passed) re-run through the guard by the executor on
this tree; the door path is the PRODUCT hosted rail (broker → admission →
router → sketch → `_accept_plan`), not a synthetic goal feed — the strongest
product-path coupling any study in this program has had. No criterion moved;
the executor stopped at the decision without tuning (refused even the cheap
`map_safety_margin_m` sweep past one sample). $0, no servers, git untouched.

| row | disposition |
|---|---|
| N1 (A 0.00, B 0.48 vs ≥ 0.80) | CONFIRMED — both arms fail; the numbers are corpus-wide, seeds fixed, room clearances audited (≥ 0.88 m, reachability pinned by the probe test), so a miss is the navigator's |
| N2/N3 (0 false arrivals, 0 contacts) | CONFIRMED |
| N4 (A 0.45, B 0.00 typed non-arrivals vs 1.00) | CONFIRMED — the silent-stall class is real in both arms |
| N5–N7 | CONFIRMED as reported; N7's honest framing (the ladder's benefit was unobservable on this corpus, its cost measured at 29 arrivals) is accepted |
| R1/R2/R4 | CONFIRMED — with the valuable mechanism note that the R1 HOLD comes from the reactive gate, not the controller (grid_v1 ships `safe_valley_micro_advance=False`) |
| R3 | CONFIRMED-WITH-NOTE — the false arrival (p = 0.9922, truth 0.534 m) is 1 of 3 seeds; small sample, but it is a measured instance of H7-L5's uncalibrated covariance reaching an ARRIVAL claim, which upgrades that refutation from "contract gap" to "wrong answer produced" |
| R4b | CONFIRMED — both shipped arms translate on HEALTHY after the kidnap (bar failed); the A4/A10 latch model holds 3/3 at 0.00 m; path (a) correctly refuses in the aliased world; path (b) re-arms cleanly. The latch and margin are HARNESS MODELS — no product code implements them (defect 4: `_relocalize` keeps no runner-up) |
| decision | CONFIRMED as pre-registered: arm C fires; **delegation refuted** (all defects are Parcel glue; 8/8 stalls inside Parcel's own brake rings with the route planned); topology decision DEFERRED to the frozen-corpus re-run after the glue fixes |

**Overall: CONFIRMED.** The five product defects are adopted as build items
(plan cards A2/A3), with one refinement the executor measured and my plan's
first draft understated: **defect 3 is not a parameter wire** —
`ReactiveSafetyPolicy.planner_inflation_m` has no call site AND passing it
does nothing because `_planner_coupling_ring_m` caps tighter-only by design
(pending DOOR-1 H-2); raising `map_safety_margin_m` to 0.45 recovered only
1 sampled episode. A2 therefore owns the DOOR-1 H-2 decision (one clearance
authority, brake→replan signalling) as a design change, not a config change.
First measured `localization_jump_m` (max 0.029 m, median 0.009 m,
room-scale) goes to `bridge/timing.py`'s record at reconciliation.

Does not prove: everything the RESULTS' own section lists — sim ray engine,
synthetic detector noise, kinematic body, harness-seeded map, and the latch/
margin being models of a proposed policy rather than product behavior.

## Amendment (2026-08-24, after parcel-6c's 4b lens + verifier re-measurement)
1. Attribution of the latch's 0.00 m is CONFIRMED non-circular (controls:
   same seeds unlatched moved 0.23–0.84 m; gated seed-303 arm A moved
   0.252 m pre-latch, 0.00 after).
2. Wording corrected: the gated latches fired at t=0.9 s on ambient
   `global_match_ambiguity` (journalled margins ≤ 0.005) — the latch **held
   motion in a world it had already judged globally ambiguous**; the
   kidnap-ONSET catch in a normal layout (JUMP_BOUND jump/mismatch path)
   was never exercised and is now an A3 acceptance criterion + proposed v3
   row. No journal anywhere fires `localization_jump_m` yet.
3. The operator-path row was a harness artifact (1 Hz live-truth feed, 79
   silent re-arms — functionally auto-resume under ambiguity). Fixed
   one-shot and re-measured (`REFUTER_4B_REMEASURE.md`): one journalled
   re-arm, 0.14–0.32 m bounded motion, standing ambiguity re-latches, all
   episodes end latched, 0 false arrivals. A4 path (b) evidence is now the
   one-shot transaction only; RESULTS' singular phrasing is superseded by
   the re-measure note.
4. R4b's REFUTED-on-shipped-arms verdict is untouched by all of the above.
