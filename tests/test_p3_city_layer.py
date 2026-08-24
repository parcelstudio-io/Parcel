"""P3 city-layer: GNSS model, OSM/Overture fixtures, crossing geofence."""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, EvidenceEnvelopeV1
from parcel_robot.gnss.injector import DOES_NOT_PROVE as GNSS_DOES_NOT_PROVE
from parcel_robot.gnss.injector import EXTRAS_KEY as GNSS_EXTRAS_KEY
from parcel_robot.gnss.injector import SimGnssInjector, SimGnssPose, gnss_from_extras
from parcel_robot.gnss.model import DEFAULT_GNSS_TTL_NS, GnssNoiseModel, GroundTruthGnss
from parcel_robot.gnss.noise import (
    GnssDropoutSchedule,
    GnssDropoutWindow,
    GnssNoiseConfig,
    schedule_from_windows,
)
from parcel_robot.gnss.sample import GnssFix
from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.maps import (
    DOES_NOT_PROVE as MAPS_DOES_NOT_PROVE,
)
from parcel_robot.maps.crossing import (
    CrossingModePolicy,
    CrossingPolicyConfig,
    CrossingState,
    decision_blocks_autonomous_road,
)
from parcel_robot.maps.graph import load_footway_crossing_graph
from parcel_robot.maps.overture import OvertureTileClient, load_overture_tile
from parcel_robot.maps.waypoints import PROPOSER_SOURCE, OsmWaypointProposer


def _envelope(
    *,
    evidence_id: str = "g-1",
    received: int = 1_000_000,
    ttl_ns: int = DEFAULT_GNSS_TTL_NS,
) -> EvidenceEnvelopeV1:
    return EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        source="test",
        source_timestamp_ns=received,
        received_monotonic_ns=received,
        sequence=1,
        frame_id="map",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=received, ttl_ns=ttl_ns
        ),
        calibration_id="test-cal",
        provenance=("test",),
    )


# --- GNSS -----------------------------------------------------------------


def test_gnss_dropout_schedule_windows_and_period() -> None:
    schedule = schedule_from_windows([(2, 4)], period_ticks=10, burst_ticks=2)
    assert schedule.is_dropout(2)
    assert schedule.is_dropout(3)
    assert not schedule.is_dropout(4)
    assert schedule.is_dropout(0)
    assert not schedule.is_dropout(5)


def test_gnss_bernoulli_requires_draw() -> None:
    schedule = GnssDropoutSchedule(p_dropout=0.5)
    with pytest.raises(ValueError, match="rng_draw"):
        schedule.is_dropout(0)
    assert schedule.is_dropout(0, rng_draw=0.1)
    assert not schedule.is_dropout(0, rng_draw=0.9)


def test_gnss_fix_round_trip_and_freshness() -> None:
    fix = GnssFix(
        envelope=_envelope(),
        east_m=1.0,
        north_m=2.0,
        cov_east_m2=2.25,
        cov_north_m2=2.25,
        cov_cross_m2=0.0,
        hdop=1.2,
        num_sats=12,
        fix_type="3d",
        horizontal_std_m=1.5,
    )
    restored = GnssFix.from_mapping(fix.as_dict())
    assert restored == fix
    fix.require_fresh(1_000_000)
    assert fix.expired(1_000_000 + DEFAULT_GNSS_TTL_NS)
    payload = fix.bag_payload()
    assert "oracle" not in payload
    assert payload["schema_version"] == SCHEMA_VERSION
    assert fix.usable(max_horizontal_std_m=5.0)
    assert not fix.usable(max_horizontal_std_m=1.0)


