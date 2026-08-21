# Embodied-Navigation Benchmark Reference vs. Parcel's Evidence

*Researched 2026-08-21. All numbers below are as-published; where I could not verify a table from a primary source I say so explicitly.*

---

## 0. Headline verdict (read this if you read nothing else)

**Parcel has no evidence that is directly comparable to any embodied-navigation benchmark in this report.** Not one. The gap is not a matter of sample size — it is that Parcel's navigation task is a *different task*: goal resolution against a hand-authored semantic map in a single known scene, versus goal *discovery* under partial observation in held-out scenes. ObjectNav, GOAT-Bench, VLN-CE and HM3D-OVON all score the perception-and-exploration problem that Parcel has designed away.

The precise statement of where Parcel actually sits:

> Parcel's `navigate_to` is, in benchmark terms, **PointGoal navigation with a known map and a GPS+compass** — a task Habitat declared solved in 2019 at 99.9% success / 0.969 SPL on *unseen* scenes (DD-PPO, 2.5B frames). Parcel's version is strictly easier than that, because the map is not merely known, it was hand-built for the deployment scene and never changes. Parcel's nav-direct 5/5 is therefore not a navigation result at all; it is a **language-to-symbol resolution result** with n=5.

The one place Parcel is arguably in *harder* territory than the literature — and the one place a real benchmark number is cheaply reachable — is the intersection of **social compliance + safety refusal + capability honesty under spoken input**, which almost no navigation benchmark scores and which Parcel's local dispose chain is explicitly built for. But Parcel currently reports **zero** of the standard social-nav metrics (PSC, H-Coll, BYR), so it cannot claim that either.

---

## 1. Arrival-semantics crosswalk (the thing you asked for first)

Parcel distinguishes three termination classes. Here is what each benchmark family actually accepts as "arrived":

| Termination rule | Benchmarks that use it | Parcel class that maps |
|---|---|---|
| **STOP within 1.0 m Euclidean of a target *instance* + oracle-visible** (turn/look allowed, no translation) | Habitat ObjectNav (HM3D v0.1/v0.2), HM3D-OVON, GOAT-Bench | **NEAR-object** — closest match, and the strictest |
| **STOP within 3.0 m of a goal *viewpoint*** (disc around a graph node) | R2R, R2R-CE, RxR-CE, REVERIE, NavGPT-2 family | NEAR-object, loosely; a 3× looser radius |
| **Maintain 1–2 m band from a *person* while facing them, for ≥k steps** | Habitat 3.0 Social Navigation | **SOCIAL-distance** — near-exact structural match |
| **≥1.0 m from every human at every timestep** (PSC, not a termination rule but an acceptance rule) | Social-HM3D / Social-MP3D (Falcon), SocialNav literature | **SOCIAL-distance** + Parcel's person-yield |
| **Agent physically inside the target region, AND sees an associated object ≥4% of pixels for ≥2 consecutive steps** | RoomNav (House3D) — **legacy**, SUNCG scenes withdrawn; not a live benchmark | **INSIDE-region** — the *only* analogue, and it's dead |

**Blunt consequence:** Parcel's INSIDE-region class has essentially **no live benchmark analogue**. Every current major navigation benchmark terminates on a *radius around a point or instance*, not on polygon containment. If Parcel wants to claim a number for region arrival, it will be inventing the metric, and must say so. Its NEAR-object class is the one that maps to ObjectNav/GOAT/OVON scoring — and that is exactly the class where Parcel's own evidence says verified arrival works for **1 of 5 shipped object classes**. Its SOCIAL-distance class maps almost perfectly onto Habitat 3.0's 1–2 m + facing rule, which is the single best-aligned benchmark surface Parcel has.

---

## 2. ObjectNav (Habitat / HM3D)

**What it actually measures.** Agent spawns at a random pose in a **previously unseen** photorealistic scan. It is given a category name only (HM3D v0.2 challenge: 6 categories — chair, couch, potted plant, bed, toilet, tv). Sensors: RGB-D + noiseless GPS+Compass on a Hello Stretch body. It must *explore*, *recognize*, and call **STOP**. No map is provided.

**Denominator and scoring rule.**
- Unit = **episode** (a start pose + a category). 2023 challenge test-standard: 1000 episodes, 48-hour compute cap. Val splits are ~1000–2000 episodes over 20–36 scenes.
- **Success** = STOP called within **1.0 m Euclidean of any instance** of the category **AND** the object is oracle-visible from the stop pose by turning / looking up-down (no translation).
- **SPL** = (1/N) Σ Sᵢ · lᵢ / max(pᵢ, lᵢ), lᵢ = geodesic shortest path, pᵢ = agent path length.
- Note: failure to call STOP = failure, even if standing on the object. Termination is part of the task.

**Current representative scores.**

