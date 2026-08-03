from __future__ import annotations

import ast
import io
import json
import math
from pathlib import Path

import numpy as np
import pytest

from evals.external.habitat2020_doctor import (
    MANIFEST_PATH,
    REPO_ROOT,
    audit_habitat2020,
    load_manifest,
)
from evals.external.habitat2020_py36_bridge import (
    PROTOCOL_VERSION,
    BridgeProtocolError,
    NominalActionOdometry,
    PointNav2020Bridge,
    decode_message,
    depth_to_planar_scan,
    encode_message,
    pointgoal_polar_to_local,
)
from evals.external.habitat2020_sidecar import ParcelPointNavSidecar, serve
from parcel_robot.navigation.base import MidLevelCommand, Mission, NavObservation


class _FakeTransport:
    def __init__(self, commands: list[dict[str, object]]) -> None:
        self.commands = list(commands)
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def request(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        if request["op"] == "start":
            return {
                "schema_version": PROTOCOL_VERSION,
                "op": "started",
                "episode_id": request["episode_id"],
            }
        command = dict(self.commands.pop(0))
        command.update(
            {
                "schema_version": PROTOCOL_VERSION,
                "op": "command",
                "episode_id": request["episode_id"],
                "step_id": request["step_id"],
            }
        )
        return command

    def close(self) -> None:
        self.closed = True


class _FakeController:
    def __init__(self, command: MidLevelCommand | None = None) -> None:
        self.command = command or MidLevelCommand(vx=0.25, note="fake_forward")
        self.mission: Mission | None = None
        self.observations: list[NavObservation] = []
        self.closed = False

    def start(self, directive: str | Mission) -> Mission:
        assert isinstance(directive, Mission)
        self.mission = directive
        self.mission.status = "running"
        return self.mission

    def step(self, observation: NavObservation) -> MidLevelCommand:
        self.observations.append(observation)
        return self.command

    def close(self) -> None:
        self.closed = True


def _command(*, vx: float = 0.0, vy: float = 0.0, vyaw: float = 0.0, stop: bool = False):
    return {"vx": vx, "vy": vy, "vyaw": vyaw, "stop": stop, "note": "test"}


def _observations() -> dict[str, np.ndarray]:
    return {
        "pointgoal": np.array([2.0, math.pi / 2.0], dtype=np.float32),
        "depth": np.full((12, 20, 1), 0.5, dtype=np.float32),
        "rgb": np.zeros((12, 20, 3), dtype=np.uint8),
    }


def test_manifest_freezes_ineligible_official_code_contract() -> None:
    manifest = load_manifest()

    assert manifest["challenge_source"]["commit"] == (
        "ddf1575532aecc4df2f4cd4c5db173b8eada3e1e"
    )
    assert manifest["container"]["base_digest"] == (
        "sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b"
    )
    assert manifest["eligibility"]["official_rank_eligible"] is False
    assert manifest["eligibility"]["leaderboard_comparable"] is False
    assert manifest["task"]["success_distance_m"] == 0.36
    assert manifest["task"]["sensors"]["goal"]["updated_with_ground_truth_pose"] is False
    assert "simulator_agent_state" in manifest["adapter"]["privileged_inputs_forbidden"]


def test_doctor_confirms_pinned_source_and_reports_every_blocker_explicitly() -> None:
    report = audit_habitat2020()
    checks = {check["id"]: check for check in report["checks"]}

    assert report["official_rank_eligible"] is False
    assert report["leaderboard_comparable"] is False
    assert checks["source_lock"]["ready"] is True
    assert checks["pinned_checkout"]["ready"] is True
    assert checks["immutable_checkout"]["ready"] is True
    assert checks["official_task_config"]["ready"] is True
    assert checks["public_minival_episodes"]["ready"] is True
    assert checks["public_minival_shape"]["ready"] is True
    assert checks["python36_bridge_grammar"]["ready"] is True
    assert report["ready"] == (not report["blockers"])
    assert all(blocker["remediation"] for blocker in report["blockers"])
    assert report["policy"]["no_silent_fallback"] is True


def test_archived_bridge_really_parses_with_python36_grammar() -> None:
    bridge_path = REPO_ROOT / "evals/external/habitat2020_py36_bridge.py"
    tree = ast.parse(
        bridge_path.read_text(encoding="utf-8"),
        filename=str(bridge_path),
        feature_version=(3, 6),
    )

    assert tree is not None
    assert MANIFEST_PATH.is_file()


def test_static_pointgoal_uses_forward_left_local_convention() -> None:
    forward, left = pointgoal_polar_to_local((2.0, math.pi / 2.0))

    assert forward == pytest.approx(0.0, abs=1e-12)
    assert left == pytest.approx(2.0)
    with pytest.raises(BridgeProtocolError, match="non-negative"):
        pointgoal_polar_to_local((-1.0, 0.0))


def test_depth_projection_is_calibrated_uniform_and_has_no_phantom_max_ring() -> None:
    depth = np.full((9, 101, 1), 0.5, dtype=np.float32)
    scan = depth_to_planar_scan(depth, bins=11)

    assert len(scan["ranges_m"]) == 11
    assert scan["angle_min_rad"] == pytest.approx(-math.radians(35.0))
    assert scan["angle_increment_rad"] == pytest.approx(math.radians(7.0))
    assert scan["ranges_m"][5] == pytest.approx(5.05)
    assert scan["ranges_m"][0] == pytest.approx(5.05 / math.cos(math.radians(35.0)))
    assert scan["ranges_m"][-1] == pytest.approx(scan["ranges_m"][0])

    saturated = depth_to_planar_scan(np.ones((9, 101), dtype=np.float32), bins=11)
    assert saturated["ranges_m"] == [None] * 11
    encoded = encode_message(
        {"schema_version": PROTOCOL_VERSION, "op": "scan", "scan": saturated}
    )
    assert "Infinity" not in encoded
    assert "null" in encoded


def test_depth_projection_fails_closed_on_bad_calibration_or_shape() -> None:
    with pytest.raises(BridgeProtocolError, match="shape"):
        depth_to_planar_scan(np.ones((10,), dtype=np.float32))
    with pytest.raises(BridgeProtocolError, match=r"\[0, 1\]"):
        depth_to_planar_scan(np.full((4, 4), 1.5, dtype=np.float32))
    with pytest.raises(BridgeProtocolError, match="hfov"):
        depth_to_planar_scan(np.ones((4, 4), dtype=np.float32), hfov_deg=180.0)


def test_json_line_protocol_rejects_nonfinite_or_wrong_schema() -> None:
    line = encode_message({"schema_version": PROTOCOL_VERSION, "op": "test", "value": 1})
    assert decode_message(line)["value"] == 1
    with pytest.raises(BridgeProtocolError, match="strict JSON"):
        encode_message({"schema_version": PROTOCOL_VERSION, "value": math.inf})
    with pytest.raises(BridgeProtocolError, match="schema_version"):
        decode_message('{"schema_version":99,"op":"test"}\n')


def test_nominal_odometry_uses_only_issued_action_history() -> None:
    odometry = NominalActionOdometry()
    odometry.integrate("TURN_LEFT")
    odometry.integrate("MOVE_FORWARD")

    assert odometry.heading_rad == pytest.approx(math.radians(30.0))
    assert odometry.x_m == pytest.approx(0.25 * math.cos(math.radians(30.0)))
    assert odometry.y_m == pytest.approx(0.25 * math.sin(math.radians(30.0)))
    with pytest.raises(BridgeProtocolError, match="unsupported"):
        odometry.integrate("TELEPORT")


def test_bridge_sends_no_privileged_state_and_integrates_previous_action() -> None:
    transport = _FakeTransport(
        [
            _command(vyaw=0.5),
            _command(vx=0.3),
            _command(stop=True),
        ]
    )
    bridge = PointNav2020Bridge(transport, scan_bins=9)
    bridge.reset()
    observations = _observations()

    assert bridge.act(observations) == {"action": "TURN_LEFT"}
    assert bridge.act(observations) == {"action": "MOVE_FORWARD"}
    assert bridge.act(observations) == {"action": "STOP"}

    start, first, second, third = transport.requests
    assert start["goal"]["x_m"] == pytest.approx(0.0, abs=1e-6)
    assert start["goal"]["y_m"] == pytest.approx(2.0)
    assert set(first) == {
        "schema_version",
        "op",
        "episode_id",
        "step_id",
        "pose",
        "scan",
        "sensor_contract",
    }
    assert first["pose"] == {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0}
    assert second["pose"]["heading_rad"] == pytest.approx(math.radians(30.0))
    assert third["pose"]["x_m"] > 0.0
    assert third["pose"]["y_m"] > 0.0
    assert first["sensor_contract"] == {
        "depth_present": True,
        "rgb_present": True,
        "gps_compass_present": False,
    }
    forbidden = {
        "simulator_agent_state",
        "navmesh",
        "geodesic_distance",
        "shortest_path",
        "collision_truth",
        "evaluation_metrics",
    }
    assert forbidden.isdisjoint(first)
    bridge.close()
    assert transport.closed
@pytest.mark.parametrize(
    ("command", "match"),
    [
        (_command(vy=0.01), "lateral"),
        (_command(vx=-0.01), "reverse"),
    ],
)
def test_bridge_refuses_to_hide_actions_missing_from_official_space(
    command: dict[str, object],
    match: str,
) -> None:
    bridge = PointNav2020Bridge(_FakeTransport([command]), scan_bins=9)
    bridge.reset()

    with pytest.raises(BridgeProtocolError, match=match):
        bridge.act(_observations())


def test_sidecar_maps_strict_sensor_request_to_unchanged_controller_contract() -> None:
    controller = _FakeController(MidLevelCommand(vx=0.2, vyaw=0.1, note="fake"))
    sidecar = ParcelPointNavSidecar(controller=controller)
    started = sidecar.handle(
        {
            "schema_version": PROTOCOL_VERSION,
            "op": "start",
            "episode_id": 1,
            "goal": {"x_m": 3.0, "y_m": -1.0},
            "arrival_radius_m": 0.30,
        }
    )
    response = sidecar.handle(
        {
            "schema_version": PROTOCOL_VERSION,
            "op": "act",
            "episode_id": 1,
            "step_id": 0,
            "pose": {"x_m": 0.25, "y_m": 0.0, "heading_rad": 0.1},
            "scan": {
                "ranges_m": [None, 2.0, None],
                "angle_min_rad": -0.5,
                "angle_increment_rad": 0.5,
                "range_min_m": 0.1,
                "range_max_m": 10.0,
                "source": "habitat_depth_center_horizon",
            },
            "sensor_contract": {
                "depth_present": True,
                "rgb_present": True,
                "gps_compass_present": False,
            },
        }
    )

    assert started == {"schema_version": 1, "op": "started", "episode_id": 1}
    assert controller.mission is not None
    assert controller.mission.goal is not None
    assert controller.mission.goal.x == 3.0
    assert controller.mission.goal.arrival_radius_m == 0.30
    observation = controller.observations[0]
    assert observation.position == (0.25, 0.0, 0.0)
    assert observation.heading_deg == pytest.approx(math.degrees(0.1))
    assert observation.lidar == (math.inf, 2.0, math.inf)
    assert observation.nearest_obstacle_m == 2.0
    assert observation.extras["pose_source"] == "nominal_commanded_action_dead_reckoning"
    assert response["vx"] == 0.2
    assert response["vyaw"] == 0.1
    assert response["stop"] is False


def test_sidecar_rejects_privileged_pose_contract_or_nonmonotonic_step() -> None:
    sidecar = ParcelPointNavSidecar(controller=_FakeController())
    sidecar.handle(
        {
            "schema_version": 1,
            "op": "start",
            "episode_id": 1,
            "goal": {"x_m": 1.0, "y_m": 0.0},
            "arrival_radius_m": 0.30,
        }
    )
    request = {
        "schema_version": 1,
        "op": "act",
        "episode_id": 1,
        "step_id": 2,
        "pose": {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0},
        "scan": {
            "ranges_m": [None, None, None],
            "angle_min_rad": -0.5,
            "angle_increment_rad": 0.5,
            "range_min_m": 0.1,
            "range_max_m": 10.0,
        },
        "sensor_contract": {
            "depth_present": True,
            "rgb_present": False,
            "gps_compass_present": False,
        },
    }
    with pytest.raises(BridgeProtocolError, match="monotonic"):
        sidecar.handle(request)
    request["step_id"] = 0
    request["sensor_contract"]["gps_compass_present"] = True
    with pytest.raises(BridgeProtocolError, match="deny GPS"):
        sidecar.handle(request)

    request["sensor_contract"]["gps_compass_present"] = False
    request["simulator_agent_state"] = {"x": 99.0}
    with pytest.raises(BridgeProtocolError, match="extra=.*simulator_agent_state"):
        sidecar.handle(request)


def test_json_line_server_fails_closed_and_closes_controller() -> None:
    controller = _FakeController()
    sidecar = ParcelPointNavSidecar(controller=controller)
    output = io.StringIO()

    status = serve(sidecar, io.StringIO('{"schema_version":99,"op":"act"}\n'), output)

    response = json.loads(output.getvalue())
    assert status == 2
    assert response["op"] == "error"
    assert controller.closed


def test_doctor_manifest_path_stays_inside_external_eval_surface() -> None:
    relative = MANIFEST_PATH.relative_to(REPO_ROOT)

    assert relative == Path("evals/external/habitat2020_manifest.json")
