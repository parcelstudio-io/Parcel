from __future__ import annotations

import difflib
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from evals.external.barn_policy_sidecar import HISTORICAL_CONFIG, PACKAGE_KIND
from evals.external.barn_v9_policy_bundle import (
    DEFAULT_REFERENCE_ROOT,
    GRID_NAVIGATOR_DESTINATION,
    PROTECTED_UNCHANGED_PATHS,
    REFERENCE_FILE_COUNT,
    TRACKER_DESTINATION,
    UNCHANGED_REFERENCE_FILE_COUNT,
    V8_PARENT_DERIVATION_ID,
    V8_REFERENCE_CONTROLLER_ID,
    V8_REFERENCE_GRID_NAVIGATOR_SHA256,
    V8_REFERENCE_MANIFEST_SHA256,
    V8_REFERENCE_PACKAGE_SHA256,
    V9_CONTROLLER_ID,
    V9_SOURCE_CONTRACT_ID,
    apply_constrained_grid_navigator_patch,
    plan_v9_candidate_bundle,
    prepare_v9_candidate_bundle,
    verify_v9_candidate_delta,
)

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_BASE_GRID = b'''"""Synthetic frozen V8 grid navigator."""\n\nfrom __future__ import annotations\n\n\nclass GridNavigator:\n    def __init__(self) -> None:\n        self.ready = True\n\n    def act(self) -> str:\n        return "legacy"\n'''
_CANDIDATE_GRID = b'''"""Synthetic frozen V8 grid navigator."""\n\nfrom __future__ import annotations\n\nfrom .experimental_sampled_predictive_tracker import SampledPredictiveTracker\n\n\nclass GridNavigator:\n    def __init__(self) -> None:\n        self.ready = True\n        self.sampled_predictive_tracker = SampledPredictiveTracker()\n\n    def act(self) -> str:\n        return "legacy"\n'''
_TRACKER = b'''"""Synthetic reviewed V9 tracker."""\n\n\nclass SampledPredictiveTracker:\n    """Fixture implementation used only to exercise bundle derivation."""\n'''


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(document: dict[str, Any], *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            document,
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _hook_patch(base: bytes = _BASE_GRID, candidate: bytes = _CANDIDATE_GRID) -> bytes:
    return "".join(
        difflib.unified_diff(
            base.decode().splitlines(keepends=True),
            candidate.decode().splitlines(keepends=True),
            fromfile=f"a/{GRID_NAVIGATOR_DESTINATION}",
            tofile=f"b/{GRID_NAVIGATOR_DESTINATION}",
        )
    ).encode()


@dataclass(frozen=True, slots=True)
class _ProtocolFixture:
    reference_root: Path
    experiment_root: Path
    destination_root: Path
    reference_package_sha256: str
    reference_manifest_sha256: str
    candidate_grid_sha256: str
    patch_sha256: str
    tracker_sha256: str

    def plan_kwargs(self) -> dict[str, object]:
        return {
            "experiment_root": self.experiment_root,
            "reference_root": self.reference_root,
            "expected_reference_package_sha256": self.reference_package_sha256,
            "expected_reference_manifest_sha256": self.reference_manifest_sha256,
        }


def _write_reference_bundle(root: Path, *, file_count: int) -> tuple[str, str]:
    payloads: dict[str, bytes] = {
        GRID_NAVIGATOR_DESTINATION: _BASE_GRID,
        HISTORICAL_CONFIG: b"synthetic frozen V8 navigation config\n",
        "evals/external/parcel_barn_adapter.py": b"synthetic frozen adapter\n",
        "src/parcel_robot/navigation/collision.py": b"synthetic frozen collision\n",
        "src/parcel_robot/navigation/experimental_all_ray_shield.py": (
            b"synthetic frozen all-ray shield\n"
        ),
        "src/parcel_robot/navigation/grid_planner.py": b"synthetic frozen planner\n",
        "src/parcel_robot/navigation/pipeline.py": b"synthetic frozen pipeline\n",
    }
    filler_count = file_count - len(payloads)
    if filler_count < 0:
        raise ValueError("fixture file count cannot omit required files")
    for index in range(filler_count):
        payloads[f"src/parcel_robot/fixture/reference_{index:03d}.py"] = (
            f"# frozen fixture payload {index}\n".encode()
        )

    files_sha256: dict[str, str] = {}
    for relative, payload in sorted(payloads.items()):
        output = root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        files_sha256[relative] = _sha256(payload)
    material: dict[str, Any] = {
        "schema_version": 1,
        "package_kind": PACKAGE_KIND,
        "navigation": {
            "adapter_id": "synthetic-frozen-v8-adapter",
            "config": HISTORICAL_CONFIG,
            "controller_id": V8_REFERENCE_CONTROLLER_ID,
            "production_source_modified_by_packaging": False,
        },
        "files_sha256": dict(sorted(files_sha256.items())),
        "experiment_derivation": {
            "id": V8_PARENT_DERIVATION_ID,
            "experimental": True,
            "deployment_enabled": False,
        },
    }
    package_sha256 = _sha256(_canonical(material))
    manifest_payload = _canonical({**material, "package_sha256": package_sha256}, pretty=True)
    manifest = root / "package-manifest.json"
    manifest.write_bytes(manifest_payload)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    return package_sha256, _sha256(manifest_payload)


def _write_experiment_sources(
    root: Path,
    *,
    reference_package_sha256: str,
    reference_manifest_sha256: str,
    patch: bytes = _hook_patch(),
    tracker: bytes = _TRACKER,
) -> None:
    root.mkdir(parents=True)
    (root / "grid_navigator.patch").write_bytes(patch)
    (root / "experimental_sampled_predictive_tracker.py").write_bytes(tracker)
    contract = {
        "schema_version": 1,
        "contract_id": V9_SOURCE_CONTRACT_ID,
        "reference_package_sha256": reference_package_sha256,
        "reference_manifest_sha256": reference_manifest_sha256,
        "reference_grid_navigator_sha256": _sha256(_BASE_GRID),
        "grid_navigator_patch_sha256": _sha256(patch),
        "candidate_grid_navigator_sha256": _sha256(_CANDIDATE_GRID),
        "tracker_source_sha256": _sha256(tracker),
    }
    (root / "PATCH_CONTRACT.json").write_bytes(_canonical(contract, pretty=True))


def _protocol_fixture(
    tmp_path: Path, *, file_count: int = REFERENCE_FILE_COUNT
) -> _ProtocolFixture:
    reference_root = tmp_path / "reference"
    experiment_root = tmp_path / "experiment"
    package_sha256, manifest_sha256 = _write_reference_bundle(
        reference_root,
        file_count=file_count,
    )
    patch = _hook_patch()
    _write_experiment_sources(
        experiment_root,
        reference_package_sha256=package_sha256,
        reference_manifest_sha256=manifest_sha256,
        patch=patch,
    )
    return _ProtocolFixture(
        reference_root=reference_root,
        experiment_root=experiment_root,
        destination_root=tmp_path / "published",
        reference_package_sha256=package_sha256,
        reference_manifest_sha256=manifest_sha256,
        candidate_grid_sha256=_sha256(_CANDIDATE_GRID),
        patch_sha256=_sha256(patch),
        tracker_sha256=_sha256(_TRACKER),
    )


def _change_digest(digest: str) -> str:
    replacement = "0" if digest[0] != "0" else "1"
    return replacement + digest[1:]


def test_v9_is_pinned_to_the_exact_rejected_v8_reference() -> None:
    assert V8_REFERENCE_PACKAGE_SHA256 == (
        "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
    )
    assert V8_REFERENCE_MANIFEST_SHA256 == (
        "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"
    )
    assert V8_REFERENCE_GRID_NAVIGATOR_SHA256 == (
        "90d05f9994c69d20fc1f05fd80771362b3cb54a01a034f35a138787ba5b44bcb"
    )
    assert DEFAULT_REFERENCE_ROOT.name == f"parcel-v8-candidate-{V8_REFERENCE_PACKAGE_SHA256}"


def test_plan_is_read_only_and_materialization_is_an_exact_one_factor_delta(
    tmp_path: Path,
) -> None:
    fixture = _protocol_fixture(tmp_path)

    plan = plan_v9_candidate_bundle(**fixture.plan_kwargs())

    assert not fixture.destination_root.exists()
    assert plan.patched_grid_navigator == _CANDIDATE_GRID
    assert plan.tracker_source == _TRACKER
    assert plan.source_contract.grid_navigator_patch_sha256 == fixture.patch_sha256
    assert plan.source_contract.candidate_grid_navigator_sha256 == (fixture.candidate_grid_sha256)
    assert plan.source_contract.tracker_source_sha256 == fixture.tracker_sha256

    built = prepare_v9_candidate_bundle(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )
    repeated = prepare_v9_candidate_bundle(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )

    assert repeated.root == built.root
    assert built.root.name == f"parcel-v9-candidate-{plan.package_sha256}"
    assert len(built.reference.files_sha256) == REFERENCE_FILE_COUNT
    assert len(built.bundle.files_sha256) == REFERENCE_FILE_COUNT + 1
    assert built.delta["replacements"] == [GRID_NAVIGATOR_DESTINATION]
    assert built.delta["additions"] == [TRACKER_DESTINATION]
    assert built.delta["unchanged_file_count"] == UNCHANGED_REFERENCE_FILE_COUNT
    assert built.delta["one_factor_tracker_subsystem_delta"] is True
    assert built.delta["experimental"] is True
    assert built.delta["deployment_enabled"] is False
    assert built.delta["reference_lineage"] == {
        "deployment_enabled": False,
        "experimental_control_only": True,
        "v8_development_gate_passed": False,
        "v8_reference_role_does_not_imply_promotion": True,
    }
    for flag in (
        "adapter_or_evaluator_source_changed",
        "navigation_config_changed",
        "grid_planner_changed",
        "pipeline_changed",
        "collision_logic_changed",
        "all_ray_safety_shield_changed",
    ):
        assert built.delta[flag] is False
    for relative, digest in built.reference.files_sha256.items():
        if relative == GRID_NAVIGATOR_DESTINATION:
            assert built.bundle.files_sha256[relative] == fixture.candidate_grid_sha256
        else:
            assert built.bundle.files_sha256[relative] == digest
    assert built.bundle.files_sha256[TRACKER_DESTINATION] == fixture.tracker_sha256
    for relative in PROTECTED_UNCHANGED_PATHS:
        assert built.bundle.files_sha256[relative] == built.reference.files_sha256[relative]

    manifest = json.loads(built.bundle.manifest_path.read_bytes())
    derivation = manifest["experiment_derivation"]
    assert manifest["navigation"]["controller_id"] == V9_CONTROLLER_ID
    assert manifest["navigation"]["config"] == HISTORICAL_CONFIG
    assert derivation["reference_file_count"] == REFERENCE_FILE_COUNT
    assert derivation["unchanged_reference_file_count"] == UNCHANGED_REFERENCE_FILE_COUNT
    assert derivation["source_contract"] == plan.source_contract.manifest_record()
    for path in (built.root, *built.root.rglob("*")):
        metadata = os.lstat(path)
        assert not stat.S_ISLNK(metadata.st_mode)
        assert metadata.st_mode & _WRITE_BITS == 0
        if stat.S_ISREG(metadata.st_mode):
            assert metadata.st_nlink == 1


def test_materialization_requires_the_explicit_frozen_candidate_identity(
    tmp_path: Path,
) -> None:
    fixture = _protocol_fixture(tmp_path)
    plan = plan_v9_candidate_bundle(**fixture.plan_kwargs())

    with pytest.raises(ValueError, match="computed V9 package digest"):
        prepare_v9_candidate_bundle(
            **fixture.plan_kwargs(),
            expected_candidate_package_sha256=_change_digest(plan.package_sha256),
            expected_candidate_manifest_sha256=plan.manifest_sha256,
            destination_root=fixture.destination_root,
        )
    assert not fixture.destination_root.exists()

    with pytest.raises(ValueError, match="all-zero placeholder"):
        prepare_v9_candidate_bundle(
            **fixture.plan_kwargs(),
            expected_candidate_package_sha256="0" * 64,
            expected_candidate_manifest_sha256=plan.manifest_sha256,
            destination_root=fixture.destination_root,
        )
    assert not fixture.destination_root.exists()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("grid_navigator_patch_sha256", "0" * 64),
        ("candidate_grid_navigator_sha256", "TBD"),
        ("tracker_source_sha256", "f" * 63),
    ],
)
def test_contract_rejects_placeholder_or_malformed_hashes(
    tmp_path: Path,
    field: str,
    invalid: str,
) -> None:
    fixture = _protocol_fixture(tmp_path)
    contract_path = fixture.experiment_root / "PATCH_CONTRACT.json"
    contract = json.loads(contract_path.read_bytes())
    contract[field] = invalid
    contract_path.write_bytes(_canonical(contract, pretty=True))

    with pytest.raises(ValueError, match="placeholder|digest"):
        plan_v9_candidate_bundle(**fixture.plan_kwargs())


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("grid_navigator.patch", "hook patch bytes"),
        ("experimental_sampled_predictive_tracker.py", "tracker source bytes"),
    ],
)
def test_plan_rejects_source_bytes_changed_after_contract_freeze(
    tmp_path: Path,
    filename: str,
    message: str,
) -> None:
    fixture = _protocol_fixture(tmp_path)
    source = fixture.experiment_root / filename
    source.write_bytes(source.read_bytes() + b"# post-review tampering\n")

    with pytest.raises(ValueError, match=message):
        plan_v9_candidate_bundle(**fixture.plan_kwargs())


