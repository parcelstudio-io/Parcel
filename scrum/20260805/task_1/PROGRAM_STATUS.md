# Program status — P0–P5 (owner amendment: hardware last)

**Date:** 2026-08-05 · **Binding:** [ADJUDICATION.md](ADJUDICATION.md)

One-line verdict: **sim capability arc P0–P4 is closed; Phase 5 readiness
paperwork is closed; all physical validation remains blocked** until the
owner authorizes purchase.

## Phase scoreboard

| Phase | Name | Status | Evidence |
|---|---|---|---|
| P0 | Contract freeze + calibration + eval (−procurement) | **CLOSED (sim/docs)** | K0 arrival authority; K1 contracts; K2′ bags + ledger; ADRs drafted |
| P1 | Four-track sim sprint | **CLOSED** | [PHASE1_GATE.md](PHASE1_GATE.md) — K3–K8 |
| P2 | Voice-behavior joins (sim) + UWB noise model | **CLOSED (sim)** | [PHASE2_GATE.md](PHASE2_GATE.md) · [P2_DIALOGUE_STATUS.md](P2_DIALOGUE_STATUS.md) · [P2_UWB_STATUS.md](P2_UWB_STATUS.md) |
| P3 | City layer (sim GNSS/maps/OCR/crossing) | **CLOSED (sim)** | [PHASE3_GATE.md](PHASE3_GATE.md) · [P3_CITY_STATUS.md](P3_CITY_STATUS.md) · [P3_OCR_STATUS.md](P3_OCR_STATUS.md) |
| P4 | Route memory + learned proposers (sim stubs) | **CLOSED (sim MVP)** | [PHASE4_GATE.md](PHASE4_GATE.md) · [P4_ROUTE_STATUS.md](P4_ROUTE_STATUS.md) |
| P5 | Hardware (all of it, last) | **READINESS ONLY** | [PHASE5_GATE.md](PHASE5_GATE.md) — physical work **blocked** |

## Sim arc complete (what we can honestly claim)

- Contracts, bags, and resume/voice/city/route **code paths** exist and are
  CI-exercised against sim stand-ins.
- Every known hardware substitution is named on
  [hardware-readiness.md](hardware-readiness.md) (HR-1…HR-14) with a **P5-G-***
  re-run gate and **unvalidated** status.
- Golden-image and firmware-pin decisions are written as **Draft** ADRs:
  - [adr/0001-golden-image.md](adr/0001-golden-image.md)
  - [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md)
- Desktop/CI compose skeleton exists (`deploy/compose.yaml`) — **not** a dock flash.
- CPU-budget proxy exists (`evals/cpu_budget_proxy.py`) — **not** Orin timing.

## Physical remaining (what we must not claim)

| Work | Blocker | First gate when unblocked |
|---|---|---|
| Purchase Go2 EDU ≥1.1.13, 2× Orin NX, D455, ZED-F9P, XVF3800 | Owner authorize-to-purchase | [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md) |
| Sacrificial golden image + firmware pin validation | Purchase + flash | **P5-G-INSTALL** (HR-9) |
| Day-one real bags into pre-built harness | Install | **P5-G-BAG-DROPIN** (HR-8) |
| Staged commissioning dry-run → bench → leashed → free | Install + dual e-stop | [P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md) |
| UWB / GNSS / pixel / Orin / audio field gates | Bench+ | P5-G-UWB, GNSS, PIXEL, ORIN-TIMING, AUDIO |
| Leashed 20-min mixed course + route memory field | Leashed+ | P5-G-CROSSING, P5-G-ROUTE (+ optional CityWalker/VLFM) |
| OTA / wizard v1 / tailnet / long-horizon study | After leashed evidence | Original P5 productization cards |

## Honesty constraints (standing)

1. Green sim tests update **sim evidence only**.
2. Nothing on the readiness ledger is hardware-validated today.
3. No docker/QSPI flash, no shopping cart, no “commissioned” claims in this
   increment.
4. Concentrated sim-to-real risk at P5 is acknowledged (motion, UWB, low-
   viewpoint perception, Orin budgets, acoustic UX) — mitigations bound it;
   they do not remove it.

## Pointers

- Gate: [PHASE5_GATE.md](PHASE5_GATE.md)
- Ledger: [hardware-readiness.md](hardware-readiness.md)
- Checklist stub: [P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md)
- BOM (do not purchase): [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md)
- Adjudication: [ADJUDICATION.md](ADJUDICATION.md)
