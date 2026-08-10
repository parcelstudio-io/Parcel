# C-B STATUS — counterfactual candidate logging + oracle replay

**Wave:** 2a sol half (contracts) + 2b opus half (arbiter wire).  
**Verdict:** **LANDED** (sol contracts + opus GoalArbiter wire).

---

## Sol half (Wave 2a) — frozen contracts

**Executor:** Sol stand-in (primary Sol `648a7ba1` hit API limit with zero progress)  
**Verdict:** **LANDED (pure contracts only).**

### Delivered (OWNS: NEW pure modules + tests only)

| Path | Role |
|---|---|
| `src/parcel_robot/counterfactual/__init__.py` | Public frozen surface |
| `src/parcel_robot/counterfactual/arbitration_log.py` | `ArbitrationCandidateV1` / `ArbitrationLogRecordV1` + `build_arbitration_log` + digest |
| `src/parcel_robot/counterfactual/oracle_replay.py` | `select_candidate_id` / `replay_committed_choice` / `counterfactual_report` |
| `tests/test_counterfactual_oracle.py` | 15 unit tests (selector, digest, bit-identical replay, oracle gap) |

**Not edited (sol):** `runtime.py`, `navigation/**`, `instructnav/**`, `camera_channel/**`, any product wiring.

### Frozen contracts (consumed by Opus Wave-2b; immutable this batch)

Schema IDs:

- log: `parcel.arbitration_log.v1`
- report: `parcel.counterfactual_report.v1`
- selector: `parcel.arbitration_selector.v1`

### Log at arbitration

```text
record = build_arbitration_log(
    record_id=...,
    episode_id=...,
    decision_monotonic_ns=...,
    candidates=(ArbitrationCandidateV1(...), ...),  # all present, incl. vetoed
    committed_candidate_id=<winner id | None for HOLD>,
    active_plan_step=...,   # optional; mirrors GoalArbiter plan-step filter
)
# persist record.as_dict() (digest-stamped)
```

Candidate fields mirror GoalArbiter sort/veto inputs without importing
`instructnav`: `source`, `priority`, `confidence`, `issued_s`, pose/waypoints,
`plan_step_id`, `task_id`, `plan_revision`, `admissible`, `veto_reason`.

### Bit-identical replay of committed choice

```text
assert replay_committed_choice(record) == record.committed_candidate_id
```

Selector key (frozen): `(-priority, -confidence, -issued_s, source, candidate_id)`
among admissible, with optional `active_plan_step` ownership filter. Unknown
`selector_id` → HOLD (`None`). Digest mismatch → raise (refuse replay).

### Would-a-different-candidate-have-won

```text
report = counterfactual_report(record, oracle_success={candidate_id: bool, ...})
# report.would_different_candidate_have_won
# report.alternate_success_ids
# report.oracle_preferred_candidate_id
# report.selection_regret
# report.replay_matches_committed
```

Inadmissible candidates never enter oracle preference. Committed success ⇒
`would_different_candidate_have_won=False` (no selection regret). This is the
COMPARISON §8.3 / T-G4 offline measurement substrate — not a learned ranker.
Pull-forward of C's offline measurement only per `INDEPENDENT_VERDICT_FABLE.md`
(not Design C full ABI).

### Sol evidence (historical)

- `.parcel/bin/python -m pytest -q tests/test_counterfactual_oracle.py` → **15 passed**
- owned ruff clean; tree-level ci_gate was red on parallel Wave-2a out-of-OWNS
  (STOP-and-reported at sol cut).

---

## Opus half (Wave 2b) — GoalArbiter live wire

**Executor:** Opus stand-in (Card C-B opus half)  
**Verdict:** **LANDED.**

### Delivered

| Path | Role |
|---|---|
| `src/parcel_robot/instructnav/arbiter.py` | Flag-gated `build_arbitration_log` at `GoalArbiter.resolve` commit; `report_counterfactual` |
| `tests/test_counterfactual_arbiter_wire.py` | 7 tests: flag-off noop, wire+replay, HOLD, plan-step, oracle report, env flag |

**Not edited (opus OWNS discipline):** `runtime.py` (arbiter-local hook; avoids V-E SE2Goal conflict),
`navigation/reactive_safety.py`, `velocity_shaping.py`, `collision.py`,
`instructnav/scoring.py`, `camera_channel/**`, `personal_convo/**`,
counterfactual frozen contracts (consumed only).

**Mechanical only (parallel V-E ruff dirt blocking ci_gate):**
`ruff check --fix` import-order on `instructnav/__init__.py` +
`navigation/pipeline.py` (I001/RUF022) — no semantic edits.

### Wire contract

```text
# default OFF
GoalArbiter(arbitration_log=True, episode_id=...)  # or PARCEL_ARBITRATION_LOG=1
winner = arbiter.resolve(goals, now_s=...)
record = arbiter.last_arbitration_log          # ArbitrationLogRecordV1
assert replay_committed_choice(record) == record.committed_candidate_id
report = arbiter.report_counterfactual(oracle_success={...})
# report.would_different_candidate_have_won / selection_regret / ...
```

- `candidate_id == SE2Goal.source`
- veto reasons logged: `stale_revision` / `ttl` / `lethal`
- selection path unchanged when flag off or on

### Opus evidence

- `.parcel/bin/python -m pytest -q tests/test_counterfactual_arbiter_wire.py` → **7 passed**
- `.parcel/bin/python -m pytest -q tests/test_counterfactual_oracle.py tests/test_instructnav_arbiter.py` → green
- `.parcel/bin/python -m ruff check src/parcel_robot/instructnav/arbiter.py tests/test_counterfactual_arbiter_wire.py` → clean

### ci_gate --tier commit (raw, 2026-08-09T23:13:37Z)

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety
[  PASS] HARD  frozen-digest-sentinels
[  skip] HARD  latency-tail-ledger        ledger rows=1 < window=5
[  PASS] HARD  model-off-non-inferiority
[  PASS] HARD  frozen-digest-integrity
[  PASS] HARD  mutation-panel-freshness
[  PASS] HARD  latency-tail
[  PASS] HARD  default-suite              3283 passed, 9 skipped, 34 deselected
RESULT: PASS — every hard gate green.
  elapsed 104.7s
```

Note: during the opus run, parallel V-E rewrites transiently reddened ruff on
`instructnav/__init__.py`, `navigation/pipeline.py`,
`tests/test_ve_detection_lock_on.py`, `evals/nav_instruct/cam_lock_on.py`.
Mechanical `ruff --fix` / `_lo` rename only; no semantic V-E edits. Gate green
above is after those import-order cleans settled.

## does_not_prove

- No eval-harness corpus / live episode oracle labels yet (T-G4 still needs
  frozen failure logs + oracle labels from wired runs).
- Does not implement Design C full ABI (CandidatePoolV1 / HardMaskVerdictV1 /
  RankDecisionV1 / CommitLeaseV1) — intentionally deferred per
  `INDEPENDENT_VERDICT_FABLE.md`.
- Flag default remains OFF — product path does not persist logs unless enabled.

## Blockers

None.
