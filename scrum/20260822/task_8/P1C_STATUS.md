# P1-C — the dog knows which person is you · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Executor:** Claude Opus ·
**Verifier:** Fable · **Date:** 2026-08-22 · **Verdict:** CLAIMS_HOLD, with three
corrections applied — **§11**.

---

## 0. Headline

Pixels now reach `OwnerTrackV1` with a confidence that is a **cosine somebody
measured**, and `confirmed` now means *the gallery matched* rather than *the
channel is fresh*. On the two-person clip, with the real SigLIP-2 fp16 encoder
on CUDA: **one** track id carries the owner through a crossing at 0.31 m
separation and a four-frame occlusion, **zero** owner claims land on the
stranger, **zero** owner claims exist without an enrolled gallery, and the
emitted confidence takes 8 distinct values in [0.9739, 0.9942] — never 1.0.

**The card's design did not survive contact with the real encoder, and the way
it failed is the most useful thing in this document.** The gallery threshold as
originally built — the owner's own agreement minus a declared slack — landed at
**0.9103**, and the stranger in the same room scores **0.9295** against the
owner's crops. Measured, on the shipping path: that gallery **claimed the
stranger as the owner on 2 of 20 frames**, every one of them a frame where the
owner was behind the occluder and the stranger was alone in shot. SigLIP-2 is an
image↔text encoder, not a person-verification network, and no constant in this
repository could have guessed where its person/person boundary sits.

