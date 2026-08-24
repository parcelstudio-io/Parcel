# Research cross-review and prototype-readiness assessment · Codex · 2026-08-24

Fable is the independent research verifier named by this program. This file
is Codex's review packet for that verification; it does not claim to be a
Fable verdict. Every older hypothesis also carries a short in-place
`Codex cross-review for Fable` note so disagreements remain attached to the
evidence that caused them.

## Executive verdict

Parcel is **an advanced desktop research codebase with several sound safety
and portability primitives; it is not yet prototype-mountable software**.
The direction is now mostly correct—sole-writer gateway, explicit contracts,
local safety, event-gated cloud cognition—but the runnable product still has
no commissioned path from its runtime to a Go2, no body-neutral physical
observation spine, no target Orin artifact, no local spoken STOP, no real LIO
provider, and no mounted evidence.

The most useful conclusion from the research is not “put a larger model on
the dog.” It is:

> Keep the dog alive with continuous local sensing, state estimation,
> safety, drives, memory state and body intent. Call hosted intelligence only
> for an admitted conversational event or an explicitly escalated task.

This split meets the cost objective in EVENT-BUDGET, survives network loss,
and gives a future custom quadruped the same companion software above two
replaceable body boundaries: a motion gateway and a synchronized observation
snapshot.

## What “progress” means here

Percent-complete estimates would imply knowledge the repository does not
contain. The following scale is auditable:

- **0 — concept:** prose only;
- **1 — designed:** contract or preregistered design;
- **2 — harness:** repeatable desktop/simulation evidence;
- **3 — product path:** installed and exercised through the shipped runtime;
- **4 — target/HIL:** packaged on target compute or hardware-in-loop;
- **5 — mounted acceptance:** repeated physical trials meet the M1 bars.

| capability | level now | evidence and limiting fact |
|---|---:|---|
| hosted conversation | 3/5 | a product lane exists; pre-cloud engagement/identity gate, local STOP and a hard spend ceiling do not |
| continuous local “mind” | 2/5 | deterministic whisperer is wired, but research drives/noticing/body composer are harness-only and reaction decisions are not enacted |
| motion gateway/safety boundary | 1–2/5 | Claude is actively building a fake-Sport gateway; no Unitree driver, runtime client, service artifact or hung-vendor-call isolation yet |
| body intent/expression | 2/5 | H4 passed a fake-body 50 Hz harness; the Go2 adapter intentionally refuses and has no runtime caller |
| known-place navigation | 2/5 | substantial simulator stack; physical input remains `SimObservation`/truth/extras and NAV-CORE has no verdict yet |
| localization/SLAM | 2/5 | H7 validates a contract, but its covariance and one teleport are refuted; no real Mid-360/IMU LIO product path |
| owner tracking/Follow | 1–2/5 | algorithms and tests exist; tracker installation, synchronized range/pixels and target evidence do not |
| perception/noticing | 2/5 | useful detector replay point; novelty is refuted, RGB-only cannot map, runtime caller and target profile are absent |
| governed memory/learning | 1–2/5 | stores and explicit tools exist; automatic product path is unwired and has four verified correctness defects |
| self-initiative | 2/5 non-travel; 1/5 travel | deterministic mechanism works in harness; travel caused 1,222 contact episodes and must stay disabled |
| Unitree deployment | 0–1/5 | deploy tree says desktop/CI; no pinned aarch64 build, robot services, calibration manifest or commissioning record |
| future custom-body portability | 2/5 actuation; 1/5 whole stack | vendor SDK is isolated and fake adapter passes; nine high-level modules still consume simulator observations |

The first milestone is therefore plausible, but it is a sequence of physical
integration gates away—not a final research memo away. Indoor supervised M1
is realistic. Outdoor autonomy, generalized open-world perception, learned
locomotion and unrestricted proactive travel are later milestones.

## Cross-review of the research corpus

