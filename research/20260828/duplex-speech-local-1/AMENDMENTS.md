# DS-1 amendments — POST-START (written 2026-08-28 17:57 from an independent design review). The pre-registered bars stand and are reported; these add measured rows and fix under-specified choices BEFORE the timing row is read.

## D1 — H-DS1a on the tail, with enough samples
Amended bar: step-time p99 ≤ 80 ms (report p50 and the fraction of steps
> 80 ms too); ≥ 2,000 measured steps (≥ 170 s of audio); the decode branch
runs on every step; the row records GPU utilisation, co-resident processes,
and 1-min load at start and end. The verifier re-runs it in isolation.

## D2 — H-DS1b becomes measurable
- Attach randomly initialised act-stream modules to the stock model for each
  variant you identify (e.g. shared depformer slice vs an extra per-step
  slice vs an extra head) and run the SAME streaming loop; amended bar:
  step-time p99 delta ≤ 5 ms with RTF still ≤ 1.0.
- Report the parameter delta BOTH ways (shared slice vs per-step slice) with
  the exact config flag and the depformer stream order (act stream last).
- "Code sites" = diff line count against the pinned moshi revision (record
  the rev), not a self-count.
- Resampling contract: Moshi 12.5 Hz vs the product's 10 Hz DuplexFrame
  clock — state the rule (DuplexConfig.frame_hz = 12.5, or an
  event-priority merge that never drops a non-idle token) and COUNT dropped
  non-idle tokens under hold-last on a synthetic act stream.
- State that the act stream terminates only in `DuplexFrameConsumer`
  (shadow-only today) behind the deterministic filter; no `push_twist` from
  the model.
- One-batch `moshi-finetune` dry run with the extra stream if the package
  installs; else record why.

## D3 — co-resident budget (additive)
Report step time with a laughter detector (AST, ~87 M params) resident and a
2×256 GRU ticking at 10 Hz on the same GPU, and the RTF at which the whole
stack fits in 80 ms. If the GPU never frees enough, mark UNMEASURED with the
free-memory log.

## D4 — H-DS1c as a decision input, and the training-data half
- Candidates: list ≥ 2 open alternatives with license, languages (Korean?),
  parameter count, duplex style, and the Orin bandwidth arithmetic
  (weights × bytes / memory bandwidth → tokens/s ceiling); int8 row if the
  package exposes it.
- Training data: compute what aligned (audio, text, act) data would look
  like — TTS-render BM-1's dialogue scripts (Piper voice in the repo or
  Kokoro-82M) into two-speaker 24 kHz audio with act labels resampled
  10 → 12.5 Hz (hold-last); state hours of audio = episodes × length;
  estimate LoRA fine-tune GPU-hours on the 32 GB Ada from Kyutai's published
  moshi-finetune recipe (verify version and its memory floor); state whether
  it fits under the 24 GB single-job rule.

## D5 — tier label
This is a desktop GPU benchmark, not one of research/README.md's tiers;
label rows `desktop-local-model` and note the label is proposed, not
registered.
