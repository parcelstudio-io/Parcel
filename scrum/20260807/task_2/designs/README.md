# Design proposals for team review — 2026-08-07

**Status:** READY FOR REVIEW  
**Inputs:** [`../RESEARCH_THESIS.md`](../RESEARCH_THESIS.md), `../research/*`  
**Constraint:** fail-closed; Sport owns gait; models propose only; no P0 regressions.

| ID | Working title | Differentiator | Status | Doc |
|---|---|---|---|---|
| D1 | Fail-closed classical companion | Zero learned motion; P0 hard-zero + LiDAR HOLD + safety units + atomic resume | ✅ | [DESIGN_D1…](DESIGN_D1_CLASSICAL_COMPANION.md) |
| D2 | Shadow-proposer hierarchy | MiniCPM → CityWalker SE2 proposers behind classical + safety | ✅ | [DESIGN_D2…](DESIGN_D2_SHADOW_PROPOSERS.md) |
| D3 | Social city companion | After D1 and real metric witnesses: N11 re-rank/terminal proof + formation→planner + OSM advisory | ✅ | [DESIGN_D3…](DESIGN_D3_SOCIAL_CITY.md) |

**Start here for the meeting:** [`COMPARISON.md`](COMPARISON.md)

Team review asks: which is Phase-0 mandatory, which is Phase-1, what shared ABI freezes first.
