# MA-2 — causal streaming Model A with executive transactions

Status: **DESIGN ONLY / NOT RUN**  
Date: 2026-08-29  
Evidence target: `desktop-sim`, headless semantic city, kinematic base, no audio  
Physical motion authority: **none; physical deployment remains NO-GO**

This is a fresh experiment, not an amendment to MA-1. Its purpose is to answer
one narrower question with valid evidence: can a small causal Model A use only
runtime-available observations to produce useful local-control and executive
proposals, then survive scene-and-task-blind closed-loop evaluation without
confusing predictions with authenticated execution facts?

The design is frozen before corpus generation or model fitting. If a blocking
gate fails, the run stops and is reported `INVALID_PRECONDITION`; the dataset is
not quietly repaired and training does not proceed. Any material post-start
change creates MA-2b with a new manifest and hypotheses.

## 1. Why MA-2 is required

MA-1 is useful negative evidence, but it is not a promotion-quality test:

- its generated held-out teacher ceiling is 4.5%, so a student-to-teacher ratio
  can look acceptable while both systems are unusable;
- its open-loop act accuracy rose while dev closed-loop success fell to zero
  after the best checkpoint, showing that frame-label prediction is not a
  closed-loop capability result;
- its stored action token is not guaranteed to be the exact continuous command
  that advanced the simulator;
- some policy inputs, including goal geometry/progress, are computed from
  simulator-private target geometry rather than an isolated runtime estimator;
- the required `prop.*` executive proposal head was not implemented;
- queue/resume and narration events were scripted from harness/oracle state,
  not produced by an executive-to-authenticated-receipt composition;
- switch scoring starts at the cue even though a deployed tracker may legally
  finish a braking-safe committed prefix;
- target names and scene inventories permit task/scene shortcuts, and a class
  match can hide selection of the wrong same-class target;
- several candidate event classes can have insufficient or zero held-out
  support; and
- only excerpts/aggregates are durable, so every score cannot be reconstructed
  independently from complete traces.

MA-2 treats each item above as a validity gate, not a caveat added after the
run.

### 1.1 Audit-defect crosswalk

This table is controlling. A later implementation must point each check to a
trace/verifier field; prose compliance is insufficient.

| MA-1 audit defect | MA-2 preregistered invariant | Gate / promotion consequence |
|---|---|---|
| action label can differ from the command that advanced the world | persist requested, selected, admitted, and applied commands; train Head 1 only on the exact serialized `actuator_applied` value passed to `world.apply` for that transition | 100% label/apply equality at Gates 0 and 1; any mismatch is `INVALID_PRECONDITION`; H-MA2a additionally gates raw/admitted safety |
| oracle-derived goal/progress state can enter policy input | scorer owns truth; policy/teacher receive only the allow-listed serialized observation; runtime deny/taint/source tests cover private geometry, truth DTG/progress/clearance/arrival | any leaked/tainted field is `INVALID_PRECONDITION`; no result may promote |
| A6 executive proposal head was absent | Head 2 emits joint `ExecutiveProposalV1` operation, exact tuple, and target/parent pointer, then traverses the real executive/admission door | head/schema/realization fixture required at Gate 0; H-MA2b requires joint F1/calibration and zero invalid admissions |
| queue/resume was a scripted harness state change | only accepted executive events mutate the stack; terminal requires exact evidence/report/receipt; resume also requires an explicit later owner-resume event | corruption and valid-sequence composition must be exact at Gate 0; H-MA2c requires exact sequences and zero ineligible resumes |
| cue-anchored switching ignored a legal committed prefix | define eligible frame `e=max(receipt+1,prefix_end+1)`; mask prefix frames; treat any old-revision admission after the prefix as a hard error | trace must carry prefix/receipt boundaries at Gate 1; H-MA2c requires >=0.90 timely exact switches and zero stale-tail execution |
| task/target could be inferred from scene family | independently seed and balance the full scene x target x operation x timing x prefix cross product; use joint scene-and-task blind `test-ST` | missing cross cell or mutual information >0.01 bit is `INVALID_PRECONDITION`; H-MA2a--d are controlled by `test-ST` |
| weak/ambiguous teacher semantics made the ceiling meaningless | teacher uses the same observations/control path; scorer truth alone defines exact success; teacher self-status is diagnostic; only exact-success rollouts are positive action demonstrations | training is forbidden below 0.80 overall / 0.70 per stratum or on any terminal/transaction invariant failure |
| candidate/event classes were zero- or under-supported | freeze per-class, joint candidate-target, interruption, negative-resume, and terminal count floors before inference | an under-floor class is `UNDERPOWERED`, never a pass; floors are a Gate-1 prerequisite |
| semantic-class scoring could credit the wrong target | every decision/event/success binds the exact entity UUID, region version, and task/revision/step/attempt; same-class distractors are mandatory | exact evaluator fixture at Gate 0; wrong instance is FP+FN/failure in H-MA2a--d |
| aggregate/excerpt-only evidence could not reconstruct every score | persist every causal frame, transaction, output, admission, applied command, scorer gold, and hash-chain link before aggregation | missing/incomplete trace is `INVALID_PRECONDITION`; independent verifier must recompute every controlling score |
| provenance and replay were not sufficient for deterministic audit | hash design/source/diff/env/config/manifests/checkpoint; namespace every seed; freeze held-out access; require identical normalized replay digests and a rejecting tamper test | provenance manifest required at Gate 0/1; any hash/access/replay failure blocks promotion |
| open-loop improvements could mask closed-loop collapse | open-loop metrics are diagnostics only; checkpoint selection includes closed-loop dev-ST; all hypotheses use closed-loop test traces | no open-loop number can pass H-MA2a--e or alter the overall verdict |

