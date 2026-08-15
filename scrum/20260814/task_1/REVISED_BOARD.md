# 2026-08-14 — revised board: hardware first, mount today

**Author:** Fable (AU-H authority) · **Supersedes:** the priority board and
schedule in [README.md](README.md) r1 · **Ruling:**
[AU-H_FABLE_REVIEW.md](AU-H_FABLE_REVIEW.md) — `ACCEPT_FINDINGS_REORDER_BOARD`
**Owner steer:** *get the rig mounted on the robot body soon.*

Sol's working agreements 1–11, hard-stop rules, and the three-way readiness
verdict (`READY_FOR_STATIONARY_STAGE0` / `DEGRADE_MMP_ONLY` / `NOT_READY`)
**carry forward verbatim** from README.md. Only the cards and their order
change.

## The one-line rationale

Every line of capture software now targets an Orin whose OS and ROS distro
**nobody has ever read**, while the owner's actual goal — the rig on the dog —
sits inside a deferred card it never needed to be in. Today inverts that:
verify the hardware first, mount today, and narrow the software work to the
one verified P0 (the calibration/TF gap).

## Board

| ID | Card | Owner | Depends on | When |
|---|---|---|---|---|
| **H-1** | Orin identity + bring-up start | **Operator** | — | **first 30 min** |
| **H-2** | No-dog Orin rehearsal (drivers → topics → record → measure) | Operator + Sol assist | H-1 | after H-1 |
| **H-3** | **Mount + measure the rig on the dog** | **Operator** | — (independent of all software) | **today** |
| **S-1** | Calibration/TF completeness gate (narrowed MR-A) | Sol/agents | — | now, parallel |
| **S-2** | Run-specific Stage-0 command addendum (T7–T10 rows) | Sol/agents | **H-1's distro answer** | after H-1 |
| **AU-F** | Close audit, readiness verdict, backlog consolidation | Fable | all attempted | close |

**Deferred to backlog with unblock steps (not deleted):** PE-D (`SensorFrameV2`
replay contract — unblocks after S-1's truth table freezes), SG-E (W0-C/W0-F
gateway slice — next software tranche; required before any Parcel-driven
motion, not before mounting), IS-F (Isaac lane — blocked on an Ubuntu
22.04/24.04 host or container; this desktop is 26.04). DOC-G folds into AU-F.

```text
H-1 (5-min identity, then bring-up)──> H-2 rehearsal ──> [next session: Stage-0 capture]
H-3 mount + measure  ────────────────────────────────────┘   (independent, today)
S-1 calibration/TF gate ──> S-2 command addendum (needs H-1's distro)
```

---

## H-1 — Orin identity + bring-up start · Operator · first 30 minutes

Power the Orin on the bench (**not** on the robot LAN; the Go2 firmware
version is still unread and the pin is a security control). Then:

```bash
cat /etc/nv_tegra_release; lsb_release -a; uname -r
ls /opt/ros; python3 --version; lsblk; df -h
```

- **JetPack 6.x / Ubuntu 22.04 / `/opt/ros/humble` present** → proceed
  straight into [session/TONIGHT_CHECKLIST.md](../../20260813/task_1/session/TONIGHT_CHECKLIST.md)
  N1→N7 (usbfs + reboot, pyrealsense2 + 10-min frame count, fio tail
  throughput, rosbag2-mcap + **the ROS driver installs PS-P added**, L2 bench,
  network pinning, the `python3.10 -c "import parcel_robot.capture"` check).
- **Anything else (5.x / Ubuntu 20.04 / Foxy / no ROS)** → **STOP. Report the
  exact output.** Do not improvise an upgrade: the golden-image ADR's two-dock
  rule is unmet (one dock on hand — it must not be flashed). S-2 and the
  recorder argv retarget to what is actually installed; that is a software
  problem and it is ours, not the bench's.

Every result — either way — goes into the run header of
[session/STAGE0_RUN_SHEET.md](../../20260813/task_1/session/STAGE0_RUN_SHEET.md)
as the day's first recorded evidence.

## H-2 — no-dog rehearsal · Operator + Sol assist · after H-1

Sol's MR-B, unchanged in substance: drivers launched, topics enumerated with
`ros2 topic list -t` and rates with `ros2 topic hz`, the recorder argv rendered
by `Rosbag2Plan(distro=<observed>)` and validated with `--verify-help`
**before** first use, a 10-minute bench recording of the real D455 through the
real command line, sustained-write measured on the actual record target,
preflight run end-to-end. Exit: measured evidence in `MRB_STATUS.md`, or a
named blocker. **The first time the stack runs must not be on the dog** — this
card is where it runs first.

## H-3 — mount + measure · Operator · today, independent of all software

The owner's card. Everything here works with the dog **powered off or lying**,
nothing joins the robot LAN, and no ROS is required.

