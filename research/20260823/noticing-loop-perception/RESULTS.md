# H6 — the noticing loop · RESULTS (Opus) · 2026-08-23/24

Contract: `DESIGN.md` (criteria pre-registered there; none moved). Evidence
tier **desktop / replay** — `ls /dev/video*` found no camera on this host, so
the DESIGN's fallback venue applies: the real-photo set and the render set
streamed through the repo's own `recorded` backend. No `desktop-real-sensor`
row exists. Hosted spend **$0.00**.

## What was run

```bash
# corpora (rebuilt — see "deviations")
.parcel/bin/python harness/build_photo_corpus.py  $SCRATCH/corpus   # 156 COCO val2017 photos
.parcel/bin/python harness/build_render_corpus.py $SCRATCH/corpus   # 42 city_block renders (EGL)
.parcel/bin/python harness/build_clips.py         $SCRATCH/corpus   # 3 replay clips + box transforms
# my own daemon, my own socket, never the owner's
env PARCEL_PERCEPTION_PROVIDER=cuda_fp16 PARCEL_OWLV2_ONNX=1 PARCEL_SIGLIP2_ONNX=1 \
  .parcel/bin/python -m parcel_robot.perception_daemon \
  --socket research/20260823/noticing-loop-perception/h6_perception.sock --preload
harness/run_loops.sh   $SCRATCH/corpus $SCRATCH/run      # 8 loop runs x3 passes (60s, 150s, 150s)
harness/run_offline.sh $SCRATCH/corpus $SCRATCH/offline  # ingress before/after/RGB-only + 6 sweeps
.parcel/bin/python harness/novelty_paired.py   ...   # P5, paired protocol
.parcel/bin/python harness/novelty_auc.py      ...   # P5, frozen-gallery protocol
.parcel/bin/python harness/preprocess_bench.py ...   # CPU-side share, no GPU session
.parcel/bin/python harness/analyze.py --runs ... --sweeps ...   # every criterion, from raw rows
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h6 \
  .parcel/bin/python -m pytest tests/test_h6_noticing.py -q     # 8 passed, 1 skipped
env -u TMPDIR PARCEL_H6_SOCKET=<sock> ... -m pytest tests/test_h6_noticing.py -q  # 9 passed
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h6 .parcel/bin/python -m pytest \
  tests/test_dec0_debt_ratchet.py tests/test_decig2_import_ratchet.py -q          # 23 passed
```

## Environment (recorded at every headline row, `results/score_*.json`)

RTX 5000 Ada 32 GB, 192-core host. My daemon resolved and **honoured**
`cuda_fp16` / `CUDAExecutionProvider` on every run (`provider_profile` in each
report), 3.7 GB VRAM. The GPU and the CPU were shared throughout:

| concurrent load | owner | effect on H6 |
|---|---|---|
| gemma-4-26b-a4b CUDA server `:8081` (15.3 GB) | H2 | GPU 77–100 % busy during pass 1 |
| Ministral-8B CUDA `:8082` (6.2 GB), H2's own perception daemon (3.4 GB) | H2 | VRAM 31 GB / 32.7 GB |
| **Qwen3-32B judge, llama.cpp CPU, 48 threads, `:8090`** | H2 | **host load 100–180 for passes 2–3** |

That last row is the finding that shaped everything else (see Surprise 1).
Timeline: pass 1 ran 22:32–22:40, pass 2 22:47–23:16, pass 3 23:17–23:41; the
judge server started at 22:32:28 (`ps -o lstart`) and the host load sampler,
started late at 23:26, then recorded 100–180 continuously to the end
(`results/host_load_samples.txt`) — pass 1's own load average was therefore
NOT sampled and is only inferred from its latencies. Headline rows were
re-measured twice (`score_shared.json`, `score_iso.json`) and a genuinely
quiet host never arrived: `harness/wait_and_remeasure.sh` polled for a
load < 40 window for 55 min and was stopped with the load still climbing
(last sample 207). **Pass 1 is the least-contended
observation and is quoted as the headline; passes 2–3 are the degradation
ladder, not a contradiction of it.**

## Pre-registered measurements

