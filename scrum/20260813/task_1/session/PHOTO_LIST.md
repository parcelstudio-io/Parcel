# Photograph list — what to shoot, from where, and why

> **Blank by design.** No photograph has been taken. This is a shot list to be
> worked through **at** the session.

**Card:** PS-F, tranche PS-1 · **Written:** 2026-08-13
**Belongs to:** [STAGE0_RUN_SHEET.md](STAGE0_RUN_SHEET.md) §11 ·
[MOUNT_GEOMETRY_SHEET.md](MOUNT_GEOMETRY_SHEET.md)

Photographs are the cheapest evidence in the building and the only evidence
that survives a disk failure, a wrong flag, a mis-transcribed number, and a
disassembled rig. They are the **backup for the one unrecoverable quantity**:
if the tape numbers turn out to be ambiguous, an orthographic photo set with a
scale reference in frame can still recover the mount geometry approximately.
Numbers without photographs are unfalsifiable.

---

## 0 · Before the first shot — four things, two minutes

1. **Clock tie.** Photograph a screen showing the capture host's clock
   (`date -u`) as your **first frame**. Then every later photo's EXIF time is
   tied to the session's host clock, and to PS-C's clock map through it.
   Without this, photo timestamps are a third, unmapped epoch.
   ```text
   host clock photographed at:  ______ UTC     phone clock read: ______ UTC
   phone_minus_host offset:     ______ s   (write it down; do not "fix" the phone)
   ```
2. **Run card in frame.** Write `run_id` on a card and put it in at least the
   first, middle, and last frame of the set.
3. **Scale reference.** A steel rule or a tape held in-plane, in every
   geometry shot (P06–P10, P16). A photo without a scale cannot recover a
   dimension.
4. **Lighting and focus.** Labels are the point of half these shots. If the
   serial is not legible when zoomed, the shot failed — check on the spot,
   not at home.

---

## 1 · The shot list

**MANDATORY** shots are required **in every branch**, including
`DEGRADE-MMP` (record nothing) and `ABORT-SAFETY`. They cost minutes and are
the difference between "we have to do the day again" and "we have it".

