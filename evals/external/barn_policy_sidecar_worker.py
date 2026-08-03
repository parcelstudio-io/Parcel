"""Standalone worker for the content-addressed BARN policy protocol.

Keep top-level imports standard-library-only.  The bundle's Python roots are
installed only after its complete file manifest and content address verify.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PACKAGE_KIND = "barn-ros2-parcel-submission-hook-bundle-v1"
PROTOCOL = "parcel-barn-policy-jsonl-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_LINE_BYTES = 16 * 1024 * 1024
_MAX_LIDAR_RAYS = 16_384


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("unsafe bundle-relative path")
    return path


def _verify_bundle(root: Path, package_sha256: str, manifest_sha256: str) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("policy bundle root is missing or unsafe")
    manifest_path = root / "package-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("policy bundle manifest is missing or unsafe")
    payload = manifest_path.read_bytes()
    if _sha256_bytes(payload) != manifest_sha256:
        raise ValueError("policy bundle manifest identity mismatch")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get("package_kind") != PACKAGE_KIND:
        raise ValueError("policy bundle kind mismatch")
    if manifest.get("package_sha256") != package_sha256:
        raise ValueError("policy bundle package identity mismatch")
    raw_files = manifest.get("files_sha256")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("policy bundle file manifest missing")
    files: dict[str, str] = {}
    for raw_relative, raw_digest in sorted(raw_files.items()):
        if (
            not isinstance(raw_relative, str)
            or not isinstance(raw_digest, str)
            or _SHA256.fullmatch(raw_digest) is None
        ):
            raise ValueError("policy bundle file manifest malformed")
        relative = _safe_relative(raw_relative)
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != raw_digest:
            raise ValueError(f"policy bundle file mismatch: {raw_relative}")
        files[raw_relative] = raw_digest
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("policy bundle contains a symbolic link")
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual != set(files) | {"package-manifest.json"}:
        raise ValueError("policy bundle exact membership mismatch")
    material = dict(manifest)
    material.pop("package_sha256", None)
    if _sha256_bytes(_canonical_json(material)) != package_sha256:
        raise ValueError("policy bundle content address mismatch")
    return files


def _finite(value: Any, *, nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("numeric protocol field required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("finite protocol field required")
    if nonnegative and result < 0.0:
        raise ValueError("non-negative protocol field required")
    if positive and result <= 0.0:
        raise ValueError("positive protocol field required")
    return result


def _pair(value: Any) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("two-element array required")
    return (_finite(value[0]), _finite(value[1]))


def _lidar_range(value: Any) -> float:
    """Decode calibrated clear and unavailable-ray representations."""

    if value is None:
        return math.nan
    if value == "+inf":
        return math.inf
    if isinstance(value, str):
        raise TypeError("unsupported LiDAR range sentinel")
    return _finite(value, nonnegative=True)


def _read() -> dict[str, Any] | None:
    payload = sys.stdin.buffer.readline(_MAX_LINE_BYTES + 1)
    if not payload:
        return None
    if len(payload) > _MAX_LINE_BYTES or not payload.endswith(b"\n"):
        raise ValueError("request exceeds protocol line limit")
    document = json.loads(payload)
    if not isinstance(document, dict) or document.get("protocol") != PROTOCOL:
        raise ValueError("request protocol mismatch")
    return document


def _write(document: dict[str, Any]) -> None:
    payload = _canonical_json({"protocol": PROTOCOL, **document})
    if len(payload) > _MAX_LINE_BYTES:
        raise ValueError("response exceeds protocol line limit")
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _install_bundle_import_path(bundle_root: Path) -> None:
    # The content-addressed bundle is an input, never a Python bytecode cache.
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[2]
    contaminated_roots = (repository_root / "src", repository_root / "evals")
    retained: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        resolved = Path(entry).resolve()
        contaminated = resolved == repository_root
        for root in contaminated_roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            contaminated = True
            break
        if not contaminated:
            retained.append(entry)
    sys.path[:] = [str(bundle_root / "src"), str(bundle_root), *retained]
    for name in tuple(sys.modules):
        if name == "parcel_robot" or name.startswith("parcel_robot."):
            del sys.modules[name]
        if name == "evals" or name.startswith("evals."):
            del sys.modules[name]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--navigation-config-relative", required=True)
    parser.add_argument("--worker-sha256", required=True)
    parser.add_argument("--episode-seed", required=True, type=int)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    for digest in (
        arguments.package_sha256,
        arguments.manifest_sha256,
        arguments.worker_sha256,
    ):
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("malformed source identity digest")
    if not 0 <= arguments.episode_seed < 2**63:
        raise ValueError("episode seed is out of range")
    if _sha256(Path(__file__).resolve()) != arguments.worker_sha256:
        raise ValueError("sidecar worker identity mismatch")
    bundle_root = Path(arguments.bundle_root).resolve()
    config_relative = _safe_relative(arguments.navigation_config_relative).as_posix()
    files = _verify_bundle(
        bundle_root,
        arguments.package_sha256,
        arguments.manifest_sha256,
    )
    if config_relative not in files:
        raise ValueError("navigation config is absent from bundle manifest")
    _install_bundle_import_path(bundle_root)
    with contextlib.redirect_stdout(sys.stderr):
        from evals.external.parcel_barn_adapter import ParcelBarnAdapter

        policy = ParcelBarnAdapter(navigation_config=bundle_root / config_relative)
    # Close constructor-time TOCTOU for config, registry, POI and imported code.
    _verify_bundle(bundle_root, arguments.package_sha256, arguments.manifest_sha256)
    _write(
        {
            "op": "ready",
            "package_sha256": arguments.package_sha256,
            "manifest_sha256": arguments.manifest_sha256,
            "worker_sha256": arguments.worker_sha256,
            "navigation_config_id": config_relative,
            "episode_seed": arguments.episode_seed,
        }
    )
    expected_sequence = 0
    while True:
        request = _read()
        if request is None:
            with contextlib.redirect_stdout(sys.stderr):
                policy.close()
            return 0
        operation = request.get("op")
        if operation == "reset":
            if set(request) != {"protocol", "op", "start_xy", "heading_rad", "goal_xy"}:
                raise ValueError("reset request schema mismatch")
            with contextlib.redirect_stdout(sys.stderr):
                policy.reset(
                    _pair(request["start_xy"]),
                    _finite(request["heading_rad"]),
                    _pair(request["goal_xy"]),
                )
            expected_sequence = 0
            _write({"op": "reset_ok"})
            continue
        if operation == "act":
            if set(request) != {"protocol", "op", "sequence", "observation"}:
                raise ValueError("act request schema mismatch")
            if request["sequence"] != expected_sequence:
                raise ValueError("act request sequence mismatch")
            raw = request["observation"]
            expected_observation = {
                "position_xy",
                "heading_rad",
                "lidar_ranges_m",
                "lidar_angle_min_rad",
                "lidar_angle_increment_rad",
                "time_s",
            }
            if not isinstance(raw, dict) or set(raw) != expected_observation:
                raise ValueError("observation schema mismatch")
            ranges = raw["lidar_ranges_m"]
            if not isinstance(ranges, list) or len(ranges) > _MAX_LIDAR_RAYS:
                raise ValueError("LiDAR array schema mismatch")
            observation = SimpleNamespace(
                position_xy=_pair(raw["position_xy"]),
                heading_rad=_finite(raw["heading_rad"]),
                lidar_ranges_m=tuple(_lidar_range(value) for value in ranges),
                lidar_angle_min_rad=_finite(raw["lidar_angle_min_rad"]),
                lidar_angle_increment_rad=_finite(raw["lidar_angle_increment_rad"], positive=True),
                time_s=_finite(raw["time_s"], nonnegative=True),
            )
            with contextlib.redirect_stdout(sys.stderr):
                action = policy.act(observation)
            stop = action.stop
            note = action.note
            if not isinstance(stop, bool) or not isinstance(note, str) or len(note) > 4096:
                raise TypeError("policy action stop/note fields violate the protocol")
            _write(
                {
                    "op": "action",
                    "sequence": expected_sequence,
                    "action": {
                        "vx_mps": _finite(action.vx_mps),
                        "yaw_rate_rps": _finite(action.yaw_rate_rps),
                        "stop": stop,
                        "note": note,
                    },
                }
            )
            expected_sequence += 1
            continue
        if operation == "close":
            if set(request) != {"protocol", "op"}:
                raise ValueError("close request schema mismatch")
            _verify_bundle(
                bundle_root,
                arguments.package_sha256,
                arguments.manifest_sha256,
            )
            latency_fn = getattr(policy, "latency_samples_ms", None)
            diagnostics_fn = getattr(policy, "policy_diagnostics", None)
            latency = latency_fn() if callable(latency_fn) else {}
            diagnostics = diagnostics_fn() if callable(diagnostics_fn) else {}
            with contextlib.redirect_stdout(sys.stderr):
                policy.close()
            _verify_bundle(
                bundle_root,
                arguments.package_sha256,
                arguments.manifest_sha256,
            )
            _write(
                {
                    "op": "closed",
                    "latency_samples_ms": latency if isinstance(latency, dict) else {},
                    "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
                }
            )
            return 0
        raise ValueError("unsupported policy sidecar operation")


if __name__ == "__main__":
    try:
        return_code = main()
    except Exception as error:
        with contextlib.suppress(Exception):
            _write({"op": "error", "error": f"{type(error).__name__}: {str(error)[:1000]}"})
        raise
    raise SystemExit(return_code)
