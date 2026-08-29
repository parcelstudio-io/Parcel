# INTEGRATION_NOTE — adding a Parcel act stream to Moshi (H-DS1b)

**Source read:** `github.com/kyutai-labs/moshi` @ `e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`
(2026-05-16), python package `moshi` **0.2.13**. All line numbers below are that
revision's `moshi/moshi/models/lm.py` unless another file is named.
Checkpoint config: `moshi/moshi/models/loaders.py::_lm_kwargs` (lines 88-113),
which is what `kyutai/moshiko-pytorch-bf16` loads.

Parcel side: `src/parcel_robot/duplex/act_codec.py::ActTokenCodec` (the act
vocabulary) and `src/parcel_robot/duplex/frames.py::FrameInterleaver`
(`frame_hz: float = 10.0`).

---

## 1. What the architecture actually is

Moshi is **not** an audio model with a text head bolted on. `LMModel` is a
`K`-parallel-stream token model where every stream is symmetric machinery:
one input embedding, and (for generated streams) one output head. The temporal
transformer sees **one summed vector per frame**, not a sequence of K tokens.

Concretely, at the moshiko config (`_lm_kwargs`, loaders.py:88-113):

| | value | meaning |
|---|---|---|
| `dim` | 4096 | temporal transformer width |
| `num_layers` / `num_heads` | 32 / 32 | temporal transformer (the 7B part) |
| `n_q` | 16 | audio streams **in** (8 = Moshi's own voice, 8 = the user's) |
| `dep_q` | 8 | audio streams **generated** by the depformer (Moshi's own voice) |
| `card` | 2048 | audio codebook cardinality (Mimi RVQ bins) |
| `text_card` | 32000 | text ("inner monologue") vocabulary |
| `depformer_dim` / `_num_layers` | 1024 / 6 | depth transformer |
| `depformer_multi_linear` | `True` | one `dim -> depformer_dim` projection per step |
| `depformer_weights_per_step` | `True` | **each depformer step has its own attention + FFN weights** |
| `delays` | `[0,0,1,1,1,1,1,1,1,0,1,1,1,1,1,1,1]` | 17 entries = `num_codebooks` |

`num_codebooks = n_q + 1 = 17` (lines 290-291): stream 0 is text, streams 1..16
are audio. `audio_offset = 1` (lines 298-304) — and its docstring says out loud
*"in practice, but in the future we might want to support >1"*, i.e. the authors
anticipated exactly this kind of extra non-audio stream.

The per-frame flow:

1. **`forward_text` (lines 379-408).** Sums the 16 audio embeddings
   (`self.emb[cb]`, line 391) and the text embedding (`self.text_emb`, line 395)
   into one `[B, S, 4096]` vector, runs the 32-layer temporal transformer
   (line 402), and emits `text_logits` from `self.text_linear` (line 406).
   **The temporal transformer never sees stream identity** — adding a stream is
   one more addend at line 394/397.
2. **`depformer_step` (lines 809-850).** Given the sampled text token and
   `transformer_out`, it loops `cb_index` in `range(dep_q)` **sequentially**,
   sampling audio codebook `cb_index` conditioned on the previous one
   (`forward_depformer`, lines 450-493).
3. **`_step` (lines 669-783)** manages the delay cache, injects the user's
   audio codes (lines 693-696) and writes the sampled tokens back (lines 762-772).

So an act stream is genuinely "one more codebook". The only real question is
**where in the depformer order it goes**, and that question is where the cost is.

---

## 2. The trap: `depformer_weights_per_step=True`

The naive change — `dep_q: 8 -> 9` — is **not** cheap, and this is the one
non-obvious finding of this note.

`modules/transformer.py:398-403` sets `mult = weights_per_step`, and lines
406-418 then build `mult` separate `in_projs` **and** `out_projs` per attention
layer; lines 684-715 build `mult` separate gating (FFN) modules per layer.
`LMModel.__init__` line 173 passes `kwargs_dep["weights_per_step"] = dep_q`.
So the depth transformer is really **8 disjoint 6-layer transformers** sharing
nothing, and `depformer_in` (line 179-181) is 8 separate `4096 -> 1024` matrices.

Raising `dep_q` to 9 therefore clones a whole extra depformer weight slot —
tens of millions of parameters, not a rounding error (exact figure in
`param_delta.json`, variant `V1_dedicated_depformer_step`).

**The escape hatch is already in the code.** `depformer_weights_per_step_schedule`
(documented at lm.py:69-70, asserted at line 127, consumed at lines 176-178,
428-429 and 472-474) is a `CODEBOOK_INDEX -> WEIGHT_INDEX` map that lets steps
*share* weights, and it sets `num_in = max(schedule) + 1`. With
`dep_q=9, schedule=[0,0,1,2,3,4,5,6,7]` the act step reuses audio step 0's
weights: `mult` stays 8, `depformer_in` stays 8 matrices, and **the entire
depth transformer is unchanged**. That is the recommended variant.

---

## 3. What was actually built and measured

This note was drafted from the source during the weight download; the sections
below have since been **replaced by the implementation**. A working patch lives
at `~/.cache/parcel-0e/ds1/moshi-act` and the measured numbers are in
`RESULTS.md` / `act_param_delta.json`. What follows is the reconciled account.

### The variants

| | where the act token is produced | depformer weights | delta @ 90 tokens |
|---|---|---|---|
| **per-step slice** | its own depformer weight slot (`dep_q=9`, no schedule) | +1 full 6-layer slot | 83.8 M (act last) |
| **shared slice** | reuses an existing slot via `depformer_weights_per_step_schedule` | unchanged | **2.56 M** (act last) / **0.56 M** (act first) |
| extra head | parallel head off `transformer_out` (`extra_heads`) | unchanged | 0.74 M — but conditionally independent of the frame's audio |

The `weights_per_step` trap is real: moshiko sets
`depformer_weights_per_step = True` (`loaders.py:110`), so
`modules/transformer.py:398-418` and `:684-715` give **every depformer step its
own attention and FFN weights**. The depth transformer is 8 disjoint 6-layer
transformers, and a 9th step clones a whole set. The schedule
(`lm.py:69-70, 127, 176-178, 428-429, 472-474`) is the escape hatch, and it is
worth a factor of ~33.

### Stream order is the other factor of 4.6

`depformer_emb` holds `dep_q - 1` tables because *"the last codebook is never an
input to Depformer"* (`lm.py:188-191`); table `i` embeds the token sampled at
step `i`.

- **act LAST** (the ordering `AMENDMENTS.md` D2 fixes): a 9th step makes audio
  codebook 7 an input for the first time, so a new **2049-row** table is needed
  (2,098,176 params). Total **2,563,072** — over the 1 M bar.
- **act FIRST**: the only new table is the **91-row** act embedding (93,184).
  Total **558,080** — under the bar.

Act-first is also semantically better: the depformer generates sequentially
within a frame, so act-first makes the frame's audio conditioned on the act the
dog just chose, rather than a comment on audio already chosen. Act-last is what
was implemented and measured, as directed.

## 4. The measured code delta

`git diff --numstat` against `e6a55d2722a65870ef52a6c9f6ecfc0e90f38362`:

| file | added | removed |
|---|---|---|
| `moshi/moshi/models/lm.py` | 22 | 3 |
| `moshi/moshi/models/loaders.py` | 46 | 1 |
| **total** | **68** | **4** |

**Seven edit sites, 72 lines.** In `lm.py` (five): constructor args
(`act_card`, `act_index`); `self.emb` (`:135-137`); `self.depformer_emb`
(`:189-191`); `self.linears` (`:230-232`); `_get_initial_token` (`:306-320`),
plus the `_card_at` helper. In `loaders.py` (two): `_remap_for_act_stream` and
`_materialize_act_modules` with their call site.

The shape of the patch is the interesting part. Rather than adding parallel
modules, it makes the existing `nn.ModuleList`s **heterogeneous** — stream `i`
gets cardinality `act_card` instead of `card` when `i == act_index`. Two
consequences:

- **`forward_text`, `forward_depformer`, the depformer and the streaming loop
  needed ZERO edits.** `forward_text` (`:379-408`) sums all stream embeddings
  into one vector before the 32-layer stack and iterates
  `range(self.num_audio_codebooks)`, so it picks the act stream up
  automatically. The pre-registered claim *"no change to the temporal
  transformer"* holds more strongly than it was stated.
- **Every stock checkpoint key still matches**, so
  `load_state_dict(strict=False)` reports only the act modules as missing and
  `assert not unexpected` proves no pretrained tensor was orphaned.

**The one non-obvious cost:** inserting the act stream at `act_index` pushes the
user's audio codebooks from `emb[8..15]` to `emb[9..16]`. Without
`_remap_for_act_stream` the pretrained embeddings load into the **wrong
streams** — silently, with no error. That is 20 of the 47 loader lines and the
single easiest thing to get wrong in this integration.

`LMGen._step` needed no change: `needed_tokens = num_codebooks - dep_q - 1`
(`:683`) is 18 − 9 − 1 = 8, the same as stock's 17 − 8 − 1 = 8, so the
**user-stream contract is untouched** — which is the point.

**Config** (`loaders.py::_lm_kwargs`): `n_q: 16 -> 17`, `dep_q: 8 -> 9`,
`act_card: 90`, `act_index: 8`,
`depformer_weights_per_step_schedule: [0,1,2,3,4,5,6,7,7]`, and `delays` gains
one `0` entry at position 9 (17 -> 18) so the act token is emitted with no delay
relative to the frame it describes.

**Functional check:** with randomly initialised act modules the loop ran and
emitted act tokens spanning [0, 89] with 63 distinct values — in range, wired
end to end. The tokens are noise by construction; this proves cost and wiring,
never behaviour.

## 5. Training data: what the corpus must look like

`moshi-finetune` (the published LoRA recipe) takes **stereo WAV** — channel 0 =
the model's voice, channel 1 = the user — plus a timestamped word-level JSON for
the inner-monologue text stream. An act stream extends this to a **third
aligned track**, and the alignment is the whole difficulty.

**Required form:** for every 80 ms frame `t`, a triple
`(user_audio[t], moshi_audio[t], text[t], act[t])` where `act[t]` is one
`ActTokenCodec` token id. `<idle>` is the act analogue of the text stream's
padding token (`existing_text_padding_id = 3`) — most frames are `<idle>`, and
that is fine; the text stream is mostly padding too.

**The rate mismatch is the actual work.** Moshi's frame is Mimi's:
`FRAME_RATE = 12.5` (loaders.py:29), i.e. **80 ms**. Parcel's duplex clock is
`frame_hz: float = 10.0` (`duplex/config.py:22`, `duplex/frames.py:24`), i.e.
**100 ms**. The ratio is 5:4 — every 4 Moshi frames span 5 Parcel frames — so
there is **no common frame and no integer resampling**. Options:

1. **Re-clock Parcel to 12.5 Hz.** `FrameInterleaver` takes `frame_hz` as a
   constructor argument and derives `_period_s = 1.0 / hz` (frames.py:24-29), so
   this is a config change, not a rewrite. This is the clean answer and it is
   *cheap*: the act stream then shares the model's clock exactly, and the
   control loop gets 20 ms *faster*, not slower. Cost: every downstream cadence
   assumption tied to 100 ms (watchdogs, TTL) must be re-checked.
2. **Nearest-neighbour hold on the 12.5 Hz grid.** Keep Parcel at 10 Hz for
   training-data generation and label each Moshi frame with the Parcel act in
   force at that frame's *start*: `act_moshi[t] = act_parcel[floor(t * 10/12.5)]
   = act_parcel[floor(t * 0.8)]`. Because acts are **states held until replaced**
   — `push_act` is documented "Acts are states for the current frame window —
   last write wins" (frames.py:52-55) — a hold is semantically correct, not an
   approximation of a spike train. The artifact is that each Parcel act is
   repeated 1 or 2 Moshi frames in a 4/5 alternating pattern, adding up to
   80 ms of quantization jitter to onset timing. For "chuckle at the joke" or
   "look back when lost", 80 ms is below the perceptual threshold; for a
   reactive stop it is not, but reactive stops must never come from the model
   anyway (they come from the safety core).
3. Resampling *audio* to a 10 Hz codec frame is **not** an option — 12.5 Hz is
   baked into Mimi's SEANet strides (`ratios: [8, 6, 5, 4]` -> 24000/960,
   loaders.py:37-55) and changing it invalidates the pretrained codec.

**Recommendation: option 1 for the product, option 2 for the first corpus**
(it lets act logs already recorded at 10 Hz be reused without regenerating
anything).

**Volume.** The literature note's numbers set the scale: `moshi-finetune` LoRA
r=128 at ~39.6 GB peak on one H100; OmniFlatten trained duplex behaviour into a
0.5B model from 2,000 h of synthesized duplex audio; DuplexSLA's action channel
took 500k h CPT + 50k h post-training. Parcel has none of that, so the realistic
path is **LoRA on the temporal transformer + full training of only the new act
modules** (~0.56 M new parameters, which can be trained from scratch cheaply)
on a small corpus of teleoperated or scripted dog sessions. The new act
embedding/head being tiny is the good news here: it is the backbone that would
need data, and the backbone is frozen.

**What is NOT solved by this note.** Nothing about whether Moshi's frozen
English-centric backbone *transfers* to dog-shaped conversation, whether the act
head learns anything useful from a small corpus, or what a wrong act token costs
at the safety boundary. Those are separate experiments.
