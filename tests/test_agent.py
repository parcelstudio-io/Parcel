from pathlib import Path

from commissioned_sim import commissioned_agent_kwargs

from parcel_robot.config import ConfigStore
from parcel_robot.skills.api import Dog
from parcel_robot.voice.agent import VoiceAgent

REPO = Path(__file__).resolve().parents[1]


def test_pose_command_publishes_pose():
    sent = []
    config = REPO / "configs" / "robot.yaml"
    dog = Dog.from_config(config, on_pose=sent.append)
    pose = dog.poses()["sit"]
    agent = VoiceAgent(
        dog.poses(),
        [],
        sent.append,
        dog=dog,
        **commissioned_agent_kwargs(config),
    )

    assert agent.handle_text("do the sit pose") == "Running sit"
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


def test_navigate_directive_with_dog():
    config = REPO / "configs" / "robot.yaml"
    dog = Dog.from_config(config)
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        dog=dog,
        **commissioned_agent_kwargs(config),
    )
    reply = agent.handle_text("I want you to go to the coffee shop at 42nd street")
    assert "coffee" in reply.lower()
    assert "Navigating" in reply or "Arrived" in reply
