from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from evals.external.barn_policy_sidecar import HISTORICAL_CONFIG, PACKAGE_KIND
from evals.external.barn_profile_candidate_bundle import (
    REFERENCE_FILE_COUNT,
    V8_PARENT_DERIVATION_ID,
    V8_REFERENCE_CONTROLLER_ID,
    PlannerProfileSpec,
    plan_planner_profile_candidate,
    prepare_planner_profile_candidate,
)

_DESTINATION = "configs/navigation/models/grid.yaml"
_BASE_PROFILE = b"""id: grid_v1
type: grid
version: "1.0.0"
description: Synthetic grid model.
checkpoint: ""
device: cpu
controller:
  cruise_vx: 0.60
  map_safety_margin_m: 0.10
  recovery_reverse_steps: 0
rl:
  enabled: false
"""
_CANDIDATE_PROFILE = b"""id: grid_v1
type: grid
version: "1.0.0"
description: Synthetic grid model.
checkpoint: ""
device: cpu
controller:
  cruise_vx: 0.60
  map_safety_margin_m: 0.10
  recovery_reverse_steps: 0
  comfort_cost_weight: 8.0
  frontier_band_m: 0.60
  frontier_min_progress_m: 0.10
  frontier_search_mode: observed_first
  map_comfort_safety_margin_m: 0.48
  reachable_frontier_fallback: true
rl:
  enabled: false
"""
_EXPERIMENT_CONFIG = b"""deployment_enabled: false
active_model: grid_v1
models_root: configs/navigation/models
pois_path: configs/navigation/cities/demo_pois.yaml
"""
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


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


def _spec() -> PlannerProfileSpec:
    return PlannerProfileSpec(
        derivation_id="fixture-planner-profile-v1",
        candidate_label="fixture-frontier-comfort-grid-v1",
        source_id="experiment:fixture/grid.yaml",
        replacement_destination=_DESTINATION,
        active_model="grid_v1",
        retained_controller_values=(("map_safety_margin_m", 0.10),),
        added_controller_values=(
            ("comfort_cost_weight", 8.0),
            ("frontier_band_m", 0.60),
            ("frontier_min_progress_m", 0.10),
            ("frontier_search_mode", "observed_first"),
            ("map_comfort_safety_margin_m", 0.48),
            ("reachable_frontier_fallback", True),
        ),
    )


@dataclass(frozen=True, slots=True)
class _Fixture:
    reference_root: Path
    source_path: Path
    destination_root: Path
    package_sha256: str
    manifest_sha256: str

    def plan_kwargs(self) -> dict[str, object]:
        return {
            "spec": _spec(),
            "profile_source_path": self.source_path,
            "reference_root": self.reference_root,
            "expected_reference_package_sha256": self.package_sha256,
            "expected_reference_manifest_sha256": self.manifest_sha256,
        }