| ID | Subject | Shoot from | Why — what it is evidence for | Branch |
|---|---|---|---|---|
| **P01** | Go2 EDU label / serial plate, legible | close, square to the label | Attestation cross-check (PS-D reads it over DDS; this proves what the *unit* says). Run header `device_ids`. BOM receipt log. | **MANDATORY** |
| **P02** | **Built-in LiDAR model label**, legible | close, square | **Settles the L1-vs-L2 contradiction** (`P5_PROCUREMENT_BOM.md:75` says L1, the vendor says L2). No software required. If one shot is taken all day, this is a candidate. | **MANDATORY** |
| **P03** | D455 label — serial + part number | close, square | `device_ids`, and the D455 model determines the intrinsics/extrinsics you later pull from the datasheet | **MANDATORY** |
| **P04** | Add-on L2 label — serial, and its firmware if shown on a screen | close, square | Second LiDAR identity; `unilidar_sdk2` version pairing | **MANDATORY** |
| **P05** | Orin NX module + carrier labels; JetPack version on screen (`cat /etc/nv_tegra_release`) | close; screen shot for the version | Precondition P2 is **waived** — the JetPack version is an *observation*, and this photo is the observation | **MANDATORY** |
| **P06** | Whole rig, **front elevation**, square on, scale in frame | tripod height ≈ rig height, 1.5–2 m away, camera axis horizontal | Orthographic recovery of lateral + height offsets if the tape numbers fail | **MANDATORY** |
| **P07** | Whole rig, **left elevation**, square on, scale in frame | as P06, from the dog's left | Recovery of forward + height offsets, and sensor pitch | **MANDATORY** |
| **P08** | Whole rig, **right elevation**, square on, scale in frame | as P06, from the dog's right | Left/right asymmetry — catches a bracket mounted off-centre | **MANDATORY** |
| **P09** | Whole rig, **plan (top-down)**, scale in frame | directly above, camera axis vertical | Yaw and lateral offsets; the view the side elevations cannot give | **MANDATORY** |
| **P10** | Each sensor mount close-up: bracket, fasteners, contact faces (3 shots: D455, built-in LiDAR, L2) | 200–400 mm, two angles each | Rebuild the identical rig later; and a before/after comparison that can reveal loosening | **MANDATORY** |
| **P11** | Cable routing, full path, each cable end to end | wide enough to see the whole run; 2–3 shots | Strain-relief evidence for pre-stand gate S3/S4; reassembly; incident reconstruction | **MANDATORY** |
| **P12** | Every connector, seated and latched (D455 USB-C, L2 Ethernet/ACM, Orin power) | close | S6. The silently-unseated USB-C is the classic mid-session data loss | **MANDATORY** |
| **P13** | Payload underside / how it attaches to the trunk | low angle or dog on its side, powered **off** | S1 payload-security evidence; mass distribution | **MANDATORY** |
| **P14** | **Both stops in one frame**, with their labels | close enough to read the labels | Checklist precondition P4 asks for "serials + photo". This is that photo. Also proves the two stops are physically distinct devices. | **MANDATORY** |
| **P15** | The workspace: mat, clear radius, obstacles, where each person stood | from a corner, wide | Incident reconstruction; and it records the environment the sensor data was taken in — geometry the bag cannot describe | **MANDATORY** |
| **P16a** | The `base_link` datum cross marked on the trunk | close, square, with scale | **Makes every geometry number re-derivable.** Without it the derived column is unverifiable | **MANDATORY** |
| **P16b** | Tape in position for each measured offset (one per key: A1, A3, B3, C1, C3, D1) | along the tape's axis, reading legible | A later reader can **check** an offset instead of trusting it. This is the audit trail of the unrecoverable quantity | **MANDATORY** |
| **P17** | Teardown: M2 re-measure in progress; then the bracket after removal | as P16b; then close on the bracket + contact faces | Proves M2 happened while assembled; witness marks show whether it shifted | **MANDATORY** |
| **P18** | Screen: the attestation report, the budget refusal (if any), the recorder's final summary | straight on, whole terminal legible | Evidence that survives loss of the Orin's disk. **Especially valuable in DEGRADE-MMP, where the failing report is the deliverable** | **MANDATORY** |
| **P19** | Every filled sheet in this pack, page by page | flat, square, well-lit | The handwriting is the primary record; digitise it before it is folded into a bag | **MANDATORY** |
| P20 | The dog seated with the rig, "hero" shot | wherever it looks right | Not evidence. Take it anyway — this is the first physical session. | optional |
| P21 | Anything that surprised you | — | The thing you photograph because it is odd is the thing you will want in three weeks | optional |

---

## 2 · If the dog is standing (Stage-1 boundary crossed)

| ID | Subject | Why | Branch |
|---|---|---|---|
| P22 | Rig **standing**, left elevation, scale in frame | The sensor heights the bag actually saw are the *standing* heights, not the seated ones. §5 of the geometry sheet measures the rig; this photo records the posture it recorded in. | MANDATORY **if standing** |
| P23 | Standing height measurement in progress (trunk top to floor) | Ties the seated datum to the standing posture; the offset between them is otherwise unrecoverable | MANDATORY **if standing** |
| P24 | Video (not a still) of one stop press from a stand | The drop is fast; a still cannot show damping behaviour. 60 fps if the phone offers it. | MANDATORY **if standing** |

```text
standing trunk-top height above floor:  ______ ± ____ mm
seated  trunk-top height above floor:  ______ ± ____ mm
```

---

## 3 · Offload rule

- [ ] Photos copied off the phone **before leaving the session** — to the same
      second physical device as the bag
- [ ] Count checked against this list; every MANDATORY row has at least one file
- [ ] Album/directory id written into the run header `photo_set_ref`
- [ ] Any illegible label **re-shot on the spot**, not noted as a to-do

```text
photo_set_ref: ____________________  file count: ______
MANDATORY rows covered: ____/20      (+ ____/3 more if the dog stood: P22–P24)
```

---

## 4 · What a photograph does not prove

- Nothing here has been shot. This is a list, not a record.
- A photograph proves an object existed in an arrangement at a moment. It does
  **not** prove a fastener was torqued, a connector was electrically good, or
  a sensor was producing data.
- Orthographic recovery from P06–P09 is a **fallback with metres-of-doubt**,
  not a substitute for the tape sheet — perspective, lens distortion, and an
  unlevel camera all bite. Use it only if the tape numbers are lost.
- EXIF times are only as good as the §0 clock tie. Without that first frame,
  they are an unmapped epoch — exactly the failure PS-C exists to prevent.
