"""H7 rows L1-L5, L7 and L8: the contract, measured on scripted sim traverses.

One entry point (``python bench.py``), one JSON artifact per arm under
``results/``.  Every number in RESULTS.md comes out of here; nothing is typed
in by hand.

**The arms.**  ``nominal`` walks each scene's 60 m circuit with scans at 10 Hz.
``dropout`` is the same walk with the sensor silent for 10 s.  ``teleport``
kidnaps the body 20 m back along the circuit at t = 30 s — the odometry feed
stays continuous across the jump (that is what makes it a kidnapping rather
than a fast walk), so the only evidence the localizer has is that its scan
stopped matching.  ``fake_quadruped`` re-runs the nominal arm with a completely
different ODOM implementation.

**What the localizer is allowed to see.**  Scans, and the ODOM pose.  Sim truth
reaches the ODOM source only.  The bench holds truth to score against, and the
scoring code and the provider share no state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fake_quadruped import FakeQuadrupedOdom
from traverse import CIRCUITS, CONTROL_HZ, SceneTraverse, build_scan_frame, traverse_poses

from parcel_robot.localization.contract import compose_se2, invert_se2, wrap_angle
from parcel_robot.localization.gicp_provider import ScanMatchConfig, ScanMatchLocalizer
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.pose import Frame, PoseHealth, provider_from_config

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SCAN_SEED = 20260823
ODOM_PROFILE = "calibrated_go2"

#: Pre-registered fault schedules.  Fixed here before any arm was run.
DROPOUT_WINDOW_S = (20.0, 10.0)
TELEPORT_AT_S = 30.0
#: The pre-registered kidnapping: back to the circuit sample 20 m of PATH
#: earlier, which is 6.3 m of Euclidean displacement on city_block and 3.1 m on
#: city_block_b.  Deliberately mapped ground, so relocalization is possible.
TELEPORT_BACK_INDEX = 100
#: POST-HOC arm, added after the pre-registered one showed a 6.3 m kidnapping
#: being silently tracked: land on the circuit sample FARTHEST from where the
#: body was, so the "is a teleport reported as LOST" question is asked of an
#: unambiguous displacement.  Reported separately; it does not stand in for the
#: pre-registered L4 row.
TELEPORT_MODES = ("back", "far")

#: KITTI-style relative-pose sub-segment length for the L2 yaw row.
RPE_SEGMENT_M = 1.0


def _landing_index(poses: list[Any], cut: int, mode: str) -> int:
    """Which circuit sample the body is kidnapped onto."""

    if mode == "back":
        return TELEPORT_BACK_INDEX
    anchor = poses[cut - 1]
    reachable = range(len(poses) - (len(poses) - cut) + 1)
    return max(
        reachable,
        key=lambda index: math.hypot(
            poses[index].x - anchor.x, poses[index].y - anchor.y
        ),
    )


def _truth_track(
    scene: str,
    *,
    teleport: str | None,
) -> list[tuple[float, tuple[float, float, float], tuple[float, float, float]]]:
    """``(t_s, truth_pose, odom_feed_pose)`` per tick, teleport folded in.

    The ODOM feed stays continuous across the jump: it is the post-teleport
    truth re-expressed relative to the landing pose and re-attached at the
    pose the body left.  Proprioception cannot see a kidnapping, and a bench
    that let it see one would be testing nothing.
    """

    poses = traverse_poses(scene)
    if teleport is None:
        return [(p.t_s, p.xy_yaw, p.xy_yaw) for p in poses]
    if teleport not in TELEPORT_MODES:
        raise ValueError(f"unknown teleport mode {teleport!r}")
    cut = round(TELEPORT_AT_S * CONTROL_HZ)
    track = [(p.t_s, p.xy_yaw, p.xy_yaw) for p in poses[:cut]]
    anchor = poses[cut - 1].xy_yaw
    index = _landing_index(poses, cut, teleport)
    landing = poses[index].xy_yaw
    remaining = len(poses) - cut
    if index + remaining > len(poses):
        raise ValueError("teleport landing would wrap past the end of the circuit")
    for step in range(remaining):
        pose = poses[index + step].xy_yaw
        feed = compose_se2(anchor, compose_se2(invert_se2(landing), pose))
        track.append(((cut + step) / CONTROL_HZ, pose, feed))
    return track


def teleport_displacement_m(scene: str, mode: str) -> float:
    """Euclidean distance the body is moved — the size of the injection."""

    poses = traverse_poses(scene)
    cut = round(TELEPORT_AT_S * CONTROL_HZ)
    anchor = poses[cut - 1]
    landing = poses[_landing_index(poses, cut, mode)]
    return math.hypot(landing.x - anchor.x, landing.y - anchor.y)


def run_arm(
    scene: str,
    *,
    arm: str,
    odom_factory: Callable[[], Any],
    dropout: bool = False,
    teleport: str | None = None,
    config: ScanMatchConfig | None = None,
) -> dict[str, Any]:
    """Walk one traverse and return every per-tick row plus the arm's metrics."""

    track = _truth_track(scene, teleport=teleport)
    world = SceneTraverse(scene)
    rng = np.random.default_rng(SCAN_SEED)
    localizer = ScanMatchLocalizer(config or ScanMatchConfig())
    holder: dict[str, Any] = {"scan": None}
    provider = LocalizedPoseProvider(
        localizer, odom_factory(), scan_source=lambda _t: holder["scan"]
    )
    provider.reset()
    rows: list[dict[str, Any]] = []
    for t_s, truth, feed in track:
        world.place(*truth)
        silent = dropout and DROPOUT_WINDOW_S[0] <= t_s < sum(DROPOUT_WINDOW_S)
        holder["scan"] = (
            None if silent else build_scan_frame(world.scan(*truth, rng), t_s)
        )
        started = time.perf_counter()
        provider.update_truth(*feed, stamp_monotonic_s=t_s)
        latency_ms = (time.perf_counter() - started) * 1e3
        rows.append(_row(provider, truth, t_s, latency_ms, silent, localizer))
    payload: dict[str, Any] = {
        "arm": arm,
        "scene": scene,
        "odom": type(provider.odom).__name__,
        "odom_profile": ODOM_PROFILE if isinstance(provider.odom, object) else "",
        "config": _config_dict(localizer.config),
        "ticks": len(rows),
        "keyframes": localizer.keyframe_count,
        "metrics": metrics(rows),
        "rows": rows,
    }
    if dropout or teleport:
        payload["events"] = fault_events(rows, dropout=dropout, teleport=teleport)
        if teleport:
            payload["events"]["teleport"]["displacement_m"] = teleport_displacement_m(
                scene, teleport
            )
            payload["events"]["teleport"]["mode"] = teleport
    return payload


