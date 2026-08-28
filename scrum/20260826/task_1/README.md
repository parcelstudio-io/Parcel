# Task 1 · DOG-GEN-1 — generalized companion learning and Go2 readiness

**Date:** 2026-08-26 (America/New_York)

**Status:** RESEARCH COMPLETE · `SIM-CONTRACT-1` READY TO BUILD · PHYSICAL
MOTION `NO-GO`

**Author:** Sol, after independent review of Claude's committed motion seam and
the current conversation/navigation stack

## Owner request

Methodically assess the prototype for a conversational autonomous companion on
a Unitree Go2 EDU+ with likely AGX Orin 64 GB, camera, Mid-series LiDAR,
speaker/microphone, and Starlink. Improve the continuing-friend prompt; review
Claude's work and mount readiness; run conversation/navigation quality evals;
test simulator-generalization and long-term research-data hypotheses; and turn
the findings into an immediate capability-development program within the
stated hosted API budgets.

## Decision

The current software is **not ready for stand, translation, autonomous
navigation, Follow, search, greeting, or stairs on the physical robot**. A
separately authorized, stationary, mechanically secured Stage-0 capture is the
only plausible near-term mount activity, with Sport disabled, an independent
remote stop, and a signed two-person runbook. It has not been executed.

Simulation is the right primary development environment now. The next build
must retain fake Sport for gateway lifecycle and the existing official Go2
MJCF assets, then bridge the native Unitree MuJoCo low-level SDK2/DDS simulator
surface through a simulated `SportPort` or explicit high-level controller,
without adding another writer.

## Review of Claude's work

Claude's committed `DEPLOYABLE-MOTION-SEAM` remains accepted at
**desktop/bench** tier. It gives Parcel an installable gateway, typed Unix
client, restart/reconnect-disarmed behavior, bounded hung-state/stop handling,
and service/CLI parity. The next dependency is clear: no normal runtime
composition imports that client; a legacy `UnitreeSportController`/
`SportClient` transport exists, but no gateway-compatible `UnitreeSportPort`
composes it and gateway vendor mode refuses. An observation-only Go2 backend
exists but is uncommissioned and untested: NIC/extrinsics are unmeasured, pose
is odometry rather than MAP/LIO, owner perception is absent, and its motion-
producing methods refuse (stop/emergency-stop are safe no-ops). No Orin or
physical stop evidence exists.

The shared Claude artifact URL returned `Page not found` and supplied no
reviewable content. No artifact-specific mount claim is made.

## Evidence that sets the priority

| surface | fresh result |
|---|---:|
| NAV_INSTRUCT | 25/125, SR 0.20, SPL 0.1348, one false arrival |
| Unseen semantic scenes | mean SR 0.253, 16 false arrivals across 75 episodes |
| Walk-with-me | 5/10 headless |
| Follow/yield | 7/9 Follow; yield extension has one simulated human contact |
| Personal conversation | 3/13 turns; 2/8 families pass |
| Current planner | 3/5 full plan and 3/5 PlanSketch |
| Realtime `si-companion-v5` | v4 companion relationship retained; DI-v2 untrusted-data boundary; deterministic render/digest/freeze/package parity; no model behavior run |
| Local structured prompt | 10/10 parse, 10/10 structured safety, 7/10 cases in one stochastic same-corpus run; all ten actions null, so no positive embodiment witness |
| Effective affect mapping | only 1/9 personality action names available |
| Aliased completion refuter | 3/3 false arrivals survive a five-tick rule in a deterministic desktop aliased-kidnap test |
| Independent completion follow-up | 120/120 alias false arrivals blocked, but only 116/120 nominal true arrivals versus a 118/120 gate; overall `REFUTED` |
| Research data-plane probe | 14,532 events replayed exactly; local mechanism only |

Repository close verification is recorded in the fresh-results report. The
one-time full commit gate was red on two deterministic repository-maintenance
checks; both exact defects were fixed afterward and passed 2/2 targeted tests,
with 111/111 affected tests passing (four additional tests skipped). The full
gate was not rerun under its once-per-close policy, so no post-fix full-gate
green claim is made.

