# Mount geometry measurement sheet — fill **while the rig is assembled**

> ## ⛔ THIS IS THE ONE THING THAT CANNOT BE RECOVERED LATER
>
> Every other defect on this board is fixable next week against the bags. The
> **mount extrinsic stops existing the moment the bracket is unbolted.** A bag
> full of LiDAR and pixels whose sensors' positions are unknown is a bag of
> numbers in unrelated coordinate systems: no fusion, no depth-to-LiDAR
> comparison, no two-LiDAR cross-validation, no reprojection, no SLAM
> evaluation against the vendor odometry. Every one of those becomes a **second
> physical session**.
>
> **Fill this sheet before the dog is powered, and again at teardown (§9).**
> If the session takes the DEGRADE-MMP branch and records nothing at all, this
> sheet plus the photographs are still a **successful day**.

**Card:** PS-F, tranche PS-1 · **Written:** 2026-08-13 · **Blank by design —
nothing below has been measured.**
**Belongs to:** [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §7 C0.2 and §11.
**Photographs that back it up:** [PHOTO_LIST.md](PHOTO_LIST.md) P06–P10, P16.
**Amended 2026-08-13 by card PS-K** (tranche PS-2): **§4A is new** — a
**pre-torque** gate that must be passed *before the bracket is finally
torqued*, because no post-hoc tool can recover an extrinsic between two LiDARs
that never shared a view. Sections 1–11 keep their numbers and their text.
The take that consumes this sheet is [TAKE_SCRIPT.md](TAKE_SCRIPT.md) T2a/T2b.

```text
run_id:      P5-DRY-________T______Z          # must match the run sheet §1
measured_by: ____________   checked_by: ____________   (two people, one reads, one writes)
date/time:   ____/____/____  ______ UTC
```

---

## 1 · The rule that makes this sheet auditable

**Raw tape readings are the artifact. Derived offsets are a convenience.**

Record what you actually read off the tape, against a physical landmark you
can point at in a photograph. Then derive the base-frame offset from it in a
separate column. If the datum convention in §2 is later judged wrong, the raw
readings survive the correction and the day is not lost. A sheet with only
derived numbers is unrecoverable if the convention was misunderstood.

**Every number carries a unit and an uncertainty. A bare number is a defect.**
`342` is not a measurement; `342 ± 3 mm` is.

**If a quantity cannot be measured, write `NOT MEASURED — <reason>`.** Do not
write the value you expect. Unknown = absent.

---

## 2 · Frame convention and how to realise the datum with a tape

**Convention:** ROS REP-103 right-handed body frame, `base_link`:
**+X forward** (nose), **+Y left**, **+Z up**. Angles in **degrees** on this
sheet; radians only in the derived column, because the code that consumes them
(`camera_channel/d455.py`) is in radians. Linear in **millimetres**; metres
only in the derived column.

**Parcel has no TF implementation** — `pose.py:74-78` is a two-member `Frame`
enum with no transform function anywhere. So there is no code-side definition
of where `base_link` physically sits on a Go2. This sheet therefore **defines
the datum operationally** and requires you to photograph it, so a later reader
can re-derive everything.

**Datum realisation — three planes, in this order.** Dog **powered off**,
**seated or on blocks**, on a flat surface.

| Plane | Definition | How to realise it |
|---|---|---|
| **Y0** — longitudinal symmetry plane | vertical plane splitting the trunk left/right | measure trunk width at the front and rear faces, mark the mid-point of each with tape, snap a line between them along the trunk's top |
| **X0** — transverse datum | vertical plane through the **mid-point between the front and rear hip-roll (shoulder) axis centres** | mark the hip axis centre on the trunk's left side (the visible rotation centre of the front and rear shoulder joints), measure the distance between them, mark the midpoint |
| **Z0** — horizontal datum | horizontal plane containing the **hip-roll axis centres** | with the dog level, this is the line joining the two marks from X0 |

`base_link` origin = **X0 ∩ Y0 ∩ Z0**. Mark it with a tape cross on the trunk
top directly above it and **photograph it** (PHOTO_LIST P16a) — that photo is
what makes every number below re-derivable.

```text
trunk_width_front:  ______ ± ____ mm      trunk_width_rear: ______ ± ____ mm
hip_axis_separation (front↔rear, along X):  ______ ± ____ mm
datum cross marked and photographed:  YES / NO
if NO:  origin: NOT ESTABLISHED — record every offset below relative to a named
        physical landmark instead, and name it here: ______________________
```

> **Fail-closed clause.** If the datum cannot be established, this sheet is
> **not** void — it degrades. Record every offset from a single named,
> photographed landmark (e.g. "front-top-centre corner of the trunk shell")
> and say so. A landmark-relative measurement is recoverable later from
> photographs and the vendor's CAD; a guessed `base_link` offset is not.

---

## 3 · Instruments — name them and their resolution

| Instrument | Make/model | Resolution | Used for |
|---|---|---|---|
| Tape / steel rule | ____________ | ± ____ mm | linear offsets |
| Digital calliper (optional) | ____________ | ± ____ mm | small offsets, sensor landmarks |
| Inclinometer / phone level app | ____________ | ± ____ ° | pitch, roll |
| Square + protractor | ____________ | ± ____ ° | yaw |
| Scale | ____________ | ± ____ g | payload masses (§7) |

**Level check before any angle is read:** put the inclinometer on the trunk's
top face with the dog seated on the flat surface and record the reading. Every
subsequent angle is relative to **that**, and you must write the trunk
reference down or the angles mean nothing.

```text
trunk_top_face_pitch_reference:  ______ ± ____ °    roll_reference: ______ ± ____ °
surface confirmed flat (spirit level):  YES / NO
```

---

## 4 · Diagram — mark your actual dimensions on this

Dimension keys (`A1`, `B2`, …) are the row IDs in §5. **Draw on a printed copy
if that is easier, then photograph it (PHOTO_LIST P16b).**

### Side view — viewed from the dog's LEFT · +X forward → right · +Z up

```text
                             +Z
                              ^
                              |
             ┌────┐  add-on L2 LiDAR
             │ L2 │  origin landmark = centre of scan aperture
             └──┬─┘         ¦
                │  C3 (up)  ¦
        ╭───╮   │           ¦
        │BLd│ built-in LiDAR (dome / aperture centre)
        ╰─┬─╯   │  B3 (up)  ¦
   ┌──────┴─────┴───────────┴───────────────┐              ┌──────┐
   │                                        │              │ D455 │
   │  TRUNK              ⊗ base_link        │              │  ▣   │ ← colour
   │                     (X0∩Y0∩Z0)         │──────────────┤      │   imager
   └───┬────────────────────────────────┬───┘   A1 (fwd)   └──────┘
       │                                │        ────────────────>
    ╔══╧══╗ rear hip                 ╔══╧══╗ front hip          │
    ║  ⊙  ║ roll axis                ║  ⊙  ║ roll axis          │ A3
    ╚══╤══╝                          ╚══╤══╝                   (up)
       │                                │                       │
       ╵                                ╵    ─── Z0 datum ──────┴───
      foot                             foot
                                                    ──────> +X (forward)

   A1 = D455 forward offset      A3 = D455 height above Z0
   B1 = built-in LiDAR forward   B3 = built-in LiDAR height
   C1 = add-on L2 forward        C3 = add-on L2 height
   (all measured from the X0 / Z0 datum planes, NOT from the trunk shell)
```

### Top view — viewed from ABOVE · +X forward → up the page · +Y left → left

```text
                          +X (forward)
                              ^
                              |
                      ┌───────┴───────┐
                      │     D455      │   A2 = lateral offset, +ve to the LEFT
                      │       ▣       │   ψ  = yaw about +Z, +ve = nose turns LEFT
                      └───────────────┘
              ¦                               ¦
   +Y  <──────┼───────────────────────────────┼──────  −Y
   (left)     ¦        ┌─────────────┐        ¦  (right)
              ¦        │   ╭───╮     │        ¦
              ¦        │   │BLd│  B2 │        ¦
              ¦        │   ╰───╯     │        ¦
              ¦        │      ⊗ base_link     ¦        ⊗ = X0 ∩ Y0 ∩ Z0
              ¦        │   ┌────┐    │        ¦
              ¦        │   │ L2 │ C2 │        ¦
              ¦        │   └────┘    │        ¦
              ¦        └─────────────┘        ¦
                              |
                          Y0 plane (dashed) — the trunk's symmetry plane

   A2/B2/C2 = lateral offsets from Y0.  LEFT is POSITIVE. Write the sign.
```

**Sign discipline — the single most common way this sheet goes wrong.**
Forward `+X`, left `+Y`, up `+Z`. Pitch is about `+Y`; **nose-up is positive**
(this matches `MOUNT_PITCH_UP_RAD` in `camera_channel/d455.py:38`). Roll is
about `+X`, right-side-down positive. Yaw is about `+Z`, nose-left positive.
Write the sign explicitly on every entry, including `+`.

---

## 4A · ⛔ PRE-TORQUE GATE — the two LiDARs must share a view

> ### Do this while the bracket can still move. Ten minutes now, or never.
>
> **A LiDAR-to-LiDAR extrinsic cannot be recovered between two units that never
> see the same thing.** Every candidate tool — **Multi-LiCa**, **`ros2_calib`**,
> **`mlcc`** — solves for a transform by matching *shared* structure. Given two
> clouds with no overlap they do not return a poor answer; they have **no
> problem to solve**. `[EXT]`, via [`../RISK_ASSESSMENT.md`](../RISK_ASSESSMENT.md)
> and [`../CHANNEL_MATRIX.md`](../CHANNEL_MATRIX.md) §C, which states the same
> requirement: *"no post-hoc LiDAR-to-LiDAR calibration tool can recover an
> extrinsic between two units that never share a view, and the bracket is
> unrecoverable once unbolted."*
>
> This is not hypothetical for our rig. The **built-in unit sits low and
> forward** on the dog; the **add-on L2 sits on a bracket on the trunk's top**.
> A chin-mounted sensor and a back-mounted sensor **may barely overlap at all**,
> and the trunk itself is between them. The two-LiDAR pair is the session's
> advertised **cross-validation asset**; if they do not share a view, that asset
> does not exist and nobody finds out until the bags are opened next week.

**WHEN.** Brackets **snug but not finally torqued** — enough that nothing can
fall, loose enough that aim can still be changed. Before §5's measurements
(measure *after* torque, or you measure a geometry that then moves).

> **Safety, because this step needs the dog powered with a bracket that is not
> yet final.** Dog **seated** on the mat, second holding stop #2, hands out of
> the leg envelope, payload hand-checked for security before power
> ([SAFETY_BRIEF.md](SAFETY_BRIEF.md) §3 H1/H4). Keep the powered window short.
> If the payload cannot be made safe at snug torque, **do not power the dog** —
> use the degraded path below and accept its consequence.

### A · The check (primary path — live clouds, both LiDARs, one screen)

1. Stand the rig facing a **large flat wall** (a door, a whiteboard, a blank
   wall) at **≈2–3 m**, square on.
2. Bring up **both** clouds live in **RViz2** on one screen: the built-in unit
   (`utlidar/cloud`) and the add-on L2, each in its own colour, with the fixed
   frame set to whichever frame you can actually resolve — **the frames are not
   yet related, and that is fine.** You are looking for *the same wall appearing
   in both*, not for them to align.
3. Confirm a **substantial shared region**: the **same physical wall patch,
   roughly ≥1 m × 1 m, visible simultaneously in both clouds**, with points from
   both units on it. Wave a board slowly across it — the patch that *moves in
   both clouds at once* is the shared region, and this is the fastest way to see
   it.
4. **Then rotate the rig ~30–45°** and confirm the shared region survives. A
   shared region that exists at exactly one heading is a shared region you will
   not be able to fill with the three non-parallel planes a plane-based
   calibration needs ([TAKE_SCRIPT.md](TAKE_SCRIPT.md) T8).
5. **Self-occlusion check — new, and equally unfixable.** With the payload on,
   look for a **new shadow** in the built-in unit's cloud caused by *our own*
   bracket, Orin, or L2. Compare against T1, the bag recorded **before** anything
   was mounted ([TAKE_SCRIPT.md](TAKE_SCRIPT.md) T1) — that is the only
   unoccluded reference this rig will ever have. A payload that blinds the
   built-in LiDAR over an arc is a permanent property of every bag afterwards.

### B · Degraded path — only if RViz2 or a live L2 is not available

Record it as **DEGRADED**, not as a pass:

1. Read each unit's field of view **off its own datasheet** (do not guess a
   number; write down where it came from).
