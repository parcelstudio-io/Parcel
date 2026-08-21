# Perception generalization — what the evidence says · Fable · 2026-08-21

Two recon agents, three literature sweeps, two GPU benches with
pre-registered criteria. Reports in this folder. The result overturns the
premise I started from, in our favour on assets and against us on the world.

## 1. The stack is far more built than believed — and the weights work

The recon corrected my brief: the 9 "skipped for want of weights" gate tests
**skip on an env flag, not missing weights.** The weights are on disk and
functional:

* `~/.cache/parcel/siglip2-b16/` (398 MB) — `PARCEL_SIGLIP2_ONNX=1` →
  **28 passed, 0 skipped**; real cosine grounding works
  (`streetlight`→`lamppost` 0.962) and correctly refuses cross-class pairs.
* `~/.cache/parcel/owlv2-b16/` (160 MB) — `PARCEL_OWLV2_ONNX=1` →
  **13 passed**; already proves pixels → detect → localize → world-point on
  EGL-rendered frames, within the repo's localization budget.

The pixel path is **built but unattached**: `runtime.attach_camera_ingress()`
exists with **zero non-test call sites**. The live mission path instead reads
MuJoCo ground truth (`extract_city_semantics` over geom names → a 12 m/±70°
frustum stamped `confidence: 0.98`), and `PerceptionChain` tier T0 is a
*documented identity no-op*. So the cutover is a wiring-and-quality problem,
not a build.

**If the labeled world vanished tomorrow:** the entire geometric and safety
stack survives — LiDAR → occupancy → A*, SafetySupervisor, reactive gates,
and crucially **person-yield, which rides a separate dynamic-agent channel**.
What breaks is every `navigate_to` naming a scene thing.

## 2. The blocker is the WORLD, not the perception stack

Two independent benches converged, one with a decisive control:

| Person recall | Parcel renders | Real photos |
|---|---|---|
| OWLv2-base fp16 | **0/69** | 127/156 (81%) |
| Grounding-DINO tiny | 5/69 (7%) | 145/156 (93%) |
| YOLO-World-S | **0/69** | 141/156 (90%) |
| Qwen3-VL-8B (yes/no) | 0/6 frames | 6/6 frames |

Prompt engineering does not move it. The VLM control is decisive: it
describes our frames as *"a stylized 3D scene with colorful geometric
shapes"* and the only object it names is **the Go2 robot itself** — the
scene's one textured mesh. Pedestrians are flat-coloured capsules with sphere
heads. `city_block.xml` has 48 material references and **zero texture
images**.

**Consequence: no perception number measured in this world means anything**,
and unskipping the 9 gate tests against this scene would *encode 0% person
recall as expected behaviour*. Keep them skipped.

## 3. What the mapping bench proved and disproved

Built a real semantic map from 120 rendered RGB-D frames on the GPU:

* **Geometry and fusion: sound and cheap.** 130 ms/frame, peak 1.19 GB VRAM,
  **108 KiB for 36 places**. Where the detector fires correctly, back-projection
  is excellent — the lamppost localizes to **1–3 cm**.
* **Text retrieval: fails.** Only 2 of 8 queries beat a random-scatter null
  control. SigLIP2 text→place cosine spans 0.060–0.135 with top-vs-runner-up
  margins of 0.0004–0.01 — near-chance ranking.
* **Abstention: fails outright — the safety-critical finding.** No threshold
  separates present from absent queries. **"Narnia" scores 0.073 and would
  send the robot to (−3.19, 4.10).** Today rows 10–13 of the corpus refuse
  correctly *because the chain checks a closed label set*; delete the labeled
  world and that refusal capability disappears with it. The detector is
  innocent — OWLv2 never once fired "coffee shop" in 120 frames. The
  hallucination lives entirely in embedding-space retrieval.
* **The answer key is wrong.** Buildings localize 1–3 cm from the visible
  **facade** and 1.2–1.7 m from the geom centre — 6/6. That is correct sensor
  behaviour; a depth camera sees surfaces, never centroids.
  `scene_truth.json`'s centre+radius convention is *unmeasurable by any RGB-D
  sensor*, so it would mis-grade a working pipeline.

## 4. Free performance, independent of everything else

The incumbent detector runs **int8 ONNX on CPU at 560 ms/query (1.8 Hz)** —
never tried on the RTX 5000 Ada. On GPU fp16 it is 50.9 ms, and **73% of the
remaining latency is CPU-side preprocessing that scales with source
resolution** though the model always sees 960×960. GPU fp16 + halving the
input edge: **560 ms → 15.7 ms, a 36× speedup, bit-identical tensors, same
`Detector` protocol.** SigLIP-2 goes 49.3 ms → 4.07 ms.
Contention, not capacity, is the real constraint: with an 8B VLM generating,
detector p95 goes 56 → 150 ms — **the person-yield path must never queue
behind a scene description.**

## 5. The fork the owner must decide

Everything above says: fix the world first. Four ways, and this is a real
architectural decision, not a detail:

1. **Texture the existing MuJoCo city.** Cheapest, keeps physics and the Go2
   rig, incremental. Still synthetic; buys detector plausibility, not
   photorealism, and no benchmark comparability.
2. **Import photorealistic scanned assets into MuJoCo.** Middle cost; real
   textures, real signage; keeps the whole control stack.
3. **Dual-sim: keep MuJoCo for control, add Habitat (HM3D/HSSD) for
   perception evaluation.** Highest strategic value — it is the standard
   ObjectNav/GOAT venue, so it fixes the perception gap *and* the benchmark
   comparability gap named in the benchmark synthesis. Cost: a second
   simulator and a scene-interchange seam.
4. **Migrate to Isaac Sim.** Photoreal + robot physics in one, but the
   largest migration and it would put the entire audited control stack back
   in play.

**Recommendation: 3, staged behind 1.** Texture the current city first so the
existing pipeline can be exercised end-to-end this week, and stand up Habitat
as the *evaluation* venue where generalization claims must be earned on
held-out scenes. That sequencing gets a working cutover fast without letting
us claim generalization we have not measured.

## 6. What proceeds regardless of the fork

Three cards, all needed under every option, all dispatched now:
**PG-1** GPU fp16 + downscale detector path (36×, pure win) ·
**PG-2** surface-based ground-truth convention (or every building query
mis-grades) · **PG-3** calibrated abstention (the safety-critical one; the
identified mechanism is detector-label agreement + evidence count, since
OWLv2's label head *did* abstain correctly where cosine did not).
