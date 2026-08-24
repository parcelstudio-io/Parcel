# H11 — spatiotemporal noticing · RESULTS · 2026-08-24

Contract: [`DESIGN.md`](DESIGN.md), written before the first run. Evidence tier:
**desktop render replay plus seeded mechanism simulation**. Hosted spend:
**$0.00**. No product code, existing research, test, scrum, gateway, or
NAV-CORE file was changed.

## Outcome

The proposed fusion passes its pre-registered arithmetic comparisons and
decisively separates H6's counterfactual new/seen probes. The overall machine
status is nevertheless **INCONCLUSIVE FOR THE PROTOTYPE** because the evidence
is insufficient for S5 and no physical map/tracker signal was measured. It is
mechanism-direction evidence: visual evidence came from the real repo models;
map, track, age, identity, and class were generated around simulator truth.

The most useful finding is not the near-perfect AUC. It is that a binary
same-label map neighborhood falsely called **17.0%** of new probes familiar at
the nominal setting. New-object recall consequently passed by only 0.15
percentage points in the stricter association-coupled refuter. A prototype
should not implement this as one binary scalar.

## Machine-readable disposition

- `pre_registered_arithmetic_criteria_met`: **true**
- `evidence_sufficiency.sufficient_for_prototype_confirmation`: **false**
- `all_required_criteria_met`: **false**
- `overall_hypothesis_status`:
  `INCONCLUSIVE_FOR_PROTOTYPE__MECHANISM_DIRECTION_SUPPORTED`

This preserves every frozen score and bar while preventing an arithmetic pass
from being interpreted as adequate physical evidence.

## What was run

```bash
.parcel/bin/ruff check \
  research/20260824/spatiotemporal-noticing/run_experiment.py

.parcel/bin/python \
  research/20260824/spatiotemporal-noticing/run_experiment.py \
  --repo . \
  --work-dir /tmp/parcel-h11-codex-20260824 \
  --out research/20260824/spatiotemporal-noticing/results.json
```

The harness regenerated H6's 42 `city_block.xml` frames, started its own
private perception daemon/socket, ran OWLv2 fp16 and SigLIP-2 fp16 through
CUDA, shut down only that child daemon, built the paired counterfactuals, and
ran 100 nominal seeds plus 4,800 sensitivity trials. The disposable corpus
was 77 MB under `/tmp`; the committed result is a compact 21 KB JSON.

Revision under test: git `389541cdc3b7b1e5265faf2ff0d364aa36c1dea0`,
scene SHA-256
`e89f4f1219f7a92a64855698fa5c04423897ab0090d53863e6996614413dda58`.

## Neural observation collection

| measurement | result |
|---|---:|
| frames | 42 |
| quality-passing OWLv2 detections | 296 |
| segmentation-matched, embedded crops | 144 |
| unique segmentation instances | 24 |
| counterfactual new/seen pairs | 141 |
| collection elapsed | 6.54 s |
| daemon detect p50 / p95 | 99.19 / 101.04 ms |
| daemon errors | 0 |
| providers | CUDA, CPU fallback listed; selected profile `cuda_fp16` |

The detector p95 remains just above H6's 100 ms aspiration. That is reported,
not claimed fixed; neural latency was not an H11 criterion.

The segmentation truth supplied the identity and class used to construct map,
track, and age signals. Map entries used simulator geometry plus seeded noise;
track matches were Bernoulli draws around truth identity; age used simulator
frame order and truth-derived association. None is a recorded SLAM, tracker,
or runtime-memory signal.

## Pre-registered rows

| row | criterion | result | disposition |
|---|---|---:|---|
| S1 | gallery AUC within 0.03 of H6's 0.7236 | **0.7190**, delta 0.0046; 141 vs 142 pairs | PASS; equivalent enough to compare |
| S2 | nominal fused AUC >= 0.80 | **0.9983 median**, 0.9938 min over 100 seeds | PASS in mechanism simulation |
| S3 | new-object recall >= 0.80 at 0.70 | **0.8085 median** | PASS, narrowly |
| S4 | repeat suppression >= 95% | **100% median**, 99.17% min | PASS on the 21 s replay |
| S5 | false repeats + H6 hallucination floor <= 1/min | **0.40/min median**, 3.26/min max | arithmetic PASS by the pre-registered median; rate evidence INADEQUATE |
| S6 | fusion-arithmetic p95 <= 0.5 ms | **0.000602 ms** (0.602 microseconds), 100,000 decisions | arithmetic PASS; excludes association/map lookup |
| S7 | sensitivity frontier | reported below | REPORT |

S5 must not be read as a reliable physical false-trigger rate. Each seed has
only 0.35 minutes of causal exposure; one repeat becomes 2.86/min. The median
is zero repeats, but at least one seed emitted one. H6's 0.40/min
hallucination value is added to every simulated repeat rate as a **fixed point
estimate**; no confidence interval or uncertainty distribution is propagated.
A mounted 30–60 minute run is required.

## Ablations and the post-run refuter

