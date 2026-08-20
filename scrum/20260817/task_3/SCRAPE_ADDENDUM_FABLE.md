# Addendum — the live scrape ran, broke twice, and is now captured · Fable

**Date:** 2026-08-18 · extends `R2C_STATUS.md` / `AUDIT_R2C_FABLE.md`
(the card closed with the scrape credit-blocked; credit landed and the scrape
was executed by the auditor, with two live defects found and fixed).

## Defect 1 — the GA API refuses the scraper's session shape

First run: every thread failed at turn 0. Wire-verified with three live
probes: `session.update` without `"type": "realtime"` is
`missing_required_parameter`, and top-level `turn_detection` is
`unknown_parameter` (it moved inside `audio.input`). Fixed in
`_session_payload` with the evidence in a comment. One thread then captured
cleanly (8 turns, $0.02).

## Defect 2 — `response.done` is not success

Full run "succeeded" while silently recording **103 empty turns out of 174
across 21/25 threads**: under load the provider closes rate-limited responses
with `status: "failed"` and zero usage, and the scraper never read `status`.
Caught by the strengthened billing-provenance test (live fixtures must carry
per-turn output tokens), diagnosed by re-scraping one damaged thread in
isolation (came back 8/8 full). Fixed with status verification + bounded retry
(`RESPONSE_ATTEMPTS=4`, linear backoff); the second full run captured
**174/174 turns non-empty, 25/25 threads, $0.50 measured** (day total across
attempts ≈ $0.79, ceiling $5).

## World-pin updates (tests that encoded the blocked/seed world)

`test_billing_data_matches_fixture_provenance` (was: seeds carry no billing
data — now provenance-conditional, with the inverse assertion for live
captures), `test_the_manifest_records_…_captured_scrape` (was `_blocked_`),
`test_the_captured_corpus_spans_every_scenario_family` (was: 3 seeds), and the
navigate-refusal replay test (count identities instead of seed literals; a
live model ordered and repeated its calls as it pleased —
`['get_status','navigate_to','navigate_to']` on thread 1). `SCRAPE_STATE` and
`FROZEN_NOTE` updated to the captured world; the pack stays deliberately
unfrozen pending human review (`human_review_required: true`).

## Corpus as captured

25 threads / 174 turns, zero empty; families navigation 9 · conversation 9 ·
punt 4 · perception 3; **32 real tool-call proposals captured
(`navigate_to` 22, `get_status` 10)**; usage recorded per turn with the cache
discipline visible (thread 1: 5,312 of 7,570 input tokens cached). Full gate
after everything: **PASS, 6,035 passed.**

## does_not_prove

Corpus quality has had no human review; the `expect` blocks still have no
scorer (AutoRater wiring is the natural next card); nothing here measures the
model's tool-call *correctness* — only that proposals were captured and that
the replay pipeline drives the real lane with them.
