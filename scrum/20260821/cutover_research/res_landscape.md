# Parcel W1-E2 Model Landscape Research (2025-2026)

## Seat 1: Open-vocabulary detection — is OWLv2 still the right detector?

**Short answer: OWLv2 is no longer SOTA among open-weights detectors, but it is still a defensible incumbent at its size. The one upgrade that clears our license/latency/VRAM bar is LLMDet.**

**LLMDet (CVPR 2025 highlight)** — Grounding-DINO-architecture detector co-trained with an LLM generating region- and image-level captions; the LLM is training-time supervision only, so inference is a plain detector. LVIS-minival zero-shot AP: Swin-T **34.6**, Swin-B **38.5**, Swin-L **42.0** (43.2 with chunk-size 80); val1.0: 34.9 (T), 43.2 (L). License: **Apache-2.0**, checkpoints on HF, and it is **merged into official `transformers==4.55.0`** (`iSEE-Laboratory/llmdet_tiny` etc.) — same integration path as our OWLv2. No published latency/VRAM; Grounding-DINO-Swin-T class models run ~100-150ms/image on data-center GPUs (my estimate, not published — bench it). Matters for Parcel: Swin-T roughly matches OWLv2-B/16 quality at similar scale; Swin-L (~7-8 pts higher AP) is the headroom card if the 86ms/query budget loosens. Crucially, Grounding-DINO-style models take the whole label list in one text pass rather than OWLv2's per-query pattern — changes the contention math PG-1 measured.

**MM-Grounding-DINO (OpenMMLab)** — fully open re-training of Grounding-DINO: **Apache-2.0**, LVIS zero-shot **31.9 val / 41.4 minival AP** (large variant, aggregator-sourced from the HF model card). In `transformers`. Strictly dominated by LLMDet on numbers; useful mainly as a second opinion / ablation baseline.

**OmDet-Turbo** — real-time transformer OVD with Efficient Fusion Head; **Apache-2.0**, in `transformers`; zero-shot ODinW **30.1**, OVDEval **26.86**; **100.2 FPS with TensorRT + language cache** (paper numbers). Matters if C-1 ever needs continuous-rate detection rather than on-demand queries.

**Ruled out on constraints, with evidence:**
- **Grounding DINO 1.5/1.6 Pro/Edge and DINO-X / DINO-X-Edge (IDEA Research)**: best published open-world numbers (GD-1.5-Pro ~47.7 mAP class), but **weights are not released — API-token access only** via DeepDataSpace. A cloud detector inside the local deterministic chain violates Parcel's disposer architecture. Skip.
- **YOLOE ("Real-Time Seeing Anything", ICCV 2025) and YOLO-World v2.x**: YOLOE is +3.5 AP over YOLO-Worldv2 on LVIS at 1.4x speed — genuinely good — but it is built on the Ultralytics codebase and distributed under **AGPL-3.0** (commercial relief only via Ultralytics enterprise license). Same reason we rejected YOLO-World before; still applies.
- **RF-DETR / YOLO26**: strong 2026 closed-set detectors; not open-vocab at inference in the form we need.

