# Task 39 — HW-8: `box-day-runbook` — the first two hours on the dog, written so a crash loses nothing and the owner can sign it

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules + anti-crash rules in `../BATCHB_DISPATCH_FABLE_4a.md`).
**Design:** `../WAVE3_HW_DESIGN_FABLE.md` §5.7, §5.9, §7 (the protocol table
+ §7.2 JetPack-5 branch), §8 (unknowns register), §9 HW-8. **Evidence:**
`scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md` (the 08-13 Stage-0 run
sheet — written for a separate Orin dock + add-on L2), `task_27/README.md`
(PO-1: the e-stop decision; MOTION.md:441-442 waiver), ADR 0002
(`scrum/20260805/task_1/adr/0002-firmware-pin.md`), `research.json`
open questions (hardware lens, 11; intent lens, 14).

## Why
Delivery is 2–4 weeks out and the owner has ~6–8 h over two weeks on the
dog. Every one of those hours must be a READ with a written result, in an
order where a JetPack-5 dock is discovered before anything else is touched
and the robot LAN is firewalled before any WAN interface comes up. The
unknowns register has 16 rows; most resolve with a one-line command.

## Work (docs only — no product code)
1. `docs/BOX_DAY.md`: the design's §7 table as a runbook — per step: the
   exact command on the Orin, the result file under `hw/` (a new directory
   convention documented here; nothing created now), the branch, who does
   it (owner / second person / engineer), the time budget. Add the two
   preconditions (dog on a stand, sport mode OFF, remote in hand, no LAN
   joined; firmware OTA disabled in the app BEFORE the dock joins any
   network), the §7.2 JetPack-5 decision tree verbatim, and the e-stop
   precondition (PO-1's record exists before any `--arm`).
2. Rewrite the Stage-0 run sheet for the EDU Plus: copy
   `scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md` to
   `task_39/STAGE0_RUN_SHEET_EDU_PLUS.md` and change ONLY what the purchase
   changes (no separate dock; Mid-360 on the M8 plug instead of an add-on
   L2; the Orin's own recorder; ports per the design's S9/Q-usb; B12's
   command addendum targets the Orin). Every change marked with a
   `<!-- HW-8: was "…" -->` comment so the diff is reviewable.
3. `task_39/SUPPORT_TICKET_UNITREE.md`: the questions for Unitree support
   (Q-jp: JetPack/L4T on 2026 EDU+ docks and a 6.2.1 BSP for the carrier;
   Q-wire: Mid-360 NIC/subnet/M8 voltage, livox_ros_driver2 preinstalled?;
   Q-fwv: shipped firmware, CVE-2026-27509 status; Q-dev: DDS exposure
   default; Q-usb: USB-C count, payload power) — written for the OWNER to
   send; nothing is sent by this card.
4. `task_39/UNKNOWNS_REGISTER.md`: the design's §8 table with a
   "resolves on" column (support ticket / B9 / §7 step / bake-off) and a
   "blocks" column (which HW card cannot close without it).
5. Cross-check every command in 1–2 against the tree: `parcel-capture
   attest`, `parcel-commission observe`, `preflight.probe_builtin_lidar`,
   `tools/xvf3800_probe.py`, `parcel-capture record --plan stage0` — each
   must exist with that spelling (run `--help` through `.parcel/bin/python`;
   no hardware is touched). A command that does not exist is a HANDOFF row
   naming the card that creates it, not an invented command.

OWNS: `docs/BOX_DAY.md` (new), `task_39/` docs. MUST NOT TOUCH: any code,
`docs/MOTION.md`, the ADRs, `task_27/`, `scrum/20260813/` (copy, never edit).

## Definition of done
Runbook + run sheet + ticket + register written; every command verified to
exist or handed off; the owner can read `docs/BOX_DAY.md` top to bottom in
ten minutes; `HW8_STATUS.md` in the lightweight register (the rows are
"command exists" checks and the cross-references, pre-registered).

## Hardware-compat (§e)
This card IS the §e of the wave: every step says which host runs it and what
is UNKNOWN until that host answers.
