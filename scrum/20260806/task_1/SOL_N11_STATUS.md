# Sol 5.6 Ultra — N11 pure layer status (2026-08-06)

> **Revision 2 (post-arbitration, same day).** The original recommendation
> below predates three events: (1) an unattributed third hand landed the
> wiring and extended this card's files; (2) Opus's review
> ([REVIEW_OPUS_ON_SOL_N11.md](REVIEW_OPUS_ON_SOL_N11.md)) returned
> REQUEST CHANGES; (3) [ARBITRATION_20260806.md](ARBITRATION_20260806.md)
> made SB-1..SB-7 binding on this lane. The **SB outcomes and the SB-6
> reconciliation record are in the addendum at the end**; the module
> contract section below is updated to the post-SB API. Seam-2's
> navigator-seed recommendation is **superseded by arbitration OB-3**
> (seed the runtime S-curve shaper, single-writer — Opus lane). Line-number
> citations in the seam section drifted under concurrent edits (Opus S6);
> per that finding, treat file+symbol as authoritative, not file+line, and
> note `relations.py` is `src/parcel_robot/instructnav/relations.py` —
> there is no `navigation/relations.py`.

**Card:** N11 traffic-aware goal placement + yield-advance pacing, pure layer
only ([backlog/NEXT.md](../../../backlog/NEXT.md) N11; defect pinned in
[scrum/20260805/task_2/README.md](../../20260805/task_2/README.md) and as the
xfail `test_go_to_the_sidewalk_with_pedestrian_traffic`,
`tests/test_voice_nav_e2e.py:223`).

**Scope discipline:** new files only —
`src/parcel_robot/navigation/traffic_aware.py`,
`tests/test_traffic_aware.py`, this doc. No existing file touched (Opus owns
existing files today). All wiring below is a *recommendation with citations*,
not a change.

## Module contract — `parcel_robot.navigation.traffic_aware`

Pure by contract: stdlib + typing only, no I/O, no clocks (callers pass
`now_s`), no imports from pipeline/runtime, mirrors
`instructnav/relations.py` / `scoring.py` style (finite-input validation,
loud `ValueError` on malformed input).

### `traffic_occupancy_cost(point_xy, tracks, *, horizon_s=3.0, step_s=0.25, influence_m=0.9, decay_half_life_s=None, max_age_s=None) -> float`

Time-integrated proximity of predicted constant-velocity agent paths to a
candidate point. Each track `(x, y, vx, vy, radius_m, age_s)` is rolled out
over the horizon; per sample, proximity is 1 at/inside the agent disc,
falling linearly to 0 at `influence_m` beyond the disc surface; cost is the
rectangle-rule sum `Σ proximity·w(t)·dt` (`w(t)=1`, or `2^(−t/half_life)`
when decay is set).

**Sampling (SB-1/SB-2):** the per-track substep is
`min(step_s, influence_m/(2·speed))` — no constant-velocity track can step
across the influence band and score a spurious 0.0 (the pre-SB-1 tunneling
defect at ≥10 m/s) — floored at `horizon_s / MAX_SAMPLES_PER_TRACK` (4096)
so a pathological `step_s` degrades resolution instead of stalling the
caller. Tracks at pedestrian speed (≤1.8 m/s at defaults) sample on exactly
the `step_s` grid, so slow-track costs are unchanged by SB-1 (pinned).

**Units: (weighted) exposure seconds.** One agent parked on the point ≈
`horizon_s + step_s` (closed sample grid); 0.0 = no predicted path enters
the influence band. Coupling note (SB-7): because the grid is closed,
`step_s` is not a pure resolution knob — a parked agent integrates to
`horizon_s + step_s`, so changing `step_s` at fixed weights slightly
re-tunes the static↔traffic tradeoff. Deterministic; empty tracks returns
exactly `0.0`. `max_age_s` (SB-5) drops tracks with `age_s > max_age_s`
before rollout. Tracks accepted as `TrackState`, attribute duck-types
(including `dynamic_costs.AgentTrack`), or `(x, y, vx, vy[, radius])`
sequences via `coerce_tracks`; runtime `extras["dynamic_agents"]` payloads
via `tracks_from_payload` (stdlib sibling of the `dynamic_layer` parser,
capped at `DEFAULT_MAX_TRACKS = 16`).