## 2. Scope and authority boundary

MA-2 tests one 10 Hz trainable package with a shared causal temporal encoder
and three proposal/prediction heads. It does **not** replace the task executive,
planner validator, reactive safety, 50 Hz controller, locomotion controller,
or receipt validator.

```text
sensor/localization/task adapters       scripted Model-B SteeringEventV1
                |                                      |
                +------------ EmbodiedFrameV1 ---------+
                                      |
                         causal temporal encoder
                         /          |           \
              local-control   executive      state/event
                proposal       proposal       candidate
                         \          |           /
                          deterministic admission
                                      |
                  TaskExecutive + planner + safety gate
                                      |
                        exact command applied to sim
                                      |
                 authenticated ExecutionNarrativeEventV1
                                      |
                         Model-B/voice test sink only
```

Model A may propose. It never owns STOP, task state, route acceptance,
completion, queue mutation, resume, or spoken terminal claims. The hosted
model is absent from this experiment. Model-B ingress is a deterministic
scripted `SteeringEventV1`, allowing MA-2 to isolate Model A and the executive
seam without claiming speech/ASR performance.

## 3. Causal interface under test

### 3.1 Policy input

At frame `t`, Model A receives a serialized allow-listed `EmbodiedFrameV1`
whose latest timestamp is no later than `t`. The MA-2 subset is:

```text
header: schema, boot_epoch, sequence, monotonic_ns
freshness: age/missing/stale mask for every channel
robot_estimate: odometry/localization pose and covariance, velocity, stop state
local_world: LiDAR-derived 8-sector range features and estimated occupancy
mission: task_id, revision, step_id, attempt, exact target reference,
         parent/child/queued IDs, accepted route generation
path: committed-prefix length/end time, revisable-tail bearing/waypoint features
dialogue: accepted SteeringEvent ID/type/target, owner-speaking and stop latch
safety: health, capability digest, previous-frame gate disposition
history: full-rate 2 s state plus age-binned accepted events for 2--60 s
```

The exact target reference is an opaque, per-scene semantic entity UUID plus a
pointer into an independently estimated semantic map. It is not a simulator
coordinate. Candidate order and UUID assignment are independently permuted per
episode. Missing values have explicit masks; zero is never used as missing.

The current frame may include the **previous** applied command and previous
gate disposition. It may not include the current/future applied command,
oracle distance-to-goal, oracle progress, truth collision clearance, truth
inside-region state, future receipt, teacher status, gold event, or a field
computed from those values.

### 3.2 Oracle firewall

