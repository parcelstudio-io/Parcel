# PS-L status — tonight's no-dog checklist

**Card:** PS-L, corrective tranche **PS-2** · **Date:** 2026-08-13
**Owns:** [`session/TONIGHT_CHECKLIST.md`](session/TONIGHT_CHECKLIST.md) (new)
**Reason this card exists:** [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) §*Platform
risks, ranked by (probability × cost), all resolvable tonight without the dog*
— six risks nobody has checked, and item 6 of *What I am changing*: *"Tonight's
no-dog checklist (N0–N7) becomes a first-class artifact."*

PS-L writes **one document**. **No source file was touched.** `git status`
attributes nothing under `src/`, `scripts/`, `tests/`, `configs/` or `evals/` to
this card — measured in **M11** below.

---

## 1 · What I built

`scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md` — **1,299 lines**, an
executable operator sheet for the night before the first physical session. Every
step is laptop-and-SSH; none needs the robot.

| Block | What it does |
|---|---|
| §0 How to use | Ordering rule, the five-part step shape (WHY · COMMAND · EXPECTED · RECORD · STOP/BRANCH), the `[REPO]`/`[EXT]`/`[UNVERIFIED-SYNTAX]` provenance tags, the standing no-arming rules, and the citation-spelling rule |
| §1 Triage | Per-step wall-clock estimate, a 90-minute subset, and a 20-minute subset |
| **PRE** | Firmware/security precondition **before any cable**; the two-dock problem; a change ledger with a verbatim `extlinux.conf` backup |
| **N0** | Orin identity dump + an uplink check I added |
| **N1** | `usbfs_memory_mb`, split into a reversible runtime write and the persistent boot-arg + reboot |
| **N2** | RealSense: install, the **metadata tradeoff**, a 10-minute per-stream frame count, and `rs-motion` with a plausibility gate |
| **N3** | `fio` with **tail** extraction, thresholded against the measured budget |
| **N4** | rosbag2 + MCAP through the exact planned command line, with synthetic publishers at the **real 84.4 MiB/s byte rate** |
| **N5** | `unilidar_sdk2` build + L2 bench read |
| **N6** | Network pinning, with a **negative-control** tcpdump that proves the DDS binding without a dog |
| **N7** | Repo transfer + the first dynamic Python-3.10 import check |
| §2–§4 | A one-page results ledger, a hand-off table into `STAGE0_RUN_SHEET.md`, and a non-empty `does not cover / does not prove` |

### The five places I did more than transcribe the card

1. **N1 is split into N1a (runtime write, reversible) → N1b (boot arg, with a
   backup) → N1c (reboot).** The card says *append, reboot, verify*, and the
   order is unchanged — but a failed reboot on the **only** Orin is the highest
   cost outcome anywhere on the sheet, so the reversible half runs first and the
   reboot is gated on the operator confirming console access in PRE-3.
2. **N2's source contradiction is surfaced, not reconciled.** The card and
   `RISK_ASSESSMENT.md:112-114` both say *"a wheel on Python 3.10/3.12"* **and**
   *"no wheel for 3.11+"*, which cannot both hold for 3.12. The sheet records
   the contradiction and makes `pip index versions` the arbiter.
3. **N4's synthetic publishers reproduce the real byte rate.** Five topics —
   colour/depth/IR×2 at 30 Hz and a cloud at 10 Hz — total **84.4 MiB/s**
   against the budget's recommended **84.60** (`../BANDWIDTH_BUDGET.md:60`), with
   **random (incompressible)** payloads so zstd cannot flatter the disk. A token
   1 Hz string topic would have proved nothing.
4. **N6 is verifiable tonight with no dog.** A tcpdump on the intended NIC plus
   a **negative control** on the other NIC proves the CycloneDDS binding, which
   is the failure the risk assessment ranks #5 and which otherwise cannot be
   tested until the robot is on the wire.
5. **An internet-uplink check added to N0.** N2a (`pip`), N3 (`apt fio`), N4a
   (`apt rosbag2-storage-mcap`) and N5 (`git clone`) **all download**. If the
   Orin has no route out tonight, four of the eight steps cannot run — and they
   cannot be fixed tomorrow on an isolated robot LAN. Five seconds to check.

