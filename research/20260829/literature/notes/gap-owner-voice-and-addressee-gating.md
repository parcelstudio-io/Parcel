# Gap note: on-device owner-voice verification and robot-directed-speech (addressee) gating

Literature note, 2026-08-29. Topic: what a household robot (Parcel: Go2 + Jetson AGX Orin 64 GB +
XVF3800 mic array + camera) can do *on device* to (a) verify that the person speaking is the owner
and (b) decide that an utterance is addressed to the robot at all, without a wake word — and how
voice assistants gate barge-in on those two signals. Covers ECAPA-TDNN / TitaNet / WavLM / CAM++ /
ReDimNet speaker verification (EER, size, CPU cost, licenses), far-field and mobile-robot
degradation, device-directed speech detection (DDSD) numbers from Apple / Amazon / Google /
Attention Labs, multi-party addressee estimation in HRI, personal (target-speaker) VAD, and the
addressee/barge-in behaviour of the hosted voice APIs.

Every source below was fetched and read on 2026-08-29. Numbers are quoted from the page as read.
Vendor pages are flagged `[vendor]`. Nothing is cited from memory. One deliberate gap is stated up
front: **no primary source measured ECAPA-TDNN / TitaNet / CAM++ latency on a Jetson**; the closest
measurements are on x86 CPU, ARM Cortex-A72 and a smartphone, and are listed as proxies (section 0
and section 6).

---

## 0. Headline numbers (one screen)

| Quantity | Value | Source |
|---|---|---|
| Wake-word-free, audio-only device-addressed detection on ARM Cortex-A72 | F1 0.86 (P 0.89 / R 0.83), false-trigger 2.1 % (7.8 % with TV audio), median 38 ms / p95 51 ms; ~520 K params, < 20 MB; +camera -> F1 0.95, median 105 ms | SAS (S1) |
| Best published DDSD EER, ASR-text + audio + decoder signals into an LLM | 7.45–7.95 % EER (GPT-2 124 M + Whisper/CLAP), 6.53 % with GPT-2 1.5 B + LoRA; text-only 12.7 %, audio-only 10.98 % | Apple (S2) |
| DDSD with 7 B LLMs, ~80 k multimodal examples | text-only 12.9–13.0 %, audio-only 9.0–10.8 %, multimodal 8.2–9.5 % EER; 126 h train, 35 h eval | Apple (S3) |
| Follow-up (no wake word) DDSD with dialogue context + ASR n-best | EER 10.5 % -> 7.9 %; FAR @ 10 % FRR 11.4 % -> 4.8 %; Vicuna-7B + 4.1 M LoRA params; 245 k segments / 1.3 k participants | Apple (S4) |
| Acoustic-only DDSD model deployable without ASR | ~4.8 M params, 6 self-attention layers, 40-D mel @ 100 fps; EER 18.4 % raw -> 6.2 % distilled; ASR-lattice model 4.8 %; ensemble 4.0 % | Apple (S5) |
| Prosody as a DDSD feature | up to 8.5 % lower FA at a fixed operating point; modality dropout +7.4 % FA with missing modalities | Apple (S6) |
| Classic acoustic / decoder / 1-best fusion (Alexa 2018) | acoustic 10.9 %, 1-best 20.1 %, decoder 9.3 %, combined 5.2 % EER | Amazon (S7) |
| Alexa Conversation Mode (camera + mic, on-device fusion) | visual head-orientation model cut FRR ~80 %; adding audio cut FRR a further 83 %; false wakes from ambient noise -80 %, from Alexa's own responses -42 % | Amazon (S9) |
| Alexa DDSD during device playback (implicit AEC) | 56 % FRR reduction for DDD during playback at fixed FAR; ~10x less compute than neural AEC + KWS | Amazon (S11) |
| Google Look and Talk (Nest Hub Max) | works within 5 ft; 3 phases (presence + Face Match -> gaze -> intent on audio+text); 8 on-device TFLite models; 3,000-participant fairness set; no accuracy published | Google (S12) |
| Hosted voice APIs and addressee | Gemini Live `proactivity.proactive_audio` lets the model "decide not to respond if the content is not relevant" — **2.5 Flash Live preview only, not supported on 3.1 Flash Live**; OpenAI Realtime has server_vad / semantic_vad only, **no addressee gate** | S13, S14 |
| Multi-party social robot (Furhat, 30 participants, 2026) | addressee correct 92.6 % (parallel) / 79.3 % (group); Azure voice ID only 18.4 % (group) / 26.8 % (parallel) correct vs face recognition 80.0 % / 94.7 %; response latency 1.35 s (SD 0.55), up to ~5 s | S15 |
| Addressee estimation from gaze + pose on iCub | 0.8 s / 10-frame window at 12.5 Hz, first estimate < 1 s; F1 "robot" class 67.5 % (dataset) / 71.7 % (live); overall 75.0 % / 75.8 % | S16, S17 |
| LLMs at addressee detection (AMI meetings, 4 speakers) | humans 66.6 % vs Qwen3-14B 51.5 %, Gemini 2.5 Pro 61.4 % (chance 25 %); raw video adds little; α = 0.67 human agreement | S18 |
| Acoustic-only addressee detection (review of 23 studies) | EER 12.63 % (2012) -> 5.48 % (2021); acoustic UAR 82.2 %, acoustic+semantic UAR 92.9 %; energy features most important | S19 |
| Speaker-verification model zoo (VoxCeleb1-O EER, params, license) | ECAPA C=512 6.2 M / 1.01 %; C=1024 14.7 M / 0.87 %; SpeechBrain ECAPA 0.80 % Apache-2.0; TitaNet-S 6.4 M / 1.15 %, -L 25.3 M / 0.68 % (HF card: 23 M / 0.66 %, CC-BY-4.0); CAM++ 7.18 M / 0.73 % (3D-Speaker 0.65 %, Apache-2.0); ReDimNet-B0 1.0 M, 0.43 GMACs / 1.16 %, B2 4.7 M / 0.57 %; WavLM Large 316.6 M / 0.617 % (0.383 % with LMFT+QAC) | S20–S28 |
| Speaker-embedding CPU cost | CAM++ RTF 0.013 vs ECAPA-TDNN 0.033 vs ResNet34 0.032 (single-thread CPU); CAM++ 1.72 GFLOPs vs ECAPA 3.96 G | S24 |
| Speaker embedding per 250 ms chunk on a Xeon Gold 5215 CPU (diart) | pyannote/embedding 57 ms; wespeaker-voxceleb-resnet34-LM 217–218 ms | S29 |
| Far-field SV on a mobile robot (RoboVox, 78 speakers, 1–3 m) | ResNet-34 baseline EER: close-talk ch5 9.29 % -> robot-angle mics 15.63–15.79 % -> in-body mic 18.22 %; multi-channel 15.06 %; DiPCo 5.84 % vs RoboVox 18.22 %; SP Cup 2024 2nd place 6.46 % EER; corpus CC BY-NC-SA 4.0 | S30–S32 |
| Distance / reverberation effect (MFCC system) | EER 2.33 % (RT 0.53 s, near) -> 6 % at 7 m -> 14.66 % at RT 1.5 s / 5 m | S33 |
| Short-context speaker embeddings (ECAPA KD student) | 250 ms context: AssA 46.8 % (teacher) -> 54.8 % (student); 750 ms 63.1 %; whole utterance 65.5 %; 512 vs 1024 channels differ <= 1.7 % | S34 |
| Personal (target-speaker) VAD on device | Personal VAD 2.0: 1.0 MB quantized (vs 5.8 MB), 9.58 MFLOPs; quantized Conformer standard VAD 0.7 MB / 8.77 MFLOPs | S35 |
| Speaker-conditioned barge-in in a full-duplex stack | FireRedChat pVAD (ECAPA-TDNN target embedding + GRU): false barge-in 10.2 % vs LiveKit 33.4 % vs TEN 78.1 %; T90 170 / 140 / 90 ms; EoT acc 94.9–96.0 % | S36 |
| ECAPA SV in a noisy operating room (~70 dB) | EER ~3.1 %; whole ASR+SV framework < 1.3 M params (ASR), "< 200 ms" end-to-end on Jetson Nano / RPi 4B (platform for the SV module not separately stated) | S37 |

