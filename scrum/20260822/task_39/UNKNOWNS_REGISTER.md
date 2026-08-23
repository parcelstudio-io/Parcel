# Unknowns register — Go2 EDU Plus with Mid-360

**Source:** `../WAVE3_HW_DESIGN_FABLE.md` §8, all sixteen rows, carried
verbatim in meaning and extended by card HW-8 with two columns the design
does not have: **resolves on** (the named measurement, ticket question or
bake-off that closes it) and **blocks** (which card cannot close *honestly*
until it is closed). **Nothing in this file is a measurement.** Every row is
open until a result file exists.

**Reading the tags** (the design's citing rule): `[documented]` = a source
URL exists in the design §2/§7; **UNCONFIRMED** = the design's `inferred`,
i.e. a plausible reading of indirect evidence and nothing more. An
UNCONFIRMED row may not be used as a premise by any card.

**Five of sixteen are answerable before delivery** — Q-jp, Q-wire, Q-fwv,
Q-dev, Q-usb — and that is exactly what `SUPPORT_TICKET_UNITREE.md` asks.
The other eleven need the box, a bake-off, or an owner decision.

| Id | Unknown | Resolves on | Blocks | Decider |
|---|---|---|---|---|
| **Q-jp** | JetPack / L4T on the 2026 EDU+ dock; is there a JetPack 6.2.1 BSP for Unitree's custom carrier? | **ticket Q1** (now) → step **B9** on the day. JetPack 5 forks to design §7.2 | **HW-9 entirely** (JetPack 5 stops the day); HW-7 `gate-on-aarch64` (the qemu container is a proxy for a machine we have not read); HW-11 native gateway build | owner |
| **Q-wire** | Mid-360 NIC / subnet / M8 voltage; is `livox_ros_driver2` preinstalled? | **ticket Q2** (now) → step **Q-wire** (`tcpdump -i <nic> udp port 56300`, meter powered-off) | HW-9 (the B-fw static address); **HW-3's live proof** — HW-3 closes on synthesised Livox frames, which proves the decoder, not the wiring | design |
| **Q-fwv** | shipped firmware version; OTA default; the release that fixes CVE-2026-27509 (GHSA still says "Patched Versions: Unknown" [documented]) | **ticket Q3** (now) → step **S20**: the owner reads the version **in the Unitree app** and `orin_rehearsal --until p3_network --firmware-attested V<x.y.z>` records it — **no software in this tree can read it off the robot** (`attest` ships no live identity reader; a DDS identity read is handoff HO-7) + a GHSA watch | HW-12 first armed step (the arming gate cites the record); nothing on the software-now rail — **the firewall, not the pin, is the load-bearing control** | owner (pin), design (firewall stands regardless) |
| **Q-dev** | is DDS "secondary development" exposure on by default on a new EDU+? | **ticket Q4** (now) → step **Q-dev** (`ros2 topic list` on domain 0) | HW-9 — if it is off, *every* topic read in the first two hours returns nothing and looks like broken hardware | — |
| **Q-con** *(added by HW-8)* | how a terminal is reached on the Orin with no LAN joined — the documented dock ports include no HDMI/DP [documented]; direct-Ethernet vs USB-serial console is **UNCONFIRMED** | **ticket Q5** (now) → step **B-con** on the day | **HW-9 entirely** — no command in the first two hours can be typed without it | owner |
| **Q-usb / Q-pwr** | dock USB complement (1 or 2 USB-C? [documented, resellers disagree]); regulated payload power; battery runtime under Orin + Mid-360 + D455 + array | **ticket Q5** (now) → step **Q-usb** (`lsusb -t`) + a 30-min idle / 30-min roam battery log | HW-9 mount sheet (B11); **HW-4** — the array's on-dog session needs a port that is not the D455's | owner (mount sheet) |
| **Q-lidar** | head LiDAR L1 vs L2; `rt/utlidar/*` rates; coexistence with the Mid-360; what `utlidar/switch` does | **ticket Q6** + step **Q-lidar**: photograph the label, then `preflight --builtin-lidar-model "<label>" --operator <name> --photo <id> --json > hw/Q_lidar.json` (the label reading is refused without an operator and a photograph); the machine read is `rt/utlidar/lidar_state` over DDS | HW-3's `L2 → HEAD_LIDAR` re-label closing as *proven* rather than *declared*; design §5.3's final word on `voxel_map` | design (updates §5.3) |
| **Q-stop** | does the remote's `L2`+`B` damp when the head board / dock hang? [documented that it damps; **UNCONFIRMED** that it is independent of DDS] | step **Q-stop**: on the stand, sport mode on, head board's NIC unplugged | **HW-12** and **PO-1** — if it does not damp, the handheld is not an independent stop and the e-stop decision must be re-taken before anything is armed | PO-1 |
| **Q-avoid** | does sport-mode obstacle avoidance stay active under `SportClient.Move`, and how does it interact with Parcel's yield / doorway logic? | Stage-1: one axis toward a box **inside the commissioning band** — linear 0.02–0.05 m/s, yaw ≤ 0.156 rad/s, step ≤ 1.0 s (`commissioning/limits.py`); the band **refuses 0.10 m/s** — avoidance on and off | **HW-6**'s Q-avoid test plan closing; HW-12's second stage | design (HW-6) |
| **Q-ort** | is `onnxruntime-gpu` ≥ 1.28 buildable on JetPack 6.2.1, or does the Orin pin ≤ 1.23 / use TensorRT directly? [no public Jetson wheel satisfies the pin today — measured] | step **Q-ort**: OWLv2 fp16 latency at the dog's power mode with `tegrastats` alongside (engineer, owner not present) | **HW-1**'s `perception-jetson` extra being *validated* rather than resolvable-on-paper; the detector daemon's placement (design §5.2) | design |
| **Q-slam** | FAST-LIO2 vs Point-LIO; does Parcel own `T_map_odom` or integrate someone else's? | **B17 bake-off** on one recording, two providers, a drift table | **HW-10** — this unknown *is* HW-10 | design |
| **Q-cam** | does the H.264 multicast front-camera stream reach the dock NIC? Is `rt/frontvideostream` at ~33 Hz usable? | capture-channel smoke during B12 | nothing — the front camera is **capture-only either way** (VENUE-1's RGB ruling stands, which is why the D455 buy survives PO-1) | design |
| **Q-uwb** | what `rt/uwbstate` carries; is the fob shipped; indoor accuracy (U39) | decode the topic + a tape test | nothing — UWB is **evidence only, never authority**; it would block an OT-2 fusion promotion that no card proposes | design |
| **Q-link** | Wi-Fi 6 vs 4G RTT to the hosted lane; behaviour on link loss | step **Q-link**: 5-minute RTT sample on each path | nothing on the software-now rail; the HOLD-on-link-loss rule's numbers | design (HOLD) |
| **Q-batt** | duty cycle; dock / charge behaviour; what the roam does at low battery | a battery log across one idle + one roam hour | nothing yet — the HOLD-at-20 % policy is recorded as a decision, not measured | design (HOLD at 20 %, recorded) |
| **Q-pose** | do `curious_look` / sit / greet get a commissioned `GatewayActionV1` on the dog? | after the leashed stage | nothing in wave 3; the "living dog" channel's second ODD | owner + PO-1 |
| **Q-image** | golden image with one integrated Orin — buy a second unit to honour ADR 0001's two-dock rule, or waive it on record? | owner decision; sharpened by Q-jp (a reflash is what makes the rule bite) | any reflash under Q-jp option (i) — there is no sacrificial dock, because the dock is inside the robot | owner |

## How a row closes

1. The measurement named in **resolves on** runs and writes its result file
   under `hw/` (see `docs/BOX_DAY.md`, "The `hw/` convention").
2. The row is edited **here** with the result and the file path — this
   register is the single place a reader looks to ask "is that still open?".
3. If the answer contradicts the design, `../WAVE3_HW_DESIGN_FABLE.md` is
   amended in the same pass and §10's falsified-claims list gets a line. A
   design that quietly stops matching the hardware is worse than no design.
4. A row is **never** closed by a document, a vendor page, or a plausible
   inference. Only a measurement or a written vendor answer closes a row, and
   a vendor answer is tagged `[documented]` with the ticket reference.

## What this register does not do

It does not rank the unknowns by risk, and it does not schedule them. The
order of work is `docs/BOX_DAY.md`'s; the risk judgement is the owner's. It
also holds no unknown that the desktop can settle — those are card rows in
the wave-3a software-now rail, and if one of them appears here it is
misfiled.
