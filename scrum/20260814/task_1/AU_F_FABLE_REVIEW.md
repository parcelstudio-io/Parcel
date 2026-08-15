# AU-F — Fable close audit (2026-08-14)

**Reviewer:** Fable (AU-F / review authority; stand-in model) · **Date:** 2026-08-14  
**Baseline:** `5fe0619` · **Tree:** working tree (much uncommitted)  
**Board of record:** [REVISED_BOARD.md](REVISED_BOARD.md) (supersedes README board)  
**Brief:** [FABLE_REVIEW_BRIEF.md](FABLE_REVIEW_BRIEF.md) · **Morning ruling:** [AU-H_FABLE_REVIEW.md](AU-H_FABLE_REVIEW.md)

**Authority:** review and veto only. No product features implemented this pass.
MR-C / full Stage-0 capture remains unexecuted.

---

## Day readiness (exactly one)

# `NOT_READY`

H-1 (Orin identity), H-2 (no-dog Orin rehearsal), and H-3 (mount + measure)
are all **NOT RUN**. Plans, desktop fixtures, and Jazzy-sandbox bags cannot
produce `READY_FOR_STATIONARY_STAGE0`. H-3 was never filled, so
`DEGRADE_MMP_ONLY` is also unavailable — that path requires a completed geometry
sheet + photo set.

---

## Verdict table

| Card | Verdict |
|---|---|
| **S-1** Calibration/TF completeness gate | **CONFIRMED** |
| **S-2** Stage-0 command addendum (T7–T10) | **PARTIAL — FINALIZE_BLOCKED_ON_H1** (MAJOR: combined-sheet storage path nests inside output dir) |
| **DOC-G** Durable backlog + status honesty | **CONFIRMED** |
| **H-1** Orin identity | **NOT RUN — Orin unread / operator** |
| **H-2** No-dog Orin rehearsal | **NOT RUN — blocked on H-1; no Orin evidence** |
| **H-3** Mount + measure | **NOT RUN — operator; geometry sheet blank** |
| **PE-D** (deferred) | **NOT RUN — deferred; backlog N23** |
| **SG-E** (deferred) | **NOT RUN — deferred; backlog N24** |
| **IS-F** (deferred) | **NOT RUN — deferred; backlog B13** |
| **MR-C** / full Stage-0 session | **NOT RUN — hard-stop; next session only** |
| **OR-1** (out-of-board H-2 harness) | **PARTIAL — desk/sandbox harness only; does not close H-2** |

---

## Close gate (executed, unsandboxed)

Prior agent notes claimed sandbox `PermissionError` / SIGKILL false-reds. Re-run
outside the agent sandbox:

```text
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-14T22:08:24Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                … clean
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical
[  PASS] HARD  latency-tail-ledger        …
[  PASS] HARD  follow-bench-jerk-ratchet  …
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              5286 passed, 9 skipped, 36 deselected in 222.97s
RESULT: PASS — every hard gate green.
  elapsed 235.2s
```

**Finding:** the prior SIGKILL reds were agent-sandbox signal restrictions, not
product defects. Gate status for this tree: **PASS**.

Focused probe suite (this audit):

```text
$ .parcel/bin/python -m pytest \
    tests/test_rosbag2_sidecar.py::test_a_bag_with_no_camera_info_cannot_finalize_go_record \
    … (CameraInfo / profile / TF / sync / ledger / stage0 / no-arm pins) …
173 passed in 20.42s

$ .parcel/bin/python -m pytest tests/test_no_arm_pin.py -q
76 passed in 20.16s
```

---

## Answers to FABLE_REVIEW_BRIEF questions

### Q1 — Does the physical recording plan preserve profile-matched calibration and every required transform, or merely mention them?

**Software: yes, as first-class plan + gates — not prose.** Executed:

```text
recorded topics: 31
camera_info -> PRESENT x4:
  /camera/camera/{color,depth,infra1,infra2}/camera_info
/tf -> PRESENT
tf_static -> PRESENT
```

Support artifacts are a separate class in `channels.py` (`SUPPORT_ARTIFACT_ROWS=8`),
not fake payload channels. Payload matrix remains 28 channels / 25 rows.

**Does not prove:** D455 actually publishes those `camera_info` names on the Orin
(U37 / H-2).

### Q2 — Is clock/sync evidence bound into the finalized sidecar?

**Yes (wiring + digest).** `test_a_bound_sync_fit_lands_in_the_sidecar_by_digest`
PASS; a run with `claims_recoverable_time` and no fit cannot certify
(`test_a_run_claiming_recoverable_time_without_a_sync_fit_cannot_certify` PASS).

**Does not prove:** any physical cross-device sync fit (S1_STATUS §6.7).

### Q3 — Can missing/mismatched CameraInfo, TF, calibration or profile still produce GO-RECORD?

**No on the landed finalize path (was YES yesterday).** Executed refusals:

| Probe | Result |
|---|---|
| No CameraInfo | finalize refused; suite PASS |
| 848×480 stream / 1280×720 CameraInfo | refused PASS |
| Competing TF parents | refused PASS |
| `/tf_static` neither bag nor snapshot | refused PASS |
| One-byte calibration perturbation | digest verify fails PASS (fixture + real bytes) |
| P0 topic graph (images only) at preflight | `ok=False`, 5 refusals, `PreflightError` on `or_raise` |

**Nuance (not a silent gap):** `/tf` alone absent is a **finding**
(recorded-opportunistic), not a preflight refusal — static transforms via
`/tf_static` or snapshot carry the GO-RECORD spatial gate. Optical frame with
no parent still refuses at finalize.

### Q4 — Are T7–T10 executable, run-specific commands rather than free-text handoff?

**Drafted yes; finalized no.** Combined + per-distro sheets exist; argv extracted
from markers equals `record_command(Rosbag2Plan(distro=…))` when paths match.
Header correctly stamps **FINALIZE BLOCKED ON H-1**.

### Q5 — Operator disk ledger from 91.87 MiB/s model; stale 84.60 removed from run-specific pack?

**Yes for this task's pack.** `DISK_LEDGER.md` quotes **91.87** MiB/s /
256 GiB → **41.4 min**; `tests/test_disk_ledger_doc.py` byte-identity + stale
reconstruction reddens (4 passed). 84.60 appears only as supersession/history
citations, not as operative arithmetic.

### Q6 — Recorder commands from distro-aware generator after help validation; no Humble-incompatible flag?

**Yes for generator + pins; finalize still blocked.** Humble argv omits
`--disable-keyboard-controls`. Injecting it raises `Rosbag2RefusedError`
(ZERO-bytes warning). Jazzy argv against Humble-shaped help refuses. Suites:
`tests/test_stage0_command_addendum.py` / `tests/test_stage0_addendum.py`
keyboard/help cases **34 passed** in the filtered run; full addendum suites
green under commit gate.

### Q7 — Did any capture change acquire a publisher, motion import, Unitree lease or command surface?

**No.** Recursive no-arm pin **76 passed**. `create_publisher` / `SportClient` /
`ControlManager` / `cmd_vel` hits in capture trees are deny-list / documentary
text (ingest auditor), not new publishers. `VENDOR_VIDEO` now declares modules
`()` + executable `ffmpeg`; `VENDOR_UWB` still `unitree_sdk2py` (unchanged pin).

### Q8 — Does every hardware claim name real Orin evidence; absent runs say NOT RUN?

**Yes in status/docs audited.** H-1/H-2/H-3 claimed NOT RUN. OR-1 honestly
labels desktop/Jazzy-sandbox results as not Orin evidence. No invented Orin
identity dump found.

### Q9 — Replay contract preserve raw fields/timing/provenance and reject oracle truth?

