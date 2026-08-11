# Lane E1 — UNBREAK THE PRODUCT PATH

Status: **DONE, UNCOMMITTED** (left in working tree for owner review, per instruction).
Base under repair: `6bd945d`. Reference base: `60ecea2`.

---

## BLOCKING 1 — cross-card circular import silently disabled the whole InstructNav ladder

### Exact cycle (traced, not inferred)

```
parcel_robot/instructnav/__init__.py
  -> instructnav.arbiter
      -> parcel_robot.core.arbiter          <-- S-B's line 12 (the offending edge)
          -> parcel_robot/core/__init__.py  (package init must run first)
              -> core.motion_shaping
                  -> navigation.velocity_shaping
                      -> parcel_robot/navigation/__init__.py
                          -> navigation.envs
                              -> navigation.envs.metaurban_env
                                  -> navigation.pipeline
                                      -> `from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal`
                                         (instructnav.arbiter is HALF-EXECUTED — it is
                                          sitting on line 12 of itself) -> ImportError
                                      -> swallowed by `except ImportError`
                                      -> _HAS_INSTRUCTNAV = False
```

The same cycle also silently killed the D3 lock-on guard
(`ImportError: cannot import name 'SE2Goal' from partially initialized module`
at `navigation/detection_lock_on.py:32`), setting `_HAS_DETECTION_LOCK_ON = False`.

Confirmed C-B's counterfactual import is innocent: `parcel_robot.counterfactual` first
returned `True` both before and after.

### Import-order matrix — 8 fresh subprocesses, `_HAS_INSTRUCTNAV` after `from parcel_robot.navigation import pipeline`

| first import | 60ecea2 (base) | 6bd945d (BEFORE) | after E1 fix |
|---|---|---|---|
| *(plain baseline)* | True | True | **True** |
| `parcel_robot.instructnav` | True | **False** | **True** |
| `parcel_robot.instructnav.arbiter` | True | **False** | **True** |
| `parcel_robot.core.arbiter` | True | True | **True** |
| `parcel_robot.headless_city` | True | **False** | **True** |
| `evals.nav_instruct.runner` | True | **False** | **True** |
| `parcel_robot.counterfactual` | True | True | **True** |
| `parcel_robot.authority` | True | True | **True** |

4 of 8 orders were broken. All 8 are green now.

### Fix 1a — the leaf-module move (structural)

New file **`src/parcel_robot/lethal_veto.py`** — a true leaf: it has **zero**
`parcel_robot` imports (only `collections.abc`), so importing it can never run a
package `__init__` and can never open a cycle. `waypoints_trigger_lethal_veto` moved
there verbatim (body unchanged).

- `src/parcel_robot/core/arbiter.py` now **re-exports** it
  (`from parcel_robot.lethal_veto import waypoints_trigger_lethal_veto`, plus a new
  `__all__` so ruff accepts the re-export). Public surface unchanged;
  `tests/test_core_arbiter_lethal.py` (not owned by this lane) keeps passing untouched.
  Removed the now-unused `Callable` / `Sequence` imports from that file.
- `src/parcel_robot/instructnav/arbiter.py:12` now imports from
  `parcel_robot.lethal_veto`, with a comment naming the trap so it does not get
  "tidied" back to `core.arbiter`.

`parcel_robot/__init__.py` is a docstring + `__version__` only, so the top-level
leaf is safe.

### Fix 1b — the loud-degradation mechanism (`navigation/pipeline.py`)

A soft import must degrade for **absence and only absence**. Added to pipeline.py:

- `_is_genuine_absence(exc) -> bool` — True only if `isinstance(exc, ModuleNotFoundError)`
  **and** `importlib.util.find_spec(exc.name) is None`. A circular import raises a plain
  `ImportError` ("cannot import name X from partially initialized module"), never
  `ModuleNotFoundError`, so the isinstance check alone already separates the two dominant
  cases; the `find_spec` probe additionally rejects a `ModuleNotFoundError` raised from
  *inside* a module that does exist.
- `_reraise_if_not_absent(exc, ladder, gate)` — re-raises a chained `ImportError` naming
  the ladder, the underlying exception, "this is almost always an import cycle", the
  remedy (leaf module / lazy import), and the gate test path.
- The InstructNav guard now calls it first. On the legitimate absence path it additionally
  records `INSTRUCTNAV_IMPORT_ERROR` and emits a `logging.warning` stating that semantic
  navigation, grounding, scan recovery and value-directed search are DISABLED for the
  process — so even the *legal* degrade is no longer silent.
- Same treatment applied to the D3 lock-on guard in the same file
  (`DETECTION_LOCK_ON_IMPORT_ERROR`), since that guard swallowed this identical cycle.
