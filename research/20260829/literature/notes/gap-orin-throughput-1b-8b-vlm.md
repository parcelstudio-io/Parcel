# Gap note: measured VLM throughput on Jetson AGX Orin 64 GB (0.5B–8B), with Orin NX / Thor for scale

Date: 2026-08-29. Scope: what has actually been *measured* for 0.5B–8B vision-language models (and the VLAs built on them) on Jetson AGX Orin 64 GB — prefill and decode tokens/s, per-step latency, precision, runtime, power mode — at navigation-relevant token counts (1–2 images per step, or an 8-frame × 196-token memory), plus Orin NX and Thor as scale points. Every number below was read from the cited page on 2026-08-29; nothing is from memory. Where I derive a number (marked **derived**) I show the arithmetic.

Bottom line first (sizing table at the end):

- No published system runs an autoregressive VLM inside a 10 Hz loop on an Orin. The fastest measured VLM step on AGX Orin is SmolVLM-256M (Q4_K_M, llama.cpp): 150.5 ms = 6.6 Hz with 12 output tokens. Only VLAs with non-autoregressive, chunked action heads (π0 27.9 ms, GR00T-N1.6 26.7 ms per step, *amortised over an action chunk*) reach 10 Hz-class numbers.
- A 1–2B VLM with ≤ 2 frames and ≤ 16 output tokens is a ~2 Hz lane on AGX Orin (Moondream-2 P50 514 ms; Qwen2.5-VL-3B-AWQ on the smaller Orin NX: TTFT 0.47 s + 32 ms/token). With an 8-frame × 196-token memory it becomes a ~1 Hz lane (prefill of ~1.6k tokens ≈ 0.45 s for a 1.5B model + decode).
- A 7–8B VLM is a ≥ 1 Hz lane only for single-image, ≤ 8-token outputs at INT4 (OpenVLA-7B INT4: 375 ms; Llama-3-VILA1.5-8B INT4 streaming 5.05 FPS); with 8 frames + a 32-token plan it is 0.2–0.3 Hz (prefill ≈ 2.3 s FP16 + 32 tokens at 10–40 tok/s).
- Runtime and precision choice is worth 3–7×: HF transformers TPOT 136 ms for Qwen3-VL-2B vs 32 ms for Qwen2.5-VL-3B-AWQ under vLLM (on an Orin NX); BitsAndBytes INT4 makes Orin *slower* (+56 % TPOT), INT8 on SigLIP encoders 2.4–4.7× slower. Vision encoders alone cost 100–160 ms per frame FP16 on AGX Orin.
- Jetson Thor is 1.6–2.7× AGX Orin on VLM/VLA and adds FP8/NVFP4; the only navigation VLM measured at ~5 Hz on a robot is Qwen-RobotNav-4B on Thor (FP8 + TensorRT, 204 ms).

---

## 1. NVIDIA's own numbers (vLLM, aggregate throughput at concurrency 8)

### S1 — NVIDIA Jetson Benchmarks page
https://developer.nvidia.com/embedded/jetson-benchmarks (read 2026-08-29)

Thor developer kit, "JetPack 7.0, NVIDIA CUDA 13.0, and NVIDIA TensorRT 10.13", vLLM, "ISL/OSL as 2048/128":

| Model | conc. 1 (tok/s) | conc. 8 (tok/s) |
|---|---|---|
| Qwen2.5-VL 3B | 71.7 | 356.86 |
| Qwen2.5-VL 7B | 45 | 252 |
| Llama 3.2 11B Vision | 26.31 | 69.63 |
| Llama 3.1 8B | 41.3 | 150.8 |
| Qwen3 30B-A3B | 61 | 226.4 |
| Qwen3 32B | 13.19 | 79.1 |
| DeepSeek R1 7B | 41.32 | 304.8 |

The page does not list AGX Orin single-stream numbers; the Orin figures come from the Thor launch blog below.

### S2 — NVIDIA blog "Introducing NVIDIA Jetson Thor" (2025-08-25)
https://developer.nvidia.com/blog/introducing-nvidia-jetson-thor-the-ultimate-platform-for-physical-ai/

Config stated on the page: sequence length 2048, output 128, **max concurrency 8**, vLLM (LLM/VLM), TensorRT (VLA), **MAXN on both platforms**.

| Model | Thor tok/s | AGX Orin tok/s | Thor/Orin |
|---|---|---|---|
| Qwen2.5-VL-3B | 356.86 | **216** | 1.65× |
| Qwen2.5-VL-7B | 252 | **154.02** | 1.64× |
| Llama 3.2 11B Vision | 69.63 | 44.22 | 1.57× |
| Llama 3.1 8B | 150.8 | 112.33 | 1.34× |
| DeepSeek-R1-Distill-Qwen-7B | 304.76 | 180.41 | 1.69× |
| Qwen3-30B-A3B | 226.42 | 76.69 | 2.95× |
| Qwen3-32B | 79.1 | 16.84 | 4.70× |
| GR00T N1 (VLA, TensorRT) | 46.7 | 18.5 | 2.52× |
| GR00T N1.5 | 41.5 | 15.2 | 2.74× |

Reading: these are *aggregate* output-token rates over 8 concurrent 2048-token prompts — the right number for a server, not for one robot loop. Dividing by 8 gives ~27 tok/s (3B) and ~19 tok/s (7B) per stream, and the Thor page's concurrency-1 rows (71.7 / 45 tok/s) confirm single-stream is 3–5× below the c=8 aggregate. **Derived** single-stream AGX Orin estimate for Qwen2.5-VL-7B: 45 / 1.64 ≈ 27 tok/s; 3B: 71.7 / 1.65 ≈ 43 tok/s.

