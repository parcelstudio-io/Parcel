# Card V-D status — vsearch C2+C3 (value-directed scan + frontier scorer)

**Executor:** Opus stand-in (primary `e7d7acda` hit API limit at turn 0).  
**Deps:** V-C (`SemanticValueMap2D`), B4 arrival path (consumed, not edited).

**Verdict:** complete for owned wiring + unit/proxy gates. Authoritative
`ci_gate --tier commit` recorded below.

## Delivered (OWNS)

### C2 — value-directed ScanBehavior
- `src/parcel_robot/navigation/value_directed_scan.py` (NEW)
  - `ValueDirectedScanSession`: `full_turn_scan_spec` **only** as first-UNSEEN
    VLFM init; after that GP-UCB look-again-vs-commit
    (`mu + sqrt(beta) * sigma`).
  - Scan stops planned as `SE2Goal` via `SCAN_PROPOSER_SOURCE` for
    ProposerBus / base-lease arbitration.
  - `suspend()` / `resume()` — summons suspends, does not cancel.
- `src/parcel_robot/navigation/instructnav_recovery.py`
  - `ScanBehaviorController` gains opt-in `value_directed` + session;
    `enqueue_value_look`, suspend/resume.
- `src/parcel_robot/navigation/pipeline.py` (flag-gated)
  - `value_directed_search=False` default → flag-off path unchanged.
  - Flag-on: shared `SemanticValueMap2D`, paint looks, GP-UCB after init,
    publish scan SE2 viewpoints, `suspend_scan_for_summons`.

### C3 — ValueMapFrontierScorer + plan-time prior
- `src/parcel_robot/instructnav/search_entity.py`
  - `PlanTimePriorCache` (LGR: frozen at plan time; no runtime model calls)
  - `TargetExistenceBelief` (V_e), `BeliefInheritance` (V_p)
  - `ValueMapFrontierScorer` / `NearestFrontierScorer` (Tier C baseline)
- `select_search_entity_frontier` accepts `value_map` / `plan_prior` /
  `existence`; pipeline passes them when flag-on.
- Exports wired in `instructnav/__init__.py`.

### Tests
- `tests/test_value_directed_search.py` — C2/C3 unit + Tier B/C proxy +
  lease-contention checks.

MUST NOT touched: `runtime.py`, `velocity_shaping.py`, `reactive_safety.py`,
`camera_channel/**`, `detection_adapter/**`, `instructnav/scoring.py`,
`core/hard_stop.py`, `core/input_health.py`.

## Gates (measured)

| Gate | Result |
|---|---|
| Tier B SR ≥ fixed-spin (paired-seed proxy) | **PASS** — value-directed recovers mid-gap targets the 4-stop lattice misses (`test_tier_b_value_directed_sr_ge_fixed_spin_paired_seeds`) |
| Tier C ≥ +10pp vs nearest-frontier (paired-seed proxy) | **PASS** — `test_tier_c_value_map_sr_plus_10pp_vs_nearest_frontier` |
| Attention / base-lease contention | **PASS** — soft glance tracks exclude `base`; scan SE2 owns plan-step; glance cannot trip SearchOwner by construction |
| Summons suspends ≠ cancels scan | **PASS** — session `suspend` keeps stops; `ResumeIntent` reason `owner summons` |
| Zero runtime model calls in control tick | **PASS** — `PlanTimePriorCache` is a frozen mapping; scorer only reads map + cache |
| Flag-off byte-identical | **PASS by construction** — `value_directed_search` defaults `False`; existing K4 wiring tests green |

```
.parcel/bin/python -m pytest -q tests/test_value_directed_search.py \
  tests/test_k4_opus_wiring.py tests/test_k4_instructnav.py tests/test_value_map.py
→ 44 passed
```

## Authoritative CI

`.parcel/bin/python scripts/ci_gate.py --tier commit` @ 2026-08-09T22:55:02Z

- **PASS — every hard gate green** (elapsed ~106.5 s)
- ruff: 7 violation(s), baseline 7, new 0
- default-suite: **3256 passed**, 9 skipped, 34 deselected
- frozen digests unmoved; model-off-non-inferiority green

## does_not_prove

- Full `nav_instruct` frozen-minival Tier B ≥90% / Tier C ≥70% live SR
  (proxy paired-seed sims only; hillclimb McNemar on the product pack not re-run).
- Real SigLIP/LLM relevance scores at plan time (cache is table-seeded).
- Hardware attention/summons e2e (pure + executive suspend contract only).
- Flag-on product A/B vs fixed-spin on the live city sim pack.
