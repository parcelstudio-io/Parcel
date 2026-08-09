# N2 — Instruction VLN / VLA research (2024–2026)

**Workstream:** Opus matrix N2 (stand-in)  
**Date:** 2026-08-07  
**Scope:** InternVLA-N1, NaVILA, StreamVLN, Uni-NaVid/NaVid, InstructNav, plus
Qwen-RobotNav as architecture north star. Map every candidate onto Parcel's
**proposals-only SE(2) + TTL shadow** contract. No motor authority.

**Method:** primary papers/project pages, GitHub SPDX metadata via API, Hugging
Face model API tags/`cardData`, and Parcel target docs
(`TARGET_ARCHITECTURE.md`, `MODEL_AND_RL_DECISION.md`, `SOURCE_LEDGER.md`,
`docs/INSTRUCTION_NAV_HILLCLIMB.md`, `src/parcel_robot/instructnav/`).
Author-reported benchmark numbers are **not** Parcel results.

---

## 1. Verdict

Do **not** replace Parcel with an end-to-end VLN/VLA. The 2024–2026 literature
converges on the same shape Parcel already chose: slow language/vision
reasoning proposes mid-level goals; a fast classical (or Sport) loop executes
under independent safety. The best near-term use of these models is an
**out-of-process shadow proposer** that emits `NavProposalV1` /
`SE2Goal{source, pose|waypoints, frame, confidence, ttl_s, …}` and is discarded
on expiry, frame mismatch, or safety veto.

**Product blockers dominate capability.** Most strong VLN weights are
noncommercial, license-ambiguous on Hub metadata, or Llama/Vicuna-derivative.
None clear as the default physical controller. Phase 0 authority/lifecycle
fixes still precede any shadow A/B.

---

## 2. Parcel contract these models must obey

Existing seams (already in tree / target ABI):

| Contract | Role |
| --- | --- |
| `SE2Goal` / `ProposerBus` / `GoalArbiter` | Hot-swappable typed goals with TTL; arbiter drops expired / lethal goals |
| `NavProposalV1` (target) | Out-of-process: `relative_se2_waypoints[]`, observation/task IDs, `expires_at`, evidence handles, ABI hashes |
| Safety / Sport | Independent metric-geometry veto **after** every proposer; no VLA→Unitree path |
| Shadow mode | Latest-only buffer; compare offline then shadow; never author authoritative commands |

Adapter rules for every model below:

1. Translate native outputs (pixel goal, verb+distance, discrete Habitat action,
   value-map peak) → **bounded relative SE(2)** waypoints / single pose.
2. Clamp horizon (e.g. ≤1.5–3 m local), declare frame (`base_link`/`odom`/`map`),
   stamp observation IDs, set short TTL (0.3–2 s typical for reactive; longer
   only for slow System-2 goals that are revalidated each cycle).
3. Mark adapter confidence as **unknown/large** until Parcel-calibrated;
   never treat model logits as calibrated probability.
4. Run inference in a sandbox: pinned hash, no network, resource deadline,
   SBOM; timeout/OOM ≡ proposer unavailable → deterministic HOLD. Continue a
   classical path only for a previously grounded, fresh, authorized goal while
   all state/geometry gates remain healthy.

---

## 3. Candidate dossier

### 3.1 InternVLA-N1 (Shanghai AI Lab / InternRobotics) — 2025

