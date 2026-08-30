# 2026-08-29 — duplex companion autonomy research index

**Target:** Unitree Go2 EDU+; likely AGX Orin 64 GB; camera; Mid-360-class
LiDAR; microphone array; speaker; optional Starlink.

**Evidence tier:** desktop code, replay, headless/kinematic simulation, and
procedural semantic simulation only.

**Autonomous physical motion:** **NO-GO**.

**Observe-only / motors-disabled HIL:** conditional on a reviewed engineering
checklist.

**Final-report status (updated 2026-08-30):** DSOAK-1 and the guarded commit
tier are complete. The extended nightly tier is a controlling red finding:
degraded-pose success floors failed. Focused remediation cleared three product/
environment findings; the repeated slow selection now has one retained stale
person-cell assertion, while the pose-drift capability failure is unchanged.
Three fresh independent Sol Ultra review passes are complete and retain
physical NO-GO. The later passes found service-graph/parity, Model-B lifecycle,
and concurrent revision-compensation/lock-order defects in preceding
remediations; bounded postfix fixes and evidence are in
[`SOL_ULTRA_POSTFIX_AUDIT.md`](SOL_ULTRA_POSTFIX_AUDIT.md). Hosted Model B candidate-Q absolute gates are complete
and refuted; its quota-truncated direct arm and calibrated human comparison
remain explicitly unmeasured. LHO-1 is complete.

## Decision

The proposed Model A / Model B split is useful only inside a typed, multi-rate
authority system:

- Model A is a trainable embodied-policy package with a nominal 10 Hz proposal
  head and a slower event-driven planning head. It proposes short trajectories,
  attention, reviewed expression, progress/risk, and replans; it does not own
  joints, safety, STOP, or completion.
- Model B has two separately scored jobs: owner-qualified steering into the
  task executive, and accepted receipt-backed events into narration context.
  Hosted Realtime produces friendly wording and prosody, never task truth.
- The task executive, deterministic planner/tracker, priority/TTL arbiter,
  final safety gates, `ControlManager`, and sole-writer gateway retain authority.
- Simulation should drive contract learning, fault coverage, dynamic-human
  scenario diversity, and champion/challenger ranking. It cannot certify mount
  integrity, acoustics, calibration, foot-ground mechanics, actuator braking,
  Orin thermals, or safe physical stopping.

The full recommendation is in
[`DUPLEX_PRODUCTION_ARCHITECTURE.md`](DUPLEX_PRODUCTION_ARCHITECTURE.md); model,
curriculum, storage, and budget details are in
[`TRAINING_AND_DATA_PLAN.md`](TRAINING_AND_DATA_PLAN.md). The final synthesis is
in [`SOL_METHODICAL_ASSESSMENT.md`](SOL_METHODICAL_ASSESSMENT.md).

## Controlling completed evidence

