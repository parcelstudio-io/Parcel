# Card `siglip-real-embeddings` (A1 + A2) — status

**Date:** 2026-08-09 · **Executor:** Sol 5.6 Ultra + Opus (single lane) ·
**Scope:** A1 (real SigLIP-2 text+image embedder, pure module) + A2 (wire the
real text embedding into `grounding._rank_candidates` + `semantic_map._matches`,
delete the cross-class substring accept path). This is the "AI determines WHAT
the object is" upgrade that targets the two cross-class `false_arrival` rows
Wave 2 left open.

## Headline (read this first)

**SigLIP-2 weights are ABSENT on this machine and cannot be fetched (offline).**
No `~/.cache/parcel/siglip2-b16/`, no HuggingFace cache, and the ML stack is not
installed in `.parcel` (`torch` / `transformers` / `open_clip` / `PIL` all
absent; only `numpy 2.5.1`). Per the card's weights-absent clause: the **real
path is implemented and unit-tested against a synthetic embedding fixture**, the
**A2 wiring is landed gated behind "weights present"**, and the **SR /
false_arrival gates are verified on the synthetic fixture with the real-weight
run deferred** to the N-item (weights-present) follow-up. No weights-present run
was faked.

Because every real-path branch is gated behind `matcher.available` (False when
weights are absent) and the `else` branches are byte-for-byte the pre-neural
code, the **weights-absent path is byte-identical to today** — proven below.

## Weights present / absent on this machine

| probe | result |
|---|---|
| `~/.cache/parcel/siglip2-b16/` | **absent** |
| `~/.cache/huggingface/` snapshot | **absent** |
| `.parcel` `torch` / `transformers` / `open_clip` / `PIL` | **absent** (numpy only) |
| `SigLIP2Matcher().available` | **False** (loud degrade to string match) |

Canonical model confirmed from `VSEARCH_SYNTHESIS.json`: `google/siglip2-base-patch16`,
Apache-2.0, ~86M, **768-dim**. The loader resolves it to the light `-224` variant
(`SIGLIP2_MODEL_ID`) or a local weights dir carrying its own `config.json`.

## A1 — `instructnav/siglip.py` (real embedder behind the frozen seam)

- `SigLIP2Matcher` keeps the `EmbeddingMatch` shape (frozen contract). New:
  `embed_text(str) -> tuple | None` and `embed_image(crop) -> tuple | None`,
  both L2-normalized; `match()` does real neural cosine + threshold when a real
  embedder loaded, else the **loud string fallback (byte-identical to the stub)**.
- `available` now means *a real embedder actually loaded* (or was injected),
  never merely "a file exists" — so the A2 gates key on a **usable** model. A
  present-but-unloadable weights dir degrades loudly, exactly like absent.
- Real load is `transformers`-backed, import-light (heavy imports live inside the
  embedder constructor; any ImportError/load failure degrades, never crashes
  grounding). The old `_hash_embed` "available" branch (meaningless cosine) is
  **deleted**.
- **Threshold recalibration.** The `0.24` gate was tuned for the char-hash stub
  (cosines clustered near zero). The real path gates on
  `SIGLIP2_MATCH_THRESHOLD` (module constant), and `calibrate_threshold(embedder,
  present_pairs, absent_pairs)` is the harness that sweeps the gate and returns
  the Youden-J operating point plus the full FAR/TAR curve — the one command the
  real-weight recalibration runs.

## A2 — wiring (existing files, gated behind weights-present)

- `grounding._rank_candidates`: **deleted the cross-class substring rescue**
  (`_norm_token(label) in _norm_token(query)`) — but only on the
  weights-present branch; weights-absent keeps the exact string rescue verbatim.
  The `_hash_embed(query)` embedding cosine (~line 204) is **replaced by the real
  `matcher.embed_text(query)`** when weights are present, `_hash_embed` when
  absent. `GrounderV2.match_threshold` now feeds an auto-built matcher's
  `real_threshold` (inert on the fallback path).
- `semantic_map._matches`: when weights are present, identity is decided by
  neural cosine over the candidate's **label-local** texts — **no substring
  containment** (the path that let `"tree"` match a lamppost via its
  `"streetlight"` alias, `"tree" ⊂ "street"`). Weights-absent keeps the exact
  alias + substring + string-fallback order, byte-identical. The curated
  exact-alias acceptance (a real synonym like `streetlight`≡`lamppost`) is kept
  on **both** paths.

