# BOX_DAY — the first two hours on the Go2 EDU Plus

**Who this is for:** the owner, reading alone before delivery, then aloud on
the day. **Read time ~10 minutes.** **Card:** HW-8
(`scrum/20260822/task_39/`). **Design of record:**
`scrum/20260822/WAVE3_HW_DESIGN_FABLE.md` §7, whose §2 holds the source URL
behind every `[documented]` claim here.

**Time this asks of you:** first two hours = **105 min**. Everything on the
whole box-day rail that you must personally be present for = **310 min
(5.2 h)**, inside PO-1's 6–8 h budget. Engineer-only work is marked and
excluded from that sum.

**The rule for the day:** every step is a **read** with a written result
file. Nothing is armed. Nothing is fixed. If a step surprises you, write the
surprise down and move on — a debugging day is how a one-shot day is lost.

## Before the box arrives (do these now)

1. **Send the support ticket** —
   `scrum/20260822/task_39/SUPPORT_TICKET_UNITREE.md`. Two of its questions
   (JetPack version, Mid-360 wiring) decide whether day 1 is a session or a
   stop. Record the reference there.
2. **Record the e-stop decision (PO-1).** `scrum/20260822/task_27/README.md`
   names the choice: the handheld remote plus a leash, with a recorded waiver
   of `docs/MOTION.md:441-442`, or a battery-path relay. **That record must
   exist before any `--arm` runs.** The first two hours arm nothing.
3. **Read this end to end and sign the last line.**

## Preconditions — the hard bar

Nothing below starts until all five hold:

- the dog is **on a stand**, feet clear of the floor;
- **sport mode is OFF**;
- the **remote is in your hand**, and whoever holds it does nothing else.
  `L2` (long press) + `B` is Damping / emergency stop [documented], and
  damping takes joint torques to **zero**, so an unstanded dog **falls**
  [documented]. That is the whole reason for the stand;
- **no LAN is joined** — the dock is on no network at all;
- **firmware OTA is disabled in the Unitree app BEFORE the dock joins any
  network** (ADR 0002 item 3, `scrum/20260805/task_1/adr/0002-firmware-pin.md`).

## Stop rules

1. **B9 says JetPack 5.** Stop. Go to "The JetPack-5 branch" below. Nothing
   else on this page runs.
2. **Firmware below 1.1.13, or unread.** Nothing joins `192.168.123.0/24`;
   unread counts as below. ADR 0002 pins ≥ 1.1.13 — but CVE-2026-27509
   (unauthenticated CycloneDDS RCE on domain 0) has **no known patched
   version** [documented], so the pin is *not* sufficient and step B-fw's
   firewall is what carries the load.
3. **Anything wants fixing by a flash, `apt upgrade`, or the bootloader.**
   Stop. One dock, no golden image, no second unit (ADR 0001's two-dock rule
   is unmet).
4. **The dog moves.** Damp it, put the remote down, and write down what
   happened before touching a keyboard.

## The first two hours — 105 min

Every command runs **on the Orin**, from the repo checkout at `~/Parcel`,
with the system `python3` (never `.parcel/`, which is an x86 3.14 venv).
Results go to `~/Parcel/hw/` — see "The `hw/` convention".

