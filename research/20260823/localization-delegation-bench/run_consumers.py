"""Row L6 — the navigation consumers, with the localizer in the MAP role.

This runs the *existing* DR-2 drift ladder (``evals/nav_instruct/run_drift_arms``)
over the frozen NAV_INSTRUCT drift cells twice: once exactly as it ships (MAP is
``DriftingOdomProvider``'s truth passthrough) and once with
``LocalizedPoseProvider`` in front of the same seeded ODOM source.  Nothing
under ``evals/`` is edited: the arm loop, the row builder, the hard invariants
and the non-vacuity checks are the shipped ones, reached by binding this
module's runner subclass onto ``run_drift_arms.NavInstructRunner`` for the
localized pass.  The frozen episode set is replayed read-only.

**Two faithfulness decisions, both stated before the run.**

1.  *A localizer's dropout is a sensor dropout.*  The ``*_lost`` profiles
    schedule a window in which ``DriftingOdomProvider`` simply declares itself
    LOST.  A real localizer has no such switch, so during those same windows
    this harness withholds the SCAN and lets the provider's own staleness logic
    produce the refusal.  The ODOM side keeps its scheduled window too, so the
    shipped non-vacuity check ("the window HELD and then RECOVERED", which
    samples ODOM) still binds.

2.  *MAP health is now earned, not configured.*  ``navigation/pipeline.py``
    reads MAP health in two places — ``_pose_lost_hold`` (stop while LOST) and
    ``_semantic_arrival_verified`` (refuse to claim arrival unless HEALTHY).
    With the localizer installed those branches are driven by scan matching for
    the first time, which is the whole point of the row.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from traverse import scan_frame_from_ranges

from evals.nav_instruct import run_drift_arms
from evals.nav_instruct.runner import NavInstructRunner, _DriftSeededHarness
from parcel_robot.localization.gicp_provider import ScanMatchConfig, ScanMatchLocalizer
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.pose import PoseHealth, load_pose_config
from parcel_robot.simulation.headless_city import HeadlessCityWorld

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

#: The rungs the H7 design names, plus the truth control for the stock pass.
LADDER = (
    "calibrated_go2",
    "go2_aggressive",
    "go2_degraded",
    "calibrated_go2_lost",
    "go2_degraded_lost",
)
STOCK_ARMS: tuple[str | None, ...] = (None, *LADDER)

#: Per-episode MAP-side telemetry the shipped row builder has no field for.
TELEMETRY: list[dict[str, Any]] = []


class TappedCityWorld(HeadlessCityWorld):
    """Caches the observation it just published so the scan can be re-read.

    A subclass rather than an edit, and a cache rather than a second raycast:
    calling ``raycast_planar_scan`` again would draw from ``_scan_rng`` a second
    time and shift every downstream result.
    """

    last_observation: Any = None

    def observe(self) -> Any:
        observation = super().observe()
        self.last_observation = observation
        return observation


class RecordingProvider(LocalizedPoseProvider):
    """The product adapter plus a per-episode MAP health / jump histogram."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.map_health = Counter()
        self.map_events = Counter()

    def update_truth(self, *args: Any, **kwargs: Any) -> Any:
        update = super().update_truth(*args, **kwargs)
        if update is not None:
            self.map_health[update.health.value] += 1
            self.map_events[str(self.localizer.diagnostics.get("event", ""))] += 1
        return update


class H7DriftHarness(_DriftSeededHarness):
    """``new_pose_provider`` returns the composed provider, seeded as before."""

    def __init__(self, world: Any, *, robot_config: Any, pose_profile: str) -> None:
        super().__init__(world, robot_config=robot_config, pose_profile=pose_profile)
        self.lost_windows = load_pose_config(profile=pose_profile).lost_windows
        self.scan_config = ScanMatchConfig()

    def _scan(self, t_s: float) -> Any:
        for start, duration in self.lost_windows:
            if start <= t_s < start + duration:
                return None
        observation = getattr(self.world, "last_observation", None)
        if observation is None:
            return None
        return scan_frame_from_ranges(
            observation.lidar_ranges,
            angle_min_rad=observation.lidar_angle_min_rad,
            angle_increment_rad=observation.lidar_angle_increment_rad,
            range_min_m=observation.lidar_range_min_m,
            range_max_m=observation.lidar_range_max_m,
            stamp_s=t_s,
        )

    def new_pose_provider(self) -> Any:
        inner = super().new_pose_provider()
        provider = RecordingProvider(
            ScanMatchLocalizer(self.scan_config), inner, scan_source=self._scan
        )
        self.last_pose_provider = provider
        return provider