| System | Split | SR | SPL | Date / source |
|---|---|---|---|---|
| FiLM-Nav | HM3D **v0.2** val | **77.0%** | **41.3%** | arXiv 2509.16445v2, 2026-04-15 — current SOTA claim |
| FiLM-Nav | HM3D v0.1 val | 61.7% | 37.3% | same |
| RATE-Nav | HM3D | 67.8% | 31.3% | ACL Findings 2025 (Jul 2025) |
| WMNav | HM3D v0.1 val | 58.1% | 31.2% | Mar 2025 |
| **VLFM (mid-tier reference)** | HM3D v0.1 val | **52.5%** | **30.4%** | ICRA 2024; also Gibson 84.0/52.2, MP3D 36.4/17.5 |
| IPPON (best-SPL, 2023 challenge) | HM3D test-standard | 54% | 34% | EvalAI 2023 leaderboard (*secondary source — I could not render the EvalAI JS leaderboard directly*) |
| SkillTron | HM3D test-standard | 59% | 28% | same caveat |

*Status note:* the Habitat **Navigation Challenge** last ran in 2023 at the CVPR Embodied AI Workshop; ObjectNav progress since is reported on **val splits**, not a live leaderboard. Treat "SOTA" as val-split SOTA.

**Parcel comparability: NOT COMPARABLE.** Six independent blockers, any one of which is fatal:
1. **Unseen scenes.** ObjectNav's entire difficulty is generalization to scans the agent has never seen. Parcel has one hand-built MuJoCo city.
2. **No map.** ObjectNav forbids a prior semantic map. Parcel's navigator *is* a semantic map lookup.
3. **Exploration is the task.** Parcel does not explore; it plans on a known graph.
4. **SPL is unreported and would be meaningless.** A shortest-path planner on a known map scores ~1.0 SPL trivially. Reporting SR without SPL is the classic ObjectNav gaming pattern; reporting SPL from a known map is worse — it looks superhuman and means nothing.
5. **Denominator mismatch.** ObjectNav's unit is an episode from a random start pose. Parcel's unit is a *spoken utterance*, adjudicated against a gold label, with the start pose uncontrolled.
6. **n = 5 vs n ≈ 1000–2000.** See §7.

**No transformation makes this comparable.** The cheapest honest transformation (build 200 ObjectNav-style episodes inside the MuJoCo city, delete the semantic map, force RGB-D-only) would be building a *different robot*.

---

## 3. HM3D-OVON — the right lens for Parcel's "1 of 5 object classes"

**What it measures.** Open-vocabulary ObjectNav: **379 object categories** over 181 HM3D scans, with three val splits that isolate vocabulary generalization:
- **Val Seen** (79 categories seen in training)
- **Val Seen Synonyms** (50 categories — e.g. "sofa" for a trained "couch")
- **Val Unseen** (49 semantically dissimilar, never-trained categories)

