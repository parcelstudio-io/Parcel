# HS-1 — humor signal: can the dog tell that a joke was funny?

Experiment code for `DESIGN.md` (frozen pre-registration) as amended by
`AMENDMENTS.md` (POST-START, binding). **Fable designs and verifies; Opus
implements** — `RESULTS.md` carries numbers only, `VERDICT.md` is Fable's.

**No hosted API calls of any kind were made.** Every model ran locally on this
host. Hosted cost: **$0.00**.

## Reproduce

```bash
export HF_HOME=~/.cache/parcel-0e/hf
~/.cache/parcel-0e/venv/bin/python research/20260828/humor-signal-1/run.py --all
```

Sub-flags: `--laughter` (HS1a), `--prior` (HS1b), `--taste` (HS1c). Everything
lands in `results.json`, plus a per-section sidecar `results_hs1{a,b,c}.json` and
the derived `owner_taste_prior.json`. Run from any directory; `run.py` puts its
own folder on `sys.path` and sets `HF_HOME`, `OPENBLAS_NUM_THREADS=32`,
`OMP_NUM_THREADS=32` if they are unset.

Order matters only in that HS1c writes `owner_taste_prior.json` and HS1b folds
its joke-category tagging into it; `--all` runs HS1c -> HS1a -> HS1b for that
reason.

## Environment

`~/.cache/parcel-0e/venv/bin/python` — Python 3.14.4, torch 2.13.0+cu130
(CUDA 13), transformers 5.16.1, numpy 2.5.2, scipy 1.18.1, scikit-learn 1.9.0,
pandas. Installed for this experiment: `soundfile librosa openpyxl xlrd torchaudio`.
GPU: NVIDIA RTX 5000 Ada, 32 GB.

**GPU cap.** `hs1b_prior.py::pick_model()` reads free VRAM at run time: >= 20 GB
free -> `Qwen/Qwen2.5-7B-Instruct` (bf16, within the 18 GB allowance); otherwise
the pre-registered fallback `Qwen/Qwen2.5-3B-Instruct`. The choice and the free-VRAM
reading are recorded in `results.json` under `hs1b.model_selection_note`, so the
run is self-documenting about which model produced the correlation.

## Data sources and checksums

Everything is cached under `~/.cache/parcel-0e/data/`.

| dataset | source URL | sha256 | bytes |
|---|---|---|---|
| ESC-50 | `https://github.com/karolpiczak/ESC-50/archive/master.zip` | `805afc618aff80eff0641d51311647871fead5807da68bb18e43a27db47a79ce` | 645,695,005 |
| Jester 1, part 1 | Wayback, see note | `cb7841756ded125b15f3d95c9f8241224065e96354c132a46ae4214deeab7615` | 4,171,628 |
| Jester 1, part 2 | Wayback, see note | `4d312fd824d8c8cb2c9c952a7b1fb7c00d1f5fd3ece370f7285aa701d371748b` | 3,924,205 |
| Jester 1, part 3 | Wayback, see note | `7f548d3762d3506cf7cd37d8cb9e3adb67984a7da7aa2d2096d5e0b1b884758d` | 2,151,299 |
| Jester 1 joke texts | Wayback, see note | `874a97180ac49a1d815ab6829fd9411021cdd25a92557dc39af46a26d5d1a9da` | 92,053 |
| LibriSpeech dev-clean | `https://www.openslr.org/resources/12/dev-clean.tar.gz` | `76f87d090650617fca0cac8f88b9416e0ebf80350acb97b343a85fa903728ab3` | 337,926,286 |
| Piper voice (in-repo, read-only) | `models/piper/voice.onnx` | `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f` | 63,201,294 |

**Jester source note.** `DESIGN.md` names `https://eigentaste.berkeley.edu/dataset/`.
That host was **unreachable** from this machine at run time (DNS resolves to
128.32.175.56; both :443 and :80 time out), and `goldberg.berkeley.edu/jester-data/`
404s. The files were recovered from the Internet Archive snapshot of the original
URLs:

```
https://web.archive.org/web/20260301101947id_/https://eigentaste.berkeley.edu/dataset/jester_dataset_1_1.zip
https://web.archive.org/web/20260301101947id_/https://eigentaste.berkeley.edu/dataset/jester_dataset_1_2.zip
https://web.archive.org/web/20260301101947id_/https://eigentaste.berkeley.edu/dataset/jester_dataset_1_3.zip
https://web.archive.org/web/20260301101948id_/https://eigentaste.berkeley.edu/dataset/jester_dataset_1_joke_texts.zip
```

