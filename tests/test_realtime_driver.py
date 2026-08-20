"""Card R1.6 §B/§C: the driver, the reconnect backoff, and the text-mode path.

WHAT THIS FILE PINS
-------------------
* **The crank exists and turns in the right order.** ``pump()`` → prompt
  refresh → ``tick()``. Anything else either refreshes the prompt plane after
  the boundary it was meant to serve, or reconnects before a ``session.created``
  in the same batch could reset the backoff ladder.
* **Reconnect backs off.** This is the R1.5 audit's first standing risk, quoted
  in full in its own test: *"Reconnect still has no backoff — inherited from R1,
  now reachable over a real socket. A flapping provider would hot-loop. This
  should be the next card's first item."* The ladder is exponential, capped,
  jittered, reset by a real session, and NOT applied to a healthy rollover.
* **Text mode is a real conversation with no audio hardware.** The typed
  sentence takes the restricted ingress first (so a typed "stop" latches the
  local emergency stop before the cloud is asked), then the conversation item,
  then an explicit ``response.create``.

Every clock, sleep and jitter source here is injected. Nothing sleeps.
"""

from __future__ import annotations

import builtins
import time
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.browser_sink import DiscardSink
from parcel_robot.realtime.config import (
    ALLOWED_MODES,
    MODE_AUDIO,
    MODE_TEXT,
    REALTIME_CONFIG_ENV,
    RealtimeConfig,
    RealtimeConfigError,
    load_realtime_config,
    realtime_config_from_mapping,
)
from parcel_robot.realtime.cost import realtime_spend_usd, realtime_usage_totals
from parcel_robot.realtime.driver import RealtimeDriver
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_done,
    handshake,
    response_done,
    transcript_done,
)
from parcel_robot.realtime.lane import (
    DEFAULT_RECONNECT_BACKOFF_S,
    RealtimeLane,
    RealtimeLaneError,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r16-driver"


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Lane:
    """A lane-shaped recorder. The driver may touch exactly these members."""

    def __init__(self, *, tick_reason: str | None = None, explode: str = "") -> None:
        self.calls: list[str] = []
        self.instructions = "v1"
        self.tick_reason = tick_reason
        self.explode = explode
        self.active = True

    def pump(self) -> int:
        self.calls.append("pump")
        if self.explode == "pump":
            raise RuntimeError("pump exploded")
        return 2

    def tick(self) -> str | None:
        self.calls.append("tick")
        if self.explode == "tick":
            raise RuntimeError("tick exploded")
        return self.tick_reason


class _Instructions:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.index = 0

    def refresh(self, lane) -> bool:
        lane.calls.append("refresh")
        text = self.texts[min(self.index, len(self.texts) - 1)]
        self.index += 1
        changed = text != lane.instructions
        lane.instructions = text
        return changed


# ================================================================ the driver
def test_the_driver_pumps_then_refreshes_then_ticks() -> None:
    lane = _Lane()
    driver = RealtimeDriver(lane, instructions=_Instructions(["v1", "v2"]))
    driver.step()
    assert lane.calls == ["pump", "refresh", "tick"]
    assert driver.frames == 2
    assert driver.refreshes == 0, "identical text is not a refresh"
    driver.step()
    assert driver.refreshes == 1, "the DI render moved, and the lane now holds it"
    assert lane.instructions == "v2"


def test_a_reconnect_reason_is_recorded_and_announced() -> None:
    notes: list[str] = []
    lane = _Lane(tick_reason="rollover")
    driver = RealtimeDriver(lane, on_event=notes.append)
    driver.step()
    assert driver.reconnect_reasons == ["rollover"]
    assert any("rollover" in note for note in notes)


@pytest.mark.parametrize("where", ["pump", "tick"])
def test_the_driver_survives_a_raising_lane(where: str) -> None:
    """A driver that died on one bad frame would take the conversation with it."""

    lane = _Lane(explode=where)
    driver = RealtimeDriver(lane)
    driver.step()
    driver.step()
    assert driver.steps == 2
    assert len(driver.failures) == 2
    assert where in driver.failures[0]


def test_a_raising_instruction_source_never_stops_the_loop() -> None:
    class _Broken:
        def refresh(self, lane) -> bool:
            raise ValueError("prompt library is missing")

    lane = _Lane()
    driver = RealtimeDriver(lane, instructions=_Broken())
    driver.step()
    assert lane.calls == ["pump", "tick"], "the tick still ran"
    assert "instruction refresh failed" in driver.failures[0]


def test_the_thread_starts_stops_and_reports() -> None:
    lane = _Lane()
    clock = _Clock()
    driver = RealtimeDriver(lane, interval_s=0.001, clock=clock, sleep=time.sleep)
    driver.start()
    try:
        deadline = time.monotonic() + 2.0
        while driver.steps < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        driver.stop()
    assert driver.steps >= 3
    assert driver.running is False
    assert driver.snapshot()["running"] is False


# =============================================================== the backoff
class _Rig:
    def __init__(self, script: list[Step], **kwargs) -> None:
        self.clock = _Clock()
        self.script = script
        self.servers: list[FakeRealtimeServer] = []
        self.slept: list[float] = []
        self.sink = DiscardSink()
        counter = {"n": 0}

        def _session_id() -> str:
            counter["n"] += 1
            return f"rt_{counter['n']}"

        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            clock=self.clock,
            session_id_factory=_session_id,
            sleep=self._sleep,
            **kwargs,
        )

    def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def open(self) -> str:
        session = self.lane.open_session(handshake_token="csrf", mic_gesture=True)
        self.step()
        return session

    def step(self) -> None:
        self.server.pump()
        self.lane.pump()