The two Wave-2 `false_arrival`s both trace to substring containment where
`"tree" ⊂ "streetlight"`: `object_goal-B-05` ("walk towards the **streetlight**"
→ committed a **tree**) and `object_goal-D-15` ("walk towards the **tree**" →
committed a **lamppost** via its `streetlight` alias). Both are killed by the
real embedding on the weights-present path; both persist byte-identically when
weights are absent (which is why the gate is honestly deferred).

## Calibrated threshold + FAR/TAR (synthetic fixture; real-weight DEFERRED)

`calibrate_threshold` on the synthetic fixture (semantic-clustering embedder):

| quantity | value |
|---|---|
| present (synonym) cosine [min, max] | **[0.9943, 0.9998]** |
| absent (cross-class) cosine [min, max] | **[0.0000, 0.0113]** |
| Youden-J threshold | **0.02** (J = 1.0) |
| TAR / FAR at gates 0.10 / 0.24 / 0.30 / 0.50 / 0.70 | **1.00 / 0.00** at all |
| module default `SIGLIP2_MATCH_THRESHOLD` | **0.30** (sits inside the separating band) |

The synthetic separation is deliberately clean, so this proves the **machinery**
(the calibrator picks a separating gate and the FAR/TAR curve is emitted), not a
real operating point. **The real-weight FAR/TAR curve and the recalibrated `0.24
→ ?` value are DEFERRED to the weights-present run.** `0.30` is a documented
provisional default, flagged as such in `siglip.py`.

## Gate status

| gate | with weights ABSENT (this machine) | verified-on-fixture | real-weight |
|---|---|---|---|
| (1) Tier D synonym/ambiguity SR up | **byte-identical: 1/5 = 0.20 before & after** | streetlight→lamppost grounds; streetlight→tree refused (matcher+grounder+`_matches` tests) | **deferred** |
| (2) 2 cross-class false_arrivals → 0 | **byte-identical: 2 before & after** (B-05, D-15) | both rejected by the real path on the fixture | **deferred** |
| (3) weights-absent path byte-identical | **PROVEN** (below) | — | n/a |
| (4) new synonym test w/o alias row | `streetlamp`→lamppost etc. on the fixture; real-weight cells `skipif(not weights)` | ✔ | **deferred (skipped honestly)** |

Tier D SR and false_arrival are unchanged **by construction** on this machine —
the fix lives entirely on the weights-present branch, which cannot run here.

## Byte-identical fallback proof (gate 3)

