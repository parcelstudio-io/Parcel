# MA-2-P0 execution log amendment

This note was created after the first complete 300-episode execution and before
the retained final execution.

The first independent verification recomputed all 300 episodes and passed, and
the deliberate tamper was correctly rejected. While unwinding the deliberately
failed trace iterator, however, the verifier printed a non-controlling
`GeneratorExit`/`SIGPIPE` cleanup warning from the `zstd` child process. No row,
gate, score, or expected outcome was wrong.

The verifier's decompression helper was changed to drain one bounded episode
file before yielding rows, eliminating that cleanup warning. No experiment,
teacher, simulator, action ledger, transaction, threshold, population, scorer,
or verification predicate changed. Because the verifier source is hashed by the
pre-run manifest, the complete 300-episode execution and verification are being
repeated and only that final source-bound run is retained as evidence.
