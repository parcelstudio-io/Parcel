# OT-2 — the running robot stops believing the owner at 1.0 · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Design:**
`../WAVE2_DESIGN_FABLE.md` §1 (DW-3) · **Executor:** Claude Opus ·
**Verifier:** Fable · **Date:** 2026-08-22 · **Verdict:** ACCEPT with
corrections (Fable), corrections applied — **§12**. All 10 pre-registered rows
MET; one HALT-item (pixels on the live camera path); five declared deviations;
six seeded REDs.

**Pre-registration:** `PREREGISTRATION.md`, sha256
`f0ac2c6c8132af76856dac19bbe88895911cf2e147714155f33151d7ed0712a3`, written
before any row was measured and before any product file was edited.

---

## 0. FIRST, FOR DOOR-1: the envelope seam did not change shape

DOOR-1 (`task_19`) reads `navigation/reactive_safety.py` read-only while this
card is being written, and the card told me to say this first if the shape
moved. **It did not.**

* `OWNER_IDENTITY_CONFIDENCE_MIN` — same name, same value (**0.65**), same
  meaning. `FollowConfig.min_confidence` and
  `SearchOwnerConfig.owner_confidence_min` still equal it, and a test asserts
  all three (`test_ot2_publishes_the_identity_seam_without_moving_what_door1_reads`).
* `OWNER_STAND_OFF_MARGIN_M` — untouched (0.10 m).
* `ReactiveSafetyPolicy` — no field added, removed or renamed by this card.
  Its `__post_init__` DID move on this working tree; that is **DOOR-1's own**
  regeneration, logged one entry above mine in `tests/test_dynamic_layer.py`.
* Everything OT-2 adds is **additive**, inside one marked region
  (`# ---- CARD OT-2: THE PUBLISHED IDENTITY SEAM. DOOR-1 READS THIS. ----`),
  and is safe to depend on: `IDENTITY_SOURCE_*`, `MEASURED_IDENTITY_SOURCES`,
  `CALIBRATED_IDENTITY_SOURCES`, `CHANNEL_PRIOR_IDENTITY_SOURCES`,
  `OWNER_IDENTITY_TRUSTED_STATES`, `OWNER_IDENTITY_MARGIN_MIN`, and
  **`owner_identity_trusted`** — the decision itself, published as a public
  *alias* of the pinned `_owner_identity_trusted` (an alias and not a wrapper,
  so the logic stays inside the symbol `REACTIVE_SAFETY_PIN` watches). Ask it
  rather than re-deriving a threshold: the threshold is no longer the rule.

The one behaviour change is inside `_owner_identity_trusted`. **Its direction,
measured** (7,650 cases against the pre-OT-2 rule): **1,314 newly refused, 66
newly granted, 6,270 unchanged**. The first version of this document said
"strictly fewer" in three places and that was false — see §12.4. All 66 grants
are one narrow shape (`pixel_reid` + `confirmed` + headroom ≥ 0.005 + a cosine
**below** 0.65), and what they buy is the relaxed comfort **band** only. No stop
distance, comfort-band value, predictive stop, TTC brake, orbit gate or obstacle
path is reachable from this predicate.

---

## 1. Headline

The audit's finding is retired on the product path. `headless_city.py:370`'s
literal `1.0` no longer arrives as an unexplained float, and under a camera
venue the control loop's owner track is **replaced** by P1-C's measured one
before anything reads it — the reactive gate, the follow controller, the orbit
gate and P2-B's greeting watcher all see one identity.

