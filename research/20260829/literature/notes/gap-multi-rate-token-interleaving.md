# Interleaving tokens at different rates in one sequence: reference designs for a 10 Hz act-token loop, a ~1 Hz language/plan lane and 12.5 Hz audio frames

Literature note for the Parcel "Model A / Model B" study, gap "multi-rate token interleaving". Written 2026-08-29. Every source below was fetched and read on that date (arXiv HTML/abs, the arXiv PDFs of ELLSA, DuplexSLA and Moshi text-extracted with pdftotext for exact quotes, GitHub READMEs, model cards). Numbers are quoted from the fetched text, never from memory. Where the summarizer's extraction was ambiguous the item is flagged.

Scope. How each system lays out tokens of different native rates in one autoregressive sequence (or in parallel streams over one clock), what block/chunk size it uses, how it handles the mismatch (pad/silence tokens, delay lines, hold-last/cached features, spill queues, predict-ahead, frozen-prefix async), and the measured latency. Systems that were already covered in `dual-system-speak-while-acting.md` (Hi Robot, Helix, GR00T N1, VITA-E, TIC-VLA) are only cross-referenced here except where a new fact was needed.

---

## 0. One-table comparison

| System (year) | Clock / block | What sits in one block, in order | Native rates reconciled | Rate-mismatch mechanism | Measured latency | Availability |
|---|---|---|---|---|---|---|
| ELLSA (ByteDance/Tsinghua, ICLR 2026) | **1 s time block** (0.48 s ablated) | `<bos>{5 speech emb}<eos><boi>{image tokens}<eoi>...<bot>{8 text / <silence>}<eot><boa>{FAST action tokens / dummy}<eoa>` | speech 25 Hz -> 5 Hz (concat 5), 1 video frame/s, 8 text tok/s, 1 s of FAST-tokenized actions (~10 action frames), TTS 25 codec/8 text emb | fixed slots + `<silence>` + dummy action tokens; two 8B experts (SA-MoE) | 854 ms (S2S) / 786 ms (S2A) per 1 s block on A100; 455/428 ms at 0.48 s | Apache-2.0 code, HF weights |
| DuplexSLA (2026) | **160 ms chunk** | `<\|user_audio_begin\|> U U <\|user_audio_end\|> <\|assistant_audio_begin\|> T A A A A <\|assistant_audio_end\|> {<=10 action text tokens} <\|action_end\|>` | user audio 2 x 80 ms feats; assistant 1 text anchor + 4 audio tokens at 40 ms; action channel <=10 tokens/chunk | `<vad_silence>`/`<tts_pad>` anchors, mandatory `<\|action_end\|>`, **FIFO spill queue** across chunks, transcripts delayed 2 chunks (320 ms) | turn-taking 0.27-0.40 s; tool call 0.64 s | CC BY 4.0 paper, MIT code, weights "coming soon" |
| Moshi (Kyutai, 2024) | **80 ms frame (12.5 Hz)** | 17 parallel streams per frame: 1 text + 8 Moshi audio + 8 user audio; Depth Transformer decodes the 17 within a frame | text ~3-4 tok/s vs 12.5 Hz audio | **PAD/EPAD** text padding (65 % of text slots are PAD); **acoustic delay** tau=2 pretrain, 1 finetune; text delay 0 for dialogue, +/-0.6 s randomized in pretrain; 2 s text/audio delay yields ASR/TTS | 160 ms theoretical, 200 ms on L4 | CC BY-NC-SA paper; code on GitHub |
| Hibiki (Kyutai, ICML 2025) | 12.5 Hz frame | source audio + target audio + target text streams | 16 quantizers/stream; acoustic delay 2 steps; target lags >=2 s | learned per-word delays via translation perplexity; Hibiki-M 1.7B real-time on iPhone 16 Pro | LAAL 5.0 s | CC BY-NC-SA |
| Delayed Streams Modeling (Kyutai, 2025) | 12.5 Hz frame | any set of time-aligned streams with per-stream integer delays | text padded with PAD/WORD | delay is the whole mechanism: STT text delay 0.25-4 s (default 2.5 s, +/-300 ms precision), TTS audio delayed 1.28 s (16 steps); extra "action" stream predicts whether next text token is a WORD | TTS 150 ms first audio | CC BY-NC-SA |
| RT-H (Google DeepMind, RSS 2024) | per control step | query 1: language motion; query 2: action given language motion (same PaLI-X 55B) | language motion (~"move arm forward") and action at the same step rate | **predict-ahead**: language-motion query predicts next step's motion so both queries batch -> "nearly identical querying lag as RT-2" | not given | none |
| pi0.5 (PI, 2025) | subtask then chunk | high-level text subtask, then 50 Hz action chunk via flow expert | "high-level inference process still runs at a lower frequency than low-level action inference" (value unspecified) | hold subtask across chunks; FAST discrete tokens in pretrain, flow expert in post-train | not given | paper only (blog) |
| SmolVLA async (HF, 2025) | chunk n=50 | RobotClient/PolicyServer, new inference when remaining < g*n | 450M model; chunks aggregated on overlap | queue + overlap aggregation + joint-space near-duplicate skip; blog recommends g~0.7 | task 9.7 s vs 13.75 s sync | open weights/code |
| Real-Time Chunking (PI, NeurIPS 2025) | H=50 at 50 Hz (1 s) | first d actions frozen, rest inpainted by guidance | d = floor(delta/dt): 76 ms model + 21 ms RTC on RTX 4090 -> d~6; +100/+200 ms -> d~11/16 | frozen prefix + soft-mask inpainting | no degradation vs linear degradation for sync | CC BY 4.0, openpi |
| Understanding async inference (2026) | 50 Hz, H=50 (LIBERO) | IT-RTC / TT-RTC / VLASH / A2C2 | delays d up to 20 | per-step correction head (A2C2) wins beyond d=4; IT-RTC collapses beyond d=8 | IT-RTC 469.7 ms vs A2C2 412.4 ms on RTX 3090 | CC BY 4.0, code |
| REALFAST (2026) | m=4 (400 ms) token chunks | FAST+ tokens, constrained decoding | latency bound 183 ms (LIBERO) / 302 ms (DROID); 324 ms with best-of-N | frozen prefix A_Q[0:m] as conditioning | LIBERO 95.7 % | CC BY 4.0 |
| Fast-in-Slow (NeurIPS 2025) | System-2 : System-1 = 1:4 | last 2 LLaMA2-7B blocks are System 1 | 117.7 Hz with chunk 8 on RTX 4090; 21.9 Hz chunk 1 | hold last System-2 latent for 4 fast steps; ratios 1:1..1:8 ablated, 1:4 best | - | code repo (license not stated in paper) |
| UniFS (2026) | layer groups at timescales [1,2,4,8,16] | one Qwen2.5-0.5B VLM, 5 groups recomputed at t = 0 mod n_k | action expert cross-attends multi-timescale features | cached features per group | 17.8 ms avg (12.3-32.6) vs 36.5 ms | CC BY 4.0, code |
| HiRT (CoRL 2024) | VLM async, policy sync | InstructBLIP-7B latent -> 35M/150M policy | 9.8 Hz vs 4.1 Hz | train with a randomly stale latent so the policy tolerates it | - | CC BY 4.0 |
| GR00T N1 (NVIDIA, 2025) | VLM 10 Hz, DiT 120 Hz | 12th-layer VLM tokens cross-attended by DiT; H=16, K=4 | 10 -> 120 Hz | (bridging not stated) | 63.9 ms / 16-action chunk on L40 | CC BY 4.0 |
| TIDAL (2026) | macro 16-step horizon, micro N=4 | GR00T-N1.5-3B on **Jetson AGX Orin** | ~9 Hz vs ~2.4 Hz | frozen intent + fresh proprio per single-step Euler | ~110 ms vs ~400 ms cycle | CC BY-SA 4.0 |
| DuoCore-FS (Astribot, 2025) | slow 1-3 Hz, fast 25-30 Hz | slow VLM writes a bridge buffer; fast diffusion reads latest | 32.3 Hz vs pi0 12.5 Hz | buffer of latents valid across cycles | - | closed |
| OneTwoVLA (ICLR 2026) | event-triggered | `[BOR]` reasoning text or `[BOA]` actions; latest reasoning stays in context | reasoning only at key moments | hold latest reasoning; interaction text appended to instruction | total time matches pi0 | CC BY 4.0 |
| Fast ECoT (2025) | async | cached high-level ECoT reused (91.6 % unchanged) while actions decode | 4997 ms -> 686 ms/step | stale reasoning R_c as action input | 7x | CC BY 4.0 |
| Qwen2.5-Omni / Qwen3-Omni (2025) | 2 s time-interleaving chunks; 40 ms (2.5) / 80 ms (3) per temporal ID | audio/video interleaved by wall time (TMRoPE); Thinker text + Talker audio | Qwen3-Omni AuT 12.5 Hz, codec 12.5 Hz | block-wise encoders, Talker prefills asynchronously per chunk | 234 ms first packet (audio) | Apache 2.0 |
| MiniCPM-o 2.6 / 4.5 (2025-26) | **1.0 s time window** (0.2/0.1 s degrade) | g_k = [v^k ; a^k ; o^k]: perception tokens then output tokens per window | 10 audio tok/s in, 3-4 text steps/s out, 25 speech tok/s via light decoder | `[listen]` token when silent; TDM slicing | RTF 0.27 on RTX 4090 | Apache-2.0 (2.6) |
| Chain-of-Action (NeurIPS 2025) | one trajectory per query | keyframe (goal) token first, then reverse-AR actions; K-token MTP; dynamic stop | 10 Hz on laptop 4070; PD 1000 Hz | no language tokens; global-to-local ordering | - | project page |
| MINT (2026) | next-scale AR over scales [1,2,4] | intent token -> finer action-token maps | PaliGemma-2.6B + 300M expert | coarse-to-fine in one sequence | - | paper only |
| tau0-VLA (Aug 2026) | HL language subtask, LL chunk | pipelined asynchronously; world-model beam search when uncertain | - | async pipeline | - | paper only |

