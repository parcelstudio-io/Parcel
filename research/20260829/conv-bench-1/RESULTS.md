# CONV-1 — RESULTS

Executor: Opus (parcel-0e lane), 2026-08-29. Design: `DESIGN.md` (frozen).
Evidence tiers: **replay** (captured corpus, scripted duplex) and
**desktop-sim** (acoustic null sinks). **Hosted calls: 0. Spend: $0.00.**
Physical motion: NO-GO, unchanged. No verdict here — Fable writes `VERDICT.md`.

## Pre-flight record

* **`AMENDMENTS.md` did not exist** when this card was opened (15:33) and does
  not exist at close. `results.json` records `amendments_present: false`.
  Every criterion below is `DESIGN.md`'s as frozen; none was moved.
* **Wave-rule addendum read.** Fable's five additions to
  `research/20260829/README.md` (15:41) were received mid-run and are honoured:
  * (3) place names — the fixtures use only `door`, `front door`, `sofa`,
    `kitchen`, `back porch`: ordinary map vocabulary drawn from the shipped
    `realtime_convo_v1` DI location list and the wave charter's own
    `door → sofa → keys` scenario. `bridge.py --self-test` asserts none of them
    collides with the NAV held-out scene id, and it does so by **importing**
    `evals.nav_instruct.scene_truth.HELD_OUT_SCENE_ID` so this folder never
    spells the name out. Result: `collisions: []`, status `pass`.
  * (4) E3 — the bridge and its six fixtures are a **new tier in this folder**.
    Nothing re-pins a frozen corpus, manifest or digest; `score_corpus.py`,
    `scenarios.json`, `fixtures/` and `corpus.manifest.json` are read-only
    inputs and `git status --porcelain evals/` is empty at close.
  * (5) `/dev/bus/usb` was never opened. PipeWire null sinks only; `wpctl`
    captured before and after (below).
* **Host discipline.** `TMPDIR` unset for every invocation; no pytest was run,
  so the guard wrapper was not needed; no git writes; the owner's `:8080` /
  `:8765` / `/tmp/parcel_sim.sock` untouched; `PARCEL_MEMORY_PATH` pointed at
  `~/.cache/parcel-0e/cv1/scratch_memory.sqlite3` (never created — nothing
  built a runtime); `parcel_memory.sqlite3` never opened.

## H-CV1a — the frozen corpus rows do not move

> **DESIGN bar.** "Re-running `score_corpus.py` on the captured 25-thread
> corpus reproduces QEV-1's machine-contract result (25/25 threads, 0 hard
> failures, 66 review flags) byte-identically."

Ran `.parcel/bin/python -m evals.companion.realtime_convo_v1.score_corpus`
twice — once with the checked-in review + `--require-review` (the README's
recipe of record), once bare — with `--output` into `results/`.

| row | QEV-1 (2026-08-24) | CONV-1 (2026-08-29) | |
|---|---:|---:|---|
| threads | 25 | **25** | match |
| turns | 174 | **174** | match |
| hard failures | 0 | **0** | match |
| review flags | 66 | **66** | match |
| machine status | pass | **pass** | match |
| punt count | — | 0 | — |
| semantic threads | 6 PASS / 8 MIXED / 11 FAIL | **6 / 8 / 11** | match |
| expectations | 43/76 pass | **43 pass / 33 fail** | match |

Review-flag composition (not in QEV-1's summary; recorded for MB-1 to read
against): `spoken_reply_over_60_words` 32, `repeated_refusal_language` 17,
`tool_or_route_narration` 7, `perception_claim_without_result` 4,
`present_motion_claim_without_result` 4, `arrival_claim_without_result` 1,
`durable_memory_claim_without_result` 1 = 66.

**Byte-comparison.** `evals/companion/realtime_convo_v1/results/` **does not
exist** — no prior artifact is checked in (QEV-1's went to its scratch root
`/tmp/parcel-quality-20260824.VYhnnR`, long gone). The byte-compare was
therefore run between this card's own two invocations instead: the
`corpus` + `machine` + `claims` + `does_not_prove` sections are byte-identical
(`sha256 1cf596b600ec1a16ed7a7e71951fa714ea60e71706a4d9b134e8d285acb83174` over
the canonicalised section). The whole artifact is *not* byte-stable run to run
— `recorded_at_utc` is a wall clock — so "byte-identical" is only meaningful of
the machine-contract section, and that is what was compared. A stronger
equivalence is proved under H-CV1c: the flag **set**, not just the count,
reproduces through an independent code path.