**NOT RUN — PE-D deferred (N23).** No `SensorFrameV2` product diff vs `5fe0619`.

### Q10 — If SG-E changed product code, are process-boundary attacks covered?

**N/A — SG-E deferred (N24).** No gateway product diff vs baseline.

### Q11 — Did Isaac remain a producer behind the same contract?

**N/A — IS-F deferred (B13).** Blocked on Ubuntu 22.04/24.04 host; this desktop
is 26.04.

### Q12 — Did every unfinished item move into durable backlog?

**Yes (DOC-G).** B9–B13, N23–N26, U37–U38 present with unblock steps. Verified
headers in `backlog/{BLOCKED,NEXT,UNVERIFIED}.md`.

### Q13 — Did MR-C remain unexecuted and scheduled only as separately staffed seated/stationary session?

**Yes.** DOC-G and board state MR-C / full Stage-0 as next session; hard-stops
intact. No bag/attestation/clock-map from a physical session today.

---

## Adversarial probes

| Probe | Status | Evidence |
|---|---|---|
| Remove/mismatch CameraInfo → refuse | **PASS** | pytest + real-bytes pins |
| Perturb one extrinsic/calibration byte → digest fail | **PASS** | `test_seeded_failure_one_perturbed…`, `test_real_complete_bag…one_real_byte…` |
| Disconnect TF edge / two competing parents → refuse | **PASS** | no-parent + competing-parents tests |
| Transient-local `/tf_static` → snapshot or refuse | **PASS** | snapshot substitute + neither-captured refuse |
| Remove sync fit from recoverable-time claim → fail | **PASS** | certifiable-time-without-fit refuse |
| Wrong ROS topic / zero messages → preflight not “present” | **PASS** | P0 graph: 4×camera_info + `/tf_static` refusals; type/unparseable pins in preflight suite |
| Oracle semantic ID/true pose into SensorFrameV2 | **NOT RUN** | PE-D not landed |
| Kill/freeze fake gateway after nonzero command | **NOT RUN** | SG-E not landed |
| Capture trees: publisher/motion/lease + mutant pin | **PASS** | no-arm 76 passed; search shows deny-list only |
| Restore stale 84.60 in run-specific pack → pin reddens | **PASS** | `test_the_stale_84_60_era_ledger_fails_the_headline_check` |
| Inject `--disable-keyboard-controls` into Humble / strip help flag | **PASS** | inject raises; help-mismatch suites pass |
| Hardware probes on Orin (identity, drivers, 10-min bag, mount) | **NOT RUN** | **blocker: H-1 unread; no Orin session; H-3 blank** |

### MAJOR finding (S-2 Part A sheet)

```text
DEFAULT_OUTPUT_DIR            = /data/parcel/session
DEFAULT_STORAGE_CONFIG_PATH   = /data/parcel/session/mcap_storage.yaml
→ storage config path is INSIDE the record output directory
```

`STAGE0_COMMAND_ADDENDUM.md` instructs emit-config-then-record. Creating the
storage file creates the output folder; Jazzy `ros2 bag record` then refuses
(“Output folder … already exists”) — executed earlier in S-2 Part B (B-M5) and
reconfirmed by path nesting this audit. **Per-distro sheets**
(`STAGE0_ADDENDUM_{HUMBLE,JAZZY}.md`) place storage at
`/data/parcel/stage0/mcap_storage.yaml` **outside** `take01` — use those after
H-1, or fix the combined defaults before any operator follows Part A literally.

Severity: **MAJOR** (would lose the first take if the combined sheet were
treated as operative). Does not flip the card to REJECTED because FINALIZE is
already blocked and the safer sheets exist; it **does** forbid treating
`STAGE0_COMMAND_ADDENDUM.md` as the run sheet of record until the path moves.

