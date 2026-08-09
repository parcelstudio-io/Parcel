# Workstream C — evaluation, simulation, latency, and promotion

## Principle

Evaluation is part of the architecture, not a final demonstration. Every
navigation, perception, behavior, model, and performance card lands with a
baseline/candidate comparison, immutable artifact, failure attribution, and a
statement of what the run does not prove.

The product target and external benchmark target are related but not
interchangeable:

- Parcel product scenarios decide whether the dog is a useful companion.
- BARN/DynaBARN isolate constrained metric and dynamic navigation.
- Habitat isolates indoor PointNav/ObjectNav/social/instruction capabilities.
- MetaUrban isolates procedural urban and social navigation.
- iGibson isolates indoor interactive/social navigation.
- Cityscapes, tracking, OCR, and recorded sensor datasets isolate perception.

“Top 10 percentile across all evals” therefore means top-decile performance on
each **supported, pinned, officially comparable protocol**, not one blended
score and not an incentive to change the robot embodiment. An external win
cannot compensate for a product collision, false-owner follow, road entry,
false action, or latency failure.

## Evidence ladder

| Level | Environment | Purpose | Promotion boundary |
| --- | --- | --- | --- |
| L0 | unit/property/contract tests | validation, state machines, geometry, invariants, determinism | every change |
| L1 | Parcel deterministic headless | full task logic, fault injection, fast CI | pull request |
| L2 | MuJoCo city | same runtime with sensor geometry and dynamic actors | daily/nightly |
| L3 | recorded camera/LiDAR/robot-state replay | real perception, timing, calibration, regression | before model/config promotion |
| L4 | MetaUrban/Habitat/iGibson/HuNavSim/SocNavBench | dynamic city, indoor, social and open-set generalization | scheduled/nightly or research CI |
| L5 | URBAN-SIM/Isaac Lab | articulated Go2 physics, terrain, large-scale learning | research/nightly GPU |
| L6 | hardware-in-loop with motion disabled | DDS, time, camera/LiDAR, model, voice, stop path | device commissioning |
| L7 | tethered/fenced physical courses | low-speed closed-loop motion | supervised release candidate |
| L8 | controlled indoor then mapped outdoor pilot | system and human interaction evidence | restricted deployment only |

No simulator level skips hardware commissioning. No hardware trial begins with
an unbounded learned controller.

## Harness architecture

```text
pinned scenario manifest
  -> environment adapter -------------------+
  -> camera/LiDAR/robot-state observations  |
                                             v
                              unchanged Parcel product stack
                                             |
  scorer-only oracle <---------------- action/feedback trace
       |
       +-> task predicates, collision, shortest path, identity truth
       +-> failure attribution and latency/resource trace join
       `-> immutable JSON report + append-only JSONL/Markdown ledger