---

## 2 · MEASURED claims

Every row is a command that was run and its actual output. Nothing is estimated
unless the row says so. `<S>` = the scratchpad path
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/e48d60af-8caa-4d79-96e6-ab618c386b8b/scratchpad`.

| # | Claim | Command | Output |
|---|---|---|---|
| **M1** | All 8 PS-L gates green on the real tree | `.parcel/bin/python -B <S>/check_ps_l.py .` | `PASS - 8 steps + PRE, 23 derived line pins, 6 content pins, 8 gates green` (exit 0) |
| **M2** | The tests the sheet's claims lean on pass | `.parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py tests/test_capture_envelope.py -q` | `77 passed in 3.64s` |
| **M3** | `configs/robot.yaml` really still carries the `enp3s0` placeholder — **and a second copy nobody has mentioned** | `grep -n "enp3s0" configs/robot.yaml` | `128:    interface: enp3s0  # replace with the dedicated robot Ethernet NIC on this host` and `342:    interface: enp3s0` (under `wifi_cards.robot`). The risk assessment names only `:128`. |
| **M4** | The firmware pin and its RCE framing are real, at the cited lines | `sed -n '10,17p' scrum/20260805/task_1/adr/0002-firmware-pin.md` | `:10 Unitree DDS on the robot LAN is unauthenticated by design. Pre-1.1.13 firmware` … `:17 1. **Hard pin:** supported EDU firmware **≥ V1.1.13**.` |
| **M5** | The two-dock rule is a BOM mandate, quantity 2 | `grep -n -i "dock" scrum/20260805/task_1/P5_PROCUREMENT_BOM.md` | `66:\| 2 \| NVIDIA Orin NX dock (16GB) \| … \| **2** \| Compute: sacrificial flash dock + production restore dock \| Two-dock rule is mandatory; do not flash the only dock first \|` |
| **M6** | PS-F already ruled the second dock unmeetable, and forbade mutating the one on hand | `sed -n '144p' scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md` | `\| P3 \| … \| **CANNOT BE MET** \| BOM line 2 specifies **qty 2** Orin docks; **one** is on hand … **do not flash it, do not \`apt upgrade\` it, do not mutate it** …` |
| **M7** | The recommended D455 profile and its requirement, for N3's threshold | `grep -n "848×480@30 C+D+IR\|848×480@15" scrum/20260813/task_1/BANDWIDTH_BUDGET.md` | `60:\| **848×480@30 C+D+IR** \| **84.60** \| 297.4 …` · `61:\| 848×480@15 C+D+IR \| 43.83 \| 154.1 …` |
| **M8** | The only sustained-write number in the repo is **dev-host** and disclaims the Orin | `grep -n "3,778 MiB/s" scrum/20260813/task_1/BANDWIDTH_BUDGET.md` | `242:> ### 3,778 MiB/s — **dev-host, to be re-measured on the Orin**` |
| **M9** | PS-A's 3.10 claim is static-only, and PS-A itself names N7 as the fix | `sed -n '123p;305,306p' scrum/20260813/task_1/PSA_STATUS.md` | `123:**No Python 3.10 process was executed. There is no 3.10 interpreter on this` … `306:   verification is running \`python3.10 -c "import parcel_robot.capture"\` on the` |
| **M10** | `usbfs`, `extlinux`, `fio`, `rosbag2-storage-mcap` appear **nowhere** in the repo — this sheet is the first record of them | `grep -rn "usbfs\|extlinux\|rosbag2-storage-mcap" --include=*.md --include=*.py --include=*.yaml . \| grep -v "^./.git"` | no match for any of the three (only the new sheet matches after it was written) |
| **M11** | PS-L touched **no** source file | `git status --porcelain --untracked-files=all scrum/20260813/task_1/session/` | six `?? …/session/*.md`, of which only `TONIGHT_CHECKLIST.md` is PS-L's; `git status --porcelain \| grep -E "\.py$\|\.yaml$"` lists only sibling cards' `tests/test_capture_*.py` and `tests/test_clockmap.py` |
| **M12** | Sheet size | `wc -l scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md` | `1299` |
| **M13** | **Three sibling-owned documents were rewritten mid-card, invalidating line citations** — caught by my own G3 | `check_ps_l.py .` at 11:09Z | `G3: sheet must cite README.md:108 (where 'a channel delivering 90%…' lives); it cites [… (105,107)]` · `G3: sheet must cite PHYSICAL_SESSION_PLAN.md:157 (where 'the two non-negotiables' lives)` · `G3: sheet must cite PHYSICAL_SESSION_PLAN.md:51` · `G3: sheet must cite CHANNEL_MATRIX.md:193 (where 'Two LiDARs, two SDKs' lives)` |
| **M14** | Same hazard, earlier, in `preflight.py` | `grep -n "build unilidar_sdk2 on the Orin" scripts/parcel_capture/preflight.py` at 10:22Z → `834`; the same grep at 10:56Z → `2200` | The file grew ~1,400 lines during this card. Any line pin into it would have been wrong within half an hour. |
| **M15** | `ci_gate --tier commit` is **RED**, and **not** because of PS-L | `.parcel/bin/python scripts/ci_gate.py --tier commit` (11:05Z and again 11:09Z) | `RESULT: FAIL — 1 hard gate(s) red: ruff` · `[  FAIL] HARD ruff 9 violation(s), baseline 7, new 2 -> scripts/parcel_capture/attest.py::F401; scripts/parcel_capture/preflight.py::RUF046`. Both files are sibling PS-2 cards' OWNS; PS-L edits no `.py`. Every other hard gate PASS, incl. `default-suite 4595 passed, 9 skipped, 36 deselected in 199.00s`. |

