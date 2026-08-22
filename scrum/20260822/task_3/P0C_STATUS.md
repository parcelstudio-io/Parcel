# P0-C — the GPU detector in the production venv · status

**Card:** `scrum/20260822/task_3/README.md` · **Board:** `../TASK_BOARD.md` ·
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22

---

## 0. Headline

The three things PG-1 left owner-gated are taken: the dependency is **declared
and installed in `.parcel`**, the fp16 weights are **pinned and fetched by the
repo's own scripts**, and `auto` now resolves to a **CUDA session onnxruntime
actually honoured** for all three models (detector, SigLIP-2 text, SigLIP-2
vision). Measured on this host, full shipping path:

| | cpu_int8 (incumbent) | cuda_fp16 | speedup |
|---|---|---|---|
| **OWLv2 detector** p50 / p95 | 558.4 / 567.0 ms | **97.8 / 104.7 ms** | 5.71× / 5.41× |
| **SigLIP-2 image encoder** p50 / p95 | 47.6 / 50.2 ms | **4.17 / 4.60 ms** | 11.4× / 10.9× |
| detector + 1 crop embed | 606.0 ms (1.65 Hz) | **101.9 ms (9.8 Hz)** | 5.95× |

The card's bound was `cuda_fp16` p50 ≤ 120 ms. **97.8 ms — met.** It is *not*
PG-1's 83 ms, and the reason is not a regression: **the GPU was 98–100% busy
throughout, with nine co-resident processes** including the live MOVE-1 patrol
sim (§4.1). PG-1's 83 ms was taken on an otherwise-idle GPU. Nothing was killed.

Against `contracts.freshness.DEFAULT_DETECTION_TTL_NS` (300 ms), which is why
this card exists: the incumbent detector alone was **186% of the whole detection
TTL** — structurally unable to land a fresh frame. On `cuda_fp16` it is **33%**.

**Nothing in `perception_providers.py`, `owlv2_onnx.py` or `siglip2_onnx.py`
changed.** PG-1's `resolve_provider` / `assert_provider_honoured` /
`prepare_cuda_runtime` were reused exactly as written; deliverable 4 was already
satisfied by that code, so this card *verified it live* instead of re-writing it.
Source diff on those three files: **0 lines**.

---

## 1. What changed

`git diff --stat` over OWNS (working tree, before this document):

```
 pyproject.toml           | 35 +++++++++++++++++++++++++++++++++++
 scripts/fetch_owlv2.sh   | 37 +++++++++++++++++++++++++++++++++++--
 scripts/fetch_siglip2.sh | 42 ++++++++++++++++++++++++++++++++++++++++--
 3 files changed, 110 insertions(+), 4 deletions(-)
```

`pyproject.toml`'s 35 insertions are **two disjoint hunks**: `+29 @ line 21`
(mine — the `perception` extra) and `+6 @ line 71` (pre-existing, card W-1's
`scenes/assets` package-data globs, already in the tree when this card started
and not touched). `git diff -U0` confirms the split. The `dev` extra that P0-E
edits concurrently is **byte-unchanged by me**; my block is inserted after it
closes, immediately before `voice`.

New files:

| File | Lines | What |
|---|---|---|
| `tests/test_perception_providers_p0c.py` | 335 | 17 cells: the extra's shape, fp16 fetchability, the installed-artifact probe, the CUDA-less no-change guarantee, the lie check at the **loader** boundary |
| `scrum/20260822/task_3/P0C_STATUS.md` | this file | |

Unchanged and deliberately so: `src/parcel_robot/perception_providers.py`,
`detection_adapter/owlv2_onnx.py`, `instructnav/siglip2_onnx.py`,
`perception_contention.py`, `tests/test_perception_providers.py`,
`tests/test_owlv2_detector.py`, `tests/test_siglip2_provider.py`.

Nothing on MUST-NOT-TOUCH was edited: `camera_channel/ingress.py`, `runtime.py`,
`docs/`, `backlog/`, `README.md`, `scrum/20260821/`, `configs/`, `evals/`,
`requirements-lock.txt` (§6), the nine env-gated skip conditions (§3.3).

---

## 2. The exact pip resolution