```

Rules:

1. Environment adapters translate sensor/action contracts only. They cannot
   alter Parcel policy or expose privileged state to the agent.
2. The oracle is a separate scorer namespace/process. Tests fail if an oracle
   field appears in the agent observation schema.
3. The exact same task request, model/config/checkpoint hashes, seed, and
   resource limits run baseline and candidate.
4. A simulator action is not silently snapped, teleported, or corrected.
5. Success requires agent-issued stop/hold plus the final semantic relation and
   controller settled state.
6. Timeouts, refusals, missing targets, crashes, OOM, dropped frames, stale
   data, and safety interventions remain scored outcomes.
7. Failed/cancelled runs write artifacts. Excluding them biases both quality
   and latency.

## Product scenario matrix

Use pairwise/combinatorial generation plus hand-authored adversarial cases.
Keep a small frozen PR set, a larger public nightly set, and a hidden promotion
set.

### Task families

- region: go to/onto/off road/sidewalk/plaza/path and hold;
- object relation: near/beside/in front of lamppost, bench, entrance, sign;
- named place: find a shop/brand/storefront and approach its safe entrance;
- owner relative: follow direct/behind, wait, recall, orbit once, move a bounded
  number of steps, rejoin after interruption;
- active perception: look around, identify, compare candidates, report absent;
- multi-step/correction: inspect, navigate, wait/posture, change target;
- social reaction: empathy, joke/chuckle, greeting, praise, attention;
- system behavior: low battery, lost localization, stale sensor, degraded
  perception, emergency/manual control;
- conversation-under-motion: answer, acknowledge, barge-in, correction, and
  planner delay while continuing a task safely.

### Environment dimensions

- indoor room, corridor, doorway, lobby, shop, elevator threshold;
- outdoor sidewalk, road edge, plaza, crossing, storefront row, alley;
- open, cluttered, narrow, dead end, alternate route, moved/blocked goal;
- no crowd, crossing pedestrian, group, opposing flow, sudden stop, child-size
  obstacle, similar-looking owner distractor;
- full visibility, outside frustum, partial/full occlusion, re-entry;
- day, night, backlight, glare, shadow, rain/fog simulation, motion blur;
- nominal, timestamp skew, dropped camera, dropped LiDAR, stale transform,
  localization jump, model timeout, GPU pressure, network delay;
- known, ambiguous, duplicate, absent, unreachable, stale-memory target;
- simple imperative, polite/paraphrased, rationale-bearing, multi-step,
  correction, negation, hypothetical, and conversational statement.

### Required vertical slices

1. `go to the sidewalk` starts on a road and succeeds only when the robot is
   stopped inside a safe sidewalk polygon without an illegal road route.
2. `wait by the lamppost` succeeds in a collision-free stand-off region on a
   walkable surface within the relation tolerance—not at the pole center.
3. `circle the owner once` requires enrolled identity, obstacle-free progress,
   approximately one swept revolution, bounded radius error, and settled stop.
4. `follow behind me` tests turn prediction, occlusion, distractors, group
   encounters, ambiguity stop, bounded search, and verified reacquisition.
5. `find the Nike store` separates open-vocabulary storefront detection, OCR/
   logo evidence, metric entrance localization, navigation, and final
   verification; ambiguous/absent scenes must not hallucinate.
6. joke/sadness/low battery cases run while idle, walking, crossing, recovering,
   and manually controlled to test overlay/defer/suppress policy.

## Metric families

Never publish only a mean task-success number.

### Task and navigation

- Success Rate (SR): final predicate true after an agent-issued stop/hold;
- Oracle Success (OSR): predicate was true at any point; `OSR-SR` isolates
  termination failures;
- SPL/soft-SPL, path ratio, distance to goal, elapsed time;
- partial/multi-step progress and verified-success precision;
- collision/contact count and distance traveled per collision;
- minimum static/dynamic/person clearance, near misses, TTC violations;
- road exposure time/distance outside an explicit crossing task;
- stuck time, recovery attempts/success, oscillation and deadlock;
- commanded/executed jerk, angular acceleration, stop overshoot;
- forward-motion fraction, lateral-distance fraction, heading error, curvature;
- gate interventions by layer and whether the planner would have collided.

### Perception and grounding

- road/sidewalk/curb IoU, boundary error and false-safe-region rate;
- object detection AP/recall and absent-target false positive rate;
- OCR exact/normalized word accuracy and named-place precision/recall;
- 3-D entity/goal localization error and covariance calibration;
- semantic-memory benefit, stale-memory error, contradiction/revision counts;
- grounding/search/termination oracle gaps and bounded-not-found correctness.

### Owner and dynamic tracking

- HOTA, IDF1/MOTA, owner recall, ID switches and track fragmentation;
- false-follow/hour and time following an unconfirmed person;
- pose/velocity error and covariance calibration;
- distance/formation error, time outside band, visibility fraction;
- lost-safe-stop correctness, time to reacquire and failed-search honesty;
- trajectory prediction ADE/FDE/NLL/calibration and collision recall at
  0.5/1/2/3 seconds.

### Social and companion behavior

- personal/intimate-space intrusion duration and minimum human clearance;
- passing-side/context compliance, group splitting, freezes/deadlocks;
- reaction appropriateness precision/recall and human preference;
- false physical-action and inappropriate-action rate;
- task interruption, defer/drop/expiry, correction and resume correctness;
- truthful acknowledgement and verified-success claim accuracy;
- emote/reaction duty cycle and any reaction-associated safety event.

### Latency and runtime

Retain the existing user metrics:

- `UserQueryEndToFirstResponse`;
- `UserQueryEndToFirstReasoningResponse`;
- `UserQueryEndToFirstPlanOutput`;
- `UserQueryEndToAcceptedPlan`;
- `QueryEndToFirstSpokenAudio`.

Add spans:

```text
audio capture -> ASR partial/final -> turn commit -> router
camera exposure -> ingest -> detector -> track -> fusion -> prediction
LiDAR sample -> ingest -> pose/map/costmap
semantic query -> detector/OCR -> memory -> GoalRegion -> admission
plan admission -> skill dispatch -> first command -> controller feedback
obstacle observation -> brake request -> issued zero -> confirmed stop
social cue -> proposal -> disposition -> audio/visible onset
barge-in -> model/TTS cancel; correction -> old-plan invalidation
pause -> fresh resume admission
```

Report p50/p95/p99, worst case, sample count, deadline-miss count, frame age,
queue wait, dropped/superseded result count, CPU/GPU utilization, VRAM,
temperature/thermal throttling, and OOM/restart events. A missing timestamp is a
coverage defect, not a zero-millisecond result.

## Failure attribution and oracle replays

Every failed task names the first culpable layer:

```text
L0 route/intent
L1 plan schema/admission
L2a vocabulary/detection
L2b identity/association
L2c metric localization/fusion
L3 semantic search/memory
L4 goal-region/approach construction
L5 global route/local control
L6 safety intervention/deadlock
L7 locomotion/controller feedback
L8 terminal verification/stop
L9 system/resource/deadline
```

Automated counterfactual replay injects one oracle boundary at a time—ground
truth intent, semantic region, owner identity, metric goal, shortest feasible
route, then perfect termination. The first injection that flips the episode
attributes the gap. Oracle data never enters a normal run.

Track `grounding_gap`, `identity_gap`, `search_gap`, `navigation_gap`, and
`termination_gap` per commit. This identifies whether a better model can
actually help.

## External benchmark ladder

| Benchmark | Use in Parcel | Adapter policy | Headline metrics |
| --- | --- | --- | --- |
| [BARN](https://www.cs.utexas.edu/~xiao/BARN/BARN.html) | cluttered metric navigation and entire sense-plan-act path | keep Jackal/official protocol for comparability; separate Go2-scaled diagnostic lane | official success/time/difficulty score plus collision |
| [DynaBARN](https://www.cs.utexas.edu/~pstone/Papers/bib2html/b2hd-ssrr22-nair.html) | systematic moving-obstacle stress | containerized ROS adapter, same Parcel navigator boundary | success, time, collision, dynamic difficulty |
| [Habitat 2020](https://aihabitat.org/challenge/2020/) | historical PointNav/ObjectNav and noisy sensor/actuation regression | agent adapter only; no challenge-code behavior edits | SR, SPL, soft-SPL, distance |
| [Habitat 3.0](https://aihabitat.org/habitat3/) | indoor human following/social interaction | map observations into Parcel track/task contracts | follow success, distance/social metrics, task completion |
| [MetaUrban](https://metadriverse.github.io/metaurban/) | procedural city PointNav/SocialNav | separate service/container; scorer oracle isolated | SR, SPL, SNS, cumulative safety cost |
| [iGibson SocialNav](https://svl.stanford.edu/igibson/challenge.html) | indoor moving-person social regression | containerized adapter; retain official termination thresholds | STL/personal-space compliance and challenge score |
| [SocNavBench](https://github.com/CMU-TBD/SocNavBench) | human-aware trajectory behavior | planner adapter only | safety, comfort, legibility/social metrics |
| Cityscapes + owner/OCR datasets | perception isolation | offline batched inference, frozen preprocessing | IoU/AP/HOTA/IDF1/OCR/pose calibration |

BARN is intentionally not a semantic/voice/companion score. Habitat 2020 is a
stable historical protocol rather than the sole definition of present SOTA.
Official leaderboard language is used only after running the official assets,
container/protocol, and submission/evaluator path.

## Dynamic simulation implementation order

### E0 — improve Parcel headless/MuJoCo first

- extend scenario schema with semantic polygons, storefront/sign evidence,
  owner enrollment IDs, pedestrian groups and intent scripts;
- add moving crossings, opposing flows, stops, occlusions, bottlenecks,
  indoor/outdoor transitions, and object/route changes;
- replace agent-visible metadata semantics with the same observation DTO used
  by physical perception; keep metadata only in the scorer;
- add sensor and compute fault schedules;
- support realtime, faster-than-realtime, step-locked, and replay clocks without
  mixing their timestamps.

### E1 — MetaUrban service

MetaUrban is the first city backend because it procedurally composes urban
layouts, sidewalk objects, vehicles, pedestrians, and SocialNav tasks. Run it
in its own pinned environment and expose a narrow IPC/ROS adapter. Add a Go2
footprint and sensor rig for task-level evaluation, but label the embodiment
diagnostic until articulated dynamics are validated.

### E2 — indoor social environments

Use Habitat 3 for human following and iGibson for interactive/social indoor
cases. Reuse the same Parcel adapter contract. Do not fork instruction logic
inside either evaluator.

### E3 — URBAN-SIM/Isaac Lab

Use this GPU lane for Go2 articulation, contact, rough terrain, perception
domain randomization, and learned policy training. It is slower and more
operationally complex, so it does not replace fast deterministic CI.

## Statistical protocol

- Freeze the scenario/episode manifest before candidate tuning.
- Use paired seeds and common random numbers for baseline/candidate.
- Report Wilson intervals for binary success/safety proportions.
- Use paired bootstrap confidence intervals for continuous metrics.
- Use paired McNemar or an exact paired test for success flips.
- Predeclare primary metrics and non-inferiority margins; do not pick the best
  metric after seeing results.
- Separate tuning/public test/hidden promotion splits.
- Repeat nondeterministic GPU/model runs enough to expose variance.
- Inspect stratified results by task, difficulty, environment, visibility,
  crowd, lighting, sensor fault, and latency load.
- A candidate needs a meaningful held-out gain and must satisfy every hard
  non-regression gate; statistical significance alone is not product value.

Suggested initial hard gates:

- unsafe plan admission, false positive motion from negation/hypothetical, and
  false-owner fallback: zero;
- hard collision and explicit road-keepout violation: zero on the frozen
  promotion set;
- no family SR drop greater than five percentage points;
- no P99 safety/control deadline regression;
- no statistically supported false-safe-region, identity, or verified-success
  precision regression;
- latency target misses remain visible and block promotion when they affect the
  designated critical path.

Zero observed collisions is not a universal probability claim; always report
exposure and confidence bounds.

## GPU and performance evaluation

The current desktop has an RTX 5000 Ada with 32,760 MiB VRAM and a working
driver, but the installed Gemma GPU server consumes roughly 15 GB and Fish can
consume roughly 11 GB. A model that passes alone may fail when conversation,
TTS, segmentation, tracking, semantic search, and simulation coexist.

For every GPU candidate record:

1. driver/runtime/container image and device UUID;
2. model/checkpoint/engine hash, precision, batch, input shape;
3. cold start, warm p50/p95/p99, throughput, and preprocessing/postprocessing;
4. peak/steady VRAM and fragmentation after repeated start/cancel cycles;
5. accuracy before and after ONNX/TensorRT/quantization;
6. co-residency matrix with Gemma, TTS, simulator, and other perception models;
7. behavior under OOM, GPU reset, thermal throttling, and model-service death;
8. CPU fallback/degraded mode and whether motion safely continues or stops.

Navigation/controller and replay suites must remain runnable headlessly without
a GPU. GPU acceleration is an optimization or research dependency for selected
perception/simulation/model lanes, never a prerequisite for emergency stop,
command arbitration, or the deterministic regression core.

## Result artifact and ledger

Each run writes immutable JSON and one append-only ledger record:

```json
{
  "run_id": "parcel-<suite>-<utc>-<nonce>",
  "started_at_utc": "...",
  "suite": "...",
  "protocol_version": "...",
  "description": "one-line change under test",
  "git_commit": "...",
  "dirty_paths": [],
  "config_hashes": {},
  "model_artifacts": {},
  "environment": {},
  "device": {},
  "seed_manifest_hash": "...",
  "baseline_run_id": "...",
  "metrics": {},
  "confidence_intervals": {},
  "failure_histogram": {},
  "latency": {},
  "resources": {},
  "hard_gate_results": {},
  "does_not_prove": [],
  "artifact_paths": []
}
```

Never overwrite historical rows. A run from a dirty tree records all dirty
paths and patch hash. Reports from different protocol/scenario/embodiment
versions are not compared without an explicit bridge study.

## CI and scheduled execution

| Cadence | Suites |
| --- | --- |
| per change | contracts/unit/property, frozen small headless navigation, behavior safety, latency schema/link checks |
| pre-merge | full headless product minival, deterministic replay, baseline/candidate diff, no-oracle-leak check |
| nightly CPU | expanded Parcel tasks, BARN proxy/adapter smoke, fault matrix, long-session executive/voice replay |
| nightly GPU | camera perception datasets, co-residency/load, MetaUrban subset, learned-proposer replay |
| weekly/release | full MetaUrban/Habitat/iGibson/social suites, official external protocol where operational, URBAN-SIM/Isaac subset |
| hardware release | stationary/HIL, fenced courses, indoor social, controlled mapped outdoor route with safety operator |

## First implementation order

1. Freeze the current failing/succeeding rows and add known-failure assertions;
   do not call 0% instruction navigation a passing baseline.
2. Land versioned DTOs, provenance, clocks, and an oracle-isolation test.
3. Add deterministic event/sensor replay and fault injection.
4. Build a single vertical `GoalRegion -> action -> feedback -> predicate`
   harness using both `grid_v1` and a stubbed Nav2 action server.
5. Add MetaUrban as a separate dynamic-city service only after the adapter
   contract and scorer separation pass.
6. Add perception dataset runners and owner-identity cases before enabling real
   detections in navigation.
7. Run baseline/candidate pairs at every subsequent card; promote only through
   the evidence ladder.
