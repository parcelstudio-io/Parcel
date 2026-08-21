# PG-1 — the detector on the GPU · status

**Card:** `scrum/20260821/task_6/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable (DEFERRED — this doc is written to be audited cold, weeks
from now, with nobody to ask) · **Date:** 2026-08-21

---

## 0. Headline — what the card asked for, and what the measurement said

The card asked for a GPU path behind the existing `Detector` protocol, a
"free 2.8× bit-identical" source downscale, the same for SigLIP-2, and a
contention guard. All four landed. **Three of the card's inherited numbers did
not reproduce against the code this repo actually ships, and one of them is
backwards.** Every correction below is measured, with denominators.

| Inherited claim | Measured on the repo's own code | Verdict |
|---|---|---|
| "560 ms → 15.7 ms, **36×**" | **524.4 → 83.0 ms p50, 6.3×** under onnxruntime | overstated ~5.7× |
| "halving the source edge is a **free 2.8×**, bit-identical tensors" | **not bit-identical** (max Δ 1.278 over 5.5% of elements) and **41% SLOWER** (83.0 → 117.4 ms), −21.6% relative recall | refuted on both axes |
| "int8 costs quality too (**.144 vs .164 recall**)" | within one runtime the recall direction **reverses** (int8 .1443 > fp16 .1242); int8's real cost is **precision** (.177 vs .278) | corrected |
| "detector p95 56 → 150 ms with a VLM generating (2.69×)" | cross-process, shipping path: **85.5 → 131.8 ms p95 (1.54×)**; ~2.1× on the GPU portion alone | direction confirmed, magnitude re-measured |

**What is genuinely won:** the provider change is worth **6.3× on the detector**
and **13.7× on the SigLIP-2 image encoder**, and a *provably bit-identical*
preprocessing restructure is worth a further **1.31×** on the GPU path. Combined
detector + one crop embedding: **570.3 ms → 86.4 ms per query, 1.75 Hz → 11.6 Hz.**

**One thing found that was not on the card and matters more than the speedup:**
onnxruntime-gpu advertises `CUDAExecutionProvider` in `get_available_providers()`
even when its CUDA libraries are missing, then **silently builds a CPU session**.
This happened on this machine during PG-1's own measurement pass: a detector
labelled `cuda_fp16`, logging "fp16", running the fp16 graph on the CPU at
**726 ms/query** — slower than the 524 ms int8 path it displaced. The code now
refuses that session (`assert_provider_honoured`) instead of running it.

---

## 1. Gate — verbatim

Baseline read **before** any edit (the R22–R26 chain had just landed; working
tree already carried that uncommitted work):

```
CI GATE — tier=commit  (2026-08-21T10:57:42Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7540 collected = 7498 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.28s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              7489 passed, 9 skipped, 42 deselected, 5 warnings in 302.41s (0:05:02)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 322.0s
```

Final, after the last edit. Two runs: **11:39:46Z** immediately after the last
*source* edit, and **11:49:37Z** after this document was written — identical
verdicts and identical counts on every line (a markdown file under `scrum/`
cannot change a test outcome, but the house rule says re-run after the final
edit, so it was re-run). The 11:39:46Z run is quoted:

```
CI GATE — tier=commit  (2026-08-21T11:39:46Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7634 collected = 7592 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.35s
[  PASS] HARD  release-parity-integrity   10 passed in 0.76s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.22s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              7583 passed, 9 skipped, 42 deselected, 5 warnings in 292.68s (0:04:52)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 317.3s
```

* **Skips unchanged: 9 → 9.** The nine deliberately-skipped gate cells
  (`test_owlv2_detector.py` ×2, `test_siglip_real_embeddings.py` ×3+3,
  `test_p3_storefront_ocr.py` ×1) were not touched and no skip condition was
  edited. `tests/test_siglip_real_embeddings.py` was not modified at all — the
  new SigLIP-2 cells live in a separate file for exactly that reason.
* Collected 7540 → 7634 (**+94** new tests). Passed 7489 → 7583.
* ruff `new 0` against the pinned 7-fingerprint baseline.
* `model-off-non-inferiority` (the SigLIP / OWLv2 flag-off byte-equal cells)
  stayed green: with `PARCEL_OWLV2_ONNX` / `PARCEL_SIGLIP2_ONNX` unset the
  loaders still return `None` before any provider work happens.

---

## 2. What landed

| File | Status | What |
|---|---|---|
| `src/parcel_robot/perception_providers.py` | **NEW** | Provider resolution, the documented fallback order, the honoured-provider fail-closed check, `preload_dlls` handling, the measured precision-quality register |
| `src/parcel_robot/perception_contention.py` | **NEW** | The contention guard: leases, admission rule, policy validation |
| `src/parcel_robot/detection_adapter/owlv2_onnx.py` | changed | Provider plumbing, bit-identical fast preprocess + its seam guard, lossy `source_max_edge` knob, safety lease |
| `src/parcel_robot/instructnav/siglip2_onnx.py` | changed | Provider plumbing (text + vision independently), bit-identical separable resize, fp16 feed cast |
| `tests/test_perception_providers.py` | **NEW** | 20 cells |
| `tests/test_perception_contention.py` | **NEW** | 21 cells |
| `tests/test_siglip2_provider.py` | **NEW** | 22 cells |
| `tests/test_owlv2_detector.py` | extended | +21 cells; existing cells and both skip conditions untouched |

**No caller changed.** `Detector.detect(*, rgb, depth, seg, query)` has the same
signature and the same return type on either provider;
`camera_channel/ingress.py`, `pixel_detections.py`, `perception_chain.py` and
`instructnav/siglip.py` are byte-unchanged. Nothing on the MUST-NOT-TOUCH list
was edited: `realtime/*`, yield/person-stop policy, scene assets, `evals/**`
fixtures, the nine skip conditions.

### 2.1 Config surface

| Env knob | Default | Meaning |
|---|---|---|
| `PARCEL_PERCEPTION_PROVIDER` | `auto` | `auto` walks `(cuda_fp16, cpu_int8)`; an explicit pin is honoured or **refused**, never silently degraded |
| `PARCEL_OWLV2_FAST_PREPROCESS` | `1` (on) | The bit-identical preprocess restructure. An escape hatch, not a feature flag |
| `PARCEL_OWLV2_SOURCE_MAX_EDGE` | `0` (off) | The **lossy** source downscale. Off by default; a malformed value disables rather than guesses |

On this repo's venv today (`onnxruntime` 1.28.0, CPU-only, no torch) `auto`
resolves to `cpu_int8` on the same `model_int8.onnx`, verified live:

```
owlv2 : perception provider: requested=auto selected=cpu_int8 precision=int8 ep=CPUExecutionProvider model=model_int8.onnx (first available in fallback order) | rejected: cuda_fp16: CUDAExecutionProvider not registered in this onnxruntime build
sig-t : ... model=text_model_int8.onnx   ... | rejected: cuda_fp16: CUDAExecutionProvider not registered ...
sig-v : ... model=vision_model_int8.onnx ... | rejected: cuda_fp16: CUDAExecutionProvider not registered ...
```

---

## 3. Measured — latency, VRAM, quality

**Setup.** RTX 5000 Ada (32,760 MiB), driver 595.84 / CUDA 13.2. The repo's own
`OwlV2Detector`, run under a scratch venv with `onnxruntime-gpu==1.28.0` (exact
version match with the repo's CPU `onnxruntime` 1.28.0) so provider is the only
variable. 42 rendered `city_block.xml` frames, 1280×720, 11 query labels,
batch 1, threshold 0.1. Latency n=20 timed after 3 warm; quality over all 42
frames with the 2026-08-21 bench's own pre-registered matcher (per-label greedy,
IoU ≥ 0.5). GPU otherwise idle at 925–929 MiB.

### 3.1 OWLv2

| Cell | detect p50 | detect p95 | preprocess p50 | VRAM Δ | TP/298 | micro R | macro R | precision |
|---|---|---|---|---|---|---|---|---|
| **A** `cpu_int8` (incumbent) | **524.4** | 556.8 | 44.2 | 0 | 43 | .1443 | .1652 | .1770 |
| **B** `cpu_int8`, fast preprocess OFF | 565.4 | 578.6 | 63.3 | 0 | — | — | — | — |
| **C** `cuda_fp16` | **83.0** | 89.8 | 43.7 | 2394 | 37 | .1242 | .1652 | .2782 |
| **C2** `cuda_fp16`, fast preprocess OFF | 109.1 | 133.9 | 65.1 | 2064 | — | — | — | — |
| **D** `cuda_fp16` + `source_max_edge=640` (LOSSY) | 117.4 | 135.5 | 74.0 | 2064 | 29 | .0973 | .1649 | .2544 |

Derived:

* **Provider change A→C: 6.32× p50** (524.4/83.0), 6.20× p95. Not 36×.
* **Bit-identical fast preprocess:** 1.49× on preprocessing alone (65.1→43.7);
  **1.31× end-to-end on the GPU path** (C2→C), 1.08× on the CPU path (B→A,
  where the 500 ms model dominates). Preprocessing is **53% of the GPU cell's
  total time** — on the GPU it is the thing worth optimising.
* **The lossy downscale C→D is a 1.41× SLOWDOWN**, not a speedup, *and* costs
  8 of 37 true positives (−21.6% relative). Mechanism in §4.2.
* Cell A reproduces the 2026-08-21 bench's incumbent quality row **exactly**
  (tp 43, n_pred 243, micro .144295, macro .165210, precision .176955), which is
  the harness cross-check that makes the other rows trustworthy.

### 3.2 SigLIP-2 (crop 300×200, n=20)

| Cell | image p50 | text p50 (uncached) | VRAM Δ |
|---|---|---|---|
| **E** `cpu_int8` | 45.94 ms | 27.93 ms | 0 |
| **F** `cuda_fp16` | **3.35 ms** | **1.43 ms** | 1338 MiB |

**13.7× on the image encoder, 19.5× on text.** (The 2026-08-21 bench measured
49.3 → 4.07 ms under torch; onnxruntime lands slightly better.)

### 3.3 Stack total

| | detector + 1 crop embed | rate |
|---|---|---|
| incumbent `cpu_int8` | 524.4 + 45.9 = **570.3 ms** | 1.75 Hz |
| `cuda_fp16` | 83.0 + 3.4 = **86.4 ms** | 11.6 Hz |

**6.6× on the combined per-query cost.** Loop-capable at ~11 Hz where the
incumbent was 1.75 Hz. Still not the card's 36×, and the reason is §4.1.

---

## 4. Where the inherited numbers came from, and why they moved

### 4.1 The 36× was a torch number, not an onnxruntime number

The bench compared `OWLv2 int8 ONNX on CPU` (560 ms) against
`OWLv2 torch fp16 on GPU + a downscale` (15.7 ms). Two things change at once
there: the provider **and the runtime**. Measured inside onnxruntime — the
runtime this repo ships and the one the whole no-torch architecture is built on
(`fetch_owlv2.sh`, `siglip2_onnx.py`) — the GPU fp16 cell is **83.0 ms**, not
15.7 ms.

The gap decomposes cleanly:

* **~43.7 ms is CPU-side preprocessing**, which is unchanged by the provider.
* **~39 ms is the ORT CUDA forward**, against torch's measured 12.9 ms. ORT
  emits a `3 Memcpy nodes are added to the graph for CUDAExecutionProvider`
  warning on this graph, i.e. its op placement is not optimal.

So 36× would require *both* switching to torch *and* accepting the lossy
downscale. Adopting torch is a large, separate architectural decision (it
reverses the deliberate no-torch stance and adds ~3 GB); it is on the owner-gated
list in §8, not taken here.

### 4.2 The downscale is neither free nor bit-identical

**Bit-identity — refuted by measurement.** Against this module's own
preprocessor, decimating 1280×720 to 640×360 and preprocessing changes the
960×960 model input by **max |Δ| = 1.278** (normalised units) across
**152,845 of 2,764,800 elements (5.5%)**. It cannot be bit-identical: the direct
path pads to 1280² and *down*-samples 4/3 to 960; the halved path pads to 640²
and *up*-samples 3/2. Different sample sites, different pixels. The bench's own
report says "bit-identical" in one sentence and "an identical model input"
(i.e. identical *shape*) in the paragraph above it; the strong reading does not
survive contact with the code.

**Free — refuted by measurement.** Two costs compound:

1. The bench produced its 640×360 with `rgb[::2, ::2]`, stride decimation. That
   is nearly free but it *aliases*. Done correctly (a 2×2 box average, which is
   what the half-pixel bilinear kernel degenerates to at an exact factor of 2)
   it costs real work. I implemented the cheap exact-integer path
   (`reshape` + `mean`) rather than the general resize, so this is a fair test.
2. **Downscaling below 960 pushes preprocessing off the fast path.** With a
   640-long-edge source the model *up*-samples, the content/pad seam no longer
   lands on an output-pixel boundary, the seam guard correctly declines, and the
   slow reference path runs. Preprocessing goes 43.7 → 74.0 ms.

Net: 83.0 → 117.4 ms. The knob ships **default OFF**, documented as lossy, with
its measured recall cost recorded.

**What IS bit-identical**, and is therefore default ON, is a restructuring of the
preprocessing arithmetic:

* never materialise the `max(H,W)` padded square — resize the content straight to
  `(960·h//side, 960·w//side)` and paste into a pre-filled grey canvas. Valid
  only when no output sample straddles the content/pad seam, which is **checked
  exactly at runtime** (`_seam_is_clean`), never assumed. True for 1280×720 and
  1920×1080; correctly False for every up-sampled shape.
* do the horizontal blend once over the source rows instead of four wide row
  gathers (`_bilinear_resize_separable`) — the same per-element expression.

One subtlety worth recording because it cost an hour: the canvas dtype **must**
match the resize output. `_bilinear_resize` returns float64 (numpy promotes
`float32 − int64` weights), so writing into a float32 canvas rounds before
normalising and drifts exactly one ULP across ~1.7% of elements. Matching the
dtype makes it exactly equal.

Verified bit-identical (`np.array_equal`, no tolerance) on **42/42 real bench
frames** and on 12 adversarial shapes including RGBA, extreme aspect ratios and
1×1 — pinned by `test_the_fast_preprocess_is_bit_identical_to_the_reference`.

### 4.3 "int8 costs recall" is backwards; int8 costs *precision*

All three rows: same 42 frames, same 11 labels, 298 GT instances, same matcher.

| | runtime | TP | preds | micro recall | macro recall | precision |
|---|---|---|---|---|---|---|
| int8 | onnxruntime CPU | 43 | 243 | **.1443** | .1652 | **.1770** |
| fp16 | onnxruntime CUDA | 37 | 133 | **.1242** | .1652 | **.2782** |
| fp16 | torch CUDA (bench) | 49 | 172 | .1644 | .1756 | .2849 |

* Within onnxruntime the recall direction **reverses**: int8 finds *more*
  objects (43 vs 37), not fewer.
* The bench's ".164" is torch's. **torch fp16 and the fp16 ONNX export are not
  the same numbers** — 49 vs 37 true positives on identical pixels.
* What survives every pairing is **precision**: int8 spends 243 predictions to
  find 43 objects; both fp16 paths spend 133–172 to find 37–49. int8 is ~1.6×
  noisier per true positive. For a stack whose next card (PG-3) is calibrated
  abstention, that is the expensive kind of error.

Recorded in `perception_providers.MEASURED_PRECISION_QUALITY` with denominators,
runtimes and sources; the confound and the reversal are recorded in
`PRECISION_QUALITY_CONFOUND`, and the sim-only caveat in
`PRECISION_QUALITY_DOES_NOT_PROVE`. Seed S10 reddens if any of it is falsified.

**Person recall is 0/69 in every row.** The scene, not the precision, is why.

---

## 5. The contention guard (work item 4) — the safety-relevant part

### 5.1 Mechanism, and why the other option is unavailable

The card offered CUDA streams or an admission rule. **Streams cannot work here,
structurally.** `cudaStreamCreateWithPriority` orders work within one CUDA
context. Parcel's generator is not in this process and never has been: it is
`llama-server`, a separate binary
(`configs/reasoner/llama_cpp_cuda12_oci_b10236.json` → `runtime.cuda_binary`,
entrypoint `app/llama-server`). Work from a different process lands in a
different context, which the driver time-slices with no user-space priority knob
(absent MPS priority partitioning, which this deployment does not run). A stream
priority set inside the Python process would order the detector against *itself*.

So: **admission control.** The long-running generation is refused, because it is
the thing that can wait. **The detector never asks permission — it runs.** That
asymmetry is the priority pin.

### 5.2 Measured, cross-process

Qwen3-VL-8B fp16 generating 64 tokens in a **separate process** (the deployment
shape), repo detector on `cuda_fp16`, 1280×720, n=30:

| condition | 1280×720 p50 | p95 | 640×360 (lossy) p50 | p95 |
|---|---|---|---|---|
| (a) GPU idle | 76.6 | **85.5** | 118.7 | 119.5 |
| (c) VLM generating | 125.9 | **131.8** | 166.9 | 172.6 |

* **1.54× on p95 end-to-end, 1.64× on p50.** That *understates* the GPU effect:
  ~44 ms of the repo detector's time is CPU preprocessing that does not contend.
  Netting it out, the GPU portion goes ~41 → ~88 ms, about **2.1×** — the same
  order as the bench's in-process 2.69×.
* Against `contracts.freshness.DEFAULT_DETECTION_TTL_NS` (300 ms): one inference
  goes from **28.5% to 43.9% of the entire detection TTL**.
* **The downscale does not rescue it** — it is *slower* in both conditions
  (0.72× idle, 0.76× contended). You cannot optimise your way out of a
  scheduling problem.
* VRAM: detector +1,366 MiB; full stack with the 8B VLM **22,848 of 32,760 MiB
  used, 9,912 MiB free** — the ≥6 GB headroom rule held throughout, checked in
  the harness with an abort if it had not.

### 5.3 The rule, and its fail-closed defaults

While any `mission_lease` is held, a generation may start only if its **declared**
duration is within `ContentionPolicy.max_generation_ms_while_active`.

* default budget **0.0 ms** — nothing real starts while a lease is held. There is
  no measured "short enough to be free" generation.
* **undeclared duration (`None`) is refused.** An unknown length is not assumed
  short.
* an **infinite** budget, a **NaN** budget, a budget **≥ the 300 ms TTL**, and a
  **never-expiring lease** are all rejected at construction. A policy that
  silently neuters the guard while still *looking* installed is exactly what a
  deferred audit cannot catch by reading call sites, so it is refused where it is
  written.
* leases carry a TTL (2.0 s default) so a crashed holder cannot starve speech
  forever; expiry logs at WARNING and is counted.

### 5.4 Wiring — one half landed, one half owner-gated

**Landed:** `OwlV2Detector.detect()` takes a lease for the duration of any
inference whose query names a human (`SAFETY_RELEVANT_LABELS`: person, people,
pedestrian, human, owner, child, man, woman — whole-word, so "personal locker"
does not match). A scene description therefore cannot *start* underneath a person
query. The set is deliberately narrow: a lease costs *speech* latency, so
leasing every label would block generation permanently at the CPU path's 1.9 Hz.

**Not landed, owner-gated:** the consumer half — the generation entry point
calling `try_admit_generation`. It lives in `realtime/*`, which this card must not
touch. The seam is: `PerceptionContentionGuard.default_guard()`, called from
wherever a response/generation is initiated, refusing or deferring by
`Admission.retry_after_s`.

### 5.5 HONEST SCOPE — read this before trusting the guard

* **This does not fix a live bug.** Today the person-yield / reactive-safety path
  does **not** consume the detector: it rides the dynamic-agent channel, the live
  mission path reads MuJoCo ground truth (`extract_city_semantics`), and
  `runtime.attach_camera_ingress()` has zero non-test call sites. The guard
  protects the path the perception cutover will *create*. It is landed now because
  the measurement exists now and because retrofitting scheduling after a cutover
  is how safety paths acquire latency bugs.
* **It cannot preempt.** It refuses to *start* a generation; a generation already
  running keeps contending for its remaining duration. That is not fixable
  without killing the generation.
* **The generator was Qwen3-VL-8B, not `llama-server` with Parcel's reasoner
  weights.** Right shape (separate CUDA context, driver-scheduled), wrong model.
  A different architecture, KV-cache size and decode rate would move the
  magnitude. Direction and mechanism hold; **1.54× does not transfer.**
* **The (b) "VLM resident but idle" cell of `pg1_contention.json` is mislabelled
  and is NOT a resident-idle measurement.** The hammer process begins generating
  immediately after signalling readiness, so (b) and (c) are two samples of the
  same contended condition (124.7 vs 125.9 ms p50) and are reported as such. The
  "resident-idle is free" finding rests on the 2026-08-21 bench alone
  (55.1 vs 56.0 ms p95).

---

## 6. The fail-closed hole the measurement found

Not on the card. Found by running the thing.

`onnxruntime-gpu` lists `CUDAExecutionProvider` in `get_available_providers()`
from a stub library. Resolution therefore legitimately selects `cuda_fp16`. The
provider then fails to load its real backend at session construction — here
`libcublasLt.so.13: cannot open shared object file` — and **ORT falls back to CPU
with a warning and no error**. Measured result on this machine:

```
[owlv2] provider resolved to cuda_fp16 but onnxruntime honoured ('CPUExecutionProvider',)
detect p50=726.1 p95=794.4 ms   (vs 524.4 ms for the int8 CPU path it displaced)
```

A session labelled fp16, logging fp16, running the fp16 graph on the CPU —
**slower than the path it replaced**. Registration is not execution.

Two fixes landed:

1. `assert_provider_honoured(resolution, session.get_providers(), model=...)` runs
   immediately after every session is built. A GPU resolution that ORT did not
   honour raises `ProviderNotHonouredError`, which the loaders convert into their
   existing "model unavailable" (`None`) degrade. Same fail-closed outcome as
   absent weights; never a silent 6× slowdown.
2. `prepare_cuda_runtime()` calls `onnxruntime.preload_dlls()` before a CUDA
   session. **This is required, not cosmetic** — when CUDA comes from pip wheels
   rather than a system install, ORT does not find them on its own. Verified both
   ways on this box:

```
without preload_dlls() -> get_providers() == ['CPUExecutionProvider']
with    preload_dlls() -> get_providers() == ['CUDAExecutionProvider', 'CPUExecutionProvider']
```

---

## 7. Seeds — 12, each RED for the right reason, each restored byte-identically

Protocol (house rule R9), identical for all twelve: snapshot bytes + sha256 →
**one** textual mutation → purge every `__pycache__` under `src/ scripts/ tests/
evals/` → **fresh-interpreter canary** (`python -B`,
`PYTHONDONTWRITEBYTECODE=1`) that *calls the live code* rather than reading its
text → run the named guards, require RED → restore in a `finally` → purge again →
assert sha256 identity → second canary proving the mutation is gone → re-run,
require GREEN.

Harness: `scratchpad/pg1/seed_harness.py` + `canary_helpers.py`; results in
`scratchpad/pg1/seed_results.json`. **Run twice: once mid-build, and again
against the final shipped tree** (the tree changed after the first run when ruff
fixes landed, so the first run's anchors no longer described what ships). The
table below is the final run.

| # | What is broken | File | RED | first failing test | GREEN after restore | sha identical |
|---|---|---|---|---|---|---|
| S1 | GPU path silently falls back: rejected providers no longer recorded | `perception_providers.py` | `3 failed in 0.10s` | `test_falling_back_records_every_rejected_provider_with_a_reason` | `3 passed` | yes |
| S2 | a degrade logs at INFO, invisible at normal verbosity | `perception_providers.py` | `1 failed in 0.10s` | `test_a_silent_degrade_is_impossible_because_the_log_level_escalates` | `1 passed` | yes |
| S3 | **fp16 selected on a CUDA-less machine** (EP availability check dropped) | `perception_providers.py` | `3 failed, 1 passed in 0.19s` | `test_a_cuda_less_machine_never_selects_fp16_even_with_the_fp16_file_present` | `4 passed` | yes |
| S4 | an explicitly pinned-but-unavailable provider degrades instead of refusing | `perception_providers.py` | `1 failed, 2 passed in 0.21s` | `test_pinning_cuda_on_a_cpu_box_refuses_instead_of_degrading` | `3 passed` | yes |
| S5 | **contention guard removed**: a generation starts while a person query is in flight | `perception_contention.py` | `4 failed in 0.24s` | `test_a_generation_is_refused_while_a_safety_lease_is_held` | `4 passed` | yes |
| S6 | an unbounded budget silently disables the guard while it still looks installed | `perception_contention.py` | `1 failed in 0.10s` | `test_an_infinite_budget_is_rejected_at_construction` | `1 passed` | yes |
| S7 | an undeclared generation duration is assumed short instead of unbounded | `perception_contention.py` | `1 failed in 0.10s` | `test_an_undeclared_generation_duration_is_refused` | `1 passed` | yes |
| S8 | seam guard always says "clean", so the fast path silently changes the tensor | `owlv2_onnx.py` | `7 failed, 6 passed in 1.41s` | `test_the_fast_preprocess_is_bit_identical_to_the_reference[shape2]` | `13 passed` | yes |
| S9 | **the lossy source downscale is on by default** | `owlv2_onnx.py` | `1 failed in 0.18s` | `test_the_preprocess_knob_defaults` | `1 passed` | yes |
| S10 | **int8 quality regression unpinned**: the measured cost is falsified | `perception_providers.py` | `2 failed in 0.11s` | `test_every_precision_row_carries_its_denominators` | `2 passed` | yes |
| S11 | the separable resize stops being the same arithmetic (weights transposed) | `owlv2_onnx.py` | `5 failed, 8 passed in 1.72s` | `test_the_separable_resize_is_bit_identical_to_the_reference_resize` | `13 passed` | yes |
| S12 | a person query no longer takes a safety lease | `owlv2_onnx.py` | `1 failed in 0.22s` | `test_a_person_query_holds_a_lease_for_the_duration_of_the_inference` | `1 passed` | yes |

Every row: `red=True`, `sha_identical=True`, `canary_clean_ok=True`,
`green_after_restore=True`.

Canaries worth quoting, because they show the mutation was genuinely live rather
than merely written to disk:

```
S3  mutated: cpu_box_selects=cuda_fp16 model=b_fp16.onnx
    clean  : cpu_box_selects=cpu_int8  model=a_int8.onnx
S5  mutated: admitted_while_lease_held=True
    clean  : admitted_while_lease_held=False
S8  mutated: seam_clean_480x640=True  fast_equals_reference=False
    clean  : seam_clean_480x640=False fast_equals_reference=True
S11 mutated: separable_equals_reference=False max_abs_delta=0.651581
    clean  : separable_equals_reference=True  max_abs_delta=0
S12 mutated: generation_admitted_during_person_query=[True]
    clean  : generation_admitted_during_person_query=[False]
```

### 7.1 Three seeds had to be redesigned, and the reason is evidence

* **S8** first disabled only the `z1` half of the seam check — and the guard
  **still held**, because the `z0` half independently catches every up-sampled
  shape. That redundancy is real and worth knowing. S8 was rewritten to attack
  the single point of failure (`_seam_is_clean` returning `True` unconditionally),
  and then reddened 7 cells.
* **S4** and **S6** initially reported `canary_clean_ok=False` — not because the
  mutation was inert (both guards reddened correctly) but because a *second,
  independent* check produced the same coarse canary outcome. S4's mutation still
  yields `selected=None` via a later branch; S6's `inf` is also caught by the
  `>= TTL` validator. Both canaries were sharpened to read the *reason* rather
  than the outcome, and both then distinguished cleanly. Recording this because
  "the canary agreed" would otherwise have looked like a clean row.

---

## 8. Deviations, and what is owner-gated

### Deviations from the card

1. **"Bit-identical downscale" was not implemented as specified, because it is
   not true.** Split into a bit-identical preprocessing restructure (default ON,
   §4.2) and an honestly-labelled lossy downscale (default OFF). §4.2 has the
   measurement. The card's phrase "that equivalence is the whole justification"
   is correct — and the equivalence does not hold, so the justification transfers
   to the restructure instead.
2. **36× is not achievable under onnxruntime.** Delivered 6.3× on the detector,
   13.7× on the SigLIP-2 image encoder, 6.6× on the combined per-query cost. §4.1.
3. **The int8 quality claim is corrected, not merely recorded.** §4.3.
4. **Contention re-measured cross-process** rather than reusing the bench's
   in-process number, because the deployment is cross-process. §5.2.
5. **Added beyond the card:** `assert_provider_honoured` + `prepare_cuda_runtime`,
   because the measurement pass hit the exact silent degrade the card's item 1
   exists to prevent. §6.
6. **The nine gate tests were not unskipped** (card item 5), and
   `tests/test_siglip_real_embeddings.py` was not edited at all.

### Owner-gated — none of this was done

1. **Shipping the GPU dependency.** `onnxruntime-gpu==1.28.0` (cp314 wheel
   exists, exact version match with the repo's CPU build) + `nvidia-cublas`,
   `nvidia-cudnn-cu13`, `nvidia-cufft`, `nvidia-curand`, `nvidia-cuda-runtime`,
   `nvidia-cuda-nvrtc` (~3 GB). `onnxruntime-gpu` occupies the same
   `onnxruntime` import namespace, so this **replaces** the CPU package rather
   than sitting beside it. The repo venv was **not** modified; everything was
   proved in `~/.cache/parcel-pg1/gpuvenv`.
2. **Shipping the fp16 weights.** `model_fp16.onnx` (307,407,627 B, sha256
   `694e2ae55306381ec0643edeb272ba6a4987820cb578ff38323210bc89fdb96d`),
   `vision_model_fp16.onnx` (186,039,516 B, sha256 `a1959f7b…68aabd95`),
   `text_model_fp16.onnx` (564,862,230 B, sha256 `711da56a…738d0eb0`) — same
   `onnx-community` export repos and same upstream Apache-2.0 checkpoints
   `scripts/fetch_owlv2.sh` / `fetch_siglip2.sh` already pin. `fetch_*.sh` were
   **not** modified; adding an `--fp16` mode is the natural follow-up.
3. **Wiring `try_admit_generation` into the generation entry point** (§5.4). Lives
   in `realtime/*`.
4. **Adopting torch** for the remaining ~3× the ORT CUDA forward leaves on the
   table (§4.1). Reverses the deliberate no-torch stance.
5. **Raising `ContentionPolicy.max_generation_ms_while_active` above 0.0.** The
   knob exists; loosening it needs evidence that a bounded generation is safe.

---

## 9. Does-not-prove

* **No perception-quality claim of any kind follows from this card.** Person
  recall is **0/69 on every precision and every provider**. `city_block.xml` has
  48 material references and zero texture images; the 2026-08-21 bench's control
  (127/156 on real photos, same checkpoint) is decisive that the scene is why.
  Moving the model to the GPU changes **latency and numeric precision**, not the
  world it looks at.
* **Every latency number is one machine, one GPU, one scene, 42 frames, batch 1,
  11 queries, 1280×720.** Nothing about a D455, a different frame size, a
  different query count, or a loaded machine follows.
* **Quality rows rank precisions against each other on THIS scene.** They are not
  field-recognition numbers.
* **The contention number used Qwen3-VL-8B, not `llama-server`.** §5.5.
* **The contention guard is not proven to protect anything today**, because the
  safety path does not consume the detector yet. §5.5.
* **Cell A reproducing the bench's incumbent row exactly** validates the harness
  and the matcher; it does not validate the *scene* or the labels.
* CPU-side timings were taken on a shared machine; the first measurement pass ran
  under a load average of 65 from an unrelated concurrent pytest run and was
  discarded and re-run at load ~3. GPU cells were taken with the GPU otherwise
  idle at 925–929 MiB.

---

## 10. Provenance

* Prior bench reused, not re-derived:
  `scrum/20260821/perception/bench_detectors.md`, `SYNTHESIS.md` §4, and the raw
  artifacts under
  `scratchpad/perception/bench-owl/` (`results/incumbent_all.json`,
  `results/gpu_owlv2_fp16.json`, `results/combined_contention.json`,
  `results/siglip_and_breakdown.json`, `frames/` — 42 frames + `manifest.json`,
  `code/evalkit.py` — the pre-registered matcher, reused unmodified).
* New artifacts, all under
  `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/pg1/`:
  `verify_biteq.py`, `diag_ulp.py`, `proto_fastpath.py` (the bit-identity
  investigation), `bench_pg1.py` + `results/pg1_owl.json`, `results/pg1_all.json`
  (latency/VRAM/quality), `bench_contention.py` + `vlm_hammer.py` +
  `results/pg1_contention.json` (cross-process contention),
  `seed_harness.py` + `canary_helpers.py` + `seed_results.json`,
  `gate_final.txt`, and `../gate_baseline.txt`.
* Scratch GPU environment at `~/.cache/parcel-pg1/` (venv + fp16 weights). The
  repo venv `.parcel/` was **not** modified.
* The owner's stack on :8765 was not contacted at all — no GET, no POST, no
  restart. No process was killed. GPU headroom stayed ≥9.9 GB throughout, above
  the 6 GB floor. Nothing was committed, staged, or stashed.


## Audit correction — Fable, 2026-08-21

§1's collection accounting ("+94 new tests") does not close against measured per-file collection, and part of the delta belongs to concurrent cards; the gate's own tier-coverage arithmetic (7634 = commit + nightly, no orphans) is the authoritative count. Noted by the auditor after verifier finding; no behavioral claim is affected.
