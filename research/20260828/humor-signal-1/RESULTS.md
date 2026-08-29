# HS-1 — RESULTS (Opus, parcel-0e, 2026-08-28)

Implementation of the frozen `DESIGN.md`. No criterion was moved. No hosted
calls of any kind were made; every model ran locally on this host.
Fable writes `VERDICT.md` — there is no verdict here, only numbers.

Reproduce: `~/.cache/parcel-0e/venv/bin/python research/20260828/humor-signal-1/run.py --all`

## Data provenance (deviation from DESIGN.md's stated URL — recorded, not waived)

`DESIGN.md` names Jester dataset 1 at `https://eigentaste.berkeley.edu/dataset/`.
**That host was unreachable from this machine at run time** — DNS resolves
(128.32.175.56) but both :443 and :80 time out; `goldberg.berkeley.edu/jester-data/`
returns 404. Two HuggingFace mirrors (`kitkatdafu/jester_rating`,
`SeppeV/rated_jokes_dataset_from_jester`) were inspected and **rejected**: both
carry 59,132 users x 140 jokes x 1.76 M ratings, i.e. Jester dataset **2**, not
the dataset 1 the design pre-registers.

The genuine dataset-1 files were recovered from the Internet Archive snapshot of
the original Berkeley URLs, and the recovered matrix matches the design's stated
size exactly (73,421 users, 4.1 M ratings, 100 jokes), which is the check that
the recovery is faithful:

| file | source | sha256 | bytes |
|---|---|---|---|
| `jester_dataset_1_1.zip` | `web.archive.org/web/20260301101947id_/https://eigentaste.berkeley.edu/dataset/…` | `cb7841756ded125b15f3d95c9f8241224065e96354c132a46ae4214deeab7615` | 4,171,628 |
| `jester_dataset_1_2.zip` | same | `4d312fd824d8c8cb2c9c952a7b1fb7c00d1f5fd3ece370f7285aa701d371748b` | 3,924,205 |
| `jester_dataset_1_3.zip` | same | `7f548d3762d3506cf7cd37d8cb9e3adb67984a7da7aa2d2096d5e0b1b884758d` | 2,151,299 |
| `jester_dataset_1_joke_texts.zip` | `…/20260301101948id_/…` | `874a97180ac49a1d815ab6829fd9411021cdd25a92557dc39af46a26d5d1a9da` | 92,053 |
| `esc50.zip` (ESC-50 master archive) | `https://github.com/karolpiczak/ESC-50/archive/master.zip` | `805afc618aff80eff0641d51311647871fead5807da68bb18e43a27db47a79ce` | 645,695,005 |

Parsed shapes, printed before any statistic was computed:
ESC-50 = 2000 clips / 50 classes, with all 10 pre-registered classes present at
40 clips each; Jester-1 = **(73,421 x 100)** with **4,136,360** observed ratings
(56.3 % dense), and 100 joke texts extracted cleanly.

---

## Amendments applied

`AMENDMENTS.md` (POST-START, binding) landed while data was still downloading.
Applied in full: **H1, H2, H3, H4, H5, H6, H7**. Where an amendment replaced a
choice, both the amended number and the originally pre-registered number are
reported so each bar can be adjudicated separately. The one HS1a run that had
started under the un-amended label set and 0.5 s hop was killed before any
result was read; every number below comes from the amended code.

---

## HS1c — owner taste is real variance, not noise

Evidence tier: `replay` (public corpus, no model). Wall time: **13.4 s**
(after a one-off ~90 s Excel parse cached to `.npz`).
Amendments applied: **H5** (biases-only baseline, residual clustering,
split-half assignment, noise ceiling), **H7** (tier).

**What ran.** All 73,421 Jester-1 users x 100 jokes; 4,136,360 observed ratings.
Dense core = users with >= 36 ratings (48,483 users, 66.0 %), split 80/20 by user
with seed 20260828 into 38,786 train / 9,697 held-out. A biases model
`mu + b_user + b_joke` was fitted on the train users by alternating means
(mu = 0.817, b_joke in [-4.54, +2.79]). k-means k=6 (seed 20260828) then ran on
the **bias-centred residuals**, not the raw vectors.

**Held-out protocol (H5, no leakage).** Each held-out user's observed ratings are
split 50/50. The **assign half** yields that user's own bias `b_u` and picks the
nearest residual centroid using only those jokes; the **eval half** is predicted
and scored. No eval rating touches assignment. 354,627 held-out ratings scored.

