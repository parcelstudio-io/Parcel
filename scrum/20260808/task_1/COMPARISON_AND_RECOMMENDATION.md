# Comparison and recommendation — three implementable companion designs

**Decision proposal:** choose **Design B, the dual-system semantic companion,**
as the product architecture; require **Design A** to remain its deterministic
operational baseline and degraded-mode implementation; develop **Design C** only
as a shadow challenger until a measured residual justifies its added assurance
and data burden.

That choice does not mean implementing three navigation stacks. All three use
the ABI, state estimate, geometry, executive, final safety monitor,
`ControlManager`, and Unitree Sport boundary in
[the shared foundation](SHARED_FOUNDATION.md). The decision is primarily about
which component may propose semantic goals and how one admissible local motion
candidate is selected.

## 1. What is actually being decided

The robot needs two very different kinds of competence:

1. **invariant competence** — stop on bad evidence, avoid obstacles, respect
   road boundaries, maintain a formation, settle at a goal, and give one
   component motion authority; and
2. **open-world competence** — understand paraphrases, infer useful but bounded
   defaults, identify a requested kind of place, choose an appropriate social
   response, and recover conversationally when the scene is ambiguous.

Invariant competence belongs in typed, inspectable algorithms. Open-world
competence benefits from learned language and vision systems. The designs differ
in where the boundary sits:

```text
                         learned decision surface
             less ◀──────────────────────────────────▶ more

Design A     language aliases only
             │ semantic goal and trajectory are classical

Design B     task/goal/reaction proposal
             │ metric path, local command and safety are classical

Design C     task/goal plus bounded trajectory-candidate comparison
             │ hard admissibility, final command shaping and safety are classical
```

No option gives a model direct velocity or Sport authority. Design C increases
learned *selection*, not learned actuation.

## 2. Shared end-to-end control path

Every accepted owner command must traverse the following stateful path:

```text
final transcript / UI request
        │
        v
authorization + TaskRequestV1 interpretation
        │
        v
trusted TaskRevisionV1 compiler ───── task/revision transaction
        │
        v
semantic grounding ───────────────── fresh scene evidence
        │
        v
NavGoalV1 / behavior goal
        │
        v
global route + local motion decision
        │
        v
kinematic limits + forward-preferred shaping
        │
        v
post-shaper camera/LiDAR/state safety admission
        │
        v
ControlManager single-writer lease + watchdog
        │
        v
Unitree Sport velocity API ────────── gait/balance remains vendor-owned
        │
        v
feedback + independent terminal witness + conversational result
```

The design-specific component may replace only the interpretation, proposal,
grounding, global planning, or local candidate-selection boxes. It cannot skip
the task transaction, hard constraints, final monitor, or feedback witness.

## 3. Condensed architecture alternatives

### 3.1 Design A — deterministic companion

Design A implements the complete product path with:

- an admitted intent grammar and alias table;
- a typed relation/quantity registry;
- classical semantic-region scoring;
- search/frontier behavior for unseen targets;
- global A*/Smac-like planning;
- regulated-pure-pursuit-style forward tracking;
- a formation controller that emits rolling goal regions;
- deterministic behavior arbitration and terminal witnesses.

Its important property is **completeness without a learned reasoning service**.
It understands every explicitly registered command family and refuses or
clarifies everything outside that language. Open-vocabulary perception may be
learned, but the label is treated as uncertain evidence; it does not decide
free space or command motion.

### 3.2 Design B — dual-system semantic companion

Design B retains the entire Design A execution path and adds two asynchronous,
proposal-only reasoners:

- a fast intent/slot path for common instructions and corrections; and
- a slower conversational/task reasoner for long-tail language, scene queries,
  clarification, decompositions, and social reactions.

Both emit the same constrained contracts as deterministic code. A trusted
compiler, goal arbiter, and evidence service validate the proposals. Common
commands never wait for a large model. A slow result is accepted only if its
task revision, evidence, deadline, authorization, and current executive state
still match. Otherwise it is logged and discarded.

This is the recommended product choice because it makes the dog conversational
without moving open-ended inference into the hard real-time control loop.

### 3.3 Design C — predictive candidate companion

Design C extends B with several bounded motion candidate generators, for
example:

- regulated pure pursuit;
- model-predictive path integral control;
- social-force or velocity-obstacle candidates;
- a learned open-weight local-navigation proposer; and
- recovery/search candidates.

Hard code first rejects candidates that violate geometry, uncertainty, task,
road, kinematic, freshness, or authorization constraints. An analytic scorer
initially chooses among the survivors. Only after a frozen candidate sampler
and evaluation corpus expose a stable selection residual may a learned ranker
replace or blend with that analytic ordering. It chooses one whole,
already-admissible candidate; it never adds a residual velocity.

This design has the highest potential in crowded or socially ambiguous scenes,
but it also has the largest state-distribution, data, latency, and assurance
burden.

## 4. Detailed comparison matrix

The cells describe architectural tendency, not measured Parcel results. The
team should not convert them into benchmark claims until the proposed paired
experiments exist.

| Dimension | A — deterministic | B — dual-system | C — predictive candidate |
| --- | --- | --- | --- |
| Hard-stop authority | Independent post-shaper monitor | Same | Same |
| Body command authority | One classical controller | One classical controller | Selected bounded candidate, then one classical command path |
| Common command latency | Best and predictable | Same as A through fast path | Same as B if candidate deadline is bounded |
| Long-tail language | Limited to grammar/aliases | Strongest practical fit | Same language path as B |
| Unseen semantic goal | Hand-coded query/search policy | VLM/LLM may propose and explain candidates | Same, plus richer motion candidates |
| Dynamic crowd behavior | Classical prediction/TTC and social costs | Same default | Highest potential if candidate diversity is useful |
| Explainability | Highest | High at execution boundary; model rationale is not evidence | Moderate; selection attribution requires richer traces |
| Determinism/replay | Highest | Deterministic execution; proposal variance must be frozen/logged | Candidate and ranker versioning makes replay hardest |
| Offline/no-GPU behavior | Full intended behavior over admitted commands | A remains functional; long-tail semantics degrade/clarify | B fallback; predictive challengers unavailable |
| Compute/thermal demand | Lowest | Moderate, model-dependent and asynchronous | Highest, especially with parallel rollouts or visual policies |
| Training requirement | None for core algorithms | Prefer open weights; task-specific fine-tuning optional | None at first; eventual ranker requires representative logged choices/outcomes |
| Integration surface | Smallest | Multiple rates, IPC, versioned proposals | Adds sampler consistency, candidate normalization, selection calibration |
| Fault containment | Straightforward | Strong if proposer is out of process and latest-only | Strong only if every generator shares the same hard filter and deadline |
| Safety argument scope | Narrowest | Models cannot affect hard constraints | Must also demonstrate candidate-set and selection containment |
| Likely early failure | Brittle paraphrases and hand-coded semantic gaps | Stale or ungrounded proposal; excessive clarification | Candidate oscillation, distribution shift, compute deadline misses |
| Product fit now | Mandatory baseline | **Recommended** | Shadow research lane |

## 5. Decision criteria

Architecture review should score evidence, not enthusiasm. The recommended
weights reflect a companion robot that will eventually operate near people:

| Criterion | Weight | What must be demonstrated |
| --- | ---: | --- |
| Authority and failure containment | 25% | No proposal, stale result, crash, or ambiguity bypasses HOLD, hard constraints, or one-writer ownership |
| Instruction/task success | 20% | Correct task, relation, quantity, referent, lifecycle, and terminal result on held-out paraphrases/scenes |
| Navigation in dynamic scenes | 15% | Collision-free progress, socially acceptable clearance, recovery, and goal completion under moving agents |
| End-to-end and tail latency | 10% | Query-end-to-acknowledgment/reasoning/speech and sensor-to-stop/control p50/p95/p99 |
| Diagnosability | 10% | A failed episode is attributable to speech, intent, grounding, state, planner, controller, safety, or witness |
| Evaluation validity | 10% | Unchanged product path, no oracle leakage, frozen seeds/manifests, independent truth scorer |
| Device feasibility | 5% | Measured CPU/GPU/VRAM, memory, thermal, power and deadline behavior on target hardware |
| Extensibility | 5% | Replaceable controllers/models through stable ABI without changing authority semantics |