**Success rule.** STOP within **1 m within 500 steps**, and the object must occupy **≥5% of the camera view** from a vantage ≤1 m away. (Note this is a *stricter, quantified* visibility rule than vanilla ObjectNav's oracle-visibility.)

**Results (arXiv 2409.14296, 2024; FiLM-Nav row from 2026-04):**

| Method | Val Seen SR/SPL | Val Seen Synonyms | Val Unseen |
|---|---|---|---|
| BC | 11.1 / 4.5 | 9.9 / 3.8 | 5.4 / 1.9 |
| DAgRL | 41.3 / 21.2 | 29.4 / 14.4 | 18.3 / 7.9 |
| VLFM (zero-shot) | 35.2 / 18.6 | 32.4 / 17.3 | 35.2 / 19.6 |
| DAgRL+OD | 38.5 / 21.1 | 39.0 / 21.4 | 37.1 / 19.9 |
| **FiLM-Nav** | **44.9 / 24.5** | 40.1 / 23.1 | **40.8 / 24.4** |

Paper's own words: *"DAgRL shows a drop in success rate of 11.9–23.0% compared to Val Seen when evaluating on Val Seen Synonyms and Val Unseen, suggesting that trained methods struggle to generalize to unseen categories."*

**Parcel comparability: NOT COMPARABLE — and the direction of the gap is the uncomfortable part.**

The OVON framing is what makes Parcel's known defect legible. OVON exists to measure *degradation from a closed vocabulary to an open one*. Parcel's shipped vocabulary is **5 object classes, all seen, all hand-authored, in one scene** — this is a condition strictly *easier* than OVON's Val Seen — and **verified arrival works for 1 of them.** Expressed in the only honest way:

> On the easiest possible split (single known scene, 5-category closed vocabulary, semantic map provided, no perception required), Parcel currently has an arrival predicate capable of producing a scoreable success for **1 / 5 = 20% of its own categories** (95% Wilson CI on the class-coverage proportion: **3.6%–62.4%**, n=5 classes). Benchmark systems achieve 40.8% SR on **49 never-seen categories in 181 never-seen scenes**.

Those two numbers are not on the same axis — 20% is class *coverage*, 40.8% is episode *success* — and it would be dishonest to juxtapose them as if they were. But the qualitative statement stands and should be made: **Parcel's arrival verification does not yet cover its own closed vocabulary, in the regime where coverage should be free.**

**Corollary for nav-direct 5/5.** Under ObjectNav/OVON scoring rules, an episode where the executive *reports* arrival but no arrival predicate fired is **not a success** — it is an unscoreable episode, because success is defined by a geometric+visibility check the benchmark performs, not by the agent's own claim. So the ObjectNav-style read of Parcel's `nav-direct 5/5 PASS` is:

- **At most 1 of the 5 shipped classes could produce a benchmark-legal success.**
- The other 4 produce "STOP called, arrival unverified" — which ObjectNav scores as **failure by default**, since the burden of proof is on the harness.
- The `5/5` therefore measures **tool-call correctness and plan admission**, not arrival. It is a real result about the dispose chain. It is not a navigation result, and must never be written next to an SR number.
- Even taken at face value as a proportion: 5/5 gives a 95% Wilson lower bound of **56.6%**. A true success rate of 60% is not excluded by this evidence. Rule of three: with 0 failures in 5 trials, failure rates up to **60%** remain consistent at 95% confidence.

---

## 4. GOAT-Bench (multimodal lifelong navigation)

**What it measures.** Sequential goal-reaching inside a *single unseen* HM3D scene: **5–10 subtask goals per episode**, each specified in one of three modalities — **category name**, **free-form language description**, or **image** of the specific instance. The "lifelong" claim is that memory of earlier subtasks should make later subtasks cheaper.

**Denominator and scoring.**
- Unit = **subtask**, not episode. Full val set ≈ 2,780 subtasks.
- **Success** = STOP within **1 m Euclidean of the goal object instance**, budget **500 actions per subtask**. (The arXiv HTML renders this as "11m" — a LaTeX artifact; multiple citing papers confirm **1 m**.)
- **SPL** is computed per-subtask with the shortest path measured **from the agent's final position on the previous subtask**, not from the episode start. This is the one benchmark-design idea in this report that Parcel's multi-turn setting could genuinely borrow.

**Scores.**

| Method | Val Seen SR/SPL | Val Unseen SR/SPL | Date |
|---|---|---|---|
| SenseAct-NN Monolithic (RL) | 16.8 / 9.4 | 12.3 / 6.8 | Apr 2024 (original baselines) |
| Modular GOAT | 26.3 / 17.5 | 24.9 / 17.2 | Apr 2024 |
| SenseAct-NN Skill Chain | 29.2 / 12.8 | 29.5 / 11.3 | Apr 2024 |
| 3D-Mem | — | 28.8 / 15.8 | 2024 |
| TANGO | — | 32.1 / 16.5 | — |
| MTU3D (training-based) | — | 47.2 / 27.7 | — |
| **MSGNav (training-free)** | — | **52.0 / 29.6** | arXiv 2511.10376v5, 2026-03-17 |

MSGNav per-modality (first episode): category 63.6 SR / 35.0 SPL; language 57.2 / 33.4; image 59.1 / 42.6.

*Unverified higher claims:* AstraNav-Memory reports 62.7 SR / 56.9 SPL on val-unseen (Dec 2025), and HGR reports 72.41 / 56.22 — but **on a 278-subtask subset**, not the full 2,780. I could not extract either table from a primary source; do not cite these as SOTA without verification.

**Parcel comparability: NOT COMPARABLE (superficially tempting, which is the danger).**

The structural resemblance is real and seductive: Parcel has `recall_memory` + `navigate_to`, a memory category in its corpus, and multi-goal sessions. But:
- GOAT-Bench memory is **instance re-identification from an image or a free-form description in a scene the agent is mapping online**. Parcel's memory is **symbolic key-value recall over a pre-authored map**. These are not the same capability; one is a perception problem, the other a database lookup.
- GOAT-Bench's denominator is subtasks in unseen scenes. Parcel's `memory` category is a handful of queries out of 52 in one scene.
- Parcel's memory category was, per your own caveat, **fixed after both corpus runs**. There is no post-fix measurement at all.

**Transformation that would make a partial comparison possible:** adopt GOAT-Bench's *episode structure and SPL convention* (5–10 chained goals per session; shortest path measured from the previous goal's terminal pose) as an internal harness design. That buys a defensible internal metric. It does **not** buy a GOAT-Bench number.

---

## 5. VLN-CE / R2R (instruction-following navigation)

**What it measures.** An agent is given a **long, step-by-step route description** ("walk down the hallway, turn left at the painting, stop by the second door on the right") and must follow it through an unseen scene using egocentric vision. The instruction encodes a *path*, not just a destination.

**Two action spaces — do not conflate them.**
- **R2R (discrete):** agent teleports between panoramic nav-graph viewpoints. Easier.
- **R2R-CE / RxR-CE (VLN-CE, continuous):** low-level velocity/step control in continuous space, no graph. Historically 10–20 points below discrete on the same instructions.

**Scoring.** Unit = instruction (R2R: 7,189 trajectories across 90 scans; val-unseen is the reported split).
- **SR** = fraction stopping within **3.0 m** of the goal.
- **NE** = mean distance from final position to goal (m).
- **OSR** = fraction where the *closest point on the trajectory* came within 3 m (an upper bound that isolates stopping failure).
- **SPL** as usual; RxR adds **nDTW/SDTW** for path fidelity, because "arrived at the right place by the wrong route" is a failure of *instruction following*.

**Scores (val-unseen).**

