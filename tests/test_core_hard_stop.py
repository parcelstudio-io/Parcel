from __future__ import annotations

import math

import pytest

from parcel_robot.core.hard_stop import (
    ZERO_COMMAND,
    InterventionSeverity,
    ResetObligation,
    finalize_command,
)
from parcel_robot.models import VelocityCommand


class _CachedStage:
    def __init__(self, scale: float) -> None:
        self.scale = scale
        self.cached = ZERO_COMMAND
        self.reset_count = 0

    def step(self, command: VelocityCommand) -> VelocityCommand:
        self.cached = VelocityCommand(
            vx=command.vx * self.scale,
            vy=command.vy * self.scale,
            vyaw=command.vyaw * self.scale,
        )
        return self.cached

    def reset(self) -> None:
        self.cached = ZERO_COMMAND
        self.reset_count += 1


@pytest.mark.parametrize("interrupt_after_stage", range(4))
def test_hard_intervention_at_every_shaping_stage_dispatches_exact_zero(
    interrupt_after_stage: int,
) -> None:
    """Property: no interruption point can leak a cached shaped command."""

    stages = [
        _CachedStage(0.9),  # acceleration smoother
        _CachedStage(0.7),  # geometric/TTC gate
        _CachedStage(0.8),  # actuator S-curve shaper
    ]
    candidate = VelocityCommand(vx=0.6, vy=-0.2, vyaw=0.4)
    severity = InterventionSeverity.CLEAR
    for index, stage in enumerate(stages, start=1):
        candidate = stage.step(candidate)
        if interrupt_after_stage == index:
            severity = InterventionSeverity.HARD_STOP
    if interrupt_after_stage == 0:
        severity = InterventionSeverity.HARD_STOP

    decision = finalize_command(
        candidate,
        severity,
        downstream_stages=(
            ResetObligation("velocity_smoother", stages[0].reset),
            ResetObligation("collision_gate_cache", stages[1].reset),
            ResetObligation("actuator_shaper", stages[2].reset),
        ),
    )

    assert decision.command == VelocityCommand(vx=0.0, vy=0.0, vyaw=0.0)
    assert decision.command == ZERO_COMMAND
    assert decision.reset_attempted == (
        "velocity_smoother",
        "collision_gate_cache",
        "actuator_shaper",
    )
    assert decision.reset_failures == ()
    assert all(stage.cached == ZERO_COMMAND for stage in stages)
    assert all(stage.reset_count == 1 for stage in stages)


def test_hard_stop_attempts_every_reset_and_still_returns_exact_zero() -> None:
    called: list[str] = []

    def broken() -> None:
        called.append("broken")
        raise RuntimeError("seeded reset failure")

    def healthy() -> None:
        called.append("healthy")

    decision = finalize_command(
        VelocityCommand(vx=0.5),
        InterventionSeverity.HARD_STOP,
        downstream_stages=(
            ResetObligation("broken", broken),
            ResetObligation("healthy", healthy),
        ),
    )

    assert decision.command == ZERO_COMMAND
    assert called == ["broken", "healthy"]
    assert decision.reset_failures == ("broken:RuntimeError",)
    assert decision.dispatch_allowed


@pytest.mark.parametrize(
    "candidate",
    [
        VelocityCommand(vx=math.nan),
        VelocityCommand(vy=math.inf),
        VelocityCommand(vyaw=-math.inf),
    ],
)
def test_malformed_candidate_fails_to_exact_hard_stop(candidate: VelocityCommand) -> None:
    decision = finalize_command(candidate, InterventionSeverity.CLEAR)

    assert decision.severity is InterventionSeverity.HARD_STOP
    assert decision.command == ZERO_COMMAND
    assert decision.reset_required


def test_unknown_severity_fails_to_exact_hard_stop() -> None:
    decision = finalize_command(
        VelocityCommand(vx=0.3),
        "clear",  # type: ignore[arg-type]
    )

    assert decision.severity is InterventionSeverity.HARD_STOP
    assert decision.command == ZERO_COMMAND


def test_proximity_stop_preserves_only_finite_yaw_without_reset() -> None:
    reset_calls = 0

    def reset() -> None:
        nonlocal reset_calls
        reset_calls += 1

    decision = finalize_command(
        VelocityCommand(vx=0.4, vy=-0.1, vyaw=0.25),
        InterventionSeverity.PROXIMITY_STOP,
        downstream_stages=(ResetObligation("shaper", reset),),
    )

    assert decision.command == VelocityCommand(vyaw=0.25)
    assert not decision.reset_required
    assert reset_calls == 0


def test_clear_severity_passes_candidate_without_reset() -> None:
    reset_calls = 0

    def reset() -> None:
        nonlocal reset_calls
        reset_calls += 1

    candidate = VelocityCommand(vx=0.15, vy=-0.05, vyaw=0.1)
    decision = finalize_command(
        candidate,
        InterventionSeverity.CLEAR,
        downstream_stages=(ResetObligation("shaper", reset),),
    )

    assert decision.command == candidate
    assert decision.severity is InterventionSeverity.CLEAR
    assert not decision.reset_required
    assert decision.reset_attempted == ()
    assert reset_calls == 0


def test_hard_stop_with_no_registered_stages_still_exact_zero() -> None:
    decision = finalize_command(
        VelocityCommand(vx=1.0, vy=0.2, vyaw=-0.3),
        InterventionSeverity.HARD_STOP,
    )

    assert decision.command == ZERO_COMMAND
    assert decision.reset_required
    assert decision.reset_attempted == ()
    assert decision.reset_failures == ()
    assert decision.dispatch_allowed


def test_seeded_residual_command_mutant_is_killed_by_exact_zero_oracle() -> None:
    """Unit-level mutant: residual nonzero after HARD_STOP fails the P0-A oracle."""

    def exact_zero_oracle(command: VelocityCommand) -> None:
        assert command == ZERO_COMMAND

    stages = [
        _CachedStage(0.9),
        _CachedStage(0.7),
        _CachedStage(0.8),
    ]
    candidate = VelocityCommand(vx=0.6, vy=-0.2, vyaw=0.4)
    for stage in stages:
        candidate = stage.step(candidate)
    healthy = finalize_command(
        candidate,
        InterventionSeverity.HARD_STOP,
        downstream_stages=(
            ResetObligation("velocity_smoother", stages[0].reset),
            ResetObligation("collision_gate_cache", stages[1].reset),
            ResetObligation("actuator_shaper", stages[2].reset),
        ),
    )
    exact_zero_oracle(healthy.command)

    residual_mutant = VelocityCommand(vx=1e-3)
    with pytest.raises(AssertionError):
        exact_zero_oracle(residual_mutant)
