# Task 2 · RTP-2 — correct the research exit and prototype-freeze review

**Date:** 2026-08-24

**Status:** REVIEW_REQUESTED · NOT DISPATCHED

**Author:** Codex (independent assessment of RTP-1 and the research direction)

**Required reviewer:** Claude

## Owner request

Review this assessment of Claude's current research work and decide whether it
is an accurate basis for ending broad research and freezing the first
prototype design. Correct or refute each finding with exact repository
evidence, then return one consolidated research-exit recommendation for owner
approval.

The objective is a mountable, supervised first prototype that can converse,
accept a bounded task, navigate one known indoor room, stop independently and
show safe continuous idle behavior on a Unitree Go2 EDU Plus. This is not a
request to claim generalized autonomy from desktop evidence.

This is a **review-only** task. It does not authorize implementation, another
research wave, experiment execution, new follow-up cards, changes to existing
designs or gold sets, process/service control, hardware activity, committing or
pushing.

## Exact review boundary

Immediately before this card was created:

- `main`, `origin/main` and `origin/HEAD` were all at `24378e6`
  (`research: independent adversarial intent-gate set (parcel-6c, 43 items;
  validated — 0 collisions with the frozen corpus)`);
- the tracked tree was clean; and
- `scrum/20260824/task_1/README.md` was the sole dirty overlay and was
  **untracked**.

This `task_2/README.md` is itself a later task overlay, not evidence that was in
`24378e6`. Claude must state the exact commit and dirty overlay actually read.
Do not normalize, stage or overwrite either untracked task prompt.

Primary evidence includes:

- `scrum/20260824/task_1/README.md` and `CLAUDE_REVIEW.md`;
- `research/20260824/README.md`;
- `research/20260824/nav-core/DESIGN.md`;
- `research/20260824/voice-gate/DESIGN.md`;
- `research/20260824/offline-first-cognition/DESIGN_v2_CONNECTED_PLANNER.md`;
- `research/20260824/offline-first-cognition/corpus/`;
- `research/20260823/localization-delegation-bench/RESULTS.md`;
- `research/20260823/MILESTONE1_DESIGN_FABLE.md`;
- the cited product paths in `src/parcel_robot/`; and
- existing hardware/audio/vendor acceptance records cited below.

## Executive assessment

Claude is moving in the right high-level direction: the work now scopes a
slow, supervised, one-room prototype; keeps model output outside motion
authority; makes the native sole-writer gateway and independent stop the next
physical build; and has correctly abandoned an LLM-as-continuous-tick design.
The H1-H10 path matrix is also candid that most research seams remain
harness/desktop evidence and are not constructed by `RobotRuntime`.

However, RTP-1's `ACCEPT_WITH_REQUIRED_CHANGES` is **not yet a reliable final
design-freeze record**. It contains one confirmed product-path error in C8,
overstates localization safety, specifies the wrong acoustic playback path,
and treats physically unproved Follow as the offline mobility floor. It also
leaves a contradiction in H9 and a stale milestone design.

The project is no longer primarily under-researched algorithmically. It is
under-validated at the hardware, authority, localization, acoustic, owner-
identity and deployment seams. Do not answer these gaps with a broad new desk
research program. Before software architecture freeze, run only the revised
**NAV-CORE** and corrected **VOICE-GATE** studies. Treat CONNECTED-PLANNER as a
small, capped acceptance probe for connected compound instructions; it must
not block starting M1-0. Everything requiring the delivered robot moves to a
box-day commissioning gate.

## Findings to confirm, correct or refute

### F1 · The research exit is close, but RTP-1 is not yet the freeze record

The following RTP-1 conclusions are sound and should be retained:

- H2 is closed: deterministic drives own the continuous tick; models may
  converse, phrase or compile bounded semantic proposals. Do not spend more
  model-comparison budget trying to make an LLM the heartbeat.
- The first ODD is one mapped indoor room, slow, supervised, with no public
  space, roads, stairs, crowds, rain or rough terrain.
- Unitree Sport owns gait and balance. Parcel owns semantic intent, governed
  velocity/task authority and stop behavior, not balance control in Python.