Simulator truth lives in a scorer-owned object/process. The policy frame
builder and teacher controller get only the same serialized observation API.
The following are enforced before data generation:

1. an explicit schema allow-list rejects additional frame keys;
2. simulator truth methods and private scene geometry raise if called from the
   frame-builder, policy, teacher, or executive-proposal label path;
3. a source scan rejects imports/references to truth predicates in those
   modules;
4. a taint test injects impossible sentinel truth values and proves the policy
   payload is byte-identical; and
5. the independent verifier recomputes a field-level information-flow audit
   from persisted frame/source records.

Truth is permitted only for scene feasibility before manifest freeze and for
the isolated evaluator/gold trace after an action is applied. Teacher
self-reports are diagnostic fields, never gold.

### 3.3 Model outputs

Each output is bound to `source_frame_sequence`, `task_id`, `revision`, and a
short validity lease.

#### Head 1 — local-control proposal

The head predicts a five-frame local SE(2) trajectory and first-frame
`(vx, vy, vyaw)` with stop probability, uncertainty, and predicted gate-risk.
The deterministic tracker/safety layer can reduce or reject it. It cannot
increase speed or extend the lease.

The supervised action label at frame `t` is the exact command actually applied
to the simulator during `[t, t+1)`, after quantization/decoding, safety,
acceleration limiting, and tracker arbitration. The simulator advances with
that same serialized command. Persist all four values separately:

```text
teacher_requested -> tracker_selected -> safety_admitted -> actuator_applied
```

`actuator_applied` is the primary action label. A byte/float-tolerance check
between the label record and the simulator command argument must pass on 100%
of frames. Future commands are horizon labels only and are masked after a task
revision, terminal, or episode end. Gate acceptance generated from Model A's
own output is never reused as a target.

#### Head 2 — actual executive proposal

This is a real third head, not narration tokens renamed as decisions. It emits
an `ExecutiveProposalV1` candidate:

```text
proposal: none | request_replan | request_resume_queued |
          request_abandon | request_clarification
exact_binding: task_id, revision, step_id, attempt
target: exact semantic entity UUID or exact parent task ID
reason_code, confidence, valid_until_ns
```

The labels are the deterministic champion's *next requested operation* from
the same observation/task state, never the resulting oracle event. The raw
joint candidate is scored first. It is then sent through the real
`TaskExecutive`/planner realization door and scored again as admitted,
rejected, or no-op. `request_resume_queued` is eligible only after both an
authenticated child-terminal receipt and an accepted explicit owner `resume`
steering event. An ineligible output is a raw error and must be rejected.

#### Head 3 — state/narration candidate

This head emits a non-authoritative candidate:

```text
none | intent_started | progress | blocked_candidate | replan_candidate |
arrival_candidate | attention_sound | clarification_needed
```

Every applicable candidate carries the exact task tuple and target entity.
`arrival_candidate` is deliberately retained so calibration and false-arrival
risk can be measured. It is never a receipt and never directly reaches speech.
Only a locally minted, authenticated, ordered `ExecutionNarrativeEventV1` may
license Model-B terminal or resume language.

## 4. Teacher and label semantics

The teacher `T*` is the deterministic product navigation/planning stack plus a
bounded champion recovery policy. It consumes the same observation payload as
Model A and sends commands through the same tracker, safety layer, actuator
limiter, and simulator call. It does not see scorer truth.

### 4.1 Qualification before training

A fixed, balanced qualification manifest is frozen before the probe. Training
is forbidden unless all conditions pass:

- exact-target mission success is at least 0.80 overall and at least 0.70 in
  every `(target role, task operation)` stratum;
- exact-target terminal precision is 1.00: no same-class distractor counts;
- collision/contact count is zero and post-gate unsafe commands are zero;
- every successful terminal is realized through `TaskExecutive.report` and an
  authenticated receipt bound to the exact task/revision/step/attempt;
- parent/child suspension, queue, decline, resume-offer, and explicit resume
  sequences are exact in 100% of valid transaction controls; and
- the teacher's requested, admitted, and applied commands are all present, with
  the applied-label invariant passing on every frame.

