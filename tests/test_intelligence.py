import json

import pytest

from parcel_robot.agent import VoiceAgent
from parcel_robot.models import AgentDecision, Pose, ToolCall
from parcel_robot.providers import parse_model_decision
from parcel_robot.safety import SafetySupervisor
from parcel_robot.voice_pipeline import VoicePipeline


class FakeModel:
    def __init__(self, decision):
        self.decision = decision

    def decide(self, transcript, tools, context):
        assert transcript
        assert {tool["name"] for tool in tools} == {"run_pose", "stop_motion", "get_status"}
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
