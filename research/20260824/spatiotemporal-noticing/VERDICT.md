# H11 — spatiotemporal noticing · VERDICT · 2026-08-24

## Verdict

**MECHANISM DIRECTION SUPPORTED; PHYSICAL-PROTOTYPE HYPOTHESIS INCONCLUSIVE.**

H6's pure visual-gallery novelty reproduced at 0.719 AUC. The frozen
spatiotemporal fusion reached 0.998 median AUC, and remained at 0.989 when a
post-run refuter required age to come from a successful map/track association.
The four-input weighted arithmetic took 0.602 microseconds p95; this excludes
association resolution, map/track/age lookup, feature extraction, IPC, and
serialization.

Do not interpret those numbers as evidence that Parcel already has generalized
perception. Simulator truth supplied identity and class for the generated map,
track, and age signals; tracker and map failures were seeded assumptions around
that truth. No synchronized physical sensor log exists. S5 also adds H6's
0.40/min false-hallucination point estimate as a fixed floor, without carrying
an uncertainty distribution.

Machine disposition: the pre-registered arithmetic comparisons pass, but
evidence sufficiency and `all_required_criteria_met` are **false**. The canonical
status is `INCONCLUSIVE_FOR_PROTOTYPE__MECHANISM_DIRECTION_SUPPORTED`.

## Accepted decisions

- Stop investing in appearance-only gallery thresholds for Milestone 1.
- Add synchronized pose/covariance, projected position, stable track
  generation, timestamp/age, and calibration epoch to the observation spine.
- Use local spatiotemporal evidence to decide *where to look again* before
  escalating perception or talking.
- Keep continuous noticing body-local; hosted VLM/LLM use is an admitted
  keyframe event, never a frame loop.
- Separate static-object association from dynamic-entity association.

## Rejected decisions

- Do not ship the tested binary 3x3 same-label map gate. It falsely suppressed
  17% of new probes at nominal conditions.
- Do not collapse identity novelty, place novelty, moved-object surprise, and
  social relevance into a single long-lived scalar.
- Do not let a perception novelty event command base motion, write a durable
  fact without governance, or speak without a conversation-opportunity gate.
- Do not claim <=1 false noticing/minute from 21 seconds of causal replay.
- Do not quote the arithmetic microbenchmark as end-to-end noticing latency.

## Prototype contract this research now requires

```text
ObservationEvidenceV1
  frame_id, source_timestamp, age
  calibration_epoch, localization_epoch
  label distribution + detector confidence
  embedding / appearance evidence
  depth-projected world position + covariance
  track_id, track_generation, association confidence

AssociationResolver
  -> identity_novelty
  -> place_novelty
  -> change_surprise
  -> evidence conflicts / uncertainty

AttentionOpportunity
  -> IGNORE | GAZE_VERIFY | MEMORY_CANDIDATE | SPEAK_PROPOSAL
```

`GAZE_VERIFY` is the default response to uncertain novelty. Only a verified,
relevant `SPEAK_PROPOSAL` enters the initiative/conversation arbiter. This is
how generalized perception can make the dog feel attentive without becoming
noisy, unsafe, or expensive.

## Remaining decision gate

Run the synchronized 30–60 minute sensor/mounted test specified in RESULTS.
Until it passes, H11 is approved as the design direction and rejected as
product-readiness evidence.

Fable should independently review the fixed score, the use of segmentation
identity, the simulated corruption grid, the post-run refuter, and the short
false-rate exposure before accepting this verdict.
