# DS-1 — reproduce

Kyutai Moshi as a local full-duplex backbone: does it run in real time here
(H-DS1a), is a Parcel act stream a cheap addition (H-DS1b), and does it fit a
Jetson AGX Orin (H-DS1c)? Pre-registered in `DESIGN.md`, amended by
`AMENDMENTS.md`; numbers in `RESULTS.md`; verdict is Fable's.

Evidence tier: **`desktop-local-model`** — proposed, not registered in
`research/README.md`.

## 0. Environment (once)

The system python has no `ensurepip`, so pip is bootstrapped from the project
venv. **Python 3.14 is supported by `moshi` 0.2.13** (`>=3.10,<3.15`).

```bash
/usr/bin/python3.14 -m venv --without-pip ~/.cache/parcel-0e/venv-moshi
/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python -m pip \
  --python ~/.cache/parcel-0e/venv-moshi/bin/python install pip

VP=~/.cache/parcel-0e/venv-moshi/bin/python
$VP -m pip install torch --index-url https://download.pytorch.org/whl/cu128

# moshi's upper pins (numpy<2.3, safetensors<0.8, torch<2.10) have NO cp314
# wheels; --only-binary avoids a source build that fails without python3.14-dev.
$VP -m pip install --only-binary=:all: \
  numpy safetensors huggingface-hub einops sentencepiece sphn tqdm transformers

# pinned source; sounddevice deliberately omitted (needs PortAudio, unused here)
git clone https://github.com/kyutai-labs/moshi.git ~/.cache/parcel-0e/ds1/moshi-src
git -C ~/.cache/parcel-0e/ds1/moshi-src checkout e6a55d2722a65870ef52a6c9f6ecfc0e90f38362
$VP -m pip install --no-deps -e ~/.cache/parcel-0e/ds1/moshi-src/moshi
```

Weights (~15.4 GB, ~390 s):

```bash
HF_HOME=~/.cache/parcel-0e/hf $VP -c \
 "from huggingface_hub import snapshot_download; \
  snapshot_download('kyutai/moshiko-pytorch-bf16', max_workers=8)"
```

**`NO_TORCH_COMPILE=1` is required on this host** — Triton cannot JIT without
`python3.14-dev` headers. It disables `torch.compile` on three small elementwise
helpers, so timings are a conservative upper bound; CUDA graphs still apply.

## 1. H-DS1a — streaming step time (D1 bars)

```bash
cd research/20260828/duplex-speech-local-1
AUDIO=~/.cache/parcel-0e/ds1/moshi-src/data/sample_fr_hibiki_crepes.mp3

# gate: refuses to start until >= 26 GB is free (logs every poll)
$VP gpu_wait.py --need-mib 26624

HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 $VP run.py \
  --audio "$AUDIO" --seconds 200 --min-steps 2000 --dtype bf16 --out results.json
```
-> `results.json`: p50/p90/p99, RTF, steps over 80 ms, peak memory, and the D1
host snapshots (GPU util, co-residents, load) at start and end.

**Run it with the card to itself.** Under three co-resident parcel-0e jobs the
same stock model measured 95 ms p50 instead of 42 ms — the step time is a
property of the model *plus* what else is on the GPU.

## 2. Phase split and the Orin extrapolation

```bash
HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 $VP profile_breakdown.py --audio "$AUDIO" --steps 200
HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 $VP edge_extrapolate.py
$VP candidates.py
```
-> `profile_breakdown.json`, `edge_extrapolation.json`, `candidates.json`.
`edge_extrapolate.py` measures achievable bandwidth (40-iteration warmup — a
short one measures the GPU in P8 and underreports by ~2x) and validates that
decode is bandwidth bound before projecting.

## 3. H-DS1b — the act stream

Parameter delta from `meta`-device builds of the real architecture:

```bash
$VP param_delta.py        # first pass: shared vs per-step vs extra-head
```

The working patch (act stream as one more generated codebook):

```bash
cp -r ~/.cache/parcel-0e/ds1/moshi-src ~/.cache/parcel-0e/ds1/moshi-act
# apply the act-stream patch to moshi/moshi/models/{lm,loaders}.py, then:
git -C ~/.cache/parcel-0e/ds1/moshi-act diff --numstat   # 68 added / 4 removed

ACT=~/.cache/parcel-0e/ds1/moshi-act/moshi
PYTHONPATH=$ACT HF_HOME=~/.cache/parcel-0e/hf $VP act_param_delta.py

# measured timing: stock vs act stream, same loop, back to back
for v in stock shared perstep; do
  PYTHONPATH=$ACT HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 \
    $VP act_stream_run.py --variant $v --audio "$AUDIO" --seconds 60 --min-steps 600
done
```
-> `act_param_delta.json`, `act_stream_{stock,shared,perstep}.json`.

The 12.5 Hz <-> 10 Hz act-clock contract, with dropped tokens counted:

```bash
$VP resample_contract.py   # imports the real ActTokenCodec from src/ (read-only)
```

## 4. D3 — co-resident budget

```bash
PYTHONPATH=$ACT HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 \
  $VP d3_coresident.py --audio "$AUDIO" --steps 400
```
-> `d3_coresident.json`: step time with an AST laughter detector (86,594,063
params) and a 2x256 GRU resident on the same card.

## 5. D4 — corpus, tokens, GPU-hours

```bash
$VP training_plan.py --measure-tflops
```
-> `training_plan.json`, reading BM-1's `behavior-model-1/splits.json` for
episode counts. Note `moshi-finetune` **cannot be installed here** (it pins
`torch==2.6`, which has no cp314 wheel), so the GPU-hour figure is an estimate
scaled from a matmul microbenchmark, not a measured training run.

## Notes

- Nothing here writes to `src/`, `tests/`, `gateway/`, or `logs/`;
  `resample_contract.py` imports `src/parcel_robot/duplex/` read-only.
- No hosted API calls; $0 spent.
- The owner's live stack (`:8080`, `:8765`, `/tmp/parcel_sim.sock`) and
  `parcel_memory.sqlite3` are untouched.
- All model/venv/weight state lives under `~/.cache/parcel-0e/`.