def _write_reference_bundle(
    root: Path,
    *,
    experiment_config: bytes = _EXPERIMENT_CONFIG,
) -> tuple[str, str]:
    payloads: dict[str, bytes] = {
        _DESTINATION: _BASE_PROFILE,
        "configs/navigation/cities/demo_pois.yaml": b"pois: []\n",
        "configs/navigation/models/stub.yaml": b"id: stub_v0\ntype: stub\n",
        HISTORICAL_CONFIG: experiment_config,
        "evals/external/parcel_barn_adapter.py": b"# frozen adapter\n",
        "src/parcel_robot/navigation/collision.py": b"# frozen collision\n",
        "src/parcel_robot/navigation/experimental_all_ray_shield.py": b"# frozen shield\n",
        "src/parcel_robot/navigation/grid_navigator.py": b"# frozen navigator\n",
        "src/parcel_robot/navigation/grid_planner.py": b"# frozen planner\n",
        "src/parcel_robot/navigation/pipeline.py": b"# frozen pipeline\n",
    }
    for index in range(REFERENCE_FILE_COUNT - len(payloads)):
        payloads[f"src/parcel_robot/fixture/reference_{index:03d}.py"] = (
            f"# frozen fixture payload {index}\n".encode()
        )
    files_sha256: dict[str, str] = {}
    for relative, payload in sorted(payloads.items()):
        output = root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        output.chmod(0o444)
        files_sha256[relative] = _sha256(payload)
    material: dict[str, Any] = {
        "schema_version": 1,
        "package_kind": PACKAGE_KIND,
        "navigation": {
            "adapter_id": "synthetic-v8-adapter",
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
    manifest.chmod(0o444)
    return package_sha256, _sha256(manifest_payload)


def _fixture(tmp_path: Path, *, source: bytes = _CANDIDATE_PROFILE) -> _Fixture:
    reference_root = tmp_path / "reference"
    package_sha256, manifest_sha256 = _write_reference_bundle(reference_root)
    source_path = tmp_path / "experiment" / "grid.yaml"
    source_path.parent.mkdir()
    source_path.write_bytes(source)
    return _Fixture(
        reference_root=reference_root,
        source_path=source_path,
        destination_root=tmp_path / "published",
        package_sha256=package_sha256,
        manifest_sha256=manifest_sha256,
    )


def _change_digest(value: str) -> str:
    return ("0" if value[0] != "0" else "1") + value[1:]


def test_read_only_plan_and_identity_gated_materialization_are_exact_one_file_delta(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    plan = plan_planner_profile_candidate(**fixture.plan_kwargs())

    assert not fixture.destination_root.exists()
    assert plan.profile_source == _CANDIDATE_PROFILE
    assert plan.delta["replacements"] == [_DESTINATION]
    assert plan.delta["additions"] == []
    assert plan.delta["unchanged_reference_file_count"] == REFERENCE_FILE_COUNT - 1
    assert plan.delta["one_factor_planner_profile_delta"] is True
    assert plan.delta["experiment_config_changed"] is False
    assert plan.delta["navigator_source_changed"] is False
    assert plan.delta["grid_planner_source_changed"] is False
    assert plan.delta["all_ray_safety_shield_changed"] is False
    assert plan.delta["adapter_or_evaluator_source_changed"] is False
    assert plan.delta["training_only"] is True
    assert plan.delta["development_execution_authorized"] is False
    assert plan.delta["holdout_execution_authorized"] is False
    assert plan.delta["external_identity_freeze_required_before_real_materialization"] is True
    manifest = json.loads(plan.manifest_payload)
    reference_manifest = json.loads(plan.reference.manifest_path.read_bytes())
    assert manifest["navigation"] == reference_manifest["navigation"]
    assert manifest["navigation"]["config"] == HISTORICAL_CONFIG
    changed = {
        relative
        for relative, digest in plan.reference.files_sha256.items()
        if manifest["files_sha256"][relative] != digest
    }
    assert changed == {_DESTINATION}

    built = prepare_planner_profile_candidate(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )
    repeated = prepare_planner_profile_candidate(
        **fixture.plan_kwargs(),
        expected_candidate_package_sha256=plan.package_sha256,
        expected_candidate_manifest_sha256=plan.manifest_sha256,
        destination_root=fixture.destination_root,
    )

    assert repeated.root == built.root
    assert built.root.name == f"parcel-profile-candidate-{plan.package_sha256}"
    assert built.delta == plan.delta
    assert len(built.bundle.files_sha256) == REFERENCE_FILE_COUNT
    for relative, digest in built.reference.files_sha256.items():
        expected = plan.profile_sha256 if relative == _DESTINATION else digest
        assert built.bundle.files_sha256[relative] == expected
    for path in (built.root, *built.root.rglob("*")):
        metadata = os.lstat(path)
        assert not stat.S_ISLNK(metadata.st_mode)
        assert metadata.st_mode & _WRITE_BITS == 0
        if stat.S_ISREG(metadata.st_mode):
            assert metadata.st_nlink == 1


def test_wrong_identity_and_existing_target_are_refused_without_clobber(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    plan = plan_planner_profile_candidate(**fixture.plan_kwargs())

    with pytest.raises(ValueError, match="package digest differs"):
        prepare_planner_profile_candidate(
            **fixture.plan_kwargs(),
            expected_candidate_package_sha256=_change_digest(plan.package_sha256),
            expected_candidate_manifest_sha256=plan.manifest_sha256,
            destination_root=fixture.destination_root,
        )
    assert not fixture.destination_root.exists()

    fixture.destination_root.mkdir()
    target = fixture.destination_root / f"parcel-profile-candidate-{plan.package_sha256}"
    target.mkdir()
    marker = target / "owner-data.txt"
    marker.write_text("do not replace\n")
    with pytest.raises(ValueError, match="manifest is missing"):
        prepare_planner_profile_candidate(
            **fixture.plan_kwargs(),
            expected_candidate_package_sha256=plan.package_sha256,
            expected_candidate_manifest_sha256=plan.manifest_sha256,
            destination_root=fixture.destination_root,
        )
    assert marker.read_text() == "do not replace\n"


@pytest.mark.parametrize(
    "changed, message",
    [
        (
            _CANDIDATE_PROFILE.replace(b"cruise_vx: 0.60", b"cruise_vx: 0.59"),
            "hidden semantic change",
        ),
        (
            _CANDIDATE_PROFILE.replace(
                b"  comfort_cost_weight: 8.0\n",
                b"  comfort_cost_weight: 8.0\n  comfort_cost_weight: 8.0\n",
            ),
            "duplicate mapping key",
        ),
        (
            _CANDIDATE_PROFILE.replace(b"id: grid_v1", b"id: another_model"),
            "hidden semantic change",
        ),
    ],
)
def test_hidden_profile_changes_are_rejected(
    tmp_path: Path,
    changed: bytes,
    message: str,
) -> None:
    fixture = _fixture(tmp_path, source=changed)

    with pytest.raises(ValueError, match=message):
        plan_planner_profile_candidate(**fixture.plan_kwargs())


def test_active_model_must_still_resolve_uniquely_to_replaced_grid_yaml(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    experiment = fixture.reference_root / HISTORICAL_CONFIG
    experiment.chmod(0o644)
    experiment.write_bytes(_EXPERIMENT_CONFIG.replace(b"grid_v1", b"stub_v0"))
    experiment.chmod(0o444)
    package_sha256, manifest_sha256 = _rewrite_manifested_payload(
        fixture.reference_root,
        HISTORICAL_CONFIG,
    )

    with pytest.raises(ValueError, match="active_model differs"):
        plan_planner_profile_candidate(
            spec=_spec(),
            profile_source_path=fixture.source_path,
            reference_root=fixture.reference_root,
            expected_reference_package_sha256=package_sha256,
            expected_reference_manifest_sha256=manifest_sha256,
        )


def _rewrite_manifested_payload(root: Path, relative: str) -> tuple[str, str]:
    """Re-address a synthetic reference after one intentional fixture mutation."""

    manifest_path = root / "package-manifest.json"
    manifest_path.chmod(0o644)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files_sha256"][relative] = _sha256((root / relative).read_bytes())
    manifest.pop("package_sha256")
    package_sha256 = _sha256(_canonical(manifest))
    payload = _canonical({**manifest, "package_sha256": package_sha256}, pretty=True)
    manifest_path.write_bytes(payload)
    manifest_path.chmod(0o444)
    return package_sha256, _sha256(payload)


def test_profile_declaration_pairs_must_be_sorted_and_disjoint() -> None:
    with pytest.raises(ValueError, match="unique, sorted"):
        PlannerProfileSpec(
            derivation_id="fixture-v1",
            candidate_label="fixture-v1",
            source_id="experiment:fixture/grid.yaml",
            replacement_destination=_DESTINATION,
            active_model="grid_v1",
            retained_controller_values=(),
            added_controller_values=(("z", 1), ("a", 2)),
        )
    with pytest.raises(ValueError, match="disjoint"):
        PlannerProfileSpec(
            derivation_id="fixture-v1",
            candidate_label="fixture-v1",
            source_id="experiment:fixture/grid.yaml",
            replacement_destination=_DESTINATION,
            active_model="grid_v1",
            retained_controller_values=(("field", 1),),
            added_controller_values=(("field", 1),),
        )


def test_fixture_yaml_is_the_declared_profile() -> None:
    candidate = yaml.safe_load(_CANDIDATE_PROFILE)
    assert candidate["id"] == "grid_v1"
    assert candidate["controller"]["map_safety_margin_m"] == pytest.approx(0.10)
    assert candidate["controller"]["map_comfort_safety_margin_m"] == pytest.approx(0.48)
    assert candidate["controller"]["comfort_cost_weight"] == pytest.approx(8.0)
    assert candidate["controller"]["reachable_frontier_fallback"] is True
    assert candidate["controller"]["frontier_search_mode"] == "observed_first"
