# Latency ledger (N19 / acoustic-ack)

Append-only product-path latency snapshots for the CI latency-tail ratchet.

| Artifact | Role |
| --- | --- |
| `ledger.jsonl` | One JSON object per runtime close (or seeded row) |
| `baseline.json` | Pinned p95/p99 ceiling + `window` for the ratchet |

## Writing a row

**Changed 2026-08-10 (lane E4, C-A debt).** Until then this ledger was
*structurally unreachable*: `resolve_latency_ledger_path` returned `None` unless
`PARCEL_LATENCY_LEDGER` was set, and nothing in the repo ever set it. The ledger
therefore held one hand-seeded row for its whole life and the CI ratchet below
was permanently `skip`.

Resolution order is now:

1. an explicit `path=` argument;
2. `PARCEL_LATENCY_LEDGER` (redirect anywhere);
3. **this file** — the repo default, used automatically.

Two suppressions keep that from being a regression:

* `PARCEL_LATENCY_LEDGER_OFF=1` — explicit opt-out; restores the old
  write-nothing behaviour byte-for-byte.
* **a pytest process never resolves this file.** A unit test's runtime teardown
  is not a measurement and must not mutate a committed artifact. Tests that want
  a ledger pass an explicit path.

A **turn-less row is refused** by this file (`append_latency_ledger_row` returns
`None`). A row with no turns carries no percentile series, and the ratchet skips
baseline metrics a row lacks — so admitting one would produce a vacuous pass.

Writers today:

* `RobotRuntime.close()` — one row per closed session.
* `evals/companion/duplex_v1/run_duplex_v1.py` — one row per duplex eval run,
  replayed from the `DuplexVoiceSession` stage clocks it already collects.

```bash
.parcel/bin/python -m evals.companion.duplex_v1.run_duplex_v1   # appends one row
```

## CI

`scripts/ci_gate.py` keeps the committed percentile-pin pytest selection
(`latency-tail`, still the authoritative hard check), and additionally ratchets
the **latest** ledger row against `baseline.json`. While
`len(ledger) < baseline.window`, the ledger ratchet skips with a note (never
red). The seed row is clock-honest against the N19 stage vocabulary; it is
**not** a live duplex wall-clock measurement.

**Coverage caveat, because the gate's own message hides it.** The ratchet reads
only `rows[-1]` and silently skips any baseline metric that row lacks. Duplex
rows come from the **text** path — no microphone, no endpointer, no audio sink —
so the four acoustic pins (`AcousticAck`, `EndpointDecision`, `SttTranscribe`,
`PlaybackEnqueueToFirstSample`) are absent by omission and are **not compared**.
With a duplex row latest, the ratchet compares 2 of the 6 pinned metrics while
reporting "6 metric series". Re-earning acoustic coverage needs a real
capture/playback run to write the newest row.

## does_not_prove

A green ledger ratchet does not prove sub-700 ms acoustic ack on hardware.
That needs a PipeWire / real-device acoustic loop (nightly / bring-up).
