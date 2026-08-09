"""``Z_r`` wired: pose covariance widens the proximity envelope, and only that.

Lane B's hand-off 1 (``LANE_B_STATUS.md``): ``PoseEstimate.position_sigma_m``
(``sqrt(sigma_xx + sigma_yy)``) is exactly the scalar
``SafetyEnvelope.pose_uncertainty_m`` expects, and ISO/TS-15066 puts it in the
stopping distance as a plain additive term::

    stop_distance(v) = r_foot + v*tau + v^2/(2a) + Z_s + Z_r

So the navigator's collision policy is now derived per tick from the pose it is
acting on. Two claims, and the first is the one that makes this landable:

1. **Inert at sigma = 0.** ``TruthPoseProvider`` reports exactly zero
   covariance, so the policy returned is ``self.collision`` *itself* — object
   identity, not a float comparison — and every frozen row, eval digest and
   measured trace is untouched by construction.
2. **Widening under uncertainty.** A drift provider with a real covariance
   moves every one of the four proximity boundaries out by exactly sigma, and
   the brake consequently stops at a distance it previously called clear.

The direction is one-way: the term can only ever brake *earlier*.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE, SafetyEnvelope
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.grounder import PlaceGrounder
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.pose import Frame, PoseEstimate, PoseHealth

MODELS = REPO / "configs" / "navigation" / "models"


class _DriftPoseProvider:
    """A localizer that knows how unsure it is. Sim truth for the mean.

    Satisfies the ``PoseProvider`` protocol (``get_pose(frame)``), which is how
    ``pose.observation_pose`` resolves a provider attached to
    ``extras['pose_provider']``.
    """

    def __init__(self, sigma_m: float, xy: tuple[float, float] = (0.0, 0.0)) -> None:
        # position_sigma_m is sqrt(sxx + syy); split the variance evenly.
        variance = (sigma_m * sigma_m) / 2.0
        self._covariance = (
            variance, 0.0, 0.0,
            0.0, variance, 0.0,
            0.0, 0.0, 0.0,
        )
        self._xy = xy

    def get_pose(self, frame: Frame) -> PoseEstimate:
        return PoseEstimate(
            x=self._xy[0],
            y=self._xy[1],
            yaw=0.0,
            frame=frame,
            health=PoseHealth.HEALTHY,
            covariance=self._covariance,
        )


def _nav() -> DirectiveNavigator:
    return DirectiveNavigator(
        registry=ModelRegistry.load(MODELS),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )


def _observation(provider=None) -> NavObservation:
    extras: dict = {"collision": False, "perception_fresh": True}
    if provider is not None:
        extras["pose_provider"] = provider
    return NavObservation(position=(0.0, 0.0, 0.0), heading_deg=0.0, extras=extras)


def test_the_envelope_authority_carries_zr_as_an_additive_stopping_term():
    base = DEFAULT_SAFETY_ENVELOPE
    widened = SafetyEnvelope(pose_uncertainty_m=0.25)
    assert base.pose_uncertainty_m == 0.0
    assert widened.stop_distance(0.0) - base.stop_distance(0.0) == pytest.approx(0.25)
    assert widened.stop_distance(0.9) - base.stop_distance(0.9) == pytest.approx(0.25)


def test_at_sim_truth_the_policy_is_the_configured_object_itself():
    """The equality assertion: identity, so no measurement can have moved."""

    nav = _nav()
    try:
        assert nav._pose_uncertainty_m(_observation()) == 0.0
        assert nav.pose_aware_collision_policy(_observation()) is nav.collision
    finally:
        nav.close()


def test_a_drift_provider_widens_every_proximity_boundary_by_exactly_sigma():
    nav = _nav()
    try:
        sigma = 0.2
        observation = _observation(_DriftPoseProvider(sigma))
        measured = nav._pose_uncertainty_m(observation)
        assert measured == pytest.approx(sigma)
        policy = nav.pose_aware_collision_policy(observation)
        assert policy is not nav.collision
        for field in (
            "person_stop_m",
            "person_slow_m",
            "obstacle_stop_m",
            "obstacle_slow_m",
        ):
            assert getattr(policy, field) - getattr(nav.collision, field) == pytest.approx(
                sigma
            ), field
        # Unchanged: the widening is a distance term, not a retune.
        assert policy.slow_scale == nav.collision.slow_scale
        assert policy.reaction_time_s == nav.collision.reaction_time_s
        assert policy.predictive_mode == nav.collision.predictive_mode
    finally:
        nav.close()


def test_an_absurd_covariance_is_bounded_rather_than_freezing_the_robot():
    """A localizer reporting a 10 m sigma is broken; the answer to that is the
    pose-health path, not a 10 m stopping envelope with no way back."""

    nav = _nav()
    try:
        observation = _observation(_DriftPoseProvider(10.0))
        assert (
            nav._pose_uncertainty_m(observation)
            == DirectiveNavigator.MAX_POSE_UNCERTAINTY_M
        )
    finally:
        nav.close()


def test_a_pose_object_without_covariance_reports_no_uncertainty():
    """Bundle/legacy poses expose no covariance; absence is reported as absence.

    Fail-*open* is correct here and only here: inventing a non-zero Z_r for a
    pose that never claimed one would brake the robot on a fiction.
    """

    nav = _nav()
    try:
        assert nav._pose_uncertainty_m(_observation()) == 0.0
    finally:
        nav.close()
