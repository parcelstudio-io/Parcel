# FL-1 — learning "chuckle if it was funny" and "look back when lost" from the owner

Executor: Opus (parcel-0e session). Design: `DESIGN.md` (Fable, frozen) +
`AMENDMENTS.md` (Fable, pre-run, **binding**). Results: `RESULTS.md`.
Verdict: Fable writes `VERDICT.md`; nothing here is a verdict.

Evidence tier: `desktop-sim`. Physical motion remains **NO-GO**; nothing in this
folder gains authority, is imported by product code, or touches `src/`.

## Reproduce

```bash
~/.cache/parcel-0e/venv/bin/python research/20260828/feedback-learning-1/run.py \
    --all --seed 20260828          # -> results.json  (~25 min, 1 GPU, <= 6 GB)
```

Sub-hypotheses can be run alone (each writes its own `fl1<x>.json`):

```bash
cd research/20260828/feedback-learning-1
~/.cache/parcel-0e/venv/bin/python run.py --only a --seed 20260828   # policy C   (GPU, ~20 min)
~/.cache/parcel-0e/venv/bin/python run.py --only b --seed 20260828   # bandit     (CPU, ~5 s)
~/.cache/parcel-0e/venv/bin/python run.py --only c --seed 20260828   # look-back  (CPU, ~5 s)
~/.cache/parcel-0e/venv/bin/python run.py --only d --seed 20260828   # REINFORCE  (GPU, needs a first)
~/.cache/parcel-0e/venv/bin/python run.py --only e --seed 20260828   # verbal fb  (CPU, ~10 s)
~/.cache/parcel-0e/venv/bin/python samples.py                        # sample_owners.txt
```

`--quick` on any of them runs a smoke-sized version (minutes, not headline numbers).

## Files

| file | what it is |
|---|---|
| `owners.py` | synthetic owner sampler: Beta-mixture humour taste (F1), preferred check-in latency + annoyance (F6), the laugh-detector / self-echo model (F5), the per-category history state (F2) |
| `fl_world.py` | FL-1 episodes built on BM-1's `worldsim.generate_episode` (READ ONLY) with FL-1 owners injected; the FL-1 42-channel frame schema; the anticipatory-chuckle relabel; loss-event extraction |
| `data.py` | owner books -> concatenated frame corpora + joke records |
| `models.py` | `BehaviorFormer` — BM-1 arm C's architecture (6 layers, d=256, 4 heads, ctx 128), FL-1's own retrain |
| `engine.py` | joke tables, the closed-loop decision-rule runner, observation regimes, the Beta/Thompson/mixture/debias rules, policy-C training and probing |
| `metrics.py` | F1, false-chuckle (both denominators), expected-reward regret, bootstrap CIs |
| `fl1a.py` … `fl1e.py` | one sub-hypothesis each |
| `run.py` | orchestration -> `results.json` |
| `samples.py` / `sample_owners.txt` | six sampled owners, one joke trace, one loss trace |

Artifacts (checkpoints, per-owner online heads) live under `~/.cache/parcel-0e/fl1/`
and are research artifacts only — never a product checkpoint.

## What is imported from where

* BM-1 `research/20260828/behavior-model-1/worldsim.py` is imported READ ONLY via
  `sys.path`: the episode generator, the frame channel vocabularies, the phrase
  tables, the scripted teacher, the cue-detector noise, the act vocabulary, the
  scenario families and the M2 windows. Nothing in that folder is written.
* No product code (`src/`, `gateway/`) is imported or executed. No hosted API calls.