---

## 1. Device-directed / device-addressed speech detection (no wake word)

### S1. Attention Labs — "Selective Attention System (SAS): Device-Addressed Speech Detection for Real-Time On-Device Voice AI" (arXiv 2604.08412, 9 Apr 2026)
URL: https://arxiv.org/html/2604.08412
- Three-stage cascade: (1) beamforming front-end; (2) 1-D conv utterance classifier on 64-d log-mel (25 ms / 10 ms) — "approximately 435 K parameters, approximately 520 KB INT8-quantized"; (3) "small causal Transformer over rolling 8-second context window", "approximately 85 K" params. Total "approximately 520 K parameters", runtime footprint "<20 MB". No lexical / transcript input. Optional skeletal + gaze from a lightweight pose model.
- Audio-only at τ = 0.70: F1 0.86, precision 0.89, recall 0.83, false-trigger 2.1 %; TV/media false-trigger 7.8 %; single-mic fallback F1 0.84. Audio+video: F1 0.95 / P 0.97 / R 0.93.
- Ablations: removing the 8-s temporal stage drops F1 to "0.57±0.03" (−38 pts); no beamforming −14; no classifier −21.
- Latency: audio-only "under 55 ms (median 38 ms, p95 51 ms)"; audio+video "under 150 ms (median 105 ms, p95 142 ms)"; baseline hardware "ARM Cortex-A72" (no GPU/NPU); also tested on Raspberry Pi 4 and the Reachy Mini companion robot.
- Data: proprietary 600 h multi-speaker corpus, 60 h held-out test, 1–4 speakers, 28–85 dBA rooms; test mix ~34 % silence / ~58 % person-directed / ~8 % device-directed. "trained weights are not released"; a 5 h subset (SAS-Bench-5h) "may be made available upon reasonable request". English only; internal evaluation "without independent third-party auditing".
- The companion search-snippet framing: "Sequential Device-Addressed Routing (SDAR)" — forward / suppress / abstain, pre-ASR, causal, bounded memory — "more effectively modeled as a sequential routing problem over interaction history than as an utterance-local classification task".
- Relevance: the only 2026 number for wake-word-free addressee detection on ARM-class hardware; the temporal-context stage is the single largest contributor.

### S2. Apple — "A Multimodal Approach to Device-Directed Speech Detection with Large Language Models" (arXiv 2403.14438, ICASSP 2024)
URL: https://arxiv.org/html/2403.14438
- Unimodal (GPT-2 124.4 M): text-only 12.70 % EER; audio-only Whisper 10.98 %; audio-only CLAP 19.13 %; decoder-signals-only 28.09 %.
- Multimodal MM6 (text + audio + decoder signals): 7.95 % (Whisper) / 7.45 % (CLAP), "relative improvements of 27.6% and 61.1% over the corresponding audio-only models" and "34.6% and 38.7%" over text-only. GPT-2 1.5 B + Whisper with LoRA r=64: 6.53 %.
- Data: ≈40 k device-directed (~59 h) + ≈40 k non-directed (~67 h) train; ≈14 k / ≈23 k eval (~35 h; mean 3.0±1.9 s vs 3.7±3.6 s); +≈3 M text-only utterances. Whisper 769 M; CLAP 153 M.
- Relevance: the reference EER floor for "text + acoustics + ASR confidence" without a wake word; note audio-only ≈ 11 %, i.e. the pre-ASR gate alone is not enough.