| row | criterion | measured (best observation) | met? |
|---|---|---|---|
| P1 | sustained FPS ≥ 10 at 640×360 | **7.38 fps** free-run, 443 frames/60 s, 10 phrases (2.8–3.6 fps at host load 170) | **NO** |
| P2 | detect p50 / p95, p95 < 100 ms | **119.6 / 132.7 ms** daemon-side (worst pass: 359 / 816 ms) | **NO** |
| P3 | frames published past 300 ms TTL = 0 | **0 / 443** free-run and **0 / 460** at 10 Hz; histogram below | **YES** (loaded host: 254/436 — NO) |
| P4 | false noticings / min ≤ 1 at τ | **0.40 /min** photos, **0.00 /min** renders (τ = 0.35, 150 s, hand-checked) | **YES** |
| P5 | novelty AUC new-vs-seen ≥ 0.8 | **0.724** paired all-label (142 pairs); 0.802 person-only; 1.00 identical-pixel | **NO** |
| P6 | photo person recall ≥ 0.75 at render FP ≤ int8 | **0.775** instance / 0.987 image at threshold **0.10**; render person FP 0.00/frame = int8's 0.00 | **YES** |
| P7 | contended p95 ≤ 150 ms, 0 past TTL | **177.6 ms** p95 with the 26B generating (8 963 tokens); **0 / 332** past TTL | **NO** (p95) / YES (TTL) |
| P8 | map writes with RGB-only | **0** — and 33 counted errors, 0 frames published | reported |

### P3 latency histogram (photos, free-run, pass 1, ms capture→publish)

| 0–50 | 50–100 | 100–150 | 150–200 | 200–250 | 250–300 | >300 |
|---|---|---|---|---|---|---|
| 0 | 0 | 416 | 26 | 0 | 1 | **0** |

Budget per frame at that operating point: capture 0.05 ms (a replay read — a
real camera adds exposure + transfer, so this row is optimistic by that
amount), detect 119.6 ms, crop embeddings 16.6 ms (3.2 crops/frame), the
noticing decision 0.7 ms.

### P3 through the PRODUCT path (`CameraIngress`, measured not restructured)

| venue | detector | res | capture→publish p50 | expired at publish | map writes | fresh-gated map writes |
|---|---|---|---|---|---|---|
| before (today's default) | `cpu_int8` in-process | 1280×720 | **1072 ms** | **16 / 16** | 96 | **0** |
| after | H6 daemon `cuda_fp16` | 640×360 | **343 ms** | 24 / 32 | 261 | **47** |
| RGB-only (P8) | H6 daemon | 640×360 | — | — | **0** | **0** |

The DESIGN's inherited "562 ms" is today **1072 ms** on this host under load;
either way 16/16 frames are already expired when they land, and
`observations_from_frame(..., require_fresh=True)` therefore writes **nothing**
to the map. Moving to the daemon at 640×360 cuts that 3.1× and turns 0 fresh
map writes into 47 — but the product path still misses the 300 ms TTL at
p50 under this host's load, while the H6 loop (same models, less per-detection
work) makes it. **The remaining gap in the product path is the ingress' own
per-detection localize + thumbnail + depth-patch work, not the detector.**

### P6 operating point — the repo's own `OwlV2Detector` + `localize_frame`

One inference pass per (corpus, provider) at a 0.005 floor with the 64-box cap
lifted to 512; thresholds swept by filtering. That filtering is exact for
greedy per-label NMS and was **verified** by re-running 6 frames at a real
threshold 0.10: 6/6 agreed, 0 disagreed (`results/score_sweeps.json`).

| threshold | photos native fp16 recall (inst / image) | photos native int8 recall | renders 1280 fp16 recall | renders 640 fp16 recall | photo person FP/frame fp16 | render person FP/frame fp16 (int8) |
|---|---|---|---|---|---|---|
| 0.02 | 0.849 / 0.987 | 0.763 | 0.661 | 0.810 | 9.53 | 1.86 (0.98) |
| 0.05 | 0.818 / 0.987 | 0.726 | 0.164 | **0.746** | 3.10 | 0.43 (0.07) |
| **0.10** | **0.775 / 0.987** | 0.677 | **0.000** | 0.238 | 1.14 | **0.00 (0.00)** |
| 0.15 | 0.722 / 0.981 | 0.595 | 0.000 | 0.032 | 0.57 | 0.00 (0.00) |
| 0.20 | 0.625 / 0.962 | 0.494 | 0.000 | 0.000 | 0.32 | 0.00 (0.00) |

