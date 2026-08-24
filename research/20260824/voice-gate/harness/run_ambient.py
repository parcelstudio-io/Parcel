#!/usr/bin/env python
"""The one desktop-real-sensor rows: this room, through this array, for hours.

H1's ambient tape was synthetic silence with a dither floor, and it said so:
"a real room has a noise floor, and a VAD's false-open rate is a function of
that floor. The ambient tape's dither is a stand-in, not a measurement." This
is the measurement. Nothing is played, nothing is simulated: the XVF3800 sat on
the desk with its DAC clocking digital silence and recorded whatever the room
did, and the gate and the STOP matcher are run over the result.

Two pre-registered rows land here: false HOSTED openings per 24 h (<= 1) and
false STOPs per 24 h (<= 1). Both are counts of zero-or-more events in a finite
tape, so the report carries the one-sided 95 % upper bound the tape length
actually supports rather than the bar it would like to claim.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

import numpy as np

from .asr import WhisperClient
from .gate import GateConfig, Tape, run_gate, vad_only_arm
from .identity import OwnerIdentity
from .session import RATE_HZ, write_result
from .stop_matcher import StopConfig, run_stop_matcher

#: Rule of three: with zero events in T hours, the 95 % upper bound on the rate
#: is 3/T. Quoted rather than hidden, because "0 observed" is not "<= 1 per day".
RULE_OF_THREE = 3.0


def load_tape(path: Path, channel: int = 1) -> tuple[np.ndarray, float]:
    raw = np.fromfile(path, dtype="<i2")
    raw = raw[: raw.size - raw.size % 2].reshape(-1, 2)
    samples = np.ascontiguousarray(raw[:, channel])
    return samples, samples.size / RATE_HZ


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--channel", type=int, default=1)
    args = parser.parse_args()

    samples, seconds = load_tape(args.tape, args.channel)
    hours = seconds / 3600.0
    tape = Tape(samples=samples, placements=[])

    vad_admissions, vad_transport = run_gate(tape, vad_only_arm, config=GateConfig())
    identity = OwnerIdentity(args.scratch / "gallery" / "research_owner_voice.json")
    id_admissions, id_transport = run_gate(tape, identity.arm, config=GateConfig())

    client = WhisperClient()
    if not client.available():
        raise SystemExit("whisper-server is not answering on 127.0.0.1:8099")
    stop_run = run_stop_matcher(samples, client, config=StopConfig())

    floats = samples.astype(np.float64) / 32768.0
    block = 1600
    usable = floats.size - floats.size % block
    frame_rms = np.sqrt(
        np.maximum(1e-12, (floats[:usable].reshape(-1, block) ** 2).mean(axis=1))
    )
    frame_db = 20 * np.log10(frame_rms)

    sidecar_path = args.tape.with_suffix(".json")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.is_file() else {}

    def bound(count: int) -> float:
        if count == 0:
            return RULE_OF_THREE / hours * 24.0
        return (count + 1.96 * np.sqrt(count)) / hours * 24.0

    payload = {
        "tier": "desktop-real-sensor",
        "host": platform.node(),
        "device": sidecar.get("device_name"),
        "channel": args.channel,
        "channel_note": "ch0 = Conference beam, ch1 = ASR beam (xvf3800_probe.py)",
        "hosted_usd": 0.0,
        "tape_seconds": seconds,
        "tape_hours": hours,
        "xruns": sidecar.get("xruns"),
        "room_floor_dbfs_rms": float(20 * np.log10(np.sqrt((floats**2).mean()) + 1e-12)),
        "room_frame_dbfs_p5": float(np.percentile(frame_db, 5)),
        "room_frame_dbfs_p50": float(np.percentile(frame_db, 50)),
        "room_frame_dbfs_p99": float(np.percentile(frame_db, 99)),
        "room_peak_dbfs": float(20 * np.log10(np.abs(floats).max() + 1e-12)),
        "vad_only": {
            "spans": len(vad_admissions),
            "opens_per_hour": len(vad_admissions) / hours,
            "opens_per_24h": len(vad_admissions) / hours * 24.0,
            "upper_bound_per_24h": bound(len(vad_admissions)),
            "uploaded_seconds": vad_transport.uploaded_seconds,
            "span_open_times_s": [round(a.open_s, 2) for a in vad_admissions][:50],
        },
        "owner_id": {
            "spans_considered": len(id_admissions),
            "admitted": sum(1 for a in id_admissions if a.admitted),
            "admitted_per_24h": sum(1 for a in id_admissions if a.admitted) / hours * 24.0,
            "upper_bound_per_24h": bound(sum(1 for a in id_admissions if a.admitted)),
            "uploaded_seconds": id_transport.uploaded_seconds,
            "max_score": max((a.score or -1.0) for a in id_admissions) if id_admissions else None,
        },
        "stop_local": {
            "asr_checks": stop_run.checks,
            "false_stops": len(stop_run.events),
            "false_stops_per_24h": len(stop_run.events) / hours * 24.0,
            "upper_bound_per_24h": bound(len(stop_run.events)),
            "texts": [event.text for event in stop_run.events][:20],
        },
        "rule_of_three_note": (
            "with zero events the 95 % upper bound on the rate is 3/T; proving <= 1 per 24 h "
            "needs about 72 h of tape with no event"
        ),
    }
    path = write_result("ambient_real.json", payload)
    print(
        f"{hours:.2f} h real room: VAD opens {len(vad_admissions)} "
        f"({payload['vad_only']['opens_per_24h']:.1f}/24h), owner-ID admits "
        f"{payload['owner_id']['admitted']}, false STOPs {len(stop_run.events)} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