| Area | Result | Interpretation |
| --- | --- | --- |
| Instruction navigation | NAV_INSTRUCT 34/125, SR 0.272, SPL 0.2058; seven false arrivals | Reproducible and below generalization/promotion bar |
| Follow | 7/9 Follow, 2/2 Navigate, zero contacts in the narrow scripted bench | Group and cut-in fail; oracle tracks and kinematics do not certify people safety |
| Dynamic social | DSP-2: 580 episodes, 145/arm; S2 and S3 each had 25 contact episodes and all four hypotheses were refuted | No sidewalk, crosswalk, elevator, or safe-proximity promotion |
| Interruptions | Admission 24/32, amended success 11/28, return 8/9; every NAV-INT-1 hypothesis refuted | Plan-stack steering and arrival authority are not established |
| Typed task boundary | Brain 15/15, including 7/7 expected fail-closed | Useful contract evidence; zero physical episodes |
| Scripted duplex | 7/7 gates, 216 synthetic 10 Hz frames | Text-injected harness evidence, not acoustic/model quality |
| Corrected acoustic v2 | 25 cases / 223.4 s; 6 gates pass, 3 fail, 2 not measured; endpoint validity failure 0.3077 and virtual-audible ack p50 0.790 s | Measurement validity is repaired on the virtual rig; semantic endpointing and acknowledgement remain red, isolated acoustic STOP and physical motion sync remain unmeasured, and mounted audio/AEC remains red |
| Endpoint-policy sensitivity | Two byte-identical 1,560-cell direct replays; 0/30 declared settings pass and corrected-rig parity fails; two actual-`MicrophoneVoiceLoop` runs match all 52 default sample clocks | The duplicate runner is faithful, but no production threshold/timeout change or provisional motion admission is supported; frozen human/room/AEC holdout required |
| Conversation | Historical Realtime review: 6 pass / 8 mixed / 11 fail, 66 flags; MB-1 hosted Q completed 120/120 scenarios and failed every absolute gate | Candidate Q is refuted; hosted Q-minus-D and calibrated human quality remain unmeasured |
| Model A | MA-2 P0 passed on 300 teacher episodes; in P1 teacher/reflex/direct each reached 198/198 while every learned S/C16 seed reached 0/198 | Causal trace substrate passes; the learned challenger and hardware promotion are refuted |
| DMC-2 authority seams | 8,448/8,448 independently verified cases per run, identical digest | Individual executive/receipt/claim seams pass; their production composition is not evaluable/red |
| DMC-3 narration bridge | H1-H3 passed twice after the continuity amendment; H4 remains partial/red | Pure consumer continuity passes, but complete owner-authored runtime transition composition is absent |
| DMC-4 composed journal | Two identical 1,824-transition runs; 256/256 corruptions; 32-producer concurrency and bounded-overflow gates passed; post-review runtime regressions retain complete available lineage and reject expired queued frames | Owner journal → process-local Model-B frames is wired with drain-time freshness; commit-time timestamps, restart-safe state/cursors, independently authenticated live speech epoch/provider/audio, and authoritative child-resume lineage remain absent |
| Official Go2 mjlab | Clean install failed; pinned environment ran 32,768 timed physics steps and a 4,608-step PPO/checkpoint/ONNX smoke | Practical lower-locomotion simulator plumbing passes; no useful walking policy or physical claim |
| Stop-only safety | SOS-1 maintenance found and repaired READY-before-handler ordering; two parallel and two sequential current-source 256-case runs now pass H1-H5 with a strict verifier | Desktop fake-gateway evidence only; real STOP inputs, target timing, independent E-stop, and hardware qualification remain absent |
| Latency handoff | LHO-1 ran 1,980 paired schedules / 5,940 arm episodes four times; G0 reduced wait 91.93% and visible gaps 91.02% vs B0 with zero stale/safety violations; the fresh-process supplement passed | Guarded prefix/revisable-tail transaction passes only in a deterministic scalar simulator; no learned, 2-D, braking, or hardware claim |
| LIT-1 grounding audit | 5/5 failed missions produced a false “reached” statement | Valid blocking counterexample, not a production failure-rate estimate |
| DSOAK-1 durability | Artifact self-reports 43,380.014 s (12.050004 h), 66,434 episodes, and 664 sampled replays / 0 recorded mismatches; all 17 gate predicates pass post-run aggregate checks; verifier mutation 32/32 | Partially corroborated desktop procedural durability only. Monitor began 2.365 h late (80.377% coverage), strict process/temporal provenance is absent, narration oracle is refuted, key safety zeroes are coupled, and L0 remained stronger than A1 |
| Guarded repository gates | Latest commit tier: all hard rows pass, 11,330 unique non-slow tests selected (11,417 total; 87 slow). Extended nightly: degraded-pose floors red. After bounded remediation, the slow marker rerun is 1 failed / 74 passed / 8 skipped / 3 xfailed / 1 xpassed; the one failure is the unchanged 0.875-vs-0.90 person-cell pin | Desktop/injected evidence only; the quiet repeat's checkout identity matched start/finish, but nightly is controlling red and autonomous motion remains NO-GO |

The product-baseline numbers, provenance, and caveats are in
[`product-evals/RESULTS.md`](product-evals/RESULTS.md) and the controlling
[`product-evals/VERDICT.md`](product-evals/VERDICT.md); later experiment rows
link their own controlling artifacts below.

## Experiment register