The blank scoring sheet is in [TEAM_REVIEW.md](TEAM_REVIEW.md). A score without
an artifact link should be marked `UNKNOWN`, not guessed.

## 6. Algorithm-by-algorithm comparison

### 6.1 Utterance interpretation

**A** uses deterministic normalization and an admitted grammar:

```text
normalize transcript
  → classify speech act (request/correction/cancel/question/statement)
  → match intent aliases and relation grammar
  → normalize typed quantity without inventing units
  → bind obvious discourse reference if unique and fresh
  → TaskRequestV1 or Clarify(reason, candidate set)
```

**B/C** race, but do not vote across, two paths:

```text
common-path parser ── valid high-specificity result ──> compile now
        │ no admitted match / real ambiguity
        v
bounded model request ── TaskSketch proposal ──> schema/policy/evidence validator
                                              ├─ accept as TaskRequestV1
                                              └─ clarify / reject / HOLD
```

The deterministic parser wins an exact, authorized, current match. A model
cannot silently reinterpret an already executing physical command; corrections
create a new plan revision. Conversation can stream while the physical branch
waits for grounding, but speech must not claim that motion completed.

### 6.2 Semantic grounding

All designs calculate a goal **region**, never blindly trust one model point:

```text
query(target_kind, descriptors, relation)
  → collect fresh semantic candidates
  → join each candidate to metric support and pose/transform epoch
  → reject stale, unreachable, road-disallowed, or insufficiently observed ones
  → sample candidate poses inside/near/next-to the supported region
  → rank by relation fit + path cost + clearance + view + social cost + uncertainty
  → NavGoalV1 with evidence lineage, expiry, and terminal relation
```

In A, the query comes from the registry and the rank weights are explicit. In B,
a model may propose a target class, descriptors, relation, or search order. In
C, a model may additionally propose viewpoints or route hypotheses. In every
case, calibrated metric geometry owns reachability and free space.

### 6.3 Global route

All designs should begin with one reproducible planner baseline:

1. fuse LiDAR/depth obstacle layers with semantic keepouts and uncertainty;
2. inflate lethal geometry by the configured footprint/clearance convention;
3. apply a high or lethal road cost unless a valid crossing authorization
   covers this task/revision and route segment;
4. plan to the best goal-region sample, not just its centroid;
5. smooth only inside checked free space and retain curvature/clearance bounds;
6. revalidate the path after every map/transform epoch change.

A and B use one classical route. C may generate multiple routes with different
homotopy, social, or visibility trade-offs, but all use the same hard map.

### 6.4 Local motion

The default controller in A/B should be an in-process regulated-pure-pursuit-
style tracker:

```text
lookahead = clamp(k0 + kv*speed, min_lookahead, max_lookahead)
target = first path point at lookahead arc distance
heading_error = wrap(bearing(target) - base_yaw)

if abs(heading_error) > turn_in_place_threshold:
    vx = 0
    vy = 0
    wz = bounded_heading_controller(heading_error)
else:
    curvature = geometric_curvature(target)
    vx = min(profile_speed,
             curvature_speed_limit,
             obstacle_approach_limit,
             stopping_distance_limit,
             dynamic_agent_limit)
    vy = bounded_lateral_correction(cross_track_error)
    wz = clamp(vx * curvature + heading_feedback)

penalize abs(vy) during normal destination travel
allow vy for short avoidance, formation correction, docking, or manual intent
```

The critical behavioral change is explicit heading acquisition before forward
translation when error is large. The dog may move laterally, but ordinary point
travel no longer looks like sliding sideways.

C generates several time-indexed candidates under the same velocity,
acceleration, jerk, curvature, lateral, and horizon limits. The hard filter
rejects any collision, unobserved-space, road, authorization, or state-invalid
candidate. The scorer then trades progress, clearance, social comfort,
alignment, visibility, smoothness, and switching hysteresis.

### 6.5 Owner following

No design should command twist directly from a person bounding box. Following
is persistent formation planning:

```text
owner track + velocity + heading + covariance
  → predict owner over a short bounded horizon
  → choose formation point behind owner at desired distance
  → project into observed, reachable, non-road free space
  → emit expiring rolling GoalRegion
  → common global/local planner
  → maintain formation hysteresis; do not chase jitter
```