2. Sight from each aperture to the intended wall patch and confirm **clear line
   of sight from both**, with nothing of the rig in the way.
3. Sketch the two FOV cones on the §4 diagram and mark the overlap.

A geometric argument is recoverable later from photographs; a **live** check is
evidence. The degraded path proves line of sight, **not** that both units return
points from the same surface.

### C · Record

```text
path used:            PRIMARY (live clouds) / DEGRADED (datasheet + sighting)
wall used:            ______________________  distance ______ m
shared region seen in BOTH clouds:   YES / MARGINAL / NO
  approx. extent of the shared patch:  ______ m × ______ m
  survives a 30–45° rotation?          YES / NO
board-wave visible in both clouds?     YES / NO
RViz2 screen photographed (add to PHOTO_LIST as P25): YES / NO
self-occlusion of the built-in LiDAR by OUR payload:
  NONE / present over approx. ______ ° of azimuth, direction ______________
  compared against the pre-mount reference bag (T1)?  YES / NO
verdict:              CONFIRMED / MARGINAL / NONE
checked by ____________ + ____________ at ______ UTC
FINAL TORQUE APPLIED AT ______ UTC   torque value/method: ____________________
```

### D · Branch — and the point of the gate is that the branch is still open

| Verdict | Action, **before** final torque |
|---|---|
| **CONFIRMED** | Torque. Proceed to §5. |
| **MARGINAL** | **Loosen and re-aim now.** Raising, tilting or yawing the L2 bracket by a few degrees is free at this moment and impossible five minutes later. Re-run the check. |
| **NONE** | Try every bracket position available. If none gives overlap: torque, and write **verbatim** into the run header's `does_not_prove` — *"the two LiDARs never shared a view; the L2↔built-in extrinsic is tape-only and no LiDAR-to-LiDAR calibration is possible from this session's bags"* — and tell the owner **on the day**, not next week. |
| **Self-occlusion present** | Re-route or re-position the offending item if it can be moved; if not, record the occluded arc as a permanent property of every bag in this session. |