---

## 1. ELLSA: End-to-end Listen, Look, Speak and Act (ICLR 2026)

- URL: https://arxiv.org/html/2510.16756 (also arXiv PDF v2, text-extracted); code https://github.com/bytedance/SALMONN/tree/ELLSA (Apache-2.0 badge; checkpoints at huggingface.co/tsinghua-ee/ELLSA).
- Block: "ELLSA operates on a one-second time block, within which it processes one second of speech input and a single video frame, generates eight tokens of text output (or a single <silence> token when no verbal response is required), and produces one second of speech and action output."
- Exact layout (Appendix A.1, default mode): `<bos> {5 speech embeddings} <eos> <boi> {front view image tokens} <eoi> <boi> {gripper view image tokens} <eoi> <bot> {8 text tokens / <silence>} <eot> <boa> {action tokens / dummy action tokens} <eoa>`. Speech-only mode: the `<boi><eoi>` pair is empty and "the model consistently produces dummy actions without actual movement."
- Rates: Mamba encoder "produces embeddings at a frame rate of 25 Hz, which are then downsampled to 5 Hz by concatenating every five consecutive embeddings"; action tokenizer is FAST on Emu3-Base ("the final 1,024 token IDs of which are replaced with FAST tokens"); TTS from CosyVoice2-0.5B "produces 25 speech codecs for every 8 textual embeddings from the LLM". The 0.48 s ablation says its action expert "produces 5 action frames per block", implying ~10 action frames per 1 s block (LIBERO at ~10 Hz).
- Rate mismatch: fixed-size slots per block; nothing else. History: "retains the complete history of speech input and text output, while preserving only a limited window of vision input and action output ... within the last two seconds".
- Two 8B experts (SA-MoE): speech expert = Mamba (32 blocks, 2048) + LLaMA-3.1-8B-Instruct; action expert = Emu3-Base; both 32 layers/4096 hidden; LoRA rank 256.
- Latency (Table 9d, A100): 1 s block: 854 ms speech-to-speech, 786 ms speech-to-action; 0.48 s block: 455 / 428 ms. "Both configurations complete inference within their respective time blocks".
- Block-size ablation (Table 9): 0.48 s speech expert unchanged (Llama Q. 77.7 -> 78.5), but the action expert drops SPATIAL 95.4 -> 91.0 %, OBJECT 98.8 -> 92.4, GOAL 93.6 -> 84.2, LONG 94.0 -> 81.0 %; full SA-MoE LONG 84.4 -> 71.6 %. "This drop is likely due to the shorter action sequences, which can reduce the temporal coherence of the generated actions." The authors also hypothesize the 1 s block "simplif[ies] the learning of full-duplex dynamics" vs "0.16 seconds for Freeze-Omni".
- Duplex numbers (Table 3): dialogue turn-taking 100 % (Moshi 85.0/76.0/37.1/83.4 %); action turn-taking SPATIAL 100 / OBJECT 99.6 / GOAL 100 / LONG 96.4 %; defective-instruction rejection 100 %; speaking-while-acting inputs: general question 100 %, interruptive command ("Action Cancelled") 94.3 %, silence 100 %.
- Speaking-while-acting cost (Table 4 vs Table 1/2): LIBERO SPATIAL 93.3 (vs 90.8 alone), OBJECT 96.6 (95.8), GOAL 86.1 (86.4), LONG 73.2 (84.4); TriviaQA S2T 35.1 (vs 45.2).
- Data: ASR 481k samples, QA 728k, LIBERO 3,386 + 1,693 rejection examples; Stage 1 40k steps bs 512, Stage 2 500 steps bs 1024, Stage 3 20k steps bs 256; A100 bf16.