| Item | Finding |
| --- | --- |
| Paper | *InternVLA-N1 / DualVLN* — dual-system VLN foundation; System 2 pixel/latent plans + System 1 agile execution; InternData-N1 (~50M egocentric images). arXiv [2512.08186](https://arxiv.org/abs/2512.08186) |
| Architecture fit | **Best conceptual match** to Parcel: slow S2 grounding, fast S1 trajectory, asynchronous rates, Go2/quadruped zero-shot claims |
| Weights | HF: `InternVLA-N1-System2`, `InternVLA-N1-DualVLN`, `InternVLA-N1-w-NavDP`, `InternVLA-N1-wo-dagger` (~8.3–8.4B BF16 params; ~16.6–16.8 GB weight files) |
| Code | [InternNav](https://github.com/InternRobotics/InternNav) — **MIT** (GitHub SPDX) |
| Weight license | Current DualVLN/System2 README badges declare **CC BY-NC-SA 4.0**, while Hub `cardData`/machine-readable artifact grants are absent. Do not infer broader rights from InternNav's MIT code or InternData's terms; block acquisition until legal clears each artifact and intended use |
| Data | InternData-N1 gated text vs YAML badge reportedly inconsistent (CC BY-NC-SA vs CC BY-SA) — separate review |
| Parcel mapping | Study **S2 first** as desktop instruction/pixel-goal → unproject → `SE2Goal`. Discard vendor System-1 / Sport replacement. A later, separately cleared DualVLN study may truncate trajectories to short relative SE(2) proposals |
| Product status | **Blocked** for product/motion. Isolated offline research needs explicit legal approval |
| Role | P4-C primary instruction shadow **after** license gate |

Author-reported DualVLN VLN-CE figures (not Parcel): R2R SR/SPL ~64.3/58.5,
RxR ~61.4/51.8. Authors claim S1 >30 Hz and long-horizon (>150 m) demos —
useful as existence proof for dual-rate design, not as Orin co-residency proof
alongside Gemma/perception.

### 3.2 NaVILA (UCSD / USC / NVIDIA) — RSS 2025

| Item | Finding |
| --- | --- |
| Paper | [arXiv 2412.04453](https://arxiv.org/abs/2412.04453) — VLA → mid-level language actions (`move forward 75cm`) → visual locomotion RL |
| Architecture fit | Strong for **legged** mid-level SE(2): language spatial verbs map cleanly to short goals; locomotion stays outside VLA (matches Sport retention) |
| Weights | HF `a8cheng/navila-llama3-8b-8f` (+ SigLIP-Llama3 pretrain). ~17 GB storage; API shows **no license field / no model card** |
| Code | [AnjieCheng/NaVILA](https://github.com/AnjieCheng/NaVILA) — **Apache-2.0** |
| Extra terms | Packaged **Llama 3** base → Meta Llama Community License still applies to derivative weights even if code is Apache |
| Runtime (author, RTX 4090) | FP16 ~594 ms / ~18.5 GB; W4A16 ~368 ms / ~8.6 GB |
| Parcel mapping | Regex/parse mid-level text → clamp distance/angle → `SE2Goal` TTL ≤2 s. Do **not** adopt NaVILA's locomotion policy; Sport + Parcel collision monitor remain writers |
| Product status | Code OK; **weights license undeclared on Hub** + Llama terms → acquisition blocked until legal + pin |
| Role | Secondary Go2-oriented instruction comparator (P4-C); NaVILA-Bench later for physics-aware quadruped VLN |

Correction vs older Parcel note (`INSTRUCTION_NAV_HILLCLIMB.md`): “Apache
weights verified on HF” is **not** current — Hub API has no license metadata
on the 8B checkpoint.

### 3.3 StreamVLN (InternRobotics) — ICRA 2026 / 2025

| Item | Finding |
| --- | --- |
| Paper | [arXiv 2507.05240](https://arxiv.org/abs/2507.05240) — SlowFast streaming Video-LLM VLN; sliding-window KV + 3D-aware token prune |
| Architecture fit | Excellent **pattern** for continuous RGB dialogue + bounded memory; documents realworld Go2 remote execution |
| Weights | HF `mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln` — **`license: cc-by-nc-sa-4.0`** in Hub `cardData` (~8.0B BF16 / ~16.1 GB) |
| Code | [InternRobotics/StreamVLN](https://github.com/InternRobotics/StreamVLN) — GitHub SPDX **null**; README declares **CC BY-NC-SA 4.0** |
| Parcel mapping | Steal D455/Go2 rig notes + async action-burst idea; if ever run, map action bursts → short SE(2) proposals with strict TTL. **Do not** productize |
| Product status | **Hard NC** — research desktop only |
| Role | Streaming-memory research comparator; not Orin default |

### 3.4 Uni-NaVid / NaVid (PKU / Galbot / BAAI) — RSS 2024 / 2025

| Item | Finding |
| --- | --- |
| NaVid | [arXiv 2402.15852](https://arxiv.org/abs/2402.15852) — video VLM, RGB-only next-step actions, no map/odom/depth |
| Uni-NaVid | [arXiv 2412.06224](https://arxiv.org/abs/2412.06224) — unified VLN / ObjectNav / EQA / tracking; online token merge ~5 Hz claim |
| Weights | HF `Jzzhang/Uni-NaVid` (~7B); Hub card warns **empty YAML metadata**; Vicuna-7B + EVA-CLIP upstream |
| Code | [jzhzhang/Uni-NaVid](https://github.com/jzhzhang/Uni-NaVid), [NaVid-VLN-CE](https://github.com/jzhzhang/NaVid-VLN-CE) — **MIT**; authors note rewrite to avoid some licenses |
| Parcel mapping | Discrete / continuous next actions → short SE(2); useful **multi-task + human-follow** research baseline offline on bags |
| Product status | Code MIT; **weight grant unclear** + Vicuna/Llama-family terms → blocked for product |
| Role | Offline generalist / follow comparator; not first shadow |

Author-reported Uni-NaVid VLN-CE Val (not Parcel): R2R SR/SPL 51.8/47.7;
RxR 66.4/44.5.

### 3.5 InstructNav (PKU) — CoRL 2024

| Item | Finding |
| --- | --- |
| Paper | [arXiv 2406.04882](https://arxiv.org/abs/2406.04882) — zero-shot DCoN + multi-sourced value maps; no nav training / no prebuilt map |
| Code | [LYX0501/InstructNav](https://github.com/LYX0501/InstructNav) — GitHub **`license: null`** (no SPDX) |
| Paper license | OpenReview lists paper under **CC BY 4.0** — that is **not** a code grant |
| Scrutiny | Follow-up work (*When Engineering Outruns Intelligence*, arXiv 2507.20021) argues frontier **geometry** may explain much of the gain; language as light heuristic |
| Parcel mapping | **Already internalized:** DCoN-like planning → value/frontier maps → SE(2) goals is Parcel's Grounder / SearchEntity / SemanticMemory path. Prefer Parcel's own MIT-shaped VLFM pattern over importing unlicensed InstructNav code |
| Product status | **Do not vendor** without license clarification; treat as architecture reference + cautionary ablation story |
| Role | Validates modular propose/dispose; reinforce geometry-first frontiers |

### 3.6 Qwen-RobotNav (Alibaba) — 2026 architecture north star

| Item | Finding |
| --- | --- |
| Paper | [arXiv 2606.18112](https://arxiv.org/abs/2606.18112) — Qwen3-VL + MLP head → **8× `(x,y,θ)` waypoints**; task-adaptive observation protocol |
| Weights | Official README: **currently no plan to release weights** |
| Parcel mapping | Closest public *interface* to `NavProposalV1.relative_se2_waypoints[]`. Copy the API shape (task mode + token budget + camera tags), not the closed weights |
| Role | Spec donor for P3-C proposer harness; not an installable candidate |

---

## 4. Cross-model comparison (Parcel-relevant)

| Model | Output native form | → Parcel SE(2) adapter | Hz class | Orin co-residency | License flag |
| --- | --- | --- | --- | --- | --- |
| InternVLA-N1 S2 | Pixel / latent goal | Unproject + clamp → pose | ~1–2 | Expected co-residency pressure; profile | README badge CC BY-NC-SA 4.0; machine-readable grant absent; InternData separately conflicts |
| InternVLA DualVLN / NavDP | Trajectory / RGB(-D) | Truncate to N relative SE2 | S1 high / S2 low | Desktop/Orin placement unprofiled | README badge CC BY-NC-SA 4.0; machine-readable grant absent; component terms separate |
| NaVILA | Verb + distance/angle text | Parse → pose/waypoints | ~1–3 | Expected pressure even quantized; profile | Code Apache; **weights undeclared** + Llama |
| StreamVLN | Streaming action tokens | Burst → short SE2 | Low-latency claim | Unspecified | **Hard NC** |
| Uni-NaVid | Next-step actions | Discrete/cont. → SE2 | ~5 claimed | Heavy (~15 GB class) | Code MIT; **weights unclear** + Vicuna |
| InstructNav | Value-map peak | Already = frontier→SE2 | LLM-slow | N/A (modular) | **No code license** |
| Qwen-RobotNav | 8× SE2 waypoints | Near-identity schema | Reactive | N/A | **Weights unreleased** |

Scores across VLN-CE / ObjectNav / real demos are **not** commensurable with
Parcel NAV_INSTRUCT (currently 1/25 = 4% on measured product path). Do not
rank product readiness by published SR.

---

## 5. Mapping diagram (proposals-only + TTL shadow)

```text
  Owner speech / instruction
            │
            ▼
  Parcel executive (TaskRequestV1 / revision / deadlines)
            │
            ├─ classical SearchEntity / Grounder / memory  ──┐
            │                                               │
            └─ optional VLN/VLA service (shadow) ───────────┤
                 │  InternVLA S2 | NaVILA | Uni-NaVid …     │
                 │  pin+hash, no net, killable deadline     │
                 ▼                                          │
              adapter → NavProposalV1 / SE2Goal             │
                 expires_at / ttl_s, frame, obs IDs         │
                                                            ▼
                                              GoalArbiter / ProposerBus
                                                   │ latest-only
                                                   ▼
                                        common planner (grid / Nav2)
                                                   │
                                                   ▼
                                      independent metric safety
                                                   │
                                                   ▼
                                            Unitree Sport
```

Shadow A/B: identical frozen episodes; log accept/reject/veto reasons; model
never wins authority by score alone.

---

## 6. License flags (acquisition matrix)

Legend: **GREEN** = code/pattern OK to study in-repo; **YELLOW** = research
possible after legal; **RED** = product/motion blocked.

| Artifact | Code | Weights / data | Flag | Parcel action |
| --- | --- | --- | --- | --- |
| InternNav | MIT | — | GREEN | May study dual-system plumbing |
| InternVLA-N1 checkpoints | — | README badge CC BY-NC-SA 4.0; machine-readable Hub grant absent | **RED** product / **YELLOW** offline | No acquisition without explicit legal approval; no physical use |
| InternData-N1 | — | NC vs SA inconsistency | **RED/YELLOW** | Block until clarified |
| NaVILA repo | Apache-2.0 | — | GREEN | OK |
| NaVILA HF 8B | — | **No Hub license** + Llama 3 | **RED/YELLOW** | Block acquisition until declared + Llama compliance |
| StreamVLN repo+weights | NC (README) | **cc-by-nc-sa-4.0** | **RED** | Pattern-only; no product weights |
| Uni-NaVid / NaVid-VLN-CE | MIT | Unclear Hub + Vicuna | **YELLOW** | Offline bags only if legal OK |
| InstructNav | **None** | N/A (API/LLM stack) | **RED** vendor | Reimplement ideas; don't import |
| Qwen-RobotNav | public report/repo | **Unreleased** | GREEN pattern | Schema donor only |
| VLFM (comparator) | MIT orchestration | Component models separate | GREEN pattern | Preferred open modular path |

**Policy reminder (task board):** restrictive/noncommercial terms block product
selection and physical motion; isolated offline research additionally requires
explicit legal approval. Stale TTL, failed deadline, or safety veto always
disqualifies the proposal.

---

## 7. Top 5 actions

1. **Freeze `NavProposalV1` + `SE2Goal` adapter tests (P0-F / P3-C)** before any
   weight download. Golden tests: schema reject, TTL expiry, frame mismatch,
   horizon clamp, safety veto → HOLD. Include a Qwen-RobotNav-*shaped*
   8-waypoint fixture with no real weights.

2. **Legal triage packet for InternVLA-N1 + NaVILA (blocking P4-C).** Capture
   per-artifact: Hub API license tag (present/absent), README SPDX, data card,
   base-model terms (Qwen2.5-VL / Llama 3). Decision: allow isolated desktop
   shadow / deny. Do not treat README badges as product clearance when YAML is
   empty.

3. **Prefer modular InstructNav/VLFM pattern on Parcel's own stack** for
   product instruction following (Grounder v2, SemanticMemory2D, SearchEntity
   frontiers) while large VLAs stay shadow-only. Treat InstructNav geometry
   scrutiny as a reason to keep frontiers geometry-first and language light.

4. **If legal clears one large model, start with InternVLA-N1 System 2 only**
   on desktop: RGB → pixel goal → unproject → short-TTL `SE2Goal`; DualVLN /
   NavDP / StreamVLN stay secondary. Never enable System-1 as Sport
   replacement. Profile peak VRAM vs Gemma/perception co-residency on the
   Ada 32 GB box before scheduling.

5. **NaVILA as second shadow only after weight license + Llama compliance**,
   with W4A16 path and mid-level text→SE2 parser. Use NaVILA-Bench later for
   quadruped physics instruction episodes — after P0 safety and P4-D embodiment
   harness — not as a shortcut around Parcel evaluation honesty.

---

## 8. Explicit non-actions

- Do not train a custom foundation VLN/VLA now.
- Do not import StreamVLN or InternVLA weights into a product image under NC.
- Do not grant any model Unitree velocity/joint authority.
- Do not cite VLN-CE SR as Parcel NAV_INSTRUCT success.
- Do not co-schedule 7–8B BF16 VLN with the full Orin NX product stack.

---

## 9. Sources (primary)

| Source | URL |
| --- | --- |
| InternVLA-N1 PDF | https://internrobotics.github.io/internvla-n1.github.io/static/pdfs/InternVLA_N1.pdf |
| DualVLN arXiv | https://arxiv.org/abs/2512.08186 |
| InternNav | https://github.com/InternRobotics/InternNav |
| InternVLA HF DualVLN | https://huggingface.co/InternRobotics/InternVLA-N1-DualVLN |
| NaVILA arXiv | https://arxiv.org/abs/2412.04453 |
| NaVILA code | https://github.com/AnjieCheng/NaVILA |
| NaVILA weights | https://huggingface.co/a8cheng/navila-llama3-8b-8f |
| StreamVLN arXiv | https://arxiv.org/abs/2507.05240 |
| StreamVLN code | https://github.com/InternRobotics/StreamVLN |
| StreamVLN weights | https://huggingface.co/mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln |
| Uni-NaVid arXiv | https://arxiv.org/abs/2412.06224 |
| Uni-NaVid code | https://github.com/jzhzhang/Uni-NaVid |
| NaVid arXiv | https://arxiv.org/abs/2402.15852 |
| InstructNav arXiv | https://arxiv.org/abs/2406.04882 |
| InstructNav scrutiny | https://arxiv.org/abs/2507.20021 |
| Qwen-RobotNav | https://github.com/QwenLM/Qwen-RobotNav · https://arxiv.org/abs/2606.18112 |

Hub/GitHub license snapshots verified 2026-08-07 via Hugging Face model API and
GitHub repo API (SPDX / `cardData.license` / tag presence as cited above).
