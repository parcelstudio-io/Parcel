# Sprint 2026-08-07 task 2 — navigation and instruction-following hardening

**Crown synthesis:** [`RESEARCH_THESIS.md`](RESEARCH_THESIS.md) is the
independent-study program thesis — diagnosis, layer-by-layer improvement plan,
RL NO-GO/reuse decision, phased roadmap with exit criteria, and source index
over `research/*`. Prefer it when a single authoritative research read is
needed; the drafts below remain supporting detail.

**Status:** research and audit complete; implementation cards are queued, not
started. **Safety status:** this stack is not cleared for unsupervised physical
operation. **Snapshot:** `main` at `4f6342d`, inspected with a dirty and moving
working tree (162 changed/untracked paths at the audit snapshot). Persisted
evaluation claims below are identified by their own run artifact. The targeted
pytest result in the source audit was observed on that moving tree but was not
persisted with a dirty-patch digest, so it is diagnostic evidence rather than a
reproducible frozen baseline.

This is the next task for 2026-08-07. It turns the owner's request for
state-of-the-art city/indoor navigation and natural instruction following into
an ordered implementation and evaluation program. The detailed audit,
research, RL decision, and gates are in:

- [RESEARCH_THESIS.md](RESEARCH_THESIS.md) — **crown independent-study thesis**
- [CURRENT_STACK_AUDIT.md](CURRENT_STACK_AUDIT.md)
- [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)
- [MODEL_AND_RL_DECISION.md](MODEL_AND_RL_DECISION.md)
- [EVALUATION_AND_ROADMAP.md](EVALUATION_AND_ROADMAP.md)
- [SOURCE_LEDGER.md](SOURCE_LEDGER.md)
- [RESEARCH_WORKSTREAM_APPENDIX.md](RESEARCH_WORKSTREAM_APPENDIX.md)
- [OPUS_RESEARCH_WAVE.md](OPUS_RESEARCH_WAVE.md) — wave status (COMPLETE)
- [designs/COMPARISON.md](designs/COMPARISON.md) — concise D1/D3/D2
  composition decision
- [designs/deep/DEEP_COMPARISON.md](designs/deep/DEEP_COMPARISON.md) — deep
  implementable design review and falsifiers

## Decision

Do **not** replace Parcel with one end-to-end navigation model and do **not**
train a custom end-to-end RL policy now. The best development direction is a
hierarchy:

1. Unitree Sport retains gait and balance control.
2. A deterministic, independently monitored metric-geometry safety lane from
   commissioned camera/depth and LiDAR sources owns the final stop decision.
3. One common metric planner/controller executes navigation and owner-follow
   formation goals. A Nav2 sidecar is the first serious challenger to the
   current Python grid controller.
4. Parcel's typed executive owns task lifecycle, resources, interruption,
   recovery, and success verification.
5. Conversation, instruction reasoning, open-vocabulary perception, and
   learned navigation produce bounded proposals. They never emit authoritative
   Unitree commands.

The first learned experiments should reuse downloadable models. The following
list is grouped by role, not experiment order:

- **MiniCPM-RobotTrack** for owner-follow waypoint proposals on Go2;
- **InternVLA-N1** for desktop instruction grounding/navigation research;
- **CE-Nav** and **X-NavDP**, only after their respective checkpoint,
  dependency, and asset terms clear, for bounded Go2/RGB-D local trajectory
  proposals;
- **CityWalker** for an urban traversability/waypoint prior;
- **VLFM-style** frontier scoring, with VAMOS/OmniNav as research comparators,
  for unseen semantic targets.

Each begins in offline replay, then shadow mode. Missing or unresolved artifact
terms block acquisition/execution. Restrictive or noncommercial terms block
product selection and physical motion; isolated offline research additionally
requires explicit legal approval. Stale outputs, frame ambiguity, a failed
deadline, or a safety veto always disqualify the runtime proposal.
Qwen-RobotNav is a valuable architecture reference, but its official repository
says there is currently no plan to release its weights.

## Why model work is not Phase 0

The measured NAV_INSTRUCT baseline and candidate both achieved only **1/25
(4%) success**. More importantly, the audit found defects that make model
comparisons uninterpretable or unsafe:

- an ordinary proximity/TTC stop can retain residual shaped velocity;
- missing/malformed LiDAR can fall back to translating open-loop;
- production pose still comes from simulator truth rather than localization;
- pause/resume can restart the motion channel while leaving its executive task
  suspended;
- `come here` is represented as a persistent follow rather than a terminating
  approach;
