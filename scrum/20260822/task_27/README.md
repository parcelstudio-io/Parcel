# Task 27 — PO-1: the purchase decision record

**Owner's decision card** (no executor; Fable keeps the record). **Board:**
`../TASK_BOARD.md`. **Evidence:** `PLAN_ASSESSMENT_FABLE.md` (the answer +
build order); the three proposals' converged buy/don't-buy lists; the
08-22 audit §7 (compute: the tethered RTX 5000 Ada is the plan; an Orin hosts
detector + ASR at most); `docs/MOTION.md:158,357,441-442,491-492` (an
independent hardware e-stop + watchdog is required and lives outside this
repo); `scrum/20260805/task_1/P5_PROCUREMENT_BOM.md` (no prices by design).

## Buy now
* **Intel RealSense D455** (~$300) — the only hardware on the critical path
  of P1-A / P1-C / VENUE-1 / OT-2 live rows; `backends/realsense.py` and
  `pyrealsense2 2.58.3` are already in `.parcel`. Not a webcam (RGB-only
  cannot feed the ingress).
* **A small speaker on the array's JST-PH2.0 amp** (~$15) if the one ordered
  on 08-04 is not on hand — the array's AEC reference is its own DAC path.

## Request now, release on evidence
* **Go2 EDU Standard quote** (free; 2–4-week lead; EDU required — CycloneDDS
  is out-of-the-box only on EDU; firmware ≥ 1.1.13 per ADR 0002,
  auto-update off; decline the Orin dock and the L2 add-on; confirm the head
  LiDAR model and whether a RealSense ships in the kit). **Release the PO at
  the week-3 gate when all three hold:**
  1. the owner backlog is done (udev/DoA, voice enrollment, quarantine);
  2. ROAM-1 reaches net displacement ≥ 1.0 m in three consecutive sim runs
     — **measured 08-22 (week-1 close, verified):** seven product-path
     tethered 120 s runs, 1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56 / 6.57 m
     net in-block, 0 contacts, in-bounds 7/7; the roam is bimodal (a 6.5 m
     out-and-back trajectory when the tether engages, a 1.3–3.4 m boxed
     wander when it does not); the tell holds on every run, and the number
     that matters next is coverage (ROAM-2, `task_33`);
  3. through-air false barge-in ≤ 2 % with the TV on (AIR-1).
  Early tells that mean "order now instead": interrupt/false-barge-in
  collapse under the far-field/noise arm (desk acoustics don't transfer), or
  the sim-viewer A/B shows the body is load-bearing for "felt like a creature".
* **Independent hardware e-stop + watchdog** — same basket as the dog.
  Decision to record before the first armed step: (a) the Unitree handheld
  remote (direct radio to the robot MCU — independent of Parcel, DDS, LAN and
  the dock, NOT of Unitree firmware) plus a leash as the Stage 0–2 stop with
  an explicit recorded waiver of `MOTION.md:441-442`, or (b) a battery-path
  relay (hardware mod, warranty). Recommendation for a prototype: (a) with the
  waiver; (b) is a week-7 question.

## Don't buy
Orin NX docks (the desktop GPU is the compute); EDU Plus (+$2k for compute
that tethers anyway); the L2 LiDAR (no physical scan consumer exists — the
built-in head LiDAR first); ZED-F9P + NTRIP (indoor companion); any USB or
Bluetooth speaker/headset (defeats the array's AEC); a second mic array; a
webcam.

## Owner time this plan asks for
Week 1 ≈ 1.5 h (backlog 15 min, recordings 20 min, speaker 10 min, quote
30 min); week 2 ≈ 2 h (through-air session + TV arm + daily felt sessions);
week 3 ≈ 1.5 h (far-field arm, personal-convo script, the decision); after
delivery 6–8 h over two weeks (Stage 0, mount sheet with two people, first
armed step, leashed follow).
