from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, Self
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ActionProposal, AffectEstimate, AgentDecision, ToolCall

logger = logging.getLogger(__name__)

if False:  # pragma: no cover - type-only imports without a runtime dependency cycle
    from .brain.contracts import IntentFrame, ObservationSnapshot, PlanIR
    from .brain.plan_sketch import PlanSketch


class LanguageModel(Protocol):
    def decide(
        self,
        transcript: str,
        tools: list[dict[str, Any]],
        context: list[dict[str, str]],
    ) -> AgentDecision: ...


class PlanningModel(Protocol):
    def plan(
        self,
        transcript: str,
        *,
        intent_frame: IntentFrame,
        observation: ObservationSnapshot,
        skill_contracts: dict[str, object],
        response_schema: dict[str, Any],
        system_prompt: str,
    ) -> PlanIR | PlanSketch: ...


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
    plan_timeout: float = 90.0
    plan_max_tokens: int = 1024
    plan_enable_thinking: bool = False
    plan_temperature: float = 0.0
    max_stream_events: int = 4096
    max_response_bytes: int = 131_072
    last_metrics: dict[str, object] = field(default_factory=dict, init=False)
    _cancel_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _active_cancel: threading.Event | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("llama.cpp base_url cannot be empty")
        if self.timeout <= 0 or self.plan_timeout <= 0:
            raise ValueError("llama.cpp timeouts must be positive")
        if not 0.0 <= self.temperature <= 2.0 or not 0.0 <= self.plan_temperature <= 2.0:
            raise ValueError("llama.cpp temperatures must be between zero and two")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError("llama.cpp top_p must be between zero and one")
        if not 1 <= self.context_messages <= 64:
            raise ValueError("llama.cpp context_messages must be between 1 and 64")
        if not 1000 <= self.context_char_budget <= 100_000:
            raise ValueError("llama.cpp context_char_budget must be between 1000 and 100000")
        if not 64 <= self.max_tokens <= 4096:
            raise ValueError("llama.cpp max_tokens must be between 64 and 4096")
        if not 128 <= self.plan_max_tokens <= 4096:
            raise ValueError("llama.cpp plan_max_tokens must be between 128 and 4096")
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
            plan_timeout=float(config.get("plan_timeout", config.get("timeout", 90))),
            plan_max_tokens=int(config.get("plan_max_tokens", 1024)),
            plan_enable_thinking=bool(config.get("plan_enable_thinking", False)),
            plan_temperature=float(config.get("plan_temperature", 0.0)),
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
        return self._request_structured(
            payload,
            timeout=self.timeout,
            mode="fast",
            parser=parse_model_decision,
        )

    def plan(
        self,
        transcript: str,
        *,
        intent_frame: IntentFrame,
        observation: ObservationSnapshot,
        skill_contracts: dict[str, object],
        response_schema: dict[str, Any],
        system_prompt: str,
    ) -> PlanIR | PlanSketch:
        """Use the already-loaded backbone in a separate constrained plan mode."""

        from .brain.contracts import IntentFrame, ObservationSnapshot, PlanIR
        from .brain.plan_sketch import PlanSketch
        from .brain.runtime_adapter import (
            PLAN_SKETCH_OUTPUT_CONTRACT,
            planner_output_contract,
        )

        if not isinstance(intent_frame, IntentFrame):
            raise TypeError("plan mode requires a parsed IntentFrame")
        if not isinstance(observation, ObservationSnapshot):
            raise TypeError("plan mode requires a parsed ObservationSnapshot")
        if not isinstance(response_schema, dict) or not response_schema:
            raise TypeError("plan mode requires a non-empty response schema")
        if not isinstance(skill_contracts, dict) or not skill_contracts:
            raise TypeError("plan mode skill contracts must be a non-empty object")
        clean_prompt = system_prompt.strip()
        if not clean_prompt:
            raise ValueError("plan mode system prompt cannot be empty")
        output_contract = planner_output_contract(response_schema)
        plan_input = json.dumps(
            {
                "original_transcript": transcript,
                "intent_frame": intent_frame.as_dict(),
                "observation_snapshot": observation.as_dict(),
                "skill_contracts": skill_contracts,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if len(plan_input) > 96_000:
            raise ValueError("plan mode input exceeds the bounded prompt budget")
        payload = {
            "model": self.model,
            "temperature": self.plan_temperature,
            "top_p": self.top_p,
            "max_tokens": self.plan_max_tokens,
            "reasoning_effort": "medium" if self.plan_enable_thinking else "none",
            "chat_template_kwargs": {"enable_thinking": self.plan_enable_thinking},
            "messages": [
                {"role": "system", "content": clean_prompt},
                {"role": "user", "content": plan_input},
            ],
            "response_format": {
                "type": "json_object",
                "schema": response_schema,
            },
        }
        if output_contract == PLAN_SKETCH_OUTPUT_CONTRACT:
            parser = lambda content: PlanSketch.from_mapping(_json_object(content, "PlanSketch"))
        else:
            parser = lambda content: PlanIR.from_mapping(_json_object(content, "PlanIR"))
        result = self._request_structured(
            payload,
            timeout=self.plan_timeout,
            mode="plan",
            parser=parser,
        )
        self.last_metrics["model_output_contract"] = output_contract
        return result

    def _request_structured(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        mode: str,
        parser: Callable[[str], Any],
    ) -> Any:
        """Make one cancellable constrained request and measure the same boundaries."""

        self.last_metrics = {}
        request_cancel = threading.Event()
        with self._cancel_lock:
            previous = self._active_cancel
            self._active_cancel = request_cancel
        if previous is not None:
            previous.set()
        request_started = time.monotonic()
        try:
            if self.streaming:
                payload["stream"] = True
                payload["stream_options"] = {"include_usage": True}
                content, usage, first_output = _post_chat_stream(
                    f"{self.base_url.rstrip('/')}/v1/chat/completions",
                    payload,
                    timeout,
                    max_events=self.max_stream_events,
                    max_content_bytes=self.max_response_bytes,
                    cancel_event=request_cancel,
                )
                response = {"usage": usage}
            else:
                response = _post_json(
                    f"{self.base_url.rstrip('/')}/v1/chat/completions",
                    payload,
                    timeout,
                    max_response_bytes=self.max_response_bytes,
                    cancel_event=request_cancel,
                )
                content = response["choices"][0]["message"]["content"]
                first_output = None
            response_received = time.monotonic()
            if request_cancel.is_set():
                raise ModelRequestCancelled("language-model request was superseded")
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            self.last_metrics = {
                "model_http_ms": round((response_received - request_started) * 1000.0, 3),
                "model_ttft_ms": (
                    round((first_output - request_started) * 1000.0, 3)
                    if first_output is not None
                    else None
                ),
                "model_json_validation_ms": None,
                "model_streaming": self.streaming,
                "model_mode": mode,
                "reasoning_first_output_estimated": first_output is None,
                "_first_output_monotonic": first_output,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "model_output_bytes": (
                    len(content.encode("utf-8")) if isinstance(content, str) else None
                ),
            }
            try:
                result = parser(content)
            except (RuntimeError, TypeError, ValueError) as error:
                parsed = time.monotonic()
                self.last_metrics["model_json_validation_ms"] = round(
                    (parsed - response_received) * 1000.0, 3
                )
                self.last_metrics["model_parse_error"] = type(error).__name__
                raise
            parsed = time.monotonic()
            self.last_metrics["model_json_validation_ms"] = round(
                (parsed - response_received) * 1000.0, 3
            )
            return result
        except Exception as error:
            if not self.last_metrics:
                self.last_metrics = {
                    "model_http_ms": round(
                        (time.monotonic() - request_started) * 1000.0,
                        3,
                    ),
                    "model_mode": mode,
                    "model_request_error": type(error).__name__,
                    "model_streaming": self.streaming,
                }
            raise
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
                                "enum": ["excited", "happy", "sad", "neutral", "unknown"],
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
                                "enum": [
                                    "inferred_affect",
                                    "explicit_command",
                                    "conversation_reaction",
                                ],
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
    """Adapter for whisper.cpp's multipart `/inference` endpoint.

    ``last_metrics`` carries the STT request/final clocks the latency ledger
    needs to attribute the ack budget. Until they existed, STT was the one
    unmeasured span between the owner finishing a sentence and the robot
    answering — docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md lists it as one
    of the four missing clocks. It mirrors ``LlamaCppProvider.last_metrics``
    so the ledger consumes both the same way, and it is plain data: nothing
    here reaches into the tracker, so this adapter stays dependency free.
    """

    base_url: str = "http://127.0.0.1:8178"
    language: str = "en"
    timeout: float = 60.0

    #: Populated after every transcribe() attempt, success or failure.
    last_metrics: dict[str, object] = field(default_factory=dict)

    def transcribe(self, wav_audio: bytes) -> str:
        # WAV header is 44 bytes for the PCM16 mono files pcm16_wav writes;
        # audio_s lets a caller compute a real-time factor without decoding.
        audio_s = max(0.0, (len(wav_audio) - 44) / 2.0 / 16_000.0)
        request_start = time.monotonic()
        self.last_metrics = {
            "request_start_monotonic": request_start,
            "audio_s": audio_s,
            "status": "in_flight",
        }
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
            self._record_final(request_start, audio_s, status="failed")
            raise RuntimeError(f"Whisper service request failed: {error}") from error
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str):
            self._record_final(request_start, audio_s, status="malformed")
            raise TypeError("Whisper service response did not contain text")
        self._record_final(request_start, audio_s, status="ok")
        return text.strip()

    def _record_final(
        self, request_start: float, audio_s: float, *, status: str
    ) -> None:
        final = time.monotonic()
        duration = max(0.0, final - request_start)
        self.last_metrics = {
            "request_start_monotonic": request_start,
            "final_monotonic": final,
            "duration_s": duration,
            "audio_s": audio_s,
            # <1.0 means faster than real time, which is the whole reason
            # base.en on CPU is viable for the ack budget.
            "real_time_factor": (duration / audio_s) if audio_s > 0 else None,
            "status": status,
        }


def _json_object(content: str, label: str) -> dict[str, object]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"model {label} response was not valid JSON") from error
    if not isinstance(data, dict):
        raise TypeError(f"model {label} response must be a JSON object")
    return data


