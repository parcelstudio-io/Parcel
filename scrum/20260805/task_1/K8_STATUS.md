# K8 status — Frozen walk-with-me integration pack

**Card:** K8 (kickoff board, ADJUDICATION)  
**Date:** 2026-08-05  
**Lane:** Sol (generator) + Opus (runner)  
**Constraint:** freeze seeds; no rewriting old ledgers; honest `does_not_prove`

## Verdict

Delivered a **10-script** frozen walk-with-me pack under `evals/walk_with_me/`
with seed-stable generator, stub/headless runner, instructnav-compatible
attribution (`FailureClass` / `AttributionLayer`), and a CI-light smoke test.

## Delivered

| Item | Path | Notes |
|---|---|---|
| Frozen pack (10 scripts) | `evals/walk_with_me/freeze/manifest.json` | freeze seed `20260805`; digest `fc24837c…` |
| Sol-style generator | `evals/walk_with_me/generator.py` | pure; no MuJoCo/runtime |
| Opus-style runner | `evals/walk_with_me/runner.py` | `stub` (CI) + `headless` (nav/spatial harness) |
| CLI | `evals/walk_with_me/run_walk_with_me_v1.py` | `--smoke`, `--write-freeze`, `--validate-freeze-only` |
| Smoke tests | `tests/test_walk_with_me_k8.py` | pack load + 2 stub episodes + CLI |
| README | `evals/walk_with_me/README.md` | |

## Themes (10)

| script_id | theme | harness |
|---|---|---|
| `wwm-follow-behind` | follow | spatial |
| `wwm-wait-hold` | wait | behavior_stub |
| `wwm-orbit-once` | orbit | spatial |
| `wwm-sidewalk-from-road` | sidewalk | navigation |
| `wwm-lamppost-standoff` | lamppost | navigation (`next_to` GoalRegion / K0) |
| `wwm-pause-resume` | pause_resume | resume (`ResumeStore` + fresh observation) |
| `wwm-barge-in-tts` | barge_in | behavior_stub (TTS interrupt, motion unchanged) |
| `wwm-absent-target` | absent_target | navigation (honest refusal) |
| `wwm-owner-search` | owner_search | behavior_stub (bounded search; no nearest-person) |
| `wwm-curb-stop` | curb_stop | behavior_stub (edge hold + voice initiation) |

## Attribution

Episode results carry:

- `failure` — `parcel_robot.instructnav.scoring.FailureClass`
- `attribution_layer` — `AttributionLayer` (L1–L6)

Absent-target honesty succeeds as a task while recording `refusal` /
`L2a_vocabulary` (not a geometric arrival). Pause/resume and barge-in stubs
map clean failures to `termination` / `control_error` + L6/L5 when contracts
break.

## Smoke results (2026-08-05)

```bash
.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --validate-freeze-only
# ok=true, count=10, digest=fc24837ce23b23cb5c87a7c2ccbb70df396a7870159802719069efc95ed6deab

.parcel/bin/python -m evals.walk_with_me.run_walk_with_me_v1 --smoke
# n=2, sr=1.0 (wwm-pause-resume + wwm-barge-in-tts)

.parcel/bin/python -m pytest tests/test_walk_with_me_k8.py -q
# 6 passed
```

Full stub pack (not CI gate): `n=10`, `sr=1.0` — stub placeholders for
follow/orbit/nav geometric themes are **not** evidence of headless capability.

## Explicit non-claims (`does_not_prove`)

Manifest lists seven boundaries, including: real sensors/robot; acoustic
barge-in/AEC; owner ReID; curb/crossing physics; camera-grounded semantics;
full voice→PlanIR path; hardware/Orin budgets. Stub geometric successes for
follow/orbit/sidewalk/lamppost are CI scaffolding — replace with `--mode
headless` nightly for L1/L2 evidence.

## Freeze discipline

- Seeds frozen at pack level (`20260805`) and per-script (`script_seeds` in
  manifest).
- Digest must match `generate_frozen_pack`; `--validate-freeze-only` enforces.
- **No old ledger rows rewritten** (nav-instruct / follow-bench / task_6 freezes
  untouched).

## Next (out of K8 MVP)

- Nightly headless attribution over nav/spatial scripts.
- Wire real barge-in / duplex clocks when K6 voice lanes land.
- Promote curb-stop + owner-search from stubs to closed-loop harnesses.