**Package `onnxruntime-gpu`, version `1.29.0`, wheel
`onnxruntime_gpu-1.29.0-cp314-cp314-manylinux_2_28_x86_64.whl` (202.2 MB).**
Installed `WHEEL` tag: `cp314-cp314-manylinux_2_28_x86_64`.

Declared as:

```toml
perception = [
  "onnxruntime-gpu[cuda,cudnn]>=1.28,<2",
]
```

Installed with the card's exact command:

```
.parcel/bin/pip install -e '.[perception]'
```

### 2.1 The CPU package had to go first — it did

`onnxruntime` and `onnxruntime-gpu` install the **same `onnxruntime` import
package**. pip does not see them as conflicting (different distribution names)
and will happily leave a half of each on disk. So, explicitly and reported as the
card asks:

```
.parcel/bin/pip uninstall -y onnxruntime
  Found existing installation: onnxruntime 1.28.0
  Successfully uninstalled onnxruntime-1.28.0
```

Nothing in `.parcel` declared a dependency on it (`pip show onnxruntime` →
`Required-by:` empty) and `pip check` is clean afterwards. `sherpa-onnx` carries
its own bundled runtime and is unaffected. The GPU wheel still registers
`CPUExecutionProvider`, so every CPU consumer keeps working.

### 2.2 Full delta to the venv (`pip freeze` before → after)

```
- onnxruntime==1.28.0
+ onnxruntime-gpu==1.29.0
+ nvidia-cublas==13.6.1.10
+ nvidia-cuda-nvrtc==13.3.33
+ nvidia-cuda-runtime==13.3.29
+ nvidia-cudnn-cu13==9.24.0.43
+ nvidia-cufft==12.3.0.29
+ nvidia-curand==10.4.3.29
+ nvidia-nvjitlink==13.3.33
```

That is the **only** change; every other pinned version is untouched.
`.parcel` grew to **2.6 GB** (`site-packages/nvidia` 2.1 GB,
`site-packages/onnxruntime` 286 MB). `pip check`: *No broken requirements found.*
The editable rebuild left no egg-info dirt in the repo.

### 2.3 Two version notes a cold auditor will want

1. **The gpuvenv proves 1.28.0; pip resolves 1.29.0.**
   `~/.cache/parcel-pg1/gpuvenv/.../onnxruntime_gpu-1.28.0.dist-info` is the
   reference the card points at (tag `cp314-cp314-manylinux_2_28_x86_64`, same
   ABI). `pip install --dry-run` on this host today says
   `Would install ... onnxruntime-gpu-1.29.0`. I installed **what the declared
   extra actually resolves to**, not the historical pin, so the measurement
   below describes the venv a fresh `pip install -e '.[perception]'` produces
   rather than one nobody will get again. The nvidia-* wheels resolved to the
   *identical* versions the gpuvenv holds. 1.29.0 honoured CUDA on the first
   try (§3.1), so the 1.28.0 fallback was never needed.
   **Consequence to keep straight:** the `cpu_int8` row below is also measured
   under 1.29.0, so the cpu-vs-cuda comparison has exactly one variable (the
   provider). It is *not* directly the same runtime as PG-1's 1.28.0 numbers.
2. **`[cuda,cudnn]` is not decoration.** The bare wheel advertises
   `CUDAExecutionProvider` and then silently builds a CPU session. Reproduced on
   *this* venv, deliberately, before trusting anything (§3.1).

---

## 3. How verified — exact commands, exact results

### 3.1 The provider list lies; the session does not

`onnxruntime.get_available_providers()` after install:

```
$ .parcel/bin/python -c "import onnxruntime as o; print(o.__version__); print(o.get_available_providers())"
1.29.0
['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

That list is worth nothing on its own — PG-1's §6 finding, re-confirmed here on
1.29.0 by building the same real session twice, in two fresh processes:

```
NO   preload_dlls -> honoured: ['CPUExecutionProvider']
     [E:onnxruntime ...] Failed to load library .../libonnxruntime_providers_cuda.so
       with error: libcublasLt.so.13: cannot open shared object file
     [W:onnxruntime ...] Failed to create CUDAExecutionProvider.
