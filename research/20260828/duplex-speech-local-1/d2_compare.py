#!/usr/bin/env python
"""DS-1 (AMENDMENTS.md D2) — stock vs act-stream variants, back to back in ONE
process so the comparison is controlled for GPU contention.

Amended bar: step-time p99 delta <= 5 ms vs stock, with RTF still <= 1.0.

Loads each variant, measures, frees, moves on. Records a host snapshot per
variant so the verifier can see whether the card was quiet for each.

    PYTHONPATH=~/.cache/parcel-0e/ds1/moshi-act/moshi \
      HF_HOME=~/.cache/parcel-0e/hf NO_TORCH_COMPILE=1 \
      ~/.cache/parcel-0e/venv-moshi/bin/python d2_compare.py --audio X.mp3
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAME_MS = 80.0


def pct(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100.0 * (len(s) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--seconds", type=float, default=80.0)
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--warmup", type=int, default=16)
    ap.add_argument("--variants", default="stock,shared,perstep")
    ap.add_argument("--out", default=str(HERE / "d2_compare.json"))
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))
    import act_stream_run as A
    import numpy as np
    import sphn
    import torch
    from moshi.models import LMGen, loaders
    from run import host_snapshot

    dev = torch.device("cuda")
    ci = loaders.CheckpointInfo.from_hf_repo("kyutai/moshiko-pytorch-bf16")
    mimi = ci.get_mimi(device=dev)
    fs = int(mimi.sample_rate / mimi.frame_rate)
    pcm, _ = sphn.read(args.audio, sample_rate=mimi.sample_rate)
    pcm = pcm[0] if pcm.ndim > 1 else pcm
    need = int(args.seconds * mimi.sample_rate)
    if len(pcm) < need:
        pcm = np.tile(pcm, int(np.ceil(need / len(pcm))))
    x = torch.from_numpy(pcm[:need].astype(np.float32))[None, None].to(dev)
    chunks = [c for c in x.split(fs, dim=2) if c.shape[-1] == fs]

    out: dict = {
        "note": "AMENDMENTS.md D2 measured act-stream cost, one process, back to back",
        "moshi_git_rev": "e6a55d2722a65870ef52a6c9f6ecfc0e90f38362",
        "frame_budget_ms": FRAME_MS,
        "bar_p99_delta_le_5ms": None,
        "variants": {},
    }

    for name in args.variants.split(","):
        over = A.VARIANTS[name]
        snap0 = host_snapshot(f"{name}_start")
        torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        lm = loaders.get_moshi_lm(
            ci.moshi_weights, device=dev, dtype=torch.bfloat16,
            lm_kwargs_overrides=over)
        lm.eval()
        lm_gen = LMGen(lm, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)
        n_params = sum(p.numel() for p in lm.parameters())

        step_ms, acts = [], []
        with torch.no_grad(), mimi.streaming(1), lm_gen.streaming(1):
            first = True
            for i, ch in enumerate(chunks):
                t = time.perf_counter()
                codes = mimi.encode(ch)
                if first:
                    lm_gen.step(codes); first = False
                tok = lm_gen.step(codes)
                if tok is not None:
                    if over.get("act_index") is not None:
                        acts.append(int(tok[0, 1 + A.ACT_INDEX, 0].item()))
                    _ = mimi.decode(tok[:, 1:1 + 8])
                torch.cuda.synchronize()
                dt = (time.perf_counter() - t) * 1e3
                if i >= args.warmup:
                    step_ms.append(dt)
                if len(step_ms) >= args.steps:
                    break
        p50, p99 = pct(step_ms, 50), pct(step_ms, 99)
        out["variants"][name] = {
            "lm_params": n_params,
            "param_delta_vs_stock": None,
            "n_steps": len(step_ms),
            "step_ms_p50": round(p50, 3),
            "step_ms_p90": round(pct(step_ms, 90), 3),
            "step_ms_p99": round(p99, 3),
            "step_ms_max": round(max(step_ms), 3),
            "rtf_p50": round(p50 / FRAME_MS, 4),
            "rtf_p99": round(p99 / FRAME_MS, 4),
            "steps_over_80ms": sum(1 for v in step_ms if v > FRAME_MS),
            "peak_gpu_alloc_gib": round(torch.cuda.max_memory_allocated() / 2**30, 3),
            "n_distinct_act_tokens": len(set(acts)) if acts else None,
            "act_token_range": [min(acts), max(acts)] if acts else None,
            "host_start": snap0,
            "host_end": host_snapshot(f"{name}_end"),
        }
        print(f"[d2] {name:8} p50={p50:7.2f} p99={p99:7.2f} params={n_params:,}", flush=True)
        del lm, lm_gen
        gc.collect(); torch.cuda.empty_cache()

    v = out["variants"]
    if "stock" in v:
        s = v["stock"]
        for name, row in v.items():
            row["param_delta_vs_stock"] = row["lm_params"] - s["lm_params"]
            row["p50_delta_ms"] = round(row["step_ms_p50"] - s["step_ms_p50"], 3)
            row["p99_delta_ms"] = round(row["step_ms_p99"] - s["step_ms_p99"], 3)
            row["bar_p99_delta_le_5ms"] = bool(row["p99_delta_ms"] <= 5.0)
            row["bar_rtf_le_1"] = bool(row["rtf_p99"] <= 1.0)
        if "shared" in v:
            out["bar_p99_delta_le_5ms"] = v["shared"]["bar_p99_delta_le_5ms"]
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: {kk: vv for kk, vv in r.items() if not kk.startswith("host")}
                      for k, r in v.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
