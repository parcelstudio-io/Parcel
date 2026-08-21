# Perception Generalization & Sim-to-Real for Parcel — Research Brief

Provenance marking: **[F]** = I fetched and read the primary source; **[S]** = search-snippet only, treat the number as indicative and re-verify before it lands in a status doc.

---

## A. How the field constructs held-out environments (and why)

### 1. HM3D-OVON (IROS 2024) — the cleanest split template that exists **[F: arxiv.org/html/2409.14296v1]**

**What it does.** Open-vocabulary ObjectNav over 379 household categories / 15k+ annotated instances on HM3D real-world scans. Goal is free-form language at test time, not a fixed 6–21 class list.

**Split construction — this is the part Parcel should copy verbatim.** 181 scans → 145 train / 36 eval scenes, with *"no scene or goal object instance overlap between splits."* Scenes are held out **unconditionally**. Then, holding scenes constant, they vary a *second, orthogonal* axis — the language:

| Split | Categories | SentenceBERT cos-sim to nearest training category |
|---|---|---|
| Val Seen | 79 | 1.00 (identical string) |
| Val Seen Synonyms | 50 | 0.68–0.96 (e.g. "sofa" vs. trained "couch") |
| Val Unseen | 49 | 0.45–0.68 (semantically novel) |

Train: 280 categories, 50 episodes/scene × 145 scenes. Val: 178 eval categories, 3 episodes/scene × 36 scenes **[F, but the val episode count conflicts with a secondary source claiming 3,000/scene — verify before quoting a denominator; the *structure* is what both agree on]**.

**Measured results (SR, %):**

| Method | Val Seen (79 cats) | Val Seen Syn (50) | Val Unseen (49) |
|---|---|---|---|
| DAgRL (learned) | 41.3 | 29.4 | 18.3 |
| DAgRL+OD (learned + detector) | 38.5 | 39.0 | 37.1 |
| VLFM (modular + VLM) | 35.2 | 32.4 | 35.2 |

Learned end-to-end policy loses **11.9–23.0 points** purely from changing the *word*, in the *same scenes*. The modular VLM method is **flat** (35.2 → 32.4 → 35.2).

**Why it matters for Parcel.** This is the single most load-bearing result in the brief. It says: (a) phrasing is a *separate generalization axis* from scene and from object class, and it is the one that breaks systems; (b) Parcel's architecture — hosted LLM proposes a phrase, local open-vocab grounding disposes — is structurally the VLFM row, not the DAgRL row. That is a real, defensible architectural advantage, and the OVON protocol is how you'd prove it.

**Design implication.** Adopt a three-tier phrasing ladder with an explicit embedding-similarity band, computed against whatever vocabulary the scene sidecar declares. Parcel already has SigLIP-2 embeddings in `instructnav/siglip2_onnx.py` — that's the similarity metric. Tier the eval goals into `exact` (1.00), `synonym` (0.68–0.96), `novel` (0.45–0.68) and report three numbers, never one.

### 2. GOAT-Bench (CVPR 2024) — multimodal + lifelong **[F: arxiv.org/html/2404.06609v1]**

Same 36 held-out HM3D scenes; same seen / seen-synonyms / unseen category axis; adds **three goal modalities** (category name, language description, image) and chains 5–10 subtasks per episode without resetting the scene. Val: 10 episodes/scene × 36 scenes = 360 episodes, ~2,669 subtasks **[S for the 2,669]**.

**Results.** Best 2024 baselines land ~29% SR (Modular GOAT 29.4% on object goals; SenseAct-NN Skill Chain 29.5%) **[F for the 29.4 modality breakdown; the split attribution differs across sources — flag]**. Language-description goals are the *hardest* modality (Modular GOAT ~24%, SenseAct-NN ~12%), attributed to "CLIP's limited efficacy in capturing instance-specific features." 2026 SOTA has moved to 62.7% SR / 56.9% SPL (AstraNav-Memory) on Val-Unseen **[S]**.

**Memory result:** removing cross-subtask memory drops Modular GOAT SPL from **17.6 → 9.4 (~2×)** with ~5% SR loss **[F]**. The monolithic RL policy barely changed — its hidden state carried nothing.

