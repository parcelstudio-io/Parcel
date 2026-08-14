# PS-K status — the session take script

**Card:** PS-K, corrective tranche **PS-2** · **Date:** 2026-08-13 · **Executor:** Opus
**Driver:** [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md) item 5 of *What I am changing*
— *"**PS-F run-sheet**: add the non-skippable 30-minute irreversible block
(SYNC-OPEN, foot-force zero-offset takes, 15 min static, SYNC-CLOSE) plus the
full take script, and the verify-LiDAR-FOV-overlap-before-final-torque step."*
**OWNS:** [`session/TAKE_SCRIPT.md`](session/TAKE_SCRIPT.md) (new) · amendments to
[`session/STAGE0_RUN_SHEET.md`](session/STAGE0_RUN_SHEET.md) and
[`session/MOUNT_GEOMETRY_SHEET.md`](session/MOUNT_GEOMETRY_SHEET.md)

PS-K writes **documents only. No source file was touched** — measured in **M12**.

---

## 1 · What I built

### New — `session/TAKE_SCRIPT.md`, 1,247 lines

An ordered, operator-followable script of **17 takes, T0–T16**, each with a
duration, a stated purpose, an explicit irreversibility claim, a procedure, a
blank `RECORD` block and a failure branch.

| Section | What it is |
|---|---|
| §0 How to use | one take = one bag = one row · the six-part take shape · provenance tags · the **two-numbering-spaces-called-T** warning · bag naming · the **profile-freeze** rule · **recorder flags measured in a ROS 2 Jazzy sandbox** |
| §1 The day at a glance | 17 rows: duration, recorded?, **irrecoverable?**, and what each take makes possible later |
| §2 The take log | the blank index that makes bags findable, including a row for takes that did **not** happen |
| §3 **The non-skippable core** | T3 + T4 + T5 + T14 = **30 min**, with the mechanism-level reason each cannot be skipped or moved |
| §4 The takes | T0 … T16, in dependency order |
| §5 **If the day is cut short** | the noon rule, an 11-rank truncation ladder, the **2-hour minimum viable day**, and three things that are never skipped |
| §6 Disk and time ledger | per-take GiB at the frozen profile, the whole-script total, and the free-space arithmetic that decides the profile |
| §7 does_not_prove | non-empty, 10 bullets |

**The gap this closes, measured at card start** (M1): the whole session pack
returned **zero hits** for `excitation`, `static bias`, `loop closure`,
`calibration target`, `per-point time`, `AprilTag/AprilGrid`, `Allan`. The pack
proved the *stack*; it never told anyone what to point the sensors at. **A
dry-run record is not a dataset.**

### Amendment 1 — `MOUNT_GEOMETRY_SHEET.md` **§4A · pre-torque FOV gate** (new section)

Before final bracket torque: dog facing a large planar wall, **both** LiDAR
clouds live in RViz2, confirm a substantial shared region, confirm it survives a
30–45° rotation, and — **an addition of mine** — check that *our own payload* has
not put a new shadow into the built-in LiDAR's view, against take T1's
pre-mount bag as the only unoccluded reference this rig will ever have.

Carries: a safety caveat (this needs the dog powered at snug-not-final torque), a
**degraded path** (datasheet FOV + line-of-sight sighting, recorded as DEGRADED,
never as a pass), a `CONFIRMED / MARGINAL / NONE` verdict, a **branch that is
still open** (`MARGINAL` ⇒ *loosen and re-aim now* — free at that moment,
impossible five minutes later), and the verbatim `does_not_prove` sentence to
write if there is no overlap at all.

### Amendment 2 — `STAGE0_RUN_SHEET.md`: take script hook + safety ordering

