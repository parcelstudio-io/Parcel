# Plan r2 — the two SLAM-adjacent pieces (route-memory "M" + Go2-drift realism)

Owner directive (2026-08-11): no full SLAM in sim (localization stays honest);
instead **(1) wire route_memory** (persistent place memory + global routing —
the measured bottleneck: planner ~8 m vs 12+ m sensing) and **(2) harden the
pose seam with standing degraded-pose eval arms**.

**Orchestration:** Opus/Sol execute; **Fable audits per wave** (fresh ci_gate,
diff-vs-OWNS, one re-run gate per card, adversarial verify on RM-2). Base:
`dd2e857` + the audited uncommitted batch (ci_gate PASS 3668/0).

**r2:** the r1 draft was adversarially checked (workflow `wf_13f735db-e5d`,
two skeptics, both `needs-edits`, 9 blocking findings) and rewritten. The
load-bearing corrections: **the drift machinery largely already exists** (see
recon), so DR-1 shrinks to an EXTEND card; DR-2's injection mechanism was
wrong (navigator overrides cannot reach the pose source — the harness
`pose_profile` seam can); RM-2's trigger claim was false (the pipeline does
NOT distinguish sighted-but-unroutable — the card now specifies the exact
mechanism); and RM-3's original McNemar substrate (v4s LA/BB) is structurally
unreachable under the memory-honesty rule — re-registered on taught-route
cells.

## Recon facts (verified against the tree, r2-corrected)

- `route_memory/`: `memory.py` (RouteKeyframe store + VPR slot),
  `proposer.py` (SE2Goal proposer, gated, "no cmd_vel" — currently does NOT
  stamp task_id/plan_revision), `teach_repeat.py`, `vpr.py` (stub embedder;
  real seam = `siglip2_onnx.embed_image`), `runtime_hook.py`
  (extras-shaped). **Zero PRODUCT consumers; contract tests exist at
  `tests/test_p4_route_memory.py` (14 tests).**
- **Existing drift machinery (Lane B, scrum/20260806/task_3 — DO NOT
  REBUILD):** `pose.py` `DriftingOdomProvider(OdometryNoiseParams)` —
  alpha1..4 variance coefficients + `systematic_translation_scale_sigma` +
  `systematic_yaw_bias_sigma_rad_per_m` + seed (NO %/m knob — pose.py:254
  documents the units trap); `configs/navigation/pose.yaml` with **6
  profiles incl. `calibrated_go2`** (DogLegs published band: 0.5–1.0 % of
  distance short-segment RPE, 0.2–0.5 deg/m yaw; derivation block in the
  yaml) **and `calibrated_go2_reanchoring`**; pinned by
  `tests/test_pose_drift_calibration.py` (12 tests, 60-seed measurement
  harness); `walk_with_me` already runs a `--pose-profile` arm (4 profiles,
  0 collisions, LOST 3/3). `provider_from_config(profile=...)` is the
  by-name construction seam (fails closed on unknown profiles AND unknown
  yaml keys). Current LOST knobs: `forced_health` + one-way `lost_after_s`
  (permanent — no recovery, no scheduling). MAP is truth-passthrough by
  default (re-anchor events only occur on `map_correction`-enabled
  profiles).
- Eval pose injection: the nav_instruct runner builds observations with
  `pose_provider=None` (runner.py:424); `HeadlessCityQualityHarness`
  already takes `pose_profile=` (headless_city.py:582) with
  `new_pose_provider()` (:613) — **the seam DR-2 uses; navigator_overrides
  cannot reach pose** (DirectiveNavigator.from_config has no pose kwarg).
