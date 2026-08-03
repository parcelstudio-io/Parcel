"""Package and run Parcel through BARN's documented ROS 2 submission hook.

This module is intentionally evaluator-only.  It copies Parcel's existing
Python controller and transport adapter into a content-addressed bundle, then
derives a launch overlay by replacing only ``launch_navigation_stack`` in the
pinned upstream launch file.  The upstream checkout and evaluator-owned
success, collision, timeout, and metric implementation remain unchanged.

The only executable benchmark action exposed by this helper is one trial on
public world 0.  A completed row is local compatibility evidence, not an
official score, a public-suite result, or top-decile evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_official_doctor import load_runtime_manifest
from .ledger import record_evaluation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CHECKOUT = REPO_ROOT / ".cache/external-evals/repos/barn_challenge_ros2_2026"
ROOTFS = REPO_ROOT / ".cache/external-evals/runtime/barn-current-rootfs"
BUNDLE_CACHE = REPO_ROOT / ".cache/external-evals/runtime/barn-parcel-bundles"
RUN_CACHE = REPO_ROOT / ".cache/external-evals/runtime/barn-parcel-runs"
RESULTS_DIR = Path(__file__).resolve().parent / "results/barn_ros2"

OFFICIAL_LAUNCH_RELATIVE = Path("jackal_helper/launch/BARN_runner.launch.py")
INSTALLED_LAUNCH = Path(
    "/jackal_ws/install/jackal_helper/share/jackal_helper/launch/BARN_runner.launch.py"
)
# ``jackal_helper.utils.get_pkg_src_path()`` resolves to the repository root,
# not the package directory.  Keep this evidence lookup aligned with the
# unchanged upstream evaluator's write location.
ROOTFS_RESULT_DIRECTORY = Path("jackal_ws/src/The-Barn-Challenge-Ros2/res")
NAVIGATION_CONFIG_RELATIVE = Path("configs/navigation/experiments/barn_grid_v1.yaml")
MODEL_CONFIG_RELATIVE = Path("configs/navigation/models/grid.yaml")

PACKAGE_KIND = "barn-ros2-parcel-submission-hook-bundle-v1"
EVALUATION_KIND = "barn-ros2-parcel-world0-rootless-compatibility-v1"
ADAPTER_ID = "parcel-barn-ros2-calibrated-sensor-transport-v2"
CONTROLLER_ID = "parcel-directive-navigator-grid-v1-unchanged"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_EXTERNAL_MODULES = (
    Path("evals/__init__.py"),
    Path("evals/external/__init__.py"),
    # The unchanged external-eval package initializer imports these modules.
    Path("evals/external/compatibility.py"),
    Path("evals/external/metrics.py"),
    Path("evals/external/runner.py"),
    Path("evals/external/agents.py"),
    Path("evals/external/episodes.py"),
    Path("evals/external/barn_native.py"),
    Path("evals/external/parcel_barn_adapter.py"),
    Path("evals/external/barn_ros2_adapter.py"),
    Path("evals/external/barn_ros2_node.py"),
)

_HOOK_START = "def launch_navigation_stack(context, *args, **kwargs):\n"
_HOOK_END = "def generate_launch_description():\n"
_PARCEL_HOOK = '''def launch_navigation_stack(context, *args, **kwargs):
    """Launch Parcel through the organizer-documented submission hook."""

    relative_goal_distance = parse_world_idx(
        LaunchConfiguration("world_idx").perform(context)
    )[1]
    parcel_adapter = ExecuteProcess(
        cmd=[
            "python3",
            "-m",
            "evals.external.barn_ros2_node",
            "--navigation-config",
            "/opt/parcel/configs/navigation/experiments/barn_grid_v1.yaml",
            "--goal-x",
            str(relative_goal_distance),
            "--goal-y",
            "0.0",
            "--ros-args",
            "-p",
            "use_sim_time:=true",
        ],
        additional_env={
            "PYTHONPATH": "/opt/parcel/src:/opt/parcel"
            + (f":{os.environ['PYTHONPATH']}" if os.environ.get("PYTHONPATH") else "")
        },
        output="screen",
    )
    parcel_exit_handler = RegisterEventHandler(
        OnProcessExit(target_action=parcel_adapter, on_exit=[Shutdown()])
    )
    return [parcel_adapter, parcel_exit_handler]

'''


@dataclass(frozen=True, slots=True)
class EvaluatorRow:
    world_idx: int
    success: int
    collision: int
    timeout: int
    elapsed_time_s: float
    navigation_metric: float


@dataclass(frozen=True, slots=True)
class Bundle:
    path: Path
    manifest_path: Path
    package_sha256: str
    launch_overlay_path: Path
    files: dict[str, str]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(document: Mapping[str, Any], *, pretty: bool = False) -> bytes:
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return (
        json.dumps(
            document,
            allow_nan=False,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _git_output(checkout: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"cannot inspect upstream checkout: {detail or result.returncode}")
    return result.stdout.strip()


def verify_upstream_checkout(
    checkout: str | Path = SOURCE_CHECKOUT,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the exact pinned, clean upstream checkout and critical hashes."""

    source_root = Path(checkout).expanduser().resolve()
    runtime_manifest = dict(manifest or load_runtime_manifest())
    source = runtime_manifest["official_sources"]
    expected_commit = str(source["repository_commit"])
    actual_commit = _git_output(source_root, "rev-parse", "HEAD")
    status = _git_output(source_root, "status", "--porcelain", "--untracked-files=all")
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"upstream checkout commit mismatch: {actual_commit} != {expected_commit}"
        )
    if status:
        raise RuntimeError("upstream checkout is dirty; refusing to package or run")

    hashes: dict[str, str] = {}
    for relative, expected in sorted(source["critical_files_sha256"].items()):
        candidate = source_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError(f"upstream critical file is missing or a symlink: {relative}")
        actual = _sha256(candidate)
        if actual != expected:
            raise RuntimeError(f"upstream critical file hash mismatch: {relative}")
        hashes[str(relative)] = actual
    return {
        "path": str(source_root),
        "commit": actual_commit,
        "clean": True,
        "critical_files_sha256": hashes,
    }


