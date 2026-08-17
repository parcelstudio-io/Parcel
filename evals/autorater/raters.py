"""Concrete AutoRaters and the judge backends they run on."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from evals.autorater import prompts as P
from evals.autorater.base import (
    ComparativeAutoRater,
    JudgeBackend,
    JudgeError,
    RaterRegistry,
    SideMetricAutoRater,
    parse_judge_json,
)
from evals.autorater.types import (
    RatingRequest,
    Response,
    Side,
    SideMetric,
)

# ---------------------------------------------------------------------------
# Judge backends
# ---------------------------------------------------------------------------


@dataclass
class LlamaCppJudge:
    """OpenAI-compatible llama.cpp server, as the reasoner stack already uses.

    Temperature defaults to 0.0: a judge that disagrees with itself between runs
    cannot support a ledger, and sampling diversity buys nothing when the output
    is a bounded verdict object.
    """

    base_url: str = "http://127.0.0.1:8090"
    model: str = "qwen3-32b-judge"
    timeout: float = 120.0
    temperature: float = 0.0
    _last_usage: dict[str, Any] = field(default_factory=dict, init=False)

    @property
    def model_id(self) -> str:
        return self.model

    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            # Qwen3 exposes a thinking mode; a judge returning a bounded JSON
            # verdict does not need it, and it triples latency per rating.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as stream:
                body = json.loads(stream.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise JudgeError(f"judge backend unreachable at {self.base_url}: {error}") from error
        except json.JSONDecodeError as error:
            raise JudgeError(f"judge returned non-JSON envelope: {error}") from error
        try:
            self._last_usage = body.get("usage") or {}
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise JudgeError(f"judge envelope missing choices/message: {error}") from error


@dataclass
class ScriptedJudge:
    """Deterministic backend for tests: replies are looked up, never generated."""

    replies: list[str]
    model_id_value: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list, init=False)

    @property
    def model_id(self) -> str:
        return self.model_id_value

    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        self.calls.append((system, user))
        if not self.replies:
            raise JudgeError("scripted judge exhausted")
        return self.replies.pop(0)


# ---------------------------------------------------------------------------
# Comparative raters
# ---------------------------------------------------------------------------


class _PromptedComparativeRater(ComparativeAutoRater):
    """Shared machinery: render a rubric, parse a winner, canonicalise the sign."""

    template: str = P.PAIRWISE_QUALITY
    max_tokens: int = 512

    def __init__(self, backend: JudgeBackend) -> None:
        self.backend = backend

    def _render(self, request: RatingRequest, *, first: Side) -> str:
        second: Side = "test" if first == "base" else "base"
        return self.template.format(
            prompt=request.prompt,
            context=request.context_transcript(),
            first_transcript=request.side(first).transcript(),
            second_transcript=request.side(second).transcript(),
        )

    def _judge_once(
        self, request: RatingRequest, *, first: Side
    ) -> tuple[float, str, Mapping[str, float]]:
        reply = self.backend.complete(
            P.JUDGE_SYSTEM, self._render(request, first=first), max_tokens=self.max_tokens
        )
        payload = parse_judge_json(reply)

        winner = str(payload.get("winner", "")).strip().lower()
        if winner not in ("a", "b", "tie"):
            raise ValueError(f"judge returned unknown winner {winner!r}")
        try:
            margin = float(payload.get("margin", 0.0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"judge returned non-numeric margin: {error}") from error
        margin = max(0.0, min(1.0, margin))

        # "A" is whichever side was shown first. Map back to the canonical
        # sign so both presentation orders are directly comparable.
        if winner == "tie":
            raw = 0.0
        else:
            winning_side: Side = first if winner == "a" else ("test" if first == "base" else "base")
            raw = margin if winning_side == "test" else -margin

        criteria: dict[str, float] = {}
        for key, value in (payload.get("criteria") or {}).items():
            try:
                numeric = max(-1.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
            # Criterion signs follow the same A/B convention as the winner.
            criteria[str(key)] = numeric if first == "base" else -numeric

        rationale = str(payload.get("rationale", "")).strip()
        return raw, rationale, criteria


class PairwiseQualityRater(_PromptedComparativeRater):
    """Overall "which response served the owner better"."""

    id = "pairwise_quality"
    version = "1"
    template = P.PAIRWISE_QUALITY


class HonestyRater(_PromptedComparativeRater):
    """Truthfulness and groundedness only — the fault class that matters most."""

    id = "honesty_groundedness"
    version = "1"
    template = P.HONESTY_GROUNDEDNESS


class PersonaConsistencyRater(_PromptedComparativeRater):
    """Does it sound like the companion, or like a status printout?"""

    id = "persona_consistency"
    version = "1"
    template = P.PERSONA_CONSISTENCY


class MultiTurnCoherenceRater(_PromptedComparativeRater):
    """Context retention and follow-through across a multi-turn exchange."""

    id = "multi_turn_coherence"
    version = "1"
    template = P.MULTI_TURN_COHERENCE


# ---------------------------------------------------------------------------
# Side metrics
# ---------------------------------------------------------------------------

#: Phrases the shipped stack emits when it gives up. These are literal strings
#: from the codebase, not guesses: `agent.py`'s unrecognised-command reply and
#: the filler/refusal families. A rule rater is exact and free, so it runs even
#: when no judge model is provisioned.
PUNT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bi did not understand that command\b", "shipped unrecognised-command reply"),
    (r"\bi don'?t (?:know|understand) how\b", "explicit inability"),
    (r"\bi'?m not (?:able|sure how) to\b", "explicit inability"),
    (r"\bi (?:can'?t|cannot) help with that\b", "bare refusal"),
    (r"\bsorry,? i (?:can'?t|don'?t)\b", "bare apology refusal"),
    (r"\bi'?m not sure what you mean\b", "non-specific confusion"),
)

#: A punt phrase followed by a concrete offer is NOT a punt: it advances the
#: exchange. Checked per turn, after a pattern hits.
PUNT_RESCUE = re.compile(
    r"\b(?:but|however|instead|though)\b|\bi can\b|\bwould you like\b|\bwhich\b|\?",
    re.IGNORECASE,
)


class RulePuntRater(SideMetricAutoRater):
    """Deterministic punt counter — exact, free, and needs no judge model.

    Catches the shipped literal phrasings. It cannot catch a novel punt a
    generative talker invents, which is what :class:`LLMPuntRater` is for; run
    both and treat a gap between them as a prompt-coverage signal.
    """

    id = "punts_rule"
    version = "1"
    metric_name = "punts"
    unit = "count"

    def measure(self, response: Response, request: RatingRequest | None = None) -> SideMetric:
        hits: list[dict[str, Any]] = []
        for index, turn in enumerate(response.robot_turns):
            text = turn.text.strip()
            for pattern, why in PUNT_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match is None:
                    continue
                if PUNT_RESCUE.search(text[match.end() :]):
                    break  # declined, then offered a way forward: not a punt
                hits.append({"index": index, "quote": match.group(0), "why": why})
                break
        return SideMetric(
            rater_id=self.id,
            rater_version=self.version,
            side=response.side,
            name=self.metric_name,
            value=float(len(hits)),
            unit=self.unit,
            per_turn=tuple(hits),
            metadata={"robot_turns": len(response.robot_turns)},
        )


class LLMPuntRater(SideMetricAutoRater):
    """Judge-scored punt count, for phrasings no rule anticipates."""

    id = "punts_llm"
    version = "1"
    metric_name = "punts"
    unit = "count"

    def __init__(self, backend: JudgeBackend) -> None:
        self.backend = backend

    def measure(self, response: Response, request: RatingRequest | None = None) -> SideMetric:
        rendered = P.PUNT_DETECTION.format(
            prompt=request.prompt if request else "(not supplied)",
            context=request.context_transcript() if request else "(none)",
            side=response.side,
            transcript=response.transcript(),
        )
        try:
            payload = parse_judge_json(
                self.backend.complete(P.JUDGE_SYSTEM, rendered, max_tokens=768)
            )
            count = int(payload["punts"])
            if count < 0:
                raise ValueError("negative punt count")
        except (JudgeError, ValueError, KeyError, TypeError) as error:
            return SideMetric(
                rater_id=self.id,
                rater_version=self.version,
                side=response.side,
                name=self.metric_name,
                value=0.0,
                unit=self.unit,
                abstained=True,
                abstain_reason=f"{type(error).__name__}: {error}",
            )
        turns = tuple(dict(item) for item in (payload.get("turns") or []) if isinstance(item, dict))
        return SideMetric(
            rater_id=self.id,
            rater_version=self.version,
            side=response.side,
            name=self.metric_name,
            value=float(count),
            unit=self.unit,
            per_turn=turns,
            metadata={"robot_turns": len(response.robot_turns)},
        )


def default_registry(backend: JudgeBackend | None = None) -> RaterRegistry:
    """Every rater that needs no model, plus the judged ones when a backend exists."""

    registry = RaterRegistry()
    registry.register(RulePuntRater())
    if backend is not None:
        for rater in (
            PairwiseQualityRater(backend),
            HonestyRater(backend),
            PersonaConsistencyRater(backend),
            MultiTurnCoherenceRater(backend),
            LLMPuntRater(backend),
        ):
            registry.register(rater)
    return registry
