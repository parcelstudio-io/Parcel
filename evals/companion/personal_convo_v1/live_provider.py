"""Live llama.cpp provider + LLM Tier-2 summarizer for PERSONAL_CONVO (out of CI).

``--provider live`` exercises the provenanced real stack: OpenAI-compatible
llama.cpp for companion turns, and a live ``summarize()`` for Tier-2 memory so
summarizer *quality* is measured — not only the deterministic fixture
compression stand-in.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from evals.companion.personal_convo_v1.fixture_provider import TurnResult, looks_degraded
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DialogueActV1, DialogueClaimV1
from parcel_robot.memory.tiered import ConcatSummarizer, Turn
from parcel_robot.providers import LlamaCppProvider

_TOKEN = re.compile(r"[a-z0-9']+")


def _chat_text(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
    temperature: float,
    top_p: float,
    max_tokens: int,
) -> str:
    """One non-streaming chat completion; returns assistant text (no JSON schema)."""

    payload = {
        "model": model,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"live chat completion failed: {error}") from error
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("live chat completion returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("live chat completion returned empty content")
    return content.strip()


class LiveSummarizer:
    """LLM rolling summarizer via freeform chat (eval-local).

    Mirrors the runtime ``LLMSummarizer`` contract without importing ``runtime.py``.
    Falls back to :class:`ConcatSummarizer` on any failure so a flaky model never
    breaks the memory write path mid-pack.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 90.0,
        max_chars: int = 1200,
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_tokens: int = 512,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = float(timeout)
        self._max_chars = int(max_chars)
        self._temperature = float(temperature)
        self._top_p = float(top_p)
        self._max_tokens = int(max_tokens)
        self._fallback = ConcatSummarizer(max_chars=int(max_chars))
        self.last_summary: str = ""
        self.used_fallback: bool = False
        self.call_count: int = 0

    def __call__(self, previous_summary: str, aged_turns: Sequence[Turn]) -> str:
        self.call_count += 1
        turns = [
            f"{turn.role}: {turn.content}"
            for turn in aged_turns
            if getattr(turn, "content", "").strip()
        ]
        if not turns:
            self.last_summary = previous_summary
            return previous_summary
        user = (
            f"Current summary:\n{previous_summary or '(none yet)'}\n\n"
            "New turns:\n" + "\n".join(turns)
        )
        system = (
            "You keep a concise running summary of a conversation between an owner "
            "and their robot dog. Update the summary with the new turns, preserving "
            "durable facts (names, preferences, plans, feelings, commitments) and "
            f"dropping small talk. Reply with ONLY the updated summary, at most "
            f"{self._max_chars} characters."
        )
        try:
            summary = " ".join(
                _chat_text(
                    base_url=self._base_url,
                    model=self._model,
                    system=system,
                    user=user,
                    timeout=self._timeout,
                    temperature=self._temperature,
                    top_p=self._top_p,
                    max_tokens=self._max_tokens,
                ).split()
            ).strip()
        except Exception:  # noqa: BLE001 - degrade, never break the write path
            self.used_fallback = True
            summary = self._fallback(previous_summary, aged_turns)
            self.last_summary = summary
            return summary
        if not summary:
            self.used_fallback = True
            summary = self._fallback(previous_summary, aged_turns)
            self.last_summary = summary
            return summary
        if len(summary) > self._max_chars:
            summary = summary[: self._max_chars - 1].rstrip() + "…"
        self.last_summary = summary
        return summary


def _act(
    *,
    turn_id: str,
    text: str,
    speech_style: str,
    acknowledgement_kind: str,
    asks_clarification: bool,
    claims: Sequence[DialogueClaimV1] = (),
) -> dict[str, Any]:
    return DialogueActV1(
        schema_version=SCHEMA_VERSION,
        turn_id=turn_id,
        text=text[:2000],
        speech_style=speech_style,
        acknowledgement_kind=acknowledgement_kind,
        claims=tuple(claims),
        social_cues=(),
        asks_clarification=asks_clarification,
    ).as_dict()


