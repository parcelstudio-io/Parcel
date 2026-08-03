import json
from pathlib import Path

import pytest

from parcel_robot.agent import VoiceAgent
from parcel_robot.brain import PlanIR
from parcel_robot.brain.observations import build_observation_snapshot
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
            "run_spatial_behavior",
            "stop_motion",
            "get_status",
        }
        return self.decision


class FakeSplitBrainModel:
    def __init__(self, plan: PlanIR):
        self.result = plan
        self.plan_calls = []
        self.decide_calls = 0

    def plan(self, transcript, **kwargs):
        self.plan_calls.append((transcript, kwargs))
        return self.result

    def decide(self, transcript, tools, context):
        self.decide_calls += 1
        return AgentDecision("Wrong fast-path response")


class FakeConversationOnlyModel:
    def __init__(self):
        self.decide_calls: list[str] = []

    def decide(self, transcript, tools, context):
        self.decide_calls.append(transcript)
        return AgentDecision("I'm right here with you.")

    def plan(self, transcript, **kwargs):
        raise AssertionError("the conversation provider must not plan")


def _hold_plan(source_turn_id: str = "turn-local-1") -> PlanIR:
    return PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": "task-hold-1",
            "plan_revision": 1,
            "source_turn_id": source_turn_id,
            "goal": {
                "relation": "hold",
                "target": {"kind": "current_pose", "query": ""},
                "tolerance_m": 0.0,
            },
            "invariants": ["keep_collision_margin"],
            "steps": [
                {
                    "id": "hold",
                    "skill": "Hold",
                    "arguments": {},
                    "preconditions": ["base_available"],
                    "success": {
                        "fact": "motion_stopped",
                        "target": None,
                        "tolerance_m": None,
                        "confidence_min": None,
                    },
                    "timeout_s": 5.0,
                    "max_attempts": 1,
                    "recovery": ["safe_stop"],
                    "resources": ["base"],
                    "interruptibility": "immediate",
                }
            ],
            "requested_interrupt": "at_checkpoint",
        }
    )


def test_compound_motion_uses_one_plan_call_and_preserves_exact_transcript():
    published = []
    model = FakeSplitBrainModel(_hold_plan())
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=model,
        planning_context_provider=lambda: build_observation_snapshot(
            None, snapshot_id="snapshot-plan-1", now=1.0
        ),
        plan_publisher=lambda plan, frame, transcript: (
            published.append((plan, frame, transcript)) or "Safe plan accepted."
        ),
        planner_system_prompt_provider=lambda: "PlanIR only.",
        planner_schema_provider=lambda: {"type": "object"},
        planner_skill_contracts_provider=lambda: {
            "schema_version": 1,
            "skills": [{"name": "Hold"}],
        },
    )

    transcript = "Walk to the Sidewalk and then WAIT."
    assert agent.handle_text(transcript) == "Safe plan accepted."
    assert len(model.plan_calls) == 1
    assert model.decide_calls == 0
    assert model.plan_calls[0][0] == transcript
    assert published[0][2] == transcript
    assert agent.memory.recent(2)[0]["content"] == transcript
    assert agent.last_intent_frame is not None
    assert agent.last_intent_frame.route == "deliberative_plan"
    assert agent.last_reasoning_source == "plan_model"


def test_conversation_and_planning_can_use_independent_provider_objects():
    conversation = FakeConversationOnlyModel()
    planner = FakeSplitBrainModel(_hold_plan("model-authored-turn"))
    published = []
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=conversation,
        planner_model=planner,
        planning_context_provider=lambda: build_observation_snapshot(
            None, snapshot_id="snapshot-split-provider-1", now=1.0
        ),
        plan_publisher=lambda *args: published.append(args) or "Safe plan accepted.",
        planner_system_prompt_provider=lambda: "PlanIR only.",
        planner_schema_provider=lambda: {"type": "object"},
        planner_skill_contracts_provider=lambda: {
            "schema_version": 1,
            "skills": [{"name": "Hold"}],
        },
    )

    assert agent.handle_text("How are you feeling today?") == "I'm right here with you."
    task = "Walk to the sidewalk and then wait."
    assert agent.handle_text(task) == "Safe plan accepted."

    assert conversation.decide_calls == ["How are you feeling today?"]
    assert [call[0] for call in planner.plan_calls] == [task]
    assert planner.decide_calls == 0
    assert published[0][2] == task


