# EVENT-BUDGET — RESULTS · 2026-08-24

## Run

```bash
.parcel/bin/python \
  research/20260824/event-driven-companion-budget/budget_model.py \
  --repo . \
  --out research/20260824/event-driven-companion-budget/results.json
```

The run is deterministic (`seed=20260824`) and made no network or provider
call. It sampled 10,000 30-day totals from H1's 174-row mini-audio cost
distribution. Because even the smallest scenario contains 5,700 monthly
turns, the simulation used the normal approximation to the sum with the
empirical mean and population standard deviation. Text calls were added at
their frozen deterministic costs. The complete machine-readable output is
in `results.json`.

## Measurements

| row | result | bar | outcome |
|---|---:|---:|---|
| E1 nominal p95 | **$30.7237/month** | <= $100 | pass |
| E2 heavy-social p95 | **$76.9501/month** | <= $150 | pass |
| E3 hosted-proactive stress p95 | **$32.1315/month** | <= $150 | pass |
| E4 ungated-TV p50 | **$571.2909/month** | > $200 refuter | pass |
| E5 1 Hz hosted tick | **$777.6000/month** | > $200 refuter | pass |
| E6 hosted calls from continuous local loops | **0** | exactly 0 | pass |

Additional distribution checks:

| scenario | p50 | p95 | simulated max |
|---|---:|---:|---:|
| nominal | $30.4860 | $30.7237 | $31.0496 |
| heavy social | $76.5639 | $76.9501 | $77.4841 |
| hosted proactive stress | $31.9025 | $32.1315 | $32.5187 |
| ungated TV | $571.2909 | $572.3630 | $573.5936 |

H1's per-turn distribution had p50 **$0.00437101** and p95
**$0.00791034**. The ungated row conservatively charges every admitted
false opening as a full turn. The 1 Hz row makes 1,296,000 calls/month with
600 input and 100 output text tokens each.

## Interpretation

The provider price is not the binding constraint at intended social use.
Admission is. A modest voice gate changes the modeled total by over $540 per
month relative to H1's TV-like false-opening rate. Structured instruction
planning and scheduled consolidation are inexpensive at their frozen text
budgets; making any hosted model a clock-driven cognition loop is not.

This is cost evidence, not a claim that VOICE-GATE meets its accuracy bar or
that all planned calls have the assumed token counts. Production must meter
actual provider usage and fail closed at the hard budget.