### The card's own requirements, item by item

| Card requirement | Where it lives | Verified by |
|---|---|---|
| Firmware/security precondition **at the top**, read **before** connecting | `## PRE` §PRE-1, above `## N0` | gate **G4** (ADR cited, `1.1.13`, `RCE`, `Unitree app`, `BEFORE`) + gate **G1** (PRE precedes N0) |
| Two-dock problem recorded, consequence stated plainly | §PRE-2 | gate **G5** (`quantity 2`, `One dock is on hand`, `there is no restore path`, `do not flash`) |
| N0 first, cheapest disconfirming first | §0 rule 1, §1 triage | gates **G1** (section order) and **G8** (`Do not reorder`, `cheapest-disconfirming first`, 90-minute triage) |
| N0–N7 each with literal command, expected result, explicit STOP/branch | eight `## Nn ·` sections | gate **G1** (WHY + fenced block + EXPECTED + RECORD + `STOP / BRANCH` in every one) |
| Nothing may claim it was executed | every `RECORD` is a blank | gate **G2** (no `- [x]`; every `RECORD` line carries a `______`) |
| Nothing arms anything | only `/tonight/*` is ever published | gate **G6** (arm scan over command blocks + two negative controls + three required prohibition sentences) |

---

## 3 · Seeded failures — one per gate, plus two refutation controls

Harness `<S>/seed_ps_l.sh` mirrors the 18 cited files, applies **one** fault, and
re-runs the checker. Baseline first. Run with `-B` and
`PYTHONDONTWRITEBYTECODE=1`, and `__pycache__` removed before every run, per the
PS-A finding — although every mutation here is to `.md`/`.yaml`, not to imported
Python, so the same-byte-length `.pyc` hazard does not arise.

```text
=== BASELINE (unmutated mirror) (exit=0)
PASS - 8 steps + PRE, 23 derived line pins, 6 content pins, 8 gates green
```

