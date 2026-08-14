# PS-F status — Stage 0 run-sheet, mount geometry, safety brief

**Card:** PS-F, tranche PS-1 · **Date:** 2026-08-13 · **Base:** `406f9d6`
**Board:** [README.md](README.md) §PS-F · **Plan:** [PHYSICAL_SESSION_PLAN.md](PHYSICAL_SESSION_PLAN.md)

PS-F writes documents. **No source file was touched.** `git status` attributes
nothing under `src/`, `scripts/`, `tests/`, `configs/` or `evals/` to this card.

---

## 1 · What I built

### New: `scrum/20260813/task_1/session/` — the operator pack (5 sheets, 1,525 lines)

| File | Lines | What it is |
|---|---|---|
| [`session/README.md`](session/README.md) | 137 | Index, order of operations, the three branches, and the **traceability table** that maps every Stage-0 checkbox to its producer |
| [`session/STAGE0_RUN_SHEET.md`](session/STAGE0_RUN_SHEET.md) | 598 | The instantiation of `P5_COMMISSIONING_CHECKLIST.md:91-109`. Run header, roles, T-30 command transcription, precondition ruling, four stop bars, per-checkbox instantiation C0.1–C0.7, the Stage-0→Stage-1 pre-stand gate, teardown |
| [`session/MOUNT_GEOMETRY_SHEET.md`](session/MOUNT_GEOMETRY_SHEET.md) | 417 | Tape-measured D455 + **both** LiDARs to `base_link`: datum realisation, two orthographic diagrams, raw-readings-win rule, per-key uncertainty, direct-vs-derived cross-check, assembly **and** teardown measurement, comparison against the sim's unchecked extrinsic |
| [`session/PHOTO_LIST.md`](session/PHOTO_LIST.md) | 113 | 20 mandatory shots + 3 conditional + 2 optional, each with subject, camera position, and why; clock-tie frame; offload rule |
| [`session/SAFETY_BRIEF.md`](session/SAFETY_BRIEF.md) | 260 | 11 hazards ordered by likelihood, roles with the no-second-job rule, the stop procedure, the ten-second pre-power version, sign-off |

**I did not author a new checklist.** The run sheet instantiates the ratified
Stage 0 and reuses its own evidence templates verbatim (`:167-181` run header,
`:205-211` gate close record). It adds **no checkbox** to the ratified list.

### What Sol omitted and the checklist assumes — all four added

1. **Mount geometry.** The unrecoverable quantity, with the consequence stated
   on the sheet's first screen. Includes a **datum you can realise with a
   tape** (three planes off the hip-roll axes), a fail-closed clause for when
   the datum cannot be established, an **independent direct measurement** of
   the two-LiDAR baseline as a check on the datum, and an **M2 teardown
   re-measure** with tolerances and an invalidation rule.
2. **Photograph list.** Includes P02 — the built-in LiDAR's model label, which
   settles the repo's L1-vs-L2 contradiction with no software at all — and a
   clock-tie first frame so EXIF times map onto the session host clock.
3. **Mechanical safety before the stand.** Ten-row pre-stand gate: payload
   pull test, cable strain relief within 100 mm of every connector, cable
   routing out of the leg envelope, pinch sweep, connector seating, padded mat,
   and an explicit acceptance that a stop press **drops a standing dog** with
   the payload on it.
4. **The named failure branch.** `DEGRADE-MMP` — *mount, measure, photograph,
   record nothing* — declared a legitimate outcome, with its own required
   deliverable list, plus a third `ABORT-SAFETY` branch that is strictly more
   conservative.

### Modified: the two P5 banners (supersede visibly, delete nothing)

**`P5_PROCUREMENT_BOM.md`** — four changes, all banner/pointer:

| Where | Change |
|---|---|
| head | `# ⛔ DO NOT PURCHASE YET` replaced by a `SUPERSEDED 2026-08-13` block that **quotes the original banner verbatim inside itself**, states what changed (`backlog/NEXT.md:28-39` reversal), points to `PHYSICAL_SESSION_PLAN.md` and the session pack, and lists what the supersession does *not* do (no spend authority, no line marked received, items 4/5/B still unconfirmed) |
| head | Added: optional item A's "Unitree L1" is now flagged as **uncertain**, resolved by reading the physical unit (P02) |
| head | Added: a line-number-moved note (item A `:35` → `:75`) |
| `## Purchase gate (owner)` | Pointer blockquote: the `NOT GIVEN` / `FORBIDDEN` / `Blocked` statuses are left **unedited** as the 2026-08-05 record; step 5 now points at the run sheet |
| `## Receipt / inventory log` | Pointer blockquote: "leave blank now" no longer holds; the table is filled at the session; an empty row means *not yet inventoried*, never *assumed present* |

The `Binding:` line, the line-item table, the authorization log, the receipt
table, the cost posture, and the non-claims are **byte-unchanged** apart from a
`superseded 2026-08-13, see banner above` marker on the `**Date:**` line.

**`P5_COMMISSIONING_CHECKLIST.md`** — two changes, all banner/pointer:

| Where | Change |
|---|---|
| head | `DO NOT EXECUTE` blockquote replaced by a `SUPERSEDED IN PART` block that **quotes the original verbatim**, explicitly keeps its last sentence (*"Completing a checkbox here is not validation"*) in force, and carries a **scope table**: Stage 0 LIVE; preconditions ruled individually; the `:86-88` dual-e-stop rule UNCHANGED and enforced; **Stages 1–3 NOT superseded, still DO NOT EXECUTE**; evidence templates unchanged and used verbatim. Plus the line-number-moved mapping. |
| `## Stage 0` | Pointer blockquote: the seven boxes are **instantiated, not replaced**, and stay **unticked here** — they are ticked on a per-run sheet |

No stage content, no exit criterion, no checkbox, and no evidence template was
edited.

---

## 2 · MEASURED claims

Every row is a command that was run and its actual output. Nothing is estimated
unless the row says so.