1. **Safety pre-reads:** [session/SAFETY_BRIEF.md](../../20260813/task_1/session/SAFETY_BRIEF.md)
   — mat down; payload-security check; the PS-F finding stands: *a stop press
   drops a standing dog onto the payload*, so no stand today without a second
   person present, and no stand is required for any step below.
2. **Mount** bracket, Orin, D455, add-on L2. Cable strain relief and
   pinch-point checks per the brief.
3. **Pre-torque FOV gate (geometric):** before final bolt-up, check the
   built-in and add-on LiDAR datasheet FOV cones against the measured mount
   poses for a substantial shared region. Record the result as
   **geometric-only, lower confidence** — the live RViz two-cloud overlap
   check is a named follow-up gate in H-2/next session. If the cones do not
   overlap, move the L2 now: after torque it is unfixable, and no post-hoc
   LiDAR-to-LiDAR calibration tool can recover an extrinsic between units
   that never share a view.
4. **Measure:** fill
   [session/MOUNT_GEOMETRY_SHEET.md](../../20260813/task_1/session/MOUNT_GEOMETRY_SHEET.md)
   completely — tape-measured offsets and orientations of D455, both LiDARs,
   and the Orin relative to `base_link`, with stated uncertainty. This is
   **evidence with uncertainty, never calibrated TF** (working agreement 6).
5. **Photograph** per [session/PHOTO_LIST.md](../../20260813/task_1/session/PHOTO_LIST.md),
   including witness marks before any re-measure.

Exit: a filled geometry sheet + photo set. **This is durable value even if
every other card today fails** — it is the `DEGRADE_MMP_ONLY` path executed
deliberately rather than as a fallback.

## S-1 — calibration/TF completeness gate · software · now

The verified P0 (executed: 4 optical streams recorded, `camera_info` ABSENT,
`/tf` ABSENT, `/tf_static` ABSENT). Scope, from Sol's MR-A narrowed to what
does not depend on the unverified distro:

1. Model **support artifacts** (`CameraInfo` per active optical stream, `/tf`,
   `/tf_static` or a machine-readable static-transform snapshot, calibration
   digests) as their own class beside the 28 payload channels — not as fake
   channels, not as prose.
2. Add them to the rosbag2 recording plan; extend preflight reconciliation so
   a required-but-missing support topic is a refusal.
3. **Sidecar gate:** a bag whose active image profile lacks matching intrinsics,
   or whose sensor transforms are absent/ambiguous, cannot finalize
   `GO-RECORD`. Seeded tests: remove `CameraInfo` → refuse; mismatch profile
   (848×480 stream, 1280×720 calibration) → refuse; two competing TF parents →
   refuse; transient-local `/tf_static` published before record start →
   snapshot captured and verified, or refuse.
4. Wire the **sync-event fit into the real sidecar** (today it is proven only
   in isolation), bound by digest.
5. Fix the `VENDOR_VIDEO` dependency declaration (the RTP H.264 path needs a
   media stack, not the vendor motion SDK — PS-H's handoff).
6. **Regenerate the operator disk ledger** from `budget.py::render_document()`
   as a run-specific addendum under this task (84.60-era arithmetic in
   yesterday's status docs stays as history; nothing operator-facing may
   derive from it). Pin: a test reddens if any run-specific operator figure
   diverges from the generated model.

House rules apply: no publisher/motion/lease surface (the recursive no-arm pin
must stay green), fail closed, measured claims, seeded-failure table,
non-empty `does_not_prove`, ci_gate green.

## S-2 — run-specific Stage-0 command addendum · software · after H-1

Sol's MR-A item 6, gated on reality: named rows for T7 (RealSense driver
launch), T8 (L2 driver launch), T9 (Unitree overlay/DDS env), T10 (the actual
`ros2 bag record -s mcap` argv + storage config) — every command rendered from
`Rosbag2Plan(distro=<H-1's observed answer>)` after `--verify-help`, never
hand-copied. Both-distro templates may be drafted now; the addendum finalizes
only on H-1's answer. Historical 20260813 sheets are provenance, not edited.

## AU-F — close · Fable

Fresh ci_gate; diff-vs-OWNS; the review brief's remaining questions answered
with executed evidence; adversarial probes from
[FABLE_REVIEW_BRIEF.md](FABLE_REVIEW_BRIEF.md) run against S-1's gates; every
unfinished item into `backlog/` with a concrete unblock step; and exactly one
readiness verdict recorded. Plans or desktop fixtures alone cannot produce
`READY_FOR_STATIONARY_STAGE0` — that requires H-2 evidence from the actual
Orin.

## What today will not do

No Parcel process commands motion. Nothing joins the robot LAN before the
firmware version is read from the app and checked against the pin. No stand
without two people. No full Stage-0 capture session at the end of a tired
engineering day — that is the next session, staffed as such, exactly as Sol's
hard-stop rules specify.
