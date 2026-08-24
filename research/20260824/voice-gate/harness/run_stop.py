#!/usr/bin/env python
"""The A9 rows: does an always-local spoken STOP land, and how late?

Two tapes, one matcher. The STOP tape gives recall and the tail; the television
tape and (separately, in ``run_ambient.py``) the real room give the false-STOP
rate. The bar is finite-sample on purpose — "p95 <= 800 ms AND all of n >= 60
within 1.0 s" — so both are reported, and the n is reported beside them.

The matcher is HARNESS code. ``lane.py:47`` says the product's spoken stop is
transcribed in the cloud; nothing here is wired into the runtime, and the
RESULTS say so before it says anything else.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from .arena import build as build_arena
from .asr import WhisperClient
from .rows import percentile
from .session import load_bed, load_manifest, speech_level_dbfs, write_result
from .stop_matcher import StopConfig, run_stop_matcher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument(
        "--tv-seconds",
        type=float,
        default=600.0,
        help="how much of the television tape to scan for false STOPs. The scan is "
        "bounded by the transcriber, so the whole tape costs about as long as the tape "
        "itself; the reported rate carries its own tape length.",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    bed = load_bed(args.tape)
    arena = build_arena(manifest, bed, speech_level_dbfs(bed))
    client = WhisperClient()
    if not client.available():
        raise SystemExit("whisper-server is not answering on 127.0.0.1:8099")
    config = StopConfig()

    started = time.time()
    stop_run = run_stop_matcher(arena.stop.samples, client, config=config)
    stop_wall = time.time() - started

    #: One latch per placement, the FIRST one at or after the word ends.
    latencies: list[float] = []
    missed: list[str] = []
    for placement in arena.stop.placements:
        candidates = [
            event
            for event in stop_run.events
            if placement.speech_start_s <= event.latch_tape_s <= placement.speech_end_s + 2.5
        ]
        if not candidates:
            missed.append(placement.name)
            continue
        # Every STOP phrasing on this tape ENDS with the stop word, so the
        # utterance's energy end is A9's "end of the spoken hotword". A latch
        # that lands before it (the first "stop" of "stop stop stop") is early,
        # not negative: clamped to 0 rather than dropped, because dropping it
        # would quietly raise the p95 by deleting the fastest trials.
        latencies.append(
            max(0.0, min(event.latch_tape_s for event in candidates) - placement.speech_end_s)
        )

    started = time.time()
    tv_samples = arena.tv.samples[: int(args.tv_seconds * 16_000)]
    tv_seconds = tv_samples.size / 16_000
    tv_run = run_stop_matcher(tv_samples, client, config=config)
    tv_wall = time.time() - started

    positives = list(latencies)
    payload = {
        "tier": "replay",
        "matcher": "harness STOP-LOCAL: Silero v6 + resident whisper base.en whole-word spot",
        "product_status": (
            "NOT in the product: realtime/lane.py:47-53 transcribes a spoken stop in the "
            "cloud. This is the A6/STOP-LOCAL reference implementation the build gate is "
            "measured against."
        ),
        "config": vars(config),
        "hosted_usd": 0.0,
        "stop_tape_seconds": arena.stop.seconds,
        "trials": len(arena.stop.placements),
        "latched": len(latencies),
        "recall": len(latencies) / len(arena.stop.placements),
        "missed": missed,
        "latency_s_p50": percentile(positives, 50),
        "latency_s_p95": percentile(positives, 95),
        "latency_s_max": max(positives, default=float("nan")),
        "latency_s_over_1s": int(sum(1 for value in positives if value > 1.0)),
        "latency_s_all": [round(value, 4) for value in positives],
        "asr_calls_stop_tape": stop_run.checks,
        "asr_skipped_busy": stop_run.skipped_busy,
        "asr_mean_latency_s": stop_run.asr_seconds / max(1, stop_run.checks),
        "stop_tape_wall_s": stop_wall,
        "tv_tape": {
            "seconds": tv_seconds,
            "false_stops": len(tv_run.events),
            "false_stops_substring_only": len(tv_run.substring_events),
            "substring_texts": [event.text for event in tv_run.substring_events][:10],
            "false_stops_per_24h": len(tv_run.events) / (tv_seconds / 86400.0),
            "texts": [event.text for event in tv_run.events][:20],
            "checks": tv_run.checks,
            "wall_s": tv_wall,
        },
        "geometry_breakdown": {
            geometry: {
                "n": int(np.sum([p.geometry == geometry for p in arena.stop.placements])),
            }
            for geometry in sorted({p.geometry for p in arena.stop.placements})
        },
    }
    path = write_result("stop_local.json", payload)
    print(
        f"STOP recall {payload['recall']:.3f} (n={payload['trials']})  "
        f"p50 {payload['latency_s_p50']*1000:.0f} ms  p95 {payload['latency_s_p95']*1000:.0f} ms  "
        f"max {payload['latency_s_max']*1000:.0f} ms  over 1 s: {payload['latency_s_over_1s']}  "
        f"TV false stops {payload['tv_tape']['false_stops']} in "
        f"{tv_seconds/60:.1f} min -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
