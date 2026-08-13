# Production-boundary design spike

This directory makes the proposed authority contracts executable before any
production code is migrated. It is deliberately outside `src/parcel_robot` and
does not alter the simulator, navigation, voice, or hardware path.

Run from the repository root:

```bash
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
```

**Revision 2 (2026-08-12, card S-1).** The Fable audit
([../FABLE_VERDICT.md](../FABLE_VERDICT.md), RC-1) proved revision 1 claimed
more than it enforced: a prior-boot-epoch lease authorized motion, `NaN` in any
clock made every expiry comparison false and so authorized instead of holding,
`LATCHED_STOP` was a stateless enum label, and 12 of 20 invariant-killing
mutants survived the suite. Revision 2 closes those, plus RC-2 (the terminal
witness now carries a localization-uncertainty reserve) and N-1..N-4. The
mutant-by-mutant record is in
[../../task_2/S1_STATUS.md](../../task_2/S1_STATUS.md).

The tests challenge typed evidence provenance, host-monotonic freshness,
task/evidence revisions, single-writer leases, **gateway boot epochs and
restart-disarm**, **latch persistence and operator clearing**, platform
capabilities, owner identity ambiguity, **bounded in-place search evidence**,
behavior resource ownership, terminal witnesses **including the pose-error
reserve**, **fail-closed handling of malformed time**, and monotone safety
composition.

The seeded corruption campaign is **200 draws over 54 single-fault corruption
classes** — evidence stream, decision clock, task, lease/boot-epoch, gateway
latch state, capability, owner identity, in-place search, speed envelope,
terminal witness and behavior payloads. Every class is additionally exercised
once deterministically, by name, so the campaign's coverage is a stated list
rather than a draw count. (Revision 1 described this as a "200-case corruption
campaign"; the audit showed it was 200 draws over 12 evidence-only classes,
which is why the count is now spelled out here and asserted in the suite.)

## What this does not prove

It proves only that this small reference model has the stated properties. In
particular it does **not** prove:

- that Parcel's current runtime implements any of them;
- that DDS, ROS, or a vendor controller stops a physical robot;
- that perception is correct, or that the system is safe for public-space
  autonomy;
- **that the latch survives a process restart or a power cycle** — the latch
  here is in-process state on one object. A product latch must persist across
  restarts and be observable and clearable by an operator through a real
  interface;
- **that the boot epoch is unforgeable** — `epoch` is an integer counter, not a
  signed or attested boot token, and nothing here models epoch distribution;
- **that the speed envelope is the right envelope** — `speed_envelope_verdict`
  is magnitude-only. It deliberately does not model directional or closing
  relevance, which is the wedge class backlog B6 measured on the product brake
  (RC-3). Reading a CLAMP here as evidence about that class would be wrong;
- **that arrival is fixed** — the RC-2 reserve is a *contract* rule with a
  caller-supplied multiplier and no hazard derivation. The product arrival
  predicate remains owner-gated under backlog B5's 2x2; the B5 fixture in the
  suite shows only that this contract refuses the episode the product accepted;
- that any threshold used in the tests is a product constant. Every threshold
  in the model is a required argument precisely so that none of them can be
  inherited by accident; the values in `test_contracts.py` are illustrative and
  carry no hazard or ODD derivation;
- that mutation kill counts measure the product. They measure this suite
  against this model.

## Product obligations this spike does NOT discharge

These belong to W0-F (and the plan's required-test list), not here:

1. Restart-disarm on the real gateway: a lease minted before a gateway restart
   must be refused by the running process, proven on the product path.
2. Latch persistence across a process restart, with an operator-facing clear
   that requires the same stationary-feedback evidence.
3. The composed physical-translation pipeline (`authorize_motion`'s job here)
   must be the only path to a physical command in the product, with no bypass.
4. Fresh 360-degree collision evidence for bounded in-place search on the real
   sensor set.
5. The pose-reserve arrival regression on B5's measured episode, and the
   bearing-relevance brake regression on B6's — both owner-gated product
   changes, named in the plan's required-test list.

Product work must port each accepted invariant, add boundary/integration/HIL
tests, and delete rather than maintain this spike once the canonical
implementation exists.
