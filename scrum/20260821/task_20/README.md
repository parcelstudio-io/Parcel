# Task 20 — MOVE-1: why doesn't the dog move? (E2-D2 + the patrol driver)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** E2_STATUS.md §4 (E2-D2, highest priority: "nothing downstream
of it can be measured until it is answered"), §6 (the dependency-ordered
re-dispatch list this card unblocks); C2_STATUS §5 (pose moved 0.1339 →
0.1674 m across the retained frames while 160/160 motion requests were
ACCEPTED); C1_STATUS §8 (C-1 explicitly disclaims patrol fitness).
**DISPATCH GATE: none — dispatches on the chain audit. Chain-contract v2
applies (quiescence via git status + content hashes with
positive-attribution waiver; last act is returning; predecessor missing ⇒
HALT).**

## Work

1. **Diagnose E2-D2 before building anything.** 160/160 accepted motions
   produced ~3.35 cm of displacement in C-1's live cell. Instrument the
   actual path: what did the 160 accepted requests COMMAND (hold-position?
   zero-velocity? real waypoints?), what did the simulator execute, where
   does acceptance diverge from displacement. The answer is a measured
   attribution — "C-1's harness never commanded displacement" and "the
   locomotion path drops commands" are different worlds; do not guess.
   Pre-register the discriminating measurement first.
2. **Then the patrol driver, the capability E-2 §6 item 1 names:** a
   bounded exploration patrol that MOVES the robot through a scene while
   the camera→detector→map loop runs (C-1's stream consumed as the
   diagnostic stream it is; its freshness limitation is a known input, not
   this card's to fix). Deliverable: a mission runner invocable per-scene
   with a fixed time budget, producing a path trace + map-growth record.
3. **E2-D3 inside the same card:** the patrol's detector query vocabulary
   under T1 (no sidecar by design). Options research is done — pick the
   design the cutover research supports (OmDet async seat's open-vocab
   sweep for map building; owner-corpus nouns for in-loop), pre-register
   it, measure yield in the dev scene.
4. **Acceptance (pre-register exact numbers before running):** the
   diagnosis names the displacement mechanism with evidence; the patrol
   moves the robot ≥ a pre-registered path length in the dev scene within
   the budget; the map ends with ≥ a pre-registered entry count with
   per-entry provenance; zero hard-safety violations (collision count 0).
5. Standard house rules: seeds RED for new logic, deviations declared,
   failures as failures, owner store untouched, no git commits.

OWNS: the mission-runner module (new file(s) under src/parcel_robot/), its
tests, task_20 docs/evidence. MUST NOT TOUCH: perception_abstention.py,
online_map/ internals (consume its public API), frozen evals/, scenes/
digests, the held-out scene.

## Definition of done

E2-D2 has a measured answer in MOVE1_STATUS.md; the patrol runs in the dev
scene inside its budget with the pre-registered numbers met or missed
honestly; gate green after; standard register with seeds.