### S3. Apple — "Multimodal Data and Resource Efficient Device-Directed Speech Detection with Large Foundation Models" (arXiv 2312.03632, Dec 2023)
URL: https://arxiv.org/html/2312.03632
- 7 B Falcon / RedPajama with LoRA (r=8, α=32) and prefix tuning, "80k or less examples".
- Text-only 12.97 % / 12.90 %; audio-only Whisper 10.45 % / 10.78 %; audio-only UAD (≈6 M-param, 256-d specialised encoder) 9.31 % / 8.99 %; all three modalities 8.80 % / 8.23 % (Falcon) and 9.45 % / 8.52 % (RedPajama).
- Train 40,568 directed + 40,062 non-directed (126.19 h); eval 14,396 + 22,958 (35.42 h).
- Key sentence: "low-dimensional specialized audio representations lead to lower EERs than high-dimensional general audio representations" — a 6 M audio encoder beat Whisper-Medium 769 M.

### S4. Apple — "Device-Directed Speech Detection for Follow-up Conversations Using LLMs" (arXiv 2411.00023, Nov 2024)
URL: https://arxiv.org/html/2411.00023
- Follow-up turns after a wake-word turn. "roughly 245k segments" from "~19k audio recordings from 1.3k participants", DD:ND "~1:4", 3.5±3.25 s, 70/10/20 split, no speaker overlap. Vicuna-7B-v1.3 + LoRA "4.1M parameters ... 0.06%" + ~8 k classifier head.
- Table 2 (classifier, at 10 % FRR): follow-up only 1-best EER 10.5 % / FAR 11.4 %; 8-best 9.5 % / 8.3 %; with previous context 1-best 8.5 % / 6.1 %; context + 8-best 7.9 % / 4.8 %. "~20-40% reduction in FAR at 10%FRR".
- Inference on "4 NVIDIA A100 GPUs" — not an on-device model.

### S5. Apple — "Device-Directed Speech Detection: Regularization via Distillation for Weakly-Supervised Models" (arXiv 2203.15975, Interspeech 2022)
URL: https://arxiv.org/html/2203.15975
- Acoustics-only AFTM: "6 self-attention layers (with 4 heads each)", "∼4.8M parameters", "40-D mel-filterbank features" at "100 frames-per-second".
- EER: base AFTM 18.4 % -> distilled AFTM-D 6.2 % (the "66% gain"); LatticeRNN (needs full ASR) 4.8 %; ensemble 4.0 %.
- "can be deployed on devices with low-resource hardware where ASR can not be deployed".

### S6. Apple — "Modality Dropout for Multimodal DDSD using Verbal and Non-Verbal Features" (arXiv 2310.15261, Oct 2023)
URL: https://arxiv.org/abs/2310.15261
- Prosody "improves DDSD performance by upto 8.5% in terms of false acceptance rate (FA) at a given fixed operating point"; modality dropout "improves ... by 7.4% in terms of FA when evaluated with missing modalities".

### S7. Amazon — "Device-directed Utterance Detection" (arXiv 1808.02504, Interspeech 2018)
URL: https://arxiv.org/abs/1808.02504
- Two LSTMs (acoustic; ASR 1-best) + DNN fusion with decoder features. EER: acoustic 10.9 %, 1-best 20.1 %, decoder 9.3 %, combined "44 % relative improvement and a final EER of 5.2 %".

### S8. Amazon Science blog — "How Alexa knows when you're talking to her" (6 May 2020)
URL: https://www.amazon.science/blog/how-alexa-knows-when-youre-talking-to-her
- Follow-Up Mode; adds semantic/syntactic features and previous-utterance context; LSTM+attention EER 9.1 % vs 10.6 % baseline ("14% improvement"); a plain DNN variant 19.2 %.

### S9. Amazon Science blog — "New Alexa feature enables natural, multiparty interactions" (Conversation Mode, 18 Nov 2021)
URL: https://www.amazon.science/blog/new-alexa-feature-enables-natural-multiparty-interactions
- "Conversation Mode measures visual device directedness by estimating the head orientation of each person in the device's field of view"; audio branch is a separable CNN; on-device fusion.
- Visual-only model "reduced the false-rejection rate (FRR) for visual device directedness detection by almost 80%"; adding audio "reduced the FRR by 83% relative to a model that used visual data only"; "80% reduction in false wakes due to ambient noise and a 42% reduction in false wakes triggered by Alexa's own responses". Entered/exited by voice command or inactivity timeout.

### S10. Amazon Science blog — "New Alexa features: Natural turn-taking" (24 Sep 2020)
URL: https://www.amazon.science/blog/change-to-alexa-wake-word-process-adds-natural-turn-taking
- "on-device algorithms process images from the camera, inferring from speakers' body positions whether they are likely to be addressing Alexa"; vision output "combined with the output of Alexa's existing acoustic algorithm ... fed to an on-device fusion model". Barge-in handled with timestamps to find the referent. No numbers.

### S11. Amazon — "Implicit Acoustic Echo Cancellation for KWS and Device-Directed Speech Detection" (arXiv 2111.10639)
URL: https://arxiv.org/abs/2111.10639
- Network consumes the playback reference channel directly; "56% reduction in false-reject rate for the DDD task during device playback conditions"; KWS "comparable or superior" to neural AEC + KWS at "an order of magnitude less computational requirements".

### S12. Google Research blog — "Look and Talk: Natural Conversations with Google Assistant" (27 Jul 2022)
URL: https://research.google/blog/look-and-talk-natural-conversations-with-google-assistant/
- "Once within 5ft of the device, the user may simply look at the screen and talk". Phase 1 face detection + face-size proximity + Face Match; phase 2 custom multi-tower CNN gaze model; phase 3 Voice Match + on-device ASR + intent models over "audio prosody and text content". "eight machine learning models together", quantized TFLite, all on-device; models "work off of partial utterances" for latency; "enforce stricter attention requirements before informing users that the system is ready ... to minimize false triggers"; 3,000-participant demographic test set. No accuracy/false-trigger numbers published.