Owner ambiguity, stale identity, loss of required coverage, or an unsafe
intervening route yields HOLD/search rather than following the nearest person.
A uses deterministic prediction. B may use a VLM for re-identification or
semantic search, but the metric track remains required. C may compare formation
routes, but cannot relax identity or person-stop constraints.

### 6.6 Reactions and interruptions

All designs route a reaction through a behavior broker. A maps admitted dialogue
acts to a small reaction library. B/C may let a model propose a
`ReactionProposalV1` with affect, gesture, utterance, urgency, expiry, and
interrupt preference.

```text
proposal
  → authorization + schema + expiry
  → behavior policy checks current task/resources/battery/safety
  → choose one:
       EXECUTE_NOW          only if safe and explicitly interruptible
       QUEUE_AT_CHECKPOINT  preserve important navigation
       SPEECH_ONLY          body is busy but conversation can respond
       SUPPRESS             stale/inappropriate/conflicting
  → trusted animation/pose primitive
  → feedback and optional dialogue acknowledgment
```

“I am sad” can schedule a bow and empathetic response. It does not cancel a road
exit, emergency return, active balance event, or higher-priority safety task.
Low battery is a system event: seek/hold a safe stopping region first, settle,
then sit or show a low-battery gesture. The gesture is not the safety policy.

## 7. Three scenario walkthroughs

### 7.1 “Can you go to the sidewalk? The road is dangerous.”

Shared execution:

1. interpret `SAFETY_CORRECTION + NavigateTo(sidewalk, inside)`;
2. cancel or checkpoint lower-priority base work in one revision transaction;
3. query fresh sidewalk regions joined to metric traversability;
4. prefer reachable samples that reduce road exposure and do not require a new
   unauthorized road crossing;
5. turn toward the route, move forward with local obstacle/TTC regulation;
6. stop exactly, settle, and verify that the footprint is within the sidewalk
   region with required clearance and the robot is no longer on the road;
7. report success only after the independent witness passes.

Design differences:

| A | B | C |
| --- | --- | --- |
| Registered phrase maps directly to the skill; deterministic region ranker. | Fast path should handle it exactly like A; VLM is queried only if sidewalk candidates are absent/ambiguous. | May compare several admissible ways to exit a crowded road; the hard road/geometry policy remains unchanged. |

### 7.2 “Walk behind me.”

Shared execution:

1. compile persistent `FollowFormation(relation=behind)` rather than terminating
   `ApproachOwner`;
2. require a fresh enrolled-owner track and unambiguous association;
3. calculate and continuously refresh a reachable region behind the predicted
   owner pose;
4. route through the same planner, controller, person/TTC gate, and watchdog;
5. hold on ambiguity/occlusion and run bounded owner reacquisition;
6. continue until cancel, replacement, deadline/policy, or system HOLD.

Design differences:

| A | B | C |
| --- | --- | --- |
| Constant-velocity prediction and explicit hysteresis. | Model can understand paraphrases and help re-identification/search, never select identity by text alone. | Multiple socially distinct formation paths may be ranked when crowds block the direct region. |

### 7.3 The owner jokes while the dog is navigating

Shared execution:

1. conversation detects a social statement, not a navigation correction;
2. propose chuckle/audio and possibly a small body reaction;
3. behavior broker sees that base motion is currently leased;
4. speak/chuckle immediately if audio policy permits;
5. queue the physical gesture for a safe checkpoint or suppress it if stale;
6. continue navigation without changing its task revision.

A has a narrow deterministic dialogue-act map. B supplies the best natural
conversation while the broker preserves control. C adds no meaningful advantage
for this case and should use B's behavior path.

## 8. Recommended composition

### 8.1 Product architecture: B

Choose B because it separates the two dominant latency and assurance domains:

- **fast deterministic plane:** control, safety, common intents, corrections,
  task state, metric grounding, route following, follow formation, witnesses;
- **slow semantic plane:** open-ended conversation, long-tail intent sketches,
  semantic queries, clarifications, plan decomposition, reaction proposals.

This makes the dog responsive to frequent commands even when the reasoner is
cold, busy, unavailable, or wrong. It also lets the conversation brain evolve
without changing the body-authority proof boundary.

