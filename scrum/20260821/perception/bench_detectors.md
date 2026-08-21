**Report:** https://claude.ai/code/artifact/5bf2990e-8ea4-4b96-8d69-61d2d51f413d

## Headline

The blocker on perception generalization is **not the detector — it's that `city_block.xml` has no visual semantics to generalize from.** Pedestrians are flat-colored capsules with sphere heads. Nothing recognizes them as people.

Proven with a control (same models, same prompts, same matching code, only the pixels differ):

| Person recall | Parcel renders (n=69) | Real photos (n=156) |
|---|---|---|
| OWLv2-base fp16 | **0/69 = 0.000** | 127/156 = 0.814 |
| Grounding-DINO tiny | 5/69 = 0.072 | 145/156 = 0.929 |
| YOLO-World-S | **0/69 = 0.000** | 141/156 = 0.904 |
| Qwen3-VL-8B (yes/no) | 0/6 frames | 6/6 frames |

Prompt engineering doesn't fix it (0/69 unchanged). The internal control is decisive: the VLM describes frames as *"stylized 3D scene with colorful geometric shapes"* and names **the Go2 robot** — the only textured mesh in the scene.

## Latency/VRAM (batch 1, 1280×720, p50/p95 ms)

- **Incumbent** (OWLv2 int8 ONNX **CPU**): **560.0 / 579.3 = 1.8 Hz.** Not loop-capable, and int8 costs quality too (.144 vs .164 recall vs fp16).
- OWLv2 torch fp16 GPU: 50.9 / 77.1, 832 MiB — 11× faster
- OWLv2 fp16 @ 640×360 source: **15.7 / 18.8** — see below
- Grounding-DINO tiny: 106.8 / 108.5, 2,776 MiB (fp16 weights crash deformable attention; needs fp32+autocast)
- YOLO-World-S: 7.1 / 7.2 — fastest, but weakest on real photos and **AGPL-3.0 via ultralytics**
- SigLIP-2: 49.3 ms CPU int8 → **4.07 ms** GPU fp16 (12×)

**Highest-leverage finding: 73% of OWLv2's latency is CPU-side preprocessing** (31.75 ms of 43.22 ms; GPU forward is only 12.91 ms). It scales with *source* resolution though the model always sees 960×960. Halving the input edge = free 2.8×, bit-identical tensor.

**Contention, not capacity, is the constraint:** OWLv2+SigLIP-2 = 1,372 MiB; full stack with an 8B VLM = 19,501 MiB of 32,760. But with the VLM *generating*, detector p95 goes 56 → 150 ms and the 640×360 trick stops helping. The person-yield path must not queue behind a scene description.

## Recommendation

Fix the assets before benchmarking detectors — **keep the 9 gate tests skipped**; unskipping them against this scene would encode 0/69 person recall as expected. Then move the incumbent to GPU fp16 + downscale (560 → 15.7 ms, 36×, same `Detector` protocol). Keep OWLv2. Split F3: geometric answerability ("is the way clear") works on sim pixels today; semantic answerability ("what is that") cannot be validated here.

Caveats: 42 frames / one scene / one revision; no per-model threshold tuning; COCO control is capability-only and says nothing about D455 field performance; latency measured with your live stack idle (927 MiB baseline). Full list in the report.

Pre-registration written before first inference; all artifacts under `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/perception/bench-owl/` (`PREREGISTRATION.md`, `code/`, `frames/`, `results/`). Nothing in the repo was modified; scene and incumbent classes read in place. Repo venv untouched — used a scratch venv (note: the box has no C compiler and no Python headers, so I bootstrapped uv + a ziglang `cc` shim for triton).