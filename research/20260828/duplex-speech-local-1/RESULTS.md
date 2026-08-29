# RESULTS — DS-1, is an open full-duplex speech model a usable local backbone?

Executor: Opus (parcel-0e), 2026-08-28. Written incrementally as each
sub-hypothesis finished. Pre-registered in `DESIGN.md`; amended mid-flight by
`AMENDMENTS.md` (POST-START, binding). **No verdict here — Fable writes
`VERDICT.md`.**

Evidence tier: **`desktop-local-model`** (AMENDMENTS.md D5) — a desktop GPU
benchmark of a locally-run model on this host's RTX 5000 Ada 32 GB. This is
**not** one of the tiers registered in `research/README.md`; the label is
**proposed, not registered**. `results.json` carries it in
`evidence_tier_label`. **No hosted calls, $0 spent.**

**Wall clock: 17:41 -> 18:25**, against a ~3.5 h budget. Weight download 390 s.
The GPU was free for the first runs; from 18:05 two-to-three peer parcel-0e jobs
took the card (reaching 29.8 GB used / 2.3 GB free by 18:24), which gated the
last three measurements and produced a finding of its own — see D1's contention
note.

---

## Amendments applied

`AMENDMENTS.md` landed at 17:57, after H-DS1a's first row had been measured but
**before** it was read as a result. All five items were addressed. The
pre-registered `DESIGN.md` bars are reported unchanged; amended bars are
reported **in addition**, never in place of them.

| amendment | status | where |
|---|---|---|
| **D1** p99 bar, >= 2,000 steps, decode every step, GPU util / co-residents / load | **APPLIED — re-ran, all bars met** | H-DS1a |
| **D2** param delta both ways + config flag + stream order | **APPLIED — bar MISSED at the amended act-last ordering (2.56 M > 1 M)** | H-DS1b |
| **D2** "code sites" as a diff-line count vs the pinned rev | **APPLIED — bar MISSED (7 sites, 72 lines)** | H-DS1b |
| **D2** resampling contract with dropped tokens counted | **APPLIED** | H-DS1b |
| **D2** act stream terminates only in `DuplexFrameConsumer` | **APPLIED — verified in source** | H-DS1b |
| **D2** measured act-stream step-time delta (p99 delta <= 5 ms) | **UNMEASURED — GPU gated** (built and functionally verified; harness ready) | H-DS1b |
| **D2** one-batch `moshi-finetune` dry run | **NOT RUN — cannot install** (pins `torch==2.6`, no cp314 wheel) | H-DS1b |
| **D3** co-resident budget (AST + GRU) | **UNMEASURED — GPU gated**, with the free-memory log, as D3 permits | D3 |
| **D4** candidates table + training-data / GPU-hours half | **APPLIED** (GPU-hours is an estimate — see below) | H-DS1c |
| **D5** tier label | **APPLIED** | header + `results.json` |

Three amended items could not be measured because two-to-three peer parcel-0e
jobs held the GPU from 18:05 onward; the free-memory log is in D3 below and the
reason each one cannot honestly be run under contention is given at its section.
**Two amended bars were met, two were missed, three are unmeasured.**

---

## 0. Setup, environment, and licenses

Weight download was launched first (17:42) and finished 17:49 — 15.4 GB in
**390 s**. Code reading for H-DS1b happened during the download, as briefed.

**Environment.** `~/.cache/parcel-0e/venv-moshi`, created with
`/usr/bin/python3.14 -m venv --without-pip` and bootstrapped with the project
venv's pip (the system python has no `ensurepip`).

- **Python 3.14 is supported — the anticipated blocker did not materialize.**
  `moshi`'s `pyproject.toml` declares `requires-python = ">= 3.10,<3.15"`, so no
  fallback to a GitHub install or a source-tree import was needed.
- Installed from the pinned clone of `github.com/kyutai-labs/moshi`
  @ **`e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`** (2026-05-16), package version
  **0.2.13**, via `pip install --no-deps -e`.
- Runtime: **torch 2.11.0+cu128**, CUDA 12.8, numpy 2.5.2, sphn 0.2.1,
  sentencepiece 0.2.2, safetensors 0.8.0, transformers 5.16.1.

### Three deviations, all recorded rather than hidden

1. **Dependency pins exceeded, of necessity.** moshi 0.2.13 pins
   `numpy<2.3`, `safetensors<0.8.0`, `torch<2.10`. **None of those have cp314
   wheels**; pip fell back to building numpy from source and failed
   (`meson.build:41:12: ERROR: Python dependency not found` — no
   `python3.14-dev` headers, and installing them needs root). Installed the
   newest wheel-available versions (`--only-binary=:all:`), above moshi's upper
   pins. The model loads and produced correct output, so the drift is benign in
   practice — but the run was **not** on the library's declared dependency set.
