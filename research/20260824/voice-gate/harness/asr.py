#!/usr/bin/env python
"""The local ASR this study uses, and the one number that matters about it.

``whisper.cpp``'s ``whisper-server`` holding ``models/whisper/ggml-base.en.bin``
resident on a private port, so a transcription is one HTTP round trip rather
than a process start (a fresh ``whisper-cli`` costs ~550 ms of model load and
would make every latency row a measurement of disk).

Nothing here reaches the network: the server is on 127.0.0.1 and the study
spends $0 hosted.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from io import BytesIO

import numpy as np

DEFAULT_URL = "http://127.0.0.1:8099/inference"
RATE_HZ = 16_000


def wav_bytes(samples: np.ndarray, rate_hz: int = RATE_HZ) -> bytes:
    payload = np.clip(np.rint(np.asarray(samples) * 32768.0), -32768, 32767).astype("<i2")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate_hz)
        handle.writeframes(payload.tobytes())
    return buffer.getvalue()


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_s: float

    @property
    def normalized(self) -> str:
        return re.sub(r"[^a-z ]+", " ", self.text.lower()).strip()

    def words(self) -> list[str]:
        return [word for word in self.normalized.split() if word]


class WhisperClient:
    """One resident whisper-server, spoken to over loopback HTTP."""

    def __init__(self, url: str = DEFAULT_URL, *, timeout_s: float = 30.0) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.calls = 0
        self.total_latency_s = 0.0

    def available(self) -> bool:
        try:
            self.transcribe(np.zeros(RATE_HZ // 2))
        except (urllib.error.URLError, OSError, TimeoutError):
            return False
        return True

    def transcribe(self, samples: np.ndarray, rate_hz: int = RATE_HZ) -> Transcript:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = [
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"w.wav\"\r\nContent-Type: audio/wav\r\n\r\n"
            ).encode(),
            wav_bytes(samples, rate_hz),
            b"\r\n",
        ]
        for name, value in (
            ("temperature", "0.0"),
            ("response_format", "json"),
            ("no_timestamps", "true"),
        ):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n".encode()
            )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latency = time.perf_counter() - started
        self.calls += 1
        self.total_latency_s += latency
        return Transcript(text=str(payload.get("text", "")).strip(), latency_s=latency)


__all__ = ["DEFAULT_URL", "RATE_HZ", "Transcript", "WhisperClient", "wav_bytes"]