| # | Step | Who | Command / action | Result file | Branch | Min |
|---|---|---|---|---|---|---|
| 0 | **B0** stand & preconditions **(added by HW-8)** | owner | the five preconditions above; then power the dock | `hw/B0_preconditions.txt` | unmet → stop | 15 |
| 1 | **B-con** a shell on the Orin **(added by HW-8)** | owner | No command below can be typed without a terminal on the Orin, and "no LAN is joined" rules out ssh over the house Wi-Fi. The dock's documented ports include **no HDMI or DisplayPort** [documented], so two routes are candidates and **which works is UNCONFIRMED** (ticket Q5d): (a) a laptop on a **direct Ethernet cable** to the dock's spare RJ45, static addresses both ends, **no gateway** — a cable between two machines is not a LAN; (b) a **USB-serial console** cable. Try (a) first. Record which worked and the address; then `mkdir -p ~/Parcel/hw` | `hw/B_con.txt` | neither route works → stop; nothing else on this page can run | 10 |
| 2 | **B9** identity | owner | `python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir ~/Parcel/hw --until p0_identity` — and if it cannot run, by hand: `cat /etc/nv_tegra_release; uname -a; python3 -V; ls /opt/ros; tegrastats --interval 1000 \| head -3; ip -br a; lsusb; lsblk` | `hw/B9_identity.txt` (the harness also leaves `hw/p0_identity.json`) | **JetPack 5 → STOP, see below.** JetPack 6 → continue | 10 |
| 3 | **B-fw** firewall | owner | <!-- HW-FW: replaces HW-8's inline stopgap — the ruleset now exists and persists. --> Fill the `define`s at the top of `deploy/orin/nftables.conf` from B9 (`$rnic` = the NIC holding **`192.168.123.18`**). Then `deploy/orin/README.md` **step 0.5 first**: read which interface your own shell arrives on — if it is `$rnic`, **STOP** and take one of the two routes recorded there, because applying now drops your next packet. Then §1: `sudo nft -c -f` each `.conf` (check-only), arm the five-minute dead-man's switch (it **disables** the unit, not just the tables), `sudo systemctl enable --now parcel-nftables`, and prove a **second, new** ssh connection before cancelling it. Verify `sudo nft list table inet parcel`: `forward` = `policy drop`, no accept; `systemctl is-failed parcel-nftables` = `active` (anything else means the lockdown fallback is running); **no default route** via `$rnic`; Mid-360 static **`192.168.1.5`, no gateway** (Q-wire); panel **`127.0.0.1`** + **tailnet** (ADR 0002 item 4). **Re-check after the first reboot and again before Q-link.** Save README §2's block | `hw/B_fw.txt` | **must pass before any WAN interface comes up** | 15 |
| 4 | **S20** firmware | owner | **Read the version in the Unitree app** and confirm OTA is off there — this repository has **no way to read it off the robot** (`attest` ships no live identity reader; it returns `REFUSE_CONNECT`). Then record it: `python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir ~/Parcel/hw --until p3_network --firmware-attested V<x.y.z>` | `hw/p3_network.json` | below 1.1.13 → owner decision; **unread → treated as below**, and the harness refuses. The record is made **before the dock joins any LAN** (ADR 0002) | 10 |
| 5 | **Q-dev** DDS exposure | owner | on domain 0, robot NIC only: `ros2 topic list` (or `cyclonedds ls`). Do `rt/sportmodestate`, `rt/utlidar/*`, `rt/uwbstate`, `rt/frontvideostream` appear? | `hw/Q_dev_topics.txt` | absent → the "secondary development" toggle is off; record it, do not flash | 10 |
| 6 | **Q-lidar** head model | owner | **Photograph the model label on the head unit first** — the photograph is the input, and an unattributed label reading is refused. Then: `python3 -m scripts.parcel_capture.preflight --builtin-lidar-model "<label as printed>" --operator "<your name>" --photo <photo id or path> --json > hw/Q_lidar.txt`. That file is the human report **followed by** the JSON block — keep it whole. The machine read is `rt/utlidar/lidar_state`, over DDS | `hw/Q_lidar.txt` | settles L1-vs-L2 and which unit feeds `voxel_map` | 10 |
| 7 | **Q-wire** Mid-360 | owner | `tcpdump -i <nic> udp port 56300` on each NIC in turn; note the device IP; meter the M8 pin voltage **powered off first** | `hw/Q_wire.txt` | decides the static address of step B-fw | 15 |
| 8 | **Q-usb** dock USB | owner | `lsusb -t`; D455 on the USB 3.0 A port → `rs-enumerate-devices`; XVF3800 on a C port → `python3 tools/xvf3800_probe.py --json hw/Q_usb_array.json` | `hw/Q_usb.txt` (+ the array's own `hw/Q_usb_array.json`) | both enumerate, or the mount sheet changes | 10 |

**Sum: 105 min.** Steps 5–8 may be reordered; steps 0–4 may not.

Facts you are confirming, and what is not —

- Orin NX 16 GB onboard, Mid-360 in the box, 720p/120° RGB front camera, **no
  depth** (why the D455 buy stands), 15 Ah, 12 kg payload [documented].
- The head LiDAR is reachable **only** over DDS `rt/utlidar/*` from
  `192.168.123.161`; the dock is `192.168.123.18` [documented]. L1 or L2:
  **UNCONFIRMED**, settled by Q-lidar.
- That the Mid-360 lands on the M8 air plug is **UNCONFIRMED** (inferred from
  third-party cable listings) — Q-wire settles it, and the voltage. It needs
  9–27 V, the battery is 28–33.6 V [both documented], so it cannot hang on the
  battery rail: the plug supplies the difference.
- Livox UDP: cmd 56100, point 56300, IMU 56400; host `192.168.1.5`, lidar
  `192.168.1.1xx` [documented]. That /24 **must not collide with the home
  LAN** — `configs/robot.yaml` flags this.
- Dock ports "1× USB 3.0 A, 1–2× USB-C, 2× GbE, M8" [documented, resellers
  disagree on the USB-C count] — the count is **UNCONFIRMED**; Q-usb settles
  it and whether a hub is needed.
- Which JetPack ships is **UNCONFIRMED**: 2024–25 units are reported as
  JetPack 5.1.1 / Ubuntu 20.04 / CPython 3.8 [documented]; a 6.2.1 path for
  Unitree's carrier is inferred only — B9 and the ticket settle it.

## The JetPack-5 branch (design §7.2)

If B9 reports L4T 35.x / Ubuntu 20.04 / Python 3.8, **stop the day's software
work.** Our preflight's L4T table covers JetPack 6.0–6.2.1 only and fails
closed on JetPack 5 — correctly. Three options, **owner-decided; no card
takes one alone**:

1. **Reflash to JetPack 6.2.1** — only if Unitree publishes a BSP for its
   custom carrier (ticket question 1). Full backup first. Warranty-sensitive.
   ADR 0001's two-dock rule is waived on record, or a second unit is bought.
2. **Run on a CPython 3.10 built on 20.04** — the perception daemon then has
   no prebuilt GPU wheel at all, and detection moves off the dog to the
   desktop over the tailnet.
3. **Hold** the box-day proofs until (1) is possible.

The design's default is (1) if the BSP exists, else (2) with perception
off-dog. Either way, card **HW-1**'s 3.10 row must be **green** before the Orin runs anything from this repository.

## Session 2 and after — 205 min with you present


| Step | Command / action | Result file | Min | Who |
|---|---|---|---|---|
| **B11** extrinsics | mount sheet, two people: D455 height/tilt, Mid-360 to `base_link`, array position; tape and photographs; then the clock-map ritual `python3 -m scripts.parcel_capture.syncevents --ritual-card` | `hw/B11_extrinsics.yaml` | 30 | owner + second |
| **B12** recorder smoke | in order: `python3 -m scripts.parcel_capture.record --check --dest <target>` (readiness + free space); `python3 -m scripts.parcel_capture.stage0_addendum --print-argv humble` (**prints** the `ros2 bag record` argv — the repo's single argv truth; never `--emit-distro`, which **writes into the checkout**, and git is read-only here); run that argv 60 s; `python3 -m scripts.parcel_capture.record --verify <bag>.mcap`. One transcript, all four outputs. **The bag stays on the record target** — it is gibibytes; the transcript carries its path and digest | `hw/B12_record.txt` | 20 | engineer, owner present |
| **S19** Stage 0 | `python3 -m parcel_robot.unitree_control observe --min-samples 3000 --timeout 90 --out hw/S19_stage0_01.json`. **There is no duration mode**: it stops at whichever comes first, `--min-samples` messages or `--timeout` seconds, and **refuses** (`NO_FEEDBACK`) below `--min-samples` — itself a finding worth keeping. 3,000 messages ≈ 60 s at the *expected* ~50 Hz (expected, not measured), so a ten-minute Stage 0 is **ten runs of that line**, `_01`…`_10`; keep every file, refusals included | `hw/S19_stage0_01.json` … `_10.json` | 15 | owner |
| **Q-stop** | on the stand, sport mode on, issue `StopMove`, then `L2`+`B` from the remote **with the head board's NIC unplugged**. Does it damp? | `hw/Q_stop.txt` | 10 | owner |
| **Q-link** | RTT from the Orin to the hosted lane over Wi-Fi 6, and 4G if provisioned; 5-minute sample | `hw/Q_link.txt` | 10 | owner |
| **Q-batt** | 30 min idle + 30 min roam, Orin + Mid-360 + D455 + array powered; log voltage and runtime (vendor's 2–4 h is unloaded). The roam is **driven from the Unitree remote or app, never from Parcel** | `hw/Q_batt.txt` | 15 attended | owner |
| **first armed step** (card HW-12) | one axis, on the stand, inside the commissioning band: linear **0.02–0.05 m/s**, yaw **≤ 0.156 rad/s**, step **≤ 1.0 s**, so one step travels **≤ 0.10 m** (`commissioning/limits.py`). The band **refuses 0.10 m/s** — that older figure is a retired 08-03 cap. Preconditions below | HW-12's status doc | 45 | owner + second |
| **first leashed follow** | after HW-12 is green | HW-12's status doc | 60 | owner + second person |

**Sum with you present: 205 min. Grand total 105 + 205 = 310 min (5.2 h).**

**"Engineer" here is a role, not a second person** — you, or whoever you hand
the keyboard to. Only rows saying *two* need two.

**Engineer-only, you are not needed** (excluded from the sum): **Q-ort** —
detector latency at the dog's power mode (`hw/Q_ort.txt`, ~20 min); the LIO
bake-off (HW-10); the native gateway build (HW-11).

## Before the first armed step — all four, no exceptions

1. **PO-1's e-stop record exists**, with the `MOTION.md:441-442` waiver
   written down if the choice was the remote plus a leash
   (`scrum/20260822/task_27/README.md`).
2. **Q-stop passed** — the remote damped the dog with the head board's NIC
   unplugged. If not, it is no independent stop and PO-1 is re-decided.
3. **S19 Stage 0 is green** — 10 minutes of observation, zero `Move`.
4. **The stopping envelope re-run is green with measured numbers** (card
   HW-6, `src/parcel_robot/bridge/timing.py`): measured braking latency, LIO
   jump magnitude and gateway watchdog period must fit inside the
   commissioned stopping distance. A gate, not a note.

## The `hw/` convention

- Every step writes exactly **one** file under `~/Parcel/hw/`, named for its
  step id: a crash loses at most one step, and a missing file shows as a
  missing row.
- **Raw output, verbatim.** A summary is not evidence.
- Git on the Orin is read-only. At session end the directory comes home —
  `rsync -av <orin>:~/Parcel/hw/ scrum/<date>/task_NN/hw/`, `task_NN` being
  the box-day card (HW-9). Those files **are** its status doc.

## Commands that do not exist yet

Four things the design names are **not in this repository**. Each is worked
around above — listed so nobody types a spelling that fails:

- **`parcel-capture …`** is not a console script; every capture tool is
  `python3 -m scripts.parcel_capture.<module>`, as used above.
- **`record --plan stage0 --dry-run`** — no `--plan`, `stage0` or
  `--dry-run`. B12 uses `record --check`, `stage0_addendum --print-argv`
  and `record --verify`.
- **`parcel-commission observe`** — the real one is
  `parcel-unitree-control observe`, with **no fixed-duration mode**: hence
  S19's ten runs.
- **A firmware read off the robot** does not exist — S20 is an app read the
  harness records. <!-- HW-FW --> `deploy/orin/nftables.conf` now **does**
  exist (card HW-FW): B-fw is a file to apply, not rules to type.

## What this runbook does not authorise, and does not prove

It authorises **no motion**. Nothing here imports
`parcel_robot.control.unitree_sport`, and nothing here is evidence about how
the dog behaves — the reads produce the evidence, and a person rules on it
afterwards, in the box-day card. A green first two hours means the machine is
what we think it is. It says nothing about perception, SLAM, owner tracking,
battery under load, or whether the robot is safe to walk.

---

**Owner sign-off.** I have read this end to end. The e-stop decision is
recorded. The support ticket is sent.

Name: ________________  Date: ____________  Ticket ref: ____________