| # | Claim | Command | Output |
|---|---|---|---|
| M1 | All 6 PS-F gates green on the real tree | `.parcel/bin/python <scratch>/check_ps_f.py .` | `IN-FLIGHT: STAGE0_RUN_SHEET.md -> ../BANDWIDTH_BUDGET.md` / `PASS — 7 Stage-0 checkboxes mapped, 6 gates green` (exit 0) |
| M2 | The two tests the run sheet tells the operator to rely on pass | `.parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py -q` | `11 passed in 3.41s` |
| M3 | `ci_gate --tier commit` green | `.parcel/bin/python scripts/ci_gate.py --tier commit` | `[  PASS] HARD  ruff  7 violation(s), baseline 7, new 0` … `RESULT: PASS — every hard gate green.` (second run; see M4) |
| M4 | An earlier `ci_gate` run was red, and **not** because of PS-F | `.parcel/bin/python scripts/ci_gate.py --tier commit` (08:56Z) | `[  FAIL] HARD ruff  8 violation(s), baseline 7, new 1 -> src/parcel_robot/capture/envelope.py::SIM223` — PS-A's in-flight file. Re-run after PS-A fixed it: green (M3). PS-F touches no `.py`. |
| M5 | No time synchronisation exists anywhere — the plan's "zero hits" is right in substance | `grep -rEc "chrony\|ntp\|ptp\|phc2sys\|time.?sync" src/ configs/ deploy/ scripts/ \| grep -v ":0"` | `src/parcel_robot/brain/validator.py:1` — one hit, and it is a **substring false positive**: `"jointpositions"` contains `ntp`. Recorded as such in run sheet §7 C0.2. |
| M6 | Every vendor/ROS dependency really is absent from the Parcel venv | `for m in rclpy cyclonedds unitree_sdk2py pyrealsense2 cv2 mcap zstandard; do .parcel/bin/python -c "import $m"; done` | `ModuleNotFoundError` for all seven; `Python 3.14.4` |
| M7 | **No test pins the runtime's arm refusal** | `grep -rl "configuration alone cannot arm hardware" tests/` | no match (exit 1). The string exists only in `src/parcel_robot/runtime.py:386-391`. Run sheet C0.6 therefore routes the demonstration through inspection + an existing test, and files the missing pin as a finding. |
| M8 | Three of the factory's four arming flags fail closed; one does not | `sed -n '113,142p' configs/robot.yaml` | `:114 controller: simulator` · `:133 enable_lease: true` · `:135 axes_commissioned: false` · `:137 state_frame_commissioned: false` · `:142 allowed_modes: []`. Run sheet C0.6 names all five as untouchable for the session. |
| M9 | The sim's D455 extrinsic is a hard-coded, never-checked assumption | `grep -n "MOUNT_" src/parcel_robot/camera_channel/d455.py` | `:34 MOUNT_HEIGHT_M = 0.35` · `:35 MOUNT_FORWARD_OFFSET_M = 0.18` · `:36 lateral 0.0` · `:38 pitch math.radians(12.0)` · `:133 abs(self.height_m - MOUNT_HEIGHT_M) <= tolerance_m` (default ±0.05 m). Geometry sheet §6 is the comparison table with the named consequence. |
| M10 | `default_frames()` provides **one** LiDAR frame id, and we have two LiDARs | `grep -c "lidar_frame" src/parcel_robot/bags/schema.py` | `2` (the key in `REQUIRED_FRAME_KEYS` and its single value `"lidar_link"` at `:121`). Geometry sheet §8 assigns `lidar_l2_link` in the sidecar `extra`, since `schema.py` is not editable by this tranche. |
| M11 | The channel matrix has **19** channels, not 15 | `grep -cE "^\| [0-9]+ \|" CHANNEL_MATRIX.md` → `19`, ids `1..19`; `PHYSICAL_SESSION_PLAN.md:161-177` summary table → `15` rows; `README.md:53` → "15 entries" | Discrepancy is real. The pack uses **19** (my brief names CHANNEL_MATRIX as authoritative). **Flagged for the auditor — PS-A may build 15.** |
| M12 | The supersession shifted line numbers, and every citation in the pack was re-pointed | `check_ps_f.py` gate G5 (20 pinned `file:line → expected text` assertions) | green in M1; seeded drift caught (S5 below) |
| M13 | Pack size | `wc -l scrum/20260813/task_1/session/*.md` | `417 + 113 + 137 + 260 + 598 = 1525` |

### The card's three gates, measured

| Card gate | How it is enforced | Result |
|---|---|---|
| "Every Stage-0 checkbox maps to a PS-A..E artifact or an explicit operator action — no orphan checkboxes" | checker gate **G1**: parses the seven checkboxes **out of the ratified checklist itself**, requires a traceability row citing each one's current line, requires the row to quote the checkbox, requires a producer drawn from {PS-A…PS-E, operator, DEFERRED, this pack}, requires any `DEFERRED` to name a consequence, requires a matching `C0.n` section in the run sheet, and rejects invented rows | **PASS** — 7/7 mapped, 0 orphans, 0 invented |
| "The go/no-go has a **named failure branch**" | checker gate **G2**: `DEGRADE-MMP`, the literal phrase *mount, measure, photograph, record nothing*, the words *legitimate outcome*, an `ABORT-SAFETY` branch, and named triggers | **PASS** |
| "No claim that anything was executed" | checker gate **G3**: no `- [x]` anywhere in the pack; every sheet declares itself blank/undelivered; every sheet has a does-not-prove section | **PASS** — 5/5 sheets |

---

## 3 · Seeded failures — one per gate, each with the proof it was caught

Harness: `<scratch>/seed_failures.sh` mirrors the tree, applies one fault, and
re-runs the checker. Baseline first, then eight seeds.