def test_gnss_noise_model_deterministic_jitter() -> None:
    model = GnssNoiseModel(
        GnssNoiseConfig(
            east_jitter_std_m=0.5,
            north_jitter_std_m=0.5,
            hdop_jitter_std=0.0,
            dropout=GnssDropoutSchedule(),
        )
    )
    truth = GroundTruthGnss(east_m=10.0, north_m=-3.0)
    a = model.observe(truth, rng=random.Random(11), received_monotonic_ns=100)
    model.reset()
    b = model.observe(truth, rng=random.Random(11), received_monotonic_ns=100)
    assert a is not None and b is not None
    assert a.east_m == b.east_m
    assert a.north_m == b.north_m
    assert a.envelope.provenance == ("gnss_noise_model_v1",)
    assert abs(a.east_m - 10.0) > 0.0 or abs(a.north_m + 3.0) > 0.0


def test_gnss_scheduled_dropouts_and_cov_inflation() -> None:
    model = GnssNoiseModel(
        GnssNoiseConfig(
            east_jitter_std_m=0.0,
            north_jitter_std_m=0.0,
            hdop_jitter_std=0.0,
            cov_east_m2=1.0,
            cov_north_m2=1.0,
            post_dropout_cov_scale=4.0,
            post_dropout_inflate_ticks=2,
            dropout=GnssDropoutSchedule(windows=(GnssDropoutWindow(1, 2),)),
        )
    )
    truth = GroundTruthGnss(east_m=0.0, north_m=0.0)
    rng = random.Random(0)
    s0 = model.observe(truth, rng=rng, received_monotonic_ns=10)
    s1 = model.observe(truth, rng=rng, received_monotonic_ns=20)
    s2 = model.observe(truth, rng=rng, received_monotonic_ns=30)
    s3 = model.observe(truth, rng=rng, received_monotonic_ns=40)
    s4 = model.observe(truth, rng=rng, received_monotonic_ns=50)
    assert s0 is not None and s0.cov_east_m2 == pytest.approx(1.0)
    assert s1 is None
    assert s2 is not None and s2.cov_east_m2 == pytest.approx(4.0)
    assert s3 is not None and s3.cov_east_m2 == pytest.approx(4.0)
    assert s4 is not None and s4.cov_east_m2 == pytest.approx(1.0)


def test_sim_gnss_injector_extras_round_trip() -> None:
    injector = SimGnssInjector(
        GnssNoiseModel(
            GnssNoiseConfig(
                east_jitter_std_m=0.0,
                north_jitter_std_m=0.0,
                hdop_jitter_std=0.0,
            )
        )
    )
    obs = SimObservation(
        timestamp=1.0,
        robot=RobotPose(x=3.0, y=-1.0, yaw=0.0),
        owner=OwnerTrack(owner_id="owner-1", x=0.0, y=0.0, visible=True, confidence=1.0),
        backend="headless",
    )
    extras: dict[str, object] = {}
    sample = injector.observe_and_inject(
        obs, extras, rng=random.Random(2), received_monotonic_ns=1_000_000_000
    )
    assert sample is not None
    assert extras[GNSS_EXTRAS_KEY]["dropout"] is False  # type: ignore[index]
    assert extras[GNSS_EXTRAS_KEY]["east_m"] == pytest.approx(3.0)  # type: ignore[index]
    restored = gnss_from_extras(extras)
    assert restored is not None
    assert restored.north_m == pytest.approx(-1.0)


def test_sim_gnss_injector_records_dropout() -> None:
    injector = SimGnssInjector(
        GnssNoiseModel(
            GnssNoiseConfig(dropout=GnssDropoutSchedule(windows=(GnssDropoutWindow(0, 1),)))
        )
    )
    extras: dict[str, object] = {}
    sample = injector.sample_from_pose(
        SimGnssPose(east_m=0.0, north_m=0.0),
        rng=random.Random(0),
        received_monotonic_ns=1,
    )
    injector.inject_extras(extras, sample)
    assert sample is None
    assert extras[GNSS_EXTRAS_KEY] == {"dropout": True, "schema_version": 1}
    assert gnss_from_extras(extras) is None