def parse_model_decision(content: str) -> AgentDecision:
    data = _json_object(content, "decision")
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
    if label not in {"excited", "happy", "sad", "neutral", "unknown"}:
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
    if trigger not in {
        "inferred_affect",
        "explicit_command",
        "conversation_reaction",
    }:
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


# ---------------------------------------------------------------------------
# On-device TTS (Piper) and sentence-chunked streaming
# ---------------------------------------------------------------------------


@dataclass
class PiperSpeechProvider:
    """Local Piper TTS via subprocess: text in, 16-bit mono PCM WAV out.

    Piper is the low-latency CPU default recommended for onboard companion
    speech; heavier providers (Fish S2) remain opt-in docked modes. The binary
    and voice model are configured paths; ``available()`` fails closed instead
    of raising so the runtime can degrade to text mode.
    """

    binary_path: str = "third_party/piper/piper"
    voice_path: str = "models/piper/voice.onnx"
    sample_rate_hz: int = 22050
    timeout_s: float = 30.0

    def available(self) -> bool:
        from pathlib import Path

        return Path(self.binary_path).is_file() and Path(self.voice_path).is_file()

    def synthesize(self, text: str) -> bytes:
        import subprocess

        clean = text.strip()
        if not clean:
            return b""
        if not self.available():
            raise SpeechServiceError(
                f"Piper is not installed (binary={self.binary_path!r}, "
                f"voice={self.voice_path!r})"
            )
        command = [
            self.binary_path,
            "--model",
            self.voice_path,
            "--output-raw",
        ]
        try:
            completed = subprocess.run(
                command,
                input=clean.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_s,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SpeechServiceError(f"Piper synthesis failed: {error}") from error
        pcm = completed.stdout
        if not pcm:
            raise SpeechServiceError("Piper produced no audio")
        return _pcm16_to_wav(pcm, self.sample_rate_hz)


def _pcm16_to_wav(pcm: bytes, sample_rate_hz: int, channels: int = 1) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate_hz)
        writer.writeframes(pcm)
    return buffer.getvalue()


