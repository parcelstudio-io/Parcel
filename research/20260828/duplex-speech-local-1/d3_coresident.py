#!/usr/bin/env python
"""DS-1 (AMENDMENTS.md D3) — co-resident budget.

Moshi will not have the GPU to itself on the robot. This measures the streaming
step time with the two companions the amendment names resident on the same card:

  * a laughter detector — AST (Audio Spectrogram Transformer, ~87 M params),
    the model class used for laughter/non-verbal-vocalisation detection, run on
    each frame's audio;
  * a 2 x 256 GRU ticking at 10 Hz (the reactive/behaviour head).

Reports the step time, the fraction of the 80 ms frame consumed, and the RTF at
which the whole stack fits.

    PYTHONPATH=~/.cache/parcel-0e/ds1/moshi-act/moshi \
      ~/.cache/parcel-0e/venv-moshi/bin/python d3_coresident.py --audio X.mp3
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAME_MS = 80.0
AST_REPO = "MIT/ast-finetuned-audioset-10-10-0.4593"


def pct(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100.0 * (len(s) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--out", default=str(HERE / "d3_coresident.json"))
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))
    import numpy as np
    import sphn
    import torch
    from moshi.models import LMGen, loaders
    from torch import nn

    dev = torch.device("cuda")
    res: dict = {"note": "AMENDMENTS.md D3 co-resident budget", "frame_budget_ms": FRAME_MS}

    # --- companions -------------------------------------------------------
    ast = None
    try:
        from transformers import ASTForAudioClassification
        ast = ASTForAudioClassification.from_pretrained(AST_REPO, dtype=torch.float16)
        ast = ast.to(dev).eval()
        res["ast_model"] = AST_REPO
        res["ast_params"] = sum(p.numel() for p in ast.parameters())
    except Exception as exc:  # noqa: BLE001
        res["ast_error"] = f"{type(exc).__name__}: {exc}"

    gru = nn.GRU(input_size=64, hidden_size=256, num_layers=2, batch_first=True)
    gru = gru.to(dev).eval()
    res["gru_params"] = sum(p.numel() for p in gru.parameters())
    gru_h = torch.zeros(2, 1, 256, device=dev)
    gru_x = torch.randn(1, 1, 64, device=dev)
    # AST expects [B, 1024 frames, 128 mel bins]
    ast_in = torch.randn(1, 1024, 128, device=dev, dtype=torch.float16)

    ci = loaders.CheckpointInfo.from_hf_repo("kyutai/moshiko-pytorch-bf16")
    mimi = ci.get_mimi(device=dev)
    lm = ci.get_moshi(device=dev, dtype=torch.bfloat16)
    lm_gen = LMGen(lm, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)

    fs = int(mimi.sample_rate / mimi.frame_rate)
    pcm, _ = sphn.read(args.audio, sample_rate=mimi.sample_rate)
    pcm = pcm[0] if pcm.ndim > 1 else pcm
    need = fs * (args.steps + args.warmup + 4)
    if len(pcm) < need:
        pcm = np.tile(pcm, int(np.ceil(need / len(pcm))))
    x = torch.from_numpy(pcm[:need].astype(np.float32))[None, None].to(dev)
    chunks = [c for c in x.split(fs, dim=2) if c.shape[-1] == fs]

    torch.cuda.reset_peak_memory_stats(); torch.cuda.synchronize()

    for mode in ("moshi_only", "with_companions"):
        step_ms, ast_ms, gru_ms = [], [], []
        with torch.no_grad(), mimi.streaming(1), lm_gen.streaming(1):
            first = True
            for i, ch in enumerate(chunks):
                t0 = time.perf_counter()
                codes = mimi.encode(ch)
                if first:
                    lm_gen.step(codes); first = False
                tok = lm_gen.step(codes)
                if tok is not None:
                    _ = mimi.decode(tok[:, 1:])
                if mode == "with_companions":
                    ta = time.perf_counter()
                    if ast is not None:
                        _ = ast(input_values=ast_in).logits
                    torch.cuda.synchronize(); tb = time.perf_counter()
                    # the GRU ticks at 10 Hz, i.e. on 4 of every 5 Moshi frames
                    if i % 5 != 0:
                        _, _gru_h2 = gru(gru_x, gru_h)
                    torch.cuda.synchronize(); tc = time.perf_counter()
                    ast_ms.append((tb - ta) * 1e3); gru_ms.append((tc - tb) * 1e3)
                torch.cuda.synchronize()
                dt = (time.perf_counter() - t0) * 1e3
                if i >= args.warmup:
                    step_ms.append(dt)
                if len(step_ms) >= args.steps:
                    break
        p50, p99 = pct(step_ms, 50), pct(step_ms, 99)
        row = {
            "n_steps": len(step_ms),
            "step_ms_p50": round(p50, 3), "step_ms_p99": round(p99, 3),
            "rtf_p50": round(p50 / FRAME_MS, 4), "rtf_p99": round(p99 / FRAME_MS, 4),
            "frac_of_frame_p99": round(p99 / FRAME_MS, 4),
            "fits_80ms_p99": bool(p99 <= FRAME_MS),
            "peak_gpu_alloc_gib": round(torch.cuda.max_memory_allocated() / 2**30, 3),
        }
        if ast_ms:
            row["ast_ms_p50"] = round(pct(ast_ms, 50), 3)
            row["gru_ms_p50"] = round(pct(gru_ms, 50), 3)
        res[mode] = row

    a, b = res["moshi_only"], res["with_companions"]
    res["delta"] = {
        "p50_ms": round(b["step_ms_p50"] - a["step_ms_p50"], 3),
        "p99_ms": round(b["step_ms_p99"] - a["step_ms_p99"], 3),
        "headroom_ms_p99": round(FRAME_MS - b["step_ms_p99"], 2),
        "max_rtf_stack_fits": round(b["step_ms_p99"] / FRAME_MS, 3),
    }
    Path(args.out).write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
