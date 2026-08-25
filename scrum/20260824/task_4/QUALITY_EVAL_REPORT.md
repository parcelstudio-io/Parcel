# QEV-1 quality evaluation and prototype-mount readiness report

**Local evaluation date:** 2026-08-24, America/New_York  
**UTC artifact date:** 2026-08-25  
**Reviewed commit:** `2ce919a1d49ba55224ae7c6cd66f3a99255a8ca5`  
**Final verification base:** `d2988421dd2a4d28cf57438001ad58a6eaa40cb0` plus the recorded acoustic hardening overlay
**Scratch root:** `/tmp/parcel-quality-20260824.VYhnnR`  
**Physical hardware used:** none

## Executive verdict

| decision | verdict | reason |
|---|---|---|
| Desktop/bench development | **GREEN with red quality gates** | The code and focused seams execute repeatably, but capability quality is below release bars. |
| Stationary, supervised Stage-0 mount | **CONDITIONAL / AMBER** | Reasonable only for zero-motion capture with Sport disabled, independent remote stop, secure support and a signed runbook. It has not been executed. |
| Motion seam on a real robot | **NO-GO / RED** | No product-runtime composition, vendor port, independent physical STOP evidence, Orin run or measured stopping envelope. |
| Supervised point-goal motion | **NO-GO / RED** | False-arrival and no-route refuters fail; no commissioned physical LIO/observation path exists. |
| Follow | **NO-GO / RED** | Simulator acceptance and yield gates are red; no real owner observation/identity path exists. |
| Conversation release | **NO-GO / RED** | The live model is parse-reliable but capability-grounding and personal-conversation quality are poor; four virtual acoustic gates fail and mounted audio is untested. |

The important result is not that every subsystem is bad. The gateway/client
seam is strong bench work, deterministic task-boundary mechanics are strong,
and the narrow 60-seed room-scale navigation experiment is excellent. The
release fails because the product path outside those narrow islands still has
specific falsifiers: false arrival after localization discontinuity,
indefinite no-route behavior, unsupported conversational actions, poor Follow
behavior, and no physical observation/actuation evidence.

## What “robot-ready validation” means here

Robot-ready validation requires the same product path that will run on the
robot, under the real process/clock/sensor/actuator boundaries, to pass both
positive tasks and adversarial refuters. It is not equivalent to unit-test
coverage, a simulator success rate, an installable gateway, or a model that
returns valid JSON.

For this prototype it means, in dependency order:

1. runtime → Unix gateway → sole vendor writer, with boot/restart/reconnect
   disarmed and an independent STOP;
2. real physical snapshots with known clock map, calibration and extrinsics,
   never simulator truth;
3. zero-motion Stage-0 capture plus dropout/restart/thermal/power evidence;
4. one stand/tether axis with measured signs, units, clamp, HOLD, remote STOP
   and stopping envelope;
5. real LIO bag refuters and supervised known-point navigation with zero false
   arrivals/contacts; and only then
6. real owner identity/occlusion/reacquisition before Follow.

The repository's own HLD defines these as Gates 2–6. This evaluation does not
collapse those gates into desktop evidence.

## Review of Claude's completed work

Claude's `DEPLOYABLE-MOTION-SEAM` materially improves the architecture:

- a CPython 3.10 gateway distribution and console entry point exist;
- `MotionGatewayClientV1` exposes a bounded typed surface and no raw-message
  escape hatch;
- reconnect and restart remain disarmed;
- hung `state()` and `stop_move()` calls are isolated from the gateway's
  supervisory responsiveness; and
- service/CLI parity and fake-Sport lifecycle behavior have focused evidence.

Fresh independent verification of `tests/test_motion_seam.py` produced
**58 passed, 4 skipped** in 6.22 s. The skipped rows require the clean
installed-artifact environment recorded by Claude; Claude's accepted record
contains three consecutive installed-artifact runs and the independent Fable
verification.

