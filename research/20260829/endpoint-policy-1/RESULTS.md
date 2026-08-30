# Endpoint-policy sensitivity results

## Outcome

**Red: no declared grid point passed, baseline rig parity failed, and no
production setting is nominated.** The experiment is useful as an in-sample
direct-replay sensitivity study only.

Two independent executions each evaluated 30 confidence/silence settings over
13 frozen utterances at four input-frame phases: 1,560 cells per execution.
The retained JSON files are byte-identical, SHA-256
`009f9a8dc3c2bb66ed6c13469f0c172a25ee11bf9d382c489babd85747933616`.
Two additional actual-production-loop parity runs are byte-identical at
`4931513d1d457d0ae526c7c66545c97b45f86239ed6606fc3b8719d91f85518a`:
all 52 default cells match the duplicate runner at the exact 30 ms sample-frame
index (maximum raw floating-clock difference is below 1 ns). The combined
verifier passes all 14 integrity, parity, and negative-result assertions.

## Main sweep

The corrected virtual-rig baseline defects were `incomplete_02`,
`incomplete_04`, `pause_01`, and `pause_03`. Direct replay instead found
`incomplete_04`, `pause_01`, `pause_02`, and `pause_03`; the stronger all-13
validity/reason/count/normalized-clock parity check also failed. Therefore even
an apparently better direct-replay point cannot tune production.

| Direct-replay point | Valid cells | Premature | Incomplete early | Valid-only ep50 | Valid-only ep90 |
|---|---:|---:|---:|---:|---:|
| current policy `.50 / .20 s` | 35/52 | 10 | 7 | 0.256 s | 0.272 s |
| `.80 / .20 s` | 41/52 | 8 | 3 | 0.257 s | 0.965 s |
| closest semantic result `.98 / any tested silence` | 49/52 | 3 | 0 | 2.537 s | 2.577 s |

The latency columns include only semantically valid complete/pause cells. They
are survivor-biased diagnostics whenever the valid count is incomplete and
must not be compared as overall policy quality. No row had all 52 cells valid,
so none reached the latency gate.

## Two-stage diagnostics

| Diagnostic | Valid | Premature | Incomplete early | Ack canceled before commit | Ack committed, then contradicted |
|---|---:|---:|---:|---:|---:|
| unconditional 0.85 s timer | 24/52 | 12 | 16 | 0 | 12 |
| one SmartTurn `.50`, then 0.85 s silence | 35/52 | 10 | 7 | 2 | 10 |
| incomplete-fixture-label diagnostic | 42/52 | 10 | 0 | 2 | 10 |

All three diagnostics triggered 64 hypothetical acknowledgements. Exactly 12
triggers were followed by resumed speech in each diagnostic. The original
metric hid committed acknowledgements by counting later speech as a new turn;
the corrected schema now partitions those 12 into pre-commit cancellations
and committed-then-contradicted outcomes. No provisional audio path was built.

## Reproducibility and limits

Runs used Python 3.14.4, NumPy 2.5.1, `onnxruntime-gpu` 1.29.0 with
`CPUExecutionProvider`, pinned Silero/SmartTurn models, the corpus builder's
windowed-sinc resampler, and production 480-to-512 Silero buffering. Run,
model, corpus, manifest, endpointing, and voice-loop hashes are embedded.

This corpus was already used to discover the defects. It contains synthetic
Piper speech, no ASR transcript, human speaker, room response, AEC, mounted
microphone/speaker, task executive, or robot. It cannot establish generalized
turn taking, safe provisional task admission, or mount readiness.
