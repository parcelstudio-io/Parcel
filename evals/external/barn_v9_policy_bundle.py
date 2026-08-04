"""Build the V9 sampled-predictive-tracker bundle from the frozen V8 arm.

V9 deliberately does not package Parcel's mutable working tree.  Its control
arm is the exact, content-addressed V8 all-ray bundle.  The treatment is one
reviewed tracker-subsystem delta:

* mechanically apply one constrained unified diff to ``grid_navigator.py``;
* add ``experimental_sampled_predictive_tracker.py``; and
* retain every other payload byte from the V8 reference.

The canonical reviewed sources are intentionally absent until implementation
review is complete.  :func:`plan_v9_candidate_bundle` is read-only and computes
the candidate identities.  Materialization additionally requires those two
identities as explicit arguments, so an unset protocol cannot accidentally
publish a canonical candidate.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .barn_policy_sidecar import HISTORICAL_CONFIG, VerifiedPolicyBundle, verify_policy_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION_ROOT = REPO_ROOT / ".cache/external-evals/runtime/barn-parcel-bundles"
DEFAULT_EXPERIMENT_ROOT = (
    REPO_ROOT / "evals/external/experiments/barn_sampled_predictive_tracker_v9"
)
DEFAULT_SOURCE_CONTRACT = DEFAULT_EXPERIMENT_ROOT / "PATCH_CONTRACT.json"
DEFAULT_PATCH_SOURCE = DEFAULT_EXPERIMENT_ROOT / "grid_navigator.patch"
DEFAULT_TRACKER_SOURCE = DEFAULT_EXPERIMENT_ROOT / "experimental_sampled_predictive_tracker.py"

V8_REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
V8_REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"
V8_REFERENCE_GRID_NAVIGATOR_SHA256 = (
    "90d05f9994c69d20fc1f05fd80771362b3cb54a01a034f35a138787ba5b44bcb"
)
DEFAULT_REFERENCE_ROOT = (
    DEFAULT_DESTINATION_ROOT / f"parcel-v8-candidate-{V8_REFERENCE_PACKAGE_SHA256}"
)

V8_PARENT_DERIVATION_ID = "parcel-v8-all-ray-candidate-from-historical-75f7ff4d-v1"
V8_REFERENCE_CONTROLLER_ID = "parcel-directive-navigator-grid-v1-v8-all-ray"
V9_DERIVATION_ID = "parcel-v9-sampled-predictive-tracker-from-v8-189ac31f-v1"
V9_CONTROLLER_ID = "parcel-directive-navigator-grid-v1-v9-sampled-predictive-tracker"
V9_SOURCE_CONTRACT_ID = "parcel-v9-sampled-predictive-tracker-source-contract-v1"

REFERENCE_FILE_COUNT = 117
UNCHANGED_REFERENCE_FILE_COUNT = 116
GRID_NAVIGATOR_DESTINATION = "src/parcel_robot/navigation/grid_navigator.py"
TRACKER_DESTINATION = "src/parcel_robot/navigation/experimental_sampled_predictive_tracker.py"
PATCH_FILENAME = "grid_navigator.patch"
TRACKER_SOURCE_FILENAME = "experimental_sampled_predictive_tracker.py"
SOURCE_CONTRACT_FILENAME = "PATCH_CONTRACT.json"
PATCH_SOURCE_ID = "experiment:barn_sampled_predictive_tracker_v9/grid_navigator.patch"
TRACKER_SOURCE_ID = (
    "experiment:barn_sampled_predictive_tracker_v9/experimental_sampled_predictive_tracker.py"
)
SOURCE_CONTRACT_ID = "experiment:barn_sampled_predictive_tracker_v9/PATCH_CONTRACT.json"

V9_REPLACEMENTS = frozenset({GRID_NAVIGATOR_DESTINATION})
V9_ADDITIONS = frozenset({TRACKER_DESTINATION})

PROTECTED_UNCHANGED_PATHS = frozenset(
    {
        HISTORICAL_CONFIG,
        "evals/external/parcel_barn_adapter.py",
        "src/parcel_robot/navigation/collision.py",
        "src/parcel_robot/navigation/experimental_all_ray_shield.py",
        "src/parcel_robot/navigation/grid_planner.py",
        "src/parcel_robot/navigation/pipeline.py",
    }
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_MAX_PATCH_BYTES = 256 * 1024
_MAX_PATCH_HUNKS = 16
_MAX_CHANGED_LINES = 256
_TRACKER_IMPORT = "from .experimental_sampled_predictive_tracker import SampledPredictiveTracker"
_CONTRACT_FIELDS = {
    "schema_version",
    "contract_id",
    "reference_package_sha256",
    "reference_manifest_sha256",
    "reference_grid_navigator_sha256",
    "grid_navigator_patch_sha256",
    "candidate_grid_navigator_sha256",
    "tracker_source_sha256",
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


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(path: Path) -> None:
    candidate = _lexical_absolute(path)
    for component in (candidate, *candidate.parents):
        if os.path.lexists(component) and component.is_symlink():
            raise ValueError(f"V9 path contains a symbolic-link component: {component}")


def _read_regular_source(path: Path, *, label: str) -> bytes:
    requested = _lexical_absolute(path)
    _reject_symlink_components(requested)
    if requested.is_symlink() or not requested.is_file():
        raise FileNotFoundError(f"{label} is missing or unsafe: {requested}")
    metadata = os.lstat(requested)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"{label} must be a uniquely linked regular file: {requested}")
    return requested.read_bytes()


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains a duplicate field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains a non-finite value: {value}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid strict JSON") from error
    if not isinstance(value, dict):
        raise TypeError(f"{label} must contain a JSON object")
    return value


def _required_sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest, not a placeholder")
    if value == "0" * 64:
        raise ValueError(f"{name} cannot use the all-zero placeholder digest")
    return value


@dataclass(frozen=True, slots=True)
class V9SourceContract:
    """Frozen identities for the two reviewed V9 source inputs."""

    reference_package_sha256: str
    reference_manifest_sha256: str
    reference_grid_navigator_sha256: str
    grid_navigator_patch_sha256: str
    candidate_grid_navigator_sha256: str
    tracker_source_sha256: str
    contract_sha256: str

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_reference_package_sha256: str,
        expected_reference_manifest_sha256: str,
    ) -> V9SourceContract:
        raw = _read_regular_source(path, label="V9 patch contract")
        value = _strict_json_object(raw, label="V9 patch contract")
        if set(value) != _CONTRACT_FIELDS:
            raise ValueError("V9 patch-contract field membership is not exact")
        if value.get("schema_version") != 1 or value.get("contract_id") != (V9_SOURCE_CONTRACT_ID):
            raise ValueError("V9 patch-contract identity is invalid")
        hashes = {
            name: _required_sha256(value.get(name), name=name)
            for name in _CONTRACT_FIELDS
            if name.endswith("_sha256")
        }
        if hashes["reference_package_sha256"] != expected_reference_package_sha256:
            raise ValueError("V9 patch contract names a different reference package")
        if hashes["reference_manifest_sha256"] != expected_reference_manifest_sha256:
            raise ValueError("V9 patch contract names a different reference manifest")
        if hashes["candidate_grid_navigator_sha256"] == hashes["reference_grid_navigator_sha256"]:
            raise ValueError("V9 patch contract does not change grid_navigator.py")
        return cls(**hashes, contract_sha256=_sha256_bytes(raw))

    @classmethod
    def from_manifest_record(cls, value: Mapping[str, Any]) -> V9SourceContract:
        expected = {
            "contract_id",
            "contract_sha256",
            "reference_package_sha256",
            "reference_manifest_sha256",
            "reference_grid_navigator_sha256",
            "grid_navigator_patch_sha256",
            "candidate_grid_navigator_sha256",
            "tracker_source_sha256",
        }
        if set(value) != expected or value.get("contract_id") != V9_SOURCE_CONTRACT_ID:
            raise ValueError("frozen V9 source-contract record is invalid")
        hashes = {
            name: _required_sha256(value.get(name), name=name)
            for name in expected
            if name.endswith("_sha256")
        }
        return cls(**hashes)

    def manifest_record(self) -> dict[str, Any]:
        return {
            "contract_id": V9_SOURCE_CONTRACT_ID,
            "contract_sha256": self.contract_sha256,
            "reference_package_sha256": self.reference_package_sha256,
            "reference_manifest_sha256": self.reference_manifest_sha256,
            "reference_grid_navigator_sha256": self.reference_grid_navigator_sha256,
            "grid_navigator_patch_sha256": self.grid_navigator_patch_sha256,
            "candidate_grid_navigator_sha256": self.candidate_grid_navigator_sha256,
            "tracker_source_sha256": self.tracker_source_sha256,
        }


def _load_manifest(bundle: VerifiedPolicyBundle) -> dict[str, Any]:
    value = _strict_json_object(bundle.manifest_path.read_bytes(), label="policy bundle manifest")
    return value


def _validate_v8_reference(reference: VerifiedPolicyBundle, contract: V9SourceContract) -> None:
    if len(reference.files_sha256) != REFERENCE_FILE_COUNT:
        raise ValueError(f"V9 reference must contain exactly {REFERENCE_FILE_COUNT} payload files")
    if contract.reference_package_sha256 != reference.package_sha256 or (
        contract.reference_manifest_sha256 != reference.manifest_sha256
    ):
        raise ValueError("V9 source contract is not bound to the verified V8 reference")
    required_reference_files = set(V9_REPLACEMENTS) | PROTECTED_UNCHANGED_PATHS
    if not required_reference_files <= set(reference.files_sha256):
        raise ValueError("V8 reference is missing a required V9 or protected payload")
    if V9_ADDITIONS & set(reference.files_sha256):
        raise ValueError("V9 tracker addition already exists in the V8 reference")
    if reference.files_sha256[GRID_NAVIGATOR_DESTINATION] != (
        contract.reference_grid_navigator_sha256
    ):
        raise ValueError("V8 reference grid_navigator.py differs from the source contract")
    if reference.package_sha256 == V8_REFERENCE_PACKAGE_SHA256 and (
        contract.reference_grid_navigator_sha256 != V8_REFERENCE_GRID_NAVIGATOR_SHA256
    ):
        raise ValueError("canonical V8 grid-navigator identity changed")

    manifest = _load_manifest(reference)
    navigation = manifest.get("navigation")
    derivation = manifest.get("experiment_derivation")
    if (
        not isinstance(navigation, dict)
        or navigation.get("config") != HISTORICAL_CONFIG
        or navigation.get("controller_id") != V8_REFERENCE_CONTROLLER_ID
    ):
        raise ValueError("V9 reference is not the exact V8 navigation profile")
    if (
        not isinstance(derivation, dict)
        or derivation.get("id") != V8_PARENT_DERIVATION_ID
        or derivation.get("experimental") is not True
        or derivation.get("deployment_enabled") is not False
    ):
        raise ValueError("V9 reference lost its rejected, deployment-disabled V8 lineage")

    for relative in reference.files_sha256:
        path = reference.root / relative
        metadata = os.lstat(path)
        if metadata.st_nlink != 1 or metadata.st_mode & _WRITE_BITS:
            raise ValueError(f"V8 reference payload is not immutable: {relative}")
    manifest_metadata = os.lstat(reference.manifest_path)
    if manifest_metadata.st_nlink != 1 or manifest_metadata.st_mode & _WRITE_BITS:
        raise ValueError("V8 reference manifest is not immutable")


def _parse_hunk_count(raw: str | None) -> int:
    return 1 if raw is None else int(raw)


def apply_constrained_grid_navigator_patch(base: bytes, patch: bytes) -> bytes:
    """Apply one small, exact unified diff to the sole allowed replacement."""

    if not base or len(patch) > _MAX_PATCH_BYTES:
        raise ValueError("V9 base source is empty or the hook patch is too large")
    try:
        base_text = base.decode("utf-8")
        patch_text = patch.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("V9 base and hook patch must be UTF-8") from error
    if "\x00" in patch_text or "\r" in patch_text:
        raise ValueError("V9 hook patch contains unsupported binary or CRLF content")
    if not base_text.endswith("\n") or not patch_text.endswith("\n"):
        raise ValueError("V9 base and hook patch must end with a newline")

    lines = patch_text.splitlines(keepends=True)
    expected_old = f"--- a/{GRID_NAVIGATOR_DESTINATION}\n"
    expected_new = f"+++ b/{GRID_NAVIGATOR_DESTINATION}\n"
    if len(lines) < 3 or lines[0] != expected_old or lines[1] != expected_new:
        raise ValueError("V9 hook patch must target only the exact grid_navigator.py path")
    if any(
        line.startswith(("diff ", "index ", "rename ", "new file", "deleted file"))
        for line in lines
    ):
        raise ValueError("V9 hook patch may not rename, add, or delete a payload file")

    base_lines = base_text.splitlines(keepends=True)
    output: list[str] = []
    base_cursor = 0
    patch_cursor = 2
    hunk_count = 0
    changed_lines = 0
    while patch_cursor < len(lines):
        header = lines[patch_cursor]
        if not header.endswith("\n"):
            raise ValueError("V9 hook patch contains an unterminated line")
        match = _HUNK_HEADER.fullmatch(header[:-1])
        if match is None:
            raise ValueError("V9 hook patch contains content outside a unified-diff hunk")
        hunk_count += 1
        if hunk_count > _MAX_PATCH_HUNKS:
            raise ValueError("V9 hook patch contains too many hunks")
        old_start = int(match.group(1))
        old_count = _parse_hunk_count(match.group(2))
        new_start = int(match.group(3))
        new_count = _parse_hunk_count(match.group(4))
        if old_start < 1 or new_start < 1 or old_start - 1 < base_cursor:
            raise ValueError("V9 hook patch hunks overlap or are out of order")
        output.extend(base_lines[base_cursor : old_start - 1])
        if len(output) != new_start - 1:
            raise ValueError("V9 hook patch new-file line coordinates are inconsistent")
        base_cursor = old_start - 1
        patch_cursor += 1
        consumed_old = 0
        produced_new = 0
        while patch_cursor < len(lines) and not lines[patch_cursor].startswith("@@ "):
            line = lines[patch_cursor]
            if not line.endswith("\n") or not line:
                raise ValueError("V9 hook patch contains an unterminated hunk line")
            prefix = line[0]
            payload = line[1:]
            if prefix == " ":
                if base_cursor >= len(base_lines) or base_lines[base_cursor] != payload:
                    raise ValueError("V9 hook patch context differs from the frozen V8 source")
                output.append(payload)
                base_cursor += 1
                consumed_old += 1
                produced_new += 1
            elif prefix == "-":
                if base_cursor >= len(base_lines) or base_lines[base_cursor] != payload:
                    raise ValueError("V9 hook patch deletion differs from the frozen V8 source")
                base_cursor += 1
                consumed_old += 1
                changed_lines += 1
            elif prefix == "+":
                output.append(payload)
                produced_new += 1
                changed_lines += 1
            else:
                raise ValueError("V9 hook patch uses an unsupported unified-diff directive")
            patch_cursor += 1
        if consumed_old != old_count or produced_new != new_count:
            raise ValueError("V9 hook patch hunk counts are inconsistent")

    if hunk_count == 0 or changed_lines == 0 or changed_lines > _MAX_CHANGED_LINES:
        raise ValueError("V9 hook patch must contain a small, non-empty reviewed change")
    output.extend(base_lines[base_cursor:])
    result = "".join(output)
    if base_text.count(_TRACKER_IMPORT) != 0 or result.count(_TRACKER_IMPORT) != 1:
        raise ValueError("V9 hook patch must add exactly one frozen tracker import")
    if result.count("SampledPredictiveTracker(") < 1:
        raise ValueError("V9 hook patch does not construct the sampled predictive tracker")
    return result.encode("utf-8")


def _reviewed_source_bytes(
    experiment_root: Path,
    contract: V9SourceContract,
    reference: VerifiedPolicyBundle,
) -> tuple[bytes, bytes]:
    root = _lexical_absolute(experiment_root)
    _reject_symlink_components(root)
    if root.is_symlink() or not root.is_dir():
        raise FileNotFoundError(f"V9 experiment source root is missing or unsafe: {root}")
    patch_path = root / PATCH_FILENAME
    tracker_path = root / TRACKER_SOURCE_FILENAME
    patch = _read_regular_source(patch_path, label="V9 grid-navigator hook patch")
    tracker = _read_regular_source(tracker_path, label="V9 sampled predictive tracker source")
    if _sha256_bytes(patch) != contract.grid_navigator_patch_sha256:
        raise ValueError("V9 hook patch bytes differ from the frozen source contract")
    if _sha256_bytes(tracker) != contract.tracker_source_sha256:
        raise ValueError("V9 tracker source bytes differ from the frozen source contract")
    try:
        tracker_text = tracker.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("V9 tracker source must be UTF-8") from error
    if not tracker_text.endswith("\n") or "class SampledPredictiveTracker" not in tracker_text:
        raise ValueError("V9 tracker source lacks its exact class identity or final newline")

    base = (reference.root / GRID_NAVIGATOR_DESTINATION).read_bytes()
    if _sha256_bytes(base) != contract.reference_grid_navigator_sha256:
        raise ValueError("V8 grid-navigator bytes changed after reference verification")
    patched = apply_constrained_grid_navigator_patch(base, patch)
    if _sha256_bytes(patched) != contract.candidate_grid_navigator_sha256:
        raise ValueError("mechanically patched grid-navigator digest differs from the contract")
    return patched, tracker


def _reviewed_sources_record(contract: V9SourceContract) -> dict[str, dict[str, Any]]:
    return {
        GRID_NAVIGATOR_DESTINATION: {
            "source_id": PATCH_SOURCE_ID,
            "source_kind": "constrained_unified_diff",
            "base_sha256": contract.reference_grid_navigator_sha256,
            "patch_sha256": contract.grid_navigator_patch_sha256,
            "sha256": contract.candidate_grid_navigator_sha256,
        },
        TRACKER_DESTINATION: {
            "source_id": TRACKER_SOURCE_ID,
            "source_kind": "reviewed_addition",
            "sha256": contract.tracker_source_sha256,
        },
    }


def _reference_lineage() -> dict[str, Any]:
    return {
        "deployment_enabled": False,
        "experimental_control_only": True,
        "v8_development_gate_passed": False,
        "v8_reference_role_does_not_imply_promotion": True,
    }


def _derivation_record(
    reference: VerifiedPolicyBundle,
    contract: V9SourceContract,
) -> dict[str, Any]:
    return {
        "id": V9_DERIVATION_ID,
        "reference_manifest_sha256": reference.manifest_sha256,
        "reference_package_sha256": reference.package_sha256,
        "replacements": sorted(V9_REPLACEMENTS),
        "additions": sorted(V9_ADDITIONS),
        "reviewed_sources": _reviewed_sources_record(contract),
        "source_contract": contract.manifest_record(),
        "reference_lineage": _reference_lineage(),
        "reference_file_count": REFERENCE_FILE_COUNT,
        "unchanged_reference_file_count": UNCHANGED_REFERENCE_FILE_COUNT,
        "all_other_file_bytes_identical_to_reference": True,
        "adapter_or_evaluator_source_changed": False,
        "navigation_config_changed": False,
        "grid_planner_changed": False,
        "pipeline_changed": False,
        "collision_logic_changed": False,
        "all_ray_safety_shield_changed": False,
        "one_factor_tracker_subsystem_delta": True,
        "experimental": True,
        "deployment_enabled": False,
    }


@dataclass(frozen=True, slots=True)
class V9CandidatePlan:
    """Read-only derivation result used to freeze candidate identities."""

    reference: VerifiedPolicyBundle
    source_contract: V9SourceContract
    patched_grid_navigator: bytes
    tracker_source: bytes
    package_sha256: str
    manifest_sha256: str
    manifest_payload: bytes
    delta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class V9CandidateBundle:
    """A verified V9 bundle and its exact V8-parent delta."""

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
            "derivation_id": V9_DERIVATION_ID,
            "reference_package_sha256": self.reference.package_sha256,
            "allowlisted_delta": copy.deepcopy(self.delta),
        }


def verify_v9_candidate_delta(
    candidate: VerifiedPolicyBundle,
    reference: VerifiedPolicyBundle,
    *,
    expected_source_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove that candidate payload differs only by the frozen tracker factor."""

    contract = V9SourceContract.from_manifest_record(expected_source_contract)
    _validate_v8_reference(reference, contract)
    if candidate.package_sha256 == reference.package_sha256:
        raise ValueError("V9 candidate must have a distinct package identity")
    reference_files = reference.files_sha256
    candidate_files = candidate.files_sha256
    expected_members = set(reference_files) | set(V9_ADDITIONS)
    if set(candidate_files) != expected_members:
        raise ValueError("V9 candidate payload membership differs outside the exact allowlist")
    changed = {
        relative
        for relative, digest in reference_files.items()
        if candidate_files[relative] != digest
    }
    if changed != set(V9_REPLACEMENTS):
        raise ValueError("V9 candidate changed a reference payload outside grid_navigator.py")
    if candidate_files[GRID_NAVIGATOR_DESTINATION] != (contract.candidate_grid_navigator_sha256):
        raise ValueError("V9 candidate grid-navigator digest differs from the frozen result")
    if candidate_files[TRACKER_DESTINATION] != contract.tracker_source_sha256:
        raise ValueError("V9 candidate tracker digest differs from the frozen source")
    if len(reference_files) - len(V9_REPLACEMENTS) != UNCHANGED_REFERENCE_FILE_COUNT:
        raise ValueError("V9 unchanged-reference member count is not exactly 116")
    for protected in PROTECTED_UNCHANGED_PATHS:
        if candidate_files[protected] != reference_files[protected]:
            raise ValueError(f"V9 candidate changed protected payload: {protected}")
    for relative in reference_files:
        if relative.startswith(("evals/", "configs/", "models/")) and (
            candidate_files[relative] != reference_files[relative]
        ):
            raise ValueError(
                f"V9 candidate changed evaluator, config, or model payload: {relative}"
            )

    manifest = _load_manifest(candidate)
    navigation = manifest.get("navigation")
    if (
        not isinstance(navigation, dict)
        or navigation.get("config") != HISTORICAL_CONFIG
        or navigation.get("controller_id") != V9_CONTROLLER_ID
    ):
        raise ValueError("V9 candidate navigation identity is invalid")
    expected_derivation = _derivation_record(reference, contract)
    if manifest.get("experiment_derivation") != expected_derivation:
        raise ValueError("V9 candidate derivation record is not exact")
    return {
        "replacements": sorted(V9_REPLACEMENTS),
        "additions": sorted(V9_ADDITIONS),
        "reference_file_count": REFERENCE_FILE_COUNT,
        "unchanged_file_count": UNCHANGED_REFERENCE_FILE_COUNT,
        "reviewed_sources": _reviewed_sources_record(contract),
        "source_contract": contract.manifest_record(),
        "reference_lineage": _reference_lineage(),
        "all_other_file_bytes_identical_to_reference": True,
        "adapter_or_evaluator_source_changed": False,
        "navigation_config_changed": False,
        "grid_planner_changed": False,
        "pipeline_changed": False,
        "collision_logic_changed": False,
        "all_ray_safety_shield_changed": False,
        "one_factor_tracker_subsystem_delta": True,
        "experimental": True,
        "deployment_enabled": False,
    }


