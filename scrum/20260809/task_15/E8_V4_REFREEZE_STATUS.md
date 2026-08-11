# E8 STATUS — THE v3 → v4 EPISODE RE-FREEZE (owner-authorized)

**Lane:** E8. **Authorization:** owner, 2026-08-11 — *"re-freeze the episodes to
v4 so the follow/circle goal radii match the retuned stand-off, keeping the
pedestrian-clearance gain."* **Uncommitted, as instructed.**
**Input:** `E7_FALSE_ARRIVAL_STATUS.md` (the diagnosis, verified not re-derived),
`E5_PERSON_CLEARANCE_STATUS.md`, `E6_OWNER_BAND_STATUS.md`,
`AUDIT_FABLE_INDEPENDENT.md`.

**Verdict: the re-freeze is LANDED and `ci_gate --tier commit` is GREEN — and the
headline finding is that the ROBOT'S OWN ARRIVAL CLAIMS ARE BYTE-IDENTICAL
across v3 and v4.** `system_arrival_moved: []`. Nothing about the robot moved;
only what K0 says about it did. That is what "the eval region went stale, not the
robot" looks like when it is measured instead of asserted.

| | v3 (in) | v4 (out) |
|---|---|---|
| `follow_owner` goal radius | `1.8` (bare literal) | **`2.1300000000000003`** (derived) |
| minival digest | `919a0fea…` | **`4113607b…`** |
| frozen-baseline `false_arrival` | **3 on this tree** (row says 0 — stale) | **0**, measured today |
| frozen-baseline `collision_total` | 0 | **0** |
| mutation panel `no_false_arrival` | `true` but **not reproducible** | **`true`, reproduces live** |
| `no_false_arrival` as a mutant kill channel | **silently disabled** | **live** (`reactive_gate_disabled` kills through it) |
| `ci_gate --tier commit` | **RED** ×3 | **PASS** |

Only three episode *fields* moved in the whole repo, and one of them is computed
from another. Everything else in this document is provenance for that.

---

## 1 — The diagnosis, verified (not re-derived)

E7's measurement reproduces exactly on this tree, to four decimals:

```
nav-follow_owner-A-00-40672702  R=1.8 dtg=0.2282 completed/at_follow_distance -> false_arrival
nav-follow_owner-B-05-334e8d3f  R=1.8 dtg=0.2190 completed/at_follow_distance -> false_arrival
nav-follow_owner-C-10-41c8032b  R=1.8 dtg=7.9354 completed/tracking_owner     -> agreement
nav-follow_owner-D-15-74a535dd  R=1.8 dtg=0.2070 completed/at_follow_distance -> false_arrival
nav-follow_owner-E-20-433c9247  R=1.8 dtg=1.2579 completed/tracking_owner     -> agreement
nav-circle_owner-*  (5)         R=2.2            timed_out/spatial_step_limit -> 4 authority_disagreement, 1 agreement
```

3 false arrivals, all `follow_owner`, all `at_follow_distance`, all at owner
distance `dtg + 1.8` = **2.0070 / 2.0190 / 2.0282 m** — every one of them at or
inside the hold band's outer edge `desired_distance_m + distance_deadband_m =
1.85 + 0.18 = 2.03 m`, exactly as E7's mechanism predicts. `circle_owner`
unchanged and false-arrival-free.

---

## 2 — The radius, DERIVED (terms, margin, why)

Not a chosen number, and demonstrably not a fitted one.

### 2.1 What the region has to admit

`FollowOwnerController.step`'s holding branch is

```python
distance_error = distance - self.config.desired_distance_m
if distance_error <= self.config.distance_deadband_m:      # follow.py:703-712
    return self._decision(..., "at_follow_distance", ...)