WITH preload_dlls -> honoured: ['CUDAExecutionProvider', 'CPUExecutionProvider']
```

`prepare_cuda_runtime()` calls `preload_dlls()` before every CUDA session, which
is why the shipping path lands on the right side of that. The full live
resolution, with the env knob unset (i.e. `auto`), all three models:

```
INFO [owlv2]          requested=auto selected=cuda_fp16 precision=fp16 ep=CUDAExecutionProvider+CPUExecutionProvider model=model_fp16.onnx (first available in fallback order)
INFO [owlv2]          onnxruntime honoured providers=('CUDAExecutionProvider', 'CPUExecutionProvider')
INFO [siglip2-text]   requested=auto selected=cuda_fp16 precision=fp16 ep=CUDAExecutionProvider+CPUExecutionProvider model=text_model_fp16.onnx (first available in fallback order)
INFO [siglip2-text]   onnxruntime honoured providers=('CUDAExecutionProvider', 'CPUExecutionProvider')
INFO [siglip2-vision] requested=auto selected=cuda_fp16 precision=fp16 ep=CUDAExecutionProvider+CPUExecutionProvider model=vision_model_fp16.onnx (first available in fallback order)
INFO [siglip2-vision] onnxruntime honoured providers=('CUDAExecutionProvider', 'CPUExecutionProvider')
```

Logged **once at construction**, at INFO (no `degraded` flag, no rejections) —
which is the deliverable-4 contract, satisfied by PG-1's code unmodified.

### 3.2 A machine without CUDA behaves exactly as today

Not simulated on a synthetic filesystem — run against the **real cache dir that
now holds the fp16 files**, with only the execution-provider list forced to a
CUDA-less box:

```
owlv2  : requested=auto selected=cpu_int8 precision=int8 ep=CPUExecutionProvider model=model_int8.onnx  | rejected: cuda_fp16: CUDAExecutionProvider not registered in this onnxruntime build
sig-t  : requested=auto selected=cpu_int8 precision=int8 ep=CPUExecutionProvider model=text_model_int8.onnx   | rejected: cuda_fp16: ...
sig-v  : requested=auto selected=cpu_int8 precision=int8 ep=CPUExecutionProvider model=vision_model_int8.onnx | rejected: cuda_fp16: ...
```

Same artifact, same EP, same numbers as before this card. Pinned by
`test_installing_fp16_does_not_change_what_a_cuda_less_box_runs_{owlv2,siglip2}`
and seeded RED as **S5**.

### 3.3 Gates

```
$ .parcel/bin/python -m pytest -q tests/test_perception_providers*.py tests/test_owlv2*.py \
      tests/test_siglip2*.py tests/test_cam_foundation.py -x
111 passed, 2 skipped in 3.80s

$ PARCEL_OWLV2_ONNX=1 PARCEL_SIGLIP2_ONNX=1 .parcel/bin/python -m pytest -q \
      tests/test_perception_providers*.py tests/test_owlv2*.py tests/test_siglip2*.py \
      tests/test_cam_foundation.py -x
112 passed, 1 skipped in 5.93s
```

With the flags on, `test_real_owlv2_loads_and_reports_512_or_768_dim` **runs for
the first time on this venv and passes on the CUDA fp16 session** — the flag-on
path is no longer a promise. The remaining skip is
`test_owlv2_detector.py:578`, whose reason string is *"only asserts the
disabled-path skip contract"*: a cell that exists to be skipped. **No skip
condition was edited.** Flags-off skip counts are unchanged (owlv2 ×2,
siglip_real ×6, p3_storefront ×1 = the same nine).

Other tests that touch onnxruntime, run because this card replaced the venv's ORT
for the whole tree:

```
$ .parcel/bin/python -m pytest -q tests/test_endpointing.py tests/test_p4_place_graph.py \
      tests/test_perception_contention.py tests/test_runtime_activation.py \
      tests/test_siglip_real_embeddings.py tests/test_c1_camera_stream.py -rs
