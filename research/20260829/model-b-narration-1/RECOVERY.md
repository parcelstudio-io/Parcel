# MB-1 hosted-wave recovery and quota record

Status: **PARTIAL_QUOTA**, 2026-08-29. This is an evidence-recovery record,
not a claim that the Q–D experiment completed.

## What failed

The original hosted Q/D process accumulated its `ScenarioResult` objects only
in memory. It completed 119 Q scenarios and then received the provider's typed
daily-request quota error before the 120th session opened. The process exited
without writing its result JSON. Provider usage and transcripts survived in
the wave ledger and the isolated research database
`~/.cache/parcel-0e/mb1/scratch/mb1_full_memory.sqlite3`; no owner-stack data
was involved.

## What was recovered

`recover_interrupted.py` verified and mapped 119 ordered research sessions to
the frozen schedule: Q sample 0 (40), Q sample 1 (40), and Q sample 2 (39).
For every session it required the owner turns to match the scheduled text
exactly and required its session ID to occur in an ordered, contiguous ledger
slice.

The old transcript store did not retain virtual receipt timestamps or latency.
The recovery therefore enumerated every order-preserving assignment of each
observed robot reply to a response slot that the frozen harness could have
created. Fifty sessions had one assignment. Sixty-nine had 2–6 assignments:
38 had 2, 24 had 3, 2 had 4, and 5 had 6. For those rows the checkpoint stores
the deterministic pessimistic assignment and the full hit-count range for
every reported metric. It stores no recovered TTFT/total latency and invents
no missing robot response.

The resume then produced three exact checkpoint rows: the final Q scenario and
the first two D scenarios. A new quota refusal occurred before provider work
for the third D scenario. Its ledger-before and ledger-after snapshots are
byte-identical, and it remains an explicit incomplete entry. No more paid
retries were made.

## Cost and completeness

| measure | value |
|---|---:|
| frozen schedule | 240 scenarios (Q 120, D 120) |
| complete | 122 (Q 120, D 2) |
| missing | 118 D scenarios |
| full-run ledger opening | 356 response rows, $0.87959880 |
| final ledger snapshot | 906 response rows, $2.20803504 |
| full-run increment | 550 response rows, **$1.32843624** |
| whole shared research-wave spend | **$2.20803504** |
| experiment stop / product envelope | $4.50 / $5.00 |

The provider's RPD accounting is not the same unit as ledger response rows, so
550 is reported as ledger rows, not mislabeled as API requests. The experiment
stopped on the provider quota, not the dollar cap.

## Recovery controls now in `run.py`

- lossless raw turns are checkpointed after every completed paid scenario;
- JSON is flushed, fsynced, and atomically replaced;
- the checkpoint fingerprints the exact schedule, config, seed, source
  instruments, arms, samples, and absolute ledger cap;
- every completed or incomplete entry carries its own SHA-256;
- resume refuses a mismatched/tampered checkpoint and skips every completed
  key;
- a scenario that spent calls before failing is never retried implicitly;
  `--hosted-retry-incomplete` is required after ledger inspection;
- a typed provider quota produces `PARTIAL_QUOTA`, a durable incomplete entry,
  teardown, and no retry loop.

`verify_hosted_checkpoint.py` independently re-hashes every entry and ledger
prefix, verifies the completed keys form the exact schedule prefix, validates
the recovery database hash, re-scores all checkpoint turns, and compares the
published summary.

## Stable evidence

- checkpoint: `results/hosted-QD-full.checkpoint.json`, SHA-256
  `76ee277c1499bd071950370321fc809cd532218400452ebe7984cb0689ceb549`
- partial result: `results/hosted-QD-full.json`, SHA-256
  `487b2dd4e7d730b5ce6cfecad12c6a8ead8c9e1d54762fb4f546c6a303fa4d1f`
- verification: `results/hosted-QD-full.verification.json`, status `PASS`
- recovery database SHA-256:
  `e83cab82a5a3cd1b8055f09551bb2b60e9480ea51497085e97b8e116400da954`

The checkpoint is the primary transcript evidence. The partial result is a
derived summary. The incomplete D arm must not be used for a Q-minus-D claim.
