"""Novelty-scored *noticing* — the pure decision layer of a continuous looking loop.

Why this module exists (research H6, 2026-08-23)
------------------------------------------------
Today the camera path is told what to look for: an operator-configured query
batch, a 2 Hz ingress, a 16-phrase cap, and no signal anywhere that says *this
one is new*. A dog that "keeps learning about the world" needs the opposite
polarity — a loop that runs continuously and reports only the things that are
not already in its map. That report is a :class:`Noticing`.

The decision, in one line: a detection becomes a noticing when its crop
embedding is FAR from everything the running gallery already holds
(``novelty = 1 - max cosine``), it clears the quality gates, and the rate
limiter still has room.

What is deliberately NOT here
-----------------------------
No model, no socket, no numpy, no clock of its own. Every input — the
embedding, the detector score, the monotonic timestamp — is passed in, so the
whole policy is testable without a GPU and cannot drift with a driver. The
loop that produces detections lives in the H6 harness; the runtime wiring is a
milestone card, not this module. Nothing in the product imports this yet: it
is reachable only from research code and its capability test.

Why cosine against a bounded gallery, and not a "map"
------------------------------------------------------
The online map's entries are governed (consent, decay, provenance); a noticing
is a *pre-map* signal that fires before anything is written, so it keeps its
own bounded gallery of unit vectors. :data:`DEFAULT_GALLERY_LIMIT` caps it —
an unbounded gallery would make novelty monotonically decrease toward zero and
turn the loop silent after a long session, which is a failure mode that looks
exactly like "nothing is happening".

Honesty
-------
``novelty`` measures embedding distance, not importance. A new *view* of a
known object (different pose, different light) scores as novel and that is a
false noticing by the H6 measurement's own definition — the rate limiter and
the per-label cooldown are what keep it survivable, not the score. Calibrating
tau is an empirical question answered in
``research/20260823/noticing-loop-perception/RESULTS.md``, not a constant that
can be defended from first principles.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

__all__ = [
    "DEFAULT_COOLDOWN_S",
    "DEFAULT_GALLERY_LIMIT",
    "DEFAULT_MAX_PER_MINUTE",
    "DEFAULT_MIN_BOX_PIXELS",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_NOVELTY_TAU",
    "NOTICING_DOES_NOT_PROVE",
    "Noticing",
    "NoticingGate",
    "NoticingLoop",
    "NoticingStats",
    "NoveltyGallery",
    "Observation",
    "cosine",
    "unit",
]

#: Novelty above this admits a noticing. 1 - cos, so 0.35 means "less than 0.65
#: cosine to the closest thing already seen". Measured, not assumed: H6 sweeps
#: it and reports the AUC and the false-noticing rate at each value.
DEFAULT_NOVELTY_TAU = 0.35

#: Detector score floor. Below this the box is not worth embedding, never mind
#: reporting. Matches the OWLv2 default gate so the loop cannot notice things
#: the detector itself would not have published.
DEFAULT_MIN_SCORE = 0.1

#: Boxes smaller than this are refused: a crop of a few dozen pixels embeds to
#: noise, and noise is maximally novel — the single cheapest source of false
#: noticings there is.
DEFAULT_MIN_BOX_PIXELS = 32 * 32

#: Rate ceiling, per the H6 criterion of <= 1 false noticing per minute: the
#: loop may not emit more than this many noticings in any trailing 60 s.
DEFAULT_MAX_PER_MINUTE = 6

#: Per-label silence after a noticing. A person who stays in frame is one
#: noticing, not thirty per second.
DEFAULT_COOLDOWN_S = 5.0

#: Gallery ceiling (see module docstring — an unbounded gallery goes silent).
DEFAULT_GALLERY_LIMIT = 512

NOTICING_DOES_NOT_PROVE = (
    (
        "Novelty is embedding distance from a bounded gallery: a new VIEW of a known "
        "object scores novel. This module ranks and rate-limits; it does not decide "
        "that something is interesting, and it never gains authority over motion."
    ),
    (
        "The gallery is per-process and unpersisted. Restarting the loop makes the "
        "whole world new again — continuity across sessions is a memory card, not this."
    ),
)


def unit(vector: Sequence[float]) -> tuple[float, ...]:
    """L2-normalise, or return all-zeros for a zero/degenerate vector.

    A zero vector is kept as zeros rather than raising: an encoder that fails
    on one crop must degrade that crop, never kill the loop. Cosine against a
    zero vector is 0.0, so such a crop reads as maximally novel and is caught
    by the score/size gates instead of by a crash.
    """

    total = 0.0
    for value in vector:
        total += float(value) * float(value)
    if total <= 0.0 or not math.isfinite(total):
        return tuple(0.0 for _ in vector)
    norm = math.sqrt(total)
    return tuple(float(value) / norm for value in vector)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors of equal length (0.0 if either is zero)."""

    if len(left) != len(right):
        raise ValueError(f"vector length mismatch: {len(left)} vs {len(right)}")
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for a, b in zip(left, right, strict=True):
        dot += float(a) * float(b)
        left_sq += float(a) * float(a)
        right_sq += float(b) * float(b)
    if left_sq <= 0.0 or right_sq <= 0.0:
        return 0.0
    return dot / math.sqrt(left_sq * right_sq)