- recovery policies are compiled to one attempt and resource/precondition waits
  lack complete deadlines;
- the person-stop envelope adds a time quantity to a distance and has not
  resolved its footprint/clearance convention;
- follow drives proportional velocity directly rather than routing a formation
  goal through the obstacle-aware planner;
- simulator metadata supplies semantic objects and owner identity on the main
  path.

A better VLM cannot repair these authority, lifecycle, sensing, or evaluation
problems. Phase 0 makes later A/B results meaningful.

## Ten-agent research matrix

The requested parallel research was performed as eight navigation/instruction
workstreams plus two independent RL decisions.

| # | Workstream | Principal output | Status |
| --- | --- | --- | --- |
| N1 | Navigation/control code audit | Ranked safety, localization, controller, and deployment defects | complete |
| N2 | Behavior/executive code audit | Ranked lifecycle, recovery, relation, and interruption defects | complete |
| N3 | Classical/model-based navigation | Nav2 sidecar design: Route/Smac, RPP baseline, MPPI challenger, final collision monitor | complete |
| N4 | Downloadable navigation models | MiniCPM, CE-Nav, InternVLA-N1, X-NavDP, CityWalker, VAMOS, OmniNav, NaVILA, StreamVLN, Uni-NaVid; weights/license/runtime audit | complete |
| N5 | Perception/localization | Camera–LiDAR geometry, owner identity, fast/slow perception, semantic memory | complete |
| N6 | Dynamic/social/owner-follow | Formation goals, identity-aware tracking, social costs, MiniCPM-RobotTrack, dynamic-city tests | complete |
| N7 | Instruction/behavior planning | One typed task contract, fast/slow planning, clarification, memory, recovery, gesture admission | complete |
| N8 | Evaluation/benchmarks | Measured-evidence audit and product/BARN/Follow-Bench/MetaUrban/HuNavSim/Habitat ladder | complete |
| RL1 | Strongest case for custom training | Independent go/no-go and narrow future learning triggers | complete |
| RL2 | Strongest case for reuse | Independent build-versus-reuse matrix and training gates | complete |

External metrics in these reports are author-reported unless an artifact under
`evals/**/results/` is cited explicitly. Scores from different tasks are not
compared as if they shared a denominator.

## Board

