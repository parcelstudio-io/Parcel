# 2026-08-14 task 1 — Unitree mount readiness and perception evidence

> **SUPERSEDED IN PART (2026-08-14, Fable/AU-H):** the priority board,
> dependency order and day schedule below are replaced by
> [REVISED_BOARD.md](REVISED_BOARD.md) per the ruling in
> [AU-H_FABLE_REVIEW.md](AU-H_FABLE_REVIEW.md) —
> `ACCEPT_FINDINGS_REORDER_BOARD` (hardware-first; mount split out of MR-C and
> scheduled today; PE-D/SG-E/IS-F deferred to backlog). The **working
> agreements, hard-stop rules and readiness verdicts below remain in force
> verbatim.** This document is otherwise preserved as authored by Sol.

**Baseline:** `5fe0619` on clean `main`, equal to `origin/main`

**Opening gate:** `ci_gate --tier commit` passed on 2026-08-14 with
**5,071 passed, 9 skipped, 36 deselected**.

**Previous task:**
[20260813/task_1](../../20260813/task_1/README.md), whose terminal software
audit is [AUDIT_CAPTURE_FABLE.md](../../20260813/task_1/AUDIT_CAPTURE_FABLE.md).

## Outcome for today

Make Parcel honestly ready for the **first sensor-only Unitree session**:

1. a mounted D455 + add-on L2 + Orin can produce a replayable, calibrated,
   timestamped dataset;
2. the no-dog Orin rehearsal either passes with evidence or fails with a named
   blocker;
3. issue an evidence-backed `READY_FOR_STATIONARY_STAGE0`,
   `DEGRADE_MMP_ONLY` or `NOT_READY` decision for the next physical session;
4. preserve a separate path toward governed autonomous motion without allowing
   that work to expand today's physical authority.

The success condition is **not** "the dog walks autonomously." It is:

> The same future perception consumer can distinguish sensor bytes, camera
> calibration, transforms, clock evidence and provenance, and no Parcel process
> can command physical movement during the session.

## Opening assessment

- The capture software is extensively tested against fixtures and test doubles.
- The physical session pack is still blank by design; no physical gate has
  passed.
- The primary D455 recording plan contains images and IMU, but no
  `CameraInfo`, `/tf` or `/tf_static`. That is a **P0 dataset-completeness gap**
  before a bag is used for SLAM or camera–LiDAR fusion.
- `sidecar_sync_block()` is exercised in a test but is not wired into the real
  sidecar.
- Stage-0 command transcription has no first-class rows for the RealSense
  launch, L2 launch, Unitree overlay and actual `ros2 bag record` command.
- The historical take script still repeats the superseded **84.60 MiB/s** disk
  model in operator-facing tables. The generated current plan is
  **91.87 MiB/s / 323.0 GiB/hour**. A run-specific copy must be generated or
  checked from `budget.py`; hand-transcribing yesterday's table is forbidden.
- Historical operator commands still hard-code `--disable-keyboard-controls`,
  which Humble does not accept, even though the landed command generator
  correctly omits it. The run-specific recorder argv must come from
  `Rosbag2Plan` after validation against the installed `--help`; copying the old
  command can exit before writing a byte.
- This desktop currently sees no D455, L2 or Go2 link and has no ROS 2, Docker,
  Isaac Sim, RealSense SDK, Unitree SDK or CycloneDDS in `.parcel`.
- W0-A typed physical provenance and W0-B commissioning landed. The isolated
  W0-C gateway and W0-F product authority gate did not.

## Priority board

| ID | Card | Owner | Depends on | Priority | Opening status |
|---|---|---|---|---|---|
| MR-A | Complete the physical recording contract | Sol | — | **P0** | ready |
| MR-B | Run the no-dog Orin/driver/recorder rehearsal | Operator + Sol | MR-A | **P0** | hardware-gated |
| MR-C | Next-session stationary Stage 0 and dataset preservation | Operator + safety observer | MR-B | **NEXT** | deliberately not run today |
| PE-D | Freeze `SensorFrameV2` and build the replay-first seam | Sol | MR-A contract freeze | P1 | parallel after freeze |
| SG-E | Deliver today's bounded W0-C/W0-F gateway slice | Sol | — | P1 | parallel; not a Stage-0 blocker |
| IS-F | Prepare the Isaac RTX sensor lane behind `SensorFrameV2` | Sol | PE-D schema | P2 | stretch/parallel |
| DOC-G | Consolidate status and durable backlog entries | Sol | MR-A findings frozen | P1 | ready |
| AU-H | Adversarial review and close-or-carry-forward ruling | Fable | all attempted cards | **gate** | pending |

Detailed cards:

- [MOUNT_CAPTURE_CARDS.md](MOUNT_CAPTURE_CARDS.md): MR-A through MR-C.
- [PARALLEL_ENGINEERING_CARDS.md](PARALLEL_ENGINEERING_CARDS.md): PE-D through
  DOC-G.
- [FABLE_REVIEW_BRIEF.md](FABLE_REVIEW_BRIEF.md): AU-H.

## Dependency and execution order

