# conv-bench-1 (CONV-1) — how to reproduce

Conversation rows for the 2026-08-29 wave: duplex timing gates and corpus
grounding, before and after Model B. `DESIGN.md` is frozen and holds the
criteria; `RESULTS.md` holds what ran; `VERDICT.md` is Fable's.

Everything here runs offline. **No hosted calls, $0.00.** The only step that
touches audio is the acoustic loop, and it creates its own PipeWire **null
sinks** — the reSpeaker XVF3800 is never opened.

## Everything at once

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
.parcel/bin/python research/20260829/conv-bench-1/run.py --all
```

Writes `results.json` here and per-suite artifacts under `results/`, stdout and
stderr under `logs/`. Takes about a second, because the acoustic step defaults
to `--acoustic reuse` (it reads the recorded artifact rather than re-measuring).

`run.py` sets `PARCEL_LATENCY_LEDGER` and `PARCEL_MEMORY_PATH` into scratch and
strips `TMPDIR` for every child, so it cannot dirty `evals/` or touch the
owner's memory store. Use `--only cv1a`, `--only cv1b`, `--only cv1c` to run one
hypothesis.

## One at a time

```bash
# H-CV1a — the captured 25-thread corpus, the QEV-1 recipe of record
.parcel/bin/python -m evals.companion.realtime_convo_v1.score_corpus \
  --review evals/companion/realtime_convo_v1/reviews/20260824-unblinded-ai-review.json \
  --require-review \
  --output research/20260829/conv-bench-1/results/cv1a-corpus-reviewed.json

# H-CV1b — scripted duplex. NOTE the flag is --out (a directory), not --output.
PARCEL_LATENCY_LEDGER=research/20260829/conv-bench-1/results/duplex/latency-ledger.jsonl \
.parcel/bin/python -m evals.companion.duplex_v1.run_duplex_v1 \
  --out research/20260829/conv-bench-1/results/duplex

# H-CV1c — the bridge, over the six fixtures
.parcel/bin/python research/20260829/conv-bench-1/bridge.py --self-test \
  --output research/20260829/conv-bench-1/results/cv1c-self-test.json
```

### The acoustic loop — read this before running it

```bash
source scripts/env-audio.sh          # puts libportaudio on the path, no root
wpctl status > /tmp/wpctl-before.txt # rule (5): capture the graph first
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 \
  --output research/20260829/conv-bench-1/results/acoustic/<name>.json
wpctl status | diff /tmp/wpctl-before.txt -   # only the wpctl client row may differ
```

or `run.py --all --acoustic run`. Takes 85–140 s. Exit **0** = every frozen gate
and teardown pass, **1** = a completed but red/invalid report, **2** = the rig
is unavailable (missing `pw-cli`/`pw-play`/`pw-record`, or no PipeWire daemon).

**On this host the full suite does not complete.** It crashes with an uncaught
`ValueError` inside the barge-in family — `robot_only_envelope` does not reject
a negative alignment offset (`run_acoustic_loop_v1.py:241-244`, called from
:502) — and writes no report. The defect is timing-dependent, it lives in
`evals/` which this card must not edit, and it is written up in `RESULTS.md`.
The three families that path never touches do complete:

```bash
.parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1 \
  --families endpointing,duplex,prosody \
  --output research/20260829/conv-bench-1/results/acoustic/acoustic-loop-v1-cv1b-subset.json
```

Two harness writes land inside `evals/` no matter what you pass, and both are
recorded in `RESULTS.md`: `run_duplex_v1` appends to `evals/latency/ledger.jsonl`
unless `PARCEL_LATENCY_LEDGER` is set, and the acoustic runner writes PCM
scratch to `evals/companion/acoustic_loop_v1/results/.tmp` (gitignored; deleted
on its success path, left behind by the crash). Check `git status --porcelain
evals/` is empty when you are done.

## The MB-1 transcript shape

`bridge.py --transcripts <path>` reads **JSONL**, one turn per line, from a file
or from every `*.jsonl` in a directory. This is the shape MB-1
(`research/20260829/model-b-narration-1/`) is expected to emit:

```json
{"scenario_id": "door-sofa-keys-03",
 "arm": "Q",
 "turn_index": 3,
 "role": "robot",
 "text": "We're there — the sofa is right in front of me.",
 "events_so_far": [{"kind": "nav_started", "t": 0.4},
                   {"kind": "arrived", "t": 9.7, "goal": "sofa"}]}
