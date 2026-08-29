#!/usr/bin/env python
"""DS-1 H-DS1b MEASURED (AMENDMENTS.md D2) — run the act-stream variants
through the SAME streaming loop as run.py and report the step-time delta.

The patched moshi tree at ~/.cache/parcel-0e/ds1/moshi-act adds a Parcel act
stream as one more generated codebook. The stock 7B checkpoint still loads; only
the act modules are randomly initialised (`_materialize_act_modules`).

Amended bar (D2): step-time p99 delta <= 5 ms with RTF still <= 1.0.

    PYTHONPATH=~/.cache/parcel-0e/ds1/moshi-act/moshi \
      ~/.cache/parcel-0e/venv-moshi/bin/python act_stream_run.py --variant shared
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAME_HZ = 12.5
FRAME_MS = 80.0

# Parcel act vocabulary (src/parcel_robot/duplex/act_codec.py); DESIGN.md budgets ~90.
ACT_CARD = 90

# Stock moshiko: n_q=16 (8 moshi audio + 8 user audio), dep_q=8.
# The act stream is inserted as the LAST GENERATED stream (AMENDMENTS.md D2),
# i.e. depformer step 8, which is emb index 8; the user's 8 audio codebooks
# shift from emb[8..15] to emb[9..16].
ACT_INDEX = 8
STOCK_DELAYS = [0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1]
# one text + 8 moshi audio + [act] + 8 user audio; act delay 0 (emit immediately)
ACT_DELAYS = STOCK_DELAYS[:9] + [0] + STOCK_DELAYS[9:]

VARIANTS = {
    # Shared slice: the act step reuses depformer weight slot 7. mult stays 8,
    # so the entire depth transformer is unchanged.
    "shared": {
        "n_q": 17, "dep_q": 9, "act_card": ACT_CARD, "act_index": ACT_INDEX,
        "delays": ACT_DELAYS,
        "depformer_weights_per_step_schedule": [0, 1, 2, 3, 4, 5, 6, 7, 7],
    },
    # Per-step slice: the act step gets its own depformer weight slot (mult 9).
    "perstep": {
        "n_q": 17, "dep_q": 9, "act_card": ACT_CARD, "act_index": ACT_INDEX,
        "delays": ACT_DELAYS,
    },
    "stock": {},
}


def pct(xs, p):
    s = sorted(xs)
    k = min(len(s) - 1, max(0, round(p / 100.0 * (len(s) - 1))))
    return s[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--min-steps", type=int, default=600)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))
    import numpy as np
    import sphn
    import torch
    from moshi.models import LMGen, loaders

    dev = torch.device("cuda")
    overrides = VARIANTS[args.variant]

    ci = loaders.CheckpointInfo.from_hf_repo("kyutai/moshiko-pytorch-bf16")
    mimi = ci.get_mimi(device=dev)
    t0 = time.time()
    lm = loaders.get_moshi_lm(
        ci.moshi_weights, device=dev, dtype=torch.bfloat16,
        lm_kwargs_overrides=overrides,
    )
    load_s = time.time() - t0
    lm.eval()

    n_params = sum(p.numel() for p in lm.parameters())
    lm_gen = LMGen(lm, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)

    fs = int(mimi.sample_rate / mimi.frame_rate)
    pcm, _ = sphn.read(args.audio, sample_rate=mimi.sample_rate)
    pcm = pcm[0] if pcm.ndim > 1 else pcm
    need = int(args.seconds * mimi.sample_rate)
    if len(pcm) < need:
        pcm = np.tile(pcm, int(np.ceil(need / len(pcm))))
    x = torch.from_numpy(pcm[:need].astype(np.float32))[None, None].to(dev)
    chunks = [c for c in x.split(fs, dim=2) if c.shape[-1] == fs]

    torch.cuda.reset_peak_memory_stats(); torch.cuda.synchronize()
    step_ms, act_tokens = [], []
    n_out = 0
    with torch.no_grad(), mimi.streaming(1), lm_gen.streaming(1):
        first = True
        for i, ch in enumerate(chunks):
            t = time.perf_counter()
            codes = mimi.encode(ch)
            if first:
                lm_gen.step(codes); first = False
            tok = lm_gen.step(codes)
            if tok is not None:
                # tok is [B, dep_q+1, 1]: text, then the generated streams.
                if overrides.get("act_index") is not None:
                    act_tokens.append(int(tok[0, 1 + ACT_INDEX, 0].item()))
                _ = mimi.decode(tok[:, 1:1 + 8])  # audio codebooks only
                n_out += 1
            torch.cuda.synchronize()
            dt = (time.perf_counter() - t) * 1000.0
            if i >= args.warmup:
                step_ms.append(dt)
            if len(step_ms) >= args.min_steps:
                break

    p50, p99 = pct(step_ms, 50), pct(step_ms, 99)
    res = {
        "variant": args.variant,
        "overrides": {k: v for k, v in overrides.items() if k != "delays"},
        "delays_len": len(overrides.get("delays", STOCK_DELAYS)),
        "act_index": overrides.get("act_index"),
        "act_card": overrides.get("act_card"),
        "lm_params": n_params,
        "load_seconds": round(load_s, 2),
        "n_steps": len(step_ms),
        "steps_with_output": n_out,
        "step_ms_p50": round(p50, 3),
        "step_ms_p90": round(pct(step_ms, 90), 3),
        "step_ms_p99": round(p99, 3),
        "step_ms_max": round(max(step_ms), 3),
        "rtf_p50": round(p50 / FRAME_MS, 4),
        "rtf_p99": round(p99 / FRAME_MS, 4),
        "peak_gpu_alloc_gib": round(torch.cuda.max_memory_allocated() / 2**30, 3),
        "n_distinct_act_tokens": len(set(act_tokens)),
        "act_token_min": min(act_tokens) if act_tokens else None,
        "act_token_max": max(act_tokens) if act_tokens else None,
        "act_tokens_in_range": (
            bool(act_tokens and min(act_tokens) >= 0 and max(act_tokens) < ACT_CARD)
            if act_tokens else None
        ),
        "note": (
            "act modules are RANDOMLY INITIALISED — the act tokens are noise. "
            "This measures cost and wiring, never behaviour."
        ),
    }
    out = args.out or str(HERE / f"act_stream_{args.variant}.json")
    Path(out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