1. **Same-budget A/B run.** Candidate v3 minival, `--budget-policy` default
   (fixed): my changes vs the HEAD stub (my 3 files `git checkout HEAD`'d),
   diffed per episode **including full traces** →
   **0 / 25 per-episode mismatches**; `episode_digest` `919a0fea…` identical;
   every aggregate metric identical (sr 0.20, spl 0.16016…, false_arrival 2,
   authority_histogram and failure_histogram equal). (Diagnostic ledger rows the
   two runs auto-appended were removed; the ledger's HEAD prefix sha256 is
   byte-identical and the diff is append-only.)
2. **Matcher-level oracle.** `test_weights_absent_match_is_byte_identical_to_pre_neural_stub`
   (10 parametrized cases) pins `SigLIP2Matcher.match` (weights absent) equal to
   a re-implemented pre-neural stub `match`.
3. **Frozen pins.** 82 passing across `test_nav_instruct_episodes_v2` (a17c04db…),
   `_episodes_v3` (919a0fea…), `_rescoring`, `_scene_truth`, `test_instructnav_scoring`,
   and `test_embodied_plan_eval::test_full_gate` (the immutable **997** row).
4. **Retired-literal ratchet** green (22 passed) — `semantic_map.py` is scanned;
   no retired-family literal (0.32/0.35/1.2/1.25/1.32) was introduced.

## Suite + lint

- Full default suite `pytest -m 'not slow'`: **3007 passed, 3 failed, 5 skipped,
  33 deselected**. The 3 failures are all `tests/test_conversation_quality_v1.py`
  (another lane's `manifest.json` churn, shown modified in `git status`); they
  **reference none of my files** and **fail identically with my 3 files reverted
  to HEAD** — pre-existing, outside this card. The 5 skips include the 3
  real-weight `skipif(not weights)` synonym cells.
- Ruff clean on all touched files.

## Files touched (mine only)

- `src/parcel_robot/instructnav/siglip.py` — A1, rewritten (real embedder,
  `embed_text`/`embed_image`, real-cosine `match`, `calibrate_threshold`,
  loud degrade; `EmbeddingMatch` shape frozen).
- `src/parcel_robot/instructnav/grounding.py` — A2 (substring rescue + hash cosine
  gated behind `matcher.available`; `match_threshold` → matcher `real_threshold`).
- `src/parcel_robot/navigation/semantic_map.py` — A2 (`_matches` substring path
  gated behind weights-absent; neural cosine when present).
- `tests/test_siglip_real_embeddings.py` — new (fallback-equals-today, real-path
  FP rejection, synonym-without-alias, calibration, deferred real-weight cells).
- `scrum/20260809/task_5/SIGLIP_REAL_STATUS.md`, `backlog/UNVERIFIED.md` (U25).

## Deferred to the weights-present (N-item) run

- Fetch/place Apache-2.0 `google/siglip2-base-patch16` under
  `~/.cache/parcel/siglip2-b16/` + install `torch`/`transformers`/`Pillow` in
  `.parcel`.
- Recalibrate `SIGLIP2_MATCH_THRESHOLD` on known-absent trials; record the real
  FAR/TAR curve (replaces the provisional 0.30).
- Re-run the candidate minival WITH weights: confirm Tier D synonym/ambiguity SR
  up vs the frozen baseline and the 2 cross-class `false_arrival`s → 0 via the
  differential-authority instrument, **without weakening any verification**.
- Validate `embed_image` against real crops (needs PIL + weights; B2 consumer).

---

## ONNX real-weight run (2026-08-09 · Sol 5.6 Ultra + Opus)

Follow-up to the deferral above. The prior run deferred because it targeted
`torch`/`transformers` (absent). This machine has **onnxruntime** (+ numpy,
mujoco) — the same no-torch/no-sudo stack the audio lane runs Silero/smart-turn
on — so the real path is now built on **ONNX Runtime**, weights fetched and
landed HERE. No run was faked.

### What was fetched (Apache-2.0 export `onnx-community/siglip2-base-patch16-224-ONNX`)

`scripts/fetch_siglip2.sh` (no-sudo, curl/wget fallback, `.part` staging,
sha256-gated, idempotent — mirrors `install_speech_services.sh`) landed into
`~/.cache/parcel/siglip2-b16`:

| file | bytes | sha256 |
|---|---|---|
| `text_model_int8.onnx`     | 283,438,275 | `3a0603d3a00c05a80a6ded4743c16aaac7b1e62cdcc7e362e7ce418659b96400` |
| `vision_model_int8.onnx`   |  94,553,333 | `0dd31785a2713f1113ef2272472165c69d580473dae38d7b47568ac587795e70` |
| `tokenizer.json`           |  34,363,039 | `cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322` |
| `tokenizer.model`          |   4,241,003 | `61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2` |
| `config.json`              |         435 | `e43a9f7692d3819886a82cb2097048258d444f123c67d37ec825f9345b019cf2` |
| `preprocessor_config.json` |         394 | `9b36b57ebaf20f09bf4c22100ccc21877ea6bfe5aead0c00c59f8af8ccefacfc` |
| `tokenizer_config.json`    |      47,240 | `7c3a247599e741bceba1a3fe0285aea88d1044dc1fad2caa1e48cdd9fd25f630` |
| `special_tokens_map.json`  |         636 | `baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351` |

**Variant = int8 (per-channel symmetric QDQ), separate text/vision encoders.**
onnxruntime here is **CPU-only** (providers: CPU + Azure, no CUDA), and VRAM is
claimed by Gemma (llama.cpp ~15 GB) + Fish, so the choice is CPU/RAM-driven:
fp32 text is 1.1 GB (accuracy ref, heavy); fp16 is a poor CPU pick (x86 lacks
native fp16 matmul → ORT up-casts to fp32, no speedup); **int8 runs on ORT's
native int8 CPU kernels** at 283 MB text / 94 MB vision. Grounding's hot path
needs only the **text** encoder; vision is the deferred B2 crop consumer, loaded
lazily.

### Pip wheels installed into `.parcel` (no torch, no transformers, no PIL)

`tokenizers 0.21.4` (rust wheel) + its deps (`huggingface_hub 0.36.2`,
`hf-xet 1.6.0`, `requests`, `tqdm`, `filelock`, `charset_normalizer`, `idna`,
`urllib3`, `certifi`). SigLIP's GemmaTokenizer loads straight from
`tokenizer.json`; **PIL was NOT needed** — image preprocess is pure numpy.

### Loader (`instructnav/siglip2_onnx.py`, behind the frozen `SigLIP2Matcher` seam)

- **Text**: lowercase (tokenizer.json's normalizer does NOT lowercase, but
  `do_lower_case=True`) → GemmaTokenizer → right-pad/truncate to **64** tokens
  (SigLIP has no attention-mask input; pad is attended and pooling reads the last
  position, so the fixed length is load-bearing) → `input_ids` int64 →
  `pooler_output[768]` → L2-normalize. Memoized (label vocab is tiny).
- **Image**: numpy resize-224 (bilinear, half-pixel centered) + rescale 1/255 +
  `(x-0.5)/0.5` from `preprocessor_config.json` → NCHW → `pooler_output[768]` →
  L2-normalize. No torch, no PIL.
- **Opt-in switch `PARCEL_SIGLIP2_ONNX`**: default OFF ⇒ byte-identical string
  fallback even with weights present, so merely landing the model never flips the
  suite/mission onto the neural model. `available` semantics unchanged (True only
  when a real embedder actually loaded). `_load_neural_embedder` now delegates to
  the ONNX loader; the transformers `_SigLIP2NeuralEmbedder` is deleted.

### Real calibration (scene vocabulary `city_semantics.CLASS_ALIASES`, int8)

SigLIP is an image-**text** model, so text↔text cosines cluster **HIGH and
overlapping**, NOT near zero — the old `0.30` provisional would accept
everything.

| quantity | value |
|---|---|
| present (within-class synonym) cosine, n=40 | **[0.844, 0.991]**, mean 0.923 |
| absent (cross-class) cosine, n=311 | **[0.759, 0.927]**, mean 0.843 |
| Youden-J | **0.870** — REJECTED: it sits *below* tree/lamppost 0.872, so D-15 survives |
| chosen `SIGLIP2_MATCH_THRESHOLD` | **0.90** (env-overridable via `PARCEL_SIGLIP2_THRESHOLD`) |

Real FAR/TAR curve (`calibrate_threshold`):

| gate | TAR | FAR |
|---|---|---|
| 0.30 | 1.000 | 1.000 |
| 0.85 | 0.950 | 0.386 |
| 0.87 | 0.900 | 0.135 |
| 0.88 | 0.825 | 0.074 |
| 0.89 | 0.750 | 0.023 |
| **0.90** | **0.700** | **0.013** |
| 0.91 | 0.625 | 0.006 |
| 0.93 | 0.525 | 0.000 |
| 0.95 | 0.300 | 0.000 |

**0.90 sits above** the two false_arrival pairs (streetlight/tree **0.869**,
tree/lamppost **0.872** → both refused) **and below** the real synonym
streetlight/lamppost **0.962** → kept. The raw TAR 0.70 is not alarming: the
rejected pairs are weak generic aliases (seat≡bench 0.873, pavement≡safe region
0.847) that the **curated alias table catches upstream** in
`semantic_map._matches` before the neural gate is consulted. The neural gate's
job here is cross-class *rejection*.

### Deferred gate — RAN with weights (candidate v3 minival, real ONNX, thr 0.90)

Env-off vs env-on, same episode set (`episode_digest 919a0fea…`), ledger
restored byte-identically after both runs (sha `39be79b3…` unchanged):

| metric | OFF (string fallback = frozen) | ON (real int8 ONNX) |
|---|---|---|
| **false_arrival** | **2** | **0** |
| SR | 0.20 | **0.28** |
| SPL | 0.16016 | 0.24016 |
| authority_histogram | agree 17 / disagree 6 / false_arrival 2 | agree **20** / disagree **5** / false_arrival **0** |
| Tier-D SR | 1/5 = 0.20 | 1/5 = **0.20** (flat) |

Per-episode (only 3 rows moved, all improvements or neutral, **no regressions,
no new false_arrivals**):

- `nav-object_goal-B-05` (streetlight→tree): false_arrival→**none**, **now
  SUCCEEDS**, authority false_arrival→**agreement**.
- `nav-object_goal-D-15` (tree→lamppost): false_arrival→**planning_error** (still
  not success), authority false_arrival→**agreement**. The wrong-object
  commitment is **killed**; reaching success needs a separate *planning* fix, not
  grounding — so Tier-D headline SR stays flat while the false_arrival goes to 0.
- `nav-region_goal-B-05`: termination→none, **now SUCCEEDS**, authority
  disagreement→agreement (bonus).

**The differential-authority instrument confirms verification was NOT weakened**:
agreement UP (17→20), authority_disagreement DOWN (6→5), false_arrival→0. The two
cross-class false_arrivals are eliminated by real neural cosine, not by loosening
any predicate.

### ms/query + placement decision (HONEST BOUNDARY)

- onnxruntime **CPU-only** here (no CUDAExecutionProvider) — the RTX 5000 is not
  reached by ORT in `.parcel`; GPU export is optional future work.
- `embed_text` warm: **~28.85 ms/query** (single 64-token encode). Label
  embeddings are **memoized**, so a warm `match()` over a cached label set is
  **~0.17 ms**; a new query with cached labels is **~28 ms**. Cold `match()` over
  5 fresh labels is ~175 ms (6 encodes).
- Whole 25-episode minival: **~25 s (string) → ~990 s (real ONNX)** — a ~40×
  slowdown. **PLACEMENT: grounding stays OFF the 10 Hz (100 ms) hot path** — it
  is a discrete grounding decision (async, at command-interpretation time), never
  per-tick. Not silently made in-loop; the number is the finding.

### Suite + lint + byte-identical

- Full default suite (env OFF) `pytest -m 'not slow'`: **3020 passed, 3 failed,
  7 skipped, 33 deselected** in 94 s. The 3 failures are all
  `tests/test_conversation_quality_v1.py` (another lane's `manifest.json` churn) —
  they **reference none of my files** and fail on
  `evals/companion/conversation_quality_v1/manifest.json`, unrelated to grounding.
  The 7 skips include the 5 real-weight `skipif(not enabled)` siglip cells.
- Env-ON `tests/test_siglip_real_embeddings.py`: **28 passed** (real-weight cells
  run: strong synonyms ground, both false_arrival pairs refused, 768-d unit-norm).
- **Weights-absent / opt-out byte-identical**: env-off candidate-v3 minival
  reproduces the frozen baseline exactly (sr 0.20, spl 0.16016, false_arrival 2,
  authority histogram); frozen v2/v3 digests + 997 embodied row green (102 passed
  across the frozen/grounding-touching modules); ruff clean on all touched files.

### Files touched (mine only)

- `scripts/fetch_siglip2.sh` — **new**: sha-pinned no-sudo fetch of the int8 ONNX
  encoders + tokenizer/preprocessor into `~/.cache/parcel/siglip2-b16`.
- `src/parcel_robot/instructnav/siglip2_onnx.py` — **new**: onnxruntime backend
  (tokenizers text path, numpy image path, memoized, opt-in env switch).
- `src/parcel_robot/instructnav/siglip.py` — swapped `_load_neural_embedder` to
  the ONNX loader, deleted the transformers embedder, real-calibrated
  `SIGLIP2_MATCH_THRESHOLD = 0.90` (env-overridable), env-gated + quieted the
  degrade warning.
- `tests/test_siglip_real_embeddings.py` — real-weight cells rewritten to the
  0.90 operating point (strong synonyms + both false_arrival rejections +
  768-d unit-norm) and an opt-in-gate test.
- `backlog/UNVERIFIED.md` (U25 → closed-with-evidence), this file.

### Deferred sub-piece (specific blocker)

- **`embed_image` end-to-end on real rendered crops (B2 consumer).** The vision
  encoder loads and returns a shape-correct, unit-norm 768-d vector, and the
  numpy preprocess matches the SigLIP config, but it is **not yet validated
  against real camera/sim crops in the grounding loop** — that needs the B2 crop
  producer wired in (the detection→crop path), which is out of this card's file
  scope. Text grounding (the false_arrival fix) is fully real and gated.
