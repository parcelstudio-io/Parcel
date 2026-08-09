# Independent research-workstream appendix

## Method and interpretation

The audit used the requested ten independent workstreams: eight for navigation,
perception, behavior, models, and evaluation, plus two separately framed RL
decisions. They were scheduled in waves because the execution environment had
four concurrent slots; independence refers to scoped analysis and conclusions,
not simultaneous wall-clock execution.

Each workstream inspected the repository slice relevant to its question and/or
checked primary sources. The lead synthesis then reconciled contracts,
evidence classes, licenses, and implementation ordering. “Confidence” below is
confidence in the recommendation from the available evidence, not confidence
that a component will work on Parcel before an experiment. External model
metrics remain author-reported unless a Parcel artifact is linked in
[CURRENT_STACK_AUDIT.md](CURRENT_STACK_AUDIT.md).

## N1 — current navigation and control audit

**Question:** What actually owns motion, and which defects invalidate physical
or model comparisons?

**Repository evidence:** `runtime.py`, command arbitration, proximity/TTC
gating, `navigation/velocity_shaping.py`, `ControlManager`, grid navigation,
pose configuration, and Unitree commissioning configuration. Targeted motion
and product-path tests were run and recorded in the source audit.

**Conclusion:** Preserve expiring motion leases, the typed HAL boundary, and
Unitree Sport. Fix final safety ordering first: the ordinary proximity/TTC
veto precedes an acceleration-limited shaper, so it can retain nonzero residual
motion. Physical missing/stale LiDAR, pose, or transform must HOLD instead of
falling back to point-goal translation. Truth pose is not production
localization, and the Unitree path is deliberately uncommissioned.

**Confidence:** high for source findings; medium for physical impact until
measured on commissioned hardware.

**Disagreement resolved:** The explicit latched E-stop does directly stop the
manager. The defect is narrower: ordinary sensor safety stops are not guaranteed
exact-zero after shaping. The report does not claim all stop paths are broken.

## N2 — behavior, task lifecycle, and instruction audit

**Question:** Why do simple language tasks fail even when a target or path is
available?

**Repository evidence:** deterministic intent routing, PlanSketch/PlanIR,
compiler, validator, task executive, runtime adapter, follow/search/spatial
channels, terminal witnesses, clarification, reactions, and strict product
tests.

**Conclusion:** Keep the typed compiler/executive boundary, but make
task-revision and motion-channel state atomic. `come here` needs terminating
`ApproachOwner`, while follow remains explicitly persistent. Invariants must be
per task, waits need admission/queue/precondition/step/task deadlines, and
declared recovery must compile into real bounded subtrees. One relation registry
must drive both goal generation and independent success witnesses.

**Confidence:** high; defects are directly visible in code and one resume
failure is an honest xfail.

**Disagreement resolved:** A stronger reasoning model may improve novel task
decomposition, but cannot repair inconsistent task authority or false terminal
success. Model work follows the lifecycle fix.

## N3 — classical and model-based navigation

**Question:** What is the strongest near-term controller direction without
rewriting the voice stack around ROS?

**Primary sources:** Nav2 Route/Smac/RPP/MPPI/Rotation Shim/smoothing/Collision
Monitor documentation, ROS 2 actions, Unitree SDK2 Sport, CMU Go2 autonomy,
Point-LIO, RTAB-Map, nvblox, and elevation mapping. Links are in
[SOURCE_LEDGER.md](SOURCE_LEDGER.md).

**Conclusion:** Add a pinned Nav2 sidecar behind versioned IPC. Use Smac 2-D +
Regulated Pure Pursuit as the interpretable baseline, then State Lattice/MPPI as
challengers. Use one velocity smoother and a contextual rotation shim. Penalize
lateral motion for ordinary travel without deleting it. Parcel's independent
metric-geometry monitor remains after all planner/smoother output, and Sport
continues to own gait and balance.

**Confidence:** high that this is the correct experiment; medium that MPPI will
win broadly. The current evidence is one upstream success on a BARN world where
Parcel timed out, not a general result.

**Disagreement resolved:** “Turn first, then move” is useful for large heading
errors but unsafe as a universal rule in tight crowds. A contextual shim plus
forward/lateral costs is preferable to mandatory turn-in-place behavior.

## N4 — downloadable navigation models

**Question:** Which current open artifacts are close enough to Parcel's sensor,
embodiment, and task contracts to justify integration?

**Primary sources:** official repositories/model cards/papers for
MiniCPM-RobotTrack, CE-Nav, InternVLA-N1, X-NavDP, CityWalker, NaVILA,
StreamVLN, Uni-NaVid, VLFM, NoMaD/ViNT, VAMOS, OmniNav, and OmTrackVLA;
Qwen-RobotNav as an architecture-only reference.

**Conclusion:** There is no single replacement brain. Profile the locally stored
CityWalker artifact first; screen CE-Nav as the released Go2 local-policy
challenger; shadow X-NavDP for bounded RGB-D local trajectories only after its
terms clear; shadow MiniCPM-RobotTrack for owner-follow waypoints; use
VLFM-style frontier scoring for unseen semantic targets; and compare VAMOS,
OmniNav, and InternVLA-N1 only in their legally eligible research roles. Every
model emits a TTL-bound proposal and is isolated from motor authority.

