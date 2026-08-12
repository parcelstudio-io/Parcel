# Follow-up designs — D-15 regression, visual-search rework, jerk drift, yield-aside, config-comment fix (2026-08-11, task_1)

**This is the authoritative design record for the next work cycle**, synthesized
from four independent designer investigations and two adversarial skeptic
passes (both initially `needs-edits` on all four designs). Every blocking and
should-fix skeptic finding is folded in below; each was re-verified against the
tree before adoption, and none was overruled (adjudication table, §0.2).

**Base:** commit `dd2e857` ("Land E1–E8 unbreak wave"), working tree clean.
The dispatch brief described the E1–E8 stack as uncommitted; that is stale —
skeptic 2's correction is confirmed (`git log`: dd2e857 on `main`, `git status`
clean). `scripts/ci_gate.py --tier commit` GREEN at base (3390 passed, 4 digest
sentinels intact: v3 `eb1289e9…`, v4 `b2945444…`, embodied_plan `22736f6e…`,
personal_convo `d338f335…`).

**Orchestration model (owner-set, unchanged from r2):** Cursor dispatches the
cards to the named executors (Sol = new pure modules with frozen contracts;
Opus = existing-file wiring). Fable audits after each wave per the
pre-registered protocol in `scrum/20260809/task_15/NEXT_BATCH_PLAN.md`
(§"Fable audit protocol") — restated with additions in §7.

**Global rules:** the 7 global rules of
`scrum/20260809/task_15/NEXT_BATCH_PLAN.md` §"Global rules (every card)" apply
verbatim to every card below — ci_gate authoritative (rule 1), frozen
discipline (rule 2), flag-off byte-identical (rule 3), no safety weakening
(rule 4), OWNS/MUST-NOT-TOUCH with one runtime.py owner per wave (rule 5),
`does_not_prove` honesty (rule 6), status docs + raw-fact final message
(rule 7). Status docs for this batch land in `scrum/20260811/task_1/`.

**Standing safety rules this design honors (verify against these):** K0 is the
single arrival authority and is never weakened (no epsilon widening, no
dropped arrival reasons, no special-casing); learned/detection components
PROPOSE, classical disposes; the collision gate / person stop distances /
GoalArbiter veto semantics are untouchable; new capability is flag-gated
default-OFF with flag-off byte-identical; constants DERIVE from the authority
(E5/E6/E8 derivation-over-exposure pattern); frozen artifacts move only by
owner-authorized re-freeze with 2x2 attribution; eval extensions are ADDITIVE;
every status-doc claim is measured, with `does_not_prove` for what is not.

---

## 0. Synthesis decisions

### 0.1 What changed relative to the four submitted designs

1. **Every skeptic blocking/should-fix folded in** (§0.2). The largest:
   J-B's nominal-stop ramp is re-specified with per-tick re-gating through the
   untouched `apply_reactive_safety` plus a resume-reset (skeptic 1's option
   (b)); D15-C's counterfactual is restated as a bystander-geometry sweep (the
   E5 undercut guard makes `person_stop_m=1.0` unrunnable on new code);
   VS-5's statistics are re-registered coherently; VS-1's refinement gate is
   defined per reference kind (the motivating failure is a region).
2. **Ownership collisions resolved by wave sequencing** (§6.1 matrix).
   `pipeline.py`: D15-B (Wave 1) → VS-4 (Wave 2, slot 1) → VS-5 (Wave 2,
   slot 2). `runtime.py`: J-B (Wave 1) → Y-2 (Wave 3) — one owner per wave,
   "sole owner" claims re-scoped to "sole owner within its wave".
   `evals/companion_nav/runner.py`: J-B → J-C (Wave 1, strictly sequenced) →
   Y-2 (Wave 3). `evals/nav_instruct/runner.py`: D15-B (Wave 1) → VS-4
   (Wave 2). `follow.py` and `reactive_safety.py`: `follow.py` has exactly one
   owner in the whole batch (Y-2, Wave 3); `reactive_safety.py` has ZERO
   owners — no card edits it, every card lists it MUST-NOT-TOUCH.
3. **Fifth follow-up folded in as DOC-1** (§5): the stale
   `configs/navigation/default.yaml` `person_slow_m` comment. Comment-only;
   moving the VALUE moves frozen rows and is explicitly out of scope.
4. **Evidence preservation**: the three session-scratchpad evidence artifacts
   the designs depend on (`trace_group.py`, `oracle_yield.py`,
   `minival_isolation.txt`) are archived verbatim in Appendix A of this record
   (skeptic 2: scratchpad GC would otherwise orphan Y-4's and D15-C's
   reproduction gates). Y-4 and D15-C extract from Appendix A.

### 0.2 Skeptic adjudication table

Rule applied: the skeptic wins unless their evidence is factually wrong; every
row below was re-checked against the tree at `dd2e857` by the synthesizer.

| # | Finding (skeptic, severity) | Tree check | Adjudication → where folded |
|---|---|---|---|
| 1 | S2: tree is committed at dd2e857, not an uncommitted stack | `git status` clean, HEAD dd2e857 | UPHELD → header |
| 2 | S1 blocking: J-B nominal ramp voids the predictive ring + resume path exceeds gate-approved | `reactive_safety.py` ring on commanded speed; runtime W6 comment anticipates decaying ramps; shaper emergency wipes state | UPHELD → J-B re-spec: per-tick re-gate of the ramp candidate (option b), resume-reset, property tests (§3.3, card J-B). Synthesizer refinement: the measured comfort win survives re-gating because formation-hold ticks are gate-CLEAR (owner band is derived `owner_slow_m` ≈ person_stop+0.10 = 1.3 m; owner clearance on the drifted ticks is 1.45–1.63 m) |
| 3 | S1 should-fix: NOMINAL_STOP "between" severities renumbers the IntEnum | `hard_stop.py`: CLEAR=0, PROXIMITY_STOP=1, HARD_STOP=2; **and** the finalize tail currently returns the candidate for any non-HARD/non-PROXIMITY severity — a new member would fall through OPEN | UPHELD + strengthened → NOMINAL_STOP = 3 appended; finalize tail becomes explicitly fail-closed (CLEAR returns candidate; every other value → HARD_STOP); tests pin the three existing int values and the fail-closed tail (card J-B) |
| 4 | S1 should-fix: replica classifies stops on post-chain command, runtime on intent | `runner.py _shape`: `_is_zero(command)` post-chain; `runtime.py:4556`: `_is_zero_command(active.command)` | UPHELD, scoped → the flag-ON nominal/hard split classifies on the INTENT in both machines; the flag-OFF replica classification is byte-untouched (changing it would move the pinned row); symbol-digest pin added over both predicates (card J-B) |
| 5 | S1 should-fix: D15-B compliant_speed is vetoed at the boundary (gate uses `<=`) | `reactive_safety.py`: `person_distance <= predictive_person_stop → _stop_translation` | UPHELD → compliant_speed specified as the float-lattice supremum: largest float v for which the gate's own inequality is False; zero new literals (cards D15-A/D15-B) |
| 6 | S1 note: D15-B trace assert weaker than the live gate | ring = stop + v·reaction, per tick | UPHELD → gate reworded: trace assert is a floor; the unmodified gate is the disposer; predictive criterion asserted from traces (card D15-B) |
| 7 | S1 should-fix: VS-1 refinement gate undefined for regions (B-05 is a region) | B-05 goal is a polygon; `object_near_envelope_m` is object-centric | UPHELD → per-kind gate: regions = fused point inside grounded polygon dilated by the interchangeable ranking's existing boundary margin (by reference); objects = vicinity band + Mahalanobis (card VS-1) |
| 8 | S1 should-fix: min yaw/baseline "derived from confirmer constants" is a fake derivation | `multi_view_confirm.py` constants are score-space; no geometry | UPHELD → real authority found in-tree: `instructnav/scan.py` `full_turn_scan_spec(n_stops=8)` — minimum angular separation between admissible views = the full-turn scan's stop separation (2π/n_stops), by reference; owner-2x2 fallback in §8 if verify rejects it (cards VS-1/VS-4) |
| 9 | S1 note: VS-4 flag scoping; VS-6 panel rewrite | commit path shared; `mutation_panel.json` not in DIGEST_SENTINELS | UPHELD → VS-4: all commit-path changes conditional on the flags, unconditional path byte-identical; VS-6: in-tree panel regeneration declared as a deliverable (+1 row, prior verdicts unchanged); development runs in scratch (cards VS-4/VS-6) |
| 10 | S1 should-fix: Y-1 "keepout by construction" false; `_clamped_lead` bypassed; aside stalls the lagging chase | `_step_direct`: hold when `distance_error <= deadband` (one-sided!); `_clamped_lead` budget = standoff − keepout ≈ 0.10 m | UPHELD → Y-1 contract: closed-loop equilibrium property (|robot_eq − owner| ≥ owner_keepout_m), lagging-regime admissibility clause, "by construction" language dropped; Y-2: clamp exemption stated with rationale + does_not_prove (cards Y-1/Y-2) |
| 11 | S1 note: gate people list carries one stranger scalar; Y-1 rejection over ALL tracks is load-bearing | `reactive_safety.py` people list = nearest_person + owner; docstring names `dynamic_agents` widening as the seam | UPHELD → Y-1 property over full randomized track sets; limitation in Y-2/Y-3 does_not_prove; widening seam in §8 (not this batch) |
| 12 | S2 blocking: D15-C "pass at 1.0" cannot run (E5 undercut guard raises) | guard verified: `person_stop_m + 1e-12 < envelope floor → ValueError` | UPHELD → counterfactual restated: bystander clearance/geometry sweep (runnable) + `person_stop=1.0` outcome computed analytically from D15-A, labeled derived-not-run (card D15-C) |
| 13 | S2 blocking: pipeline.py claimed by D15-B, VS-4, VS-5 | OWNS lists as submitted | UPHELD → sequenced D15-B (W1) → VS-4 (W2 slot 1) → VS-5 (W2 slot 2); "sole owner" wave-scoped (§6.1) |
| 14 | S2 blocking: runtime.py double-claimed (J-B, Y-2) | both regions real (`:4548-4557` predicate; `:506-536` follow plumb) | UPHELD → J-B owns runtime.py in Wave 1; Y-2 owns it in Wave 3; enumerated-patch fallback (rule 5) only if Cursor reorders (§6.1) |
| 15 | S2 blocking: companion runner.py claimed x3 (J-B, J-C, Y-2) | `_shape` ~:589-603, BenchFeatures :84, `_follow_config_from_store` :849 all real | UPHELD → strict sequence J-B → J-C (Wave 1) → Y-2 (Wave 3), each successor re-baselines its identity gate on the predecessor's landed state (§6.1, cards J-C/Y-2) |
| 16 | S2 blocking: VS-4's flag cannot run — ALLOWED_NAVIGATOR_OVERRIDES edit in nobody's OWNS | frozenset at nav_instruct `runner.py:75-77`; unknown overrides raise | UPHELD → VS-4 OWNS `evals/nav_instruct/runner.py` in Wave 2 (one-line additive); D15-B owns the same file in Wave 1 for `person_aware_nav` (card VS-4/D15-B) |
| 17 | S2 should-fix: VS-5 "+10pp AND McNemar p<0.05 at n=20" incoherent | 2 net flips at n=20 → p≈0.5; ≥6 net flips needed | UPHELD → re-registered: exact-McNemar computed by the harness; floor = ≥6 net paired flips (losses 0; equivalently p≤0.031); generation aims n≥60/axis to make +10pp detectable; below either bar → STOP-and-report with the measured delta (card VS-5) |
| 18 | S2 should-fix: VS-6 pins the wrong hash (4113607b is the minival digest) | `sha256sum` v4 manifest = `b2945444…`; E8 line 19 labels `4113607b…` "minival digest" | UPHELD → gate re-pinned to "all 4 DIGEST_SENTINELS byte-identical via scripts/ci_gate.py"; `4113607b…` kept as a second invariant labeled minival-report digest (card VS-6) |
| 19 | S2 should-fix: VS-4 phantom gate can pass vacuously | zero-arrivals is also the nothing-happened outcome | UPHELD → non-vacuity conjuncts: ≥1 lock-on COMMIT-then-REFUTATION event and ≥1 FP-memory suppression hit on re-encounter, asserted from traces (card VS-4) |
| 20 | S2 should-fix: D15-A OWNS contradiction (extend an existing test file while claiming "nothing existing edited") | `tests/test_authority_no_literal_drift.py` exists | UPHELD → no-literal-drift assertions live in the NEW `tests/test_person_keepout.py`; extend-clause deleted; "nothing existing edited" stays true (card D15-A) |
| 21 | S2 note: Y-4 depends on session-scratchpad files that will not survive GC | files present now, only copies | UPHELD → archived verbatim in Appendix A of this record; Y-4/D15-C extract from here (§0.1.4) |
| 22 | S2 note: J-C's fresh bench run would append a ledger row and shift latest-row pins | FOLLOWBENCH_LEDGER read by hard-safety; `test_duplex_v1` latest-row pins | UPHELD → J-C gate: fresh run writes to a scratch results dir (no ledger append), or if appended officially every latest-row-pinned value is byte-identical to the prior latest row (card J-C) |

