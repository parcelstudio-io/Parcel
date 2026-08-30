# MB-2 — the receipt-typed utterance contract, measured

`DESIGN.md` (Fable, frozen before any run) · `RESULTS.md` (Opus, incremental) ·
`VERDICT.md` (Fable — **not written by this card**).

MB-1 refuted free-form narration: a hosted model handed the plan queue and a
speech act inferred facts nobody had filed (grounding 0.61–0.73, 45
invented-action flags, 1/25 on the keys turn). MB-2 measures the replacement
both verdicts recommended — **the executive emits a typed speech act with
slots, a template renders it, a paraphraser may only reword it, and a
post-condition checker refuses any claim the receipt did not license.**

## Files

| file | what it is |
|---|---|
| `DESIGN.md` | Fable's frozen pre-registration: arms, hypotheses, bars |
| `mb1.py` | the read-only bridge to MB-1's frozen instrument (imported by path, never edited) |
| `contract.py` | the nine speech acts + slots, the template table, the **post-condition checker** |
| `arms.py` | receipt → act mapping, owner-turn → act mapping, the scenario walk (mirrors MB-1's ordering, `IMMEDIATE_RECEIPT_S = 0.6`) |
| `run.py` | the runner: arm T, arm T+P, the shadow arm, the blind flag audit, the naturalness judge |
| `sensitivity.py` | post-hoc re-scoring of the stored candidates (0 model calls): what a claim-preserving checker would have cost |
| `prompts/paraphrase_v1.txt` | the paraphraser's system prompt, **frozen 2026-08-30T00:21Z, before any T+P row** |
| `prompts/naturalness_judge_v1.txt` | the judge's system prompt, **frozen at the same moment**, report-only |
| `results.json` | the merged run record (arms, references, judge, host rows) |
| `results/T.json`, `results/TP.json` | per-arm aggregates + every turn, template, candidate and check result |
| `results/naturalness.json` | every judged pair, blind order recorded |
| `results/sensitivity.json` | the 23 turns whose headline claim MB-1's matcher does not recognise |
| `results/adjudication-P-raw.json` | MB-1's frozen blind adjudication prompt over the shadow arm's flags |
| `transcripts/*.jsonl` | CONV-1's JSONL shape (`scenario_id / arm / turn_index / role / text / events_so_far`) |

## Reproduce

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
export OPENBLAS_NUM_THREADS=32

# everything: arm T, then arm T+P (starts and stops its own llama-server), then
# the report-only judge.  ~15 minutes, $0.00, no hosted call of any kind.
.parcel/bin/python research/20260829/model-b-contract-2/run.py --all --seed 20260829

# arm T alone — deterministic, no model, no network, ~0.1 s
.parcel/bin/python research/20260829/model-b-contract-2/run.py --arm T --seed 20260829
```

`--arm T+P` runs the paraphrase arm alone; `--limit N` takes the first N
scenarios for a smoke run; `--no-judge` skips the report-only preference pass;
`--judge-pairs N` sets its sample size.

```bash
# the post-hoc sensitivity row (no model, no network, ~1 s)
.parcel/bin/python research/20260829/model-b-contract-2/sensitivity.py
```

## Host discipline

The only model is **local**: `Qwen2.5-7B-Instruct-Q4_K_M` on a `llama-server`
this card starts on **:8093** (`third_party/llama.cpp-bin/llama-b10235`, a CPU
build) and kills **by process group** on every exit path, including
`SystemExit` and an unhandled exception. Nothing here calls a hosted provider —
the only network client in `run.py` is `urllib` against `127.0.0.1:8093`. The
owner's stack on `:8765`, the foreign server on `:8080` and
`parcel_memory.sqlite3` are never touched.