```

`at_follow_distance` is in `SYSTEM_ARRIVAL_REASONS`, so it **is** a system
arrival claim. The set of owner distances at which a *compliant* controller may
make that claim is therefore `(0, desired_distance_m + distance_deadband_m]`.
Approaching from outside — which is how every one of these episodes starts — the
controller stops at the first distance satisfying the predicate, i.e. at the
band's **outer edge**. That edge is the ring the eval region must contain.

### 2.2 Which terms

Every term read from the same authority the controller obeys:

| term | value | read from |
|---|---|---|
| `person_stop_m` | 1.2 | `authority.DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)` |
| `owner_collision_envelope_m` | 0.55 | `navigation.follow._OWNER_COLLISION_ENVELOPE_M` |
| `owner_keepout_m` | 1.75 | `person_stop_m + owner_collision_envelope_m` — the ring `apply_reactive_safety` refuses to translate through |
| `OWNER_STAND_OFF_MARGIN_M` | 0.10 | `DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m` (0.06) `+ .stand_off_margin_m` (0.04) |
| `desired_distance_m` | 1.85 | `owner_keepout_m + OWNER_STAND_OFF_MARGIN_M` (lane E5) |
| `distance_deadband_m` | 0.18 | `navigation.follow.FollowConfig.distance_deadband_m` |

### 2.3 Which margin, and why that one

`StandOffEnvelope` already fixes the margin this codebase puts between a ring
that must be cleared and the region that wraps it:

```
stand_off(r) - minimum_vicinity(r) == arrival_radius_m + stand_off_margin_m
```

`arrival_radius_m` is, verbatim from `authority.FIELD_META`, *"Controller
position tolerance at the terminal pose"* — which is precisely what an eval
region must tolerate **on top of** a nominal hold band. `stand_off_margin_m` is
the authority's standing trailing margin on every stand-off. Lane E5 named that
pair `OWNER_STAND_OFF_MARGIN_M` and applied it to the owner keepout ring to get
the stand-off. Correction **(e)** applies the *same pair, one ring further out*,
to the hold band's outer edge to get the eval region:

```
radius = (desired_distance_m + distance_deadband_m) + OWNER_STAND_OFF_MARGIN_M
       = (1.85            + 0.18)                  + 0.10
       = 2.0300000000000002                        + 0.10
       = 2.1300000000000003 m            (IEEE-754 double, association L-to-R)
