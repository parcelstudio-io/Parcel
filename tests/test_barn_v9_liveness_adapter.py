from __future__ import annotations

import math
from pathlib import Path

import pytest

from evals.external.barn_v8_action_evidence import (
    V8ActionEvidenceBuilder,
    V8ActionEvidenceReadResult,
    read_v8_action_evidence,
)
from evals.external.barn_v9_liveness import LivenessConfig
from evals.external.barn_v9_liveness_adapter import (
    LivenessEvidenceSchemaError,
    aggregate_paired_failure_taxonomy,
    diagnose_paired_episode,
    diagnose_verified_episode,
    published_action_samples_from_verified_evidence,
)

RAY_COUNT = 720
ANGLE_MIN_RAD = -math.pi
ANGLE_INCREMENT_RAD = 2.0 * math.pi / (RAY_COUNT - 1)
WORLD_ID = 4100
TRIAL_ID = 2
SEED = 8675309


def _verified_evidence(
    tmp_path: Path,
    name: str,
    *,
    arm: str,
    actions: list[tuple[float, float, bool, str]],
    world_id: int = WORLD_ID,
) -> V8ActionEvidenceReadResult:
    builder = V8ActionEvidenceBuilder()
    for step, (vx, yaw, stop, note) in enumerate(actions):
        builder.append(
            step_index=step,
            execution_order=0 if arm == "reference" else 1,
            arm=arm,
            world_id=world_id,
            trial_id=TRIAL_ID,
            seed=SEED,
            issued_by_policy=True,
            observation_reused=False,
            normalized_scan_m=(math.inf,) * RAY_COUNT,
            angle_min_rad=ANGLE_MIN_RAD,
            angle_increment_rad=ANGLE_INCREMENT_RAD,
            published_vx_mps=vx,
            published_vy_mps=0.0,
            published_yaw_rate_rps=yaw,
            published_stop=stop,
            note=note,
            policy_observation_sha256=f"{step + 1:064x}",
        )
    target = tmp_path / f"{name}.v8e"
    written = builder.write_exclusive(target)
    return read_v8_action_evidence(
        target,
        expected_artifact_sha256=written.identity.artifact_sha256,
    )


def _step_rows(
    evidence: V8ActionEvidenceReadResult,
    *,
    positions: list[float] | None = None,
    requested: list[tuple[float, float]] | None = None,
    scales: list[float | None] | None = None,
    trial_started: list[bool] | None = None,
    success: list[bool] | None = None,
    collision: list[bool] | None = None,
    timed_out: list[bool] | None = None,
    no_progress: list[bool] | None = None,
    clearance: float | None = 0.48,
) -> list[dict[str, object]]:
    count = len(evidence.records)
    positions = positions if positions is not None else [0.0] * count
    requested = requested if requested is not None else [(0.0, 0.0)] * count
    scales = scales if scales is not None else [None] * count
    trial_started = trial_started if trial_started is not None else [True] * count
    success = success if success is not None else [False] * count
    collision = collision if collision is not None else [False] * count
    timed_out = timed_out if timed_out is not None else [False] * count
    no_progress = no_progress if no_progress is not None else [False] * count
    assert all(
        len(values) == count
        for values in (
            positions,
            requested,
            scales,
            trial_started,
            success,
            collision,
            timed_out,
            no_progress,
        )
    )
    return [
        {
            "step_index": record.step_index,
            "world_id": record.world_id,
            "trial_id": record.trial_id,
            "seed": record.seed,
            "arm": record.arm,
            "position_xy": [positions[index], 0.0],
            "inside_success_region": success[index],
            "collided": collision[index],
            "trial_started": trial_started[index],
            "navigation_no_progress_latched": no_progress[index],
            "timed_out": timed_out[index],
            "signed_clearance_m": clearance,
            "requested_vx_mps": requested[index][0],
            "requested_vy_mps": requested[index][1],
            "all_ray_scale_limit": scales[index],
        }
        for index, record in enumerate(evidence.records)
    ]