The ceiling is decisive:

- `RobotRuntime` is still typed around `SimulatorBackend`, and its ordinary
  builder requires explicit injection for any physical controller;
- the runtime snapshot still originates from `CarrierObservationSource`;
- no product code imports/composes the new motion client;
- `--sport vendor` refuses because no `UnitreeSportPort` exists;
- the Orin unit set remains mostly unrun skeletons;
- the physical observation source always raises
  `PhysicalSourceNotCommissioned`; and
- no physical stopping distance or independent-stop result exists.

Therefore the Claude work earns **bench seam accepted**, not robot-ready.

## Conversation evaluation

### Implemented in this task

1. Added a deterministic scorer for the 25 captured realtime-conversation
   threads. It enforces scenario/fixture parity, declared tool planes, JSON
   object arguments and nonempty output; reports risk flags for long replies,
   unsupported motion/perception/arrival/memory claims, tool narration and
   repeated refusals; and validates complete semantic-review provenance.
2. Added a complete unblinded AI semantic review artifact covering every
   authored expectation. It is explicitly nonhuman, uncalibrated and
   report-only.
3. Corrected the personal-conversation report's judge provenance: its local
   heuristic is no longer mislabeled as model-judge evidence.
4. Made the acoustic runner automation-safe: unavailable remains exit 2; a
   completed red/invalid run exits 1; only green gates plus clean teardown exit
   0.
5. Repaired the virtual acoustic graph. Recorders disable autolinking, own a
   unique node, resolve exact global monitor/input port IDs, create and verify
   an explicit link, use cancellable partial-read accumulation with a bounded
   first-frame deadline, and serialize terminate/kill/reap. Teardown now
   verifies both graph nodes and child processes.

### Fresh results

| suite | result | interpretation |
|---|---|---|
| Conversation-focused pytest campaign | **318 passed, 1 skipped, 2 deselected** | Strong deterministic mechanics; the skip/deselections retain their declared environment/tier limits. |
| Final post-change focused rerun | **180 passed** | New scorer, provenance and explicit acoustic routing/process tests green. |
| Offline brain task corpus | **15/15 passed**, including **7/7 fail-closed** | Task compilation/executive boundaries work; physical navigation count is zero. |
| Scripted duplex | **7/7 hard gates passed**, TTFT p50 ≈ **35.7 ms** | Software clock/queue regression only; no real microphone, model speech or mounted speaker. |
| Realtime captured-corpus machine contract | **25/25 threads**, 174 turns, **0 hard failures**, 66 review flags | Artifacts are structurally replayable; this does not establish good dialogue. |
| Realtime semantic review | **6 PASS / 8 MIXED / 11 FAIL** threads; 43/76 expectations pass | Conversation quality is red. Review is a single unblinded AI pass, not owner preference. |
| Live pinned local model, 10-case quality set | **10/10 parsed; 2/10 machine-pass** | Transport/schema reliability is good; structured capability safety is **0.20**. |
| Live model latency | TTFT median **375.4 ms**; HTTP median **1510.7 ms** | Useful desktop inference timing, not spoken end-to-end latency. |
| Live personal conversation | **3/13 turns pass**; 1/8 families pass, 1 recency-blocked, 6 fail | Memory/context/persona/adaptation quality is not release-ready. |
| Virtual acoustic PipeWire smoke | 80 frames / 76,800 bytes, 27,915 nonzero samples; monitor 117,364 bytes, 33,577 nonzero; zero orphans | The repaired routing and lifecycle work on this host. |
| Frozen virtual acoustic suite | **25/25 cases executed; 5/9 gates pass; 4/9 fail; clean teardown** | Valid red Tier-1 measurement, not mounted audio/AEC evidence. |

