# Task 1 · DUPLEX-GEN-1 — trainable companion fluidity and mount-readiness

**Date:** 2026-08-29 (America/New_York)

**Last update:** 2026-08-30 (America/New_York)

**Status:** COMPLETE · SOFTWARE RESEARCH CLOSED · PHYSICAL MOTION NO-GO

**Physical-motion status:** **NO-GO**

**Permitted hardware rung:** observe-only or motors-disabled HIL, conditional on
a reviewed engineering checklist

## Owner outcome

Research, design, implement, and evaluate the shortest credible path to a
conversational autonomous companion on a Unitree Go2 EDU+ with an AGX Orin,
camera, Mid-360-class LiDAR, microphone, speaker, and Starlink. The dog should
sustain multi-turn conversation while navigating, redirect safely during a
mission, express state through reviewed body behavior, recover quickly from
transient pedestrian blocks, and learn from simulation without self-granting
motion authority.

The concrete transaction of record is:

```text
go to door -> owner interrupts: check sofa for keys -> suspend door mission
-> navigate/search at sofa -> report arrival and key evidence separately
-> offer to resume door mission -> resume only after explicit acceptance
```

## Review of Claude's prior work

The local Claude/Fable records in
[`ROBOT_READY_PLAN.md`](../../20260824/task_3/ROBOT_READY_PLAN.md) and
[`CLAUDE_RESPONSE.md`](../../20260824/task_4/CLAUDE_RESPONSE.md) correctly
established three boundaries that remain binding:

- the gateway/runtime seam must be sole-writer, restart-disarmed, TTL-governed,
  and tested against faults before physical motion;
- strong desktop contracts and simulator runs are not robot evidence; and
- motion-enabled mounting is NO-GO while an observe-only Stage 0 can be useful
  after explicit mechanical, electrical, time-sync, audio, and independent-stop
  review.

