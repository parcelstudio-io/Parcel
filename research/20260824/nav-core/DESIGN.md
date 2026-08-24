# NAV-CORE — known-place navigation without the oracle · DESIGN (Fable) · 2026-08-24

## The one decision (RTP-1 C5; owner strategy: converge fast, early-exit)
For Milestone 1, does Parcel **(a) retain** its current navigator
(`DirectiveNavigator` + grid_v1) as-is, **(b) simplify** M1 navigation to
metric point-goals (grid planner + arrival check, bypassing semantic
resolution), or **(c) delegate** to an external navigation subsystem? Stop
the study the moment the choice is unambiguous; do not tune past it.

## Hypothesis (falsifiable)
Under **physical-shaped inputs** — `DriftingOdomProvider(calibrated_go2)`
instead of truth pose, detector-shaped semantic evidence with dropouts
instead of oracle IDs/polygons, scan from the LiDAR band with injected gaps —
the retained navigator reaches a **known** place goal in one room with
arrival ≥ 0.80 at ≤ 0.5 m, 0 false arrivals, 0 contacts, and 100 % typed
honest failures on the remainder. (The recorded v4 baseline is SR 0.24–0.28
over 25 city-scale episodes with oracle semantics — the room-scale,
known-place case has never been measured separately.)

## Experiment
1. **Corpus**: one-room world (8×8 m, 6 known places pre-registered in the
   learned map, 4 obstacle layouts), 20 episodes × 3 seeds per arm:
   `final transcript → validated NavigateTo(known place) → planner/controller
   → arrival verification | typed failure`. Transcripts through the REAL
   door (`_realtime_navigate` replay rails), not synthetic goals.
2. **Input shaping** (the point of the study): pose = `calibrated_go2`
   drift (MAP re-anchor allowed at the H7 contract's health semantics);
   semantics = the learned map queried with detector-shaped noise (drop
   p=0.2 per re-detection, position jitter σ=0.15 m, no `associated_lidar_ids`
   identity matching, no exact polygons — arrival verified by the metric
   band + detector confirmation only); scan = planar band with one 2 s
   dropout injected per episode.
3. **Arms**: A retained navigator (full semantic ladder); B simplified
   (metric point-goal: grid planner + chance-constrained arrival at the
   place's stored coordinate, semantic resolution bypassed); C only if A
   and B both fail their bars — a scoping note on delegation (Nav2-class),
   not an integration.
4b. **False-healthy refuter (v2, RTP-2 F3/A4/A10)** — one wrong-place
   episode per seed: kidnap into an aliased corridor mid-episode; the bar is
   that NO motion resumes on HEALTHY alone — re-arm requires the globally
   discriminative relocalization margin or the journaled operator
   pose-reset transaction; a false arrival after the kidnap fails the arm
   outright. Pickup/restart latch disarmed (A10 signal list).
4. **Refuters** (one episode each per seed): scan dropout mid-leg ⇒ HOLD;
   pose DEGRADED ⇒ refusal not arrival; moved obstacle ⇒ replan or typed
   failure; goal place removed from the map ⇒ honest `not_found`-class
   refusal, never a false arrival.

## Measurements (pre-registered)
| row | metric | bar |
|---|---|---|
| N1 | arrival rate at ≤ 0.5 m (arm A / arm B) | ≥ 0.80 either arm |
| N2 | false arrivals | 0 |
| N3 | contacts | 0 |
| N4 | honest-failure typing on non-arrivals | 100 % |
| N5 | median time-to-goal, path/optimal ratio | reported |
| N6 | refuter episodes behave as specified | 4/4 kinds |
| N7 | the A-vs-B delta that justifies the ladder's complexity | reported |

## Decision rule (early exit)
A passes ⇒ **retain** (M1 uses the navigator as-is; H8's probe may follow).
A fails N1/N2 but B passes ⇒ **simplify** for M1 (semantic ladder returns
post-milestone). Both fail ⇒ write the delegation scoping note and stop.
Whatever the outcome, stop at the decision; improvements become M1 cards.

## Evidence tier / does not prove
`desktop-sim` with physical-shaped inputs. Proves the topology choice; does
not prove physical navigation, real perception, or real localization.

## OWNS
`research/20260824/nav-core/**`, `tests/test_navcore_probe.py` (thin).
Must not touch: `navigation/**` product code (measure it; the fix list goes
in RESULTS), `runtime.py`, frozen NAV_INSTRUCT baselines, the owner's stack.
Guard label `navcore`. No GPU model servers needed (detector-shaped noise is
synthetic; the real-detector arm is explicitly out of scope here — H6 owns
detector fidelity).

## Codex cross-review for Fable · 2026-08-24

**UNFINISHED; useful only as an early topology decision.** At this review the
folder has a design and in-progress fixtures, but no canonical RESULTS or
VERDICT. Passing desktop rows would retain a policy shape, not prove a
mountable navigator. The product still feeds navigation through
`SimObservation`, untyped `extras` and truth pose.

Interpret the result only after introducing or explicitly scoping the
stamped observation boundary. Regardless of arm, physical promotion requires
real localization health, obstacle evidence, sole-writer actuation, local
STOP and supervised point-goal trials. Stop at the registered topology
decision as planned; do not turn this into another navigation rewrite.
