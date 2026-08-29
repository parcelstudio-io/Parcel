# Gap note: adding a non-speech token stream / world-state conditioning to Moshi

Date: 2026-08-28. Scope: the two most direct templates for the Parcel behavior model
(speech + a discrete body/act token stream on one 12.5 Hz clock, steerable by voice,
conditioned on world state) — Moshi-Face and MoshiVis — plus every other 2025–2026
work found that adds an input or output stream to a Moshi/Mimi-based model.
Every source below was fetched and read on 2026-08-28; numbers are transcribed from the
fetched text (Moshi-Face Table 2 was read from the raw arXiv HTML, because the
model-summarised PDF read produced fabricated 8.x scores on a 1–5 scale).

Terminology used below (from the Moshi family): Temporal Transformer = the 7B causal
backbone that runs once per 80 ms frame; Depth Transformer = the small transformer that
autoregressively emits the 8 Mimi codebooks (plus the text token) inside a frame;
"RQ-Transformer" = the pair. Mimi tokens: 12.5 Hz, 8 codebooks, 1.1 kbps.

---

## 1. Moshi-Face — "Integrating Facial Generation into Full-Duplex Spoken Dialogue Systems"

- arXiv 2606.21970 (v1, 20 Jun 2026), cs.HC, accepted to Interspeech 2026.
  https://arxiv.org/abs/2606.21970 · https://arxiv.org/html/2606.21970v1
- Jingjing Jiang, Atsumoto Ohashi, Ryuichiro Higashinaka — Graduate School of
  Informatics, Nagoya University (the J-Moshi lab). Funded by JST Moonshot R&D.
- Paper license: arXiv perpetual non-exclusive. **No code, no weights, no demo link.**

### What it is
"Moshi-Face, the first full-duplex dialogue model that jointly processes the user's audio
and facial input while simultaneously generating speech and facial motion."
Base: kyutai/moshiko-pytorch-bf16 (7B). Face = 3D FLAME head mesh (5,143 vertices),
i.e. lip motion + expression + head motion — not pixels.

### Face token representation (the "extra stream")
- Face codec: VQ-VAE "following the design of CodeTalker". Encoder = "a downsampling 1-D
  convolutional layer followed by a transformer layer"; decoder mirrors it.
- **Rate: 12.5 Hz** — input motion at 25 fps, temporal downsampling factor r = 2, "such that
  the face codec encoded the input facial motion at 25 fps into face tokens at 12.5 Hz."
- **N = 8 face tokens per frame**, each an index into one shared codebook of
  **K = 256 entries, C = 128 dims** (chosen from a 2x2 sweep; Table 1):

  | K | C | perplexity (norm.) | MVE x1e-3 | LVE x1e-3 |
  |---|---|---|---|---|
  | 128 | 64 | 0.66 | 11.20 | 12.79 |
  | 128 | 128 | 0.67 | 11.79 | 13.95 |
  | 256 | 64 | 0.57 | 9.85 | 12.40 |
  | **256** | **128** | 0.66 | **9.90** | **11.77** |

- The N tokens inside a frame are "quantized independently with no sequential dependency"
  (parallel VQ, not residual VQ) — this is what licenses non-autoregressive generation.
- Loss: L1 reconstruction + quantization + velocity loss. Codec trained 70 epochs, AdamW,
  lr 1e-4, batch 4, on 70 h of mesh data (8:1:1 split).
- **The codec is non-causal** — the authors' own stated limitation: "we plan to replace our
  non-causal face codec with a causal, streaming codec to enable fully real-time visual
  input and output."

### Streams (verbatim, section 2.2)
"At each timestep i, the model operates on three types of token streams at 12.5 Hz, taking
as input the tokens of both the system and user and generating only those of the system:
- Text token stream (1 in, 1 out) …
- Audio token streams (2M in, M out): Each speaker is represented by M=8 audio tokens …
- Face token streams (2N in, N out): Analogously, each speaker is represented by N=8 face
  tokens. The model reads 2N streams (system and user) and generates the N streams of the
  system's facial motion."
