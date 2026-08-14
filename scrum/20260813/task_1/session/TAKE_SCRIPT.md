# Take script — what actually gets recorded, in what order, and why

> ## ⬜ BLANK BY DESIGN — NOTHING HERE HAS BEEN EXECUTED
>
> Every `RECORD` field, every time, every digest on this sheet is filled **by
> hand, at the session, by the operator**. No take on this sheet has been shot.
> A blank is honest; a plausible-looking number is the first false entry in the
> dataset. **Unknown = absent.**

**Card:** PS-K, corrective tranche **PS-2** · **Written:** 2026-08-13 ·
**Author:** Fable (PS-K)
**Extends, does not replace:** [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) — that
sheet governs safety, stop bars, branches and evidence; **this sheet governs
what goes in the bags.** Where the two disagree, the run sheet wins.
**Pack:** [README.md](README.md) · [SAFETY_BRIEF.md](SAFETY_BRIEF.md) ·
[MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md) ·
[PHOTO_LIST.md](PHOTO_LIST.md) · [TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md)
**Channels:** [CHANNEL_MATRIX.md](../CHANNEL_MATRIX.md) — 25 rows / **28
channels** / 11 payload-field rows · **Budget:** [BANDWIDTH_BUDGET.md](../BANDWIDTH_BUDGET.md)

### Why this sheet exists

The session pack as it stood had **no data-collection takes at all**. Measured
at card start, over the whole pack:

```console
$ grep -rniE "excitation|static.bias|loop.closure|calibration.target|per.point.time|apriltag|aprilgrid|allan" \
    scrum/20260813/task_1/session/
EXIT=1        (no output — zero hits in any sheet)
```

The run sheet proves the **stack** works: preflight, attestation, a bag, a
digest, a stop test. That is a *dry-run record*. **A dry-run record is not a
dataset.** Nothing in it tells the operator to excite the IMU so a LiDAR-IMU
extrinsic can be solved, to zero the foot-force counts so they mean anything
later, to close a loop so drift can be measured, or to bracket the day with a
physical sync event so cross-device time can be recovered at all.

**There is no second session.** Every take below is on this sheet because the
thing it captures stops existing when the rig is unbolted and the dog is powered
down.

---

## 0 · How to use this sheet

1. **One take = one bag = one row in the take log (§2).** A take with no row is
   an unfindable bag; a row with no bag is a `NOT RECORDED`.
2. Each take has the same six parts: **WHY** (what becomes impossible without
   it) · **WHEN** · **CHANNELS** · **DO** · **RECORD** (blank) · **DONE-WHEN /
   BRANCH**.
3. **Work top to bottom.** The order is a dependency order, not a preference.
   T3/T4/T5 come before everything discretionary because a discretionary take
   recorded before them is *unusable* — see §3.
4. Write **units** on every number, and **UTC** on every time. A bare number is
   a defect.
5. Provenance tags, same convention as [TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md) §0:
   - **[REPO]** — verified in this repository at a cited `file:line`.
   - **[EXT]** — external research via [`../RISK_ASSESSMENT.md`](../RISK_ASSESSMENT.md).
     True of Go2/D455/Orin units *described online*; **not yet true of ours.**
   - **[UNVERIFIED-SYNTAX]** — a command whose exact flags could not be checked:
     the dev box has no ROS, no RealSense, no Jetson, no `mcap`. **Run `--help`
     first and correct the flag**; the requirement is the measurement, never the
     exact string.
   - **[MEASURED-JAZZY]** — checked by actually running `--help` inside the
     repo's ROS 2 **Jazzy** sandbox
     (`.cache/external-evals/runtime/ros-jazzy-base-sandbox`, which carries
     `rosbag2_storage_mcap`). **The Orin is expected to be Humble**, and flags do
     move between distros, so this is a strong prior and **not** a guarantee.
     Run `--help` on the Orin anyway.

### Recorder and discovery flags — [MEASURED-JAZZY], and three of them change the plan

| Finding | Consequence for the day |
|---|---|
| `--max-bag-size` **default 0** *and* `--max-bag-duration` **default 0** — both split thresholds off by default | Answers the question tonight's N4e sends the operator looking for. Pass `--max-bag-size 0` anyway: **explicit beats default**, and a split bag is the documented loss path. |
| `--storage-preset-profile {none,fastwrite,zstd_fast,zstd_small}` exists | A **named preset** for the mcap plugin. The hand-written `~/tonight_mcap.yaml` carries a real risk that **unknown YAML keys are silently ignored**; a preset cannot be silently misspelt. If last night could not confirm compression was applied, use `--storage-preset-profile zstd_fast` instead of the config file. |
| `--custom-data KEY=VALUE` exists, repeatable | **Put the take id, its purpose and the `run_id` inside the bag's own metadata.** A bag that describes itself survives the loss of this sheet, of the take log, and of its own directory name. **Check it exists on the Orin's distro first** — it is newer than `--max-bag-size` and may be absent on Humble; if absent, drop a two-line `TAKE.txt` in the bag directory instead. |
| `--max-cache-size` **default 104857600** (100 MiB), **double-buffered — up to 2× that in RAM** | The 512 MiB tonight's N4 rehearsed means up to **1 GiB** of recorder RAM on the Orin. Fine on a 16 GB module; worth knowing on an 8 GB one. |
| In Jazzy the **positional** topic list is deprecated in favour of `--topics` | Harmless on Humble, where the positional form is normal. If the recorder warns, switch to `--topics`. |
| `ros2 topic hz -w/--window` · `ros2 topic echo --once --full-length` · `ros2 topic info -v` · `ros2 interface show` · `ros2 bag info` — **all present, these spellings** | Every command take T0 depends on is spelt correctly below. |

### ⚠ Two numbering spaces called "T". Do not confuse them.

