# NAV-GEN-1 — why does the shipped navigator fail on generated geometry?

Author: Fable (parcel-0e), 2026-08-29 20:2x. Pre-registered before any run.
Evidence tier: `desktop-sim` (headless city on real generated MJCF variants
from `evals.nav_instruct.scene_gen.build_scene`, plus the frozen demo block
as a control). Physical: NO-GO. No product edits; no frozen digest touched;
the NAV evals' held-out scene is never loaded or named.

## Why

MA-1 measured the shipped stack (`DirectiveNavigator` + grid planner +
semantic ladder + reactive safety) at **4.5 % strict success / 65 % band
entry** on 600 held-out generated layouts. That number is the binding
constraint on everything the owner asked for, and it has no attribution:
grounding, planning clearance, or termination? NAV-CORE (08-24) found three
uncoordinated clearance authorities (planner 0.42 m vs brakes 0.75/0.80 m;
`map_safety_margin_m` 0.45 recovered stalls); NAV-QUALITY found the
`semantic_target_unreachable` class on "sit next to the bench" at the
commissioned inflation. This probe asks whether the generated-geometry gap is
the same class.

## Hypotheses (falsifiable)

**H-NG1a (it is termination/clearance, not grounding).** On ≥ 300 episodes
(≥ 30 generated scenes × the five demonstrable targets × ≥ 2 start poses),
≥ 70 % of strict failures end with the robot inside 2× the goal band or with
`reason ∈ {semantic_target_unreachable, goal_blocked, arrival verification
failed}`, and < 15 % end with a grounding failure
(`directive_not_understood`, no candidate, wrong instance). Refuted if
grounding failures ≥ 30 %.

**H-NG1b (clearance is the lever).** Sweeping the navigation config's
clearance parameters (the map safety margin and planner inflation as the
config store exposes them; ≥ 4 values from the commissioned value down to
0.20 m, plus the reactive-safety stop/slow bands held fixed) raises strict
success on the same episodes by ≥ 20 points absolute at some value **without
raising the collision count above 0** and without lowering minimum clearance
below the stop band. Refuted if no value gains ≥ 10 points at zero
collisions.

**H-NG1c (the frozen block is not special).** On the frozen demo block the
same recipe reproduces the known per-target rates (sidewalk ≈ 0.75, lamppost
≈ 0.6, bench ≈ 0.0 from MA-1's pre-generation probe) within ± 0.15, so the
generated scenes' 4.5 % is a geometry effect, not a harness effect.

## Measurements
Per episode: status, reason, terminal_relation, DTG, inside-band (strict and
2× band), minimum vs required clearance, collision count, path length,
steps, semantic_scan_steps; per scene: obstacle density and the goal's
nearest-obstacle distance. Reason histogram; success vs clearance value;
Wilson CIs.

## Success criteria
a, b, c as stated; each verdicted separately.

## OWNS
`research/20260829/nav-gen-attribution-1/**`, scratch `~/.cache/parcel-0e/ng1/`.
Reads MA-1's `teacher.py` for the scene recipe (read-only; import by path is
fine), `simulation/headless_city.py`, navigation config loaders. CPU only,
≤ 48 threads. `.parcel/bin/python`.

## Reproduction
`.parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --all --seed 20260829`