def test_plan_rejects_an_incorrect_mechanically_derived_hash(tmp_path: Path) -> None:
    fixture = _protocol_fixture(tmp_path)
    contract_path = fixture.experiment_root / "PATCH_CONTRACT.json"
    contract = json.loads(contract_path.read_bytes())
    contract["candidate_grid_navigator_sha256"] = _change_digest(
        contract["candidate_grid_navigator_sha256"]
    )
    contract_path.write_bytes(_canonical(contract, pretty=True))

    with pytest.raises(ValueError, match="mechanically patched grid-navigator digest"):
        plan_v9_candidate_bundle(**fixture.plan_kwargs())


def test_hook_patch_applier_rejects_wrong_target_context_and_missing_import() -> None:
    valid = _hook_patch()
    assert apply_constrained_grid_navigator_patch(_BASE_GRID, valid) == _CANDIDATE_GRID

    wrong_target = valid.replace(
        f"a/{GRID_NAVIGATOR_DESTINATION}".encode(),
        b"a/src/parcel_robot/navigation/pipeline.py",
        1,
    )
    with pytest.raises(ValueError, match="target only the exact"):
        apply_constrained_grid_navigator_patch(_BASE_GRID, wrong_target)

    wrong_context = valid.replace(b" class GridNavigator:\n", b" class OtherNavigator:\n", 1)
    with pytest.raises(ValueError, match="context differs"):
        apply_constrained_grid_navigator_patch(_BASE_GRID, wrong_context)

    no_import_candidate = _BASE_GRID.replace(
        b"        self.ready = True\n",
        b"        self.ready = True\n        SampledPredictiveTracker()\n",
    )
    with pytest.raises(ValueError, match="exactly one frozen tracker import"):
        apply_constrained_grid_navigator_patch(
            _BASE_GRID,
            _hook_patch(candidate=no_import_candidate),
        )


