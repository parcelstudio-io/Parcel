# RL1 — Strongest honest case FOR custom RL/IL training

**Workstream:** RL1 (Claude Opus stand-in)  
**Date:** 2026-08-07  
**Hardware frame:** NVIDIA RTX 5000 Ada, 32 GB ECC GDDR6, ~250 W TDP  
**Companion question:** RL2 argues reuse; this document steelmans ownership of training.

---

## Executive verdict

| Decision surface | Verdict | One-line reason |
| --- | --- | --- |
| Train a Parcel-owned policy **now** | **NO-GO** | Safety, state, simulator, dataset, serving ABI, and frozen eval are not valid; measured failures are mostly non-policy |
| Train **from scratch** (E2E nav, VLA, or Sport-replacing locomotion) | **NO-GO** | Literature and Parcel constraints agree: priors + hierarchy beat greenfield; one 32 GB card cannot fund foundation pretraining |
| **Later** narrow custom IL → optional sim RL on a bounded residual | **CONDITIONAL GO** | Highest-return Parcel-owned learning is a small trajectory ranker / social critic, or LoRA/DAgger adaptation of a released waypoint policy—never motor authority |

**Bottom line:** Custom learning may become worthwhile for a narrow,
companion-specific residual only after released baselines demonstrably plateau.
It is not worth owning as a from-scratch dog brain. Spend **0 RL GPU-hours**
until prerequisites pass; even then, authorize a capped adaptation pilot only
if the residual and sampler feasibility gates pass.

The owner's skepticism of from-scratch is correct and is **not** a reason to reject all custom training. The honest FOR case is **adaptation after a competent baseline**, not greenfield RL.

---

## 1. Steelman: when Parcel might eventually own narrow training

### 1.1 Released policies plateau on product-shaped residuals

Open models solve adjacent jobs (owner track waypoints, RGB-D local trajectories, urban traversability priors, instruction grounding). None of them is Parcel's composition:

- enrolled-owner identity with TTL and multi-frame confirmation;
- typed executive modes (`ApproachOwner` vs persistent follow, interrupt/recovery);
- independent metric-geometry safety that must never be traded in a reward;
- city sidewalk / storefront / proxemic preferences that are preference-shaped, not collision-shaped.

If classical planners and frozen open weights are exhausted on a **frozen,
attributable** eval, one plausible remaining gap is preference ranking among
already-safe short trajectories—not “invent navigation.” Only measured residuals
can establish whether Parcel-owned data has leverage on interventions,
pass-side, formation distance, jerk comfort, or mode-conditioned HOLD.

### 1.2 The field’s winning pattern is IL priors + narrow RL/IL post-training

Recent navigation and robot-policy results converge on the same recipe. They do **not** win by training a dog from random weights on one workstation.

| Evidence | What it shows for Parcel |
| --- | --- |
| **X-NavDP** (arXiv 2607.28560): online RL post-trains a pretrained NavDP-class diffusion policy; sim SR **61.20% → 84.28%**; real hard-case SR reported **10% → 65%**; learns trap escape / long detours while keeping waypoint→MPC→locomotion hierarchy | Post-training buys behaviors offline IL never saw; still outputs trajectory chunks, not joints |
| **NavOL** (ICML 2026): online imitation on a pretrained diffusion nav policy with privileged planner labels; avoids reward engineering; scales in IsaacLab parallel rollouts | Prefer DAgger/online IL **before** RL when a teacher exists |
| **Beyond Imitation / GRPO on NavDP** (arXiv 2603.12868): freeze encoders + early DiT layers; train ~**11.83 M / 173.59 M** params (~6.8%); ~**1 h train + 2 h collect per round on one RTX 6000 Ada**; author reports under 17 GB peak, SR **52.0% → 58.7%**, safer clearances, and zero-shot real-quadruped transfer | Demonstrates selective fine-tuning on a 48 GB RTX 6000 Ada; the reported peak makes 32 GB memory-plausible, but Parcel has not profiled the workload locally |
| **FLaRe** (arXiv 2409.16578): RL fine-tune of BC foundation policies; +23.6% sim / +30.7% real over prior SoTA on long-horizon mobile manip; **&lt;1 day** embodiment adaptation with sparse rewards, but no disclosed GPU hardware | RL can break a pretrained plateau; the timing does not establish Parcel-device feasibility |
| **CityWalker** (arXiv 2411.17820): web-scale video pretrain + fine-tuning on **6 h of recorded Go1 teleoperation data** → **77.3%** author-reported real urban success, based on small direction strata and a permissive 5 m arrival threshold; training compute is not disclosed | Parcel stores a checkpoint, but neither the data duration nor score predicts local training cost or product quality |
| **MiniCPM-RobotTrack**: ~0.9B total policy with a ~0.5B language backbone; public finetune path with gradient checkpointing; DAgger-style self-evolving data on Go2 | Owner-follow adaptation is IL/DAgger-shaped; Parcel GPU cost is unmeasured |
| **HALO** (arXiv 2508.01539): offline preference → reward used inside MPC **or** offline policy; real Husky gains on success / path length / Frechet-to-expert | Preference learning can sit **beside** classical control—ideal for Parcel’s authority model |
| **CE-Nav**: IL then embodiment-specific RL refinement on Go2 lineage (checkpoint/eval caveats remain) | Matches Parcel’s eventual “adapt the narrowest head” hypothesis |