2. **`sounddevice == 0.5` not installed.** Needs PortAudio; imported only by
   `moshi.client` / `moshi.server` for live microphone I/O, which DS-1 does not
   exercise.
3. **`NO_TORCH_COMPILE=1`.** Triton could not JIT (`/usr/bin/gcc ...
   -I/usr/include/python3.14` fails — the same missing headers). moshi exposes
   this env var for exactly this case. It disables `torch.compile` on three
   small elementwise helpers only (`modules/rope.py:11`,
   `modules/gating.py:13`, `modules/transformer.py:45`). **This can only make
   the measured step slower, never faster**, so every timing below is a
   conservative upper bound. The CUDA-graph path
   (`utils/compile.py::CUDAGraphed`) — the large win for step time — does not
   use Triton and stayed active.

**Weights.** `kyutai/moshiko-pytorch-bf16`, snapshot
`2bfc9ae6e89079a5cc7ed2a68436010d91a3d289`, `HF_HOME=~/.cache/parcel-0e/hf`.
`model.safetensors` 15,375,500,136 B; Mimi codec 384,644,900 B; text tokenizer
552,778 B.

### Licenses (recorded exactly, as DESIGN.md requires)

From the downloaded model card of `kyutai/moshiko-pytorch-bf16`:

- YAML front-matter, verbatim: **`license: cc-by-4.0`**
- Body, verbatim: **`- **License:** CC-BY`**
- Also on the card: `language: - en`, and verbatim: *"This model is for research
  only and we do not recommend it for providing advices or to perform any
  professionnal duty."* (sic)

Code licenses are separate: `LICENSE-MIT` and `LICENSE-APACHE` are both at the
repo root; the Python package declares `license = {text = "MIT"}`.

**Weights CC-BY-4.0** — attribution required, commercial use permitted, no NC
and no ND clause — and **Python code MIT**. The "research only" sentence is
prose on the card, not a license term: a risk signal to raise with the owner,
not a legal bar. `language: - en` is the more consequential line (see D4).

---

## H-DS1a — does it run here in real time?

**Pre-registered bar (`DESIGN.md`), quoted:** *"per-step time <= 80 ms for its
12.5 Hz frame (i.e. real-time factor <= 1.0) in bf16, with peak GPU memory
<= 24 GB. Measured on >= 30 s of a public WAV or a synthetic prompt; report
p50/p99 step time, RTF, and memory."*

**Amended bar (D1), quoted:** *"step-time p99 <= 80 ms (report p50 and the
fraction of steps > 80 ms too); >= 2,000 measured steps (>= 170 s of audio); the
decode branch runs on every step; the row records GPU utilisation, co-resident
processes, and 1-min load at start and end."*

**GPU gate.** `gpu_wait.py` logged `poll=1 free=30146 MiB used=2083 MiB
need=26624 MiB CLEAR`, with only desktop processes (204 MiB) resident. Log:
`~/.cache/parcel-0e/ds1/gpu_wait.log`.

**What ran.** `run.py` drives the reference loop — `mimi.encode(chunk) ->
LMGen.step(codes) -> mimi.decode(tokens[:, 1:])` — copied in structure from
`moshi/run_inference.py::InferenceState.run`, including its double-step of the
first frame. Input: **200.0 s of real speech**,
`data/sample_fr_hibiki_crepes.mp3` from the moshi repo (a public sample shipped
with the package; 56.3 s looped x4). It is **French**, which does not affect
timing — a dense transformer's batch-1 step time is content-independent — but
means nothing here speaks to output quality. The synthetic path in `run.py` was
**not** used.

### Result — every bar met, pre-registered and amended

| quantity | measured | bar | met? |
|---|---|---|---|
| step p50 | **42.28 ms** | <= 80 ms (DESIGN) | **yes** |
| **step p99** | **43.66 ms** | **<= 80 ms (D1)** | **yes** (55% of budget) |
| step p90 / max | 43.11 / 44.69 ms | — | — |
| RTF p50 / **p99** | 0.529 / **0.546** | <= 1.0 | **yes** |
| **steps > 80 ms** | **0 of 2,492 (0.0000)** | reported (D1) | — |
| peak GPU allocated | **16.249 GiB** | <= 24 GB (DESIGN) | **yes** |
| **steps measured** | **2,492** | **>= 2,000 (D1)** | **yes** |
| audio | 200.0 s | >= 170 s (D1) | **yes** |
| **decode ran every measured step** | **yes (0 skipped)** | required (D1) | **yes** |

Host record (D1), from `results.json`:

| | GPU util | free | co-resident | load 1m | compute apps |
|---|---|---|---|---|---|
| start | 15% | 30,146 MiB | 204 MiB | 2.74 | 3 |
| end | 100% | 12,716 MiB | 204 MiB | 4.99 | 4 |

Co-residents at both ends were desktop processes only (Chrome GPU, ptyxis,
nautilus); the 100% utilisation and the memory drop at the end are this job
itself. **The run was clean.**

