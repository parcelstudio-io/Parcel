# Local proactive-conversation opportunity gate · RESULTS · 2026-08-24

Evidence tier: **preserved-authored-desktop-replay**. Hosted spend: **$0.00**.
No model, daemon, live microphone, camera, robot, owner database or product
runtime was invoked.

## Headline

The pre-registered hypothesis **passed every numerical row on the frozen H2
replay**, but post-registered refuters exposed two real prototype dependencies.
If an absent person is falsely asserted to be the verified owner, the gate
speaks on **14/17** affected cases. If one required field is missing/malformed,
the research dictionary interface fails open on **9/9** probes. The policy
mechanism is promising; the perfect corpus classification is not physical or
product-contract evidence.

The six H2 cases already marked `arguable=true` were excluded from the
pre-registered headline and are reported separately. No case, threshold or bar
was changed after execution.

## Reproduction

```bash
.parcel/bin/ruff check \
  research/20260824/conversation-opportunity/opportunity_gate.py
.parcel/bin/python \
  research/20260824/conversation-opportunity/opportunity_gate.py \
  --repo . \
  --out research/20260824/conversation-opportunity/results.json
```

Input:

- H2 `gold_set.json`: 60 cases, SHA-256
  `8afcf8e0b2ff2af0ba9796d02a5505f837dd68769e0fef8cffd937b6dafe90ff`;
- H1 frozen median modelled mini-audio response: **$0.004371**;
- H3 headline initiative rate: **5.3333/hour**, with 4 remarks over three
  headline hours.

The first attempted execution stopped before producing a result because the H1
cost field was addressed at the JSON root rather than `models.mini`. Only that
artifact path was corrected; policy, thresholds, labels and bars were unchanged.

## Pre-registered classification

Headline: 54 unarguable cases, including 15 useful speech opportunities
(`remark` or `ask`).

| arm | calls | TP / FP / FN | precision | recall |
|---|---:|---:|---:|---:|
| timer-only, 360 s | 43 | 11 / 32 / 4 | 0.2558 | 0.7333 |
| naive novelty | 44 | 15 / 29 / 0 | 0.3409 | 1.0000 |
| context timer | 11 | 9 / 2 / 6 | 0.8182 | 0.6000 |
| **opportunity gate** | **15** | **15 / 0 / 0** | **1.0000** | **1.0000** |

All 60 cases, including the six arguable labels:

| arm | calls | TP / FP / FN | precision | recall |
|---|---:|---:|---:|---:|
| timer-only | 48 | 14 / 34 / 4 | 0.2917 | 0.7778 |
| naive novelty | 50 | 18 / 32 / 0 | 0.3600 | 1.0000 |
| context timer | 14 | 12 / 2 / 6 | 0.8571 | 0.6667 |
| **opportunity gate** | **18** | **18 / 0 / 0** | **1.0000** | **1.0000** |

Interpretation: novelty alone retained every useful row but would call the
hosted model for most looks, go-checks and prohibited moments. The timer was
both chatty and forgetful. The context timer was precise enough but missed 40%
of useful headline opportunities. A semantic opportunity needs both a context
door and evidence scoring.

## Acceptance rows

| row | bar | measured | disposition |
|---|---|---|---|
| O1 prohibited proactive speech | 0 | **0** frozen admissions; **0/48** authored one-field refuters admitted | MET |
| O2 useful recall | >= 0.80 | **1.0000** | MET |
| O3 useful precision | >= 0.80 | **1.0000** | MET |
| O4 call reduction vs naive | >= 50% while O2 holds | **65.91%**, recall 1.0 | MET |
| O5 cooldown/dedup sequence | exact, no premature repeat | exact; **0** premature repeats | MET |
| O6 determinism | one SHA over 10 repeats | one SHA, `3f454abd…32c032` | MET |
| O7 local latency | p95 <= 1 ms over >=100k | 120,000 decisions: median **0.002053 ms**, p95 **0.003536 ms**, p99 0.003926 ms, max 0.127222 ms | MET |
| O8 cost | report | reported below | MET |

The authored stateful sequence produced exactly:

```text
subject@0     ADMIT
subject@30    REFUSE internal cooldown
subject@90    REFUSE subject dedup
subject@120   REFUSE subject dedup
distinct@120  ADMIT
subject@601   ADMIT
```

Those 48 mutations and six-step sequence are rule-derived synthetic refuters.
They verify implementation invariants, not whether a person appreciates the
interruption.

## Hosted-call and cost effect

Using H1's frozen modelled median audio-turn price:

| arm | one 54-case pass | per 1,000 candidate digests | H3-normalized month |
|---|---:|---:|---:|
| timer-only | $0.187953 | $3.4806 | $6.6828 |
| naive novelty | $0.192324 | $3.5616 | $6.8382 |
| context timer | $0.048081 | $0.8904 | $1.7095 |
| **opportunity gate** | **$0.065565** | **$1.2142** | **$2.3312** |

The month column assumes H3's 5.3333 *candidate* initiatives/hour, 12 active
hours/day and 30 days (1,920 candidates/month), then applies this corpus's
admission fraction. It is a normalization, not measured household prevalence.
The context timer is cheaper because it misses useful opportunities; it fails
O2. At these sparse rates, proactive phrasing is not the $200/month risk. H1's
TV-induced response firehose remains the risk.

The one preserved H3 per-tick trace contained seven owner turns and one remark
proposal. That remark landed exactly **90.0 s** after the prior owner turn,
consistent with its existing deterministic quiet gate. This is n=1 and is
context only.

## Post-registered refuters: upstream state errors

These probes were added only after the clean pass and do not alter O1–O8.

| deliberately wrong upstream field | affected frozen cases | newly admitted |
|---|---:|---:|
| absent owner falsely marked verified/present | 17 | **14** |
| owner speaking falsely marked silent | 6 | 0 |
| busy lane falsely marked free | 3 | 0 |
| quiet hours falsely marked daytime | 4 | **3** |

The speaking and lane mutations remained safe because the 15 s turn-tail gate
also rejected those cases. Owner identity had no equivalent independent guard.
The 14 identity-dependent errors were 3 ignores, 5 silent looks and all 6
go-check cases. This is the most important result for the prototype: the local
door can only be as private as the owner-presence assertion feeding it.

An independent post-run audit then challenged the untyped research interface.
All nine malformed/incomplete variants were admitted:

| invalid candidate | result |
|---|---|
| missing `owner_speaking`, `lane_busy`, `quiet_hours`, or E-stop state | **4/4 admitted** |
| missing owner-turn or robot-utterance age | **2/2 admitted** |
| string `"false"` used for `owner_present` | **admitted** (truthy in Python) |
| NaN owner-turn or robot-utterance age | **2/2 admitted** |

This is a refutation of the harness interface, not a retroactive change to
O1--O8. The frozen corpus supplies well-typed complete rows, so its classification
scores are unchanged. Production must parse a versioned typed candidate and
reject missing, non-finite, wrong-type, stale, or unknown-version evidence
before policy evaluation. The research script must not be copied into the
runtime as-is.

A post-registered ablation also found:

- hard gates without evidence scoring: recall **1.0**, precision **0.7895**;
- minimum admitted score: **0.40625**;
- maximum rejected score after hard gates: **0.073125**;
- separation margin: **0.333125**.

That enormous separation explains the perfect score and is a warning, not a
triumph: H2 was authored with very legible positive and negative situations.
Real detector confidence, stale tracks, mixed rooms and ambiguous social timing
will fill this empty margin.

## Mechanism learned

The useful product split is:

1. continuous local sensing produces a typed, grounded candidate and a
   fail-closed boundary validates it;
2. a local opportunity gate enforces identity/privacy, interruption, quiet,
   staleness, cooldown and subject dedup;
3. only an admitted candidate may request hosted phrasing;
4. a refusal may still become a free silent look/gesture; and
5. the hosted model can abstain but cannot buy back a local refusal.

This is event-driven. No LLM should poll the world or decide emergency,
privacy, turn-taking or cadence.

## Limitations

- H2 is authored, balanced desktop evidence created inside the same project.
  It has no natural base rate and no independent human raters.
- `owner_present` was treated as `verified_owner_present`; the artifact carries
  neither identity confidence nor consent. The post-hoc refuter shows that this
  assumption is load-bearing.
- A natural-language noticing label is used only as an opaque hashed dedup key.
  Production needs a stable track/event ID and timestamp, not text identity.
- `recent_actions` has no ages, so any string containing `remarked` is treated
  as recent. This is conservative and can create silence after unrelated old
  remarks.
- No phrasing, barge-in, AEC, acoustic tail, multi-person privacy, emotion or
  owner annoyance was measured.
- The research implementation accepts a raw dictionary with permissive
  defaults; its 9/9 malformed-input failures explicitly disqualify that
  interface from product reuse.
- The exact latency is host/Python specific. The meaningful result is its
  >280× margin beneath a 1 ms bar, not the microsecond digits.

The canonical machine result is `results.json`; its exploratory fields are
explicitly marked `post_registered`.