## 2. DuplexSLA (May/June 2026)

- URLs: https://arxiv.org/html/2605.20755v1 ; abs https://arxiv.org/abs/2605.20755 (CC BY 4.0); PDF text-extracted; https://github.com/hyzhang24/DuplexSLA (MIT badge; "Inference code, model checkpoints, and DuplexSLA-Bench are coming soon"); project page https://hyzhang24.github.io/DuplexSLA/.
- Backbone: "7B speech-LM, initialized from Step-Audio 2 mini" (Table 1; the HTML summarizer once returned "77B" -- a table-parse artifact; the PDF text and README both say 7B).
- Chunk: "Streaming clock: 160 ms conversational chunks. User audio granularity: 2 causal acoustic features per chunk (80 ms each). Assistant audio granularity: 4 discrete audio tokens per chunk (40 ms each). Per-chunk speech layout: TA4 (one text anchor + four audio tokens). Action channel content: Delayed transcript text, planning text, turn-taking labels, tool calls. Per-chunk action token budget: <= 10 tokens; overflow spills into next chunks."
- Layout of one chunk: `<|user_audio_begin|> U U <|user_audio_end|> <|assistant_audio_begin|> T A A A A <|assistant_audio_end|> <action text> <|action_end|>`. "Within a chunk, the three channels are interleaved into a single token stream consumed by the LLM backbone."
- Silence/idle: "Whenever the chunk has nothing to say, T is predicted as a special anchor token (<vad_silence> or <tts_pad>) and the four A tokens are predicted as the corresponding silence audio codes. The <|action_end|> marker terminates the chunk regardless of whether any action text was emitted, which keeps every chunk strictly aligned to the 160 ms clock."
- Budget rule: "Real-time full-duplex interaction requires the per-chunk decoding cost of the model to fit inside one 160 ms chunk on the actual inference hardware. After the assistant TA4 unit is paid for, the autoregressive decoding throughput of a 7B-scale backbone on mainstream inference accelerators leaves room for only a small number of action-channel tokens per chunk. We therefore cap the action channel at 10 text tokens per chunk ... This bound is a deployment budget, not an architectural constraint, and can be re-tuned per accelerator without retraining."
- FIFO spill (Sec. 3.3): "Within a chunk. If two or more actions are triggered in the same chunk, they are serialized in trigger-time order ... Across chunks. If an action's planning text plus tool-call body exceeds the per-chunk <= 10-token budget, the surplus tokens spill into the action segments of the following chunks. Any later-triggered action waits in the queue until the in-flight action has fully drained ... it never preempts an earlier action, and never breaks an open <|toolcall_begin|> ... <|toolcall_end|> block." "Because the assistant TA4 channel has its own per-chunk token budget, this FIFO queue on the action channel never blocks assistant speech".
- Delay line: user-channel ASR "emitted on the action channel with a fixed lag of 2 chunks (320 ms)"; assistant-channel ASR aligned to playback time.
- Results (DuplexSLA-Bench, 2,100 cases, context-prefill): normal 96.00 % / 0.27 s, pause 93.33 % / 0.27 s, interrupt 99.33 % / 0.40 s, backchannel 98.33 % / 0.32 s; tool calling 85.56 % at 0.64 s average delay, "~4x lower tool-call delay" than ASR+LLM cascade.
- Data: CPT ~500k h audio (duplex dialogue ~320k h, 2 x 90k h ASR) + 1.92M text samples; post-training ~50k h (36k h interrupt/backchannel/pause, 14k h tool calls). GPU/latency per chunk not given.

## 3. Moshi (Kyutai, 2024)

