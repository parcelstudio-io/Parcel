# EMBODIMENT-KERNEL — Go2 now, custom body later · DESIGN (Codex) · 2026-08-24

## Hypothesis

Parcel's existing controller and body-intent seams isolate vendor-specific
actuation well enough to become the nucleus of a portable **Embodiment
Kernel**, but its observation and deployment seams do not yet isolate the
physical body. Specifically:

- direct Unitree SDK imports should be confined to Unitree adapters;
- high-level cognition/memory/conversation packages should not depend on a
  Unitree type;
- navigation and safety should consume a body-neutral stamped observation,
  not `SimObservation`;
- a second controller and body-intent adapter should pass the existing
  portability tests without edits to brain/navigation code;
- the target deployment should own explicit services for motion gateway,
  supervisory runtime, sensing/localization, audio and perception.

The expected verdict is **partially confirmed**: actuation is portable, while
observation assembly and deployment are refuted. The purpose is to measure
the boundary and turn it into a concrete design, not to produce a favorable
score.

## Rationale

H4 proved `BodyIntentV1` against one fake custom body, and H7 proved a
body-neutral localization provider in a harness. That does not establish
whole-product portability: `RobotRuntime`, Follow, SearchOwner, reactive
safety and spatial behavior still mention a carrier named `SimObservation`,
and the deployment tree describes itself as desktop-only. A static audit is
the cheapest refuter before committing the M1 architecture.

## Experiment

`audit.py` performs an AST/lexical audit over `src/parcel_robot` and the
deployment tree. It records:

1. imports containing `unitree_sdk2` outside the allowed Unitree adapter
   files;
2. executable high-level references to names containing `Go2` or `Unitree`;
3. modules outside backends/simulation that import or annotate
   `SimObservation`;
4. whether the proposed replacement `NavigationSnapshotV2` exists;
5. target service files and whether the deploy README still disclaims an
   Orin/aarch64 artifact.

It then runs the existing focused portability evidence through the mandated
test guard; no product code is edited.

## Measurements and bars

| row | measurement | bar |
|---|---|---|
| K1 | direct vendor-SDK imports outside allowed adapters | 0 |
| K2 | executable Go2/Unitree references in brain, memory, realtime, attention | 0 |
| K3 | non-backend/non-simulation modules coupled to `SimObservation` | 0 (expected refuter) |
| K4 | `NavigationSnapshotV2` body-neutral carrier exists | yes (expected refuter) |
| K5 | focused controller/body portability tests | all pass |
| K6 | target services: gateway, supervisor, sensing/localization, audio, perception | all explicitly owned (expected refuter) |

## Decision rule

K1/K2/K5 passing permits reuse of `LocomotionController`, `RobotStateSource`,
`ControlManager`, `BodyIntentV1` and the capability manifest. Any K3/K4 miss
makes a stamped observation spine a precondition for Follow/navigation on
hardware. A K6 miss creates an explicit target-deployment card before first
physical motion. Stop after this audit; implementation belongs to M1 cards.

## Evidence tier and limits

`static product audit + focused desktop tests`. This proves neither physical
behavior nor that a future whole-body controller implements the contracts.
String/reference counts are coupling indicators, not a semantic proof.

## OWNS

Only `research/20260824/embodiment-kernel-portability/**`. Product and deploy
trees are read-only.