**Implication:** The strongest FOR case is that Parcel may eventually benefit
from **its own narrow post-training loop** if sensor-only, task-labeled
residuals survive strong baselines—not that Parcel should recreate
NavDP/InternVLA/Sport.

### 1.3 Bounded ranking is the highest-leverage Parcel-owned artifact

The least dangerous, highest-return custom learner is discrete selection among hard-admissible short trajectories:

```text
sampler → K feasible 2–3 s SE(2) trajectories + HOLD
  → hard masks (stale / collision / road / footprint / TTC)
  → learned ranker picks index or abstains
  → deterministic re-validate
  → common controller + independent metric-geometry stop + Unitree Sport
```

Why this is the FOR case’s center of mass:

1. **Authority-preserving.** Collision, sensor loss, forbidden road, and TTC stay constraints, never soft reward terms.
2. **Lower-dimensional hypothesis.** Action space is `K+1` indices rather than
   continuous velocity or joints, but this alone does not prove sample
   efficiency.
3. **Fits preference literature.** HALO-style ranking and trajectory-preference offline methods align with “choose among safe options,” not “discover locomotion.”
4. **Plausibly fits the RTX 5000 Ada.** A small critic/ranker or compact-head
   LoRA is the right class to profile first; no Parcel training workload has
   yet established peak VRAM or throughput.
5. **Matches measured product needs.** NAV_INSTRUCT is currently **4% (1/25)** with failures dominated by planning, grounding/refusal, and termination. After those are fixed, the durable learned gap is social/local ranking and owner-follow comfort—not greenfield PointNav.

Additive residual RL on velocities/joints is a weaker FOR case for Parcel: it fights Sport’s authority and the independent safety lane. Prefer discrete ranking or waypoint-head adaptation.

### 1.4 Companion-specific data may remain a gap in released weights

Even perfect reuse leaves Parcel-private supervision:

- enrolled-owner track with Parcel’s identity posterior and approach vs follow modes;
- operator interventions and HOLD decisions on Parcel’s sidewalk courses;
- preference labels for pass-side, formation distance, and storefront courtesy;
- typed `TaskRequestV1` utterances for a tiny schema adapter (FunctionGemma-class), which is SFT/LoRA—not navigation RL.

Owning the **data contract + small adapter** is the durable FOR argument. Owning a from-scratch foundation model is not.

### 1.5 Hierarchy makes custom learning safer and cheaper

X-NavDP, NavOL, GR00T/COMPASS-style stacks, and Parcel’s own target architecture agree:

- low-level balance/gait stays with Sport (or a separate LowCmd program, never this pilot);
- learned component emits waypoints / ranked candidates;
- MPC or common planner tracks;
- independent monitor can veto.

Custom training inside that envelope may address the same bounded failure
classes as X-NavDP without granting end-to-end motor authority. Its gain is a
hypothesis, not an X-NavDP-scale promise.

---

## 2. Why from-scratch is the wrong FOR case (user doubt, affirmed)

From-scratch fails on evidence, not vibes:

1. **Compute.** DD-PPO-class image nav from scratch historically burned enormous interaction budgets. FLaRe and NavDP papers explicitly treat from-scratch RL as reward-heavy and slow relative to BC priors + fine-tune.
2. **Hardware.** RTX 5000 Ada (32 GB, 576 GB/s, no NVLink) is a plausible
   profiling target for single-GPU fine-tuning, LoRA, small critics, and replay,
   not proof those jobs fit. X-NavDP's released recipe uses 448 parallel
   environments across eight GPUs; selective NavDP fine-tuning reports one RTX
   6000 Ada. Neither establishes throughput or memory on Parcel's 32 GB card.