- URLs: https://arxiv.org/abs/2410.00037 ; https://arxiv.org/html/2410.00037v2 (CC BY-NC-SA 4.0 on the arXiv page); PDF text-extracted.
- Streams: K = 2Q+1 = 17 per 12.5 Hz frame: "V_{s,1} = W_s aligned text tokens. V_{s,2} = A_{s,1} semantic tokens of Moshi. V_{s,1+q} = A_{s-tau,q} delayed acoustic tok. of Moshi. V_{s,1+Q+1} = A'_{s,1} semantic tokens of other. V_{s,1+Q+q} = A'_{s-tau,q} delayed acoustic tok. of other". Temporal Transformer 7B (Helium: 32 layers, 4096, 32 heads); Depth Transformer "6 layers, a dimension of 1024, 16 attention heads" with per-index linear weights.
- Mimi: 24 kHz -> 12.5 Hz, 80 ms frame, Q = 8 quantizers x 2048, 1.1 kbps.
- Text/audio alignment (Inner Monologue): "English speech can be represented with around 3 to 4 text tokens per second." Padding: "For each word i and its start index t_i, we update W as {W_{t_i-1} <- EPAD, W_{t_i+j} <- w_{i,j}}"; "In English conversational speech, we observe that padding tokens represent about 65% of the tokens." Forcing an EPAD "will make Moshi start talking immediately."
- Delays (Table 1): pretraining acoustic delay 2, text delay +/-0.6 s (randomized); fine-tuning acoustic delay 1, text delay 0. "we pretrain Moshi with an acoustic delay of 2 and finetune it with an acoustic delay of 1, for a theoretical latency of 160ms." Table 6: delay pattern [0,2,2,2,2,2,2,2] + RQ-Transformer perplexity 36.8 vs [0,1,...,7] 40.3 vs [0,2,...] without RQ 135.4.
- ASR/TTS by delay: "By setting the audio ahead of the text, the content of the text will be dictated by what audio has been sampled ... one obtain a streaming Automatic Speech Recognition model ... by changing the text delay so that the text is ahead of the audio tokens ... one obtain a streaming Text-To-Speech model." Appendix: ASR "The text is delayed by 2 seconds, and we use an acoustic token delay tau = 2"; TTS "The audio is delayed by 2 seconds".
- Silence: "When the user speaks and Moshi stays silent, the corresponding audio tokens for Moshi's stream decode into 'natural silence' ... Moshi's text stream will be filled with PAD tokens."
- Latency: "theoretical latency of 160 ms, 200ms in practice" (L4). Data: 7M h audio, Fisher 2000 h, 170 h natural/scripted, >20k h synthetic; H100 FSDP.

## 4. Hibiki (Kyutai, ICML 2025)

- URL: https://arxiv.org/html/2502.03382 (CC BY-NC-SA 4.0); code github.com/kyutai-labs/hibiki.
- Multistream at 12.5 Hz: per frame concatenation of target and source audio tokens (up to 16 quantizers per stream) plus target text (Inner Monologue). Temporal Transformer 2.2B (24 layers, 20 heads, local attention over 500 tokens, 40 s context); Depth Transformer 1.1B (6 layers/codebook, 1024) or distilled 449M (4 layers/codebook). Hibiki 2.7B; Hibiki-M 1.7B "remains faster than real-time" on iPhone 16 Pro; 320 sequences in parallel faster than real-time on H100.
- Delays: acoustic delay of 2 time steps (tau(A)_{t,q} = A_{t-2,q} for q >= 2); target "to lag by at least 2 seconds compared to the contextual alignment", where the contextual alignment is a_j^ctx = argmax_i [log p_{j,i} - log p_{j,i-1}] computed with MADLAD-3B.
- Results: ASR-BLEU 39.2 (short-form) vs Seamless 37.0; 27.5 long-form vs 25.4; speaker similarity 0.41/0.48; naturalness MOS 3.73 +/- 0.09 vs 2.18; LAAL 5.0 s long-form. Data ~40K h per language, 900 h synthetic aligned set.

## 5. Delayed Streams Modeling (Kyutai, Sept 2025)

- URLs: https://arxiv.org/abs/2509.08753 ; https://arxiv.org/html/2509.08753v2 (CC BY-NC-SA 4.0); code github.com/kyutai-labs/delayed-streams-modeling.
- Abstract: "DSM instead models already time-aligned streams with a decoder-only language model. By moving the alignment to a pre-processing step, and introducing appropriate delays between streams, DSM provides streaming inference of arbitrary output sequences ... ASR corresponds to the text stream being delayed, while the opposite gives a text-to-speech (TTS) model."
- Text stream uses "PAD (indicating the absence of words at this time) and WORD (indicating the start of a new word)" on the 12.5 Hz grid.
- STT: delays 0.25-4 s (variable-delay conditioning), default 2.5 s, latency "~300ms around its target delay"; 6.4 % WER short-form (9 sets), 7.9 % long-form; 2.6B backbone (2048 dim, 48 layers) and 300M variant. Fig. 4: WER ~7 % at 0.25 s -> ~5.5 % at 4 s delay. TTS: "a stream delay of 1.28s (or 16 steps)" audio behind text; 150 ms latency at batch 1, 380/403 ms at batch 32/64; 1.8B (1B backbone + 0.8B RQ sampler).
- Extra control stream: "We add an extra stream to the TTS outputs, whose goal is to predict whether the next input text token will be a WORD token or not" (plus a lookahead text stream with l=2). Trade-off statement: "There is a trade-off between the level of independence of Y_t with X_{>t+tau}, and the latency of the method."

## 6. RT-H: Action Hierarchies Using Language (RSS 2024)

- URLs: https://arxiv.org/abs/2403.01823 ; https://arxiv.org/html/2403.01823.
- Single PaLI-X 55B VLM, two queries per step: language-motion query, then action query conditioned on the language motion. ">2500 language motions" auto-labelled from proprioception ("move arm forward", "rotate arm right", "close gripper").
- The rate trick: "this process doubles inference time since the two queries must be run sequentially at each time step ... We train just the language motion query in RT-H to predict the skill one step into the future. Then at test time, we query the action using the inferred language motion of the previous time step, while also predicting the language motion for the next time step. This enables us to batch the queries and thus achieve nearly identical querying lag as RT-2."
- Intervention: the human types "a new language motion correction on the keyboard or use hotkeys ... This new language motion will directly be passed into the action query". Learning from corrections updates only the language-motion query.
- Numbers: "RT-H outperforms RT-2 by 15% on average" on 8 tasks (Diverse+Kitchen, 100K demos); intervention "60-70% improvement on the harder precise tasks". No latency in ms; no code.

## 7. pi0.5 (Physical Intelligence, 2025)

