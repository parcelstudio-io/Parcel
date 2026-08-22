# Task 12 — P1-E: the social zone is a config, not a constant

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Evidence:** P0-A's pinned blocker
(`scrum/20260822/task_1/P0A_STATUS.md`): `safety.person_stop_m: 0.7` from the
prototype overlay refuses to boot because
`authority.SafetyEnvelope.person_social_zone_m` is hardcoded to 1.2 and
`navigation/reactive_safety.py` floors on it; parcel-74's independent
verification note (Wave P0 verification, same folder) carries the minimal
change. Audit §6 / §11 item 12 (planner and gate disagree on the envelope).

## Why
E2-D2 in a new costume: the dog stopped at 0.31 m of forward travel because
the owner stood inside the 1.2 m wedge; in an apartment the owner is ALWAYS
inside 1.2 m. A companion that cannot come to you is not semi-autonomous. The
P0 ruling already says reactive-safety *distances are config and may move*;
the *semantics* (the gate, TTLs, the e-stop latch, `finalize_command`) do not.

## Work
1. **Derive, don't hardcode:** `SafetyEnvelope.person_social_zone_m` comes
   from config (`safety.person_stop_m`), with a **hard floor that is itself a
   named constant at the commissioning band** (the value the Go2's real
   commissioning record will pin; pick it from the audit's hardware section
   and say why). Below the floor ⇒ refuse to boot with the floor named in the
   message — that refusal is the safety core and stays.
2. **One number, two consumers:** grid-planner inflation derives from the same
   envelope quantity so the planner stops choosing corridors the gate refuses
   (audit §6). Pre-register the before/after on the three dev-scene corridors
   the audit names.
3. **Overlay lands the prototype value** (`configs/robot.prototype.yaml`,
   P0-A's mechanism): indoor 0.7 m; shipped `robot.yaml` unchanged, digest
   unchanged.
4. **Seeds RED:** floor removed; planner inflation decoupled from the
   envelope; overlay value below the floor boots.
5. **Measure it where it bit:** re-run MOVE-1's patrol harness
   (`scrum/20260821/task_20/evidence/`, the owner-standoff arm) with the
   prototype overlay — net displacement must clear the standoff wedge with
   zero robot-initiated contact (pre-register the number).

## Proves
With the prototype profile the dog approaches to 0.7 m of a person and stops
there; below the floor the system refuses to boot; the planner and the gate
agree on one envelope.

OWNS: `authority.py` (`SafetyEnvelope` derivation + floor constant),
`navigation/reactive_safety.py` (distance SOURCE only — not the gate logic),
`navigation/grid_planner.py` inflation derivation, `configs/robot.prototype.yaml`
`safety` block, `tests/test_p1e_*.py`, `task_12/` docs.
MUST NOT TOUCH: `core/hard_stop.finalize_command`, e-stop latch, TTLs/watchdog,
`SafetySupervisor.validate`, any other card's OWNS.

## Definition of done
Pre-registered rows measured including the MOVE-1 re-run; three seeds RED;
`P1E_STATUS.md`; the verifier's independent read confirms the semantics diff
is empty (only the distance source and the floor moved).