**Why it matters for Parcel.** Two things. First, "language description" is exactly Parcel's input mode and it's the weakest modality in the literature — do not assume the LLM's rich phrasing helps grounding; it may hurt. Second, the memory ablation legitimizes `route_memory/place_graph.py` as a *measurable* asset, and tells you the metric that shows its value is **SPL, not SR**.

### 3. GOAT (real-world, Chang et al. 2023) — the denominator standard for a companion robot **[S]**

90 hours, **9 homes, 675 goals across 200+ object instances**, 83% overall SR. Critically: **60% SR on the first goal in a home → 90% after exploration.**

**Why it matters.** This is the correct mental model for Parcel and it dissolves the "generalize vs. memorize" framing. A companion dog on one owner's block *should* memorize that block. The honest split is:
- **Generalize across blocks** — first-visit SR on a never-seen block. This is the perception-generalization claim.
- **Memorize within a block** — Nth-visit SPL improvement. This is the route-memory claim, and it is legitimate.

Report both, never blend them into one success number.

### 4. VLN-CE / R2R and the seen-unseen gap **[S]**

R2R splits: train 10,819 episodes / 61 scenes; val-seen 778 / 53; val-unseen 1,839 / 11; test 3,408 / 18. The historical seen→unseen gap was ~8 points; ScaleVLN drove it under 1% by massively scaling synthetic environments. NaVILA (legged, Go2/H1) reports 88% real-world SR on 25 instructions **[S]** — note the denominator: **25**. That is the norm for real-robot VLN claims and it is thin.

**Design implication.** Parcel should be explicit that N=25-style real trials support a *feasibility* claim, not a *reliability* claim. Pre-register the denominator.

### 5. Habitat Challenge two-phase evaluation **[S]**

Test-Standard = public leaderboard, ≤10 submissions/day, "use judiciously." Test-Challenge = hidden, **5 total submissions**, results withheld until announcement. The submission budget is the anti-overfitting mechanism.

**Design implication for Parcel.** Freeze a **held-out scene + phrasing set that is opened at most N times**, with N logged in the commit gate. With ~7,164 tests green and 26 closed cards, Parcel's risk is precisely leaderboard-style overfitting through iteration: every dev loop that touches the eval set burns generalization evidence. Make the burn auditable.

---

## B. Photorealism, domain randomization, and MuJoCo's specific problem

### 6. Web-trained vision models do **not** transfer to MuJoCo renders **[F: arxiv.org/html/2606.07723v1, Appendix H.2 "vision tools do not transfer to non-photoreal sims"]**

