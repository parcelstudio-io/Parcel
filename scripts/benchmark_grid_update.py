"""Reproducible, assertion-free microbenchmark for LiDAR grid integration."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time

import numpy as np

from parcel_robot.navigation.grid_planner import (
    GridPlannerConfig,
    LidarScan,
    Pose2D,
    RollingOccupancyGrid,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rays", type=int, default=720)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmups", type=int, default=10)
    args = parser.parse_args()
    if args.rays < 2 or args.iterations < 1 or args.warmups < 0:
        parser.error("rays >= 2, iterations >= 1, and warmups >= 0 are required")

    config = GridPlannerConfig(
        resolution_m=0.10,
        grid_size_cells=161,
        lidar_range_cap_m=12.0,
    )
    field_of_view = 3.0 * math.pi / 2.0
    scan = LidarScan(
        ranges_m=(math.inf,) * args.rays,
        angle_min_rad=-field_of_view / 2.0,
        angle_increment_rad=field_of_view / (args.rays - 1),
        range_min_m=0.05,
        range_max_m=30.0,
    )
    grid = RollingOccupancyGrid(config)
    pose = Pose2D(0.05, 0.05, 0.0)
    for _ in range(args.warmups):
        grid.update(pose, scan)

    durations_ms = []
    for _ in range(args.iterations):
        started_ns = time.perf_counter_ns()
        grid.update(pose, scan)
        durations_ms.append((time.perf_counter_ns() - started_ns) / 1e6)
    ordered = sorted(durations_ms)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    print(
        json.dumps(
            {
                "benchmark": "rolling_occupancy_grid_open_space_update",
                "python": platform.python_version(),
                "numpy": np.__version__,
                "rays": args.rays,
                "field_of_view_degrees": 270.0,
                "range_cap_m": config.lidar_range_cap_m,
                "grid_size_cells": config.grid_size_cells,
                "warmups": args.warmups,
                "iterations": args.iterations,
                "min_ms": min(durations_ms),
                "median_ms": statistics.median(durations_ms),
                "mean_ms": statistics.fmean(durations_ms),
                "p95_ms": ordered[p95_index],
                "max_ms": max(durations_ms),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