def test_verified_record_and_explicit_evaluator_fields_convert_exactly(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "conversion",
        arm="candidate",
        actions=[(0.1, -0.2, False, "navigation_no_progress|obstacle_stop")],
    )
    rows = _step_rows(
        evidence,
        positions=[1.25],
        requested=[(0.3, 0.4)],
        scales=[0.25],
    )

    samples = published_action_samples_from_verified_evidence(evidence, rows)

    assert len(samples) == 1
    sample = samples[0]
    assert sample.step_index == 0
    assert sample.position_xy == (1.25, 0.0)
    assert sample.published_vx_mps == pytest.approx(0.1)
    assert sample.published_yaw_rate_rps == pytest.approx(-0.2)
    assert sample.requested_translation_mps == pytest.approx(0.5)
    assert sample.all_ray_scale_limit == pytest.approx(0.25)
    assert sample.certificate_satisfied is True
    assert not hasattr(sample, "note")


def test_explicit_null_request_keeps_liveness_but_refuses_causal_attribution(
    tmp_path: Path,
) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "request-unavailable",
        arm="candidate",
        actions=[(0.0, 0.1, False, "all_ray_hard_boundary_stop")],
    )
    rows = _step_rows(evidence)
    rows[0]["requested_vx_mps"] = None
    rows[0]["requested_vy_mps"] = None

    samples = published_action_samples_from_verified_evidence(evidence, rows)

    assert samples[0].requested_translation_mps is None
    diagnosis = diagnose_verified_episode(
        evidence,
        rows,
        config=LivenessConfig(long_stall_steps=2),
    )
    assert diagnosis.structured_shield_long_run_count == 0


def test_half_present_request_is_rejected(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "half-request",
        arm="candidate",
        actions=[(0.0, 0.1, False, "clear")],
    )
    rows = _step_rows(evidence)
    rows[0]["requested_vx_mps"] = None

    with pytest.raises(LivenessEvidenceSchemaError, match="both be present or both be null"):
        published_action_samples_from_verified_evidence(evidence, rows)


def test_bare_records_are_rejected_even_when_their_artifact_was_verified(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "bare-record",
        arm="candidate",
        actions=[(0.0, 0.1, False, "clear")],
    )

    with pytest.raises(TypeError, match="verified reader"):
        published_action_samples_from_verified_evidence(  # type: ignore[arg-type]
            evidence.records,
            _step_rows(evidence),
        )


@pytest.mark.parametrize(
    "missing_field",
    ["position_xy", "requested_vx_mps", "requested_vy_mps", "all_ray_scale_limit"],
)
def test_missing_position_request_or_structured_shield_field_fails_closed(
    tmp_path: Path,
    missing_field: str,
) -> None:
    evidence = _verified_evidence(
        tmp_path,
        f"missing-{missing_field}",
        arm="candidate",
        actions=[(0.0, 0.1, False, "clear")],
    )
    row = _step_rows(evidence)[0]
    del row[missing_field]

    with pytest.raises(LivenessEvidenceSchemaError, match="never inferred"):
        published_action_samples_from_verified_evidence(evidence, [row])


def test_step_join_and_episode_identity_are_exact(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "join",
        arm="candidate",
        actions=[(0.0, 0.1, False, "clear")],
    )
    extra = _step_rows(evidence)[0] | {"step_index": 99}
    with pytest.raises(LivenessEvidenceSchemaError, match="one-to-one"):
        published_action_samples_from_verified_evidence(
            evidence,
            [*_step_rows(evidence), extra],
        )

    mismatch = _step_rows(evidence)
    mismatch[0]["world_id"] = WORLD_ID + 1
    with pytest.raises(LivenessEvidenceSchemaError, match="identity mismatch"):
        published_action_samples_from_verified_evidence(evidence, mismatch)


def test_failure_taxonomy_uses_structured_flags_not_adversarial_note_text(
    tmp_path: Path,
) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "watchdog",
        arm="candidate",
        actions=[
            (0.0, 0.1, False, "all_ray_hard_boundary_stop"),
            (0.0, -0.1, False, "success"),
            (0.0, 0.1, False, "everything_is_fine"),
        ],
    )
    rows = _step_rows(
        evidence,
        requested=[(0.0, 0.0)] * 3,
        scales=[None] * 3,
        no_progress=[False, False, True],
        timed_out=[False, False, True],
    )

    diagnosis = diagnose_verified_episode(
        evidence,
        rows,
        config=LivenessConfig(long_stall_steps=3),
    )

    assert diagnosis.failure_kind == "navigation_no_progress"
    assert diagnosis.liveness.long_stationary_run_count == 1
    assert diagnosis.structured_shield_long_run_count == 0
    assert diagnosis.navigation_no_progress_latched is True