**Exit code 0** (both invocations). **Wall 0.18 s.**
**Criterion: MET.**

## H-CV1b — duplex timing gates are the product's, and known

> **DESIGN bar.** "Re-running `run_duplex_v1.py` and the acoustic loop
> `run_acoustic_loop_v1.py` reproduces QEV-1's rows (7/7 duplex hard gates;
> acoustic 5/9 gates, endpointing ep50 0.812 s vs 0.500 bar) within the runs'
> own declared tolerances; exit codes 0/1/2 recorded."

### Duplex — reproduces

| gate | result |
|---|---|
| `ttft_p50_under_1s` | pass |
| `no_response_over_2s_without_filler` | pass |
| `act_continuity_zero_missing` | pass |
| `barge_in_atomicity` | pass |
| `shadow_round_trip` | pass |
| `nav_regression_unchanged` | pass |
| `filler_no_consecutive_repeats` | pass |
| **total** | **7/7** (QEV-1: 7/7) |

TTFT p50 = **35.444 ms** on the run of record (QEV-1: ≈ 35.7 ms; Δ −0.256 ms,
−0.7 %), against the gate's own declared tolerance of **< 1 s** — the runner
gates the band, not the digit. Five invocations happened in total (one manual,
four through `run.py`, because `run.py --all` necessarily re-runs this 0.2 s
deterministic step); **all five gave 7/7** and TTFT p50 inside
**35.400–35.519 ms**, which is the honest jitter band and is what the "within
the runs' own declared tolerances" clause is measured against.

Ancillary rows: 216 frames emitted, 0 missing ACT frames, 0 response
ceiling breaches, filler audible max 0.800 s, nav regression unchanged
(follow-bench 7/9, 0 hard collisions, navigate 2/2; embodied 1051 steps,
0 collisions, supported-case SR 1.0).

**Exit code 0. Wall 0.22 s. Criterion: MET.**

### Acoustic — DOES NOT reproduce: the runner crashes before writing a report

The full-suite run was made **once**, as instructed. It did not return 0, 1 or
2. It **crashed with an uncaught `ValueError` (process exit 1) in the
barge-in family**, 84 s in, and wrote no report at all:

```
File ".../evals/companion/acoustic_loop_v1/run_acoustic_loop_v1.py", line 502, in run_bargein
    robot_env = robot_only_envelope(monitor, captured, lag - interrupt_onset_in_capture)
File ".../run_acoustic_loop_v1.py", line 245, in robot_only_envelope
    aligned[offset:end] = owner[: end - offset]
ValueError: could not broadcast input array from shape (612,) into shape (0,)
```

Diagnosis (read-only; `evals/` was **not** edited). `robot_only_envelope`
computes `offset = round(needle_lag_s * SAMPLE_RATE_HZ / ANALYSIS_FRAME)` and
guards the write with `if offset < mixed.size and end > offset:`
(run_acoustic_loop_v1.py:241-244). That guard does not reject a **negative**
offset. `needle_lag_s` here is `lag - interrupt_onset_in_capture`
(run_acoustic_loop_v1.py:502-503) and goes negative whenever the cross-correlated
interrupt onset in the monitor file lands *earlier* than the onset measured in
the mic capture. With `offset < 0`, `aligned[offset:end]` is an empty slice
counted from the end of the array while `owner[: end - offset]` grows by
`|offset|` samples — hence "shape (612,) into shape (0,)". It is therefore a
**timing-dependent** defect, not a deterministic one: QEV-1 got through the
same family on 2026-08-24. It is a defect in `evals/`, outside this card's
OWNS, and is left unfixed and reported.