- M1-0, the native sole-writer gateway/governor plus an independent operator
  stop, is the next physical implementation lane.
- Full H8 exploration, broad generalized perception, governed continual
  memory, trainable initiative, outdoor autonomy and AGX/26B comparisons are
  deferred.

Required response: say which of these remain binding and identify any exact
repository fact that prevents research exit. A preference for more confidence
is not itself a reason to admit another study.

### F2 · C8 was incorrectly refuted; goal amendment can overlap an executive task

RTP-1 says the amendment path sends `requested="interrupt_now"` and therefore
refutes the race. That traces only the sender, not the policy decision:

- `src/parcel_robot/brain/executive.py:55-62` omits `goal_amend` from
  `VOICE_INTERRUPT_POLICY`; the default is `overlap`.
- `executive.py:571-585` resolves voice interrupts from the reason policy and
  returns `overlap` for that default. The request's `requested` field does not
  override this branch.
- `executive.py:902-911` explicitly maps an unknown reason to the default.
- `src/parcel_robot/runtime.py:4072-4079` sends the request but does not inspect
  the returned `InterruptDecision`; it then sets `_amendment_pending = True`.

Therefore an executive-only task can continue while a replacement plan is
being generated. C8 should be `CONFIRM`, not `REFUTE`. This requires one
focused product fix and regression before connected replanning is enabled. It
is a **build blocker**, not a new research topic or a reason for a broad voice
rewrite.

Required response: trace the receiver as well as the sender. If refuting this
finding, show the exact currently reachable code that maps `goal_amend` to
`suspend` or `cancel_now` and a focused test that observes the executive task
state, not merely the request payload.

### F3 · Localization can be confidently wrong, so the current NAV-CORE refuters are incomplete

RTP-1's hazard table calls localization health handling "H7-proven." H7
actually contains a severe false-healthy result:

- `research/20260823/localization-delegation-bench/RESULTS.md:95-107` records a
  6.3 m teleport in `city_block` that never became `DEGRADED` or `LOST` and
  ended with 8.66 m error.
- `RESULTS.md:109-127` shows the wrong match passed all gates, MAP error jumped
  from 0.005 m to 7.25 m, health stayed `HEALTHY`, and covariance remained
  millimetric while the local map absorbed the wrong place.
- `research/20260824/nav-core/DESIGN.md:26-41` covers drift, dropout,
  `DEGRADED`, moved obstacle and a missing goal, but not false-healthy place
  aliasing or independent relocalization.

NAV-CORE must add a bounded wrong-place/pickup/restart/power-cycle or
relocalization refuter. Motion must remain disarmed until localization is
independently revalidated after a discontinuity; a small covariance and
`HEALTHY` label alone are insufficient.

Required response: revise the evidence claim and state the minimum refuter and
fail-closed decision. Do not turn this into a broad SLAM benchmark. If retained
and simplified Parcel navigation both fail, allow one small, measured
Nav2-class interface/lifecycle spike, then choose retain, simplify or delegate.

### F4 · VOICE-GATE uses the wrong speaker path and misses decision-critical rows

`research/20260824/voice-gate/DESIGN.md:20-37` specifies robot TTS through a
"desk speaker." That does not exercise the intended acoustic echo-reference
path. The intended assembly is the XVF3800 DAC/JST amplifier driving the
CQRobot 4-ohm speaker. The latest real-array run in
`scrum/20260822/task_44/HWMIC_STATUS.md:18-21,121-125` captured from the array,
but `frames_out` and `bytes_out` were zero; only digital silence reached
playback. It did not prove live AEC through the physical speaker.

The corrected study must:

- use the actual XVF3800-to-CQRobot speaker path;
- include a live second person, not only recorded corpus voices;
- keep spoken STOP on an explicit always-local path that bypasses identity and
  wake gating;
- measure barge-in/cancel latency, quantitative AEC attenuation,
  intent/critical-slot accuracy, first-word loss, endpoint latency and cost;
- cover owner-recording replay, TV, robot self-speech and limited
  fan/footfall/wind conditions; and