| ID | Card | Depends on | Parallel lane | Exit condition | Status |
| --- | --- | --- | --- | --- | --- |
| P0-0 | Freeze the current baseline | — | evaluation | immutable source/patch/config/scenario hashes; current product-path and controller/fault evidence captured before fixes | todo |
| P0-A | Final hard-zero safety ordering | P0-0 | control | A stop/TTC veto produces exactly zero at the HAL on the same dispatch, resets shapers, and is pinned under timing/fault tests | todo |
| P0-B | State-health and fail-closed contract | P0-0 | state | typed pose/transform covariance, freshness, and health gates exist; stale/missing LiDAR, pose, transform, or feedback can never translate; simulator truth remains permitted only in labeled simulation | todo |
| P0-C | Atomic executive/channel lifecycle | P0-0 | behavior | pause/resume/cancel/transfer is one task-revision transaction; strict resume xfail is removed | todo |
| P0-D | Recovery, invariants, and deadlines | P0-0, P0-C | behavior | per-task invariant sets; queue/precondition/step/task deadlines; typed bounded recovery is executable | todo |
| P0-E | Freeze the post-fix baseline | P0-A..D,H | evaluation | product-path NAV_INSTRUCT and controller fault suites rerun on identical episodes with complete telemetry | todo |
| P0-F | Minimal cross-lane ABI freeze | P0-0 | architecture | versioned task/state/perception/goal/proposal/safety schemas exist without authorizing any model execution | todo |
| P0-G | Approach/follow lifecycle split | P0-C,D | behavior | `ApproachOwner` settles, verifies, releases `base`, and terminates; `FollowFormation` remains active until Hold/cancel; no task may report success while leaving an orphan motion channel | todo |
| P0-H | Dimensionally valid safety envelope | P0-0 | safety/control | no seconds-to-metres addition; relative-speed or measured-distance allowance is typed; center/footprint clearance convention is single and tested; physical parameters remain unverified until commissioned | todo |
| P1-A | `TaskRequestV1` canonical intent | P0-C,F | language | one parser result carries relation, quantity, units, candidates, ambiguity, amendment, and transcript evidence | todo |
| P1-B | Real localization and perception producers | P0-B,F | perception | synchronized, calibrated camera/LiDAR/IMU/odometry produces MAP/ODOM localization plus typed regions, entities, people, and owner tracks without oracle fields | todo |
| P1-C | Owner identity + formation goal | P1-B | social | multi-frame enrolled identity with ambiguity state; follow emits short-TTL SE(2) goals into the common planner | todo |
| P1-D | Relation-aware terminal witnesses | P0-D,F,G, P1-A,B | semantics | `inside`, `near`, `next_to`, `towards`, `approach_owner`, follow, and orbit each have independent sensor-grounded success | todo |
| P1-E | RPP-style regulation in Parcel | P0-A,B,E,F,H | navigation | current grid path gains curvature/obstacle speed regulation and arc footprint checking with paired local evidence and no hard-stop or p99 regression | todo |
| P2-A | Isolated Nav2 sidecar | P1-E | navigation | exclusive challenger behind narrow versioned IPC; Smac + RPP baseline and MPPI challenger; one smoother; final independent metric-geometry collision monitor; `grid_v1` remains production writer until promotion | todo |
| P2-B | Semantic/topological memory | P1-B | world model | provenance, covariance, TTL, scene revision, reachability, and re-observation are first-class | todo |
| P2-C | Reactive behavior subtrees | P0-C,D,F, P1-A | behavior | clarification, rescan, alternate target, replan, backoff, safe stop, and persistent follow execute with feedback/results | todo |
| P2-D0 | BARN adapter scaffolding | P0-F | evaluation | observation/action translation and evidence-class labeling compile without executing an unfinished controller | todo |
| P2-D | BARN paired controller regression | P0-E, P1-E, P2-A, P2-D0 | evaluation | frozen public-development episodes run unchanged grid/RPP/MPPI adapters with paired `external_proxy` evidence | todo |
| P2-E | Contested-goal re-ranking and arrival | P0-E, P1-B,D,E | social/navigation | dynamic sidewalk xfail passes via bounded mid-mission re-ranking; success requires fresh independent metric geometry, polygon membership with clearance, settled feedback, an agent-issued stop, and no active collision brake | todo |
| P3-A | Product evaluation overhaul | P0-E, P1-A,D | evaluation | unchanged product runtime is exercised; oracle replays are attribution-only; agent-issued stop is required | todo |
| P3-B | External owner/social adapters | P2-A, P1-C | evaluation | Follow-Bench, then MetaUrban/HuNavSim run through adapters without changing Parcel behavior | todo |
| P3-C | Learned proposer harness | P1-B, P2-A, P3-A | models | latest-only out-of-process service, bounded SE(2) proposal schema, TTL, evidence, deterministic HOLD/re-admission contract, veto telemetry | todo |
| P4-A | MiniCPM owner-follow shadow | P1-C, P3-C | models | frozen owner/distractor/occlusion comparison with no identity or safety regression | todo |
| P4-B | Open local-policy shadows | P2-D, P3-C | models | CityWalker plus legally eligible CE-Nav/X-NavDP candidates run paired point-goal/detour comparisons with no collision, latency, or failure-degradation regression | todo |
| P4-C | InternVLA/NaVILA instruction shadow | P2-C, P3-A,C | models | frozen language-navigation comparison; license and memory/co-residency review complete | todo |
| P4-D | Quadruped embodiment physics harness/gate | P0-A,B,F | simulation | harness models Go2 footprint, gait/Sport-like response, command delay, slopes, curbs, stairs, slip, falls, and stopping; every deployable classical or learned composition must pass before HIL | todo |
| P4-E | Local-to-city map handoff | P1-B, P2-B | world model | local mapped/observable navigation is explicit; optional GEO/world-to-MAP/topological handoff has freshness and uncertainty, while external maps remain advisory | later |
| P5-0 | ODD, hazard log, and safety-case signoff | P0-A..H, P1-B, P4-D | safety | ODD limits, FMEA/STPA-style hazards, mitigations, verification traceability, residual-risk owner, incident/replay process, commissioning evidence, and formal go/no-go are reviewed | todo |
| P5-A | Supervised HIL/physical courses | P1-B, P4-D, P5-0 | hardware | commissioned frames/axes/modes, independent E-stop, measured stopping envelope, supervised indoor then outdoor course | todo |
| P6-A | Narrow adaptation decision | P4-A..D, P5-0, P5-A | learning | only a repeated attributable residual remains after open baselines; data and promotion protocol frozen before training | gated |

## Parallel execution and interface locks

After P0 contracts are frozen, four lanes can proceed concurrently:

