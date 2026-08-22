# E-2 pre-registration — the held-out generalization run

**Written before any E-2 measurement and before the exposure-spend decision.**
Card: `scrum/20260821/task_14/README.md` incl. the binding REVISION 2026-08-21.
Executor: Claude Opus · Date: 2026-08-22 (local 2026-08-21 evening).

The point of writing this first is that the *decision rule* below — the one
that governs whether the held-out scene's single exposure gets spent — is
fixed before I know what the entry survey says. A rule written afterwards
would be a rationalization either way: for spending it, or for not.

---

## 1. The protocol

**Row H (held-out).** The dog enters `city_block_b` cold: empty
`OnlineSemanticMap`, `perception.semantic_source: learned_map`, no sidecar
vocabulary, no POI table.

* **Phase 1 — bounded exploration patrol.** Fixed wall-clock budget, fixed
  route policy declared before the run. The map learns from the real
  detector stream during this phase and only this phase. Snapshot the map at
  phase-1 end; that snapshot is a pack artifact.
* **Phase 2 — the corpus.** Nav rows 1–13 (nav-direct, nav-indirect,
  nav-invalid) plus scene questions, spoken through the real voice stack,
  scored by PG-2 convention, with null controls beside every localization
  claim, at pass^k with k = 3.

**Row D (development, the comparison row).** The identical protocol in the
textured `city_block`. This row is not decoration: the headline number is a
*difference*, and a difference needs both terms.

**Headline:** generalization gap = score(Row D) − score(Row H).

## 2. Targets fixed in advance

| id | Target | Bar |
|---|---|---|
| H1 | Phase-1 map in `city_block_b` learns ≥ 4 distinct place classes | ≥ 4 |
| H2 | nav-direct rows admit correctly (any-person GT rule applies) | ≥ 0.60 pass^3 |
| H3 | nav-invalid rows (10–13) refuse **without** a label set | 4 / 4 refuse |
| H4 | null controls admitted | 0 |
| H5 | POI-disabled probe (REVISION §1): one query whose *only* possible pass is the POI table | **MUST NOT PASS** |
| D1–D5 | the same five, in `city_block` | same bars |
| G1 | gap = D − H reported with its denominators, both rows scored | reported |
| R1 | storefront true-positive, "go to the coffee shop" as a PRESENT query (REVISION §2) | admits |
| R2 | person-poster decoy is **not** admitted as a person-place (REVISION §3) | not admitted |
| R3 | place-name decal does **not** forge an admission (REVISION §3) | not admitted |
| R4 | count-questions emit **no** count without map corroboration (REVISION §4) | 0 uncorroborated counts |

Scoring rules, per the binding REVISION and fixed here:

* **Any-person GT rule.** Tiny background figures must not score correct
  perception as failure. A person cell is scored against *any* admissible
  person in frame, not one designated instance.
* **Shadow/divergence taxonomy** from C-3's revision applies to E-2 scoring
  (`benign_miss`, `localization_delta`, `admission_flip`, `refusal_flip`),
  and every divergence carries its frames.
* **Count questions** (F3-class): a count emitted without map corroboration
  is scored **wrong**, not partially right. VLM counting is unreliable at
  every size (12–17/40 exact).
* Person-class cells are scored **known-limited** with W-1's mechanism note
  (T1 person recall 0.014; correctly-placed hypotheses, no confidence).

## 3. Claims this run can and cannot support

* **CAN:** "the pipeline generalizes to an unseen *synthetic* scene."
* **CAN:** "unknown places refuse without a label set in an unseen scene."
* **CANNOT — stated prominently, in the pack README and here:** *any*
  real-world claim. **MuJoCo textures are not photographs.** No number in
  this pack transfers to a sidewalk.

## 4. The exposure-spend decision rule (pre-registered, binding on me)

`city_block_b` has **one** exposure. The card says so: "one exposure is
spent by this run … a future refresh needs a new variant." Once spent it is
development data forever and no amount of care restores it.

Therefore, **before** Row H is run:

> **Rule E.** Spend the held-out exposure only if Row D — the development
> row — is *obtainable under this card's OWNS*, and its protocol has been
> demonstrated to complete end to end at least once. If Row D cannot be
> produced, Row H is **not run**, because gap = D − H is not computable
> without D, and a bare H of 0/N cannot distinguish "does not generalize"
> from "has never worked in any scene." In that case: HALT, report what is
> missing, leave the exposure unspent.

**Rule F.** E-2 edits no perception source (the E1 discipline). Any defect
found is recorded and carded, never patched inline. If meeting a target
would require editing a predecessor's module, a frozen manifest, or the
scene, the target is **reported as blocked**, not met.

**Rule G.** Failures are recorded as failures. A target that is missed is
written down as missed, with its mechanism measured where measuring is free.

## 5. Entry survey — what I measure before deciding

1. Tree quiescence, twice, ≥ 3 min, unchanged (chain contract rule 1).
2. `git status --porcelain` ⊆ predecessors' documented set.
3. `scripts/ci_gate.py` green.
4. Predecessor deliverables present: W-1's scene + truth artifact; C-1's
   stream; C-2's `online_map/`; C-3's `perception_source/` and the
   `semantic_source` switch; **the REVISION §2 storefront fixture; the
   REVISION §3 decoy fixtures**; a means of driving Phase 1.

Item 4 is where Rule E gets its answer.

---

*Nothing below this line was written before the entry survey. The survey's
result and the halt it produced are in `../E2_STATUS.md`.*
