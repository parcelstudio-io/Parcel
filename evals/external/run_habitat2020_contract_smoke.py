"""Run an immutable, rank-ineligible Habitat 2020 adapter contract smoke.

This runner deliberately stops before Habitat-Sim.  It proves that every
episode identifier in the pinned public ``val_mini`` archive can initialize
the unchanged Parcel navigator through the real Python-3.6-compatible JSONL
bridge and modern-Python sidecar boundary.  The RGB-D frames are synthetic
contract fixtures, so this runner never emits navigation metrics and can never
be used as Habitat leaderboard evidence.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml

from .habitat2020_doctor import MANIFEST_PATH, REPO_ROOT, audit_habitat2020, load_manifest
from .habitat2020_py36_bridge import (
    OFFICIAL_ACTIONS,
    PointNav2020Bridge,
    SubprocessJsonTransport,
)

DEFAULT_NAVIGATION_CONFIG = REPO_ROOT / "configs/navigation/default.yaml"
DEFAULT_RESULTS_DIR = REPO_ROOT / "evals/external/results/habitat2020"
PUBLIC_SMOKE_REQUIRED_CHECKS = frozenset(
    {
        "source_lock",
        "pinned_checkout",
        "immutable_checkout",
        "official_task_config",
        "public_minival_episodes",
        "public_minival_shape",
        "python36_bridge_grammar",
        "modern_parcel_sidecar",
    }
)


class _Transport(Protocol):
    def request(self, message: dict[str, object]) -> dict[str, object]: ...

    def close(self) -> None: ...


TransportFactory = Callable[[Path], _Transport]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_tree_provenance(root: Path) -> dict[str, object]:
    source_root = root / "src/parcel_robot"
    files = sorted(path for path in source_root.rglob("*.py") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "algorithm": "sha256(relative_posix_path + NUL + bytes + NUL)",
        "file_count": len(files),
        "sha256": digest.hexdigest(),
    }


def _git_state(root: Path) -> dict[str, object]:
    def run(*arguments: str) -> tuple[int, str]:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        return completed.returncode, completed.stdout.strip()

    head_code, head = run("rev-parse", "HEAD")
    status_code, status = run("status", "--porcelain")
    status_lines = status.splitlines() if status else []
    return {
        "head": head if head_code == 0 else None,
        "dirty": status_code != 0 or bool(status_lines),
        "porcelain_entry_count": len(status_lines),
    }


def _active_model_provenance(root: Path, navigation_config: Path) -> dict[str, object]:
    config = yaml.safe_load(navigation_config.read_text(encoding="utf-8")) or {}
    active_model = config.get("active_model")
    models_root_value = config.get("models_root")
    if not isinstance(active_model, str) or not active_model:
        raise ValueError("navigation config must declare a non-empty active_model")
    if not isinstance(models_root_value, str) or not models_root_value:
        raise ValueError("navigation config must declare a non-empty models_root")
    models_root = (root / models_root_value).resolve()
    if not models_root.is_relative_to(root.resolve()):
        raise ValueError("navigation models_root must remain inside the repository")
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(models_root.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if document.get("id") == active_model:
            matches.append((path, document))
    if len(matches) != 1:
        raise ValueError(f"active_model {active_model!r} must resolve to exactly one model spec")
    model_path, model = matches[0]
    return {
        "active_model": active_model,
        "model_type": model.get("type"),
        "declared_device": model.get("device", "cpu"),
        "model_spec_path": model_path.relative_to(root).as_posix(),
        "model_spec_sha256": _sha256(model_path),
    }


def _load_public_episodes(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    episodes = payload.get("episodes") if isinstance(payload, dict) else None
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("public Habitat episode archive has no episodes")
    if any(not isinstance(episode, dict) for episode in episodes):
        raise ValueError("public Habitat episode archive contains a non-object episode")
    return episodes


def _default_transport_factory(navigation_config: Path) -> _Transport:
    return SubprocessJsonTransport(
        [
            sys.executable,
            "-m",
            "evals.external.habitat2020_sidecar",
            "--navigation-config",
            str(navigation_config),
        ]
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[rank]


def run_contract_smoke(
    *,
    repo_root: Path = REPO_ROOT,
    navigation_config: Path = DEFAULT_NAVIGATION_CONFIG,
    max_episodes: int | None = None,
    transport_factory: TransportFactory = _default_transport_factory,
) -> dict[str, Any]:
    """Exercise the public artifact/adapter boundary without a scene or metric."""

    root = repo_root.expanduser().resolve()
    config_path = navigation_config.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"navigation config does not exist: {config_path}")
    if not config_path.is_relative_to(root):
        raise ValueError("navigation config must remain inside the repository")
    if max_episodes is not None and max_episodes < 1:
        raise ValueError("max_episodes must be positive")

    manifest = load_manifest(MANIFEST_PATH)
    doctor = audit_habitat2020(repo_root=root)
    checks = {check["id"]: check for check in doctor["checks"]}
    missing_checks = sorted(PUBLIC_SMOKE_REQUIRED_CHECKS - set(checks))
    failed_checks = sorted(
        check_id
        for check_id in PUBLIC_SMOKE_REQUIRED_CHECKS
        if check_id in checks and checks[check_id]["ready"] is not True
    )
    if missing_checks or failed_checks:
        raise RuntimeError(
            "Habitat public smoke provenance is not ready; "
            f"missing_checks={missing_checks}, failed_checks={failed_checks}"
        )

    source = manifest["challenge_source"]
    task = manifest["task"]
    checkout = root / source["checkout_relative_path"]
    episodes_path = checkout / task["episodes_relative_path"]
    episodes = _load_public_episodes(episodes_path)
    public_episode_ids = [str(episode.get("episode_id")) for episode in episodes]
    if len(set(public_episode_ids)) != len(public_episode_ids):
        raise ValueError("public Habitat episode identifiers must be unique")
    selected = episodes if max_episodes is None else episodes[:max_episodes]

    height = int(task["sensors"]["depth"]["height"])
    width = int(task["sensors"]["depth"]["width"])
    depth = np.ones((height, width, 1), dtype=np.float32)
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    fixture_angles = (-math.pi / 3.0, 0.0, math.pi / 3.0)

    transport = transport_factory(config_path)
    bridge = PointNav2020Bridge(
        transport,
        arrival_radius_m=float(manifest["adapter"]["arrival_radius_m"]),
        scan_bins=int(manifest["adapter"]["depth_scan_bins"]),
    )
    actions: list[dict[str, object]] = []
    latency_ms: list[float] = []
    started_ns = time.perf_counter_ns()
    try:
        for index, episode in enumerate(selected):
            bridge.reset()
            rho = 1.0 + 0.25 * (index % 5)
            phi = fixture_angles[index % len(fixture_angles)]
            observations = {
                "pointgoal": np.asarray([rho, phi], dtype=np.float32),
                "depth": depth,
                "rgb": rgb,
            }
            action_started_ns = time.perf_counter_ns()
            response = bridge.act(observations)
            latency_ms.append((time.perf_counter_ns() - action_started_ns) / 1_000_000.0)
            action = response.get("action")
            if action not in OFFICIAL_ACTIONS:
                raise RuntimeError(f"bridge emitted a non-Habitat action: {action!r}")
            actions.append(
                {
                    "public_episode_id": str(episode.get("episode_id")),
                    "scene_id": episode.get("scene_id"),
                    "fixture_pointgoal_rho_m": rho,
                    "fixture_pointgoal_phi_rad": phi,
                    "action": action,
                }
            )
    finally:
        bridge.close()
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0

    generated_at = datetime.now(timezone.utc)
    identity = {
        "generated_at_utc": generated_at.isoformat(),
        "episode_archive_sha256": task["episodes_sha256"],
        "navigation_config_sha256": _sha256(config_path),
        "episode_count": len(selected),
    }
    identity_sha = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    action_counts = Counter(str(action["action"]) for action in actions)

    return {
        "schema_version": 1,
        "run_id": (
            "habitat20-contract-smoke-"
            f"{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-{identity_sha[:8]}"
        ),
        "generated_at_utc": generated_at.isoformat(),
        "evaluation": {
            "id": manifest["evaluation_id"],
            "scope": "public-val-mini-adapter-contract-smoke",
            "official_rank_eligible": False,
            "leaderboard_comparable": False,
            "official_evaluator_executed": False,
            "habitat_sim_scene_loaded": False,
            "navigation_metrics_emitted": False,
            "allowed_claim": "public-artifact adapter contract smoke",
        },
        "provenance": {
            "challenge_repository": source["repository"],
            "challenge_commit": source["commit"],
            "checkout_head": checks["pinned_checkout"]["detail"],
            "checkout_clean": checks["immutable_checkout"]["ready"],
            "manifest_path": MANIFEST_PATH.relative_to(root).as_posix(),
            "manifest_sha256": _sha256(MANIFEST_PATH),
            "source_lock_sha256": _sha256(root / "evals/external/sources.lock.json"),
            "official_config_path": task["config_relative_path"],
            "official_config_sha256": task["config_sha256"],
            "episode_archive_path": task["episodes_relative_path"],
            "episode_archive_sha256": task["episodes_sha256"],
            "public_archive_episode_count": len(episodes),
            "public_archive_scene_ids": sorted(
                {str(episode.get("scene_id")) for episode in episodes}
            ),
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "bridge_sha256": _sha256(root / "evals/external/habitat2020_py36_bridge.py"),
            "sidecar_sha256": _sha256(root / "evals/external/habitat2020_sidecar.py"),
            "navigation_config_path": config_path.relative_to(root).as_posix(),
            "navigation_config_sha256": _sha256(config_path),
            "active_model": _active_model_provenance(root, config_path),
            "parcel_python_tree": _python_tree_provenance(root),
            "parcel_git": _git_state(root),
        },
        "execution": {
            "declared_device": "cpu",
            "gpu_used": False,
            "reason": "This smoke validates IPC and contracts; full Habitat-Sim rendering is the CUDA workload.",
            "full_evaluator_gpu_detected": checks["nvidia_gpu"]["ready"],
            "full_evaluator_readiness": doctor["ready"],
            "full_evaluator_blockers": doctor["blockers"],
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
        },
        "fixture": {
            "kind": "synthetic-contract-only",
            "rgb": f"zeros uint8 {height}x{width}x3",
            "depth": f"normalized max-depth float32 {height}x{width}x1",
            "pointgoal": "deterministic rho/phi sweep independent of evaluator geometry",
            "privileged_simulator_state_used": False,
        },
        "result": {
            "passed": len(actions) == len(selected),
            "scope_complete": len(selected) == int(task["expected_episode_count"]),
            "episodes_exercised": len(actions),
            "expected_public_episodes": int(task["expected_episode_count"]),
            "action_counts": dict(sorted(action_counts.items())),
            "one_step_sidecar_latency_ms": {
                "sample_count": len(latency_ms),
                "median": statistics.median(latency_ms) if latency_ms else 0.0,
                "p95_nearest_rank": _percentile(latency_ms, 0.95),
                "max": max(latency_ms, default=0.0),
                "measurement_scope": "episode start and action synchronous JSONL round-trips; not control-loop E2E latency",
            },
            "total_wall_ms": elapsed_ms,
            "actions": actions,
        },
        "limitations": [
            "No Gibson scene was loaded and no licensed dataset was downloaded.",
            "Synthetic RGB-D frames do not measure navigation quality, collisions, Success, SPL, or Soft-SPL.",
            "Passing this smoke does not make the historical public split official-rank eligible.",
            "The unchanged controller still needs a full pinned Habitat-Sim public-validation run after the user supplies Pablo.glb and the archived GPU runtime is available.",
        ],
    }


def write_immutable_report(path: Path, report: dict[str, Any]) -> None:
    """Write once using exclusive creation; never replace prior evidence."""

    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(encoded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--navigation-config",
        type=Path,
        default=DEFAULT_NAVIGATION_CONFIG,
        help="Explicit Parcel navigation config; defaults to the unchanged deployment config.",
    )
    parser.add_argument(
        "--max-episodes",
        type=int,
        help="Development-only prefix; omit to exercise all 30 public episode identifiers.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional immutable JSON destination; an existing file is never replaced.",
    )
    args = parser.parse_args(argv)
    report = run_contract_smoke(
        navigation_config=args.navigation_config,
        max_episodes=args.max_episodes,
    )
    if args.output is not None:
        write_immutable_report(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["result"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
