from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from evals.external.barn_native import BarnAction, BarnObservation
from evals.external.barn_policy_specs import (
    BarnPolicySpec,
    parcel_isolated_bundle_candidate_spec,
)
from evals.external.barn_sensor_faithful import (
    CANDIDATE_THEN_REFERENCE,
    REFERENCE_THEN_CANDIDATE,
    CalibratedBarnConfig,
    alternating_paired_arm_order_schedule,
    calibrated_reference_config_spec,
    run_sensor_faithful_paired_comparison,
    validate_paired_arm_order_schedule,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BARN_GRID_REFERENCE_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_v1.yaml"
)


def _assets(root: Path) -> None:
    (root / "path_files").mkdir(parents=True)
    (root / "world_0.world").write_text(
        '<sdf version="1.6"><world name="default"/></sdf>\n',
        encoding="utf-8",
    )
    np.save(root / "path_files" / "path_0.npy", np.asarray([[15, 0], [15, 29]]))


class _LifecyclePolicy:
    def __init__(
        self,
        role: str,
        seed: int,
        events: list[tuple[str, int, str]],
        *,
        speed: float,
        latency_ms: float,
    ) -> None:
        self.role = role
        self.seed = seed
        self.events = events
        self.speed = speed
        self.latency_ms = latency_ms
        self.events.append((role, seed, "constructed"))

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy
        self.events.append((self.role, self.seed, "reset"))

    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        self.events.append((self.role, self.seed, "act"))
        return BarnAction(self.speed, 0.0, note=self.role)

    def latency_samples_ms(self) -> dict[str, tuple[float, ...]]:
        return {"test_policy_act": (self.latency_ms,)}

    def policy_diagnostics(self) -> dict[str, Any]:
        return {"role": self.role}

    def close(self) -> None:
        self.events.append((self.role, self.seed, "closed"))


def _lifecycle_spec(
    role: str,
    events: list[tuple[str, int, str]],
    *,
    speed: float,
    latency_ms: float,
    experimental: bool,
) -> BarnPolicySpec:
    return BarnPolicySpec(
        policy_id=f"paired-{role}",
        description=f"paired {role} lifecycle policy",
        agent_id="paired-test-agent",
        adapter_id="paired-test-adapter",
        model_id="none",
        factory=lambda seed: _LifecyclePolicy(
            role,
            seed,
            events,
            speed=speed,
            latency_ms=latency_ms,
        ),
        experimental=experimental,
    )