def test_startup_timeout_is_derived_from_structured_trial_state(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "startup",
        arm="candidate",
        actions=[
            (0.0, 0.1, False, "success"),
            (0.0, -0.1, False, "success"),
            (0.0, 0.1, False, "success"),
        ],
    )
    diagnosis = diagnose_verified_episode(
        evidence,
        _step_rows(
            evidence,
            trial_started=[False] * 3,
            timed_out=[False, False, True],
        ),
        config=LivenessConfig(long_stall_steps=3),
    )

    assert diagnosis.failure_kind == "startup_timeout"
    assert diagnosis.liveness.startup_failed is True


def test_policy_stop_outside_goal_is_a_label_independent_failure(tmp_path: Path) -> None:
    evidence = _verified_evidence(
        tmp_path,
        "stopped-outside-goal",
        arm="candidate",
        actions=[(0.0, 0.0, True, "everything_is_fine")],
    )

    diagnosis = diagnose_verified_episode(
        evidence,
        _step_rows(evidence, timed_out=[True]),
    )

    assert diagnosis.failure_kind == "stopped_outside_goal"
    assert diagnosis.policy_stop_latched is True


def test_paired_taxonomy_counts_certified_safe_escape_from_structured_shield_stall(
    tmp_path: Path,
) -> None:
    reference = _verified_evidence(
        tmp_path,
        "reference",
        arm="reference",
        actions=[
            (0.0, 0.1, False, "clear"),
            (0.0, -0.1, False, "clear"),
            (0.0, 0.1, False, "clear"),
        ],
    )
    candidate = _verified_evidence(
        tmp_path,
        "candidate",
        arm="candidate",
        actions=[
            (0.2, 0.0, False, "navigation_no_progress"),
            (0.2, 0.0, False, "obstacle_stop"),
            (0.2, 0.0, False, "collision"),
        ],
    )
    config = LivenessConfig(
        long_stall_steps=3,
        safe_escape_progress_m=0.5,
        safe_escape_minimum_clearance_m=0.475,
    )
    pair = diagnose_paired_episode(
        reference,
        _step_rows(
            reference,
            requested=[(0.4, 0.0)] * 3,
            scales=[0.0] * 3,
            timed_out=[False, False, True],
        ),
        candidate,
        _step_rows(
            candidate,
            positions=[0.0, 0.3, 0.6],
            requested=[(0.2, 0.0)] * 3,
            scales=[1.0] * 3,
            success=[False, False, True],
        ),
        config=config,
    )
    aggregate = aggregate_paired_failure_taxonomy([pair])

    assert pair.transition == "structured_shield_stall->success"
    assert pair.safe_escape_witness is not None
    assert pair.safe_escape_witness.candidate_progress_m == pytest.approx(0.6)
    assert aggregate.pair_count == 1
    assert aggregate.reference_counts["structured_shield_stall"] == 1
    assert aggregate.candidate_counts["success"] == 1
    assert aggregate.reference_structured_shield_stall_episode_count == 1
    assert aggregate.candidate_structured_shield_stall_episode_count == 0
    assert aggregate.safe_escape_witness_count == 1
    assert aggregate.candidate_liveness_gain_count == 1
    assert aggregate.candidate_liveness_regression_count == 0
    assert aggregate.as_dict()["transition_counts"] == {"structured_shield_stall->success": 1}


def test_paired_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    reference = _verified_evidence(
        tmp_path,
        "identity-reference",
        arm="reference",
        actions=[(0.0, 0.1, False, "clear")],
    )
    candidate = _verified_evidence(
        tmp_path,
        "identity-candidate",
        arm="candidate",
        actions=[(0.1, 0.0, False, "clear")],
        world_id=WORLD_ID + 1,
    )

    with pytest.raises(LivenessEvidenceSchemaError, match="identities differ"):
        diagnose_paired_episode(
            reference,
            _step_rows(reference),
            candidate,
            _step_rows(candidate),
        )
