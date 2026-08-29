#!/usr/bin/env python
"""DS-1 H-DS1a — Moshi streaming step-time / RTF / peak-memory measurement.

Runs the reference `moshi` streaming loop (mimi.encode -> LMGen.step ->
mimi.decode, exactly as in `moshi/run_inference.py::InferenceState.run`) over
>= 30 s of audio and records per-step wall time.

Usage:
    HF_HOME=~/.cache/parcel-0e/hf \
      ~/.cache/parcel-0e/venv-moshi/bin/python run.py --out results.json

The GPU gate (>= 26 GB free) is enforced by `gpu_wait.py`, not here.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Moshi frame rate is 12.5 Hz -> one step must complete in <= 80 ms for RTF <= 1.
MOSHI_FRAME_HZ = 12.5
MOSHI_FRAME_MS = 1000.0 / MOSHI_FRAME_HZ  # 80.0


def _nvidia_smi_free_mib() -> int | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True,
            timeout=30,
        )
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def host_snapshot(label: str) -> dict:
    """D1: GPU utilisation, co-resident compute processes, and 1-min load."""
    snap: dict = {"label": label, "wall": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        q = subprocess.check_output(
            ["nvidia-smi",
             ("--query-gpu=utilization.gpu,utilization.memory,memory.free,memory.used,"
             "clocks.current.sm,clocks.current.memory,temperature.gpu,power.draw"),
             "--format=csv,noheader,nounits"],
            text=True, timeout=30).strip().split(",")
        snap.update({
            "gpu_util_pct": int(q[0]), "gpu_mem_util_pct": int(q[1]),
            "gpu_mem_free_mib": int(q[2]), "gpu_mem_used_mib": int(q[3]),
            "sm_clock_mhz": int(q[4]), "mem_clock_mhz": int(q[5]),
            "gpu_temp_c": int(q[6]), "power_w": float(q[7]),
        })
    except Exception as exc:  # noqa: BLE001
        snap["gpu_query_error"] = str(exc)
    try:
        procs = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"], text=True, timeout=30).strip()
        rows = [r.strip() for r in procs.splitlines() if r.strip()]
        snap["gpu_compute_apps"] = rows
        snap["gpu_compute_app_count"] = len(rows)
        mine = os.getpid()
        others = []
        for r in rows:
            parts = [p.strip() for p in r.split(",")]
            try:
                if int(parts[0]) != mine:
                    others.append(r)
            except ValueError:
                others.append(r)
        snap["co_resident_processes"] = others
        snap["co_resident_mib"] = sum(
            int(p.split(",")[-1].strip()) for p in others
            if p.split(",")[-1].strip().isdigit()
        )
    except Exception as exc:  # noqa: BLE001
        snap["gpu_proc_error"] = str(exc)
    try:
        snap["loadavg_1m"], snap["loadavg_5m"], snap["loadavg_15m"] = os.getloadavg()
    except Exception:  # noqa: BLE001,S110
        pass
    return snap


def _synthetic_pcm(seconds: float, sample_rate: int):
    """Deterministic speech-ish input: 3 formant-like tones + a 4 Hz amplitude
    envelope (syllable rate) + low-level noise. Used only if no real audio is
    available; RESULTS.md must say which was used."""
    import numpy as np

    n = int(seconds * sample_rate)
    t = np.arange(n, dtype=np.float32) / sample_rate
    rng = np.random.default_rng(0)
    sig = (
        0.5 * np.sin(2 * np.pi * 130.0 * t)  # f0
        + 0.3 * np.sin(2 * np.pi * 700.0 * t)  # F1
        + 0.2 * np.sin(2 * np.pi * 1220.0 * t)  # F2
    )
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 4.0 * t))  # syllable rate
    sig = sig * envelope + 0.02 * rng.standard_normal(n).astype(np.float32)
    peak = float(np.abs(sig).max()) or 1.0
    return (0.9 * sig / peak).astype(np.float32)


def load_audio(path: str | None, seconds: float, sample_rate: int):
    """Returns (pcm_1d_float32, source_description)."""
    import numpy as np

    if path:
        import sphn

        pcm, _sr = sphn.read(path, sample_rate=sample_rate)
        pcm = pcm[0] if pcm.ndim > 1 else pcm
        src = f"file:{path} (resampled to {sample_rate} Hz by sphn)"
        need = int(seconds * sample_rate)
        if len(pcm) < need:  # loop the clip up to the requested duration
            reps = int(np.ceil(need / len(pcm)))
            pcm = np.tile(pcm, reps)
            src += f" [looped x{reps} to reach {seconds:.0f}s]"
        return pcm[:need].astype(np.float32), src
    return _synthetic_pcm(seconds, sample_rate), (
        "synthetic (130 Hz f0 + 700/1220 Hz formants, 4 Hz syllable envelope, "
        "sigma=0.02 noise, seed 0)"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-repo", default="kyutai/moshiko-pytorch-bf16")
    ap.add_argument("--audio", default=None, help="input audio path; omit for synthetic")
    ap.add_argument("--seconds", type=float, default=200.0)
    ap.add_argument("--min-steps", type=int, default=2000)
    ap.add_argument("--warmup-steps", type=int, default=8)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp16", "fp32"])
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--tag", default="h-ds1a", help="label written into results.json")
    args = ap.parse_args()

    os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))

    import torch
    from moshi.models import LMGen, loaders

    dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[args.dtype]
    device = torch.device(args.device)

    free_before = _nvidia_smi_free_mib()
    snap_start = host_snapshot("start")
    print(f"[ds1] device={device} dtype={args.dtype} gpu_free_before={free_before} MiB "
          f"co_resident={snap_start.get('co_resident_mib')} MiB "
          f"load1m={snap_start.get('loadavg_1m')}", flush=True)

    t_load0 = time.time()
    checkpoint_info = loaders.CheckpointInfo.from_hf_repo(args.hf_repo)
    mimi = checkpoint_info.get_mimi(device=device)
    checkpoint_info.get_text_tokenizer()
    lm = checkpoint_info.get_moshi(device=device, dtype=dtype)
    load_s = time.time() - t_load0
    print(f"[ds1] loaded in {load_s:.1f}s", flush=True)

    n_params = sum(p.numel() for p in lm.parameters())
    mimi_params = sum(p.numel() for p in mimi.parameters())

    lm_gen = LMGen(lm, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)

    frame_size = int(mimi.sample_rate / mimi.frame_rate)
    pcm, audio_src = load_audio(args.audio, args.seconds, mimi.sample_rate)
    print(f"[ds1] audio: {audio_src} -> {len(pcm)/mimi.sample_rate:.1f}s", flush=True)

    in_pcms = torch.from_numpy(pcm)[None, None].to(device)
    chunks = [c for c in in_pcms.split(frame_size, dim=2) if c.shape[-1] == frame_size]
    if len(chunks) < args.min_steps + args.warmup_steps:
        print(
            f"[ds1] FATAL: only {len(chunks)} frames, need "
            f">= {args.min_steps + args.warmup_steps}; raise --seconds",
            file=sys.stderr,
        )
        return 2

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    mem_after_load = torch.cuda.memory_allocated() if device.type == "cuda" else 0

    step_ms: list[float] = []
    n_text_emitted = 0
    n_steps_without_decode = 0
    t_wall0 = time.time()

    with torch.no_grad(), mimi.streaming(1), lm_gen.streaming(1):
        first_frame = True
        for i, chunk in enumerate(chunks):
            t0 = time.perf_counter()
            codes = mimi.encode(chunk)
            if first_frame:
                # Reference loop: the first slice must be stepped twice so it is
                # actually seen by the transformer (run_inference.py).
                lm_gen.step(codes)
                first_frame = False
            tokens = lm_gen.step(codes)
            decoded = False
            if tokens is not None and lm.dep_q > 0:
                _ = mimi.decode(tokens[:, 1:])
                n_text_emitted += 1
                decoded = True
            if device.type == "cuda":
                torch.cuda.synchronize()
            dt_ms = (time.perf_counter() - t0) * 1000.0
            if i >= args.warmup_steps:  # drop warmup (CUDA graph capture, alloc)
                step_ms.append(dt_ms)
                if not decoded:
                    n_steps_without_decode += 1
            if len(step_ms) >= args.min_steps and i + 1 >= len(chunks):
                break

    wall_s = time.time() - t_wall0
    snap_end = host_snapshot("end")
    peak_bytes = torch.cuda.max_memory_allocated() if device.type == "cuda" else 0
    peak_reserved = torch.cuda.max_memory_reserved() if device.type == "cuda" else 0

    srt = sorted(step_ms)

    def pct(p: float) -> float:
        if not srt:
            return float("nan")
        k = min(len(srt) - 1, max(0, round(p / 100.0 * (len(srt) - 1))))
        return srt[k]

    p50, p90, p99 = pct(50), pct(90), pct(99)
    n_over_80 = sum(1 for x in step_ms if x > MOSHI_FRAME_MS)
    audio_s = len(step_ms) / MOSHI_FRAME_HZ

    res = {
        "tag": args.tag,
        "hypothesis": "H-DS1a",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": platform.node(),
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "dtype": args.dtype,
        "hf_repo": args.hf_repo,
        "moshi_version": __import__("moshi").__version__,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "python": platform.python_version(),
        "audio_source": audio_src,
        "audio_seconds_fed": len(chunks) / MOSHI_FRAME_HZ,
        "frame_hz": MOSHI_FRAME_HZ,
        "frame_budget_ms": MOSHI_FRAME_MS,
        "load_seconds": round(load_s, 2),
        "lm_params": n_params,
        "mimi_params": mimi_params,
        "warmup_steps_dropped": args.warmup_steps,
        "n_steps_measured": len(step_ms),
        "steps_with_output": n_text_emitted,
        "measured_steps_without_decode": n_steps_without_decode,
        "decode_ran_every_measured_step": bool(n_steps_without_decode == 0),
        "host_snapshot_start": snap_start,
        "host_snapshot_end": snap_end,
        "step_ms_p50": round(p50, 3),
        "step_ms_p90": round(p90, 3),
        "step_ms_p99": round(p99, 3),
        "step_ms_mean": round(statistics.fmean(step_ms), 3) if step_ms else None,
        "step_ms_min": round(srt[0], 3) if srt else None,
        "step_ms_max": round(srt[-1], 3) if srt else None,
        "steps_over_80ms": n_over_80,
        "frac_steps_over_80ms": round(n_over_80 / len(step_ms), 6) if step_ms else None,
        "rtf_p50": round(p50 / MOSHI_FRAME_MS, 4),
        "rtf_p99": round(p99 / MOSHI_FRAME_MS, 4),
        "measured_audio_seconds": round(audio_s, 2),
        "measured_wall_seconds": round(wall_s, 2),
        "peak_gpu_alloc_bytes": peak_bytes,
        "peak_gpu_alloc_gib": round(peak_bytes / 2**30, 3),
        "peak_gpu_reserved_gib": round(peak_reserved / 2**30, 3),
        "gpu_alloc_after_load_gib": round(mem_after_load / 2**30, 3),
        "gpu_free_before_mib": free_before,
        # Pre-registered bars from DESIGN.md, evaluated mechanically.
        "bar_step_ms_le_80": bool(p50 <= MOSHI_FRAME_MS),
        "bar_rtf_le_1p0": bool(p50 / MOSHI_FRAME_MS <= 1.0),
        "bar_peak_mem_le_24gib": bool(peak_bytes / 2**30 <= 24.0),
        # AMENDMENTS.md D1 (post-start, binding): tail bar + sample count.
        "bar_D1_step_ms_p99_le_80": bool(p99 <= MOSHI_FRAME_MS),
        "bar_D1_min_2000_steps": bool(len(step_ms) >= 2000),
        "bar_D1_decode_every_step": bool(n_steps_without_decode == 0),
        "evidence_tier_label": "desktop-local-model (proposed, not registered — AMENDMENTS.md D5)",
        "step_ms_all": [round(x, 3) for x in step_ms],
    }

    Path(args.out).write_text(json.dumps(res, indent=2))
    print(
        f"[ds1] p50={p50:.1f}ms p99={p99:.1f}ms RTF(p50)={p50/MOSHI_FRAME_MS:.3f} "
        f"RTF(p99)={p99/MOSHI_FRAME_MS:.3f} peak={peak_bytes/2**30:.2f} GiB "
        f"over {len(step_ms)} steps; {n_over_80} steps > 80 ms; "
        f"no-decode steps={n_steps_without_decode} -> {args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
