# DR-1 — EXTEND the existing drift machinery — STATUS

Card: `scrum/20260811/task_2/SLAM_M_PLAN.md` Wave 1, DR-1. Executor: Sol 5.6 Ultra.
Base: `dd2e857` + the audited uncommitted batch. **Not committed.**

Prime directive was EXTEND, not rebuild. The result is measurably additive:
across the three edited files there are **163 + 161 insertions and 0 deletions**
in `configs/navigation/pose.yaml` and `tests/test_pose_drift_calibration.py`,
and in all of `pose.py` exactly **one** pre-existing line is modified —
`self._var_xy += var_trans` becomes `self._var_xy += var_trans + slip_var`,
where `slip_var` is exactly `0.0` unless slip is configured.

No new `pose_profiles.py`. No new dataclass system. No re-derivation of the
calibration. `provider_from_config(profile=...)` was already the by-name seam
and still is.

## 1. New knobs and their defaults

| Knob | Where | Default | Meaning |
|---|---|---|---|
| `slip_jump_magnitude_m` | `OdometryNoiseParams` | `0.0` (off) | displacement of one foot-slip event, metres, applied in a uniformly random direction |
| `slip_jump_rate_per_m` | `OdometryNoiseParams` | `0.0` (off) | mean slip events per metre **travelled** (Poisson along distance, not time) |
| `lost_windows` | `DriftingOdomProvider`, `PoseConfig`, yaml `health.lost_windows` | `()` (off) | scheduled `(start_s, duration_s)` dropouts that **recover** |
| `DriftingOdomProvider.slip_events` | read-only property | `0` | events fired since reset — non-vacuity evidence for an eval row |

Both slip fields are appended **after** `seed` in the dataclass on purpose:
inserting mid-list would silently re-map any positional construction of
`OdometryNoiseParams`. Field order is API surface.

Slip is enabled only when **both** knobs are strictly positive
(`OdometryNoiseParams.slip_enabled`). This is load-bearing, not stylistic — see §4.

`lost_windows` semantics: episode-relative (measured from the first stamped
truth sample, identical to `lost_after_s`), half-open `[start, start+duration)`
so a window lasts exactly `duration_s` and recovery is a single well-defined
instant, sorted on normalize, overlapping windows legal and meaning their union.
Health precedence is **`forced_health` > `lost_after_s` > `lost_windows`**: the
one-way trapdoor is checked first so no recovering window can ever resurrect a
permanently-lost provider. The existing one-way `lost_after_s` is unchanged.

**Drift is independent of health.** ODOM keeps integrating through a LOST window
exactly as it would without one — a localizer announcing it is lost does not
stop the legs. Pinned by a bit-identical-track test (§4).

## 2. The two new profiles

`go2_nominal` is **not a new yaml entry**. Per the card, the nominal rung *is*
`calibrated_go2` verbatim, and its derivation block in `configs/navigation/pose.yaml`
(DogLegs Go2: 0.5–1.0 % distance short-segment RPE, 0.2–0.5 deg/m yaw) is the
provenance for the whole ladder. A `go2_nominal` alias was deliberately not
added: copying those seven constants into a second entry would create two things
that must be kept equal. **The r1 draft's "1–3 %/m" figure is refuted by that
same derivation block and is not used anywhere here.**

### Derivation (no second citation invented)

No published slip-rate or degraded-terrain drift figure for the Go2 exists in
the sources this repo cites. Rather than fabricate one, each new rung is a
**stated multiple `k` of the calibrated sigma**, so the single published anchor
governs the entire ladder, and each rung's **target band is `k` × the published
DogLegs band**. The multiplier is declared as an engineering tier choice; the
band it implies is then measured.

`go2_aggressive` k = 2 · `go2_degraded` k = 4.

**alphas scale as k², systematic sigmas as k.** `alpha1..4` are *variance*
coefficients (`pose.py` docstring: sampled sigma of a straight `d`-metre
increment is `sqrt(alpha3)·d`), so scaling sampled sigma by `k` requires scaling
the alphas by `k²`. Getting this backwards would make "2×" mean 1.41×. Pinned by
`test_the_ladder_multiples_are_exactly_what_the_yaml_derivation_claims`.

### Parameters

