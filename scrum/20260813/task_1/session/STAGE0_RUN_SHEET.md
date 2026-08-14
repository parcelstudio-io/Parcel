# Stage 0 run-sheet — dry-run (motion disabled)

> ## ⬜ THIS SHEET IS BLANK BY DESIGN — NOTHING HERE HAS BEEN EXECUTED
>
> Every box, every measurement, every result field on this sheet is filled
> **by hand, at the session, by the operator**. A box that is still empty
> when the session ends is **not** a pass — it is an unmeasured quantity, and
> the honest record says so. Do not pre-fill. Do not fill from memory
> afterwards. **Unknown = absent.**

**Instantiates:** [`P5_COMMISSIONING_CHECKLIST.md:91-109`](../../../20260805/task_1/P5_COMMISSIONING_CHECKLIST.md)
— Stage 0, Dry-run (motion disabled). This sheet **does not replace** that
checklist and **does not add** a checkbox to it. It is that checklist's Stage 0
turned into something an operator can hold.
**Superseding authority for the sequencing:** [PHYSICAL_SESSION_PLAN.md](../PHYSICAL_SESSION_PLAN.md)
**Channel enumeration:** [CHANNEL_MATRIX.md](../CHANNEL_MATRIX.md) — **25 rows / 28 channels** (rewritten by PS-H; §7 C0.3's 19-row table is completed in §7A)
**Safety brief (read aloud before power):** [SAFETY_BRIEF.md](SAFETY_BRIEF.md)
**Mount geometry (fill while the rig is assembled):** [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)
**Photographs:** [PHOTO_LIST.md](PHOTO_LIST.md) · **Takes (what actually gets recorded):** [TAKE_SCRIPT.md](TAKE_SCRIPT.md) — T0–T16, added by PS-K; read **§7A below** before §3

**Card:** PS-F, tranche PS-1 · **Written:** 2026-08-13 · **Author:** Fable (PS-F)

---

## 0 · How to use this sheet

1. Work **top to bottom**. Sections are ordered by physical dependency, not by
   the checklist's printing order.
2. A section with a **STOP BAR** may not be passed until every row above it is
   filled with a real value. The stop bars are §5, §6, §9 and §11.
3. Write **units** on every number. A bare number is a defect.
4. If something cannot be measured, write `NOT MEASURED — <reason>`. Never
   leave a plausible-looking default. A default must never be the permissive
   value.
5. Anyone may call **"STOP"** at any time. See [SAFETY_BRIEF.md](SAFETY_BRIEF.md) §5.

---

## 1 · Run header — fill before anything is powered

Template copied verbatim from `P5_COMMISSIONING_CHECKLIST.md:167-181`. The
fields marked **†** are additions this sheet needs and the ratified template
does not carry; they are recorded *below* the ratified block so the template
itself is unchanged.

```text
run_id:           P5-DRY-________T______Z     # UTC date of THE SESSION, format YYYYMMDDTHHMMSSZ
stage:            dry-run
device_ids:       go2=____________ dock=____________ d455=____________
                  gnss=____________ xvf=____________
firmware:         go2=__________ (pin ≥1.1.13) jetpack=__________ image_hash=__________
git_sha:          ____________________________________
operator:         ____________________
second:           ____________________          # safety observer — REQUIRED, see §2
gates_targeted:   [ P5-G-BAG-DROPIN? , P5-G-INSTALL? ]   # circle only what §7 actually closes
hr_rows:          [ HR-8? , HR-9? ]
bag_digest:       ____________________________________   # from PS-B sidecar, §7 C0.3
does_not_prove:   ____________________________________   # NON-EMPTY. see §12 for the floor
```

† Additions required by this session and not present in the ratified template:

```text
l2_addon_serial:      ____________________
l2_addon_firmware:    ____________________
builtin_lidar_model:  ____________________   # READ OFF THE UNIT. L1 vs L2 is unresolved
                                             # in the repo (BOM:75 says L1, vendor says L2)
builtin_lidar_serial: ____________________
orin_serial:          ____________________
attestation_digest:   ____________________   # PS-D
clockmap_digest:      ____________________   # PS-C
mcap_sha256:          ____________________   # PS-B
mount_geometry_ref:   MOUNT_GEOMETRY_SHEET.md, filled ____/____/____ by __________
photo_set_ref:        ____________________   # album id · take_log_ref: TAKE_SCRIPT.md §2, filled by ______
branch_taken:         GO-RECORD | DEGRADE-MMP | ABORT-SAFETY     # circle one, §6
```

**`run_id` note (fidelity call, read once).** The board text
(`README.md:212`) wrote the example as `P5-DRY-20260813-…`. The **ratified**
template at `P5_COMMISSIONING_CHECKLIST.md:170` is
`P5-<STAGE>-YYYYMMDDTHHMMSSZ`. The ratified form wins. Worked example for a
session starting 09:15 UTC on 14 Aug 2026: `P5-DRY-20260814T091500Z`. Use the
**session's** UTC date, not the date on this sheet.

---

## 2 · Roles — fill before power. No named second, no powered dog.

| Role | Name | Holds | Sole duty |
|---|---|---|---|
| **Operator** | ____________ | Vendor handheld / stop #1 | Hardware, connections, vendor controls |
| **Safety observer (the "second")** | ____________ | Stop #2 | **Nothing else.** Watches the dog, calls the abort. Does not type, does not photograph, does not hold the tape. |
| **Scribe** | ____________ | This sheet | Fills boxes, timestamps, reads back |

Scribe and operator **may** be the same person. Operator and safety observer
**may not**.

> **STAFFING RULE (fail closed).** If fewer than two people are present, the
> dog is **not powered**. The session runs the DEGRADE-MMP branch (§6): mount,
> measure, photograph, record nothing. This is a legitimate outcome.

Confirmed by second, aloud: *"I hold stop #2 and I have no other job."*  [ ]

---

## 3 · T-30 — command transcription (rows T1–T6 here are **commands**, not takes — see §7A)

The capture stack is being written **today** by cards PS-A…PS-E in parallel
with this sheet. Their exact CLI surfaces are **theirs**, not this sheet's. Do
not guess a flag at the session.

Thirty minutes before the run, open each card's status doc, copy the exact
invocation into the box, and initial it. An untranscribed box is a
**NOT MEASURED** in §7.

| # (**command** row; takes are T0–T16 in TAKE_SCRIPT.md) | What | Source of truth | Exact command (transcribe) | Init |
|---|---|---|---|---|
| T1 | Preflight + attestation | `PSD_STATUS.md`, `scripts/parcel_capture/preflight.py` | `______________________________________` | ____ |
| T2 | Budget check for planned duration | `PSE_STATUS.md`, `scripts/parcel_capture/budget.py`, [BANDWIDTH_BUDGET.md](../BANDWIDTH_BUDGET.md) | `______________________________________` | ____ |
| T3 | Clock map (start burst → run → end burst) | `PSC_STATUS.md`, `scripts/parcel_capture/clockmap.py` | `______________________________________` | ____ |
| T4 | Record | `PSB_STATUS.md`, `scripts/parcel_capture/record.py` | `______________________________________` | ____ |
| T5 | Sidecar emit + verify | `PSB_STATUS.md`, `scripts/parcel_capture/sidecar.py` | `______________________________________` | ____ |
| T6 | Rehearsal replay (dry, on the Orin, before the dog) | `PSE_STATUS.md`, `scripts/parcel_capture/rehearse.py` | `______________________________________` | ____ |

**T6 is not optional.** The stack must have run once end-to-end on the Orin
against synthetic publishers **before** it is pointed at the dog. Result of
that run: `PASS / FAIL` ______  at ______ UTC.

---

## 4 · Precondition ruling (checklist `:63-73`, P0–P6)

The ratified checklist requires **all** preconditions true before Stage 0.
Three of them cannot be true today, and pretending otherwise would be the
first lie in the dataset. Rule each one explicitly; a ruling of
**WAIVED-FOR-SENSOR-ONLY** carries a named consequence that a later session
must pay.

| # | Precondition (abridged) | Ruling (circle) | Evidence / consequence |
|---|---|---|---|
| P0 | Owner authorized purchase; BOM received + inventoried | MET / NOT MET | Hardware is on hand (Go2 EDU, L2, D455, Orin NX). **The BOM receipt log is still empty** — fill `P5_PROCUREMENT_BOM.md` receipt table with serials at this session. Serials also go in §1. |
| P1 | Go2 firmware ≥1.1.13 recorded; auto-update disabled | MET / NOT MET | PS-D attestation reads it **off the unit**. Below pin ⇒ **hard refusal**, §6 branch DEGRADE-MMP, and **do not attach the Orin to the robot LAN** (ADR 0002: pre-pin firmware is RCE-capable on that LAN). Auto-update disabled: operator confirms in the vendor app, records screenshot ID ______ |
| P2 | Sacrificial Orin dock flashed to pinned JetPack 6.2.x; image hash recorded | **WAIVED-FOR-SENSOR-ONLY** | **No flash is performed today.** Record the JetPack version the Orin already carries (PS-D attestation) as an observation, not as a validated golden image. Consequence: **ADR 0001 stays unvalidated and P5-G-INSTALL cannot close from this session.** |
| P3 | Second (production) dock restored from golden image | **CANNOT BE MET** | BOM line 2 specifies **qty 2** Orin docks; **one** is on hand. The two-dock rule (`adr/0001-golden-image.md:19-21`) is not exercisable. Consequence: the only dock present is therefore **not** sacrificial — **do not flash it, do not `apt upgrade` it, do not mutate it** during this session. Installing anything on it during the session is an OWNS violation of this sheet. |
| P4 | Dual e-stop hardware present and labeled | MET / NOT MET | §5 is the verification. Serials + photo → [PHOTO_LIST.md](PHOTO_LIST.md) P14. **NOT MET ⇒ the dog is not powered.** |
| P5 | Machine-readable commissioning record schema ready; runtime refuses to arm without it | **PARTIAL** | Schema exists: `src/parcel_robot/commissioning/record.py` (card W0-B, landed 2026-08-12). The *runtime refusal* half is demonstrated read-only in §7 C0.6. |
| P6 | Day-one bag destination + `parcel.bag.v1` harness green in CI | MET / NOT MET | `tests/test_bags_roundtrip.py` + PS-B `tests/test_capture_sidecar.py`. Paste the CI/pytest line in §7 C0.3. |

Ruling signed by operator ____________ and second ____________ at ______ UTC.

---

## 5 · ⛔ STOP BAR — Stage-0 entry stop verification (`checklist:86-88, 154-161`)

> The checklist rule is unconditional: **"dual e-stop and comms-loss auto-damp
> must be re-verified at every stage entry."** Stage 0 is a stage entry. A
> sensor-only session does not exempt it. This table is verified **again** at
> §9 before the dog is allowed to stand.

**Read [SAFETY_BRIEF.md](SAFETY_BRIEF.md) aloud before this section. All hands
clear of the leg envelope.**

Name the two **independent** stops. They must not share a battery, a radio
link, or a failure mode.

```text
stop_1_device:  ____________________  label/serial: ____________  held by: __________
stop_2_device:  ____________________  label/serial: ____________  held by: __________
independence argument (one sentence, written not assumed):
  _________________________________________________________________________
```

| # | Check | Method (stage-appropriate: dog powered, **seated**, motion disabled) | Pass criterion | Result | Time UTC |
|---|---|---|---|---|---|
| E1 | Stop #1 (operator handheld) | Press while powered and idle | Robot latches stopped; requires explicit clear before anything responds | ______ | ______ |
| E2 | Stop #2 (independent) | Trigger secondary stop | Same as E1, **and** works with stop #1 unpowered/absent | ______ | ______ |
| E3 | Comms loss | Cut the operator link (power down handheld / pull the link) | Auto-damp then latched stop; **no resume without an operator action** | ______ | ______ |
| E4 | False-clear resistance | Attempt nothing. See note. | — | **N/A this stage** | — |

**E1/E2 latency (`checklist:104` "≤300 ms budget (measure)") — read this before
you write a number.**

This session can measure **one** of the two things that line asks for, and
must not claim the other:

- **Measurable today:** the *vendor* stop response, from the bag. The press is
  timestamped on channel 8 `wirelesscontroller`; the response appears in
  channel 6 `lowstate` (motor `tau_est`, `mode`) and channel 5
  `sportmodestate`. Both are recorded by PS-B with per-channel sequence and
  dual clocks, so the interval is recoverable **post hoc from the bag** —
  provided recording is running when you press. **Press the stops while the
  recorder is running**, and note the wall time here so the bag can be found.
- **NOT measurable today:** Parcel's *software* stop-path latency. Nothing in
  Parcel's stack is armed, holds a lease, or commands motion; there is no
  software stop path to time. Write `NOT MEASURED — no armed Parcel motion
  path exists this session` and leave the ≤300 ms budget **open**. It is a
  Stage-1/Stage-2 measurement.

```text
e_stop_handheld_ms:      NOT MEASURED — vendor interval recoverable from bag, see below
e_stop_dock_ms:          NOT MEASURED — as above
comms_loss_to_damp_ms:   NOT MEASURED — as above
hot_path_median_ms:      N/A — no Parcel hot path runs this session
proxy_delta_ms:          N/A
vendor_stop_press_wall_times_utc: E1 ______  E2 ______  E3 ______
recorder_running_during_stop_tests:  YES / NO      # NO ⇒ the interval is unrecoverable
```

**E4 note.** "Attempt arm without commissioning record → runtime hard-fail" is
verified by inspection and by the absent SDK in §7 C0.6. **Do not attempt an
arm at this session to produce this row.** An attempted arm is the one thing
this tranche forbids.

> **STOP BAR.** If E1, E2 or E3 is anything other than a clean pass, or if two
> genuinely independent stops cannot be named: **the dog is not powered
> further and the session takes ABORT-SAFETY (§6).** Geometry and photographs
> still happen — with the dog **off**.

---

## 6 · ⛔ STOP BAR — go / no-go, with the named branches

Decide **after** §5 passes and **after** T1/T2 in §3 have run. Circle one and
write the time. There are exactly three outcomes and **two of the three are
successful sessions**.

### Branch A — `GO-RECORD`

**Entry conditions, all required:**

| Condition | Source | Required value | Observed | OK? |
|---|---|---|---|---|
| Attestation emitted, exit 0 | PS-D `attest.py` | no channel claiming `PHYSICAL` without a received message | ______ | [ ] |
| Go2 firmware | PS-D, read off unit | **≥ 1.1.13** (ADR 0002) | ______ | [ ] |
| Critical channels `PRESENT` | PS-D vs [CHANNEL_MATRIX.md](../CHANNEL_MATRIX.md) | at minimum ch.1 built-in LiDAR, ch.5 sportmodestate, ch.6 lowstate, ch.12–15 D455 | ______ | [ ] |
| Free space ≥ budget for planned duration | PS-E `budget.py` | recorder must **refuse to start** below it | ______ | [ ] |
| Sustained write ≥ selected D455 profile | PS-E, **measured on the Orin** | ______ MiB/s vs required ______ MiB/s | ______ | [ ] |
| Rehearsal T6 green on the Orin | PS-E `rehearse.py` | PASS | ______ | [ ] |
| §5 stop verification | this sheet | all pass | ______ | [ ] |
| Payload + cable pre-stand gate (only if standing) | §8 | all pass | ______ | [ ] |

### Branch B — `DEGRADE-MMP` — *mount, measure, photograph, record nothing*

**Trigger:** attestation fails, **or** firmware is below pin, **or** the budget
check fails, **or** the rehearsal is not green, **or** fewer than two people
are present.

**This is a legitimate, successful outcome. It is not a failed session.** It
costs a later session **nothing**, because it captures the two quantities that
are unrecoverable once the rig is disassembled and the day is over:

- the **mount geometry** ([MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)) — gone the moment the bracket is unbolted;
- the **photographic record** ([PHOTO_LIST.md](PHOTO_LIST.md)) — including the built-in LiDAR's model label, which settles the L1-vs-L2 contradiction in the repo without any software at all.

**Branch-B required deliverables (all of them, no exceptions):**

- [ ] Mount geometry sheet fully filled, including the teardown re-measure (M2)
- [ ] Every photograph marked **MANDATORY** in PHOTO_LIST.md
- [ ] The failing attestation report **saved** (a failed attestation is evidence)
- [ ] The refusal message pasted verbatim into §10
- [ ] BOM receipt log filled with serials
- [ ] This sheet completed with `branch_taken: DEGRADE-MMP` and a non-empty `does_not_prove`

**Branch-B additional rule if the trigger was firmware-below-pin:** the Orin
and any laptop stay **off the robot LAN** entirely. ADR 0002 treats pre-pin
firmware as RCE-capable on that segment. Measure and photograph with the dog
powered only as long as needed to read labels, and do not connect a computer.

### Branch C — `ABORT-SAFETY`

**Trigger:** §5 fails · two independent stops cannot be named · payload cannot
be secured · a cable cannot be strain-relieved out of the leg envelope · fewer
than two people **and** the dog is already powered · any injury or near-miss.

**Action:** power the dog **off**. Then run the Branch-B deliverable list with
the dog off. Geometry measurement and photography do not require a powered
robot.

```text
branch:          GO-RECORD | DEGRADE-MMP | ABORT-SAFETY
decided at:      ______ UTC   by: ____________ (operator) + ____________ (second)
trigger (if B or C), verbatim: ______________________________________________
```

---

## 7 · Stage-0 checkbox instantiation — every box has a named producer

The seven rows below are the **verbatim** checkboxes of
`P5_COMMISSIONING_CHECKLIST.md:101-107`. Each has a **producer**: a PS-A…PS-E
artifact that emits its evidence, an explicit **operator action**, or an
explicit **deferral with a named consequence**. There is no eighth row and no
orphan.

### C0.1 — "Dock compose stack boots; safety+control container has **zero** network deps"

**Producer: DEFERRED — explicit.** Today's capture stack runs **natively on
the Orin**, not under `deploy/compose.yaml`; no golden image is flashed (§4
P2/P3). The compose stack is not exercised.

- **Consequence:** **P5-G-INSTALL does not close** from this session; HR-9
  stays `unvalidated`. Do not tick this box.
- **Substitute evidence recorded anyway (cheap, useful):** PS-D attestation
  records the Orin's JetPack version, free disk, NIC and DDS domain as
  *observations*.
- The "zero network deps" property for **today's** stack is a different and
  stronger claim, and it is proven in software, not on the dock: the capture
  package neither publishes nor imports motion (PS-A read-only import pin).

```text
result:  DEFERRED — compose stack not exercised; P5-G-INSTALL not closable
jetpack_observed:  ____________     free_disk_GiB: ______     nic: __________
```

### C0.2 — "Clock / TF / DDS segment firewalled (`192.168.123.0/24`); remote = tailnet only"

**Producer: OPERATOR ACTION + PS-D attestation (NIC, DDS domain, reachability).**

Three sub-claims, ruled separately because they are not equally true:

| Sub-claim | Producer | Fill |
|---|---|---|
| DDS segment firewalled to `192.168.123.0/24`; remote access tailnet-only (ADR 0002 §4) | **Operator action**, verified by PS-D's NIC + route observation | firewall rule applied? Y/N ____ · verified how: ____________ |
| **Clock** | **PS-C `clockmap.py`** — and read the note below | clockmap started ______ UTC, ended ______ UTC, digest ____________ |
| **TF** | **NOT APPLICABLE this session** — there is no TF implementation in Parcel (`pose.py:74-78` is a 2-member `Frame` enum with no transform function). Today's substitute is the **measured** extrinsic in [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md). | geometry sheet filled? Y/N ____ |

> **Clock note — the honest reading.** There is **no** time synchronisation
> anywhere in this repo. Measured today:
> `grep -rEc "chrony|ntp|ptp|phc2sys|time.?sync" src/ configs/ deploy/ scripts/`
> returns exactly **one** hit and it is a substring false positive
> (`brain/validator.py:83` `"jointpositions"` contains `ntp`). So this
> checkbox's "clock" clause is **not** satisfied by a synchronised clock —
> it is satisfied by **recording offset triples live** (PS-C `ClockMapV1`).
> If the clockmap is not running, cross-device timestamps in this session's
> bag are **permanently unrecoverable**. This is the single most expensive
> thing to get wrong today.

Also record the network placeholder actually used: `configs/robot.yaml:128`
still ships `interface: enp3s0  # replace with the dedicated robot Ethernet
NIC`. Whatever NIC the Orin really uses goes here — **as an observation, not
as a config edit** (config edits are out of scope for this tranche):

```text
observed_robot_nic:  ____________     dds_domain: ______    (config still says enp3s0 / 0)
```

### C0.3 — "Camera (D455) + LiDAR topics publish; bag recorder writes `parcel.bag.v1`"

**Producer: PS-D `preflight.py` (publish evidence) + PS-B `record.py` /
`sidecar.py` (the `parcel.bag.v1` manifest).**

The ratified box says *camera + LiDAR*. The owner's directive for this session
is **all the sensors possible**, so the box is instantiated against the full
[CHANNEL_MATRIX.md](../CHANNEL_MATRIX.md) — **28 channels; the 19 rows below are incomplete — §7A carries the rest** — and a channel that
cannot be probed is `ABSENT`, never assumed.

Fill from the PS-D attestation. **Do not fill by eye.**

| # | Channel | Expected rate | `PRESENT`/`ABSENT`/`DEGRADED` | Observed rate | Msg count |
|---|---|---|---|---|---|
| 1 | built-in LiDAR cloud `utlidar/cloud` | ~10 Hz | ______ | ______ | ______ |
| 2 | built-in LiDAR IMU `utlidar/imu` | ~200 Hz | ______ | ______ | ______ |
| 3 | vendor LiDAR odometry `utlidar/robot_pose` | ~10 Hz | ______ | ______ | ______ |
| 4 | vendor voxel map `utlidar/voxel_map_compressed` | ~1 Hz | ______ | ______ | ______ |
| 5 | `sportmodestate` | ~50 Hz | ______ | ______ | ______ |
| 6 | `lowstate` | ~500 Hz | ______ | ______ | ______ |
| 7 | `lf/lowstate`, `lf/sportmodestate` | ~10 Hz | ______ | ______ | ______ |
| 8 | `wirelesscontroller` | on change | ______ | ______ | ______ |
| 9 | front camera `/frontvideostream` (**not DDS**) | vendor path | ______ | ______ | ______ |
| 10 | add-on L2 cloud | ~10–20 Hz | ______ | ______ | ______ |
| 11 | add-on L2 IMU | ~200 Hz | ______ | ______ | ______ |
| 12 | D455 color | ______ | ______ | ______ | ______ |
| 13 | D455 depth | ______ | ______ | ______ | ______ |
| 14 | D455 IR ×2 | ______ | ______ | ______ | ______ |
| 15 | D455 IMU | ______ | ______ | ______ | ______ |
| 16 | Orin `tegrastats` | ______ | ______ | ______ | ______ |
| 17 | GNSS ZED-F9P | CONFIRM on hand | ______ | ______ | ______ |
| 18 | UWB owner fob | CONFIRM on hand | ______ | ______ | ______ |
| 19 | XVF3800 mic array | **AWAITING** (in the post) | ABSENT (expected) | — | — |

D455 profile actually selected (a **budget decision**, not a default — see
[BANDWIDTH_BUDGET.md](../BANDWIDTH_BUDGET.md)):

```text
d455_profile:   ______ × ______ @ ______ Hz   color=______ depth=______ ir=on/off
predicted_rate: ______ MiB/s     predicted_GiB_per_hour: ______
measured_rate:  ______ MiB/s     (from the sidecar, after the take)
```

Bag / sidecar evidence:

```text
mcap_path:        ____________________________________
mcap_sha256:      ____________________________________
sidecar_path:     ____________________________________
sidecar_verify:   PASS / FAIL          (mutating one byte must FAIL — PS-B gate)
truncation flag:  none / TRUNCATED     (a SIGKILL or brown-out ⇒ TRUNCATED, not a dropout)
degraded channels + deficit: ____________________________________
harness green (P6): paste the pytest line ____________________________________
```

### C0.4 — "Soft stop + both hardware e-stops trip the stop path within ≤300 ms budget (measure)"

**Producer: §5 of this sheet (operator action) + PS-B bag (the timestamps).**
Split into a measurable half and an honestly-deferred half — see the boxed
note in §5. Copy the two results here:

```text
vendor stop response, recoverable from bag:  YES / NO   (NO ⇒ recorder was not running)
Parcel software stop-path latency:           NOT MEASURED — nothing armed this session
consequence: the ≤300 ms budget remains UNVERIFIED and is a Stage-1/2 measurement
```

### C0.5 — "Comms-loss auto-damp demo once (disconnect → damp → latched stop)"

**Producer: operator action (§5 E3, re-verified at §9 if the dog stands) + PS-B bag.**

The damp behaviour is only *visible* on a dog that is holding a posture. If
the dog never leaves the ground this session, the demonstration is partial and
must say so:

```text
demonstrated with dog:  SEATED / STANDING / NOT DEMONSTRATED
if SEATED: recorded as PARTIAL — the standing-damp case is UNVERIFIED
```

### C0.6 — "Runtime refuses Sport arm without commissioning record"

**Producer: operator action — three read-only demonstrations. NO ARM IS
ATTEMPTED.**

| # | Demonstration | How (read-only) | Expected | Result |
|---|---|---|---|---|
| D1 | The vendor SDK is absent from every Parcel environment | `python -c "import unitree_sdk2py"` in the Parcel venv **and** in the Orin capture env | `ModuleNotFoundError` in both | ______ |
| D2 | Config cannot arm by itself | inspect `configs/robot.yaml`: `control.controller` is `simulator` (`:114`); `axes_commissioned: false` (`:135`), `state_frame_commissioned: false` (`:137`), `allowed_modes: []` (`:142`) | all four as stated | ______ |
| D3 | The factory refuses an unknown/uncommissioned controller | run the existing CI test `tests/test_portability_proof.py` | pass | ______ |

> **Do not** construct a `RobotRuntime`, a `ControlManager`, or a motion client
> to produce this row. `runtime.py:385-391` does raise
> *"configuration alone cannot arm hardware"* for any non-`simulator`
> controller — but **no test in the repo pins that refusal** (measured:
> `grep -rl "configuration alone cannot arm hardware" tests/` → no match).
> That missing pin is a **finding for the backlog**, not a thing to exercise
> by hand on a hardware day.
>
> **Standing prohibition for the whole session:** do not edit
> `control.controller`, `enable_lease`, `axes_commissioned`,
> `state_frame_commissioned`, or `allowed_modes`; do not `pip install`
> `unitree_sdk2py` into any environment. Note that
> `configs/robot.yaml:133` already has `enable_lease: true` — three of the
> factory's four flags fail closed, the fourth does not. The absent SDK and
> `controller: simulator` are what is actually holding the line.

### C0.7 — "Evidence: run ID `P5-DRY-…`, bag digest, latency snapshot → fill template"

**Producer: this sheet §1 + PS-B sidecar (bag digest) + PS-C (clock) + PS-D
(attestation digest).** Complete when §1 has no blanks and §11 is signed.

---

## 7A · The take script — what actually gets recorded

> **Added 2026-08-13 by card PS-K** (corrective tranche PS-2). Sections 0–7 and
> 8–12 are unchanged and keep their numbers; every `file:line` citation into
> this sheet from other documents still resolves to the same text.

Everything above this line proves the **stack** works: preflight, attestation, a
bag, a digest, a stop test. That is a **dry-run record, and a dry-run record is
not a dataset.** The ordered takes — what to point the sensors at, for how long,
and in what order — are in **[TAKE_SCRIPT.md](TAKE_SCRIPT.md)**, T0–T16, and the
session is run from **both** sheets: this one for safety, branches and evidence;
that one for the bags.

### ⚠ Two numbering spaces called "T"

§3 above has rows **T1–T6**: those are **commands to transcribe**. The take
script has **T0–T16**: those are **takes**. They are unrelated, and both
numberings are load-bearing (other landed cards cite §3's rows by id). **Never
write a bare `T4`** — write *"command row T4"* or *"take T4"*.

### The non-skippable core — 30 minutes, before any free-form activity

| Take | Min | Why it cannot be moved or skipped |
|---|---:|---|
| **T3 SYNC-OPEN** | 5 | The dog exposes **no clock protocol** and its 500 Hz IMU channel has **no timestamp at all**. A bracketed physical sync ritual is the **only** mechanism that recovers cross-device offset. Skipped ⇒ no bag from this session has recoverable cross-device time. |
| **T4 FOOT-FORCE ZERO-OFFSET** | 5 | `foot_force[4]`/`foot_force_est[4]` are `int16` **raw counts with no published units, gain or offset**. Skipped ⇒ the numbers are uninterpretable forever. |
| **T5 STATIC** | 15 | IMU bias, noise floor, thermal baseline — every uncertainty this dataset can ever carry is measured against this interval. |
| **T14 SYNC-CLOSE** | 5 | T3 verbatim, on the **still-bolted, still-powered** rig, as the **last action of the day**. Bracketing is what turns an offset into an offset **plus a drift slope**. |

**If the day is cut short**, [TAKE_SCRIPT.md](TAKE_SCRIPT.md) §5 is the explicit
ladder of what must already exist. Its short form: **geometry + photos → the
pre-torque FOV gate → T3 → T14 → T4 → T5**, and **T14 always happens before
power-down**, even if it is the only other thing that happens.

### D455 profile freeze

The profile chosen in C0.3 above is **frozen for the whole day**. Camera
intrinsics are per-profile: change the profile after take T9 and T9's
calibration no longer applies to anything recorded after it.

### The nine channels C0.3's table predates

C0.3's 19-row table was written against the PS-1 matrix. PS-H's rewrite carries
**25 rows / 28 channels**. The rows below are the difference — all free, all
recorded by the same recorder, all costing a second session to recover. Fill
them beside C0.3's table, from the PS-D attestation.

| # | Channel (ROS name) | Rate | `PRESENT`/`ABSENT`/`DEGRADED` | Observed | Msgs |
|---|---|---|---|---|---|
| 20 | `utlidar/lidar_state` — **settles L1-vs-L2 electronically**, + packet loss + firmware | ~1 Hz | ______ | ______ | ______ |
| 21 | `utlidar/cloud_deskewed` | ~10 Hz | ______ | ______ | ______ |
| 22 | `utlidar/robot_odom` (service-gated) | ~10 Hz | ______ | ______ | ______ |
| 23 | `utlidar/switch` — **SUBSCRIBE-ONLY, never write** | on change | ______ | ______ | ______ |
| 24 | front camera **H.264** — not a topic: RTP over multicast `230.1.1.1:1720` | ? | ______ | ______ | ______ |
| 25 | `uwbstate` | ~20 Hz | ______ | ______ | ______ |
| 7b | `lf/sportmodestate` (row 7 is **two** channels) | ~10 Hz | ______ | ______ | ______ |
| 14b | D455 infrared **right** (row 14 is **two** channels) | ______ | ______ | ______ | ______ |
| 15b | D455 **gyro** (row 15 is accel **and** gyro, two rates) | ______ | ______ | ______ | ______ |

**Two corrections to C0.3's table itself, which must not be filled as printed:**

```text
row 9 "front camera (**not DDS**)" is REFUTED — it IS a DDS topic,
      `frontvideostream` carrying JPEG frames at ~33 Hz.  Record it as a topic.
      which resolution field is populated (720p/360p/180p)? ______
rows 3, 4, 5, 22 are SERVICE-GATED — a publisher can exist and emit nothing.
      `ABSENT` here means "no message received", NOT "bad DDS config".
      obstacle avoidance ON  → which publish? ______________________
      obstacle avoidance OFF → which publish? ______________________
```

**Payload fields to confirm inside rows 5 and 6** (they are *fields*, not
channels — they arrive when their parent arrives and cost no extra bandwidth):
`range_obstacle[4]` and `stamp` inside row 5; `tick`, `power_v`/`power_a`,
`wireless_remote[40]`, `motor_state[20]` (**0–11 actuated, 12–19 padding**),
`foot_force[4]` **and** `foot_force_est[4]`, `bms_state` (**no voltage field**),
`imu_state`, `fan_frequency[4]`, `temperature_ntc1/2` inside row 6.

```text
fields confirmed present in a received message (list any that are MISSING):
  ______________________________________________________________________
```

---

## 8 · The Stage-0 → Stage-1 boundary: the pre-stand gate

**Read this even if you do not plan to stand the dog.**

`P5_COMMISSIONING_CHECKLIST.md:81` defines Stage 0 as **motion disabled**.
Standing is motion. A stand therefore **crosses into Stage 1**
(`:82` — "Stand / sit / standstill; no locomotion"), and the checklist's rule
(`:86-88`) demands the stop verification be run **again** at that entry (§9).

**Envelope this sheet authorises, and nothing beyond it:**

- Permitted: the dog **seated / on blocks / on a stand**, powered, publishing.
- Permitted **only after §9 passes**: an operator-initiated **stand and sit**,
  under the **vendor handheld**, feet stationary, no gait, no locomotion, no
  yaw. Parcel software subscribes and records; it commands nothing, ever.
- **Not authorised by this sheet at any point:** locomotion, gait, teleop
  through Parcel, arming, autonomy of any kind, stairs, or leaving the mat.

### Pre-stand mechanical gate — every row before any stand

The hazards of a sensor-only session are **mechanical, not autonomy**. Full
descriptions in [SAFETY_BRIEF.md](SAFETY_BRIEF.md) §3.

> **⚠ ORDERING, amended 2026-08-13 by PS-K.** Two rows below were being read as
> paperwork to be signed at the moment of the first stand. They are **ordering
> constraints on the whole day**, and taking them late is how the payload gets
> destroyed while nobody is expecting it:
>
> 1. **The mat goes down before the dog is powered at all** (S0) — not before
>    the stand. A powered Go2 can move without a command from you
>    ([SAFETY_BRIEF.md](SAFETY_BRIEF.md) H4), and the first unplanned posture
>    change is the one nobody is standing ready for.
> 2. **A stop press DROPS a standing dog**, payload first, from ≈0.3 m (H5).
>    That drop therefore happens **once, deliberately, over the mat, with
>    everyone expecting it** — as [TAKE_SCRIPT.md](TAKE_SCRIPT.md) take **T2c**,
>    recorded — **before any take that puts the payload on a standing dog**
>    (T4's standing segments, T5, T10, T13). Not discovered at T10.
> 3. **Drop acceptance is stated aloud before the first stand** (S9), by
>    everyone, not initialled quietly afterwards.

| # | Check | Pass criterion | Result |
|---|---|---|---|
| **S0** | **Mat down and floor cleared — BEFORE the dog is powered**, not before the stand | Padded mat under the dog and under the intended stand position; ≥1.5 m clear radius; done at the time of the safety brief | ______ |
| S1 | **Payload security** — Orin, D455, L2, brackets, battery | Each item cannot be moved by a firm two-finger pull in **any** axis. Every fastener seated; nothing held by tape or friction alone. | ______ |
| S2 | **Payload mass + placement recorded** | Total added mass ______ g, recorded in the geometry sheet. Nothing overhangs a leg's sweep. | ______ |
| S3 | **Cable strain relief** | Every cable has a service loop and is anchored **within 100 mm of each connector**, so a pull loads the anchor, not the connector. | ______ |
| S4 | **Cable routing out of the leg envelope** | No cable crosses a hip or knee sweep, passes under the trunk, or can be stood on. Trace each cable end-to-end with a finger and say it aloud. | ______ |
| S5 | **Pinch points clear** | No cable, strap, or tie-wrap tail inside a joint gap. Nothing routed through the trunk-to-leg gap. | ______ |
| S6 | **Connector seating** | Every connector positively latched; photographed (PHOTO_LIST P12). USB-C to the D455 is the classic silent unseat. | ______ |
| S7 | **Floor** | ≥1.5 m clear radius; **padded mat under the dog**; no trip hazards across the walk route; nobody within the leg envelope. | ______ |
| S8 | **Hands and heads** | No hand under the trunk, no face within 500 mm, for the whole time the dog is powered. | ______ |
| S9 | **Drop acceptance** | Everyone states aloud that a stop press **drops a standing dog** and that the payload may be damaged. Payload treated as expendable from here. | ______ |
| S10 | **Thermal** | Orin and D455 not hot to touch before handling; airflow not blocked by the bracket or a cable. | ______ |
| **S11** | **The deliberate standing-stop drop test has been done** — §9 E1′, over the mat, **with the recorder running** ([TAKE_SCRIPT.md](TAKE_SCRIPT.md) take T2c) | No take that relies on the payload staying on a **standing** dog may run before this. Damage found afterwards is recorded, and the payload is re-checked from S1. | ______ |

> **STOP BAR.** Any `S` row not passed ⇒ **the dog does not stand.** That is
> not a failure of the session; the seated take is a complete Stage-0 record.
> **Takes T4 and T5 then run seated and are marked `DEGRADED — dog not stood`**,
> which is a legitimate outcome and still yields the zero-offset and the noise
> floor.

---

## 9 · ⛔ STOP BAR — Stage-1 entry stop verification (only if standing)

Re-run the **whole** of §5, from scratch, and write new times. Do not copy the
§5 results forward — the checklist requires re-verification at every stage
entry, and copying is exactly the thing that rule exists to prevent.

| # | Check | Result | Time UTC |
|---|---|---|---|
| E1′ | Stop #1 while standing | ______ | ______ |
| E2′ | Stop #2 while standing | ______ | ______ |
| E3′ | Comms loss while standing (→ damp → latched) | ______ | ______ |

**Do E1′ over the padded mat, once, deliberately, with the recorder running.**
The dog will drop. That drop is the evidence.

> **This whole section is [TAKE_SCRIPT.md](TAKE_SCRIPT.md) take T2c**, and it is
> the **first standing action of the day** — before take T4's standing segments,
> before T5, before any walk. Give it a bag directory and a row in the take log
> ([TAKE_SCRIPT.md](TAKE_SCRIPT.md) §2): the press is timestamped on
> `wirelesscontroller`, the response is in `lowstate` and `sportmodestate`, and
> the interval is recoverable **only** from a bag that was running at the time
> (§5). Inspect the payload after the drop and re-run S1 before anything else
> stands on it.

Second's verbal confirmation before the first stand: *"Mat down, cables clear,
payload solid, I have stop #2."*  [ ]

---

## 10 · Refusals, faults, and surprises — write them down as they happen

The refusal messages are evidence. Paste them verbatim; do not paraphrase.

```text
time UTC | what was attempted | verbatim message / observation
_________|____________________|________________________________________________
_________|____________________|________________________________________________
_________|____________________|________________________________________________
_________|____________________|________________________________________________
```

Specifically capture, if they occur: the firmware-pin refusal, the disk-budget
refusal, any `ABSENT` channel and the probe that produced it, any recorder
truncation, any brown-out, any connector that unseated, and every `STOP` call.

---

## 11 · ⛔ STOP BAR — teardown, before a single bolt is loosened

- [ ] **Take T14 SYNC-CLOSE recorded BEFORE power-down** — [TAKE_SCRIPT.md](TAKE_SCRIPT.md) T14, on the still-bolted, still-powered rig. It is 5 minutes and it is what turns take T3's offset into an offset **plus a drift slope**. If it was skipped, write that in `does_not_prove` in those words.
- [ ] **The take log is filled** — [TAKE_SCRIPT.md](TAKE_SCRIPT.md) §2, one row per take, including the takes that did **not** happen and why
- [ ] **§4A pre-torque FOV verdict recorded** in [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md) — `CONFIRMED` / `MARGINAL` / `NONE` / `NOT DONE`
- [ ] **M2 re-measure done** — the teardown column of [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md) is filled **while the rig is still assembled**. A delta beyond tolerance invalidates the session's extrinsic; you can only know that now.
- [ ] Every **MANDATORY** photograph in [PHOTO_LIST.md](PHOTO_LIST.md) taken and offloaded
- [ ] Bag + sidecar + clockmap + attestation copied off the Orin to a second physical device; both copies' digests compared and recorded
- [ ] `P5_PROCUREMENT_BOM.md` receipt/inventory table filled with the real serials
- [ ] §1 run header has **no blanks**, including a non-empty `does_not_prove`
- [ ] This sheet photographed (PHOTO_LIST P19) so the handwriting survives

```text
digest of the off-Orin copy:  ____________________  matches on-Orin: YES / NO
teardown completed:  ______ UTC   operator ____________  second ____________
```

### Gate close record (`checklist:205-211`) — fill one per gate actually closed

```text
gate:        P5-G-…
result:      pass | fail | blocked
evidence:    run_id + bag_digest
ledger:      update hardware-readiness.md row → validated (do not delete history)
```

Expected honest outcome of this session: **P5-G-INSTALL — blocked** (no golden
image flashed, one dock only); **P5-G-BAG-DROPIN — pass only if** real bags
went through the `parcel.bag.v1` harness with no schema change. Do not write
`pass` for a gate whose evidence is a plan.

---

## 12 · What this sheet does not authorise, and does not prove

**Does not authorise.** Locomotion. Gait. Teleoperation through Parcel.
Arming. Any autonomy. Any firmware flash. Any install onto the single Orin.
Any edit to `control.controller`, `enable_lease`, `axes_commissioned`,
`state_frame_commissioned`, or `allowed_modes`. Any `pip install` of
`unitree_sdk2py`. Any Stage 2 or Stage 3 activity.

**Does not prove** (this is the *floor* for §1's `does_not_prove`, not the
whole of it — add what the day actually showed):

- Nothing on this sheet has been executed. It is blank paperwork until an
  operator fills it at the session.
- A filled sheet proves what the sensors and the stack did **on one day, in
  one place, at one temperature, with one payload**. It says nothing about
  behaviour under motion, outdoors, over time, or at any other mount geometry.
- It proves nothing about Parcel's stop-path latency, because nothing was
  armed. The ≤300 ms budget is untested by this session.
- It proves nothing about the golden image or the firmware-pin ADRs: no flash
  was performed and the two-dock rule was not exercised.
- A `PRESENT` channel means *a message was received*. It does **not** mean the
  message carries what we believe it carries. Verifying the semantic content
  of any Unitree topic is a separate, later job.
- The mount geometry is a **tape measurement with a stated uncertainty**, not
  a calibration. It is the best recoverable record of a thing that stops
  existing when the bracket comes off — not a substitute for extrinsic
  calibration.
- Recording a channel proves it was recorded. It proves nothing about whether
  the data in it is *good*.
- **A dry-run record is not a dataset.** Everything §7 closes is evidence that
  the *stack* worked. Whether the session produced data anyone can calibrate,
  fuse or evaluate against depends on the takes in
  [TAKE_SCRIPT.md](TAKE_SCRIPT.md), and on nothing in §7.
- **The takes are a plan written by someone who has never seen this rig.** Their
  durations are optimistic estimates, their commands are unverified against a
  real Go2, and whether the calibration takes actually converge is a next-week
  question that this sheet cannot answer and must not claim.
- **A completed take script does not prove a calibration exists.** It proves the
  *inputs* were captured in a form the standard tools ask for.
