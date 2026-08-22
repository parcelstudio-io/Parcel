# Task 14 — E-2: generalization, earned (the held-out eval)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** res_evalgen.md — a perception claim is credible only against
environments never seen during development; benchmarks enforce scene
splits for exactly this reason; and our own benchmark synthesis
(scrum/20260821/benchmarks/SYNTHESIS.md) names the in-domain trap: gold
labels we wrote, in a world we tuned against, are an IFEval, not an
IFBench. W-1 built `city_block_b` and quarantined it for this card.
**DISPATCH GATE: after C-3 closes. This card edits no perception source —
defects it finds are recorded and carded, never patched inline (the E1
discipline).**

## Work

1. **The protocol, pre-registered before any run:** the dog enters
   `city_block_b` cold — empty OnlineSemanticMap, T1 only, no sidecar
   vocabulary. Phase 1: a bounded exploration patrol (fixed time budget)
   during which the map learns. Phase 2: the corpus nav queries (nav-direct,
   nav-indirect, nav-invalid — rows 1–13) plus scene questions, spoken
   through the real voice stack, scored by PG-2 convention with null
   controls and pass^k (k=3) per the benchmark synthesis.
2. **The three claims this can and cannot support, stated in advance:**
   CAN: "the pipeline generalizes to an unseen synthetic scene"; CAN:
   "unknown places refuse without a label set in an unseen scene"; CANNOT:
   any real-world claim (MuJoCo textures are not photographs — say it in
   the README, prominently).
3. **Comparison row:** the same protocol run in the DEVELOPMENT scene
   (city_block textured), so the generalization gap is a measured number
   (dev-scene score minus held-out score), the one that matters.
4. **The pack:** `evals/20260822/generalization_run_1/` in the E1 layout —
   per-query transcripts, paths, the learned map snapshots (phase-1 end),
   shadow tables where applicable, verdicts with denominators, costs.
   Failures recorded as failures; every failure becomes a carded defect.
5. **Corpus hygiene:** rows measured here join the eval suite as the
   T1 regression set; the held-out scene remains held-out (one exposure is
   spent — note it; a future refresh needs a new variant).

OWNS: the eval harness (reusing R17's UI-mounted runner where possible),
the run pack, `E2_STATUS.md`. MUST NOT TOUCH: any perception/navigation
source, the held-out scene's assets (it is data now), evals/ frozen
surfaces. Standard house rules; spend cap $3.

## Definition of done

The pack exists per layout with the pre-registered protocol and both rows
(dev + held-out) scored with null controls and pass^3; the generalization
gap reported as the headline number with its honest interpretation; every
failure carded. Gate green after the pack lands. `E2_STATUS.md` standard
register (no seeds — no source edits; the register carries the verdict
table and the defects filed).

## REVISION 2026-08-21 (binding; supersedes the above where in conflict)
Evidence: scrum/20260821/cutover_research/*.md.

1. **Scoring rules fixed in advance:** an any-person GT rule (tiny
   background figures must not score correct perception as failure); the
   shadow/divergence taxonomy from C-3's revision applies to E-2 scoring;
   confirm in-protocol that the POI arm is disabled (one probe query whose
   only possible pass is the POI table — it must NOT pass).
2. **Add a true-positive storefront case:** the dev world now has a real
   coffee-shop-class facade (W-1) — "go to the coffee shop" as a PRESENT
   query, since the absent-set alone cannot catch a gate that over-refuses
   commercial classes.
3. **Red-team cells:** the dev-scene decoys (person poster, place-name
   decal) get their own scored cells — the poster must not be admitted as
   a person-place, the decal must not forge an admission; both verdicts
   with the frames. The held-out scene remains decoy-free and untouched.
4. **Count questions:** F3-class scene answers must never emit counts
   without map corroboration (VLM counting is unreliable at every size —
   12–17/40 exact); E-2 scores count-questions accordingly.