```

The float carries its own noise rather than being rounded: rounding would be a
choice, and the derivation's own value is what the freeze records.

A zero-margin region (radius exactly 2.03) would technically admit the
supremum — `contains` is `dist <= radius` — but it would sit exactly on the
controller's worst case, and one control tick of overshoot or one float ulp
re-opens the false arrival. The margin is what stops the eval from being
tangent to the behaviour it scores.

### 2.4 Why this is NOT a fit

* The three measured false arrivals sit at 2.0070 / 2.0190 / 2.0282 m. **Any**
  radius from 2.0282 up turns them green. 2.13 is not the smallest such number;
  it is 0.10 m past it, and it is past it by a margin applied to the *band edge*,
  never to a measured pose. The derivation never reads a run.
  Pinned by `test_the_radius_was_not_fitted_to_the_failing_episodes`.
* It is not applied only to the three that failed. The radius is a family-level
  constant and the defect is family-level (E7 §3.4 — C-10 and E-20 escape only
  because the owner is far/absent, so the controller says `tracking_owner`,
  which is deliberately not an arrival claim). All five `follow_owner` episodes
  take it.

### 2.5 Why the derivation is worth more than the number

v1–v3's `1.8` had no relationship to the controller, so E5's authorized retune
could invalidate it **silently**, and the failure surfaced three lanes later as a
false arrival. In v4 the radius is a live derivation, and
`test_the_v4_radius_is_derived_from_the_authority_not_typed` +
`test_the_generators_restated_terms_still_equal_the_live_controllers` pin it
against both the frozen literal and today's `FollowConfig`. The next clearance
retune reddens the digest pin **immediately, naming the cause**, instead of
silently making the region stale. That is the durable half of this card.

### 2.6 `circle_owner` — audited, and deliberately NOT touched

The card allows "follow/circle goal radii that the retuned stand-off
invalidated". The retune did not reach the orbit:

* the compliant terminal ring is `default_orbit_radius_m` (1.6) ±
  `waypoint_tolerance_m` (0.16) = **1.76 m**; even the widest orbit the config
  permits (`max_orbit_radius_m` 2.0) tops out at **2.16 m** — both inside 2.2;
* **not one term feeding it moved** under E5 or E6 — `default/min/max_orbit_radius_m`,
  `waypoint_tolerance_m`, `owner_collision_envelope_m`, `orbit_clearance_margin_m`
  are all untouched, and `minimum_safe_orbit_radius` reads `obstacle_stop_m`,
  which E5 did not change;
* measured: the five `circle_owner` episodes reproduce the frozen baseline
  exactly on this tree (4 `authority_disagreement` + 1 `agreement`, 0 false
  arrivals, dtg 0.0000), and are **bit-identical between the v3 and v4 columns of
  the 2x2 in both code arms**.

Pinned by `test_circle_owner_is_untouched_because_the_retune_never_reached_it`.
**Honest caveat:** applying (e)'s wrap margin to the orbit's *widest* possible
ring would give 2.16 + 0.10 = 2.26 > 2.2. That is a pre-existing tightness in a
region no term of this batch moved, no episode requests the widest orbit
("circle around the owner" resolves to `default_orbit_radius_m`), and it has
never produced a false arrival. Moving it would be a change unattributable to
this diagnosis. Flagged, not made.

---

## 3 — Byte-level scope: exactly what changed in the episodes

Diffed field-by-field over all 25 minival episodes **and** all 125 matrix
episodes:

```
episodes moved:            5 / 25   (minival)      25 / 125  (full matrix)
families moved:            ['follow_owner']        ['follow_owner']
fields moved anywhere:     ['goal', 'shortest_path_m']
goal sub-fields moved:     ['radius_m']            <- and nothing else
episode id set:            IDENTICAL (mapping total)
```

| episode | instruction | `goal.radius_m` | `shortest_path_m` |
|---|---|---|---|
| `nav-follow_owner-A-00-40672702` | follow the owner | 1.8 → 2.1300000000000003 | 1.0 → 0.0 |
| `nav-follow_owner-B-05-334e8d3f` | follow me | 1.8 → 2.1300000000000003 | 1.0 → 0.5 |
| `nav-follow_owner-C-10-41c8032b` | come with me | 1.8 → 2.1300000000000003 | 11.0 → 10.5 |
| `nav-follow_owner-D-15-74a535dd` | stay with the owner | 1.8 → 2.1300000000000003 | 0.0 → 0.0 |
| `nav-follow_owner-E-20-433c9247` | follow the owner | 1.8 → 2.1300000000000003 | 4.5 → 4.0 |

`shortest_path_m` is **computed** from the goal by `_approx_shortest_path_m`; it
is not an independent edit, and it is the only other byte the resize can reach.
D-15 already started inside the smaller disc, so its path was 0.0 and stays 0.0.

**Asserted unmoved, per episode:** `instruction`, `start_pose`, `seed`,
`target_entity_id`, `placement_overrides`, `notes`, `tier`, `absent_target`,
`distractors`, `synonym`, and every other `goal` sub-field (`center`, `kind`,
`band_m`, `polygon`, `anchor_entity`, `anchor_footprint_m`).
`test_only_follow_owner_goals_moved_and_only_in_the_radius`.

**v1, v2 and v3 did not move by a byte.** Their digests re-verify as
`cf4d5384…` / `a17c04db…` / `919a0fea…`, `git diff HEAD -- episodes/` is empty,
and `episodes/v3/manifest.json` is still byte-identical to its sentinel pin.
They keep the 1.8 literal through
`generator.FOLLOW_GOAL_RADIUS_BY_REFERENCE["frozen_literal"]`, so every ledger
row ever measured against them still means what it meant.

---

## 4 — The 2x2, with the required signature

**Axes.** *Episodes* are the DATA axis; the *tree* is the CODE axis.
**old code** = commit `6bd945d` (the tree the historical frozen-baseline row was
measured on, and the tree E1–E6 sit on top of); **new code** = that tree plus the
uncommitted lanes E1–E6. Every cell ran the 25-episode minival, `mode=baseline`,
`arrival_rule=hold-or-trace-end-v1`, `budget_policy=scaled-path-v1`,
`max_steps=200` — the historical row's own settings, or the cells would not be
comparable to it or to each other.

The old-code cells ran in a detached `git worktree` at `6bd945d` with
`third_party/` symlinked in and `PYTHONPATH=<oldtree>/src:<oldtree>`, with
`parcel_robot.__file__` **asserted in-process** to resolve inside the worktree
(the editable `.pth` points at the main tree). `navigation.pipeline` was imported
first, per E7 §2.1, because at `6bd945d` importing the runner first hits the
import cycle E1 fixed; `_HAS_INSTRUCTNAV` was asserted **True in both arms**, so
the old-code column is not a degraded navigator. The v4 column on old code
replays the **frozen v4 episode data** — `6bd945d`'s generator has no v4, and its
pre-retune authority would derive 1.93 m, not 2.13 m. That is the point of
freezing a set: the artifact is the data, not the recipe.

|  | **v3 episodes** | **v4 episodes** |
|---|---|---|
| **old code** (`6bd945d`) | SR 0.20 · agreement 21 · **false_arrival 0** | SR 0.20 · agreement 19 · ad 6 · **false_arrival 0** |
| **new code** (+E1–E6) | SR 0.12 · agreement 18 · **false_arrival 3** | SR 0.24 · agreement 21 · **false_arrival 0** |

**REQUIRED SIGNATURE — HOLDS.** False arrivals exist in exactly one cell,
(old episodes × new code) = 3, and are 0 in the other three.

**(old × old) reproduces the historical baseline bit-for-bit.** Against the
committed row `nav-instruct-v1-baseline-v3-20260809T161252Z`, every pinned
quantity is identical, not approximately equal:

```
sr                        0.2                    spl   0.16016476583919256
mean_dtg_m                8.24432438739639       sr_frozen_rule 0.04
collision_total           0                      episode_digest 919a0fea…
authority_histogram       {agreement 21, authority_disagreement 4, false_arrival 0, …}
failure_histogram         {none 5, termination 5, planning_error 6, grounding_error 3, refusal 6}
arrival_branch_histogram  {frozen_hold 1, none 20, trace_end_hold 4}
```

This is checked **from this tree** by
`bridge_v3_v4.verify_recorded_baseline_cell()` and pinned by
`test_the_recorded_old_code_cell_still_matches_the_committed_frozen_row`, so the
recorded half of the 2x2 is falsifiable rather than trusted. A loader control was
also run: v3 on old code via the generator and via the JSON episode dump are
byte-identical, so the dump loader the v4 column needs is not a confound.

### 4.1 — Reading the two axes separately

**DATA axis** (resize, at fixed code) — reaches **only `follow_owner`, on both
code arms**. Every non-follow episode is bit-identical between the v3 and v4
columns in each row of the 2x2.

**CODE axis** (E1–E6, at fixed episodes) — moves four non-follow episodes, and
moves them **identically under both episode sets**:

```
nav-object_goal-B-05-0ee314d5      dtg 0.3407 termination    -> 0.3969 planning_error
nav-object_goal-D-15-109547e2      dtg 0.0000 SUCCESS        -> 3.0293 planning_error   (-1 success)
nav-object_relative-D-15-61f68ad6  dtg 4.3301                -> 4.1822
nav-region_goal-D-15-1b8b2361      dtg 1.8999                -> 2.1020                 (E7 saw this one)
```

That identity is the proof the wider region neither causes nor **masks** any of
it: the four are just as visible in (v4 × new code) as in (v3 × new code), and
the v4 re-baseline carries them honestly. See §7.1 — they are escalated, not
this lane's.

### 4.2 — Where the +3 successes come from, honestly

v3 → v4 on new code: SR 0.12 → 0.24, `episodes_gained` = the three former false
arrivals, `episodes_lost` = **none**, collisions 0 → 0.

The most important line in the bridge is `system_arrival_moved: []` — **the set
of episodes where the robot claims arrival is byte-identical across v3 and v4.**
The robot did not start arriving at more things. K0 stopped disagreeing with it.

And the resize does not manufacture success on its own: in (v4 × old code), A-00
and B-05 do **not** flip to success. The pre-retune controller stops at ~1.83 m
from the owner, which is inside the 2.13 m disc — so K0 says arrived — but still
outside its own 1.78 m hold band, so it never claims `at_follow_distance`. The
honest verdict there is `authority_disagreement` (scorer yes, system no), the
safe direction, and the v4 region reports it rather than papering over it. Their
success on new code is the retuned controller reaching its hold band within
budget where the pre-retune one was still approaching.

---

## 5 — Every re-pinned artifact, with its 2x2

### Pin 1 — the frozen episode digest (v3 → v4)

* **old** `919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa`
* **new** `4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222`
* full-matrix digest (125 ep) `a1d43298…` → `e7c302dd…`

| | old pin (`919a0fea…`) | new pin (`4113607b…`) |
|---|---|---|
| **old episodes** | **MATCH** — `matrix_digest(generate_minival(version="v3"))` still `919a0fea…`, and the checked-in `episodes/v3/` is byte-identical to a fresh generation | mismatch — v3's radius is 1.8 |
| **new episodes** | mismatch | **MATCH** — `episodes/v4/` equals a fresh generation, file for file |

v3's pin is **not moved**; v4's is **added**. Both sets remain reproducible from
`generator.py` alone.

### Pin 2 — `DIGEST_SENTINELS` (`scripts/ci_gate.py`): 3 → 4, none moved

`evals/nav_instruct/episodes/v4/manifest.json` **ADDED** as
`b29454443e93b68d238c11d31298e81c2e9cae89d7669d9d6556405e9b7388ec`.
The three existing sentinels are **byte-identical to their pins**, re-verified
after every edit:

```
eb1289e9…  episodes/v3/manifest.json               (unchanged)
22736f6e…  companion/embodied_plan_v1/manifest.json (unchanged, E5's)
d338f335…  companion/personal_convo_v1/manifest.json (unchanged, E3's)
```

| | 3-sentinel set | 4-sentinel set |
|---|---|---|
| **old code** | **PASS** — this is the state E5/E6 left green | fail — `episodes/v4/manifest.json` does not exist at `6bd945d` |
| **new code** | **PASS but WEAKER** — the newest frozen set (the one the panel and the frozen-baseline row are now on) would be unpinned, re-opening the exact hole `AUDIT_FABLE_INDEPENDENT.md` BLOCKING 2 named | **PASS** — `4 immutable manifest(s) byte-identical to pin` |

A widening, not a re-freeze — the E3 precedent. `tests/test_ci_gate.py`'s
per-sentinel seeded-byte proof is parametrized over the set, so the new pin
gets its own redden-on-a-seeded-byte test automatically (that is 1 of the +19
tests in §8). Its literal count assertion moved 3 → 4, deliberately left a
literal so a sentinel cannot be dropped silently.

### Pin 3 — the frozen-baseline ledger row (E7 §5.1's escalation, resolved)

* **old** `nav-instruct-v1-baseline-v3-20260809T161252Z` — records
  `false_arrival: 0`, which **this tree no longer reproduces**: a fresh run of
  that same 25-episode minival gives `false_arrival: 3`, `agreement 21 → 18`,
  SR 0.20 → 0.12.
* **new** `nav-instruct-v1-baseline-v4-20260811T070536Z` — `false_arrival: 0`,
  `collision_total: 0`, `agreement: 21`, SR 0.24, `episode_digest 4113607b…`,
  `budget_policy scaled-path-v1`, measured today.

| | old row (v3, fa 0) | new row (v4, fa 0) |
|---|---|---|
| **old code** | **MATCH** — bit-for-bit, §4 | the v4 set does not exist there |
| **new code** | **mismatch** — fa 3 ≠ 0; the row certifies a property this tree does not have | **MATCH** — `hard-safety`: `nav frozen baseline …v4-20260811T070536Z: collisions=0 false_arrival=0` |

The stale row is **superseded, not deleted or edited**: the ledger is append-only
and its prefix is byte-identical (`diff` of the pre-append file against the new
file's head is empty). `ci_gate._latest_frozen_baseline_row` reads the last
`frozen_baseline` row, so the v4 row is now the pin and
`PINNED_FROZEN_FALSE_ARRIVAL = 0` is satisfied **legitimately**.

The new row carries `refreeze_provenance` — a new optional ledger key stamped
only when a run declares one, following the `navigator_flags` precedent so an
ordinary row's shape does not move. It names the authorization, the superseded
row, the mechanism, the derivation, and the bridge. A reader of the pin the hard
gate consults should not have to find a status doc to learn the episode set moved.

### Pin 4 — `scripts/mutation_panel.py` `EPISODE_SET_V3` → `EPISODE_SET_V4`

This bump is the one `tests/test_mutation_panel_freshness.py` was **written to
demand**: its `_CURRENT_FROZEN_EPISODE_SET` advances on its own when a `vN` set
is added, and both its guards stay red until this module follows.

| | panel on v3 | panel on v4 |
|---|---|---|
| **old code** | **PASS** — v3 was current and its clean run was genuinely false-arrival free | fail — v4 does not exist there |
| **new code** | **FAIL, correctly** — `mutation panel certifies 'v3' but the current frozen baseline is 'v4'`; and on this tree the v3 clean run contains a false arrival, which `harness_checks` then excludes from every mutant's kill list, silently disabling `no_false_arrival` for all six (E7 §1.1's v2 rot, recurring) | **PASS** — 6/6 killed, `no_false_arrival` green on the clean run **and** reddened by `reactive_gate_disabled` |

The five `PANEL_EPISODE_IDS` are unchanged: v4 moves only a goal radius, and the
selection is a coverage argument about which code each mutation touches.

### Pin 5 — `ci_gate.evaluate_nav_instruct_candidate` `--episode-version v3` → `v4`

Nightly-only, and a pin update, not a behaviour change: the candidate arm must
run the same frozen set the frozen-baseline row and the panel are on, or the
nightly comparison is between two different eval regions.

### Not re-pinned (deliberately)

* `episodes/v3/**` and its sentinel — v3 stays frozen and immutable.
* `tests/test_nav_instruct_episodes_v3.py` — untouched; all 14 still pass.
* `PINNED_FROZEN_FALSE_ARRIVAL = 0` — the pin was never the problem; the row
  under it was. Unchanged.
* `ARRIVAL_BOUNDARY_EPSILON_M`, `SYSTEM_ARRIVAL_REASONS`, `at_follow_distance` —
  untouched. See §6.
* `configs/**` person values, `navigation/follow.py`, `navigation/reactive_safety.py`,
  `runtime.py`, `instructnav/**`, `camera_channel/**`, the `value_map` /
  `detection_lock_on` feature code — untouched.
* **No locked file's content was altered to make a pin fit.** The one sentinel
  change is an addition; the three existing pins name files whose bytes did not
  move.

---

## 6 — What was NOT done, because it was forbidden and wrong

Every one of these would have turned the gate green and is a weakening:

| candidate | why not |
|---|---|
| drop `at_follow_distance` from `SYSTEM_ARRIVAL_REASONS` | makes `false_arrival` structurally unreachable for the whole follow family. Explicitly rejected. |
| widen `ARRIVAL_BOUNDARY_EPSILON_M` past 0.21 | widening a tolerance to pass a test. |
| special-case the spatial lane's `system_arrival` in the runner | deletes the channel instead of satisfying it. |
| back out `person_stop_m` 1.2 → 1.0 | reverses an owner-authorized safety retune and *reduces* pedestrian clearance. |
| pick the smallest radius that passes (2.0282+ε) | fitting the eval to the measurement — a FAIL of this card by its own terms. |

None was needed. The region was the stale thing, and the region is what moved.

---

## 7 — Gate

```
CI GATE — tier=commit  (2026-08-11T07:14:30Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z:
                                          collisions=0 false_arrival=0 |
                                          mutation panel clean: collisions=0 no_false_arrival=True |
                                          mutation panel freshness: committed fields reproduce live = True |
                                          follow-bench: 7 row(s), hard_collision_total all 0 = True |
                                          walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling (rows=5)
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3390 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.
```

The three gates E7 left RED — `hard-safety`, `mutation-panel-freshness`,
`default-suite` — are green, and green for the right reason:
`mutation panel freshness: committed fields reproduce live = True`.

`ruff check` is `All checks passed!` on all eight touched Python files; the gate
ratchet is `7 / baseline 7 / new 0`.

### 7.1 — The suite count reconciles exactly: **3371 + 19 = 3390**

Measured, not asserted: re-running the default selection with the new test file
ignored and the one new sentinel parametrization deselected gives **3371 passed,
9 skipped** — the pre-E8 baseline on this tree. (The card said 3370; 3371 is
E6's 3365 plus E7's six.) The +19 is `tests/test_nav_instruct_episodes_v4.py`
(18) plus the automatically parametrized fourth sentinel (1). **No test was
deleted, weakened, skipped or re-baselined.**

### 7.2 — E7's staleness guard still reddens (proved, not assumed)

A guard that went green by being defanged is a fail. Seeded live against the real
`evaluate_hard_safety`, each case on a scratch copy of the artifact (the
committed file was never edited), with one shared live clean run:

```
OK  control_real_artifact           pass  red=False   <- the real artifact is genuinely green
OK  no_false_arrival_flipped_true   fail  red=True    <- the exact E7 case
OK  authority_histogram_drifted     fail  red=True
OK  no_false_arrival_key_deleted    fail  red=True    <- dropping the key is not cheaper
OK  collisions_drifted              fail  red=True
OK  benign_mean_dtg_moved           pass  red=False   <- performance drift still must NOT redden
```

All five `test_ci_gate.py` hard-safety freshness self-tests and both
`test_mutation_panel_freshness.py` guards pass on their own merits. The guard is
live in both directions.

### 7.3 — The panel was regenerated LAST, and laundered nothing

E7 refused to regenerate while the defect was live. That reasoning still binds,
so the panel was regenerated only after §4 showed the defect resolved — and the
evidence that nothing was laundered is that **the artifact's safety-relevant
fields did not move at all**:

```
clean_safety_fields(superseded v3 artifact) == clean_safety_fields(regenerated v4 artifact)  ->  True
{authority: {agreement: 5}, collisions: 0,
 clean_checks: {no_false_arrival, no_authority_disagreement, zero_collisions, path_length_plausible} all true}
```

What did move: the `episode_set_version` label; two clean-run poses that E1–E6
already moved on the CODE axis (`nav-region_goal-D-15` path 0.4548 → 0.2520 and
`nav-follow_owner-D-15` path 0.2428 → 0.0 — both reported by E7 before this lane
existed); and **two mutants gaining an extra reddened check**
(`arrival_radius_x2` and `inverted_relation` now also redden
`mean_dtg_within_tolerance`). The panel got *stronger*, not greener. Still 6/6
killed, `PANEL PASSED`. The payload carries an `episode_set_provenance` field
stating all of this on the artifact itself.

---

## 8 — Files touched

| Path | Change |
|---|---|
| `evals/nav_instruct/generator.py` | `EPISODE_SET_V4`; the correction-(e) derivation block (terms, margin, why, and why it is not a fit); `FOLLOW_OWNER_GOAL_RADIUS_M` + the five terms it is built from; `CIRCLE_OWNER_GOAL_RADIUS_M` with the audit for leaving it alone; `EpisodeSetSpec.follow_goal_radius_reference`; `follow_owner_goal_radius_m()`; the follow/circle branches read the version instead of a literal |
| `evals/nav_instruct/runner.py` | `ARRIVAL_RULE_FOR_VERSION["v4"]` — the v2/v3 rule, unchanged, so a v3→v4 delta cannot contain a rule change |
| `evals/nav_instruct/bridge_v3_v4.py` | **new** — the derivation as re-evaluable data, the spec bridge, the 2x2 with its required signature, the episode-axis / code-axis split, and the falsifiable check of the recorded old-code cell |
| `evals/nav_instruct/run_nav_instruct_v1.py` | optional `--refreeze-provenance`, stamped on the report and the ledger row only when given |
| `evals/nav_instruct/episodes/v4/**` | **new** — 25 episode JSONs + manifest (`b2945444…`) |
| `evals/nav_instruct/README.md` | v4 row in the episode-set table, the "why v4" paragraph, `bridge_v3_v4.py`, the current-baseline command |
| `evals/nav_instruct/results/ledger.jsonl` | one appended row; append-only prefix byte-identical |
| `evals/nav_instruct/results/nav-instruct-v1-baseline-v4-20260811T070536Z.json` | **new** — the frozen-baseline report |
| `evals/nav_instruct/results/bridge_v3_v4.json` | **new** — the measured bridge |
| `evals/nav_instruct/results/mutation_panel.json` | regenerated on v4, LAST, with `episode_set_provenance` |
| `scripts/mutation_panel.py` | `EPISODE_SET_V3` → `V4` (3 sites); `PANEL_REGENERATION_PROVENANCE` + the payload field; the note on why the ids did not change |
| `scripts/ci_gate.py` | `DIGEST_SENTINELS` + v4 manifest and its re-pin log entry; candidate arm `--episode-version` v3 → v4 |
| `tests/test_nav_instruct_episodes_v4.py` | **new**, 18 tests |
| `tests/test_ci_gate.py` | sentinel count literal 3 → 4, with the reason inline |
| `scrum/20260809/task_15/E8_V4_REFREEZE_STATUS.md` | this record |

Nothing in MUST-NOT-TOUCH was edited: no `configs/**` yaml person value,
`navigation/follow.py`, `navigation/reactive_safety.py`, `runtime.py`,
`instructnav/**`, `camera_channel/**`, the `value_map` / `detection_lock_on`
feature code, or the `personal_convo` / `embodied` locked files' content.
`evals/nav_instruct/episodes/v1|v2|v3/**` are byte-identical to HEAD.
**Nothing committed.**

---

## 9 — Escalated, deliberately NOT fixed here

**E1–E6 cost `nav-object_goal-D-15` and moved three other episodes' `dtg` on the
nav_instruct minival, and nobody has owned it.** §4.1 has the four episodes and
the numbers. This is a real capability delta on the CODE axis, it is fully
visible in the new v4 frozen-baseline row (SR 0.24 where the code axis alone
would have given 0.28), and the resize does not hide it — the four move
identically under both episode sets.

Two hypotheses were **ruled out by measurement**, so whoever picks this up starts
further along:

* **`safety.person_slow_m` is not the cause.** Forcing the stranger comfort band
  back to E5's pre-retune 2.0 m (single patch point, diagnostic only, nothing
  shipped) reproduces all four episodes **bit-identically** — same dtg to four
  decimals, same failure class, same verdict.
* **The InstructNav ladder is not the cause.** `_HAS_INSTRUCTNAV` is `True` in
  both code arms, so the old-code column was not running a degraded navigator and
  E1's cycle fix is not what moved them.

E5 and E6 both state they did not re-measure nav_instruct; this lane did, and
this is what it found. It belongs to a card that owns E1–E4.

---

## does_not_prove

* Does **not** prove 2.13 m is the *only* defensible radius. It is the one this
  stack's own margin convention yields when applied to the hold band's outer
  edge. A different convention (e.g. wrapping the band's *centre*, or adding the
  reaction-time term) would yield a different number; the claim is that this one
  is derived from the authority the controller obeys, with the margin the
  authority already uses one ring in, and that it reads no measurement.
* Does **not** prove the `follow_owner` family is *well* evaluated. All five
  episodes still centre their goal disc on the owner's start position, so a
  robot that follows a moving owner perfectly can still score badly and one that
  stands still can score well (D-15 succeeds with `path_length 0.0`). The resize
  fixes an arrival-authority contradiction; it does not make the family a good
  test of following.
* Does **not** prove anything about `circle_owner` beyond "the retune did not
  reach it". The four pre-existing `authority_disagreement`s in that family are
  unchanged, unexplained by this lane, and still unowned.
* Does **not** prove the +3 successes are a capability gain. They are a scoring
  correction: `system_arrival_moved` is empty, so the robot's own claims are
  byte-identical across v3 and v4.
* Does **not** prove the E1–E6 code-axis deltas in §9 are benign. It proves only
  that they are not the resize, and that the resize does not mask them.
* Does **not** re-measure FOLLOW_BENCH_V1, the embodied plan, or the companion
  ledgers. No config, no controller and no locked input moved in this lane, so
  all three are read from their existing frozen artifacts.
* Does **not** prove hardware behaviour: every number here is the headless
  kinematic city block with an oracle owner track.
