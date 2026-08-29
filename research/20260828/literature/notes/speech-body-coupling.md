# Coupling speech with body motion in real time — literature notes

Date: 2026-08-28. Researcher: subagent (Claude). Method: every source below was located with WebSearch and then READ with WebFetch (arXiv PDFs were converted with `pdftotext` and grepped); nothing is cited from memory. Numbers are quoted from the fetched text. Where a source only exposed its abstract, that is stated.

Scope requested: co-speech gesture generation (GENEA 2022/2023, DiffuseStyleGesture, EMAGE, Audio2Gestures, ZeroEGGS); robot co-speech gesture systems (NAO/Pepper from LLM, Spot, Ameca); laughter / backchannel timing in spoken dialogue systems (Moshi, VAP family, shared-laughter generation, laughter TTS); listener-motion generation (L2L, LM-Listener, DIM, INFP, ARIG, Seamless Interaction); quadruped / pet robots reacting to speech; and a recommended timing architecture for a full-duplex listen-speak-move loop.

---

## 0. Executive summary (the five facts a design should rest on)

1. **Human timing budget.** Across 10 languages, turn transitions have a cross-language mean offset of **+208 ms** (mode 0 ms; Japanese +7 ms, Danish +469 ms), and *visible* responses (nods, gestures) are produced **faster than vocal responses** in every language (Stivers et al. 2009, PNAS). A dog that reacts with its body inside ~200 ms and with its voice inside ~300-500 ms is inside the human envelope.
2. **The prediction primitive exists and runs on CPU.** Voice Activity Projection (VAP) predicts the next 2 s of both parties' voice activity as a 256-state distribution from stereo audio (CPC encoder at 100 Hz, 4-layer 256-d transformer), gives **backchannel-prediction F1 0.723** on Switchboard, is **MIT-licensed**, and a 1-s-context variant runs at **14.6 ms/frame (RTF 0.73 at 50 fps) on a Xeon CPU** with no accuracy loss (76.2 % balanced accuracy). The Kyoto group fine-tuned it with one extra linear layer to predict **backchannels 500 ms ahead** (timing F1 42.85 vs 15.11 zero-shot) and **nods 500 ms ahead** (three nod types), running at 10 Hz with RTF 0.19 on an i7. This is the trainable local "when to react" model.
3. **Full-duplex speech models learn paralinguistics end-to-end but are big.** Moshi is a 7B Temporal Transformer + 6-layer Depth Transformer over a 12.5 Hz / 1.1 kbps codec, 160 ms theoretical / 200 ms practical latency, CC-BY-4.0 weights, needs ~24 GB GPU un-quantised; its instruct data was synthesised with **92 speaking styles including "laughs"** and prompts saying "Use some backchanneling", and it reproduces Fisher-like pause/gap/overlap statistics. On Full-Duplex-Bench it turn-takes with **0.265 s latency** but its backchannel frequency is **0.001** (near zero). F-Actor shows the small alternative: Llama-3.2-1B + frozen codec, **2,000 h synthetic data**, explicit per-dialogue control of **"backchannels: 2 / interruptions: 1"** counts, code and model released.
4. **Co-speech gesture generation is solved for realism, unsolved for appropriateness.** GENEA 2022: a synthetic system (FSA, median 71) beat mocap (FNA, 70) on human-likeness, yet the best synthetic speech-appropriateness was 60.5 % matched vs 74.0 % for mocap. GENEA 2023: NA 71 / SG 69 / SF 65 on human-likeness; MAS 0.81 (NA) vs 0.39 (SG) vs 0.20 (SF); interlocutor-appropriateness of every submission at best 0.09 vs 0.63 for NA. The 2025 BEAT2 re-evaluation (600 raters, 16,000 votes) found realism "saturated" (four models at 41-46 % win rate vs mocap) while alignment scores of several "SOTA" models sit at ~50 % (chance). => For Parcel, do not chase gesture realism; invest in *appropriateness/timing*, which is a prediction problem (fact 2), not a rendering problem.
5. **Laughing along is learnable but hard from audio alone.** Inoue et al. 2022 (ERICA): laugh detection BiGRU F1 82.6; *shared-laughter* decision (should the robot laugh back) F1 **30.3 vs 16.2 chance**; laugh-type choice macro-F1 70.2; response window **within 2 s**; the full system was rated significantly higher on empathy/naturalness/human-likeness (p<0.001) than never-laughing or always-laughing baselines. => "chuckle if the joke was funny" should be a two-signal decision (audio-prosody head at 10 Hz + text-level humour appraisal per utterance) with online reward from the owner's own laughter.

---

## 1. Co-speech gesture generation (benchmarks and models)

### 1.1 GENEA Challenge 2022 — Kucherenko, Wolfert, Yoon et al.
- URL (journal version, fetched PDF): https://arxiv.org/abs/2303.08737 ; short version https://arxiv.org/abs/2208.10441
- Data: "The dataset was based on 18 hours of full-body motion capture" from Talking With Hands 16.2M (which "comprises 50 hours of audio"); 30-fps BVH; two tiers (full-body, upper-body); "a total of 10 teams".
- Scale: "9,196 ratings for the full-body study and 11,400 ratings for the upper-body study"; each rater contributed 76 ratings.
- Results (Table 3, fetched):
  - Full-body human-likeness medians: FNA (mocap) 70 [69,71]; **FSA 71 [70,73]** (a synthetic system rated above mocap — "the first demonstration" of this); FSC 53; FSI 46; rest 27-38.
  - Full-body appropriateness ("percent matched", splitting ties): FNA **74.0 %** [70.9,76.9]; best synthetic FSH **60.5 %**; FSA 57.1 %; several at 51-55 % (chance = 50 %).
  - Upper-body: UNA 63; USQ 69 (above mocap); appropriateness UNA 75.4 %, best synthetic USQ 59.7 %.
