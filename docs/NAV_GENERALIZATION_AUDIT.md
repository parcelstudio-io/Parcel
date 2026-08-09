# Navigation generalization audit — how much is hardcoded?

**Date:** 2026-08-06 · **Method:** 4-auditor workflow (`wf_9cdc754a-d83`):
motion/planning, semantics/directives, full parameter census, and a
5-scenario generalization stress test. 127 findings with file:line
evidence; census over 30 files / ~15.7k lines.

## Headline

**The architecture is general; the content is hardcoded.** Mechanisms —
rolling occupancy grid, A*, GoalRegion algebra, frustum→memory grounding,
recovery state machines, the model registry / proposer bus / noise-adapter
/ profile seams — are scene- and label-agnostic. What is baked is the
*content* those mechanisms run on: one scene's vocabulary, one robot's
scale constant, one speed regime's tuning, and an oracle perception
contract.

**Parameter census (~335 meaningful tuned constants):**

| Class | Share |
|---|---|
| YAML-config-exposed | **~43%** (145) — grid.yaml controller block, default.yaml safety/watchdog, FollowConfig/SearchOwnerConfig with fail-closed unknown-key rejection |
| Code-baked named constants | ~27% (90) — scoring bands, log-odds, grounding thresholds, recovery/scan/search defaults |
| Code-baked inline literals | ~29% (96) — stub brakes, frontier numbers, TTC person gates, clearances, wedge angles |
| RobotProfile-derived | **~1%** (4) — the profile exists but almost nothing in navigation reads it |

## What is genuinely general today

- **The geometric core**: robot-centered 16.1 m rolling log-odds grid
  (no world bounds, sensor-only evidence), 8-connected A*, explicit
  LaserScan contract from observation extras, loud degradation when the
  scan is missing, reactive/TTC gates, watchdog/terminal machinery.
- **The config seam quality where it exists**: the ModelRegistry passes
  the whole YAML controller block as constructor kwargs; a speed-regime or
  map-scale change in the *primary* controller is a YAML exercise.
- **The grounding/recovery state machines**: outcomes, scan→frontier→
  honest-refusal control flow, memory, relations solvers, K0 single
  arrival authority — all label-agnostic.

## The five hardcoded strata (worst first)

