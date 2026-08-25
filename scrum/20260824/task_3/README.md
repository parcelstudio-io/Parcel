# Task 3 · RRV-1 — post-Lane-A robot-readiness promotion plan

**Date:** 2026-08-24

**Status:** REVIEW_REQUESTED · NOT DISPATCHED

**Author:** Codex (independent post-implementation review)

**Required reviewer:** Claude

## Owner request

Review Claude's completed Lane A work against its actual evidence ceilings and
turn the remaining robot-facing gaps into one dependency-correct promotion
plan. The result must select exactly one bounded software tranche that can be
built now, before the robot or vendor SDK is available, and must place every
later hardware activity behind the existing physical gates.

The goal is the shortest honest route to the supervised M1 robot described by
`research/20260824/PORTABLE_LIVING_DOG_HLD.md`: one private flat room, low
speed, an operator present with the independent remote, and no claim of
unattended, outdoor, public-space or generalized autonomy.

This is a **review and promotion-planning task only**. It authorizes no product
implementation, new experiment, hardware access, service/process control,
credential use, physical motion, commit or push.

## Exact review boundary

Immediately before this card was created:

- `main`, `origin/main` and `origin/HEAD` were all at full commit
  `61f97af16e41b85e3e5086ef391fd2ec3637e65c`
  (`chore: Lane A close — recorded STOPs as strict xfails; gate green`);
- the tracked tree was clean; and
- no task-3 overlay existed.

This `README.md` is the only overlay introduced by the card author. Claude must
record the exact commit and dirty overlay actually reviewed. Concurrent work
may advance the tree; do not overwrite, normalize, stage or attribute another
session's changes to this task.

Primary evidence:

- `scrum/20260824/task_2/LANE_A_CLOSE.md`;
- `scrum/20260824/task_2/IMPLEMENTATION_PLAN.md`;
- `scrum/20260824/task_2/M1_0_STATUS.md`;
- `scrum/20260824/task_2/A2_STATUS.md` through `A9_STATUS.md` and their
  corresponding `*_VERDICT_FABLE.md` files;
- `research/20260824/PORTABLE_LIVING_DOG_HLD.md` §§12–14;
- `gateway/`, `src/parcel_robot/bridge/`,
  `src/parcel_robot/observation/`, `deploy/orin/services/`, and their tests;
- `docs/BOX_DAY.md`; and
- the exact product paths cited below.

## Independent review of Claude's work

Claude made substantial, well-verified software progress after the earlier
robot-readiness recommendation was written. That earlier sequence—"finish A6,
then A7–A9"—is now obsolete:

- `LANE_A_CLOSE.md` records A1–A9 accepted and pushed;
- the integrator close gate passed with 10,429 tests passed, 18 skipped and
  five strict xfails, with the four newly recorded STOPs attributed and given
  explicit revisit triggers; and
- A6, A7, A8 and A9 each have an executor status and an independent Fable
  verdict.

The result is a credible software architecture and a strong desktop safety
baseline. It is not yet a deployable or physically validated robot stack. The
accepted records themselves make that distinction:

| card | accepted contribution | present evidence ceiling / remaining robot handoff |
|---|---|---|
| A1 / M1-0 | sole-writer gateway semantics, TTL, epoch, watchdog, isolated `Move` and fake-Sport soak | bench only; `gateway/process.py --sport vendor` still refuses, no production runtime client reaches it, and `state()` / `stop_move()` remain synchronous vendor calls under the core lock without hung-call fault seeds; no Orin or physical stop evidence |
| A2 | one clearance authority and the M1 `SIMPLIFY` point-goal topology | commissioned shipped profile must still score at least 0.80 on the frozen corpus before the first physical point-goal; four strict STOPs revisit at that gate |
| A3 | discontinuity latch, whole-map margin contract, jump journal and one-shot re-arm transaction | no real LIO, real scan, pickup, restart or wrong-place commissioning evidence |
| A4 | `NavigationSnapshotV2`, stamped evidence, adapters and service ownership skeletons | `PhysicalObservationSource.poll()` deliberately raises `PhysicalSourceNotCommissioned`; native wire/client, clock/extrinsics manifest, real LIO and runnable Orin services remain absent |
| A5 | transactional goal amendment with HOLD-first rollback and command-stream proof | desktop product-path proof only; no real actuator stream exercised |
| A6 | always-local spoken STOP routed to the panel's own latch; replay-tier tail latency met | no mounted/through-air or physical-stop proof; recall remains below 0.99 and the false-trigger bar remains unfalsified, not proven |
| A7 | pre-upload ear gate and hard hosted-call governor | fixture/desktop evidence; deployment-channel identity, mounted AEC and live provider reconciliation remain commissioning work |
| A8 | Follow composition, synchronization/ambiguity vetoes and a measured UWB defer | Follow ships disabled; no real owner, camera, crossing, occlusion, reacquisition or physical avoidance gate has passed |
| A9 | four memory fixes, body-intent lane and structural zero-translation initiative lease | initiative remains off, body adapters and scheduler trigger remain unwired, and soak/human nuisance evidence is absent; nothing moved a real body |