def _canonical(document: dict[str, object]) -> bytes:
    return (
        json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _isolated_candidate_bundle(root: Path) -> tuple[str, str]:
    files = {
        "configs/navigation/experiments/policy.yaml": (
            "models_root: configs/navigation/models\nactive_model: fake_v1\n"
        ),
        "configs/navigation/models/fake.yaml": "id: fake_v1\ndevice: cpu\n",
        "evals/__init__.py": "",
        "evals/external/__init__.py": "",
        "evals/external/parcel_barn_adapter.py": '''from types import SimpleNamespace

class ParcelBarnAdapter:
    def __init__(self, *, navigation_config):
        self.navigation_config = str(navigation_config)
    def reset(self, start_xy, heading_rad, goal_xy):
        return None
    def act(self, observation):
        return SimpleNamespace(
            vx_mps=0.3,
            yaw_rate_rps=0.0,
            stop=False,
            note="isolated-candidate",
        )
    def close(self):
        return None
''',
        "src/parcel_robot/__init__.py": "BUNDLE_ONLY = True\n",
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
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return package_sha256, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_alternating_schedule_is_exactly_balanced_for_thirty_pairs() -> None:
    schedule = alternating_paired_arm_order_schedule(30)

    assert schedule[::2] == (REFERENCE_THEN_CANDIDATE,) * 15
    assert schedule[1::2] == (CANDIDATE_THEN_REFERENCE,) * 15
    assert validate_paired_arm_order_schedule(schedule, pair_count=30) == schedule


@pytest.mark.parametrize(
    ("schedule", "pair_count", "message"),
    [
        ((REFERENCE_THEN_CANDIDATE,), 2, "exactly one order"),
        (("unsupported",), 1, "unsupported order"),
        ((REFERENCE_THEN_CANDIDATE,) * 4, 4, "counterbalance"),
    ],
)
def test_explicit_schedule_validation_fails_closed(
    schedule: tuple[str, ...],
    pair_count: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_paired_arm_order_schedule(schedule, pair_count=pair_count)


def test_local_pairs_are_serial_fresh_and_role_stable_when_candidate_runs_first(
    tmp_path: Path,
) -> None:
    _assets(tmp_path)
    events: list[tuple[str, int, str]] = []
    schedule = (CANDIDATE_THEN_REFERENCE, REFERENCE_THEN_CANDIDATE)
    report = run_sensor_faithful_paired_comparison(
        assets_root=tmp_path,
        world_indices=(0,),
        trials=2,
        suite_seed=401,
        workers=1,
        reference_spec=_lifecycle_spec(
            "reference",
            events,
            speed=0.25,
            latency_ms=1.0,
            experimental=False,
        ),
        candidate_spec=_lifecycle_spec(
            "candidate",
            events,
            speed=0.35,
            latency_ms=2.0,
            experimental=True,
        ),
        allow_experimental=True,
        config=CalibratedBarnConfig(timeout_s=0.1),
        arm_order_schedule=schedule,
    )

    expected_seeds = (401, 402)
    for seed, expected_roles in zip(
        expected_seeds,
        (("candidate", "reference"), ("reference", "candidate")),
        strict=True,
    ):
        lifecycle = [
            (role, event)
            for role, event_seed, event in events
            if event_seed == seed and event in {"constructed", "closed"}
        ]
        assert lifecycle == [
            (expected_roles[0], "constructed"),
            (expected_roles[0], "closed"),
            (expected_roles[1], "constructed"),
            (expected_roles[1], "closed"),
        ]

    baseline_episodes = report["baseline"]["episodes"]
    candidate_episodes = report["candidate"]["episodes"]
    assert [episode["episode_seed"] for episode in baseline_episodes] == list(expected_seeds)
    assert [episode["episode_seed"] for episode in candidate_episodes] == list(expected_seeds)
    assert all(episode["last_action_note"] == "reference" for episode in baseline_episodes)
    assert all(episode["last_action_note"] == "candidate" for episode in candidate_episodes)
    assert candidate_episodes[0]["paired_execution"] == {
        "role": "candidate",
        "arm_order": CANDIDATE_THEN_REFERENCE,
        "position": "first",
        "concurrent_with_other_arm": False,
    }
    assert baseline_episodes[0]["paired_execution"]["position"] == "second"

    paired = report["comparison"]["paired_execution"]
    assert paired["arms_never_concurrent_within_pair"] is True
    assert paired["same_world_config_trial_and_seed_within_pair"] is True
    assert paired["order_counts"] == {
        REFERENCE_THEN_CANDIDATE: 1,
        CANDIDATE_THEN_REFERENCE: 1,
    }
    assert [item["arm_order"] for item in paired["schedule"]] == list(schedule)
    assert paired["order_stratified"]["reference"]["first"]["latency"][
        "test_policy_act_p50_ms"
    ] == pytest.approx(1.0)
    assert paired["order_stratified"]["candidate"]["first"]["latency"][
        "test_policy_act_p50_ms"
    ] == pytest.approx(2.0)
    assert all(
        pair["arm_order"] == schedule[index]
        for index, pair in enumerate(report["comparison"]["paired_episodes"])
    )


def test_spawned_pair_accepts_process_and_isolated_descriptor_union(tmp_path: Path) -> None:
    assets_root = tmp_path / "assets"
    bundle_root = tmp_path / "candidate-bundle"
    _assets(assets_root)
    package_sha256, manifest_sha256 = _isolated_candidate_bundle(bundle_root)
    reference = calibrated_reference_config_spec(
        BARN_GRID_REFERENCE_CONFIG,
        reference_id="v8-paired-process-reference",
        description="spawned ProcessPolicyDescriptor reference",
    )
    candidate = parcel_isolated_bundle_candidate_spec(
        bundle_root,
        package_sha256=package_sha256,
        reference_package_sha256="0" * 64,
        manifest_sha256=manifest_sha256,
        navigation_config_relative="configs/navigation/experiments/policy.yaml",
        experiment_id="v8-paired-isolated-candidate",
        description="spawned IsolatedPolicyDescriptor candidate",
    )

    report = run_sensor_faithful_paired_comparison(
        assets_root=assets_root,
        world_indices=(0,),
        trials=2,
        suite_seed=509,
        workers=2,
        reference_spec=reference,
        candidate_spec=candidate,
        allow_experimental=True,
        config=CalibratedBarnConfig(timeout_s=0.1),
    )

    assert report["baseline"]["execution"]["process_start_method"] == "spawn"
    assert report["candidate"]["execution"]["process_start_method"] == "spawn"
    assert report["baseline"]["execution"]["episode_workers_effective"] == 2
    assert report["candidate"]["execution"]["episode_workers_effective"] == 2
    assert report["comparison"]["paired_episode_count"] == 2
    assert report["comparison"]["paired_execution"]["order_counts"] == {
        REFERENCE_THEN_CANDIDATE: 1,
        CANDIDATE_THEN_REFERENCE: 1,
    }
    assert all(
        episode["last_action_note"] == "isolated-candidate"
        for episode in report["candidate"]["episodes"]
    )