_SENTENCE_BOUNDARY = (".", "!", "?", ";", ":", "\n")


def split_speech_sentences(text: str, *, max_chars: int = 220) -> list[str]:
    """Split a reply into speakable sentence/clause chunks.

    Long unpunctuated runs are split at word boundaries near ``max_chars`` so
    a single chunk can never stall barge-in for the whole reply.
    """

    clean = " ".join(text.split())
    if not clean:
        return []
    sentences: list[str] = []
    current: list[str] = []
    for word in clean.split(" "):
        current.append(word)
        if word.endswith(_SENTENCE_BOUNDARY) or sum(len(w) + 1 for w in current) >= max_chars:
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return sentences


_EMOTE_TAG = re.compile(r"\[emote:([a-z0-9_]{1,40})(?::([0-9]*\.?[0-9]+))?\]", re.IGNORECASE)


def strip_emote_tags(text: str) -> tuple[str, list[tuple[str, float]]]:
    """Split ``[emote:name]`` / ``[emote:name:0.8]`` markers out of a reply.

    Returns the speakable text (tags removed, spacing tidied) and the ordered
    emotes found. The conversation model writes tags inline so a gesture is
    anchored to the words it belongs with; nothing here validates the name —
    dispatch does that against the admitted catalog.
    """

    emotes: list[tuple[str, float]] = []

    def capture(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        raw_intensity = match.group(2)
        try:
            intensity = 1.0 if raw_intensity is None else float(raw_intensity)
        except ValueError:
            intensity = 1.0
        emotes.append((name, intensity))
        return " "

    spoken = _EMOTE_TAG.sub(capture, text)
    # Tidy the seams the removed tags leave behind.
    spoken = re.sub(r"\s+([,.;:!?])", r"\1", spoken)
    spoken = " ".join(spoken.split())
    return spoken, emotes


class SpeechChunk(bytes):
    """Synthesized audio that remembers the emotes authored in its sentence.

    A plain ``bytes`` cannot carry the association, and the session's audio
    path is deliberately byte-oriented, so the chunk itself is the carrier:
    every consumer keeps treating it as PCM/WAV while the runtime reads
    ``emotes`` when it hands the chunk to the speaker sink.
    """

    emotes: tuple[tuple[str, float], ...]

    def __new__(
        cls,
        data: bytes,
        emotes: Iterable[tuple[str, float]] = (),
    ) -> Self:
        chunk = super().__new__(cls, data)
        chunk.emotes = tuple((str(name), float(intensity)) for name, intensity in emotes)
        return chunk


def _sentences_with_emotes(
    text: str, *, max_chars: int
) -> list[tuple[str, list[tuple[str, float]]]]:
    """Sentence chunks plus the emotes anchored inside each one.

    One pass over the word stream, applying the exact chunking rule of
    ``split_speech_sentences`` after tags are stripped per word — so tag
    characters can never skew the max-length word splits, and a trailing tag
    after the final sentence anchors to that sentence instead of being
    silently dropped (both found in the 2026-08-04 sprint review's
    dual-split mapping).
    """

    words: list[str] = []
    emotes_by_word: dict[int, list[tuple[str, float]]] = {}
    pending: list[tuple[str, float]] = []
    for raw_word in text.split():
        found: list[tuple[str, float]] = []

        def capture(match: re.Match[str], _found: list[tuple[str, float]] = found) -> str:
            name = match.group(1).lower()
            raw_intensity = match.group(2)
            try:
                intensity = 1.0 if raw_intensity is None else float(raw_intensity)
            except ValueError:
                intensity = 1.0
            _found.append((name, intensity))
            return ""

        spoken_word = _EMOTE_TAG.sub(capture, raw_word).strip()
        pending.extend(found)
        if spoken_word:
            index = len(words)
            words.append(spoken_word)
            if pending:
                emotes_by_word.setdefault(index, []).extend(pending)
                pending = []
    if pending and words:
        emotes_by_word.setdefault(len(words) - 1, []).extend(pending)

    sentences: list[tuple[str, list[tuple[str, float]]]] = []
    current: list[str] = []
    current_emotes: list[tuple[str, float]] = []
    for index, word in enumerate(words):
        current.append(word)
        current_emotes.extend(emotes_by_word.get(index, ()))
        if word.endswith(_SENTENCE_BOUNDARY) or sum(len(w) + 1 for w in current) >= max_chars:
            sentences.append((" ".join(current), current_emotes))
            current, current_emotes = [], []
    if current:
        sentences.append((" ".join(current), current_emotes))
    elif current_emotes and sentences:
        sentences[-1][1].extend(current_emotes)
    return sentences


_CLAUSE_BOUNDARY = re.compile(r"[,;:]|\s+(?:and|but|so|then|because|while|though)\b", re.IGNORECASE)

#: Below this the opening flush buys no latency and only sounds clipped.
#: 4 admits the natural "Okay," / "Sure," lead-in, which is the common case.
_MIN_LEADING_CLAUSE_CHARS = 4


def _split_leading_clause(
    chunks: list[tuple[str, list[tuple[str, float]]]], *, budget: int
) -> list[tuple[str, list[tuple[str, float]]]]:
    """Split only the FIRST chunk at its earliest clause boundary.

    Time-to-first-audio is set by how long the first chunk takes to synthesize,
    so a shorter opening clause is audible sooner while every later chunk keeps
    its sentence shape. A first chunk that carries emote tags is left whole: the
    tags are anchored per word, and re-anchoring them across a split is how a
    gesture lands on the wrong words (card W8), so the latency win is declined
    rather than paid for with a mistimed gesture.
    """

    if not chunks:
        return chunks
    head_text, head_emotes = chunks[0]
    if head_emotes or len(head_text) <= budget:
        return chunks
    match = _CLAUSE_BOUNDARY.search(head_text)
    if match is None or not _MIN_LEADING_CLAUSE_CHARS <= match.end() <= budget:
        return chunks
    lead, rest = head_text[: match.end()].strip(), head_text[match.end() :].strip()
    if not lead or not rest:
        return chunks
    return [(lead, []), (rest, [])] + chunks[1:]


class SentenceChunkedSynthesizer:
    """Adapt any blocking synthesizer into a cancellable streaming one.

    ``DuplexVoiceSession`` prefers ``synthesize_stream`` when present. Chunking
    on sentence boundaries means the first audio arrives after the first
    sentence is synthesized — not after the whole reply — and barge-in takes
    effect at the next sentence boundary at the latest.
    """

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        *,
        max_chars: int = 220,
        first_clause_chars: int | None = None,
    ):
        if not 40 <= max_chars <= 2000:
            raise ValueError("sentence chunk size must be between 40 and 2000 characters")
        if first_clause_chars is not None and not _MIN_LEADING_CLAUSE_CHARS <= first_clause_chars <= max_chars:
            raise ValueError("first clause budget must be between 4 chars and the sentence budget")
        self._synthesizer = synthesizer
        self._max_chars = max_chars
        self._first_clause_chars = first_clause_chars

    def synthesize(self, text: str) -> SpeechChunk:
        spoken, emotes = strip_emote_tags(text)
        return SpeechChunk(self._synthesizer.synthesize(spoken), emotes)

    def synthesize_stream(
        self,
        text: str,
        *,
        cancel_event: threading.Event | None = None,
        on_sentence: Callable[[str], None] | None = None,
    ) -> Iterator[SpeechChunk]:
        chunks = _sentences_with_emotes(text, max_chars=self._max_chars)
        if self._first_clause_chars is not None:
            chunks = _split_leading_clause(chunks, budget=self._first_clause_chars)
        for sentence, emotes in chunks:
            if cancel_event is not None and cancel_event.is_set():
                return
            if on_sentence is not None:
                try:
                    on_sentence(sentence)
                except Exception as error:  # noqa: BLE001 - observe path must not kill TTS
                    logger.debug("on_sentence observe callback failed: %s", error)
            chunk = self._synthesizer.synthesize(sentence)
            if cancel_event is not None and cancel_event.is_set():
                return
            if chunk:
                # Synthesis time is not playback time: with a deep audio queue
                # a tag fired here would land seconds before its words. The
                # emotes ride the chunk and fire from the sink's playback-start
                # callback instead (card W8).
                yield SpeechChunk(chunk, emotes)


