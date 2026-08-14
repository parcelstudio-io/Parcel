# Session pack — first physical session, Stage 0 dry-run

> **Nothing in this folder has been executed.** Every sheet is blank by design
> and is filled **by hand, at the session, by the operator**. A folder full of
> empty boxes is the correct state of this pack until the day happens.

**Card:** PS-F, tranche PS-1 · **Written:** 2026-08-13 · **Author:** Fable (PS-F)
**Session:** the day after this pack was written — first physical session on
Go2 EDU + add-on Unitree L2 + RealSense D455 + Jetson Orin NX (recording
onboard).
**Superseding authority:** [../PHYSICAL_SESSION_PLAN.md](../PHYSICAL_SESSION_PLAN.md)
**Instantiates:** [`P5_COMMISSIONING_CHECKLIST.md:91-109`](../../../20260805/task_1/P5_COMMISSIONING_CHECKLIST.md)
— Stage 0 only. That checklist is the ratified artifact; this pack does not
replace it, does not add checkboxes to it, and does not close any of its
later stages.

---

## The pack — print all four, in this order

| # | Sheet | When it is filled | If you only do one thing |
|---|---|---|---|
| 1 | [SAFETY_BRIEF.md](SAFETY_BRIEF.md) | read aloud **before power**, signed at §7 | two people, mat down, hands out of the leg envelope |
| 2 | [MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md) | **while the rig is assembled**, and again at teardown | **this one.** It is the only quantity that cannot be recovered later |
| 3 | [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) | throughout; it drives the day | fill the run header before you power anything |
| 4 | [PHOTO_LIST.md](PHOTO_LIST.md) | throughout; offload before leaving | P02 — the built-in LiDAR's model label |

---

## Order of operations

```text
  T-30   Read PS-A…PS-E status docs. Transcribe the exact commands into
         STAGE0_RUN_SHEET §3. An untranscribed command is a NOT MEASURED.
  T-20   Rehearsal (PS-E) runs green on the Orin against synthetic publishers.
         The stack's first run must not be on the dog.
  T-10   Safety brief read aloud and signed. Roles named. Mat down.
   T-0   Dog OFF: mount the rig, MEASURE the geometry (M1), photograph.
         ── this much is a successful session even if nothing else happens ──
   +30   Preconditions ruled (run sheet §4). Stops verified (§5). Dog powered,
         SEATED. Preflight + attestation + budget (PS-D, PS-E).
   +45   GO / NO-GO (§6). One of three branches, two of which are successes.
   +50   Clock map running (PS-C) ── if this is not running, the bag's
         cross-device timestamps are permanently unrecoverable.
   +55   Record (PS-B). Stop tests pressed WITH THE RECORDER RUNNING.
  (opt)  Pre-stand gate (§8) → second stop verification (§9) → stand / sit.
   END   M2 re-measure BEFORE loosening a bolt. Offload. Sign off (§11).
```

---

## Three outcomes, two of them successes

| Branch | Trigger | What it produces |
|---|---|---|
| **GO-RECORD** | attestation, firmware pin, channels, budget, rehearsal, stops — all pass | the full dataset: MCAP + `parcel.bag.v1` sidecar + clock map + attestation + geometry + photos |
| **DEGRADE-MMP** | attestation fails · firmware < 1.1.13 · budget fails · rehearsal not green · fewer than two people | **mount, measure, photograph, record nothing.** Geometry + photographs + the failing attestation. Costs a later session nothing, because it captures exactly what a later session could not recover. **A legitimate outcome, not a failure.** |
| **ABORT-SAFETY** | stops fail · payload not securable · cable not relievable · injury or near-miss | dog off, then the DEGRADE-MMP deliverables with the dog off |

---

## Traceability — every Stage-0 checkbox has a named producer

The seven rows are the verbatim checkboxes of
`P5_COMMISSIONING_CHECKLIST.md:101-107`. **No orphans**: each is produced by a
PS-A…PS-E artifact, by an explicit operator action, or is explicitly deferred
with a named consequence.

