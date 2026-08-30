# Current-tree product evaluations

This directory is the 2026-08-29 evidence ledger for evaluation paths that exercise
Parcel's current product code or its checked-in evaluation harnesses.  It is kept
separate from the exploratory Model A/Model B experiments so that fixture success,
simulator evidence, and physical evidence are not conflated.

The controlling result is **motion-enabled physical deployment: NO-GO**.  The
strongest positive result is that the typed executive/runtime path works on four
supported frozen headless cases.  The strongest negative results are 27.2% success
on the fresh 125-episode NAV_INSTRUCT suite, unsafe contacts in the separately
reproduced dynamic-social study, and four failed null-sink acoustic gates.

## Contents

- `navigation/embodied-plan-v1.json` — five frozen accepted plans executed through
  `TaskExecutive` and `SemanticTaskRuntimeAdapter` in the headless kinematic city.
- `nav-instruct*/` — two independent invocations over the same frozen 125-episode
  v4 instruction set.
- `follow-bench*/` — two independent invocations of the 11-case scripted follow and
  navigation bench.
- `conversation/brain-v1.json` — typed intent, admission, executive, dispatch, and
  verified-fact boundary cases.
- `conversation/duplex-v1/` — scripted text duplex timing and interruption checks.
- `conversation/acoustic-loop-full*.json` — three full null-sink acoustic runs after
  fixing a negative-offset evaluator crash.
- `conversation/realtime-corpus-quality.json` — historical captured Realtime corpus
  plus machine checks and an unblinded report-only semantic review.
- `conversation/personal-convo-fixture.json` — deterministic reference fixture, not a
  hosted-model quality measurement.
- `RESULTS.md` — exact measurements and reproducibility notes.
- `VERDICT.md` — controlling readiness interpretation.
- `summary.json` — compact machine-readable index.
- `TEST_RUNS.md` — guarded test commands and outcomes.

## Interpretation rules

1. A frozen fixture can establish contract/integration behavior only within that
   fixture; it cannot establish language or navigation generalization.
2. A null-sink audio run can test software timing and teardown, not room acoustics,
   microphone/loudspeaker behavior, echo cancellation, or mounted audio.
3. Zero collisions in a small scripted or kinematic corpus is a count, not a safety
   rate.
4. Historical captured model output does not establish the quality of the model that
   would be deployed today.
5. Simulator evidence does not waive the staged gateway, stationary, tethered, and
   physical stop-distance promotion ladder.