| ID | Folder | State and controlling interpretation |
| --- | --- | --- |
| Product baseline | [`product-evals/`](product-evals/) | Complete; generalized navigation, social safety, acoustics, and conversation-motion authority are red or unmeasured |
| Literature | [`literature/`](literature/) | Complete focused review of streaming VLN/VLA, hierarchical policies, intervention, feedback, social navigation, and sim-to-real |
| NAV-INT-1 | [`nav-interrupt-1/`](nav-interrupt-1/) | Complete; all registered hypotheses refuted |
| DMC-1 | [`duplex-mission-control-1/`](duplex-mission-control-1/) | Complete but its receipt/narration oracle and learned-policy evidence fail independent audit; no promotion |
| DMC-2 | [`duplex-transaction-2/`](duplex-transaction-2/) | Complete; seam conformance passes, architecture composition red |
| DMC-3 | [`duplex-transaction-3/`](duplex-transaction-3/) | Complete through amendment 1; H1-H3 pass twice, H4 runtime composition remains partial/red, and promotion fails |
| DMC-4 | [`duplex-transaction-4/`](duplex-transaction-4/) | Complete; `DMC4_COMPOSED_PASS` for the frozen source transaction; the additive [`runtime-journal-composition/`](runtime-journal-composition/) wires disarmed process-local frames. Post-review frames preserve and drain-revalidate available authority lineage; commit-time/restart/live-session/provider/audio remain red |
| LIT-1 audit | [`lit1-grounding-audit/`](lit1-grounding-audit/) | Complete; grounding claim refuted by five false terminal statements |
| Acoustic v1 audit | [`ACOUSTIC_LOOP_V1_AUDIT.md`](ACOUSTIC_LOOP_V1_AUDIT.md) | Complete diagnostic; retains the 5/9 historical score, invalidates interpretation of all four red metrics, hardens drain-time abort, and keeps mounted audio/AEC red |
| Acoustic v2 | [`acoustic-eval-v2/`](acoustic-eval-v2/) | Complete corrected virtual-rig measurement; 6 pass / 3 fail / 2 not measured, with endpoint semantics and audible acknowledgement red |
| Endpoint-policy | [`endpoint-policy-1/`](endpoint-policy-1/) | Complete exploratory sensitivity study; two identical runs, no declared point passes, baseline parity red, and no production nomination |
| MA-1 | [`model-a-stream-1/`](model-a-stream-1/) | Run artifacts exist, but causal leakage, label/application mismatch, confounded splits, changed thresholds, and scoring defects invalidate generalization; promotion refuted |
| MA-2 | [`model-a-stream-2/`](model-a-stream-2/) | Complete through P1; P0's 300-episode causal teacher substrate passed, but all six learned runs scored 0/198 and P1 is refuted |
| MB-1 | [`model-b-narration-1/`](model-b-narration-1/) | Hosted Q completed 120/120 and failed all absolute gates; D stopped at 2/120, so Q-minus-D and calibrated human failure rates remain unmeasured |
| DSP-2 | [`dynamic-social-progress-2/`](dynamic-social-progress-2/) | Complete; S2/S3 each contacted in 25/145 episodes and H1-H4 are refuted; no safe proximity or physical promotion |
| MJLAB-1 | [`mjlab-feasibility-1/`](mjlab-feasibility-1/) | Complete; strict clean-install gate failed, while pinned physics/PPO/export plumbing passed; no trained locomotion or hardware readiness |
| SOS-1 | [`stop-only-safety-1/`](stop-only-safety-1/) | Current maintenance-3 source/fake-gateway evidence passes after preserving a red concurrent race and repairing product/verifier/oracle defects; real STOP inputs and target qualification remain absent |
| DSOAK-1 | [`duplex-soak-1/`](duplex-soak-1/) | Complete: scoped `SUPPORTED_PROCEDURAL_SOAK` from self-reported, partially corroborated 12.050004 h evidence, post-run aggregate checks, and verifier mutation; strict provenance and narration truth are absent |
| Pose-drift nightly audit | [`POSE_DRIFT_NIGHTLY_AUDIT.md`](POSE_DRIFT_NIGHTLY_AUDIT.md) | Complete read-only attribution: same metric/substrate, real post-Aug-21 regression; isotropic commissioned clearance and missing safe-frontier/MAP→ODOM handling are the controlling repair targets |
| Nightly remediation audit | [`NIGHTLY_REMEDIATION_AUDIT.md`](NIGHTLY_REMEDIATION_AUDIT.md) | Bounded literal, packaging, and terminal-pose repairs verified; slow rerun retains one stale person-cell assertion and the independent pose-drift gate remains red |
| Sol Ultra final audit | [`SOL_ULTRA_FINAL_AUDIT.md`](SOL_ULTRA_FINAL_AUDIT.md) | Fresh read-only ultra review confirms NO-GO, downgrades soak provenance, finds the invalid runtime profile and latent authority defects, and separates code remediations from hardware blockers |
| Post-Ultra remediation | [`POST_ULTRA_REMEDIATION.md`](POST_ULTRA_REMEDIATION.md) | Bounded software findings fixed and regression-tested; hardware, deployment-artifact, sensing, storage, and nightly blockers remain open |
| Sol Ultra post-fix audit | [`SOL_ULTRA_POSTFIX_AUDIT.md`](SOL_ULTRA_POSTFIX_AUDIT.md) | Second and third read-only ultra passes found and drove fixes for service failure/parity semantics, valid Model-B histories, and concurrent revision compensation/lock order; 91-test combined and 19-test adversarial panels pass, physical NO-GO unchanged |
| LHO-1 | [`latency-handoff-1/`](latency-handoff-1/) | Complete; `LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED` across four 5,940-episode scalar scheduling runs, with local distinct-process provenance for C/D; no learned, perception, dynamics, braking, Orin, or physical claim |
| Conversation bridge | [`conv-bench-1/`](conv-bench-1/) | Deterministic scoring bridge available; model/human claims retain their evidence labels |
| Integrated sim loop | [`sim-loop-1/`](sim-loop-1/) | Scripted integration harness exists; audited false terminal language prevents promotion |
| Mount code review | [`mount-readiness-code-review/`](mount-readiness-code-review/) | Read-only review produced physical NO-GO; several software defects were subsequently hardened, while independent safety and hardware evidence remain absent |