**Surprises.**

- **The tail is essentially absent.** Across 2,492 steps the whole spread is
  41.6-44.7 ms and p99/p50 = 1.033. Not one step exceeded 80 ms. That is CUDA
  graph replay doing its job: every frame replays an identical graph. For a
  real-time control loop this matters more than the mean — the budget is met by
  a *fixed* margin, not on average. It is also why D1's p99 bar, which could
  have been the amendment that broke the result, was met with room to spare.
- **~2x the required headroom** (RTF 0.55) even with `torch.compile` disabled.
- **Peak memory a third under the bar** (16.2 vs 24 GB), leaving room on this
  32 GB card for Moshi plus a second model — which D3 then tests directly.

**Contention finding (not pre-registered, worth recording).** After this run,
three other parcel-0e GPU jobs took the card. Under that contention the *same
stock model* measured **95.3 ms p50** — 2.3x slower, and over the 80 ms frame.
The step time is therefore not a property of the model alone; it is a property
of the model **with the card to itself**. Any deployment claim has to say what
else is resident. This is exactly what D1's co-resident recording is for, and it
is why the D2 comparison below was re-run under a gate.

**What this does not show.** Nothing about speech quality, Korean/English
handling, the mic array, or barge-in through a real speaker path — `DESIGN.md`
excluded all of these. Batch 1, one conversation.

---

## H-DS1b — is an action stream an architectural one-liner?

**Pre-registered bar (`DESIGN.md`), quoted:** *"Adding a Parcel act stream (the
`ActTokenCodec` vocabulary as one more codebook, ~90 tokens) requires only: one
embedding table, one linear head, a loss term, and training data of aligned
(audio, text, act) frames — no change to the temporal transformer."* Criterion:
*"the delta is <= 4 code sites and <= 1 M parameters."*

**Amended (D2):** the delta must be **measured** — randomly initialised act
modules attached to the stock model and run through the same streaming loop,
bar **p99 delta <= 5 ms with RTF still <= 1.0**; parameter delta reported **both
ways** with the exact config flag and the depformer stream order (**act stream
last**); "code sites" = **diff line count** against the pinned revision.

Design detail in **`INTEGRATION_NOTE.md`**. This section reports what was built
and measured.

### It was actually built

A real patch against `e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`, in
`~/.cache/parcel-0e/ds1/moshi-act`. The act stream is the **last generated
stream** (depformer step 8, `emb` index 8), as amended; the user's 8 audio
codebooks shift from `emb[8..15]` to `emb[9..16]`.

Design choice worth stating: **every stock checkpoint key still matches.** The
patch makes the existing `nn.ModuleList`s heterogeneous rather than adding
parallel modules, so `load_state_dict(strict=False)` reports *only* the act
modules as missing, and `_materialize_act_modules` gives those random weights.
`assert not unexpected` in the loader proves no pretrained tensor was orphaned.
The one thing that does not fall out for free is the `emb` index shift, which
needs an explicit remap (`_remap_for_act_stream`) or the pretrained user-audio
embeddings would silently load into the wrong streams.

### Code sites — MEASURED as a diff, and the bar is MISSED

`git diff --numstat` against the pinned revision:

| file | added | removed |
|---|---|---|
| `moshi/moshi/models/lm.py` | 22 | 3 |
| `moshi/moshi/models/loaders.py` | 46 | 1 |
| **total** | **68** | **4** |

Two files, **72 changed lines**. Against the pre-registered *"<= 4 code sites"*:
the architecture change in `lm.py` is **5 edit sites** (constructor args; `emb`;
`depformer_emb`; `linears`; `_get_initial_token`, plus the `_card_at` helper),
and `loaders.py` adds **2 more** (checkpoint remap, and materialising the new
modules). **7 sites, 72 lines — the <= 4 bar is NOT met.** Recording it as a
miss rather than arguing the definition. Two mitigations for the reader, offered
as context and not as a re-scoring: 25 of the 72 lines are the architecture and
47 are checkpoint-compatibility plumbing that a from-scratch training run would
not need; and no line of the temporal transformer, the depformer, or the
streaming loop changed.

**The pre-registered claim "no change to the temporal transformer" is CONFIRMED,
and more strongly than stated.** `forward_text` (`lm.py:379-408`) sums all
stream embeddings into one vector before the 32-layer stack, so it needed **zero
edits** — the act stream is picked up automatically by the existing
`for cb_index in range(self.num_audio_codebooks)` loop. `forward_depformer` also
needed zero edits. The library's own docstring for `audio_offset`
(`lm.py:298-304`) says *"in practice, but in the future we might want to support
>1"*: the authors anticipated this.

### Parameter delta — both ways, and the amended ordering MISSES the bar

From `act_param_delta.py`, building the **actual patched implementation** on the
`meta` device (`act_param_delta.json`). Baseline **7,687,729,152**.

