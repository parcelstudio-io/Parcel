# Support ticket — Unitree / robostore, Go2 EDU Plus with Mid-360

> ## ⬜ NOT SENT. This card sent nothing.
>
> This is a **draft for the owner to send**, from the owner's own account, to
> the reseller the unit was bought from (robostore) and/or Unitree support.
> Card HW-8 wrote it and sent nothing, contacted nobody, and opened no
> account. Fill the three bracketed fields, send it, and write the reference
> in the log at the bottom.

**Why now, before delivery.** Two of these six answers change what happens
in the first ten minutes with the box, and one of them (Q-jp) can stop the
day entirely. Delivery is 2–4 weeks out, so a support round-trip is free
time; after delivery it is the critical path. Every one of these is
currently **UNCONFIRMED** in `UNKNOWNS_REGISTER.md` (same folder).

---

## The message (copy from here down)

**Subject:** Go2 EDU Plus w/ Mid-360 — pre-delivery technical questions
(order [ORDER REF], [NAME])

Hello,

I have a Go2 EDU Plus with the Livox Mid-360 on order ([ORDER REF], expected
[DATE]). I am integrating my own perception and voice software on the onboard
Jetson, so I would like to plan the first session before the unit arrives.
Six questions, in the order that matters to me:

**1. JetPack / L4T on the AI docking station, as delivered in 2026.**
Which JetPack and Jetson Linux (L4T) release ships on the Orin NX 16 GB dock
today? Reports from 2024–25 units say JetPack 5.1.1 (Ubuntu 20.04, Python
3.8). My software stack targets Ubuntu 22.04 / CPython 3.10, i.e. JetPack 6.x.
If the unit ships on JetPack 5:

  a. Do you publish a JetPack 6.x (L4T 36.x) BSP or flashable image for the
     EDU Plus carrier board? NVIDIA's own images do not cover a custom
     carrier, and NVIDIA's forum directs users to the board vendor.
  b. If yes — what is the supported flashing procedure, does it void
     warranty, and is there a recovery path if the flash fails? There is only
     one dock and it is inside the robot.
  c. If no — is a JetPack 6 image planned, and on what timescale?

**2. Mid-360 wiring on the dock.**
The bundle's Mid-360 connects through the round connector on the Jetson
docking station ("M8 air plug"). Please confirm:

  a. What voltage and current does that plug supply? The Mid-360 datasheet
     asks for 9–27 V DC, 6.5 W average, 14 W peak.
  b. Which Jetson network interface does the Mid-360 land on, and what IP
     addressing is preconfigured (Livox's convention is host 192.168.1.5,
     sensor 192.168.1.1xx — does yours follow it, or does the sensor sit on
     192.168.123.x with the robot LAN)?
  c. Is `livox_ros_driver2` (and Livox-SDK2) preinstalled on the dock, and
     against which ROS 2 distribution?
  d. Is the Mid-360's Ethernet bridged to any other interface on the dock?

**3. Shipped firmware and the DDS security advisories.**
  a. Which robot firmware version will ship on my unit?
  b. Is over-the-air / automatic firmware update **on** by default, and how
     do I turn it off before the robot ever joins a network?
  c. CVE-2026-27509 describes an unauthenticated CycloneDDS remote code
     execution on domain 0 (topic `rt/api/programming_actuator/request`),
     affecting V1.1.7–V1.1.9 and V1.1.11 EDU, and the advisory still lists
     the patched version as unknown. **In which firmware release was
     CVE-2026-27509 fixed?** If it is not fixed, please say so plainly — I
     will keep the robot LAN firewalled either way, but I need to know
     whether the version pin means anything.

**4. "Secondary development" / DDS exposure out of the box.**
On a new EDU Plus, are the DDS topics (`rt/sportmodestate`, `rt/lowstate`,
`rt/utlidar/*`, `rt/uwbstate`, `rt/frontvideostream`) published by default, or
does something have to be enabled first — a "secondary development" toggle in
the app, or a firmware tool? If it is a toggle, where is it, and does enabling
it affect warranty or the built-in obstacle avoidance?

**5. Dock ports and payload power.**
  a. Exactly how many USB ports does the docking station expose, and of which
     type and speed? Resellers list "1× USB 3.0 Type-A plus one or two USB
     Type-C" and I cannot tell which is right. I need to attach a RealSense
     D455 (USB-C 3.1 Gen 1, bus-powered) **and** a USB microphone array at the
     same time, both at USB 3 speed for the camera.
  b. Is any regulated DC output available to payloads besides the M8 plug, and
     at what voltage and current budget?
  c. What battery runtime should I expect with the Orin under load (25–40 W)
     plus the Mid-360, a D455 and a USB mic array? The listed 2–4 h appears to
     be for an unloaded robot.
  d. **How do I get a terminal on the Jetson before it joins any network?**
     The port list I have shows no HDMI or DisplayPort. Is there a serial /
     USB console header, and what are its settings? And what is the second
     RJ45 for — is it free for a direct cable to a laptop with a static
     address, or is it bridged to the robot's internal 192.168.123.0/24
     segment? I would rather not attach the robot to my house network before
     I have read its firmware version and set up a firewall.

**6. Head LiDAR model (short one).**
Is the built-in wide-angle head LiDAR on a 2026 EDU Plus an L1 or an L2? Your
comparison table says 4D LiDAR L2; older listings and docs describe an L1. And
with the Mid-360 also fitted, which unit feeds `rt/utlidar/voxel_map` — is
`rt/utlidar/switch` how I choose?

Thank you — happy to be pointed at documentation rather than answered
directly for any of these.

[NAME]

## (end of the message)

---

## What each question closes

| Q | Unknown | Why it cannot wait for delivery | If unanswered |
|---|---|---|---|
| 1 | **Q-jp** | JetPack 5 stops the software day (design §7.2); the decision is a reflash, a Python-3.10 build on 20.04, or a hold — all owner decisions with a lead time | step B9 reads it on the day and the day may end there |
| 2 | **Q-wire** | decides the static addressing of the day-1 firewall, and whether a meter has to come out before the plug is trusted | step Q-wire reads it with `tcpdump` and a multimeter; slower, and the meter reading must happen powered-off |
| 3 | **Q-fwv** | the version pin (ADR 0002, ≥ 1.1.13) is a security control with an unknown patched version; OTA must be disabled **before** the robot joins any network | step S20 records the version; the firewall carries the load regardless |
| 4 | **Q-dev** | if DDS is off by default, every topic read in the first two hours returns nothing and looks like broken hardware | step Q-dev finds out; the remedy is a toggle, never a flash |
| 5d | **Q-con** | a shell on the Orin with no LAN joined — no HDMI/DP in the documented port list; direct-Ethernet vs serial console is UNCONFIRMED | **nothing in the first two hours can be typed without it** | step B-con tries a direct cable first, then serial |
| 5 | **Q-usb / Q-pwr** | decides whether a powered hub is on the shopping list and whether the mount sheet is drawn around two USB-C ports or one | step Q-usb reads `lsusb -t`; a missing port costs a session |
| 6 | **Q-lidar** | decides whether the head unit is worth recording alongside the Mid-360 | step Q-lidar reads it electronically off `utlidar/lidar_state` plus a photograph of the label |

## Log — fill when sent

```text
sent to:        robostore / Unitree support / both      ______
sent at:        ____-__-__  __:__
ticket ref:     ____________________
reply received: ____-__-__      answers merged into UNKNOWNS_REGISTER.md by: __________
```