**Threshold 0.10 — the repo's existing default — satisfies P6**: real-photo
person recall 0.775 ≥ 0.75, render-side person FP 0.00/frame, equal to the int8
incumbent's 0.00, with better all-label precision (0.422 vs 0.301 on renders,
0.361 vs 0.242 on photos). The loop's own 640×360 costs almost nothing on
photos: 0.757 instance recall vs 0.775 at native size.

## Surprises (each one is a finding, not a caveat)

1. **The loop is CPU-bound at 640×360, not GPU-bound.** Detect latency tracked
   the host CPU load, not GPU utilisation: 119.6 ms p50 in pass 1 with the GPU
   96–100 % busy, 311 ms p50 in pass 3 at load 170 with the GPU 2–40 % idle. The
   thing that stops this loop reaching 10 Hz on this box is another process's
   48 CPU threads, not the RTX 5000.
2. **Downscaling to 640×360 makes preprocessing *slower*.**
   `OwlV2Detector._preprocess_image`'s bit-identical fast path is guarded by
   `_seam_is_clean`, which is only true when the source long edge exceeds 960.
   At 1280×720 the fast path runs (183.9 ms median under load); at 640×360 it
   falls back to the reference path (**239.0 ms**, ratio 0.77 —
   `results/preprocess_bench.json`, interleaved arms, no GPU session). The
   2026-08-21 bench's "halving the input edge = free 2.8×" does **not** hold
   through this repo's own preprocessor at the loop's resolution.
3. **Renders are not blind — they are under-confident.** Person recall on the
   (now textured, post-W-1) city scene is 0.000 at threshold 0.10 and 0.661 at
   0.02. OWLv2 finds the pedestrians and scores them below the gate. The
   photo/render gap the bench reported as 0/69 vs 127/156 is, at least on
   today's scene, a **score-calibration** gap, not an absence of signal.
4. **Downscaling renders raises render recall 4.5×** (0.164 → 0.746 at
   threshold 0.05, 1280 → 640). The model's 960² input up-samples the small
   source; sim pixels apparently survive that better than they survive
   down-sampling.
5. **On real photos fp16-CUDA beats int8-CPU everywhere** — recall 0.775 vs
   0.677 and precision 0.361 vs 0.242 at threshold 0.10. `perception/providers.py`'s
   `MEASURED_PRECISION_QUALITY` note ("under onnxruntime the recall direction
   REVERSES, int8 .1443 vs fp16 .1242") is a **renders-only** artifact; it does
   not survive contact with photographs. The note should be qualified.
6. **The product module's pure-Python gallery cannot be in-loop.** With a
   filling gallery of SigLIP-2 vectors, `NoveltyGallery` cost **34–55 ms p50
   and 130–195 ms p95** *per frame* across the three passes, versus 0.7–1.8 ms
   p50 for the vectorised gallery the measurements used — a third to a half of
   the frame budget spent on arithmetic numpy does in microseconds
   (`photos_free_puregallery*` rows). The module is correct and testable
   anywhere; a vectorised gallery is a prerequisite for wiring it in.
7. **Novelty lives in a tiny range.** In SigLIP-2 crop space, a re-encountered
   instance scores 0.051–0.065 mean novelty and a genuinely new one
   0.072–0.087. The pre-registered τ = 0.35 therefore only ever fires on the
   first sightings of a session or on an out-of-distribution crop: 6 noticings
   in 150 s on photos, **1** in 150 s on renders. The τ curve (replayed through
   the product gate, `tau_sweep_uncapped`) is the calibration this needs:

   | τ | 0.10 | 0.20 | 0.25 | 0.30 | **0.35** | 0.40 |
   |---|---|---|---|---|---|---|
   | noticings/min (photos) | 23.2 | 15.2 | 10.4 | 4.8 | **2.4** | 0.8 |
   | false noticings/min | 8.78 | 4.39 | 3.19 | 1.20 | **0.40** | 0.40 |

   τ = 0.35 is the lowest grid point that holds P4's ≤ 1/min budget.
8. **P4's automated "false" verdict survives a hand look.** The contact sheet
   (`results/noticings_photos.png`) shows 6 photo noticings: five are real
   people/an umbrella; the single FALSE is a `car 0.20` box on a truck-mounted
   warning sign — a COCO label-granularity disagreement, not an invented
   object. The render sheet's single noticing is a correct `lamppost`.
9. **P5's easy protocol is an artifact.** Scoring "first appearance = new" as
   the loop runs gives AUC 1.00 — because the gallery starts empty and
   "first" correlates with "early". Held out properly (gallery frozen, probe
   never in the gallery) the same signal gives 0.724 all-label / 0.802 person,
   and re-encountering the *same pedestrian from a new range and bearing* is
   separated from a new object barely better than chance in two of three
   frozen-gallery splits (0.75, 0.51, 0.34 — n_new 11, 9, 1).

## What P7 measured, exactly

`photos_10hz` vs `photos_10hz_contended`, same pass, same 60 s: detect p50
112.2 → 156.6 ms, p95 128.4 → **177.6 ms** (+38 %), fps 7.65 → 5.53, while my
harness kept `:8081` generating 256-token completions back to back (36
completions, 8 963 tokens, 1 error). Zero frames passed the TTL in either arm.
The reasoner on `:8081` is H2's server (up and healthy when I reached P7, as
the task allows); I did not start a second one, so no extra VRAM was taken.

