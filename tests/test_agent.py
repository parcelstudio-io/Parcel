from parcel_robot.agent import VoiceAgent
from parcel_robot.config import ConfigStore
from parcel_robot.models import Pose


def test_pose_command_publishes_pose():
    sent = []
    pose = Pose("sit", {"hip": 0.5})
    agent = VoiceAgent({"sit": pose}, [], sent.append)

    assert agent.handle_text("do the sit pose") == "Running sit pose"
    assert sent == [pose]


def test_unknown_pose_is_safe():
    sent = []
    agent = VoiceAgent({}, [], sent.append)

    assert agent.handle_text("pose backflip") == "Unknown pose: backflip"
    assert sent == []


def test_config_and_custom_module(tmp_path):
    config = tmp_path / "robot.yaml"
    config.write_text(
        """
poses: {}
modules:
  - name: status
    class: parcel_robot.modules.StatusModule
    config: {label: scout}
""",
        encoding="utf-8",
    )
    store = ConfigStore(config)
    agent = VoiceAgent({}, store.load_modules(), lambda pose: None)

    assert agent.handle_text("status") == "scout is ready"

