# Latency ledger (N19 / acoustic-ack)

Append-only product-path latency snapshots for the CI latency-tail ratchet.

| Artifact | Role |
| --- | --- |
| `ledger.jsonl` | One JSON object per runtime close (or seeded row) |
| `baseline.json` | Pinned p95/p99 ceiling + `window` for the ratchet |

## Writing a row

Opt-in only — ordinary sessions write nothing:

```bash
PARCEL_LATENCY_LEDGER=evals/latency/ledger.jsonl .parcel/bin/python -m parcel_robot ...
# or explicit path via RobotRuntime.write_latency_ledger_row(path=...)
```

`RobotRuntime.close()` appends one row when a ledger path is configured.

## CI

`scripts/ci_gate.py` keeps the committed percentile-pin pytest selection, and
additionally ratchets the latest ledger row against `baseline.json`. While
`len(ledger) < baseline.window`, the ledger ratchet **skips with a note**
(never red). The seed row is clock-honest against the N19 stage vocabulary; it
is **not** a live duplex wall-clock measurement.

## does_not_prove

A green ledger ratchet does not prove sub-700 ms acoustic ack on hardware.
That needs a PipeWire / real-device acoustic loop (nightly / bring-up).