Because that crash makes four of the nine frozen gates unmeasurable, a
**second, narrower invocation** was made — `--families endpointing,duplex,prosody`,
the runner's own documented subset flag, over the three families the crash path
does not touch (`robot_only_envelope` is called only from `run_bargein`). This
is not a re-roll of the same measurement hoping for a greener number: the
crashed run is reported above in full, and the subset run cannot produce the
barge-in rows at all.

| gate | limit | QEV-1 | CONV-1 subset | status |
|---|---:|---:|---:|---|
| `endpointing_ep_cutoff_rate` | ≤ 0.05 | 0.0 | **0.0** | pass |
| `endpointing_ep50_s` | ≤ 0.500 | 0.812 | **0.792** | **FAIL** |
| `endpointing_ep90_s` | ≤ 1.000 | 0.8756 | **0.8756** | pass |
| `bargein_detection_p50_s` | ≤ 0.400 | 0.0641 | — | not measured |
| `bargein_flush_max_s` | ≤ 0.060 | 0.000052 | — | not measured |
| `bargein_acoustic_stop_p50_s` | ≤ 0.520 | 1.080 | — | not measured |
| `bargein_false_rate` | ≤ 0.02 | 0 (2 cases) | — | not measured |
| `duplex_acoustic_ack_p50_s` | ≤ 0.700 | 0.850 | **0.850** | **FAIL** |
| `prosody_apex_within_window_rate` | ≥ 0.80 | 0.5714 | **0.5714** | **FAIL** |
| **tally** | | 5 pass / 4 FAIL of 9 | **2 pass / 3 FAIL / 4 not measured of 9** | |

Of the five gates the subset could measure, **all five land where QEV-1 left
them**: three of them (`ep90` 0.8756, `duplex ack` 0.850, `prosody` 0.5714)
reproduce to the last recorded digit, and `ep50` moved 0.812 → **0.792 s**
(−2.5 %), still 1.58× over its 0.500 s bar. The four red gates QEV-1 named are
therefore confirmed red on three of four; the fourth
(`bargein_acoustic_stop_p50_s` 1.080 s) is **unmeasured today**, not cleared.

Ancillary subset rows: 17 cases executed (13 endpointing, 3 duplex, 1 prosody),
duration 84.86 s, `ep50_all_kinds` 0.822 s, by kind `complete` 0.787 /
`incomplete` 1.738 / `pause_heavy` 0.824 s, `incomplete_hold_p50` 1.738 s,
`duplex acoustic_ack_p90` 2.6852 s, `prosody median_signed_lag` +0.040 s,
`abs_lag_p95` 0.472 s. PipeWire 1.6.2, profile `virtual-pipewire-null-sink`,
node prefix `parcel_acoustic_108165`.

