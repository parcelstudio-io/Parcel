# Nightly run — 20260821T102132Z

Started `2026-08-21T10:21:32.971000+00:00` · elapsed 3001.9s · verdict **FAIL** (exit 1).

Produced by `scripts/run_nightly.py` (card R26). This folder is the whole
record of the run, including what failed — a nightly that only publishes its
greens is not a nightly.

## Stages

| Stage | Gating | Status | Detail |
| --- | --- | --- | --- |
| `ruff` | HARD | **pass** | 7 violation(s), baseline 7, new 0 |
| `hard-safety` | HARD | **pass** | nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 \| mutation panel clean: collisions=0 no_false_arrival=True \| mutation panel freshness: committed fields reproduce live = True \| follow-bench: 7 row(s), hard_collision_total all 0 = True \| walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True |
| `frozen-digest-sentinels` | HARD | **pass** | 4 immutable manifest(s) byte-identical to pin |
| `release-parity` | HARD | **pass** | 91 packaged asset(s) byte-identical to canonical source |
| `latency-tail-ledger` | HARD | **pass** | latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5) |
| `follow-bench-jerk-ratchet` | HARD | **pass** | latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2) |
| `assertion-evals` | HARD | **pass** | 5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^3 green on f03_estop_pass_k; 3/3 committed run folder(s) present |
| `model-off-non-inferiority` | HARD | **pass** | 23 passed in 0.49s |
| `frozen-digest-integrity` | HARD | **pass** | 6 passed, 1 warning in 0.41s |
| `release-parity-integrity` | HARD | **pass** | 10 passed in 0.74s |
| `mutation-panel-freshness` | HARD | **pass** | 2 passed, 3 warnings in 4.29s |
| `latency-tail` | HARD | **pass** | 6 passed, 2 warnings in 0.41s |
| `tier-coverage` | HARD | **pass** | 7539 collected = 7497 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap |
| `default-suite` | HARD | **fail** | 1 failed, 7487 passed, 9 skipped, 42 deselected, 5 warnings in 296.31s (0:04:56)<br>    FAILED tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress |
| `mutation-panel` | HARD | **pass** | 7/7 killed, survivors=[] |
| `nav-instruct-candidate:collisions` | HARD | **pass** | collision_total=0 (report nav-instruct-v1-candidate-v4-20260821T102746Z) |
| `nav-instruct-candidate:differential` | soft | **report** | sr=0.28 authority={'agreement': 18, 'authority_disagreement': 6, 'false_arrival': 1, 'tolerated_boundary': 0, 'unknown': 0} false_arrival=1 |
| `pose-drift-arms:safety` | HARD | **pass** | collisions=0 false_arrival=0 across 7 arm(s) on 61 cell(s) |
| `pose-drift-arms:non-vacuity` | HARD | **pass** | 176/176 episode(s) in band; SR truth=0.180, calibrated_go2=0.148, go2_aggressive=0.098, go2_degraded=0.033, calibrated_go2_lost=0.115, go2_degraded_lost=0.049, calibrated_go2_reanchoring=0.082 |
| `pose-drift-arms:floors` | HARD | **pass** | 6 arm(s) at or above their Stage-B floor |
| `slow-suite` | HARD | **fail** | 1 failed, 27 passed, 7 skipped, 7498 deselected, 4 xfailed, 3 warnings, 3 errors in 742.10s (0:12:22)<br>    FAILED tests/test_voice_nav_e2e.py::test_go_to_the_lamppost_grounds_plans_and_arrives<br>    ERROR tests/test_release_parity_wheel.py::test_wheel_imports_the_previously_broken_modules<br>    ERROR tests/test_release_parity_wheel.py::test_every_default_asset_resolves_inside_the_installed_wheel<br>    ERROR tests/test_release_parity_wheel.py::test_wheel_effective_config_equals_the_source_checkout |
| `metamorphic` | soft | **pass** | 5 passed, 11 deselected, 2 xfailed, 3 warnings in 47.80s |
| `future-clock-sweep` | HARD | **fail** | +400d: 1 failed, 7486 passed, 11 skipped, 42 deselected, 5 warnings in 290.47s (0:04:50)<br>    FAILED tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress |
| `assertion-nightly` | soft | **report** | 5 fixture session(s), pass^3; review queue 22 item(s); judge on, estimated $0.006496 of $1.5 cap |

