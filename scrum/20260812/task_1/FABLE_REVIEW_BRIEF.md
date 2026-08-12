# Fable review brief

## Decision requested

Audit `PRODUCTION_COMPANION_PLAN.md` and return exactly one disposition:

- `ACCEPT_ITERATION_3_AND_WAVE_0`
- `ACCEPT_WITH_REQUIRED_CHANGES`
- `REJECT`

If conditional, list every blocking change, its owner, a falsifiable test, and whether
the contract spike or product code must change. Do not approve prose that is not backed
by an executable or future evidence gate.

## Scope of this Sol task

New review-only artifacts:

- `PRODUCTION_COMPANION_PLAN.md` — recommendation, architecture iterations,
  contracts, algorithms, implementation waves, and promotion gates.
- `RESEARCH_LEDGER.md` — primary/official sources and local measured evidence.
- `design_spike/contracts.py` — isolated executable authority model.
- `design_spike/test_contracts.py` — 43 tests plus a seeded 200-corruption campaign.

No file below `src/`, `configs/`, `evals/`, `tests/`, or `scripts/` is owned or changed by
this task. The existing dirty tree includes the independent route-memory/pose-drift
batch under `scrum/20260811/task_2`; do not attribute those changes to this design.

## Candidate decision

Keep Python Parcel for conversation/typed tasks/behavior/global semantics; use ROS 2
selectively for sensors, transforms, SLAM, bags, and navigation components; isolate
Unitree DDS/lease/Sport command in a native sole-writer gateway with a local watchdog.
Models produce proposals. Typed evidence, task revisions, owner belief, capabilities,
and a monotone safety governor authorize short-lived commands.

## Known blockers the plan must actually close

1. Physical `UnitreeSportStateSource` is discarded by current runtime wiring.
2. Physical/sim evidence is inferred from unsafe source strings.
3. Commissioning cannot bootstrap without pre-claiming commissioning.
4. No product hardware launcher, physical camera/LiDAR adapter, or SLAM provider.
5. No real owner identity/re-ID path; simulator owner IDs hide the problem.
6. No trustworthy audible-output/full-duplex evidence on this desktop.
7. No independent physical software stop; Unitree remote behavior still needs exact
   firmware commissioning.
8. No production power/thermal, security, update, privacy, or long-soak evidence.

## Invariants to attack

- only one process can write motion;
- every nonzero command has a current task/evidence/capability/session/TTL;
- simulator, replay, and unknown evidence cannot authorize physical translation;
- the receiver uses its own steady clock for expiry;
- missing geometry/localization/feedback holds; malformed provenance/frame latches;
- owner ambiguity never becomes nearest-person following;
- semantic arrival is fresh evidence plus relation plus settled feedback;
- safety decisions only become more restrictive downstream;
- emergency stop bypasses language, model, smoothing, logging, and ROS;
- process restart is disarmed and cannot resume prior work;
- no simulator/external-eval score is represented as physical/public safety.

## Adversarial questions

1. Is a Unix sidecar actually independent enough, or does public-product scope require
   a separate MCU/appliance in Wave 0 rather than later?
2. Is any important motion/safety state duplicated with contradictory owners?
3. Does selective ROS create an unmodeled second `cmd_vel`/Sport writer?
4. Can a source clock packet replay arrive “fresh” at the gateway? What additional
   source/session/sequence validation is required?
5. Can a task be owner-authorized while the speaker/owner identity is uncertain?
6. Does the owner state machine permit safe in-place search without fresh 360-degree
   collision evidence?
7. Are proposed latency gates compatible with the current 350 ms TTL and physical
   stopping distance, or must Wave 0 explicitly retune them?
8. Does the route graph encourage blindly replaying an obsolete city route?
9. Does the TTS/audio plan preserve AEC reference, actual presentation truth, and
   privacy under simultaneous navigation load?
10. Are model tournaments large and independent enough to prevent evaluator drift or
    prompt overfitting?
11. Which acceptance targets are arbitrary and need a hazard/ODD-derived value before
    implementation?
12. What concrete evidence would cause the team to abandon Unitree Sport, the selected
    LIO, RPP, or the hybrid architecture?

## Reproduce

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
.parcel/bin/python scripts/ci_gate.py --tier commit --json
git diff --check
```

Expected design-spike result at handoff: `43 passed`. A pass proves only the reference
model. Require canonical product, process-fault, replay, simulator, HIL, and physical
evidence at the corresponding promotion rungs.

## Review output template

```text
VERDICT:
BLOCKING FINDINGS:
NON-BLOCKING FINDINGS:
CONTRACTS ACCEPTED:
CONTRACTS REJECTED/REVISED:
MISSING FAILURE CASES:
REQUIRED TESTS:
WAVE 0 OWNERSHIP/CONFLICTS:
CLAIMS THAT MUST BE DOWNGRADED:
NEXT GO/NO-GO GATE:
```