---

## 5 · Raw readings and derived offsets

One block per sensor. **Fill the raw columns first.** The derived column is
arithmetic done afterwards, and the raw reading wins any disagreement.

### A · RealSense D455 — the primary raw-pixel source

Landmark: **centre of the colour imager's front glass** (marked `▣`). Also
record the mounting screw centre as a second landmark — the D455's
imager-to-optical-frame offsets come from `rs-enumerate-devices`/the datasheet
later, so only the mount needs tape.

```text
D455 serial (off the label): ____________   firmware: ____________
landmark used:  colour imager glass centre  /  other: ______________________
```

| Key | Quantity | Raw reading + datum used | Uncertainty | Derived (base_link) |
|---|---|---|---|---|
| A1 | forward `+X` | ______ mm from ______________ | ± ____ mm | ______ mm = ______ m |
| A2 | lateral `+Y` (left +) | ______ mm from Y0 | ± ____ mm | ______ mm = ______ m |
| A3 | height `+Z` | ______ mm above Z0 | ± ____ mm | ______ mm = ______ m |
| A4 | pitch (nose-up +) | ______ ° rel. trunk ref | ± ____ ° | ______ ° = ______ rad |
| A5 | roll | ______ ° | ± ____ ° | ______ ° = ______ rad |
| A6 | yaw (left +) | ______ ° | ± ____ ° | ______ ° = ______ rad |

