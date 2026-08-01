from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AgentDecision, ToolCall


class LanguageModel(Protocol):
    def decide(
        self,
        transcript: str,
        tools: list[dict[str, Any]],
        context: list[dict[str, str]],
    ) -> AgentDecision: ...


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> bytes: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, wav_audio: bytes) -> str: ...


@dataclass
class LlamaCppProvider:
    """OpenAI-compatible llama.cpp server adapter with strict JSON output."""

    base_url: str = "http://127.0.0.1:8080"
    model: str = "gemma"
    timeout: float = 30.0

    def decide(
        self,
        transcript: str,
        tools: list[dict[str, Any]],
        context: list[dict[str, str]],
    ) -> AgentDecision:
        system = (
            "You are Parcel, a robot dog. Respond with exactly one JSON object: "
            '{"reply":"short spoken reply","tool_calls":[{"name":"tool","arguments":{}}]}. '
            "Only use the supplied tools. Never invent poses or joint values. "
            "A request can be refused by returning an empty tool_calls list.\n"
            f"TOOLS={json.dumps(tools, separators=(',', ':'))}"
        )
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                *context[-8:],
                {"role": "user", "content": transcript},
            ],
            "response_format": {"type": "json_object"},
        }
        response = _post_json(
            f"{self.base_url.rstrip('/')}/v1/chat/completions", payload, self.timeout
        )
        content = response["choices"][0]["message"]["content"]
        return parse_model_decision(content)


@dataclass
class CsmSpeechProvider:
    """Adapter for an isolated CSM HTTP service returning WAV bytes."""

    base_url: str = "http://127.0.0.1:8090"
    speaker: int = 0
    timeout: float = 60.0

    def synthesize(self, text: str) -> bytes:
        payload = json.dumps({"text": text, "speaker": self.speaker}).encode()
        request = Request(
            f"{self.base_url.rstrip('/')}/synthesize",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(f"CSM service request failed: {error}") from error


@dataclass
class WhisperCppProvider:
    """Adapter for whisper.cpp's multipart `/inference` endpoint."""

    base_url: str = "http://127.0.0.1:8178"
    language: str = "en"
    timeout: float = 60.0

    def transcribe(self, wav_audio: bytes) -> str:
        boundary = "parcel-whisper-boundary"
        fields = [
            _multipart_field(boundary, "response_format", "json"),
            _multipart_field(boundary, "language", self.language),
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode()
            + wav_audio
            + b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        request = Request(
            f"{self.base_url.rstrip('/')}/inference",
            data=b"".join(fields),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(f"Whisper service request failed: {error}") from error
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str):
            raise TypeError("Whisper service response did not contain text")
        return text.strip()


def parse_model_decision(content: str) -> AgentDecision:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("model response was not valid JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        raise TypeError("model response must contain a string reply")
    raw_calls = data.get("tool_calls", [])
    if not isinstance(raw_calls, list) or len(raw_calls) > 4:
        raise ValueError("model response tool_calls must be a list of at most four calls")
    calls = []
    for item in raw_calls:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise TypeError("each tool call must contain a name")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be an object")
        calls.append(ToolCall(item["name"], arguments))
    return AgentDecision(data["reply"].strip(), tuple(calls))


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"language-model request failed: {error}") from error
    if not isinstance(result, dict):
        raise TypeError("language-model server returned an invalid response")
    return result


def _multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode()
