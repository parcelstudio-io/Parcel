"""Two live proposers, so "not fit" and "not wired" can be told apart.

MEASURED FIRST, THEN BUILT
---------------------------
``owner_model.distiller.LanguageModelFactProposer`` calls
``LanguageModel.decide(prompt, [], [])`` and then looks for a JSON **array** in
``decision.reply``. Every ``LanguageModel`` in this tree is
``providers.LlamaCppProvider``, whose ``decide`` pins
``response_format={"type": "json_object", "schema": _decision_response_schema(...)}``
— the AgentDecision schema, whose ``reply`` is a conversational STRING. Asked
for owner facts, the shipped seam returns:

    "I have noted that your sister's name is Hana, she lives two streets away,
     and you prefer short answers before you have your coffee."

which is a good answer to the wrong question. ``_parse_candidates`` finds no
``[`` and returns ``[]``, and the proposer degrades to the deterministic one —
correctly, silently, and every single time. So a "live proposer" arm run through
the product seam measures the regex proposer with extra latency.

:class:`ChatFactProposer` is the research-side control: the SAME model, the same
prompt, asked through a plain chat completion with no AgentDecision schema, so
the reply may be the JSON array the contract wants. It implements the product's
``FactProposer`` protocol and its output is parsed by the product's own
``_parse_candidates``, so the only thing that differs from the shipped path is
the request. That isolates the question the DESIGN's refutation clause asks:
is the local model unfit to distil, or was it never asked properly?

It is deliberately NOT a product module. Fixing the seam is a milestone card
with a real decision in it (a second constrained response schema, or a
free-form call with a parser); this file exists to tell whoever writes that card
which of the two problems they have.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.owner_model.distiller import (
    MAX_FACTS_PER_PASS,
    DeterministicFactProposer,
    FactCandidate,
    _parse_candidates,
)

logger = logging.getLogger(__name__)

#: The shipped prompt's instruction, restated as a system message. Same content
#: as ``owner_model.distiller._LM_PROMPT`` so the comparison is about the
#: REQUEST SHAPE and not about prompt wording.
SYSTEM = (
    "You keep a small profile of a robot dog's owner. Read the conversation "
    "turns the user sends and list ONLY durable facts about the OWNER that they "
    "stated themselves — names, preferences, routines, places. Do not infer, do "
    "not guess, and do not include anything the robot said. If there is nothing "
    "durable, reply with an empty list.\n"
    'Reply with ONLY a JSON array of objects: [{"key": "sister_name", '
    '"value": "their sister is called Hana", "confidence": 0.9}]\n'
    'The "value" is the sentence the robot would say back, in the third person.'
)

#: A JSON-schema the server converts to a grammar. An array is not a valid
#: top-level ``json_object`` for every llama.cpp build, so the array is wrapped
#: in an object with one key and unwrapped on the way out.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "maxItems": MAX_FACTS_PER_PASS,
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["key", "value"],
            },
        }
    },
    "required": ["facts"],
}


@dataclass
class ChatFactProposer:
    """The same model, asked for the array the shipped parser wants.

    ``constrained`` selects between a plain chat completion (the model may wrap
    the array in prose; ``_parse_candidates`` tolerates that) and a
    schema-constrained one. Both are measured, because "the model can do it if
    you grammar-constrain it" and "the model does it when asked in words" are
    different claims about fitness.
    """

    base_url: str
    model: str
    timeout: float = 180.0
    temperature: float = 0.0
    top_p: float = 0.9
    max_tokens: int = 512
    constrained: bool = True
    owner_speakers: frozenset[str] = frozenset({"owner", "user"})
    fallback: DeterministicFactProposer = field(default_factory=DeterministicFactProposer)
    #: Measured, not assumed: how often this proposer had to fall back.
    calls: int = 0
    fallbacks: int = 0
    failures: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]:
        lines: list[str] = []
        for turn in turns:
            speaker = str(turn.get("speaker") or turn.get("role") or "").strip().lower()
            text = " ".join(str(turn.get("content") or turn.get("text") or "").split())
            if not text:
                continue
            who = "owner" if speaker in self.owner_speakers else "robot"
            lines.append(f"{who}: {text}")
        if not lines:
            return ()
        self.calls += 1
        try:
            reply = self._chat("Turns:\n" + "\n".join(lines))
        except Exception as error:
            # Degrade exactly as the product proposer does — never break the
            # caller — but record WHY, because a silent total degrade is the
            # defect this module exists to measure.
            logger.exception("chat fact proposer failed; using the offline one")
            self.failures.append(str(error))
            self.fallbacks += 1
            return self.fallback(turns)
        self.replies.append(reply[:2000])
        payload = _parse_candidates(self._unwrap(reply))
        if not payload:
            self.fallbacks += 1
            return self.fallback(turns)
        return payload[:MAX_FACTS_PER_PASS]

    def _unwrap(self, reply: str) -> str:
        """``{"facts": [...]}`` -> ``[...]``; anything else passes through."""

        text = reply.strip()
        if not self.constrained:
            return text
        try:
            body = json.loads(text)
        except (TypeError, ValueError):
            return text
        if isinstance(body, Mapping) and isinstance(body.get("facts"), list):
            return json.dumps(body["facts"])
        return text

    def _chat(self, user: str) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": False,
            # The product's own inference policy, copied verbatim from
            # ``LlamaCppProvider.decide``: this server runs with
            # ``--reasoning auto --reasoning-format deepseek``, and without these
            # two keys gemma spends the whole token budget in
            # ``reasoning_content`` and returns ``content: ""`` with
            # ``finish_reason: "length"``. Measured. Keeping them identical is
            # what makes this a comparison of RESPONSE SHAPE and nothing else.
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
        }
        if self.constrained:
            payload["response_format"] = {"type": "json_object", "schema": RESPONSE_SCHEMA}
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("chat completion returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("chat completion returned empty content")
        return content.strip()

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "fallbacks": self.fallbacks,
            "fallback_rate": round(self.fallbacks / self.calls, 4) if self.calls else 0.0,
            "failures": self.failures[:5],
            "sample_reply": self.replies[0] if self.replies else "",
            "constrained": self.constrained,
        }


@dataclass
class InstrumentedSeamProposer:
    """The SHIPPED ``LanguageModelFactProposer``, counting its own degrades.

    Wraps rather than replaces: the product object does the work, and this only
    records whether the reply it got could ever have parsed. Without the count,
    a live arm and a deterministic arm produce identical rows and the report
    cannot say why.
    """

    inner: Any
    calls: int = 0
    parsed: int = 0
    replies: list[str] = field(default_factory=list)

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]:
        self.calls += 1
        lines = [
            f"{'owner' if str(t.get('speaker') or t.get('role') or '').lower() in {'owner', 'user'} else 'robot'}: "
            f"{' '.join(str(t.get('content') or t.get('text') or '').split())}"
            for t in turns
            if str(t.get("content") or t.get("text") or "").strip()
        ]
        if lines:
            from parcel_robot.owner_model.distiller import _LM_PROMPT

            try:
                decision = self.inner.model.decide(_LM_PROMPT + "\n".join(lines), [], [])
                reply = str(decision.reply)
                self.replies.append(reply[:2000])
                if _parse_candidates(reply):
                    self.parsed += 1
            except Exception as error:
                logger.exception("seam proposer observation failed")
                self.replies.append(f"<error: {error}>")
        return self.inner(turns)

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "replies_parseable_as_fact_array": self.parsed,
            "degrade_rate": round(1.0 - (self.parsed / self.calls), 4) if self.calls else 0.0,
            "sample_reply": self.replies[0] if self.replies else "",
        }


__all__ = ["RESPONSE_SCHEMA", "SYSTEM", "ChatFactProposer", "InstrumentedSeamProposer"]
