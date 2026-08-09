# Phase 5 gate — readiness docs closed; physical work blocked

**Date:** 2026-08-05  
**Status:** **READINESS CLOSED** · **PHYSICAL WORK BLOCKED**

Binding: [ADJUDICATION.md](ADJUDICATION.md) Owner amendment — hardware
purchased **last**; simulator was the test substrate for P0–P4.

## What closed (paperwork only)

| Artifact | Path | Claim |
|---|---|---|
| Hardware-readiness ledger (refreshed) | [hardware-readiness.md](hardware-readiness.md) | HR-1…HR-14 each have named **P5-G-*** gate, **unvalidated** status, and pointer to today's sim test |
| Commissioning checklist stub | [P5_COMMISSIONING_CHECKLIST.md](P5_COMMISSIONING_CHECKLIST.md) | dry-run → bench → leashed → free; dual e-stop; evidence templates — **draft only** |
| Procurement BOM draft | [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md) | Go2 EDU ≥1.1.13, 2× Orin NX, D455, ZED-F9P, XVF3800 — **DO NOT PURCHASE YET** |
| Golden-image ADR | [adr/0001-golden-image.md](adr/0001-golden-image.md) | Still **Draft**; validation at P5 (**P5-G-INSTALL**) |
| Firmware-pin ADR | [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md) | Still **Draft**; ≥1.1.13; validation at P5 (**P5-G-INSTALL**) |
| Program status | [PROGRAM_STATUS.md](PROGRAM_STATUS.md) | P0–P4 sim arc vs physical remaining |

## What is explicitly blocked

Until the owner records authorize-to-purchase in
[P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md):

- [ ] No shopping cart / PO
- [ ] No dock flash / QSPI / golden-image bake
- [ ] No firmware check on a physical Go2
- [ ] No bench, leashed, or free motion
- [ ] No claim that any HR-* row is hardware-validated
- [ ] No “commissioned” language in ledgers or demos

## Exit criteria for *this* gate (readiness)

- [x] Ledger lists every sim stand-in with exact P5 re-run gate name + unvalidated
- [x] Commissioning stub + BOM draft + ADR draft links published
- [x] Physical work called out as blocked on owner purchase decision

## Exit criteria for *future* physical Phase 5 (not claimed today)

1. Owner authorize-to-purchase  
2. Inventory + ADR validation (**P5-G-INSTALL**)  
3. Staged commissioning per checklist (dry-run → bench → leashed → free)  
4. Close HR-* rows to **validated** with run ID + bag digest  
5. Optional productization (OTA, wizard v1, tailnet, long-horizon study) only after leashed course evidence

## Does not prove

Anything physical: Sport tracking, UWB field stats, GNSS canyon behavior,
Orin budgets, acoustic UX, outdoor OCR, or install-on-Unitree as a tested fact.

**Next:** owner purchase decision. Until then, keep iterating sim/eval only;
do not open shopping or flash workstreams.
