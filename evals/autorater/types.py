"""Typed inputs and verdicts for conversation-quality AutoRaters.

Two rater shapes, deliberately separated because they answer different
questions and fail differently:

* **Comparative** — base vs test, "which side was better", one signed score.
  Susceptible to position bias, so the harness runs both orders (see
  ``base.ComparativeAutoRater``).
* **Side metric** — one side only, "how many punts did this side make".
  No comparison, no position bias, and countable without a second sample.

A rater may always **abstain**. An abstention is a first-class outcome, not a
tie and not a zero: a judge that cannot parse its own output has produced no
evidence, and averaging that into a score would launder a failure into a
measurement (the same rule the eval packs already apply to ``does_not_prove``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

Side = Literal["base", "test"]
Preference = Literal["base", "test", "tie"]

#: Verdict score bounds. Negative favours base, positive favours test.
SCORE_MIN = -1.0
SCORE_MAX = 1.0


def _frozen(mapping: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True, slots=True)
class Turn:
    """One utterance in a conversation.

    ``metadata`` carries whatever the producing run recorded — latency, tool
    calls, mission state, emote tags. Raters read it but never require it: a
    transcript captured without metadata must still be ratable.
    """

    role: Literal["owner", "robot", "system"]
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.role not in ("owner", "robot", "system"):
            raise ValueError(f"unknown turn role: {self.role!r}")
        object.__setattr__(self, "metadata", _frozen(self.metadata))


@dataclass(frozen=True, slots=True)
class Response:
    """One side of a comparison: a single reply *or* a multi-turn exchange.

    A single-response sample is just ``turns`` of length one. Keeping both in
    one type is deliberate — the alternative is two parallel rater hierarchies
    that drift, and most criteria (persona, honesty, punting) are identical
    whether the sample is one turn or six.
    """

    side: Side
    turns: tuple[Turn, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in ("base", "test"):
            raise ValueError(f"side must be 'base' or 'test', got {self.side!r}")
        if isinstance(self.turns, Turn):
            # `Response("base", (Turn(...)))` — a missing trailing comma is not
            # a tuple. Say so, rather than failing later on a TypeError.
            raise TypeError("turns must be a sequence of Turn; did you drop a trailing comma?")
        if not self.turns:
            raise ValueError("a response needs at least one turn")
        object.__setattr__(self, "turns", tuple(self.turns))
        object.__setattr__(self, "metadata", _frozen(self.metadata))

    @property
    def is_multi_turn(self) -> bool:
        return len(self.robot_turns) > 1

    @property
    def robot_turns(self) -> tuple[Turn, ...]:
        return tuple(turn for turn in self.turns if turn.role == "robot")

    def transcript(self) -> str:
        return "\n".join(f"{turn.role.upper()}: {turn.text}" for turn in self.turns)


@dataclass(frozen=True, slots=True)
class RatingRequest:
    """A base/test pair plus the shared context that produced them."""

    prompt: str
    base: Response
    test: Response
    context: tuple[Turn, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.base.side != "base" or self.test.side != "test":
            raise ValueError("RatingRequest requires a base-sided and a test-sided response")
        if not self.prompt.strip():
            raise ValueError("rating request needs the owner prompt that produced both sides")
        object.__setattr__(self, "context", tuple(self.context))
        object.__setattr__(self, "metadata", _frozen(self.metadata))

    def side(self, side: Side) -> Response:
        return self.base if side == "base" else self.test

    def context_transcript(self) -> str:
        if not self.context:
            return "(no prior conversation)"
        return "\n".join(f"{turn.role.upper()}: {turn.text}" for turn in self.context)


@dataclass(frozen=True, slots=True)
class ComparativeVerdict:
    """Which side was better, and by how much.

    ``score`` is signed and bounded: ``-1`` means base is decisively better,
    ``+1`` means test is, ``0`` is a genuine tie. ``abstained`` verdicts carry
    ``score = None`` — never 0.0, which would be indistinguishable from a tie.
    """

    rater_id: str
    rater_version: str
    score: float | None
    preference: Preference | None
    rationale: str
    per_criterion: Mapping[str, float] = field(default_factory=dict)
    abstained: bool = False
    abstain_reason: str = ""
    position_bias: float | None = None
    order_scores: tuple[float, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.abstained:
            if self.score is not None or self.preference is not None:
                raise ValueError("an abstained verdict carries no score or preference")
            if not self.abstain_reason.strip():
                raise ValueError("an abstention must say why")
        else:
            if self.score is None or self.preference is None:
                raise ValueError("a non-abstained verdict needs both a score and a preference")
            if not SCORE_MIN <= self.score <= SCORE_MAX:
                raise ValueError(f"score {self.score} outside [{SCORE_MIN}, {SCORE_MAX}]")
        object.__setattr__(self, "per_criterion", _frozen(self.per_criterion))
        object.__setattr__(self, "metadata", _frozen(self.metadata))
        object.__setattr__(self, "order_scores", tuple(self.order_scores))

    @property
    def is_decisive(self) -> bool:
        """True when the verdict survives its own position-bias check."""

        return (
            not self.abstained
            and self.preference != "tie"
            and (self.position_bias is None or self.position_bias < 1.0)
        )


@dataclass(frozen=True, slots=True)
class SideMetric:
    """A countable property of ONE side, e.g. number of punts.

    ``value`` is the headline number and ``per_turn`` records which turns
    contributed, so a count is always auditable back to the text that produced
    it rather than being an unexplained integer.
    """

    rater_id: str
    rater_version: str
    side: Side
    name: str
    value: float
    unit: str
    per_turn: tuple[Mapping[str, Any], ...] = ()
    abstained: bool = False
    abstain_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.abstained and not self.abstain_reason.strip():
            raise ValueError("an abstention must say why")
        if not self.abstained and self.value < 0:
            raise ValueError("side metrics are counts or rates and cannot be negative")
        object.__setattr__(self, "per_turn", tuple(_frozen(item) for item in self.per_turn))
        object.__setattr__(self, "metadata", _frozen(self.metadata))


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """The same side metric measured on both sides, plus the difference."""

    name: str
    base: SideMetric
    test: SideMetric

    @property
    def delta(self) -> float | None:
        """test - base. ``None`` if either side abstained."""

        if self.base.abstained or self.test.abstained:
            return None
        return self.test.value - self.base.value
