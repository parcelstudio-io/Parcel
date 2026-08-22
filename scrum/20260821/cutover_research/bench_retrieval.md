All measurements complete. Final results below.

---

# Retrieval redesign bench — results and recommendation (agent: retrieval-fable)

**Workspace:** `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/cutover-research/retrieval-fable/` — `PREREGISTRATION.md` (written before any run), `out/SUMMARY.json`, `out/eval_*.json` (full per-query rows), `rebuild.py`, `eval_abc.py`, `eval_de.py`, `veto.py`, `aggregate.py`. API spend: $0 (all local).

## Substrate and one disclosed deviation

Arms ran on a rebuilt Arm-B map (OWLv2-b16 + SigLIP2-b16, 120 archived frames): **33 entries vs the archived 36** — exact reproduction failed because the archived map was built on torch cu129 (pylibs) and the only working venv is cu130; near-threshold OWLv2 detections flap. Per the pre-registered fallback, ALL arms including the baseline ran on the rebuilt map; the rebuild is deterministic across my two runs, and the oracle Arm-A map reproduced exactly (105/105 entries, max centroid delta 0.028 m). Baseline character matches the archived result (non-separable cosine, same top confuser "the parking garage").

Queries: the same 8 present / 8 absent as bench-semmap. Null control: exact rank-p — probability a uniformly random map entry does as well as the arm's pick (best achievable 1/33 = 0.03); regions (sidewalk, crosswalk) excluded from the null tally per the prior bench's disclosed metric flaw. W1 textured renders were NOT complete at run time (task_10/W1_STATUS.md §2 pending), so all sim numbers carry the untextured caveat.

## Cross-arm table (8 present / 8 absent; NAV = gt_radius+1.0 m; TIGHT = 0.30 m)

| arm | NAV | TIGHT | med err | abstain-on-present | null-beats (obj, p≤.10) | sep. margin | separable | present lost to reject all absent | AUROC (64 pairs) | latency | VRAM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A SigLIP2-b16 cosine (baseline) | 7/8 | 2/8 | 0.68 m | 0 | 4/6 | −0.037 | **no** | 5/8 | 0.766 | 2.2 ms | 0.8 GB |
| B detector-label-primary | 6/8 | 4/8 | 0.22 m | 1 | 3/6 | **+0.118** | **yes** | 1/8 | 0.875 | ~0 ms | 0 |
| C SigLIP2-So400m cosine | 7/8 | 2/8 | 0.68 m | 0 | 4/6 | −0.022 | no | 3/8 | 0.859 | 10.8 ms | 2.8 GB |
| D VLM-rerank top-5 (Qwen3-VL-2B) | 5/8 | 1/8 | 0.94 m | 2 | 3/6 | −0.514 | no | 3/8 | 0.922 | 155 ms/query (27 ms/call) | 5.2 GB |
| D VLM-rerank top-5 (Qwen3-VL-8B) | 4/8 | 0/8 | 1.57 m | 2 | 1/6 | −0.857 | no | 2/8 | 0.906 | 293 ms/query (53 ms/call) | 17.8 GB |
| **D3 composite: B's pick + 2B-VLM veto** | 5/8 | **4/8** | 0.014 m | 3 | 2/6 | n/a* | see * | 2/8 | 0.875 | ~30 ms | 5.2 GB |

\* D3's decision rule is answer-vs-abstain, not a threshold: **8/8 absent abstained, 5/8 present answered, and all 5 answers were NAV hits — 0 wrong answers dispatched.** The margin field is an artifact of scoring abstentions as confidence 0.

**No arm passed all three pre-registered criteria** (≥6/8 NAV + separable keeping ≥6 + ≥4/6 null-beats). B alone is separable; A/C alone have the hits. The composite gets precision instead.

## Answers to the open design questions