def plan_v9_candidate_bundle(
    *,
    experiment_root: str | Path = DEFAULT_EXPERIMENT_ROOT,
    reference_root: str | Path = DEFAULT_REFERENCE_ROOT,
    expected_reference_package_sha256: str = V8_REFERENCE_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = V8_REFERENCE_MANIFEST_SHA256,
) -> V9CandidatePlan:
    """Compute identities and bytes without creating a candidate directory."""

    expected_package = _required_sha256(
        expected_reference_package_sha256,
        name="expected_reference_package_sha256",
    )
    expected_manifest = _required_sha256(
        expected_reference_manifest_sha256,
        name="expected_reference_manifest_sha256",
    )
    source_root = _lexical_absolute(experiment_root)
    contract_path = source_root / SOURCE_CONTRACT_FILENAME
    contract = V9SourceContract.load(
        contract_path,
        expected_reference_package_sha256=expected_package,
        expected_reference_manifest_sha256=expected_manifest,
    )
    reference = verify_policy_bundle(
        reference_root,
        expected_package_sha256=expected_package,
        expected_manifest_sha256=expected_manifest,
    )
    _validate_v8_reference(reference, contract)
    patched, tracker = _reviewed_source_bytes(source_root, contract, reference)

    reference_manifest = _load_manifest(reference)
    material = copy.deepcopy(reference_manifest)
    material.pop("package_sha256", None)
    files = dict(reference.files_sha256)
    files[GRID_NAVIGATOR_DESTINATION] = contract.candidate_grid_navigator_sha256
    files[TRACKER_DESTINATION] = contract.tracker_source_sha256
    material["files_sha256"] = dict(sorted(files.items()))
    navigation = material.get("navigation")
    if not isinstance(navigation, dict):
        raise TypeError("V8 reference navigation metadata is malformed")
    navigation["controller_id"] = V9_CONTROLLER_ID
    material["experiment_derivation"] = _derivation_record(reference, contract)
    package_sha256 = _sha256_bytes(_canonical_json(material))
    document = {**material, "package_sha256": package_sha256}
    manifest_payload = _canonical_json(document, pretty=True)
    manifest_sha256 = _sha256_bytes(manifest_payload)
    delta = {
        "replacements": sorted(V9_REPLACEMENTS),
        "additions": sorted(V9_ADDITIONS),
        "reference_file_count": REFERENCE_FILE_COUNT,
        "unchanged_file_count": UNCHANGED_REFERENCE_FILE_COUNT,
        "reviewed_sources": _reviewed_sources_record(contract),
        "source_contract": contract.manifest_record(),
        "reference_lineage": _reference_lineage(),
        "all_other_file_bytes_identical_to_reference": True,
        "adapter_or_evaluator_source_changed": False,
        "navigation_config_changed": False,
        "grid_planner_changed": False,
        "pipeline_changed": False,
        "collision_logic_changed": False,
        "all_ray_safety_shield_changed": False,
        "one_factor_tracker_subsystem_delta": True,
        "experimental": True,
        "deployment_enabled": False,
    }
    return V9CandidatePlan(
        reference=reference,
        source_contract=contract,
        patched_grid_navigator=patched,
        tracker_source=tracker,
        package_sha256=package_sha256,
        manifest_sha256=manifest_sha256,
        manifest_payload=manifest_payload,
        delta=delta,
    )


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


