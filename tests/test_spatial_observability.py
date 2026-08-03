from __future__ import annotations

import io
import math
import subprocess
import time
import wave

import pytest

from parcel_robot import audio_io
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import SpatialIntent, ToolCall
from parcel_robot.navigation.spatial import (
    SpatialBehaviorController,
    parse_spatial_intent,
)
from parcel_robot.observability import ComponentMetrics, LatencyTracker
from parcel_robot.perception import NullMapProvider, PerceptionContract
from parcel_robot.safety import SafetySupervisor


def observation(
    *,
    robot: RobotPose | None = None,
    owner: OwnerTrack | None = None,
) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic(),
        robot=robot or RobotPose(),
        owner=owner or OwnerTrack(x=2.0, visible=True, confidence=1.0),
        backend="test",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Can you walk away from the owner 5 steps?",
            SpatialIntent("move_steps", "away_from_owner", steps=5),
        ),
        ("take three steps backward", SpatialIntent("move_steps", "backward", steps=3)),
        ("walk forward 2 steps", SpatialIntent("move_steps", "forward", steps=2)),
        (
            "walk in a small clockwise circle around me",
            SpatialIntent("orbit_owner", "clockwise", size="small", revolutions=1.0),
        ),
        (
            "walk around the owner 1 time",
            SpatialIntent(
                "orbit_owner",
                "counterclockwise",
                size="normal",
                revolutions=1.0,
            ),
        ),
        (
            "walk around me once",
            SpatialIntent(
                "orbit_owner",
                "counterclockwise",
                size="normal",
                revolutions=1.0,
            ),
        ),
    ],
)
def test_parse_bounded_spatial_intents(text, expected):
    assert parse_spatial_intent(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "don't walk away from the owner 5 steps",
        "do not walk in a circle around me",
        "what happens if you walk away from me five steps",
        "walk away from me many steps",
        "walk away from me 500 steps",
        "walk in a circle around me three times",
        "walk around me 2 times",
    ],
)
def test_spatial_parser_does_not_execute_negated_hypothetical_or_unbounded_text(text):
    assert parse_spatial_intent(text) is None


def test_spatial_parser_accepts_only_explicit_polite_imperatives():
    assert parse_spatial_intent("Parcel, could you please take five steps away from me?") == (
        SpatialIntent("move_steps", "away_from_owner", steps=5)
    )


def test_away_from_owner_aligns_then_reverses_a_bounded_distance():
    controller = SpatialBehaviorController()
    initial = observation(robot=RobotPose(yaw=math.pi / 2.0))
    controller.start(SpatialIntent("move_steps", "away_from_owner", steps=5), initial, now=1.0)

    aligning = controller.step(initial, now=1.1)
    assert aligning.command.vx == 0.0
    assert aligning.command.vyaw < 0.0
    assert aligning.state == "aligning"

    facing_owner = observation(robot=RobotPose(yaw=0.0))
    reversing = controller.step(facing_owner, now=1.2)
    assert reversing.command.vx < 0.0
    assert reversing.command.vy == 0.0

    finished = controller.step(
        observation(robot=RobotPose(x=-1.22, yaw=0.0)),
        now=2.0,
    )
    assert finished.done
    assert finished.reason == "distance_reached"


def test_owner_relative_behavior_fails_closed_without_camera_track():
    controller = SpatialBehaviorController()
    hidden = observation(owner=OwnerTrack(visible=False, confidence=0.0))
    with pytest.raises(RuntimeError, match="owner_not_visible_to_camera"):
        controller.start(SpatialIntent("orbit_owner", "clockwise"), hidden)


def test_owner_relative_behavior_cancels_if_owner_moves_from_anchor():
    controller = SpatialBehaviorController()
    controller.start(
        SpatialIntent("orbit_owner", "clockwise"),
        observation(owner=OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)),
        now=1.0,
    )
    moved = observation(owner=OwnerTrack(x=0.7, y=0.0, visible=True, confidence=1.0))
    decision = controller.step(moved, now=1.1)
    assert decision.done
    assert decision.reason == "owner_moved_during_spatial_behavior"


def test_spatial_behavior_fails_after_bounded_no_progress_window():
    controller = SpatialBehaviorController()
    initial = observation()
    controller.start(SpatialIntent("move_steps", "forward", steps=2), initial, now=1.0)
    decision = controller.step(initial, now=21.0)
    assert decision.done
    assert decision.reason == "spatial_stalled"