| Seed | Gate | Fault injected | Caught? | Verbatim detection |
|---|---|---|---|---|
| **S1** | G1 | Moved the whole `N0` section after `N1` | yes, exit 1 | `G1: sections out of order: [('N0', 291), ('N1', 198), ('N2', 365), …]` |
| **S2** | G1 | Renamed N3's `**STOP / BRANCH.**` to `**Some thoughts.**` | yes, exit 1 | `G1: N3 has no an explicit STOP / BRANCH` |
| **S3** | G2 | Pre-filled one `RECORD` blank with `412 MiB/s` | yes, exit 1 | `G2: RECORD field at line 636 has no blank - it may be pre-filled: 'RECORD  tail (last 60 s mean) …… 412 MiB/s'` |
| **S4** | G3 | Inserted **one** comment line at the top of `RISK_ASSESSMENT.md` — every cited line now off by one | yes, exit 1 | `G3: sheet must cite ../RISK_ASSESSMENT.md:141 (where '~1e24 m/s²' lives); it cites [(30, 45), …, (88, 99)]` |
| **S5** | G4 | Replaced `0002-firmware-pin.md` with prose inside the PRE block | yes, exit 1 | `G4: PRE block does not cite the firmware ADR (missing '0002-firmware-pin.md')` (+ the G3 pin) |
| **S6** | G5 | Removed **every** occurrence of *there is no restore path* | yes, exit 1 | `G5: two-dock consequence not stated plainly (missing 'there is no restore path')` |
| **S6b** | G5 | **Refutation:** removed only the PRE-2 occurrence | **correctly green** | `PASS — …` — the claim survives in §4, so the gate is asserting the *claim*, not one string's location |
| **S7** | G6 | Added `ros2 topic pub /api/sport/request unitree_api/msg/Request '{}'` to a code block | yes, exit 1 | `G6: a command in this sheet publishes to a topic that is not under /tonight/: …ros2 topic pub /api/sport/request unitree_api/msg/Requ…` |
| **S8** | G7 | Renamed the mount-geometry link to a non-existent file | yes, exit 1 | `G7: dead link 'MOUNT_GEOMETRY.md' -> …/session/MOUNT_GEOMETRY.md` |
| **S9** | G8 | Replaced `Do not reorder.` with `Reorder as convenient.` | yes, exit 1 | `G8: the sheet does not tell the operator the order is load-bearing` |
| **S10** | G6 | **Refutation:** the same forbidden tokens (`ros2 topic pub` on `rt/…`, `ControlManager`, `acquire_lease`, `pip install unitree_sdk2py`) placed in **prose** and in a `#` **comment** inside a code block | **correctly green** | `PASS — …` — G6 fires on commands, not on sentences that forbid those commands |

**S4 is the one that matters most for this card**, and it is not hypothetical:
the identical failure occurred *live*, twice, during the card (**M13**, **M14**).
It is why every citation is a **derived** pin — the checker locates the pinned
text in the cited file and requires the sheet to cite *that* line — rather than a
number I typed once and trusted.

**S10 is the refutation of the obvious way to write an anti-arming gate.** A
plain `grep -r ControlManager` would have failed this sheet for *prohibiting*
`ControlManager`. The gate scans fenced command blocks with comment lines
stripped, and the negative controls prove it.

---

## 4 · OWNS and deviations, declared

