# H11 — spatiotemporal noticing · DESIGN (Codex) · 2026-08-24

## Hypothesis

For a prototype dog, a noticing score that combines actual visual-gallery
novelty with label-aware map-cell familiarity, short-term track persistence,
and time-since-seen will separate new from re-encountered objects with
**AUC >= 0.80**, while suppressing at least **95%** of repeat noticings and
producing at most **1 false repeat noticing/minute**. Its non-neural decision
cost will remain below **0.5 ms p95/observation** on this desktop.

This specifically tests the remedy proposed after H6 refuted pure gallery
novelty (paired all-label AUC 0.724). It does not test object detection,
localization, tracking, or Orin throughput as complete product systems.

## Why this matters to the physical milestone

A companion that announces every visually changed crop is annoying, while a
companion that never notices a moved or newly encountered object is inert.
Appearance alone changed too much across range and bearing in H6. A mounted
robot will also know approximately *where* an observation occurred, whether a
tracker believes it is the same object, and how recently it reacted. Those
signals are cheap and body-local. If their combination cannot beat H6's
gallery, a continuous generalized-noticing loop should not enter Milestone 1.

## Evidence and data boundary

The experiment will regenerate H6's 42-frame `city_block.xml` render protocol
at the current tree revision, use the same OWLv2 fp16 detector and SigLIP-2
fp16 image embedder, and reproduce H6's paired new-versus-seen visual score.
The committed H6 compact result (AUC 0.7235915493, 142 pairs) is the historical
anchor; raw pair rows and the render corpus were not preserved in git.

H6 did **not** record a SLAM map cell, causal timestamps, or tracker output.
Consequently:

- visual scores, detections, segmentation identities, camera poses, depth,
  and static geometry positions are replay/simulation observations;
- map observation noise and track association failures are a seeded
  **mechanism simulation**, not empirical tracker/SLAM accuracy;
- no result may be described as mounted, real-sensor, or target-compute proof.

This missing synchronized `(embedding, depth, pose, track_id, timestamp)` log
is itself a decision finding for the prototype sensor contract.

## Fixed score (chosen before running)

For each label-matched probe crop:

```text
visual = clamp(raw_gallery_novelty / 0.20, 0, 1)
map    = 1 when no same-label memory lies in the 3x3 neighborhood, else 0
track  = 1 when no active/reidentified track matches, else 0
age    = clamp(seconds_since_seen / 30, 0, 1); unseen = 1

fused = 0.35*visual + 0.35*map + 0.20*track + 0.10*age
```

The fixed noticing threshold is **0.70**. Map cells are 0.75 m square. The
nominal corruption arm applies independent Gaussian map noise with sigma
0.20 m, seen-track association recall 0.85, and new-object false association
probability 0.02. Every random arm uses seeds 0–99. No coefficient, threshold,
cell size, noise level, or seed may move after results are inspected.

## Experiment

1. Rebuild H6 renders and clips in an isolated temporary directory. Start a
   private perception daemon/socket; never touch the owner's stack.
2. Match OWLv2 detections to H6 segmentation truth and embed the matched crop.
   Recreate the paired protocol: identical probe crop, one gallery excluding
   its instance (`new`) and one adding other views of it (`seen`).
3. Derive static world positions from the scene geometry indexed by the H6
   segmentation id. Construct label-aware map memories and inject only the
   pre-registered localization noise.
4. Simulate tracker association at nominal settings and across the full
   sensitivity grid: seen recall `{0.65, 0.75, 0.85, 0.95}`, new false-match
   `{0.00, 0.02, 0.05}`, map sigma `{0.10, 0.20, 0.40, 0.75}` m.
5. Report AUC for visual-only, visual+age, visual+map, visual+track, and fused
   ablations. The headline is the median nominal result across 100 seeds;
   sensitivity rows are evidence of fragility, not tuning opportunities.
6. Replay the observations causally at 2 Hz. A first correctly matched
   instance may trigger once; another trigger for that instance inside 60 s is
   a false repeat. Report new-object recall, repeat suppression, and false
   repeats/minute. H6's separately measured 0.40 false hallucinations/minute
   is carried as an empirical floor, not silently treated as fixed by this
   matched-only harness.
7. Benchmark 100,000 score decisions after warm-up and report p50/p95. Record
   model inference separately; the criterion applies only to the fusion
   decision because H6 already measured the neural seat.

## Pre-registered measurements

| row | metric | criterion |
|---|---|---|
| S1 | regenerated pure-gallery paired AUC | report; within 0.03 of H6's 0.724 or flag corpus/model drift |
| S2 | nominal fused paired AUC, median of 100 seeds | >= 0.80 |
| S3 | nominal new-object recall at threshold 0.70 | >= 0.80 |
| S4 | repeat suppression within 60 s | >= 95% |
| S5 | matched-object false repeats/min + H6 hallucination floor | <= 1.0/min |
| S6 | fusion decision p95 | <= 0.5 ms/observation |
| S7 | worst sensitivity cell and failure frontier | report; no pass requirement |

## What would refute or limit the hypothesis

- S2 below 0.80 refutes the proposed fusion.
- S3 below 0.80 means the threshold is too conservative for prototype use;
  it is a refutation, not permission to tune on this corpus.
- S4/S5 failure means spatial or tracking errors still cause an annoying dog.
- A pass only in the oracle/high-track-recall arms is mechanism confirmation,
  not prototype readiness.
- Any S1 drift over 0.03 makes comparisons to H6 non-equivalent; report the
  new run but do not claim improvement over H6.

## Prototype decision if confirmed

Implement the score only after the observation spine emits synchronized
depth, pose/covariance, stable track ids, monotonic timestamps, frame age, and
calibration epochs. Keep all signals and state local. A noticing may propose a
gaze shift, memory candidate, or bounded utterance; it may never command base
motion or call a hosted model directly.

## Post-run evidence-scope clarification

This clarification changes no frozen score, weight, threshold, arm, or
arithmetic bar:

- the map, track, and age mechanism signals are generated around MuJoCo
  segmentation-truth identity and class; seeded noise/failure probabilities
  do not turn them into measured SLAM or tracker outputs;
- S5 adds H6's 0.40 false-hallucinations/minute point estimate as a fixed
  floor to every simulated repeat rate; it does not propagate H6 uncertainty;
- S6 times the four-input weighted scalar arithmetic only. It excludes map
  lookup, track association, age lookup, feature extraction, serialization,
  and IPC;
- passing the pre-registered numerical comparisons is distinct from having
  enough evidence to confirm a physical-prototype false rate. A 0.35-minute
  causal replay per seed is insufficient for that claim.

## OWNS

Only `research/20260824/spatiotemporal-noticing/**`. No product, existing
research, test, scrum, gateway, or NAV-CORE edits.
