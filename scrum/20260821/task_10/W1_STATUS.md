# W-1 — a world worth looking at · status

**Card:** `scrum/20260821/task_10/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable (DEFERRED — this doc is written to be audited cold, weeks
from now, with nobody to ask) · **Date:** 2026-08-21

---

## 0. Headline

The card's premise was right and its headline target was missed, and both of
those are measurements rather than opinions.

**The world stopped being unreadable.** Same 42 poses, same detector, same
matcher, same 0.1 threshold; only the pixels differ:

| | untextured (bench's own row) | textured |
|---|---|---|
| micro recall | 49/298 = **0.164** | 149/306 = **0.487** |
| macro recall | 0.176 | **0.484** |
| bench | 7/13 = 0.538 | **13/13 = 1.000** |
| building | 34/104 = 0.327 | **81/104 = 0.779** |
| door | **0/11 = 0.000** | **7/11 = 0.636** |
| tree | **0/30 = 0.000** | **16/31 = 0.516** |
| crate | 0/9 = 0.000 | 7/10 = 0.700 |
| planter | 0/28 = 0.000 | 10/29 = 0.345 |
| lamppost | 4/15 = 0.267 | 11/15 = 0.733 |
| **person** | **0/69 = 0.000** | **1/74 = 0.014** |

**T1 (person recall ≥ 0.5) is MISSED, and the miss has a mechanism.** At the
pre-registered threshold the number is 1/74. At threshold 0.02 the *same* run
localizes **36 of 74 people at IoU ≥ 0.5** and fires a person box in 24 of 42
frames. The control settles what that means: run the identical low-threshold
probe on the **untextured** frames and OWLv2 emits **zero** person predictions —
0 boxes, 0/69 at any IoU, in all 42 frames.

> The world change did not make the detector confident about people. It made the
> detector **have a person hypothesis at all**, correctly placed, at a
> confidence the incumbent threshold rejects. That is a different failure from
> the one this card started with, and it hands PG-3 (calibrated abstention) a
> real signal where there was none.

**T2 passes 8/8** (target ≥ 5), and **T2b — the card's two named silent prompts
— both fire**: `door` 0 → 7 matches, `storefront` 0 → 12. **T3 passes**, and the
discriminating half of it is that the VLM's person question goes **0/6 → 6/6
correct**.

**Two of the card's inherited premises did not survive contact with the bench's
own artifacts, and both are corrected in §5.3:** the VLM did *not* name "only
the Go2" before this card (it named seven real categories), and the T2 target of
≥5 classes was already met by the untextured world. Neither correction touches
the T1 result or the world's condition; both change what counts as evidence.

**Physics is byte-equivalent by measurement, not assertion:** 141 dynamics
arrays equal, the same 68 colliding geoms in the same order, a 3,000-step /
31,290-contact rollout with `max |Δqpos| = 0.0`, and the frozen embodied suite
reproducing 997/0/0/0.883147 with per-case 200/260/64/389/84 bit-identically.
**15 seeds, 15/15 RED, 15/15 restored byte-identically.**

**Gate: PASS at 20:21:46Z**, every hard gate green, skips unchanged at 9,
release-parity unchanged at 91, the frozen nav baseline unmoved. Two later runs
went red **entirely on a concurrently-executing card's camera-ingress work**, and
§1.2 attributes every one of those lines rather than asserting innocence.

---

## 1. Gate — verbatim

### 1.1 Baseline, read before any edit

Read at **2026-08-21T18:49:49Z**, before a single byte of this card was written.

```
CI GATE — tier=commit  (2026-08-21T18:49:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7766 collected = 7724 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.25s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  owner-store-isolation      6 passed in 1.58s
[  PASS] HARD  default-suite              7715 passed, 9 skipped, 42 deselected, 5 warnings in 301.30s (0:05:01)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 325.9s
```

### 1.2 Final, after the last edit

Five runs, all of them recorded, because the tree is shared with a concurrently
executing card and the last two reds are that card's, not mine.

| run | stamp | result |
|---|---|---|
| `gate_final.txt` | 19:57:06Z | **FAIL** — `default-suite`, 2 metamorphic cells. **Mine.** Fixed in §4.4b. |
| `gate_final2.txt` | 20:14:56Z | **PASS** — every hard gate green |
| `gate_final3.txt` | 20:21:46Z | **PASS** — every hard gate green, after this document was written |
| `gate_final4.txt` | 20:28:39Z | FAIL — `ruff` only, `camera_channel/ingress.py::F401`. **Not mine.** |
| `gate_final5.txt` | 20:37:17Z | FAIL — `ruff` `ingress.py::RUF022` + 4 camera-ingress cells. **Not mine.** |

The **20:21:46Z** run is W-1's final gate: it postdates every source edit in this
card, postdates the final 15-seed sweep, and postdates the body of this document.

```
CI GATE — tier=commit  (2026-08-21T20:21:46Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7797 collected = 7755 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.35s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.43s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  owner-store-isolation      6 passed in 1.60s
[  PASS] HARD  default-suite              7746 passed, 9 skipped, 42 deselected, 5 warnings in 304.51s (0:05:04)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 329.2s
```

**The two later reds, attributed rather than asserted.** Between 20:21:46Z and
20:37:17Z the only repo files that changed at all were:

```
src/parcel_robot/camera_channel/ingress.py            16:29:20 local   NOT MINE
src/parcel_robot/camera_channel/backends/mujoco_egl.py                 NOT MINE
src/parcel_robot/runtime.py                                            NOT MINE
scrum/20260814/task_1/STAGE0_COMMAND_ADDENDUM.md                       NOT MINE
evals/external/experiments/.../experimental_sampled_predictive_tracker.py  NOT MINE
scrum/20260821/task_10/W1_STATUS.md                                    <- this document
```

Every red line names that work: `ruff` points at
`camera_channel/ingress.py` (F401 at 20:28, then RUF022 at 20:37 — the file was
being edited *while* my run read it, mtime 16:28:47 then 16:29:20 local), and
the four `default-suite` cells are `test_cam_arrival.py` ×2,
`test_runtime_activation.py::test_camera_ingress_poll_produces_pixel_candidate`
and `test_r24_lock_discipline.py::test_the_lock_roster_is_complete` — the pixel
ingress path and its lock roster. `camera_channel/**` and `runtime.py` are on
this card's MUST-NOT-TOUCH list and I never opened either.

Independently checked: **every file W-1 changed or added is ruff-clean** —
`ruff check tests/test_scene_assets.py tests/test_held_out_scene.py
evals/nav_instruct/scene_truth.py evals/nav_instruct/metamorphic.py
scripts/ci_gate.py` → *All checks passed!*

I did **not** fix the other card's violation. It is theirs to fix before their
own gate, and reaching into a frozen path to make my own run look green is
exactly the kind of tidiness that destroys attribution.

### 1.3 Baseline → final, and the arithmetic closes

| | baseline 18:49:49Z | final 20:21:46Z | Δ |
|---|---|---|---|
| collected | 7766 | 7797 | **+31** |
| passed | 7715 | 7746 | **+31** |
| **skipped** | **9** | **9** | **0** — the nine deliberately-skipped gate cells were not touched and no skip condition was edited |
| deselected | 42 | 42 | 0 |
| ruff | 7, baseline 7, new 0 | 7, baseline 7, new 0 | 0 |
| frozen-digest sentinels | 4 byte-identical | 4 byte-identical | 0 (the pin moved with the file; both are re-pinned together — §4.5) |
| release-parity | 91 packaged assets | **91** | 0 — the held-out scene needed no second sidecar |
| hard-safety | collisions 0, false_arrival 0, same baseline id | identical | 0 |

The +31 is exactly the two new files, measured per file rather than inferred:
`tests/test_scene_assets.py` collects **24** and `tests/test_held_out_scene.py`
collects **7**. 24 + 7 = 31 = the collected delta = the passed delta, with
skipped and deselected flat. (PG-1's audit correction was that its own collection
arithmetic did not close; this one is measured so that it does.)

---

## 2. Acceptance — pre-registered, then measured

`scratchpad/w1/PREREGISTRATION.md` was written **before the first textured frame
existed and before any asset was composited**, against the repo baseline gate of
18:49:49Z. It is restated in §7 so this document survives the scratch directory.

Ordering, because it is the thing an auditor cannot reconstruct later:

| artifact | mtime |
|---|---|
| last write to `city_block.xml` | 15:18:14 |
| 42 acceptance frames rendered | 15:18:54 |
| OWLv2 fp16 result | 15:19:25 |
| VLM control result | 15:25:40 |
| T2/T2b coverage result | 15:26:17 |

Every measured number postdates the final scene. The visual probes in
`scratchpad/w1/probe_*.png` and `city_*.png` came earlier and were **eyeballing,
not measurement** — no model was run on them and no target was adjusted after
any of them.

### 2.1 The instrument

The PG-1 / bench-owl harness, reused unmodified except for one mapping line:

* `render_frames.py` — 42 robot-eye poses, D455 nominal intrinsics
  (1280×720, fx=fy=644), Go2 mount (0.35 m, 0.18 m forward, 12° up), ground
  truth from MuJoCo's segmentation buffer, floor ≥ 460 visible px AND ≥ 0.05% of
  frame. **The one change:** the textured scene hides each person capsule in
  MuJoCo group 4 and stands a textured mesh named `vis_<body>` beside it, so
  `vis_pedestrian_3` maps onto the SAME logical object id `pedestrian_3`. The
  ground truth is therefore about the same set of things. Nothing about the
  poses, the floor, the intrinsics or the matcher changed.
* `evalkit.py` — per-label greedy matcher, IoU ≥ 0.5, one prediction per GT.
  Byte-unchanged.
* `bench_gpu_detectors.py::run_owlv2` — OWLv2-base-patch16-ensemble, torch fp16,
  CUDA, batch 1, threshold 0.1, the 11-label `WORLD_LABELS` set. Byte-unchanged.
* `bench_vlm.py` — Qwen3-VL-8B-Instruct fp16, the same three questions, the same
  six frame stems. Byte-unchanged.

The **before** column is the bench's own recorded row
(`scratchpad/perception/bench-owl/results/gpu_owlv2_fp16.json`), not a re-run:
same code, same poses, same model, so a re-run could only reproduce it.

The ground-truth denominator moves slightly, and it should: a human mesh has a
different silhouette from a capsule, so a few instances cross the pixel floor
that did not before. **person 69 → 74, crate 9 → 10, planter 28 → 29, tree
30 → 31; the other seven classes are identical.** Recall is reported on the new
denominator, which is the honest one — it is the set of instances actually
visible above the same floor.

### 2.2 T1 — person recall ≥ 0.50. **MISSED: 0.014 (1/74).**

Reported as a miss, with the frames, and without touching the target.

| | untextured | textured |
|---|---|---|
| person recall @ threshold 0.1 (registered) | 0/69 = 0.000 | **1/74 = 0.014** |
| frames emitting ANY person box @ 0.02 | **0 / 42** | **24 / 42** |
| GT people localized at IoU ≥ 0.5 @ 0.02 | **0 / 69** | **36 / 74 = 0.486** |
| GT people with best IoU ≥ 0.3 | 0 / 69 | 37 / 74 |
| GT people with best IoU > 0 | 0 / 69 | 43 / 74 |
| best person confidence anywhere | — (no boxes) | 0.139 |

The threshold sweep, **post-hoc and labelled as such** — it is a diagnostic, not
a re-registration, and the target stays where the card put it:

| threshold | 0.10 | 0.08 | 0.06 | 0.05 | 0.04 | 0.03 | 0.02 |
|---|---|---|---|---|---|---|---|
| person recall | .014 | .014 | .054 | .108 | .189 | .351 | **.486** |

The scores of the correctly-localized people run 0.139, 0.062, 0.061, 0.061,
0.058, 0.057, 0.056, 0.054, 0.048, 0.044, 0.043, 0.042 … — one instance clears
0.1 and the rest sit in a band the incumbent threshold rejects wholesale.

**What the control establishes and what it does not.** The untextured control is
the reason this is a finding rather than an excuse: OWLv2 produced **not one
person box in 42 untextured frames even at 0.02**, so "the detector was always
nearly right and the threshold was always wrong" is false. The textured world
created the hypothesis. It did not create confidence, and 0.486-at-0.02 is not
0.5-at-0.1 — the card's target is unmet on its own terms.

**Why the confidence is low, honestly.** I did not isolate the cause and will not
guess in the register. The candidates a reader should weigh: the meshes are
12-sided tubes with flat facets and no self-shadowing at 3–6 m; the person
atlases are 512 px; MuJoCo's headlight-plus-two-lights rig has no ambient
occlusion; and PG-1 already measured that the ONNX fp16 export finds fewer
objects than torch fp16 on identical pixels (37 vs 49 TP), so precision-path
choice is a live confound for anyone reproducing this on the shipping path
rather than on torch.

**What was NOT done, deliberately:** no asset was changed after this number was
read. Improving the humans until the number crosses 0.5 would be fitting the
world to the metric, which is the failure mode the pre-registration exists to
prevent.

### 2.3 T2 — ≥5 of the 8 corpus place classes fire. **PASS: 8/8.**

The eight are the eight declared by `configs/scenes/city_block.semantics.yaml`,
which is also the semantic-map bench's eight answerable queries. Same threshold
0.1, same IoU ≥ 0.5, same matcher; region classes matched against the
segmentation buffer's *stuff* boxes.

| class | kind | untextured | textured |
|---|---|---|---|
| lamppost | object | 4 | **11** |
| bench | object | 7 | **13** |
| door | object | **0 — silent** | **7** |
| tree | object | **0 — silent** | **16** |
| planter | object | **0 — silent** | **10** |
| building | object | 36 | **82** |
| sidewalk | region | 6 | **27** |
| crosswalk | region | 3 | 2 |
| **classes firing** | | **5 / 8** (objects 3/6) | **8 / 8** (objects 6/6) |

`crosswalk` is the one class that did not improve (3 → 2 matches). It still
fires, so it counts, and it is recorded as flat rather than dressed up: box IoU
against a ground-plane region is a weak metric — the semantic-map bench said so
about its own containment metric and PG-2 replaced it for exactly this reason.

### 2.4 T2b — the two prompts the card names. **PASS: both fire.**

`storefront` is not a ninth class: the sidecar declares it as an **alias of
`building`** (`aliases: [bldg, storefront, building face]`), and the 2026-08-21
mapping bench recorded it among the prompts that never fired once in 120 frames.
Measured as a literal prompt string against the class's ground truth:

| prompt | untextured | textured |
|---|---|---|
| `door` | **0 matches — SILENT** | **7 matches** |
| `storefront` | **0 matches — SILENT** | **12 matches** |

Both were silent before and both fire now. This is the pair the card singled out
and the sharpest single result in the card.

### 2.5 T3 — the VLM control. **PASS, and the criterion is not the discriminator.**

Qwen3-VL-8B-Instruct fp16, same six frames, same three questions.

| | untextured | textured |
|---|---|---|
| "Is there a person in this image?" **correct** | **0 / 6** | **6 / 6** |
| — answered "yes" | 0 | 5 (the 6th frame has 0 people; "no" is correct) |
| real scene categories named across the six `scene` answers | 7 | 7 |

The category count does not discriminate — see the correction in §5.3. The
transcript does. Untextured:

> *"A stylized, abstract scene with colorful geometric shapes including tall
> cylinders, a green tree, and a bench on a checkered floor."*
> *"Yes, a large teal cylinder is blocking the path straight ahead."* (the
> "cylinder" is a pedestrian)

Textured:

> *"A wooden bench sits on a sidewalk in front of a "Corner Market" storefront
> with large windows and a red awning."*
> *"A 3D-rendered street scene with stylized, blocky human figures walking past
> brick buildings and a "Daily Bread" shop."*
> *"A 3D-rendered street scene featuring a "City Books" store with a green
> traffic light and a nearby "Daily Bread" shop."*

It reads the shop signage, calls the pedestrians human figures, and answers the
person question correctly on every frame. It also still says "stylized" and
"blocky", which is accurate and is left in the record.

Full before/after transcripts: `scratchpad/w1/` (`bench/results/vlm_sim.json`)
and the bench's own `perception/bench-owl/results/vlm_sim.json`.

### 2.6 T4 — physics byte-equivalence. **PASS, three ways.**

| check | result |
|---|---|
| named dynamics arrays byte-equal (`nq/nv/nu`, body mass/inertia/frames, `qpos0`, joints, dofs, actuators, equalities, tendons, sensors, sites, keyframes, `opt.*`) | **141 / 141 equal** |
| colliding geoms (type, size, pose, friction, solref, solimp, condim, margin, gap) | **68 / 68 equal, same names, same order** |
| 3,000-step `mj_step` rollout, same seed, same controls, mocap actors swept | `qpos`, `qvel`, `act`, contact count and constraint force **all bit-identical**, `max |Δqpos| = 0.0`, **31,290 contacts** in both |
| frozen embodied suite (real MuJoCo geometry over this scene) | **997** steps, **0** collisions, **0** timeouts, min clearance **0.883147 m**, per-case **200/260/64/389/84**, 4 passed / 1 unsupported — bit-identical |
| gate `hard-safety` | frozen nav baseline `nav-instruct-v1-baseline-v4-20260811T070536Z` unmoved, `collisions=0 false_arrival=0`, mutation panel reproduces live |

Harness: `scratchpad/w1/physics_equivalence.py`, output
`scratchpad/w1/physeq_final.json`.

---

## 3. Owner store isolation

| | sha256 |
|---|---|
| `parcel_memory.sqlite3` **before** this session | `40506fd96fc61c341d64d44cb607ec206fd547c03b223fbe91134ab5c2db4aa8` |
| `parcel_memory.sqlite3` **after** this session | `40506fd96fc61c341d64d44cb607ec206fd547c03b223fbe91134ab5c2db4aa8` — **unchanged** |

Store isolation is mechanical as of R27 (`owner-store-isolation` is a HARD gate,
`PARCEL_MEMORY_PATH` overrides, `purpose=owner` is refused under pytest). Every
command in this card — probes, renders, seed harness, gate — ran with
`PARCEL_MEMORY_PATH` pointed at scratch. The before/after measurement is taken
anyway, because R27's register entry says an isolation claim without a
measurement is what failed four times.

---

## 4. What landed

| File | Status | What |
|---|---|---|
| `src/parcel_robot/scenes/city_block.xml` | changed | photo textures on every material; 6 storefront quads, 4 awnings, 9 human meshes (all `vis_*`); person capsules moved to the un-drawn group 4. **No geom's name, type, size, pos, quat, friction or contact flags changed.** |
| `src/parcel_robot/scenes/city_block_b.xml` | **NEW** | the held-out block: street runs N–S, different buildings/furniture/crossing, different textures, same 8 semantic classes |
| `src/parcel_robot/scenes/assets/` | **NEW** | 33 textures + 5 meshes + `PROVENANCE.json`, **9.34 MB**, every byte a build product of CC0 sources |
| `evals/nav_instruct/scene_truth.json` | **regenerated** | 1 line moved: `scene.sha256`. `derived`, `surfaces`, `surface_convention`, `transcribed`, `transcription_deltas`, `generator_landmark_ids` **byte-identical** |
| `evals/nav_instruct/scene_truth_city_block_b.json` | **NEW** | the held-out scene's PG-2-convention truth artifact, 17 entities, all 8 classes |
| `evals/nav_instruct/scene_truth.py` | changed | `SCENE_TARGETS` registry + `--scene` on the CLI; `build_artifact(relpath=, transcription=)` |
| `evals/companion/embodied_plan_v1/manifest.json` | changed | **one sha string** — the `locked_inputs.city_scene` digest |
| `scripts/ci_gate.py` | changed | the matching `DIGEST_SENTINELS` re-pin + its re-pin-log entry |
| `pyproject.toml` | changed | package-data globs so a wheel carries `scenes/assets/**` |
| `evals/nav_instruct/metamorphic.py` | changed | the transformed-scene re-rooter now re-roots **every** compiler asset directory, not just `meshdir` (§4.6) |
| `tests/test_scene_assets.py` | **NEW** | 24 cells |
| `tests/test_held_out_scene.py` | **NEW** | 7 cells |
| `scrum/20260821/task_10/W1_STATUS.md` | **NEW** | this document |

### NOT TOUCHED — frozen by the card

`src/parcel_robot/realtime/**`, the yield / person-stop policy, every navigation
source file, `detection_adapter/**`, `instructnav/**`, `perception_chain.py`,
`camera_channel/**` (PG-1 owns the detector), the nine deliberately-skipped gate
cells and every skip condition, `configs/scenes/*.semantics.yaml` and their
runtime mirrors, every frozen episode set. **No commit, no stage, no stash at any
point.**

**The tree is shared, and two things in it are not mine.**
`scrum/20260821/cutover_research/` and `scrum/20260821/TASK_BOARD.md` show as
untracked — another agent's research folder and the sprint board.
`src/parcel_robot/camera_channel/ingress.py` shows as **modified** (+221 lines,
a typed `DETECTION_FRAME_SCHEMA` envelope): that is a concurrent card's work on
the pixel-ingress path, it landed at **16:18:28 local**, and I never opened it —
`camera_channel/**` is on this card's MUST-NOT-TOUCH list.

That timing matters for reading §1.2 honestly: the 20:14:56Z green run spans
16:14:56–16:20:33 local, so the 16:18:28 edit landed *inside* it; the 20:21:46Z
green run wholly postdates it. **Both are green.** The *later* ingress edits
(16:28:47, 16:29:20) are what turned the 20:28 and 20:37 runs red, and §1.2
attributes every one of those lines.

The owner's stack on :8765 was never contacted: no GET, no POST, no restart, no
process killed. GPU headroom: the owner's baseline is ~929 MiB and my heaviest
moment was the 8B VLM at 17,451 MiB delta on a 32,760 MiB card, leaving
~14 GB free — above the 6 GB floor throughout. One OOM did occur and is worth
recording: an earlier VLM attempt died because two of **my own** processes were
still resident; nothing of the owner's was involved and nothing was killed to
recover — I waited for my own processes to exit.

### 4.1 The rule that made the scene edit safe

One namespace, checked four ways:

> **Every geom W-1 adds is named `vis_*` and carries
> `contype="0" conaffinity="0" density="0"`.**

`vis_` matches no prefix in `sim.LOGICAL_OBSTACLE_PREFIXES`, none in
`headless_city._STATIC_OBSTACLE_PREFIXES`, no row of the sidecar's
`geom_prefixes`/`region_prefixes`, and none in
`test_city_orbit_clearance.STATIC_LOGICAL_PREFIXES` — so nothing added for looks
can become an obstacle the robot brakes for, a semantic instance the grounder
ranks, or a mass. `test_scene_assets.py` checks that against the **live** tables
rather than a copy of them, and separately freezes the *resolved* obstacle set
(44 names, sha `8cbc7b94…`) so a decoration named `obstacle_awning` would be
caught by the name it chose rather than by the prefix it avoided.

`density="0"` is the half that is easy to forget and impossible to see: without
it MuJoCo derives a mesh's mass from its volume and `pedestrian_1`'s body mass
goes **225.07 → 2881.67 kg**. A mocap body is never integrated, so nothing moves
— which is exactly why it needs a test rather than a reader's judgement. Seed S6.

### 4.2 Making the capsules invisible without deleting them

The card says the capsule collider stays and the visual rides along. A capsule
and a human mesh in the same place render on top of each other, so the capsule
had to stop being drawn. Three mechanisms were measured before choosing:

| mechanism | RGB | segmentation buffer | `web_panel` payload |
|---|---|---|---|
| `rgba` alpha = 0 | hidden | **also hidden** | rgba goes to 0 → pedestrians vanish from the 2-D city viewer |
| `group="3"` | hidden | hidden | unaffected — but group 3 is already the repo's *collision* group (`go2.xml`'s `class="collision"`) |
| **`group="4"`** | **hidden** | **hidden** | **unaffected** |

MuJoCo's `mjv_defaultOption` sets `geomgroup = [1,1,1,0,0,0]`, measured on this
machine, so groups 3–5 are not drawn. Group 4 keeps the collision group's meaning
intact and leaves `web_panel`'s viewer payload — which reads `geom_rgba` and
skips mesh geoms entirely — exactly as it was. `test_viewer_panel.py` passes
unchanged.

**Consequence, stated because it is a real one:** the interactive MuJoCo viewer
now shows the human mesh instead of the capsule. That is the intent. Anyone who
wants the capsule back toggles group 4.

### 4.3 Assets: provenance and reproducibility

| | |
|---|---|
| upstream | 17 Poly Haven CC0 textures, downloaded with upstream md5 **verified on fetch** |
| shipped | 33 PNGs + 5 OBJs, 9.34 MB, under `scenes/assets/` |
| built by | `scratchpad/w1/build_assets.py` + `humanoid.py` (scratch; the PNGs and OBJs are the shippable) |
| recorded | `assets/PROVENANCE.json`: per-file sha256 + size, and per-source asset id, author, licence, url, upstream md5 |
| enforced | `test_every_built_asset_matches_its_recorded_digest`, `test_no_asset_file_is_unrecorded`, `test_every_upstream_source_is_cc0_with_an_attributable_author` |

The humans are **generated**, not downloaded: a parametric low-poly humanoid
(`humanoid.py`) built from tapered elliptical tubes and ellipsoids with UVs
mapped into a named atlas layout, four body plans (1.63–1.80 m, different
shoulder width, bulk, stride and arm swing) × six outfit atlases. Nine bodies in
`city_block` use nine **distinct** (mesh, texture) pairs, and each carries its
own fixed yaw, so a detector sees nine different silhouettes from nine different
angles rather than one mesh nine times. Generating rather than downloading buys
three things the card needs: ≥3 genuinely different silhouettes, UVs that match
an atlas we also generate, and an unambiguous licence.

Two MuJoCo facts that cost time and are worth leaving in the record:

* **`type="2d"` textures streak on box faces.** A brick wall came out as vertical
  stripes. `type="cube"` maps correctly on boxes, cylinders and spheres; planes
  and UV meshes stay `2d`. Every tiling material in both scenes is `cube`.
* **`texuniform="true"` degenerates on a *thin* box.** The crosswalk stripes
  (0.30 × 2.4 × 0.004 m) rendered as a radial starburst because the two in-plane
  extents differ by an order of magnitude. `texuniform="false"` with an explicit
  `texrepeat` fixes it; the crosswalk and the bench slats use it.

**A known visual defect, shipped and reported rather than quietly fixed.**
`door_1` and the two `entry_wall_*` stubs are thin boxes (0.8 × 0.12 × 2.1 m)
still carrying `texuniform="true"`, so they show the same starburst the
crosswalk did — see `scratchpad/w1/city_door.png`. The one-line fix is the same
one the crosswalk got. It is **not** applied here because the acceptance numbers
were already measured against these bytes, and changing the scene after reading
the result — even to fix a defect — is how a pre-registration stops meaning
anything. It also does not flatter the result: `door` fires **7/11** in spite of
it. Carded as a follow-up, not patched inline.

### 4.4 The held-out scene, and what "held out" is enforced to mean

`city_block_b.xml` is a different block — the street runs north–south, six
buildings stand in different places at different sizes, the crossing is at the
north end, the bench faces the street instead of lying along it, the lighting is
a different hour, and **no facade, road, sidewalk, bench, door or storefront
texture is shared with the development scene**. What it keeps is the vocabulary:
`extract_city_semantics` reads it with the *existing* sidecar and returns all
eight classes (2 sidewalks, 1 crosswalk, 6 buildings, 2 lampposts, 2 trees,
2 planters, 1 bench, 1 door), so a claim measured there is a claim about the same
question asked of unseen pixels. **No second sidecar was needed and none was
added** — which is also why release-parity stays at 91 packaged assets.

The isolation rule is mechanical, not conventional (R27's lesson):
`tests/test_held_out_scene.py` enumerates every tracked **and untracked** file
that mentions `city_block_b`, and reddens unless that set is exactly the declared
allowlist — the scene, its generated truth artifact, the regeneration tooling,
the two tests, and the two cards (W-1 and E-2/`task_14`). Three sharper cells sit
on top: **no module under `src/parcel_robot/` may name it at all** (that is where
every perception component lives), no test outside the declared pair may load it,
and it may not be wired as a default anywhere.

**Card W-1 ran no detector and no VLM on `city_block_b`.** The only thing this
card measured there is geometry.

### 4.4b The gate found something the seeds did not

The first full gate run after the last source edit was **RED**, and it is
recorded here rather than quietly re-run:

```
[  FAIL] HARD  default-suite   2 failed, 7744 passed, 9 skipped, 42 deselected, 5 warnings in 310.02s
    FAILED tests/test_nav_metamorphic.py::test_transform_moves_every_landmark_and_keeps_every_name[mirror_y]
    FAILED tests/test_nav_metamorphic.py::test_transform_moves_every_landmark_and_keeps_every_name[rotate_90]
RESULT: FAIL — 1 hard gate(s) red: default-suite
```

`evals/nav_instruct/metamorphic.py::transform_scene_xml` writes a mirrored or
rotated copy of the scene into a `tmp_path` and re-roots the scene's relative
paths so the copy still resolves. It re-rooted `include` and **`meshdir`** — the
only asset directory the untextured block had. W-1 gave the block a
`texturedir`, and the copy could no longer find its own textures:

```
ValueError: Error: Error opening file 'assets/textures/road_asphalt.png'
```

Fixed by widening the loop to every asset directory the compiler understands
(`meshdir`, `texturedir`, `assetdir`) instead of naming one. Pinned as seed
**S15**, whose canary is the clearest in the sweep:

```
S15  mutated: transformed_scene_REFUSED Error: Error opening file 'assets/textures/curb_concrete.png'
     clean  : transformed_scene_compiles ngeom=139
```

**Worth saying plainly: my 14 seeds did not catch this and the gate did.** The
seeds were all written around the invariants I had thought about — physics,
naming, provenance, isolation. The defect was in a *consumer* of the scene that
I had not thought about at all, and the only thing that found it was running
everything. That is what the full gate is for, and it is why "my targeted
selections were green" is never a substitute for it.

### 4.5 The digest re-pin — mechanical, and the evidence for it

`evals/companion/embodied_plan_v1/manifest.json` SHA-locks
`src/parcel_robot/scenes/city_block.xml` as `locked_inputs.city_scene`, so a
texture pass moves it whether or not it changes behaviour. The R14 protocol was
followed exactly:

1. The committed manifest was verified to be **byte-identical to HEAD** before
   anything was measured (`sha256 88fa9fb5…`, checked against
   `git show HEAD:…` inside the probe).
2. The suite was re-run against a **scratch** manifest carrying the final scene
   digest: `997 / 0 / 0 / 0.883147`, per-case `200/260/64/389/84`,
   4 passed / 1 unsupported — bit-identical to the frozen row.
3. Only then was the committed file edited: **one sha string**,
   `bb7f8e02…` → `38d71b66…`, manifest `88fa9fb5…` → `d251f781…`.
4. `DIGEST_SENTINELS` re-pinned with a re-pin-log entry naming the card, the
   authority (the owner's standing world-simulator decision, "texture the city
   now", recorded in `AUDIT_OVERNIGHT_FABLE.md`), and the physics evidence.

**It is unmoved for a reason, not by luck:** W-1 changed no physics at all, and
§2.6 measures that three independent ways. If the row had moved by a digit the
texture work would have been reverted rather than re-pinned — that consequence
was registered in the pre-registration before the measurement ran.

**Owner-gated ratification.** This re-pin is mechanical and reversible, and
nothing is committed by this card. If the owner declines the texture fork, the
correct action is to drop this whole change set; the sentinel returns to
`88fa9fb5…` with it.

---

## 5. Corrections to inherited numbers

### 5.1 The card's T2 target was already met before this card

The card asks for "≥5 of the 8 corpus place classes detected at least once".
Measured on the **untextured** frames with the same instrument: **5 of 8**
(lamppost, bench, building, sidewalk, crosswalk). The target was therefore
already satisfied by the world the card was written to replace, and 8/8 is a
pass whose margin — not whose verdict — is the result. The discriminating
statement is the one in §2.3–2.4: **objects 3/6 → 6/6, and the two prompts the
card names go from silent to firing.**

### 5.2 "0/69 person recall" is right; "the detector was close" is wrong

Worth stating positively because it is the load-bearing control: at threshold
0.02, on untextured frames, OWLv2 emits **zero** person boxes in 42 frames. The
0/69 was not a thresholding artefact. It is the strongest single piece of
evidence that `bench_detectors.md`'s diagnosis was correct.

### 5.3 The VLM did NOT name "only the Go2"

The card's evidence line says *"a VLM describes our city as 'colorful geometric
shapes', naming only the Go2 (the one textured mesh)."* The first half is a
verbatim quote and is accurate. The second half is not supported by the bench's
own transcript (`perception/bench-owl/results/vlm_sim.json`): across the six
untextured `scene` answers the model names **bench, building, crosswalk,
lamppost, road, traffic light and tree** — seven real categories by the
pre-registered vocabulary. One answer is *"A stylized 3D street scene with
buildings, a traffic light showing green, a lamppost, and a crosswalk."*

Consequence: the T3 criterion I pre-registered from that summary (≥3 categories)
cannot discriminate, and I say so rather than reporting a pass as a win. The
part of the VLM control that *does* discriminate is the yes/no person question:
**0/6 correct → 6/6 correct**, and the fact that the untextured model calls a
pedestrian *"a large teal cylinder"* while the textured one calls them *"blocky
human figures walking past brick buildings"*.

I inherited the claim, restated it in my own pre-registration, and only caught it
when I dumped the full transcript to score it. Recording that sequence because a
pre-registration that copies an unchecked summary is only as good as the summary.

---

## 6. Seeds — 15, each RED for the right reason, each restored byte-identically

Protocol (house rule R9, session-B), identical for all fourteen: snapshot bytes +
sha256 → **one** textual mutation → purge every `__pycache__` under
`src/ scripts/ tests/ evals/ tools/` → **fresh-interpreter canary** (`python -B`,
`PYTHONDONTWRITEBYTECODE=1`) that *calls the live code* rather than reading its
text → run the named guards, require RED → restore in a `finally` → purge again →
assert sha256 identity → second canary proving the mutation is gone → re-run,
require GREEN. Harness `scratchpad/w1/seed_harness.py`, results
`scratchpad/w1/seed_results.json`, log `scratchpad/w1/seeds.log`.

The card names four by hand — a broken texture path (**S1**), the held-out scene
referenced outside E-2 (**S2**), a hand-edited sidecar (**S3**), a changed
collision geom (**S4**). **S15** was added after the gate found the defect it
pins (§4.4b).

| # | What is broken | File | first failing test | RED | GREEN | sha |
|---|---|---|---|---|---|---|
| **S1** | **a texture path points at a PNG that does not exist** | `city_block.xml` | the module refuses to compile → every cell errors | ✓ | ✓ | ✓ |
| **S2** | **a perception module names the held-out scene** | `perception_providers.py` | `test_only_the_allowlist_names_the_held_out_scene` | ✓ | ✓ | ✓ |
| **S3** | **the held-out truth artifact is hand-edited (a radius nudged)** | `scene_truth_city_block_b.json` | `test_the_held_out_truth_artifact_equals_a_fresh_derivation` | ✓ | ✓ | ✓ |
| **S4** | **a COLLISION geom moves: `bldg_1` shifts 5 cm** | `city_block.xml` | `test_the_city_block_collision_model_is_byte_frozen` | ✓ | ✓ | ✓ |
| S5 | a visual-only geom becomes a collider | `city_block.xml` | compile refused (`shopfront_1` is a non-convex shell) | ✓ | ✓ | ✓ |
| S6 | a visual mesh gains mass (`density="0"` dropped) | `city_block.xml` | `test_the_body_inertial_model_is_byte_frozen` | ✓ | ✓ | ✓ |
| S7 | a person capsule leaves group 4 — capsule and mesh both render | `city_block.xml` | `test_the_person_bodies_kept_their_capsules` | ✓ | ✓ | ✓ |
| S8 | a decoration is renamed into the obstacle namespace | `city_block.xml` | `test_the_logical_obstacle_set_is_frozen` | ✓ | ✓ | ✓ |
| S9 | the held-out scene reuses a development facade texture | `city_block_b.xml` | `test_the_held_out_scene_shares_no_texture_with_the_development_scene` | ✓ | ✓ | ✓ |
| S10 | an asset's recorded digest and its bytes disagree | `PROVENANCE.json` | `test_every_built_asset_matches_its_recorded_digest` | ✓ | ✓ | ✓ |
| S11 | the wheel stops shipping the textures (package-data glob dropped) | `pyproject.toml` | `test_the_packaged_wheel_would_carry_the_assets` | ✓ | ✓ | ✓ |
| S12 | the held-out artifact fabricates a transcription section | `scene_truth.py` | `test_the_held_out_truth_artifact_equals_a_fresh_derivation` | ✓ | ✓ | ✓ |
| S13 | storefront art creates a SECOND door instance (R14's invariant) | `city_block.xml` | `test_the_block_still_grounds_exactly_one_door` | ✓ | ✓ | ✓ |
| S14 | the frozen suite's locked scene digest is hand-edited | `embodied_plan_v1/manifest.json` | `test_manifest_hash_locks_every_physical_input_and_unique_seed` | ✓ | ✓ | ✓ |
| S15 | the transformed-scene re-rooter forgets `texturedir` again | `metamorphic.py` | `test_transform_moves_every_landmark_and_keeps_every_name[mirror_y]` | ✓ | ✓ | ✓ |

**15/15 RED, 15/15 byte-restored, 15/15 green after restore.** The sweep was run
twice: once against the tree before the metamorphic fix (14 seeds), and again in
full against the **final shipped tree**, which is the run tabulated here. The
final sweep postdates the last source write.

Canaries worth quoting, because they show the mutation was live rather than
merely written to disk:

```
S4   mutated: signature=2fbd70e8615fa6ff6c0defd0aae3e5ffd2f03d88dca68c6b9ccc330756e86076 count=68
     clean  : signature=4e3e13e37a99f79d26e9fbff3f3241028ed301b4f4a049a1ce830b8870d41537 count=68
S6   mutated: pedestrian_1 body_mass=2881.668425      <- +2.66 tonnes of decoration
     clean  : pedestrian_1 body_mass=225.072075
S7   mutated: pedestrian_1_body group=0 (default mjvOption draws 0,1,2)
     clean  : pedestrian_1_body group=4
S8   mutated: visual_obstacles=45                     <- the robot now brakes for an awning
     clean  : visual_obstacles=44
S13  mutated: door_instances=['door_1', 'door_shopfront_2']
     clean  : door_instances=['door_1']
S2   mutated: unexpected=['src/parcel_robot/perception_providers.py']
     clean  : unexpected=[]
S15  mutated: transformed_scene_REFUSED Error: Error opening file 'assets/textures/curb_concrete.png'
     clean  : transformed_scene_compiles ngeom=139
```

### 6.1 The first sweep found five real gaps, and that is the point

An earlier run of the first fourteen seeds was **9/14 RED**. The five that did not
redden were not broken seeds — they were missing tests, and each one is now a
cell that did not exist before:

| seed | what slipped through | test added |
|---|---|---|
| S3, S12 | the held-out truth artifact had **no** golden-file check at all — it could be hand-edited freely | `test_the_held_out_truth_artifact_equals_a_fresh_derivation` |
| S6 | mass was only checked on bodies whose geoms are *all* visual; the pedestrian bodies have capsules too, so a 2.6-tonne mesh passed | `test_the_body_inertial_model_is_byte_frozen` + `test_every_visual_geom_declares_zero_density` |
| S8 | a decoration renamed *out* of `vis_` was invisible to a rule written in terms of `vis_` | `test_the_logical_obstacle_set_is_frozen` |
| S10 | the first draft mutated a provenance *comment* rather than a digest — a weak seed, rewritten to mutate a recorded sha256 | (existing digest cell, now genuinely exercised) |

Recording this because "14/14 RED" on the second run means nothing without the
first run's 9/14 beside it.

### 6.2 Repo-root strays

The harness sweeps the repo root afterwards (R27's addendum). It reports
`seed_table.md` — a **pre-existing tracked file** that predates this card and is
unmodified (`git status` clean for it). No file was left behind.

---

## 7. The pre-registration, restated

Written before the first textured frame and before any asset was composited.
Verbatim content of `scratchpad/w1/PREREGISTRATION.md`, condensed only by
removing the recorded BEFORE table that §2.1 already carries.

* **Instrument:** the PG-1 bench, unmodified except for the `vis_*` → logical-id
  mapping line; the BEFORE column is the bench's own recorded row, not a re-run.
* **T1:** OWLv2-base fp16 CUDA, threshold 0.1, 11-label `WORLD_LABELS`,
  IoU ≥ 0.5, 42 poses: **person recall ≥ 0.50** (was 0.000). Both denominators
  reported; recall on the new one.
* **T2:** **≥5 of the 8 corpus place classes** — the eight declared by
  `city_block.semantics.yaml`, which are also the semantic-map bench's eight
  answerable queries — detected at least once at IoU ≥ 0.5 under the class's
  canonical prompt. Region classes matched against *stuff* boxes, with the
  weakness of box IoU on ground planes disclosed in advance.
* **T2b:** the literal prompts **`door`** and **`storefront`** each produce ≥1
  IoU ≥ 0.5 match; `storefront` is a declared alias of `building`, not a ninth
  class. Reported whether or not T2 passes.
* **T3:** Qwen3-VL-8B fp16, same 6 frames and 3 questions, names **≥3 real scene
  categories**, with the category vocabulary and the excluded
  geometry/rendering words fixed in advance.
* **T4:** physics byte-equivalence, asserted as a measurement: named dynamics
  arrays byte-equal, frozen nav baseline and mutation panel unmoved, and the
  frozen embodied row bit-identical. **Registered consequence: if that row moves
  by any digit, the texture work is reverted, not re-pinned.**
* **Method:** CC0 textures with upstream md5 verified; every added geom `vis_*`
  and non-colliding; no existing geom's physical attributes touched; the
  held-out scene never rendered for perception by this card; identical 42 poses.
* **Declared limits:** textured MuJoCo is not photorealism and is not a D455;
  42 frames of one block is an existence check; `city_block_b` exists so E-2 CAN
  make a claim — this card makes none; nothing here says the detector is good,
  only that the world stopped being unreadable.

---

## 8. Deviations, does-not-prove, and what is owner-gated

### Deviations from the card, with reasons

1. **The pedestrian capsules are hidden, not merely accompanied.** The card says
   "capsule COLLIDERS stay — physics unchanged; visuals ride along". They stay,
   byte for byte, in the model — but a capsule drawn *through* a human mesh is
   worse than either alone, so they move to MuJoCo group 4, which the default
   `mjvOption` does not draw. `group` is a visualization field; the collision
   signature and the rollout are unmoved (§2.6). §4.2 has the three mechanisms I
   measured before choosing.
2. **Those capsules are not, in fact, colliders.** `pedestrian_*`, `owner_*` and
   `cyclist_*` geoms already carried `contype="0" conaffinity="0"` before this
   card. They are LiDAR/semantic markers, not contact geometry. The card's phrase
   is honoured in the sense that matters — they are unchanged — but a reader
   should not infer that people collide in this sim. They do not.
3. **`storefront` is a class alias, not a ninth class.** The card lists it
   alongside `door` as one of the "8 corpus place classes". The sidecar declares
   exactly eight classes and files `storefront` as an alias of `building`. Both
   readings are measured and reported separately (§2.3, §2.4) so the audit can
   score either.
4. **The scene-truth tooling grew a `--scene` flag** rather than gaining a second
   copy. The held-out artifact deliberately omits `transcribed` and
   `transcription_deltas` instead of emitting them empty: those two record a
   disagreement with the episode generator's hand table, nothing generates
   episodes against the held-out block, and an empty delta list reads as
   "checked, agreed". Seed S12.
5. **`pyproject.toml` was edited** although it is not named in OWNS. Without the
   package-data globs a wheel ships a scene whose `<texture file=…>` targets are
   absent and MuJoCo refuses to compile it. Seed S11.
6. **No second semantics sidecar for the held-out scene.** It uses the same
   eight classes and the same geom-name prefixes, so the existing sidecar reads
   it unchanged — which is what "same semantic classes" means, and which keeps
   release-parity at 91 packaged assets.
7. **T1 is reported as a miss and nothing was tuned afterwards.** §2.2.

### does_not_prove

* **Nothing here is evidence about real-world perception.** Textured MuJoCo is
  not photorealism and is not a D455. What is measured is that the *scene*
  stopped being the blocker; the detector's field performance is untouched and
  unmeasured.
* **No generalization claim is made.** `city_block_b` exists so E-2 can earn one.
  This card ran no detector and no VLM on it.
* **42 frames, one block, one revision, one detector, one precision.** PG-1
  measured that torch fp16 and the ONNX fp16 export disagree on identical pixels
  (49 vs 37 true positives); every number here is torch fp16, which is **not**
  the path the repo ships. A reproduction on `owlv2_onnx.py` would move.
* **The person result does not say the humans look human enough.** It says they
  produce a correctly-placed, low-confidence hypothesis where the capsules
  produced none. Whether higher-poly meshes, better lighting, or a calibrated
  threshold closes the gap is unmeasured.
* **`crosswalk` did not improve** (3 → 2 matches) and box IoU against a ground
  plane is a weak metric; PG-2 replaced exactly that metric for its own scoring.
* **The held-out scene's *difficulty* is unmeasured.** It is different; nobody
  has shown it is comparably hard. If E-2 finds it easier or harder than
  `city_block`, that is a property of my layout choices and not of the pipeline.
* **The signage is readable text that no ground truth covers.** Six shop names
  now exist as pixels (`CORNER MARKET`, `DAILY BREAD`, `CITY BOOKS`,
  `NORTH CAFE`, and two more), and the VLM already reads them. No sidecar
  declares them, so a storefront-OCR run would produce `storefront:<name>`
  classes with nothing to grade against. Flagged, not fixed — see owner-gated 3.
* **The `vis_*`/`density=0`/group-4 discipline is enforced on these two scenes
  only.** A third scene author has to obey it; the tests will catch them, but
  nothing teaches them first.

### Owner-gated — none of this was done

1. **Ratifying the digest re-pin.** §4.5. Mechanical and reversible; nothing is
   committed.
2. **The person-recall gap.** Three named options, none taken: raise mesh
   fidelity (higher-poly humans, larger atlases, better lighting); accept a
   calibrated per-class threshold, which is PG-3's territory and not a scene
   change; or accept 0.486-at-0.02 as the honest current state and let E-2
   measure it on held-out pixels. **The detector's threshold must not be tuned to
   make a world look better** — that is the same mistake in a new place.
3. **Shop signage without ground truth.** Either declare the six storefront names
   in a sidecar (making them gradeable) or record that the OCR path must not be
   evaluated on this scene. Today it is neither.
4. **Repository size.** The asset pack adds 9.34 MB of PNG/OBJ to the tree. That
   is small for a sim asset pack and large for a git repo that had none.
5. **`dynamic_city` routes for the held-out block.** `city_block_b` carries mocap
   bodies with the same names, so `DynamicCity.default()` would drive them along
   `city_block`'s routes if anyone loaded it into the live sim. E-2 needs its own
   route set; nothing today loads it.

### Risks I would watch

* The collision signature and the inertial signature are two more pins that a
  legitimate future physics change must move deliberately. That is the intent,
  but it is two more places a re-pin has to be justified.
* `test_held_out_scene.py` greps the whole repo on every run. It is fast today
  (git-indexed, extension-filtered) and will get slower as the tree grows.
* The isolation allowlist exempts `scrum/**` from the *staleness* half so that
  writing this document is not a source edit. The leak half — an unexpected file
  naming the scene — still covers `scrum/**` fully.

---

## 9. Reproduce everything in this document

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel

# the answer keys, regenerated from the scenes (never hand-edited)
.parcel/bin/python -m evals.nav_instruct.scene_truth --check                       # drifted: false
.parcel/bin/python -m evals.nav_instruct.scene_truth --scene city_block_b --check  # drifted: false

# the card's own guards
.parcel/bin/python -m pytest tests/test_scene_assets.py tests/test_held_out_scene.py -q

# the contracts it must not have moved
.parcel/bin/python -m pytest tests/test_city_semantics.py tests/test_scene_semantics.py \
    tests/test_city_orbit_clearance.py tests/test_dynamic_city.py tests/test_portal_world.py \
    tests/test_viewer_panel.py tests/test_nav_instruct_scene_truth.py \
    tests/test_scene_surface_truth.py tests/test_embodied_plan_eval.py -q

# the gate
.parcel/bin/python scripts/ci_gate.py --tier commit
```

Scratch artifacts (will not survive; every fact they carry is restated above):

* `scratchpad/w1/PREREGISTRATION.md` — written before the first textured frame
* `scratchpad/w1/fetch_textures.py`, `build_assets.py`, `humanoid.py` — the asset
  build chain, and `texcache/provenance.json` with the upstream md5s
* `scratchpad/w1/physics_equivalence.py` + `physeq_final.json` — the array audit
  and the 3,000-step rollout
* `scratchpad/w1/seed_harness.py` + `seed_results.json` + `seeds.log` — 15 seeds
* `scratchpad/w1/bench/` — the 42 textured frames, their manifest, and the OWLv2 /
  VLM results; `diag_person.json` and `diag_person_before.json` — the
  low-threshold person probe and its untextured control
* `scratchpad/w1/t2_coverage.json`, `t2_coverage_before.json` — T2/T2b
* `scratchpad/w1/gate_baseline.txt` (18:49:49Z), `gate_final.txt` (19:57:06Z, the
  metamorphic RED), `gate_final2.txt` (20:14:56Z, PASS), `gate_final3.txt`
  (20:21:46Z, PASS — quoted in §1.2), `gate_final4.txt` / `gate_final5.txt`
  (the concurrent card's reds, §1.2)
* prior bench, read-only: `scratchpad/perception/bench-owl/` (frames, code,
  results) — reused, not re-derived