### B · Built-in LiDAR — **read the model off the unit**

> The repo contradicts itself: `P5_PROCUREMENT_BOM.md:75` says **L1**; the
> vendor's page says **L2**. Neither is evidence. **Read the label, write it
> here, and photograph it** (PHOTO_LIST P02). This one line resolves a
> documented open question with no software involved, and PS-D's attestation
> is checked against it.

```text
model READ OFF THE UNIT: ____________    serial: ____________
label photographed (P02):  YES / NO
landmark used: centre of scan aperture / other: ______________________
```

| Key | Quantity | Raw reading + datum used | Uncertainty | Derived (base_link) |
|---|---|---|---|---|
| B1 | forward `+X` | ______ mm from ______________ | ± ____ mm | ______ mm = ______ m |
| B2 | lateral `+Y` | ______ mm from Y0 | ± ____ mm | ______ mm = ______ m |
| B3 | height `+Z` | ______ mm above Z0 | ± ____ mm | ______ mm = ______ m |
| B4 | pitch | ______ ° | ± ____ ° | ______ ° = ______ rad |
| B5 | roll | ______ ° | ± ____ ° | ______ ° = ______ rad |
| B6 | yaw | ______ ° | ± ____ ° | ______ ° = ______ rad |

### C · Add-on Unitree L2 LiDAR