def test_orbit_is_local_and_limited_to_one_revolution():
    intent = parse_spatial_intent("walk in a wide circle around me")
    assert intent == SpatialIntent(
        "orbit_owner",
        "counterclockwise",
        size="wide",
        revolutions=1.0,
    )
    controller = SpatialBehaviorController()
    center_owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        intent,
        observation(robot=RobotPose(x=2.0, y=0.0, yaw=math.pi / 2), owner=center_owner),
        now=1.0,
    )
    snapshot = controller.snapshot()
    assert snapshot["orbit_radius_m"] == 2.0


def test_small_orbit_radius_clears_the_default_owner_safety_envelope():
    config = SpatialBehaviorController().config
    assert config.min_orbit_radius_m == pytest.approx(config.minimum_safe_orbit_radius(0.65))


@pytest.mark.parametrize(
    ("direction", "direction_sign"),
    [("counterclockwise", 1.0), ("clockwise", -1.0)],
)
def test_orbit_progress_completes_one_bounded_revolution(direction, direction_sign):
    controller = SpatialBehaviorController()
    radius = controller.config.min_orbit_radius_m
    owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        SpatialIntent("orbit_owner", direction, size="small"),
        observation(
            robot=RobotPose(x=radius, y=0.0, yaw=direction_sign * math.pi / 2),
            owner=owner,
        ),
        now=1.0,
    )

    decision = None
    for index in range(1, 66):
        angle = direction_sign * index * 0.1
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=radius * math.cos(angle),
                    y=radius * math.sin(angle),
                    yaw=angle + direction_sign * math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + index * 0.1,
        )
        if decision.done:
            break

    assert decision is not None
    assert decision.done
    assert decision.reason == "orbit_complete"
    assert decision.progress == 1.0


def test_orbit_oscillation_does_not_accumulate_forward_progress():
    controller = SpatialBehaviorController()
    radius = controller.config.default_orbit_radius_m
    owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        SpatialIntent("orbit_owner", "counterclockwise"),
        observation(robot=RobotPose(x=radius, yaw=math.pi / 2), owner=owner),
        now=1.0,
    )

    decision = None
    for index in range(80):
        angle = 0.2 if index % 2 == 0 else 0.0
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=radius * math.cos(angle),
                    y=radius * math.sin(angle),
                    yaw=angle + math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + (index + 1) * 0.1,
        )
        assert not decision.done

    assert decision is not None
    assert decision.progress == pytest.approx(0.0, abs=1e-9)
    assert controller.snapshot()["progress"] == pytest.approx(0.0, abs=1e-9)


def test_reverse_orbit_motion_cancels_net_progress():
    controller = SpatialBehaviorController()
    radius = controller.config.default_orbit_radius_m
    owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        SpatialIntent("orbit_owner", "counterclockwise"),
        observation(robot=RobotPose(x=radius, yaw=math.pi / 2), owner=owner),
        now=1.0,
    )

    decision = None
    angles = [0.2, 0.4, 0.6, 0.8, 1.0, 0.8, 0.6]
    for index, angle in enumerate(angles, start=1):
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=radius * math.cos(angle),
                    y=radius * math.sin(angle),
                    yaw=angle + math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + index * 0.1,
        )

    assert decision is not None
    assert not decision.done
    assert decision.progress == pytest.approx(0.6 / (2.0 * math.pi))
    assert controller.snapshot()["progress"] == pytest.approx(0.6)


def test_off_ring_angular_motion_receives_no_orbit_credit():
    controller = SpatialBehaviorController()
    radius = controller.config.default_orbit_radius_m
    off_ring_radius = radius + controller.config.waypoint_tolerance_m + 0.1
    owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        SpatialIntent("orbit_owner", "counterclockwise"),
        observation(robot=RobotPose(x=radius, yaw=math.pi / 2), owner=owner),
        now=1.0,
    )

    decision = None
    for index in range(1, 66):
        angle = index * 0.1
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=off_ring_radius * math.cos(angle),
                    y=off_ring_radius * math.sin(angle),
                    yaw=angle + math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + index * 0.1,
        )
        assert not decision.done

    assert decision is not None
    assert decision.progress == pytest.approx(0.0, abs=1e-9)
    assert controller.snapshot()["progress"] == pytest.approx(0.0, abs=1e-9)