- run the arms sequentially with early stop: owner-ID first, wake phrase only
  if it fails, and push-to-talk as the safe fallback.

Do not spend multiple hours on every arm after one policy has met the decision
bars. On-robot motor/gait acoustics remain box-day evidence.

### F5 · Follow is not a proven offline floor and may change the BOM

RTP-1 keeps Follow in M1 because it interprets the owner's offline floor as
"canned line + follow + avoid." The repository does not yet prove physical
owner continuity, pixel/range pairing, two-person crossing, occlusion,
reacquisition or obstacle avoidance. A failed appearance-only arm may require
UWB and therefore alter the payload/BOM.

The fastest safe M1 floor is **local STOP + HOLD + an honest canned
explanation**. Follow should remain disabled until an on-body identity and
occlusion commissioning study passes. If the owner explicitly requires Follow
in the first prototype, then owner tracking and any UWB decision are a
hardware-gated prototype blocker, not evidence already supplied by H3/H4.

The link-loss policy must distinguish failure classes:

- cloud/Internet loss may retain only previously commissioned local behaviors
  and must not invent or partially execute a compound plan;
- sensor, localizer or owner-track loss must command HOLD; and
- independent local STOP must remain available in every rung.

Required response: state one unambiguous offline floor and a separate Follow
enable gate. Do not use "link loss" as a single catch-all state.

### F6 · H9's declared direction and its v2 experiment still disagree

RTP-1 and `research/20260824/README.md` say the grammar plus 8B-normalizer
offline arms are dropped. Yet
`research/20260824/offline-first-cognition/DESIGN_v2_CONNECTED_PLANNER.md:8-26`
restores grammar-only as arm 1 and grammar-first plus hosted fallback as arm 3.

For the fastest connected prototype, the clean topology is:

```text
intent gate
  -> hosted structured-output PlanSketch
  -> local compile + fresh validation
  -> governed execution | typed refusal
```

The provider must not own dialogue state, memory, coordinates, velocities,
joints, gait, safety, replanning ticks or tool execution. Drop the grammar arm
unless Claude demonstrates that the implementation already exists at
essentially zero incremental cost and that measuring it changes the product
decision. CONNECTED-PLANNER should report schema/semantic validity, false
physical-plan rate, timeout/malformed behavior, p95 latency and cost, then
stop. It blocks connected compound execution only; it does not block the
gateway, sensor spine or one-step local behaviors.

Required response: remove the contradiction and name the exact early-stop
condition. Do not revive an AGX/26B comparison if the hosted path or honest
clarification already establishes the prototype topology.

### F7 · The independent adversarial intent set is useful closure, not planner proof

Commit `24378e6` adds an independently authored 43-item adversarial intent-gate
set and reports zero collisions with the frozen corpus. This addresses the
provenance/distribution-overlap part of RTP-1 C7 and should be credited.

It does **not** by itself prove that the current router, hosted planner,
compiler or validator produces zero false physical plans. Keep the corpus
immutable and separately report gate-only false opens and end-to-end false
physical plans when the bounded connected probe is run.

Required response: distinguish corpus construction validation from system
evaluation and state what, if anything, remains before the connected planner
can ship behind a flag.

### F8 · The milestone design remains stale and should be reconciled surgically

`research/20260823/MILESTONE1_DESIGN_FABLE.md` still marks H2/H9 pending,
retains an AGX-versus-grammar branch, and orders implementation largely by
subsystem rather than by the accepted physical dependency chain. This can
send implementation in two directions even if the new studies are correct.

After this review is accepted—but not within this review task—the milestone
document should receive a small reconciliation patch, not a rewrite. It should
name the frozen ODD, the actual online/offline policy, the corrected build
order, the C8 prerequisite, the false-healthy localization rule and which
items are commissioning rather than research.

The deployment plan must also preserve the existing process boundary rather
than assuming one Python environment: product Python 3.12 where supported;
vendor/ROS/native dependencies in their compatible process/environment;
typed IPC; systemd ownership; boot disarmed; credential isolation; restart
disarmed; and rollback. Final versions wait for the vendor's written JetPack
and SDK answers.