```text
serial: ____________   firmware: ____________   transport used: UDP / /dev/ttyACM0
bracket description (one line): ______________________________________________
landmark used: centre of scan aperture / base flange centre / other: __________
```

| Key | Quantity | Raw reading + datum used | Uncertainty | Derived (base_link) |
|---|---|---|---|---|
| C1 | forward `+X` | ______ mm from ______________ | ± ____ mm | ______ mm = ______ m |
| C2 | lateral `+Y` | ______ mm from Y0 | ± ____ mm | ______ mm = ______ m |
| C3 | height `+Z` | ______ mm above Z0 | ± ____ mm | ______ mm = ______ m |
| C4 | pitch | ______ ° | ± ____ ° | ______ ° = ______ rad |
| C5 | roll | ______ ° | ± ____ ° | ______ ° = ______ rad |
| C6 | yaw | ______ ° | ± ____ ° | ______ ° = ______ rad |

### D · The two-LiDAR baseline — measure it directly as well

Do **not** only derive L2↔built-in from B and C: a direct measurement is an
independent check on the datum, and the two LiDARs at a known relative
extrinsic is the session's **cross-validation asset** for every SLAM
candidate.

| Key | Quantity | Raw reading | Uncertainty | Derived from B,C | Agree? |
|---|---|---|---|---|---|
| D1 | aperture-to-aperture distance | ______ mm | ± ____ mm | ______ mm | Y / N |
| D2 | relative yaw (L2 vs built-in) | ______ ° | ± ____ ° | ______ ° | Y / N |

**A `N` in "Agree?" beyond the combined uncertainty means the datum is wrong
somewhere. Re-measure now — you cannot re-measure tomorrow.**

### E · Not tape-measurable — record the source, do not invent a number

| Item | Value | Source | Rule |
|---|---|---|---|
| D455 depth→colour extrinsic | ______ | `rs-enumerate-devices` / datasheet | intra-device, read from the device later; **do not tape-measure** |
| D455 IMU→depth extrinsic | ______ | datasheet | as above |
| L2 IMU→L2 optical | ______ | `unilidar_sdk2` docs | as above |
| Built-in LiDAR IMU→cloud | ______ | vendor | as above |
| Go2 body IMU location | ______ | vendor / `lowstate` docs | **`NOT MEASURED` is the correct entry if unknown** |

