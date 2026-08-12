"""Card Y-2 gate: yield-aside wiring into direct follow, flag-gated default OFF.

What this file has to establish, in the record's order: the flag-off path is
the old path field for field; the flag-on path actually changes the aim
somewhere (a flag that never fires proves nothing); and the proposal lands
UPSTREAM of the gate, which keeps disposing exactly as it did.

``does_not_prove``: the full-bench flag-off byte-identity is measured by the
harness, not here (status doc W3_Y_STATUS.md); the reactive gate's people list
still carries one stranger scalar plus the owner, so the proposer's rejection
over the whole track set is the load-bearing multi-stranger check, not the
gate's; and nothing here says a scripted pedestrian is a person.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from parcel_robot.backends.base import (
    DynamicAgentTrack,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.follow import (
    FollowConfig,
    FollowOwnerController,
    FollowPredictionConfig,
    FollowYieldConfig,
)
from parcel_robot.navigation.owner_prediction import PredictedPath
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy, apply_reactive_safety
from parcel_robot.navigation.yield_aside import MEANINGFUL_IMPROVEMENT_M

RAY_COUNT = 72


def _scan(free_m: float = 30.0) -> dict[str, object]:
    return {
        "lidar_ranges": tuple([free_m] * RAY_COUNT),
        "lidar_angle_min_rad": -math.pi,
        "lidar_angle_increment_rad": 2.0 * math.pi / RAY_COUNT,
        "lidar_range_min_m": 0.05,
        "lidar_range_max_m": 30.0,
    }


def _pedestrian(agent_id: str, x: float, y: float, vx: float = 0.0, vy: float = 0.0):
    return DynamicAgentTrack(
        agent_id=agent_id,
        kind="pedestrian",
        x=x,
        y=y,
        vx=vx,
        vy=vy,
        radius_m=0.2,
    )


def _observation(
    *,
    robot: tuple[float, float, float] = (0.0, 0.0, 0.0),
    owner: tuple[float, float] = (3.4, 0.0),
    agents: tuple = (),
    now: float = 1.0,
    scan: bool = True,
    free_m: float = 30.0,
) -> SimObservation:
    extras = _scan(free_m) if scan else {}
    return SimObservation(
        timestamp=now,
        robot=RobotPose(x=robot[0], y=robot[1], yaw=robot[2]),
        owner=OwnerTrack(owner_id="owner-1", x=owner[0], y=owner[1], visible=True, confidence=1.0),
        dynamic_agents=agents,
        **extras,
    )


def _controller(enabled: bool) -> FollowOwnerController:
    controller = FollowOwnerController(
        FollowConfig(),
        yield_aside=FollowYieldConfig(enabled=enabled),
    )
    controller.start("direct")
    return controller


#: A geometry the proposer engages on: a lagging chase with a stranger crossing
#: the un-offset path and open lanes either side.
ENGAGING_AGENTS = (_pedestrian("crossing", 2.0, -1.6, vy=0.5),)


# ---------------------------------------------------------------------------
# (1) flag OFF is the old path
# ---------------------------------------------------------------------------


def test_flag_off_matches_a_controller_built_without_the_parameter() -> None:
    legacy = FollowOwnerController(FollowConfig())
    legacy.start("direct")
    flagged = _controller(enabled=False)
    assert legacy.yield_aside == FollowYieldConfig(enabled=False)
    for tick in range(20):
        observation = _observation(
            robot=(0.1 * tick, 0.0, 0.0),
            owner=(3.4 + 0.05 * tick, 0.0),
            agents=ENGAGING_AGENTS,
            now=1.0 + 0.1 * tick,
        )
        assert legacy.step(observation, now=observation.timestamp) == flagged.step(
            observation, now=observation.timestamp
        )


def test_flag_off_never_builds_the_proposer_limits() -> None:
    assert _controller(enabled=False)._yield_limits is None
    assert _controller(enabled=True)._yield_limits is not None


def test_flag_off_decision_carries_the_idle_yield_telemetry() -> None:
    controller = _controller(enabled=False)
    decision = controller.step(_observation(agents=ENGAGING_AGENTS), now=1.0)
    assert decision.yield_active is False
    assert decision.yield_reason == "idle"
    assert decision.yield_side == 0
    assert decision.yield_offset_m is None
    assert controller.snapshot()["yield_aside"]["enabled"] is False


# ---------------------------------------------------------------------------
# (2) flag ON engages, and only where it should
# ---------------------------------------------------------------------------


def test_flag_on_changes_the_aim_when_a_stranger_crosses_the_path() -> None:
    off = _controller(enabled=False).step(_observation(agents=ENGAGING_AGENTS), now=1.0)
    on = _controller(enabled=True).step(_observation(agents=ENGAGING_AGENTS), now=1.0)
    assert off.yield_active is False
    assert on.yield_active is True
    assert on.yield_reason == "yield_aside"
    assert on.yield_side in (-1, 1)
    assert on.yield_offset_m is not None and on.yield_offset_m > 0.0
    assert on.command != off.command
    # The aim moved, not the distance law: the reported owner distance is the
    # distance to the AIM, which stays on the follow circle about the owner.
    assert on.distance_m != off.distance_m


def test_flag_on_is_inert_without_strangers() -> None:
    off = _controller(enabled=False).step(_observation(), now=1.0)
    on = _controller(enabled=True).step(_observation(), now=1.0)
    # Everything but the telemetry field that names WHY nothing happened.
    assert replace(on, yield_reason=off.yield_reason) == off
    assert on.yield_reason == "no_strangers"


def test_flag_on_is_inert_without_a_scan() -> None:
    off = _controller(enabled=False).step(
        _observation(agents=ENGAGING_AGENTS, scan=False), now=1.0
    )
    on = _controller(enabled=True).step(_observation(agents=ENGAGING_AGENTS, scan=False), now=1.0)
    assert on.command == off.command
    assert on.yield_reason == "no_scan"


def test_flag_on_is_inert_when_the_scan_is_blocked() -> None:
    blocked = _observation(agents=ENGAGING_AGENTS, free_m=0.3)
    off = _controller(enabled=False).step(blocked, now=1.0)
    on = _controller(enabled=True).step(blocked, now=1.0)
    assert on.command == off.command
    assert on.yield_active is False


def test_the_owners_own_track_is_not_treated_as_a_stranger() -> None:
    """A perception stack that publishes the owner as an agent must not trigger."""

    owner_as_agent = (_pedestrian("owner-1", 3.4, 0.0),)
    on = _controller(enabled=True).step(_observation(agents=owner_as_agent), now=1.0)
    assert on.yield_reason == "no_strangers"
    assert on.yield_active is False


def test_engagement_latches_a_side_and_releases_on_recovery() -> None:
    controller = _controller(enabled=True)
    engaged = controller.step(_observation(agents=ENGAGING_AGENTS), now=1.0)
    assert engaged.yield_active
    side = engaged.yield_side
    held = controller.step(_observation(agents=ENGAGING_AGENTS, now=1.1), now=1.1)
    assert held.yield_active and held.yield_side == side
    far = (_pedestrian("crossing", 2.0, -9.0),)
    released = controller.step(_observation(agents=far, now=1.2), now=1.2)
    assert released.yield_active is False
    assert released.yield_reason == "clearance_recovered"
    assert controller._yield_side == 0


# ---------------------------------------------------------------------------
# (3) the proposal is UPSTREAM of the untouched gate
# ---------------------------------------------------------------------------


def test_the_gate_still_disposes_of_the_yielded_command() -> None:
    """The aside proposes an aim; ``apply_reactive_safety`` still decides motion.

    Same fixed command, same observation, gate verdict identical whether or not
    the aside is enabled — the proposal cannot reach the gate's inputs. And the
    command the controller actually derives from a yielded aim is subject to
    that same verdict, including its veto.
    """

    policy = ReactiveSafetyPolicy()
    blocking = _observation(
        agents=ENGAGING_AGENTS,
        owner=(3.4, 0.0),
    )
    # A stranger inside the person stop ring: the gate must refuse translation.
    stopped_observation = SimObservation(
        timestamp=blocking.timestamp,
        robot=blocking.robot,
        owner=blocking.owner,
        dynamic_agents=blocking.dynamic_agents,
        nearest_person_m=0.9,
        nearest_person_bearing_rad=0.0,
        nearest_person_id="crossing",
        lidar_ranges=blocking.lidar_ranges,
        lidar_angle_min_rad=blocking.lidar_angle_min_rad,
        lidar_angle_increment_rad=blocking.lidar_angle_increment_rad,
        lidar_range_min_m=blocking.lidar_range_min_m,
        lidar_range_max_m=blocking.lidar_range_max_m,
    )
    fixed = VelocityCommand(vx=0.3, vyaw=0.0)
    verdict_off = apply_reactive_safety(
        fixed, stopped_observation, policy=policy, now=stopped_observation.timestamp
    )
    verdict_on = apply_reactive_safety(
        fixed, stopped_observation, policy=policy, now=stopped_observation.timestamp
    )
    assert verdict_off == verdict_on
    assert verdict_off[1] == "stopped"

    yielded = _controller(enabled=True).step(
        stopped_observation, now=stopped_observation.timestamp
    )
    assert yielded.yield_active
    gated, state = apply_reactive_safety(
        yielded.command, stopped_observation, policy=policy, now=stopped_observation.timestamp
    )
    assert state == "stopped"
    assert gated.vx == 0.0


def test_the_yielded_aim_stays_on_the_follow_circle_about_the_measured_owner() -> None:
    controller = _controller(enabled=True)
    observation = _observation(agents=ENGAGING_AGENTS)
    decision = controller.step(observation, now=observation.timestamp)
    assert decision.yield_active
    state = controller.snapshot()["yield_aside"]
    owner = observation.owner
    radius = math.hypot(state["aim_x_m"] - owner.x, state["aim_y_m"] - owner.y)
    assert radius == pytest.approx(FollowConfig().desired_distance_m, abs=1e-9)
    assert state["aside_clearance_m"] - state["baseline_clearance_m"] >= MEANINGFUL_IMPROVEMENT_M


def test_an_active_aside_replaces_the_clamped_lead_point() -> None:
    """The documented clamp exemption, asserted rather than assumed.

    ``_clamped_lead`` polices anticipation of a MOVING owner (its budget is
    ``standoff - keepout`` ~ 0.10 m). A yielded aim is a stance rotation at
    constant owner distance, so it replaces the clamped lead outright; what
    polices it instead is the proposer's equilibrium precondition plus the
    untouched gate.
    """

    controller = FollowOwnerController(
        FollowConfig(),
        prediction=FollowPredictionConfig(enabled=True),
        yield_aside=FollowYieldConfig(enabled=True),
    )
    controller.start("direct")
    observation = _observation(agents=ENGAGING_AGENTS)
    prediction = PredictedPath(
        horizon_s=0.9,
        step_s=0.3,
        points=((3.9, 0.0), (4.4, 0.0), (4.9, 0.0)),
        speed_mps=0.5,
        heading_rad=0.0,
        confidence=0.9,
    )
    decision = controller.step(observation, now=observation.timestamp, prediction=prediction)
    assert decision.prediction_active is True
    assert decision.yield_active is True
    state = controller.snapshot()["yield_aside"]
    owner = observation.owner
    # The aim is on the owner circle, NOT on the (clamped) lead point.
    assert math.hypot(
        state["aim_x_m"] - owner.x, state["aim_y_m"] - owner.y
    ) == pytest.approx(FollowConfig().desired_distance_m, abs=1e-9)
    assert (state["aim_x_m"], state["aim_y_m"]) != (decision.lead_x_m, decision.lead_y_m)


# ---------------------------------------------------------------------------
# config plumbing
# ---------------------------------------------------------------------------


def test_follow_config_still_rejects_the_nested_yield_block() -> None:
    """Why runtime.py and the bench runner must POP the block before merging."""

    with pytest.raises(ValueError, match="unknown owner_follow settings"):
        FollowConfig.from_mapping({"yield_aside": {"enabled": True}})


def test_yield_config_from_mapping_is_strict() -> None:
    assert FollowYieldConfig.from_mapping({}) == FollowYieldConfig(enabled=False)
    assert FollowYieldConfig.from_mapping({"enabled": True}).enabled is True
    with pytest.raises(ValueError, match="unknown owner_follow.yield_aside settings"):
        FollowYieldConfig.from_mapping({"enable": True})
    with pytest.raises(TypeError):
        FollowYieldConfig.from_mapping({"enabled": 1})


def test_bench_runner_plumbs_the_flag_from_its_feature_switch() -> None:
    from evals.companion_nav.runner import BenchFeatures, _follow_config_from_store

    class _Store:
        def __init__(self, follow: dict) -> None:
            self._follow = follow

        def section(self, name: str) -> dict:
            if name == "safety":
                return {"person_stop_m": 1.2, "person_slow_m": 2.5}
            if name == "owner_follow":
                return dict(self._follow)
            return {}

    class _Spatial:
        owner_collision_envelope_m = 0.55

    config, prediction, yield_aside = _follow_config_from_store(
        _Store({"owner_keepout_m": 1.75}), _Spatial()
    )
    assert config.owner_keepout_m == 1.75
    assert prediction.enabled is False
    assert yield_aside.enabled is False
    _, _, enabled = _follow_config_from_store(
        _Store({"owner_keepout_m": 1.75, "yield_aside": {"enabled": True}}), _Spatial()
    )
    assert enabled.enabled is True
    assert BenchFeatures().yield_aside is False
    assert BenchFeatures.baseline().yield_aside is False


def test_runtime_pops_the_yield_block_before_the_follow_merge() -> None:
    """The runtime plumb, read from the source it must mirror (runtime.py:528)."""

    from pathlib import Path

    source = Path("src/parcel_robot/runtime.py").read_text(encoding="utf-8")
    assert 'raw_yield = follow_config.pop("yield_aside", {})' in source
    assert "FollowYieldConfig.from_mapping(raw_yield)" in source
    assert "yield_aside=follow_yield," in source
    # And no shipped configuration turns it on.
    for config in Path("configs").rglob("*.yaml"):
        assert "yield_aside" not in config.read_text(encoding="utf-8"), config