Required response: identify only the sections that need surgery and state
whether this reconciliation blocks M1-0 (it should not, unless an exact
authority contradiction is found).

### F9 · RTP-1's requested gate and hazard output was incomplete

C3 required a positive proof, refuter and stop/continue criterion for every
stage. RTP-1's abbreviated gate list does not distinctly close observation,
real LIO, Follow identity, transcript-to-task, continuous body behavior,
memory and initiative. C17 also asked for a residual-risk owner; its table has
no owner column.

Required response: provide one compact corrected table. Each row must name:
stage/hazard, positive witness, refuter/fault injection, fail state,
stop/continue bar, evidence tier, and residual-risk owner. It must clearly mark
what blocks first pulse, first translation and first autonomous mission. Do
not create a card per row.

### F10 · Research provenance and artifact hygiene still need a binding boundary

Task 1 authorized only `CLAUDE_REVIEW.md` and explicitly prohibited research
edits, new tasks, commits and pushes. The resulting sequence nevertheless
included `b2fe05f`, which bundled review/research/config/log changes, followed
by `edb78c0` research designs and `24378e6` corpus work. The additions are
useful, but their provenance exceeds the task's ownership boundary and makes
independent review harder.

The governing Task 1 prompt is also untracked while its response is tracked.
Artifact hygiene is only partial: active/raw logs outside the one ignored H2
location remain repository/index noise. Do not kill or alter another session's
processes from this review.

Required response: acknowledge the boundary mismatch; identify canonical
`DESIGN`, `RESULTS`, `VERDICT` and compact evidence artifacts; define where
large/raw/live logs go; and enforce a WIP limit of one physical-integration
lane plus one disjoint decision-blocking study. Batch corrections by milestone
boundary instead of creating one follow-up card per observation.

### F11 · Vendor answers and target mounting are acceptance gates, not desk research

The owner has already sent a written procurement inquiry covering the exact
Orin module/storage/JetPack/admin/SDK2 entitlement, installed Mid-360 mount and
harness, included battery/charger/controller, free USB/Ethernet/power,
sensor/audio access, US cellular/external 5G, mounting CAD/warranty, packing
list, lead time and return terms. Treat those answers as **pending until the
vendor replies in writing**; do not duplicate the email or treat a prepared
ticket as evidence that a reply exists.

On box day, execute commissioning packets rather than admit more desk studies:

1. **Compute/power/network/mount/sensors:** a 60-minute Orin co-residency soak;
   RAM/VRAM/temperature/throttling/power/battery/deadline/queue/restart data;
   clock map and extrinsics; actual Mid-360 LIO bags; feature-poor, restart and
   wrong-place cases; FOV/ground visibility/self-occlusion; center of gravity,
   vibration, cable retention and antennas; and 5G jitter/drop/reconnect/late
   result behavior.
2. **Authority/audio/identity:** independent remote stop and measured stopping
   envelope; mounted AEC/ego-noise/STOP; and, only if Follow stays in M1,
   two-person crossing, occlusion/reacquisition and obstacle avoidance.

Required response: classify each item as vendor blocker, build blocker or
box-day acceptance—not as another open-ended research project.

### F12 · Build and research can now proceed in a narrow parallel order

Recommended order:

```text
Lane A — build now
  M1-0 native sole-writer gateway/governor
    -> independent stop
    -> real stamped body/sensor observation
    -> real localization provider and health boundary
    -> supervised local Stop / HOLD / one known-place NavigateTo

Lane B — bounded decisions only
  revised NAV-CORE (architecture-freeze blocker)
  corrected VOICE-GATE (voice-policy/BOM blocker)
  small CONNECTED-PLANNER acceptance probe (blocks connected compounds only)

Box day
  vendor/port/power/mount/compute packet
  real LIO and wrong-place commissioning
  stop envelope and mounted acoustics
  optional Follow identity/UWB gate
```

NAV-CORE can affect which navigator sits behind the gateway but need not delay
building the gateway contract itself. The CONNECTED-PLANNER must not sit on
the physical critical path.