**(2) How should retrieval work given cosine failed → detector-label-primary, embeddings as tiebreak, VLM as veto.** Cosine at ANY embedder size cannot gate presence on this map: b16 loses 5/8 present to reject all absent; So400m (4.6× params) improves AUROC 0.766→0.859 but stays non-separable — the upgrade shrinks the overlap, it does not remove it. Label-primary is the only separable arm (margin +0.118 vs −0.037, present-lost 1/8 vs 5/8), and its confidence — evidence-weighted label strength — has a clean structure: corroborated entries score 2.8–8.2, stray single-detection labels 0.12 (this directly validates PG-3's detector-agreement + evidence-count signals). Critical negative result: **VLM re-ranking hurts localization** — the VLM verifies CLASS, not INSTANCE, so it happily says "yes" to the wrong lamppost crop and overrode a correct first-stage ranking (0.014 m → 2.65/3.81 m in both D variants). Use the VLM veto-only on the strength-ranked top candidate (D3): it caught exactly arm B's one false answer (a 4.8 m stray "a tree" label, strength 0.12, vetoed at p_yes 0.003) at ~30 ms/query. B's known hole — synonyms ("the streetlight" abstains; lexicon is exact-match) — is properly closed by the hosted voice model normalizing nouns before grounding (it is already in the loop); interim, So400m-cosine tiebreak absorbed the functional paraphrase ("somewhere to sit" → bench, 0.22 m) that b16 missed.

**(3) Can a VLM name novel places → yes on real imagery, no in the current sim, and cheap.** Real COCO crops: 2B lenient 23/30 (77%, over the pre-registered 70% bar; strict 15/30), 52 ms/call; 8B lenient 18/30 — partly under-scored by my matcher on descriptive answers ("Women on bench", "Biker in silhouette" scored as misses; disclosed artifact). Untextured sim: 1/28 and 2/28 — the VLM names the geometry itself: "Blue cylinder", "Sphere", "Void", "Column". Vocabulary-free map growth is viable for C-2 (gate: N corroborating frames before accepting a VLM-proposed name), but only after W-1 lands — a second-modality confirmation that the world, not the models, is the blocker.

**(4) Embedding versioning → store evidence crops; upgrade becomes a batch job.** Re-embedding the whole map (411 crops, 33 entries) with So400m took **6.4 s** (~15.6 ms/crop) once crops are retained. C-2's card should add: per-entry top-k evidence crops (my 411 PNGs ≈ few MB) + an `embedder_version` tag per embedding; on upgrade, re-embed offline and bump the tag. Without stored crops, versioning genuinely is a migration problem; with them it is not a problem at all.

**(1) Detector** (not my lane, one datapoint): every retrieval fix above still rides on OWLv2's labels; grounding-dino base/tiny are already in scratch (`perception/bench-owl/hf/hub`) if the detector bench wants a head-to-head.

**(5) Structural gaps in W1-E2:** (a) The VLM's absent-rejections split by plausibility: semantically impossible queries are crushed (Narnia 0.0002, my office 0.0001, swimming pool 0.003) but **physically plausible absentees pass the VLM gate on untextured crops** (fire hydrant p_yes 0.53/0.82, parking garage 0.68/0.97 for 2B/8B — a bollard IS hydrant-shaped, a plain box IS garage-shaped). E-2's null controls should include plausible-absent probes, not just Narnia-class ones. (b) The coffee-shop refusal currently rests on the detector never fusing that label — W-1's textured storefronts could start firing it; re-run the abstention panel post-W1. (c) "grass" veto is the composite's honest cost (VLM can't confirm an untextured green box); pre-registered expectation: that veto flips after texturing.

## Recommendation for C-2/C-3

1. **C-2 OnlineSemanticMap retrieval key = detector labels with evidence-weighted strength**, embeddings kept for tiebreak/paraphrase only; add evidence crops + embedder version to the entry schema.
2. **C-3 grounding chain:** hosted model normalizes noun → detector-vocab match (no match → refuse, preserves "go to Narnia") → candidates ranked by label strength → **Qwen3-VL-2B veto on the top candidate's crop** (p_yes ≥ 0.5) → navigability gate. Measured on this bench: 0/8 absent answered, 5/5 answered-present correct at NAV (4 at TIGHT), ~30 ms added latency, 5.2 GB VRAM — the 2B verifier fits alongside OWLv2+SigLIP well under the contention regime that 19.5 GB Qwen-8B violated (detector p95 1.54×), and the 8B bought no verify accuracy here.
3. Do not buy a bigger embedder for separation; So400m's only measured win is paraphrase absorption (2.8 GB, 10.8 ms if wanted).

**Caveats:** n=8/8 queries is directional, not calibration; untextured sim — between-arm comparison on identical inputs is the claim, absolute recall is not; latencies on a shared GPU (owner stack ~1 GB; a co-process spiked to 17 GiB twice mid-bench, OOM-killing my first 8B attempt — tolerated per rules, rerun when clear; 18 GiB in use again at bench close, after my last GPU work).