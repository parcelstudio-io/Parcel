# Team architecture review packet

**Meeting outcome required:** select the product design, freeze the first ABI,
approve implementation order, and define evidence gates. Do not use this review
to select a model checkpoint or tune controller constants.

## 1. Pre-read

Read in this order:

1. [Shared foundation](SHARED_FOUNDATION.md) — authority, contracts, safety
   math, common navigation and terminal witnesses.
2. [Design A](designs/DESIGN_A_DETERMINISTIC_COMPANION.md) — complete
   deterministic baseline.
3. [Design B](designs/DESIGN_B_DUAL_SYSTEM_COMPANION.md) — asynchronous
   conversation/reasoning proposals over the deterministic spine.
4. [Design C](designs/DESIGN_C_PREDICTIVE_COMPANION.md) — bounded candidate
   generators and optional learned selection.
5. [Comparison and recommendation](COMPARISON_AND_RECOMMENDATION.md).

Evidence behind the designs is indexed in the prior
[research task](../../20260807/task_2/README.md). Reviewers should distinguish a
published system result, a Parcel proxy run, a derived rescore, a component
test, and an architecture hypothesis.

## 2. Proposed 75-minute agenda

| Minutes | Topic | Required output |
| ---: | --- | --- |
| 0–5 | Reconfirm product goal and operational boundary | One-sentence scope |
| 5–15 | Safety/authority invariants | Accept or record a blocking objection |
| 15–30 | Design A/B/C advocates | One strongest case and one falsifier each |
| 30–42 | Scenario walkthroughs | Identify algorithm/interface gaps |
| 42–52 | Evidence-based scoring | Completed worksheet with `UNKNOWN`s |
| 52–62 | Product/fallback/shadow decision | One selected composition |
| 62–70 | ABI and parallel lanes | Named owners and dependency order |
| 70–75 | ADRs and unresolved risks | Decision record plus follow-ups |

## 3. Scope statement to approve

> Parcel is a voice-enabled Unitree companion whose software interprets owner
> requests, grounds them in camera/LiDAR-derived state, plans and executes
> bounded navigation and behavior through Unitree Sport, reacts naturally
> without inappropriately interrupting higher-priority work, and independently
> verifies outcomes. Current work is prototype architecture and evaluation; it
> does not authorize unsupervised operation in public streets.

Edits to that statement should be made before comparing designs; otherwise the
team may optimize for different products.

## 4. Non-negotiable invariant vote

Mark each `ACCEPT`, `BLOCK`, or `NEEDS ADR`. A `BLOCK` prevents architecture
selection until its exact concern and alternative are written down.

| ID | Invariant | Vote | Concern / evidence |
| --- | --- | --- | --- |
| I-01 | Unitree Sport owns gait, balance, joint control |  |  |
| I-02 | Exactly one base-motion writer/lease at a time |  |  |
| I-03 | Final post-shaper metric monitor can only reduce or stop |  |  |
| I-04 | Missing/stale required sensor, pose, transform or feedback means exact-zero HOLD |  |  |
| I-05 | Model outputs are proposals; no model emits Sport commands or certifies safety/success |  |  |
| I-06 | Every physical action has task/revision/evidence/deadline/resource lineage |  |  |
| I-07 | Pause/cancel/resume/replace is one authority transaction |  |  |
| I-08 | Road crossing requires authenticated task-bound authorization, not transcript alone |  |  |
| I-09 | Lateral motion is permitted but penalized for ordinary destination travel |  |  |
| I-10 | Simulator success is not physical clearance |  |  |

## 5. Evidence scoring worksheet

Use a 0–5 score only when an artifact supports it:

- `0`: contradicted by current evidence;
- `1`: concept only;
- `2`: component/synthetic evidence;
- `3`: unchanged product-headless evidence;
- `4`: external/public-development evidence plus fault coverage;
- `5`: applicable HIL/physical evidence under a defined operating domain;
- `UNKNOWN`: not yet measured.

Scores are multiplied by weight only after the evidence link is recorded.

| Criterion | Weight | A score/evidence | B score/evidence | C score/evidence |
| --- | ---: | --- | --- | --- |
| Authority/failure containment | 25 |  |  |  |
| Instruction/task success | 20 |  |  |  |
| Dynamic navigation | 15 |  |  |  |
| E2E/control tail latency | 10 |  |  |  |
| Diagnosability/replay | 10 |  |  |  |
| Evaluation validity | 10 |  |  |  |
| Target-device feasibility | 5 |  |  |  |
| Extensibility | 5 |  |  |  |
| **Weighted total** | **100** |  |  |  |

The architecture recommendation can precede complete scores because it is also
a staged experiment plan. Unknown evidence must become a phase gate, not an
optimistic score.

