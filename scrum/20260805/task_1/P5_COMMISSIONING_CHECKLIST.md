# P5 Commissioning checklist — DRAFT STUB ONLY

**Date:** 2026-08-05 · **Status:** Draft stub (paperwork; not executed)  
**Binding:** [ADJUDICATION.md](ADJUDICATION.md) Owner amendment; Sol H0 / L6–L8 content.  
**Blocked on:** owner purchase decision → [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md).

> **DO NOT EXECUTE.** No robot, dock, or sensor has been procured for this
> program increment. This checklist is readiness paperwork so Phase 5 can
> run later without redesign. Completing a checkbox here is not validation.

Sources: Fable staged live protocol (stand → dry-run → gaze-only → leashed
vx≤0.15 → free); Sol H0 (physical commissioning checklist, test course,
E-stop, evidence template); dual e-stop + comms-loss auto-damp at every
stage; commissioning record required to arm.

Related: [hardware-readiness.md](hardware-readiness.md) ·
[PHASE5_GATE.md](PHASE5_GATE.md) ·
[adr/0001-golden-image.md](adr/0001-golden-image.md) ·
[adr/0002-firmware-pin.md](adr/0002-firmware-pin.md)

---

## Preconditions (all must be true before Stage 0)

| # | Precondition | Evidence | Done? |
|---|---|---|---|
| P0 | Owner authorized purchase; BOM items received and inventoried | PO / receipt IDs in [P5_PROCUREMENT_BOM.md](P5_PROCUREMENT_BOM.md) receipt log | [ ] |
| P1 | Go2 EDU firmware ≥1.1.13 recorded; auto-update disabled | Firmware string + photo/log; ADR 0002 checklist | [ ] |
| P2 | Sacrificial Orin NX dock flashed to pinned JetPack 6.2.x; image hash recorded | Image hash; ADR 0001 checklist (**P5-G-INSTALL**) | [ ] |
| P3 | Second (production) dock restored from golden image — never mutated | Restore log | [ ] |
| P4 | Dual e-stop hardware present and labeled (operator handheld + dock/soft latch) | Serials + photo | [ ] |
| P5 | Machine-readable commissioning record schema ready; runtime refuses to arm without it | Wizard / record schema path | [ ] |
| P6 | Day-one bag destination + `parcel.bag.v1` harness green in CI | `tests/test_bags_roundtrip.py` | [ ] |

---

## Stage ladder (do not skip)

| Stage | Name | Motion envelope | Exit criteria (summary) | HR / P5 gates |
|---|---|---|---|---|
| 0 | **Dry-run** | Motion **disabled**; DDS/time/camera/LiDAR/voice/stop path only (Sol L6) | Sensors stream; e-stop path verified twice; no Sport velocity admitted | P5-G-INSTALL, P5-G-BAG-DROPIN |
| 1 | **Bench** | Stand / sit / standstill; no locomotion; gaze-only optional | Height-map/UWB/SportModeState adapters live; D455 + XVF3800 mounted; UWB pairing; firmware pin gate hard-fails below pin once on purpose | P5-G-UWB (bench), P5-G-PIXEL (bench), P5-G-AUDIO (bench), P5-G-ORIN-TIMING (replay) |
| 2 | **Leashed** | Fenced / tethered; **vx ≤ 0.15 m/s** first; operator leash + dual e-stop | Commanded vs measured SE2 within tolerance; latched E-stop; curb-stop on mapped crossings; zero autonomous street entries | P5-G-MOTION, P5-G-LIDAR, P5-G-CROSSING, P5-G-MAPS |
| 3 | **Free** (restricted) | Supervised mapped sidewalk / indoor only; still dual e-stop | Headline 20-min mixed course; minutes-per-intervention baseline; Tier-0 survival; no claim beyond tested envelope | P5-G-ROUTE (+ optional CityWalker/VLFM promotion) |

**Rule:** dual e-stop and comms-loss auto-damp must be **re-verified at every
stage entry**. No stage begins with an unbounded learned controller.

---

## Stage 0 — Dry-run (motion disabled)

- [ ] Dock compose stack boots; safety+control container has **zero** network deps
- [ ] Clock / TF / DDS segment firewalled (`192.168.123.0/24`); remote = tailnet only
- [ ] Camera (D455) + LiDAR topics publish; bag recorder writes `parcel.bag.v1`
- [ ] Soft stop + both hardware e-stops trip the stop path within ≤300 ms budget (measure)
- [ ] Comms-loss auto-damp demo once (disconnect → damp → latched stop)
- [ ] Runtime refuses Sport arm without commissioning record
- [ ] Evidence: run ID `P5-DRY-…`, bag digest, latency snapshot → fill template below