```text
baseline:       P0-0 -> [P0-A/B/C/D/H] -> P0-E ───────────────────┐
contracts:        └-> P0-F minimal ABI ───────────────────────────┤
navigation:           P0-A/B/E/F/H -> P1-E -> P2-A -> P4-D ─────┤
evaluation:           P0-F -> P2-D0; P0-E/P1-E/P2-A/D0 -> P2-D ┤
                      P0-E -> P3-A product ───────────────────────┤
language/task:        P0-C/D -> P0-G + P1-A -> P2-C ─────────────┤
perception/social:    P0-B -> P1-B -> [P1-C + P2-B + P2-E] ─────┤
external social:      P1-C + P2-A -> P3-B ───────────────────────┤
physical:             P1-B + P4-D -> P5-0 safety case -> HIL ───┘
```

The cross-lane contracts must be versioned before parallel work begins:

- `TaskRequestV1` and `TaskRevisionV1`;
- `PoseEstimateV1` with MAP/ODOM transform, covariance, health, and timestamp;
- `PerceptionSnapshotV1` with evidence IDs and expiry;
- `OwnerTrackV1` / `DynamicTrackV1` with identity posterior and covariance;
- `NavProposalV1` with relative SE(2) waypoints, confidence, source, frame,
  per-waypoint time and uncertainty, timestamp, TTL, task/revision and
  observation IDs, footprint/kinematic profile, and input/calibration ABI hash;
- async goal/feedback/result/cancel semantics for task and navigation actions;
- one `SafetyEnvelope` / `RobotProfile` authority.

## Working agreements

1. No LLM/VLA/learned policy writes Unitree velocity or joint targets.
2. Unitree Sport remains the low-level locomotion controller during this
   program. Replacing it is a separate, evidence-heavy project.
3. Camera and LiDAR are the environmental sensors. Internal IMU/odometry is
   required for state estimation; Google Maps remains advisory and disabled.
4. The final safety monitor sees independent fresh metric geometry **after**
   every smoother or learned component. Sources and coverage are ODD-specific;
   a required missing/stale input or uncovered commanded direction stops and
   never opens a fallback motion path. RGB semantics cannot declare free space.
5. Learned outputs are proposals with TTL and provenance. Timeout, OOM,
   uncertainty, invalid frame, or validator rejection defaults to deterministic
   HOLD. A classical controller may continue only an independently grounded,
   still-fresh, still-authorized goal through the unchanged state and geometry
   gates.
6. Evaluation adapters adapt observations/actions only. They do not change
   Parcel behavior to chase a benchmark.
7. Frozen and candidate runs use identical episode IDs, seeds, resource limits,
   sensor faults, and evaluator versions. Derived rescoring is never called a
   run.
8. Zero simulated collisions is reported with exposure and confidence bounds;
   it is not a physical safety certificate.
9. Model code license, weight license, data terms, and third-party asset terms
   are separate review items.
10. Physical motion stays supervised until commissioning and stopping-envelope
    gates pass. A software E-stop does not replace an independent hardware
    E-stop.
11. Every third-party model is pinned by immutable revision and artifact hash.
    Any custom/remote model code is reviewed, then run without network or
    credentials in a resource-bounded sandbox with an SBOM; it is never
    imported into the control process.
12. Speech, replayed media, OCR, signs, and network content are untrusted
    inputs. Motion tasks require a recorded speaker/channel authorization
    decision; emergency stop is accepted from anyone, while environmental text
    can never become a command.

## Definition of done

This sprint's implementation program is complete only when:

- every P0 defect has a regression test and a clean current baseline;
- common instructions (`sidewalk`, `lamppost`, small owner orbit, relative
  steps, approach owner, persistent follow, wait/hold, pause/resume/cancel) run
  through the real product executive and satisfy independent predicates;
- owner following navigates around obstacles through the common planner and
  never silently switches identity;
- real or sensor-faithful camera/LiDAR evidence replaces oracle semantics on
  the product path;
- Nav2 RPP/MPPI and each license-eligible learned candidate are evaluated on
  the same frozen **role-relevant** episodes and declared sensor contract as
  their appropriate baseline; full-product comparisons with different native
  inputs are reported separately;
- one product-relevant suite and one external suite show a statistically
  credible gain without a hard safety, identity, task-family, or p99 latency
  regression;
- HIL and supervised physical courses demonstrate fail-closed sensor loss,
  cancel/stop handoff, and the measured braking envelope;
- any decision to train is tied to a repeatable residual failure that released
  models and classical baselines do not solve.

The owner's top-decile goal remains an evaluation target, not an optimization
license: it must be reported benchmark-by-benchmark, and no aggregate score may
hide a collision, road entry, false owner, or false success.
