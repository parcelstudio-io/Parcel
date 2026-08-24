"""Row B3 on a jitter-free clock, plus the spectral roll-off the design asks for.

The four 10-minute state runs tick on wall time, so their finite-difference
third derivative carries the host's scheduling jitter.  This bench drives the
same expression engine through the same composer on an EXACT 20 ms grid, so the
number it reports is the limiter's own property rather than the host's.

It also answers two questions the state runs cannot:

* how much of the raw expression signal is passed through untouched (an axis
  whose output equals its input is a limiter that is not in the way), and
* what the limiter does to the signal's spectrum — the roll-off above the
  band the body can actually follow.
"""

from __future__ import annotations

import argparse
import cmath
import json
import math
import random
from pathlib import Path

from parcel_robot.audio.prosody import Accent, BeatTrack
from parcel_robot.motion.body_composer import DEFAULT_LIMITS, BodyComposer
from parcel_robot.motion.expression import ExpressionEngine, ExpressionGate, IdleLayer
from parcel_robot.robot_profile import RobotProfile

HZ = 50.0
DT = 1.0 / HZ
CHANNELS = {
    "posture_dz": "body_height_m",
    "posture_pitch": "body_pitch_rad",
    "gaze_yaw": "head_yaw_rad",
    "gaze_pitch": "head_pitch_rad",
}


def derivatives(series: list[float], dt: float) -> tuple[float, float, float]:
    first = [(series[i + 1] - series[i]) / dt for i in range(len(series) - 1)]
    second = [(first[i + 1] - first[i]) / dt for i in range(len(first) - 1)]
    third = [(second[i + 1] - second[i]) / dt for i in range(len(second) - 1)]
    return (
        max(abs(v) for v in first),
        max(abs(v) for v in second),
        max(abs(v) for v in third),
    )


def band_energy(series: list[float], dt: float, edges: tuple[float, ...]) -> list[float]:
    """Energy in each frequency band, by direct DFT of a mean-removed window."""

    count = min(len(series), 4096)
    window = series[:count]
    mean = sum(window) / count
    centred = [value - mean for value in window]
    bands = [0.0] * (len(edges) - 1)
    for bin_index in range(1, count // 2):
        frequency = bin_index / (count * dt)
        total = sum(
            value * cmath.exp(-2j * math.pi * bin_index * n / count)
            for n, value in enumerate(centred)
        )
        power = abs(total) ** 2
        for band in range(len(bands)):
            if edges[band] <= frequency < edges[band + 1]:
                bands[band] += power
                break
    return bands


def run(seconds: float, seed: int) -> dict[str, object]:
    profile = RobotProfile.go2()
    engine = ExpressionEngine(profile, idle=IdleLayer(rng=random.Random(seed)))
    composer = BodyComposer()
    gate = ExpressionGate()
    rng = random.Random(seed + 1)
    raw: dict[str, list[float]] = {name: [] for name in CHANNELS}
    out: dict[str, list[float]] = {name: [] for name in CHANNELS}
    pending: list[tuple[float, str, object]] = []
    next_speech = 4.0

    for step in range(int(seconds * HZ)):
        now = step * DT
        if now >= next_speech:
            pending.append((now, "speech_start", rng.uniform(-0.6, 0.6)))
            pending.append((now + 1.2, "speech_end", None))
            pending.append((now + 1.2, "turn_pending", None))
            pending.append((now + 2.0, "reply_started", None))
            pending.append((now + 2.0, "arm", rng.uniform(0.2, 0.9)))
            next_speech = now + rng.uniform(8.0, 16.0)
        due = [event for event in pending if event[0] <= now]
        pending = [event for event in pending if event[0] > now]
        for _when, kind, payload in due:
            if kind == "speech_start":
                engine.reactions.on_speech_start(now, float(payload))  # type: ignore[arg-type]
            elif kind == "speech_end":
                engine.reactions.on_speech_end(now)
            elif kind == "turn_pending":
                engine.reactions.on_turn_pending(now)
            elif kind == "reply_started":
                engine.reactions.on_reply_started(now)
            elif kind == "arm":
                engine.beats.arm(
                    BeatTrack(
                        duration_s=1.8,
                        accents=tuple(
                            Accent(time_s=0.25 * k, strength=rng.uniform(0.5, 1.0))
                            for k in range(7)
                        ),
                        envelope_hop_s=0.01,
                        rms_envelope=(),
                        arousal=float(payload),  # type: ignore[arg-type]
                    ),
                    playback_start_s=now,
                    epoch=engine.speech_epoch,
                )
        offsets = engine.step(now, gate)
        intent = composer.compose(now_s=now, finalized_velocity=None, offsets=offsets)
        emitted = {
            "posture_dz": intent.posture[0],
            "posture_pitch": intent.posture[1],
            "gaze_yaw": intent.gaze[0],
            "gaze_pitch": intent.gaze[1],
        }
        for name, attribute in CHANNELS.items():
            raw[name].append(getattr(offsets, attribute))
            out[name].append(emitted[name])

    bounds = DEFAULT_LIMITS.jerk_bounds()
    edges = (0.0, 1.0, 5.0, 25.0)
    axes: dict[str, object] = {}
    for name in CHANNELS:
        raw_d = derivatives(raw[name], DT)
        out_d = derivatives(out[name], DT)
        identical = sum(1 for a, b in zip(raw[name], out[name]) if a == b)
        raw_bands = band_energy(raw[name], DT, edges)
        out_bands = band_energy(out[name], DT, edges)
        axes[name] = {
            "declared": {
                "max_rate": getattr(DEFAULT_LIMITS, name).max_rate,
                "max_accel": getattr(DEFAULT_LIMITS, name).max_accel,
                "max_jerk": bounds[name],
            },
            "raw": {"d1": round(raw_d[0], 5), "d2": round(raw_d[1], 3), "d3": round(raw_d[2], 1)},
            "emitted": {
                "d1": round(out_d[0], 5),
                "d2": round(out_d[1], 3),
                "d3": round(out_d[2], 1),
            },
            "within_declared_jerk": out_d[2] <= bounds[name] + 1e-6,
            "within_declared_rate": out_d[0] <= getattr(DEFAULT_LIMITS, name).max_rate + 1e-9,
            "passed_through_unchanged_pct": round(100.0 * identical / len(raw[name]), 3),
            "max_abs_tracking_error": round(
                max(abs(a - b) for a, b in zip(raw[name], out[name])), 6
            ),
            "band_energy_ratio_out_over_raw": [
                round(o / r, 5) if r > 0 else None for o, r in zip(out_bands, raw_bands)
            ],
        }
    return {
        "seconds": seconds,
        "tick_hz": HZ,
        "clock": "exact 20 ms grid (no host jitter)",
        "band_edges_hz": list(edges),
        "limited_axis_ticks": composer.limited_ticks,
        "clamp_events": composer.clamp_events,
        "max_clamp_excess_frac": composer.max_clamp_excess_frac,
        "ticks": composer.seq,
        "axes": axes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 limiter bench (jitter-free)")
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--out", default="results/limiter_bench.json")
    args = parser.parse_args()
    payload = run(args.seconds, args.seed)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