The live model's dominant structured failure is concrete: it proposes action
names such as `comfort_bow`, `happy_wiggle`, `attentive_nod`,
`observing_head_tilt` and `chuckle` even though the runtime context exposes
only `play_bow` and `paw_wave`. It also acts on hypothetical affect. The
captured realtime corpus adds premature navigation/tool proposals, unsupported
monitoring/perception claims, durable-memory confabulation, repeated refusals
and capture concatenation artifacts.

The acoustic red gates are:

| gate | measured | limit |
|---|---:|---:|
| endpointing ep50 | **0.812 s** | ≤ 0.500 s |
| barge-in acoustic-stop p50 | **1.080 s** | ≤ 0.520 s |
| duplex acoustic-ack p50 | **0.850 s** | ≤ 0.700 s |
| prosody apex within ±150 ms | **0.5714** | ≥ 0.80 |

Passing acoustic rows include zero endpoint cutoffs, ep90 0.8756 s,
barge-in detection p50 0.0641 s, flush max 0.000052 s and zero false barges on
the two frozen noise cases. Because both endpoints are null sinks and the
voices are synthesized, none of these numbers measure a room, XVF3800 AEC,
real speaker/mic placement, self-speech, fan/gait/wind noise or a human voice.

## Navigation evaluation

### Test and integration gates

| campaign | fresh result | finding |
|---|---|---|
| Fast navigation-focused tests | **345 passed, 5 skipped, 3 xfailed** | Broad mechanics green; three strict search/grounding cases retain a known 1.0223 m inflation/geometry mismatch. |
| Slow navigation/metamorphic/integrity | **9 passed, 49 deselected, 2 xfailed** | Two known rigid-transform region-goal metamorphic violations remain (≈3.0196 m mismatch). |
| Slow Follow acceptance | **1 passed, 4 failed** | Only 7/9 Follow cases pass; shipped jerk regresses and predictive TTC evidence is absent. |
| Voice → runtime → MuJoCo E2E | **15 passed, 2 failed, 1 xfailed** | `sit next to lamppost` is semantically unreachable; `go to lamppost` regresses arrival verification; dynamic pedestrian yield remains xfailed. |

### Room-scale NAV-ACCEPT

The current shipped arm is dramatically better than its legacy control on the
frozen narrow corpus:

| arm | arrivals | object-class arrival | false arrivals | contacts | median time | median path/optimal |
|---|---:|---:|---:|---:|---:|---:|
| shipped | **60/60** | **1.00** | **0** | **0** | 14.55 s | 0.97475 |
| shipped + margin flag | **60/60** | **1.00** | **0** | **0** | 14.55 s | 0.97475 |
| legacy control | **29/60** | 0.4167 | 0 | 0 | 11.20 s among successes | 0.81458 |

The two shipped arms are numerically identical because this corpus offered no
actual relocalization-margin decisions. Do not over-credit the flag.

The adversarial rows reverse the promotion decision:

- Scan dropout and degraded-pose episodes correctly make zero translation
  during their evidence gaps.
- Every shipped moved-obstacle seed remains `running` until the 900-tick
  limit, 4.26–4.50 m from truth, with `silent_stall_step_limit`.
- Every shipped kidnapping seed declares a false arrival roughly 5.21–5.27 m
  from the true goal.
- A modeled ambiguity/discontinuity latch blocks those false arrivals with
  `arming_latched`, proving a viable remedy, but that modeled gated arm is not
  the currently shipped product path.

### Instruction navigation, Follow and external proxies

