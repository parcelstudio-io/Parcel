# C5 · SPEECH-ACTS-1 — receipt-typed speech acts as a product leaf module, flag OFF

**Executor:** Opus · **Verifier:** Fable · **Second lens:** parcel-6c · **Wave:** A for the leaf modules + tests; **B** for the `realtime/lane.py` / `runtime.py` install

## Finding (MB-2, verified + panel)

A receipt-typed contract (9 acts × slots × one template) scores grounding 1.000 / coverage 0.969 / 0 invented / 15/15 capability refusals at 0.4 ms; the hosted model scores 0.61–0.73 with invented actions; an ungated paraphraser deleted the "I have no camera" refusal 15/15. Facts belong in the contract. Evidence: `model-b-contract-2/{VERDICT.md, contract.py, arms.py, mb1_pins.sha256}`.

## Build

1. `src/parcel_robot/realtime/speech_acts.py` — port `contract.py`'s acts, slots, templates and the post-condition checker (`check`) as a leaf module with no research imports. **The product must not import `research/` at runtime.**
2. `src/parcel_robot/realtime/narration_matcher.py` — the claim extractor / invented-action matcher / inability & offer regexes ported from MB-1's `scorer.py`; its test asserts `sha256(research/20260829/model-b-narration-1/scorer.py) == e5044a90…9bab5` (from `mb1_pins.sha256`) and re-runs MB-2's arm T through the product module to the identical numbers, so the product never silently forks the matcher.
3. Flag: `realtime.speech_acts.enabled: false` in the realtime config (NOT `config.py` — it is at the ceiling; use the realtime yaml/section the whisperer already reads). Off-path byte-identical: a test pins `narrate_event`'s output over MB-1's corpus with the flag off.
4. Install (wave B): when ON, `narrate_event` renders the receipt through `speech_acts` and injects the template as the narration item (unbilled tail item), the paraphrase path stays OUT of scope (no local model in product on this card).

## Acceptance (verbatim bars)

- `~/.cache/parcel-guard/pytest_guard.sh --label C5 .parcel/bin/python -m pytest tests/test_speech_acts.py tests/test_narration_matcher.py tests/test_realtime_lane*.py -q` green; the arm-T reproduction row in the test equals MB-2's `results.json` `arm_T` (grounding 1.0, coverage 0.9688, invented 0, 180 turns).
- Off-path digest unchanged with the flag OFF; the flag exists and defaults OFF (test).
- No `noqa`; `config.py` unchanged; no hosted calls; no research import from `src/`.

## Does not prove
Naturalness (MB-2's judge was position-biased — unmeasured); the paraphrase layer; the install (wave B).
