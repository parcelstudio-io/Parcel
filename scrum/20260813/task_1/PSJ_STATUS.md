# PS-J — physical-plausibility gate in preflight

**Tranche:** PS-2 (corrective) · **Date:** 2026-08-13 · **Executor:** Opus
**Card:** `RISK_ASSESSMENT.md` item 4 — *"a channel is not healthy because
messages arrive"*
**OWNS:** `scripts/parcel_capture/preflight.py`,
`scripts/parcel_capture/attest.py`, `tests/test_capture_preflight.py`

---

## The defect, measured at card start

```
$ grep -rn "9.81|plausib|gravity|magnitude" scripts/parcel_capture/preflight.py scripts/parcel_capture/attest.py
EXIT=1        (no output — zero hits in either module)
```

`ChannelProbe.status` had exactly one route to PRESENT — `messages_received >= 1`
— and `ChannelAttestation.origin` had exactly one route to PHYSICAL, the same
one. Nothing anywhere looked at *what the bytes said*. So `utlidar/imu` emitting
`-2.17e24 m/s^2` (two independent unfixed field reports of precisely that value)
was attested **PRESENT + PHYSICAL + healthy**, and the session would have been
recorded, packed up and powered down with that verdict on the record.

## What I built

A per-channel physical-plausibility layer that answers the second question —
*is what arrived possible?* — beside, and never instead of, the first.

**Rule selection is derived, not listed.** `classify_channel()` picks rule sets
off the matrix's DECLARED `message_type`, so it survives PS-A's matrix rewrite —
which landed *underneath this card mid-execution*: the matrix went from 22 to 28
channels while I was working, and the classifier absorbed `utlidar/cloud_deskewed`
(point cloud) and `front_camera_h264` (camera) with no edit. It also caught the
front camera's correction to `Go2FrontVideoData_` (research item 1), which a
`message_type.startswith("image/")` rule would have silently dropped.

| class | selected by | rules |
|---|---|---|
| IMU | a `message_type` segment starting `imu`, or any `LowState` | finite · within sensor full scale · `\|accel\|` = 9.80665 ± 1.0 at rest · `\|gyro\|` < 0.05 at rest · component presence |
| POINT CLOUD | `pointcloud` in the type | non-zero points · finite coordinates · range distribution · **fields[] dump** · per-point time field · ring field · layout stability |
| POWER | any `LowState` | `power_v` bounded · per-cell voltage bounded · `sum(cell_vol)` consistent with `power_v` |
| FOOT FORCE | any `LowState` | four channels · fits int16 · **the four vary and are not stuck** — and *no absolute value asserted anywhere* |
| CAMERA | `image/`/`video/` prefix or a `video`/`image` token | frame decodes · non-degenerate (all-black / all-saturated / flat) |
| *(none)* | anything else | `channel.no_rule_defined` → UNKNOWN, and a `PLAUSIBILITY_NO_RULE` NOTE so the coverage gap is visible rather than silent |

**Four IMUs, cross-checked.** `imu_unit_id()` groups streams by
`(device, frame_id)`, not by channel id. That is load-bearing in both
directions: the `lf/` mirror is the *same* body IMU and must not become a fifth
witness, and the D455's split accel/gyro streams are *one* unit and must not
become two. It yields exactly four, pinned by test. At rest,
`imu_cross_check()` compares their mean `|accel|` and names the unit furthest
from the median.

**Three verdicts, and UNKNOWN is not a soft PASS.** No rest period declared, no
measurement supplied, too few samples, no rule for the class, nothing received —
all UNKNOWN. `ChannelPlausibility.verdict` is a *property*: no constructor
argument anywhere names PASS.

**Rest is an operator claim, not an inference.** `--at-rest OPERATOR` (and
`RestPeriod`), following the LiDAR-label precedent. `--at-rest-note` without
`--at-rest` is refused. There is no code path that infers rest from the data it
is about to judge.

**The verdict never silences a recording.** `ChannelProbe.status` is computed
without reference to plausibility; plausibility findings are capped at MAJOR
because BLOCKING is the lane that drives *record nothing*. An implausible
channel stays PRESENT, stays `EvidenceOrigin.PHYSICAL`, and carries its verdict
into the sidecar via the attestation digest.