**Disposition (post-audit, same day):** fixed. Combined defaults now use
`DEFAULT_STORAGE_CONFIG_PATH = /data/parcel/mcap_storage.yaml` (outside
`/data/parcel/session`). Addendum regenerated; pin
`test_storage_config_path_is_outside_the_bag_output_dir` added (22 S-2 pins
green). FINALIZE remains blocked on H-1; readiness stays `NOT_READY`.

---

## Diff-vs-OWNS attribution

### S-1 (claimed OWNS)

| Path | Attribution |
|---|---|
| `scripts/parcel_capture/rosbag2.py` (+481) | S-1 OWNS |
| `scripts/parcel_capture/sidecar.py` (+644) | S-1 OWNS |
| `scripts/parcel_capture/preflight.py` (+224 support reconciliation) | S-1 OWNS (narrowed) |
| `src/parcel_robot/capture/channels.py` (+421 support class) | S-1 OWNS (narrowed) |
| `tests/test_rosbag2_sidecar.py`, `test_capture_envelope.py`, `test_capture_preflight.py` | S-1 OWNS |
| `scrum/20260814/task_1/DISK_LEDGER.md`, `S1_STATUS.md` | S-1 OWNS |
| `scripts/parcel_capture/record.py` (17 lines VENDOR_VIDEO) | **disclosed deviation** — board item 5 |
| `tests/test_disk_ledger_doc.py` | **disclosed deviation** — ledger pin/generator |

No silent ownership grab of PE-D/SG-E/IS-F surfaces.

### S-2 (claimed OWNS — two concurrent lanes)

| Path | Attribution |
|---|---|
| `scripts/parcel_capture/stage0_addendum.py` | Shared; Part A public API + Part B additive region (collision documented in `S2_STATUS.md` §B5–B6) |
| `tests/test_stage0_command_addendum.py`, `STAGE0_COMMAND_ADDENDUM.md` | Part A |
| `tests/test_stage0_addendum.py`, `STAGE0_ADDENDUM_{HUMBLE,JAZZY}.md` | Part B |
| `S2_STATUS.md` | Shared (Part B appended) |

### Outside S-1/S-2 OWNS (do not mis-attribute)

| Path | Card |
|---|---|
| `scripts/parcel_capture/orin_rehearsal.py`, `tests/test_orin_rehearsal.py`, `ORIN_RUNBOOK.md`, `OR1_STATUS.md` | **OR-1** — H-2 software assist; **not** H-2 completion |
| `backlog/BLOCKED.md`, `NEXT.md`, `UNVERIFIED.md` | DOC-G |

---

## Card-by-card findings

### S-1 — CONFIRMED

All six REVISED_BOARD items have executed software evidence and seeded
reddens. Opus verification section in `S1_STATUS.md` matches this audit's
probes; the only disagreement was the sandbox gate false-red, now cleared.

**Claim refutation:** “GO-RECORD still possible without CameraInfo/TF” — **refuted**
for the rosbag2 finalize path. “84.60 still drives operator arithmetic in this
task pack” — **refuted**.

### S-2 — PARTIAL — FINALIZE_BLOCKED_ON_H1

Templates + generator + pins are real. Distro unread (B9/B12). Combined sheet
has the nested storage-config MAJOR defect. Do not claim T7–T10 as operative
commands of record.

### DOC-G — CONFIRMED

B9–B13 / N23–N26 / U37–U38 landed with unblock steps. `docs/CURRENT_STATUS.md`
refresh correctly skipped (would imply re-verification of unrelated matrix).
Honesty substitute documented.

### H-1 / H-2 / H-3 — NOT RUN

- H-1: no `nv_tegra_release` / `ls /opt/ros` evidence in tree.
- H-2: OR-1 harness ≠ Orin rehearsal evidence.
- H-3: `MOUNT_GEOMETRY_SHEET.md` still blank by design (“nothing below has been
  measured”).

### Deferred PE-D / SG-E / IS-F

