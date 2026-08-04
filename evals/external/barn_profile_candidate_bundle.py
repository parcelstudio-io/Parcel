"""Strict one-file planner-profile derivation from an immutable policy bundle.

This builder exists for training-screen candidates whose only payload factor is
one navigation-model YAML.  Planning is read-only and computes content
identities.  Publication is separately identity-gated, no-clobber, and makes
the complete result read-only.  The caller supplies a declarative semantic
delta so a replacement cannot hide controller, model, source, shield, adapter,
evaluator, or experiment-config changes.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .barn_policy_sidecar import HISTORICAL_CONFIG, VerifiedPolicyBundle, verify_policy_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION_ROOT = REPO_ROOT / ".cache/external-evals/runtime/barn-parcel-bundles"
V8_REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
V8_REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"
DEFAULT_REFERENCE_ROOT = (
    DEFAULT_DESTINATION_ROOT / f"parcel-v8-candidate-{V8_REFERENCE_PACKAGE_SHA256}"
)
V8_REFERENCE_CONTROLLER_ID = "parcel-directive-navigator-grid-v1-v8-all-ray"
V8_PARENT_DERIVATION_ID = "parcel-v8-all-ray-candidate-from-historical-75f7ff4d-v1"
REFERENCE_FILE_COUNT = 117

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._:/_-]*$")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_MODEL_ROOT = "configs/navigation/models"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(document: Mapping[str, Any], *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            document,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(path: Path) -> None:
    candidate = _lexical_absolute(path)
    for component in (candidate, *candidate.parents):
        if os.path.lexists(component) and component.is_symlink():
            raise ValueError(f"planner-profile path contains a symbolic-link component: {component}")


def _safe_relative(value: str, *, name: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{name} must be a normalized safe relative POSIX path")
    return path


def _required_sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if value == "0" * 64:
        raise ValueError(f"{name} cannot use the all-zero placeholder digest")
    return value


def _read_regular_file(path: str | Path, *, label: str) -> bytes:
    requested = _lexical_absolute(path)
    _reject_symlink_components(requested)
    if requested.is_symlink() or not requested.is_file():
        raise FileNotFoundError(f"{label} is missing or unsafe: {requested}")
    metadata = os.lstat(requested)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"{label} must be a uniquely linked regular file: {requested}")
    return requested.read_bytes()


class _UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise ValueError("planner-profile YAML contains an unhashable mapping key") from error
        if duplicate:
            raise ValueError(f"planner-profile YAML contains a duplicate mapping key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _strict_yaml_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must be UTF-8") from error
    if not text.endswith("\n") or "\x00" in text or "\r" in text:
        raise ValueError(f"{label} must be newline-terminated UTF-8 without NUL or CR bytes")
    try:
        value = yaml.load(text, Loader=_UniqueSafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"{label} is not valid safe YAML") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{label} must contain a string-keyed YAML object")
    return value


def _same_value(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def _validate_json_scalar(value: object, *, name: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise TypeError(f"{name} must be a finite JSON scalar")


def _sorted_pairs(
    values: tuple[tuple[str, object], ...],
    *,
    name: str,
) -> tuple[tuple[str, object], ...]:
    keys = [key for key, _value in values]
    if any(not isinstance(key, str) or not key for key in keys):
        raise ValueError(f"{name} keys must be non-empty strings")
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError(f"{name} must have unique, sorted keys")
    for key, value in values:
        _validate_json_scalar(value, name=f"{name}.{key}")
    return values


@dataclass(frozen=True, slots=True)
class PlannerProfileSpec:
    """Declarative semantic authority for one model-profile replacement."""

    derivation_id: str
    candidate_label: str
    source_id: str
    replacement_destination: str
    active_model: str
    retained_controller_values: tuple[tuple[str, object], ...]
    added_controller_values: tuple[tuple[str, object], ...]
    replaced_controller_values: tuple[tuple[str, object, object], ...] = ()

    def __post_init__(self) -> None:
        for name in ("derivation_id", "candidate_label", "source_id", "active_model"):
            value = getattr(self, name)
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"{name} is not a stable lowercase identifier")
        destination = _safe_relative(
            self.replacement_destination,
            name="replacement_destination",
        )
        if destination.parent.as_posix() != _MODEL_ROOT or destination.suffix != ".yaml":
            raise ValueError("replacement_destination must be one model YAML in models_root")
        retained = _sorted_pairs(
            self.retained_controller_values,
            name="retained_controller_values",
        )
        added = _sorted_pairs(self.added_controller_values, name="added_controller_values")
        replacement_keys: list[str] = []
        for key, reference_value, candidate_value in self.replaced_controller_values:
            if not isinstance(key, str) or not key:
                raise ValueError("replaced_controller_values keys must be non-empty strings")
            _validate_json_scalar(reference_value, name=f"replaced_controller_values.{key}.from")
            _validate_json_scalar(candidate_value, name=f"replaced_controller_values.{key}.to")
            if _same_value(reference_value, candidate_value):
                raise ValueError(f"replaced controller field does not change: {key}")
            replacement_keys.append(key)
        if replacement_keys != sorted(replacement_keys) or len(set(replacement_keys)) != len(
            replacement_keys
        ):
            raise ValueError("replaced_controller_values must have unique, sorted keys")
        groups = [
            {key for key, _value in retained},
            {key for key, _value in added},
            set(replacement_keys),
        ]
        if any(groups[left] & groups[right] for left in range(3) for right in range(left + 1, 3)):
            raise ValueError("controller-field declarations must be disjoint")

    def semantics_record(self) -> dict[str, Any]:
        return {
            "active_model": self.active_model,
            "candidate_label": self.candidate_label,
            "retained_controller_values": dict(self.retained_controller_values),
            "added_controller_values": dict(self.added_controller_values),
            "replaced_controller_values": [
                {"field": key, "from": before, "to": after}
                for key, before, after in self.replaced_controller_values
            ],
        }


def _load_manifest(bundle: VerifiedPolicyBundle) -> dict[str, Any]:
    try:
        value = json.loads(bundle.manifest_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("policy bundle manifest is not valid JSON") from error
    if not isinstance(value, dict):
        raise TypeError("policy bundle manifest must contain an object")
    return value


def _validate_reference(
    reference: VerifiedPolicyBundle,
    spec: PlannerProfileSpec,
) -> dict[str, Any]:
    if len(reference.files_sha256) != REFERENCE_FILE_COUNT:
        raise ValueError(f"planner-profile reference must contain {REFERENCE_FILE_COUNT} files")
    required = {
        spec.replacement_destination,
        HISTORICAL_CONFIG,
        "evals/external/parcel_barn_adapter.py",
        "src/parcel_robot/navigation/collision.py",
        "src/parcel_robot/navigation/experimental_all_ray_shield.py",
        "src/parcel_robot/navigation/grid_navigator.py",
        "src/parcel_robot/navigation/grid_planner.py",
        "src/parcel_robot/navigation/pipeline.py",
    }
    if not required <= set(reference.files_sha256):
        raise ValueError("planner-profile reference is missing a required protected payload")
    manifest = _load_manifest(reference)
    navigation = manifest.get("navigation")
    derivation = manifest.get("experiment_derivation")
    if (
        not isinstance(navigation, dict)
        or navigation.get("config") != HISTORICAL_CONFIG
        or navigation.get("controller_id") != V8_REFERENCE_CONTROLLER_ID
    ):
        raise ValueError("planner-profile reference is not the exact V8 navigation profile")
    if (
        not isinstance(derivation, dict)
        or derivation.get("id") != V8_PARENT_DERIVATION_ID
        or derivation.get("experimental") is not True
        or derivation.get("deployment_enabled") is not False
    ):
        raise ValueError("planner-profile reference lost its rejected V8 lineage")
    for relative in reference.files_sha256:
        path = reference.root / relative
        metadata = os.lstat(path)
        if metadata.st_nlink != 1 or metadata.st_mode & _WRITE_BITS:
            raise ValueError(f"planner-profile reference payload is not immutable: {relative}")
    manifest_metadata = os.lstat(reference.manifest_path)
    if manifest_metadata.st_nlink != 1 or manifest_metadata.st_mode & _WRITE_BITS:
        raise ValueError("planner-profile reference manifest is not immutable")
    return manifest


def _validate_profile_semantics(
    reference_raw: bytes,
    candidate_raw: bytes,
    spec: PlannerProfileSpec,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = _strict_yaml_object(reference_raw, label="reference planner profile")
    candidate = _strict_yaml_object(candidate_raw, label="candidate planner profile")
    reference_controller = reference.get("controller")
    candidate_controller = candidate.get("controller")
    if not isinstance(reference_controller, dict) or not isinstance(candidate_controller, dict):
        raise TypeError("planner profiles must contain controller objects")
    if any(not isinstance(key, str) for key in (*reference_controller, *candidate_controller)):
        raise TypeError("planner-profile controller keys must be strings")

    expected = copy.deepcopy(reference)
    expected_controller = expected["controller"]
    for key, value in spec.retained_controller_values:
        if key not in reference_controller or not _same_value(reference_controller[key], value):
            raise ValueError(f"reference retained controller value differs: {key}")
    for key, value in spec.added_controller_values:
        if key in reference_controller:
            raise ValueError(f"declared controller addition already exists in reference: {key}")
        expected_controller[key] = value
    for key, before, after in spec.replaced_controller_values:
        if key not in reference_controller or not _same_value(reference_controller[key], before):
            raise ValueError(f"reference replaced controller value differs: {key}")
        expected_controller[key] = after
    if candidate != expected:
        raise ValueError("candidate planner profile contains a hidden semantic change")
    if reference.get("id") != spec.active_model or candidate.get("id") != spec.active_model:
        raise ValueError("planner-profile model identity changed")
    return reference, candidate


def _validate_active_model_resolution(
    reference: VerifiedPolicyBundle,
    spec: PlannerProfileSpec,
    candidate_raw: bytes,
) -> None:
    experiment_raw = (reference.root / HISTORICAL_CONFIG).read_bytes()
    experiment = _strict_yaml_object(experiment_raw, label="V8 experiment config")
    if experiment.get("active_model") != spec.active_model:
        raise ValueError("V8 experiment active_model differs from the planner-profile declaration")
    if experiment.get("models_root") != _MODEL_ROOT:
        raise ValueError("V8 experiment models_root differs from the frozen bundle layout")

    matching: list[str] = []
    for relative in sorted(reference.files_sha256):
        path = Path(relative)
        if path.parent.as_posix() != _MODEL_ROOT or path.suffix != ".yaml":
            continue
        raw = candidate_raw if relative == spec.replacement_destination else (
            reference.root / relative
        ).read_bytes()
        model = _strict_yaml_object(raw, label=f"navigation model {relative}")
        if model.get("id") == spec.active_model:
            matching.append(relative)
    if matching != [spec.replacement_destination]:
        raise ValueError("active_model does not resolve uniquely to the replaced planner profile")


def _reviewed_source_record(
    reference: VerifiedPolicyBundle,
    spec: PlannerProfileSpec,
    candidate_sha256: str,
) -> dict[str, dict[str, Any]]:
    return {
        spec.replacement_destination: {
            "source_id": spec.source_id,
            "source_kind": "complete_planner_profile_replacement",
            "base_sha256": reference.files_sha256[spec.replacement_destination],
            "sha256": candidate_sha256,
        }
    }


def _derivation_record(
    reference: VerifiedPolicyBundle,
    spec: PlannerProfileSpec,
    candidate_sha256: str,
) -> dict[str, Any]:
    return {
        "id": spec.derivation_id,
        "reference_manifest_sha256": reference.manifest_sha256,
        "reference_package_sha256": reference.package_sha256,
        "replacements": [spec.replacement_destination],
        "additions": [],
        "reviewed_sources": _reviewed_source_record(reference, spec, candidate_sha256),
        "profile_semantics": spec.semantics_record(),
        "reference_file_count": REFERENCE_FILE_COUNT,
        "unchanged_reference_file_count": REFERENCE_FILE_COUNT - 1,
        "all_other_file_bytes_identical_to_reference": True,
        "experiment_config_changed": False,
        "active_model_id_changed": False,
        "navigator_source_changed": False,
        "grid_planner_source_changed": False,
        "pipeline_source_changed": False,
        "collision_logic_changed": False,
        "all_ray_safety_shield_changed": False,
        "adapter_or_evaluator_source_changed": False,
        "one_factor_planner_profile_delta": True,
        "training_only": True,
        "development_execution_authorized": False,
        "holdout_execution_authorized": False,
        "external_identity_freeze_required_before_real_materialization": True,
        "experimental": True,
        "deployment_enabled": False,
    }


def _delta_record(
    reference: VerifiedPolicyBundle,
    spec: PlannerProfileSpec,
    candidate_sha256: str,
) -> dict[str, Any]:
    derivation = _derivation_record(reference, spec, candidate_sha256)
    return {
        key: copy.deepcopy(value)
        for key, value in derivation.items()
        if key not in {"id", "reference_manifest_sha256", "reference_package_sha256"}
    }


@dataclass(frozen=True, slots=True)
class PlannerProfileCandidatePlan:
    """Read-only, content-addressed plan; it does not freeze or publish anything."""

    reference: VerifiedPolicyBundle
    spec: PlannerProfileSpec
    profile_source: bytes
    profile_sha256: str
    package_sha256: str
    manifest_sha256: str
    manifest_payload: bytes
    delta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlannerProfileCandidateBundle:
    """Verified materialization plus its exact reference delta."""

    bundle: VerifiedPolicyBundle
    reference: VerifiedPolicyBundle
    spec: PlannerProfileSpec
    delta: dict[str, Any]

    @property
    def root(self) -> Path:
        return self.bundle.root


def plan_planner_profile_candidate(
    *,
    spec: PlannerProfileSpec,
    profile_source_path: str | Path,
    reference_root: str | Path = DEFAULT_REFERENCE_ROOT,
    expected_reference_package_sha256: str = V8_REFERENCE_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = V8_REFERENCE_MANIFEST_SHA256,
) -> PlannerProfileCandidatePlan:
    """Compute a strict candidate and both identities without filesystem writes."""

    expected_package = _required_sha256(
        expected_reference_package_sha256,
        name="expected_reference_package_sha256",
    )
    expected_manifest = _required_sha256(
        expected_reference_manifest_sha256,
        name="expected_reference_manifest_sha256",
    )
    reference = verify_policy_bundle(
        reference_root,
        expected_package_sha256=expected_package,
        expected_manifest_sha256=expected_manifest,
    )
    reference_manifest = _validate_reference(reference, spec)
    profile_source = _read_regular_file(profile_source_path, label="candidate planner profile")
    reference_profile = (reference.root / spec.replacement_destination).read_bytes()
    _validate_profile_semantics(reference_profile, profile_source, spec)
    _validate_active_model_resolution(reference, spec, profile_source)
    profile_sha256 = _sha256_bytes(profile_source)
    if profile_sha256 == reference.files_sha256[spec.replacement_destination]:
        raise ValueError("candidate planner profile must differ byte-for-byte from reference")

    material = copy.deepcopy(reference_manifest)
    material.pop("package_sha256", None)
    files = dict(reference.files_sha256)
    files[spec.replacement_destination] = profile_sha256
    material["files_sha256"] = dict(sorted(files.items()))
    material["experiment_derivation"] = _derivation_record(reference, spec, profile_sha256)
    package_sha256 = _sha256_bytes(_canonical_json(material))
    document = {**material, "package_sha256": package_sha256}
    manifest_payload = _canonical_json(document, pretty=True)
    return PlannerProfileCandidatePlan(
        reference=reference,
        spec=spec,
        profile_source=profile_source,
        profile_sha256=profile_sha256,
        package_sha256=package_sha256,
        manifest_sha256=_sha256_bytes(manifest_payload),
        manifest_payload=manifest_payload,
        delta=_delta_record(reference, spec, profile_sha256),
    )


def verify_planner_profile_candidate_delta(
    candidate: VerifiedPolicyBundle,
    reference: VerifiedPolicyBundle,
    *,
    spec: PlannerProfileSpec,
    expected_profile_sha256: str,
) -> dict[str, Any]:
    """Prove exact membership, byte equality, and the declared semantic delta."""

    profile_sha256 = _required_sha256(expected_profile_sha256, name="expected_profile_sha256")
    reference_manifest = _validate_reference(reference, spec)
    if candidate.package_sha256 == reference.package_sha256:
        raise ValueError("planner-profile candidate must have a distinct package identity")
    if set(candidate.files_sha256) != set(reference.files_sha256):
        raise ValueError("planner-profile candidate payload membership changed")
    changed = {
        relative
        for relative, digest in reference.files_sha256.items()
        if candidate.files_sha256[relative] != digest
    }
    if changed != {spec.replacement_destination}:
        raise ValueError("planner-profile candidate is not an exact one-file delta")
    if candidate.files_sha256[spec.replacement_destination] != profile_sha256:
        raise ValueError("planner-profile candidate digest differs from the reviewed source")
    for relative, digest in reference.files_sha256.items():
        if relative != spec.replacement_destination and candidate.files_sha256[relative] != digest:
            raise ValueError(f"planner-profile candidate changed protected payload: {relative}")

    candidate_profile = (candidate.root / spec.replacement_destination).read_bytes()
    reference_profile = (reference.root / spec.replacement_destination).read_bytes()
    _validate_profile_semantics(reference_profile, candidate_profile, spec)
    _validate_active_model_resolution(candidate, spec, candidate_profile)

    manifest = _load_manifest(candidate)
    if manifest.get("navigation") != reference_manifest.get("navigation"):
        raise ValueError("planner-profile candidate changed navigation manifest metadata")
    expected_derivation = _derivation_record(reference, spec, profile_sha256)
    if manifest.get("experiment_derivation") != expected_derivation:
        raise ValueError("planner-profile candidate derivation record is not exact")
    return _delta_record(reference, spec, profile_sha256)


def _make_tree_read_only(root: Path) -> None:
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=str)
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in files:
        path.chmod(0o444)
    for path in directories:
        path.chmod(0o555)
    root.chmod(0o555)


def _make_tree_removable(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_dir()),
        key=lambda candidate: len(candidate.parts),
    ):
        path.chmod(0o755)
    root.chmod(0o755)


def _assert_tree_read_only(
    candidate: VerifiedPolicyBundle,
    *,
    allow_private_staging_root: bool = False,
) -> None:
    for path in (candidate.root, *candidate.root.rglob("*")):
        metadata = os.lstat(path)
        private_staging_root = (
            allow_private_staging_root
            and path == candidate.root
            and stat.S_IMODE(metadata.st_mode) == 0o700
        )
        if stat.S_ISLNK(metadata.st_mode) or (
            metadata.st_mode & _WRITE_BITS and not private_staging_root
        ):
            raise ValueError(f"planner-profile candidate output is writable or aliased: {path}")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise ValueError(f"planner-profile candidate output contains a hard-linked file: {path}")


def prepare_planner_profile_candidate(
    *,
    spec: PlannerProfileSpec,
    profile_source_path: str | Path,
    expected_candidate_package_sha256: str,
    expected_candidate_manifest_sha256: str,
    reference_root: str | Path = DEFAULT_REFERENCE_ROOT,
    expected_reference_package_sha256: str = V8_REFERENCE_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = V8_REFERENCE_MANIFEST_SHA256,
    destination_root: str | Path = DEFAULT_DESTINATION_ROOT,
) -> PlannerProfileCandidateBundle:
    """Publish only an explicitly identity-gated, no-clobber candidate."""

    expected_candidate_package = _required_sha256(
        expected_candidate_package_sha256,
        name="expected_candidate_package_sha256",
    )
    expected_candidate_manifest = _required_sha256(
        expected_candidate_manifest_sha256,
        name="expected_candidate_manifest_sha256",
    )
    plan = plan_planner_profile_candidate(
        spec=spec,
        profile_source_path=profile_source_path,
        reference_root=reference_root,
        expected_reference_package_sha256=expected_reference_package_sha256,
        expected_reference_manifest_sha256=expected_reference_manifest_sha256,
    )
    if plan.package_sha256 != expected_candidate_package:
        raise ValueError("computed planner-profile package digest differs from expected identity")
    if plan.manifest_sha256 != expected_candidate_manifest:
        raise ValueError("computed planner-profile manifest digest differs from expected identity")

    reference = verify_policy_bundle(
        plan.reference.root,
        expected_package_sha256=plan.reference.package_sha256,
        expected_manifest_sha256=plan.reference.manifest_sha256,
    )
    _validate_reference(reference, spec)
    if reference.files_sha256 != plan.reference.files_sha256:
        raise ValueError("reference identity changed after the read-only planner-profile plan")

    destination = _lexical_absolute(destination_root)
    _reject_symlink_components(destination)
    if os.path.lexists(destination) and (destination.is_symlink() or not destination.is_dir()):
        raise ValueError("planner-profile destination root is not a safe directory")
    target = destination / f"parcel-profile-candidate-{plan.package_sha256}"
    if os.path.lexists(target):
        candidate = verify_policy_bundle(
            target,
            expected_package_sha256=plan.package_sha256,
            expected_manifest_sha256=plan.manifest_sha256,
        )
        _assert_tree_read_only(candidate)
        delta = verify_planner_profile_candidate_delta(
            candidate,
            reference,
            spec=spec,
            expected_profile_sha256=plan.profile_sha256,
        )
        return PlannerProfileCandidateBundle(candidate, reference, spec, delta)

    destination.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=".parcel-profile-candidate-", dir=destination))
    temporary = temporary_parent / "bundle"
    try:
        shutil.copytree(reference.root, temporary, symlinks=False)
        profile_output = temporary / spec.replacement_destination
        profile_output.chmod(0o644)
        profile_output.write_bytes(plan.profile_source)
        manifest_output = temporary / "package-manifest.json"
        manifest_output.chmod(0o644)
        manifest_output.write_bytes(plan.manifest_payload)
        _make_tree_read_only(temporary)
        temporary.chmod(0o700)
        staged = verify_policy_bundle(
            temporary,
            expected_package_sha256=plan.package_sha256,
            expected_manifest_sha256=plan.manifest_sha256,
        )
        _assert_tree_read_only(staged, allow_private_staging_root=True)
        staged_delta = verify_planner_profile_candidate_delta(
            staged,
            reference,
            spec=spec,
            expected_profile_sha256=plan.profile_sha256,
        )
        if staged_delta != plan.delta:
            raise ValueError("staged planner-profile delta differs from the read-only plan")
        try:
            os.rename(temporary, target)
        except OSError as error:
            if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FileExistsError(
                    f"refusing to replace an existing planner-profile candidate: {target}"
                ) from error
            raise
        target.chmod(0o555)
    finally:
        if temporary.exists():
            _make_tree_removable(temporary)
        if temporary_parent.exists():
            shutil.rmtree(temporary_parent)

    candidate = verify_policy_bundle(
        target,
        expected_package_sha256=plan.package_sha256,
        expected_manifest_sha256=plan.manifest_sha256,
    )
    _assert_tree_read_only(candidate)
    delta = verify_planner_profile_candidate_delta(
        candidate,
        reference,
        spec=spec,
        expected_profile_sha256=plan.profile_sha256,
    )
    if delta != plan.delta:
        raise ValueError("materialized planner-profile delta differs from the read-only plan")
    return PlannerProfileCandidateBundle(candidate, reference, spec, delta)


__all__ = [
    "DEFAULT_DESTINATION_ROOT",
    "DEFAULT_REFERENCE_ROOT",
    "REFERENCE_FILE_COUNT",
    "V8_REFERENCE_MANIFEST_SHA256",
    "V8_REFERENCE_PACKAGE_SHA256",
    "PlannerProfileCandidateBundle",
    "PlannerProfileCandidatePlan",
    "PlannerProfileSpec",
    "plan_planner_profile_candidate",
    "prepare_planner_profile_candidate",
    "verify_planner_profile_candidate_delta",
]
