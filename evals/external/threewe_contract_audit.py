"""Fail-closed audit of the pinned 3WE benchmark contract.

This module does not run a simulator or a Parcel policy.  It inspects the
immutable 3WE source revision adopted by the external-evaluation portfolio and
records whether that revision exposes a valid, injectable evaluation boundary.
The distinction matters: a benchmark implementation can be importable while
still being unable to produce a defensible navigation or percentile score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PARCEL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = PARCEL_ROOT / ".cache/external-evals/repos/threewe_robot_platform"
DEFAULT_SOURCE_LOCK = Path(__file__).with_name("sources.lock.json")
DEFAULT_PORTFOLIO = Path(__file__).with_name("targets") / "portfolio.json"
SOURCE_LOCK_KEY = "threewe_robot_platform"
PINNED_COMMIT = "6073a1bd0a30b6ca1348027ac35b05832b97bfe9"
SOURCE_URL = "https://github.com/telleroutlook/3we-robot-platform.git"

_FILES = {
    "docs": Path("docs/leaderboard.md"),
    "leaderboard": Path("data/leaderboard.json"),
    "runner": Path("sdk/threewe/src/threewe/benchmark/runner.py"),
    "objectnav": Path("sdk/threewe/src/threewe/benchmark/objectnav_runner.py"),
    "tasks": Path("sdk/threewe/src/threewe/benchmark/tasks.py"),
    "submission": Path("sdk/threewe/src/threewe/benchmark/leaderboard.py"),
    "ros2_backend": Path("sdk/threewe/src/threewe/backends/_ros2_node.py"),
    "mock_backend": Path("sdk/threewe/src/threewe/backends/mock.py"),
    "isaac_backend": Path("sdk/threewe/src/threewe/backends/isaac_sim.py"),
    "cli": Path("sdk/threewe/src/threewe/cli.py"),
    "baselines": Path("sdk/threewe/src/threewe/benchmark/baselines.py"),
    "robot_urdf": Path("ros2_ws/robot_description/urdf/robot.urdf.xacro"),
    "gazebo_urdf": Path("ros2_ws/robot_simulation/urdf/robot_gazebo.urdf.xacro"),
    "office_world": Path("ros2_ws/robot_simulation/worlds/office_v2.sdf"),
    "bridge": Path("ros2_ws/robot_simulation/config/bridge_params.yaml"),
    "scene_metadata": Path("sdk/threewe/src/threewe/scenes/office_v2/metadata.yaml"),
    "start_poses": Path("sdk/threewe/src/threewe/scenes/office_v2/start_poses.yaml"),
    "goal_poses": Path("sdk/threewe/src/threewe/scenes/office_v2/goal_poses.yaml"),
}


class ThreeWEAuditError(RuntimeError):
    """Raised when source provenance or an expected audit invariant drifts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThreeWEAuditError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ThreeWEAuditError(f"expected a JSON object at {path}")
    return value


