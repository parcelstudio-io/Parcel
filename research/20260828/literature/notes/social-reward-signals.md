# Social reward signals: what a companion dog can reliably extract from the owner's reactions

Research note for Parcel, 2026-08-28. Topic: learning social/affective behaviour from the owner's reactions —
what signals a robot can reliably extract to learn "was that joke funny" and "did the owner approve of what I just did".

Method: every source below was located with web search and then fetched and read (arXiv abstract/HTML, PDF
converted with `pdftotext`, GitHub README, vendor model card). Numbers are copied from the fetched text. Two
papers that are only on the ACM DL (Weber et al. ICMI 2018; Vilk & Fitter HRI 2020) could not be fetched
directly (HTTP 403; Semantic Scholar API rate-limited) and are cited through sources that were fetched — this is
flagged wherever it matters.

Sections:
1. Laughter detection (audio)
2. Facial expression / smile / engagement (vision, multimodal)
3. Humor and funniness prediction: datasets, SOTA, and LLM-vs-human agreement
4. Engagement, rapport and UX estimation in HRI
5. RL / preference learning from social signals on real social robots; what commercial companions do
6. Backchannel timing models
7. Assessment: the most reliable low-cost reward design for "chuckle if funny" and "owner approval"
8. What this means for Parcel
9. Open questions

---

## 1. Laughter detection (audio)

### 1.1 Gillick, Deng, Ryokai, Bamman — "Robust Laughter Detection in Noisy Environments" (Interspeech 2021)
- Paper: https://people.ischool.berkeley.edu/~kimiko/papers/Gillick.2021.Interspeech.pdf (fetched, PDF→text)
- Code/models: https://github.com/jrgillick/laughter-detection (fetched; MIT licence; PyTorch; 291 stars; default
  threshold 0.5, min segment length 0.2 s)
- Training data: Switchboard telephone corpus, "about 260 hours of speech from 543 total speakers", laughter
  annotated to within a fraction of a second. Evaluation data they created: a random sample of 1,000 AudioSet
  clips tagged "laughter" (out of 5,696 such 10-s clips), manually segmented for laughter start/end, plus 1,000
  random AudioSet clips without laughter. A second annotator re-annotated 10% of the data: "95.2% per-frame
  inter-annotator agreement rate".
- Model: an adaptation of ResNet-18 on spectrograms; predictions at every frame with a 1-second sliding window
  of context; frame rate 43.1 fps (librosa default); audio downsampled to 8 kHz; batch size 32. Baseline: 39 MFCC
  + delta features with a 3-layer network (prior published approach).
- Results (Table 2, segment-based per-frame P/R/F1, 95% bootstrap CIs):
  - Trained on Switchboard (strong labels), tested on Switchboard: ResNet P 0.677 / R 0.830 / F1 0.747;
    ResNet+Augmentation P 0.676 / R 0.847 / F1 0.752.
  - Trained on Switchboard, tested on AudioSet (in-the-wild): ResNet F1 0.573; ResNet+Aug P 0.508 / R 0.759 /
    F1 0.608.
  - Trained on AudioSet weak labels, tested on AudioSet: ResNet+Aug P 0.385 / R 0.925 / F1 0.545 (very high
    recall, low precision).
  - MFCC baseline on Switchboard: F1 0.688 (text) — it "is substantially outperformed even in this environment by
    ResNet models that operate directly on the underlying spectrogram, which achieve an F-Score of 0.75".
- Key quote on the wild: in some real-world recordings with an earlier MFCC detector, "false positives
  outweighed the correctly identified laughter by as much as a factor of 10, calling into question the practical
  utility of existing methods for laughter detection."
- Assessment: this is the canonical open laughter segmenter and the best-documented statement of the
  clean-to-wild gap. Expect F1 ≈ 0.6 in the wild and precision ≈ 0.5 unless you retrain on in-domain audio.
  For a reward signal, precision matters more than recall (a false "laugh" reinforces the wrong action); operate
  at a high threshold and gate on speaker identity / the mic array's DoA.

### 1.2 Omine, Akita, Tsuruno — "Robust Laughter Segmentation with Automatic Diverse Data Synthesis" (Interspeech 2024)
- https://www.isca-archive.org/interspeech_2024/omine24_interspeech.pdf (fetched, PDF→text)
- Idea: no human annotation — synthesize 0–4 laughter episodes (from VocalSound 21,024 crowdsourced clips and
  other laughter corpora, incl. synthetic crowd laughter made by superimposing 5–30 samples) into base audio from
  the Spotify Podcast Dataset (1,456 episodes from 764 programs, filtered so YAMNet's laughter-related
  probability stays below 0.05) and AudioSet 7-s excerpts, with pitch/speed/loudness/reverb/compressor/low-pass
  and bit-depth degradation augmentations.
- Model: wav2vec 2.0 extended for frame classification (`Wav2Vec2ForAudioFrameClassification`), pre-trained
  checkpoint `jonatasgrosman/wav2vec2-large-xlsr-53-english`; 7.0-s input, a class every ~0.02 s (349-bit
  annotation vector); "approximately 315 million parameters"; trained 2,500 steps; "approximately 75 minutes to
  train, and 1 minute to segment an hour-long audio file on an i9-9900K CPU with 32 GB of memory and an NVIDIA
  GeForce RTX 2080 Ti GPU".
- Detection results (Table 1, F1): AMI meetings — Gillick 0.583, Gillick arch + their data 0.594, Ours 0.784;
  MAHNOB laughter DB (22 subjects) — Gillick 0.618, Ours 0.890; Gillick's own AudioSet test (840 laughter +
  909 non-laughter samples) — Gillick 0.844, Ours 0.865; their Spotify test set — Gillick 0.897, Ours 0.943.
  Gillick's model keeps high precision (0.90–0.93) but low recall (0.43–0.46) on AMI/MAHNOB.