| | `calibrated_go2` (k=1, existing) | `go2_aggressive` (k=2) | `go2_degraded` (k=4) |
|---|---|---|---|
| `alpha1` | 0.002 | 0.008 | 0.032 |
| `alpha2` | 0.001 | 0.004 | 0.016 |
| `alpha3` | 0.003 | 0.012 | 0.048 |
| `alpha4` | 0.001 | 0.004 | 0.016 |
| `systematic_translation_scale_sigma` | 0.0075 | 0.015 | 0.030 |
| `systematic_yaw_bias_sigma_rad_per_m` | 0.0061 | 0.0122 | 0.0244 |
| `slip_jump_magnitude_m` | 0.0 | 0.0 | **0.15** |
| `slip_jump_rate_per_m` | 0.0 | 0.0 | **0.05** |
| `seed` | 20260807 | 20260807 | 20260807 |

Slip constants (`go2_degraded` only) are a declared tier choice with a stated
intent, not a measurement: magnitude 0.15 m ≈ one Go2 stride at the ~1 m/s eval
cruise (one fully-slipped stance phase mis-integrated); rate 0.05 /m = one
expected event per 20 m, i.e. ~one observable discrete jump per travel-heavy
episode — frequent enough to be exercised, rare enough to stay a jump rather
than become a second noise floor.

### Target bands and MEASURED results — 60 seeds, existing harness

Measured by `tests/test_pose_drift_calibration.py` (`sweep` / the new
`sweep_full`), canned square circuit, seeds 0–59, D = 10 / 20 / 40 m.
`sweep_full` exists because `sweep` enumerates the six fields it copies and so
would silently drop the slip knobs; rather than edit a helper the twelve pinned
tests depend on, the variant uses `dataclasses.replace`, which cannot drop a
field added later.

| profile | metric | target band (source) | measured 10 / 20 / 40 m | verdict |
|---|---|---|---|---|
| `go2_aggressive` | yaw deg/m | **0.4 – 1.0** = 2× DogLegs | 0.737 / 0.629 / 0.548 | in band at every length |
| `go2_aggressive` | scale-only % | **1.0 – 2.0** = 2× DogLegs | 1.282 (straight, rotation noise off) | in band |
| `go2_aggressive` | accum. % @20 m | pinned as MEASURED (2.5–7.5) | 4.59 | pinned |
| `go2_degraded` | yaw deg/m | **0.8 – 2.0** = 4× DogLegs | 1.557 / 1.239 / 1.197 | in band at every length |
| `go2_degraded` | scale-only % | **2.0 – 4.0** = 4× DogLegs | 2.563 | in band |
| `go2_degraded` | accum. % @20 m | pinned as MEASURED (5.0–14.0) | 9.22 | pinned |
| `go2_degraded` | slip events / 20 m | 0.5 – 2.0 (rate implies ~1.0) | 0.57 / 1.13 / 2.15 | fires, matches intent |

As with `calibrated_go2`, the **accumulated** end-of-path percentage is pinned as
MEASURED and is *not* claimed to match the published translational band —
heading error dominates it, for exactly the reason derived in the
`calibrated_go2` block. The honesty split of the existing methodology is
preserved rung for rung.

### The ladder interpolates the two anchors this repo already owned

At D = 20 m, both metrics strictly monotone
(`test_the_ladder_is_strictly_monotone_and_interpolates_the_existing_anchors`):

| | calibrated_go2 | go2_aggressive | go2_degraded | stress |
|---|---|---|---|---|
| yaw deg/m | 0.315 | 0.629 | 1.239 | 2.147 |
| accum. % | 2.30 | 4.59 | 9.22 | 20.50 |

The published band bounds the bottom and the pre-existing pinned stress tier
bounds the top, so the two new rungs are bracketed from both sides. The test also
asserts `calibrated_go2` is the only rung inside the published band — a degraded
tier a reader could mistake for nominal is not a tier.

### `*_lost` variants

`calibrated_go2_lost`, `go2_aggressive_lost`, `go2_degraded_lost` = base profile
+ one window `(start_s 4.0, duration_s 3.0)`.

Window derivation: the travel-heavy eval cells run ~12 m at the ~1 m/s cruise the
harness assumes (0.1 m per 0.1 s tick) ≈ 12 s. To prove RECOVERY and not merely
the drop, the episode must contain healthy operation before **and** after, so
split the shortest such episode in three: 4 s healthy lead-in, 3 s LOST, ~5 s
recovered. 3.0 s = 30 ticks at 10 Hz, so the hold spans many ticks rather than
being a single-tick blip a consumer could miss. Pinned by
`test_the_derived_window_recovers_inside_a_short_travel_episode`
(asserts exactly 30 LOST ticks, healthy at 3.9 s and again at 7.0 s).

**Handoff note for DR-2:** if a DR-2 substrate is materially shorter than ~10 s
of travel this window stops being derivable and needs a DR-1 handoff, not a
local edit — `pose.yaml` is DR-1-frozen for Wave 2.