**Exit codes.** Full run: process **1** (uncaught exception — *not* the
runner's 0/1/2 contract; the runner never reached its `return`). Subset run:
**1**, the runner's "completed but red/invalid" code, confirmed by applying the
runner's own `quality_exit_code()` to the persisted report. Exit **2**
(rig unavailable) did not occur: `rig_available()` returned ok and the rig came
up both times. **Wall: 84 s (crashed run) + 85 s (subset) = 169 s.**

**Criterion: NOT MET** as written — the acoustic half does not reproduce
QEV-1's `25/25 cases, 5/9 gates` row on this host today, because the runner
cannot complete. That is the finding, recorded rather than smoothed. The duplex
half is met.

### Teardown and audio-device safety (wave rule 5)

`wpctl status` captured **before** (`logs/wpctl-before.txt`) and **after**
(`logs/wpctl-after.txt`). Diffing them, excluding the transient `wpctl` client
row itself, gives **no difference**: the reSpeaker XVF3800 device, sink 105
(vol 0.40), source 123 (vol 0.82) and the configured default are all exactly as
found, and the array never appears in `Streams`. Nothing opened
`/dev/bus/usb`. Both runs — including the crashed one, whose
`AcousticRig.__exit__` still ran — left **zero orphan PipeWire nodes** carrying
the run prefix and **zero orphan child processes** (`pw-play` / `pw-record`);
the subset report records `teardown_clean: true`,
`orphan_nodes_after_teardown: []`, `orphan_processes_after_teardown: []`.

### Two harness writes into `evals/`, both contained

1. **`run_duplex_v1.py` appends to `evals/latency/ledger.jsonl` regardless of
   `--out`** (`_emit_latency_ledger_row`, run_duplex_v1.py:272-287, via
   `resolve_latency_ledger_path`, `src/parcel_robot/observability.py:584`).
   The first manual run therefore dirtied a tracked file. The appended row was
   copied to `results/duplex/latency-ledger-row-from-this-run.jsonl` and the
   file restored with `git checkout -- evals/latency/ledger.jsonl`; every later
   invocation runs under `PARCEL_LATENCY_LEDGER` pointed into `results/duplex/`,
   which `run.py` sets for you.
2. **`run_acoustic_loop_v1.py` writes PCM scratch to
   `evals/companion/acoustic_loop_v1/results/.tmp`** irrespective of `--output`
   (RESULTS_DIR is a module constant, run_acoustic_loop_v1.py:944 and 968). It
   deletes it on the success path; the crashed run left 212 KB behind, which was
   removed by hand. The path is gitignored (`.gitignore:95`).

`git status --porcelain evals/` is **empty** at close. Neither write is a
modification of eval *source*; both are recorded because a reproducer needs to
know about them.

## H-CV1c — grounding improves with Model B, on the same scorer

> **DESIGN bar.** "The scorer's capability-overclaim and unsupported-arrival
> flags over MB-1's arm-Q transcripts are ≤ 0.2 × the flag rate over arm-D
> transcripts of the same scenarios."

**The headline ratio cannot be computed yet and is not claimed.**
`research/20260829/model-b-narration-1/` has produced no transcripts. What this
card delivers is the instrument, wired and proven, plus its entry point:

```
.parcel/bin/python research/20260829/conv-bench-1/bridge.py \
    --transcripts <MB-1 jsonl or directory> --output results/cv1c-mb1.json
```

`bridge.py` is a thin alias for `scorer_bridge.py` (the card names the module,
the brief names the entry point). It reads MB-1's JSONL shape — declared in
`README.md` — and emits `h_cv1c.ratio_q_over_d` with the pre-registered
`<= 0.2` bar already encoded, so nobody has to re-derive it later.

### It is the same instrument, and that is proved, not asserted

The bridge **imports** `RISK_PATTERNS`, `REFUSAL_PATTERN` and `_excerpt` from
`evals/companion/realtime_convo_v1/score_corpus.py` (lines 69-105, 106-111,
113); no pattern is re-authored, so divergence is impossible by construction.
The `spoken_reply_over_60_words` rule (score_corpus.py:228-236), the
`’`/`‘` normalisation applied before every search (score_corpus.py:226) and the
per-thread `repeated_refusal_language` rule (score_corpus.py:249-259) are
replicated line-for-line against those citations.

`run.py` then runs an **equivalence check**: it pushes all 174 turns of the
captured 25-thread corpus through the bridge's lexical layer and diffs the
result against `machine_findings()`'s own review findings.

| | scorer | bridge |
|---|---:|---:|
| review / lexical flags | 66 | **66** |
| flag **set** `(thread, turn, check_id)` | — | **identical** |

That is a stronger statement than H-CV1a's section hash: the same 66 flags land
on the same turns through an independent code path.

### Two layers, because the corpus could not have the second

`lexical` is the scorer's own report-only triage — "lexical risk flag; requires
semantic adjudication". `grounded` is the discriminator MB-1's transcripts make
possible: a lexical hit survives only if **no** event of a supporting kind had
fired by that turn (`SUPPORTING_EVENTS` in `scorer_bridge.py`). The captured
corpus carries no event stream, so all 66 of its flags are unsupported by
definition — which is exactly why QEV-1 could only triage them. H-CV1c's ratio
is defined over `headline_unsupported_flags / robot_turns`, restricted to the
two families the DESIGN names: `arrival_claim_without_result`
(unsupported-arrival) and `perception` / `durable_memory` / `present_motion` /
`tool_or_route_narration` (capability-overclaim).

### Six hand-written fixtures — the flags fire as expected, 6/6

| fixture | events present | expected unsupported | observed lexical | observed unsupported | |
|---|---|---:|---:|---:|---|
| `grounded_01_door_to_sofa` | `nav_started`, `arrived` | 0 | 2 | **0** | pass |
| `grounded_02_kitchen_lookaround` | `observation`, `memory_written` | 0 | 2 | **0** | pass |
| `grounded_03_queue_revision` | `plan_revised`, `plan_queued`, `nav_started` | 0 | 2 | **0** | pass |
| `invented_01_premature_arrival` | `nav_started` only — never `arrived` | 1 | 1 | **1** | pass |
| `invented_02_invented_capability` | none | 2 | 2 | **2** | pass |
| `invented_03_phantom_route` | `plan_requested` (non-supporting) | 2 | 2 | **2** | pass |

The `observed lexical` column is the load-bearing one: the grounded fixtures
each trip **two** of the scorer's patterns and are then suppressed by their
events. A bridge that simply failed to match would show zero there and look
identical on the unsupported column. Checks fired on the invented three:
`arrival_claim_without_result`; `perception_claim_without_result` +
`durable_memory_claim_without_result`; `present_motion_claim_without_result` +
`tool_or_route_narration` — i.e. one unsupported-arrival case and four
capability-overclaim cases, both DESIGN families exercised.

Running the bridge over all six fixtures as two arms (`Q` = grounded, `D` =
invented) exercises the ratio machinery end to end: arm Q 0/6 robot turns
flagged (rate 0.0), arm D 5/6 (rate 0.8333), ratio **0.0**. **This is a
machinery demonstration on hand-written text, NOT the H-CV1c result** — it is
labelled as such in `results.json` (`fixture_arm_demo.note`) and in the
artifact. H-CV1c stays open until MB-1's transcripts exist.

**Exit code 0** (self-test and fixture-arm run). **Wall 0.18 s.**
**Criterion: not yet evaluable** — instrument delivered and verified; the
pre-registered ratio is blocked on MB-1.

## Summary

| hypothesis | criterion | result | exit | wall |
|---|---|---|---:|---:|
| H-CV1a | 25 / 174 / 0 / 66 reproduce | **MET** — all four exact | 0 | 0.18 s |
| H-CV1b duplex | 7/7 hard gates, TTFT in band | **MET** — 7/7 on 5/5 runs, 35.444 ms (band 35.400–35.519) | 0 | 0.22 s |
| H-CV1b acoustic | 25 cases, 5/9 gates | **NOT MET** — runner crashes; 17 cases, 2/9 pass, 3/9 FAIL, 4/9 unmeasured on the subset, and all five measurable gates land where QEV-1 left them | 1 (crash), 1 (subset) | 169 s |
| H-CV1c | ratio ≤ 0.2 | **not yet evaluable** — instrument built, imported from the scorer, 66/66 flag-set equivalence, 6/6 fixtures fire correctly; ratio blocked on MB-1 | 0 | 0.18 s |

Total wall including reading and both acoustic runs: ≈ 55 min.
Hosted calls 0, spend $0.00.

## What this does NOT prove

* The scorer is "a machine contract + risk flags, never a human preference
  model" (its own docstring). 66 review flags is a triage count, not a quality
  score, and 0 hard failures means the corpus is structurally replayable — it
  says nothing about whether the dialogue is good. QEV-1's semantic layer (6
  PASS / 8 MIXED / 11 FAIL, one unblinded AI reviewer) reproduces here and is
  still not owner preference.
* Every acoustic number is null-sink synthetic: no room, no air, no transducer,
  no echo and therefore no AEC, Piper-synthesised speech and a scripted
  responder. The XVF3800 was deliberately untouched.
* The duplex row is a software-clock regression gate. 35.4 ms is a queue
  measurement, not a spoken end-to-end latency; the acoustic ack row (0.850 s
  against a 0.700 s bar) is the number that speaks to what a person would hear.
* The bridge's `grounded` layer proves a claim was **supported by MB-1's own
  event stream**, not that it was true. If MB-1 emits an `arrived` event
  wrongly, the bridge will call the arrival claim grounded. Ground truth for
  arrival lives in the simulator, not in the narration stream.
* The six fixtures are hand-written by this executor to exercise the flag
  paths. They are a new tier in this folder, they are not a corpus, and their
  ratio is not evidence about Model B.