"Following the implementation of Moshi, the audio and face token streams are delayed by one
timestep relative to the text tokens to improve the generation stability."

So the user's face IS an input modality (world-state in) and the system's face IS an
output stream (act out), both on Moshi's clock.

### Architecture: parallel Depth-Transformer stream or side head? — **side head**
Section 2.3, verbatim:
- Eq. 1: h_{i+1}, t_{i+1}, a^{1:M}_i = T_RQ( t_(<=i), a^{1:M}_(<i), f^{1:N}_(<i) ) — face
  tokens of both speakers enter the RQ-Transformer's input like audio tokens.
- "The resulting hidden state h_{i+1} and tokens t_{i+1}, a^{1:M}_i then condition the Face
  Transformer."
- "Face Transformer. This module is a non-causal, transformer-based module that generates
  N face tokens at each timestep, conditioned on the outputs of RQ-Transformer. Since the N
  face tokens within each frame are quantized independently with no sequential dependency,
  they are generated non-autoregressively in parallel."
- Eq. 2: e^All_{i+1} = h_{i+1} + e^0_{i+1} + sum_{m=1..M} e^m_i — "the module first forms a
  unified conditioning vector by summing the hidden state with the text and audio token
  embeddings" ("both produced by the embedding tables of the Face Transformer").
- "This vector is then projected and combined with a learnable positional embedding pe^n
  to form a query q^n = Proj(e^All_{i+1}) + pe^n for each of the N output positions. These
  query vectors are then passed through the Face Transformer, which applies non-causal
  self-attention across the N positions within each timestep, and N per-component linear
  heads predict the face tokens f^{1:N}_i in parallel."
- Loss: L = L_text + L_audio + lambda * L_face, lambda = 1.
- Teacher forcing across time: "ground-truth face tokens from timestep i-1 were embedded and
  added to the corresponding query vectors at timestep i, providing autoregressive
  conditioning across time while maintaining non-autoregressive generation across the N
  face tokens within each timestep."

Reading of Eq. 2: the face head runs AFTER the Depth Transformer has sampled the frame's
text token and all 8 audio codebooks (their embeddings are summed in), so per frame it is
one extra small forward pass over N = 8 query positions — not 8 extra Depth-Transformer
steps. The Face Transformer's layer count / width / parameter count are **not reported**.

### Training data and cost
- "approximately 180 hours of dialogue data, totaling around 3,400 dialogues" from Meta's
  Seamless Interaction dataset; "time-aligned speech transcriptions, separate-channel
  audio, and single-speaker videos for both speakers." 3D meshes via VHAP at 25 fps.
- Two-step: "Step 1: The RQ-Transformer was frozen, and only the Face Transformer was
  trained" (lr 5e-4, **500 steps, batch 32**); "Step 2: All components were jointly
  fine-tuned" (lr 2e-6 / 4e-6 / 1e-5 for Temporal / Depth / Face Transformers,
  **1,200 steps, batch 16**). Full fine-tuning, no LoRA. GPU type and wall-clock:
  **not reported**.

### Latency
**Not measured.** The paper says "real time" and "low latency" throughout but gives no
ms/step, no GPU, no real-time factor.

### Effect on dialogue quality (Table 2; 100 test dialogues; free-run = two Moshi-Face
models talking to each other; LLMAJ = GPT-5-mini on Whisper-large-v3 transcripts, 1–5,
averaged over 3 runs)