class H7Runner(NavInstructRunner):
    """``NavInstructRunner`` with the tapped world and the composed provider."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.pose_drift_profile is None:
            return
        self.world = TappedCityWorld()
        self.scene = str(self.world.scene)
        self.harness = H7DriftHarness(
            self.world,
            robot_config=self.robot_config,
            pose_profile=self.pose_drift_profile,
        )

    def run_episode(self, episode: Any) -> Any:
        result = super().run_episode(episode)
        provider = getattr(self.harness, "last_pose_provider", None)
        if isinstance(provider, RecordingProvider):
            TELEMETRY.append(
                {
                    "profile": self.pose_drift_profile,
                    "episode_id": episode.episode_id,
                    "map_health": dict(provider.map_health),
                    "map_events": dict(provider.map_events),
                    "max_jump_m": provider.max_jump_m,
                    "updates": provider.updates,
                }
            )
        return result


def _telemetry_by_arm() -> dict[str, dict[str, Any]]:
    """Aggregate the per-episode MAP telemetry into one block per rung."""

    out: dict[str, dict[str, Any]] = {}
    for row in TELEMETRY:
        block = out.setdefault(
            str(row["profile"]),
            {
                "episodes": 0,
                "map_health": Counter(),
                "map_events": Counter(),
                "max_jump_m": 0.0,
                "episodes_with_map_lost": 0,
                "episodes_with_map_degraded": 0,
                "updates": 0,
            },
        )
        block["episodes"] += 1
        block["updates"] += int(row["updates"])
        block["map_health"].update(row["map_health"])
        block["map_events"].update(row["map_events"])
        block["max_jump_m"] = max(block["max_jump_m"], float(row["max_jump_m"]))
        if row["map_health"].get(PoseHealth.LOST.value):
            block["episodes_with_map_lost"] += 1
        if row["map_health"].get(PoseHealth.DEGRADED.value):
            block["episodes_with_map_degraded"] += 1
    return {
        name: {**block, "map_health": dict(block["map_health"]),
               "map_events": dict(block["map_events"])}
        for name, block in out.items()
    }


def run_pass(*, localized: bool, arms: tuple[str | None, ...], limit: int) -> dict[str, Any]:
    """One full sweep of the ladder, stock or localized."""

    TELEMETRY.clear()
    original = run_drift_arms.NavInstructRunner
    if localized:
        run_drift_arms.NavInstructRunner = H7Runner  # type: ignore[misc]
    try:
        payload = run_drift_arms.run_stage("a", limit=limit, arms=arms)
    finally:
        run_drift_arms.NavInstructRunner = original  # type: ignore[misc]
    payload["pass"] = "localized" if localized else "stock"
    payload["map_telemetry"] = _telemetry_by_arm() if localized else {}
    return payload


def compare(stock: dict[str, Any], localized: dict[str, Any]) -> str:
    """The L6 table: one line per rung, stock beside localized."""

    stock_rows = {str(row["profile"]): row for row in stock["arms"]}
    header = (
        "| rung | SR stock | SR localized | false arrivals (stock/loc) | collisions | "
        "authority_disagreement (stock/loc) | MAP lost ticks | max jump m |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|"]
    for row in localized["arms"]:
        name = str(row["profile"])
        other = stock_rows.get(name, {})
        telemetry = localized["map_telemetry"].get(name, {})
        health = telemetry.get("map_health", {})
        lines.append(
            f"| `{name}` | {other.get('sr', float('nan')):.4f} | {row['sr']:.4f} | "
            f"{other.get('false_arrival', '-')}/{row['false_arrival']} | "
            f"{row['collision_total']} | "
            f"{other.get('authority_histogram', {}).get('authority_disagreement', '-')}/"
            f"{row['authority_histogram'].get('authority_disagreement', 0)} | "
            f"{health.get('lost', 0)} | {telemetry.get('max_jump_m', 0.0):.3f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--passes", default="stock,localized")
    args = parser.parse_args(argv)
    wanted = {name.strip() for name in args.passes.split(",")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, Any] = {}
    if "stock" in wanted:
        payloads["stock"] = run_pass(localized=False, arms=STOCK_ARMS, limit=args.limit)
        _write(payloads["stock"], f"consumers-stock-{stamp}.json")
        print(run_drift_arms.markdown_table(payloads["stock"]))
    if "localized" in wanted:
        payloads["localized"] = run_pass(localized=True, arms=LADDER, limit=args.limit)
        _write(payloads["localized"], f"consumers-localized-{stamp}.json")
        print(run_drift_arms.markdown_table(payloads["localized"]))
    if len(payloads) == 2:
        print()
        print(compare(payloads["stock"], payloads["localized"]))
    for name, payload in payloads.items():
        for problem in payload["problems"]:
            print(f"RED[{name}]: {problem}")
    return 0


def _write(payload: dict[str, Any], name: str) -> Path:
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"-> {path}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