### `rank_approach_candidates(candidates, tracks, *, static_cost_fn=None, static_costs=None, static_weight=1.0, traffic_weight=1.0, horizon_s=3.0, step_s=0.25, influence_m=0.9, decay_half_life_s=None, top_k=None, max_age_s=None) -> list[RankedCandidate]`

Best-first ranking of candidate points. Static suitability is
caller-supplied (callable *or* precomputed list — both at once raises;
neither means static 0.0). Returns every candidate as a frozen
`RankedCandidate(index, x, y, static_cost, traffic_cost, total_cost)` with
`total = static_weight·static + traffic_weight·traffic` so the eval can
attribute placement decisions. No reject threshold — safety/feasibility
prefiltering stays with the caller.

**Ladder rule (pinned by test, verified sound by Opus's adversarial float
testing — mechanism unchanged per arbitration):** sort key is
`(total_cost, static_cost, index)`. With empty `tracks` (or
`traffic_weight=0`, or every track filtered by `max_age_s`) every traffic
term is exactly `0.0`, so the key reduces to the static ordering
`(static_cost, index)` — byte-identical for any `static_weight > 0`
(positive-scalar multiplication is monotone; ties fall to static then
original index, same as the static ordering). An inactive proposer changes
nothing.

**`top_k` (SB-5):** when set, only the `top_k` statically best candidates
(by `(static_cost, index)`) receive traffic evaluation and appear in the
result — bounds the rollout cost at `approach.py`'s up-to-~1.7k-sample
candidate grids (Opus measured 19–34 ms unbounded). The ladder rule holds
on the subset: with no tracks the result is exactly the static head.

### `RampMemory(*, max_hold_s=2.5, decay_half_life_s=1.5, resume_scale=0.75, min_record_vx=0.05)`

Yield-advance pacing memory. Per-tick protocol for the layer that owns the
stop decision:

- moving tick → `note_running(now_s, commanded_vx)` (pre-gate forward
  command; negative vx raises — forward ramps only);
- gated tick → `note_stopped(now_s)` — **returns nothing, ever**;
- first tick after the gate opens → `seed = release(now_s)`; seed the
  controller slew state with `seed` instead of zero.

`release` returns `held · resume_scale · 2^(−stop_s/decay_half_life_s)` for
stops shorter than `max_hold_s`, else exactly `0.0` **clearing the held
memory** — the monotonic time base survives; only `reset()` is a full reset
(SB-7 wording fix; long stops also clear the memory *while still stopped*).
`note_running` ignores commands below `min_record_vx` (default 0.05, SB-4)
after validating them: controller align/hold ticks command ~zero velocity
and must not wipe the held state mid corner-flap-plus-pedestrian — the
wiring carries the same guard on its side (OB-4, intentional defense in
depth). Time regressions, NaN/inf, wrong-type, and bad config raise
`ValueError` at every public entry (SB-3 — previously several of these
surfaced as `TypeError`, contradicting the documented contract).

**Safety argument:** RampMemory is memory, never a gate and never a command
source. There is no API that yields a non-zero velocity while a stop is in
force (`note_stopped` returns `None`; `held_velocity_mps` is telemetry).
`release` is by definition the caller's statement that the safety gate has
*already* opened, and the returned seed only raises the *requested*
velocity, which every downstream authority still bounds every tick
(collision brake `collision.py:59`, reactive gate `reactive_safety.py`,
velocity bounds + all-ray shield `pipeline.py:468-497`, runtime
`_collision_safe` + S-curve shaper `runtime.py:3740-3762`). It changes
recovery speed after the gate releases, never the gate itself. Person-stop
behavior is untouched by construction.