---

## 6 · Comparison against the values the simulator has been assuming

Parcel's simulated low-viewpoint camera already hard-codes a mount extrinsic
(`src/parcel_robot/camera_channel/d455.py:34-40`). **Nobody has ever checked
it against a real bracket.** This is that check.

| Quantity | Sim-assumed (code) | Measured (from §5A) | Δ | Within tol? |
|---|---|---|---|---|
| height | **0.35 m** (`MOUNT_HEIGHT_M`, `:34`) | ______ m | ______ m | ±0.05 m → Y / N |
| forward | **0.18 m** (`MOUNT_FORWARD_OFFSET_M`, `:35`) | ______ m | ______ m | — |
| lateral | **0.0 m** (`MOUNT_LATERAL_OFFSET_M`, `:36`) | ______ m | ______ m | — |
| pitch up | **12.0°** (`MOUNT_PITCH_UP_RAD`, `:38`) | ______ ° | ______ ° | — |
| roll | **0.0°** (`:39`) | ______ ° | ______ ° | — |
| yaw | **0.0°** (`:40`) | ______ ° | ______ ° | — |

> **The named consequence.** `CameraMountGeometry.is_dog_height()`
> (`d455.py:132-133`) returns `False` once the measured height differs from
> 0.35 m by more than **0.05 m**. If that happens, **every low-viewpoint claim
> derived from sim frames is measured at a mount height the hardware does not
> have**, and the P5-G-PIXEL bench subset must be re-argued rather than
> inherited. Write the verdict here, in words:
>
> ```text
> is_dog_height would return:  TRUE / FALSE
> if FALSE, the affected claims are: ______________________________________
> ```
>
> **Do not "fix" the constant at the session.** Source edits are out of scope
> for this tranche. Record the delta; the change is a later, reviewed card.

---

## 7 · Payload inventory — mass, placement, and how it is held on

Feeds the pre-stand gate (`STAGE0_RUN_SHEET.md` §8 S1/S2) and the unanswered
power/thermal/session-length question.

| Item | Mass (g) | Mounted where | Held by (fasteners, not tape) | Overhangs a leg sweep? |
|---|---|---|---|---|
| Orin NX + carrier | ______ | ____________ | ____________ | Y / N |
| Orin power supply / battery | ______ | ____________ | ____________ | Y / N |
| D455 + bracket | ______ | ____________ | ____________ | Y / N |
| Add-on L2 + bracket | ______ | ____________ | ____________ | Y / N |
| Cables + ties | ______ | — | — | — |
| Other: ____________ | ______ | ____________ | ____________ | Y / N |
| **TOTAL ADDED MASS** | **______ g** | approx. CG at X ______ mm, Y ______ mm from base_link | | |

```text
any item that moves under a firm two-finger pull:  NONE / ______________ (⇒ S1 FAILS)
```

---

## 8 · Frame-id assignment — decide it here, once

`bags/schema.py:115-127` `default_frames()` provides exactly **one**
`lidar_frame` key (`"lidar_link"`). **We have two LiDARs.** The second needs a
distinct id or the two clouds are indistinguishable in the bag. `schema.py` is
**not editable** by this tranche, so the second id rides in the sidecar's
`extra` mount-geometry block, which PS-B owns.

Proposed ids — confirm or amend at the session, then tell PS-B:

| Sensor | `frame_id` | Notes |
|---|---|---|
| body | `base_link` | `default_frames()` `base_frame` |
| D455 colour | `camera_color_optical_frame` | matches `default_frames()` `camera_frame` and `d455.py:28` |
| built-in LiDAR | `lidar_link` | takes the single `default_frames()` `lidar_frame` slot |
| **add-on L2** | `lidar_l2_link` | **not** in `default_frames()`; carried in sidecar `extra` |
| L2 IMU | `lidar_l2_imu_link` | as above |
| D455 IMU | `camera_imu_optical_frame` | as above |