def test_a_flapping_provider_no_longer_hot_loops() -> None:
    """The R1.5 audit's first standing risk, closed.

    Before this card ``_reconnect`` re-dialled with no delay at all, so a
    provider that accepts a socket and immediately drops it turned ``pump()``
    into one full reconnect per call, forever.
    """

    rig = _Rig(handshake(), jitter=lambda: 1.0)
    rig.open()
    for _ in range(4):
        rig.lane._reconnect("disconnect")
    assert rig.slept == [0.5, 1.0, 2.0, 4.0], "exponential from the documented base"
    assert rig.lane.backoff_waits == rig.slept


def test_the_backoff_is_capped_and_jittered() -> None:
    rig = _Rig(handshake(), reconnect_backoff_max_s=2.0, jitter=lambda: 0.0)
    rig.open()
    for _ in range(6):
        rig.lane._reconnect("stall")
    # jitter 0.0 halves each step; the cap bounds the ladder.
    assert rig.slept == [0.25, 0.5, 1.0, 1.0, 1.0, 1.0]
    assert max(rig.slept) <= 2.0


def test_a_nonsense_jitter_source_lengthens_the_wait_rather_than_shortening_it() -> None:
    rig = _Rig(handshake(), jitter=lambda: float("nan"))
    rig.open()
    rig.lane._reconnect("disconnect")
    assert rig.slept == [DEFAULT_RECONNECT_BACKOFF_S]


def test_a_real_session_resets_the_ladder() -> None:
    """``session.created`` is the provider's own word that a session exists."""

    rig = _Rig(handshake(), jitter=lambda: 1.0)
    rig.open()
    rig.lane._reconnect("disconnect")
    rig.lane._reconnect("disconnect")
    assert rig.slept == [0.5, 1.0]
    rig.step()  # the new socket's handshake lands
    assert rig.lane.provider_session_id == "sess_fake_1"
    rig.lane._reconnect("disconnect")
    assert rig.slept[-1] == 0.5, "a healthy session put the ladder back on rung one"


def test_a_rollover_waits_for_nothing() -> None:
    """A rollover is scheduled and healthy; delaying it would add dead air."""

    rig = _Rig(handshake(), jitter=lambda: 1.0)
    rig.open()
    rig.lane._rollover(rig.clock())
    assert rig.slept == []
    assert rig.lane.rollovers == 1


def test_backoff_can_be_switched_off_entirely() -> None:
    rig = _Rig(handshake(), reconnect_backoff_s=0.0)
    rig.open()
    rig.lane._reconnect("disconnect")
    assert rig.slept == []


# ============================================================== the text path
def test_send_text_orders_the_user_line_then_the_report_then_the_ask() -> None:
    seen: list[str] = []

    def _ingress(text, *, item_id=None, session_id=None):
        from parcel_robot.realtime.ingress import RealtimeTranscriptOutcome

        seen.append(text)
        return RealtimeTranscriptOutcome(
            kind="hold",
            name="hold",
            transcript=text,
            reply="Staying.",
            executed=True,
            item_id=item_id,
            session_id=session_id,
        )

    rig = _Rig(handshake(), ingress=_ingress)
    rig.open()
    rig.lane.send_text("  stay   here  ")
    assert seen == ["stay here"], "whitespace is collapsed exactly like the voice path"

    sent = rig.lane.transport.sent  # type: ignore[union-attr]
    tail = [str(frame.get("type")) for frame in sent][-3:]
    assert tail == ["conversation.item.create", "conversation.item.create", "response.create"]
    roles = [
        frame["item"].get("role")
        for frame in sent
        if frame.get("type") == "conversation.item.create"
    ]
    assert roles[-2:] == ["user", "system"], "the robot's report follows the sentence"
    assert rig.lane.text_turns == 1
    assert rig.lane.outcomes[0].executed is True


