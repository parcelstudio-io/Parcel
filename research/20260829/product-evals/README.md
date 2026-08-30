# Current-tree product evaluations

This directory is the 2026-08-29 evidence ledger for evaluation paths that exercise
Parcel's current product code or its checked-in evaluation harnesses.  It is kept
separate from the exploratory Model A/Model B experiments so that fixture success,
simulator evidence, and physical evidence are not conflated.

The controlling result is **motion-enabled physical deployment: NO-GO**.  The
strongest positive result is that the typed executive/runtime path works on four
supported frozen headless cases.  The strongest negative results are 27.2% success
on the fresh 125-episode NAV_INSTRUCT suite, unsafe contacts in the separately
reproduced dynamic-social study, six failed pose-drift floors, and corrected
acoustic v2 endpoint/acknowledgement failures. The acoustic v1 audit remains as
historical measurement-debugging evidence, not the current capability result.

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
- `../ACOUSTIC_LOOP_V1_AUDIT.md` — additive measurement audit and direct
  drain-time PortAudio abort hardening; it does not rewrite the historical runs.
- `conversation/realtime-corpus-quality.json` — historical captured Realtime corpus
  plus machine checks and an unblinded report-only semantic review.
- `conversation/personal-convo-fixture.json` — deterministic reference fixture, not a
  hosted-model quality measurement.
- `RESULTS.md` — exact measurements and reproducibility notes.
- `VERDICT.md` — controlling readiness interpretation.
- `summary.json` — compact machine-readable v2 index including corrected
  acoustic, DSOAK scope, and current commit/nightly state.
- `TEST_RUNS.md` — guarded test commands and outcomes.
- `../POST_ULTRA_REMEDIATION.md` — bounded source dispositions from the fresh
  read-only Ultra review; the physical and capability blockers remain open.

## Interpretation rules

1. A frozen fixture can establish contract/integration behavior only within that
   fixture; it cannot establish language or navigation generalization.
2. A null-sink audio run is useful only when its clocks, rates, and channels are
   valid. It still cannot establish room acoustics, microphone/loudspeaker
   behavior, echo cancellation, audible presentation, or mounted audio.
3. Zero collisions in a small scripted or kinematic corpus is a count, not a safety
   rate.
4. Historical captured model output does not establish the quality of the model that
   would be deployed today.
5. Simulator evidence does not waive the staged gateway, stationary, tethered, and
   physical stop-distance promotion ladder.