@dataclass(frozen=True, slots=True)
class Observation:
    """One detection offered to the loop, detector-agnostic and frame-stamped."""

    label: str
    score: float
    box: tuple[int, int, int, int]
    embedding: tuple[float, ...]
    monotonic_ns: int
    sequence: int = 0
    instance_key: str | None = None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("label must be non-empty")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be in [0, 1]")
        if len(self.box) != 4:
            raise ValueError("box must be (u0, v0, u1, v1)")
        u0, v0, u1, v1 = self.box
        if u1 <= u0 or v1 <= v0:
            raise ValueError("box must have positive extent")

    @property
    def box_pixels(self) -> int:
        u0, v0, u1, v1 = self.box
        return int((u1 - u0) * (v1 - v0))


@dataclass(frozen=True, slots=True)
class Noticing:
    """One thing the loop decided is worth reporting. Pure evidence, no authority.

    ``novelty`` is ``1 - max cosine`` against the gallery AT THE MOMENT of the
    decision, and ``nearest_cosine`` is that cosine, kept so a reader can tell
    "nothing like this at all" (cosine ~0) from "close, but past tau" without
    re-deriving it. ``gallery_size`` is the denominator of that claim: a
    noticing against an empty gallery is trivially novel and says so.
    """

    label: str
    score: float
    box: tuple[int, int, int, int]
    novelty: float
    nearest_cosine: float
    gallery_size: int
    monotonic_ns: int
    sequence: int
    instance_key: str | None = None

    @property
    def first_ever(self) -> bool:
        """True when the gallery was empty — the loop had nothing to compare to."""

        return self.gallery_size == 0


@dataclass(frozen=True, slots=True)
class NoticingGate:
    """The tunable policy. Frozen so a run cannot retune itself mid-measurement."""

    novelty_tau: float = DEFAULT_NOVELTY_TAU
    min_score: float = DEFAULT_MIN_SCORE
    min_box_pixels: int = DEFAULT_MIN_BOX_PIXELS
    max_per_minute: int = DEFAULT_MAX_PER_MINUTE
    cooldown_s: float = DEFAULT_COOLDOWN_S
    gallery_limit: int = DEFAULT_GALLERY_LIMIT

    def __post_init__(self) -> None:
        if not 0.0 <= self.novelty_tau <= 1.0:
            raise ValueError("novelty_tau must be in [0, 1]")
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score must be in [0, 1]")
        if self.min_box_pixels < 0:
            raise ValueError("min_box_pixels must be >= 0")
        if self.max_per_minute < 0:
            raise ValueError("max_per_minute must be >= 0")
        if self.cooldown_s < 0.0:
            raise ValueError("cooldown_s must be >= 0")
        if self.gallery_limit < 1:
            raise ValueError("gallery_limit must be >= 1")


@dataclass
class NoticingStats:
    """Why the loop stayed quiet — every rejection is counted, never silent."""

    observations: int = 0
    noticings: int = 0
    rejected_score: int = 0
    rejected_size: int = 0
    rejected_familiar: int = 0
    rejected_cooldown: int = 0
    rejected_rate_limit: int = 0
    gallery_admits: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "observations": self.observations,
            "noticings": self.noticings,
            "rejected_score": self.rejected_score,
            "rejected_size": self.rejected_size,
            "rejected_familiar": self.rejected_familiar,
            "rejected_cooldown": self.rejected_cooldown,
            "rejected_rate_limit": self.rejected_rate_limit,
            "gallery_admits": self.gallery_admits,
        }