def test_gnss_does_not_prove_honesty() -> None:
    assert any("HR-3" in line for line in GNSS_DOES_NOT_PROVE)


def test_gnss_config_frozen() -> None:
    cfg = GnssNoiseConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.east_jitter_std_m = 0.1  # type: ignore[misc]


# --- OSM / Overture -------------------------------------------------------


def test_load_neighborhood_fixture_and_pathfind() -> None:
    graph = load_footway_crossing_graph()
    assert graph.fixture_id == "neighborhood-v1-sim"
    assert graph.road_keepout is not None
    assert graph.is_road_keepout(30.0, 0.0)
    assert not graph.is_road_keepout(0.0, 5.0)

    # Same-side path without crossing.
    path = graph.path_waypoints((0.0, 5.0), (50.0, 5.0), allow_crossing=False)
    assert path is not None
    assert path[0] == pytest.approx((0.0, 5.0))
    assert path[-1] == pytest.approx((50.0, 5.0))

    # Opposite sidewalk requires crossing edges — blocked by default.
    blocked = graph.path_waypoints((0.0, 5.0), (0.0, -5.0), allow_crossing=False)
    assert blocked is None
    allowed = graph.path_waypoints((0.0, 5.0), (0.0, -5.0), allow_crossing=True)
    assert allowed is not None
    assert any(abs(p[1]) < 1e-9 for p in allowed)  # passes through crossing mid


def test_osm_waypoint_proposer_emits_se2_goal() -> None:
    graph = load_footway_crossing_graph()
    proposer = OsmWaypointProposer(graph)
    goal = proposer.propose(
        now_s=10.0,
        robot_x=0.0,
        robot_y=5.0,
        goal_x=50.0,
        goal_y=5.0,
        allow_crossing=False,
    )
    assert goal is not None
    assert goal.source == PROPOSER_SOURCE
    assert goal.pose is not None
    assert goal.waypoints

    # Road keepout goal without crossing auth → None (fail-closed).
    assert (
        proposer.propose(
            now_s=10.0,
            robot_x=0.0,
            robot_y=5.0,
            goal_x=30.0,
            goal_y=0.0,
            allow_crossing=False,
        )
        is None
    )


def test_osm_proposer_registers_on_goal_arbiter() -> None:
    graph = load_footway_crossing_graph()
    proposer = OsmWaypointProposer(graph, priority=4)
    bus = ProposerBus()
    bus.register(
        PROPOSER_SOURCE,
        proposer.as_bus_proposer(goal_x=50.0, goal_y=5.0, allow_crossing=False),
    )
    arbiter = GoalArbiter(lethal_cost=lambda x, y: graph.is_road_keepout(x, y))
    goals = bus.poll(now_s=1.0, context={"robot_x": 0.0, "robot_y": 5.0})
    winner = arbiter.resolve(goals, now_s=1.0)
    assert winner is not None
    assert winner.source == PROPOSER_SOURCE
    assert isinstance(winner, SE2Goal)


def test_overture_tile_client_offline_query() -> None:
    client = OvertureTileClient()
    tile = client.fetch_tile()
    assert tile.fixture_id == "overture-places-v1-sim"
    near = tile.query_near(8.0, 7.0, radius_m=5.0)
    assert len(near) >= 1
    assert near[0].brand == "Parcel Roast"
    matches = tile.match_brand_text("green cross pharmacy")
    assert matches and matches[0].id == "plc_pharmacy_1"
    with pytest.raises(LookupError, match="offline"):
        client.fetch_tile("not-a-real-tile")


def test_overture_load_matches_client() -> None:
    tile = load_overture_tile()
    assert any(p.category == "cafe" for p in tile.places)


# --- Crossing / curb geofence ---------------------------------------------