### 8.2 Mandatory operational baseline: A

A is not throwaway scaffolding. It is:

- the no-model/offline operating mode;
- the benchmark attribution baseline;
- the fallback when proposal services miss deadlines;
- the implementation of common high-value intents;
- the oracle for whether a learned component adds value;
- the simplest physical commissioning path.

If B cannot execute all A-supported tasks with identical safety and no material
tail-latency regression, B has not earned promotion.

### 8.3 Shadow research lane: C

C should start only with candidate logging and analytic scoring. A learned
ranker is justified when all of the following are true:

1. A/B safety, state, lifecycle, and product-path evaluations are green;
2. at least two admissible candidates regularly exist in the failure domain;
3. an oracle replay shows that choosing a different existing candidate would
   have fixed a meaningful fraction of failures;
4. the residual is candidate *selection*, not perception, localization,
   grounding, missing recovery, or controller tuning;
5. representative training/evaluation data can be separated by scene and
   route, with leakage checks;
6. inference fits a hard deadline and missing output falls back to the analytic
   selector;
7. paired results improve task success without hard-safety, comfort, latency,
   energy, or hardware regressions.

Until those gates pass, training a ranker or navigation RL policy is premature.

## 9. Phased implementation plan

The phases are evidence dependencies, not calendar promises.

### Phase 0 — freeze authority and ABI

Implement and test before model or planner expansion:

- fix the dimensionally invalid person-stop computation;
- add final post-shaper exact-zero reassertion and shaper reset;
- make stale/missing LiDAR, pose, transform, state, or feedback HOLD;
- define one footprint/clearance convention;
- make task/revision/lease pause, cancel, resume, and replace atomic;
- split `ApproachOwner` from `FollowFormation`;
- freeze the interfaces in `SHARED_FOUNDATION.md`;
- label simulator truth and prevent it from satisfying physical admission.

**Exit:** fault-injection tests prove command zeroing and authority revocation;
strict lifecycle tests pass; schema compatibility tests are pinned.

### Phase 1 — complete Design A product path

- commissioned state/localization interface behind sim and future hardware
  producers;
- semantic region registry and evidence join;
- goal-region sampler and relation witnesses;
- RPP-style forward-preferred controller and bounded recovery;
- formation-goal generator for owner follow;
- deterministic common command compiler;
- product headless tests for sidewalk, lamppost, orbit, away, follow, cancel,
  correction, ambiguity, absent target, moving people, and sensor faults.

**Exit:** common tasks succeed through the unchanged voice/text-to-Sport adapter
path in frozen headless scenarios, with independently scored terminal states.

### Phase 2 — activate Design B semantic plane

- separate dialogue stream from physical task proposals;
- run model/VLM services out of process with latest-only queues;
- validate versioned proposal schemas and reject raw motor/coordinate authority;
- implement deadline, evidence, task/revision, generation, and authorization
  checks;
- support clarify/acknowledge/execute/result dialogue states;
- evaluate long-tail paraphrases and scene ambiguity against A.

**Exit:** B materially improves held-out instruction and conversation quality;
all A tasks and safety properties remain non-inferior; model loss/OOM/timeout
falls back to A or HOLD as specified.

### Phase 3 — planner challenger

- keep current/in-process controller as sole writer;
- compare an isolated Nav2 Smac + RPP sidecar using identical observations and
  action adapter;
- then compare Smac/state-lattice + MPPI if failures indicate local optimization
  rather than grounding/state issues;
- promote only one controller through a controlled switch, never concurrent
  body writers.

**Exit:** paired product and external proxy results improve without regressions
in hard events, lateral travel, jerk, p99 cycle time, or recovery stability.

### Phase 4 — Design C shadow candidates

- normalize all generator outputs to `TrajectoryCandidateV1`;
- hard-filter against one snapshot and one constraint version;
- calculate analytic costs and counterfactual oracle selection;
- log candidate diversity, invalid reasons, regret, deadline, and outcomes;
- only then consider supervised preference/ranking or offline RL over the
  discrete candidate set.

**Exit:** candidate-selection residual and promotion benefit are demonstrated;
otherwise retain B and remove unused complexity.