| System | Benchmark | SR | SPL | Date |
|---|---|---|---|---|
| ScaleVLN | R2R (discrete) | ~81% | ~70% | 2023 |
| **NavGPT-2 (FlanT5-XXL)** | R2R (discrete) | **73.8%** | **61.1%** | ECCV 2024 |
| NavGPT-2 (FlanT5-XL) | R2R (discrete) | 69.9% | 58.9% | ECCV 2024 |
| **NaVILA** | R2R-**CE** | 54.0% | 49.0% (NE 5.22 m, OS 62.5%) | Dec 2024 |
| NaVILA | RxR-CE | 44.0% | 44.0% (NE 6.77 m) | Dec 2024 |
| StreamVLN | R2R-CE | 56.9% | 51.9% | 2025 |
| DualVLN | R2R-CE | 64.3% | 58.5% | 2025–26 |
| DualVLN | RxR-CE | 61.4% | 51.8% | 2025–26 |
| Qwen-VLA-Instruct | RxR-CE | 59.6% | 47.8% | 2026 |

**NaVILA is the closest thing in this entire report to Parcel's body.** It is a legged-robot VLA deployed on a **Unitree Go2** (and H1), and it introduced **VLN-CE-Isaac**, a physics-realistic legged-robot VLN benchmark (1,077 traversable trajectories drawn from the 1,839 R2R val-unseen trajectories) precisely because prior VLN ignored joint-level locomotion. Real-world protocol: **25 instructions × 3 repetitions = 75 trials** across workspace / home / outdoor; **88% overall**, **75% on complex (3+ command) instructions**. That 88% on n=75 carries a 95% CI of roughly **[78.7%, 93.6%]** — a useful calibration for what "a credible small-n real-robot claim" costs.

**Parcel comparability: NOT COMPARABLE.**
- **The task is different in kind.** R2R measures *route following from a narrated path*. Parcel's nav-direct measures *destination resolution from a single named goal*. Parcel does not accept, parse, or execute multi-step route descriptions. A benchmark that scores nDTW path fidelity has nothing to score in Parcel.
- Parcel has no unseen-scene split.
- Parcel does not report NE, OSR, or path length — so even the 3 m NEAR-object analogue cannot be evaluated.

**Partial-comparability transformation (expensive, and I do not recommend it):** author an R2R-style instruction corpus over the MuJoCo city with reference trajectories, then report SR@3m / NE / SPL / nDTW. This is 2–4 weeks of harness work and yields a **private single-scene benchmark** whose numbers cannot be placed on the R2R leaderboard. The only thing it would buy is internal regression tracking — which a smaller instrumented harness buys more cheaply.

---

## 6. Social navigation — the family where Parcel is *not* obviously behind

This is the one place where Parcel's design is aimed at something the field measures, and where the transformation cost is genuinely low.

### 6a. Habitat 3.0 Social Navigation (Oct 2023) — best structural match to Parcel's SOCIAL-distance class

**Task.** Robot must **find and then follow a moving humanoid** in an indoor scene.

**Metrics (exact rules).**
- **Finding Success (S):** robot reaches within **1–2 m of the humanoid while facing it**, within the episode step limit.
- **SPS** = S · l / max(l, p), in *steps* against an oracle.
- **Following Rate (F):** fraction of steps maintaining the 1–2 m band while facing.
- **Collision Rate (CR):** fraction of episodes ending in robot–humanoid collision.

| Policy | S | SPS | F | CR |
|---|---|---|---|---|
| Heuristic expert (**privileged map**) | 1.00 | 0.97 | 0.51 | **0.52** |
| End-to-end RL (no map) | 0.97 | 0.65 | 0.44 | **0.51** |
| SDA Stage-2 (Feb 2025) | 0.91 | 0.45 | 0.39 | 0.57 |

**Note the number that should stop you:** even the **privileged-map heuristic expert collides with the human in 52% of episodes** while scoring 1.00 finding-success. This benchmark's "success" metric is *fully compatible with hitting the person*. Later work (SDA, Feb 2025) added **Backup-Yield Rate (BYR)** — frequency of backward/yield motion when human distance < 1.5 m — precisely because S/SPS were blind to this.

**This is the strongest argument you have that Parcel's problem is harder in the dimension it cares about.** Parcel's SafetySupervisor + person-yield navigator is engineered to make the *collision-and-proxemics* dimension the primary constraint, whereas the flagship social-nav benchmark treats it as an afterthought metric that its own reference expert fails half the time.

### 6b. Social-HM3D / Social-MP3D + Falcon (ICRA 2025)

**Task.** PointGoal navigation in human-populated scenes: reach the goal (within **2.0 m**) while avoiding static obstacles and moving humans. Social-HM3D = 844 HM3D scenes; Social-MP3D = 72 MP3D scenes (distribution-shift test).

**Metrics with exact thresholds.**
- **Suc.** — reached goal.
- **SPL**, **STL** (success weighted by *time*).
- **PSC (Personal Space Compliance)** — **% of timesteps maintaining ≥1.0 m from all humans** (threshold derived from human radius 0.3 m + robot radius 0.25 m).
- **H-Coll** — % of episodes with any direct human–robot contact.
- Composite: **Final Score = 0.4·SR + 0.2·SPL + 0.2·PSC + 0.2·(1 − H-Coll)**.

