# E6 STATUS — OWNER-BAND SEPARATION (owner-authorized)

**Lane:** E6. **Authorization:** owner — the follow-up card lane E5 wrote up in
its §7.1 and correctly declined to attempt (its own card forbade touching
`apply_reactive_safety`). **Uncommitted, as instructed.**
**Input:** `E5_PERSON_CLEARANCE_STATUS.md`, re-verified rather than re-derived.

**Verdict: the separation is LANDED, the gate is GREEN, pedestrian clearance did
not move by a single float — and `follow_success` is 7/9, not 9/9.**

The card's headline gate (9/9) is **NOT MET**, and this document says so with the
factorial that shows why it is not reachable this way. Only one of the three lost
episodes was ever an owner-band episode. It is recovered. The other two are the
STRANGER band's cost, i.e. the same 0.17 m of pedestrian clearance E5 bought —
buying those rows back means selling that clearance, and that is the owner's
decision, not this lane's.

| | E5 (in) | E6 (out) |
|---|---|---|
| `follow_success` | 6/9 | **7/9** |
| `min_pedestrian_surface_m` | 0.5300 | **0.5300** (unchanged, bit-identical) |
| `personal_space_time_total_s` | 2.3 | **2.3** (unchanged) |
| `hard_collision_total` / `pedestrian_contact_total` | 0 / 0 | **0 / 0** |
| `navigate_success` | 2/2 | **2/2** |
| `false_arrival` | 0 | **0** |

---

## 1 — What landed

| # | Change | File |
|---|---|---|
| 1 | `ReactiveSafetyPolicy.owner_slow_m` — a **derived, unconfigurable property**: the owner's comfort band | `navigation/reactive_safety.py` |
| 2 | `_owner_identity_trusted` — the fail-closed owner-identity predicate | `navigation/reactive_safety.py` |
| 3 | `_owner_comfort_band_m` — identity + the two-body interlock, returning which band this tick | `navigation/reactive_safety.py` |
| 4 | `apply_reactive_safety` — the `people` list carries a per-person BAND; the stop distance stays one shared value | `navigation/reactive_safety.py` |
| 5 | `__post_init__` — the derived band must leave a real ramp outside the shared stop ring | `navigation/reactive_safety.py` |
| 6 | `OWNER_STAND_OFF_MARGIN_M` moved here (follow.py imports it); `FollowConfig.min_confidence` derived by reference from `OWNER_IDENTITY_CONFIDENCE_MIN` — **both values unchanged** | `reactive_safety.py`, `follow.py` |

No config file was touched. E5's `1.2 / 2.5` stays exactly as it settled it, in
all four `robot*.yaml` copies.

---

## 2 — The owner band, DERIVED (§ the card's guardrail 3)

The gate reasons in **clearance** (owner *center* distance minus
`owner_collision_envelope_m`); the follow controller reasons in **center**
distance. Converting the controller's own stand-off into the gate's coordinates,
the envelope cancels:

```
owner_slow_m = desired_distance_m                                    - envelope
             = (owner_keepout_m + OWNER_STAND_OFF_MARGIN_M)          - envelope
             = (person_stop_m + envelope + OWNER_STAND_OFF_MARGIN_M) - envelope
             = person_stop_m + OWNER_STAND_OFF_MARGIN_M
             = 1.2 + 0.10   = 1.30 m clearance   (= 1.85 m center)
```