| stream order | depformer slice | config flag | delta @ 90 | <= 1 M? |
|---|---|---|---|---|
| **act last (amended)** | **shared** | `depformer_weights_per_step_schedule=[0,1,2,3,4,5,6,7,7]` | **2,563,072** (2.56 M) | **NO** |
| **act last (amended)** | **per-step** | `depformer_weights_per_step=True`, no schedule (mult=9) | **83,827,712** (83.8 M) | **NO** |
| act first | shared | `schedule=[0,0,1,2,3,4,5,6,7]` | **558,080** (0.56 M) | **yes** |
| act first | per-step | no schedule | 81,822,720 (81.8 M) | NO |

At the codec's real vocabulary sizes the picture is unchanged: act-last/shared
is 2.38 M at 54 tokens and 2.45 M at 68; act-first/shared is 0.34 M and 0.42 M.

*Cross-validation:* the meta-device figure for act-last/shared (2,563,072)
matches the delta measured on the **real loaded GPU model** exactly
(7,690,292,224 − 7,687,729,152). And the baseline count matches H-DS1a's
`lm_params` exactly. The arithmetic is not free-floating.

**Two findings here, and they cut in opposite directions.**

1. **The per-step slice is a trap.** `depformer_weights_per_step = True`
   (`loaders.py:110`) means `modules/transformer.py:398-418` and `:684-715` give
   **every depformer step its own attention and FFN weights** — the depth
   transformer is 8 disjoint 6-layer transformers. Adding a 9th step clones a
   whole set: **83.8 M, 84x the bar.** The escape hatch is already in the
   library (`depformer_weights_per_step_schedule`, documented at `lm.py:69-70`),
   and it brings the cost down by a factor of ~33.
2. **The amended ordering costs 4.6x what act-first costs, and that is what
   breaks the bar.** `depformer_emb` holds `dep_q - 1` tables because *"the last
   codebook is never an input to Depformer"* (`lm.py:188-191`). With act
   **last**, a 9th step means audio codebook 7 becomes an input for the first
   time, requiring a new **2049-row** table (2,098,176 params). With act
   **first**, the new table is the 91-row act embedding (93,184). That single
   table is the entire difference between 2.56 M and 0.56 M — and between
   missing and meeting the 1 M bar.

So: **at the amended act-last ordering the <= 1 M bar is NOT met (2.56 M).** It
is met only at act-first (0.56 M). I implemented and measured act-last as
directed and am reporting it as the headline; act-first is offered as a design
finding for Fable to weigh, not as a substitution. Act-first also has the better
semantics — the depformer generates sequentially within a frame, so act-first
means the frame's audio is conditioned on the act the dog just chose (the bark
is shaped by the decision to lunge) rather than commenting on it after the fact.

### Measured step-time delta (D2's new bar) — UNMEASURED, gated

**Amended bar: p99 delta <= 5 ms vs stock, RTF still <= 1.0. This bar is
currently UNMEASURED, and I am not reporting a number I do not trust.**

The act stream was built and **does run** — that much is measured. With randomly
initialised act modules the streaming loop completed and emitted act tokens
spanning **[0, 89] with 63 distinct values**, in range and wired end to end
(`act_stream_shared.json`). Measured `lm_params` 7,690,292,224, i.e. exactly the
+2,563,072 the meta-device build predicts. So the wiring claim is settled.

What is **not** settled is the timing delta, because the card stopped being
mine. Timeline:

| time | run | p50 | p99 | card state |
|---|---|---|---|---|
| 18:00 | stock (`run.py`, D1) | 42.28 | **43.66** | clean, 30,146 MiB free |
| ~18:03 | shared act variant | 44.36 | **100.58** | contended |
| ~18:05 | stock, same harness | 42.28 | 43.59 | briefly clean again |
| ~18:07 | stock, diagnostic | **95.31** | — | contended (then OOM) |

The 18:07 row is the decisive one: **stock itself measured 95.31 ms** under
contention. So the act variant's 100.58 ms p99 is a measurement of GPU sharing,
not of the act stream. Reporting `100.58 - 43.66 = +56.9 ms` against a 5 ms bar
would be false precision about someone else's job.

The only defensible reading of what exists: the shared variant's **p50 of
44.36 ms against stock's 42.28 ms is a +2.08 ms delta**, and p50 is the
statistic least disturbed by intermittent contention. That is consistent with
the +12.5% of depformer work the 9th step adds (8 -> 9 sequential sub-steps on a
714 M-parameter stack). It is suggestive, not a result, and it is **not** the
p99 bar the amendment set.

**Why it stayed unmeasured.** From 18:05 the card carried two peer parcel-0e
jobs at 5,046 MiB each. `gpu_wait.py` polled every 60 s against the 26,624 MiB
gate and logged `WAIT` on every poll; free memory sat at **19,723-19,725 MiB**
and did not trend upward. Full poll log:
`~/.cache/parcel-0e/ds1/gate2.log`. Running anyway would have produced exactly
the contaminated numbers above.