Required response: accept this parallelization or show the exact interface
decision that makes M1-0 unsafe to start.

### F13 · Do not conflate the conversational prototype with locomotion research

The current plan assumes Unitree Sport owns gait and balance. Custom gait,
direct joint control and locomotion RL require different vendor access,
control-rate, safety, simulation and warranty evidence and would materially
change the program.

Required response: keep those objectives deferred. If the owner re-declares
low-level locomotion research as a primary top-level objective, flag written
vendor low-level access/control-rate/warranty confirmation as a **procurement
decision blocker**, not a small extension of this prototype milestone.

## Minimum closure before architecture freeze

Only these items should remain in the pre-freeze decision budget:

1. Revised NAV-CORE, including false-healthy alias/relocalization behavior and
   one retain/simplify/delegate decision.
2. Corrected VOICE-GATE through the actual intended playback path, selecting
   owner-ID, wake phrase, push-to-talk or restricted listening.
3. One small CONNECTED-PLANNER acceptance probe, if credentials/provider access
   are available, without delaying M1-0.
4. The corrected C8 disposition and a named focused product regression.
5. A surgical milestone/deployment reconciliation plan after owner approval.

Research stop rule: admit another study only if its failure can change the
robot body, BOM, compute/process topology, safety/authority boundary, declared
ODD or first-prototype acceptance test. Each admitted study needs one decision,
pre-registered branches, a small evidence budget and an early-stop rule.

Explicitly defer:

- full H8 exploration/OCR and open-world search;
- outdoor, crowds, stairs, weather and generalized perception;
- governed continual memory/"recursive learning" beyond repairing existing
  correctness and revocation defects;
- AGX/26B comparisons and an offline compound grammar;
- trainable initiative or lifelikeness optimization; and
- custom gait, joint control or locomotion RL under the present product goal.

## Required review output

Create only `scrum/20260824/task_2/CLAUDE_RESPONSE.md` with:

- the exact reviewed commit and dirty-overlay boundary;
- one top-level disposition:
  `ACCEPT_AS_WRITTEN`, `ACCEPT_WITH_CORRECTIONS`, or `REJECT`;
- an F1-F13 table using `CONFIRM`, `CONFIRM_WITH_CORRECTION`, or `REFUTE`,
  with exact file/line or measurement evidence for every correction/refutation;
- a corrected list of the only remaining pre-freeze studies and their
  early-stop conditions;
- a dependency-correct parallel build order;
- separate `DESIGN_FREEZE_BLOCKER`, `BUILD_BLOCKER`, `VENDOR_BLOCKER`,
  `BOX_DAY_ACCEPTANCE`, and `DEFER` assignments;
- the corrected C8 receiver-path conclusion and false-healthy localization
  conclusion;
- an explicit offline/cloud-loss/sensor-loss/owner-loss policy;
- the compact stage/hazard table requested in F9, including residual-risk
  owners;
- the exact minimal sections needing later milestone reconciliation; and
- a non-empty `Does not prove` section.

Claude may recommend corrections, but must not implement them in this task.
Do not execute NAV-CORE, VOICE-GATE or CONNECTED-PLANNER; create or dispatch
cards; edit research criteria; change code/tests/config/docs; start or stop
processes; touch hardware; commit; or push.

## Ownership and collision boundary

**OWNS:** `scrum/20260824/task_2/CLAUDE_RESPONSE.md` only.

**MUST NOT TOUCH:** this `README.md`; `scrum/20260824/task_1/**`; `src/**`;
`tests/**`; `research/**`; `configs/**`; `scripts/**`; `tools/**`; `docs/**`;
other `scrum/**`; Git state; running services/processes; credentials; the owner
memory store; or physical hardware.

No test run is required. Focused read-only file inspection is sufficient.

## What this task does not prove

Accepting this review proves no target installation, vendor entitlement,
independent stop, stopping distance, payload stability, compute endurance,
network reliability, localization correctness, perception accuracy, owner
identity, Follow safety, acoustic quality, conversational quality, planner
quality, autonomous navigation success, outdoor fitness or readiness to move a
Unitree. It selects the shortest honest route to those physical proofs.
