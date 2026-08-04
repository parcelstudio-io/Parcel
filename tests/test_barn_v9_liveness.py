from __future__ import annotations

import pytest

from evals.external.barn_v9_liveness import (
    LivenessConfig,
    PublishedActionSample,
    analyze_episode_liveness,
    find_safe_escape_witness,
)


def _sample(
    step: int,
    *,
    x: float = 0.0,
    vx: float = 0.0,
    yaw: float = 0.0,
    stop: bool = False,
    inside: bool = False,
    collided: bool = False,
    requested: float | None = None,
    scale: float | None = None,
    certified: bool | None = None,
    clearance: float | None = None,
) -> PublishedActionSample:
    return PublishedActionSample(
        step_index=step,
        position_xy=(x, 0.0),
        published_vx_mps=vx,
        published_vy_mps=0.0,
        published_yaw_rate_rps=yaw,
        published_stop=stop,
        collided=collided,
        inside_success_region=inside,
        requested_translation_mps=requested,
        all_ray_scale_limit=scale,
        certificate_satisfied=certified,
        signed_clearance_m=clearance,
    )


def test_hidden_incomplete_scan_hard_stop_is_measured_without_note_parsing() -> None:
    samples = [
        _sample(step, yaw=0.001, requested=0.45, scale=0.0)
        for step in range(63)
    ]

    report = analyze_episode_liveness(
        samples,
        trial_started=True,
        navigation_no_progress_latched=True,
    )

    assert report.long_stationary_run_count == 1
    assert report.maximum_consecutive_stationary_steps == 63
    assert report.stationary_tail_steps == 63
    assert report.structured_shield_veto_steps == 63
    assert report.navigation_no_progress_latched is True


def test_short_rotate_first_alignment_is_not_a_long_stall() -> None:
    samples = [_sample(step, yaw=0.35) for step in range(20)]
    samples.extend(_sample(step, x=(step - 19) * 0.02, vx=0.2) for step in range(20, 30))

    report = analyze_episode_liveness(
        samples,
        trial_started=True,
        navigation_no_progress_latched=False,
    )

    assert report.maximum_consecutive_stationary_steps == 20
    assert report.long_stationary_run_count == 0
    assert report.stationary_tail_steps == 0
    assert report.structured_shield_veto_steps == 0


def test_odometry_excursion_prevents_out_and_back_motion_from_being_called_stall() -> None:
    samples = [
        _sample(step, x=0.05 * min(step, 100 - step))
        for step in range(100)
    ]

    report = analyze_episode_liveness(
        samples,
        trial_started=True,
        navigation_no_progress_latched=False,
    )

    assert report.runs[0].step_count == 100
    assert report.runs[0].maximum_odometry_excursion_m == pytest.approx(2.5)
    assert report.runs[0].is_long is False


def test_arrival_collision_and_explicit_stop_are_not_stationary_liveness_failures() -> None:
    samples = [
        _sample(0, stop=True),
        _sample(1, inside=True),
        _sample(2, collided=True),
    ]

    report = analyze_episode_liveness(
        samples,
        trial_started=True,
        navigation_no_progress_latched=False,
    )

    assert report.stationary_action_count == 0
    assert report.runs == ()


@pytest.mark.parametrize(("steps", "expected"), [(49, 0), (50, 1), (51, 1)])
def test_long_stall_threshold_is_exact(steps: int, expected: int) -> None:
    report = analyze_episode_liveness(
        [_sample(step) for step in range(steps)],
        trial_started=False,
        navigation_no_progress_latched=False,
    )

    assert report.long_stationary_run_count == expected
    assert report.startup_failed is True


def test_safe_escape_requires_half_metre_certified_clearance_preserving_progress() -> None:
    reference = [_sample(step, requested=0.4, scale=0.0) for step in range(60)]
    candidate = [
        _sample(
            step,
            x=step * 0.01,
            vx=0.1,
            certified=True,
            clearance=0.48,
        )
        for step in range(60)
    ]

    witness = find_safe_escape_witness(reference, candidate)

    assert witness is not None
    assert witness.reference_stall_start_step == 0
    assert witness.reference_stall_steps == 60
    assert witness.candidate_escape_step == 50
    assert witness.candidate_progress_m == pytest.approx(0.5)
    assert witness.minimum_candidate_clearance_m == pytest.approx(0.48)


def test_safe_escape_rejects_certificate_or_clearance_gap() -> None:
    reference = [_sample(step) for step in range(50)]
    candidate = [
        _sample(
            step,
            x=step * 0.02,
            vx=0.2,
            certified=step != 10,
            clearance=0.48,
        )
        for step in range(30)
    ]

    assert find_safe_escape_witness(reference, candidate) is None


def test_validation_rejects_reordered_steps_and_unstructured_scale() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        analyze_episode_liveness(
            [_sample(2), _sample(1)],
            trial_started=True,
            navigation_no_progress_latched=False,
        )
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        _sample(0, scale=1.1)


def test_validation_rejects_step_gaps_in_stationary_duration() -> None:
    with pytest.raises(ValueError, match="must be consecutive"):
        analyze_episode_liveness(
            [_sample(4), _sample(6)],
            trial_started=True,
            navigation_no_progress_latched=False,
        )


def test_report_serialization_is_json_ready() -> None:
    report = analyze_episode_liveness(
        [_sample(step) for step in range(3)],
        trial_started=False,
        navigation_no_progress_latched=False,
        config=LivenessConfig(long_stall_steps=3),
    )

    payload = report.as_dict()
    assert payload["long_stationary_run_count"] == 1
    assert payload["runs"][0]["duration_s"] == pytest.approx(0.3)