### Phase 5 — HIL and supervised physical ladder

- axis/frame/mode commissioning;
- watchdog and network impairment;
- restrained or bounded HIL;
- fenced static course;
- staffed indoor dynamic course;
- fenced outdoor course with conservative operational domain;
- only later, specifically authorized public-space trials.

Simulator results never skip these gates.

## 10. Parallel work after the Phase-0 ABI freeze

Four lanes can run concurrently without creating conflicting authority:

| Lane | Owns | Depends on | Produces |
| --- | --- | --- | --- |
| Safety/control | final gate, shaping order, watchdog, Sport adapter, commissioning | frozen command/state/safety ABI | exact-zero and stop-distance evidence |
| State/perception | pose/transform health, geometry, semantics, owner/dynamic tracks | frozen evidence/state ABI | sensor-faithful snapshots and faults |
| Instruction/executive | request compiler, lifecycle, relations, behavior broker, proposer gateway | frozen task/goal/proposal ABI | common tasks and long-tail proposal path |
| Evaluation/navigation | world fixtures, truth scorer, goal sampler, controller challengers, ledgers | frozen trace/result ABI | paired product/external evidence |

Integration occurs at explicit artifacts, not shared implementation details:

```text
ABI conformance
  → synthetic component tests
  → recorded snapshot replay
  → product headless episode
  → fault suite
  → external proxy
  → HIL
```

No lane should change a shared field or authority semantic without an ADR and
schema migration.

## 11. Promotion scorecard

Every experiment compares a candidate against the current frozen product
baseline and records at least:

- task success and relation-specific success;
- collision/contact and minimum person/obstacle clearance;
- forbidden-region/road entries and authorization violations;
- SPL/path efficiency, completion time, distance, replans and recoveries;
- angular/lateral travel, jerk, oscillation and stop settling;
- owner identity swaps, formation error and reacquisition outcome;
- semantic grounding accuracy and clarification correctness;
- proposal validity, rejection reasons, deadline misses and fallback usage;
- query-end-to-first-log/reasoning/audio and query-end-to-task-admission;
- sensor-to-brake decision, safety-to-manager, manager-to-feedback-zero;
- control cycle, planner, perception, IPC, model and witness p50/p95/p99;
- CPU/GPU/VRAM, memory, temperature, power and crashes;
- exact source/config/model/scenario/evaluator hashes and evidence class.

Hard regressions are not averaged away by task success. A run with an
authorization violation, oracle leak, silent telemetry loss, or invalid
evidence classification is invalid or failed according to the frozen protocol.

## 12. Main risks and explicit falsifiers

### A is the wrong long-term product choice if

- held-out natural instructions remain dominated by parser/ontology failures;
- adding aliases creates unmaintainable collisions and brittle discourse state;
- semantic search needs open-world reasoning that cannot be expressed through
  registry composition.

It remains the required operational baseline even if these occur.

### B is the wrong product choice if

- long-tail proposals do not materially improve end-to-end task success over A;
- asynchronous semantics cause unacceptable correction or tail-latency errors;
- the target device cannot sustain conversation/perception within thermal and
  power limits and no viable split deployment exists;
- proposal containment cannot be made observable and deterministic enough for
  physical promotion.

### C is unjustified if

- most failures are caused before trajectory selection;
- the candidate set rarely contains a successful alternative;
- analytic selection matches an oracle ranker closely;
- compute/deadlines reduce rather than improve dynamic-scene success;
- gains disappear on held-out towns, pedestrian processes, or sensor faults;
- a simpler MPPI/RPP tuning or recovery fix captures the same gain.

## 13. Team recommendation to record

Approve the following as one coherent decision:

1. **B is the target product architecture.**
2. **A is implemented first and remains a supported deterministic mode.**
3. **C is a shadow-only challenger until the six residual gates in section 8.3
   are met.**
4. **The shared ABI and authority rules freeze before lanes parallelize.**
5. **Models propose; trusted code grounds, admits, executes, stops, and verifies.**
6. **The next implementation milestone is Phase 0 plus the Design A closed
   product path, not model training.**

This recommendation maximizes useful semantic capability while keeping one
understandable navigation and safety substrate for the robot that will actually
walk beside its owner.