## Recommended wiring seam (for Opus — cited, not edited)

### Seam 1 — traffic-aware goal placement

The single approach-pose decision point for semantic missions is
`pipeline.py:666` (`NavPipeline._commit_semantic_candidate` →
`safe_approach_pose`, defined at `approach.py:18`). Inside it the final
point choice is a traffic-blind nearest-static pick at:

- `approach.py:229` — `_safe_polygon_point`: `min(valid, key=distance)` —
  the **sidewalk ("inside") case that the xfail exercises**;
- `approach.py:281` — `_safe_near_object_point`: same pattern for
  near-object goals;
- (lower priority) `src/parcel_robot/instructnav/relations.py:92` —
  `next_to_placement` score sort (SB-7 correction: this is `instructnav/`,
  not `navigation/` — the earlier bare citation misread as a nonexistent
  `navigation/relations.py`).

Recommended edit shape (Opus):

1. Add optional `tracks: Sequence[AgentTrack] = ()` to
   `safe_approach_pose` and thread it from `_commit_semantic_candidate`,
   parsing `observation.extras.get("dynamic_agents")` with
   `tracks_from_payload` (`dynamic_layer.py:159`) — the exact payload the
   grid navigator already consumes at `grid_navigator.py:475`. Wrap the
   parse in the same loud-but-degrading pattern used there
   (`grid_navigator.py:477-483`).
2. Replace the two `min(...)` selections with
   `rank_approach_candidates(points, tracks, static_cost_fn=distance_to_robot)[0]`.
   Default `tracks=()` keeps behavior byte-identical (ladder rule above,
   pinned by `test_empty_tracks_ordering_identical_to_static_ordering`);
   `min` first-minimum semantics equals the `(static, index)` tie-break.
3. Record the chosen candidate's breakdown
   (`approach_static_cost`, `approach_traffic_cost`) into mission metadata
   at `pipeline.py:680` (`metadata.update`) so the e2e eval can attribute
   placement decisions.

Note on overlap: `navigation/proxemic_approach.py` (numpy, unwired) already
scores poses via `dynamic_costs.agent_cost_at` + TTC, with a fail-closed
`reject_cost`. It is complementary, not competing: `traffic_aware` is the
stdlib-pure ranking seam the N11 card specifies, guarantees static-order
identity when inactive (which `select_proxemic_approach` cannot — it
returns `None` fail-closed), and returns full breakdowns. If Opus prefers
one module at the seam, `rank_approach_candidates` is the ranking;
`proxemic_approach.reject_cost` remains available later as an *additional*
veto on top.

### Seam 2 — RampMemory into the velocity slew

> **SUPERSEDED by arbitration OB-3 (2026-08-06):** Opus measured the
> navigator-side seed as ~96% masked by the runtime S-curve shaper's jerk
> limit (+6.4% recovered distance, one tick faster to 80% cruise). The
> binding wiring is now: seed the runtime shaper (`_last_shaped` — the
> shaper already supports seeding), single-writer, with the navigator
> `seed_ramp` path dropped or sim-gated. The text below is retained as the
> original recommendation for the record; its person-stop keying was also
> corrected by the landed wiring (`cnote` captured before shield
> concatenation, per Opus-B3). Time source: the landed `_ramp_now_s` uses
> a finite-stamp check with a tick-counter fallback (Opus-B2 resolved).

The re-ramp-from-zero lives in the grid controller: `grid_navigator.py:443-447`
slews `vx` from `self._last_vx` by `max_linear_accel · control_dt_s`
= 0.9 × 0.1 = **0.09 m/s per tick** (defaults at `grid_navigator.py:74-75`).
During a pedestrian pass `_last_vx` is zeroed by align mode
(`grid_navigator.py:426` → stored at `:454`) and blocked-plan recovery
(`grid_navigator.py:505`), and the pipeline's person gate zeroes the output
at `pipeline.py:499-500` (from `apply_collision_brake` `collision.py:74-75`).
So each clear window restarts from 0 and needs ~9 ticks to reach cruise.