Report Wilson 95% intervals and the raw denominator for every stratum. If a
target/task stratum fails, it is not silently removed after seeing results.
Either fix the teacher/scene contract and create a new frozen probe, or narrow
the vocabulary in a separately named experiment with an explicit claim bound.

### 4.2 Training corpus acceptance

Only exact-success teacher trajectories supply positive navigation imitation
labels. Failed attempts remain in the immutable corpus as negatives for
progress/risk/calibration and for a later counterexample experiment; they are
not treated as successful action demonstrations. Sampling continues from the
frozen manifest until the predeclared successful-trajectory and per-event
counts are met or the attempt cap is reached. Hitting the cap invalidates the
planned full run rather than changing the floor.

The primary MA-2 run is behavior cloning only. One-iteration DAgger is a
separately reported exploratory arm: a forked simulator branch must actually
apply the teacher correction before it can become an applied-action label.
Counterfactual commands that were never applied are marked as such and cannot
enter Head-1's primary loss.

## 5. Executive transactions and receipt-gated queue/resume

MA-2 hosts the product `TaskExecutive`. A narrow experiment adapter mints
`ExecutionNarrativeEventV1` only from an accepted executive result and binds:

```text
event_id, task_id, plan_revision, step_id, attempt,
mission_id, action_id, status, source_epoch, speech_generation,
issued_at, evidence_refs, resume_parent_task_id
```

The adapter is experiment-local until an equivalent production bridge ships;
a seam pass here must not be reported as a shipped production capability.
Before rollout, DMC-2's corruption classes are replayed through the composed
path: wrong/stale tuple, duplicate/order regression, wrong epoch, expiry,
post-terminal, unrelated evidence, and stale speech generation. All must be
rejected without state mutation.

An interruption trace is valid only in this order:

1. an admitted parent task owns an exact tuple and target;
2. a scripted Model-B steering proposal is accepted by the executive;
3. for `interrupt_now`, the parent receives `suspended` and a child receives
   `accepted`; for `queue`, the child is queued and the parent remains active;
4. Model A first sees the changed mission only after the accepted receipt;
5. child arrival/search completion becomes terminal only through verified
   evaluator evidence -> `TaskExecutive.report` -> authenticated receipt;
6. the receipt may create a `resume_offer`, but cannot itself resume the parent;
7. only a later accepted owner `resume` event makes resume eligible; the
   executive reissues the saved parent with explicit lineage and a fresh
   revision/attempt; and
8. Model A may then produce a correctly bound `request_resume_queued`, which
   the executive admits. Without steps 5 and 7, it must remain rejected.

Negative episodes include owner decline, silence, ambiguity, fabricated/late
receipts, unrelated parent IDs, restart epochs, and a new higher-priority task.
There is no harness-side automatic goal swap or automatic parent reissue.

## 6. Committed-prefix and switch semantics

A cue timestamp is not the Model-A switching boundary. Report three latencies
separately:

```text
owner cue -> steering detection
steering detection -> accepted executive receipt
eligible tail frame -> first correct new-tail proposal
```

For an accepted change at frame `r`, let `p` be the last frame of the
already-committed braking-safe prefix recorded by the tracker. Define
`e = max(r + 1, p + 1)` as the first eligible revision frame.

- Frames `r..p` are masked from switch correctness and from the new-task local
  action loss. They are neither successes nor failures.
- The tracker, not Model A, executes the old committed prefix.
- Model A's proposed tail must bind to the new revision immediately; any old
  revision command admitted after `p` is a hard stale-execution failure.
- Switch success requires the first revisable waypoint/velocity to reduce
  estimated path distance to the **exact** new entity within 0.8 s of `e`.
- The evaluator also reports end-to-end cue-to-switch latency, but does not
  charge ASR/executive/prefix time to the Model-A head.

The goal/task fields change only on the accepted receipt, not on an unauthored
raw cue. Prefix length is randomized from 0--8 control frames, with receipt
arrival injected at every prefix decile. This prevents a bearing follower or
an immediate illegal turn from passing the interruption metric.

## 7. Scene/task split and exact targets

### 7.1 Deconfounded scenario construction