| Where | What `T4` means there |
|---|---|
| [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §3 rows **T1–T6** | a **command to transcribe** before the run (T4 = the record command) |
| **this sheet**, rows **T0–T16** | a **take** — a recording with a purpose (T4 = foot-force zero-offset) |

**Never write a bare `T4`.** Write *"command row T4"* or *"take T4"*. The run
sheet's §3 rows keep their ids — they are cited by other landed cards
([`../PSE_STATUS.md:400`](../PSE_STATUS.md) names `record.py` at command row T4)
and renaming them would break those citations.

### Standing rules, unchanged and non-negotiable

- **Nothing arms anything.** No take here publishes a robot command, creates a
  `ControlManager`, takes a lease, or constructs a motion client. Parcel
  subscribes and records; it never commands. **[REPO]**
  `../CHANNEL_MATRIX.md` row 23: `utlidar/switch` is the one topic the vendor
  stack treats as an **input** — **we subscribe and never write to it.**
- The **only** thing that moves the dog is the **vendor handheld, in the
  operator's hand**, and only inside the envelope
  [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §8 authorises. Takes T10 and T13
  ask for more than that envelope grants and carry their own authorisation gate.
- The **second holds stop #2 and has no other job** for the whole day
  ([SAFETY_BRIEF.md](SAFETY_BRIEF.md) §4), including during every take on this
  sheet. The second never runs a take.
- **No source edits, no config edits, no installs** during the session
  ([STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §12).

### Bag naming — decide once, before T0

```text
run_id (from run sheet §1):  P5-DRY-________T______Z
bag root:                    /data/<run_id>/
one directory per take:      /data/<run_id>/T03_sync_open/
                             /data/<run_id>/T05_static/            ...
non-bag artifacts:           /data/<run_id>/T00_discovery/*.txt
```

The **take id must be in the directory name.** Six months from now the directory
name is the only thing that says what a bag was *for*, and a bag whose purpose is
unknown is a bag nobody will trust.

### ⛔ PROFILE FREEZE — decide the D455 profile before T3, then do not change it

Camera **intrinsics are per-profile.** The AprilGrid take (T9) calibrates the
resolution it was shot at. If the profile changes after T9, **T9 must be re-run
at the new profile or the intrinsics do not apply to any later take.**

```text
d455_profile frozen at: ______ × ______ @ ______ Hz  colour ___ depth ___ IR ___
frozen at ______ UTC by ____________   (copy into run sheet §7 C0.3)
changed mid-session?  NO / YES → which takes are before the change: ____________
                                 T9 re-run at the new profile?  YES / NO
```

Default, and the only profile the whole stack has been driven through end to end:
**848×480@30 colour+depth+IR pair**, whole-rig **84.60 MiB/s ≈ 297.4 GiB/hour**
— **[REPO]** [`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md) §1. If tonight's
`N2c` frame count forced a lower profile, that profile wins
([TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md) N2c → run sheet §3).

---

## 1 · The day at a glance

`irrecoverable?` = *does the ability to capture this end when the dog powers
down and the bracket comes off?*

| # | Take | Duration | Recorded? | Irrecoverable? | What it makes possible later |
|---|---|---:|---|---|---|
| **T0** | Discovery — topics, rates, fields, IDL, LiDAR state | 30 min | artifacts, not a bag | **YES** | Knowing what our unit actually publishes; the transcode key for every bag |
| **T1** | First bag — tier-1 DDS only, **no payload mounted** | 10 min | ✔ | **YES** | A real bag inside the first hour; the **unoccluded** built-in-LiDAR reference |
| **T2** | Mount · geometry M1 · **pre-torque FOV gate** · photos · pre-stand gate | 60 min | T2c only | **YES** | Every extrinsic; the two-LiDAR asset; the drop test that must precede trust |
| **T3** | **SYNC-OPEN** | **5 min** | ✔ | **YES** | **The only cross-device clock evidence that exists.** §3 |
| **T4** | **FOOT-FORCE ZERO-OFFSET** | **5 min** | ✔ | **YES** | Makes `foot_force` int16 counts mean something, ever. §3 |
| **T5** | **STATIC** | **15 min** | ✔ | **YES** | IMU bias, noise floor, thermal baseline, rate stability. §3 |
| T6 | Hand-carried 3-axis excitation | 15 min | ✔ | **YES** | LiDAR↔IMU extrinsic **and** time offset |
| T7 | Visual–LiDAR calibration, 5–10 **separate** short bags | 20 min | ✔ ×5–10 | **YES** | Camera↔LiDAR extrinsic |
| T8 | Static planar-structure captures, **both** LiDARs | 12 min | ✔ ×3–5 | **YES** | LiDAR↔LiDAR extrinsic (the cross-validation asset) |
| T9 | AprilGrid 6-DOF, locked short exposure; repeat IR-projector-off | 20 min | ✔ ×2 | **partly** | Intrinsics (redoable) · camera↔IMU extrinsic + time offset (**not** redoable) |
| T10 | Walk take — loops, taped mark, taped 10 m baseline | 25 min | ✔ | **YES** | Loop closure, drift ground truth, scale check |
| T11 | Power-cycle pose-origin probe | 12 min | ✔ ×2 | **YES** | Settles the undocumented `SportModeState.position` origin/reset |
| T12 | Deliberately degenerate take (bare corridor) | 8 min | ✔ | **YES** | The negative control — the take that makes a positive result mean something |
| T13 | Exposure capped ≤5 ms | 10 min | ✔ | **YES** | Removes gait-locked blur, which is **systematic**, not noise |
| **T14** | **SYNC-CLOSE — repeat T3 verbatim, last action on the powered rig** | **5 min** | ✔ | **YES** | The **drift slope**. Without it T3 gives an offset with no rate. §3 |
| T15 | Teardown — **M2 re-measure before loosening**, photos | 25 min | no | **YES** | Proof the bracket did not shift; the extrinsic's validity |
| T16 | Overnight ≥3 h static IMU (Allan variance) | ≥3 h | ✔ | **NO** | IMU noise model — the **one** take a later session could redo |

**≈4.5 h of takes.** Add the run sheet's brief, preflight, attestation and
go/no-go (≈45 min) and setup (≈30 min): a **≈6 hour day** before T16.

---

## 2 · The take log — fill as you go, one row per take

This is the index that makes the bags findable. Copy the run header's `run_id`
into every row's path. **A take that is not in this table did not happen**, as
far as any later reader is concerned.

| Take | Bag / artifact path | Start UTC | End UTC | Channels + profile | Msgs / size | Sidecar digest | Verdict | One line: what happened |
|---|---|---|---|---|---|---|---|---|
| T0 | ______ | ____ | ____ | n/a | ______ | ______ | ______ | ______ |
| T1 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T2c | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T3 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T4 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T5 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T6 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T7 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T8 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T9 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T10 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T11 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T12 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T13 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T14 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |
| T16 | ______ | ____ | ____ | ______ | ______ | ______ | ______ | ______ |

*(T7 and T8 are several bags each — add sub-rows `T7.1 … T7.n`.)*

```text
take_log_ref (write into run sheet §1):  this sheet §2, filled by ____________
takes NOT recorded, and why (this is evidence too):
  ______________________________________________________________________
  ______________________________________________________________________
```

---

## 3 · ⛔ THE NON-SKIPPABLE CORE — ~30 minutes, before any free-form activity

**T3 (5) + T4 (5) + T5 (15) + T14 (5) = 30 minutes.** Everything else on this
sheet is discretionary. These four are not, and the reason is the same for all
four: **they are the takes that make the other takes interpretable.** A
beautiful walk take recorded without T3 is a set of streams that cannot be put
on one timeline. A foot-force trace recorded without T4 is a column of int16
counts with no zero and no scale.

| | Why it cannot be skipped | What is lost if it is |
|---|---|---|
| **T3 SYNC-OPEN** | **[EXT]** `../RISK_ASSESSMENT.md:81-102`: the Go2 exposes **no queryable clock and no round-trip primitive**, and its densest channel (`lowstate`, 500 Hz IMU) **carries no timestamp at all** — only a wrapping `uint32` `tick`. A software clock protocol **cannot be run against this robot.** The bracketed physical ritual is not a nice-to-have, it is *the mechanism*. | Every cross-device timestamp in the whole session. Nothing recovers it afterwards. |
| **T4 FOOT-FORCE ZERO-OFFSET** | **[EXT]** `../CHANNEL_MATRIX.md` Table B F7: `foot_force[4]` and `foot_force_est[4]` are **`int16` raw counts** from an air-pressure contact proxy with **no published units, gain or offset**. | The only ground-truth contact signal in the rig, permanently. The numbers stay uninterpretable forever. |
| **T5 STATIC** | Bias, noise floor and thermal baseline are *defined* by a quiet interval. Every later noise claim is measured against this one. **[EXT]** two independent reports have `utlidar/imu` emitting \|accel\| of order **1e24 m/s²** — T5 is where that is caught, by PS-J's plausibility gate, not by a receipt count. | Every uncertainty number the dataset could ever carry. |
| **T14 SYNC-CLOSE** | T3 alone gives an **offset**. T3 **and** T14 give an offset **and a drift rate**, plus a residual that says whether the model held. **[EXT]** two published quadruped-dataset teams (CEAR, M-SEVIQ) bracket exactly this way. | The drift slope — i.e. you learn the clocks were offset but not that they were *diverging*, which is the part that ruins long takes. |

> **The core rule, stated once:** if at any moment the day looks like it may end
> early, **stop what you are doing and complete the core.** T14 in particular is
> **the last action on the still-bolted, still-powered rig, always** — even if it
> is the only other thing that happens after T3. See §5.

---

## 4 · The takes

### T0 · DISCOVERY — before anything is mounted · 30 min · artifacts, not a bag

**WHY.** Every row of [`../CHANNEL_MATRIX.md`](../CHANNEL_MATRIX.md) is
**documentation about other robots** (that sheet says so itself, in bold, at the
top). T0 is where documentation becomes measurement, on our unit, and four of its
outputs are things a bag alone does **not** give you:

- **the topic list and per-topic QoS** — a topic with a publisher that emits
  nothing is **[EXT]** the documented failure mode of the service-gated rows
  (`sportmodestate`, `utlidar/robot_pose`, `utlidar/voxel_map_compressed`,
  `utlidar/robot_odom`), and at the DDS layer it is *indistinguishable from a bad
  network config*. `ros2 topic info -v` separates the two in one command.
- **`ros2 topic hz` with the built-in obstacle avoidance ON and then OFF** —
  this is the **only** thing that settles open question 1 of the matrix
  (*can the vendor SLAM outputs coexist with our own SLAM, or does
  obstacle-avoidance-off kill them?*). One sweep in each state, ten minutes, and
  a question that has been open all week is closed with data.
- **`PointCloud2.fields[]` for every cloud topic** — whether there is a
  **per-point time** field, what it is called, its datatype and offset. Every
  deskewing SLAM (FAST-LIO2, Point-LIO, GLIM) needs it. The field is recoverable
  from a recorded message later; **what is not recoverable is today's chance to
  change a driver setting that would have added it.**
- **the robot's own `unitree_go` / `unitree_api` message definitions, as the
  running system has them** — without the IDL text in the bag directory, a later
  transcode of these bags is guesswork. It costs one loop.

**WHEN.** Dog powered, **seated**, on the mat, after the run sheet's §5 stop
verification. **Nothing is bolted to the dog yet** — the Orin sits bench-side,
cabled to the robot LAN. Payload mounting is T2.

**CHANNELS.** None recorded to a bag; text artifacts only.

**DO** — the `ros2` **flags** below are [MEASURED-JAZZY]; the **topic names** are
[EXT] and are exactly what this take exists to check. Run `--help` on the Orin
first; do not fight the sheet.

```bash
# ON THE ORIN.  RUN_ID from run sheet §1.
export A=/data/$RUN_ID/T00_discovery && mkdir -p $A && cd $A
date -u | tee t00_start_utc.txt

# (a) THE SESSION'S FIRST ARTIFACT — write it, then copy it off the Orin at once
ros2 topic list | tee topic_list.txt | wc -l

# (b) per-topic type, publisher count and QoS — separates "silent" from "absent"
for t in $(cat topic_list.txt); do
  echo "===== $t"; ros2 topic type "$t"; ros2 topic info -v "$t"
done > topic_info.txt 2>&1

# (c) the message definitions the RUNNING system has, not the ones we assume
for ty in $(for t in $(cat topic_list.txt); do ros2 topic type "$t"; done | sort -u); do
  echo "===== $ty"; ros2 interface show "$ty"
done > idl_dump.txt 2>&1
ros2 interface list | grep -iE 'unitree' > unitree_interfaces.txt
sha256sum idl_dump.txt topic_list.txt topic_info.txt | tee t00_digests.txt

# (d) rate sweep — OBSTACLE AVOIDANCE **ON** (vendor default)
for t in $(cat topic_list.txt); do
  echo "===== $t"; timeout 12 ros2 topic hz -w 50 "$t" 2>&1 | tail -4
done > hz_oa_on.txt

#    ... operator turns built-in obstacle avoidance OFF on the VENDOR handheld
#        or the vendor app.  This is a vendor-stack setting changed by hand.
#        Parcel publishes nothing.  Dog stays seated.  Second keeps stop #2.
for t in $(cat topic_list.txt); do
  echo "===== $t"; timeout 12 ros2 topic hz -w 50 "$t" 2>&1 | tail -4
done > hz_oa_off.txt
diff <(grep '=====' hz_oa_on.txt) <(grep '=====' hz_oa_off.txt) ; echo "topics identical: $?"

# (e) one raw message from every cloud topic, and its fields[]
for t in $(grep -iE 'cloud|points|scan' topic_list.txt); do
  f=$(echo "$t" | tr '/' '_'); echo "== $t";
  timeout 20 ros2 topic echo --once --full-length "$t" > "raw${f}.yaml" 2>&1
done
grep -H -A40 '^fields:' raw_*.yaml > pointcloud_fields.txt

# (f) the electronic answer to L1-vs-L2, plus packet loss and firmware strings
timeout 15 ros2 topic echo --once /utlidar/lidar_state | tee lidar_state.yaml
```

**RECORD.**

```text
topic count ......................................... ______
topics present that the matrix does NOT list ........ ______________________
matrix rows with NO topic at all .................... ______________________
publishers-but-zero-rate (the service-gated question):
   sportmodestate ______  utlidar/robot_pose ______
   utlidar/voxel_map_compressed ______  utlidar/robot_odom ______
obstacle avoidance ON  → which of those four publish? ______________________
obstacle avoidance OFF → which of those four publish? ______________________
  ⇒ vendor SLAM and our SLAM mutually exclusive?  YES / NO / INCONCLUSIVE
per-point time field present in utlidar/cloud? name/type/offset: ____________
per-point time field present in the L2 cloud?   name/type/offset: ____________
built-in LiDAR: model ______ firmware ______ serial ______ (from lidar_state)
   agrees with the sticker photo P02?  YES / NO      packet loss: ______
frontvideostream: which of video720p/360p/180p is populated? ______________
idl_dump.txt sha256 ................................. ______________________
FIRST ARTIFACT copied off the Orin at ______ UTC to ____________  [ ]
```

**DONE-WHEN.** `topic_list.txt`, `topic_info.txt`, `idl_dump.txt`,
`hz_oa_on.txt`, `hz_oa_off.txt`, `pointcloud_fields.txt`, `lidar_state.yaml`
exist, are non-empty, and **a copy is already off the Orin**.

**BRANCH.** *Zero topics visible* → this is the classic wrong-NIC/DDS binding
failure; go to [TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md) N6 (interface names,
`CYCLONEDDS_URI`, the tcpdump negative control) **before** suspecting the robot.
*Topics visible but a matrix row missing* → record `ABSENT` and carry on; unknown
is absent, and a missing row is a finding, not a blocker. *Obstacle avoidance
cannot be toggled* → record `NOT TOGGLED — <reason>`, run the ON sweep only, and
write that matrix open question 1 stays open.

---

### T1 · FIRST BAG — tier-1 DDS only, no payload · 10 min (5 min recorded) · ✔

**WHY.** Three things at once, all cheap:

1. **A real bag exists inside the first hour.** If the day collapses at 11:00,
   the session still produced a readable dataset with real robot data in it.
2. **It proves the recorder path on real messages**, not on last night's
   synthetic publishers ([TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md) N4). Real
   drivers have different QoS, burstiness and CPU cost.
3. **It is the only unoccluded view the built-in LiDAR will ever give us.**
   After T2 our own bracket, Orin and L2 are in its field of view forever. T1 is
   the reference against which self-occlusion (geometry sheet §4A) is measured.

**WHEN.** Immediately after T0, dog still seated and bare.

**CHANNELS.** Tier-1 DDS only — `lowstate`, `sportmodestate`, `utlidar/cloud`,
`utlidar/imu`, `utlidar/lidar_state`, `wirelesscontroller`, plus the two
`/events/` channels. ≈**1.51 MiB/s** (derived from
[`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md) §2 per-channel rows) → **5 min
≈ 0.44 GiB.**

**DO** — the exact command line that survived last night's N4, changing only
`-o` and the topic list:

```bash
ros2 bag record -s mcap \
  --storage-config-file ~/tonight_mcap.yaml \
  --max-bag-size 0 --max-cache-size 536870912 --disable-keyboard-controls \
  --custom-data take=T1 run_id=$RUN_ID purpose="tier-1 DDS, no payload, pre-mount reference" \
  -o /data/$RUN_ID/T01_dds_tier1 \
  /lowstate /sportmodestate /utlidar/cloud /utlidar/imu /utlidar/lidar_state \
  /wirelesscontroller /events/write_split /events/messages_lost
#  ... 5 minutes ... Ctrl-C
ros2 bag info /data/$RUN_ID/T01_dds_tier1
```

**This command line is the template for every recorded take below** — change
`-o`, `--custom-data take=`/`purpose=`, and the topic list; change nothing else.
Two substitutions, decided once and written into run sheet §3:

```text
--custom-data present on this distro?   YES / NO → use a TAKE.txt in the bag dir
--storage-config-file verified applied? YES / NO → use --storage-preset-profile zstd_fast
```

Then the attestation/sidecar step from run sheet §3 command rows T1/T5, and
**verify the sidecar now** — not at 18:00.

**RECORD.**

```text
per-topic counts vs expected rate × 300 s:
  lowstate ______ / ~150000   utlidar/cloud ______ / ~3000
  utlidar/imu ______ / ~60000  sportmodestate ______ / ~15000
splits (expected 0) ______   /events/messages_lost count ______
bag size ______ GiB   sidecar verify: PASS / FAIL   mcap_sha256 ______
plausibility gate (PS-J) verdict per IMU channel ..... ______________________
```

**DONE-WHEN.** One `.mcap`, zero splits, sidecar verifies, and the IMU
plausibility gate has an explicit verdict for `lowstate.imu_state` **and**
`utlidar/imu`.

**BRANCH.** *Splits > 0* → stop and fix before any core take;
**[REPO]** [TONIGHT_CHECKLIST.md](TONIGHT_CHECKLIST.md) N4e names splitting as
the documented loss path. *`utlidar/imu` fails plausibility* (the 1e24 m/s²
report reproduced) → record it, keep recording the channel, and write into
`does_not_prove` that no claim may rest on that IMU.

---

### T2 · MOUNT, MEASURE, GATE, PHOTOGRAPH · ~60 min · one short recorded segment

**WHY.** Three quantities that stop existing at three different moments, and all
three moments are inside this one hour: the **extrinsic** dies when the bracket
is unbolted, the **chance to re-aim for LiDAR overlap** dies at final torque, and
the **chance to meet the drop deliberately** dies the first time the payload is
on a standing dog. Three sub-takes, in this order. **T2b is the one that becomes
unfixable at torque.**

**T2a — mount and measure.** [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)
§§2–5 and §7, with the dog **powered off** ([SAFETY_BRIEF.md](SAFETY_BRIEF.md)
H11), on blocks or a bench. Photographs P06–P10, P16a/b.

**T2b — ⛔ PRE-TORQUE FOV GATE.** [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)
**§4A**, added by this card. *Before final bracket torque*: dog facing a large
planar wall, **both** LiDAR clouds live in RViz2, confirm a substantial shared
region, and check that our own payload has not put a new shadow into the built-in
LiDAR's view. **[EXT]** no post-hoc LiDAR-to-LiDAR calibration tool — Multi-LiCa,
`ros2_calib`, `mlcc` — can recover an extrinsic between two units that never share
a view, and a chin-mounted built-in plus a back-mounted L2 may barely overlap. If
this is wrong, it is wrong forever from the moment the bolts are torqued.

**T2c — pre-stand gate and the deliberate standing-stop drop test · recorded.**
Run sheet §8 (all S rows) then §9 (E1′/E2′/E3′). **Record this.** The stop press
is timestamped on `wirelesscontroller`, the response on `lowstate` and
`sportmodestate`, and the interval is recoverable from the bag **only if the
recorder was running** (run sheet §5). Two minutes of full-profile recording
≈ **9.9 GiB**.

> **Ordering, and it is the whole point:** the dog **drops** when stopped while
> standing, payload first, from ≈0.3 m ([SAFETY_BRIEF.md](SAFETY_BRIEF.md) H5).
> That drop happens **here, once, deliberately, over the mat, with everyone
> expecting it** — not at T10 when nobody is thinking about it. **No take that
> puts the payload on a standing dog (T4's standing segments, T5, T10, T13) may
> run before T2c passes.**

**RECORD.**

```text
T2a  M1 complete, geometry sheet signed ......... ______ UTC
T2b  shared-region verdict (geometry §4A) ....... CONFIRMED / MARGINAL / NONE
     self-occlusion of the built-in LiDAR by our payload:  NONE / ______
     RViz2 screen photographed ................... YES / NO
     final torque applied at ..................... ______ UTC
T2c  bag path ______  E1′ ______  E2′ ______  E3′ ______
     payload damage from the drop test ........... NONE / ______________
```

**BRANCH.** *T2b finds no shared region* → **loosen and re-aim before torque.**
If no achievable bracket position gives overlap, record `NONE`, torque, and write
in the run header's `does_not_prove`: *"the two LiDARs never shared a view; the
L2↔built-in extrinsic is tape-only and no LiDAR-to-LiDAR calibration is
possible from this session's bags."* *Any S row fails* → the dog does not stand;
run the whole core seated and mark T4's and T5's standing segments
`NOT MEASURED — dog not stood`.

---

### T3 · ⛔ CORE — SYNC-OPEN · 5 min · ✔ all channels

**WHY.** **[EXT]** `../RISK_ASSESSMENT.md:81-102`. The dog has **no clock
protocol**: no queryable device clock, no round-trip primitive, and its 500 Hz
IMU channel has **no timestamp field at all**. `ClockMapV1`'s sample type cannot
even be populated for it. So the offset between the dog's clock, the D455's, the
L2's and the Orin's is recovered **one way only** — by making one physical event
appear in several sensors at once and finding it in each stream afterwards.
**Ten seconds of ritual buys the entire session's cross-device timing. Skipping
it cannot be undone by anything.**

**The five events, and what each one bridges.** This is why all five are needed:
no single event touches every device.

| Event | dog IMU (`lowstate`) | built-in LiDAR | L2 | D455 colour/IR | D455 IMU | `wireless_remote` |
|---|---|---|---|---|---|---|
| controller button, **pressed at the instant of each tap** | — | — | — | — | — | ✔ (+`wirelesscontroller`) |
| still–twist–still, 3 axes | ✔ | ✔ IMU + cloud | ✔ IMU + cloud | ✔ (scene moves) | ✔ | — |
| 3 sharp taps on the payload | ✔ | ✔ IMU | ✔ IMU | — | ✔ | ✔ via the button |
| 5 torch flashes, uneven intervals | — | — | — | ✔ colour **and** IR | — | — |
| board wave through the shared FOV | — | ✔ cloud | ✔ cloud | ✔ image | — | — |

> **The button is only useful if it is simultaneous with something physical.**
> Hold the handheld in the hand that taps and press the button **at each tap**.
> That single trick is what ties the 500 Hz `wireless_remote[40]` track — a
> gap-free copy of the controller, **[EXT]** `../CHANNEL_MATRIX.md` Table B F5 —
> to every IMU in the rig.

**WHEN.** Immediately after T2c. The rig is bolted, torqued, measured,
photographed and powered.

**CHANNELS.** **All 28.** Frozen profile. 5 min ≈ **24.8 GiB**.

**DO.** Start recording, then, with ≥3 s of stillness between events so they are
separable:

1. **0:00–0:30** — quiet head. Nobody touches anything. (This doubles as a short
   static segment, useful if T5 is later cut.)
2. **0:30** — **controller button** ×3, ~2 s apart, *each press synchronised
   with a tap* (step 4). Use a button with **no motion binding** — verify what it
   does before you press it. **Never a stick.**
3. **0:45** — **still–twist–still**, ~10 s: hold still 3 s · rotate about the
   nose axis (roll) · about the pitch axis · about the yaw axis · hold still 3 s.
   Two people lift the rig; announce first; hands out of the leg envelope; over
   the mat. If lifting a powered dog is refused (a legitimate call), **tilt it in
   place** on the mat instead and **record which variant you used** — T14 must
   repeat the same one.
4. **1:15** — **3 sharp taps** on a **rigid part of the payload deck or
   bracket** — never a sensor housing, never a lens — ~2 s apart, controller
   button pressed at each tap.
5. **1:45** — **5 torch flashes** into the D455 at intervals of **1 s, 2 s, 1 s,
   3 s**. The pattern is uneven on purpose: an even pattern can be aligned one
   period out and nobody would know. Do the whole pattern with a **white** torch,
   then the whole pattern again with an **850 nm** source. Not into anyone's eyes.
6. **2:30** — **board wave**: pass a rigid flat board (the calibration target, or
   a card with the `run_id`) slowly across the shared field of view, twice.
7. **3:00–5:00** — quiet tail. Stop recording.

**RECORD** — wall times matter more than tidiness. **Write them as you go.**

```text
bag path ____________________________  recorder started ______ UTC
button presses (UTC) ...... 1 ______  2 ______  3 ______
twist variant ............. LIFTED / TILTED-IN-PLACE     start ______ end ______
taps (UTC) ................ 1 ______  2 ______  3 ______   surface tapped: ______
torch white  first flash ______   pattern used: 1/2/1/3 s   as scripted? Y/N
torch 850 nm first flash ______   source (make/model): ______________________
                                  850 nm source ABSENT?  YES / NO
board wave pass 1 ______  pass 2 ______   board: ______________________
performed by: ____________  witnessed by: ____________
ANYTHING done differently from this script (T14 must copy it exactly):
  ______________________________________________________________________
```

**DONE-WHEN.** One bag, all five events inside it, wall times written, and the
deviations box filled — even if it says "none".

**BRANCH.** *An event cannot be performed* → do the other four and **write down
which one was omitted**, because an omitted event is an **unbridged device
pair**, and a reader six months from now needs to know which pair. *No 850 nm
source* → white only, and record that the IR-stream cross-check is absent.
*The recorder was not running* → **the take did not happen. Do it again.**

---

### T4 · ⛔ CORE — FOOT-FORCE ZERO-OFFSET · 5 min · ✔ all channels

**WHY.** **[EXT]** `../CHANNEL_MATRIX.md` Table B F7: there are **two** arrays,
`foot_force[4]` and `foot_force_est[4]`, both **`int16` raw counts** from an
air-pressure contact proxy with **no published units, no gain, no offset**.
Without a zero and at least one known load, every foot-force number this robot
ever emits is uninterpretable — and the zero can only be taken with the feet
genuinely unloaded, which means *today, on this rig, with this payload mass*.
Recording the two arrays side by side is also free evidence about which one is
sensed and which is derived.

**WHEN.** Straight after T3. Requires T2c passed for the standing segments.

**CHANNELS.** All 28 (`lowstate` is the one that matters). 5 min ≈ **24.8 GiB**.

**DO** — one continuous bag, five segments, announce each aloud so the scribe can
timestamp it:

| Seg | Duration | State | What it gives |
|---|---|---|---|
| **A** | 60 s | **Lying / on blocks, all four feet genuinely unloaded** — hanging free is better than lying | the **zero** |
| **B** | 60 s | **Standing, planted, still**, nobody touching | the robot's own weight through four feet |
| **C** | ≥20 s | A **known mass** placed on the trunk, centred, held still | a second point ⇒ a crude counts-per-kg scale |
| **D** | ≥20 s | Mass removed, standing again | repeatability of the zero, and hysteresis |
| **E** | 60 s | Lying again; **press each foot by hand in a named order**, 5 s each, 5 s gaps | **which array index is which physical foot** — undocumented, and unrecoverable later |

Segment E is the cheapest thing on this sheet and it answers a question nobody
can answer from a bag alone.

**RECORD.**

```text
bag path ____________________  A start ______  B ______  C ______  D ______  E ______
known mass used: ______ g (± ____ g)  scale used: ____________  placed: ____________
foot press order in E:  1 ______  2 ______  3 ______  4 ______   (name the feet)
observed foot_force at rest (if visible live): ____________________
both foot_force AND foot_force_est recorded?  YES / NO
payload mass on the dog during this take: ______ g  (= geometry sheet §7 total)
```

**DONE-WHEN.** Five segments in one bag with written boundary times, the known
mass written in grams, and the foot-press order named.

**BRANCH.** *The dog will not lie down / cannot be blocked up* → do B–E and mark
segment A `NOT MEASURED — no unloaded state achievable`, which means the zero is
**absent** and the scale is one-point. Say so; do not substitute the minimum
observed value for a zero. *No mass and no scale on hand* → C/D become
`NOT MEASURED`; the zero (A) is still the valuable half and it still happens.

---

### T5 · ⛔ CORE — STATIC · 15 min · ✔ all channels

**WHY.** IMU bias, noise floor, per-channel rate stability, and the **thermal
baseline** are all defined by a long quiet interval, and every uncertainty number
this dataset will ever carry is measured against this one. It is also where
**[EXT]** the `utlidar/imu` 1e24 m/s² pathology either reproduces on our unit or
does not — a receipt-count probe would call that channel healthy; PS-J's
plausibility gate (\|accel\| = 9.80665 ± 1.0 m/s², \|gyro\| < 0.05 rad/s at rest)
is what catches it.

**WHEN.** Straight after T4, before anything free-form.

**CHANNELS.** All 28, frozen profile. 15 min ≈ **74.4 GiB.**

**DO.**

1. Dog **standing, planted, still** (seated is the degraded variant — say which).
2. **Nobody touches the dog, and nobody walks near it.** Footfall on a wooden
   floor is visible in a 500 Hz IMU. Stand outside the 1.5 m radius.
3. Doors closed; note HVAC/fan state and room temperature.
4. Let it run **15 uninterrupted minutes**, `tegrastats` logging throughout.
5. Use the time to fill the take log and the geometry sheet — do not use it to
   fiddle with the rig.

**RECORD.**

```text
bag path ____________________  start ______ UTC  end ______ UTC
posture: STANDING / SEATED (degraded)      anyone touch it? NO / ______
room temp ______ °C   HVAC ______   floor type ____________
tegrastats: start temps ____________  end temps ____________  throttled? Y/N
per-IMU at rest — |accel| m/s², |gyro| rad/s (fill from the plausibility gate):
   lowstate.imu_state ............ |a| ______  |g| ______  verdict ______
   utlidar/imu ................... |a| ______  |g| ______  verdict ______
   l2.imu ........................ |a| ______  |g| ______  verdict ______
   d455 accel/gyro ............... |a| ______  |g| ______  verdict ______
observed vs nominal rate, worst channel: ____________ ______ %
```

**DONE-WHEN.** 15 minutes, uninterrupted, with a plausibility verdict written
for **every** IMU.

**BRANCH.** *Interrupted* (someone bumped it, a cable moved) → note the time and
**keep going**; a marked disturbance is usable, an unmarked one is poison.
*Thermal throttle appears* → that is a **result**, not a failure: record it, and
carry it into the session-length answer nobody has yet.

---

### T6 · EXCITATION — hand-carried, 3-axis, non-constant rate · 15 min · ✔

**WHY.** The LiDAR↔IMU **extrinsic and time offset** are only observable under
excitation. Two specific properties are required and both are easy to get wrong:

- **Non-constant rate.** A smooth constant-rate rotation makes the time offset
  **unobservable** — it looks identical shifted in time. Vary the rate
  deliberately: jerky, uneven, changing direction.
- **Geometric constraint in ≥3 directions.** Walls/floor visible in at least
  three non-parallel directions, or the LiDAR's own pose is underdetermined and
  the fit runs on nothing.

And **start from >5 s of complete rest**, which is what the initialisers use to
estimate the gravity direction and the gyro bias before anything moves.

**WHEN.** After the core. Two people, dog powered and damped, announced, over the
mat, hands out of the leg envelope.

**CHANNELS.** All 28. **3 bags × 90 s ≈ 4.5 min ≈ 22.3 GiB.**

**DO**, per bag: start recording · **stand completely still ≥10 s** · then ~60 s
of hand-carried motion: rotate about all three axes at *varying* speed, with
translation as well as rotation (accelerometer excitation is what fixes scale) ·
finish with ≥5 s still · stop. Do it in a room with structure on at least three
sides. Three bags, so one bad one is not the whole take.

**RECORD.**

```text
bag paths ______________________________________________________
rest at start ≥10 s in each?  Y/N     rest at end?  Y/N
rate varied (not a smooth sweep)?  Y/N    axes covered: X ___ Y ___ Z ___
structure visible in ≥3 directions?  Y/N   room: ____________
carried by ____________ + ____________
```

**BRANCH.** *Carrying a powered dog is refused* → tilt/rock it in place through
all three axes with the feet planted, record `IN-PLACE`, and note that
translational excitation is absent, which weakens the scale observability.

---

### T7 · VISUAL–LiDAR CALIBRATION — 5–10 **separate** short bags · 20 min · ✔

**WHY.** The camera↔LiDAR extrinsic is rig-specific and dies with the bracket.
`direct_visual_lidar_calibration` and its relatives take **a set of bags, each a
static viewpoint**, not one long moving bag — that is why these are separate
files and why each one **starts at rest**.

**WHEN.** After T6. Hand-carried or on the dog, seated/standing.

**CHANNELS.** All 28. **5–10 bags × ~30 s ≈ 4 min recorded ≈ 19.8 GiB.**

**DO.** Pick a scene that is **both** geometry-rich (edges, corners, depth
variation) **and** texture-rich (posters, shelves, patterned surfaces — a bare
white wall gives the camera nothing). For each bag: place the rig, **hold it
still ≥10 s**, record 20–30 s, stop, **move to a new viewpoint** differing by
roughly 30–60° or a metre of translation, repeat. **5 minimum, 10 better.**

**RECORD.**

```text
bag paths (one per viewpoint) ______________________________________
count ______   scene described: ______________________________________
each bag static throughout?  Y/N     viewpoints spread ≥30°?  Y/N
lighting: ____________  (note it: a calibration shot in the dark is a wasted bag)
```

**BRANCH.** *Fewer than 5 usable* → record how many; below 5 the fit is
under-constrained and the extrinsic stays tape-only.

---

### T8 · PLANAR STRUCTURE, BOTH LiDARs, FULLY STATIC · 12 min · ✔

**WHY.** The LiDAR↔LiDAR extrinsic — the session's **cross-validation asset**,
two independent range sensors at a known relative pose. Plane-based tools
(Multi-LiCa, `mlcc`) need static scans and *shared* structure.

> **One wall is not enough, and this is the trap.** A single plane leaves **three
> degrees of freedom unobservable**: translation *within* the plane and rotation
> *about its normal* are invisible to a single-plane fit. Get a **corner** — two
> non-parallel walls plus the floor — in the shared view of **both** LiDARs for at
> least one capture. The card that scripted this asked for a large planar wall;
> the wall is necessary and it is **not sufficient**.

**WHEN.** After T7, before the rig is disturbed.

**CHANNELS.** All 28 (the two clouds are what matter). **3–5 × 45 s ≈ 3 min ≈
14.9 GiB.**

**DO.** 3–5 captures, each **fully static** (nothing moves, nobody walks
through), each 30–60 s:

1. Large flat wall at ~2–3 m, filling as much of the **shared** region as possible.
2. Same wall, rig rotated ~30–45° about the vertical.
3. **A corner**: two non-parallel walls + floor, all in the shared region.
4. Optional: a cluttered scene with depth variation, as a robustness case.

**RECORD.**

```text
bag paths ______________________________________________________
capture 1 wall size ______ m × ______ m at ______ m
capture 3 corner: two walls + floor shared by BOTH LiDARs?  Y/N
≥3 non-parallel planes present across the set?  Y/N   ⇒ if N, 3 DOF unobservable
anyone walk through frame?  NO / which capture ______
```

**BRANCH.** *The two clouds do not overlap enough* → this is geometry sheet §4A's
verdict arriving late and it is **already too late to fix**; record it and write
the consequence into `does_not_prove`.

---

### T9 · APRILGRID, 6-DOF, LOCKED SHORT EXPOSURE — twice · 20 min · ✔

**WHY.** Intrinsics **are** recalibrable later from a target, so this is the
*least* irreversible calibration take. Two things inside it are **not**: the
**camera↔IMU extrinsic** and the **camera↔IMU time offset**, which are properties
of *this rig assembled this way* and die with the bracket.

Three requirements that quietly ruin the take if missed:

- **Locked exposure, gain and white balance.** Auto-exposure changes the
  effective capture instant frame to frame and corrupts exactly the timing the
  calibration is solving for.
- **Short exposure.** Blur destroys corner localisation, and the calibration will
  happily report a confident wrong answer.
- **Repeat with the D455 IR projector OFF.** The projector's dot pattern is
  overlaid on the IR images and breaks target detection in the IR streams — the
  streams that see the target best in poor light.

**WHEN.** After T8.

**CHANNELS.** All 28, **frozen profile** (see §0 — intrinsics belong to the
profile). **2 runs × ~4 min ≈ 8 min ≈ 39.7 GiB.**

**DO.**

1. **Measure a tag with callipers and write the number down** — tag size in mm is
   a required calibration input, and a printed target that gets thrown away takes
   the scale with it. Photograph the target flat, with a rule in frame.
2. Lock exposure/gain/WB. Record the values.
3. Move slowly through **all six degrees of freedom** — left/right, up/down,
   near/far, roll, pitch, yaw — keeping the **whole grid in frame** and covering
   the **image corners** (lens distortion lives there). Vary the distance.
4. Repeat the entire run with the **IR projector off**.

**RECORD.**

```text
bag paths: projector ON ____________  projector OFF ____________
target type: AprilGrid / checkerboard / other ____________
tag size measured ______ mm ± ____   rows × cols ______   photographed? Y/N
exposure locked at ______ ms   gain ______   WB ______
resolution/fps at which this was shot: ______ × ______ @ ______ Hz
corners of the image covered?  Y/N     grid ever clipped?  Y/N
```

**BRANCH.** *No target on hand* → **say so plainly**; intrinsics fall back to the
factory values from `rs-enumerate-devices` (record them), and the camera↔IMU
extrinsic + time offset become **unrecoverable for this rig**. That is a real
loss and it should be written in `does_not_prove`, not glossed.

---

### T10 · WALK TAKE — loops, taped mark, taped 10 m baseline · 25 min · ✔

> ### ⛔ AUTHORISATION GATE — this take is outside the pack's envelope
>
> [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §8 and
> [SAFETY_BRIEF.md](SAFETY_BRIEF.md) §2 authorise **stand and sit under the
> vendor handheld, feet stationary — no gait, no locomotion.** T10 is
> locomotion. **This sheet does not grant it and cannot.** It runs only if the
> **owner** extends the envelope in writing, on the day, with the extension
> recorded below. Otherwise run **T10-ALT**.
>
> ```text
> owner extension granted?  NO → run T10-ALT
>                           YES → by ____________ at ______ UTC
>                           scope, verbatim: ______________________________
> ```
>
> **T10-ALT — hand-carried, and it keeps most of the value.** Two people carry
> the rig along the same taped route, the same loops, the same 10 m baseline,
> with the same button presses. You get loop closure, return-to-mark drift and
> the scale check. You do **not** get gait dynamics, foot-force under load, or
> the vibration spectrum of walking. Record which variant ran.

**WHY.** Three measurements that need a *route*, not a viewpoint:

- **Loop closure** — the only way to evaluate any SLAM candidate on drift.
- **Return-to-mark ground truth** — come back to a **taped** start mark and
  measure the physical offset with a tape. That number is ground truth, it costs
  a strip of masking tape, and it cannot be reconstructed later from anything.
- **A taped 10 m baseline** walked out and back — an absolute **scale** check for
  every odometry candidate.

**WHEN.** After the calibration takes, so the extrinsics apply to it.

**CHANNELS.** All 28. **~12 min ≈ 59.5 GiB.**

**DO.**

1. Tape a **start mark** on the floor: a cross for position **and** a line for
   heading. Photograph it with a rule.
2. Tape a **10 m baseline** (measure it; write the real length, e.g.
   `10.02 ± 0.01 m`).
3. Record. Sit still ≥10 s at the mark. **Press the controller button** — that
   press is the loop-point annotation, gap-free at 500 Hz in
   `wireless_remote[40]`.
4. Walk (or carry) a closed loop through a **geometry-rich** room; return to the
   mark; **press the button again**. **At least two loops.**
5. Then the baseline: from one end to the other and back, **button press at each
   end**, four presses total.
6. Stop at the mark, sit still ≥10 s, stop recording.
7. **Measure the final offset from the mark with the tape** — Δx, Δy, Δyaw —
   before anything moves.

**RECORD.**

```text
variant: T10 (owner-extended locomotion) / T10-ALT (hand-carried)
bag path ____________________   loops completed ______
button presses (UTC): loop ends ______________  baseline ends ______________
taped baseline true length ______ m ± ______
final offset from the start mark:  Δx ______ mm  Δy ______ mm  Δyaw ______ °
route described: ______________________________________________
anything unexpected (slip, snag, stop call): ______________________
```

**BRANCH.** *Any stop call* → the drop is over the mat, the take ends, and the
time goes in run sheet §10. Restart as a new take with a new row.

---

### T11 · POWER-CYCLE POSE-ORIGIN PROBE · 12 min · ✔ ×2

**WHY.** Nobody knows where `SportModeState.position`'s origin is, whether it
resets at boot, or whether it advances without gait. Every consumer of that field
is guessing until this is settled, and it is settled by one power cycle against
one strip of tape. **[EXT]** the field also rides a **service-gated** channel, so
this take doubles as a check that it survives a reboot at all.

**WHEN.** After T10, while the tape mark is still on the floor.

**CHANNELS.** All 28. **2 bags × ~90 s ≈ 3 min ≈ 14.9 GiB.**

**DO.**

1. Park the dog **exactly on the mark**, nose on the heading line.
2. Record 60 s. Note `position` and, if visible, its frame.
3. **Power cycle fully** — off, wait ≥20 s, on. **Do not move the dog.**
4. Record 60 s again from the same physical pose.
5. Then move the dog **by hand** 1.00 m along the taped line and record 30 s —
   does `position` change with no gait at all?

**RECORD.**

```text
bag paths: before ____________  after ____________
position before power cycle:  x ______ y ______ z ______  frame ______
position after  power cycle:  x ______ y ______ z ______
  ⇒ origin RESETS to current pose / PERSISTS / OTHER: ____________
after a hand-move of 1.00 m: Δposition ______ m  ⇒ updates without gait? Y/N
sportmodestate publishing after the power cycle at all?  YES / NO
```

**BRANCH.** *`sportmodestate` silent* → record `ABSENT`, and note that the dog's
**only source-clock anchor** (`stamp`) is absent with it, which makes T3/T14 the
session's sole cross-device timing evidence rather than a cross-check on it.

---

### T12 · DEGENERATE TAKE — the negative control · 8 min · ✔

**WHY.** A dataset of successes cannot tell you what failure looks like. A bare
corridor — long, featureless, geometrically degenerate along its axis — is where
LiDAR odometry is *supposed* to slide. Recording it deliberately means that when
a method fails there later, that is a **known-correct result**, and when it
succeeds, that is informative. **[EXT]** it also characterises how the vendor
odometry behaves when starved, which no amount of good data reveals.

**WHEN.** Late. It is cheap and it is not a prerequisite for anything.

**CHANNELS.** All 28. **~3 min ≈ 14.9 GiB.**

**DO.** Traverse a long bare corridor (or face a large blank wall and translate
along it), ideally the most featureless space in the building. Same variant rule
as T10 — carried unless the owner extended the envelope. Note what makes it
degenerate.

**RECORD.**

```text
bag path ____________________  variant: WALKED / CARRIED
space described (length, width, featurelessness): ____________________
degeneracy direction (along the corridor axis?): ____________________
```

---

### T13 · EXPOSURE-CAPPED TAKE, ≤5 ms · 10 min · ✔

**WHY.** Indoors at 30 fps, auto-exposure will happily choose 20–30 ms. On a
walking quadruped the resulting motion blur is **locked to the gait cycle** — it
is *systematic*, correlated with the trot frequency, and it biases every
feature-based method in a way that looks like sensor noise and is not. Capping
exposure at **≤5 ms** costs brightness and buys a take whose blur is not a
function of the legs.

**WHEN.** After T10, same route.

**CHANNELS.** All 28, **frozen profile** (T9's intrinsics must still apply).
**~4 min ≈ 19.8 GiB.**

**DO.** Lock exposure ≤5 ms; raise gain and/or add lighting to compensate;
re-walk (or re-carry) the T10 route, including one loop back to the mark. Record
the actual exposure applied — some drivers silently clamp a requested value.

**RECORD.**

```text
bag path ____________  requested exposure ______ ms  APPLIED exposure ______ ms
gain ______  extra lighting used: ____________  images usable/too dark? ______
same route as T10?  Y/N     variant: WALKED / CARRIED
```

**BRANCH.** *Too dark to be usable at 5 ms* → keep the bag anyway (a dark bag
with known exposure is still a controlled sample), and record the brightest
setting that stayed under 10 ms as a second attempt.

---

### T14 · ⛔ CORE — SYNC-CLOSE · 5 min · ✔ all channels · **the last action on the powered rig**

**WHY.** T3 gives an **offset**. T3 and T14 together give an offset **and a drift
rate**, plus a residual that says whether the linear model held over the day. The
clocks in this rig are free-running and unsynchronised — **[REPO]** there is no
`chrony`/`ntp`/`ptp`/`phc2sys` anywhere in the repository (run sheet §7 C0.2
records the grep and its single substring false positive). A drift of tens of
ppm over six hours is tens of milliseconds, which is several LiDAR sweeps and
many IMU samples.

**WHEN.** **Last.** On the **still-bolted, still-powered** rig, before the M2
re-measure, before a single bolt is loosened, before power-down. If the day is
collapsing, T14 comes **before** whatever else is left.

**CHANNELS.** All 28, same frozen profile as T3. 5 min ≈ **24.8 GiB.**

**DO.** **Repeat T3 verbatim.** Same operator if possible, same order, same
intervals, same button, same torch, same board, same twist variant. Read T3's
"anything done differently" box and copy that too. The value is in the events
being *the same events*.

**RECORD.**

```text
bag path ____________________  recorder started ______ UTC
elapsed T3 → T14: ______ h ______ min      ⇐ THIS IS THE DRIFT BASELINE
same operator as T3?  Y/N    same twist variant?  Y/N    same torch?  Y/N
button presses (UTC) ...... 1 ______  2 ______  3 ______
taps (UTC) ................ 1 ______  2 ______  3 ______
torch white first flash ______   torch 850 nm first flash ______
board wave pass 1 ______  pass 2 ______
deviations from T3 (each one weakens the pairing): ____________________
```

**DONE-WHEN.** The bag exists **and** the elapsed time from T3 is written down.

**BRANCH.** *A device died mid-day* → still do T14 with what is alive; a
bracketed pair for three devices beats a single ended pair for four. *T3 never
happened* → T14 is then a single unbracketed ritual: still do it, and record that
there is **no drift slope, only an end-of-day offset**.

---

### T15 · TEARDOWN · 25 min · not recorded

**WHY.** A bracket that shifted during the day silently invalidates every
extrinsic in every bag, and the **only** way to find out is to measure the same
quantities again *while the rig is still assembled*. Once a bolt is loosened the
question is unanswerable forever — and so is the answer to "did the extrinsic we
recorded this morning still hold this afternoon?".

**M2 before a single bolt is loosened.** [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)
§9 and run sheet §11 own this; it is listed here only so the take order is
complete and nobody powers down before T14. Photographs P17 (M2 in progress, then
the bracket and its contact faces after removal — witness marks are the evidence
of a shift). Then the offload: bag + sidecar + clockmap + attestation + T0
artifacts to a **second physical device**, digests compared both sides.

```text
T14 completed BEFORE power-down? ................. YES / NO   (NO ⇒ say so loudly)
M2 completed BEFORE loosening? ................... YES / NO
offload complete, digests match? ................. YES / NO
```

---

### T16 · OVERNIGHT STATIC IMU, ≥3 h — Allan variance · ✔ IMU subset only

**WHY.** An Allan-variance IMU noise model (angle/velocity random walk, bias
instability) needs **hours** of undisturbed static data, and it is what turns
"the IMU is noisy" into numbers a filter can actually use. It is also the **only
take on this sheet a later session could redo**, because it depends on the
sensors, not on the rig geometry — which is why it is last in every priority
list here.

> **⚠ Safety conflict, resolved fail-closed.** [SAFETY_BRIEF.md](SAFETY_BRIEF.md)
> §3 **H7**: *"Do not charge unattended."* An overnight take on the charger
> violates that. So:
>
> | Variant | What runs | Charging? | Default |
> |---|---|---|---|
> | **T16a** | **Dog OFF.** D455 + L2 IMUs only, payload powered from mains, on a solid bench (not the dog) | no LiPo charging | ✔ **default** |
> | T16b | Dog powered, body IMU included, **on battery, attended**, for as long as the battery lasts | no | only with a person present |
> | T16c | Dog on charger overnight | **yes — violates H7** | **only with explicit owner sign-off recorded below** |
>
> ```text
> variant run: T16a / T16b / T16c    if T16c, owner sign-off: ____________ at ______
> ```

**CHANNELS.** IMU subset only. **T16a ≈ 0.29 MiB/s → 3 h ≈ 3.1 GiB.** T16b adds
`lowstate` + `utlidar/imu` ≈ **1.07 MiB/s → 3 h ≈ 11.3 GiB.** (Derived from
[`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md) §2.)

**DO.** Rigid, level, isolated surface. Nothing touching it. Doors closed, no
foot traffic, HVAC noted (thermal drift shows up in Allan plots and it is not the
IMU's fault). Start the take, write the start time, leave. ≥3 h; longer is
strictly better.

**RECORD.**

```text
bag path ____________  start ______ UTC  end ______ UTC  duration ______ h
surface ____________  room temp start ______ °C end ______ °C
disturbances (anything at all): ____________________________________
```

---

## 5 · ⛔ IF THE DAY IS CUT SHORT — the truncation ladder

**Read this at 09:00, not at noon.** The takes are already ordered by
irreversibility, so "cut short" mostly means "stop starting new things and finish
the core". But the priority is explicit, because at noon nobody reasons well.

### The noon rule

> **At 12:00, if T3, T4 and T5 are not all complete: stop whatever is running and
> run them now, in that order.** They are 25 minutes together. Then T14 whenever
> the day actually ends.

### What must already exist, in priority order

| Rank | Must exist | Why it outranks the next one |
|---|---|---|
| **1** | **T2a — geometry M1** + photographs **P02, P06–P10, P16a/b** | Gone the instant the bracket is unbolted. Also the whole of branch **DEGRADE-MMP**, which the run sheet already calls a *legitimate outcome*. |
| **2** | **T2b — the pre-torque FOV check** | Unfixable after torque; no tool recovers an extrinsic between LiDARs that never shared a view. |
| **3** | **T3 SYNC-OPEN** | Without it **no** bag in the session has recoverable cross-device time. It contaminates every other take retroactively. |
| **4** | **T14 SYNC-CLOSE** | Cheap (5 min) and it upgrades T3 from an offset to an offset **plus drift**. Do it even if the gap is only two hours. |
| **5** | **T4 FOOT-FORCE ZERO-OFFSET** | 5 minutes; without it a whole sensor modality is permanently uninterpretable. |
| **6** | **T5 STATIC** — full 15 min, or a degraded 5 min, or seated | Every uncertainty number the dataset can carry. A short static beats none by a lot. |
| **7** | **T0 discovery artifacts** | Cheap, and they are the transcode key for every bag; only obtainable with the dog present and powered. |
| **8** | **T8** then **T7** then **T6** | The rig-specific extrinsics: LiDAR↔LiDAR, camera↔LiDAR, LiDAR↔IMU. All die with the bracket. |
| **9** | **T15 M2 re-measure** before loosening | Without it you cannot know whether the extrinsic held; with it, a shift is at least *known*. |
| 10 | T9 · T10 · T11 · T12 · T13 | Valuable, and each needs its own later session to recover — but they are useless without ranks 1–8 anyway. |
| 11 | T16 | The only take a later session can genuinely redo. |

### The 2-hour minimum viable day

**T2a + T2b + T3 + T4 + T5 + T14 + T15(M2).** ≈2 hours including mounting. That
is a **successful session**: a measured rig, a bracketed clock, an interpretable
foot-force channel, a noise floor, and proof the bracket did not move.

### Three things that must never be skipped, whatever happens

1. **T14 before power-down.** Always. Even at noon. Even if nothing else ran.
2. **M2 before loosening a bolt.** Run sheet §11 stop bar.
3. **The offload to a second device before leaving**, digests compared. A bag
   that exists only on the Orin is one failure away from never having existed.

---

## 6 · Disk and time ledger

At the frozen default profile — **84.60 MiB/s = 297.4 GiB/h = 4.957 GiB per
recorded minute** (**[REPO]** [`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md)
§1, recommended row). Derived here, not measured:

| Take | Recorded min | Rate | Disk (GiB) |
|---|---:|---|---:|
| T1 tier-1 DDS only | 5 | ≈1.51 MiB/s | 0.4 |
| T2c stop test | 2 | full | 9.9 |
| **T3 SYNC-OPEN** | **5** | full | **24.8** |
| **T4 foot-force** | **5** | full | **24.8** |
| **T5 static** | **15** | full | **74.4** |
| T6 excitation | 4.5 | full | 22.3 |
| T7 visual–LiDAR (×5–10) | 4 | full | 19.8 |
| T8 planar (×3–5) | 3 | full | 14.9 |
| T9 AprilGrid (×2) | 8 | full | 39.7 |
| T10 walk | 12 | full | 59.5 |
| T11 power-cycle | 3 | full | 14.9 |
| T12 degenerate | 3 | full | 14.9 |
| T13 exposure-capped | 4 | full | 19.8 |
| **T14 SYNC-CLOSE** | **5** | full | **24.8** |
| T16 overnight (T16a / T16b) | 180 | 0.29 / 1.07 MiB/s | 3.1 / 11.3 |
| **TOTAL** | **≈78 recorded min + 3 h** | | **≈368–376** |

**Free space actually required: ≈425 GiB**, because PS-B's `SpaceBudget` keeps a
**15 % margin** and the recorder **refuses to start** below it (**[REPO]**
[`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md) §1/§3).

**The non-skippable core alone is 30 recorded minutes ≈ 148.7 GiB.**

> **⚠ The arithmetic that decides the profile.** At **256 GiB free** the
> recommended profile buys **≈45 minutes** of recording in total — the core plus
> about fifteen minutes. **Check free space before T3, not before T10.**
>
> Step down the ladder **before** the frozen profile is set, never mid-day
> (§0 profile freeze). **[REPO]** the budget's own preference is to drop
> **resolution before frame rate** — resolution can be downsampled from a bag,
> 15 fps cannot be interpolated back to 30:
>
> | Fallback | GiB/h | Whole script ≈ |
> |---|---:|---:|
> | 640×480@30 C+D+IR | 227.1 | ≈283 GiB |
> | 424×240@30 C+D+IR | 82.5 | ≈103 GiB |
> | 848×480@15 C+D+IR *(last resort — costs frame rate)* | 154.1 | ≈192 GiB |

```text
free space on the record target before T3: ______ GiB   checked at ______ UTC
profile this permits (§6 table): ____________   frozen profile: ____________
```

---

## 7 · What this script does not prove, and does not authorise

- **Nothing on it has been executed.** It is blank paperwork written the day
  before by someone who has never seen this rig. Every take is a plan; filling a
  box is not validation.
- **It authorises nothing.** Safety, envelope, stop bars and branches belong to
  [SAFETY_BRIEF.md](SAFETY_BRIEF.md) and
  [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md), and where this sheet and those
  disagree, **they win**. T10 and T13 explicitly require an owner extension that
  this sheet cannot grant, and T16c requires an owner override of hazard H7.
- **The durations are estimates, and they are optimistic.** They assume nothing
  is being debugged, nobody is looking for a cable, and every command works
  first time. **[EXT]** none of it has been rehearsed against a real Go2.
- **The commands are only half-verified.** The `ros2` **flags** marked
  [MEASURED-JAZZY] were run — in a ROS 2 **Jazzy** sandbox in this repository's
  cache, **not on the Orin and not on Humble**, which is the distro the Orin is
  merely *expected* to carry. Everything else — every **topic name**, the L2's
  transport, the RealSense profile — is [UNVERIFIED-SYNTAX] or [EXT]. The dev box
  has no `rclpy`, no `mcap`, no RealSense and no Jetson. The requirement is the
  *measurement*; the string is a starting point.
- **The disk numbers are derived, not measured.** They come from
  [`../BANDWIDTH_BUDGET.md`](../BANDWIDTH_BUDGET.md)'s model, whose sustained
  write rate was **measured on the dev host only** and explicitly not
  extrapolated to the Orin.
- **A take being recorded proves nothing about the data in it.** A `PRESENT`
  channel means a message arrived. Whether it carries what we believe it carries
  is what T0 exists to start settling, and it will not be finished in one day.
- **This script cannot make a calibration succeed.** It is designed so the
  *inputs* to the standard tools exist and are well-formed. Whether GLIM,
  FAST-LIO2, Multi-LiCa, `ros2_calib` or `direct_visual_lidar_calibration`
  actually converge on these bags is a next-week question, and if they do not,
  the failure may well be in these takes.
- **The sync ritual is a mechanism, not a measurement.** T3/T14 produce *events*.
  Turning them into an offset and a drift rate with an uncertainty is fitting
  work that happens afterwards, against the recorded bags, and it may find that
  the events were not sharp enough. **[EXT]** the ritual is what two published
  quadruped-dataset teams do; it is not something we have ever done.
- **T4 gives a zero and one crude load point.** It is not a calibrated force
  sensor and no claim requiring newtons may cite it.
- **The foot-index mapping (T4 segment E), the pose origin (T11), and the
  per-point time fields (T0) are single-observation findings** on one unit, on
  one firmware, on one day.
