# MB-1 verdict — Model B narration

Verdict: **candidate Q is refuted; paired Q–D effect is unmeasured; physical
motion remains NO-GO.**

The hosted schedule is incomplete because the provider's daily request quota
stopped arm D after 2/120 scenarios. Therefore there is no valid hosted
Q-minus-D estimate. This limitation does not make candidate Q inconclusive:
all 120 Q scenarios completed, and its absolute pre-registered gates fail even
under the most optimistic permissible recovery timing.

| hypothesis / bar | hosted Q result | decision |
|---|---:|---|
| H-MB1a grounding | point range **0.6120–0.7274**; target ≥0.90, failure <0.75 | **refuted** |
| narratable coverage | point range **0.2283–0.2883** | failed |
| H-MB1b new-goal acknowledgement | 99/225 = **0.440**; target ≥0.90 | **refuted** |
| H-MB1b completion announcement | 11–27/165 = **0.067–0.164**; target ≥0.90 | **refuted** |
| H-MB1b resume offer | 10–11/30 = **0.333–0.367**; target ≥0.80 | **refuted** |
| keys inability bar | 1/25 = **0.040** | failed |
| premature arrival | 5–13/164 = **0.030–0.079**; ceiling 0.05 | timing-ambiguous |
| H-MB1c invented actions | 45 deterministic flags; blind local audit confirmed 4 and rejected 41; target 0 | **refuted, matcher needs recalibration** |
| H-MB1d local latency | Q-local TTFT p50 633 ms; ceiling 400 ms | **refuted** |

The deterministic invented-action breakdown is 22 acts with no declared tool,
22 perception claims despite no `perceive.*` receipt, and 1 undeclared gesture.
The pre-registered report-only local blind audit called 41/45 of these false
positives and confirmed 4/45. That is enough to miss a zero-invention gate, but
the 91% disagreement means the matcher must be recalibrated against human gold
labels before its raw count is used as a promotion metric.

The older 16-scenario hosted-Q pilot was less pessimistic—grounding 0.8187
[0.6521, 0.9479], coverage 0.2938—but still failed the 0.90 grounding target,
completion (11/66), resume offer (3/12), keys bar (1/10), and zero-invention
requirement (19 flags). The larger Q row strengthens rather than reverses the
rejection.

## Recommendation

Do not promote the plan-queue prompt as Model B and do not let Realtime text
infer task status. Replace free-form fact inference with a deterministic
utterance contract:

1. TaskExecutive emits a typed speech act (`ack`, `blocked`, `completed`,
   `failed`, `resume_offer`, `capability_refusal`) with allowed slots.
2. The hosted/local language model may paraphrase those slots, but a
   postcondition checker rejects any arrival, perception, motion, or action
   claim not licensed by the triggering receipt and capability enum.
3. Completion and resumption wording uses deterministic templates until the
   paraphraser clears the ≥0.90 bars on a held-out corpus.
4. Run future hosted comparisons in small stratified blocks with atomic
   checkpoints and stop before the account RPD boundary; do not count empty
   quota-degraded responses as evidence of model quality.

This experiment concerns wording over scripted receipts. It provides no
evidence for perception, navigation execution, motor safety, audio duplexing,
or Unitree mount readiness.
