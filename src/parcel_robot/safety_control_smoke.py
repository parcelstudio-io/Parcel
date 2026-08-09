"""Desktop/CI smoke entry for the network-independent safety+control container.

Runs a synthetic 10 Hz authority-loop tick (navigator + reactive note) until
SIGINT/SIGTERM. No outbound network is required or used.
"""

from __future__ import annotations

import argparse
import os
import signal
import time
import math
from typing import Any

from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.paths import parcel_roots, resolve_navigation_config


def _observation(step: int) -> NavObservation:
    # Slow crawl toward a far POI so the hot path stays in track/align modes.
    x = 0.02 * step
    ray_count = 360
    ranges = [8.0] * ray_count
    return NavObservation(
        position=(x, 0.0, 0.0),
        heading_deg=0.0,
        lidar=ranges,
        nearest_obstacle_m=8.0,
        nearest_person_m=None,
        extras={
            "lidar_angle_min_rad": -math.pi,
            "lidar_angle_increment_rad": (2.0 * math.pi) / ray_count,
            "lidar_range_min_m": 0.05,
            "lidar_range_max_m": 12.0,
        },
    )


def run_loop(*, hz: float, max_ticks: int | None, directive: str) -> dict[str, Any]:
    if hz <= 0:
        raise ValueError("hz must be positive")
    period = 1.0 / hz
    nav = DirectiveNavigator.from_config(resolve_navigation_config())
    nav.start(directive)
    stop = {"flag": False}

    def _stop(_signum: int, _frame: Any) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    ticks = 0
    last_note = ""
    started = time.monotonic()
    while not stop["flag"]:
        if max_ticks is not None and ticks >= max_ticks:
            break
        tick_start = time.monotonic()
        cmd = nav.step(_observation(ticks))
        last_note = cmd.note
        ticks += 1
        elapsed = time.monotonic() - tick_start
        sleep_for = period - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
    nav.close()
    return {
        "ticks": ticks,
        "hz": hz,
        "elapsed_s": time.monotonic() - started,
        "last_note": last_note,
        "parcel_roots": [str(p) for p in parcel_roots()],
        "network_independent": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hz", type=float, default=10.0)
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="Exit after N ticks (CI smoke). Default: run until signal.",
    )
    parser.add_argument("--directive", default="go to the coffee shop at 42nd street")
    args = parser.parse_args(argv)

    # Compose sets PARCEL_ROOT; keep a clear breadcrumb in logs.
    print(
        "parcel.safety_control_smoke starting "
        f"PARCEL_ROOT={os.environ.get('PARCEL_ROOT', '')!r} roots={list(parcel_roots())}",
        flush=True,
    )
    summary = run_loop(hz=args.hz, max_ticks=args.max_ticks, directive=args.directive)
    print(f"parcel.safety_control_smoke done {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
