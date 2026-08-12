"""Value-map evidence policy: match-scored paints, misses, evidence_count (card VS-3).

Why this module exists
----------------------
V-D was measured as a **no-op whose value map was running empty**
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §2.1(2)): the eval loop has no
camera, so the map was painted from the same oracle frustum grounding already
uses, by SUBSTRING match, with the floors ``0.15`` (nothing seen) and ``0.05``
(something seen that is not the query) at ``conf=1.0``. That is a
scanned-cone marker, not evidence — every look painted a positive value
whether or not anything relevant was there, and nothing ever recorded a MISS.
With no evidence in the map, a value-directed scorer cannot differ from the
baseline for any reason that has to do with the world.

What this module supplies
-------------------------
The evidence contract for one look:

* **value** comes from the QUERY-MATCH SCORE through the existing SigLIP
  seam (:class:`~parcel_robot.instructnav.siglip.SigLIP2Matcher`), multiplied
  by the observation's own confidence. Both factors are already ``[0, 1]``, and
  both matter: a certain detection of a poorly-matching label and an unsure
  detection of a perfect match are each weak evidence. The ``string_fallback``
  degrade is preserved untouched — with no weights loaded the matcher scores a
  substring hit 1.0 and everything else 0.0, exactly as it does today.
* **misses are painted.** A scanned cone containing no query-relevant evidence
  paints its best (low) match value with the same optical-axis confidence a hit
  carries, so looking somewhere and finding nothing LOWERS that region's value
  instead of raising it by a floor. There is no floor here, and no substring
  branch.
* **evidence_count** is the number of paints that actually carried
  query-relevant evidence. It is the number card VS-5's empty-map delegation
  keys on: ``evidence_count == 0`` must mean the map contains nothing that
  could move a decision, which is what makes "flag-on with no evidence is
  EXACTLY the baseline" provable rather than accidental (the E4 0-flip tie was
  an accident; §2.1(2) end).

Contract for the empty-map proof (frozen — VS-5 consumes it)
------------------------------------------------------------
``ValueEvidencePolicy.evidence_count`` counts PAINTS, not candidates, and
increments **iff** the paint's ``is_evidence`` is true, which happens **iff**
at least one observation in the cone matched the query at or above
:data:`~parcel_robot.instructnav.siglip.SIGLIP2_MATCH_THRESHOLD`. Background
looks and miss-only looks therefore leave it at zero, for any number of looks.

This module paints nothing itself: it returns tuples. ``value_map.py``,
``value_directed_scan.py`` and ``search_entity.py`` are the wiring card's
(VS-5) business and are untouched here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from parcel_robot.instructnav.siglip import SIGLIP2_MATCH_THRESHOLD, SigLIP2Matcher

__all__ = [
    "DOES_NOT_PROVE",
    "LOOK_CONFIDENCE",
    "EvidencePaint",
    "ObservationMatch",
    "ValueEvidenceConfig",
    "ValueEvidencePolicy",
    "match_observation",
    "paint_for_look",
]

#: Optical-axis confidence of one look. This is the map's own unit weight and
#: is exactly what the painter being replaced already passes to
#: ``paint_look(conf=...)``; a MISS is painted with the SAME weight as a hit so
#: that only the VALUE distinguishes them — the geometry of a look does not
#: depend on what was found in it.
LOOK_CONFIDENCE: float = 1.0

DOES_NOT_PROVE = (
    (
        "These cells prove the evidence policy: what a look is worth, when a look "
        "is a miss, and what evidence_count counts. They do not prove that the "
        "eval arms have a camera — in T0 the observations are the oracle frustum "
        "(record §2.1(2)), so the match scores exercised here are the "
        "string_fallback degrade unless a synthetic embedder is injected."
    ),
    (
        "Nothing here changes a scorer or a map. The empty-map == baseline claim "
        "is only made PROVABLE by this contract; proving it is card VS-5's gate "
        "on the full v4 minival."
    ),
    (
        "value = match_score x observation confidence is a policy choice, not a "
        "calibrated likelihood. It is monotone in both factors and bounded in "
        "[0, 1]; no probabilistic claim is made."
    ),
)


@dataclass(frozen=True, slots=True)
class ValueEvidenceConfig:
    """Frozen policy. The threshold is the SigLIP operating point, by reference."""

    match_threshold: float = SIGLIP2_MATCH_THRESHOLD
    look_confidence: float = LOOK_CONFIDENCE

    def __post_init__(self) -> None:
        if not 0.0 <= self.match_threshold <= 1.0:
            raise ValueError("match_threshold must be in [0, 1]")
        if not 0.0 < self.look_confidence <= 1.0:
            raise ValueError("look_confidence must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ObservationMatch:
    """One observation scored against the query."""

    label: str
    match_score: float
    confidence: float
    match_source: str
    is_evidence: bool

    @property
    def value(self) -> float:
        """Evidence strength of this observation, in ``[0, 1]``."""

        return self.match_score * self.confidence


@dataclass(frozen=True, slots=True)
class EvidencePaint:
    """The ``(value, conf, is_evidence)`` tuple for one look, plus provenance."""

    value: float
    conf: float
    is_evidence: bool
    match_score: float
    match_source: str
    label: str
    observations: int

    @property
    def is_miss(self) -> bool:
        """A scanned cone with no query-relevant evidence in it."""

        return not self.is_evidence

    def as_tuple(self) -> tuple[float, float, bool]:
        """The frozen paint tuple, in the order the record names it."""

        return (self.value, self.conf, self.is_evidence)


def match_observation(
    query: str,
    observation: Any,
    *,
    matcher: SigLIP2Matcher | None = None,
    config: ValueEvidenceConfig | None = None,
) -> ObservationMatch:
    """Score one observation against ``query`` through the embed seam.

    Accepts either the navigator's ``SemanticCandidate`` (``label`` /
    ``confidence``) or the contract ``DetectionMsg`` (``class_id`` / ``score``)
    — the one ingress, in both of its shapes.

    The raw match score is requested with an explicit ``threshold=0.0`` so a
    sub-threshold match still reports its true score instead of collapsing to
    "no match": a weak match is weak EVIDENCE, and painting it as such is the
    whole point. The evidence decision is then this module's own, taken at
    :attr:`ValueEvidenceConfig.match_threshold`.
    """

    cfg = config if config is not None else ValueEvidenceConfig()
    engine = matcher if matcher is not None else SigLIP2Matcher()
    label = _label_of(observation)
    confidence = _confidence_of(observation)
    match = engine.match(str(query), [label], threshold=0.0)
    score = _unit(float(match.score)) if match is not None else 0.0
    source = match.source if match is not None else "none"
    return ObservationMatch(
        label=label,
        match_score=score,
        confidence=confidence,
        match_source=source,
        is_evidence=score >= cfg.match_threshold,
    )


def paint_for_look(
    query: str,
    observations: Iterable[Any],
    *,
    matcher: SigLIP2Matcher | None = None,
    config: ValueEvidenceConfig | None = None,
) -> EvidencePaint:
    """The paint tuple for one look over ``observations`` (possibly empty).

    The look's value is its STRONGEST query-relevant evidence. An empty cone,
    or a cone holding only things that are not the query, paints a MISS: value
    at or near zero with full look confidence, which lowers the fused value of
    everything in the cone. No floor is applied, and no substring branch
    exists — that painter is what this replaces.
    """

    cfg = config if config is not None else ValueEvidenceConfig()
    engine = matcher if matcher is not None else SigLIP2Matcher()
    best: ObservationMatch | None = None
    count = 0
    for observation in observations:
        count += 1
        scored = match_observation(query, observation, matcher=engine, config=cfg)
        if best is None or scored.value > best.value:
            best = scored
    if best is None:
        return EvidencePaint(
            value=0.0,
            conf=cfg.look_confidence,
            is_evidence=False,
            match_score=0.0,
            match_source="none",
            label="",
            observations=0,
        )
    return EvidencePaint(
        value=_unit(best.value),
        conf=cfg.look_confidence,
        is_evidence=best.is_evidence,
        match_score=best.match_score,
        match_source=best.match_source,
        label=best.label,
        observations=count,
    )


class ValueEvidencePolicy:
    """Stateful ledger over one mission's looks: the ``evidence_count`` source.

    ``evidence_count`` is the contract card VS-5's empty-map delegation keys
    on. It counts PAINTS that carried query-relevant evidence, so a session
    that only ever looked at background — however many looks — reports zero and
    the flag-on scorer is provably the flag-off scorer.
    """

    def __init__(
        self,
        *,
        matcher: SigLIP2Matcher | None = None,
        config: ValueEvidenceConfig | None = None,
    ) -> None:
        self.config = config if config is not None else ValueEvidenceConfig()
        self.matcher = matcher if matcher is not None else SigLIP2Matcher()
        self._paints = 0
        self._evidence_paints = 0
        self._miss_paints = 0

    @property
    def evidence_count(self) -> int:
        """Number of query-relevant evidence paints. Zero == an empty map."""

        return self._evidence_paints

    @property
    def miss_count(self) -> int:
        return self._miss_paints

    @property
    def paint_count(self) -> int:
        return self._paints

    def reset(self) -> None:
        """Mission scope: a new search starts with an empty map."""

        self._paints = 0
        self._evidence_paints = 0
        self._miss_paints = 0

    def paint(self, query: str, observations: Iterable[Any]) -> EvidencePaint:
        """Score one look and record it in the ledger."""

        paint = paint_for_look(
            query, observations, matcher=self.matcher, config=self.config
        )
        self._paints += 1
        if paint.is_evidence:
            self._evidence_paints += 1
        else:
            self._miss_paints += 1
        return paint


def _label_of(observation: Any) -> str:
    label = getattr(observation, "label", None)
    if label is None:
        label = getattr(observation, "class_id", None)
    if label is None and isinstance(observation, str):
        label = observation
    return str(label or "")


def _confidence_of(observation: Any) -> float:
    value = getattr(observation, "confidence", None)
    if value is None:
        value = getattr(observation, "score", None)
    if value is None:
        return LOOK_CONFIDENCE
    return _unit(float(value))


def _unit(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("evidence values must be finite")
    return min(1.0, max(0.0, number))