| # | Call | Why | Risk if I am wrong |
|---|---|---|---|
| **D1** | **PS-L owns no test file and no repo test.** The eight gates live in a scratchpad checker, exactly as PS-F did (`PSF_STATUS.md` D1). My OWNS is one `.md`; adding `tests/` would be an OWNS violation. | Staying inside OWNS while sibling cards are writing `tests/` | The gates are not in CI. The checker is ~200 lines and drops into `tests/` unchanged if the auditor wants them pinned. |
| **D2** | **N1 split into a reversible runtime write, then the persistent boot arg, then the reboot** — and the reboot is gated on the operator recording console access. The card says *append, REBOOT, verify*, and that sequence is intact; I added a cheaper step before it and a precondition on it. | A non-booting Orin with no second dock (M5/M6) ends the week, and PS-F already forbade mutating the only dock | If the operator reads N1a as sufficient and skips N1b, the setting is lost at the next boot. The sheet says so explicitly and puts a re-apply line in the hand-off table. |
| **D3** | **N6 does not test against the actual Go2.** The card's premise is *no robot tonight*, and PRE-1 forbids attaching computers to that LAN before the firmware is cleared. N6 pins and **verifies configuration** (via tcpdump with a negative control); the ping-the-dog test is tomorrow's first network action. | Following the card's own no-robot rule and the ADR's security precondition | The single largest tomorrow-morning unknown — *does the dog actually appear on the wire* — is still unknown at 09:00. The sheet names this as an owner decision with its preconditions, rather than doing it silently. |
| **D4** | **The sheet contains an rclpy publisher script, typed on the Orin, not added to the repo.** It publishes only `/tonight/*`, never any `rt/…` topic, and is not a robot-command publisher. | N4 is worthless at a token message rate; matching 84.4 MiB/s is what tests the recorder | A reader could mistake it for repo code. It is labelled *"Type this file on the Orin; it is NOT a repository file"* and gate G6 scans it. |
| **D5** | **Six citations carry no line number** (`../README.md`, `../PHYSICAL_SESSION_PLAN.md`, `../CHANNEL_MATRIX.md`, `scripts/parcel_capture/preflight.py`). | M13/M14: those files were being rewritten by sibling PS-2 cards *while this card ran*. A line number into a moving file looks precise and points at the wrong thing. | Slightly less precise citations. The checker still asserts the quoted text exists, and flags any future attempt to line-pin those files. |
| **D6** | **`session/README.md` does not index this sheet.** That file is PS-F's OWNS and PS-L may not edit it. | OWNS boundary | **Residual, for the auditor:** the pack index lists four sheets and does not mention `TONIGHT_CHECKLIST.md`. Someone who prints the pack from `session/README.md` will not print this. A one-line pointer by PS-F or the tranche lead fixes it. |
| **D7** | **`ci_gate --tier commit` is red and I did not fix it.** The two new ruff violations are in `scripts/parcel_capture/attest.py` and `preflight.py` — sibling cards' OWNS, in flight (M15). | Editing another card's file to green my own gate would be an OWNS violation and would collide with a live editor | The tranche cannot close until a sibling fixes them. Recorded rather than quietly re-run to green. Both are trivial (`F401` unused export, `RUF046` redundant `int()`). |

**No blocker.** Every item above is a declared judgement call.

---

## 5 · Findings handed to the auditor and to other cards

1. **`ci_gate` is red on `ruff`, +2 new** (M15) — `attest.py::F401`,
   `preflight.py::RUF046`. Owner: whichever PS-2 card is rewriting those files.
2. **`configs/robot.yaml` has a *second* `enp3s0` placeholder at `:342`** (M3),
   under `wifi_cards.robot.interface`. `RISK_ASSESSMENT.md:122` names only
   `:128`. An operator who fixes one leaves the other.
3. **Three tranche documents were rewritten mid-tranche** (M13) —
   `README.md`, `PHYSICAL_SESSION_PLAN.md`, `CHANNEL_MATRIX.md` — plus
   `preflight.py` growing ~1,400 lines (M14). **Any sibling status doc that
   line-cites those files is now stale.** Worth a sweep at audit.
4. **`session/README.md` does not index the new sheet** (D6).
5. **The pip `pyrealsense2` wheel costs the `device_source` timestamp.** If N2b
   reports `system_time`, `CaptureEnvelope.source_timestamp_ns` must be **null**
   for every D455 channel and the PS-C physical sync ritual becomes the only
   camera-to-world tie. That is a **PS-C / PS-A** consequence, decided by a
   measurement taken tonight.
6. **`/events/messages_lost` may not exist on Humble's rosbag2.** If N4 finds it
   absent, per-channel loss provenance must come from the `parcel-capture`
   sidecar — which is an argument *for* keeping the sidecar in the reworked D-1/D-2
   design, and it should be stated there rather than assumed.
7. **The Orin's internet uplink is an unstated precondition** for four of the
   eight steps, and for tomorrow's install of anything at all.

---

## 6 · Gate runs — as instructed

PS-L owns no test file (D1). Run: the tests the sheet's claims lean on.

```console
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && \
  .parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py \
      tests/test_capture_envelope.py -q
........................................................................ [ 93%]
.....                                                                    [100%]
77 passed in 3.64s
```

```console
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T11:05:13Z)
==============================================================================
[  FAIL] HARD  ruff                       9 violation(s), baseline 7, new 2 -> scripts/parcel_capture/attest.py::F401; scripts/parcel_capture/preflight.py::RUF046
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 | mutation panel clean: … | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.32s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.28s
[  PASS] HARD  default-suite              4595 passed, 9 skipped, 36 deselected, 5 warnings in 194.76s (0:03:14)
==============================================================================
RESULT: FAIL — 1 hard gate(s) red: ruff
  elapsed 206.3s
```