```text
ids confirmed at session:  YES / amended to: ______________________________
communicated to PS-B (sidecar extra):  YES / NO
```

---

## 9 · M2 — teardown re-measure. Do this BEFORE loosening anything.

A bracket that shifted mid-session silently invalidates every extrinsic in the
bag. The only way to know is to measure the same quantities again at the end,
**while the rig is still assembled**.

| Key | §5 value (M1) | Teardown value (M2) | Δ | Tolerance | Verdict |
|---|---|---|---|---|---|
| A1 D455 forward | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |
| A3 D455 height | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |
| A4 D455 pitch | ______ | ______ | ______ | ±1.0° | OK / SHIFTED |
| B3 built-in LiDAR height | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |
| C1 L2 forward | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |
| C3 L2 height | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |
| D1 LiDAR baseline | ______ | ______ | ______ | ±5 mm | OK / SHIFTED |

> The ±5 mm / ±1.0° tolerances are **this sheet's proposal**, chosen to sit
> just above a careful tape's uncertainty. They are not derived from any
> accuracy requirement, because no such requirement exists in the repo yet.
> **Label them as provisional** wherever they are quoted.

```text
any SHIFTED row ⇒ the session's extrinsic is UNRELIABLE. Write it in the run
sheet's does_not_prove, verbatim:
  "mount geometry shifted during the session (key ______, Δ ______); all
   extrinsic-dependent claims from this bag are void"
verdict:  ALL OK / SHIFTED: ______________________________________
```

---

## 10 · Sign-off

```text
§4A pre-torque FOV gate:  CONFIRMED / MARGINAL / NONE / DEGRADED / NOT DONE
   (NOT DONE ⇒ say so in the run header's does_not_prove — it cannot be done later)
M1 (assembly) complete:  ______ UTC   measured ____________  checked ____________
M2 (teardown)  complete: ______ UTC   measured ____________  checked ____________
all photographs P06–P10, P16 taken:  YES / NO
values transcribed to the PS-B sidecar `extra.mount_geometry`:  YES / NO / N/A (no recording)
```

---

## 11 · What this sheet does not prove

- **Nothing here has been measured.** Every field is blank until an operator
  fills it at the session.
- A tape measurement is **not a calibration**. These numbers are good to
  millimetres and degrees; they do not replace target-based extrinsic
  calibration, and no claim requiring sub-degree accuracy may cite them.
- The datum in §2 is an **operational convention defined by this sheet**, not
  a vendor-published `base_link`. If Unitree's body frame origin differs, the
  raw readings and the datum photograph are what make the correction possible
  — the derived column would be wrong.
- It says nothing about **intrinsics**, about time alignment between sensors
  (that is PS-C's clock map), or about whether any sensor was actually
  producing good data.
- An `OK` verdict in §9 proves the bracket did not shift **between the two
  measurements**. It does not prove it never shifted in between.
- Masses in §7 are static bench masses; they say nothing about dynamic load,
  CG under motion, or the power/thermal envelope. Those remain unmeasured.
- **§4A is an eyeball judgement, not an overlap measurement.** "A shared patch
  roughly 1 m × 1 m" is an operator looking at a screen. It does not quantify the
  overlapping solid angle, the point density either unit puts on the shared
  surface, or whether that overlap is enough for any particular calibration tool
  to converge. It is designed to catch the **catastrophic** case — no shared view
  at all — while the bracket can still move, and nothing more. A `CONFIRMED`
  verdict does **not** promise that Multi-LiCa, `ros2_calib` or `mlcc` will
  succeed on this rig.
- **The self-occlusion check depends on having T1**, the pre-mount reference bag.
  Without it, "is that shadow new?" is unanswerable, and the honest entry is
  `NOT COMPARED`.
