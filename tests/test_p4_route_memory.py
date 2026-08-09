"""P4 route memory / teach-and-repeat / CityWalker / VLFM stubs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
from parcel_robot.instructnav.search_entity import (
    FrontierCandidate,
    select_frontier,
)
from parcel_robot.route_memory import (
    CITYWALKER_PROPOSER_SOURCE,
    DOES_NOT_PROVE,
    EXTRAS_KEY,
    PROPOSER_SOURCE,
    CityWalkerAdapterConfig,
    CityWalkerInferenceAdapter,
    CityWalkerObservation,
    HeuristicValueMap,
    HeuristicVLFMScorer,
    RouteKeyframe,
    RouteMemoryProposer,
    RouteMemoryRuntimeHook,
    RouteMemoryStore,
    StubVPREmbedder,
    TeachRepeatSession,
    ValueMapCell,
    cosine_similarity,
    goal_from_path_snapshot,
    load_cached_walk,
    match_keyframe_index,
    resolve_citywalker_vendor,
)


# --- Route memory store -----------------------------------------------------


def test_route_keyframe_and_path_roundtrip(tmp_path: Path) -> None:
    store = RouteMemoryStore(root=tmp_path)
    kfs = (
        RouteKeyframe(x=0.0, y=0.0, yaw_rad=0.0, t_s=0.0, embedding=(0.1, 0.2)),
        RouteKeyframe(x=1.0, y=0.0, yaw_rad=0.0, t_s=0.1),
        RouteKeyframe(x=2.0, y=1.0, yaw_rad=0.5, t_s=0.2),
    )
    path = store.record(kfs, path_id="loop-a", name="morning")
    assert path.path_id == "loop-a"
    assert len(path.waypoints_xy()) == 3
    saved = store.save("loop-a")
    store2 = RouteMemoryStore()
    loaded = store2.load(saved)
    assert loaded.path_id == "loop-a"
    assert loaded.keyframes[0].embedding == (0.1, 0.2)
    assert loaded.does_not_prove
    assert any("teach-and-repeat" in s.lower() for s in loaded.does_not_prove)


def test_teach_and_follow_gated_by_default() -> None:
    session = TeachRepeatSession()
    path = session.teach([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.5, 0.2)], path_id="p1")
    assert path.path_id == "p1"
    assert all(kf.embedding for kf in path.keyframes)  # stub VPR filled

    gated = session.follow("p1")  # gate_enabled=False
    assert gated.propose(now_s=1.0, robot_x=0.0, robot_y=0.0) is None

    active = session.follow("p1", gate_enabled=True)
    goal = active.propose(now_s=1.0, robot_x=0.0, robot_y=0.0)
    assert isinstance(goal, SE2Goal)
    assert goal.source == PROPOSER_SOURCE
    assert goal.ttl_s == 2.0
    assert goal.pose is not None
    assert goal.issued_s == 1.0


def test_incremental_teach_and_vpr_match() -> None:
    session = TeachRepeatSession(embedder=StubVPREmbedder(dim=32))
    session.begin_teach(name="inc")
    session.append_pose((0.0, 0.0, 0.0), t_s=0.0, frame_id="f0")
    session.append_pose((1.0, 0.0, 0.0), t_s=0.1, frame_bytes=b"rgb-ish")
    path = session.end_teach(path_id="inc-1")
    assert path.name == "inc"
    emb = StubVPREmbedder(dim=32).embed(pose=(0.0, 0.0, 0.0), frame_id="f0")
    idx = match_keyframe_index(emb, [kf.embedding for kf in path.keyframes])
    assert idx == 0
    assert cosine_similarity(emb, path.keyframes[0].embedding) > 0.99


def test_route_memory_proposer_into_goal_arbiter() -> None:
    session = TeachRepeatSession()
    session.teach([(0.0, 0.0), (3.0, 0.0), (3.0, 3.0)], path_id="square")
    proposer = session.follow("square", gate_enabled=True, priority=5, ttl_s=1.5)
    bus = ProposerBus()
    bus.register(PROPOSER_SOURCE, proposer.as_bus_proposer())
    arbiter = GoalArbiter(lethal_cost=lambda x, y: x < -10.0)
    goals = bus.poll(now_s=10.0, context={"robot_x": 0.1, "robot_y": 0.0})
    winner = arbiter.resolve(goals, now_s=10.0)
    assert winner is not None
    assert winner.source == PROPOSER_SOURCE
    assert not winner.expired(10.5)
    assert winner.expired(12.0)

    # Snapshot helper also respects gate.
    assert goal_from_path_snapshot(session.store.require("square"), now_s=1.0) is None
    snap = goal_from_path_snapshot(
        session.store.require("square"), now_s=1.0, gate_enabled=True
    )
    assert snap is not None and snap.pose is not None


def test_terminal_arrival_stops_proposals() -> None:
    path = RouteMemoryStore().record(
        [
            RouteKeyframe(0.0, 0.0, 0.0),
            RouteKeyframe(1.0, 0.0, 0.0),
        ],
        path_id="short",
    )
    proposer = RouteMemoryProposer(path=path, gate_enabled=True, arrive_tol_m=0.4)
    assert proposer.propose(now_s=0.0, robot_x=1.0, robot_y=0.0) is None


# --- CityWalker -------------------------------------------------------------


def test_citywalker_gate_and_fail_closed_without_velocity() -> None:
    adapter = CityWalkerInferenceAdapter(CityWalkerAdapterConfig(gate_enabled=False))
    obs = CityWalkerObservation(
        robot_x=0.0,
        robot_y=0.0,
        cached_waypoints=((1.0, 0.0), (2.0, 0.0)),
    )
    result = adapter.propose(obs, now_s=1.0)
    assert result.status == "skipped"
    assert result.reason == "gate_disabled"
    assert result.goal is None
    assert result.unverified is True


def test_citywalker_cached_offline_when_gated_and_vendor_present() -> None:
    vendor = resolve_citywalker_vendor()
    if vendor is None:
        pytest.skip("third_party/CityWalker not present in this checkout")
    adapter = CityWalkerInferenceAdapter(
        CityWalkerAdapterConfig(
            gate_enabled=True,
            require_checkpoint=False,
            require_torch=False,
        )
    )
    obs = CityWalkerObservation(
        robot_x=0.0,
        robot_y=0.0,
        cached_waypoints=((1.0, 0.0), (2.0, 0.5)),
    )
    result = adapter.propose(obs, now_s=2.0)
    assert result.status == "ready"
    assert result.goal is not None
    assert result.goal.source == CITYWALKER_PROPOSER_SOURCE
    assert result.goal.pose is not None
    # Never a velocity command shape.
    assert "vx" not in result.goal.as_dict()
    assert "cmd_vel" not in result.as_dict()


def test_citywalker_skips_live_inference_honestly() -> None:
    vendor = resolve_citywalker_vendor()
    if vendor is None:
        pytest.skip("third_party/CityWalker not present in this checkout")
    adapter = CityWalkerInferenceAdapter(
        CityWalkerAdapterConfig(
            gate_enabled=True,
            require_checkpoint=False,
            require_torch=False,
            allow_cached_offline=True,
        )
    )
    # No cached waypoints → live path → UNVERIFIED skip (CI-safe).
    result = adapter.propose(
        CityWalkerObservation(robot_x=0.0, robot_y=0.0),
        now_s=0.0,
    )
    assert result.status == "skipped"
    assert "UNVERIFIED" in result.reason
    assert result.goal is None


def test_citywalker_rejects_huge_cached_step() -> None:
    vendor = resolve_citywalker_vendor()
    if vendor is None:
        pytest.skip("third_party/CityWalker not present")
    adapter = CityWalkerInferenceAdapter(
        CityWalkerAdapterConfig(
            gate_enabled=True,
            require_checkpoint=False,
            require_torch=False,
            max_waypoint_step_m=2.0,
        )
    )
    result = adapter.propose(
        CityWalkerObservation(
            robot_x=0.0,
            robot_y=0.0,
            cached_waypoints=((10.0, 0.0),),
        ),
        now_s=0.0,
    )
    assert result.status == "error"
    assert result.goal is None


def test_load_cached_walk_roundtrip(tmp_path: Path) -> None:
    payload = {
        "observations": [
            {
                "robot_x": 0.0,
                "robot_y": 0.0,
                "robot_yaw": 0.1,
                "cached_waypoints": [[0.5, 0.0], [1.0, 0.0]],
                "t_s": 0.0,
            }
        ]
    }
    file_path = tmp_path / "walk.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    obs = load_cached_walk(file_path)
    assert len(obs) == 1
    assert obs[0].cached_waypoints == ((0.5, 0.0), (1.0, 0.0))


# --- VLFM scorer ------------------------------------------------------------


def test_heuristic_vlfm_feeds_search_entity() -> None:
    value_map = HeuristicValueMap(
        cells=(
            ValueMapCell(x=4.0, y=0.0, value=0.95, label="sidewalk"),
            ValueMapCell(x=0.0, y=4.0, value=0.1, label="road"),
        ),
        radius_m=3.0,
    )
    scorer = HeuristicVLFMScorer(value_map=value_map, travel_weight=0.05)
    assert "UNVERIFIED" in scorer.label
    candidates = (
        FrontierCandidate(x=4.0, y=0.0, geodesic_cost_m=4.0, semantic_prior=0.5, candidate_id="a"),
        FrontierCandidate(x=0.0, y=4.0, geodesic_cost_m=1.0, semantic_prior=0.5, candidate_id="b"),
    )
    best = select_frontier(candidates, scorer=scorer)
    assert best is not None
    assert best.candidate_id == "a"  # high value map beats closer low-value cell
    meta = scorer.as_dict()
    assert meta["unverified"] is True
    assert meta["does_not_prove"]


def test_value_map_from_label_priors() -> None:
    vm = HeuristicValueMap.from_label_priors({(1.0, 2.0): "sidewalk", (3.0, 0.0): "road"})
    assert vm.value_at(1.0, 2.0) == pytest.approx(0.95)
    assert vm.value_at(3.0, 0.0) == pytest.approx(0.08)


# --- Runtime hook -----------------------------------------------------------


def test_runtime_hook_extras_and_does_not_prove() -> None:
    hook = RouteMemoryRuntimeHook()
    path_id = hook.teach_poses([(0.0, 0.0), (1.0, 1.0)], path_id="hook-1")
    hook.arm_follow(path_id, gate_enabled=True)
    goal = hook.propose_route(now_s=1.0, robot_x=0.0, robot_y=0.0)
    assert isinstance(goal, SE2Goal)
    extras: dict = {}
    hook.inject_extras(extras, now_s=1.0)
    assert EXTRAS_KEY in extras
    assert extras[EXTRAS_KEY]["active_path_id"] == "hook-1"
    assert extras[EXTRAS_KEY]["gate_enabled"] is True
    assert DOES_NOT_PROVE
    assert extras[EXTRAS_KEY]["does_not_prove"]