| study | evidence verdict | product verdict | disposition for M1 |
|---|---|---|---|
| H1 ambient ear/cost | economics confirmed; local answer ladder refuted | gating and rate-card enforcement unwired | retain hosted mini; finish pre-cloud gate and hard governor |
| H2 local cognition/GPU | LLM tick decisively refuted | monologue has no caller | close model zoo; deterministic tick, optional phrasing only |
| H3 drives/initiative | rate/quiet/preemption useful; physical-contact row refuted | research drive module unwired | speech/look/posture only; travel radius zero |
| H4 continuous body intent | contract confirmed in harness | no runtime caller; Go2 refuses | retain contract; commission only after gateway |
| H5 continual memory | overall refuted; mechanisms partial | four defects and no scheduler path | explicit remember/forget first; governed automatic path later |
| H6 noticing/perception | detector point partial; novelty refuted; target latency unresolved | no product caller; RGB-only no map writes | spatial/depth fusion then Orin/mounted profile |
| H7 localization delegation | contract useful; covariance and false-healthy teleport refuted | no caller; planar truth-shaped input | retain output contract; real LIO is a physical gate |
| H8 search-before-refuse | design only | none | defer full exploration; one thin probe after known navigation |
| H9 connected planner | design internally stale; no results | none | hosted PlanSketch fuzz only if compound motion is M1 |
| H10 platform/connectivity | provisional desk memo | vendor and box facts unverified | written confirmation + box-day; cloud/desk remain optional |
| NAV-CORE | active design/fixtures, no verdict at review time | does not change physical coupling | stop at retain/simplify decision |
| VOICE-GATE | important but v1/v2 tables conflict | no pre-cloud product gate | consolidate and run; push-to-talk is safe fallback |
| EVENT-BUDGET (new) | all six bars pass | hard governor not implemented | freeze local-clock/event-cloud policy |
| EMBODIMENT-KERNEL (new) | actuation partial; observation/deploy refuted | nine simulator-coupled modules | snapshot + gateway boundaries before Follow |

### Findings that are strong enough to freeze

1. **No LLM owns a periodic cognition tick.** H2 fails both judgment and
   latency. More 8B/26B comparisons will not change the systems decision.
2. **Hosted conversation is affordable when admitted.** H1's distribution
   plus EVENT-BUDGET gives $30.72/month nominal p95 and $76.95/month at 500
   turns/day under the frozen mix.
3. **Ambient admission dominates cost.** H1's TV-like rate produces
   $571.29/month in the same model. Identity applied after upload is too
   late for cost and privacy.
4. **Continuous safe intent is body-neutral.** H4 supports retaining
   `BodyIntentV1` and capability degradation. `HOLD` is a first-class intent.
5. **The localization contract is more valuable than the test localizer.**
   Keep MAP/ODOM/health/jump semantics; replace its physical provider.
6. **Pure gallery novelty should not ship.** It needs place, track and time
   context before another threshold sweep.
7. **Online model-weight recursion is not an M1 feature.** Governed event,
   fact and world-model learning is; weights change only through offline,
   evaluated, signed releases.
8. **Self-initiated translation is disabled by default.** H3 supports local
   non-translating initiative, not roaming on a body.

### Claims that must be narrowed

- “Generalized perception” becomes a layered perception system with bounded
  local safety categories, tracked people/objects and event-gated open-vocab
  escalation. The present evidence is not general perception.
- “Recursively learns” becomes governed, reversible updates to episodic,
  semantic, social and spatial memory. Recursive self-modification is neither
  evidenced nor safe for M1.
- “Motion planner continuously emits trajectories” becomes: a fixed-rate
  body/control lane continuously refreshes a setpoint or HOLD; the task/global
  planner replans on state changes and need. Continuous non-zero planning is
  wasteful and unsafe.
- “The desk GPU is part of the dog” is an M1 convenience, not an architecture
  rule. Loss of desk/cloud cannot remove STOP, state estimation, safety,
  gateway, event capture or the dog's minimal interaction state.
- “Localization never LOST while stationary” is not an acceptance bar.
  Stationary loss can be honest. The bar is no false motion/rearm/arrival on
  uncertain, stale or discontinuous localization.