class NoveltyGallery:
    """Bounded FIFO of unit vectors — the loop's running "what I have seen".

    Kept deliberately dumb (no clustering, no decay): the H6 question is
    whether raw cosine novelty separates new from seen at all. Anything
    cleverer would confound the measurement with the cleverness.
    """

    def __init__(self, limit: int = DEFAULT_GALLERY_LIMIT) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = int(limit)
        self._vectors: deque[tuple[float, ...]] = deque(maxlen=int(limit))

    def __len__(self) -> int:
        return len(self._vectors)

    @property
    def limit(self) -> int:
        return self._limit

    def add(self, vector: Sequence[float]) -> None:
        normalised = unit(vector)
        if any(normalised):
            self._vectors.append(normalised)

    def nearest_cosine(self, vector: Sequence[float]) -> float:
        """Highest cosine to anything held, or 0.0 when the gallery is empty."""

        probe = unit(vector)
        if not any(probe) or not self._vectors:
            return 0.0
        best = -1.0
        for held in self._vectors:
            if len(held) != len(probe):
                continue
            best = max(best, cosine(probe, held))
        return max(best, 0.0)

    def novelty(self, vector: Sequence[float]) -> float:
        """``1 - max cosine``, clamped to [0, 1]."""

        return min(1.0, max(0.0, 1.0 - self.nearest_cosine(vector)))


@dataclass
class NoticingLoop:
    """Stateful policy: observations in, noticings out, everything else counted.

    One instance per looking session. Not thread-safe by design — the caller
    that owns the camera cadence owns this object, and adding a lock here would
    invite a producer to share it across threads it does not order.
    """

    gate: NoticingGate = field(default_factory=NoticingGate)
    gallery: NoveltyGallery = field(default=None)  # type: ignore[assignment]
    stats: NoticingStats = field(default_factory=NoticingStats)
    _recent: deque[int] = field(default_factory=deque, init=False, repr=False)
    _last_by_label: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.gallery is None:
            self.gallery = NoveltyGallery(self.gate.gallery_limit)

    def observe(self, observation: Observation) -> Noticing | None:
        """Score one detection; return a :class:`Noticing` when it clears every gate.

        The gallery is updated for every observation that passes the QUALITY
        gates, whether or not it is reported: what the loop has looked at is
        what it has seen, and a rate-limited frame must not make the world
        permanently new again.
        """

        self.stats.observations += 1
        if float(observation.score) < self.gate.min_score:
            self.stats.rejected_score += 1
            return None
        if observation.box_pixels < self.gate.min_box_pixels:
            self.stats.rejected_size += 1
            return None

        nearest = self.gallery.nearest_cosine(observation.embedding)
        novelty = min(1.0, max(0.0, 1.0 - nearest))
        gallery_size = len(self.gallery)
        self.gallery.add(observation.embedding)
        self.stats.gallery_admits += 1

        if novelty <= self.gate.novelty_tau:
            self.stats.rejected_familiar += 1
            return None
        if self._in_cooldown(observation):
            self.stats.rejected_cooldown += 1
            return None
        if self._rate_limited(observation.monotonic_ns):
            self.stats.rejected_rate_limit += 1
            return None

        self._recent.append(int(observation.monotonic_ns))
        self._last_by_label[observation.label] = int(observation.monotonic_ns)
        self.stats.noticings += 1
        return Noticing(
            label=observation.label,
            score=float(observation.score),
            box=tuple(observation.box),  # type: ignore[arg-type]
            novelty=novelty,
            nearest_cosine=nearest,
            gallery_size=gallery_size,
            monotonic_ns=int(observation.monotonic_ns),
            sequence=int(observation.sequence),
            instance_key=observation.instance_key,
        )

    def observe_frame(self, observations: Iterable[Observation]) -> list[Noticing]:
        """Score a whole frame in order, returning the noticings it produced."""

        out: list[Noticing] = []
        for observation in observations:
            noticing = self.observe(observation)
            if noticing is not None:
                out.append(noticing)
        return out

    def novelty_of(self, observation: Observation) -> float:
        """Novelty this observation WOULD score, with no state change.

        Exists for calibration (the AUC row): scoring a sweep must not be able
        to alter the gallery the loop under test is using.
        """

        return self.gallery.novelty(observation.embedding)

    def _in_cooldown(self, observation: Observation) -> bool:
        last = self._last_by_label.get(observation.label)
        if last is None:
            return False
        elapsed_s = (int(observation.monotonic_ns) - last) / 1e9
        return elapsed_s < self.gate.cooldown_s

    def _rate_limited(self, monotonic_ns: int) -> bool:
        cutoff = int(monotonic_ns) - 60_000_000_000
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()
        return len(self._recent) >= self.gate.max_per_minute