@dataclass(frozen=True)
class SpeechStack:
    """Resolved speech services plus a human-readable status per role."""

    recognizer: SpeechRecognizer | None
    synthesizer: SpeechSynthesizer | None
    mode: str
    stt_detail: str
    tts_detail: str


# Every key the speech: section may carry — read either here or by the
# runtime (devices, endpointing, echo guard). Anything else fails closed:
# an accepted-but-unread key is indistinguishable from a working one
# (the mis-indented-YAML incident, 2026-08-04).
_ALLOWED_SPEECH_KEYS = frozenset(
    {
        "mode",
        "stt_provider",
        "whisper_url",
        "stt_timeout_s",
        "tts_provider",
        "piper_binary",
        "piper_voice",
        "piper_sample_rate_hz",
        "fish_url",
        "fish_reference_id",
        "echo_guard_scale",
        "input_device",
        "output_device",
        # FIX-A/F1: opt back into capturing a sink monitor (loopback rigs).
        # Read by the runtime's arming gate, not by build_speech_stack.
        "allow_monitor_capture",
        "endpointing",
        "vad_model",
        "turn_model",
        "complete_silence_s",
        "incomplete_silence_s",
        # V1-A: opening-clause flush budget in characters. Unset/null keeps the
        # sentence-granular stream byte-identical. Read by the runtime, not by
        # build_speech_stack.
        "first_clause_chars",
    }
)