| Model | TF LSE-D v | TF LSE-C ^ | FR LSE-D v | FR LSE-C ^ | UTMOS ^ | Coh | Nat | Rel | Ove |
|---|---|---|---|---|---|---|---|---|---|
| Moshi (original) | – | – | – | – | **3.08** | 3.76 | 3.73 | **4.26** | **3.85** |
| Moshi-ft (180 h, no face) | – | – | – | – | 1.69 | 3.59 | 4.28 | 3.95 | 3.55 |
| Reconstructed face (upper bound) | 8.53 | 0.12 | – | – | – | – | – | – | – |
| Random face (lower bound) | 11.7 | 0.13 | 11.8 | 0.11 | – | – | – | – | – |
| **Moshi-Face** | **8.76** | 0.14 | 11.0 | 0.16 | 1.75 | **3.79** | 4.52 | 4.24 | 3.76 |
| w/o Face Transformer pre-training (Step 1) | 9.53 | 0.13 | 10.4 | 0.14 | 1.71 | 3.78 | 4.53 | 4.25 | 3.76 |
| w/o full fine-tuning (Step 2; frozen Moshi + head only) | 11.8 | 0.16 | 11.1 | 0.20 | 2.42 | 3.24 | 3.94 | 3.89 | 3.23 |
| w/o t-1 face token input | 11.3 | 0.15 | 10.1 | 0.09 | 1.45 | 3.65 | 4.51 | 3.89 | 3.50 |

Authors' reading, verbatim:
- "Both Moshi-Face and Moshi-ft obtained lower UTMOS scores than the original Moshi, which is
  expected, given that fine-tuning on a smaller domain-specific dataset can degrade general
  speech quality."
- "Notably, the ablation without full fine-tuning achieved a higher UTMOS than other
  Moshi-Face variants, as only training the Face Transformer preserves the original Moshi
  speech generation ability."
- "Despite the lower UTMOS, Moshi-Face achieved the highest coherence and the second-highest
  naturalness in LLMAJ among all models, with overall quality comparable to Moshi. This
  suggests that incorporating face tokens does not degrade dialogue quality and may even
  provide beneficial multimodal context for semantic generation."
- "Removing full fine-tuning (Step 2) resulted in the worst LSE-D and lowest LLMAJ scores,
  demonstrating that joint fine-tuning is essential."
- "Removing t-1 face token input improved free-run LSE-D but degraded LSE-C and UTMOS,
  suggesting a trade-off between error accumulation robustness and generation quality."

Honest summary: the face stream itself costs nothing on the LLM-judge axes (Moshi-Face ≈
Moshi and ≥ Moshi-ft), but the recipe's full fine-tune on 180 h halves UTMOS (3.08 → 1.75),
and that regression is attributable to the data/fine-tune, not the stream (Moshi-ft: 1.69).
A frozen backbone + side head alone gives the worst synchrony (LSE-D 11.8 ≈ random 11.7/11.8).
No human evaluation; LSE-C values (0.1–0.2) are far below typical talking-head numbers
because the metric is computed on rendered FLAME meshes.

---

## 2. MoshiVis — "Vision-Speech Models: Teaching Speech Models to Converse about Images"

- arXiv 2503.15633 (19 Mar 2025). Royer, Böhle, de Marmiesse, Mazaré, Zeghidour, Défossez,
  Pérez (Kyutai). https://arxiv.org/abs/2503.15633 · https://arxiv.org/html/2503.15633
- Code: https://github.com/kyutai-labs/moshivis — **Python MIT, Rust Apache-2.0**;
  **model weights CC-BY 4.0** (vision encoder PaliGemma2 Apache-2.0). HF card
  https://huggingface.co/kyutai/moshika-vis-pytorch-bf16 : "License: CC-BY-4.0"; "This
  model is for research only". Demo vis.moshi.chat; Babillage eval dataset on HF.

### Adapter
- Image encoder: frozen PaliGemma2 SigLIP "stage 2" encoder, ~400M params, 448 px →
  1024 image tokens.
- "we keep the weights of the image embedder and the speech transformer frozen" and
  "only train the adaptation modules which amounts to a total of **206M trainable
  parameters**" (HF card rounds to ~200M; total system ~9B).
