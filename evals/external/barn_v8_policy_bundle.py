"""Derive the v8 policy bundle from the byte-exact historical reference.

The repository is intentionally dirty and contains work unrelated to the v8
collision experiment.  Packaging the current tree wholesale would therefore
confound the comparison.  This builder starts from a completely verified
historical bundle and changes only the explicitly reviewed v8 policy files.

The v8 experiment configuration is installed at the historical bundle's
configuration path.  This keeps the documented ROS hook and the sidecar entry
point aligned without changing either adapter or any evaluator code.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .barn_policy_sidecar import (
    HISTORICAL_BUNDLE,
    HISTORICAL_CONFIG,
    HISTORICAL_MANIFEST_SHA256,
    HISTORICAL_PACKAGE_SHA256,
    VerifiedPolicyBundle,
    verify_policy_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION_ROOT = (
    REPO_ROOT / ".cache/external-evals/runtime/barn-parcel-bundles"
)
V8_DERIVATION_ID = "parcel-v8-all-ray-candidate-from-historical-75f7ff4d-v1"
V8_CONFIG_SOURCE = Path(
    "configs/navigation/experiments/barn_grid_v1_all_ray_yaw_swept_cap_0p8_v8.yaml"
)

# Keys are bundle-relative destinations. Values are repository-relative,
# reviewed source inputs. No directory glob can expand this authority.
V8_REPLACEMENTS: dict[str, str] = {
    HISTORICAL_CONFIG: V8_CONFIG_SOURCE.as_posix(),
    "src/parcel_robot/navigation/collision.py": (
        "src/parcel_robot/navigation/collision.py"
    ),
    "src/parcel_robot/navigation/pipeline.py": (
        "src/parcel_robot/navigation/pipeline.py"
    ),
}
V8_ADDITIONS: dict[str, str] = {
    "src/parcel_robot/navigation/experimental_all_ray_shield.py": (
        "src/parcel_robot/navigation/experimental_all_ray_shield.py"
    ),
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def _load_manifest(bundle: VerifiedPolicyBundle) -> dict[str, Any]:
    document = json.loads(bundle.manifest_path.read_bytes())
    if not isinstance(document, dict):
        raise TypeError("policy bundle manifest must contain an object")
    return document


def _reviewed_sources(repo_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for destination, source_relative in sorted({**V8_REPLACEMENTS, **V8_ADDITIONS}.items()):
        source = repo_root / source_relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"reviewed v8 source is missing or unsafe: {source_relative}")
        result[destination] = {
            "source_id": source_relative,
            "sha256": _sha256(source),
        }
    return result


@dataclass(frozen=True, slots=True)
class V8CandidateBundle:
    """A verified v8 candidate plus its exact historical delta."""

    bundle: VerifiedPolicyBundle
    reference: VerifiedPolicyBundle
    delta: dict[str, Any]

    @property
    def root(self) -> Path:
        return self.bundle.root

    @property
    def package_sha256(self) -> str:
        return self.bundle.package_sha256

    @property
    def manifest_sha256(self) -> str:
        return self.bundle.manifest_sha256

    def report_metadata(self) -> dict[str, Any]:
        return {
            **self.bundle.report_metadata(),
            "derivation_id": V8_DERIVATION_ID,
            "reference_package_sha256": self.reference.package_sha256,
            "allowlisted_delta": copy.deepcopy(self.delta),
        }


def verify_v8_candidate_delta(
    candidate: VerifiedPolicyBundle,
    reference: VerifiedPolicyBundle,
    *,
    repo_root: str | Path | None = REPO_ROOT,
    expected_reviewed_sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require exact equality outside the four reviewed v8 destinations."""

    if candidate.package_sha256 == reference.package_sha256:
        raise ValueError("v8 candidate must have a distinct package identity")
    if expected_reviewed_sources is None:
        if repo_root is None:
            raise ValueError("working-tree or frozen reviewed-source identity is required")
        source_root = Path(repo_root).expanduser().resolve()
        reviewed = _reviewed_sources(source_root)
    else:
        reviewed = copy.deepcopy(dict(expected_reviewed_sources))
        if set(reviewed) != set(V8_REPLACEMENTS) | set(V8_ADDITIONS):
            raise ValueError("frozen v8 reviewed-source membership is invalid")
        for relative, record in reviewed.items():
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("source_id"), str)
                or not isinstance(record.get("sha256"), str)
                or len(record["sha256"]) != 64
            ):
                raise ValueError(f"frozen v8 reviewed-source identity is invalid: {relative}")
    reference_files = reference.files_sha256
    candidate_files = candidate.files_sha256
    expected_replacements = set(V8_REPLACEMENTS)
    expected_additions = set(V8_ADDITIONS)
    if not expected_replacements <= set(reference_files):
        raise ValueError("historical reference is missing a v8 replacement destination")
    if expected_additions & set(reference_files):
        raise ValueError("a declared v8 addition already exists in the historical reference")
    if set(candidate_files) != set(reference_files) | expected_additions:
        raise ValueError("v8 candidate bundle membership differs outside the allowlist")

    changed = {
        relative
        for relative in reference_files
        if candidate_files[relative] != reference_files[relative]
    }
    if changed != expected_replacements:
        raise ValueError(
            "v8 candidate changed historical files outside the exact replacement set"
        )
    for relative in expected_replacements | expected_additions:
        if candidate_files[relative] != reviewed[relative]["sha256"]:
            raise ValueError(f"v8 candidate source digest mismatch: {relative}")

    candidate_manifest = _load_manifest(candidate)
    derivation = candidate_manifest.get("experiment_derivation")
    expected_derivation = {
        "id": V8_DERIVATION_ID,
        "reference_manifest_sha256": reference.manifest_sha256,
        "reference_package_sha256": reference.package_sha256,
        "replacements": sorted(expected_replacements),
        "additions": sorted(expected_additions),
        "reviewed_sources": reviewed,
        "all_other_file_bytes_identical_to_reference": True,
        "evaluator_or_adapter_source_changed": False,
        "experimental": True,
        "deployment_enabled": False,
    }
    if derivation != expected_derivation:
        raise ValueError("v8 candidate derivation record is not exact")
    return {
        "replacements": sorted(expected_replacements),
        "additions": sorted(expected_additions),
        "unchanged_file_count": len(reference_files) - len(expected_replacements),
        "reviewed_sources": reviewed,
        "all_other_file_bytes_identical_to_reference": True,
        "evaluator_or_adapter_source_changed": False,
        "experimental": True,
        "deployment_enabled": False,
    }


