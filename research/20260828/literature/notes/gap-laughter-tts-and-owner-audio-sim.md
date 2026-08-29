# Gap note: local, permissively licensed laughter synthesis and owner-audio simulation

Date: 2026-08-28. Author: research subagent (Fable). Scope: open TTS models with non-verbal
tags (can the dog's own chuckle and a simulated owner's laugh be synthesized locally?),
laughter-only synthesizers, and laughter datasets usable to augment a laughter detector.
Every source below was fetched and read in this session; numbers are quoted from the source.
Where a statement is my inference it is marked **[inference]**.

Context from the first sweep (not re-fetched here): Gillick laughter detector F1 0.61 in the
wild; Omine synthetic-laughter recipe; Orin 8B int4 30-50 tok/s.

---

## 0. Headline answers

1. **Best open laughter-tag TTS today (English): Orpheus TTS (Apache-2.0, 3B Llama).** In the
   only head-to-head benchmark of tag-based TTS (NVBench, Apr 2026) it has the highest NVV F1
   of any open system, 0.728 (CosyVoice 2 0.463, Dia 0.632, Bark 0.654, Fish-Speech 0.432,
   Higgs-Audio 0.382), and the best subjective NVV accuracy 3.71/5. Its tag set is
   `<laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>`.
2. **Tags are unreliable even at the top.** NV-Bench (Mar 2026) measures paralinguistic CER:
   Orpheus-TTS 71.92 % PCER on English; CosyVoice3 62.75 %; best fine-tuned system
   (NV-CV3) 46.13 %. On Mandarin, laughter-only PCER is 57.69 % for CosyVoice3 and 27.69 %
   for NV-CV3. Any pipeline that emits a laugh must verify it with a detector, or fine-tune.
3. **Korean + laughter tag + permissive license** exists in exactly two places:
   Fun-CosyVoice3-0.5B (Apache-2.0, 9 languages incl. Korean, `[laughter]`/`[breath]`) and
   Bark (MIT, 13 languages incl. Korean, `[laughter]`, but WER 14.73 and 12 GB VRAM).
   Orpheus has an Apache-2.0 Korean research checkpoint whose tag support is undocumented.
   Chatterbox-Multilingual has Korean but its `[laugh]` tag lives only in the English-only
   Turbo model. Maya1, Dia/Dia2, Chatterbox-Turbo, Parler-Expresso, CSM are English-only.
