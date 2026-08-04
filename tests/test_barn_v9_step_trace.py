from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest

from evals.external import barn_sensor_faithful as evaluator_module
from evals.external.barn_native import (
    OFFICIAL_START_XY,
    BarnAction,
    BarnObservation,
    BarnWorld,
    CylinderObstacle,
)
from evals.external.barn_sensor_faithful import (
    CalibratedBarnConfig,
    SensorFaithfulBarnRunner,
    V8EpisodeEvidenceCaptureSpec,
)
from evals.external.barn_v8_action_evidence import read_v8_action_evidence
from evals.external.barn_v9_liveness_adapter import (
    published_action_samples_from_verified_evidence,
)
from evals.external.barn_v9_step_trace import (
    V9PostIntegrationTrace,
    V9StepTraceError,
    deterministic_episode_result_payload,
    run_sensor_faithful_with_v9_step_trace,
)


class _ConstantPolicy:
    def __init__(self, action: BarnAction) -> None:
        self.action = action
        self.closed = False

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy

    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        return self.action

    def close(self) -> None:
        self.closed = True


class _ExplodingPolicy(_ConstantPolicy):
    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        raise RuntimeError("intentional policy failure")


class _BlockingPolicy(_ConstantPolicy):
    def __init__(
        self,
        *,
        reset_seen: threading.Event,
        act_seen: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        super().__init__(BarnAction(0.0, 0.0, stop=True, note="irrelevant"))
        self.reset_seen = reset_seen
        self.act_seen = act_seen
        self.release = release

    def reset(
        self,
        start_xy: tuple[float, float],
        heading_rad: float,
        goal_xy: tuple[float, float],
    ) -> None:
        del start_xy, heading_rad, goal_xy
        self.reset_seen.set()

    def act(self, observation: BarnObservation) -> BarnAction:
        del observation
        if self.act_seen is not None:
            self.act_seen.set()
        if self.release is not None and not self.release.wait(timeout=2.0):
            raise RuntimeError("test release was not signaled")
        return self.action


def _world(*cylinders: CylinderObstacle) -> BarnWorld:
    return BarnWorld(
        world_index=0,
        cylinders=tuple(cylinders),
        reference_path_grid=((15.0, 0.0), (15.0, 29.0)),
        reference_path_world=((-2.25, 5.075), (-2.25, 9.425)),
        optimal_path_length_m=10.0,
    )


def _config() -> CalibratedBarnConfig:
    return CalibratedBarnConfig(
        timeout_s=0.2,
        startup_timeout_s=0.4,
        trace_stride_steps=1,
        trace_max_samples=32,
    )


def test_traced_run_has_deterministic_full_step_evidence_and_result_parity() -> None:
    action = BarnAction(0.5, 0.15, note="label-must-not-affect-v9")
    runner = SensorFaithfulBarnRunner(_world(), _config())
    uninstrumented = runner.run(_ConstantPolicy(action))

    first = run_sensor_faithful_with_v9_step_trace(
        SensorFaithfulBarnRunner(_world(), _config()),
        _ConstantPolicy(action),
    )
    second = run_sensor_faithful_with_v9_step_trace(
        SensorFaithfulBarnRunner(_world(), _config()),
        _ConstantPolicy(action),
    )

    assert deterministic_episode_result_payload(first.result) == (
        deterministic_episode_result_payload(uninstrumented)
    )
    assert len(first.step_trace.records) == first.result.steps
    assert tuple(record.step_index for record in first.step_trace.records) == tuple(
        range(first.result.steps)
    )
    assert first.step_trace.records[-1].post_step_position_xy == first.result.final_position_xy
    assert first.step_trace.records[-1].timed_out is first.result.timed_out
    assert first.step_trace.canonical_json_bytes() == second.step_trace.canonical_json_bytes()
    assert first.step_trace.sha256 == second.step_trace.sha256

    payload = json.loads(first.step_trace.canonical_json_bytes())
    assert payload["schema_version"] == 1
    assert "note" not in payload["records"][0]
    assert payload["records"][0]["requested_vx_mps"] is None
    assert payload["records"][0]["requested_vy_mps"] is None
    assert payload["records"][0]["all_ray_scale_limit"] is None

    reparsed = V9PostIntegrationTrace.from_mapping(payload)
    assert reparsed == first.step_trace
    assert reparsed.canonical_json_bytes() == first.step_trace.canonical_json_bytes()
    assert reparsed.sha256 == first.step_trace.sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"unknown": 1}), "trace fields are not exact"),
        (lambda value: value.pop("records"), "trace fields are not exact"),
        (lambda value: value.update({"schema_version": True}), "schema_version"),
        (
            lambda value: value["records"][0].update({"unknown": 1}),
            "step fields are not exact",
        ),
        (
            lambda value: value["records"][0].update({"requested_vx_mps": 0.2}),
            "cannot contain inferred shield fields",
        ),
        (
            lambda value: value["records"][0].update({"post_step_position_xy": [0.0]}),
            "two-item tuple",
        ),
    ],
)
def test_serialized_trace_parser_rejects_schema_and_evidence_mutations(
    mutation,
    message: str,
) -> None:
    traced = run_sensor_faithful_with_v9_step_trace(
        SensorFaithfulBarnRunner(_world(), _config()),
        _ConstantPolicy(BarnAction(0.5, 0.0)),
    )
    payload = deepcopy(traced.step_trace.as_dict())
    mutation(payload)

    with pytest.raises(V9StepTraceError, match=message):
        V9PostIntegrationTrace.from_mapping(payload)


