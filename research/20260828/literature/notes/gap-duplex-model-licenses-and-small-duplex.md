# Gap note: duplex-model licenses and sub-4B full-duplex / streaming speech-to-speech options

Literature notes, 2026-08-28 (gap fill for `duplex-speech-llms.md`). Every URL below was fetched in this session; numbers and quotes are from the fetched page unless marked *(search snippet)*. Model-card licenses were read from the Hugging Face API metadata (`/api/models/<id>`) because three of the repos are gated and their raw README returns HTTP 401.

Two questions:
1. Exact license strings for `kyutai/personaplex-rl-seamless`, `kyutai/moshika-rl-seamless`, `nvidia/personaplex-7b-v1`, `kyutai/moshiko-pytorch-bf16`, `kyutai/moshika-pytorch-q8`, and what the non-commercial clauses actually bind.
2. Any open full-duplex or streaming speech-to-speech model **under 4B parameters** released 2025-2026, with duplex style, latency, license, and language coverage (Korean in particular).

---

## 0. Headline table

| Model | Params | License (verbatim field) | Duplex style | Latency | Languages | Verdict for Parcel |
|---|---|---|---|---|---|---|
| kyutai/moshiko-pytorch-bf16 | 7,687,729,152 (safetensors) | `cc-by-4.0` | native full-duplex | 160 ms theoretical / 200 ms practical | en | commercially clean base |
| kyutai/moshika-pytorch-q8 | same arch, q8 | `cc-by-4.0` | native full-duplex | same | en | commercially clean int8 |
| nvidia/personaplex-7b-v1 | 8,371,408,896 | `license: other`, `license_name: nvidia-open-model-license` (+ CC-BY-4.0 attribution for Moshi base) | native full-duplex + text/voice persona | FDB turn-taking 0.170 s; interruption 0.240 s | en | commercial OK under NVIDIA OML |
| kyutai/moshika-rl-seamless | 7,687,729,152 | `cc-by-nc-4.0` | native full-duplex, GRPO-aligned | (none on card) | en | **non-commercial** |
| kyutai/personaplex-rl-seamless | 8,371,408,896 | `license: other`; gated text: "a combination of CC BY-NC 4.0 and the NVIDIA Open Model License" | native full-duplex | (none on card) | en | **non-commercial** |
| LiquidAI/LFM2-Audio-1.5B (Oct 2025) | 1.5B (1.2B LM + 115M encoder) | LFM Open License v1.0 (commercial < US$10M revenue) | interleaved streaming, **turn-based** | < 100 ms end-to-end (blog) | en (JP variant separate) | smallest permissive real-time S2S |
| LiquidAI/LFM2.5-Audio-1.5B (Nov 2025) | 1.5B | LFM Open License v1.0 | interleaved streaming, turn-based | not stated | en | same family, newer |
| gpt-omni/mini-omni (2024) | Qwen2-0.5B base (0.6B in Liquid's table) | `mit` | streaming, "talking while thinking"; turn-based | not stated | en | reference-only, weak (VoiceBench 33.49 for Mini-Omni2) |
| gpt-omni/mini-omni2 (2024) | Qwen2 base | `mit` | "command-based interruption mechanism" | not stated | en out only | half-duplex |
| SLAM-Omni (Dec 2024) | Qwen2-0.5B (per VocalNet comparison) | code MIT; Chinese model GPL-3.0 "research purposes only"; weights on Google Drive | turn-based | not stated | en, zh | research toy |
| VocalNet-1B (Apr 2025) | LLaMA-3.2-1B-Instruct | `Apache-2.0` | streaming s2s, turn-based | not stated | en, zh | permissive but turn-based |
| ICTNLP/LLaMA-Omni2-0.5B (May 2025) | "2B params" on card (0.5B LLM + Whisper-large-v3 + CosyVoice 2) | code Apache-2.0; "The model may not be used for any commercial purposes." | turn-based streaming | not on card | en (bilingual variants en/zh) | **academic-only** |
| MiniMind-O (May 2026) | 0.1B (113.13M) and 0.3B MoE (314.89M) | repo `Apache-2.0`; paper CC BY 4.0 | turn-based streaming, VAD barge-in | not stated | zh, en | proof that Mimi-codec S2S trains on one RTX 3090 |
| SALM-Duplex (NVIDIA, Interspeech 2025) | TinyLlama-1.1B-chat + 100M encoder | NeMo code; **no released checkpoint** (issue #14936 unanswered) | native duplex (channel fusion) | barge-in 0.69 s; first response 0.52-0.72 s | en | the only sub-4B *native duplex* recipe; would need retraining (~30.2k h, 32xA100) |
| kyutai/hibiki-1b-pytorch-bf16 | 1.7B ("Hibiki-M") | `cc-by-4.0` | Moshi multistream, **translation only** fr->en | 12.5 Hz | fr->en | architecture precedent for a 1-2B multistream model |
| kyutai/hibiki-zero-3b-pytorch-bf16 (Feb 2026) | 3B | CC BY-NC-SA 4.0 | Moshi multistream, translation only | 12.5 Hz, 2.2 kbps | fr/es/pt/de -> en | NC; translation |
| Qwen/Qwen2.5-Omni-3B | "6B params" on HF (Thinker+Talker) | `qwen-research` ("FOR NON-COMMERCIAL PURPOSES ONLY") | turn-based streaming | not stated; VRAM 18.38 GB bf16+FA @15 s video | multilingual text; Korean speech unconfirmed | **non-commercial** |
| Qwen/Qwen3-Omni-30B-A3B-Instruct | 35B total / 3B active | `apache-2.0` | turn-based real-time streaming | not stated; 78.85 GB bf16 @15 s video | **19 speech-in incl. Korean; 10 speech-out incl. Korean** | only Apache model with Korean speech I/O; too big for Orin |
| KRAFTON/Raon-SpeechChat-9B (Apr 2026) | 9B (HF shows 10B), Qwen3 backbone | CC BY-NC 4.0 (card) / CC BY-NC-SA 4.0 (paper) | native full-duplex, **English only** | FDB v1 interruption 1.219 s; pause TOR 0.212 | en (duplex); base Raon-Speech-9B en+ko turn-based | NC; Korean not duplex |
| naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B (Jan 2026) | 8B | "HyperCLOVA X SEED 8B Omni Model License Agreement" (commercial OK under 10M MAU, not competing with NAVER) | ASR/TTS/S2ST only, no duplex | none | ko, en | Korean TTS/ASR; ~48 GB over 3 GPUs |
| kakaocorp/Kanana-1.5-o-9.8B (Feb 2026) | 11.6B total | `kanana-license`, **API-only** | streaming, no duplex | configurable | ko, en | not open |
| HIT-TMG/Lychee-FD (Jul 2026) | "13B params" on HF | `apache-2.0` | native multi-stream full-duplex | +28.5% FDB 1.5 vs baseline | zh, en | permissive native duplex, but 13B |
| tencent/Covo-Audio-Chat(-FD) (Feb 2026) | 7B | "use ... only for academic purposes ... refrain from ... any commercial or production purposes" | native full-duplex (FD variant) | not on page | en, zh | **academic-only** |
| MiniCPM-o 4.5 | 9B | `apache-2.0` | TDM full-duplex | TTFT 0.6 s; 19 GB bf16 / 11 GB int4 | en, zh only | no smaller variant exists |

**Bottom line:** as of 2026-08-28 there is **no open, permissively licensed, native full-duplex dialogue model under 4B parameters**, and **no open full-duplex model of any size that speaks Korean**. The sub-4B space is turn-based streaming S2S (LFM2-Audio-1.5B is the strongest and fastest), a 1.1B native-duplex recipe without weights (SALM-Duplex), and two Moshi-architecture translation models (Hibiki-1B/-Zero-3B) that prove the multistream decoder fits in 1.7-3B.

---

## 1. The five model cards, exact license strings

### 1.1 kyutai/moshiko-pytorch-bf16
- Card: https://huggingface.co/kyutai/moshiko-pytorch-bf16 ; raw README: https://huggingface.co/kyutai/moshiko-pytorch-bf16/raw/main/README.md ; API: https://huggingface.co/api/models/kyutai/moshiko-pytorch-bf16
- Front-matter verbatim: `license: cc-by-4.0`, `language: - en`, `library_name: moshi`. Body: "License: CC-BY". No non-commercial clause.
- API: `cardData.license: "cc-by-4.0"`, tag `license:cc-by-4.0`, safetensors total **7,687,729,152**, created 2024-09-11, gated **false**.
- Numbers: "theoretical latency of 160ms, 200ms in practice"; "audio tokens running at 12Hz and a bitrate of 1.1kbps"; training "127 DGX nodes provided by Scaleway, accounting for 1016 H100 Nvidia GPUs". "Language(s) (NLP): English".

### 1.2 kyutai/moshika-pytorch-q8
- Card: https://huggingface.co/kyutai/moshika-pytorch-q8 ; raw README: https://huggingface.co/kyutai/moshika-pytorch-q8/raw/main/README.md ; API: https://huggingface.co/api/models/kyutai/moshika-pytorch-q8
- Front-matter verbatim: `license: cc-by-4.0`, `language: - en`, `library_name: moshi`. Body: "License: CC-BY"; "Pytorch version with q8 precision." Same latency text as above. Created 2025-02-04, gated false. Files: `model.q8.safetensors` + `tokenizer-e351c8d8-checkpoint125.safetensors`.
- Kyutai org listing (API, 69 repos) also has `moshiko-pytorch-q8`, `moshiko/moshika-candle-{bf16,q8}`, `moshiko/moshika-mlx-{bf16,q8,q4}` — i.e. int8 and int4 Moshi weights exist under the same CC-BY-4.0.

### 1.3 nvidia/personaplex-7b-v1
- Card: https://huggingface.co/nvidia/personaplex-7b-v1 ; API: https://huggingface.co/api/models/nvidia/personaplex-7b-v1 (raw README is gated: HTTP 401)
- API verbatim: `license: "other"`, `license_name: "nvidia-open-model-license"`, `license_link: "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/"`, `base_model: "kyutai/moshiko-pytorch-bf16"`, language `en`, gated `auto`, safetensors total **8,371,408,896** (BF16), created 2025-12-31, modified 2026-03-02, pipeline `audio-to-audio`.
- Card text: "NVIDIA Open Model License Agreement" with additional "CC-BY-4.0" terms (the Moshi base attribution). Released January 15, 2026. English only. 24 kHz audio. FullDuplexBench: smooth turn-taking **0.170 s**, user-interruption response **0.240 s**, speaker similarity 0.650. Tested on A100 80 GB (Ampere/Hopper). Training data: Fisher English Parts 1 & 2, "fewer than 10,000 hours of human speech, 7,303 conversations".
- **NVIDIA Open Model License** (https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/, "Last Modified: October 24, 2025"): grant is "a perpetual, worldwide, non-exclusive, no-charge, royalty-free, revocable license to publicly perform, publicly display, reproduce, use, create derivative works of, make, have made, sell, offer for sale, distribute (through multiple tiers of distribution) and import the Model." Models are "commercially usable"; you may "create and distribute Derivative Models". Restrictions: rights "automatically terminate" if you "bypass, disable, reduce the efficacy of, or circumvent any technical limitation, safety guardrail or associated safety guardrail hyperparameter"; must ship a notice "Licensed by NVIDIA Corporation under the NVIDIA Open Model License"; terminates on copyright/patent litigation against the Model. Note the word **revocable** (Moshi's CC-BY is not).

### 1.4 kyutai/moshika-rl-seamless
- Card: https://huggingface.co/kyutai/moshika-rl-seamless ; API: https://huggingface.co/api/models/kyutai/moshika-rl-seamless (raw README gated: 401)
- API verbatim: tag `license:cc-by-nc-4.0`, `cardData.license: cc-by-nc-4.0`, `base_model: kyutai/moshika-pytorch-bf16`, `datasets: facebook/seamless-interaction`, language `en`, gated `auto`, safetensors **7,687,729,152** BF16, created 2026-06-02, modified 2026-06-11, pipeline `audio-to-audio`.
- Card text: "This model is licensed under CC BY-NC 4.0"; users must "accept the terms of this license". RL post-training targets "pause handling, turn-taking, backchanneling, and user interruption" using "axis-specific rewards with GRPO and an LLM Judge reward". Blog 2026-06-10; paper arXiv 2606.11167. No latency or hardware numbers on the card.

### 1.5 kyutai/personaplex-rl-seamless
- Card: https://huggingface.co/kyutai/personaplex-rl-seamless ; API: https://huggingface.co/api/models/kyutai/personaplex-rl-seamless (raw README gated: 401)
- API verbatim: tag `license:other`, `cardData.license: "other"`, gated prompt: **"This model is licensed under a combination of CC BY-NC 4.0 and the NVIDIA Open Model License."**, `base_model: nvidia/personaplex-7b-v1`, `datasets: facebook/seamless-interaction`, language `en`, gated `auto`, safetensors **8,371,408,896** BF16, created 2026-06-02, modified 2026-06-11.
- Card text: users must comply with **both** licenses; the weights combine CC BY 4.0 (Moshi base) + NVIDIA Open Model License (PersonaPlex delta) + CC BY-NC 4.0 (this RL delta). Same four-axis RL description as 1.4.

### 1.6 Why the RL checkpoints are NC: the Seamless Interaction dataset
- https://huggingface.co/datasets/facebook/seamless-interaction — license field `cc-by-nc-4.0`, "Creative Commons Attribution-NonCommercial 4.0 International"; "over 4,000 hours", "more than 4,000 participants"; video 1080p/30 fps, 48 kHz audio, transcripts, SMPL-H body, VAD, keypoints, annotations. Both `*-rl-seamless` cards list this as their dataset, and the NC term propagates to the RL delta. There is no separate clause on the dataset page about models trained on it, but Kyutai chose to license the deltas NC.

**Implication (load-bearing):** the *only* commercially clean native-duplex weights in this family are Moshi (CC-BY-4.0, all precisions) and PersonaPlex-7B-v1 (NVIDIA OML). The interactivity gains of the RL checkpoints (interruption latency 1.377 -> 0.409 s in the prior sweep's reading of arXiv 2606.11167) cannot be shipped in a product; the GRPO recipe would have to be re-run on data we are allowed to use (Fisher, synthetic, or our own).

---

## 2. Sub-4B candidates, one by one

### 2.1 Kyutai: no small Moshi; "pocket" is a TTS
- Org listing via API (https://huggingface.co/api/models?author=kyutai&limit=100, 69 repos): all `moshiko`/`moshika` dialogue repos are the 7B model in bf16/q8/q4 (pytorch, candle, mlx); `moshika-vis`, `moshika-rag`, `moshika-rl-seamless`, `personaplex-rl-seamless` are 7B fine-tunes. Sub-7B repos are `hibiki-1b`, `hibiki-2b`, `hibiki-zero-3b` (translation), `stt-1b-en_fr`, `stt-2.6b-en`, `tts-1.6b-en_fr`, `tts-0.75b-en-public`, `pocket-tts`, `helium-1-2b*`, `CASA-*-VL-2B/3B`. **No Moshi/Moshika/Moshiko dialogue checkpoint smaller than 7B exists.**
- kyutai/pocket-tts (https://huggingface.co/kyutai/pocket-tts): `cc-by-4.0`, **100M parameters**, TTS only, "~200ms to first audio chunk", "~6x real-time on a CPU of MacBook Air M4", card says English only / "More languages are planned" (the Kyutai X post found by search claims six languages now: en, fr, de, es, pt, it — *(search snippet)*). arXiv 2509.06926.
- kyutai/hibiki-1b-pytorch-bf16 (https://huggingface.co/kyutai/hibiki-1b-pytorch-bf16): `cc-by-4.0`, **1.7B** ("Hibiki-M"), 12.5 Hz, 1.1 kbps, "currently only supports French-to-English translation", speech-to-speech + speech-to-text simultaneous. Paper arXiv 2502.03382.
- kyutai/hibiki-zero-3b-pytorch-bf16 (https://huggingface.co/kyutai/hibiki-zero-3b-pytorch-bf16): **CC BY-NC-SA 4.0**, **3B**, "constant framerate of 12.5Hz", 2.2 kbps, sources fr/es/pt/de -> target en, Korean not included; "the same multistream architecture as [Moshi]"; no word-level alignments; released 2026-02-11; paper arXiv 2602.11072. *(search snippet from the repo README: "8 GB VRAM should work, 12 GB is safe" — not verified on the fetched card.)*

### 2.2 LFM2-Audio-1.5B / LFM2.5-Audio-1.5B (Liquid AI) — strongest permissive small streaming S2S
- Cards: https://huggingface.co/LiquidAI/LFM2-Audio-1.5B , https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B , https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B-JP ; blog: https://www.liquid.ai/blog/lfm2-audio-an-end-to-end-audio-foundation-model ; license text: https://huggingface.co/LiquidAI/LFM2-Audio-1.5B/raw/main/LICENSE
- Architecture: "1.2B" hybrid conv+attention LM + "FastConformer (115M, canary-180m-flash)" encoder = 1.5B; audio decoder "Mimi-compatible, using 8 codebooks"; two modes — "interleaved generation" (real-time S2S) and "sequential generation" (ASR/TTS). 32,768-token context.
- Latency (blog, 2025-10-01): "LFM2-Audio-1.5B achieved an average end-to-end latency of under 100 ms" measured "from receiving a 4-second input waveform to generating the first audible sound output"; "decode up to 8 discrete audio tokens per step".
- Benchmarks (blog table): VoiceBench overall LFM2-Audio-1.5B **56.78** vs Moshi (7B) **29.51**, Qwen2.5-Omni-3B (5B) **63.57**, Mini-Omni2 (0.6B) **33.49**; ASR avg WER 7.24 vs Whisper-large-v3 7.93. LFM2.5-Audio-1.5B card: VoiceBench 54.92, ASR WER 7.53; released 2025-11-28 (arXiv 2511.23404).
- Duplex style: **turn-based** (interleaved generation within a turn; nothing on the cards or blog describes listening while speaking).
- Languages: "Supported languages: English"; the `-JP` variant is "Liquid AI's first Japanese capable audio model". No Korean.
- **LFM Open License v1.0** (fetched): "perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license" + patent license; commercial use allowed **unless annual revenue is "$10,000,000 or more"**, in which case a commercial license is needed; non-profits exempt; derivatives allowed with notices retained and modifications marked; patent-litigation termination.

### 2.3 Mini-Omni / Mini-Omni2 (gpt-omni, 2024)
- https://huggingface.co/gpt-omni/mini-omni : license `mit`; base "Qwen/Qwen2-0.5B"; "Talking while thinking, with the ability to generate text and audio at the same time"; "Streaming audio output"; English; arXiv 2408.16725 (2024-08-29): "the first fully end-to-end, open-source model for real-time speech interaction"; VoiceAssistant-400K dataset.
- https://huggingface.co/gpt-omni/mini-omni2 : license `mit`; Qwen2 backbone; "is only trained on English ... the output is only in English"; arXiv 2410.11190: "we introduce a command-based interruption mechanism" (i.e. half-duplex with an explicit stop command, not simultaneous listening). Liquid's table sizes Mini-Omni2 at 0.6B with VoiceBench 33.49.

### 2.4 SLAM-Omni (X-LANCE, Dec 2024)
- https://github.com/X-LANCE/SLAM-LLM/tree/main/examples/s2s ; abstract https://arxiv.org/abs/2412.15649 — "a timbre-controllable, end-to-end voice interaction system with single-stage training"; "15 hours of training on 4 GPUs". Repo: "Our code is released under MIT License. The Chinese dialogue model is licensed under GPL-3.0 due to its use of Belle data and is intended for research purposes only." Checkpoints are Google-Drive links (en single-round, en multi-round, zh multi-round). 0.5B (Qwen2-0.5B) per the VocalNet comparison. Turn-based.

### 2.5 VocalNet-1B (SJTU, Apr 2025)
- https://github.com/SJTU-OmniAgent/VocalNet : `Apache-2.0`; "VocalNet-1B" on "LLaMA-3.2-1B-Instruct", VocalNet-8B on LLaMA-3.1-8B, VocalNet-Qwen25-7B; s2t and s2s with streaming inference; trained on VoiceAssistant-430K + UltraChat, "speech wave is synthesized with CosyVoice2"; English + Chinese; released 2025-04-25; EMNLP 2025. No latency numbers on the page. Turn-based.

### 2.6 LLaMA-Omni2-0.5B / -1.5B (ICT/CAS, May 2025)
- https://huggingface.co/ICTNLP/LLaMA-Omni2-0.5B : code Apache-2.0 but **"The model may not be used for any commercial purposes."** (contact fengyang@ict.ac.cn); card shows 2B params total = Qwen2.5-0.5B-Instruct + Whisper-large-v3 encoder + CosyVoice 2 flow-matching/vocoder; English only for the 0.5B-14B series, separate bilingual en/zh models; turn-based.
- Abstract https://arxiv.org/abs/2505.02625 : sizes "ranging from 0.5B to 14B parameters", "built upon the Qwen2.5 series models", "trained on only 200K multi-turn speech dialogue samples".

### 2.7 MiniMind-O (May 2026) — a 0.1B/0.3B speech-native omni model on the Mimi codec
- https://arxiv.org/abs/2605.03937 (paper CC BY 4.0; submitted 2026-05-05): "An open 0.1B-scale omni model built on the MiniMind language model. It accepts text, speech, and image inputs, and returns both text and streaming speech." "Code, checkpoints, and training data are available."
- https://github.com/jingyaogong/minimind-o : "Apache-2.0 License"; minimind-3o ~0.1B (113.13M trainable), minimind-3o-moe ~0.3B (314.89M); "Mimi audio codec" "8 codebooks, 12.5 Hz, 24 kHz"; **turn-based** streaming with VAD "real-time interruption" (asymmetric, not simultaneous); data 45.7% zh / 46.5% en / 7.8% mixed (T2A), 70.8% zh / 21.2% en (A2A); mini dataset trains "approximately 2 hours" on one RTX 3090.

### 2.8 SALM-Duplex (NVIDIA, Interspeech 2025) — the only sub-4B *native* duplex recipe
- https://arxiv.org/abs/2505.15670 and https://arxiv.org/html/2505.15670 : "Duplex speech to speech (S2S) architecture featuring continuous user inputs and codec agent outputs with channel fusion that directly models simultaneous user and agent streams"; backbone **"TinyLlama-1.1B-chat"**, "100M streaming speech encoder from a CTC model" with "80ms right context", codec "NanoCodec" at "0.6 kbps" with "4 independent codebooks" at "12.5 Hz"; barge-in latency **0.69 s**, first-response latency **0.52-0.72 s**; barge-in success **94.5% vs 55.1%** (Moshi); UTMOS 4.3 vs 3.9; ~30.2k h training data; 32xA100-80G; "The first openly available duplex S2S model with training and inference code"; code https://github.com/cchen1436/NeMo/tree/main/examples/speechlm2 .
- Weights: https://github.com/NVIDIA-NeMo/NeMo/issues/14936 (opened 2025-10-15) asks NVIDIA to "provide the pre-trained SALM-Duplex model to facilitate our reproduction"; assigned, no documented response. **No checkpoint is distributed**; a search for a HF checkpoint found none.

### 2.9 Qwen2.5-Omni-3B and Qwen3-Omni-30B-A3B
- https://huggingface.co/Qwen/Qwen2.5-Omni-3B : license field `qwen-research`; HF shows "6B params" (Thinker + Talker); Thinker-Talker with TMRoPE; "Architecture designed for fully real-time interactions, supporting chunked input and immediate output" — turn-based; VRAM (bf16 + flash-attn) 18.38 GB @15 s video, 22.43 GB @30 s, 28.22 GB @60 s; Mar 26 2025. Korean speech I/O not confirmed on the card (search only confirms Korean *text*).
- License text https://huggingface.co/Qwen/Qwen2.5-Omni-3B/raw/main/LICENSE : "Qwen RESEARCH LICENSE AGREEMENT" (2024-09-19); grant is "FOR NON-COMMERCIAL PURPOSES ONLY"; "If you are commercially using the Materials, you shall request a license from us"; must display "Built with Qwen" / "Improved using Qwen".
- https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct : `apache-2.0`; 35B total, 30B-A3B = 3B active; "real-time streaming responses in both text and natural speech" (turn-based); **speech input 19 languages including Korean; speech output 10 languages including Korean**; VRAM bf16+FA2: 78.85 GB @15 s video, 88.52 @30 s, 107.74 @60 s, 144.81 @120 s. Far beyond Orin.

### 2.10 Korean-capable models (none are open + duplex + Korean)
- **Raon-Speech / Raon-SpeechChat-9B (KRAFTON)** — paper https://arxiv.org/abs/2605.23912 + https://arxiv.org/html/2605.23912 ; card https://huggingface.co/KRAFTON/Raon-SpeechChat-9B . "a top-performing 9B-parameter speech language model (SpeechLM) for English and Korean speech understanding, answering, and generation", backbone "Qwen3-VL-8B-Instruct"; "Raon-SpeechChat enables natural full-duplex conversation" via a causal streaming encoder, token-level interleaving, special tokens SIL / BOW / BC (backchannel) and text lookahead; training "1.38M hours of highly curated English and Korean speech and text" incl. "119K hours of time-aligned real and synthetic dialogue data"; Full-Duplex-Bench v1.0: **user-interruption latency 1.219 s, pause takeover rate 0.212**; Korean KVoiceBench 66.62, VoiceBench 76.79, LibriSpeech WER 1.44. License: paper "CC BY-NC-SA 4.0"; the SpeechChat card says "Creative Commons Attribution-NonCommercial 4.0 International". **The duplex model is "real-time, simultaneous listen-and-speak conversation in English"** — Korean is only in the turn-based base model. Card: HF shows 10B params; components Voxtral-Mini encoder, Mimi codec, ECAPA-TDNN; "NVIDIA GPU with CUDA 12.x (16 GB+ VRAM)"; released April 2026; demo https://github.com/krafton-ai/Raon-SpeechChat-Demo ; an AWQ-INT4 base exists (KRAFTON/Raon-Speech-9B-AWQ-INT4, *(search snippet)*).
- **HyperCLOVAX-SEED-Omni-8B (NAVER)** — https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B , license https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B/raw/main/LICENSE , paper https://arxiv.org/html/2601.01792v1 (2026-01-05). 8B; inputs text/image/video/audio, outputs text/image/audio; ASR + TTS + speech-to-speech *translation*, **no streaming-dialogue or full-duplex claim**; Korean numbers: KsponSpeech-c WER 28.74, KsponSpeech-o 33.09, Fleurs-ko 15.33; S2ST ASR-BLEU 22.91 (ko->en), 24.70 (en->ko); TTS MOS 3.94 en / 4.22 ko; ~48 GB across 3 GPUs (vision enc ~8 GB, LLM ~16 GB, vision dec ~16 GB, audio ~4 GB). License: "non-exclusive, worldwide, non-transferable, revocable and royalty-free limited license" incl. commercial use, but a separate license is required if the service has "over 10 million monthly active users" or "directly competes with any product and service provided by NAVER"; derivative names must begin with "HyperCLOVA X"; "Powered by HyperCLOVA X" notice required.
- **Kanana-1.5-o-9.8B (Kakao)** — https://huggingface.co/kakaocorp/Kanana-1.5-o-9.8B-instruct-2602-API_Doc : **API-only**, `kanana-license`, 11.6B total (9.8B LM + encoders/decoders + voice token decoder), ko/en, streaming with `latency_first`, no duplex, released 2026-02-12.
- **Qwen3-Omni-30B-A3B** (above) is the only Apache-2.0 model with Korean speech in and out; turn-based; 35B.

### 2.11 Larger 2026 native-duplex releases (for license contrast)
- **Lychee-FD** (HITsz, Jul 2026): https://github.com/HITsz-TMG/Lychee-FD ("Apache License 2.0", three decoupled upper-layer streams — semantic, acoustic, dialogue-control — on a shared backbone; multi-stream vLLM serving "2.96x speedup in speaking rounds", "23%" less incremental GPU memory; Token2Wav from stepfun-ai/Step-Audio-2-mini; release 2026/07/10) ; https://huggingface.co/HIT-TMG/Lychee-FD (`apache-2.0`, "13B params", zh/en) ; abstract https://arxiv.org/abs/2607.06540 (+7.4% spoken QA, +28.5% FullDuplexBench 1.5).
- **Covo-Audio / Covo-Audio-Chat-FD** (Tencent, Feb 2026): https://arxiv.org/abs/2602.09823 ("7B-parameter end-to-end LALM"; "Covo-Audio-Chat-FD, the evolved full-duplex model"), https://huggingface.co/tencent/Covo-Audio-Chat (en/zh, 8B params on HF), license https://raw.githubusercontent.com/Tencent/Covo-Audio/main/LICENSE : "You agree to use the Covo-Audio only for academic purposes, and refrain from using it for any commercial or production purposes under any circumstances." **Academic-only.**
- **Voila** (Maitrix, Apr 2025): https://huggingface.co/maitrix-org/Voila-chat (MIT, 8B, "as low as 195 ms"), https://github.com/maitrix-org/Voila (Voila-autonomous full-duplex listed as "(preview)"; "six languages" not enumerated), https://arxiv.org/abs/2505.02707 ("full-duplex, low-latency conversations", "over one million pre-built voices"), dataset https://huggingface.co/datasets/maitrix-org/Voila-million-voice (MIT; en/zh/fr "+3"; Korean not confirmed on the page).
- **MiniCPM-o 4.5**: https://huggingface.co/openbmb/MiniCPM-o-4_5 — `apache-2.0`, 9B, "bilingual real-time speech conversation with configurable voices in English and Chinese", TDM full-duplex, TTFT 0.6 s, 19.0 GB bf16 / 11.0 GB int4; vision-only and audio-only *modes*, **no smaller checkpoint**.
- **Freeze-Omni**: https://huggingface.co/VITA-MLLM/Freeze-Omni (`apache-2.0` + Tencent Acceptable Use Policy with 19 prohibited categories incl. military and undisclosed machine-generated content); https://github.com/VITA-MLLM/Freeze-Omni (frozen Qwen2-7B-Instruct; chunk-level state classifier "to predict different states. These states will determine whether or not the user interrupts"; released 2024-11-26). 7B only.
- **GLM-4-Voice-9B**: https://github.com/THUDM/GLM-4-Voice (code Apache 2.0; model under https://huggingface.co/THUDM/glm-4-voice-9b/blob/main/LICENSE; zh/en; streaming decoder starts after 10 speech tokens, end-to-end after 20 tokens; Int4 option); license text https://huggingface.co/THUDM/glm-4-voice-9b/raw/main/LICENSE : "The glm-4-voice License" — "Registered users are free to use this model for commercial activities", must show "Built with glm-4" and prefix derivative names with "glm-4". 9B only.
- **Step-Audio-2-mini**: https://huggingface.co/stepfun-ai/Step-Audio-2-mini — Apache 2.0, 8B, eval tables in zh/en/ja/ar; no Korean; arXiv 2507.16632.
- **OpenS2S**: https://github.com/CASIA-LM/OpenS2S (Apache 2.0; Qwen3-8B-Instruct; needs THUDM/glm-4-voice-decoder; en/zh), https://huggingface.co/CASIA-LM/OpenS2S (`apache-2.0`, "11B params"). Streaming interleaved, turn-based.
- **VITA-Audio**: https://github.com/VITA-MLLM/VITA-Audio — four 7B checkpoints on Qwen2.5-7B-Instruct (Boost / Balance / Plus-Vanilla / Plus-Boost); first audio chunk "from 236 ms to just 53 ms" with 32 prefill tokens; 3-5x speedup; turn-based; zh/en. **No sub-4B checkpoint.**
- **Ming-Lite-Omni-1.5**: https://huggingface.co/inclusionAI/Ming-Lite-Omni-1.5 — MIT, 20.3B total / 3B active, 42 GB bf16, zh/en + dialects; no duplex claim.
- **DuplexCascade** (Mar 2026): https://arxiv.org/abs/2603.09180 — "VAD-free cascaded streaming pipeline for full-duplex speech-to-speech dialogue" that converts "utterance-wise long turns into chunk-wise micro-turn interactions"; SOTA turn-taking on Full-DuplexBench claimed; no sizes/latency in the abstract. Relevant as a *cascade* route to duplex with any small LLM + Korean TTS.
- Survey https://arxiv.org/html/2606.19453 (2026): no consolidated size/license table; catalogs Moshi, Mini-Omni/2, OmniFlatten, SyncLLM, LSLM, FireRedChat, FlexDuo, Fun-Audio-Chat, Covo-Audio.

---

## 3. What this means for Parcel

1. **License map is now exact.** Commercially clean native-duplex bases: `kyutai/moshiko-pytorch-bf16` and `kyutai/moshika-pytorch-q8` (CC-BY-4.0, all precisions incl. mlx q4) and `nvidia/personaplex-7b-v1` (NVIDIA Open Model License: commercial, derivative models allowed, revocable, guardrail-bypass and litigation termination, attribution notice). **Do not build on `moshika-rl-seamless` (CC BY-NC 4.0) or `personaplex-rl-seamless` (CC BY-NC 4.0 + NVIDIA OML)** for anything that could ship; they are gated `auto` and NC because they were tuned on the CC-BY-NC Seamless Interaction corpus. If Parcel wants the RL interactivity gains it must re-run the published GRPO recipe on Fisher/synthetic/own data.
2. **There is no sub-4B native-duplex dialogue model to download.** Kyutai's org has no Moshi below 7B; Hibiki-1B (1.7B, CC-BY) and Hibiki-Zero-3B (NC) prove the multistream decoder fits at 1.7-3B but are translation-only. SALM-Duplex is the only published sub-4B native-duplex recipe (1.1B TinyLlama + 100M encoder, 12.5 Hz NanoCodec, barge-in 0.69 s) and NVIDIA has not released weights. A "small dog brain" therefore means **training or distilling one ourselves** (Moshi-architecture at 1-3B on Helium-2B or the Hibiki-M trunk, or SALM-Duplex in NeMo on Orin-class hardware after training on a desktop), not fine-tuning a download.
3. **Best off-the-shelf small fallback is turn-based:** LFM2-Audio-1.5B / LFM2.5-Audio-1.5B (LFM Open License v1.0, fine below US$10M revenue; <100 ms first-audio; Mimi 8-codebook decoder; English only). It cannot listen while speaking, so the "chuckle mid-joke" and "look back when lost" behaviours would have to be driven by a separate always-on listener (laughter detector, track-loss event) that *interrupts* the turn-based model — the cascaded "micro-turn" pattern of DuplexCascade. That is a legitimate M1 architecture if 7B Moshi does not fit the Orin budget.
4. **Korean is unsolved everywhere.** No open full-duplex model speaks Korean: Raon-SpeechChat's duplex mode is English-only and CC BY-NC; HyperCLOVAX-SEED-Omni-8B is ASR/TTS/S2ST (no dialogue streaming) with a commercial-OK custom license; Kanana-o is API-only. The only Apache model with Korean speech in/out is Qwen3-Omni-30B-A3B (35B, turn-based, >78 GB). For Parcel, Korean means either (a) English-only dog voice with a Korean ASR front-end for commands, (b) Korean TTS side-car (HyperCLOVA X TTS MOS 4.22 ko; pocket-tts has no Korean), or (c) our own Moshi-style training with Korean synthetic dialogue — for which the Raon-Speech Korean benchmarks (KVoiceBench, KOpenAudioBench) are the evaluation set.
5. **Design-A stays 7B Moshi/PersonaPlex.** Everything that is both permissive and natively duplex is 7B-13B (Moshi, PersonaPlex, Lychee-FD 13B Apache, MiniCPM-o 4.5 9B TDM). The int8/int4 Moshi weights are CC-BY-4.0, so the Orin experiment (Moshi q8 at 12.5 Hz, 7 GB) remains the gating benchmark; PersonaPlex adds text-prompt persona/world-state injection under a license that allows a product.
6. **Compute precedent for a self-trained small model:** MiniMind-O trains a 0.1B Mimi-codec S2S in ~2 h on one RTX 3090 (turn-based); SALM-Duplex used ~30.2k h and 32xA100 for 1.1B native duplex; Raon-SpeechChat used 119K h of time-aligned dialogue. A 1-2B Parcel duplex model on the desktop RTX 5000 Ada is a weeks-scale project, not days, and needs a synthetic time-aligned corpus first.

---

## 4. All URLs fetched in this session
- https://huggingface.co/kyutai/personaplex-rl-seamless ; https://huggingface.co/api/models/kyutai/personaplex-rl-seamless
- https://huggingface.co/kyutai/moshika-rl-seamless ; https://huggingface.co/api/models/kyutai/moshika-rl-seamless
- https://huggingface.co/nvidia/personaplex-7b-v1 ; https://huggingface.co/api/models/nvidia/personaplex-7b-v1
- https://huggingface.co/kyutai/moshiko-pytorch-bf16 ; https://huggingface.co/kyutai/moshiko-pytorch-bf16/raw/main/README.md ; https://huggingface.co/api/models/kyutai/moshiko-pytorch-bf16
- https://huggingface.co/kyutai/moshika-pytorch-q8 ; https://huggingface.co/kyutai/moshika-pytorch-q8/raw/main/README.md ; https://huggingface.co/api/models/kyutai/moshika-pytorch-q8
- https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/
- https://huggingface.co/datasets/facebook/seamless-interaction
- https://huggingface.co/api/models?author=kyutai&limit=100 ; https://huggingface.co/kyutai ; https://huggingface.co/kyutai/pocket-tts ; https://huggingface.co/kyutai/hibiki-1b-pytorch-bf16 ; https://huggingface.co/kyutai/hibiki-zero-3b-pytorch-bf16
- https://huggingface.co/LiquidAI/LFM2-Audio-1.5B ; https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B ; https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B-JP ; https://huggingface.co/LiquidAI/LFM2-Audio-1.5B/raw/main/LICENSE ; https://www.liquid.ai/blog/lfm2-audio-an-end-to-end-audio-foundation-model
- https://huggingface.co/gpt-omni/mini-omni ; https://arxiv.org/abs/2408.16725 ; https://huggingface.co/gpt-omni/mini-omni2 ; https://arxiv.org/abs/2410.11190
- https://github.com/X-LANCE/SLAM-LLM/tree/main/examples/s2s ; https://arxiv.org/abs/2412.15649
- https://github.com/SJTU-OmniAgent/VocalNet
- https://huggingface.co/ICTNLP/LLaMA-Omni2-0.5B ; https://arxiv.org/abs/2505.02625
- https://arxiv.org/abs/2605.03937 ; https://github.com/jingyaogong/minimind-o
- https://arxiv.org/abs/2505.15670 ; https://arxiv.org/html/2505.15670 ; https://github.com/NVIDIA-NeMo/NeMo/issues/14936
- https://huggingface.co/Qwen/Qwen2.5-Omni-3B ; https://huggingface.co/Qwen/Qwen2.5-Omni-3B/raw/main/LICENSE ; https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct
- https://arxiv.org/abs/2605.23912 ; https://arxiv.org/html/2605.23912 ; https://huggingface.co/KRAFTON/Raon-SpeechChat-9B
- https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B ; https://huggingface.co/naver-hyperclovax/HyperCLOVAX-SEED-Omni-8B/raw/main/LICENSE ; https://arxiv.org/html/2601.01792v1
- https://huggingface.co/kakaocorp/Kanana-1.5-o-9.8B-instruct-2602-API_Doc
- https://github.com/HITsz-TMG/Lychee-FD ; https://huggingface.co/HIT-TMG/Lychee-FD ; https://arxiv.org/abs/2607.06540
- https://github.com/Tencent/Covo-Audio ; https://huggingface.co/tencent/Covo-Audio-Chat ; https://arxiv.org/abs/2602.09823 ; https://raw.githubusercontent.com/Tencent/Covo-Audio/main/LICENSE
- https://huggingface.co/maitrix-org/Voila-chat ; https://github.com/maitrix-org/Voila ; https://arxiv.org/abs/2505.02707 ; https://huggingface.co/datasets/maitrix-org/Voila-million-voice
- https://huggingface.co/openbmb/MiniCPM-o-4_5 ; https://huggingface.co/VITA-MLLM/Freeze-Omni ; https://github.com/VITA-MLLM/Freeze-Omni ; https://github.com/THUDM/GLM-4-Voice ; https://huggingface.co/THUDM/glm-4-voice-9b ; https://huggingface.co/THUDM/glm-4-voice-9b/raw/main/LICENSE ; https://huggingface.co/stepfun-ai/Step-Audio-2-mini ; https://github.com/CASIA-LM/OpenS2S ; https://huggingface.co/CASIA-LM/OpenS2S ; https://github.com/VITA-MLLM/VITA-Audio ; https://huggingface.co/inclusionAI/Ming-Lite-Omni-1.5 ; https://arxiv.org/abs/2603.09180 ; https://arxiv.org/html/2606.19453 ; https://arxiv.org/abs/2502.11123
- Failed fetches (gated, HTTP 401): raw READMEs of personaplex-rl-seamless, moshika-rl-seamless, personaplex-7b-v1 (metadata taken from the API instead). OpenReview (Lychee-FD) returned a verification page; arXiv HTML of Covo-Audio was malformed (abstract page used instead).
