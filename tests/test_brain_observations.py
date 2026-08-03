from __future__ import annotations

from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.brain.observations import (
    build_observation_snapshot,
    task_state_from_executive,
)
from parcel_robot.models import VelocityCommand


def test_planner_snapshot_preserves_sensor_provenance_without_world_geometry():
    observation = SimObservation(
        timestamp=10.0,
        robot=RobotPose(x=1.0, y=2.0, z=0.3, yaw=0.4),
        owner=OwnerTrack(
            owner_id="owner 1",
            x=4.0,
            y=5.0,
            visible=True,
            confidence=0.91,
        ),
        nearest_obstacle_m=2.0,
        semantic_regions=(
            SemanticRegionTrack(
                region_id="safe sidewalk",
                label="sidewalk",
                polygon=((1.0, 2.0), (3.0, 4.0), (5.0, 6.0)),
                confidence=0.88,
                source="camera-segmentation",
            ),
        ),
        semantic_objects=(
            SemanticObjectTrack(
                object_id="lamp post",
                label="lamppost",
                position=(8.0, 9.0, 0.0),
                confidence=0.84,
                source="rgbd-detector",
            ),
        ),
        backend="headless-city",
    )

    snapshot = build_observation_snapshot(
        observation,
        snapshot_id="snapshot-1",
        now=10.1,
        measured_velocity=VelocityCommand(vx=0.2),
        controller_state="armed",
        owner_heading_available=True,
    )

    assert snapshot.camera.fresh and snapshot.lidar.fresh
    assert snapshot.robot.moving
    assert snapshot.robot.x is None
    assert snapshot.robot.y is None
    assert snapshot.robot.yaw_rad is None
    assert {item.label for item in snapshot.entities} == {
        "owner",
        "sidewalk",
        "lamppost",
    }
    serialized = snapshot.as_dict()
    entity_payload = str(serialized["entities"])
    assert "polygon" not in entity_payload
    assert "position" not in entity_payload
    assert "8.0" not in entity_payload
    owner = next(item for item in snapshot.entities if item.kind == "owner")
    assert owner.entity_id == "owner:owner-1"
    assert owner.attributes["motion_heading_available"] is True


def test_planner_snapshot_fails_freshness_closed_and_uses_no_fake_battery():
    observation = SimObservation(
        timestamp=4.0,
        robot=RobotPose(),
        owner=OwnerTrack(),
        backend="camera-lidar-adapter",
    )

    snapshot = build_observation_snapshot(
        observation,
        snapshot_id="snapshot-stale",
        now=5.0,
        sensor_stale_s=0.5,
    )

    assert not snapshot.camera.fresh
    assert not snapshot.lidar.fresh
    assert not snapshot.safety.telemetry_fresh
    assert snapshot.battery.state == "unavailable"
    assert snapshot.battery.percent is None


def test_task_snapshot_drops_terminal_history_from_active_context():
    active = task_state_from_executive(
        {
            "state": "running",
            "task_id": "task-1",
            "plan_revision": 2,
            "step_id": "navigate",
            "at_checkpoint": False,
        }
    )
    terminal = task_state_from_executive(
        {"state": "succeeded", "task_id": "task-1", "plan_revision": 2}
    )

    assert active.task_id == "task-1"
    assert active.step_id == "navigate"
    assert terminal.state == "idle"
    assert terminal.task_id is None