- Segmentation results (Table 2, true positives only): on Gillick's set F1 0.600 → 0.638 and start-time MAE
  2.070 s → 1.085 s; on their set F1 0.617 → 0.789 and start-time MAE 1.500 s → 0.314 s, end-time MAE 0.573 s.
- Assessment: the most practical current recipe for a *retrainable* laughter detector: you can manufacture an
  in-domain training set (your own room, your own mic array, your own speaker) with no labelling. 315 M params is
  heavy for Orin at 50 Hz, but the same recipe works with wav2vec2-base (~95 M) or with Gillick's ResNet
  architecture (their "Gillick + our data" rows show the synthesis alone helps the small model).

### 1.3 MultiLinguahah — unsupervised multilingual laughter segmentation (arXiv 2605.06309, 2026)
- https://arxiv.org/pdf/2605.06309 (fetched, PDF→text)
- Pipeline: auditok energy-based non-speech segmentation → BYOL-A self-supervised audio embeddings → Isolation
  Forest anomaly detection (contamination "auto"); no labels. Hardware: RTX 2080.
- Test data: Standup4AI (3,617 stand-up videos, 7 languages; test split 100 videos, 8.53 h, 3,453 laughter
  events); Friends sitcom (~10 h); Kuznetsova bilingual RU/EN stand-up (10 test videos, 617 laughter instances);
  AudioSet (724 available videos) and FSD50K (40,966 clips, 80 h) used for training BYOL-A.
- Result pattern (Table 1, F1 at two IoU thresholds): Gillick et al. degrades badly across languages/domains —
  F1 values in the table range from 0.130 to 0.646 (e.g., 0.456, 0.646, 0.544, 0.565, 0.294, 0.245, 0.149,
  0.144, 0.237, 0.130, 0.439, 0.578, 0.240); MultiLinguahah 0.506 / 0.585 on rows where Gillick has 0.456 /
  0.439; the combination Omine + MultiLinguahah reaches 0.848 (vs Gillick 0.646) and 0.638 (vs 0.578). In US
  English "Omine et al.'s model achieves the best results".
- Assessment: confirms (a) supervised English/telephone detectors do not transfer, (b) the Omine synthetic
  recipe is the current strongest supervised option, (c) a cheap unsupervised anomaly detector over a frozen
  audio embedding is a viable, label-free fallback. For Parcel (one owner, one room) a personal calibration is
  the real answer, not multilinguality.

### 1.4 SMILE-Next — LLMs that detect, classify and reason about laughter (arXiv 2605.28084, 2026)
- https://arxiv.org/html/2605.28084 (fetched)
- 3,590 video clips, 6,386 QA pairs. Detection: 2,384 samples (1,565/460/359); type classification 1,957
  samples (1,636/207/114); reasoning 2,045. Laughter types: mirthful, polite, satirical.
- Best model (LLaMA3 backbone) — detection F1 0.9674 / acc 0.9696; type classification F1 0.8067 / acc 0.8425;
  reasoning BLEU-4 0.2427, METEOR 0.2328, ROUGE-L 0.4168, SentBERT 0.7828. Baselines: Qwen-Omni-7B,
  MiniCPM-o-2.6, Video-LLaVA, Qwen2.5-VL.
- Assessment: the important design fact is the taxonomy — polite laughter is a *social lubricant*, not a
  funniness signal. A reward that cannot distinguish mirthful from polite laughter will learn that the owner
  "liked" things they were merely being polite about. An LLM is not needed for this; laughter duration/intensity
  plus a smile (Duchenne-like) cue is the cheap proxy.

