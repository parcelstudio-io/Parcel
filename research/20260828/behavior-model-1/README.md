# BM-1 — trainable full-duplex behavior model (reproduction)

`DESIGN.md` is the frozen pre-registration, `AMENDMENTS.md` the POST-START
review, `RESULTS.md` the executor's numbers, `VERDICT.md` Fable's.
Evidence tier: `desktop-sim (synthetic token world, no physics/sensors)`.
No hosted API calls; no product caller is exercised; motion stays **NO-GO**.

```bash
V=~/.cache/parcel-0e/venv/bin/python                 # py3.14, torch 2.13+cu130
cd research/20260828/behavior-model-1
$V worldsim.py --seed 20260828 --workers 32 --train-episodes 3000  # ~5 s -> splits.json, sample_episodes.txt, ~/.cache/parcel-0e/bm1/data
HF_HOME=~/.cache/parcel-0e/hf $V run.py --arm all --seed 20260828  # arms -> results.json, results-<arm>.json
$V extras.py && $V report.py                          # A8 slices + criterion -> RESULTS.md
```

Single arm: `run.py --arm C` (also `ref,A,Aprime,E,B,D`). Checkpoints and logs
live under `~/.cache/parcel-0e/bm1/{ckpt,logs}`. A/B/C/E reproduce exactly at a
fixed seed (torch deterministic flags set); arm D's LoRA run is not guaranteed
bit-reproducible — see RESULTS.md §2.
