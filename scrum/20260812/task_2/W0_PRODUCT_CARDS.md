# Cards W0-A and W0-B — first Wave-0 product cards

Source of truth: `../task_1/PRODUCTION_COMPANION_PLAN.md` §"Wave 0", cards
W0-A / W0-B, as amended by `../task_1/FABLE_VERDICT.md`. Base: commit
`7242660`. Both P0 targets were CONFIRMED by executed audit (verdict
"verified clean" section): the defects are real and exactly where cited.

Shared MUST-NOT-TOUCH: frozen episode definitions/success rules; the B5/B6
owner-gated surfaces (K0 arrival predicate, `apply_collision_brake`,
`collision.py` semantics, their configs); `navigation/**` behavior;
`route_memory/**`; `evals/**`; any physical auto-arm path; low-level joint
control. `runtime.py` is W0-A's exclusively this tranche.

## Card W0-A [opus] — physical feedback and typed provenance (P0-1, P0-2)

The two defects, confirmed at:
- `runtime.py:391-396` — an injected manager's state source is retained only
  via `isinstance(BufferedRobotStateSource)`; a `UnitreeSportStateSource`
  (a plain class, control/unitree_sport.py:74) is discarded, so input-health
  feedback reads (runtime.py:4693, 5700) see nothing from the physical path.
- `core/input_health.py:100-133` — authority inferred from source strings;
  `PHYSICAL_SOURCE_NAMES = {"", "unknown", "physical"}` trusts `unknown` as
  physical while `unitree_sport(_state)` is classified a simulator fixture.

OWNS: `control/base.py`, `control/models.py`, the narrow runtime state-source
wiring, `core/input_health.py`, focused tests (new file + amendments with
provenance).

Implement (from the plan, verbatim intent):
- retain any read-only `RobotStateSource` for `.latest()`;
- a separate simulator-only `ObservationSink.update_observation()` seam;
- typed `EvidenceOrigin` (`PHYSICAL | SIMULATION | REPLAY`) on boundary data;
  remove string inference entirely; `UNKNOWN` is never physical authority;
- preserve vendor/source time, host receipt, session epoch, and sequence;
- missing calibrated geometry = exact hold for physical deployments, with the
  existing simulator default preserved until deliberately migrated.

GATE (from the plan, plus verdict additions):
- physical `unitree_sport` feedback satisfies a commissioned input-health
  join; simulator/replay cannot satisfy physical requirements;
- `unknown`, stale, reordered, future, wrong-frame, invalid data hold/latch
  exactly, each with a seeded-failure companion;
- no missing-scan/geometry path can emit physical translation;
- simulator behavior and frozen evals byte-unmoved (digest evidence, AF-2
  recipe precedent); ci_gate green.

## Card W0-B [opus] — commissioning-only path (P0-3)

The defect, confirmed at `control/factory.py:107-130`: normal construction
requires `enable_lease` / `axes_commissioned` / `state_frame_commissioned` /
`allowed_modes` pre-set, and the commissioning CLI (`unitree_control.py:66`)
calls that same factory — commissioning cannot bootstrap without pre-claiming
commissioning.

OWNS: `control/factory.py`, `unitree_control.py`, new commissioning record
module + tests.

Implement (plan verbatim): an explicitly armed manager permitting one axis,
0.02–0.05 m/s, short TTL/duration, fenced/support-rig instructions, stop
confirmation, and evidence output (`CommissioningRecordV1`-shaped; defaults
fail closed). It cannot enter the autonomous runtime. Normal factory gates
remain untouched.

GATE (plan verbatim):
- commissioning works while flags are false;
- cannot issue multi-axis / autonomous / over-limit / over-duration commands
  (seeded-failure proof each);
- interruption, state loss, process exit, or failed stop ⇒ latched failure;
- only a reviewed evidence record can enable normal configuration;
- no path from this manager into `RobotRuntime`; ci_gate green.

## Audit note (both cards)

The Fable tranche audit will adversarially verify: (a) W0-A's origin typing
cannot be spoofed by string or by omission (UNKNOWN paths), (b) the simulator
seam split leaves the sim path byte-identical, (c) W0-B's manager is
un-enterable from the autonomous runtime under fault interleavings
(kill/restart mid-commissioning), (d) OWNS compliance. Write status docs in
the Wave-1 register (measured claims, does_not_prove, seeded-failure tables).