| Method | Dataset | Suc. | SPL | STL | PSC | H-Coll |
|---|---|---|---|---|---|---|
| A* | Social-HM3D | 46.14 | 46.14 | 46.12 | 90.56 | 53.50 |
| ORCA | Social-HM3D | 38.91 | 38.91 | 38.44 | 90.55 | 47.52 |
| Proximity-Aware | Social-HM3D | 20.11 | 18.57 | 19.51 | **92.91** | **33.99** |
| **Falcon** | Social-HM3D | **55.15** | **55.15** | 54.94 | 89.56 | 42.96 |
| **Falcon** | Social-MP3D | **55.05** | 55.04 | 54.80 | 90.01 | 42.19 |
| HUMA (later) | Social-MP3D | ~70.35 | — | — | — | 20.82 *(secondary source)* |

Read the Proximity-Aware row carefully: it has the **best** PSC and the **best** H-Coll and the **worst** success rate by 35 points. The safety/throughput trade-off is explicit and unresolved in this literature.

### 6c. SEAN 2.0 / SEANavBench, SocNavBench, and the state of the field

- **SEAN 2.0** (RA-L 2022, Yale): Unity + ROS high-fidelity human sim with **social-situation logic classifiers** (five common situations) and generated crowd motion; metrics include success rate, **path irregularity** (mean |angle between robot heading and goal vector|, radians; a straight line = 0), and **personal-space duration** (average time inside minimum-comfortable personal space). SEANavBench = SEAN 2.0 + SocNavBench, launched as an ICRA'22 competition.
- **SocNavBench** (THRI 2021): grounded sim replaying real pedestrian datasets.

**Meta-evidence you should quote when positioning Parcel.** A methodological review of **85 IEEE papers (Jan 2020 – Jul 2025)** found: **39 distinct metrics** in use; **52.2%** of papers gave **no rationale** for their metric choice; **65%** compared against fewer than three algorithms; only **18.9%** ran human surveys; and of 26 papers claiming superiority, **22 relied on ≤2 metrics or ≤2 baselines**. Separately, a correlation study (Oct 2025) of 11 quantitative metrics vs. 4 human survey dimensions found only five metrics reach Spearman > 0.4 (p<0.05) against human perception — **intimate-space occupancy, average minimum distance to person, personal-space occupancy, average linear velocity, time to goal** — while the theoretically-motivated "social work" metric does **not** correlate. Conclusion: *quantitative metrics cannot replace human surveys; surveys remain the gold standard for final validation.*

**Parcel comparability: PARTIALLY COMPARABLE — and this is the only "partially" in the report that is worth acting on.**

- **What transfers today, at near-zero cost:** PSC (≥1.0 m from all humans, per-timestep) and H-Coll (any contact, per-episode) are **pure trajectory post-processing**. If Parcel's navigator already logs robot pose and person pose per tick — which person-yield requires — these two numbers are computable from **existing recorded runs with no model calls and no new simulation**. Same for BYR (backward/yield motion when distance < 1.5 m) and average-minimum-distance-to-person.
- **What does not transfer:** Parcel has **no crowd**. One owner is not a pedestrian population. Social-HM3D runs multi-human scenes with motion models; Habitat 3.0 runs an actively-moving humanoid with a policy. A PSC computed against a single scripted owner in one scene is a *self-report*, not a benchmark number, and must be labelled as such.
- **What Parcel must not do:** report PSC/H-Coll and place them beside Falcon's 89.56 / 42.96. Different scene count (1 vs 844), different human count (1 vs many), different human motion model. The correct framing is: *"Using the Social-HM3D metric definitions (PSC at 1.0 m, H-Coll per episode), Parcel measures X / Y over N single-owner episodes in one scene. This is not a Social-HM3D result and is not comparable to Falcon's 89.56 / 42.96."*

---

## 7. The language-goal family — the closest *evidentiary* analogue Parcel has

### LM-Nav (CoRL 2022)

**What it measures.** Free-form natural-language instruction → landmark sequence (GPT-3) → visual grounding of landmarks (CLIP) → execution (ViNG topological policy). No fine-tuning, no language-annotated robot data. Real-world **outdoor**, no prior semantic map.

**Evaluation protocol — read this closely, it is the honest mirror of Parcel's corpus runs.**
- **n = 20 instructions**, multiple outdoor environments, **>6 km total traversal**, individual routes up to **800 m**.
- **Success rule is human-adjudicated and disjunctive:** a walk succeeds if *(1)* it matches the path the user intended, **or** *(2)* the landmark images the search algorithm extracted actually contain the named landmarks.
- Result: **17/20 = 85%**, "without collisions or disengagements (an average of 1 intervention per 6.4 km)."
- Failure analysis: all three failures were **grounding** failures — CLIP could not localize hard landmarks (fire hydrant, cement mixer) and underexposed images.

**95% Wilson CI on 17/20: [64.0%, 94.8%].** LM-Nav — a CoRL paper, widely cited — shipped a headline number whose confidence interval spans 31 points. This is the precedent that makes Parcel's small-n evidence *publishable in form*, if not in magnitude.

### NavGPT-2 (ECCV 2024)

Discrete R2R nav-graph. Val-unseen: **73.8 SR / 61.1 SPL** (FlanT5-XXL, 5B), **69.9 / 58.9** (XL, 1.5B) — a **+3.79 SR** gain from the 3.3× parameter scale-up. Closes the gap to VLN specialists like DUET; ScaleVLN remains ahead at ~81/70.

