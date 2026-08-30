"""M1-0 — the co-located final governor + autonomous sole-writer gateway.

This package is deliberately a **top-level tree beside** ``src/``, not a
module inside ``parcel_robot``.  On the dog it runs as its own systemd unit in
its own vendor interpreter (``pyproject.toml`` floor ``>=3.10``; the Orin's
JetPack CPython is 3.10), holding the one robot-network credential and the one
autonomous vendor command writer.  ``src/parcel_robot`` is the *product* side
of the seam; deployable gateway modules may import only its pure-stdlib bridge
surfaces: the frozen protocol, the product-owned client compatibility export,
and the device-wide ``UnitreeWriterLockV1`` shared with supervised
commissioning.  They do not import runtime, control, perception, or model code.
``tests/test_m1_0_gateway.py`` and ``tests/test_motion_seam.py`` pin that import
surface.

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

**What this package is not.** It is not a general Unitree control surface and
it does not give the product runtime an SDK object.  The optional SDK2 binding
is localized to :mod:`gateway.ports`, loaded dynamically only after an
explicit physical launch profile, and exposes only ``Move``, ``StopMove`` and
read-only Sport state through the structural :class:`gateway.ports.SportPort`.
Before real SDK construction, both gateway entry points must hold the fixed
device-wide writer lock.  The armed commissioning CLI uses that same lock only
while this service is stopped and while running as the same ``parcel-gateway``
UID; after SDK activation the authority lasts until that process exits.
Importing this package or selecting the fake imports no vendor package.  The
product reaches the gateway only over the frozen local socket contract.  A
bench run against ``parcel_robot.bridge.fake_sport`` proves contract and fault
behaviour on a desktop; it proves nothing about robot identity, vendor
firmware, braking distance, physical safety, or scheduling on the Orin.
"""