3. **Simulator honesty.** Parcel’s `Go2Env` is a stub (constants / incomplete dynamics). MetaUrban real-backend is `NotImplementedError`. Privileged city kinematics teach reward bugs. From-scratch on this substrate maximizes overfitting to lies.
4. **Product bottleneck.** NAV_INSTRUCT is 4%; separately, one untouched
   upstream Nav2 MPPI run solved one public BARN world where Parcel timed out.
   That single comparison motivates integration/executive work, not a general
   claim that Nav2 wins.
5. **Authority.** Low-level RL conflicts with Sport; online physical exploration around people is unacceptable.

**Correct reading of the doubt:** reject from-scratch; keep a path to **narrow owned adaptation**.

---

## 3. Hardware fit — RTX 5000 Ada 32 GB

| Workload | Fit on this card? | Notes |
| --- | --- | --- |
| Small trajectory ranker / preference critic (sensor features → K scores) | **Plausible; unprofiled** | Primary eventual pilot class; measure peak VRAM with Torch in a pinned image (active `.parcel` currently lacks `torch`) |
| MiniCPM-RobotTrack / CityWalker fine-tune or LoRA | **Plausible; unprofiled** | Compact policies; CityWalker ~214 M params / ~127 M trainable in paper; local optimizer-state, batch, and co-residency peaks are unmeasured |
| Selective NavDP-class FT (~12 M trainable, frozen backbone) | **Plausible** | Published on RTX 6000 Ada in ~3 h/round; expect longer wall-clock and careful batch/`G` tuning on 32 GB vs 48 GB class cards |
| Full 7B+ VLA full FT | **Poor / no** | OpenVLA docs cite ~27 GB+ even for constrained LoRA setups; co-resident sim+vision unsafe without measurement |
| X-NavDP released 448-environment online RL recipe | **No as published** | Uses eight GPUs; Parcel can at most evaluate a downscoped pilot if legal/sim gates pass |
| From-scratch foundation nav / locomotion | **No** | Out of budget and out of product strategy |

Operational constraints already audited: Gemma idle CUDA ~15 GB observed; InternVLA-class BF16 trees ~16–17 GB on disk before runtime; do not assume co-residency with training. Train in an isolated pinned environment, never by mutating the control runtime.

---

## 4. Ranked custom-training targets (FOR order)

| Rank | Target | Method | Why FOR | Containment |
| ---: | --- | --- | --- | --- |
| 1 | Bounded local trajectory **ranker / social critic** | BC/DAgger → optional shielded sim RL **or** conservative offline/preference RL | Conditional Parcel-residual hypothesis; bounded authority; device fit unprofiled | Choose among masked candidates only; abstain → HOLD |
| 2 | **Owner-follow waypoint head** adaptation (MiniCPM-RobotTrack-class) | IL / DAgger on Parcel identity+formation data | Closest product surface; public train scripts | Waypoints + TTL; no Sport bypass; identity remains Parcel’s |
| 3 | **CityWalker** teleop fine-tune as urban prior | SFT on recorded teleop data (paper used 6 h of data; compute undisclosed) | Checkpoint already local; urban sidewalk prior | Proposal only; original-asset license scope and training-data rights must clear |
| 4 | Typed **intent/schema** SFT (FunctionGemma-class) | LoRA/SFT | Cheap; unblocks language→`TaskRequestV1` | No motion authority |
| 5 | Embodiment post-train of a **reviewed** RGB-D local policy (CE-Nav / X-NavDP-class) | Online IL or GQRM-style RL in sim | Author-reported gains justify a later test, not an expected Parcel gain | Legal gate first; shadow only; downscope parallel envs to one Ada GPU |
| ✗ | From-scratch E2E / VLA / LowCmd locomotion | — | Not a Parcel FOR case under this hardware or safety model | Reject for this program |

---

## 5. Prerequisites (non-waivable)

Custom training becomes honest only after:

1. Exact-zero / fail-closed safety ordering; no open-loop LiDAR fallback.
2. Production pose from localization, not sim truth on the learning path.
3. Atomic pause/resume across executive task and motion channel.
4. Sensor-only observation ABI (no privileged polygons, actor IDs, future truth).
5. Versioned proposal serving contract: freshness, frames, masks, deadline, rollback, veto logging.
6. Frozen classical + open-weight baselines on the same contract; attributable residual documented.
7. Representative corpus: synced sensors, expert/intervention labels, independent terminals—for rankers—or reviewed utterance labels for schema SFT.
8. For online sim RL: reactive humans/delay/dropout/extrinsics, hard shields, held-out layouts; coverage analysis before GPU burn.
9. Legal clearance per artifact (X-NavDP / InternVLA / CityWalker original-asset scope especially).
10. Pinned Torch training image; measured peak VRAM/latency; 0 physical online RL.