A subsequent adversarial close removed two safety/integration defects before
this task was considered finished: a model-authored `explicit_command` trigger
can no longer bypass the tagged social-skill allowlist, and developer-note
history/owner/sensor blocks are versioned, quoted, and delimited as untrusted
data. The direct HeadlessCity simulator clock is now explicitly mapped at the
synchronous ingress instead of appearing permanently stale to the shadow
observer. Prompt/action/freeze/parity tests passed 265; the direct clock node
passed 1/1; and the final cross-surface focused suite passed 269.

## Recommended `BUILD_NEXT`: `SIM-CONTRACT-1`

Build one bounded, default-disarmed Go2 simulation/product contract tranche.
It has five deliverables in dependency order.

### A. One capability truth

Implement `CapabilityManifestV1` from the effective profile/adapters and make
it the source for prompt context, action schemas, personality closure, logs,
UI, and eval manifests. Include commissioning state and trajectory/schema
digests. Do not treat an enum member as physically commissioned.

Acceptance:

- 100% personality-to-manifest closure or explicit boot-time drop;
- zero action names in prompts/evals that are absent from the effective
  manifest;
- one manifest digest in every proposed/admitted/rejected action record; and
- missing/unknown/malformed capability state fails closed.

### B. Same-path simulation

Compose the normal product runtime through `MotionGatewayClientV1` and the
gateway against fake Sport, startup disarmed. Retain the existing official Go2
MJCF assets, then integrate the native `unitree_mujoco` simulator/control
boundary in an isolated pinned environment at its low-level SDK2/DDS surface
through a simulated `SportPort` or explicit high-level-to-low-level controller
bridge, using a nonphysical domain/interface and preserving the same
sole-writer surface.

Acceptance:

- no simulator backend or model has a second path to velocities/joints;
- boot, gateway/runtime death, reconnect, lease expiry, stale feedback, DDS
  loss, process restart, and clock skew leave authority disarmed;
- axes, units, signs, clamp, command age/rate, HOLD, STOP, and state/scan loss
  have deterministic seeded witnesses; and
- all evidence is labeled desktop/articulated simulation, never physical.

### C. Typed progress and independent completion

Implement `PlannerOutcomeV1` with `progress`, `reason`, `since`, `retryable`,
`evidence_age`, bounded recovery choices, and per-skill retry/progress/total
budgets. Preregister H2b before product integration: keep loss of translation/
completion authority latched after a localization discontinuity, then require
separate place-identity evidence, a verified new pose epoch with residual-
consistent reset, and conservative target-relative terminal geometry. The
current identity-witness candidate is a research lead, not an admitted policy.

Acceptance:

- a new untouched dynamic holdout covers doors reopening, moving people,
  alternate paths, temporary/transient blockage, `no_path`, and
  `goal_blocked`;
- zero silent timeouts and no nominal/transient-block regression;
- zero false arrivals in the frozen discontinuity/completion holdout; and
- one false arrival or authority bypass is an automatic red gate.

### D. Conversation-to-body state

Implement `DialogueStateV1`, `EmbodimentEnvelopeV1`, action start/terminal
receipts, and a typed `CompanionMission` graph. Give the model reply/proposal
authority only; local identity, consent, privacy, evidence, body state,
capability, and safety decide admission. Proactive speech, approach, Follow,
search, and stairs remain default off.

Acceptance:

- raw multi-turn held-out cases cover correction, interruption, negation,
  quotation, stale receipts, “again,” reference resolution, memory update/
  revocation, owner/non-owner/TV/self-TTS, and busy-body deferral;
- zero unavailable/unauthorized action, false completion, unsupported
  perception, or unsupported memory assertion on the high-risk frozen set;
- exact action/intent at least 95% in every high-risk family; and
- no inferred emotion or relationship cue produces base travel.

### E. Immutable simulator-learning loop

Create a versioned scenario/split registry and an isolated local research
summary spool. Every candidate binds code, config, model, calibration,
dataset, and evaluator digests. Failure-mined train/dev cases never enter the
frozen holdout. No candidate self-promotes.

Acceptance:

- deterministic replay from an empty workspace reproduces counts, digests,
  metrics, and gate verdicts; human approval/signature remains a separately
  recorded release authority;
- owner memory and research spool have separate paths/APIs and a test proves
  the exporter cannot open the owner database;
- research upload is default off; before any pilot, demonstrate client
  AES-256-GCM, managed KMS wrapping, TLS/IAM, restore, rotation/cryptoshred,
  resumable checksummed upload, and link interruption. Revoke one consent and
  verify deletion from spool, object store, catalog/cache, and one derived
  dataset while retaining only a non-content receipt; and