### S3 — NVIDIA forum threads (users reproducing the above on AGX Orin 64 GB)
- "The token speed of qwen 2.5 vl 3b model is very lower on Jetson AGX Orin" (Sept 2025) https://forums.developer.nvidia.com/t/the-token-speed-of-qwen-2-5-vl-3b-model-is-very-lower-on-jeston-agx-orin/345073 — user (vLLM, w4a16, max concurrency 8, ISL 2048 / OSL 128, JetPack 6.2.1, PyTorch 2.3.0 + CUDA 12.4): **30 tokens/s**; NVIDIA reproduction: "225.65 output token throughput on an AGX Orin 64GB + developer kit" (Sept 22, 2025). A 7× gap from container/kernel mismatch alone.
- "LLM library recommendations for maximum token speeds" (Jan–Mar 2026) https://forums.developer.nvidia.com/t/llm-library-recomendations-for-maximum-token-speeds/358521 — AGX Orin 64 GB, JetPack 6.2: Ollama 7B "~15 tokens/second"; TensorRT-LLM "capped at 20–22 tokens/second" across 0.5B–34B; NVIDIA: "231 tok/s on AGX Orin 64GB with concurrency=8"; advice: `sudo nvpmodel -m 0` + `sudo jetson_clocks`. The user's "300+ tokens a second with llama.cpp ... 7b mistral" ran on an unsupported CUDA 12.9 build with "corruption issues with the cuda buffers" — not a usable number.
- "The token speed of LLM on Jetson AGX Orin" https://forums.developer.nvidia.com/t/the-token-speed-of-llm-on-jetson-agx-orin/343901 — HF transformers on AGX Orin: DeepSeek-R1-Distill-Qwen-1.5B "less than 20 tokens/s", 7B "about 10 tokens/s"; NVIDIA's vLLM w4a16 c=8 figure for the 7B: 180.4 tok/s; 32B: 16.96 tok/s.
- "Performance Comparison of Qwen3-30B-A3B-AWQ on Jetson Thor vs Orin AGX 64GB" https://forums.developer.nvidia.com/t/performance-comparison-of-qwen3-30b-a3b-awq-on-jetson-thor-vs-orin-agx-64gb/345449 — user single-stream: Thor ~53 tok/s, Orin ~41.5 tok/s (MoE, 3B active); NVIDIA c=8: 226.42 vs 76.69.

## 2. Jetson AI Lab benchmarks (MLC INT4, single stream, end-to-end)

### S4 — Jetson AI Lab archived benchmarks (charts rendered locally from the site's SVGs)
https://www.jetson-ai-lab.com/archive/benchmarks.html

"Multimodal Streaming Rate — Vision Encoder + Projector + VLM", refresh rate in FPS (the page: "This measures the end-to-end pipeline performance for continuous streaming like with Live Llava"; 4-bit MLC):

| Model | Jetson AGX Orin (FPS) | Jetson Orin Nano (FPS) |
|---|---|---|
| Obsidian-3B | 2.30 | 0.85 |
| VILA1.5-3B | **7.57** | 2.76 |
| Llama-3-VILA1.5-8B | **5.05** | 1.86 |
| Llava-7B | 1.43 | 0.55 |
| Llava-13B | 0.85 | ~0.1 |
| VILA1.5-13B | 2.85 | ~0.1 |

"LLM Text Generation Rate — Jetson AGX Orin, 4-bit quantization" (tok/s): Llama2-7B 47, Llama3-8B 40, Llama2-13B 25, Llama1-33B 10, Llama2-70B 5.
"SLM Text Generation Rate — 4-bit (MLC/TVM)", AGX Orin / Orin Nano (tok/s): TinyLlama-1.1B 150 / 68; ShearedLlama-1.3B 146 / 56; StableLM-1.6B 111 / 37; ShearedLlama-2.7B 100 / 33; StableLM-3B 92 / 31; OpenLlama-3B 82 / 27; Gemma-2B 75 / 27; Phi-2 (2.7B) 74 / 24.