**Gate cross-link:** HR-8 **P5-G-BAG-DROPIN**, HR-9 **P5-G-INSTALL**

---

## Stage 1 — Bench (standstill / no locomotion)

- [ ] D455 extrinsics auto-cal (or recorded manual cal) at 35 cm mount height
- [ ] UWB fob paired; bearing/range logged vs vision truth (indoor first)
- [ ] XVF3800 mounted; AEC / ack latency smoke (desktop B1 apt may still be needed for WoZ tooling)
- [ ] On-device bag replay of frozen sim bags; hot path median ≤176 ms (**P5-G-ORIN-TIMING**)
- [ ] Low-viewpoint gate pack on day-one D455 frames (**P5-G-PIXEL** bench subset)
- [ ] GNSS receiver cold-start + NTRIP (if available) logged into bag harness (**P5-G-GNSS** bench)
- [ ] Evidence: run ID `P5-BENCH-…`

**Gate cross-link:** HR-2, HR-3, HR-4, HR-6, HR-7

---

## Stage 2 — Leashed (vx ≤ 0.15 first)

- [ ] Dual e-stop re-check; leash attached; geofence / keepout loaded
- [ ] Command bag replay closed-loop through `ControlManager` only (**P5-G-MOTION**)
- [ ] LiDAR freeze/collision rates vs sim baseline (**P5-G-LIDAR**)
- [ ] Mapped crossing: curb-stop 100%; zero autonomous road entries (**P5-G-CROSSING**)
- [ ] Voice initiation through T1 with gate concurrence on ≥1 scripted curb
- [ ] Minutes-per-intervention logged for fixed 20-min mixed course (leashed)
- [ ] Evidence: run ID `P5-LEASH-…`

**Gate cross-link:** HR-1, HR-5, HR-10, HR-11

---

## Stage 3 — Free (restricted envelope only)

- [ ] Operator brief + dual e-stop; envelope map posted (indoor / mapped sidewalk only)
- [ ] Teach ≥2 habitual walks; repeat-route metrics vs HR-12 targets (**P5-G-ROUTE**)
- [ ] Optional: CityWalker / VLFM promotion only per ladder (≥+5pp, no extra gate interventions)
- [ ] Tier-0 (onboard-only) sustains one full walk
- [ ] Explicit `does_not_prove` on any claim outside tested envelope
- [ ] Evidence: run ID `P5-FREE-…`

**Gate cross-link:** HR-12, HR-13, HR-14

---

## Dual e-stop verification (repeat every stage)

| Check | Method | Pass criterion | Result |
|---|---|---|---|
| Handheld e-stop | Press during idle / commanded motion (stage-appropriate) | Motion latches stop ≤300 ms; requires explicit clear | _TBD_ |
| Dock / soft latch | Trigger secondary stop | Same as above; independent of handheld | _TBD_ |
| Comms loss | Kill teleop / dock link | Auto-damp then latched stop; no resume without operator | _TBD_ |
| False-clear resistance | Attempt arm without commissioning record | Runtime hard-fail | _TBD_ |

---

## Evidence templates (copy per run)

### Run header

```text
run_id:           P5-<STAGE>-YYYYMMDDTHHMMSSZ
stage:            dry-run | bench | leashed | free
device_ids:       go2=<serial> dock=<serial> d455=<serial> gnss=<serial> xvf=<serial>
firmware:         go2=<version ≥1.1.13> jetpack=<pinned> image_hash=<sha>
git_sha:          <commit>
operator:         <name>
second:           <safety observer>
gates_targeted:   [P5-G-…]
hr_rows:          [HR-…]
bag_digest:       <sha256 of bag root>
does_not_prove:   <non-empty>
```

### Latency / stop snippet

```text
e_stop_handheld_ms:
e_stop_dock_ms:
comms_loss_to_damp_ms:
hot_path_median_ms:      # ≤176 on Orin for P5-G-ORIN-TIMING
proxy_delta_ms:          # vs cpu-budget-proxy-k7.json
```

### Course / intervention snippet (leashed / free)

```text
course_id:               mixed-20min-v1
duration_s:
interventions:
minutes_per_intervention:
curb_stops_expected:
curb_stops_observed:
autonomous_road_entries: # must be 0
```

### Gate close record

```text
gate:        P5-G-…
result:      pass | fail | blocked
evidence:    run_id + bag_digest
ledger:      update hardware-readiness.md row → validated (do not delete history)
```

---

## Explicit non-claims (this stub)

- This document does **not** commission any device.
- No flash, purchase, or field run is implied by its existence.
- Sim-closed P0–P4 gates do **not** satisfy any checkbox above.
