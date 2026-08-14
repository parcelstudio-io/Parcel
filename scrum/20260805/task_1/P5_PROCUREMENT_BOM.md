# P5 Procurement BOM — DRAFT ONLY

> ## ⚠️ SUPERSEDED 2026-08-13 — hardware is on hand
>
> **From 2026-08-05 until 2026-08-13 this document opened with the banner:**
>
> > # ⛔ DO NOT PURCHASE YET
>
> **That banner was correct and binding for that entire period, and it is
> preserved here rather than deleted.**
>
> **What changed.** The owner has reversed the standing *"hardware last, sim
> throughout"* sequencing recorded at
> [`backlog/NEXT.md:28-39`](../../../backlog/NEXT.md) (2026-08-05
> adjudication). Hardware is now **on hand** — Go2 **EDU** · add-on Unitree
> **L2** LiDAR · RealSense **D455** · Jetson **Orin NX** — and the first
> physical session is imminent.
>
> **Superseding record:**
> [`scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md`](../../20260813/task_1/PHYSICAL_SESSION_PLAN.md).
> Operator sheets for the session:
> [`scrum/20260813/task_1/session/`](../../20260813/task_1/session/README.md).
>
> **What this supersession does *not* do.** It does not authorise spending, it
> does not mark any BOM line as received, and it closes no gate. Items **4**
> (ZED-F9P GNSS) and **5** (XVF3800 mic kit) and optional **B** (UWB fob) are
> still **unconfirmed** — the session's preflight probes for them and reports
> honestly, and XVF3800 remains blocked (`backlog/BLOCKED.md` B3, in the post).
> **The receipt / inventory log below is still empty and is filled with real
> serials at the session** — see the session run sheet §4 P0 and §11.
>
> **Optional item A's "Unitree L1" (now `:75`) is uncertain, not a fact.** The
> vendor's page says the built-in unit is an **L2**. The session **reads the
> model off the physical unit** and photographs the label
> ([`session/PHOTO_LIST.md`](../../20260813/task_1/session/PHOTO_LIST.md) P02).
> Do not resolve it from this document.
>
> **Line numbers moved.** This banner shifted every line below it: optional
> item A was `:35` at base `406f9d6` and is now `:75`. Documents written
> before 2026-08-13 cite the older coordinates; the text they name is
> unchanged.

**Date:** 2026-08-05 · **Status:** Draft bill of materials (not an order) ·
**superseded 2026-08-13, see banner above**  
**Binding (as written 2026-08-05, retained as history):**
[ADJUDICATION.md](ADJUDICATION.md) Owner amendment — hardware is
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

> **Pointer (2026-08-13):** the `NOT GIVEN` / `FORBIDDEN` / `Blocked` statuses
> in this table are the record **as of 2026-08-05** and are left unedited on
> purpose. The sequencing they encode has been superseded — see the banner at
> the top of this file and
> [`PHYSICAL_SESSION_PLAN.md`](../../20260813/task_1/PHYSICAL_SESSION_PLAN.md).
> Step 5's "Begin Stage 0" is now instantiated as
> [`session/STAGE0_RUN_SHEET.md`](../../20260813/task_1/session/STAGE0_RUN_SHEET.md).

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

> **Pointer (2026-08-13):** "leave blank now" no longer holds. Hardware is on
> hand and this table is **filled at the first physical session** with real
> serials, per
> [`session/STAGE0_RUN_SHEET.md`](../../20260813/task_1/session/STAGE0_RUN_SHEET.md)
> §4 P0 and §11. It is still blank because nobody has been at the session yet
> — an empty row means **not yet inventoried**, never "assumed present".
> The table below is unchanged from 2026-08-05 apart from this pointer.

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
