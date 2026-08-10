# Card V-C status — SemanticValueMap2D

**Verdict:** path-corrected after Wave-1 RETURN (audit § V-C).

## Delivered (OWNS paths)

- `src/parcel_robot/navigation/value_map.py` — `SemanticValueMap2D` / `ViewCone` /
  `CellRegion`; frozen surface `write(cone,value,conf)`, `read(cell)->(value,conf)`,
  `unknown_fraction(region)`.
- `tests/test_value_map.py` — 9 unit tests (cone/fusion/unknown math).

## Removed (wrong path from first landing)

- `src/parcel_robot/instructnav/semantic_value_map.py`
- `tests/test_semantic_value_map.py`

## Evidence

- `.parcel/bin/python -m pytest -q tests/test_value_map.py` → **9 passed**
- `.parcel/bin/python -m ruff check src/parcel_robot/navigation/value_map.py tests/test_value_map.py` → clean
- `scripts/ci_gate.py --tier commit` @ 2026-08-09T22:41:21Z: **7/8 hard PASS**;
  default-suite 3209 passed; sole red =
  `test_habitat2020_contract_smoke…` (known pre-existing / out of V-C OWNS)

## does_not_prove

No C2/C3 wiring; no Tier B SR claim. Pure module only.

## Note

First Sol landing used `instructnav/` (orchestrator prompt allowed additive path
avoiding `__init__` edits). Audit RETURNED vs plan OWNS
`navigation/value_map.py`. Cursor orchestrator relocated after Sol API limit on
redispatch `3566f49f`.