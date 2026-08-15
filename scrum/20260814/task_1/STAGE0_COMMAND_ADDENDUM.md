# Stage-0 command addendum — INDEX (2026-08-14, card S-2)

> ## ⚠ GENERATED INDEX — no commands live here
>
> This file is rendered by `scripts/parcel_capture/stage0_addendum.py::render_combined_index()` and carries **no command rows at all**. Every operator command — the RealSense launch, the L2 launch, the Unitree overlay/DDS environment and the recorder argv — lives in exactly one of the two per-distro sheets below, rendered by the single command renderer `render_addendum()`.
>
> It used to carry a second copy of those commands. The copies disagreed: different record target, different storage-config path, and a RealSense launch line missing the transform arguments S-1's GO-RECORD gate requires. One renderer now, and `tests/test_stage0_command_addendum.py` tokenises every committed sheet and fails if two of them spell one distro's argv or launch line differently.

## Which sheet is operative

**Neither, yet.** H-1 has not run: nobody has read the Orin's ROS distro, so
both sheets carry a DRAFT-UNTIL-H-1 banner and **FINALIZE is blocked**.
`READY_FOR_STATIONARY_STAGE0` is **not claimed** — that needs H-2 evidence
from the actual Orin, not a desktop or a sandbox.

Run H-1's identity dump (REVISED_BOARD.md H-1), then branch:

| H-1 reports | Operative sheet | VOID |
|---|---|---|
| `/opt/ros/humble` | [STAGE0_ADDENDUM_HUMBLE.md](STAGE0_ADDENDUM_HUMBLE.md) | `STAGE0_ADDENDUM_JAZZY.md` |
| `/opt/ros/jazzy` | [STAGE0_ADDENDUM_JAZZY.md](STAGE0_ADDENDUM_JAZZY.md) | `STAGE0_ADDENDUM_HUMBLE.md` |
| anything else — Foxy, JetPack 5.x, no ROS | **none** | **both** — take REVISED_BOARD.md H-1's 'anything else' branch: STOP, report the exact output, retarget |

Exactly one sheet becomes operative. The generator refuses to render an unknown distro rather than defaulting to a plausible one, so there is no path by which a Foxy Orin gets handed the Humble sheet.

## Regeneration

```
.parcel/bin/python -m scripts.parcel_capture.stage0_addendum --distro <H-1's answer> --emit-distro   # the operative sheet
.parcel/bin/python -m scripts.parcel_capture.stage0_addendum --emit-all-distros                      # both drafts
.parcel/bin/python -m scripts.parcel_capture.stage0_addendum --emit                                  # this index
```

## Provenance and scope

| Field | Value |
|---|---|
| **H-1 Orin identity** | **UNREAD** — `cat /etc/nv_tegra_release`; `lsb_release -a`; `ls /opt/ros` not yet executed |
| **Observed ROS distro** | unknown — fail closed |
| **FINALIZE** | **BLOCKED ON H-1** |
| **READY_FOR_STATIONARY_STAGE0** | **not claimed** — requires H-2 evidence |
| Plan of record (D455) | `848x480@30 CDI` |
| Record target (both sheets) | `/data/parcel/stage0/take01` |
| Storage config (outside the record target) | `/data/parcel/stage0/mcap_storage.yaml` |
| Rows covered | T7, T8, T9, T10 |
| Provenance (immutable) | `scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md`, `scrum/20260813/task_1/session/TONIGHT_CHECKLIST.md` N2e/N5b/N6/N4 |

Historical 20260813 sheets stay as provenance (working agreement 3). The per-distro pair supersedes them for the four missing command rows only.

## What this index does not know

- Which distro the Orin actually has (H-1 unread) — **FINALIZE blocked**.
- Whether the driver package names, overlay paths and launch-argument spellings in the per-distro sheets match what is installed (H-2).
- Whether the real topic names equal the plan's documentation-derived names.
- Sustained write rate or free space on the record target (see `DISK_LEDGER.md`; measure on the Orin).
- Anything that would authorize motion, stand, gait, or a vendor lease.