- promotion requires frozen safety/navigation/conversation suites, human
  review where social quality matters, signature, rollback, and shadow mode.

## OWNS

- a leaf capability-manifest package and its focused tests;
- normal runtime-to-gateway composition behind default-disarmed configuration;
- an isolated native Unitree MuJoCo SDK2/DDS environment and adapter, reusing
  the tracked official Go2 MJCF assets;
- typed planner outcome/completion/dialogue/embodiment/mission contracts;
- scenario and split registry, minimal failure refuters, and local-only
  research exporter/spool pilot; and
- dated research/task evidence.

## MUST NOT TOUCH OR ENABLE

- physical vendor motion, robot Sport activation, stand/floor pulses, Follow,
  stairs, approach/search, or proactive speech;
- local E-stop, TTL watchdog, speed caps, reactive gate, or sole-writer
  invariants except to consume their existing typed interfaces;
- owner SQLite as a research store, raw upload by default, or direct
  research-to-control/model hot swap;
- tracked frozen ledgers/corpora after results are visible; or
- the owner's live simulator ports/socket.

## Required evaluation matrix

The tranche cannot close on unit tests alone. Freeze and report:

- gateway/DDS fault and command-contract campaign;
- nominal + dynamic-blocker + aliased-localization minimal refuters;
- seen/unseen semantic navigation by scene/instruction/goal/disturbance;
- Follow owner/distractor/crossing/occlusion/loss/reacquisition;
- social clearance/collision/intimate-space/formation/jerk;
- multi-turn conversation, receipt, memory, capability, initiative, and
  acoustic timeline cases;
- exact-device AGX latency/RAM/VRAM/power/thermal/deadline bakeoff when the
  device exists; and
- reproducibility, lineage, privacy negative controls, corruption, retention,
  and byte-cap replay. The initial policy under test is 90-day summaries; up
  to one-year pseudonymous feedback; separately approved redacted text/exact
  GNSS at most 30 days; raw audio seven days extendable to at most 30; named-
  protocol image/video/MCAP 7–30 days; and no biometric-embedding export by
  default. Expiry/revocation must reach spool, object, catalog, cache, derived
  data, and backups. Seeded regex/key tests are not de-identification proof.

## Later physical ladder

After `SIM-CONTRACT-1` closes: stationary Stage-0 MCAP → real-bag replay →
tethered single-axis commissioning → controlled flat known-point missions →
owner-identity Follow trials → slope/single-step/stair fixtures. Each rung has
its own stop conditions; simulator performance never skips a rung.

## Budget contract

- Realtime API: $210 owner turns, $45 admitted proactive/embodied turns, $30
  frozen/shadow evaluation, $15 reserve per month.
- Hosted text: $60 deliberate planning/research, $20 offline labels/evals, $20
  reserve per month.
- Local safety/perception/navigation/control never spend API tokens.
- Propose 50 MiB/day for P0 consent/tombstone control, P1 feedback/manifests,
  and P2 summaries, with a separate 5 GB/month defense-in-depth ceiling. These
  caps are not currently enforced; P3 raw stays off on metered links and at
  least 1 MiB/day outside the normal cap is reserved for P0 control.
- Enforce actual provider-token and network-byte ledgers; forecast overruns
  disable hosted proactivity and queue deep work before degrading ordinary
  owner-initiated conversation.

## Deliverables from this task

- [Research synthesis](../../../research/20260826/FINAL_REPORT.md)
- [Mount-readiness decision](../../../research/20260826/MOUNT_READINESS.md)
- [Fresh quality results](../../../research/20260826/system-readiness/RESULTS.md)
- [Conversational embodiment study](../../../research/20260826/conversational-embodiment/VERDICT.md)
- [Navigation generalization study](../../../research/20260826/navigation-generalization/VERDICT.md)
- [Independent completion follow-up](../../../research/20260826/independent-completion/VERDICT.md)
- [Dynamic social-progress study](../../../research/20260826/dynamic-social-progress/VERDICT.md)
- [Research data-plane study](../../../research/20260826/research-data-plane/VERDICT.md)

`CODEBASE_INDEX.md` intentionally indexes `git ls-files` only. Today’s new
untracked research, prompt snapshots, social-progress modules, and tests will
not appear there until an integrator stages/commits them and regenerates the
index; no staging or commit was performed by this task.