**Parcel comparability:**
- **vs. NavGPT-2: NOT COMPARABLE.** Same objection as §5 — R2R route-following ≠ destination resolution, plus discrete nav-graph action space.
- **vs. LM-Nav: PARTIALLY COMPARABLE in *methodology*, NOT in *number*.** Both are small-n, human-adjudicated, single-operator, hand-selected-environment evaluations of an LLM proposing over a fixed downstream execution stack. That is a real structural match and the right precedent to cite for Parcel's evaluation *design*. But LM-Nav solves a **strictly harder perception problem** (CLIP-grounding landmarks in outdoor imagery with no prior map, over 800 m) and its 85% is on **end-to-end physical traversal**, whereas Parcel's 5/5 is on **tool-call correctness with unverified arrival for 4 of 5 classes**. Putting "Parcel 100%" next to "LM-Nav 85%" would be the single most misleading sentence anyone could write about this project.

---

## 8. Statistical reality check on Parcel's specific numbers

Computed 95% Wilson intervals, with rule-of-three upper bounds on failure rate where the observed count is perfect:

| Parcel claim | Point est. | 95% Wilson CI | Rule-of-three: failure rates NOT excluded |
|---|---|---|---|
| nav-direct 5/5 PASS (replay) | 100% | **[56.6%, 100%]** | up to **60%** |
| chat tool+args 6/6 direct nav | 100% | **[61.0%, 100%]** | up to **50%** |
| canonical spoken e-stop 7/7 live | 100% | **[64.6%, 100%]** | up to **42.9%** |
| estop-pos 3/3 (replay, dead lane) | 100% | **[43.8%, 100%]** | up to **100%** |
| arrival-relation hints 12/12 | 100% | [75.7%, 100%] | up to 25% |
| self-consistency 15/15 | 100% | [79.6%, 100%] | up to 20% |
| E1 pack 4/6 | 66.7% | [30.0%, 90.3%] | — |
| live_run_1 PASS 13/52 | 25.0% | [15.2%, 38.2%] | — |
| replay_run_1 PASS 10/52 | 19.2% | [10.8%, 31.9%] | — |
| live PASS+PARTIAL 22/52 | 42.3% | [29.9%, 55.8%] | — |
| fabricated junk `navigate_to` 5/6 | 83.3% | [43.6%, 97.0%] | — |
| required follow-up asked 0/6 | 0% | [0%, 39.0%] | — |

**What n buys you, for planning:** a perfect run gives a 95% lower bound of 56.6% at n=5, 72.2% at n=10, 83.9% at n=20, 88.6% at n=30, **93.1% at n=52**, 96.3% at n=100. **If Parcel wants to claim "≥90% reliability" on any category, the minimum perfect-run size is n=30.** For the safety-critical e-stop path specifically, n=7 licenses no claim stronger than "≥65%," which is not a safety claim anyone should accept.

**And the caveat that dominates all of the above:** both 52-query corpus runs **predate** the cards that fixed silence, scene answerability, memory recall, unknown-place refusal, and the safety ring. In replay_run_1 the hosted lane **died at q30**, so roughly 20 of 52 verdicts describe a dead lane, not the product — meaning the replay denominator is effectively ~32 for product claims and ~52 only for "what the harness recorded." **The current build has never been measured on the corpus at all.** Any benchmark-adjacent number sourced from those runs is describing a build that no longer exists. This should be stated in the first line of any external artifact, not a footnote.

---

## 9. The honest positioning statement

Write this, verbatim or close to it, wherever Parcel is compared to the literature:

> **Parcel does not compete on the axis these benchmarks measure.** ObjectNav, HM3D-OVON, GOAT-Bench and VLN-CE all exist to measure *perceptual and exploratory generalization to unseen environments*. Parcel navigates one hand-built MuJoCo city using a hand-authored semantic map with a closed 5-class object vocabulary. It has no perception generalization, is not designed to have any, and its navigation problem is therefore **strictly easier than every benchmark in this report** — easier, specifically, than PointGoal-with-GPS+Compass, which Habitat declared solved at 99.9% SR / 0.969 SPL on *unseen* scenes in 2019.
>
> Parcel's genuine difficulty is elsewhere, and it is a difficulty the navigation literature largely does not score: a hosted, non-deterministic voice model proposing tool calls over an open-ended spoken channel, with a local deterministic chain that must **refuse** unsafe or out-of-capability requests, **latch** an emergency stop, **yield** to a person in the path, and **decline to fabricate** a capability it does not have. On the closest comparable surface — Habitat 3.0's social-navigation metrics — the field's own privileged-map reference expert scores 1.00 finding-success while colliding with the human in **52% of episodes**, and a 2025 review of 85 papers found that most social-nav work compares against fewer than three baselines on unjustified metrics. Parcel is not behind the state of the art on social compliance; **nobody has a defensible state of the art on social compliance.**
>
> But Parcel cannot presently claim credit for that either, because it reports **none** of the standard social metrics (PSC, H-Coll, BYR, minimum-distance-to-person), and its two 52-query corpus runs predate the five fix cards, so **the shipped build has no measurement of any kind on its own corpus.**

