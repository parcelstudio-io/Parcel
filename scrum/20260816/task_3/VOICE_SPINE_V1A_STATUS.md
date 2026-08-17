# Voice Spine V1-A — opening-clause flush, and the M1 blockers found on the way

**Date:** 2026-08-16 · **Card:** V1-A, first unblocked slice of Voice Spine **M1**
**Executor:** Claude Opus (execution lane) · **Baseline:** `8473a51` on `main`
**Design of record:** the 2026-08-15 Parcel Voice Spine design
(artifact `c7240e68-7244-48f0-9332-420a5abe360b`; memory `voice-spine-design`)
**Parallel sprints today:** [task_1](../task_1/README.md) Sol/N24 gateway,
[task_2](../task_2/N27_RELEASE_PARITY_STATUS.md) Opus/N27 release parity. Same
checkout; neither touched here.

## Why this card exists

Yesterday's deliverable was a **design**, not code. Nothing of it had been
started: no card, no `talker`, no sidecar, no Kokoro/Parakeet/Pipecat reference
anywhere in the tree. Yesterday's other repo work (FIX-A) landed complete with no
open handoffs, and the two items opened yesterday (B14 blur-cancels-mission,
B15 self-echo transcripts) are owner-gated 2×2 decisions. So the Voice Spine
build was the only unfinished, executable work in the execution lane.

## Two corrections to the design of record

The design was written from a code survey. Two of its load-bearing claims are
**wrong**, and both were verified against the tree before any code was written.

1. **"The Smart Turn / Silero ONNX models are not bundled, so endpointing
   silently degrades to a fixed 2.5 s timeout."** The models **are** on disk:
   `models/endpointing/silero_vad_v6.onnx` (2.3 MB) and
   `smart_turn_v3.onnx` (8.7 MB), both present since 2026-08-07, and FIX-A's own
   `/api/state` dump already reported `models_present: {vad_model: true,
   turn_model: true}`. The 2.5 s fallback is a **deliberate config choice** —
   `configs/robot.yaml:247` sets `endpointing: energy` with the two model paths
   commented out on lines 248-249. Nothing is missing; the semantic stack is
   switched off.