def test_orbit_does_not_complete_away_from_its_terminal_gate():
    controller = SpatialBehaviorController()
    radius = controller.config.default_orbit_radius_m
    off_ring_radius = radius + controller.config.waypoint_tolerance_m + 0.1
    owner = OwnerTrack(x=0.0, y=0.0, visible=True, confidence=1.0)
    controller.start(
        SpatialIntent("orbit_owner", "counterclockwise"),
        observation(robot=RobotPose(x=radius, yaw=math.pi / 2), owner=owner),
        now=1.0,
    )

    decision = None
    step = 0
    for step, index in enumerate(range(1, 62), start=1):
        angle = index * 0.1
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=radius * math.cos(angle),
                    y=radius * math.sin(angle),
                    yaw=angle + math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + step * 0.1,
        )
        assert not decision.done

    # Change phase while outside the credit corridor, then re-enter far from
    # the terminal point. The next on-ring delta puts net progress over 2*pi,
    # but completion must still wait until the robot is near its endpoint.
    for angle in (6.2, 0.5):
        step += 1
        decision = controller.step(
            observation(
                robot=RobotPose(
                    x=off_ring_radius * math.cos(angle),
                    y=off_ring_radius * math.sin(angle),
                    yaw=angle + math.pi / 2,
                ),
                owner=owner,
            ),
            now=1.0 + step * 0.1,
        )
        assert not decision.done

    step += 1
    decision = controller.step(
        observation(
            robot=RobotPose(
                x=radius * math.cos(0.5),
                y=radius * math.sin(0.5),
                yaw=0.5 + math.pi / 2,
            ),
            owner=owner,
        ),
        now=1.0 + step * 0.1,
    )
    assert not decision.done
    step += 1
    decision = controller.step(
        observation(
            robot=RobotPose(
                x=radius * math.cos(0.7),
                y=radius * math.sin(0.7),
                yaw=0.7 + math.pi / 2,
            ),
            owner=owner,
        ),
        now=1.0 + step * 0.1,
    )

    assert not decision.done
    assert controller.snapshot()["progress"] > 2.0 * math.pi


def test_spatial_tool_schema_rejects_unbounded_or_extra_arguments():
    safety = SafetySupervisor({})
    assert safety.validate(
        ToolCall(
            "run_spatial_behavior",
            {"behavior": "move_steps", "direction": "away_from_owner", "steps": 5},
        )
    ).accepted
    assert not safety.validate(
        ToolCall(
            "run_spatial_behavior",
            {
                "behavior": "orbit_owner",
                "direction": "clockwise",
                "size": "town",
                "revolutions": 100,
                "waypoints": [[1000, 1000]],
            },
        )
    ).accepted


def test_latency_tracker_computes_named_e2e_and_component_metrics():
    tracker = LatencyTracker(max_turns=4)
    tracker.start(1, "Hello Parcel", now=10.0)
    tracker.mark(1, "reasoning_start", now=10.1)
    tracker.mark(1, "action_commit_start", now=10.25)
    tracker.mark(1, "action_commit_end", now=10.3)
    tracker.mark(1, "reasoning_response", now=10.4)
    tracker.set_result(1, "Hello!", reasoning_source="model")
    tracker.mark(1, "response_logged", now=10.45)
    tracker.mark(1, "tts_start", now=10.5)
    tracker.mark(1, "tts_first_chunk", now=10.6)
    tracker.mark(1, "audio_first_playback", now=10.7)
    tracker.mark(1, "tts_complete", now=10.8)
    tracker.finalize(1, now=10.8)

    row = tracker.snapshot()["turns"][0]
    assert row["user_query"] == "Hello Parcel"
    assert row["model_response"] == "Hello!"
    assert row["latency_ms"]["UserQueryEndToFirstResponse"] == pytest.approx(450.0)
    assert row["latency_ms"]["UserQueryEndToFirstReasoningResponse"] == pytest.approx(400.0)
    assert row["latency_ms"]["TTSTimeToFirstChunk"] == pytest.approx(100.0)

    components = ComponentMetrics(samples_per_component=2)
    components.observe_ms("SimulatorObserve", 2.0)
    components.observe_ms("SimulatorObserve", 4.0)
    summary = components.snapshot()["SimulatorObserve"]
    assert summary["p50_ms"] == 2.0
    assert summary["latest_ms"] == 4.0


