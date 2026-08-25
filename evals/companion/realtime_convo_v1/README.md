# realtime_convo_v1 — hosted companion conversation corpus

**Card:** R2-C (`scrum/20260817/task_3`) · **Suite id:** `parcel-realtime-convo-v1`
**Model targeted:** `gpt-realtime-2.1-mini` · **Modality:** text
**Status: captured and reviewed once by an unblinded AI, NOT frozen.** The
2026-08-18 live scrape produced 25/25 threads and 174/174 non-empty owner turns
on its second full run. The successful run recorded $0.50 of provider usage.
The 2026-08-24 review found 6 PASS / 8 MIXED / 11 FAIL threads; calibrated,
blinded human review is still absent.

## What this pack is

25 authored conversation **scenarios** whose owner side is fixed text, a
**scraper** that runs them live and captures one JSON **fixture** per thread,
and a **schema** that turns any fixture back into a `FakeRealtimeServer` script
so the real `RealtimeLane` can replay it offline forever.

```
scenarios.json ──(scrape_realtime_convo.py, live, $-gated)──▶ fixtures/*.json
fixtures/*.json ──(schema.fixture_to_script)──▶ FakeRealtimeServer steps
steps ──(RealtimeLane, offline)──▶ ledger rows · usage rows · tool refusals
```

`tests/test_realtime_corpus_replay.py` drives that second and third arrow on
every commit. It never opens a socket and never needs a credential. The three
original hand-authored fixtures were overwritten by the live captures with the
same thread ids, so the replay path now runs recorded model output.

## Why the owner side is fixed text

The model is the variable. If the owner's turns were generated too, a re-scrape
in 2027 would be a different experiment rather than a comparable one. The 174
owner utterances across the 25 threads are deterministic probes: two of them are
the owner's own verbatim examples (`I am hungry, let's go to mcdonald's` and
`Can you see the closest lamppost?`) and are pinned character for character by
test.

## Coverage

| Family | Threads | What it probes |
| --- | --- | --- |
| `navigation` | 9 | going somewhere: ambiguity, unreachable targets, distance limits, corrections, deferring road-crossing decisions |
| `perception` | 3 | looking at something: what the robot can and cannot see, and refusing to invent it |
| `conversation` | 9 | the companion half: emotional support, small talk, memory callbacks, name/date corrections |
| `punt` | 4 | requests that should end in an honest "I can't": phone calls, recording the neighbours, carrying shopping, unlocking a door |

Developer flags vary per thread — six locations (`living room`, `front yard`,
`sidewalk near home`, `kitchen`, `back porch`, `hallway by the front door`),
mornings and evenings, and two personalities (`gentle_companion`,
`playful_companion`). Six threads carry a history digest that refers back to an
earlier thread, which is what makes the memory probes real rather than notional.

## Files

| File | What |
| --- | --- |
| `scenarios.json` | the 25 authored threads: family, probes, `si_profile`, DI flags, fixed owner turns, and what a good reply looks like |
| `schema.py` | typed, fail-closed loaders + `fixture_to_script` + `verify_prompt_plane` |
| `scrape_realtime_convo.py` | the live scraper. Env-gated, budget-guarded, never a test |
| `build_manifest.py` | regenerates `corpus.manifest.json`; `--check` diffs it against the tree |
| `score_corpus.py` | hard structural/tool checks, report-only lexical risks and punts, and exact reviewer-coverage validation |
| `reviews/*.json` | explicit expectation-by-expectation semantic reviews with reviewer kind/blinding/calibration stated |
| `fixtures/*.json` | captured live conversation threads |
| `corpus.manifest.json` | digests, versions, usage totals, and the scrape's honest state |

## Running things

Always as a module, from the repository root — running the files by path puts
the pack directory on `sys.path` instead of the repo root and `evals` never
imports:

```bash
# offline, safe, free
.parcel/bin/python -m evals.companion.realtime_convo_v1.scrape_realtime_convo --self-test
.parcel/bin/python -m evals.companion.realtime_convo_v1.scrape_realtime_convo --dry-run
# Expected to report only si_version + si_digests while this SI-v1 capture is
# replayed by a tree shipping a later SI. The replay tests pin that exact drift.
.parcel/bin/python -m evals.companion.realtime_convo_v1.build_manifest --check
.parcel/bin/python -m evals.companion.realtime_convo_v1.score_corpus \
  --review evals/companion/realtime_convo_v1/reviews/20260824-unblinded-ai-review.json \
  --require-review --output /tmp/realtime-convo-quality.json

# the live scrape: costs money, needs BOTH the flag and a key
set -a; . ~/.config/parcel/realtime.env; set +a
PARCEL_REALTIME_SCRAPE=1 .parcel/bin/python \
    -m evals.companion.realtime_convo_v1.scrape_realtime_convo
.parcel/bin/python -m evals.companion.realtime_convo_v1.build_manifest
```

## The budget guard

The preflight estimate is printed and checked **before the first socket opens**,
and the measured spend is re-checked **after every response**. Either crossing
`$5.00` aborts the whole run. The ceiling is a module constant, not a flag: a
flag that can raise a spending limit is not a spending limit.

The prices used for the estimate are an operator **estimate**, generous on
purpose, and are *not* read from any price list. Before any future live scrape,
compare `ASSUMED_*_USD_PER_MTOK` with the billed rates and re-run `--dry-run`.
Reported spend always comes from the provider's own usage block, never from the
estimate.

## Why the manifest is not frozen, and is not called `manifest.json`

`tests/test_ci_gate.py` scans `evals/**/manifest.json` for `"frozen": true` and
pins that exact set, so that freezing a suite is always a reviewed act. This
pack now holds 25 live text captures, but they have not received the required
human quality review. `corpus.manifest.json` therefore carries digests, versions
and usage totals but **no frozen flag**.

The filename is the card's, and it has a consequence worth knowing: the ci_gate
scan globs `manifest.json` exactly, so it cannot see this file. A second, wider
scan lives in `tests/test_realtime_corpus_replay.py`
(`test_no_frozen_manifest_escapes_the_wider_scan`) and covers it. If a later
owner freezes this pack, rename the manifest to `manifest.json`, add it to
`DIGEST_SENTINELS`, and both scans cover it for free.

## does_not_prove

* **One AI review is not human preference.** The checked-in unblinded review
  judges all authored expectations and exposes 11 failing threads, but it is
  neither human, blinded nor calibrated. The machine checks prove corpus/tool
  contracts and surface lexical risks; they do not prove warmth or naturalness.
* **Usage is provenance, not an invoice audit.** The successful second full run
  records $0.50 from provider usage blocks (164,446 input and 18,730 output
  tokens); total spend across failed/retried attempts was about $0.79.
* **There is no captured audio**, so the fixtures store none. The
  `synthetic_audio_ms` option in `fixture_to_script` emits a deterministic tone
  for one playback-bridge test and is never written into a fixture.
* **The `expect` blocks remain authored expectations, not an AutoRater.** The
  semantic review records a verdict for each one, while the executable layer
  verifies complete coverage. It does not infer those semantic verdicts with
  keyword rules or silently treat the reviewer as ground truth.
* **Tool calls are proposals only.** The credential-free replay deliberately
  runs without the product broker and asserts refusal. It does not score the
  current broker's tool correctness, admission, navigation, or execution.
