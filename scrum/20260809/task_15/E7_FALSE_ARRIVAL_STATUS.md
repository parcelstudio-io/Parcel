# E7 STATUS — THE STALE SAFETY SIGNAL, AND THE LIVE FALSE ARRIVAL BEHIND IT

**Lane:** E7. **Input:** Fable's audit finding (committed `mutation_panel.json`
says `no_false_arrival: true`; a live run on this tree says `false`), plus
E6 §7.1, which flagged the same thing and correctly did not touch it.
**Uncommitted, as instructed.**

**Verdict, in one line: the stale artifact is real, the false arrival behind it
is real, it is NOT one marginal episode but the whole `follow_owner` family, it
was introduced by the UNCOMMITTED lane E5, and its honest fix is a product
decision that this lane cannot make. The staleness hole is closed, and closing
it turns `hard-safety` RED. That red is correct and must stay red.**

| | committed artifact | live on this tree |
|---|---|---|
| `clean_checks.no_false_arrival` | `true` | **`false`** |
| clean-run `authority` | `{agreement: 5}` | **`{agreement: 4, false_arrival: 1}`** |
| clean-run `failure_histogram` | `{none: 4, grounding_error: 1}` | `{none: 3, grounding_error: 1, false_arrival: 1}` |
| panel verdict | `PANEL PASSED` | `PANEL PASSED` (unchanged — see §1.1) |

---

## 1 — Reproduction

`MUJOCO_GL=egl .parcel/bin/python scripts/mutation_panel.py` on the current tree,
written to a scratch path so the committed artifact stays attributable:

```
nav-region_goal-A-00-1c735162      succ=True  dtg=0.0000  path=3.0258   (identical)
nav-region_goal-D-15-1b8b2361      succ=False dtg=2.1020  path=0.2520   (was dtg=1.9000 path=0.4548)
nav-object_goal-A-00-4caa923b      succ=True  dtg=0.0000  path=0.6785   (identical)
nav-object_relative-A-00-3efbba45  succ=True  dtg=0.0000  path=1.8226   (identical)
nav-follow_owner-D-15-74a535dd     succ=False dtg=0.2070  path=0.0000   failure=false_arrival
                                                                        (was succ=True dtg=0.0000 path=0.2428)
```

Two of five episodes moved. Only one is safety-relevant: **`nav-follow_owner-D-15-74a535dd`**.

### 1.1 — Why the panel still says PANEL PASSED

The panel's verdict is "every exercised mutant reddened >= 1 harness check", and
all six still do. But `harness_checks` computes `reddened` as

```python
key for key, green in checks.items() if not green and clean_checks.get(key, True)
```

— a check that is **already red on the clean run is excluded from every mutant's
kill list**. So a clean-run false arrival does not fail the panel; it silently
*disables* `no_false_arrival` as a kill channel for all six mutants. That is the
exact v2 rot `tests/test_mutation_panel_freshness.py` was written for, recurring
on v3 for a different reason.

### 1.2 — What "false arrival" means here

`differential_arrival_verdict` (`instructnav/scoring.py`) records both
authorities on the final pose and classifies the pair:

| verdicts | category |
|---|---|
| agree | `agreement` |
| differ, within `ARRIVAL_BOUNDARY_EPSILON_M` (0.05 m) of the boundary | `tolerated_boundary` |
| scorer only, beyond epsilon | `authority_disagreement` |
| **system only, beyond epsilon** | **`false_arrival`** |

`scorer_arrival` is the K0 `GoalRegion.contains` predicate on the final pose.
`system_arrival` is `system_arrival_claim(status, reason)`, true when the
terminal `status` is in `{arrived, succeeded}` or the `reason` is in
`{arrived, arrived_verified, at_follow_distance, goal_reached}`.

---

## 2 — Bisect: the answer is (c), the UNCOMMITTED repair lanes

