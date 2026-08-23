# AWARE-1 — periodic head-turn awareness (wave B — do not start until wave A lands)

**Tier B · Executor: Opus · Verifier: Fable.** Owner directive: the robot
should periodically turn its head to stay aware of surroundings — there may
be people around.

## What to build
1. **R28 input-class × axis table** (one page, `R28_AXIS_TABLE.md` in this
   folder): which input-health classes permit bounded sensing yaw during
   translation-HOLD, which force all-axis latch. Fable ratifies it in
   verification; the awareness behavior must obey it.
2. **Awareness-yaw proposer**: periodic gentle yaw scan when idle/stationary
   (the existing machinery is the template — `patrol/mission.py` emits
   `PatrolCommand(vyaw=…, reason='turn_coverage')`; `value_directed_scan`
   has dwell-yaw). New behavior: outside patrol, on an idle cadence
   (configurable period), propose a bounded yaw sweep; it goes through the
   NORMAL proposal/arbitration/safety path (no new authority); people
   detections during the sweep flow to the existing perception/owner
   tracking unchanged. On hardware today the backend refuses motion — the
   proposal path is still exercised in sim (capability test) and is
   hardware-ready.
3. Wire PROX-1's `set_proximity_context` handoff if PROX-1 recorded one.

## OWNS
`src/parcel_robot/patrol/mission.py` (marked region), a new small proposer
module under `src/parcel_robot/navigation/` or `patrol/`, `runtime.py`
(ONE marked wire-in region `# ---- CARD AWARE-1` — this is the wave's only
runtime.py toucher), `configs/robot.yaml` awareness keys (base),
`tests/test_aware1_head_turn.py`, this folder.

## MUST NOT TOUCH
Safety gates/arbitration internals, `backends/`, `config.py`,
`reactive_safety.py` (PROX-1's), other fences, git.

## Testing policy (owner — binding)
Capability tests only: cadence fires when idle; sweep is bounded and obeys
the R28 table (a HOLD input-class that forbids yaw suppresses the sweep);
proposal is refused cleanly when motion is refused. Short STATUS md.

## Execution rules
Guard wrapper `--label aware1`, `env -u TMPDIR`, no `-n auto`, no `--tier`,
no `noqa`, ruff clean, owner's stack untouched, no commit/push.

## Addendum (integrator, post-wave-A): the wave's runtime.py wire-ins are yours

AWARE-1 is the only card allowed in `runtime.py` this wave, so it carries all
three wire-ins, each a small marked region (or one region if adjacent):

4. **PROX-1 wire-in**: `set_proximity_context` / profile application at the
   `ReactiveSafetyPolicy(...)` construction — the handoff shape is in
   scrum/20260823/task_2/PROX1_STATUS.md (verified: runtime.py:1763 is the
   construction site; `apply_to` preserves extra fields; 5 read sites).
   Context source: venue mapping (`proximity_context_for_venue`) at build;
   the setter stays reachable for a later reasoning-model tool.
5. **SENSE-1 pose-seam wire-in**: compose/read `CommissionedPoseSource`
   (core/input_health.py:487-684) in the dispatch-health join the way
   CommissionedScanSource is read (the HW-2 region ~runtime.py:13825) — the
   handoff shape is in scrum/20260823/task_3/SENSE1_STATUS.md. After wiring,
   update hw2's `test_b3` to the new (correct) behavior if it measures the
   old pose path — name the pin update in your STATUS.
6. Regenerate `CODEBASE_INDEX.md` is NOT yours — integrator does it at close.
