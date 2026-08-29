# Edge deployment reality (Jetson AGX Orin 64 GB) and Unitree Go2 control surfaces

Research note for Parcel, 2026-08-28. Every source below was fetched and read in this session
(WebFetch or Python `urllib` against the raw file); nothing is cited from memory. Where a
number is an inference of mine rather than a measurement, it is labelled **[my inference]**.
Where a page could not be fetched, that is stated and the claim is either dropped or marked
as resting on a secondary source.

Scope: (A) measured inference numbers on Jetson Orin for small LLMs, ASR, TTS, small VLMs and
full-duplex speech models; (B) the Go2 EDU control surfaces: SDK2 SportClient (high level),
MotionSwitcher, LowCmd/LowState (joint level), unitree_mujoco / unitree_rl_lab / unitree_rl_mjlab
for training and deploying custom low-level policies, and what runs on the dog's own Jetson vs
an external Orin.

---

## 0. Hardware reference (needed to read every number below)

Source: NVIDIA Jetson Orin product page, https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ (fetched twice; the two reads disagreed on some cells, so only the cells that agreed or were quoted verbatim are listed).

| Module | AI perf | GPU | CPU | Memory | Bandwidth | Power |
|---|---|---|---|---|---|---|
| Jetson AGX Orin 64GB | "275 TOPS" | 2048-core Ampere, 64 Tensor Cores | 12-core Cortex-A78AE | 64 GB 256-bit LPDDR5 | **204.8 GB/s** | 15–60 W |
| Jetson Orin NX 16GB | "100 TOPS" (one read showed 157 TOPS, i.e. the JetPack 6.2 "Super" figure) | 1024-core / 32 TC (first read) | 6–8 core A78AE (reads disagreed) | 16 GB 128-bit LPDDR5 | **102.4 GB/s** | 10–25 W (one read 10–40 W) |
| Jetson Orin Nano 8GB | 67 TOPS (Super) | 1024-core / 32 TC | 6-core A78AE | 8 GB | 102 GB/s (page) | 7–15 W (one read 7–25 W) |

