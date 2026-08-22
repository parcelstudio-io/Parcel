# Task 12b — C-2: the dog's own map (online semantic memory)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** bench_mapping.md — fusion and the spatial representation are
sound and cheap (lamppost to 1–3 cm, 108 KiB / 36 places, 0.24 ms/frame
fuse) and are the parts to keep; retrieval and abstention were the failures,
now addressed by PG-2 (surface convention + null controls) and PG-3 (the
four-signal gate incl. navigability). res_mapping.md's design pressure:
object-centric entries beat dense fields at this scale; persistence and
re-localization ride the EXISTING `route_memory/place_graph`.
**DISPATCH GATE: after C-1 closes.**

## Work

1. **`OnlineSemanticMap`** (new module): consumes C-1's detection stream;
   object-centric entries — class label, surface-based location (PG-2
   convention), embedding, evidence count, first/last-seen, writer
   provenance (R27 discipline). Incremental: re-observation updates and
   strengthens; absence on re-visit decays (tunable, honest defaults);
   nothing is ever silently deleted — decayed entries are marked, kept,
   and auditable.
2. **Continuous learning across sessions:** the map persists (own store,
   NEVER the conversation store; PARCEL_MEMORY_PATH-class isolation from
   birth) and reloads on start — the dog that walked yesterday knows the
   lamppost today. Integrate with `route_memory/place_graph` for the
   place-level graph; the sidecar-free vocabulary emerges from the map's
   own entries.
3. **Query API shaped for the consumers it will have:** C-3's grounding
   (label/embedding query → candidates with evidence + PG-3 abstention
   verdict), R18's scene answerability (what is around me, by kind and
   bearing), R20's vocabulary (known-places list + nearest offers, learned
   not labeled).
4. **Offline-first testing:** fixture detection streams (from the W-1
   re-render + hand-built cases) drive every property — growth, decay,
   persistence, provenance, abstention integration — with the live proof a
   patrol in the textured world that builds a map answering ≥5 corpus
   place queries within PG-2 tolerance WITH null controls.

OWNS: the new map module + its store, `route_memory/` integration
(smallest honest touch), tests + fixtures, `C2_STATUS.md`.
MUST NOT TOUCH: grounding/semantic_map consumers (C-3), the conversation
store, detector/ingress internals, yield policy. Standard house rules.

## Definition of done

Gate green; ≥10 seeds RED (decay deletes instead of marks; provenance
dropped; persistence to the conversation store; reload skipped; abstention
bypassed in the query API; null control absent from the live-proof
scoring). Live proof: the patrol-built map, its query table with
distances + null controls, persistence across a restart demonstrated.
`C2_STATUS.md` standard register.

## REVISION 2026-08-21 (binding; supersedes the above where in conflict)
Evidence: scrum/20260821/cutover_research/{res_design_review,bench_retrieval,bench_vlm,bench_detectors2026,res_landscape}.md — read all five before starting.

1. **Retrieval is detector-label-primary with a TEXT-side channel.** Query
   resolution: query noun → fused detector labels (evidence-weighted), plus
   name/caption entries retrieved text-to-text (the BinTrack pattern —
   67.4% vs 44.6% baseline). Image-text cosine is admissible ONLY as
   within-query relative ranking; NEVER an absolute threshold, NEVER an
   absence/presence verdict (the modality gap is architectural: measured
   spans 0.060–0.135 are the textbook signature).
2. **Embeddings: best-view, versioned, re-derivable.** Store the
   entropy/best-view embedding — NEVER average across views (averaging
   measurably degrades retrieval). Per entry: {embedding_model_id,
   revision, dim, preprocessing} + a bounded source-crop thumbnail so
   re-embedding is possible. Version mismatch ⇒ "embedding unavailable"
   (fall back to label/text channel), never cross-space cosine.
3. **Map hygiene (safety):** (a) volatile-class exclusion — persons,
   vehicles, and other dynamic classes are NEVER persisted as places;
   (b) a class-conditional metric-size + depth-planarity gate (the
   picture-of-a-person defense: RGB/depth agreement — a poster fires the
   detector but is planar and wrong-sized); (c) decay-marked entries are
   EXCLUDED FROM RETRIEVAL, not merely annotated — quarantine semantics,
   pinned by seed.
4. **Two-detector design:** OWLv2 stays the in-loop query seat (PG-1's
   landed path). OmDet-Turbo tiny (Apache-2.0, 728 MiB) takes the ASYNC
   keyframe map-building seat — best macro object recall measured (0.753;
   planter 0.63 vs 0.25) and best texture-poor degradation. Co-resident
   budget ~1.5 GB. Any future seat swap requires a pinned-fixture eval in
   CI first (the llmdet_tiny silent-collapse lesson).
5. **Vocabulary-free naming, gated:** VLM naming runs as an IDLE-TIME
   batch pass only (never during patrol — every VLM size breaches the
   100 ms detector bound while generating). Names enter as
   `provenance: vlm_proposed` and are promoted to admissible vocabulary
   only after k independent-visit consistent re-namings (bench: naming is
   16/20 with perfect consistency on distinctive classes, poor on
   ambiguous ones — the k-gate is what makes 82–87% accuracy safe).
   The VLM seat is Qwen3-VL-2B (Apache-2.0, ~4.4 GB resident, no measured
   quality loss vs the 8B); the 8B's residency is retired.
6. **Red-team props:** add TWO decoys to the dev scene via the
   regeneration tooling (a photorealistic person poster; a scene-text
   decal reading a place name, e.g. "coffee shop") so the hygiene gates in
   (3) are exercisable. Seeds must include: poster-enters-map-as-person
   RED; decal-forges-label-agreement RED. (These decoys are dev-scene
   only; the held-out scene stays untouched.)
