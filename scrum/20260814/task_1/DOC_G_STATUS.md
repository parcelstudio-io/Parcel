# DOC-G — durable backlog + status honesty (2026-08-14)

**Card:** DOC-G (folds into AU-F per REVISED_BOARD) · **Executor:** Opus
stand-in · **Date:** 2026-08-14

## What landed

| Deliverable | Location |
|---|---|
| S-1 Opus verification | [`S1_STATUS.md`](S1_STATUS.md) §Opus verification |
| Orin / mount / S-2 / Isaac blockers | [`backlog/BLOCKED.md`](../../../backlog/BLOCKED.md) B9–B13 |
| PE-D / SG-E / camera-plausibility / rosbag loss | [`backlog/NEXT.md`](../../../backlog/NEXT.md) N23–N26 |
| S-1 Orin-name + Humble-parser unverified | [`backlog/UNVERIFIED.md`](../../../backlog/UNVERIFIED.md) U37–U38 |

## `docs/CURRENT_STATUS.md` — skipped this pass

**Why:** the page is a 2026-08-04 desktop capability matrix spanning navigation,
audio, duplex, packaging and more. A honest full refresh needs measurements
this desk does not have (Orin unread, H-2 NOT RUN, no new acoustic/hardware
commissioning today). Patching only the capture rows without re-dating the
whole snapshot would imply the rest of the matrix was re-verified on
2026-08-14.

**Honest substitute:** this task's `S1_STATUS.md`, `REVISED_BOARD.md`, the
backlog entries above, and S-2's `STAGE0_COMMAND_ADDENDUM.md` (FINALIZE
BLOCKED ON H-1) are the operational truth for Stage-0 / capture readiness.
Update `docs/CURRENT_STATUS.md` in a dedicated pass after H-1/H-2 produce
named Orin evidence — or with an explicit "software-only, hardware NOT RUN"
dated banner if AU-F requires a pointer sooner.

## Closed-by-S-1 residuals (do not re-open as unfinished)

These DOC-G bullets from `PARALLEL_ENGINEERING_CARDS.md` are **software-closed**
by S-1; Orin verification remains U37/B10:

- sync fit wired into real rosbag2 sidecar (digest-bound);
- `VENDOR_VIDEO` media-stack dependency (not motion SDK);
- CameraInfo/TF/calibration capture completeness **gates** (plan + preflight +
  GO-RECORD).

## Pointers for AU-F

- Close audit landed: [`AU_F_FABLE_REVIEW.md`](AU_F_FABLE_REVIEW.md).
- Attempted today: S-1 (verified), DOC-G (this file), S-2 templates drafted but
  finalize blocked (Sol-owned; do not edit-war).
- NOT RUN: H-1, H-2, H-3, PE-D, SG-E, IS-F, MR-C.
- Readiness verdict: **cannot** be `READY_FOR_STATIONARY_STAGE0` without H-2
  Orin evidence. Fixtures ≠ commissioning.
- Commit gate: re-run `ci_gate --tier commit` outside the agent sandbox before
  close (agent runtime denies `os.kill` → false reds on four SIGKILL/Habitat
  cases; focused S-1 suites are green).