Two status documents are stale as queue displays: `IMPLEMENTATION_PLAN.md`
still labels A1 "running" and A2 "next" even though the close record says the
whole lane is accepted. Treat the close record and per-card verdicts as the
delivery truth. The new plan may note this drift but must not turn bookkeeping
cleanup into the next physical tranche.

## Recommendation to review

### Select exactly one `BUILD_NEXT`: `DEPLOYABLE-MOTION-SEAM`

The next owner-authorized implementation tranche should close the missing
installable process/client seam **against fake Sport only**:

1. Package `parcel-gateway` as a clean CPython 3.10 installable artifact with
   a real console entry point matching `parcel-gateway.service`.
2. Add the production Unix `MotionGatewayClient` contract required by HLD Gate
   1. Its public surface is bounded to connect/hello, acquire, time-bounded
   command refresh, explicit stop, state/stop-report observation, close and
   reconnect-disarmed behavior. It exposes no raw-packet or malformed-message
   bench API.
3. Prove the installed client → Unix `SOCK_SEQPACKET` → installed gateway →
   fake-Sport path from a clean environment, including service-style process
   start, kill and restart.
4. Close the remaining vendor-I/O containment gap against injectable fake
   faults: a hung `state()` or `stop_move()` may never hold the gateway core
   lock, freeze the watchdog, or make a bounded independent stop depend on the
   hung call returning. Preserve the existing isolated `Move` behavior.
5. Keep every reconnect and gateway restart disarmed. No readiness event,
   successful handshake or healthy state may automatically reacquire motion
   authority.
6. Produce an implementation-ready card with exact `OWNS`, `MUST NOT TOUCH`,
   test roster, rollback and acceptance evidence. Do not execute that card in
   this review.

This tranche is deliberately narrower than "wire the robot." It closes the
production IPC and packaging hole without pretending an unavailable Unitree
SDK, robot, Orin image or calibration exists. It creates the stable seam the
real `UnitreeSportPort` and later runtime composition can join at HLD Gate 4.

If Claude rejects `DEPLOYABLE-MOTION-SEAM`, it must name one **smaller**
software-now tranche, show the exact repository dependency that blocks this
one, and preserve the same outcome: an installed, production-shaped,
restart-disarmed path to fake Sport. A preference for broader cleanup is not a
refutation.

## Required acceptance contract for `BUILD_NEXT`

The proposed future implementation card is acceptable only if its definition
of done includes all of these:

1. **Clean install.** A clean CPython 3.10 environment installs the built
   artifact without importing from the repository checkout; `parcel-gateway`
   exists and starts against fake Sport.
2. **Service/CLI parity.** The installed executable, supported arguments,
   environment files and `deploy/orin/services/parcel-gateway.service` agree.
   A skeleton pointing at a nonexistent executable cannot pass.
3. **Production client boundary.** The client owns no vendor SDK object and
   offers no raw-message test escape hatch. Runtime/domain callers see typed
   acquire/command/stop/state results only.
4. **End-to-end authority proof.** Client death, gateway death/restart, TTL
   expiry, stale feedback, old epoch, sequence regression and reconnect each
   end with fake Sport at exact zero, no lease held and the next motion command
   refused until a new explicit arm transaction.
