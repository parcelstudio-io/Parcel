# P5 Procurement BOM — DRAFT ONLY

# ⛔ DO NOT PURCHASE YET

**Date:** 2026-08-05 · **Status:** Draft bill of materials (not an order)  
**Binding:** [ADJUDICATION.md](ADJUDICATION.md) Owner amendment — hardware is
purchased **last**. Physical Phase 5 work is blocked until the owner
explicitly authorizes purchase.

This file is paperwork so P5 can execute later. It is **not** a shopping cart,
PO, or approval to spend.

Related: [PHASE5_GATE.md](PHASE5_GATE.md) ·
[P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md) ·
[hardware-readiness.md](hardware-readiness.md) ·
[adr/0001-golden-image.md](adr/0001-golden-image.md) ·
[adr/0002-firmware-pin.md](adr/0002-firmware-pin.md)

---

## Line items (v1 supported platform)

| # | Item | Spec / pin | Qty | Why | Notes |
|---|---|---|---|---|---|
| 1 | Unitree Go2 EDU | Firmware **≥ 1.1.13** (hard pin; ADR 0002) | 1 | Body + Sport + UWB fob channel | Customer-owned EDU posture; Parcel does **not** flash Unitree firmware |
| 2 | NVIDIA Orin NX dock (16GB) | JetPack **6.2.x** golden image (ADR 0001) | **2** | Compute: sacrificial flash dock + production restore dock | Two-dock rule is mandatory; do not flash the only dock first |
| 3 | Intel RealSense D455 | Color+depth; mount at ~35 cm (low-viewpoint) | 1 | CameraChannel / DetectionMsg real pixels (HR-4) | Intrinsics already nominal in sim bags |
| 4 | u-blox ZED-F9P (GNSS) | Multi-band RTK-capable; NTRIP client planned | 1 | Field GNSS vs P3 cov/dropout model (HR-3) | Antenna + mount TBD at order time |
| 5 | XMOS XVF3800 mic kit | Far-field AEC array | 1 | Hardware voice path (HR-7) | Acoustic UX unvalidated even on desktop until B1 apt + this kit |

Optional / already-on-robot (confirm at order time; do not assume):

| # | Item | Qty | Notes |
|---|---|---|---|
| A | Unitree L1 (or installed LiDAR) | 1 | HR-5; confirm EDU kit contents before buying a duplicate |
| B | UWB owner fob | 1 | Usually ships with Go2; confirm pairing path for HR-2 |
| C | Leash / fence hardware + dual e-stop buttons | 1 set | Required by commissioning ladder; not “AI” SKUs |
| D | NTRIP subscription / base | 1 | Service, not hardware; needed for P5-G-GNSS realism |

---

## Explicitly out of scope for this BOM

- Extra Go2 bodies for scale testing
- AIR/PRO “Parcel Lite” WebRTC kits (demo tier only; no authority loop)
- Cloud GPU contracts (Tier-2) — productization card, not procurement day-one
- Nav2 / ROS 2 host appliances (D1: no authority migration in v1)

---

## Purchase gate (owner)

| Step | Action | Owner | Status |
|---|---|---|---|
| 1 | Review this BOM + [PHASE5_GATE.md](PHASE5_GATE.md) | Owner | Pending |
| 2 | Explicit written authorize-to-purchase | Owner | **NOT GIVEN** |
| 3 | Place POs / carts | — | **FORBIDDEN until step 2** |
| 4 | Inventory + serials into commissioning preconditions | Operator | Blocked |
| 5 | Begin [P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md) Stage 0 | Operator | Blocked |

Until step 2 is recorded below, any agent or human claiming “hardware on order”
or “commissioned” is in error.

### Authorization log

```text
authorized_by:
date:
reference:          # email / ticket / chat ID
notes:
```

_(empty = do not purchase)_

---

## Receipt / inventory log (fill after purchase — leave blank now)

| Line | Vendor | PO / order ID | Serial(s) | Received | Firmware / image |
|---|---|---|---|---|---|
| Go2 EDU | | | | | |
| Orin NX #1 (sacrificial) | | | | | |
| Orin NX #2 (production) | | | | | |
| D455 | | | | | |
| ZED-F9P | | | | | |
| XVF3800 | | | | | |

---

## Cost posture (honesty)

Prices are intentionally omitted from this draft so the document cannot be
mistaken for a ready-to-click cart. When the owner authorizes purchase,
attach a dated quote sheet as a sibling artifact (e.g.
`P5_PROCUREMENT_QUOTE_<date>.md`) — still separate from this BOM.

---

## Non-claims

- Existence of this file ≠ procurement.
- Desktop/CI compose (`deploy/compose.yaml`) ≠ dock ownership.
- ADR drafts ≠ flashed golden image.