def _assert_candidate_read_only(
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
            raise ValueError(f"V9 candidate output is writable or aliased: {path}")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise ValueError(f"V9 candidate output contains a hard-linked file: {path}")


def prepare_v9_candidate_bundle(
    *,
    expected_candidate_package_sha256: str,
    expected_candidate_manifest_sha256: str,
    experiment_root: str | Path = DEFAULT_EXPERIMENT_ROOT,
    reference_root: str | Path = DEFAULT_REFERENCE_ROOT,
    expected_reference_package_sha256: str = V8_REFERENCE_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = V8_REFERENCE_MANIFEST_SHA256,
    destination_root: str | Path = DEFAULT_DESTINATION_ROOT,
) -> V9CandidateBundle:
    """Publish a no-clobber bundle only after both candidate hashes are frozen."""

    expected_candidate_package = _required_sha256(
        expected_candidate_package_sha256,
        name="expected_candidate_package_sha256",
    )
    expected_candidate_manifest = _required_sha256(
        expected_candidate_manifest_sha256,
        name="expected_candidate_manifest_sha256",
    )
    plan = plan_v9_candidate_bundle(
        experiment_root=experiment_root,
        reference_root=reference_root,
        expected_reference_package_sha256=expected_reference_package_sha256,
        expected_reference_manifest_sha256=expected_reference_manifest_sha256,
    )
    if plan.package_sha256 != expected_candidate_package:
        raise ValueError("computed V9 package digest differs from the frozen protocol identity")
    if plan.manifest_sha256 != expected_candidate_manifest:
        raise ValueError("computed V9 manifest digest differs from the frozen protocol identity")

    reverified_reference = verify_policy_bundle(
        plan.reference.root,
        expected_package_sha256=plan.reference.package_sha256,
        expected_manifest_sha256=plan.reference.manifest_sha256,
    )
    _validate_v8_reference(reverified_reference, plan.source_contract)
    if reverified_reference.files_sha256 != plan.reference.files_sha256:
        raise ValueError("V8 reference identity changed after the read-only V9 plan")

    destination = _lexical_absolute(destination_root)
    _reject_symlink_components(destination)
    if os.path.lexists(destination) and (destination.is_symlink() or not destination.is_dir()):
        raise ValueError("V9 destination root exists but is not a safe directory")
    target = destination / f"parcel-v9-candidate-{plan.package_sha256}"
    if os.path.lexists(target):
        candidate = verify_policy_bundle(
            target,
            expected_package_sha256=plan.package_sha256,
            expected_manifest_sha256=plan.manifest_sha256,
        )
        _assert_candidate_read_only(candidate)
        delta = verify_v9_candidate_delta(
            candidate,
            plan.reference,
            expected_source_contract=plan.source_contract.manifest_record(),
        )
        return V9CandidateBundle(candidate, plan.reference, delta)

    destination.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=".parcel-v9-candidate-", dir=destination))
    temporary = temporary_parent / "bundle"
    try:
        shutil.copytree(plan.reference.root, temporary, symlinks=False)
        grid_output = temporary / GRID_NAVIGATOR_DESTINATION
        grid_output.chmod(0o644)
        grid_output.write_bytes(plan.patched_grid_navigator)
        tracker_output = temporary / TRACKER_DESTINATION
        tracker_output.parent.mkdir(parents=True, exist_ok=True)
        tracker_output.write_bytes(plan.tracker_source)
        manifest_output = temporary / "package-manifest.json"
        manifest_output.chmod(0o644)
        manifest_output.write_bytes(plan.manifest_payload)
        _make_tree_read_only(temporary)
        # Some filesystems refuse to rename a mode-0555 source directory.  The
        # private 0700 staging parent keeps this root inaccessible while the
        # payload and all descendant directories remain read-only.
        temporary.chmod(0o700)
        staged = verify_policy_bundle(
            temporary,
            expected_package_sha256=plan.package_sha256,
            expected_manifest_sha256=plan.manifest_sha256,
        )
        _assert_candidate_read_only(staged, allow_private_staging_root=True)
        staged_delta = verify_v9_candidate_delta(
            staged,
            plan.reference,
            expected_source_contract=plan.source_contract.manifest_record(),
        )
        if staged_delta != plan.delta:
            raise ValueError("staged V9 candidate delta differs from the read-only plan")
        try:
            os.rename(temporary, target)
        except OSError as error:
            if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise FileExistsError(
                    f"refusing to replace an existing V9 candidate: {target}"
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
    _assert_candidate_read_only(candidate)
    delta = verify_v9_candidate_delta(
        candidate,
        plan.reference,
        expected_source_contract=plan.source_contract.manifest_record(),
    )
    if delta != plan.delta:
        raise ValueError("materialized V9 candidate delta differs from the read-only plan")
    return V9CandidateBundle(candidate, plan.reference, delta)


__all__ = [
    "DEFAULT_DESTINATION_ROOT",
    "DEFAULT_EXPERIMENT_ROOT",
    "DEFAULT_PATCH_SOURCE",
    "DEFAULT_REFERENCE_ROOT",
    "DEFAULT_SOURCE_CONTRACT",
    "DEFAULT_TRACKER_SOURCE",
    "GRID_NAVIGATOR_DESTINATION",
    "PROTECTED_UNCHANGED_PATHS",
    "REFERENCE_FILE_COUNT",
    "TRACKER_DESTINATION",
    "UNCHANGED_REFERENCE_FILE_COUNT",
    "V8_REFERENCE_GRID_NAVIGATOR_SHA256",
    "V8_REFERENCE_MANIFEST_SHA256",
    "V8_REFERENCE_PACKAGE_SHA256",
    "V9_ADDITIONS",
    "V9_DERIVATION_ID",
    "V9_REPLACEMENTS",
    "V9CandidateBundle",
    "V9CandidatePlan",
    "V9SourceContract",
    "apply_constrained_grid_navigator_patch",
    "plan_v9_candidate_bundle",
    "prepare_v9_candidate_bundle",
    "verify_v9_candidate_delta",
]
