# AutoRaters — conversation-quality scoring for Parcel

Compare a **base** and a **test** response to the same owner request and return
either a signed "which was better" score or a countable side metric such as the
number of punts. Both single-turn and multi-turn samples use the same types.

## Two rater shapes

| Shape | Question | Output | Position bias? |
| --- | --- | --- | --- |
| `ComparativeAutoRater` | which side was better? | `ComparativeVerdict`, `score ∈ [-1, +1]` | yes — both orders are run |
| `SideMetricAutoRater` | how many X did this side do? | `SideMetric`, a count or rate | n/a — one side only |

`score` is signed: **negative favours base, positive favours test**, `0` is a
genuine tie. An **abstention** carries `score = None`, never `0.0` — a judge that
could not parse its own output produced no evidence, and scoring that as a tie
would launder a failure into a measurement.

## Raters

| id | Kind | What it measures |
| --- | --- | --- |
| `pairwise_quality` | comparative | overall: task success, honesty, personality, efficiency |
| `honesty_groundedness` | comparative | unsupported claims and admitted limits, only |
| `persona_consistency` | comparative | companion voice vs. template/status-printout register |
| `multi_turn_coherence` | comparative | context retention, follow-through, non-repetition |
| `punts_rule` | side metric | punts, by exact rule — **no model required** |
| `punts_llm` | side metric | punts, judge-scored, catches novel phrasings |

### What counts as a punt

A robot turn that declines without doing the work **and without advancing the
conversation**. `"I did not understand that command."` is a punt. `"I can't get
onto the sidewalk, there's a fence — want me to go around?"` is not: it names the
obstacle and offers a next step. The test is whether the exchange moved.

`punts_rule` is exact, free, and runs with no judge provisioned; it catches the
literal phrasings the current stack ships. `punts_llm` catches phrasings no rule
anticipated. **Run both** — a gap between them is a signal that the rule set has
fallen behind the model's vocabulary, not that one of them is broken.

## Usage

```python
from evals.autorater import (
    LlamaCppJudge, RatingRequest, Response, Turn, default_registry,
)

request = RatingRequest(
    prompt="go to the sidewalk",
    base=Response("base", (Turn("robot", "Okay—I'll move onto sidewalk and verify it."),)),
    test=Response("test", (Turn("robot", "Sidewalk, got it — heading over now."),)),
    context=(Turn("owner", "hey, you there?"), Turn("robot", "Right here.")),
)

registry = default_registry(LlamaCppJudge(base_url="http://127.0.0.1:8090"))

verdict = registry.get("pairwise_quality").rate(request)
print(verdict.score, verdict.preference, verdict.position_bias, verdict.rationale)

base_punts, test_punts = registry.get("punts_rule").measure_both(request)
print(base_punts.value, test_punts.value)
```

Without a backend, `default_registry()` returns only the rule-based raters, so
punt counting works on a machine with no judge model at all.

## Why the judge is run twice

An LLM judge shown the same pair twice with the sides swapped will often pick
whichever it saw first. `ComparativeAutoRater` therefore runs both orders,
canonicalises the sign, and reports the spread as `position_bias`. A judge that
answers "A" both times scores `0.0` with `position_bias = 1.8`, and
`is_decisive` is `False` — the disagreement is surfaced rather than averaged
into a confident-looking number.

There is also a `tie_band` (default `0.1`): a judge asked to name a winner will
always name one, so margins inside the band are reported as ties rather than
being recorded as real preferences.

## Provisioning the judge model

`models/judge/` holds a provenance-pinned GGUF, following the same lock schema as
`models/reasoner/`. Serve it with the existing llama.cpp stack on a port that
does not collide with the reasoner (`:8080`) or a talker:

```bash
llama-server -m models/judge/Qwen3-32B-Q4_K_M.gguf --port 8090 --ctx-size 8192
```

Qwen3-32B-Q4_K_M is Apache-2.0 (the lock admits no other licence) and ~19.8 GB,
which fits the 32 GB card. AutoRating is **offline batch work** — it does not
share the GPU with MuJoCo or the live voice stack, so it can use the whole card.

## Scores are only comparable within one `rater_id@rater_version`

Changing a prompt changes the version. A ledger that mixes two prompt revisions
under one name is worthless, so `fingerprint` (`pairwise_quality@1`) belongs in
every recorded row.

## does_not_prove

* **An AutoRater is itself unverified.** Nothing here has been calibrated against
  human preference on Parcel transcripts. Until it is, these scores rank two
  candidates against *each other* under one rubric — they are not a quality
  measurement, and a win does not mean an owner would prefer it.
* **`punts_rule` cannot see a punt it has no pattern for**, and `punts_llm`
  inherits every bias of the judge model.
* **The judge shares a family with nothing it rates today**, but if it is ever
  pointed at responses generated by Qwen, self-preference bias becomes a live
  concern and needs a held-out check.