4. **Laughter-only synthesis** is thin: the only open method with a corpus is Xin/Takamichi
   2023 (pseudo-phonetic tokens on Laughterscape; code MIT; corpus "research and development
   purpose only (tentative)"; MOS 3.00 vs GT 3.73, Japanese). There is no 2025-26 open
   laughter-only generator with weights.
5. **Detector augmentation is fully permissive:** VocalSound (CC BY-SA 4.0, 3,504 laughter
   clips) + AudioSet Laughter (CC BY 4.0 labels, 5,696 clips) + the Omine 2024 recipe
   (code MIT; their released weights "research use only"; retrain: 75 min on an RTX 2080 Ti).
   Adding VocalSound to FSD50K raised laughter F1 0.45 -> 0.59.
6. **Orin feasibility:** Orpheus needs ~83-91 tok/s for real time; NVIDIA's own MLC int4
   numbers are 47 tok/s for Llama2-7B on AGX Orin and 43 tok/s for Llama-3.2-3B on Orin Nano
   Super. **[inference]** A 3B int4 model on AGX Orin should land near 80-110 tok/s, i.e.
   marginal real time for Orpheus; Chatterbox (500M) on an Orin Nano 8 GB takes ~4 s per
   utterance. Sub-1B models (CosyVoice3-0.5B, Chatterbox-Turbo 350M, OmniVoice 0.8B) are the
   realistic on-robot candidates; 3B models belong on the desktop RTX 5000 Ada.

---

## 1. Open TTS models with non-verbal tags (2025-2026)

### 1.1 Orpheus TTS (Canopy Labs, Mar-Apr 2025)
- Sources: https://github.com/canopyai/Orpheus-TTS (README, fetched);
  https://huggingface.co/canopylabs/3b-ko-ft-research_release (fetched);
  https://huggingface.co/collections/canopylabs/orpheus-multilingual-research-release-67f5894cd16794db163786ba (fetched);
  https://www.baseten.co/library/orpheus-tts/ (fetched); https://www.simplismart.ai/blog/orpheus-tts-simplismart (fetched).
- License: "Apache-2.0" (GitHub). Korean checkpoint card: "apache-2.0".
- Size: "Llama-3b backbone"; base "trained on 100k+ hours of English speech data".
  Smaller sizes "1b, 400m, 150m parameters" are on the checklist but unreleased.
- Tags (English): `<laugh>`, `<chuckle>`, `<sigh>`, `<cough>`, `<sniffle>`, `<groan>`,
  `<yawn>`, `<gasp>`. "For multilingual, see this post for supported tags" — the link only
  resolves to the HF collection, which says "Beta Release of multilingual models" and lists
  no tags. The Korean card says "Guided Emotion and Intonation: Control speech and emotion
  characteristics with simple tags" without listing them. Korean models:
  `3b-ko-pretrain-research_release` and `3b-ko-ft-research_release` (base
  `meta-llama/Llama-3.2-3B-Instruct`); no training data or eval disclosed.
- Latency: "~200ms streaming latency for realtime applications, reducible to ~100ms with
  input streaming". Baseten: "Orpheus TTS must generate ~83 tokens/second for real-time
  streaming"; Simplismart: "~91 tokens/sec = ~1 second of audio (real-time factor 1.0)",
  "~130 ms TTFB" on a full H100, "25+ concurrent streams under 300ms" per H100.
- Evaluation of tags: none in the repo. External: NVBench F1 0.728 (Sec. 2.1); NV-Bench
  English PCER 71.92 % (Sec. 2.2). No Orin benchmark exists (searched).

### 1.2 CosyVoice 3 / Fun-CosyVoice3-0.5B-2512 (Alibaba FunAudioLLM, May/Dec 2025)
- Sources: https://arxiv.org/html/2505.17589v1 (fetched);
  https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 (fetched);
  https://github.com/FunAudioLLM/CosyVoice (fetched).
- License: "apache-2.0" (HF card and GitHub).
- Size: paper scales the LM "from 0.5 billion to 1.5 billion"; the released Fun-CosyVoice3 is
  0.5B. Training data "from ten thousand hours to one million hours, encompassing 9 languages
  and 18 Chinese dialects"; languages: Chinese, English, Japanese, **Korean**, German, French,
  Russian, Italian, Spanish.
- Tags: "markers such as '[laughter]' and '[breath]' in the input text can be used to
  generate a noticeable laughter and breath"; also `<strong>` emphasis. Example prompts on the
  HF card use `[breath]`.
- Numbers: WER en 2.24 / SS 71.8 %; CER zh 1.21 / SS 78.0 % (HF card); RL variant zh CER
  0.81 %, en WER 1.68 % (GitHub). Latency: "achieves latency as low as 150ms" (bi-streaming);
  "TensorRT-LLM ... 4x acceleration comparing with huggingface transformers".
- Tag evaluation: none in the paper ("Table 14 focuses on style similarity and WER"). External:
  NV-Bench laughter PCER (zh) 57.69 %, English PCER 62.75 %; CosyVoice 2 NVBench F1 0.463
  (en) / 0.496 (zh).

### 1.3 Dia-1.6B (Nari Labs, Apr/Jun 2025) and Dia2 (1B/2B)
- Sources: https://huggingface.co/nari-labs/Dia-1.6B-0626 (fetched);
  https://huggingface.co/nari-labs/Dia2-2B (fetched); https://github.com/nari-labs/dia2 (fetched).
- License: "Apache License 2.0" (both).
- Size 1.6B; "The model only supports English generation at the moment"; Dia2 "only supports up
  to 2 minutes of generation in English".
- Tags: (laughs), (clears throat), (sighs), (gasps), (coughs), (singing), (sings), (mumbles),
  (beep), (groans), (sniffs), (claps), (screams), (inhales), (exhales), (applause), (burps),
  (humming), (sneezes), (chuckle), (whistles) — with the caveat "will be recognized, but might
  result in unexpected output". Dia2 card lists only `[S1]`/`[S2]` speaker tags.
- Speed: "The full version of Dia requires around 10GB of VRAM"; "On a A4000 GPU, Dia roughly
  generates 40 tokens/s (86 tokens equals 1 second of audio)" => **[inference]** RTF ~2.1x
  slower than real time on an A4000; "On enterprise GPUs, Dia can generate audio in real-time".
- External: NVBench coverage 0.29 (13 types, the widest open tag set), F1 0.632, but WER 21.95.

### 1.4 Chatterbox family (Resemble AI, 2025-26)
- Sources: https://github.com/resemble-ai/chatterbox (fetched);
  https://huggingface.co/ResembleAI/chatterbox-turbo (fetched);
  https://forums.developer.nvidia.com/t/chatterbox-on-a-jetson-orin-nano-8gb/360554 (fetched).
- License: MIT (all variants).
- Sizes: Chatterbox 500M; Chatterbox-Turbo 350M; Chatterbox-Nano 110M; Chatterbox-Multilingual
  V3 500M (23+ languages incl. "Korean (ko)").
- Tags: "Paralinguistic tags are now native to the Turbo model": `[cough]`, `[laugh]`,
  `[chuckle]` and more — **Turbo is English only**; the Multilingual model has no tag list.
  Original model exposes `exaggeration` and `cfg_weight` (defaults 0.5/0.5).
- Speed: Nano "running 3x faster than realtime on 8 CPU cores"; decoder "from 10 steps to
  just one" (Turbo). No RTF for the open model on the HF card. Community: "~4 seconds per
  utterance on GPU" on a Jetson Orin Nano 8 GB (forum post, not peer reviewed).
- Tag evaluation: none published. Not in NVBench.

### 1.5 Fish Speech / OpenAudio S1-mini / S2-Pro (Fish Audio)
- Sources: https://huggingface.co/fishaudio/openaudio-s1-mini (fetched);
  https://github.com/fishaudio/fish-speech (fetched).
- License: S1-mini "CC-BY-NC-SA-4.0"; current repo (S2-Pro) "FISH AUDIO RESEARCH LICENSE"
  ("We will take action against any violation of the license"). **Not permissive.**
- Sizes: S1-mini 0.5B (distilled from 4B S1); S2-Pro 4B slow AR + 400M fast AR.
- Languages: 13 incl. Korean (S1-mini); S2 lists Korean as "Tier 2".
- Tags: (laughing) (chuckling) (sobbing) (crying loudly) (sighing) (panting) (groaning)
  (crowd laughing) (background laughter) (audience laughing) + ~50 emotion markers; "Ha,ha,ha"
  also works. S2: "15,000+ Unique Tags".
- Numbers: S1-mini WER 0.011 / CER 0.005 / speaker distance 0.380; S2-Pro on H200 RTF 0.195,
  TTFA ~100 ms. External: NVBench F1 0.432 (en) / 0.598 (zh).

### 1.6 Higgs Audio v2 (Boson AI, Jul 2025)
- Sources: https://huggingface.co/bosonai/higgs-audio-v2-generation-3B-base/raw/main/README.md
  (fetched); .../raw/main/LICENSE (fetched); https://github.com/boson-ai/higgs-audio/blob/main/README_V2.md (fetched).
- License: "Boson Higgs Audio 2 Community License Agreement" — commercial use allowed, but
  ">100,000 annual active users ... must request an expanded license", attribution "Built with
  Higgs Materials licensed from Boson AI USA, Inc.", derived models must carry "Higgs Audio 2"
  in the name, no use of outputs to improve other LLMs. Higgs TTS 3 is research/non-commercial.
- Size: 3.6B LLM + 2.2B Audio DualFFN (5.8B), "same training / inference FLOPs as
  Llama-3.2-3B"; "pretrained on over 10 million hours"; README lists English, Chinese, German,
  Korean; "GPU with at least 24GB memory".
- Numbers: EmergentTTS-Eval Emotions 75.71 % win vs gpt-4o-mini-tts; Seed-TTS WER 2.44 /
  SIM 67.70. No laughter tag documented ("melodic humming", background music are).
  External: NVBench coverage 0.09, F1 0.382 — weakest open tag system.

### 1.7 Kokoro-82M (hexgrad)
- Source: https://huggingface.co/hexgrad/Kokoro-82M (fetched).
- Apache 2.0; 82M; "A few hundred hours of audio"; training "1000 hours of A100 80GB vRAM".
  Korean not listed. No non-verbal tag mechanism documented; not in NVBench. Use only as a
  neutral narration fallback.

### 1.8 Sesame CSM-1B
- Source: https://huggingface.co/sesame/csm-1b (fetched).
- "apache-2.0"; HF tensor count 2B; "some capacity for non-English languages due to data
  contamination ... but it likely won't do well". No tag control for laughter; usage
  restrictions on impersonation. Not a laughter tool.

### 1.9 Parler-TTS mini-expresso
- Source: https://huggingface.co/parler-tts/parler-tts-mini-expresso (fetched).
- "apache-2.0"; 0.6B; English; emotions via description text: "happy", "confused", "default",
  "laughing", "sad", "whisper", "emphasis"; trained ~1.5 h on one A100. External: NVBench
  Parler-TTS Mini NVV instruction following 0.92/5, WER 6.25 — description-prompted laughter
  essentially does not work.

### 1.10 Bark (Suno, 2023, MIT relicense)
- Source: https://github.com/suno-ai/bark (fetched).
- "Bark is licensed under the MIT License." Korean (ko) supported. Tags `[laughter]`,
  `[laughs]`, `[sighs]`, `[music]`, `[gasps]`, `[clears throat]` ("we are finding more every
  day"). "around 12GB of VRAM"; small models fit 8 GB; "roughly real-time" on enterprise GPUs.
  External: NVBench F1 0.654 but WER 14.73, coverage 0.11.

### 1.11 NVSpeech / Emilia-NV (CUHK-SZ Amphion, Aug 2025)
- Sources: https://arxiv.org/html/2508.04195v1 (fetched);
  https://huggingface.co/datasets/amphion/Emilia-NV (fetched).
- Dataset: "48,430 human-spoken utterances with 18 word-level paralinguistic categories" (76 h)
  + "174,179 utterances (573 hours)" auto-labeled; Mandarin only; categories incl. [Laughter],
  [Cough], [Breathing], [Crying], [Uhm], [Surprise-oh] ... License **CC BY-NC-SA 4.0**; the
  human-annotated subset is "Private".
- Models: CosyVoice / CosyVoice2 fine-tunes; "recall of paralinguistic tags (up to 61.9%)";
  human win rates 78.7 % / 75.4 %; NMOS 3.9-4.0. ASR: SenseVoice CER 4.61 %, F1 0.83.

### 1.12 Other 2025-26 releases checked
- **Maya1** (https://huggingface.co/maya-research/maya1, fetched): "Apache 2.0"; "3B-parameter
  decoder-only transformer (Llama-style)" + SNAC; tags `<laugh> <sigh> <whisper> <angry>
  <giggle> <chuckle> <gasp> <cry>` "+12 more"; "Currently English"; "16GB+ VRAM";
  "sub-100ms latency" via vLLM; no evaluation numbers.
- **Qwen3-TTS** (https://github.com/QwenLM/Qwen3-TTS, fetched): Apache-2.0; 0.6B/1.7B; 10
  languages incl. Korean; instruction-driven, no laughter tag list; "latency as low as 97ms";
  Seed-TTS WER zh 0.77 / en 1.24. External: NVBench NVV instruction following 2.15/5.
- **Step-Audio-EditX** (https://huggingface.co/stepfun-ai/Step-Audio-EditX and
  https://arxiv.org/html/2511.03601v1, fetched): 3B; code "Apache 2.0"; paralinguistic edit
  types "breathing, laughter, surprise-oh, ... sigh, ..."; Step-Audio-Edit-Test paralinguistic
  score (1-3, LLM judge) Iter0 1.91 -> Iter1 2.89 (zh 1.80 -> 2.89, en 2.02 -> 2.88);
  "12 GB is just a critical value, and 16GB GPU memory should be safer"; evaluated zh/en only
  (HF card mentions Korean tag support; report does not test it).
- **OmniVoice** (https://arxiv.org/html/2604.00688v3, fetched): 0.8B; "646 languages ... 581k
  hours" incl. Korean; "we incorporate paralinguistic control (e.g., laughter)" — no NV eval;
  RTF 0.0319 (16 steps, H20); paper CC BY 4.0; code at github.com/k2-fsa/OmniVoice (repo
  license reported Apache-2.0 by a secondary source; not verified here).
- **Breeze-TTS-2** (https://huggingface.co/BreezeBlue/Breeze-TTS-2, fetched, released
  2026-08-25): 3B; code Apache-2.0 but weights "BreezeBlue Research and Non-Commercial License";
  tags (laugh), (cough), (clears throat), (sigh); EN/ZH; H100 TTFA < 40 ms, RTF 0.32, 7.7 GiB.
- **Zonos-v0.1** (https://huggingface.co/Zyphra/Zonos-v0.1-transformer, fetched): apache-2.0;
  2B; EN/JA/ZH/FR/DE (no Korean); emotion sliders, no laughter tag; "~2x" real-time on 4090;
  6 GB+ VRAM; 200k h.
- **IndexTTS-2.5** (https://github.com/index-tts/index-tts, fetched): "bilibili Model Use
  License Agreement", commercial by contact; 0.8B; zh/en/ja/es/ar; no laughter; RTF 0.2065
  on 4090 bf16.

### 1.13 Comparison table

| Model | License | Params | Laugh tag | Korean | Tag evidence | Speed (source) |
|---|---|---|---|---|---|---|
| Orpheus TTS | Apache-2.0 | 3B | `<laugh>` `<chuckle>` | ko research ckpt, tags undocumented | NVBench F1 0.728; NV-Bench PCER 71.9 % | ~200 ms stream; needs 83-91 tok/s |
| Fun-CosyVoice3-0.5B | Apache-2.0 | 0.5B | `[laughter]` | yes | NV-Bench zh laughter PCER 57.7 %; CV2 F1 0.463 | 150 ms bi-stream; TRT-LLM 4x |
| Dia-1.6B | Apache-2.0 | 1.6B | (laughs) (chuckle) | no | NVBench F1 0.632, WER 21.95 | A4000 40 tok/s vs 86 needed |
| Chatterbox-Turbo | MIT | 350M | `[laugh]` `[chuckle]` | no (Multilingual has ko, no tags) | none | Orin Nano ~4 s/utt (community) |
| Maya1 | Apache-2.0 | 3B | `<laugh>` `<giggle>` `<chuckle>` | no | none | vLLM sub-100 ms; 16 GB |
| Bark | MIT | n/a | `[laughter]` | yes | NVBench F1 0.654, WER 14.73 | ~real-time enterprise GPU; 12 GB |
| Fish S1-mini / S2 | CC-BY-NC-SA / Research | 0.5B / 4B | (laughing) | yes | NVBench F1 0.432 | S2 H200 RTF 0.195 |
| Higgs Audio v2 | Boson Community (100k AAU cap) | 5.8B | none documented | README lists ko | NVBench F1 0.382 | 24 GB GPU |
| Step-Audio-EditX | Apache-2.0 (code) | 3B | edit-op "laughter" | claimed, untested | 1.91 -> 2.89 /3 | 12-16 GB |
| Qwen3-TTS | Apache-2.0 | 0.6/1.7B | instruction only | yes | NVBench IF 2.15/5 | 97 ms |
| OmniVoice | paper CC BY 4.0 | 0.8B | "laughter" control | yes (646 langs) | none | RTF 0.032 H20 |
| Parler-Expresso | Apache-2.0 | 0.6B | "laughing" description | no | NVBench IF 0.92/5 | — |
| Kokoro-82M | Apache-2.0 | 82M | none | no | — | — |
| CSM-1B | Apache-2.0 | ~2B | none | no | — | — |
| Breeze-TTS-2 | non-commercial weights | 3B | (laugh) | no | none | H100 RTF 0.32 |

---

## 2. Do laughter tags actually work? (benchmarks)

### 2.1 NVBench / NVV-SuperBench (Apr 2026) — https://arxiv.org/html/2604.16211v2 (fetched)
- 15 systems (7 prompt-based, 8 tag-based); "2,250 English and 2,250 Chinese items" over a
  "45-type NVV taxonomy"; metrics WER/CER, DNSMOS, NVV precision/recall/F1, onset accuracy,
  subjective "NVV Instruction Following" and "NVV Perceptual Effect". Coverage =
  N_supported x 50 / (45 x 50).
- English objective (tag-based, open):
  Orpheus TTS cov 0.18, P 0.687, R 0.774, **F1 0.728**, WER 4.98;
  CosyVoice 2 cov 0.18, F1 0.463, WER 3.82; Dia cov 0.29, F1 0.632, WER 21.95;
  Fish-Speech cov 0.16, F1 0.432, WER 5.65; Bark cov 0.11, F1 0.654, WER 14.73;
  Higgs-Audio cov 0.09, F1 0.382, WER 9.41; ChatTTS cov 0.02, F1 0.664.
- Subjective (English): Orpheus naturalness 4.01, NVV accuracy 3.71, expression 3.49;
  CosyVoice 2 3.65 / 2.22 / 3.34; Dia 3.12 / 2.99 / 3.24. Prompt-based: Qwen3-TTS NVV IF
  2.15, Parler-TTS Mini 0.92, CapSpeech 1.11.
- Supported types: Orpheus "laugh, chuckle, sigh, cough, sniffle, groan, yawn, gasp";
  CosyVoice 2 "breath, laughter, cough, clucking, quick_breath, hissing, sigh, lipsmack";
  Dia 13 types (EN only). Chinese: CosyVoice 2 F1 0.496, Fish-Speech 0.598.
- Per-type: "laughter-related cues (laugh/laughter) and respiratory cues tend to obtain higher
  PE when present"; "low-SNR oral cues and long-duration affective NVVs remain persistent
  bottlenecks". Data at https://lmxue.github.io/NVBench/ (license not stated).

### 2.2 NV-Bench (Mar 2026) — https://arxiv.org/html/2603.15352 (fetched)
- "1,651 multi-lingual, in-the-wild utterances", "14 NV categories", "7.9 hours"; single-label
  650 Mandarin + 350 English; test set CC BY-NC-SA 4.0; metrics PCER (paralinguistic CER),
  OCER, speaker similarity, DNSMOS, FAD/FD.
- English single-label PCER: Orpheus-TTS 71.92 % (OCER 10.63), CosyVoice3 62.75 % (OCER
  9.06, SIM 0.701), Emilia-NV-CV2 55.30 %, SMIIP-NV-CV2 56.80 %, NV-FlexiVoice 50.43 %,
  NV-CV3 46.13 %.
- Mandarin laughter PCER: NV-CV3 27.69 %, Emilia-NV-CV2 40.00 %, CosyVoice3 57.69 %.
- Reading: even a laughter-specialised fine-tune misrenders ~1 in 4 laughs; stock CosyVoice3
  misses more than half.

### 2.3 NVMOS (Jun 2026) — https://arxiv.org/html/2606.15888 (fetched)
- NV-quality predictor; dataset "7,784 samples with about 9.51 hours ... 2,655 synthetic and
  5,129 natural" over 16 NV categories, 3 expert raters 0-5. WavLM-Large Pearson 0.697 vs
  inter-expert 0.589-0.699; Gemini 3 Flash 0.468. Released at github.com/yongaifadian1/NVMOS.
  Usable as an automatic "did that laugh sound right" scorer.

### 2.4 Preference optimization for NV synthesis (Aug 2026) — https://arxiv.org/html/2608.24163 (fetched)
- CosyVoice2-0.5B SFT on Emilia-NV (573.4 h) then DPO with an NV-aware CER; single-tag NV-CER
  3.62 -> 2.59; human preference 55.5 % vs 44.5 % (NV accuracy). No per-type laughter split;
  no code/weights. Shows the fix path: tag fidelity improves with preference RL on a 0.5B model.

### 2.5 NonverbalTTS (Jul 2025) — https://arxiv.org/abs/2507.13155 and
https://huggingface.co/datasets/deepvk/NonverbalTTS (fetched)
- "17-hour open-access dataset annotated with 10 types of NVs (e.g., laughter, coughs) and 8
  emotional categories", from VoxCeleb + Expresso, English; HF card license "apache-2.0";
  6,260 rows (train 3.64k / dev 46 / test 359 / other 2.21k); fine-tuned open TTS reaches
  "parity with ... CosyVoice2" on speaker similarity and NV fidelity. The one permissively
  licensed English NV-TTS fine-tuning corpus found.

---

## 3. Laughter-only synthesizers

### 3.1 Laughterscape + pseudo-phonetic-token synthesis (Xin, Takamichi et al., Interspeech 2023)
- Sources: https://arxiv.org/pdf/2305.12442 (PDF read);
  https://github.com/Aria-K-Alethia/laughter-synthesis (fetched);
  https://sites.google.com/site/shinnosuketakamichi/research-topics/laughter_corpus (fetched).
- Corpus v1.0 (site): "6.04 hours", "11413 utterances", "584 Japanese speakers", 24 kHz,
  YouTube; paper version 7,489 utterances / 470 speakers / ~3.5 h. Terms: "Research and
  development purpose only. (tentative. This will be subject to change.)" Zip 0.7 GB.
- Method: HuBERT-base-ls960 features -> k-means (200 clusters) -> PPTs -> FastSpeech2 ->
  HiFi-GAN (vocoder trained on JVS, 1.5 weeks on a V100). Token LM (6-layer transformer) for
  unconditional laughter.
- Numbers (Table 1): GT MOS 3.73, HiFi-GAN resynthesis 3.31/SMOS 4.74; baseline (ASR
  phonemes) MOS 1.25 / SMOS 1.20; Proposed-L5 MOS **3.00**, L12 SMOS **3.22**, MCD 11.41,
  F0-RMSE 80.28. Unconditional (Table 2): L5 MOS 3.11, SMOS 2.65. Baseline ASR failed on 6.9 %
  of utterances. Code MIT; pretrained vocoder on Google Drive; Japanese.
- Fit: the PPT recipe is language-agnostic and could be retrained on VocalSound (CC BY-SA)
  for a fully permissive laugh-only synth; but small, non-streaming, single-purpose.

### 3.2 ehehe-corpus (litagin, HF) — https://huggingface.co/datasets/litagin/ehehe-corpus (fetched)
- "only laughter voice acting recordings by Japanese professional voice actors"; 16,415 files,
  ~5.13 h; ripped from purchased PC games; usable "only ... under Article 30-4 of the Copyright
  Law of Japan for data analysis". Not usable for a shipped product outside that regime.

### 3.3 LaughGANter (2021) — https://arxiv.org/abs/2111.03146 (fetched abstract)
- GAN laughter generator "trained on a dataset of diverse laughter samples"; no size, no code
  statement on the abstract page. Historical only.

### 3.4 No 2025-2026 laughter-only generator with open weights was found (searches:
"laughter synthesis 2025 arxiv open source", "laughter generation model 2026 arxiv"). The
field moved laughter into the TTS tag mechanism (Sec. 1) and into LLM laughter understanding
(SMILE-Next, https://arxiv.org/abs/2605.28084, fetched: "laughter detection, laughter type
classification, and laughter reasoning"; paper CC BY 4.0; no numbers on the abstract page).

---

## 4. Laughter datasets to augment a detector

| Dataset | Laughter content | License | Notes |
|---|---|---|---|
| VocalSound (MIT, ICASSP 2022) | 3,504 laughter clips of 21,024; 3,365 speakers; mean 4.18 s | CC BY-SA 4.0 | acted, crowdsourced, clean |
| AudioSet "Laughter" | 5,696 clips (Baby 863, Giggle 991, Snicker 1,857, Belly 843, Chuckle 1,693) | CC BY 4.0 (labels); audio via YouTube IDs | in-the-wild, noisy labels |
| Laughterscape v1.0 | 11,413 single-speaker laughs, 6.04 h, 584 speakers | R&D only (tentative) | Japanese, YouTube |
| ehehe-corpus | 16,415 acted laughs, 5.13 h | JP Art. 30-4 analysis only | fiction voice acting |
| NonverbalTTS | 17 h English speech with laughter markers | Apache-2.0 | VoxCeleb + Expresso |
| Emilia-NV / NVSpeech | 573 h Mandarin with [Laughter] word-level tags | CC BY-NC-SA 4.0 | human subset private |
| KsponSpeech | 969 h Korean spontaneous dialogue, laughter/breath symbols in transcripts | AI Hub application; terms not verified here | Korean laughter in context |
| Omine 2024 eval set | 201 laughter + 201 non-laughter podcast clips | released with repo (code MIT) | segmentation ground truth |

### 4.1 VocalSound — https://github.com/YuanGongND/vocalsound and https://arxiv.org/pdf/2205.03433 (both read)
- "licensed under a Creative Commons Attribution-ShareAlike 4.0 International License".
- Table 1: Laughter 3,504 (vs AudioSet 5,696, FSD50K 1,186, ESC-50 40); all six classes 3,504
  each; total 21,024. 3,365 subjects, 60 countries, 45 % female; ages 18-80; "mean, median,
  and standard deviation of the audio length is 4.18s, 3.72s, and 1.81s"; 44.1 kHz wav (16 kHz
  version 1.7 GB). Split 15,570 / 1,860 / 3,594, speaker-independent.
- Six-class accuracy 90.5 +/- 0.2 %. Training FSD50K + VocalSound vs FSD50K only: laughter F1
  0.45 -> 0.59 (+29.7 %), AP 0.46 -> 0.54; overall mAP +41.9 %. Caveat: "audio samples are not
  produced spontaneously but acted by the subjects".

### 4.2 AudioSet — https://research.google.com/audioset/download.html and
https://research.google.com/audioset/ontology/laughter_1.html (both fetched)
- "Creative Commons Attribution 4.0 International (CC BY 4.0)" for the dataset (CSV of YouTube
  IDs + 128-d 1 Hz features, 2.4 GB); ontology CC BY-SA 4.0. Splits: eval 20,383, balanced
  22,176, unbalanced 2,042,985 segments. Laughter = "rhythmical contractions of the diaphragm
  in response to stimuli such as tickling, or from humorous stories or thoughts"; 5,696
  annotations with the five children above. Audio must be pulled from YouTube separately.

### 4.3 Omine, Akita, Tsuruno (Interspeech 2024) — https://www.isca-archive.org/interspeech_2024/omine24_interspeech.pdf (PDF read);
https://github.com/omine-me/LaughterSegmentation (fetched)
- Recipe: base audio 7.0 s from Spotify Podcast Dataset (YAMNet laughter score < 0.05) and
  AudioSet (3,007 clips without laughter labels); laughter from VocalSound ("3,504 samples of
  laughter"), Laughterscape (11,413), 93 web samples (infant/crowd); "randomly synthesize 0-4
  laughter segments"; keep first episode >= 0.30 s; per-laugh augmentation of loudness, speed,
  pitch, reverb, compressor, low-pass; synthetic crowd laughter by superimposing 5-30 samples;
  base audio ducked while laughter plays; labels every 0.02 s; 16 kHz mono.
- Model: wav2vec2-large-xlsr-53-english frame classifier, "approximately 315 million
  parameters", 2,500 steps, batch 5, "approximately 75 minutes to train, and 1 minute to
  segment an hour-long audio file on an i9-9900K CPU ... and an NVIDIA GeForce RTX 2080 Ti".
- Detection F1 (Table 1): AMI Gillick 0.583 -> Ours 0.784; MAHNOB 0.618 -> 0.890;
  Gillick-set 0.844 -> 0.865; own podcast set 0.897 -> 0.943. Segmentation (Table 2):
  Gillick-set F1 0.600 -> 0.638, start-time MAE 2.070 s -> 1.085 s; own set F1 0.617 -> 0.789,
  start MAE 1.500 s -> 0.314 s. Retraining Gillick's architecture on the synthetic data alone
  already lifts MAHNOB F1 0.618 -> 0.778.
- Licensing: repo "MIT-licensed"; released weights (1.26 GB safetensors) "currently available
  for research use only" — for a product, retrain with the MIT code on VocalSound + AudioSet.
- Gillick detector (https://github.com/jrgillick/laughter-detection, fetched): MIT; trained on
  Switchboard; AudioSet-based in-the-wild eval annotations included.

### 4.4 Korean — https://github.com/sooftware/ksponspeech and https://huggingface.co/datasets/cheulyop/ksponspeech (fetched)
- KsponSpeech: "969 hrs of general open-domain dialog utterances, spoken by about 2,000 native
  Korean speakers"; transcripts carry non-speech symbols (`b/`, `n/`, `/`, `*`, `+` seen in
  examples; the MDPI paper listing the laughter symbol returned HTTP 403). "Anyone can download
  this dataset just by applying" on AI Hub; license terms were not verified in this sweep. No
  dedicated open Korean laughter corpus was found (search "Korean laughter corpus AI Hub").

---

## 5. Orin / desktop feasibility numbers

- Real-time bar for SNAC-token LLM-TTS (Orpheus): "~83 tokens/second" (Baseten) /
  "~91 tokens/sec" (Simplismart); Dia: "86 tokens equals 1 second of audio".
- NVIDIA Jetson AI Lab (via https://github.com/dusty-nv/jetson-containers/issues/532, fetched):
  published AGX Orin MLC int4 Llama2-7B 47 tok/s, Gemma 75 tok/s; a user on AGX Orin 32 GB
  reproduced only ~19 and ~23 tok/s. Orin Nano Super (archive page, fetched): Llama 3.2 3B
  27.7 -> 43.07 tok/s. No TTS numbers on the Jetson benchmarks page (only a Riva chart).
- Chatterbox on Jetson Orin Nano 8 GB: "~4 seconds per utterance on GPU" (forum, fetched).
- Desktop (RTX 5000 Ada 32 GB, **[inference]** from vendor GPU numbers): every model here fits;
  Orpheus/Maya1 3B stream in real time on a 4090-class card; Dia needs an enterprise GPU for
  real time; Zonos "~2x" real time on a 4090; IndexTTS-2.5 RTF 0.21 on a 4090.

---

## 6. What this means for Parcel

1. **Two-tier synthesis plan.** Desktop (RTX 5000 Ada) runs Orpheus TTS (Apache-2.0) as the
   generator of (a) the dog's chuckle library and (b) synthetic owner reactions for the
   simulator. On the robot, do not run a 3B LLM-TTS for a chuckle: pre-render a bank of dog
   chuckles/vocalizations offline and play them from disk; if live TTS is needed on Orin, the
   candidates are Fun-CosyVoice3-0.5B (Apache-2.0, `[laughter]`, 150 ms streaming, Korean)
   or Chatterbox-Turbo (MIT, `[laugh]`, English). Orpheus on AGX Orin is at best marginal
   real time **[inference]** and unmeasured.
2. **Never trust a tag.** The best open model still fails the paralinguistic transcript on
   46-72 % of items (NV-Bench) and reaches F1 0.73 at best (NVBench). Every synthesized laugh —
   dog or simulated owner — should be gated by the laughter detector (and optionally NVMOS)
   before it enters the vocalization bank or the simulator's reward channel. This also means
   the simulated-owner reward signal must be defined on the *detector output*, not the tag,
   or the sim reward and the real-world reward will disagree.
3. **Korean owner audio.** For simulated Korean owner laughter use Fun-CosyVoice3-0.5B
   (Apache-2.0, Korean + `[laughter]`) and test Orpheus `3b-ko-ft-research_release` (Apache-2.0)
   with `<laugh>`; Bark (MIT) is the fallback but WER 14.7 and 12 GB. Fish/OpenAudio is the
   strongest Korean tag model but CC-BY-NC-SA / research license — excluded for a product.
   Higgs Audio v2's community license (100k AAU cap, naming, attribution) is tolerable for a
   prototype but adds obligations; it is also the weakest open tag system (F1 0.382).
4. **Owner-laughter detector training data is clean.** VocalSound (CC BY-SA 4.0, 3,504 laughs)
   + AudioSet Laughter (CC BY 4.0, 5,696 clips, five subtypes incl. "Chuckle, chortle" 1,693)
   + the Omine recipe (MIT code; retrain the 315M wav2vec2 in ~75 min on one desktop GPU)
   is a fully permissive path that lifted detection F1 to 0.78-0.94 and cut onset MAE to
   0.31-1.09 s. Use the retrained model rather than Omine's released weights (research-only).
   Because the reward is a *timing* signal ("chuckle if the joke was funny"), the onset MAE
   improvement matters more than F1.
5. **Laugh-only synthesis is optional.** If a distinct non-speech dog vocalization is wanted,
   the Laughterscape PPT pipeline (MIT code) retrained on VocalSound laughs gives a permissive
   laugh-only generator (expected MOS ~3/5 by analogy); otherwise Orpheus `<laugh>` clips
   post-filtered by the detector suffice.
6. **Fine-tuning path if tag fidelity is not enough:** NonverbalTTS (Apache-2.0, 17 h English)
   is the only permissive NV fine-tuning corpus; Emilia-NV (573 h Mandarin) is CC BY-NC-SA.
   The Aug-2026 DPO result (NV-CER 3.62 -> 2.59 on CosyVoice2-0.5B) shows preference RL on
   a 0.5B model is the cheap lever — the same lever Parcel already plans for the behavior
   model.
7. **Ship-blocking licenses to avoid:** Fish/OpenAudio (CC-BY-NC-SA / Fish Research),
   Breeze-TTS-2 weights (non-commercial), IndexTTS (bilibili license), Higgs TTS 3
   (non-commercial), Omine released weights (research), Laughterscape corpus (R&D only),
   ehehe-corpus (JP Art. 30-4), Emilia-NV (NC).

---

## 7. Open questions / not verified
- Whether Orpheus Korean research checkpoints honour `<laugh>` (no doc; needs a 10-minute test).
- Actual tok/s of a 3B SNAC-TTS on AGX Orin 64 GB (no public number; the first-sweep 8B figure
  suggests 3B ~2x that).
- KsponSpeech / AI Hub license text (page not fetched).
- OmniVoice repository license (paper CC BY 4.0; repo license unverified).
- Step-Audio-EditX weights license (card states Apache-2.0 for the code).
- Whether NVBench data/code carry a license (page says "Available at lmxue.github.io/NVBench").
