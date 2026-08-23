# ARCH-1 Fable review brief

## Assignment

Adversarially review this packet as an architecture and verification proposal.
Do not implement it. Do not repair, stage, commit, or amend the Wave 3 landing.
Read-only code inspection is allowed; product, test, tool, config, deployment,
prior-sprint, and Git-index writes are forbidden. Review the implementation
delta at exactly `0ce1c5f8bb4a..c1b84055bd57`; `be86b7861322` is the subsequent
index-only head at the addendum freeze.

An initial `FABLE_VERDICT.md` now exists and records
`ACCEPT_WITH_REQUIRED_CHANGES` for the original eight-file packet. Preserve its
authorship and text. Add a clearly dated `## Claude Wave 3 exact-delta
supplement` only after reviewing `CLAUDE_WAVE3_DECOMPOSITION.md`; do not repeat
the original broad review.

`CONCERNS_REGISTER.md` is required review input, not background reading. Record
coverage of every concern ID using compact family/range rows plus explicit
exceptions. Give detailed evidence for `BLOCKER`/`HIGH`; checked grouped rows
are sufficient for agreed `MEDIUM`/`WATCH/PRESERVE` findings. Do not silently
omit, delete, or mark a dirty-tree correction closed. Do not spawn one reviewer
or create one implementation card per ID.

## Required lenses

### Lens A — boundaries and dependency direction

- Does each extraction create one coherent state/clock/lifecycle owner?
- Are facades stable while dependencies point from contracts through pure
  domain logic to adapters and composition?
- Does the sequence remove cycles/coupling, or only move code into more files?
- Are process/native boundaries justified by timing, crash containment,
  credentials, vendor SDKs, GPU ownership, ROS integration, or throughput?
- Is the order realistic given Wave 3, physical gateway, and target evidence?

### Lens B — authority, safety, and physical truth

- Can any provider/model/audio/UI/storage/ROS path write motion or remain a
  liveness dependency of the stop chain?
- Is there exactly one sole vendor writer and one final software
  positive-command admission owner? Is the independently operated physical
  E-stop a separate, dominant, out-of-band failure domain?
- Are freshness, device/receipt clocks, sequence, epoch, frame, transform,
  calibration, covariance, origin, and witness independence owned explicitly?
- Do latched software STOP, axis-specific recoverable HOLD, independent
  physical/operator stop, restart-disarmed, TTL, preemption, terminal truth,
  unknown-space, and no-auto-resume invariants survive every stage?
- Does any desktop/mock/replay/SIL result overclaim physical readiness?

### Lens C — tests, evidence, and rollback

- What exact product-path caller exercises every proposed seam?
- Does every card have independent equivalence and refutation oracles?
- What mutant proves each hard gate can redden?
- Can evaluator failure still emit valid failure-complete output and later rows?
- Are target timings, sample sizes, maximums, hashes, origins, denominators, and
  `does_not_prove` appropriate?
- Can each card and physical deployment roll back independently and disarmed?
- Are source-shape tests replaced only after better observable contract tests
  and mutation evidence exist?

### Skeptic — value and execution cost

- Which proposed split has the highest risk and lowest prototype value?
- Which boundary is missing?
- Which item should be preserved rather than decomposed?
- Does card/process overhead itself reproduce the current complexity problem?
- What is the smallest sequence that materially improves physical prototype
  readiness and Claude review efficiency?
- Are spend, review fanout, context/index, CI compute, correction-cycle, and
  documentation budgets explicit enough to stop low-ROI work?
- Are follow-up cards admitted only for independently owned/blocking outcomes,
  with lesser notes batched, amended, deferred, refuted, or accepted as risk?

### Lens D — Claude Wave 3 landed delta

- Reproduce the grouped declaration coverage and dispositions in
  `CLAUDE_WAVE3_DECOMPOSITION.md`; do not infer completeness from line count.
- Decide whether the stopping gate's V1 path, hard-capability skip behavior,
  product/vendor-venv contradiction, resolved-profile simulator inheritance,
  socket deadline, and split mic serialization are confirmed defects.
- Protect cohesive leaves: motion refusals, commissioned sticky latch, replay
  cursor, resampler, pure codec/band math, and duplex lifecycle atomicity.
- Verify that test decomposition preserves every hard oracle/node ID and does
  not promote source-shape, fake transport, custom parser, or QEMU metadata to
  target/physical evidence.

## Questions Fable must answer explicitly

1. Should import/package integrity and test characterization precede runtime
   extraction? If not, name the safer order and evidence.
2. Are linked navigation/world snapshot authorities correctly before product
   credential/motion while allowing an earlier no-credential gateway bench?
3. Are D01–D25 complete enough that every major product/tooling system has an
   action or preserve disposition?
4. Is the threshold census useful without encouraging cosmetic splits?
5. Are `RobotRuntime`, `DirectiveNavigator`, and `RealtimeLane` decomposed along
   the correct state boundaries?
6. After native cutover, should `ControlManager` be kept, retired, or
   decomposed? Default to preserve unless production callers/traces show that
   internal extraction still removes live risk.
7. Do configuration, packaging, capture, CI, UI, and repository artifacts have
   appropriate priority relative to the physical prototype?
8. Does the unit/integration/replay/SIL/HIL/physical plan contain a green path
   that could pass while a new component is disconnected?
9. Are exact-zero, stale/origin/frame/epoch, unknown-space, false-arrival,
   cancellation, one-writer, and restart-disarmed refuters sufficient?
10. Are the proposed coverage, fuzz, repetition, p99, and physical progression
    thresholds defensible?
