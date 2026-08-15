# AU-H — Fable review of the 2026-08-14 board, and the revision

**Reviewer:** Fable · **Date:** 2026-08-14 · **Baseline:** `5fe0619`
**Reviewing:** Sol's board as authored ([README.md](README.md) r1,
[MOUNT_CAPTURE_CARDS.md](MOUNT_CAPTURE_CARDS.md),
[PARALLEL_ENGINEERING_CARDS.md](PARALLEL_ENGINEERING_CARDS.md))
**Owner steer this morning:** *"I want our robot to get mounted on the robot
body soon."*

## Verdict: `ACCEPT_FINDINGS_REORDER_BOARD`

Sol's central finding is real, verified by me, and I missed it yesterday. Sol's
working agreements are sound and are kept verbatim. **The sequencing is wrong
for the owner's goal**, and one card the owner explicitly asked for does not
exist. The board is revised, not replaced.

---

## 1. What Sol got right — verified, not taken on trust

**The P0 is real and it is mine to own.** I executed the recording plan:

```
recorded topics: 25
  camera_info  -> ABSENT
  CameraInfo   -> ABSENT
  /tf          -> ABSENT
  tf_static    -> ABSENT
image/imu: /camera/camera/color/image_raw, .../depth/image_rect_raw,
           .../infra1/image_rect_raw, .../infra2/image_rect_raw,
           /utlidar/imu, /unilidar/imu
```

Four optical streams recorded, **not one `camera_info`**, and **no transform
topics at all**. A bag with `color/image_raw` and no intrinsics or distortion
model cannot feed any camera-involving SLAM or fusion; without TF there are no
extrinsics between the sensors either. My channel matrix enumerated *sensor*
channels and never modelled *calibration and transform support artifacts* as a
class. Three tranches and a 63-agent audit did not catch it, because every one
of them was auditing the thing I had specified. **Sol found the gap in the
specification, which is the harder thing to find.** MR-A survives as today's
one software P0.

**The stale-budget catch is real too.** `BANDWIDTH_BUDGET.md` is now generated
and correct (91.870 MiB/s, with 84.60 quoted as superseded), but operator-facing
arithmetic derived from the old model survives — e.g. `PSK_STATUS.md:123` builds
a whole disk ledger on `84.60 × 60 / 1024`, concluding "≈425 GiB free required"
and "256 GiB buys ≈45 min". Those are ~8.6% low, so the free-space requirement
is **understated** and takes would truncate. Sol's rule — the run-specific pack
is generated, never hand-transcribed — is correct and kept.

**Also right and kept:** rule 5 (unknown fails closed), rule 6 (one source of
profile truth; tape-measured geometry is evidence with uncertainty, never
relabelled as calibrated TF — an important distinction I had left fuzzy), rule 7
(one source of recorder argv truth, which follows directly from PS-M's Humble
finding), the hard-stop rules, the three-way readiness verdict, and holding a
full capture session back from the end of an engineering day.

## 2. Where the board is wrong: the dependency arrow is backwards

Sol's order is `MR-A (software) ──> MR-B (hardware)`, with MR-B scheduled at
**hours 4–7** and conditional on *"If Orin is accessible."* Measured this
morning:

```
eno1np0    DOWN          <- robot LAN NIC
eno2np1    DOWN          <- robot LAN NIC
192.168.123.{161,18,222}, 192.168.1.2  -> no response
ros2 ABSENT · docker ABSENT · colcon ABSENT
```

And from yesterday's pack: `TONIGHT_CHECKLIST.md` — **0 steps executed**.
`STAGE0_RUN_SHEET.md` — **0 of 15 boxes ticked**. No `.mcap`, no attestation, no
clock map anywhere in the tree.

**Nobody has ever run a single command on the Orin.** Which means:

> We do not know whether the Orin runs JetPack 6.2 / Ubuntu 22.04 / **Humble**
> or 5.1.1 / **Foxy**. MR-A's rosbag2 topic plan, PS-M's distro-aware argv, and
> the whole recorder design are aimed at a target **nobody has verified exists.**

So MR-A is **epistemically downstream of the Orin check, not upstream of it**.
`cat /etc/nv_tegra_release` costs five minutes, depends on nothing, and can
invalidate hours of software work — it is the highest information-per-second
action available and it is scheduled fourth, behind a gate it should precede.

