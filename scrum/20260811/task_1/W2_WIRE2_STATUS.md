# W2-WIRE2 status — card VS-5 (2026-08-11, task_1)

Lane W2-WIRE-2, executor Claude Opus. One card from the authoritative record
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` (§0, §2, §6 card block "Card
VS-5"): **evidence-fed value map wiring + empty-map == exact baseline**, Wave-2
pipeline.py slot 2. VS-4 closed first; this lane was pipeline.py's sole owner.
No commit made.

**Verdict: gate clauses (1), (3-control), (4) and (5) PASS; the EFFECT GATE
(2) FAILS and this lane STOPS on it.** The map is now genuinely fed — 35 235
looks painted across the v4s arm, 306 of them carrying real query evidence,
28 918 of them MISSES that lower value — the empty-map delegation is proved on
120 evidence-free episodes AND on a painting-disabled arm, and the
value-directed frontier is observed taking 30 decisions it could not have taken
before. It converts **zero** episodes on either gated axis: **0 wins, 0 losses
on LA; 0 wins, 0 losses on BB** (exact McNemar p = 1.0000 on both), against a
pre-registered floor of ≥6 net paired flips — and the same verdict holds in a
second, complete pair of arms run with the REAL SigLIP matcher
(`PARCEL_SIGLIP2_ONNX=1`), where the LA baseline is not even degenerate
(SR 0.100 flag-off) and exactly one ungated PH cell converts, by precisely the
designed mechanism (§10). Per the card's own rule ("a true-but-smaller
effect FAILS the gate → STOP-and-report with the measured delta and power note,
never a silent margin shrink") the honest numbers are below, with the measured
reason (§7). No mechanism was invented to force the number.

---

## 1. Gate table (all measured)

| Card gate clause | Result |
|---|---|
| (1) EMPTY-MAP NO-OP PROOF: `value_directed_search` ON with evidence painting disabled == flag-OFF, per-episode outcomes AND SPL float-identical on the full v4 minival | **PASS, bit-for-bit** — 25/25 rows byte-equal, SPL `0.273259…` identical to the last bit, and the same holds on the v4s 180-episode set. Strengthened beyond the card's wording: painting fully LIVE with `evidence_count == 0` is also bit-identical, proved in vivo on 120 episodes that painted 29 718 misses between them (§4) |
| (2) EFFECT GATE on v4s: paired flag-on-vs-off per axis, ≥6 net flips (losses 0), exact McNemar p ≤ 0.031, ΔSR ≥ +10pp | **FAIL — STOP-and-report, in BOTH matcher arms.** Default (string-fallback) arm — LA: 0 wins / 0 losses / ΔSR +0.000, p = 1.0000; BB: 0 / 0 / +0.000, p = 1.0000. Real-SigLIP arm — LA: 0 / 0 / +0.000; BB: 0 / 0 / +0.000. (PH, not a gated axis: 0/0 default, 1 win / 0 losses with real SigLIP.) Measured cause in §7 |
| (3) zero runtime model calls in the control tick (PlanTimePriorCache gate kept); flag-off byte-identical | **PASS, with the scope stated exactly** — the frontier PRIOR is still plan-time-only and `PlanTimePriorCache` is untouched; the evidence paint does call the embed seam per look, which is §2.2(d)'s own design and is the same matcher the flag-off grounding ingress already calls on the same tick (§9.1). Flag-off byte-identity proved three ways (§4.1) |
| (4) non-vacuity — the value-directed path ENGAGED (dispatch requirement) | **PASS.** Default arm: `evidence_count > 0` on 74/180 episodes; 306 evidence paints; 30 value-directed frontier decisions; 13 episodes with a physically different trajectory, all of them evidence-carrying (§5). SigLIP arm: 76/180, 280 evidence paints, 48 directed decisions, 19 moved, and one full commit→unroutable-release→value-directed-frontier→arrival (§10) |
| (5) ci_gate GREEN | **PASS** — `scripts/ci_gate.py --tier commit`: every hard gate green, 3594 passed, ruff 7 = baseline 7 / new 0 (§9) |

Baseline at lane open, verified fresh before any edit: `scripts/ci_gate.py
--tier commit` **PASS**, 3575 passed, ruff 7 = baseline 7 / new 0 — exactly
VS-4's landed state.

---

## 2. What landed

| Deliverable | Where | What it is |
|---|---|---|
| evidence surface | `src/parcel_robot/navigation/value_map.py` `+48 −2` | `evidence_count` property, `write(..., is_evidence=False)` keyword, `reset()` |
| paint passthrough + C2 empty behaviour | `src/parcel_robot/navigation/value_directed_scan.py` `+28 −1` | `paint_look(is_evidence=…)`, `_evidence_count_of`, the `empty_map_no_evidence` COMMIT clause in `choose_next_look` |
| C3 empty delegation | `src/parcel_robot/instructnav/search_entity.py` `+38 −1` | `ValueMapFrontierScorer.baseline_scorer()` / `.has_evidence()` / `empty_map_delegate`, and the delegating head of `.score()` |
| the wiring | `src/parcel_robot/navigation/pipeline.py` `+147 −16` | VS-3 policy construction, the single-ingress evidence paint, the delegation predicate at the frontier call site, mission-scoped map reset, telemetry |
| tests | `tests/test_value_directed_search.py` `+367 −2`, `tests/test_value_map.py` `+60` | 14 + 5 new cases; 5 pre-existing fixtures re-declared (§8) |

(Line counts are against this lane's OPENING state — VS-4's landed pipeline.py,
not `HEAD`.)

`configs/**`, `runtime.py`, `instructnav/scoring.py`, `detection_adapter/**`,
`camera_channel/**`, `evals/**`, `core/**`, `reactive_safety.py` — untouched, as
the card's MUST-NOT-TOUCH requires. **No file outside this card's OWNS list was
edited.** No allowlist entry was needed: `value_directed_search` has been in
`ALLOWED_NAVIGATOR_OVERRIDES` since V-D.

---

## 3. The architecture, as wired

Everything below is conditional on `value_directed_search`, default OFF.

**(a) One ingress, one paint per searching tick.** The replaced painter lived at
the BOTTOM of `_step_scan_behavior` and ran only on the ticks that got past the
frustum and memory commit doors above it. Every frontier-crawl tick, and every
tick where a sighting resolved immediately, painted NOTHING. That is the
mechanical half of the measured "the map ran EMPTY" defect (record §2.1(2a)) and
it is why an in-range target could be seen and forgotten. The paint now sits at
the single ingress in `_step_semantic_resolution`, immediately after the
false-positive and attribute filters and immediately before grounding reads the
same list — so the scan ticks, the frustum-confirm ticks and the frontier ticks
all paint, hit or miss, and no second perception channel is invented.

**(b) The paint tuple is VS-3's, not the pipeline's.** `ValueEvidencePolicy`
(frozen contract, W2_PURE_STATUS.md §4) supplies `(value, conf, is_evidence)`:
`value = match_score x observation_confidence` through the SigLIP seam;
`is_evidence` iff the match cleared `SIGLIP2_MATCH_THRESHOLD`. The `0.15`
scanned-cone floor, the `0.05` something-irrelevant floor and the substring
branch are **gone** — pinned by
`test_a_look_at_nothing_paints_a_miss_and_never_counts_as_evidence`, which reads
every covered cell back at exactly `0.0`. A look that finds nothing therefore
LOWERS the fused value of its cone, which is the "stop re-looking there" half of
the design.

**(c) `evidence_count` is on the MAP, not only on the policy.** The scorer is
handed a map, not a policy, so the delegation predicate has to be readable from
the map. `SemanticValueMap2D.evidence_count` increments iff a look was evidence
AND landed at least one cell — a cone that fell outside the rolling window put
no evidence in the map and must not claim to have. Misses never increment it,
for any number of looks.

**(d) The empty-map contract, in two places.**

* **C2** — `ValueDirectedScanSession.choose_next_look` returns COMMIT with
  `detail="empty_map_no_evidence"` when the map carries no evidence. With
  nothing to be directed BY, an "informed" extra look is an uninformed one that
  spends dwell steps the baseline full turn does not: flag-on is then exactly
  the baseline full turn.
* **C3** — `ValueMapFrontierScorer.score` DELEGATES to
  `SemanticMinusGeodesicScorer(travel_weight=self.travel_weight,
  prior_weight=1.0, coverage_weight=self.coverage_weight)` — the object
  `select_frontier` itself builds when no scorer is passed, not a copy of its
  arithmetic. `test_evidence_free_map_scores_are_float_identical_to_the_baseline`
  pins `struct.pack` identity over 1 080 candidate scorings.

**(e) The delegation is made TOTAL at the pipeline call site.** The scorer alone
is not sufficient, and this lane pins the reason rather than assuming it away:
`select_search_entity_frontier` stamps `coverage_gain` from the map's
`unknown_fraction` whenever it is HANDED a map, and a map full of MISSES is no
longer unknown — a candidate field the scorer never sees and cannot delegate
away (`test_misses_move_the_callee_which_is_why_the_wiring_gates_at_the_call_site`
proves it moves). So `_select_semantic_frontier` passes `value_map=None,
plan_prior=None` when `evidence_count == 0`. That is not an approximation of the
flag-off call: it **is** the flag-off call — same function, same arguments — so
`evidence_count == 0` gives a bit-identical frontier decision however many
misses have been painted.

**(f) The 8-12 m window is closed by the existing machinery, as §2 requires.**
A target sighted at ~12 m commits, the ~8 m local costmap cannot route to it,
and `_unroutable_goal_recovery` → `_begin_semantic_replan` releases the
instance. That funnel clears scan and frontier state but **not** the belief map,
so the evidence paint from the sighting survives the release and the next
frontier selection is pulled back toward it. No new mechanism, no new constant,
no arrival predicate: the wiring keeps the evidence and lets the frontier close
the range. This is the path that produced all 30 value-directed frontier
decisions and all 13 moved trajectories (§5, §7).

**(g) Mission scope.** `start()` resets both the map and the policy ledger. A
map that kept a previous mission's evidence would report `evidence_count > 0`
before this mission had looked at anything and the delegation would silently not
fire on its first frontier.

**K0 untouched.** No epsilon, no arrival reason, no goal special-cased, no second
predicate. Every branch this card owns chooses a LOOK or a FRONTIER POINT.

---

## 4. Gate (1) — the empty-map proof, three ways

### 4.1 Flag-off byte-identity (standing rule 3)

| Arm | Result |
|---|---|
| v4 minival, `--mode baseline`, `scaled-path-v1`, seed 20260804, scratch rsync | report digest `c172da375ff23987cb6414fe8899fa263f7ec00ef363659306a38c7719f7553a`, episodes payload `440fd8842854d446a0c5ffc6ccf625def708d4c9889cb4324a10f6a3ee41f8d6` — **equal to the committed frozen row** `nav-instruct-v1-baseline-v4-20260811T070536Z.json` under the same recipe |
| v4 minival, `--mode candidate` (the mode that actually exercises the search ladder) | pre-change tree and post-change tree both `58aa1aa1643fca94879d4178568662d45c9edacf976689e3c7173ab4dd91358c` |
| **v4s, all 180 episodes, `--mode candidate`** | pre-change and post-change both `e31fdd82ced8bdc9d500ef2f77403e64dd2097178188a79528ea6796f5ccbcae`; episodes payload `e2a4d151c68d45f2407ddcf177e4a6113538f243a6161bf8af77a3bf76b0f7cb` — **the same `run_digest` W2_EVAL_STATUS.md §3 recorded**, i.e. this lane's flag-off arm is VS-6's arm to the byte |

Digest recipe (path-independent, VS-4 §4's correction applied): sha256 over the
report minus `{report_id, elapsed_s, scene, navigator_flags,
refreeze_provenance}` and minus `aggregate.scene`. VS-4's published value
`897d6ce7…` came from a different serializer; the CLAIM is reproduced here under
one recipe applied to both sides, which is the stronger form.

> **AF-2 (2026-08-11), completing that note.** The "different serializer" is
> exactly `json.dumps`'s separators: this lane used `separators=(",", ":")`,
> VS-4 used the defaults. **Both values are correct and reproduce from the
> committed frozen row** — `897d6ce7…` at default separators, `c172da37…`
> compact, same five-field exclusion, same `aggregate.scene` drop. Likewise the
> two lanes' episodes payload shas: VS-4 sorted the rows by `episode_id` first
> (`bfb21cd2…`, default separators), this lane kept report order
> (`440fd884…`, compact). All five are now pinned against the frozen row by
> `tests/test_nav_instruct_digest_recipe.py`, and the full recipe block is in
> W2_WIRE1_STATUS.md §4. AF-2 re-ran this lane's `--mode candidate` v4 minival
> arm at its own landed state and reproduced `58aa1aa1…` exactly, which is the
> flag-off byte-identity re-proof after AF-2's pipeline edits.

### 4.2 Painting disabled (the card's own wording)

`value_directed_search` ON with `_paint_scan_observation` replaced by a no-op,
v4 minival, one process per episode:

```
mv_nopaint vs mv_off : 25/25 rows byte-equal (decision sequence)
SR   0.3200 == 0.3200
SPL  0.273259252142310  == 0.273259252142310   (float-identical)
dtg  7.847902           == 7.847902
```

### 4.3 Painting LIVE, evidence absent (the dispatch brief's stronger reading)

No double, no patch — the matcher, the painting and the misses are all live, and
the arms are partitioned by the flag-on arm's own telemetry:

| Set | evidence_count == 0 episodes | bit-identical to flag-off | MISS looks those episodes painted |
|---|---|---|---|
| v4 minival (n=25) | 14 | **14 / 14** | 918 |
| v4s (n=180) | 106 | **106 / 106** | 28 800 |
| v4s (n=180), real-SigLIP arm | 104 | **104 / 104** | 39 312 |

**Zero violations.** 224 episodes painted 69 030 miss looks between them and did
not move one decision. `evidence_count == 0 ⇒ bit-identical` is a property, not
a coincidence — which is what the E4 "accidental 0-flip tie" (record §2.1(2))
was not, and it holds under both matcher arms.

> **CORRECTIONS — card AF-2, 2026-08-11.** Provenance: `AUDIT_WAVE2_FABLE.md`
> should-fix 4, "VS-5 partition circularity + comparator scope". Two corrections
> and one added control; the claim SURVIVES all three, restated exactly.
>
> **(i) "bit-identical" EXCLUDES the note channel — state it.** The table above
> reads as row-level byte equality; it is not. Under the flag every non-terminal
> searching command carries the `|value_map=evidence=…` telemetry suffix (§5),
> so on a re-measurement **0 of 33** evidence-free rows are byte-equal as
> persisted, while **33 of 33** are identical once the suffix is stripped. The
> honest claim is: *the flag-on arm's DECISIONS — every trace field except the
> note-channel telemetry suffix this card itself appends — are identical to
> flag-off on every evidence-free episode.* That is the claim the delegation
> contract makes, and it is the one that holds.
>
> **(ii) The partition was keyed off the arm under test.** `evidence_count` was
> read from the FLAG-ON arm's own telemetry, so the arm named its own control
> group. AF-2 added the independent control the auditor specified: a **FLAG-OFF
> replay** carrying a SHADOW `ValueEvidencePolicy` evaluated on the same
> grounding ingress, writing into no map and read by no decision, so the
> partition is derived from the flag-off arm alone.
>
> Measured — v4s, `--per-axis 20` (n = **60** episodes, ≥ the 20 the audit
> asked for), `--mode candidate`, `scaled-path-v1`, `max_steps 200`, seed
> 20260811, `hold-or-trace-end-v1`, **one fresh `NavInstructRunner` (hence one
> fresh world and one fresh scan RNG) per episode per arm**:
>
> | | |
> |---|---|
> | flag-off-derived partition | 33 zero-evidence / 27 evidence-carrying |
> | zero-evidence episodes whose DECISIONS are identical to flag-off | **33 / 33** |
> | zero-evidence episodes whose RAW rows are identical (telemetry included) | 0 / 33 — see (i) |
> | evidence-carrying episodes whose decisions moved | 4 / 27 |
> | flag-off-derived partition vs the flag-on telemetry partition | **0 disagreements** on all 60 |
>
> So the original partition was circular but not wrong: the two partitions are
> the same set, episode for episode.
>
> **(iii) A whole-arm partition cannot attribute a per-episode difference.** Run
> as two 60-episode arms in single processes, the SAME comparison shows **4
> apparent violations** (`BB-06`, `BB-07`, `BB-13`, `PH-16`). All four are
> decision-identical under one-world-per-episode isolation: they are VS-4 §5's
> shared `HeadlessCityWorld._scan_rng` carried over from the 4 earlier episodes
> that legitimately moved. Any future delegation claim must be measured with a
> fresh world per episode, as above.
>
> **(iv) The scan-viewpoint side channel, documented.** Under the flag the scan
> path does two things flag-off does not, neither of which the `evidence_count`
> delegation gates: `_publish_scan_viewpoint` PUBLISHES an `SE2Goal`
> (`SCAN_PROPOSER_SOURCE`) into the shared `ProposerBus` and latches the
> `GoalArbiter`'s active plan step; and `choose_next_look` may ENQUEUE a value
> look that changes where the body points. Verified inert on a zero-evidence
> episode, structurally and empirically
> (`test_the_scan_viewpoint_side_channel_cannot_steer_an_evidence_free_episode`):
> the look is gated by C2 (`empty_map_no_evidence` ⇒ COMMIT, so `LOOK` is never
> returned), and the published goal cannot reach a decision because **every**
> `goal_arbiter.resolve` site in `pipeline.py` sets its own plan step
> immediately before resolving over a single-element tuple it has just built —
> the pipeline never calls `proposer_bus.poll()`. The 33/33 result in (ii) is
> the empirical half. Recorded as a latent seam, not a defect: a future caller
> that polls the shared bus would put the scan viewpoint inside arbitration,
> and the empty-map delegation would not cover it.

A methodological note worth keeping: the first version of the seeded proof used
a "never-match" embedder built on Python's `hash()`. String hashing is
per-process randomized, two different texts collided, and the double emitted
136 SPURIOUS evidence paints across 10 episodes — which the wiring then
correctly acted on. The seeded double was wrong, not the wiring; it was replaced
by the in-vivo partition above, which needs no double at all. (A "never-match"
double is in any case impossible on this set: a region query's string IS its
label, so any embedder scores it 1.0.)

---

## 5. Gate (4) — non-vacuity: the machine is observed running

Not absence-of-failure. Whole v4s flag-ON arm (default string-fallback matcher),
from the persisted traces; the SigLIP arm's equivalents are in §10:

| axis | episodes with `evidence_count > 0` | evidence paints | total paints | miss paints | cells painted | value-directed frontier picks | delegated frontier picks |
|---|---|---|---|---|---|---|---|
| `LA` | 14 / 60 | 48 | 14 034 | 13 986 | 1 633 456 | 1 | 139 |
| `BB` | 16 / 60 | 56 | 18 129 | 18 073 | 2 215 238 | 13 | 158 |
| `PH` | 44 / 60 | 202 | 3 072 | 2 870 | 462 939 | 16 | 0 |
| whole arm | **74 / 180** | **306** | **35 235** | **28 918** | 4 311 633 | **30** | 297 |

* 13 episodes have a physically different trajectory from the flag-off arm, and
  **every one of them is an evidence-carrying episode** — the 106 evidence-free
  episodes are bit-identical (§4.3). The feature's footprint is exactly its
  evidence.
* The C3 clause is observed both ways in the same arm: 297 frontier decisions
  took the delegated branch and 30 took the value-directed branch.
* **The C2 clause is NOT separately instrumented in the live arm.** The
  `empty_map_no_evidence` COMMIT is proved by
  `test_empty_map_scan_session_commits_instead_of_looking_again` (and its
  positive control, which LOOKs once one evidence paint lands), not by a trace
  counter — `choose_next_look`'s verdict rides `mission.metadata`, which the
  frozen runner drops. Adding a counter would have meant re-running every arm
  including the ~2 h SigLIP pair for a field no decision reads; it is recorded
  as a gap instead of quietly claimed.
* Telemetry channel: `MidLevelCommand.note`, VS-4's finding that it is the only
  navigator-side channel the frozen runner persists. Suffix form
  `…|value_map=evidence=E,paints=P,hits=H,misses=M,cells=C,directed=D,delegated=G`,
  appended only under the flag and only to NON-terminal commands (so `reason` is
  never written), after a `|`. `test_telemetry_rides_the_note_without_touching_the_runners_own_keys`
  pins that the suffix introduces none of `frontier` /
  `semantic_target_not_found` / `scan_for_target` and never displaces the
  `semantic_search_scan` PREFIX the runner counts scan steps by.

---

## 6. Gate (2) — the effect gate, pre-registered, FAILED

Protocol: v4s, all 180 episodes, `--mode candidate`, `scaled-path-v1`,
`max_steps 200`, v4s seed 20260811, arrival rule `hold-or-trace-end-v1`, scratch
rsync, no in-tree ledger row. **One process per episode per arm** — VS-4 §5
found that `HeadlessCityWorld._scan_rng` is seeded once per world construction
and never re-seeded by `reset()`, so within one runner process an arm that
shortens one episode shifts the RNG for every LATER episode. Process-per-episode
removes that confound by construction and makes the pairing exact; both arms ran
that way, and both reproduce byte-for-byte on a re-run from a second scratch
tree at the final source state.

| axis | n | SR off | SR on | ΔSR | SPL off | SPL on | mean dtg off | mean dtg on | wins | losses | net | exact McNemar p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `LA` | 60 | 0.000 | 0.000 | +0.000 | 0.0000 | 0.0000 | 12.0575 | 12.0424 | **0** | **0** | **0** | **1.0000** |
| `BB` | 60 | 0.000 | 0.000 | +0.000 | 0.0000 | 0.0000 | 12.3811 | 12.4417 | **0** | **0** | **0** | **1.0000** |
| `PH` (not gated) | 60 | 0.000 | 0.000 | +0.000 | 0.0000 | 0.0000 | 8.1045 | 7.7617 | 0 | 0 | 0 | 1.0000 |

Failure histograms move by at most one episode per class (LA identical: planning
17, false_arrival 10, grounding 33 both arms; BB planning 17→16, search 2→3; PH
planning 39→40, search 4→3). The v4s flag-off column reproduces
W2_EVAL_STATUS.md §3 exactly, which is the cross-check that this harness is that
harness.

**Pre-registered bar: ≥6 net paired flips with losses 0 (equivalently exact
McNemar p ≤ 0.031) AND ΔSR ≥ +10pp, on the LA and BB axes. Measured: 0 net
flips, p = 1.0000, ΔSR +0.000. The gate FAILS and this lane STOPS.** Exact
McNemar is the two-sided sign test on the discordant pairs, computed by the
harness with `math.comb` — no normal approximation; with zero discordant pairs
it is exactly 1.0.

v4 minival (n=25, the frozen tripwire, not a gate for this card): SR 0.3200 →
0.3200, SPL identical, wins 0, losses 0, authority `false_arrival` 1 → 1.

### Secondary, NOT pre-registered, reported because it is real

On the 13 episodes the feature actually moved, mean final distance-to-goal falls
from **11.3188 m to 9.9468 m (−1.3720 m)**; 10 of the 13 end closer to the goal
and 3 end farther. That is a direction, on a hand-picked subset chosen by the
outcome variable's sibling, at n=13. **It is not evidence of an effect and this
lane does not offer it as one** — the pre-registered statistic is the paired
flip count and it is zero.

---

## 7. Why zero — measured, not conjectured

Three findings, all measured on the arms above. Together they say the design's
own empty-map contract confines its reach to a part of these episodes that is
small by construction.

**(1) The delegation contract means miss-painting alone can never move a
decision, and on these cells most episodes never get past misses.** §2.2(d) is
explicit — `evidence_count == 0` ⇒ the flag-off scorer, float-identically — and
`evidence_count` counts EVIDENCE, not paints (VS-3's frozen contract). So the
"a look that matches nothing must LOWER covered cells so the search stops
re-looking there" mechanism is real, is wired, and paints 28 918 misses across
the arm, but it is invisible to the frontier until the FIRST evidence paint
arrives. On LA 46/60 and on BB 44/60 episodes it never arrives: the target is
generated beyond the 12.0 m frustum and the frontier crawl never brings it into
view, so those 90 episodes are bit-identical to flag-off by design. This is not
a wiring gap — it is what the record specifies, and a design that let misses
steer before any evidence existed would forfeit exactly the delegation proof the
card is built around. Recorded here as the design's price, for the owner.

**(2) Where evidence DOES arrive, the search is usually already over.** The
ingress that produces evidence is the same frustum list grounding reads, so the
tick that first paints evidence is normally the tick that resolves the target
and commits; the mission then navigates and the frontier is never consulted
again. Measured: 74 episodes reached `evidence_count > 0` but only 30 frontier
decisions were value-directed, all of them on the release-and-resume path of
§3(f). Median evidence paints per engaged episode on LA/BB is **2**.

**(3) The engaged episodes are planner-bound, not search-bound.** All 8 engaged
LA/BB episodes end `navigation_step_limit` or `semantic_target_unreachable` with
a final distance of 7.7-14.3 m — the ~8 m local costmap (`grid_size_cells 161 x
resolution_m 0.10`, W2_EVAL §3) against a 12-14 m target, inside a
`scaled-path-v1` budget the frontier crawl spends at 0.22 m/s. A better-directed
frontier moves the robot toward the target sooner (10 of 13 end closer) and then
runs out of budget in the same place. Converting these cells needs the planner
or the budget to reach, which is upstream of everything this card owns and of
the value map itself.

W2_EVAL_STATUS.md §8 pre-registered exactly this outcome — "if the flag-on arm
also scores 0, VS-5's pre-registered answer is STOP-and-report, and the ~8 m
planner reach measured in §3 is the first thing to look at". It is.

**The SigLIP arm sharpens (1) rather than contradicting it.** With real matching
the reachable subset is if anything SMALLER on the gated axes — 12/60 LA and
4/60 BB episodes ever reach `evidence_count > 0`, against 14 and 16 in the
default arm, because neural matching refuses the cross-class sightings the
substring fallback accepted. Where evidence IS plentiful (PH: 60/60 episodes,
238 evidence paints, 41 value-directed frontier decisions) the mechanism
produces its one conversion. The pattern across both arms is consistent: this
feature does what it is built to do exactly where evidence exists, and evidence
on the LA/BB cells is scarce by their own construction.

---

## 8. The five pre-existing test fixtures this card re-declared

All five are inside this card's OWNS (`tests/test_value_directed_search.py`),
and all five are the SAME kind of change: a paint that represents a SIGHTING now
says so with `is_evidence=True`. Under VS-3's contract `is_evidence` is decided
by the MATCH (did it clear the SigLIP operating point?) while the painted VALUE
is match x observation confidence — so a weak-but-real sighting is a genuine
evidence paint with a low value, which is exactly what these fixtures build.
Left undeclared they would be MISSES, and the empty-map contract would
(correctly) make every one of these tests measure the baseline.

| Test | Fixture | Why it is a sighting |
|---|---|---|
| `test_tier_b_value_directed_sr_ge_fixed_spin_paired_seeds` (via `_value_directed_finds`) | the 0.55/conf-0.25 cue at the target bearing; the in-loop `0.95 if hit else 0.05` | the cue IS the target; the in-loop paint is now `is_evidence=hit`, so a look that misses stays a miss |
| `test_value_map_frontier_scorer_uses_ve_vp` | a 0.9 paint | a 0.9 value is a sighting |
| `test_tier_c_value_map_sr_plus_10pp_vs_nearest_frontier` | the 0.2/conf-0.4 seed toward the target | V_e must not fire on an evidence-free map — that firing is the measured V-D no-op |
| `test_select_search_entity_frontier_reads_value_map` | a 0.85 paint | an evidence-free map is not read at all |

No assertion was weakened and none was deleted; every one of these tests still
makes the claim it made, now about a map with evidence in it, which the record
says is the only map it can be about. **Fable should read these as declared
fixture corrections and adjudicate them.**

---

## 9. ci_gate, and what gate (3) does and does not say

### 9.1 The model-call clause, stated exactly

The card's clause is "zero runtime model calls in the control tick (existing
PlanTimePriorCache gate kept)". Two halves, kept apart deliberately:

* **The frontier prior is still plan-time only.** `PlanTimePriorCache` is
  byte-untouched, is still built once per mission in `start()` and only on the
  value-map path, and `test_plan_time_prior_cache_has_no_model_callable` is
  still green. The 10 Hz frontier decision reads a frozen table, as before.
* **The evidence paint DOES call the embed seam, once per look.** That is
  §2.2(d)'s own design — "using match scores (embed seam)" — and it is not a new
  class of call on this tick: the pipeline's grounding ingress already calls the
  same `SigLIP2Matcher` through `semantic_map._matches` on every searching tick,
  flag-off included, whenever the real path is enabled. In the DEFAULT arm (and
  every ci_gate arm) the matcher is in its string-fallback degrade and the call
  is a substring comparison, not a model. Reported here rather than folded into
  a "zero model calls" claim it does not literally satisfy.

### 9.2 `scripts/ci_gate.py --tier commit`, 2026-08-11T16:38:16Z (final, after
everything in this lane landed; identical result at 13:56:25Z):

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …v4-20260811T070536Z: collisions=0
                                          false_arrival=0 | mutation panel clean | freshness ok |
                                          follow-bench 7 rows hard_collision_total all 0 | walk_with_me ok
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3594 passed, 9 skipped, 36 deselected
RESULT: PASS — every hard gate green.   elapsed 126.6s
```

Suite delta attributed: 3594 = the lane's own baseline 3575 + **19**, exactly
the new cases this lane adds — `tests/test_value_map.py` 9 → 14 (+5) and
`tests/test_value_directed_search.py` 14 → 28 (+14). `ruff check` over the six
touched files: **All checks passed**; the tree ratchet stays `new 0`.

---

## 10. SigLIP arm

`_siglip_matcher().available` is `False` in the eval arms unless
`PARCEL_SIGLIP2_ONNX=1` (VS-4's note; weights present at
`~/.cache/parcel/siglip2-b16`, verified loadable here — text cosines: `the
tree`/`tree` 0.9652, `the bench`/`bench` 0.9637, `the lamppost`/`lamppost`
0.9780, cross-class `the tree`/`lamppost` 0.8499, `the tree`/`planter` 0.8627,
i.e. the 0.90 operating point separates them). The record's gate for this card
names no matcher, so both arms are reported.

Both arms were re-run end to end with `PARCEL_SIGLIP2_ONNX=1` (plus
`PARCEL_SIGLIP2_THREADS=1`), same protocol, one process per episode, 180
episodes each. Note this moves the BASELINE too: with real weights the
pipeline's own `_matches` becomes neural-only, so the flag-OFF arm is a
different (better) navigator, not the frozen one.

| axis | n | SR off | SR on | ΔSR | mean dtg off | mean dtg on | wins | losses | net | exact McNemar p |
|---|---|---|---|---|---|---|---|---|---|---|
| `LA` | 60 | **0.100** | **0.100** | +0.000 | 12.4102 | 12.4137 | 0 | 0 | **0** | 1.0000 |
| `BB` | 60 | 0.000 | 0.000 | +0.000 | 12.8391 | 12.7352 | 0 | 0 | **0** | 1.0000 |
| `PH` (not gated) | 60 | 0.000 | **0.017** | +0.017 | 8.3312 | 7.5964 | **1** | 0 | 1 | 1.0000 |

**The gate verdict is the same in both arms: 0 net flips on both gated axes,
far below the ≥6 floor. STOP stands.**

Three things the SigLIP arm adds that the default arm cannot show:

1. **The v4s LA axis is not degenerate under real matching.** Flag-off SR is
   **0.100** (6/60), not 0.000, and LA's 10 authority `false_arrival`s become
   **0** — real cosine matching refuses the cross-class commits the
   substring/alias fallback accepts (VS-4 §7's PH-31 finding, confirmed at axis
   scale). The "flag-off SR is 0.000 so ANY success is a flip" premise in the
   dispatch brief holds only for the string-fallback arm.
2. **The delegation contract holds identically here**: 104 evidence-free
   episodes, **104/104 bit-identical** to flag-off, 39 312 miss paints between
   them, zero violations. The proof is not an artifact of the degraded matcher.
3. **One episode converts, and it converts by exactly the designed mechanism.**
   `nav-object_goal-PH-15-1085316c`: flag-off `semantic_target_unreachable /
   search_error`, dtg **14.123**; flag-on `arrived_verified`, dtg **0.000**, SPL
   **1.0**. Its telemetry is the §3(f) story end to end — 172 looks painted, 168
   of them misses, **4** evidence paints, and **1** value-directed frontier
   decision taken after the unroutable release. That is the first v4s cell this
   feature has ever converted; it is 1 net flip on an axis the gate does not
   score, p = 1.0000, and it is reported as an existence proof of the mechanism,
   **not** as an effect.

Engagement telemetry, SigLIP flag-ON arm: `evidence_count > 0` on 76/180
episodes; **280** evidence paints, **49 169** total paints, **48 889** misses;
**48** value-directed frontier decisions against **415** delegated ones; 19
episodes with a physically different trajectory (mean final distance 10.9747 →
**8.3371 m**, 14 closer / 5 farther — again secondary and not pre-registered).

Cost, measured: with the real encoders the arms are ~90x slower per episode
(≈6 CPU-minutes vs ≈4 seconds), and the flag-OFF arm is just as slow as the
flag-ON one — the cost is the grounding ingress's own per-tick `match()` calls,
which predate this card, not the evidence paint.

**What the T0 ingress does to VS-3's graded scoring, either way.** The paint's
ingress is the frustum list `_resolution_semantic_map.query` returns, which is
ALREADY query-filtered by the pipeline's own `_matches`. A non-empty ingress is
therefore a set the pipeline has already accepted as the query, and an empty one
carries nothing to score — so in both arms the paint is effectively binary
(value ~1.0 x confidence, or 0.0) and VS-3's match-score gradation is exercised
only at unit level, by its own tests with a synthetic embedder. Feeding the
policy the RAW `semantic_candidates` instead would exercise the gradation, but
the record names the one ingress as "the same oracle frustum grounding already
uses" (§2.1(2a)), so this lane fed that one and records the consequence rather
than widening the ingress.

---

## 11. Interpretations recorded (the record wins; these fill gaps it leaves)

1. **`evidence_count` lives on the MAP as well as the policy.** The record puts
   it on `SemanticValueMap2D` ("`SemanticValueMap2D` gains `evidence_count`") and
   VS-3 puts it on the policy; both exist and they agree, because the pipeline
   paints through `paint_look(..., is_evidence=paint.is_evidence)`. Where they
   can differ is deliberate: the MAP counts only looks that LANDED a cell, since
   the map's counter answers "is there evidence in this map?" and a cone outside
   the rolling window put none there.
2. **The paint moved to the single ingress.** The record says the painter is
   replaced, not where it is called. Leaving it at the old call site would have
   left the frontier crawl and the immediate-resolve tick painting nothing —
   i.e. would have left the measured defect in place while replacing its
   arithmetic. One ingress, one paint per searching tick, is the reading that
   closes §2.1(2a).
3. **The delegation predicate is enforced at the call site, not only in the
   scorer.** §2.4 demands the scorer call the flag-off scorer OBJECT and it does;
   §2.2(d) demands `evidence_count == 0` be PROVABLY the baseline, and the
   scorer alone cannot deliver that once misses are painted (§3(e)). Both are
   implemented; the call-site gate is the one the pipeline takes, and the
   scorer-level delegation is the contract-level guarantee for any other caller.
   Consequence, stated plainly: in the live pipeline the scorer's delegating
   branch is unreachable, because the call site never hands it an evidence-free
   map. It is exercised by tests and by direct callers.
4. **The belief map is mission-scoped** (`start()` resets it), matching VS-3's
   policy clause. `_begin_semantic_replan` deliberately does NOT reset it — that
   is the mechanism of §3(f).
5. **The interchangeable-query gate on the C2 look block is untouched.** The
   record's deference discipline (§2.2(a)(i), VS-4) owns that decision, and the
   empty-map contract now makes the block a no-op for evidence-free maps anyway.

---

## 12. `does_not_prove`

* **No SR claim of any kind.** In the default arm both sides score 0.000 on all
  three v4s axes and 0.3200 on the v4 minival; in the SigLIP arm both sides
  score 0.100 / 0.000 on LA / BB. This lane does not claim the evidence-fed
  value map finds anything these cells hide; it claims the map is fed, the
  delegation is exact, and the paired effect on the gated axes is zero at
  n=60/axis under both matchers.
* **The one PH conversion is an existence proof, not an effect.** 1 net flip at
  n=60 is exact-McNemar p = 1.0000; PH is not a gated axis; and it appears in
  one of the two matcher arms. It shows the §3(f) mechanism can convert a cell,
  nothing more.
* **The zero is not proof of no effect.** At 0 discordant pairs the paired test
  has no power to exclude a small true effect; it excludes the pre-registered
  one (≥6 net flips). §7 names three measured reasons the reachable subset is
  small; none of them is a measurement of the mechanism's value in a setting
  where the planner can route.
* **The secondary dtg movement is not an effect estimate.** n=13, subset chosen
  post hoc by "did the trajectory move", no pre-registration.
* **No real-camera evidence.** In T0 the observations are the oracle frustum
  (record §2.1(2a)); it never hallucinates and never misses within 12 m, so
  "evidence" here is oracle presence and "miss" is oracle absence. VS-3's
  `DOES_NOT_PROVE` says the same about its match scores.
* **The graded match score is not exercised end to end** (§10): the ingress is
  pre-filtered, so the live paint is binary in both matcher arms.
* **The v4 minival is n=25.** Its 0-flip result is a regression tripwire at that
  power, not an estimate.
* **The delegation proof is about this contract, on these arms.** It shows no
  evidence-free episode moved a decision across 120 episodes and 29 718 miss
  paints; it does not prove no such episode can exist for a caller that
  constructs `ValueMapFrontierScorer` itself and stamps its own
  `coverage_gain` — that caller gets the scorer-level delegation only (§3(e)).
* **Determinism is proved across processes and across scratch trees** (both arms
  byte-reproduce), but per-episode numbers from a multi-episode runner process
  are still not portable: VS-4's shared-`_scan_rng` confound is unfixed and
  lives outside this card's OWNS. Every per-episode number here comes from a
  one-episode process.

---

## 13. Files touched

**Edited (all in OWNS):** `src/parcel_robot/navigation/pipeline.py`,
`src/parcel_robot/navigation/value_directed_scan.py`,
`src/parcel_robot/navigation/value_map.py`,
`src/parcel_robot/instructnav/search_entity.py`,
`tests/test_value_directed_search.py`, `tests/test_value_map.py`.

**Edited out of OWNS:** none.

**Untouched, as required:** `runtime.py`, `instructnav/scoring.py`,
`detection_adapter/**`, `camera_channel/**`, `evals/**` (including
`evals/nav_instruct/runner.py` and every episode set), `core/**`,
`reactive_safety.py`, `configs/**`, every `DIGEST_SENTINELS`-pinned file, and the
three Wave-2 pure modules (`lock_on_verify.py`, `false_positive_memory.py`,
`value_evidence.py`) — consumed frozen.

No in-tree ledger row, no frozen artifact read-modify-written, no commit made.
Every eval arm ran in a scratch rsync outside the tree.

---

## 14. Residuals for the Wave-2 audit

1. **The effect gate is unmet and the lane stopped on it.** §6 has the numbers,
   §10 the SigLIP replication, §7 the measured reasons. The owner decision this
   raises is whether the v4s axes are the right substrate for a value-map card
   at all: they are built so the target is unfindable flag-off (VS-6), but the
   measured barrier on the engaged episodes is the ~8 m planner reach and the
   crawl speed, not the search policy.
1b. **VS-6's "unfindable flag-off" property is matcher-dependent** (new,
   measured here, outside this card's scope to fix). With
   `PARCEL_SIGLIP2_ONNX=1` the LA axis's flag-off SR is **0.100**, not 0.000,
   and its 10 authority `false_arrival`s go to **0**. Any future card that
   pre-registers "flag-off SR is 0.000 so any success is a flip" on v4s must
   also pin the matcher arm. Reported for VS-6's record and the owner.
2. **The design's own delegation contract bounds the feature's reach.**
   Miss-painting cannot steer until the first evidence paint. That is the
   record's specification and this lane implemented it as written; if the owner
   wants misses to steer an evidence-free search, that is a different contract
   and a different proof, and it forfeits `evidence_count == 0 ⇒ baseline`.
3. **Five declared test-fixture corrections** (§8) — same shape as VS-6's two
   declared pin moves, but inside this card's OWNS.
4. **The scorer-level delegation is unreachable from the pipeline** (§11.3) —
   deliberate, tested, and recorded rather than removed, because the record names
   it as the deliverable.
5. **Still open from VS-4, untouched here:** the shared `_scan_rng` (world file,
   no owner in this batch), the `towards` arrival band vs the verify schedule,
   and the substring/alias grounding fallback when SigLIP is unavailable.