2. **"Install the models and make endpointing default-on" is a cheap M1 step.**
   It is not cheap, and it is not currently available. `configs/robot.yaml` is
   **hash-locked**: it is a pinned input of `evals/companion/embodied_plan_v1/
   manifest.json` and is covered by `DIGEST_SENTINELS` in `scripts/ci_gate.py`.
   Editing it moves a frozen digest and reddens `frozen-digest-sentinels`. The
   same trap is already recorded in the N13 history ("`configs/robot.yaml` was
   **not** changed for this — the file is a locked input of the frozen
   embodied-plan manifest"). **Flipping endpointing to the semantic stack is an
   owner 2×2 re-freeze, not a config edit.** The design's M1 assumed otherwise.

This reprices M1's single largest latency win (2 500 ms → ~200 ms). It is still
the right move; it is now correctly classified as owner-gated.

## What landed

**V1-A — opening-clause flush.** Time-to-first-audio is set by how long the
*first* chunk takes to synthesize. `SentenceChunkedSynthesizer` chunks on
sentence boundaries up to 220 chars, so a long opening sentence is fully
synthesized before a single sample plays. V1-A flushes only the opening clause.

| File | Change |
| --- | --- |
| `src/parcel_robot/providers.py` | `_split_leading_clause()` + `_CLAUSE_BOUNDARY` + `_MIN_LEADING_CLAUSE_CHARS = 4`; `SentenceChunkedSynthesizer(first_clause_chars=None)`. |
| `src/parcel_robot/runtime.py` | Reads `speech.first_clause_chars` at the existing wrap site (`:1023`). |
| `src/parcel_robot/providers.py` | `first_clause_chars` added to `_ALLOWED_SPEECH_KEYS` (unknown speech keys still fail closed). |
| `tests/test_first_clause_flush.py` | 8 tests, new. |

**Default OFF and byte-identical off.** `first_clause_chars` is unset in every
committed config — deliberately, because setting it in `configs/robot.yaml` would
move the frozen digest described above. With the flag unset the chunk stream is
the same object sequence as before, pinned by
`test_flag_off_is_byte_identical_to_the_sentence_stream`.

**Two design decisions worth naming.** A first chunk that carries `[emote:]` tags
is **never** split: tags are anchored per word, and re-anchoring them across a
split is exactly how a gesture lands on the wrong words (card W8). The latency
win is declined rather than paid for with a mistimed gesture — pinned by
`test_a_first_chunk_carrying_emotes_is_never_split`. And the 4-character floor is
derived, not tuned: it is the shortest split that admits the natural "Okay," /
"Sure," lead-in while refusing a clipped one-or-two-character fragment. It was
found by a **failing test**, not by taste — the first implementation used a
12-character floor, which silently refused to split "Okay, I am heading over…",
i.e. the single most common opening the robot produces.

## Gate table

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  default-suite              5439 passed, 9 skipped, 40 deselected in 231.96s
RESULT: PASS — every hard gate green.   elapsed 244.5s
```

5431 → 5439 passed (+8, this card's tests). Voice-path regression set
(`test_voice_streaming`, `test_runtime`, `test_duplex_integration`,
`test_acoustic_defects`) run together: 103 passed.

## does_not_prove

* **No measured latency improvement.** V1-A shortens the first synthesis call;
  it does not prove a millisecond. The gap it targets is the measured 0.54-0.64 s
  enqueue-to-audible window, and the ledger fan-in that would show it is **N19,
  still open** — until that lands, no sub-700 ms claim may be made from
  `/latency` (N19's own words). The expected win is ~100 ms on a 220-char
  opening sentence at Piper's RTF; that is an estimate, not a measurement.
* **The flag has never run on a live audio path.** This desktop has no
  transducer and PortAudio is not loadable, so every test drives a recording
  double. Whether a 5-character opening chunk sounds natural or clipped through
  a real speaker is **unmeasured**, and it is a perceptual question no unit test
  can close.
* **This is a small fraction of M1.** The design's M1 is a streaming spine:
  WebRTC sidecar, Kokoro TTS, a Qwen3-4B talker on `:8081`, and token-streaming
  from the LLM into the TTS. V1-A touches only the last hop of the last item.
  The dominant serialization — `DuplexVoiceSession` waiting for the **complete**
  LLM reply before any synthesis begins — is untouched.
* **Nothing here changes the robotic voice.** Personality is a prompt/contract
  problem (the grammar-locked JSON `decide()` envelope and the template ack
  table at `runtime.py:1441`), not a chunking problem.

## Handoffs — the real M1 blockers, now priced

1. **OWNER 2×2 — semantic endpointing.** Flipping `speech.endpointing` from
   `energy` to the bundled Silero + Smart Turn stack is the largest single
   latency win available (2 500 ms → ~200 ms) and is blocked only by the
   `configs/robot.yaml` freeze. Needs an authorized re-freeze of
   `evals/companion/embodied_plan_v1/manifest.json` and the `DIGEST_SENTINELS`
   pin. **Recommend raising this as the next owner decision** — it is cheap in
   code and large in effect. Relates to B2's frozen ep50 endpointing eval.
2. **Token-streaming LLM → TTS** is the next unblocked slice, but it is not
   small: it requires retiring the grammar-locked JSON envelope on the
   conversation lane (`providers.py _post_chat_stream` buffers the whole SSE
   stream by construction). Design it as its own card with a flag and a
   flag-off byte-identity proof, the same shape as V1-A.
3. **Sidecar / Kokoro / Qwen3-4B talker** need a pinned Python 3.12 venv, network
   installs, and a ~2.5 GB model download. None was attempted here; attempting
   them blind in a shared checkout is how another session's day gets broken.
4. **N19 first.** Land the latency-ledger fan-in before claiming any voice
   latency number, or V1-A and everything after it stay unmeasurable.
5. **File V1-A's residual in `backlog/UNVERIFIED.md`**: claim = "the opening
   clause reaches the speaker sooner"; reality = "never run on a live audio
   path, and no ledger records first-audible". `backlog/*` is being edited by
   another session right now, so this was **not** written there — hand it over
   rather than racing the file.
