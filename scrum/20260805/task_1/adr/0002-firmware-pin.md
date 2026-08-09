# ADR 0002 — Go2 firmware pin ≥1.1.13 (draft; validate at P5)

**Status:** Draft (written P0 under owner amendment; **validation deferred to P5**)  
**Date:** 2026-08-05  
**Card:** K2′  
**Related:** [ADJUDICATION.md](../ADJUDICATION.md); [hardware-readiness.md](../hardware-readiness.md) HR-9

## Context

Unitree DDS on the robot LAN is unauthenticated by design. Pre-1.1.13 firmware
is treated as RCE-capable on home Wi-Fi (CVE-2026-27509 / 27510 class findings
cited in the Fable research plan). Parcel's FCC posture is accessory-plus-software
on a customer-owned Go2 — **no firmware modification** by Parcel.

## Decision (intent; not yet executed)

1. **Hard pin:** supported EDU firmware **≥ V1.1.13**.
2. **Commissioning gate:** runtime / wizard refuses to arm motion without a
   machine-readable record that the pin passed.
3. **Auto-update:** disable at commissioning; pin stays operator-owned.
4. **Network:** dock firewalls `192.168.123.0/24`; remote access tailnet-only.
5. **Parcel scope:** software + accessory only; never flash or patch Unitree
   firmware from this repository.

## Consequences

- Sim work (P0–P4) does not need a robot; the pin is a P5 install invariant.
- Security claims before HR-9 validation are aspirational process, not evidence.
- K7 compose/packaging work does **not** touch Unitree firmware or perform any
  flash — consistent with this ADR's scope boundary.

## Validation checklist (P5)

- [ ] Go2 EDU reports firmware ≥1.1.13 at commissioning; version recorded
- [ ] Auto-update disabled; DDS segment firewalled behind dock
- [ ] Wizard / runtime hard-fails below pin (tested once on purpose)
- [ ] Cross-link run ID into hardware-readiness HR-9

## Does not prove (until checklist complete)

Any sim bag, Sport mock, desktop compose smoke, or documentation that mentions
the pin number.