**Ready to run the moment the card frees** (one command, ~4 min):
`d2_compare.py` loads stock, shared and per-step **back to back in one process**,
with a host snapshot per variant, so both arms of the delta are measured in the
same window. `PYTHONPATH=$ACT ... $VP d2_compare.py --audio "$AUDIO"`.

### Resampling contract, with dropped tokens COUNTED

`resample_contract.py` -> `resample_contract.json`. Moshi is 12.5 Hz / 80 ms
(`loaders.py:29`); Parcel is `frame_hz: float = 10.0` / 100 ms
(`duplex/config.py:22`, `duplex/frames.py:24`). Ratio **5:4 — no common frame,
no integer resampling.** The two directions are **not** symmetric, which is the
main thing this measurement establishes.

**Training direction (Parcel 10 Hz act log -> Moshi 12.5 Hz frames) is
UPSAMPLING — hold-last drops nothing, by construction:**

| non-idle events/s | events | dropped | fraction |
|---|---|---|---|
| 1.0 | 307 | **0** | 0.00% |
| 2.0 | 628 | **0** | 0.00% |
| 4.0 | 1,177 | **0** | 0.00% |

Each Parcel act covers 1 or 2 Moshi frames in a 4/5 alternating pattern; the
only cost is up to **80 ms of act-onset quantization jitter**.

**Inference direction (model emits at 12.5 Hz -> the 10 Hz DuplexFrame clock) is
DOWNSAMPLING, and hold-last does drop acts:**

| non-idle events/s | events | hold-last dropped | fraction | event-priority merge dropped |
|---|---|---|---|---|
| 1.0 | 301 | 15 | **4.98%** | **0** |
| 2.0 | 596 | 39 | **6.54%** | 2 (0.34%) |
| 4.0 | 1,163 | 114 | **9.80%** | 14 (1.20%) |
| 8.0 | 2,379 | 351 | **14.75%** | 173 (7.27%) |

Hold-last is what `FrameInterleaver.push_act` already does — *"Acts are states
for the current frame window — last write wins"* (`frames.py:52-55`) — so this
is the behaviour the product would get for free, and it silently discards
**5-15% of non-idle acts**.

**The contract, stated as the amendment asks:**

- **Recommended: set `DuplexConfig.frame_hz = 12.5.`** `frame_hz` is a
  constructor argument and `_period_s = 1.0 / hz` is derived from it
  (`frames.py:24-29`), so this is a config change, not a rewrite. It removes the
  resampling entirely and makes the control loop 20 ms *faster*. Cost: every
  cadence assumption tied to 100 ms (filler watchdog, response ceiling, TTLs)
  must be re-checked.
- **Fallback if the 10 Hz clock must stay: the event-priority merge**, not
  hold-last — each destination frame takes the earliest non-idle token in its
  window and carries a second one into the next frame. Zero drops up to
  1 event/s and ~1% at 4 events/s, at the cost of delaying at most one act by
  100 ms.
- **Resampling the audio to a 10 Hz codec frame is not an option** — 12.5 Hz is
  baked into Mimi's SEANet strides (`ratios: [8, 6, 5, 4]`, `loaders.py:37-55`);
  changing it invalidates the pretrained codec.

### Where the act stream terminates (as D2 requires stating)

**The act stream terminates only in `DuplexFrameConsumer`, which is shadow-only
today, behind the deterministic filter. No `push_twist` from the model.**
Verified in source, not assumed:

- `src/parcel_robot/duplex/consumer.py:21` — `shadow: bool = True`, defaulted on
  by `config.py:27` (`shadow_consumer: bool = True`) and wired at
  `coordinator.py:45`.
- In shadow mode `consume()` decodes and returns the `ActCommand` but never
  appends to `_executed`; only the live branch does, and its own comment reads
  *"Live mode (D1): only non-idle commands would enter admissibility."*
- `push_twist` runs the **opposite** direction: `runtime.py:17738` calls
  `self.duplex.push_twist(commanded.vx, commanded.vyaw)` — it records what the
  controller **already commanded** into the frame log. It is an observation of
  executed behaviour, not a command channel, so a model-emitted act cannot reach
  the body through it.

### moshi-finetune one-batch dry run — NOT RUN, and why

**Blocked: the package cannot be installed on this host.** `moshi-finetune`'s
`pyproject.toml` pins **`torch==2.6`**, and pip reports:

```
ERROR: Could not find a version that satisfies the requirement torch==2.6
       (from versions: 2.9.0, 2.9.1, 2.10.0, 2.11.0, 2.12.0, 2.12.1, 2.13.0)
```