```text
=== BASELINE (unmutated) ===
PASS — 7 Stage-0 checkboxes mapped, 6 gates green
    checker exit=0
```

| Seed | Gate | Fault injected | Caught? | Verbatim detection |
|---|---|---|---|---|
| S1 | **G1** | Deleted the traceability row for `checklist:105` (comms-loss) | ✅ exit 1 | `G1: orphan checkbox — no traceability row cites checklist:105 ('Comms-loss auto-damp demo once (disconnect → ')` |
| S2 | **G1** | Replaced the named `**PS-D** + **PS-B**` producer with `somebody` | ✅ exit 1 | `G1: checklist:103 producer 'somebody' names no PS-A..E artifact, operator action, or explicit deferral` |
| S3 | **G2** | Reworded the degrade branch into an abort | ✅ exit 1 | `G2: go/no-go is missing its named failure branch token 'mount, measure, photograph, record nothing'` |
| S4 | **G3** | Ticked one checkbox (`- [ ]` → `- [x]`) in the run sheet | ✅ exit 1 | `G3: STAGE0_RUN_SHEET.md contains a ticked checkbox '- [x]' — claims execution` |
| S5 | **G4** | Renamed the mount-geometry pointer to a non-existent file | ✅ exit 1 | `G4: README.md: dead link 'MOUNT_GEOMETRY.md' -> …/session/MOUNT_GEOMETRY.md` |
| S6 | **G5** | Inserted one line into the checklist above Stage 0 — every cited line number now off by one | ✅ exit 1 | 11 failures, incl. `G5: P5_COMMISSIONING_CHECKLIST.md:101 should contain 'Dock compose stack boots', got ''` and `G1: orphan checkbox — no traceability row cites checklist:108` |
| S7 | **G6** | Deleted the preserved `DO NOT EXECUTE` text from the checklist supersession | ✅ exit 1 | `G6: checklist supersession deleted the original DO NOT EXECUTE banner text` (+16 knock-on) |
| S8 | **G6** | Deleted the preserved `⛔ DO NOT PURCHASE YET` text from the BOM supersession | ✅ exit 1 | `G6: BOM supersession deleted the original DO NOT PURCHASE banner text` |

S6 is the one that matters most for this card: it is the exact failure mode a
supersession banner *creates*, and it is why every citation in the pack is
pinned by a `file:line → expected text` assertion rather than trusted.

S7/S8 are the refutation of the obvious way to write a supersession — deleting
the old banner instead of quoting it — and the checker treats that as a hard
failure, not a style preference.

---

## 4 · Judgement calls and deviations, declared

