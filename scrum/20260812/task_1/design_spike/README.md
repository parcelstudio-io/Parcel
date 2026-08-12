# Production-boundary design spike

This directory makes the proposed authority contracts executable before any
production code is migrated. It is deliberately outside `src/parcel_robot` and
does not alter the simulator, navigation, voice, or hardware path.

Run from the repository root:

```bash
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
```

The tests challenge typed evidence provenance, host-monotonic freshness,
task/evidence revisions, single-writer leases, platform capabilities, owner
identity ambiguity, behavior resource ownership, terminal witnesses, and
monotone safety composition. The seeded 200-case corruption campaign is
repeatable.

This proves only that this small reference model has the stated properties. It
does **not** prove that Parcel's current runtime implements them, that DDS or a
vendor controller stops a physical robot, that perception is correct, or that
the system is safe for public-space autonomy. Product work must port each
accepted invariant, add boundary/integration/HIL tests, and delete rather than
maintain this spike once the canonical implementation exists.