5. **Restart-disarmed.** Gateway restart produces a new boot epoch and never
   resumes or automatically reacquires the previous command source.
6. **Fault containment.** Slow client, audit-full and blocked/raising `move`,
   `state` and `stop_move` seams cannot block the watchdog/stop path. The test
   corpus gains explicit hung-state and hung-stop seeds with anti-vacuity
   witnesses that the fake call really is still blocked while the supervisor
   remains responsive. Existing A1 invariants remain green without weaker
   limits or re-pins.
7. **Repeatability.** The focused installed-artifact/conformance suite passes
   three consecutive guarded runs. The designated integrator runs the commit
   tier once at close; executors do not.
8. **Honest evidence label.** Status and verdict say `desktop/bench`, not
   `on-Orin`, `target-run`, `on-robot`, `physical stop` or `robot-ready`.
9. **Repository discipline.** Ruff adds no fingerprint; no `-n auto`; the
   codebase index is regenerated if tracked files move or are added; the
   owner's live stack and memory store remain untouched.

The plan must name seeded reds or mutations proving that the installed test
would fail if reconnect auto-rearmed, the boot epoch were reused, the client
bypassed the Unix gateway, or hung `state()` / `stop_move()` could wedge the
watchdog.

## Later promotion sequence—not part of `BUILD_NEXT`

The output must crosswalk later work without bundling it into the first
tranche:

| promotion | required positive witness | refuter / fail state | stop/continue bar |
|---|---|---|---|
| Gate 2 deployment/observation | pinned Orin artifacts; runnable supervised services; physical snapshot with real clock/calibration provenance | service kill/restart, stale/reordered/mixed-epoch input, simulation origin in physical profile | any truth fallback, unknown calibration or auto-rearm stops promotion |
| Gate 3 observe-only box day | hardware identity, mounts, time maps/extrinsics, body/LiDAR/camera/audio capture and zero `Move` Stage 0 | reboot, dropout, disk/network/power pressure; independent remote with head-board link unavailable | missing vendor facts, failed independent stop or any unexplained motion stops the day |
| Gate 4 controlled pulse | real `UnitreeSportPort`; one reviewed axis on stand/tether; signs/units/rates/clamps/HOLD measured | mid-pulse remote stop, client/gateway kill, lease loss and restart | measured envelope must pass; no floor translation from a pulse result |
| Gate 5 localization/navigation | real LIO bags and health/latch/re-arm behavior; shipped nav profile ≥0.80; at least ten leashed known-point missions | feature-poor, restart, pickup/wrong-place, moved obstacle, removed goal and mid-leg dropout | zero contacts and false arrivals; any false-healthy motion or false arrival stops promotion |
| Gate 6 Follow | commissioned real owner identity and synchronized perception; one- and two-person trials | crossing, identity swap, occlusion/loss and reacquisition | any identity swap keeps Follow disabled; ambiguity/loss must HOLD |
| M1 close | mounted audio, 4–8 h Orin fault/thermal soak and ten supervised 60-minute sessions | WAN/desk/runtime loss, disk full, thermal/queue pressure, self-TTS/TV/fan/gait/wind | every HLD §14 acceptance row passes inside the narrow supervised ODD |

No later row may be declared complete from the earlier row's evidence.

## Blocker and owner-input classification

The response must separate:

- **SOFTWARE_NOW:** only the selected `BUILD_NEXT` tranche and its focused
  desktop verification;
- **VENDOR_BLOCKER:** written JetPack/SDK2 entitlement, ports, power, mount,
  harness, firmware and support answers;
- **BOX_DAY_ACCEPTANCE:** physical inventory, firewall/network facts, clock
  map/extrinsics, real sensor bags, mounted acoustics, stop envelope, thermal/
  power/mount soak and Follow identity trials;
- **OWNER_ACTION:** PO-1 independent E-stop decision, signed box-day runbook,
  robot delivery/availability and owner plus second-person scheduling; and
- **DEFER:** connected compound planner unless explicitly made binding for M1,
  semantic navigation ladder, self-initiated translation, UWB unless its
  measured reopen bar is crossed, custom gait/joint control, outdoor/public
  operation and generalized autonomy.