def _row(
    provider: LocalizedPoseProvider,
    truth: tuple[float, float, float],
    t_s: float,
    latency_ms: float,
    silent: bool,
    localizer: ScanMatchLocalizer,
) -> dict[str, Any]:
    map_pose = provider.get_pose(Frame.MAP)
    odom_pose = provider.get_pose(Frame.ODOM)
    update = provider.last_update
    return {
        "t_s": round(t_s, 4),
        "truth": [round(value, 6) for value in truth],
        "map": [round(map_pose.x, 6), round(map_pose.y, 6), round(map_pose.yaw, 6)],
        "odom": [round(odom_pose.x, 6), round(odom_pose.y, 6), round(odom_pose.yaw, 6)],
        "health": map_pose.health.value,
        "jump_m": round(float(update.jump_m) if update else 0.0, 6),
        "cov": [round(value, 12) for value in map_pose.covariance],
        "latency_ms": round(latency_ms, 4),
        "scan": not silent,
        "event": localizer.diagnostics.get("event", ""),
    }


def _config_dict(config: ScanMatchConfig) -> dict[str, Any]:
    return {
        key: (list(value) if isinstance(value, tuple) else value)
        for key, value in vars(config).items()
    }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def _errors(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [math.hypot(row[key][0] - row["truth"][0], row[key][1] - row["truth"][1]) for row in rows]


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """L1/L2/L3/L5/L7 for one arm, plus the ODOM-only baseline for contrast."""

    map_errors = _errors(rows, "map")
    odom_errors = _errors(rows, "odom")
    jumps = [float(row["jump_m"]) for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    healthy = [row for row in rows if row["health"] == PoseHealth.HEALTHY.value]
    healthy_errors = _errors(healthy, "map") if healthy else []
    histogram: dict[str, int] = {}
    for row in rows:
        histogram[row["health"]] = histogram.get(row["health"], 0) + 1
    return {
        "ate_rmse_m": _rms(map_errors),
        "ate_rmse_healthy_m": _rms(healthy_errors),
        "ate_max_m": max(map_errors, default=0.0),
        "ate_final_m": map_errors[-1] if map_errors else 0.0,
        "odom_ate_rmse_m": _rms(odom_errors),
        "odom_final_m": odom_errors[-1] if odom_errors else 0.0,
        "rpe_yaw_deg_per_m": _rpe_yaw(rows),
        "rpe_trans_pct": _rpe_translation(rows),
        "jump_max_m": max(jumps, default=0.0),
        "jump_p95_m": _percentile(jumps, 95),
        "jump_mean_m": statistics.fmean(jumps) if jumps else 0.0,
        "jump_nonzero": sum(1 for value in jumps if value > 1e-9),
        "nees": _nees(healthy),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "latency_max_ms": max(latencies, default=0.0),
        "health_histogram": histogram,
    }


def _rms(values: list[float]) -> float:
    return math.sqrt(statistics.fmean([value * value for value in values])) if values else 0.0


def _percentile(values: list[float], pct: float) -> float:
    return float(np.percentile(values, pct)) if values else 0.0


def _segment_pairs(rows: list[dict[str, Any]], segment_m: float) -> list[tuple[int, int]]:
    """Index pairs whose TRUTH path length is closest to ``segment_m``."""

    cumulative = [0.0]
    for index in range(1, len(rows)):
        step = math.hypot(
            rows[index]["truth"][0] - rows[index - 1]["truth"][0],
            rows[index]["truth"][1] - rows[index - 1]["truth"][1],
        )
        cumulative.append(cumulative[-1] + step)
    pairs = []
    end = 0
    for start in range(len(rows)):
        while end < len(rows) and cumulative[end] - cumulative[start] < segment_m:
            end += 1
        if end >= len(rows):
            break
        pairs.append((start, end))
    return pairs


def _rpe_yaw(rows: list[dict[str, Any]], segment_m: float = RPE_SEGMENT_M) -> float:
    """RMS yaw error accumulated over ``segment_m`` of travel, in deg/m."""

    errors = []
    for start, end in _segment_pairs(rows, segment_m):
        truth_turn = wrap_angle(rows[end]["truth"][2] - rows[start]["truth"][2])
        map_turn = wrap_angle(rows[end]["map"][2] - rows[start]["map"][2])
        errors.append(abs(wrap_angle(map_turn - truth_turn)))
    if not errors:
        return 0.0
    return math.degrees(_rms(errors)) / segment_m


def _rpe_translation(rows: list[dict[str, Any]], segment_m: float = RPE_SEGMENT_M) -> float:
    errors = []
    for start, end in _segment_pairs(rows, segment_m):
        truth = _relative(rows[start]["truth"], rows[end]["truth"])
        estimate = _relative(rows[start]["map"], rows[end]["map"])
        errors.append(math.hypot(estimate[0] - truth[0], estimate[1] - truth[1]))
    if not errors:
        return 0.0
    return 100.0 * _rms(errors) / segment_m


def _relative(
    start: list[float] | tuple[float, ...],
    end: list[float] | tuple[float, ...],
) -> tuple[float, float, float]:
    return compose_se2(invert_se2(tuple(start)), tuple(end))  # type: ignore[arg-type]


def _nees(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalised estimation error squared against the published covariance."""

    values = []
    for row in rows:
        error = np.array(
            [
                row["map"][0] - row["truth"][0],
                row["map"][1] - row["truth"][1],
                wrap_angle(row["map"][2] - row["truth"][2]),
            ]
        )
        cov = np.array(row["cov"], dtype=np.float64).reshape(3, 3)
        try:
            values.append(float(error @ np.linalg.solve(cov, error)))
        except np.linalg.LinAlgError:
            continue
    if not values:
        return {"n": 0}
    mean = statistics.fmean(values)
    return {
        "n": len(values),
        "mean": mean,
        "median": statistics.median(values),
        "anees": mean / 3.0,
        # The multiplier that would bring ANEES to 1.0 — a diagnostic for the
        # milestone ADR, never applied to the published covariance here.
        "inflation_to_consistent": math.sqrt(mean / 3.0),
    }


def fault_events(
    rows: list[dict[str, Any]],
    *,
    dropout: bool,
    teleport: str | None,
) -> dict[str, Any]:
    """Health-transition timings — the L4 row."""

    events: dict[str, Any] = {}
    if dropout:
        start = DROPOUT_WINDOW_S[0]
        resumed = sum(DROPOUT_WINDOW_S)
        degraded = _first(rows, lambda row: row["t_s"] >= start and row["health"] != "healthy")
        lost = _first(rows, lambda row: row["t_s"] >= start and row["health"] == "lost")
        recovered = _first(
            rows, lambda row: row["t_s"] >= resumed and row["health"] == "healthy"
        )
        events["dropout"] = {
            "window_s": list(DROPOUT_WINDOW_S),
            "first_non_healthy_s": degraded,
            "time_to_degraded_s": None if degraded is None else round(degraded - start, 3),
            "first_lost_s": lost,
            "recovered_s": recovered,
            "recovery_time_s": None if recovered is None else round(recovered - resumed, 3),
        }
    if teleport:
        lost = _first(
            rows, lambda row: row["t_s"] >= TELEPORT_AT_S and row["health"] == "lost"
        )
        recovered = _first(
            rows, lambda row: row["t_s"] >= TELEPORT_AT_S and row["health"] == "healthy"
        )
        after = [row for row in rows if row["t_s"] >= TELEPORT_AT_S]
        events["teleport"] = {
            "at_s": TELEPORT_AT_S,
            "first_lost_s": lost,
            "time_to_lost_s": None if lost is None else round(lost - TELEPORT_AT_S, 3),
            "recovered_s": recovered,
            "recovery_time_s": None if recovered is None else round(recovered - TELEPORT_AT_S, 3),
            "relocalized": any(row["event"] == "relocalized" for row in after),
            "relocalize_failures": sum(
                1 for row in after if row["event"] == "relocalize_failed"
            ),
            "max_jump_after_m": max((float(row["jump_m"]) for row in after), default=0.0),
            "ate_rmse_after_recovery_m": _rms(
                _errors(
                    [
                        row
                        for row in after
                        if recovered is not None and row["t_s"] >= recovered
                    ],
                    "map",
                )
            ),
        }
    return events


def _first(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> float | None:
    for row in rows:
        if predicate(row):
            return float(row["t_s"])
    return None


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def module_hashes() -> dict[str, str]:
    """sha256 of the three product modules, so L8 can prove they did not move."""

    root = HERE.parents[2] / "src" / "parcel_robot" / "localization"
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        for path in sorted(root.glob("*.py"))
    }


def _write(payload: dict[str, Any], name: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _summary(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    return (
        f"{payload['arm']:16s} {payload['scene']:14s} "
        f"ATE {m['ate_rmse_m']:.4f} m (odom {m['odom_ate_rmse_m']:.3f}) "
        f"yawRPE {m['rpe_yaw_deg_per_m']:.4f} deg/m  jump_max {m['jump_max_m']:.4f} m  "
        f"ANEES {m['nees'].get('anees', float('nan')):.1f}  "
        f"lat p50/p95 {m['latency_p50_ms']:.1f}/{m['latency_p95_ms']:.1f} ms  "
        f"health {m['health_histogram']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arms", default="nominal,dropout,teleport,teleport_far,fake_quadruped"
    )
    args = parser.parse_args(argv)
    wanted = {name.strip() for name in args.arms.split(",") if name.strip()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    written: list[str] = []
    for scene in CIRCUITS:
        plans = [
            ("nominal", {"dropout": False, "teleport": None}, _go2_odom),
            ("dropout", {"dropout": True, "teleport": None}, _go2_odom),
            ("teleport", {"dropout": False, "teleport": "back"}, _go2_odom),
            ("teleport_far", {"dropout": False, "teleport": "far"}, _go2_odom),
            ("fake_quadruped", {"dropout": False, "teleport": None}, FakeQuadrupedOdom),
        ]
        for arm, faults, factory in plans:
            if arm not in wanted:
                continue
            payload = run_arm(scene, arm=arm, odom_factory=factory, **faults)
            payload["generated_at"] = stamp
            payload["host"] = platform.node()
            payload["module_sha256"] = module_hashes()
            path = _write(payload, f"{arm}-{scene}-{stamp}.json")
            written.append(str(path))
            print(_summary(payload))
            if "events" in payload:
                print(f"    events: {json.dumps(payload['events'], sort_keys=True)}")
    print("\n".join(written))
    return 0


def _go2_odom() -> Any:
    return provider_from_config(profile=ODOM_PROFILE)


if __name__ == "__main__":
    raise SystemExit(main())
