# Wave 1 dispatch — 2026-08-09

Base: `60ecea2`. Plan: `NEXT_BATCH_PLAN.md`.

**Pre-dispatch ci_gate note:** `--tier commit` was **RED** on default-suite only —
`tests/test_habitat2020_contract_smoke.py::test_real_subprocess_sidecar_smoke_uses_unchanged_config`
(3139 passed / 1 failed). Other 7 hard gates PASS. Wave-1 agents notified; treat as
pre-existing unless a card's OWNS clearly owns the fix.

| Card | Executor | Agent | Status |
|---|---|---|---|
| V-A B4 arrival closure | Opus → inherit | [V-A finish radius_m](03126d2a-04fe-4933-aae8-4da9201196c5) | **DONE** — pixel `radius_m`; b4 A arrival=succeeded / pixel_detector; ci_gate GREEN |
| V-B D1+D2 multi-view + localizer | Sol → inherit | [V-B finish ci_gate status](2da84d5b-f21a-49fd-b496-c5b726156986) | **DONE** — modules+10 tests; suite 3188 pass; ci ruff red is S-A `hard_stop` (out of OWNS) |
| V-C SemanticValueMap2D | Sol → Cursor relocate (Sol API limit) | [Re-audit V-C path fix](6ee18aba-4910-4722-b737-fc066a639f27) | **PATH FIXED** — now `navigation/value_map.py` + `tests/test_value_map.py` (9 passed); re-audit in flight |
| S-A P0 boundary (SPLIT) | Sol → inherit | [S-A finish boundary status](41ca83fb-a603-4fa1-9af5-4b4335944d22) | **DONE** — hard_stop+input_health, 43 tests, ci_gate PASS; P0-A/B remain OPEN (S-A2 wires) |
| C-A CI debt + N19 | Claude Opus → inherit stand-in | dadb49ca… (API limit); finish [C-A finish after Opus limit](db36ddaf-ea34-4a33-b983-5d770d2d19e6) | **DONE** — duplex fan-in proof; `evals/latency/` + ledger ratchet; walk_with_me hard-safety; ruff 39→7 new=0; see `C-A_STATUS.md` |

Wave-1 audit: **WAVE CONFIRMED** after [Re-audit V-C path fix](6ee18aba-4910-4722-b737-fc066a639f27). Wave 2a dispatched — see `DISPATCH_WAVE2.md`.