def build_speech_stack(config: Mapping[str, object]) -> SpeechStack:
    """Construct STT/TTS providers from the ``speech:`` config section.

    Fails soft by design: an unreachable or uninstalled provider yields a
    ``None`` role plus a status string, and the runtime keeps operating in
    text mode. ``mode: text`` disables audio explicitly; ``audio`` demands it;
    ``auto`` uses whatever is healthy. Unknown keys fail closed (loud), not
    soft — a key that parses but does nothing is a configuration lie.
    """

    unknown = set(config) - _ALLOWED_SPEECH_KEYS
    if unknown:
        raise ValueError(f"unsupported speech config keys: {sorted(unknown)}")
    mode = str(config.get("mode", "auto")).strip().lower()
    if mode not in {"auto", "text", "audio"}:
        raise ValueError("speech.mode must be auto, text, or audio")
    if mode == "text":
        return SpeechStack(None, None, mode, "disabled (speech.mode=text)", "disabled")

    recognizer: SpeechRecognizer | None = None
    stt_provider = str(config.get("stt_provider", "whisper_cpp")).strip().lower()
    if stt_provider == "whisper_cpp":
        candidate = WhisperCppProvider(
            base_url=str(config.get("whisper_url", "http://127.0.0.1:8178")),
            timeout=float(config.get("stt_timeout_s", 30.0)),
        )
        health = _http_health(candidate.base_url)
        if health:
            recognizer = candidate
            stt_detail = f"whisper.cpp at {candidate.base_url}"
        else:
            stt_detail = f"whisper.cpp unreachable at {candidate.base_url}"
    elif stt_provider == "none":
        stt_detail = "disabled"
    else:
        raise ValueError(f"unsupported speech.stt_provider: {stt_provider}")

    synthesizer: SpeechSynthesizer | None = None
    tts_provider = str(config.get("tts_provider", "piper")).strip().lower()
    if tts_provider == "piper":
        piper_voice = str(config.get("piper_voice", "models/piper/voice.onnx"))
        configured_rate = config.get("piper_sample_rate_hz")
        piper = PiperSpeechProvider(
            binary_path=str(config.get("piper_binary", "third_party/piper/piper")),
            voice_path=piper_voice,
            # The voice's companion JSON is authoritative: a 16 kHz voice
            # wrapped in a 22050 Hz header plays ~1.38x too fast.
            sample_rate_hz=int(
                configured_rate
                if configured_rate is not None
                else (_piper_voice_sample_rate(piper_voice) or 22050)
            ),
        )
        if piper.available():
            synthesizer = piper
            tts_detail = f"piper ({piper.voice_path})"
        else:
            tts_detail = "piper not installed (binary/voice missing)"
    elif tts_provider == "fish_s2":
        fish_reference = config.get("fish_reference_id")
        fish = FishSpeechProvider(
            base_url=str(config.get("fish_url", "http://127.0.0.1:8091")),
            reference_id=str(fish_reference) if fish_reference else None,
        )
        if fish.is_healthy():
            synthesizer = fish
            tts_detail = f"fish_s2 at {fish.base_url}"
        else:
            tts_detail = f"fish_s2 unreachable at {fish.base_url}"
    elif tts_provider == "none":
        tts_detail = "disabled"
    else:
        raise ValueError(f"unsupported speech.tts_provider: {tts_provider}")

    if mode == "audio" and (recognizer is None or synthesizer is None):
        raise SpeechServiceError(
            "speech.mode=audio requires healthy STT and TTS services "
            f"(stt: {stt_detail}; tts: {tts_detail})"
        )
    return SpeechStack(recognizer, synthesizer, mode, stt_detail, tts_detail)


def _piper_voice_sample_rate(voice_path: str) -> int | None:
    """Read the native rate from the companion JSON every Piper voice ships."""

    import json
    from pathlib import Path

    try:
        metadata = json.loads(Path(f"{voice_path}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    audio = metadata.get("audio") if isinstance(metadata, dict) else None
    rate = audio.get("sample_rate") if isinstance(audio, dict) else None
    if isinstance(rate, (int, float)) and 8000 <= rate <= 96000:
        return int(rate)
    return None


def _http_health(base_url: str, timeout: float = 0.5) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=timeout):
            return True
    except HTTPError as error:
        # A 4xx (e.g. no /health route) still proves a live server; a 5xx is
        # a dead backend behind a reverse proxy and must read as unhealthy.
        return 200 <= error.code < 500
    except (URLError, TimeoutError, OSError):
        return False