**Second sequencing problem: three of eight cards do not serve the goal.**
PE-D (`SensorFrameV2` replay contract), SG-E (gateway/authority slice) and IS-F
(Isaac RTX lane) are legitimate engineering aimed at *governed autonomous
motion* — a milestone the board itself says today is not about. IS-F in
particular I already ruled a distraction this week: Isaac Sim 6.0 supports
Ubuntu 22.04/24.04 and this host is 26.04. Every hour on those three is an hour
not spent getting sensors onto the dog.

## 3. What is missing: nothing on the board mounts the rig

The owner asked for mounting. On Sol's board mounting exists only inside **MR-C**,
which is bundled with a full stationary Stage-0 capture session and marked
*"deliberately not run today."*

That bundling is the error. **Mounting is separable from capturing**, and the
two have completely different risk profiles:

| | Mount + measure | Stage-0 capture session |
|---|---|---|
| Needs the software stack working | no | yes |
| Needs two people + stop paths | for the stand only | yes, throughout |
| Needs firmware pin cleared | no (nothing joins the LAN) | yes |
| Yields something irrecoverable | **yes — the extrinsics** | yes |
| Blocked by anything today | **no** | yes, by MR-B |

Mount geometry is the one quantity that exists only while the rig is
assembled, and it is recoverable by tape and camera with no ROS, no drivers,
and no dog powered. Holding it hostage to a capture session that is correctly
deferred means the owner's stated goal slips for reasons that do not apply to
it. **Split it out and do it today.**

One honest caveat, and it is why the FOV check is staged: verifying that the
two LiDARs share a field of view *properly* wants both clouds live in RViz,
which does need the stack. Revised card **H-3** therefore takes the geometric
check (datasheet FOV cones against measured pose) as the pre-torque gate and
records it as **lower confidence**, with the RViz confirmation as a named
follow-up before the capture session. That is worse than the ideal and much
better than not mounting.

## 4. Answers to the review brief, so far as they can be answered

Most of the brief's thirteen questions ask whether cards that have not run yet
did their job; those are `NOT YET RUN` and will be answered at close. Three can
be answered now:

- **Q3 — can a missing/mismatched `CameraInfo`, TF or profile still produce
  `GO-RECORD`?** **Yes, today it can**, because none of them is recorded or
  checked at all. This is the gap S-1 closes.
- **Q5 — is the operator ledger generated from the current model?** **No.** The
  budget doc is generated; the derived operator arithmetic in the status pack is
  not, and still carries 84.60-era figures.
- **Q7 — did any capture change acquire a publisher, motion import or command
  surface?** **No.** Re-verified yesterday at close: the recursive no-arm pin
  reddens on a seeded `create_publisher("/cmd_vel")` + `SportClient().Move()`,
  and `hard-safety` plus `frozen-digest-sentinels` were green with nothing
  frozen moved.

## 5. What changed in the revised board

| Sol's card | Disposition |
|---|---|
| MR-A | **Kept, narrowed → S-1.** Calibration/TF/sidecar gate only — the verified P0. Truth-table and preflight-reconciliation parts that assume an unverified ROS distro move behind H-1. |
| MR-B | **Promoted to H-1/H-2 and unblocked.** No longer depends on MR-A. H-1 is the five-minute identity dump, first action of the day. |
| MR-C | **Split.** The mount half becomes **H-3, today**. The capture-session half stays deferred, unchanged, with its hard-stop rules intact. |
| PE-D, SG-E, IS-F | **Deferred to backlog** with concrete unblock steps. Good work; not this day. |
| DOC-G | Kept, folded into close. |
| AU-H | Kept — this document plus the close audit. |
| Working agreements 1–11 | **Kept verbatim.** |
| Hard-stop rules | **Kept verbatim.** |

Net: 8 cards → 6, hardware-first, and the thing the owner asked for is now on
the board instead of inside a deferred one.

## 6. What I am not claiming

This review is desk work on a machine with no robot attached. It does not prove
the Orin exists in a usable state, that any driver installs, or that any topic
carries what we believe. It re-ranks work against a stated goal; it does not
substitute for the five-minute command that nobody has yet run.
