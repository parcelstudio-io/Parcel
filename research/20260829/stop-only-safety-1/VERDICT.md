# SOS-1 verdict

Adopt the split runtime/stop-only credential policy and `parcel-safety`
process. The prior P0 statement “independent stop-only service absent” is now
resolved at source, fake-gateway, signal-lifecycle, packaging, and unit-file
levels.

Do **not** interpret this as physical safety qualification. The service has not
run on AGX Orin or Unitree, and its real STOP inputs are not wired. Autonomous
physical motion therefore remains **NO-GO**.

Before any untethered motion:

1. Build the aarch64 image and create distinct `parcel-runtime`,
   `parcel-safety`, `parcel-gateway`, and `parcel-motion` identities; load and
   verify all units on the target.
2. Wire local voice STOP and the commissioned remote/GPIO input into the
   stop-only principal, inject stuck process/socket/DDS/vendor faults, and show
   STOP still reaches the robot within its measured deadline.
3. Retain a physical E-stop/Unitree remote path that does not depend on the
   Orin, Python, Parcel, DDS, Starlink, or mains networking.
4. Measure stationary witness integrity and worst-case stop distance on each
   surface, speed, payload, slope, battery, and pedestrian geometry before
   setting any social-navigation clearance.

The immediate mount verdict improves from an absent software principal to a
tested source-level principal. It does not advance beyond motors-disabled HIL
or tethered commissioning.

This is the original verdict. The current-source decision, including the
READY/signal race repair and strict maintenance-3 rerun, is in
`MAINTENANCE_VERDICT.md`; physical readiness remains NO-GO.