---

## 1. Follow-up 1 — D-15 regression (`nav-object_goal-D-15-109547e2`)

### 1.1 Diagnosis (measured; bisect complete)

The flip is a single config knob from lane E5: `safety.person_stop_m`
1.0 → 1.2 (`configs/robot.yaml`, owner-authorized person-clearance retune,
2026-08-10). Mechanism, traced in-episode:

- The headless world places a DEFAULT OWNER at (2.00, −0.50) in every
  nav_instruct episode even though the runner resets with owner=None;
  `apply_reactive_safety` treats the visible owner as a person
  (`reactive_safety.py` people-list construction).
- On D-15's route the robot reaches (0.29, 0.11) heading toward tree_2
  (5.0, 3.1); owner clearance 1.8132 − 0.55 = 1.2632 m. Predictive person stop
  = 1.2 + 0.85·0.12 = **1.3020 ≥ 1.2632 → hard `_stop_translation`** every
  tick. The pipeline never sees the veto (note stays
  `grid_track … status=planned|clear`, err 0.0), the step-220
  `semantic_replan_after_no_progress` replans the SAME straight route, and the
  episode times out at 400 steps: FAIL, dtg 3.0301, planning_error.
- Old value: threshold 1.0 + 0.102 = 1.102 < 1.2632 → passes, arrives 2.49 m
  from the tree — 1 cm inside the 2.5 m band outer edge. The episode is
  intrinsically MARGINAL.

**Bisect table** (scratch worktrees, v3 episodes, baseline mode,
scaled-path-v1, pipeline-first import per E7 §2.1): [1] 6bd945d old src+evals
→ SUCCESS 0.0; [2] dd2e857 full → FAIL 3.0301; [3] revert E1 set → FAIL
3.0301 (E1 exonerated); [4] revert perception set → FAIL 3.0301 (exonerated);
[5] revert 4x robot.yaml + reactive_safety.py + follow.py → SUCCESS 0.0;
[6] revert code only, keep new yamls → FAIL 3.1124 (config is the driver);
[7] `person_stop_m` 1.2→1.0 alone (old rs code to pass the guard) →
**SUCCESS 0.0, 106 steps — THE KNOB.**

The 3 moved-dtg episodes are the SAME cause (25-ep isolation minival, Appendix
A.3): region_goal-D-15 restores 2.1021→1.8967 (frozen old 1.8999),
object_relative-D-15 4.1822→4.3258 (frozen 4.3301), object_goal-B-05
0.3928→0.3242 with the old failure class (false_arrival), object_goal-D-15
back to the band edge (dtg 0.0067 in-context / 0.0 alone).

**Classification: (b) CORRECT stricter behavior** — the retune matches the
SafetyEnvelope authority (`person_stop(0)=person_social_zone_m=1.2`) and must
not be reverted — compounded by two real gaps it exposed: (1) capability gap:
no person-aware detour/speed proposal, so a compliant robot deadlocks forever
behind any human on route; (2) eval-honesty gap: an UNDECLARED stationary
bystander (the default owner) lives inside every nav episode's world.

