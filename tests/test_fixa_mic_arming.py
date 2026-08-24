"""FIX-A / F1 + F2: the microphone must not arm into its own loudspeaker.

THE DEFECT THESE TESTS PIN
--------------------------
Arming was gated on STT reachability alone (``runtime.py``: "if
speech_stack.recognizer is not None: MicrophoneVoiceLoop(...)"). On a host with
a PipeWire ``Dummy Output`` sink and ZERO sources, the default capture stream
is wired to the MONITOR of the robot's own speaker sink. The runtime's audio
probe reported ``connected_input: false`` and nothing read it, so the loop
armed, transcribed the robot's own TTS fillers, and answered them as commands
for 669 turns.

WHAT THE MONITOR CHECK CAN AND CANNOT SEE
-----------------------------------------
The identity signal is PipeWire OBJECT METADATA read through ``wpctl inspect``
(``device.class=monitor``, a ``media.class`` ending in ``/sink``,
``stream.monitor`` / ``port.monitor``), with a ``node.name`` suffix as a last,
explicitly-weakest resort. For an explicitly configured PortAudio device the
only available signal is the device NAME, and that is labelled
``confidence="name_only"`` rather than being passed off as metadata.

It CANNOT detect:
  * an ALSA loopback (``snd-aloop``) card wired to a playback stream — it
    presents as genuine capture hardware with a genuine ``Audio/Source`` node;
  * a filter-chain / virtual source that mixes sink audio but declares itself
    ``media.class = Audio/Source`` with no monitor markers;
  * a PHYSICAL loopback — a cable from line-out to line-in, or a real
    microphone sitting next to a real speaker. That is acoustic echo, which is
    a different problem with a different owner (B10), and nothing in this
    module improves it;
  * anything at all when PipeWire tooling is absent: ``wpctl`` missing yields
    ``input_identity="unknown"`` and ``connected_input=False``, which fails
    closed via the no-endpoint gate rather than via the monitor gate.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parcel_robot.audio import devices
from parcel_robot.audio.arming import (
    CODE_ARMED,
    CODE_MONITOR,
    CODE_NO_INPUT_ENDPOINT,
    CODE_NO_RECOGNIZER,
    CODE_OVERRIDE,
    CaptureIdentity,
    capture_identity,
    decide_microphone_arming,
    resolve_allow_monitor_capture,
)
from parcel_robot.audio.devices import AudioDeviceStatus, detect_audio_devices
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.providers import SpeechStack, build_speech_stack

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "fixa-mic-arming"


# --------------------------------------------------------------- fixtures
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
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
        del transcript, tools, context
        return AgentDecision("no planning in this test")


class _Recognizer:
    """Stands in for a reachable whisper.cpp. Never opens a device."""

    def transcribe(self, wav: bytes) -> str:  # pragma: no cover - never called
        del wav
        return ""


def _audio(
    *,
    connected_input: bool,
    is_monitor: bool = False,
    identity: str = "media.class=Audio/Source",
) -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="available" if connected_input else "text mode",
        driver="test",
        capture_hardware=True,
        connected_input=connected_input,
        connected_output=True,
        detail=(
            "Audio input and output endpoints are connected."
            if connected_input
            else "ALSA hardware and drivers are installed, but no microphone/speaker "
            "endpoint is connected; using streaming text."
        ),
        input_is_monitor=is_monitor,
        input_identity=identity,
    )


def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, audio, speech: str = ""):
    """A real RobotRuntime with a reachable-looking recognizer.

    ``build_speech_stack`` is patched rather than the arming gate, so the test
    exercises the production construction path: whether the loop is built at
    all is the only thing under test.
    """

    from parcel_robot import runtime as runtime_module

    def _stack(config):
        real = build_speech_stack(config)
        return SpeechStack(
            recognizer=_Recognizer(),  # type: ignore[arg-type]
            synthesizer=real.synthesizer,
            mode=real.mode,
            stt_detail="whisper.cpp (test double)",
            tts_detail=real.tts_detail,
        )

    monkeypatch.setattr(runtime_module, "build_speech_stack", _stack)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "fixa.yaml"
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
poses: {{}}
modules: []
{speech}""",
        encoding="utf-8",
    )
    return runtime_module.RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=audio,
    )


