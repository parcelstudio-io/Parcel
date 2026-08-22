# OT-2 — pre-registration

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Executor:** Claude Opus ·
**Written:** 2026-08-22, BEFORE any row was measured and before any product
file was edited. Its sha256 is quoted in `OT2_STATUS.md`; a row that moves
after this file is written is a declared correction, not a re-registration.

---

## 0. The derivations, fixed here

### D-1 · `OWNER_IDENTITY_MARGIN_MIN = 0.005`

The reactive gate must not compare a **measured cosine** to a constant. The
gallery already made the identity decision at the place where the boundary was
*measured* (`AppearanceGallery.threshold`, the midpoint of the measured gap
between the owner's leave-one-out floor and the best negative). What the gate
needs is not a second opinion on the cosine but **how much headroom that
decision had**.

So the gate consumes `identity_margin` = `identity_score − gallery.threshold`,
the headroom above the producer's own measured operating point, and the floor
under it is derived — in advance, from a published measurement, not from this
card's fixtures:

> P1-C measured the gallery's own reproducibility at **2.02e-4**: two
> enrollments of the same six crops produced `negative_reference` 0.928006 and
> 0.928208 (fp16 CUDA nondeterminism, `P1C_STATUS.md` §6.6). A headroom smaller
> than the boundary's own reproducibility is noise, not evidence. Take an order
> of magnitude over it — 10 × 2.02e-4 = 2.02e-3 — and round **up** to the next
> 5e-3 grid point:
>
> **`OWNER_IDENTITY_MARGIN_MIN = 0.005`**

Declared now, before measurement: this floor is NOT fitted to P1-C's clip. If
the clip's owner headroom turns out to sit below it, that is a MISS and is
reported as one.

### D-2 · `OWNER_IDENTITY_CONFIDENCE_MIN = 0.65` is **retired on the cosine
scale** and **kept on the channel-prior scale**

0.65 was always a threshold on a channel *prior* — the fusion stub's hard-coded
trust in whichever channel supplied pose (0.55 UWB / 0.70 vision, ±0.10
corroboration). It stays exactly that, at exactly that value, for exactly those
tracks, because `follow.FollowConfig.min_confidence` and
`SearchOwnerConfig.owner_confidence_min` import it and a controller's
willingness to follow a weak *channel* is a different question.

It is never applied to a measured cosine. A track whose identity came from
pixels is judged on `state` + calibration + headroom, never on the number.

### D-3 · who may write a durable owner fact (DW-3, the memory principal)

| principal (P2-B's speaker label) | may propose | may create `granted` | may confirm a `pending` row |
|---|---|---|---|
| `owner` — verified against the enrolled voice | yes | **yes** | **yes** |
| `unenrolled` — there IS no check yet | yes | **yes** | **yes** |
| `unverified` — the check ran and abstained | yes (`pending`) | **no** | **no** |
| `not_owner` — verified, somebody else | yes (`pending`) | **no** | **no** |
| `ungated` — the emergency class | yes (`pending`) | **no** | **no** |

`unenrolled` grants, and that is a decision rather than an oversight: the
owner has not yet run `tools/enroll_owner_voice.py` (a pending owner action on
the board), the voice gate arms everything in that state anyway, and demoting
every memory on a stock install would be a new fail-closed default — forbidden
by this wave's rule 1. `unverified` is the row the card names and is the row
that must never grant.

A downgrade is never silent: the tool result carries
`consent_downgraded: true`, the principal, and a reason, and the runtime emits
a `realtime` note.

---

## 1. Pre-registered rows

Rows R1–R5 are **pure gate rows** — constructed `OwnerTrack`s, no encoder, no
GPU, exact. Rows R6–R7 run **through the runtime** on P1-C's two-person clip
with P1-C's deterministic fixture encoder. Rows R8–R10 run on a **scratch**
memory store; the owner's `parcel_memory.sqlite3` is never opened read-write.

| # | Row | Target, fixed now | Path |
|---|---|---|---|
| **R1** | a calibrated, confirmed owner claim with headroom ≥ 0.005 is trusted by the identity gate | trusted on **100 %** of such cases over a 41-point cosine grid (0.60→1.00 step 0.01) restricted to those clearing the floor | `_owner_identity_trusted` |
| **R2** | an **uncalibrated** pixel identity is never trusted, at any cosine — this is the stranger at 0.917 / 0.9295 | **0 of 41** trusted on the same grid with `identity_source="pixel_reid_uncalibrated"`, `state="confirmed"`, headroom 0.10 | `_owner_identity_trusted` |
| **R3** | the raw-cosine gate is gone | with `identity_source="pixel_reid"` and `state="ambiguous"`: **0 of 41** trusted. A 0.65 raw-cosine gate would trust **36 of 41** — that difference is the row | `_owner_identity_trusted` |
| **R4** | the gate keys on STATE, not the number | 4 states (`confirmed/ambiguous/lost/searching`) × 41 cosines = 164 cases: exactly **41** trusted, all of them `confirmed` | `_owner_identity_trusted` |
| **R5** | the mocap venue is unchanged | over a 648-case matrix (3 owner_id × 2 visible × 27 confidence × 2 person-channel × 2 orbit) the sha256 of `apply_reactive_safety`'s dispositions equals the pre-OT-2 tree's | `apply_reactive_safety` |
| **R6** | the running robot stops believing the owner at 1.0 | driving the clip through `RobotRuntime._publish_camera_frame`: the emitted `SimObservation.owner.confidence` takes **≥ 5 distinct values**, **max < 1.0**, and **0** frames are trusted by the gate while the tracker has not confirmed | runtime |
| **R7** | reacquisition degrades, never guesses | after `lost_after_s` with no person in frame the emitted track is `state="searching"`, `visible=False`, `confidence=0.0` on **100 %** of frames; **0** frames carry the last-known confidence | runtime |
| **R8** | unverified audio never creates consent-granted memory | 5 labels × 3 dispositions = 15 cases: exactly **2** produce a `granted` row (`owner`/`unenrolled` × `keep`); the other 13 produce `pending` or nothing, and **every** downgrade is reported in the result | `ToolDoors.remember_fact` |
| **R9** | `set_owner_fact_consent` has a product caller | exactly **1** product call path (broker `remember_fact(action="confirm")` → `ToolDoors.confirm_fact` → `memory.set_owner_fact_consent`), asserted by walking the call graph; a confirmed row moves `pending→granted` (**1** row) and then renders in `known_facts()` | broker → runtime → store |
| **R10** | repeating `remember_fact` is not confirmation | the same `ask`-class fact sent **3** times leaves `granted` count at **0**; a `confirm` from an `unverified` principal also leaves it at **0** | broker → runtime → store |

### Owner-gated (listed, never claimed)

| # | Row | Why gated |
|---|---|---|
| **G-1** | the calibrated-identity campaign: clothing / lighting / pose / occlusion / crossing / across-days | needs a camera **and** the owner's appearance enrollment; no camera on this host |
| **G-2** | the voice principal measured against a REAL enrolled voice | needs `tools/enroll_owner_voice.py` (1 min of the owner's voice) |

Exact commands go in `OT2_STATUS.md` §7.

---

## 2. Seeded RED — one per new guard

Every seed is applied to a **byte-identical scratch copy of `src/`**, the named
test is watched to fail, and the copy is discarded. The product tree is never
seeded.

| # | Seed (in the PRODUCT) | Test that must go RED |
|---|---|---|
| **S1** | `_ot2_apply_owner_identity` re-emits a constant `confidence=1.0` for a confirmed pixel track | `test_ot2_the_runtime_never_emits_a_constant_owner_confidence` |
| **S2** | `_owner_identity_trusted`'s measured arm restored to `confidence >= OWNER_IDENTITY_CONFIDENCE_MIN` (a raw-cosine gate) | `test_ot2_a_measured_identity_is_never_judged_on_the_raw_cosine` |
| **S3** | `pixel_reid_uncalibrated` admitted to the calibrated set (the stranger at 0.917) | `test_ot2_an_uncalibrated_gallery_can_never_grant_the_owner_band` |
| **S4** | `may_grant_consent` returns True for the `unverified` principal | `test_ot2_unverified_audio_never_creates_granted_memory` |
| **S5** | the remember door promotes a `pending` row to `granted` on a repeat | `test_ot2_repeating_remember_fact_is_not_confirmation` |

---

## 3. What is NOT claimed, decided in advance

* Nothing here has seen a real person or a real camera (P1-C's limit, inherited
  whole). The clip is synthesized and the encoder used for R6/R7 is P1-C's
  deterministic fixture encoder, not SigLIP-2 — the numbers 0.917 / 0.9295 /
  0.9591 are P1-C's published real-encoder measurements and are used here as
  **direct inputs to the gate rows**, never re-derived.
* `0.005` is a floor on headroom, not an operating point for anything.
* The memory principal is derived from P2-B's voice label. A typed owner in the
  panel, and the local (non-hosted) agent, carry no voice label — the rows say
  which principal each path produces.

---

## 4. Gates that must stay green

`ruff` on the touched files with the ratchet at exactly **7** (none added, no
`noqa`, no re-pin); the targeted pytest set named in the status doc; the
reactive-safety AST ratchet — with **only `_owner_identity_trusted` moved** and
its regeneration logged in `tests/test_dynamic_layer.py`'s log, as P1-E did.