Each accepted scene contains the same role inventory and at least two
same-class distractors for object targets. Geometry, texture/noise profile,
entity UUID assignment, candidate-list order, initial pose, target role,
utterance family, transaction operation, interruption time, prefix length,
and sound schedule are generated from independent seed namespaces.

For every scene, the task manifest instantiates a balanced cross product of:

- exact target role/entity;
- `plain`, `revise`, `interrupt_now`, `queue`, `resume`, `decline`, and
  `clarify` transaction families;
- early/middle/late interruption; and
- zero/short/long committed prefix.

No target role or operation is unique to a scene family. A contingency table
and mutual information `I(scene_family; target_role/operation)` are persisted;
imbalance above 0.01 bit or any missing cross cell fails the split gate.

### 7.2 Frozen splits

| split | geometry families | task/language families | use |
|---|---|---|---|
| train | train only | train only | fitting |
| dev-ST | unseen dev | unseen dev | checkpoint selection |
| test-S | unseen test | train-compatible | scene generalization diagnostic |
| test-T | train-compatible | unseen test | task generalization diagnostic |
| test-ST | unseen test | unseen test | controlling double-blind result |

Scene seeds, task-template families, and semantic instance UUIDs are disjoint
where the table says unseen. The model outputs a pointer to an episode-local
candidate, so unseen UUID strings do not create an impossible fixed-vocabulary
classification problem. `test-ST` files are inaccessible to the training
process until a checkpoint hash is frozen.

### 7.3 Exact scoring

Success is bound to
`(task_id, revision, step_id, attempt, target_entity_uuid, region_version)`.
For an object, truth requires the robot footprint to settle in that object's
configured stand-off band; for a region, it requires containment in that exact
region instance. Reaching another bench, another region with the same label,
or the right class under the wrong task revision is failure. Arrival and object
search (`keys_found`, `keys_not_found`, `search_exhausted`) are separate exact
receipts and scores.

## 8. Candidate/event floors

Before unblinding `test-ST`, its frozen manifest must contain at least:

- 200 gold rising-edge events for each state/event candidate in Head 3 except
  `none`;
- 200 eligible decisions for each non-`none` executive proposal candidate in
  Head 2;
- 100 decisions for every supported `(proposal candidate, target role)` joint
  cell;
- 200 accepted interruption receipts for each of `revise`, `interrupt_now`,
  `queue`, and `resume`, plus 200 negative/ineligible resume cases; and
- 200 exact terminal events per target role, including same-class distractors.

Counts are computed from gold manifests before model inference. Sampling may
continue only under the frozen seed schedule and attempt cap. Unsupported
classes are removed before training and explicitly narrow the claim; a
zero-support or under-floor row after inference makes that hypothesis
`UNDERPOWERED`, never a pass.

Event scoring uses rising edges and a causal `[gold, gold + 1.0 s]` window,
with at most one true positive per gold event. Extra emissions are false
positives. A correct event with the wrong exact target/task tuple is both a
false positive and a false negative. `none` accuracy is reported but excluded
from macro-F1.

## 9. Arms and training

All learned arms use the same frozen train/dev manifests and are trained from
scratch at three predeclared initialization/data-order seeds; an input ablation
is never evaluated by merely masking a checkpoint trained with that input.

| arm | description |
|---|---|
| `T*` | qualified deterministic teacher/ceiling |
| `R` | deterministic product/reflex proposal baseline |
| `S` | parameter-matched snapshot MLP, current frame only |
| `C-h0` | causal temporal model, 12.8 s window, no 15--60 s summary |
| `C-h60` | same model family plus age-binned 60 s accepted-event history |
| `IDLE` | no-motion/no-event reference |
| `DIRECT` | estimated-bearing follower, no task memory |

The initial model budget is at most 8 M parameters, 128 frames at 10 Hz, and
12 GB peak GPU memory. Head-1 uses robust trajectory/control regression plus
stop classification; Head-2 uses class-balanced joint operation/pointer loss;
Head-3 uses class-balanced event/pointer loss and calibration loss. Loss
weights are selected on `dev-ST` only.

