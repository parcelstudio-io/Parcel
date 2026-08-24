"""Card W2: anticipatory following and the NIS uncertainty brake.

The prediction only ever changes *where the controller aims* and *how fast it
is allowed to translate*. Both halves are pinned here, along with the fallback
that must reproduce the unpredicted behavior bit for bit.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.follow import (
    OWNER_STAND_OFF_MARGIN_M,
    FollowConfig,
    FollowOwnerController,
    FollowPredictionConfig,
)
from parcel_robot.navigation.owner_prediction import PredictedPath
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


def _observation(
    timestamp: float,
    *,
    owner_x: float,
    owner_y: float = 0.0,
    robot_x: float = -3.0,
    robot_y: float = 0.0,
    robot_yaw: float = 0.0,
    confidence: float = 1.0,
) -> SimObservation:
    return SimObservation(
        timestamp=timestamp,
        robot=RobotPose(x=robot_x, y=robot_y, yaw=robot_yaw),
        owner=OwnerTrack(
            owner_id="owner-camera-track",
            x=owner_x,
            y=owner_y,
            visible=True,
            confidence=confidence,
        ),
        # Healthy fixtures include a far-field scan; missing scan fails closed (P0-B).
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        backend="follow-prediction-test",
    )


def _path(
    *,
    start: tuple[float, float] = (0.0, 0.0),
    velocity: tuple[float, float] = (1.2, 0.0),
    confidence: float = 0.9,
    step_s: float = 0.1,
    horizon_s: float = 2.5,
) -> PredictedPath:
    count = round(horizon_s / step_s)
    points = tuple(
        (start[0] + velocity[0] * step_s * index, start[1] + velocity[1] * step_s * index)
        for index in range(1, count + 1)
    )
    return PredictedPath(
        horizon_s=horizon_s,
        step_s=step_s,
        points=points,
        speed_mps=math.hypot(*velocity),
        heading_rad=math.atan2(velocity[1], velocity[0]),
        confidence=confidence,
    )


def _enabled(**overrides) -> FollowPredictionConfig:
    values = {"enabled": True}
    values.update(overrides)
    return FollowPredictionConfig(**values)


# --- configuration ----------------------------------------------------------


def test_unknown_prediction_keys_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown owner_follow.prediction settings"):
        FollowPredictionConfig.from_mapping({"lead_seconds": 0.6})


def test_prediction_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="lead_s must be positive"):
        FollowPredictionConfig(lead_s=0.0)
    with pytest.raises(ValueError, match="min_confidence must be within"):
        FollowPredictionConfig(min_confidence=1.4)
    with pytest.raises(ValueError, match="brake_stop_confidence must be below"):
        FollowPredictionConfig(brake_stop_confidence=0.9, brake_full_confidence=0.5)
    with pytest.raises(TypeError, match="enabled must be a boolean"):
        FollowPredictionConfig.from_mapping({"enabled": "yes"})


def test_the_shipped_config_block_loads() -> None:
    import yaml

    raw = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    config = FollowPredictionConfig.from_mapping(raw["owner_follow"]["prediction"])

    assert config.enabled is True
    assert config.lead_s == 0.6


# --- the brake ramp ---------------------------------------------------------


def test_the_brake_ramp_matches_the_card_worked_example() -> None:
    config = _enabled()

    # The card's example: half speed at confidence 0.3.
    assert config.speed_scale(0.3) == pytest.approx(0.5)
    assert config.speed_scale(0.9) == 1.0
    assert config.speed_scale(0.1) == 0.0
    assert config.speed_scale(0.0) == 0.0
    assert config.speed_scale(float("nan")) == 0.0


def test_the_brake_scales_translation_but_never_the_yaw() -> None:
    controller = FollowOwnerController(prediction=_enabled())
    controller.start()

    unbraked = controller.step(
        _observation(0.0, owner_x=0.0), now=0.0, prediction=_path(confidence=0.9)
    )
    controller.stop()
    controller.start()
    braked = controller.step(
        _observation(0.0, owner_x=0.0), now=0.0, prediction=_path(confidence=0.3)
    )

    assert unbraked.command.vx > 0.0
    assert braked.command.vx == pytest.approx(unbraked.command.vx * 0.5)
    assert braked.command.vyaw == pytest.approx(unbraked.command.vyaw)
    assert braked.speed_scale == pytest.approx(0.5)
    assert braked.reason.endswith("_uncertainty_braked")


def test_a_collapsed_confidence_brakes_to_a_standstill() -> None:
    controller = FollowOwnerController(prediction=_enabled())
    controller.start()

    decision = controller.step(
        _observation(0.0, owner_x=0.0), now=0.0, prediction=_path(confidence=0.05)
    )

    assert decision.command.vx == 0.0
    assert decision.speed_scale == 0.0
    # A collapsed prediction is refused as a target *and* braked.
    assert decision.prediction_active is False


# --- lead-point selection ---------------------------------------------------


def test_direct_follow_aims_at_the_lead_point_not_the_measured_owner() -> None:
    # A generous standoff leaves room to anticipate inside the owner keepout.
    config = FollowConfig(desired_distance_m=2.6)
    controller = FollowOwnerController(config, prediction=_enabled(lead_s=0.6))
    controller.start()
    observation = _observation(0.0, owner_x=0.0, robot_x=-3.0)
    # Owner at the origin walking +x at 1.2 m/s: 0.6 s ahead is x = 0.72.
    path = _path(start=(0.0, 0.0), velocity=(1.2, 0.0))

    predicted = controller.step(observation, now=0.0, prediction=path)
    controller.stop()
    controller.start()
    measured = controller.step(observation, now=0.0, prediction=None)

    assert predicted.prediction_active is True
    assert predicted.lead_x_m == pytest.approx(0.72)
    assert predicted.lead_y_m == pytest.approx(0.0)
    # The lead point is further away, so the anticipating follower drives
    # harder to close the same nominal band.
    assert predicted.distance_m == pytest.approx(measured.distance_m + 0.72)
    assert predicted.command.vx > measured.command.vx


def test_the_lead_point_curls_with_a_turning_owner() -> None:
    config = FollowConfig(desired_distance_m=2.6)
    controller = FollowOwnerController(config, prediction=_enabled(lead_s=0.6))
    controller.start()

    decision = controller.step(
        _observation(0.0, owner_x=0.0, robot_x=-3.0),
        now=0.0,
        prediction=_path(velocity=(0.0, 1.2)),
    )

    assert decision.lead_x_m == pytest.approx(0.0)
    assert decision.lead_y_m == pytest.approx(0.72)


def test_the_lead_is_clamped_to_the_owner_keepout() -> None:
    # The lead budget IS the stand-off margin: the direct stand-off minus the
    # owner keepout. Anticipation may not be paid for with owner clearance.
    # 2026-08-10 (owner-authorized person-clearance retune): the budget moved
    # 0.05 -> 0.10 m because ``desired_distance_m`` is now derived as
    # ``owner_keepout_m + OWNER_STAND_OFF_MARGIN_M`` instead of being a literal
    # 1.6 that happened to sit 0.05 m outside a 1.55 m keepout. Asserted through
    # the derivation so it cannot re-fork into a literal.
    config = FollowConfig()
    budget = config.desired_distance_m - config.owner_keepout_m
    assert budget == pytest.approx(OWNER_STAND_OFF_MARGIN_M)

    controller = FollowOwnerController(prediction=_enabled(lead_s=0.6))
    controller.start()

    decision = controller.step(
        _observation(0.0, owner_x=0.0, robot_x=-3.0),
        now=0.0,
        prediction=_path(velocity=(1.2, 0.0)),
    )

    assert decision.lead_x_m == pytest.approx(budget)
    assert controller.snapshot()["prediction"]["reason"] == "lead_clamped_to_owner_keepout"
    # The aim point still sits a full keepout away from the measured owner.
    assert decision.distance_m is not None
    assert math.hypot(decision.lead_x_m - 0.0, 0.0) <= budget + 1e-9


def test_the_behind_formation_anchors_on_the_prediction() -> None:
    config = FollowConfig()
    controller = FollowOwnerController(config, prediction=_enabled(lead_s=0.6))
    controller.start_formation("behind")
    # Seed the passive heading filter: behind formation refuses to run without
    # a measured owner heading, prediction or not.
    for index in range(6):
        stamp = index * 0.15
        controller.observe_owner(
            _observation(stamp, owner_x=index * 0.18, robot_x=-3.0), now=stamp
        )
    observation = _observation(0.9, owner_x=0.9, robot_x=-3.0)

    predicted = controller.step(observation, now=0.9, prediction=_path(start=(0.9, 0.0)))
    measured = controller.step(observation, now=0.9, prediction=None)

    assert predicted.target_x_m is not None and measured.target_x_m is not None
    # The usable lead is behind_distance minus the keepout, so the anchor sits
    # at owner + budget and the rear offset is the full behind distance.
    # 2026-08-10 (owner-authorized person-clearance retune): keepout
    # 1.55 -> 1.75 shrinks that budget 0.35 -> 0.15 m at an unchanged 1.9 m
    # behind distance. Derived from the config, not restated as a literal.
    behind_budget = config.behind_distance_m - config.owner_keepout_m
    assert behind_budget == pytest.approx(0.15)
    assert predicted.target_x_m == pytest.approx(
        0.9 + behind_budget - config.behind_distance_m
    )
    # The unpredicted path keeps its own 0.25 m short-horizon extrapolation;
    # the lead point replaces that rather than stacking on top of it. That
    # extrapolation is floored at the keepout ring plus the stand-off margin,
    # and after the retune the floor (1.85) now BINDS over 1.9 - 0.25 = 1.65:
    # a short-horizon guess may not pull the rear station inside the ring.
    rear_floor = config.owner_keepout_m + OWNER_STAND_OFF_MARGIN_M
    assert rear_floor == pytest.approx(1.85)
    assert measured.target_x_m == pytest.approx(
        0.9 - max(rear_floor, config.behind_distance_m - 0.25)
    )
    assert predicted.target_x_m > measured.target_x_m
    assert predicted.state == "tracking_behind"


# --- fallback ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("prediction", "expected_reason"),
    [
        (None, "no_prediction"),
        ("low", "confidence_below_threshold"),
        ("short", "lead_beyond_horizon"),
    ],
)
def test_every_fallback_reproduces_the_unpredicted_target(
    prediction: object,
    expected_reason: str,
) -> None:
    observation = _observation(0.0, owner_x=0.0, robot_x=-3.0)
    baseline = FollowOwnerController()
    baseline.start()
    expected = baseline.step(observation, now=0.0)

    controller = FollowOwnerController(prediction=_enabled(lead_s=0.6))
    controller.start()
    path = {
        None: None,
        "low": _path(confidence=0.2),
        "short": _path(horizon_s=0.2),
    }[prediction]
    decision = controller.step(observation, now=0.0, prediction=path)

    assert decision.prediction_active is False
    assert controller.snapshot()["prediction"]["reason"] == expected_reason
    assert decision.distance_m == pytest.approx(expected.distance_m)
    if expected_reason != "confidence_below_threshold":
        # The low-confidence case is also braked; the other two must be
        # indistinguishable from having no predictor at all.
        assert decision.command == expected.command


def test_a_disabled_predictor_changes_nothing_anywhere() -> None:
    observation = _observation(0.0, owner_x=0.0, robot_x=-3.0)
    baseline = FollowOwnerController()
    baseline.start()
    expected = baseline.step(observation, now=0.0)

    controller = FollowOwnerController(prediction=FollowPredictionConfig(enabled=False))
    controller.start()
    decision = controller.step(observation, now=0.0, prediction=_path(confidence=0.05))

    assert decision.command == expected.command
    assert decision.speed_scale == 1.0
    assert controller.snapshot()["prediction"]["reason"] == "disabled"


def test_the_prediction_block_is_reset_when_follow_stops() -> None:
    controller = FollowOwnerController(prediction=_enabled())
    controller.start()
    controller.step(_observation(0.0, owner_x=0.0), now=0.0, prediction=_path())
    assert controller.snapshot()["prediction"]["active"] is True

    controller.stop()

    assert controller.snapshot()["prediction"] == {
        "enabled": False,
        "active": False,
        "reason": "idle",
        "confidence": None,
        "lead_x_m": None,
        "lead_y_m": None,
        "speed_scale": 1.0,
    }


# --- safety composition -----------------------------------------------------


def test_the_brake_never_raises_a_command_it_was_given() -> None:
    controller = FollowOwnerController(prediction=_enabled())
    controller.start()

    for confidence in (0.0, 0.15, 0.3, 0.45, 0.6, 1.0):
        controller.stop()
        controller.start()
        baseline = FollowOwnerController()
        baseline.start()
        observation = _observation(0.0, owner_x=0.0, robot_x=-3.0)
        unbraked = baseline.step(observation, now=0.0)
        decision = controller.step(
            observation, now=0.0, prediction=_path(confidence=confidence)
        )
        assert abs(decision.command.vx) <= abs(unbraked.command.vx) + 1e-9


def test_a_stop_state_stays_stopped_under_every_confidence() -> None:
    controller = FollowOwnerController(prediction=_enabled())
    controller.start()
    blocked = SimObservation(
        timestamp=0.0,
        robot=RobotPose(x=-3.0),
        owner=OwnerTrack(owner_id="owner-camera-track", visible=True, confidence=1.0),
        collision=True,
        backend="follow-prediction-test",
    )

    decision = controller.step(blocked, now=0.0, prediction=_path(confidence=1.0))

    assert decision.command == VelocityCommand()
    assert decision.state == "blocked"


# --- runtime ownership ------------------------------------------------------


class _Backend:
    name = "follow-prediction-runtime"

    def __init__(self) -> None:
        self.owner = OwnerTrack(
            owner_id="owner-camera-track", x=0.0, y=0.0, visible=True, confidence=1.0
        )

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=-3.0),
            owner=self.owner,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("no planning in this test")


def _runtime(tmp_path: Path, *, prediction: str = "enabled: true") -> RobotRuntime:
    path = tmp_path / "follow-prediction.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
owner_follow:
  prediction:
    {prediction}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )


def test_a_typo_in_the_runtime_prediction_block_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown owner_follow.prediction settings"):
        _runtime(tmp_path, prediction="lead_seconds: 0.6")


def test_the_runtime_owns_one_predictor_fed_from_the_follow_track(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        for index in range(12):
            observation = SimObservation(
                timestamp=time.monotonic(),
                robot=RobotPose(x=-3.0),
                owner=OwnerTrack(
                    owner_id="owner-camera-track",
                    x=index * 0.12,
                    y=0.0,
                    visible=True,
                    confidence=1.0,
                ),
                backend="follow-prediction-runtime",
            )
            prediction = runtime._step_owner_prediction(observation)

        assert prediction is not None
        assert prediction.speed_mps > 0.0
        assert runtime._owner_predictor_id == "owner-camera-track"
    finally:
        runtime.close()


def test_a_new_owner_identity_resets_the_filter(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        for index in range(12):
            runtime._step_owner_prediction(
                SimObservation(
                    timestamp=time.monotonic(),
                    robot=RobotPose(x=-3.0),
                    owner=OwnerTrack(
                        owner_id="owner-a",
                        x=index * 0.12,
                        visible=True,
                        confidence=1.0,
                    ),
                    backend="follow-prediction-runtime",
                )
            )
        assert runtime.owner_predictor.predict(now_s=time.monotonic()) is not None

        after = runtime._step_owner_prediction(
            SimObservation(
                timestamp=time.monotonic(),
                robot=RobotPose(x=-3.0),
                owner=OwnerTrack(
                    owner_id="owner-b", x=9.0, visible=True, confidence=1.0
                ),
                backend="follow-prediction-runtime",
            )
        )

        assert runtime._owner_predictor_id == "owner-b"
        # One observation of a brand-new person carries no velocity yet.
        assert after is not None
        assert after.speed_mps == pytest.approx(0.0)
    finally:
        runtime.close()


def test_a_disabled_predictor_is_never_stepped(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, prediction="enabled: false")
    try:
        result = runtime._step_owner_prediction(runtime.backend.observe())

        assert result is None
        assert runtime.owner_predictor.predict(now_s=time.monotonic()) is None
    finally:
        runtime.close()


def test_the_snapshot_exposes_which_mode_is_live(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        block = runtime.snapshot()["follow"]["prediction"]

        assert block["enabled"] is False  # not started, so idle
        assert set(block) == {
            "enabled",
            "active",
            "reason",
            "confidence",
            "lead_x_m",
            "lead_y_m",
            "speed_scale",
        }
    finally:
        runtime.close()