def replace_navigation_hook(source: bytes, *, expected_sha256: str | None = None) -> bytes:
    """Replace exactly one upstream function and preserve every other byte."""

    if expected_sha256 is not None:
        if _SHA256.fullmatch(expected_sha256) is None:
            raise ValueError("expected launch SHA-256 is malformed")
        if _sha256_bytes(source) != expected_sha256:
            raise ValueError("official launch input SHA-256 does not match the frozen pin")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("official launch file is not UTF-8") from exc
    if text.count(_HOOK_START) != 1 or text.count(_HOOK_END) != 1:
        raise ValueError("official launch file has an unexpected hook structure")
    start = text.index(_HOOK_START)
    end = text.index(_HOOK_END, start)
    if end <= start:
        raise ValueError("official launch hook boundaries are malformed")
    return (text[:start] + _PARCEL_HOOK + text[end:]).encode("utf-8")


def _package_sources(repo_root: Path) -> list[Path]:
    sources = [
        path.relative_to(repo_root)
        for path in sorted((repo_root / "src/parcel_robot").rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    sources.extend(_EXTERNAL_MODULES)
    sources.append(NAVIGATION_CONFIG_RELATIVE)
    sources.extend(
        path.relative_to(repo_root)
        for path in sorted((repo_root / "configs/navigation/models").glob("*.yaml"))
    )
    sources.append(Path("configs/navigation/cities/demo_pois.yaml"))
    unique = sorted(set(sources), key=lambda path: path.as_posix())
    if not unique:
        raise RuntimeError("Parcel submission source set is empty")
    return unique


def _source_hashes(repo_root: Path, sources: Sequence[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in sources:
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe package path: {relative}")
        candidate = repo_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError(f"package source is missing or a symlink: {relative}")
        hashes[relative.as_posix()] = _sha256(candidate)
    return hashes


def _bundle_from_manifest(path: Path, manifest: Mapping[str, Any]) -> Bundle:
    files = manifest.get("files_sha256")
    package_hash = manifest.get("package_sha256")
    if not isinstance(files, dict) or not isinstance(package_hash, str):
        raise TypeError("submission bundle manifest is incomplete")
    if _SHA256.fullmatch(package_hash) is None:
        raise ValueError("submission package SHA-256 is malformed")
    normalized_files: dict[str, str] = {}
    for relative, expected in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or _SHA256.fullmatch(expected) is None
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError("submission file manifest is malformed")
        candidate = path / relative
        if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != expected:
            raise ValueError(f"submission bundle file mismatch: {relative}")
        normalized_files[relative] = expected
    expected_actual = set(normalized_files) | {"package-manifest.json"}
    actual = {file.relative_to(path).as_posix() for file in path.rglob("*") if file.is_file()}
    if actual != expected_actual:
        raise ValueError("submission bundle contains unmanifested or missing files")
    material = dict(manifest)
    material.pop("package_sha256", None)
    if _sha256_bytes(_canonical_json(material)) != package_hash:
        raise ValueError("submission package content hash mismatch")
    launch = path / "overlay/BARN_runner.launch.py"
    return Bundle(
        path=path,
        manifest_path=path / "package-manifest.json",
        package_sha256=package_hash,
        launch_overlay_path=launch,
        files=normalized_files,
    )


def verify_bundle(path: str | Path) -> Bundle:
    root = Path(path).expanduser().resolve()
    manifest_path = root / "package-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load submission bundle manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("package_kind") != PACKAGE_KIND:
        raise ValueError("submission bundle kind mismatch")
    return _bundle_from_manifest(root, manifest)


def prepare_bundle(
    *,
    repo_root: str | Path = REPO_ROOT,
    checkout: str | Path = SOURCE_CHECKOUT,
    destination_root: str | Path = BUNDLE_CACHE,
) -> Bundle:
    """Create a content-addressed, no-clobber Parcel submission overlay."""

    parcel_root = Path(repo_root).expanduser().resolve()
    checkout_root = Path(checkout).expanduser().resolve()
    destination = Path(destination_root).expanduser().resolve()
    runtime_manifest = load_runtime_manifest()
    upstream = verify_upstream_checkout(checkout_root, manifest=runtime_manifest)
    official_launch_path = checkout_root / OFFICIAL_LAUNCH_RELATIVE
    official_launch = official_launch_path.read_bytes()
    official_launch_hash = runtime_manifest["official_sources"]["critical_files_sha256"][
        OFFICIAL_LAUNCH_RELATIVE.as_posix()
    ]
    overlay = replace_navigation_hook(
        official_launch,
        expected_sha256=str(official_launch_hash),
    )

    sources = _package_sources(parcel_root)
    source_hashes = _source_hashes(parcel_root, sources)
    files = dict(source_hashes)
    files["overlay/BARN_runner.launch.py"] = _sha256_bytes(overlay)
    material: dict[str, Any] = {
        "schema_version": 1,
        "package_kind": PACKAGE_KIND,
        "upstream": {
            "commit": upstream["commit"],
            "clean": upstream["clean"],
            "critical_files_sha256": upstream["critical_files_sha256"],
        },
        "hook": {
            "name": "launch_navigation_stack",
            "official_input_sha256": _sha256_bytes(official_launch),
            "overlay_output_sha256": _sha256_bytes(overlay),
            "evaluator_behavior_modified_outside_documented_hook": False,
        },
        "navigation": {
            "adapter_id": ADAPTER_ID,
            "controller_id": CONTROLLER_ID,
            "config": NAVIGATION_CONFIG_RELATIVE.as_posix(),
            "production_source_modified_by_packaging": False,
        },
        "files_sha256": files,
        "claims": {
            "package_only_until_episode_completes": True,
            "official_protocol": False,
            "organizer_attested": False,
            "top_decile_evidence": False,
        },
    }
    package_hash = _sha256_bytes(_canonical_json(material))
    document = dict(material)
    document["package_sha256"] = package_hash
    target = destination / f"parcel-world0-{package_hash[:16]}"
    if target.exists():
        bundle = verify_bundle(target)
        if bundle.package_sha256 != package_hash:
            raise FileExistsError(f"refusing mismatched existing bundle: {target}")
        return bundle

    destination.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".parcel-world0-", dir=destination))
    try:
        for relative in sources:
            output = temporary / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(parcel_root / relative, output)
        overlay_path = temporary / "overlay/BARN_runner.launch.py"
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_bytes(overlay)
        manifest_path = temporary / "package-manifest.json"
        manifest_path.write_bytes(_canonical_json(document, pretty=True))
        for file in temporary.rglob("*"):
            if file.is_file():
                file.chmod(0o444)
        try:
            temporary.rename(target)
        except FileExistsError as exc:
            raise FileExistsError(f"submission bundle already exists: {target}") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_bundle(target)


def parse_evaluator_row(text: str) -> EvaluatorRow:
    """Validate exactly one terminal world-0 row from the official evaluator."""

    rows = [line.strip() for line in text.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("expected exactly one non-empty evaluator row")
    columns = rows[0].split()
    if len(columns) != 6:
        raise ValueError("evaluator row must contain six columns")
    try:
        row = EvaluatorRow(
            world_idx=int(columns[0]),
            success=int(columns[1]),
            collision=int(columns[2]),
            timeout=int(columns[3]),
            elapsed_time_s=float(columns[4]),
            navigation_metric=float(columns[5]),
        )
    except ValueError as exc:
        raise ValueError("evaluator row contains an invalid number") from exc
    if row.world_idx != 0:
        raise ValueError("this compatibility runner accepts public world 0 only")
    if any(value not in {0, 1} for value in (row.success, row.collision, row.timeout)):
        raise ValueError("terminal flags must be binary")
    if row.success + row.collision + row.timeout != 1:
        raise ValueError("exactly one terminal evaluator flag must be set")
    if not math.isfinite(row.elapsed_time_s) or not 0.0 <= row.elapsed_time_s <= 100.1:
        raise ValueError("elapsed time is outside the one-episode protocol")
    if not math.isfinite(row.navigation_metric) or not 0.0 <= row.navigation_metric <= 0.5:
        raise ValueError("navigation metric is outside the official per-episode bounds")
    if row.success == 0 and abs(row.navigation_metric) > 1e-12:
        raise ValueError("an unsuccessful evaluator row must have zero navigation metric")
    return row


def inspect_launch_progress(text: str) -> dict[str, bool]:
    """Classify only process-owned liveness markers from an ignored launch log.

    These markers are diagnostic; they are never accepted as an evaluator row
    or used to infer success, collision, timeout, or a navigation metric.
    """

    return {
        "parcel_startup_observed": "Parcel BARN ROS2 adapter ready:" in text,
        "first_odometry_observed": "Parcel BARN first odometry received" in text,
        "first_scan_observed": "Parcel BARN first scan received:" in text,
        "first_policy_command_observed": "Parcel BARN first policy command:" in text,
        "command_bridge_observed": (
            "Passing message from ROS geometry_msgs/msg/TwistStamped to Gazebo" in text
        ),
        "evaluator_waiting_for_motion": "Waiting for robot to start moving" in text,
        "evaluator_trial_started": "Trial running" in text,
        "evaluator_terminal_observed": bool(
            re.search(r"Navigation (?:succeeded|collided|timeout) with time", text)
        ),
        "adapter_error_observed": "adapter failed closed:" in text,
    }


def _validated_rootfs(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    supplied = Path(path).expanduser().absolute()
    if root != supplied or root.is_symlink() or not root.is_dir():
        raise RuntimeError("rootfs must be an existing, direct, non-symlink path")
    required = root / INSTALLED_LAUNCH.relative_to("/")
    if required.is_symlink() or not required.is_file():
        raise RuntimeError("rootfs is missing the installed official BARN launch file")
    return root


def world0_command(
    bundle: Bundle,
    *,
    rootfs: str | Path = ROOTFS,
    out_file: str,
    ros_domain_id: int = 179,
) -> list[str]:
    """Return the exact cache-only Bubblewrap world-0 launch command."""

    if _SAFE_NAME.fullmatch(out_file) is None or not out_file.endswith(".txt"):
        raise ValueError("out_file must be a safe relative .txt filename")
    if not 1 <= ros_domain_id <= 232:
        raise ValueError("ROS domain id must be in [1, 232]")
    verified = verify_bundle(bundle.path)
    root = _validated_rootfs(rootfs)
    shell = (
        "source /opt/ros/jazzy/setup.bash; "
        "source /jackal_ws/install/local_setup.bash; "
        "cd /jackal_ws; "
        "ros2 launch jackal_helper BARN_runner.launch.py "
        f"world_idx:=0 gui:=false rviz:=false out_file:={out_file}"
    )
    return [
        "bwrap",
        "--bind",
        str(root),
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/opt/parcel",
        "--ro-bind",
        str(verified.path),
        "/opt/parcel",
        "--ro-bind",
        str(verified.launch_overlay_path),
        str(INSTALLED_LAUNCH),
        "--uid",
        "0",
        "--gid",
        "0",
        "--unshare-pid",
        "--unshare-uts",
        "--die-with-parent",
        "/usr/bin/env",
        "HOME=/root",
        "ROS_LOCALHOST_ONLY=1",
        f"ROS_DOMAIN_ID={ros_domain_id}",
        "LIBGL_ALWAYS_SOFTWARE=1",
        "QT_QPA_PLATFORM=offscreen",
        "RCUTILS_LOGGING_BUFFERED_STREAM=1",
        "bash",
        "-lc",
        shell,
    ]


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=10.0)
        return
    except subprocess.TimeoutExpired:
        pass
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5.0)


def _write_immutable(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to overwrite immutable result: {target}") from exc
        target.chmod(0o444)
    finally:
        temporary.unlink(missing_ok=True)


def run_world0(
    *,
    bundle: Bundle | None = None,
    rootfs: str | Path = ROOTFS,
    results_dir: str | Path = RESULTS_DIR,
    timeout_s: float = 180.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one public episode and record evidence only after a valid row exists."""

    if not 120.0 <= timeout_s <= 600.0:
        raise ValueError("process timeout must be in [120, 600] seconds")
    selected_bundle = bundle or prepare_bundle()
    selected_bundle = verify_bundle(selected_bundle.path)
    root = _validated_rootfs(rootfs)
    upstream_before = verify_upstream_checkout()
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"barn-ros2-parcel-{stamp}-world0-{selected_bundle.package_sha256[:8]}"
    out_file = f"parcel_{stamp}_{selected_bundle.package_sha256[:8]}_world0.txt"
    raw_in_rootfs = root / ROOTFS_RESULT_DIRECTORY / out_file
    if raw_in_rootfs.exists():
        raise FileExistsError(f"refusing pre-existing evaluator output: {raw_in_rootfs}")

    run_cache = RUN_CACHE / run_id
    run_cache.mkdir(parents=True, exist_ok=False)
    launch_log = run_cache / "launch.log"
    command = world0_command(selected_bundle, rootfs=root, out_file=out_file)
    timed_out = False
    with launch_log.open("xb") as log_stream:
        process = subprocess.Popen(
            command,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
            return_code = process.returncode
        log_stream.flush()
        os.fsync(log_stream.fileno())

    log_text = launch_log.read_text(encoding="utf-8", errors="replace")
    progress = inspect_launch_progress(log_text)
    if timed_out:
        progress_json = json.dumps(progress, separators=(",", ":"), sort_keys=True)
        raise RuntimeError(
            f"world-0 launch exceeded {timeout_s:.1f}s; progress={progress_json}; "
            "no evidence recorded"
        )
    if not raw_in_rootfs.is_file() or raw_in_rootfs.is_symlink():
        progress_json = json.dumps(progress, separators=(",", ":"), sort_keys=True)
        raise RuntimeError(
            f"world-0 launch exited {return_code} without a real evaluator row; "
            f"progress={progress_json}; see {launch_log}"
        )
    raw_payload = raw_in_rootfs.read_bytes()
    try:
        row = parse_evaluator_row(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"invalid world-0 evaluator output; see {launch_log}: {exc}") from exc
    upstream_after = verify_upstream_checkout()
    if upstream_before != upstream_after:
        raise RuntimeError("upstream checkout provenance changed during the episode")
    if "Parcel BARN ROS2 adapter ready:" not in log_text:
        raise RuntimeError("evaluator row exists but Parcel adapter startup was not observed")

    destination = Path(results_dir).expanduser().resolve()
    result_stem = f"parcel-world0-{stamp}-{selected_bundle.package_sha256[:8]}"
    raw_result = destination / f"{result_stem}.raw.txt"
    evidence_path = destination / f"{result_stem}.json"
    _write_immutable(raw_result, raw_payload)
    package_manifest_sha = _sha256(selected_bundle.manifest_path)
    source_hashes = json.loads(selected_bundle.manifest_path.read_text(encoding="utf-8"))[
        "files_sha256"
    ]
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "evaluation_kind": EVALUATION_KIND,
        "run_id": run_id,
        "timestamp_utc": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": load_runtime_manifest()["official_sources"]["repository"],
            "commit": upstream_after["commit"],
            "checkout_clean_before_and_after": True,
            "critical_files_sha256": upstream_after["critical_files_sha256"],
        },
        "runtime": {
            "driver": "bubblewrap-plus-proot-cache-only-diagnostic-rootfs",
            "upstream_tested_singularity_path_used": False,
            "software_rendering_forced": True,
            "gpu_used": False,
            "host_system_packages_installed": False,
            "launch_return_code": return_code,
        },
        "package": {
            "kind": PACKAGE_KIND,
            "package_sha256": selected_bundle.package_sha256,
            "manifest_sha256": package_manifest_sha,
            "launch_overlay_sha256": _sha256(selected_bundle.launch_overlay_path),
            "content_addressed_cache_path": str(selected_bundle.path.relative_to(REPO_ROOT)),
        },
        "navigation": {
            "adapter_id": ADAPTER_ID,
            "adapter_exercised": True,
            "adapter_sha256": source_hashes["evals/external/barn_ros2_adapter.py"],
            "ros_node_sha256": source_hashes["evals/external/barn_ros2_node.py"],
            "controller_id": CONTROLLER_ID,
            "controller_source_unchanged": True,
            "production_package_modified": False,
            "config": NAVIGATION_CONFIG_RELATIVE.as_posix(),
            "config_sha256": source_hashes[NAVIGATION_CONFIG_RELATIVE.as_posix()],
            "model_config_sha256": source_hashes[MODEL_CONFIG_RELATIVE.as_posix()],
            "documented_launch_navigation_stack_hook_only": True,
            "evaluator_success_collision_timeout_metric_modified": False,
        },
        "scope": {
            "world_indices": [0],
            "trials_per_world": 1,
            "episode_count": 1,
        },
        "episode": asdict(row),
        "raw_result": {
            "path": raw_result.name,
            "sha256": _sha256(raw_result),
            "size_bytes": raw_result.stat().st_size,
            "columns": [
                "world_idx",
                "success",
                "collision",
                "timeout",
                "elapsed_time_s",
                "navigation_metric",
            ],
        },
        "launch_log": {
            "ignored_cache_path": str(launch_log.relative_to(REPO_ROOT)),
            "sha256": _sha256(launch_log),
            "size_bytes": launch_log.stat().st_size,
            "parcel_adapter_startup_observed": True,
        },
        "classification": {
            "package_only": False,
            "parcel_adapter_single_episode_metric": True,
            "public_suite_result": False,
            "official_score": False,
            "top_decile_evidence": False,
        },
        "claims": {
            "official_protocol": False,
            "organizer_attested": False,
            "leaderboard_claim_allowed": False,
            "top_decile_evidence": False,
        },
        "change_description": (
            "Calibrated Parcel ROS2 LiDAR transport v2 with explicit base-to-LiDAR "
            "extrinsic, robot self-return invalidation, and scan/odometry synchronization; "
            "the unchanged grid_v1 DirectiveNavigator is packaged through upstream "
            "launch_navigation_stack for one local public-world-0 cache-only "
            "compatibility episode."
        ),
    }
    _write_immutable(evidence_path, _canonical_json(evidence, pretty=True))
    ledger = record_evaluation_run(
        benchmark_id="barn-ros2-2026-parcel-world0-rootless-compatibility",
        benchmark_source=str(evidence["source"]["repository"]),
        benchmark_source_commit=str(evidence["source"]["commit"]),
        change_description=str(evidence["change_description"]),
        aggregate_metrics={
            "world_indices": [0],
            "trials_per_world": 1,
            "episode_count": 1,
            "success_rate": float(row.success),
            "collision_rate": float(row.collision),
            "timeout_rate": float(row.timeout),
            "elapsed_time_s": row.elapsed_time_s,
            "navigation_metric": row.navigation_metric,
            "parcel_adapter_exercised": True,
            "package_only": False,
            "official_protocol": False,
            "organizer_attested": False,
            "top_decile_evidence": False,
            "gpu_used": False,
        },
        report_path=evidence_path,
        run_id=run_id,
        agent_id=CONTROLLER_ID,
        agent_hash=f"sha256:{selected_bundle.package_sha256}",
        adapter_id=ADAPTER_ID,
        adapter_hash=f"sha256:{source_hashes['evals/external/barn_ros2_adapter.py']}",
        config_id=NAVIGATION_CONFIG_RELATIVE.as_posix(),
        config_hash=f"sha256:{source_hashes[NAVIGATION_CONFIG_RELATIVE.as_posix()]}",
        model_id="grid_v1",
        model_hash=f"sha256:{source_hashes[MODEL_CONFIG_RELATIVE.as_posix()]}",
    )
    return {
        "run_id": run_id,
        "episode": asdict(row),
        "evidence_path": str(evidence_path),
        "raw_result_path": str(raw_result),
        "launch_log_path": str(launch_log),
        "ledger_record_path": str(ledger.record_path),
        "classification": evidence["classification"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", action="store_true", help="prepare/verify the bundle")
    actions.add_argument(
        "--run-world0",
        action="store_true",
        help="run exactly one local compatibility episode on public world 0",
    )
    parser.add_argument("--rootfs", type=Path, default=ROOTFS)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle = prepare_bundle()
    if args.prepare:
        output = {
            "package_kind": PACKAGE_KIND,
            "path": str(bundle.path),
            "manifest_path": str(bundle.manifest_path),
            "package_sha256": bundle.package_sha256,
            "classification": {
                "package_only": True,
                "parcel_adapter_metric": False,
                "official_score": False,
                "top_decile_evidence": False,
            },
        }
    else:
        output = run_world0(bundle=bundle, rootfs=args.rootfs, timeout_s=args.timeout)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ADAPTER_ID",
    "CONTROLLER_ID",
    "EVALUATION_KIND",
    "PACKAGE_KIND",
    "Bundle",
    "EvaluatorRow",
    "inspect_launch_progress",
    "main",
    "parse_evaluator_row",
    "prepare_bundle",
    "replace_navigation_hook",
    "run_world0",
    "verify_bundle",
    "verify_upstream_checkout",
    "world0_command",
]