- URL: https://arxiv.org/html/2504.16054 (arXiv perpetual license; blog pi.website/blog/pi05).
- "At inference time, the model first produces a high-level subtask for the robot to perform and then, conditioned on this subtask, predicts the low-level actions via the action expert." "the high-level inference process still runs at a lower frequency than low-level action inference" -- the value is not stated. Control "50 Hz (with action chunking)", 10 denoising steps.
- Pre-training: "all tasks, including tasks with robot actions, are represented with discrete tokens" (FAST); post-training adds the flow action expert with loss H(...) + alpha ||...||^2, alpha = 10. "Image patch, textual prompt, and continuous action tokens use bidirectional attention"; "the different action representations do not attend to each other". 280k + 80k steps; ~400 h mobile-manipulator data over ~100 homes; tasks 2-5 min; unseen-home language-following ~60-70 % in-distribution, ~40-50 % OOD (Fig. 9).

## 8. SmolVLA and the LeRobot async stack (2025)

- URLs: https://arxiv.org/html/2506.01844 ; https://huggingface.co/blog/async-robot-inference.
- 450M params (~100M action expert; first 16 LLM layers); flow matching 10 steps; chunk n = 50. "A RobotClient sends an observation o_t to a PolicyServer, receiving an action chunk A_t once inference is complete"; new inference triggered when |A_t|/n < g; "The updated queue A_t is obtained aggregating queues on the overlapping timesteps"; near-duplicate observations (joint-space distance < eps) are not sent. Blog: "g~0.7" recommended (start g = 0.5); aggregators "Replace" or "Weighted blend"; "~100ms---~3 frames at 30fps using an ACT model on a 2021 MacBook Pro"; "sub-100ms round-trip latency" hosting SmolVLA on an RTX 4090; "~2x speedup in task completion time".
- Paper: async "completes the task in 9.7 seconds, compared to 13.75 seconds in the synchronous setting (~30% faster)"; 19 vs 9 pick-and-place cycles in fixed time. LIBERO 87.3 %; real SO100 78.3 %; ~30k GPU hours.

## 9. Real-Time Chunking (PI, NeurIPS 2025)

- URL: https://arxiv.org/html/2506.07339 (CC BY 4.0; openpi).
- "d := floor(delta/dt)" inference delay in controller steps; first d actions of the new chunk frozen to the committed ones, remainder inpainted by guidance with weight 1 on the frozen prefix, exponentially decaying over the overlap, 0 on the last s actions.
- pi0.5: H = 50 at 50 Hz (dt = 20 ms, 1 s lookahead); base 76 ms on RTX 4090, RTC +21 ms (97 ms); remote baseline d~6; injected +100/+200 ms -> d~11/16.
- Results: Kinetix 12 tasks -- RTC "outperforms all baselines" as delay grows; 6 real bimanual tasks (match lighting) -- "RTC is completely robust to injected delay, showing no degradation, whereas synchronous degrades linearly." Temporal ensembling "poor actions"; naive async "jerky, out-of-distribution" transitions; bidirectional decoding 2.3x latency.

## 10. Understanding Asynchronous Inference Methods for VLAs (May 2026)

- URL: https://arxiv.org/html/2605.08168v1 (CC BY 4.0; code github.com/TheAyos/async-vla-inference).
- Four methods: IT-RTC (inference-time inpainting), TT-RTC ("training-time delay simulation that conditions the policy on action prefixes so it learns to predict only the non-stale postfix, with no inference overhead"), VLASH ("estimates the robot's future state at execution time using known previous actions"), A2C2 ("a lightweight correction head that runs at every control step, producing residual adjustments to the base policy's stale actions").
- Setup: 50 Hz (dt = 20 ms); Kinetix H in {16, 30}, d up to 15 (300 ms); LIBERO with SmolVLA, H = 50, d up to 20; "Cloud inference over 4G reaches d=13; edge server on 4G reaches d=3".
- Findings: Kinetix H=16 -- A2C2 ">90% even at d=8", naive "<40%"; LIBERO -- A2C2 "takes the lead ... from d=4 onwards and holds a ~10-point margin", IT-RTC "collapses essentially to the naive baseline beyond d=8", VLASH "~55-56% through d=20". Wall clock (RTX 3090): IT-RTC 469.7 ms (+15.9 %), TT-RTC 402.7 ms, A2C2 412.4 ms (+1.8 %). Guidance: "if retraining is infeasible and the expected delay is low, IT-RTC is a sensible drop-in; if fine-tuning is possible and chunks are short, TT-RTC offers a near-free fix; on long-chunk VLA settings, A2C2 is the most reliable choice".

## 11. Real-Time Execution with Autoregressive Policies (REALFAST, June 2026)

- URL: https://arxiv.org/html/2606.13355v1 (CC BY 4.0; page oddqueue.github.io/realfast).
- Re-tokenizes the horizon into m-step chunks (m = 4 on LIBERO, m = 6 on DROID, "400ms") so few tokens need decoding; constrained (DP) decoding guarantees detokenizable sequences within a latency bound: "183 ms" (LIBERO, B = 11) / "302 ms" (DROID, B = 20); best-of-N multi-trajectory decoding ~324 ms total sharing KV cache. Prefix A_Q[0:m] is fed as a non-modifiable conditioning prefix (RTC-like freeze, but re-run whenever an observation arrives). Base pi0-FAST with FAST+ tokens, RTX 4090. LIBERO 95.7 % (pi0+RTC 94.7, pi0.5+RTC 96.9); DROID: surpasses sync pi0-FAST, comparable to pi0.5.

## 12. Fast-in-Slow VLA (NeurIPS 2025)

- URL: https://arxiv.org/html/2506.01953 (code github.com/CHEN-H01/Fast-in-Slow).
- "we repurpose the final few blocks of the LLM for System 1" (LLaMA2-7B; "two blocks" best); System 2 "latent features from an intermediate block of the LLM" condition System 1, which also takes high-frequency images, point cloud and state. Frequency ratio System 2 : System 1 ablated 1:1 .. 1:8; "when the ratio is 1:4, FiS-VLA excels the best performance."
- "FiS-VLA achieves a 117.7 Hz control frequency on an NVIDIA 4090 GPU with action chunk set to eight" (21.9 Hz at chunk 1; "2x faster than CogACT (9.8 Hz)"). RLBench 69 % avg (CogACT +8, pi0 +14 pts); real: Agilex 68 % vs pi0 59, AlphaBot 74 % vs 61. 860K trajectories; 8 A800, 300 epochs.