# --------------------------------------------------------- F1: the gate
def test_no_input_endpoint_refuses_to_arm_and_says_why() -> None:
    """The storm condition: probe says no capture endpoint exists."""

    decision = decide_microphone_arming(
        recognizer_available=True,
        audio_status=_audio(connected_input=False, identity="no default node"),
        identity=CaptureIdentity(source="pipewire", signal="no default node"),
    )
    assert decision.armed is False
    assert decision.code == CODE_NO_INPUT_ENDPOINT
    assert "no connected input endpoint" in decision.reason
    assert decision.reason.count("\n") == 0


def test_monitor_identity_refuses_to_arm_even_with_a_connected_endpoint() -> None:
    identity = CaptureIdentity(
        name="system default",
        is_monitor=True,
        signal="device.class=monitor",
        source="pipewire",
        confidence="metadata",
    )
    decision = decide_microphone_arming(
        recognizer_available=True,
        audio_status=_audio(connected_input=True, is_monitor=True, identity="device.class=monitor"),
        identity=identity,
    )
    assert decision.armed is False
    assert decision.code == CODE_MONITOR
    assert "device.class=monitor" in decision.reason
    assert "allow_monitor_capture" in decision.reason


def test_real_input_device_arms_exactly_as_before() -> None:
    decision = decide_microphone_arming(
        recognizer_available=True,
        audio_status=_audio(connected_input=True),
        identity=CaptureIdentity(
            name="system default",
            signal="media.class=Audio/Source",
            source="pipewire",
            confidence="metadata",
        ),
    )
    assert decision.armed is True
    assert decision.code == CODE_ARMED
    assert decision.override is False


def test_missing_recognizer_still_reports_a_reason() -> None:
    decision = decide_microphone_arming(
        recognizer_available=False,
        audio_status=_audio(connected_input=True),
        identity=CaptureIdentity(),
    )
    assert decision.armed is False
    assert decision.code == CODE_NO_RECOGNIZER


@pytest.mark.parametrize(
    ("connected_input", "is_monitor", "identity_signal"),
    [
        (False, False, "no default node"),
        (True, True, "device.class=monitor"),
    ],
)
def test_override_arms_both_gates_and_is_never_silent(
    connected_input: bool, is_monitor: bool, identity_signal: str
) -> None:
    """A deliberate loopback rig opts in — loudly. Fail closed, never silent."""

    decision = decide_microphone_arming(
        recognizer_available=True,
        audio_status=_audio(
            connected_input=connected_input, is_monitor=is_monitor, identity=identity_signal
        ),
        identity=CaptureIdentity(is_monitor=is_monitor, signal=identity_signal, source="pipewire"),
        allow_monitor_capture=True,
    )
    assert decision.armed is True
    assert decision.override is True
    assert decision.code == CODE_OVERRIDE
    assert "own speech" in decision.reason


def test_override_must_be_a_boolean() -> None:
    assert resolve_allow_monitor_capture({}) is False
    assert resolve_allow_monitor_capture({"allow_monitor_capture": True}) is True
    with pytest.raises(ValueError, match="must be a boolean"):
        resolve_allow_monitor_capture({"allow_monitor_capture": "yes"})


def test_speech_config_accepts_the_override_key() -> None:
    """Unknown speech keys fail closed, so the new key must be declared."""

    stack = build_speech_stack(
        {"mode": "text", "allow_monitor_capture": True, "stt_provider": "none"}
    )
    assert stack.mode == "text"


# --------------------------------------- F1: identity, by metadata not name
_DUMMY_SINK_INSPECT = """id 67, type PipeWire:Interface:Node
    audio.channels = "2"
  * client.id = "35"
    factory.name = "support.null-audio-sink"
  * media.class = "Audio/Sink"
  * node.description = "Dummy Output"
  * node.name = "auto_null"
  * object.serial = "2799"
"""

_REAL_SOURCE_INSPECT = """id 88, type PipeWire:Interface:Node
  * device.id = "51"
  * media.class = "Audio/Source"
  * node.description = "ReSpeaker 4 Mic Array"
  * node.name = "alsa_input.usb-SEEED_ReSpeaker"
"""

_REAL_DEVICE_INSPECT = """id 51, type PipeWire:Interface:Device
  * device.api = "alsa"
  * device.name = "alsa_card.usb-SEEED_ReSpeaker"
"""