- Cross-attention inserted "between the multi-head self attention (MHSA) and the feedforward
  network (FFN) in every transformer block" of the 7B Temporal Transformer; queries = speech
  tokens after self-attention, keys/values = image embeddings; output added as "residual
  update of the speech tokens".
- Efficiency trick: the cross-attention "QKV projection weights in every layer of the
  transformer" are shared across layers, so image KV projections are computed and cached
  once per image ("precompute and cache their KV projections once at the beginning").

### Gating mechanism
- "modulate the output of the cross-attention module with a self-gating mechanism": "gate is
  a small 2-layer MLP with a hidden size reduction factor of 1/8, followed by a sigmoid
  activation"; "gate output of zero would turn off the image information and exactly recover
  the base model behaviour".
- Motivation: "introducing this additional source of information may be detrimental to the
  model's initial conversational abilities, in particular its ability to switch context".
- "During training, we do not supervise the gate's outputs and instead let it implicitly
  learn an image relevance score"; the gates learned to activate "more on image-relevant
  information, and less on more general knowledge questions".
- OCR-VQA (audio prompt): 63.7 % without gate → 65.2 % with gate; the gate mainly improves
  "robustness, particularly when p_concat = 0" (no concatenated off-topic dialogue in training).

### Latency
- "MoshiVis only increases latency by **7 ms per inference step** compared to the base model
  Moshi"; "roughly **51 ms per step** at the beginning of the conversation and **59 ms** with
  a 5-minute context window" — "well within the 80 ms threshold for real-time latency (the
  audio codec having a frequency of 12.5 Hz)". Measured on an NVIDIA L4 and a Mac Mini
  M4 Pro. (No Orin numbers.)
- PyTorch backend needs ~24 GB GPU memory (bf16, no quantisation); Rust/MLX offer Q8_0.

### Training recipe and cost
- One-stage, parameter-efficient; synthetic multi-turn (8–16 turn) visual dialogues generated
  by two Mistral-Nemo instances over PixMo / DOCCI / PixelProse images, plus OCR-VQA, VQAv2,
  COCO, TallyQA, DocVQA.
- Mixed batches: p_audio % samples carry speech streams, the rest are "speechless"
  image–text samples; **p_audio = 25 %** is the chosen trade-off.
- **50k steps, batch 64, ~1 day on 8x H100** (HF card: single DGX node, 8x H100).
- Speech quality preservation: MOSNet 2.78 with no audio in training → 3.59 with only 1 %
  audio (base Moshi 3.34): "adding even small amounts of audio quickly recovers audio
  quality". VQAv2 zero-shot 49.3 %; COCO CIDEr 113–125 depending on config.

---

## 3. Other Moshi/Mimi-family stream extensions (2025–2026)

### 3a. MoshiRAG — asynchronous retrieval injected as a stream (Apr 2026)
- arXiv 2604.12928 (14 Apr 2026). Chien, Orsini, Kharitonov, Zeghidour, Livescu, Défossez
  (TTI-Chicago / Kyutai / Gradium). https://arxiv.org/html/2604.12928v1
- Code https://github.com/kyutai-labs/moshi-rag (MIT/Apache-2.0); weights
  kyutai/moshika-rag-pytorch-bf16 and -candle-bf16, **CC-BY 4.0**. Demo moshi-rag.kyutai.org.
- Mechanism: the model emits a retrieval-trigger token in its text (inner-monologue) stream;
  a text-in/text-out retriever runs asynchronously; "the reference text is encoded and
  injected back into Moshi as a stream". Injection = reference embeddings "projected via a
  one-layer trainable linear layer and summed to the temporal Transformer input in a
  streaming fashion" — **no new Depth-Transformer stream**, additive at the input.
- Uses the natural "keyword delay": end-to-end keyword delay 3.1 s (MoshiRAG) vs 2.1 s
  (Moshi); target retrieval ≤ 2 s; README: "sensitive to retrieval delays over 3 seconds".