Each `_lost` variant repeats its base's noise block verbatim. That duplication is
forced (the base profiles are byte-frozen, so a yaml anchor would require editing
them) and follows the precedent `calibrated_go2_reanchoring` already set.
`test_lost_variants_are_their_base_profile_plus_a_window` asserts each variant's
parsed noise **equals** its base, so the copies cannot silently drift apart.

## 3. Schema extension

`PoseConfig` gains `lost_windows: tuple[tuple[float, float], ...] = ()`.
`OdometryNoiseParams` gains the two slip fields — `from_mapping` derives its
allowed key set from the dataclass fields, so it accepted them with no loader
change (additive by construction).

Unknown-keys-fail-closed is **preserved and extended**. The profile level and the
`noise` level already failed closed; the two nested sub-maps did **not** — a
typo'd `health: {los_after_s: 3}` was silently ignored, which is the exact
failure mode fail-closed parsing exists to prevent. Adding a nested key
(`lost_windows`) without closing that hole would have widened it, so
`_MAP_CORRECTION_KEYS` and `_HEALTH_KEYS` are now validated too. No pre-existing
profile carries an unknown nested key, so **no parsed config moves** (§4).

yaml shape — mappings only, one shape, fail closed:

```yaml
health:
  lost_windows:
    - start_s: 4.0
      duration_s: 3.0
```

Bare pairs are rejected: `[4.0, 3.0]` is ambiguous between (start, duration) and
(start, end) at a glance, and a silently misread dropout schedule would
invalidate every eval row that ran under it. Wrong *shape* raises `TypeError`,
well-shaped-but-invalid *values* raise `ValueError`; both fail closed.

## 4. Byte-untouched proofs

Baselines were captured from the tree **before** any edit and re-verified after
every edit (`diff` clean, three times including final).

Pinned at three depths in `tests/test_pose_degraded_profiles.py`, for all five
pre-existing profiles (`stress`, `calibrated_go2`, `calibrated_go2_reanchoring`,
`lost`, `degraded`) plus the `truth` top-level default:

1. **Raw yaml mapping** — `sha256(json(mapping, sorted))[:16]`:
   `calibrated_go2` `b54044cc36fb85ba` · `calibrated_go2_reanchoring`
   `9ab13b1209b45f81` · `degraded` `0bde3a76b86ce0eb` · `lost`
   `df6bbaceea4b7e02` · `stress` `a9137a7430ccceec` — all unmoved. Independently
   corroborated by `git diff`: **0 deletions** in `pose.yaml`.
2. **Parsed `PoseConfig`** — every field asserted against its pre-edit value,
   plus the new fields asserted inert (`lost_windows == ()`,
   `slip_enabled is False`) on every pre-existing profile.
3. **Driven ODOM endpoint** — exact float equality after the 20 m canned
   circuit. This is the RNG-stream fingerprint and the only one of the three that
   can catch a stray draw:
   `calibrated_go2` / `calibrated_go2_reanchoring`
   `(0.032388019441, 0.039168085, -0.016629364578)`;
   `lost` / `degraded` `(-0.072875542135, 0.148539576874, -0.060044507358)`;
   `stress` `(-0.643125285871, 2.118524768364, -0.880073219765)`.

**Why depth 3 is the one that matters.** `DriftingOdomProvider` draws every
sample from one shared `random.Random`. A slip implementation that consumed a
random number even when slip is *off* would shift every pre-existing profile's
trajectory by a full sample — and every calibration band would still pass,
because the bands are means over 60 seeds. The guard (`slip_enabled` requires
**both** knobs positive) is therefore the load-bearing line, and it is proved
three ways:

- `test_disabled_slip_consumes_no_randomness` — parametrized over
  (0,0), (0.25, 0) and (0, 0.5): a half-configured slip is OFF and off means
  **bit-identical**, position *and* covariance.
- `test_enabled_slip_moves_the_trajectory_so_the_neutrality_pins_can_fail` — the
  **seeded-failure proof**: enabling slip on the same seed fires >0 events and
  moves the endpoint off its pin, so the pins above are not vacuous.
- `test_pre_existing_profiles_drive_to_the_same_odom_pose` — the pins themselves.

The twelve original calibration tests are **literally byte-untouched**: `git
diff` reports 161 insertions and **0 deletions** in
`tests/test_pose_drift_calibration.py`. All twelve pass unmodified.

LOST-window composition is proved by `test_windows_do_not_corrupt_drift_state`:
the same seed driven with and without a window produces **bit-identical**
position tracks, `travelled_m`, `odom_error_m` and covariance — and the windowed
run really does report LOST, or the test would prove nothing.