## 6. Advocate briefs

Assign one person to make the best case for each design and another to state
what would falsify it.

### A — deterministic companion

Strongest case:

- smallest authority surface and most reproducible baseline;
- fully useful for common commands without a GPU/model service;
- quickest route to trustworthy lifecycle, localization, controller, and
  witness evidence;
- isolates whether failures are semantic or navigational.

Required concession:

- an explicit grammar/ontology will not deliver the desired long-tail
  conversational companion by itself.

Question for advocate:

> Which command families must be first-class and how does the system respond
> when a natural request falls just outside them?

### B — dual-system semantic companion

Strongest case:

- preserves A's fast deterministic path while adding long-tail language,
  semantic search, clarification, and natural reactions;
- proposal deadlines and out-of-process isolation keep model inference outside
  hard real-time control;
- the conversation model can evolve independently of navigation authority.

Required concession:

- versioning, late results, amendments, evidence joins, model availability, and
  dialogue/task consistency create substantial orchestration work.

Question for advocate:

> What exact result is produced when the slow reasoner times out during a new
> command, a correction, and a currently valid classical task?

Expected answer: the new unresolved physical request clarifies/HOLDs; a stale
correction never revives old work; an already authorized and independently
grounded classical task may continue only under its existing live revision and
evidence—not because the model timed out.

### C — predictive candidate companion

Strongest case:

- candidate diversity could capture different crowd, visibility, recovery,
  and social trade-offs that one controller cannot;
- a discrete selector is easier to contain and evaluate than an end-to-end
  residual-velocity policy;
- counterfactual candidate logs create a disciplined path toward learning.

Required concession:

- if no successful alternative is already in the candidate set, ranking cannot
  fix the episode; parallel inference also consumes the most compute and creates
  new switching/deadline failure modes.

Question for advocate:

> Which frozen replay proves a candidate-selection residual rather than a
> grounding, state-estimation, candidate-generation, or witness defect?

## 7. Scenario red-team prompts

For each scenario, reviewers should identify the request, authorization,
evidence join, task revision, goal region, local algorithm, veto, terminal
witness, spoken response, and logged failure reason.

### Navigation and grounding

1. “Get off the road and go to the sidewalk,” with two sidewalks, one across
   traffic and one on the current side.
2. “Wait by the lamppost,” with three lampposts, one behind a parked car and one
   in an unobserved region.
3. “Go to the Nike store,” where the sign is visible but the entrance is not.
4. “Walk five steps away from me,” with a wall 0.7 m behind the dog.
5. “Walk in one small circle around me,” while a pedestrian crosses the orbit.
6. “Come here,” with an owner track that becomes ambiguous halfway through.

### Lifecycle and conversation

7. “Follow me” → “stop” while the large reasoner still has an older result in
   flight.
8. Manual joystick takes over during `FollowFormation`, then releases.
9. The owner tells a joke during a safety-correction task.
10. The owner says they are sad while the dog is crossing a doorway.
11. A new urgent task arrives while the dog is executing a non-interruptible
    settling/pose transition.
12. ASR revises its final transcript after a task has already been admitted.

### State, dynamics, and faults

13. LiDAR coverage drops only on the commanded side while camera semantics look
    normal.
14. Pose covariance jumps after a loop closure while following a path.
15. The local planner, model proposer, or TTS process crashes independently.
16. A pedestrian stops suddenly inside the predicted corridor.
17. The planner oscillates between two homotopies around a moving group.
18. The robot reaches the goal while a proximity brake is still active.

Minimum acceptable properties across all designs:

- late data cannot acquire authority;
- missing required data cannot degrade into open-loop translation;
- a soft social objective cannot weaken hard metric stopping;
- task success cannot be reported while a brake is active or feedback is not
  settled;
- a conversational response cannot claim an unverified physical outcome;
- the trace reveals the first boundary that rejected or failed.

## 8. Interface-freeze checklist

Approve semantic ownership as well as field names.

| Interface | Producer | Consumers | Freeze question |
| --- | --- | --- | --- |
| `TaskRequestV1` | deterministic/model gateway | compiler | Does it represent correction, quantity, ambiguity, authorization and expiry without raw motor fields? |
| `TaskRevisionV1` | trusted compiler/executive | skills, broker, nav | Are resources, deadlines, invariants, attempts, witnesses and persistence system-owned? |
| `PoseEstimateV1` | state estimator | grounding, planner, controller, safety | Are covariance, health, frame epoch and freshness mandatory? |
| `PerceptionSnapshotV1` | evidence joiner | grounder/planner/safety | Can semantics be separated from metric free-space authority? |
| `NavGoalV1` | goal arbiter | planner/controller | Is goal-region, relation, road constraint, evidence and expiry sufficient? |
| `NavProposalV1` | B/C proposers | validator/arbiter | Can every proposal be rejected without affecting current authority? |
| `TrajectoryCandidateV1` | C generators | hard filter/selector | Are snapshot, limits, sample times and validity lineage explicit? |
| `SafetyDecisionV1` | final monitor | manager/trace | Does it record raw/shaped/final commands and every hard reason? |
| `NavFeedbackV1` | controller/manager | executive/witness | Is command zero, settled state, active brake and evidence lineage visible? |
| `NavResultV1` | terminal witness service | executive/dialogue/eval | Can success exist only with an independent witness bundle? |