- Training: ~1.9M synthetic conversations (474k QA topics + 5.5k expert topics); full
  fine-tune, reference encoder frozen; 100k updates, lr 2e-6, batch 32.
- Results: HaluEval 36.3 % vs 10.5 %; TriviaQA 69.6 % vs 22.8 %; compute 0.37 vs 0.22
  FLOPs/s (relative); takeover rate on pause track 0.32 vs 0.99 (turn-taking preserved).
- Hardware: 24 GB+ GPU for Moshi plus GPU for the reference encoder.

### 3b. Hibiki — Moshi's multistream reused for simultaneous S2ST (Feb 2025)
- arXiv 2502.03382 (v2 26 Feb 2025). Labiausse, Mazaré, Grave, Pérez, Défossez, Zeghidour.
  https://arxiv.org/abs/2502.03382 · https://arxiv.org/html/2502.03382 ·
  https://github.com/kyutai-labs/hibiki (code MIT/Apache-2.0; **weights CC-BY 4.0**; the
  arXiv page's "CC BY-NC-SA 4.0" is the paper's license).
- Streams: source audio (in), target audio + target text (out), 12.5 Hz; **Q = 16 audio
  codebooks** per stream (Hibiki-M: 8).
- Sizes: Temporal 2.2B (d 2560, 24 layers) + Depth 1.1B distilled to 449M ≈ 2.7B;
  Hibiki-M 1.7B "capable of running real-time on device" (iPhone 16 Pro via MLX-Swift);
  "faster than real-time on a H100 even when processing 320 sequences in parallel".
- Data: ~40k h per language of synthetic parallel speech (Whisper + MADLAD-3B + TTS);
  text pretrain 600k steps, audio pretrain 1,450k steps, S2ST 150k steps batch 96,
  fine-tune 8k steps on ~900 h alignment-aware TTS data.
- Lag control by inserting silence into the target stream according to a perplexity-based
  word alignment (delta_{j,i} = log p_{j,i} − log p_{j,i−1}); penalty scaled 0 → −2 as lag
  grows 1 → 2 s. CVSS-C: ASR-BLEU 39.2 vs Seamless 37.0; speaker sim 0.41 vs 0.30;
  naturalness MOS 3.73 vs 2.18; end offset 2.9 s, LAAL 5.0 s. CFG on a voice-similarity
  label (gamma = 3.0) lifts speaker similarity 0.42 → 0.48.

### 3c. DyaPlex — full-duplex speech + body motion (NVIDIA / HKUST, Jun 2026)
- arXiv 2606.03874 (2 Jun 2026). Nagano, Liu, Park, Li, Mazumdar, Jacobsen, Wang, Stengel,
  Roy, Cheung, See, De Mello. https://arxiv.org/abs/2606.03874 ·
  https://arxiv.org/html/2606.03874 · project page
  https://research.nvidia.com/labs/amri/projects/DyaPlex — **no code or weights announced**.
