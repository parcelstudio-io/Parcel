# Full-duplex speech LLMs as the backbone of a talking + listening dog

Literature notes, 2026-08-28. Topic: open-weight and hosted full-duplex / streaming speech language models, their architectures, numbers, licenses, fine-tunability, edge evidence, and every precedent I could find for adding an **action / motion / non-speech token stream** to a speech LLM.

Method: every source below was located with WebSearch and then **read with WebFetch** (arXiv abstract or HTML, GitHub README, Hugging Face card, or vendor doc). Numbers are transcribed from what the fetched page said; where a page did not state a number I say so rather than fill from memory. Where two fetched sources disagree I flag it. Searches were exhausted at 200/200 for the session, so a few late items were fetched by direct URL only.

Parcel context (from the brief): Go2 EDU+ with Jetson AGX Orin 64 GB, camera, Mid-360 LiDAR, mic array + speaker; dev box RTX 5000 Ada 32 GB; hosted budget <= $300/mo Realtime speech + <= $100/mo text; the current dog picks from a fixed list of strict commands; owner wants a trainable full-duplex model whose movement is driven by the state of the world (learn to chuckle at a funny joke; learn to look back at the owner when lost).

---

## 0. One-page summary table

| Model | Params | Weights / license | Duplex type | Reported latency | Extra / non-speech streams | Fine-tune path | Edge evidence |
|---|---|---|---|---|---|---|---|
| Kyutai Moshi (2024) | 7B temporal + 6-layer depth; Mimi codec | CC-BY 4.0 weights; MIT/Apache code | **Native full-duplex**, 2 parallel audio streams + inner-monologue text | 160 ms theoretical, ~200 ms practical (L4) | 17 parallel token streams; text stream already hosts special tokens (`<ret>` in MoshiRAG) | `moshi-finetune` LoRA r=128, stereo WAV + timestamped JSON | None published for Jetson; needs 24 GB bf16; int8/int4 backends exist; Hibiki-1B (same arch) runs on iPhone 16 Pro |
| PersonaPlex-7B (NVIDIA, 2026) | 7B (Moshi init) | NVIDIA Open Model License + CC-BY-4.0; MIT code | Native full-duplex + text persona + voice prompt | Turn-taking 0.170 s; interruption 0.240 s (FDB) | Same as Moshi | 6 h on 8xA100 for its own SFT (batch 32, 24,576 steps) | Tested on A100 80 GB |
| moshika-rl-seamless (Kyutai, 2026) | 8B (bf16 card) | CC BY-NC 4.0 research-only | Native full-duplex, GRPO-aligned | Interrupt latency 1.377 -> 0.409 s; backchannel 0.074 -> 0.101 /s | Same | GRPO recipe published (32 H100) | none |
| Freeze-Omni (2024) | Qwen2-7B-Instruct frozen + 350M enc + 120M dec | Repo License.txt (unclear) | Chunk-level state classifier (0/1/2) on top of VAD | 745 ms avg / 1020 ms p90 statistical; ~1.2 s real | none | LLM frozen; encoder/decoder trained (110k h ASR, 3k h TTS, 60k QA) | none |
| LLaMA-Omni2 (2025) | 0.5B-14B (Qwen2.5) + Whisper-large-v3 + 0.5B TTS LM | Apache code; **academic-only** weights | Turn-based, streaming | 543-663 ms first chunk on L40 | none | 200K dialogues, 4xL40 / 4xH800 | none |
| GLM-4-Voice (2024) | 9B (GLM-4-9B) | Apache code; separate model agreement | Turn-based, streaming interleave | "as few as 20 tokens" before audio | none | 1T tokens continued pretrain | none |
| Qwen2.5-Omni (2025) | 7B (11B incl. Talker/enc) and 3B | Apache 2.0 | Turn-based, streaming (chunked in / immediate out) | not on card | RoboOmni adds FAST+ action tokens on this backbone | full FT (RoboOmni: 64 A100 x 10 d) | 7B Q8_0 ran on AGX Orin 64 GB in llama.cpp at ~15-16 tok/s (audio path had a bug) |
| Qwen3-Omni (2025) | Thinker 30B-A3B + Talker 3B-A0.3B + AuT 650M | Apache 2.0 | Turn-based, streaming | 234 ms first packet (audio, 1 conc.) | none | vLLM; 78.85 GB bf16 min | none |
| Qwen3.5-Omni (2026) | "hundreds of billions" (Plus/Flash) | paper CC BY 4.0; weights not confirmed | **Half-duplex** with semantic interruption | 235 ms (Flash) / 435 ms (Plus) audio first packet | none | n/a | none |
| MiniCPM-o 4.5 (2026) | 9B (Qwen3-8B + SigLip2 + Whisper-medium + CosyVoice2) | Apache 2.0 | **Full-duplex via time-division multiplexing** (video+audio in, text+speech out) | TTFT 0.6 s; 154 tok/s bf16 / 212 int4 | none | LLaMA-Factory / SWIFT | 19 GB bf16, 11 GB int4; iPhone/iPad demos; llama.cpp/Ollama |
| Step-Audio 2 / 2-mini (2025) | mini = 8B (Qwen2.5-7B base) | Apache 2.0 | VAD-based turn-taking | none stated | tool-call tokens; paralinguistic understanding 83.09 | GRPO recipe in paper | none |
| Fun-Audio-Chat-8B (2025) | 8B dense (MoE 30B-A3B not released) | Apache 2.0 | Duplex variant exists (weights not released) | none stated | none | 4x80 GB train; 24 GB infer | none |
| SALMONN-omni (2025) | Llama-3-8B + Mamba encoder + CosyVoice2-0.5B | code at bytedance/SALMONN | Full-duplex via `<think>`/`<shift>` state tokens | 320 ms | state tokens | DPO recipe | none |
| OmniFlatten (2024) | Qwen2-0.5B | no weights | Full-duplex by stream flattening | 193 ms assistant response | none | 2,000 h synthetic duplex from 390K dialogues | none |
| Mini-Omni2 (2024) | Qwen2-0.5B + CLIP + Whisper-small | code/data promised | Command-based interrupt (`irq` token) | none stated | irq / n-irq tokens | 8xA100 | none |
| Sesame CSM-1B (2025) | 1B backbone + 100M decoder | Apache 2.0 | **Not duplex**; audio generator, cannot emit text | none stated | none | not documented | CUDA GPU |
| DuplexSLA (2026) | ~7-8B (Step-Audio-2-mini init) | MIT code; **weights "coming soon"** | Native full-duplex + **action channel** (<=10 text tokens / 160 ms chunk) | Response delay 0.27 s; interrupt 0.40 s; tool call 0.64 s | **Yes: action channel** (control labels, plans, JSON tool calls) | 500k h CPT + 50k h post-train | none |
| RoboEgo / FLM-Ego (2025) | 7B | not released | Native full-duplex, **parallel streams incl. action tokens** | 80 ms theoretical duplex latency | **Yes: action token stream**; deployed on LEJU Kuavo humanoid | not released | none |
| RoboOmni (2025) | Qwen2.5-Omni 3B/7B + FAST+ action tokens | CC BY-NC-ND paper; HF collection fnlp/roboomni | Turn-based; speech + action outputs | 0.49x cascade latency on RTX 4090 | **Yes: FAST+ 7-DoF action tokens** | 64 A100 x 10 days | none |
| OpenAI gpt-realtime / 2.1 (hosted) | n/a | hosted | Server/semantic VAD + barge-in truncation | not published | none (function calls only) | not trainable | n/a; $32/$64 per M audio tokens |
| Gemini 3.1 Flash Live / 2.5 native audio (hosted) | n/a | hosted | Auto/manual VAD; "generation is canceled and discarded" on interrupt; proactive audio; affective dialog | not published | none | not trainable | $0.005/min audio in, $0.018/min audio out (3.1 Flash Live) |

