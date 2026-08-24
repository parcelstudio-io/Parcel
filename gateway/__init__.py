"""M1-0 — the co-located final governor + sole-writer gateway process.

This package is deliberately a **top-level tree beside** ``src/``, not a
module inside ``parcel_robot``.  On the dog it runs as its own systemd unit in
its own vendor interpreter (``pyproject.toml`` floor ``>=3.10``; the Orin's
JetPack CPython is 3.10), holding the one robot-network credential and the one
vendor command writer.  ``src/parcel_robot`` is the *product* side of the seam
and is not imported here — the deployable modules of this package import
exactly one thing from it, the frozen wire contract
``parcel_robot.bridge.protocol``, which is pure stdlib and is what both sides
must agree on.  ``tests/test_m1_0_gateway.py`` pins that import surface.

Design record, in the order it binds:

* ``docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md`` §8.8 — the final
  safety governor's disposition lattice and the native sole-writer gateway's
  duty list (boot epoch, restart-disarmed, one authenticated lease, monotonic
  sequence, short TTL + watchdog, local caps, allowlisted action catalog, stop
  dominance, fresh feedback + stationary witness, bounded audit ring).
* ``scrum/20260823/task_1/FABLE_VERDICT.md`` X12 — governor and gateway are
  **co-located in one process** for the prototype: one clamp owner (the
  governor), the writer module veto-only (may reject or zero, never originate
  or increase).
* ``scrum/20260824/task_2/CLAUDE_RESPONSE.md`` — the ``gateway/governor`` row
  of the stage/hazard table: bench witness = fake-Sport suite green with
  exact-zero on kill/stale/epoch; refuter = the seeded fault inventory; any
  non-zero on a loss class stops the program.

**What this package is not.** It is not a Unitree SDK client: no vendor SDK is
imported anywhere in this tree, and the vendor is reached only through the
structural :class:`gateway.ports.SportPort`.  It is not wired to
``RobotRuntime`` — that is a later card.  A bench run against
``parcel_robot.bridge.fake_sport`` proves contract and fault behaviour on a
desktop; it proves nothing about a robot, a vendor firmware, braking distance,
or scheduling on the Orin.
"""
