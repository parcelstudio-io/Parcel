"""Fail-closed readiness audit for the archived Habitat 2020 PointNav gate."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).with_name("habitat2020_manifest.json")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (127, "", str(exc))
    return (completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "evaluation_id", "eligibility", "challenge_source", "container", "task", "adapter"}
    if not isinstance(document, dict) or not required.issubset(document):
        raise ValueError("Habitat manifest is missing required sections")
    if document["schema_version"] != 1:
        raise ValueError("unsupported Habitat manifest schema")
    if document["eligibility"].get("official_rank_eligible") is not False:
        raise ValueError("historical public-validation manifest must be rank-ineligible")
    digest = document["container"].get("base_digest")
    reference = document["container"].get("base_reference")
    if not isinstance(digest, str) or reference != f"fairembodied/habitat-challenge@{digest}":
        raise ValueError("container reference must pin the declared digest")
    return document


def audit_habitat2020(
    *,
    repo_root: Path = REPO_ROOT,
    data_root: Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Return readiness checks without installing, pulling, or downloading anything."""

    root = repo_root.resolve()
    manifest = load_manifest(manifest_path)
    source = manifest["challenge_source"]
    task = manifest["task"]
    container = manifest["container"]
    checkout = root / source["checkout_relative_path"]
    challenge_data = (data_root or checkout).resolve()
    checks: list[dict[str, Any]] = []

    def record(
        check_id: str,
        ready: bool,
        detail: str,
        remediation: str,
        *,
        category: str = "runtime",
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "ready": bool(ready),
                "required": True,
                "category": category,
                "detail": detail,
                "remediation": remediation,
            }
        )

    lock_path = root / "evals/external/sources.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        locked = lock["sources"][source["lock_key"]]
        lock_ready = (
            locked.get("url") == source["repository"]
            and locked.get("commit") == source["commit"]
        )
        lock_detail = f"{locked.get('url')}@{locked.get('commit')}"
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        lock_ready = False
        lock_detail = str(exc)
    record(
        "source_lock",
        lock_ready,
        lock_detail,
        "Restore the exact habitat_challenge_2020 entry in sources.lock.json.",
        category="provenance",
    )

    git_ready = False
    git_detail = "checkout missing"
    clean_ready = False
    clean_detail = "checkout missing"
    if checkout.is_dir():
        code, head, error = _run(["git", "rev-parse", "HEAD"], cwd=checkout)
        git_ready = code == 0 and head == source["commit"]
        git_detail = head or error
        code, status, error = _run(["git", "status", "--porcelain"], cwd=checkout)
        clean_ready = code == 0 and not status
        clean_detail = "clean" if clean_ready else status or error
    record(
        "pinned_checkout",
        git_ready,
        git_detail,
        ".parcel/bin/python evals/external/fetch_sources.py",
        category="provenance",
    )
    record(
        "immutable_checkout",
        clean_ready,
        clean_detail,
        "Do not patch the archived evaluator; restore or refetch the pinned checkout.",
        category="provenance",
    )

    def hashed_file_check(check_id: str, relative: str, expected: str) -> None:
        path = checkout / relative
        actual = _sha256(path) if path.is_file() else None
        record(
            check_id,
            actual == expected,
            f"path={path}; sha256={actual}",
            "Refetch the pinned evaluator revision; never patch the official config or episodes.",
            category="provenance",
        )

    hashed_file_check("official_task_config", task["config_relative_path"], task["config_sha256"])
    hashed_file_check(
        "public_minival_episodes",
        task["episodes_relative_path"],
        task["episodes_sha256"],
    )

    episodes_path = checkout / task["episodes_relative_path"]
    episode_ready = False
    episode_detail = "episode archive missing"
    if episodes_path.is_file():
        try:
            with gzip.open(episodes_path, "rt", encoding="utf-8") as handle:
                episodes = json.load(handle)["episodes"]
            scene_ids = {episode.get("scene_id") for episode in episodes}
            episode_ready = (
                len(episodes) == task["expected_episode_count"]
                and scene_ids == {task["required_scene_id"]}
            )
            episode_detail = f"episodes={len(episodes)}; scenes={sorted(scene_ids)}"
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            episode_detail = str(exc)
    record(
        "public_minival_shape",
        episode_ready,
        episode_detail,
        "Refetch the pinned challenge checkout containing the official val_mini episode file.",
        category="provenance",
    )

    scene_path = challenge_data / task["required_scene_relative_path"]
    record(
        "licensed_gibson_scene",
        scene_path.is_file() and scene_path.stat().st_size > 0,
        f"path={scene_path}; exists={scene_path.is_file()}",
        "Accept the Gibson research terms, then place the Habitat-format Pablo.glb at this exact path.",
        category="user_gated_asset",
    )

    nvidia_smi = shutil.which("nvidia-smi")
    gpu_ready = False
    gpu_detail = "nvidia-smi not found"
    if nvidia_smi:
        code, output, error = _run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,driver_version,compute_cap",
                "--format=csv,noheader,nounits",
            ]
        )
        gpu_ready = code == 0 and bool(output)
        gpu_detail = output or error
    record(
        "nvidia_gpu",
        gpu_ready,
        gpu_detail,
        "Install/repair the NVIDIA driver before attempting headless Habitat rendering.",
    )

    docker = shutil.which("docker")
    record(
        "docker_engine",
        docker is not None,
        docker or "docker not found",
        "Install Docker Engine from Docker's Ubuntu repository.",
    )
    toolkit = shutil.which("nvidia-container-cli") or shutil.which("nvidia-ctk")
    record(
        "nvidia_container_toolkit",
        toolkit is not None,
        toolkit or "NVIDIA container tools not found",
        "Install and configure NVIDIA Container Toolkit for Docker.",
    )

    image_ready = False
    image_detail = "Docker unavailable; image not inspected"
    if docker:
        code, output, error = _run(
            [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", container["base_reference"]]
        )
        if code == 0:
            try:
                repo_digests = json.loads(output)
            except json.JSONDecodeError:
                repo_digests = []
            image_ready = container["base_reference"] in repo_digests
            image_detail = f"repo_digests={repo_digests}"
        else:
            image_detail = error or output or "pinned image absent"
    record(
        "pinned_archived_image",
        image_ready,
        image_detail,
        f"Pull exactly {container['base_reference']}; do not evaluate an unpinned tag.",
        category="provenance",
    )

    bridge_path = root / "evals/external/habitat2020_py36_bridge.py"
    py36_ready = False
    py36_detail = "bridge file missing"
    if bridge_path.is_file():
        try:
            ast.parse(
                bridge_path.read_text(encoding="utf-8"),
                filename=str(bridge_path),
                feature_version=(3, 6),
            )
            py36_ready = True
            py36_detail = "parses with Python 3.6 grammar"
        except (OSError, SyntaxError, ValueError) as exc:
            py36_detail = str(exc)
    record(
        "python36_bridge_grammar",
        py36_ready,
        py36_detail,
        "Keep the archived-process bridge free of Python >3.6 syntax.",
        category="adapter",
    )
    parcel_import = importlib.util.find_spec("parcel_robot") is not None
    modern_python = sys.version_info >= (3, 10)
    record(
        "modern_parcel_sidecar",
        modern_python and parcel_import,
        f"python={sys.version.split()[0]}; parcel_robot_importable={parcel_import}",
        "Run the doctor from Parcel's .parcel environment (Python >=3.10).",
        category="adapter",
    )

    blockers = [check for check in checks if check["required"] and not check["ready"]]
    return {
        "schema_version": 1,
        "evaluation_id": manifest["evaluation_id"],
        "official_rank_eligible": False,
        "leaderboard_comparable": False,
        "ready": not blockers,
        "checks": checks,
        "blockers": [
            {
                "id": check["id"],
                "category": check["category"],
                "remediation": check["remediation"],
            }
            for check in blockers
        ],
        "paths": {
            "repo_root": str(root),
            "checkout": str(checkout),
            "challenge_data": str(challenge_data),
            "required_scene": str(scene_path),
        },
        "container_reference": container["base_reference"],
        "policy": {
            "no_install_or_download_performed": True,
            "no_silent_fallback": True,
            "archived_evaluator_must_remain_clean": True,
            "production_parcel_behavior_modified": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        help="Checkout root or mounted challenge-data root; defaults to the pinned checkout.",
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Print blockers but return success; intended only for inventory automation.",
    )
    args = parser.parse_args(argv)
    report = audit_habitat2020(data_root=args.data_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] or args.allow_blocked else 2


if __name__ == "__main__":
    raise SystemExit(main())
