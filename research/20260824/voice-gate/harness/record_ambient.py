#!/usr/bin/env python
"""Record the real room through the XVF3800 array — the one stimulus this host has.

    record_ambient.py OUT.raw --seconds 5400 [--device 4]

Writes interleaved int16 PCM (ch0 = Conference beam, ch1 = ASR beam) at 16 kHz
and a sidecar ``OUT.json`` with per-minute RMS, xruns and the wall clock, so the
tape's own quality is a measured thing rather than an assumption.

WHY A RAW TAPE AND NOT AN ONLINE GATE
-------------------------------------
The gate parameters are exactly what VOICE-GATE is choosing between. A tape can
be re-run through every arm; an online decision cannot be re-decided.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from queue import Empty, Full, Queue

import numpy as np
import sounddevice as sd

RATE_HZ = 16_000
CHANNELS = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--seconds", type=float, default=3600.0)
    parser.add_argument("--device", type=int, default=None)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    device = args.device
    if device is None:
        for index, info in enumerate(sd.query_devices()):
            if "XVF3800" in info["name"] and info["max_input_channels"] >= CHANNELS:
                device = index
                break
    if device is None:
        raise SystemExit("no XVF3800 capture device found")

    minutes: list[dict[str, float]] = []
    started = time.time()
    stats = {"xruns": 0}
    queue: Queue[np.ndarray] = Queue(maxsize=256)

    def on_audio(indata, outdata, _frames, _time, status) -> None:
        # The array's PLAYBACK endpoint is its capture clock (audio_gateway.py
        # hardware fact 3b): an input-only stream on this device never fires a
        # callback at all. What the amplifier gets meanwhile is digital zero.
        outdata[:] = 0
        if status:
            stats["xruns"] += 1
        try:
            queue.put_nowait(indata.copy())
        except Full:  # pragma: no cover - a full queue is a dropped second
            stats["xruns"] += 1

    acc: list[np.ndarray] = []
    pending = 0
    with args.out.open("wb") as sink, sd.Stream(
        device=(device, device),
        samplerate=RATE_HZ,
        channels=(CHANNELS, CHANNELS),
        dtype="int16",
        blocksize=1024,
        callback=on_audio,
    ):
        while time.time() - started < args.seconds:
            try:
                frames = queue.get(timeout=1.0)
            except Empty:  # pragma: no cover - a silent device is a finding
                continue
            sink.write(frames.tobytes())
            acc.append(frames)
            pending += frames.shape[0]
            if pending >= RATE_HZ * 60:
                chunk = np.concatenate(acc).astype(np.float64) / 32768.0
                acc = []
                pending = 0
                sink.flush()
                minutes.append(
                    {
                        "minute": len(minutes),
                        "rms_dbfs_ch0": float(
                            20 * np.log10(np.sqrt((chunk[:, 0] ** 2).mean()) + 1e-12)
                        ),
                        "rms_dbfs_ch1": float(
                            20 * np.log10(np.sqrt((chunk[:, 1] ** 2).mean()) + 1e-12)
                        ),
                        "peak_dbfs_ch1": float(20 * np.log10(np.abs(chunk[:, 1]).max() + 1e-12)),
                        "xruns_cumulative": stats["xruns"],
                    }
                )
                args.out.with_suffix(".json").write_text(
                    json.dumps(
                        {
                            "device_index": device,
                            "device_name": sd.query_devices(device)["name"],
                            "rate_hz": RATE_HZ,
                            "channels": CHANNELS,
                            "started_unix": started,
                            "note": args.note,
                            "minutes": minutes,
                        },
                        indent=1,
                    ),
                    encoding="utf-8",
                )
    elapsed = time.time() - started
    sidecar = args.out.with_suffix(".json")
    if not sidecar.is_file():  # a run shorter than one minute still leaves a record
        sidecar.write_text(
            json.dumps(
                {
                    "device_index": device,
                    "device_name": sd.query_devices(device)["name"],
                    "rate_hz": RATE_HZ,
                    "channels": CHANNELS,
                    "started_unix": started,
                    "note": args.note,
                    "minutes": minutes,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["elapsed_s"] = elapsed
    payload["xruns"] = stats["xruns"]
    payload["bytes"] = args.out.stat().st_size
    sidecar.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"recorded {elapsed:.1f}s to {args.out} ({args.out.stat().st_size} bytes, {stats['xruns']} xruns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