| Checkbox (`checklist:` line) | Producer | Artifact / action | Sheet |
|---|---|---|---|
| `:101` Dock compose stack boots; safety+control container has zero network deps | **DEFERRED** | no golden image flashed; one dock only (§4 P2/P3) ⇒ **P5-G-INSTALL cannot close**, HR-9 stays unvalidated | run sheet §7 C0.1 |
| `:102` Clock / TF / DDS segment firewalled; remote = tailnet only | **PS-C** + operator | `scripts/parcel_capture/clockmap.py` (`ClockMapV1`); firewall = operator action; NIC/DDS domain from PS-D. **TF: not applicable — Parcel has no TF; the measured extrinsic is the substitute** | run sheet §7 C0.2 + geometry sheet |
| `:103` Camera (D455) + LiDAR topics publish; bag recorder writes `parcel.bag.v1` | **PS-D** + **PS-B** | `preflight.py` per-channel `PRESENT`/`ABSENT`/`DEGRADED` over all 19 channels; `record.py` + `sidecar.py` | run sheet §7 C0.3 |
| `:104` Soft stop + both hardware e-stops trip the stop path ≤300 ms (measure) | operator + **PS-B** | vendor stop response recoverable from the bag (ch.8 press, ch.5/6 response). **Parcel software stop-path latency: NOT MEASURABLE — nothing armed** | run sheet §5, §7 C0.4 |
| `:105` Comms-loss auto-damp demo once | operator + **PS-B** | link cut, recorded; PARTIAL if the dog never stands | run sheet §5 E3, §9 E3′, §7 C0.5 |
| `:106` Runtime refuses Sport arm without commissioning record | operator, **read-only** | D1 absent `unitree_sdk2py` · D2 config inspection · D3 `tests/test_portability_proof.py`. **No arm is attempted.** | run sheet §7 C0.6 |
| `:107` Evidence: run ID `P5-DRY-…`, bag digest, latency snapshot → fill template below | this pack + **PS-B/C/D** | run header §1; digests from sidecar, clock map, attestation | run sheet §1, §11 |
| Rule `:86-88` dual e-stop + comms-loss re-verified at **every** stage entry | operator | verified at Stage-0 entry (§5) **and again** at the Stage-1 boundary before any stand (§9) | run sheet §5, §9 |
| Preconditions `:63-73` P0–P6 | mixed | ruled individually; P2/P3 waived/unmeetable with named consequences | run sheet §4 |

> **Line-number note.** The 2026-08-13 supersession banner shifted every
> line of `P5_COMMISSIONING_CHECKLIST.md` downward (Stage 0 moved from
> `:51-61` to `:91-109`; the dual-e-stop rule from `:46-48` to `:86-88`; the
> run header from `:119-133` to `:167-181`). The citations in this pack point
> at the file **as it stands now**. Citations written earlier —
> [`../README.md:210`](../README.md) and
> [`../PHYSICAL_SESSION_PLAN.md:88`](../PHYSICAL_SESSION_PLAN.md), both
> `:51-61` — refer to the **pre-supersession** file at base `406f9d6`. Same
> text, older coordinates. Neither of those documents was edited by this card,
> and the banner itself records the mapping.

---

## What this pack adds that the ratified checklist assumes

The checklist is a good artifact that presumes an assembled, safe rig. These
four things are what stand between it and a real day, and none of them exists
anywhere else in the repo:

1. **Mount geometry** — tape-measured D455 + **both** LiDAR offsets and
   orientations to `base_link`, with a datum you can realise with a tape, a
   raw-readings-win rule, an assembly *and* a teardown measurement, and a
   direct comparison against the extrinsic the simulator has been assuming
   unchecked (`camera_channel/d455.py:34-40`).
2. **Photographs** — 20 mandatory shots, including the one that settles the
   L1-vs-L2 contradiction in the repo, and the clock-tie frame that maps EXIF
   time onto the session's host clock.
3. **Mechanical safety before the dog stands** — payload pull test, cable
   strain relief within 100 mm of every connector, pinch sweep, padded mat,
   and the explicit acknowledgement that a stop press **drops** a standing dog
   with the payload on it.
4. **A named failure branch** — DEGRADE-MMP, so that a failed attestation or a
   blown budget produces a *successful geometry-and-photograph session*
   instead of a wasted day.

---

## What this pack does not prove

- **Nothing in it has been executed.** It is blank paperwork. Filling a box is
  not validation; the checklist said so from the start — *"Completing a
  checkbox here is not validation"*, preserved verbatim inside its own
  supersession banner at `P5_COMMISSIONING_CHECKLIST.md:9` — and that sentence
  is explicitly **not** superseded.
- It closes **no gate**. `P5-G-INSTALL` is expected to end the day **blocked**
  (no flash, one dock). `P5-G-BAG-DROPIN` closes only if real bags actually go
  through the `parcel.bag.v1` harness unchanged.
- It authorises **no motion beyond an operator-initiated stand and sit under
  the vendor handheld**, and nothing at all through Parcel.
- It says nothing about Stages 1–3. Those checkboxes are untouched and remain
  the ratified checklist's.
- A completed pack proves what happened on **one day, in one room, at one
  temperature, with one payload**. Every rate, every thermal number, and every
  timing figure in it is a single-sample observation.
- The two open safety findings (`runtime.py:5711-5712` latched-stop yaw leak;
  `pose.py:945-954` fabricated pose confidence) are **not** addressed here and
  are not reachable today only because nothing is armed.