---

## 1. Kyutai Moshi family

### 1.1 Moshi: a speech-text foundation model for real-time dialogue
- arXiv 2410.00037 (HTML v2 fetched): https://arxiv.org/html/2410.00037v2
- Repo (fetched): https://github.com/kyutai-labs/moshi

What it says (numbers):
- Temporal Transformer (Helium): **7B**, 32 layers, d=4096, 32 heads, 4,096-token context. Depth Transformer: 6 layers, d=1024, 16 heads.
- Mimi codec: **12.5 frames/s** at 24 kHz, Q=8 codebooks of 2,048 entries, **1.1 kbps**, causal, 80 ms initial frame; 8-layer Transformers before and after quantization.
- Joint sequence is **K = 2Q+1 = 17 parallel streams**: (1) Moshi's aligned text tokens, (2) Moshi semantic token, (3-9) seven delayed acoustic streams, (10) user semantic, (11-17) user acoustic.
- "Moshi can speak and listen at all time, and do both at once if needed" — no explicit turn boundaries; overlap and interruption are just data.
- Inner monologue: time-aligned text tokens predicted as a prefix to the audio tokens ("text -> semantic audio -> acoustic audio").
- Acoustic delay tau of 1-2 steps between semantic and acoustic tokens "greatly improves the quality".
- Latency: **160 ms theoretical, 200 ms practical**; README: "160ms theoretical (80ms frame size + 80ms acoustic delay), practical ~200ms on L4 GPU".
- Data: 2.1T text tokens; **7M hours unsupervised audio**; Fisher 2,000 h; 170 h supervised multi-stream; >20k h synthetic instruct speech. Trained on H100s with FSDP.
- Repo: weights **CC-BY 4.0**; code MIT (Python) / Apache 2.0 (Rust). Variants moshika (F) / moshiko (M). PyTorch bf16/int8; MLX int4/int8/bf16; Rust/Candle int8/bf16. "GPU with 24GB+ VRAM" for PyTorch. **No Jetson/embedded support mentioned.**

Assessment: still the canonical open native-duplex architecture; every 2026 Kyutai/NVIDIA duplex release (PersonaPlex, MoshiRAG, moshika-rl-seamless, Hibiki) is a Moshi fine-tune. The 17-stream design is exactly the shape we need: adding an 18th "action" stream is architecturally the same operation Kyutai used for the second speaker and for MoshiVis's vision gating.

### 1.2 moshi-finetune (the LoRA recipe)
- https://github.com/kyutai-labs/moshi-finetune (fetched)
- LoRA recommended **rank 128** (cap <=128), adapters saved separately; full FT also supported.
- Data: **stereo WAV, left channel = Moshi, right channel = user**, plus a `.jsonl` of `{"path":..., "duration":...}` and per-file `.json` transcripts with timestamps (`annotate.py` generates them).
- Memory on H100 with rank 128, batch 16, 100 s clips: **~39.6 GB peak single GPU**, ~23.7 GB/GPU on 8 GPUs; ~12k tok/s single GPU. Defaults: batch 16, 2,000 steps, lr 2e-6.
- Apache 2.0.

Assessment: on the RTX 5000 Ada 32 GB we must cut batch to ~4-8 and/or duration to ~40-60 s; the README warns that shrinking these may degrade inference quality. The data format (two-channel conversation + timestamped transcript) is what our simulator must emit, and the transcript JSON is where a synthetic `[laugh]` / `<act:look_back>` token stream would be injected.

### 1.3 Hibiki (same architecture at 1B/2B, on-device)
- Paper: https://arxiv.org/abs/2502.03382 (fetched; CC BY-NC-SA paper) ; Repo: https://github.com/kyutai-labs/hibiki (fetched)
- **Hibiki 2B** (16 RVQ/stream) and **Hibiki 1B** (8 RVQ/stream, "ideal for on device inference"); MLX-Swift iOS build "tested on iPhone 16 Pro"; 12.5 Hz constant frame rate; weights CC-BY 4.0.
- Kyutai papers page lists Hibiki-Zero (arXiv 2602.11072, ICML 2026): simultaneous S2ST with sentence-level data + RL, no word alignments.

Assessment: this is the only concrete evidence that the Moshi multistream architecture runs on a phone-class SoC. There is no small (1-2B) *dialogue* Moshi release, but Hibiki-1B shows the codec + multistream decoder budget fits a mobile NPU; a 1-2B Moshi-style dog model is credible on Orin.

### 1.4 Delayed Streams Modeling (DSM) STT/TTS and Unmute (cascade alternative)
- DSM paper HTML: https://arxiv.org/html/2509.08753v1 (fetched). Unmute repo: https://github.com/kyutai-labs/unmute (fetched).
- DSM-ASR: **2.6B** backbone (also **300M**, 350M with Mimi encoder); default delay 2.5 s, conditionable in [0.25, 4] s; short-form WER 6.4%, long-form 7.9%; latency precision ~300 ms around the target delay; pretrain on 2.5M h public audio, ASR finetune 24k h. DSM-TTS: **1B** backbone (1.8B with RQ sampler), delay 1.28 s (16 steps at 12.5 Hz). CC BY-NC-SA 4.0.
- Unmute: STT -> any OpenAI-compatible LLM -> TTS; TTS latency "~750 ms (single GPU) to ~450 ms" with separate GPUs; VRAM LLM 6.1 GB (Gemma 3 1B) + STT 2.5 GB + TTS 5.3 GB; min 16 GB GPU; MIT.

