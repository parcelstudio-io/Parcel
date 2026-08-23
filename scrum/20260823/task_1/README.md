# Task 1 · ARCH-1 — boundary-first codebase decomposition

**Date:** 2026-08-23

**Status:** REVIEW-ONLY · NOT DISPATCHED

**Author:** Codex (repository audit and review packet)

**Required reviewer:** Fable

**Possible executors after approval:** risk-tiered—scripts/lower-cost model for
mechanical work, one capable implementer for boundary work, and an Opus-class
executor plus independent Fable review only where safety/authority complexity
justifies them

## Owner request

List the systems, classes, and functions that should be decomposed, and define
the unit, integration, and quality-evaluation plan Fable should review. Record
that work as today's task. Include the full concern register—architecture,
robotics, physical evidence, testing, language, deployment, Claude spend,
indexing, follow-up-card efficiency, and process risks—so Claude can review and
disposition it later rather than silently turning each note into a new card.
Also decompose the code Claude newly included in Wave 3, including its product
symbols, tests, configuration, packaging, CI, and Orin deployment artifacts.

## Decision requested from Fable

Return exactly one top-level disposition in `FABLE_VERDICT.md`:

1. `ACCEPT_DECOMPOSITION_SEQUENCE`
2. `ACCEPT_WITH_REQUIRED_CHANGES`
3. `REJECT`

This task designs the work. It does **not** authorize a refactor, behavior
change, safety change, dependency migration, process launch, gate run, commit,
or push.

## Why this is a separate review card

The repository contains strong safety contracts and broad synthetic tests, but
its main orchestration has outgrown safe cognitive limits:

- `RobotRuntime`: about 14,942 class lines, 345 methods, and a 1,333-line
  constructor;
- `DirectiveNavigator`: about 5,764 class lines and 116 methods;
- `RealtimeLane`: about 3,146 class lines and 81 methods;
- one 10 Hz runtime thread currently coordinates work spanning safety,
  navigation, perception, mission logic, conversation, and audio;
- physical data still crosses a simulator-oriented observation abstraction;
- configuration, test, CI, capture, and process evidence have also grown into
  independent monoliths.

Smaller files alone would not fix those problems. ARCH-1 therefore asks Fable
to review boundaries, authority, dependency direction, test oracles, rollout,
and rollback before implementation cards are cut.

## Snapshot and collision boundary

- Original committed reference: `0ce1c5f8bb4a`.
- Original moving-tree audit: 2026-08-23 15:39 EDT over the then-dirty Wave 3
  overlay.
- Claude's exact implementation landing is now `c1b84055bd57`; the subsequent
  `be86b7861322` commit changes only `CODEBASE_INDEX.md`.
- At the post-landing freeze, `HEAD == origin/main == be86b7861322` and the
  worktree was clean. `CLAUDE_WAVE3_DECOMPOSITION.md` regenerates the exact
  `0ce1c5f..c1b8405` delta rather than treating dirty-tree estimates as final.
- The landing's own evidence ceiling is desktop/synthetic/replay. A clean
  commit and commit-tier gate record are not target or physical proof.

**OWNS:** `scrum/20260823/task_1/**` only.

**MUST NOT TOUCH:** `scrum/20260822/**`, `src/**`, `tests/**`, `scripts/**`,
`tools/**`, `configs/**`, `deploy/**`, `.github/**`, `pyproject.toml`,
`requirements*.txt`, the index, the Git index, or any running process.

No implementation card may start until all remaining conditions hold:

1. Fable has narrowly reviewed the exact Wave 3 delta and resolved the
   scan-age, hard-skip, SDK/venv, resolved-profile, blocking-I/O, and lifecycle
   findings in `CLAUDE_WAVE3_DECOMPOSITION.md`.
2. Fable has written an accepted verdict for the revised ARCH-1 design.
3. The owner has approved the exact tranche, integrator, constituent cards,
   risk tier/model/reviewer fanout, spend/compute/documentation/diff budget,
   prototype outcome, and stop/continue gate.

Fable accepts or rejects architecture; only the owner authorizes spend and
dispatch. `CONFIRM_OPEN` or provisional is not closure. The initial verdict
records X08/X16 closed, X11 revised, and an X12 co-location decision; its other
required changes plus this later delta supplement remain review inputs. Other
physical blockers prohibit the affected physical milestone, while only an
explicitly scoped, dependency-safe tranche may work toward closing them.

## Packet