## 5. Gate results

| Gate | Result |
|---|---|
| Fresh baseline `ci_gate --tier commit` (pre-work, verified) | **PASS** — 3668 passed, 0 failed, ruff 7 = baseline 7, new 0 |
| Existing 12 calibration tests, untouched | **PASS** (0 deletions in the file) |
| New profiles measured in-band, 60 seeds | **PASS** — 4/4 target bands, all lengths (§2) |
| New profiles construct via `load_pose_config`; pre-existing parsed configs unchanged | **PASS** (§4 depth 2) |
| LOST windows recover, compose with drift without corruption | **PASS** — bit-identical track + 30-tick hold |
| Slip default-off byte-neutral; seeded non-zero slip fires | **PASS** (§4, three tests) |
| `ruff check` on all touched files | **PASS** — All checks passed; **0** new fingerprints attributable to DR-1 |
| `ci_gate --tier commit` after the change | 9/10 hard gates PASS; **ruff red is RM-1's, attributed in §7** |

Pose suite total: **144 passed** across
`test_pose_degraded_profiles.py` (56 new) + `test_pose_drift_calibration.py`
(12 original + 13 new = 25) + `test_pose_seam.py` + `test_pose_consumers.py`.

## 6. The by-name contract DR-2 consumes

Nothing else is needed. No `OdometryNoiseParams` construction, no code change
here to add an arm:

```python
from parcel_robot.pose import provider_from_config

provider_from_config(profile="calibrated_go2")        # nominal rung (= go2_nominal)
provider_from_config(profile="go2_aggressive")        # 2x the published band
provider_from_config(profile="go2_degraded")          # 4x, plus foot slip
provider_from_config(profile="calibrated_go2_lost")   # + recovering dropout
provider_from_config(profile="go2_aggressive_lost")
provider_from_config(profile="go2_degraded_lost")
provider_from_config(profile=None)                    # shipping truth passthrough
```

Returns a ready `PoseProvider`. Unknown profile names and unknown yaml keys
raise, so a mistyped arm fails loudly instead of quietly measuring the nominal
tier and reporting it as degraded. Providers are stateful and accumulate drift,
so DR-2 must keep building one **fresh per episode** —
`HeadlessCityQualityHarness.new_pose_provider()` already does exactly this and
already accepts `pose_profile=`, so the DR-2 injection path needs no change in
DR-1's files.

For per-episode non-vacuity reporting, DR-2 has
`provider.travelled_m`, `provider.odom_error_m`, `provider.odom_yaw_error_rad`
and the new `provider.slip_events`.

Verified end-to-end through the **unmodified** harness seam
(`HeadlessCityQualityHarness(pose_profile=...).new_pose_provider()`), 12 s
straight episode at the 1 m/s cruise — nothing in DR-2's injection path needs a
DR-1 change:

| profile | travelled | odom error | slips | LOST ticks |
|---|---|---|---|---|
| `calibrated_go2` | 11.90 m | 0.183 m | 0 | 0 |
| `go2_aggressive` | 11.90 m | 0.364 m | 0 | 0 |
| `go2_degraded` | 11.90 m | 3.071 m | 0 | 0 |
| `go2_degraded_lost` | 11.90 m | 3.071 m | 0 | **30** |

The fresh-per-episode invariant holds (a second `new_pose_provider()` starts at
zero error), and the derived window produces its full 30-tick hold **and**
recovers inside a 12 s episode.

> ### ⚠ Handoff warning for DR-2 — single-episode divergence is NOT the band
>
> The in-band figures in §2 are **60-seed means**. A single episode can sit deep
> in the tail, and a per-episode "divergence within the profile's band" gate
> written against the mean **will red spuriously**. Straight 11.9 m run,
> % of distance:
>
> | profile | 60-seed mean | median | p90 | max | **default seed 20260807** |
> |---|---|---|---|---|---|
> | `calibrated_go2` | 3.42 | 2.89 | 6.38 | 11.44 | 1.53 |
> | `go2_aggressive` | 6.83 | 5.76 | 12.75 | 22.73 | 3.06 |
> | `go2_degraded` | 14.21 | 12.43 | 28.25 | 46.95 | **25.81** |
>
> The means are a clean 1 : 2.00 : 4.15 ladder, exactly as derived. But every
> profile ships `seed: 20260807`, and that one seed lands *below* the mean for
> `calibrated_go2` and *well above* it for `go2_degraded` — enabling slip adds a
> draw per increment, which reshuffles the whole stream relative to the
> non-slip profiles. So:
>
> 1. **Vary the seed per episode** (`dataclasses.replace(cfg.noise, seed=...)`)
>    or every episode of an arm replays one identical draw, and n = 60 episodes
>    measures a sample of size one.
> 2. Size any per-episode band off the **p90 (≈2× the mean)**, not the mean.
> 3. Straight-line percentages exceed the §2 canned-circuit ones because the
>    circuit's turns partially cancel accumulated heading bias. Compare like
>    with like.