---

## 10. What Parcel would have to run to claim a benchmark number

Ordered cheapest-first. Each item names the existing artifact it reuses.

### Tier 0 — free, this week, no model calls, no new simulation

**0.1 — Compute PSC / H-Coll / BYR / min-distance from existing navigator logs.**
Reuses: the **person-yield navigator's existing pose logs** from the E1 recorded eval pack and both corpus runs. Pure post-processing.
Definitions to adopt verbatim so the numbers are at least *interpretable* by the field:
- **PSC** = % of timesteps with distance ≥ **1.0 m** to every person (Social-HM3D convention: human radius 0.3 + robot 0.25).
- **H-Coll** = % of episodes with any contact.
- **BYR** = frequency of backward/yield motion when person distance < **1.5 m** (Habitat 3.0 / SDA convention).
- **Average minimum distance to person** — one of only five metrics shown to correlate (Spearman > 0.4) with human survey judgment.
Deliverable: *"Parcel, single-owner, one scene, N episodes: PSC = x%, H-Coll = y%, BYR = z. Metric definitions from Social-HM3D / Habitat 3.0. Not a Social-HM3D result — 1 scene, 1 human, scripted motion."*
**Cost: hours. This is the single highest value-per-hour item in the whole list.**

**0.2 — Log path length and geodesic-optimal length; publish SPL, and immediately explain why it is near 1.0.**
Reuses: the **navigator's plan output** (it already computes a route on a known graph).
The point is not to claim a good SPL — it will be ~0.9–1.0 and meaningless. The point is that publishing it, *with the explanation that a known-map planner trivially maximizes it*, is what distinguishes an honest report from a misleading one. It also pre-empts the obvious reviewer objection.
**Cost: hours.**

**0.3 — Restate `nav-direct 5/5` with its confidence interval and its arrival caveat, in the same sentence.**
Reuses: **replay_run_1 verdicts**.
Mandatory wording: *"5/5 on nav-direct tool-call correctness (95% CI 56.6%–100%, n=5). This scores tool selection and plan admission, not arrival: verified arrival predicates exist for 1 of 5 shipped object classes, so under ObjectNav-style scoring at most 1 class could produce a scoreable success."*
**Cost: minutes. Not doing this is the largest credibility risk in the current evidence set.**

### Tier 1 — days, reuses the existing harness

**1.1 — Re-run the 52-query corpus on the current build (replay lane), with the hosted-lane death fixed or fenced.**
Reuses: the **52-query corpus, pre-registered gold labels, and the replay harness**. Known cost: **$0.85 per full replay run**.
This is non-negotiable before *any* external number is quoted. Right now the best-documented result describes a build superseded by five fix cards, with ~20 verdicts describing a dead lane. Run it 3× ($2.55 total) to get a variance estimate rather than a point.
**Cost: ~$3 and a day. There is no defensible reason not to have done this already.**

**1.2 — Instrument arrival verification for all 5 object classes, then re-run nav-direct.**
Reuses: the **1 working arrival predicate** as the template; the **navigate_to surface**; the corpus's nav-direct + nav-indirect + nav-invalid items.
Adopt the ObjectNav acceptance rule for the NEAR-object class — **terminate within 1.0 m of the instance, with a visibility check** — and RoomNav-style containment for the INSIDE-region class (**inside polygon**, since no live benchmark offers a better rule; say so explicitly). Adopt Habitat 3.0's **1–2 m + facing** rule for the SOCIAL-distance class.
This converts Parcel's arrival semantics from prose into three machine-checkable predicates, which is the precondition for *every* remaining item.
**Cost: days. Highest structural leverage.**

**1.3 — Expand the safety-critical cells to n = 30 each.**
Reuses: the **e-stop test protocol** (already 7/7 live) and the **ASR-variant generation path** that currently has one untested positive.
n=30 perfect ⇒ 95% lower bound **88.6%**; n=52 perfect ⇒ **93.1%**. n=7 licenses only "≥64.6%," which is not a safety claim. Include the untested ASR-variant positive and adversarial near-miss negatives — SafeAgentBench (arXiv 2412.13178) found the best embodied-LLM baseline reached **69% success on safe tasks but only 5% rejection of hazardous ones**, and the most safety-conscious model managed **10%** rejection. Parcel's refusal path is its differentiator; it deserves the sample size.
**Cost: days. Cheapest path to a number that is both defensible and genuinely favourable.**

**1.4 — Report the fabrication result as the headline negative, at n = 30.**
Reuses: the **chat-API bench** (currently 5/6 fabricated a junk `navigate_to` when the needed tool was absent; 0/6 asked the required follow-up from injected state).
At n=6 the CI on the fabrication rate is [43.6%, 97.0%] — too wide to act on. At n=30 it becomes a real engineering target, and it is *directly analogous* to SafeAgentBench's rejection-rate finding, which gives it external context. A project that publishes its own fabrication rate is a project people believe about everything else.
**Cost: days, ~$5 in API spend.**

### Tier 2 — weeks, and only if an external claim is genuinely required