## What went red

* **HARD `default-suite`** — 1 failed, 7487 passed, 9 skipped, 42 deselected, 5 warnings in 296.31s (0:04:56)
    FAILED tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress
* **HARD `slow-suite`** — 1 failed, 27 passed, 7 skipped, 7498 deselected, 4 xfailed, 3 warnings, 3 errors in 742.10s (0:12:22)
    FAILED tests/test_voice_nav_e2e.py::test_go_to_the_lamppost_grounds_plans_and_arrives
    ERROR tests/test_release_parity_wheel.py::test_wheel_imports_the_previously_broken_modules
    ERROR tests/test_release_parity_wheel.py::test_every_default_asset_resolves_inside_the_installed_wheel
    ERROR tests/test_release_parity_wheel.py::test_wheel_effective_config_equals_the_source_checkout
* **HARD `future-clock-sweep`** — +400d: 1 failed, 7486 passed, 11 skipped, 42 deselected, 5 warnings in 290.47s (0:04:50)
    FAILED tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress

## Provenance

```json
{
 "cpus": 192,
 "executable": "/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python",
 "git_dirty": true,
 "git_dirty_paths": [
  "onfigs/realtime.yaml.example",
  "docs/CI.md",
  "evals/20260820/voice_corpus_v1/queries.tsv",
  "scripts/ci_gate.py",
  "src/parcel_robot/agent.py",
  "src/parcel_robot/config.py",
  "src/parcel_robot/core/arbiter.py",
  "src/parcel_robot/memory.py",
  "src/parcel_robot/navigation/goals.py",
  "src/parcel_robot/realtime/__init__.py",
  "src/parcel_robot/realtime/audio_gateway.py",
  "src/parcel_robot/realtime/config.py",
  "src/parcel_robot/realtime/driver.py",
  "src/parcel_robot/realtime/lane.py",
  "src/parcel_robot/realtime/protocol.py",
  "src/parcel_robot/realtime/whisperer.py",
  "src/parcel_robot/runtime.py",
  "src/parcel_robot/safety.py",
  "src/parcel_robot/ui/index.html",
  "tests/conftest.py",
  "tests/test_ci_gate.py",
  "tests/test_cpu_budget_proxy.py",
  "tests/test_dynamic_costs.py",
  "tests/test_mission_log.py",
  "tests/test_realtime_answer_beat.py",
  "tests/test_realtime_completion_tense.py",
  "tests/test_realtime_lane.py",
  "tests/test_realtime_protocol.py",
  "tests/test_realtime_tool_broker.py",
  "tests/test_runtime.py",
  "tests/test_runtime_activation.py",
  "tests/test_runtime_whisperer_wiring.py",
  "tests/test_scene_and_memory_answers.py",
  "tests/test_voice_nav_e2e.py",
  "evals/20260820/voice_corpus_v1/make_impostor_wavs.py",
  "evals/assertions/",
  "models/speaker_id/",
  "scripts/future_clock.py",
  "scripts/load_guard.py",
  "scripts/run_nightly.py",
  "scrum/20260820/AUDIT_R17_R21_FABLE.md",
  "scrum/20260820/task_10/R21_STATUS.md",
  "scrum/20260820/task_11/EV1_STATUS.md",
  "scrum/20260820/task_12/F1SI_STATUS.md",
  "scrum/20260820/task_9/R20_STATUS.md",
  "scrum/20260821/",
  "src/parcel_robot/realtime/evidence_log.py",
  "src/parcel_robot/realtime/spend_ledger.py",
  "src/parcel_robot/realtime/voice_identity.py",
  "tests/test_eval_assertions.py",
  "tests/test_fail_closed_limits.py",
  "tests/test_future_clock_guard.py",
  "tests/test_load_guard.py",
  "tests/test_nightly_runner.py",
  "tests/test_r24_lock_discipline.py",
  "tests/test_realtime_pump_survival.py",
  "tests/test_realtime_spend_budget.py",
  "tests/test_realtime_voice_identity.py",
  "tests/test_safety_log.py",
  "tests/test_unknown_place_admission.py",
  "tools/enroll_owner_voice.py"
 ],
 "git_head": "2c274967b4927f2de4295fde9cfa9508ce633576",
 "git_head_subject": "feat: land hosted realtime companion and embodied voice navigation",
 "hostname": "jaewoo-jang-parcel",
 "load_at_start": {
  "busy_fraction": 0.0038,
  "busy_fraction_ceiling": 0.3,
  "ceiling": 57.599999999999994,
  "contended": false,
  "cpus": 192,
  "load1": 0.73681640625,
  "mode": "on"
 },
 "mujoco_gl": "egl",
 "platform": "Linux-7.0.0-29-generic-x86_64-with-glibc2.43",
 "python": "3.14.4"
}
```