_MONITOR_SOURCE_INSPECT = """id 90, type PipeWire:Interface:Node
  * device.id = "51"
    device.class = "monitor"
  * media.class = "Audio/Source"
  * node.name = "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
"""


def _wpctl_probe(monkeypatch: pytest.MonkeyPatch, *, status: str, inspects: dict[str, str]):
    monkeypatch.setattr(devices.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _fake(command: list[str], *, max_chars: int = 16_384) -> str:
        del max_chars
        if command[1:2] == ["status"]:
            return status
        if command[1:2] == ["inspect"]:
            return inspects.get(command[2], "")
        return ""

    monkeypatch.setattr(devices, "_command_output", _fake)
    monkeypatch.setattr(
        devices.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no arecord in this test")),
    )


def test_probe_flags_a_sink_default_source_as_a_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    """media.class=Audio/Sink reached as the default SOURCE == monitor capture."""

    status = "Sinks:\n *   67. Dummy Output\nSources:\n *   67. Dummy Output\nFilters:\n"
    _wpctl_probe(monkeypatch, status=status, inspects={"67": _DUMMY_SINK_INSPECT})
    probe = detect_audio_devices()
    assert probe.connected_input is True
    assert probe.input_is_monitor is True
    assert probe.input_identity == "media.class=Audio/Sink"


def test_probe_flags_device_class_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    status = "Sinks:\n *   67. Dummy Output\nSources:\n *   90. Monitor\nFilters:\n"
    _wpctl_probe(
        monkeypatch,
        status=status,
        inspects={
            "90": _MONITOR_SOURCE_INSPECT,
            "51": _REAL_DEVICE_INSPECT,
            "67": _DUMMY_SINK_INSPECT,
        },
    )
    probe = detect_audio_devices()
    assert probe.input_is_monitor is True
    assert probe.input_identity == "device.class=monitor"


def test_probe_leaves_a_real_microphone_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    status = "Sinks:\n *   67. Dummy Output\nSources:\n *   88. ReSpeaker\nFilters:\n"
    _wpctl_probe(
        monkeypatch,
        status=status,
        inspects={
            "88": _REAL_SOURCE_INSPECT,
            "51": _REAL_DEVICE_INSPECT,
            "67": _DUMMY_SINK_INSPECT,
        },
    )
    probe = detect_audio_devices()
    assert probe.connected_input is True
    assert probe.input_is_monitor is False
    assert probe.input_identity == "media.class=Audio/Source"


def test_explicit_portaudio_device_name_is_weak_evidence_and_labelled_so() -> None:
    """A configured device is not the default: only its NAME is left."""

    identity = capture_identity(
        audio_status=_audio(connected_input=True),
        device_detail="Monitor of Built-in Audio (index 4)",
        device_index=4,
    )
    assert identity.is_monitor is True
    assert identity.confidence == "name_only"
    assert identity.source == "portaudio"

    honest = capture_identity(
        audio_status=_audio(connected_input=True),
        device_detail="ReSpeaker 4 Mic Array (index 2)",
        device_index=2,
    )
    assert honest.is_monitor is False
    assert honest.confidence == "name_only"


def test_probe_verdict_does_not_leak_onto_an_explicitly_configured_device() -> None:
    """The probe classifies the DEFAULT; a named device is a different object."""

    identity = capture_identity(
        audio_status=_audio(connected_input=True, is_monitor=True, identity="device.class=monitor"),
        device_detail="ReSpeaker 4 Mic Array (index 2)",
        device_index=2,
    )
    assert identity.is_monitor is False
    assert identity.source == "portaudio"


# ----------------------------------------------- F1: the product path
def test_runtime_does_not_arm_the_microphone_without_an_input_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the storm's arming condition end to end."""

    runtime = _runtime(
        tmp_path, monkeypatch, audio=_audio(connected_input=False, identity="no default node")
    )
    try:
        assert runtime.speech_stack.recognizer is not None, "STT is reachable in this fixture"
        assert runtime._microphone_loop is None, "mic loop armed with no capture endpoint"
        speech = runtime.snapshot()["speech"]
        assert speech["microphone_active"] is False
        assert speech["mic_arming"]["armed"] is False
        assert speech["mic_arming"]["code"] == CODE_NO_INPUT_ENDPOINT
        assert "no connected input endpoint" in speech["mic_arming"]["reason"]
    finally:
        runtime.close()


def test_runtime_does_not_arm_onto_a_sink_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(
        tmp_path,
        monkeypatch,
        audio=_audio(connected_input=True, is_monitor=True, identity="media.class=Audio/Sink"),
    )
    try:
        assert runtime._microphone_loop is None, "mic loop armed onto its own speaker monitor"
        arming = runtime.snapshot()["speech"]["mic_arming"]
        assert arming["code"] == CODE_MONITOR
        assert arming["capture_device"]["signal"] == "media.class=Audio/Sink"
    finally:
        runtime.close()


def test_runtime_arms_on_a_real_capture_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unchanged path: a genuine source still arms, with no new conditions."""

    runtime = _runtime(tmp_path, monkeypatch, audio=_audio(connected_input=True))
    try:
        assert runtime._microphone_loop is not None, "a real capture endpoint must still arm"
        arming = runtime.snapshot()["speech"]["mic_arming"]
        assert arming["armed"] is True
        assert arming["code"] == CODE_ARMED
        assert arming["override"] is False
    finally:
        runtime.close()


def test_runtime_override_arms_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="parcel_robot.runtime"):
        runtime = _runtime(
            tmp_path,
            monkeypatch,
            audio=_audio(connected_input=False, identity="no default node"),
            speech="speech:\n  allow_monitor_capture: true\n",
        )
    try:
        assert runtime._microphone_loop is not None, "the override must still be able to arm"
        arming = runtime.snapshot()["speech"]["mic_arming"]
        assert arming["armed"] is True
        assert arming["override"] is True
        assert any("allow_monitor_capture" in record.getMessage() for record in caplog.records), (
            "an override must be logged as a WARNING, never silently"
        )
    finally:
        runtime.close()


# --------------------------------------------------- F2: observability
def test_startup_reports_the_resolved_speech_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path, monkeypatch, audio=_audio(connected_input=True))
    try:
        stack = runtime.snapshot()["speech"]["stack"]
        assert stack["config_path"].endswith("fixa.yaml")
        assert stack["endpointing"]["requested"] == "energy"
        assert stack["endpointing"]["semantic_loaded"] is False
        assert stack["aec"]["constructed"] is False
        assert stack["capture_device"]["name"] == "system default"
        assert stack["capture_device"]["is_monitor"] is False
        # The models the config would have to name are reported by path, so a
        # "which weights?" question never needs a second command.
        assert "silero_vad_v6.onnx" in stack["endpointing"]["models"]["vad_model"]
    finally:
        runtime.close()


def test_warns_once_when_the_tuned_semantic_stack_is_present_but_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The exact silence that let a missing --config downgrade turn-taking."""

    models_present = (REPO / "models" / "endpointing" / "silero_vad_v6.onnx").is_file()
    if not models_present:
        pytest.skip("semantic endpointing weights are not installed on this host")
    with caplog.at_level(logging.WARNING, logger="parcel_robot.runtime"):
        runtime = _runtime(tmp_path, monkeypatch, audio=_audio(connected_input=True))
    try:
        warnings = [
            record.getMessage()
            for record in caplog.records
            if "Semantic endpointing models are present" in record.getMessage()
        ]
        assert len(warnings) == 1, f"expected exactly one warning, got {warnings}"
        assert "NOT running" in warnings[0]
    finally:
        runtime.close()


def test_semantic_config_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    if not (REPO / "models" / "endpointing" / "silero_vad_v6.onnx").is_file():
        pytest.skip("semantic endpointing weights are not installed on this host")
    speech = (
        "speech:\n"
        "  endpointing: semantic\n"
        "  vad_model: models/endpointing/silero_vad_v6.onnx\n"
        "  turn_model: models/endpointing/smart_turn_v3.onnx\n"
    )
    with caplog.at_level(logging.WARNING, logger="parcel_robot.runtime"):
        runtime = _runtime(tmp_path, monkeypatch, audio=_audio(connected_input=True), speech=speech)
    try:
        stack = runtime.snapshot()["speech"]["stack"]
        assert stack["endpointing"]["requested"] == "semantic"
        assert not [
            record
            for record in caplog.records
            if "Semantic endpointing models are present" in record.getMessage()
        ]
    finally:
        runtime.close()