### 1.5 General-purpose AudioSet taggers that expose a "Laughter" class
- YAMNet — https://github.com/tensorflow/models/tree/master/research/audioset/yamnet (fetched). MobileNet-v1
  depthwise-separable; "3.7M weights"; "69.2M multiplies for each 960ms input frame"; 521 classes (6 of 527
  dropped after fairness review); 25 ms window / 10 ms hop, 0.96 s patches, needs 975 ms of audio for the first
  output; AudioSet eval (20,366 segments): balanced mAP 0.306, d-prime 2.318, lwlrap 0.393. Licence: the
  tensorflow/models repo is Apache 2.0 (https://github.com/tensorflow/models/blob/master/LICENSE fetched).
- PANNs — https://arxiv.org/pdf/1912.10211 (fetched, PDF→text). AudioSet 1.9 M clips, 527 classes, hop 320
  (10 ms) at 32 kHz. Params / mAP: CNN6 4,837,455 / 0.343; CNN10 5,219,279 / 0.380; CNN14 80,753,615 / 0.431;
  MobileNetV1 4,796,303 / 0.389 (3.61 GFLOPs); MobileNetV2 4,075,343 / 0.383 (2.81 GFLOPs); LeeNet11 748,367 /
  0.266; ResNet38 73.8 M / 0.434; Wavegram-Logmel-CNN 81,065,487 / 0.439. Class-wise AP is uncorrelated with
  clip count ("Hoot" 106 clips → AP 0.86; "Inside, small" 70,159 clips → AP 0.19). 16 kHz training only costs
  0.431 → 0.427 mAP.
- AST — https://github.com/YuanGongND/ast (fetched; BSD-3-Clause): single model 0.459 mAP (weight averaging),
  3-model ensemble 0.475, 6-model ensemble 0.485; ESC-50 95.75%; Speech Commands 98.12%; input 10.24 s × 128
  bins at 16 kHz. HF card https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593 (fetched): 86.6 M params.
- BEATs — https://arxiv.org/abs/2212.09058 (fetched): AudioSet-2M mAP 50.6% with no external data; ESC-50
  98.1%; code https://aka.ms/beats. Parameter count is not on the abstract page; the OpenBEATs paper
  (https://arxiv.org/html/2507.14129, fetched) states BEATs is "90M" parameters (OpenBEATs-Base 90 M, Large 300 M).
- Whisper-AT — https://github.com/YuanGongND/whisper-at (fetched; BSD-2-Clause). Frozen Whisper encoder +
  Time-and-Layer-wise Transformer head → 527 AudioSet classes with "less than 1%" extra compute over ASR.
  AudioSet mAP: tiny 36.5, base 37.6, small 39.8, medium 40.8, large-v2 41.7.
- Assessment: all of these give a per-second "Laughter" probability for free. YAMNet / PANNs-MobileNetV1
  (≈4–5 M params) are trivially Orin-feasible alongside everything else; Whisper-AT is the elegant option if the
  duplex voice stack already runs a Whisper encoder (the laughter tag rides on the ASR encoder). None is a
  *segmenter*: they give 1-s tags, so onset timing (needed to credit the right utterance/motion) comes from a
  Gillick/Omine-style frame model or from VAP-style voice-activity features.

### 1.6 Owner vocal affect (not laughter): emotion2vec and Wav2Small
- emotion2vec (ACL 2024 Findings) — https://arxiv.org/html/2312.15185v1 (fetched). data2vec-style 7-layer CNN
  + 12-layer Transformer, ~93.79 M params upstream (+0.20 M linear head); pre-trained on 262 h of unlabeled
  emotion speech (IEMOCAP, MELD, MEAD, CMU-MOSEI, MSP-Podcast); IEMOCAP WA 71.79 / UA 72.69 / WF1 71.80 vs
  WavLM-base WA 65.94, HuBERT-base 64.92; consistent gains across 10 languages / 13 datasets; code
  https://github.com/ddlBoJack/emotion2vec.
- Wav2Small (arXiv 2408.13920, fetched abstract) — "only 72K parameters", ONNX quantized 120 KB, distilled from
  a Transformer teacher that sets "a new Sota on the MSP Podcast dataset of valence CCC=0.676"; predicts
  arousal/dominance/valence.
- Assessment: valence/arousal from the owner's *voice* is a second, cheap approval channel (a warm "good
  boy" vs a flat "stop"). Valence from speech is hard (CCC ≈ 0.68 at the SOTA teacher), so use it as a
  coarse sign, not a magnitude.

## 2. Facial expression / smile / engagement (vision)

### 2.1 MediaPipe Face Landmarker + Blendshape model (Google)
- Task page: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker (fetched). Bundle =
  BlazeFace short-range detector (192×192) + FaceMesh-V2 (256×256, 478 3-D landmarks) + Blendshape model
  (input 1×146×2), float16.
- Blendshape model card: https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf
  (fetched, PDF→text). "52 facial blendshape coefficients as float values in [0, 1] range"; input is 146 of the
  478 landmarks; indices 44 = mouthSmileLeft, 45 = mouthSmileRight (also cheekSquint, eyeSquint, jawOpen,
  browInnerUp, etc.); licensed Apache 2.0; evaluation is MAD/STDEV of predicted vs average activation across
  subjects, by gender and skin tone; known failure modes: face rotated > 80°, < 50% visible; the card warns of
  "jittering" in blendshapes on video.
- Assessment: this is the cheapest on-device smile/AU-like signal (mouthSmile ×2 + cheekSquint ≈ a Duchenne
  proxy), runs on phone CPUs, and gives continuous [0,1] values you can threshold and smooth. Its blendshapes
  are *not* validated action units; treat them as a proxy calibrated per owner.

### 2.2 HSEmotion lightweight FER (Savchenko) — https://github.com/av-savchenko/face-emotion-recognition (fetched)
- MobileNet 7-class AffectNet 64.71%, 14 MB, 16 ± 5 ms (Samsung Fold 3); EfficientNet-B0 64.63% (7 cls) /
  60.95% (8 cls), 16 MB, 59 ± 26 ms; EfficientNet-B2 66.34% / 63.03%, 30 MB, 191 ± 18 ms. Apache-2.0, "no
  limitation for both academic and commercial usage". Backbones pre-trained on VGGFace2 for identity.
- Assessment: 7-class accuracy in the mid-60s on AffectNet is the state of small-model FER — categorical
  emotion is unreliable frame by frame; smile intensity and change-over-time are far more robust than a
  "happy/neutral" label.

### 2.3 Embedded smile detector on Jetson (arXiv 1807.10570, fetched PDF→text)
- Full pipeline (Viola-Jones face → alignment → CNN smile classifier) on NVIDIA Jetson TX2, asynchronous
  threads, "grab and draw frames at 20-25 fps". Model table: MobileNet α=0.25: 27.3 FPS on Jetson, 0.21 M
  params, 0.03 GFLOPs; MobileNet α=0.75: 24.2 FPS, 1.8 M params; Inception V3: 7.9 FPS, 21.8 M params, 2.8
  GFLOPs; VGG16 "about 750x" the params of the smallest. Datasets: GENKI-4K (4,000 faces), CelebA (40
  attributes), ChaLearn LAP 2016.
- Assessment: an older Jetson TX2 already ran a whole smile pipeline at 20–25 fps; Orin has headroom to run
  smile + engagement + laughter concurrently with the 50 Hz body-intent lane.

## 3. Humor / funniness prediction: datasets, SOTA, LLM-vs-human agreement

### 3.1 rJokes (Weller & Seppi, LREC 2020)
- Paper https://aclanthology.org/2020.lrec-1.753.pdf (fetched, PDF→text); data https://github.com/orionw/rJokesData
  (fetched; data under Reddit's Licence/ToS, remove posts on request).
- 573,335 English jokes from r/Jokes over 11 years (from 1.1 M scraped posts); ~20% earn no upvote; body 192 ±
  503 tokens, punchline ~48 ± 26 tokens. Regression label = log(upvotes) rescaled "from 0-136,353 down to
  0-10", zeros left unchanged; posts before 2016 dropped → 432,457 jokes for the regression task.
- Baselines (large models, 5 epochs, test set): BERT RMSE 1.619 / Pearson 0.471 / Spearman 0.430; RoBERTa
  1.614 / 0.474 / 0.435; XLNet 1.739 / 0.457 / 0.411.
- Assessment: upvotes are a crowd-aggregate, exposure-confounded proxy; the best text model explains only
  ~22% of the variance (r≈0.47). Useful as a *prior* over joke quality, useless as a per-owner reward.

### 3.2 SemEval-2020 Task 7 / Humicroedit (Hossain, Krumm, Gamon, Kautz)
- https://cs.rochester.edu/u/nhossain/hossain-semeval-2020-task-7.pdf (fetched, PDF→text)
- ~5,000 original headlines × 3 edits = 15,095 edited headlines; "Five judges were asked to rate the funniness of
  each edited headline" on a 0–3 scale; label = mean of five; split 64/16/20 (Subtask 1: 9,653 train / 2,420 dev
  / 3,025 test; extra FunLines 8,248). 48 teams (subtask 1), 31 (subtask 2).
- Results: BASELINE (predict the mean) RMSE 0.575; winner Hitachi 0.49725 ("a 13.5% improvement over
  BASELINE"); a BERT feature-based baseline with FunLines 0.522. Subtask 2 (which of two edits is funnier):
  baseline 49.5%, winner 67.43% accuracy; larger funniness gaps are easier. Annotator disagreement noted: for
  one headline σ = 0.9 across judges vs 0.4 for its sibling; topical biases ("Trump" + "hair" scored high).
- Assessment: the strongest shared-task result is only 13.5% better than predicting the mean, with five raters
  per item. Funniness of text is intrinsically low-agreement; any text-only reward model inherits this ceiling.

### 3.3 UR-FUNNY (Hasan et al., EMNLP 2019)
- https://aclanthology.org/D19-1211.pdf (fetched, PDF→text); arXiv https://arxiv.org/abs/1904.06618 (CC BY-NC-SA 4.0)
- 1,866 TED videos, 1,741 speakers, 417 topics, 90.23 h total; 8,257 humorous + 8,257 non-humorous instances.
  Labels come from the "laughter" markup in TED transcripts: the sentence immediately before the marker is the
  punchline, the sentences after the previous marker are context. Avg punchline 16.14 words, 4.97 s.
- C-MFN baseline binary accuracy (Table 4): T 64.44, A+V 57.99, T+A 64.47, T+V 64.22, T+A+V 65.23; punchline-only
  64.47, context-only 58.45.
- Assessment: the important precedent for Parcel is *the label source*: audience laughter is used as the ground
  truth for "was that funny", and multimodal cues (prosody, gesture) add only ~1 point over text. That is the
  same construction as an online reward: laughter after the punchline = positive.

### 3.4 MUStARD (Castro et al., ACL 2019)
- https://arxiv.org/pdf/1906.01815 (fetched, PDF→text); https://github.com/soujanyaporia/MUStARD (fetched; MIT)
- 690 utterances (balanced) from Friends, The Golden Girls, The Big Bang Theory, Sarcasmaholics Anonymous, with
  context and speaker IDs; 5-fold CV. SVM baselines (weighted F): speaker-dependent T+A 66.2, A+V 65.7, T+A+V
  71.5 ("relative error rate reduction of up to 12.9%"); speaker-independent T 59.8, A 62.7, T+A 63.1, T+A+V 62.8.
- Assessment: sarcasm is the case where text alone is wrong and prosody carries the signal; speaker-independent
  accuracy collapses toward 60%. Relevant for reading owner approval: "great, thanks" said sarcastically.

### 3.5 ColBERT (Annamoradnejad & Zoghi)
- https://arxiv.org/abs/2004.12765 (fetched abstract). 200,000 short texts (100k jokes / 100k news); F1 0.982 on
  their set, 0.869 on Spanish tweets. Assessment: binary joke-vs-not is a solved and *irrelevant* task (source
  artefacts); it says nothing about funniness magnitude.

### 3.6 Humor in AI: New Yorker caption contest preferences (Zhang et al., NeurIPS 2024)
- https://arxiv.org/html/2406.10522 (fetched)
- 284,183,913 ratings over 2.2 M+ captions across 365 contests (avg 6,044 captions/contest); 1–3 scale
  (unfunny / somewhat funny / funny); a UCB bandit allocates ratings.
- Ranking benchmark (Table 2): GPT-4-Turbo (with text descriptions) 67% ; human crowdworkers (pairwise)
  61.67 ± 3.45; former New Yorker cartoon editor 94.28 ± 2.79.
- Fine-tuning (Table 3, win rate vs top-10 human captions): Mistral-7B DPO 9.34% overall / 10.44% best pick;
  Mistral-7B RLHF 8.79% / 2.20%; Claude-3-Opus 54.40% / 40.11%; GPT-4o 44.51% / 42.86%. Crowd preferred
  Claude captions 35.4% of the time vs top-10 humans; the expert only 1.6%.
- Assessment: even with a quarter of a billion ratings, RLHF/DPO on a 7 B model barely moves humor quality, and
  crowd vs expert judgments diverge massively (61.7 vs 94.3). Funniness is not a stable scalar to regress on.

### 3.7 Bridging the Creativity Understanding Gap (arXiv 2502.20356, fetched HTML)
- Pairwise "which caption is funnier" on New Yorker data; easy (#1–10 vs #1000–1009) and hard (#30–39 vs #300–309).
- Zero-shot GPT-4o 67.3% (easy); previous benchmark (Hessel et al. 2023) "around 67%". Persona prompting ≤ 76.5%.
  Fine-tuning on 5,580 pairs (279 cartoons × 20) with explanations → 82.4% easy / 63.2% hard. Human experts
  average 78% / 61.6%; best expert (Bob Mankoff) 85.33% / 68%; majority vote 84% / 66%. Models tested:
  GPT-4o, Claude 3.5 Sonnet, Gemini 2.0 Flash, o1, o1-preview, o3-mini, DeepSeek.
- Assessment: a few thousand human pairwise labels lift an LLM judge to expert level on *this* domain. The
  transferable lesson: small-scale preference alignment works for ranking when the domain is fixed — which is
  exactly the per-owner situation.

### 3.8 Cards Against LLMs (arXiv 2604.08757, 2026, fetched HTML)
- 148,497 online Cards-Against-Humanity games (Nov 2023–Apr 2025); 4,947 sampled rounds (10 candidates each).
- LLM accuracy at picking the human-chosen card: Claude ~18%, Grok ~17%, Gemini ~16%, DeepSeek ~14%, GPT ~13%;
  random 10%; popularity baseline 19.11%. Inter-model agreement 21.4–44.9% vs 13–18% with humans; position bias
  and topic bias (bodily/sexual over political).
- Assessment: an LLM zero-shot funniness judge is at or below a popularity heuristic. Do not use an LLM as the
  reward for "was that funny".

### 3.9 Oogiri multi-dimensional humor evaluation (arXiv 2511.09133, fetched HTML)
- 200 Japanese Oogiri topics (100 text, 100 image) × 8 response types; 4 native raters; six dimensions.
- Spearman with human Overall Funniness: Claude Sonnet 4 0.266, GPT-4.1 0.224, Gemini 2.5 Pro 0.169. GPT-4.1
  per-dimension: Novelty 0.361, Clarity 0.379, Relevance 0.441, Intelligence 0.352, Empathy 0.303. Humans gave
  irrelevant responses 0.681/4; LLMs gave them 2.411–3.291. "LLMs prioritize Novelty, whereas humans prioritize
  Empathy."
- Assessment: same conclusion as 3.8 with a different culture and format: ρ ≈ 0.2–0.27.

## 4. Engagement, rapport and UX estimation in HRI

### 4.1 Del Duchetto, Baxter, Hanheide — "Are You Still With Me?" (Frontiers in Robotics & AI 2020)
- https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2020.00116/full (fetched);
  https://arxiv.org/abs/2001.03515
- Data from the Lindsey museum tour-guide robot: 278 days deployed, 556 km, 2,691 guided tours; ~10 days 16 h of
  video collected, 5 h 50 min annotated (94 videos, 227 people, 53.74% female); 3 coders continuously annotating
  engagement in [0, 1]; inter-rater Spearman ρ 0.56–0.72 depending on smoothing.
- Model: ResNeXt-50 (ImageNet) → 2048-d → single-layer LSTM (2048) → sigmoid; robot's own camera.
- Results: test MSE 0.126, ρ = 0.634 (1-s smoothing); single-party MSE 0.087 / ρ 0.758; multi-party 0.136 /
  0.622. Transfer to UE-HRI (Pepper, different robot/camera/task) without adaptation: AUC-ROC 0.89 for binary
  engagement. Inference ≤ 200 ms per 10-frame sample, 5 Hz, GTX 1060, 5.4 GB. Model and code released.
- Assessment: a robot-POV engagement scalar is learnable, transfers across robots, and is cheap. It is the
  right *state* feature for "the owner is (not) with me" — i.e., the trigger for "look back at the owner".

### 4.2 MultiMediate'24 multi-domain engagement estimation (Müller et al., ACM MM 2024)
- https://arxiv.org/pdf/2408.16625 (fetched, PDF→text)
- Train: NOXI dyadic novice–expert corpus, "over 25 hours (x2)", 48 sessions train / 16 test, continuous
  engagement 0–1 by 2–7 raters (avg 3.6). Test: NOXI, NOXI additional languages, MPIIGroupInteraction (3–4
  person, 20-min discussions; val 6 recordings/21 people, test 6/23). Metric CCC.
- Baseline (MLP, 3×136): OpenFace 2.0 val 0.81 → NOXI test 0.28, MPIIGI 0.00; w2v-BERT 2.0 audio features NOXI
  test 0.64 → best average 0.41; eGeMAPS 0.39 avg; OpenPose 0.32; XLM-R text 0.23; on MPIIGI the best baseline is
  0.15. Winner USTC-IAT-United average CCC 0.68 (+0.27 over baseline); Li et al. 0.64 with a new NOXI SOTA of 0.76.
- Assessment: engagement estimators overfit their recording setup; audio (paralinguistics) transferred better
  than face features. Personal calibration in the owner's home is again the answer.

### 4.3 UX estimation via multi-instance learning of social signals (arXiv 2507.23544, fetched HTML)
- 22 participants (21 M / 1 F, mean age 21.1), 10 scenarios each → 220 interactions of 30–120 s (~5 turns) with
  Sota and a self-recommendation robot; 15-item questionnaire (UEQ-derived, 7-point).
- Features: OpenFace 2.0 faces (112×112) + mel-spectrogram voice; CNN+Transformer encoders, MIL, late fusion.
  Acc.7 35.1% vs third-party human evaluators ~23.0%; Acc.3 70.0% vs 64.0%; best items "annoying–enjoyable" and
  "bad–good". Attention peaks on mouth elevation / surprise and on tonal variation.
- Assessment: a model reading face+voice over a *whole* interaction predicts the user's own 3-level "was that
  good" better than a human observer — supporting an episode-level, not frame-level, approval reward.

### 4.4 Multimodal rapport estimation in real-world HRI (arXiv 2608.18401, 2026, fetched HTML)
- Drugstore in Japan, teleoperated Sota; 131 sessions → 62 analysed, 97 participants, mean 54.23 s (SD 42.42),
  7.06 utterances; CCR-8 rapport 1–5 by 3 raters, ICC(2,3) = .85, mean 3.72.
- Zero-shot Gemini 2.5 Flash on transcripts CCC 0.580 (PCC 0.665); supervised HuBERT-large audio 0.460; V-JEPA
  2.1 video 0.310; ST5 text 0.281; best fusion (Gemini + HuBERT + V-JEPA) CCC 0.656, PCC 0.717, MAE 0.471.
  V-JEPA collapses from 0.503 (one person) to 0.043 (three people).
- Assessment: for *rapport* over a short interaction, what was said (LLM over transcript) beats embeddings, and
  audio adds complementary signal. For Parcel's hosted text model this is a cheap slow-loop rapport score.

## 5. RL / preference learning from social signals on robots; what commercial companions do

### 5.1 EMPATHIC — task learning from implicit human facial feedback (Cui et al., CoRL 2020)
- https://proceedings.mlr.press/v155/cui21a/cui21a.pdf (fetched, PDF→text); code https://github.com/Pearl-UTexas/EMPATHIC
- 17 participants watched 3 Robotaxi episodes each (financially incentivised, told not to teach); 14 watched 7
  robot-sorting trajectories. OpenFace 2.0 head pose + facial action units at 30 fps; 7 annotated gestures
  (smile, pout, eyebrow-raise, eyebrow-frown, nod, shake, eye-roll).
- Human proxies could rank rewards from reactions only weakly (avg Kendall τ 0.209, p = .078; best 0.569, p = .004).
  The learned mapping beats random on held-out subjects (p = 0.0024 with the auxiliary gesture loss; 0.0207
  without). Online: 9/10 new participants' sessions beat a random policy; 7/10 ended with the optimal reward
  mapping most probable. Transfer to robot sorting: ranking 8 trajectories by mean positivity gives τ = 0.70
  (p = 0.034).
- Assessment: facial reactions carry enough information to *rank* outcomes, but the signal is weak per event,
  varies by person, and needs aggregation over an episode. This is the closest primary evidence for "owner
  approval from the face".

### 5.2 Facial feedback in TAMER at scale (arXiv 2001.08703, fetched abstract)
- 561 participants, Infinite Mario, CNN-RNN facial model. Instructing trainers to use their face plus a
  competitive element "improve the accuracies for estimating positive and negative feedback using facial
  expressions"; in simulation, facial responses "would significantly improve the performance of agents" only
  with strong prediction models. Assessment: unprompted faces are a weak reward; asking the owner to react
  (which a dog naturally elicits) strengthens it.

### 5.3 RL in social robotics survey (Akalin & Loutfi, arXiv 2009.09689, fetched PDF→text) — the concrete robot precedents
- Weber et al. [59] (ICMI 2018; primary on ACM DL, not fetchable here — HTTP 403): Reeti robot adapts its sense
  of humour with Q-learning + linear function approximation; state = 2-D vector of laugh and smile probabilities
  from the SSI (Social Signals Interpretation) framework; actions = sounds, grimaces, three joke types and
  combinations; reward = "average reward based on all samples from the punchline to the end with a predefined
  punchline for every joke". This is *exactly* the "chuckle if funny" loop, done on a physical robot in 2018.
- Gordon et al. [68] (Tega tutor, SARSA): reward = weighted sum of facial valence and engagement from Affectiva.
- Park et al. [58] (Tega language companion): personalised tabular Q-learning over 6–8 sessions; reward =
  weighted engagement (Affectiva) + learning gains [−100, 0, +50, +100].
- Ritschel et al. [57] (Reeti storytelling): reward = change in user engagement (Kinect 2 + dynamic Bayesian net).
- Addo & Ahamed [55] (Nao joke-teller): reward from *verbal* self-report ("very funny" … "not funny").
- Zarinbal et al. [54]: reward r ∈ {−1, 0, 1} from classified facial expressions (dislike/neutral/like).
- Assessment: the field's pattern is tabular/linear RL over a *tiny* action set with reward = mean affect
  probability in a fixed post-action window. No one has reported a deep policy trained online from laughs on a
  home robot; the small action set and windowed averaging are what made it work.

### 5.4 Preference-based RL for HRI personalisation
- PbARL (arXiv 2409.13822, fetched PDF→text): keep a pre-trained robot policy, learn a preference-aligned latent
  action space (conditional VAE, mutual-information + preference + KL losses) instead of retraining; benchmark +
  real-world user study N = 8.
- CLEA (arXiv 2501.01367, fetched abstract): Kuri robot; users' *exploratory actions* (what they chose to look
  at in a signal-design activity) used as implicit preference data; N = 25 and N = 42; features outperform
  self-supervised alternatives on completeness/simplicity/minimality/explainability.
- HAPI (arXiv 2503.17046, IROS 2025, fetched abstract): 35-DOF android face; pairwise human comparisons → Siamese
  RankNet → expressions for Anger/Happiness/Surprise rated "significantly more realistic and socially resonant"
  than baseline and expert-designed ones.
- Assessment: pairwise preference over *short candidate behaviours* is the workable format for learning
  expressive motion; PbARL's "keep the pre-trained policy, adapt a latent" is the right shape for Parcel's
  body-intent lane (safety layer keeps authority; preference only steers a latent).

### 5.5 Commercial companions — what they actually learn
- Sony aibo ERS-1000 help guide (https://helpguide.sony.net/aibo/ers1000/v1/en-us/contents/TP0001970093.html,
  fetched): "When aibo see a smile on its owner's face or it is petted on head, back, or under the chin, aibo
  takes it as a compliment and looks delighted"; "aibo may be delighted with what you say ... or it may be hurt
  and depressed by your cold, unkind words"; "Depending on how aibo is raised, it may grow clingy or wild".
  No algorithm, rate, or evaluation is disclosed.
- Anki/DDL Vector 2.0 product page (https://anki.bot/products/vector-robot, fetched): smile recognition is a
  *planned* camera improvement; features run through "Vector cloud"; no on-device learning described.
- Loona, MiRo-E, Moxie: no primary source with a learning claim was fetched in this pass (search budget
  exhausted); treat as unknown.
- Assessment: the commercial state of the art is hand-authored reactions to praise/pet/smile detectors plus a
  scripted "personality" drift. That leaves real room for a learned, owner-specific reward.

### 5.6 Robot comedy field studies (OSU SHARE lab) — https://osusharelab.com/research/robotComedy/ (fetched)
- Program page lists 9 publications 2020–2025 on "Jon the Robot", with "room-reading of audience laughter
  sounds, audience facial expressions, and audience spoken input during crowd work", "Human-Inspired Laughter
  Classification Methods for Adaptive Robotic Comedians" (2022) and "Adaptive Robot Repartee Tends to Improve
  Social Attribute Ratings" (2023). The HRI 2020 best-paper (Vilk & Fitter, "Comedians in Cafes Getting Data")
  is on the ACM DL and could not be fetched; the lab page gives no numbers, so none are cited here.
- Assessment: the applied precedent — pause for laughter, quip back based on the laugh score — is the timing
  behaviour the dog needs (chuckle *with* the owner, not 2 s later).

## 6. Backchannel timing models

### 6.1 Voice Activity Projection (Ekstedt & Skantze, Interspeech 2022) — https://arxiv.org/pdf/2205.09812 (fetched, PDF→text)
- Switchboard, 2,438 dialogs (98 excluded, 135 test, 11 folds of 2000/205); 16 kHz mono; frozen CPC encoder at
  100 Hz (256-d) + VA-history features → causal transformer (hidden 256, 4 layers, 4 heads) → 256-way discrete
  projection of the next 2 s of both speakers' voice activity. Code https://github.com/ErikEkstedt/conv_ssl.
- Zero-shot weighted F1: SHIFT/HOLD .899 (SHIFT .510); SHORT/LONG .786; SHIFT-pred .733*; **BC-pred .723***
  vs .685 (independent) / .661 / majority .333 — significant at p < 0.025.
- Assessment: a self-supervised, label-free objective gives a usable "a backchannel is appropriate now" signal
  from raw audio at 100 Hz with a tiny model; this is the timing primitive for nods, "mm-hm" sounds and for
  placing a chuckle.

### 6.2 "Yeah, Un, Oh" — continuous real-time backchannel prediction by fine-tuning VAP (Inoue et al., arXiv 2410.15929, fetched HTML)
- Japanese; VAP pre-trained on ~35 h (attentive listening, job interviews, first meetings), fine-tuned on 109
  sessions (87/11/11) with 13,601 backchannel annotations (11,371/1,139/1,091); two types (continuers "un/hai",
  assessments "he-/oh"); frozen CPC, 1 channel-wise + 3 cross-attention layers, 4 heads; 10 Hz output; optimal
  context ~5 s.
- Timing+type (continuer): proposed multitask + pre-training F1 38.11% (P 29.89 / R 52.58) vs 34.13% baseline
  (36.10% single-task without pre-training). Real-time factor < 1.0 on an Intel Core i7-11700 CPU.
- Assessment: even the best model is far from perfect (F1 ~38% for *when + which*), but it runs on a CPU core
  and is trained on ~1 day of dialogue. For a dog, the "type" is a body cue (nod vs ear-perk), and the tolerance
  window is wide — the task is easier than for a speaking agent.

### 6.3 Morency, de Kok, Gratch (2010) — https://research.utwente.nl/en/publications/a-probabilistic-multimodal-approach-for-predicting-listener-backc/ (fetched)
- Sequential probabilistic models (HMM / CRF) over speaker prosody, words and gaze predict listener head-nod
  backchannels with "a statistically significant improvement over a previously published approach based on
  hand-crafted rules". Numbers are not on the fetched page. Canonical origin of the learned-backchannel line.

### 6.4 TIC-TALK comedic timing database (arXiv 2603.21803, 2026, fetched abstract)
- 90 stand-up specials (2015–2024), 5,400+ aligned topic segments; Whisper-AT for 0.8-s laughter detection,
  YOLOv8 pose; "kinetic energy negatively predicts audience laughter rate (r = −0.75, N = 24)" — the
  stillness-before-punchline pattern. Assessment: a ready-made corpus of (speech, gesture, laughter-onset)
  triples for pre-training a "when will they laugh" predictor; also evidence that *motion stillness* precedes
  the laugh — the dog should hold still through the punchline, then react.

## 7. Assessment: the most reliable low-cost reward design

What the evidence says, in order of reliability:

1. Vocal laughter is the single most reliable "that was funny" signal, but only when (a) the detector is
   adapted to the owner and room (Gillick F1 0.75 clean → 0.61 wild; Omine synthetic in-domain data brings
   detection F1 to 0.78–0.94 and start-time error to ~0.3 s), (b) it is credited to a *specific* preceding
   event with a fixed window (Weber: mean laugh/smile probability from the punchline to the end), and (c)
   polite/social laughter is discounted (SMILE-Next: mirthful vs polite is learnable, F1 0.81; the cheap proxy
   is duration + smile co-occurrence).
2. Smile intensity from blendshapes (MediaPipe mouthSmileL/R in [0,1]) is the cheapest co-signal; frame-level
   categorical emotion is unreliable (~65% on AffectNet). Use change-from-baseline and co-occurrence with
   laughter, not absolute values. EMPATHIC shows faces rank outcomes above chance but weakly per event
   (τ ≈ 0.2 per subject, 0.70 after aggregating 8 trajectories across 14 people).
3. "Owner approval" is best read as an *episode-level* score, not a frame-level reward: the UX study's
   whole-interaction MIL model beats human observers (70% vs 64% on 3 classes); rapport from transcripts via a
   text LLM reaches CCC 0.58 zero-shot. Explicit verbal/tactile approval (aibo's praise + pet; Addo & Ahamed's
   spoken ratings) is cleaner than any inferred signal and should be logged as a separate, high-weight event.
4. Engagement (is the owner still with me?) from the robot's own camera is learnable and transferable (ρ 0.63,
   AUC 0.89 cross-robot, 5 Hz). Its *drop* is the trigger for "look back at the owner"; its recovery after the
   look-back is the reward.
5. Text-only funniness models and LLM judges are not usable as reward: SemEval winner only 13.5% better than the
   mean; rJokes r ≈ 0.47; LLM–human ρ 0.17–0.27 (Oogiri); 13–18% vs a 19% popularity baseline (Cards Against
   LLMs); RLHF/DPO on 250 M ratings barely moves a 7 B model. Use them only as a weak prior on joke selection.

Recommended reward (all local, all small models):

  r_funny(e)   = clip( mean_{t in [t_punch, t_punch+3s]} p_laugh_owner(t) * (0.5 + 0.5 * smile_delta(t)) , 0, 1 )
                 with p_laugh from an Omine-style wav2vec2/ResNet frame model retrained on synthetic in-room
                 data, masked by mic-array DoA = owner and speaker-ID = owner; subtract the owner's rolling
                 baseline; zero if the laugh onset precedes the punchline (owner laughing at something else).
  r_approve(e) = w_v * explicit_verbal_praise (ASR keyword + valence sign from a Wav2Small/emotion2vec head)
               + w_t * touch/pet event (if tactile available) + w_f * smile_delta over the 5 s after the action
               + w_e * (engagement_after − engagement_before), evaluated per behaviour episode, with a
                 per-owner learned baseline; missing modalities simply drop their term.
  Use both as *preference labels over candidate behaviours* (pairwise, Weber/HAPI/PbARL style) rather than as
  dense RL reward; the action set stays small (which expression variant, when to chuckle, whether to look back).

## 8. What this means for Parcel

- The existing stack already has most of the sensors: mic array (DoA + laughter + valence), camera
  (blendshapes + engagement), ASR (Whisper-AT would give the laughter tag on the same encoder), owner model
  (consent-gated facts → store the owner's laugh/smile baselines there), reaction arbiter (the place where the
  "chuckle" candidate is emitted with a timestamp so credit assignment is exact).
- Compute on Orin: YAMNet/PANNs-MobileNet (≈4–5 M params, ~3.6 GFLOPs/s) or Whisper-AT tiny/base for tags;
  a Gillick-size ResNet or wav2vec2-base frame model for onsets; MediaPipe blendshapes on CPU; Del Duchetto
  engagement at 5 Hz on a GTX-1060-class budget; VAP (CPC + 4-layer transformer, 256 hidden) runs at RTF < 1
  on one CPU core. All of this fits beside a 50 Hz body-intent lane.
- What to *train* in the next 12 hours (desktop, MuJoCo not required for this part):
  1. Build a synthetic in-room laughter set from recorded room ambience + open laughter clips (Omine recipe) and
     fine-tune (a) wav2vec2-base frame classifier and (b) Gillick's ResNet; measure P/R/F1 and onset MAE at
     thresholds 0.5–0.9; keep the operating point with precision ≥ 0.8.
  2. Log a "reaction window" record per emitted behaviour: {behaviour id, t_emit, p_laugh[t], smile[t],
     engagement[t], ASR text, valence} for 0–5 s after; this is the dataset for the preference learner.
  3. Fit the Weber-style bandit/Q-table over (joke type × expression variant) with reward = windowed mean
     laugh×smile, in simulation with a *scripted owner* whose laugh probability depends on the joke/expression
     and on fatigue (habituation) — this is what lets the dog "learn to chuckle if funny" before hardware.
  4. Train the look-back policy on engagement: simulate engagement drop events (owner turns away / leaves the
     camera frame / stops talking) and reward engagement recovery after a look-back; the deterministic safety
     layer keeps final authority; the learned part only chooses *whether/when* to emit "look_back".
- Budget: none of this touches the hosted APIs; the text model can still be used once per session for a
  rapport score (CCC 0.58 zero-shot) as a slow, episode-level term.

## 9. Open questions

- Laughter-type discrimination (mirthful vs polite) on a single owner: does duration + smile co-occurrence
  suffice, or is a small classifier (SMILE-Next style, on audio only) needed? No audio-only numbers found.
- Habituation: the same joke/expression will stop being funny; none of the robot RL papers report decay
  handling. Needs a non-stationary bandit and a "novelty" term in simulation.
- Multi-person homes: V-JEPA rapport CCC fell from 0.50 to 0.04 with three people; Del Duchetto's model lost
  0.14 ρ in multi-party. Speaker/face identity gating is mandatory; how well does XVF3800 DoA + face ID hold up?
- No fetched primary source for what Loona, MiRo-E or Moxie learn online; and Weber 2018 / Vilk & Fitter 2020
  are cited only through the survey and lab page (ACM DL 403; Semantic Scholar 429).
- Per-class "Laughter" AP in AudioSet for the small taggers was not extracted (figure-only in PANNs); measure it
  locally on the AudioSet laughter eval clips from Gillick's annotations (1,000 + 1,000 clips, MIT).
- Whether the Omine 315 M-parameter frame model can be distilled to ≤ 20 M for Orin without losing the
  ~0.3 s onset accuracy is untested.