Schema freezes should include serialization fixtures and backward/forward
compatibility expectations, not only Python dataclasses.

## 9. ADR set proposed for approval

### ADR-001 — product/fallback/research composition

**Proposal:** B is the target product; A is implemented first and remains the
deterministic mode; C stays shadow-only until a candidate-selection residual is
measured.

**Why now:** teams otherwise build model, navigation, and evaluation paths with
different assumptions about authority and fallback.

**Revisit when:** paired evidence falsifies B's semantic benefit or C's residual
gates pass.

### ADR-002 — one navigation authority path

**Proposal:** one selected global/local implementation at a time owns the base
lease. Nav2 or learned planners begin as isolated challengers and never write in
parallel with `grid_v1`.

**Why now:** “fallback” and “challenger” must not create two smoothers, two
writers, or inconsistent stop behavior.

### ADR-003 — model role

**Proposal:** models may emit constrained task/goal/trajectory/dialogue/reaction
proposals. Trusted code owns authorization, metric grounding, hard
admissibility, execution limits, stop, and terminal success.

**Why now:** checkpoint choice and prompt iteration must not move the authority
boundary accidentally.

### ADR-004 — state/evidence policy

**Proposal:** camera/LiDAR/commissioned state are the product evidence sources;
external maps are advisory. Required evidence is joined at one decision time and
stale/missing/frame-invalid input HOLDs.

**Why now:** all planning and evaluation results are invalid if simulator truth
or incompatible sensor epochs leak into the agent.

### ADR-005 — evaluation promotion

**Proposal:** every promotion uses frozen paired product-path episodes, isolated
truth scoring, fault tests, complete hashes, resource/latency telemetry, and a
declared evidence class. Physical promotion follows a separate HIL ladder.

**Why now:** published benchmark scores and direct-controller proxies are not
proof of an improved Parcel product path.

## 10. Parallel work allocation

Only start these lanes after ADR-001 through ADR-005 and the ABI fixtures are
accepted.

| Lane | First deliverable | Integration gate |
| --- | --- | --- |
| Safety/control | exact-zero post-shaper pin; valid stop-envelope units; manager fault traces | final command and settled-feedback contract tests |
| State/perception | sensor-faithful pose/transform/geometry snapshot with health and replay fixtures | evidence-join and simulated-oracle rejection tests |
| Instruction/executive | request/revision compiler, lifecycle transaction, common relation skills | typed trace through product text/voice entry point |
| Evaluation/navigation | goal-region scorer, RPP baseline, truth-only scenario evaluator and result ledger | deterministic headless sidewalk/lamppost/follow/orbit suite |

The next integration checkpoint should demonstrate one vertical slice:

```text
text "go to the sidewalk"
  → authorized TaskRequest
  → atomic TaskRevision
  → camera/LiDAR-supported sidewalk GoalRegion
  → forward-preferred route execution
  → post-shaper monitor + Unitree adapter simulation
  → exact-zero settled stop
  → independent inside-sidewalk/not-road witness
  → truthful response + latency trace
```

## 11. Decision record

Copy this block into the meeting notes:

```text
Date:
Participants:

Product architecture: A | B | C | DEFER
Operational fallback/baseline:
Shadow/research design:

Accepted invariants:
Blocked invariants and exact objections:
Accepted ABI revision/hash:

Phase-0 exit artifacts:
Phase-1 vertical slice:
Lane owners:

Evidence supporting decision:
Known unknowns:
Falsifiers/revisit triggers:
Explicitly deferred work:

ADR-001: ACCEPT | REVISE | REJECT
ADR-002: ACCEPT | REVISE | REJECT
ADR-003: ACCEPT | REVISE | REJECT
ADR-004: ACCEPT | REVISE | REJECT
ADR-005: ACCEPT | REVISE | REJECT
```

## 12. Default decision if no blocker is substantiated

Adopt B as the product architecture, A as the mandatory deterministic baseline,
and C as a shadow research lane. Begin with the shared Phase-0 corrections and
the Design A vertical slice. Do not begin navigation-policy training or give any
model active motion-selection authority until the evaluator demonstrates a
repeatable residual at that boundary.
