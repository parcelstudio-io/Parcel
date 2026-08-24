# SAFE-ADAPT — RESULTS · 2026-08-24

## Run

The design was written before `run_experiment.py`. The run made no network,
model, API, product-runtime, live-memory or hardware call.

```bash
.parcel/bin/ruff check \
  research/20260824/safe-preference-adaptation/run_experiment.py
.parcel/bin/python \
  research/20260824/safe-preference-adaptation/run_experiment.py \
  --out research/20260824/safe-preference-adaptation/results.json
```

The harness executed 320 main runs: four profiles × 40 frozen seeds × two
arms. It also executed 24 full persistence equivalence cases. Runtime was
2.522 s in the final reporting run. `results.json` contains the per-seed
summaries, persistence hashes, design hash and evaluated bars.

A second full run wrote to a fresh temporary directory. After removing only
the measured wall-runtime field (`A8.runtime_s`), canonical `jq -S` output was
byte-identical to the first run.

Two reporting defects were corrected after execution. First, an unrecovered
drift case was represented by mathematical infinity, which strict JSON rightly
refused. A subsequent independent audit caught that replacing it with 2161
(`TOTAL_SLOTS + 1`) mixed total-slot units with eligible-opportunity units and
made the p95 look estimable. The final artifact reports p95 as **not estimable**,
14 right-censored runs, and the actual 710--762 eligible-opportunity exposure.
No policy, probability, seed, threshold, metric or bar changed.

## Preregistered rows

| row | bar | measured | outcome |
|---|---|---|---|
| A1 hard/translation violations | exactly 0 | 0 hard; 0 translation across both arms | **pass** |
| A2 expected-regret reduction | median >=25%; every stable profile >=15% | overall **40.26%**; social 38.57%, quiet 51.26%, mixed 37.12% | **pass** |
| A3 final negative-feedback reduction | every stable profile >=20% | social **15.77%**, quiet 31.35%, mixed **12.19%** | **fail** |
| A4 drift recovery | median <=72; p95 <=144 eligible opportunities | median **464**; p95 **not estimable**; **14/40 right-censored** after 710--762 eligible opportunities | **fail** |
| A5 final initiative rate | profile medians 3–8/h | all four profiles **4.05/h** | **pass** |
| A6 talk personalization | quiet <=.20; social >=.35 | quiet **.2173**; social .4821 | **fail** (quiet misses by .0173) |
| A7 persist/reload equivalence | byte-identical | 24/24 identical; 0 mismatches | **pass** |
| A8 runtime | <10 s | **2.522 s** | **pass** |

Quiet-profile talk fraction ranged from .1945 to .2705 across seeds. The
adaptive social profile's final negative-feedback rate ranged from .2887 to
.3747, demonstrating that the aggregate A3 miss is not one corrupt seed.

## Interpretation

The experiment separates two ideas that should not be conflated:

1. **A hard safety/capability shield around learning works.** It permitted
   stable activity around four initiatives/hour, admitted no translating
   action, violated no hard context gate, and survived persistence/reload
   byte-identically.
2. **This implicit decayed-bandit rule is not good enough to enact user
   preferences.** It substantially reduces expected regret in stable worlds,
   but negative feedback does not improve enough for the social/mixed users,
   it talks slightly too often to the quiet user, and it reacts far too slowly
   to an abrupt preference change.

The diversity penalty, exploration term and per-context sparse evidence all
contribute to the drift metric, but this run does not tune among mechanisms.
Doing so against these same authored probability tables would overfit the
study. A real product should collect explicit feedback in shadow mode and
preregister a new learner against held-out longitudinal users.

## Evidence boundary

This is a seeded mechanism simulation. The H3 cadence and action families are
repo-grounded; the user preferences and feedback are not. It establishes
constraint and replay behavior and refutes the preregistered adaptation rule.
It does not measure human comfort, implicit-signal validity or mounted robot
behavior.

The zero-translation row is structural—the policy's candidate vocabulary has
no translating action—not an adversarial parser test. A product implementation
still needs a malformed/unknown-action rejection test at its contract boundary.
Likewise, the common 4.05 initiatives/hour in A5 mostly reflects the simulated
opportunity cadence and shield, not evidence that this rate will feel natural.