Until then: **0 RL GPU-hours.**

---

## 6. Conditional GO triggers and stop-loss

**Flip NO-GO → CONDITIONAL GO for pilot #1 when all of the following hold:**

- sampler feasibility spike produces a stable K-candidate API (do not pretend stock MPPI internals are the contract);
- classical + frozen open models plateau on a repeated social/local ranking gap with predeclared effect size;
- BC/DAgger learning curve shows held-out lift without constraint violations;
- ranker p99 latency fits the controller budget.

**Pilot budget (future planning cap, not authorization now):**

- ≤ **120** single-GPU hours on the RTX 5000 Ada;
- ≤ **16 h** BC/DAgger, then ≤ **36 h** for three RL seeds only if justified, ≤ **48 h** ablations/baselines, remainder replay/latency;
- stop on absent effect, reward exploit, hard-constraint bypass, sensor-only collapse, or non-reproducing seeds.

**Never budgeted here:** foundation VLA pretraining, from-scratch PointNav, custom LowCmd locomotion, physical online RL.

---

## 7. GO / NO-GO card

```text
NOW
  custom RL/IL training .............. NO-GO
  from-scratch anything .............. NO-GO
  open-weight shadow + classical ...... GO (see RL2 / main decision)

AFTER PREREQUISITES + ATTRIBUTABLE RESIDUAL
  bounded ranker / social critic ..... CONDITIONAL GO (leading)
  MiniCPM / CityWalker IL adapt ...... CONDITIONAL GO (narrow)
  schema LoRA ........................ CONDITIONAL GO (cheap, parallel track)
  X-NavDP/CE-Nav post-train .......... CONDITIONAL GO (legal + downscoped sim)
  E2E language→motor / LowCmd RL ..... NO-GO (separate program or never)
```

**Confidence:** high on NO-GO-now and NO-GO-from-scratch; medium on the eventual ranker (depends on sampler spike and residual surviving the classical/open ladder).

---

## 8. Sources consulted (web + repo)

**Primary papers / project pages (2026-08-07 web search):**

- [X-NavDP](https://arxiv.org/html/2607.28560) / [HF card](https://huggingface.co/InternRobotics/X-NavDP)
- [NavOL](https://logosroboticsgroup.github.io/NavOL/) (ICML 2026)
- [Beyond Imitation: RL FT for diffusion nav (GRPO/NavDP)](https://doi.org/10.48550/arxiv.2603.12868)
- [FLaRe](https://arxiv.org/abs/2409.16578)
- [CityWalker](https://arxiv.org/html/2411.17820v3) / [fine_tune.py](https://github.com/ai4ce/CityWalker/blob/main/fine_tune.py)
- [MiniCPM-Robot](https://github.com/OpenBMB/MiniCPM-Robot)
- [HALO preference nav](https://doi.org/10.48550/arxiv.2508.01539)
- [Accessible VLA LoRA on ≤8–27 GB class GPUs](https://arxiv.org/html/2512.11921v1); [OpenVLA finetune notes](https://github.com/openvla/openvla)
- [NVIDIA RTX 5000 Ada product page](https://www.nvidia.com/en-us/products/workstations/rtx-5000/)
- [GR00T / COMPASS nav FT blog](https://developer.nvidia.com/blog/building-generalist-humanoid-capabilities-with-nvidia-isaac-gr00t-n1-6-using-a-sim-to-real-workflow/)

**Parcel inputs:** `MODEL_AND_RL_DECISION.md`, `README.md`, `SOURCE_LEDGER.md`, `RESEARCH_WORKSTREAM_APPENDIX.md` (RL1 brief), `src/parcel_robot/rl/env.py` (stub).

---

## 9. Independent note vs prior synthesis

This workstream agrees with the folder’s existing executive decision on **timing** (no training now) and **shape** (bounded ranker, not E2E). The FOR contribution is sharper on three points:

1. Custom training may become useful if a frozen companion-specific
   ranking/formation residual survives reuse; it is not assumed inevitable.
2. The user’s from-scratch doubt should be treated as **settled NO**, while preserving a **CONDITIONAL GO** for adaptation.
3. The RTX 5000 Ada is a **profile-first candidate** for the narrow pilot class
   and not a platform for reproducing published multi-GPU online RL farms or
   foundation pretraining.