## 13. UniFS (June 2026)

- URL: https://arxiv.org/html/2606.22794 (CC BY 4.0; code github.com/linsun449/UniFS).
- Frequency dilemma: "large update gaps cause semantic drift from stale context, while small gaps erode the intended computational savings." One Qwen2.5-0.5B VLM stratified into 5 layer groups with timescales [1, 2, 4, 8, 16]; group k recomputes "if t = 0 (mod n_k), otherwise reuses cached features"; the action expert (24 layers) cross-attends all groups with latent-vector inversion (noisy proposals see deep/slow features, refined outputs see shallow/fast). Latency 17.8 ms avg (12.3-32.6) vs 36.5 ms VLA-Adapter; LIBERO 98.3 % (Spatial 99.6, Object 99.6, Goal 98.1, Long 95.6).

## 14. HiRT (CoRL 2024)

- URL: https://arxiv.org/html/2410.05273 (CC BY 4.0).
- InstructBLIP-7B produces a latent at low rate; a 35M (sim) / 150M (real) vision policy conditioned by FiLM/cross-attention runs at high rate reading "the most recent latent variable from the cache". Training: "HiRT randomly selects a step from the past observation contexts" so the policy tolerates stale latents. 9.8 Hz vs Vanilla-VLA 4.1 Hz (RT-1 20.1 Hz at 55 %); dynamic tasks 48 % -> 75 % (seen 80 %, unseen 70 %).

## 15. GR00T N1 (NVIDIA, 2025) -- rate facts only

- URL: https://arxiv.org/html/2503.14734v1 (CC BY 4.0). "The System 2 reasoning module is a pre-trained Vision-Language Model (VLM) that runs at 10Hz on an NVIDIA L40 GPU." "It generates closed-loop motor actions at a higher frequency (120Hz)." H = 16, K = 4 denoising steps; "we use the representations from the 12th layer"; 2.2B total / 1.34B VLM; "63.9ms on an L40 GPU using bf16" per 16-action chunk. The 10 Hz -> 120 Hz bridging is not spelled out.

## 16. TIDAL (Jan 2026) -- the only Orin number in this set

- URL: https://arxiv.org/html/2601.14945 (CC BY-SA 4.0).
- GR00T-N1.5-3B on "NVIDIA Jetson AGX Orin (Max-N mode, TensorRT)": macro loop extracts intent once per 16-step horizon; micro loop does "a single-step Euler integration to generate the action chunk", executes N = 4 steps, discards the rest, repeats with fresh fused proprio state (K = 4 latency stages). "approximately 9 Hz control updates on edge hardware (vs. approximately 2.4 Hz baselines)", "~110 ms" vs "~400 ms" per cycle. Dynamic interception 0.61/0.36 vs 0.31/0.16; static RoboCasa 50.94 % vs 59.25 % (a cost); no real-robot results yet.

## 17. DuoCore-FS (Astribot, Dec 2025)

- URL: https://arxiv.org/html/2512.20188v1 (closed: "provided to commercial users by Astribot").
- Slow VLM (PaliGemma-3B / Qwen2.5-VL) "refreshes B_t at a low rate of 1-3 Hz, while the fast system fetch[es] the latest representations at 25-30 Hz" from a bridge buffer; 32.3 Hz vs pi0 12.5 Hz; success 90 % vs 85 % ID, 50 % vs 10 % OOD, language following 42.9 % vs 14.3 %; 1,780 demos (10.22 h), 24 H100.

## 18. OneTwoVLA (ICLR 2026)

- URL: https://arxiv.org/html/2505.11917 (CC BY 4.0).
- Tokens `[BOR]` (begin reasoning) / `[BOA]` (begin action). When acting the model attends to "current image observations ... the reference images from the latest reasoning timestep ... the language instruction, and the latest reasoning content R." Reasoning fires only at critical moments; "OneTwoVLA achieves total times that match those of a flat VLA without language reasoning (pi0)". Human input: "any interaction text will be consistently added to the language instruction in subsequent steps." Long-horizon 87 % vs pi0 30 %; human interaction 20/20; visual grounding 78 % vs 5 %; 16,000 synthetic reasoning samples (Gemini 2.5 Pro + FLUX.1-dev).

## 19. Fast ECoT (2025)

- URL: https://arxiv.org/html/2506.07639v1 (CC BY 4.0). ECoT stages "Task, Plan, Subtask, Move Command, Gripper Command, and Visible Objects"; gripper < 20 tokens, object grounding > 120. Baseline 4997 +/- 691 ms/step on RTX 4090 (OpenVLA-7B ECoT). Planning "average update ratio of only 8.4%, meaning 91.6% of its reasoning content is unchanged" -> cache + async scheduler using stale R_c: 686 +/- 412 ms LIBERO (~7x), 716 +/- 529 ms real (7.5x), 70 % real success.

## 20. Qwen2.5-Omni and Qwen3-Omni (2025)

- URLs: https://arxiv.org/html/2503.20215 ; https://arxiv.org/html/2509.17765v1 (Apache 2.0).
- Qwen2.5-Omni: "time-interleaving method, which segments the representation in the video with audio into chunks every 2 seconds according to the actual time"; audio frames "roughly correspond to a 40ms segment"; "one temporal ID corresponds to 40ms" (TMRoPE); audio encoder attends "in blocks of 2 seconds"; Talker is "a dual-track autoregressive Transformer Decoder" fed Thinker hidden states; DiT vocoder receptive field "4 blocks, including a lookback of 2 blocks and a lookahead of 1 block".
- Qwen3-Omni (30B-A3B, Talker 3B-A0.3B): AuT "reducing the token rate to 12.5 Hz"; codec 12.5 Hz with an MTP module for residual codebooks; "80 ms per ID" temporal resolution; Talker "no longer consumes the Thinker's high-level text representations and conditions only on audio and visual multimodal features"; "when Thinker completes prefilling the current chunk, its output high-level representations are immediately used to prefill the Talker's current chunk asynchronously"; first-packet 234 ms (audio) / 547 ms (audio-video).