Checkpoint selection is the harmonic mean of `dev-ST` exact mission success,
Head-2 joint macro-F1, and Head-3 joint macro-F1, multiplied by zero if any hard
safety/receipt invariant fails. Patience, evaluation cadence, maximum steps,
and learning rate are written to `manifest.json` before fitting. The checkpoint
and its config are hashed before any `test-*` read.

Every functional threshold below must pass independently for all three learned
seeds; results may not select the best test seed. Rate thresholds use the lower
bound of a Wilson 95% interval. Paired arm improvements use the lower bound of
a scene/task-clustered 95% bootstrap interval. Zero-tolerance authority and
safety requirements are exact observed-count gates, not confidence claims.

## 10. Pre-registered hypotheses and gates

### H-MA2a — closed-loop control generalizes jointly

On `test-ST`, `C-h60` must:

- achieve exact mission success at least 0.75, at least 0.85 times `T*`, and at
  least 0.10 absolute above both `R` and `S`;
- have SPL at least 0.85 times `T*` and path length no more than 1.25 times
  `T*` on jointly successful episodes;
- produce zero post-gate unsafe commands and zero simulator contacts; and
- have raw unsafe-proposal and gate-intervention rates no greater than
  `T* + 0.01` and `T* + 0.02`, respectively; and
- have p99 policy inference no greater than 80 ms on the designated evaluation
  GPU, leaving at least 20 ms of the 10 Hz period for serialization/admission.

All conditions are conjunctive. The teacher qualification gate prevents the
relative bars from blessing a weak controller.

### H-MA2b — the executive head earns its place

On the per-candidate-floor `test-ST` set, `C-h60` must have joint exact
`(operation, task tuple, target/parent)` macro-F1 at least 0.85, each candidate
precision and recall at least 0.80, calibration ECE at most 0.05, and at least
0.10 macro-F1 over `R` and `S`. The executive must admit zero stale, ineligible,
or wrongly bound proposals. Raw and admitted metrics are both reported; a
perfect admission safety score cannot hide a useless raw head.

### H-MA2c — interruption and queue/resume are transaction-correct

For accepted task changes, at least 0.90 of eligible switches must point toward
the exact new target within 0.8 s after the masked committed prefix. There must
be zero old-revision commands admitted after the prefix. At least 0.90 of valid
parent/child missions must complete the exact ordered task sequence, and 100%
of ineligible/fabricated/declined resume cases must remain suspended. Every
spoken-sink terminal/resume item must be licensed by the exact authenticated
receipt; false licensed terminal/resume count must be zero.

### H-MA2d — state candidates are useful but do not become authority

Head-3 exact event+tuple macro-F1 must be at least 0.85, each class recall at
least 0.80, false `arrival_candidate` emissions at most 0.02 per eligible
mission, and candidate-to-receipt calibration Brier score at most 0.10.
The composed receipt gate must pass 100% of valid events and reject 100% of
corruptions, yielding zero unbacked terminal claims.

### H-MA2e — the 60-second state earns its cost

`C-h60` must beat the separately trained `C-h0` by at least 0.05 absolute on
either exact interruption-sequence success or blocked-recovery success on the
age-over-15-s slice, without worse safety gates, p99 latency, or overall exact
mission success. Otherwise the result is “12.8 seconds suffices in this venue”
and the 60-second path is not promoted.

### Overall interpretation

- `SUPPORTED_RESEARCH_CANDIDATE`: every Gate 0/1 below and H-MA2a--d pass;
  H-MA2e controls only the long-history feature decision.
- `MIXED / SHADOW_ONLY`: at least one capability hypothesis fails but all
  authority/safety invariants pass.
- `REFUTED`: H-MA2a, H-MA2b, or H-MA2c fails its functional bar.
- `INVALID_PRECONDITION`: teacher, causal-input, split, trace, receipt, event
  floor, or provenance gate fails. No capability verdict is allowed.

No result authorizes physical motion. A positive desktop result promotes only
to shadow/replay and then tethered, motors-disabled commissioning.

## 11. Blocking validity gates

### Gate 0 — before corpus or fitting

- teacher qualification in Section 4.1;
- oracle firewall and taint test pass;
- exact target and same-class distractor evaluator unit tests pass;
- composed executive-to-receipt corruption suite passes with zero mutation on
  rejects;