## Assessment of Claude's current implementation direction

The gateway-first decision is correct. It is the highest-leverage way to keep
Unitree-specific credentials and SDK behavior below the companion stack. The
current live `gateway/` work already has useful epoch, lease, TTL, governor,
audit and Unix-server concepts. It is still a reference implementation, not
the mount boundary:

- it is untracked and outside the package tree;
- no Unitree Sport driver or production runtime client exists;
- no robot service unit or pinned Orin artifact installs it;
- the product `Go2Backend` and Sport body adapter still refuse motion;
- synchronous `stop_move()`/`state()` calls occur while the gateway core lock
  is held, so a hung vendor call can freeze the server/watchdog unless the
  driver bounds I/O or is independently contained;
- fake exact-zero evidence does not prove the real robot stopped.

The current implementation order needs one material correction. Follow
cannot precede the observation spine, physical localization and synchronized
owner evidence when Follow itself imports `SimObservation` and its tracker
has no product installation. The dependency-correct order is gateway bench →
snapshot/deployment spine → local STOP → real driver/client → LIO → supervised
known-point navigation → owner tracking/Follow. Transactional goal amendment
can proceed independently, but it does not make the code mountable.

## Research still worth doing before architecture freeze

Limit remaining desk research to tests that choose a design branch:

1. **Pre-cloud voice topology.** Compare push-to-talk, buffered local
   VAD+speaker/engagement gate→hosted audio, and local ASR→hosted text. Require
   owner committed-turn recall >=95%, local STOP recall >=99%, no hosted bytes
   for TV/self-TTS/non-owner input, <=1 false hosted opening/24 h, no
   self-transcribed motion and p95 projected spend below the internal cap.
   Failure selects push-to-talk M1.
2. **Gateway/control isolation fault injection.** Hang `stop_move`, state and
   socket/ledger I/O; kill/restart every service; duplicate/reorder epochs.
   Require no body/control gap over 100 ms, stop within one supervisory tick,
   bounded counted queues, restart-disarmed and no stale command acceptance.
3. **NAV-CORE early stop.** Decide retain/simplify only. It cannot substitute
   for physical point-goal evidence.
4. **Hosted plan/authority fuzz—conditional.** Only if compound physical
   instructions are in M1. Require no explicit-negation, stale, duplicate or
   system-initiated travel commits; malformed/timeouts become typed refusal.
5. **Governed memory product path—conditional on the learning promise.**
   Run real runtime turns through consent, revoke, restart and prompt
   retrieval. Failure selects explicit remember/forget only.
6. **Spatial noticing comparison—conditional on visual initiative.** Compare
   gallery score with map-cell+label+track+time novelty. Stop unless AUC >=.8
   and false noticing <=1/min at the freshness bar.

Do not spend more pre-design time on local model-size comparisons, another
pure-gallery threshold sweep, full autonomous exploration, outdoor autonomy,
custom gait/RL, or trying to prove target thermals on the desktop.

## Unknowns that only the purchased hardware can answer

- exact Go2 payload interfaces, SDK entitlement, firmware/JetPack, mounts,
  warranty and power rails;
- real `Move`/`StopMove`/`Euler` signs, envelopes, rates, balance effects,
  watchdog behavior and stopping distance;
- Mid-360 + IMU time alignment, extrinsics, LIO health and relocalization;
- D455 occlusion, depth quality and motion blur from the mounted pose;
- XVF3800 AEC, fan/gait/wind/TV behavior, replay resistance, barge-in and
  local STOP latency through air;
- Orin NX 16 GB co-residency, memory, thermal throttling and 4–8 h stability;
- USB/Ethernet/power brownout behavior and 5G loss/reconnect;
- human comfort around posture, gaze, sound, following distance and
  non-translating initiative.

These require preregistered box-day packets, not further prose. The detailed
target architecture and promotion order are in
[`PORTABLE_LIVING_DOG_HLD.md`](PORTABLE_LIVING_DOG_HLD.md).
