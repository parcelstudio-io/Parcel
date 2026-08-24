"""CLI for FOLLOW_BENCH_YIELD_EXT — the additive yield-aside measurement tier.

Card Y-3 (``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §4.2/§6). This is a
SEPARATE bench from FOLLOW_BENCH_V1: its own suite id, its own scenarios, and
its own results namespace (``results/yield-ext-*``, ledger
``results/yield-ext-ledger.jsonl``). It never writes ``results/ledger.jsonl``
and never touches a FOLLOW_BENCH_V1 report, because those rows are pinned by
the hard-safety gate and by FOLLOW_BENCH_POST_SPEED.

The run is a PRE-REGISTERED two-stage measurement, and the stages are executed
in one invocation so a report cannot quietly contain a stage-B run with no
stage-A baseline beside it:

* **Stage A** (flag OFF) records the baseline for both new cells and checks the
  premise the tier exists to test: ``pedestrian_oncoming_group`` must show the
  displacement failure — the robot's stance INSIDE the group's swept corridor
  at closest approach, band below 0.60. If it does not, the scenario is
  redesigned before any flag-on number is looked at.
* **Stage B** (flag ON) re-runs the same geometry with the yield-aside enabled
  and scores it against the thresholds registered in the design record:
  oncoming band >= stage-A band + 0.15 with the stance outside the swept
  corridor by >= ``person_stop_m``; wide band >= 0.75; both cells with zero
  hard collisions, zero pedestrian contact, zero intimate-space time and a
  per-episode minimum pedestrian surface of at least 1.2 m.
* **V1 regression** (flag ON, all eleven FOLLOW_BENCH_V1 cells) checks that the
  flag, if it were ever switched on, does not move the frozen suite: no episode
  band lower than the dd2e857 row by more than 0.01, no per-episode pedestrian
  surface decrease, aggregate ``min_pedestrian_surface_m`` unchanged, dwell
  within 2.3 s, zero collisions.

A miss on any registered threshold is a STOP-and-report with attribution, not
a retune: the report carries ``verdict`` and ``misses`` and the exit code is
non-zero, but the numbers are written either way.

Usage:
    .parcel/bin/python -m evals.companion_nav.run_follow_bench_yield \\
        --out evals/companion_nav/results

``does_not_prove``: everything FOLLOW_BENCH_V1's report disclaims (headless
kinematic base, scripted non-reactive pedestrians, raycast LiDAR, oracle owner
track) plus two of this tier's own — a scripted pedestrian that walks through a
stopped robot scores ``pedestrian_contact`` that a reactive human would never
produce, and the reactive gate's people list still carries one stranger scalar,
so multi-stranger rejection lives in the proposer and not in the gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

from evals.companion_nav.metrics import EpisodeMetrics, compute_episode_metrics
from evals.companion_nav.runner import (
    CONTROL_DT_S,
    GRID_MODEL_ID,
    RUNNER_VERSION,
    BenchFeatures,
    FollowBenchRunner,
)
from evals.companion_nav.scenarios import (
    FOLLOW_BENCH_V1,
    FOLLOW_BENCH_YIELD_EXT,
    Scenario,
    interpolate_position,
)
from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE

SUITE = "follow-bench-yield-ext"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
REPORT_PREFIX = "yield-ext"

#: The committed dd2e857 FOLLOW_BENCH_V1 row this tier regresses against.
V1_PINNED_AGGREGATE_MIN_PEDESTRIAN_SURFACE_M = 0.5299999999999998
V1_PINNED_DWELL_S = 2.3

#: Stage-B thresholds, from the design record §6 card Y-3. The one number that
#: is NOT here is the oncoming band floor: it is stage A's measurement plus
#: 0.15, computed in this run so it cannot be back-fitted.
ONCOMING_BAND_MARGIN = 0.15
WIDE_BAND_FLOOR = 0.75
MIN_EPISODE_PEDESTRIAN_SURFACE_M = 1.2
#: How far outside the swept corridor a yielded stance has to end up.
STANCE_CLEARANCE_FLOOR_M = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)

DOES_NOT_PROVE = (
    (
        "real-sensor or real-robot performance (headless kinematic base, oracle "
        "owner track, raycast LiDAR with modeled noise only)"
    ),
    (
        "behavior around reactive humans: the scripted pedestrians never yield, "
        "so a stopped robot in their lane is walked through and scores "
        "pedestrian_contact that a reactive human would never produce"
    ),
    (
        "multi-stranger protection by the reactive gate (its people list is one "
        "stranger scalar plus the owner); rejecting over the whole track set is "
        "the proposer's job and is proven in tests/test_yield_aside.py, not here"
    ),
    (
        "anything about FOLLOW_BENCH_V1's frozen rows beyond the regression arm "
        "recorded in this report; this tier never writes the V1 ledger"
    ),
    (
        "real corridor traversability: the proposer's free-range check is a "
        "planar-scan proxy, and this world has no curbs, drops or doors"
    ),
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "")


def swept_corridor_clearance_m(scenario: Scenario, x: float, y: float) -> float:
    """Surface clearance from one point to every pedestrian's whole swept path.

    The "swept corridor" is the union of the group's scripted positions over the
    episode; a negative result means the point is inside it — the robot stood
    where the group was going to walk.
    """

    worst = math.inf
    samples = int(scenario.duration_s / CONTROL_DT_S) + 1
    for pedestrian in scenario.pedestrians:
        for index in range(samples):
            moment = index * CONTROL_DT_S
            ped_x, ped_y = interpolate_position(pedestrian.waypoints, moment)
            worst = min(worst, math.hypot(x - ped_x, y - ped_y) - pedestrian.radius_m)
    return worst


def validate_free_space(scenarios: tuple[Scenario, ...]) -> list[str]:
    """Re-run the V1 scenario-table free-space check over the new tier.

    ``tests/test_follow_bench_v1.py`` validates FOLLOW_BENCH_V1 only, and this
    card does not own that file, so the same check runs here on every
    invocation instead of being asserted nowhere.
    """

    from parcel_robot.simulation.headless_city import HeadlessCityWorld

    world = HeadlessCityWorld()
    world.reset(robot=(0.0, 0.0, 0.0), owner=(1.0, 0.0))
    owner_radius_m = 0.3
    problems: list[str] = []
    for scenario in scenarios:
        start = world.truth_minimum_clearance(scenario.robot_start[0], scenario.robot_start[1])
        if start <= 0.05:
            problems.append(f"{scenario.scenario_id}: robot start clearance {start:.3f}")
        samples = int(scenario.duration_s / 0.5) + 1
        for index in range(samples):
            moment = index * 0.5
            owner_x, owner_y = interpolate_position(scenario.owner_waypoints, moment)
            clearance = world.truth_minimum_clearance(owner_x, owner_y)
            if clearance <= (owner_radius_m - world.robot_radius_m) + 0.05:
                problems.append(
                    f"{scenario.scenario_id}: owner clearance {clearance:.3f} at t={moment}"
                )
            for pedestrian in scenario.pedestrians:
                ped_x, ped_y = interpolate_position(pedestrian.waypoints, moment)
                clearance = world.truth_minimum_clearance(ped_x, ped_y)
                if clearance <= (pedestrian.radius_m - world.robot_radius_m) + 0.05:
                    problems.append(
                        f"{scenario.scenario_id}: {pedestrian.agent_id} clearance "
                        f"{clearance:.3f} at t={moment}"
                    )
    return problems


def _episode_payload(scenario: Scenario, result, metrics: EpisodeMetrics) -> dict[str, object]:
    """One episode's metrics plus the two stance quantities this tier scores on."""

    steps = result.steps
    surfaces = [
        (step.nearest_pedestrian_surface_m, index)
        for index, step in enumerate(steps)
        if step.nearest_pedestrian_surface_m is not None
    ]
    payload = dict(metrics.payload())
    if surfaces:
        _value, index = min(surfaces)
        closest = steps[index]
        payload["closest_approach_time_s"] = round(closest.time_s, 3)
        payload["closest_approach_x_m"] = round(closest.robot_x, 4)
        payload["closest_approach_y_m"] = round(closest.robot_y, 4)
        payload["stance_swept_corridor_clearance_m"] = round(
            swept_corridor_clearance_m(scenario, closest.robot_x, closest.robot_y), 4
        )
    payload["max_owner_distance_m"] = round(max(step.owner_distance_m for step in steps), 4)
    payload["step_count"] = len(steps)
    # NOT recorded here: how many steps the proposer was active for. That would
    # need a field on ``metrics.StepRecord``, which this card does not own; the
    # per-step engagement histogram is a scratch diagnostic quoted in
    # Y-3_STATUS.md, and folding it into the record is a named handoff.
    return payload