## Product changes (flag-off, harness-only reachability)

* **new** `src/parcel_robot/perception/noticing.py` (395 lines, pure stdlib,
  leaf imports, zero `noqa`): `Noticing`, `NoticingGate`, `NoticingLoop`,
  `NoveltyGallery`, `Observation`. **Nothing in the product imports it** — it
  is reachable only from `research/` and its test. No env flag was added
  because no product code path was touched.
* **new** `tests/test_h6_noticing.py` — 8 offline cells + 1 opt-in cell that
  runs the decision over a live daemon when `PARCEL_H6_SOCKET` is set.
* `perception_daemon/server.py` was **not** modified: the DESIGN's "move
  preprocessing into the daemon" knob is unnecessary — preprocessing already
  happens daemon-side, and measured IPC overhead is 2.2–4.8 ms per frame.

## Does not prove

Orin throughput (no aarch64 ORT wheel exists); live-scene recall (no camera —
every "real photo" is a photograph, not this room); that the runtime consumes
noticings (product wiring is a milestone card, and the module is imported by
nothing); anything about a D455 or about depth (P8 is a null result, not a
depth measurement). Every latency row was taken on a host carrying another
executor's 48-thread CPU model server, and the DESIGN's "re-measure alone"
step could not be satisfied — the best rows here are *upper bounds on
latency*, i.e. P1/P2 may pass on a quiet host and this experiment cannot say.
The render venue is **not** the 2026-08-21 bench's frames: that scene has since
been textured (card W-1), so the 0/69 comparison is against a different scene.

## Deviations from the DESIGN (all recorded before measuring)

1. The bench's 156 real photos and 69 render person-instances live in a
   deleted scratchpad. The photo set was rebuilt from COCO val2017 through the
   HuggingFace datasets-server (`images.cocodataset.org` is unreachable from
   this host): 156 photos, 650 non-crowd person instances, 14 crowd IGNORE
   regions, taken in dataset order with no area filter. The render set was
   re-rendered from `city_block.xml` at today's revision: 42 frames, 189 person
   instances, ground truth from the repo's own `SegTruthDetector`.
2. "n = 156" in the bench does not say whether it counts photos or instances,
   so **both** recalls are reported and neither was chosen after the fact.
3. P5 is reported under three protocols because the obvious one is confounded
   (Surprise 9). The headline is the paired, best-powered one.
4. The loop rows use a vectorised gallery injected into `NoticingLoop`
   (Surprise 6); `tests/test_h6_noticing.py` pins the two implementations to
   the same scores, and the pure-gallery cost is reported as its own row.

## Raw files

`results/` (900 KB): `score_v1.json` (pass 1 — headline), `score_shared.json`,
`score_iso.json` (per-run latency stats, τ curves, per-run `nvidia-smi`),
`score_sweeps.json` (P6, every threshold × corpus × provider),
`ingress_*.json` (product-path freshness + map writes),
`auc_paired_*.json` / `auc_*crossview*.json` / `auc_photos.json` (P5),
`preprocess_bench.json`, `query_scaling.json` (inconclusive under load — no
monotonic trend in Q; IPC overhead 2.2–4.8 ms is the usable part),
`noticings_*.png` (P4 hand-check), `host_load_samples.txt`.
Full per-frame / per-detection rows (~19 MB) stay in the session scratchpad
under `.../scratchpad/h6/{run,run_v1,offline}/`; `harness/*` regenerates
everything from the repo.

## Cost

$0.00 — no hosted call was made.