Why this matters: single-stream LLM decode on Jetson is memory-bandwidth bound (see Eric Liu's
Orin Nano measurement below: "Every single model is memory-bound in this single-stream inference
scenario"). The external AGX Orin 64 GB has **2x the bandwidth and 4x the memory** of the Orin NX
16 GB that ships in the Go2 EDU Plus.

---

## A. Inference numbers on Jetson Orin

### A1. Small/medium LLMs (0.5B–8B)

**A1.1 llama.cpp on AGX Orin 64GB (JetPack 6.1, CUDA 12.6, `-ngl 999 -fa 1`, test date 2026-05-29)**
Source: multimodalflow.net, "LLM Inference Benchmarks on Jetson AGX Orin 64GB (2026)", https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/ (independent blog; methodology stated).

| Model | Quant | GGUF | Decode | TTFT | Memory |
|---|---|---|---|---|---|
| Llama 3.1 8B | Q4_K_M | 4.9 GiB | 28 t/s | 1.2 s | 5.8 GB |
| Qwen2.5 7B | Q4_K_M | 4.7 GiB | 31 t/s | 1.0 s | 5.2 GB |
| Phi-3 Mini 3.8B | Q4_K_M | 2.4 GiB | 47 t/s | 0.7 s | 2.8 GB |

**A1.2 llama.cpp / Ollama across Orin SKUs (JetPack 6.2, `jetson_clocks` on, ctx 2048)**
Source: ProventusNova, https://proventusnova.com/blog/llm-inference-jetson-orin-llamacpp-ollama (independent blog).

| Device | Model | Prompt t/s | Gen t/s |
|---|---|---|---|
| AGX Orin 64GB | Llama 3.1 8B Q4_K_M | 48 | **52** |
| Orin NX 16GB | Llama 3.1 8B Q4_K_M | 15 | 18 |
| Orin NX 16GB | Qwen2.5 7B Q4_K_M | 18 | 20 |
| Orin NX 8GB | Llama 3.1 8B Q4_K_M | 10 | 11 |
| Orin Nano 8GB | Phi-3 mini 3.8B Q4_K_M | 22 | 28 |

Also: "Q4_K_M Llama 3.1 8B model file is ~4.7GB", ~6 GB total with 4096 context; practical max
model size on AGX Orin 64GB "~40GB". Note the 28 t/s (A1.1) vs 52 t/s (A1.2) spread for the same
model/quant on the same board: JetPack version, clocks and llama.cpp build matter by ~2x. Assume
**~30–50 t/s for an 8B Q4 model** on AGX Orin until measured on our unit.

**A1.3 TensorRT-LLM v0.12.0-jetson (official NVIDIA README, Jetson Orin 64GB, JetPack 6.1)**
Source: https://github.com/NVIDIA/TensorRT-LLM/blob/v0.12.0-jetson/README4Jetson.md (primary).
Meta-Llama-3-8B-Instruct, batch 1, CUDA graphs on:

| Config | ISL/OSL | Context (ms) | Decode (tok/s) |
|---|---|---|---|
| INT4 default | 512/512 | 260 | 35.2 |
| INT4-GPTQ | 512/512 | 292 | 33.7 |

Peak decode "approximately 35.9 tokens/second" at smaller inputs. The forum announcement
(https://forums.developer.nvidia.com/t/tensorrt-llm-for-jetson/313228) confirms the branch name and
JetPack 6.1; the archived Jetson AI Lab page (https://www.jetson-ai-lab.com/archive/tensorrt_llm.html)
says "Jetson AGX Orin" with "Support for other Orin devices is currently undergoing testing",
JetPack 6.1 (L4T r36.4), INT4 example on Llama-2-7b-chat GPTQ.

**A1.4 vLLM on AGX Orin (NVIDIA staff numbers)**
- "we can get 231 tok/s on AGX Orin 64GB with concurrency=8" using the vLLM container (r36.4) —
  NVIDIA staff on https://forums.developer.nvidia.com/t/llm-library-recomendations-for-maximum-token-speeds/358521.
  Model not named in the thread. Same thread, user reports: TensorRT-LLM "capped at 20 tokens/second",
  brief 22 t/s in MAXN then throttled to 5 t/s (thermal), Ollama 7B ~15 t/s. Treat as anecdotal.
- Jetson AI Lab GenAI benchmarking tutorial, https://www.jetson-ai-lab.com/tutorials/genai-benchmarking/:
  sample output for `RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w4a16`, ISL/OSL 2048/128, 50
  prompts, concurrency 1: **44.19 tok/s output, mean TTFT 32.02 ms, mean ITL 22.47 ms**. The device
  for that sample is not stated (containers offered: `ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin`
  and `...-jetson-thor`).
- NVIDIA blog (2025-12-11), https://developer.nvidia.com/blog/getting-started-with-edge-ai-on-nvidia-jetson-llms-vlms-and-foundation-models-for-robotics/:
  AGX Orin 64GB targets "4B–20B" models; **gpt-oss-20b at "40 tokens/sec generation speed via
  Open WebUI"** on AGX Orin; Orin Nano Super 8GB targets up to ~4B (Llama 3.2 3B, Qwen2.5-VL-3B...).

**A1.5 Official Jetson AI Lab benchmark page**
https://www.jetson-ai-lab.com/archive/benchmarks.html — the AGX Orin / Thor LLM, SLM and VLM charts
are SVGs whose labels are rendered as vector paths (0 `<text>` nodes; verified by downloading the
SVGs), so the AGX Orin numbers could not be extracted. The page's HTML table for **Orin Nano Super**
(MLC, INT4): Llama 3.1 8B 14 → 19.14 t/s; Llama 3.2 3B 27.7 → 43.07 t/s; Qwen2.5 7B 14.2 → 21.75 t/s;
InternVL2.5 4B 2.5 → 5.1; PaliGemma2 3B 13.7 → 21.6; clip-vit-base-patch32 196 → 314.
Reproducibility caveat: jetson-containers issue #532 (https://github.com/dusty-nv/jetson-containers/issues/532)
reports Llama2-7b MLC on AGX Orin 32GB measured ~19 t/s vs 47 t/s published, Gemma ~23 vs 75; closed
without explanation. The jetson-containers MLC README (https://github.com/dusty-nv/jetson-containers/blob/master/packages/llm/mlc/README.md)
gives one example: Llama-2-7b q4f16_ft decode 46.9 t/s, prefill 632.8 t/s (device unstated).

**A1.6 Sub-1B models (Orin Nano Super; AGX Orin will be faster)**
Source: smolhub.com "Tiny LLM Benchmark: Jetson Orin Nano Super 8GB", https://smolhub.com/posts/jetson-nano-super-benchmark-non-reasoning/
(llama.cpp b9292, JetPack r36.4.7, ctx 2048, gen 256, 25 W mode):

| Model | Quant | GGUF | Out tok/s | TTFT p50 |
|---|---|---|---|---|
| SmolLM2-135M | Q4_K_M | 101 MB | 165.2 | ~80–820 ms |
| SmolLM2-360M | Q8_0 | 369 MB | 102.2 | ~400 ms |
| Qwen2.5-0.5B | Q4_K_M | 469 MB | 92.9 | ~500 ms |
| Qwen3-0.6B | Q8_0 | 610 MB | 49.4 | ~550 ms |
| Llama3.2-1B | Q4_K_M | 771 MB | 47.1 | ~750 ms |
| Gemma3-1B | Q4_K_M | 769 MB | 40.8 | ~700 ms |

"25W (nvpmodel -m 1) is the paretto sweet spot for every model". Eric X. Liu's Orin Nano study
(https://ericxliu.me/posts/benchmarking-llms-on-jetson-orin-nano/): Qwen2.5-0.5B Q4_K_M via Ollama
35.24 t/s, Qwen3-0.6B FP8 38.84 t/s, first-token 0.5–1.4 s; "average efficiency 20.8% of theoretical
compute"; conclusion: memory-bound.

**A1.7 TensorRT Edge-LLM (new NVIDIA C++ runtime)**
Source: https://www.jetson-ai-lab.com/tutorials/tensorrt-edge-llm/ — supports AGX Orin / Orin NX /
Orin Nano (CC 8.7) and Thor; model families Llama 3.x, Qwen3/3.5/3.6, InternVL3/3.5, Phi-4-MM,
Nemotron-Nano; 0.6B–27B; INT4 AWQ on Orin (NVFP4/FP8 Thor only); **requires JetPack 7.2 / R39.2 on
Orin**. Independent Orin Nano Super numbers (https://github.com/hokwangchoi/jetson-orin-nano-benchmarks,
JetPack 6.2.2, MAXN_SUPER), Cosmos-Reason2-2B VLM:

| Runtime | Quant | TTFT text | TTFT image | TPOT | TPS | Peak mem |
|---|---|---|---|---|---|---|
| llama.cpp | Q4_K_M | 33 ms | 114 ms | 26 ms | 38 | — |
| vLLM | W4A16 AWQ | 61 ms | 75 ms | 17 ms | 56 | 6.9 GB |
| TRT Edge-LLM | W4A16 AWQ | 29 ms | 420 ms | 17 ms | 60 | 4.3 GB |

### A2. Small VLMs

- **Qwen2.5-VL-3B on AGX Orin 64GB** (NVIDIA forum, https://forums.developer.nvidia.com/t/the-token-speed-of-qwen-2-5-vl-3b-model-is-very-lower-on-jeston-agx-orin/345073):
  NVIDIA staff: "225.65 output token throughput on an AGX Orin 64GB" (vLLM, concurrency 8, ISL/OSL
  2048/128). The user's un-tuned run on JetPack 6.2.1 with vLLM w4a16 got 30 tok/s. HF card
  (https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct): "4B params" including the ViT; visual tokens
  configurable 4–16,384 per image via `min_pixels/max_pixels` (example 256–1280 tokens).
- **Qwen3-VL-4B Q4_K_M in llama.cpp on AGX Orin** (https://github.com/ggml-org/llama.cpp/discussions/17732):
  image encode **4,079 ms** for 2,040 image tokens, decode of image batch 1,181 ms, prompt eval
  359 t/s, generation **32.7 t/s**, 2.38 GB GPU memory, flash attention on. Vision encoding, not the
  LLM, dominates per-frame latency.
- **Moondream 2 on Jetson AGX Orin** (m87-labs Kestrel PERFORMANCE.md, https://github.com/m87-labs/kestrel/blob/main/PERFORMANCE.md):
  ChartQA "query" skill, prefix caching, batch 64: Direct (~3 output tokens) **4.63 req/s, P50 5,111 ms**;
  CoT (~30 tokens) 3.28 req/s, P50 15,141 ms. Thor batch 64: 15.13 req/s, 1,805 ms. The moondream.ai
  landing page (https://moondream.ai/) shows "514 ms" P50 / "4.6 req/s" for AGX Orin running Moondream 2
  — same throughput, so 514 ms is presumably per-request service time at lower batch; **[my inference]**
  a single query on AGX Orin costs ~0.2–0.5 s. Weights: "open weights · commercial use".
- **SmolVLM-256M-Instruct** (https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct): 256M
  (SigLIP 93M + SmolLM2-135M), Apache 2.0, "can run inference on one image with under 1GB of GPU RAM",
  64 visual tokens per 512x512 patch. No Jetson throughput found. LearnOpenCV's Jetson Orin Nano VLM
  guide (https://learnopencv.com/vlm-on-jetson-nano/, 2025-09) runs Moondream2, LFM2-VL-450M/1.6B,
  FastVLM-0.5B/1.5B and SmolVLM2-2.2B via HF Transformers but publishes no numbers.

### A3. ASR on Orin

- **whisper_trt (NVIDIA-AI-IOT), Jetson Orin Nano, 20 s audio** (https://github.com/NVIDIA-AI-IOT/whisper_trt):

  | Model | whisper (PyTorch) | faster-whisper | WhisperTRT |
  |---|---|---|---|
  | tiny.en | 1.74 s / 569 MB | 0.85 s / 404 MB | **0.64 s** / 488 MB |
  | base.en | 2.55 s / 666 MB | n/a | **0.86 s** / 439 MB |

  i.e. RTF ~0.03–0.04 on the smallest Orin; "~3x faster" and "~60%" memory vs PyTorch. First call
  builds a TensorRT engine (cached in `~/.cache/whisper_trt/`).
- **AGX Orin, whisper tiny.en, ~10 s jfk.wav**: "1.6 s for both models" (FP16 and Q8_0), Orin in
  "its most efficient mode" (15 W); RTX 4090 0.49 s (arXiv 2511.02269, https://arxiv.org/html/2511.02269v1).
  Framework/batch not specified by the paper — weak number.
- **whisper.cpp large-v3 family on AGX Orin** (vendor KB, Yobitel, https://yobitel.com/knowledge-base/whisper):
  Q5_K large-v3 RTF ~0.9 (~1 stream); large-v3-turbo RTF ~0.15 (~6 streams). Vendor claim, no method.
- whisper.cpp on Jetson: first load "more than 10 minutes" on AGX Xavier and AGX Orin with CUDA
  (https://github.com/ggml-org/whisper.cpp/issues/2402, unresolved) — plan for engine/JIT warmup.
- **Parakeet TDT 0.6B**: v2 WER 6.05%, RTFx 3,386 at batch 128 on datacenter GPUs, CC-BY-4.0
  (https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2); v3 25 languages, WER 6.32%, RTFx 3,332.74,
  CC-BY-4.0, streaming script provided (https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3). On Jetson:
  NeMo CUDA fails with "CUDA error: no kernel image is available for execution on the device"; NVIDIA:
  "haven't tried on Jetson"; users fall back to CPU or sherpa-onnx (https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2/discussions/19).
  sherpa-onnx int8 v3: encoder 622 MB; RTF on an RK3588 Cortex-A76 CPU 0.220 (1 thread) → 0.088
  (4 threads) (https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/nemo-transducer-models.html).
- **Moonshine v2** (arXiv 2602.12241, https://arxiv.org/html/2602.12241v1): tiny 33.57M / small
  123.36M / medium 244.93M params; avg WER 12.01 / 7.84 / 6.65; response latency on Apple M3 **50 /
  148 / 258 ms** at 8–29% CPU; medium "43.7x faster than Whisper Large v3" (11,286 ms); fixed encoder
  latency via sliding-window attention; no Jetson row. Moonshine v1 (https://arxiv.org/abs/2410.15608):
  "5x reduction in compute" vs Whisper tiny.en for a 10 s segment at equal WER. License: MIT for the
  toolkit and current models (https://github.com/moonshine-ai/moonshine).
- Riva embedded: jetson-containers `riva-client` README says the Riva server runs "locally on your
  Jetson Xavier or Orin device and is supported on JetPack 5"; the Riva support-matrix and embedded
  quick-start pages returned 404 in this session, so JetPack 6 status is **unknown**.

### A4. TTS on Orin

- **Piper**: original repo MIT, archived 2025-10-06; successor `OHF-Voice/piper1-gpl` is **GPL-3.0**
  (embeds espeak-ng) (https://github.com/rhasspy/piper, https://github.com/OHF-Voice/piper1-gpl).
  jetson-containers ships `piper1-tts` (L4T >= 32.6) and notes the GPL. On Jetson Orin Nano in ROS 2
  with `onnxruntime-gpu`: first audible sound **~800–900 ms end-to-end** after a ROS message, voice
  `en_US-amy-low` (https://thomasthelliez.com/blog/running-piper-tts-on-nvidia-jetson-orin-nano-with-low-latency/).
- **Kokoro-82M**: 82M params, Apache 2.0, StyleTTS2/ISTFTNet decoder, 24 kHz, 8 languages / 54 voices,
  trained on "a few hundred hours" for ~$1,000 (https://huggingface.co/hexgrad/Kokoro-82M).
  jetson-containers has `kokoro-tts:onnx`, `:hf`, `:fastapi` packages (CUDA 12.6, PyTorch 2.8) but
  publishes no RTF (https://github.com/dusty-nv/jetson-containers, packages/speech/kokoro-tts/*).
- CPU relative cost (sherpa-onnx PR #2460, MacBook Pro, single thread, https://github.com/k2-fsa/sherpa-onnx/pull/2460):
  Piper medium fp32 RTF **0.114** (75 MB), fp16 0.123, int8 0.320; MatchaTTS 0.118; KittenTTS 0.389
  (23 MB); **Kokoro fp32 RTF 1.128** (330 MB), int8 1.972. So Kokoro needs the GPU on Orin; Piper
  can run on the CPU cores.
- NVIDIA forum on TTS for Orin Nano (https://forums.developer.nvidia.com/t/tts-better-than-piper-for-jetson-orin-nano/339548):
  user wants "<700 ms for short sentences"; NVIDIA: "We don't have experience with the TTS other than
  the tutorial"; XTTS "high response time". No numbers.
- **Sesame CSM-1B** (https://huggingface.co/sesame/csm-1b): "the 1B CSM variant" (2025-03-13),
  "a Llama backbone and a smaller audio decoder that produces Mimi audio codes"; HF metadata says
  "Model size: 2B params, F32"; Apache 2.0; 24 kHz; English; needs a separate text LLM; fine-tunable
  with HF Trainer; explicit no-impersonation terms. No latency or Jetson figures anywhere I found.

### A5. Full-duplex speech models on Orin

- **Moshi** (https://github.com/kyutai-labs/moshi; paper https://kyutai.org/Moshi.pdf, text extracted
  with pdftotext): 7B Temporal Transformer initialised from Helium (7B, pretrained on 2.1T tokens) plus
  a Depth Transformer; Mimi codec at **12.5 Hz**, Q = 8 codebooks x 2048 entries = **1.1 kbps**, 24 kHz;
  "theoretical latency of 160ms, 200ms in practice" (README: 200 ms "on an L4 GPU"). PyTorch: "we do
  not support quantization for the PyTorch version, so you will need a GPU with a significant amount
  of memory (24GB)". int8 via Rust/Candle (`kyutai/moshiko-candle-q8`, described as an 8B-parameter
  8-bit GGUF, https://huggingface.co/kyutai/moshiko-candle-q8) and int4/int8 via MLX (macOS only).
  Code MIT (Python) / Apache-2.0 (Rust); weights CC-BY-4.0.
- **Has anyone run Moshi on AGX Orin?** No. The only thread (https://forums.developer.nvidia.com/t/kyutai-moshi-install/331658)
  is an unanswered question; NVIDIA staff: "We don't have experience with Moshi." MoshiRAG also
  requires "a GPU with a significant amount of memory (24GB)" (https://github.com/kyutai-labs/moshi-rag).
- **PersonaPlex-7B-v1** (NVIDIA, Moshi architecture, https://huggingface.co/nvidia/personaplex-7b-v1):
  7B bf16; NVIDIA Open Model License (+CC-BY-4.0 components), "ready for commercial use"; tested on
  A100 80GB (Ampere/Hopper listed); turn-taking latency 0.170 s, user-interruption latency 0.240 s,
  95% interruption success. No Jetson mention.
- **[my inference] bandwidth budget for Moshi-class on AGX Orin 64GB.** The temporal transformer must
  step at 12.5 Hz. Int8 weights ~7 GB read per step -> ~87.5 GB/s, i.e. ~43% of the 204.8 GB/s peak
  before the depth transformer (8 sub-steps), Mimi encode/decode, and the fact that real decoders reach
  ~20–60% of peak (A1.6). bf16 would need ~175 GB/s (>85% of peak) — not credible. So int8 Moshi on the
  external AGX Orin is *plausible but unproven*, bf16 is not, and on the dog's Orin NX (102.4 GB/s)
  neither is. Nobody has published a run.

---

## B. Unitree Go2 EDU control surfaces

Caveat up front: the official pages at support.unitree.com (Basic_motion_control, Basic_services,
AI_motion_service, "Motion Switcher Service Interface", "Motion Control Service Interface V2.0 Update
Notice", Quick_start, module_update) are a JS single-page app (the HTML is a 707-byte shell loading
`/assets/index-7c5888a6.js`; the bundle contains no fetchable data endpoint). They could not be read in
this session. Everything below is taken from the SDK source on GitHub, its examples and commit history,
plus a few secondary sources that are flagged.

### B1. What the EDU buys you (and what Air/Pro do not)

- Unitree product page (https://www.unitree.com/go2): Air $1,600 / Pro $2,800 / X $4,500 / EDU
  "contact sales"; joint torque "About 45N.m"; max speed "0 ~ 3.7m/s (MAX ~ 5m/s)"; ~15 kg; EDU-only:
  foot-end force sensor, charging pile, "Secondary development" (full support), 15000 mAh battery
  (2–4 h), 9 A fast charger.
- DroneBlocks (reseller, https://droneblocks.io/introducing-the-unitree-go2-edu-quadruped-a-new-era-of-robotics-education-with-droneblocks/):
  EDU compute "NVIDIA Jetson Orin NX 16GB module, which delivers an astounding 100 TOPS"; L2 4D LiDAR
  360°x90°, min range 0.05 m; optional Mid-360 (360° horizontal, -7° to 52° vertical, 70 m) or Hesai
  XT16; 8000 mAh (1–2 h) or 15000 mAh (2–4 h), 28.8 V.
- Roboworks (reseller, https://www.roboworks.net/store/p/unitree-go2-wc48f): "Go2 Edu Standard: extra
  Jetson Orin Nano board"; "Go2 Edu Plus: extra Jetson Orin NX board"; both add a RealSense depth
  camera, voice module + microphone, foot sensors, eSIM 4G; Standard from USD 17,648.
- MyBotShop forum (https://forum.mybotshop.de/t/unitree-go2-low-level-control/950): "The Go2 Pro model
  doesn't support any type of programming. Only edu/edu+ versions support it." Robot IP
  192.168.123.161.
- legion1581/go2_python_sdk README (https://github.com/legion1581/go2_python_sdk): "CycloneDDS works
  out of the box only with the EDU version"; Air/Pro need a custom firmware; the WebRTC path used by the
  app "is limited to topics... low-level commands would not work fully as rt/lowcmd is not supported.
  Reading is only supported through rt/lf/lowstate (lf for low frequency)"; it also exposes a
  `motion_swither_client` "for switching between normal and advanced sport modes".

**Bottom line:** everything in B3–B6 is EDU-only. The dog's own Jetson (Orin Nano on EDU Standard,
Orin NX 16GB on EDU Plus) is a *separate* computer on the 192.168.123.x Ethernet; the locomotion
controller ("sport" / "motion_switcher" / "ai_sport" services) lives on the robot's internal controller,
which is what the SDK talks to over DDS. **[my inference from the SDK topology; the official network
diagram could not be fetched.]**

### B2. SDK2 basics

- `unitree_sdk2` (https://github.com/unitreerobotics/unitree_sdk2): BSD-3-Clause; Ubuntu 20.04,
  gcc 9.4, CMake >= 3.10; CycloneDDS transport; examples under `example/go2/`: `go2_sport_client.cpp`,
  `go2_low_level.cpp`, `go2_stand_example.cpp`, `go2_robot_state_client.cpp`, `go2_video_client.cpp`,
  `go2_vui_client.cpp` (`go2_trajectory_follow.cpp` is present but **commented out** of CMakeLists).
- `unitree_sdk2_python` (https://github.com/unitreerobotics/unitree_sdk2_python): BSD-3-Clause,
  Python >= 3.8, `cyclonedds == 0.10.2`; "First, use the app to turn off the high-level motion service
  (sport_mode) to prevent conflicting instructions" before low-level control; low-level example holds one
  hip at 0 deg "for safety, set kp=10, kd=1" and outputs 1 N·m on a calf joint.
- Network: PC static IP 192.168.123.99/24 (unitree_ros2 README, https://github.com/unitreerobotics/unitree_ros2)
  or 192.168.123.222/24 (unitree_rl_mjlab README); DDS domain 0 on the real robot, 1 on `lo` for the
  MuJoCo bridge.
- ROS 2 topics (unitree_ros2 README): `/lowcmd`, `/lowstate` and `lf/lowstate`, `/sportmodestate` and
  `lf/sportmodestate` ("lf" = low frequency), `/wirelesscontroller`, `/utlidar/cloud`,
  `/api/sport/request` (request/response). No publish rates stated.

### B3. SportClient — the high-level action surface (service "sport", API version "1.0.0.1")

Current `main` header, verified by raw fetch of
https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_api.hpp and
`sport_client.hpp`; Python mirror `unitree_sdk2py/go2/sport/sport_api.py` matches. 39 methods:

| ID | Method | Notes |
|---|---|---|
| 1001 | `Damp()` | passive damping |
| 1002 | `BalanceStand()` | |
| 1003 | `StopMove()` | |
| 1004 | `StandUp()` | |
| 1005 | `StandDown()` | |
| 1006 | `RecoveryStand()` | |
| 1007 | `Euler(roll, pitch, yaw)` | body attitude — the only continuous "expression" knob |
| 1008 | `Move(vx, vy, vyaw)` | velocity; example uses `Move(0.3, 0, 0.3)` |
| 1009 | `Sit()` | |
| 1010 | `RiseSit()` | |
| 1015 | `SpeedLevel(int)` | |
| 1016 | `Hello()` | wave |
| 1017 | `Stretch()` | |
| 1020 | `Content()` | "happy" |
| 1022 / 1023 | `Dance1()` / `Dance2()` | |
| 1027 | `SwitchJoystick(bool)` | |
| 1028 | `Pose(bool)` | |
| 1029 | `Scrape()` | |
| 1030 / 1031 / 1032 | `FrontFlip()` / `FrontJump()` / `FrontPounce()` | |
| 1036 | `Heart()` | |
| 1061 / 1062 / 1063 | `StaticWalk()` / `TrotRun()` / `EconomicGait()` | gait selectors (renumbered) |
| 2041 / 2043 / 2044 | `LeftFlip()` / `BackFlip()` / `HandStand(bool)` | |
| 2045–2048 | `FreeWalk()` / `FreeBound(bool)` / `FreeJump(bool)` / `FreeAvoid(bool)` | |
| 2049–2051 | `ClassicWalk(bool)` / `WalkUpright(bool)` / `CrossStep(bool)` | |
| 2054 / 2055 | `AutoRecoverSet(bool)` / `AutoRecoverGet(bool&)` | |
| 2058 | `SwitchAvoidMode()` | |

Client defaults from `go2_sport_client.cpp`: `SetTimeout(10.0f)`, `Init()`; a stale comment gives a
body-height range of -0.18 to 0.03 m from the old API.

**What was removed.** Commit 0953c60 "update for syncretic_motion_control" (2025-05-21, 9 files,
+64/-444; https://github.com/unitreerobotics/unitree_sdk2/commit/0953c60143) deleted these Go2 sport
APIs that existed in the 2024-01-02 and 2024-11-25 headers (raw-fetched at 124f92953e and 01ead90a08):
`SwitchGait(int)` 1011, `Trigger()` 1012, **`BodyHeight(float)` 1013, `FootRaiseHeight(float)` 1014**,
`TrajectoryFollow(vector<PathPoint>)` 1018, `ContinuousGait(bool)` 1019, `Wallow()` 1021,
**`WiggleHips()` 1033**, `GetState()` 1034, old `EconomicGait(bool)` 1035, `Dance3/4` 1037/1038,
`HopSpinLeft/Right` 1039/1040, plus legacy 1042–1051. (`GetBodyHeight/GetFootRaiseHeight/GetSpeedLevel`
1024–1026 were already commented out in 2024.) The trajectory example (30 `PathPoint`s at 0.06 s spacing;
fields `timeFromStart, x, y, yaw, vx, vy, vyaw`) still calls `TrajectoryFollow` and therefore no longer
compiles — hence its CMake line is commented out. Whether older robot firmware still serves 1011–1040 is
not something I could verify (the V2.0 update notice page is unfetchable).

### B4. MotionSwitcher — mode gating (service "motion_switcher")

Headers `include/unitree/robot/b2/motion_switcher/motion_switcher_api.hpp` / `_client.hpp` (shared
by Go2) and `unitree_sdk2py/comm/motion_switcher/*`: `CheckMode(form, name)` 1001,
`SelectMode(nameOrAlias)` 1002, `ReleaseMode()` 1003, `SetSilent(bool)` 1004, `GetSilent(bool&)` 1005.
Mode names appear only in the Python example (`example/motionSwitcher/motion_switcher_example.py`):
`"ai"` (default in the example), `"normal"`, `"advanced"`, `"ai-w"` ("for wheeled robot"). The
low-level stand examples (C++ and Python) loop on `CheckMode()` and call `ReleaseMode()` (and
`SportClient.StandDown()`) until no motion mode is active before publishing `rt/lowcmd`; the
unitree_rl_lab Go2 deployer refuses to start if "The other process is using the lowcmd channel".
=> **high-level sport control and low-level joint control are mutually exclusive**, and the switch is a
service call that the safety layer must own.

### B5. LowCmd / LowState — the joint-level surface

IDL: `include/unitree/idl/go2/LowCmd_.hpp` and `LowState_.hpp` (fetched).
- `LowCmd_`: `head[2]`, `level_flag`, `frame_reserve`, `sn[2]`, `version[2]`, `bandwidth`,
  **`motor_cmd[20]`** (`mode` uint8, `q`, `dq`, `tau`, `kp`, `kd`, `reserve[3]`), `bms_cmd`,
  `wireless_remote[40]`, `led[12]`, `fan[2]`, `gpio`, `reserve`, **`crc`**. Go2 uses 12 of the 20 slots.
  Joint torque is `tau + kp*(q_des - q) + kd*(dq_des - dq)` in the motor driver (standard Unitree PD form;
  the examples set `mode = 0x01` "motor switch to servo (PMSM) mode"). The CRC32 must be computed over
  the struct (`crc32_core((uint32_t*)&low_cmd, (sizeof(LowCmd_)>>2)-1)`) or the command is dropped.
- `LowState_`: `imu_state` (quaternion, gyro, accel, temperature), `motor_state[20]` (`q, dq, ddq,
  tau_est, temperature, lost`), `foot_force[4]`, `foot_force_est[4]`, `bms_state`, `power_v`, `power_a`,
  `tick`, `wireless_remote[40]`, `bit_flag`, `temperature_ntc1/2`, `fan_frequency[4]`, `crc`.
- Rate: both official examples run the command loop at **`dt = 0.002` s (500 Hz), comment "0.001~0.01"**
  (`go2_low_level.cpp`, `go2_stand_example.cpp`, `go2_stand_example.py`). The DeepWiki overview of the
  SDK also says "500Hz control loops" (secondary). Gains in the examples: stand-up `Kp = 60, Kd = 5`;
  sine test `Kp = 5, Kd = 1`; `PosStopF = 2.146E+9`, `VelStopF = 16000` sentinel values. Stand sequence:
  500 ms + 500 ms + 1000 ms hold + 900 ms interpolation. Warning text: "Make sure the robot is hung up
  or lying on the ground".

### B6. Training and deploying your own low-level policy

- **unitree_rl_lab** (Apache-2.0, https://github.com/unitreerobotics/unitree_rl_lab): IsaacLab 2.3.0 /
  IsaacSim 5.1.0; robots Go2, H1, G1-29dof; deploy path "unitree_mujoco for sim-to-sim, unitree_sdk2 for
  sim-to-real". Go2 velocity env (`tasks/locomotion/robots/go2/velocity_env_cfg.py`, raw-fetched):
  `sim.dt = 0.005`, `decimation = 4` -> **policy step 20 ms = 50 Hz**; `episode_length_s = 20`;
  `num_envs = 4096`; actions = joint-position offsets, `scale = 0.25`; observations `base_ang_vel`
  (x0.2), `projected_gravity`, `velocity_commands`, `joint_pos_rel`, `joint_vel_rel` (x0.05), `actions`
  (privileged critic adds `joint_effort`); actuator `Go2HV` stiffness 25, damping 0.5
  (`assets/robots/unitree.py`). Deployer (`deploy/robots/go2/`): C++ FSM `Passive` (kd 3) ->
  `FixStand` (kp [60,80,80]x4, kd [5,4,4]x4, two-keyframe interpolation) -> `Velocity` (RLBase, ONNX via
  bundled onnxruntime 1.22.0, loop `sleep_until(step_dt)`); gamepad `L2+A` then `Start`.
- **unitree_rl_mjlab** (Apache-2.0, https://github.com/unitreerobotics/unitree_rl_mjlab): same
  IsaacLab-style API on **MuJoCo Warp** (GPU MuJoCo); Go2, A2, As2, G1, R1, H1_2, H2; train
  `--env.scene.num-envs=4096`, multi-GPU `--gpu-ids`; auto-exports `policy.onnx`; real deploy: PC
  192.168.123.222/24, robot suspended in zero-torque, `L2+R2` = "debug mode" (joint damping), then
  `./<robot>_ctrl --network=<if>`; sim-to-sim through `./simulate/build/unitree_mujoco --network=lo`.
- **unitree_rl_gym** (BSD-3, https://github.com/unitreerobotics/unitree_rl_gym): Isaac Gym + MuJoCo;
  `deploy_real` "Currently supported robots include Unitree G1, H1, H1_2" — **no Go2 real-deploy
  config** (`configs/` has only g1/h1/h1_2.yaml).
- **unitree_mujoco** (BSD-3, https://github.com/unitreerobotics/unitree_mujoco): MuJoCo scenes for Go2,
  B2, B2w, H1, Go2w, G1, H1-2, AS2 that expose the **same DDS `LowCmd` / `LowState` / `SportModeState`
  messages** as the real robot, so SDK2 / ROS 2 / Python control code runs unchanged; Python bridge
  `SIMULATE_DT = 0.005` (200 Hz physics), `VIEWER_DT = 0.02`, `DOMAIN_ID = 1`, `INTERFACE = "lo"`,
  xbox/switch gamepad emulation of the WirelessController; C++ `simulate/` is the recommended build.
  (Note: it does *not* emulate the sport service — only the joint-level interface.)

---

## C. What this means for Parcel

1. **Two very different action surfaces, and the cheap one just got narrower.** With the current SDK
   the "trick" vocabulary is 1016 Hello, 1017 Stretch, 1020 Content, 1022/1023 Dance, 1028 Pose,
   1029 Scrape, 1030–1032 flips/jumps/pounce, 1036 Heart, Sit/RiseSit/StandUp/StandDown/Damp, plus
   the 2041–2058 gaits and stunts. The only *continuous* expressive channels left in sport mode are
   `Euler(roll, pitch, yaw)`, `Move(vx, vy, vyaw)` and `SpeedLevel`; `BodyHeight`, `FootRaiseHeight`,
   `WiggleHips`, `ContinuousGait` and `TrajectoryFollow` were deleted in May 2025. Anything richer than
   "pick a preset + tilt/turn" — a learned chuckle-bounce, a glance-back-over-the-shoulder, breathing
   amplitude driven by conversational state — needs the 500 Hz `rt/lowcmd` surface with a custom
   policy, which is EDU-only and mutually exclusive with sport mode (B4).
2. **The realistic split for "learn to chuckle / learn to look back":**
   - *Look back at the owner when lost* is expressible today in sport mode: it is a yaw/`Euler` + `Move`
     policy over owner-bearing and localisation-confidence inputs. It can be learned as a small
     discrete/continuous policy on top of Parcel's existing 50 Hz body-intent lane without touching
     the joints. Train it in Parcel's MuJoCo/grid sim; validate the command path through
     unitree_mujoco's DDS bridge only if we go low-level.
   - *Chuckle if the joke was funny* has a cheap version (trigger `Content`/`Heart`/`Scrape` with
     learned timing/probability from the affect signal) and an expensive version (a learned whole-body
     "laugh" on `rt/lowcmd`). The expensive version is a unitree_rl_lab / unitree_rl_mjlab job:
     50 Hz joint-offset policy, 4096 envs, ONNX out, C++ FSM in — exactly the pipeline Unitree ships,
     and MuJoCo Warp matches the MuJoCo 3.11 stack already on the desktop.
3. **Compute budget on the external AGX Orin 64GB.** Expect ~30–50 tok/s for an 8B Q4 LLM
   (llama.cpp / TensorRT-LLM), ~90–165 tok/s for 0.1–0.5B models on an Orin Nano (faster on AGX), a
   Qwen2.5-VL-3B frame costing seconds in llama.cpp (image encode ~4 s for 2k tokens) but ~0.2–0.5 s
   per Moondream-2 query in Kestrel, and TTFT of 0.5–1.2 s for 1–8B models at 2k context. That rules
   out running any LM inside a 20 ms (50 Hz) loop; LMs set intent at 1–5 Hz and a small ONNX policy
   owns the 50 Hz lane, as unitree_rl_lab does. The dog's own Orin NX 16GB is ~half the bandwidth
   and a quarter of the memory: keep it for perception/LiDAR/SDK bridging, not for the LLM/VLM.
4. **Full-duplex speech stays hosted for now.** Nobody has run Moshi/PersonaPlex on an Orin; bf16
   needs 24 GB and >85% of the 204.8 GB/s bandwidth at 12.5 Hz; int8 is borderline on paper only.
   The <= $300/mo Realtime API remains the duplex path; a local fallback of whisper_trt/Moonshine
   (<300 ms) + Piper (RTF ~0.1 CPU; ~0.8–0.9 s end-to-end measured on Orin Nano) is feasible. If we
   do want a *trainable* duplex model, the trainable unit should be a small listener/turn-taking head
   over Mimi-style tokens, not the 7B speech LM.
5. **Licenses to watch:** Qwen2.5-3B is "Qwen Research License", Llama 3.2 is a custom community
   license, piper1-gpl is GPL-3.0 (the archived MIT Piper still works), PersonaPlex is NVIDIA Open
   Model License, Moshi weights CC-BY-4.0, Parakeet CC-BY-4.0, Kokoro / SmolVLM / CSM-1B Apache 2.0,
   all Unitree repos BSD-3 or Apache-2.0.
6. **Safety-layer obligations that fall out of the SDK:** own `CheckMode/ReleaseMode`, refuse to
   publish `rt/lowcmd` while a sport mode is active, compute the CRC, enforce the 500 Hz cadence
   (dt 1–10 ms), start in damping (`Passive`, kd 3) and pass through a fixed stand before any policy
   (as the Unitree FSM does), and treat the app's sport-mode toggle as an external state change.

## D. Gaps / could not verify

- Official Unitree doc pages (rt/lowstate publish rate, AI-mode requirements for FrontFlip/Dance,
  firmware compatibility of the 2000-series APIs, expansion-dock IP/topology) — JS-only site.
- Jetson AI Lab AGX Orin official LLM/VLM numbers — SVG charts with no text nodes.
- Riva embedded on JetPack 6 — support-matrix pages 404.
- Any Kokoro / CSM-1B / Moshi / Parakeet-GPU measurement on Orin — none found.
- Moondream AGX Orin batch-1 latency (only batch-64 P50 and a landing-page "514 ms").
