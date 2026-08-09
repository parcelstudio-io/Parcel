from pathlib import Path

import pytest

from parcel_robot.gait import TrajectoryPlayer
from parcel_robot.skills.api import Dog
from parcel_robot.skills.catalog import SkillCatalog
from parcel_robot.skills.executor import SkillExecutor
from parcel_robot.skills.schema import parse_skill, playback_timing

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "configs" / "skills"
CONFIG = ROOT / "configs" / "robot.yaml"


def test_catalog_has_twenty_plus_skills():
    catalog = SkillCatalog.load(SKILLS)
    assert len(catalog.ids()) >= 20
    assert "jump" in catalog.ids()
    assert "kick_front" in catalog.ids()
    assert "run" in catalog.ids()
    assert catalog.get("sit").kind == "pose"
    assert catalog.get("jump").kind == "trajectory"


def test_dog_execute_pose_and_velocity():
    dog = Dog.from_config(CONFIG)
    poses = []
    walks = []
    dog.executor.on_pose = poses.append
    dog.executor.on_velocity = walks.append
    dog.executor.sim_socket = None
    assert dog.execute("sit").accepted
    assert poses and poses[-1].name == "sit"
    assert dog.execute("walk_forward").accepted
    assert walks and walks[-1].vx > 0
    assert dog.select("jump").id == "jump"
    assert len(dog.obs()) == 48


def test_pose_stops_locomotion_before_publishing_pose():
    events = []

    class Motion:
        def stop(self):
            events.append("stop")
            return "stopped"

    executor = SkillExecutor(
        SkillCatalog.load(SKILLS),
        motion=Motion(),  # type: ignore[arg-type]
        on_pose=lambda pose: events.append(f"pose:{pose.name}"),
    )

    result = executor.execute("sit")

    assert result.accepted
    assert events == ["stop", "pose:sit"]


def test_normalized_speed_retimes_pose_without_changing_joint_targets():
    catalog = SkillCatalog.load(SKILLS)
    poses = []
    executor = SkillExecutor(catalog, on_pose=poses.append)

    result = executor.execute("sit", speed=0.5)

    assert result.requested_speed == 0.5
    assert result.effective_rate == pytest.approx(0.625)
    assert result.effective_duration_s == pytest.approx(2.4)
    assert poses[0].duration == pytest.approx(result.effective_duration_s)
    assert poses[0].joints == catalog.get("sit").joints


def test_normalized_speed_retimes_trajectory_immutably():
    catalog = SkillCatalog.load(SKILLS)
    authored = catalog.get("excited_paw_taps")
    authored_times = tuple(frame.t for frame in authored.keyframes)
    trajectories = []
    executor = SkillExecutor(catalog, on_trajectory=trajectories.append)

    result = executor.execute("excited_paw_taps", speed=0.0)
    retimed = trajectories[0]

    assert result.effective_rate == pytest.approx(0.25)
    assert result.requested_speed == 0.0
    assert retimed.speed == 1.0
    assert result.effective_duration_s == pytest.approx(authored_times[-1] / 0.25)
    assert tuple(frame.t for frame in retimed.keyframes) == pytest.approx(
        tuple(timestamp / 0.25 for timestamp in authored_times)
    )
    assert tuple(frame.t for frame in authored.keyframes) == authored_times
    assert [frame.joints for frame in retimed.keyframes] == [
        frame.joints for frame in authored.keyframes
    ]


@pytest.mark.parametrize("speed", [True, "0.5", float("nan"), float("inf"), -0.01, 1.01])
def test_bounded_motion_rejects_invalid_normalized_speed(speed):
    executor = SkillExecutor(SkillCatalog.load(SKILLS))

    with pytest.raises((TypeError, ValueError), match="speed"):
        executor.execute("sit", speed=speed)


def test_playback_timing_endpoints_and_duration_floor():
    assert playback_timing(1.0, 1.0, maximum_duration_s=10.0) == pytest.approx(
        (1.0, 1.0)
    )
    assert playback_timing(1.0, 0.0, maximum_duration_s=10.0) == pytest.approx(
        (0.25, 4.0)
    )
    assert playback_timing(9.0, 0.0, maximum_duration_s=10.0) == pytest.approx(
        (0.9, 10.0)
    )


def test_skill_yaml_speed_is_optional_and_configurable():
    base = {
        "id": "test_pose",
        "kind": "pose",
        "joints": {"FL_hip_joint": 0.0},
    }

    assert parse_skill(base).speed == 1.0
    assert parse_skill({**base, "speed": 0.35}).speed == 0.35


def test_executor_uses_the_catalog_speed_when_no_override_is_supplied():
    skill = parse_skill(
        {
            "id": "test_pose",
            "kind": "pose",
            "duration": 1.0,
            "speed": 0.0,
            "joints": {"FL_hip_joint": 0.0},
        }
    )
    poses = []
    executor = SkillExecutor(
        SkillCatalog({skill.id: skill}, order=(skill.id,)),
        on_pose=poses.append,
    )

    result = executor.execute(skill.id)

    assert result.requested_speed == 0.0
    assert result.effective_duration_s == pytest.approx(4.0)
    assert poses[0].duration == pytest.approx(4.0)


def test_trajectory_player_interpolates():
    player = TrajectoryPlayer()
    player.start(
        [
            {"t": 0.0, "joints": {"FL_thigh_joint": 0.0}},
            {"t": 1.0, "joints": {"FL_thigh_joint": 1.0}},
        ]
    )
    mid = player.joints_for(0.5)
    assert mid is not None
    assert 0.4 < mid["FL_thigh_joint"] < 0.6
