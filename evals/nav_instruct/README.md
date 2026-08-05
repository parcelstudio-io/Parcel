# NAV_INSTRUCT_V1

Seeded instruction-navigation eval: five families × tiers A–E.

```bash
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
  --minival --mode baseline --out evals/nav_instruct/results
```

Hard gate: freeze a refusal-heavy baseline **before** grounding rewire (N-O2).