Assessment: the cascade floor is ~450-750 ms TTS latency plus LLM TTFT, and it cannot speak-while-listening. Useful as a fallback voice for the dog and as the transcription tool for building fine-tuning data (moshi-finetune's `annotate.py`).

### 1.5 MoshiVis (adding a modality with adapters)
- https://arxiv.org/abs/2503.15633 (fetched; CVPR 2026). Augments Moshi with visual inputs via "lightweight adaptation modules", one-stage parameter-efficient FT on a mix of image-text and image-speech samples, with a **dynamic gating mechanism** to switch between visual inputs and unrelated conversation. Adapter parameter counts were not on the abstract page.

Assessment: precedent that Moshi accepts a new input modality through gated adapters without retraining the backbone. For Parcel, camera/LiDAR "state of the world" could enter the same way (a gated cross-attention side-stream) rather than through text.

### 1.6 MoshiRAG (adding a special token to the text stream)
- https://arxiv.org/html/2604.12928v2 (fetched; ICML 2026); repo https://github.com/kyutai-labs/moshi-rag (fetched).
- `<ret>` token is inserted **into Moshi's text (inner-monologue) stream**; predicting it triggers asynchronous retrieval while speech continues. Data: ~1.9M synthetic conversations, ~1.9B tokens, **~47,770 h synthetic speech**; retrieval budget max 2 s; HaluEval accuracy 10.5% (vanilla Moshi) -> 36.3% (Gemma backend) -> 51.3% (GPT-4.1 backend); keyword delay 3.1 s vs 2.1 s vanilla. Weights CC-BY 4.0; 24 GB GPU.

Assessment: **the closest published precedent for "a speech LLM emits a non-speech control token mid-sentence without stopping talking."** A `<act:...>` or `<laugh>` token in the same stream is the same mechanism, and the training data was fully synthetic (LLM-written dialogues + TTS), which is exactly what we can build in simulation.

### 1.7 Aligning spoken dialogue models from user interactions (offline preference alignment)
- https://arxiv.org/abs/2506.21463 (fetched; ICML 2025). >150,000 preference pairs from raw multi-turn speech conversations, annotated with AI feedback over "both linguistic content and temporal context variations"; offline alignment of "a full-duplex autoregressive speech-to-speech model" improves factuality, safety, contextual alignment.

Assessment: shows DPO-style offline alignment works on the multistream model, and that temporal behaviour (when to speak) can be a preference axis. This is the mechanism for "learn from user history" once we log owner reactions.

### 1.8 Multi-faceted interactivity alignment (GRPO on Moshi/PersonaPlex) and moshika-rl-seamless
- Paper HTML: https://arxiv.org/html/2606.11167 (fetched). Checkpoint card: https://huggingface.co/kyutai/moshika-rl-seamless (fetched).
- GRPO, lr 2e-7 cosine, KL beta 0.01, clip 0.2, 16 completions/segment, 32 segments/epoch, 100 epochs; **32 H100s** FSDP.
- Rewards: R_pause = -1 if generated audio contains speech >1 s during a user pause; R_turn = negative response delay; R_bc = F1 of short (<=1 s) vocalizations vs ground-truth backchannel positions; R_int = negative delay after user interruption; R_llm = Qwen3-235B-A22B judge (1-3).
- Data: Fisher 2,000 h + Seamless Interaction 4,000 h (1,300 h improvised + 2,700 h naturalistic); up to 2,000 segments per axis.
- Results, Moshi + RL (FDB v1): pause TOR 0.445 -> 0.307; turn-taking latency 0.162 -> 0.160 s; backchannel 0.074 -> 0.101 /s; **interruption latency 1.377 -> 0.409 s**; GPT-4o score 3.44 -> 3.63. PersonaPlex + RL: pause TOR 0.482 -> 0.350; turn-taking 0.219 -> 0.086 s; backchannel 0.046 -> 0.112 /s; interruption 0.271 -> 0.223 s.
- Card: 8B bf16 params listed; **CC BY-NC 4.0, research-only**.

Assessment: **load-bearing.** This is a published, reproducible recipe for teaching a full-duplex model *timing behaviours* (backchannel = a short vocalization at the right moment) with rule-based rewards computed from the two audio channels. "Chuckle at a funny joke" is a backchannel-timing reward with a laughter detector instead of a VAD; the same GRPO loop applies. Note FDB v1's own paper reports Moshi pause TOR 0.985 vs Kyutai's baseline 0.445 — different evaluation subsets/settings, so compare within one harness only.

### 1.9 PersonaPlex (NVIDIA, Feb 2026)
- Paper HTML: https://arxiv.org/html/2602.06053 (fetched). HF card: https://huggingface.co/nvidia/personaplex-7b-v1 (fetched). Repo: https://github.com/NVIDIA/personaplex (fetched).
- Moshi init; "Hybrid System Prompt": role text on the agent text channel + a voice sample on the agent audio channel.
- Data: 1,840 h customer-service dialogues (105,410 conversations) + 410 h QA (39,322 conversations), transcripts from Qwen-3-32B and GPT-OSS-120B, speech from Dia and Chatterbox TTS; HF card adds Fisher (7,303 conversations). **Training: 6 h on 8xA100, batch 32, 24,576 steps.**
- FDB: smooth turn-taking latency **0.170 s**, user-interruption latency **0.240 s**, interruption TOR 0.950, turn-taking success 0.908, speaker similarity 0.650 (WavLM); DMOS 3.90 +/- 0.15.
- License: weights NVIDIA Open Model License (+ CC-BY-4.0 attribution), code MIT. Tested on A100 80 GB; CPU offload option.

Assessment: **load-bearing for "steerable by voice commands / persona".** PersonaPlex proves a Moshi fine-tune can be role-conditioned by a text prompt (the dog's persona + current world-state summary can be injected the same way) and voice-conditioned by audio. The 6-GPU-hour SFT budget is small — a 24-h run on one 32 GB card is the same order of compute if we use LoRA.

---

## 2. Other open speech-LLM backbones

### 2.1 Freeze-Omni (VITA, Nov 2024)
- https://arxiv.org/html/2411.00774 (fetched); repo https://github.com/VITA-MLLM/Freeze-Omni (fetched).
- Backbone **Qwen2-7B-Instruct, frozen**. Encoder ~350M (24 layers, 12.5 Hz out); decoder ~120M (NAR prefix + 4-layer AR Llama, d=896). Data: **110k h ASR**, ~3k h TTS, 60k multi-round text QA; 8 GPUs.
- Duplex: VAD-gated chunks; classification head after the last LLM layer predicts **state 0 (keep listening) / 1 / 2 (end of speech / interrupt)**; speech-token chunk 40.
- Latency: LLM interrupt -> first text token 478 ms avg (750 ms p90); prefill -> first speech 237 ms; **total 745 ms avg / 1,020 ms p90**; "controlled at about 1.2 seconds" in real scenarios.
- Spoken QA: WebQ 44.73, LLaMA-Q 72.0, TriviaQA 53.88. License unclear (License.txt; Qwen2 terms).

Assessment: shows the "frozen text LLM + state classifier" pattern. Not native duplex (cannot vocalize while listening); latency 4-5x Moshi. Its value for Parcel is the idea of a tiny *state head* on top of a frozen brain — cheap to train, deterministic to arbitrate.

### 2.2 LLaMA-Omni2 (ICT/CAS, ACL 2025)
- https://arxiv.org/html/2505.02625 (fetched); repo https://github.com/ictnlp/LLaMA-Omni2 (fetched).
- Qwen2.5-Instruct 0.5B/1.5B/3B/7B/14B (+32B bilingual) + Whisper-large-v3 + 0.5B AR TTS LM + CosyVoice2 flow matching; read/write R=3, W=10.
- 200K multi-turn dialogues (InstructS2S-200K, synthesized with fish-speech-1.5 and CosyVoice2-0.5B). First-chunk latency on one L40: **0.5B 542.71 ms, 7B 582.91 ms, 14B 663.32 ms**. LLaMA-Q S2S 60.7%. Trained on 4xL40 (<=7B) / 4xH800 (14B).
- **Turn-based, not duplex.** Code Apache-2.0; **model academic-only**.

Assessment: not a duplex candidate and not commercially usable; the useful fact is that 200K synthetic dialogues on 4 mid-range GPUs suffices to add speech I/O to a small text LLM — a scale we can afford.

### 2.3 GLM-4-Voice (THUDM, Dec 2024)
- https://arxiv.org/abs/2412.02612 (fetched); repo https://github.com/THUDM/GLM-4-Voice (fetched).
- GLM-4-9B continued pretrain to **1T tokens**; **12.5 Hz single-codebook tokenizer at 175 bps** (VQ bottleneck in an ASR encoder); flow-matching decoder; "as few as 20 tokens" before speech starts; controls emotion/tone/speed/dialect by instruction. Paper CC-BY-4.0; code Apache 2.0; weights under a separate model agreement. Turn-based.
- BayLing-Duplex (2026, below) converts it to full-duplex with special tokens.

### 2.4 Qwen2.5-Omni (Mar 2025), Qwen3-Omni (Sep 2025), Qwen3.5-Omni (Apr 2026)
- Qwen2.5-Omni-7B card: https://huggingface.co/Qwen/Qwen2.5-Omni-7B (fetched): "11B params" total, **Apache-2.0**, bf16 memory 31.11 GB (15 s video) / 41.85 / 60.19 GB (60 s); **3B variant 18.38 GB**; "fully real-time interactions, supporting chunked input and immediate output"; 22 quantized community variants (llama.cpp, Ollama...).
- Qwen3-Omni HTML: https://arxiv.org/html/2509.17765 (fetched); repo https://github.com/QwenLM/Qwen3-Omni (fetched). Thinker **30B-A3B**, Talker **3B-A0.3B**, MTP 80M, Code2Wav 200M, AuT audio encoder 650M trained on **20M h**; audio tokens 12.5 Hz; first-packet **234 ms audio / 547 ms video** (Thinker TTFT 88 ms, Talker TTFT 57 ms, MTP 14 ms/token, codec 3 ms/code); RTF < 1; 2T-token general stage; Apache 2.0; min **78.85 GB bf16** for the Instruct model. Described as turn-based; no interruption/non-verbal statements.
- Qwen3.5-Omni HTML: https://arxiv.org/html/2604.15804 (fetched). "Hundreds of billions" params, Plus/Flash; **half-duplex** with "semantic interruption through native turn-taking intent recognition"; first packet **Flash 235 ms / Plus 435 ms** audio (426/651 ms video), degrading to 955/1,980 ms at 8 concurrent; ARIA adaptive rate interleave alignment; RVQ Talker at **6.25 Hz**; >100M h audio-visual; 4T-token pretrain. Weights not confirmed as released.

Assessment: Qwen2.5-Omni-3B/7B is the strongest **Apache-2.0 omni (vision+audio) backbone that fits Orin memory** and it is the backbone RoboOmni used to emit action tokens. It is turn-based, so it would need OmniFlatten/Fun-Audio-Chat-style duplex post-training. Qwen3-Omni is too large for Orin (78.85 GB bf16 minimum); Qwen3.5-Omni is API-scale.

### 2.5 MiniCPM-o 4.5 (OpenBMB, 2026)
- Repo: https://github.com/OpenBMB/MiniCPM-o (fetched); card: https://huggingface.co/openbmb/MiniCPM-o-4_5 (fetched).
- **9B total** = SigLip2 + Whisper-medium + CosyVoice2 + **Qwen3-8B**. "Full-duplex multimodal live streaming": video+audio input streams and text+speech output streams "do not block each other", implemented by **time-division multiplexing (TDM)** — parallel streams are divided into sequential info groups within periodic ms-scale time slices.
- OpenCompass 77.6; speech CER 0.86% zh / WER 2.38% en; **TTFT 0.6 s; 154.3 tok/s bf16, 212.3 tok/s int4**; GPU memory **19 GB bf16 / 11 GB int4 / 10 GB GGUF**; vLLM, SGLang, llama.cpp, Ollama; iPhone/iPad demos; Mac M3/M4 16 GB via llama.cpp-omni; fine-tune via **LLaMA-Factory / SWIFT**; voice cloning + emotion control via reference audio; **Apache-2.0** (card says commercial use allowed). (The card's "February 6, 2025" date looks like a 2.6-era line; not relied on.)

Assessment: **load-bearing as the "state of the world" candidate.** It is the only open model in this survey that ingests live video + audio and emits speech concurrently, fits Orin memory at int4 (11 GB), and has a mainstream fine-tuning path. Its duplex is TDM (interleaved slices) rather than Moshi's parallel streams, so behaviour timing granularity is a time-slice, and there is no published Orin benchmark.

### 2.6 Step-Audio 2 / 2-mini (StepFun, Jul 2025) and StepAudio 2.5 (May 2026)
- Paper HTML: https://arxiv.org/html/2507.16632 (fetched); repo https://github.com/stepfun-ai/Step-Audio2 (fetched); mini card https://huggingface.co/stepfun-ai/Step-Audio-2-mini (fetched); 2.5 abstract https://arxiv.org/abs/2605.23463 (fetched).
- Frozen audio encoder at 25 Hz, adaptor /2 -> 12.5 Hz; CosyVoice 2 tokenizer (6,600 audio tokens added); fixed-ratio text/audio interleave; **680B text tokens + 8M h audio, 1.356T tokens over 21 days**; RL: binary reward (60 it) -> learned preference (120 it) -> **GRPO 400 it**. MMAU 78.0 (mini 73.2); **StepEval-Audio-Paralinguistic 83.09 (mini 80.00)**; URO-Bench zh 83.32; tool-call precision 88.4%. Turn-taking via VAD; no latency numbers. **Step-Audio-2-mini = 8B, Apache 2.0** (Qwen2.5-7B base per repo).
- StepAudio 2.5: unified ASR/TTS/Realtime branches, RLHF with generative reward modelling; no sizes/latency/licence in the abstract.

Assessment: strongest open model at *understanding* paralinguistics (laughter, tone) — the "was the joke funny?" perception side — and the backbone DuplexSLA chose for its action channel. Not natively duplex.

### 2.7 Fun-Audio-Chat (Alibaba Tongyi, Dec 2025)
- Paper HTML: https://arxiv.org/html/2512.20156v1 (fetched); card https://huggingface.co/FunAudioLLM/Fun-Audio-Chat-8B (fetched).
- Dual-resolution: shared LLM at **5 Hz**, Speech Refined Head at **25 Hz**; ~50% GPU-hour reduction; bases Qwen3-30B-A3B / Qwen3-VL-8B; Core-Cocktail two-stage FT with merging.
- **Fun-Audio-Chat-Duplex**: "parallel speech-text input stream architecture", trained on duplex data "synthesized by augmenting high-quality half-duplex dialogue datasets with simulated full-duplex interaction behaviors" (OmniFlatten method); turn-taking success 100% (30B-A3B). **Only the 8B non-duplex checkpoint is released**, Apache 2.0, ~24 GB inference, 4x80 GB training.

### 2.8 2026 duplex releases: Covo-Audio, Lychee-FD, BayLing-Duplex, DuplexOmni, DuplexPO
- Covo-Audio https://arxiv.org/abs/2602.09823 (fetched): **7B** end-to-end LALM on continuous audio; variants Covo-Audio / -Chat / **-Chat-FD (full-duplex)**; "intelligence-speaker decoupling" so voice can be changed with minimal TTS data; CC BY 4.0 paper; the Awesome list marks weights released.
- Lychee-FD https://arxiv.org/abs/2607.06540 (fetched): native end-to-end full-duplex with hierarchical parameter separation to reduce acoustic/semantic gradient conflict; +7.4% Spoken QA, **+28.5% on FullDuplexBench 1.5**; size not in abstract.
- BayLing-Duplex https://arxiv.org/abs/2606.14528 (fetched): starts from **GLM-4-Voice**; "a single autoregressive LLM decides when to listen, when to speak, and when to stop, with no auxiliary turn-taking module" via special tokens; **400K full-duplex samples SFT + lightweight DPO**; 92% turn-taking / 100% interruption success (InstructS2S-Eval); speech-response score 2.17 -> 3.39 vs Moshi; CC BY-NC-ND.
- DuplexOmni https://arxiv.org/html/2606.09186v1 (fetched): XJTU/PKU/Meituan; init from **Qwen3-Omni**; time-sliced AR inference with fixed **480 ms slices**, each emitting a thinking-control signal, a semantic interpretation, and text/speech; pluggable asynchronous "thinking layer" via control tokens; response latency **0.506 s**; ~3.02M synthetic conversations (1.486M user-initiated + 1.528M system-initiated, 10K video-call), 70% zh / 30% en; FDB ToR 72.6%, Big Bench Audio 77.2%; "will release weights, data, code"; CC BY 4.0.
- DuplexPO ("Decoupling Conversational Dynamics ... through RL") https://arxiv.org/html/2607.07148 (fetched): NTU/NTU-Taiwan/HKUST/NVIDIA, Jul 2026; **Qwen2.5-7B-Instruct + 600M Parakeet streaming encoder + CosyVoice2**; GRPO with a **Factorized Conversational Dynamics Reward** (onset timing Gaussian penalty, backchannel-window reward, yield-after-barge-in penalty, regulariser); Fisher onset MAE 0.98 -> 0.69 s; backchannel yield 57.1% -> 100%; FDB v3 voiced-interrupt rate 7.33% -> 0.24%; QA preserved (WebQ 44.3 -> 44.5); 530K h continuation pretrain + 70K h QA; **64 A800 80 GB**; judge preference 76.9%. No weights statement.

Assessment: 2026 consensus is converging on (a) native duplex via special state/control tokens or parallel streams, (b) synthetic duplex data built by augmenting half-duplex dialogues with simulated overlaps, (c) **GRPO/DPO with rule-based timing rewards** to fix pause/backchannel/interrupt behaviour. Two independent groups (Kyutai; NTU/NVIDIA) report the same qualitative result.

### 2.9 Small-model duplex recipes: OmniFlatten, SALMONN-omni, Mini-Omni2, DuplexMamba
- OmniFlatten https://arxiv.org/html/2410.17799 (fetched): **Qwen2-0.5B**; CosyVoice single codebook 4,096; stages modality alignment (~100K h) -> half-duplex -> full-duplex; **390K dialogues synthesized into 2,000 h of full-duplex data** with user audio at 15-30 dB SNR; chunks = 2 text + 10 speech tokens; **193 ms assistant response**, 287 ms user turn-taking; no weights.
- SALMONN-omni https://arxiv.org/html/2505.17060 (fetched): Llama-3-8B-Instruct + 32-block Mamba encoder (25 Hz) + CosyVoice2-0.5B; codec-free; `<think>` / `<shift>` tokens for listen/speak transitions; **80 ms time block per text token**, 4 text tokens -> 480 ms speech, **320 ms latency**; ~1.81M samples; barge-in/backchannel F1 0.88 -> 0.93 after **DPO**; code at bytedance/SALMONN.
- Mini-Omni2 https://arxiv.org/html/2410.11190 (fetched): Qwen2-0.5B + CLIP ViT-B/32 + Whisper-small + SNAC (7 layers, 7x4,160 sub-heads, vocab 181,120); **`irq` / `n-irq` interrupt tokens** trained with "Stop Omni" phrases mixed into noise; 8xA100; LibriSpeech test-other WER 9.8%.
- DuplexMamba https://arxiv.org/abs/2502.11123 (fetched): Mamba speech encoder + Mamba LM, duplex decoding strategy; weights stated released (size not in abstract).

Assessment: OmniFlatten's 2,000 h synthetic-duplex-from-390K-dialogues and Mini-Omni2's `irq` token show that *duplex control tokens can be trained into a 0.5B model on 8 A100s*. That is the size class that would leave Orin headroom for locomotion.

### 2.10 Sesame CSM
- Blog https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice (fetched); repo https://github.com/SesameAILabs/csm (fetched).
- Sizes: Tiny 1B/100M, Small 3B/250M, Medium 8B/300M; ~1M h English audio; Mimi at 12.5 Hz; decoder trained on 1/16 of frames (compute amortization). Released **csm-1b, Apache 2.0**. "CSM is trained to be an audio generation model and not a general-purpose multimodal LLM. It cannot generate text." Blog: "can only model the text and speech content in a conversation — not the structure of the conversation itself"; full duplex listed as future work.

Assessment: not a duplex brain; a context-aware voice renderer. Could voice a cascaded fallback but adds nothing to the "learn what to do" problem.

---

## 3. Hosted full-duplex-ish APIs

### 3.1 OpenAI Realtime (gpt-realtime, gpt-realtime-2.1, -mini)
- Pricing https://developers.openai.com/api/docs/pricing (fetched): gpt-realtime text $4 in / $0.40 cached / $16 out; **audio $32 in / $0.40 cached / $64 out** per 1M tokens; image $5. gpt-realtime-mini audio $10 / $20. gpt-realtime-2.1 same audio price, text out $24. 2.1-mini = mini prices.
- Model pages (fetched): gpt-realtime snapshot 2025-08-28, **32k context, 4,096 max output**; gpt-realtime-2.1 **128k context, 32k max output**, function calling + prompt caching; realtime endpoint only.
- Guides (fetched): transports WebRTC / WebSocket / SIP; VAD `server_vad` (threshold, prefix_padding_ms, silence_duration_ms) and `semantic_vad` (eagerness auto/low/medium/high); `create_response` and `interrupt_response` flags; barge-in: server truncates unplayed audio on `input_audio_buffer.speech_started` (WebRTC/SIP) or client sends `conversation.item.truncate` with `audio_end_ms`; **max session 60 minutes**; 24 kHz PCM; out-of-band responses via `"conversation":"none"`.

Assessment: half-duplex with fast barge-in, not a model that speaks while listening; no way to train it; behaviour steering is prompt + function calls only. Motion could be driven by function calls, but every non-speech decision then costs a round-trip and audio tokens at $32-64/M.

### 3.2 Gemini Live API (native audio)
- Capabilities https://ai.google.dev/gemini-api/docs/live-api/capabilities (fetched): models **gemini-3.1-flash-live-preview** and **gemini-2.5-flash native audio**; input 16 kHz PCM, output 24 kHz; 97 languages; thinking (`thinkingLevel` on 3.1, default minimal); **affective dialog** and **proactive audio** (model declines to respond to non-device-directed speech) on 2.5 only, v1beta; VAD automatic (start/end sensitivity, prefixPaddingMs, silenceDurationMs) or manual `activityStart/End`; "When VAD detects an interruption, the ongoing generation is canceled and discarded"; async tool calls (`NON_BLOCKING`) on 2.5; **session limits 15 min audio-only, 2 min audio+video; 128k context** on native-audio models.
- Pricing https://ai.google.dev/gemini-api/docs/pricing (fetched): gemini-2.5-flash-native-audio-preview-12-2025: text in $0.50, audio/video in $3.00, text out $2.00, audio out $12.00 per 1M; gemini-3.1-flash-live-preview: text in $0.75, **audio in $3.00 (= $0.005/min)**, video in $1.00 ($0.002/min), text out $4.50, **audio out $12.00 (= $0.018/min)**.

Budget arithmetic (mine): continuous listening at $0.005/min = $0.30/h; with the dog speaking ~20% of the time, ~$0.52/h, so **$300/mo buys ~575 h/month (~19 h/day)** of Gemini 3.1 Flash Live — the vendor per-minute rates make an always-on hosted ear affordable, but the 15-min session cap forces reconnect logic and the model still cannot emit motion except through tool calls.

---

## 4. Adding an ACTION / MOTION stream to a speech LLM (the core question)

### 4.1 DuplexSLA (May 2026) — full-duplex speech + language + **action channel**
- https://arxiv.org/html/2605.20755 (fetched); repo https://github.com/hyzhang24/DuplexSLA (fetched).
- Dual-stream, three-channel model on a **160 ms conversational clock**: per chunk (1) two 80 ms causal user-audio features, (2) TA4 layout = 1 text anchor + four 40 ms assistant audio tokens, (3) **up to ten action text tokens** (overflow to later chunks). The action channel carries delayed transcript, planning text, **interaction-control labels (response / interrupt / backchannel)** and JSON tool calls. "Three semantic phenomena therefore become intrinsic model behaviours rather than external rules: Pause, Interrupt, Backchannel."
- Init from Step-Audio 2 mini (README: ~7B; HTML extraction said "77B", almost certainly a parse error of 7B — Step-Audio-2-mini is 8B). Continued pretraining ~**500k h** (320k duplex dialogue + 90k user ASR + 90k assistant ASR) + 1.92M text samples; post-training ~50k h (36k interrupt/backchannel/pause + 14k tool calling).
- DuplexSLA-Bench (2,100 turn-taking + 900 tool cases): Normal 96.00% / 0.27 s; Pause 93.33% / 0.27 s; **Interrupt 99.33% / 0.40 s; Backchannel 98.33% / 0.32 s; tool-call delay ~0.64 s vs 2.77 s cascade**. 50-function schema (cabin control, navigation, media, search). MIT code; **checkpoints and inference "coming soon"**; paper CC BY 4.0.

Assessment: **load-bearing design precedent.** It is precisely "speech + a rate-limited symbolic action stream on one clock", trained so that backchannel/interrupt decisions are tokens on the action channel — the same slot a `look_back` / `chuckle` / velocity-bin token would occupy. The 160 ms chunk is a natural match for Parcel's 50 Hz body-intent lane (8 ticks). Weights are not out, and 500k h is far beyond us, so it is a blueprint, not a checkpoint.

### 4.2 RoboEgo / FLM-Ego (Jun 2025) — omnimodal native duplex with action tokens on a humanoid
- https://arxiv.org/html/2506.01934 (fetched). NTU Singapore + BAAI. **7B** backbone; **six parallel streams: contextual visual, streaming visual, speaking audio, listening audio, text, action tokens**; parallel input streams instead of TDM; "theoretical duplex latency of 80 ms"; text-first with a configurable speaker delay. Deployed on **LEJU Kuavo humanoid**: 96.5% locomotion accuracy, 97.2% "Telepathy Challenge" success; human eval naturalness 8.2 vs 7.9, responsiveness 8.8 vs 8.1; WER 3.2-5.4. No weights.

Assessment: the only fetched source with a full-duplex speech model **driving a legged robot's locomotion from an action-token stream while talking**. It validates the architecture Parcel needs (action tokens as one more parallel stream at 12.5 Hz / 80 ms), even though nothing is released.

### 4.3 RoboOmni (Oct 2025) — Qwen2.5-Omni + FAST+ action tokens, speech + action out
- https://arxiv.org/html/2510.23763 (fetched); code https://github.com/OpenMOSS/RoboOmni; HF collection fnlp/roboomni.
- Perceiver-Thinker-Talker-Executor on **Qwen2.5-Omni 3B/7B**; actions as **FAST+ tokens of 7-DoF control**, emitted autoregressively; both speech and actions produced ("interactive confirmation" before acting). OmniAction: **141,162 episodes**, 5,096 speaker timbres, 2,482 sound events, 640 backgrounds, 112 skills / 748 objects, six contextual-instruction types (sentiment cues, overlapping voices, non-verbal cues, identity cues, dyadic/triadic dialogue).
- Results: LIBERO-TTS **85.6%** vs OpenVLA 2.6% / NORA 25.9% / pi0 3.0%; real speech 76.6% vs pi0 73.8%; **0.49x latency** of ASR+VLA cascades on one RTX 4090; **64 A100 x 10 days**; WidowX 250S arm. Paper CC BY-NC-ND.

Assessment: proves an Apache-2.0 omni backbone that fits Orin can be taught to emit action tokens *conditioned on non-verbal audio cues* (a sigh, an alarm, who is speaking) — the "state of the world" conditioning the owner asked for — but at 15k A100-hours and turn-based.

### 4.4 VLAS (ICLR 2025)
- https://arxiv.org/abs/2502.13508 (fetched). Speech recognition integrated directly into the VLA policy via inner speech-text alignment, retaining voiceprint; voice RAG for owner-specific knowledge; SQA and CSI datasets. Numbers not on the abstract page.

### 4.5 Non-verbal vocalization (laughter) as tokens
- dGSLM (2022) https://arxiv.org/abs/2203.16502 and https://ar5iv.labs.arxiv.org/html/2203.16502 (both fetched): dual-tower transformer with cross-attention, 6 layers / 8 heads / d=512, HuBERT 500 units, HiFi-GAN; **2,000 h Fisher two-channel audio, textless**; generates "speech, laughter and other paralinguistic signals in the two channels simultaneously"; naturalness MOS 3.70, meaningfulness 2.48; per minute: 24.2 IPUs, 5.4 pauses, 7.2 gaps, 10.9 overlaps. Canonical proof that laughter/backchannel timing is learnable from raw dyadic audio without labels.
- NVSpeech https://arxiv.org/html/2508.04195v1 (fetched): 18 paralinguistic categories incl. **[Laughter]**, [Cough], [Uhm], [Surprise-oh]; **48,430 human-annotated utterances (76 h) + 174,179 auto-labelled (573.4 h)**; paralinguistic-aware ASR decodes inline tokens ("You're so funny [Laughter]") with F1 up to 0.85, CER 3.79%; TTS with inline tags: 78.7% listener preference, paralinguistic recall 61.9%; CC BY-NC-SA 4.0.
- NonVerbalSpeech-38K https://arxiv.org/html/2508.05385 (fetched): 131 h / 38,718 samples, 10 tags incl. [laughing]; F5-TTS fine-tune; frame-level NV detector ~91% F1; CC BY-NC 4.0.
- Preference optimization for NV synthesis (Aug 2026) https://arxiv.org/html/2608.24163 (fetched): CosyVoice2-0.5B + **DPO** on Emilia-NV (573.4 h), NV-aware CER metric; human preference 55.5% vs 44.5% for NV accuracy.

Assessment: the field already treats laughter as an **inline token in the text stream** for both ASR and TTS, with open datasets. For Parcel: (1) a laughter *detector* (NVSpeech-style ASR or the NVS-38K frame detector, ~91% F1) gives the reward signal "the owner laughed"; (2) a `[Laughter]` tag in Moshi's inner-monologue stream is the emission mechanism for the dog's chuckle, and a `<act:chuckle>` motion token can be co-emitted.

### 4.6 Seamless Interaction dataset (Meta, 2025)
- https://arxiv.org/abs/2506.22554 and https://huggingface.co/datasets/facebook/seamless-interaction (both fetched): **>4,000 h**, >4,000 participants; 1080p video, 48 kHz separate-channel audio, time-aligned transcripts, **SMPL-H body motion at 30 Hz, facial/body keypoints, VAD at 100 Hz**, emotion (arousal/valence), Facial Action Units, gaze/head encodings; ~10.5 h of internal-state / rationale annotations; **CC-BY-NC 4.0**; train ~20 TB+. Baseline models generate dyadic motion and facial expressions from the interlocutor's speech and visual behaviour.

Assessment: the largest dyadic corpus with **motion + speech + VAD + emotion** aligned — the natural pretraining source for "what does a listener's body do when the speaker is funny / pauses / looks away". Non-commercial, so research-phase only.

---

## 5. Benchmarks and the curated list
- Full-Duplex-Bench v1 https://arxiv.org/html/2503.04721 (fetched): tasks pause handling (Candor 216 + synthetic 137), backchannel (ICC 55), turn-taking (Candor 119), interruption (synthetic 200); metrics TOR, backchannel frequency & JSD, response latency, GPT-4o coherence. Reported: Moshi pause TOR 0.985, turn-taking latency 0.265 s, interrupt latency 0.257 s; Freeze-Omni 0.642 / 0.953 s / 1.409 s; **Gemini Live 0.255 / 1.301 s / 1.183 s**; dGSLM 0.934 / 0.352 s / 2.531 s. Code: github.com/DanielLin94144/Full-Duplex-Bench.
- Full-Duplex-Bench v2 https://arxiv.org/abs/2510.07838 (fetched; ACL 2026): streaming automated examiner, Fast vs Slow pacing, task families daily / correction / entity tracking / safety; supports commercial APIs and open models; finds duplex systems "get confused when people talk at the same time".
- Awesome-Full-Duplex-SDM https://github.com/Ruiqi-Yan/Awesome-Full-Duplex-SDM (fetched): 2026 entries Qwen3.5-Omni (API), DuplexOmni (code), Lychee-FD (weights), BayLing-Duplex (weights), DuplexSLA (code), Seeduplex (API), Covo-Audio (weights), PersonaPlex (code); benchmarks FDB v3 (tool use under disfluency), HumDial-FDBench, SID-bench, Game-Time, MTR-DuplexBench; datasets DuplexGen (2.6M utterances), DuplexChat, ConversationalVoice; turn detectors X2-Turn, TurnSense 1.1, SoulX-Duplug.

---

## 6. Edge / Jetson AGX Orin evidence
- Orin spec page https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ (fetched): AGX Orin 64 GB — 2048 Ampere cores, 64 Tensor cores, 12-core A78AE, **64 GB LPDDR5 at 204.8 GB/s**, 15-60 W; the fetched page quoted 248 sparse INT8 TOPS.
- llama.cpp issue #15923 https://github.com/ggml-org/llama.cpp/issues/15923 (fetched): **Qwen2.5-Omni-7B Q8_0 on Jetson AGX Orin 64 GB, full GPU offload, ~15.3-16.1 tok/s**; audio input produced garbage after commit eb39499 (integrated-GPU handling), unresolved in the thread — i.e. someone has run an omni model on our exact board, and the audio path is fragile.
- Jetson AGX Orin LLM benchmark (secondary blog, May 2026) https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/ (fetched): llama.cpp CUDA, JetPack 6.1: Llama 3.1 8B Q4_K_M 28 tok/s (TTFT 1.2 s, 5.8 GB); Qwen2.5 7B Q4_K_M 31 tok/s; Phi-3 Mini 47 tok/s.
- NanoLLM https://dusty-nv.github.io/NanoLLM/ and /agents.html (fetched): Jetson Orin, JetPack 5/6; VoiceChat agent = ASR -> LLM -> TTS with Riva ASR/TTS, Piper, XTTS; interrupt "when the user submits (or speaks) a full query". Jetson AI Lab tutorials index (fetched) lists only a Jetson Thor ASR+LLM+TTS studio; no full-duplex or omni tutorial.
- **No fetched source reports Moshi, MiniCPM-o or any native-duplex model running on Orin.**

Feasibility arithmetic (mine, from the numbers above): Moshi's 7B temporal transformer must step **12.5 times/s**; at int8 (~7 GB weights) the 204.8 GB/s bus bounds decode at ~28 steps/s, and the measured 15-16 tok/s for a Q8 7B in llama.cpp on Orin leaves ~20% headroom before Mimi and the depth transformer. So 7B native duplex on Orin is *marginal at int8, plausible at int4, unproven*. A 1-3B Moshi-style model (Hibiki-1B precedent) or MiniCPM-o 4.5 int4 (11 GB, 212 tok/s on a desktop GPU) is the safer bet; both must be benchmarked on the board before any design commits.

---

## 7. Cross-cutting assessment

1. **Two viable native-duplex architectures exist in the open**: Moshi-style parallel streams (Moshi, PersonaPlex, Hibiki, MoshiRAG, RoboEgo, DuplexSLA) and TDM/time-sliced interleaving (MiniCPM-o 4.5, DuplexOmni, OmniFlatten). Parallel streams give 80 ms behaviour granularity and the cleanest place for an action stream; TDM gives vision for free today.
2. **Non-speech control tokens inside a duplex speech model are proven** at three levels: `<ret>` (MoshiRAG), interaction-control labels + tool JSON on a rate-limited action channel (DuplexSLA), and locomotion action tokens on a humanoid (RoboEgo). None of the three released a robot checkpoint; two released the recipe.
3. **Behaviour timing is trained with RL on rule-based rewards** computed from the two audio channels (Kyutai GRPO; DuplexPO FCDR; SALMONN-omni DPO). Backchannel rewards are literally "short vocalization inside a window" — chuckle-on-joke is the same reward with a laughter detector.
4. **Data is synthetic almost everywhere**: PersonaPlex 2,250 h from LLM+TTS; MoshiRAG 47,770 h synthetic; OmniFlatten 2,000 h duplex from 390K text dialogues; DuplexOmni 3M conversations; RoboOmni 141k episodes with injected sounds. Nobody needed real robot-dog conversations to train timing.
5. **Licenses**: Moshi/MoshiRAG/Hibiki CC-BY 4.0 and MiniCPM-o/Qwen2.5-Omni/Step-Audio-2-mini/Fun-Audio-Chat/CSM Apache 2.0 are commercially clean; PersonaPlex is NVIDIA Open Model License; moshika-rl-seamless, LLaMA-Omni2, BayLing-Duplex, Seamless Interaction, NVSpeech are non-commercial/research.
6. **Hosted APIs are half-duplex with barge-in**; Gemini Live scored worst on FDB v1 pause handling (TOR 0.255 is *good* there — lower is better — but 1.3 s turn-taking latency is 5x Moshi). They cannot be trained; Gemini's per-minute audio pricing does fit the $300/mo budget for near-continuous listening.

## 8. What this means for Parcel

**Candidate design A — "Moshi + action stream" (recommended experiment):** take Moshi-7B (or PersonaPlex-7B for the persona/voice prompt) and add a **19th token stream, `act`, at 12.5 Hz** that carries Parcel's existing discrete ACT-token codec (velocity bins) plus symbolic expression tokens (`<chuckle>`, `<look_back>`, `<nod>`, `<idle>`), trained with moshi-finetune LoRA r<=128. Input side: the user channel stays audio; the **world state** (owner bearing from the mic array / camera, distance-to-owner from LiDAR, "lost" flag from the planner, owner-model facts) is rendered as a short text system prompt refreshed every few seconds in the PersonaPlex way, later replaced by MoshiVis-style gated adapters. Safety layer keeps final motor authority; the `act` stream is an *intent* input to the existing 50 Hz lane. Chunk alignment: 1 model step = 80 ms = 4 body-intent ticks.

**Candidate design B — "MiniCPM-o 4.5 + tool-call actions":** fine-tune MiniCPM-o 4.5 (Apache 2.0, int4 11 GB) with LLaMA-Factory so its text output stream interleaves `<act:...>` tags while its TDM speech stream keeps talking, using live camera + audio as inputs. Cheaper to stand up, runs on Orin memory, but behaviour timing is bounded by the TDM slice and there is no published Orin latency.

**Candidate design C — hosted brain + local reflexes:** Gemini 3.1 Flash Live (~$0.52/h at 20% speaking) or gpt-realtime for language, local small duplex model (0.5-1B, OmniFlatten/Mini-Omni2-style) for backchannels/laughs/look-back reflexes on Orin. Cheapest to ship, but the owner's ask ("learn what to do given the state of the world") is only satisfied by the local trainable part.

**Simulation / training plan implied by the sources:**
1. Build a **synthetic dyadic corpus** the way PersonaPlex/MoshiRAG/OmniFlatten did: LLM-written owner-dog dialogues with the world-state prompt, TTS for the owner voice (include [Laughter] tags via an NVSpeech-style TTS), the dog's audio from Moshi itself, and a scripted `act` track (chuckle after owner-laugh, look_back when "lost" flag set). Target 1-2k h; PersonaPlex needed 6 h x 8 A100 for 2,250 h.
2. **SFT** with LoRA on the stereo-WAV format; verify on Full-Duplex-Bench v1 (open code) that pause/backchannel/interrupt metrics do not regress below Moshi's baseline.
3. **RL stage** with the Kyutai GRPO recipe: rewards R_bc from a laughter/backchannel detector (NVSpeech F1 0.85 / NVS-38K 91%) restricted to windows after detected owner laughter; R_lookback = negative delay between "lost" flag and `<look_back>` token; R_pause / R_int unchanged; LLM judge for content. Kyutai used 32 H100 for 100 epochs; on one 32 GB GPU expect to scale down to a 1-3B student or run RL on the LoRA only.
4. **Sim-in-the-loop**: MuJoCo Go2 executes the `act` stream through the existing safety layer; the "lost" flag and owner bearing come from the sim; owner laughter is injected from NVSpeech-style clips; log preference pairs (owner reaction vs no reaction) for a later DPO pass (Kyutai 150k-pair recipe).
5. **Board gating**: before any of this, benchmark Moshi int8/int4 and MiniCPM-o int4 on the Orin (nobody has published it; llama.cpp's Orin audio path had an open bug).

## 9. Open questions
- Can a 7B Moshi step at 12.5 Hz on Orin at int4 with Mimi in the loop, and what is the power draw? (No published measurement.)
- Does adding an `act` stream to Moshi degrade speech quality the way acoustic-delay ablations suggest, and what delay tau should the act stream have relative to text? (DuplexSLA rate-limits to 10 tokens/chunk; RoboEgo uses text-first ordering.)
- Will Kyutai or NVIDIA release a sub-3B dialogue Moshi? Hibiki-1B exists for translation only.
- DuplexSLA weights: "coming soon" (MIT). If released, it is a direct starting point with an action channel already trained.
- Can laughter-conditioned rewards be computed reliably from the XVF3800 mic array in a room with the dog's own speaker output (echo)? SALMONN-omni reports echo-cancellation training; Moshi's two-channel format assumes separated channels.
- Licensing: moshika-rl-seamless and Seamless Interaction are non-commercial; if Parcel is ever sold, RL must be re-run on Fisher-like or synthetic data.

## 10. Fetched source list
- https://arxiv.org/html/2410.00037v2 ; https://github.com/kyutai-labs/moshi ; https://github.com/kyutai-labs/moshi-finetune ; https://github.com/kyutai-labs/hibiki ; https://arxiv.org/abs/2502.03382 ; https://arxiv.org/html/2509.08753v1 ; https://github.com/kyutai-labs/unmute ; https://arxiv.org/abs/2503.15633 ; https://arxiv.org/html/2604.12928v2 ; https://github.com/kyutai-labs/moshi-rag ; https://arxiv.org/abs/2506.21463 ; https://arxiv.org/html/2606.11167 ; https://huggingface.co/kyutai/moshika-rl-seamless ; https://kyutai.org/papers/
- https://arxiv.org/html/2602.06053 ; https://huggingface.co/nvidia/personaplex-7b-v1 ; https://github.com/NVIDIA/personaplex
- https://arxiv.org/html/2411.00774 ; https://github.com/VITA-MLLM/Freeze-Omni ; https://arxiv.org/html/2505.02625 ; https://github.com/ictnlp/LLaMA-Omni2 ; https://arxiv.org/abs/2412.02612 ; https://github.com/THUDM/GLM-4-Voice
- https://huggingface.co/Qwen/Qwen2.5-Omni-7B ; https://arxiv.org/html/2509.17765 ; https://github.com/QwenLM/Qwen3-Omni ; https://arxiv.org/html/2604.15804
- https://github.com/OpenBMB/MiniCPM-o ; https://huggingface.co/openbmb/MiniCPM-o-4_5
- https://arxiv.org/html/2507.16632 ; https://github.com/stepfun-ai/Step-Audio2 ; https://huggingface.co/stepfun-ai/Step-Audio-2-mini ; https://arxiv.org/abs/2605.23463
- https://arxiv.org/html/2512.20156v1 ; https://huggingface.co/FunAudioLLM/Fun-Audio-Chat-8B
- https://arxiv.org/abs/2602.09823 ; https://arxiv.org/abs/2607.06540 ; https://arxiv.org/abs/2606.14528 ; https://arxiv.org/html/2606.09186v1 ; https://arxiv.org/html/2607.07148
- https://arxiv.org/html/2410.17799 ; https://arxiv.org/html/2505.17060 ; https://arxiv.org/html/2410.11190 ; https://arxiv.org/abs/2502.11123
- https://github.com/SesameAILabs/csm ; https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice
- https://developers.openai.com/api/docs/pricing ; https://developers.openai.com/api/docs/guides/realtime ; https://developers.openai.com/api/docs/guides/realtime-vad ; https://developers.openai.com/api/docs/guides/realtime-conversations ; https://developers.openai.com/api/docs/models/gpt-realtime ; https://developers.openai.com/api/docs/models/gpt-realtime-2.1
- https://ai.google.dev/gemini-api/docs/live-api/capabilities ; https://ai.google.dev/gemini-api/docs/pricing ; https://ai.google.dev/gemini-api/docs/live
- https://arxiv.org/html/2605.20755 ; https://github.com/hyzhang24/DuplexSLA ; https://arxiv.org/html/2506.01934 ; https://arxiv.org/html/2510.23763 ; https://arxiv.org/abs/2502.13508
- https://arxiv.org/abs/2203.16502 ; https://ar5iv.labs.arxiv.org/html/2203.16502 ; https://arxiv.org/html/2508.04195v1 ; https://arxiv.org/html/2508.05385 ; https://arxiv.org/html/2608.24163 ; https://arxiv.org/abs/2506.22554 ; https://huggingface.co/datasets/facebook/seamless-interaction
- https://arxiv.org/html/2503.04721 ; https://arxiv.org/abs/2510.07838 ; https://github.com/Ruiqi-Yan/Awesome-Full-Duplex-SDM
- https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ ; https://github.com/ggml-org/llama.cpp/issues/15923 ; https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/ ; https://dusty-nv.github.io/NanoLLM/ ; https://dusty-nv.github.io/NanoLLM/agents.html ; https://www.jetson-ai-lab.com/tutorials