**Confidence:** medium. Availability, license, sensor fit, and author metrics are
well sourced; Parcel latency, co-residency, identity, and closed-loop quality are
unmeasured.

**Disagreements and caveats:**

- InternNav code is MIT; current InternVLA System 2/DualVLN README badges
  declare CC BY-NC-SA 4.0, while machine-readable Hub metadata/artifact grants
  are absent. InternData's gated text and YAML metadata also disagree.
  Product use is blocked; isolated research requires explicit legal approval.
- X-NavDP's self-contained subtree has an MIT file, while its checkpoint lacks
  declared terms, the parent has no top-level license and a CC BY-NC-SA README,
  and Isaac assets have separate restrictions.
- The local CityWalker checkpoint is byte-identical to the official v1.0
  GitHub asset (SHA-256 `a42326778e5e318c6222575dc5e02f1794d9a60cce4dc8f8a2ee5df7dc6d1c29`).
  It still scans `NOASSERTION`; Apache terms on the separately converted Hugging
  Face artifact do not automatically establish the original asset's scope.
- Qwen-RobotNav is a strong design reference, but its official repository says
  there is currently no plan to release weights.
- CE-Nav publishes an MIT repository, evaluation code, VelFlow expert, and Go2
  checkpoint, but its training code is still listed as forthcoming and it pins
  a legacy Isaac Sim release. Checkpoint and simulator terms remain separate.
- VAMOS now publishes inference/ROS code plus planner and Spot/HOUND artifacts;
  its model card applies Gemma terms and a noncommercial data restriction, its
  repository has no detected top-level license, and it has no Go2 affordance
  checkpoint.
- OmniNav publishes code and checkpoints but relies on legacy Habitat variants;
  repository and ModelScope artifact terms need review, and it has no verified
  Go2 deployment evidence.

## N5 — perception, localization, and semantic memory

**Question:** What sensor-derived state is required for instructions such as
“walk to the sidewalk” or “wait by the lamppost”?

**Primary sources:** CMU Go2 autonomy/Point-LIO, RTAB-Map, nvblox,
elevation_mapping_cupy, RT-DETR, PP-LiteSeg, DeepStream tracking, OSNet/
FastReID, Grounding DINO, SAM 2, PaddleOCR, timestamp synchronization and
extrinsic-calibration documentation, Clio/Khronos/VLMaps/ConceptGraphs.

**Conclusion:** Separate a fast camera/LiDAR geometry lane, fast closed-set
semantic/owner lane, and slow queried open-vocabulary/OCR lane. Implement real
MAP/ODOM localization with covariance and transform history. Semantic memory
stores provenance, uncertainty, TTL, reachability, and re-observation; raw
geometry alone declares free space. Owner identity is an enrolled multi-frame
posterior, never a simulator ID or nearest-person shortcut.

**Confidence:** high for contracts; medium for component selection until
mounted-camera/LiDAR data and Orin profiles exist.

**Disagreement resolved:** The built-in L1/CMU path is a useful baseline, not a
complete sensor solution. Its documented low-obstacle, drift, timestamp, and
delay caveats require mount-specific tests and may justify depth or a different
3-D LiDAR.

## N6 — owner following, dynamic people, and social behavior

**Question:** How should the dog follow consistently without cutting through
walls, switching owners, or behaving unnaturally in crowds?

**Primary sources:** MiniCPM-RobotTrack, Follow-Bench, HuNavSim, MetaUrban,
Trajectron++, RVO2, and Nav2 social-cost references, plus Parcel's follow and
dynamic-cost code.

**Conclusion:** Replace direct proportional follow velocity with a 10–20 Hz
formation-goal generator that samples reachable owner-relative poses and feeds
the common planner. Fuse identity, visibility, motion, geometry, and ambiguity;
stop/search/ask on loss. Start human prediction with calibrated CV/CA/turn
models. Fix Parcel's crowd-cost normalization and retain the riskiest tracks,
not source order. Social comfort is a soft cost; raw geometry is hard.

**Confidence:** high for architecture and current crowd-cost defect; medium for
which learned predictor or follower will win.

**Disagreement resolved:** MiniCPM-RobotTrack is the closest released Go2 owner-
follow proposer, but its own nonzero collisions and absent-person caveat mean it
cannot decide identity, target presence, or safety.

## N7 — instruction following and behavior planning

**Question:** How should conversation, common commands, long-horizon planning,
affect, and task interruption compose at low latency?

**Primary sources:** SayCan, Inner Monologue, PlanBench, BehaviorTree.CPP,
PlanSys2, FunctionGemma, constrained generation, KnowNo, SayPlan, RT-H, and the
Parcel voice/planner/executive code.