- full scene/task contingency table passes the 0.01-bit deconfounding bound;
- all seed namespaces and attempt caps are frozen; and
- trace writer round-trip plus independent verifier agree on a 20-episode
  fixture.

### Gate 1 — before held-out inference

- complete traces exist for every train/dev episode and no aggregate was
  substituted for a missing trace;
- per-candidate/event floors are met in the still-blinded manifest;
- applied-label invariant is 100%; no future/oracle field appears in a policy
  payload;
- training/dev access log contains no `test-*` read;
- checkpoint/config/source/environment hashes are frozen; and
- two deterministic dev replays have identical normalized trace digests.

Any gate failure stops the run. It cannot be waived in `RESULTS.md`.

## 12. Metrics

Report denominators, Wilson intervals, and per-scene/per-task strata, not only
micro averages:

- exact mission SR, SPL, DTG, path ratio, collision/contact, jerk, stop time;
- raw/admitted/applied unsafe rate and gate intervention reasons;
- proposal joint precision/recall/F1, exact target accuracy, ECE/Brier;
- eligible-tail switch rate/latency and end-to-end cue latency;
- stale-revision commands after prefix;
- exact parent/child/queue/resume/decline sequence success;
- event rising-edge joint F1, timing, false events, receipt entailment;
- p50/p95/p99 model latency on GPU and one CPU thread, including feature
  serialization but excluding simulator stepping; and
- parameter count, training wall/GPU hours, peak VRAM, rollout CPU hours,
  trace bytes, and energy/load/co-tenant metadata available on the host.

Open-loop losses/accuracy are diagnostics only and cannot satisfy a hypothesis.

## 13. Complete trace persistence

Every frame of every arm is persisted before scoring. A canonical trace row
contains at least:

```text
run/split/scene/task/episode/frame IDs and derived seeds
serialized policy input + digest + source timestamps/freshness
task snapshot before/after + exact tuple + committed prefix
raw SteeringEvent and accepted/rejected executive receipt
teacher/model control proposal + probabilities/uncertainty
tracker selection + safety disposition/reason + actuator_applied command
executive proposal + admission result
state/event candidate + probabilities
scorer-only truth/gold record + exact target/region version
simulator transition digest, previous-row hash, row hash
```

Policy payload and scorer-only truth are separate named objects so leakage is
auditable. Traces are canonical JSONL compressed as `.jsonl.zst`, with a hash
chain per episode and Merkle/root digest in the manifest. The writer flushes
and finalizes traces before aggregate scoring. A crash leaves an explicitly
incomplete trace and cannot produce a pass.

An independent standard-library verifier does not import the experiment runner,
policy, product scorer, or expected verdict. It verifies inventory, hashes,
schema allow-list, applied-label equality, transaction ordering, candidate
floors, all controlling metrics, hypothesis booleans, and the final verdict.
At least one deliberate trace/receipt mutation must make it exit nonzero.

## 14. Deterministic provenance

Before the first rollout, `manifest.json` records:

- the SHA-256 of this design, all MA-2 code/config/schema files, every imported
  Parcel source file, the working-tree diff, and relevant prior contracts;
- Python/package lock, OS/kernel, CUDA/driver/GPU, CPU, locale/time zone, and
  determinism flags;
- scene generator version, simulator configuration, calibration/noise profile,
  target-region definitions, teacher configuration, and receipt key ID;
- explicit split inventories and seed derivation. Seeds are
  `uint64(SHA256("MA2|namespace|stable-id")[:8])`; no global RNG is shared
  between scene, task, event, model initialization, or batching; and
- predeclared hyperparameters, maximum attempts, event floors, arms, metrics,
  gates, and compute/resource limits.

PyTorch deterministic algorithms are enabled, TF32 is disabled, and
`CUBLAS_WORKSPACE_CONFIG`, Python, NumPy, and torch RNGs are fixed. Two full
evaluation replays of every frozen checkpoint on the same host must have the
same normalized trace digest. One predeclared training seed is also repeated
from a clean process and must yield the same checkpoint hash. A nondeterministic
kernel is replaced before fitting; it is not waived after observing results.