## Production transaction to build

```text
sensors + final owner-qualified transcript
        -> EmbodiedFrame + SteeringEvent proposal
        -> TaskExecutive task stack and exact revision tuple
        -> short-lease Model A proposal
        -> deterministic planner/tracker, arbiter, safety, ControlManager
        -> sole-writer gateway and vendor locomotion
        -> accepted execution result and authenticated narrative receipt
        -> Model B compact context
        -> hosted Realtime wording / local fallback
```

Today, learned Model A is not integrated, no qualified learned artifact is
loaded, the normal launcher neither injects nor arms a commissioned physical
manager, and normal backend observations are wrapped with simulation origin.
DMC-4 adds a bounded owner-authored
journal of immutable executive transition records and a journal-only authenticated narration bridge
for every constructible frozen transition. The normal `RobotRuntime` now polls
that journal into bounded, process-local, non-speaking Model-B frames. It does
retain exact plan/step/attempt/mission/action/evidence/source/speech/deadline
lineage and rechecks queued-frame freshness at drain. It does not bind speech
generation to an independently authenticated live session epoch, persist a
restart-safe cursor, carry authoritative separate-child resume lineage, or
deliver provider/audio context. The [one-page code
map](../../docs/PRODUCTION_RUNTIME_CODE_MAP.md) shows the exact current source
boundaries.

## Immediate priorities

1. Preserve the completed DSOAK-1 bytes and address the extended-nightly
   findings without moving frozen capability floors. In particular, add a
   hard-inflation-preserving reachable-frontier fallback, direction-aware
   clearance, and the missing MAP→ODOM goal transform before rerunning the
   7×61 drift matrix; then obtain a fresh independent review. Do not assign a hosted Q-minus-D
   effect or calibrated human failure rate from the quota-truncated MB-1 arm.
2. Extend the new disarmed DMC-4 runtime observer to a supervised live lane:
   add independently owned session authentication, a persistent/restart-safe
   cursor, speech-generation epoch/cancellation, provider backpressure, audio
   tests, and explicit separate-child resume lineage. Keep wording unable to
   actuate or certify an outcome.
3. Preregister MA-2 P2 around learner-visited recovery data and residual/hybrid
   control; keep direct/reflex control as champion and require closed-loop wins
   across every frozen split before scaling.
4. Use corrected acoustic v2 without tuning to its discovery corpus: build a
   frozen human/room/AEC holdout, repair premature endpointing and persistent
   playback latency, and add isolated owner/robot STOP channels plus actual
   BeatLayer motion. Then test mounted mic/speaker/AEC plus Starlink loss/jitter
   while local safety stays independent.
5. Hermetically pin the completed MJLAB-1 substrate, train and gate an actual
   Go2 velocity policy, benchmark its export on AGX Orin, mirror its I/O in a
   second engine such as Isaac Lab, and keep dynamic-human/semantic curricula in
   the higher simulator layers.
6. Build the governed off-robot data plane: encrypted immutable blobs,
   relational task/event/receipt/consent/experiment metadata, local offline
   spool, shadow candidates, signed promotion, and rollback. No self-promotion.
7. Implement LHO-1's guarded prefix/revisable tail in the disarmed runtime and
   repeat its invariants with measured Orin timing, 2-D/3-D swept volumes, and
   commissioned braking. Move to motors-disabled HIL only after final software
   review. Wire and target-qualify SOS-1 plus a physically independent E-stop;
   tethered motion additionally requires measured localization, calibration,
   stopping, power, thermal, and mechanical evidence.

## Evidence rules

- `desktop`, `replay`, `procedural`, `headless`, `MuJoCo`, `second-engine`,
  `HIL`, `stationary hardware`, and `moving hardware` remain separate tiers.
- Process completion is not mission success. A narration is grounded only when
  exact accepted evidence licenses its tense, task identity, and result.
- Learned raw proposals, admitted commands, executed commands, and measured
  outcomes are stored separately. A model never labels its own safety.
- No frozen corpus or threshold moves after results are observed; post-hoc work
  is labeled exploratory.
- Zero contacts, false arrivals, stale-sensor motion, unauthorized entry, and
  post-STOP authorization are hard gates, not averages to trade away.
- Pending experiments remain pending; interim counters cannot appear in the
  final conclusion.