## 21. MiniCPM-o 2.6 and 4.5 (2025-2026)

- URLs: https://huggingface.co/openbmb/MiniCPM-o-2_6 (Apache-2.0; SigLip-400M + Whisper-medium-300M + ChatTTS-200M + Qwen2.5-7B = 8B; "time-division multiplexing (TDM) mechanism ... divides parallel omni-modality streams into sequential info within small periodic time slices"); https://arxiv.org/html/2604.27393 (MiniCPM-o 4.5, 9B on Qwen3-8B).
- 4.5: "Omni-Flow partitions the continuous interaction into fine-grained time windows of duration t"; "1.0 s provides the best balance"; 0.2 s / 0.1 s "caused significant performance degradation". Per window g_k = [v^k ; a^k ; o^k]: "Within each chunk, the model first processes newly arrived perceptual tokens and then generates output tokens." Audio in: Whisper 50 tok/s compressed 5x to "10 audio tokens per second"; text out "3-4 decoding steps per second (i.e., human speech speed)"; speech ~25 tok/s handled by a light decoder; `[listen]` token when silent. RTF 0.27 on RTX 4090 BF16 (0.21 INT4); < 12 GB RAM; LiveSports-3K-CC win rate 54.4.

## 22. Chain-of-Action (NeurIPS 2025)

- URL: https://arxiv.org/html/2506.09990. "the first token corresponds to a stable keyframe action that encodes the task-specific goals, and subsequent action tokens are generated autoregressively" backward toward the current state; continuous action tokens; dynamic stopping; MTP with 5 heads; reverse temporal ensemble. No language tokens. "The neural policy operates at 10Hz on a laptop with a 4070 GPU"; "PD controller runs locally on the robot at 1000Hz". RLBench-60: 0.552 vs ACT 0.389 vs DP 0.326; real 8 tasks 0.613 vs 0.463. Small model (ResNet-18 + 4-layer enc / 7-layer dec, d = 512).

## 23. MINT (Feb 2026) and tau0-VLA (Aug 2026)

- MINT https://arxiv.org/html/2602.08602: next-scale AR action tokens over scales "[1,2,4]" or "[1,2,3,4]", intent token first, "all distributions over l_k tokens in s_k will be generated in parallel, conditioned on the prefix token maps"; PaliGemma-2.6B + ~300M expert; LIBERO-Long 97.8 % vs pi0-FAST 60.2 %; no latency reported.
- tau0-VLA https://arxiv.org/html/2608.16885: high level emits a "language subtask", low level an H-step chunk; "the high-level and low-level policies are pipelined asynchronously"; world-model beam search when uncertain; 40,115 h robot data; Make Milk Tea 5/10 vs pi0.5 3/10 (7/10 with test-time compute). No ms.

---

## 24. The six rate-mismatch mechanisms seen in the field (with who uses which)

1. **Fixed slots + pad/silence tokens inside a block.** ELLSA (8 text / `<silence>`, dummy action tokens, 1 s), DuplexSLA (`<vad_silence>`/`<tts_pad>` anchor, silence audio codes, mandatory `<|action_end|>`, 160 ms), Moshi/DSM (PAD/EPAD, 65 % of text slots), MiniCPM-o 4.5 (`[listen]`, 1 s). Cost: pad tokens are decoded and attended like any other; benefit: the sequence position is the clock.
2. **Delay lines between streams.** Moshi acoustic delay 1-2 frames (80-160 ms), text delay 0 for dialogue, 2 s for ASR/TTS; DSM 0.25-4 s STT (2.5 s default), 1.28 s TTS; Hibiki >= 2 s; DuplexSLA transcripts +2 chunks (320 ms). Delay buys context at the price of latency; DSM quantifies WER 7 % -> 5.5 % from 0.25 s to 4 s.
3. **Hold-last / cached slow features.** GR00T (10 -> 120 Hz), HiRT (train with random staleness), FiS (1:4 best of 1:1..1:8), UniFS ([1,2,4,8,16] layer groups), DuoCore-FS (1-3 Hz -> 25-30 Hz buffer), Fast ECoT (91.6 % of plan text unchanged), OneTwoVLA (latest reasoning stays in context), pi0.5 (subtask at lower, unstated rate). UniFS names the failure mode: "semantic drift from stale context".
4. **Spill/FIFO queues for a rate-limited text channel.** DuplexSLA only: <= 10 tokens/chunk, surplus spills, later actions wait, tool-call JSON never split.
5. **Predict-ahead to batch the slow lane with the fast lane.** RT-H predicts the next step's language motion so both queries run in one batch.
6. **Frozen-prefix asynchronous chunk execution.** RTC (d = 6-16 at 50 Hz, no degradation), REALFAST (m = 4 tokens, 183-302 ms bound), SmolVLA (g ~ 0.7 refill), A2C2 per-step corrections (best beyond d = 4, +1.8 % compute), TIDAL (N = 4 of H = 16 executed per single Euler step, ~9 Hz on Orin).