Recommended hook (single writer, pipeline layer — it owns the stop reason):

1. `NavPipeline` owns one `RampMemory`; `reset()` it in mission
   set/reset/pause paths and on emergency stop.
2. In `NavPipeline.step` after `apply_collision_brake`
   (`pipeline.py:460-467`):
   - `cnote == "person_stop"` → `ramp.note_stopped(t)`; the zero return at
     `pipeline.py:499-500` stands **unchanged**;
   - first non-person_stop tick while `ramp.state == "stopped"` →
     `seed = ramp.release(t)`; seed the controller (below);
   - otherwise → `ramp.note_running(t, cmd.vx)` with the pre-brake
     navigator command (`pipeline.py:461`).
3. Seeding: add a small `GridNavigator.seed_ramp(vx)` setting
   `self._last_vx = min(max(self._last_vx, vx), self.cruise_vx)` so the next
   `_slew` at `grid_navigator.py:443` starts from the seed, not zero. The
   gate chain after the navigator is untouched.
4. Time source: `RampMemory` needs only monotonic seconds —
   `observation.extras["odometry_timestamp_s"]` (the freshness key,
   `grid_navigator.py:908-909`) or a pipeline tick counter ×
   `control_dt_s`.
5. Optional second hook, only if the pipeline seed proves insufficient in
   the e2e: the runtime S-curve shaper resumes from `_last_shaped`, which
   `_reset_motion_shaper` (`runtime.py:3891`) zeroes on stops; the shaper
   already supports velocity seeding (`runtime.py:3876`,
   `shaper.reset(self._last_shaped)`). Start with the pipeline hook only —
   one writer.

## Tunables

| Tunable | Default | Rationale |
|---|---|---|
| `horizon_s` | 3.0 s | Covers a crosswalk pedestrian (~1.2–1.5 m/s) sweeping the ~2 m person-slow envelope past a candidate. Longer than the 2.0 s per-tick planner horizon (`dynamic_costs.py:43`) because placement is a one-shot decision, not a 10 Hz cost. |
| `step_s` | 0.25 s | 13 samples/track/candidate for slow tracks; stdlib cost stays trivially cheap for tens of candidates × a few tracks. Coupling (SB-7): the closed grid adds one `step_s` of exposure for a parked agent, so this knob also slightly re-tunes the static↔traffic tradeoff. Above 1.8 m/s the substep adapts to `influence_m/(2·speed)` (SB-1). |
| `MAX_SAMPLES_PER_TRACK` | 4096 | SB-2 floor on the effective substep: a config typo (`step_s=1e-5` measured at 300k samples / 59 ms pre-fix) degrades resolution instead of stalling the control loop. Worst case ≈ 16 tracks × 4097 samples, single-digit ms. |
| `top_k` | None (off) | SB-5: bound traffic evaluation at large candidate grids (`approach.py` up to ~1.7k interior samples measured at 19–34 ms unbounded). K=32 covers realistic geometries; the wiring chooses. |
| `max_age_s` | None (off) | SB-5: CV-extrapolating a stale track is confidently wrong. The wiring should set this to its perception staleness budget; all-stale degrades exactly to static ordering. |
| `min_record_vx` | 0.05 m/s | SB-4: align/hold ticks command ~zero and must not wipe held ramp state; below-floor commands validate but do not record. Matches the wiring-side OB-4 guard (defense in depth). |
| `influence_m` | 0.9 m | Matches the brake envelope this cost exists to avoid: default `person_stop_m` 1.2 (`collision.py:23`) minus typical pedestrian radius 0.35 ≈ 0.85. A point within influence of a predicted path would trip person_stop/slow on arrival. |
| `decay_half_life_s` (cost) | None (off) | For *placement*, a pedestrian arriving at t=2.5 s blocks the final metre just as surely as one at t=0.5 s. The grid layer's 0.8 s decay is a per-tick concern. Enable only if placement flaps in the wired eval. |
| `static_weight` | 1.0 | Static cost arrives in metres (distance/clearance); 1.0 keeps the total in metre-equivalents. |
| `traffic_weight` | 1.0 | 1 exposure-second ≙ 1 m of detour. The crosswalk stream yields ≥1 s exposure while quieter entries are ~1–2 m worse — flips exactly the xfail geometry (`test_traffic_cost_only_overrides_static_when_it_matters`). |
| `max_hold_s` | 2.5 s | About one pedestrian pass. A person-stop longer than this means the scene changed; resume from zero. |
| `decay_half_life_s` (ramp) | 1.5 s | A 1.5 s stop resumes at half the scaled velocity — bounded aggression between passes. |
| `resume_scale` | 0.75 | Never resume above 75 % of the pre-stop command even for instant stops; recovers most of the ~9-tick ramp while conceding margin. Also applied on re-stop (release re-arms memory at the seed, not the stale pre-stop value). |