| suite | fresh result | release meaning |
|---|---|---|
| NAV_INSTRUCT v4 minival | SR **0.24** (6/25), SPL 0.1933, 1 false arrival | Red. |
| NAV_INSTRUCT v4 full | SR **0.256** (32/125), SPL **0.1908**, frozen-rule SR 0.136, 0 contacts, **6 false arrivals** | Red; zero contacts do not offset false completion. |
| Full instruction failure mix | 53 planning, 24 termination, 7 grounding, 3 search, 6 false-arrival, 32 success/no-failure; 22 authority disagreements | Planning and completion authority both need work. |
| Current Follow bench | Follow **7/9**, navigation 2/2, zero contacts | Narrow scripted/oracle-owner evidence only; two Follow failures. |
| Follow yield extension | **STOP-AND-REPORT**, 7 misses | Oncoming group produces 1 hard collision/contact and −0.468 m pedestrian surface clearance; wide-group band regresses 1.0→0.524. |
| BARN PR native proxy | **1/10 success**, metric 0.04466, 0 collisions | Nine worlds travel 0 m and stop `navigation_no_progress`; collision zero is vacuous for those worlds. |
| Generic five-task proxy | SR **0.54**, collision rate **0.46**, human-collision rate **0.06** over 50 episodes | Coarse baseline only, but clearly red. BARN-like and exploration tasks collide in every episode. |
| Habitat public adapter contract | **30/30 one-step contracts pass** | IPC/action grammar only; no Habitat scene, episode navigation or score. |
| Habitat full doctor | **BLOCKED** | Missing licensed Pablo scene, Docker, NVIDIA container toolkit and pinned archived image. |

The BARN PR zero-collision result is not positive safety evidence: nine of ten
episodes never move, ending after 20 s with 1,800 aggregate
`grid_recover_scan` steps. Controller p95 is 166.2 ms in the eight-worker run,
above the simulator's 100 ms step interval; parallel CPU contention makes it a
warning, not a real-time or physical claim.

## Physical code-path audit

The source independently agrees with the empirical `NO-GO`:

- `RobotRuntime.__init__` accepts a `SimulatorBackend`; normal construction
  rejects a non-simulator controller unless one is explicitly injected.
- The current snapshot source wraps `self.backend.observe`, while the
  physical observation adapter always refuses commissioning.
- `LiveGo2Sources` can read physical DDS state/LiDAR without blocking, but its
  motion methods all refuse and it emits `OwnerTrack(visible=False)` because
  there is no owner sensor.
- The scan-match localizer explicitly has no IMU, loop closure, pose graph or
  place descriptors. Its installer has no product map-template source by
  default.
- Orin services are documented as skeletons that have not run on target.
- The desktop MuJoCo base advances by kinematic `qpos` placement and semantic
  perception is generated from scene truth.

This makes a stationary observation-only profile technically plausible after
commissioning. It does not make a motion profile plausible today.

## Simulator feasibility

| option | feasibility | best use | hard ceiling |
|---|---|---|---|
| Existing deterministic city + MuJoCo | **High, usable now** | False-arrival/no-route/dropout/kidnap refuters, planner regressions, crowds and fault injection | Kinematic base, synthetic semantics; no gait/contact/real LIO/stopping proof. |
| BARN native/proxy | **High for planner work** | Clutter, inflation, recovery and generalization | Planar Jackal-style proxy; not robot embodiment or official leaderboard evidence. Current baseline is red. |
| Real Stage-0 bag replay | **High value; medium feasibility after capture** | Exact clocks/extrinsics, snapshot assembly, LIO health, dropouts and replayable regression | Requires robot/sensors and valid bags first; replay cannot prove actuation. |
| Official Unitree MuJoCo | **Medium** | Vendor SDK lifecycle, command axes/signs/rates and articulated interface tests | Needs adapter and separate environment; simulated stops cannot set physical envelope. |
| MetaUrban | **Medium later** | Procedural social-navigation, crossing and occlusion diversity | Current adapter raises `NotImplementedError`; Python 3.9/IPC integration required. |
| Habitat 2020 | **Low near-term** | Standard contract and later indoor generalization if assets/runtime arrive | Current run is adapter-only; licensed scene/evaluator stack is blocked and embodiment differs. |
| Isaac/URBAN-SIM | **Medium-low near-term** | Longer-term articulated training/domain randomization | High integration cost before the product seams are closed. |