## Gate output, verbatim

```
CI GATE — tier=nightly  (2026-08-21T11:06:18Z)
==============================================================================
[  PASS] HARD  ruff                                 7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                          nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels              4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity                       91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger                  latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet            latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals                      5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^3 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  model-off-non-inferiority            23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity              6 passed, 1 warning in 0.41s
[  PASS] HARD  release-parity-integrity             10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness             2 passed, 3 warnings in 4.29s
[  PASS] HARD  latency-tail                         6 passed, 2 warnings in 0.41s
[  PASS] HARD  tier-coverage                        7539 collected = 7497 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  FAIL] HARD  default-suite                        1 failed, 7487 passed, 9 skipped, 42 deselected, 5 warnings in 296.31s (0:04:56)
    FAILED tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress
[  PASS] HARD  mutation-panel                       7/7 killed, survivors=[]
[  PASS] HARD  nav-instruct-candidate:collisions    collision_total=0 (report nav-instruct-v1-candidate-v4-20260821T102746Z)
[report] soft  nav-instruct-candidate:differential  sr=0.28 authority={'agreement': 18, 'authority_disagreement': 6, 'false_arrival': 1, 'tolerated_boundary': 0, 'unknown': 0} false_arrival=1
[  PASS] HARD  pose-drift-arms:safety               collisions=0 false_arrival=0 across 7 arm(s) on 61 cell(s)
[  PASS] HARD  pose-drift-arms:non-vacuity          176/176 episode(s) in band; SR truth=0.180, calibrated_go2=0.148, go2_aggressive=0.098, go2_degraded=0.033, calibrated_go2_lost=0.115, go2_degraded_lost=0.049, calibrated_go2_reanchoring=0.082
[  PASS] HARD  pose-drift-arms:floors               6 arm(s) at or above their Stage-B floor
[  FAIL] HARD  slow-suite                           1 failed, 27 passed, 7 skipped, 7498 deselected, 4 xfailed, 3 warnings, 3 errors in 742.10s (0:12:22)
    FAILED tests/test_voice_nav_e2e.py::test_go_to_the_lamppost_grounds_plans_and_arrives
    ERROR tests/test_release_parity_wheel.py::test_wheel_imports_the_previously_broken_modules
    ERROR tests/test_release_parity_wheel.py::test_every_default_asset_resolves_inside_the_installed_wheel
    ERROR tests/test_release_parity_wheel.py::test_wheel_effective_config_equals_the_source_checkout
[  PASS] soft  metamorphic                          5 passed, 11 deselected, 2 xfailed, 3 warnings in 47.80s
==============================================================================
RESULT: FAIL — 2 hard gate(s) red: default-suite, slow-suite
  elapsed 2685.0s
```