| score | nominal paired AUC median |
|---|---:|
| visual gallery only | 0.7190 |
| visual + age | 0.9694 |
| visual + map | 0.9486 |
| visual + track | 0.9521 |
| full frozen fusion | **0.9983** |
| refuter: fusion with age removed | **0.9910** |
| refuter: age available only after map/track association | **0.9893** |

The refuter was added only after seeing the headline pass. It moves no
coefficient, threshold, criterion, or headline. It tests an optimistic
assumption in the first implementation: a real system cannot retrieve
`time_since_seen` when neither its map nor tracker associates the observation.
Under that correction, new recall was **0.8014 median** (0.7518 minimum across
seeds), so the mechanism survives but the threshold has almost no margin.

## Sensitivity

Across map noise sigma `{0.10, 0.20, 0.40, 0.75}` m, seen-track recall
`{0.65, 0.75, 0.85, 0.95}`, and new-object false association
`{0, 0.02, 0.05}`:

- frozen fused AUC medians ranged **0.9467–0.9997**;
- association-coupled-age AUC medians ranged **0.8930–0.9968**;
- new-object recall medians ranged **0.7801–0.8794**;
- the worst coupled AUC occurred at 0.75 m map noise, 0.65 tracker recall,
  and 0.05 false association;
- the worst recall occurred with 0.05 false association and low map noise:
  a precise map confidently conflated nearby same-label instances.

The last observation matters. More localization precision alone does not cure
identity ambiguity. At nominal noise, **17.0% median** of new probes landed
near an existing same-label map entry, whereas only 0–0.7% of seen probes
missed their map neighborhood through p95. This asymmetry explains both the
excellent AUC and the marginal new recall.

## Causal replay

At 2 Hz, the 42-frame stream provided 0.35 minutes/seed, 24 first instances,
and 120 repeat observations. Median new-instance recall was **87.5%** and
median repeat suppression **100%**. The minimum new recall was 79.2%; minimum
repeat suppression was 99.17%. This is a short sanity check, not the duration
needed to establish a per-minute rate.

## What the experiment actually verifies

1. H6's weak appearance-only result reproduces on the current model/scene.
2. Truth-derived spatial and temporal mechanism signals are strong enough *in
   principle* to rescue multi-view appearance variation.
3. The gain survives removing the most optimistic age signal.
4. A single class-aware map bit is unsafe for identity: two people, chairs,
   doors, or planters near one another can suppress a genuinely new event.
5. H6's missing synchronized evidence is now a concrete prototype blocker,
   not merely a documentation gap.

## What it does not verify

- no real camera, depth sensor, LIO pose, covariance, track output, moved
  object, moving person, occlusion, relocalization, or target Orin was used;
- segmentation ids and static geometry supplied perfect evaluation identity;
- the corruption probabilities are hypotheses, not measured Parcel tracker
  quality;
- matched crops exclude detector hallucinations; H6's 0.40/min is only carried
  as a fixed empirical point-estimate floor, without uncertainty propagation;
- 24 static render instances are too few for a calibrated production score;
- neither a pleasant gaze response nor a relevant spoken observation was
  evaluated;
- the 0.602-microsecond latency covers weighted scalar arithmetic only. Map
  search, association resolution, track lookup, age lookup, feature
  extraction, serialization, and IPC were not benchmarked.

## New design implication: world delta, not one novelty scalar

The prototype should preserve four separate evidence axes:

```text
identity novelty   is this entity probably new?
place novelty      is this class/entity unusual at this place?
change surprise    is a known entity missing, moved, or materially changed?
social opportunity is now a good time to look, remember, or speak?
```

Static objects may weight place evidence strongly. People and animals should
weight track/appearance identity strongly and map cell weakly. A familiar
chair in a new location should produce a `MOVED_OR_RELOCATED` world delta, not
be averaged into either “new” or “boring.”

The action ladder should also be asymmetric:

1. low-confidence delta: turn gaze/camera locally;
2. collect a second view and depth projection;
3. resolve association and update a governed memory candidate;
4. speak only when relevance, confidence, cooldown, privacy, and conversation
   opportunity all admit it;
5. never allow a noticing to command base motion or invoke a hosted model
   directly.

## Next decisive setup

Record one synchronized 30–60 minute mounted or sensor-rig log containing
`embedding/detection, depth projection, pose + covariance, track id +
generation + confidence, monotonic timestamp, frame/calibration epoch`, with:

- nearby same-class objects;
- owner/non-owner crossings and deliberate track swaps;
- an object moved between known places;
- occlusion/reappearance;
- one SLAM relocalization and one stale-pose interval.

Score identity, place, and change axes separately. Require both <=1 unwanted
spoken noticing/minute and >=80% recall of deliberately planted changes.
That test—not another desktop detector sweep—decides whether to wire H11 into
the prototype.

## Artifacts

- `run_experiment.py` — isolated reproducible harness
- `results.json` — compact final result, all 48 sensitivity cells, and the
  explicit evidence-sufficiency disposition; numerical scores remain frozen
- `/tmp/parcel-h11-codex-20260824/daemon.log` — disposable private-daemon log