def prepare_v8_candidate_bundle(
    *,
    repo_root: str | Path = REPO_ROOT,
    reference_root: str | Path = HISTORICAL_BUNDLE,
    expected_reference_package_sha256: str = HISTORICAL_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = HISTORICAL_MANIFEST_SHA256,
    destination_root: str | Path = DEFAULT_DESTINATION_ROOT,
) -> V8CandidateBundle:
    """Create a no-clobber, content-addressed candidate from the reference."""

    source_root = Path(repo_root).expanduser().resolve()
    destination = Path(destination_root).expanduser().resolve()
    reference = verify_policy_bundle(
        reference_root,
        expected_package_sha256=expected_reference_package_sha256,
        expected_manifest_sha256=expected_reference_manifest_sha256,
    )
    reviewed = _reviewed_sources(source_root)
    reference_manifest = _load_manifest(reference)
    material = copy.deepcopy(reference_manifest)
    material.pop("package_sha256", None)
    files = dict(reference.files_sha256)
    for relative, record in reviewed.items():
        files[relative] = record["sha256"]
    material["files_sha256"] = dict(sorted(files.items()))
    navigation = material.get("navigation")
    if not isinstance(navigation, dict) or navigation.get("config") != HISTORICAL_CONFIG:
        raise ValueError("historical navigation metadata changed unexpectedly")
    navigation["controller_id"] = "parcel-directive-navigator-grid-v1-v8-all-ray"
    material["experiment_derivation"] = {
        "id": V8_DERIVATION_ID,
        "reference_manifest_sha256": reference.manifest_sha256,
        "reference_package_sha256": reference.package_sha256,
        "replacements": sorted(V8_REPLACEMENTS),
        "additions": sorted(V8_ADDITIONS),
        "reviewed_sources": reviewed,
        "all_other_file_bytes_identical_to_reference": True,
        "evaluator_or_adapter_source_changed": False,
        "experimental": True,
        "deployment_enabled": False,
    }
    package_sha256 = _sha256_bytes(_canonical_json(material))
    document = {**material, "package_sha256": package_sha256}
    manifest_payload = _canonical_json(document, pretty=True)
    manifest_sha256 = _sha256_bytes(manifest_payload)
    target = destination / f"parcel-v8-candidate-{package_sha256}"
    if target.exists():
        candidate = verify_policy_bundle(
            target,
            expected_package_sha256=package_sha256,
            expected_manifest_sha256=manifest_sha256,
        )
        delta = verify_v8_candidate_delta(candidate, reference, repo_root=source_root)
        return V8CandidateBundle(bundle=candidate, reference=reference, delta=delta)

    destination.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=".parcel-v8-candidate-", dir=destination))
    temporary = temporary_parent / "bundle"
    try:
        shutil.copytree(reference.root, temporary, symlinks=False)
        for relative, source_relative in sorted({**V8_REPLACEMENTS, **V8_ADDITIONS}.items()):
            output = temporary / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                output.chmod(0o644)
            shutil.copyfile(source_root / source_relative, output)
        manifest_path = temporary / "package-manifest.json"
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(manifest_payload)
        for candidate_path in temporary.rglob("*"):
            if candidate_path.is_file():
                candidate_path.chmod(0o444)
        try:
            os.rename(temporary, target)
        except FileExistsError as error:
            raise FileExistsError(f"v8 candidate bundle already exists: {target}") from error
    finally:
        if temporary_parent.exists():
            shutil.rmtree(temporary_parent)

    candidate = verify_policy_bundle(
        target,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
    )
    delta = verify_v8_candidate_delta(candidate, reference, repo_root=source_root)
    return V8CandidateBundle(bundle=candidate, reference=reference, delta=delta)


__all__ = [
    "DEFAULT_DESTINATION_ROOT",
    "V8_ADDITIONS",
    "V8_CONFIG_SOURCE",
    "V8_DERIVATION_ID",
    "V8_REPLACEMENTS",
    "V8CandidateBundle",
    "prepare_v8_candidate_bundle",
    "verify_v8_candidate_delta",
]