### S13. Google — Gemini Live API capabilities guide (proactive audio)
URL: https://ai.google.dev/gemini-api/docs/live-api/capabilities
- "When this feature is enabled, Gemini can proactively decide not to respond if the content is not relevant." Config: `proactivity: { proactive_audio: true }` in setup, `v1beta`. "available in Gemini 2.5 Flash Live Preview" but "not supported in Gemini 3.1 Flash Live". VAD params: `start_of_speech_sensitivity`, `end_of_speech_sensitivity`, `prefix_padding_ms`, `silence_duration_ms`. On interruption "The ongoing generation is canceled and discarded."

### S14. OpenAI — Realtime API voice activity detection guide
URL: https://developers.openai.com/api/docs/guides/realtime-vad
- `server_vad` (threshold, prefix_padding_ms, silence_duration_ms) and `semantic_vad` (eagerness low/medium/high/auto); `create_response` / `interrupt_response` flags. **No documented option for the model to ignore speech not directed at it.** The addressee gate has to live in front of the API.

---

## 2. Addressee estimation in human-robot interaction

### S15. Abbo, Pinto-Bernal, Catrycke, Belpaeme — "Multi-party open-ended conversation with a social robot" (Frontiers in Robotics and AI, 15 Apr 2026)
URL: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2026.1766383/full
- Furhat; ReSpeaker array for direction of arrival; Azure Cognitive Services speaker ID; python face_recognition; GPT-3.5 streaming; 30 participants (8 F / 22 M), "group" vs "parallel" scenarios.
- Voice ID accuracy 18.4 % (group) / 26.8 % (parallel); face recognition 80.0 % / 94.7 %; "face recognition proved to be more reliable", vision wins on conflict.
- Turn-taking: "The system takes the turn if the robot is looked at by the last speaker or after prolonged silence." Addressee correct 92.6 % (parallel) / 79.3 % (group); incorrect 7.0 % / 13.6 %.
- Latency 1.35 s (SD 0.55), "occasionally reaching 5 seconds"; overlapping speech was the most fragile condition; users confused when "verbal output conflicted with nonverbal behaviour".

### S16. Mazzola, Rea, Sciutti — "Real-time Addressee Estimation: Deployment of a Deep-Learning Model on the iCub Robot" (arXiv 2311.05334, Nov 2023)
URL: https://arxiv.org/html/2311.05334
- "input sequences of 10 frames, each sequence lasting 0.8 s" at "12.5 Hz"; "provides a first estimate less than 1 second"; face crop + 2-D body pose; classes robot / left / right.
- Vernissage test F1: overall 75.01 %, robot 67.52 %, left 78.61 %, right 81.75 %. Live on iCub (6 participants in pairs): overall 75.84 %, robot 71.73 %, left 82.14 %, right 76.33 %.

### S17. Mazzola, Romeo, Rea, Sciutti, Cangelosi — "To Whom are You Talking? A Deep Learning Model to Endow Social Robots with Addressee Estimation Skills" (arXiv 2308.10757, IJCNN 2023)
URL: https://arxiv.org/abs/2308.10757
- CNN + LSTM over "images portraying the face of the speaker and 2D vectors of the speaker's body posture"; egocentric robot perspective; trained on the Vernissage corpus (NAO). Paper CC-BY-4.0; code and data on Zenodo.

### S18. Fukuda et al. (incl. Delcroix, Watanabe) — "Evaluating LLM Abilities for Addressee, Turn-change, and Next Speaker Prediction in Meetings" (arXiv 2606.17542, 16 Jun 2026)
URL: https://arxiv.org/html/2606.17542v1
- AMI, 10 sessions, 4,051 utterances, 262 min, 16 speakers; human subset 2 sessions / 347 utterances / 8 speakers. Online setting: "only past and current conversation information".
- Addressee accuracy: humans 66.6 %; Qwen3-14B 51.5 %; Gemini 2.5 Pro 61.4 %; chance 25 %. Next-speaker F1: humans 60.1 %, Qwen3-14B 69.4 %, Gemini 2.5 Pro 57.7 %. Human agreement α = 0.67 (addressee). Gemini improved when given focus-of-attention labels, i.e. it "does not fully extract or utilize gaze cues from raw video"; raw multimodal signals gave "limited complementary information beyond text".

### S19. Siegert, Weißkirchen, Wendemuth — "Acoustic-Based Automatic Addressee Detection for Technical Systems: A Review" (Frontiers in Computer Science, 14 Jul 2022)
URL: https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2022.831784/full
- 23 studies. Corpora: SVC 4 h / 99 speakers; VACC 17 h / 27 speakers; RBC 90 dialogues; Amazon in-house up to 6 M utterances (4 M:2 M). Acoustic-only: Shriberg 2012 EER 12.63 %; Batliner 2009 74.2 % acc; Akhtiamov 2017 UAR 82.2 % with 1,000 ComParE features; Tong 2021 EER 5.48 %. Multimodal: acoustic + semantic UAR 92.9 %; Tsai 2015 13.9 % EER. Cues: "duration, energy, F0, pauses, jitter, shimmer" — "energy-based acoustic features tend to be the most important ones". Gaps: small corpora, weak demographic coverage, unclear cross-condition generalisation.

