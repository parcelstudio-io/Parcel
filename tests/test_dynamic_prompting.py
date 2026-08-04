"""Bare dynamic prompting: sectioned composition, profile facts, info tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from parcel_robot.agent import VoiceAgent
from parcel_robot.dynamic_prompting import (
    CallableContextSource,
    ConversationTool,
    ConversationToolRegistry,
    DynamicPromptComposer,
    StaticContextSource,
    ToolPolicySource,
    UserProfileSource,
    build_prompting_stack,
    build_weather_tool,
)
from parcel_robot.models import AgentDecision, ToolCall

REPO = Path(__file__).resolve().parents[1]


def test_composer_orders_stable_before_turn_and_by_priority() -> None:
    composer = DynamicPromptComposer()
    composer.register(
        CallableContextSource("volatile", lambda: "TURN-TEXT", placement="turn", priority=5)
    )
    composer.register(StaticContextSource("later", "SECOND", priority=20))
    composer.register(StaticContextSource("earlier", "FIRST", priority=10))
    composed = composer.compose()
    ids = [section.source_id for section in composed.sections]
    assert ids == ["earlier", "later", "volatile"]
    assert composed.text.index("FIRST") < composed.text.index("SECOND")
    assert composed.stable_text.endswith("SECOND")
    assert composed.turn_text == "TURN-TEXT"
    assert composer.last is composed


def test_composer_truncates_per_section_and_drops_over_turn_budget() -> None:
    composer = DynamicPromptComposer(turn_budget_chars=200)
    composer.register(
        CallableContextSource(
            "big", lambda: "x" * 500, placement="turn", priority=10, budget_chars=180
        )
    )
    composer.register(
        CallableContextSource(
            "overflow", lambda: "y" * 150, placement="turn", priority=20, budget_chars=400
        )
    )
    composed = composer.compose()
    rendered = {section.source_id: section for section in composed.sections}
    assert rendered["big"].truncated and rendered["big"].chars == 180
    # The second source no longer fits the shared turn budget: dropped loudly.
    assert composed.dropped == ("overflow",)


def test_composer_skips_empty_sources_and_rejects_duplicates() -> None:
    composer = DynamicPromptComposer()
    composer.register(CallableContextSource("silent", lambda: None))
    composer.register(CallableContextSource("failing", lambda: 1 / 0))
    composed = composer.compose()
    assert composed.sections == ()
    with pytest.raises(ValueError, match="already registered"):
        composer.register(CallableContextSource("silent", lambda: "text"))


def test_user_profile_renders_facts_and_updates_live() -> None:
    profile = UserProfileSource(
        {"location": "New York", "home": "Manhattan", "occupation": "software engineer"}
    )
    text = profile.snapshot(None)
    assert text is not None
    assert "location: New York" in text
    assert "occupation: software engineer" in text
    profile.set_fact("Favorite Park", "Central Park")
    assert "favorite park: Central Park" in profile.snapshot(None)
    profile.remove_fact("home")
    assert "Manhattan" not in profile.snapshot(None)


def test_tool_registry_definitions_and_invocation_contract() -> None:
    registry = ConversationToolRegistry()
    registry.register(
        ConversationTool(
            name="lookup",
            description="Look something up.",
            when_to_use="the owner asks a lookup question",
            parameters={"type": "object", "properties": {"q": {"type": "string"}},
                        "required": ["q"]},
            handler=lambda arguments: f"result for {arguments['q']}",
        )
    )
    definition = registry.definitions()[0]
    assert definition["name"] == "lookup"
    assert "Use when" in definition["description"]
    assert registry.invoke("lookup", {"q": "parks"}) == "result for parks"
    with pytest.raises(ValueError, match="requires arguments"):
        registry.invoke("lookup", {})
    with pytest.raises(LookupError):
        registry.invoke("missing", {})


def test_weather_tool_uses_profile_location_as_default() -> None:
    profile = UserProfileSource({"location": "New York"})
    tool = build_weather_tool(profile)
    assert "New York" in tool.handler({})
    assert "Tokyo" in tool.handler({"location": "Tokyo"})
    with pytest.raises(ValueError, match="needs a location"):
        build_weather_tool(None).handler({})


def test_tool_policy_source_renders_decision_guidance() -> None:
    registry = ConversationToolRegistry()
    registry.register(build_weather_tool(None))
    text = ToolPolicySource(registry).snapshot(None)
    assert text is not None
    assert "get_weather" in text
    assert "decide each turn" in text.lower()
    assert "Use when" in text


def test_build_prompting_stack_from_config() -> None:
    stack = build_prompting_stack(
        {
            "user_profile": {"location": "New York", "occupation": "software engineer"},
            "tools": {"weather": True},
        }
    )
    assert stack.composer is not None
    assert stack.tools.names() == ("get_weather",)
    composed = stack.composer.compose()
    assert "location: New York" in composed.stable_text
    assert "get_weather" in composed.stable_text

    disabled = build_prompting_stack({"enabled": False})
    assert disabled.composer is None
    assert disabled.detail == "disabled"


def test_agent_executes_information_tool_and_folds_result_into_reply() -> None:
    registry = ConversationToolRegistry()
    registry.register(build_weather_tool(UserProfileSource({"location": "New York"})))

    class WeatherModel:
        def decide(self, transcript, tools, history):
            del transcript, history
            assert any(tool["name"] == "get_weather" for tool in tools)
            return AgentDecision("Let me check.", (ToolCall("get_weather", {}),))

    agent = VoiceAgent(
        {},
        [],
        lambda pose: None,
        language_model=WeatherModel(),
        info_tools=registry,
    )
    reply = agent.handle_text("what's the weather like today?")
    assert "Let me check." in reply
    assert "New York" in reply and "22°C" in reply
    tool_rows = [row for row in agent.memory.recent(8) if row["role"] == "tool"]
    assert any("get_weather:" in row["content"] for row in tool_rows)


def test_agent_rejects_unregistered_information_tool() -> None:
    class RogueModel:
        def decide(self, transcript, tools, history):
            del transcript, tools, history
            return AgentDecision("Sure.", (ToolCall("delete_files", {}),))

    agent = VoiceAgent({}, [], lambda pose: None, language_model=RogueModel())
    reply = agent.handle_text("please tidy up")
    assert "couldn't do that safely" in reply.lower()


def test_runtime_wires_prompting_into_system_prompt(tmp_path: Path) -> None:
    import time as _time

    from parcel_robot.audio_io import AudioDeviceStatus
    from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
    from parcel_robot.runtime import RobotRuntime

    class _Backend:
        name = "prompting-test"

        def observe(self) -> SimObservation:
            return SimObservation(
                timestamp=_time.monotonic(),
                robot=RobotPose(),
                owner=OwnerTrack(),
                backend=self.name,
            )

        def move(self, command) -> None:
            del command

        def stop(self) -> None:
            pass

        def pose(self, pose) -> None:
            del pose

        def trajectory(self, skill) -> None:
            del skill

        def move_owner(self, dx, dy) -> None:
            del dx, dy

    config = tmp_path / "prompting-runtime.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
prompting:
  turn_budget_chars: 1500
  user_profile:
    location: New York
    home: Manhattan
    occupation: software engineer
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    runtime = RobotRuntime(
        config,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )
    try:
        prompt = runtime._render_system_prompt()
        assert "location: New York" in prompt
        assert "occupation: software engineer" in prompt
        assert "get_weather" in prompt
        assert "Current situation:" in prompt

        inspection = runtime.prompt_inspection()
        assert inspection["enabled"] is True
        ids = [section["source_id"] for section in inspection["composed"]["sections"]]
        assert "user_profile" in ids
        assert "tool_policy" in ids
        assert "current_situation" in ids
        assert inspection["tools"][0]["name"] == "get_weather"

        runtime.set_user_fact("favorite park", "Central Park")
        assert "Central Park" in runtime._render_system_prompt()
    finally:
        runtime.close()


def test_prompting_rejects_keys_that_belong_to_another_section() -> None:
    """2026-08-04: a mis-indented YAML block put the speech section's audio
    keys under `prompting:` for a whole sprint. They were silently accepted
    and never read, so device selection and endpointing config did nothing.
    An accepted-but-unread key must now fail loudly."""

    with pytest.raises(ValueError, match="unsupported prompting config keys"):
        build_prompting_stack({"user_profile": {}, "endpointing": "semantic"})
    with pytest.raises(ValueError, match="echo_guard_scale"):
        build_prompting_stack({"echo_guard_scale": 2.5})


def test_canonical_config_keeps_audio_settings_in_the_speech_section() -> None:
    """Pins the section boundary the regression above crossed."""

    from parcel_robot.config import ConfigStore

    store = ConfigStore(REPO / "configs" / "robot.yaml")
    speech = store.section("speech")
    # (barge_in/fish_streaming were removed entirely 2026-08-04: they were
    # accepted-but-unread, the same bug class this test exists to prevent.)
    for key in ("endpointing", "echo_guard_scale", "fish_url"):
        assert key in speech, f"{key} must live under speech:"
    # And the canonical config must still build a prompting stack at all.
    assert build_prompting_stack(store.section("prompting")).composer is not None