```text
MR-A recording completeness
  ├──> MR-B no-dog Orin rehearsal ──> MR-C stationary physical capture
  └──> PE-D SensorFrame/replay contract ──> IS-F Isaac contract smoke

SG-E isolated gateway/authority slice runs independently.
DOC-G records all unfinished or hardware-gated work durably.
AU-H audits every attempted lane and decides what actually closed.
```

MR-A is the only implementation card allowed to block the sensor-only session.
SG-E is required before future Parcel-driven physical motion, but it must not
delay safe stationary data collection.

## Suggested day schedule

| Timebox | Work | Exit |
|---|---|---|
| 0–30 min | Freeze scope, topic/calibration truth table and no-motion rules | MR-A contract agreed |
| 30 min–3 h | MR-A implementation + focused tests; DOC-G starts in parallel | replayable calibration/TF/sync evidence specified and gated |
| 3–4 h | Full commit gate; generate the operator addendum and exact commands | no red software gate |
| 4–7 h | If Orin is accessible: MR-B. Otherwise PE-D + SG-E proceed | measured Orin result or explicit hardware blocker |
| 7 h onward | Finish MR-B or continue PE-D/SG-E/IS-F; do not start a tired physical session | measured readiness verdict |
| Close | AU-H audit, full gate, handoffs into backlog | no residual hidden in Scrum history |

## Global working agreements

1. **Nothing in this task authorizes Parcel motion.** Do not change
   `control.controller`, commissioning flags, `allowed_modes`, or call a Unitree
   motion API during MR-A/B/C.
2. **No vendor SDK enters `.parcel`.** Orin/ROS driver dependencies live in the
   supported deployment environment, not the desktop product venv.
3. **Historical Scrum is immutable.** Do not rewrite the 20260813 status
   records. Create a superseding operational addendum or a run-specific copy
   under this task and link the old template as provenance.
4. **Raw data and truth are separate.** Simulator semantic IDs, true pose and
   collision labels may reach a scorer, never the agent sensor contract.
5. **Unknown fails closed.** Missing calibration, unresolved TF, mismatched
   profile, uncertain clock mapping or absent topic is not silently defaulted.
6. **One source of profile truth.** Resolution, frame rate, intrinsics,
   distortion model, frame IDs and calibration digest travel together.
   Tape-measured mount geometry is evidence with uncertainty, not calibrated
   TF, and must never be relabelled as such.
7. **One source of recorder argv truth.** Operator commands are rendered from
   the distro-aware plan after `--verify-help`; they are not maintained as a
   second handwritten CLI in Markdown.
8. **No tuning to pass a test.** B5/B6 safety semantics remain owner-gated.
   Record B7/B8 decisions; do not silently alter frozen navigation behavior.
9. Every implemented card supplies focused tests, its exact commands/results,
   a seeded-failure case and a non-empty `does_not_prove` section.
10. `.parcel/bin/python scripts/ci_gate.py --tier commit` must be green at close.
11. Every incomplete, unverified or hardware-dependent item moves to
    `backlog/` with a concrete unblock step.

## Hard stop rules

MR-C is a **next-session card** and remains `NOT RUN` today. It may be scheduled
only after all of the following are true:

- MR-A is green and the selected camera profile has matching calibration;
- MR-B passed on the actual Orin and record destination;
- Go2 firmware is at or above the pinned version;
- the real topic names/types/QoS were observed, not copied from documentation;
- two people are present and two independent stop paths are named and tested;
- payload, bracket, cables and sensor fields of view pass the mechanical gate;
- free space and sustained recorder throughput cover the requested take;
- the clock ritual and raw recorder are running before the first valuable take.
- the clock ritual and raw recorder are running before the first valuable take;
- the run-specific disk ledger equals the current generated budget model.

If firmware is unknown or below the security pin, do not place the Orin or this
desktop on the robot LAN. MR-C also authorizes no stand or gait today; those
belong to a separately approved physical-motion session.

Failure takes the existing `DEGRADE-MMP` path: mount, measure, photograph and
record nothing. That is a valid result.

Today's close records exactly one readiness decision:

- `READY_FOR_STATIONARY_STAGE0`
- `DEGRADE_MMP_ONLY`
- `NOT_READY`

Plans or desktop fixtures alone cannot produce the first verdict.

## Definition of done

### Close — hardware unavailable

- MR-A implemented and adversarially tested.
- A run-specific Stage-0 capture addendum exists with the four missing command
  rows and calibration/TF/sync gates.
- PE-D has a reviewed contract plus at least one deterministic normalized
  replay fixture.
- SG-E reports an honest completed slice or a bounded carry-forward.
- Full commit gate green and DOC-G/AU-H complete.

### Close — Orin/sensors available

All of the above, plus:

- MR-B evidence from the actual Orin;
- a frozen driver/recorder/profile decision and a measured readiness verdict;
- MR-C prepared as the next separately staffed session, not executed at the end
  of this engineering day.

## What a green task will not prove

- It will not prove SLAM accuracy, camera–LiDAR fusion accuracy or owner
  tracking.
- It will not prove Unitree gateway crash-stop behavior or safe autonomous
  motion.
- It will not prove stairs, hills, outdoor crowds, weather or public-city
  operation.
- It will not make Isaac simulation evidence equivalent to physical evidence.
- It will not close `P5-G-INSTALL` while the golden-image/two-dock precondition
  remains unmet.