def run_arm(
    scenarios: tuple[Scenario, ...],
    *,
    robot_config: Path,
    yield_aside: bool,
) -> list[dict[str, object]]:
    features = BenchFeatures(yield_aside=yield_aside)
    runner = FollowBenchRunner(robot_config=robot_config, features=features)
    payloads: list[dict[str, object]] = []
    for scenario in scenarios:
        result = runner.run(scenario)
        metrics = compute_episode_metrics(result, scenario)
        payload = _episode_payload(scenario, result, metrics)
        payloads.append(payload)
        print(
            f"  {scenario.scenario_id}: band={payload.get('band_fraction')} "
            f"min_ped_surface={payload.get('min_pedestrian_surface_m')}"
        )
    return payloads


def _by_id(payloads: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["scenario_id"]): item for item in payloads}


def score(
    stage_a: list[dict[str, object]],
    stage_b: list[dict[str, object]],
    v1_regression: list[dict[str, object]],
    v1_reference: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Apply the pre-registered thresholds. Returns the verdict and every miss."""

    a = _by_id(stage_a)
    b = _by_id(stage_b)
    misses: list[str] = []

    oncoming_a = a["pedestrian_oncoming_group"]
    stage_a_ok = (
        float(oncoming_a["band_fraction"]) < 0.60
        and float(oncoming_a["stance_swept_corridor_clearance_m"]) < 0.0
    )
    if not stage_a_ok:
        misses.append(
            "STAGE A: pedestrian_oncoming_group did not show the displacement "
            f"failure (band {oncoming_a['band_fraction']}, stance corridor "
            f"clearance {oncoming_a['stance_swept_corridor_clearance_m']}); the "
            "scenario needs redesign before any flag-on number is read"
        )

    oncoming_floor = round(float(oncoming_a["band_fraction"]) + ONCOMING_BAND_MARGIN, 6)
    oncoming_b = b["pedestrian_oncoming_group"]
    if float(oncoming_b["band_fraction"]) < oncoming_floor:
        misses.append(
            f"STAGE B: pedestrian_oncoming_group band {oncoming_b['band_fraction']} "
            f"< stage-A + {ONCOMING_BAND_MARGIN} = {oncoming_floor}"
        )
    if float(oncoming_b["stance_swept_corridor_clearance_m"]) < STANCE_CLEARANCE_FLOOR_M:
        misses.append(
            "STAGE B: pedestrian_oncoming_group stance corridor clearance "
            f"{oncoming_b['stance_swept_corridor_clearance_m']} < "
            f"{STANCE_CLEARANCE_FLOOR_M}"
        )
    wide_b = b["pedestrian_group_wide"]
    if float(wide_b["band_fraction"]) < WIDE_BAND_FLOOR:
        misses.append(
            f"STAGE B: pedestrian_group_wide band {wide_b['band_fraction']} < {WIDE_BAND_FLOOR}"
        )
    for payload in stage_b:
        name = payload["scenario_id"]
        if payload.get("hard_collision_count"):
            misses.append(f"STAGE B: {name} hard_collision_count {payload['hard_collision_count']}")
        if payload.get("pedestrian_contact_count"):
            misses.append(
                f"STAGE B: {name} pedestrian_contact_count {payload['pedestrian_contact_count']}"
            )
        if float(payload.get("intimate_space_time_s") or 0.0) > 0.0:
            misses.append(
                f"STAGE B: {name} intimate_space_time_s {payload['intimate_space_time_s']}"
            )
        surface = payload.get("min_pedestrian_surface_m")
        if surface is not None and float(surface) < MIN_EPISODE_PEDESTRIAN_SURFACE_M:
            misses.append(
                f"STAGE B: {name} min_pedestrian_surface_m {surface} "
                f"< {MIN_EPISODE_PEDESTRIAN_SURFACE_M}"
            )

    surfaces = [
        float(item["min_pedestrian_surface_m"])
        for item in v1_regression
        if item.get("min_pedestrian_surface_m") is not None
    ]
    aggregate_surface = min(surfaces, default=None)
    if aggregate_surface != V1_PINNED_AGGREGATE_MIN_PEDESTRIAN_SURFACE_M:
        misses.append(
            f"V1 REGRESSION: aggregate min_pedestrian_surface_m {aggregate_surface} != "
            f"{V1_PINNED_AGGREGATE_MIN_PEDESTRIAN_SURFACE_M}"
        )
    dwell = round(sum(float(item["personal_space_time_s"]) for item in v1_regression), 3)
    if dwell > V1_PINNED_DWELL_S:
        misses.append(f"V1 REGRESSION: personal_space_time_total_s {dwell} > {V1_PINNED_DWELL_S}")
    for payload in v1_regression:
        name = str(payload["scenario_id"])
        reference = v1_reference.get(name)
        if payload.get("hard_collision_count"):
            misses.append(f"V1 REGRESSION: {name} hard_collision_count")
        if reference is None:
            continue
        band = payload.get("band_fraction")
        reference_band = reference.get("band_fraction")
        if (
            band is not None
            and reference_band is not None
            and float(reference_band) - float(band) > 0.01
        ):
            misses.append(
                f"V1 REGRESSION: {name} band {band} below reference {reference_band} by "
                f"{float(reference_band) - float(band):.4f}"
            )
        surface = payload.get("min_pedestrian_surface_m")
        reference_surface = reference.get("min_pedestrian_surface_m")
        if (
            surface is not None
            and reference_surface is not None
            and float(surface) < float(reference_surface)
        ):
            misses.append(
                f"V1 REGRESSION: {name} min_pedestrian_surface_m {surface} below "
                f"reference {reference_surface}"
            )
    return {
        "verdict": "PASS" if not misses else "STOP-AND-REPORT",
        "misses": misses,
        "registered": {
            "oncoming_band_floor": oncoming_floor,
            "oncoming_band_margin": ONCOMING_BAND_MARGIN,
            "oncoming_stance_clearance_floor_m": STANCE_CLEARANCE_FLOOR_M,
            "wide_band_floor": WIDE_BAND_FLOOR,
            "min_episode_pedestrian_surface_m": MIN_EPISODE_PEDESTRIAN_SURFACE_M,
            "v1_aggregate_min_pedestrian_surface_m": (
                V1_PINNED_AGGREGATE_MIN_PEDESTRIAN_SURFACE_M
            ),
            "v1_dwell_ceiling_s": V1_PINNED_DWELL_S,
        },
        "measured": {
            "stage_a_oncoming_band": oncoming_a["band_fraction"],
            "stage_b_oncoming_band": oncoming_b["band_fraction"],
            "stage_a_wide_band": a["pedestrian_group_wide"]["band_fraction"],
            "stage_b_wide_band": wide_b["band_fraction"],
            "v1_aggregate_min_pedestrian_surface_m": aggregate_surface,
            "v1_personal_space_time_total_s": dwell,
        },
    }


def load_v1_reference(path: Path | None) -> dict[str, dict[str, object]]:
    """Per-episode reference rows from a committed FOLLOW_BENCH_V1 report."""

    if path is None or not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["scenario_id"]): item for item in report.get("episodes", [])}


def write_report(report: dict[str, object], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    stamp = "".join(
        character for character in str(report["generated_at_utc"]) if character.isdigit()
    )[:14]
    nonce = hashlib.sha256(
        f"{report['generated_at_utc']}:{time.monotonic_ns()}".encode()
    ).hexdigest()[:8]
    path = results_dir / f"{REPORT_PREFIX}-{stamp}Z-{nonce}.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {path}")
    path.write_text(serialized, encoding="utf-8")
    scoring = dict(report["scoring"])  # type: ignore[arg-type]
    ledger_line = {
        "utc": report["generated_at_utc"],
        "report": path.name,
        "suite": SUITE,
        "verdict": scoring["verdict"],
        "miss_count": len(scoring["misses"]),
        "measured": scoring["measured"],
    }
    ledger = results_dir / f"{REPORT_PREFIX}-ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(ledger_line, sort_keys=True, allow_nan=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="results directory for this tier's report and its own ledger",
    )
    parser.add_argument(
        "--robot-config",
        type=Path,
        default=REPO_ROOT / "configs" / "robot.yaml",
        help="production robot configuration used to build the controllers",
    )
    parser.add_argument(
        "--v1-reference",
        type=Path,
        default=(
            DEFAULT_RESULTS_DIR / "follow-bench-v1-20260811023618Z-93eba090.json"
        ),
        help="committed FOLLOW_BENCH_V1 report the regression arm compares against",
    )
    args = parser.parse_args(argv)

    problems = validate_free_space(FOLLOW_BENCH_YIELD_EXT)
    if problems:
        for problem in problems:
            print(f"scenario validation: {problem}")
        raise SystemExit("FOLLOW_BENCH_YIELD_EXT actors are not on free space")

    print("stage A (flag OFF):")
    stage_a = run_arm(FOLLOW_BENCH_YIELD_EXT, robot_config=args.robot_config, yield_aside=False)
    print("stage B (flag ON):")
    stage_b = run_arm(FOLLOW_BENCH_YIELD_EXT, robot_config=args.robot_config, yield_aside=True)
    print("V1 regression (flag ON, all 11):")
    v1_regression = run_arm(FOLLOW_BENCH_V1, robot_config=args.robot_config, yield_aside=True)

    scoring = score(stage_a, stage_b, v1_regression, load_v1_reference(args.v1_reference))
    report = {
        "suite": SUITE,
        "runner_version": RUNNER_VERSION,
        "navigator_model_id": GRID_MODEL_ID,
        "control_dt_s": CONTROL_DT_S,
        "generated_at_utc": _utc_timestamp(),
        "robot_config": str(args.robot_config),
        "features_stage_a": {
            item.name: getattr(BenchFeatures(yield_aside=False), item.name)
            for item in fields(BenchFeatures)
        },
        "features_stage_b": {
            item.name: getattr(BenchFeatures(yield_aside=True), item.name)
            for item in fields(BenchFeatures)
        },
        "scenario_ids": [item.scenario_id for item in FOLLOW_BENCH_YIELD_EXT],
        "stage_a": stage_a,
        "stage_b": stage_b,
        "v1_regression": v1_regression,
        "v1_reference_report": str(args.v1_reference.name),
        "scoring": scoring,
        "does_not_prove": list(DOES_NOT_PROVE),
    }
    path = write_report(report, args.out)
    print(f"report: {path}")
    print(f"verdict: {scoring['verdict']}")
    for miss in scoring["misses"]:
        print(f"  miss: {miss}")
    return 0 if scoring["verdict"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
