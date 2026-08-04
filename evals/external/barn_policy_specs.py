"""Feature-gated policy factories for isolated BARN experiments.

The native evaluator depends only on :class:`BarnPolicy`.  This module owns the
experiment boundary: the default spec constructs Parcel's unchanged production
navigator, while behavior variants require an explicit opt-in and remain
disabled for deployment.  No evaluator map or reference path is accepted by a
factory.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .barn_native import BarnPolicy
from .barn_policy_sidecar import (
    HISTORICAL_BUNDLE,
    HISTORICAL_CONFIG,
    HISTORICAL_MANIFEST_SHA256,
    HISTORICAL_PACKAGE_SHA256,
    IsolatedPolicyDescriptor,
)
from .parcel_barn_adapter import PARCEL_BARN_ADAPTER_ID, ParcelBarnAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
PARCEL_POLICY_SOURCE_ROOT = REPO_ROOT / "src" / "parcel_robot"
DEFAULT_NAVIGATION_CONFIG = REPO_ROOT / "configs" / "navigation" / "default.yaml"
POLICY_INPUTS = ("goal", "odometry", "270_degree_lidar", "clock")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

PolicyFactory = Callable[[int], BarnPolicy]


class ExperimentalPolicyDisabledError(ValueError):
    """Raised when a candidate policy is used without explicit opt-in."""


@dataclass(frozen=True, slots=True)
class FrozenPolicyFile:
    """One immutable file opened while constructing a Parcel navigation policy."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not self.path.strip() or not path.is_absolute():
            raise ValueError("frozen policy file paths must be non-empty and absolute")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("frozen policy file sha256 must be a lowercase SHA-256 digest")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("frozen policy file size_bytes must be a non-negative integer")

    def report_metadata(self) -> dict[str, str | int]:
        return {
            "id": _path_id(Path(self.path)),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class PolicyRuntimeDependencies:
    """Exact transitive configuration inputs loaded by ``DirectiveNavigator``.

    ``ModelRegistry.load`` parses every direct ``*.yaml`` child of its models
    root, not just the active model declaration.  Therefore membership, bytes,
    and sizes for the complete registry are part of policy identity.  The POI
    database is loaded unconditionally.  Only the active model's checkpoint is
    executable input, so non-active checkpoint artifacts are deliberately not
    included.
    """

    navigation_models_root: str
    navigation_model_files: tuple[FrozenPolicyFile, ...]
    pois_file: FrozenPolicyFile
    active_model_checkpoint_path: str | None = None
    active_model_checkpoint_kind: str | None = None
    active_model_checkpoint_files: tuple[FrozenPolicyFile, ...] = ()

    def __post_init__(self) -> None:
        models_root = Path(self.navigation_models_root)
        if not self.navigation_models_root.strip() or not models_root.is_absolute():
            raise ValueError("navigation_models_root must be non-empty and absolute")
        if not self.navigation_model_files:
            raise ValueError("navigation model registry must contain at least one YAML file")
        if not all(isinstance(record, FrozenPolicyFile) for record in self.navigation_model_files):
            raise TypeError("navigation_model_files must contain FrozenPolicyFile records")
        if not isinstance(self.pois_file, FrozenPolicyFile):
            raise TypeError("pois_file must be a FrozenPolicyFile")
        model_paths = tuple(record.path for record in self.navigation_model_files)
        if model_paths != tuple(sorted(model_paths)) or len(model_paths) != len(set(model_paths)):
            raise ValueError("navigation model registry files must be unique and sorted")
        for record in self.navigation_model_files:
            path = Path(record.path)
            if path.parent != models_root or path.suffix != ".yaml":
                raise ValueError(
                    "navigation model dependency files must be direct *.yaml children "
                    "of navigation_models_root"
                )

        checkpoint_path = self.active_model_checkpoint_path
        checkpoint_kind = self.active_model_checkpoint_kind
        checkpoint_files = self.active_model_checkpoint_files
        if checkpoint_path is None:
            if checkpoint_kind is not None or checkpoint_files:
                raise ValueError("checkpoint metadata must be empty when no checkpoint is active")
            return
        if not checkpoint_path.strip() or not Path(checkpoint_path).is_absolute():
            raise ValueError("active checkpoint path must be non-empty and absolute")
        if checkpoint_kind not in {"file", "directory"}:
            raise ValueError("active checkpoint kind must be 'file' or 'directory'")
        checkpoint_member_paths = tuple(record.path for record in checkpoint_files)
        if not all(isinstance(record, FrozenPolicyFile) for record in checkpoint_files):
            raise TypeError("active_model_checkpoint_files must contain FrozenPolicyFile records")
        if checkpoint_member_paths != tuple(sorted(checkpoint_member_paths)) or len(
            checkpoint_member_paths
        ) != len(set(checkpoint_member_paths)):
            raise ValueError("active checkpoint files must be unique and sorted")
        root = Path(checkpoint_path)
        if checkpoint_kind == "file":
            if len(checkpoint_files) != 1 or Path(checkpoint_files[0].path) != root:
                raise ValueError("file checkpoint closure must contain exactly the checkpoint file")
        else:
            for record in checkpoint_files:
                try:
                    Path(record.path).relative_to(root)
                except ValueError as error:
                    raise ValueError(
                        "directory checkpoint files must be descendants of the checkpoint root"
                    ) from error

    @property
    def dependency_set_sha256(self) -> str:
        """Digest the semantic dependency manifest, independent of JSON ordering."""

        return hashlib.sha256(
            json.dumps(
                self.report_metadata(include_set_digest=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def report_metadata(self, *, include_set_digest: bool = True) -> dict[str, Any]:
        model_files = [record.report_metadata() for record in self.navigation_model_files]
        result: dict[str, Any] = {
            "navigation_model_registry": {
                "root_id": _path_id(Path(self.navigation_models_root)),
                "membership": "exact_direct_*.yaml",
                "file_count": len(model_files),
                "files": model_files,
            },
            "places_of_interest": self.pois_file.report_metadata(),
            "active_model_checkpoint": self._checkpoint_report_metadata(),
        }
        if include_set_digest:
            result["dependency_set_sha256"] = self.dependency_set_sha256
        return result

    def verify(
        self,
        *,
        navigation_config_path: str | Path,
        active_model_artifact_path: str | Path,
    ) -> None:
        """Fail closed if membership, content, size, or config linkage changed."""

        models_root = Path(self.navigation_models_root)
        if not models_root.is_dir() or models_root.is_symlink():
            raise ValueError(f"worker navigation model root changed or is unsafe: {models_root}")
        candidates = tuple(sorted(models_root.glob("*.yaml")))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(f"worker policy input must not be a symbolic link: {candidate}")
        actual_paths = tuple(str(candidate.resolve()) for candidate in candidates)
        expected_paths = tuple(record.path for record in self.navigation_model_files)
        if actual_paths != expected_paths:
            raise ValueError(
                "worker navigation model registry membership changed after parent validation: "
                f"{models_root} (expected {expected_paths!r}, got {actual_paths!r})"
            )
        for record in self.navigation_model_files:
            _verify_frozen_file(record)
        _verify_frozen_file(self.pois_file)
        self._verify_checkpoint()
        self._verify_config_linkage(
            navigation_config_path=Path(navigation_config_path),
            active_model_artifact_path=Path(active_model_artifact_path),
        )

    def _checkpoint_report_metadata(self) -> dict[str, Any] | None:
        if self.active_model_checkpoint_path is None:
            return None
        return {
            "root_id": _path_id(Path(self.active_model_checkpoint_path)),
            "kind": self.active_model_checkpoint_kind,
            "file_count": len(self.active_model_checkpoint_files),
            "files": [record.report_metadata() for record in self.active_model_checkpoint_files],
        }

    def _verify_checkpoint(self) -> None:
        root_value = self.active_model_checkpoint_path
        if root_value is None:
            return
        root = Path(root_value)
        if root.is_symlink():
            raise ValueError(f"worker checkpoint input must not be a symbolic link: {root}")
        if self.active_model_checkpoint_kind == "file":
            _verify_frozen_file(self.active_model_checkpoint_files[0])
            return
        if not root.is_dir():
            raise ValueError(f"worker checkpoint directory changed or is missing: {root}")
        candidates = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
        for candidate in root.rglob("*"):
            if candidate.is_symlink():
                raise ValueError(
                    f"worker checkpoint input must not be a symbolic link: {candidate}"
                )
        actual_paths = tuple(str(candidate.resolve()) for candidate in candidates)
        expected_paths = tuple(record.path for record in self.active_model_checkpoint_files)
        if actual_paths != expected_paths:
            raise ValueError(
                "worker active checkpoint membership changed after parent validation: "
                f"{root} (expected {expected_paths!r}, got {actual_paths!r})"
            )
        for record in self.active_model_checkpoint_files:
            _verify_frozen_file(record)

    def _verify_config_linkage(
        self,
        *,
        navigation_config_path: Path,
        active_model_artifact_path: Path,
    ) -> None:
        data = yaml.safe_load(navigation_config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise TypeError("navigation config must contain a YAML object")
        actual_models_root = _resolve_from_config(
            navigation_config_path,
            data.get("models_root") or "configs/navigation/models",
        )
        if actual_models_root != Path(self.navigation_models_root):
            raise ValueError("navigation config no longer references the frozen models root")
        actual_pois = _resolve_from_config(
            navigation_config_path,
            data.get("pois_path") or data.get("pois") or "configs/navigation/cities/demo_pois.yaml",
        )
        if actual_pois != Path(self.pois_file.path):
            raise ValueError("navigation config no longer references the frozen POI file")
        model_id = str(data.get("active_model") or data.get("default_model") or "stub_v0")
        actual_model_artifact = _find_model_artifact(actual_models_root, model_id)
        if actual_model_artifact != active_model_artifact_path.resolve():
            raise ValueError("navigation config no longer references the frozen active model")
        model_data = yaml.safe_load(actual_model_artifact.read_text(encoding="utf-8")) or {}
        checkpoint_value = str(model_data.get("checkpoint") or "").strip()
        expected_checkpoint = self.active_model_checkpoint_path
        if not checkpoint_value:
            if expected_checkpoint is not None:
                raise ValueError("active model no longer references the frozen checkpoint")
            return
        actual_checkpoint = _resolve_checkpoint_from_runtime(checkpoint_value)
        if expected_checkpoint is None or actual_checkpoint != Path(expected_checkpoint):
            raise ValueError("active model checkpoint reference changed after parent validation")


@dataclass(frozen=True, slots=True)
class ProcessPolicyDescriptor:
    """Serializable, fail-closed recipe for an episode worker policy.

    Arbitrary :class:`BarnPolicySpec` factories are deliberately not sent to a
    process pool: closures and lambdas are not portably pickleable, and silently
    falling back to ``fork`` would make CUDA-backed policies unsafe.  Only the
    built-in Parcel configuration recipe is supported. The adapter, config,
    complete navigation-model registry, POI database, active checkpoint, and
    deterministic Python policy-source tree are re-hashed inside the worker
    before policy construction.
    """

    kind: str
    navigation_config_path: str
    navigation_config_sha256: str
    adapter_path: str
    adapter_sha256: str
    policy_source_root: str
    policy_source_sha256: str
    model_artifact_path: str
    model_artifact_sha256: str
    runtime_dependencies: PolicyRuntimeDependencies

    def __post_init__(self) -> None:
        if self.kind != "parcel_navigation_config_v1":
            raise ValueError(f"unsupported process policy descriptor kind: {self.kind!r}")
        for name in (
            "navigation_config_path",
            "adapter_path",
            "policy_source_root",
            "model_artifact_path",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        for name in (
            "navigation_config_sha256",
            "adapter_sha256",
            "policy_source_sha256",
            "model_artifact_sha256",
        ):
            digest = str(getattr(self, name))
            if not _SHA256.fullmatch(digest):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.runtime_dependencies, PolicyRuntimeDependencies):
            raise TypeError("runtime_dependencies must be PolicyRuntimeDependencies")
        active_model_record = next(
            (
                record
                for record in self.runtime_dependencies.navigation_model_files
                if record.path == str(Path(self.model_artifact_path).resolve())
            ),
            None,
        )
        if active_model_record is None:
            raise ValueError("active model artifact is absent from the frozen model registry")
        if active_model_record.sha256 != self.model_artifact_sha256:
            raise ValueError("active model artifact digest disagrees with runtime dependencies")

    def create(self, *, episode_seed: int) -> BarnPolicy:
        """Construct a fresh policy after verifying the parent's exact inputs."""

        episode_seed = int(episode_seed)
        expected_files = (
            (Path(self.navigation_config_path), self.navigation_config_sha256),
            (Path(self.adapter_path), self.adapter_sha256),
            (Path(self.model_artifact_path), self.model_artifact_sha256),
        )
        for path, expected_digest in expected_files:
            if not path.is_file():
                raise FileNotFoundError(f"worker policy input does not exist: {path}")
            actual_digest = _sha256(path)
            if actual_digest != expected_digest:
                raise ValueError(
                    f"worker policy input changed after parent validation: {path} "
                    f"(expected {expected_digest}, got {actual_digest})"
                )
        policy_source_root = Path(self.policy_source_root)
        actual_source_digest = _source_tree_sha256(policy_source_root)
        if actual_source_digest != self.policy_source_sha256:
            raise ValueError(
                "worker policy source tree changed after parent validation: "
                f"{policy_source_root} (expected {self.policy_source_sha256}, "
                f"got {actual_source_digest})"
            )
        self.runtime_dependencies.verify(
            navigation_config_path=self.navigation_config_path,
            active_model_artifact_path=self.model_artifact_path,
        )
        # DirectiveNavigator is deterministic today; the seed remains part of
        # the recipe so future stochastic built-ins cannot accidentally omit it.
        del episode_seed
        policy = ParcelBarnAdapter(navigation_config=self.navigation_config_path)
        # Constructor-time registry/POI reads must not hide a concurrent change.
        self.runtime_dependencies.verify(
            navigation_config_path=self.navigation_config_path,
            active_model_artifact_path=self.model_artifact_path,
        )
        return policy


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_and_size(path: Path) -> tuple[str, int]:
    if path.is_symlink():
        raise ValueError(f"policy dependency must not be a symbolic link: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"policy dependency is not a regular file: {path}")
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size_bytes


def _freeze_file(path: Path) -> FrozenPolicyFile:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"policy dependency must not be a symbolic link: {expanded}")
    resolved = expanded.resolve()
    digest, size_bytes = _hash_and_size(resolved)
    return FrozenPolicyFile(
        path=str(resolved),
        sha256=digest,
        size_bytes=size_bytes,
    )


def _verify_frozen_file(record: FrozenPolicyFile) -> None:
    path = Path(record.path)
    try:
        actual_digest, actual_size = _hash_and_size(path)
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(
            f"worker policy input changed after parent validation: {path} ({error})"
        ) from error
    if actual_size != record.size_bytes or actual_digest != record.sha256:
        raise ValueError(
            f"worker policy input changed after parent validation: {path} "
            f"(expected sha256={record.sha256}, size={record.size_bytes}; "
            f"got sha256={actual_digest}, size={actual_size})"
        )


def _source_tree_sha256(root: Path) -> str:
    """Hash ordered Python source paths and bytes without filesystem metadata."""

    resolved_root = root.expanduser().resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"policy source root does not exist: {resolved_root}")
    source_paths = sorted(
        (path for path in resolved_root.rglob("*.py") if path.is_file()),
        key=lambda path: path.relative_to(resolved_root).as_posix(),
    )
    if not source_paths:
        raise ValueError(f"policy source root has no Python files: {resolved_root}")
    digest = hashlib.sha256()
    for path in source_paths:
        relative = path.relative_to(resolved_root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, byteorder="big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, byteorder="big"))
        digest.update(content)
    return digest.hexdigest()


def _path_id(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


@dataclass(frozen=True, slots=True)
class BarnPolicySpec:
    """Reproducible policy construction and provenance for one experiment arm."""

    policy_id: str
    description: str
    agent_id: str
    adapter_id: str
    model_id: str
    factory: PolicyFactory = field(repr=False, compare=False)
    execution_device: str = "cpu"
    experimental: bool = False
    production_files_modified: bool = False
    deployment_enabled: bool = False
    policy_inputs: tuple[str, ...] = POLICY_INPUTS
    implementation_id: str | None = None
    implementation_sha256: str | None = None
    policy_source_id: str | None = None
    policy_source_sha256: str | None = None
    config_id: str | None = None
    config_sha256: str | None = None
    model_artifact_id: str | None = None
    model_artifact_sha256: str | None = None
    runtime_dependencies: PolicyRuntimeDependencies | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    process_descriptor: ProcessPolicyDescriptor | IsolatedPolicyDescriptor | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.policy_id):
            raise ValueError("policy_id must be a safe non-empty identifier")
        if not self.description.strip():
            raise ValueError("policy description must not be empty")
        if not self.agent_id.strip() or not self.adapter_id.strip() or not self.model_id.strip():
            raise ValueError("agent_id, adapter_id and model_id must not be empty")
        if not self.execution_device.strip():
            raise ValueError("execution_device must not be empty")
        if tuple(self.policy_inputs) != POLICY_INPUTS:
            raise ValueError(
                "BARN policies may receive only goal, odometry, 270_degree_lidar and clock"
            )
        if self.experimental and self.deployment_enabled:
            raise ValueError("experimental BARN policies must remain disabled for deployment")
        if self.runtime_dependencies is not None and not isinstance(
            self.runtime_dependencies,
            PolicyRuntimeDependencies,
        ):
            raise TypeError("runtime_dependencies must be PolicyRuntimeDependencies or None")
        if (
            self.process_descriptor is not None
            and self.runtime_dependencies is not None
            and self.process_descriptor.runtime_dependencies != self.runtime_dependencies
        ):
            raise ValueError("report and process runtime dependencies must match exactly")

    def create(self, *, episode_seed: int, allow_experimental: bool = False) -> BarnPolicy:
        """Create one episode-isolated policy after enforcing the feature gate."""

        self.ensure_enabled(allow_experimental=allow_experimental)
        policy = self.factory(int(episode_seed))
        if not isinstance(policy, BarnPolicy):
            raise TypeError("policy factory must return an object implementing BarnPolicy")
        return policy

    def ensure_enabled(self, *, allow_experimental: bool = False) -> None:
        """Fail before loading benchmark assets when an experiment is not enabled."""

        if self.experimental and not allow_experimental:
            raise ExperimentalPolicyDisabledError(
                f"policy {self.policy_id!r} is experimental; pass explicit opt-in"
            )

    def require_process_descriptor(
        self,
    ) -> ProcessPolicyDescriptor | IsolatedPolicyDescriptor:
        """Return the portable worker recipe or reject unsafe parallel use."""

        if self.process_descriptor is None:
            raise ValueError(
                f"policy {self.policy_id!r} has an arbitrary in-process factory and cannot "
                "run with workers > 1; use workers=1 or a built-in Parcel config policy"
            )
        return self.process_descriptor

    def report_metadata(self) -> dict[str, Any]:
        """Return JSON-safe metadata; the executable factory is never serialized."""

        runtime_dependencies = self.runtime_dependencies
        if runtime_dependencies is None and self.process_descriptor is not None:
            runtime_dependencies = getattr(self.process_descriptor, "runtime_dependencies", None)
        result = {
            "policy_id": self.policy_id,
            "description": self.description,
            "agent_id": self.agent_id,
            "adapter_id": self.adapter_id,
            "model_id": self.model_id,
            "execution_device": self.execution_device,
            "experimental": self.experimental,
            "production_files_modified_by_harness": self.production_files_modified,
            "production_behavior_modified": self.experimental,
            "production_default_behavior_modified": False,
            "production_behavior_variant": self.experimental,
            "deployment_enabled": self.deployment_enabled,
            "policy_inputs": list(self.policy_inputs),
            "provenance": {
                "implementation": _component(self.implementation_id, self.implementation_sha256),
                "policy_source_tree": _component(
                    self.policy_source_id,
                    self.policy_source_sha256,
                ),
                "config": _component(self.config_id, self.config_sha256),
                "model_artifact": _component(self.model_artifact_id, self.model_artifact_sha256),
                "runtime_dependencies": (
                    None if runtime_dependencies is None else runtime_dependencies.report_metadata()
                ),
            },
        }
        if isinstance(self.process_descriptor, IsolatedPolicyDescriptor):
            result["execution_isolation"] = self.process_descriptor.report_metadata()
        return result


def _component(identifier: str | None, digest: str | None) -> dict[str, str] | None:
    if identifier is None and digest is None:
        return None
    result: dict[str, str] = {}
    if identifier is not None:
        result["id"] = identifier
    if digest is not None:
        result["sha256"] = digest
    return result


def _resolve_from_config(config_path: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    from_repo = (REPO_ROOT / candidate).resolve()
    if from_repo.exists():
        return from_repo
    return (config_path.parent / candidate).resolve()


def _resolve_checkpoint_from_runtime(value: str | Path) -> Path:
    """Mirror ``CheckpointNavigator``: relative checkpoints use process cwd."""

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def _find_model_artifact(models_root: Path, model_id: str) -> Path:
    matches: list[Path] = []
    for candidate in sorted(models_root.glob("*.yaml")):
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and str(data.get("id", "")) == model_id:
            matches.append(candidate.resolve())
    if len(matches) > 1:
        raise ValueError(f"duplicate navigation model id {model_id!r} in {models_root}")
    if not matches:
        raise FileNotFoundError(
            f"no navigation model YAML declares id {model_id!r} in {models_root}"
        )
    return matches[0]


def _freeze_runtime_dependencies(
    *,
    config_path: Path,
    config_data: dict[str, Any],
    models_root: Path,
    active_model_data: dict[str, Any],
) -> PolicyRuntimeDependencies:
    if not models_root.is_dir():
        raise FileNotFoundError(f"navigation models root does not exist: {models_root}")
    model_candidates = tuple(sorted(models_root.glob("*.yaml")))
    model_files = tuple(_freeze_file(path) for path in model_candidates)
    pois_path = _resolve_from_config(
        config_path,
        config_data.get("pois_path")
        or config_data.get("pois")
        or "configs/navigation/cities/demo_pois.yaml",
    )
    pois_file = _freeze_file(pois_path)

    checkpoint_value = str(active_model_data.get("checkpoint") or "").strip()
    checkpoint_path: str | None = None
    checkpoint_kind: str | None = None
    checkpoint_files: tuple[FrozenPolicyFile, ...] = ()
    if checkpoint_value:
        resolved_checkpoint = _resolve_checkpoint_from_runtime(checkpoint_value)
        checkpoint_path = str(resolved_checkpoint)
        if resolved_checkpoint.is_file():
            checkpoint_kind = "file"
            checkpoint_files = (_freeze_file(resolved_checkpoint),)
        elif resolved_checkpoint.is_dir():
            checkpoint_kind = "directory"
            checkpoint_candidates = tuple(
                sorted(path for path in resolved_checkpoint.rglob("*") if path.is_file())
            )
            checkpoint_files = tuple(_freeze_file(path) for path in checkpoint_candidates)
        else:
            raise FileNotFoundError(
                f"active navigation model checkpoint does not exist: {resolved_checkpoint}"
            )

    return PolicyRuntimeDependencies(
        navigation_models_root=str(models_root),
        navigation_model_files=model_files,
        pois_file=pois_file,
        active_model_checkpoint_path=checkpoint_path,
        active_model_checkpoint_kind=checkpoint_kind,
        active_model_checkpoint_files=checkpoint_files,
    )


def _parcel_policy_spec(
    *,
    config_path: Path,
    policy_id: str,
    description: str,
    experimental: bool,
) -> BarnPolicySpec:
    resolved_config = config_path.expanduser().resolve()
    if not resolved_config.is_file():
        raise FileNotFoundError(f"navigation config does not exist: {resolved_config}")
    data = yaml.safe_load(resolved_config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError("navigation config must contain a YAML object")
    model_id = str(data.get("active_model") or data.get("default_model") or "stub_v0")
    models_root = _resolve_from_config(
        resolved_config,
        data.get("models_root") or "configs/navigation/models",
    )
    model_path = _find_model_artifact(models_root, model_id)
    model_data = yaml.safe_load(model_path.read_text(encoding="utf-8")) or {}
    if not isinstance(model_data, dict):
        raise TypeError("active navigation model YAML must contain an object")
    runtime_dependencies = _freeze_runtime_dependencies(
        config_path=resolved_config,
        config_data=data,
        models_root=models_root,
        active_model_data=model_data,
    )
    adapter_path = Path(__file__).with_name("parcel_barn_adapter.py")
    source_tree_sha256 = _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT)
    return BarnPolicySpec(
        policy_id=policy_id,
        description=description,
        agent_id="DirectiveNavigator",
        adapter_id=PARCEL_BARN_ADAPTER_ID,
        model_id=model_id,
        execution_device=str(model_data.get("device") or "cpu"),
        factory=lambda _seed: ParcelBarnAdapter(navigation_config=resolved_config),
        experimental=experimental,
        production_files_modified=False,
        deployment_enabled=False,
        implementation_id=_path_id(adapter_path),
        implementation_sha256=_sha256(adapter_path),
        policy_source_id=_path_id(PARCEL_POLICY_SOURCE_ROOT),
        policy_source_sha256=source_tree_sha256,
        config_id=_path_id(resolved_config),
        config_sha256=_sha256(resolved_config),
        model_artifact_id=_path_id(model_path),
        model_artifact_sha256=_sha256(model_path),
        runtime_dependencies=runtime_dependencies,
        process_descriptor=ProcessPolicyDescriptor(
            kind="parcel_navigation_config_v1",
            navigation_config_path=str(resolved_config),
            navigation_config_sha256=_sha256(resolved_config),
            adapter_path=str(adapter_path.resolve()),
            adapter_sha256=_sha256(adapter_path),
            policy_source_root=str(PARCEL_POLICY_SOURCE_ROOT.resolve()),
            policy_source_sha256=source_tree_sha256,
            model_artifact_path=str(model_path),
            model_artifact_sha256=_sha256(model_path),
            runtime_dependencies=runtime_dependencies,
        ),
    )


def parcel_baseline_policy_spec() -> BarnPolicySpec:
    """Return the immutable default arm around Parcel's unchanged navigator."""

    return _parcel_policy_spec(
        config_path=DEFAULT_NAVIGATION_CONFIG,
        policy_id="parcel-directive-baseline-v1",
        description="Unchanged Parcel DirectiveNavigator through the sensor-only adapter",
        experimental=False,
    )


def parcel_experimental_config_spec(
    config_path: str | Path,
    *,
    experiment_id: str,
    description: str,
) -> BarnPolicySpec:
    """Build an opt-in, eval-only Parcel configuration experiment arm."""

    return _parcel_policy_spec(
        config_path=Path(config_path),
        policy_id=experiment_id,
        description=description,
        experimental=True,
    )


def parcel_reference_config_spec(
    config_path: str | Path,
    *,
    reference_id: str,
    description: str,
) -> BarnPolicySpec:
    """Build a non-deployed, immutable comparison reference configuration.

    This does not promote the referenced model into Parcel's production
    default.  It only marks the arm as the unchanged reference so the paired
    harness cannot accidentally classify both arms as experimental variants.
    """

    return _parcel_policy_spec(
        config_path=Path(config_path),
        policy_id=reference_id,
        description=description,
        experimental=False,
    )


def _isolated_bundle_policy_spec(
    *,
    bundle_root: str | Path,
    package_sha256: str,
    manifest_sha256: str,
    navigation_config_relative: str,
    policy_id: str,
    description: str,
    experimental: bool,
) -> BarnPolicySpec:
    """Build an arm whose Parcel imports occur only inside a pinned sidecar."""

    descriptor = IsolatedPolicyDescriptor.freeze(
        bundle_root,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
        navigation_config_relative=navigation_config_relative,
    )
    bundle = descriptor.verify()
    config_path = bundle.root / navigation_config_relative
    config_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config_data, dict):
        raise TypeError("isolated navigation config must contain a YAML object")
    model_id = str(config_data.get("active_model") or config_data.get("default_model") or "stub_v0")
    models_value = Path(config_data.get("models_root") or "configs/navigation/models")
    if models_value.is_absolute():
        raise ValueError("isolated policy models_root must be bundle-relative")
    models_root = (bundle.root / models_value).resolve()
    try:
        models_root.relative_to(bundle.root)
    except ValueError as error:
        raise ValueError("isolated policy models_root escapes its bundle") from error
    model_path = _find_model_artifact(models_root, model_id)
    model_relative = model_path.relative_to(bundle.root).as_posix()
    if model_relative not in bundle.files_sha256:
        raise ValueError("isolated active model is absent from bundle manifest")
    model_data = yaml.safe_load(model_path.read_text(encoding="utf-8")) or {}
    if not isinstance(model_data, dict):
        raise TypeError("isolated active model YAML must contain an object")
    adapter_relative = "evals/external/parcel_barn_adapter.py"
    if adapter_relative not in bundle.files_sha256:
        raise ValueError("isolated Parcel BARN adapter is absent from bundle manifest")
    source_root = bundle.root / "src" / "parcel_robot"
    source_digest = _source_tree_sha256(source_root)
    source_id = f"bundle:{package_sha256}/src/parcel_robot"
    return BarnPolicySpec(
        policy_id=policy_id,
        description=description,
        agent_id="DirectiveNavigator",
        adapter_id=PARCEL_BARN_ADAPTER_ID,
        model_id=model_id,
        execution_device=str(model_data.get("device") or "cpu"),
        factory=lambda seed: descriptor.create(episode_seed=seed),
        experimental=experimental,
        production_files_modified=False,
        deployment_enabled=False,
        implementation_id=f"bundle:{package_sha256}/{adapter_relative}",
        implementation_sha256=bundle.files_sha256[adapter_relative],
        policy_source_id=source_id,
        policy_source_sha256=source_digest,
        config_id=f"bundle:{package_sha256}/{navigation_config_relative}",
        config_sha256=bundle.files_sha256[navigation_config_relative],
        model_artifact_id=f"bundle:{package_sha256}/{model_relative}",
        model_artifact_sha256=bundle.files_sha256[model_relative],
        process_descriptor=descriptor,
    )


def parcel_isolated_bundle_reference_spec(
    bundle_root: str | Path,
    *,
    package_sha256: str,
    manifest_sha256: str,
    navigation_config_relative: str,
    reference_id: str,
    description: str,
) -> BarnPolicySpec:
    """Create a non-deployed reference with an explicit bundle identity."""

    return _isolated_bundle_policy_spec(
        bundle_root=bundle_root,
        package_sha256=package_sha256,
        manifest_sha256=manifest_sha256,
        navigation_config_relative=navigation_config_relative,
        policy_id=reference_id,
        description=description,
        experimental=False,
    )


def parcel_isolated_bundle_candidate_spec(
    bundle_root: str | Path,
    *,
    package_sha256: str,
    reference_package_sha256: str,
    manifest_sha256: str,
    navigation_config_relative: str,
    experiment_id: str,
    description: str,
) -> BarnPolicySpec:
    """Create an opt-in candidate with a separate explicit bundle identity."""

    if _SHA256.fullmatch(reference_package_sha256) is None:
        raise ValueError("reference_package_sha256 must be a lowercase SHA-256 digest")
    if package_sha256 == reference_package_sha256:
        raise ValueError("candidate and reference must have distinct package identities")
    return _isolated_bundle_policy_spec(
        bundle_root=bundle_root,
        package_sha256=package_sha256,
        manifest_sha256=manifest_sha256,
        navigation_config_relative=navigation_config_relative,
        policy_id=experiment_id,
        description=description,
        experimental=True,
    )


def parcel_historical_isolated_reference_spec(
    bundle_root: str | Path = HISTORICAL_BUNDLE,
) -> BarnPolicySpec:
    """Return the byte-exact historical package 75f7ff4d reference arm."""

    return parcel_isolated_bundle_reference_spec(
        bundle_root,
        package_sha256=HISTORICAL_PACKAGE_SHA256,
        manifest_sha256=HISTORICAL_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="parcel-historical-75f7ff4d-isolated",
        description="Byte-exact historical Parcel 75f7ff4d bundle through JSONL isolation",
    )


def validate_isolated_policy_pair(
    reference: BarnPolicySpec,
    candidate: BarnPolicySpec,
) -> dict[str, dict[str, Any]]:
    """Fail closed unless a paired experiment uses fair, distinct sidecars."""

    reference_descriptor = reference.process_descriptor
    candidate_descriptor = candidate.process_descriptor
    if not isinstance(reference_descriptor, IsolatedPolicyDescriptor) or not isinstance(
        candidate_descriptor,
        IsolatedPolicyDescriptor,
    ):
        raise TypeError("both experiment arms must use isolated policy descriptors")
    if reference.experimental or not candidate.experimental:
        raise ValueError("isolated pair must contain one reference and one opt-in candidate")
    if reference_descriptor.package_sha256 == candidate_descriptor.package_sha256:
        raise ValueError("isolated reference and candidate package identities must differ")
    if reference_descriptor.worker_sha256 != candidate_descriptor.worker_sha256:
        raise ValueError("isolated arms must use the byte-exact same sidecar worker")
    runtime_fields = (
        "worker_path",
        "navigation_config_relative",
        "python_executable",
        "python_realpath",
        "python_binary_sha256",
        "python_implementation",
        "python_version",
        "environment",
        "request_timeout_s",
    )
    if any(
        getattr(reference_descriptor, name) != getattr(candidate_descriptor, name)
        for name in runtime_fields
    ):
        raise ValueError("isolated arms must use the exact same execution environment")
    policy_contract_fields = (
        "agent_id",
        "adapter_id",
        "model_id",
        "execution_device",
        "policy_inputs",
        "implementation_sha256",
        "model_artifact_sha256",
        "deployment_enabled",
        "production_files_modified",
    )
    if any(
        getattr(reference, name) != getattr(candidate, name)
        for name in policy_contract_fields
    ):
        raise ValueError("isolated arms must use the same policy boundary and model contract")
    if reference.deployment_enabled or candidate.deployment_enabled:
        raise ValueError("isolated experiment arms must remain disabled for deployment")
    # Re-verify both complete bundles at pairing time, not only construction.
    reference_descriptor.verify()
    candidate_descriptor.verify()
    return {
        "reference": reference_descriptor.report_metadata(),
        "candidate": candidate_descriptor.report_metadata(),
    }


def validate_isolated_planner_profile_pair(
    reference: BarnPolicySpec,
    candidate: BarnPolicySpec,
    *,
    expected_reference_model_artifact_sha256: str,
    expected_candidate_model_artifact_sha256: str,
) -> dict[str, dict[str, Any]]:
    """Validate an isolated pair whose sole policy-input delta is its model YAML.

    Unlike :func:`validate_isolated_policy_pair`, this contract deliberately
    permits the active model artifact digest to differ.  Both digests must be
    supplied explicitly and must match their respective arms.  The active
    model ID, navigation config, adapter, policy source, worker, interpreter,
    environment, and every other policy-boundary field remain equal.
    """

    for name, value in (
        (
            "expected_reference_model_artifact_sha256",
            expected_reference_model_artifact_sha256,
        ),
        (
            "expected_candidate_model_artifact_sha256",
            expected_candidate_model_artifact_sha256,
        ),
    ):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if expected_reference_model_artifact_sha256 == (
        expected_candidate_model_artifact_sha256
    ):
        raise ValueError("planner-profile model artifact identities must differ")

    reference_descriptor = reference.process_descriptor
    candidate_descriptor = candidate.process_descriptor
    if not isinstance(reference_descriptor, IsolatedPolicyDescriptor) or not isinstance(
        candidate_descriptor,
        IsolatedPolicyDescriptor,
    ):
        raise TypeError("both planner-profile arms must use isolated policy descriptors")
    if reference.experimental or not candidate.experimental:
        raise ValueError(
            "planner-profile pair must contain one reference and one opt-in candidate"
        )
    if reference_descriptor.package_sha256 == candidate_descriptor.package_sha256:
        raise ValueError("planner-profile reference and candidate packages must differ")
    if reference_descriptor.worker_sha256 != candidate_descriptor.worker_sha256:
        raise ValueError("planner-profile arms must use the byte-exact same sidecar worker")
    runtime_fields = (
        "worker_path",
        "navigation_config_relative",
        "python_executable",
        "python_realpath",
        "python_binary_sha256",
        "python_implementation",
        "python_version",
        "environment",
        "request_timeout_s",
    )
    if any(
        getattr(reference_descriptor, name) != getattr(candidate_descriptor, name)
        for name in runtime_fields
    ):
        raise ValueError("planner-profile arms must use the exact same execution environment")

    required_hash_fields = (
        "implementation_sha256",
        "policy_source_sha256",
        "config_sha256",
        "model_artifact_sha256",
    )
    if any(
        not isinstance(getattr(arm, name), str)
        or _SHA256.fullmatch(getattr(arm, name)) is None
        for arm in (reference, candidate)
        for name in required_hash_fields
    ):
        raise ValueError("planner-profile arms must expose complete SHA-256 provenance")
    equal_policy_fields = (
        "agent_id",
        "adapter_id",
        "model_id",
        "execution_device",
        "policy_inputs",
        "implementation_sha256",
        "policy_source_sha256",
        "config_sha256",
        "deployment_enabled",
        "production_files_modified",
    )
    if any(
        getattr(reference, name) != getattr(candidate, name)
        for name in equal_policy_fields
    ):
        raise ValueError(
            "planner-profile arms differ outside the exact active model artifact"
        )
    if reference.model_artifact_sha256 != expected_reference_model_artifact_sha256:
        raise ValueError("reference model artifact differs from its pinned identity")
    if candidate.model_artifact_sha256 != expected_candidate_model_artifact_sha256:
        raise ValueError("candidate model artifact differs from its pinned identity")
    if reference.deployment_enabled or candidate.deployment_enabled:
        raise ValueError("planner-profile experiment arms must remain disabled for deployment")

    reference_descriptor.verify()
    candidate_descriptor.verify()
    return {
        "reference": reference_descriptor.report_metadata(),
        "candidate": candidate_descriptor.report_metadata(),
        "allowed_planner_profile_factor": {
            "kind": "active_navigation_model_artifact_sha256",
            "model_id": reference.model_id,
            "config_sha256": reference.config_sha256,
            "reference_model_artifact_sha256": (
                expected_reference_model_artifact_sha256
            ),
            "candidate_model_artifact_sha256": (
                expected_candidate_model_artifact_sha256
            ),
            "all_other_runtime_and_policy_boundary_fields_equal": True,
        },
    }


@dataclass(frozen=True, slots=True)
class IsolatedPlannerProfileAuthorization:
    """Explicit authority for one pinned active-model-profile experiment."""

    reference_package_sha256: str
    reference_manifest_sha256: str
    candidate_package_sha256: str
    candidate_manifest_sha256: str
    reference_model_artifact_sha256: str
    candidate_model_artifact_sha256: str
    navigation_config_sha256: str
    model_id: str
    reference_policy_id: str
    candidate_policy_id: str

    def __post_init__(self) -> None:
        for name in (
            "reference_package_sha256",
            "reference_manifest_sha256",
            "candidate_package_sha256",
            "candidate_manifest_sha256",
            "reference_model_artifact_sha256",
            "candidate_model_artifact_sha256",
            "navigation_config_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if self.reference_package_sha256 == self.candidate_package_sha256:
            raise ValueError("authorized reference and candidate packages must differ")
        if self.reference_model_artifact_sha256 == self.candidate_model_artifact_sha256:
            raise ValueError("authorized planner-profile artifacts must differ")
        for name in ("reference_policy_id", "candidate_policy_id"):
            if not _SAFE_ID.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a safe non-empty identifier")
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must be non-empty")

    def report_metadata(self) -> dict[str, Any]:
        return {
            "kind": "isolated_planner_profile_artifact_delta_v1",
            "reference_package_sha256": self.reference_package_sha256,
            "reference_manifest_sha256": self.reference_manifest_sha256,
            "candidate_package_sha256": self.candidate_package_sha256,
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "reference_model_artifact_sha256": (
                self.reference_model_artifact_sha256
            ),
            "candidate_model_artifact_sha256": (
                self.candidate_model_artifact_sha256
            ),
            "navigation_config_sha256": self.navigation_config_sha256,
            "model_id": self.model_id,
            "reference_policy_id": self.reference_policy_id,
            "candidate_policy_id": self.candidate_policy_id,
            "strict_default_validation_preserved": True,
            "exact_profile_validator_required": True,
        }

    def validate_candidate_report_identity(
        self,
        *,
        package_sha256: str,
        manifest_sha256: str,
        experiment_id: str,
    ) -> None:
        """Bind separately supplied report identity to the authorized candidate."""

        if (
            package_sha256 != self.candidate_package_sha256
            or manifest_sha256 != self.candidate_manifest_sha256
            or experiment_id != self.candidate_policy_id
        ):
            raise ValueError(
                "reported candidate identity differs from the authorized candidate spec"
            )

    def validate_pair(
        self,
        reference: BarnPolicySpec,
        candidate: BarnPolicySpec,
    ) -> dict[str, dict[str, Any]]:
        """Authenticate package/config identities, then run the exact validator."""

        reference_descriptor = reference.process_descriptor
        candidate_descriptor = candidate.process_descriptor
        if not isinstance(reference_descriptor, IsolatedPolicyDescriptor) or not isinstance(
            candidate_descriptor,
            IsolatedPolicyDescriptor,
        ):
            raise TypeError("authorized planner-profile arms must use isolated descriptors")
        if (
            reference_descriptor.package_sha256 != self.reference_package_sha256
            or reference_descriptor.manifest_sha256 != self.reference_manifest_sha256
            or candidate_descriptor.package_sha256 != self.candidate_package_sha256
            or candidate_descriptor.manifest_sha256 != self.candidate_manifest_sha256
        ):
            raise ValueError("isolated planner-profile bundle differs from authorization")
        if (
            reference.policy_id != self.reference_policy_id
            or candidate.policy_id != self.candidate_policy_id
            or reference.model_id != self.model_id
            or candidate.model_id != self.model_id
            or reference.config_sha256 != self.navigation_config_sha256
            or candidate.config_sha256 != self.navigation_config_sha256
        ):
            raise ValueError("isolated planner-profile policy identity differs from authorization")
        validated = validate_isolated_planner_profile_pair(
            reference,
            candidate,
            expected_reference_model_artifact_sha256=(
                self.reference_model_artifact_sha256
            ),
            expected_candidate_model_artifact_sha256=(
                self.candidate_model_artifact_sha256
            ),
        )
        return {
            **validated,
            "planner_profile_authorization": self.report_metadata(),
        }


__all__ = [
    "POLICY_INPUTS",
    "BarnPolicySpec",
    "ExperimentalPolicyDisabledError",
    "FrozenPolicyFile",
    "IsolatedPlannerProfileAuthorization",
    "PolicyRuntimeDependencies",
    "ProcessPolicyDescriptor",
    "parcel_baseline_policy_spec",
    "parcel_experimental_config_spec",
    "parcel_historical_isolated_reference_spec",
    "parcel_isolated_bundle_candidate_spec",
    "parcel_isolated_bundle_reference_spec",
    "parcel_reference_config_spec",
    "validate_isolated_planner_profile_pair",
    "validate_isolated_policy_pair",
]