def test_send_text_refuses_an_empty_string_and_a_closed_session() -> None:
    rig = _Rig(handshake())
    with pytest.raises(RealtimeLaneError):
        rig.lane.send_text("hello")  # no session yet
    rig.open()
    with pytest.raises(RealtimeLaneError):
        rig.lane.send_text("   ")


def test_send_text_still_ledgers_the_owner_when_no_ingress_is_wired() -> None:
    from parcel_robot.memory import ConversationMemory

    ledger = ConversationMemory(":memory:")
    rig = _Rig(handshake(), ledger=ledger)
    rig.open()
    rig.lane.send_text("hello dog")
    assert [row["content"] for row in ledger.realtime_turns()] == ["hello dog"]


def test_an_ingress_failure_in_text_mode_still_asks_for_a_reply() -> None:
    def _explode(text, *, item_id=None, session_id=None):
        raise RuntimeError("boom")

    rig = _Rig(handshake(), ingress=_explode)
    rig.open()
    rig.lane.send_text("hello")
    types = [str(frame.get("type")) for frame in rig.lane.transport.sent]  # type: ignore[union-attr]
    assert types[-1] == "response.create"
    assert any("ingress refused" in note for note in rig.lane.events)


# ================================================================ the config
def test_the_mode_key_round_trips_and_defaults_to_text() -> None:
    assert RealtimeConfig().mode == MODE_TEXT
    assert RealtimeConfig().audio is False
    parsed = realtime_config_from_mapping({"enabled": True, "mode": "audio"})
    assert parsed.mode == MODE_AUDIO
    assert parsed.audio is True
    assert parsed.as_dict()["mode"] == MODE_AUDIO
    assert ALLOWED_MODES == {MODE_TEXT, MODE_AUDIO}


@pytest.mark.parametrize("body", ["mode: speaker", "mode: 3", "mode: true", "mode: ''"])
def test_an_unreadable_mode_refuses_rather_than_guessing(tmp_path: Path, body: str) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text(f"enabled: true\n{body}\n", encoding="utf-8")
    with pytest.raises(RealtimeConfigError):
        load_realtime_config(path)


def test_the_rest_of_the_fail_closed_shape_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "realtime.yaml"
    path.write_text("enabled: true\nmodel: x\nmoad: text\n", encoding="utf-8")
    with pytest.raises(RealtimeConfigError) as caught:
        load_realtime_config(path)
    assert "moad" in str(caught.value)
    assert load_realtime_config(tmp_path / "absent.yaml").source == "absent"


# ================================================================== the cost
def test_spend_is_estimated_from_usage_rows_at_assumed_rates() -> None:
    rows = [
        {"input_tokens": 1_000, "cached_tokens": 400, "output_tokens": 500},
        {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0},
    ]
    # 600 uncached @ $4/Mtok + 400 cached @ $0.40/Mtok + 500 out @ $16/Mtok
    assert realtime_spend_usd(rows) == pytest.approx(
        (600 * 4.00 + 400 * 0.40 + 500 * 16.00) / 1_000_000
    )
    totals = realtime_usage_totals(rows)
    assert totals["responses"] == 2
    assert totals["rates_are_assumed"] is True


def test_a_garbage_usage_row_contributes_nothing_rather_than_raising() -> None:
    assert realtime_spend_usd([{"input_tokens": None, "output_tokens": "many"}]) == 0.0


# =========================================================== the discard sink
def test_the_discard_sink_counts_what_it_drops() -> None:
    sink = DiscardSink()
    sink.begin_utterance()
    sink.enqueue(b"RIFF" + b"\x00" * 100)
    sink.enqueue(b"")
    assert sink.snapshot() == {
        "kind": "discard",
        "utterances": 1,
        "chunks_discarded": 2,
        "bytes_discarded": 104,
        "interrupts": 0,
    }
    assert sink.first_chunk_started_monotonic is None, "nothing was ever heard"


# ======================================================= the runtime, end to end
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        raise AssertionError(f"the local conversation model saw a hosted turn: {transcript!r}")