### Also read (qualitative only)
- Cano, Pérez, Merino, Gomez — "Multimodal Voice Activity Projection for Turn-Taking in Social Robots" (arXiv 2607.07294, Jul 2026): audio-visual VAP with LoRA on pretrained backbones, NoXi / NoXi+J / Haru EDR; no numbers in abstract. https://arxiv.org/abs/2607.07294
- Studerus et al. — "A Framework for Low-Latency, LLM-driven Multimodal Interaction on the Pepper Robot" (arXiv 2603.21013, Jan 2026): S2S model on the robot tablet, function calling for gaze/navigation; no addressee mechanism or latency numbers in abstract. https://arxiv.org/abs/2603.21013
- IntenBot (arXiv 2605.04585, May 2026): voice + gaze + pointing in XR disambiguated by an LLM; CC-BY-4.0; no numbers in abstract. https://arxiv.org/abs/2605.04585
- M³V (arXiv 2409.09284): multi-view text-audio alignment for DDSD under ASR errors; numbers not in abstract. https://arxiv.org/abs/2409.09284
- SELMA (Apple, arXiv 2501.19377): one speech-LLM for voice trigger + DDSD + ASR; "64% on the VT detection task, and 22% on DDSD" relative EER improvements. https://arxiv.org/abs/2501.19377
- FLoRA (Apple, arXiv 2406.09617): 22 % relative EER reduction vs text-only; adapter dropout 20 % lower EER / 56 % lower FA than full fine-tuning; 16 M–3 B. https://arxiv.org/abs/2406.09617

---

## 3. Speaker verification models: accuracy, size, license

### S20. Desplanques, Thienpondt, Demuynck — ECAPA-TDNN (arXiv 2005.07143, Interspeech 2020)
URL: https://arxiv.org/html/2005.07143v3
- C=512: 6.2 M params; EER 1.01 % / 1.24 % / 2.32 % (Vox1-O / E / H), minDCF 0.1274 / 0.1418 / 0.2181. C=1024: 14.7 M; 0.87 % / 1.12 % / 2.12 %, minDCF 0.1066 / 0.1318 / 0.2101. Trained on VoxCeleb2 dev (5,994 speakers) with MUSAN + RIR + tempo + codec augmentation and SpecAugment.

### S21. SpeechBrain — `speechbrain/spkrec-ecapa-voxceleb` (Hugging Face model card)
URL: https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb
- License "apache-2.0"; trained on VoxCeleb1+2; "EER 0.80" on VoxCeleb1-test cleaned (release 05-03-21); cosine scoring; 16 kHz mono; CPU or `run_opts={"device":"cuda"}`.

### S22. Koluguri, Park, Ginsburg — TitaNet (arXiv 2110.04410)
URL: https://ar5iv.labs.arxiv.org/html/2110.04410
- TitaNet-S 6.4 M / 1.15 % EER; TitaNet-M 13.4 M / 0.81 %; TitaNet-L 25.3 M / 0.68 % (VoxCeleb1 cleaned); 192-d embeddings; DER CH109 1.11 % (S), AMI-MixHeadset 1.73 % (L).

### S23. NVIDIA — `nvidia/speakerverification_en_titanet_large` (Hugging Face model card)
URL: https://huggingface.co/nvidia/speakerverification_en_titanet_large
- "23M" params, "CC-BY-4.0"; trained on VoxCeleb1/2, Fisher, Switchboard, LibriSpeech, SRE 2004–2010; EER "0.66" on VoxCeleb1 cleaned; DER NIST SRE 2000 6.73, AMI Lapel 2.03, AMI MixHeadset 1.73, CH109 1.19; 16 kHz mono.

### S24. Wang, Zheng, Chen, Cheng, Chen — CAM++ (arXiv 2303.00332, Interspeech 2023)
URL: https://ar5iv.labs.arxiv.org/html/2303.00332
- Table 3: CAM++ 7.18 M params / 1.72 GFLOPs; ECAPA-TDNN 14.66 M / 3.96 G; ResNet34 6.70 M / 6.84 G. EER/minDCF: CAM++ 0.73/0.0911 (O), 0.89/0.0995 (E), 1.76/0.1729 (H); CN-Celeb 6.78/0.3830; ECAPA 0.89 / 1.07 / 1.98; ResNet34 0.97 / 1.03 / 1.88.
- RTF, CPU single thread: CAM++ 0.013, ECAPA-TDNN 0.033, ResNet34 0.032 — i.e. ~2.5x faster than ECAPA at equal or better EER. (x86 CPU; not Jetson.)

### S25. 3D-Speaker (ModelScope) — GitHub README
URL: https://github.com/modelscope/3D-Speaker
- "released under the Apache License 2.0". Pretrained table (VoxCeleb1-O / CN-Celeb EER): Res2Net 4.03 M 1.56 % / 7.96 %; ResNet34 6.34 M 1.05 % / 6.92 %; ECAPA-TDNN 20.8 M 0.86 % / 8.01 %; ERes2Net-base 6.61 M 0.84 % / 6.69 %; CAM++ 7.2 M 0.65 % / 6.78 %; ERes2NetV2 17.8 M 0.61 % / 6.14 %; ERes2Net-large 22.46 M 0.52 % / 6.17 %. ONNX Runtime inference scripts under `runtime/onnxruntime` (Apr 2024). No latency numbers.
- Toolkit paper (arXiv 2403.19971v3, Dec 2024) adds Vox1-E/H: CAM++ 0.81 / 1.58 %; ERes2NetV2 0.76 / 1.45 %; ECAPA 0.97 / 1.90 %; export to ONNX for Triton. https://arxiv.org/html/2403.19971v3

### S26. Yakovlev et al. (ID R&D) — ReDimNet (arXiv 2407.18223, Jul 2024)
URL: https://arxiv.org/html/2407.18223v1
- Vox1-O EER by size: B0 1.0 M params / 0.43 GMACs / 1.16 %; B1 2.2 M / 0.54 / 0.85 %; B2 4.7 M / 0.90 / 0.57 %; B3 3.0 M / 3.00 / 0.50 %; B4 6.3 M / 4.80 / 0.51 %; B5 9.2 M / 9.87 / 0.43 %; B6 15.0 M / 20.27 / 0.40 %. Code https://github.com/IDRnD/ReDimNet (paper under arXiv non-exclusive license; check the repo license before use). CAM++ quoted at 0.71 % in their table.