| # | Call | Why | Risk if I am wrong |
|---|---|---|---|
| D1 | **PS-F owns no test file.** The card's closing instruction says to run `pytest tests/<your test file>`; PS-F's OWNS is `session/` + two banner updates, and adding a repo test would be outside it. The six gates live in a scratchpad checker; the pytest I ran is the pair the run sheet actually tells the operator to rely on (M2). | Staying inside OWNS on a day when five other cards are writing `tests/` | The gates are not in CI. If the auditor wants them pinned, the checker is 190 lines and drops into `tests/` unchanged. |
| D2 | **A stand is a Stage-1 entry, not Stage-0 content.** `checklist:81` defines Stage 0 as *motion disabled*; `:82` puts stand/sit in Stage 1. So the pack runs Stage 0 with the dog **seated**, and puts standing behind a pre-stand gate **and a second full stop verification**, with the envelope capped at operator-initiated stand/sit under the vendor handheld. | The alternative — quietly treating a stand as Stage 0 — would break the ladder rule the checklist puts in bold | If the owner intends a standing session, §8/§9 are the gate to walk through, not a wall; nothing is lost. |
| D3 | **`run_id` follows the ratified template, not the board's example.** Board `README.md:212` shows `P5-DRY-20260813-…`; ratified `checklist:170` is `P5-<STAGE>-YYYYMMDDTHHMMSSZ`. I used the ratified form and left the date blank (the session is the day *after* this pack). | The ratified artifact outranks a board example, and pre-filling tomorrow's date would be a claim about a day that has not happened | Cosmetic; the note in §1 explains both. |
| D4 | **The pack uses 19 channels; the board says 15** (M11). | My brief names CHANNEL_MATRIX.md as the authoritative enumeration and it lists 19 | **Real risk to PS-A**: if PS-A builds 15 entries, the run sheet's §7 C0.3 table has four rows nothing produces. Flagged for the auditor. |
| D5 | **`:56`'s ≤300 ms is split into a measurable and an unmeasurable half.** The vendor stop response is recoverable from the bag; Parcel's *software* stop-path latency is `NOT MEASURED — nothing armed`, and the budget is left explicitly open. | Writing any number for a path that does not exist would be the first false entry in the dataset | The checkbox does not close. That is the honest state, and the sheet says so. |
| D6 | **Preconditions P2/P3 are ruled `WAIVED` and `CANNOT BE MET`** rather than ticked. BOM line 2 specifies **two** Orin docks; one is on hand, so the two-dock rule is not exercisable and the single dock is therefore **not** sacrificial — the sheet forbids flashing or mutating it. | ADR 0001's whole point is that the first flash is a one-way door | `P5-G-INSTALL` ends the day **blocked**. Stated up-front rather than discovered at teardown. |
| D7 | **Three pointer blockquotes added inside the two P5 docs** (BOM purchase gate, BOM receipt log, checklist Stage 0), beyond the head banners. | The card's OWNS says "banner/**pointer** updates". Leaving `FORBIDDEN until step 2` and `leave blank now` unannotated next to a live session invites an operator to act on a stale instruction | No substance was rewritten and no row was edited; every original status value is still there verbatim. |
| D8 | **Line numbers in both P5 docs moved** because banners are prepended. I re-pointed every citation **in my own pack** and recorded the old→new mapping **inside both banners**. I did **not** edit `README.md`, `PHYSICAL_SESSION_PLAN.md`, or `CHANNEL_MATRIX.md`, which still cite the pre-supersession coordinates (`:51-61` etc.) — they are outside PS-F's OWNS. | Editing sibling-card documents would be an OWNS violation | Residual: three same-tranche docs carry stale coordinates. Both banners state the mapping, so a reader is never stranded. **Left for the auditor to decide.** |
| D9 | **One forward reference:** `session/STAGE0_RUN_SHEET.md` §3 links `../BANDWIDTH_BUDGET.md`, which PS-E owns and had not landed when PS-F finished. The checker reports it as `IN-FLIGHT` rather than silently allowing it. | The T-30 transcription step genuinely needs that document | If PS-E does not land it, the link is dead. Declared, not hidden. |

**No blocker.** Nothing about PS-F was blocked; every deviation above is a
declared judgement call, not a workaround.

---

## 5 · Findings handed to other cards / the backlog

1. **No test pins `runtime.py:386-391`** (M7). The refusal *"configuration
   alone cannot arm hardware"* — cited by the board as one of today's motion
   guarantees — is unpinned. A one-line test would fix it; **not today**, and
   the run sheet routes around it rather than exercising an arm by hand.
2. **`configs/robot.yaml:133` `enable_lease: true`** (M8). Three of the
   factory's four commissioning flags fail closed; this one is already
   permissive. The absent SDK and `controller: simulator` are what actually
   hold the line. Named as untouchable in run sheet C0.6.
3. **`default_frames()` has one `lidar_frame` for two LiDARs** (M10). PS-B
   needs `lidar_l2_link` (and `lidar_l2_imu_link`, `camera_imu_optical_frame`)
   in the sidecar `extra`; `schema.py` must not be edited.