**Verdict for question (1):** Keep OWLv2-b16 as the working detector for W-1/C-1 (it's vendored, int8, contention-characterized). Slot **LLMDet Swin-T as the A/B challenger** in the same `transformers` harness, with Swin-L as a stretch config. OWLv2's label-head miscalibration ("the moon" at 0.338) is a known family trait; LLMDet's caption-supervised head is claimed to be better calibrated on rare/absurd queries — worth testing directly against PG-3's abstention signals, but do not assume it.

## Seat 1b: Segmentation — SAM 3 changes the frame

**SAM 3 "Segment Anything with Concepts"** (Meta, Nov 19 2025): text noun-phrase or exemplar prompt → masks + IDs for **every instance at once**, plus video tracking; ~2x prior systems on the SA-Co benchmark; **~840M params (~3.4GB), ~30ms/image on H200** (aggregator-sourced via Ultralytics docs/Roboflow; expect materially slower on RTX 5000 Ada). License: custom **"SAM License" — commercial use allowed**, ITAR/military/weapons restrictions, weights redistribution stays under SAM License. Not Apache, but nothing blocking Parcel. Why it matters: it collapses detector + segmenter + tracker into one seat, giving surface-level masks that would feed C-2's surface-based locations directly, and its concept prompting is exactly our query pattern. The cost is ~3.4GB VRAM resident plus an unknown contention profile — it competes with the reasoner budget, not with OWLv2's int8 footprint. Treat as an option for a later cut, not W1.

## Seat 2: Image-text embedders — why cosine failed and what replaces it

The near-chance SigLIP-2 text→place result (spans 0.060-0.135, margins ≤0.01) is consistent with the literature, and the strongest evidence says the fix is **architectural, not a bigger embedder**:

- **"The Bare Necessities" (arXiv 2412.01539)** measured exactly our failure surface in open-vocab scene graphs: CLIP-family features are **extremely viewpoint-sensitive**; **averaging embeddings across views significantly degrades retrieval** vs selecting the best single view; multi-scale crops/SAM-masking preprocessing "triples computation" for minimal gain; **Shannon-entropy-based feature selection over a domain prompt list** beat both averaging and confidence scoring (+5% from a domain-appropriate prompt list alone), at 3x less compute. Direct hit on C-2: if the OnlineSemanticMap averages SigLIP embeddings across evidence, that alone can produce our margins.
- **ConceptGraphs / HOV-SG lineage** ground queries through object-level CLIP embeddings but evaluate with top-k rankings over a *closed comparison set*, not absolute cosine thresholds — nobody in this literature thresholds raw cosine and survives. Retrieval should be **rank-then-gate**: detector-label match first (exact/synonym via the label head), embedding similarity only as a ranker among candidates, PG-3's four signals as the gate.
- **Stronger embedders if we still want one:** **Perception Encoder (Meta, NeurIPS 2025)** — **Apache-2.0 code and checkpoints**. PE-Core-B/16-224: 78.4% IN-1k zero-shot, 50.9 COCO retrieval (0.09B vision); PE-Core-L/14-336: **83.5% / 57.1** (0.32B); G/14-448: 85.4 / 58.1 (1.88B). Paper claims PE-Core surpasses SigLIP2 at matched sizes. SigLIP2 for reference: So400m/14-384 84.1% IN-1k; our b16 is the family's floor. PE-Core-L/14-336 is the best license-clean upgrade per parameter.
- **DINOv3 (Meta, Aug 2025)** — image-only SSL features, **+10.9 GAP instance retrieval** over predecessors, 7B teacher distilled to usable sizes; **custom commercial DINOv3 License** (commercial use permitted; not OSI — flagged as controversial at release). No text tower, so irrelevant to text→place retrieval — but it is the right feature for **instance re-ID / evidence association** in C-2 (is this the same chair as yesterday), which SigLIP class-level embeddings do poorly.

**Verdict for question (2):** detector-label-primary retrieval with embedding-as-ranker; store best-view (entropy-selected) embeddings, never averaged; optional VLM rerank only over top-k candidates (bounded cost, fits contention guard). Swapping SigLIP2-b16 for PE-Core-L would raise the ceiling but does not fix a thresholding-on-cosine design.

## Seat 3: Small VLMs for scene QA and place naming

- **Qwen3-VL-4B / 2B** (Oct 2025, Apache-2.0): 4B runs in **~6GB at Q4_K_M**, 8B needs ~12GB at Q4 (aggregator-sourced VRAM figures, codersera); 2B is ~1.9GB quantized. The 8B at 19.5GB (our bf16 measurement) is the outlier configuration — a quantized 4B/8B collapses the co-generation contention that produced detector p95 1.54x. Same family as our vendored 8B, so prompts/harness carry over.
- **Moondream 3 preview** — 9B MoE, **2B active**, built specifically for detection/grounding/pointing/structured output; claims SOTA on grounding benchmarks at its activation size; **BSL 1.1** license (personal/research/most commercial use OK; forbids selling a competing hosted API — fine for Parcel). The pointing + structured-output orientation matches "name this place, return JSON" better than chat-tuned VLMs.
- **SmolVLM2-2.2B** (Apache-2.0): outperforms larger models on some video benchmarks; weakest of the three on grounding; a fallback, not a first choice.
- **Vocabulary-free naming evidence (question 3):** "From Open-Vocabulary to Vocabulary-Free Semantic Segmentation" (arXiv 2502.11891, 2025) and CaSED show VLM-generated class names for unenumerated categories are feasible but noisy — naming quality is the stated open problem. "Seeing with Partial Certainty" (arXiv 2501.04947) applies **conformal prediction to VLM place recognition** precisely because VLMs hallucinate place labels with confident wording. So: yes, a VLM can propose "coffee shop", but only behind an abstention gate — propose-name → hold as provisional → promote after N independent sightings agree (evidence counts already exist in C-2's schema). Never let a single VLM utterance mint a map entry.

## Seat 4: Monocular depth

**Depth Anything 3** (ByteDance, Nov 2025): code Apache-2.0; **DA3-Small (0.08B), DA3-Base (0.12B), DA3METRIC-LARGE and DA3MONO-LARGE (0.35B) are Apache-2.0**; Giant/Nested are CC-BY-NC-4.0. **DA3METRIC-LARGE outputs metric depth** (`metric_depth = focal * net_output / 300`). >10% better than DA2 on ETH3D; DA2's own large checkpoints are CC-BY-NC, so DA3 is both better and cleaner-licensed. For Parcel: a D455 cross-check / fill-in for surfaces beyond stereo range, and a sim-only depth source in W-1 textured scenes. Low priority while fusion is at 1-3cm, but the license-clean metric variant is worth vendoring when depth matters.

## Answers to the open design questions

1. **Detector:** OWLv2 remains adequate and characterized; **LLMDet (Apache-2.0, in transformers) is the only clear open-weights upgrade** — A/B it in shadow mode. Everything stronger is API-only (IDEA) or AGPL (YOLOE/YOLO-World).
2. **Retrieval:** detector-label-primary, embedding-as-ranker over candidates, best-view selection (entropy), no cross-view averaging, VLM rerank only over top-k. Evidence: Bare Necessities ablations; HOV-SG/ConceptGraphs evaluate rankings, never absolute cosine.
3. **Vocabulary-free naming:** feasible with Qwen3-VL-4B/Moondream-3 class models, but the literature (2502.11891, 2501.04947) says treat names as hypotheses under abstention + repeated-evidence promotion, not facts.
4. **Embedding versioning:** industry practice is unambiguous — **vectors from different model versions are incompatible spaces; never mix in one index** (Qdrant/Weaviate migration docs; Drift-Adapter arXiv 2509.23471 for near-zero-downtime mapping). C-2 must (a) stamp every embedding with `model_id+version`, (b) **persist the source crop/keyframe per map entry** so re-embedding is always possible, (c) treat upgrade as re-embed-and-swap (alias/dual-write pattern), never in-place. Storing the crop also enables VLM rerank and human audit for free.
5. **Structurally missing:** (a) an instance re-ID feature (DINOv3-class) distinct from the class embedding — decay-marks-never-deletes needs "same object again" evidence; (b) detector calibration transfer check after W-1 texturing (0/69→real-photo parity does not guarantee threshold transfer); (c) segmentation-grade surfaces (SAM 3) as a later cut for surface-based location quality.

## Recommended test matrix for bench agents (worth the disk)

| Download | Size | Why | Test |
|---|---|---|---|
| `iSEE-Laboratory/llmdet_tiny` (+base if T looks good) | ~0.5-1GB | Only license-clean OWLv2 successor | Person/object recall on W-1 textured renders vs OWLv2-b16; latency/VRAM under PG-1 contention; "the moon"/"Narnia" calibration vs PG-3 gates |
| PE-Core-B/16-224 and PE-Core-L/14-336 | ~0.4/1.3GB | Apache upgrade over SigLIP2-b16 | Re-run the text→place retrieval bench with best-view (no averaging) protocol; report spans/margins |
| Qwen3-VL-4B-Instruct (Q4 + bf16) | ~3-9GB | Kills the 19.5GB contention problem | Scene QA parity vs 8B; place-naming reliability over N sightings; detector p95 under co-generation |
| Moondream 3 preview | ~9GB disk, 2B active | Grounding/pointing specialist, structured output | Same place-naming bench; JSON reliability |
| DINOv3-S or B | ~0.1-0.4GB | Instance re-ID for map evidence | Same-object-across-sessions matching on textured scenes |
| DA3METRIC-LARGE | ~0.7GB | Apache metric depth | Agreement vs D455/sim ground truth on W-1 scenes |
| SAM 3 | ~3.4GB | Only if surface quality blocks C-2 | Concept-prompt masks vs box-derived surfaces; VRAM/latency on our GPU |
| Skip | — | GD-1.5/1.6/DINO-X (API-only), YOLOE/YOLO-World (AGPL), SmolVLM2 (dominated), MM-GDINO (dominated by LLMDet) | — |

## Design pressure

- **CHANGE (C-2): retrieval architecture, not just the embedder.** Rank-then-gate with detector labels primary; ban cosine thresholds; ban cross-view embedding averaging; adopt entropy-based best-view selection. Evidence: our measured margins (0.0004-0.01) + Bare Necessities ablations showing averaging degrades and view selection wins.
- **CHANGE (C-2): add embedding versioning now.** `model_version` stamp + persisted source crop per entry + re-embed-and-swap upgrade path. Evidence: unanimous vector-DB migration practice; incompatible spaces silently corrupt neighbors, which decay-marks-never-deletes would then preserve forever.
- **CHANGE (contention plan): bench Qwen3-VL-4B/Q4 as the resident VLM.** Evidence: measured 1.54x detector p95 under the 19.5GB 8B; 4B-Q4 at ~6GB restores headroom for LLMDet-L or SAM 3 later.
- **KEEP: OWLv2 as W1 detector; add LLMDet in shadow, not as a swap.** Evidence: OWLv2 is vendored, int8, contention-measured; LLMDet's gains (34.6-42.0 LVIS minival, Apache, transformers-native) justify a challenger lane but nothing 2026 justifies destabilizing C-1 mid-cutover.
- **KEEP: PG-3's four-signal abstention as the naming gate too.** Evidence: conformal-prediction work on VLM place recognition exists precisely because VLM place labels hallucinate; route vocabulary-free names through the same abstention + evidence-count promotion.
- **ADD (C-2): instance re-ID feature (DINOv3-S/B) alongside the class embedding.** Evidence: DINOv3's +10.9 GAP instance retrieval; class-level embeddings cannot support "same chair, moved" which the persistence + decay semantics implicitly require.
- **ADD (E-2): calibration-transfer null control.** After W-1 texturing, verify detector score distributions (not just recall) transfer, since PG-3 thresholds were tuned in the untextured regime.

Sources:
- [LLMDet GitHub (iSEE-Laboratory)](https://github.com/iSEE-Laboratory/LLMDet), [LLMDet arXiv 2501.18954](https://arxiv.org/pdf/2501.18954)
- [MM-Grounding-DINO HF card](https://huggingface.co/openmmlab-community/mm_grounding_dino_large_o365v2_oiv6_goldg), [MM-GDINO arXiv 2401.02361](https://arxiv.org/pdf/2401.02361)
- [Grounding-DINO-1.5 API repo (IDEA)](https://github.com/IDEA-Research/Grounding-DINO-1.5-API), [DINO-X API repo](https://github.com/idea-research/dino-x-api), [DINO-X arXiv 2411.14347](https://arxiv.org/abs/2411.14347)
- [YOLOE GitHub (THU-MIG)](https://github.com/THU-MIG/yoloe), [YOLOE ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Wang_YOLOE_Real-Time_Seeing_Anything_ICCV_2025_paper.pdf), [Ultralytics YOLOE docs](https://docs.ultralytics.com/models/yoloe)
- [OmDet-Turbo arXiv 2403.06892](https://arxiv.org/abs/2403.06892), [OmDet-Turbo in transformers](https://huggingface.co/docs/transformers/en/model_doc/omdet-turbo)
- [OWL-ST/OWLv2 scaling paper (NeurIPS 2023)](https://papers.neurips.cc/paper_files/paper/2023/file/e6d58fc68c0f3c36ae6e0e64478a69c0-Paper-Conference.pdf)
- [SAM 3 arXiv 2511.16719](https://arxiv.org/pdf/2511.16719), [Meta SAM 3 announcement](https://about.fb.com/news/2025/11/new-sam-models-detect-objects-create-3d-reconstructions/), [SAM 3 LICENSE](https://github.com/facebookresearch/sam3/blob/main/LICENSE), [Ultralytics SAM 3 docs (aggregator)](https://docs.ultralytics.com/models/sam-3)
- [Perception Encoder README (facebookresearch)](https://github.com/facebookresearch/perception_models/blob/main/apps/pe/README.md), [PE NeurIPS 2025 paper](https://papers.neurips.cc/paper_files/paper/2025/file/57bc0a850255e2041341bf74c7e2b9fa-Paper-Conference.pdf)
- [SigLIP 2 arXiv 2502.14786](https://arxiv.org/pdf/2502.14786), [SigLIP 2 HF blog](https://huggingface.co/blog/siglip2)
- [DINOv3 Meta blog](https://ai.meta.com/blog/dinov3-self-supervised-vision-model/), [DINOv3 license page](https://ai.meta.com/resources/models-and-libraries/dinov3-license/), [license controversy (aggregator)](https://biggo.com/news/202508160125_DINOv3_Commercial_License_Controversy)
- [The Bare Necessities arXiv 2412.01539](https://arxiv.org/html/2412.01539v1), [ConceptGraphs arXiv 2309.16650](https://arxiv.org/html/2309.16650v1), [HOV-SG](https://hovsg.github.io/)
- [Vocabulary-Free Semantic Segmentation arXiv 2502.11891](https://arxiv.org/abs/2502.11891), [Seeing with Partial Certainty arXiv 2501.04947](https://arxiv.org/html/2501.04947)
- [Qwen3-VL-4B vs 8B VRAM guide (aggregator)](https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/), [Artificial Analysis Qwen3-VL-8B (aggregator)](https://artificialanalysis.ai/models/qwen3-vl-8b-instruct)
- [Moondream 3 preview HF](https://huggingface.co/moondream/moondream3-preview), [Moondream 3 blog](https://moondream.ai/blog/moondream-3-preview), [SmolVLM arXiv 2504.05299](https://arxiv.org/pdf/2504.05299)
- [Depth Anything 3 GitHub](https://github.com/bytedance-seed/depth-anything-3), [DA3 arXiv 2511.10647](https://arxiv.org/abs/2511.10647)
- [Qdrant embedding migration](https://qdrant.tech/documentation/tutorials-operations/embedding-model-migration/), [Weaviate vectorizer migration](https://docs.weaviate.io/weaviate/tutorials/vectorizer-migration), [Drift-Adapter arXiv 2509.23471](https://arxiv.org/html/2509.23471v1)