### S27. Chen et al. (Microsoft) — WavLM (arXiv 2110.13900)
URL: https://ar5iv.labs.arxiv.org/html/2110.13900
- WavLM Base / Base+ 94.70 M; Large 316.62 M. Speaker verification, Vox1-O / E / H EER: ECAPA-TDNN Fbank baseline 1.080 / 1.200 / 2.127 %; WavLM Base+ + ECAPA 0.84 / 0.928 / 1.758 %; WavLM Large + ECAPA 0.617 / 0.662 / 1.318 %; + large-margin fine-tuning + quality-aware calibration 0.383 / 0.480 / 0.986 %.
- HF `microsoft/wavlm-base-plus-sv`: license via the UniSpeech repo LICENSE; pretraining 94 k h (60 k Libri-Light + 10 k GigaSpeech + 24 k VoxPopuli), fine-tuned on VoxCeleb1; example cosine "threshold = 0.86 # the optimal threshold is dataset-dependent". https://huggingface.co/microsoft/wavlm-base-plus-sv

### S28. WeSpeaker toolkit (arXiv 2210.17016v2)
URL: https://arxiv.org/html/2210.17016v2
- Vox1-O: ECAPA-TDNN 0.870 % / minDCF 0.107; ResNet34 1.31 % / 0.154 (as read); ResNet221 0.505 % / 0.045. Export to ONNX / TensorRT, Triton deployment; no RTF numbers in the paper.

### Vendor / secondary data points
- Picovoice speaker-recognition benchmark (GitHub) `[vendor]`: Eagle 0.18 % EER / 4.48 MB; SpeechBrain 0.70 % / 117.48 MB; pyannote 0.49 % / 46.45 MB, on a Ryzen 7 5700X. The product page swaps the SpeechBrain/pyannote EERs (0.49 vs 0.70) and says VoxConverse; treat both as marketing. https://github.com/Picovoice/speaker-recognition-benchmark , https://picovoice.ai/products/voice/speaker-recognition/
- Leguillier, Matrouf, Lechien, Rouvier — "On Low-Bit Quantization Errors in Speaker Verification" (arXiv 2606.08078, Jun 2026): ResNet-36 / ResNet-200, "a clear knee point at 2 bits"; decision flips concentrate near the FP32 threshold; proposes a "calibrated multi-precision cascade that resolves most trials at 2 bits and escalates only ambiguous cases". https://arxiv.org/abs/2606.08078

---

## 4. Far-field, noisy and mobile-robot speaker verification

### S30. Mohammadamini, Matrouf, Rouvier, Bonastre, Serizel, Gonos — "RoboVox: A Single/Multi-channel Far-field Speaker Recognition Benchmark for a Mobile Robot" (LREC-COLING 2024, pp. 14152–14156)
URL: https://aclanthology.org/2024.lrec-main.1234.pdf
- French corpus, "78 speakers", "≃ 11,000" dialogues; 8-channel recordings: channels 1–3 on the angles of the robot, channel 4 inside the robot, channel 5 close-talk ground truth; robot has a loudspeaker beneath it; internal actuator noise, moving robot, distance not fixed, overlapping speakers. Dialogues < 2 s discarded. Enrollment on channel 5 (3 dialogues/speaker).
- ResNet-34 baseline (Table 4, EER / DCT): Channel 1 15.79 / 0.92; Channel 2 15.63 / 0.87; Channel 3 15.74 / 0.88; Channel 4 18.22 / 0.91; Channel 5 9.29 / 0.73; Multi-channel 15.06 / 0.86. "the EER in the Dipco single-channel track is 5.84 while in the RoboVox is 18.22." Corpus footnote license: CC BY-NC-SA 4.0.

### S31. Dip et al. — "RoboVox Far Field Speaker Recognition: A Novel Data Augmentation Approach with Pretrained Models" (arXiv 2409.10240, Sep 2024, CC BY 4.0)
URL: https://arxiv.org/html/2409.10240v1
- 2,219 conversations / 78 speakers / ~11,000 dialogues avg 3.5 s; 1 m / 2 m / 3 m; halls, open spaces, small and medium rooms; robot at wall / centre / corner. Enrollment ch5 (225 files), test ch4 (10,332 files). Models: ECAPA-TDNN, ResNet-TDNN, pyannote, TitaNet-Large, mel + ECAPA. Best no-augmentation: ResNet "DCF of 0.84 and an EER of 13.44"; adding test-like noise (SNR −10 to −4 dB) to *enrollment* files: "0.75 DCF and 12.79 EER".

### S32. Choi et al. — "Team HYU ASML ROBOVOX SP Cup 2024 System Description" (arXiv 2407.11365)
URL: https://arxiv.org/abs/2407.11365
- ResNet + TDNN ensemble trained with French data, focus on augmentation and training-segment duration; "second place on the SP Cup 2024 public leaderboard, with a detection cost function of 0.5245 and an equal error rate of 6.46%".

### S33. Al-Karawi, Al-Bayati — "The effects of distance and reverberation time on speaker recognition performance" (Int. J. Information Technology, 2024)
URL: https://link.springer.com/article/10.1007/s41870-024-01789-y
- MFCC-based system. "At 0.53-s RT and 0.5-cm distance the EER is 2.33%" (as printed; near-field), "it rises to 6%" at 7 m, and "a notable EER increase of 14.66%" at RT 1.5 s / 5 m; "optimal accuracy when the microphone-to-source distance is less than 0.5 m".

### S34. Iatariene, Guérin, Serizel — "Towards Low-Latency Tracking of Multiple Speakers With Short-Context Speaker Embeddings" (arXiv 2508.14115, Aug 2025)
URL: https://arxiv.org/html/2508.14115
- ECAPA-TDNN teacher (SpeechBrain, 1024 ch, VoxCeleb 7,205 ids) distilled to students trained on crops of "250, 500, 750, 1000, 1500, 2000, 8000 ms"; evaluation blocks 256 ms – 6.4 s. LibriJump 2-speaker AssA: teacher 250 ms 46.8 %; student 250 ms 54.8 %; 750 ms 63.1 %; whole 65.5 %. 512-channel student within 1.7 % of 1024. Students more robust to overlap in 800–3200 ms contexts.