```

| field | type | meaning |
|---|---|---|
| `scenario_id` | string | the scenario; arms Q and D must share it to be comparable |
| `arm` | string | `Q` (Model B narration) or `D` (the direct baseline). H-CV1c's ratio is `Q ÷ D`; any other arm label is scored and reported but not put in the ratio |
| `turn_index` | int | position in the thread, owner and robot turns numbered together |
| `role` | `"owner"` / `"robot"` | only robot turns are scored |
| `text` | string | exactly what was said, curly apostrophes fine — the scorer's own `’`→`'` normalisation is applied |
| `events_so_far` | list | every narration event true **at the moment this turn was spoken**, in order. Each item is a bare kind string or an object with `kind` (`type` / `event` also accepted); extra fields are carried but ignored |

Event kinds that ground a claim (`SUPPORTING_EVENTS` in `scorer_bridge.py`):

| scorer check | grounded by |
|---|---|
| `arrival_claim_without_result` | `arrived` |
| `present_motion_claim_without_result` | `nav_started`, `nav_progress`, `moving` |
| `perception_claim_without_result` | `observation`, `detection` |
| `durable_memory_claim_without_result` | `memory_written` |
| `tool_or_route_narration` | `tool_result`, `nav_started`, `plan_queued`, `plan_revised` |

Anything else (`user_utterance`, `plan_requested`, …) is carried and does not
ground anything. If MB-1 settles on different names, change that one table —
nothing else in the bridge knows about event vocabulary.

Output: `h_cv1c.ratio_q_over_d`, with `pre_registered_bar: "<= 0.2"` and `met`
already computed, plus per-arm `lexical_flags` / `unsupported_flags` /
`headline_flag_rate_per_robot_turn` and every finding.

## Why there are two flag layers

`scorer_bridge.py` **imports** `RISK_PATTERNS` and `REFUSAL_PATTERN` from
`evals/companion/realtime_convo_v1/score_corpus.py`, so it cannot drift from the
QEV-1 instrument. `run.py` proves this every run by pushing the captured
25-thread corpus through the bridge and diffing against the scorer's own
findings: 66 flags, on the same turns, identical set.

* **`lexical`** — the scorer's report-only triage, unchanged. On the captured
  corpus this *is* the 66.
* **`grounded`** — the subset of those with no supporting event by that turn.
  The captured corpus has no event stream, so all 66 of its flags are
  unsupported by definition; that is precisely the gap MB-1 is supposed to
  close, and the gap H-CV1c measures.

A grounded claim is one MB-1's own event stream supported. It is **not**
necessarily true — see `does_not_prove` in `RESULTS.md`.

## Files

| path | what |
|---|---|
| `DESIGN.md` | Fable's frozen hypotheses and criteria |
| `RESULTS.md` | what ran, exact numbers, met / not met, exit codes, wall |
| `run.py` | `--all` orchestrator → `results.json` |
| `scorer_bridge.py` | H-CV1c: the QEV-1 flag logic over MB-1-shaped transcripts |
| `bridge.py` | entry-point alias for `scorer_bridge.py` |
| `fixtures/*.jsonl` | six hand-written transcripts, 3 grounded / 3 invented |
| `results/cv1a-corpus-*.json` | corpus scorer artifacts (reviewed and bare) |
| `results/duplex/` | duplex reports, its ledger, and the latency row the runner leaked into `evals/` before it was redirected |
| `results/acoustic/` | the subset acoustic report |
| `results/cv1c-*.json` | bridge self-test and the fixture-arm machinery demo |
| `logs/` | stdout/stderr per run, plus `wpctl-before.txt` / `wpctl-after.txt` |
| `results.json` | the roll-up `run.py --all` writes |

## Standing constraints honoured

`TMPDIR` unset; no pytest (so no guard wrapper needed); no git writes; no
hosted calls; `evals/`, `src/`, `tests/` and other research folders unmodified
(`git status --porcelain evals/` empty at close); PipeWire null sinks only and
`/dev/bus/usb` never opened, with `wpctl` before/after identical; place names in
the fixtures checked against the NAV held-out scene id by importing the constant
rather than naming it; the fixtures are a new tier in this folder and re-pin no
frozen corpus or digest (E3).