- New public health flag: **`pipeline.soft_import_health()`** returns
  `{"instructnav": bool, "instructnav_error": str|None, "detection_lock_on": bool,
  "detection_lock_on_error": str|None}`. Healthy tree today:
  `{'instructnav': True, 'instructnav_error': None, 'detection_lock_on': True,
  'detection_lock_on_error': None}`.

No other guarded import in pipeline.py was changed.

### Gate — `tests/test_import_order_no_cycle.py` (NEW, 10 tests, all in fresh subprocesses)

1. `test_instructnav_ladder_survives_import_order` — parametrized over all 8 orders above.
   One fresh subprocess per case (a single interpreter's `sys.modules` cache would hide
   the ordering effect entirely).
2. `test_guarded_import_does_not_swallow_a_cycle` — injects a stand-in
   `instructnav.arbiter` missing `SE2Goal` (exactly the mid-cycle shape) and asserts the
   pipeline raises rather than degrading.
3. `test_genuinely_absent_instructnav_still_soft_degrades` — hides
   `parcel_robot.voice.amendment` via a `meta_path` blocker and asserts
   `_HAS_INSTRUCTNAV is False`, `GrounderV2 is None`, `soft_import_health()["instructnav"]
   is False`, and **no** raise.

Before/after on this test file:

```
BEFORE fix: 6 failed, 4 passed
            FAILED ...[parcel_robot.instructnav]
            FAILED ...[parcel_robot.instructnav.arbiter]
            FAILED ...[parcel_robot.headless_city]
            FAILED ...[evals.nav_instruct.runner]
            FAILED test_guarded_import_does_not_swallow_a_cycle
            FAILED test_genuinely_absent_instructnav_still_soft_degrades
AFTER  fix: 10 passed
```

Lives in `tests/`, so the `default-suite` hard gate covers it. `scripts/ci_gate.py` NOT
edited (lane E2/E3 own it).

### Incidental finding (NOT fixed — out of lane, flagged for the owner)

The `except ImportError: # frozen BARN bundle path` comment is **already stale**.
`navigation/pipeline.py:14` imports `.approach`, which hard-imports
`parcel_robot.instructnav.relations` **outside any guard**, and
`instructnav/__init__.py` eagerly imports every instructnav submodule. So a tree that
genuinely lacks `instructnav/` can no longer load the pipeline at all, guard or no guard —
the guard's only remaining real job is absent *optional* deps. That is why gate test 3
hides `voice.amendment` rather than an instructnav module. Owners of `approach.py` /
`instructnav/__init__.py` should decide whether the BARN path is still a supported claim.

---

## BLOCKING-adjacent 2 — V-D broke flag-off byte-identity (global rule 3)

`navigation/instructnav_recovery.py`. V-D replaced
`prior = semantic_prior_for_label(query_label)` with
`prior_cache = plan_prior or PlanTimePriorCache.from_query_table(query_label)` **outside**
any `value_map is not None` guard. `PlanTimePriorCache.__post_init__` raises
`ValueError("query must be non-empty")` for an empty/whitespace query, so a value-map card
changed the value-map-**OFF** path.

`select_search_entity_frontier(origin_xy=(0,0), robot_xy=(0,0), query_label=Q, covered=[])`:

| `Q` | 60ecea2 (base) | 6bd945d (BEFORE) | after E1 fix |
|---|---|---|---|
| `''` | `(2.0, 0.0)` | `ValueError: query must be non-empty` | **`(2.0, 0.0)`** |
| `'   '` | `(2.0, 0.0)` | `ValueError: query must be non-empty` | **`(2.0, 0.0)`** |

FIX: the cache is a value-map concern, so it is only built on the value-map path.

```python
prior_cache: PlanTimePriorCache | None = plan_prior
if prior_cache is None and value_map is not None:
    prior_cache = PlanTimePriorCache.from_query_table(query_label)
if prior_cache is None:
    prior = semantic_prior_for_label(query_label)   # the original flag-off path
else:
    prior = prior_cache.prior_for_region(query_label)
```

(`semantic_prior_for_label` re-imported; the `ValueMapFrontierScorer` construction keeps a
`prior_cache or PlanTimePriorCache.from_query_table(...)` fallback purely to keep the type
honest — that branch always has a cache.)

Non-empty labels are unchanged: `PlanTimePriorCache.default` is `0.35`, identical to
`semantic_prior_for_label`'s default, and `noun_region_scores` is
`dict(SIDEWALK_BORDERS_ROAD_PRIORS)`, so `prior_for_region` and `semantic_prior_for_label`
agree on every key. Spot-checked: `query_label='bench'` returns
`(-0.9999999999999996, 1.7320508075688774)` both at `6bd945d` and after the fix.

