import json
from pathlib import Path

import pytest

from parcel_robot.agent import VoiceAgent
from parcel_robot.models import ActionProposal, AffectEstimate, AgentDecision, Pose, ToolCall
from parcel_robot.providers import parse_model_decision
from parcel_robot.safety import SafetySupervisor
from parcel_robot.skills import Dog
from parcel_robot.voice_pipeline import VoicePipeline

REPO = Path(__file__).resolve().parents[1]


class FakeModel:
    def __init__(self, decision):
        self.decision = decision

    def decide(self, transcript, tools, context):
        assert transcript
        assert {tool["name"] for tool in tools} == {
            "run_pose",
            "run_skill",
            "set_velocity",
            "set_motion_backend",
            "navigate",
            "set_behavior",
            "stop_motion",
            "get_status",
        }
        return self.decision


def test_model_pose_passes_safety_and_publishes():
    sent = []
    pose = Pose("sit", {"hip": 0.5})
    agent = VoiceAgent(
        {"sit": pose},
        [],
        sent.append,
        language_model=FakeModel(
            AgentDecision("Sitting down.", (ToolCall("run_pose", {"name": "sit"}),))
        ),
    )

    assert agent.handle_text("Could you sit?") == "Sitting down."
    assert sent == [pose]


def test_hallucinated_pose_is_rejected():
    sent = []
    agent = VoiceAgent(
        {},
        [],
        sent.append,
        language_model=FakeModel(
            AgentDecision("Doing a flip.", (ToolCall("run_pose", {"name": "backflip"}),))
        ),
    )

    assert "couldn't do that safely" in agent.handle_text("Do a flip")
    assert sent == []


def test_invalid_multi_action_plan_is_rejected_atomically():
    sent = []
    pose = Pose("sit", {"hip": 0.5})
    agent = VoiceAgent(
        {"sit": pose},
        [],
        sent.append,
        language_model=FakeModel(
            AgentDecision(
                "Sitting and sprinting.",
                (
                    ToolCall("run_pose", {"name": "sit"}),
                    ToolCall("set_velocity", {"vx": 100.0}),
                ),
            )
        ),
    )

    assert "couldn't do that safely" in agent.handle_text("Sit and then sprint")
    assert sent == []


@pytest.mark.parametrize(
    ("affect_actions", "proposal_name"),
    [
        ({"sad": "play_bow"}, "paw_wave"),
        ({"sad": "kick_front"}, "kick_front"),
        ({"sad": "sit"}, "sit"),
    ],
)
def test_inferred_affect_requires_exact_social_trajectory(
    affect_actions: dict[str, str],
    proposal_name: str,
):
    proposed = []
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    decision = AgentDecision(
        "I have an idea.",
        affect=AffectEstimate("sad", 0.99),
        next_action=ActionProposal(
            kind="skill",
            name=proposal_name,
            trigger="inferred_affect",
        ),
    )
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        language_model=FakeModel(decision),
        action_proposal_publisher=lambda proposal: proposed.append(proposal) or "accepted",
        affect_actions=affect_actions,
        dog=dog,
    )

    assert "couldn't do that safely" in agent.handle_text("I feel sad")
    assert proposed == []


def test_inferred_affect_accepts_personality_social_trajectory():
    proposed = []
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    proposal = ActionProposal(kind="skill", name="play_bow", trigger="inferred_affect")
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        language_model=FakeModel(
            AgentDecision(
                "I'm here.",
                affect=AffectEstimate("sad", 0.99),
                next_action=proposal,
            )
        ),
        action_proposal_publisher=lambda action: proposed.append(action) or "accepted",
        affect_actions={"sad": "play_bow"},
        dog=dog,
    )

    assert agent.handle_text("I feel sad") == "I'm here."
    assert proposed == [proposal]


@pytest.mark.parametrize("skill_name", ["sit", "play_bow"])
def test_explicit_bounded_named_skill_still_uses_activity_coordinator(skill_name: str):
    proposed = []
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        action_proposal_publisher=lambda action: proposed.append(action) or "accepted",
        dog=dog,
    )

    assert agent.handle_text(f"perform {skill_name.replace('_', ' ')}") == "accepted"
    assert proposed[0].name == skill_name
    assert proposed[0].trigger == "explicit_command"


def test_coordinated_run_skill_tool_advertises_only_bounded_skills():
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        action_proposal_publisher=lambda action: "accepted",
        dog=dog,
    )

    run_skill = next(tool for tool in agent.tool_definitions() if tool["name"] == "run_skill")
    advertised = set(run_skill["parameters"]["properties"]["name"]["enum"])
    assert {"sit", "play_bow", "jump"} <= advertised
    assert advertised.isdisjoint({"run", "trot", "walk_forward", "turn_left"})
    assert "bounded" in run_skill["description"]


@pytest.mark.parametrize("tool_name", ["run_pose", "run_skill"])
def test_model_cannot_route_velocity_skill_into_activity_coordinator(tool_name: str):
    proposed = []
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    agent = VoiceAgent(
        dog.poses(),
        [],
        lambda pose: None,
        language_model=FakeModel(
            AgentDecision(
                "Walking.",
                (ToolCall(tool_name, {"name": "walk_forward"}),),
            )
        ),
        action_proposal_publisher=lambda action: proposed.append(action) or "accepted",
        dog=dog,
    )

    assert "couldn't do that safely" in agent.handle_text("Use walk forward skill")
    assert proposed == []


def test_follow_and_stay_publish_only_whitelisted_behaviors():
    modes = []
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        behavior_publisher=lambda mode: modes.append(mode) or mode,
    )

    assert agent.handle_text("follow me") == "I will follow you."
    assert agent.handle_text("stay") == "I will stay here."
    assert modes == ["follow", "stay"]


def test_stop_bypasses_language_model():
    stopped = []
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=FakeModel(AgentDecision("Wrong response.")),
        stop_publisher=lambda: stopped.append(True),
    )

    assert agent.handle_text("STOP") == "Stopping."
    assert stopped == [True]


def test_model_json_is_strict():
    decision = parse_model_decision(
        json.dumps(
            {
                "reply": "Okay.",
                "tool_calls": [{"name": "run_pose", "arguments": {"name": "sit"}}],
            }
        )
    )
    assert decision.tool_calls == (ToolCall("run_pose", {"name": "sit"}),)

    with pytest.raises((TypeError, ValueError)):
        parse_model_decision('{"tool_calls":[]}')


def test_safety_rejects_unknown_tools_and_arguments():
    supervisor = SafetySupervisor({"sit": Pose("sit", {"hip": 0.0})})

    assert not supervisor.validate(ToolCall("shell", {"command": "anything"})).accepted
    assert not supervisor.validate(ToolCall("stop_motion", {"delay": 1})).accepted


def test_voice_pipeline_connects_adapters():
    played = []

    class Recognizer:
        def transcribe(self, wav_audio):
            assert wav_audio == b"wav"
            return "status"

    class Synthesizer:
        def synthesize(self, text):
            return f"audio:{text}".encode()

    agent = VoiceAgent({}, [], lambda pose: None)
    pipeline = VoicePipeline(Recognizer(), agent, Synthesizer(), played.append)

    assert pipeline.process(b"wav") == ("status", "I did not understand that command")
    assert played == [b"audio:I did not understand that command"]