- Quote: "all synthetic motion is found to be vastly less appropriate for the speech than the original motion-capture recordings"; "conventional objective metrics do not correlate well with subjective human-likeness ratings" (FGD Kendall's tau ≈ -0.5 at best).
- Assessment: canonical evidence that realism and speech-appropriateness are different axes; FGD is a weak proxy.

### 1.2 GENEA Challenge 2023 — Kucherenko, Nagy, Yoon et al. (ICMI 2023)
- URL (fetched PDF): https://arxiv.org/abs/2308.12646
- Setup: dyadic TWH data (main agent + interlocutor audio/text/motion); "12 teams participated", plus 2 baselines (BM monadic, BD dyadic) and NA (mocap); core test set "41 chunks of approximately one minute each"; extended set 70 chunks. DiffuseStyleGesture+ reports the total TWH data used as "approximately 20 hours and 49 minutes".
- Human-likeness (Table 4): **NA 71 [70,71]; SG 69 [67,70]; SF 65 [64,67]**; SJ 51; SL 51; SE 50; SH 46; BD 46; SD 45; BM 43; SI 40; SK 37; SA 30; SB 24; SC 9.
- Appropriateness for agent speech (Table 5a, MAS, chance = 0): **NA 0.81±0.06 (73.6 % pref. matched); SG 0.39±0.07 (61.8 %); SJ 0.27; BM 0.20; SF 0.20±0.06 (55.8 %)**; most submissions "confined to a narrow range of MAS scores between 0.27 and 0.10".
- Appropriateness for the interlocutor (Table 5b): **NA 0.63±0.08 (67.9 %)**; best submission SA 0.09; SG -0.09; SH -0.21. "The effect of the interlocutor is even more subtle, with submitted systems at best performing barely above chance."
- Key sentence: "a dyadic system being highly appropriate for agent speech does not necessarily imply high appropriateness for the interlocutor."
- Who was who: DiffuseStyleGesture+ states "The median of our system (SF) was 65 ∈ [64, 67]" (https://arxiv.org/abs/2308.13879, HTML fetched; trained "with Td = 1000 noising steps", "in about 132 hours on one NVIDIA V100 GPU"). Deichler et al. (KTH, CSMP + diffusion, https://arxiv.org/abs/2309.05455, abstract fetched) state "Our entry achieved highest human-likeness and highest speech appropriateness rating among the submitted entries" — which in the official tables is uniquely condition SG (my inference from the two documents; the KTH abstract does not print the label).
- Assessment: the strongest 2023 systems are diffusion models conditioned on audio+text; but *reacting to the other party* (the listener/interlocutor axis, exactly what a companion dog must do) was essentially unsolved by every entry.

### 1.3 Towards a GENEA Leaderboard (2024) and the BEAT2 re-evaluation (2025)
- Leaderboard proposal (abstract fetched): https://arxiv.org/abs/2410.06327 — "Current evaluation practices in speech-driven gesture generation lack standardisation and focus on aspects that are easy to measure over aspects that actually matter."
- Re-evaluation (HTML fetched): https://arxiv.org/abs/2511.01233 — six models on BEAT2 (DiffuseStyleGesture, Semantic Gesticulator, ConvoFusion, RAG-Gesture, AMUSE, HoloGest); "over 600 evaluators ... over 16,000 pairwise votes"; motion-realism Elo: mocap 1133, ConvoFusion 1102, RAG-Gesture 1088, HoloGest 1084, Semantic Gesticulator 1070, AMUSE 824, DiffuseStyleGesture 701 — "four models showcasing comparable performance, with projected win rates between 41–46% against motion-capture recordings"; speech-gesture alignment via audio mismatching: mocap ≈ 74 %, DiffuseStyleGesture and HoloGest ≈ 60 %, Semantic Gesticulator ≈ 57 %, "AMUSE, ConvoFusion, and RAG-Gesture all scored near 50% mismatching scores". Conclusion: "motion realism has become a saturated evaluation measure on the BEAT2 dataset"; "previous findings of high speech-gesture alignment do not hold up under rigorous evaluation".
- Assessment (load-bearing): realism is cheap; alignment/appropriateness is the frontier. For a quadruped with a tiny "gesture vocabulary", realism is even less of an issue — timing is everything.

### 1.4 DiffuseStyleGesture (IJCAI 2023)
- URL (fetched PDF + GitHub): https://arxiv.org/abs/2305.04919 ; https://github.com/YoungSeng/DiffuseStyleGesture (MIT license; "tested on NVIDIA GeForce RTX 2080 Ti"; pretrained models for ZEGGS, BEAT, TWH).
- Model: diffusion over 4-s gesture clips resampled to **20 fps (N = 80 frames)**, conditioned on WavLM-Large audio features, one-hot style, and an 8-frame seed gesture (last 8 frames of the previous clip for continuity); cross-local attention + self-attention; classifier-free guidance for style interpolation/extrapolation; **T = 1000 noising steps**, cosine schedule.
- Data: ZEGGS dataset (19 styles).
- Results: MOS human-likeness **4.11±0.08 vs ground truth 4.15±0.11**; speech appropriateness 4.11±0.10 vs 4.25±0.09; ablations: removing cross-local attention drops to 3.76/3.51, removing self-attention 3.55/3.08.
- Assessment: strong, open, MIT — but 1000-step sampling of 4-s blocks is a per-clip (not per-frame) generator; usable as an offline teacher for a small real-time student, not as the 50 Hz lane.

### 1.5 EMAGE + BEAT2 (CVPR 2024)
- URL (fetched PDF, project page, GitHub): https://arxiv.org/abs/2401.00374 ; https://pantomatrix.github.io/EMAGE/ ; https://github.com/PantoMatrix/PantoMatrix (weights on Hugging Face; dataset https://huggingface.co/datasets/H-Liu1997/BEAT2).
- Data: raw BEAT "contains 76 hours of data for 30 speakers"; after excluding 5 noisy-finger speakers "leaving 60 hours of data for 25 speakers (12 female and 13 male)"; split into BEAT2-standard (27 h) and BEAT2-additional (33 h); SMPL-X body + FLAME face; "1762 sequences with an average length of 65.66 seconds".
- Model: Masked Audio Gesture Transformer; four compositional VQ-VAEs (face, upper, hands, lower body + global); content/rhythm attention; 4-frame seed pose.
- Results (Table 4, units FGD×10^-1, BC×10^-1, MSE×10^-8, LVD×10^-5): **EMAGE FGD 5.512, BC 7.724, Diversity 13.06, MSE 7.680, LVD 7.556** vs TalkSHOW 6.209/6.947/13.47/7.791/7.771, CaMN 6.644/6.769/10.86, DiffuseStyleGesture 8.811/7.241/11.49. User study: "60 participants, each participant evaluates 40 pairs of 10-second results"; EMAGE preferred over TalkSHOW/Habibie holistic (52.7 % vs 34.9 % vs 12.4 %).
- License: arXiv page shows CC BY-NC-SA 4.0 for the paper; the repo did not state a code license in the fetched README.
- Assessment: the standard holistic dataset/model; its "masked gesture hints" trick (accept partially specified frames) is a useful pattern for a motion generator that must obey the safety layer's overrides.

### 1.6 ZeroEGGS (Ubisoft La Forge, CGF 2023)
- URL (fetched via ar5iv + GitHub): https://arxiv.org/abs/2209.07556 ; https://github.com/ubisoft/ubisoft-laforge-ZeroEGGS
- Data: "67 sequences of monologue performed by a female actor" in "19 different motion styles", "total length of the dataset is 135 minutes", **60 fps, 75 joints incl. fingers**.
- Model: speech encoder (80-channel mel, 12.5 ms hop) + VAE style encoder (64-d embedding from a 256-512-frame example clip) + gesture generator "two GRU layers with 1024 hidden state size".
- Numbers: **inference "4ms per frame" vs 29 ms for MoGlow**; user study "131 participants"; naturalness ≈ 56.3±22.2 vs MoGlow 11.8±12.2.
- License: "© [2022] Ubisoft Entertainment. All Rights Reserved" (research-only proprietary license in repo).
- Assessment: proof that a *recurrent, per-frame* audio-to-motion generator with a style vector runs far faster than real time — the right shape for the 30-50 Hz lane; but its license blocks product use, so treat as a design reference only.

### 1.7 Audio2Gestures (ICCV 2021)
- URL (abstract fetched): https://arxiv.org/abs/2108.06720 (CC-BY 4.0)
- Contribution: conditional VAE that "splits the cross-modal latent code into shared code and motion-specific code" to model the one-to-many audio-to-motion mapping; relaxed motion loss, bicycle constraint, diversity loss; evaluated on 3D and 2D datasets; code at https://jingli513.github.io/audio2gestures.
- Assessment: canonical statement of why regression to the mean produces "plain/boring" motion — a small dog model must also be stochastic (VQ or diffusion) or it will look robotic.

---

## 2. Robot co-speech gesture systems

### 2.1 Yoon et al. 2019, "Robots learn social skills" (ICRA) — NAO
- URL (fetched PDF): https://arxiv.org/abs/1810.12541
- Data: TED Gesture dataset — "1,295 videos", "Ratio of shots of interest 12.9% (14,221 / 109,946)", "Total length of shots of interest 52.7 h".
- Model: text-to-gesture encoder-decoder, "Two-layered GRUs with 200 hidden units", output upper-body 2D poses (PCA-compressed), retargeted to NAO.
- Numbers: "network inferences were completed in 0.14 s in a CPU"; user study "46 valid participants" (18 of 64 excluded); significant effects on anthropomorphism and speech-gesture correlation vs baselines (p = 0.009, <0.001).
- Assessment: the canonical robot pipeline (learn in human pose space, retarget to fewer DoF). Follow-up: Yoon et al. 2020 trimodal (text+audio+speaker ID, introduces FGD; https://arxiv.org/abs/2009.02119, abstract fetched).

### 2.2 Gesture Generation from Trimodal Context for Humanoid Robots (2024) — Pepper
- URL (fetched PDF): https://arxiv.org/abs/2409.05010
- Reproduces Yoon 2020 on Pepper "using Naoqi's python API", with Pose2Angle + velocity clamping to joint limits; 3 speaker IDs as introverted/normal/extroverted styles; FGD between styles 0.6274 (extro vs intro), 0.3093, 0.4338; "21 participants"; "no significant difference between the robot and stick figure" (retargeting preserved perception); people prefer extroverted/normal styles.
- Assessment: confirms the retargeting step is not the bottleneck; style is perceivable through a low-DoF body.

### 2.3 Low-latency LLM-driven multimodal interaction on Pepper (HRI 2026)
- URL (fetched HTML): https://arxiv.org/abs/2603.21013 ; code https://github.com/studerus/pepper-android-realtime-chat (MIT).
- Uses speech-to-speech APIs ("gpt-realtime, gpt-realtime-mini, gpt-4o-realtime-preview, gpt-4o-mini-realtime-preview", Grok Voice, Gemini Live) with function calling for "navigation, gaze control, tablet interaction". Reports that prior cascaded Pepper LLM systems had "system response times ranging from 3.84 to 8.96 seconds" against a "1–2 second threshold" for natural flow. No gesture-generation details; no measured latencies of its own.
- Assessment: matches Parcel's hosted-Realtime-API assumption; confirms function-calling is how people currently attach body actions to S2S models — at per-utterance granularity only.

### 2.4 EMOTION: expressive motion for humanoids via LLM in-context learning (2024)
- URL (fetched HTML): https://arxiv.org/abs/2410.23234
- Fourier GR-1 humanoid; "OpenAI's GPT-4o (gpt-4o-2024-05-13)"; motion as 22 real values per step (hand positions, orientations, finger openings) from two in-context demos; 10 gestures; "22 valid participants"; EMOTION "does not statistically differentiate from human oracle behaviors" (naturalness p=0.267); **generation time "26.8s for the initial motion sequence generation and 21.2s for a single-round sequence generation after human feedback"**.
- Assessment: LLM-authored motion is expressive but ~25 s per gesture — only viable as an *offline library builder*, never in the loop.

### 2.5 Boston Dynamics, "Robots That Can Chat" (Spot, Oct 2023)
- URL (fetched): https://bostondynamics.com/blog/robots-that-can-chat/
- Stack: "OpenAI Chat GPT API starting with gpt-3.5 before upgrading to gpt-4", BLIP-2 VQA/captioning, Whisper ASR, ElevenLabs TTS; Respeaker V2 mic array on the EAP 2 payload; body language: "turned the arm toward that person" (nearest-person estimate) and "a lowpass filter on the generated speech and turned this into a gripper trajectory to mimic speech sort of like the mouth of a puppet"; **"the latency between a person asking a question and the robot responding is also quite high—sometimes 6 seconds or so."**
- Assessment: the only published legged-robot conversational demo from a major vendor; body coupling was hand-engineered from the speech envelope (a good cheap trick for a dog's "mouth"/head bob), and latency was the acknowledged failure.

### 2.6 Engineered Arts Ameca (vendor page)
- URL (fetched): https://engineeredarts.com/robot/ameca/
- "61 Degrees of Freedom", "27 Degrees of Freedom" in head/face, "over 50 realistic facial expressions"; Tritium software integrates third-party ASR/NLP/TTS; no latency figures or LLM named on the page.
- Assessment: vendor-level only; no numbers on timing. Not load-bearing.

---

## 3. Full-duplex dialogue: turn-taking, backchannels, laughter

### 3.1 Stivers et al. 2009 (PNAS) — the human timing target
- URL (fetched via PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC2705608/
- 10 languages; overall mode 0 ms; cross-linguistic mean **+208 ms**; language means from +7 ms (Japanese) to +469 ms (Danish), "within ≈250 ms either side of this cross-language mean"; confirmations 100-500 ms faster than disconfirmations; **visible responses (head nods, gestures) occurred faster than vocal-only responses in all languages**.
- Assessment (load-bearing): sets the latency budget and licenses "body first, voice second".

### 3.2 Voice Activity Projection (Ekstedt & Skantze, Interspeech 2022)
- URL (fetched PDF + GitHub): https://arxiv.org/abs/2205.09812 ; https://github.com/ErikEkstedt/VoiceActivityProjection (MIT; checkpoint `VAP_3mmz3t0u_50Hz_ad20s_134-epoch9-val_2.56.pt`).
- Objective: "a VAP window of 2 seconds" with "bin durations of 200, 400, 600 and 800ms"; 4 bins per speaker -> "8 total bits, or 256 different possible states"; the model outputs a distribution over these states.
- Architecture: pretrained CPC encoder "outputs frame representations ... at 100Hz"; VA-history features; "causal, decoder only, transformer using a hidden size of 256, 4 layers, 4 heads".
- Data: Switchboard, "2438 dialogs", 11-fold; 10-s chunks.
- Results (Table 1, weighted F1): Discrete (proposed) S/H .899 (.510 for SHIFT), S/L .786, **S-pred .733, BC-pred .723** (both significantly better than independent-bin baselines, p<0.025); majority-class BC-pred .333.
- Assessment (load-bearing): the self-supervised objective needs no labels — Parcel can train it on any stereo conversation audio (including its own logs).

### 3.3 Real-time VAP (Inoue, Ekstedt, Skantze, IWSDS 2024) and VAP-Realtime
- URL (fetched PDF + GitHub): https://arxiv.org/abs/2401.04868 ; https://github.com/inokoj/VAP-Realtime (MIT code; "The trained models ... are used for only academic purposes").
- Model: "self-attention transformer with 1 layer for each channel, and a cross-channel transformer with 3 layers. Both have 4 attention heads and a unit size of 256"; trained on Japanese Travel Agency Task Dialogue, "92.5 hours" train.
- Table 1 (Intel Xeon Gold 6128, 3.40 GHz; balanced accuracy on shift/hold; inference time per frame / RTF at 50 fps): 20 s context 74.20 % / 273.84 ms (13.69); 10 s 75.73 % / 94.93 ms (4.75); 5 s 75.01 % / 33.66 ms (1.68); 3 s 75.75 % / 30.54 (1.53); **1 s 76.16 % / 14.61 ms (0.73)**; 0.5 s 75.41 % / 13.11 (0.66); 0.3 s 71.50 %; 0.1 s 62.81 %.
- Quote: "by restricting the input sequence to around 1 second in the transformer, real-time processing becomes feasible without compromising accuracy."
- VAP-Realtime repo ships: VAP for Japanese/English (Switchboard)/multilingual at "5Hz, 10Hz, 20Hz" with 2.5-5 s context; **VAP-BC** (continuer/assessment backchannel); noise-robust variants "for robot dialogue applications"; and a **nodding model** ("predicts the probability of noddings occurring 500 milliseconds later", outputs `p_nod_short`, `p_nod_long`, `p_nod_long_p`, 10 Hz, 10 s context, "fine-tuned with an attentive listening dialogue data using ERICA (WoZ)", Japanese only). Input contract: 160 samples at 16 kHz per cycle (10 ms), TCP server.
- Assessment (load-bearing): a listener-gesture-from-audio predictor (nods) already exists in this family and runs on CPU; the same recipe gives Parcel "ear perk / head tilt / look-at-owner" heads.

### 3.4 "Yeah, Un, Oh": continuous real-time backchannel prediction by fine-tuning VAP (NAACL 2025)
- URL (fetched HTML): https://arxiv.org/abs/2410.15929
- Method: "A new linear layer is introduced on top of the VAP model"; positive frames are "500 milliseconds before the actual backchannel utterances"; two types: continuers ("un", "hai") and assessments ("he-", "oh"); CPC frozen; 1 channel-wise + 3 cross-attention layers.
- Data: pre-training "about 35 hours" of Japanese dialogue; fine-tuning WOZ corpus "109 dialogue sessions, each lasting approximately 7 to 8 minutes", "11,371 utterances for training".
- Results: timing F1 **42.85** (zero-shot VAP 15.11; baseline 36.37); continuer F1 38.11 (baseline 34.13); assessment F1 31.76 (baseline 19.74); real-time: "RTF was consistently below 1.0" on Intel Core i7-11700, **RTF 0.194 with 5-s context at 10 Hz**. Limitation: "evaluated solely on a Japanese dialogue dataset".
- Assessment: F1 in the 30-40s is the realistic ceiling for audio-only backchannel timing; combine with text/semantic context.

### 3.5 Inoue, Lala, Kawahara 2022 — "Can a robot laugh with you?" (Frontiers in Robotics and AI; ERICA)
- URL (fetched full text): https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.933261/full
- Data: speed-dating dialogues with ERICA (WoZ), "82 dialogue sessions", 10-15 min each; laughter IPUs "2,453 IPUs (8.2%) ... solo laughs (1,611) or speech laughs (842)"; shared-laughter positives 268 vs 1,389 negatives.
- Three sub-models: (1) laugh detection — "Bi-directional GRU (2 layers, 256 hidden)" on "40-dimensional Mel-filterbank", **F1 82.6** (P 78.2 / R 87.6); (2) shared-laughter prediction — logistic regression on 80-d acoustic + 12-d prosodic (F0, power), **P 21.2 / R 53.4 / F1 30.3 vs random 16.2 %**; (3) laugh-type (mirthful vs social) — prosodic LR, **macro-F1 70.2**.
- Timing: shared laughter defined as ERICA laughing "within 2 s after the end of the initial laugh".
- Evaluation: crowdsourced raters (n = 30-41 per scenario), three conditions (no laugh / always social laugh / proposed); proposed significantly higher on empathy (p=0.003), naturalness (p<0.001), human-likeness (p<0.001) in scenario 1, and similar in scenario 4.
- Assessment (load-bearing for the "chuckle" target): this is the closest existing system to "learn to chuckle when the joke was funny"; the decision model is the weak link (F1 30), and it used only audio — Parcel can add the text channel and owner-history features.

### 3.6 Moshi (Kyutai, 2024) — full-duplex speech-text model
- URL (fetched PDF + GitHub): https://arxiv.org/abs/2410.00037 (PDF at https://kyutai.org/Moshi.pdf) ; https://github.com/kyutai-labs/moshi
- Architecture: Helium "7B-parameter text LLM ... pretrain[ed] on 2.1T tokens"; Mimi codec at **12.5 Hz, 1.1 kbps, 80 ms frame**; Temporal Transformer (7B) + "Depth Transformer has 6 layers, a dimension of 1024"; multi-stream (user audio, Moshi audio, "Inner Monologue" text prefix); "theoretical latency of 160ms (80ms for the frame size of Mimi + 80ms of acoustic delay), with a practical overall latency as low as 200ms on an L4 GPU"; the paper contrasts this with "the 230 ms average in natural conversations ... (Stivers et al., 2009)".
- Data: "audio collection of 7 million hours"; Fisher "2000 hours of phone conversations" for full-duplex; "170 hours of natural and scripted conversations"; "more than 20k hours of synthetic speech data" from LLM-written transcripts; TTS voice actor "monologues covering more than 70 speaking styles" — Table 19 lists **92 styles including "laughs", "amused", "joking", "panting", "whispering"**; synthetic transcript prompts literally include "Use some backchanneling. Use short turns." and "Use a lot of backchanneling."
- Turn-taking statistics (Table 9, cumulative seconds per minute of generated dialogue, temp 1.0): Moshi IPU 50.8 s, Pause 7.0 s, Gap 4.5 s, Overlap 4.1 s vs Fisher ground truth 51.1 / 6.4 / 4.2 / 3.3.
- Licensing/hardware: "MIT license for the Python parts, and Apache license for the Rust backend"; weights "CC-BY 4.0"; PyTorch needs "a GPU with a significant amount of memory (24GB)"; MLX int4/int8/bf16 variants exist; variants Moshiko/Moshika.
- Assessment (load-bearing): the paralinguistic channel (laughter, styles) is learned *from synthetic data whose style tags were chosen by an LLM* — this is the recipe for a dog whose vocal reactions and (by extension) motion tokens are conditioned on conversation state. But 7B is heavy for Orin and Moshi's own backchannelling is near zero (3.8).

### 3.7 Full-Duplex-Bench (2025)
- URL (fetched HTML): https://arxiv.org/abs/2503.04721
- Four dimensions: pause handling, backchanneling, smooth turn-taking, user interruption. Table III (TOR = takeover rate): pause handling TOR dGSLM 0.934, Moshi 0.985, Freeze-Omni 0.642, Gemini Live 0.255 (lower TOR is better here — do not take over during a pause); backchannel (ICC set): **Moshi frequency 0.001, JSD 0.957**; dGSLM freq 0.015; Gemini Live 0.012; smooth turn-taking (Candor): **Moshi TOR 1.000 latency 0.265 s**; dGSLM 0.352 s; Freeze-Omni 0.953 s; Gemini Live 1.301 s; user interruption: Moshi latency 0.257 s (GPT-4o judge score 0.765), Freeze-Omni 1.409 s (3.615), Gemini Live 1.183 s (3.376). Sample sizes: 216 / 119 / 55 / 200 / 137.
- Assessment: even the best open full-duplex model barely backchannels; a dedicated backchannel/reaction head (VAP-BC) is still needed on top of any S2S model.

### 3.8 Survey of Full-Duplex Spoken Dialogue Systems (2026)
- URL (fetched HTML): https://arxiv.org/html/2606.19453v1
- Hierarchy: L0 module-level external scheduler (FireRedChat, FlexDuo), L1 hidden-state-level (MinMo, Freeze-Omni), L2 token-level (Moshi, LSLM, OmniFlatten), L3 representation-level ("no published system yet"). Ontology T×I×R (temporal / intent incl. backchannel / response incl. backchannel). Latencies: "FireRedChat T90≈170 ms barge-in", Moshi "approximately 200 ms in practice", MinMo "approximately 600 ms in theory, 800 ms in practice", and an "L0 ceiling" of "roughly 500 ms" for external-scheduler designs. Notes "Backchannel during system speech ... most systems mis-classify". Body/face extensions are out of its scope.
- Assessment: Parcel's current design (hosted S2S + local arbiter) is L0/L1; the survey's ~500 ms L0 ceiling is the number to beat with the local reaction lane.

### 3.9 F-Actor (2026) — controllable behaviour in a small full-duplex model
- URL (fetched PDF + GitHub): https://arxiv.org/abs/2601.11329 ; https://github.com/MaikeZuefle/f-actor
- "Llama3.2-1B-Instruct" backbone, frozen audio encoder, four DAU streams per audio stream; "requires just 2,000 hours of data" (Behavior-SD, "2,164 hours of English multi-turn" synthetic CosyVoice dialogues with backchannel/interruption annotations; 52 speakers subset ≈ 48 h for some experiments); instruction block "Your behaviors: - backchannels: 2 - interruptions: 1"; Table 4 (per minute): Ours IPU 59.3 s, Pause 10.4 s, Gap 3.0 s, Overlap 5.4 s vs Behavior-SD GT 55.8 / 10.8 / 3.8 / 3.0; LLM-judge vs human ranking τ = 1.00; interruptions rare ("averaging only 0.9" per dialogue) so control is directional not exact.
- Assessment: proves that behaviour *counts* can be instruction-controlled in a 1B model trained on synthetic data — the same mechanism can carry "reaction budget" tokens for a dog (e.g., "chuckles: 1, looks-at-owner: 3").

### 3.10 Moshi-Face: facial generation inside a full-duplex model (2026)
- URL (fetched HTML): https://arxiv.org/html/2606.21970v1
- Extends Moshi with a non-autoregressive Face Transformer whose "face tokens are trained at the same frame rate as the text and audio tokens" (12.5 Hz; video 25 fps downsampled ×2); trained on "approximately 180 hours of dialogue data, totaling around 3,400 dialogues" from Seamless Interaction with VHAP meshes ("5,143 vertices"); LSE-D 8.76, UTMOS 1.75 (teacher-forced). No latency numbers; no code.
- Assessment (load-bearing pattern): the first published "L2" system where a *motion* stream is emitted at the codec rate alongside speech — exactly the architecture for "listen-speak-move" at 12.5 Hz, with a faster lane for interpolation.

### 3.11 ELaTE — laughter-controllable zero-shot TTS (Microsoft, 2024)
- URL (fetched HTML): https://arxiv.org/abs/2402.07383
- Voicebox-style flow-matching TTS, "335 million parameters", "24 Transformer layers"; pretrain LibriLight "60 thousand hours"; fine-tune "459.8 hours of speech containing laughter" (AMI, Switchboard, Fisher) with frame-level laughter-detector conditioning; control by "start and end times for laughing" or an example laugh; WER 2.2, SIM-o 0.662 on LibriSpeech; laughter timing correlation 0.673. No weights released.
- Assessment: laughter can be *placed at frame level* inside speech if you own the TTS; with a hosted Realtime API you cannot, so the dog's chuckle must come from a local sound bank or local TTS.

---

## 4. Listener / dyadic motion generation (reacting while listening)

### 4.1 Learning to Listen (L2L), Ng et al., CVPR 2022
- URL (fetched via ar5iv): https://arxiv.org/abs/2204.08451
- Data: "72 hours of in-the-wild conversations" from 6 YouTube channels; "All frames are extracted at 30 fps"; 3DMM 53 expression + jaw + head rotation.
- Model: motion VQ-VAE "K=200" codes, d=256; autoregressive transformer with cross-attention over speaker audio+motion; prediction window "w=8" frames (267 ms) over T=64.
- Results: L2 33.16 (expr), FD 3.55; user study "75.3% of the total 150 evaluators preferred Ours over NN", 71.1 % over the audio+motion ablation. Code/data released.
- Assessment (load-bearing pattern): discrete listener-motion tokens predicted ~250 ms at a time from speaker audio — direct template for a "dog reaction token" model (K≈50-200 codes over head/ears/tail/posture).

### 4.2 Can Language Models Learn to Listen? (LM-Listener), ICCV 2023
- URL (fetched via ar5iv): https://arxiv.org/abs/2308.10897 ; code https://github.com/sanjayss34/lm-listener
- Input: speaker transcript tokens with timestamps; output: listener VQ motion tokens appended as new vocabulary; backbone "GPT2-Medium, which has 24 layers and 345M parameters"; data: one listener (Trevor Noah), "2366 training, 222 validation, and 543 test segments" of up to 8 s; FD 18.22 vs GT 2.59; preference "92.8% preferred Ours over Uncond", "55.7%" over L2L (audio-based), 49.7 % vs ground truth. Initialising from a text-pretrained LM "results in significantly higher quality listener responses than training a transformer from scratch".
- Assessment (load-bearing): a text LM fine-tuned to emit motion tokens interleaved with words learns *semantically* timed reactions (laugh at the punchline) — this is the mechanism for "chuckle because the joke was funny" rather than "because the prosody rose".

### 4.3 Dyadic Interaction Modeling (DIM), ECCV 2024
- URL (abstract fetched): https://arxiv.org/abs/2403.09069 ; code https://github.com/Boese0601/Dyadic-Interaction-Modeling
- Masked + contrastive pretraining on both speaker and listener VQ motion; SOTA on listener metrics at publication. Numbers not on the abstract page.

### 4.4 From Audio to Photoreal Embodiment (Meta/Berkeley, CVPR 2024)
- URL (fetched HTML): https://arxiv.org/abs/2401.01885
- Data: "8 hours of video data from 4 participants, each engaging in 2 hours of paired conversational data"; both speakers' audio as input (Wav2Vec).
- Model: VQ-Transformer emits "guide poses at 1fps", diffusion "in-fills intricate motion details ... at a higher fps" (30 fps); face diffusion conditioned on audio + lip regressor; outputs 104 joint angles + 256-d face codes.
- Results: FD_g 2.94±0.2, FD_k 0.96±0.07; "70% of evaluators preferring our method" over the LDA diffusion baseline. Code and dataset released.
- Assessment (load-bearing pattern): **coarse tokens at 1 Hz + fine generator at 30 Hz** is a validated two-rate factorisation — matches Parcel's per-utterance/50 Hz split.

### 4.5 INFP (ByteDance, 2024) and ARIG (ICCV 2025) — real-time interactive heads
- INFP (fetched HTML): https://arxiv.org/abs/2412.04037 — DyConv dataset "over 200 hours"; "dynamically alternates between speaking and listening state, guided by the input dyadic audio" with no explicit role switch; vs DIM: SSIM 0.834 vs 0.651, FID 15.727 vs 34.361, SID 2.613 vs 0.766; user study 20 participants: naturalness 4.38 vs 2.71; 4-block diffusion transformer; CC BY-NC-SA.
- ARIG (fetched HTML): https://arxiv.org/abs/2507.00472 — frame-wise autoregressive, continuous (non-quantised) diffusion "15 diffusion steps", **31 fps** real-time; 200+ h (MultiDialog, ViCo, RealTalk); seven conversational states ("regular speaking, regular listening, receiving feedback during speech, pausing to think, being interrupted, waiting during others' pauses, and giving feedback while listening"); vs DIM on RealTalk: SyncScore 7.218 vs 4.192, FID 21.64 vs 26.29, SID 2.428 vs 1.083.
- Assessment: state-of-the-art shows (a) speaking/listening should be *implicit* in a single dual-audio-conditioned generator, (b) frame-wise AR diffusion at ~30 fps with ~15 steps is real-time on a GPU — a candidate for the Orin motion lane if the motion space is tiny.

### 4.6 Seamless Interaction (Meta, 2025) — the dyadic dataset
- URL (fetched HTML): https://arxiv.org/abs/2506.22554
- "4,065 hours" of dyadic footage, "4,284 unique participants", "64,739 interactions across 5,098 sessions"; Naturalistic 2,745 h / Improvised 1,320 h; "UHD 4k ... at 30 FPS", 48 kHz lapel audio; parametric body/hands + face representations + transcripts; on Hugging Face under CC BY-SA 4.0 (per arXiv header). Models: audio-only and audiovisual dyadic motion models (joint vs cascaded face+body), with emotion and expressivity control and "LLM-Guided Codebook Generations" using emotion and semantic-gesture codebooks. Model sizes/latency not exposed in the fetched sections.
- Assessment (load-bearing for data): the only >1,000 h open dyadic corpus with listener behaviour; pretraining a human listener-reaction model here and distilling to dog tokens is feasible on the desktop GPU.

---

## 5. Quadruped / pet robots reacting to speech or affect

### 5.1 Sony aibo (ERS-1000) help guide — "aibo's desires and emotions"
- URL (fetched): https://helpguide.sony.net/aibo/ers1000/v1/en-us/contents/TP0001970094.html
- Four desires (affection, curiosity, sleep, expressing feelings); emotions "similar to delight, anger, sorrow and pleasure"; delight "when it is complimented, or when it finds one of its favorites"; sadness "when there is no one to play with"; surprise "when it hears a loud sound"; expression through "eye or tail movement or its tricks"; "Over time, these shifts in mood affect aibo's behavior and growth". No numbers.
- Assessment: the product-level spec of the behaviour Parcel wants; the mechanism is an internal affect state modulated by events — consistent with a small learned "affect state -> reaction prior".

### 5.2 Uni-Mo / Quad-Imaginarium (2026) — expressive Go2 motion from video priors
- URL (fetched HTML): https://arxiv.org/html/2606.28237 ; data https://github.com/GaoLii/Quad-Imaginarium.git (CC BY 4.0 header)
- "7,488 language-annotated quadruped motions (18.5 hours)"; pipeline: Wan2.2 video diffusion fine-tuned (LoRA + identity-consistency loss) -> 3D reference trajectory -> "PPO tracking policy"; validated on Unitree Go2: "96.7% deployment success rate" over 392 sampled motions; 97.6 % in sim. No latency numbers.
- Assessment (load-bearing for the motion vocabulary): an open, language-labelled Go2 expressive-motion corpus with an RL tracker — the missing "gesture library" for a dog body; text-conditioned selection can be driven by the reaction-token layer.

### 5.3 LLM-powered interactive robotic action synthesis (Go2, 2026)
- URL (fetched HTML): https://arxiv.org/html/2606.31158v1
- Unitree Go2; "OpenAI's Whisper 'small' model for transcription"; "Qwen3:0.6b was used as Ollama-based LLM"; gestures via video, music via beat detection; LLM maps to an "Action Space" of executables; evaluation is a single anecdote (handstand on fist gesture); no latency, no user study, no code.
- Assessment: confirms the current state of Go2 + speech work is command-mapping, not full-duplex reaction; no numbers to build on.

### 5.4 e-Inu (2023) — simulated quadruped with "emotional sentience"
- URL (abstract fetched): https://arxiv.org/abs/2301.00964 (CC BY-SA 4.0)
- Speech-emotion accuracy "63.5%", face-emotion "99.66%"; PPO gait in sim; responds "via sounds and expression on a screen".
- Assessment: weak; shows the naive SER->reaction mapping and its accuracy ceiling.

### 5.5 Frontiers 2026 review of AI-driven quadrupeds
- URL (fetched): https://www.frontiersin.org/journals/neurorobotics/articles/10.3389/fnbot.2026.1855550/full
- No coverage of affect/social behaviour; names CognitiveDog, QUAR-VLA, NaVILA as early language->action systems; barriers "reliable grounding, action feasibility, latency, computation load, safety constraints, and hardware validation".
- Assessment: negative result — as of 2026 there is no peer-reviewed quadruped system with measured speech-affect-driven reaction timing. Parcel would be first; the evidence must come from the human/avatar literature above.

---

## 6. What this means for Parcel

### 6.1 Re-framing the ask
"Generate movement commands as a full-duplex system steerable by voice and learned from the state of the world" decomposes, on the evidence, into three *trainable* problems at three rates:

| Rate | Problem | Evidence-backed model class | Runs where |
|---|---|---|---|
| per utterance (~0.2-1 Hz) | *What* to react with and *how much*: semantic appraisal (was that a joke? is the owner sad? am I lost?), reaction budget, style | LM-Listener (GPT2-M emitting motion tokens interleaved with words), F-Actor behaviour-count instructions, Moshi inner-monologue + style tags, Seamless "LLM-guided codebooks" | hosted text model (<= $100/mo) or a local 1-3B LM |
| 10-12.5 Hz | *When* to react: turn-shift, backchannel, nod, laugh-back, look-at-owner probabilities 500 ms ahead | VAP (+BC, +nod heads), Inoue laugh detector/shared-laughter predictor | local CPU/GPU on Orin (RTF 0.19-0.73 on desktop CPUs) |
| 30-50 Hz | *How* the body moves: continuous head/ears/tail/posture/gait modulation, blending, safety | ZeroEGGS-style GRU (4 ms/frame), ARIG-style frame-wise AR diffusion (31 fps), or codebook lookup into Quad-Imaginarium clips tracked by the RL policy | the existing 50 Hz body-intent lane; safety layer keeps authority |

The coarse-then-fine split is validated by "From Audio to Photoreal Embodiment" (1 fps guide poses + 30 fps diffusion) and by Moshi-Face (motion tokens at the 12.5 Hz codec rate).

### 6.2 The two target behaviours
- **"Learn to chuckle if a joke was funny."** Evidence says: (a) audio-only shared-laughter prediction tops out near F1 30 (Inoue); (b) text-conditioned listener models capture semantics (LM-Listener 92.8 % over unconditioned; 55.7 % over audio-only L2L); (c) the reaction must land within ~2 s of the owner's laugh and ideally the *body* reaction (head bob, tail) within ~200-500 ms (Stivers; VAP 500-ms lead). Design: 10 Hz laugh-detector + VAP-BC head fires a fast, low-amplitude "amused" body reaction; the per-utterance LM decides whether to escalate to an audible chuckle (a local sound, since the hosted Realtime API cannot place laughter frame-accurately — ELaTE shows that requires owning the TTS). Learning signal: Parcel's `skill_outcomes` can log (context, chuckle?, owner-laughed-within-3-s?, owner said "stop"?) and fit a per-owner logistic/bandit policy on top — the exact structure of Inoue's LR predictor, but with text + owner-history features they lacked.
- **"Learn to look back at the owner when it gets lost."** This is a *listener-style* gesture triggered by world state (localisation confidence, owner distance/bearing, no owner voice for N s), not by speech. The nodding model shows gesture timing can be predicted 500 ms ahead from context; Boston Dynamics' Spot demo did the "turn toward nearest person" version by hand. Design: add a "look-at-owner" head to the 10 Hz predictor whose inputs include VAP audio features *and* a small world-state vector (owner bearing, distance, localisation covariance, seconds since last owner utterance); train in sim with a reward for owner-gaze events that precede successful re-acquisition, then fine-tune on real logs. Keep the safety layer as the only thing allowed to actually turn the body.

### 6.3 Concrete 12-hour experiment plan (desktop, no robot)
1. **Hour 0-2 — stand up the timing lane.** Clone VoiceActivityProjection (MIT) and VAP-Realtime (MIT code); run the English Switchboard VAP at 10 Hz with 1-5 s context on CPU; log p_now/p_future and VAP-BC probabilities against the reSpeaker XVF3800 + the robot's own TTS stream as the two channels (the model *expects stereo = both parties*).
2. **Hour 2-5 — add reaction heads.** Following "Yeah, Un, Oh", add linear heads for {backchannel, nod/head-tilt, amused, look-at-owner} with positives 500 ms before the event. Labels: mine your existing conversation logs and/or Seamless Interaction (CC BY-SA) for human listener head events; map to dog tokens. Expect F1 in the 30-45 range; that is normal.
3. **Hour 5-8 — per-utterance appraisal.** Fine-tune a small LM (LM-Listener recipe: motion tokens as extra vocabulary, initialise from a text LM) or, cheaper, prompt the hosted text model to emit a JSON "reaction budget" per turn ({amused: 0-1, chuckle: bool, look_at_owner: n, style: ...}) in the F-Actor style; feed it as conditioning to the 10 Hz heads.
4. **Hour 8-11 — motion lane in MuJoCo.** Build a 50-200-code dog reaction codebook (L2L K=200 at 30 fps, w=8) over head/neck/body posture from Quad-Imaginarium clips; train a ZeroEGGS-style GRU decoder (target << 4 ms/frame) that blends reaction codes into the idle-breathing expression layer; verify the safety layer can pre-empt any code within one 50 Hz tick.
5. **Hour 11-12 — measure.** Report: reaction-onset latency from owner laugh end to body onset (target <= 300 ms) and to chuckle onset (target <= 1 s, hard limit 2 s per Inoue); backchannel precision/recall at 500 ms lead; and Full-Duplex-Bench-style "no takeover during owner pauses" rate.

### 6.4 What NOT to do (per the evidence)
- Do not put a 7B full-duplex model (Moshi) in the reaction loop on Orin as the first experiment: 24 GB bf16, and its measured backchannel frequency is 0.001; use it, if at all, as an *offline data generator* (its synthetic-dialogue recipe with 92 style tags is the reusable part).
- Do not ask an LLM to author motion online (EMOTION: 26.8 s per gesture; Spot: ~6 s end-to-end).
- Do not optimise gesture realism metrics (FGD); the field's own re-evaluation shows realism is saturated and FGD correlates poorly with perception; optimise timing and appropriateness.
- Do not ship ZeroEGGS code (Ubisoft proprietary licence) or rely on VAP-Realtime *weights* (academic-only) in a product path; retrain from the MIT code.

---

## 7. Source index (all fetched)
- GENEA 2022 journal: https://arxiv.org/abs/2303.08737 (PDF read) — 2024
- GENEA 2023: https://arxiv.org/abs/2308.12646 (PDF read) — 2023
- DiffuseStyleGesture+: https://arxiv.org/abs/2308.13879 (HTML read) — 2023
- Deichler et al. CSMP+diffusion: https://arxiv.org/abs/2309.05455 (abstract) — 2023
- GENEA Leaderboard: https://arxiv.org/abs/2410.06327 (abstract) — 2024
- Reliable human evals on BEAT2: https://arxiv.org/abs/2511.01233 (HTML read) — 2025
- DiffuseStyleGesture: https://arxiv.org/abs/2305.04919 (PDF read); https://github.com/YoungSeng/DiffuseStyleGesture — 2023
- EMAGE/BEAT2: https://arxiv.org/abs/2401.00374 (PDF read); https://github.com/PantoMatrix/PantoMatrix — 2024
- ZeroEGGS: https://arxiv.org/abs/2209.07556 (ar5iv read); https://github.com/ubisoft/ubisoft-laforge-ZeroEGGS — 2022/2023
- Audio2Gestures: https://arxiv.org/abs/2108.06720 (abstract) — 2021
- Yoon 2019 NAO: https://arxiv.org/abs/1810.12541 (PDF read) — 2019
- Yoon 2020 trimodal: https://arxiv.org/abs/2009.02119 (abstract) — 2020
- Trimodal on Pepper: https://arxiv.org/abs/2409.05010 (PDF read) — 2024
- Pepper low-latency LLM framework: https://arxiv.org/abs/2603.21013 (HTML read) — 2026
- EMOTION humanoid: https://arxiv.org/abs/2410.23234 (HTML read) — 2024
- Boston Dynamics Spot chat: https://bostondynamics.com/blog/robots-that-can-chat/ — 2023
- Ameca: https://engineeredarts.com/robot/ameca/ — vendor
- Stivers 2009: https://pmc.ncbi.nlm.nih.gov/articles/PMC2705608/ — 2009
- VAP 2022: https://arxiv.org/abs/2205.09812 (PDF read); https://github.com/ErikEkstedt/VoiceActivityProjection — 2022
- Real-time VAP: https://arxiv.org/abs/2401.04868 (PDF read); https://github.com/inokoj/VAP-Realtime — 2024
- Yeah, Un, Oh: https://arxiv.org/abs/2410.15929 (HTML read) — 2024/2025
- Inoue shared laughter: https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.933261/full — 2022
- Moshi: https://arxiv.org/abs/2410.00037 (PDF read); https://github.com/kyutai-labs/moshi — 2024
- Full-Duplex-Bench: https://arxiv.org/abs/2503.04721 (HTML read) — 2025
- Full-duplex survey: https://arxiv.org/html/2606.19453v1 — 2026
- F-Actor: https://arxiv.org/abs/2601.11329 (PDF read) — 2026
- Moshi-Face: https://arxiv.org/html/2606.21970v1 — 2026
- ELaTE: https://arxiv.org/abs/2402.07383 (HTML read) — 2024
- Learning to Listen: https://arxiv.org/abs/2204.08451 (ar5iv read) — 2022
- LM-Listener: https://arxiv.org/abs/2308.10897 (ar5iv read) — 2023
- DIM: https://arxiv.org/abs/2403.09069 (abstract) — 2024
- Audio to Photoreal Embodiment: https://arxiv.org/abs/2401.01885 (HTML read) — 2024
- INFP: https://arxiv.org/abs/2412.04037 (HTML read) — 2024
- ARIG: https://arxiv.org/abs/2507.00472 (HTML read) — 2025
- Seamless Interaction: https://arxiv.org/abs/2506.22554 (HTML read) — 2025
- aibo help guide: https://helpguide.sony.net/aibo/ers1000/v1/en-us/contents/TP0001970094.html — vendor
- Uni-Mo / Quad-Imaginarium: https://arxiv.org/html/2606.28237 — 2026
- Go2 LLM action synthesis: https://arxiv.org/html/2606.31158v1 — 2026
- e-Inu: https://arxiv.org/abs/2301.00964 (abstract) — 2023
- Frontiers quadruped review: https://www.frontiersin.org/journals/neurorobotics/articles/10.3389/fnbot.2026.1855550/full — 2026

Not fetched / not found within budget: INFP fps figure; Seamless Interaction model sizes and licence for model weights; any peer-reviewed quadruped system with speech-affect reaction latency numbers (appears not to exist); Yoon 2020 full text (PDF > fetch limit).