Wayback rate-limits (HTTP 429); `~/.cache/parcel-0e/data/fetch_jester.py` retries
with backoff. Two HuggingFace mirrors (`kitkatdafu/jester_rating`,
`SeppeV/rated_jokes_dataset_from_jester`) were checked and **rejected** — both are
Jester dataset **2** (59,132 users x 140 jokes x 1.76 M ratings), not the dataset 1
the design pre-registers. The recovered matrix parses to exactly the size the
design states — 73,421 users x 100 jokes, 4,136,360 observed ratings — which is
the check that the recovery is faithful.

To re-download from scratch:

```bash
mkdir -p ~/.cache/parcel-0e/data && cd ~/.cache/parcel-0e/data
wget -O esc50.zip https://github.com/karolpiczak/ESC-50/archive/master.zip
unzip -q esc50.zip -d esc50
wget -O librispeech-dev-clean.tar.gz https://www.openslr.org/resources/12/dev-clean.tar.gz
mkdir -p librispeech && tar xzf librispeech-dev-clean.tar.gz -C librispeech
~/.cache/parcel-0e/venv/bin/python ~/.cache/parcel-0e/data/fetch_jester.py   # Wayback, with backoff
```

The Piper TTS negatives are rendered on first use by `negatives.py` into
`~/.cache/parcel-0e/data/piper_tts/`, by invoking the repo's own
`third_party/piper/piper` with `models/piper/voice.onnx` — the same binary and
voice `src/parcel_robot/providers.py::PiperSpeechProvider` uses in production.
Both are read **read-only**; nothing under `src/`, `models/`, or `third_party/`
is modified.

## Files

| file | what it is |
|---|---|
| `DESIGN.md` | Fable's frozen pre-registration (not edited) |
| `AMENDMENTS.md` | Fable's binding POST-START amendments H1–H7 (not edited) |
| `run.py` | entry point, `--all` / `--laughter` / `--prior` / `--taste` |
| `hs_common.py` | paths, seed, locked `results.json` writer, bootstrap helper |
| `jester_data.py` | Jester-1 loader (Excel -> npz) + joke-text extraction |
| `negatives.py` | H2 negative slices: LibriSpeech speech + the repo's own Piper TTS |
| `hs1a_laughter.py` | HS1a: AST scoring, per-slice AUROC, operating point, onset latency, compute latency |
| `hs1b_prior.py` | HS1b: LM funniness ratings (2 paraphrases), H6 memorisation probe, joke-category tagging |
| `hs1c_taste.py` | HS1c: between-user SD, biases-only baseline, residual clustering, held-out RMSE, noise ceiling |
| `results.json` | every number the design and the amendments ask for |
| `results_hs1a.json`, `results_hs1b.json`, `results_hs1c.json` | per-section sidecars |
| `owner_taste_prior.json` | **derived artifact** for FL-1 (see below) |
| `RESULTS.md` | Opus: what ran, raw numbers, each bar met / not met |
| `VERDICT.md` | Fable's, not written here |

## `owner_taste_prior.json` — a derived artifact, not a measurement

Six k-means taste clusters over **bias-centred residuals** of real Jester-1 users,
with per-cluster per-joke mean ratings, taste residual vectors, cluster weights,
the joke-bias vector `b_j`, and a model-tagged 6-category joke mapping. It exists
so FL-1's synthetic owners inherit *real* human preference spread instead of
invented noise. It is **not** a measurement of the Parcel owner, and the file says
so in its own `_derived_artifact` field.

Read `RESULTS.md` before using it: HS1c found that six clusters buy only 2.06 %
RMSE over a biases-only baseline (oracle assignment: 5.95 %), so "6 clusters" must
not be treated as a claim that six synthetic owners span owner taste.

## Determinism

Seed `20260828` everywhere (`hs_common.SEED`); the held-out assign/eval split uses
`20260829`. LM decoding is greedy (`do_sample=False`). Bootstraps are 2000 resamples
from a seeded `numpy.random.default_rng`. The Jester matrix is memoised to
`~/.cache/parcel-0e/data/jester1_matrix.npz` after the first (~90 s) Excel parse.
