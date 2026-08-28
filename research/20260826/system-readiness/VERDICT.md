# System-readiness verdict

Date: 2026-08-26

## Decision

**Do not mount or arm the current software for physical motion.** A supervised,
mechanically secured, stationary Stage-0 capture may be prepared only under a
separate signed runbook with Sport disabled and an independent remote stop.

| surface | verdict |
|---|---|
| Desktop research and deterministic replay | Proceed |
| Current `si-companion-v5` relationship/data contract | Accept deterministic render/freeze/parity and local admission hardening; no model/realtime behavior evidence |
| Local-only research summary spool prototype | Proceed as an isolated development pilot |
| Stationary, supervised, zero-motion Stage 0 | Conditional; not yet executed |
| Stand pulse, translation, autonomous navigation, Follow, stairs | **NO-GO** |
| Proactive speech or autonomous approach/search | **Default off** |
| Conversation release | **NO-GO** |

## Why

The bench motion seam is valuable, but the product runtime still does not
compose it into a sole Unitree writer and `--sport vendor` still refuses. A
selectable observation-only Go2 backend exists but is uncommissioned and
untested: NIC/extrinsics are unmeasured, pose is odometry rather than
commissioned MAP/LIO, owner perception is absent, and every motion-producing
method refuses. No Orin service, mounted audio, real localization, independent stop,
or stopping envelope has been demonstrated.

Quality is also below any reasonable promotion floor: NAV_INSTRUCT is 0.20 SR
and 0.1348 SPL with a false arrival; unseen scenes have 16 false arrivals;
walk-with-me is 5/10; social yield contacts a simulated person; fresh planning
is 3/5; personal conversation is 3/13; and mounted acoustics are absent.

## Carry-forward findings

- Implement a versioned `CapabilityManifestV1` and typed
  `EmbodimentEnvelopeV1`; 8/9 personality affect mappings currently name a
  gesture absent from the effective Go2 realtime enum.
- Implement typed `PlannerOutcome` liveness budgets over explicit planner
  states, then test the post-hoc `{no_path, goal_blocked}` result on an
  untouched dynamic holdout.
- Keep translation and completion authority latched after localization
  discontinuity, but do not integrate the current identity-witness candidate:
  its 360-case follow-up blocked 120/120 alias false arrivals yet missed the
  nominal-recall gate at 116/120. H2b must separately verify place identity,
  a new pose epoch/residual-consistent reset, and conservative target-relative
  terminal geometry.
- Keep fake Sport as the gateway-lifecycle tier and retain the integrated
  official Go2 MJCF assets. Then integrate the native Unitree MuJoCo
  low-level SDK2/DDS simulator boundary through a simulated `SportPort` or
  explicit high-level controller bridge; train articulated terrain policies
  later in Unitree RL/Isaac Lab and keep semantic/social simulators as a
  second wave.
- Keep research data isolated and summary-first. No learned candidate promotes
  itself; immutable data, lineage, frozen evals, human review, signatures, and
  rollback remain mandatory.

The detailed promotion ladder and next task are in `../MOUNT_READINESS.md` and
`../../../scrum/20260826/task_1/README.md`.