## Verification (revision 2)

- `.parcel/bin/python -m pytest tests/test_traffic_aware.py -q` →
  **56 passed** (original 40, plus the 5 reconciled third-party
  `tracks_from_payload` tests, plus 11 new SB pins: 10/15 m/s
  anti-tunneling, pedestrian-cost invariance under SB-1, SB-2 sample cap,
  SB-3 ValueError-at-every-boundary table, SB-4 floor semantics ×2, SB-5
  top_k + staleness ×3, payload/duck age threading).
- `.parcel/bin/python -m ruff check` on both files → clean (three
  `noqa: TRY004` with SB-3 citations — the arbitration mandates ValueError
  for wrong-type input at public boundaries, which ruff's TRY004 would
  otherwise rewrite to TypeError).
- Wiring consumers re-run after the API changes (additive keyword-only —
  no signature breaks): `tests/test_approach_traffic_wiring.py` +
  `tests/test_navigation_admission_regression.py` green alongside mine
  (65 passed combined).
- `pytest tests/ -q --co` → collects with zero errors (full-suite green is
  Opus's lane — OB-1/OB-9; not claimed here).

## Not proven (honesty section)

- **No closed-loop evidence from this lane.** The wiring has since landed
  (Opus lane, arbitration baseline), but the e2e xfail
  (`tests/test_voice_nav_e2e.py:223`) is OB-9's gate: it flips (or gets an
  updated measured reason) at the end of the Opus round — nothing here
  claims it. These tests prove the pure contract, not the fix.
- The occupancy model is constant-velocity only — no intent, turning, or
  IMM; accelerating/curving pedestrian streams are outside the model.
- Costs are exposure-seconds under a linear kernel, not calibrated
  probabilities; the default weights were chosen by geometric argument, not
  tuned on the eval (and must not be tuned on the hidden split).
- RampMemory's safety property is architectural (cannot emit during a
  stop); "faster recovery is still safe" is a closed-loop claim that needs
  the wired e2e plus the person-stop safety suite re-run.
- Determinism is proven at the unit level (same process, same platform);
  cross-platform bit-identity is not claimed.
- `proxemic_approach.py` is **PARKED** by arbitration (adopting Opus's
  recommendation): not wired (two disagreeing proxemic authorities = the
  D5 defect class), not deleted (its TTC term and `reject_cost` shape are
  the ingredients for a later fail-closed veto on the ranked winner).

---

## Addendum — arbitration round SB-1..SB-7 (2026-08-06, revision 2)

Binding rulings from [ARBITRATION_20260806.md](ARBITRATION_20260806.md),
executed in this lane's three files only.

### Per-SB outcomes

