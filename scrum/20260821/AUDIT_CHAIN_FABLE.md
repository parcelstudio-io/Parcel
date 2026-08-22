# AUDIT — the perception-cutover chain (C-1 → C-2 → C-3 → E-2) · Fable · 2026-08-21/22

Chain run wf_66ee1c7a (re-dispatch with the tombstone/quiescence contract),
~3h50m wall, four executors, sequential, script-enforced halt propagation.
Audit method: four adversarial read-only verifiers (one per card) instructed
to REFUTE, plus my own gate runs and spot checks. What a verifier could not
independently reproduce is listed as unverified in its transcript, never
silently promoted — the per-card notes below say which claims rest on
executor artifacts (gate counts, seed reds) versus independent recomputation
(hashes, arithmetic, AST, collection counts, store round-trips).

## Verdicts

### C-1 "attach the eye" — ACCEPT_CLOSE

The missing call site now exists and the pixel path ran inside the live
robot, both arms symmetric, every loss counted, EV-1 rows hash-verified by
the verifier independently (sha `1dff417b…` recomputed; 69 perception rows
re-counted in the raw event log). The safety bound closes where it matters:
CollisionGate p99 delta **+0.735 ms** against the pre-registered +5 ms, with
the whole-loop +28.211 ms declared a MISS in advance, not discovered
conveniently. The freshness MISS (562 ms p50 vs 300 ms TTL, 16/16 frames
expired at publish) is the card's most consequential honesty: **the stream
is proposal/diagnostic only and not fit for grounding authority as
measured** — C-1's own words, held.

One discrepancy, minor, corrected here rather than in C-1's doc (which is
its executor's record): C1_STATUS claims "69/69 inferences under a
mission_lease"; every artifact reads **68** leased, and the 69th is an
inference from teardown timing. The supported claim is 68-plus-one-likely.
Nothing downstream depends on it.

Also to C-1's credit, self-reported: a harness incident (seed 8's deadlock
left a mutation in the tree mid-run; caught, restored, harness hardened
with `finally`), a test defect its own seeds exposed (the freshness test
could not detect the violation it asserted; the TEST was fixed and the seed
then went red), and a discarded measurement confound (shared simulator
latched an e-stop across arms). This is what the register asks for.

### C-2 "online semantic map" — ACCEPT_CLOSE, one defect carded

The map package is real, self-contained, and R27-clean (verifier walked
the code: no default store location, owner store refused by name AND
identity, env-gated path, the single sqlite connect behind the refusal
gate). The 0/5 live-corpus miss is reported as a miss with the
false-positive entry dissected rather than the size prior retuned. The
**blocking architectural finding** — `ranking_margin ≡ 0.0` whenever the
evidence-weighted background's MAD is 0.0, which it always is — was
reproduced mechanically by the verifier through the real code path.

**REFUTED (the audit's one refutation): the REVISION §6 source crop does
not survive persistence.** `MapEntry` holds a bounded thumbnail in memory,
but `as_dict()` omits it and `from_mapping` cannot restore it, so
`OnlineMapStore.save` silently drops the crop — demonstrated by round-trip.
Consequence: lazy re-embedding across a model upgrade has no source
evidence after a store reload, which is the exact migration REVISION §6
exists to protect. Filed as **AU-C2-1** on the board; the fix is mechanical
(persist + restore the bounded bytes) but it is a product edit and gets a
card, not an audit patch.

### C-3 "grounding cutover" — ACCEPT_PARTIAL, honestly bounded

The semantic_source axis, the POI disable (REVISION §1's highest priority,
proven: all four demo_pois.yaml classes reach `goal_source:
semantic_search` with the table at length 0), the divergence taxonomy with
non-droppable denominators, and the R18/R20 learned-map consumers all
landed; 54 cases; oracle arm pinned at construction-equivalence. The
headline is a failure reported as a failure: **shadow agreement 0.0/18,
every learned-map answer refusing `indecisive_ranking`** — C-2's finding
reproduced through an independent consumer on perfect-geometry data.
`admission_flip` 0/18: the safety-critical direction is clean. The tail
(VLM veto/duty-cycle, PG-3 re-derivation, live voice + ≥3 closed-loop
missions) is NOT REACHED and says so; the card's central claim is marked
UNPROVEN in its own status doc. OWNS nuance noted by the verifier: the
navigation-config and two navigation-file edits ride pre-registered
deviations (D2/D4) backed by the binding REVISION, not the base OWNS list —
declared, so accepted.

### E-2 "generalization, earned" — ACCEPT_HALT (exemplary)

E-2 passed every mechanical entry check, then halted on Rule E of its own
pre-registration: with no card having ever completed the patrol protocol
anywhere, a held-out 0/N could not distinguish "does not generalize" from
"has never worked", and would spend the scene's single exposure to produce
it. **The held-out scene is UNSPENT** — sha `b218b5a4…` identical at entry
and exit, verified again by this audit; no run pack exists because no run
happened ("the absence is the honest artifact"). Zero source edits; every
modified file in the tree attributes to W-1/auditor/C-1/C-3. Seven defects
filed (§4 of E2_STATUS), all now on the board. Verifier corrections, both
minor and both in E-2's favor as understatements of care: the "4 cm" is
3.35 cm over the 16 retained frames' 8.8 s (the 40 s figure is C-1's full
cell), and the texture count is 33, not 30.

