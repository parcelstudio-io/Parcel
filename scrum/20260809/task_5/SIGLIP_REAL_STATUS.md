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