def test_reference_must_have_exactly_117_immutable_payloads(tmp_path: Path) -> None:
    short_fixture = _protocol_fixture(tmp_path / "short", file_count=REFERENCE_FILE_COUNT - 1)
    with pytest.raises(ValueError, match="exactly 117"):
        plan_v9_candidate_bundle(**short_fixture.plan_kwargs())

    mutable_fixture = _protocol_fixture(tmp_path / "mutable")
    mutable = mutable_fixture.reference_root / "src/parcel_robot/navigation/grid_planner.py"
    mutable.chmod(0o644)
    with pytest.raises(ValueError, match="not immutable"):
        plan_v9_candidate_bundle(**mutable_fixture.plan_kwargs())


def test_existing_foreign_content_address_target_is_never_replaced(tmp_path: Path) -> None:
    fixture = _protocol_fixture(tmp_path)
    plan = plan_v9_candidate_bundle(**fixture.plan_kwargs())
    target = fixture.destination_root / f"parcel-v9-candidate-{plan.package_sha256}"
    target.mkdir(parents=True)
    sentinel = target / "foreign-content"
    sentinel.write_text("must survive\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest is missing"):
        prepare_v9_candidate_bundle(
            **fixture.plan_kwargs(),
            expected_candidate_package_sha256=plan.package_sha256,
            expected_candidate_manifest_sha256=plan.manifest_sha256,
            destination_root=fixture.destination_root,
        )

    assert sentinel.read_text(encoding="utf-8") == "must survive\n"