- The closest published thing to "speech + body tokens on one clock", but it is a
  **dual-tower** design, not an extra Moshi stream: "frozen full-duplex speech tower
  (PersonaPlex)" (d = 4096, 32 layers, Moshi-derived) + trainable causal motion tower
  (32 layers, d = 1024) that cross-attends to **all 32 speech-tower layers** ("Exposing all
  L_s = 32 layers rather than a single final embedding gives the motion tower's
  cross-attention access to all intermediate speech representations") with a time-aligned
  speech–motion RoPE.
- Motion tokenizer: body-part RVQ-VAE adapted from GestureLSM, made **causal/streaming**;
  25 fps SMPL-X in → **12.5 Hz tokens**; **K = 22 codes per frame (18 body + 4 face)** over a
  shared **4096-entry** vocabulary; four decoders (upper body, hands, lower body, face).
- Motion tower sequence per frame: speaker tag + 22 codes for each of two participants
  (46 tokens/frame), decoded one code at a time.
- Data: Seamless Interaction, 4,000 h, filtered to 57,947 pairs (3,435 h) of dyadic motion.
  Training: 6x H100, 30k iterations, effective batch 512, lr 3e-4, AdamW.
- **Latency (RTX A6000 Ada, 12.5 Hz):** "the audio tower and RVQ-VAE decoder run efficiently
  at 30 ms and 0.8 ms per frame, respectively. The autoregressive motion tower is the
  primary computational bottleneck, taking 173 ms/frame with a full 4096-token context. By
  reducing the motion context to 1024 tokens (1.8 s) while preserving the full 7.1 s speech
  context, the motion tower latency drops to 80 ms/frame."
- Limitation (verbatim): "Our model currently decodes one body token at a time for 22
  codes, which may not be most optimal for performance" — they suggest chunked decoding or
  a "Moshi-similar depth transformer design to speed up inference". Agent speech is NOT
  conditioned on partner motion (asymmetric).
- Results: FGD 5.6e-3 vs Audio2Photoreal 57e-3; diversity 0.611 vs GT 0.633; BeatAlign
  0.059 vs GT 0.050; dyadic P-FD 7.3e-3 vs 72e-3; +31 % delta-User when partner motion is
  real vs shuffled; user study n = 32 on rendered meshes: 97.5 % preference vs DualTalk,
  66.3 % vs Audio2Photoreal. No live-user study.

### 3d. PersonaPlex (NVIDIA, Jan 2026) — the Moshi derivative DyaPlex sits on
- https://huggingface.co/nvidia/personaplex-7b-v1 · https://github.com/NVIDIA/personaplex
- 7B, initialised from Moshiko; Mimi + Temporal + Depth Transformer unchanged; trained on
  Fisher (7,303 conversations, < 10k h real audio) plus synthetic; turn-taking 0.170 s,
  interruption stop 0.240 s; A100 80 GB tested. **Weights: NVIDIA Open Model License
  (commercial use permitted) with CC-BY-4.0 components; code MIT.**

### 3e. DuplexSLA — synchronized speech, language and action (May 2026)
- arXiv 2605.20755 (v2 11 Jun 2026). https://arxiv.org/abs/2605.20755
- "dual-stream three-channel formulation: a continuous user audio channel, a discrete
  assistant audio channel, and a rate-limited textual action channel" decoded "together
  with a structured action stream on a shared 160 ms chunk timeline". Actions are text
  (function-call style) on the chunk clock, not a learned codebook. Base model not Moshi
  (covered in the first sweep; kept here only as the "action-as-text-channel" contrast).

### 3f. Unmute (Kyutai) — NOT a stream extension
- https://github.com/kyutai-labs/unmute — cascaded Kyutai STT → text LLM (Gemma 3 1B
  locally; GPT-OSS-120B in production) → Kyutai TTS; ~750 ms on one GPU, ~450 ms on three;
  16 GB VRAM, x86_64 Linux only; code MIT; **tool/function calling "not currently
  supported"**. Useful as the "wrap any LLM" alternative, not as a Moshi template.

### 3g. Tool use / action-space RL on full-duplex SLMs
- Full-Duplex-Bench-v3, arXiv 2604.04847 (6 Apr 2026, Lin, Chen, Chen, Lee), CC BY-SA 4.0:
  real human audio with five disfluency categories + chained API calls in four domains;
  evaluates GPT-Realtime (Pass@1 0.600, 13.5 % interruption rate), Gemini Live 2.5 / 3.1
  (3.1: 4.25 s latency, 78.0 % turn-take), Grok, Ultravox v0.7, cascade (10.12 s latency,
  perfect turn-taking). **No Moshi-family model is in it**; tool-call emission mechanism
  not specified in the abstract. https://arxiv.org/abs/2604.04847