Torch 2.6 predates Python 3.14 and has no cp314 wheel; this host has only
Python 3.14 (`/usr/bin/python3.14`, and `.parcel` is 3.14 too), and installing
an older interpreter needs root. (`sphn==0.1.12`, its other hard pin, *would*
install.) A dry run would require either a second Python or relaxing the torch
pin and hoping the trainer's internals survive a five-minor-version jump — both
outside DS-1's OWNS and neither honest to report as "the published recipe". The
recipe's parameters are instead read off the published config and used in D4's
GPU-hour estimate, clearly labelled as an estimate rather than a measurement.

---

## D3 — co-resident budget — UNMEASURED, gated

D3 provides for this: *"If the GPU never frees enough, mark UNMEASURED with the
free-memory log."* Doing exactly that.

Everything is staged: `d3_coresident.py` measures the streaming step with an
**AST laughter detector** (`MIT/ast-finetuned-audioset-10-10-0.4593`,
**86,594,063 parameters** — already downloaded to `~/.cache/parcel-0e/hf`) and a
**2x256 GRU** ticking at 10 Hz (on 4 of every 5 Moshi frames) resident on the
same card, and reports the step time, the fraction of the 80 ms frame consumed,
and the RTF at which the whole stack fits.

It cannot run honestly right now for the same reason as D2: the measurement is a
*co-residency* measurement, and the card already has uncontrolled co-residents.
Adding a third would measure the peer jobs, not the laughter detector.

**Free-memory log** (`~/.cache/parcel-0e/ds1/gate2.log`), every poll from 18:09:

```
18:09:56 poll=2  free=18891 MiB need=26624 WAIT  [4071156:1624, 4076457:5046, 4077477:4566]
18:12:56 poll=5  free=17015 MiB need=26624 WAIT  [4076457:5046, 4077477:5046, 4079223:1390]
18:15:57 poll=8  free=19723 MiB need=26624 WAIT  [4076457:5046, 4077477:5046]
18:20:57 poll=13 free=19724 MiB need=26624 WAIT  [4076457:5046, 4077477:5046, 4084793:310]
18:22:57 poll=15 free=19723 MiB need=26624 WAIT  [4076457:5046, 4077477:5046, 4084793:310]
18:23:57 poll=16 free= 2387 MiB need=26624 WAIT  [4076457:5046, 4077477:5046, 4084793:16252, 4087130:1390]
```

Two peer jobs held 5,046 MiB each throughout; free memory never rose above
19,725 MiB against a 26,624 MiB gate, and at 18:23 a third peer grew to
16,252 MiB, taking the card to **2,387 MiB free**. The trend was away from
clearing, not toward it.

**What can still be said without the measurement.** Moshi's own peak is
16.25 GiB and it uses **55% of the 80 ms frame** (p99 43.66 ms) when alone. AST
at 87 M parameters is ~0.17 GB in fp16 and the GRU ~1.2 M parameters, so
**memory is not the question** on a 32 GB card — contention for SM time is, and
the contention finding above (42 -> 95 ms from peer jobs alone) suggests the
answer is not obviously comfortable. That is a reason to measure it, not a
substitute for measuring it.

---

## H-DS1c — edge extrapolation to Jetson AGX Orin 64 GB

**Pre-registered ask, quoted:** *"state whether Moshi-7B fits the Orin's
real-time budget; if not, name the smallest open full-duplex alternative and its
size."* `DESIGN.md` notes this *"is a computed statement, not a verdict"*.
**Amended (D4):** >= 2 open alternatives with license, languages (Korean?),
parameter count, duplex style, and the Orin bandwidth arithmetic; plus the
training-data half.

Sources: `research/20260828/literature/notes/duplex-speech-llms.md` §6 (the
briefed `edge-deploy-and-go2-api.md` does not exist; the sibling agent's duplex
note carries the Orin evidence). Computation in `edge_extrapolate.py` and
`candidates.py`.

### Step 1 — is the bandwidth model even valid here? (measured, not assumed)

`profile_breakdown.py` splits the frame; `edge_extrapolate.py` measures this
host's achievable bandwidth:

| | value |
|---|---|
| Mimi encode p50 | 1.83 ms (4.4%) |
| **LM step p50 (temporal + depformer)** | **38.49 ms (91.4%)** |
| Mimi decode p50 | 1.77 ms (4.2%) |
| temporal transformer params | 6,576,930,816 |
| depformer stack params | 714,362,880 |
| achievable device bandwidth (measured) | **480 GB/s** (theoretical 576.1) |
| pure weight-sweep floor at bf16 | 15.375 GB / 480 GB/s = **32.0 ms** |
| **roofline efficiency** | **0.83** |

The LM step reaches **83% of the pure weight-sweep floor**, so batch-1 decode
here *is* bandwidth bound and scaling by bandwidth to another device is a sound
first-order model. This validation is what makes the extrapolation more than
arithmetic.

*Method note:* the first bandwidth run reported 234 GB/s and an impossible
efficiency of 1.71. Cause: a 5-iteration warmup measured the GPU in its P8
low-power state. With a 40-iteration warmup it is a stable 476-484 GB/s across
four trials. `measure_bandwidth_gbs` now warms up properly, takes best-of-N, and
its docstring records the trap.