| Where | Change |
|---|---|
| **§7A (new)** | The take-script hook: the *dry-run record is not a dataset* framing, the two-numbering-spaces warning, the non-skippable core as a table, the cut-short pointer, the profile freeze, **the nine channels C0.3's 19-row table predates** (PS-H's matrix is 25 rows / 28 channels), the two corrections C0.3 must not be filled as printed (front camera **is** a DDS topic; rows 3/4/5/22 are service-gated), and the payload fields to confirm |
| **§8** | New row **S0** — *mat down and floor cleared **before the dog is powered at all***, not before the stand. New row **S11** — *the deliberate standing-stop drop test has been done*. An ordering blockquote naming the three constraints and the takes they gate (T4's standing segments, T5, T10, T13) |
| **§9** | §9 is identified as take **T2c**, the **first standing action of the day**, given a bag directory and a take-log row, with a re-run of S1 after the drop |
| **§11** | Three new teardown stop-bar rows: **T14 recorded before power-down**, the take log filled, the §4A verdict recorded |
| **§12** | Four new `does_not_prove` bullets, including *a dry-run record is not a dataset* |
| header, §1, §3 (×2), §7 C0.3 | **Line-count-neutral** edits: take-script pointer, `take_log_ref`, the command-row-vs-take disambiguation, and the stale "19 channels" corrected to 25 rows / 28 channels |

**Every edit above line 388 of the run sheet is line-count-neutral by
construction**, because ten `file:line` citations from four other documents point
into that region — including `TONIGHT_CHECKLIST.md:136-137,150`, which an
operator follows **tonight**, on the highest-stakes branch in the pack
(firmware-below-pin ⇒ DEGRADE-MMP). Shifting those is precisely the failure PS-F
seeded as S6. Gate **G1** pins all thirteen and seed **S1** proves it fires.

### The five places I did more than transcribe the card

1. **T10/T13 carry an authorisation gate, and a `-ALT`.** The card scripts a
   **walk** take. `STAGE0_RUN_SHEET.md` §8 and `SAFETY_BRIEF.md` §2 authorise
   *stand and sit under the vendor handheld — no gait, no locomotion*. A take
   script cannot grant what the safety pack forbids, so T10/T13 run only on a
   recorded **owner extension**, and otherwise degrade to **T10-ALT** — the same
   taped route, the same loops, the same button presses, **hand-carried** —
   which keeps loop closure, return-to-mark drift and the 10 m scale check and
   loses only gait dynamics.
2. **T16 collides with hazard H7 and is resolved fail-closed.**
   `SAFETY_BRIEF.md` §3 H7: *"Do not charge unattended."* An overnight take on
   the charger violates it. Three variants: **T16a (default)** — dog **OFF**,
   D455 + L2 IMUs only, payload on mains, no LiPo charging; T16b — dog on
   battery, **attended**; T16c — on the charger, **only with recorded owner
   sign-off**.
3. **T8 needs three non-parallel planes, not one wall.** The card says *a large
   planar wall in BOTH LiDARs*. A single plane leaves **three DOF unobservable**
   — translation within the plane and rotation about its normal. The take asks
   for a **corner** (two non-parallel walls + floor) in the shared view for at
   least one capture, and says why.
4. **The sync ritual's button press is made load-bearing.** A controller press on
   its own bridges *nothing* — it appears only in `wireless_remote[40]` and
   `wirelesscontroller`. T3 therefore specifies pressing the button **at the
   instant of each tap**, with the handheld in the tapping hand, which is what
   ties the gap-free 500 Hz controller track to every IMU in the rig. §4 carries
   an event × device table showing which event bridges which pair, and the
   branch note that an omitted event = **an unbridged device pair**.
5. **T4 gains segment E — the foot-index map.** With the dog lying, press each
   foot by hand in a named order, 5 s each. Which `foot_force[]` index is which
   physical foot is undocumented and **not derivable from a bag**. It costs 60
   seconds.

---

## 2 · MEASURED claims

Every row is a command that was run and its actual output.

| # | Claim | Command | Output |
|---|---|---|---|
| **M1** | **THE GAP is real: the session pack had zero data-collection takes** | `grep -rniE "excitation\|static.bias\|loop.closure\|calibration.target\|per.point.time\|apriltag\|aprilgrid\|allan" scrum/20260813/task_1/session/` | no output, `EXIT=1` (run before TAKE_SCRIPT.md existed) |
| M2 | All 6 PS-K gates green on the real tree | `.parcel/bin/python -B <scratch>/check_ps_k.py .` | `G1: 13 pins, 10 live citations` · `G2: 17 take sections T0..T16` · `G6: STAGE0_RUN_SHEET.md keeps 13 sections, adds ['7A']` · `G6: MOUNT_GEOMETRY_SHEET.md keeps 11 sections, adds ['4A']` · `PASS — 6 gates green; takes T0..T16; 13 citations stable` (exit 0) |
| M3 | **The gate found two real defects in my own sheet**, and they were fixed, not waived | same checker, first run | `G2: T2 has no WHY (purpose) block` · `G2: T15 has no WHY (purpose) block` · `FAIL — 2 problem(s)`. Both takes gained a WHY; re-run green (M2). |
| M4 | **Every external `file:line` citation into the two amended sheets still resolves to the same text** | checker gate G1 (13 pins) + `sed -n` spot check after editing | `121: record.py` · `122: sidecar.py` · `123: rehearse.py` · `142: 1.1.13` · `144: CANNOT BE MET` · `235: Critical channels` · `237: Sustained write` · `259: failing attestation report` · `381-387: d455_profile block`. Run sheet still **598 lines** after the six line-neutral edits. |
| M5 | The citing documents are real and would have broken | `grep -rn "STAGE0_RUN_SHEET\.md:[0-9]" --include=*.md .` | `PSE_STATUS.md:115,305,400,590,606` · `PSD_STATUS.md:69,425` · `session/TONIGHT_CHECKLIST.md:136,137,150`. Ten citations, four documents; **max cited line 387**, which is why every insertion is at ≥389. |
| **M6** | **`ros2 bag record` flags verified by running them** — in the repo's ROS 2 **Jazzy** sandbox, which carries `rosbag2_storage_mcap` | `bwrap --bind .cache/external-evals/runtime/ros-jazzy-base-sandbox / … ros2 bag record --help` | `-b/--max-bag-size … Default: 0, recording written in single bagfile and splitting is disabled` · `-d/--max-bag-duration … Default: 0` · `--max-cache-size … Default: 104857600` (double-buffered) · `--storage-preset-profile {none,fastwrite,zstd_fast,zstd_small}` · `--custom-data [KEY=VALUE ...]` · `-s {sqlite3,mcap}` |
| **M7** | **Every T0 discovery flag is spelt correctly** | same sandbox, `--help` on four subcommands | `ros2 topic hz`: `--window WINDOW, -w WINDOW` · `ros2 topic echo`: `--once`, `--full-length, -f`, `--field` · `ros2 topic info`: `--verbose, -v` · `ros2 interface show`: `usage: ros2 interface show [-h] [--all-comments \| --no-comments] type` · `ros2 bag info`: `-t/--topic-name`, `-v/--verbose` |
| M8 | The mcap storage plugin exists in that sandbox (so the `-s mcap` path is real, not assumed) | `ls .../opt/ros/jazzy/lib \| grep -i mcap` | `libmcap.so` · `librosbag2_storage_mcap.so` |
| M9 | The disk ledger's per-minute figure | derived from [`BANDWIDTH_BUDGET.md`](BANDWIDTH_BUDGET.md) §1 recommended row, `84.60 MiB/s` | `84.60 × 60 / 1024 = 4.957 GiB per recorded minute`; core = 30 min = **148.7 GiB**; whole script ≈ **368–376 GiB**; ×1.15 recorder margin ⇒ **≈425 GiB free required**. At **256 GiB** free the profile buys **≈45 min total** — the core plus fifteen minutes. |
| M10 | The reduced-channel rates in T1/T16 are derived from the budget's own per-channel table, not invented | `BANDWIDTH_BUDGET.md` §2 rows summed | tier-1 DDS (T1) = `0.650+0.027+0.663+0.133+0.033` ≈ **1.51 MiB/s**; payload-only IMU (T16a) = `0.134+0.084+0.070+0.001` ≈ **0.29 MiB/s**; dog-on IMU (T16b) adds `0.650+0.133` ≈ **1.07 MiB/s** |
| M11 | The tests the sheets tell the operator to rely on pass | `.parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py tests/test_capture_envelope.py -q` | `77 passed in 3.60s` |
| M12 | **PS-K touched no source file** | `git status --porcelain -- src scripts tests configs evals` | only `??` untracked directories belonging to PS-A/B/C/D/E/G/I (`scripts/parcel_capture/`, `src/parcel_robot/capture/`, five `tests/test_capture_*.py`). PS-K created/edited exactly three files, all under `scrum/20260813/task_1/session/`. |
| M13 | Sheet sizes | `wc -l session/TAKE_SCRIPT.md session/STAGE0_RUN_SHEET.md session/MOUNT_GEOMETRY_SHEET.md` | `1247 + 727 + 535 = 2509` (run sheet 598 → 727, geometry 417 → 535) |
| **M15** | **The gate fired on this status document**, and the fix was narrowed rather than broadened | `.parcel/bin/python -B <scratch>/check_ps_k.py .` after writing §3 | `G1: unpinned external citation STAGE0_RUN_SHEET.md:500 in scrum/20260813/task_1/PSK_STATUS.md` — G1's discovery scan read seed S2's **quoted output** as a real citation. Exemption added: skip only lines containing the checker's own diagnostic string `unpinned external citation`. Re-run green, and **all nine seeds re-verified as still firing** afterwards. |
| **M14** | `ci_gate --tier commit` is **RED, and not because of PS-K** | `.parcel/bin/python scripts/ci_gate.py --tier commit` | see §5 — 13 new `ruff` violations, **every one** in `scripts/parcel_capture/ingest/*`, `rosbag2.py`, `syncevents.py`: files written by in-flight cards PS-G/PS-I **at the minute the gate ran**. PS-K owns no `.py`. |

---

## 3 · Seeded failures — one per gate, each with the verbatim detection

Harness: `<scratch>/seed_failures.sh` mirrors the tree, applies **one** fault,
re-runs the checker. Baseline first.

```text
=== BASELINE (unmutated real tree) ===
PASS — 6 gates green; takes T0..T16; 13 citations stable
    checker exit=0
```

| Seed | Gate | Fault injected | Caught? | Verbatim detection |
|---|---|---|---|---|
| **S1** | **G1** | **One line inserted at run-sheet line 100** — i.e. the exact defect this card was built to avoid: a supersession that silently re-points four other documents' `file:line` citations | ✅ exit 1 | `G1: STAGE0_RUN_SHEET.md:121 should contain 'record.py', got '\| T3 \| Clock map (start burst → run → end burst)…'` (+12 more) |
| S2 | **G1** | A new external citation `STAGE0_RUN_SHEET.md:500` added to `PSF_STATUS.md`, unpinned | ✅ exit 1 | `G1: unpinned external citation STAGE0_RUN_SHEET.md:500 in scrum/20260813/task_1/PSF_STATUS.md` |
| S3 | **G2** | Take T3 loses its `WHY` block — a take with no purpose is a dry run | ✅ exit 1 | `G2: T3 has no WHY (purpose) block` |
| S4 | **G2** | T5's heading stops saying `⛔ CORE` | ✅ exit 1 | `G2: T5 is core but its heading is not marked '⛔ CORE'` |
| S5 | **G3** | One `- [ ]` → `- [x]` in the run sheet: the pack claims execution | ✅ exit 1 | `G3: STAGE0_RUN_SHEET.md contains a ticked checkbox '- [x]' — claims execution` |
| S6 | **G4** | The geometry sheet points at `TAKES.md`, which does not exist | ✅ exit 1 | `G4: MOUNT_GEOMETRY_SHEET.md: dead link 'TAKES.md'` (×3) |
| S7 | **G5** | §4A's `MARGINAL` branch reworded from *"**Loosen and re-aim now.**"* to *"Note it and carry on."* — the gate becomes advice | ✅ exit 1 | `G5: §4A has no 'loosen and re-aim before torque' branch` |
| S8 | **G5** | Row **S11** deleted — the standing-stop test stops gating payload trust | ✅ exit 1 | `G5: pre-stand gate has no S11 (standing-stop test done) row` |
| S9 | **G6** | Run-sheet §9 renumbered to §10, breaking every `§9` reference from the other four sheets | ✅ exit 1 | `G6: STAGE0_RUN_SHEET.md section numbering changed: [… '8','10','10','11','12'] != [… '8','9','10','11','12']` |

S1 and S9 are the two that matter for this card: **an amendment to a live
operator sheet is dangerous in exactly two ways** — it moves line numbers other
documents cite, and it moves section numbers other documents cite. Both are now
pinned rather than trusted, and both seeds fire.

S7 is the refutation of the obvious way to write the FOV gate — as a note to
observe rather than a branch to act on. A gate without an action is a note, and
the checker treats the difference as a hard failure.

---

## 4 · OWNS deviations and judgement calls, declared

| # | Call | Why | Risk if I am wrong |
|---|---|---|---|
| **D1** | **T10 and T13 are gated on an owner authorisation this pack cannot grant**, with a hand-carried `-ALT` as the default | The card scripts a walk; `STAGE0_RUN_SHEET.md` §8 and `SAFETY_BRIEF.md` §2 forbid locomotion. A take script that quietly authorised gait would be the pack contradicting itself on the one axis where it is strictest | If the owner always intended a walking session, the gate is a signature, not a wall — and `-ALT` still yields loop closure and scale. **Owner decision needed on the day.** |
| **D2** | **T16 defaults to the dog-OFF variant** (payload IMUs on mains) | `SAFETY_BRIEF.md` H7 forbids unattended charging, and Allan variance wants ≥3 h. Overriding a written hazard control to get a nice-to-have take is the wrong trade | The body IMU gets no Allan estimate this session. It is the **one** take a later session can redo, so the cost is genuinely low. |
| **D3** | **Sub-takes T2a/T2b/T2c** added under the card's single "T2 mount" | The mount hour contains three separately-irreversible things (extrinsic, FOV overlap, the first drop) and each needs its own verdict; T2c is also a *recorded* take and needs a log row | Extra ids to keep straight. The take log carries T2c only, so the ledger stays flat. |
| **D4** | **T8 asks for three non-parallel planes**, beyond the card's "large planar wall" | One plane leaves 3 DOF unobservable; the wall is necessary and not sufficient. Recording only walls would produce a take that *looks* right and cannot be solved | If a corner is unavailable in the room, the take degrades and the sheet says so. |
| **D5** | **I corrected `STAGE0_RUN_SHEET.md`'s stale channel count** (19 → 25 rows / 28 channels) and added the nine missing rows in §7A, rather than leaving C0.3 as printed | The take script states a channel set per take; if the sheet's own table is missing nine channels on a *record-everything* day, the two documents contradict each other in the operator's hands. The sheet is in my OWNS; PS-H owns the matrix, and I did not touch it | Scope-adjacent. I did **not** renumber or rewrite C0.3's table (that would have shifted PSE's `:381-387` citation); the nine rows are additive, below the citation boundary. |
| **D6** | **Every run-sheet edit above line 388 is line-count-neutral**; all new content is at line ≥389 | Ten citations from four documents point into that region, one of them followed by an operator **tonight**. PS-F's own S6 seed is this failure mode | It constrained where things could go: the take-script hook is §7A (late in the sheet) rather than §0, and the pointer at the top is a same-line append. **The pack's `README.md` "order of operations" still does not mention the take script** — see D8. |
| D7 | **`--custom-data take=…` recommended for every bag**, guarded by a distro check | Discovered by M6. A bag that describes itself survives losing this sheet, the take log and its own directory name — which is exactly the "six months from now" failure the pack keeps naming | It may not exist on Humble. The sheet says so and gives the `TAKE.txt` fallback. |
| D8 | **I did not edit `session/README.md`** (the pack index and "order of operations"), which lists four sheets and mentions neither `TAKE_SCRIPT.md` nor PS-L's `TONIGHT_CHECKLIST.md` | `session/README.md` is PS-F's OWNS, not mine, and PS-L left the same residual | **Residual for the auditor:** the pack index under-describes the pack. Both amended sheets point at the take script from their headers, so an operator holding either one is never stranded. |
| D9 | **PS-K owns no test file**; the six gates live in a scratchpad checker | My OWNS is three documents. The checker is 190 lines and drops into `tests/` unchanged if the auditor wants it pinned | The gates are not in CI. Same call PS-F made (its D1). |
| D10 | **I ran commands inside the repo's ROS 2 Jazzy sandbox** (`.cache/external-evals/runtime/`, read-only `--help` invocations under `bwrap`, `--unshare-net`) | Turning six [UNVERIFIED-SYNTAX] flags into measurements is worth ten minutes on a one-session day. Nothing was installed, nothing entered `.parcel/`, no topic was published | **Jazzy is not Humble.** Everything from it is labelled `[MEASURED-JAZZY]` and the sheet still says *run `--help` on the Orin*. |

**No blocker.** Every deviation above is a declared judgement call. Two of them
(**D1**, **D2**) are **owner decisions the day cannot make for itself** and
should be settled tonight.

---

## 5 · Gate run — as instructed

```console
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && \
  .parcel/bin/python -m pytest tests/test_bags_roundtrip.py tests/test_portability_proof.py \
                              tests/test_capture_envelope.py -q
........................................................................ [ 93%]
.....                                                                    [100%]
77 passed in 3.60s
```

```console
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T12:01:23Z)
[  FAIL] HARD  ruff                       20 violation(s), baseline 7, new 13 ->
      scripts/parcel_capture/ingest/__init__.py::I001; ingest/dds.py::ISC004;
      ingest/fake.py::ISC004; ingest/l2.py::RUF046; ingest/realsense.py::ISC004;
      rosbag2.py::F401; rosbag2.py::ISC004; rosbag2.py::RUF100;
      syncevents.py::C408; syncevents.py::F541; syncevents.py::ISC004;
      syncevents.py::RUF022; syncevents.py::RUF046
[  PASS] HARD  hard-safety                collisions=0 false_arrival=0 …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.46s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.41s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.33s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.37s
[  PASS] HARD  default-suite              4688 passed, 9 skipped, 36 deselected in 198.34s
RESULT: FAIL — 1 hard gate(s) red: ruff
  elapsed 210.4s
```

**RESULT: FAIL — 1 hard gate(s) red: ruff.** Recorded rather than quietly
re-run, and **not attributable to PS-K**:

- All **13** new violations are in `scripts/parcel_capture/ingest/*`,
  `rosbag2.py` and `syncevents.py` — files owned by **PS-G** (the ingest layer +
  rosbag2 primary path) and **PS-I** (the sync-event clock redesign), both
  **in flight**. `ls -l` at 12:01:34 UTC showed `rosbag2.py` and `sidecar.py`
  mtime **08:01 local = 12:01 UTC** — written in the same minute the gate ran.
- PS-K owns no `.py` file and cannot redden or green `ruff` (M12).
- The nine other hard gates are green, including `default-suite`
  (**4688 passed**).

### 5b · Re-run at 12:11 UTC — still red, and **more** red, still not PS-K

```console
$ .parcel/bin/python scripts/ci_gate.py --tier commit
[  FAIL] HARD  ruff        20 violation(s), baseline 7, new 13 ->
      scripts/parcel_capture/syncevents.py::C408,F541,ISC004,RUF022,RUF046;
      tests/test_capture_ingest.py::B017,F401,RUF059;
      tests/test_rosbag2_sidecar.py::F401,RUF059;
      tests/test_syncevents.py::C408,F401,I001
[  FAIL] HARD  default-suite   9 failed, 4861 passed, 9 skipped, 36 deselected in 197.42s
    FAILED tests/test_syncevents.py::test_a_seeded_500ms_step_between_rituals_is_reported_as_a_step
    FAILED tests/test_syncevents.py::test_two_brackets_alone_cannot_locate_a_step_and_say_so
    FAILED tests/test_syncevents.py::test_missing_two_of_five_flashes_widens_the_uncertainty
    FAILED tests/test_syncevents.py::test_a_runaway_threshold_is_refused_rather_than_becoming_a_fit
    FAILED tests/test_syncevents.py::test_one_matched_pair_becomes_one_bracketed_clock_sample
    FAILED tests/test_syncevents.py::test_the_fit_round_trips_through_the_bag_sidecar_extra_by_digest
    FAILED tests/test_syncevents.py::test_a_synthetic_fit_must_be_labelled_and_a_physical_one_must_not_be
    FAILED tests/test_syncevents.py::test_the_fit_carries_a_non_empty_does_not_prove
    FAILED tests/test_syncevents.py::test_the_cli_runs_as_a_plain_script_with_no_pythonpath
RESULT: FAIL — 2 hard gate(s) red: ruff, default-suite
  elapsed 208.2s
```

**Attribution, measured rather than asserted:**

```console
$ ls -l --time-style=+%H:%M:%S scripts/parcel_capture/syncevents.py tests/test_syncevents.py ; date -u
-rw-rw-r-- … 143753 08:11:24 scripts/parcel_capture/syncevents.py
-rw-rw-r-- …  54630 08:02:22 tests/test_syncevents.py
Thu Aug 13 12:11:28 PM UTC 2026
```

`syncevents.py` was rewritten **four seconds** before that `date` (08:11:24 local
= 12:11:24 UTC): **PS-I is mid-write.** Every failing path in both runs belongs to
PS-I (`syncevents`) or PS-G (`ingest`, `rosbag2_sidecar`). PS-K created or edited
exactly three `.md` files under `session/` (M12) and cannot move either gate.

**Honest statement of the gate's status for this card: RED, twice, cause
attributed to two named in-flight cards, and I did not re-run until it went
green because that would be waiting on someone else's work rather than reporting
it.** The eight other hard gates are green in both runs, and `default-suite` was
green in the first run with **4,688 passed** before PS-I's test file landed.

---

## 6 · Findings handed to other cards / the owner

1. **Two owner decisions are needed tonight, not tomorrow** (D1, D2): whether
   the session may include **locomotion** (takes T10/T13, otherwise hand-carried)
   and whether an **unattended overnight charge** is permitted (T16c, otherwise
   dog-off).
2. **The whole take script needs ≈425 GiB free** at the recommended profile, and
   **256 GiB buys only ≈45 recorded minutes** (M9). If tonight's `df -h`
   (TONIGHT_CHECKLIST N0) is under that, the profile must step down **before
   T3** — never mid-day, because camera intrinsics are per-profile.
3. **For PS-G:** `--custom-data KEY=VALUE`, `--storage-preset-profile
   {none,fastwrite,zstd_fast,zstd_small}` and `--max-bag-duration` (default 0)
   all exist in the Jazzy `ros2 bag record` (M6). The preset removes the
   silently-ignored-YAML-key risk in tonight's hand-written storage config, and
   `--custom-data` puts the take id inside the bag.
4. **For PS-I:** the take script's T3/T14 are the **producers** of the sync
   events your fitter consumes. T3 §4's event×device table is the claim about
   which pairs are bridged; if a pair is missing there, no fit can recover it.
   T14 records `elapsed T3 → T14` explicitly — that is the drift baseline.
5. **For PS-F / the pack index:** `session/README.md` still lists four sheets and
   an order of operations with no takes and no tonight-checklist (D8).
6. **For PS-D:** run-sheet §7A now asks the attestation to report the nine
   channels C0.3's table predates, plus the eleven payload fields — the operator
   is told to fill them **from the attestation, not by eye**.

---

## 7 · does_not_prove

- **Nothing in the take script has been executed, and nothing in it can be.** It
  is blank paperwork written the day before by someone who has never seen this
  rig, this room, or this robot. Every measured claim in §2 is about the
  **documents** — that their citations resolve, their sections are stable, their
  takes have purposes and durations. **None of it is evidence about the robot,
  the sensors, or the data.**
- **A take script is not a session.** Six green gates prove the sheet is
  internally consistent, traceable and honest about its own blankness. They prove
  nothing about whether it is *followable*, and the first operator to hold it
  will find things wrong with it.
- **The durations are estimates and they are optimistic.** They assume nothing is
  being debugged, no cable is missing, and every command works first time. The
  ≈6-hour day is arithmetic on those estimates, not a schedule anyone has run.
- **The disk figures are derived from a model, not measured.** They come from
  `BANDWIDTH_BUDGET.md`, whose sustained-write number was measured **on the dev
  host only** and explicitly not extrapolated to the Orin. If the Orin's real
  write path is slower, every take in the ledger is longer or smaller than
  written.
- **M6/M7 were measured on ROS 2 Jazzy, not Humble, and not on the Orin.** Flags
  move between distros. `--custom-data` in particular may not exist on the
  Orin's distro. The sheet labels every one of them `[MEASURED-JAZZY]` and still
  instructs the operator to run `--help` there.
- **Every topic name, message field, rate and payload clock in the script is
  [EXT]** — documentation and field reports about *other* Go2 EDUs, via
  `CHANNEL_MATRIX.md`, which says so itself. Take T0 exists to start replacing
  them; one day will not finish the job.
- **I did not verify that any take produces solvable calibration data.** The
  script is designed so the *inputs* the standard tools ask for exist and are
  well-formed — rest before excitation, non-constant rate, separate bags,
  non-parallel planes, locked exposure. **Whether GLIM, FAST-LIO2, Multi-LiCa,
  `ros2_calib` or `direct_visual_lidar_calibration` actually converge on these
  bags is a next-week question**, and if they do not, the fault may well be in
  these takes.
- **The sync ritual is a mechanism, not a measurement.** T3/T14 produce *events*.
  Turning them into an offset, a drift rate and an uncertainty is fitting work
  that happens afterwards, and it may find the events were not sharp enough. That
  two published quadruped-dataset teams do this is [EXT]; **we never have.**
- **§4A is an eyeball judgement, not an overlap measurement.** "A shared patch
  roughly 1 m × 1 m" is a person looking at a screen. It quantifies no solid
  angle and no point density, and a `CONFIRMED` verdict does **not** promise any
  calibration tool will converge. It is built to catch the catastrophic case —
  no shared view at all — while the bracket can still move.
- **The 30-minute core is a claim about irreversibility, not about sufficiency.**
  Completing it does not make the session good; skipping it makes everything else
  in the session unusable. Those are different statements and only the second is
  argued here.
- **`ci_gate` is currently red**, on `ruff`, from two other cards' in-flight
  files (M14). PS-K contains no executable code and can neither redden nor green
  any gate in it — which also means **a green `ci_gate` would have proved nothing
  about this card either.**