181 passed, 6 skipped, 2 warnings in 4.57s
```

And the whole commit tier, because replacing the venv's onnxruntime is a
tree-wide act and "my OWNS is green" would not have covered it:

```
$ .parcel/bin/python -m pytest -q -m "not slow" -p no:cacheprovider
3 failed, 7982 passed, 9 skipped, 80 deselected, 6 warnings in 329.28s (0:05:29)
```

**Skips 9 → 9.** The three failures are **other cards' live edits, not this
card's**, and neither the failing modules nor their causes touch onnxruntime:

| Failure | Cause | Whose |
|---|---|---|
| `test_c3_cutover.py::test_E2_the_abstention_gate_is_not_modified_by_this_card` | asserts `src/parcel_robot/perception_abstention.py` has an empty diff; it now carries a `label_strength_margin` estimator | **P0-D** (`ranking_margin ≡ 0` is literally its deliverable) |
| `test_realtime_idle_hangup.py::…_is_a_refusal_not_a_default[0]` and `[0.0]` | `RealtimeConfigError` no longer raised for a `0` idle window | **P0-B** ("idle stays live") |

Both are inside those cards' OWNS and both are the board's own
loosen-the-fail-closed directive taking effect. `grep -i onnxruntime` over the
run's output finds one line, a `RuntimeWarning` from a test that *injects* a
failing ONNX on purpose (`endpointing.py:269`). No perception, provider, camera,
detector, or SigLIP cell failed.


ruff:

```
$ .parcel/bin/ruff check <the eight OWNS python files>
All checks passed!