**It rides in the attestation under the house discipline.**
`ChannelAttestation.plausibility_verdict` is written for a human, **discarded on
read**, and recomputed from the channel's own stored checks — same mechanism as
`status`/`origin`. `verify_mapping()` now reports three more forgeries: a
hand-edited per-channel `plausibility_verdict`, a shortened
`implausible_channels` list, and doctored counts.

**Printed into the run header, every run, for every channel.**
`format_plausibility_block()` leads with the rest attestation, the IMU
cross-check, the pass/fail/unknown counts and the IMPLAUSIBLE list, then gives
every rule and every note per channel — including the `PointCloud2 fields[]`
dump verbatim in wire order. `attest.py` prints it even without
`--print-preflight`.

**27 distinct rule ids** are reachable (24 sensor rules + `no_rule_defined`,
`no_message_received`, `assessor_raised`, plus the per-class `no_measurement`).

---

## MEASURED claims

Every row is a command actually run on this host and its actual output.

| # | Claim | Command | Output |
|---|---|---|---|
| 1 | The defect was real: zero plausibility logic existed | `grep -rn "9.81\|plausib\|gravity\|magnitude" preflight.py attest.py` (at card start) | `EXIT=1`, no output |
| 2 | It is gone | same grep, now | `attest.py:64` `preflight.py:87` matching lines |
| 3 | Card tests green | `.parcel/bin/python -m pytest tests/test_capture_preflight.py -q` | `219 passed in 0.75s` (baseline before this card: `126 passed`) |
| 4 | No sibling card regressed | `... -m pytest tests/test_capture_preflight.py tests/test_capture_rehearsal.py tests/test_capture_sidecar.py tests/test_capture_envelope.py tests/test_clockmap.py -q` | `604 passed in 13.35s` |
| 5 | Both modules parse as 3.10 **and** 3.14 | `compile(src, flags=PyCF_ONLY_AST, _feature_version=10/14)` | `preflight.py: parses under feature_version 3.10 OK` / `3.14 OK`; same for `attest.py`. **Static only — no 3.10 interpreter exists on this host** (PS-A's finding, unchanged) |
| 6 | The 1e24 case is FAILed with the value verbatim | end-to-end run, reader emits `accel=(-2.17e24, 0.13, 9.79)` | `imu.accel_within_sensor_range: largest component -2.17e+24 m/s^2 exceeds the 200.0 m/s^2 bound (BMI055-class full scale is +/-16 g = 156.9 m/s^2)` |
| 7 | …and the channel is still recorded | same run | `channels present=22 degraded=6 absent=0` · `PHYSICAL 28 channel(s)` · `IMPLAUSIBLE go2.utlidar.cloud, go2.utlidar.imu — RECORD THEM ANYWAY` |
| 8 | The four IMUs really cross-check | same run, 3 units at ~9.8 and `utlidar` at 1e24 | `IMU_CROSS_CHECK_DISAGREEMENT: … spread 2.17e+24 m/s^2 across 4 unit(s) (d455:camera_imu_optical_frame \|accel\|=9.82, go2:base_link \|accel\|=9.80003, go2:go2_utlidar_imu_link \|accel\|=2.17e+24, l2:l2_imu_link \|accel\|=9.80003). Furthest from the median (9.82) is go2:go2_utlidar_imu_link` |
| 9 | The fields[] dump is prominent and unrecoverable-after-powerdown is said out loud | same run, cloud with `fields[]=x,y,z,intensity` | `POINTCLOUD_NO_DESKEW_FIELDS: … NO per-point time field … so GLIM / FAST-LIO2 / Point-LIO / KISS-ICP cannot motion-compensate this cloud. This is discoverable ONLY while the rig is powered.` |
| 10 | Dev-box run is still honest, complete and traceback-free | `.parcel/bin/python scripts/parcel_capture/attest.py --window 0.01` | `plausible pass=0 fail=0 unknown=28`, `VERDICT: REFUSE_CONNECT`, exit 2, no traceback |
| 11 | `--at-rest` works end to end | `scripts/parcel_capture/preflight.py --window 0.005 --at-rest jae` | header line `rest period: operator jae attests the rig was at rest` |
| 12 | 27 rule ids reachable | driver script over every class | listed above; 24 sensor + 3 structural |
| 13 | Exactly four IMU units in the (rewritten) matrix | `len({imu_unit_id(e) for e in CHANNELS if IMU in classify_channel(e)})` | `4` — pinned by `test_the_matrix_really_does_carry_four_independent_imu_units` |
| 14 | ruff clean on all three owned files | `.parcel/bin/python -m ruff check preflight.py attest.py test_capture_preflight.py` | `All checks passed!` |
| 15 | ci_gate commit tier | `cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit` | see **RESULT** below |

### ci_gate

```
CI GATE — tier=commit  (2026-08-13T11:29:32Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.30s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              4688 passed, 9 skipped, 36 deselected, 5 warnings in 196.84s (0:03:16)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 208.3s
EXIT=0
```

**A previous run of this same command was RED and is reported here rather than
hidden:** `RESULT: FAIL — 1 hard gate(s) red: ruff … 12 violation(s), baseline
7, new 5`. All five were mine (`RUF046`, `F401`, `F811`, `RUF059`, `RUF100`),
all in my three files, all fixed; the run above is the same command after the
fix. `default-suite` was green in both (`4687` then `4688 passed`) — the ruff
ratchet was the only red.

---

## Seeded failures — one row per gate

Every rule below has a test that seeds the defect and proves the oracle catches
it. The 1e24 case uses the field-reported value verbatim.

| Gate | Seeded defect | Caught by | Verdict |
|---|---|---|---|
| **headline** | `accel = (-2.17e24, 0.13, 9.79)`, the field-report value | `imu.accel_within_sensor_range` | FAIL; the same probe re-scored by yesterday's oracle (`_receipt_count_health`, re-implemented in the test) returns `HEALTHY` — the refutation is measured, not asserted |
| IMU | `\|accel\|` = 7.0 at rest | `imu.accel_magnitude_at_rest` | FAIL |
| IMU | `\|accel\|` = 12.5 at rest | `imu.accel_magnitude_at_rest` | FAIL |
| IMU | `\|accel\|` = 0.0 at rest (dead sensor reading zero) | `imu.accel_magnitude_at_rest` | FAIL |
| IMU | `accel` component NaN | `imu.accel_finite` | FAIL |
| IMU | `accel` component inf | `imu.accel_finite` | FAIL |
| IMU | `\|gyro\|` = 0.4 rad/s at rest | `imu.gyro_magnitude_at_rest` | FAIL |
| IMU | `gyro` NaN | `imu.gyro_finite` | FAIL |
| IMU | `gyro` = 1e9 rad/s | `imu.gyro_within_sensor_range` | FAIL |
| IMU | a FULL stream that omits its gyro | `imu.gyro_present` | UNKNOWN (not PASS) |
| IMU | band edges: 9.80665+0.99 vs +1.01 | `imu.accel_magnitude_at_rest` | PASS / FAIL — the band is the card's band, pinned |
| IMU cross-check | 3 units at 9.81, `utlidar` at 1e24 | `IMU_CROSS_CHECK_DISAGREEMENT` | MAJOR, names the outlier unit |
| IMU cross-check | *refutation*: four agreeing units | — | no finding at all |
| IMU cross-check | only one unit reporting | `IMU_CROSS_CHECK_UNAVAILABLE` | UNKNOWN NOTE |
| POINT CLOUD | `point_count = 0` | `point_cloud.point_count` | FAIL |
| POINT CLOUD | 12 non-finite points | `point_cloud.coordinates_finite` | FAIL |
| POINT CLOUD | every range identical | `point_cloud.range_distribution` | FAIL (degenerate) |
| POINT CLOUD | a 42000 m range (mm reported as m) | `point_cloud.range_distribution` | FAIL |
| POINT CLOUD | a negative range | `point_cloud.range_distribution` | FAIL |
| POINT CLOUD | a NaN range | `point_cloud.range_distribution` | FAIL |
| POINT CLOUD | `fields[] = (x,y,z)` | `point_cloud.per_point_time_field` | FAIL + `POINTCLOUD_NO_DESKEW_FIELDS` with the list dumped |
| POINT CLOUD | `fields[] = (x,y,z,time)` | `point_cloud.ring_field` | FAIL, detail distinguishes "time-based deskew still available" |
| POINT CLOUD | `fields[] = ()` | `point_cloud.per_point_time_field` | FAIL |
| POINT CLOUD | layout changes mid-window | `point_cloud.field_layout_stable` | FAIL |
| POINT CLOUD | no ranges sampled | `point_cloud.range_distribution` | UNKNOWN (not PASS) |
| POWER | `power_v = 0.0` / `-57.75` / `1e6` / NaN | `power.pack_voltage_range` | FAIL (4 cases) |
| POWER | cells at 3850.0 (millivolts unconverted) | `power.cell_voltage_range` | FAIL, detail names the units trap and refuses to guess |
| POWER | cells at 1.2 V | `power.cell_voltage_range` | FAIL |
| POWER | `power_v = 40.0` against a 57.75 V cell sum | `power.cell_sum_consistent` | FAIL |
| POWER | no `cell_vol` array | both cell rules | UNKNOWN (`BmsState` has no voltage field, so nothing to cross-check) |
| FOOT FORCE | foot 1 stuck at one value | `foot_force.varies` | FAIL, names `[1]` |
| FOOT FORCE | all four stuck | `foot_force.varies` | FAIL, names `[0, 1, 2, 3]` |
| FOOT FORCE | a 3-element array | `foot_force.four_channels` | FAIL |
| FOOT FORCE | a count of 40000 | `foot_force.int16_container` | FAIL, detail says "container check, not a force claim" |
| FOOT FORCE | 3 samples | `foot_force.varies` | UNKNOWN (cannot tell stuck from slow) |
| FOOT FORCE | *negative control*: counts of 30000 that vary | — | PASS — proof no absolute force is asserted |
| CAMERA | `decoded = False` | `camera.frame_decodes` | FAIL |
| CAMERA | `width = 0` | `camera.frame_decodes` | FAIL |
| CAMERA | `mean_level` NaN | `camera.frame_decodes` | FAIL |
| CAMERA | all-black (lens cap) | `camera.non_degenerate` | FAIL; old oracle says `HEALTHY` |
| CAMERA | 99.9% saturated | `camera.non_degenerate` | FAIL |
| CAMERA | flat frame (`min == max`) | `camera.non_degenerate` | FAIL |
| fail-closed | a reader that yields bytes and no measurement | `imu.no_measurement` | UNKNOWN + one aggregate `PLAUSIBILITY_NOT_ASSESSED` NOTE |
| fail-closed | assessor itself raises `ZeroDivisionError` | `channel.assessor_raised` | UNKNOWN, probe still PRESENT with all 5 messages, `PLAUSIBILITY_ASSESSOR_FAILED` MAJOR |
| fail-closed | `[PASS, PASS, UNKNOWN]` | aggregate | UNKNOWN — UNKNOWN never decays into PASS |
| fail-closed | receipt carrying a list / a str / a bare object as `measurements` | `SampleReceipt` | `ProbeContractError` (3 cases) |
| fail-closed | 10 malformed physical samples (2-tuple vector, str component, bool component, negative point count, empty field name, list not tuple, str voltage, float foot count, fraction > 1) | sample constructors | `ProbeContractError` (10 cases) |
| fail-closed | `ChannelPlausibility(accel_magnitude_mean_mps2=NaN)` | constructor | refused — a non-finite statistic would make `canonical_json(allow_nan=False)` unserialisable; it is reported in words instead |
| fail-closed | a sample type that forgot to inherit `PhysicalSample` | `SampleReceipt`'s base-class gate | structurally pinned: all five sample types are `PhysicalSample` subclasses, and `_CLASS_SAMPLE_TYPE` covers every `ChannelClass` member |
| forgery | hand-edited `plausibility_verdict: "pass"` + emptied `implausible_channels` + doctored counts | `verify_mapping` | three discrepancies reported, recomputed verdict still FAIL |
| forgery | *refutation*: untouched file | `verify_mapping` | `discrepancies == ()`, digest stable |
| forgery | a `ChannelAttestation` carrying another channel's ruling | constructor | `AttestationRefused` |
| forgery | undecodable verdict string in a record | `from_mapping` | `AttestationRefused` |
| never-silences | plausibility FAIL on a channel | attestation verdict | `GO_RECORD`, `origin = PHYSICAL`, `status = PRESENT` |
| never-silences | three seeded FAILs across three classes | finding severities | all MAJOR — **no plausibility finding can ever be BLOCKING** |

### Mutation harness — 10 mutants, 10 killed

Run with `python -B`, `PYTHONDONTWRITEBYTECODE=1`, and every `__pycache__`
removed before each case (PS-A's same-byte-length `.pyc` contamination finding).
Sources restored from a backup after each mutant and verified clean afterwards.

```
MUTANT M1 accel ceiling 200 -> 1e30: KILLED  (1 failed) first=test_seeded_failure_the_1e24_accelerometer_is_caught_and_the_old_oracle_misses_it
MUTANT M2 rest band 1.0 -> 100.0: KILLED  (1 failed) first=test_seeded_failure_each_bad_accelerometer_is_caught_by_its_own_rule[accel0-imu.accel_magnitude_at_rest]
MUTANT M3 aggregate treats UNKNOWN as PASS: KILLED  (1 failed) first=test_without_a_declared_rest_period_the_rest_rules_are_unknown_never_pass
MUTANT M4 no-ruling default UNKNOWN -> PASS: KILLED  (1 failed) first=test_an_absent_channel_is_unknown_and_a_channel_with_no_rule_says_so
MUTANT M5 missing per-point time field -> PASS: KILLED  (1 failed) first=test_seeded_failure_each_bad_cloud_is_caught_by_its_own_rule[overrides6-point_cloud.per_point_time_field]
MUTANT M6 a plausibility FAIL silences the channel: KILLED  (1 failed) first=test_the_implausible_channel_is_still_present_physical_and_recorded
MUTANT M7 plausibility findings MAJOR -> BLOCKING: KILLED  (1 failed) first=test_the_implausible_channel_is_still_present_physical_and_recorded
MUTANT M8 verify_mapping stops checking plausibility_verdict: KILLED  (1 failed) first=test_seeded_failure_a_hand_forged_plausibility_pass_is_reported_not_absorbed
MUTANT M9 imu_unit_id groups by channel id, not frame: KILLED  (1 failed) first=test_the_matrix_really_does_carry_four_independent_imu_units
MUTANT M10 stuck foot-force feet are no longer detected: KILLED  (1 failed) first=test_seeded_failure_a_stuck_foot_is_caught_and_named
harness complete
```

Harness re-run against the FINAL source (after the ruff fixes and the run-header
restructure) — the output above is that second run; 10/10 killed both times.
Post-harness restoration verified:
`grep -c "1e30\|ACCEL_REST_TOLERANCE_MPS2 = 100.0\|plausibility_verdict_disabled\|stuck = \[\]"`
→ `0` in both modules, `219 passed`, `ruff: All checks passed!`.

---

## OWNS deviations

**None.** Three files changed, all three on the card:
`scripts/parcel_capture/preflight.py`, `scripts/parcel_capture/attest.py`,
`tests/test_capture_preflight.py`.

Nothing armed: no publisher, no `ControlManager`, no lease, no motion client, no
vendor SDK import, no write handle to anything. The existing AST pins
(`test_no_symbol_in_either_module_can_reach_a_motion_surface`,
`test_neither_module_imports_a_vendor_sdk_or_the_runtime`,
`test_a_full_preflight_run_never_imports_a_vendor_sdk`) pass unchanged over the
grown modules; the subprocess probe still reports `VENDOR []`.

`src/parcel_robot/capture/channels.py` was **not** touched — including when I
found the matrix had grown from 22 to 28 channels underneath me. The
`test_the_channel_enumeration_is_ps_a_s_and_this_card_keeps_no_second_list` pin
(no channel id may appear as a string constant in either module) is why the
classifier keys on `message_type`, and it is the reason the rewrite cost this
card nothing.

### Notes for the auditor

1. **Plausibility findings are deliberately capped at MAJOR.** BLOCKING drives
   `SessionVerdict.DEGRADE_MMP`, which is *record nothing* — the exact outcome
   the card forbids ("a failed plausibility check must never silence a
   recording"). MAJOR is the lane `advisories` already documents as "never
   hidden, decided at the go/no-go". A reviewer who wants an implausible
   critical channel to *stop the session* should say so explicitly; I read the
   card as saying the opposite.
2. **The matrix changed under this card mid-execution** (22 → 28 channels,
   `rt/` prefixes, front camera corrected to `Go2FrontVideoData_`). Everything
   here is derived from `message_type`, so it absorbed the change and picked up
   the two new point-cloud/camera channels for free. The one thing it exposed:
   a prefix-only camera rule would have dropped the JPEG front camera, so the
   classifier matches a `video`/`image` token anywhere in the type.
3. **`SampleReceipt` gained a field** (`measurements`), defaulting to `()`. Every
   existing caller is unaffected and an empty tuple is the fail-closed value —
   it produces UNKNOWN, not PASS. The receipt still carries no payload; a
   `PhysicalSample` is a small typed summary in SI units, not the message.
4. **This layer only ever tightens.** It adds a verdict, findings, and three new
   forgery checks. It removes no refusal, relaxes no threshold, and changes no
   existing derivation. `status`, `origin`, `verdict` and the firmware gate are
   byte-for-byte the same logic as before.

---

## does_not_prove

1. **No hardware was involved in any of this.** Every measurement above came
   from injected readers on a dev box with no `rclpy`, `cyclonedds`,
   `unitree_sdk2py`, `pyrealsense2`, `cv2`, `mcap` or `zstandard`. The rules
   have never seen a real IMU, a real cloud, or a real battery. On the Orin
   every channel will read UNKNOWN until a live reader actually populates
   `measurements` — **that ingest work is PS-G's, not this card's**, and until
   it lands this layer is a loaded gun with no round in it.
2. **A PASS is not a calibration.** It says the summarised quantities were in
   bounds during the probe window. It says nothing about axis order, sign
   convention, handedness, or the frame the numbers are in — an IMU mounted
   upside down reads 9.81 m/s² at rest and PASSES.
3. **UNKNOWN is the expected outcome today and will be common tomorrow.** It
   means the evidence to judge was absent. Do not read a screen of UNKNOWNs as
   a screen of quiet successes.
4. **The at-rest rules stand on an operator's word.** Nothing verifies that the
   rig was actually stationary. A wrong claim turns real motion into a spurious
   FAIL, or hides a real fault behind a plausible-looking one.
5. **The sensor-full-scale ceilings (200 m/s², 40 rad/s) are bounds on
   absurdity, not device specs.** They are set generously above BMI055-class
   full scale so no real sensor can trip them. A sensor wrong by 3× at rest
   passes them; only the at-rest band catches that, and only under a declared
   rest period.
6. **The `fields[]` dump records what the driver DECLARED.** It does not prove
   the per-point time values are correct, monotonic, or in the units the field
   name implies — only that a field by that name exists. A cloud that passes
   `point_cloud.per_point_time_field` may still be undeskewable.
7. **Foot force is asserted only to vary and to fit int16.** No absolute contact
   force is claimed anywhere, because none can be: the counts have no published
   units, gain or offset (research item 7). A sensor stuck at a *slowly drifting*
   value passes `foot_force.varies`.
8. **The four-IMU cross-check compares mean `|accel|` only.** It cannot see a
   rotational disagreement, a lever-arm effect, or two units broken the same
   way. Three units agreeing at a wrong value would be reported as agreement.
9. **The camera rules see the reader's summary, not pixels.** A reader that
   computes `zero_fraction` wrongly makes the rule wrong, and preflight cannot
   tell. Focus, exposure, rolling shutter and colour correctness are entirely
   outside this layer.
10. **Python 3.10 compatibility is STATIC only.** `_feature_version=10` parses
    both modules; no 3.10 interpreter exists on this host and none of this code
    has ever been executed on one. That is PS-A's limitation, unchanged and
    not narrowed by this card.
11. **The mutation harness proves the tests bite for ten specific mutations.**
    It is not a coverage claim, and a rule with no mutant is a rule whose test
    I have not adversarially checked.
