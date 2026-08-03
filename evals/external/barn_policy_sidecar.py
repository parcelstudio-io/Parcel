"""Content-addressed subprocess isolation for BARN policy implementations.

The evaluator process must never import an experiment arm's ``parcel_robot``
package.  Instead, this module verifies a submission bundle, launches a small
JSON-lines worker with Python isolated mode, and exposes the worker as the
sensor-only :class:`BarnPolicy` interface.

This boundary is intended for successor experiments.  It does not change any
existing v7 result or protocol.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import select
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .barn_native import BarnAction, BarnObservation

PACKAGE_KIND = "barn-ros2-parcel-submission-hook-bundle-v1"
SIDECAR_PROTOCOL = "parcel-barn-policy-jsonl-v1"
DEFAULT_WORKER_PATH = Path(__file__).with_name("barn_policy_sidecar_worker.py")
HISTORICAL_PACKAGE_SHA256 = (
    "75f7ff4dfbf45d36f67cdf3eb3eac6a7e9d05abf48350db449ca23d93b597813"
)
HISTORICAL_MANIFEST_SHA256 = (
    "41256fa28177ddcbdbee294307355cc2af3877f5bf7235ed665057fef7dc26ef"
)
HISTORICAL_CONFIG = "configs/navigation/experiments/barn_grid_v1.yaml"
HISTORICAL_BUNDLE = (
    Path(__file__).resolve().parents[2]
    / ".cache/external-evals/runtime/barn-parcel-bundles"
    / "parcel-world0-75f7ff4dfbf45d36"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_LINE_BYTES = 16 * 1024 * 1024
_MAX_LIDAR_RAYS = 16_384
_SIDECAR_ENV_KEYS = ("LANG", "LC_ALL", "LD_LIBRARY_PATH", "OMP_NUM_THREADS", "PATH")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_relative(value: str, *, name: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{name} must be a normalized safe relative POSIX path")
    return path


@dataclass(frozen=True, slots=True)
class VerifiedPolicyBundle:
    """The exact, independently verified source identity of one policy arm."""

    root: Path
    manifest_path: Path
    manifest_sha256: str
    package_sha256: str
    files_sha256: dict[str, str]

    def report_metadata(self) -> dict[str, Any]:
        return {
            "isolation": "python_isolated_mode_jsonl_subprocess",
            "protocol": SIDECAR_PROTOCOL,
            "package_kind": PACKAGE_KIND,
            "package_sha256": self.package_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifested_file_count": len(self.files_sha256),
        }


def verify_policy_bundle(
    root: str | Path,
    *,
    expected_package_sha256: str,
    expected_manifest_sha256: str,
) -> VerifiedPolicyBundle:
    """Verify exact membership and every byte in a content-addressed bundle."""

    if _SHA256.fullmatch(expected_package_sha256) is None:
        raise ValueError("expected_package_sha256 must be a lowercase SHA-256 digest")
    if _SHA256.fullmatch(expected_manifest_sha256) is None:
        raise ValueError("expected_manifest_sha256 must be a lowercase SHA-256 digest")
    expanded_root = Path(root).expanduser()
    if expanded_root.is_symlink():
        raise ValueError(f"policy bundle root is missing or unsafe: {expanded_root}")
    bundle_root = expanded_root.resolve()
    if not bundle_root.is_dir():
        raise ValueError(f"policy bundle root is missing or unsafe: {bundle_root}")
    manifest_path = bundle_root / "package-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("policy bundle manifest is missing or unsafe")
    manifest_payload = manifest_path.read_bytes()
    manifest_sha256 = _sha256_bytes(manifest_payload)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("policy bundle manifest does not match its explicit identity")
    try:
        manifest = json.loads(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("policy bundle manifest is not valid JSON") from error
    if not isinstance(manifest, dict) or manifest.get("package_kind") != PACKAGE_KIND:
        raise ValueError("policy bundle kind mismatch")
    if manifest.get("package_sha256") != expected_package_sha256:
        raise ValueError("policy bundle package digest does not match its explicit identity")
    raw_files = manifest.get("files_sha256")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ValueError("policy bundle has no file manifest")

    files: dict[str, str] = {}
    for raw_relative, raw_digest in sorted(raw_files.items()):
        if not isinstance(raw_relative, str) or not isinstance(raw_digest, str):
            raise TypeError("policy bundle file manifest is malformed")
        relative = _safe_relative(raw_relative, name="manifest file")
        if _SHA256.fullmatch(raw_digest) is None:
            raise ValueError("policy bundle file digest is malformed")
        candidate = bundle_root / relative
        if candidate.is_symlink() or not candidate.is_file() or _sha256(candidate) != raw_digest:
            raise ValueError(f"policy bundle file mismatch: {raw_relative}")
        files[raw_relative] = raw_digest

    for candidate in bundle_root.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(f"policy bundle contains a symbolic link: {candidate}")
    actual_files = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    }
    if actual_files != set(files) | {"package-manifest.json"}:
        raise ValueError("policy bundle contains unmanifested or missing files")
    material = dict(manifest)
    material.pop("package_sha256", None)
    if _sha256_bytes(_canonical_json(material)) != expected_package_sha256:
        raise ValueError("policy bundle content-address digest mismatch")
    return VerifiedPolicyBundle(
        root=bundle_root,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        package_sha256=expected_package_sha256,
        files_sha256=files,
    )


@dataclass(frozen=True, slots=True)
class IsolatedPolicyDescriptor:
    """Pickle-safe recipe for a byte-exact policy subprocess."""

    bundle_root: str
    package_sha256: str
    manifest_sha256: str
    navigation_config_relative: str
    worker_path: str
    worker_sha256: str
    python_executable: str
    python_realpath: str
    python_binary_sha256: str
    python_implementation: str
    python_version: str
    environment: tuple[tuple[str, str], ...]
    request_timeout_s: float = 30.0

    def __post_init__(self) -> None:
        if not Path(self.bundle_root).is_absolute():
            raise ValueError("bundle_root must be absolute")
        if not Path(self.worker_path).is_absolute():
            raise ValueError("worker_path must be absolute")
        if not Path(self.python_executable).is_absolute() or not Path(
            self.python_realpath
        ).is_absolute():
            raise ValueError("Python interpreter paths must be absolute")
        for name in (
            "package_sha256",
            "manifest_sha256",
            "worker_sha256",
            "python_binary_sha256",
        ):
            if _SHA256.fullmatch(str(getattr(self, name))) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if self.python_implementation not in {"CPython", "PyPy"} or not self.python_version:
            raise ValueError("Python runtime identity is malformed")
        if tuple(sorted(self.environment)) != self.environment or len(
            {name for name, _value in self.environment}
        ) != len(self.environment):
            raise ValueError("sidecar environment must be unique and sorted")
        if any(name not in _SIDECAR_ENV_KEYS for name, _value in self.environment):
            raise ValueError("sidecar environment contains an unapproved key")
        _safe_relative(self.navigation_config_relative, name="navigation_config_relative")
        if (
            isinstance(self.request_timeout_s, bool)
            or not math.isfinite(self.request_timeout_s)
            or self.request_timeout_s <= 0.0
        ):
            raise ValueError("request_timeout_s must be finite and positive")

    @classmethod
    def freeze(
        cls,
        bundle_root: str | Path,
        *,
        expected_package_sha256: str,
        expected_manifest_sha256: str,
        navigation_config_relative: str,
        worker_path: str | Path = DEFAULT_WORKER_PATH,
        request_timeout_s: float = 30.0,
    ) -> IsolatedPolicyDescriptor:
        bundle = verify_policy_bundle(
            bundle_root,
            expected_package_sha256=expected_package_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        config_relative = _safe_relative(
            navigation_config_relative,
            name="navigation_config_relative",
        ).as_posix()
        if config_relative not in bundle.files_sha256:
            raise ValueError("navigation config is absent from the frozen policy bundle")
        worker = Path(worker_path).expanduser().resolve()
        if worker.is_symlink() or not worker.is_file():
            raise ValueError("policy sidecar worker is missing or unsafe")
        python_executable = Path(sys.executable).absolute()
        python_realpath = python_executable.resolve()
        environment = tuple(
            sorted((name, os.environ[name]) for name in _SIDECAR_ENV_KEYS if name in os.environ)
        )
        return cls(
            bundle_root=str(bundle.root),
            package_sha256=bundle.package_sha256,
            manifest_sha256=bundle.manifest_sha256,
            navigation_config_relative=config_relative,
            worker_path=str(worker),
            worker_sha256=_sha256(worker),
            python_executable=str(python_executable),
            python_realpath=str(python_realpath),
            python_binary_sha256=_sha256(python_realpath),
            python_implementation=platform.python_implementation(),
            python_version=platform.python_version(),
            environment=environment,
            request_timeout_s=float(request_timeout_s),
        )

    def verify(self) -> VerifiedPolicyBundle:
        worker = Path(self.worker_path)
        if worker.is_symlink() or not worker.is_file() or _sha256(worker) != self.worker_sha256:
            raise ValueError("policy sidecar worker changed after descriptor freeze")
        current_executable = Path(sys.executable).absolute()
        current_realpath = current_executable.resolve()
        current_environment = tuple(
            sorted((name, os.environ[name]) for name in _SIDECAR_ENV_KEYS if name in os.environ)
        )
        if (
            str(current_executable) != self.python_executable
            or str(current_realpath) != self.python_realpath
            or _sha256(current_realpath) != self.python_binary_sha256
            or platform.python_implementation() != self.python_implementation
            or platform.python_version() != self.python_version
            or current_environment != self.environment
        ):
            raise ValueError("policy sidecar execution environment changed after freeze")
        bundle = verify_policy_bundle(
            self.bundle_root,
            expected_package_sha256=self.package_sha256,
            expected_manifest_sha256=self.manifest_sha256,
        )
        if self.navigation_config_relative not in bundle.files_sha256:
            raise ValueError("navigation config disappeared from policy bundle")
        return bundle

    def create(self, *, episode_seed: int) -> IsolatedBarnPolicy:
        self.verify()
        return IsolatedBarnPolicy(self, episode_seed=int(episode_seed))

    def report_metadata(self) -> dict[str, Any]:
        return {
            "isolation": "python_isolated_mode_jsonl_subprocess",
            "protocol": SIDECAR_PROTOCOL,
            "package_kind": PACKAGE_KIND,
            "package_sha256": self.package_sha256,
            "manifest_sha256": self.manifest_sha256,
            "navigation_config_id": self.navigation_config_relative,
            "worker_sha256": self.worker_sha256,
            "python": {
                "executable": self.python_executable,
                "realpath": self.python_realpath,
                "binary_sha256": self.python_binary_sha256,
                "implementation": self.python_implementation,
                "version": self.python_version,
            },
            "environment": dict(self.environment),
            "request_timeout_s": self.request_timeout_s,
        }


class IsolatedBarnPolicy:
    """Strict JSON-lines proxy implementing the evaluator's policy protocol."""

    def __init__(self, descriptor: IsolatedPolicyDescriptor, *, episode_seed: int) -> None:
        if not 0 <= episode_seed < 2**63:
            raise ValueError("episode_seed must be in [0, 2**63)")
        self._descriptor = descriptor
        self._episode_seed = episode_seed
        self._sequence = 0
        self._closed = False
        self._stdout_buffer = bytearray()
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()
        self._latency: dict[str, tuple[float, ...]] = {}
        self._diagnostics: dict[str, Any] = {}
        self._reset_round_trip_ms: list[float] = []
        self._act_round_trip_ms: list[float] = []
        process_started_ns = time.perf_counter_ns()
        command = [
            descriptor.python_executable,
            "-I",
            descriptor.worker_path,
            "--bundle-root",
            descriptor.bundle_root,
            "--package-sha256",
            descriptor.package_sha256,
            "--manifest-sha256",
            descriptor.manifest_sha256,
            "--navigation-config-relative",
            descriptor.navigation_config_relative,
            "--worker-sha256",
            descriptor.worker_sha256,
            "--episode-seed",
            str(episode_seed),
        ]
        environment = dict(descriptor.environment)
        # ``-I`` intentionally ignores PYTHON* environment variables.  The
        # episode seed crosses the explicit protocol; no hash-seed claim is
        # made. A bounded background drain prevents a chatty child deadlock.
        self._process = subprocess.Popen(
            command,
            cwd=descriptor.bundle_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"barn-policy-stderr-{self._process.pid}",
            daemon=True,
        )
        self._stderr_thread.start()
        try:
            ready = self._receive()
            expected = {
                "protocol": SIDECAR_PROTOCOL,
                "op": "ready",
                "package_sha256": descriptor.package_sha256,
                "manifest_sha256": descriptor.manifest_sha256,
                "worker_sha256": descriptor.worker_sha256,
                "navigation_config_id": descriptor.navigation_config_relative,
                "episode_seed": episode_seed,
            }
            if ready != expected:
                raise RuntimeError("policy sidecar identity handshake mismatch")
            self._process_start_ms = (time.perf_counter_ns() - process_started_ns) / 1e6
        except BaseException:
            self._terminate()
            raise

    def _send(self, document: Mapping[str, Any]) -> None:
        if self._closed or self._process.stdin is None:
            raise RuntimeError("policy sidecar is closed")
        payload = _canonical_json(document)
        if len(payload) > _MAX_JSON_LINE_BYTES:
            raise ValueError("policy sidecar request exceeds protocol limit")
        try:
            self._process.stdin.write(payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError(self._failure_message("policy sidecar request failed")) from error

    def _receive(self) -> dict[str, Any]:
        stdout = self._process.stdout
        if stdout is None:
            raise RuntimeError("policy sidecar stdout is unavailable")
        payload = self._readline(stdout)
        if not payload:
            raise RuntimeError(self._failure_message("policy sidecar exited before response"))
        if not payload.endswith(b"\n"):
            raise RuntimeError(self._failure_message("policy sidecar emitted a truncated response"))
        try:
            response = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("policy sidecar emitted invalid JSON") from error
        if not isinstance(response, dict):
            raise TypeError("policy sidecar response must be a JSON object")
        if response.get("protocol") != SIDECAR_PROTOCOL:
            raise RuntimeError("policy sidecar response protocol mismatch")
        if response.get("op") == "error":
            raise RuntimeError(f"policy sidecar rejected request: {response.get('error')!r}")
        return response

    def _request(self, document: Mapping[str, Any], *, expected_op: str) -> dict[str, Any]:
        self._send(document)
        response = self._receive()
        if response.get("op") != expected_op:
            raise RuntimeError(f"expected policy sidecar operation {expected_op!r}")
        return response

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        start = _finite_pair(start_xy, name="start_xy")
        goal = _finite_pair(goal_xy, name="goal_xy")
        heading = _finite_float(heading_rad, name="heading_rad")
        started_ns = time.perf_counter_ns()
        response = self._request(
            {
                "protocol": SIDECAR_PROTOCOL,
                "op": "reset",
                "start_xy": list(start),
                "heading_rad": heading,
                "goal_xy": list(goal),
            },
            expected_op="reset_ok",
        )
        if set(response) != {"protocol", "op"}:
            raise RuntimeError("policy sidecar reset response schema mismatch")
        self._reset_round_trip_ms.append((time.perf_counter_ns() - started_ns) / 1e6)

    def act(self, observation: BarnObservation) -> BarnAction:
        if len(observation.lidar_ranges_m) > _MAX_LIDAR_RAYS:
            raise ValueError("LiDAR frame exceeds policy protocol ray limit")
        # JSON has no non-finite numeric representation.  The protocol keeps
        # the two calibrated LaserScan meanings distinct: ``"+inf"`` is a
        # valid clear ray and ``null`` is an unavailable/self-masked bin.
        ranges = [_encode_lidar_range(value) for value in observation.lidar_ranges_m]
        sequence = self._sequence
        started_ns = time.perf_counter_ns()
        response = self._request(
            {
                "protocol": SIDECAR_PROTOCOL,
                "op": "act",
                "sequence": sequence,
                "observation": {
                    "position_xy": list(_finite_pair(observation.position_xy, name="position_xy")),
                    "heading_rad": _finite_float(observation.heading_rad, name="heading_rad"),
                    "lidar_ranges_m": ranges,
                    "lidar_angle_min_rad": _finite_float(
                        observation.lidar_angle_min_rad, name="lidar_angle_min_rad"
                    ),
                    "lidar_angle_increment_rad": _finite_float(
                        observation.lidar_angle_increment_rad,
                        name="lidar_angle_increment_rad",
                        positive=True,
                    ),
                    "time_s": _finite_float(observation.time_s, name="time_s", nonnegative=True),
                },
            },
            expected_op="action",
        )
        if set(response) != {"protocol", "op", "sequence", "action"}:
            raise RuntimeError("policy sidecar action response schema mismatch")
        if response["sequence"] != sequence:
            raise RuntimeError("policy sidecar action sequence mismatch")
        action = response["action"]
        if not isinstance(action, dict) or set(action) != {
            "vx_mps",
            "yaw_rate_rps",
            "stop",
            "note",
        }:
            raise RuntimeError("policy sidecar action payload schema mismatch")
        stop = action["stop"]
        note = action["note"]
        if not isinstance(stop, bool) or not isinstance(note, str) or len(note) > 4096:
            raise RuntimeError("policy sidecar action contains invalid stop/note fields")
        self._act_round_trip_ms.append((time.perf_counter_ns() - started_ns) / 1e6)
        self._sequence += 1
        return BarnAction(
            vx_mps=_finite_float(action["vx_mps"], name="vx_mps"),
            yaw_rate_rps=_finite_float(action["yaw_rate_rps"], name="yaw_rate_rps"),
            stop=stop,
            note=note,
        )

    def close(self) -> None:
        if self._closed:
            return
        try:
            # Detect any package/runtime mutation before asking the child to
            # report diagnostics. The child independently verifies the same
            # complete bundle immediately before and after policy.close().
            self._descriptor.verify()
            started_ns = time.perf_counter_ns()
            response = self._request(
                {"protocol": SIDECAR_PROTOCOL, "op": "close"},
                expected_op="closed",
            )
            if set(response) != {"protocol", "op", "latency_samples_ms", "diagnostics"}:
                raise RuntimeError("policy sidecar close response schema mismatch")
            latency = _validate_latency(response["latency_samples_ms"])
            if any(name.startswith("sidecar_") for name in latency):
                raise RuntimeError("policy sidecar child used a reserved latency namespace")
            latency.update(
                {
                    "sidecar_process_start": (self._process_start_ms,),
                    "sidecar_reset_round_trip": tuple(self._reset_round_trip_ms),
                    "sidecar_act_round_trip": tuple(self._act_round_trip_ms),
                    "sidecar_close_round_trip": (
                        (time.perf_counter_ns() - started_ns) / 1e6,
                    ),
                }
            )
            self._latency = latency
            diagnostics = response["diagnostics"]
            self._diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        finally:
            self._closed = True
            self._terminate()
            self._descriptor.verify()

    def latency_samples_ms(self) -> dict[str, tuple[float, ...]]:
        return dict(self._latency)

    def latency_metrics(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for name, samples in self._latency.items():
            if samples:
                ordered = sorted(samples)
                result[f"{name}_count"] = float(len(ordered))
                result[f"{name}_mean_ms"] = sum(ordered) / len(ordered)
                result[f"{name}_p99_ms"] = ordered[max(0, math.ceil(0.99 * len(ordered)) - 1)]
                result[f"{name}_max_ms"] = ordered[-1]
        return result

    def policy_diagnostics(self) -> dict[str, Any]:
        return dict(self._diagnostics)

    def _terminate(self) -> None:
        process = self._process
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if process.poll() is None:
            try:
                process.wait(timeout=0.5 if self._closed else 0.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        if process.stderr is not None:
            process.stderr.close()
        self._stderr_thread.join(timeout=1.0)

    def _failure_message(self, prefix: str) -> str:
        return_code = self._process.poll()
        suffix = "" if return_code is None else f" (exit {return_code})"
        with self._stderr_lock:
            stderr_tail = bytes(self._stderr_tail).decode("utf-8", errors="replace").strip()
        detail = "" if not stderr_tail else f": stderr tail: {stderr_tail}"
        return f"{prefix}{suffix}{detail}"

    def _drain_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        while True:
            try:
                chunk = stream.read(8192)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr_tail.extend(chunk)
                if len(self._stderr_tail) > 65_536:
                    del self._stderr_tail[:-65_536]

    def _readline(self, stdout: Any) -> bytes:
        deadline = time.monotonic() + self._descriptor.request_timeout_s
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline >= 0:
                payload = bytes(self._stdout_buffer[: newline + 1])
                del self._stdout_buffer[: newline + 1]
                return payload
            if len(self._stdout_buffer) > _MAX_JSON_LINE_BYTES:
                raise RuntimeError("policy sidecar response exceeds protocol limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError("policy sidecar response timed out")
            ready, _, _ = select.select([stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("policy sidecar response timed out")
            chunk = os.read(stdout.fileno(), min(65_536, _MAX_JSON_LINE_BYTES + 1))
            if not chunk:
                return bytes(self._stdout_buffer)
            self._stdout_buffer.extend(chunk)


def historical_isolated_policy_descriptor(
    bundle_root: str | Path = HISTORICAL_BUNDLE,
) -> IsolatedPolicyDescriptor:
    """Freeze the exact historical 75f7ff4d reference implementation."""

    return IsolatedPolicyDescriptor.freeze(
        bundle_root,
        expected_package_sha256=HISTORICAL_PACKAGE_SHA256,
        expected_manifest_sha256=HISTORICAL_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
    )


def _finite_float(
    value: Any,
    *,
    name: str,
    nonnegative: bool = False,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0.0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _encode_lidar_range(value: Any) -> float | str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("lidar_ranges_m must be numeric")
    result = float(value)
    if result == math.inf:
        return "+inf"
    if math.isnan(result):
        return None
    if not math.isfinite(result):
        raise ValueError(
            "lidar_ranges_m must be non-negative, NaN, or positive infinity"
        )
    if result < 0.0:
        raise ValueError(
            "lidar_ranges_m must be non-negative, NaN, or positive infinity"
        )
    return result


def _finite_pair(value: Any, *, name: str) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{name} must contain two values")
    return (_finite_float(value[0], name=name), _finite_float(value[1], name=name))


def _validate_latency(value: Any) -> dict[str, tuple[float, ...]]:
    if not isinstance(value, dict):
        raise TypeError("policy sidecar latency payload must be an object")
    result: dict[str, tuple[float, ...]] = {}
    for raw_name, raw_samples in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_samples, list):
            raise TypeError("policy sidecar latency payload is malformed")
        result[raw_name] = tuple(
            _finite_float(sample, name="latency_sample", nonnegative=True)
            for sample in raw_samples
        )
    return result


__all__ = [
    "DEFAULT_WORKER_PATH",
    "HISTORICAL_BUNDLE",
    "HISTORICAL_CONFIG",
    "HISTORICAL_MANIFEST_SHA256",
    "HISTORICAL_PACKAGE_SHA256",
    "SIDECAR_PROTOCOL",
    "IsolatedBarnPolicy",
    "IsolatedPolicyDescriptor",
    "VerifiedPolicyBundle",
    "historical_isolated_policy_descriptor",
    "verify_policy_bundle",
]