@pytest.mark.parametrize("protected", sorted(PROTECTED_UNCHANGED_PATHS))
def test_delta_verifier_rejects_each_protected_source_confound(
    tmp_path: Path,
    protected: str,
) -> None:
    fixture = _protocol_fixture(tmp_path)
    plan = plan_v9_candidate_bundle(**fixture.plan_kwargs())
    built = prepare_v9_candidate_bundle(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )
    forged_files = dict(built.bundle.files_sha256)
    forged_files[protected] = _change_digest(forged_files[protected])
    forged = type(built.bundle)(
        root=built.bundle.root,
        manifest_path=built.bundle.manifest_path,
        manifest_sha256=built.bundle.manifest_sha256,
        package_sha256=built.bundle.package_sha256,
        files_sha256=forged_files,
    )

    with pytest.raises(ValueError, match="outside grid_navigator.py"):
        verify_v9_candidate_delta(
            forged,
            built.reference,
            expected_source_contract=plan.source_contract.manifest_record(),
        )


def test_delta_verifier_rejects_extra_payload_membership(tmp_path: Path) -> None:
    fixture = _protocol_fixture(tmp_path)
    plan = plan_v9_candidate_bundle(**fixture.plan_kwargs())
    built = prepare_v9_candidate_bundle(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )
    forged_files = {
        **built.bundle.files_sha256,
        "src/parcel_robot/navigation/unreviewed_helper.py": "f" * 64,
    }
    forged = type(built.bundle)(
        root=built.bundle.root,
        manifest_path=built.bundle.manifest_path,
        manifest_sha256=built.bundle.manifest_sha256,
        package_sha256=built.bundle.package_sha256,
        files_sha256=forged_files,
    )

    with pytest.raises(ValueError, match="membership differs"):
        verify_v9_candidate_delta(
            forged,
            built.reference,
            expected_source_contract=plan.source_contract.manifest_record(),
        )