Method: `git worktree add --detach` on each commit, `third_party/` symlinked in,
run with `PYTHONPATH=<worktree>/src` so `parcel_robot` resolves to the tree under
test (asserted in-process, because the editable `.pth` points at the main
worktree's `src`). The clean run is the only thing measured — the six mutants say
nothing about whether the committed clean run is still true.

| tree | `no_false_arrival` | clean `authority` | `follow_owner-D-15` |
|---|---|---|---|
| `60ecea2` (before the task_15 batch) | **true** | `{agreement: 5}` | succ=True dtg=0.0000 path=0.2428 |
| `6bd945d` (after the task_15 batch) | **true** | `{agreement: 5}` | succ=True dtg=0.0000 path=0.2428 |
| working tree (6bd945d + E1–E6) | **false** | `{agreement: 4, false_arrival: 1}` | **succ=False dtg=0.2070 path=0.0000** |

Both commits reproduce the committed artifact's clean run **exactly** — all five
episodes, final poses and path lengths to four decimals. So:

* **(a) pre-existing since 19c9226/b75ed05 — NO.**
* **(b) introduced by the task_15 batch (60ecea2 -> 6bd945d) — NO.**
* **(c) introduced by the repair lanes E1–E6 (uncommitted) — YES.** §3 names E5.

The committed `mutation_panel.json` is byte-identical from 19c9226 to HEAD
(`git diff 19c9226 HEAD -- …/mutation_panel.json` is empty), and it was still
*true* at 6bd945d. It became a lie only when the uncommitted lanes landed.

### 2.1 — A bisect obstacle worth recording

At `6bd945d`, importing `evals.nav_instruct.runner` first makes
`navigation/detection_lock_on.py` hit a circular import on
`parcel_robot.instructnav.arbiter`; `pipeline.py`'s soft `try/except ImportError`
swallows it into `_HAS_INSTRUCTNAV = False` and the run then dies on
`GroundingOutcome is None`. **The whole InstructNav ladder is import-order
dependent at that commit.** The uncommitted `lethal_veto.py` +
`instructnav/arbiter.py` change (with `tests/test_import_order_no_cycle.py`)
fixes it. For the bisect the cycle was broken by importing `pipeline` first — no
source edit in any worktree — and the methodology was validated by re-running
`60ecea2` both ways: byte-identical results, so the preload perturbs nothing.

---

## 3 — Diagnosis: E5's person-clearance retune vs a frozen 1.8 m goal disc

### 3.1 — The failing episode, exactly

```
episode   nav-follow_owner-D-15-74a535dd  (family follow_owner, tier D)
goal      GoalRegion(kind='disc', center=(2.0, -0.5), radius_m=1.8)   [FROZEN v3]
owner     (2.0, -0.5)  — the disc is centred on the owner
start     (0.05, -0.025, yaw 1.0);  |start - owner| = 2.0070 m
trace     50 ticks, robot NEVER MOVES (path_length 0.0000 m)
terminal  mission_status='completed'  reason='at_follow_distance'
claim     system_arrival_claim('completed','at_follow_distance') -> True
K0        GoalRegion.contains(0.05, -0.025) -> False
          distance_to_goal_m = 0.2070   boundary_margin_m = 0.2070   epsilon = 0.05
verdict   AuthorityCategory.FALSE_ARRIVAL
detail    false_arrival:claim_without_predicate:dtg=0.2070m
branch    arrival_branch='none'  (arrival_hold_s=0.0 for spatial families)
```

The arrival branch that fired is `FollowOwnerController.step`'s **holding**
branch: `distance_error = distance - desired_distance_m <= distance_deadband_m`
-> `reason='at_follow_distance'`, which is in `SYSTEM_ARRIVAL_REASONS`.
`HeadlessCityQualityHarness._run_follow` then reports `status='completed'`. K0
accepted nothing — K0 said **no**; the *system* claimed arrival. This is a
claim-without-predicate (U32), not a widened region.

### 3.2 — The mechanism

`FollowConfig` on this tree, after E5 + E6:

```
person_stop_m              1.0 -> 1.2    (E5, owner-authorized 2026-08-10)
owner_keepout_m            1.55 -> 1.75  (= person_stop_m + owner_collision_envelope_m 0.55)
OWNER_STAND_OFF_MARGIN_M   0.05 -> 0.10  (E6, arrival_radius 0.06 + stand_off_margin 0.04)
desired_distance_m         1.60 -> 1.85  (= owner_keepout_m + OWNER_STAND_OFF_MARGIN_M)
distance_deadband_m        0.18          (unchanged)
```

The follow controller holds anywhere in `[desired - deadband, desired + deadband]`
and, approaching from outside, **stops at the OUTER edge** `desired + deadband`:

```
before:  1.60 + 0.18 = 1.78 m  <  1.80 m goal radius  -> inside  -> agreement
now:     1.85 + 0.18 = 2.03 m  >  1.80 m goal radius  -> outside -> false_arrival
```

On D-15 the robot starts at 2.0070 m, already inside the new band, so it never
moves at all — `path_length 0.0000`.

### 3.3 — The 2x2 (E5 vs E6), measured

Only the follow stand-off family varies; `person_stop_m` / `person_slow_m` stay
at E5's settled values in every arm (the reactive gate refuses to construct
below its floor, which is itself E5 working correctly).

