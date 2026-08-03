from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ActionProposal, AffectEstimate, AgentDecision, ToolCall


class LanguageModel(Protocol):
    def decide(
        self,
        transcript: str,
        tools: list[dict[str, Any]],
        context: list[dict[str, str]],
    ) -> AgentDecision: ...


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> bytes: ...


class StreamingSpeechSynthesizer(SpeechSynthesizer, Protocol):
    def synthesize_stream(
        self,
        text: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[bytes]: ...


class SpeechRecognizer(Protocol):
    def transcribe(self, wav_audio: bytes) -> str: ...


class SpeechServiceError(RuntimeError):
    """A local speech service could not complete a request."""


class ModelRequestCancelled(RuntimeError):
    """A superseded streaming model request stopped cooperatively."""


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    detail: str


@dataclass
class LlamaCppProvider:
    """OpenAI-compatible llama.cpp server adapter with strict JSON output."""

    base_url: str = "http://127.0.0.1:8080"
    model: str = "gemma"
    timeout: float = 30.0
    system_prompt: str = ""
    streaming: bool = True
    temperature: float = 0.25
    top_p: float = 0.9
    context_messages: int = 16
    context_char_budget: int = 12_000
    max_tokens: int = 256
    enable_thinking: bool = False
    max_stream_events: int = 4096
    max_response_bytes: int = 131_072
    last_metrics: dict[str, object] = field(default_factory=dict, init=False)
    _cancel_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _active_cancel: threading.Event | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("llama.cpp base_url cannot be empty")
        if self.timeout <= 0:
            raise ValueError("llama.cpp timeout must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("llama.cpp temperature must be between zero and two")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError("llama.cpp top_p must be between zero and one")
        if not 1 <= self.context_messages <= 64:
            raise ValueError("llama.cpp context_messages must be between 1 and 64")
        if not 1000 <= self.context_char_budget <= 100_000:
            raise ValueError("llama.cpp context_char_budget must be between 1000 and 100000")
        if not 64 <= self.max_tokens <= 4096:
            raise ValueError("llama.cpp max_tokens must be between 64 and 4096")
        if not 64 <= self.max_stream_events <= 65_536:
            raise ValueError("llama.cpp max_stream_events must be between 64 and 65536")
        if not 4096 <= self.max_response_bytes <= 4_194_304:
            raise ValueError("llama.cpp max_response_bytes must be between 4096 and 4194304")

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> LlamaCppProvider:
        """Build every runtime surface from the same bounded inference policy."""

        return cls(
            base_url=str(config.get("base_url", "http://127.0.0.1:8080")),
            model=str(config.get("model", "gemma")),
            timeout=float(config.get("timeout", 30)),
            streaming=bool(config.get("streaming", True)),
            temperature=float(config.get("temperature", 0.25)),
            top_p=float(config.get("top_p", 0.9)),
            context_messages=int(config.get("context_messages", 16)),
            context_char_budget=int(config.get("context_char_budget", 12_000)),
            max_tokens=int(config.get("max_tokens", 256)),
            enable_thinking=bool(config.get("enable_thinking", False)),
            max_stream_events=int(config.get("max_stream_events", 4096)),
            max_response_bytes=int(config.get("max_response_bytes", 131_072)),
        )

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt.strip()

    def cancel_current(self) -> None:
        """Request cancellation of the active streamed generation, if any."""

        with self._cancel_lock:
            if self._active_cancel is not None:
                self._active_cancel.set()

    def decide(
        self,
        transcript: str,
        tools: list[dict[str, Any]],
        context: list[dict[str, str]],
    ) -> AgentDecision:
        self.last_metrics = {}
        request_cancel = threading.Event()
        with self._cancel_lock:
            previous = self._active_cancel
            self._active_cancel = request_cancel
        if previous is not None:
            previous.set()
        fallback = (
            "You are Parcel, a robot dog. Return one JSON object with reply, "
            "tool_calls, intent, affect, and next_action. Use null for affect or "
            "next_action when unnecessary. Never invent poses or joint values."
        )
        system = (
            f"{self.system_prompt or fallback}\nTOOLS={json.dumps(tools, separators=(',', ':'))}"
        )
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            # Ordinary conversation and parameterized skills do not benefit from
            # thousands of hidden reasoning tokens. A future planning tier can
            # opt in explicitly without making every acknowledgement slow.
            "reasoning_effort": "medium" if self.enable_thinking else "none",
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
            "messages": [
                {"role": "system", "content": system},
                *_bounded_chat_context(
                    context,
                    max_messages=self.context_messages,
                    max_chars=self.context_char_budget,
                ),
                {"role": "user", "content": transcript},
            ],
            # llama.cpp converts this schema to a grammar, preventing harmless
            # metadata drift (for example ``affect: "empathetic"``) from
            # discarding an otherwise useful conversational response. Runtime
            # parsing and SafetySupervisor remain a second validation boundary.
            "response_format": {
                "type": "json_object",
                "schema": _decision_response_schema(tools),
            },
        }
        request_started = time.monotonic()
        try:
            if self.streaming:
                payload["stream"] = True
                payload["stream_options"] = {"include_usage": True}
                content, usage, first_output = _post_chat_stream(
                    f"{self.base_url.rstrip('/')}/v1/chat/completions",
                    payload,
                    self.timeout,
                    max_events=self.max_stream_events,
                    max_content_bytes=self.max_response_bytes,
                    cancel_event=request_cancel,
                )
                response = {"usage": usage}
            else:
                response = _post_json(
                    f"{self.base_url.rstrip('/')}/v1/chat/completions",
                    payload,
                    self.timeout,
                    max_response_bytes=self.max_response_bytes,
                    cancel_event=request_cancel,
                )
                content = response["choices"][0]["message"]["content"]
                first_output = None
            response_received = time.monotonic()
            if request_cancel.is_set():
                raise ModelRequestCancelled("language-model request was superseded")
            decision = parse_model_decision(content)
            parsed = time.monotonic()
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            self.last_metrics = {
                "model_http_ms": round((response_received - request_started) * 1000.0, 3),
                "model_ttft_ms": (
                    round((first_output - request_started) * 1000.0, 3)
                    if first_output is not None
                    else None
                ),
                "model_json_validation_ms": round((parsed - response_received) * 1000.0, 3),
                "model_streaming": self.streaming,
                "reasoning_first_output_estimated": first_output is None,
                "_first_output_monotonic": first_output,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
            return decision
        finally:
            with self._cancel_lock:
                if self._active_cancel is request_cancel:
                    self._active_cancel = None


def _bounded_chat_context(
    context: list[dict[str, str]],
    *,
    max_messages: int,
    max_chars: int,
) -> list[dict[str, str]]:
    """Keep the newest complete dialogue turns inside a conservative budget."""

    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(context[-max_messages:]):
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant", "tool"} or not isinstance(content, str):
            continue
        cost = len(role) + len(content)
        if used + cost > max_chars:
            break
        selected.append({"role": role, "content": content})
        used += cost
    selected.reverse()
    # When the budget boundary bisects a user/assistant pair, never begin the
    # retained history with an answer whose prompting user message was dropped.
    while selected and selected[0]["role"] in {"assistant", "tool"}:
        selected.pop(0)
    return selected


def _decision_response_schema(tools: list[dict[str, Any]]) -> dict[str, Any]:
    tool_variants: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        parameters = tool.get("parameters")
        if not isinstance(name, str) or not name or not isinstance(parameters, dict):
            raise TypeError("language-model tools require a name and parameter schema")
        tool_variants.append(
            {
                "type": "object",
                "properties": {
                    "name": {"const": name},
                    "arguments": parameters,
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
        )
    tool_items: dict[str, Any] = (
        {"oneOf": tool_variants}
        if tool_variants
        else {"type": "object", "additionalProperties": False}
    )
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "maxLength": 500},
            "tool_calls": {
                "type": "array",
                "items": tool_items,
                "maxItems": 4 if tool_variants else 0,
            },
            "intent": {"type": "string", "minLength": 1, "maxLength": 80},
            "affect": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "enum": ["happy", "sad", "neutral", "unknown"],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                        },
                        "required": ["label", "confidence"],
                        "additionalProperties": False,
                    },
                ]
            },
            "next_action": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "kind": {"const": "skill"},
                            "name": {"type": "string", "minLength": 1, "maxLength": 80},
                            "trigger": {
                                "type": "string",
                                "enum": ["inferred_affect", "explicit_command"],
                            },
                            "timing_preference": {
                                "type": "string",
                                "enum": ["when_safe", "now"],
                            },
                            "interruption_request": {
                                "type": "string",
                                "enum": ["none", "safe_checkpoint"],
                            },
                            "reason": {"type": "string", "maxLength": 240},
                        },
                        "required": [
                            "kind",
                            "name",
                            "trigger",
                            "timing_preference",
                            "interruption_request",
                            "reason",
                        ],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "required": ["reply", "tool_calls", "intent", "affect", "next_action"],
        "additionalProperties": False,
    }


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
class FishSpeechProvider:
    """Client for a local Fish Speech S2 `/v1/tts` service.

    Fish keeps its semantic/audio tokens inside the TTS server. This adapter's
    public boundary is deliberately text in and audio bytes out, so codec tokens
    can never be confused with instructions for the robot's action reasoner.

    The current Fish server only supports WAV for streamed synthesis. Its first
    response chunk is a WAV header and subsequent chunks contain mono PCM16 audio
    (44.1 kHz for S2 Pro). A streaming sink should consume the chunks in order.
    """

    base_url: str = "http://127.0.0.1:8091"
    reference_id: str | None = None
    api_key: str | None = None
    timeout: float = 120.0
    chunk_size: int = 4096
    max_new_tokens: int = 1024
    chunk_length: int = 200
    top_p: float = 0.8
    repetition_penalty: float = 1.1
    temperature: float = 0.8
    normalize: bool = True

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("Fish Speech timeout must be positive")
        if self.chunk_size <= 0:
            raise ValueError("Fish Speech chunk_size must be positive")
        if not 100 <= self.chunk_length <= 1000:
            raise ValueError("Fish Speech chunk_length must be between 100 and 1000")

    def health(self) -> ProviderHealth:
        """Probe the service without raising when it is offline or still loading."""

        request = Request(
            f"{self.base_url.rstrip('/')}/v1/health",
            headers=self._headers("application/json"),
            method="GET",
        )
        try:
            with urlopen(request, timeout=min(self.timeout, 5.0)) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            return ProviderHealth(False, f"Fish Speech unavailable: {error}")
        if isinstance(result, dict) and result.get("status") == "ok":
            return ProviderHealth(True, "Fish Speech ready")
        return ProviderHealth(False, "Fish Speech returned an invalid health response")

    def is_healthy(self) -> bool:
        return self.health().available

    def synthesize(self, text: str) -> bytes:
        """Return one complete WAV file."""

        response = self._open_tts(text, streaming=False)
        try:
            return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise SpeechServiceError(f"Fish Speech response failed: {error}") from error
        finally:
            response.close()

    def synthesize_stream(
        self,
        text: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[bytes]:
        """Return a stream that can be cancelled safely from another thread."""

        response = self._open_tts(text, streaming=True)
        return _FishAudioStream(response, self.chunk_size, cancel_event)

    def _open_tts(self, text: str, *, streaming: bool) -> Any:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Fish Speech text cannot be empty")
        request = Request(
            f"{self.base_url.rstrip('/')}/v1/tts?format=msgpack",
            data=_pack_msgpack(self._payload(clean_text, streaming=streaming)),
            headers=self._headers("audio/wav", content_type="application/msgpack"),
            method="POST",
        )
        try:
            return urlopen(request, timeout=self.timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise SpeechServiceError(f"Fish Speech request failed: {error}") from error

    def _payload(self, text: str, *, streaming: bool) -> dict[str, Any]:
        return {
            "text": text,
            "references": [],
            "reference_id": self.reference_id,
            "format": "wav",
            "latency": "normal",
            "max_new_tokens": self.max_new_tokens,
            "chunk_length": self.chunk_length,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
            "temperature": self.temperature,
            "streaming": streaming,
            "use_memory_cache": "on" if self.reference_id else "off",
            "seed": None,
            "normalize": self.normalize,
        }

    def _headers(self, accept: str, *, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": accept}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class _FishAudioStream(Iterator[bytes]):
    """Closable HTTP response iterator used to make barge-in immediate."""

    def __init__(
        self,
        response: Any,
        chunk_size: int,
        external_cancel: threading.Event | None,
    ):
        self._response = response
        self._chunk_size = chunk_size
        self._external_cancel = external_cancel
        self._cancelled = threading.Event()
        self._close_lock = threading.Lock()
        self._closed = False

    def __iter__(self) -> _FishAudioStream:
        return self

    def __next__(self) -> bytes:
        if self._should_stop():
            self.close()
            raise StopIteration
        try:
            chunk = self._response.read(self._chunk_size)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            if self._should_stop():
                raise StopIteration from None
            self.close()
            raise SpeechServiceError(f"Fish Speech stream failed: {error}") from error
        if not chunk or self._should_stop():
            self.close()
            raise StopIteration
        return chunk

    def cancel(self) -> None:
        self._cancelled.set()
        self.close()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._response.close()
            except OSError:
                pass

    def _should_stop(self) -> bool:
        return (
            self._closed
            or self._cancelled.is_set()
            or bool(self._external_cancel and self._external_cancel.is_set())
        )


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
    if len(data["reply"]) > 500:
        raise ValueError("model response reply is too long")
    allowed_top_level = {"reply", "tool_calls", "intent", "affect", "next_action"}
    unknown = set(data) - allowed_top_level
    if unknown:
        raise ValueError(f"model response contains unsupported fields: {sorted(unknown)}")
    raw_calls = data.get("tool_calls", [])
    if not isinstance(raw_calls, list) or len(raw_calls) > 4:
        raise ValueError("model response tool_calls must be a list of at most four calls")
    calls = []
    for item in raw_calls:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise TypeError("each tool call must contain a name")
        if not set(item).issubset({"name", "arguments"}):
            raise ValueError("tool call contains unsupported fields")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be an object")
        calls.append(ToolCall(item["name"], arguments))
    intent = data.get("intent", "conversation")
    if not isinstance(intent, str) or not intent.strip() or len(intent) > 80:
        raise TypeError("model response intent must be a short string")
    affect = _parse_affect(data.get("affect"))
    next_action = _parse_action_proposal(data.get("next_action"))
    return AgentDecision(
        data["reply"].strip(),
        tuple(calls),
        intent.strip(),
        affect,
        next_action,
    )


def _parse_affect(value: object) -> AffectEstimate | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"label", "confidence"}:
        raise TypeError("affect must contain only label and confidence")
    label = value.get("label")
    confidence = value.get("confidence")
    if label not in {"happy", "sad", "neutral", "unknown"}:
        raise ValueError("affect label is not allowed")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("affect confidence must be numeric")
    numeric = float(confidence)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError("affect confidence must be between zero and one")
    return AffectEstimate(str(label), numeric)


def _parse_action_proposal(value: object) -> ActionProposal | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("next_action must be an object or null")
    allowed = {
        "kind",
        "name",
        "trigger",
        "timing_preference",
        "interruption_request",
        "reason",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"next_action contains unsupported fields: {sorted(unknown)}")
    if value.get("kind") != "skill":
        raise ValueError("next_action currently supports only semantic skills")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise TypeError("next_action name must be a short string")
    trigger = value.get("trigger", "inferred_affect")
    if trigger not in {"inferred_affect", "explicit_command"}:
        raise ValueError("next_action trigger is not allowed")
    timing = value.get("timing_preference", "when_safe")
    if timing not in {"when_safe", "now"}:
        raise ValueError("next_action timing preference is not allowed")
    interruption = value.get("interruption_request", "none")
    if interruption not in {"none", "safe_checkpoint"}:
        raise ValueError("next_action interruption request is not allowed")
    reason = value.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 240:
        raise TypeError("next_action reason must be a short string")
    return ActionProposal(
        kind="skill",
        name=name.strip(),
        trigger=str(trigger),
        timing_preference=str(timing),
        interruption_request=str(interruption),
        reason=reason.strip(),
    )


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    max_response_bytes: int = 131_072,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelRequestCancelled("language-model request was superseded")
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_response_bytes + 1)
            if cancel_event is not None and cancel_event.is_set():
                raise ModelRequestCancelled("language-model request was superseded")
            if len(raw) > max_response_bytes:
                raise ValueError("language-model response exceeded the configured byte limit")
            result = json.loads(raw)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"language-model request failed: {error}") from error
    if not isinstance(result, dict):
        raise TypeError("language-model server returned an invalid response")
    return result


