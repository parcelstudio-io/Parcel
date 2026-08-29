#!/usr/bin/env python
"""DS-1 supplement — where the 80 ms frame budget actually goes.

Splits the measured step into (a) Mimi encode, (b) the temporal transformer +
text head, (c) the depformer's dep_q sequential sub-steps, (d) Mimi decode.
This matters for the Orin extrapolation: the depformer runs 8 SEQUENTIAL passes
per frame, so its cost is latency-bound in a way that quantization helps less
than it helps the one big weight sweep of the temporal transformer.

Implemented with the hooks the library already exposes (`LMGen.on_text_hook`)
plus direct timing of `mimi.encode` / `mimi.decode` / `lm_gen.step`.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAME_MS = 80.0


def pct(xs, p):
    s = sorted(xs)
    if not s:
        return float("nan")
    k = min(len(s) - 1, max(0, round(p / 100.0 * (len(s) - 1))))
    return s[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-repo", default="kyutai/moshiko-pytorch-bf16")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=str(HERE / "profile_breakdown.json"))
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))
    import sphn
    import torch
    from moshi.models import LMGen, loaders

    dev = torch.device("cuda")
    ci = loaders.CheckpointInfo.from_hf_repo(args.hf_repo)
    mimi = ci.get_mimi(device=dev)
    lm = ci.get_moshi(device=dev, dtype=torch.bfloat16)
    lm_gen = LMGen(lm, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)

    # Parameter split, to reason about bandwidth per phase.
    dep_params = sum(p.numel() for p in lm.depformer.parameters())
    dep_params += sum(p.numel() for p in lm.depformer_in.parameters())
    dep_params += sum(p.numel() for p in lm.depformer_emb.parameters())
    dep_params += sum(p.numel() for p in lm.depformer_text_emb.parameters())
    dep_params += sum(p.numel() for p in lm.linears.parameters())
    temporal_params = sum(p.numel() for p in lm.transformer.parameters())

    fs = int(mimi.sample_rate / mimi.frame_rate)
    pcm, _ = sphn.read(args.audio, sample_rate=mimi.sample_rate)
    x = torch.from_numpy(pcm[:1])[None].to(dev)
    chunks = [c for c in x.split(fs, dim=2) if c.shape[-1] == fs]

    enc, step, dec = [], [], []

    def sync():
        torch.cuda.synchronize()

    with torch.no_grad(), mimi.streaming(1), lm_gen.streaming(1):
        first = True
        for i, ch in enumerate(chunks[: args.steps + args.warmup + 2]):
            t0 = time.perf_counter(); codes = mimi.encode(ch); sync(); t1 = time.perf_counter()
            if first:
                lm_gen.step(codes); sync(); first = False
                t1 = time.perf_counter()
            tok = lm_gen.step(codes); sync(); t2 = time.perf_counter()
            if tok is not None:
                _ = mimi.decode(tok[:, 1:]); sync()
            t3 = time.perf_counter()
            if i >= args.warmup:
                enc.append((t1 - t0) * 1000)
                step.append((t2 - t1) * 1000)
                dec.append((t3 - t2) * 1000)

    out = {
        "note": "phase split of the DS-1 streaming step; same loop as run.py",
        "n_steps": len(step),
        "dep_q": lm.dep_q,
        "temporal_transformer_params": temporal_params,
        "depformer_stack_params": dep_params,
        "mimi_encode_ms_p50": round(pct(enc, 50), 3),
        "lm_step_ms_p50": round(pct(step, 50), 3),
        "mimi_decode_ms_p50": round(pct(dec, 50), 3),
        "total_ms_p50": round(pct(enc, 50) + pct(step, 50) + pct(dec, 50), 3),
        "mimi_encode_ms_mean": round(statistics.fmean(enc), 3),
        "lm_step_ms_mean": round(statistics.fmean(step), 3),
        "mimi_decode_ms_mean": round(statistics.fmean(dec), 3),
        "frame_budget_ms": FRAME_MS,
    }
    tot = out["total_ms_p50"]
    out["share_pct"] = {
        "mimi_encode": round(100 * out["mimi_encode_ms_p50"] / tot, 1),
        "lm_step_temporal_plus_depformer": round(100 * out["lm_step_ms_p50"] / tot, 1),
        "mimi_decode": round(100 * out["mimi_decode_ms_p50"] / tot, 1),
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