### Step 2 — the projection

Orin AGX 64 GB: 64 GB LPDDR5 at **204.8 GB/s**
([nvidia.com](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/)).
Bandwidth ratio desktop/Orin = **2.35**.

| precision | weights | Orin LM step | + Mimi | **frame total** | RTF | fits 80 ms? |
|---|---|---|---|---|---|---|
| bf16 | 15.38 GB | 90.3 ms | 8.5 | **98.7 ms** | **1.23** | **NO** |
| int8 | 7.69 GB | 45.1 ms | 8.5 | **53.6 ms** | 0.67 | yes |
| int4 | 3.84 GB | 22.6 ms | 8.5 | **31.0 ms** | 0.39 | yes |

Two independent methods agree: roofline-anchored bf16 **98.7 ms**, naive
ratio-scaling of the measured p50 **97.8 ms**.

### Step 3 — a conservative anchor, because the idealized rows flatter

The table assumes Orin reaches the same fraction of its roofline as this
desktop. The one published 7B-class measurement on this exact board says
otherwise: **Qwen2.5-Omni-7B Q8_0, llama.cpp, AGX Orin 64 GB, 15.3-16.1 tok/s**
([llama.cpp #15923](https://github.com/ggml-org/llama.cpp/issues/15923)) =
**63.7 ms/token** against an idealized 45.4 ms — a **1.4x derate**. Re-anchored:

| | frame total | RTF | fits 80 ms? |
|---|---|---|---|
| int8, derated | **72.2 ms** | **0.90** | yes, ~8 ms margin |
| int4, derated | **40.3 ms** | 0.50 | yes |

Corroborating: Llama 3.1 8B Q4_K_M 28 tok/s, Qwen2.5 7B Q4_K_M 31 tok/s on Orin
([multimodalflow](https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/)).

### Candidates (D4), with the Orin bandwidth arithmetic

steps/s ceiling = 204.8 GB/s / (params x bytes); the realistic column applies
the **0.83 roofline efficiency measured here**. A Moshi-style frame needs
**12.5 steps/s**. Full table in `candidates.json`.

| model | params | weights license | languages | duplex style | bf16 | int8 | int4 |
|---|---|---|---|---|---|---|---|
| **Moshi** (measured here) | 7.69 B | **CC-BY-4.0** (code MIT) | **English only** (`language: - en`) — **no Korean** | native full-duplex, 17 streams @ 12.5 Hz | 11.1/s **x0.88 FAIL** | 22.1/s x1.77 | 44.2/s x3.54 |
| **Hibiki-1B** | 1.0 B | CC-BY-4.0 | fr->en **translation, not dialogue** | same Moshi arch, 8 RVQ/stream | 85.0/s x6.8 | 170/s x13.6 | 340/s x27.2 |
| **MiniCPM-o 4.5** | 9.0 B | Apache-2.0 | Qwen3-8B backbone; **Korean unverified** | full-duplex by time-division multiplexing | 9.4/s **x0.76 FAIL** | 18.9/s x1.51 | 37.8/s x3.02 |
| **Qwen2.5-Omni-7B** | 7.0 B | Apache-2.0 | multilingual; **Korean unverified** | **turn-based**, not full-duplex | 12.1/s **x0.97 FAIL** | 24.3/s x1.94 | 48.6/s x3.89 |

The bf16 column reproduces the Step-2 conclusion from a completely different
direction (Moshi x0.88 vs the 98.7 ms / 80 ms = 1.23 projection), which is a
useful consistency check.

### The computed statement

**Moshi-7B does not fit the Orin's real-time budget at bf16** — 98.7 ms per
80 ms frame, RTF 1.23, ~23% over. **At int8 it fits but is marginal** (RTF 0.90
on the conservative anchor, ~8 ms of slack in an 80 ms frame). **At int4 it fits
with real headroom** (RTF 0.50). Memory is never the constraint on a 64 GB
board; bandwidth is.

Three caveats, all pushing the wrong way. (1) Moshi's depformer runs **8
sequential sub-steps per frame**, each a small kernel launch; Orin's weaker
launch-latency profile penalizes that pattern more than this desktop's, and the
bandwidth model does not capture it. (2) The literature note records that **no
fetched source reports Moshi, MiniCPM-o, or any native-duplex model running on
Orin at all**, and llama.cpp's Orin audio path had an open bug. (3) D3 below
shows what happens once anything else shares the card. So int8 should be planned
as *unproven and marginal*, not as a fit.

**Smallest open full-duplex alternative.** **Hibiki-1B** — 1 B parameters, same
Moshi multistream architecture at 12.5 Hz, weights CC-BY-4.0, with an MLX-Swift
build tested on an iPhone 16 Pro
([kyutai-labs/hibiki](https://github.com/kyutai-labs/hibiki),
[arXiv:2502.03382](https://arxiv.org/abs/2502.03382)). The honest caveat is that
**Hibiki is a speech-translation model, not a dialogue model** — there is no
small Moshi *dialogue* release. What it proves is that the codec plus
multistream decoder budget fits a phone-class SoC, making a 1-2 B Moshi-style
dog model credible on Orin; it is not a drop-in.

**The Korean problem, which the bandwidth table does not capture.** Moshi's
model card declares **English only**. No source fetched in this experiment
verifies Korean for *any* candidate. If Korean matters to the owner, that is an
open question for every row and a **refuting consideration for Moshi
specifically** — independent of whether it hits 12.5 Hz.

### Training data and GPU-hours (D4's second half)

`training_plan.py` -> `training_plan.json`. **BM-1 has already generated the
episodes** (`behavior-model-1/splits.json`), so this reuses them rather than
inventing a corpus. The audio does not exist yet; it would be TTS-rendered.

| split | episodes | frames @ 10 Hz | hours |
|---|---|---|---|
| train | 3,000 | 3,619,357 | **100.54** |
| dev | 500 | 604,168 | 16.78 |
| frozen_core / family / profile / phrasing | 1,280 | 1,541,724 | 42.83 |
| **TOTAL** | **4,780** | **5,765,249** | **160.15** |

Mean episode 120.6 s; BM-1's act vocabulary is **81 tokens**, corroborating
`DESIGN.md`'s ~90 budget.

**Token budget, one epoch over the train split:** 100.54 h -> 4,524,196 frames
at 12.5 Hz -> **40.7 M tokens** at the stock 9 per frame, **45.2 M** with the
act stream at 10 per frame.

**TTS plan.** Piper 1.2.0 is in-repo (`third_party/piper/piper`,
`models/piper/voice.onnx`). Render dialogue turns -> resample **22,050 -> 24,000
Hz** -> place on the episode timeline as 24 kHz stereo (ch0 = dog, ch1 = owner)
-> resample act labels 10 -> 12.5 Hz hold-last (zero drops, measured above) ->
emit moshi-finetune's `{path, duration}` jsonl. **Blocker: only one Piper voice
is present**, so both speakers would share a timbre, which Moshi's multistream
training does not expect. A second voice (or Kokoro-82M's multi-voice set) is
required before rendering.

**GPU-hours.** The published recipe (`example/moshi_7B.yaml`): LoRA rank 128,
scaling 2.0, `duration_sec` 100, `batch_size` 16, `max_steps` 2000, lr 2e-6,
gradient checkpointing on. Published throughput **12k tokens/s on 1xH100**, so
one epoch = **1.05 H100-hours**.

**The memory answer is the decisive one: it does NOT fit the 24 GB rule.** The
published recipe peaks at **39.6 GB on one H100** — above this **32 GB** card and
above `DESIGN.md`'s **24 GB** single-job rule. `batch_size` must drop from 16
(the README's own OOM advice); the 8xH100 row shows 23.7 GB/GPU at batch 16
sharded, so a single-GPU batch of ~2-4 with gradient checkpointing is the
plausible landing zone, at proportionally lower throughput. Scaled estimate on
this card is reported in `training_plan.json` — labelled an **estimate from a
matmul microbenchmark, not a measured training run**, because moshi-finetune
could not be installed (above).

---

## Files

| file | what it is |
|---|---|
| `run.py` | H-DS1a timing harness (+D1 host snapshots, p99 bar) |
| `gpu_wait.py` | the >= 26 GB GPU gate, logs every poll |
| `param_delta.py` | first-pass parameter delta via `meta`-device builds |
| `act_param_delta.py` | D2 delta both ways from the **actual patched** implementation |
| `act_stream_run.py` | D2 measured act-stream timing through the same loop |
| `profile_breakdown.py` | per-phase split of the frame |
| `edge_extrapolate.py` | H-DS1c bandwidth measurement + Orin projection |
| `candidates.py` | D4 candidate table + Orin bandwidth arithmetic |
| `resample_contract.py` | D2 12.5<->10 Hz contract, dropped tokens counted |
| `training_plan.py` | D4 corpus hours, token budget, GPU-hours, memory verdict |
| `d3_coresident.py` | D3 co-resident budget (AST + GRU) |
| `INTEGRATION_NOTE.md` | H-DS1b design: exact classes, lines, params, training data |
| `results.json`, `param_delta.json`, `act_param_delta.json`, `act_stream_*.json`, `profile_breakdown.json`, `edge_extrapolation.json`, `candidates.json`, `resample_contract.json`, `training_plan.json`, `d3_coresident.json` | raw numbers |
| `README.md` | reproduce commands |

The patched moshi tree is at `~/.cache/parcel-0e/ds1/moshi-act` (diff against
`e6a55d2722a65870ef52a6c9f6ecfc0e90f38362` reproduces the 68/4 line count).