- Pipeline reality for RM-2: the ONLY unroutable hook is
  `_unroutable_goal_recovery` (fires on `goal_blocked`/`no_path` + a
  non-progress hysteresis; its action is release + blacklist into
  `_unreachable_candidates`, and blacklisted targets can never be
  re-grounded). Beyond-window goals are CLIPPED to the rolling window and
  planned as status `partial` — they usually never reach that hook. No code
  path consumes bus proposals into motion (arbiter resolve() is used as
  veto/validation of the pipeline's own proposal).
- P0-C: SE2Goal carries (task_id, plan_revision); `flush_task()` exists on
  bus + arbiter (AF-2); the pipeline threads `_active_task_id` /
  `_active_plan_revision` (lock-on precedent).
- Gate substrates: v4s LA/BB are STRAIGHT corridors — an episode's own
  traversal never covers a route the planner can't already see, so
  route-memory cannot flip them under the memory-honesty rule (Y-3 lesson:
  do not pre-register an unreachable gate). The v4 minival travels 13.5 m
  TOTAL — drift-insensitive (Lane B's own smoke: SPL delta 0.0003) — floors
  derived from it would be vacuous.

## Global rules (unchanged from task_1; binding on every card)

1. `ci_gate --tier commit` GREEN to close; red = fix or STOP-and-report.
2. Frozen artifacts immutable; frozen-row movement = STOP + 2×2.
3. Flags default OFF; flag-off byte-identity PROVED (AF-2's pinned digest
   recipe).
4. No safety weakening; route-memory output = SE2Goal proposals only;
   grid_v1 + reactive gate remain sole motion authority; K0 sole arrival
   authority.
5. OWNS/MUST-NOT-TOUCH per card; `runtime.py`, `pipeline.py`,
   `evals/nav_instruct/runner.py` single-owner per wave; out-of-OWNS =
   enumerated handoff. Audit treats a violated union as RETURNED.
6. Constants derive or carry documented provenance; no tuning to a gate.
7. Measured claims, `does_not_prove`, seeded-failure proofs for property
   tests. Status docs in `scrum/20260811/task_2/`.

---

## Wave 1 — pure/extend, parallel, disjoint (RM-1 ∥ DR-1)

### Card RM-1 [sol] — place-graph memory: persistence + route query
Extend the existing store (contract amendments with provenance; update
`tests/test_p4_route_memory.py` alongside, each edit citing the amendment):
- **Ingestion**: `record_visit(pose, view_embedding=None, semantic_labels=(),
  timestamp_tick=…)`. **Frame discipline day one:** poses are MAP-frame
  PoseEstimates via the sanctioned seam; the persisted schema records the
  frame; behavior under MAP re-anchor jumps is documented in the contract
  (keyframes are MAP snapshots; edges recorded across a jump carry a flag).
  Keyframe admission: `keyframe_spacing_m` constructor parameter whose
  DEFAULT derives once from the grid resolution × a stated multiple
  (derivation comment at the definition).
- **Route query**: `waypoints_toward(goal_xy, from_xy) ->
  tuple[RouteKeyframe, ...]` — recorded-edges-only shortest chain (NEVER
  inventing unvisited shortcuts; empty tuple = no route, fail-closed).
  SE2Goal conversion is NOT here — it lives in proposer.py (RM-2).
- **Persistence**: session-scoped default; `save(path)`/`load(path)`
  (versioned header, refuse-don't-partially-load). Cross-session enablement
  is owner-gated (OPEN); mechanism lands now.
- **Embedding seam**: stub default; `embed_fn` injection documented for
  `siglip2_onnx.embed_image`. No onnx import in the pure module.
- OWNS: `route_memory/{memory,teach_repeat,vpr}.py` (amendments with
  provenance), NEW pure files in the package, `tests/test_p4_route_memory.py`
  + new tests. MUST-NOT-TOUCH: `proposer.py`/`runtime_hook.py` (RM-2's,
  editable there), runtime.py, pipeline.py, evals/**.
- GATE: property tests w/ seeded-failure proofs — no-invented-edges;
  persistence round-trip + corrupted-file refusal; MAP-frame recorded in
  schema; derived spacing pinned by reference; determinism. ci_gate green.

### Card DR-1 [sol] — EXTEND the existing drift machinery (no new profile system)
No new `pose_profiles.py`, no new dataclass system, no re-derivation of the
calibration. Additive extensions to `pose.py` + `configs/navigation/pose.yaml`
+ the `PoseConfig`/`load_pose_config` schema (unknown-keys-fail-closed
preserved):
- **Scheduled LOST windows that RECOVER**: `(start_s, duration_s)` dropout
  windows composing with drift (existing `lost_after_s` is permanent —
  unchanged; the new knob is additive, default off).
- **Slip-jump params**: magnitude (m) + mean rate (/m), default 0.0 = off —
  every existing profile and `tests/test_pose_drift_calibration.py`
  byte-untouched.
- **Two new profiles by the EXISTING methodology**: `go2_aggressive`,
  `go2_degraded` — expressed in the provider's actual parameter space
  (alpha1..4 + the two systematic sigmas + slip), each with a stated target
  band per source and then MEASURED over 60 seeds via the
  test_pose_drift_calibration harness (reuse it — that IS the "within
  envelope" gate). `go2_nominal` = the existing `calibrated_go2` verbatim
  (cite pose.yaml's derivation block; provenance = DogLegs band 0.5–1.0 %
  distance RPE / 0.2–0.5 deg/m yaw — NOT the r1 draft's "1–3 %/m", which the
  yaml's own derivation refutes).
- **Deliverable contract for DR-2**: `provider_from_config(profile=
  "calibrated_go2"|"go2_aggressive"|"go2_degraded"[|"*_lost"])` returns a
  ready provider — the by-name seam, nothing else needed.
- OWNS: `src/parcel_robot/pose.py` (additive), `configs/navigation/pose.yaml`
  (additive entries; existing profiles byte-untouched — test-pinned),
  the PoseConfig schema extension, `tests/test_pose_drift_calibration.py`
  (additive cases). MUST-NOT-TOUCH: runtime.py, navigation/**, evals/**,
  headless_city.py.
- GATE: existing 12 calibration tests green untouched; new profiles measured
  in-band over 60 seeds; every new profile constructs via
  `load_pose_config` while pre-existing profiles' parsed configs are
  asserted unchanged; LOST windows recover (test) and compose with drift
  without state corruption; slip default-off proven byte-neutral. ci_gate
  green.

---

## Wave 2 — wiring, parallel, disjoint (RM-2 ∥ DR-2), after Wave-1 audit

### Card RM-2 [opus] — route-memory on the product path
Flag `route_memory`, default OFF. Three mechanisms, specified concretely
(r2 — the r1 "pipeline already distinguishes" claim was false):
- **Auto-teach**: feed `record_visit` from the product path per admitted
  keyframe (MAP-frame via the seam; labels from resolved candidates;
  embedding seam optional). `runtime_hook.py`'s extras shape where it fits.
- **Beyond-reach trigger (build it, don't assume it)**: consult
  `waypoints_toward` (i) inside `_unroutable_goal_recovery` BEFORE
  `_release_unreachable_candidate`, and (ii) on prolonged non-progress while
  `last_route_status == "partial"` with the commitment grounded.
  Distinguish at-range from inside-obstacle via
  `RoutePlan.requested_goal_world` vs `planning_target_world` (or goal
  distance > window_span/2) so inside-obstacle goals keep today's release
  path. While a memory route is active AND advancing, DEFER the blacklist
  and suspend the UNROUTABLE_GOAL_STEPS release; memory returns empty ⇒
  today's behavior verbatim (fail-closed).
- **Consumption (build it — no path consumes bus proposals into motion
  today)**: publish the waypoint SE2Goal **stamped with the pipeline's
  active (task_id, plan_revision)** (thread like the lock-on precedent —
  `proposer.py`/`runtime_hook.py` are RM-2-EDITABLE for the stamping;
  RM-1's memory/teach_repeat/vpr contracts stay frozen); resolve through
  `goal_arbiter` (veto/lethal preserved); on win, store ONLY as an interim
  navigation target consumed where the grid navigator's GoalPose is built.
  **The mission goal, K0 region, and arrival predicate are never replaced**
  — the chain ends by handing back to normal planning when the true goal
  enters routable range; mission completion remains K0-at-the-true-goal
  only. `flush_task` clears pending waypoints on refusal/correction.
- OWNS: `route_memory/{proposer,runtime_hook}.py`, `runtime.py` (Wave-2
  owner), `navigation/pipeline.py` (Wave-2 owner), config plumbing, NEW
  test files + the named AF-2 interleaving test (extension only).
  MUST-NOT-TOUCH: instructnav/arbiter.py contracts (consume), K0/scoring,
  collision/reactive, evals/** (DR-2 owns runner this wave),
  tests/test_e4_evidence_seams.py + tests/test_person_aware_nav.py (DR-2's
  if needed; moot if no allowlist change).
- GATE: (a) flag-off byte-identity (v4 minival digest per AF-2 recipe) AND
  flag-off `_unroutable_goal_recovery` release behavior byte-identical;
  (b) non-vacuity with a paired control: a scripted corridor scenario
  (drive A→B→A, then task a goal near B sighted at 10–12 m — memory covers
  A↔B) where flag-ON arrives via a winning waypoint chain and flag-OFF
  fails-or-is-≥N-ticks-slower under the same budget (N pre-stated; the
  DELTA is the evidence, not the win alone); (c) a lethal-veto test on a
  waypoint proposal (no new motion authority); (d) correction mid-chain
  flushes pending waypoints (AF-2 interleaving extension); (e) ci_gate
  green.

### Card DR-2 [opus] — the standing degraded-pose arm (r2 mechanism)
- **Injection (corrected)**: `pose_drift_profile: str | None = None` on
  NavInstructRunner, forwarded to `HeadlessCityQualityHarness(pose_profile=…)`;
  one FRESH provider per episode via `harness.new_pose_provider()`, passed
  as `pose_provider=` to `_nav_observation` (drift never crosses episodes —
  the harness's own invariant). CLI arm on run_nav_instruct_v1.py, recorded
  in every persisted row; `--freeze` refuses any non-None profile. **No
  ALLOWED_NAVIGATOR_OVERRIDES change, no pin moves, no headless_city.py
  edits.**
- **Substrate (corrected — the v4 minival is drift-insensitive)**:
  floor-bearing arms run on TRAVEL-HEAVY substrates — the v4s cells (12 m
  routes, candidate-only) and/or new long-travel scenario cells; the v4
  minival is a tripwire only (report, no floor). REQUIRED per-episode
  report: distance travelled + measured truth-vs-ODOM divergence;
  non-vacuity = divergence within the profile's band, per episode.
- **Floor protocol (fixed NOW, before Stage A — the Y-3 lesson):** Stage-B
  floor per (profile, metric) = the Stage-A measured value exactly, minus
  at most one episode quantum (1/n). No other margin, no per-profile
  discretion. Stage A and Stage B are one harness invocation apart;
  Stage-A numbers land in the status doc before any floor is asserted.
- **Hard from day one** (no measurement grace): collisions = 0 and
  false_arrival = 0 under every profile.
- **Re-anchor metric scoping (corrected)**: `re-anchor events > 0` is
  asserted ONLY on `calibrated_go2_reanchoring` (or a map-correction
  profile) — MAP is truth-passthrough by default and the metric is
  pre-known 0 there. The LOST-window arm asserts POSE_LOST hold + recovery.
- **Cadence**: ci_gate NIGHTLY tier (+ its self-test: a seeded drift-arm
  failure reddens nightly); commit tier gains only cheap unit tests.
- OWNS: `evals/nav_instruct/runner.py` + `run_nav_instruct_v1.py` (Wave-2
  owner), `scripts/ci_gate.py` (nightly arm only), NEW scenario/test files.
  MUST-NOT-TOUCH: runtime.py + pipeline.py (RM-2), pose.py/pose.yaml (DR-1
  frozen), headless_city.py, frozen episodes (candidate-only rows).
- GATE: injection non-vacuity (per-episode divergence in-band); Stage-A
  table with all required metrics; the two hard safety floors; frozen
  digests unmoved; nightly self-test reddens on seed; ci_gate green.

---

## Wave 3 — measurement (RM-3), after Wave-2 audit

### Card RM-3 [opus] — does place memory convert the bottleneck? (r2 substrate)
- **GATED substrate (re-registered — v4s LA/BB is structurally unreachable
  for route memory under the memory-honesty rule):** NEW additive
  **taught-prior-route cells** (own results namespace, n ≥ 60): each
  scenario declares a taught route whose recorded edges cover a path from
  start region to goal region; goal sighted-or-known but beyond planner
  reach. Pre-registered: **≥6 net paired flips, exact McNemar p ≤ 0.031**,
  route_memory ON vs OFF, isolated processes, both matcher arms reported.
- **Report-only arms** (no gate): v4s LA/BB ON-vs-OFF (expected ≈no-op —
  confirming the honesty rule, not failing a gate); one drifted arm
  (`calibrated_go2` × route_memory ON) — keyframe integrity under drift
  reported (MAP-frame discipline observed), not gated first pass.
- **Teach-and-repeat cell** (additive, own namespace): teach by driving,
  `follow` replays via proposals — SR + path fidelity vs the taught line.
- OWNS: runner + run_nav_instruct_v1 (Wave-3 owner), new cell files, docs.
  MUST-NOT-TOUCH: all src/** (measurement card; src fix = handoff).
- GATE: honest numbers, met or STOP-and-report; frozen digests unmoved;
  ci_gate green.

## Fable audit protocol (pre-registered)

Per wave: fresh ci_gate; diff-vs-OWNS; one independently re-run gate per
card; **adversarial workflow on RM-2** (arbitration-bypass hunt, P0-C
interleavings incl. flush_task, waypoint-vs-mission-goal authority, flag-off
byte-path, the deferred-blacklist livelock question) and on DR-2's
non-vacuity; verdicts in `AUDIT_<wave>_FABLE.md` here.

## OPEN (owner-gated)

- Cross-session place-graph persistence policy (store location, retention,
  remember-routes-across-days default — ties to tiered-memory conventions).
- Voice surface for teach-and-repeat ("learn this route") — closed-intent
  growth.
- Drift-arm Stage-B floors: nightly-only vs eventually commit-tier.
- CityWalker A/B (ADJUDICATION D7) + VLFM-real: out of scope until this
  lands.
