# RL2 — Strongest case for open-weight reuse

**Workstream:** RL2 (independent of RL1)  
**Checked:** 2026-08-07 via official repos, Hugging Face cards, papers, and
WebSearch cross-checks against `SOURCE_LEDGER.md` / `MODEL_AND_RL_DECISION.md`.  
**No models were downloaded or installed for this note.**

## Verdict

**Reuse released waypoint/local-policy proposers behind Parcel's classical
planner and independent safety lane. Allocate zero custom RL / VLA training
GPU-hours now.**

The cheapest path that can still move measured product metrics is:

1. Repair P0 authority/state/lifecycle so model A/B is interpretable.
2. Acquire only artifacts whose full code/weight/backbone/data/asset terms have
   cleared review; pin/hash them and sandbox custom load code
   (`trust_remote_code`).
3. Run offline replay → shadow proposals with TTL, frame IDs, and deterministic
   fallback. Never grant Sport/HAL authority to a learned process.
4. Train only after a repeated, attributable residual survives Nav2 + these
   frozen open baselines on a frozen evaluation contract.

This is the affirmative reuse case: released models expose candidate interfaces
for owner-follow waypoints (MiniCPM), urban XY priors (CityWalker), Go2 RGB-D
local trajectories (X-NavDP/CE-Nav, terms and dependencies pending), and
instruction grounding (InternVLA / NaVILA as desktop research). They have not
yet been shown to cover Parcel's product needs, and none justifies replacing
Unitree Sport or skipping classical control.

## Ranked acquisition queue

Acquisition means legal clearance + pinned revision/hash + reviewed remote code
+ isolated serving image. It does **not** mean wire-to-motion or product
selection.

| Rank | Artifact | Acquire? | Why this rank | Shadow role |
| ---: | --- | --- | --- | --- |
| 1 | **MiniCPM-RobotTrack** | **Hold for transitive terms/custom-code review; first candidate** | Apache-2.0 core code/weights; official Go2 EDU/Orin dry-run path; emits eight `(x,y,yaw)` waypoints; ~0.9B / author ~180 ms on Go2; DINOv3 and deployment dependencies are separate | Owner-follow / target-track `NavProposalV1` (P4-A) |
| 2 | **CityWalker** | **Hold for original-asset license/loader review** | Official v1.0/local byte identity verified; ~0.2B / 1,752,028,242 bytes already on disk; original artifact scans `NOASSERTION`; HF conversion is separately Apache and executes custom code | Urban point-goal / traversability prior (P4-B) |
| 3 | **X-NavDP** | **Hold — legal review before any download** | Strong Go2 RGB-D local-trajectory/recovery candidate, but HF weights lack license metadata; parent NavDP README says CC BY-NC-SA; only `baselines/x-navdp` subtree declares MIT; Isaac assets separate | Local detour/recovery proposals after clearance (P4-B) |
| 4 | **InternVLA-N1** | **Hold — research-only if counsel clears intended use** | Strong dual-system instruction→pixel-goal / trajectory research; InternNav code MIT; README badges declare CC BY-NC-SA 4.0 while machine-readable Hub metadata/artifact grants are absent; InternData separately has a gated NC/SA metadata conflict | Desktop instruction-nav shadow after legal OK (P4-C); **not** product |
| 5 | **NaVILA** | **Defer — secondary comparator** | Apache-2.0 code and real Go2 demos, but HF `navila-llama3-8b-8f` has **no model card / no declared weight license**; Llama 3 community terms apply to the backbone; ~8B / author 18.5 GB FP16 on 4090; mid-level verb+distance≠ Parcel SE(2) waypoint ABI | Instruction mid-level action research only (P4-C), after license review |

**Do not acquire now for training:** any InternData-N1 dump, Isaac scene packs
for custom RL, or “retrain MiniCPM/CityWalker from scratch” corpora. Reuse
inference first.

## License matrix (code ≠ weights ≠ data ≠ assets)