def _runtime(tmp_path: Path) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r16-driver.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r1.6 driver fixture",
        ),
    )


def test_text_mode_builds_a_discard_sink_and_no_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        assert isinstance(lane._sink, DiscardSink)
        assert runtime.realtime_gateway is None, "text mode opens no listener at all"
        assert runtime.realtime_driver is not None
        assert runtime.realtime_driver.running is False, "nothing pumps until a session exists"
    finally:
        runtime.close()


def test_the_panel_token_is_what_arms_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed: no panel, no token, no session — and it says so."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_snapshot()["panel_token_bound"] is False
        with pytest.raises(RuntimeError) as caught:
            runtime.submit_realtime_text("hello")
        assert "handshake token" in str(caught.value)
        runtime.bind_panel_token("csrf-abc")
        assert runtime.realtime_snapshot()["panel_token_bound"] is True
    finally:
        runtime.close()


def test_submit_realtime_text_refuses_without_a_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(RuntimeError) as caught:
            runtime.submit_realtime_text("hello")
        assert "realtime.yaml" in str(caught.value)
    finally:
        runtime.close()


def test_a_hosted_turn_reaches_the_panel_chat_and_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§C: replies render in the chat panel AND the ledger."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        clock = _Clock()
        # A TEXT-mode turn: the owner item and response.create go up, and the
        # reply comes back with no speech events at all — there is no mic.
        script = handshake() + [
            Step(
                "response.create",
                (
                    transcript_done("resp_1", "item_robot_1", "Warm and quiet."),
                    audio_done("resp_1", "item_robot_1"),
                    response_done("resp_1"),
                ),
                label="text_turn",
            )
        ]

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            _factory.server = FakeRealtimeServer(
                transport=server_end, script=list(script), clock=clock
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token("csrf-abc")
        runtime.submit_realtime_text("how was your day")
        _factory.server.pump()
        lane.pump()

        rows = [(row["speaker"], row["content"]) for row in runtime.agent.memory.realtime_turns()]
        assert ("owner", "how was your day") in rows
        assert ("robot", "Warm and quiet.") in rows
        chat = [(item["role"], item["text"]) for item in runtime.snapshot()["chat"]]
        assert ("user", "how was your day") in chat
        assert ("assistant", "Warm and quiet.") in chat
    finally:
        runtime.close()


def test_a_typed_stop_latches_the_emergency_stop_before_the_cloud_is_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property text mode must not lose."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        lane = runtime.realtime_lane
        clock = _Clock()

        def _factory():
            lane_end, server_end = transport_pair(clock=clock)
            _factory.server = FakeRealtimeServer(
                transport=server_end, script=handshake(), clock=clock
            )
            return lane_end

        lane._transport_factory = _factory
        runtime.bind_panel_token("csrf-abc")
        runtime.submit_realtime_text("Stop.")
        assert runtime.agent.safety.emergency_stopped is True
        assert lane.outcomes[-1].kind == "emergency"
    finally:
        runtime.close()


# =========================== the persona seam (owner directive, 2026-08-18)
def test_a_free_text_persona_replaces_the_profile_block_verbatim() -> None:
    """Personality is prose. Everything that is NOT personality rides along."""

    from parcel_robot.realtime.prompting import (
        ABILITY_WORDING,
        COMPANION_CONTRACT,
        COMPANION_PREAMBLE,
        PERSONA_PROFILE_ID,
        TOOL_TURN_CADENCE,
        render_system_instruction,
        si_guardrails,
    )

    persona = "You are a lively conversational agent that likes to go around New York."
    si = render_system_instruction(profile_id="unused", persona_text=persona)

    assert persona in si.text, "the operator's words, verbatim"
    assert si.text.startswith(COMPANION_PREAMBLE), "the companion framing still leads"
    # The SHIPPED guardrails, not v1's: the persona path and the profile path
    # must carry the same version-selected block, or the owner's free-text
    # persona would quietly run on the prompt R5 exists to replace.
    assert si_guardrails() in si.text, "a persona may not prompt the voice guardrails away"
    assert TOOL_TURN_CADENCE in si.text
    assert ABILITY_WORDING in si.text
    assert COMPANION_CONTRACT in si.text, "the developer-note contract still rides along"
    assert si.profile_id == PERSONA_PROFILE_ID
    assert si.provenance()["si_profile"] == PERSONA_PROFILE_ID

    # Deterministic: same prose in, same bytes and same digest out.
    again = render_system_instruction(profile_id="something-else", persona_text=persona)
    assert again.text == si.text
    assert again.digest == si.digest


@pytest.mark.parametrize("persona", ["", "   ", "\n\t "])
def test_an_empty_persona_is_refused_rather_than_silently_blank(persona: str) -> None:
    from parcel_robot.realtime.prompting import PromptPlaneError, render_system_instruction

    with pytest.raises(PromptPlaneError) as caught:
        render_system_instruction(profile_id="gentle_companion", persona_text=persona)
    assert "persona" in str(caught.value)


def test_the_profile_path_is_byte_identical_when_the_persona_key_is_absent() -> None:
    """The pins in SI_DIGESTS are the proof; this is the same claim, directly."""

    from parcel_robot.realtime.prompting import SI_DIGESTS, SI_VERSION, render_system_instruction

    for profile_id, pinned in SI_DIGESTS[SI_VERSION].items():
        rendered = render_system_instruction(profile_id=profile_id)
        assert rendered.digest == pinned, profile_id
        # Passing persona_text=None explicitly must be the same call.
        assert render_system_instruction(profile_id=profile_id, persona_text=None).text == (
            rendered.text
        )


def test_editing_the_persona_moves_the_session_digest() -> None:
    """S: attribution. A persona edit MUST be visible in the session digest."""

    from parcel_robot.realtime.prompting import DeveloperFlags, render_session_instructions

    flags = DeveloperFlags(
        location="unknown",
        part_of_day="evening",
        local_time="19:40",
        owner_name="the owner",
    )
    first = render_session_instructions(
        profile_id="unused",
        flags=flags,
        persona_text="You are a lively agent that likes to go around New York.",
    )
    second = render_session_instructions(
        profile_id="unused",
        flags=flags,
        persona_text="You are a lively agent that likes to go around New Jersey.",
    )
    assert first.digest != second.digest, "one word changed and the digest did not move"
    assert first.si.digest != second.si.digest
    assert first.di.digest == second.di.digest, "DI is unrelated to the persona"
    assert first.provenance()["instructions_digest"] == first.digest


def test_the_config_carries_a_persona_and_refuses_a_blank_one(tmp_path: Path) -> None:
    from parcel_robot.realtime.config import MAX_PERSONA_CHARS

    path = tmp_path / "realtime.yaml"
    path.write_text(
        'enabled: true\npersona: "You are a lively agent that likes New York."\n',
        encoding="utf-8",
    )
    config = load_realtime_config(path)
    assert config.persona == "You are a lively agent that likes New York."
    assert config.persona_text == config.persona

    assert RealtimeConfig().persona == ""
    assert RealtimeConfig().persona_text is None, "absent ⇒ the preset-profile path"

    path.write_text('enabled: true\npersona: "   "\n', encoding="utf-8")
    with pytest.raises(RealtimeConfigError):
        load_realtime_config(path)

    path.write_text(f"enabled: true\npersona: \"{'x' * (MAX_PERSONA_CHARS + 1)}\"\n", "utf-8")
    with pytest.raises(RealtimeConfigError):
        load_realtime_config(path)


def test_the_runtime_hands_the_config_persona_to_the_prompt_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    config.write_text(
        'enabled: true\nmode: text\n'
        'persona: "You are a lively conversational agent that likes to go around New York."\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        source = runtime.realtime_instructions
        assert source is not None
        assert source.persona_text is not None
        assert "New York" in runtime.realtime_lane.instructions
        assert source.current().si.profile_id == "persona"
    finally:
        runtime.close()


def test_audio_mode_fails_loudly_rather_than_downgrading_to_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator who asked for a microphone must HEAR a build that has none.

    Card R7 shipped R1.6 §A, so this no longer fires on the shipped build — the
    live construction path is pinned in ``test_realtime_audio_gateway.py``. What
    survives is the arm that made this test worth writing: ``websockets`` is an
    OPTIONAL dependency, and a build without it still parses ``mode: audio``
    perfectly happily. That build must refuse at construction rather than
    silently hand the operator a text box, which is exactly the failure they
    would otherwise discover one spoken sentence later.
    """

    real_import = builtins.__import__

    def _no_gateway(name, *args, **kwargs):
        if name == "parcel_robot.realtime.audio_gateway":
            raise ImportError("no module named 'websockets'")
        return real_import(name, *args, **kwargs)

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: audio\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setattr(builtins, "__import__", _no_gateway)
    with pytest.raises(RuntimeError) as caught:
        _runtime(tmp_path)
    assert "mode: text" in str(caught.value)
    assert "browser audio gateway is not" in str(caught.value)
