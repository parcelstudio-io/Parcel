"""CPU-budget proxy for the 10 Hz onboard hot path (HR-6 desktop stand-in).

Profiles ``DirectiveNavigator.step`` on synthetic lidar observations and writes
a small JSON report. This is a **desktop/CI proxy**, not Orin NX evidence.

Default budget: integrated hot-path median ≤ 176 ms (adjudicated program plan).

Examples::

    PYTHONPATH=src .parcel/bin/python -m evals.cpu_budget_proxy
    PYTHONPATH=src .parcel/bin/python -m evals.cpu_budget_proxy \\
      --output scrum/20260805/task_1/cpu-budget-proxy-k7.json
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.paths import parcel_roots, resolve_navigation_config

DEFAULT_OUTPUT = Path("scrum/20260805/task_1/cpu-budget-proxy-k7.json")
DEFAULT_BUDGET_MEDIAN_MS = 176.0
DEFAULT_HZ = 10.0


def _obs(step: int) -> NavObservation:
    x = min(20.0, 0.05 * step)
    ray_count = 360
    ranges = [6.0] * ray_count
    # Inject a soft frontal return every few ticks so the gate path exercises.
    if step % 7 == 0:
        for index in range(5):
            ranges[index] = 1.2
    return NavObservation(
        position=(x, 0.0, 0.0),
        heading_deg=5.0 if step % 2 else 0.0,
        lidar=ranges,
        nearest_obstacle_m=min(ranges),
        nearest_person_m=None,
        extras={
            "lidar_angle_min_rad": -math.pi,
            "lidar_angle_increment_rad": (2.0 * math.pi) / ray_count,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 12.0,
        },
    )


def profile_hot_path(
    *,
    ticks: int,
    hz: float,
    directive: str,
    warmup: int,
) -> dict[str, Any]:
    if ticks <= 0:
        raise ValueError("ticks must be positive")
    nav = DirectiveNavigator.from_config(resolve_navigation_config())
    nav.start(directive)
    samples_ms: list[float] = []
    notes: list[str] = []
    for step in range(warmup + ticks):
        started = time.perf_counter()
        cmd = nav.step(_obs(step))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if step >= warmup:
            samples_ms.append(elapsed_ms)
            notes.append(cmd.note)
    nav.close()
    samples_ms.sort()
    median_ms = float(statistics.median(samples_ms))
    p95_ms = float(samples_ms[max(0, int(round(0.95 * (len(samples_ms) - 1))))])
    mean_ms = float(statistics.fmean(samples_ms))
    period_ms = 1000.0 / hz
    return {
        "ticks": ticks,
        "warmup": warmup,
        "hz": hz,
        "period_ms": period_ms,
        "directive": directive,
        "latency_ms": {
            "min": float(samples_ms[0]),
            "mean": mean_ms,
            "median": median_ms,
            "p95": p95_ms,
            "max": float(samples_ms[-1]),
        },
        "headroom_ms_median": period_ms - median_ms,
        "last_notes": notes[-5:],
    }


def build_report(
    *,
    ticks: int,
    hz: float,
    directive: str,
    warmup: int,
    budget_median_ms: float,
) -> dict[str, Any]:
    profile = profile_hot_path(ticks=ticks, hz=hz, directive=directive, warmup=warmup)
    median = float(profile["latency_ms"]["median"])
    within_budget = median <= budget_median_ms
    return {
        "schema": "parcel.cpu_budget_proxy.v1",
        "card": "K7",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "parcel_roots": [str(p) for p in parcel_roots()],
        "budget": {
            "median_ms": budget_median_ms,
            "period_ms": 1000.0 / hz,
            "within_budget": within_budget,
        },
        "profile": profile,
        "does_not_prove": [
            "Orin NX 16GB latency or thermal behavior",
            "GPU co-residency with Gemma/Fish",
            "Sport-mode tracking under the live 10 Hz stream",
            "Real sensor end-to-end pipeline timing",
        ],
        "hardware_readiness": "HR-6",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--hz", type=float, default=DEFAULT_HZ)
    parser.add_argument("--directive", default="go to the coffee shop at 42nd street")
    parser.add_argument("--budget-median-ms", type=float, default=DEFAULT_BUDGET_MEDIAN_MS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--fail-on-budget",
        action="store_true",
        help="Exit non-zero when median exceeds the budget (strict CI gate).",
    )
    args = parser.parse_args(argv)

    report = build_report(
        ticks=args.ticks,
        hz=args.hz,
        directive=args.directive,
        warmup=args.warmup,
        budget_median_ms=args.budget_median_ms,
    )
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    median = report["profile"]["latency_ms"]["median"]
    print(
        f"cpu_budget_proxy wrote {output} median_ms={median:.3f} "
        f"within_budget={report['budget']['within_budget']}",
        flush=True,
    )
    if args.fail_on_budget and not report["budget"]["within_budget"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