| ID | Outcome |
|---|---|
| SB-1 | **Done.** Per-track adaptive substep `min(step_s, influence_m/(2·speed))`. Opus's measured tunnel (9 m/s → 0.0417, 10 m/s → 0.0000) is closed: pinned nonzero at 10 and 15 m/s with mid-grid crossing geometry that provably scored 0.0 pre-fix; pedestrian-speed costs pinned bit-equal to the fixed grid (≤1.8 m/s unaffected). |
| SB-2 | **Done.** `MAX_SAMPLES_PER_TRACK = 4096` floors the effective substep at `horizon_s/4096`; `step_s=1e-6` now converges to ≈horizon in ~4k samples instead of 300k (pinned). |
| SB-3 | **Done.** `_finite_float` boundary coercion on every public entry (`traffic_occupancy_cost`, `rank_approach_candidates`, `coerce_tracks`, `tracks_from_payload`, `TrackState`, all `RampMemory` methods/ctor). Opus's TypeError table is now a pinned ValueError table (16 calls). Three `noqa: TRY004` carry SB-3 citations — ruff prefers TypeError for type errors; the arbitration overrules for this module's contract. |
| SB-4 | **Done.** `min_record_vx=0.05` ctor param; `note_running` validates then ignores below-floor commands (time guard still advances). Pinned: align tick + 0.04 tick leave held=0.85; configurable floor; below-floor input still validates loudly. Wiring-side OB-4 guard is Opus's — intentional defense in depth. |
| SB-5 | **Done.** `top_k` (statically-best preselection; traffic evaluated only for the kept set; ladder rule holds on the subset — pinned) and `max_age_s` staleness filter with a new `TrackState.age_s` field (default 0.0 = fresh) threaded through `coerce_tracks` duck-typing and `tracks_from_payload`; all-stale degrades exactly to the empty-tracks static ordering (pinned). |
| SB-6 | **Done.** Reconciliation record below. |
| SB-7 | **Done.** Header note pins file+symbol over file+line for cross-agent recipes and corrects `instructnav/relations.py`; Seam-2 section marked SUPERSEDED by OB-3 with the measured reason; `release()` wording fixed ("clears the held memory; time base survives; only `reset()` is full reset") in both module and doc; `step_s`/parked-cost coupling documented in module docstring and tunables table. |

### SB-6 reconciliation of the unattributed extensions (313→432 lines, 40→45 tests)

Reviewed line-by-line against my revision-1 originals. Inventory of the
third-party delta and disposition:

| Extension | Disposition |
|---|---|
| Module: `DEFAULT_MAX_TRACKS = 16` (+ comment tying it to `dynamic_layer.MAX_TRACKS`) | **Claimed as-is.** Correct constant, correct rationale. |
| Module: `tracks_from_payload(payload, *, max_tracks)` (~44 lines) | **Claimed with fixes.** Intent and shape correct (stdlib sibling of the `dynamic_layer` parser; None→(), cap, loud reject). Fixed: two `TypeError` raises → `ValueError` (SB-3); `max_tracks` validation tightened (rejects bool and non-int); gained `age_s` parsing (SB-5). |
| Module: imports (`Iterable`, `Mapping`, `Any`) + docstring bullet for the new function | **Claimed as-is** (docstring bullet reworded in revision 2 for the wiring-state update). |
| Tests: `test_tracks_from_payload_none_and_empty`, `_parses_runtime_shape`, `_feeds_occupancy_cost`, `_caps_at_default_max` | **Claimed as-is.** Correct, useful pins (runtime payload shape mirror included). |
| Tests: `test_tracks_from_payload_rejects_malformed` | **Claimed with fixes.** Three assertions pinned `TypeError` — contradicting both the module's documented contract and SB-3; re-pinned to `ValueError` and extended with the bool-`max_tracks` case. |

Nothing in the extensions was removed as wrong; the net defect was the
TypeError contract drift, now fixed and pinned. Ownership of these lines is
hereby claimed by this card — they are covered by its tests and this
record. (The *wiring* files — `pipeline.py`, `approach.py`,
`tests/test_approach_traffic_wiring.py` — are Opus-lane per the
arbitration's ownership ruling and are not claimed here; I verified only
that my API changes are additive keyword-only and that those tests stay
green: 65 passed combined.)