| arm | `desired_distance_m` | stop distance from owner | `dtg` | authority |
|---|---|---|---|---|
| **A** current (E5 + E6) | 1.85 | 2.0070 | 0.2070 | **`false_arrival`** |
| **B** pre-retune stand-off | 1.60 | 1.7797 | 0.0000 | `agreement` (success) |
| **C** E5 term only (keepout 1.75 + old 0.05) | 1.80 | 1.9774 | 0.1774 | **`false_arrival`** |
| **D** E6 term only (old keepout 1.55 + new 0.10) | 1.65 | 1.8264 | 0.0264 | `tolerated_boundary` |

**E5 is necessary and sufficient.** Arm C — E5's `person_stop_m` 1.0 -> 1.2 with
E6's margin change backed out — is already a false arrival on its own. Arm D —
E6's margin change alone — lands 0.0264 m outside, *inside* the 0.05 m boundary
epsilon, so it is `tolerated_boundary` and would never have been called a false
arrival. E6 adds 0.05 m on top of E5's 0.20 m and makes it worse; it does not
cause it. This matches E6 §7.1's own A/B (forcing the stranger band reproduces
the failure identically) from the other direction.

### 3.4 — It is the WHOLE `follow_owner` family, not one episode

Running all ten spatial episodes of the v3 minival on this tree:

```
nav-follow_owner-A-00-40672702  dtg=0.2282  completed/at_follow_distance  -> false_arrival
nav-follow_owner-B-05-334e8d3f  dtg=0.2190  completed/at_follow_distance  -> false_arrival
nav-follow_owner-C-10-41c8032b  dtg=7.9354  completed/tracking_owner      -> agreement
nav-follow_owner-D-15-74a535dd  dtg=0.2070  completed/at_follow_distance  -> false_arrival
nav-follow_owner-E-20-433c9247  dtg=1.2579  completed/tracking_owner      -> agreement
nav-circle_owner-*  (5)                     timed_out/spatial_step_limit  -> 4 authority_disagreement, 1 agreement
```

**Three false arrivals**, all at `dtg ~= 0.21` (= 2.03 - 1.8 + rounding), i.e. all
the same structural cause. C-10 and E-20 escape only because the owner is far /
absent, so the controller reports `tracking_owner`, which is deliberately **not**
a claim of arrival. The `circle_owner` `authority_disagreement: 4` is pre-existing
and unchanged (it matches the committed frozen-baseline row exactly).

### 3.5 — Why this is not fixable by a better robot

