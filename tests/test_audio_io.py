from __future__ import annotations

import subprocess

from parcel_robot import audio_io


def _install_probe(
    monkeypatch,
    responses: dict[tuple[str, ...], str],
) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(audio_io.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        command_key = tuple(command)
        commands.append(command_key)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 2
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=responses.get(command_key, ""),
            stderr="",
        )

    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    return commands


def _base_responses() -> dict[tuple[str, ...], str]:
    return {
        ("/usr/bin/arecord", "-l"): "card 1: Audio\n",
        ("/usr/bin/bluetoothctl", "show"): "Controller private\nPowered: yes\n",
        ("/usr/bin/bluetoothctl", "devices", "Connected"): (
            "Device 11:22:33:44:55:66 Input Device\n"
        ),
        ("/usr/bin/wpctl", "status"): (
            "Sinks:\n * 41. Default output\nSources:\n * 42. Default input\nFilters:\n"
        ),
    }


def test_unrelated_bluetooth_connection_does_not_make_alsa_defaults_duplex(monkeypatch):
    responses = _base_responses()
    responses.update(
        {
            ("/usr/bin/wpctl", "inspect", "41"): 'device.id = "70"\n',
            ("/usr/bin/wpctl", "inspect", "42"): 'device.id = "70"\n',
            ("/usr/bin/wpctl", "inspect", "70"): (
                'device.api = "alsa"\ndevice.profile.name = "analog-stereo"\n'
            ),
        }
    )
    _install_probe(monkeypatch, responses)

    status = audio_io.detect_audio_devices()

    assert status.connected_input
    assert status.connected_output
    assert status.bluetooth_connected
    assert not status.bluetooth_duplex_ready
    assert status.transport == "pipewire"
    assert "11:22:33:44:55:66" not in str(status.as_dict())


def test_a2dp_output_with_separate_input_is_not_bluetooth_duplex(monkeypatch):
    responses = _base_responses()
    responses.update(
        {
            ("/usr/bin/wpctl", "inspect", "41"): (
                'device.id = "77"\nnode.name = "bluez_output.private.a2dp-sink"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "42"): 'device.id = "70"\n',
            ("/usr/bin/wpctl", "inspect", "70"): 'device.api = "alsa"\n',
            ("/usr/bin/wpctl", "inspect", "77"): (
                'device.api = "bluez5"\napi.bluez5.profile = "a2dp-sink"\n'
            ),
        }
    )
    _install_probe(monkeypatch, responses)

    status = audio_io.detect_audio_devices()

    assert not status.bluetooth_duplex_ready
    assert status.transport == "bluetooth_a2dp"


def test_hfp_defaults_must_resolve_to_same_bluez_device(monkeypatch):
    responses = _base_responses()
    responses.update(
        {
            ("/usr/bin/wpctl", "inspect", "41"): (
                'device.id = "77"\nnode.name = "bluez_output.private.headset-head-unit"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "42"): (
                'device.id = "76"\nnode.name = "bluez_input.private.headset-head-unit"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "76"): (
                'device.api = "bluez5"\napi.bluez5.profile = "headset-head-unit"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "77"): (
                'device.api = "bluez5"\napi.bluez5.profile = "headset-head-unit"\n'
            ),
        }
    )
    _install_probe(monkeypatch, responses)

    status = audio_io.detect_audio_devices()

    assert not status.bluetooth_duplex_ready
    assert status.transport == "bluetooth"


def test_hfp_probe_is_read_only_bounded_and_caches_parent_device(monkeypatch):
    responses = _base_responses()
    responses.update(
        {
            ("/usr/bin/wpctl", "inspect", "41"): (
                'device.id = "77"\nnode.name = "bluez_output.private.hfp_hf"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "42"): (
                'device.id = "77"\nnode.name = "bluez_input.private.hfp_hf"\n'
            ),
            ("/usr/bin/wpctl", "inspect", "77"): (
                'device.api = "bluez5"\napi.bluez5.profile = "hfp_hf"\n'
            ),
        }
    )
    commands = _install_probe(monkeypatch, responses)

    status = audio_io.detect_audio_devices()

    assert status.bluetooth_duplex_ready
    assert status.transport == "bluetooth_hfp"
    assert commands.count(("/usr/bin/wpctl", "inspect", "77")) == 1
    assert len(commands) == 7
    assert all(
        " ".join(command).casefold().find(action) == -1
        for command in commands
        for action in (" pair ", " connect ", " scan ", " power ")
    )


def test_dummy_nondefault_does_not_hide_real_default_output(monkeypatch):
    responses = _base_responses()
    responses[("/usr/bin/wpctl", "status")] = (
        "Sinks:\n   38. Dummy Output\n * 41. Speakers\nSources:\n * 42. Microphone\nFilters:\n"
    )
    responses.update(
        {
            ("/usr/bin/wpctl", "inspect", "41"): 'device.id = "70"\n',
            ("/usr/bin/wpctl", "inspect", "42"): 'device.id = "70"\n',
            ("/usr/bin/wpctl", "inspect", "70"): 'device.api = "alsa"\n',
        }
    )
    _install_probe(monkeypatch, responses)

    status = audio_io.detect_audio_devices()

    assert status.connected_output
    assert status.transport == "pipewire"