Simulation is therefore very feasible as a capability-improvement engine. It
can cheaply generate failure distributions, mutations and regression packs,
and the current failures give it excellent targets. It cannot satisfy HLD
Gates 3–6: real hardware identity, clocks/extrinsics, AEC, LIO, independent
stop, stopping distance, owner identity, thermal/power/mount integrity and
human acceptance remain physical evidence.

Recommended simulator sequence:

1. gateway/runtime restart, hung-I/O, stale-feedback and lease-loss faults;
2. current-city + BARN R3/R4b/no-progress/false-arrival campaigns;
3. real Stage-0 bags through the exact production observation/localization
   path;
4. identity/crossing/occlusion social-navigation campaigns; and
5. articulated Unitree simulation after the real vendor adapter contract is
   known.

## Coverage, unavailable tiers and early stops

“All quality evals” was treated as every release-relevant conversation and
navigation lane that can produce honest evidence on this host: deterministic
tests, frozen corpora, current local-model inference, virtual audio, product
E2E simulation, room-scale acceptance/refuters, instruction navigation,
Follow/yield, BARN PR, generic external proxies and Habitat contracts.

The following were not silently treated as passes:

- no robot/Orin/Unitree SDK was present, so all physical gates are
  **UNMEASURED**;
- no human owner panel was run, so warmth/preference claims remain
  **UNMEASURED**;
- mounted through-air/AEC testing is **UNMEASURED**;
- official Habitat navigation is **BLOCKED**, with named assets/runtime
  blockers; and
- the much larger BARN public expansion was stopped after the pinned PR set
  produced nine zero-progress failures. Running more worlds cannot promote a
  controller that already fails the early admission/liveness gate; it belongs
  after the systemic issue is fixed.

## Repository close verification

The final focused conversation/acoustic regression selection passed
**180/180** tests. Targeted Ruff checks passed with no findings, the generated
codebase index reached a fixed point, and `git diff --check` was clean.

The integrator's commit gate was then run once and passed every hard gate. Its
default suite reported **10,506 passed, 22 skipped and 5 xfailed** in the
parallel lane, plus **12 passed and 1 skipped** in the serial lane. The gate's
Ruff debt ratchet reported four existing baseline findings, seven allowed and
zero new. Most importantly, the same successful gate explicitly reported the
stopping envelope as **UNMEASURED** because gateway period, physical
command-to-standstill time, scan age and localization jump are not yet
measured. Repository green therefore confirms desktop/bench integrity; it
does not promote physical motion.

## Overall recommendation

Do not mount this software for motion. Preserve Claude's gateway seam, close
the shipped product-path falsifiers, constrain conversation to installed
capabilities, keep Follow disabled, and use simulation to make those failures
repeatable. Then perform a separately authorized stationary Stage-0 mount and
bag capture. A tethered pulse should be considered only after the real runtime
gateway path, independent STOP, physical observation provenance and measured
stopping envelope are all green.

The actionable task and acceptance criteria are in `README.md` under
`PRE-MOUNT-CLOSE-1`.

## Evidence limitations

- The campaign began from the exact reviewed Claude commit. During the
  campaign, the conversation/task evaluation layer was integrated as
  `d2988421dd2a4d28cf57438001ad58a6eaa40cb0`; the final acoustic lifecycle
  hardening remains a working-tree overlay on that base. Neither layer is
  presented as physical-product evidence or as part of Claude's original
  motion-seam change.
- The local-model run uses one pinned model/configuration and one pass through
  small frozen sets. It does not estimate population-level conversational
  quality.
- The semantic corpus review is one unblinded AI review; it is useful defect
  triage and not a human preference score.
- Simulator metrics use modeled sensing, scripted actors or scene truth to
  varying degrees. Cross-suite numbers are not directly comparable.
- No result in this document proves mount integrity, electrical safety,
  physical stopping, real localization, real owner identity, room acoustics,
  long-duration thermals or unattended operation.