$ .parcel/bin/ruff check          # whole tree
Found 12 errors.
```

Those 12 collapse to exactly the **7 baseline fingerprints** in
`scripts/ci_ruff_baseline.json` (`B009` fires 6× in one file); the fingerprint
set is byte-identical to the baseline, so **new = 0**. Every violation is in
`camera_channel/**` and `detection_adapter/{noise,sim_bridge}.py` — none of them
mine, all of them pre-existing debt.

### 3.4 Seeded RED — 5 seeds, every new guard

Protocol per house rule R9: snapshot bytes + sha256 → **one** textual mutation →
purge every `__pycache__` under `src/ scripts/ tests/ evals/` → run the named
guards under `python -B` with `PYTHONDONTWRITEBYTECODE=1`, require RED → restore
in a `finally` → purge → assert sha256 identity → re-run, require GREEN.
Harness + results: `~/.cache/parcel-p0-c/seed_harness.py`, `seed_results.json`.

**Concurrency addition, because this wave shares one tree:** before restoring,
the harness re-reads the file and refuses to write if the on-disk bytes are not
the exact bytes it wrote. A peer's edit inside the mutation window would be
*reported*, never silently reverted. No seed tripped it.

| # | What is broken | File | RED | GREEN after restore | sha identical |
|---|---|---|---|---|---|
| S1 | the `perception` extra drops `[cuda,cudnn]` — installs with no CUDA libs, every session becomes CPU | `pyproject.toml` | `1 failed in 0.23s` | yes | yes |
| S2 | `fetch_owlv2.sh` stops pinning the fp16 artifact — a CUDA box resolves to a file no script can fetch | `scripts/fetch_owlv2.sh` | `1 failed, 1 passed` | yes | yes |
| S3 | `--fp16` **replaces** the int8 rows instead of appending — the cpu_int8 fallback loses its artifact | `scripts/fetch_siglip2.sh` | `1 failed, 1 passed` | yes | yes |
| S4 | the lie check returns instead of raising — loaders hand back a "cuda_fp16" detector ORT ran on the CPU | `perception_providers.py` | `3 failed in 0.21s` | yes | yes |
| S5 | a CUDA-less machine starts selecting fp16 now that it is installed | `perception_providers.py` | `2 failed in 0.21s` | yes | yes |

`ALL SEEDS OK: True`. S1 mutating `pyproject.toml` is the one that touches a file
another card owns a different region of; the window was ~0.3 s and the
concurrency guard confirmed byte-identical restore.

---

## 4. Measured

### 4.1 Conditions — read this before the table

**Host:** RTX 5000 Ada Generation, 32,760 MiB, driver **595.84** / CUDA 13.2,
Python **3.14.4**, `onnxruntime-gpu` **1.29.0**.

**The GPU was NOT idle.** `nvidia-smi` immediately before each pass, verbatim
process list (nothing was killed, per the card):

| PID | Type | Process | VRAM |
|---|---|---|---|
| 11571 | G | `/usr/bin/gnome-shell` | 370–396 MiB |
| 15346 | C+G | `snapd-desktop-integration` | 18 MiB |
| 20590 | G | `/usr/share/cursor/cursor` | 199–242 MiB |
| 20596 | G | `/usr/bin/Xwayland` | 7 MiB |
| 26900 | C+G | `chrome --type=gpu-process` | 185–237 MiB |
| **910287** | **G** | **`Parcel/.parcel/bin/python`** — the live MOVE-1 patrol sim the board names | **354 MiB** |
| **973200** | **G** | **`Parcel/.parcel/bin/python`** — second live Parcel process | **347 MiB** |
| 938372 | C+G | `/usr/bin/nautilus` | 26 MiB |
| 975331 | C+G | `gnome-control-center` | 26 MiB |

Baseline occupancy **1,774 / 32,760 MiB** and **`utilization.gpu` 98–100%** in
every `smi_before`/`smi_resident` sample except one (the SigLIP CUDA cell caught
a 34% instant at start, 100% resident). **Every `cuda_fp16` number below is a
contended number.** That is why 97.8 ms and not PG-1's 83.0 ms, which was taken
at 925–929 MiB and an idle GPU. It is arguably the more useful number — the
deployment shape *is* a shared GPU — but it is not a like-for-like re-measurement
of PG-1, and it must not be quoted as one.

**Method.** One cell **per process** (no two ORT sessions in one interpreter, no
CUDA context reuse). Provider pinned explicitly via `PARCEL_PERCEPTION_PROVIDER`
so `auto` is never the thing under test. Frames: the **42 rendered
`city_block.xml` frames at 1280×720** from PG-1's bench
(`.../bench-owl/frames/*_rgb.npy`), copied to
`~/.cache/parcel-p0-c/frames/`. 11 query labels (`evalkit.WORLD_LABELS`),
batch 1. **n = 30 timed after 5 warm-up**, cycling through the 42 frames rather
than repeating one, so a single-frame artefact cannot carry the median. Timing
wraps the **whole shipping call** — `OwlV2Detector.detect()` is preprocess +
tokenize + forward + numpy box decode + NMS; `embed_image()` is resize +
normalise + forward + L2. SigLIP crops are 300×200 slices of the same frames.

**On "cuda-synchronised":** ORT's `run()` copies its outputs to *host* memory
before returning, so the call is device-synchronised by construction — no GPU
work is outstanding when the timer stops. There is no torch in this stack, so
`cudaDeviceSynchronize` is not reachable from Python; the host copy is the sync.
This is the same basis PG-1 timed on.

*No W-1 textured-frame fixture exists* under `tests/data/` (which holds only
`c2_online_map_frames.json` and `pg3_abstention_bench.json`) or
`scrum/20260821/task_11b/evidence` (session logs, no frames), so the card's
fallback applies. The PG-1 frames were chosen over synthetic 1280×720 noise
because they make these rows comparable to PG-1's. **Texture content cannot move
a latency number** — the tensor shape is fixed by the preprocessor — so nothing
is lost by their being untextured.

### 4.2 The table

| Cell | artifact | honoured providers | n | p50 | p95 | mean | min | max | VRAM Δ |
|---|---|---|---|---|---|---|---|---|---|
| **A** detector `cpu_int8` | `model_int8.onnx` | `('CPUExecutionProvider',)` | 30 | **558.39** | 566.96 | 557.44 | 545.53 | 574.82 | 0 |
| **B** detector `cuda_fp16` | `model_fp16.onnx` | `('CUDAExecutionProvider', 'CPUExecutionProvider')` | 30 | **97.75** | 104.72 | 98.71 | 96.47 | 108.46 | +2,430 MiB |
| **C** SigLIP-2 image `cpu_int8` | `vision_model_int8.onnx` | `('CPUExecutionProvider',)` | 30 | **47.59** | 50.21 | 47.87 | 46.83 | 52.32 | 0 |
| **D** SigLIP-2 image `cuda_fp16` | `vision_model_fp16.onnx` | `('CUDAExecutionProvider', 'CPUExecutionProvider')` | 30 | **4.17** | 4.60 | 4.41 | 4.13 | 8.48 | +1,252 MiB |
| **B′** detector `cuda_fp16`, independent replication | `model_fp16.onnx` | `('CUDAExecutionProvider', 'CPUExecutionProvider')` | 30 | 100.84 | 110.99 | 102.45 | 96.63 | 130.27 | +2,398 MiB |

All times in ms. Every row's honoured provider is the one it resolved to —
no cell ran on a provider it did not claim.

**B′** is a fresh process, a fresh CUDA context, run ~20 minutes later at a
different baseline occupancy (1,899 vs 1,774 MiB, both at 99% utilisation), and
it is reported because a single pass on a contended GPU is a weak claim. It
agrees within 3.2% on p50 and 6.0% on p95, and **both passes are under the
card's 120 ms bound**. The p50 quoted in the headline is the first pass; B′ is
the honest spread, not a discarded outlier.

Derived:

* **Detector A→B: 5.71× p50, 5.41× p95.** PG-1 measured 6.32× on an idle GPU.
* **SigLIP-2 image C→D: 11.41× p50, 10.92× p95.** PG-1 measured 13.7×.
* **Combined per query** (detector + one crop embedding): **606.0 → 101.9 ms,
  5.95×**; 1.65 Hz → 9.81 Hz.
* Cell A at 558 ms reproduces the incumbent's known ~524–565 ms band (PG-1's
  cell A 524.4 ms idle, cell B 565.4 ms with the fast preprocess off). The CPU
  was also shared; A is a contended CPU number for the same reason B is a
  contended GPU one.
* **Card bound `cuda_fp16` p50 ≤ 120 ms: PASS at 97.75 ms** (replication
  100.84 ms). Not tuned. The first pass is the one quoted; the second was run to
  test stability, not to improve the number, and both are reported.

Raw JSON per cell (including every `nvidia-smi` sample):
`~/.cache/parcel-p0-c/{det_cuda,det_cuda_rep,detector_cpu_int8,siglip_cuda_fp16,siglip_cpu_int8}.json`.
Harness: `~/.cache/parcel-p0-c/bench_p0c.py`.

---

## 5. Artifacts — sizes and sha256

Fetched by the repo's own scripts, into the same cache dirs the loaders probe.
Every sha256 was **independently cross-checked against the HuggingFace tree API
LFS oid** before being written into the scripts (not copied on faith from
PG-1's doc, which truncates two of the three):

| File | Cache dir | Bytes | sha256 |
|---|---|---|---|
| `model_fp16.onnx` | `~/.cache/parcel/owlv2-b16` | 307,407,627 | `694e2ae55306381ec0643edeb272ba6a4987820cb578ff38323210bc89fdb96d` |
| `text_model_fp16.onnx` | `~/.cache/parcel/siglip2-b16` | 564,862,230 | `711da56ada0a4aa11c7dd3320df741081a3cae4f0ae1b5e5c6d5b294738d0eb0` |
| `vision_model_fp16.onnx` | `~/.cache/parcel/siglip2-b16` | 186,039,516 | `a1959f7bd3993a607e48839f6d01e25b876fe76afda301b028b78eef68aabd95` |

Source repos and upstream checkpoints are the ones the scripts already pinned for
int8 — `onnx-community/owlv2-base-patch16-ensemble-ONNX` and
`onnx-community/siglip2-base-patch16-224-ONNX`, both Apache-2.0. No new licence
surface. +1.06 GB on disk; the int8 artifacts are **kept**, not replaced.

Note recorded because it is an easy mistake: the SigLIP-2 repo *also* has an
`onnx/model_fp16.onnx` (750,910,198 B) — the **fused** encoder. It is a different
artifact from the separate `text_/vision_` encoders this path uses and is
deliberately not fetched; the script header says so.

### 5.1 The scripts

`--fp16` is **additive** and idempotent, matching the existing `.part`-staging
and sha-gate pattern exactly:

```
$ scripts/fetch_owlv2.sh --fp16       # first run
  model_fp16.onnx            downloaded 694e2ae5...
$ scripts/fetch_owlv2.sh --fp16       # second run
  fetch_owlv2: model_fp16.onnx already present + verified
$ scripts/fetch_siglip2.sh --fp16     # second run: 10/10 rows "present + verified"
```

No `.part` files survive either run. `bash -n` clean on both.

---

## 6. `requirements-lock.txt` — what a refresh would change (NOT refreshed)

The file is on MUST-NOT-TOUCH and was not touched. For the record, it currently
**does not list `onnxruntime` at all** — the CPU package was in `.parcel` but
never in the lock, so the lock has been silently incomplete with respect to the
perception stack since before this card. A refresh from the current venv would
add **eight** lines and remove none:

```
+ nvidia-cublas==13.6.1.10
+ nvidia-cuda-nvrtc==13.3.33
+ nvidia-cuda-runtime==13.3.29
+ nvidia-cudnn-cu13==9.24.0.43
+ nvidia-cufft==12.3.0.29
+ nvidia-curand==10.4.3.29
+ nvidia-nvjitlink==13.3.33
+ onnxruntime-gpu==1.29.0
```

Plus, if it were regenerated by tooling rather than hand-edited, the transitive
`flatbuffers` / `protobuf` / `numpy` pins the GPU wheel requires — already
present in the venv, absent from the lock. **A lock refresh is a real decision,
not a formality: it would make ~2.1 GB of CUDA wheels mandatory for every
`pip install -r requirements-lock.txt`,** including CPU-only and CI machines that
have no GPU to use them on. That is why `perception` is an *extra*. Recommend the
lock stay GPU-free and the extra stay opt-in; flagged to Fable rather than
decided here.

---

## 7. What this does NOT prove

* **No perception-quality claim of any kind.** This card measured latency and
  changed which numeric precision runs. It did not run the quality matcher.
  PG-1's finding stands unamended: person recall is **0/69 under every
  precision** on `city_block.xml`, and int8-vs-fp16 trades recall for precision
  (.177 vs .278) rather than being strictly worse. Nothing here is a
  field-recognition number, and nothing transfers to a D455.
* **The `cuda_fp16` numbers are contended numbers** (§4.1), taken with nine
  co-resident GPU processes and the GPU pegged at 98–100%. They are neither an
  idle-GPU best case nor a worst case — a `llama-server` generation would be
  worse (PG-1 measured 1.54× on p95 cross-process). No `llama-server` was
  started, per the card.
* **The `cpu_int8` rows are contended too** — same shared box, plus the
  measurement pass ran while other cards' pytest runs were live. A is 6.5% above
  PG-1's idle 524.4 ms.
* **One machine, one GPU, one scene, 42 frames, batch 1, 11 queries, 1280×720,
  n=30.** Nothing about a different frame size, query count, or camera follows.
* **The venv now differs from what the repo's lock file describes** (§6). Anyone
  reproducing from `requirements-lock.txt` gets *no* onnxruntime at all, which is
  a pre-existing hole this card makes more consequential, not one it created.
* **1.29.0 is not the version PG-1 proved.** It honoured CUDA and hit the bound
  on the first attempt here, but no other card's numbers were re-derived under
  it, and PG-1's 1.28.0 rows should not be mixed with these into one series.
* **The detector still has no live consumer.** `runtime.attach_camera_ingress()`
  had zero non-test call sites as of PG-1 and this card did not change that.
  Making the detector 5.7× faster does not put a frame in front of it.
* The installed-artifact probe checks size and the ONNX protobuf leading byte,
  **not** the sha, on every run — a full 1 GB re-hash in the commit tier is not
  worth it. The sha gate lives where the file is written (the fetch scripts),
  which is the only place it can prevent anything.

---

## 8. Deviations from the card

1. **The extra is `onnxruntime-gpu[cuda,cudnn]>=1.28,<2`, not
   `onnxruntime-gpu>=1.22,<2`.** Two changes, both forced by measurement:
   * `[cuda,cudnn]` — without the extras pip installs no CUDA runtime and the
     session silently degrades to CPU. Demonstrated live in §3.1 on this exact
     venv. Declaring the bare package would ship a `perception` extra that does
     not deliver perception on the GPU.
   * `>=1.28` not `>=1.22` — 1.28.0 is what the gpuvenv proves on this host
     (Python 3.14.4, cp314 wheel); 1.22 admits builds with no cp314 wheel at all
     and nothing measured here. The card's own instruction to "match the exact
     package/version that the gpuvenv proves" points the same way.
2. **Installed 1.29.0, not the gpuvenv's 1.28.0** (§2.3). The card's install
   command was run verbatim and this is what it resolves to today; installing an
   older pin would have described a venv nobody will reproduce. Reported rather
   than narrowed.
3. **`perception_providers.py`, `owlv2_onnx.py`, `siglip2_onnx.py` were not
   edited.** Deliverable 4 ("provider default `auto`, logged once at
   construction, no-CUDA unchanged") was already fully implemented by PG-1. The
   card says *reuse, do not fork*, so this card verified the behaviour live
   (§3.1, §3.2) and added tests, rather than producing a diff for its own sake.
4. **Latency was measured on PG-1's 42 untextured frames**, because no W-1
   textured fixture exists in either location the card names (§4.1). The card's
   own fallback ("else on any 1280×720 RGB") is satisfied and then some.
5. **No new frozen digest was added to the test tree.** The board forbids new
   hash-locks; the fp16 test pins the *linkage* (loader candidate name ↔ hub path
   ↔ *a* 64-hex sha in the script) and leaves the sha value owned solely by the
   fetch script, where it already lives for int8.
6. **A wider pytest sweep than the card's gate was run** — every test file that
   references onnxruntime, plus the commit-tier suite — because swapping the
   venv's ORT affects the whole tree, not just OWNS. Results in §3.3.

---

## 9. Handoffs

* **To Fable (verification):** the one-command re-check is
  `.parcel/bin/python -m pytest -q tests/test_perception_providers_p0c.py`
  (17 cells, 0.2 s, no GPU needed — every CUDA row is injected). To re-derive a
  latency number: `.parcel/bin/python ~/.cache/parcel-p0-c/bench_p0c.py detector cuda_fp16`.
  Expect a *different* p50 from 97.75 ms if the GPU's load differs; check
  `smi_before` in the JSON before treating a delta as a regression.
* **To P0-E (gate tiers):** `tests/test_perception_providers_p0c.py` adds **17
  commit-tier cells**, all sub-millisecond, none marked `slow`, none env-gated.
  Two are `skipif`-guarded on the fp16 artifacts being installed, so they will
  *skip* on a machine that has not run `fetch_*.sh --fp16` — that is 3 additional
  potential skips beyond the standing nine, and they are **not** in the nine's
  category (no skip condition of an existing cell changed). The whole-tree ruff
  fingerprint set is unchanged from `ci_ruff_baseline.json`.
* **To whoever wires the camera cutover (C-1/C-3):** the detector now fits the
  300 ms TTL with ~200 ms of headroom on a *loaded* GPU. It did not before.
  `PerceptionContentionGuard`'s consumer half is still unwired (PG-1 §5.4) — a
  `llama-server` generation will still contend, and that budget is not in these
  numbers.
* **To the owner:** `.parcel` is now **2.6 GB** and pulls 2.1 GB of NVIDIA CUDA
  wheels. Re-creating the venv from scratch without `.[perception]` gives you a
  box with **no onnxruntime at all** — the base dependency list still does not
  declare it. Worth fixing, but it is a `pyproject.toml` `dependencies` change
  outside this card's OWNS.
* **Open, not decided here:** whether `requirements-lock.txt` should carry the
  GPU stack (§6). Recommendation: no.

---

## 10. Provenance

* Reused unmodified: PG-1's `resolve_provider` / `assert_provider_honoured` /
  `prepare_cuda_runtime` (`src/parcel_robot/perception_providers.py`), its 42
  bench frames and `evalkit.WORLD_LABELS`, and its `~/.cache/parcel-pg1/gpuvenv`
  as the wheel reference.
* Everything new is under **`~/.cache/parcel-p0-c/`** (not `/tmp`, per the
  board): `bench_p0c.py`, `frames/` (42 × `*_rgb.npy` + `manifest.json`),
  `det_cuda.json`, `det_cuda_rep.json`, `detector_cpu_int8.json`, `siglip_cuda_fp16.json`,
  `siglip_cpu_int8.json`, `seed_harness.py`, `seed_results.json`,
  `freeze_before.txt`, `freeze_after.txt`, `pip_install_report.json`,
  `full_suite.txt`, `hfapi.json`, `owl.json`.
* Git: **nothing** added, committed, stashed, checked out, reset, or restored.
* Processes: nothing killed. The MOVE-1 sim (pid 910287), the panel on :8765 and
  `/tmp/parcel_sim.sock` were never contacted. No `llama-server` was started.
  GPU headroom stayed above 28 GB throughout.