The fix is not a tuned constant. The enrollment now **measures** the boundary:
show it one crop of somebody who is not you, and the threshold becomes the
midpoint of the measured gap (0.9591 here, between the owner's leave-one-out
floor 0.9903 and the stranger's best 0.9280). Same clip, same weights, **zero**
false claims. An enrollment with no negative is still possible — it needs
`--allow-uncalibrated`, it is stamped `calibrated: false` in the file, that flag
rides all the way to `OwnerFusionResult.identity_source ==
"pixel_reid_uncalibrated"`, and `test_p1c_real_siglip2.py` pins the fact that it
is unsafe **as a positive assertion**, so the day it stops being true somebody
finds out.

**Nothing existing moved.** `OwnerFusionStub.fuse()` called without a pixel track
produces byte-identical output to HEAD over a 512-case matrix
(sha256 `a98f47d99404955c6df5be8f4298f1f7d89fb4f17fbcf7f85270403e2cd65c55`).

**Not delivered:** the two live rows (person recall on the owner, live follow)
are OWNER-GATED on a camera this host does not have; commands in §7. Nothing is
wired into `runtime.py` — that file is not in OWNS and the runtime seam is
handoff 1.

---

## 1. What changed

| File | + | − | Note |
|---|---:|---:|---|
| `src/parcel_robot/uwb/fusion.py` | 155 | 0 | **the only pre-existing file touched.** `PixelTrackInput`, the `pixel=` kwarg, `identity_source` |
| **new** `src/parcel_robot/owner_tracking/__init__.py` | 98 | — | package surface + `DOES_NOT_PROVE` |
| **new** `src/parcel_robot/owner_tracking/gallery.py` | 571 | — | the enrolled gallery, its operating point, its refusals |
| **new** `src/parcel_robot/owner_tracking/tracker.py` | 729 | — | C-1 frames → crops → embeddings → re-ID tracks |
| **new** `src/parcel_robot/owner_tracking/embedder.py` | 211 | — | `embed_fn` resolution: ingress → SigLIP-2 → None |
| **new** `src/parcel_robot/owner_tracking/synthetic_clip.py` | 442 | — | the two-person clip renderer + the fixture stand-in encoder |
| **new** `tools/enroll_owner_appearance.py` | 468 | — | the owner action |
| **new** `tests/test_p1c_owner_gallery.py` | 299 | — | 28 cells |
| **new** `tests/test_p1c_owner_tracker.py` | 479 | — | 23 cells, 4 seeded RED |
| **new** `tests/test_p1c_owner_fusion_seam.py` | 448 | — | 22 cells, incl. the 512-case back-compat digest |
| **new** `tests/test_p1c_enroll_appearance.py` | 337 | — | 20 cells |
| **new** `tests/test_p1c_real_siglip2.py` | 211 | — | 6 cells, GPU/weights-gated |
| **new** `tests/data/p1c_two_person_clip.json` | 377 | — | the clip *script* (not pixels) |

```
$ git diff --numstat -- src/parcel_robot/uwb/fusion.py
155     0       src/parcel_robot/uwb/fusion.py
```

`fusion.py` is the only tracked file in the diff that is mine. Every edit to it
was an exact-match single-occurrence replacement against the file as re-read at
that moment; no `git add/commit/stash/checkout/reset/restore` was run. The other
~36 modified paths in `git status` belong to the six concurrent cards and were
not read-modified by this one.

**Not touched, deliberately:** `camera_channel/ingress.py` (P1-B), `online_map/`,
`navigation/reactive_safety.py`, `runtime.py`, `headless_city.py`,
`backends/mujoco.py`, the voice identity stack (P2-B), `configs/**`,
`pyproject.toml` (the new package is found automatically by
`[tool.setuptools.packages.find] where=["src"]` — no declaration needed),
`scripts/ci_gate.py`, `docs/`, `backlog/`, `README.md`, `scrum/20260821/`.
`src/parcel_robot/uwb/__init__.py` was deliberately **not** edited — see
deviation D4.

---

## 2. Pre-registration

Written to `/home/jaewoo-jang/.cache/parcel-p1c/prereg/PREREGISTRATION.md` at
**02:26**, before the first measurement (first tracker run 02:39, first real
SigLIP-2 run 02:41). Verbatim rows in §3.

---

## 3. Pre-registered rows: measured

Measured with the real encoder unless noted. Full raw output:
`/home/jaewoo-jang/.cache/parcel-p1c/FINAL_NUMBERS.txt`.

| # | Row | Pre-registered | Measured (SigLIP-2 fp16, calibrated) | Verdict |
|---|---|---|---|---|
| R1 | owner claims with an EMPTY gallery | exactly 0 | **0** / 20 frames (also 0 with the stand-in; and *unrepresentable*: `PixelTrackInput` refuses `owner_claim` without `gallery_enrolled`) | **MET** |
| R2 | track id across one occlusion | identical; label back ≤ 2 frames | **1 distinct id** (`pixel-person-1`) across the whole clip; reacquired **1 frame** after the owner reappears | **MET** |
| R3a | owner label on the non-owner | exactly 0 | **0** | **MET** (weak — see D1) |
| R3b | owner TRACK id through the crossing | *(added, D1)* exactly 1 | **1**; the seeded-RED position-dominated build gives **2** | **MET** |
| R4 | confidence in (0,1), ≥5 distinct | over the clip | held-out frames: **8 distinct**, min 0.9739, max 0.9942, all < 1.0. **Enrollment frames: exactly 1.0** | **MET on held-out / MISS as written** — see D2 |
| R5 | decay while lost; fusion gets nothing | monotone ↓ | **0.8313 → 0.7037 → 0.5957 → 0.5042** over the four occluded frames, strictly decreasing; `owner_track is None`, frame state `searching`, on all four | **MET** |
| R6 | owner−stranger separation, real weights | ≥ 0.05 | **0.0634** (owner mean 0.9807 min 0.9404; stranger mean 0.9173 max 0.9295) | **MET, narrowly** |
| R7 | crop-embed latency, `cuda_fp16` | p50 ≤ 15.0 ms | **p50 3.44 ms**, p95 4.67 ms, max 9.02 ms, n=60 | **MET** |
| R8 | fusion back-compat, no `pixel` | byte-identical over 24 cases | **byte-identical over 512 cases**, sha256 `a98f47d9…` on both sides | **MET, exceeded** |
| R9 | person recall on held-out owner frames | ≥ 0.8 | **NOT MEASURED — OWNER-GATED** (no camera on this host) | **HALTED** |
| R10 | live owner track across the room | qualitative | **NOT MEASURED — OWNER-GATED** | **HALTED** |
| R11 | enrollment refuses an inconsistent gallery | refusal with numbers | refuses: <5 crops, no negatives, mixed people, unnamed encoder, repo path. All with numbers | **MET** |
| R12 | seeded-RED proofs | 3 | **6** (§4; RED-2 now measured on both encoders, RED-6 added in verification) | **MET, exceeded** |

Two derived numbers worth having, not pre-registered:

* **Owner recall on the clip** (claims ÷ frames where the owner is visible):
  **14/16 = 0.875** with SigLIP-2 calibrated; **16/16 = 1.000** with the
  histogram stand-in. The two SigLIP-2 misses are the crossing frames 9 and 10,
  where roughly half the owner's crop is the other person's body. The dog says
  `searching` for 0.5 s mid-crossing rather than guessing — the card's specified
  behaviour, measured, and a real cost.
* **The uncalibrated gallery, same clip, same weights:** threshold 0.9103,
  **2 false owner claims** (frames 14 and 15, owner occluded), **2 distinct
  owner track ids**. This is the finding in §0.

---

## 4. Seeded RED

Every guard here has been watched to fail. Each RED is a *build*, not a mocked
assertion, and the GREEN assertion is the one that catches it.

| # | The defect, seeded | Guard | RED evidence |
|---|---|---|---|
| RED-1 | tracker labels every person `owner` regardless of gallery (the "only person in the room must be you" bug) | `test_R1_seeded_RED_a_tracker_that_defaults_to_the_only_person` | claims > 0 with `gallery=None`; and `as_fusion_input()` then raises `owner_claim without gallery_enrolled` |
| RED-2 | association cost trusts geometry over appearance (`appearance_weight=0.01, position_weight=10.0`) | `test_R3b_seeded_RED_…_at_the_crossing` (stand-in) **and** `…_on_the_real_encoder` (SigLIP-2, GPU-gated) | distinct owner track ids **2** vs **1** on the shipped config, on BOTH encoders — the real-encoder half was promoted out of scratch in verification, §11 C-2 |
| RED-3 | `identity_score` pinned to 1.0 (the audit's actual defect) | `test_R4_seeded_RED_a_constant_confidence_is_caught` | held-out scores collapse to one value; `all(0<s<1)` fails |
| RED-4 | an enrollment whose "owner" is two different people | `test_R11_an_enrollment_that_is_two_different_people_is_refused` | `build_gallery` refuses: *"cannot identify its owner: … agree with each other at X while a NON-owner crop scores Y"* |
| RED-5 | the back-compat digest itself | `test_R8_seeded_RED_the_digest_actually_notices_a_change` | one of 512 tracks nudged to `identity_score: 1.0` ⇒ digest moves |

| RED-6 | a coasted track keeps its owner claim through an occlusion (added in verification, §11 C-1) | `test_R6b_a_calibrated_gallery_makes_zero_false_owner_claims` | *"an owner was claimed while the owner was occluded, on frames [13, 14, 15, 16]"*; the same seed also reddens 4 cells in the stand-in suite |

A seventh is not a seeded build but a **pinned live defect**:
`test_R6c_the_uncalibrated_fallback_is_measurably_unsafe` asserts, as a
positive, that the derived threshold currently admits the stranger. It fails the
day that stops being true, which is the day the enroller may relax.

---

## 5. How verified — exact commands

All from the repo root with `.parcel/bin/python`. `scripts/ci_gate.py` was **not
run** (board rule 4: only P0-E runs it).

```bash
# CI rows — no GPU, no weights, deterministic (0.9 s)
.parcel/bin/python -m pytest tests/test_p1c_owner_gallery.py \
    tests/test_p1c_owner_tracker.py tests/test_p1c_owner_fusion_seam.py \
    tests/test_p1c_enroll_appearance.py tests/test_p1c_real_siglip2.py -q
# -> 93 passed, 6 skipped in 1.06s      (the 6 skips are the GPU rows)

# the real-encoder rows (R6, R6b, R6c, R7, R4-real)
PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
    .parcel/bin/python -m pytest tests/test_p1c_*.py -q
# -> 99 passed in 3.79s

# lint (the gate's ratchet fails on any NEW (file, rule) pair)
.parcel/bin/ruff check src/parcel_robot/owner_tracking/ \
    src/parcel_robot/uwb/fusion.py tools/enroll_owner_appearance.py \
    tests/test_p1c_*.py
# -> All checks passed!

# neighbours that consume what I touched
.parcel/bin/python -m pytest tests/test_p2_uwb_noise.py tests/test_e6_owner_band.py \
    tests/test_owner_prediction.py tests/test_search_owner.py \
    tests/test_owner_and_settle_plans.py tests/test_owner_estop.py -q
# -> 135 passed

# the isolation + drift properties this card could plausibly have broken
.parcel/bin/python -m pytest tests/test_owner_store_isolation.py \
    tests/test_authority_no_literal_drift.py tests/test_load_guard.py -q
# -> 100 passed
```

**How the R8 baseline digest was produced** (scratch, not committed):

```bash
git show HEAD:src/parcel_robot/uwb/fusion.py > ~/.cache/parcel-p1c/head_replica/fusion_head.py
# load that file as its own module, run the same 512-case matrix as
# tests/test_p1c_owner_fusion_seam.py::_matrix_rows, json.dumps(sort_keys, indent=1)
# HEAD  -> a98f47d99404955c6df5be8f4298f1f7d89fb4f17fbcf7f85270403e2cd65c55
# TREE  -> a98f47d99404955c6df5be8f4298f1f7d89fb4f17fbcf7f85270403e2cd65c55
```

**One neighbouring failure, not mine:**
`tests/test_r24_lock_discipline.py::test_the_lock_roster_is_complete` fails with
*"RobotRuntime.__init__ constructs a lock this file does not order:
`['_p1b_map_lock']`"*. That is P1-B (task_7) mid-flight in `runtime.py`. I did
not touch `runtime.py`, `test_r24_lock_discipline.py`, or any lock. Left alone.

---

## 6. What this does not prove

1. **Nothing here has seen a real person.** The clip is synthesized (no camera on
   this host). Two flat-shaded bodies with distinct patterns are easier to tell
   apart than two housemates in the same grey hoodie. R6's 0.0634 separation is
   an **upper bound on an easy case**, not an estimate of field performance —
   and it is *already* narrow enough that the uncalibrated threshold fails.
2. **The calibrated threshold is calibrated against ONE negative person, on ONE
   day, in ONE rendered room.** It is a measured number, which is strictly better
   than a guessed one, and it is not an operating point.
3. **Recall 0.875 on the clip is not R9.** R9 asks for ≥0.8 on held-out frames of
   the *owner*, live. The clip number is measured on rendered frames of a
   rendered person and is reported only so the crossing cost is visible.
4. **The tracker is not in the product path.** `runtime.py` never constructs an
   `OwnerTracker`; `headless_city.py:370` still emits `OwnerTrack(confidence=1.0)`
   into `SimObservation`, and `reactive_safety._owner_identity_trusted` still
   reads that 1.0. This card built the producer and the seam; the wiring is
   handoff 1. **Until that lands, the audit's "owner at confidence 1.0" finding
   is still true of the running system.**
5. **The association tuning is fixture-informed.** `appearance_weight=1.0`,
   `position_weight=0.25`, `max_assoc_cost=0.75` were chosen to work on this
   clip. The *structure* (position gates, appearance decides) is defended by
   RED-2 on both encoders; the *numbers* are not defended by anything.
6. **A gallery is not bit-reproducible on the GPU.** Two enrollments of the same
   six crops produced `negative_reference` 0.928006 and 0.928208 — fp16 CUDA
   nondeterminism. Nothing here hashes a gallery, and nothing should.
7. **No latency was measured under contention.** R7's 3.44 ms was taken with the
   GPU otherwise mostly idle; P0-C measured the same encoder at 4.17 ms with nine
   co-resident processes. Neither number is a budget for a running robot.

---

## 7. OWNER-GATED live rows — exact commands

Both need a camera plugged in (D455 or any UVC webcam: `ls /dev/video*` returns
nothing on this host today) and both need the appearance enrollment.

### G-1 · enroll the owner's appearance (~30 s, needs one other person for 10 s)

```bash
# ten seconds of you, then ten seconds of somebody else, as PNG/JPEG frames:
PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
.parcel/bin/python tools/enroll_owner_appearance.py \
    --camera 0 --seconds 10 --rate-hz 2 \
    --negative-frames ~/parcel-negatives/*.png

# or entirely from files, if you would rather record on a phone:
PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
.parcel/bin/python tools/enroll_owner_appearance.py \
    --frames ~/parcel-owner/*.png --negative-frames ~/parcel-negatives/*.png

# where it went, and whether it is calibrated:
.parcel/bin/python tools/enroll_owner_appearance.py --show
```

Writes `~/.config/parcel/owner_appearance_gallery.json`, mode 0600, **outside
the repo** (the tool refuses a path inside it). It does not open
`parcel_memory.sqlite3`. Expect `calibrated: true`; if it says `false`, the
threshold is a guess and §0 explains why that matters.

*Two things it may refuse, both on purpose:* fewer than 5 owner crops, and no
negative at all. The second is not optional politeness — it is the difference
between 0 and 2 false owner claims on the fixture.

### G-2 · R9, person recall on held-out frames of the owner (≥ 0.8)

```bash
# with the camera live, record ~60 s of yourself walking around the room, then:
PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
.parcel/bin/python -m pytest tests/test_p1c_real_siglip2.py -q
#   ^ the CI half; then the live half, which does not exist yet as a test:
#     feed the recorded frames through OwnerTracker with the enrolled gallery
#     and count claims / frames-where-you-are-visible.
```
**Status: HALTED on hardware.** The live harness is deliberately not written
against an imagined camera API — P1-A (task_6) owns the `CameraBackend`s, and
the honest move is to write G-2 against the backend it lands rather than against
a guess. Handoff 5.

### G-3 · R10, the owner track follows you across the room

```bash
PARCEL_PROFILE=prototype PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
    scripts/launch_stack.sh --prototype --camera 0
# then, with a second person in shot, walk across the room while somebody pans
# the camera by hand. Watch: the owner track id must not change, and the second
# person must never take the `owner` label.
```
**Status: HALTED on hardware AND on handoff 1** — `--camera` is P1-A's switch and
nothing in `runtime.py` constructs an `OwnerTracker` yet, so this command
currently proves the camera works and nothing about identity.

---

## 8. Deviations from OWNS / from the card

**D1 — the R3 metric was replaced after it failed to discriminate.** I
pre-registered "owner label lands on the non-owner = 0". Measured: the
position-dominated seeded-RED build **also scores 0** on it, because the owner
label is recomputed per-frame from the gallery and does not ride the track. The
metric was therefore not measuring swap-on-crossing at all. I added R3b — the
number of distinct track ids that ever carry the owner claim — which separates
the builds 1 vs 2. Both are reported; R3a is kept because it is still a property
worth having.

**D2 — R4 is a MISS as literally written.** I pre-registered "*every* emitted
owner `identity_score` is strictly in (0.0, 1.0)". On the six enrollment frames
it is exactly 1.0, because the crop being scored *is* an enrolled crop. That is
correct behaviour and it is the only documented way to reach 1.0, but it is not
what I wrote down. The guard is pinned on held-out frames (6-19) and the
enrollment-frame behaviour is asserted separately and explicitly.

**D3 — the gallery grew a calibration concept the card did not ask for**
(`negatives=`, `calibrated`, `negative_reference`, and the enroller's default
refusal). Driven entirely by the §0 measurement: without it the card's own
"confidence is a measured similarity" deliverable ships a system that calls a
stranger the owner. `self_consistency` also changed mid-build from
cosine-to-centroid to **leave-one-out max**, because the runtime query is
max-over-crops and a threshold derived from one statistic and applied to another
is a number nobody measured.

**D4 — `src/parcel_robot/uwb/__init__.py` was NOT edited**, although exporting
`PixelTrackInput` there would be the tidy thing to do. OWNS says
"`uwb/fusion.py` (pixel-track input seam only)". Consumers import
`from parcel_robot.uwb.fusion import PixelTrackInput`. Handoff 6.

**D5 — two fixture-shaped things live in the shipped package**, not under
`tests/`: `owner_tracking/synthetic_clip.py` (the clip renderer) and its
`histogram_embed_image` stand-in encoder. Reasons, stated: the enrollment tool's
`--clip` path uses the renderer, so it is a product path; and there is house
precedent (`route_memory.place_graph.stub_embed_image`). Both carry docstrings
saying what they are not. `tests/data/p1c_two_person_clip.json` holds the
*script* — per-frame world positions and appearances — and the pixels are
rendered from it, so an auditor can read whether the crossing crosses without
opening an image viewer.

**D6 — the hand-off rule was observed and then lifted.** `pyproject.toml`,
`scripts/ci_gate.py` and `tests/**` were untouched until
`scrum/20260822/task_5/P0E_STATUS.md` existed (checked absent 02:24, present
02:28). Package and tool were built first; the clip fixture was staged in
`~/.cache/parcel-p1c/` and moved to `tests/data/` after the lift.
`pyproject.toml` needed no edit at all.

---

## 9. Handoffs

1. **Runtime wiring (the big one).** Nothing constructs an `OwnerTracker`. The
   shape it wants: subscribe to `CameraIngress.on_frame`, keep the RGB alongside
   (the published `CameraDetectionFrame` carries boxes, not pixels — see
   handoff 3), call `update()`, and pass `owner_track.as_fusion_input()` into
   `OwnerFusionStub.fuse(pixel=…)`. Then `SimObservation.owner.confidence` can
   come from the fused track instead of `headless_city.py:370`'s literal `1.0`,
   and `reactive_safety._owner_identity_trusted`'s 0.65 floor finally reads a
   real number. Owner of `runtime.py` regions required.
2. **`OWNER_IDENTITY_CONFIDENCE_MIN = 0.65` will be wrong.** It is a threshold on
   a *channel prior* today. Once identity_score is a SigLIP-2 cosine, 0.65 is met
   by essentially any person-shaped crop (the stranger scores 0.917). Whoever
   lands handoff 1 must either map the cosine into a calibrated probability or
   move that floor — and it lives in `reactive_safety`, which is MUST-NOT-TOUCH
   for this card and is safety-authority-pinned.
3. **Pixels do not travel with the C-1 frame.** `CameraDetectionFrame` carries
   boxes and world coordinates but no image, so any in-runtime consumer needs the
   RGB by another route. P1-B owns `ingress.py`; the natural fix is a
   frame-buffer handle beside `on_frame`.
4. **`load_onnx_embedder` loads the TEXT session eagerly.** This package only
   ever wants vision, so the standalone path pays 565 MB of fp16 text weights it
   never uses (~1.7 s). `embedder.from_ingress` exists precisely so the in-runtime
   path shares P1-B's already-loaded encoder. A vision-only loader belongs in
   `instructnav/`, which this card does not own.
5. **The live harness for R9/R10** should be written against P1-A's
   `CameraBackend`, not against an imagined camera API. See §7 G-2.
6. **`PixelTrackInput` is not exported from `parcel_robot.uwb`** (D4).
7. **`OwnerTrackerConfig` is a dataclass, not a config key.** If the prototype
   wants to tune the association gate or `lost_after_s`, the keys belong in
   `configs/robot.prototype.yaml` (P0-A's file, not in this card's OWNS).
8. **Threshold recalibration is a recurring owner action, not a one-off.** A
   haircut, a new coat, or a different room invalidates the gallery in a way the
   file itself cannot detect. `--show` prints the operating point; nothing warns
   when it has gone stale. That is a real gap and it is not fixed here.

---

## 10. Files an auditor should open first

1. `src/parcel_robot/owner_tracking/gallery.py` — the `build_gallery` docstring
   and the calibrated/uncalibrated split. This is where the card's central
   judgement call lives.
2. `tests/test_p1c_real_siglip2.py::test_R6c_the_uncalibrated_fallback_is_measurably_unsafe`
   — the finding in §0, pinned as an executable positive.
3. `src/parcel_robot/uwb/fusion.py`, the block after both primary branches — the
   only behaviour change to an existing code path in the whole card, and its
   back-compat proof at `tests/test_p1c_owner_fusion_seam.py::test_R8_…`.
4. §6 item 4 — the honest statement that the running robot still believes the
   owner at 1.0.

---

## 11. Post-verification corrections

Verdict received: **CLAIMS_HOLD** — the finding, all rows, deviations, handoffs
and hygiene reproduced. Three corrections were required and are applied here.
Nothing in §0–§10 changed except the two line references and the RED count noted
below; the numbers in §3 were re-run after every edit and did not move.

### C-1 · a vacuous assertion, replaced and then watched to fail

`tests/test_p1c_real_siglip2.py::test_R6b_…` ended with:

```python
for index in OCCLUSION_FRAMES:      # ints
    assert index not in owner_ids   # a set of track-id STRINGS
```

An `int` is never `in` a set of strings, so the row could not fail and proved
nothing — the one thing this card claims to be careful about, in this card's own
test. It now asserts the intended property on the **per-frame claim record**:

* `claimed_while_occluded == []` — no owner claim on any occluded frame;
* every occluded frame's tracker state is `searching`;
* and the converse, `claimed_frames` non-empty and ≥ `frames − occluded − 4`, so
  the row cannot pass by the tracker simply never claiming anybody.

The new block is asserted **before** the stranger/identity rows, deliberately: a
build that keeps the claim while coasting also trips `false_claims` (a coasted
track's stale pose sits nearest the only visible person, who is the stranger),
and with the old ordering that fired first and the row under test was never
reached. That ordering bug was found by the seeded RED below, not by reasoning.

**Seeded RED (RED-6).** `tracker.py` was temporarily mutated so a coasted track
keeps its owner label and is eligible as `owner_track`:

```
owner = next((track for track in tracks if track.is_owner and track.seen_this_frame), None)
  ->  owner = next((track for track in tracks if track.is_owner), None)
label=track.label if seen else "unknown",   ->   label=track.label,
```

```
E  AssertionError: an owner was claimed while the owner was occluded, on frames [13, 14, 15, 16]
E  assert [13, 14, 15, 16] == []
1 failed in 2.52s
```

The same seed also reddened 4 cells in `tests/test_p1c_owner_tracker.py`
(R3a, R5, the uncalibrated-label row, and one more), which is independent
corroboration that the stand-in suite covers the property too.

**Restored byte-identically**, verified by digest rather than by eye:

```
$ sha256sum src/parcel_robot/owner_tracking/tracker.py
4a2878922e5c14e89b80cf8dfdce027f229f4366f1fe784036195e5647b73b4b   (pre-seed == post-restore)
```

### C-2 · RED-2 promoted from scratch to a test

The position-dominated swap RED was pinned only against the histogram stand-in;
its real-encoder run lived in `~/.cache/parcel-p1c/FINAL_NUMBERS.txt` and would
have evaporated. It is now
`test_p1c_real_siglip2.py::test_R3b_seeded_RED_position_dominated_association_swaps_on_the_real_encoder`,
under the same `PARCEL_SIGLIP2_ONNX` gating as its neighbours.

This matters more than a tidy-up: the stand-in scores the stranger at **0.28**
against the owner's crops, so "appearance beats geometry" is nearly free there.
SigLIP-2 scores the same stranger at **~0.92**. Measured, real weights:
position-dominated → **2** distinct owner track ids; shipped config → **1**. The
guard survives the thin signal, and that is now a test rather than a sentence.

### C-3 · numbers and a line reference

* `gallery.py` quoted the stranger at `0.9297` and the enroller quoted `0.9281` /
  `0.9592` where §3 has `0.9295` / `0.9280` / `0.9591`. Aligned to §3, and each
  file now states **once** that these are one run's values, that they wander by
  ~2e-4 because fp16 CUDA is not deterministic, and that nothing pins or hashes
  a cosine. (This is the same fact as §6 item 6, now visible from the code.)
* The `OwnerTrack(` call in `headless_city.py` opens at :365 but the
  `confidence=1.0` literal — the thing handoff 1 replaces — is at **:370**. Both
  references in §6 and §9 corrected.

### Verification after the corrections

```bash
$ .parcel/bin/ruff check src/parcel_robot/owner_tracking/ \
      src/parcel_robot/uwb/fusion.py tools/enroll_owner_appearance.py tests/test_p1c_*.py
All checks passed!

$ .parcel/bin/python -m pytest tests/test_p1c_*.py -q
93 passed, 7 skipped in 0.93s

$ PARCEL_SIGLIP2_ONNX=1 PARCEL_PERCEPTION_PROVIDER=cuda_fp16 \
      .parcel/bin/python -m pytest tests/test_p1c_*.py -q
100 passed in 4.11s
```

Cell count 99 → 100 (C-2's promoted RED); GPU-gated cells 6 → 7. `ci_gate.py`
was not run (board rule 4). No file outside OWNS was touched by these
corrections; no git write command was run.
