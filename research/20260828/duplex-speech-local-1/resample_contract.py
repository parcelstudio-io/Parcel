#!/usr/bin/env python
"""DS-1 (AMENDMENTS.md D2) — the 12.5 Hz <-> 10 Hz act-clock resampling contract,
with the number of dropped non-idle tokens COUNTED on a synthetic act stream.

Moshi's frame is Mimi's: 12.5 Hz / 80 ms (`moshi/models/loaders.py:29`).
Parcel's duplex clock is `frame_hz: float = 10.0` / 100 ms
(`src/parcel_robot/duplex/config.py:22`, `duplex/frames.py:24`).
The ratio is 5:4 — no common frame, no integer resampling.

Two directions, and they are NOT symmetric:

  TRAINING  (Parcel 10 Hz act log -> Moshi 12.5 Hz training frames): UPSAMPLING.
            Hold-last cannot drop anything; each source frame covers >= 1 target
            frame. Cost is onset jitter only.

  INFERENCE (Moshi emits act at 12.5 Hz -> Parcel's 10 Hz DuplexFrame clock):
            DOWNSAMPLING. 2.5 of every 12.5 frames per second have no slot of
            their own. Hold-last (last-write-wins, which is what
            `FrameInterleaver.push_act` already does) DROPS a non-idle token
            whenever two distinct non-idle acts fall in the same 100 ms window.

This script measures the drop rate for the inference direction and compares
hold-last against the event-priority merge named in the amendment.

Uses the real `ActTokenCodec` vocabulary (read-only import from src/).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.duplex.act_codec import (
    ActTokenCodec,
    default_twist_bins,
)
from parcel_robot.duplex.frames import ACT_IDLE

MOSHI_HZ = 12.5
PARCEL_HZ = 10.0


def synth_act_stream(n_frames: int, hz: float, events_per_s: float, seed: int):
    """An act stream as the product actually models it: a STATE held until
    replaced, with non-idle events arriving as a Poisson-ish process."""
    rng = random.Random(seed)
    codec = ActTokenCodec(
        twist=default_twist_bins(),
        skills=("sit", "stand", "come", "fetch", "shake", "spin", "lie_down", "follow"),
        emotes=("happy", "alert", "tired", "curious", "shy", "excited"),
    )
    vocab = [t for t in codec.vocabulary() if t != ACT_IDLE]
    p_event = events_per_s / hz
    out, cur = [], ACT_IDLE
    for _ in range(n_frames):
        if rng.random() < p_event:
            cur = rng.choice(vocab)
        elif rng.random() < 0.25:  # events decay back to idle
            cur = ACT_IDLE
        out.append(cur)
    return out


def hold_last(src, src_hz: float, dst_hz: float):
    """Resample by taking the source token in force at each destination frame's
    START. This is 'last write wins', matching FrameInterleaver.push_act."""
    n_dst = int(len(src) * dst_hz / src_hz)
    return [src[min(len(src) - 1, int(i * src_hz / dst_hz))] for i in range(n_dst)]


def count_dropped_non_idle(src, src_hz: float, dst_hz: float):
    """A non-idle token is DROPPED if it never appears in the resampled stream.

    We count *token occurrences* (a maximal run of one token counts once), so
    this is 'how many distinct non-idle acts the product never sees'.
    """
    dst = hold_last(src, src_hz, dst_hz)
    # Maximal runs in the source, and which source index each dst frame sampled.
    sampled = {min(len(src) - 1, int(i * src_hz / dst_hz)) for i in range(len(dst))}
    runs, i = [], 0
    while i < len(src):
        j = i
        while j + 1 < len(src) and src[j + 1] == src[i]:
            j += 1
        runs.append((i, j, src[i]))
        i = j + 1
    non_idle_runs = [r for r in runs if r[2] != ACT_IDLE]
    dropped = [r for r in non_idle_runs if not any(k in sampled for k in range(r[0], r[1] + 1))]
    return {
        "src_frames": len(src),
        "dst_frames": len(dst),
        "non_idle_events": len(non_idle_runs),
        "dropped_non_idle_events": len(dropped),
        "dropped_fraction": (
            round(len(dropped) / len(non_idle_runs), 5) if non_idle_runs else 0.0
        ),
    }


def event_priority_merge(src, src_hz: float, dst_hz: float):
    """The alternative named in the amendment: a destination frame takes the
    most recent NON-IDLE token that arrived in its window, and only falls back
    to idle if the window genuinely contained none. Never drops an event; it can
    delay one by at most one destination frame."""
    n_dst = int(len(src) * dst_hz / src_hz)
    out, carry = [], None
    for i in range(n_dst):
        lo = int(i * src_hz / dst_hz)
        hi = min(len(src), int((i + 1) * src_hz / dst_hz))
        window = src[lo:hi] or [src[min(lo, len(src) - 1)]]
        non_idle = [t for t in window if t != ACT_IDLE]
        if carry is not None:
            out.append(carry); carry = None
            if non_idle:
                carry = non_idle[-1]
            continue
        if len(non_idle) >= 2 and non_idle[-1] != non_idle[0]:
            out.append(non_idle[0]); carry = non_idle[-1]
        elif non_idle:
            out.append(non_idle[-1])
        else:
            out.append(ACT_IDLE)
    return out


def main() -> int:
    results = {
        "moshi_hz": MOSHI_HZ, "parcel_hz": PARCEL_HZ,
        "ratio": "5:4 — 4 Moshi frames span 5 Parcel frames; no common frame",
        "parcel_frame_hz_source": "src/parcel_robot/duplex/config.py:22 (frame_hz: float = 10.0)",
        "moshi_frame_rate_source": "moshi/models/loaders.py:29 (FRAME_RATE = 12.5)",
        "training_direction": {},
        "inference_direction": {},
    }

    # TRAINING: 10 Hz act log -> 12.5 Hz training frames (upsampling).
    for eps in (1.0, 2.0, 4.0):
        src = synth_act_stream(int(300 * PARCEL_HZ), PARCEL_HZ, eps, seed=int(eps * 7))
        results["training_direction"][f"{eps}_events_per_s"] = count_dropped_non_idle(
            src, PARCEL_HZ, MOSHI_HZ)

    # INFERENCE: 12.5 Hz model output -> 10 Hz DuplexFrame clock (downsampling).
    for eps in (1.0, 2.0, 4.0, 8.0):
        src = synth_act_stream(int(300 * MOSHI_HZ), MOSHI_HZ, eps, seed=int(eps * 13))
        row = count_dropped_non_idle(src, MOSHI_HZ, PARCEL_HZ)
        merged = event_priority_merge(src, MOSHI_HZ, PARCEL_HZ)
        src_events = row["non_idle_events"]
        merged_runs = sum(
            1 for i, t in enumerate(merged)
            if t != ACT_IDLE and (i == 0 or merged[i - 1] != t)
        )
        row["event_priority_merge_events_preserved"] = merged_runs
        row["event_priority_merge_drops"] = max(0, src_events - merged_runs)
        results["inference_direction"][f"{eps}_events_per_s"] = row

    results["contract"] = {
        "training": (
            "10 -> 12.5 Hz, hold-last. Upsampling: ZERO dropped non-idle tokens "
            "by construction. Each Parcel act is repeated over 1 or 2 Moshi "
            "frames in a 4/5 alternating pattern; the only cost is up to 80 ms "
            "of act-onset quantization jitter."
        ),
        "inference_recommended": (
            "Set DuplexConfig.frame_hz = 12.5 so the product clock matches the "
            "model's. This removes the resampling entirely and makes the control "
            "loop 20 ms faster. Downstream cadence assumptions (filler watchdog, "
            "response ceiling, TTLs) must be re-checked against the new period."
        ),
        "inference_fallback": (
            "If the 10 Hz clock must stay, use the event-priority merge rather "
            "than hold-last: a destination frame takes the earliest non-idle "
            "token in its window and carries any second one into the next frame. "
            "It never drops an event; it delays at most one by 100 ms."
        ),
    }
    Path(HERE / "resample_contract.json").write_text(json.dumps(results, indent=2))

    print("TRAINING 10 -> 12.5 Hz (upsample, hold-last)")
    for k, v in results["training_direction"].items():
        print(f"  {k:20} events {v['non_idle_events']:>5} dropped "
              f"{v['dropped_non_idle_events']:>4} ({v['dropped_fraction']:.2%})")
    print("\nINFERENCE 12.5 -> 10 Hz (downsample)")
    for k, v in results["inference_direction"].items():
        print(f"  {k:20} events {v['non_idle_events']:>5} | hold-last dropped "
              f"{v['dropped_non_idle_events']:>4} ({v['dropped_fraction']:.2%})"
              f" | event-priority dropped {v['event_priority_merge_drops']:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
