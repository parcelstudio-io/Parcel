# E2 STATUS — SAFETY WIRING TRUTH

**Lane:** E2 (sole `runtime.py` owner this wave)
**Input:** Fable independent audit `wf_00b0c758-4e3`, three defects where the
published CONTRACT and the live WIRING disagree.
**Batch under repair:** `6bd945d`. **Uncommitted, as instructed.**

**Verdict:** defects 1 and 2 **FIXED and wired**. Defect 3 is **SPLIT**: the
envelope-derived fallbacks landed; the symmetric guard + `robot.yaml` retune are
**STOPPED under rule 2 and owner-gated** — turning them on moves a frozen row
(FOLLOW_BENCH_V1 `follow_success` **9/9 -> 6/9**, measured) and breaks the
SHA-locked `robot_config` input of the frozen `embodied_plan_v1` manifest.

**No safety weakening anywhere in this lane.** Every landed change is neutral or
strictly stricter. The one strictly-more-conservative change (stopping 0.2 m
farther from people) is precisely the one that is owner-gated, because it costs
a frozen row.

---

## 1 — P0-B now actually LATCHES

### Before (the defect)

`runtime.py` `_collision_safe`, one line:

```python
health = self._evaluate_dispatch_input_health(observation, now=decision_now)
self._input_health_latched = bool(health.stop_latched)   # a MIRROR, not a latch
```

