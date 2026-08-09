# ADR 0001 — Golden dock image (draft; validate at P5)

**Status:** Draft (written P0 under owner amendment; **validation deferred to P5**)  
**Date:** 2026-08-05  
**Card:** K2′  
**Related:** [ADJUDICATION.md](../ADJUDICATION.md) Owner amendment; [hardware-readiness.md](../hardware-readiness.md) HR-9

## Context

v1 target platform is Go2 EDU + Orin NX 16GB dock. JetPack / QSPI flash is a
one-way door. Without a frozen golden image, every dock becomes a snowflake and
sim→device timing comparisons are meaningless.

## Decision (intent; not yet executed)

1. **Golden image:** JetPack 6.2.x (TensorRT 10.x line; jetson-containers-compatible).
2. **Two-dock rule:** flash and bake on a **sacrificial** dock first; freeze the
   image; installer restores, never mutates the golden artifact.
3. **Ship artifact:** golden image + compose bundle. Safety+control container
   has zero network dependencies and restarts independently.
4. **OTA posture:** versioned image pulls with A/B rollback; dev iteration via
   bind-mounted source / rsync — not ad-hoc system mutation.

## Consequences

- P1–P4 may build and run the compose skeleton on desktop/CI without flashing
  (see repo `deploy/compose.yaml`, card K7). That smoke is **not** golden-image
  validation.
- P5 commissioning starts by validating this ADR on the sacrificial dock.
- Until HR-9 closes, no claim that Parcel "installs on Unitree" as a tested fact.

## Validation checklist (P5)

- [ ] Sacrificial dock flashed to pinned JetPack 6.2.x revision; image hash recorded
- [ ] Compose stack boots; safety+control container survives network loss
- [ ] Image restore path exercised once without manual package drift
- [ ] Cross-link run ID into hardware-readiness HR-9

## Does not prove (until checklist complete)

Desktop compose smoke (`deploy/compose.yaml`), CI x86_64 slim images, aarch64
deferral, or this document's existence. **K7 explicitly did not flash any dock.**
