# AutoRater framework + judge model provisioning

**Date:** 2026-08-16 · **Executor:** Claude Opus · **Baseline:** `8473a51` on `main`
**Location:** `evals/autorater/` — deliberately **not** under `src/parcel_robot/`,
because `evals/external/barn_policy_specs.py` hashes that subtree's `rglob('*.py')`
**membership tuple**; a new module there moves a frozen external-eval digest.

## What this is

An interface for scoring conversation quality by comparing a **base** and a
**test** response — single-turn or multi-turn, with metadata — returning either a
signed "which was better" score or a countable single-side metric such as the
number of punts.

| Type | Role |
| --- | --- |
| `Turn` / `Response` / `RatingRequest` | inputs; one `Response` holds 1..n turns, so single- and multi-turn samples share one type |
| `ComparativeAutoRater` | base vs test → `ComparativeVerdict.score ∈ [-1, +1]` |
| `SideMetricAutoRater` | one side → `SideMetric.value` (count/rate) |
| `RaterRegistry` | id → rater, so a suite is config rather than code |
| `JudgeBackend` | text-in/text-out protocol; `LlamaCppJudge` and `ScriptedJudge` |

Six raters ship: `pairwise_quality`, `honesty_groundedness`, `persona_consistency`,
`multi_turn_coherence` (comparative), and `punts_rule` / `punts_llm` (side metric).

## Three decisions that carry the design

1. **Position bias is measured, not averaged away.** An LLM judge shown the same
   pair twice with sides swapped often prefers whichever it saw first. Every
   comparative rater runs **both orders**, canonicalises the sign, and reports the
   spread as `position_bias`. A judge answering "A" both times scores `0.0` with
   `position_bias = 1.8` and `is_decisive = False` — the disagreement surfaces
   instead of becoming a confident-looking number. Pinned by
   `test_a_judge_that_always_picks_the_first_side_is_caught`.
2. **Abstention is not a tie.** An unparseable judge reply yields
   `score = None`, never `0.0`. Scoring a broken judge as a tie launders a
   failure into a measurement — the same rule the eval packs already apply to
   `does_not_prove`. The dataclass refuses to construct an abstention that
   carries a score, and refuses one that does not say why.
3. **A tie band, because a judge asked for a winner will always name one.**
   Margins within `0.1` of zero are reported as ties rather than recorded as
   real preferences.

## Punts

A punt is a robot turn that declines **without doing the work and without
advancing the conversation**. `"I did not understand that command."` (the literal
shipped string from `agent.py`) is a punt. `"I can't get onto the sidewalk,
there's a fence — want me to go around?"` is not: it names the obstacle and
offers a next step. The test is whether the exchange moved.

`punts_rule` is deterministic, exact, free, and **needs no model** — it matches
the literal phrasings the current stack ships, and a rescue pattern suppresses a
hit when the decline is followed by a concrete offer. `punts_llm` catches
phrasings no rule anticipated. Run both: a gap between them means the rule set
has fallen behind the model's vocabulary.

## Judge model

`models/judge/Qwen3-32B-Q4_K_M.gguf` — Qwen3-32B, **Apache-2.0** (the lock schema
admits no other licence), 19.8 GB, pinned to hub revision `938a7432`.
`models/judge/pin_lock.py --pin` computes the digest of the bytes actually on
disk and writes `models.lock.json` in the same schema as `models/reasoner/`;
`--verify` re-checks. The weights are gitignored; the lock is the artifact.

Chosen because AutoRating is **offline batch work** — it does not share the GPU
with MuJoCo or the live voice stack, so it can use the whole 32 GB card, and
judge capability is the thing that matters most for rating quality.

## Test evidence

```
$ .parcel/bin/python -m pytest tests/test_autorater.py -q
32 passed in 0.11s
$ .parcel/bin/python -m ruff check evals/autorater tests/test_autorater.py models/judge
All checks passed!
```

The suite pins the failure modes, not the happy path: position-bias detection,
abstain-on-unparseable, abstain-on-unreachable, abstain-on-unknown-winner,
tie-vs-abstention distinguishability, per-turn punt attribution, owner turns
never counting as punts, and `MetricDelta` returning `None` when either side
abstained.

One test bug of mine (`(Turn(...))` without a trailing comma) surfaced a real
usability gap — the dataclass raised a `TypeError` from deep inside `tuple()`.
It now rejects that explicitly and names the cause; regression-pinned.

## does_not_prove

* **The AutoRaters have never run against the judge model.** The download was
  still in flight at the end of this session. Every test drives `ScriptedJudge`,
  a deterministic double. **No rater has produced a real verdict yet**, and the
  prompts are unexercised against a live model — the most likely first failure
  is a prompt whose JSON contract the model does not honour, which the harness
  will report as an abstention rather than a bad score.
* **No calibration against human preference.** These scores rank two candidates
  against each other under one rubric. A win does not mean an owner would prefer
  it. Calibration on held-out Parcel transcripts is the next card, and until it
  exists nothing here should gate a promotion.
* **`punts_rule` cannot see a punt it has no pattern for**; `punts_llm` inherits
  every bias of the judge.
* **Self-preference is a live risk later.** The judge is Qwen; nothing it rates
  today is Qwen-generated, but the Voice Spine design proposes a Qwen3-4B talker.
  If that lands, this judge rating its output needs a held-out cross-check.
* Nothing here touches the runtime, motion, or any safety surface. It is an
  offline evaluation package with no import from `parcel_robot`.

## Handoffs

1. `python models/judge/pin_lock.py --pin` once the download completes, then
   serve it: `llama-server -m models/judge/Qwen3-32B-Q4_K_M.gguf --port 8090`.
2. First real run should be a **sanity pair with a known answer** (a templated
   ack vs. a grounded refusal) before any batch: if the judge cannot call that
   one, the rubric is wrong, not the candidates.
3. Calibration card: score N held-out Parcel transcript pairs, collect human
   preference, report judge-human agreement. Until that number exists, treat
   every score here as a ranking signal and not a quality measurement.