**And the threshold was not merely moved, it was retired on the scale it could
not answer.** `OWNER_IDENTITY_CONFIDENCE_MIN = 0.65` was always a floor on a
*channel prior*; on the cosine P1-C actually produces it is met by every
person-shaped crop in the room (P1-C measured a **stranger at 0.9295** against
the owner's own gallery). `_owner_identity_trusted` now branches on
`OwnerTrack.identity_source`:

| the number is… | judged on |
|---|---|
| a MEASURED cosine (`pixel_reid*`) | the producer's `state` (`confirmed` only) **+** whether its boundary was calibrated against a known non-owner **+** the HEADROOM the claim had above that boundary (≥ **0.005**, derived) |
| a CHANNEL PRIOR (`""`, `mocap_ground_truth`, `channel_prior`) | `confidence ≥ 0.65`, byte-identically to before |
| anything else | not an identity |

**Measured, on the gate:** an uncalibrated gallery is trusted **0 of 41** times
at any cosine; a calibrated-but-ambiguous claim is trusted **0 of 41** where the
old raw-cosine gate would have trusted **36 of 41**; across 4 producer states ×
41 cosines exactly **41 of 164** are trusted and every one is `confirmed`.
**Measured, on the legacy path:** 648 reactive-safety dispositions over tracks
with no identity provenance hash **byte-identically** to the pre-OT-2 tree
(`f16316b3…`). **Measured, through the runtime:** P1-C's two-person clip driven
through `RobotRuntime._publish_camera_frame`, scoring the **held-out** frames
6–19 as the clip's own header requires, yields an owner confidence that takes
**10 distinct values over 10 confirmed frames, max 0.999915 < 1.0**, and is
trusted by the gate on exactly the frames the tracker confirmed. On a lost owner
the emitted track degrades to `searching` / `confidence 0.0` — **and keeps
`visible`**, because presence is not identity's to delete (§12.1): a degraded
owner at 0.7 m still returns `stopped`.

**The memory-principal half (DW-3) landed too.** `owner_model.principal` is a
typed principal on the durable-fact write path: an `unverified` or `not_owner`
voice may talk, may interrupt, may STOP the dog — and cannot create a
consent-granted memory. Measured through the runtime's **real hosted broker**
over a 5 label × 3 disposition matrix: exactly **2 of 15** cells produce a
`granted` row, and no downgrade is silent. And
`ConversationMemory.set_owner_fact_consent`, which had **exactly one caller in
the whole tree and it was a test**, now has a product caller:
`remember_fact(action="confirm")` → `ToolDoors.confirm_fact` →
`RobotRuntime._ot2_confirm_fact`. Repeating `remember_fact` three times leaves
`granted` at **0**.

**Six seeded REDs, one per new guard**, each on a byte-identical scratch copy
of `src/`, each reddening its named test.

**Rows: 10 of 10 MET.** R6 was reported as a partial miss in the first version
of this document; the miss was an artefact of scoring the *enrollment* frames,
not of the encoder, and the pre-registered assertion now passes as written
(§4.1, §12.3). Two rows are owner-gated and are listed with commands in §7,
never claimed.

---

## 2. What changed

`git diff -U0` per file, after the correction pass (§12), with each hunk
attributed by whether its added lines carry this card's marker. Five of these files are being edited by other wave-2
executors **right now**; the "other cards" column is their in-flight work,
which was not touched, not reverted and not counted.

| file | OT-2 (+/−) | other cards (+/−) | what |
|---|---|---|---|
| **new** `src/parcel_robot/owner_model/principal.py` | +304 / −0 | — | the typed memory principal and the one rule |
| **new** `tests/test_ot2_identity.py` | +963 / −0 | — | 22 tests: the gate, the seam, the runtime rows, the safety row |
| **new** `tests/test_ot2_memory_principal.py` | +554 / −0 | — | 34 tests: the principal matrix, the confirm door, who-spoke |
| `src/parcel_robot/runtime.py` | **+619 / −2** | +909 / −1 | two marked regions + three one-line seams |
| `src/parcel_robot/realtime/tool_broker.py` | **+181 / −3** | +167 / −2 | `FACT_ACTION_CONFIRM`, the fourth door, the downgrade arm |
| `src/parcel_robot/navigation/reactive_safety.py` | **+163 / −1** | +60 / −5 | the published seam, the public alias, the re-derived gate |
| `src/parcel_robot/backends/base.py` | +51 / −0 | 0 / 0 | `OwnerTrack.state` / `.identity_source` / `.identity_margin` |
| `src/parcel_robot/headless_city.py` | +33 / −1 | 0 / 0 | the mocap emission, named and stamped |
| `tests/test_dynamic_layer.py` | +75 / −1 | +1 / −1 | the AST-ratchet regeneration + its log entry |
| `scrum/20260822/task_17/` | — | — | `PREREGISTRATION.md`, this file |

Attribution script: `/home/jaewoo-jang/.cache/parcel-ot2/share.py`. Every edit
to an existing file was an exact-match, single-occurrence replacement applied
against the file **as re-read at that moment**; every patch script asserts on 0
or >1 matches and writes nothing on failure (two did, and were corrected rather
than forced). No `git add/commit/stash/checkout/reset/restore` was run.

### 2.1 The regions and the seams

`runtime.py` carries **two** marked OT-2 regions and **three** one-line seams,
following P1-B's convention in the same file:

* `# CARD OT-2 — THE ROBOT STOPS BELIEVING THE OWNER AT 1.0. (NEW REGION)` —
  `install_owner_tracker`, the `owner_track` property, `_ot2_note_camera_frame`,
  `_ot2_publish_update`, `_ot2_apply_owner_identity`, `_ot2_latest_rgb`,
  `owner_identity_snapshot`;
* `# CARD OT-2 — WHO MAY WRITE A DURABLE OWNER FACT. (NEW REGION, DW-3)` —
  `_ot2_memory_principal`, `_ot2_remember_fact`, `_ot2_confirm_fact`,
  `memory_principal_snapshot`;
* seam 1 in `_publish_camera_frame` (the frame reaches the tracker, on the
  camera worker thread, after `_camera_stream_lock` is released and after
  P1-B's map feed);
* seam 2 in `_control_loop_body` (the overlay, one line after
  `backend.observe()` and before every reader);
* seam 3 in the `ToolDoors(...)` construction (`remember_fact=` rewrapped,
  `confirm_fact=` added).

**No new lock.** R24's roster (`tests/test_r24_lock_discipline.py`) asserts the
lock list is complete against an AST scan, so a new `threading.Lock` would
redden it. The tracker runs under **no** lock — it is single-threaded by
construction and driven from exactly one place — and only the finished
`OwnerTrackV1` is published under the runtime's existing `_lock`, taken alone.
`test_r24_lock_discipline.py` is green (30 tests).

---

## 3. The derivation, and why it is not a tuned constant

The card's binding instruction was *do NOT key it on the raw number*. The
gallery already made the identity decision **at the place where the boundary
was measured**; what the gate needed was not a second opinion on the cosine but
how much headroom that decision had.

`OwnerTrack.identity_margin` therefore carries `identity_score −
gallery.threshold` — headroom above the producer's own operating point, which
the runtime computes because the runtime is the one object that holds both the
track and the gallery. (It is deliberately **not** the same quantity as
`owner_tracking.PixelOwnerTrack.identity_margin`, which is best-minus-runner-up
between people in frame; both docstrings say so, and the tracker's own margin
still guards the `ambiguous` case upstream.)

The floor under it, pre-registered before measurement (`PREREGISTRATION.md`
D-1):

> P1-C measured the gallery's own **reproducibility** at 2.02e-4 — two
> enrollments of the same six crops gave `negative_reference` 0.928006 and
> 0.928208 on fp16 CUDA. A headroom smaller than the boundary's own
> reproducibility is noise, not evidence. 10 × 2.02e-4 = 2.02e-3, rounded up to
> the next 5e-3 grid point ⇒ **0.005**.

It is a noise floor, not an operating point, and it was not fitted: the clip's
own owner headroom (0.0148–0.0351 against P1-C's 0.9591 threshold) sits three
to seven times above it, which is a check on the derivation rather than its
source. On the CPU fixture encoder the same clip's calibrated threshold lands at
0.6399 and the owner's headroom at 0.2109-0.3601 — a different encoder with a
different scale, reported so nobody reads the fixture's comfortable margin as
evidence about SigLIP-2's narrow one.

**0.65 is retired on the cosine scale IN THE IDENTITY GATE, and kept on the
channel-prior scale.** Retiring the symbol outright would have been worse than
useless: `follow.py` and `search_owner.py` import it to answer a genuinely
different question ("how weak a *channel* will this controller act on"), and
moving it there would have changed follow behaviour for a UWB-only build that
this card never measured.

**CORRECTION (Fable, item 2).** The first version of this section said 0.65 "is
never applied to a measured cosine". **That is false**, and it became false the
moment the overlay started feeding a cosine to the whole control loop:
`follow.py:657`, `:701`, `:1082` and `search_owner.py:582` still threshold
`owner.confidence` at 0.65, and they now receive P1-C's cosine. The accurate
statement is: **the identity gate no longer applies it to a measured cosine; two
motion controllers still do.**

The measured consequence, pinned as an executable assertion in
`test_ot2_the_follow_and_search_admissions_still_read_the_raw_cosine`: a
calibrated gallery reporting `ambiguous` at 0.85 — "two people, I cannot tell
them apart" — is **refused** by the identity gate and **accepted** by the follow
controller. The dog declines to grant the owner band and then walks after them
anyway. P1-C's stranger at 0.9295 from an uncalibrated gallery does the same.

**Not fixed here, deliberately.** `follow.py` is DOOR-1's file this wave and
`search_owner.py` is also under concurrent edit; changing either would be
editing another executor's region mid-flight, which the board forbids. The
one-line patch and the seam to use are in §10 handoff 3, and the gap is written
as a test that *asserts it exists*, so closing it reddens this file and the
handoff gets struck rather than quietly rotting.

---

## 4. Pre-registered rows, measured

Rows R1–R5 are exact, over constructed tracks (no encoder, no GPU). R6–R7 run
through the runtime on P1-C's clip with P1-C's deterministic fixture encoder.
R8–R10 run through the runtime's **real** `RealtimeToolBroker` against a
scratch SQLite store.

| # | Target (fixed in advance) | Measured | Verdict |
|---|---|---|---|
| R1 | calibrated + `confirmed` + headroom ≥ 0.005 trusted on 41/41 grid points | **41 / 41** | **MET** |
| R2 | uncalibrated pixel identity trusted 0/41 at any cosine | **0 / 41** | **MET** |
| R3 | calibrated-but-`ambiguous` trusted 0/41; a raw 0.65 gate would trust 36 | **0 / 41**; raw gate = **36 / 41** | **MET** |
| R4 | 4 states × 41 cosines = 164 cases, exactly 41 trusted, all `confirmed` | **41 / 164**, all `confirmed` | **MET** |
| R5 | 648-case disposition sha equals the pre-OT-2 tree's | `f16316b33b5c4899513a1cd1c9f628def58b10091202d1e9f4be15f30001982c` both sides | **MET** |
| R6 | through the runtime: ≥ 5 distinct confidences, **max < 1.0**, 0 trusted while unconfirmed | **10 distinct** over 10 held-out confirmed frames; **max 0.999915 < 1.0**; **0** trusted while unconfirmed | **MET** (was mis-scored; §4.1) |
| R7 | after loss: identity degrades to `searching` / `0.0` on 100 % of frames, 0 guesses | **100 %**, 0 guesses; presence carried, and a degraded owner at 0.7 m still returns `stopped` | **MET** (as corrected, §12.1) |
| R8 | 5 labels × 3 dispositions: exactly 2 `granted`, every downgrade reported | **2 / 15**; every downgrade carries `consent_downgraded`, the principal and a reason | **MET** |
| R9 | exactly 1 product caller for `set_owner_fact_consent`; a confirm moves 1 row and it then renders | callers over the whole package = `["runtime.py:_ot2_confirm_fact"]`; 1 row `pending→granted`; renders in `known_facts()` | **MET** |
| R10 | 3 repeats leave `granted` at 0; an `unverified` confirm also leaves it at 0 | **0** and **0** | **MET** |

### 4.1 R6, and the mistake that made it look like a miss

The first version of this document reported R6's "max < 1.0" as a **declared
MISS**, attributed to the fixture encoder self-matching. **Both halves were
wrong**, and Fable caught it (item 3).

`_drive_clip` scored all twenty clip frames. The clip's own header says:

> *"Frames 0-5 are the enrollment set; identity rows are measured on 6-19 so no
> cosine is a crop against itself."*

So the six exact-1.0 values were **enrollment crops compared with themselves** —
the gallery scoring its own inputs. The encoder does not self-match, measured
independently before accepting the correction: over all 16 visible owner crops,
pairs of **different** frames at exactly 1.0 = **0**, max off-diagonal cosine
**0.9999731**, and 15 of 16 crops have distinct pixel heights.

Fixed by feeding every frame (the robot does not get to skip frames — this is
P1-C's own protocol) and **scoring only the held-out 6–19**, with an added
assertion that no enrollment index can appear in the scored rows. The
pre-registered assertion is restored verbatim. Measured:

**10 distinct confidences over 10 held-out confirmed frames — 0.850819,
0.909637, 0.910424, 0.946207, 0.967681, 0.980573, 0.988236, 0.999811, 0.999906,
0.999915 — max 0.999915 < 1.0.** R6 is **MET** as written.

**The practice note, kept because it is the most useful thing in this document.**
A pre-registered assertion was weakened, and the justification was a
cause-shaped sentence that had never been measured. That is worse than a plain
miss: a plain miss is visible, and a plausible explanation is load-bearing
camouflage. The rule this card should have followed, and now has: **if a
pre-registered row fails, the cause must itself be measured before anything is
rewritten** — and if the cause is measured, it usually turns out to be the
harness.

## 5. How it was verified — exact commands

`TMPDIR` unset throughout. `.parcel/bin/python`, `.parcel/bin/ruff`.

```bash
# the two new files
.parcel/bin/python -m pytest -q tests/test_ot2_identity.py tests/test_ot2_memory_principal.py
# -> 51 passed

# everything the change can reach, targeted
.parcel/bin/python -m pytest -q \
  tests/test_ot2_identity.py tests/test_ot2_memory_principal.py \
  tests/test_e6_owner_band.py tests/test_dynamic_layer.py \
  tests/test_p1c_owner_fusion_seam.py tests/test_p1c_owner_tracker.py \
  tests/test_p1c_owner_gallery.py tests/test_p2a_owner_model.py \
  tests/test_p2a_memory_probes.py tests/test_p2b_owner_awareness.py \
  tests/test_c1_camera_stream.py tests/test_r24_lock_discipline.py
# -> 503 passed

.parcel/bin/python -m pytest -q \
  tests/test_realtime_tool_broker.py tests/test_realtime_answer_beat.py \
  tests/test_realtime_voice_identity.py tests/test_realtime_prompting.py \
  tests/test_backends.py tests/test_contracts_v1.py \
  tests/test_headless_city_tasks.py tests/test_w0a_physical_provenance.py \
  tests/test_e2_safety_wiring.py
# -> 351 passed, 1 xfailed

.parcel/bin/python -m pytest -q \
  tests/test_runtime.py tests/test_runtime_activation.py \
  tests/test_follow_formation.py tests/test_search_owner.py \
  tests/test_person_aware_nav.py tests/test_arrival_semantics.py \
  tests/test_owner_estop.py tests/test_nominal_stop_wiring.py \
  tests/test_follow_prediction.py tests/test_prototype_profile.py \
  tests/test_import_order_no_cycle.py
# -> 266 passed, 2 failed — BOTH belong to other cards, see §5.1

.parcel/bin/ruff check <the 8 OT-2 files>
# -> All checks passed!
```

**Ruff ratchet.** `ruff check . --output-format=json` yields **15**
fingerprints on this working tree at the end of the correction pass (it was 12
at the end of the first pass — the set moves as other executors work). Seven
are the pinned baseline (`scripts/ci_ruff_baseline.json`, unchanged, not
re-pinned). Every non-baseline fingerprint is in another card's in-flight files
— `tests/test_duplex1_*` earlier, `scrum/20260822/task_18/evidence/*` now.
**OT-2 contributes zero**, at both measurements, and its nine files are
individually clean (`ruff check` on them: "All checks passed!").

`noqa` count, corrected (Fable, item 6): this card added **four**, not two, and
all four are the `# noqa: BLE001` the house convention requires on a
never-raise-into-the-loop handler, matching every neighbouring seam in the same
file — `_ot2_memory_principal` ("a principal may never end a turn"),
`_ot2_latest_rgb` ("the eye may never end a frame"), `_ot2_note_camera_frame`
and `_ot2_publish_update` (both "never break the camera worker"). No other
suppression of any kind was added.

### 5.1 The two failures in this tree that are NOT OT-2's

Both reproduce with OT-2's own files reverted out of the picture and neither
touches anything this card owns:

* `test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival`
  — `navigate_to`'s schema grew a `confirm` property. That is **ASK-1**
  (`task_18`): `CONFIRM_KEY`, `CONFIRM_TOKEN_KEY` and
  `uncertain_place_confirms` are its added lines in `tool_broker.py`. OT-2's
  own schema edit added `consent` to **`remember_fact`**, a different tool.
* `test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures`
  — an undeclared `turn_detection` key in
  `configs/realtime.prototype.yaml.example`. That is **DUPLEX-1** (`task_26`).
  OT-2 edited **no** config file.

### 5.2 The AST ratchet: only the identity gate moved

The ratchet reddened unprompted and named exactly one symbol:

```
_owner_identity_trusted: 646234a1… != pinned 5262d3ed…
```

`apply_reactive_safety` (`f52db9c5…`), `ReactiveSafetyPolicy.owner_slow_m`
(`119af4ad…`) and `_owner_comfort_band_m` (`7d5050eb…`) are **unchanged —
checked, not assumed**. The gate function, the owner band, and *which* band is
chosen carry zero AST-normalised change; only *who counts as the owner* moved.
`ReactiveSafetyPolicy.__post_init__` also reads as moved on this tree — that is
DOOR-1's regeneration, logged one entry above mine, and OT-2 changed **exactly
one digest** in `REACTIVE_SAFETY_PIN`. The regeneration and its reasoning are in
the log immediately above the dict, as P1-E did.

---

## 6. Seeded RED — one per new guard (six after the correction pass)

Every seed was applied to a **byte-identical scratch copy** of `src/`
(`sha256sum` over every `.py`, equal on both sides before seeding), run with
`PYTHONPATH=<tree>/src`, and then discarded. **The product tree was never
seeded** — verified by grepping it for every seed string afterwards, and by the
green re-run below.

| # | Seed, in the PRODUCT | Test that went RED | Result |
|---|---|---|---|
| **S1** | `_ot2_apply_owner_identity` re-emits a constant `confidence=1.0` for a confirmed track | `test_ot2_the_runtime_never_emits_a_constant_owner_confidence` | **1 failed**, 50 passed |
| **S2** | the measured arm restored to `confidence >= OWNER_IDENTITY_CONFIDENCE_MIN` (a raw-cosine gate) | `test_ot2_a_measured_identity_is_never_judged_on_the_raw_cosine` (+ R1, R4, the headroom floor, the uncalibrated row) | **5 failed**, 46 passed |
| **S3** | `pixel_reid_uncalibrated` admitted to `CALIBRATED_IDENTITY_SOURCES` — the stranger at 0.917 | `test_ot2_an_uncalibrated_gallery_can_never_grant_the_owner_band` (+ the DOOR-1 seam row) | **2 failed**, 49 passed |
| **S4** | `GRANTING_LABELS` widened to include `unverified` | `test_ot2_unverified_audio_never_creates_granted_memory[…-keep-unverified]` (+ 4 more) | **5 failed**, 46 passed |
| **S5** | the remember door promotes a row whose key already exists (a repeat = a confirmation) | `test_ot2_repeating_remember_fact_is_not_confirmation` | **1 failed**, 55 passed |
| **S6** | the degrade sets `visible=False` again — a lost identity deletes the person from the gate | `test_ot2_a_degraded_owner_still_gets_a_persons_clearance` (+ R7) | **2 failed**, 54 passed |

Harness: `/home/jaewoo-jang/.cache/parcel-ot2/{seed.sh,seedall.py}`; trees at
`/home/jaewoo-jang/.cache/parcel-ot2/red{1..6}`. Reproduce with
`PYTHONPATH=/home/jaewoo-jang/.cache/parcel-ot2/red3/src .parcel/bin/python -m pytest -q -p no:cacheprovider tests/test_ot2_*.py`.

**The S5 tree stacked two seeds and no longer does** (Fable, item 6). In the
first pass the ineffective S5 was left in `seedall.py` and the effective one was
applied on top by a second script, so `red5` carried both edits — which makes
"this seed reddens that test" an ambiguous claim. `seedall.py` now holds the
effective S5 only, all six trees were rebuilt from the corrected product, and
the table above is that run.

**S4 caught a vacuous assertion in my own test, and it is worth reading.** The
first version of the 5×3 matrix computed its expectation as `label in
GRANTING_LABELS` — read from the product. Seed S4 widened that set, and the
matrix followed it and stayed **green**. The expectation is now a literal in the
test file, and the seed reddens the exact parametrised cell. The seed did its
job on the test rather than on the code, which is the argument for seeding at
all. **S5's first version was also ineffective** (it promoted before the upsert,
which then overwrote the consent); it was rewritten to promote on a repeat, and
only then reddened. Both first attempts are recorded because a seed that passes
is evidence about the seed, not about the guard.

---

## 7. OWNER-GATED rows — surfaced with exact commands, never claimed

### G-1 · the calibrated-identity campaign (the card's own owner-gated row)

Needs **a camera** (`ls /dev/video*` returns nothing on this host) and the
owner's appearance enrollment. Six arms, and the point of running them together
is that the gallery's operating point is calibrated on **one** day in **one**
room and nothing in the file can detect that it has gone stale (P1-C handoff 8).

```bash
# 0. enroll: ten seconds of you, ten seconds of somebody who is not you.
PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
.parcel/bin/python tools/enroll_owner_appearance.py \
    --camera 0 --seconds 10 --rate-hz 2 \
    --negative-frames ~/parcel-negatives/*.png --show

# 1..6. one gallery, six held-out capture sets. Record for each arm:
#   frames, owner-claim recall, false claims on the negative person,
#   min/median headroom above the gallery threshold.
for arm in clothing lighting pose occlusion crossing day2; do
  PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
  .parcel/bin/python tools/enroll_owner_appearance.py \
      --verify --frames ~/parcel-campaign/$arm/*.png --json \
      > ~/parcel-campaign/$arm/report.json
done

# the row that decides whether OWNER_IDENTITY_MARGIN_MIN is right:
#   min headroom over ALL owner frames in all six arms, vs 0.005.
```

**What the campaign is actually for.** `0.005` is a noise floor derived from an
encoder's reproducibility. It is NOT an operating point and this card does not
claim it is one. If the campaign's minimum owner headroom lands near it, the
floor is doing nothing; if owner frames land *below* it in a new coat, the
robot will treat its owner as a stranger in the social band and the fix is a
re-enrollment, not a lowered floor.

### G-2 · the voice principal against a real enrolled voice

The memory-principal rows are measured with a stand-in gate that reports one
chosen label, because no voice is enrolled on this host. The labels are pinned
equal to `voice_identity.SPEAKER_LABELS`, so the *rule* is measured on the real
vocabulary; what is not measured is a real verifier producing them.

```bash
.parcel/bin/python tools/enroll_owner_voice.py          # ~1 min of the owner's voice
# then, with the stack up, say a fact and check WHICH principal it landed under:
#   the row's `writer` and the tool result's `principal.label` must both say `owner`.
```

---

## 8. What this does not prove

1. **Nothing here has seen a real person or a real camera.** P1-C's limit,
   inherited whole. The clip is synthesized, and R6/R7 use the CPU fixture
   encoder, so they measure the wiring and the degrade behaviour — not
   recognition.
2. **Pixels do not reach the tracker on the live camera path yet.** See §9.
   Under a real camera today the tracker is fed boxes with no image, degrades to
   `no_pixels`, and the robot correctly treats the owner as a stranger. That is
   safe and it is not the feature.
3. **`0.005` is defended as a noise floor and nothing more.** No campaign has
   been run (§7 G-1). One negative person, one day, one room is the whole
   calibration behind the boundary it sits above.
3a. **`OwnerTrack.identity_margin` is the headroom of an EMA, not of the
   comparison the producer actually made** (Fable, item 5).
   `PixelOwnerTrack.identity_score` is a time-decayed EMA of the per-frame
   cosine, so on a frame the tracker genuinely confirmed this number can be
   **negative** — the smoothed score still carries earlier weak frames. The
   error is one-directional (a lagging EMA can only WITHHOLD the relaxed band,
   never invent headroom), which is why it is tolerable and not a safety
   finding; but "headroom above the operating point" is not literally what the
   field holds, and the docstring now says so. Not fixed here because the
   per-compare similarity (`_Track.last_similarity`) is internal to
   `owner_tracking`, which this card may consume and not touch. Handoff in §10.
3b. **0.65 is still applied to a measured cosine by two motion controllers.**
   `follow.py` (three sites) and `search_owner.py` admit on the raw number, and
   the overlay now feeds them one. A calibrated `ambiguous` claim at 0.85 is
   refused by the identity gate and followed by the follow controller. Pinned as
   `test_ot2_the_follow_and_search_admissions_still_read_the_raw_cosine`;
   see §3 and §10 handoff 3.
4. **The control-loop seam is proven by an AST pin plus functional rows through
   `_publish_camera_frame`/`_ot2_apply_owner_identity`, not by a spun-up loop
   thread.** The pin asserts the call sits between `backend.observe()` and every
   downstream reader (`_observation_sink`, `follow.observe_owner`,
   `_record_owner_sighting`); it does not prove a live 10 Hz loop behaves as the
   pin describes.
5. **The memory principal is authorization over a LABEL, not authentication.**
   A recording of the owner's voice produces the `owner` label. Nothing here is
   anti-spoofing. `owner_model.principal.DOES_NOT_PROVE` says so beside the code.
6. **`unenrolled` grants.** On a stock install — which is every install today —
   whoever is talking to the robot may create durable consented memories. That
   is a deliberate prototype decision (§3 of `PREREGISTRATION.md` D-3, and the
   `GRANTING_LABELS` docstring), taken because the alternative is a new
   fail-closed default this wave forbids. It also means **enrolling a voice is a
   real security act**, not a convenience, and nothing in the product says so to
   the owner yet.
7. **Typed panel turns and the local agent** carry no voice verdict and resolve
   to the `unenrolled` principal. The keyboard is trusted exactly as far as the
   room is.
8. **Nothing schedules distillation** (P2-A's own handoff, unchanged).
   `DISTILLER_PRINCIPAL` exists and is proven unable to grant, but no code path
   invokes `distil_session`.
9. **No latency was measured.** The tracker runs on the camera worker thread and
   the overlay is three attribute reads under `_lock`; neither was timed under
   contention.

---

## 9. Declared deviations, and the one HALT-item

### 9.1 HALT-item — pixels cannot reach the tracker on the live path, and I did not take another card's file

`CameraDetectionFrame` carries boxes and world coordinates and **no image**
(P1-C handoff 3). The natural fix is a one-line frame-buffer handle beside
`on_frame` in `camera_channel/ingress.py` — which is **P1-B's file, and both
VENUE-1 and NM-1 are explicitly told not to touch it**, so OT-2 did not either.

What I did instead: `_ot2_latest_rgb()` duck-types `latest_rgb()` on the
attached ingress. An ingress that grows the method lights the path up with no
further wiring; one that has not degrades to `no_pixels`, which is pinned as a
positive assertion (`test_ot2_no_pixels_is_a_degrade_and_not_a_claim`) so the
gap cannot be mistaken for the feature working. The rows in §4 supply the
pixels through that same runtime code path from a stand-in ingress; **only the
ingress implementation is a stand-in, the runtime path is the product's.**

**Handoff for whoever owns `ingress.py` next — and it is NOT one line**
(Fable, item 6; the first version of this section called it one and was wrong).
It is three edits plus an invariant that nothing currently pins:

```python
# 1. CameraIngress.__init__ / the dataclass: an initializer, or latest_rgb()
#    raises AttributeError before the first successful poll.
self._last_rgb: Any | None = None
# 2. CameraIngress._detect_and_localize, beside the frame publish:
self._last_rgb = rgb
# 3. the accessor:
def latest_rgb(self) -> Any | None:
    return self._last_rgb
```

**The invariant, stated because a side channel does not carry it.** Nothing in
`latest_rgb()`'s signature ties the pixels to the frame whose boxes will index
them. It is sound in the one caller that exists because
`_ot2_note_camera_frame` runs synchronously on the camera worker inside the
same `_publish_frame` call that produced the frame, so no later capture can
have swapped the buffer. Any other consumer — or this one moved behind a queue
— desynchronizes silently, drawing boxes from frame *n* over pixels from frame
*n+1*. **The better shape is to carry the pixels WITH the frame**
(`on_frame(frame, rgb=…)`, or a `frame_id`-keyed accessor) so the pairing is a
type rather than a timing coincidence. `_ot2_latest_rgb`'s docstring records
this.

### 9.2 `src/parcel_robot/backends/base.py` — outside OWNS (+34 / −0)

(The full path matters: there are two `backends/base.py` in this tree. This
deviation is into **`src/parcel_robot/backends/base.py`**, the simulator
observation types — **not** `src/parcel_robot/camera_channel/backends/base.py`,
which is P1-A's camera backend surface and was not touched. Fable, item 6.)

The card gives me `headless_city.py`'s owner-track emission and
`reactive_safety.py`'s identity gate, and asks the gate to consume `state` +
a calibrated margin. `_owner_comfort_band_m` — which I may **not** move, and did
not — calls `_owner_identity_trusted(observation.owner)`, so the state has
nowhere to travel except on `OwnerTrack`. Three fields, all defaulted to the
value every pre-card producer effectively emitted, and row R5 is the proof that
nothing moved.

### 9.3 `realtime/tool_broker.py` — outside OWNS (+181 / −3)

The card's memory-principal slice requires "a PRODUCT caller for
`set_owner_fact_consent`". A caller nothing calls is the exact defect P1-C
declared and this card exists to close, so the confirmation has to be reachable
from the conversation, and every other fact action lives in the broker. Checked
first: CAP-1 (`task_31`) names "the broker's tool bodies" in its MUST NOT TOUCH,
and NM-1 (`task_18`) as written owns `naming.py`/`vlm_veto` — so no wave-2 card
claims this file. All of it is inside `# ---- CARD OT-2 …` markers except two
sentences appended to the `remember_fact` tool description. ASK-1 is editing the
same file concurrently in disjoint places; nothing of its work was touched.

### 9.4 `owner_model/principal.py` is not exported from `owner_model/__init__.py`

`__init__.py` is P2-A's package surface and is not in my OWNS, so consumers
import the submodule directly (`from parcel_robot.owner_model.principal import
…`). Same shape as P1-C's declared D4. A one-line re-export belongs in whichever
card next owns that package.

### 9.5 The memory principal decides the row and is only PARTLY on it

`add_owner_fact`'s `provenance` column is two-valued (`owner_stated` /
`model_proposed`) and is P2-A's schema. For a voice the verifier said was **not**
the owner, `owner_stated` asserts something nobody established (Fable, item 6).
Widening the column is a schema change outside this card, so the correction
stamps `[heard from: <label>]` into the row's `reason`, which `add_owner_fact`
already persists verbatim, and only for principals that may not grant — for
`owner` and `unenrolled` the existing provenance is already true and churning
every reason would move P2-A's committed result text for nothing. Pinned by
`test_ot2_a_row_records_who_spoke_when_it_was_not_the_owner`. **The column
itself is still wrong for those rows**, and that is the residue: a third
provenance value (`heard_unverified`) belongs to whichever card next owns
`memory.py`.

### 9.6 `tests/test_dynamic_layer.py` — sanctioned by the card, noted for the diff

"regenerate its pin only with a log entry, as P1-E did." One digest changed, one
log entry added (+67 / −1). DOOR-1 changed a different digest in the same dict;
neither card touched the other's.

---

## 10. Handoffs

1. **`ingress.py` needs `latest_rgb()`** — §9.1. Until it lands, a physical
   camera venue produces `no_pixels` and the owner reads as a stranger to the
   comfort band. One line, in a file this wave fenced off.
2. **VENUE-1 (`task_16`)** — nothing in OT-2 calls `install_owner_tracker`. The
   composition root is deliberately a method, because the tracker needs an
   encoder and a gallery that only exist once a venue has resolved. The natural
   call site is the end of `_attach_configured_camera_ingress`, which is
   VENUE-1's region:
   ```python
   from parcel_robot.owner_tracking import OwnerTracker, load_gallery, resolve_embed_fn
   gallery = load_gallery()                       # None when unenrolled: claims nobody
   self.install_owner_tracker(OwnerTracker(gallery=gallery, embed_fn=embed_space[0]))
   ```
3. **DOOR-1 (`task_19`) — and this one is a REQUEST, not a note.** §0: nothing
   you read moved. But `follow.py` is yours this wave and it still admits the
   owner on the raw cosine at three sites (`:657`, `:701`, `:1082`), as does
   `search_owner.py:582`. Since OT-2's overlay landed, those are thresholding a
   SigLIP-2 cosine with a channel-prior constant, and a calibrated `ambiguous`
   claim at 0.85 is refused by the identity gate and followed by your
   controller (§3, and
   `test_ot2_the_follow_and_search_admissions_still_read_the_raw_cosine`
   asserts the gap exists so closing it reddens that test). The patch:

   ```python
   from parcel_robot.navigation.reactive_safety import owner_identity_trusted
   # follow.py:657 and :1082, search_owner.py:582 — instead of
   #   owner.confidence < self.config.min_confidence
   # for a MEASURED source, ask the decision:
   if owner.identity_source in MEASURED_IDENTITY_SOURCES:
       admit = owner_identity_trusted(owner)
   else:
       admit = owner.visible and owner.confidence >= self.config.min_confidence
   ```

   `owner_identity_trusted` is a public **alias** bound to the pinned
   `_owner_identity_trusted`, so asking it costs the ratchet nothing. I did not
   make this change because both files are under concurrent edit and they are
   not in OT-2's OWNS. If you would rather not own it, say so and it becomes a
   card.
4. **P2-B (`task_11`)'s greeting is now live on the measured track.**
   `owner_presence_sample` needed **no edit** — it already reached for
   `self.owner_track`, and this card makes that property return one.
   `test_ot2_the_presence_seam_reads_the_measured_track` pins that the source
   flips from `mocap` to `pixels` and the confidence stops being 1.0.
5. **The panel renders none of this.** `owner_identity_snapshot()` and
   `memory_principal_snapshot()` are public and unrendered, as are the broker's
   new `facts_confirmed` / `facts_consent_downgraded`. "Who does the dog think
   that is, and what has it decided to keep about me" is a question the owner
   should be able to answer without a debugger.
6. **The distiller should carry `DISTILLER_PRINCIPAL`.** `distil_session` writes
   `model_proposed` rows and consults the policy only; routing its consent
   through `admit_consent(DISTILLER_PRINCIPAL, …)` would make "a model may
   propose" structural there too. It is not wired because nothing schedules
   distillation at all (P2-A's own handoff).
6a. **`owner_tracking` should publish the headroom the producer actually
   measured.** `PixelOwnerTrack` exposes only the decayed EMA, so the reactive
   gate's `identity_margin` is the headroom of a smoothed score and can go
   negative on a confirmed frame (§8.3a). The tracker already holds the right
   number at the compare — `_Track.last_similarity` — so:

   ```python
   # owner_tracking/tracker.py, in _snapshot():
   identity_margin_above_threshold=(
       track.last_similarity - gallery.threshold if seen and gallery else 0.0
   ),
   ```

   then have `RobotRuntime._ot2_publish_update` read that instead of
   `identity_score - threshold`. Consume-only for OT-2; one field for whoever
   owns that package.
7. **`OwnerTrackerConfig` still is not a config key** (P1-C handoff 7). The
   association gate and `lost_after_s` are dataclass defaults; a prototype that
   wants to tune them needs keys in `configs/robot.prototype.yaml`, which is
   P0-A's/VENUE-1's file.
8. **The owner should be told that enrolling a voice is a security act** (§8.6).
   Today the difference between `unenrolled` and `owner` is invisible in the
   product and decides who may teach the robot facts about them.

---

## 11. Files an auditor should open first

1. `src/parcel_robot/navigation/reactive_safety.py`, the marked OT-2 seam and
   `_owner_identity_trusted` — the card's central judgement, and the only
   safety-authority symbol that moved.
2. `tests/test_dynamic_layer.py`, the log entry above `REACTIVE_SAFETY_PIN` —
   what moved, what did not, and the evidence for "did not".
3. `src/parcel_robot/owner_model/principal.py`, `GRANTING_LABELS` — the
   `unenrolled`-grants decision is the most arguable thing in this card (§8.6).
4. §4.1 — the one row that missed, and why the miss is the fixture.
5. §9.1 — the honest statement that pixels still do not reach the tracker on a
   live camera, and the one line that would fix it.

---

## 12. Correction pass — Fable's verification, 2026-08-22

Verdict received: **ACCEPT with corrections** (15-agent read-only workflow; the
safety seam verified clean against 21ea2fb, R5's digest re-derived on both
trees, R2/R3/R7 reproduced through the real tracker, the memory slice driven
through the real broker, all five seeds re-run). Six items; all six addressed.
Same rules as the first pass: Edit-only, git read-only, `TMPDIR` unset, a
seeded RED for the new guard.

### 12.1 SAFETY (major) — a lost identity was deleting the person from the gate

**The finding, and it is correct.** The degrade branch set `visible=False`.
`apply_reactive_safety` appends the owner to its people list only `if
observation.owner.visible` — so "I have lost the identity" was silently spelled
"there is nobody there", which costs the person their **clearance**, not merely
the relaxed band. My own §1 said the degrade "treats the owner as a stranger";
a stranger gets `person_stop_m`. This got nothing.

Worse, **my R7 test asserted `visible is False`** — it was pinning the defect in
place. That is the more useful half of the finding.

**Fixed** in both branches of `_ot2_apply_owner_identity`, because the fresh
branch had the same confusion (`visible = state == confirmed`, which would have
deleted an `ambiguous` person):

* not-fresh: `visible=previous.visible` — presence is carried from the backend
  untouched. This method may only ever answer *who*.
* fresh: `visible=True` — a fused track exists, so the camera localized a body
  there. Whether the gate RELAXES around them is `_owner_identity_trusted`'s
  question and it reads `state` for itself.

**Pinned** by `test_ot2_a_degraded_owner_still_gets_a_persons_clearance`:
owner at 0.7 m centre distance (0.15 m clearance once the 0.55 m owner
collision envelope is removed, against a 1.2 m person stop), tracker installed
and no claim ever published — the identity gate refuses the relaxed band
(`_owner_comfort_band_m` returns `person_slow_m` = 2.5 m) **and**
`apply_reactive_safety` returns `stopped` with zero translation. R7's assertion
is inverted to the corrected semantics with the reason written next to it.

**Seeded RED (S6):** restore `visible=False` in the not-fresh branch →
2 failed, 54 passed, on the safety row and on R7.

### 12.2 The raw-cosine gate is still live in `follow.py` / `search_owner.py`

Correct, and §3's "never applied to a measured cosine" was **false**. Chose to
**correct the claim and hand the fix off**, not to make it: `follow.py` is
DOOR-1's file this wave and `search_owner.py` is under concurrent edit, so
changing either would be editing another executor's region mid-flight.

Rather than leave it as prose, the gap is now an **executable positive
assertion** (P1-C's convention for its own uncalibrated finding):
`test_ot2_the_follow_and_search_admissions_still_read_the_raw_cosine` measures
that a calibrated `ambiguous` claim at 0.85 is refused by the identity gate and
accepted by `FollowConfig` and `SearchOwnerConfig`, and that P1-C's stranger at
0.9295 from an uncalibrated gallery is too. When somebody closes the gap, that
test reddens and the handoff gets struck rather than quietly rotting. §3 is
rewritten, §8 gains item 3b, §10 handoff 3 carries the patch.

### 12.3 R6's declared MISS had the wrong cause — and the row PASSES

The most instructive item, and it is entirely mine. Verified independently
before accepting: over all 16 visible owner crops, different-frame pairs at
exactly 1.0 = **0**, max off-diagonal cosine **0.9999731**, 15 of 16 crop
heights distinct. The encoder does not self-match. The six exact-1.0 values
were **enrollment crops scored against themselves**, because `_drive_clip`
iterated all twenty frames while the clip header says identity rows are
measured on 6–19.

Fixed: feed every frame, score only the held-out ones, assert no enrollment
index can appear in the scored rows, and **restore the pre-registered
assertion**. Measured: 10 distinct values over 10 held-out confirmed frames,
max **0.999915 < 1.0**. R6 is **MET as written**; §4.1 is rewritten from a miss
to a met row with the self-match explanation deleted.

**Taken as a practice note, and it is the one worth keeping.** A weakened
pre-registered assertion justified by a measured-sounding cause that was never
measured is worse than a plain miss: the miss is visible, the explanation is
camouflage. The rule now: *if a pre-registered row fails, measure the cause
before rewriting anything* — and when the cause is measured, it is usually the
harness.

### 12.4 "Strictly FEWER" was false

Measured on my own enumeration (7,650 cases: 6 sources × 5 states × 51
confidences × 5 margins) against the pre-OT-2 rule: **1,314 newly refused, 66
newly granted, 6,270 unchanged.** (Fable measured 198 on a different grid; same
phenomenon.)

**Chose option (a) — state the direction correctly — and did not AND the 0.65
floor onto the measured arm.** Three reasons, in order of weight:

1. The card's binding instruction is *do NOT key it on the raw number*. ANDing
   `confidence >= 0.65` onto the measured arm is exactly that.
2. It is not costless, contrary to the suggestion. It costs nothing on P1-C's
   real encoder (threshold 0.9591) but a **calibrated** operating point can
   legitimately sit below 0.65 — the fixture encoder in this very test file
   calibrates to **0.639943**. Refusing a confirmed, calibrated claim there
   would be a channel-prior number overruling a measured boundary.
3. What the 66 buy is the relaxed comfort **band** only; the stop ring is
   `person_stop_m` on both sides. And they require a calibrated gallery to have
   *confirmed* with headroom above the noise floor — a strictly stronger
   evidentiary standard than the rule they replace, which granted on a mocap
   1.0 or a UWB channel prior with no identification at all.

Restated in all three places (§0, the `reactive_safety` marked-region comment,
the `REACTIVE_SAFETY_PIN` log entry) and **pinned as a measurement** rather than
a claim: `test_ot2_the_direction_of_the_change_is_measured_not_asserted`
reproduces HEAD's rule inline and asserts 1314 / 66 / 6270 plus the shape of all
66. Lesson from 12.3 applied — the direction is now a number, not an adjective.

### 12.5 `identity_margin` is an EMA, not the producer's headroom

Correct. `PixelOwnerTrack.identity_score` is a time-decayed EMA, so the field
holds the headroom of a *smoothed* score and can go negative on a confirmed
frame. `owner_tracking/` is MUST-NOT-TOUCH for this card, so the semantics are
published where a reader will hit them: the `OwnerTrack.identity_margin`
docstring, a note at the computation site in `_ot2_publish_update`, §8.3a, and
§10 handoff 6a with the concrete field to add
(`identity_margin_above_threshold = last_similarity - gallery.threshold`).

Stated plainly because it changes how the number should be read: the error is
**one-directional** — a lagging EMA can only withhold the relaxed band, never
invent headroom — which is why this is a documentation correction and not a
second safety finding.

### 12.6 Notes

* **`noqa: BLE001` count** — four, not two, now named in §5:
  `_ot2_memory_principal`, `_ot2_latest_rgb`, `_ot2_note_camera_frame`,
  `_ot2_publish_update`.
* **The S5 scratch tree stacked both seed attempts.** It did, and that makes
  "this seed reddens that test" ambiguous. `seedall.py` now carries the
  effective S5 only; all six trees were rebuilt from the corrected product and
  §6's table is that run.
* **Two tracker fields read outside `_lock`** — fixed rather than declared.
  `_ot2_note_camera_frame` now snapshots the tracker under `_lock` before
  driving it outside (the encoder call must not be under a lock the control
  loop wants); `_ot2_publish_update` snapshots the fusion stub and the gallery
  threshold the same way; `_ot2_apply_owner_identity` and
  `owner_identity_snapshot` fold their `is None` checks into the `_lock` block
  they already take. No new lock, R24's roster unchanged, 30 tests green.
* **The ingress handoff is not one line** — restated in §9.1 as three edits
  plus the frame/pixel pairing invariant, with the better shape named (carry
  the pixels with the frame). `_ot2_latest_rgb`'s docstring now records why the
  bare accessor is sound in this one caller and nowhere else.
* **The principal was not persisted on the row** — fixed as far as this card's
  OWNS reaches: `[heard from: <label>]` is stamped into the row's `reason` for
  every principal that may not grant. `provenance` is still `owner_stated` for
  those rows and that is still wrong; §9.5 declares it and names the residue.
  Pinned by `test_ot2_a_row_records_who_spoke_when_it_was_not_the_owner` and
  its twin asserting the owner's own rows are not churned.
* **The deviation path** — §9.2 now says
  `src/parcel_robot/backends/base.py` in full and states explicitly that
  `src/parcel_robot/camera_channel/backends/base.py` (P1-A's) was not touched.

### 12.7 Gates after the corrections

```
.parcel/bin/python -m pytest -q tests/test_ot2_identity.py tests/test_ot2_memory_principal.py
# -> 56 passed  (22 + 34; was 19 + 32)

.parcel/bin/python -m pytest -q <the 20-file targeted sweep of §5>
# -> 708 passed

PYTHONPATH=src .parcel/bin/python .../r5_matrix.py
# -> cases=648  sha256=f16316b3…  (unchanged: the legacy path still did not move)

# AST ratchet: _owner_identity_trusted 646234a1… (unchanged by this pass —
# the corrections touched comments around it and the runtime overlay, not the
# predicate); apply_reactive_safety f52db9c5…, owner_slow_m 119af4ad…,
# _owner_comfort_band_m 7d5050eb… all unchanged.

.parcel/bin/ruff check <the 9 OT-2 files>            # -> All checks passed!
ruff fingerprints: 12 total, 7 baseline, 5 DUPLEX-1's, OT-2 zero.
```

Seeds S1–S6 re-run against trees rebuilt from the corrected product: each
reddens its named test (§6). The two pre-existing failures in this tree
(`test_arrival_semantics`, `test_prototype_profile`) are unchanged and still
belong to ASK-1 and DUPLEX-1 (§5.1).
