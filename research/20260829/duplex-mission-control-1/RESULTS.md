# DMC-1 results

Date: 2026-08-29. Evidence tier:
`desktop-sim/procedural-semantic-stream`; no physics, pixels, point clouds,
audio, ROS 2, Orin, gateway, hosted call, robot, or physical motion. Hosted
cost: $0.00.

## Runs

- 1,000 frozen seeds (`20000..20999`) and 500 adversarial seeds
  (`30000..30499`), five arms per episode;
- 100 simulated stream-hours per arm, 500 across all arms;
- 5,000 dedicated transient/persistent blocker cases;
- two process-level reproductions; semantic projections were identical with
  normalized SHA-256
  `0d8d4623daafba661664b5ff665b98a8825c642db2d0d3f7e78db9dee2b9ba15`;
- raw result bytes differ because encode-latency measurements were mistakenly
  included in the nominal deterministic payload; `POSTRUN_NOTES.md` records
  that defect; and
- a post-run adversarial receipt/narration probe, frozen in
  `REVIEW_TEST_PLAN.md`, produced SHA-256
  `1da64b6b8c7aa6682b87bb0172dc46c98a48f1bfaf765c32ce6be5fbfba7bbbf`.

## Headline measurements

| arm | mission success | raw unsafe proposals | admitted unsafe | wrong-route moves | premature completion |
|---|---:|---:|---:|---:|---:|
| F0 flat/latest intent | 0 / 1,500 | 369 | 0 | 0 | 1,508 |
| L0 ledger + conservative snapshot | **1,500 / 1,500** | 458 | 0 | 0 | 0 |
| L1 ledger + explicit time | 1,495 / 1,500 | 372 | 0 | 0 | 0 |
| A0 ledger + snapshot MLP | 1,494 / 1,500 | **249** | 0 | 0 | 0 |
| A1 ledger + history GRU | 1,496 / 1,500 | **3,781** | 0 | **296** | 0 |

A1 success was 0.99733 (seed-bootstrap 95% interval
[0.99467, 0.99933]). The ideal semantic admission gate caught all 3,781 A1
raw-unsafe proposals; this is evidence about the gate in this generator, not
evidence that A1 is safe. L0 succeeded on all four A1 refuter seeds:
`20127`, `20468`, `20994`, and `30360`.

On the authored liveness slice, clear-to-progress p95 was 0.7 s for L0, 0.3 s
for L1, 0.0 s for A0, and 0.3 s for A1. Mean excess hold was 6.0036, 2.0036,
0.0, and 2.5018 frames respectively. L1 therefore matched A1's p95 and had
lower mean hold without a neural model. The slice's post-gate unsafe count is
not an independent safety test: the implementation defines admission using
`not occupied` and then checks `admitted and occupied`.

The snapshot MLP had 5,704 parameters; the history GRU had 20,232. On the
authored label-to-feature generator, held-out macro-F1 was 0.98109 versus
0.99995, a delta of only 0.01886 against a frozen 0.05 promotion bar. Desktop
single-thread p99 inference was 0.026 ms and 0.163 ms. H6 is therefore
**refuted**, irrespective of the high absolute self-consistency score.

Event frames used 4,064,368 bytes for A1 versus 1,438,611,026 bytes for full
10 Hz frames, a 99.717% byte reduction. The measured conservative maximum
per-episode encode p99 was 0.0289 ms. This supports change-triggered transport
as an efficiency mechanism; it does not establish hosted token cost or fact
recall.

## Independent validity audit

Sol Ultra reviewed source and results independently, reproduced the key
arithmetic, and found benchmark-validity defects. We then encoded and ran
three minimal counterexamples. All three secure expectations failed:

| counterexample | observed DMC-1 behavior | secure behavior |
|---|---|---|
| correct task/revision, wrong `step_id`, attempt 999, terminal completion | **accepted_terminal** | reject |
| `started` receipt after that terminal | **accepted_started** | reject invalid transition |
| fabricated task/revision completion using an unrelated trusted receipt ID | narration oracle returned **true** | reject |

The DMC ledger checks task/revision and receipt-ID duplication but not step,
attempt, status ordering, active execution, authentication, expiry, or
sequence. The narration validator treats membership of a receipt ID in a set
as sufficient for a terminal claim and does not compare every claimed field
with the receipt. Stored rows contain aggregate self-scores rather than the
full receipt/narration traces needed for an independent oracle. Consequently
the automated H3/H4 booleans in `results.json` are not valid evidence.

Other limitations found by review:

- training examples select the action label before constructing features, so
  the learned held-out row is generator self-consistency;
- held-out command templates are hard-coded into the parser;
- command kinds and ticks are fixed across episode splits rather than timing-
  and family-disjoint as promised;
- arms use different receipt-delay random streams, so they are not fully
  matched on exogenous schedules;
- final empty/all-completed state substitutes for exact queue/suspend/resume
  transition accuracy; and
- F0 structurally loses queued tasks while success requires all three tasks,
  making it a deliberately weak architectural sentinel rather than a fair
  controller baseline.

For a product-shaped comparison, the same-day blind NAV-INT-1 steering set
scored 0.827 overall, with queue 0.667 and clarify 0.800. Those rows are more
informative about language generalization than DMC-1's 1.0 template-parser
score.

## Automated versus controlling interpretation

`results.json` is preserved unchanged: its code reported H1–H5 supported and
H6 refuted. After independent audit, the controlling interpretation is:

- H1: **inconclusive/narrow** — high final completion in one fixed transaction
  schedule, but no valid two-frame timing or exact transition-sequence oracle;
- H2: **inconclusive/narrow** — useful authored hysteresis comparison, no
  pedestrian prediction, social geometry, sensor perception, or independent
  post-gate collision test;
- H3: **unverified due to invalid receipt/narration oracle**;
- H4: **unverified due to missing corruption classes and the same oracle**;
- H5: **supported only for byte/CPU compression**, not required-fact recall or
  hosted token/cost behavior; and
- H6: **refuted**.