11. Can the sequence be executed with maximum WIP two and independently
    reversible cards?
12. What does acceptance still not prove?
13. Can the no-credential native final-governor/gateway host/CI bench start
    after only the minimum bridge protocol/authority freeze, then repeat the
    same artifact on Orin after B25/deploy while B16/B30 remain gated on
    OBS/deploy/independent-stop evidence?
14. Does Python own supervisory proposal/pre-gating while a native governor
    owns final local admission and the gateway independently enforces
    credential/epoch/TTL/watchdog rules, or is a safer explicit ownership split
    supported by evidence?
15. Can the real product launcher prove that the observation source, native
    governor client, sole writer, commissioned feedback wrapper, and stop path
    are connected, including disconnected-component mutants?
16. What are the accepted dispositions for legacy `ros_node.py`, ROS 2/QoS/tf2,
    Nav2 candidate authority, `ARCH-LOCALIZATION`, and `ARCH-DEPLOY`?
17. Are multi-rate navigation/world snapshots, per-source receipt/device clocks,
    clock mapping, exclusive readers, evidence lineage, and stationary feedback
    modeled without restamping or correlated-witness inflation?
18. What independent stop and gateway kill/hang evidence is mandatory before
    the first pulse and before autonomous movement?
19. Should commodity navigation/localization code be evaluated for replacement
    before Claude decomposes it, and which Parcel-specific semantic/social
    differentiators should remain custom?
20. Are the risk-tiered review plan, follow-up admission rule, two-correction
    limit, per-tranche spend/ROI stop gate, context-index policy, and CI compute
    SLA sufficient? Name required corrections rather than creating one card per
    concern.
21. Does `scripts/ci_gate.py` have to evaluate the six-term V2 envelope before
    any printed `FITS` result can support promotion, and must missing/broken
    terms or active-regime mismatch fail the applicable admission mode?
22. Can an absent required hard capability ever become a skipped row while the
    gate exits zero or prints `PASS`? State the accepted hard/soft/report-only
    truth table.
23. Is a read-only Unitree/Mid-360 sidecar required because the SDK-free product
    venv cannot construct `LiveGo2Sources`, and what bounded IPC/deadline owns
    that seam?
24. Does the fully resolved Go2 physical profile refuse inherited simulated
    battery, desktop NIC, placeholder extrinsics, and uncommissioned simulator
    thresholds rather than checking only the overlay text?
25. Are bounded dedicated LiDAR ingest and gateway-owned mic lifecycle state
    required before the current lock/deadline claims are accepted?
26. Which Wave 3 symbols and tests should be extracted, preserved, deferred, or
    target-proved, and how are those outcomes batched into existing ARCH cards
    without a follow-up card per symbol or finding?

## Review method

1. Verify snapshot/collision facts, the threshold census, and the exact Claude
   delta census read-only.
2. Trace at least one real product path for runtime control, navigation,
   realtime tool motion, camera ingress, browser/array audio, and Go2 evidence.
3. Attempt one counterexample against each non-negotiable authority invariant.
4. Inspect current tests for whether each proposed oracle is behavioral,
   source-shape, mock-only, replay, process, target, or physical.
5. Review the DAG for circular prerequisites, shared OWNS, unsafe parallelism,
   and legacy paths that could stay live.
6. State which rows were not independently reproduced.

A full gate is not required for this docs-only review. Do not rerun it merely
to produce a green number; distinguish the landing's recorded commit-tier
claim from evidence Fable independently reproduces.

## Required verdict format

```text
# ARCH-1 Fable verdict

Disposition: ACCEPT_DECOMPOSITION_SEQUENCE |
             ACCEPT_WITH_REQUIRED_CHANGES |
             REJECT

Reviewed tree: <commit plus dirty-overlay statement>
Review scope: <files/seams inspected>

## Blocking findings
- owner · violated invariant · exact boundary · falsifiable regression ·
  blocks refactor only or physical prototype

## Required sequence changes
...

## Accepted preserve boundaries
...

## Test/eval findings
...

## Evidence not reproduced
...

## Concern dispositions
<canonical family/range minus named exceptions>:
    CONFIRM_OPEN | PROVISIONALLY_CLOSED_IN_DIRTY_TREE |
    REFUTE_WITH_EVIDENCE | DEFER_ACCEPTED_RISK | DUPLICATE_OF <ID> | PRESERVE
Exceptions: <individual IDs, each removed from the range, and evidence>
Coverage: <all IDs accounted for; none silently omitted>

## Concern batching and spend controls
State the smallest accepted batches, rejected/deferred work, review tier,
owner/integrator, tranche budget, and stop/continue gate.

## Does not prove
...

## Authorization
State which dependency-safe foundation tranche, if any, is architecturally
eligible for owner consideration. Fable does not authorize spend/dispatch or
physical motion. `CONFIRM_OPEN`/provisional is not closure. The initial verdict
records X08/X16 refuted, X11 revised, and the X12 co-location decision; other
physical blockers and every required change still block their affected
milestones.
```

Every blocking finding must identify an owner, violated invariant, exact
boundary, falsifiable regression, and whether it blocks only the refactor or
the physical prototype. A non-empty `Does not prove` section is mandatory.
Every concern ID must be covered by exactly one family/exception row or merged
with `DUPLICATE_OF`; acceptance does not authorize one follow-up card per row.

For the narrow supplement, return one of the same three dispositions, answer
questions 21–26, state which initial-verdict findings remain unchanged, and
disposition only the new/changed exact-delta findings. Do not regenerate the
147-ID partition or repeat the reported nine-agent/556k-token review unless a
specific contradiction makes that necessary.
