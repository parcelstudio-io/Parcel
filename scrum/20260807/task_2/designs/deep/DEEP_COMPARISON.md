# Deep designs — team comparison (2026-08-07)

**Status:** READY FOR REVIEW (depth-gated)  
**v0 shallow archive:** `../DESIGN_D*.md` (~700–840 lines) — superseded for review  
**Deep corpus:** 5,177 lines across three designs

| Design | Doc | Lines | Passes | Agent |
|---|---|---:|---|---|
| **D1** Classical companion | [DEEP_D1…](DEEP_D1_CLASSICAL_COMPANION.md) | 1693 | 4 | research workstream D1 |
| **D2** Shadow proposers | [DEEP_D2…](DEEP_D2_SHADOW_PROPOSERS.md) | 1776 | 4 | research workstream D2 |
| **D3** Social city | [DEEP_D3…](DEEP_D3_SOCIAL_CITY.md) | 1708 | 4 | research workstream D3 |

---

## Depth gate (all passed)

| Requirement | D1 | D2 | D3 |
|---|---|---|---|
| ≥1,200 dense lines | 1689 | 1747 | 1683 |
| ≥3 passes + pass log | 4 | 4 | 4 |
| ≥20 file:line cites | ≥35 | 24 | 30+ |
| Worked scenario(s) | yes (stop + come/resume) | yes (occlusion+distractor) | yes (occupied sidewalk) |
| Why-it-works + falsifiers | yes | 15 mechanisms | GSNI + adversarial |
| Complete motion/lifecycle pseudocode | yes | yes | yes |

---

## One-line theses

| ID | Thesis |
|---|---|
| **D1** | Exact-zero post-shaper (measured residual **0.48 m/s** on stop tick) + LiDAR HOLD + atomic resume + ApproachOwner; **no learned motion**. |
| **D2** | MiniCPM → CityWalker as sandboxed SE(2) proposers; TTL; `NavProposalV1`; `grid_v1` executes; D1 veto; **SHADOW default; never Sport**. |
| **D3** | N11 is **commitment + arrival**, not a missing brake: mid-mission re-rank + dwell `inside` + formation→planner; OSM advisory only. |

---

## Composition (not forks)

```text
Phase 0 ──► D1 substrate (hard-zero, HOLD, safety units, resume, ApproachOwner, ABI freeze)
Phase 1 ──► real P1-B/P1-D witnesses → D3 week-A (re-rank + terminal witness) → flip pedestrian xfail
Phase 2+ ─► D2 SHADOW → gated ACTIVE after D1 exit + MiniCPM legal pin
```

Shared ABI freeze once: post-shaper hard-zero hook, Pose/Perception/Safety V1,
TaskRevision atomicity, NavGoalV1 + NavProposalV1.

---

## Strongest “why it may work” claim per design

| Design | Justification spine |
|---|---|
| **D1** | Residual is a **composition bug** (gate zeros, shaper slews). Snap-to-zero after veto is local, testable, matches Nav2 collision-monitor *ordering*. Synthetic shaper traces show nonzero post-gate targets; only a same-dispatch HAL pin and commissioned stopping tests establish the fix. |
| **D2** | Dual-system VLN precedent + Parcel already forbids language→motor. Open weights already emit waypoints (MiniCPM Go2 path; CityWalker urban XY). Failure defaults to HOLD; an existing classical goal continues only through unchanged authorization/freshness/geometry gates. |
| **D3** | Historical N11 evidence suggests a contested commitment; re-rank + terminal witnesses don't touch hard gates. `traffic_aware` empty-tracks identity is preserved. Falsifiable only after fresh metric producers exist and a `--runxfail` hard pass records clearance, agent-stop/settled feedback, and mechanism attribution. |

---

## Review asks

1. Approve **D1** as Phase-0 mandatory (including P0-H dimensional safety-envelope repair)?
2. Approve **D3 week-A** only after P0-A/B/C/H and real P1-B/P1-D witnesses (no models required)?
3. Keep **D2** SHADOW-only until D1 exit + license pin?
4. Any ABI field rename before code starts?

**Default recommendation:** D1 → D3 week-A → D2 shadow.