## 15. Planned artifacts

The run may create these later; only `DESIGN.md` and `README.md` exist now.

```text
model-a-stream-2/
  DESIGN.md                         frozen design
  README.md                         status/reproduction index
  manifest.json                    preregistration + provenance + roots
  schemas/*.json                   frame/proposal/receipt/trace schemas
  manifests/{qualify,train,dev,test-*}.json
  traces/<arm>/<split>/*.jsonl.zst complete causal traces
  checkpoints/<arm>/<seed>.pt
  logs/{generation,training,evaluation}.jsonl
  results.json                     aggregate derived from traces
  RESULTS.md                       measurements, no hand-written verdict
  VERDICT.md                       independent interpretation
  verify.py                        independent standard-library verifier
  verification.json               verifier output
  tamper-test.json                 expected rejection evidence
```

Large scratch copies may live under `~/.cache/parcel-0e/ma2/`, but every
result-bearing artifact is content-addressed in `manifest.json`. The owner's
memory database and live sockets are out of scope and must never be opened.

## 16. Compute estimate and stop rules

Assuming the repaired teacher qualifies:

| stage | planned scale | estimate |
|---|---:|---:|
| P0 qualification | 300 balanced episodes + replay/corruptions | 20--60 min wall, <= 24 CPU workers |
| corpus | about 4,000 successful train, 480 dev, >= 800 test episodes, expanded until floors | 1--3 h wall, 30--70 CPU h |
| learned arms | `S`, `C-h0`, `C-h60`, 3 seeds if kernels are nondeterministic | 2--5 GPU h, <= 12 GB VRAM |
| closed-loop arms | all arms across S/T/ST and two deterministic replays | 3--7 h wall with bounded parallelism |
| verification/report | full trace recomputation + tamper test | 30--90 min wall |

Expected full-run wall is 7--12 hours if CPU rollouts parallelize cleanly,
with roughly 2--6 GB compressed traces. These are estimates, not evidence.
The run stops immediately on a Gate-0 failure, receipt invariant violation,
oracle leak, applied-label mismatch, held-out access before checkpoint freeze,
post-gate unsafe command, or resource cap breach.

## 17. Smallest informative follow-up that can run today

Run **MA-2-P0 only; do not train a neural model yet**:

1. implement the oracle-isolated observation adapter, exact target evaluator,
   four-stage action ledger, product-executive receipt adapter, and canonical
   trace writer/verifier;
2. freeze 10 new geometry seeds, five target roles with same-class distractors,
   and three task families (`plain`, `interrupt_now`, `queue/resume`), two
   repeats each: 300 balanced teacher episodes;
3. replay 30 episodes twice for normalized-digest determinism and run at least
   one instance of every DMC-2 corruption class through the composed seam;
4. report teacher exact SR by target/task, applied-label equality, oracle taint,
   exact transaction sequences, trace completeness, and Wilson intervals; and
5. stop. Proceed to corpus generation only if every Gate-0 condition passes.

This is the smallest useful next experiment because the already observed MA-1
teacher ceiling makes another transformer training run unlikely to teach us
anything. P0 tells us whether we have a valid demonstrator and causal data path;
if it fails, the immediate work is teacher/receipt/evaluator repair, not model
scaling.

## 18. Assumptions and claim limits

- A research-local exact executive-to-receipt adapter may be built for MA-2;
  the current production architecture still lacks that proven composition.
- The scene generator can be extended to produce duplicate same-class target
  instances and a balanced semantic inventory without touching frozen product
  eval scenes.
- Localization, semantic mapping, and LiDAR features used by Model A can be
  generated through observation adapters; simulator truth remains scorer-only.
- Steering timing/text is scripted. This is cue-duplex, not audio-duplex, and
  says nothing about ASR, echo cancellation, speech latency, or human dialogue
  preference.
- The venue is kinematic and pedestrian-free unless a later named MA-2-social
  extension adds dynamic-agent families. It does not establish Go2 gait,
  contact, stair, elevator, crosswalk, acoustic, thermal, or physical safety.
- A supported result justifies shadow/replay work. It does not make the robot
  mount-ready or motion-ready.
