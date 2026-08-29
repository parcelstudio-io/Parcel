#!/usr/bin/env python
"""DS-1 (AMENDMENTS.md D4, training-data half) — what an aligned
(audio, text, act) corpus would actually cost.

Data source: BM-1's world simulator has already generated the episodes
(research/20260828/behavior-model-1/splits.json). This computes hours of audio,
the moshi-finetune token budget, the LoRA GPU-hour estimate on this 32 GB Ada,
and whether that fits DESIGN.md's 24 GB single-job rule.

    ~/.cache/parcel-0e/venv-moshi/bin/python training_plan.py [--measure-tflops]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BM1 = HERE.parent / "behavior-model-1" / "splits.json"

# --- moshi-finetune published recipe (github.com/kyutai-labs/moshi-finetune) ---
# example/moshi_7B.yaml + README "Memory Requirements" table.
RECIPE = {
    "lora_rank": 128, "lora_scaling": 2.0, "ft_embed": False,
    "duration_sec": 100, "batch_size": 16, "max_steps": 2000,
    "lr": 2e-6, "gradient_checkpointing": True,
    "tokens_per_step_per_second": 9,   # 8 audio codebooks + 1 text
    "frame_hz": 12.5,
    "h100_1gpu_tokens_per_s": 12000,
    "h100_1gpu_peak_alloc_gb": 39.6,
    "h100_8gpu_tokens_per_s": 10700,
    "h100_8gpu_peak_alloc_gb_per_gpu": 23.7,
}
# H100 SXM BF16 tensor core: 1,979 TFLOPS *with sparsity* (nvidia.com H100 page)
# -> dense bf16 ~= 989.5 TFLOPS.
H100_SXM_BF16_DENSE_TFLOPS = 989.5
H100_SPEC_SRC = "https://www.nvidia.com/en-us/data-center/h100/ (1,979 TFLOPS with sparsity)"

ADA_LIMITS = {"card_gb": 32, "design_single_job_gb": 24}


def measure_bf16_tflops(n: int = 8192, iters: int = 50) -> dict:
    import torch
    if not torch.cuda.is_available():
        return {"achieved_tflops": None, "note": "no CUDA device"}
    a = torch.randn(n, n, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(n, n, device="cuda", dtype=torch.bfloat16)
    for _ in range(20):
        a @ b
    torch.cuda.synchronize()
    times = []
    for _ in range(iters):
        s = torch.cuda.Event(enable_timing=True); e = torch.cuda.Event(enable_timing=True)
        s.record(); a @ b; e.record(); torch.cuda.synchronize()
        times.append(s.elapsed_time(e))
    flops = 2 * n ** 3
    best = min(times)
    del a, b; torch.cuda.empty_cache()
    return {
        "achieved_tflops": round(flops / (best / 1000.0) / 1e12, 1),
        "matrix_n": n, "iters": iters,
        "method": "best-of-N square bf16 matmul, 2*n^3 FLOPs",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure-tflops", action="store_true")
    ap.add_argument("--ada-tflops", type=float, default=None,
                    help="use this instead of measuring")
    args = ap.parse_args()

    splits = json.loads(BM1.read_text())["splits"]
    corpus = {}
    total_frames = total_eps = 0
    for name, s in splits.items():
        frames, eps = s["frames"], s["episodes"]
        total_frames += frames; total_eps += eps
        corpus[name] = {
            "episodes": eps, "frames_10hz": frames,
            "seconds": round(frames / 10.0, 1),
            "hours": round(frames / 10.0 / 3600.0, 2),
            "mean_episode_s": round(frames / eps / 10.0, 1),
            "nonidle_frame_frac": s.get("nonidle_frame_frac"),
        }
    corpus["TOTAL"] = {
        "episodes": total_eps, "frames_10hz": total_frames,
        "seconds": round(total_frames / 10.0, 1),
        "hours": round(total_frames / 10.0 / 3600.0, 2),
        "mean_episode_s": round(total_frames / total_eps / 10.0, 1),
    }
    train_h = corpus["train"]["hours"]
    train_s = corpus["train"]["seconds"]

    # Tokens: one Moshi frame carries 8 audio codebooks + 1 text; the act stream
    # makes it 10. Frames come from the 12.5 Hz clock, not BM-1's 10 Hz.
    frames_125 = train_s * RECIPE["frame_hz"]
    tokens_stock = frames_125 * 9
    tokens_act = frames_125 * 10
    h100_h = tokens_act / RECIPE["h100_1gpu_tokens_per_s"] / 3600.0

    tf = None
    if args.ada_tflops is not None:
        tf = {"achieved_tflops": args.ada_tflops, "method": "supplied"}
    elif args.measure_tflops:
        tf = measure_bf16_tflops()

    out = {
        "note": "AMENDMENTS.md D4, training-data half",
        "corpus_source": str(BM1),
        "corpus_note": (
            "BM-1 has ALREADY generated these episodes as token streams at 10 Hz; "
            "this plan reuses them rather than inventing a corpus. The audio does "
            "not exist yet — it would be TTS-rendered."
        ),
        "corpus": corpus,
        "bm1_act_vocab_size": json.loads(BM1.read_text())["n_acts"],
        "tts_plan": {
            "engine": "in-repo Piper 1.2.0 (third_party/piper/piper)",
            "voice": "models/piper/voice.onnx — en-US, 22050 Hz, single voice",
            "required": "24 kHz stereo: channel 0 = the dog, channel 1 = the owner",
            "steps": [
                "render each episode's dialogue turns to wav with Piper",
                "resample 22050 -> 24000 Hz",
                "place turns on the episode timeline; dog -> ch0, owner -> ch1",
                ("resample the 10 Hz act labels to 12.5 Hz (hold-last; zero drops "
                "in this direction — see resample_contract.json)"),
                "emit moshi-finetune's jsonl {path, duration} manifest",
            ],
            "blocker": (
                "only ONE Piper voice is present, so both speakers would share a "
                "timbre; Moshi's multistream training assumes two distinguishable "
                "speakers. A second voice (or Kokoro-82M's multi-voice set) is "
                "required before rendering."
            ),
        },
        "recipe": RECIPE,
        "recipe_source": "github.com/kyutai-labs/moshi-finetune example/moshi_7B.yaml + README",
        "token_budget_one_epoch_train_split": {
            "audio_hours": train_h,
            "frames_at_12p5hz": int(frames_125),
            "tokens_stock_9_per_frame": int(tokens_stock),
            "tokens_with_act_10_per_frame": int(tokens_act),
        },
        "gpu_hours": {
            "h100_1gpu_hours_one_epoch": round(h100_h, 2),
            "h100_throughput_source": "moshi-finetune README memory/throughput table",
        },
        "memory_verdict": {
            "published_peak_gb_1gpu": RECIPE["h100_1gpu_peak_alloc_gb"],
            "this_card_gb": ADA_LIMITS["card_gb"],
            "design_single_job_gb": ADA_LIMITS["design_single_job_gb"],
            "fits_this_card_at_published_batch": False,
            "fits_24gb_rule_at_published_batch": False,
            "conclusion": (
                "The published recipe peaks at 39.6 GB on one GPU — above this "
                "32 GB card AND above DESIGN.md's 24 GB single-job rule. batch_size "
                "must drop from 16 (the README's own advice for OOM); the 8xH100 "
                "row shows 23.7 GB/GPU is reachable at batch 16 sharded, so a "
                "single-GPU batch of ~2-4 with gradient checkpointing is the "
                "plausible landing zone — at proportionally lower throughput."
            ),
        },
        "ada_bf16": tf,
    }
    if tf and tf.get("achieved_tflops"):
        ratio = H100_SXM_BF16_DENSE_TFLOPS / tf["achieved_tflops"]
        out["gpu_hours"].update({
            "h100_sxm_bf16_dense_tflops": H100_SXM_BF16_DENSE_TFLOPS,
            "h100_spec_source": H100_SPEC_SRC,
            "ada_measured_bf16_tflops": tf["achieved_tflops"],
            "compute_ratio_h100_over_ada": round(ratio, 2),
            "ada_hours_one_epoch_compute_scaled": round(h100_h * ratio, 1),
            "ada_hours_one_epoch_with_batch_derate_4x": round(h100_h * ratio * 4, 1),
            "derate_note": (
                "the 4x row assumes batch_size drops 16 -> 4 to fit memory, with "
                "throughput falling roughly linearly. Both rows are ESTIMATES "
                "scaled from a matmul microbenchmark, not a measured training run "
                "— moshi-finetune could not be installed (see RESULTS.md)."
            ),
        })
    Path(HERE / "training_plan.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "corpus"}, indent=2))
    print("\ncorpus:")
    for k, v in corpus.items():
        print(f"  {k:16} {v['episodes']:>5} eps  {v['frames_10hz']:>9,} frames  {v['hours']:>7.2f} h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
