"""CLI for the FOLLOW_BENCH_V1 companion-navigation integration eval.

Runs one or all scenarios, writes an immutable JSON report per invocation into
the results directory, and appends one summary line to ``ledger.jsonl``.
Reports carry an explicit ``does_not_prove`` list; nothing in a report may be
read as evidence for claims on that list.

Usage:
    .parcel/bin/python -m evals.companion_nav.run_follow_bench_v1 \
        --scenario all --out evals/companion_nav/results
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.companion_nav.metrics import EpisodeMetrics, compute_episode_metrics
from evals.companion_nav.runner import (
    CONTROL_DT_S,
    GRID_MODEL_ID,
    RUNNER_VERSION,
    FollowBenchRunner,
)
from evals.companion_nav.scenarios import FOLLOW_BENCH_V1, scenario_by_id

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

DOES_NOT_PROVE = (
    (
        "real-sensor or real-robot performance (headless kinematic base, oracle "
        "owner track, raycast LiDAR with modeled noise only)"
    ),
    (
        "quadruped contact physics or gait stability (base motion is kinematic; "
        "static collisions are counted by a truth oracle, not simulated contact)"
    ),
    (
        "behavior around reactive humans (pedestrians follow fixed scripts and "
        "never yield or react)"
    ),
    (
        "pedestrian avoidance from raw sensing alone (scripted pedestrians are "
        "injected into dynamic_agents/nearest_person telemetry; they are visible "
        "to the raycast scan but absent from the analytic nearest-obstacle "
        "channel and from the static-collision oracle)"
    ),
    (
        "owner perception quality (owner visibility is a geometric line-of-sight "
        "ray at 1.0 m height, not a camera pipeline)"
    ),
    (
        "navigation speed competitiveness (BARN-style speed scoring is "
        "deliberately excluded)"
    ),
)


def build_report(
    metrics: list[EpisodeMetrics], *, robot_config: str
) -> dict[str, object]:
    follow = [item for item in metrics if item.directive_kind == "follow"]
    navigate = [item for item in metrics if item.directive_kind == "navigate"]
    band_fractions = [
        item.band_fraction for item in follow if item.band_fraction is not None
    ]
    separations = [
        item.min_pedestrian_surface_m
        for item in metrics
        if item.min_pedestrian_surface_m is not None
    ]
    aggregate = {
        "episode_count": len(metrics),
        "hard_collision_total": sum(item.hard_collision_count for item in metrics),
        "pedestrian_contact_total": sum(
            item.pedestrian_contact_count for item in metrics
        ),
        "follow_episode_count": len(follow),
        "follow_success_count": sum(1 for item in follow if item.following_success),
        "navigate_episode_count": len(navigate),
        "navigate_success_count": sum(1 for item in navigate if item.navigate_success),
        "mean_band_fraction": (
            sum(band_fractions) / len(band_fractions) if band_fractions else None
        ),
        "min_pedestrian_surface_m": min(separations, default=None),
        "personal_space_time_total_s": round(
            sum(item.personal_space_time_s for item in metrics), 3
        ),
        "intimate_space_time_total_s": round(
            sum(item.intimate_space_time_s for item in metrics), 3
        ),
    }
    return {
        "suite": "follow-bench-v1",
        "runner_version": RUNNER_VERSION,
        "navigator_model_id": GRID_MODEL_ID,
        "control_dt_s": CONTROL_DT_S,
        "generated_at_utc": _utc_timestamp(),
        "git_describe": _git_describe(),
        "robot_config": robot_config,
        "scenario_ids": [item.scenario_id for item in metrics],
        "episodes": [item.payload() for item in metrics],
        "aggregate": aggregate,
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def write_report(report: dict[str, object], results_dir: Path) -> Path:
    """Write one immutable report file and append the ledger line."""

    results_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    stamp = "".join(
        character for character in str(report["generated_at_utc"]) if character.isdigit()
    )[:14]
    nonce = hashlib.sha256(
        f"{report['generated_at_utc']}:{time.monotonic_ns()}".encode()
    ).hexdigest()[:8]
    path = results_dir / f"follow-bench-v1-{stamp}Z-{nonce}.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {path}")
    path.write_text(serialized, encoding="utf-8")

    aggregate = dict(report["aggregate"])  # type: ignore[arg-type]
    ledger_line = {
        "utc": report["generated_at_utc"],
        "report": path.name,
        "scenarios": report["scenario_ids"],
        "hard_collision_total": aggregate["hard_collision_total"],
        "follow_success": (
            f"{aggregate['follow_success_count']}/{aggregate['follow_episode_count']}"
        ),
        "navigate_success": (
            f"{aggregate['navigate_success_count']}/{aggregate['navigate_episode_count']}"
        ),
        "mean_band_fraction": aggregate["mean_band_fraction"],
    }
    ledger = results_dir / "ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(ledger_line, sort_keys=True, allow_nan=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default="all",
        help="FOLLOW_BENCH_V1 scenario id, or 'all' (default)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="results directory for the immutable report and ledger.jsonl",
    )
    parser.add_argument(
        "--robot-config",
        type=Path,
        default=REPO_ROOT / "configs" / "robot.yaml",
        help="production robot configuration used to build the controllers",
    )
    args = parser.parse_args(argv)

    if args.scenario == "all":
        scenarios = list(FOLLOW_BENCH_V1)
    else:
        scenarios = [scenario_by_id(args.scenario)]

    runner = FollowBenchRunner(robot_config=args.robot_config)
    metrics: list[EpisodeMetrics] = []
    for scenario in scenarios:
        result = runner.run(scenario)
        episode = compute_episode_metrics(result, scenario)
        metrics.append(episode)
        print(
            f"{scenario.scenario_id}: status={episode.status} "
            f"hard_collisions={episode.hard_collision_count} "
            f"band_fraction={episode.band_fraction} "
            f"navigate_success={episode.navigate_success}"
        )

    report = build_report(metrics, robot_config=str(args.robot_config))
    path = write_report(report, args.out)
    print(f"report: {path}")
    aggregate = report["aggregate"]
    print(f"aggregate: {json.dumps(aggregate, sort_keys=True)}")
    return 0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _git_describe() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = completed.stdout.strip()
    return output if completed.returncode == 0 and output else None


if __name__ == "__main__":
    raise SystemExit(main())
