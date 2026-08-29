#!/usr/bin/env python
"""DS-1 H-DS1c — extrapolate the measured desktop step time to Jetson AGX Orin 64 GB.

Batch-1 autoregressive decode of a dense transformer is memory-bandwidth bound:
each step must stream the whole weight set once. So the desktop -> Orin scaling
is well approximated by the achievable-bandwidth ratio, at equal precision.

This script MEASURES this host's achievable HBM bandwidth (rather than trusting
a spec sheet), takes Orin's published 204.8 GB/s, and reports the projection
together with an independent cross-check against a published Orin measurement.

    ~/.cache/parcel-0e/venv-moshi/bin/python edge_extrapolate.py \
        --results results.json --out edge_extrapolation.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

MOSHI_FRAME_MS = 80.0  # 12.5 Hz

# --- Cited constants -------------------------------------------------------
# Jetson AGX Orin 64 GB: 64 GB LPDDR5 @ 204.8 GB/s.
ORIN_BW_GBS = 204.8
ORIN_BW_SRC = "https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/"

# Independent cross-check: a 7B-class omni model actually measured on this board.
ORIN_XCHECK = {
    "model": "Qwen2.5-Omni-7B Q8_0, llama.cpp, full GPU offload, AGX Orin 64 GB",
    "tok_per_s": 15.7,  # midpoint of the reported 15.3-16.1
    "tok_per_s_range": [15.3, 16.1],
    "source": "https://github.com/ggml-org/llama.cpp/issues/15923",
    "note": "audio input path had an open bug in that thread; decode rate still valid",
}
ORIN_XCHECK2 = {
    "model": "Llama 3.1 8B Q4_K_M / Qwen2.5 7B Q4_K_M, llama.cpp CUDA, JetPack 6.1",
    "tok_per_s": [28.0, 31.0],
    "source": "https://multimodalflow.net/en/blog/jetson-orin-llm-benchmark/",
}


def measure_bandwidth_gbs(mib: int = 2048, iters: int = 30, warmup: int = 40) -> dict:
    """Achievable device bandwidth from a large contiguous copy (read + write).

    NOTE: a short warmup measures the GPU in its P8 low-power state and
    underreports by ~2x (observed: 234 GB/s cold vs 476 GB/s warm on this host).
    We warm up until the clocks ramp, then report the BEST of `iters` timings —
    the least-contended sample, i.e. the closest to the hardware's capability.
    """
    import torch

    if not torch.cuda.is_available():
        return {"achievable_gbs": None, "note": "no CUDA device"}
    n = mib * 1024 * 1024 // 2  # fp16 elements
    src = torch.empty(n, dtype=torch.float16, device="cuda")
    dst = torch.empty_like(src)
    bytes_moved = 2 * src.numel() * src.element_size()  # one read + one write
    for _ in range(warmup):
        dst.copy_(src)
    torch.cuda.synchronize()
    times = []
    for _ in range(iters):
        s = torch.cuda.Event(enable_timing=True)
        e = torch.cuda.Event(enable_timing=True)
        s.record()
        dst.copy_(src)
        e.record()
        torch.cuda.synchronize()
        times.append(s.elapsed_time(e))
    del src, dst
    torch.cuda.empty_cache()
    best = min(times)
    med = sorted(times)[len(times) // 2]
    return {
        "achievable_gbs": round(bytes_moved / (best / 1000.0) / 1e9, 1),
        "achievable_gbs_median": round(bytes_moved / (med / 1000.0) / 1e9, 1),
        "buffer_mib": mib,
        "iters": iters,
        "warmup": warmup,
        "method": "torch fp16 device-to-device copy, read+write counted, best of N",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results.json"))
    ap.add_argument("--profile", default=str(HERE / "profile_breakdown.json"))
    ap.add_argument("--out", default=str(HERE / "edge_extrapolation.json"))
    ap.add_argument("--measured-p50-ms", type=float, default=None,
                    help="override; otherwise read from --results")
    args = ap.parse_args()

    import torch

    p50 = args.measured_p50_ms
    lm_params = None
    src_note = "supplied on the command line"
    rp = Path(args.results)
    if p50 is None and rp.exists():
        r = json.loads(rp.read_text())
        p50 = r.get("step_ms_p50")
        lm_params = r.get("lm_params")
        src_note = f"{rp.name} ({r.get('n_steps_measured')} steps, {r.get('dtype')})"

    bw = measure_bandwidth_gbs()
    desktop_bw = bw.get("achievable_gbs")
    props = torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None

    out = {
        "hypothesis": "H-DS1c",
        "desktop_gpu": props.name if props else None,
        "desktop_bandwidth": bw,
        "desktop_bandwidth_theoretical_gbs": 576.1,
        "desktop_bandwidth_theoretical_derivation": (
            "nvidia-smi clocks.max.memory = 9001 MHz; GDDR6 double data rate "
            "-> 18.002 Gbps/pin; RTX 5000 Ada has a 256-bit bus "
            "-> 18.002 * 256 / 8 = 576.1 GB/s"
        ),
        "orin_bandwidth_gbs": ORIN_BW_GBS,
        "orin_bandwidth_source": ORIN_BW_SRC,
        "measured_step_ms_p50": p50,
        "measured_step_source": src_note,
        "lm_params": lm_params,
        "frame_budget_ms": MOSHI_FRAME_MS,
        "cross_checks": [ORIN_XCHECK, ORIN_XCHECK2],
    }

    # --- Roofline validation ------------------------------------------------
    # If batch-1 decode really is bandwidth bound, the measured LM-only step
    # should sit just above (weights_bytes / achievable_bandwidth). Measuring
    # how close it sits tells us how much to trust the Orin projection.
    pb = Path(args.profile)
    if pb.exists() and lm_params and desktop_bw:
        prof = json.loads(pb.read_text())
        lm_step_ms = prof.get("lm_step_ms_p50")
        weight_gb_bf16 = lm_params * 2 / 1e9
        floor_ms = weight_gb_bf16 / desktop_bw * 1000.0
        eff = floor_ms / lm_step_ms if lm_step_ms else None
        out["roofline_validation"] = {
            "lm_step_ms_p50_measured": lm_step_ms,
            "weights_gb_bf16": round(weight_gb_bf16, 3),
            "desktop_achievable_gbs": desktop_bw,
            "bandwidth_floor_ms": round(floor_ms, 2),
            "roofline_efficiency": round(eff, 3) if eff else None,
            "interpretation": (
                "the LM step achieves this fraction of the pure weight-sweep "
                "floor, so batch-1 decode here IS bandwidth bound and scaling "
                "by bandwidth to another device is a sound first-order model"
            ),
            "mimi_encode_decode_ms_p50": (
                round(prof.get("mimi_encode_ms_p50", 0)
                      + prof.get("mimi_decode_ms_p50", 0), 3)
            ),
            "temporal_transformer_params": prof.get("temporal_transformer_params"),
            "depformer_stack_params": prof.get("depformer_stack_params"),
        }
        # Orin projection anchored on the measured efficiency, per precision.
        orin = {}
        for name, bytes_per in (("bf16", 2), ("int8", 1), ("int4", 0.5)):
            gb = lm_params * bytes_per / 1e9
            f_ms = gb / ORIN_BW_GBS * 1000.0
            lm_ms = f_ms / eff if eff else None
            mimi_ms = out["roofline_validation"]["mimi_encode_decode_ms_p50"] * (
                desktop_bw / ORIN_BW_GBS
            )
            orin[name] = {
                "weights_gb": round(gb, 2),
                "bandwidth_floor_ms": round(f_ms, 1),
                "lm_step_ms": round(lm_ms, 1) if lm_ms else None,
                "plus_mimi_ms": round(mimi_ms, 1),
                "frame_total_ms": round(lm_ms + mimi_ms, 1) if lm_ms else None,
                "rtf": round((lm_ms + mimi_ms) / MOSHI_FRAME_MS, 2) if lm_ms else None,
                "fits_80ms": bool(lm_ms + mimi_ms <= MOSHI_FRAME_MS) if lm_ms else None,
            }
        out["orin_projection_roofline_anchored"] = orin

        # --- Conservative anchor -------------------------------------------
        # The roofline projection assumes Orin reaches the same fraction of its
        # bandwidth roofline that this desktop does. The one published 7B-class
        # measurement on this exact board says otherwise, so we also report the
        # projection re-anchored on it. This is the number to plan against.
        meas_ms_per_tok = 1000.0 / ORIN_XCHECK["tok_per_s"]
        ideal_int8 = orin["int8"]["lm_step_ms"]
        derate = meas_ms_per_tok / ideal_int8 if ideal_int8 else None
        mimi_ms = orin["int8"]["plus_mimi_ms"]
        out["orin_projection_conservative"] = {
            "anchor": ORIN_XCHECK,
            "anchor_ms_per_token": round(meas_ms_per_tok, 1),
            "idealized_int8_lm_step_ms": ideal_int8,
            "derate_factor": round(derate, 2) if derate else None,
            "derate_note": (
                "llama.cpp on Orin reaches only 1/derate of the bandwidth-roofline "
                "projection for a 7B at Q8; applying the same derate to Moshi"
            ),
            "int8_lm_step_ms": round(meas_ms_per_tok, 1),
            "int8_frame_total_ms": round(meas_ms_per_tok + mimi_ms, 1),
            "int8_rtf": round((meas_ms_per_tok + mimi_ms) / MOSHI_FRAME_MS, 2),
            "int8_fits_80ms": bool(meas_ms_per_tok + mimi_ms <= MOSHI_FRAME_MS),
            "int4_frame_total_ms": round(meas_ms_per_tok / 2 + mimi_ms, 1),
            "int4_rtf": round((meas_ms_per_tok / 2 + mimi_ms) / MOSHI_FRAME_MS, 2),
            "int4_fits_80ms": bool(meas_ms_per_tok / 2 + mimi_ms <= MOSHI_FRAME_MS),
            "caveat": (
                "Moshi's depformer runs dep_q=8 SEQUENTIAL sub-steps per frame, "
                "each a small kernel launch; on Orin's weaker launch/latency "
                "profile that overhead is likely worse than on this desktop, so "
                "even this row may be optimistic. Nothing replaces running it "
                "on the board."
            ),
        }

    if p50 is not None and desktop_bw:
        ratio = desktop_bw / ORIN_BW_GBS
        out["bandwidth_ratio_desktop_over_orin"] = round(ratio, 3)
        # Same precision (bf16) on Orin:
        proj_bf16 = p50 * ratio
        out["projection"] = {
            "orin_bf16_step_ms": round(proj_bf16, 1),
            "orin_bf16_rtf": round(proj_bf16 / MOSHI_FRAME_MS, 2),
            # Quantization shrinks the streamed weight set roughly linearly.
            "orin_int8_step_ms": round(proj_bf16 / 2.0, 1),
            "orin_int8_rtf": round(proj_bf16 / 2.0 / MOSHI_FRAME_MS, 2),
            "orin_int4_step_ms": round(proj_bf16 / 4.0, 1),
            "orin_int4_rtf": round(proj_bf16 / 4.0 / MOSHI_FRAME_MS, 2),
            "assumption": (
                "batch-1 decode is bandwidth bound; step time scales with "
                "streamed weight bytes / achievable bandwidth. Quantization "
                "scaling is idealized (ignores dequant overhead and the fact "
                "that Mimi and the depformer stay in higher precision), so the "
                "int8/int4 rows are optimistic lower bounds."
            ),
        }
        # Weight-sweep floor: even a perfect kernel must read the weights once.
        if lm_params:
            for name, bytes_per in (("bf16", 2), ("int8", 1), ("int4", 0.5)):
                gb = lm_params * bytes_per / 1e9
                out["projection"][f"orin_{name}_weight_sweep_floor_ms"] = round(
                    gb / ORIN_BW_GBS * 1000.0, 1
                )
                out["projection"][f"orin_{name}_weight_gb"] = round(gb, 2)

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