def test_collision_step_records_exact_post_pose_and_swept_clearance() -> None:
    obstacle = CylinderObstacle(center_xy=(-2.25, 3.45), radius_m=0.05)
    traced = run_sensor_faithful_with_v9_step_trace(
        SensorFaithfulBarnRunner(_world(obstacle), _config()),
        _ConstantPolicy(BarnAction(2.0, 0.0, note="success")),
    )

    assert traced.result.collided is True
    assert traced.result.steps == 1
    record = traced.step_trace.records[0]
    assert record.collided is True
    assert record.post_step_position_xy == OFFICIAL_START_XY
    assert record.post_step_position_xy == traced.result.final_position_xy
    assert record.swept_clearance_m is not None
    assert record.swept_clearance_m <= 0.0
    assert record.inside_success_region is False


def test_trace_rows_join_verified_actions_without_inventing_shield_fields(
    tmp_path: Path,
) -> None:
    capture = V8EpisodeEvidenceCaptureSpec(
        arm="candidate",
        execution_order=1,
        world_id=0,
        trial_id=3,
        seed=12345,
    )
    traced = run_sensor_faithful_with_v9_step_trace(
        SensorFaithfulBarnRunner(_world(), _config()),
        _ConstantPolicy(BarnAction(0.5, 0.0, note="all_ray_hard_boundary_stop")),
        evidence_capture=capture,
    )
    assert traced.action_evidence is not None
    target = tmp_path / "candidate.v8e"
    written = traced.action_evidence.write_exclusive(target)
    verified = read_v8_action_evidence(
        target,
        expected_artifact_sha256=written.identity.artifact_sha256,
    )

    rows = traced.step_trace.adapter_step_rows(
        capture,
        navigation_no_progress_latch_step=None,
    )
    samples = published_action_samples_from_verified_evidence(verified, rows)

    assert len(samples) == traced.result.steps
    assert len(samples) == len(verified.records)
    assert all(sample.requested_translation_mps is None for sample in samples)
    assert all(sample.all_ray_scale_limit is None for sample in samples)
    assert tuple(sample.position_xy for sample in samples) == tuple(
        record.post_step_position_xy for record in traced.step_trace.records
    )
    assert rows[-1]["timed_out"] is traced.result.timed_out


def test_integrator_global_is_restored_when_the_exact_runner_raises() -> None:
    original = evaluator_module._integrate_collision_terminal
    with pytest.raises(RuntimeError, match="intentional policy failure"):
        run_sensor_faithful_with_v9_step_trace(
            SensorFaithfulBarnRunner(_world(), _config()),
            _ExplodingPolicy(BarnAction(0.0, 0.0)),
        )
    assert evaluator_module._integrate_collision_terminal is original


def test_instrumented_runs_are_serialized_while_module_global_is_patched() -> None:
    first_reset = threading.Event()
    first_act = threading.Event()
    release_first = threading.Event()
    second_reset = threading.Event()
    failures: list[BaseException] = []

    def run(policy: _BlockingPolicy) -> None:
        try:
            run_sensor_faithful_with_v9_step_trace(
                SensorFaithfulBarnRunner(
                    _world(),
                    CalibratedBarnConfig(timeout_s=0.1, startup_timeout_s=0.1),
                ),
                policy,
            )
        except (AssertionError, RuntimeError, TypeError, ValueError) as exc:  # pragma: no cover
            failures.append(exc)

    first = threading.Thread(
        target=run,
        args=(
            _BlockingPolicy(
                reset_seen=first_reset,
                act_seen=first_act,
                release=release_first,
            ),
        ),
    )
    second = threading.Thread(
        target=run,
        args=(_BlockingPolicy(reset_seen=second_reset),),
    )
    original = evaluator_module._integrate_collision_terminal
    first.start()
    assert first_reset.wait(timeout=1.0)
    assert first_act.wait(timeout=1.0)
    second.start()
    assert not second_reset.wait(timeout=0.05)
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_reset.is_set()
    assert failures == []
    assert evaluator_module._integrate_collision_terminal is original