- ASPIRin, arXiv 2604.10065 (11 Apr 2026, Hsiao … Hung-yi Lee): "explicitly decouples when
  to speak from what to say. Using Action Space Projection, ASPIRin maps the text vocabulary
  into a coarse-grained binary state (active speech vs. inactive silence)" and runs GRPO
  with rule-based rewards; "reduces the portion of duplicate n-grams by over 50 % compared
  to standard GRPO". https://arxiv.org/abs/2604.10065

### 3h. Side-head state predictors (frame/chunk-synchronous)
- SoulX-Duplug, arXiv 2603.14877 (16 Mar 2026): Qwen3-0.6B + frozen GLM-4-Voice tokenizer;
  per 160 ms chunk it "first predicts the ASR token sequence for the current chunk" then a
  state token from {user_idle, user_nonidle, user_backchannel, user_complete,
  user_incomplete}; theoretical latency 80 + 160 = 240 ms, deployed 205 ms (EN) / 250 ms
  (bilingual); Full-Duplex-Bench turn-taking TOR 0.933 (Moshi 0.941, Freeze-Omni 0.336),
  pause TOR 0.352 (Moshi 0.983); Easy-Turn 84.33 %; state data 1,000 h Fisher + 10,000 h
  Mandarin; code https://github.com/Soul-AILab/SoulX-Duplug (license not stated).
  https://arxiv.org/html/2603.14877
- X2-Turn, arXiv 2608.10878 (Aug 2026): a turn-state head "operates in parallel with the
  ASR head on shared streaming representations" (Voxtral Realtime encoder), predicting
  fine-grained turn states frame-synchronously. Numbers not in the abstract.
  https://arxiv.org/abs/2608.10878

### 3i. Base-model facts and fine-tuning cost anchors
- kyutai-labs/moshi README: 7B Temporal Transformer; Mimi 24 kHz → 12.5 Hz at 1.1 kbps;
  theoretical latency 160 ms (80 ms frame + 80 ms acoustic delay), ~200 ms practical on an
  L4; 24 GB+ for bf16 PyTorch; int4/int8/bf16 across PyTorch / MLX / Rust; code MIT +
  Apache-2.0, **weights CC-BY 4.0**. https://github.com/kyutai-labs/moshi
- kyutai-labs/moshi-finetune (Apache-2.0): LoRA on Temporal + Depth Transformers, optional
  full embedding fine-tune, recommended rank ≤ 128; stereo wav (left = Moshi, right = user) +
  timestamped JSON transcripts; H100: ~12k tokens/s at 39.6 GB on one GPU, ~10.7k tokens/s
  per GPU at 23.7 GB on eight; example run 2,000 steps, batch 16, 100 s sequences ≈ 30M
  tokens. https://github.com/kyutai-labs/moshi-finetune

---

## 4. What this means for Parcel

### The two templates, side by side
| | Moshi-Face (act OUT) | MoshiVis (world IN) |
|---|---|---|
| Where the new information enters | New token streams in the Temporal Transformer input (2N in) | Gated cross-attention adapters in every block |
| Where the new information leaves | Non-AR side head over N positions, after the Depth Transformer | — |
| Trainable params | Face Transformer (size unreported) + full 7B in step 2 | 206M adapters, backbone frozen |
| Data | 180 h paired dialogue+face | synthetic dialogues, 25 % with speech |
| Cost | 500 + 1,200 steps (batch 32/16) | 50k steps batch 64, 1 day 8x H100 |
| Latency | unreported | +7 ms/step (51 → 59 ms on L4) |
| Quality cost | UTMOS 3.08 → 1.75 (from fine-tune on 180 h, Moshi-ft 1.69) ; LLMAJ unchanged | MOSNet recovered with ≥1 % audio |
| Weights | none | CC-BY 4.0 |