The episode's goal disc is centred on the owner with radius **1.80 m**. The
smallest owner distance a compliant follow controller will hold is
`desired_distance_m = 1.85 m` — which is **already outside the disc** before the
deadband is considered. Even with `distance_deadband_m` driven to zero and the
0.05 m boundary epsilon spent in full, the best reachable margin is exactly
0 and only at `desired = 1.85`, i.e. `1.85 > 1.80 + 0.05` is false by 0.00 m.
**With E5's settled clearance, this frozen episode is unsatisfiable.** No control
improvement reaches it.

---

## 4 — What I fixed vs what I am escalating

### 4.1 — ESCALATED, not fixed: the false arrival itself

Every honest fix is outside this card's fences:

| candidate fix | why not |
|---|---|
| widen the `follow_owner` goal disc 1.8 -> >= 2.05 m | changes `evals/nav_instruct/generator.py` -> moves the frozen v3 `episode_digest` `919a0fea…`. **MUST-NOT-TOUCH; the card says an episode change is a STOP.** |
| back out `person_stop_m` 1.2 -> 1.0 | reverses an owner-authorized safety retune and *reduces* pedestrian clearance. Config person values are MUST-NOT-TOUCH (E5/E6 settled them). Also a safety regression traded for a green test. |
| drop `at_follow_distance` from `SYSTEM_ARRIVAL_REASONS` | **weakening the arrival check.** It makes `false_arrival` structurally unreachable for the whole follow family and would mask a genuine one. Forbidden by the standing rule, and pinned by `tests/test_arrival_authority_differential.py:85`. |
| widen `ARRIVAL_BOUNDARY_EPSILON_M` past 0.21 m | widening a tolerance to pass a test. Forbidden. |
| special-case the spatial lane's `system_arrival` in `evals/nav_instruct/runner.py` | same weakening, wearing a different hat: it deletes the channel rather than satisfying it. |

**The product decision to make:** E5's clearance retune moved the owner stand-off
ring outside a frozen eval region that was sized to the pre-retune ring. Either
the v3 `follow_owner` (and possibly `circle_owner`) goal radii are re-frozen to
the retuned stand-off under a **v4 freeze with an authorized digest move**, or
the clearance retune is revisited. Both are owner calls. Recommendation: the v4
re-freeze — the robot is behaving *more* safely, and the eval region, not the
robot, is what went stale.

Note the direction of the harm: this false arrival is the robot standing
**farther** from a person than the eval expects. It is not a robot creeping
closer while claiming success. That does not make it a tolerance to widen — a
claim/predicate disagreement is a defect either way, and it currently blinds the
panel's strongest kill channel (§1.1) — but it should inform the severity call.

### 4.2 — FIXED: the staleness hole

The hard gate could certify a safety property from a file that a live run
contradicts. It now cannot.

| # | Change | File |
|---|---|---|
| 1 | `SAFETY_RELEVANT_CLEAN_CHECKS` + `clean_safety_fields(payload)` — the narrow safety projection of a panel payload (collisions, the arrival-authority histogram, the four **absolute** clean checks). Performance fields are deliberately excluded: a guard that reddens on benign movement is a guard somebody turns off. A missing check reads `False`, so *deleting* `no_false_arrival` is never cheaper than recording it false. | `scripts/mutation_panel.py` |
| 2 | `live_clean_safety_fields()` — one clean run (~4 s), no mutants, so it is cheap enough for the **commit** tier. The pre-existing live guard runs the whole panel and is `@pytest.mark.slow`, which is exactly why it never fired in the gate. | `scripts/mutation_panel.py` |
| 3 | `evaluate_hard_safety` re-derives the committed artifact's safety fields live and reddens on divergence, naming the drifted keys. `reproduce_panel` is the seam: `None` means "re-derive live, but only for the real committed artifact"; a synthetic path records an explicit `skipped` line rather than a silent pass. | `scripts/ci_gate.py` |
| 4 | `test_committed_panel_safety_fields_still_reproduce` — the same comparison as a fast test, in the file that already owns this convention. | `tests/test_mutation_panel_freshness.py` |
| 5 | Registered in `MUTATION_FRESHNESS_NODE_IDS`, so the `mutation-panel-freshness` hard gate runs it in commit **and** nightly. | `scripts/ci_gate.py` |
| 6 | Five self-tests, seeding *staleness* the way the file seeds every other regression — a stub reproducer, never a committed-artifact edit. Includes the drop-the-key case and a proof that the default path actually wires the live reproducer instead of defaulting to skip. | `tests/test_ci_gate.py` |

