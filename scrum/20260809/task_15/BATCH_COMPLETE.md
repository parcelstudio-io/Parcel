# Batch complete — task_15 NEXT_BATCH_PLAN (2026-08-09)

**Wave-1:** CONFIRMED (`AUDIT_WAVE1.md` + V-C re-audit)  
**Wave-2:** CONFIRMED (`AUDIT_WAVE2.md` via [Fable Wave2 full audit](881661d9-8597-4675-9cc9-a1e6129c6c0b))  
**ci_gate:** PASS @ audit (3283 passed, ruff new=0)

## Headline landings

| Area | Outcome |
|---|---|
| Camera arrival (V-A) | Pixel path arrives (`candidate_source=pixel_detector`) |
| Multi-view + localizer (V-B) | Pure D1/D2 modules |
| Value map + directed scan (V-C/V-D) | `navigation/value_map.py` + C2/C3 flag-gated |
| Lock-on + chance-K0 (V-E) | Detection-triggered SE2Goal; P≥0.9 |
| P0-A/B (S-A → S-A2) | Closed on live dispatch path |
| Proximity (S-B) | Clearance convention + P0-H + mixed-lethal |
| CI/N19 (C-A) | Acoustic marks + latency ledger |
| Counterfactual (C-B) | Pure log + GoalArbiter wire |
| PERSONAL_CONVO (M-A) | PC-4 judge + live summarizer measure |

## Non-blocking follow-ups (from Wave-2 audit)

- yaml safety inject retune (person_stop still injected at 1.0 in places)
- deferred P0-C `_accept_plan` nav-plan filter
- live nav_instruct SR under flag-on (not just proxy cells)

Uncommitted tree — commit/push only on owner request.