| File | Purpose |
|---|---|
| `CURRENT_STRUCTURE_AUDIT.md` | Measured system, class, and function inventory; action vs preserve decisions |
| `SYMBOL_CENSUS.md` | Threshold-complete list: 94 product classes/140 functions plus 9 operational-tooling classes/59 functions |
| `CLAUDE_WAVE3_DECOMPOSITION.md` | Exact `0ce1c5f..c1b8405` Claude delta: all changed declaration groups, boundaries, test splits, blockers, and refuters |
| `DESIGN.md` | Target boundaries, dependency direction, staged extraction DAG, follow-on cards, and rollback |
| `TEST_AND_EVAL_PLAN.md` | Unit, contract, integration, replay, SIL, HIL, physical, and quality-eval gates |
| `CONCERNS_REGISTER.md` | Required concern-by-concern risk, evidence, consequence, response, and batching review |
| `PREREGISTRATION.md` | Claims and thresholds pinned before Fable review or implementation |
| `FABLE_REVIEW_BRIEF.md` | Required review lenses, questions, and verdict format |
| `FABLE_VERDICT.md` | External initial verdict: `ACCEPT_WITH_REQUIRED_CHANGES` for the original eight-file packet; preserve unchanged and supplement narrowly for the later Claude-delta addendum |

## Scope definition: what “all” means

The inventory is threshold-complete rather than line-count-driven:

- every product subsystem is assigned a disposition;
- every new or definition-body-modified Wave 3 product/tooling declaration is
  accounted for in grouped exhaustive rows in `CLAUDE_WAVE3_DECOMPOSITION.md`;
- every product and operational-tooling class with at least 300 lines or 10
  direct methods is triaged by name;
- every product and operational-tooling function with at least 100 lines or an
  approximate decision count of 20 is assigned to an extraction family or a
  preserve-and-test family;
- individual test/eval functions are deliberately classified by product seam
  under D23 instead of being treated as refactor targets because of length;
- critical code may be marked `PRESERVE` even when large: decomposition is not
  automatically safer;
- smaller functions remain in their owning component unless coupling, state
  ownership, or timing evidence gives a concrete reason to extract them.

The census is a decision aid, not an instruction to split every long symbol.

## Non-negotiable architecture rules

1. Preserve one physical command writer and one final software positive-command
   authority. The independently operated physical E-stop is separate, remains
   dominant, and is never removed by this rule.
2. Learned/model output stays an untrusted proposal and never mints authority.
3. Keep the 10 Hz Python supervisory proposal/pre-gate path free of model,
   audio, HTTP, UI, persistence, and unbounded queue work. A 20–50 Hz native
   boundary owns final local positive-command admission after cutover.
4. Freshness is based on host monotonic receipt time while device timestamps,
   frames, sequence, epoch, covariance, origin, and calibration remain visible.
5. Unknown, stale, future, malformed, wrong-frame, or simulator evidence in a
   physical profile cannot become positive evidence.
6. Latched software/gateway STOP remains bit-exact all-axis zero after every
   shaper; recoverable HOLD follows an explicit input-class × axis table;
   restart remains disarmed and no extraction adds auto-resume. The independent
   operator stop has its own out-of-band failure-domain proof.
7. Simulation, replay, and physical adapters may share contracts but not
   authority claims.
8. Existing public imports, CLI entrypoints, config defaults, endpoint status
   and JSON bodies, wire DTOs, event ordering, and gate output remain compatible
   unless a separate behavior-change card is approved.
9. A decomposition must reduce state ownership or dependency coupling. Moving
   the same god object into a differently named file does not count.
10. Every card must be independently reversible.

## Proposed board

ARCH-1 is an epic design card. Fable reviews/accepts the architecture; only
after the owner authorizes a tranche is implementation cut into smaller cards
with disjoint OWNS.

The table below is the proposal under review, not an accepted schedule.
The initial Fable verdict revises the early native rail and renders X11/X12/
X16 dispositions, while retaining deployment, evidence, composition, and
physical blockers. The later Claude-delta supplement must address its exact
new findings; Claude must not dispatch the table merely because it appears
here or because an architecture verdict exists.

Numbers express prerequisites, not a single global queue. Rows 6A and 6B are
independent branches after their named contracts; ROS/localization is a hard
prerequisite for map-relative/custom navigation, not for audio. Physical-rail
blockers retain priority and the owner still caps WIP at two.