4. **Channel count 19 vs 15** (M11) — PS-A.
5. **The sim's D455 extrinsic has never been checked against hardware** (M9).
   Geometry sheet §6 is the check, with `is_dog_height()`'s ±0.05 m as the
   named threshold and a written verdict box.
6. **A stop press drops a standing dog onto the payload.** Not recorded
   anywhere in the repo before this pack. It changes the order of operations
   (mat first, drop-acceptance stated aloud, one deliberate standing stop test).

---

## 6 · Gate run — as instructed

PS-F owns no test file (D1). Run: the two tests the run sheet cites.

```console
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && \
  .parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py -q
...........                                                              [100%]
11 passed in 3.41s
```

```console
$ .parcel/bin/python scripts/ci_gate.py --tier commit
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                …collisions=0 false_arrival=0 …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        …6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.30s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              4134 passed, 9 skipped, 36 deselected in 185.03s
RESULT: PASS — every hard gate green.
```

(The 08:56Z run of the same command was **FAIL** on `ruff`, `+1` new violation
in `src/parcel_robot/capture/envelope.py::SIM223` — PS-A's in-flight file, not
PS-F's. Re-run after PS-A fixed it is the block above. Recorded rather than
quietly re-run: M4.)

---

## 7 · does_not_prove

- **Nothing in the session pack has been executed, and nothing in it can be.**
  It is blank paperwork. Every measured claim in §2 is about the *documents* —
  that their citations resolve, that their checkboxes map, that they refuse to
  claim execution. **None of it is evidence about the robot, the sensors, or
  the capture stack.**
- **A run sheet is not a session.** Passing all six gates here proves the sheet
  is internally consistent and traceable. It proves nothing about whether it is
  *usable* — that is discovered by an operator holding it, and the first
  session will find things wrong with it.
- **The mount-geometry datum is a convention I defined**, not a vendor-published
  `base_link`. If Unitree's body-frame origin differs, the derived column will
  be wrong; only the raw readings and the datum photograph make the correction
  possible, which is exactly why the sheet demands both. **I have not verified
  the datum against any Unitree document or CAD** — this dev box has neither.
- **The ±5 mm / ±1.0° M2 tolerances are proposals, not derivations.** No
  accuracy requirement exists anywhere in the repo to derive them from. They
  are labelled provisional on the sheet and must not be quoted as a spec.
- **The hazard list is not a risk assessment and is not exhaustive.** It is
  eleven hazards ordered by my judgement of likelihood for an indoor,
  flat-floor, room-temperature, sensor-only session. It has not been reviewed
  by anyone with hardware-safety authority, no one has walked the actual room,
  and outdoors/stairs/slopes/crowds are outside it entirely.
- **The mass, drop-height, and payload figures in the brief are stated ranges,
  not measurements.** "15 kg quadruped", "1–2 kg payload", "≈0.3 m drop" are
  order-of-magnitude, used only to size the hazard. The geometry sheet §7 is
  where the **real** masses get recorded.
- **I did not verify that any Unitree topic carries what the matrix says it
  carries**, that the built-in LiDAR is an L1 or an L2, that the D455 profile
  in the budget is achievable, or that the stop devices exist and are
  independent. Every one of those is a **session** measurement; the pack is
  built to *record* them, not to assert them.
- **The traceability gate proves each checkbox has a named producer. It does
  not prove the producer works.** PS-A…PS-E were being written in parallel; I
  read their OWNS paths off the board, not their code. If PS-B's sidecar never
  ships, run sheet C0.3 has a producer that does not exist — and the T-30
  transcription step (§3) is the only thing that would catch it.
- **The supersession does not prove the owner's reversal.** I recorded it from
  the board and `PHYSICAL_SESSION_PLAN.md:211-220`, which record it from the
  owner. The BOM's authorization log is **still empty**, and I did not fill it:
  filling it would be a claim I have no standing to make.
- **`ci_gate` green proves the repo is green. It proves nothing about this
  card**, which contains no executable code and cannot redden or green any
  gate in it.
