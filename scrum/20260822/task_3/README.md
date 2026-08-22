# Task 3 — P0-C: the GPU detector in the production venv

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(read its standing rules first — concurrent writers, Edit-only, git read-only).

## Why

The live detector runs OWLv2 int8 on `CPUExecutionProvider` at ~524 ms/query
(`perception_providers.py:12`) because `.parcel`'s `onnxruntime 1.28.0` has no
CUDA EP and `onnxruntime` is not even declared in `pyproject.toml`. PG-1
(`scrum/20260821/task_6/PG1_STATUS.md`) already landed the CUDA fp16 path
behind the same `Detector` protocol and measured 83 ms p50 — in a scratch venv
at `~/.cache/parcel-pg1/gpuvenv` (Python 3.14.4, `onnxruntime` 1.28 with
`['TensorrtExecutionProvider','CUDAExecutionProvider','CPUExecutionProvider']`).
This card brings that to the production venv so C-1's frames land inside the
300 ms TTL.

## Deliverables

1. **Declare it.** `pyproject.toml`: add an optional extra
   `perception = ["onnxruntime-gpu>=1.22,<2"]` (match the exact package/version
   that the gpuvenv proves works on this host: inspect
   `~/.cache/parcel-pg1/gpuvenv/lib/python3.14/site-packages/*.dist-info`).
   P0-E edits the `dev` extra concurrently — Edit-only, touch only your lines.
2. **Install it** into `.parcel`: `.parcel/bin/pip install -e '.[perception]'`
   (or the non-editable equivalent if `-e` regenerates egg-info noisily; either
   is acceptable). Then prove `.parcel/bin/python -c "import onnxruntime as o;
   print(o.get_available_providers())"` lists `CUDAExecutionProvider`, and — the
   PG-1 lesson — that `assert_provider_honoured` passes on a **real** CUDA
   session (the provider list can lie; the session cannot).
3. **fp16 artifacts.** Extend `scripts/fetch_owlv2.sh` and
   `scripts/fetch_siglip2.sh` with sha256-pinned fp16 variants (same source
   repos, same `.part` staging and idempotency), into the same cache dirs.
   Run them. Record sizes and shas in the status doc.
4. **Provider default `auto`** in `perception_providers.py`: `cuda_fp16` when
   honoured, else `cpu_int8`, logged once at construction (PG-1 already built
   most of this — reuse, do not fork). A machine without CUDA must behave
   exactly as today (flag-off/no-CUDA test).
5. **Measure on this GPU**, n ≥ 25 after 5 warm-up, cuda-synchronised, the full
   preprocess+forward+decode path, on the W-1 textured frames if a fixture
   exists (`tests/data/` or `scrum/20260821/task_11b/evidence`), else on any
   1280×720 RGB: detector p50/p95 for `cpu_int8` vs `cuda_fp16`, and the
   SigLIP-2 image encoder. Report the honoured provider of each run.
6. **Tests:** provider resolution order; the lie check (`assert_provider_honoured`
   refuses a CPU session labelled cuda — seed it RED by monkeypatching the
   provider list); fp16 artifact probe; existing OWLv2/SigLIP-2 tests still
   green under `PARCEL_OWLV2_ONNX=1 PARCEL_SIGLIP2_ONNX=1`.

## OWNS

`pyproject.toml` (the `perception` extra only), `scripts/fetch_owlv2.sh`,
`scripts/fetch_siglip2.sh`, `src/parcel_robot/perception_providers.py`,
`src/parcel_robot/detection_adapter/owlv2_onnx.py`,
`src/parcel_robot/instructnav/siglip2_onnx.py`, `src/parcel_robot/perception_contention.py`
(only if a constant must move), tests for those modules, this folder.
Network access for pip and the HF downloads is expected.

## MUST NOT TOUCH

`src/parcel_robot/camera_channel/ingress.py` and `runtime.py` (P0-A/P0-D),
`docs/**`, `backlog/**`, `README.md`, `scrum/20260821/**`, `configs/**`,
`evals/**`, `requirements-lock.txt` (report what a refresh would change; do not
refresh it), the 9 env-gated skipped gate tests' skip conditions.
Do not kill or use the running sim/panel (`/tmp/parcel_sim.sock`, :8765); do
not start `llama-server`. The GPU is shared — check `nvidia-smi` before a
measurement pass and report co-resident processes.

## Gates

* `.parcel/bin/python -m pytest -q tests/test_perception_providers*.py tests/test_owlv2*.py tests/test_siglip2*.py tests/test_cam_foundation.py -x` green (with and without the env flags).
* `.parcel/bin/ruff check` on OWNS, no new violations.
* The measured `cuda_fp16` p50 ≤ 120 ms on this host (PG-1 saw 83 ms); if it
  is not, report the number — do not tune the bound.

## Status doc

`P0C_STATUS.md`, per the board's register, with the measurement table and the
exact pip resolution (package, version, wheel tag).
