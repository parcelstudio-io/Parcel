# DMC-2 — production transaction and narration-evidence conformance

DMC-2 replaces the invalid truthfulness inference in DMC-1 with retained,
hash-chained traces over Parcel's actual product seams.

## Result

- **Seam conformance: PASS.** Two independent 8,448-case runs produced the
  same normalized trace SHA-256
  `e388cd60e4260919ffd2a6839625709d5cf451700dceebfb543d14c4dd48ebe5`.
- **Architecture composition: NOT EVALUABLE / RED.** Parcel does not yet mint
  an `ActionReceiptV1` from `TaskExecutive.report`, and the receipt cannot bind
  task revision, step, attempt, source epoch, or speech generation.
- **Physical motion: NO-GO.** This suite contains no navigation, physics,
  sensing, audio, gateway, Orin, or Go2 execution.

Read in this order:

1. `DESIGN.md` — frozen hypotheses and evidence boundary.
2. `AMENDMENTS.md` — the independent-review corrections applied before the
   full run.
3. `RESULTS.md` — exact counts and reproduction.
4. `VERDICT.md` — controlling interpretation.
5. `verification.json` — independent oracle result.

The full retained traces are `results-run1.json` and `results-run2.json`.
They intentionally contain no expected labels, oracle verdicts, HMAC tags, or
keys. `verify_results.py` is stdlib-only and does not import the product
reducers it judges.

## Reproduce

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
env PARCEL_MEMORY_PATH=:memory: PARCEL_LATENCY_LEDGER_OFF=1 \
  .parcel/bin/python research/20260829/duplex-transaction-2/run.py \
  --out research/20260829/duplex-transaction-2/results-run1.json
env PARCEL_MEMORY_PATH=:memory: PARCEL_LATENCY_LEDGER_OFF=1 \
  .parcel/bin/python research/20260829/duplex-transaction-2/run.py \
  --out research/20260829/duplex-transaction-2/results-run2.json
.parcel/bin/python research/20260829/duplex-transaction-2/verify_results.py \
  research/20260829/duplex-transaction-2/results-run1.json \
  research/20260829/duplex-transaction-2/results-run2.json \
  --out research/20260829/duplex-transaction-2/verification.json
```

Capability proof:

```bash
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh \
  --label sol-dmc2-trace-oracle \
  /home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python \
  -m pytest -q tests/test_duplex_transaction_v2.py
```

Observed: `2 passed`.