Both input terms are E5's, unchanged: `owner_keepout_m = person_stop_m +
owner_collision_envelope_m` and `desired_distance_m = owner_keepout_m +
arrival_radius_m + stand_off_margin_m`.

**Why that margin.** It is not chosen here at all — it is the margin the
authority *already* puts between a minimum-clearance ring and the stand-off that
wraps it (`StandOffEnvelope`: `stand_off(r) - minimum_vicinity(r) ==
arrival_radius_m + stand_off_margin_m`), which is exactly the pair E5 used one
ring further out. So the owner's comfort ramp occupies **exactly the stand-off
margin**: the 10 cm of slack between the keepout ring and the formation the dog
is trying to hold.

Read as behaviour: *holding the formation is not throttled; closing inside the
formation eases off; at the keepout ring the same hard stop as any stranger
fires.* It is E5's own defect ("a stand-off must not sit inside its own
keepout") applied to the comfort band instead of the stop.

The identity in IEEE-754 is exact and is asserted with `==`, not `approx`:
`owner_slow_m + owner_collision_envelope_m == FollowConfig().desired_distance_m`
→ `1.85 == 1.85`.

**Not exposed.** `owner_slow_m` is a `@property`, not a dataclass field:
`ReactiveSafetyPolicy(owner_slow_m=...)` raises `TypeError`. It is clamped by
`person_slow_m` so no commissioning can give the owner a *wider* band than a
stranger, and `__post_init__` refuses a policy whose derived band would collapse
onto the stop ring.

---

## 3 — Who gets it: fail closed, twice (§ guardrails 1 and 4)

`_owner_comfort_band_m` returns the relaxed band only when **both** hold; every
other path returns `policy.person_slow_m` (2.5 m).

**(a) Identity.** `_owner_identity_trusted(owner)` requires a non-blank
`owner_id` **and** a finite `confidence >= OWNER_IDENTITY_CONFIDENCE_MIN`. Never
"the nearest person", never an unlabeled track. The threshold is not invented
here: it is the value the stack already uses to answer the same question, and
`FollowConfig.min_confidence` and `SearchOwnerConfig.owner_confidence_min` are
asserted equal to it (all 0.65, unchanged). It is deliberately a module-level
**floor** rather than a policy field — a commissioning file may lower a
*controller's* willingness to act on a weak track, but it must not widen the set
of tracks that get relaxed clearance from the final gate.

Note the default `OwnerTrack` carries `confidence=0.0`, so **every** track that
does not positively assert an identity already fails closed.

**(b) Two-body interlock.** No stranger on the person channel *at all*. The
relaxation is a two-body contract: the owner chose to walk beside the dog; a
bystander did not, and cannot consent on the dog's timetable. While any stranger
is perceived, the social band governs the whole command — including the part of
it chasing the owner. The dog therefore lags its owner in a crowd. That is the
intended reading of the rule, not a defect.

**The range-based version of this interlock was built first and REJECTED BY
MEASUREMENT** — see §4.2. A presence test also has no free parameter to tune,
which is the strongest available answer to "derivation over exposure", and it
makes the central safety claim true *by construction*: in every episode where a
pedestrian is perceived, this gate is the same function E5 measured.

**What the owner's band cannot do**, bounded exactly: it moves ONE band, for ONE
entry in the people list, between 1.30 m and 2.50 m of owner clearance. It cannot
touch the stop ring, the predictive stop, the TTC brake, the orbit gate, the
collision gate, the obstacle path, or any stranger entry.

**Residual, flagged not fixed:** `nearest_person_m is None` cannot distinguish
"nobody there" from "no person channel", so a deployment with no person sensing
reads as two-body. Bounded by the paragraph above (worst case: the dog closes on
*its own owner* to 1.85 m of center distance before the same hard stop as ever)
and by P0-B, which already refuses to translate when the scan channel is missing.
Widening the test to `dynamic_agents` is the obvious extension seam and belongs
to a card that owns that channel.

---

## 4 — Measurement (FOLLOW_BENCH_V1, all 11 scenarios)

Official row: `follow-bench-v1-20260811023618Z-93eba090.json`.

### 4.1 Before / after

| metric | E5 (in) | E6 (out) | direction |
|---|---|---|---|
| `follow_success` | 6/9 | **7/9** | +1 episode |
| `min_pedestrian_surface_m` | 0.5299999999999998 | **0.5299999999999998** | identical |
| `personal_space_time_total_s` | 2.3 | **2.3** | identical |
| `intimate_space_time_total_s` | 0.0 | **0.0** | identical |
| `hard_collision_total` | 0 | **0** | identical |
| `pedestrian_contact_total` | 0 | **0** | identical |
| `reactive_gate_stop_total` | 2 | **2** | identical |
| `navigate_success` | 2/2 | **2/2** | identical |
| `mean_band_fraction` | 0.6398553712083124 | **0.708782386458857** | +0.069 |
| `mean_rms_commanded_jerk_mps3` | 0.8918 | **1.2187** | +37 %, not gated |

Per episode (`thr` = the scenario's own `min_band_fraction`):

| episode | thr | band E5 -> E6 | min ped surface E5 -> E6 |
|---|---|---|---|
| `straight_follow` | 0.9 | 1.0 -> 1.0 ✓ | – |
| `follow_turn_corner` | 0.3 | 0.3417 -> **0.4958** ✓ | – |
| `owner_stops` | 0.9 | 1.0 -> 1.0 ✓ | – |
| `pedestrian_group` | 0.75 | 0.584 -> 0.584 ✗ | 1.4335847533578658 -> **same** |
| `doorway_gap` | 0.7 | 1.0 -> 1.0 ✓ | – |
| `pedestrian_cut_in` | 0.6 | 0.525 -> 0.525 ✗ | 1.4073609461551488 -> **same** |
| `navigate_crossing_ped` | – | – | 0.5299999999999998 -> **same**, dwell 2.3 -> **same** |
| `owner_turn_90` | 0.8 | **0.500 -> 0.9529** ✗ -> ✓ | – (no pedestrians) |
| `pedestrian_cut_in_predictive` | 0.6 | 0.7154 -> 0.7154 ✓ | 0.818256373512604 -> **same** |
| `owner_corner_loss` | 0.0 | 0.0926 -> **0.1059** ✓ | – |
| `navigate_near_wall` | – | arrived -> arrived | – |

**Every episode containing a pedestrian re-measures bit-identical**, to the last
digit of the float. That is the interlock's design intent showing up as evidence
rather than as an argument. The only recovered episode, `owner_turn_90`, is
exactly the one E5 proved was owner-only: it contains **zero pedestrians**.

### 4.2 The factorial: why 9/9 is not reachable through the owner band

Owner band swept with the interlock **OFF** — the most favourable case for
following, and the widest give-back of pedestrian clearance. All cells measured
today on this tree, all 11 scenarios, via a single patch point
(`_owner_comfort_band_m`); strangers keep 2.5 m in every cell.

| cell | owner band | `follow_success` | `mean_band_fraction` | `min_pedestrian_surface_m` | dwell | `pedestrian_group` |
|---|---|---|---|---|---|---|
| **none** (= E5, control) | 2.50 | 6/9 | 0.6398553712083124 | **0.5300** | 2.3 | 0.584 ✗ |
| n2.0 | 2.00 | 7/9 | 0.7119047259929613 | 0.3824 | 3.8 | 0.636 ✗ |
| n1.75 | 1.75 | 8/9 | 0.7413622423328305 | 0.2182 | 4.0 | 0.652 ✗ |
| **derived** | 1.30 | 8/9 | 0.7458251215015921 | 0.1794 | 4.1 | 0.652 ✗ |
| range interlock (2.5 m ring) | 1.30 | 7/9 | 0.7297396514161220 | 0.2810 | 3.9 | 0.588 ✗ |
| **SHIPPED** (two-body interlock) | 1.30 | **7/9** | 0.7087823864588570 | **0.5300** | **2.3** | 0.584 ✗ |

`hard_collision_total` is **0** and `pedestrian_contact_total` is **0** in every
cell above. The control cell reproduces E5's shipped row exactly (6/9,
0.6398553712083124, 0.5300, 2.3), which is what validates the harness.

Read the columns:

* **`pedestrian_group` fails in every single cell** (0.584 / 0.636 / 0.652 /
  0.652 / 0.588 / 0.584 against a 0.75 threshold). No owner band at any value
  recovers it. It is not an owner-band episode; E5's cell A recovers it only by
  moving the STRANGER band back to 2.0 m.
* `pedestrian_cut_in` *can* be recovered (0.615-0.625 at bands 1.30-1.75) — but
  only by relaxing the owner *in a pedestrian's presence*, which is precisely
  what costs the clearance.
* **Pedestrian clearance falls monotonically as the owner band is relaxed with
  the interlock off**: 0.5300 -> 0.3824 -> 0.2182 -> 0.1794. Guardrail 2 is
  violated by every one of those cells.
* The shipped design sits **off that curve**: it buys the same follow row as the
  2.00 cell while giving back **nothing**.

### 4.3 Why a range-based interlock was rejected — traced, not guessed

The obvious interlock ("withdraw the relaxation while a stranger is inside
`person_slow_m`") was implemented and measured first: 7/9, but
`min_pedestrian_surface_m` **0.2810** and dwell 3.9 s. Guardrail 2 violated.

The step trace of `pedestrian_cut_in_predictive` says why, and it is not what a
band argument would predict. At the moment of closest approach **the robot is
stationary in both cells** (`command_vx == 0.000` from t≈15.2 s, halted by the
prediction-confidence brake, not by the proximity gate). What differs is *where*
it is standing: `x = -2.34` under E5, `x = -1.80` with the relaxation — 0.54 m
further up the corridor, which is 0.54 m deeper into a scripted, non-reactive
pedestrian's path. The give-back is not a throttle that fired late; it is
accumulated displacement from *before* the pedestrian was anywhere near a ring.
No ring fixes that. Choosing one that happened to hold the bench would have been
fitting a safety constant to an eval — the exact thing E5 refused to do.

---

## 5 — Every moved pin, with 2x2 attribution

2x2 convention: *old-code* = this working tree at the end of lane E5;
*new-code* = that tree plus this lane. The pre-E6 file was reconstructed by
**reverse-applying this lane's own edits** to the live file, so the "old code"
column is this tree minus this lane, not a retyped guess.

### Pin 1 — `REACTIVE_SAFETY_PIN["apply_reactive_safety"]` (`tests/test_dynamic_layer.py`)

* **old** `1f46251c2b9ea072081bfc8d094b19fdc01e5682eac598540a9459815505a505`
* **new** `f52db9c50cd6efe3958471a87d7f53e7ef3ba7b0038c895422dd0d7a4cf6bded`

| | old pin (`1f46251c…`) | new pin (`f52db9c5…`) |
|---|---|---|
| **old code** | **MATCH** — measured on both `HEAD:reactive_safety.py` *and* the reconstructed pre-E6 file: `1f46251c…` in both. E5's claim that the gate function never moved is confirmed independently, not taken on trust. | **mismatch** — the band-separation block does not exist there |
| **new code** | **mismatch** — the observed initial red on this lane (`apply_reactive_safety: f52db9c5… != pinned 1f46251c…`) | **MATCH** — regenerated with the command in the pin's own docstring; `tests/test_dynamic_layer.py` 34 passed |

**Attribution: the owner-band separation, and nothing else.** The delta inside the
symbol is exactly (a) the `people` tuple growing a third element, the per-person
comfort band, (b) the stranger entry being handed `policy.person_slow_m`
explicitly, (c) the owner entry being handed `_owner_comfort_band_m(...)`, and
(d) the ramp reading the per-person band instead of `policy.person_slow_m`. The
stop line above it — `person_distance <= predictive_person_stop` with
`predictive_person_stop = policy.person_stop_m + speed * reaction_time_s` — is
character-for-character unchanged, which is what guardrail 1 asks for.
This is the **first authorized change to this symbol in the whole batch.**

### Pin 2 — `REACTIVE_SAFETY_PIN["ReactiveSafetyPolicy.__post_init__"]`

* **old** `4c07dc077c2eb6999b46ce8a89998ce1cd73e11ed0d566ab0130f5d2285afba2`
* **new** `e01bcca941f8b8ed1448a62b066246235682941e8ff94e5c2927de7e8c47684e`

| | old pin (`4c07dc07…`) | new pin (`e01bcca9…`) |
|---|---|---|
| **old code** | **MATCH** — the reconstructed pre-E6 file digests to `4c07dc07…`, i.e. E5's re-freeze named a state that really existed (`HEAD` is still `2be49ad0…`, also confirmed) | **mismatch** — the owner-band guard is not there |
| **new code** | **mismatch** — the second half of this lane's initial red | **MATCH** — `ci_gate` green |

**Attribution: one added guard, four lines of code.** `owner_slow_m <=
person_stop_m` now refuses construction. E5's symmetric person floor is
untouched and still above it. The guard is reachable only through an authority
whose stand-off margin is zero; it is tested by monkeypatching
`OWNER_STAND_OFF_MARGIN_M` to `0.0` and asserting `ReactiveSafetyPolicy()`
raises.

### Pin 3 — three symbols ADDED to `REACTIVE_SAFETY_PIN`

`ReactiveSafetyPolicy.owner_slow_m` `119af4ad…`, `_owner_comfort_band_m`
`7d5050eb…`, `_owner_identity_trusted` `5262d3ed…`.

Not a re-freeze — a widening. The gate's safety decision now lives partly in
helpers, and a ratchet watching only the caller would have been **weaker after
this change than before it**. The 2x2 is degenerate by construction (the symbols
do not exist in old code), which is itself the argument for adding them: nothing
was moved out of the ratchet's sight.

### Pin 4 — FOLLOW_BENCH_V1 latest-shipped row (`results/ledger.jsonl` + `FOLLOW_BENCH_POST_SPEED`)

* **old** `follow_success 6/9`, `mean_band_fraction 0.6398553712083124`,
  `mean_rms_commanded_jerk_mps3 0.8918`, report `…20260811020631Z-2f7bbb07.json`
* **new** `follow_success 7/9`, `mean_band_fraction 0.708782386458857`,
  `mean_rms_commanded_jerk_mps3 1.2187`, report `…20260811023618Z-93eba090.json`
* `hard_collision_total 0` and `navigate_success 2/2` unchanged in both.

| | old pin (6/9) | new pin (7/9) |
|---|---|---|
| **old code** | **MATCH** — re-measured today as the factorial's control cell: 6/9, `0.6398553712083124`, `0.5300`, 2.3, collisions 0 | **mismatch** — 6/9 ≠ 7/9 |
| **new code** | **mismatch** — the red `tests/test_duplex_v1.py::test_nav_regression_pins_post_speed_raise_rows` produces | **MATCH** — `ci_gate` green; `hard-safety` reports follow-bench rows with `hard_collision_total` all 0 |

**Attribution: `owner_turn_90` alone, and this lane alone.** The +1 is one
episode, 0.500 -> 0.953, in a scenario with no pedestrians; §4.1 shows the other
eight follow episodes and all five pedestrian metrics unmoved. The ledger is
append-only and the append-only prefix is untouched.

Note the ledger's `mean_band_fraction` re-measures exactly (`0.6398553712083124`
in the control cell = E5's pinned value), so E5's caveat about a 5th-decimal
band drift did **not** recur here. E5's *other* caveat stands and is still
unowned: `mean_rms_commanded_jerk_mps3` drifted ~58 % before either lane touched
it. This lane adds a real, attributable +37 % on top (0.8918 -> 1.2187): the dog
now accelerates to hold formation instead of being throttled into it. It is not
gated, and it is reported rather than buried.

### Not re-pinned (deliberately)

* `evals/companion/embodied_plan_v1/manifest.json`, `personal_convo_v1`,
  `evals/nav_instruct/episodes/v3/manifest.json` — **no config file was touched
  by this lane**, so no locked input's hash moved. The three
  `DIGEST_SENTINELS` are byte-identical to their pins and `scripts/ci_gate.py`
  needed no edit at all.
* `PINNED_FROZEN_FALSE_ARRIVAL = 0` and the nav_instruct frozen baseline —
  untouched; `ci_gate` reports `collisions=0 false_arrival=0`.
* `tests/test_embodied_plan_eval.py`'s behavioural pins — untouched, nothing
  moved.
* No locked file's *content* was altered to make a pin fit.

---

## 6 — Tests added

`tests/test_e6_owner_band.py`, 25 tests. The two the card names explicitly:

* **`test_an_unidentified_person_receives_the_stranger_band`** (6 parametrised
  cases: no confidence at all, one ulp under the threshold, a plausible-but-
  unconfirmed 0.5, an empty label, a whitespace label, a NaN confidence). Stated
  *behaviourally*, not by reading the predicate: at 1.65 m of clearance an
  identified owner runs unthrottled at `vx = 0.35`, while every track in the
  table is slowed to exactly the stranger ramp `(1.65 - 1.2) / (2.5 - 1.2)`.
* **`test_the_owners_hard_stop_is_bit_identical_to_a_strangers`**. The stop ring
  is **measured by bisecting the gate's own verdict** (80 iterations), at three
  speeds, for an identified owner and for an unidentified person, and the two
  rings are asserted equal to each other *and* to
  `person_stop_m + v * reaction_time_s`. A relaxation hidden anywhere in the stop
  path — the ring, the speed term, or the new identity branch — moves a number
  here.

The rest: the derivation asserted with `==` against `FollowConfig`; the band is a
property and cannot be constructed; the clamp under a tight `person_slow_m`; a
zero stand-off margin refusing construction; the three owner-confidence
thresholds asserted equal; the TTC brake proved identity-blind; the stranger ramp
proved unchanged at five distances; an exhaustive sweep of the band decision
proving it always returns one of two values, both strictly outside the stop ring;
and the presence-not-range interlock proved with a stranger 40 m away.

---

## 7 — Gate

| requirement | result |
|---|---|
| `follow_success` back to 9/9 | **NO — 7/9.** 6/9 -> 7/9. Reported with the factorial in §4.2 that shows 9/9 is not reachable through the owner band at any value, because `pedestrian_group` fails in every cell. Not massaged, not silent. |
| `person_slow_m` still 2.5 for strangers | **yes** — no config touched; the stranger band is `SafetyEnvelope.person_comfort_band_m` as E5 left it |
| band metric reported | **yes** — `mean_band_fraction` 0.63986 -> 0.70878 |
| `min_pedestrian_surface_m` >= 0.5300 | **yes — 0.5299999999999998, the identical float** |
| dwell <= 2.3 s | **yes — 2.3, identical** |
| collisions 0 | **yes** |
| pedestrian contacts 0 | **yes** |
| `false_arrival` 0 | **yes** — nav frozen baseline unchanged and untouched |
| a test proving an UNIDENTIFIED person gets the stranger band | **yes** — §6, 6 parametrised cases |
| a test proving the owner's hard stop is still 1.2 m | **yes** — §6, measured by bisection at three speeds |
| `apply_reactive_safety` pin regenerated deliberately, with log + 2x2 | **yes** — §5 pin 1, inline log in `tests/test_dynamic_layer.py` |
| every moved pin re-frozen with 2x2 | **yes** — §5, four entries |
| `scripts/ci_gate.py --tier commit` | **PASS** (see below) |
| ruff | **clean** |

```
CI GATE — tier=commit  (2026-08-11T02:53:26Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …20260809T161252Z: collisions=0 false_arrival=0 |
                                          mutation panel clean: collisions=0 no_false_arrival=True |
                                          follow-bench: 7 row(s), hard_collision_total all 0 = True |
                                          walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    3 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling (rows=5)
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   1 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3365 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.
```

`3365 = 3340 + 25`: the coordinator-verified baseline plus exactly this lane's
new test file. No existing test was deleted, weakened, or re-baselined; the
`REACTIVE_SAFETY_PIN` edit is a regeneration inside a kept test, not a removal.
`ruff check` is `All checks passed!` on all five touched Python files.

### 7.1 — Two `@pytest.mark.slow` failures found, NEITHER caused here

Running the suite with no marker filter (3380 tests, i.e. the 40 `slow` ones the
commit tier deselects) surfaces two reds. Both are outside the commit gate, and
neither is this lane's:

* `tests/test_mutation_panel_freshness.py::test_mutation_panel_runs_on_the_current_frozen_set_live`
  — the LIVE panel re-run reports `clean_checks.no_false_arrival is False`.
  **A/B'd directly:** with `_owner_comfort_band_m` forced to return the stranger
  band (an exact emulation of the pre-E6 gate, installed and then reverted), the
  test fails **identically**. Pre-existing on this working tree. Note the
  committed panel artifact still reads `no_false_arrival: True` and is what the
  commit gate checks — so the frozen artifact and a live re-run now disagree.
  That is the exact class of rot that test was written to make loud, and it is
  loud. It belongs to whoever owns the nav_instruct frozen set; flagged, not
  touched (`evals/nav_instruct/episodes/**` is in this lane's MUST-NOT-TOUCH).
* `tests/test_runtime_activation.py::test_camera_ingress_live_owlv2_localizes_object`
  — a live OWLv2 model test in `camera_channel` territory, untouched by this
  lane and also in MUST-NOT-TOUCH.

---

## 8 — Files touched

| Path | Change |
|---|---|
| `src/parcel_robot/navigation/reactive_safety.py` | `OWNER_STAND_OFF_MARGIN_M` (moved here) + `OWNER_IDENTITY_CONFIDENCE_MIN`; `ReactiveSafetyPolicy.owner_slow_m` derived property; `__post_init__` band guard; `_owner_comfort_band_m`; `_owner_identity_trusted`; per-person comfort band in `apply_reactive_safety` |
| `src/parcel_robot/navigation/follow.py` | imports the margin and the identity threshold instead of restating them (both values unchanged); the now-unused `DEFAULT_STAND_OFF_ENVELOPE` import dropped |
| `tests/test_e6_owner_band.py` | **new**, 25 tests |
| `tests/test_dynamic_layer.py` | `REACTIVE_SAFETY_PIN` regenerated (2 symbols) and widened (3 symbols) + inline regeneration log + the docstring's regeneration command |
| `evals/companion/duplex_v1/run_duplex_v1.py` | `FOLLOW_BENCH_POST_SPEED` 6/9 -> 7/9 + the attribution block |
| `evals/companion_nav/results/ledger.jsonl` (+ new report json) | one appended row; the append-only prefix untouched |
| `scrum/20260809/task_15/E6_OWNER_BAND_STATUS.md` | this file |

Nothing in MUST-NOT-TOUCH was edited: no `configs/**` yaml, `instructnav/**`,
`camera_channel/**`, `detection_adapter/**`, `evals/nav_instruct/episodes/**`,
`runtime.py`, or the `value_map` / `detection_lock_on` feature code.
`scripts/ci_gate.py` needed no edit — no sentinel bytes moved. **Nothing
committed.**

---

## 9 — The decision this leaves with the owner

`follow_success` 9/9 is available, and its price is measured:

| option | `follow_success` | `min_pedestrian_surface_m` | dwell |
|---|---|---|---|
| **shipped (E6)** | 7/9 | **0.5300** | **2.3 s** |
| stranger band back to 2.0 m (E5 cell A/G) | 9/9 | 0.3824 | 3.8 s |
| owner band relaxed in company (interlock off, 1.30 m) | 8/9 | 0.1794 | 4.1 s |

The two rows E6 does not recover are bought with pedestrian clearance, not with
engineering. That is a product decision about a real trade, and it is the
owner's.

---

## does_not_prove

* Does **not** prove 7/9 is acceptable. Two follow-bench episodes remain red,
  and this lane's own factorial says the only lever left for them is the
  stranger band E5 was authorized to widen.
* Does **not** prove the two-body interlock is right for a crowded street. It
  means the dog lags its owner whenever anyone else is perceived; FOLLOW_BENCH_V1
  contains no scenario where that is the dominant condition for a long stretch.
* Does **not** prove the owner band generalises past an oracle owner track. The
  bench's owner is a geometric visibility ray with `confidence == 1.0`; a real
  re-ID pipeline would sit under `_owner_identity_trusted` and its false-positive
  rate becomes the relaxation's false-positive rate. That predicate is the seam
  to test when a real one lands.
* Does **not** prove anything about a deployment with no person channel: §3's
  residual is bounded, not eliminated.
* Does **not** re-measure nav_instruct, the mutation panel, or the embodied plan
  from scratch; no locked input moved, so all three are read from their existing
  frozen artifacts.
* Does **not** prove the mutation panel is healthy. §7.1 found the live panel
  disagreeing with its own committed artifact on `no_false_arrival`, and proved
  only that E6 did not cause it.
* Does **not** prove hardware behaviour: every number here is the headless
  kinematic city block, and FOLLOW_BENCH_V1's own `does_not_prove` list applies
  in full — in particular its pedestrians follow fixed scripts and never yield,
  which is exactly what makes §4.3's stationary-robot near-miss a bench artifact
  worth reading twice.
