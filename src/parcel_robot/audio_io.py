from __future__ import annotations

import io
import re
import shutil
import subprocess
import time
import wave
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class AudioDeviceStatus:
    status: str
    driver: str
    capture_hardware: bool
    connected_input: bool
    connected_output: bool
    detail: str
    bluetooth_controller: bool = False
    bluetooth_powered: bool = False
    bluetooth_connected: bool = False
    bluetooth_duplex_ready: bool = False
    transport: str = "none"
    #: True when the DEFAULT capture endpoint is the monitor of a playback
    #: sink — i.e. a capture stream would record the machine's own output.
    #: Decided from PipeWire node/device metadata, never from a name alone
    #: (see ``_monitor_signal``); ``input_identity`` names the deciding signal.
    input_is_monitor: bool = False
    input_identity: str = "unknown"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _PipeWireEndpoint:
    node_id: str | None = None
    device_id: str | None = None
    bluetooth: bool = False
    headset_profile: bool = False
    a2dp_profile: bool = False
    #: Monitor-of-a-sink capture endpoint, plus the metadata key that decided.
    monitor: bool = False
    identity: str = "unknown"


def detect_audio_devices() -> AudioDeviceStatus:
    """Inspect audio non-destructively and choose audio or text-only operation."""
    arecord = shutil.which("arecord")
    aplay = shutil.which("aplay")
    capture_hardware = False
    if arecord:
        try:
            result = subprocess.run(
                [arecord, "-l"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            capture_hardware = "card " in result.stdout.lower()
        except (OSError, subprocess.TimeoutExpired):
            capture_hardware = False

    bluetooth_controller = False
    bluetooth_powered = False
    bluetooth_connected = False
    bluetoothctl = shutil.which("bluetoothctl")
    if bluetoothctl:
        controller_status = _command_output([bluetoothctl, "show"])
        bluetooth_controller = "Controller " in controller_status
        bluetooth_powered = "Powered: yes" in controller_status
        connected_status = _command_output([bluetoothctl, "devices", "Connected"])
        # Do not retain device addresses or names in telemetry.
        bluetooth_connected = any(
            line.strip().startswith("Device ") for line in connected_status.splitlines()
        )

    connected_input = False
    connected_output = False
    default_input = _PipeWireEndpoint()
    default_output = _PipeWireEndpoint()
    wpctl = shutil.which("wpctl")
    if wpctl:
        status = _command_output([wpctl, "status"])
        if status:
            source_block = (
                status.split("Sources:", 1)[1].split("Filters:", 1)[0]
                if "Sources:" in status
                else ""
            )
            sink_block = (
                status.split("Sinks:", 1)[1].split("Sources:", 1)[0] if "Sinks:" in status else ""
            )
            input_id = _default_node_id(source_block)
            output_id = _default_node_id(sink_block)
            connected_input = input_id is not None
            connected_output = output_id is not None and not _node_is_dummy_output(
                sink_block, output_id
            )
            default_input, default_output = _inspect_pipewire_endpoints(
                wpctl,
                input_id if connected_input else None,
                output_id if connected_output else None,
            )

    bluetooth_connected = bluetooth_connected or default_input.bluetooth or default_output.bluetooth
    bluetooth_duplex = (
        connected_input
        and connected_output
        and default_input.bluetooth
        and default_output.bluetooth
        and default_input.device_id is not None
        and default_input.device_id == default_output.device_id
        and default_input.headset_profile
        and default_output.headset_profile
    )
    transport = (
        "bluetooth_hfp"
        if bluetooth_duplex
        else "bluetooth_a2dp"
        if connected_output and default_output.bluetooth and default_output.a2dp_profile
        else "bluetooth"
        if default_input.bluetooth or default_output.bluetooth
        else "pipewire"
        if connected_input or connected_output
        else "none"
    )
    if connected_input and connected_output:
        endpoint_detail = (
            "A Bluetooth headset is connected for duplex input/output. Microphone use may "
            "switch playback from A2DP to the lower-bandwidth HFP/HSP profile."
            if bluetooth_duplex
            else "Audio input and output endpoints are connected."
        )
        return AudioDeviceStatus(
            "available",
            "PipeWire/ALSA",
            capture_hardware,
            True,
            True,
            endpoint_detail,
            bluetooth_controller,
            bluetooth_powered,
            bluetooth_connected,
            bluetooth_duplex,
            transport,
            default_input.monitor,
            default_input.identity,
        )
    detail = (
        "ALSA hardware and drivers are installed, but no microphone/speaker endpoint "
        "is connected; using streaming text."
        if capture_hardware
        else "No ALSA capture hardware was detected; using streaming text."
    )
    return AudioDeviceStatus(
        "text mode",
        "PipeWire/ALSA" if arecord or aplay else "unavailable",
        capture_hardware,
        connected_input,
        connected_output,
        detail,
        bluetooth_controller,
        bluetooth_powered,
        bluetooth_connected,
        bluetooth_duplex,
        transport,
        default_input.monitor,
        default_input.identity,
    )


def _command_output(command: list[str], *, max_chars: int = 16_384) -> str:
    """Run one fixed, read-only probe with bounded time and retained output."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout[:max_chars]


def _default_node_id(status_block: str) -> str | None:
    """Return the numeric ID of a starred PipeWire default node."""
    for line in status_block.splitlines():
        match = re.search(r"\*\s+(\d+)\.", line)
        if match:
            return match.group(1)
    return None


def _node_is_dummy_output(status_block: str, node_id: str) -> bool:
    for line in status_block.splitlines():
        match = re.search(r"\*\s+(\d+)\.", line)
        if match and match.group(1) == node_id:
            return "dummy output" in line.casefold()
    return False


def _inspect_pipewire_endpoints(
    wpctl: str,
    input_id: str | None,
    output_id: str | None,
) -> tuple[_PipeWireEndpoint, _PipeWireEndpoint]:
    """Resolve default nodes to their parent devices without exposing identifiers."""
    cache: dict[str, str] = {}

    def inspect(object_id: str) -> str:
        if not object_id.isdecimal():
            return ""
        if object_id not in cache:
            cache[object_id] = _command_output([wpctl, "inspect", object_id])
        return cache[object_id]

    def endpoint(node_id: str | None, *, capture: bool = False) -> _PipeWireEndpoint:
        # ``capture`` gates the monitor verdict: "this object is a sink" is only
        # damning for the endpoint we would RECORD from. The playback default is
        # supposed to be a sink.
        if node_id is None or not node_id.isdecimal():
            return _PipeWireEndpoint(identity="no default node")
        node = inspect(node_id)
        if not node:
            return _PipeWireEndpoint(node_id=node_id, identity="node not inspectable")
        device_id = _inspect_property(node, "device.id")
        if device_id is None or not device_id.isdecimal():
            monitor, identity = _monitor_signal(node)
            return _PipeWireEndpoint(
                node_id=node_id, monitor=monitor and capture, identity=identity
            )
        device = inspect(device_id)
        combined = f"{node}\n{device}"
        monitor, identity = _monitor_signal(combined)
        monitor = monitor and capture
        device_api = _inspect_property(device, "device.api") or _inspect_property(
            node, "device.api"
        )
        bluetooth = device_api.casefold() == "bluez5" if device_api else False
        profiles = " ".join(
            value
            for key in (
                "api.bluez5.profile",
                "bluez5.profile",
                "device.profile.name",
                "device.profile.description",
                "node.name",
            )
            if (value := _inspect_property(combined, key)) is not None
        ).casefold()
        normalized_profiles = profiles.replace("_", "-").replace("/", "-")
        headset_profile = bluetooth and any(
            token in normalized_profiles
            for token in (
                "headset-head-unit",
                "handsfree-head-unit",
                "headset-audio-gateway",
                "handsfree-audio-gateway",
                "hfp-hf",
                "hfp-ag",
                "hsp-hs",
                "hsp-ag",
            )
        )
        return _PipeWireEndpoint(
            node_id=node_id,
            device_id=device_id,
            bluetooth=bluetooth,
            headset_profile=headset_profile,
            a2dp_profile=bluetooth and "a2dp" in normalized_profiles,
            monitor=monitor,
            identity=identity,
        )

    return endpoint(input_id, capture=True), endpoint(output_id)


def _monitor_signal(inspection: str) -> tuple[bool, str]:
    """Decide monitor-ness from PipeWire object metadata, not from a name.

    Checked in decreasing order of trust: ``device.class=monitor``, then a
    ``media.class`` ending in ``/sink`` (reached through the *source* default,
    that object's capture side is the sink's monitor ports), then the explicit
    ``stream.monitor`` / ``port.monitor`` booleans. ``node.name`` is consulted
    LAST and only as a suffix, because it is the one field an operator can
    name arbitrarily.

    Returns ``(is_monitor, signal)`` where ``signal`` names the exact property
    that decided, so the runtime can report *why* it refused to arm instead of
    asserting an unfalsifiable "looks like a monitor".
    """

    device_class = _inspect_property(inspection, "device.class")
    if device_class and device_class.casefold() == "monitor":
        return True, "device.class=monitor"
    media_class = _inspect_property(inspection, "media.class")
    if media_class and media_class.casefold().endswith("/sink"):
        # Reached as the default *source*, yet the object is a sink: the
        # capture side of it is the sink's monitor ports.
        return True, f"media.class={media_class}"
    for key in ("stream.monitor", "port.monitor"):
        value = _inspect_property(inspection, key)
        if value and value.casefold() in {"true", "1", "yes"}:
            return True, f"{key}={value}"
    node_name = _inspect_property(inspection, "node.name")
    if node_name and node_name.casefold().endswith(".monitor"):
        return True, f"node.name={node_name}"
    if media_class:
        return False, f"media.class={media_class}"
    if node_name:
        return False, f"node.name={node_name}"
    return False, "no monitor metadata"


def _inspect_property(inspection: str, key: str) -> str | None:
    match = re.search(
        rf"^\s*\*?\s*{re.escape(key)}\s*=\s*(?:\"([^\"]*)\"|(\S+))\s*$",
        inspection,
        flags=re.MULTILINE,
    )
    if match is None:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


class AlsaAudioIO:
    """Direct ALSA fallback for hosts where PortAudio/PipeWire is unavailable.

    The default ALC1220 device exposes 48 kHz stereo capture. Captured PCM is
    downmixed and decimated to the 16 kHz mono WAV expected by speech models.
    A production robot should replace this with an AEC-capable audio transport.
    """

    def __init__(self, capture_device: str = "hw:1,0", playback_device: str = "default"):
        self.capture_device = capture_device
        self.playback_device = playback_device

    def capture_wav(self, duration_s: float = 4.0) -> bytes:
        if not 0.1 <= duration_s <= 30.0:
            raise ValueError("capture duration must be between 0.1 and 30 seconds")
        arecord = shutil.which("arecord")
        if arecord is None:
            raise RuntimeError("arecord is not installed")
        process = subprocess.Popen(
            [
                arecord,
                "-q",
                "-D",
                self.capture_device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                "48000",
                "-c",
                "2",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(duration_s)
            process.terminate()
            raw, stderr = process.communicate(timeout=2)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        if not raw:
            raise RuntimeError(f"audio capture returned no samples: {stderr.decode().strip()}")
        stereo = np.frombuffer(raw, dtype="<i2")
        stereo = stereo[: stereo.size - stereo.size % 2].reshape(-1, 2)
        mono_48k = stereo.astype(np.int32).mean(axis=1)
        usable = mono_48k[: mono_48k.size - mono_48k.size % 3]
        mono_16k = usable.reshape(-1, 3).mean(axis=1).clip(-32768, 32767).astype("<i2")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(mono_16k.tobytes())
        return output.getvalue()

    def play_wav(self, wav_audio: bytes) -> None:
        aplay = shutil.which("aplay")
        if aplay is None:
            raise RuntimeError("aplay is not installed")
        subprocess.run(
            [aplay, "-q", "-D", self.playback_device],
            input=wav_audio,
            timeout=60,
            check=True,
        )


class PipeWireAudioIO:
    """Default-node capture/playback suitable for USB and Bluetooth headsets.

    Device selection remains with PipeWire/WirePlumber, so an AirPods connection
    or HFP profile switch does not require a MAC-address-derived device name in
    Parcel configuration. This adapter captures one bounded utterance; continuous
    VAD/AEC transport remains a higher-level service concern.
    """

    def __init__(self, capture_target: str | None = None, playback_target: str | None = None):
        self.capture_target = capture_target
        self.playback_target = playback_target

    def capture_wav(self, duration_s: float = 4.0) -> bytes:
        if not 0.1 <= duration_s <= 30.0:
            raise ValueError("capture duration must be between 0.1 and 30 seconds")
        recorder = shutil.which("pw-record")
        if recorder is None:
            raise RuntimeError("pw-record is not installed")
        sample_count = max(1, round(duration_s * 16_000))
        command = [
            recorder,
            "--raw",
            "--format",
            "s16",
            "--rate",
            "16000",
            "--channels",
            "1",
            "--sample-count",
            str(sample_count),
        ]
        if self.capture_target:
            command.extend(("--target", self.capture_target))
        command.append("-")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=duration_s + 5.0,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"PipeWire capture failed: {error}") from error
        if not result.stdout:
            raise RuntimeError("PipeWire capture returned no samples")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16_000)
            wav.writeframes(result.stdout)
        return output.getvalue()

    def play_wav(self, wav_audio: bytes) -> None:
        if not wav_audio:
            raise ValueError("playback audio must not be empty")
        player = shutil.which("pw-play")
        if player is None:
            raise RuntimeError("pw-play is not installed")
        command = [player]
        if self.playback_target:
            command.extend(("--target", self.playback_target))
        command.append("-")
        try:
            subprocess.run(
                command,
                input=wav_audio,
                timeout=60,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"PipeWire playback failed: {error}") from error
