# HW-8 `box-day-runbook` — DESIGN

**Card:** `scrum/20260822/task_39/README.md` · **Executor:** Claude Opus ·
**Verifier:** Fable · **Design of record:** `../WAVE3_HW_DESIGN_FABLE.md`
§5.7, §5.9, §7 (+§7.2), §8, §9 HW-8 · **Board:** `../TASK_BOARD.md` wave 3.
**Docs only — this card writes no product code and runs no hardware.**

## 1 · Purpose

The dog is 2–4 weeks out and the owner has 6–8 h with it over two weeks.
This card converts design §7 from a table inside a 440-line design document
into four documents a person can hold in one hand on the day: a runbook the
owner reads once and signs, a run sheet the two people follow while the rig
is bolted together, a support ticket that turns two of the sixteen unknowns
into answers *before* delivery, and a register that says which card each
remaining unknown blocks. The failure this prevents is the one the 08-13
session plan names: a one-shot physical day spent debugging instead of
reading, and irrecoverable measurements (extrinsics, clock offsets, the M8
voltage) lost because nobody wrote down that they were to be taken.

## 2 · The four documents, and who reads each

| Document | Reader | Read when | Shape |
|---|---|---|---|
| `docs/BOX_DAY.md` (new, tracked) | **the owner**, alone, before delivery; then aloud on the day | once, top to bottom, ≤ 10 min (≤ 2,500 words) | ordered steps: command → result file → branch → who → minutes |
| `task_39/STAGE0_RUN_SHEET_EDU_PLUS.md` | the **operator + second person**, in hand, during the session | line by line, boxes ticked | the 08-13 Stage-0 sheet with EDU+ deltas marked |
| `task_39/SUPPORT_TICKET_UNITREE.md` | the **owner**, to send to Unitree/robostore support **now** | copy, paste, send | five numbered questions, each naming the unknown it closes |
| `task_39/UNKNOWNS_REGISTER.md` | **Fable / the next card cutter** | when a wave-3b card is planned | design §8 + `resolves on` + `blocks` |

The runbook is the index; the run sheet is the procedure; the ticket is the
only thing that can be done before the box exists; the register is the join
between the two.

## 3 · Architecture fit (what this card touches, as file:symbol)

No seam is modified. The documents *name* seams and their product-path
callers so the day's reads land on real code:

- `scripts/parcel_capture/preflight.py` — the L4T table (`L4T_TO_JETPACK`,
  JetPack 6.0–6.2.1 only) is what makes B9 a **stop**, not a note, on
  JetPack 5; `probe_builtin_lidar` is Q-lidar's read.
- `scripts/parcel_capture/attest.py` — `FIRMWARE_PIN` is ADR 0002's pin
  in code; S20's result file is what the arming gate later cites.
- `scripts/parcel_capture/orin_rehearsal.py` — the 08-14 OR-1 harness
  (`ORIN_RUNBOOK.md`, phases `p0_identity`…`p5_recorder`) already automates
  most of B9/Q-usb/B12 and fails closed. The runbook points at it rather
  than re-specifying it; §7's per-step commands are the manual fallback and
  the things the harness does not cover (the robot LAN, the Mid-360, DDS).
- `scripts/parcel_capture/record.py` / the `parcel-capture` console script —
  B12's recorder smoke.
- `tools/xvf3800_probe.py` — Q-usb's array half.
- `src/parcel_robot/control/unitree_sport.py` — the only motion caller;
  the runbook's rule is that nothing in the first two hours imports it.

## 4 · The result-file convention (`hw/`)

Every step of §7 writes exactly one file. The convention documented by the
runbook (and **not created by this card** — no `hw/` directory is added to
the tree):

- On the Orin, results go to `~/Parcel/hw/<STEP>_<name>.<ext>` — the repo
  checkout's own subdirectory, created by the day's first step with
  `mkdir -p`. Git on the Orin is read-only (COMMON brief); the Orin never
  commits.
- At the end of the session the whole directory is `rsync`ed to the dev box
  into the **box-day card's** folder (`scrum/<box-day>/task_NN/hw/`), where
  it is committed. Design §9: "the card is HW-9 `first-two-hours` and its
  status doc IS the §7 result files."