GATE (`tests/test_value_directed_search.py`, which had NO flag-off test):
- `test_flag_off_frontier_uses_table_prior_not_plan_time_cache` — pins `(2.0, 0.0)` for
  `''` and `'   '`.
- `test_flag_off_frontier_matches_semantic_prior_for_label_path` — flag-off must equal the
  `plan_prior`-only call for a known noun, a table noun, and an unknown noun.

---

## 3 — CityWalker fail-soft contract broken by the ruff burn-down

`route_memory/citywalker.py:181` — the lint sweep narrowed `_probe_torch`'s
`except Exception:` to `except ImportError:` in a file no card owned. torch is a compiled
extension: a CUDA/driver mismatch or a bad `.so` load raises `OSError`/`RuntimeError`, so a
broken-but-installed torch propagated out of `CityWalkerInferenceAdapter.__init__` instead
of reaching the documented `UNVERIFIED: torch unavailable for CityWalker inference` skip
(citywalker.py:247-251).

FIX: `except (ImportError, OSError, RuntimeError):` plus a docstring stating *why* the
handler is wide, so the next lint sweep does not re-narrow it. No `noqa` was added, so
**`scripts/ci_ruff_baseline.json` needs no change** (verified: still exactly 7
fingerprints, all in `camera_channel/` + `detection_adapter/`, none from this lane).

GATE: `tests/test_p4_route_memory.py::test_citywalker_torch_probe_fails_soft_on_broken_install`,
parametrized over `OSError`, `RuntimeError`, `ImportError`. It monkeypatches
`builtins.__import__` so `import torch` raises the given exception, then asserts the
constructor does not raise, `availability()["torch_ok"] is False`, and `propose(...)`
returns `status="skipped"`, the exact `UNVERIFIED: torch unavailable for CityWalker
inference` reason, `goal is None`, `unverified is True`.

Verified against the pre-fix handler: `2 failed (OSError, RuntimeError), 1 passed
(ImportError)`. After the fix: 3 passed.

---

## VERIFY

`.parcel/bin/python scripts/ci_gate.py --tier commit` — **RESULT: PASS — every hard gate green** (112.4s):

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v3-20260809T161252Z:
                                          collisions=0 false_arrival=0 | mutation panel clean | follow-bench 5 rows
                                          hard_collision_total all 0 | walk_with_me all 0
[  PASS] HARD  frozen-digest-sentinels    3 immutable manifest(s) byte-identical to pin
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5; ratchet skipped
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3309 passed, 9 skipped, 34 deselected in 109.51s
```

- ruff: `new 0`; whole-repo `ruff check .` returns exactly the 7 baseline fingerprints.
- Frozen digests unmoved: `frozen-digest-sentinels` PASS; `git status` shows **no**
  modification under `evals/nav_instruct/`; nav_instruct v3 `919a0fea…` untouched. No fix
  in this lane moved a frozen row, so rule 2 was never triggered.

## Files touched by E1

| file | change |
|---|---|
| `src/parcel_robot/lethal_veto.py` | **NEW** leaf module — `waypoints_trigger_lethal_veto` |
| `src/parcel_robot/core/arbiter.py` | re-export from the leaf; add `__all__`; drop dead `Callable`/`Sequence` |
| `src/parcel_robot/instructnav/arbiter.py` | import from `parcel_robot.lethal_veto`, not `core.arbiter` |
| `src/parcel_robot/navigation/pipeline.py` | `_is_genuine_absence` / `_reraise_if_not_absent`, loud guards, `soft_import_health()`, `import importlib.util` |
| `src/parcel_robot/navigation/instructnav_recovery.py` | gate `PlanTimePriorCache` behind the value-map path; restore `semantic_prior_for_label` flag-off |
| `src/parcel_robot/route_memory/citywalker.py` | `_probe_torch` catches `(ImportError, OSError, RuntimeError)` + why-comment |
| `tests/test_import_order_no_cycle.py` | **NEW** — 10 fresh-subprocess import-order / loudness / soft-degrade tests |
| `tests/test_value_directed_search.py` | +2 flag-off equivalence tests |
| `tests/test_p4_route_memory.py` | +1 parametrized citywalker fail-soft test |
| `scripts/ci_ruff_baseline.json` | **unchanged** (no noqa added; count still 7) |

Nothing committed. `MUST NOT TOUCH` respected: `runtime.py`, `navigation/reactive_safety.py`,
`configs/**`, `scripts/ci_gate.py`, `evals/companion/personal_convo_v1/**`,
`tests/test_authority_*`, `tests/test_dynamic_layer.py`, `tests/test_sa2_live_pipeline.py`,
`camera_channel/**` all untouched by this lane (they show as modified in `git status` —
that is lanes E2/E3 working concurrently in the same tree).
