# Cutover design research — synthesis · Fable · 2026-08-21

Five reports in this folder: a 2026 model-landscape sweep, an adversarial
review of the W1–E2 design, and three pre-registered GPU benches that
downloaded and tested nine new models on this machine. Card revisions
(binding sections appended to task_12b, task_13, task_14) carry every
decision below; this is the index.

## Decisions, each with its strongest evidence

1. **Detector seat: OWLv2 stays.** Best permissive-license detector at a
   precision-matched operating point in 2026, with the only landed int8
   path. Every stronger alternative fails a hard constraint: YOLOE /
   YOLO-World (the measured technical winners — 14 ms, 0.946 person
   recall) are AGPL; Grounding-DINO 1.5/1.6 and DINO-X are API-only (a
   cloud detector inside the local disposer is architecturally forbidden);
   LLMDet-base costs 2.3× latency at 4.4 GB. LLMDet is the named re-visit
   candidate only if post-W-1 recall targets miss.
2. **New second seat: OmDet-Turbo tiny (Apache, 728 MiB) for ASYNC
   keyframe map-building** — best macro object recall (0.753; planter
   0.63 vs incumbent 0.25) and by far the best texture-poor degradation.
   In-loop queries stay OWLv2; map building gets the better object eye.
3. **Retrieval: label/text-primary, cosine demoted permanently.** The
   modality gap is architectural (cross-modal cosines live in a narrow
   band; our measured 0.060–0.135 spans are the textbook signature) — no
   bigger embedder fixes thresholding-on-cosine. Chain: noun → label
   match (no match ⇒ refuse) → evidence-weighted ranking → 2B-VLM veto →
   navigability. Measured: 0/8 absent admitted, 5/5 present correct,
   ~30–55 ms. Embeddings: best-view only (averaging measurably degrades),
   within-query ranking only.
4. **VLM seat: Qwen3-VL-2B replaces the 8B's residency** — statistical
   quality tie at n=40 across QA/naming/verification, 4.4 GB vs 17 GB,
   89 ms vs 214 ms answers. Hard limit confirmed: EVERY VLM size breaches
   the 100 ms detector bound while generating — so the duty-cycle policy
   (own it: C-3) is the mechanism, not model choice. VLM-verify becomes
   PG-3's fifth signal; it is also embedding-version-free, bridging model
   upgrades.
5. **Vocabulary-free naming: yes, behind a k-consistency promotion gate.**
   ~82–87% naming accuracy means 1-in-7 names is wrong; idle-time batch
   naming with `vlm_proposed` provenance and promotion after k
   independent-visit agreements makes it safe. This is how the dog's
   vocabulary grows beyond any prompt list — the owner's "learn about the
   world" directive, mechanized.
6. **Embedding versioning (C-2's confirmed gap):** per-entry model-id/
   revision/dim + a bounded source crop; mismatch = unavailable, never
   cross-space cosine; lazy re-embed. Nearly free now, a store migration
   later.
7. **Map hygiene is a safety surface:** volatile classes never persist;
   a class-conditional size + depth-planarity gate defeats
   picture-of-a-person (posters pass ALL FOUR current signals — detector
   fires, evidence strengthens, margins fine, adjacent ground navigable);
   decay-marked means excluded-from-retrieval; red-team decoys (poster +
   scene-text decal) added to the dev scene so the defenses are
   exercisable. AgentPoison (≥80% attack success at 2 poisoned entries)
   and CHAI (>87% embodied typographic ASR) are the threat models.
8. **F1 — the eval-saver: the POI grounder is a second oracle** firing
   before semantic search with hardcoded coordinates, owned by no card.
   Disabled under T1 and E-2, with a RED seed. Without this finding both
   the cutover mission and the generalization eval could have "passed"
   while measuring a lookup table.
9. **Shadow-mode discipline:** pre-registered per-class thresholds, a
   four-class divergence taxonomy with admission/refusal flips as hard
   gates, and ≥3 T1-only closed-loop missions — because shadow agreement
   structurally cannot see the states T1's own behavior would create.
10. **All PG-3 operating points re-derive on textured renders** (F2): the
    current calibration was measured on the invalidated world; the
    architecture survives, the numbers do not.

## Process finding worth the register

The llmdet_tiny anomaly (a converted checkpoint silently mis-scoring
through an identical wrapper) generalizes: **any future model-seat swap
requires a pinned-fixture eval in CI before cutover** — paper numbers and
even sibling-model behavior are not evidence about a specific converted
artifact.

## Cost of the whole research wave

$0 API (all local inference), ~15 GB of scratch downloads, one afternoon
of GPU time shared politely with the executing chain.