### S37. Shi et al. — "A knowledge-driven framework for surgical safety check integration using speech recognition and speaker verification" (Frontiers in Neuroscience, 12 Jan 2026)
URL: https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2025.1726720/full
- "The final model contains fewer than 1.3 million parameters and runs in real time on NVIDIA Jetson Nano and Raspberry Pi 4B platforms, with an end-to-end latency below 200 ms for typical utterances." (This sentence is about the ASR model.) ECAPA-TDNN SV module with per-member enrollment and AM-softmax; "achieved an EER of about 3.1%" under "medium-to-high noise and multi-speaker interference"; ~70 dB medium noise. The SV module's own platform/latency is not separately stated.

---

## 5. Personal (target-speaker) VAD and speaker-gated barge-in

### S35. Ding et al. (Google) — "Personal VAD 2.0: Optimizing Personal Voice Activity Detection for On-Device Speech Recognition" (arXiv 2204.03793, Interspeech 2022)
URL: https://ar5iv.labs.arxiv.org/html/2204.03793
- Frame-level target-speaker VAD inside a streaming on-device ASR; Conformer blocks (4 layers, dim 64, 8 heads, 31 left-context), 512-d stacked log-mel input; enrollment and enrollment-less variants; VAD threshold 0.1.
- Table 2 sizes: LSTM standard VAD 1.5 MB / 3.41 MFLOPs; Conformer standard VAD 0.7 MB / 8.77 MFLOPs; Personal VAD (v1) 5.8 MB / 3.54 MFLOPs; Personal VAD 2.0 1.0 MB / 9.58 MFLOPs ("only 1/4 model size"). Enrollment WER (non-concat / concat): PVAD v1 17.9 / 41.0; PVAD 2.0 12.4 / 32.7; standard VAD 6.9 / 10.1 (standard VAD passes all speakers, so its concat WER is not a target-speaker metric). Enrollment-less: PVAD 2.0 7.0 (voice-search) / 10.1. Train 2.6 M utterances (~1,600 h, 6,923 speakers) + 35 M pairs (~27,500 h) for enrollment-less.
- Follow-on: Feng et al., "Adaptive Speaker Embedding Self-Augmentation for PVAD with Short Enrollment Speech" (arXiv 2601.12769, ICASSP 2026): wake-word-length enrollment "matching full-length enrollment performance after five iterative updates". https://arxiv.org/abs/2601.12769

### S36. FireRed team — "FireRedChat: A Pluggable, Full-Duplex Voice Interaction System" (arXiv 2509.06502, Sep 2025)
URL: https://arxiv.org/html/2509.06502
- pVAD: "target-speaker embedding extracted by an ECAPA-TDNN encoder ... concatenated with the post-convolution features ... a GRU module models temporal dependencies"; trained on "2000 hours of clean Mandarin and English speech" with 5 s target + 5 s interferer/noise mixtures at 0–30 dB SNR.
- False barge-in rate = "erroneous interruptions triggered when the primary speaker is silent; ... any interruption induced by other sounds (background noise or non-primary speakers) is counted as an error." Results: LiveKit T90 140 ms / false barge-in 33.4 %; TEN 90 ms / 78.1 %; FireRedChat 170 ms / 10.2 %. End-of-turn accuracy 94.9–96.0 % (FireRedChat) vs 70.8–86.2 % (LiveKit) vs 94.4–95.8 % (TEN); P50 e2e latency 2.341 s / 3.598 s / 3.375 s.

---

## 6. Latency on Jetson-class hardware — what is and is not measured

No fetched source measured ECAPA-TDNN, TitaNet, CAM++ or WavLM embedding extraction on a Jetson. The
usable proxies:

| Proxy | Number | Hardware | Source |
|---|---|---|---|
| Audio-only DDSD cascade, 520 K params | median 38 ms, p95 51 ms per decision | ARM Cortex-A72 (RPi 4 class) | S1 |
| CAM++ vs ECAPA-TDNN RTF | 0.013 vs 0.033 (single thread) => ~40 ms vs ~100 ms for a 3 s utterance | x86 CPU | S24 |
| Speaker embedding per 250 ms chunk in diart | pyannote/embedding 57 ms; wespeaker ResNet34-LM 217–218 ms | Xeon Gold 5215, CPU only | S29 (https://arxiv.org/html/2407.04293) |
| Personal VAD 2.0 | 9.58 MFLOPs per frame-step, 1.0 MB | phone-class on-device | S35 |
| ReDimNet-B0 | 0.43 GMACs per (VoxCeleb-style ~2–3 s) input, 1.0 M params | — | S26 |
| ASR (<1.3 M params) + ECAPA SV framework | "< 200 ms" end-to-end (platform for SV not itemised) | Jetson Nano / RPi 4B | S37 |

An AGX Orin (GPU + 12x Cortex-A78AE) is far above every one of these platforms, so a 1–7 M-param
embedding extractor per utterance and a ~1 MB personal VAD per frame are not the bottleneck; the
number that must still be measured in-house is the *end-to-end* owner-voice + addressee decision
under the XVF3800's own beamformer/AEC, with the GPU already loaded by the Model A lanes.

---

## 7. What this means for Parcel's Model A / Model B

### 7.1 Owner voice -> steering injection (Model B input side)
1. **Two-tier owner gate, both on-device.** Tier 1 is a personal VAD conditioned on the owner's enrolled embedding running every frame (Personal VAD 2.0 class: ~1 MB, ~10 MFLOPs) — it is what decides *whose* speech is allowed to (a) barge in on narration and (b) be forwarded to the hosted voice at all. Tier 2 is a per-utterance verification embedding (CAM++ 7.2 M / Apache-2.0 or ReDimNet-B1/B2 1–5 M, cosine vs. a multi-condition owner template) that confirms the speaker before a steering command is committed. FireRedChat's pVAD (ECAPA embedding + GRU) is the working template: it took false barge-ins from 33–78 % down to 10 % at T90 = 170 ms.
2. **Budget for far-field EER an order of magnitude worse than VoxCeleb.** VoxCeleb1-O EERs are 0.4–1.2 %, but on a moving robot at 1–3 m with its own actuator noise the ResNet-34 baseline is 15–18 % EER (9.3 % even on the close-talk reference channel), and a SP-Cup-winning system only reaches 6.5 %. Furhat's cloud speaker-ID was right only 18–27 % of the time in multi-party rooms. Therefore: owner identity from voice is a **soft prior** fused with direction-of-arrival (XVF3800) and face/pose from the camera, never a hard gate on its own; enroll the owner in several rooms and distances; add robot-noise augmentation to the *enrollment* side (the RoboVox recipe: −10…−4 dB SNR robot noise on enrollment files improved EER 13.44 -> 12.79).
3. **Short windows lose accuracy fast.** A 250 ms context gives ~55 % assignment accuracy vs 65 % for the full utterance (ECAPA KD student); the 10 Hz act loop cannot get a reliable "owner" bit within one tick. Design the steering channel so that the owner bit is available ~0.3–1 s after speech onset (in step with the 0.5–2 Hz language lane), and let the 10 Hz loop act on a provisional "someone is speaking from DOA θ" signal only.
4. **Barge-in on the robot's own narration needs a playback reference.** Feed the TTS output as a reference channel to the personal VAD / DDSD net (Amazon's implicit-AEC design: −56 % FRR during playback; Conversation Mode: −42 % false wakes from Alexa's own speech). The XVF3800 already does AEC; keep the TTS reference path deterministic.

### 7.2 Robot-directed speech (addressee) gate before the hosted voice (Model B) and before plan edits (Model A language lane)
5. **The hosted voice will not decide addressee for us.** OpenAI Realtime exposes only server/semantic VAD and interrupt/create flags; Gemini's `proactive_audio` exists only on the 2.5 Flash Live preview and is absent from 3.1 Flash Live. Every non-robot-directed utterance we stream is billed, may be answered, and (per the first sweep) hosted voices resume after side-talk only ~2 % of the time. The addressee gate must be local and must sit **before** audio is forwarded.
6. **Adopt the SAS/SDAR shape: pre-ASR acoustic gate -> interaction-state -> ASR-text/LLM confirmation.** Stage A: a ~0.5 M-param audio-only classifier on the beamformed stream (expect F1 ~0.86, ~2 % false triggers, ~8 % with a TV on; < 55 ms on a Cortex-A72, so trivially fast on Orin). Stage B: an 8 s rolling interaction state (robot just spoke / was just addressed / owner is facing the robot) — removing it cost SAS 38 F1 points and Apple's dialogue context cut FAR@10 %FRR from 11.4 % to 4.8 %. Stage C: the language lane's ASR text + confidence + prosody into the small local LM for a final DD/ND decision (EER 7–8 % class with a 124 M LM; ~6.5 % with 1.5 B). Only Stage-C-positive utterances become plan edits or get forwarded to the hosted voice; Stage-A/B-positive ones may trigger orienting behaviour (look toward DOA) so the camera can vote.
7. **Camera fusion is the biggest single lever, but only at close range.** Audio+video raised SAS F1 from 0.86 to 0.95; Alexa's head-orientation model cut visual FRR ~80 %; Google gates Look-and-Talk at 5 ft; the iCub gaze+pose addressee model reaches only ~70 % F1 for the "robot" class and needs 0.8 s of frames. So: use face/head-pose toward the robot as a strong positive cue within ~1.5–2 m and as neutral (not negative) beyond that — a dog that ignores its owner from across the room is a worse failure than one that occasionally turns its head.
8. **Do not delegate addressee to a big LLM.** On AMI meetings humans reach 66.6 % addressee accuracy while Qwen3-14B gets 51.5 % and Gemini 2.5 Pro 61.4 % (chance 25 %), and raw video does not supply gaze to the LLM. The local multimodal gate decides; the LLM at most re-ranks.
9. **Data and licensing.** Usable weights: SpeechBrain ECAPA (Apache-2.0), 3D-Speaker CAM++/ERes2NetV2 (Apache-2.0), TitaNet-L (CC-BY-4.0), WavLM-SV (UniSpeech license), ReDimNet (GitHub, verify repo license). RoboVox is CC BY-NC-SA (research only). SAS weights are not released and every DDSD corpus above (Apple ~126 h train, SAS 600 h, Amazon 6 M utterances) is proprietary, so Parcel needs its own robot-directed / side-talk corpus recorded through the XVF3800 on the real body (actuator noise, gait noise, 1–3 m, TV on), on the order of tens of hours with per-segment labels, before any of the EERs above can be believed for this robot.
10. **Latency budget to write into the spec.** Personal-VAD owner bit: per frame (≤ 20 ms). Audio-only addressee: ≤ 55 ms after end-of-utterance (SAS). Camera-fused addressee: ≤ 150 ms. First gaze/pose addressee estimate on a humanoid: < 1 s. Text-confirmed DD decision: after ASR of the utterance (the 0.5–2 Hz lane). Speaker-gated barge-in on narration: T90 ≈ 170 ms with ≈ 10 % false barge-ins is the current open-source state of the art; treat anything better as unproven.

---

## 8. Not readable / not cited
- MDPI "Comparison of Modern Deep Learning Models for Speaker Verification" (Appl. Sci. 14(4):1329) — HTTP 403; its "69.43 ms ECAPA inference time" appears only in search snippets and is not used.
- arXiv 2308.10757 PDF exceeded the fetch size limit; only the abstract page was read (numbers taken from the deployment paper 2311.05334 instead).
- CAM++ and Personal VAD 2.0 PDFs returned binary; the ar5iv HTML renderings were used.
- Springer "A Deep Neural Networks Approach for Speaker Verification on Embedded Devices" — not fetched (paywalled chapter).