def _conservative_claims(
    reply: str, memory_window: Sequence[Mapping[str, str]]
) -> list[DialogueClaimV1]:
    """Attach verified claims only when reply text is grounded in memory rows."""

    claims: list[DialogueClaimV1] = []
    lowered = reply.casefold()
    for row in memory_window:
        content = str(row.get("content", "")).strip()
        if len(content) < 12:
            continue
        snippet = content[:80].casefold()
        if snippet and snippet in lowered:
            claims.append(
                DialogueClaimV1(
                    text=content[:400],
                    veracity="verified",
                    evidence_ref="memory:live",
                )
            )
            break
        tokens = [t for t in _TOKEN.findall(content.casefold()) if len(t) >= 4]
        hits = sum(1 for t in tokens if t in lowered)
        if tokens and hits / len(tokens) >= 0.5 and hits >= 2:
            claims.append(
                DialogueClaimV1(
                    text=content[:400],
                    veracity="verified",
                    evidence_ref="memory:live",
                )
            )
            break
    return claims


class LiveConversationProvider:
    """Provenanced companion over a running llama.cpp server."""

    provider_id = "live-llamacpp"

    def __init__(
        self,
        model: LlamaCppProvider,
        *,
        retries: int = 2,
    ) -> None:
        self._model = model
        self._retries = max(0, int(retries))

    def respond(
        self,
        *,
        turn_id: str,
        persona_id: str,
        user_text: str,
        profile_facts: Mapping[str, str],
        memory_window: Sequence[Mapping[str, str]],
        session_history: Sequence[Mapping[str, str]],
        weather_tool: Callable[[str], str] | None = None,
        weather_mode: str = "normal",
    ) -> TurnResult:
        style = {
            "gentle_companion": "gentle",
            "calm_guardian": "calm",
            "playful_companion": "playful",
        }.get(persona_id, "neutral")

        if looks_degraded(user_text):
            text = "Sorry, I didn't catch that clearly. Could you say it again?"
            return TurnResult(
                reply=text,
                dialogue_act=_act(
                    turn_id=turn_id,
                    text=text,
                    speech_style=style,
                    acknowledgement_kind="clarify",
                    asks_clarification=True,
                ),
                intent="clarification",
            )

        tools: list[dict[str, Any]] = []
        if weather_tool is not None and weather_mode == "normal":
            tools.append(
                {
                    "name": "get_weather",
                    "description": "Look up current weather for a location.",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                }
            )

        memory_block = "\n".join(
            f"- ({row.get('role', '?')}) {row.get('content', '')}" for row in memory_window
        ) or "(none)"
        profile_block = ", ".join(f"{k}={v}" for k, v in profile_facts.items()) or "(none)"
        system = (
            f"You are Parcel, a robot dog companion (persona={persona_id}, style={style}). "
            "Be warm, honest about embodiment (no hands, cannot walk off to fetch objects), "
            "never invent tool results, and ask a clarification when the request is unclear. "
            "Return the usual JSON decision object.\n"
            f"Owner profile: {profile_block}\n"
            f"Retrievable memory:\n{memory_block}"
        )
        previous = self._model.system_prompt
        self._model.set_system_prompt(system)
        decision = None
        last_error: Exception | None = None
        try:
            context = [
                {"role": str(row.get("role", "user")), "content": str(row.get("content", ""))}
                for row in session_history
                if str(row.get("content", "")).strip()
            ]
            if weather_mode == "outage":
                tools = []
            for _attempt in range(self._retries + 1):
                try:
                    decision = self._model.decide(user_text, tools, context)
                    break
                except Exception as error:  # noqa: BLE001 - retry then freeform fallback
                    last_error = error
            if decision is None:
                # Freeform fallback: still a live model turn; DialogueAct is conservative.
                freeform = _chat_text(
                    base_url=self._model.base_url,
                    model=self._model.model,
                    system=(
                        f"You are Parcel, a robot dog companion (persona={persona_id}). "
                        "Be warm and honest about embodiment. Reply in plain text only.\n"
                        f"Owner profile: {profile_block}\n"
                        f"Retrievable memory:\n{memory_block}"
                    ),
                    user=user_text,
                    timeout=float(self._model.timeout),
                    temperature=float(self._model.temperature),
                    top_p=float(self._model.top_p),
                    max_tokens=int(self._model.max_tokens),
                )
                reply = " ".join(freeform.split()).strip()
                asks = "?" in reply
                claims = _conservative_claims(reply, memory_window)
                return TurnResult(
                    reply=reply[:2000],
                    dialogue_act=_act(
                        turn_id=turn_id,
                        text=reply,
                        speech_style=style,
                        acknowledgement_kind="clarify" if asks else "reply",
                        asks_clarification=asks,
                        claims=claims,
                    ),
                    intent="conversation",
                )
        finally:
            self._model.set_system_prompt(previous)

        assert decision is not None
        del last_error
        reply = " ".join(str(decision.reply).split()).strip() or (
            "I'm here, but I couldn't form a clear reply just now."
        )

        tool_calls: list[dict[str, Any]] = []
        claims: list[DialogueClaimV1] = []
        for call in decision.tool_calls or []:
            name = str(getattr(call, "name", "") or "")
            args = dict(getattr(call, "arguments", {}) or {})
            if name == "get_weather" and weather_tool is not None and weather_mode == "normal":
                location = str(args.get("location") or profile_facts.get("home") or "")
                report = weather_tool(location)
                tool_calls.append(
                    {
                        "name": "get_weather",
                        "arguments": {"location": location},
                        "ok": True,
                        "result": report,
                    }
                )
                if "weather" not in reply.casefold() and report:
                    reply = f"I checked for {location or 'you'}: {report.split('] ', 1)[-1]}"
                claims.append(
                    DialogueClaimV1(
                        text=report[:400],
                        veracity="verified",
                        evidence_ref="tool:get_weather",
                    )
                )
            else:
                tool_calls.append(
                    {
                        "name": name or "unknown",
                        "arguments": args,
                        "ok": False,
                        "result": "unavailable",
                    }
                )

        asks = "?" in reply and any(
            w in reply.casefold()
            for w in ("which", "what", "could you", "can you repeat", "clarify", "mean")
        )
        if not claims:
            claims = _conservative_claims(reply, memory_window)

        intent = str(decision.intent or "conversation")
        return TurnResult(
            reply=reply[:2000],
            dialogue_act=_act(
                turn_id=turn_id,
                text=reply,
                speech_style=style,
                acknowledgement_kind="clarify" if asks else "reply",
                asks_clarification=asks,
                claims=claims,
            ),
            tool_calls=tool_calls,
            intent=intent,
        )


def measure_summarizer_quality(
    *,
    summary_text: str,
    used_fallback: bool,
    call_count: int,
    evidence_terms: Sequence[str] = ("offer", "interview", "monday", "friday"),
) -> dict[str, Any]:
    """Report-only metrics for a live Tier-2 summary (not CI-gating)."""

    lowered = summary_text.casefold()
    term_hits = {term: (term in lowered) for term in evidence_terms}
    return {
        "summary_text": summary_text,
        "summary_chars": len(summary_text),
        "summary_words": len(summary_text.split()),
        "used_fallback": bool(used_fallback),
        "summarizer_calls": int(call_count),
        "evidence_term_hits": term_hits,
        "durable_fact_coverage": sum(1 for hit in term_hits.values() if hit) / max(len(term_hits), 1),
        "contains_offer": bool(term_hits.get("offer")),
        "report_only": True,
    }