## 7. ci_gate — and the ruff red, attributed

Fresh baseline before any DR-1 edit (`2026-08-12T04:30:10Z`): **PASS**, 3668
passed / 0 failed, ruff 7 violations = baseline 7, new 0.

After DR-1 (`2026-08-12T04:42:31Z`):

```
CI GATE — tier=commit
[  FAIL] HARD  ruff              8 violation(s), baseline 7, new 1
                                 -> src/parcel_robot/route_memory/__init__.py::I001
[  PASS] HARD  hard-safety       collisions=0 false_arrival=0 across every artifact
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite     3737 passed, 9 skipped, 36 deselected, 0 failed
==============================================================================
RESULT: FAIL — 1 hard gate(s) red: ruff
```

**The test suite is fully green: 3737 passed, 0 failed** = baseline 3668 + 69 new
DR-1 tests (56 + 13). Every frozen digest, safety and latency gate is unmoved.

**The ruff red is RM-1's, not DR-1's — proven, not asserted.** RM-1 runs
concurrently in `route_memory/**`, which is DR-1's MUST-NOT-TOUCH. Using
`ci_gate`'s own `_ruff_fingerprints()` against `scripts/ci_ruff_baseline.json`:

```
baseline count : 7      current count : 11
NEW fingerprints:
  src/parcel_robot/route_memory/__init__.py::I001      <- RM-1
  tests/test_p4_place_graph.py::I001                   <- RM-1
  tests/test_p4_place_graph.py::RUF007                 <- RM-1
  tests/test_p4_place_graph.py::RUF046                 <- RM-1
  attributable to DR-1 (pose*) : []                    <- ZERO
```

Corroboration: (a) `ruff check` on all three DR-1 python files returns *All
checks passed*; (b) `src/parcel_robot/route_memory/place_graph.py` — the module
whose new import block triggers the `I001` — opens with *"This is the RM-1 half
of the route-memory wiring"*; (c) both `place_graph.py` and
`tests/test_p4_place_graph.py` are untracked files that did not exist at DR-1's
session start; (d) the count grew from 8 to 11 *during* this card's execution as
RM-1 kept writing.

DR-1 contributes **zero** new ruff fingerprints. With RM-1's in-flight files
excluded the ratchet is back at baseline. DR-1's own gate obligation is met; the
ruff gate closes when RM-1 lands (`ruff check --fix` on their two files).

## 8. Files touched

- `src/parcel_robot/pose.py` — additive (+219 / −1, the one line being
  `_var_xy += var_trans` → `+ slip_var`)
- `configs/navigation/pose.yaml` — additive (+163 / −0); five new profiles
- `tests/test_pose_drift_calibration.py` — additive (+161 / −0); 13 new cases
- `tests/test_pose_degraded_profiles.py` — NEW; 56 cases
- `scrum/20260811/task_2/DR1_STATUS.md` — this doc

Net new tests: **69** (56 + 13). Suite 3668 → 3737, 0 failures.

MUST-NOT-TOUCH honored: no edit to `runtime.py`, `navigation/**`, `evals/**`,
`headless_city.py`, `route_memory/**`. RM-1 is concurrently modifying
`src/parcel_robot/route_memory/{__init__,memory,teach_repeat}.py`; those are
theirs and are untouched by DR-1.

## 9. Notes / does_not_prove

- The plan's recon says pose.yaml has "6 profiles". The file actually defines
  **five** named profiles plus the `truth` top-level default (six selectable
  configurations). All six are pinned. Stated for the auditor rather than
  silently reconciled.
- These profiles are a stand-in for leg odometry, **not a model of one**. The
  measurements prove the injector produces drift of a stated magnitude; they do
  not prove any of it resembles a real Go2 on real terrain.
- The `k = 2` / `k = 4` multipliers and the two slip constants are declared
  engineering tier choices, not published measurements. They must never be tuned
  against a downstream eval gate.
- Slip covariance uses the **expected** per-axis contribution
  (`rate · trans · m²/2`) rather than the realized jump, matching the convention
  the alpha terms already use — covariance reports uncertainty, not realized
  error. Exactly `0.0` when slip is off.
- No claim is made about downstream navigation behavior under any profile. That
  is DR-2's measurement, on DR-2's substrate.