VoLo (2026) tested GroundingDINO, SAM2/SAM3, and Molmo2 on MuJoCo-rendered scenes from RoboCerebra and VLABench. Reported failure modes **[S for the specific modes, F for the section's existence and conclusion]**:
- GroundingDINO returns **empty boxes or wrong-class boxes** for everyday objects (mug, plate, basket).
- SAM2/SAM3 refuse to segment or attach masks to the wrong instance.
- Molmo2's pointing **collapses to image center** on flat-shaded scenes.
- Same three failure modes reproduced on *two independent* MuJoCo benchmarks without tuning → the authors attribute it to **the renderer, not the benchmark**.

They concluded MuJoCo-based benchmarks were "unsuitable" and moved to Isaac Lab's PathTracer, whose photometrically realistic output preserves transfer.

**No side-by-side quantitative table is published.** That gap is an opportunity: Parcel can produce the number nobody has.

**Why this matters for Parcel — bluntly.** This is the direct answer to the owner's focus question. MuJoCo renders flat-shaded primitives with rasterized OpenGL, no ray tracing, no global illumination **[S]**. OWLv2 and SigLIP-2 were trained on web photographs (SigLIP 2: WebLI, ~10B images / 12B alt-texts / 109 languages **[S]**). A MuJoCo sidewalk is a grey box. **An OWLv2 score on a MuJoCo render is not an estimate of OWLv2's real-world performance in either direction** — it is a measurement of a different distribution. It can be *arbitrarily* pessimistic (flat shading destroys the texture cues the model relies on) or *arbitrarily* optimistic (a scene with 6 unambiguous prisms and no clutter, distractors, occlusion, motion blur, or lens flare).

### 7. Real-scan vs. artist-synthetic vs. deployment-splat — the sharpest number available **[F: arxiv.org/html/2509.17430v1, EmbodiedSplat, ICCV 2025]**

Stretch robot, ImageNav, **10 start/goal pairs**, 100-step cap, 1m success radius, one lounge scene:

| Training source | Real-world SR |
|---|---|
| HSSD (artist-made synthetic), zero-shot | **10%** |
| HM3D (real scans), zero-shot | **50%** |
| HSSD fine-tuned on Polycam splat of the deployment scene | 50% |
| HM3D fine-tuned on splat of the deployment scene | **70%** |

Sim-vs-real correlation 0.87–0.97. Sim validation SR ~90%+ vs 70% real — sim overstates by ~20 points even *with* splats.

**Why it matters.** Two independent effects, both quantified: (1) **appearance realism of training data is worth ~40 absolute points** (10% → 50%); (2) **personalizing to the actual deployment environment is worth ~+20 points** on top. For a companion dog serving one owner's block, effect (2) is the strategy. Parcel does not need to generalize to all sidewalks on earth; it needs to generalize to *this* block under unseen lighting, seasons, and clutter — a far cheaper claim to earn and to defend.

**Design implication.** The highest-leverage cutover is not "make MuJoCo prettier." It is: capture the owner's block with the D455 (`camera_channel/d455.py` already exists), build a splat/real-frame corpus, and run perception eval **on real frames**. `EmbodiedSplat`, `Habitat-GS`, `NavGSim`, `GS-Playground` are the 2025–2026 tooling lineage **[S]**.

### 8. UrbanVerse (2026) — outdoor RGB sim-to-real does work, but not semantically **[F: arxiv.org/html/2510.15018v1]**

Converts crowd-sourced city-tour videos into physics-aware sim scenes. **UrbanVerse-100K: 102,530 annotated 3D urban assets**, 306 skyboxes, 288 ground materials; 160 training scenes from 32 city-tour videos across 24 countries. Real-world eval: **16 urban scenes, avg 24.6 m routes, 3 trials each**, two embodiments.

| Robot | SR | Collisions/100 |
|---|---|---|
| Unitree Go2 | **89.7%** | 10.4 |
| COCO wheeled | 77.1% | 22.9 |
| S2E baseline (Go2) | 58.6% | — |

Caveat the paper itself carries: task is **position-goal with RGB + goal coordinates** — no semantics. And the real test cities are unspecified, so "unseen city" is claimed but not verifiable.

**Why it matters.** It proves outdoor sidewalk RGB sim-to-real is achievable at 90% on the exact platform Parcel simulates — *when the sim assets are derived from real video*. It also proves this does nothing for "go to the sidewalk" as a *semantic* query. Parcel needs both halves.

### 9. CityWalker **[S]** — already in the repo (`models/nav/citywalker`, 1.7GB)

2,000+ hours of web-scraped city-walking/driving video, visual-odometry pseudo-labels for action supervision, **77.3% real navigation SR on a Unitree Go1**. Zero-shot web-trained model beat fine-tuned baselines.

**Design implication.** CityWalker is a *label-free urban motion prior* — exactly the "no map, no labeled world" asset. Pair it explicitly: **CityWalker answers "how do I move like something that belongs on a sidewalk"; OWLv2/SigLIP-2 answer "which region is the sidewalk."** Don't ask either to do the other's job.

### 10. Domain randomization — necessary, but not Parcel's main lever **[S]**

Tobin 2017 / Tremblay 2018 established that non-photorealistic randomized synthetic data can beat fine-tuning on real data for *trained* detectors. One MuJoCo visual-DR study reports **90% vs 41% success** under randomized lighting/camera with vs. without full randomization.

**But note the asymmetry that matters for Parcel:** DR is a *training-side* technique. Parcel is not training OWLv2 or SigLIP-2; it is *consuming frozen web-pretrained models*. You cannot domain-randomize a frozen model into liking MuJoCo. DR for Parcel is only useful for (a) anything Parcel *does* train, and (b) as an appearance-robustness *test axis* (randomize lighting/texture and see if grounding survives) — which is a legitimate and cheap eval axis.

---

## C. Do open-vocab detectors actually transfer? Measured degradation

### 11. OWLv2 under domain shift — the false-positive problem **[F: arxiv.org/html/2601.22164v1]**

LAE-80C aerial benchmark: **3,592 images, 86,558 instances, 80 categories**.

| Model | F1 | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|---|
| OWLv2 (ViT-L/14, 428M) | 0.276 | 0.313 | 0.247 | 21,408 | **47,058** | 65,150 |
| LLMDet | 0.125 | 0.441 | 0.073 | 6,308 | 8,009 | 80,250 |
| Grounding DINO (batch) | 0.059 | 0.697 | 0.031 | 2,650 | 1,151 | 83,908 |

Three findings that transfer directly to Parcel:
- **Vocabulary size is the dominant bottleneck.** Cutting the prompt list from 80 classes to the ~3.2 GT classes actually present yielded a **15× F1 improvement (0.5% → 7.4%)**. Semantic confusion, not localization, is the failure.
- **Prompt engineering backfired.** Adding "Aerial view of" raised precision 60.4% → 92.6% but crushed recall 3.9% → 2.3%, net F1 7.4% → 4.5%. **Synonym expansion also hurt** (F1 5.9% → 5.0%).
- The authors' own verdict: this high-recall/low-precision regime "cannot be used as a fully autonomous deployment."

**Design implications for Parcel — three concrete ones.**
1. **Query-conditioned vocabulary.** The LLM proposes `navigate_to("the sidewalk")`. The detector prompt should be *that phrase plus a small curated distractor set*, not a global class list. This is the 15× lever and it is a small code change in `detection_adapter/perception_chain.py`.
2. **Do not auto-expand synonyms into the detector prompt.** Counterintuitive, measured, and Parcel's alias tables in `city_semantics.py` make this an easy mistake to make.
3. **Report precision and recall at the operating threshold**, per class, with TP/FP/FN counts. A single "detection accuracy" number hides a 69% FP rate.

### 12. Ground-truth vs. real perception — budget the cutover cost **[F: arxiv.org/html/2408.02297, "Perception Matters"]**

Habitat ObjectNav, EMSANet/SegFormer/Mask-RCNN:

- Ground-truth perception + shortest-path policy: **99.2% SR**
- Same policy, real segmentation, naive "latest" map aggregation: **30.1% SR**
- Their uncertainty-weighted map aggregation: **74.9% SR**
- **Average GT-vs-real gap across the object-search literature: 25.8 points**, "an error often as big as the gap to an optimal policy."

Their recipe: temperature scaling → calibrated probabilities; normalized entropy → per-pixel uncertainty; **inverse-uncertainty weighting during map fusion**; uncertainty-thresholded "found" decision (ξ=0.4).

**Why it matters.** This is the number for the `scene_truth.json` → real-perception cutover. **Expect a 25–70 point success drop**, and expect roughly half of it to be recoverable by confidence-weighted fusion rather than by a better detector. `navigation/semantic_map.py` currently carries a scalar `confidence ∈ [0,1]` on `SemanticCandidate` — that field is the hook, but a scalar confidence is not a calibrated probability. `value_evidence.py` is where inverse-uncertainty weighting belongs.

### 13. Appearance shift collapses open-vocab mapping even inside sim **[S: OSMa-Bench, IROS 2025]**

ConceptGraphs f-mIoU across lighting conditions on Augmented ReplicaCAD (22 scenes × 4 lighting configs) + HM3D (8 scenes × 2):

| Condition | f-mIoU |
|---|---|
| Baseline | 27.9 |
| Nominal lights | 26.6 |
| Dynamic lights | 28.0 |
| **Camera light** | **14.8** |

A *lighting change alone* halves semantic fidelity. And the absolute ceiling is ~28 f-mIoU — open-vocab semantic mapping is nowhere near solved.

**Design implication.** Lighting/time-of-day must be an explicit eval axis, not an afterthought. An outdoor companion dog sees dawn, noon, dusk, overcast, and headlights.

### 14. "Zero-shot" is contaminated **[S]**

Open-vocab detectors' "novel" classes routinely appear in pretraining corpora; Grounding DINO's gains after Object365/GoldG/Cap4M pretraining are attributed partly to leakage. Proposed mitigations: use *fine-grained* novel classes, or evaluate with detailed captions.

**Design implication — claim hygiene.** When Parcel tests an "unseen object class," it is testing whether *Parcel's configuration* handles a class it wasn't set up for. It is **not** testing whether the model has zero-shot ability — the model has almost certainly seen "sidewalk," "fire hydrant," and "mailbox" millions of times. Word the claim as *system-level* novelty, not *model-level* zero-shot.

---

## D. "Did it generalize" vs. "did it memorize the map"

### 15. Shortcut learning is real and measurable **[S: Hoftijzer et al., ICPR/IJSC 2024]**

Proof of concept: they associated room types with wall colors (bedrooms → green walls) during training. The SOTA ObjectNav agent learned to **navigate to the wall color, not the object**. Under the OOD test (bedrooms → blue walls), **SOTA SR dropped 69%**; their language-based feature augmentation dropped only 23%.

**This is the single best-designed generalization probe in the literature and it is trivially portable to Parcel.** MuJoCo makes it *easier* than Habitat: recolor sidewalk geoms, swap textures, move a landmark. If Parcel's grounding tracks the recolor rather than the semantics, the perception claim is dead — and you find out in an afternoon.

### 16. Blind baselines **[S: Blindfold Baselines for EmbodiedQA; RobustNav ICCV 2021; NaVILA]**

Blindfold (question-only, never sees the environment) baselines achieved SOTA on EmbodiedQA. In NaVILA's VLN-CE-Isaac, the **vision policy beat the blind policy by only 14% SR**. RobustNav (1,100 PointNav / 1,095 ObjectNav episodes across 15 validation scenes) shows standard agents "significantly underperform or fail" under visual corruptions, and that augmentation/adaptation recovers only part of it.

**Design implication.** Parcel's eval **must** ship a blind baseline: a Parcel that ignores all perception and uses only priors + odometry + the route-memory graph. If blind-Parcel scores within ~10 points of full-Parcel on the held-out set, the perception stack is decoration. This is cheap to build and is the most likely finding to embarrass a perception claim later.

---

## Recommended held-out protocol for Parcel

**Factorial, four axes, always report the cell — never the marginal.**

| Axis | Held-out condition | What a pass licenses you to claim |
|---|---|---|
| **S — Scene** | MJCF block never used in dev (OVON: scenes held out *unconditionally*) | Layout generalization |
| **O — Object class** | Goal class absent from every sidecar/prompt list during dev | System handles unconfigured classes |
| **P — Phrasing** | Three SigLIP-2 similarity bands: exact 1.00 / synonym 0.68–0.96 / novel 0.45–0.68 | Robustness to LLM rephrasing |
| **R — Render/appearance** | Lighting + texture randomization **and, separately, real D455 frames** | Appearance robustness / real transfer |

**The oracle ablation ladder — this is how you keep the claim inside what the evidence supports:**

- **L0** `scene_truth.json` — measures router / plan admission / task executive / navigator **only**. Zero perception content.
- **L1** `SegTruthDetector` (MuJoCo seg-truth) — perfect recognition, *real* geometry, occlusion, FOV, depth. Measures mapping + search + arrival.
- **L2** OWLv2 on MuJoCo render — adds recognition error **on a domain the model was never built for**. Publish as *"pipeline-integration evidence"* only. **Never** as a perception accuracy number.
- **L3** OWLv2 / SigLIP-2 on **held-out real D455 clips** of the owner's block. The **only** recognition number that supports a deployment claim.
- **L4** Closed-loop on the real Go2.

Report **L1→L2** and **L1→L3** as *separate deltas*. The repo's B3 docstring already frames the L1→L2 delta as "the honest recognition number the P0 stance predicts" — the correction is that L1→L2 is an *artifact-domain* delta, and only L1→L3 is the recognition number.

**Answer to the owner's focus question, stated plainly:** MuJoCo-render perception evidence is **not** transferable as a recognition claim, in either direction. It is transferable as evidence about *plumbing, geometry, localization, search behavior, arrival logic, and failure handling* — which is genuinely most of the cutover. Structure the eval so every published perception number is tagged L0–L4, and the L2 tier is explicitly labeled non-predictive.

---

## Design pressure

### What Parcel's existing assets get right

- **The two-ruler stance is already correct and ahead of the literature.** `owlv2_onnx.py`'s docstring — `SegTruthDetector` as a geometry-only perfect-recognition ruler, OWLv2 as the same pipeline with recognition error added, the delta as the honest number — *is* the oracle ablation ladder. Most ObjectNav papers train on GT perception and evaluate on real perception without ever isolating the delta; that's exactly the 25.8-point blind spot "Perception Matters" calls out. Parcel built the instrument first.
- **Modular propose/dispose is the phrasing-robust architecture.** OVON's VLFM row (35.2 / 32.4 / 35.2, flat across phrasing) vs DAgRL (41.3 / 29.4 / 18.3, −23 points) is direct empirical support. Parcel's LLM-proposes/local-chain-disposes split is the right side of that table.
- **`false_positive_memory.py` and `multi_view_confirm.py` are the right defenses**, and the aerial OWLv2 result (47,058 FP vs 21,408 TP) says they will be load-bearing, not optional.
- **`scene_semantics.py`'s fail-closed sidecar with no geometry** is unusually disciplined — it already prevents the "second drifting copy of the world" failure, and the same principle should govern the eval-set register.
- **`route_memory/place_graph.py`** matches the GOAT-Bench memory finding (SPL 17.6 → 9.4 without memory) and the GOAT real-world curve (60% first goal → 90% after exploration). The asset exists; it just needs the metric.
- **`models/nav/citywalker`** is the right label-free urban motion prior (77.3% real SR on a Go1), and `camera_channel/d455.py` is the right sensor for building a real-frame corpus.

### What they are missing

1. **A real-frame corpus.** Everything hinges on L3, and L3 does not exist. Nine gate tests skip for want of weights — but even with weights, they'd run on MuJoCo renders. **Highest-value next action: record D455 clips of the owner's actual block and hand-label a few hundred frames.** This does not require the robot to walk; a handheld rig is enough. Without it, no perception claim is defensible.
2. **No calibrated uncertainty.** `SemanticCandidate.confidence` is a scalar in [0,1], not a calibrated probability. "Perception Matters" recovers 30.1% → 74.9% via temperature scaling + entropy-weighted map fusion. That recovery lives in `semantic_map.py` / `value_evidence.py` and is currently absent.
3. **No blind baseline.** Cheap, and it is the control that determines whether the whole perception stack is measurable at all.
4. **No shortcut probe.** Recolor/retexture MuJoCo geoms and re-run. The literature's number is a 69% SR collapse. MuJoCo makes this easier than Habitat — this is a one-day card with an outsized truth yield.
5. **No held-out register with a burn budget.** With ~7,164 tests green and rapid card iteration, the eval set will be silently overfit through dev loops. Habitat's answer is a 5-submission cap on the hidden split. Parcel needs the equivalent, logged.
6. **Query-conditioned vocabulary.** The 15× F1 lever (80 classes → 3.2) is not currently exploited; `perception_chain.py` should narrow the prompt list to the LLM's phrase plus a curated distractor set.
7. **No appearance axis.** OSMa-Bench halves ConceptGraphs' f-mIoU (27.9 → 14.8) on a lighting change alone. Parcel evaluates under one lighting condition.

### Pitfalls

- **The seductive one: publishing an L2 number as "perception accuracy."** VoLo's Appendix H.2 says web-trained detectors fail *categorically* on MuJoCo renders — empty boxes, wrong classes, pointing collapsing to image center — and attributes it to the renderer, reproduced across two independent MuJoCo benchmarks. An OWLv2-on-MuJoCo score is a measurement of a distribution that does not exist in deployment. It can be arbitrarily pessimistic *or* arbitrarily optimistic (6 unambiguous prisms, no clutter, no motion blur, no distractors). **Both error directions, so it is not even a safe lower bound.**
- **Fixing the renderer is the expensive wrong move.** The impulse will be "make MuJoCo photorealistic." EmbodiedSplat says the payoff is in *real-derived* assets (HSSD 10% → HM3D 50% → deployment-splat 70%), not in prettier synthetics. Splat the owner's block; don't shade the primitives.
- **Claiming zero-shot when it's contaminated.** OWLv2 and SigLIP-2 have seen "sidewalk" at web scale. An "unseen class" test measures Parcel's *configuration* generalization, not model zero-shot ability. Overclaiming here is the easiest reviewer kill.
- **Conflating the two memories.** Memorizing the owner's block is the *product*. Memorizing the eval set is *fraud*. They look identical in a success-rate table. Split first-visit SR (generalization) from Nth-visit SPL (memory value), per GOAT's 60%→90% curve.
- **Auto-expanding synonyms into detector prompts.** Measured to *hurt* (F1 5.9 → 5.0). Parcel's alias tables make this a natural and wrong instinct.
- **Thin denominators.** NaVILA's headline 88% is over 25 instructions; EmbodiedSplat's 70% is over 10 start/goal pairs. This is the field norm and it is weak. Pre-register N, report CIs, and say "feasibility" when N is small.
- **Sim overstates even with good assets.** EmbodiedSplat: ~90%+ sim validation vs 70% real, with 0.87–0.97 correlation. Correlation being high does not mean the level transfers — expect a systematic ~20-point optimism offset and state it in every sim-derived claim.

---

Sources:

- [HM3D-OVON (arXiv 2409.14296)](https://arxiv.org/html/2409.14296v1) · [repo](https://github.com/naokiyokoyama/ovon)
- [GOAT-Bench (arXiv 2404.06609)](https://arxiv.org/html/2404.06609v1) · [project page](https://mukulkhanna.github.io/goat-bench/)
- [GOAT: GO to Any Thing (arXiv 2311.06430)](https://arxiv.org/abs/2311.06430)
- [VLFM (arXiv 2312.03275)](https://arxiv.org/abs/2312.03275)
- [ObjectNav Revisited (arXiv 2006.13171)](https://arxiv.org/abs/2006.13171)
- [Habitat Challenge (test-standard / test-challenge)](https://github.com/facebookresearch/habitat-challenge/blob/main/README.md)
- [VoLo, Appendix H.2 — vision tools do not transfer to non-photoreal sims (arXiv 2606.07723)](https://arxiv.org/html/2606.07723v1)
- [EmbodiedSplat (arXiv 2509.17430, ICCV 2025)](https://arxiv.org/html/2509.17430v1)
- [UrbanVerse (arXiv 2510.15018)](https://arxiv.org/html/2510.15018v1)
- [CityWalker (arXiv 2411.17820)](https://arxiv.org/html/2411.17820v2)
- [NaVILA (arXiv 2412.04453)](https://arxiv.org/html/2412.04453v1)
- [Do Open-Vocabulary Detectors Transfer to Aerial Imagery? (arXiv 2601.22164)](https://arxiv.org/html/2601.22164v1)
- [Open-Vocabulary Object Detectors: Robustness Challenges under Distribution Shifts](https://prakashchhipa.github.io/projects/ovod_robustness/)
- [Perception Matters: Uncertainty-Aware Semantic Segmentation (arXiv 2408.02297)](https://arxiv.org/html/2408.02297)
- [OSMa-Bench (arXiv 2503.10331, IROS 2025)](https://arxiv.org/abs/2503.10331)
- [SigLIP 2 (arXiv 2502.14786)](https://arxiv.org/abs/2502.14786)
- [Language-Based Augmentation to Address Shortcut Learning in ObjectNav (arXiv 2402.05090)](https://arxiv.org/abs/2402.05090)
- [Blindfold Baselines for Embodied QA (arXiv 1811.05013)](https://arxiv.org/pdf/1811.05013)
- [RobustNav (ICCV 2021)](https://openaccess.thecvf.com/content/ICCV2021/papers/Chattopadhyay_RobustNav_Towards_Benchmarking_Robustness_in_Embodied_Navigation_ICCV_2021_paper.pdf)
- [Fine-Grained OVD / data-leakage critique (arXiv 2503.14862)](https://arxiv.org/html/2503.14862v2)
- [Tremblay et al., Training Deep Networks with Synthetic Data (CVPR-W 2018)](https://openaccess.thecvf.com/content_cvpr_2018_workshops/w14/html/Tremblay_Training_Deep_Networks_CVPR_2018_paper.html)
- [SD-OVON (arXiv 2505.18881)](https://arxiv.org/abs/2505.18881)
- [HOV-SG (arXiv 2403.17846)](https://arxiv.org/abs/2403.17846) · [ConceptGraphs](https://concept-graphs.github.io/)
- [A Survey of Robotic Navigation and Manipulation with Physics Simulators (arXiv 2505.01458)](https://arxiv.org/html/2505.01458)