### Concrete recommendations
1. **Act stream = Moshi-Face's recipe with a symbolic, causal vocabulary.** Represent the
   body/act channel as N small parallel tokens per 80 ms frame (Moshi-Face uses N = 8,
   K = 256), fed back as inputs to the Temporal Transformer (2N in: the robot's own act
   history AND a world/owner stream) and emitted by a non-autoregressive side head
   conditioned on h_{i+1} + text embedding + the 8 audio-token embeddings. Because
   Moshi-Face's tokens are independent parallel VQ codes, the head needs no in-frame
   ordering — the same holds for a hand-designed act vocabulary (gait, body yaw bin, body
   pitch bin, vocalisation-type, gaze-target) so Parcel can skip the codec entirely and
   avoid the non-causal-codec problem the authors flag. DyaPlex shows the alternative
   (22 AR codes/frame from an RVQ-VAE) costs 173 ms/frame at full context on an A6000 Ada,
   which cannot fit an 80 ms frame budget on Orin; keep act codes few and non-AR.
2. **Expect to need Step-2 joint fine-tuning, and budget for its speech-quality tax.** The
   frozen-backbone ablation gave chance-level synchrony (LSE-D 11.8 vs random 11.7); joint
   fine-tuning was "essential". But the 180 h fine-tune halved UTMOS. Mitigations that the
   evidence supports: LoRA via moshi-finetune instead of full FT; MoshiVis-style mixing of
   "speechless" samples (speech recovered with as little as 1 % audio); Moshi-Face's Step-1
   head-only warm-up (removing it worsens LSE-D 8.76 → 9.53).
3. **World-state conditioning ("was the joke funny", "is the owner tracked") = MoshiVis
   gated cross-attention or MoshiRAG additive injection.** MoshiVis's unsupervised sigmoid
   gate is precisely the mechanism for "only react when the world stream is relevant" and
   costs 7 ms/step and 206M params; MoshiRAG's one-linear-layer additive injection is the
   cheapest possible path for a sparse event stream (track-loss event, laughter-detector
   score) and preserved turn-taking. A track-loss event can additionally be produced by a
   SoulX-Duplug/X2-Turn-style frame-synchronous state head on the same backbone.
4. **Reward learning should act on a projected action space, not raw tokens.** ASPIRin's
   result (GRPO on a coarse speak/silence projection keeps semantics, −50 % duplicate
   n-grams) argues for optimising "chuckle / no-chuckle" or "look-back / continue" as a
   coarse projected action under laughter reward while leaving the audio codebooks alone.
5. **Licensing is clean for the Kyutai path and closed for the two closest papers.** Moshi,
   MoshiVis, MoshiRAG, Hibiki weights are CC-BY 4.0; moshi-finetune Apache-2.0; PersonaPlex
   is under the NVIDIA Open Model License (commercial OK). Moshi-Face and DyaPlex ship no
   code or weights, so the act head must be reimplemented (the Moshi-Face description is
   complete enough to do so: Eq. 1–3 plus the training schedule).
6. **No Orin numbers exist anywhere in this set.** All latencies are L4 / A6000 Ada / H100
   / M4 Pro. MoshiVis's 51–59 ms/step on an L4 leaves ~20 ms of the 80 ms frame; Parcel must
   measure a Moshi (int4/int8) + side-head step on the Orin before committing to the
   single-clock design, and Hibiki (1.7B real-time on an iPhone 16 Pro) is the evidence that
   the multistream architecture survives shrinking to ~1–2B if the 7B does not fit.
7. **Data scale anchor.** 180 h of paired dialogue+behaviour was enough for a synchronous
   face head; 3,435 h was used for full-body dyadic motion. Parcel's act vocabulary is far
   smaller than a 4096-entry motion codebook, so the lower bound is the relevant one — but
   the paired (speech, act, world-state) corpus does not exist and must be synthesised or
   collected, and Moshi-Face used ground-truth act tokens with teacher forcing across time.

### Open questions this note does not settle
- Face Transformer size and per-frame cost in Moshi-Face (not reported).
- Whether Moshi-Face's user-face input streams actually help (no ablation of the 2N-in).
- How an act head interacts with Moshi's 1-step acoustic delay when the act must precede
  the speech (e.g., look back, then speak).
