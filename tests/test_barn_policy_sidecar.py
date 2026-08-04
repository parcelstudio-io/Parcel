from __future__ import annotations

import hashlib
import json
import math
import pickle
from dataclasses import replace
from pathlib import Path

import pytest

from evals.external import barn_policy_specs as policy_specs_module
from evals.external.barn_native import BarnObservation
from evals.external.barn_policy_sidecar import (
    HISTORICAL_BUNDLE,
    HISTORICAL_MANIFEST_SHA256,
    HISTORICAL_PACKAGE_SHA256,
    IsolatedPolicyDescriptor,
    historical_isolated_policy_descriptor,
    verify_policy_bundle,
)
from evals.external.barn_policy_specs import (
    ExperimentalPolicyDisabledError,
    IsolatedPlannerProfileAuthorization,
    parcel_historical_isolated_reference_spec,
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_planner_profile_pair,
    validate_isolated_policy_pair,
)
from evals.external.barn_sensor_faithful import run_sensor_faithful_paired_comparison


def _canonical(document: dict[str, object]) -> bytes:
    return (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _fake_bundle(
    root: Path,
    *,
    velocity: float,
    note: str,
    classify_lidar: bool = False,
    model_extra: str = "",
) -> tuple[str, str]:
    files = {
        "configs/navigation/experiments/policy.yaml": (
            "models_root: configs/navigation/models\n"
            "active_model: fake_v1\n"
            f"velocity: {velocity!r}\n"
            f"note: {note}\n"
            f"classify_lidar: {str(classify_lidar).lower()}\n"
        ),
        "configs/navigation/models/fake.yaml": (
            "id: fake_v1\ndevice: cpu\n" + model_extra
        ),
        "evals/__init__.py": "",
        "evals/external/__init__.py": "",
        "evals/external/parcel_barn_adapter.py": '''import math
from pathlib import Path
from types import SimpleNamespace

class ParcelBarnAdapter:
    def __init__(self, *, navigation_config):
        self.config = str(navigation_config)
        values = {}
        for line in Path(navigation_config).read_text(encoding="utf-8").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip()] = value.strip()
        self.velocity = float(values["velocity"])
        self.note = values["note"]
        self.classify_lidar = values["classify_lidar"] == "true"
        self.calls = 0
    def reset(self, start_xy, heading_rad, goal_xy):
        self.calls = 0
    def act(self, observation):
        self.calls += 1
        note = self.note
        if self.classify_lidar:
            note = (
                f"finite={sum(math.isfinite(value) for value in observation.lidar_ranges_m)};"
                f"clear={sum(math.isinf(value) and value > 0 for value in observation.lidar_ranges_m)};"
                f"unavailable={sum(math.isnan(value) for value in observation.lidar_ranges_m)}"
            )
        return SimpleNamespace(vx_mps=self.velocity, yaw_rate_rps=0.25, stop=False, note=note)
    def latency_samples_ms(self):
        return {"adapter_act": [1.25]}
    def policy_diagnostics(self):
        return {"calls": self.calls, "policy_owned_only": True}
    def close(self):
        return None
''',
        "src/parcel_robot/__init__.py": "FAKE_BUNDLE_ONLY = True\n",
    }
    hashes: dict[str, str] = {}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    material: dict[str, object] = {
        "files_sha256": hashes,
        "package_kind": "barn-ros2-parcel-submission-hook-bundle-v1",
        "schema_version": 1,
    }
    package_sha256 = hashlib.sha256(_canonical(material)).hexdigest()
    manifest = {**material, "package_sha256": package_sha256}
    manifest_path = root / "package-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return package_sha256, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _observation() -> BarnObservation:
    return BarnObservation(
        position_xy=(-2.25, 3.0),
        heading_rad=1.57,
        lidar_ranges_m=(10.0,) * 32,
        lidar_angle_min_rad=-2.35,
        lidar_angle_increment_rad=0.1,
        time_s=0.0,
    )


def test_bundle_verification_is_exact_membership_and_content_addressed(tmp_path: Path) -> None:
    package_sha256, manifest_sha256 = _fake_bundle(tmp_path, velocity=0.2, note="reference")
    verified = verify_policy_bundle(
        tmp_path,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
    )
    assert verified.package_sha256 == package_sha256

    unexpected = tmp_path / "unexpected.py"
    unexpected.write_text("pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unmanifested or missing"):
        verify_policy_bundle(
            tmp_path,
            expected_package_sha256=package_sha256,
            expected_manifest_sha256=manifest_sha256,
        )


def test_isolated_policy_round_trip_and_worker_identity(tmp_path: Path) -> None:
    package_sha256, manifest_sha256 = _fake_bundle(tmp_path, velocity=0.2, note="sidecar")
    descriptor = IsolatedPolicyDescriptor.freeze(
        tmp_path,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
    )
    assert pickle.loads(pickle.dumps(descriptor)) == descriptor
    assert descriptor.python_version
    assert len(descriptor.python_binary_sha256) == 64
    policy = descriptor.create(episode_seed=17)
    policy.reset((-2.25, 3.0), 1.57, (-2.25, 13.0))
    action = policy.act(_observation())
    policy.close()

    assert action.vx_mps == pytest.approx(0.2)
    assert action.note == "sidecar"
    latency = policy.latency_samples_ms()
    assert latency["adapter_act"] == (1.25,)
    assert len(latency["sidecar_act_round_trip"]) == 1
    assert latency["sidecar_act_round_trip"][0] >= 0.0
    assert policy.policy_diagnostics()["calls"] == 1
    assert not tuple(tmp_path.rglob("__pycache__"))

    changed_worker = replace(descriptor, worker_sha256="0" * 64)
    with pytest.raises(ValueError, match="worker changed"):
        changed_worker.create(episode_seed=17)


def test_isolated_policy_round_trips_clear_and_unavailable_rays(
    tmp_path: Path,
) -> None:
    package_sha256, manifest_sha256 = _fake_bundle(
        tmp_path,
        velocity=0.2,
        note="unused",
        classify_lidar=True,
    )
    descriptor = IsolatedPolicyDescriptor.freeze(
        tmp_path,
        expected_package_sha256=package_sha256,
        expected_manifest_sha256=manifest_sha256,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
    )
    policy = descriptor.create(episode_seed=18)
    policy.reset((-2.25, 3.0), 1.57, (-2.25, 13.0))
    mixed = replace(
        _observation(),
        lidar_ranges_m=(1.0,) * 5 + (math.inf,) * 7 + (math.nan,) * 20,
    )
    try:
        action = policy.act(mixed)
        assert action.vx_mps == pytest.approx(0.2)
        assert action.note == "finite=5;clear=7;unavailable=20"
    finally:
        policy.close()


def test_reference_and_candidate_use_same_ipc_but_distinct_sources(tmp_path: Path) -> None:
    reference_root = tmp_path / "reference"
    candidate_root = tmp_path / "candidate"
    reference_package, reference_manifest = _fake_bundle(
        reference_root,
        velocity=0.2,
        note="reference",
    )
    candidate_package, candidate_manifest = _fake_bundle(
        candidate_root,
        velocity=0.3,
        note="candidate",
    )
    reference = parcel_isolated_bundle_reference_spec(
        reference_root,
        package_sha256=reference_package,
        manifest_sha256=reference_manifest,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
        reference_id="isolated-reference",
        description="test reference",
    )
    candidate = parcel_isolated_bundle_candidate_spec(
        candidate_root,
        package_sha256=candidate_package,
        reference_package_sha256=reference_package,
        manifest_sha256=candidate_manifest,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
        experiment_id="isolated-candidate",
        description="test candidate",
    )
    reference_isolation = reference.report_metadata()["execution_isolation"]
    candidate_isolation = candidate.report_metadata()["execution_isolation"]
    assert reference_isolation["protocol"] == candidate_isolation["protocol"]
    assert reference_isolation["worker_sha256"] == candidate_isolation["worker_sha256"]
    assert reference_isolation["package_sha256"] != candidate_isolation["package_sha256"]
    paired_identity = validate_isolated_policy_pair(reference, candidate)
    assert paired_identity["reference"] == reference_isolation
    assert paired_identity["candidate"] == candidate_isolation

    unequal_runtime = replace(
        candidate,
        process_descriptor=replace(
            candidate.process_descriptor,
            request_timeout_s=candidate.process_descriptor.request_timeout_s + 1.0,
        ),
    )
    with pytest.raises(ValueError, match="same execution environment"):
        validate_isolated_policy_pair(reference, unequal_runtime)

    unequal_worker_path = replace(
        candidate,
        process_descriptor=replace(
            candidate.process_descriptor,
            worker_path=str(tmp_path / "different-worker.py"),
        ),
    )
    with pytest.raises(ValueError, match="same execution environment"):
        validate_isolated_policy_pair(reference, unequal_worker_path)

    with pytest.raises(ValueError, match="same policy boundary and model contract"):
        validate_isolated_policy_pair(reference, replace(candidate, model_id="different-model"))

    with pytest.raises(ExperimentalPolicyDisabledError):
        candidate.create(episode_seed=1)
    reference_policy = reference.create(episode_seed=1)
    candidate_policy = candidate.create(episode_seed=1, allow_experimental=True)
    try:
        for policy in (reference_policy, candidate_policy):
            policy.reset((-2.25, 3.0), 1.57, (-2.25, 13.0))
        assert reference_policy.act(_observation()).vx_mps == pytest.approx(0.2)
        assert candidate_policy.act(_observation()).vx_mps == pytest.approx(0.3)
    finally:
        reference_policy.close()
        candidate_policy.close()

    with pytest.raises(ValueError, match="distinct package identities"):
        parcel_isolated_bundle_candidate_spec(
            reference_root,
            package_sha256=reference_package,
            reference_package_sha256=reference_package,
            manifest_sha256=reference_manifest,
            navigation_config_relative="configs/navigation/experiments/policy.yaml",
            experiment_id="invalid-same-source",
            description="invalid",
        )


def test_planner_profile_pair_allows_only_exact_pinned_model_yaml_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_root = tmp_path / "profile-reference"
    candidate_root = tmp_path / "profile-candidate"
    reference_package, reference_manifest = _fake_bundle(
        reference_root,
        velocity=0.2,
        note="same-config",
        model_extra="planner_mode: baseline\n",
    )
    candidate_package, candidate_manifest = _fake_bundle(
        candidate_root,
        velocity=0.2,
        note="same-config",
        model_extra="planner_mode: observed_first_frontier\n",
    )
    reference = parcel_isolated_bundle_reference_spec(
        reference_root,
        package_sha256=reference_package,
        manifest_sha256=reference_manifest,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
        reference_id="profile-reference",
        description="profile reference",
    )
    candidate = parcel_isolated_bundle_candidate_spec(
        candidate_root,
        package_sha256=candidate_package,
        reference_package_sha256=reference_package,
        manifest_sha256=candidate_manifest,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
        experiment_id="profile-candidate",
        description="profile candidate",
    )
    reference_model = reference.model_artifact_sha256
    candidate_model = candidate.model_artifact_sha256
    assert reference_model is not None
    assert candidate_model is not None
    assert reference_model != candidate_model
    assert reference.config_sha256 == candidate.config_sha256
    assert reference.model_id == candidate.model_id

    paired = validate_isolated_planner_profile_pair(
        reference,
        candidate,
        expected_reference_model_artifact_sha256=reference_model,
        expected_candidate_model_artifact_sha256=candidate_model,
    )

    assert paired["reference"] == reference.report_metadata()["execution_isolation"]
    assert paired["candidate"] == candidate.report_metadata()["execution_isolation"]
    assert paired["allowed_planner_profile_factor"] == {
        "kind": "active_navigation_model_artifact_sha256",
        "model_id": "fake_v1",
        "config_sha256": reference.config_sha256,
        "reference_model_artifact_sha256": reference_model,
        "candidate_model_artifact_sha256": candidate_model,
        "all_other_runtime_and_policy_boundary_fields_equal": True,
    }
    authorization = IsolatedPlannerProfileAuthorization(
        reference_package_sha256=reference_package,
        reference_manifest_sha256=reference_manifest,
        candidate_package_sha256=candidate_package,
        candidate_manifest_sha256=candidate_manifest,
        reference_model_artifact_sha256=reference_model,
        candidate_model_artifact_sha256=candidate_model,
        navigation_config_sha256=str(reference.config_sha256),
        model_id="fake_v1",
        reference_policy_id="profile-reference",
        candidate_policy_id="profile-candidate",
    )
    authorized = authorization.validate_pair(reference, candidate)
    assert authorized["allowed_planner_profile_factor"] == paired[
        "allowed_planner_profile_factor"
    ]
    assert authorized["planner_profile_authorization"] == (
        authorization.report_metadata()
    )
    authorization.validate_candidate_report_identity(
        package_sha256=candidate_package,
        manifest_sha256=candidate_manifest,
        experiment_id="profile-candidate",
    )
    with pytest.raises(ValueError, match="reported candidate identity"):
        authorization.validate_candidate_report_identity(
            package_sha256=reference_package,
            manifest_sha256=candidate_manifest,
            experiment_id="profile-candidate",
        )
    with pytest.raises(ValueError, match="same policy boundary and model contract"):
        validate_isolated_policy_pair(reference, candidate)

    with pytest.raises(ValueError, match="reference model artifact"):
        validate_isolated_planner_profile_pair(
            reference,
            candidate,
            expected_reference_model_artifact_sha256="0" * 64,
            expected_candidate_model_artifact_sha256=candidate_model,
        )
    with pytest.raises(ValueError, match="candidate model artifact"):
        validate_isolated_planner_profile_pair(
            reference,
            candidate,
            expected_reference_model_artifact_sha256=reference_model,
            expected_candidate_model_artifact_sha256="0" * 64,
        )
    with pytest.raises(ValueError, match="identities must differ"):
        validate_isolated_planner_profile_pair(
            reference,
            candidate,
            expected_reference_model_artifact_sha256=reference_model,
            expected_candidate_model_artifact_sha256=reference_model,
        )

    for changed in (
        replace(candidate, config_sha256="0" * 64),
        replace(candidate, model_id="different-model"),
        replace(candidate, policy_source_sha256="0" * 64),
        replace(candidate, implementation_sha256="0" * 64),
    ):
        with pytest.raises(ValueError, match="outside the exact active model artifact"):
            validate_isolated_planner_profile_pair(
                reference,
                changed,
                expected_reference_model_artifact_sha256=reference_model,
                expected_candidate_model_artifact_sha256=candidate_model,
            )

    unequal_runtime = replace(
        candidate,
        process_descriptor=replace(
            candidate.process_descriptor,
            request_timeout_s=candidate.process_descriptor.request_timeout_s + 1.0,
        ),
    )
    with pytest.raises(ValueError, match="same execution environment"):
        validate_isolated_planner_profile_pair(
            reference,
            unequal_runtime,
            expected_reference_model_artifact_sha256=reference_model,
            expected_candidate_model_artifact_sha256=candidate_model,
        )

    original_validator = policy_specs_module.validate_isolated_planner_profile_pair
    validator_calls: list[tuple[object, object]] = []

    def exact_validator_spy(
        first: object,
        second: object,
        **kwargs: object,
    ) -> dict[str, dict[str, object]]:
        validator_calls.append((first, second))
        return original_validator(first, second, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        policy_specs_module,
        "validate_isolated_planner_profile_pair",
        exact_validator_spy,
    )
    with pytest.raises(ValueError, match="same policy boundary and model contract"):
        run_sensor_faithful_paired_comparison(
            assets_root=tmp_path / "missing-assets",
            world_indices=(1,),
            candidate_spec=candidate,
            reference_spec=reference,
            allow_experimental=True,
        )
    assert validator_calls == []
    with pytest.raises(FileNotFoundError):
        run_sensor_faithful_paired_comparison(
            assets_root=tmp_path / "missing-assets",
            world_indices=(1,),
            candidate_spec=candidate,
            reference_spec=reference,
            allow_experimental=True,
            isolated_planner_profile_authorization=authorization,
        )
    assert validator_calls == [(reference, candidate)]


@pytest.mark.skipif(not HISTORICAL_BUNDLE.is_dir(), reason="historical bundle cache is absent")
def test_historical_reference_is_the_pinned_75f7ff4d_bundle() -> None:
    descriptor = historical_isolated_policy_descriptor()
    assert descriptor.package_sha256 == HISTORICAL_PACKAGE_SHA256
    assert descriptor.manifest_sha256 == HISTORICAL_MANIFEST_SHA256
    spec = parcel_historical_isolated_reference_spec()
    metadata = spec.report_metadata()
    assert metadata["execution_isolation"]["package_sha256"] == HISTORICAL_PACKAGE_SHA256
    assert metadata["provenance"]["policy_source_tree"]["sha256"] == (
        "ba49b751e8ddbec786ac269145cb40e036948fe54348a8e530114afcba40ae4d"
    )
    policy = spec.create(episode_seed=23)
    try:
        policy.reset((-2.25, 3.0), 1.57, (-2.25, 13.0))
        action = policy.act(_observation())
        assert action.note.startswith("grid_track")
    finally:
        policy.close()
