from __future__ import annotations

import io
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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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

    connected_input = False
    connected_output = False
    wpctl = shutil.which("wpctl")
    if wpctl:
        try:
            result = subprocess.run(
                [wpctl, "status"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            status = result.stdout
            source_block = (
                status.split("Sources:", 1)[1].split("Filters:", 1)[0]
                if "Sources:" in status
                else ""
            )
            sink_block = (
                status.split("Sinks:", 1)[1].split("Sources:", 1)[0]
                if "Sinks:" in status
                else ""
            )
            connected_input = any(
                line.strip().startswith(("*", "│  *"))
                for line in source_block.splitlines()
            )
            connected_output = "Dummy Output" not in sink_block and any(
                line.strip().startswith(("*", "│  *"))
                for line in sink_block.splitlines()
            )
        except (OSError, subprocess.TimeoutExpired):
            connected_input = connected_output = False

    if connected_input and connected_output:
        return AudioDeviceStatus(
            "available",
            "PipeWire/ALSA",
            capture_hardware,
            True,
            True,
            "Audio input and output endpoints are connected.",
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
    )


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
