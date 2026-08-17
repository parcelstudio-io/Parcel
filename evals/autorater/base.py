"""AutoRater base interfaces, the judge backend protocol, and the registry.

Design rules, each of which exists because of a known LLM-judge failure mode:

1. **Position bias is measured, not assumed away.** An LLM judge shown the same
   pair twice, sides swapped, frequently prefers whichever it saw first. Every
   ``ComparativeAutoRater`` runs both orders and reports ``position_bias``; a
   verdict whose two orders disagree is reported, never silently averaged into
   a confident-looking number.
2. **Parsing is fail-closed.** A judge reply that is not strict JSON in the
   expected shape yields an abstention, never a default score. An unparseable
   judge has produced no evidence.
3. **Prompts are versioned.** ``rater_version`` changes whenever the prompt or
   the parse changes, because scores from two prompt versions are not
   comparable and a rating ledger that silently mixes them is worthless.
4. **Determinism where it is available.** Rule-based raters are exact and get
   no LLM at all. Reach for the model only where judgement is genuinely
   required.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from evals.autorater.types import (
    ComparativeVerdict,
    RatingRequest,
    Response,
    Side,
    SideMetric,
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class JudgeBackend(Protocol):
    """Minimal text-in/text-out contract a judge model must satisfy."""

    @property
    def model_id(self) -> str: ...

    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> str: ...


class JudgeError(RuntimeError):
    """The judge backend could not produce a reply at all."""


def parse_judge_json(reply: str) -> dict[str, Any]:
    """Extract the single JSON object from a judge reply, fail-closed.

    Judges wrap JSON in prose or fences no matter how firmly they are told not
    to, so one balanced-brace extraction is permitted. Anything beyond that
    raises: guessing at a malformed verdict is how a broken judge starts
    producing confident numbers.
    """

    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if match is None:
            raise ValueError(f"judge reply contained no JSON object: {reply[:200]!r}") from None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise ValueError(f"judge reply was not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise TypeError(f"judge reply was {type(payload).__name__}, expected an object")
    return payload


class AutoRater(ABC):
    """Common identity for every rater; scores are only comparable within one."""

    id: str = "autorater"
    version: str = "0"

    @property
    def fingerprint(self) -> str:
        return f"{self.id}@{self.version}"


class ComparativeAutoRater(AutoRater):
    """Base vs test, one signed score in [-1, +1].

    Subclasses implement :meth:`_judge_once`, which rates a single presentation
    order. This class owns the swap: it presents (base, test) and then
    (test, base), maps both back to the canonical sign, and reports the spread
    between them as ``position_bias``.
    """

    #: Both orders are run by default. Set False only for raters that are
    #: provably order-invariant (rule-based ones), never to save tokens.
    swap_orders: bool = True

    @abstractmethod
    def _judge_once(self, request: RatingRequest, *, first: Side) -> tuple[float, str, Mapping[str, float]]:
        """Rate one presentation order.

        Returns ``(score, rationale, per_criterion)`` where ``score`` is already
        canonical: negative favours base, positive favours test, regardless of
        which side was shown first.
        """

    def rate(self, request: RatingRequest) -> ComparativeVerdict:
        orders: list[Side] = ["base", "test"] if self.swap_orders else ["base"]
        scores: list[float] = []
        rationales: list[str] = []
        criteria: dict[str, float] = {}
        try:
            for first in orders:
                score, rationale, per_criterion = self._judge_once(request, first=first)
                scores.append(max(-1.0, min(1.0, float(score))))
                rationales.append(rationale.strip())
                for key, value in per_criterion.items():
                    criteria[key] = criteria.get(key, 0.0) + float(value) / len(orders)
        except (JudgeError, TypeError, ValueError) as error:
            return ComparativeVerdict(
                rater_id=self.id,
                rater_version=self.version,
                score=None,
                preference=None,
                rationale="",
                abstained=True,
                abstain_reason=f"{type(error).__name__}: {error}",
            )

        mean = sum(scores) / len(scores)
        bias = (max(scores) - min(scores)) if len(scores) > 1 else None
        return ComparativeVerdict(
            rater_id=self.id,
            rater_version=self.version,
            score=mean,
            preference=self.preference_for(mean),
            rationale=" | ".join(r for r in rationales if r),
            per_criterion=criteria,
            position_bias=bias,
            order_scores=tuple(scores),
        )

    #: Scores within this band of zero are reported as a tie rather than a
    #: direction. A judge asked for a winner will always name one; without a
    #: dead band every coin-flip becomes a recorded preference.
    tie_band: float = 0.1

    def preference_for(self, score: float) -> str:
        if abs(score) <= self.tie_band:
            return "tie"
        return "test" if score > 0 else "base"


class SideMetricAutoRater(AutoRater):
    """Measures one countable property of a single side."""

    metric_name: str = "metric"
    unit: str = "count"

    @abstractmethod
    def measure(self, response: Response, request: RatingRequest | None = None) -> SideMetric:
        """Measure this metric on one response."""

    def measure_both(self, request: RatingRequest) -> tuple[SideMetric, SideMetric]:
        return self.measure(request.base, request), self.measure(request.test, request)


class RaterRegistry:
    """Name -> rater lookup so a suite can be declared as config, not code."""

    def __init__(self) -> None:
        self._raters: dict[str, AutoRater] = {}

    def register(self, rater: AutoRater) -> AutoRater:
        if rater.id in self._raters:
            raise ValueError(f"duplicate rater id: {rater.id}")
        self._raters[rater.id] = rater
        return rater

    def get(self, rater_id: str) -> AutoRater:
        try:
            return self._raters[rater_id]
        except KeyError:
            known = ", ".join(sorted(self._raters)) or "(none registered)"
            raise KeyError(f"unknown rater {rater_id!r}; known: {known}") from None

    def ids(self) -> Sequence[str]:
        return tuple(sorted(self._raters))

    def __len__(self) -> int:
        return len(self._raters)