The separately supplied
[Claude Code artifact](https://claude.ai/code/artifact/5adb2865-5165-4936-b358-bc871687823e)
did not return content through an unauthenticated fetch or exact-ID search on
2026-08-29. No claim below relies on unseen bytes from that private surface;
the mount assessment uses the checked-in Claude/Fable records plus an
independent source and test review of this checkout.

The August 29 audit updates the implementation details and makes the capability
gap more explicit. The gateway now has a native vendor port and commissioned
runtime adapter. SOS-1 also adds an independently verified source/fake-gateway
stop-only service and split credential principal. Its real voice/remote/GPIO
STOP inputs, target deployment and timing, physically independent E-stop, and
stopping-distance qualification are still absent. Synchronized physical
perception/localization, Orin qualification, and mounted acoustics also remain
absent. The new navigation and conversation evaluations strengthen rather than
relax Claude's NO-GO.

The current-checkout Task 2 follow-up is independently reviewed in
[`../../../research/20260829/CLAUDE_TASK2_REVIEW.md`](../../../research/20260829/CLAUDE_TASK2_REVIEW.md).
Its integrated mount-ready claim is rejected. The initial C0 evidence was
stale/blind; a subsequent independent nine-row refreeze repaired that evaluator
and killed 7/7 mutants twice, but has no hard-stop witness. C6 queue lineage is
absent, C2 misses its arrival-authority bar,
C1 retains global scene state and regressions, and C3 ships disabled while its
enabled arm worsens another failure class. C7 is retained as evaluator work;
C4/C5 remain unwired leaf prototypes.

## Architectural recommendation

Use a typed, multi-rate Model A / Model B system; reject a monolithic model that
owns raw sensors, global planning, joints, completion, and speech.

- **Model A:** one trainable embodied-policy package with shared temporal state,
  a nominal 10 Hz fast proposal head, and an event-driven 0.5–2 Hz planning
  head. It proposes short trajectories or reviewed behavior, attention,
  expression, progress/risk, and replan requests. The 20–50 Hz tracker,
  50 Hz `ControlManager`, final safety shield, and vendor gait/balance controller
  remain deterministic and independent.
- **Model B ingress:** turns a final owner/addressee-qualified transcript into a
  typed `stop|revise|interrupt_now|queue|keep|resume|status|clarify` proposal.
  The task executive—not Model B—commits the change.
- **Model B egress:** turns an accepted execution event and authenticated receipt
  into compact narration context. Hosted Realtime chooses friendly wording and
  prosody, but may not establish that an action started, succeeded, or found an
  object.
- **Task executive:** owns task stack, parent/child lineage, revisions,
  checkpoints, suspend/resume, attempts, and terminal state. A short-lived Model
  A proposal is valid only for its exact task tuple.
- **Motion:** all proposals pass the explicit planner/tracker, priority/TTL
  arbiter, freshness/collision/braking gates, `ControlManager`, and the one
  vendor-writing gateway.

The production contract and code mapping are in
[`DUPLEX_PRODUCTION_ARCHITECTURE.md`](../../../research/20260829/DUPLEX_PRODUCTION_ARCHITECTURE.md)
and [`PRODUCTION_RUNTIME_CODE_MAP.md`](../../../docs/PRODUCTION_RUNTIME_CODE_MAP.md).

## Methodical workstreams and acceptance

| Workstream | Required artifact / test | Promotion rule |
| --- | --- | --- |
| Product baseline | Re-run navigation, Follow, interruption, brain, duplex, acoustic, current conversation, and mount-boundary suites with exact provenance | Report failures and unavailable tiers; no aggregate “green” may hide false arrival, contact, or missing hardware evidence |
| Model A | Preserve MA-2's leakage-free P0/P1 substrate; add learner-visited recovery data and residual/hybrid P2 challengers against the direct/reflex champions | Learned head stays shadow-only until every seed improves blind-family closed-loop mission/progress metrics without increasing raw risk, false arrival, intervention, STOP, or latency tails |
| Model B | Matched scripted/local/hosted arms, full task-stack steering, receipt-grounded event context, machine metrics plus blinded adjudication, exact TTFT/total latency and cost | Zero premature terminal claims; exact task/revision/step/attempt/epoch/speech binding; sample floor and adjudication must complete |
| Transaction authority | DMC-3 authenticated event/consumer seam plus the DMC-4 owner-authored executive transition journal, with replay/restart/corruption/overflow cases | All individual seams and their complete runtime composition pass; wrong, stale, replayed, post-STOP, or cross-task evidence fails closed |
| Dynamic people | Stable tracks, uncertainty and predicted occupancy; braking-safe committed prefix; asymmetric stop/resume; sidewalk, crosswalk, and elevator scenario families | Zero contacts/hard-envelope breaches/unauthorized entries; false-stop and clear-to-progress bounds pass on blind layouts and sensor mutations |
| Duplex durability | At least 12 wall-clock hours of deterministic/adversarial transaction and liveness soak, independently verified from append-only artifacts | No unsafe admission, premature completion, replay mismatch, epoch confusion, resource leak, or nondeterministic digest |
| Sim-to-real | Same policy I/O across deterministic replay, current MuJoCo, official Unitree MuJoCo/mjlab, Isaac Lab second engine, social simulation, recorded-sensor replay, then HIL | Cross-engine and domain-randomized performance is necessary but never substitutes for target timing, acoustics, calibration, mechanics, or stop-distance evidence |

## Evidence snapshot at task creation/update

- NAV_INSTRUCT: 34/125 success (SR 0.272, SPL 0.2058), seven false arrivals.
- Follow: 7/9 scripted follow and 2/2 point navigation; misses group and cut-in.
- NAV-INT-1: all registered interruption hypotheses refuted; blind queue
  classification is 0.667 and arrival authorities disagree on 17/80 legs.
- DSP-2 dynamic social: 580 episodes, 145/arm. S2 and S3 each record 25/145
  contact episodes; all four hypotheses are refuted. No safe-proximity,
  public-sidewalk, crosswalk, or elevator promotion.
- Corrected acoustic evaluator v2 passes 6 gates, fails 3, and marks 2 not
  measured. Four of 13 endpoint fixtures commit prematurely or multiply;
  virtual audible acknowledgement is 0.790 s p50; isolated acoustic STOP and
  physical motion/audio synchronization are not measured. Its 13/14 prosody
  gate covers audio transport only. Generation-bound PortAudio abort and the
  first-write-attempt hook are regression-tested; mounted audio/AEC remains red.
- Endpoint-policy sensitivity replayed 30 declared confidence/silence points
  over 52 phase variants twice. The runs are byte-identical, 0/30 points pass,
  and direct replay fails corrected-v2 parity. No threshold/timeout change or
  provisional motion admission is supported; a frozen human/room/AEC holdout
  is required.
- Conversation: historical Realtime review is 6 pass / 8 mixed / 11 fail; it
  is not a blinded measurement of the current provider. MB-1 hosted Q completed
  120/120 scenarios and failed its absolute gates: grounding 0.6120–0.7274,
  new-goal acknowledgment 99/225, completion 11–27/165, and resume offer
  10–11/30. Hosted D stopped at 2/120, so Q-minus-D remains unmeasured; the local
  blind audit is not calibrated human gold.
- DMC-2: 8,448/8,448 cases independently conform per run at each existing seam,
  but the end-to-end executive-to-narration composition is not evaluable/red.
- DMC-3: after amendment 1, H1-H3 pass twice; H4 complete runtime composition
  remains partial/red. DMC-4 then passed two identical 1,824-transition runs,
  256/256 corruptions, concurrency, replay, and bounded-overflow gates for its
  source-level owner-authored journal and journal-only bridge. A later 26-test
  hardening step wires a process-local, journal-only observer into normal
  runtime. Post-Ultra hardening retains exact plan/step/attempt/mission/action/
  evidence/source/speech/deadline lineage and revalidates queued frames at
  drain. Commit-time freshness is still not implemented because event TTL
  begins at poll. Persisted executive/outbox/provider-ack state, independently
  authenticated live speech generation, provider/audio, and authoritative
  separate-child resume lineage remain red.
- MA-1 remains invalid as independent generalization evidence. MA-2 P0 passed
  its 300-episode causal teacher probe; P1's teacher, reflex, and direct controls
  each reached 198/198 held missions, while every S/C16 learned seed reached
  0/198. The learned challenger is refuted and no checkpoint is promoted.
  The normal launcher also has no commissioned physical manager/arm route;
  `Go2Backend` refuses motion and the runtime carrier snapshot is stamped
  simulation, so Model A has no mountable physical proposal path today.
- MJLAB-1: the strict clean-install gate failed, while the pinned environment
  passed 32,768 timed physics steps and a 4,608-step PPO/checkpoint/ONNX smoke.
  This establishes lower-locomotion simulator plumbing, not a trained policy.
- SOS-1: current maintenance exposed and preserved a reproducible
  READY-before-signal-handler failure, repaired the product ordering, replaced
  an instantaneous lifecycle oracle, and tightened a false-positive verifier.
  Two parallel and two sequential 256-case current-source runs now pass H1-H5
  with one normalized digest. Physical inputs, target timing, braking,
  independent E-stop, and hardware qualification remain absent.
- DSOAK-1 completed after 43,380.014 monotonic seconds (12.050004 h), 66,434
  episodes, 664 sampled replays with zero recorded mismatches, strict
  recomputation of all 17 gates, and a 32/32 verifier-mutation result. Its
  external monitor began 2.365 h late and covers 80.377% of elapsed time; its
  narration oracle is refuted and deterministic L0 remained stronger than A1,
  so the verdict supports desktop procedural durability only. LHO-1 completed
  four reproducible 5,940-episode runs; its additive
  local-host supplement proved C/D were distinct sequential child processes
  and passed all eight integrity gates. G0 reduced waiting 91.93% and visible
  gaps 91.02% versus B0 with zero authored stale or safety violations. This is
  not learned, 2-D, quadruped, braking, Orin, or physical evidence.

Product-baseline measurements and caveats are in
[`product-evals/RESULTS.md`](../../../research/20260829/product-evals/RESULTS.md);
later workstreams retain their controlling artifacts in the research index.

## Data and continual-improvement system

Create a governed off-robot research plane, not online self-modifying control.
Store immutable raw blobs (sensor/audio only with consent), normalized embodied
frames, task/plan/event/receipt tables, executed command and intervention logs,
conversation turns, model/config/calibration digests, scenario manifests,
evaluation outcomes, and human review. Use append-only object storage plus a
relational metadata/consent/experiment registry; encrypt, retain, revoke, and
delete by owner and data class. The robot spools locally while offline and
uploads only approved records when Starlink is available.

Candidates train off-robot, replay against immutable splits, run shadow-only on
the Orin, receive signed human promotion, and always retain a rollback target.
No trainer, model, cloud service, or hosted LLM can activate itself or change a
safety floor.

## Immediate implementation order

1. Preserve the completed DSOAK-1 evidence and address the extended-nightly red
   findings without changing frozen floors. The fresh independent Sol Ultra
   review is complete; its bounded software fixes and remaining physical
   blockers are recorded in the research index. MB-1's hosted direct arm and
   calibrated human comparison remain unmeasured; assign no comparative/human
   failure rate.
2. Extend the process-local DMC-4 observer to a supervised live lane: timestamp
   transitions at executive commit, persist executive/outbox plus independent
   read/consume/provider-ack cursors, propagate and revalidate deadline/session/
   speech lineage at provider and audio boundaries, add bounded async dispatch,
   and make separate-child resume lineage authoritative. Keep narration
   non-actuating.
3. Preregister MA-2 P2 around learner-visited recovery data and residual/hybrid
   control. Keep direct/reflex control as champion and require closed-loop wins
   on every frozen split before scaling.
4. Use corrected acoustic v2 as the desktop baseline: fix premature endpoint
   commits and slow audible acknowledgement, add isolated robot/owner channels
   for acoustic STOP and an actual BeatLayer motion trace, then test mounted
   mic/speaker/AEC plus Starlink jitter/loss without putting speech on the
   control critical path.
5. Hermetically pin the completed MJLAB-1 substrate, train and gate an actual
   Go2 velocity policy, benchmark the export on AGX Orin, mirror its contract in
   Isaac Lab, and keep predicted-human sidewalk/crosswalk/elevator curricula in
   the higher simulation layers.
6. Stand up encrypted object storage plus the consent/metadata registry and run
   a shadow-only champion/challenger loop.
7. First compose a permanently disarmed physical-shadow runtime with honest
   physical snapshot provenance, passive commissioned control, and fake-gateway
   replay. Integrate LHO-1's guarded prefix/revisable tail and repeat its invariants with
   target timing, 2-D/3-D swept volumes, and commissioned braking; then perform
   motors-disabled HIL and stationary commissioning. Wire and target-qualify
   SOS-1 plus a physically independent E-stop; proceed to tethered, speed-capped
   motion only after physical stopping, localization, calibration, power,
   thermal, and mechanical gates pass.

## Budget boundary

Use the owner's approximate monthly ceilings as separate hard ledgers:
Realtime voice **$300/month** and deliberative hosted text **$100/month**.
Prefer local perception, AEC/VAD, event compression, Model A, and routine Model B
work on the AGX Orin 64 GB. Send only change-triggered accepted events to hosted
Realtime; never stream raw camera/LiDAR or a 10 Hz state feed. Starlink failure
may degrade narration or remote research upload, never STOP, tracking, task
state, or local safety.

## Definition of done

This task closes only when DSOAK-1 finishes and verifies; a fresh Sol Ultra
review is addressed; the relevant guarded regressions are green; and the final
assessment reports positive, negative, and quota-limited/unmeasured results
without widening physical authority.
Even a completed task does **not** authorize autonomous physical motion; that
requires a separate hardware promotion record.