def test_crossing_curb_stop_awaits_voice() -> None:
    graph = load_footway_crossing_graph()
    policy = CrossingModePolicy(graph)
    # Approach north curb at (30, 5).
    d0 = policy.evaluate(robot_x=30.0, robot_y=6.5, now_s=0.0)
    assert d0.state is CrossingState.APPROACHING_CURB
    assert not d0.allow_crossing_edges

    d1 = policy.evaluate(robot_x=30.0, robot_y=5.2, now_s=1.0)
    assert d1.state is CrossingState.CURB_STOPPED
    assert d1.stop_required
    assert d1.announcement is not None
    assert "go" in d1.announcement.lower()
    assert decision_blocks_autonomous_road(d1)

    # No voice → still blocked; crossing edges off.
    d2 = policy.evaluate(
        robot_x=30.0,
        robot_y=5.1,
        now_s=2.0,
        proposed_goal_xy=(30.0, 0.0),
    )
    assert d2.state is CrossingState.CURB_STOPPED
    assert d2.reason == "goal_in_road_keepout_without_voice"
    assert not d2.allow_crossing_edges


def test_crossing_voice_initiation_required_and_pins_zero_autonomous_entry() -> None:
    graph = load_footway_crossing_graph()
    policy = CrossingModePolicy(graph)
    policy.evaluate(robot_x=30.0, robot_y=5.1, now_s=0.0)
    assert policy.state is CrossingState.CURB_STOPPED

    # Wrong phrase / autonomous attempt.
    assert not policy.request_voice_initiation("just walk across", now_s=1.0)
    assert policy.state is CrossingState.CURB_STOPPED
    assert not policy.may_enter_road()

    # Accepted companion phrase.
    assert policy.request_voice_initiation("go", now_s=1.0)
    assert policy.state is CrossingState.CROSSING_AUTHORIZED
    assert policy.may_enter_road()

    d = policy.evaluate(robot_x=30.0, robot_y=5.1, now_s=2.0, proposed_goal_xy=(30.0, 0.0))
    assert d.state is CrossingState.CROSSING_AUTHORIZED
    assert d.allow_crossing_edges
    assert not decision_blocks_autonomous_road(d)

    # Proposer may now include crossing edges.
    proposer = OsmWaypointProposer(graph)
    goal = proposer.propose(
        now_s=2.0,
        robot_x=0.0,
        robot_y=5.0,
        goal_x=0.0,
        goal_y=-5.0,
        allow_crossing=policy.allow_crossing_edges(),
    )
    assert goal is not None


def test_crossing_blocks_robot_already_in_road_without_auth() -> None:
    graph = load_footway_crossing_graph()
    policy = CrossingModePolicy(graph)
    d = policy.evaluate(robot_x=30.0, robot_y=0.0, now_s=0.0)
    assert d.state is CrossingState.BLOCKED
    assert d.stop_required
    assert d.reason == "autonomous_road_entry_blocked"
    assert not policy.may_enter_road()


def test_crossing_rejects_voice_when_not_at_curb() -> None:
    graph = load_footway_crossing_graph()
    policy = CrossingModePolicy(graph)
    policy.evaluate(robot_x=0.0, robot_y=5.0, now_s=0.0)
    assert policy.state is CrossingState.SIDEWALK
    assert not policy.request_voice_initiation("go", now_s=1.0)


def test_crossing_authorization_ttl_expires() -> None:
    graph = load_footway_crossing_graph()
    policy = CrossingModePolicy(
        graph, config=CrossingPolicyConfig(authorization_ttl_s=5.0)
    )
    policy.evaluate(robot_x=30.0, robot_y=5.1, now_s=0.0)
    assert policy.request_voice_initiation("let's go", now_s=1.0)
    d = policy.evaluate(robot_x=30.0, robot_y=5.1, now_s=10.0)
    assert d.state is CrossingState.CURB_STOPPED
    assert not d.allow_crossing_edges


def test_maps_does_not_prove_honesty() -> None:
    assert MAPS_DOES_NOT_PROVE
    assert any("HR-10" in line or "HR-11" in line for line in MAPS_DOES_NOT_PROVE)