- One file per step, named for the step id, so a crash loses at most one
  step and a missing file is visible as a missing row.
- Raw command output verbatim, never a summary: the 08-13 lesson is that a
  summary of a hardware read is not evidence.

## 5 · What "command exists" means (Work 5's test)

A command may appear in the runbook or the run sheet only if one of these
holds, and the status doc records which:

1. **Console script** — the name is in `pyproject.toml [project.scripts]`
   *and* `.parcel/bin/python -m <module> --help` (or the installed script
   with `--help`) exits 0 and prints a usage line containing the
   sub-command named. Verified with `--help` only; nothing is executed
   against hardware and no device is opened.
2. **Module/symbol** — `.parcel/bin/python -c "import <mod>; <mod>.<sym>"`
   resolves the attribute (for `preflight.probe_builtin_lidar`), or the
   file exists and `--help` exits 0 (for `tools/xvf3800_probe.py`).
3. **Vendor/OS command** (`ip`, `lsusb`, `nft`, `tcpdump`, `ros2`,
   `rs-enumerate-devices`, `nvidia-smi`) — not ours to verify; it is
   written as *runs on the Orin, presence unverified on this host*, which
   is the honest tag. These are excluded from the pre-registered rows and
   listed once in the status doc.

A command that fails 1 or 2 is **not written**. It becomes a HANDOFF row in
`HW8_STATUS.md` naming the card that must create it, and the runbook step
carries `COMMAND DOES NOT EXIST YET — HW-n` in place of a command line.
Inventing a plausible spelling is the specific failure this rule exists to
prevent: the owner would type it on the day and lose the step.

## 6 · Claim tagging (the citing rule, inherited from `research.json`)

Every hardware claim in the runbook carries its tag from the design:

- `[documented]` — a source URL exists in `WAVE3_HW_DESIGN_FABLE.md` §2/§7
  or `research.json`. Written as fact; the URL stays in the design, not in
  the runbook (the runbook is a 10-minute read, and §2 is one hop away).
- `[inferred]` — written as **UNCONFIRMED**, in those words, and the step
  that resolves it is named on the same line. An inferred claim never
  appears as an instruction ("plug the Mid-360 into the M8 plug") without
  its resolving read next to it.
- Repo-measured facts are untagged, as in the design.

## 7 · Time budgets

Two sums are printed in the runbook and in `HW8_STATUS.md`:

- the **first-two-hours** table ≤ 120 min;
- **everything the owner must be personally present for** ≤ 480 min (8 h),
  the PO-1 budget ("after delivery 6–8 h over two weeks").

Engineer-only work (Q-ort, the LIO bake-off, the native gateway build) is
excluded from the second sum and marked *engineer, owner not present*.

## 8 · Risks and what this design does NOT cover

- **The run-sheet base file.** The card names
  `scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md` as the thing to copy;
  that file is the 08-13 *verdict + board*, not a run sheet. The actual
  Stage-0 run sheet is `scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md`
  (727 lines, stop bars, branches, checkbox instantiation). The rewrite is
  based on the run sheet — the card's Work-2 sentence says "Rewrite the
  Stage-0 run sheet", and design §7's B12 row says "the 08-13 Stage-0 run
  sheet rewritten for EDU+". Recorded as a deviation; both source files are
  copied, never edited.
- This card cannot prove any hardware claim. Everything it writes is a
  *plan to read*; the reads happen on HW-9. A verifier who treats a green
  status doc here as evidence about the dog has made the batch-A mistake.
- The runbook does not authorise motion. `--arm` appears exactly once, as a
  precondition list, and PO-1's record + design §6's envelope re-run are
  both in it.
- Ordering deviation, on the record: Work 5's command cross-check is
  measured **after** `PREREGISTRATION.md` is fixed and **before** the
  runbook is written, so that no unverified command can enter the runbook
  text. The rows are pre-registered as written; only the order of the
  writing and the measuring is swapped, and it is swapped in the safe
  direction.