Caveats: the page does not state JetPack or output length; a GitHub issue (dusty-nv/jetson-containers #532, https://github.com/dusty-nv/jetson-containers/issues/532) reports reproducing only ~19 tok/s (Llama2-7B) and ~23 tok/s (Gemma) on an AGX Orin 32 GB vs the published 47 / 75 — i.e. the published rates need MAXN + jetson_clocks + the exact MLC build.

### S4b — NVIDIA blog "Jetson Orin Nano Developer Kit Gets a Super Boost" (2024-12-17, JetPack 6.1)
https://developer.nvidia.com/blog/nvidia-jetson-orin-nano-developer-kit-gets-a-super-boost/

VLM table (tokens/sec, Orin Nano → Nano Super): VILA 1.5 3B 0.7 → 1.06; VILA 1.5 8B 0.574 → 0.83; LLAVA 1.6 7B 0.412 → 0.57; Qwen2 VL 2B 2.8 → 4.4; InternVL2.5 4B 2.5 → 5.1; PaliGemma2 3B 13.7 → 21.6; SmolVLM 2B 8.1 → 12.9. Footnote: "All VILA and LLAVA models were run with INT4 precision using MLC while the rest of the models were run in FP4 precision with Hugging Face Transformers." NVIDIA staff on the forum (https://forums.developer.nvidia.com/t/jetson-nano-8g-run-vlm-benchmark/325702, 2025-03-05): "The VLM benchmark is generated with the huggingface script with 4-bit quantization." These sub-5 tok/s VLM numbers are end-to-end including vision prefill on an 8 GB part; they are the floor, not the AGX Orin ceiling.

### S4c — NVIDIA blog "Visual Language Intelligence and Edge AI 2.0" (2024-05-03)
https://developer.nvidia.com/blog/visual-language-intelligence-and-edge-ai-2-0/
"VILA1.5 2.7B runs up to 7.5 frames per second on Jetson AGX Orin" with TinyChat 4-bit AWQ; the benchmark "include[s] the overall time to query a frame, including vision encoding (with CLIP or SigLIP), multimodal projection, assembly of the chat embeddings, and generation of the language model output with 4-bit quantization." Consistent with S4's 7.57 FPS.

### S19 — NVIDIA blog "Getting Started with Edge AI on NVIDIA Jetson" (2025-12-11)
https://developer.nvidia.com/blog/getting-started-with-edge-ai-on-nvidia-jetson-llms-vlms-and-foundation-models-for-robotics/
Tiering: Orin Nano Super 8 GB → Qwen2.5-VL-3B / VILA1.5-3B / Gemma-3-4B; **AGX Orin 64 GB → LLaVA-13B, Qwen2.5-VL-7B, Phi-3.5-Vision**; Thor → 70B-class. Only number: gpt-oss-20b at 40 tok/s (vLLM) on AGX Orin. VLA: GR00T N1 "sub-30 ms latency" with TensorRT. No guidance on co-scheduling a VLM with a control loop.

### S18 — TensorRT Edge-LLM on Jetson (Jetson AI Lab tutorial)
https://www.jetson-ai-lab.com/tutorials/tensorrt-edge-llm/
"TensorRT Edge-LLM is NVIDIA's high-performance C++ inference runtime for LLMs and VLMs on embedded platforms." Supported VLMs: Qwen3-VL (2B–8B), InternVL3/3.5 (1B–14B), Cosmos Reason2 8B, Phi-4-Multimodal. Precision: FP16, INT4 AWQ on Orin; FP8 and NVFP4 on Thor only. Requires "Jetson Orin: JetPack 7.2 / Jetson Linux R39.2". No per-model numbers on the tutorial page (its benchmark page is Thor-only per the search index). This is the runtime a Parcel port should target for InternVL3-1B/2B and Qwen3-VL-2B/4B.

## 3. Peer-reviewed / arXiv measurements on Orin

### S5 — TIC-VLA (arXiv 2602.02459v2, ICML 2026) — the only navigator measured on a Go2's Orin NX
https://arxiv.org/html/2602.02459v2 ; code https://github.com/ucla-mobility/TIC-VLA

Backbone "InternVL3-1B vision-language model, which consists of an InternViT-300M vision encoder and a Qwen2.5-0.5B language model". Input: "a sequence of historical images spanning up to a nine-second temporal window", "sampled at three-second intervals, resulting in three historical frames and one current frame" at 1920×1080, encoded to "visual tokens of size 4×256" (= 1024 visual tokens per reasoning step). Output horizon "three seconds, discretized into T=30 action chunks". "the action policy runs at 10 Hz and asynchronous VLM reasoning running at 0.5 Hz".

| Platform | action policy (ms) | VLM reasoning (ms) | real-world SR |
|---|---|---|---|
| RTX A6000 | 32.70 | 1681.66 | 0.80 |
| RTX 4060 Laptop (50 W) | 85.73 | 3430.73 | 0.85 |
| **Jetson Orin NX (25 W)** | **120.27** | **4831.73** | **0.75** |

Precision/runtime not stated (PyTorch implied). License (LICENSE.md, read from raw.githubusercontent.com): "Academic Software License: © 2026 UCLA Mobility Lab ... Academic or nonprofit researchers are permitted to use this Software..." — **non-commercial**; Parcel cannot ship these weights.

Reading for Parcel: 4.8 s for a 1B VLM is *not* the cost of 1024 visual tokens — it is dominated by generating reasoning text (the same model's prefill on an Orin NX would be well under a second; see S7, S15). Output tokens, not input tokens, set the plan-lane rate.

### S6 — Qwen-RobotNav technical report (arXiv 2606.18112v3, CC BY 4.0)
https://arxiv.org/html/2606.18112v3 ; repo https://github.com/QwenLM/Qwen-RobotNav ; alphaXiv https://www.alphaxiv.org/abs/2606.18112

Qwen3-VL backbone + "lightweight 4-layer MLP action head", sizes 2B / 4B / 8B ("favourable scaling from 2B to 8B"). Output: "K=8 waypoints each encode a 2D position (xk,yk) and heading θk". Deployment: "edge inference runs on Jetson Thor with FP8 quantization and TensorRT acceleration"; on-device "204 ms (4.9 Hz)" vs remote server "196 ms (5.1 Hz)"; on-device "provided much more consistent latency". Figure 11 caption identifies the deployed model as **Qwen-RobotNav-4B on Unitree Go2**. Frames / visual-token budget used on the robot are not stated. Weights: "There is currently no plan to release the model weights for Qwen-RobotManip or Qwen-RobotNav."

**Derived** Orin scaling: Thor/Orin on VLM ≈ 1.65× (S2) and Thor has FP8 while Orin tops out at INT4/INT8 → a 4B navigator with an MLP head would land around 2–3 Hz on AGX Orin if ported to TensorRT Edge-LLM INT4 — plausible, unmeasured.

### S7 — "Rethinking Small VLM Quantization" (arXiv 2607.08029, ETRI, ICML 2026 workshop, CC BY 4.0)
https://arxiv.org/pdf/2607.08029

Jetson Orin NX and AGX Orin, JetPack 6.2.1, HF transformers + BitsAndBytes; five sVLMs (Qwen3-VL-2B 2.44B, DeepSeek-VL2-Tiny 3.37B, PaliGemma2-3B 3.6B, LLaVA-OV-0.5B 1.03B, Kosmos-2.5). Orin Nano "consistently encountered out-of-memory".

Time per output token (TPOT, ms), FP16 baseline (cfg0) → LLM INT4 via BitsAndBytes (cfg1):

| Model | NX cfg0 | NX cfg1 | AGX cfg0 | AGX cfg1 |
|---|---|---|---|---|
| Qwen3-VL-2B | 111.1 | 173.1 (+55.8 %) | **136.2** | 212.4 (+55.9 %) |
| PaliGemma2-3B | 166.0 | 183.3 | 137.9 | 182.1 (+32.0 %) |
| LLaVA-OV-0.5B | 96.5 | 143.9 | **90.5** | 141.4 (+56.3 %) |

VRAM: Qwen3-VL 4.06 → 2.13 GB; PaliGemma2 5.85 → 3.18 GB. Vision-encoder latency, FP16 (ms) NX / AGX: PaliGemma2 (SigLIP-So400m) 311.9 / **98.5**; Qwen3-VL (SigLIP-2) 394.6 / **160.6**; LLaVA-OV 719.8 / 381.2; DeepSeek-VL2 1423.3 / 903.5; Kosmos-2.5 11029 / 2904. INT8 vision (cfg4) makes encoders 2.43–4.66× *slower* (SigLIP-So400m) and 1.73–2.51× (SigLIP-2). Energy per query, Qwen3-VL on AGX: 4.90 J FP16 → 7.12 J INT4. Verbatim conclusion: "LLM INT4 implemented via BitsAndBytes should be viewed purely as a VRAM-saving approach, rather than as a technique for reducing latency." Also: "the Jetson Orin GPU ... computation falls back to INT8 since its Ampere architecture does not support INT4" (S8 says the same).

Reading: these are *unoptimised* (eager PyTorch) numbers — 7 tok/s for a 2B model on AGX Orin — and they matter because that is what a research checkpoint does out of the box. The 4× gap to vLLM/MLC (S4, S15) is the port cost.

### S8 — EdgeReasoning (arXiv 2511.01866, Nov 2025, CC BY 4.0) — AGX Orin 64 GB latency model (vLLM, FP16, MAXN)
https://arxiv.org/pdf/2511.01866

Hardware table: "2048 (5.3TFLOPs) CUDA cores, 64 (275TOPs) Tensor Cores, 2 DLA, 64GB @ 204.8GB/s"; "four configurable power modes (15W, 30W, 50W, and MAXN) ... All experiments are conducted in MAXN mode". vLLM, single batch, DeepSeek-R1-Distill 1.5B / 8B / 14B in FP16.

Decode: "The average time between tokens (TBT) for the 1.5B, 8B, and 14B models are 0.029s, 0.092s, and 0.187s" (fitted n: 0.024 / 0.10 / 0.186 s); TBT rises only 3.1 % from 1 to 4k context. → **~35–42 tok/s (1.5B), ~10 tok/s (8B), ~5.4 tok/s (14B)** single-stream FP16.

Prefill fit L(I) = a·I² + b·I + c with I padded to 128: 1.5B a=1.56e-7, b=2.31e-6, c=0.046; 8B a=6.65e-7, b=2.90e-4, c=0.104; 14B a=1.23e-6, b=5.3e-4, c=0.189 (MAPE ≤ 13 % prefill, < 1 % decode). **Derived** prefill latencies: I=256 → 1.5B 0.06 s, 8B 0.22 s; I=1024 → 1.5B 0.21 s, 8B 1.10 s, 14B 2.02 s; I=1600 (8 frames × 196 + text, padded) → **1.5B 0.45 s, 8B 2.27 s, 14B 4.19 s**. Equivalent prefill rates at 1.6k tokens: ~3.5k tok/s (1.5B), ~700 tok/s (8B).

Table II (150 MMLU-Redux questions, includes prefill): gemma-7B 7.2 TPS, llama3.1-8B 6.6, qwen2.5-7B 7.2, DSR1-1.5B 9.3, DSR1-8B 7.8, DSR1-14B 4.7. "decode phase consuming 192–569× longer than prefill phase" for reasoning models — again: output length is the budget.

### S9 — Quantization-Aware Imitation Learning (arXiv 2412.01034, Dec 2024) — OpenVLA-7B on AGX Orin 64 GB
https://arxiv.org/html/2412.01034v1

OpenVLA (7.6B: Llama2-7B + DINOv2 + SigLIP), one image, 7 action tokens, Jetson AGX Orin 64 GB:

| Weights | Memory | Latency | Speed-up | Energy saving |
|---|---|---|---|---|
| BF16 | 15.2 GB | 955.2 ms | 1.0× | 1.0× |
| INT8 | 7.9 GB | 573.6 ms | 1.6× | 1.7× |
| INT4 | 4.0 GB | **374.7 ms** | 2.5× | 2.5× |

→ a 7B VLM with a single 256-token image and a 7-token output is a **2.7 Hz** step at INT4, 1.0 Hz at BF16, on AGX Orin.

### S10 — LiteVLA-Edge (arXiv 2603.03380, Mar 2026) — smallest VLM measured on AGX Orin 64 GB
https://arxiv.org/html/2603.03380v1
SmolVLM-256M, "4-bit (Q4_K_M) GGUF quantization", llama.cpp CUDA, "NVIDIA Jetson AGX Orin (64GB)", "maximum of 12 tokens" output, RGB frames fed sequentially, 30 runs after warm-up: "mean end-to-end latency of 150.5 ms" (6.6 Hz). Power mode and image resolution not stated.

### S11 — vla.cpp (arXiv 2606.08094, Jun 2026, TU Darmstadt) — VLAs across RTX 3060 / AGX Orin / Orin Nano
https://arxiv.org/pdf/2606.08094

Table 3, per-step latency (ms), "wall-clock per environment step (amortized over chunk replay)":

| Model | RTX 3060 | **AGX Orin** | Orin Nano 8 GB |
|---|---|---|---|
| SmolVLA | 28.16 | 65.41 | 141.81 |
| BitVLA | 37.85 | 101.11 | 355.65 |
| Evo-1 | 63.60 | 131.01 | 458.84 |
| GR00T-N1.5 | 14.17 | 28.78 | 84.76† |
| π0 | 9.74 | 27.90 | 39.10† |
| GR00T-N1.6 | 10.29 | 26.70 | does not fit |
| GR00T-N1.7 | 10.26 | 26.84 | does not fit |

Roofline: "Jetson AGX Orin (sm 87; 21.3 TFLOP/s, 204.8 GB/s)", ridge 104 FLOP/byte; "the prefix computation is firmly compute-bound ... The low-token action expert that consumes the prefix is, by contrast, memory-bound". BitVLA W2A8 on IMMA tensor cores: 406.6 → 101.11 ms on AGX Orin (4.0×) — "The choice of arithmetic unit, not weight format, then determines latency." On the 8 GB Nano "footprint, not latency, determines what can be deployed". Also cites LiteVLA's "approximately 6.6 Hz on the Jetson AGX Orin".

Reading: the 27–28 ms "per step" for π0 / GR00T is amortised over an action chunk (a 50-step chunk at 50 Hz is one ~1 s forward); it is a 10 Hz-compatible *effective* rate, not a 10 Hz forward pass.

### S12 — RhinoVLA technical report (arXiv 2606.07383, Jun 2026) — Orin roofline for VLAs
https://arxiv.org/html/2606.07383v1
Qwen3-VL 2.13B backbone; Orin assumptions "theoretical FP16 throughput of approximately 43 TFLOPS", "memory bandwidth of around 203 GB/s", "ideal compute utilization of 40%, corresponding to an effective FP16 throughput of approximately 17.2 TFLOPS". Measured π0.5 on Orin: total ~858.3 ms = vision encoder 69.3 + VLM backbone (PaliGemma-class 3B) 528.0 + action expert 257.0 ms. "π0.5 and RDT already approach or exceed Orin's effective roofline limit at a target frequency of 5 Hz, and significantly exceed the hardware capability at 10 Hz." RhinoVLA itself: INT8 weights / FP16 activations, 11.69 Hz on a different SoC (Huixi R1).

### S13 — REIS / "On-Device Robotic Planning" (arXiv 2605.31460, May 2026, Yonsei + ETRI) — Orin NX 16 GB, VLM with zero output tokens
https://arxiv.org/pdf/2605.31460
Jetson Orin NX (16 GB). Scene-change gate EMA-HSVS: "average computational overhead of only 181.42 ms (± 24.3 ms) per frame". Affordance routing by KV-cache steering (3B-class VLM, 0 output tokens): **406.21 ms**, accuracy 0.913; Base+Direct 327.56 ms; CAG/RAG ~1020 ms; "Base + Reasoning incurs an impractical edge latency of 43.59 s". Failure-detection latency 0.933 ± 0.874 s. Models named: Qwen3-VL, DeepThink-3B, Llama-3.2-3B-Instruct.

### S14 — Moondream on Jetson
https://moondream.ai/ ; https://moondream.ai/blog/photon-1-2-0-update (2026-05-01) ; https://moondream.ai/models
Homepage benchmark strip (ChartQA test split, prefix caching): **Jetson AGX Orin, Moondream 2: P50 514 ms, peak 4.6 req/s**; Jetson AGX Thor, Moondream 3.1 on Photon: P50 246 ms, 12.6 req/s. Photon 1.2.0 (JetPack 7 Thor): Moondream 2 ~152 ms single-request / 14.53 req/s at batch 64; Moondream 3 ~147 ms / 12.05 req/s. Orin supported via "CUDA 12 for Jetson Orin" wheel. License: "All Moondream models are available on HuggingFace with permissive licensing. Free for personal, research, and most commercial use."

### S15 — AVerMedia Orin NX SUPER-mode VLM benchmark (2025-10-09)
https://developer.avermedia.com/blog/benchmark-super-mode-of-nvidia-jetson-orin-nx/
Orin NX (D133 = MAXN, D133S = MAXN SUPER; module size not stated), MMStar images, averages of TTFT and TPOT in seconds:

| Model | Framework | TTFT D133 → D133S (s) | TPOT D133 → D133S (s) |
|---|---|---|---|
| Qwen2.5-VL-3B-Instruct | vLLM | 0.69 → 0.599 | 0.084 → 0.080 |
| Qwen2.5-VL-3B-Instruct-AWQ | vLLM | 0.544 → 0.471 | **0.034 → 0.032** |
| Ovis2-4B-GPTQ-Int4 | vLLM | 1.68 → 1.367 | 0.034 → 0.033 |
| Phi-3.5-vision-instruct | vLLM | 1.33 → 1.075 | 0.111 → 0.104 |
| SmolVLM2-2.2B-Instruct | vLLM | 2.202 → 1.709 | 0.056 → 0.052 |
| qwen2.5vl:3b | Ollama | 2.119 → 1.82 | 0.062 → 0.051 |
| qwen2.5vl:7b | Ollama | 2.652 → 2.249 | 0.099 → 0.082 |
| minicpm-v:8b | Ollama | 1.98 → 1.688 | 0.082 → 0.069 |
| llava:7b | Ollama | 2.497 → 2.043 | 0.079 → 0.069 |
| llava:13b | Ollama | 4.31 → 3.578 | 0.166 → 0.158 |
| gemma3:4b | Ollama | 5.407 → 4.655 | 0.071 → 0.059 |

Reading: on an Orin NX a 3B AWQ VLM under vLLM is TTFT ≈ 0.47 s + 32 ms/token → a 16-token answer in ~1.0 s (≈1 Hz); Ollama (llama.cpp) TTFT is 3–4× worse for the same model, and its 7B is TTFT 2.25 s + 82 ms/token. AGX Orin is ~1.5–2× an NX on the same stack (S7's encoder ratios: 1.9–3.2×; S17 llama.cpp: 2.6–3.2×).

### S16 — llama.cpp discussion #17732: Qwen3-VL-4B Q4_K_M on AGX Orin
https://github.com/ggml-org/llama.cpp/discussions/17732
llama.cpp build 7193, CUDA, AGX Orin (sm 8.7): image encoding **4,079 ms** for a 1,472×1,472 warm-up image (2,040 tokens), image decoding 1,181 ms, "prompt eval 2.78 ms/token (359.12 tokens/second)", "generation 30.58 ms/token (32.71 tokens/second)". Unanswered thread. Reading: with an unoptimised mmproj, the *vision encoder* is 3–4× the LLM prefill — confirms S7's warning; at 359 tok/s prefill an 8×196-token memory is 4.4 s under llama.cpp on Orin.

### S17 — llama.cpp Q4_K_M text-LLM numbers on AGX Orin 64 GB (two independent blogs)
- multimodalflow.net (2026-05-29, "All numbers ... from live hardware testing on a Jetson AGX Orin 64GB Developer Kit", JetPack 6.1, CUDA 12.6, full offload, flash attention): Llama 3.1 8B 28 t/s, TTFT 1.2 s, 5.8 GB; Qwen2.5 7B 31 t/s, 1.0 s, 5.2 GB; Phi-3 Mini 3.8B 47 t/s, 0.7 s, 2.8 GB. https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/
- ProventusNova (JetPack 6.2, jetson_clocks, context 2048): AGX Orin 64GB Llama 3.1 8B Q4_K_M **prompt 48 tok/s, generation 52 tok/s**; Orin NX 16GB 15 / 18; Orin NX 8GB 10 / 11; Orin NX 16GB Qwen 2.5 7B 18 / 20; Orin Nano Phi-3 mini 22 / 28. https://proventusnova.com/blog/llm-inference-jetson-orin-llamacpp-ollama
Reading: llama.cpp prompt-processing on Orin is pathological (48 tok/s for 8B vs ~700 tok/s under vLLM FP16 from S8) — never use llama.cpp for a many-token vision prefill on Orin.

### S20 — Jetson AI Lab: OpenPI π0.5 on Thor (scale point)
https://www.jetson-ai-lab.com/tutorials/openpi_on_thor/
π0.5, pi05_libero, action horizon 10, Thor: PyTorch BF16 ~132 ms total (~128 model); TensorRT FP8 ~54 ms; FP8 + NVFP4 ~49 ms ("~2.7x"). Compare S12's 858 ms for π0.5 on Orin: Thor+TRT is ~16× Orin+PyTorch for the same policy — most of that is the runtime, not the silicon.

### S21 — NVIDIA forum: Qwen3-VL-2B on Orin Nano Super, 2 QPS target (Feb 2026)
https://forums.developer.nvidia.com/t/performance-inquiry-optimizing-qwen3-vl-2b-inference-for-2-qps-target-on-orin-nano-super/359639
1280×720 image + 100–200 text tokens, FP16/BF16, MAXN_SUPER: transformers 4.57.1 **0.89 QPS**, llama.cpp b7641 **0.53 QPS**; vLLM OOM at launch on 8 GB. NVIDIA: "Qwen3-VL is a relatively new model so you will need the backend that has already added the support for it"; "more options for Thor + JetPack 7".

### Cloud-in-the-loop Go-class systems (for contrast; VLM not on the Orin)
- Decision-Driven Semantic Object Exploration (arXiv 2509.20739v2, Go1 + "Jetson AGX Orin onboard the robot serves as the edge computing unit, responsible for planning and control"): Qwen2.5-VL-7B "via their official cloud APIs" ~2.5 s per viewpoint; GroundingDINO ~1.2 s on an RTX 4090 workstation; trajectory tracking 12 Hz; motion policy 50 Hz; event-triggered ("invoked only when the robot reaches a stable viewpoint"). https://arxiv.org/html/2509.20739
- Slow Brain, Fast Planner (arXiv 2606.20458, Jun 2026): cloud Gemini over 4G, "round-trip latency typically 1.5–3.0 s", planner 5 Hz (Δt_plan 0.2 s), control 0.1 s, 4 s horizon, delivery robot. https://arxiv.org/html/2606.20458
- EdgeReasoning and TIC-VLA are the only Orin measurements with both a language lane and a control lane; nobody publishes a VLM + control-loop *contention* measurement on one Orin.

### Excluded
- iotdigitaltwinplm.com "Edge LLM Benchmark Q2 2026" claims measured AGX Orin numbers (Llama 3.2 3B INT4 ~85 tok/s, Gemma 2 2B FP16 ~120 tok/s, 128-token prefill p50 ~50 ms) but cites TensorRT-LLM 0.13 / vLLM 0.6 / llama.cpp b3829 / Ollama 0.1.40 as its April-2026 stack — 2024-vintage versions — so I do not trust it as measured data.
- NVILA paper (arXiv 2412.04468): its Jetson numbers are not in the HTML version I could read; the robot navigation result is NVILA-8B on an RTX 4090 at 1 Hz.
- "Cloud to Edge" (arXiv 2604.24785, CC BY 4.0) is Orin Nano Super only (Ollama 0.5B–3B: 6–13 tok/s; TTFT 1.4–3.2 ms for very short prompts).

---

## 4. Sizing table — AGX Orin 64 GB (MAXN), best published runtime per class

Workloads: **W1** = 1 image (~256 visual tokens) + ≤ 12 output tokens (act tokens / a waypoint tuple). **W2** = 2 images (~512 tokens) + ~32-token structured plan. **W3** = 8 frames × 196 = 1,568 visual tokens + ~32–64-token plan (StreamVLN-style memory, re-prefilled each step). "Measured" = a number read above; "derived" = arithmetic from S8's fits plus measured decode rates; the 8-frame prefill assumes vision tokens are *cached* per frame (encoding 8 frames fresh costs another 0.8–1.3 s at 100–160 ms/frame, S7).

| Model class (examples) | Precision / runtime | W1 rate | W2 rate | W3 rate | Evidence |
|---|---|---|---|---|---|
| 0.25–0.5B (SmolVLM-256M, LLaVA-OV-0.5B, InternVL3-1B's 0.5B LM) | Q4 llama.cpp / FP16 vLLM | **≥ 5 Hz** (150 ms measured, S10) | ~2 Hz (derived: prefill ~0.15 s + 32 tok at 40–100 tok/s) | **~1–2 Hz** (derived: prefill ≤ 0.45 s + decode 0.3–0.8 s) | S10, S8, S4 SLM rates |
| 1–2B (InternVL3-1B/2B, Moondream-2 1.9B, Qwen3-VL-2B, SmolVLM2-2.2B) | INT4-AWQ vLLM / TRT Edge-LLM | **~2 Hz** (Moondream-2 514 ms measured on Orin; 3B-AWQ on NX: 0.47 s TTFT + 32 ms/tok) | ~1 Hz (derived: ~0.3 s prefill + 32 × 25–30 ms) | **~0.7–1 Hz** (derived: 0.45 s prefill + 0.8–1 s decode) | S14, S15, S8 |
| 3–4B (VILA1.5-3B, Qwen2.5-VL-3B, Qwen3-VL-4B, PaliGemma2-3B, π0.5 backbone) | INT4 MLC / TRT; FP16 vLLM | **2–7 Hz** with tiny outputs (VILA1.5-3B 7.57 FPS streaming; π0.5 858 ms with a 257 ms action expert) | ~0.8–1 Hz (derived: ~0.5 s prefill + 32 × 30 ms) | **~0.5 Hz** (derived: ~1.0–1.2 s prefill FP16 + ~1 s decode; 4.4 s prefill if llama.cpp) | S4, S12, S16, S8 |
| 7–8B (Qwen2.5-VL-7B, Llama-3-VILA1.5-8B, OpenVLA-7B) | INT4 (MLC/AWQ) | **1–2.7 Hz** (OpenVLA INT4 375 ms measured; VILA1.5-8B 5.05 FPS streaming; BF16 955 ms) | ~0.5–0.7 Hz (derived: ~0.6 s prefill + 32 × 25–40 ms) | **~0.2–0.3 Hz** (derived: 2.27 s prefill FP16 + 32 tok at 10–40 tok/s) | S9, S4, S8, S17 |
| 13–14B (Llava-13B, VILA1.5-13B) | INT4 MLC / FP16 vLLM | 0.85–2.85 FPS streaming | < 0.5 Hz | ~0.15 Hz (4.2 s prefill + 32 × 0.19 s) | S4, S8 |

So, on AGX Orin 64 GB:
- **≥ 2 Hz**: ≤ 2B VLMs at W1; 3–4B only with an optimised INT4 stack and ≤ 8-token outputs (VILA-class); 7B only as a W1 INT4 VLA with ≤ 7 tokens (OpenVLA 2.7 Hz).
- **≥ 1 Hz**: ≤ 2B at W2; ≤ 0.5B at W3; 3–4B at W1/W2; 7–8B at W1 (INT4 or BF16 at exactly ~1 Hz).
- **≥ 0.5 Hz**: 3–4B at W3; 7–8B at W2 (INT4); 1–2B at W3 comfortably.
- **< 0.5 Hz**: 7–8B at W3 (0.2–0.3 Hz); anything 7B+ that emits reasoning text (TIC-VLA's 1B emitting reasoning on an NX: 0.2 Hz).

Thor scale points (same workloads): Qwen-RobotNav-4B FP8+TRT 204 ms (4.9 Hz) on a Go2; π0.5 FP8 54 ms; Moondream-3 147 ms; Qwen2.5-VL-7B single-stream 45 tok/s, 3B 71.7 tok/s; VLM aggregate 1.6× Orin, VLA 2.5–2.7× Orin.
Orin NX (Go2 EDU's own computer, 25 W) scale points: TIC-VLA 1B policy 120 ms / reasoning 4.8 s; Qwen2.5-VL-3B-AWQ vLLM TTFT 0.47 s + 32 ms/tok; 3B-class KV-steered affordance check 406 ms with 0 output tokens; 8B Q4 llama.cpp 15–18 tok/s.

---

## 5. What this means for Parcel's Model A / Model B

1. **The 10 Hz act-token loop cannot host a language model on the Orin; keep it a small non-LM policy (or a chunked action head) and make the VLM an asynchronous 0.5–2 Hz writer.** Fastest measured VLM step on AGX Orin is 150 ms (SmolVLM-256M, 12 tokens) — 6.6 Hz, and that is a toy. The only 10 Hz-compatible numbers (π0 27.9 ms, GR00T-N1.6 26.7 ms) are amortised over action chunks; RhinoVLA's roofline says a π0.5-class 3B VLA "already approach[es] or exceed[s] Orin's effective roofline limit at 5 Hz". This matches TIC-VLA's 10 Hz policy + 0.5 Hz VLM split, which is the only navigator that has been run on a Go2's Orin (0.75 SR on an NX).

2. **Model A's language/plan lane on AGX Orin: ≤ 2B parameters if it consumes an 8-frame × 196-token memory at ≥ 1 Hz; ≤ 4B if it consumes ≤ 2 frames; a 7–8B backbone is a 0.5 Hz lane at best and only with a ≤ 32-token structured output.** The derived W3 numbers (1.5B: 0.45 s prefill; 8B: 2.27 s prefill at FP16; 8B decode 10 tok/s FP16 / 28–52 tok/s INT4) put an 8B StreamVLN-style loop at 0.2–0.3 Hz. InternVL3-1B/2B and Qwen3-VL-2B are the candidates that TensorRT Edge-LLM supports on Orin at INT4-AWQ.

3. **Cache vision tokens per frame; never re-encode the memory.** SigLIP-class encoders cost 98–160 ms per frame FP16 on AGX Orin (Qwen3-VL-2B 160.6 ms, PaliGemma2 98.5 ms), and an unoptimised llama.cpp mmproj took 4.1 s for one 1472² image. Encoding 8 frames fresh each step is 0.8–1.3 s before any LLM work. The design should encode each camera frame once (at the plan-lane rate or on scene change), keep 196 tokens/frame in a ring buffer, and prefill only the newest frame + text (≈ 0.05–0.2 s for ≤ 2B). Do not INT8-quantise the vision tower on Orin (2.4–4.7× slower).

4. **Output-token budget is the biggest single lever — larger than model size.** TIC-VLA's 1B took 4.8 s per reasoning step on an NX because it writes reasoning text; REIS's 3B-class affordance check with zero output tokens (KV-steering) is 406 ms on the same NX; EdgeReasoning: decode is 192–569× the prefill time for reasoning-style outputs. Model A's plan lane should emit a fixed, short structured plan (waypoints / subgoal id / act-token prior; ≤ 16–32 tokens) or a latent/KV handoff as TIC-VLA does — never chain-of-thought on-device. That also makes the lane's period deterministic, which the 10 Hz loop needs.

5. **Runtime is a 3–7× multiplier; budget a TensorRT Edge-LLM (or vLLM INT4-AWQ) port as a first-class deliverable, and measure at MAXN + jetson_clocks.** Eager transformers: Qwen3-VL-2B TPOT 136 ms on AGX Orin; vLLM AWQ: 32 ms/token for a 3B on an NX; MLC INT4: 40–47 tok/s for 7–8B on AGX Orin; llama.cpp prompt-processing on Orin is 48 tok/s for 8B (unusable for 1.5k-token prefills). BitsAndBytes INT4 *slows* Orin (+56 % TPOT) because Ampere has no INT4 tensor path — use AWQ/W4A16 kernels (vLLM w4a16, MLC, TRT Edge-LLM INT4 AWQ), not bnb. A user's misconfigured vLLM ran 7× slower than NVIDIA's reproduction of the same model (30 vs 225 tok/s). Every Parcel latency claim should state runtime, precision and nvpmodel.

6. **Model B on the Orin shares the same 204.8 GB/s; keep the on-device part of Model B small and treat narration as a hosted job.** A 7–8B text model decodes at ~10 tok/s FP16 / ~40 tok/s INT4 *on an idle Orin*; a 30-token narration is 0.75–3 s and would halve Model A's lane while it runs (no co-scheduling measurement exists — Parcel should produce one). The local Model B should be a ≤ 3B INT4 model (SLM class: 75–110 tok/s on AGX Orin per Jetson AI Lab) or a steering classifier, emitting receipts for the hosted Realtime voice to narrate; local narration is the Starlink-dropout fallback only.

7. **Memory is not the constraint; bandwidth and utilisation are.** 64 GB holds Model A (≤ 2B INT4 ≈ 1–2 GB, or 8B BF16 16 GB), Model B, ASR/TTS and the policy simultaneously; what cannot be shared is the memory bus during decode. vla.cpp's roofline: prefix is compute-bound, the low-token action expert/decoder is memory-bound — so co-locating two decoders is where contention bites; pipeline them (Model A prefill while Model B decodes) rather than running two decodes at once.

8. **Sim-to-Orin evaluation rule.** TIC-VLA lost 10 SR points moving from a laptop GPU to an Orin NX purely from latency (0.85 → 0.75). Parcel's sim evaluations must inject the Orin-measured lane latency (W3 numbers above: ~1 s for ≤ 2B, ~2 s for 3–4B, 3–5 s for 7–8B) into the plan lane, and should train Model A under randomised 0.5–5 s lane delays as TIC-VLA does.

9. **Thor is the escape hatch, not the baseline.** Qwen-RobotNav-4B at 4.9 Hz on a Go2 is a Thor + FP8 + TensorRT result; the same model class on Orin INT4 is a ~2–3 Hz derived estimate, unmeasured. If Parcel later wants a 4B navigator at ≥ 2 Hz with real memory, that is a Thor purchase, not a software fix.

10. **Licences.** TIC-VLA code/weights are under a UCLA "Academic Software License" (non-commercial) — usable for study, not for shipping; Qwen-RobotNav weights are not released; Moondream is "free for personal, research, and most commercial use"; the measurement papers cited here are CC BY 4.0 (EdgeReasoning, Qwen-RobotNav report, small-VLM quantization) or arXiv non-exclusive.

## 6. Open gaps after this sweep
- No published single-stream TTFT/decode for Qwen2.5-VL-7B or InternVL3-2B on **AGX Orin** under vLLM/TensorRT (only c=8 aggregates and NX numbers); Parcel should measure W1–W3 for InternVL3-1B/2B and Qwen3-VL-2B/4B under TRT Edge-LLM INT4 on the AGX Orin at MAXN and at 30 W.
- No measurement of a VLM lane and a control policy contending on one Orin.
- No Orin number for an 8-frame video-token prefill with cached per-frame vision tokens (the derived 0.45 s / 2.27 s figures are text-token fits).