def test_superseded_compound_plan_cannot_commit_to_executive():
    published = []
    model = FakeSplitBrainModel(_hold_plan())
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=model,
        planning_context_provider=lambda: build_observation_snapshot(
            None, snapshot_id="snapshot-plan-1", now=1.0
        ),
        plan_publisher=lambda *args: published.append(args) or "accepted",
        planner_system_prompt_provider=lambda: "PlanIR only.",
        planner_schema_provider=lambda: {"type": "object"},
        planner_skill_contracts_provider=lambda: {
            "schema_version": 1,
            "skills": [{"name": "Hold"}],
        },
    )

    reply = agent.handle_text_guarded(
        "Walk to the sidewalk and then wait.",
        lambda action: "Superseded before commit.",
    )

    assert reply == "Superseded before commit."
    assert len(model.plan_calls) == 1
    assert published == []


def test_model_plan_turn_id_is_rebound_to_trusted_router_context():
    published = []
    model = FakeSplitBrainModel(_hold_plan("different-turn"))
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=model,
        planning_context_provider=lambda: build_observation_snapshot(
            None, snapshot_id="snapshot-plan-1", now=1.0
        ),
        plan_publisher=lambda *args: published.append(args) or "accepted",
        planner_system_prompt_provider=lambda: "PlanIR only.",
        planner_schema_provider=lambda: {"type": "object"},
        planner_skill_contracts_provider=lambda: {
            "schema_version": 1,
            "skills": [{"name": "Hold"}],
        },
    )

    reply = agent.handle_text("Walk to the sidewalk and then wait.")

    assert reply == "accepted"
    assert model.decide_calls == 0
    assert agent.last_reasoning_source == "plan_model"
    assert len(published) == 1
    assert published[0][0].source_turn_id == published[0][1].turn_id


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
    "transcript",
    [
        "Don't walk in a circle around me.",
        "Don’t walk in a circle around me.",
        "What would happen if you walked in a circle around me?",
        "Imagine walking five steps away from me.",
        "If I told you I was sad someday, what would you do?",
    ],
)
def test_model_motion_is_suppressed_for_negated_or_hypothetical_text(transcript: str):
    spatial = []
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=FakeModel(
            AgentDecision(
                "I can explain that without moving.",
                (
                    ToolCall(
                        "run_spatial_behavior",
                        {
                            "behavior": "orbit_owner",
                            "direction": "counterclockwise",
                            "size": "small",
                            "revolutions": 1.0,
                        },
                    ),
                ),
            )
        ),
        spatial_behavior_publisher=lambda intent: spatial.append(intent) or "started",
    )

    assert agent.handle_text(transcript) == (
        "I won't move from that request, but I can explain what I would do."
    )
    assert spatial == []
    assert agent.last_reasoning_guard is not None


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


def test_explicit_follow_behind_uses_formation_behavior_not_direct_follow():
    modes = []
    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        behavior_publisher=lambda mode: modes.append(mode) or mode,
    )

    reply = agent.handle_text("follow behind me")

    assert "estimate your direction" in reply
    assert modes == ["follow_behind"]


def test_direct_semantic_navigation_reports_search_without_resolved_goal():
    dog = Dog.from_config(REPO / "configs" / "robot.yaml")
    agent = VoiceAgent(dog.poses(), [], lambda pose: None, dog=dog)

    reply = agent.handle_text(
        "Can you go to the sidewalk so that you are not on the road. It's dangerous"
    )

    assert reply.startswith("Navigating to sidewalk")
    assert "semantic_search_scan" in reply
    assert dog._navigator.mission.status == "searching"
    assert dog._navigator.mission.goal is None


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