**Conclusion:** Use one `TaskRequestV1`; compile common tasks deterministically;
run novel planning asynchronously against a frozen evidence snapshot; and keep
conversation streaming independently. The reasoning model proposes the next
semantic skill/goal, a navigation model may propose a short trajectory, and the
executive chooses execute/defer/queue/drop/clarify. It owns resources,
interruptibility, recovery, and success. Inferred affect never interrupts a
critical road-exit or recovery; emergency stop remains immediate.

**Confidence:** high for authority separation; medium for the eventual best
small intent model, which requires a Parcel calibration set.

**Disagreement resolved:** Splitting conversation and planning is recommended,
but not as two competing authorities. Both communicate through typed events and
only the executive authorizes behavior.

## N8 — evaluation, benchmarks, and dynamic simulation

**Question:** What evidence ladder can distinguish better navigation from a
benchmark-specific adapter or oracle shortcut?

**Primary sources:** BARN/DynaBARN 2026, Follow-Bench, MetaUrban, HuNavSim,
Arena-Rosnav, Habitat/VLN-CE, NaVILA-Bench, OmniGibson/BEHAVIOR, and Parcel's
stored result artifacts.

**Conclusion:** First freeze a product-path headless suite and causal oracle
replays, then BARN controller regression, Follow-Bench, MetaUrban/HuNavSim,
indoor language suites, Go2-specific physics, HIL, and supervised courses.
Adapters transform observations/actions only. Use matched-information and
full-product A/Bs, isolated truth-side scoring, paired seeds, failure-inclusive
latency, family-level metrics, and hard promotion vetoes.

**Confidence:** high for evidence policy; medium for MetaUrban/legacy Habitat
operational cost because Parcel's real adapter is not implemented.

**Disagreement resolved:** BARN's official 50×10 worlds are hidden organizer
evaluation, not public regression. DynaBARN is separately reported. Neither is
a voice, owner-follow, city-semantics, or quadruped-safety certificate.

## RL1 — strongest case for Parcel-owned training

**Question:** Assume reuse is insufficient: what could custom learning add, and
what is the least dangerous/highest-return target?

**Repository and research evidence:** current RL environment/reward/backend,
MetaUrban wrapper, data recording, Unitree RL reference stacks, DAgger,
residual RL, offline RL, FLaRe, and SPOC.

**Conclusion:** No-go now. The strongest future case is not end-to-end control;
it is a small ranker/social critic selecting or abstaining among explicitly
feasible short trajectories. Start with BC/DAgger, then compare either shielded
simulation RL or conservative offline RL only when its respective data premise
is true. Keep Sport, the common controller, and final safety outside learning.

**Confidence:** high for no-go; medium for the eventual ranker because stock
Nav2 MPPI does not expose a stable K-trajectory API and needs a sampler/plugin
feasibility spike.

**Distinct emphasis:** This workstream made the best affirmative training case,
then rejected immediate training because the environment, data, reward, serving,
and safety prerequisites fail.

## RL2 — strongest case for open-model and classical reuse

**Question:** Can released planners/models cover the gaps more cheaply and
reliably than custom RL, and what evidence would reverse that decision?

**Evidence:** model/license/runtime matrix, current hardware and artifacts,
measured NAV_INSTRUCT/BARN/follow results, current simulator and policy-serving
code, and established imitation/offline/residual methods.

**Conclusion:** Allocate zero RL GPU-hours now. Repair product contracts; add
Nav2; then evaluate only artifact-by-artifact legally approved, provenance-
pinned CityWalker, CE-Nav/X-NavDP, MiniCPM-RobotTrack, VLFM-style, or InternVLA
candidates in role-specific shadows. Train only when paired causal attribution
shows a repeated model-addressable residual after strong frozen baselines and
the proposed component has representative data plus a deployment ABI.

**Confidence:** high. Both independently framed RL workstreams converge on the
same decision for different reasons.

**Distinct emphasis:** Reuse does not mean blindly trusting a published score.
License, custom-code security, sensor/embodiment fit, target-device latency,
co-residency, independent task success, and deterministic fallback all remain
promotion gates.

## Cross-workstream synthesis

The strongest common conclusions were:

1. The immediate bottleneck is trustworthy authority/state/evaluation, not a
   lack of raw model capacity.
2. Unitree Sport should remain the low-level closed loop while Parcel matures
   planning, perception, behavior, and safety above it.
3. Navigation, following, and language-selected goals need one obstacle-aware
   execution lane and one final camera/LiDAR-derived safety authority.
4. Language and navigation models are replaceable proposers with distinct
   roles; none should emit raw Sport commands or declare task success.
5. Dynamic-city and benchmark work needs both information-matched component
   comparisons and full-product comparisons, followed by Go2 physics and
   physical gates.
6. Custom learning becomes rational only after a repeatable residual survives
   the classical/open-model ladder; its first likely form is bounded ranking,
   not end-to-end or low-level RL.

No workstream recommended changing Parcel behavior inside an evaluator merely
to increase a score. The top-decile goal remains benchmark-specific and subject
to collision, owner-identity, forbidden-region, false-success, and latency vetoes.
