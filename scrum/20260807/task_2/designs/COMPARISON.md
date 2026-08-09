# Team review — three design proposals (2026-08-07)

**Status:** ready for review  
**Crown research:** [`../RESEARCH_THESIS.md`](../RESEARCH_THESIS.md)  
**Designs:** [D1](DESIGN_D1_CLASSICAL_COMPANION.md) · [D2](DESIGN_D2_SHADOW_PROPOSERS.md) · [D3](DESIGN_D3_SOCIAL_CITY.md)

These are **complementary layers**, not mutually exclusive forks. Recommended
composition: **D1 substrate → D3 week-A social residual → D2 shadow proposers**.

---

## One-line each

| ID | Thesis |
|---|---|
| **D1** | Exact-zero post-shaper + LiDAR HOLD + dimensionally valid safety envelope + atomic resume + ApproachOwner; **no learned motion**. |
| **D2** | MiniCPM → CityWalker as sandboxed SE(2) proposers behind TTL + classical + D1 veto; **never Sport**. |
| **D3** | N11 near-miss is commitment/arrival: mid-mission re-rank + dwell `inside` + formation→planner; OSM advisory only. |

---

## Comparison matrix

| Dimension | D1 Classical | D2 Shadow proposers | D3 Social city |
|---|---|---|---|
| **Primary job** | Close S0/S1 authority defects | Reuse open weights safely | Flip pedestrian e2e + social follow |
| **Learned motion** | Forbidden | Propose-only (out-of-process) | Forbidden for N11 flip |
| **Depends on** | Current stack | **D1 P0-A/B/C/H green** | **D1 P0-A/B/C/H plus real P1-B/P1-D witnesses** |
| **Key algorithms** | Hard-zero monitor; LiDAR HOLD; resume TX; ApproachOwner | Validate/TTL/latest-only; shadow vs active; GoalArbiter | `should_rerank_approach`; dwell inside; RampMemory seed-only |
| **Key interfaces** | Pose/Perception/TaskRevision/Safety/NavGoal V1 | `NavProposalV1` + sandbox IPC | `ApproachCommitment`, `FollowFormationGoalV1` |
| **Tick authority** | obs→plan→grid→brake→shaper→**veto**→HAL | same + proposal ingress before GoalArbiter | same + ~1 Hz re-rank near goal |
| **Eval exit** | Exact-zero pin; HOLD pin; resume xfail→pass | L0–L6 ladder; SHADOW default | `--runxfail` hard pass → remove xfail |
| **Phase fit** | **Phase 0 / ship-first** | Phase 2+ after D1 | **Phase 1** week-A after D1 |
| **Biggest risk** | Sport latency / Zs Zr UNVERIFIED | License / trust_remote_code / false A/B | Pressure to weaken person-stop |

---

## Shared ABI (freeze once for all three)

1. Post-shaper **hard-zero** hook (D1 owns; D2/D3 never bypass).
2. `PoseEstimateV1` / `PerceptionSnapshotV1` / dimensionally validated
   `SafetyEnvelope` health gates, with one explicit footprint/clearance convention.
3. `TaskRevisionV1` atomic with channel leases.
4. `NavGoalV1` / `NavFeedbackV1` (classical) and `NavProposalV1` (D2/OSM advisory).
5. Soft social costs never declare free space; person-stop / TTC stay hard.

---

## Recommended review decisions

Ask in the meeting:

1. **Approve D1 as Phase-0 mandatory?** (Ship order: P0-A/H → P0-C → P0-B → ApproachOwner → ABI freeze.)
2. **Approve D3 week-A only after P0-A/B/C/H and fresh P1-B/P1-D metric witnesses?** (Does not need models; targets N11.)
3. **Hold D2 ACTIVE until D1 exit + MiniCPM legal pin?** (SHADOW logging OK earlier.)
4. Any ABI field rename before code starts?

**Default recommendation if no objections:** implement D1 first; schedule D3 week-A next; keep D2 in SHADOW prototype lane.