Block-size evidence: ELLSA 1 s vs 0.48 s (action expert LONG 94.0 -> 81.0 %; 0.48 chosen because 25 Hz speech cannot make 0.5 s); MiniCPM-o 4.5 1.0 s best, 0.2/0.1 s degrade; DuplexSLA 160 ms (matches Freeze-Omni's 0.16 s that ELLSA contrasts with); FiS 1:4; Qwen2.5-Omni 2 s interleave chunks.

---

## 25. What this means for Parcel's Model A / Model B

**A. Pick a block that is an integer multiple of every native rate, and put the clock in the token layout.** 10 Hz act tokens (100 ms), 12.5 Hz Mimi-style audio frames (80 ms) and a ~1 Hz plan lane have LCM 400 ms: one 400 ms block = 4 act tokens + 5 audio frames + a capped plan slot; 800 ms = 8 + 10; 2 s = 20 + 25. ELLSA had to use 0.48 s because 25 Hz speech "cannot support a 0.5 s interval" -- the same arithmetic bites a 12.5 Hz stream at 1 s (12.5 frames). A DuplexSLA-style layout (`<act x4> <audio x5> <plan <=k> <|block_end|>`) with a mandatory end marker makes the sequence index the clock and lets the plan lane be empty most blocks.

**B. Fill, do not skip.** Every system that runs one backbone over mixed rates emits an explicit idle token (ELLSA `<silence>` + dummy actions, DuplexSLA `<vad_silence>`/`<tts_pad>`, Moshi PAD at 65 %, MiniCPM-o `[listen]`). For Model A the plan lane should emit a `<hold>` token each block rather than being absent, so the 10 Hz loop never waits on the 1 Hz lane; OneTwoVLA's `[BOR]/[BOA]` shows the alternative (event-triggered reasoning) costs no extra wall time only because reasoning is rare.

**C. Cap the slow lane by decode budget, and spill.** DuplexSLA's rule is the right one for an Orin: "the per-chunk decoding cost of the model to fit inside one 160 ms chunk on the actual inference hardware ... cap the action channel at 10 text tokens per chunk ... a deployment budget, not an architectural constraint". For Parcel: measure tokens/s of the chosen backbone on the Orin, subtract the 4 (or 8) act tokens per block, and cap plan tokens at what remains with margin; overflow spills FIFO into later blocks without ever splitting a structured receipt.

**D. Do not expect an 8B-class interleaved model to hit the block on Orin.** ELLSA (two 8B experts) needs 786-854 ms per 1 s block on an A100; DuplexSLA is 7B on unstated accelerators; the only Orin measurement in this set is TIDAL, where a 3B GR00T-N1.5 reaches ~9 Hz only by executing 4 of 16 actions per single Euler step (and pays 59.3 -> 50.9 % on static tasks). UniFS (0.5B VLM, 17.8 ms on a data-center GPU) and SmolVLA (450M) are the size class that has any chance of 10 Hz on Orin. This is consistent with the first sweep's finding that no language model runs at 10 Hz on a robot: the 10 Hz lane must be act tokens from a small head, with language on the slow lane.

**E. Use delay lines deliberately, in both directions.** Moshi/DSM show that shifting one stream by a fixed number of frames converts the same model between "audio dictates text" and "text dictates audio". For Model A, delay the plan lane by one block (RT-H's predict-one-step-ahead) so the plan for block t+1 is decoded during block t and act tokens never stall; for Model B's receipts, a 2-chunk (320 ms) delayed transcript channel a la DuplexSLA is the precedent for time-stamped narration text that never blocks speech.

**F. Hold-last is the default for stale plans, but train for the staleness.** HiRT trains the fast policy on randomly stale latents; FiS finds 1:4 optimal and 1:8 worse; UniFS names the drift. If Model A's plan lane refreshes every ~10 act tokens, train with randomized 5-20 token staleness and measure drift, do not assume it.

**G. Model B steering injection has a direct precedent in DuplexSLA's action channel and OneTwoVLA's instruction append.** DuplexSLA emits interrupt/backchannel/response labels plus tool JSON on the action channel at 0.27-0.40 s while speech continues; OneTwoVLA appends "any interaction text ... to the language instruction in subsequent steps"; RT-H accepts a typed language motion that "will directly be passed into the action query". For Parcel: owner speech -> a short steering string injected into the next block's plan slot (not into the act tokens), with ELLSA's "Action Cancelled" barge-in (94.3 %) as the safety path.

**H. Async execution of act chunks: adopt a frozen prefix and measure d.** At 10 Hz a 100 ms inference delay is d = 1; RTC shows no degradation up to d = 16 at 50 Hz (320 ms) with a 21 ms overhead; the 2026 survey says beyond d = 4 a per-step correction head (A2C2, +1.8 % compute) beats inpainting, and that IT-RTC collapses beyond d = 8. With a Go2 gait controller consuming velocity commands, Parcel's d will be set by the Orin decode time of one block; REALFAST's bound (183-302 ms for m = 4-6 tokens on a 4090) is the closest AR-token analogue.

**I. Audio at 12.5 Hz can be a parallel stream, not interleaved tokens.** Moshi/Hibiki/DSM decode 17 streams per frame with a small Depth Transformer rather than 17x the sequence length; Qwen3-Omni runs a separate Talker prefilled asynchronously per chunk; MiniCPM-o 4.5 keeps 25 tok/s speech out of the LLM entirely. Because Parcel's voice is the hosted Realtime model, Model A should ingest at most 12.5 Hz *features* (5 per 400 ms block) or none, and never generate audio tokens.

**J. Licenses.** Trainable references: ELLSA (Apache-2.0 code/weights), SmolVLA and LeRobot async (open), UniFS (CC BY 4.0, code), RTC/openpi (CC BY 4.0 paper), async-vla-inference (code), GR00T N1 (CC BY 4.0), TIDAL (CC BY-SA 4.0). Non-commercial: Moshi, Hibiki, DSM (CC BY-NC-SA). DuplexSLA weights not yet released (MIT code badge). Closed: DuoCore-FS, RT-H, pi0.5.

---

## 26. Not found / open

- No paper interleaves *three* rates (10 Hz act, ~1 Hz plan, 12.5 Hz audio) in one sequence on an embedded GPU; the closest are ELLSA (5 Hz speech, 1 Hz text/vision, ~10 Hz FAST actions, 1 s block, A100) and DuplexSLA (12.5 Hz user feats, 25 Hz assistant audio, 6.25 Hz text anchor, <= 62.5 tok/s action text, 160 ms, 7B).
- pi0.5 does not state the subtask refresh rate; GR00T N1 does not state how the 10 Hz VLM output is held across 120 Hz steps.
- No ablation anywhere compares "pad token every block" vs "event-triggered slow lane" at equal compute; ELLSA (fixed) and OneTwoVLA (event) are the two poles.
- Chain-of-Action and MINT order action tokens coarse-to-fine *within* a chunk (goal/intent first) but carry no language tokens; combining a MINT-style intent token with a DuplexSLA-style capped plan slot is untested.