def test_latency_tracker_retains_earliest_provider_token_delivered_late():
    tracker = LatencyTracker(max_turns=2)
    tracker.start(1, "hello", now=10.0)
    tracker.mark(1, "reasoning_start", now=10.1)
    tracker.mark(1, "reasoning_first_output", now=12.0)
    # Provider metrics arrive with the completed response, but carry the actual
    # earlier token timestamp from its streaming reader.
    tracker.mark(1, "reasoning_first_output", now=10.4)
    tracker.mark(1, "reasoning_response", now=12.1)
    tracker.finalize(1, now=12.2)

    row = tracker.snapshot()["turns"][0]
    assert row["latency_ms"]["UserQueryEndToFirstReasoningResponse"] == pytest.approx(400.0)


def test_latency_headline_aggregates_exclude_superseded_and_error_turns():
    tracker = LatencyTracker(max_turns=4)
    tracker.start(1, "completed", now=1.0)
    tracker.mark(1, "reasoning_response", now=1.1)
    tracker.finalize(1, now=1.2)
    tracker.start(2, "cancelled", now=2.0)
    tracker.mark(2, "superseded", now=2.1)
    tracker.finalize(2, now=4.0)

    snapshot = tracker.snapshot()
    assert snapshot["aggregate"]["TurnTotal"]["count"] == 1
    assert snapshot["aggregate_by_status"]["superseded"]["TurnTotal"]["count"] == 1
    assert snapshot["status_counts"] == {"superseded": 1, "completed": 1}


def test_perception_contract_rejects_extra_sensors_and_maps_never_networks():
    contract = PerceptionContract.from_config(
        {
            "spatial_sensors": ["camera", "lidar"],
            "maps": {"provider": "google_maps", "enabled": False},
        }
    )
    snapshot = contract.snapshot(NullMapProvider())
    assert snapshot["reasoning_visibility"]["environment"] == ["camera", "lidar"]
    assert snapshot["reasoning_visibility"]["simulator_ground_truth"] is False
    assert snapshot["maps"] == {
        "provider": "google_maps",
        "status": "placeholder",
        "available": False,
        "data": None,
    }
    with pytest.raises(ValueError, match="unsupported spatial sensors"):
        PerceptionContract.from_config({"spatial_sensors": ["camera", "lidar", "gps"]})
    with pytest.raises(ValueError, match="cannot be enabled"):
        PerceptionContract.from_config(
            {"spatial_sensors": ["camera", "lidar"], "maps": {"enabled": True}}
        )


def test_audio_probe_reports_bluetooth_duplex_without_exposing_device_address(monkeypatch):
    monkeypatch.setattr(audio_io.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        joined = " ".join(command)
        if "arecord -l" in joined:
            output = "card 1: Headset"
        elif "bluetoothctl show" in joined:
            output = "Controller AA:BB:CC:DD:EE:FF\nPowered: yes\n"
        elif "bluetoothctl devices Connected" in joined:
            output = "Device 11:22:33:44:55:66 AirPods\n"
        elif "wpctl status" in joined:
            output = "Sinks:\n * 41. AirPods\nSources:\n * 42. AirPods\nFilters:\n"
        elif "wpctl inspect 41" in joined:
            output = 'device.id = "77"\nnode.name = "bluez_output.private.headset-head-unit"\n'
        elif "wpctl inspect 42" in joined:
            output = 'device.id = "77"\nnode.name = "bluez_input.private.headset-head-unit"\n'
        elif "wpctl inspect 77" in joined:
            output = 'device.api = "bluez5"\napi.bluez5.profile = "headset-head-unit"\n'
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    status = audio_io.detect_audio_devices()

    assert status.bluetooth_controller
    assert status.bluetooth_powered
    assert status.bluetooth_connected
    assert status.bluetooth_duplex_ready
    assert status.transport == "bluetooth_hfp"
    assert "11:22:33:44:55:66" not in str(status.as_dict())


def test_pipewire_audio_uses_default_nodes_and_produces_whisper_wav(monkeypatch):
    commands = []
    monkeypatch.setattr(audio_io.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b"\x01\x00" * 1600, stderr=b"")

    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    adapter = audio_io.PipeWireAudioIO()
    captured = adapter.capture_wav(0.1)
    with wave.open(io.BytesIO(captured), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
    adapter.play_wav(captured)

    assert commands[0][0][0] == "/usr/bin/pw-record"
    assert "--target" not in commands[0][0]
    assert commands[1][0] == ["/usr/bin/pw-play", "-"]