**2.1 — Adopt GOAT-Bench's episode structure and SPL convention as the internal multi-goal harness.**
Reuses: the **corpus categories** (compound, memory, ambiguous) restructured into 5–10 chained goals per session, with shortest-path measured **from the previous goal's terminal pose**. Yields a defensible internal lifelong-nav metric. **Does not yield a GOAT-Bench number.**

**2.2 — Add a scripted multi-pedestrian scenario library to the MuJoCo city.**
Reuses: the **person-yield navigator** and Tier-0 metric code. Borrow SEAN 2.0's **five social-situation logic classifiers** (intersection, overtaking, head-on, etc.) as the scenario taxonomy so the scenarios are at least named the way the field names them. Then Tier-0's PSC/H-Coll/BYR become meaningful rather than degenerate. This is the only realistic path to Parcel producing a number that a social-navigation researcher would engage with.

**2.3 — A small human-survey study (unobtrusiveness, friendliness, smoothness, avoidance foresight; 5-point Likert).**
The correlation literature is unambiguous: quantitative social metrics **cannot** replace human surveys, and only five of eleven common metrics correlate above Spearman 0.4. For a *companion* robot — where the product claim is about how it feels to be around, not how fast it reaches a point — this is arguably the most valid measurement available, and it is cheap relative to building a benchmark. Note that only **18.9%** of 85 surveyed social-nav papers ran one; doing so would place Parcel in the top fifth of the field on evaluation rigour.

### Explicitly NOT worth doing

- **Running ObjectNav / HM3D-OVON / R2R-CE.** Parcel would have to delete its semantic map and add a perception stack — i.e. build a different robot. If the goal is a leaderboard number, the honest answer is that Parcel is not a candidate and should not pretend to be.
- **Authoring an R2R-style route-instruction corpus in the MuJoCo city.** 2–4 weeks for a private single-scene benchmark with no unseen split and no external comparability. A smaller instrumented harness (1.2 + 1.3) gives better regression signal per week.
- **Quoting any current number without the pre-fix caveat.** Both corpus runs describe a superseded build. Until 1.1 runs, every number in Parcel's evidence set is historical.

---

**Sources:**

ObjectNav / HM3D: [Habitat Challenge 2023](https://aihabitat.org/challenge/2023/) · [FiLM-Nav (arXiv 2509.16445)](https://arxiv.org/html/2509.16445) · [VLFM (arXiv 2312.03275)](https://arxiv.org/html/2312.03275) · [RATE-Nav, ACL Findings 2025](https://aclanthology.org/2025.findings-acl.341/) · [IPPON (arXiv 2410.19697)](https://arxiv.org/abs/2410.19697) · [WMNav (arXiv 2503.02247)](https://arxiv.org/html/2503.02247) · [DD-PPO (arXiv 1911.00357)](https://arxiv.org/abs/1911.00357)
Open-vocabulary: [HM3D-OVON (arXiv 2409.14296)](https://arxiv.org/html/2409.14296v1)
GOAT: [GOAT-Bench (arXiv 2404.06609)](https://arxiv.org/html/2404.06609v1) · [project page](https://mukulkhanna.github.io/goat-bench/) · [MSGNav (arXiv 2511.10376)](https://arxiv.org/html/2511.10376) · [GOAT (arXiv 2311.06430)](https://arxiv.org/pdf/2311.06430)
VLN: [NaVILA (arXiv 2412.04453)](https://arxiv.org/html/2412.04453v1) · [NaVILA project](https://navila-bot.github.io/) · [NavGPT-2 (arXiv 2407.12366)](https://arxiv.org/html/2407.12366v1) · [VLN-CE (ECCV 2020)](https://www.ecva.net/papers/eccv_2020/papers_ECCV/papers/123730103.pdf)
Social nav: [Habitat 3.0 (arXiv 2310.13724)](https://arxiv.org/html/2310.13724) · [Following the Human Thread (arXiv 2404.11327)](https://arxiv.org/html/2404.11327) · [Falcon / Social-HM3D (arXiv 2409.13244)](https://arxiv.org/html/2409.13244) · [SEAN 2.0](https://sean.interactive-machines.com/) · [SEAN (Yale)](https://interactive-machines.gitlab.io/assets/papers/tsoi-HAI20.pdf) · [SocNavBench (THRI)](https://dl.acm.org/doi/10.1145/3476413) · [SocNav benchmarking review (arXiv 2510.22448)](https://arxiv.org/html/2510.22448v1) · [Metrics vs Surveys (arXiv 2510.02941)](https://arxiv.org/html/2510.02941v2) · [Benchmarking Social Robot Navigation (Francis et al. 2023)](https://storage.googleapis.com/pirk.io/papers/Francis.etal-2023-SocialNav.pdf)
Language-goal: [LM-Nav (arXiv 2207.04429)](https://ar5iv.labs.arxiv.org/html/2207.04429) · [LM-Nav (PMLR v205)](https://proceedings.mlr.press/v205/shah23b)
Adjacent: [SafeAgentBench (arXiv 2412.13178)](https://arxiv.org/html/2412.13178v1) · [NaviTrace (arXiv 2510.26909)](https://arxiv.org/html/2510.26909v1) · [RoomNav / House3D](https://github.com/facebookresearch/House3D/blob/master/House3D/roomnav.py)