def _git(source_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ThreeWEAuditError(f"cannot inspect 3WE checkout at {source_root}: {exc}") from exc
    return completed.stdout.strip()


def _line(text: str, fragment: str, *, label: str) -> int:
    matches = [index for index, value in enumerate(text.splitlines(), start=1) if fragment in value]
    if len(matches) != 1:
        raise ThreeWEAuditError(
            f"expected exactly one {label!r} fragment {fragment!r}; found {len(matches)}"
        )
    return matches[0]


def _lines(text: str, fragment: str, *, minimum: int = 1) -> list[int]:
    matches = [index for index, value in enumerate(text.splitlines(), start=1) if fragment in value]
    if len(matches) < minimum:
        raise ThreeWEAuditError(
            f"expected at least {minimum} occurrences of {fragment!r}; found {len(matches)}"
        )
    return matches


def _ref(relative_path: Path, line: int) -> str:
    return f"{relative_path.as_posix()}:{line}"


def _pose_manifest(text: str, *, label: str) -> list[tuple[float, float]]:
    matches = re.findall(r"x:\s*(-?[0-9.]+),\s*y:\s*(-?[0-9.]+)", text)
    if not matches:
        raise ThreeWEAuditError(f"{label} contains no parseable x/y poses")
    return [(float(x), float(y)) for x, y in matches]


def _finding(
    identifier: str,
    severity: str,
    summary: str,
    evidence: list[str],
    implication: str,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "severity": severity,
        "summary": summary,
        "evidence": evidence,
        "implication": implication,
    }


def audit_threewe_contract(
    source_root: str | Path = DEFAULT_SOURCE_ROOT,
    *,
    source_lock_path: str | Path = DEFAULT_SOURCE_LOCK,
    portfolio_path: str | Path = DEFAULT_PORTFOLIO,
    require_clean: bool = True,
    audit_id: str | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Audit the exact adopted 3WE revision without executing untrusted code."""

    source = Path(source_root).expanduser().resolve()
    if not source.is_dir():
        raise ThreeWEAuditError(
            f"pinned 3WE checkout is absent: {source}; run evals.external.fetch_sources first"
        )

    lock_path = Path(source_lock_path).expanduser().resolve()
    portfolio_file = Path(portfolio_path).expanduser().resolve()
    lock = _load_object(lock_path)
    sources = lock.get("sources")
    if not isinstance(sources, dict) or not isinstance(sources.get(SOURCE_LOCK_KEY), dict):
        raise ThreeWEAuditError(f"source lock has no {SOURCE_LOCK_KEY!r} object")
    locked = sources[SOURCE_LOCK_KEY]
    if locked.get("commit") != PINNED_COMMIT or locked.get("url") != SOURCE_URL:
        raise ThreeWEAuditError("3WE source-lock provenance drifted from the adopted revision")

    checkout_commit = _git(source, "rev-parse", "HEAD")
    if checkout_commit != PINNED_COMMIT:
        raise ThreeWEAuditError(
            f"3WE checkout is {checkout_commit!r}, expected immutable commit {PINNED_COMMIT}"
        )
    dirty_output = _git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if require_clean and dirty_output:
        raise ThreeWEAuditError("3WE checkout is dirty; refusing to audit mutable evaluator source")

    paths = {name: source / relative for name, relative in _FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ThreeWEAuditError(f"3WE audit inputs are missing: {missing}")
    texts = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}

    portfolio = _load_object(portfolio_file)
    unresolved = portfolio.get("unresolved_targets")
    if not isinstance(unresolved, list):
        raise ThreeWEAuditError("portfolio unresolved_targets must be a list")
    adopted = {
        item.get("id"): item
        for item in unresolved
        if isinstance(item, dict) and str(item.get("id", "")).startswith("threewe_")
    }
    expected_ids = {"threewe_pointnav", "threewe_objectnav", "threewe_exploration"}
    if set(adopted) != expected_ids:
        raise ThreeWEAuditError(f"adopted 3WE target set drifted: {sorted(adopted)}")
    if any(item.get("source_commit") != PINNED_COMMIT for item in adopted.values()):
        raise ThreeWEAuditError("portfolio and source-lock 3WE commits disagree")

    leaderboard = _load_object(paths["leaderboard"])
    entries = leaderboard.get("entries")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ThreeWEAuditError("3WE leaderboard entries must be JSON objects")
    snapshot_sha = _sha256(paths["leaderboard"])
    portfolio_snapshot_hashes = {
        item.get("leaderboard_snapshot", {}).get("sha256")
        for item in adopted.values()
        if isinstance(item.get("leaderboard_snapshot"), dict)
    }
    if portfolio_snapshot_hashes != {snapshot_sha}:
        raise ThreeWEAuditError("portfolio 3WE leaderboard snapshot hash does not match checkout")

    task_backend_counts = Counter(
        (str(item.get("task")), str(item.get("software", {}).get("backend")))
        for item in entries
        if isinstance(item.get("software"), dict)
    )
    task_counts = Counter(str(item.get("task")) for item in entries)

    docs = texts["docs"]
    runner = texts["runner"]
    objectnav = texts["objectnav"]
    tasks = texts["tasks"]
    submission = texts["submission"]
    ros2 = texts["ros2_backend"]
    mock = texts["mock_backend"]
    isaac = texts["isaac_backend"]
    cli = texts["cli"]
    baselines = texts["baselines"]
    robot_urdf = texts["robot_urdf"]
    gazebo_urdf = texts["gazebo_urdf"]
    office_world = texts["office_world"]
    bridge = texts["bridge"]
    scene_metadata = texts["scene_metadata"]
    start_poses_text = texts["start_poses"]
    goal_poses_text = texts["goal_poses"]

    # Fail closed if the exact evidence anchors disappear.  These are source
    # checks, not a regex approximation of benchmark behavior.
    docs_seed = _line(docs, "seed range `[0, 99]`", label="documented seed range")
    docs_timeouts = _line(
        docs,
        "PointNav: 60s, ObjectNav: 120s, Exploration: 180s.",
        label="documented timeouts",
    )
    docs_metrics_schema = _lines(docs, '"metrics": {', minimum=2)[0]
    docs_software_schema = _lines(docs, '"software": {', minimum=2)[0]
    runner_seed = _lines(runner, "seed: int = 42", minimum=2)[0]
    runner_timeout = _line(
        runner,
        "result = await robot.move_to(x=goal.x, y=goal.y, timeout=30.0)",
        label="PointNav timeout",
    )
    runner_success = _line(runner, "success=result.success", label="PointNav success")
    runner_robot = _lines(
        runner, "async with Robot(backend=self._backend, auto_connect=True) as robot:", minimum=2
    )[0]
    runner_explore_timeout = _line(
        runner, "timeout_per_episode: float = 120.0", label="Exploration timeout"
    )
    object_seed_lines = _lines(objectnav, "seed: int = 42", minimum=2)
    object_timeout_default = _line(
        objectnav, "timeout: float = 60.0", label="ObjectNav timeout default"
    )
    object_timeout_episode = _line(objectnav, "timeout=60.0", label="ObjectNav generated timeout")
    object_move = _line(
        objectnav, "x=config.target_position.x,", label="ObjectNav coordinate injection"
    )
    object_category = _line(
        objectnav,
        "category = task.object_categories[rng.integers(0, len(task.object_categories))]",
        label="ObjectNav category generation",
    )
    object_goal = _line(
        objectnav,
        "goal = scene.goal_poses[rng.integers(0, len(scene.goal_poses))]",
        label="ObjectNav position generation",
    )
    point_threshold = _line(
        tasks, "Success condition: robot reaches within 0.5m of goal.", label="PointNav threshold"
    )
    ros_distance = _line(ros2, "distance = math.sqrt(dx * dx + dy * dy)", label="ROS path length")
    ros_success_lines = _lines(ros2, "success=True", minimum=3)
    ros_explore_stub = _line(
        ros2,
        "Autonomous exploration stub — samples map coverage over a 1-second window only.",
        label="ROS exploration stub",
    )
    ros_explore_sleep = _line(
        ros2, "await asyncio.sleep(min(timeout, 1.0))", label="ROS exploration window"
    )
    mock_explore = _line(mock, "coverage=1.0", label="mock exploration coverage")
    submission_schema = _line(
        submission, '"success_rate": float,', label="implemented submission schema"
    )
    cli_episodes = _line(
        cli,
        'run_parser.add_argument("--episodes", type=int, default=100)',
        label="benchmark CLI episode option",
    )
    cli_submit = _line(
        cli,
        '"""Validate and display a leaderboard submission."""',
        label="submission command behavior",
    )
    cli_submit_success = _line(
        cli, 'print("Submission validated successfully!")', label="submission validation output"
    )
    isaac_constant_pose = _line(
        isaac, "return Pose2D(x=0.0, y=0.0, theta=0.0)", label="Isaac constant pose"
    )
    isaac_instant_goal = _line(
        isaac,
        "final_pose=Pose2D(x=x, y=y, theta=theta or 0.0),",
        label="Isaac instant goal",
    )
    isaac_import_failures = _lines(isaac, "except ImportError:", minimum=2)
    metadata_area = _line(scene_metadata, 'area: "20x15m"', label="scene metadata area")
    world_dimensions = _line(office_world, "15m x 10m floor plan", label="Gazebo office dimensions")
    world_name = _line(office_world, '<world name="office">', label="Gazebo world name")
    empty_world_topics = _lines(bridge, "/world/empty_world/", minimum=5)
    mecanum_macro = _line(
        robot_urdf, '<xacro:macro name="mecanum_wheel"', label="mecanum embodiment"
    )
    planar_plugin = _line(
        gazebo_urdf,
        "Planar Move Plugin — Holonomic (Mecanum) drive simulation",
        label="planar motion plugin",
    )
    docs_baseline = _line(
        docs,
        "| Nav2 DWB | pointnav | office_v2 | 0.85 | 0.72 |",
        label="documented PointNav baseline",
    )
    code_baseline_sr = _line(baselines, "success_rate=0.82", label="code PointNav baseline success")
    code_baseline_spl = _line(baselines, "spl=0.65", label="code PointNav baseline SPL")

    pointnav_scope = runner[
        runner.index("async def run_pointnav") : runner.index("async def run_exploration")
    ]
    if "start_poses" in pointnav_scope or "set_pose" in pointnav_scope or "reset" in pointnav_scope:
        raise ThreeWEAuditError("PointNav episode reset semantics changed; audit needs review")
    object_episode_scope = objectnav[
        objectnav.index("async def run_objectnav_episode") : objectnav.index(
            "def generate_objectnav_episodes"
        )
    ]
    if "target_category" in object_episode_scope:
        raise ThreeWEAuditError(
            "ObjectNav target-category policy boundary changed; audit needs review"
        )
    if "config.start_pose" in object_episode_scope or "set_pose" in object_episode_scope:
        raise ThreeWEAuditError("ObjectNav start-pose reset semantics changed; audit needs review")

    cli_run_start = cli.index('run_parser = benchmark_sub.add_parser("run"')
    cli_run_end = cli.index('compare_parser = benchmark_sub.add_parser("compare"')
    cli_run_scope = cli[cli_run_start:cli_run_end]
    if "--seed" in cli_run_scope:
        raise ThreeWEAuditError("benchmark CLI seed contract changed; audit needs review")
    cli_submit_scope = cli[cli.index("def _cmd_benchmark_submit") : cli.index("def _cmd_hal")]
    if any(token in cli_submit_scope for token in ("http", "requests", "urllib", "upload")):
        raise ThreeWEAuditError("leaderboard submission transport changed; audit needs review")

    start_poses = _pose_manifest(start_poses_text, label="office start poses")
    goal_poses = _pose_manifest(goal_poses_text, label="office goal poses")
    if len(start_poses) != 20 or len(goal_poses) != 50:
        raise ThreeWEAuditError(
            f"office pose counts drifted: {len(start_poses)} starts, {len(goal_poses)} goals"
        )
    outside_starts = [
        point for point in start_poses if not (0 < point[0] < 15 and 0 < point[1] < 10)
    ]
    outside_goals = [point for point in goal_poses if not (0 < point[0] < 15 and 0 < point[1] < 10)]
    if len(outside_starts) != 15 or len(outside_goals) != 34:
        raise ThreeWEAuditError("office pose/world coordinate mismatch changed; audit needs review")

    implemented_required_fields = {
        "agent_name",
        "task",
        "scene",
        "success_rate",
        "spl",
        "hardware",
        "timestamp",
    }
    validator_rejected_rows = sum(
        not implemented_required_fields.issubset(item.keys()) for item in entries
    )
    if validator_rejected_rows != len(entries):
        raise ThreeWEAuditError("leaderboard rows versus implemented validator result changed")

    static_pointnav = next(
        (
            item
            for item in entries
            if item.get("agent_name") == "3we-baseline-v2" and item.get("task") == "pointnav"
        ),
        None,
    )
    if not isinstance(static_pointnav, dict) or static_pointnav.get("metrics") != {
        "success_rate": 0.915,
        "spl": 0.87,
        "mean_duration": 11.2,
    }:
        raise ThreeWEAuditError("static PointNav baseline reference changed; audit needs review")

    findings = [
        _finding(
            "protocol_seed_and_reset_mismatch",
            "critical",
            "The published 0-99 episode seed protocol is not what the PointNav runner executes.",
            [
                _ref(_FILES["docs"], docs_seed),
                _ref(_FILES["runner"], runner_seed),
                _ref(_FILES["runner"], runner_robot),
                *[_ref(_FILES["objectnav"], line) for line in object_seed_lines],
                _ref(_FILES["cli"], cli_episodes),
            ],
            "One RNG seeded with 42 samples goals while one persistent Robot instance carries state "
            "between episodes; no documented start-pose reset or per-episode seed hook exists.",
        ),
        _finding(
            "task_timeout_mismatch",
            "critical",
            "All three implemented task time limits conflict with the published protocol.",
            [
                _ref(_FILES["docs"], docs_timeouts),
                _ref(_FILES["runner"], runner_timeout),
                _ref(_FILES["runner"], runner_explore_timeout),
                _ref(_FILES["objectnav"], object_timeout_default),
                _ref(_FILES["objectnav"], object_timeout_episode),
            ],
            "PointNav uses 30 rather than 60 seconds, ObjectNav config uses 60 rather than 120, "
            "and Exploration uses 120 rather than 180.",
        ),
        _finding(
            "pointnav_success_boundary_not_enforced",
            "critical",
            "The documented 0.5 m PointNav success condition is not evaluated by the runner.",
            [
                _ref(_FILES["tasks"], point_threshold),
                _ref(_FILES["runner"], runner_success),
                *[_ref(_FILES["ros2_backend"], line) for line in ros_success_lines[:1]],
            ],
            "The runner trusts the backend boolean, while the ROS backend reports success after "
            "an accepted action completes without checking the action result status or final radius.",
        ),
        _finding(
            "spl_path_length_is_displacement",
            "critical",
            "The ROS backend reports endpoint displacement, not traveled path length, to SPL.",
            [_ref(_FILES["ros2_backend"], ros_distance)],
            "Obstacle detours are omitted, so the resulting value cannot implement standard SPL "
            "path-efficiency semantics.",
        ),
        _finding(
            "objectnav_hidden_coordinate_oracle",
            "critical",
            "ObjectNav never presents the generated semantic category to an agent.",
            [
                _ref(_FILES["objectnav"], object_category),
                _ref(_FILES["objectnav"], object_goal),
                _ref(_FILES["objectnav"], object_move),
            ],
            "A category and an unrelated goal pose are sampled, then hidden target coordinates are "
            "sent directly to Robot.move_to; the generated start pose is also never applied.",
        ),
        _finding(
            "exploration_backend_is_stub",
            "critical",
            "The Gazebo/ROS Exploration implementation issues no exploration action.",
            [
                _ref(_FILES["ros2_backend"], ros_explore_stub),
                _ref(_FILES["ros2_backend"], ros_explore_sleep),
                _ref(_FILES["mock_backend"], mock_explore),
            ],
            "Gazebo samples map coverage after at most one second, while the mock backend returns "
            "perfect coverage. Neither path evaluates a Parcel exploration policy.",
        ),
        _finding(
            "runner_owns_navigation_stack",
            "critical",
            "The benchmark constructs 3WE Robot and delegates navigation to its backend.",
            [_ref(_FILES["runner"], runner_robot), _ref(_FILES["runner"], runner_timeout)],
            "There is no immutable external policy/agent hook. Replacing Robot.move_to or the "
            "Nav2 server would change the evaluation boundary and/or the wheeled embodiment.",
        ),
        _finding(
            "isaac_backend_is_stub",
            "critical",
            "The advertised GPU/Isaac backend does not connect actions or observations to a simulator.",
            [
                _ref(_FILES["isaac_backend"], isaac_constant_pose),
                _ref(_FILES["isaac_backend"], isaac_instant_goal),
                *[_ref(_FILES["isaac_backend"], line) for line in isaac_import_failures],
            ],
            "It returns constant sensor state, ignores velocity commands, reports instant goal "
            "success, and suppresses both Isaac import failures. Its leaderboard row cannot "
            "establish a valid GPU-evaluation cohort.",
        ),
        _finding(
            "simulated_embodiment_is_not_go2",
            "critical",
            "The official simulation assets describe a four-wheel mecanum robot with planar motion.",
            [
                _ref(_FILES["robot_urdf"], mecanum_macro),
                _ref(_FILES["gazebo_urdf"], planar_plugin),
            ],
            "Replacing this wheeled holonomic body with Unitree Go2 dynamics would be a substantive "
            "benchmark change rather than a neutral Parcel policy adapter.",
        ),
        _finding(
            "office_scene_coordinate_contract_mismatch",
            "critical",
            "The bundled office metadata, Gazebo walls, pose manifests, and bridge topics disagree.",
            [
                _ref(_FILES["scene_metadata"], metadata_area),
                _ref(_FILES["office_world"], world_dimensions),
                _ref(_FILES["office_world"], world_name),
                _ref(_FILES["bridge"], empty_world_topics[0]),
                _ref(_FILES["start_poses"], 2),
                _ref(_FILES["goal_poses"], 2),
            ],
            f"The metadata says 20x15 m while the enclosed world is 15x10 m in positive "
            f"coordinates; {len(outside_starts)}/20 starts and {len(outside_goals)}/50 goals "
            "are outside or on that boundary. Sensor topics name empty_world, not office.",
        ),
        _finding(
            "report_submission_schema_divergence",
            "critical",
            "The documented submission schema and implemented validator are incompatible.",
            [
                _ref(_FILES["docs"], docs_metrics_schema),
                _ref(_FILES["docs"], docs_software_schema),
                _ref(_FILES["submission"], submission_schema),
                _ref(_FILES["cli"], cli_submit),
                _ref(_FILES["cli"], cli_submit_success),
            ],
            "Documentation nests metrics and software and requires episode/seed metadata; the "
            f"validator expects flat success_rate, spl, hardware, and timestamp fields and rejects "
            f"all {validator_rejected_rows} static rows. The submit command only validates and prints; "
            "it contains no upload transport.",
        ),
        _finding(
            "published_baseline_references_diverge",
            "critical",
            "Three first-party locations report different office PointNav baselines.",
            [
                _ref(_FILES["docs"], docs_baseline),
                f"{_FILES['leaderboard'].as_posix()} (3we-baseline-v2 SR 0.915, SPL 0.87)",
                _ref(_FILES["baselines"], code_baseline_sr),
                _ref(_FILES["baselines"], code_baseline_spl),
            ],
            "Documentation reports SR/SPL 0.85/0.72, the static snapshot reports 0.915/0.87, "
            "and the comparison module reports 0.82/0.65, with no authoritative selection rule.",
        ),
        _finding(
            "leaderboard_cohort_not_rankable",
            "critical",
            "The pinned snapshot has no sufficiently large backend-specific cohort for top-decile ranking.",
            [f"{_FILES['leaderboard'].as_posix()} (SHA-256 {snapshot_sha})"],
            "PointNav mixes Gazebo, Isaac Sim, and mock results; ObjectNav and Exploration each "
            "contain only one entry. A top-decile cutoff or tie rule cannot be inferred defensibly.",
        ),
    ]

    observed_counts = {
        task: {
            backend: task_backend_counts[(task, backend)]
            for backend in sorted({key[1] for key in task_backend_counts if key[0] == task})
        }
        for task in sorted(task_counts)
    }
    critical_count = sum(item["severity"] == "critical" for item in findings)
    now = created_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    identifier = audit_id or f"threewe-contract-audit-{now.translate(str.maketrans('', '', ':-'))}"

    return {
        "schema_version": 1,
        "audit_id": identifier,
        "created_at_utc": now,
        "kind": "source_contract_compatibility_audit",
        "audit_implementation": {
            "path": Path(__file__).resolve().relative_to(PARCEL_ROOT).as_posix(),
            "sha256": _sha256(Path(__file__).resolve()),
            "upstream_python_imported": False,
        },
        "source": {
            "url": SOURCE_URL,
            "lock_key": SOURCE_LOCK_KEY,
            "expected_commit": PINNED_COMMIT,
            "checkout_commit": checkout_commit,
            "checkout_clean": not bool(dirty_output),
            "source_lock_sha256": _sha256(lock_path),
            "portfolio_sha256": _sha256(portfolio_file),
            "files": {
                name: {
                    "path": relative.as_posix(),
                    "sha256": _sha256(paths[name]),
                }
                for name, relative in sorted(_FILES.items())
            },
        },
        "published_contract": {
            "page": "https://3we.org/benchmarks",
            "documentation": "https://docs.3we.org/leaderboard/",
            "scene": "office_v2",
            "episodes_per_task": 100,
            "seed_start": 0,
            "timeouts_seconds": {
                "pointnav": 60,
                "objectnav": 120,
                "exploration": 180,
            },
        },
        "leaderboard_snapshot": {
            "sha256": snapshot_sha,
            "version": leaderboard.get("version"),
            "last_updated": leaderboard.get("last_updated"),
            "entry_count": len(entries),
            "task_entry_counts": dict(sorted(task_counts.items())),
            "task_backend_entry_counts": observed_counts,
            "rows_rejected_by_implemented_validator": validator_rejected_rows,
        },
        "scene_snapshot": {
            "metadata_area": "20x15m",
            "gazebo_enclosed_coordinate_bounds": {"x": [0, 15], "y": [0, 10]},
            "start_pose_count": len(start_poses),
            "start_poses_outside_or_on_boundary": len(outside_starts),
            "goal_pose_count": len(goal_poses),
            "goal_poses_outside_or_on_boundary": len(outside_goals),
        },
        "findings": findings,
        "admission": {
            "status": "not_admitted",
            "simulator_execution_allowed": False,
            "parcel_adapter_execution_allowed": False,
            "rank_threshold_freeze_allowed": False,
            "reason": "The pinned implementation does not yet expose a task-correct, injectable, "
            "backend-specific evaluator contract.",
            "resolution_required": [
                "Organizer-published immutable runner with an explicit external-agent action/observation hook.",
                "One authoritative seed/reset/timeout contract shared by docs and code.",
                "Correct PointNav success and traveled-path accounting.",
                "ObjectNav observations that reveal category but never target coordinates.",
                "A real Exploration controller/evaluator and authoritative coverage/efficiency metric.",
                "A working simulator backend and a frozen Unitree Go2 embodiment contract.",
                "A scene whose geometry, pose manifests, and sensor bridge share one coordinate/world contract.",
                "One submission schema and a real provenance-preserving submission path.",
                "Backend-specific leaderboard cohorts, ranking metric, tie rule, and provenance.",
            ],
        },
        "execution": {
            "source_code_executed": False,
            "simulator_started": False,
            "parcel_policy_executed": False,
            "episodes_run": 0,
            "metrics_emitted": False,
            "rank_eligible": False,
        },
        "aggregate": {
            "critical_contract_blockers": critical_count,
            "targets_remaining_unresolved": len(expected_ids),
            "eligible_navigation_scores": 0,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit the pinned 3WE source contract without running an evaluator"
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--source-lock", type=Path, default=DEFAULT_SOURCE_LOCK)
    parser.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-id")
    parser.add_argument("--allow-dirty-source", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = audit_threewe_contract(
            args.source_root,
            source_lock_path=args.source_lock,
            portfolio_path=args.portfolio,
            require_clean=not args.allow_dirty_source,
            audit_id=args.audit_id,
        )
        payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            print(payload, end="")
        else:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with output.open("x", encoding="utf-8") as stream:
                    stream.write(payload)
            except FileExistsError as exc:
                raise ThreeWEAuditError(f"refusing to replace immutable report: {output}") from exc
            output.chmod(0o444)
            print(output)
    except (OSError, ThreeWEAuditError) as exc:
        print(f"3WE contract audit failed: {exc}", file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
