from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from evals.external.barn_native import BarnObservation
from evals.external.barn_policy_sidecar import (
    HISTORICAL_BUNDLE,
    HISTORICAL_CONFIG,
    verify_policy_bundle,
)
from evals.external.barn_policy_specs import (
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_policy_pair,
)
from evals.external.barn_v8_policy_bundle import (
    V8_ADDITIONS,
    V8_CONFIG_SOURCE,
    V8_REPLACEMENTS,
    prepare_v8_candidate_bundle,
    verify_v8_candidate_delta,
)


def _canonical(document: dict[str, object]) -> bytes:
    return (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _reference_bundle(root: Path) -> tuple[str, str]:
    files = {
        "configs/navigation/experiments/barn_grid_v1.yaml": "reference config\n",
        "src/parcel_robot/navigation/collision.py": "reference collision\n",
        "src/parcel_robot/navigation/pipeline.py": "reference pipeline\n",
        "evals/external/barn_ros2_node.py": "reference node\n",
        "evals/external/parcel_barn_adapter.py": "reference adapter\n",
        "overlay/BARN_runner.launch.py": "reference hook\n",
    }
    hashes: dict[str, str] = {}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    material: dict[str, object] = {
        "schema_version": 1,
        "package_kind": "barn-ros2-parcel-submission-hook-bundle-v1",
        "navigation": {
            "config": "configs/navigation/experiments/barn_grid_v1.yaml",
            "controller_id": "historical",
        },
        "files_sha256": hashes,
    }
    package_sha256 = hashlib.sha256(_canonical(material)).hexdigest()
    document = {**material, "package_sha256": package_sha256}
    manifest = root / "package-manifest.json"
    manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return package_sha256, hashlib.sha256(manifest.read_bytes()).hexdigest()


def _reviewed_repo(root: Path) -> None:
    contents = {
        V8_CONFIG_SOURCE.as_posix(): "v8 config\n",
        "src/parcel_robot/navigation/collision.py": "v8 collision\n",
        "src/parcel_robot/navigation/pipeline.py": "v8 pipeline\n",
        "src/parcel_robot/navigation/experimental_all_ray_shield.py": "v8 shield\n",
        # This deliberately differs from the historical byte, but is outside
        # the exact allowlist and therefore must never enter the candidate.
        "evals/external/barn_ros2_node.py": "unrelated current node\n",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_v8_candidate_is_an_exact_allowlisted_historical_delta(tmp_path: Path) -> None:
    reference_root = tmp_path / "reference"
    source_root = tmp_path / "repo"
    destination = tmp_path / "bundles"
    package_sha256, manifest_sha256 = _reference_bundle(reference_root)
    _reviewed_repo(source_root)

    first = prepare_v8_candidate_bundle(
        repo_root=source_root,
        reference_root=reference_root,
        expected_reference_package_sha256=package_sha256,
        expected_reference_manifest_sha256=manifest_sha256,
        destination_root=destination,
    )
    second = prepare_v8_candidate_bundle(
        repo_root=source_root,
        reference_root=reference_root,
        expected_reference_package_sha256=package_sha256,
        expected_reference_manifest_sha256=manifest_sha256,
        destination_root=destination,
    )

    assert second.package_sha256 == first.package_sha256
    assert second.manifest_sha256 == first.manifest_sha256
    assert set(first.delta["replacements"]) == set(V8_REPLACEMENTS)
    assert set(first.delta["additions"]) == set(V8_ADDITIONS)
    assert first.root.name.endswith(first.package_sha256)
    assert first.report_metadata()["allowlisted_delta"]["deployment_enabled"] is False
    assert (first.root / "evals/external/barn_ros2_node.py").read_text() == "reference node\n"
    assert (first.root / "evals/external/parcel_barn_adapter.py").read_text() == (
        "reference adapter\n"
    )
    assert (first.root / "configs/navigation/experiments/barn_grid_v1.yaml").read_text() == (
        "v8 config\n"
    )
    assert (first.root / "src/parcel_robot/navigation/experimental_all_ray_shield.py").is_file()


def test_v8_delta_verifier_rejects_nonallowlisted_tampering(tmp_path: Path) -> None:
    reference_root = tmp_path / "reference"
    source_root = tmp_path / "repo"
    destination = tmp_path / "bundles"
    package_sha256, manifest_sha256 = _reference_bundle(reference_root)
    _reviewed_repo(source_root)
    built = prepare_v8_candidate_bundle(
        repo_root=source_root,
        reference_root=reference_root,
        expected_reference_package_sha256=package_sha256,
        expected_reference_manifest_sha256=manifest_sha256,
        destination_root=destination,
    )
    reference = verify_policy_bundle(
        reference_root,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
    )
    candidate = built.bundle
    forged_files = dict(candidate.files_sha256)
    forged_files["evals/external/barn_ros2_node.py"] = "0" * 64
    forged = type(candidate)(
        root=candidate.root,
        manifest_path=candidate.manifest_path,
        manifest_sha256=candidate.manifest_sha256,
        package_sha256=candidate.package_sha256,
        files_sha256=forged_files,
    )

    with pytest.raises(ValueError, match="outside the exact replacement set"):
        verify_v8_candidate_delta(forged, reference, repo_root=source_root)


@pytest.mark.skipif(not HISTORICAL_BUNDLE.is_dir(), reason="historical bundle cache is absent")
def test_real_historical_bundle_derives_only_the_reviewed_v8_delta(tmp_path: Path) -> None:
    built = prepare_v8_candidate_bundle(destination_root=tmp_path / "bundles")

    assert set(built.delta["replacements"]) == set(V8_REPLACEMENTS)
    assert set(built.delta["additions"]) == set(V8_ADDITIONS)
    assert built.delta["unchanged_file_count"] == 113
    assert built.delta["evaluator_or_adapter_source_changed"] is False
    assert len(built.reference.files_sha256) == 116
    assert len(built.bundle.files_sha256) == 117
    for unchanged_boundary in (
        "evals/external/barn_ros2_node.py",
        "evals/external/parcel_barn_adapter.py",
        "overlay/BARN_runner.launch.py",
    ):
        assert built.bundle.files_sha256[unchanged_boundary] == (
            built.reference.files_sha256[unchanged_boundary]
        )
    frozen_sources = built.report_metadata()["allowlisted_delta"]["reviewed_sources"]
    assert (
        verify_v8_candidate_delta(
            built.bundle,
            built.reference,
            repo_root=None,
            expected_reviewed_sources=frozen_sources,
        )["reviewed_sources"]
        == frozen_sources
    )

    reference = parcel_isolated_bundle_reference_spec(
        built.reference.root,
        package_sha256=built.reference.package_sha256,
        manifest_sha256=built.reference.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="v8-real-reference-smoke",
        description="real historical sidecar smoke",
    )
    candidate = parcel_isolated_bundle_candidate_spec(
        built.bundle.root,
        package_sha256=built.bundle.package_sha256,
        reference_package_sha256=built.reference.package_sha256,
        manifest_sha256=built.bundle.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id="v8-real-candidate-smoke",
        description="real v8 sidecar smoke",
    )
    validate_isolated_policy_pair(reference, candidate)
    scan = (math.inf,) * 720
    observation = BarnObservation(
        position_xy=(0.0, 0.0),
        heading_rad=0.0,
        lidar_ranges_m=scan,
        lidar_angle_min_rad=-math.pi,
        lidar_angle_increment_rad=2.0 * math.pi / 719,
        time_s=1.0,
    )
    reference_policy = reference.create(episode_seed=4000)
    candidate_policy = candidate.create(episode_seed=4000, allow_experimental=True)
    try:
        for policy in (reference_policy, candidate_policy):
            policy.reset((0.0, 0.0), 0.0, (10.0, 0.0))
        assert math.isfinite(reference_policy.act(observation).vx_mps)
        candidate_action = candidate_policy.act(observation)
        assert math.isfinite(candidate_action.vx_mps)
        assert "all_ray" in candidate_action.note
    finally:
        reference_policy.close()
        candidate_policy.close()