## Audit-time acts (mine, on the record)

1. **Held-out allowlist seats** for `E2_STATUS.md` and
   `E2_PREREGISTRATION.md`, with reasons in the test. E-2's mandated halt
   record names the scene it protects, and it is written AFTER the entry
   gate — so the executor could not see the scan redden. The catch-22 twin
   of E2-D7; both are chain-contract fixes below. Gate red found by my
   post-chain run, seats added, isolation suite 7/7 green including
   anti-rot.
2. **Final full gate on the audited tree**: **PASS — every hard gate
   green, 7,934 passed / 9 skipped** (after the allowlist seats; the prior
   run's single red was exactly the doc catch-22 described above).
3. The two count corrections above (69→68 leased; 4→3.35 cm) recorded here,
   not silently edited into executors' docs.

## Chain-contract v2 (for every future dispatch)

The v1 contract worked — quiescence was measured twice by every executor,
predecessor evidence was hash-verified, the one halt propagated as a STOP.
Two defects in the contract itself, both found by its executors:

1. **E2-D7**: the mandated entry gate rewrites a tracked file
   (`experimental_sampled_predictive_tracker.py`) byte-identically, moving
   the mtime the next executor must find quiet. v2: quiescence is measured
   on `git status` + content hashes, and a moved mtime may be waved through
   ONLY with positive attribution (process identified + bytes identical) —
   C-2 and E-2 both already practiced this.
2. **The documentation catch-22**: a card whose deliverable must name a
   gate-scanned artifact cannot see its own record redden the gate (the
   record post-dates its last gate run). v2: the card design pre-grants the
   allowlist seat, so the scan stays green by construction, and the
   anti-rot direction keeps the seat honest.

## The consolidated owner-decision list

1. **PG-4 (E2-D4 + E2-D5, owner-gated card task_21)**: `min_ranking_margin`
   is structurally unsatisfiable under label-primary retrieval — measured
   independently by two cards — and every learned-map threshold is fitted
   on the invalidated untextured distribution. The card must touch PG-3
   internals (MUST NOT TOUCH for every chain card), so its dispatch is
   yours. Recommendation in the card: replace the margin signal with the
   REVISION's VLM-veto as the fourth signal and re-derive all operating
   points on textured renders, pinned-fixture CI eval before cutover.
2. **RT-1 (E2-D1, card task_22)**: the red-team decoys need a home.
   Recommendation: a DERIVED variant scene (`city_block` + decoys as a new
   file) so the frozen digest never moves and no re-pin is needed; the
   alternative (decoys in `city_block.xml` + R14-protocol re-pin) is in the
   card as the owner-choice.
3. Standing, unchanged: W-1 person-class path; 256-row memory cleanup;
   udev rule; voice enrollment; corpus sign-off.

## Next dispatch (gates now satisfied per the board)

**task_20 MOVE-1 first** — E2-D2 (3.35 cm displacement under 160/160
accepted motions, undiagnosed) plus the patrol capability, because E-2's §6
is correct that nothing downstream is measurable without it. Then the C-3
tail card, then E-2 re-dispatches with its pre-registration UNCHANGED.
task_15 M-1 is independent of the learned-map blockers and dispatches on
this audit per its gate. All future executors get contract v2.
