# HW-8 `box-day-runbook` — PREREGISTRATION

Written **before** any measurement, at 13:0x EDT 2026-08-23, against
`DESIGN.md` (same folder) and the card's Work items 1–5. Rows are measured
exactly as written; a miss is a miss and is reported as one. No row touches
hardware, opens a device, starts a process on `:8765` or
`/tmp/parcel_sim.sock`, or runs `pytest` (this card runs none; if one were
ever needed it goes through `~/.cache/parcel-guard/pytest_guard.sh --label
hw8`). All commands run from the repo root
`/home/jaewoo-jang/Desktop/Projects/Parcel` with `TMPDIR` unset.

**Definition used by every C-row** — `DESIGN.md` §5: a console script must
appear in `pyproject.toml [project.scripts]` **and** answer `--help` with
exit 0; a module symbol must resolve by import; an OS/vendor command is out
of scope and is written as *presence unverified on this host*.

## A · Command-exists rows (Work 5)

| Row | Command in the documents | Verification command (exact) | Threshold = MET when |
|---|---|---|---|
| **C1** | `parcel-capture attest` | `grep -n 'parcel-capture' pyproject.toml` then `.parcel/bin/python -m scripts.parcel_capture --help` (or the entry-point module named by the grep) | the script name is in `[project.scripts]`, `--help` exits 0, and `attest` appears in its sub-command list |
| **C2** | `parcel-capture record --plan stage0` | `<parcel-capture entry> record --help` | exit 0, `--plan` is an accepted option, and `stage0` is an accepted value (named in help text, choices, or the plan registry the help points at) |
| **C3** | `parcel-commission observe` | `grep -n 'parcel-commission' pyproject.toml` then `<entry> --help` and `<entry> observe --help` | the script name is in `[project.scripts]`, both `--help` exit 0, `observe` present |
| **C4** | `preflight.probe_builtin_lidar` | `.parcel/bin/python -c "import scripts.parcel_capture.preflight as p; print(p.probe_builtin_lidar)"` | prints a callable; no device opened (import only) |
| **C5** | `tools/xvf3800_probe.py --help` | `.parcel/bin/python tools/xvf3800_probe.py --help` | exit 0, usage printed, **no PortAudio device opened** (the array is on hand; `--help` must not enumerate) |
| **C6** | `parcel_robot.cli` (the product CLI, if cited) | `.parcel/bin/python -m parcel_robot.cli --help` | exit 0 and a usage line; if it exits non-zero the runbook cites no `parcel_robot.cli` command |
| **C7** | `orin_rehearsal` harness (§3 of DESIGN) | `.parcel/bin/python -m scripts.parcel_capture.orin_rehearsal --help` | exit 0; `--evidence-dir`, `--record-target`, `--firmware-attested` present (the flags `ORIN_RUNBOOK.md` §2 names) |
| **C8** | `parcel-capture preflight` | `<parcel-capture entry> preflight --help` | exit 0; if absent, the runbook names the module path instead and this row is a HANDOFF, not a miss of C8's meaning |

Every C-row that does NOT meet its threshold produces (a) no command text
in `docs/BOX_DAY.md` or the run sheet, (b) a `COMMAND DOES NOT EXIST YET —
HW-n` line in the step, and (c) a HANDOFF row in `HW8_STATUS.md` naming the
card that must create it. **Rows C1–C8 are the complete set of Parcel-owned
commands the two documents may use.** Any command the drafting discovers it
needs beyond this list is added to this file as C9+ *before* it is checked,
and the addition is declared in the status doc.

## B · Cross-reference rows (Work 1–4)