| Candidate | Code | Weights (observed) | Blocking third-party | Product motion? |
| --- | --- | --- | --- | --- |
| MiniCPM-RobotTrack | Apache-2.0 ([OpenBMB/MiniCPM-Robot](https://github.com/OpenBMB/MiniCPM-Robot)) | Apache-2.0 ([HF card](https://huggingface.co/openbmb/MiniCPM-RobotTrack)) | Gated DINOv3 / SigLIP / TRT / Unitree SDK / EVT scenes — review `THIRD_PARTY_NOTICES` | Eligible for **shadow** after sandbox; not safety authority |
| CityWalker | Apache-2.0 ([ai4ce/CityWalker](https://github.com/ai4ce/CityWalker)) | HF port Apache-2.0 ([ai4ce/citywalker](https://huggingface.co/ai4ce/citywalker)); local GitHub v1.0 asset byte identity verified, but it scans `NOASSERTION` | DINOv2 bundled in HF port; web-video training provenance | Shadow only after original-asset license-scope and loader review; not language/identity authority |
| X-NavDP | MIT file in self-contained subtree; parent [NavDP](https://github.com/InternRobotics/NavDP) README CC BY-NC-SA 4.0, no top-level LICENSE | [InternRobotics/X-NavDP](https://huggingface.co/InternRobotics/X-NavDP) card documents MIT for **code**, no clear weight SPDX | Isaac Sim/Lab, robot USDs, Scene-N1 | **Blocked** until counsel maps code vs weights vs assets |
| InternVLA-N1 | InternNav MIT | System 2/DualVLN README badges declare CC BY-NC-SA 4.0; machine-readable Hub metadata/artifact grant is absent | InternData-N1 gated CC BY-NC-SA (text) vs CC BY-SA (YAML conflict); Qwen2.5-VL lineage | **Blocked**; isolated offline use still needs explicit legal approval |
| NaVILA | Apache-2.0 ([AnjieCheng/NaVILA](https://github.com/AnjieCheng/NaVILA)) | [a8cheng/navila-llama3-8b-8f](https://huggingface.co/a8cheng/navila-llama3-8b-8f): no card, no declared license | Meta Llama 3 Community License on backbone; Habitat/Isaac eval assets | **Blocked** until weight grant + Llama compliance documented |

**Rule:** a README badge, a code LICENSE, and a Hugging Face `license:` field are
three different claims. Recheck all three plus SBOM at pin time. Restrictive or
noncommercial weight/data terms block product selection and physical motion;
isolated research still needs explicit legal approval.

## Go2 fit

| Candidate | Embodiment evidence | Sensor / I/O fit for Parcel | Onboard realism |
| --- | --- | --- | --- |
| MiniCPM-RobotTrack | Official Go2 EDU + Orin NX 16GB deployment; default **dry-run**; live control requires interactive `MOVE` | RGB (Go2 cam or D435i RGB only) → language-conditioned track → 8 future `(x,y,yaw)` waypoints | Author: stable 5+ FPS / ~180 ms e2e on native Go2 stack. Validated JetPack/TRT pins. Air/Pro/Orin Nano out of support scope. |
| CityWalker | Paper fine-tune real tests on **Go1**, not Parcel Go2 zero-shot | 5 RGB + relative pose history + target → 5 XY waypoints + arrive logit; **no yaw** | Compact (~0.2B). Orin latency/memory **unmeasured**. Good desktop/urban prior. |
| X-NavDP | Explicit Unitree Go2 in sim + real hard-case sets; quadruped server configs | RGB-D local diffusion trajectories; embodiment modulation; point-goal / recovery behaviors | Author: sim SR 61.20%→84.28%; Go2 SR/SPL 79.85/74.04 (author bench); real hard-case ~60–80% on small sets. Orin/VRAM unknown. |
| InternVLA-N1 | Authors demonstrate Go2 deployment; System 1 claimed >30 Hz | S2: instruction + egocentric RGB → pixel goals / latent plans; S1: NavDP* or DualVLN trajectories | ~8B System 2 → desktop/service, not Orin co-resident default. DualVLN R2R/RxR author scores are not Parcel results. |
| NaVILA | Real Go2 / H1 / T1; mid-level language actions + separate locomotion | 8-frame RGB + instruction → discrete verb + continuous distance/angle (often mapped to velocity/duration). Authors' own vision locomotion policy is a **different** LowCmd-class program than Parcel's Sport retention. | Author RTX 4090: 594.58 ms / 18.5 GB FP16; 367.80 ms / 8.6 GB W4A16. Joint Gemma/perception co-residency is unprofiled and likely resource-pressured. |

**Fit summary:** MiniCPM has the closest combination of Apache core artifacts,
Go2 documentation, and SE(2)-like waypoints, but its full deployment still has
gated/transitive terms. CityWalker is the only already-on-disk urban prior with
Apache upstream/conversion claims; the local bytes match official v1.0, while
original-asset license scope remains unresolved. CE-Nav and X-NavDP belong in
the same local-policy screen after
their distinct legal/dependency gates. InternVLA/NaVILA are instruction
research brains, not Orin default controllers.

## Shadow-mode contract (all five)

Parcel shadow means the model process may **propose**; it may never **command**.

```text
sensors → frozen episode / live observation ABI
       → out-of-process model sandbox (no net, no creds, cgroup/VRAM caps)
       → NavProposalV1 | MidLevelActionV1  (TTL, frame, task/revision IDs)
       → validator (kinematic, frame, freshness, identity gates)
       → classical planner / formation goal  (authoritative path)
       → independent metric-geometry safety  (final zero)
       → Unitree Sport
```

Hard rules for every candidate:

1. **Latest-only proposals.** Stale TTL, OOM, deadline miss, invalid frame, or
   validator reject → deterministic HOLD; log veto reason. Classical
   continuation is allowed only for a prior grounded/fresh/authorized goal
   while every state and geometry gate remains healthy.
2. **No identity or free-space authority.** MiniCPM may propose track waypoints
   only after Parcel's enrolled-owner posterior admits a target; RGB semantics
   never declare free space.
3. **Sandbox `trust_remote_code`.** MiniCPM and CityWalker HF loaders both use
   it. Pin reviewed code; never import into the control process.
4. **Role-matched frozen episodes.** Owner-follow suite for MiniCPM; point-goal /
   detour for CityWalker/X-NavDP; language-nav for InternVLA/NaVILA. Do not
   compare R2R SR to EVT CR as if they share a denominator.
5. **Co-residency measured.** Desktop has RTX 5000 Ada 32 GB; active `.parcel`
   still lacks Torch. Build a pinned inference image. Do not assume Gemma + 8B
   VLA + sim + LiDAR stack fit simultaneously.
6. **Physical motion stays supervised.** MiniCPM's own docs warn the model may
   predict forward motion when no person is visible. Dry-run/shadow first;
   hardware E-stop independent of software.

### Per-candidate shadow adapters

| Candidate | Adapter output | Must **not** become |
| --- | --- | --- |
| MiniCPM | Relative SE(2) waypoints + confidence + observation IDs | Owner ID, presence truth, Sport velocity |
| CityWalker | Relative XY polyline + arrive probability; derive yaw from segment if needed | Language goal, social cost, curb/road legality |
| X-NavDP | Short-horizon RGB-D trajectory samples + critic scores (if exposed) | Collision certificate, LowCmd joints |
| InternVLA-N1 | Pixel goal / latent plan (S2) and/or trajectory samples (S1) as proposals | Task success witness, road-entry clearance |
| NaVILA | Parsed mid-level `{verb, distance, angle}` → candidate SE(2) step proposal | Direct twist to HAL; replacement for Sport |

## Candidate dossiers

### 1. MiniCPM-RobotTrack — review first

- **Why reuse beats training:** product-shaped owner/target following on the
  actual dog platform, Apache core weights, dry-run-first deployment, waypoint
  interface that matches Parcel's proposer ABI. The complete deployment still
  requires transitive license and custom-code review.
- **Author metrics (not Parcel):** EVT STT SR/TR/CR 84.1 / 89.8 / 3.0; DT CR
  13.6; AT CR 9.0 — nonzero collisions even in the authors' bench.
- **Acquisition steps:** clear DINOv3 and SigLIP terms for any evaluation/live
  vision path; separately review TensorRT only for the TRT deployment backend;
  snapshot `openbmb/MiniCPM-RobotTrack`; hash `model.safetensors*`; vendor reviewed
  modeling code; run offline feature→waypoint tests before any robot process.
- **Promotion gate:** frozen owner/distractor/occlusion suite with no identity
  swap, no safety veto regression, and p99 latency within budget vs formation
  baseline.

### 2. CityWalker — pin what we already have

- **Why reuse beats training:** urban walking/driving prior from ~2000 h web
  video; small checkpoint; XY waypoints are a natural cost/prior for
  role-specific urban point-goal episodes. It does not explain or directly
  repair Parcel's 4% aggregate NAV_INSTRUCT result.
- **Limits:** no language, no yaw, no owner identity, no social rules. Go1
  fine-tune 77.3% author real-world success ≠ Go2 zero-shot.
- **Acquisition steps:** record that local `CityWalker_2000hr.ckpt` is
  byte-identical to official v1.0 (1,752,028,242 bytes; SHA-256
  `a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`).
  Separately clear the original asset's license scope (`NOASSERTION`) or pin a
  legally approved HF conversion; sandbox custom modeling code either way.
- **Promotion gate:** paired urban point-goal / sidewalk approach shadows vs
  grid/Nav2; no collision or latency regression.

### 3. X-NavDP — local-policy peer with an unclear grant

- **Why it belongs on the shortlist:** RL-post-trained NavDP specifically for
  dead-end escape, long-obstacle detour, and cross-embodiment (Dingo / Go2 /
  G1). Matches Parcel's eventual “bounded trajectory proposer” hypothesis
  without Parcel training.
- **Why not acquire today:** MIT subtree claim does not automatically license
  HF checkpoints; parent NavDP NC-SA README conflicts; Isaac/NVIDIA terms.
- **If cleared:** shadow as RGB-D local proposal service behind the same
  validator used for CityWalker; keep CE-Nav (MIT repo + Go2 ckpt, separate
  card) as the legally cleaner local-policy screen when its artifact terms pass.

### 4. InternVLA-N1 — desktop instruction research, NC badge plus metadata gap

- **Why reuse beats training a Parcel VLA:** dual-system grounding already
  exists; authors report DualVLN R2R SR/SPL 64.3/58.5 and RxR 61.4/51.8;
  System 1 path reuses NavDP-class controllers Parcel may already evaluate.
- **Why blocked for product:** current README badges declare CC BY-NC-SA 4.0,
  while machine-readable Hub metadata/artifact grants are absent; InternData
  separately has conflicting NC/SA metadata; ~8B S2 is a service candidate,
  not an assumed Orin-resident brain.
- **If counsel approves isolated offline study:** shadow S2 pixel goals into
  typed semantic goals; never authorize motion without an explicit artifact-
  level grant for the intended use.

### 5. NaVILA — Go2 story, wrong ABI and murky weights

- **Why it is interesting:** RSS'25 legged VLN; real Go2 demos; mid-level
  language actions that can sit above Sport the way Parcel wants models above
  the planner.
- **Why ranked last for acquisition:** undeclared HF weight license + Llama 3
  terms; large VRAM; action is verb/distance/angle rather than metric waypoint
  polyline; authors' vision locomotion policy is out of scope while Parcel
  retains Sport.
- **Use:** after legal review, optional P4-C comparator that converts mid-level
  actions into short-TTL SE(2) proposals. Do not adopt their LowCmd locomotion
  stack.

## No-train-now (RL2 framing)

RL1 asks “when would training help?” RL2 asks “what can we get without it?”
Answer: enough adjacent roles exist to justify reuse-first experiments, but the
models are unwired and cannot repair P0 defects. Their value must be measured
on role-specific product episodes rather than assumed.

### Do not train now because reuse already supplies the roles

| Product gap | Open reuse that should be tried first |
| --- | --- |
| Owner follow around people | MiniCPM waypoints + Parcel identity + common planner |
| Urban sidewalk / lamppost approach prior | CityWalker XY prior + semantic memory + Nav2 |
| Local dead-end / detour | X-NavDP or CE-Nav after terms; else Nav2 MPPI |
| Language → visual goal | InternVLA S2 / NaVILA mid-level only after artifact-specific research approval |
| Gait / balance | Unitree Sport (retain) |
| Hard stop / LiDAR freshness | Deterministic Parcel safety (P0) — not learnable here |

### Training remains blocked until reuse fails a frozen residual

A custom learning pilot is rational only when **all** of the following hold:

1. P0-A..E and P0-F ABI frozen; exact-zero safety and fail-closed state proven.
2. Nav2 RPP/MPPI and every license-eligible open proposer above have been A/B'd
   against the appropriate role-matched baseline on frozen episodes with
   complete telemetry and a declared sensor contract.
3. The residual failure is **model-addressable** (e.g. social ranking among
   hard-admissible trajectories), not authority/lifecycle/oracle bugs.
4. A representative sensor-only dataset or shielded sim exists for that narrow
   component (not `Go2Env` stub kinematics).
5. Serving contract exists: observation ABI, deadline, rollback, veto logging.
6. Legal terms for base weights/data allow the intended adaptation.

Leading eventual hypothesis if those gates pass: **bounded trajectory
ranker/social critic** over classical/open samples — not end-to-end VLA, not
online physical RL, not LowCmd locomotion.

### Explicit rejects for this cycle

- End-to-end language/camera→motor VLA training.
- Online RL on hardware or people.
- Retraining MiniCPM/CityWalker/InternVLA/NaVILA from scratch “to own the
  weights.”
- Any GPU hours spent before Torch-capable pinned inference/training images
  and frozen eval harnesses exist.

## Build-versus-reuse decision table

| Approach | RL2 decision | Evidence that would reverse it |
| --- | --- | --- |
| Classical Nav2 + frozen MiniCPM/CityWalker shadows | **Do next** | Measured residual after paired shadows with clean safety |
| CE-Nav local proposals | **Next after review** | Confirm checkpoint scope plus transitive dependency and legacy Isaac/Orbit asset terms; training release completeness is separate |
| X-NavDP local proposals | **Next only after legal** | Complete code, weight, backbone, dependency, data, and asset grants for the intended use |
| InternVLA / NaVILA instruction shadows | **Research only if cleared** | Explicit artifact-level intended-use grant plus upstream/base-model compliance |
| SFT/LoRA on typed `TaskRequestV1` | Later | Parser error dominates after executive fixes |
| Bounded trajectory ranker | Later leading hypothesis | Sampler + residual after open local policies |
| Custom E2E nav / physical RL | **No** | No near-term reverse trigger |

## Sources rechecked (2026-08-07)

- [openbmb/MiniCPM-RobotTrack](https://huggingface.co/openbmb/MiniCPM-RobotTrack),
  [OpenBMB/MiniCPM-Robot](https://github.com/OpenBMB/MiniCPM-Robot),
  [GO2_DEPLOYMENT.md](https://github.com/OpenBMB/MiniCPM-Robot/blob/main/MiniCPM-RobotTrack/docs/GO2_DEPLOYMENT.md)
- [InternRobotics/InternNav](https://github.com/InternRobotics/InternNav),
  [InternVLA-N1-System2](https://huggingface.co/InternRobotics/InternVLA-N1-System2),
  [InternVLA-N1-w-NavDP](https://huggingface.co/InternRobotics/InternVLA-N1-w-NavDP),
  DualVLN paper [arXiv:2512.08186](https://arxiv.org/abs/2512.08186)
- [InternRobotics/X-NavDP](https://huggingface.co/InternRobotics/X-NavDP),
  [NavDP](https://github.com/InternRobotics/NavDP),
  X-NavDP paper [arXiv:2607.28560](https://arxiv.org/abs/2607.28560)
- [ai4ce/CityWalker](https://github.com/ai4ce/CityWalker),
  [ai4ce/citywalker](https://huggingface.co/ai4ce/citywalker)
- [AnjieCheng/NaVILA](https://github.com/AnjieCheng/NaVILA),
  [a8cheng/navila-llama3-8b-8f](https://huggingface.co/a8cheng/navila-llama3-8b-8f),
  [navila-bot.github.io](https://navila-bot.github.io/),
  NaVILA paper [arXiv:2412.04453](https://arxiv.org/abs/2412.04453)

External scores remain author-reported. Parcel NAV_INSTRUCT 1/25 (4%) success
is the only product-path success rate this workstream treats as measured.

## One-line board update

**RL2: reuse wins — review MiniCPM's full deployment stack, then establish a
cleared CityWalker pin; screen CE-Nav/X-NavDP under their distinct legal gates;
train nothing until role-matched shadows fail a frozen residual.**
