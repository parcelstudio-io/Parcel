# DUPLEX_V1 — duplex dual-stream eval (D0)

Headless, scripted turns against the D0 frame producer, filler policy, and
shadow consumer. Navigation quality is a regression gate against the
2026-08-04 post-speed-raise follow-bench + embodied ledger rows.

```bash
.parcel/bin/python -m evals.companion.duplex_v1.run_duplex_v1 \
  --out evals/companion/duplex_v1/results
```

Hard gates: TTFT P50 < 1 s measured via `DuplexVoiceSession`
(`query_end`→`tts_first_chunk`); no ceiling breaches without filler; zero
missing ACT frames at 10 Hz on coordinator producer ticks with ACT/TEXT
pushes; barge-in atomicity; shadow decode round-trip; nav rows unchanged
(follow-bench ledger + embodied freeze pin cross-check).