No owner input is required to review this card or to build the fake-Sport
`DEPLOYABLE-MOTION-SEAM`. Vendor and box-day inputs gate only their later
stages. The optional CONNECTED-PLANNER decision must not block this tranche.

The HLD's `≤ 0.3 m/s` is an ODD ceiling, while the currently declared
restricted gateway regime is 0.25 m/s. That is compatible. Ask the owner about
a new 0.3 m/s commissioned regime only if 0.3 m/s performance is a required
capability; do not manufacture a contradiction or silently widen the existing
regime.

## Stop conditions for this review

Return `HOLD` rather than recommend a tranche that:

- depends on the unavailable robot, Unitree SDK/credentials or unwritten
  vendor answers;
- treats the service skeletons as deployable artifacts;
- auto-arms or auto-reacquires on startup, readiness, reconnect or restart;
- adds a second vendor writer or places a vendor handle in `RobotRuntime`;
- bypasses the gateway from a runtime/domain caller;
- leaves `state()` or `stop_move()` as an unbounded call capable of holding
  the gateway core lock or watchdog;
- skips observe-only Gate 3 to claim Gate 4 readiness;
- bundles physical observation, LIO, Follow, mounted audio, memory, initiative
  or hardware motion into `BUILD_NEXT`;
- weakens an accepted A1–A9 safety invariant or silently re-pins a failing
  gate; or
- claims any physical, target or robot-readiness result from fake-Sport.

## Required review output

Create only `scrum/20260824/task_3/ROBOT_READY_PLAN.md` containing:

1. the exact reviewed commit and dirty-overlay boundary;
2. one top-level disposition:
   `ACCEPT_BUILD_NEXT`, `ACCEPT_WITH_CORRECTIONS`, or `HOLD`;
3. an A1–A9 evidence-ceiling/remaining-handoff matrix, correcting this task
   with exact file/line or measurement evidence where necessary;
4. exactly one `BUILD_NEXT` tranche, preferably
   `DEPLOYABLE-MOTION-SEAM`, with objective, prerequisites, `OWNS`,
   `MUST NOT TOUCH`, work items, tests, seeded reds, rollback and definition
   of done;
5. a Gate 2→Gate 6/M1 crosswalk with positive witness, refuter, fail state,
   stop/continue bar, evidence tier and accountable human residual-risk owner;
6. separate `SOFTWARE_NOW`, `VENDOR_BLOCKER`, `BOX_DAY_ACCEPTANCE`,
   `OWNER_ACTION` and `DEFER` lists;
7. the exact runbook/status drift that must be corrected before an operator
   follows it, without performing that correction here;
8. the 0.25 m/s versus 0.3 m/s treatment stated explicitly;
9. a non-empty risk/rollback section; and
10. a non-empty `Does not prove` section.

Claude may correct or replace the recommendation, but must not implement it,
create or dispatch child cards, edit accepted A-card records, rewrite the HLD
or box-day runbook, run broad tests, start or stop processes, touch hardware,
commit or push.

## Ownership and collision boundary

**OWNS:** `scrum/20260824/task_3/ROBOT_READY_PLAN.md` only.

**MUST NOT TOUCH:** this `README.md`; `scrum/20260824/task_1/**`;
`scrum/20260824/task_2/**`; `src/**`; `gateway/**`; `tests/**`; `research/**`;
`configs/**`; `scripts/**`; `tools/**`; `deploy/**`; `docs/**`; other
`scrum/**`; Git state; running services/processes; credentials; the owner's
memory store; or physical hardware.

No test run is required. Focused read-only inspection is sufficient.

## What this task does not prove

Accepting this plan proves no clean target install, Orin compatibility, vendor
entitlement, Unitree SDK behavior, independent stop, stopping distance,
payload stability, clock/extrinsics accuracy, real localization, perception,
owner identity, Follow safety, mounted acoustic performance, thermal
endurance, autonomous mission success, outdoor fitness or readiness to move a
Unitree. It selects and bounds the next software seam that must exist before
those proofs can begin.