| Order | Proposed card | Outcome | Dispatch rule |
|---:|---|---|---|
| 0 | `ARCH-F0-MIN` characterization and contract freeze | Accepted critical traces, API/lock graph, bridge authority/protocol | Minimal slice; behavior-free |
| 0P | native gateway/final-governor bench | No-credential host/CI native process against fake Sport | Parallel after protocol freeze; no target/robot claim or writer credential |
| 1 | `ARCH-IG` + `ARCH-TEST` | Thin imports, forbidden edges, hermetic bounded launcher | Bounded foundation; must not delay gateway bench |
| 2 | `ARCH-OBS-MIN` neutral navigation evidence | Multi-rate stamped navigation/world snapshots; sim/replay/live read adapters | Before product credential or autonomous motion |
| 3 | `ARCH-CONFIG` + `ARCH-PKG` bounded slices | Typed physical composition and clean target artifacts | Only minimum required for target rail first |
| 4 | `ARCH-DEPLOY` | Process/artifact matrix, systemd topology, identities, restart-disarmed, rollback | First-class owner before B16/B30 |
| 5 | B25 + Orin gateway rebench, then B16/B30 | Repeat the same native artifact on Orin; independent stop, commissioning credential, then product-path HIL | Owner/hardware gates; inspected progression |
| 6A | `ARCH-ROS` + `ARCH-LOCALIZATION` decisions | Retire/adapt legacy ROS path; provider/TF/covariance/Nav2 authority choice | Before map-relative/custom navigation decomposition; independent of audio branch |
| 6B | `ARCH-AUDIO` + `ARCH-CAMERA` | Bounded ingress/state/transport boundaries | After relevant evidence contracts; must not delay physical rail |
| 6C | `ARCH-REALTIME` | Session reducer, barge-in, accounting, declarative tool registry | Risk-tiered; after audio facade |
| 7 | `ARCH-NAV-*` | Preserve semantic/social differentiators; decompose only retained custom stack | After 6A provider decision; one bounded leaf per card |
| 8 | `ARCH-MISSION` + `ARCH-RUNTIME` | Proposal services and thin compatibility/lifecycle facade | After retained leaf services exist |
| 9 | `ARCH-LOOP` | Python supervisory observe→join→arbitrate→pre-gate proposal path | No final vendor authority; critical review |
| 10 | `ARCH-CONTROL` decision | Keep, retire, or decompose Python `ControlManager` after native cutover | Default preserve unless live risk justifies extraction |
| P | `ARCH-CAPTURE-*`, `ARCH-CI`, `ARCH-SIM`, `ARCH-UI`, `ARCH-PROVIDERS` | Parallel supporting decomposition | Must not delay physical blockers |

Maximum work in progress after approval: two implementation cards. Cards that
share runtime, configuration, CI runner, or test-hook semantics are sequential.

## Definition of done for this review card

- [x] Current structure measured without product changes.
- [x] Candidate systems, classes, and high-risk functions inventoried.
- [x] Claude's exact landed Wave 3 code, operational assets, and 8,863-line new
  hardware-card test suite decomposed into extract/preserve/target-proof seams.
- [x] Preserve boundaries identified so line count does not drive unsafe churn.
- [x] Target dependency direction and staged extraction order proposed.
- [x] Unit, integration, quality, replay, target, and physical verification
  planned with explicit `does_not_prove` statements.
- [x] Architecture, robotics, evidence, language, deployment, cost, indexing,
  follow-up-card, CI, and process concerns recorded with required dispositions.
- [x] Fable questions and verdict vocabulary preregistered.
- [ ] Fable has accounted for every concern ID in `CONCERNS_REGISTER.md` using
  compact family/range rows plus explicit exceptions; no omitted ID is closed.
- [x] Fable has written an initial verdict for the original eight-file packet.
- [ ] Fable has supplemented that verdict for
  `CLAUDE_WAVE3_DECOMPOSITION.md`, its newly recorded false-green/config/
  lifecycle findings, and questions 21–26.
- [ ] Any required changes have been incorporated and re-reviewed.

## What this task does not prove

This is a static architecture review whose original measurements were made on
a moving tree and whose Claude-specific addendum is now frozen to the exact
landing. It proves no behavior, timing, target installation, sensor accuracy,
stopping distance, conversational quality, or physical safety. It does not
independently reproduce the landing's commit-tier result or establish that all
proposed target names are final. Those facts belong to the preregistered
implementation and hardware gates after Fable accepts the design.