Re-run at 11:09Z after allowing time for the sibling card to land: **identical**
— `RESULT: FAIL — 1 hard gate(s) red: ruff`, `default-suite 4595 passed, 9
skipped, 36 deselected in 199.00s`. Attribution measured:

```console
$ .parcel/bin/python -m ruff check scripts/parcel_capture/attest.py scripts/parcel_capture/preflight.py
RUF046 Value being cast to `int` is already an integer
    --> scripts/parcel_capture/preflight.py:1079:13
Found 2 errors.
```

Both files are sibling PS-2 cards' OWNS. **PS-L modifies no `.py` file and
cannot redden or green `ruff`** (M11).

---

## 7 · does_not_prove

- **Nothing in the sheet has been executed, and nothing in it can be by me.** It
  is blank paperwork for a person at a laptop tonight. Every measured claim in §2
  is about *this document and the repository it cites* — that its citations
  resolve, that its steps have branches, that it refuses to claim execution.
  **None of it is evidence about the Orin, the D455, the L2, the NVMe, or
  rosbag2.**
- **Not one command in the sheet has been run anywhere.** This dev box has no
  Jetson, no ROS, no RealSense, no LiDAR, and none of `rclpy`, `mcap`,
  `pyrealsense2`, `unilidar_sdk2`, `fio`, or `zstandard`. The commands are
  **[UNVERIFIED-SYNTAX]** by construction and the sheet says so per step. Flags,
  YAML keys, pyrealsense2 method spellings, and SDK target names may all differ
  from what is written; the sheet tells the operator the requirement is the
  measurement, not the string.
- **Every threshold in the sheet is a proposal, not a derivation.** The ≥99 % /
  90 % per-stream bands in N2c, the 2× disk-headroom rule in N3, the 8.81–10.81
  m/s² accel window — no accuracy or availability requirement exists anywhere in
  this repository to derive them from. They are my judgement, labelled as
  decision thresholds, and they must not be quoted as a spec.
- **Every `[EXT]` claim is about other people's hardware.** The 16 MB `usbfs`
  default, the ~80 % RGB drop, the dead D455 IMU, the missing 3.11+ wheel, the
  DRAM-less NVMe knee, the L2 factory IP, `rs-motion`'s unavailability on
  aarch64 — all reach me through `RISK_ASSESSMENT.md`, which is itself
  documentation and issue threads. **I verified none of them and cannot.**
- **The `pyrealsense2` wheel-availability statement in my own source is
  self-contradictory** (*"3.10/3.12"* vs *"no wheel for 3.11+"*). I did not
  resolve it; I flagged it and delegated it to `pip`. If both halves are wrong,
  N2a's branch table is aimed at the wrong problem.
- **The N4 publisher script has never been run.** Its byte-rate arithmetic is
  checked (84.4 vs the budget's 84.60 MiB/s) but the code is unexecuted, in a
  language runtime that is not present here. It may not even import.
- **A green sheet tonight does not predict tomorrow.** N2's ten minutes is not
  an hour; N3's `fio` measures a disk, not the recorder; N4's synthetic
  publishers are not sensor drivers sharing a machine. Thermal and power bounds
  remain the explicit unknown `BANDWIDTH_BUDGET.md` names, and stay unknown after
  tonight.
- **The sheet touches nothing on the dog's DDS.** The `rt/` name mangling, the
  service-gated topics, the 12-vs-20 joint count, the two foot-force arrays, and
  the L1-vs-L2 identity of the built-in LiDAR are **all still open**. No amount
  of laptop work settles them.
- **The eight gates prove the sheet is internally consistent and honest. They
  prove nothing about whether it is *usable*.** That is discovered by an operator
  holding it at 22:00, and the first person to run it will find things wrong with
  it.
- **`ci_gate` is red, and that proves nothing about this card either way** — PS-L
  contains no executable code. A green `ci_gate` would not have been evidence
  for the sheet, and the red one is not evidence against it.
- **The citation gates prove that each cited line currently says what the sheet
  says it says.** They do **not** prove the cited *claim* is true, and they will
  go red — correctly — the moment a sibling card shifts one of those files again.
  It happened twice during this card (M13, M14).