Present in backlog only. **Not silently claimed done.** No product diffs.

---

## Finding severity summary

| Sev | Finding |
|---|---|
| **BLOCKING (day readiness)** | H-1, H-2, H-3 all NOT RUN → `NOT_READY` |
| **MAJOR** | `STAGE0_COMMAND_ADDENDUM.md` / Part A defaults nest storage config inside output dir (take-losing) |
| **MAJOR (known, backlog)** | Support topic names UNVERIFIED on Orin (U37); Humble topic-list format UNVERIFIED (U38) |
| **INFO** | `/tf` absence is finding-not-refusal at preflight; spatial GO-RECORD rides `/tf_static`+snapshot |
| **INFO** | Prior ci_gate SIGKILL failures were sandbox artifacts; unsandboxed gate PASS |
| **CLEAR** | No-arm pin green; MR-C unexecuted; deferred cards not claimed done |

---

## Claim refutation (blocking / major claims from the day)

| Claim (heard or implied) | Ruling |
|---|---|
| Software P0 (no camera_info / no TF on plan) still open | **Refuted** — plan has 31 topics; gates refuse P0 graph |
| Desk fixtures / Jazzy bags ⇒ ready for stationary Stage-0 | **Refuted** — readiness `NOT_READY`; board rule explicit |
| S-2 finalized argv of record | **Refuted** — FINALIZE BLOCKED ON H-1 |
| H-2 done because OR-1 / sandbox P5 passed | **Refuted** — OR-1 PARTIAL harness; H-2 NOT RUN |
| Mount done / DEGRADE_MMP_ONLY available | **Refuted** — geometry sheet blank |
| PE-D / SG-E / IS-F progressed in product code today | **Refuted** — backlog only |
| Commit gate red on SIGKILL | **Refuted** — unsandboxed PASS 5286 |

---

## does_not_prove

1. Orin JetPack / Ubuntu / `/opt/ros/*` identity (H-1).
2. Any driver, topic rate, QoS, or 10-minute bag on the real Orin (H-2).
3. Mount geometry, FOV overlap, or photos (H-3).
4. That RealSense publishes `camera_info` under the derived names (U37).
5. That Humble `ros2 topic list -t` matches the Jazzy parser form (U38).
6. Physical sync-event time recovery.
7. Extrinsic *values* (tape measure remains evidence-with-uncertainty).
8. Humble `--verify-help` against an Orin-installed recorder binary.
9. That following `STAGE0_COMMAND_ADDENDUM.md` as written would succeed a take
   (MAJOR path defect) — per-distro sheets are the safer draft.
10. `SensorFrameV2` replay / gateway authority / Isaac producer behavior (deferred).
11. Anything about robot LAN, firmware pin, stand, gait, or Parcel motion —
    none authorized or executed.
12. A green ci_gate does not substitute for H-2 Orin evidence.

---

## Backlog residuals (must remain)

| ID | Residual |
|---|---|
| **B9** | H-1 Orin identity unread |
| **B10** | H-2 no-dog rehearsal NOT RUN |
| **B11** | H-3 mount + measure NOT RUN |
| **B12** | S-2 FINALIZE blocked on B9 |
| **B13** | IS-F blocked on 22.04/24.04 host |
| **N23** | PE-D SensorFrameV2 replay |
| **N24** | SG-E gateway slice |
| **N25** | Camera plausibility samples |
| **N26** | Rosbag interior-loss attribution |
| **U37** | S-1 support topic names on Orin |
| **U38** | Humble topic-list line format |
| *(open)* | Fix Part A storage-config path nesting before any use of the combined addendum |

---

## Working agreements / hard-stops

Agreements 1–11 and hard-stop rules from README carry forward and were not
weakened. No Parcel motion, no robot-LAN join before firmware pin, no stand
without two people, no full Stage-0 at end of engineering day.

---

*End of AU-F close audit.*
