# Opus cross-review of Sol · task_2

**Reviewer:** Opus standing in · **Date:** 2026-08-06 · **Scope:** Sol
pure-lane drop (proxemic approach scorer + NavigateTo admission pin)

## Verdict

**APPROVE**

## Criteria

| Criterion | Result |
|---|---|
| Pure module only (not wired into pipeline) | Pass |
| Fail-closed `reject_cost` / scoring math sound | Pass |
| Admission pin searchable ≠ visible, not duplicative-broken | Pass |
| Pedestrian e2e xfail left alone | Pass |
| Unit tests adequate | Pass |

## Findings

### Proxemic scorer (`navigation/proxemic_approach.py`)

- Confined to its own module: no imports from `approach.py`,
  `pipeline.py`, reactive safety, or `collision.py`. Correct handoff —
  Opus wires `select_proxemic_approach` into polygon/approach samplers
  later.
- Cost composition is sound and documented:

  ```
  cost = w_occ * occupancy
       + w_ttc * max(0, 1 - ttc / horizon_s)
       + w_dist * (‖pose − robot‖ / distance_norm_m)
  ```

  Occupancy reuses `agent_cost_at` (CV Gaussian rollout, clipped `[0,1]`).
  TTC uses `time_to_collision_s` with **stationary** robot velocity at the
  candidate pose — the right model for “would parking here sit in the
  stream?” Distance is a soft tie-break (`distance_weight=0.05`).
- Fail-closed selection: empty candidates → `None`; admissible set is
  `costs < reject_cost` (at-threshold rejected); no least-bad stream
  landing. Malformed poses / config / tracks raise. Empty tracks yield
  zero social cost (distance only) — correct.
- Default `reject_cost=0.85` with unit occupancy+TTC weights means a pose
  that is both occupied and imminent-contact rejects hard (~2.0 combined);
  quieter side poses stay under threshold. Matches the pedestrian-xfail
  story (traffic-blind goal → person-stop; proxemic should refuse stream
  landings once wired).

### Admission pin (`brain/navigate_admission.py`)

- Pin correctly requires `{camera_fresh, lidar_fresh, base_available}` and
  forbids `target_grounded` at admission (searchable ≠ visible).
- Not duplicative-broken: module documents the contract; `validator.py`
  remains the runtime source of truth. Shared helper
  `assert_searchable_admission_contract` is what both
  `tests/test_navigate_admission_pin.py` and
  `tests/test_navigation_admission_regression.py` call against the live
  `SkillContractRegistry` — one assertion surface, no second frozenset
  that could drift from the registry independently of the check.
- Explicit `target_grounded` when plan-declared stays enforceable
  (regression already covers that path; pin does not weaken it).

### Xfail

- `test_go_to_the_sidewalk_with_pedestrian_traffic` remains
  `@pytest.mark.xfail` with the social-planning reason. Sol did not flip
  it; status note correctly defers wiring + flip to Opus / follow-on.

### Tests

```text
.parcel/bin/pytest tests/test_proxemic_approach.py \
  tests/test_navigate_admission_pin.py \
  tests/test_navigation_admission_regression.py -q
→ 17 passed
```

Proxemic coverage hits the important cases: empty tracks, stream vs quiet,
select-over-distance, TTC urgency magnitude, overlap urgency=1, reject
fail-closed, empty candidates, malformed inputs. Pin tests cover registry
match, forbidden visibility token, and missing sensor precondition.
Regression uses the shared pin on the contract test.

## Must-fix

None.

## Non-blocking notes (not blocking APPROVE)

- Optional boundary pin: assert a pose with `cost == reject_cost` is
  rejected (`<` vs `<=`). Behavior is already correct; a one-liner would
  lock it.
- Validator still owns the skill table literals; importing the pin
  frozensets into `SkillContractRegistry.default()` would eliminate the
  remaining documentation dual-source. Fine as Opus wiring follow-on —
  tests already bridge the gap today.