| Row | Claim | Verification | Threshold = MET when |
|---|---|---|---|
| **X1** | the runbook is design §7, not a paraphrase | count the step ids in `docs/BOX_DAY.md` against §7's table | all 13 §7 ids (B9, B-fw, S20, Q-dev, Q-lidar, Q-wire, Q-usb, B11, B12, S19, Q-stop, Q-ort, Q-link) appear; any step the runbook adds is marked **(added by HW-8)** with its reason |
| **X2** | §7.2 JetPack-5 branch is carried verbatim in substance | read §7.2 against the runbook's branch section | all three options (i reflash / ii 3.10 on 20.04 with perception off-dog / iii hold), "owner-decided, none taken by a card on its own", and the doc's default (i if the BSP exists, else ii) all present |
| **X3** | e-stop precondition | grep the runbook for the PO-1 reference | `task_27/README.md` cited by path, the `MOTION.md:441-442` waiver named, and the sentence that PO-1's record exists **before** any `--arm` present |
| **X4** | firmware pin | grep for ADR 0002 | `scrum/20260805/task_1/adr/0002-firmware-pin.md` cited by path; ≥ 1.1.13, auto-update disabled at commissioning, and the firewall item all present; CVE-2026-27509's "no known patched version" stated so the pin is not read as sufficient |
| **X5** | the two preconditions | read the runbook's preconditions block | dog on a stand, sport mode OFF, remote in hand, no LAN joined; **and** firmware OTA disabled in the app BEFORE the dock joins any network |
| **X6** | firewall before WAN (design §5.7) | read the step order | B-fw appears before any step that brings up a WAN interface, and carries: default-drop forwarding robot-LAN↔WAN, DDS multicast confined to the robot NIC, panel on 127.0.0.1 reached over tailnet, Mid-360 static `192.168.1.5` with no gateway |
| **X7** | claim tagging (DESIGN §6) | count `[documented]` and `UNCONFIRMED` occurrences; read every hardware sentence | zero untagged hardware claims; every `inferred` design claim used in the runbook is written as UNCONFIRMED with the step that resolves it named on the same line |
| **X8** | unknowns register completeness | count rows of `UNKNOWNS_REGISTER.md` against design §8 | all 16 §8 ids present, each with a non-empty `resolves on` and `blocks` cell; `blocks` names a card id (HW-n) or "nothing" |
| **X9** | run-sheet diff reviewability | `grep -c '<!-- HW-8: was' STAGE0_RUN_SHEET_EDU_PLUS.md` and a manual diff against the source | every substantive change carries one `<!-- HW-8: was "…" -->` comment; count of comments ≥ count of changed content blocks; the 08-13 source file is byte-unchanged (`git status --porcelain scrum/20260813/` empty) |
| **X10** | the support ticket covers the pre-delivery unknowns | read the ticket | Q-jp, Q-wire, Q-fwv, Q-dev, Q-usb each present as a numbered question naming the unknown id; the ticket states it is for the **owner** to send and that nothing was sent by this card |
| **X11** | one result file per step | read the runbook's table | each of the 13 §7 steps names exactly one result file under `hw/`, matching design §7's names where §7 gives one |

## C · Budget and readability rows

| Row | Measurement (exact command) | Threshold |
|---|---|---|
| **W1** | `wc -w < docs/BOX_DAY.md` | **≤ 2,500 words.** This is the ten-minute-read check (250 wpm). `wc -w` counts markdown table pipes as tokens, so it over-counts prose — passing it is the conservative outcome. If it is over, the row is a MISS and the status doc states the count, the reason, and a secondary prose count from `sed -E 's/\|/ /g; s/[-:]+//g' docs/BOX_DAY.md \| wc -w` |
| **T1** | sum the `minutes` column of the first-two-hours table | **≤ 120 min**; the sum is printed in the runbook and in the status doc |
| **T2** | sum the `minutes` of every row marked *owner present* across the whole runbook | **≤ 480 min (8 h)**, the PO-1 budget; engineer-only rows excluded and marked *engineer, owner not present*; the sum is printed in both places |

## D · Hygiene rows

| Row | Threshold |
|---|---|
| **H1** | Nothing outside OWNS is modified: `git status --porcelain` shows changes only under `scrum/20260822/task_39/` and the new `docs/BOX_DAY.md`; `scrum/20260813/` and `scrum/20260822/task_27/`, `docs/MOTION.md`, the ADRs are untouched |
| **H2** | No product code is touched: `git status --porcelain -- src/ scripts/ tools/ tests/ configs/ pyproject.toml` is empty at close |
| **H3** | Zero pytest processes and zero processes started by this card at close (`tools/list_parcel_procs.py`); no `~/.cache/parcel-batchb/` lock held; git used read-only (no add/commit/stash/checkout) |