A `LATCHED_STOP` cleared itself the instant the input recovered. One malformed
tick followed by one healthy tick silently re-authorized translation. That
contradicts the frozen contract at `S-A_STATUS.md:57` ("if `verdict.stop_latched`:
latch STOP") and the `HealthAction.LATCHED_STOP` name itself.

### After

```python
if health.stop_latched:
    self._input_health_latched = True                    # only ever SETS
    self._input_health_latch_faults = tuple(...)         # why, for the operator
translation_allowed = health.translation_allowed and not self._input_health_latched
```

`translation_allowed` (not the raw verdict) now drives both the translation zero
and the `proximity_state == "stopped"` promotion, so a latched runtime reports
`stopped` even on a tick whose join says ALLOW. `_finalize_for_actuator` already
routed `_input_health_latched` to `HARD_STOP`, so the latch reaches `set_target`
as exact `(0,0,0)`.

### The clear path

`RobotRuntime.clear_input_health_latch(*, now=None) -> str` — an explicit
operator acknowledgement, and the **only** clear. It is **refused while the
fault is still live**: it re-evaluates the join against the current observation
and returns `"input health still latched: pose:timestamp_in_future, ..."`
without clearing, so acknowledging a live fault can never re-authorize motion
into a broken sensor. `clear_emergency_stop()` calls it (the operator ack that
clears an e-stop is the same ack), so the existing operator surface reaches it
with no new control flow.

`RobotRuntime.input_health_latch() -> dict` is the inspection surface:
`{"latched", "faults", "sim_fixture_inputs_allowed", "require_physical_inputs"}`.

### Gate evidence

`tests/test_e2_safety_wiring.py`:

| Test | Proves |
|---|---|
| `test_latched_stop_survives_a_single_tick_recovery` | future-dated evidence latches; **one tick later the join returns `ALLOW`** and translation is still zero, `proximity_state == "stopped"`, `_finalize_for_actuator(...) == ZERO_COMMAND` |
| `test_latch_clear_is_refused_while_the_fault_is_still_live` | ack refused, latch held |
| `test_operator_acknowledgement_is_the_only_clear` | after ack: cleared, second ack is a no-op, and `vx=0.4` flows again (`state == "clear"`) |

Pause/resume + N14 resume-transaction: **green** —
`tests/test_closed_intent_product_path.py`, `tests/test_k6_voice_lanes.py`,
`tests/test_sa2_live_pipeline.py`, `tests/test_core_input_health.py`,
`tests/test_core_hard_stop.py` = **211 passed** together with this lane's file.

---

## 2 — simulated inputs are labeled fixtures, not "PHYSICAL"

### Before (the defect)

`_evaluate_dispatch_input_health` stamped POSE and CONTROLLER_FEEDBACK
`origin=InputOrigin.PHYSICAL` **unconditionally**, while SCAN correctly routed
through `scan_evidence_from_observation`. Under `DEFAULT_REQUIRED_INPUTS`, POSE
and CONTROLLER_FEEDBACK have `sim_fixture_allowed=False` — that check exists
exactly to catch stub geometry satisfying a physical-sensor requirement (P0-B's
core promise), and hard-coding `PHYSICAL` made it unreachable.

### After

One shared stamper in `core/input_health.py`, used by every channel:

```python
PHYSICAL_SOURCE_NAMES = frozenset({"", "unknown", "physical"})
def is_simulated_source(source) -> bool          # exact match, fails CLOSED
def evidence_origin(source) -> (InputOrigin, str | None)
def requirements_allowing_sim_fixtures(reqs=DEFAULT_REQUIRED_INPUTS)
```

* POSE is stamped from `observation.backend`.
* CONTROLLER_FEEDBACK is stamped from `RobotMotionState.source` (the producing
  controller/backend — `observation.backend` on the sim path, the vendor channel
  name on hardware).
* SCAN's own predicate was **deleted and replaced by a call to the same helper**,
  so no channel can hard-code `PHYSICAL` again.

Matching is deliberately **not** case- or whitespace-normalised: `"Physical"` is
an unrecognised producer and therefore a fixture, i.e. it fails closed.

**The refactor is behaviour-identical to the old SCAN predicate** — verified on
`['', 'unknown', 'physical', 'mujoco', 'Physical', 'UNKNOWN', ' physical ',
'sa2-live-pipeline', None]`: **0 mismatches**. AST digest of
`apply_reactive_safety` is `1f46251c…` = unchanged from `6bd945d`.

### Commissioning, not a blanket allowance

`DEFAULT_REQUIRED_INPUTS` is untouched: pose/feedback fixtures are still
forbidden there. A runtime commissioned against a simulator (control manager
built from config, where `control.controller` is *required* to be `"simulator"`,
or a simulated backend name) uses `requirements_allowing_sim_fixtures()`, which
relaxes **who may produce** a sample and never **what makes it healthy**. New
hardware-readiness switch `safety.require_physical_inputs: true` withdraws the
allowance everywhere (read via `.get`, not added to any yaml — no config-schema
surface change).

### Labeling proof (measured, not asserted)

```
deployment:        {'sim_fixture_inputs_allowed': True, 'require_physical_inputs': False}
pose origin:       (InputOrigin.SIM_FIXTURE, 'sa2-live-pipeline')
feedback source:   'sa2-live-pipeline' -> (InputOrigin.SIM_FIXTURE, 'sa2-live-pipeline')
scan:              origin=SIM_FIXTURE  fixture_label='sa2-live-pipeline'
verdict, sim-commissioned deployment : HealthAction.ALLOW
verdict, SAME evidence, DEFAULT_REQUIRED_INPUTS : HealthAction.LATCHED_STOP
```

Gate tests: `test_simulated_pose_and_feedback_carry_a_labeled_sim_fixture_origin`,
`test_simulated_pose_latches_under_physical_commissioning` (faults are exactly
`{sim_fixture_forbidden}` on exactly `{POSE, CONTROLLER_FEEDBACK}`),
`test_unlabeled_sim_fixture_pose_latches_even_where_fixtures_are_allowed`,
`test_requirements_allowing_sim_fixtures_only_relaxes_the_producer`.

**Frozen rows: UNMOVED.** Neither `evals/nav_instruct/**` nor
`evals/companion_nav/**` nor `headless_city.py` constructs a `RobotRuntime`
(`grep -rn "RobotRuntime" evals/nav_instruct/*.py evals/companion_nav/*.py
src/parcel_robot/headless_city.py` -> no hits), so defects 1 and 2 cannot reach
a frozen harness at all.

---

## 3 — person clearance: SPLIT (landed / owner-gated)

### Landed — envelope-derived fallbacks (zero behaviour change)

`runtime.py` and `headless_city.py` no longer restate the retired literals:

| Site | Before | After |
|---|---|---|
| `runtime.py` safety parse | `.get("person_stop_m", 1.0)` / `.get("person_slow_m", 2.0)` | `.get(..., DEFAULT_SAFETY_ENVELOPE.person_stop(0.0))` / `.get(..., DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m)` |
| `headless_city._reactive_safety_from_store` | same two literals | same derivation |

Behaviour is unchanged today because all four shipped configs still supply the
key explicitly; the change removes the class of defect where an absent key
silently reintroduces 1.0 m. Proven by
`test_the_runtime_person_clearance_defaults_derive_from_the_envelope` (no
`safety` section -> 1.2/2.5) and `test_no_hardcoded_one_metre_person_fallback_remains`.

### STOPPED under rule 2 — the guard + the yaml retune

Confirmed asymmetry (measured on `6bd945d`):

```
ReactiveSafetyPolicy(person_stop_m=1.0)    -> ACCEPTED
ReactiveSafetyPolicy(obstacle_stop_m=0.5)  -> REJECTED
DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)   == 1.2      (configs say 1.0)
DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m == 2.5   (configs say 2.0)
```

The guard cannot land alone (every `RobotRuntime` construction against the
shipped `configs/robot.yaml` would raise), so guard + retune are one bundle. The
retune is **also larger than the card states**: `person_stop_m` 1.0 -> 1.2 forces
`owner_follow.owner_keepout_m` 1.55 -> **1.75** in all four copies
(`runtime.py` requires `owner_keepout_m >= person_stop_m + owner_collision_envelope_m`
= 1.2 + 0.55), and forces `FollowConfig.person_stop_m/person_slow_m/owner_keepout_m`
in `navigation/follow.py` off their literals too.

I built that full bundle, measured it, and then **reverted it**. Measurements:

#### 2x2 attribution — FOLLOW_BENCH_V1 (all 11 scenarios, `--out` to scratch, committed ledger untouched)

| | old pin (2026-08-09 frozen row) | new measurement |
|---|---|---|
| **old code** (shipped 1.0/2.0) | `follow_success 9/9`, band 0.74334, jerk 0.6025, coll 0 | `follow_success 9/9`, band **0.74315**, jerk **0.9541**, coll 0, `min_pedestrian_surface_m` 0.3566, `personal_space_time_total_s` 3.8, `reactive_gate_stop_total` 4 |
| **new code** (1.2/2.5 + keepout 1.75) | — | `follow_success` **6/9**, band **0.63986**, jerk 0.8868, coll 0, `min_pedestrian_surface_m` **0.5300**, `personal_space_time_total_s` **2.3**, `reactive_gate_stop_total` 2 |

**Rows that move: `follow_success` 9/9 -> 6/9 and `mean_band_fraction` 0.7431 ->
0.6399.** `hard_collision_total` stays 0 and `navigate_success` stays 2/2.

Direction of the loss is understood, not mysterious: `owner_keepout_m` rises to
1.75 m while `owner_follow.desired_distance_m` stays **1.6 m**, so the follow
controller's target distance falls *inside* its own keepout ring and it brakes.
Recovering 9/9 would need `desired_distance_m` raised as well — a product
decision about how far behind the owner the dog walks, which is not this lane's
to make.

The same change is **strictly more conservative around people**:
`min_pedestrian_surface_m` 0.357 -> 0.530 m (+0.17 m) and personal-space dwell
3.8 s -> 2.3 s. This is a real capability/clearance trade, not a regression to
paper over.

#### Embodied plan v1 — behaviourally UNMOVED

Re-ran the full suite under the retune (via a scratchpad copy of the manifest;
**the committed manifest was never modified**, sha still
`33c662c8d3611f39bb1fc56dabbebb2c4c7c913a8499449107cd5add95c6e54f`):

```
simulator_step_count 997   collision 0   timeout 0   minimum_clearance_m 0.883147
per-case: 200 / 260 / 64 / 389 / 84        (pins: 997, 0.883147, median 200, mean 199.4)
```

Bit-identical to the frozen row. **But the retune still breaks this eval**, for a
provenance reason rather than a behavioural one: `manifest.json` SHA-locks
`configs/robot.yaml` at `f6468887…`, so `run_suite` raises
`EmbodiedPlanError: locked input robot_config failed SHA-256 verification`.
Re-freezing that manifest moves its own sha, which is a `DIGEST_SENTINELS` entry
in `scripts/ci_gate.py` — **MUST-NOT-TOUCH for this lane**. That alone makes the
yaml retune unlandable here, independent of follow-bench.

#### What landed instead — the disagreement pinned AS a disagreement

Same idiom `test_authority_config_drift.py` already uses for the 0.35-vs-0.32
radius, so the gap cannot be silently widened or silently "fixed":

* `test_the_obstacle_floor_guard_still_exists_and_the_person_one_does_not`
* `test_every_robot_config_copy_pins_the_person_clearance_disagreement` (all four
  copies asserted at 1.0/2.0 **and** asserted to be below the envelope)
* `test_the_runtime_constructed_policy_reflects_the_yaml_not_a_hidden_literal` —
  the RUNTIME-built policy, not the bare dataclass: no `safety` section -> 1.2,
  shipped 1.0 override -> 1.0

`ReactiveSafetyPolicy.__post_init__` carries a comment naming the bundle and
pointing here.

### Owner decision required

Land as ONE commit: symmetric `person_stop_m` guard + four yaml copies to
1.2/2.5 + `owner_keepout_m` 1.75 + `FollowConfig` literals derived + a
`desired_distance_m` decision + **FOLLOW_BENCH_V1 re-freeze (9/9 -> 6/9, or 9/9
recovered by the `desired_distance_m` retune)** + **embodied `manifest.json`
re-freeze** + the matching `DIGEST_SENTINELS` update in `scripts/ci_gate.py` +
flipping the three pinned-disagreement tests above.

---

## VERIFY

### ruff — clean

`ruff check` on all five touched files: **All checks passed.** Gate: `7
violation(s), baseline 7, new 0`.

### ci_gate --tier commit — ONE red, and it is NOT in this lane's files

```
[  PASS] ruff / hard-safety / frozen-digest-sentinels / model-off /
         frozen-digest-integrity / mutation-panel-freshness / latency-tail
[  FAIL] default-suite   1 failed, 3326 passed, 9 skipped, 34 deselected
   FAILED tests/test_dynamic_layer.py::test_the_reactive_safety_authority_is_pinned_not_merely_unmodified
```

(Baseline on this same shared tree before E2 touched anything: **PASS**, 3283
passed. Delta +43 passing = this lane's 15 plus other lanes' concurrent adds.)

#### Proof the red is a cross-lane pin race, not a defect in this lane

`tests/test_dynamic_layer.py` is **lane E3's file and MUST-NOT-TOUCH for E2**.
E3 pinned an AST digest of *my* file. They captured it during my measurement
window — while the person guard was transiently in the working tree — and
regenerated `REACTIVE_SAFETY_PIN["ReactiveSafetyPolicy.__post_init__"]` from
`2be49ad0…` to `4c07dc07…`, logging it as "lane **E2**'s symmetric
person-clearance guard". **That guard did not land** (rule-2 STOP above), so the
pin now names a state that exists in no commit and in no working tree.

Measured with E3's own `_symbol_digest`:

```
apply_reactive_safety:
   HEAD 6bd945d : 1f46251c…   live (E2): 1f46251c…   same_as_HEAD=True   E3 pin: 1f46251c…  MATCHES
ReactiveSafetyPolicy.__post_init__:
   HEAD 6bd945d : 2be49ad0…   live (E2): 2be49ad0…   same_as_HEAD=True   E3 pin: 4c07dc07…  MISMATCH
```

**`reactive_safety.py` is semantically identical to `6bd945d` on both pinned
symbols** — this lane's only edits to that file are comments plus the
behaviour-proven `evidence_origin` call. E3 anticipated exactly this
(`E3_EVAL_INTEGRITY_STATUS.md:240`, "FLAG for the coordinator... the ratchet will
redden again — by design. Regenerate... Do not delete the test.").

**Remedy (E3 / coordinator, one line, in E3's file):** revert
`REACTIVE_SAFETY_PIN["ReactiveSafetyPolicy.__post_init__"]` to
`2be49ad05223628fbe0b06a26ff57a4d1b6c5ca02f7a25eca4d0bae0f6dfc683` — the
committed HEAD value, i.e. E3's own first pin before the regeneration — and drop
the second bullet of the regeneration log. The gate is then fully green. E2 did
not touch that file and will not.

#### Also outside this lane

`tests/test_runtime_activation.py::test_camera_ingress_live_owlv2_localizes_object`
fails on this tree, `@pytest.mark.slow` and therefore **deselected by the gate**
(`-m "not slow"`). Cause is env-gated weights: `camera ingress requested but the
OWLv2 detector is unavailable (set PARCEL_OWLV2_ONNX=1 …)`. Not E2's.

#### Flagged for whoever owns follow-bench

On the **unchanged** config, today's baseline reproduces `follow_success 9/9` and
`mean_band_fraction 0.74315` (pin 0.74334) but
`mean_rms_commanded_jerk_mps3` **0.9541 vs the pinned 0.6025** — a ~58 % drift
present on this working tree *before* any E2 change. Not gated (ci_gate only
pins `hard_collision_total` for follow-bench) and not E2's, but it is real and
someone in this wave moved it.

---

## Files touched

| Path | Change |
|---|---|
| `src/parcel_robot/runtime.py` | real latch + `_input_health_latch_faults`; `clear_input_health_latch()` + `input_health_latch()`; `clear_emergency_stop()` calls the ack; backend-aware POSE/CONTROLLER_FEEDBACK stamping; `_input_health_requirements` commissioning; envelope-derived person fallbacks |
| `src/parcel_robot/core/input_health.py` | `PHYSICAL_SOURCE_NAMES`, `is_simulated_source`, `evidence_origin`, `requirements_allowing_sim_fixtures` |
| `src/parcel_robot/navigation/reactive_safety.py` | SCAN routed through the shared stamper; owner-gate comment on the missing person floor |
| `src/parcel_robot/headless_city.py` | envelope-derived person fallbacks (that fallback only) |
| `tests/test_e2_safety_wiring.py` | **new**, 15 tests |

**Reverted deliberately (owner-gated, not landed):** `configs/robot.yaml`,
`configs/robot.acoustic.yaml`, `src/parcel_robot/config/robot.yaml`,
`src/parcel_robot/runtime_assets/configs/robot.yaml`,
`src/parcel_robot/navigation/follow.py`, and the `person_stop_m` guard itself.
`src/parcel_robot/core/hard_stop.py` needed no change. Nothing in MUST-NOT-TOUCH
was edited. **Nothing was committed and nothing was re-frozen.**

## does_not_prove

* Does not prove the person-clearance contract is honoured on the product path —
  it is still 1.0 m, pinned as a known disagreement.
* Does not prove hardware behaviour: on the Unitree path `_control_state_source`
  is not a `BufferedRobotStateSource`, so CONTROLLER_FEEDBACK evidence is
  `None` -> permanent `HOLD`. Pre-existing, out of scope, flagged for the
  hardware-readiness ledger.
* Does not prove FOLLOW_BENCH_V1 would stay at 6/9 after a `desired_distance_m`
  retune — that pairing was not measured.
