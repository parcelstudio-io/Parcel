from pathlib import Path

from parcel_robot.gait import TrajectoryPlayer
from parcel_robot.skills.api import Dog
from parcel_robot.skills.catalog import SkillCatalog
from parcel_robot.skills.executor import SkillExecutor

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