The artifact was **NOT regenerated**. It is a gated input, and regenerating it
here would have laundered a live defect into a fresh green certificate — the
precise failure mode this lane exists to prevent.

---

## 5 — Gate

`.parcel/bin/python scripts/ci_gate.py --tier commit` is **RED**, in exactly the
two places the defect lives:

* `hard-safety` — `mutation panel is STALE: a live clean run contradicts the
  committed artifact on ['authority', 'clean_checks']`
* `mutation-panel-freshness` —
  `test_committed_panel_safety_fields_still_reproduce` fails with the same pair
* `default-suite` — the same new test, once

Nothing else moved: the other 30 tests in `test_ci_gate.py` and
`test_mutation_panel_freshness.py` pass, `ruff check` is `All checks passed!` on
all four touched files, and no frozen artifact, config, episode, or digest was
touched.

**This red is the correct outcome and must stay red until §4.1 is decided.**
Regenerating `mutation_panel.json` would turn it green while leaving three live
false arrivals in the product path, and would re-arm the exact blindness in §1.1.

### 5.1 — Also escalated: the nav frozen-baseline row has the same staleness

`evals/nav_instruct/results/ledger.jsonl`'s latest `frozen_baseline` row
(`nav-instruct-v1-baseline-v3-20260809T161252Z`, same era as the panel artifact)
records `authority_histogram.false_arrival = 0`, and `hard-safety` pins that at
`PINNED_FROZEN_FALSE_ARRIVAL = 0`. From §3.4, a fresh run of that same 25-episode
minival on this tree yields **`false_arrival = 3`** (`agreement` 21 -> 18). The
committed row is therefore certifying a property this tree no longer has, by the
same mechanism.

Deliberately **not** guarded here: a frozen baseline is a historical pin by
design, unlike the panel, and `evals/nav_instruct/results/ledger.jsonl` is not
this card's to regenerate. Flagged with the measurement so whoever owns the
frozen set can decide, alongside §4.1, whether the pin or the tree is wrong.
`evaluate_nav_instruct_candidate`'s `false_arrival` line is `hard=False` (a
report), so nightly surfaces this but does not gate on it.

---

## 6 — Files touched

| Path | Change |
|---|---|
| `scripts/mutation_panel.py` | `SAFETY_RELEVANT_CLEAN_CHECKS`, `clean_safety_fields`, `live_clean_safety_fields` — additive; the panel's own behaviour and output are unchanged |
| `scripts/ci_gate.py` | `Callable` import; `_panel_safety_fields_live`; `reproduce_panel` seam + the freshness comparison in `evaluate_hard_safety`; second node id in `MUTATION_FRESHNESS_NODE_IDS` |
| `tests/test_mutation_panel_freshness.py` | `test_committed_panel_safety_fields_still_reproduce` + module docstring |
| `tests/test_ci_gate.py` | five hard-safety freshness self-tests + helpers |
| `scrum/20260809/task_15/E7_FALSE_ARRIVAL_STATUS.md` | this record |

**Not touched:** `evals/nav_instruct/results/mutation_panel.json` (gated input,
deliberately left stale-and-loud), `evals/nav_instruct/episodes/**`, the v3
`episode_digest`, the three `DIGEST_SENTINEL` manifests, any `configs/**yaml`
person value, `instructnav/arbiter.py`, `runtime.py`, `navigation/follow.py`, the
`value_map` / `detection_lock_on` feature code (V-D/V-E stay OFF).