1. **No localization exists.** `observation.position` is MuJoCo ground
   truth; world-frame goals (POIs, semantic memory, K0 regions) presume a
   globally consistent pose that no component provides. The biggest
   single sim-to-real gap (already HR-ledger'd) and it is architectural,
   not a constant.
2. **Oracle perception assumptions on the mission path.** Fatal for real
   sensors: relational-goal verification keys on
   `associated_lidar_ids` == candidate ID (no real stack provides this);
   exact polygons as arrival authority; 0.98 confidence + deterministic
   re-detection assumed by memory ingest; absence-of-detection treated as
   absence-of-object. The DetectionMsg noise-adapter chain exists but
   **nothing on the mission path consumes it** — runtime and headless
   feed the navigator oracle semantics directly.
3. **Closed vocabulary, three-deep.** New object class ("fire hydrant") =
   ~4 code files + scene + eval landmark tables (prefix table, alias
   table, label if-chains, `_instance_id` — which hardcodes `bench_1`
   and merges all benches in any richer scene). New relation ("between")
   = ~8 closed enum surfaces with no registry. New *phrasing* mostly
   works ("head over to the sidewalk" parses), but truly novel verbs are
   gated out of BOTH lanes — the deterministic grammar and the LLM lane's
   `_PHYSICAL_CUE` verb regex. The "open-vocabulary" SigLIP path is a
   stub degrading to substring match.
4. **Off-primary-path tuning is code-baked.** The frontier search crawls
   at a hardcoded 0.22 m/s with hardcoded 6 m ring geometry; scan-approach
   gains, stub-fallback brakes, TTC person gates (0.8/1.8 s), waypoint
   speed-shaping floors, watchdog epsilon — all invisible to YAML. Proven
   consequence: both speed raises (2026-08-04, -05) missed these paths.
5. **Embodiment scale is one literal.** `ROBOT_FOOTPRINT_RADIUS_M = 0.32`
   in geometry.py is imported by planner, pipeline, scoring, and
   city_semantics; `RobotProfile.footprint_radius_m` never reaches them.
   A second inconsistent radius (0.35, TTC) coexists. The lamppost
   stand-off 1.32 embeds the 0.32 by value.

## The most dangerous pattern: 12 drift-capable duplicated families

Proximity envelopes (**6 copies — one drift already live**: 1.25 vs
1.2 m), arrival radii (7 definitions — the K0 unification covered the
scorer chain, not all consumers), robot radius (5 sites, two values),
frontier probe quadruple (4 copies), dynamic-agent Gaussian params (4+1
divergent), front-wedge 1.15 rad (5), oracle confidence 0.98 (4+), align
hysteresis (4 loops — only one retuned in the speed fix), scan height,
the "12 m world" range (4 independent 12.0s), viewpoint-memory caps,
lidar `[:64]` caps. This is the D5/U31 defect class as a standing
inventory.

## Stress test: what breaks first, with effort

| Scenario | Works unchanged | Breaks first | Effort |
|---|---|---|---|
| Indoor apartment scene | entire geometric core, recovery machinery, relations, memory | `_REGION_WORDS` (kitchen/bedroom parse as objects → every directive UNSEEN→refusal); prefix/alias tables; `bench_1`; sidewalk-labeled support lookup | ~1–2 wk to make vocab scene-metadata-driven |
| 100×100 m city | rolling grid, A*, dynamic layer | frontier bounded to ~6 m rings + 300 steps (cross-block search impossible); 12 m sensor caps; watchdog sized "for this block"; memory 4096 cells | days config + ~1 wk real frontier exploration |
| Half-size robot | gait/kinematics via profile | nothing crashes — it navigates with 2× conservative inflation and Go2-sized arrival bands (0.32 everywhere) | 2–4 days plumbing profile→planner/scoring |
| Real perception | adapter chain (built, unwired) | lidar-ID association (fatal), exact-polygon verification, FP handling | days wire + 1–2 wk geometric association + 2–4 wk robustness |
| Learned goal proposer | SE2Goal contract, arbitration, route_memory proposers | **ProposerBus is never polled on the mission path**; DirectiveNavigator has no external-goal mission type | 2–4 days + safety review |

Three key seams stop **one wire short** of the component they serve:
perception adapter → mission path, ProposerBus → DirectiveNavigator,
RobotProfile → planner/scoring.

## Recommended consolidation (mechanical, not redesign)

1. **One `SafetyEnvelope` + `SpeedRegime` authority** injected everywhere
   — kills the worst duplicated families and makes the next speed raise a
   one-place change.
2. Route the ~15 highest-consequence baked numbers (TTC gates, log-odds,
   grounding threshold, search speeds, frontier quadruple) through the
   existing `from_mapping` config pattern.
3. Derive every 0.32/0.35/0.45 from `RobotProfile` by reference.
4. Regenerate eval landmark tables from `extract_city_semantics` instead
   of hand-transcription (any scene edit currently corrupts goals
   silently).
5. Close the three one-wire-short seams when their cards come up (real
   perception is Phase-1 Track B; proposer polling is the P4 A/B lane).

Bottom line: **~43% of tuning is properly externalized, ~1% scales with
the robot, and the rest is baked — but almost all of it is content
behind genuinely general mechanisms.** The system is exactly what it was
asked to be (deliberately bare, hillclimbable, with real seams); the
hardcoding is concentrated where the roadmap already plans replacements
(perception, vocabulary, localization), plus one cheap consolidation pass
that would remove the drift-family risk.