**Raw numbers.**

| held-out predictor | RMSE (−10..10 scale) |
|---|---|
| global per-joke mean (the design's original baseline) | 5.0350 |
| **biases-only, `mu + b_u + b_j`** (H5's amended baseline) | **4.3702** |
| 6-cluster residual model | **4.2802** |
| oracle cluster (best of 6 per user, ceiling on the family) | 4.1100 |

| improvement of the 6-cluster model | value |
|---|---|
| over the global mean (original bar's comparison) | **14.99 %** |
| **over biases-only (H5's amended comparison)** | **2.06 %** |
| oracle-assignment ceiling over biases-only | 5.95 % |

| other reported quantities | value |
|---|---|
| between-user SD of the per-joke rating, median over 100 jokes | **5.102** |
| same, mean / min / max | 5.086 / 4.412 / 5.814 |
| jokes whose between-user SD exceeds 3.0 | **100 / 100** |
| split-half reliability of the per-joke mean profile (Pearson, 20 repeats) | 0.9994 |
| same, Spearman-Brown corrected (noise ceiling) | **0.9997** |
| residual-cluster sizes | 4802 / 4775 / 9850 / 4817 / 11105 / 3437 |
| cluster weights | 0.124 / 0.123 / 0.254 / 0.124 / 0.286 / 0.089 |

**Pre-registered and amended bars.**

- Bar (quoted, DESIGN.md): *"the between-user standard deviation of the per-joke
  rating exceeds 3.0 points on the −10..10 scale for the median joke"* —
  **MET**: median 5.102 > 3.0. The *minimum* over all 100 jokes (4.412) already
  clears it, so no joke fails. H5 keeps this as a reported number.
- Bar (quoted, DESIGN.md): *"a 6-cluster k-means over users' rating vectors
  reproduces a held-out user's ratings better than the global mean (RMSE lower
  by ≥ 10 %)"* — **MET as written**: 14.99 % lower than the global mean.
- Bar (quoted, AMENDMENTS.md H5): *"amended bar: ≥ 10 % RMSE improvement over
  biases-only"* — **NOT MET**: 2.06 %, an order of magnitude short of the bar.

**Surprises — this is the important one.**

1. **The original bar was carried by the weakness of its baseline.** Almost all of
   the 14.99 % "cluster" win is just user rating bias: some Jester users rate
   everything high, some everything low, and the global-mean baseline models none
   of that. Subtract `b_u` and the six taste clusters are worth **2.06 %**.
2. **The 6-cluster family cannot reach the amended bar even with perfect
   assignment.** The oracle that hands each held-out user their single best
   cluster still only reaches 5.95 %. So the 2.06 % is not an assignment failure
   that better inference could fix — k=6 taste types is simply too coarse a model
   of Jester taste. Raising k, or using a factor model, is the follow-up; six
   clusters is not it.
3. **Taste disagreement is nonetheless enormous and real.** The SD result is not
   close to its bar (5.10 vs 3.0, every joke clearing it), and the split-half
   reliability of 0.9997 says the per-joke signal is measured essentially without
   noise at this sample size. So the disagreement between users is genuine
   structure, not measurement error — it is just *not* six-cluster-shaped.
4. Consequence for the derived artifact: `owner_taste_prior.json` is still a fair
   sample of real human spread (that is what H5 leaves intact), but FL-1 must not
   treat "6 clusters" as a claim that six synthetic owners span owner taste.

---

## HS1a — laughter is detectable locally

Evidence tier: `replay` (H7). Wall time: **6.9 min** (550 clips scored + latency).
Amendments applied: **H1** (laughter-family label set), **H2** (speech and own-TTS
negative slices), **H3** (out-of-sample threshold + `operating_point`),
**H4** (streaming onset latency), **H7** (tier).

**What ran.** `MIT/ast-finetuned-audioset-10-10-0.4593`, **86.6 M params**, bf32
on an NVIDIA RTX 5000 Ada. 550 clips: 40 ESC-50 `laughing` positives, 360 ESC-50
human non-speech negatives (the nine classes DESIGN.md names, 40 each), 100
LibriSpeech dev-clean read-speech negatives (40 speakers), and 50 negatives
rendered by **the repo's own production Piper voice** through
`third_party/piper/piper` + `models/piper/voice.onnx` — the same binary and voice
file `src/parcel_robot/providers.py::PiperSpeechProvider` uses (read-only).
Audio resampled to 16 kHz, scored in 1-s windows at a **250 ms hop** (H4), and a
clip's score is the max over its windows.

**H1 label set (ids recorded).** Laughter score = max over the six AudioSet
laughter-family labels: `Laughter`(16), `Giggle`(18), `Snicker`(19),
`Belly laugh`(20), `Chuckle, chortle`(21), `Baby laughter`(17).

**H2 chuckle-asset search.** The only `chuckle` artifact under `src/` is
`runtime_assets/configs/skills/trajectories/chuckle.yaml`, a **motion** trajectory,
not audio. The repo ships no laugh/chuckle audio asset, so that sub-slice of H2 is
empty; recorded rather than substituted.

**Separation — raw numbers** (bootstrap 95 % CI, stratified over clips, n=2000).

| slice (positives = 40 ESC-50 `laughing`) | AUROC | 95 % CI | AUPRC |
|---|---|---|---|
| ESC-50 human non-speech (360) — *upper bound* | **0.9870** | [0.9766, 0.9943] | 0.9106 |
| **read SPEECH, LibriSpeech (100)** | **0.9992** | **[0.9970, 1.0000]** | 0.9968 |
| **own Piper TTS (50)** | **1.0000** | [1.0000, 1.0000] | 1.0000 |
| all negatives pooled (510) | 0.9905 | — | 0.9241 |
| ESC-50, single `Laughter` label only (H1 comparison) | 0.9590 | — | — |

**H3 operating point (this is what FL-1 consumes).** Threshold **−2.2592**,
chosen by Youden J on ESC-50 **folds 1–4**, then reported on held-out **fold 5**:

| | n | TPR | FPR | accuracy |
|---|---|---|---|---|
| folds 1–4 (in-sample) | 320 | 1.000 | 0.0382 | 0.9656 |
| **fold 5 (held out)** | 80 | **0.625** | **0.0556** | **0.9125** |
| speech slice at this threshold | 100 | — | **0.0000** | — |
| own Piper TTS at this threshold | 50 | — | **0.0000** | — |

**H4 streaming behaviour** (1-s window, 250 ms hop, onset annotated as the first
RMS frame above 20 % of the clip's peak RMS):

| quantity | value |
|---|---|
| positive clips detected at the operating threshold | 37 / 40 (3 missed) |
| time to first detection, p50 | **1.00 s** |
| time to first detection, p95 | **2.81 s** |
| time to first detection, min | 0.82 s |
| false triggers/min — ESC-50 human non-speech (25.5 min) | **1.65** |
| false triggers/min — read speech (13.2 min) | **0.00** |
| false triggers/min — own Piper TTS (1.1 min) | **0.00** |

Detection time includes the 1.00 s of window fill by construction, so p50 = 1.00 s
means the *first* full window containing the laugh already fires.

**Compute latency** (batch 1, one 1-s window, log-mel extraction included, 200 reps):

| device | p50 | p99 |
|---|---|---|
| GPU (RTX 5000 Ada) | **30.4 ms** | **31.5 ms** |
| CPU, `torch.set_num_threads(1)` | **2265.6 ms** | **2358.1 ms** |

**Pre-registered and amended bars.**

- Bar (quoted, DESIGN.md): *"separates human laughter from other non-speech human
  sounds at AUROC ≥ 0.95"* — **MET**: 0.9870, CI lower bound 0.9766 also clears it.
- Bar (quoted, AMENDMENTS.md H2): *"the pre-registered ESC-50 AUROC ≥ 0.95 AND the
  speech-slice lower bound ≥ 0.90"* — **MET**: 0.9870 and speech lower bound
  **0.9970**, far above 0.90.
- Bar (quoted, DESIGN.md): *"runs at ≤ 100 ms per 1-s window on this GPU"* —
  **MET**: p50 30.4 ms, p99 31.5 ms.
- Bar (quoted, DESIGN.md): *"and ≤ 500 ms on one CPU thread"* —
  **NOT MET**, and not marginally: p50 **2265.6 ms**, **4.5x over the bar**. One
  CPU thread cannot run this model in real time at all — a 1-s window takes 2.3 s.

**Surprises.**

1. **The self-excitation risk is zero at this operating point, and that was the
   amendment's whole worry.** The dog's own Piper voice separates *perfectly*
   (AUROC 1.0000, 0 false triggers in 1.1 min), and read speech gives 0 false
   triggers in 13.2 min. The negatives that actually break the detector are the
   ESC-50 *human non-speech* ones — 1.65 false triggers/min, 15 of 360 clips.
   The reward signal's real enemy is coughing/crying/clapping, not the dog's TTS.
2. **The laughter *family* label set matters a lot** (H1 was the right call):
   0.9870 with the six-label max vs **0.9590** with the single `Laughter` label —
   the bar would have been cleared either way, but the family max removes about
   two-thirds of the remaining error.
3. **The held-out fold-5 TPR is only 0.625** while folds 1–4 gave TPR 1.000 at the
   same threshold. With 8 positives in fold 5 that is 5/8, so the confidence
   interval is very wide — but it is a concrete warning that the in-sample Youden
   threshold is optimistic, which is exactly what H3 was written to expose.
4. **CPU-only deployment of this model is off the table.** 2.27 s per 1-s window on
   one thread is not a tuning problem; it is the wrong model for a CPU budget. On
   GPU there is 30x headroom. Either the laughter listener gets GPU on the dog, or
   it needs a much smaller model (the design's BEATs/PANNs alternates, or a
   purpose-built laugh detector).

---

## HS1b — a funniness prior without the laugh (section written by the verifier from `results_hs1b.json`; the executor was killed by the account spend limit at 18:27 after this row finished at 18:26)

Evidence tier: `replay` (H7). Wall time **492 s**. Amendments applied: **H6**
(verbatim-completion probe, verdict bands), **H7** (tier). Model:
**Qwen/Qwen2.5-7B-Instruct** (7.62 B params, bf16; the GPU had ≥ 20 GB free so
the 7–8 B step was allowed), greedy decoding, one call per joke, two prompt
paraphrases (A: "how funny an average adult reader would find it"; B:
"estimate the average funniness rating a large group of ordinary people would
give"), integer scale −10..10.

| statistic | paraphrase A | paraphrase B | **mean of paraphrases** |
|---|---|---|---|
| Spearman ρ vs Jester mean | 0.198 [−0.000, 0.388] | 0.253 [0.053, 0.432] | **0.219 [0.023, 0.399]** |
| Pearson r | 0.185 [0.006, 0.355] | 0.178 [−0.001, 0.354] | 0.195 [0.025, 0.364] |
| distinct predicted values | 6 | 6 | 13 |
| predicted mean / min / max | 1.49 / −5 / 7 | 0.86 / −5 / 6 | 1.18 / −5 / 6.5 |

Paraphrase agreement: Spearman 0.743 between the two prompts (the model is
consistent with itself; it is just not consistent with people).

**H6 memorisation probe.** First 40 % of each joke given, exact continuation
requested: exact-continuation rate (≥ 8 consecutive shared words) **0.02**
(2/100 jokes); longest shared run mean 2.15 words, p90 5.0. The 1990s Jester
jokes are not memorised by this model, so the low ρ is not a contamination
artefact hiding a higher true one.

**H6 verdict bands (quoted from AMENDMENTS.md):** CONFIRMED = point ρ ≥ 0.40
and lower bound ≥ 0.25; REFUTED = upper bound < 0.40. Mean-of-paraphrases
upper bound **0.399 < 0.40 → REFUTED band**. The original DESIGN.md bar
(ρ ≥ 0.40; refuted below 0.25) puts the point estimate 0.219 **below the
refute line** as well.

**Derived artifact (DERIVED, tagged by the same local model):** the 100 jokes
were classified into 6 coarse categories — wordplay_or_pun 45,
sex_or_relationships 17, professions_or_workplace 14, absurd_dark_or_other 13,
politics_or_current_affairs 8, religion_or_clergy 3 — written into
`owner_taste_prior.json` beside the six residual clusters. FL-1's named
consumer is the per-category Beta prior; FL-1 ran before this file existed
and used its synthetic prior instead (recorded in FL-1's RESULTS.md).

**Surprise.** The 7B model's ratings collapse onto a handful of values (6
distinct per prompt) — it rates most jokes "−2" or "2". A funniness *prior*
from a local text model is close to useless for this corpus; the literature
sweep's numbers (GPT-4-Turbo 67 % vs editor 94 % on New Yorker captions) said
the same for a far larger model.