Why nobody found it: E5 measured person_stop cost on FOLLOW_BENCH only ("cost
zero", E5_STATUS:15-17) and did not re-measure nav_instruct (E8 §9); E8 could
not A/B person_stop on new code because E5's guard REFUSES
`person_stop_m < envelope floor` (ValueError, reproduced — see also
adjudication #12); E8's person_slow_m null result is consistent because the
owner's comfort band does not use `person_slow_m` (E6 owner band) and the hard
predictive stop uses only `person_stop_m`.

Key marginality/context numbers (all measured): old arm arrives 2.49 vs band
edge 2.50 (1 cm); new-code D-15 dtg is 3.0301 single-episode / 3.0268 in
4-episode context / 3.0293 in E8's 25-episode row — frozen numbers are valid
only under their full protocol; episode-order state leaks through the shared
world (unowned; §8).

### 1.2 Design

The retune stays. The v4 frozen row already carries the cost honestly
(SR 0.24) — no re-freeze, no tolerance change. Deliverables: (1) the
attribution record; (2) a flag-gated capability (`person_aware_nav`,
default OFF) that lets a compliant robot get past a human instead of
deadlocking — grid keepout painting + proposer-side speed cap so the
UNTOUCHED gate approves; (3) an additive declared-bystander eval cell that
would have caught this class, plus the marginality annotation for the four
moved episodes. Constants derive from `ReactiveSafetyPolicy` by reference.
K0, the gate, person distances, veto semantics: byte-untouched.

**compliant_speed (skeptic-corrected):** the gate vetoes at
`person_distance <= person_stop_m + |v|·reaction_time_s` (verified `<=`).
compliant_speed(c) is therefore specified as the FLOAT-LATTICE SUPREMUM: the
largest float v for which the gate's own inequality evaluates False (found by
nextafter-stepping/bisection on the float lattice — zero new constants, exact
by construction, testable by evaluating the gate's expression verbatim).
D-15 pin: clearance 1.2632, threshold at v=0.85 is 1.3020 → veto;
compliant_speed(1.2632) ≈ 0.5266 (strictly below (1.2632−1.2)/0.12), and the
gate expression at that v is False.

### 1.3 Rejected alternatives (upheld from the design, all still binding)

- **Revert person_stop_m / special-case the eval world** — safety-negative;
  the 1.2 floor IS the authority; E5's guard exists to stop this drift.
- **Fix the deadlock inside `apply_reactive_safety`** — edits untouchable
  gate semantics; identical outcome achievable proposer-side.
- **Re-freeze v4 / widen the D-15 band or tolerance** — the frozen row
  carries the loss honestly; moving tolerances is the prohibited silent
  change; the 1-cm margin would only relocate the knife edge.
- **Classify as flakiness; seed-sweep only** — refuted: deterministic 0.2 m
  threshold change, reproduced across three protocols.
- **Delete the default owner from nav worlds** — moves every frozen row and
  hides a real deployment condition; the honest fix is to DECLARE bystanders.

### 1.4 Risks

- Cross-episode state leakage (3.0301/3.0268/3.0293) — every gate pins its
  protocol; the leakage itself is unowned (§8).
- D-15 stays a 1-cm band-edge episode even with the detour; flag-on gate runs
  twice; the eventual honest fix is an owner-authorized v5 with margin-aware
  bands (§8, NOT this batch).
- The speed cap must stay proposer-side; any drift of compliant_speed INTO
  `apply_reactive_safety` is a gate edit and is rejected — the D15-A
  no-literal-drift test is the tripwire.
- The undeclared default owner also stands in follow/circle worlds; declaring
  bystanders may surface further confounds (e.g. the 4 unexplained
  circle_owner authority_disagreements E8 left unowned, §8).
- E5's "person_stop cost zero" record is falsified for nav_instruct; D15-C's
  attribution cross-references it additively (correction note, no edit of
  E5's measured FOLLOW_BENCH claims).
- If `person_aware_nav` ever defaults ON, V-D/V-E pre-registered margins on
  the same harness must be re-checked (out of scope while flag-off is
  byte-identical).

---

## 2. Follow-up 2 — Visual-search rework (V-D no-op + V-E false arrival + V-B phantom)

### 2.1 Diagnosis (three measured causes, one per finding)

**(1) V-E false arrival = wrong-INSTANCE commit** against a silently rewritten
goal — not a phantom, not an arrival-check bug. The lock-on branch
(pipeline.py ~:2298) fires inside the searching path with no
interchangeable-query check, bypassing the region-instance selection
discipline the flag-off scan enforces (~:2541-2543, arbitration 2026-08-07).
For "walk onto the sidewalk" it committed the first-RESOLVED sidewalk
(south), retargeted the candidate xy to the D2 fused estimate (:1673-1686),
built `arrival_goal_region` FROM that committed candidate (:1809-1826), and
K0 then CORRECTLY verified arrival against the rewritten region: final pose
(1.3480, −2.5785) is inside the south sidewalk; episode polygon y∈[2.2,4.2];
dtg 4.778530810034543 = 2.2 − (−2.578530810034543) exactly. Compounding:
lock-on "views" are self-confirming — `observe_candidate` re-reads the SAME
grounded oracle candidate every tick; `now_ns` changes per tick so every tick
is a distinct view token (`multi_view_confirm.py` token =
`("timestamp", source_timestamp_ns)`, verified) — M-of-N ≈ any 3 consecutive
ticks with zero independent evidence; and MetricLocalizer fuses every
measurement into one [x,y] state with no association gate.

**(2) V-D no-op, three legs:** (a) the eval loop has NO camera
(runner.py `world.observe()` GT semantics; the runner's own does_not_prove
says so) — the map is painted from the same oracle frustum grounding already
uses, substring match, floors 0.15/0.05 at conf 1.0 (a scanned-cone marker,
not evidence); (b) the GP-UCB look block is skipped for interchangeable
queries and only runs AFTER the full 2π turn (verified in-tree), so any
in-range target is already found — Tier B extra looks structurally redundant;
(c) Tier C is planner-bound, not frontier-bound (grid_recover_scan
no_path|obstacle_stop dominates; 2 of 5 Tier C episodes never search). The
empty-map ValueMapFrontierScorer is NOT the baseline scorer (coverage=1.0 +
prior-blend terms) — the 0-flip tie was accidental.

**(3) V-B/FP-memory:** MultiViewConfirm consults rejected memory every update,
but entries arise ONLY from in-window M-of-N failure (flicker); a
view-consistent phantom never fails the window (V-B measured commit on
view 2), and once committed the session returns None forever (verified
`if self._committed: return None`) — no re-verification on approach, no veto
path, no negative evidence ever written.

### 2.2 Design

ONE architecture, four components + eval cells, all flag-gated default-OFF,
all constants derived from existing authorities.

**Core principle — reference/estimate separation:** the mission's grounded
goal (landmark id + geometry) is the REFERENCE and is never rewritten by
perception; a lock-on produces an ESTIMATE (approach pose + covariance) that
must stay consistent with the reference; K0 verifies arrival against the
REFERENCE only. The B-05 false arrival becomes structurally impossible
without touching K0 (no epsilon change, no second predicate; the D4
chance-constrained `contains()` unchanged).

**(a) Arrival integrity (VS-4 wiring):** (i) lock-on defers to the
interchangeable_scan ranking — for region/"nearest" queries the instance is
fixed by the existing scan-complete boundary-aware ranking BEFORE any lock-on
session may observe; lock-on then only refines that instance; (ii)
`arrival_goal_region` is built from the GROUNDED reference geometry (region
polygon / object vicinity via `object_near_envelope_m`, consumed not edited),
never from the fused point; the fused estimate moves only the approach pose
(SE2Goal through the existing propose/dispose seam, veto semantics
untouched); (iii) refinement gate, defined PER REFERENCE KIND
(skeptic-corrected): for REGIONS, the fused point must lie inside the
grounded polygon dilated by the boundary margin the interchangeable ranking
already uses (by reference — Mahalanobis vs a polygon is undefined); for
OBJECTS, |fused − reference| inside the vicinity band AND
Mahalanobis-consistent with the D2 covariance. Violation is a REFUTATION,
not a commit. The `goal_landmark_id` never-rewritten promise (:1818-1820)
becomes enforced. All commit-path changes are CONDITIONAL on the flags; the
unconditional path is byte-identical.

**(b) Verify-on-approach (VS-1 pure):** lock-on is a PROPOSAL with a
re-verification schedule as range closes — checkpoints DERIVED from the
envelope (`vicinity_radius_m`, `stand_off_m` via `object_near_envelope_m`);
at each checkpoint the session demands fresh evidence: persistence,
covariance shrink (D2 trace decreasing as range closes), optional SigLIP
identity re-check through the existing `embed_fn` seam. Any failure ⇒ veto:
flush the SE2Goal via the existing P0-C stamp/flush seam, write negative
evidence, resume search. **Independent-evidence rule** fixes
self-confirmation: a view is admissible for M-of-N only if separated from the
previous admitted view by the full-turn scan's own stop separation —
2π / `ScanPlanSpec.n_stops` from `instructnav/scan.py` `full_turn_scan_spec`
(n_stops=8, verified) — BY REFERENCE (skeptic-corrected: the previously
claimed "confirmer association constants" are score-space and derive
nothing). View ADMISSION lives in the new pure module / session wrapper;
`multi_view_confirm.py` is untouched.

**(c) FP-memory negative evidence (VS-2 pure):** mission-scoped memory keyed
by (class, world-cell) recording REFUTATIONS (failed re-verify, failed
refinement gate) with TTL/decay; consulted before accepting any hypothesis at
a remembered location. A view-consistent phantom passes M-of-N (measured),
fails verify-on-approach, gets refuted and remembered. MultiViewConfirm's
window-failure memory untouched (flicker vs persistence, distinct).

**(d) Evidence-fed value map with DEFINED empty behavior (VS-3 pure + VS-5
wiring):** `value_evidence.py` maps real inputs — semantic candidates from
the one ingress plus MISSES (scanned cone with no query evidence lowers
value) — to (value, conf, is_evidence) paint tuples using match scores
(embed seam), replacing the substring/floor painter; `SemanticValueMap2D`
gains `evidence_count`. EMPTY-MAP CONTRACT: `evidence_count==0` ⇒ C2 session
returns COMMIT (no extra looks — exactly the baseline full turn) and the C3
scorer DELEGATES to the flag-off scorer OBJECT (not a re-implementation)
float-identically — flag-on with no evidence is PROVABLY the baseline, so
any measured delta is attributable to actual evidence.

**(e) Additive search-exercising cells (VS-6):** new episode set
`evals/nav_instruct/episodes/v4s/` (own manifest; v4 sentinels untouched),
≥20 paired episodes per axis (target initially out of frustum AND beyond the
initial scan position; beyond-the-block frontier), generation-time
A*-routability asserted (the measured Tier C no_path lesson); plus one
ADDITIVE mutation-panel mutant injecting a view-consistent phantom that must
redden ≥1 harness via the differential-authority false-arrival channel.
Generation aims for n≥60/axis if routable yield allows (makes +10pp
statistically detectable; see card VS-5 gate).

### 2.3 Rejected alternatives (all binding)

- **Widen K0 epsilon / special-case lock-on goals / second arrival
  predicate** — K0 is the single authority; the failure is an identity error
  upstream; K0 verified the goal it was given correctly.
- **Stricter M-of-N or higher credibility** — a view-consistent phantom
  passes ANY finite window (measured commit at view 2); only negative
  evidence under approach discriminates.
- **IPDA / recursive existence probability** — explicitly deferred seam
  (task_4 anti-goals); verify-on-approach + FP-memory delivers the channel
  behind the existing `existence_probability_source` seam.
- **Edit v4 frozen episodes to add search pressure** — rule 2; v4s is the
  additive path.
- **Feed the map from a globally lowered detector threshold** — the operating
  point is not a safety lever (V-B); the eval arms have no detector in the
  loop; the map needs an evidence contract including misses.
- **Provenance stamps on rewritten goals** — labels do not prevent the
  wrong-instance verify; only reference/estimate separation does.
- **Multi-target Kalman association** — larger estimator surface for the same
  guarantee; the refinement gate + ranking-fixed instance already reject
  inconsistent fusions; remains a hardware-era seam.

### 2.4 Risks

- Power: the v4 minival stays n=5/tier — VS-4's ≤0.10 per-tier margin is a
  regression tripwire, not an estimate; real power lives in v4s; if
  generation cannot produce the pre-registered n per axis → STOP-and-report,
  never silent shrink.
- Verify-on-approach adds dwell steps; budgets derive from scaled-path-v1
  (no new literals); the paired zero-lost-episodes gate catches conversions
  to step-limit failures.
- In T0 arms "persistence" is the oracle frustum (never hallucinates) —
  verify-on-approach passes trivially on real targets; phantom-rejection
  power is exercised only via the injected phantom cells; does_not_prove must
  state real-camera persistence is hardware-deferred.
- Float-identical empty-map delegation is strict — must call the flag-off
  scorer object itself.
- VS-4/VS-5 both own pipeline.py — strictly sequenced (§6.1).
- Lock-on adds no value for region/"nearest" queries BY DESIGN (deference);
  speeding those up is a future card against the ranking, not a loosening.
- The view-admission rule slows legitimate commits by ~one scan arc; the
  per-tier margin bounds the cost; any breach is STOP-and-report.

---

## 3. Follow-up 3 — Jerk drift on FOLLOW_BENCH_V1

### 3.1 Diagnosis (measured, bisected, bit-exact where pinned)

- The 0.6025 pin reproduces bit-exactly at be20471 (mean 0.6025,
  mean_band_fraction 0.7433396178984414 to 16 digits) — the bench is
  deterministic; no environment drift.
- **The pre-existing 58% (0.6025 → 0.9541) splits into two committed,
  DELIBERATE changes:** (a) be20471→60ecea2 +0.0923, entirely in the two
  navigate episodes, caused by `grid_navigator.py`
  `TERMINAL_APPROACH_FLOOR_MPS=0.12` (owner pacing seam; single-hunk revert
  restores navigate_near_wall to exactly 1.1401); residual +0.29 on
  navigate_crossing_ped attributed by elimination to the same commit's
  pipeline.py scan-creep seam (not single-hunk isolated; ~20 s scratch cell
  if the owner wants it pinned separately); (b) 60ecea2→6bd945d +0.2329, in
  the stop-heavy follow episodes, caused ENTIRELY by P0-A's hard-stop change
  in `velocity_shaping.py` (emergency: accel-limited `_move_toward` →
  instant exact (0,0,0); reverting only that hunk returns the mean to exactly
  0.7212 = the 60ecea2 value). Both are shipped, owner-adjudicated trades —
  the 58% is a legitimate re-pin-with-attribution, NOT a regression to fix.
- **E6's +37% (0.8918 → 1.2187) is NOT band-edge transitions** (E6's own
  guess, refuted by trace): in straight_follow and owner_stops the owner band
  is granted 200/200 and 180/180 ticks and owner center distance stays
  2.00–2.18 m — never inside the 0.10 m ramp. Instead 96.7%/96.3% of summed
  squared jerk sits on emergency-ADJACENT ticks: E6 unthrottles the dog, it
  genuinely accelerates to formation, the follow controller commands zero,
  and the runtime routes ANY zero intent (`_is_zero_command`, runtime.py:4556)
  through the same emergency bypass as safety stops — since 6bd945d an
  instant discontinuity (vx 0.141 → 0.0 in one tick, jerk² ~199/event). A
  comfort cost with zero safety benefit on those ticks: every safety stop
  takes its own predicate arm.
- **Design cell** (replica patch: instant-zero kept for hard stops,
  pre-6bd945d accel-limited ramp for nominal zero intents): 1.2187 → 1.0039
  with every safety metric bit-identical (min_pedestrian_surface_m
  0.5299999999999998, dwell 2.3, collisions 0, gate stops 2, follow 7/9).
- Clean-HEAD control reproduces the committed pin exactly (7/9,
  0.708782386458857, 1.2187).

### 3.2 Design

**Part 1 — gate NOW at the attributed value (J-C):** follow-bench jerk
ratchet in `scripts/ci_gate.py` mirroring the latency-tail-ledger pattern:
committed baseline `evals/companion_nav/results/jerk_baseline.json`
({window, mean_rms_commanded_jerk_mps3: 1.2187, provenance: this
attribution}), gate reds iff latest shipped ledger row > baseline ×
LATENCY_TAIL_MARGIN (reuse 1.20 by reference — one repo-wide ratchet margin,
no new constant), skip-with-note when no shipped row carries the field,
seeded-spike self-test. `FOLLOW_BENCH_POST_SPEED` (run_duplex_v1.py:114)
gains the jerk value with the three-component attribution (0.6025 → +0.09
floor [60ecea2 pacing] → +0.23 instant-zero [6bd945d P0-A] → +0.33
E6-dynamics × instant-zero interaction), correcting E6's band-edge guess on
the record. The 58% closes as documented-deliberate.

**Part 2 — severity-split stop shaping, flag-gated default OFF (J-A + J-B),
re-specified per skeptic 1's blocking finding:**

- **J-A pure module `core/stop_ramp.py`:** `nominal_stop_step(velocity,
  accel_limits, dt)` = per-axis `_move_toward(v, 0, max_accel·dt)` — the
  exact pre-6bd945d emergency semantics, rate derived from the shaper's own
  `MotionShapingConfig.limits()`; `enforce_monotone_stop(prev, candidate)`
  fails closed (any magnitude increase, sign flip, or non-finite → None →
  caller must HARD_STOP).
- **J-B wiring, structural safety closure (skeptic option b):** severity
  `NOMINAL_STOP = 3` APPENDED to `InterventionSeverity` (never renumber;
  dispatch by identity); `finalize_command` tail becomes explicitly
  fail-closed (CLEAR returns candidate; ANY other severity → the untouched
  HARD_STOP branch — note the current tail returns the candidate for unknown
  members, so this is a required hardening, byte-identical for all reachable
  inputs today). Runtime predicate split (runtime.py:4548-4557): hard =
  proximity 'stopped' ∨ arbiter.emergency_stopped ∨ input-health latched ∨
  active is None (unchanged, still emergency + HARD finalize); nominal =
  `_is_zero_command(active.command)` alone, and ONLY under flag
  `motion_shaping.nominal_stop_ramp` (default False). **Per-tick re-gate:**
  each nominal-ramp tick the ramp candidate is fed through the UNTOUCHED
  `apply_reactive_safety` (+ TTC verdict) as the command, so the predictive
  ring sees the TRUE decaying speed; the actuated value is the gate's
  disposition of the candidate; any stop verdict ('stopped'/zeroed
  translation/veto) preempts to the untouched HARD path with exact (0,0,0)
  THAT tick + full reset obligations. **Resume-reset:** on the first non-zero
  intent after a nominal ramp, the shaper's cached state is reset to zero
  BEFORE the resume tick — resume dynamics byte-equal **at the shaper**, which
  is the stage this clause names; the PRE-GATE velocity smoother is *not* reset
  by a nominal stop (a nominal stop is not a hard stop, so it does not run the
  HARD reset obligations), which is disclosed and tested by J-B and leaves
  safety untouched because every subsequent tick is re-smoothed and re-gated;
  actuated can never exceed gate-approved from above.
  <!-- CHANGELOG — AF-1 correction, 2026-08-11: the resume clause above read
  "resume dynamics byte-equal to flag-off resume" without naming the stage.
  Narrowed to the shaper, with the smoother's behaviour stated, per the Wave-1
  Fable audit's [note] on §3.2 wording. Nothing else in §3.2 was touched and no
  code moved. -->
  **Operand parity:** the
  flag-ON nominal/hard split classifies on the INTENT in both machines; the
  replica's flag-OFF classification is byte-untouched (its pre-existing
  post-chain-command operand divergence from the runtime is recorded in
  does_not_prove, not silently "fixed" — fixing it moves the pinned row and
  is owner-gated); the stopping predicates of BOTH machines join a
  symbol-digest pin (REACTIVE_SAFETY_PIN pattern) so silent divergence
  reddens. Why the measured win survives re-gating (synthesizer tree-check):
  the drifted episodes' stop ticks have owner clearance 1.45–1.63 m against
  the derived owner band `owner_slow_m` ≈ 1.3 m and ring ≤ 1.2 + 0.141·0.12 =
  1.217 m — the gate is CLEAR there, so the ramp passes undisturbed; scaling
  bites only with a stranger inside 2.5 m or owner inside 1.3 m, exactly
  where caution is correct. The 1.0039 expectation is re-measured under the
  final wired code; ≤1.05 is the pre-registered bar; a miss is
  STOP-and-report, not a margin renegotiation.

**Part 3 — additive metric separation (inside J-C):** per-step `emergency`
flag + `mean_rms_commanded_jerk_nominal_mps3` (report-only) so the ratchet
never pressures safety stops and future re-pins attribute stop-cost vs
smoothness-cost mechanically. After an owner flag-flip decision, J-C re-pins
the baseline DOWNWARD with 2x2 — ratchets only tighten.

### 3.3 Rejected alternatives (all binding)

- **Revert/soften P0-A instant-zero or the terminal floor** — deliberate
  shipped decisions (P0-A is the verdict-ranked contract); re-pin with
  attribution is the honest move.
- **Owner-band hysteresis / slew inside the reactive layer** — refuted by
  trace: band granted 100% of ticks, owner never in the ramp; would touch
  `apply_reactive_safety` to fix a mechanism contributing ~nothing.
- **Route nominal zeros through the NORMAL s-curve** — weakens W6 further
  than needed; the pre-6bd945d emergency semantics are proven and monotone.
- **Per-episode gates instead of the ledger mean** — new parsing path +
  per-episode pins that legitimately reshuffle; immutable reports remain the
  attribution escape hatch.
- **Gate only "nominal" jerk** — would blind the gated metric to a bug
  spraying spurious hard stops; gate the inclusive mean, report the nominal
  variant.
- **Default-ON in the same card** — flag-off byte-identity is a standing
  rule; the default flip moves a pinned row (1.2187 → ~1.00) and is an
  explicit owner decision after J-B's measurement.

### 3.4 Risks

- Replica/runtime parity: the symbol-digest pin is the guard; the bench must
  measure the machine production ships.
- The 1.0039 was a replica monkeypatch; the finalize-boundary monotone check
  and the yield-advance seed (runtime.py:4690) could interact — a >1.05
  landing is STOP-and-report.
- Ratchet blindness by construction: 1.20× tolerates ~+22% silent creep;
  the additive nominal metric + immutable reports are the escape hatch;
  re-pin downward after any flag flip.
- Scratch-integrity caveat (recorded): one transient corruption of a scratch
  copy was observed mid-investigation; all final cells were re-run on freshly
  verified worktrees and anchored by two bit-exact pin reproductions
  (0.6025/0.7433396178984414 at be20471; 1.2187/0.708782386458857 at
  dd2e857). Executors re-measuring keep the verify-hash-inside-the-run
  discipline.
- Bench-only scope: jerk numbers are the shaper's contribution on the
  headless kinematic block; not a hardware ride-quality claim.

---

## 4. Follow-up 4 — Yield-aside (pedestrian_group price, re-aimed)

### 4.1 Diagnosis (measured; topic premise corrected)

pedestrian_group's band failure is NOT the stationary-in-the-group's-path
stance the topic premised (that trace is E6 §4.3's pedestrian_cut_in). In
pedestrian_group the robot NEVER stops (0 gate stops; 223/250 steps
'slowing'), never gets closer than 1.43 m to any pedestrian, never reaches
the group (ends x=2.74; group at x≈4.0–5.2). It LAGS under two multiplicative
throttles: (a) the owner's own people-list entry under the 2.5 m stranger
band — the two-body interlock is denied for all 25 s because three
near-stationary flankers sit on the person channel; the chase equilibrates at
2.77 m owner distance (vx 0.275 = scale 0.78 × 0.35, matching
(2.77−0.55−1.2)/1.3 exactly); (b) the stranger ramp at the 3.4 m flanker gap
(pinch clearance 1.5–1.7 m → scale 0.19–0.38) cuts vx to 0.05–0.13 for
~10 s → 104/250 steps above 3.0 m. **Derived infeasibility:** holding band
pace (scale ≥0.8) needs clearance ≥ 1.2 + 0.8·1.3 = 2.24 m; the corridor
offers ~1.5–1.7 m; NO lateral aim offset can recover 0.75. Oracle
upper-bound confirms (Appendix A.2): shifts +0.2/+0.4/+0.6 REGRESS band
(0.568/0.552/0.540 vs 0.584); best cell (−0.3) = 0.616; cut_in ±0.4 moves
band ±0.005. Yield-aside's real value is where the failure is
displacement-into-a-crossing-corridor (cut_in stance; oncoming groups) — not
pedestrian_group, whose 0.75 is the stranger band's honestly-unreachable
price in this geometry. E6's factorial already bounds the owner-side lever
(fails in EVERY cell incl. interlock-off: 0.584–0.652 vs 0.75).

### 4.2 Design

Yield-aside re-aimed at corridor displacement; the pedestrian_group ≥0.75
gate is explicitly REFUSED as unreachable and returned to the owner as the
E5 §4.4 `person_slow_m` band decision with the derived bound attached (Y-4).

**Y-1 pure proposer `navigation/yield_aside.py`:** candidate aim points ON
the circle of radius `desired_distance_m` about the owner, bearing rotated
±asin(k·step/desired) — |aim−owner| = desired always (this preserves the
DISTANCE LAW; it is NOT by itself a keepout guarantee — see the corrected
contract below). Scoring: worst predicted surface clearance along the
robot→aim segment under constant-velocity rollout of every `dynamic_agents`
track (consume `traffic_aware.coerce_tracks`/`TrackState`; new pure
corridor_min_clearance with SB-1-style substep). Margins DERIVED by
reference: max offset = `person_comfort_band_m` − `person_stop(0.0)` = 1.3 m;
candidate step = `FollowConfig.distance_deadband_m` (0.18); rollout horizon =
`person_comfort_band_m` / max_vx; minimum meaningful improvement =
`OWNER_STAND_OFF_MARGIN_M` (0.10). Hard rejects: any rollout sample <
`person_stop_m` predicted surface clearance; static scan free range along the
candidate bearing < segment + `obstacle_stop_m` (walkability proxy —
does_not_prove); owner-side preference as tiebreak. Fail-closed strict
superset of today: no tracks → inactive('no_strangers'); scan missing →
inactive('no_scan'); no candidate beats un-offset by ≥0.10 m →
inactive('no_meaningful_aside') → today's in-place brake exactly. Side
latched by caller; asymmetric exit (hold while un-offset predicted worst
clearance < `person_slow_m`, release at ≥).

**Skeptic-corrected contract clauses (both mandatory):**
- **Closed-loop equilibrium property:** `_step_direct` holds
  `desired_distance_m` FROM THE AIM, so |robot−owner| is NOT constrained by
  |aim−owner| = desired. Y-1 must specify the aim as a virtual track point
  whose closed-loop equilibrium under the verified `_step_direct` distance
  law satisfies |robot_eq − owner| ≥ `owner_keepout_m` for ALL admissible
  offsets and geometries — property-tested, constants by reference. The
  "safe by construction" language is DROPPED from the safety argument.
- **Lagging-regime admissibility (stall guard):** `_step_direct` holds when
  `distance_error <= deadband` (one-sided, verified). While the robot lags
  the owner (|robot−owner| > desired + deadband), a candidate is admissible
  only if it does not reduce |robot−aim| below desired + deadband — the
  aside must never convert a lagging chase into a hold. The skeptic's worked
  example (lag 2.77, offset 0.6 → |robot−aim| ≈ 1.18 → spurious
  'at_follow_distance') is a canned MUST-REJECT regression case.

**Y-2 wiring:** `follow.py` `_step_direct` only, immediately after
`_clamped_lead` — the proposal replaces the aim point UPSTREAM of the
untouched dispatch chain (smoother → `apply_reactive_safety` → TTC → shaper),
so every band, stop ring, veto and K0 semantics apply identically to the
yielded command. **The yielded aim intentionally bypasses `_clamped_lead`'s
anticipation budget** (standoff − keepout ≈ 0.10 m): that clamp polices
LEAD-anticipation of a moving owner, not commanded stance rotation at
constant owner distance; the replacement policing is Y-1's equilibrium
property (unit-enforced) with the untouched gate's owner band as the runtime
disposer — this rationale and the gate-as-sole-runtime-protection fact go in
the status doc's does_not_prove. `FollowYieldConfig(enabled=False)` mirrors
`FollowPredictionConfig`; `owner_follow.yield_aside` popped per the
runtime.py:528-531 pattern; `BenchFeatures.yield_aside: bool = False`;
additive defaulted telemetry on FollowDecision/snapshot. Behind mode not
wired (unmeasured — documented seam).

**Y-3 additive tier:** `FOLLOW_BENCH_YIELD_EXT` appended in scenarios.py +
NEW `run_follow_bench_yield.py` with its OWN bench id and results namespace
(`evals/companion_nav/results/yield-ext-*`) — FOLLOW_BENCH_V1, its ledger
rows, and the FOLLOW_BENCH_POST_SPEED pins never touched. Two scenarios where
an aside geometrically exists: pedestrian_oncoming_group (free half-corridor)
and pedestrian_group_wide (gap ≥ 5 m so 2.24 m band-pace clearance is
reachable). Thresholds pre-registered only after the flag-OFF baseline is
recorded (Stage A/B, card Y-3).

**Y-4 owner memo:** pedestrian_group ≥ 0.75 returned to the owner as the E5
§4.4 `person_slow_m` decision with the derived bound (needs 2.24 m; corridor
caps ~1.7 m; oracle ceiling 0.616). No behavior, no threshold edit; the v1
episode stays as the honest record. The owner-entry equilibrium term (2.77 m
whenever any stranger is perceived) remains and is NAMED as the residual only
the owner's band decision can move.

### 4.3 Rejected alternatives (all binding)

- **Gate on pedestrian_group ≥ 0.75** — refuted by measurement + derivation
  before design; a pre-registered unreachable gate guarantees a failed lane.
- **Translate the aim laterally (owner-point shift)** — stretches the
  distance law; the oracle showed band REGRESSION on 3 of 4 group cells.
- **Crowd-conditional interlock relaxation** — E6 measured it selling exactly
  the clearance E5 bought (min surface 0.53 → 0.28/0.18); pinned authority.
- **Tune person_slow_m / floors / half-angle to the bench, or lower 0.75** —
  fitting safety constants to an eval (E5 refused) / threshold-massaging.
- **Lateral vy strafing** — direct follow emits vx/vyaw only; new motion
  contract for zero geometric gain.
- **Detour logic inside `apply_reactive_safety`** — inverts propose/dispose;
  the gate is the pinned disposer.
- **Behind-mode wiring this batch** — unmeasured (bench exercises direct
  mode only); documented seam.

### 4.4 Risks

- Oracle fidelity (owner-shift emulation vs aim rotation): sign and derived
  bound make 0.75 recovery implausible either way; no shipped gate depends
  on the oracle.
- If pedestrian_oncoming_group's flag-OFF baseline does not reproduce the
  displacement failure, Y-3 Stage A forces redesign before thresholds freeze.
- Ledger/pin coupling: Y-3 writes an isolated results namespace; diff-vs-OWNS
  is the audit check.
- The nearest-scalar gate limitation (one stranger + owner in the people
  list, verified) makes Y-1's all-tracks rejection LOAD-BEARING, not
  belt-and-suspenders — named in Y-2/Y-3 does_not_prove; `dynamic_agents`
  widening is the gate docstring's own future seam (§8).
- Side-latch dynamics with multiple crossing groups: bench-proven only on
  scripted pedestrians (does_not_prove in full).
- Real-robot transfer: headless kinematic block, capsule pedestrians, no
  curbs/drops until a card owns real occupancy.

---

## 5. Follow-up 5 — DOC-1: stale `person_slow_m` comment (trivial, comment-only)

`configs/navigation/default.yaml` `safety.person_slow_m: 2.0` carries the
comment "Match the runtime reactive person band (2.0 m) so a pedestrian at
2.0-2.5 m is not slow-banded twice by disagreeing envelopes." Since the E5
owner-authorized retune (2026-08-10), the runtime reactive band is 2.5
(`configs/robot.yaml` `safety.person_slow_m: 2.5`) — the comment asserts a
match that no longer holds, and the planner-side 2.0 now DIVERGES from the
runtime band by design-debt, not by design. **Comment-only fix**: rewrite the
comment to document the divergence (runtime band now 2.5 per E5; this
planner-side cost band intentionally left at 2.0 this batch because moving
the VALUE moves frozen v3/v4 rows; alignment is an owner decision — §8).
Moving the value is explicitly OUT OF SCOPE.

---

## 6. Card plan

### 6.1 Waves, sequencing, and the file-ownership matrix

Wave 1 — diagnosis-complete, low-risk, independent lanes (D-15 remedy, jerk
groundwork+wiring+ratchet, doc fix). Wave 2 — visual-search rework (sol pure
modules + cells first, then opus wiring). Wave 3 — yield-aside (behind
everything that touches follow/companion files). A wave opens only after the
previous wave's Fable audit passes (§7).

Intra-wave dispatch order (Cursor enforces; "→" = strictly after):

- **Wave 1:** {DOC-1, D15-A, J-A} at open; D15-A → {D15-B, D15-C}
  (parallel, disjoint); J-A → J-B → J-C.
- **Wave 2:** {VS-1, VS-2, VS-3, VS-6} at open; {VS-1, VS-2, VS-6} → VS-4;
  {VS-3, VS-4, VS-6} → VS-5.
- **Wave 3:** {Y-1, Y-4} at open; Y-1 → Y-2 → Y-3.

Shared-file ownership (one owner per file per wave; rule 5):

| File | Wave 1 | Wave 2 | Wave 3 |
|---|---|---|---|
| `src/parcel_robot/navigation/pipeline.py` | D15-B | VS-4 (slot 1) → VS-5 (slot 2, after VS-4 closes) | — |
| `src/parcel_robot/runtime.py` | J-B | — | Y-2 |
| `evals/companion_nav/runner.py` | J-B (slot 1) → J-C (slot 2, after J-B closes) | — | Y-2 |
| `evals/nav_instruct/runner.py` | D15-B (allowlist + `person_aware_nav`) | VS-4 (allowlist + `lock_on_verify_on_approach`) | — |
| `src/parcel_robot/navigation/follow.py` | — | — | Y-2 (sole owner, whole batch) |
| `src/parcel_robot/navigation/reactive_safety.py` | ZERO owners — MUST-NOT-TOUCH for every card in the batch | | |
| `scripts/ci_gate.py` | J-C | — | — |
| `scripts/mutation_panel.py` | — | VS-6 | — |
| `src/parcel_robot/core/hard_stop.py`, `core/motion_shaping.py`, `navigation/velocity_shaping.py` | J-B | — | — |
| `evals/companion_nav/scenarios.py`, `metrics.py`, `run_follow_bench_v1.py` | metrics/run_follow_bench: J-C | — | scenarios: Y-3 (append-only) |
| `evals/nav_instruct/generator.py`, `run_nav_instruct_v1.py` | — | VS-6 | — |
| `src/parcel_robot/navigation/detection_lock_on.py`, `instructnav_recovery.py` | — | VS-4 | — |
| `src/parcel_robot/navigation/value_directed_scan.py`, `value_map.py`, `instructnav/search_entity.py` | — | VS-5 | — |
| `configs/navigation/default.yaml` | DOC-1 (comment only) | — | — |

Re-baselining rule (from adjudication #15): every flag-off identity gate is
measured against the PREDECESSOR'S LANDED STATE. Concretely: J-C and Y-2
verify all PRE-EXISTING fields of the committed dd2e857 row byte-identical
(7/9, mean_band_fraction 0.708782386458857, jerk 1.2187, report-aggregate
min_pedestrian_surface_m 0.5299999999999998, dwell 2.3, collisions 0), with
J-C's additive fields present as landed; VS-4's flag-off control runs with
BOTH new nav flags absent and must byte-reproduce the frozen v4 baseline row.

Executor key: sol = new pure modules with frozen contracts (new files only);
opus = existing-file wiring. All 17 OWNS lists below were path-verified
against the tree at dd2e857 (every existing file exists; every NEW path is
absent) — the batch-r2 lesson applied.

---

### Wave 1

### Card DOC-1 [opus] — stale person_slow_m comment + documented divergence
Comment-only edit in `configs/navigation/default.yaml` (§5). Replace the
"Match the runtime reactive person band (2.0 m)" comment with the divergence
record: runtime band retuned to 2.5 (E5, owner-authorized, 2026-08-10); this
planner-side people-cost band intentionally stays 2.0 this batch (moving the
value moves frozen v3/v4 rows); alignment = owner decision, referenced in
scrum/20260811/task_1/FOLLOWUP_DESIGNS.md §8.
- READ FIRST: §5 above; configs/robot.yaml safety block (:309-318);
  E5_PERSON_CLEARANCE_STATUS.md header table.
- OWNS: `configs/navigation/default.yaml` (comment lines ONLY).
- MUST NOT TOUCH: every value/key in the file; every other config; all code.
- GATE: `git diff` shows changed lines are comments only (no key or value
  differs); full test suite byte-unaffected; ci_gate --tier commit green.

### Card D15-A [sol] — person_keepout pure module (derived ring + strict compliant-speed + D-15 pin test)
New pure module deriving (never restating) from a `ReactiveSafetyPolicy`
instance: the veto ring `person_stop_m + v·reaction_time_s +
owner_collision_envelope_m`, a grid-cost painter for the ring, and
`compliant_speed(clearance)` = the FLOAT-LATTICE SUPREMUM — the largest
float v for which the gate's own veto inequality
(`clearance <= person_stop_m + v·reaction_time_s`) evaluates False (found on
the float lattice, e.g. nextafter-stepping/bisection; zero new literals;
adjudication #5). Includes the D-15 geometry pin.
- READ FIRST: reactive_safety.py:185-320 (read-only), E5_STATUS §2, §1 of
  this record.
- OWNS (all NEW; nothing existing edited): `src/parcel_robot/navigation/person_keepout.py`,
  `tests/test_person_keepout.py`. The no-literal-drift assertions live INSIDE
  the new test file (adjudication #20) — `tests/test_authority_no_literal_drift.py`
  is NOT edited.
- MUST NOT TOUCH: reactive_safety.py, follow.py, configs/**, instructnav/**,
  every existing file.
- GATE: pin test reproduces the measured D-15 veto (clearance 1.2632 vs
  threshold 1.3020 at v=0.85, reaction 0.12) to 4 decimals;
  compliant_speed(1.2632) ≈ 0.5266 with the gate inequality False at that v
  and True at nextafter(v, +inf); property test over randomized
  (clearance, policy): for all v > compliant_speed the inequality vetoes, at
  v = compliant_speed it does not; all constants read from a
  ReactiveSafetyPolicy instance (no-literal-drift assertions in the new test
  file); ci_gate --tier commit green.

### Card D15-B [opus] — person_aware_nav flag wiring (grid keepout cost + proposer-side speed cap)
Wire `person_keepout` into pipeline.py behind flag `person_aware_nav`,
default OFF, flag-off byte-identical: (i) paint person/owner keepout costs
into the grid plan so routes detour around humans; (ii) cap the pipeline's
COMMANDED speed strictly below the veto boundary via
`compliant_speed(clearance)` when a person/owner is within the slow band —
the ring shrinks because the PROPOSAL slows, while `apply_reactive_safety`
is untouched and still disposes every tick. Add `person_aware_nav` to
`ALLOWED_NAVIGATOR_OVERRIDES` (additive one-liner; D15-B is Wave 1's sole
owner of that file; VS-4 adds its own flag in Wave 2).
- READ FIRST: pipeline.py grid_track/_step_semantic_resolution path,
  nav_instruct runner.py ALLOWED_NAVIGATOR_OVERRIDES (V-D/V-E pattern), §1
  of this record.
- OWNS: `src/parcel_robot/navigation/pipeline.py` (Wave-1 owner),
  `evals/nav_instruct/runner.py` (allowlist line, additive), NEW
  `tests/test_person_aware_nav.py`.
- MUST NOT TOUCH: navigation/reactive_safety.py, navigation/follow.py,
  runtime.py, configs/**, evals/nav_instruct/episodes/**, results/ledger
  prefix, instructnav/arbiter.py + scoring.py.
- GATE (pre-registered, existing harness): (1) flag-off byte-identical —
  fresh v4 25-ep minival reproduces the frozen row
  nav-instruct-v1-baseline-v4-20260811T070536Z bit-for-bit; (2) flag-on,
  FULL 25-ep protocol (dtg is context-dependent — protocol pinned), v3 AND
  v4: nav-object_goal-D-15-109547e2 flips to success in both, run twice
  (1-cm band-edge margin); (3) collisions 0, false_arrival 0, no
  currently-passing episode lost (v4 SR ≥ 0.24); trace-level floor assert:
  minimum person clearance during detour ≥ person_stop_m AND the predictive
  criterion (clearance > person_stop_m + v_commanded·reaction) holds at
  every detour tick — these asserts are CONSISTENCY CHECKS; the unmodified
  `apply_reactive_safety` remains the safety mechanism/disposer
  (adjudication #6); (4) ci_gate green; any frozen row moves → STOP and
  report (rule 2).

### Card D15-C [sol] — declared-bystander clearance-sweep cell + attribution record + marginality annotation
New additive eval cell with DECLARED bystanders + the attribution doc.
Counterfactual restated per adjudication #12 (the E5 guard makes
person_stop=1.0 unrunnable on new code): the cell sweeps the BYSTANDER'S
geometry — bystander placed on the route at parametric clearance steps
spanning the veto boundary (clearance > 1.3020 m at v=0.85 passes; below
deadlocks) — and the person_stop=1.0 outcome is computed ANALYTICALLY from
D15-A's formula, labeled derived-not-run. Cell writes its own report files;
NEVER appends to results/ledger.jsonl.
- READ FIRST: E8 §9, E5 §6 does_not_prove, generator.py additive-tier
  pattern, §1 + Appendix A.3 of this record.
- OWNS (all NEW): `evals/nav_instruct/person_cell.py`,
  `tests/test_person_cell.py`, `scrum/20260811/task_1/D15_ATTRIBUTION.md`
  (bisect table + mechanism + isolation minival from Appendix A.3 + E5
  correction note (additive cross-reference; E5's file untouched) +
  does_not_prove: does not prove the retune optimal, only causal; does not
  prove detour safety at higher pedestrian density — the sweep cell's job).
- MUST NOT TOUCH: episodes/v1|v2|v3|v4/**, generator.py frozen sets, ledger
  prefix, mutation_panel.json, reactive_safety.py.
- GATE: cell reproduces the D-15 deadlock signature (veto every tick,
  planner `planned|clear`, 0 m progress) on a synthetic declared-bystander
  episode at person_stop=1.2; geometric sweep emits pass/deadlock/detour per
  clearance step with the measured boundary at 1.2 + v·0.12; derived-not-run
  person_stop=1.0 row carries its label; marginality table for the 4 moved
  episodes with measured band-edge margins; all 4 DIGEST_SENTINELS
  byte-identical (scripts/ci_gate.py); ledger append-only prefix unchanged;
  ci_gate green.

### Card J-A [sol] — stop-ramp pure module (monotone nominal-stop decay + boundary check)
`core/stop_ramp.py`: `nominal_stop_step` = per-axis
`_move_toward(v, 0, max_accel·dt)` reproducing the pre-6bd945d emergency
semantics exactly (`git show 60ecea2:src/parcel_robot/navigation/velocity_shaping.py`
lines 97-120), rate derived from `MotionShapingConfig.limits()`;
`enforce_monotone_stop(prev, candidate)` fails closed (magnitude increase,
sign flip, non-finite → None → caller must HARD_STOP).
- READ FIRST: the 60ecea2 emergency hunk above; core/hard_stop.py;
  core/motion_shaping.py (`limits()`); §3 of this record.
- OWNS (all NEW): `src/parcel_robot/core/stop_ramp.py`,
  `tests/test_stop_ramp.py`.
- MUST NOT TOUCH: every existing file; especially navigation/
  reactive_safety.py, core/hard_stop.py, runtime.py.
- GATE: property tests exhaustive on the frozen contract — for all finite
  inputs |v'| ≤ |v| per axis, sign preserved or zero, zero reached in
  ceil(|v|/(max_accel·dt)) steps, dt≤0/non-finite fail closed;
  enforce_monotone_stop rejects every magnitude increase / sign flip /
  non-finite; bit-equality vs the reconstructed 60ecea2 `_move_toward`
  semantics on a seeded (v, accel, dt) grid; ci_gate green (trivially — no
  existing-file change).

### Card J-B [opus] — severity-split stop shaping, flag-gated default OFF (re-gated ramp; safety-closed per adjudications #2/#3/#4)
The full re-specified wiring of §3.2 Part 2. Deliverables: (a)
`core/hard_stop.py`: `NOMINAL_STOP = 3` APPENDED (existing three int values
unchanged, pinned by test); finalize branch consumes
`stop_ramp.enforce_monotone_stop`, falls closed to the untouched HARD_STOP
branch; the finalize TAIL becomes explicitly fail-closed (CLEAR returns
candidate; ANY other severity → HARD_STOP; byte-identical for all reachable
inputs today, property-tested for unknown members). (b)
`velocity_shaping.py`: additive `stop=` keyword consuming
`nominal_stop_step`; `emergency=True` byte-identical. (c)
`core/motion_shaping.py`: flag `nominal_stop_ramp` default False. (d)
`runtime.py` predicate split (:4548-4557, :4690-4698, :4713-4726): hard set
unchanged (proximity 'stopped' / arbiter emergency / input-health / active
None — all still emergency + HARD finalize; intent EXPIRY stays
fail-closed); nominal = zero INTENT alone, only under the flag; per-tick
RE-GATE of the ramp candidate through the untouched `apply_reactive_safety`
(+ TTC verdict) with any stop verdict preempting to HARD exact (0,0,0) that
same tick + reset obligations; resume-reset (first non-zero intent → shaper
state zeroed first). (e) replica `_DispatchReplica._shape` mirrors the split
UNDER THE FLAG, classifying on the INTENT (operand parity); flag-off replica
classification byte-untouched; both stopping predicates added to a
symbol-digest pin (REACTIVE_SAFETY_PIN pattern, tests/test_dynamic_layer.py
precedent).
- READ FIRST: §3.2 of this record (the re-spec is normative), S-A_STATUS.md
  P0-A property tests, runtime.py:4548-4562 + `_finalize_for_actuator`,
  runner.py `_DispatchReplica.step/_shape`, scripts/ci_gate.py model-off
  gate.
- OWNS: `src/parcel_robot/core/hard_stop.py`,
  `src/parcel_robot/navigation/velocity_shaping.py`,
  `src/parcel_robot/core/motion_shaping.py`, `src/parcel_robot/runtime.py`
  (Wave-1 owner; enumerated-patch fallback per rule 5 only if Cursor
  reorders), `evals/companion_nav/runner.py` (Wave-1 slot 1;
  `_DispatchReplica._shape` + the flag plumb only), NEW
  `tests/test_nominal_stop_wiring.py`.
- MUST NOT TOUCH: navigation/reactive_safety.py, navigation/collision.py,
  instructnav/**, configs/** person values, evals/nav_instruct/**,
  FOLLOW_BENCH scenario/metric definitions, follow.py.
- GATE (pre-registered, full 11-scenario FOLLOW_BENCH_V1; scratch runs, no
  ledger append; official row only on owner flag decision): (1) flag OFF
  byte-identical — model-off-non-inferiority green AND a full bench run
  reproduces the committed row exactly (7/9, mean_band_fraction
  0.708782386458857, jerk 1.2187); (2) flag ON —
  mean_rms_commanded_jerk_mps3 ≤ 1.05 (design cell 1.0039; a miss under the
  re-gated dynamics is STOP-and-report, never a margin renegotiation),
  min_pedestrian_surface_m == 0.5299999999999998 bit-identical,
  personal_space 2.3, hard_collision 0, pedestrian_contact 0,
  follow_success ≥ 7/9, reactive_gate_stop_total == 2; (3) property tests:
  P0-A interrupt-at-every-stage exact-zero untouched-green; injected safety
  stop (gate/arbiter/input-health) mid-ramp dispatches exact (0,0,0) that
  same tick; ramp ticks are monotone non-increasing per axis AND each
  candidate was disposed by the untouched gate; resume after nominal ramp is
  byte-equal to flag-off resume-from-zero; NOMINAL_STOP=3 with the three
  existing int values unchanged and unknown severities failing closed to
  HARD_STOP; (4) REACTIVE_SAFETY_PIN symbols unmoved; the new
  stopping-predicate symbol pin green; ci_gate green. does_not_prove: the
  pre-existing flag-off replica/runtime operand divergence is recorded, not
  fixed (fixing moves the pinned row; owner-gated).

### Card J-C [opus] — jerk ratchet + attributed re-pin + additive nominal-jerk metric (after J-B closes)
§3.2 Parts 1 and 3. New ci_gate gate `follow-bench-jerk-ratchet` mirroring
`evaluate_latency_ledger`/`evaluate_latency_ratchet` (~:525-615): committed
baseline `jerk_baseline.json` (1.2187, provenance = §3.1 + the two commits
60ecea2/6bd945d), reads the latest shipped FOLLOWBENCH_LEDGER row carrying
the field, reds iff > baseline × LATENCY_TAIL_MARGIN (1.20 by reference),
skip-with-note when absent, seeded-spike self-test.
FOLLOW_BENCH_POST_SPEED gains the jerk value + three-component attribution
(corrects E6's band-edge guess on the record). Additive per-step `emergency`
flag + `mean_rms_commanded_jerk_nominal_mps3` in report aggregate + ledger
row (report-only; no existing field edited).
- READ FIRST: scripts/ci_gate.py:190 + :525-615 + :205-207;
  run_duplex_v1.py:114 + :509-510 latest-row pins; §3 of this record.
- OWNS: `scripts/ci_gate.py`, NEW
  `evals/companion_nav/results/jerk_baseline.json`,
  `evals/companion/duplex_v1/run_duplex_v1.py`,
  `evals/companion_nav/metrics.py` + `runner.py` (Wave-1 slot 2, after J-B
  closes; additive step-flag/aggregate only) + `run_follow_bench_v1.py`,
  NEW `tests/test_ci_gate_jerk_ratchet.py`.
- MUST NOT TOUCH: existing ledger rows (append-only), all frozen
  manifests/DIGEST_SENTINELS, evals/nav_instruct/**, any FOLLOW_BENCH
  scenario definition, runtime.py, core/**.
- GATE: (1) ci_gate green with the new gate PASSING on the real ledger
  (1.2187 ≤ 1.2187·1.20 = 1.46244); (2) self-test reddens on a seeded row
  at 1.47; (3) skip-with-note proven on a field-less ledger slice; (4) a
  fresh bench run's report carries the additive nominal metric while every
  pre-existing aggregate field is byte-identical in name and semantics
  (old-row parsing unaffected; hard-safety output string unchanged) — the
  fresh run writes to a SCRATCH results dir (no ledger append), or if
  appended officially every latest-row-pinned value (7/9,
  0.708782386458857, 1.2187) is byte-identical to the prior latest row
  (adjudication #22); (5) baseline JSON committed with the three-component
  provenance; any later re-pin (post owner flag-flip) is owner-authorized
  with 2x2 and only DECREASES the baseline.

---

### Wave 2 (opens after the Wave-1 Fable audit)

### Card VS-1 [sol] — verify-on-approach lock-on state machine + per-kind refinement gate (pure, frozen contract)
§2.2(b) + the per-kind refinement gate of §2.2(a)(iii). Also owns the
view-ADMISSION rule (independent-evidence): minimum angular separation
between admissible M-of-N views = 2π / `ScanPlanSpec.n_stops` from
`instructnav/scan.py` `full_turn_scan_spec`, consumed by reference
(adjudication #8; owner-2x2 fallback in §8 if verify rejects the
derivation).
- READ FIRST: §2 of this record; instructnav/scoring.py
  (`object_near_envelope_m`, `p_inside_goal_region`, the interchangeable
  ranking's boundary margin — read-only), detection_lock_on.py
  (LockOnDecision), detection_adapter/metric_localizer.py,
  instructnav/scan.py (`ScanPlanSpec`).
- OWNS (all NEW): `src/parcel_robot/navigation/lock_on_verify.py`,
  `tests/test_lock_on_verify.py`.
- MUST NOT TOUCH: pipeline.py, runtime.py, instructnav/arbiter.py, core/**,
  reactive_safety.py, velocity_shaping.py, multi_view_confirm.py.
- GATE: pytest green — (1) checkpoint radii bit-identical (struct.pack
  equality, E5/E6/E8 pattern) to `object_near_envelope_m` derivations, and
  the view-admission angle bit-identical to 2π/n_stops by reference (no new
  literals); (2) the V-B view-consistent-phantom trace (constant
  bearing/range, no covariance shrink on closure) ends REFUTED, never
  VERIFIED, at every operating point; (3) covariance-trace increase or
  persistence miss at any checkpoint ⇒ veto verdict; (4) refinement gate
  per kind: REGION — fused point outside the grounded polygon dilated by the
  ranking's boundary margin ⇒ REJECT (the measured B-05 4.78 m displacement
  is a canned rejected case); OBJECT — fused xy outside the vicinity band or
  Mahalanobis-inconsistent with D2 covariance ⇒ REJECT; (5) three
  consecutive same-pose ticks are ONE admissible view (self-confirmation
  killed at unit level); ci_gate green.

### Card VS-2 [sol] — false-positive memory: negative evidence with TTL/decay (pure, frozen contract)
§2.2(c).
- READ FIRST: §2 of this record; multi_view_confirm.py (its window-failure
  memory stays untouched and distinct).
- OWNS (all NEW): `src/parcel_robot/detection_adapter/false_positive_memory.py`,
  `tests/test_false_positive_memory.py`.
- MUST NOT TOUCH: multi_view_confirm.py, metric_localizer.py,
  pixel_detections.py, camera_channel/**.
- GATE: pytest green — record_refutation((class, world-cell)) ⇒
  suppressed() true within TTL, false after decay; the
  commit-then-refute-then-re-encounter sequence (V-B phantom followed by
  VS-1 refutation) suppressed on the second encounter; does_not_prove
  recorded for real-camera behavior; `tests/test_vb_multiview_metric.py`
  byte-unchanged (still 10 passed); ci_gate green.

### Card VS-3 [sol] — value-map evidence policy incl. miss-painting + evidence_count contract (pure)
§2.2(d) pure half.
- READ FIRST: §2 of this record; value_map.py (SemanticValueMap2D/ViewCone),
  DetectionMsg contract, instructnav/siglip.py match surface.
- OWNS (all NEW): `src/parcel_robot/navigation/value_evidence.py`,
  `tests/test_value_evidence.py`.
- MUST NOT TOUCH: value_map.py, search_entity.py, pipeline.py,
  value_directed_scan.py.
- GATE: pytest green — (1) paint tuples derive value from the query-match
  score (embed seam, string_fallback preserved), not substring floors; (2) a
  scanned cone with zero query evidence paints a MISS (value decrease); (3)
  evidence_count == exactly the number of query-relevant evidence paints, 0
  for background/miss-only — the number VS-5's empty-map delegation keys on;
  ci_gate green.

### Card VS-6 [opus] — additive search-exercising eval cells + phantom mutant (v4 untouched)
§2.2(e). The mutation-panel regeneration is a DECLARED in-tree deliverable:
running the panel rewrites `evals/nav_instruct/results/mutation_panel.json`
(legal — not in DIGEST_SENTINELS) with exactly +1 mutant row and all
pre-existing verdicts unchanged, proven by before/after diff in the status
doc. Development iterations run in a scratch rsync; only the final
regeneration lands in-tree (adjudications #9/#21-adjacent).
- READ FIRST: §2 of this record; generator.py additive-tier pattern;
  scripts/ci_gate.py:189 + :777 (panel freshness gate); E4 byte-proof
  pattern.
- OWNS: `evals/nav_instruct/generator.py` (additive v4s entrypoint), NEW
  `evals/nav_instruct/episodes/v4s/**` (own manifest),
  `evals/nav_instruct/run_nav_instruct_v1.py` (--episode-set seam; refuses
  --freeze on v4s this cycle), `scripts/mutation_panel.py` (one ADDITIVE
  view-consistent-phantom mutant) + the regenerated
  `evals/nav_instruct/results/mutation_panel.json`, NEW
  `tests/test_v4s_search_cells.py`.
- MUST NOT TOUCH: evals/nav_instruct/episodes/v4/** and every
  DIGEST_SENTINELS-pinned file, runner.py scoring rules, rescore.py frozen
  traces, cam_foundation_pack.json, results/ledger.jsonl.
- GATE: (1) all 4 DIGEST_SENTINELS byte-identical via scripts/ci_gate.py
  (v4 manifest sha256 `b2945444…`); the E8 minival-report digest
  `4113607b…` additionally byte-unmoved as a second invariant
  (adjudication #18 — it is the MINIVAL digest, not the manifest hash);
  (2) v4s: ≥20 paired episodes per axis (look-around-required beyond the
  initial scan pose; beyond-the-block frontier), aiming for ≥60/axis if
  routable yield allows (powers VS-5's +10pp; see its gate), with
  generation-time A*-routability asserted per episode; (3) control arm on
  v4s byte-reproduces across two runs (determinism); (4) the phantom mutant
  reddens ≥1 harness via the differential-authority false-arrival channel
  (additive row; panel verdict logic untouched; +1-row diff with prior
  verdicts unchanged); ci_gate green.

### Card VS-4 [opus] — arrival-integrity + verify-on-approach wiring (Wave-2 pipeline.py slot 1; after VS-1/VS-2/VS-6)
§2.2(a)+(b) wiring. ALL commit-path changes are CONDITIONAL on the existing
`detection_lock_on` / new `lock_on_verify_on_approach` flags; the
unconditional path is byte-identical (adjudication #9). Adds
`lock_on_verify_on_approach` to `ALLOWED_NAVIGATOR_OVERRIDES` (Wave-2 owner
of that file; D15-B's Wave-1 edit already landed — additive line alongside
it, adjudication #16).
- READ FIRST: §2 of this record; pipeline.py :2298-2321 / :2541-2549 /
  :1673-1686 / :1809-1826; the P0-C stamp/flush seam; V-D/V-E allowlist
  pattern.
- OWNS: `src/parcel_robot/navigation/pipeline.py` (Wave-2 slot 1 — sole
  owner until VS-4 closes, then hands to VS-5),
  `src/parcel_robot/navigation/detection_lock_on.py` (session integration
  seam only), `src/parcel_robot/navigation/instructnav_recovery.py`,
  `evals/nav_instruct/runner.py` (allowlist line, additive),
  `tests/test_ve_detection_lock_on.py` (extend).
- MUST NOT TOUCH: runtime.py, instructnav/arbiter.py + scoring.py (consume
  only — K0/veto semantics untouchable), reactive_safety.py,
  velocity_shaping.py, core/**, camera_channel/**, configs/**,
  evals/nav_instruct/episodes/**.
- GATE (pre-registered, existing harness, frozen v4 minival, paired arms,
  --mode candidate): (1) flag-OFF control (BOTH new nav flags absent)
  byte-reproduces the committed v4 frozen-baseline row; (2)
  detection_lock_on(+lock_on_verify_on_approach) arm: false_arrival == 0
  AND paired episodes lost == 0 (v3 measured: 1 false arrival, 2 lost —
  both to zero) AND per-tier |SR_lock − SR_off| ≤ 0.10; (3) structural
  pytest: for every commit, arrival_goal_region geometry provenance ==
  grounded reference (never the fused point), and for interchangeable
  queries the committed instance == the flag-off ranking's instance; (4)
  VS-6's v4s phantom cells, flag on: zero phantom arrivals AND — the
  non-vacuity conjuncts (adjudication #19) — ≥1 lock-on
  COMMIT-then-REFUTATION event (lock_on_verify telemetry) and ≥1 FP-memory
  suppression hit on re-encounter, asserted from traces; (5)
  model-off-non-inferiority green (flag-off byte-identical); ci_gate green.

### Card VS-5 [opus] — evidence-fed value map wiring + empty-map == exact baseline (Wave-2 pipeline.py slot 2; after VS-4 closes; deps VS-3, VS-6)
§2.2(d) wiring. The empty-map delegation calls the FLAG-OFF SCORER OBJECT
itself (never a re-implementation) so float-identity is achievable.
- READ FIRST: §2 of this record; pipeline.py `_paint_scan_observation`
  (:2877-2906) + C2 call sites (:2566, :2573-2597); search_entity.py
  scorers (:106-111, :444-465, :493-497); PlanTimePriorCache gate.
- OWNS: `src/parcel_robot/navigation/pipeline.py` (Wave-2 slot 2),
  `src/parcel_robot/navigation/value_directed_scan.py` (choose_next_look
  empty-evidence behavior), `src/parcel_robot/instructnav/search_entity.py`
  (ValueMapFrontierScorer empty-delegation),
  `src/parcel_robot/navigation/value_map.py` (evidence_count surface),
  `tests/test_value_directed_search.py` + `tests/test_value_map.py`
  (extend).
- MUST NOT TOUCH: runtime.py, instructnav/scoring.py, detection_adapter/**,
  camera_channel/**, evals episodes, core/**, reactive_safety.py.
- GATE (pre-registered, existing harness): (1) EMPTY-MAP NO-OP PROOF:
  value_directed_search ON with evidence painting disabled == flag-OFF,
  per-episode outcomes AND SPL float-identical on the full v4 minival
  (E4's accidental 0-flip tie becomes a designed, gated property); (2)
  EFFECT GATE on VS-6's v4s axes, re-registered coherently (adjudication
  #17): paired flag-on-vs-off per axis; SHIP requires net paired flips
  (wins − losses) ≥ 6 with losses == 0 — equivalently exact-McNemar
  two-sided p = 2·0.5^b ≤ 0.031 — AND ΔSR ≥ +10pp; the harness computes
  exact McNemar (no approximation); at n=20/axis this floor equals +30pp,
  the DESIGNED expectation for cells built to be unfindable flag-off; at
  n≥60/axis (VS-6's aim) +10pp with 6 net flips is directly detectable; a
  true-but-smaller effect FAILS the gate → STOP-and-report with the
  measured delta and power note, never a silent margin shrink; (3) zero
  runtime model calls in the control tick (existing PlanTimePriorCache gate
  kept); flag-off byte-identical; ci_gate green.

---

### Wave 3 (opens after the Wave-2 Fable audit)

### Card Y-1 [sol] — yield_aside pure proposer (corridor min-clearance + aim rotation; equilibrium + stall clauses)
§4.2 Y-1 including BOTH skeptic-corrected contract clauses (equilibrium
property; lagging-regime admissibility).
- READ FIRST: §4 of this record + Appendix A; traffic_aware.py (consume
  TrackState/coerce_tracks, do not edit); reactive_safety.py:30-60
  (OWNER_STAND_OFF_MARGIN_M — read-only); follow.py `_step_direct` +
  `_clamped_lead` (the verified one-sided deadband + budget); E6 §4.3.
- OWNS (all NEW): `src/parcel_robot/navigation/yield_aside.py`,
  `tests/test_yield_aside.py`.
- MUST NOT TOUCH: follow.py, reactive_safety.py, collision.py, runtime.py,
  traffic_aware.py, configs/**, evals/**.
- GATE: unit-exact, CI-green — (a) |aim−owner| == desired_distance_m for
  every active proposal (== not approx); (b) fail-closed triple
  (no_strangers / no_scan / no_meaningful_aside → today's behavior);
  (c) no candidate ever samples < person_stop_m predicted surface clearance
  — property over RANDOMIZED FULL TRACK SETS, seeded (load-bearing given
  the gate's nearest-scalar people list; adjudication #11); (d) derived
  margins asserted by reference (improvement quantum ==
  OWNER_STAND_OFF_MARGIN_M; max offset == person_comfort_band_m −
  person_stop(0.0)); (e) determinism (identical inputs → bit-identical
  proposals); (f) asymmetric exit proven; (g) EQUILIBRIUM PROPERTY: the
  closed-loop fixed point of the verified `_step_direct` distance law
  satisfies |robot_eq − owner| ≥ owner_keepout_m for all admissible
  proposals over randomized geometries; (h) STALL GUARD: while
  |robot−owner| > desired + deadband, no admissible candidate reduces
  |robot−aim| below desired + deadband; the skeptic's worked example
  (lag 2.77, offset 0.6) is a canned MUST-REJECT case; ruff clean;
  ci_gate green (trivially — no existing file edited).

### Card Y-2 [opus] — follow wiring, flag plumbing, flag-off identity (Wave-3 owner of runtime.py + companion runner.py + follow.py)
§4.2 Y-2. The `_clamped_lead` exemption rationale and the
gate-as-sole-runtime-protection fact are stated in the status doc
does_not_prove (adjudication #10); "safe by construction" language is
banned from the status doc.
- READ FIRST: §4 of this record; follow.py :585-735; runtime.py :506-536
  (prediction plumb pattern); runner.py BenchFeatures +
  `_follow_config_from_store`; the J-B/J-C landed diffs (re-baseline).
- OWNS: `src/parcel_robot/navigation/follow.py` (`_step_direct` aim swap
  after `_clamped_lead`, FollowYieldConfig param, additive
  FollowDecision/snapshot fields), `src/parcel_robot/runtime.py` (Wave-3
  owner; ONLY the owner_follow.yield_aside pop mirroring :528-531),
  `evals/companion_nav/runner.py` (Wave-3 owner;
  BenchFeatures.yield_aside=False + `_follow_config_from_store` plumb),
  NEW `tests/test_follow_yield_wiring.py`.
- MUST NOT TOUCH: reactive_safety.py, collision.py, core/**, configs/**
  (flag stays code-default OFF; no yaml ships),
  evals/companion_nav/scenarios.py, results/**, any frozen manifest.
- GATE: (1) flag-off identity, re-baselined on the J-C landed state
  (adjudication #15): full FOLLOW_BENCH_V1 run reproduces every
  PRE-EXISTING field of the committed dd2e857 row bit-identically —
  follow_success 7/9, mean_band_fraction 0.708782386458857, jerk 1.2187,
  report-aggregate min_pedestrian_surface_m 0.5299999999999998, dwell 2.3,
  hard_collision_total 0 — with J-C's additive fields present as landed
  (scratch run, no ledger append); model-off-non-inferiority green.
  (2) Flag-ON inertness where no strangers: straight_follow / owner_stops /
  owner_turn_90 / follow_turn_corner / owner_corner_loss bit-identical to
  flag-off (trigger requires strangers). (3) Wiring test proves the
  proposal is applied UPSTREAM of `apply_reactive_safety` (gate verdict
  unchanged for a fixed command, aim changed). (4) REACTIVE_SAFETY_PIN
  untouched-green; digest sentinels 4/4; ci_gate green. Any frozen row
  moves → STOP and report (rule 2). does_not_prove: nearest-scalar gate
  limitation; clamp-exemption rationale; scripted-pedestrian bench scope.

### Card Y-3 [opus] — additive yield tier: oncoming/wide scenarios + pre-registered two-stage measurement (after Y-2)
§4.2 Y-3.
- READ FIRST: §4 of this record + Appendix A oracle table; E6 §4.2-4.3;
  metrics.py band/dwell definitions.
- OWNS: `evals/companion_nav/scenarios.py` (APPEND-ONLY: new
  FOLLOW_BENCH_YIELD_EXT tuple; FOLLOW_BENCH_V1 tuple byte-untouched), NEW
  `evals/companion_nav/run_follow_bench_yield.py` (own bench id + own
  results namespace `evals/companion_nav/results/yield-ext-*`), NEW
  `scrum/20260811/task_1/Y-3_STATUS.md`.
- MUST NOT TOUCH: results/ledger.jsonl and existing report jsons
  (FOLLOW_BENCH_POST_SPEED pins), run_follow_bench_v1.py, runner.py
  internals beyond consuming, evals/nav_instruct/**.
- GATE (pre-registered two-stage): STAGE A (flag OFF): both new scenarios
  recorded; pedestrian_oncoming_group must show the displacement failure
  (stance inside the group's swept corridor at closest approach, band
  < 0.60) else the scenario is REDESIGNED before any flag-ON run. STAGE B
  (flag ON): pedestrian_oncoming_group band ≥ baseline + 0.15 AND stance at
  closest approach outside the swept corridor by ≥ person_stop_m;
  pedestrian_group_wide band ≥ 0.75; both cells hard_collision 0,
  pedestrian_contact 0, intimate 0.0, per-episode min ped surface ≥ 1.2.
  V1 REGRESSION (flag ON, full 11): no episode band lower than the dd2e857
  row by > 0.01, no per-episode min ped surface decrease, aggregate
  min_pedestrian_surface_m 0.5299999999999998 UNCHANGED, dwell ≤ 2.3 s,
  collisions 0. Ship only if all hold; any miss → STOP-and-report with
  per-step attribution (does_not_prove mandatory). ci_gate green; git diff
  scoped to OWNS.

### Card Y-4 [opus] — pedestrian_group infeasibility record + owner band-decision memo (docs only; may open at wave start)
§4.2 Y-4. First action: EXTRACT the archived diagnostic scripts and
isolation table from Appendix A of this record into
`scrum/20260811/task_1/evidence/` (trace_group.py, oracle_yield.py,
minival_isolation.txt) — the scratchpad originals do not survive GC
(adjudication #21). Scripts are archived with their session-scratch paths;
Y-4 re-points the two sys.path inserts and the config path at the committed
tree when re-running.
- OWNS (all NEW): `scrum/20260811/task_1/YIELD_DESIGN_RECORD.md`,
  `scrum/20260811/task_1/evidence/{trace_group.py,oracle_yield.py,minival_isolation.txt}`.
- MUST NOT TOUCH: everything else — zero code, zero thresholds, zero
  configs.
- GATE: both archived scripts re-run against the committed tree reproduce
  the recorded table (band 0.584 baseline; oracle cells
  0.568/0.552/0.540/0.616; cut_in 0.525/0.530/0.515) within float identity;
  the memo states the derived 2.24 m-vs-~1.7 m bound, restates E5 §4.4's
  person_slow_m lever verbatim with its measured two-sided price, and
  carries does_not_prove (scripted pedestrians, oracle-emulation fidelity,
  headless-kinematic world). ci_gate green (docs only).

---

## 7. Orchestration note

Cursor dispatches; Fable audits. The pre-registered audit protocol of
`NEXT_BATCH_PLAN.md` (§"Fable audit protocol") applies verbatim per wave:
(1) fresh `ci_gate --tier commit` green or the wave is returned;
(2) diff-vs-ownership per card against OWNS (the §6.1 matrix is the
authority for shared files — any out-of-scope edit returns to the executor
with the diff); (3) one named gate per card re-run independently;
(4) adversarial refute-first verify on the safety-adjacent wiring cards —
this batch that set is **J-B, VS-4, Y-2** (plus any card whose claims touch
a frozen row); (5) verdict per card CONFIRMED / RETURNED-with-findings in
`scrum/20260811/task_1/AUDIT_WAVE<N>.md`; cross-card conflicts → Fable
arbitration, same file. Additional batch-specific audit items:
- Wave 1: verify DOC-1's diff is comment-only; verify J-B's flag-off bench
  row and the D15-B frozen-row byte-identity YOURSELF (not from the status
  doc); check the stopping-predicate symbol pin exists and covers both
  machines.
- Wave 2: verify the v4 sentinels (4/4) and the mutation-panel +1-row diff;
  verify VS-4's non-vacuity counters are read from traces, not asserted.
- Wave 3: verify Y-3 wrote only to its own results namespace (ledger tail
  unchanged); verify Y-2's re-baselined identity against the J-C landed
  row.
- Measurement discipline for every executor: development/measurement runs
  that WRITE (eval harnesses append ledger rows/reports; the mutation panel
  rewrites its artifact) run in a scratch rsync of the repo, main venv by
  absolute path; only declared deliverables land in-tree.

## 8. OPEN QUESTIONS (owner-gated; no card in this batch decides these)

1. **Flag defaults after measurement** — `person_aware_nav`,
   `motion_shaping.nominal_stop_ramp`, `lock_on_verify_on_approach`,
   `value_directed_search`, `yield_aside`: each flip is an owner decision on
   the batch's measured numbers; nominal_stop_ramp's flip additionally
   re-pins the jerk baseline downward with 2x2 (J-C).
2. **pedestrian_group ≥ 0.75** — unreachable under the owner-authorized
   2.5 m stranger band (derived 2.24 m needed vs ~1.7 m corridor; oracle
   ceiling 0.616). The lever is E5 §4.4's `person_slow_m` with its measured
   two-sided price (Y-4 memo). The threshold stays honestly red until the
   owner decides.
3. **D-15 marginality** — 1-cm band-edge episode; the honest eventual fix is
   an owner-authorized v5 with margin-aware goal bands (E8 precedent). Not
   this batch.
4. **Cross-episode state leakage in the nav_instruct harness** (3.0301 /
   3.0268 / 3.0293 across protocols; shared world/caches across
   run_episode) — unowned; worth a future card.
5. **Undeclared default owner in follow/circle worlds** + the 4 unexplained
   circle_owner authority_disagreements E8 left unowned — D15-C declares
   bystanders for nav cells only; the rest needs an owner-prioritized card.
6. **Planner-vs-runtime person_slow divergence** (default.yaml 2.0 vs
   robot.yaml 2.5) — aligning the planner-side value moves frozen rows;
   owner decision (DOC-1 documents only).
7. **`dynamic_agents` widening of the reactive gate's people list** — the
   gate docstring's own named extension seam; needed before yield-aside can
   claim gate-level multi-stranger coverage.
8. **v4s generation power** — if routable-episode yield cannot reach the
   pre-registered n per axis, VS-5/VS-6 STOP; owner chooses: accept lower
   power, fund scene work, or defer.
9. **View-admission derivation fallback** — if verify rejects
   2π/`ScanPlanSpec.n_stops` as the minimum-baseline authority, the constant
   goes to the owner as a new authority value with 2x2 (it does NOT ship as
   an undocumented literal).
10. **navigate_crossing_ped +0.29 residual** (60ecea2 scan-creep seam,
    attributed by elimination) — one ~20 s scratch cell isolates it if the
    owner wants a separate pin.

---

## Appendix A — archived evidence (extract, do not retype)

The three artifacts below are the only copies outside the session scratchpad
(adjudication #21). Y-4 extracts A.1/A.2/A.3 into
`scrum/20260811/task_1/evidence/`; D15-C cites A.3 in D15_ATTRIBUTION.md.
Scripts are verbatim, including their session-scratch sys.path/config paths;
re-runners re-point those at the tree under test.

### A.1 `trace_group.py` (pedestrian_group step-trace diagnostic)

```python
"""Step-trace pedestrian_group on the scratch tree (diagnostic, no ledger write)."""
import sys, math, json
from collections import Counter

sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/src")

from evals.companion_nav.runner import FollowBenchRunner
from evals.companion_nav.scenarios import FOLLOW_BENCH_V1
from evals.companion_nav import metrics as M

scenario = next(s for s in FOLLOW_BENCH_V1 if s.scenario_id == "pedestrian_group")
runner = FollowBenchRunner("/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/configs/robot.yaml")
result = runner.run(scenario)

steps = result.steps
band = [s for s in steps if 1.2 <= s.owner_distance_m <= 3.0]
print("steps:", len(steps), "band_fraction:", round(len(band)/len(steps), 4))

# where the band fails: above or below
above = sum(1 for s in steps if s.owner_distance_m > 3.0)
below = sum(1 for s in steps if s.owner_distance_m < 1.2)
print("above_band:", above, "below_band:", below, "max_dist:", round(max(s.owner_distance_m for s in steps), 3))

print("proximity_state counts:", Counter(s.proximity_state for s in steps))
print("reactive_state counts:", Counter(s.reactive_proximity_state for s in steps))
print("controller state counts:", Counter(s.state for s in steps))

# sample trace every 10 steps
print(f"{'t':>5} {'rx':>6} {'ry':>6} {'own_d':>6} {'vx':>6} {'pedsurf':>7} prox/react state note")
for i, s in enumerate(steps):
    if i % 10 == 0 or (s.proximity_state != "clear" and i % 3 == 0):
        note = s.note.split("|")[0][:40]
        print(f"{s.time_s:5.1f} {s.robot_x:6.2f} {s.robot_y:6.2f} {s.owner_distance_m:6.2f} {s.command_vx:6.3f} "
              f"{(s.nearest_pedestrian_surface_m if s.nearest_pedestrian_surface_m is not None else -1):7.3f} "
              f"{s.proximity_state}/{s.reactive_proximity_state} {s.state} {note}")

# throttle attribution: fraction of steps slowed/stopped while behind
slowed = [s for s in steps if s.proximity_state in ("slowing", "stopped")]
print("slowed_or_stopped steps:", len(slowed), "of", len(steps))
print("min ped surface:", round(min(s.nearest_pedestrian_surface_m for s in steps if s.nearest_pedestrian_surface_m is not None), 4))
```

### A.2 `oracle_yield.py` (lateral yield-aside oracle upper-bound)

```python
"""Oracle upper-bound for a lateral yield-aside on pedestrian_group (+ cut_in).

Emulates "the follow controller aims at a laterally shifted lane" by giving
follow.step() an observation whose OWNER point is shifted perpendicular to the
owner's travel direction; the dispatch gate, TTC, metrics, and the world all
see the TRUE observation. Diagnostic only, scratch tree only.
"""
import sys, math
from dataclasses import replace
from collections import Counter

sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree")
sys.path.insert(0, "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/src")

import evals.companion_nav.runner as R
from evals.companion_nav.scenarios import FOLLOW_BENCH_V1

SHIFT = 0.0  # set per cell

_orig_step = None

def install(shift_y: float):
    import parcel_robot.navigation.follow as F
    global _orig_step
    if _orig_step is None:
        _orig_step = F.FollowOwnerController.step
    def shifted_step(self, observation, now=None, *, prediction=None):
        if observation is not None and shift_y != 0.0:
            owner = observation.owner
            observation = replace(observation, owner=replace(owner, y=owner.y + shift_y))
        return _orig_step(self, observation, now=now, prediction=prediction)
    F.FollowOwnerController.step = shifted_step

def restore():
    import parcel_robot.navigation.follow as F
    if _orig_step is not None:
        F.FollowOwnerController.step = _orig_step

def run_cell(scenario_id: str, shift_y: float):
    install(shift_y)
    try:
        scenario = next(s for s in FOLLOW_BENCH_V1 if s.scenario_id == scenario_id)
        runner = R.FollowBenchRunner("/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects/10414eee-ec95-484f-80ab-02978d7e3f5b/scratchpad/tree/configs/robot.yaml")
        result = runner.run(scenario)
        steps = result.steps
        n = len(steps)
        band = sum(1 for s in steps if 1.2 <= s.owner_distance_m <= 3.0) / n
        surfaces = [s.nearest_pedestrian_surface_m for s in steps if s.nearest_pedestrian_surface_m is not None]
        minsurf = min(surfaces) if surfaces else None
        dwell = sum(1 for v in surfaces if v < 1.2) * 0.1
        intimate = sum(1 for v in surfaces if v < 0.45) * 0.1
        stopped = sum(1 for s in steps if s.proximity_state == "stopped")
        coll = steps[-1].cumulative_static_collisions
        print(f"{scenario_id:24s} shift={shift_y:+.2f}  band={band:.4f}  min_surf={minsurf if minsurf is None else round(minsurf,4)}  dwell={dwell:.1f}s  intimate={intimate:.1f}s  gate_stops={stopped}  static_coll={coll}")
    finally:
        restore()

for shift in (0.0, 0.2, 0.4, 0.6, -0.3):
    run_cell("pedestrian_group", shift)
for shift in (0.0, 0.4, -0.4):
    run_cell("pedestrian_cut_in", shift)
```

### A.3 `minival_isolation.txt` (25-episode isolation minival, person_stop_m restored to 1.0 — the D-15 counterfactual arm)

```
{"id": "nav-region_goal-A-00-1c735162", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-region_goal-B-05-586317e4", "success": false, "dtg": 2.425, "failure": "refusal", "authority": "agreement"}
{"id": "nav-region_goal-C-10-138643ba", "success": false, "dtg": 2.325, "failure": "refusal", "authority": "agreement"}
{"id": "nav-region_goal-D-15-1b8b2361", "success": false, "dtg": 1.8967, "failure": "grounding_error", "authority": "agreement"}
{"id": "nav-region_goal-E-20-6a95f8c4", "success": false, "dtg": 56.1392, "failure": "grounding_error", "authority": "agreement"}
{"id": "nav-object_goal-A-00-4caa923b", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-object_goal-B-05-0ee314d5", "success": false, "dtg": 0.3242, "failure": "false_arrival", "authority": "false_arrival"}
{"id": "nav-object_goal-C-10-68aa2ab8", "success": false, "dtg": 1.87, "failure": "grounding_error", "authority": "agreement"}
{"id": "nav-object_goal-D-15-109547e2", "success": false, "dtg": 0.0067, "failure": "planning_error", "authority": "agreement"}
{"id": "nav-object_goal-E-20-1a854173", "success": false, "dtg": 56.1595, "failure": "refusal", "authority": "agreement"}
{"id": "nav-object_relative-A-00-3efbba45", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-object_relative-B-05-7d441aee", "success": false, "dtg": 1.4835, "failure": "refusal", "authority": "agreement"}
{"id": "nav-object_relative-C-10-0d3f5ebd", "success": false, "dtg": 7.4702, "failure": "refusal", "authority": "agreement"}
{"id": "nav-object_relative-D-15-61f68ad6", "success": false, "dtg": 4.3258, "failure": "planning_error", "authority": "agreement"}
{"id": "nav-object_relative-E-20-0c739ea2", "success": false, "dtg": 54.9003, "failure": "refusal", "authority": "agreement"}
{"id": "nav-follow_owner-A-00-40672702", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-follow_owner-B-05-334e8d3f", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-follow_owner-C-10-41c8032b", "success": false, "dtg": 7.9354, "failure": "planning_error", "authority": "agreement"}
{"id": "nav-follow_owner-D-15-74a535dd", "success": true, "dtg": 0.0, "failure": "none", "authority": "agreement"}
{"id": "nav-follow_owner-E-20-433c9247", "success": false, "dtg": 0.2249, "failure": "planning_error", "authority": "agreement"}
{"id": "nav-circle_owner-A-00-6ba3a31d", "success": false, "dtg": 0.0, "failure": "termination", "authority": "authority_disagreement"}
{"id": "nav-circle_owner-B-05-4d7b5b21", "success": true, "dtg": 0.0, "failure": "none", "authority": "authority_disagreement"}
{"id": "nav-circle_owner-C-10-4dd3449c", "success": false, "dtg": 7.5082, "failure": "planning_error", "authority": "agreement"}
{"id": "nav-circle_owner-D-15-717b5947", "success": false, "dtg": 0.0, "failure": "termination", "authority": "authority_disagreement"}
{"id": "nav-circle_owner-E-20-12e7db57", "success": false, "dtg": 0.0, "failure": "termination", "authority": "authority_disagreement"}
```

Reading of A.3 (from §1.1): region_goal-D-15 1.8967 ≈ frozen old 1.8999 (vs
2.1021 on new code); object_relative-D-15 4.3258 ≈ frozen 4.3301 (vs
4.1822); object_goal-B-05 0.3242 false_arrival = old failure class (vs
0.3928 planning_error); object_goal-D-15 dtg 0.0067 (band edge, in-context).
All four moved episodes attribute to the single knob.

---

## Integrity notes

- All designer measurements were made in scratch rsync copies / detached
  worktrees with the main venv by absolute path; the real tree was verified
  clean (HEAD dd2e857) before and after each investigation and after this
  synthesis (this file is the batch's one additive write).
- One designer recorded a transient scratch-copy corruption mid-jerk-bisect;
  final cells were re-run on freshly verified worktrees and anchored by two
  bit-exact pin reproductions (§3.4).
- Every load-bearing file:line and artifact citation in §§1-5 was verified by
  at least one skeptic and re-verified by the synthesizer where contested
  (§0.2). Numbers not re-measured by the synthesizer carry their original
  measurement protocol in the source design digests.