def _post_chat_stream(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    max_events: int = 4096,
    max_content_bytes: int = 131_072,
    cancel_event: threading.Event | None = None,
) -> tuple[str, dict[str, object], float | None]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    pieces: list[str] = []
    usage: dict[str, object] = {}
    first_output: float | None = None
    event_count = 0
    content_bytes = 0
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise ModelRequestCancelled("language-model request was superseded")
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                if cancel_event is not None and cancel_event.is_set():
                    raise ModelRequestCancelled("language-model request was superseded")
                line = raw_line.decode("utf-8", errors="strict").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event_count += 1
                if event_count > max_events:
                    raise ValueError("language-model stream exceeded the event limit")
                chunk = json.loads(data)
                if not isinstance(chunk, dict):
                    continue
                raw_usage = chunk.get("usage")
                if isinstance(raw_usage, dict):
                    usage = {
                        str(key): value
                        for key, value in raw_usage.items()
                        if isinstance(value, (int, float)) and not isinstance(value, bool)
                    }
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if first_output is None and (
                    isinstance(reasoning, str) and reasoning or isinstance(content, str) and content
                ):
                    first_output = time.monotonic()
                if isinstance(content, str) and content:
                    content_bytes += len(content.encode("utf-8"))
                    if content_bytes > max_content_bytes:
                        raise ValueError("language-model stream exceeded the content byte limit")
                    pieces.append(content)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"language-model streaming request failed: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("language-model stream was malformed") from error
    result = "".join(pieces)
    if not result:
        raise ValueError("language-model stream returned no response content")
    return result, usage, first_output


def _pack_msgpack(payload: dict[str, Any]) -> bytes:
    try:
        import msgpack
    except ImportError as error:
        raise SpeechServiceError(
            "Fish Speech requires MessagePack support; install the 'voice' extra"
        ) from error
    try:
        return msgpack.packb(payload, use_bin_type=True)
    except (TypeError, ValueError) as error:
        raise SpeechServiceError("Fish Speech request could not be encoded") from error


def _multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
    ).encode()
